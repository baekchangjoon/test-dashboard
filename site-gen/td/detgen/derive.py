"""케이스 도출(설계 §5.2 케이스 도출, §5.3 baseline, §5.4 모수).

입력은 det 번들(`Bundle`)뿐이다. SUT 이름·임계값은 모두 번들에서 읽고, 이 모듈에는 설계 §5.6 허용 리터럴과
bbtg 관례 표지(`null/empty`, `no_data`, `code=`, `BRANCH_CONDITION`)만 둔다.

흐름: 엔드포인트 표 구성 → 계획 항목마다 파싱·제약 변환 → 초안(draft) → 1차 구체화(baseline·선행 요청·충돌 점검)
→ baseline/R-HAPPY 추가 → 정렬·id 부여 → 기호(uniq·분산) 확정 → 모수 계산.
계수 단위는 슬롯이다. 초안 하나가 슬롯 하나이고, 생성되면 case, 아니면 `unresolved` 한 줄이 된다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

from td.detgen.inputs import Bundle
from td.detgen.parse import STORED_RECEIVER, Atom, Operand, parse

REASONS = ("no-endpoint-mapping", "unparsed", "unresolved-operand", "unreachable-state", "needs-state-transition",
           "param-name-unknown", "no-id-ref", "no-condition", "no-body-schema", "format-unknown", "input-missing")
# 한 슬롯에 사유가 여럿이면 앞선 것을 쓴다(근본 원인 우선)
_REASON_PRIORITY = ("input-missing", "needs-state-transition", "unresolved-operand", "format-unknown",
                    "no-body-schema", "param-name-unknown", "no-id-ref", "unreachable-state")
# §5.6 허용 리터럴
LARGE_NUMBER = 1000000
INT_STEP = 1
REAL_STEP = 0.01
RESPONSE_BUILDER_STATUS = {"badRequest": 400, "unprocessableEntity": 422, "notFound": 404, "ok": 200,
                           "noContent": 204, "created": 201}
EMAIL_TOKEN = "EMAIL"
EMAIL_VALID = "uniq@example.com"
EMAIL_INVALID = "not-an-email"
ID_SUFFIX = "Id"
ID_FIELD = "id"
CREATE_METHOD = "POST"
# bbtg 관례 표지(설계 §5.2 특수 항목)
EMPTY_BODY_MARK = "null/empty"
NO_DATA_MARK = "no_data"
BRANCH_REASON = "BRANCH_CONDITION"
_EXPECTED_PATTERN = re.compile(r"(?:([A-Za-z_$][\w$.]*)\s+)?code=(\d{3})")
_CONDITION_SIGNS = re.compile(r"[=<>!≠.]")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
# Java 타입 분류(문법 지식)
_INT_TYPES = {"int", "long", "short", "byte", "java.lang.Integer", "java.lang.Long", "java.lang.Short", "java.lang.Byte"}
_REAL_TYPES = {"double", "float", "java.lang.Double", "java.lang.Float", "java.math.BigDecimal"}
_BOOL_TYPES = {"boolean", "java.lang.Boolean"}
_STRING_TYPES = {"java.lang.String"}
_DATE_TYPES = {"java.time.LocalDate"}
_BOXED = {"Integer": "int", "Long": "long", "Short": "short", "Byte": "byte", "Double": "double", "Float": "float",
          "Boolean": "boolean"}
_VALID_RULES = ("valid-boundary", "baseline-valid", "enum-value", "happy", "branch-entry", "filter-empty")
_DAY_SHIFT = re.compile(r"\.(plus|minus)Days\((\d+)\)")


@dataclass
class Value:
    value: object
    provenance: Literal["input", "derived", "generic-sentinel"]
    source: str | None = None
    transform: str | None = None


@dataclass
class Case:
    id: str
    endpoint: str
    rule: str
    sources: list[str]
    values: dict[str, Value]
    query: dict[str, Value]
    path: dict[str, Value]
    setup: list[dict]
    auth: Literal["authed", "anonymous"]
    expect: dict
    oracle: Literal["status", "status-only", "framework-reject"]
    assumes: list[str]
    baseline_proof: list[str]
    pair: str | None


@dataclass
class Derivation:
    cases: list[Case]
    unresolved: list[dict]
    universe: dict


class _Uniq:
    """`uniq:<caseId>` 자리표시. id가 정해진 뒤 확정한다."""


UNIQ = _Uniq()
_OMIT = object()  # baseline에서 보내지 않는 필드
_KEEP = "_KEEP"  # 값을 바꾸지 않는 원자식(count: 선행 건수만 정한다)
_BASE = "_BASE"  # null 규칙을 무시한 baseline 값


@dataclass(frozen=True)
class _Spread:
    """유효 범위 [lo, hi]에서 caseId 해시로 고르는 정수(경계값 집합 제외)."""
    lo: int
    hi: int
    excluded: tuple


@dataclass
class _Field:
    name: str
    loc: str
    type: str
    kind: str  # int | real | bool | string | date | enum | other
    primitive: bool
    required: bool = False
    constants: tuple = ()


@dataclass(frozen=True)
class _Con:
    """요청 필드(또는 저장 상태)에 대한 정규화 제약. value는 수치(길이·날짜 오프셋 포함)·상수명·문자열."""
    field: str
    op: str  # < <= > >= == != null notnull fmt eqlit neqlit count rel
    value: object = None
    length: bool = False
    date: bool = False
    stored: bool = False
    extra: bool = False  # 날짜 `!isAfter` 위반 쪽 추가값(today-1)
    side: tuple = ()  # rel: 값을 정하는 요청 필드들
    assumes: tuple = ()  # rel: (위반 쪽 가정, 유효 쪽 가정)


@dataclass
class _Endpoint:
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
    error_disjuncts: list = field(default_factory=list)  # (addr, [_Con]). addr 끝 `~`는 미해결 논리곱의 부분 제약
    branch_disjuncts: list = field(default_factory=list)  # 분기 진입 항목의 제약(모수 계산용)
    state_fields: set = field(default_factory=set)  # 미해결 메서드의 인자·수신자로 쓰인 enum 요청 필드
    count_fields: set = field(default_factory=set)  # count 질의 인자로 쓰인 요청 필드(해석 여부와 무관)


@dataclass
class _Draft:
    ep: _Endpoint
    rule: str
    sources: list
    key: tuple
    targets: dict = field(default_factory=dict)
    stored: dict = field(default_factory=dict)
    expect: dict | None = None
    oracle: str = "status"
    assumes: list = field(default_factory=list)
    priors: int = 0
    path_mode: str = "ref"  # ref | missing
    reason: str | None = None
    pair_key: tuple | None = None
    case: Case | None = None


def _simple(fqn: str) -> str:
    return re.split(r"[.$]", fqn or "")[-1]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _glob(patterns) -> re.Pattern:
    """`**`·`*` 경로 glob → 정규식(여러 패턴이면 OR)."""
    parts = []
    for pattern in [patterns] if isinstance(patterns, str) else list(patterns or []):
        parts.append("".join(".*" if token == "**" else "[^/]*" if token == "*" else re.escape(token)
                             for token in re.findall(r"\*\*|\*|[^*]+", pattern)))
    return re.compile("(?:" + "|".join(parts or ["(?!)"]) + r")\Z")


def _number(text: str):
    text = re.sub(r"[lLdDfF]$", "", text)
    return float(text) if "." in text else int(text)


def _best_reason(reasons) -> str:
    return min(reasons, key=_REASON_PRIORITY.index)


class _Deriver:
    def __init__(self, bundle: Bundle) -> None:
        self.plans = bundle.read("plans.json")
        self.keyparams = {(kp["class"], kp["method"]): kp for kp in bundle.read("keyparams.json")}
        self.auth = bundle.read("auth.json")
        self.ontology = bundle.read("ontology.json")
        self.ext = bundle.read("ext.json")
        self.harness = bundle.read("harness.json")
        self.missing = bundle.missing
        self.drafts: list[_Draft] = []
        self.unresolved: list[dict] = []
        self.nodata: dict[str, _Draft] = {}
        self.baselines: dict[str, dict] = {}
        self.endpoints = self._endpoints()

    # --- 엔드포인트 표 ----------------------------------------------------------------------------

    def _field(self, name, loc, type_name, required=False) -> _Field:
        enums = self.ext.get("enums", {})
        kind = ("int" if type_name in _INT_TYPES else "real" if type_name in _REAL_TYPES
                else "bool" if type_name in _BOOL_TYPES else "string" if type_name in _STRING_TYPES
                else "date" if type_name in _DATE_TYPES else "enum" if type_name in enums else "other")
        constants = tuple(enums[type_name]["constants"]) if kind == "enum" else ()
        return _Field(name, loc, type_name, kind, type_name[:1].islower() and "." not in type_name, required, constants)

    def _endpoints(self) -> dict[str, _Endpoint]:
        include = _glob(self.harness.get("apiInclude"))
        ext_endpoints = self.ext.get("endpoints", {})
        result = {}
        for node in sorted(self.ontology.get("nodes", []), key=lambda n: n["id"]):
            props = node.get("props") or {}
            if node.get("kind") != "Endpoint" or props.get("view") or not include.match(props.get("path", "")):
                continue
            params = sorted((ext_endpoints.get(node["id"]) or {}).get("params", []), key=lambda p: p["index"])
            path_names = re.findall(r"\{([^}/]+)\}", props["path"])
            path_types = [p["type"] for p in params if p["kind"] == "PathVariable"]
            path_vars = [self._field(name, "path", path_types[i] if i < len(path_types) else "java.lang.String", True)
                         for i, name in enumerate(path_names)]
            body_param = next((p for p in params if p["kind"] == "RequestBody"), None)
            body_type = body_param["type"] if body_param else None
            body = None
            if body_type and body_type in self.ext.get("dtos", {}):
                body = {f["name"]: self._field(f["name"], "body", f["type"])
                        for f in self.ext["dtos"][body_type]["fields"]}
            response = (ext_endpoints.get(node["id"]) or {}).get("responseDto")
            dto = self.ext.get("dtos", {}).get(response) if response else None
            result[node["id"]] = _Endpoint(
                node["id"], f"{props['method']} {props['path']}", props["method"], props["path"],
                props.get("handler", "").split("#")[0], path_vars, body, body_type, {}, [],
                {f["name"] for f in dto["fields"]} if dto else None, slug=_slug(f"{props['method']} {props['path']}"))
            for param in params:
                if param["kind"] == "RequestParam":
                    required = param["required"] is True or (param["required"] is None and param["defaultValue"] is None)
                    result[node["id"]].unnamed_query.append(self._field("", "query", param["type"], required))
        return result

    def _map(self, plan) -> _Endpoint | None:
        hits = {call["endpoint"] for call in self.ext.get("calls", [])
                if _simple(call["service"]) == plan["class"] and call["method"] == plan["method"]}
        return self.endpoints.get(next(iter(hits))) if len(hits) == 1 else None

    def _name_query(self, ep: _Endpoint, keyparams) -> None:
        """이름 없는 RequestParam에 key-params `http_name`을 타입·순서로 맞춘다."""
        path_names = {f.name for f in ep.path_vars}
        candidates = [p for p in (keyparams or {}).get("parameters", []) if p["http_name"] and p["http_name"] not in path_names]
        remaining = []
        for param in ep.unnamed_query:
            want = _BOXED.get(_simple(param.type), _simple(param.type))
            match = next((c for c in candidates if _BOXED.get(_simple(c["java_type"]), _simple(c["java_type"])) == want), None)
            if match is None:
                remaining.append(param)
                continue
            candidates.remove(match)
            param.name = match["http_name"]
            ep.query[param.name] = param
        ep.unnamed_query = remaining

    def _lookup(self, ep: _Endpoint, name: str) -> _Field | None:
        return (ep.body or {}).get(name) or ep.query.get(name)

    def _creator(self, ep: _Endpoint) -> _Endpoint | None:
        """`P/{v}` 엔드포인트의 선행 생성 요청: 같은 api 집합의 `POST P`."""
        parent = re.sub(r"/\{[^}/]+\}$", "", ep.path)
        if parent == ep.path:
            return None
        return next((e for e in self.endpoints.values() if e.method == CREATE_METHOD and e.path == parent), None)

    # --- 기대 상태 -------------------------------------------------------------------------------

    def _expect(self, expected: str) -> dict | None:
        match = _EXPECTED_PATTERN.search(expected or "")
        if match is None:
            return None
        code = int(match.group(2))
        result = {"strict": code, "class": "2xx" if code < 300 else "4xx", "source": "bbtg", "bbtgCode": code}
        if match.group(1):
            name = _simple(match.group(1))
            hits = [fqn for fqn in self.ext.get("exceptions", {}) if fqn.endswith(("$" + name, "." + name))]
            if len(hits) == 1 and isinstance(self.ext["exceptions"][hits[0]].get("status"), int):
                status = self.ext["exceptions"][hits[0]]["status"]
                result.update(strict=status, graphStatus=status, source="graph", **{"class": "2xx" if status < 300 else "4xx"})
        return result

    def _not_found(self, ep: _Endpoint) -> dict:
        status = RESPONSE_BUILDER_STATUS["notFound"]
        for info in self.ext.get("exceptions", {}).values():
            handler = info.get("handler") or ""
            if info.get("status") == status and ep.controller and handler.startswith((ep.controller + "$", ep.controller + "#")):
                return {"strict": status, "class": "4xx", "source": "graph", "graphStatus": status}
        return {"strict": "4xx", "class": "4xx", "source": "rule"}

    # --- 제약 변환 -------------------------------------------------------------------------------

    def _constant(self, name: str, owner: str):
        candidates = [c for c in self.ext.get("constants", []) if c["name"] == name]
        own = [c for c in candidates if _simple(c["owner"]) == owner]
        chosen = own[0] if len(own) == 1 else candidates[0] if not own and len(candidates) == 1 else None
        value = chosen.get("value") if chosen else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def _request_fields(self, text: str, ep: _Endpoint, var: str | None, kinds) -> list[str]:
        if not var:
            return []
        names = re.findall(rf"(?<![\w$.]){re.escape(var)}\s*\.\s*([A-Za-z_$][\w$]*)\s*\(\s*\)", text)
        return list(dict.fromkeys(n for n in names if self._lookup(ep, n) and self._lookup(ep, n).kind in kinds))

    def _remap(self, operand: Operand, scalars: dict) -> Operand:
        if operand is not None and operand.kind == "unresolved" and operand.name in scalars:
            return Operand("request", scalars[operand.name], operand.detail)
        return operand

    def _con(self, atom: Atom, ep: _Endpoint, var, scalars, owner) -> _Con | str:
        left, right = self._remap(atom.left, scalars), self._remap(atom.right, scalars)
        op = atom.op
        if left.kind == "unresolved":
            if op in ("<", "<=", ">", ">=") and right is not None and right.kind == "unresolved":
                return self._relation(op, left.name, right.name, ep, var)
            if op == "countGe" and left.detail:
                return "needs-state-transition"
            if op in ("==", "!=") and right is not None and right.kind == "literal" and right.detail == "boolean":
                enums = self._request_fields(left.name, ep, var, ("enum",))
                ep.state_fields.update(enums)
                return "needs-state-transition" if enums and f"{STORED_RECEIVER}." in left.name else "unresolved-operand"
            return "unresolved-operand"
        stored = left.kind == "stored"
        if stored:
            creator = self._creator(ep)
            if creator is None:
                return "no-id-ref"
            fld = (creator.body or {}).get(left.name)
            if fld is None:
                return "unreachable-state"
        elif left.kind == "request":
            fld = self._lookup(ep, left.name)
            if fld is None:
                return "unresolved-operand"
        else:
            return "unresolved-operand"
        base = {"field": fld.name, "stored": stored}
        if op == "countGe":
            if not stored:
                ep.count_fields.add(fld.name)
            if left.detail:
                return "needs-state-transition"
            limit = self._constant(right.name, owner) if right.kind == "constant" else (
                _number(right.name) if right.kind == "literal" and right.detail == "number" else None)
            return _Con(op="count", value=int(limit), **base) if isinstance(limit, (int, float)) and limit >= 1 else "unresolved-operand"
        if op in ("==null", "!=null"):
            return _Con(op="null" if op == "==null" else "notnull", **base)
        if op == "matchesNot":
            if right.kind != "constant":
                return "unresolved-operand"
            return _Con(op="fmt", value=right.name, **base) if EMAIL_TOKEN in right.name.split("_") else "format-unknown"
        if op == "equalsLit":
            return _Con(op="eqlit", value=right.name, **base)
        if op in ("isAfterNot", "isBefore"):
            offset = self._clock(right, fld)
            return _Con(op="<=" if op == "isAfterNot" else "<", value=offset, date=True, extra=op == "isAfterNot", **base) \
                if isinstance(offset, int) else offset
        if op not in ("<", "<=", ">", ">=", "==", "!="):
            return "unresolved-operand"
        if right.kind == "clock":
            offset = self._clock(right, fld)
            return _Con(op=op, value=offset, date=True, **base) if isinstance(offset, int) else offset
        if right.kind == "enum":
            if fld.kind != "enum" or right.name not in fld.constants or op not in ("==", "!="):
                return "unresolved-operand"
            return _Con(op=op, value=right.name, **base)
        if right.kind == "literal" and right.detail == "boolean" and op in ("==", "!="):
            return _Con(op=op, value=right.name == "true", **base)
        if right.kind == "literal" and right.detail == "string" and op == "!=":
            return _Con(op="neqlit", value=right.name, **base)
        number = _number(right.name) if right.kind == "literal" and right.detail == "number" else (
            self._constant(right.name, owner) if right.kind == "constant" else None)
        if number is None or not (fld.kind in ("int", "real") or atom.length):
            return "unresolved-operand"
        return _Con(op=op, value=number, length=atom.length, **base)

    def _clock(self, operand: Operand, fld: _Field) -> int | str:
        if operand is None or operand.kind != "clock" or fld.kind != "date":
            return "unresolved-operand"
        shifts = _DAY_SHIFT.findall(operand.detail)
        if _DAY_SHIFT.sub("", operand.detail):
            return "unresolved-operand"  # 일 단위 밖 이동(시간 등)은 기호로 못 낸다
        return sum(int(n) if sign == "plus" else -int(n) for sign, n in shifts)

    def _relation(self, op, left_text, right_text, ep, var) -> _Con | str:
        """산술 관계(피연산자 미해결): 요청 수치 필드가 있는 쪽을 극단값으로 둔다(설계 §5.3)."""
        left = self._request_fields(left_text, ep, var, ("int", "real"))
        right = self._request_fields(right_text, ep, var, ("int", "real"))
        if left:
            side, other, low_violates = left, right_text, op in ("<", "<=")
        elif right:
            side, other, low_violates = right, left_text, op in (">", ">=")
        else:
            return "unresolved-operand"
        violation, valid = (0, LARGE_NUMBER) if low_violates else (LARGE_NUMBER, 0)
        assume = {0: f"{other} > 0", LARGE_NUMBER: f"{other} 유한"}
        return _Con(field=side[0], op="rel", value=(violation, valid), side=tuple(side),
                    assumes=(assume[violation], assume[valid]))

    # --- 값 계산 ---------------------------------------------------------------------------------

    @staticmethod
    def _step(fld: _Field, con: _Con) -> float:
        return REAL_STEP if fld.kind == "real" and not con.length and not con.date else INT_STEP

    def _render(self, fld: _Field, con: _Con, number, provenance, source, transform) -> Value:
        if con.date:
            return Value(f"today{number:+d}" if number else "today", "generic-sentinel", source, transform)
        if con.length:
            seed = hashlib.sha256(f"{fld.name}:{number}".encode()).hexdigest()
            return Value((seed * (number // 64 + 1))[:number], provenance, source, f"length={number}")
        number = round(number, 2) if fld.kind == "real" else int(number)
        return Value(number, provenance, source, transform)

    def _sides(self, ep: _Endpoint, con: _Con, source: str):
        """(위반 값 목록, 유효 경계 값). 값은 Value 또는 자리표시(_BASE 등). 만들 수 없으면 사유 문자열."""
        fld = self._field_of(ep, con)
        if con.op in ("<", "<=", ">", ">=", "==", "!=") and isinstance(con.value, (int, float)) and not isinstance(con.value, bool):
            step = self._step(fld, con)
            a = con.value
            table = {"<": ([a - step], a), "<=": ([a] + ([a - step] if con.extra else []), a + step),
                     ">": ([a + step], a), ">=": ([a], a - step), "==": ([a], a + step), "!=": ([a + step], a)}
            violations, valid = table[con.op]
            if con.length and min(violations + [valid]) < 0:
                return "unresolved-operand"

            def make(number):
                return self._render(fld, con, number, "input" if number == a else "derived", source,
                                    None if number == a else f"{a}{number - a:+g}".replace("+-", "-"))
            return [make(v) for v in violations], make(valid)
        if con.op in ("==", "!="):  # enum·boolean
            if isinstance(con.value, bool):
                hit, miss = Value(con.value, "input", source), Value(not con.value, "derived", source, "negate")
            else:
                other = next((c for c in self._enum_order(ep, fld) if c != con.value), None)
                if other is None:
                    return "unresolved-operand"
                hit, miss = Value(con.value, "input", source), Value(other, "input", f"graph:{ep.id}", "other-constant")
            return ([hit], miss) if con.op == "==" else ([miss], hit)
        if con.op == "null":
            return [Value(None, "input", source, "null")], _BASE
        if con.op == "notnull":
            return [_BASE], Value(None, "input", source, "null")
        if con.op == "fmt":
            return [Value(EMAIL_INVALID, "generic-sentinel", source, "format-heuristic")], \
                Value(EMAIL_VALID, "generic-sentinel", source, "format-heuristic")
        if con.op in ("eqlit", "neqlit"):
            hit, miss = Value(con.value, "input", source), Value(UNIQ, "generic-sentinel", source)
            return ([hit], miss) if con.op == "eqlit" else ([miss], hit)
        if con.op == "rel":
            violation, valid = con.value
            return [Value(violation, "generic-sentinel", source)], Value(valid, "generic-sentinel", source)
        if con.op == "count":
            return [_KEEP], _KEEP
        return "unresolved-operand"

    def _field_of(self, ep: _Endpoint, con: _Con) -> _Field:
        if con.stored:
            return self._creator(ep).body[con.field]
        return self._lookup(ep, con.field)

    def _enum_order(self, ep: _Endpoint, fld: _Field) -> list:
        """결합 제약이 적은 상수 순(같으면 선언 순)."""
        coupling = dict.fromkeys(fld.constants, 0)
        for _, cons in ep.error_disjuncts:
            for con in cons:
                if con.field == fld.name and not con.stored and con.op == "==" and con.value in coupling and len(cons) > 1:
                    coupling[con.value] += 1
        return sorted(fld.constants, key=lambda c: (coupling[c], fld.constants.index(c)))

    def _field_cons(self, ep: _Endpoint, name: str) -> list[_Con]:
        return [con for _, cons in ep.error_disjuncts for con in cons
                if not con.stored and (con.field == name or name in con.side)]

    def _base(self, ep: _Endpoint, fld: _Field, ignore_null=False):
        """baseline 값: (Value | _OMIT, assumes, 사유|None). 필드에 걸린 모든 원자식을 거짓으로 만든다."""
        cons = self._field_cons(ep, fld.name)
        update_like = bool(ep.path_vars) and ep.body is not None and fld.loc == "body"
        if not cons and ((update_like and not fld.primitive) or (fld.loc == "query" and not fld.required)):
            return _OMIT, [], None
        if not ignore_null and any(c.op == "notnull" for c in cons):
            return _OMIT, [], None
        rel = [c for c in cons if c.op == "rel"]
        if rel:
            return Value(rel[0].value[1], "generic-sentinel", None, "relation-satisfy"), [rel[0].assumes[1]], None
        if any(c.op == "fmt" for c in cons):
            return Value(EMAIL_VALID, "generic-sentinel", None, "format-heuristic"), ["format-heuristic"], None
        if fld.kind == "enum":
            forced = [c.value for c in cons if c.op == "!="]
            banned = {c.value for c in cons if c.op == "=="}
            choice = forced[0] if forced else next((c for c in self._enum_order(ep, fld) if c not in banned), None)
            return (Value(choice, "input", f"graph:{ep.id}"), [], None) if choice else (_OMIT, [], "unresolved-operand")
        if fld.kind == "bool":
            value = next((not c.value for c in cons if c.op == "=="), next((c.value for c in cons if c.op == "!="), False))
            return Value(value, "generic-sentinel"), [], None
        numeric = [c for c in cons if c.op in ("<", "<=", ">", ">=", "==", "!=") and not isinstance(c.value, (bool, str))]
        if numeric:
            lo = hi = None
            for con in numeric:
                step = self._step(fld, con)
                bound = {"<": ("lo", con.value), "<=": ("lo", con.value + step), ">": ("hi", con.value),
                         ">=": ("hi", con.value - step), "!=": ("eq", con.value)}.get(con.op)
                if bound is None:
                    continue
                if bound[0] in ("lo", "eq"):
                    lo = bound[1] if lo is None else max(lo, bound[1])
                if bound[0] in ("hi", "eq"):
                    hi = bound[1] if hi is None else min(hi, bound[1])
            spread = self._spread(ep, fld, lo, hi)
            if spread is not None:
                return Value(spread, "derived", None, "spread(sha256(caseId))"), [], None
            number = lo if lo is not None else hi
            if number is not None:
                con = numeric[0]
                return self._render(fld, con, number, "input" if number in [c.value for c in numeric] else "derived",
                                    None, None), [], None
        if any(c.op in ("eqlit", "neqlit") for c in cons):
            literal = next((c.value for c in cons if c.op == "neqlit"), None)
            return (Value(literal, "input") if literal is not None else Value(UNIQ, "generic-sentinel")), [], None
        defaults = {"string": UNIQ, "int": 1, "real": LARGE_NUMBER, "date": "today+7", "bool": False}
        if fld.kind not in defaults:
            return _OMIT, [], None
        return Value(defaults[fld.kind], "generic-sentinel", None, "type-default"), [], None

    def _spread(self, ep: _Endpoint, fld: _Field, lo, hi) -> _Spread | None:
        """count 조건 인자로 쓰이는 정수 필드만 분산한다. 경계 케이스가 쓰는 값은 뺀다."""
        if fld.kind != "int" or lo is None or hi is None or hi <= lo:
            return None
        if fld.name not in ep.count_fields:
            return None
        used = set()
        for con in self._field_cons(ep, fld.name):
            if con.op in ("<", "<=", ">", ">=", "==", "!="):
                sides = self._sides(ep, con, "")
                if not isinstance(sides, str):
                    used.update(v.value for v in sides[0] + [sides[1]] if isinstance(v, Value))
        excluded = tuple(sorted(v for v in used if isinstance(v, int) and lo <= v <= hi))
        return _Spread(int(lo), int(hi), excluded) if hi - lo + 1 > len(excluded) else None

    def _baseline(self, ep: _Endpoint) -> dict:
        if ep.id not in self.baselines:
            fields = list((ep.body or {}).values()) + list(ep.query.values())
            self.baselines[ep.id] = {(f.loc, f.name): self._base(ep, f) for f in fields}
        return self.baselines[ep.id]

    # --- 평가(충돌 점검) --------------------------------------------------------------------------

    @staticmethod
    def _holds(con: _Con, value) -> bool | None:
        raw = None if value is _OMIT else value.value if isinstance(value, Value) else value
        if con.op == "null":
            return raw is None
        if con.op == "notnull":
            return raw is not None
        if raw is None or isinstance(raw, (_Uniq, _Spread)) or con.op in ("count", "rel"):
            return None
        if con.op == "fmt":
            return {EMAIL_INVALID: True, EMAIL_VALID: False}.get(raw)
        if con.op in ("eqlit", "neqlit"):
            return (raw == con.value) == (con.op == "eqlit")
        if con.date:
            match = re.fullmatch(r"today([+-]\d+)?", str(raw))
            raw = int(match.group(1) or 0) if match else None
        elif con.length:
            raw = len(raw) if isinstance(raw, str) else None
        if raw is None:
            return None
        if isinstance(con.value, (str, bool)):
            return (raw == con.value) == (con.op == "==")
        if isinstance(raw, (str, bool)):
            return None
        return {"<": raw < con.value, "<=": raw <= con.value, ">": raw > con.value, ">=": raw >= con.value,
                "==": raw == con.value, "!=": raw != con.value}[con.op]

    def _violated(self, disjuncts, body, query, stored, skip=None) -> list[str]:
        hits = []
        for addr, cons in disjuncts:
            if addr == skip or addr.endswith("~"):
                continue
            values = [stored.get(c.field, _OMIT) if c.stored else body.get(c.field, query.get(c.field, _OMIT)) for c in cons]
            if all(self._holds(c, v) is True for c, v in zip(cons, values, strict=True)):
                hits.append(addr)
        return sorted(set(hits))

    # --- 계획 항목 -------------------------------------------------------------------------------

    def _items(self, plan, keyparams) -> list[dict]:
        items = [dict(item, addr=f"{plan['file']}#{item['index']}@{item['conditionSha'][:12]}") for item in plan["items"]]
        seen = {re.sub(r"\s+", "", item["condition"]) for item in items}
        for p_index, param in enumerate((keyparams or {}).get("parameters", [])):
            for r_index, reason in enumerate(param["reasons"]):
                normalized = re.sub(r"\s+", "", reason["detail"])
                if reason["type"] != BRANCH_REASON or not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                items.append({"condition": reason["detail"], "expected": "", "branch_value": "", "param": "",
                              "addr": f"{keyparams['file']}#{p_index}.{r_index}@{_sha12(reason['detail'])}"})
        return items

    def _skip(self, addr, reason, ep=None, rule="item") -> None:
        self.unresolved.append({"source": addr, "reason": reason, "endpoint": ep.label if ep else None, "rule": rule})

    def _plan(self, plan) -> None:
        keyparams = self.keyparams.get((plan["class"], plan["method"]))
        ep = self._map(plan)
        items = self._items(plan, keyparams)
        if ep is None:
            for item in items:
                self._skip(item["addr"], "no-endpoint-mapping")
            return
        if not ep.mapped:
            ep.mapped, ep.slug = True, _slug(plan["method"])
            self._name_query(ep, keyparams)
        body_simple = _simple(ep.body_type) if ep.body_type else None
        var = next((p["accessor"] for p in (keyparams or {}).get("parameters", [])
                    if body_simple and _simple(p["java_type"]) == body_simple), None)
        scalars = {}
        for param in (keyparams or {}).get("parameters", []):
            target = param["http_name"] if param["http_name"] in ep.query else param["name"] if param["name"] in (ep.body or {}) else None
            for alias in {param["name"], param["accessor"]} - {"", var}:
                if target:
                    scalars[alias] = target
        no_keyparams = keyparams is None and any(m.startswith("keyparams") for m in self.missing)
        parsed_items = []
        for item in items:
            addr = item["addr"]
            if item["branch_value"] == NO_DATA_MARK:
                self._no_data(ep, item, scalars)
            elif item["branch_value"] == EMPTY_BODY_MARK:
                if ep.body_type is None:
                    self._skip(addr, "no-body-schema", ep)
                else:
                    expect = {"strict": "4xx", "class": "4xx", "source": "rule"}
                    graph = self._expect(item["expected"]) or {}
                    expect.update({k: graph[k] for k in ("bbtgCode", "graphStatus") if k in graph})
                    self._add(_Draft(ep, "empty-body", [addr], (addr, 0, 0, 0), expect=expect, oracle="framework-reject"))
            elif not _CONDITION_SIGNS.search(item["condition"]):
                self._skip(addr, "no-condition", ep)
            else:
                parsed = parse(item["condition"], var)
                if parsed.disjuncts is None:
                    self._skip(addr, "unparsed", ep)
                    continue
                expect = self._expect(item["expected"])
                disjuncts = []
                for atoms in parsed.disjuncts:
                    cons = [self._con(atom, ep, var, scalars, plan["class"]) for atom in atoms]
                    reasons = [c for c in cons if isinstance(c, str)]
                    if no_keyparams and "unresolved-operand" in reasons:
                        reasons.append("input-missing")
                    fields = [(c.stored, c.field) for c in cons if not isinstance(c, str)]
                    if not reasons and len(set(fields)) != len(fields):
                        reasons.append("unresolved-operand")  # 한 논리곱에서 같은 필드를 두 번 묶는 식은 다루지 않는다
                    disjuncts.append((cons, _best_reason(reasons) if reasons else None))
                    ok = [c for c in cons if not isinstance(c, str)]
                    if expect is None:
                        ep.branch_disjuncts.append((addr, ok))
                    else:
                        if ok and not reasons:
                            ep.error_disjuncts.append((addr, ok))
                        elif ok:  # 미해결 논리곱이라도 baseline 제약(원자식별 거짓)에는 쓴다
                            ep.error_disjuncts.append((addr + "~", [c for c in ok if c.op not in ("count",)]))
                parsed_items.append((item, expect, disjuncts))
        for item, expect, disjuncts in parsed_items:
            for d_index, (cons, reason) in enumerate(disjuncts):
                self._expand(ep, item, expect, d_index, cons, reason)
        for _ in ep.unnamed_query:  # 이름을 못 얻은 query 파라미터 하나 = 생성 불가 슬롯 하나
            self._skip(f"graph:{ep.id}", "param-name-unknown", ep, "param")

    def _no_data(self, ep: _Endpoint, item, scalars) -> None:
        param = item["param"]
        if param in {f.name for f in ep.path_vars}:
            draft = self.nodata.get(ep.id)
            if draft is None:
                draft = _Draft(ep, "no-data", [], (item["addr"], 0, 0, 0), expect=self._not_found(ep), path_mode="missing")
                self.nodata[ep.id] = draft
                self._add(draft)
            draft.sources.append(item["addr"])
            return
        name = scalars.get(param, param)
        fld = ep.query.get(name)
        if fld is None:
            self._skip(item["addr"], "param-name-unknown", ep)
            return
        empty = {"int": LARGE_NUMBER, "real": LARGE_NUMBER, "bool": True, "date": "today+7"}.get(fld.kind)
        value = Value(fld.constants[-1], "input", f"graph:{ep.id}") if fld.kind == "enum" else (
            Value(empty, "generic-sentinel", None, "empty-filter") if empty is not None else Value(UNIQ, "generic-sentinel"))
        self._add(_Draft(ep, "filter-empty", [item["addr"]], (item["addr"], 0, 0, 0), targets={("query", name): value},
                         expect={"strict": "2xx", "class": "2xx", "source": "rule"}, oracle="status-only"))

    def _expand(self, ep, item, expect, d_index, cons, reason) -> None:
        addr = item["addr"]
        valid_expect = {"strict": "2xx", "class": "2xx", "source": "rule"}
        if expect is None:  # 분기 진입(예외 없음): 조건 참 1건, 상태로 구별 불가
            draft = _Draft(ep, "branch-entry", [addr], (addr, d_index, 0, 0), expect=valid_expect, oracle="status-only")
            sides = [] if reason else [self._sides(ep, c, addr) for c in cons]
            draft.reason = reason or next((s for s in sides if isinstance(s, str)), None)
            if draft.reason is None:
                self._fill(draft, ep, cons, sides, None)
            self._add(draft)
            return
        sides = [] if reason else [self._sides(ep, c, addr) for c in cons]
        reason = reason or next((s for s in sides if isinstance(s, str)), None)
        violation_count = len(sides[0][0]) if not reason and len(cons) == 1 else 1
        boundary_keys = [(addr, d_index, 1, i) for i in range(len(cons))]
        for variant in range(violation_count):
            draft = _Draft(ep, "violation", [addr], (addr, d_index, 0, variant), expect=dict(expect),
                           pair_key=boundary_keys[-1], reason=reason)
            if not reason:
                self._fill(draft, ep, cons, sides, None, variant)
                if any(c.op == "null" and self._field_of(ep, c).primitive for c in cons):
                    draft.oracle = "framework-reject"
                    draft.expect.update(strict="4xx", **{"class": "4xx"})
            self._add(draft)
        for index, key in enumerate(boundary_keys):
            draft = _Draft(ep, "valid-boundary", [addr], key, expect=dict(valid_expect), reason=reason)
            if not reason:
                self._fill(draft, ep, cons, sides, index)
            self._add(draft)

    def _fill(self, draft, ep, cons, sides, flip, variant=0) -> None:
        """논리곱의 원자식 값을 초안에 넣는다. flip이 정해지면 그 원자식만 유효 경계로 뒤집는다."""
        for index, (con, (violations, valid)) in enumerate(zip(cons, sides, strict=True)):
            value = valid if index == flip else violations[variant if len(cons) == 1 else 0]
            if con.op == "count":
                draft.priors = con.value - 1 if index == flip else con.value
                continue
            targets = draft.stored if con.stored else draft.targets
            names = con.side if con.op == "rel" else (con.field,)
            for name in names:
                targets[name if con.stored else (self._lookup(ep, name).loc, name)] = value
            if con.op == "rel":
                draft.assumes.append(con.assumes[1] if index == flip else con.assumes[0])
            if con.op == "fmt":
                draft.assumes.append("format-heuristic")

    def _add(self, draft: _Draft) -> None:
        self.drafts.append(draft)

    # --- 그래프·하네스 규칙 -------------------------------------------------------------------------

    def _graph_rules(self) -> None:
        login = " ".join((self.harness.get("login") or "").split())
        protected = any(h.get("required") for h in self.auth.get("required_headers", []))
        for ep in self.endpoints.values():
            source = f"graph:{ep.id}"
            if ep.path_vars:
                if ep.id in self.nodata:
                    self.nodata[ep.id].sources.append(source)
                else:
                    self._add(_Draft(ep, "no-data", [source], (source, 0, 0, 0), path_mode="missing",
                                     expect=self._not_found(ep)))
            if protected and ep.label != login:
                self._add(_Draft(ep, "auth", ["harness:unauthenticatedStatus", source], (source, 0, 0, 0),
                                 path_mode="missing", assumes=["보호됨"],
                                 expect={"strict": self.harness.get("unauthenticatedStatus"), "class": "4xx",
                                         "source": "harness-config"}))
            if ep.body_type is not None and ep.body is None and not ep.mapped and ep.method != "GET":
                self._skip(source, "no-body-schema", ep, "happy")
            for fld in [f for f in list((ep.body or {}).values()) + list(ep.query.values()) if f.kind == "enum"]:
                base = self._baseline(ep).get((fld.loc, fld.name), (_OMIT,))[0]
                chosen = base.value if isinstance(base, Value) else None
                for position, constant in enumerate(fld.constants):
                    if constant == chosen:
                        continue
                    draft = _Draft(ep, "enum-value", [source], (source, 1, position, 0),
                                   targets={(fld.loc, fld.name): Value(constant, "input", source)},
                                   expect={"strict": "2xx", "class": "2xx", "source": "rule"})
                    if fld.name in ep.state_fields:
                        draft.reason = "needs-state-transition"
                    self._add(draft)

    def _late_rules(self) -> None:
        """위반 case가 생긴 엔드포인트의 baseline-valid, 그리고 그 밖의 GET에 R-HAPPY."""
        with_violation = {d.ep.id for d in self.drafts if d.rule == "violation" and d.reason is None}
        late = []
        for ep in self.endpoints.values():
            source = f"graph:{ep.id}"
            valid = {"strict": "2xx", "class": "2xx", "source": "rule"}
            if ep.id in with_violation:
                addrs = sorted({addr.rstrip("~") for addr, _ in ep.error_disjuncts})
                late.append(_Draft(ep, "baseline-valid", [source] + addrs, (source, 0, 0, 0), expect=valid))
            elif ep.method == "GET" and (ep.body_type is None):
                late.append(_Draft(ep, "happy", [source], (source, 0, 0, 0), expect=valid))
        for draft in late:
            self._materialize(draft)
            self._add(draft)

    # --- 구체화 ----------------------------------------------------------------------------------

    def _materialize(self, draft: _Draft) -> None:
        """1차 구체화: 값·선행 요청을 채우고 충돌을 점검한다. 실패하면 draft.reason을 정한다."""
        if draft.reason or draft.case:
            return
        ep, reasons, assumes = draft.ep, [], list(draft.assumes)
        body, query, path, setup = {}, {}, {}, []
        bare = draft.rule == "auth"
        if draft.rule not in ("empty-body", "auth") and ep.body_type is not None:
            if ep.body is None:
                if draft.rule != "no-data":  # 없는 id 조회는 본문 없이도 4xx를 기대한다
                    reasons.append("no-body-schema")
            else:
                for name, fld in ep.body.items():
                    value, extra, reason = self._value(ep, fld, draft.targets.get(("body", name)))
                    assumes += extra
                    reasons += [reason] if reason else []
                    if value is not _OMIT:
                        body[name] = value
        if not bare:
            for name, fld in ep.query.items():
                value, extra, reason = self._value(ep, fld, draft.targets.get(("query", name)))
                assumes += extra
                reasons += [reason] if reason else []
                if value is not _OMIT:
                    query[name] = value
            if any(f.required for f in ep.unnamed_query):
                reasons.append("param-name-unknown")
        if any(name in ep.state_fields and (v == _BASE or isinstance(v, Value) and v.value is not None)
               for (loc, name), v in draft.targets.items() if loc == "body"):
            reasons.append("needs-state-transition")  # 상태 전이 규칙을 모르면 상태 필드에 구체 상수를 넣을 수 없다
        stored_values = {}
        for var in ep.path_vars:
            if draft.path_mode == "missing":
                path[var.name] = Value(LARGE_NUMBER if var.kind in ("int", "real", "other") else UNIQ,
                                       "generic-sentinel", None, "nonexistent-id")
                continue
            creator = self._creator(ep)
            capture = None
            if creator is not None and creator.response_fields:
                if var.name in creator.response_fields:
                    capture = var.name
                elif var.name.endswith(ID_SUFFIX) and ID_FIELD in creator.response_fields:
                    capture = ID_FIELD
            if capture is None:
                reasons.append("no-id-ref")
                continue
            if creator.body is None:
                reasons.append("no-body-schema")
                continue
            if not setup:
                values = {}
                for name, fld in creator.body.items():
                    value, extra, reason = self._value(creator, fld, draft.stored.get(name))
                    assumes += extra
                    reasons += [reason] if reason else []
                    if value is not _OMIT:
                        values[name] = value
                if self._violated(creator.error_disjuncts, values, {}, {}):
                    reasons.append("unreachable-state")  # 선행 생성이 거부될 값(저장 상태 설정 불가)
                stored_values = values
                setup.append({"endpoint": creator.label, "values": values, "capture": {}})
            setup[0]["capture"][var.name] = capture
            path[var.name] = Value(f"ref:{var.name}", "input", f"graph:{creator.id}", f"capture {capture}")
        for _ in range(draft.priors):
            setup.append({"endpoint": ep.label, "values": body, "capture": {}})
        if reasons:
            draft.reason = _best_reason(reasons)
            return
        # 본문을 보내지 않거나 서버 진입 전 거부를 기대하는 규칙은 다른 조건과의 충돌을 따지지 않는다
        hits = [] if draft.rule in ("auth", "empty-body", "no-data") else self._violated(
            ep.error_disjuncts, body, query, stored_values, skip=draft.sources[0] if draft.rule == "violation" else None)
        if draft.rule in _VALID_RULES and hits:
            draft.reason = "unreachable-state"  # 다른 조건이 같은 필드를 막아 유효 요청을 만들 수 없다
            return
        assumes += [f"also-violates:{h}" for h in hits]
        checked = sorted({addr.rstrip("~") for addr, _ in ep.error_disjuncts} - set(hits) - set(draft.sources))
        draft.case = Case("", ep.label, draft.rule, list(draft.sources), body, query, path, setup,
                          "anonymous" if draft.rule == "auth" else "authed", draft.expect,
                          draft.oracle, sorted(set(assumes)), checked + sorted(set(assumes)), None)

    def _value(self, ep, fld, target):
        """(값|_OMIT, assumes, 사유). target이 `_BASE`면 null 규칙을 무시한 baseline 값."""
        if isinstance(target, Value):
            return target, [], None
        if target == _BASE:
            return self._base(ep, fld, ignore_null=True)
        return self._baseline(ep)[(fld.loc, fld.name)]

    # --- 마무리 ----------------------------------------------------------------------------------

    def _finalize(self, draft: _Draft, case_id: str) -> None:
        case = draft.case
        case.id = case_id
        seen = {}

        def resolve(value):
            if not isinstance(value, Value):
                return value
            if isinstance(value.value, _Uniq):
                return Value(f"uniq:{case_id}", value.provenance, value.source, value.transform)
            if isinstance(value.value, _Spread):
                if id(value) not in seen:
                    spread = value.value
                    index = int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % (spread.hi - spread.lo + 1 - len(spread.excluded))
                    number = spread.lo + index
                    for excluded in spread.excluded:
                        number += 1 if excluded <= number else 0
                    seen[id(value)] = Value(number, value.provenance, value.source, value.transform)
                return seen[id(value)]
            return Value(value.value, value.provenance, value.source, value.transform)  # case마다 독립 사본

        for mapping in (case.values, case.query, case.path):
            mapping.update({k: resolve(v) for k, v in mapping.items()})
        case.setup = [dict(step, values={k: resolve(v) for k, v in step["values"].items()}, capture=dict(step["capture"]))
                      for step in case.setup]

    def run(self) -> Derivation:
        for plan in sorted(self.plans, key=lambda p: p["file"]):
            self._plan(plan)
        for name in self.missing:
            self._skip(f"input:{name}", "input-missing")
        self._graph_rules()
        for draft in self.drafts:
            self._materialize(draft)
        self._late_rules()
        made = sorted((d for d in self.drafts if d.reason is None), key=lambda d: (d.ep.slug, d.rule, d.ep.id, d.key))
        counters: dict[tuple, int] = {}
        by_key = {}
        for draft in made:
            group = (draft.ep.slug, draft.rule)
            counters[group] = counters.get(group, 0) + 1
            self._finalize(draft, f"{draft.ep.slug}-{draft.rule}-{counters[group]}")
            by_key[(draft.ep.id, draft.key)] = draft.case.id
        for draft in made:
            if draft.rule == "violation" and draft.pair_key is not None:
                draft.case.pair = by_key.get((draft.ep.id, draft.pair_key))
        for draft in self.drafts:
            if draft.reason is not None:
                self._skip(draft.sources[0], draft.reason, draft.ep, draft.rule)
        self.unresolved.sort(key=lambda e: (e["source"], e["rule"], e["reason"], e["endpoint"] or ""))
        cases = [d.case for d in made]
        return Derivation(cases, self.unresolved, self._universe(cases))

    def _universe(self, cases) -> dict:
        by_reason = dict.fromkeys(REASONS, 0)
        for entry in self.unresolved:
            by_reason[entry["reason"]] += 1
        by_rule: dict[str, int] = {}
        for case in cases:
            by_rule[case.rule] = by_rule.get(case.rule, 0) + 1
        factors, terms, total = [], [], 0
        for ep in self.endpoints.values():
            fields = {}
            for fld in ep.path_vars + list((ep.body or {}).values()) + list(ep.query.values()):
                # count는 해석 여부(상태 전제)와 무관하게 한 클래스로 센다
                classes = {("count",) if c.op == "count" else (c.op, str(c.value), c.length, c.date)
                           for _, cons in ep.error_disjuncts + ep.branch_disjuncts
                           for c in cons if not c.stored and (c.field == fld.name if c.op != "rel" else c.side[0] == fld.name)}
                classes |= {("count",)} if fld.name in ep.count_fields and fld.loc != "path" else set()
                fields[f"{fld.loc}.{fld.name}"] = 1 + len(classes)
            product = 1
            for count in fields.values():
                product *= count
            total += product
            factors.append({"endpoint": ep.label, "fields": fields, "product": product})
            terms.append("*".join(str(v) for v in fields.values()) or "1")
        return {"bySlot": {"total": len(cases) + len(self.unresolved), "generated": len(cases),
                           "unresolved": len(self.unresolved), "byReason": by_reason},
                "byRule": dict(sorted(by_rule.items())),
                "theoretical": {"value": total, "formula": "Σ_endpoint Π_field (1 + 위반 클래스 수(field)) = " + " + ".join(terms),
                                "factors": factors}}


def derive(bundle: Bundle) -> Derivation:
    """det 번들에서 케이스·생성 불가 슬롯·모수를 도출한다. 같은 번들이면 결과가 같다."""
    return _Deriver(bundle).run()
