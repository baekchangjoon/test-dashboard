"""엔드포인트 표(설계 §5.2 엔드포인트 대응·파라미터·선행 응답 id·기대 상태).

번들의 온톨로지·보강 그래프·하네스 설정에서 api 엔드포인트 표를 만든다. 계획 메서드 → 엔드포인트 대응,
이름 없는 query 파라미터 이름 정렬, 선행 생성 엔드포인트, 예외 → 기대 상태를 맡는다.
이 모듈은 Java·Spring 문법과 §5.6 관례만 안다(SUT 이름을 모른다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# §5.6 허용 리터럴: ResponseEntity 빌더 → 코드 표, 경로 변수 관례, 매핑 애노테이션 이름
RESPONSE_BUILDER_STATUS = {"badRequest": 400, "unprocessableEntity": 422, "notFound": 404, "ok": 200,
                           "noContent": 204, "created": 201}
ID_SUFFIX = "Id"
ID_FIELD = "id"
CREATE_METHOD = "POST"
# bbtg 관례: expected 문자열의 `<예외 단순명> code=NNN`
_EXPECTED_PATTERN = re.compile(r"(?:([A-Za-z_$][\w$.]*)\s+)?code=(\d{3})")
# Java 타입 분류(문법 지식)
_INT_TYPES = {"int", "long", "short", "byte", "java.lang.Integer", "java.lang.Long", "java.lang.Short", "java.lang.Byte"}
_REAL_TYPES = {"double", "float", "java.lang.Double", "java.lang.Float", "java.math.BigDecimal"}
_BOOL_TYPES = {"boolean", "java.lang.Boolean"}
_STRING_TYPES = {"java.lang.String"}
_DATE_TYPES = {"java.time.LocalDate"}
_BOXED = {"Integer": "int", "Long": "long", "Short": "short", "Byte": "byte", "Double": "double", "Float": "float",
          "Boolean": "boolean"}


@dataclass
class Field:
    name: str
    loc: str  # body | query | path
    type: str
    kind: str  # int | real | bool | string | date | enum | other
    primitive: bool
    required: bool = False
    constants: tuple = ()


@dataclass
class Endpoint:
    id: str
    label: str
    method: str
    path: str
    controller: str
    path_vars: list
    body: dict | None
    body_type: str | None
    query: dict
    unnamed_query: list
    response_fields: set | None
    slug: str = ""
    mapped: bool = False
    error_disjuncts: list = field(default_factory=list)  # (addr, [Con]). addr 끝 `~`는 미해결 논리곱의 부분 제약
    branch_disjuncts: list = field(default_factory=list)  # 분기 진입 항목의 제약(모수 계산용)
    state_fields: set = field(default_factory=set)  # 미해결 메서드의 인자·수신자로 쓰인 enum 요청 필드
    count_fields: set = field(default_factory=set)  # count 질의 인자로 쓰인 요청 필드(해석 여부와 무관)
    extra_classes: set = field(default_factory=set)  # 변환은 못 했지만 필드는 아는 원자식(모수 계산용)


def simple(fqn: str) -> str:
    return re.split(r"[.$]", fqn or "")[-1]


def status_class(code) -> str:
    """상태 코드 → 클래스(`<백의 자리>xx`). 100~599 정수가 아니면(설정 누락 등) 규칙 기본값 `4xx`."""
    if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
        return f"{code // 100}xx"
    return "4xx"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def glob(patterns) -> re.Pattern:
    """`**`·`*` 경로 glob → 정규식(여러 패턴이면 OR)."""
    parts = []
    for pattern in [patterns] if isinstance(patterns, str) else list(patterns or []):
        parts.append("".join(".*" if token == "**" else "[^/]*" if token == "*" else re.escape(token)
                             for token in re.findall(r"\*\*|\*|[^*]+", pattern)))
    return re.compile("(?:" + "|".join(parts or ["(?!)"]) + r")\Z")


class Catalog:
    """api 엔드포인트 표와 그래프 조회."""

    def __init__(self, ontology: dict, ext: dict, harness: dict) -> None:
        self.ext = ext
        self.harness = harness
        self.login = " ".join((harness.get("login") or "").split())
        self.endpoints = self._endpoints(ontology)

    def field(self, name, loc, type_name, required=False) -> Field:
        enums = self.ext.get("enums", {})
        kind = ("int" if type_name in _INT_TYPES else "real" if type_name in _REAL_TYPES
                else "bool" if type_name in _BOOL_TYPES else "string" if type_name in _STRING_TYPES
                else "date" if type_name in _DATE_TYPES else "enum" if type_name in enums else "other")
        constants = tuple(enums[type_name]["constants"]) if kind == "enum" else ()
        return Field(name, loc, type_name, kind, type_name[:1].islower() and "." not in type_name, required, constants)

    def _endpoints(self, ontology) -> dict[str, Endpoint]:
        include = glob(self.harness.get("apiInclude"))
        ext_endpoints = self.ext.get("endpoints", {})
        dtos = self.ext.get("dtos", {})
        result = {}
        for node in sorted(ontology.get("nodes", []), key=lambda n: n["id"]):
            props = node.get("props") or {}
            if node.get("kind") != "Endpoint" or props.get("view") or not include.match(props.get("path", "")):
                continue
            info = ext_endpoints.get(node["id"]) or {}
            params = sorted(info.get("params", []), key=lambda p: p["index"])
            path_types = [p["type"] for p in params if p["kind"] == "PathVariable"]
            path_vars = [self.field(name, "path", path_types[i] if i < len(path_types) else "java.lang.String", True)
                         for i, name in enumerate(re.findall(r"\{([^}/]+)\}", props["path"]))]
            body_param = next((p for p in params if p["kind"] == "RequestBody"), None)
            body_type = body_param["type"] if body_param else None
            body = ({f["name"]: self.field(f["name"], "body", f["type"]) for f in dtos[body_type]["fields"]}
                    if body_type in dtos else None)
            response = dtos.get(info.get("responseDto")) if info.get("responseDto") else None
            label = f"{props['method']} {props['path']}"
            endpoint = Endpoint(node["id"], label, props["method"], props["path"], props.get("handler", "").split("#")[0],
                                path_vars, body, body_type, {}, [],
                                {f["name"] for f in response["fields"]} if response else None, slug=slug(label))
            for param in params:
                if param["kind"] == "RequestParam":
                    # Spring 기본: required 미지정 + defaultValue 없음이면 필수
                    required = param["required"] is True or (param["required"] is None and param["defaultValue"] is None)
                    endpoint.unnamed_query.append(self.field("", "query", param["type"], required))
            result[node["id"]] = endpoint
        return result

    def map(self, plan) -> Endpoint | None:
        """계획 (서비스 단순명, 메서드) → ext.calls의 엔드포인트. 정확히 1개일 때만 대응한다."""
        hits = {call["endpoint"] for call in self.ext.get("calls", [])
                if simple(call["service"]) == plan["class"] and call["method"] == plan["method"]}
        return self.endpoints.get(next(iter(hits))) if len(hits) == 1 else None

    def name_query(self, ep: Endpoint, keyparams) -> None:
        """아직 이름 없는 RequestParam에 key-params `http_name`을 타입·순서로 맞춘다(계획마다 호출해도 된다)."""
        taken = {f.name for f in ep.path_vars} | set(ep.query)
        candidates = [p for p in (keyparams or {}).get("parameters", []) if p["http_name"] and p["http_name"] not in taken]
        remaining = []
        for param in ep.unnamed_query:
            want = _BOXED.get(simple(param.type), simple(param.type))
            match = next((c for c in candidates if _BOXED.get(simple(c["java_type"]), simple(c["java_type"])) == want), None)
            if match is None:
                remaining.append(param)
                continue
            candidates.remove(match)
            param.name = match["http_name"]
            ep.query[param.name] = param
        ep.unnamed_query = remaining

    @staticmethod
    def lookup(ep: Endpoint, name: str) -> Field | None:
        return (ep.body or {}).get(name) or ep.query.get(name)

    def creator(self, ep: Endpoint) -> Endpoint | None:
        """`P/{v}` 엔드포인트의 선행 생성 요청: 같은 api 집합의 `POST P`."""
        parent = re.sub(r"/\{[^}/]+\}$", "", ep.path)
        if parent == ep.path:
            return None
        return next((e for e in self.endpoints.values() if e.method == CREATE_METHOD and e.path == parent), None)

    @staticmethod
    def capture(creator: Endpoint | None, var: str) -> str | None:
        """경로 변수에 대응하는 선행 응답 필드: 같은 이름, 없으면 `{<x>Id}` → `id`."""
        if creator is None or not creator.response_fields:
            return None
        if var in creator.response_fields:
            return var
        return ID_FIELD if var.endswith(ID_SUFFIX) and ID_FIELD in creator.response_fields else None

    def constant(self, name: str, owner: str):
        """그래프 상수값: 조건 소유 클래스 우선, 없으면 전역 유일 이름일 때만."""
        candidates = [c for c in self.ext.get("constants", []) if c["name"] == name]
        own = [c for c in candidates if simple(c["owner"]) == owner]
        chosen = own[0] if len(own) == 1 else candidates[0] if not own and len(candidates) == 1 else None
        value = chosen.get("value") if chosen else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def expect(self, expected: str) -> dict | None:
        """bbtg expected → 기대 상태. 예외 단순명이 그래프 예외 하나와 맞으면 그래프 상태를 strict로 쓴다."""
        match = _EXPECTED_PATTERN.search(expected or "")
        if match is None:
            return None
        code = int(match.group(2))
        result = {"strict": code, "class": status_class(code), "source": "bbtg", "bbtgCode": code}
        if match.group(1):
            name = simple(match.group(1))
            exceptions = self.ext.get("exceptions", {})
            hits = [fqn for fqn in exceptions if fqn.endswith(("$" + name, "." + name))]
            if len(hits) == 1 and isinstance(exceptions[hits[0]].get("status"), int):
                status = exceptions[hits[0]]["status"]
                result.update({"strict": status, "graphStatus": status, "source": "graph",
                               "class": status_class(status)})
        return result

    def not_found(self, ep: Endpoint) -> dict:
        """없는 id: 같은 컨트롤러(또는 중첩 클래스) 핸들러가 받는 notFound 상태 예외가 있으면 그 상태."""
        status = RESPONSE_BUILDER_STATUS["notFound"]
        for info in self.ext.get("exceptions", {}).values():
            handler = info.get("handler") or ""
            if info.get("status") == status and ep.controller and handler.startswith((ep.controller + "$", ep.controller + "#")):
                return {"strict": status, "class": status_class(status), "source": "graph", "graphStatus": status}
        return {"strict": "4xx", "class": "4xx", "source": "rule"}
