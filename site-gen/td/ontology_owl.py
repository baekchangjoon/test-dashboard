"""S05 OWL 온톨로지(설계 §6.5 S05, §13.4, §13.5, §13.9 "입력 해시 안정성", REQ-018/022/024/061).

흐름:
  1. 결정적 골격(`skeleton`): S03 jQA JSON + S02 정제 bbtg -> rdflib Graph. LLM을 쓰지 않는다.
     - Entity, DTO, REST 자원 경로마다 `owl:Class`, 엔티티 연관마다 `owl:ObjectProperty`, 엔티티 필드마다
       `owl:DatatypeProperty`, REST 엔드포인트마다 `owl:NamedIndividual`(자원 클래스의 개체).
     - 모든 용어에 provenance `td:fromJqa "<jQA 노드 id>"`와 `td:kind`가 있다. 이름공간은 일반 값
       `http://test-dashboard.local/ontology#`(SUT 이름 없음)이다.
     - 연관 이름: jQA `references` 간선(원본 -> 대상)마다 원본 엔티티의 연관 필드를 찾는다. (1) 필드 타입이 대상 클래스이면
       그 필드, (2) 아니면 bbtg `derive-test-data`의 관계(대상 이름, 관계 종류)와 같은 애노테이션을 가진 필드가 하나뿐이면
       그 필드, (3) 그래도 없으면 `<원본>_to_<대상>`이라는 일반 이름을 쓴다.
  2. LLM 보강(`enrich`): 골격 + 정제 bbtg 번들(`S05/bundle/`, `td.bundle build --arm owlgen`이 A1 검사·서명)을
     `pipeline/lib/llm.sh`로 보내고, Turtle 추가분(영어 `rdfs:label@en`, `rdfs:comment`, 속성 특성, OWL 제한)을 받는다.
     추가분은 골격의 기존 용어(또는 `owl:Restriction` 빈 노드)만 설명할 수 있고 provenance(`td:` 주석)와 domain/range를
     쓸 수 없다(`merge_additions`). 파싱 실패, 계약 위반, SHACL 위반은 오류 문구와 직전 출력만으로 최대 2회 수리한다.
     claude 응답 자체의 오류(llm.sh 비-0)는 수리하지 않고 실패다.
  3. 스냅샷: `ontology/generated/<sut>/<inputKey8>/{ontology-owl.ttl, _COMPLETE}`. 입력 키(전체 64자)는
     sha256({번들 해시, 생성·수리 프롬프트 해시, shapes 해시, 모델, 수리 상한})이다. 번들에 골격(= jQA JSON + bbtg의 결정적
     함수)과 정제 bbtg가 들어 있으므로 REQ-024의 "jQA JSON + 정제 bbtg + 프롬프트" 키를 덮는다. S06과 같은 규칙
     (`td.snapshot`: 임시 디렉터리에서 검증 -> `_COMPLETE` -> 원자적 rename, `.reserve/` 예약, 변조 스냅샷은 failed)이다.
  4. 출력: `S05/ontology-owl.ttl`(스냅샷과 바이트 동일, S06 owl arm 번들 입력), `S05/ontology-owl.json`(온톨로지 JSON
     스키마, S04 owl.html 입력), `S05/owl-gen.json`(`owl-gen.schema.json`), `S05/skeleton.ttl`, `S05/bundle/`.

CLI: python -m td.ontology_owl stage --run-dir D --sut-file F --sut-src S   (stdout: {status, reason, outputs, extra})
     python -m td.ontology_owl skeleton <ontology-jqa.json> <bbtg clean dir> <out.ttl>
     python -m td.ontology_owl validate <ttl>                                  (conforms면 0)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import rdflib
from rdflib import BNode, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from td import snapshot

TD = Namespace("http://test-dashboard.local/ontology#")
ONTOLOGY_IRI = URIRef("http://test-dashboard.local/ontology")
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
MAX_REPAIRS = 2
TTL_NAME = "ontology-owl.ttl"
ERROR_TEXT_LIMIT = 12000
PREFIX_HEADER = (f"@prefix td: <{TD}> .\n@prefix owl: <{OWL}> .\n@prefix rdf: <{RDF}> .\n"
                 f"@prefix rdfs: <{RDFS}> .\n@prefix xsd: <{XSD}> .\n")

ASSOCIATIONS = ("OneToMany", "ManyToOne", "ManyToMany", "OneToOne")
ANNOTATION_PROPERTIES = ("fromJqa", "kind", "javaType", "annotation", "jpaRelation", "httpMethod", "path", "handler",
                         "anyMethod", "requestBody", "relatedEntity")
_XSD_BY_JAVA = {
    "int": XSD.integer, "java.lang.Integer": XSD.integer, "long": XSD.integer, "java.lang.Long": XSD.integer,
    "short": XSD.integer, "java.lang.Short": XSD.integer, "java.math.BigInteger": XSD.integer,
    "double": XSD.double, "java.lang.Double": XSD.double, "float": XSD.double, "java.lang.Float": XSD.double,
    "java.math.BigDecimal": XSD.decimal, "boolean": XSD.boolean, "java.lang.Boolean": XSD.boolean,
    "java.lang.String": XSD.string, "char": XSD.string, "java.lang.Character": XSD.string,
    "java.time.LocalDate": XSD.date, "java.time.LocalDateTime": XSD.dateTime, "java.time.OffsetDateTime": XSD.dateTime,
    "java.time.Instant": XSD.dateTime, "java.time.ZonedDateTime": XSD.dateTime, "java.util.Date": XSD.dateTime,
    "java.time.LocalTime": XSD.time, "java.util.UUID": XSD.string,
}
# 추가분 계약(merge_additions): 허용 술어와 rdf:type 값
_RESTRICTION_PREDICATES = {OWL.onProperty, OWL.minCardinality, OWL.maxCardinality, OWL.cardinality,
                           OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue, OWL.onClass, OWL.onDataRange,
                           OWL.qualifiedCardinality, OWL.minQualifiedCardinality, OWL.maxQualifiedCardinality}
ALLOWED_PREDICATES = {RDF.type, RDFS.label, RDFS.comment, RDFS.subClassOf, OWL.inverseOf, OWL.disjointWith} \
    | _RESTRICTION_PREDICATES
ALLOWED_TYPES = {OWL.FunctionalProperty, OWL.InverseFunctionalProperty, OWL.SymmetricProperty, OWL.AsymmetricProperty,
                 OWL.TransitiveProperty, OWL.IrreflexiveProperty, OWL.ReflexiveProperty, OWL.Restriction}
_STANDARD_NAMESPACES = (str(OWL), str(RDF), str(RDFS), str(XSD))


class OwlGenError(RuntimeError):
    """S05를 실패로 만드는 오류(사유 문자열)."""


# --- 1. 결정적 골격 -----------------------------------------------------------------------------------
def load_bbtg(clean_dir) -> dict:
    """정제 bbtg 디렉터리 -> {skill 이름: JSON}. 없으면 빈 dict."""
    clean_dir = Path(clean_dir)
    if not clean_dir.is_dir():
        return {}
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(clean_dir.glob("*.json"))}


def _bbtg_relations(bbtg: dict) -> dict[str, list[tuple[str, str]]]:
    """bbtg derive-test-data의 엔티티 관계: 클래스 단순 이름 -> [(대상 단순 이름, 관계 종류)]."""
    relations: dict[str, list[tuple[str, str]]] = {}
    for result in (bbtg.get("derive-test-data") or {}).get("results") or []:
        data = result.get("data") if isinstance(result, dict) else None
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict) or not item.get("class_name"):
                continue
            for relation in item.get("relations") or []:
                if isinstance(relation, dict) and relation.get("target") and relation.get("type"):
                    relations.setdefault(str(item["class_name"]), []).append((str(relation["target"]), str(relation["type"])))
    return relations


def _simple(fqn: str) -> str:
    return fqn.rsplit(".", 1)[-1]


def _sanitize(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    return cleaned if cleaned and not cleaned[0].isdigit() else f"n_{cleaned}"


class _Names:
    """IRI 지역 이름 할당(결정적: 호출 순서가 정렬돼 있으면 결과도 같다). 겹치면 `_2`, `_3`."""

    def __init__(self):
        self.used: set[str] = set()

    def take(self, wanted: str) -> URIRef:
        base = _sanitize(wanted)
        name, index = base, 2
        while name in self.used:
            name, index = f"{base}_{index}", index + 1
        self.used.add(name)
        return TD[name]


def _resource_path(path: str) -> str:
    """REST 자원 경로: 끝의 `/{변수}` 조각을 뗀다(`/api/items/{id}` -> `/api/items`)."""
    parts = [part for part in path.split("/") if part]
    while parts and parts[-1].startswith("{"):
        parts.pop()
    return "/" + "/".join(parts)


def skeleton(jqa: dict, bbtg: dict | None = None) -> rdflib.Graph:
    """jQA 온톨로지 JSON과 정제 bbtg({skill: JSON})에서 OWL 골격을 만든다(결정적, LLM 없음)."""
    bbtg = bbtg or {}
    graph = rdflib.Graph()
    for prefix, namespace in (("td", TD), ("owl", OWL), ("rdf", RDF), ("rdfs", RDFS), ("xsd", XSD)):
        graph.bind(prefix, namespace, override=True)
    nodes = {node["id"]: node for node in jqa.get("nodes", [])}
    edges = sorted((e["source"], e["target"], e["kind"]) for e in jqa.get("edges", []))
    by_kind = lambda kind: sorted((n for n in nodes.values() if n["kind"] == kind), key=lambda n: n["id"])
    names = _Names()

    graph.add((ONTOLOGY_IRI, RDF.type, OWL.Ontology))
    graph.add((ONTOLOGY_IRI, RDFS.label, Literal("Ontology derived from a static code graph")))
    meta = jqa.get("meta") or {}
    if meta.get("commit"):
        graph.add((ONTOLOGY_IRI, OWL.versionInfo, Literal(str(meta["commit"]))))
    for local in ANNOTATION_PROPERTIES:
        graph.add((TD[local], RDF.type, OWL.AnnotationProperty))

    def declare(iri: URIRef, rdf_type: URIRef, label: str, kind: str, sources: list[str]) -> URIRef:
        graph.add((iri, RDF.type, rdf_type))
        graph.add((iri, RDFS.label, Literal(label)))
        graph.add((iri, TD.kind, Literal(kind)))
        for source in sorted(set(sources)):
            graph.add((iri, TD.fromJqa, Literal(source)))
        return iri

    # 엔티티와 DTO 클래스
    class_of: dict[str, URIRef] = {}
    entity_by_fqn: dict[str, str] = {}
    for kind in ("Entity", "DTO"):
        for node in by_kind(kind):
            fqn = str((node.get("props") or {}).get("fqn") or node["label"])
            iri = declare(names.take(_simple(fqn).replace("$", "_")), OWL.Class, node["label"], kind, [node["id"]])
            graph.add((iri, TD.javaType, Literal(fqn)))
            class_of[node["id"]] = iri
            if kind == "Entity":
                entity_by_fqn[fqn] = node["id"]

    # 엔티티 필드: 연관 필드는 객체 속성 후보로 모으고, 나머지는 데이터 속성
    fields_of: dict[str, list[dict]] = {}
    for source, target, kind in edges:
        if kind == "hasField" and source in class_of and target in nodes:
            fields_of.setdefault(source, []).append(nodes[target])
    for entity_id in sorted(fields_of):
        domain = class_of[entity_id]
        for field in sorted(fields_of[entity_id], key=lambda n: n["id"]):
            props = field.get("props") or {}
            annotations = sorted(str(a) for a in props.get("annotations") or [])
            if set(annotations) & set(ASSOCIATIONS):
                continue
            name = str(props.get("name") or field["label"].rsplit(".", 1)[-1])
            java_type = str(props.get("type") or "")
            iri = declare(names.take(f"{domain.split('#')[1]}_{name}"), OWL.DatatypeProperty, name, "Field", [field["id"]])
            graph.add((iri, RDFS.domain, domain))
            graph.add((iri, RDFS.range, _XSD_BY_JAVA.get(java_type, XSD.string)))
            if java_type:
                graph.add((iri, TD.javaType, Literal(java_type)))
            for annotation in annotations:
                graph.add((iri, TD.annotation, Literal(annotation)))

    # 객체 속성: references 간선 + 타입이 엔티티인 연관 필드
    relations = _bbtg_relations(bbtg)
    used_fields: set[str] = set()
    pairs = [(s, t) for s, t, k in edges if k == "references" and s in class_of and t in class_of]
    for entity_id in sorted(fields_of):   # 간선이 없는 연관 필드(타입이 엔티티)도 넣는다
        for field in fields_of[entity_id]:
            target = entity_by_fqn.get(str((field.get("props") or {}).get("type") or ""))
            if target and (entity_id, target) not in pairs and set((field.get("props") or {}).get("annotations") or []) & set(ASSOCIATIONS):
                pairs.append((entity_id, target))
    for source, target in sorted(set(pairs)):
        candidates = [f for f in sorted(fields_of.get(source, []), key=lambda n: n["id"])
                      if set((f.get("props") or {}).get("annotations") or []) & set(ASSOCIATIONS) and f["id"] not in used_fields]
        target_fqn = str((nodes[target].get("props") or {}).get("fqn") or nodes[target]["label"])
        matched = [f for f in candidates if (f.get("props") or {}).get("type") == target_fqn]
        relation_types = {kind for name, kind in relations.get(_simple(str((nodes[source].get("props") or {}).get("fqn") or "")), [])
                          if name == _simple(target_fqn)}
        if not matched and relation_types:
            by_relation = [f for f in candidates if set((f.get("props") or {}).get("annotations") or []) & relation_types
                           and (f.get("props") or {}).get("type") not in entity_by_fqn]
            matched = by_relation if len(by_relation) == 1 else []
        field = matched[0] if len(matched) == 1 else None
        domain_local, range_local = class_of[source].split("#")[1], class_of[target].split("#")[1]
        sources = [source, target]
        if field is not None:
            used_fields.add(field["id"])
            name = str((field.get("props") or {}).get("name") or field["label"].rsplit(".", 1)[-1])
            iri = declare(names.take(f"{domain_local}_{name}"), OWL.ObjectProperty, name, "Association", sources + [field["id"]])
            graph.add((iri, TD.javaType, Literal(str((field.get("props") or {}).get("type") or ""))))
            field_relations = sorted(set((field.get("props") or {}).get("annotations") or []) & set(ASSOCIATIONS))
        else:
            iri = declare(names.take(f"{domain_local}_to_{range_local}"), OWL.ObjectProperty, f"to {nodes[target]['label']}",
                          "Association", sources)
            field_relations = []
        graph.add((iri, RDFS.domain, class_of[source]))
        graph.add((iri, RDFS.range, class_of[target]))
        for relation in sorted(set(field_relations) | relation_types):
            graph.add((iri, TD.jpaRelation, Literal(relation)))

    # REST 자원 클래스와 엔드포인트 개체(화면용 view 핸들러는 뺀다)
    endpoints = [n for n in by_kind("Endpoint") if not (n.get("props") or {}).get("view")]
    resources: dict[str, list[str]] = {}
    for node in endpoints:
        resources.setdefault(_resource_path(str(node["props"]["path"])), []).append(node["id"])
    resource_iri = {path: declare(names.take(f"Resource{path}" if path != "/" else "Resource_root"), OWL.Class, path,
                                  "Resource", ids) for path, ids in sorted(resources.items())}
    for path, iri in resource_iri.items():
        graph.add((iri, TD.path, Literal(path)))
    declared_by = {t: s for s, t, k in edges if k == "declares"}
    depends = {}
    for s, t, k in edges:
        if k == "dependsOn":
            depends.setdefault(s, []).append(t)
    manages = {}
    for s, t, k in edges:
        if k == "manages" and t in class_of:
            manages.setdefault(s, []).append(t)

    def reachable_entities(start: str) -> list[str]:
        seen, frontier, found = {start}, [start], set()
        for _ in range(3):
            nxt = []
            for item in frontier:
                found.update(manages.get(item, []))
                for dep in depends.get(item, []):
                    if dep not in seen:
                        seen.add(dep)
                        nxt.append(dep)
            frontier = nxt
        for item in frontier:
            found.update(manages.get(item, []))
        return sorted(found)

    uses = {}
    for s, t, k in edges:
        if k == "uses" and t in class_of:
            uses.setdefault(s, []).append(t)
    for node in endpoints:
        props = node["props"]
        iri = declare(names.take(f"Endpoint_{props['method']}_{props['path']}"), OWL.NamedIndividual, node["label"],
                      "Endpoint", [node["id"]])
        graph.add((iri, RDF.type, resource_iri[_resource_path(str(props["path"]))]))
        graph.add((iri, TD.httpMethod, Literal(str(props["method"]))))
        graph.add((iri, TD.path, Literal(str(props["path"]))))
        graph.add((iri, TD.handler, Literal(str(props["handler"]))))
        if props.get("anyMethod"):
            graph.add((iri, TD.anyMethod, Literal(True)))
        for dto in sorted(uses.get(node["id"], [])):
            graph.add((iri, TD.requestBody, class_of[dto]))
        controller = declared_by.get(node["id"])
        for entity in reachable_entities(controller) if controller else []:
            graph.add((iri, TD.relatedEntity, class_of[entity]))
    return graph


def serialize(graph: rdflib.Graph) -> str:
    return graph.serialize(format="turtle")


def parse_ttl(text: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(data=text, format="turtle")
    return graph


# --- 형식 검증(pySHACL) -----------------------------------------------------------------------------
def shapes_path() -> Path:
    return snapshot.root() / "ontology" / "owl" / "shapes.ttl"


def validate(graph: rdflib.Graph, shapes: Path | None = None) -> tuple[bool, str]:
    from pyshacl import validate as shacl_validate
    shacl = rdflib.Graph().parse(shapes or shapes_path(), format="turtle")
    conforms, _, report = shacl_validate(graph, shacl_graph=shacl)
    return bool(conforms), str(report)


def stats(graph: rdflib.Graph, jqa: dict) -> dict:
    """REQ-018 지표: Entity 대응률(jQA Entity 노드 중 td:fromJqa로 owl:Class에 대응하는 비율), 클래스·속성 수."""
    entity_ids = {n["id"] for n in jqa.get("nodes", []) if n["kind"] == "Entity"}
    classes = set(graph.subjects(RDF.type, OWL.Class))
    provenance = {str(o) for c in classes for o in graph.objects(c, TD.fromJqa)}
    matched = entity_ids & provenance
    return {"entities": len(entity_ids), "entityClasses": len(matched),
            "entityCoverage": round(len(matched) / len(entity_ids), 4) if entity_ids else 0.0,
            "classes": len(classes), "objectProperties": len(set(graph.subjects(RDF.type, OWL.ObjectProperty))),
            "datatypeProperties": len(set(graph.subjects(RDF.type, OWL.DatatypeProperty))),
            "endpoints": len({s for s in graph.subjects(TD.kind, Literal("Endpoint"))}), "triples": len(graph)}


# --- 2. LLM 추가분 계약과 합치기 -----------------------------------------------------------------------
_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(?P<body>.*)\n```\s*$", re.DOTALL)


def _strip_fence(text: str) -> str:
    body = (text or "").strip()
    fenced = _FENCE_RE.match(body)
    return fenced.group("body").strip() if fenced else body


def _short(term) -> str:
    text = str(term)
    return "td:" + text[len(str(TD)):] if text.startswith(str(TD)) else text


def merge_additions(base: rdflib.Graph, text: str) -> tuple[rdflib.Graph | None, list[str]]:
    """LLM 추가분(Turtle)을 계약대로 검사하고 골격과 합친다. 반환 (합친 Graph, []) 또는 (None, 문제 목록[영어])."""
    body = _strip_fence(text)
    if not body:
        return None, ["the reply contains no Turtle triples"]
    try:
        additions = parse_ttl(PREFIX_HEADER + body)
    except Exception as exc:  # noqa: BLE001 - rdflib 파서는 여러 예외 형식을 낸다
        return None, [f"Turtle parse error: {type(exc).__name__}: {str(exc)[:800]}"]
    if len(additions) == 0:
        return None, ["the reply contains no Turtle triples"]
    terms = {s for s in base.subjects() if isinstance(s, URIRef)}
    object_properties = set(base.subjects(RDF.type, OWL.ObjectProperty))
    properties = object_properties | set(base.subjects(RDF.type, OWL.DatatypeProperty))
    restrictions = set(additions.subjects(RDF.type, OWL.Restriction))
    problems: list[str] = []
    for s, p, o in sorted(additions, key=lambda triple: tuple(str(x) for x in triple)):
        where = f"{_short(s)} {_short(p)} {_short(o)}"
        if isinstance(s, URIRef) and s not in terms:
            problems.append(f"unknown subject {_short(s)}: new terms are not allowed, describe only skeleton terms ({where})")
        elif isinstance(s, BNode) and s not in restrictions:
            problems.append(f"a blank-node subject must be an owl:Restriction ({where})")
        if str(p).startswith(str(TD)):
            problems.append(f"{_short(p)} is a td: annotation owned by the skeleton (td:fromJqa, td:kind, ...); "
                            f"do not write it ({where})")
        elif p in (RDFS.domain, RDFS.range):
            problems.append(f"rdfs:domain/rdfs:range are already set in the skeleton; do not add them ({where})")
        elif p not in ALLOWED_PREDICATES:
            problems.append(f"predicate {_short(p)} is not allowed ({where})")
        elif p == RDF.type and o not in ALLOWED_TYPES:
            problems.append(f"rdf:type {_short(o)} is not allowed ({where})")
        elif p == RDF.type and o == OWL.Restriction and not isinstance(s, BNode):
            problems.append(f"owl:Restriction may only type a blank node inside rdfs:subClassOf ({where})")
        elif p == RDF.type and o != OWL.Restriction and s not in properties:
            problems.append(f"{_short(o)} may only type a skeleton property ({where})")
        elif p == OWL.onProperty and o not in properties:
            problems.append(f"owl:onProperty {_short(o)} is not a skeleton property ({where})")
        elif p == OWL.inverseOf and not (s in object_properties and o in object_properties):
            problems.append(f"owl:inverseOf must link two skeleton object properties ({where})")
        if isinstance(o, URIRef) and not str(o).startswith(_STANDARD_NAMESPACES) and o not in terms:
            problems.append(f"unknown term {_short(o)} ({where})")
    if problems:
        unique = list(dict.fromkeys(problems))
        return None, unique[:40] + ([f"... and {len(unique) - 40} more"] if len(unique) > 40 else [])
    merged = rdflib.Graph()
    for prefix, namespace in base.namespaces():
        merged.bind(prefix, namespace, override=True)
    for triple in base:
        merged.add(triple)
    for triple in additions:
        merged.add(triple)
    if set(base.triples((None, TD.fromJqa, None))) != set(merged.triples((None, TD.fromJqa, None))):
        return None, ["the reply changes provenance (td:fromJqa)"]
    return merged, []


def render_repair(template: str, problems: list[str], previous: str) -> str:
    errors = "\n".join(f"- {problem}" for problem in problems)
    if len(errors) > ERROR_TEXT_LIMIT:
        errors = errors[:ERROR_TEXT_LIMIT] + "\n... (truncated)"
    return template.replace("{{ERRORS}}", errors).replace("{{PREVIOUS_OUTPUT}}", previous.strip() or "(empty)")


def _shacl_problems(report: str) -> list[str]:
    lines = [line.strip() for line in report.splitlines() if line.strip().startswith(("Focus Node", "Result Path", "Message"))]
    return [f"SHACL validation failed: {' | '.join(lines[:60])[:ERROR_TEXT_LIMIT]}"]


@dataclass
class OwlContext:
    model: str
    work_dir: Path
    llm: object = snapshot.call_llm
    gen_prompt: Path | None = None
    repair_prompt: Path | None = None


def prompt_paths() -> tuple[Path, Path]:
    return snapshot.root() / "prompts" / "owl-gen.md", snapshot.root() / "prompts" / "owl-repair.md"


def enrich(graph: rdflib.Graph, bundle, *, ctx: OwlContext, record: dict | None = None) -> rdflib.Graph:
    """LLM 보강: 골격 graph와 검사·서명된 번들(td.bundle.Bundle 또는 경로) -> 합친 Graph. record에 repairs, tokens를 더한다.
    파싱·계약·SHACL 오류는 최대 2회 수리, 그래도 남으면 OwlGenError. claude 호출 자체의 실패도 OwlGenError(수리 없음)."""
    record = record if record is not None else {"repairs": 0, "tokens": {"in": 0, "out": 0}}
    gen_prompt, repair_prompt = (ctx.gen_prompt, ctx.repair_prompt) if ctx.gen_prompt else prompt_paths()
    bundle_dir = Path(getattr(bundle, "path", bundle))
    ctx.work_dir.mkdir(parents=True, exist_ok=True)

    def ask(prompt_file: Path, label: str) -> str:
        try:
            reply = ctx.llm(bundle_dir, prompt_file, ctx.work_dir / f"{label}.json")
        except snapshot.LlmCallError as exc:
            raise OwlGenError(str(exc)) from exc
        record["tokens"]["in"] += reply.tokens_in
        record["tokens"]["out"] += reply.tokens_out
        (ctx.work_dir / f"{label}.ttl").write_text(reply.text, encoding="utf-8")
        return reply.text

    text = ask(gen_prompt, "llm-gen")
    while True:
        merged, problems = merge_additions(graph, text)
        if merged is not None:
            conforms, report = validate(merged)
            if conforms:
                return merged
            problems = _shacl_problems(report)
        if record["repairs"] >= MAX_REPAIRS:
            raise OwlGenError(f"수리 {record['repairs']}회 뒤에도 LLM 추가분을 받을 수 없다: {'; '.join(problems)[:1000]}")
        record["repairs"] += 1
        prompt_file = ctx.work_dir / f"repair-{record['repairs']}.md"
        prompt_file.write_text(render_repair(repair_prompt.read_text(encoding="utf-8"), problems, text), encoding="utf-8")
        text = ask(prompt_file, f"llm-repair-{record['repairs']}")


# --- 3. 시각화 JSON -----------------------------------------------------------------------------------
def _label(graph: rdflib.Graph, term) -> str:
    labels = sorted(graph.objects(term, RDFS.label), key=str)
    english = [str(l) for l in labels if isinstance(l, Literal) and l.language == "en"]
    plain = [str(l) for l in labels if isinstance(l, Literal) and not l.language]
    return (english or plain or [term.split("#")[-1]])[0]


def _comment(graph: rdflib.Graph, term) -> str | None:
    comments = sorted(str(c) for c in graph.objects(term, RDFS.comment))
    return " ".join(comments) if comments else None


def _restrictions(graph: rdflib.Graph, term) -> list[str]:
    out = []
    for parent in graph.objects(term, RDFS.subClassOf):
        if (parent, RDF.type, OWL.Restriction) not in graph:
            out.append(f"subClassOf {_short(parent)}")
            continue
        on = next(iter(graph.objects(parent, OWL.onProperty)), None)
        parts = [f"{_short(p).replace(str(OWL), 'owl:')} {_short(o).replace(str(OWL), 'owl:')}"
                 for p, o in sorted(graph.predicate_objects(parent), key=lambda x: (str(x[0]), str(x[1])))
                 if p not in (RDF.type, OWL.onProperty)]
        out.append(f"{_short(on) if on is not None else '?'}: {', '.join(parts)}")
    return sorted(out)


def to_json(graph: rdflib.Graph, meta: dict | None = None) -> dict:
    """OWL Graph -> 온톨로지 JSON(ontology.schema.json, S04가 owl.html로 그린다). 노드 id는 IRI이고 props.fromJqa에 provenance."""
    meta = meta or {}
    nodes, edges = [], []

    def base_props(term) -> dict:
        props = {"iri": str(term), "fromJqa": sorted(str(o) for o in graph.objects(term, TD.fromJqa))}
        comment = _comment(graph, term)
        if comment:
            props["comment"] = comment
        java_type = next(iter(graph.objects(term, TD.javaType)), None)
        if java_type is not None:
            props["javaType"] = str(java_type)
        return props

    for term in sorted(set(graph.subjects(TD.kind, None)), key=str):
        kind = str(next(iter(graph.objects(term, TD.kind))))
        props = base_props(term)
        if kind in ("Entity", "DTO"):
            restrictions = _restrictions(graph, term)
            if restrictions:
                props["restrictions"] = restrictions
            nodes.append({"id": str(term), "kind": kind, "label": _label(graph, term), "props": props})
        elif kind == "Endpoint":
            resource = next((o for o in graph.objects(term, RDF.type) if o != OWL.NamedIndividual), None)
            props.update(method=str(next(iter(graph.objects(term, TD.httpMethod)))),
                         path=str(next(iter(graph.objects(term, TD.path)))),
                         handler=str(next(iter(graph.objects(term, TD.handler)))), view=False)
            if resource is not None:
                props["resource"] = _label(graph, resource)
            if (term, TD.anyMethod, Literal(True)) in graph:
                props["anyMethod"] = True
            nodes.append({"id": str(term), "kind": "Endpoint", "label": str(next(iter(graph.objects(term, RDFS.label)))),
                          "props": props})
            for dto in sorted(graph.objects(term, TD.requestBody), key=str):
                edges.append({"source": str(term), "target": str(dto), "kind": "requestBody"})
            for entity in sorted(graph.objects(term, TD.relatedEntity), key=str):
                edges.append({"source": str(term), "target": str(entity), "kind": "relatedEntity"})
        elif kind == "Field":
            domain = next(iter(graph.objects(term, RDFS.domain)), None)
            range_ = next(iter(graph.objects(term, RDFS.range)), None)
            props.update(range=_short(range_).replace(str(XSD), "xsd:") if range_ is not None else None,
                         annotations=sorted(str(a) for a in graph.objects(term, TD.annotation)))
            label = _label(graph, term)
            domain_label = _label(graph, domain) if domain is not None else ""
            nodes.append({"id": str(term), "kind": "Field", "label": f"{domain_label}.{label}" if domain_label else label,
                          "props": props})
            if domain is not None:
                edges.append({"source": str(domain), "target": str(term), "kind": "hasField"})
        elif kind == "Association":
            domain = next(iter(graph.objects(term, RDFS.domain)), None)
            range_ = next(iter(graph.objects(term, RDFS.range)), None)
            if domain is not None and range_ is not None:
                edges.append({"source": str(domain), "target": str(range_), "kind": _label(graph, term)})
    return {"nodes": nodes, "edges": edges,
            "meta": {"tool": "owl", "version": str(meta.get("version") or "rdflib-" + rdflib.__version__),
                     "commit": str(meta.get("commit") or "unknown"), "fallbacks": list(meta.get("fallbacks") or [])}}


# --- 4. S05 단계 --------------------------------------------------------------------------------------
def generated_root(sut: str) -> Path:
    """`ontology/generated/<sut>`(TD_ONTOLOGY_GENERATED_DIR가 있으면 그 아래)."""
    base = os.environ.get("TD_ONTOLOGY_GENERATED_DIR") or str(snapshot.root() / "ontology" / "generated")
    return Path(base) / sut


def input_key(bundle_hash: str, gen_prompt: bytes, repair_prompt: bytes, shapes: bytes, model: str) -> str:
    material = {"bundle": bundle_hash, "prompt": snapshot.sha256_bytes(gen_prompt),
                "repairPrompt": snapshot.sha256_bytes(repair_prompt), "shapes": snapshot.sha256_bytes(shapes),
                "model": model, "maxRepairs": MAX_REPAIRS}
    return snapshot.sha256_bytes(json.dumps(material, sort_keys=True).encode("utf-8"))


def _produce(graph, built, key: str, parent: Path, ctx: OwlContext, record: dict) -> Path:
    """예약을 쥔 상태에서 LLM 보강 -> 임시 디렉터리 -> `_COMPLETE` -> rename. 실패하면 임시 디렉터리를 지운다."""
    started = time.monotonic()
    name = key[:8]
    tmp = snapshot.make_tmp(parent, name)
    try:
        merged = enrich(graph, built, ctx=ctx, record=record)
        (tmp / TTL_NAME).write_text(serialize(merged), encoding="utf-8")
        record["seconds"] = round(time.monotonic() - started, 3)
        final = parent / name
        if final.exists():
            raise OwlGenError(f"예약을 쥔 채로 최종 디렉터리가 이미 있다: {name}")
        snapshot.write_complete(tmp, key, {k: record[k] for k in ("repairs", "tokens", "seconds", "model", "promptHash",
                                                                   "repairPromptHash", "bundleHash")}, name=name)
        os.rename(tmp, final)
        return final
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def obtain(graph, built, key: str, parent: Path, ctx: OwlContext, record: dict, wait_timeout: float) -> tuple[Path, bool]:
    """스냅샷을 재사용하거나 만든다. 반환 (최종 디렉터리, reused). 쓸 수 없는 스냅샷이나 실패는 OwlGenError."""
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / key[:8]
    deadline = time.monotonic() + wait_timeout
    while True:
        if final.exists():
            problem = snapshot.complete_problem(final, key)
            if problem is not None:
                raise OwlGenError(f"스냅샷이 있지만 재사용할 수 없다(덮어쓰지 않는다): {final.name}: {problem}")
            return final, True
        if os.environ.get("TD_OWLGEN_REQUIRE_SNAPSHOT") == "1":
            raise OwlGenError(f"TD_OWLGEN_REQUIRE_SNAPSHOT=1인데 입력 키의 스냅샷이 없다(입력이 바뀌었다): {final.name}")
        lock = snapshot.try_reserve(parent, final.name)
        if lock is not None:
            try:
                if final.exists():
                    continue
                return _produce(graph, built, key, parent, ctx, record), False
            finally:
                snapshot.release(lock)
        if time.monotonic() > deadline:
            raise OwlGenError(f"다른 프로세스의 예약이 {int(wait_timeout)}초 동안 풀리지 않았다: {final.name}")
        time.sleep(1.0)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(snapshot.root().resolve()).as_posix()
    except ValueError:
        return str(path)


def run_stage(run_dir, sut_file, sut_src, *, llm=snapshot.call_llm) -> dict:
    """S05 전체. 반환 {status, reason, outputs, extra}. owl-gen.json(번들 조립 뒤에는 실패해도)을 쓴다."""
    from td import prepare, state, sut_config
    run_dir, sut_src = Path(run_dir), Path(sut_src)
    out = run_dir / "S05"
    out.mkdir(parents=True, exist_ok=True)
    sut = sut_config.load(sut_file).name
    jqa_path = run_dir / "S03" / "ontology-jqa.json"
    try:
        jqa = json.loads(jqa_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _result("failed", f"S03 jQA 온톨로지를 읽을 수 없다: {exc}", out)
    graph = skeleton(jqa, load_bbtg(run_dir / "S02" / "bbtg" / "clean"))
    (out / "skeleton.ttl").write_text(serialize(graph), encoding="utf-8")
    try:
        built = snapshot.build_bundle("owlgen", run_dir, out / "bundle", sut_src, Path(sut_file), out / "bundle-build")
    except snapshot.BundleBuildError as exc:
        return _result("failed", str(exc), out)

    gen_prompt, repair_prompt = prompt_paths()
    model = prepare.resolve_model(snapshot.root() / "pipeline" / "config.yaml")
    key = input_key(built.input_hash, gen_prompt.read_bytes(), repair_prompt.read_bytes(), shapes_path().read_bytes(), model)
    sanitize = snapshot.sanitize_info(run_dir)
    record = {"schema": 1, "runId": state.read_run(run_dir).get("runId"), "sut": sut, "status": "failed", "reason": None,
              "reused": False, "inputHash": key, "bundleHash": built.input_hash,
              "promptHash": snapshot.sha256_bytes(gen_prompt.read_bytes()),
              "repairPromptHash": snapshot.sha256_bytes(repair_prompt.read_bytes()),
              "shapesHash": snapshot.sha256_bytes(shapes_path().read_bytes()), "model": model,
              "cliVersion": snapshot.cli_version(run_dir), "flags": list(prepare.CLAUDE_FLAGS), "maxRepairs": MAX_REPAIRS,
              "repairs": 0, "tokens": {"in": 0, "out": 0}, "seconds": 0.0,
              "strippedFields": sanitize["strippedFields"], "forbiddenDeclared": sanitize["forbiddenDeclared"],
              "snapshot": None, "conforms": None, "stats": None}
    ctx = OwlContext(model=model, work_dir=out / "work", llm=llm)
    started = time.monotonic()
    status, reason = "passed", None
    try:
        final, reused = obtain(graph, built, key, generated_root(sut), ctx, record,
                               float(os.environ.get("TD_OWLGEN_WAIT_SEC", "3600")))
        if reused:
            original = snapshot.read_complete_meta(final)
            record.update(repairs=original["repairs"], tokens=original["tokens"], seconds=original["seconds"], reused=True)
        else:
            record["seconds"] = round(time.monotonic() - started, 3)
        record["snapshot"] = _rel(final)
        shutil.copyfile(final / TTL_NAME, out / TTL_NAME)
        owl = parse_ttl((out / TTL_NAME).read_text(encoding="utf-8"))
        conforms, report = validate(owl)
        record["conforms"] = conforms
        record["stats"] = stats(owl, jqa)
        if not conforms:
            raise OwlGenError(f"스냅샷 온톨로지가 shapes를 통과하지 못한다: {_shacl_problems(report)[0][:800]}")
        doc = to_json(owl, {"commit": (jqa.get("meta") or {}).get("commit"), "version": f"rdflib-{rdflib.__version__}"})
        jsonschema.validate(doc, json.loads((SCHEMA_DIR / "ontology.schema.json").read_text(encoding="utf-8")))
        (out / "ontology-owl.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        weak = []
        if record["stats"]["entityCoverage"] < 0.9:
            weak.append(f"Entity 대응 {record['stats']['entityCoverage']:.0%} < 90%")
        if record["stats"]["objectProperties"] < 3:
            weak.append(f"객체 속성 {record['stats']['objectProperties']}개 < 3")
        if weak:
            status, reason = "degraded", "; ".join(weak)
    except Exception as exc:  # noqa: BLE001 - 어떤 오류든 failed로 마감하고 owl-gen.json을 쓴다
        message = str(exc) if isinstance(exc, OwlGenError) else f"S05 실행 오류: {type(exc).__name__}: {exc}"
        status, reason = "failed", message[:1500]
        if record["seconds"] == 0.0:
            record["seconds"] = round(time.monotonic() - started, 3)
        for name in (TTL_NAME, "ontology-owl.json"):
            (out / name).unlink(missing_ok=True)
    record.update(status=status, reason=reason)
    jsonschema.validate(record, json.loads((SCHEMA_DIR / "owl-gen.schema.json").read_text(encoding="utf-8")))
    (out / "owl-gen.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _result(status, reason, out, record)


def _result(status: str, reason: str | None, out: Path, record: dict | None = None) -> dict:
    outputs = {"skeleton": str(out / "skeleton.ttl"), "bundle": str(out / "bundle")}
    if status != "failed":
        outputs.update(ontology=str(out / "ontology-owl.json"), ttl=str(out / TTL_NAME))
    if record is not None:
        outputs["owlGen"] = str(out / "owl-gen.json")
    extra = {"owl": {k: record[k] for k in ("inputHash", "reused", "repairs", "snapshot", "stats")}} if record else {}
    return {"status": status, "reason": reason, "outputs": outputs, "extra": extra}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.ontology_owl")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage", help="S05 전체 실행. stdout: {status, reason, outputs, extra}")
    stage.add_argument("--run-dir", required=True)
    stage.add_argument("--sut-file", required=True)
    stage.add_argument("--sut-src", required=True)
    skel = sub.add_parser("skeleton", help="jQA JSON + 정제 bbtg 디렉터리 -> 골격 Turtle")
    skel.add_argument("jqa_json")
    skel.add_argument("bbtg_dir")
    skel.add_argument("out_ttl")
    check = sub.add_parser("validate", help="Turtle을 shapes.ttl로 검증(conforms면 0, 아니면 1과 보고서)")
    check.add_argument("ttl")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, snapshot.on_term)
    if args.command == "skeleton":
        graph = skeleton(json.loads(Path(args.jqa_json).read_text(encoding="utf-8")), load_bbtg(args.bbtg_dir))
        Path(args.out_ttl).write_text(serialize(graph), encoding="utf-8")
        return 0
    if args.command == "validate":
        conforms, report = validate(rdflib.Graph().parse(args.ttl, format="turtle"))
        if not conforms:
            print(report, file=sys.stderr)
        return 0 if conforms else 1
    try:
        result = run_stage(args.run_dir, args.sut_file, args.sut_src)
    except Exception as exc:  # noqa: BLE001 - 단계 실패 사유로 기록한다
        result = {"status": "failed", "reason": f"S05 실행 오류: {type(exc).__name__}: {str(exc)[:1200]}", "outputs": {},
                  "extra": {}}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
