"""det 조합 시각화 데이터(det-viz.json) 결합·집계.

`factors.json`(생성기 산출)과 S07 실행 결과를 합쳐 화면용 문서를 만든다. 파일을 쓰지 않고, 입력만 읽으며,
같은 입력이면 경로와 무관하게 같은 결과다. LLM·네트워크를 쓰지 않는다.
집계 정의는 설계 §5.4를 따른다: inModel=true 케이스만 세고, 칸에 적지 않은 필드는 그 필드의 valid 클래스로 해석한다.
"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import jsonschema

from td.detgen.observed import observed_codes
from td.detgen.results import case_statuses

__all__ = ["FactorsMissing", "build", "validate"]

VERSION = 1
FACTORS_FILE = "factors.json"
CASES_FILE = "cases.json"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_PATH = SCHEMA_DIR / "det-viz.schema.json"
FACTORS_SCHEMA_PATH = SCHEMA_DIR / "factors.schema.json"


class FactorsMissing(Exception):
    """generation 디렉터리에 factors.json이 없다(시각화 대상 아님)."""


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _case_results(cases: list[dict], gen_dir: Path, s07_dir: Path) -> dict[str, dict]:
    """케이스 id → {endpoint, status, observed, expectStrict}. passed·failed 외는 모두 notRun."""
    raw = case_statuses(gen_dir, s07_dir)
    cucumber = s07_dir / "cucumber.json"
    try:
        codes = observed_codes(cucumber.read_text(encoding="utf-8")) if cucumber.is_file() else {}
    except ValueError:
        codes = {}
    results: dict[str, dict] = {}
    for case in cases:
        case_id = case["id"]
        status = raw.get(case_id)
        status = status if status in ("passed", "failed") else "notRun"
        strict = (case.get("expect") or {}).get("strict")
        strict = strict if isinstance(strict, int) and not isinstance(strict, bool) else None
        if status == "passed":
            observed = strict
        elif status == "failed":
            observed = codes.get(case_id)
        else:
            observed = None
        results[case_id] = {"endpoint": case["endpoint"], "status": status, "observed": observed, "expectStrict": strict}
    return results


def _class_state(statuses: list[str], hits: list) -> str:
    if "passed" in statuses:
        return "covered-pass"
    if "failed" in statuses:
        return "covered-fail"
    if statuses:
        return "covered-notrun"
    return "unresolved" if hits else "empty"


def _endpoint_aggregate(entry: dict, factors: dict, case_results: dict[str, dict]) -> dict:
    label = entry["endpoint"]
    fields = {field["field"]: field["classes"] for field in entry["fields"]}
    valid_of = {name: classes[0]["id"] for name, classes in fields.items()}
    resolved: dict[str, dict] = {}
    for case_id, info in factors["cases"].items():
        if info["inModel"] and case_results.get(case_id, {}).get("endpoint") == label:
            resolved[case_id] = {name: info["cells"].get(name, valid_of[name]) for name in fields}
    class_ids = {klass["id"] for classes in fields.values() for klass in classes}
    slots = [slot for slot in factors["unresolved"] if class_ids & set(slot["cells"].values())]

    classes_out: dict[str, dict] = {}
    for name, classes in fields.items():
        for klass in classes:
            members = sorted(case_id for case_id, cell in resolved.items() if cell[name] == klass["id"])
            hits = [{"index": slot["index"], "reason": slot["reason"]}
                    for slot in slots if slot["cells"].get(name) == klass["id"]]
            boundary = sum(1 for case_id in resolved if klass["id"] in factors["cases"][case_id]["boundaries"])
            classes_out[klass["id"]] = {
                "state": _class_state([case_results[case_id]["status"] for case_id in members], hits),
                "cases": members, "boundaryCases": boundary, "unresolved": hits}

    matrix, total, covered = [], 0, 0
    for a, b in combinations(fields, 2):
        counts = [[sum(1 for cell in resolved.values() if cell[a] == ca["id"] and cell[b] == cb["id"])
                   for cb in fields[b]] for ca in fields[a]]
        matrix.append({"a": a, "b": b, "counts": counts})
        total += len(fields[a]) * len(fields[b])
        covered += sum(1 for row in counts for count in row if count >= 1)
    return {"classes": classes_out, "pairs": {"total": total, "covered": covered, "matrix": matrix}}


def _aggregates(factors: dict, case_results: dict[str, dict]) -> dict:
    by_endpoint = {entry["endpoint"]: _endpoint_aggregate(entry, factors, case_results) for entry in factors["endpoints"]}
    all_classes = [info for item in by_endpoint.values() for info in item["classes"].values()]
    out_of_model: dict[str, int] = {}
    for info in factors["cases"].values():
        if not info["inModel"]:
            out_of_model[info["outReason"]] = out_of_model.get(info["outReason"], 0) + 1
    summary = {
        "endpoints": len(by_endpoint),
        "fields": sum(len(entry["fields"]) for entry in factors["endpoints"]),
        "classes": len(all_classes),
        "classesCovered": sum(1 for info in all_classes if info["state"].startswith("covered-")),
        "pairsCovered": sum(item["pairs"]["covered"] for item in by_endpoint.values()),
        "pairsTotal": sum(item["pairs"]["total"] for item in by_endpoint.values()),
        "outOfModel": dict(sorted(out_of_model.items())),
    }
    return {"summary": summary, "byEndpoint": by_endpoint}


def build(gen_dir: Path, s07_dir: Path) -> dict:
    """det-viz.json 내용. factors.json이 없으면 FactorsMissing."""
    gen_dir, s07_dir = Path(gen_dir), Path(s07_dir)
    factors_path = gen_dir / FACTORS_FILE
    if not factors_path.is_file():
        raise FactorsMissing(str(factors_path.name))
    factors = _read_json(factors_path)
    try:
        cases_doc = _read_json(gen_dir / CASES_FILE)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{CASES_FILE}을 읽을 수 없다: {exc}") from exc
    if not isinstance(cases_doc, dict) or not isinstance(cases_doc.get("cases"), list):
        raise ValueError(f"{CASES_FILE} 형식이 맞지 않는다(cases 목록 필요)")
    cases = cases_doc["cases"]
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not isinstance(case.get("endpoint"), str):
            raise ValueError(f"{CASES_FILE}의 케이스에 id 또는 endpoint가 없다: {case!r:.80}")
    case_results = _case_results(cases, gen_dir, s07_dir)
    return {"version": VERSION, "genId": gen_dir.name, "factors": factors, "caseResults": case_results,
            "aggregates": _aggregates(factors, case_results), "trace": _trace(cases_doc, factors)}


def _trace(cases_doc: dict, factors: dict) -> dict:
    """화면 추적용 보조 정보. factors.json에 없는 두 가지를 cases.json에서 옮긴다.
    - caseSources: 케이스 id → 출처 주소(`~` 제거, 순서 유지). 케이스 노드 패널의 조건식 원문에 쓴다.
    - unresolvedEndpoints: factors.unresolved[i]의 엔드포인트(cases.json unresolved[i].endpoint, 없으면 null).
      칸이 빈 생성 불가 슬롯도 그래프에서 엔드포인트별로 보이게 한다."""
    case_sources: dict[str, list[str]] = {}
    for case in cases_doc["cases"]:
        sources = case.get("sources") if isinstance(case.get("sources"), list) else []
        case_sources[case["id"]] = [address.rstrip("~") for address in sources if isinstance(address, str)]
    raw = cases_doc.get("unresolved") if isinstance(cases_doc.get("unresolved"), list) else []
    endpoints: list[str | None] = []
    for slot in factors.get("unresolved") or []:
        index = slot.get("index")
        item = raw[index] if isinstance(index, int) and 0 <= index < len(raw) and isinstance(raw[index], dict) else {}
        endpoint = item.get("endpoint")
        endpoints.append(endpoint if isinstance(endpoint, str) else None)
    return {"caseSources": case_sources, "unresolvedEndpoints": endpoints}


def validate(doc: dict) -> None:
    """det-viz.schema.json 검증. 어긋나면 jsonschema.ValidationError."""
    jsonschema.validate(doc, _composed_schema())


def _composed_schema() -> dict:
    """det-viz 스키마의 `#/$defs/factors`에 factors.schema.json을 넣는다(정의 중복 방지).
    factors 스키마 자신의 `$defs`(classId 등)는 루트 `$defs`로 올린다. 이름이 겹치면 오류다."""
    schema = _read_json(SCHEMA_PATH)
    factors = _read_json(FACTORS_SCHEMA_PATH)
    inner = factors.pop("$defs", {})
    factors.pop("$schema", None)
    defs = schema.setdefault("$defs", {})
    clash = (set(inner) | {"factors"}) & set(defs)
    if clash:
        raise ValueError(f"스키마 $defs 이름 충돌: {sorted(clash)}")
    defs.update(inner)
    defs["factors"] = factors
    return schema
