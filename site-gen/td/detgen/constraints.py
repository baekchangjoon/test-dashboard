"""원자식 → 필드 제약, 위반값·유효 경계, baseline, 분산, 평가(설계 §5.2 연산자 정규화 표, §5.3 baseline).

파서(`td.detgen.parse`)의 원자식을 엔드포인트 필드에 대한 정규화 제약(`Con`)으로 바꾸고, 제약마다 위반 값과 유효 경계 값을 계산한다.
수치 리터럴은 §5.6의 것만 쓴다(`LARGE_NUMBER`, step 1·0.01, 형식 휴리스틱).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from td.detgen.endpoints import Catalog, Endpoint, Field
from td.detgen.parse import STORED_RECEIVER, Atom, Operand

# §5.6 허용 리터럴
LARGE_NUMBER = 1000000
INT_STEP = 1
REAL_STEP = 0.01
EMAIL_TOKEN = "EMAIL"
EMAIL_VALID = "uniq@example.com"
EMAIL_INVALID = "not-an-email"
_DAY_SHIFT = re.compile(r"\.(plus|minus)Days\((\d+)\)")
_NUMERIC_OPS = ("<", "<=", ">", ">=", "==", "!=")


@dataclass
class Value:
    value: object
    provenance: Literal["input", "derived", "generic-sentinel"]
    source: str | None = None
    transform: str | None = None


class Uniq:
    """`uniq:<caseId>` 자리표시. case id가 정해진 뒤 확정한다."""


UNIQ = Uniq()
OMIT = object()  # baseline에서 보내지 않는 필드
KEEP = "_KEEP"  # 값을 바꾸지 않는 원자식(count: 선행 건수만 정한다)
BASE = "_BASE"  # null 규칙을 무시한 baseline 값(명시적으로 값을 채워야 하는 자리)


@dataclass(frozen=True)
class Spread:
    """유효 범위 [lo, hi]에서 caseId 해시로 고르는 정수(경계값 집합 제외)."""
    lo: int
    hi: int
    excluded: tuple

    def pick(self, case_id: str) -> int:
        index = int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % (self.hi - self.lo + 1 - len(self.excluded))
        number = self.lo + index
        for excluded in self.excluded:
            number += 1 if excluded <= number else 0
        return number


@dataclass(frozen=True)
class Con:
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


def number(text: str):
    text = re.sub(r"[lLdDfF]$", "", text)
    return float(text) if "." in text else int(text)


class Constraints:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.baselines: dict[str, dict] = {}

    # --- 변환 -------------------------------------------------------------------------------------

    def request_fields(self, text: str, ep: Endpoint, var: str | None, kinds) -> list[str]:
        """원문에서 `<var>.<f>()` 꼴 요청 필드 중 kinds 타입인 것."""
        if not var:
            return []
        names = re.findall(rf"(?<![\w$.]){re.escape(var)}\s*\.\s*([A-Za-z_$][\w$]*)\s*\(\s*\)", text)
        lookup = self.catalog.lookup
        return list(dict.fromkeys(n for n in names if lookup(ep, n) and lookup(ep, n).kind in kinds))

    @staticmethod
    def remap(operand: Operand, scalars: dict) -> Operand:
        """파서가 미해결로 둔 단일 식별자 중 계획 파라미터 이름이면 요청 필드로 바꾼다."""
        if operand is not None and operand.kind == "unresolved" and operand.name in scalars:
            return Operand("request", scalars[operand.name], operand.detail)
        return operand

    def con(self, atom: Atom, ep: Endpoint, var, scalars, owner) -> Con | str:
        """원자식 → Con. 만들 수 없으면 생성 불가 사유 문자열."""
        left, right = self.remap(atom.left, scalars), self.remap(atom.right, scalars)
        op = atom.op
        if left.kind == "unresolved":
            if op in ("<", "<=", ">", ">=") and right is not None and right.kind == "unresolved":
                return self._relation(op, left.name, right.name, ep, var)
            if op == "countGe" and left.detail:
                return "needs-state-transition"
            if op in ("==", "!=") and right is not None and right.kind == "literal" and right.detail == "boolean":
                enums = self.request_fields(left.name, ep, var, ("enum",))
                ep.state_fields.update(enums)
                return "needs-state-transition" if enums and f"{STORED_RECEIVER}." in left.name else "unresolved-operand"
            return "unresolved-operand"
        stored = left.kind == "stored"
        if stored:
            creator = self.catalog.creator(ep)
            if creator is None:
                return "no-id-ref"
            fld = (creator.body or {}).get(left.name)
            if fld is None:
                return "unreachable-state"
        elif left.kind == "request":
            fld = self.catalog.lookup(ep, left.name)
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
            limit = self.catalog.constant(right.name, owner) if right.kind == "constant" else (
                number(right.name) if right.kind == "literal" and right.detail == "number" else None)
            return Con(op="count", value=int(limit), **base) if isinstance(limit, (int, float)) and limit >= 1 else "unresolved-operand"
        if op in ("==null", "!=null"):
            return Con(op="null" if op == "==null" else "notnull", **base)
        if op == "matchesNot":
            if right.kind != "constant":
                return "unresolved-operand"
            return Con(op="fmt", value=right.name, **base) if EMAIL_TOKEN in right.name.split("_") else "format-unknown"
        if op == "equalsLit":
            return Con(op="eqlit", value=right.name, **base)
        if op in ("isAfterNot", "isBefore"):
            offset = self._clock(right, fld)
            return Con(op="<=" if op == "isAfterNot" else "<", value=offset, date=True, extra=op == "isAfterNot", **base) \
                if isinstance(offset, int) else offset
        if op not in _NUMERIC_OPS:
            return "unresolved-operand"
        if right.kind == "clock":
            offset = self._clock(right, fld)
            return Con(op=op, value=offset, date=True, **base) if isinstance(offset, int) else offset
        if right.kind == "enum":
            if fld.kind != "enum" or right.name not in fld.constants or op not in ("==", "!="):
                return "unresolved-operand"
            return Con(op=op, value=right.name, **base)
        if right.kind == "literal" and right.detail == "boolean" and op in ("==", "!="):
            return Con(op=op, value=right.name == "true", **base)
        if right.kind == "literal" and right.detail == "string" and op == "!=":
            return Con(op="neqlit", value=right.name, **base)
        value = number(right.name) if right.kind == "literal" and right.detail == "number" else (
            self.catalog.constant(right.name, owner) if right.kind == "constant" else None)
        if value is None or not (fld.kind in ("int", "real") or atom.length):
            return "unresolved-operand"
        return Con(op=op, value=value, length=atom.length, **base)

    @staticmethod
    def _clock(operand: Operand, fld: Field) -> int | str:
        if operand is None or operand.kind != "clock" or fld.kind != "date":
            return "unresolved-operand"
        shifts = _DAY_SHIFT.findall(operand.detail)
        if _DAY_SHIFT.sub("", operand.detail):
            return "unresolved-operand"  # 일 단위 밖 이동(시간 등)은 기호로 못 낸다
        return sum(int(n) if sign == "plus" else -int(n) for sign, n in shifts)

    def _relation(self, op, left_text, right_text, ep, var) -> Con | str:
        """산술 관계(피연산자 미해결): 요청 수치 필드가 있는 쪽을 극단값으로 둔다(설계 §5.3)."""
        left = self.request_fields(left_text, ep, var, ("int", "real"))
        right = self.request_fields(right_text, ep, var, ("int", "real"))
        if left:
            side, other, low_violates = left, right_text, op in ("<", "<=")
        elif right:
            side, other, low_violates = right, left_text, op in (">", ">=")
        else:
            return "unresolved-operand"
        violation, valid = (0, LARGE_NUMBER) if low_violates else (LARGE_NUMBER, 0)
        assume = {0: f"{other} > 0", LARGE_NUMBER: f"{other} 유한"}
        return Con(field=side[0], op="rel", value=(violation, valid), side=tuple(side),
                   assumes=(assume[violation], assume[valid]))

    # --- 값 계산 ---------------------------------------------------------------------------------

    @staticmethod
    def step(fld: Field, con: Con) -> float:
        return REAL_STEP if fld.kind == "real" and not con.length and not con.date else INT_STEP

    @staticmethod
    def render(fld: Field, con: Con, value, provenance, source, transform) -> Value:
        if con.date:
            return Value(f"today{value:+d}" if value else "today", "generic-sentinel", source, transform)
        if con.length:
            seed = hashlib.sha256(f"{fld.name}:{value}".encode()).hexdigest()
            return Value((seed * (value // 64 + 1))[:value], provenance, source, f"length={value}")
        value = round(value, 2) if fld.kind == "real" else int(value)
        return Value(value, provenance, source, transform)

    def field_of(self, ep: Endpoint, con: Con) -> Field:
        if con.stored:
            return self.catalog.creator(ep).body[con.field]
        return self.catalog.lookup(ep, con.field)

    def sides(self, ep: Endpoint, con: Con, source: str):
        """(위반 값 목록, 유효 경계 값). 값은 Value 또는 자리표시(BASE·KEEP). 만들 수 없으면 사유 문자열."""
        fld = self.field_of(ep, con)
        if con.op in _NUMERIC_OPS and isinstance(con.value, (int, float)) and not isinstance(con.value, bool):
            step = self.step(fld, con)
            a = con.value
            table = {"<": ([a - step], a), "<=": ([a] + ([a - step] if con.extra else []), a + step),
                     ">": ([a + step], a), ">=": ([a], a - step), "==": ([a], a + step), "!=": ([a + step], a)}
            violations, valid = table[con.op]
            if con.length and min(violations + [valid]) < 0:
                return "unresolved-operand"

            def make(value):
                return self.render(fld, con, value, "input" if value == a else "derived", source,
                                   None if value == a else f"{a}{value - a:+g}".replace("+-", "-"))
            return [make(v) for v in violations], make(valid)
        if con.op in ("==", "!="):  # enum·boolean
            if isinstance(con.value, bool):
                hit, miss = Value(con.value, "input", source), Value(not con.value, "derived", source, "negate")
            else:
                other = next((c for c in self.enum_order(ep, fld) if c != con.value), None)
                if other is None:
                    return "unresolved-operand"
                hit, miss = Value(con.value, "input", source), Value(other, "input", f"graph:{ep.id}", "other-constant")
            return ([hit], miss) if con.op == "==" else ([miss], hit)
        if con.op == "null":
            return [Value(None, "input", source, "null")], BASE
        if con.op == "notnull":
            return [BASE], Value(None, "input", source, "null")
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
            return [KEEP], KEEP
        return "unresolved-operand"

    @staticmethod
    def enum_order(ep: Endpoint, fld: Field) -> list:
        """결합 제약이 적은 상수 순(같으면 선언 순)."""
        coupling = dict.fromkeys(fld.constants, 0)
        for _, cons in ep.error_disjuncts:
            for con in cons:
                if con.field == fld.name and not con.stored and con.op == "==" and con.value in coupling and len(cons) > 1:
                    coupling[con.value] += 1
        return sorted(fld.constants, key=lambda c: (coupling[c], fld.constants.index(c)))

    @staticmethod
    def field_cons(ep: Endpoint, name: str) -> list[Con]:
        return [con for _, cons in ep.error_disjuncts for con in cons
                if not con.stored and (con.field == name or name in con.side)]

    def base(self, ep: Endpoint, fld: Field, ignore_null=False):
        """baseline 값: (Value | OMIT, assumes, 사유|None). 필드에 걸린 모든 원자식을 거짓으로 만든다.

        ignore_null이면(값을 꼭 채워야 하는 자리) null·생략 규칙을 건너뛴다.
        """
        cons = self.field_cons(ep, fld.name)
        update_like = bool(ep.path_vars) and ep.body is not None and fld.loc == "body"
        if not ignore_null:
            if update_like and not fld.primitive:
                return OMIT, [], None  # update 계열 boxed 필드는 최소 요청(대상 필드만 채운다, §5.3)
            if fld.loc == "query" and not fld.required and not cons:
                return OMIT, [], None
            if any(c.op == "notnull" for c in cons):
                return OMIT, [], None
        rel = [c for c in cons if c.op == "rel"]
        if rel:
            return Value(rel[0].value[1], "generic-sentinel", None, "relation-satisfy"), [rel[0].assumes[1]], None
        if any(c.op == "fmt" for c in cons):
            return Value(EMAIL_VALID, "generic-sentinel", None, "format-heuristic"), ["format-heuristic"], None
        if fld.kind == "enum":
            forced = [c.value for c in cons if c.op == "!="]
            banned = {c.value for c in cons if c.op == "=="}
            choice = forced[0] if forced else next((c for c in self.enum_order(ep, fld) if c not in banned), None)
            return (Value(choice, "input", f"graph:{ep.id}"), [], None) if choice else (OMIT, [], "unresolved-operand")
        if fld.kind == "bool":
            value = next((not c.value for c in cons if c.op == "=="), next((c.value for c in cons if c.op == "!="), False))
            return Value(value, "generic-sentinel"), [], None
        numeric = [c for c in cons if c.op in _NUMERIC_OPS and not isinstance(c.value, (bool, str))]
        if numeric:
            found = self._numeric_base(ep, fld, numeric)
            if found is not None:
                return found, [], None
        if any(c.op in ("eqlit", "neqlit") for c in cons):
            literal = next((c.value for c in cons if c.op == "neqlit"), None)
            return (Value(literal, "input") if literal is not None else Value(UNIQ, "generic-sentinel")), [], None
        defaults = {"string": UNIQ, "int": 1, "real": LARGE_NUMBER, "date": "today+7", "bool": False}
        if fld.kind not in defaults:
            return OMIT, [], None
        return Value(defaults[fld.kind], "generic-sentinel", None, "type-default"), [], None

    def _numeric_base(self, ep: Endpoint, fld: Field, numeric: list[Con]) -> Value | None:
        """수치(길이·날짜 포함) 제약을 모두 거짓으로 만드는 유효 경계 중 최솟값 쪽."""
        lo = hi = None
        banned = []
        for con in numeric:
            step = self.step(fld, con)
            if con.op == "==":
                banned.append((con.value, step))
                continue
            kind, bound = {"<": ("lo", con.value), "<=": ("lo", con.value + step), ">": ("hi", con.value),
                           ">=": ("hi", con.value - step), "!=": ("eq", con.value)}[con.op]
            if kind in ("lo", "eq"):
                lo = bound if lo is None else max(lo, bound)
            if kind in ("hi", "eq"):
                hi = bound if hi is None else min(hi, bound)
        spread = self.spread(ep, fld, lo, hi)
        if spread is not None:
            return Value(spread, "derived", None, "spread(sha256(caseId))")
        value = lo if lo is not None else hi
        if value is None and banned:
            value = banned[0][0] + banned[0][1]
        if value is None:
            return None
        value = self._avoid(value, lo, hi, banned)
        return self.render(fld, numeric[0], value, "input" if value in [c.value for c in numeric] else "derived", None, None)

    @staticmethod
    def _avoid(value, lo, hi, banned):
        """`f == a` 위반값을 피해 [lo, hi] 안에서 가장 가까운 값(같은 거리면 위쪽). 범위 안에 없으면 원래 값."""
        if not banned:
            return value
        step = min(s for _, s in banned)
        bad = {a for a, _ in banned}
        for distance in range(len(bad) + 1):
            for candidate in (value + distance * step, value - distance * step):
                inside = (lo is None or candidate >= lo) and (hi is None or candidate <= hi)
                if inside and not any(abs(candidate - a) < step / 2 for a in bad):
                    return round(candidate, 2) if isinstance(step, float) else candidate
        return value

    def spread(self, ep: Endpoint, fld: Field, lo, hi) -> Spread | None:
        """count 조건 인자로 쓰이는 정수 필드만 분산한다. 경계 케이스가 쓰는 값은 뺀다."""
        if fld.kind != "int" or lo is None or hi is None or hi <= lo or fld.name not in ep.count_fields:
            return None
        used = set()
        for con in self.field_cons(ep, fld.name):
            if con.op in _NUMERIC_OPS:
                sides = self.sides(ep, con, "")
                if not isinstance(sides, str):
                    used.update(v.value for v in sides[0] + [sides[1]] if isinstance(v, Value))
        excluded = tuple(sorted(v for v in used if isinstance(v, int) and lo <= v <= hi))
        return Spread(int(lo), int(hi), excluded) if hi - lo + 1 > len(excluded) else None

    def baseline(self, ep: Endpoint) -> dict:
        if ep.id not in self.baselines:
            fields = list((ep.body or {}).values()) + list(ep.query.values())
            self.baselines[ep.id] = {(f.loc, f.name): self.base(ep, f) for f in fields}
        return self.baselines[ep.id]

    def value(self, ep: Endpoint, fld: Field, target):
        """(값|OMIT, assumes, 사유). target이 BASE면 null·생략 규칙을 무시한 baseline 값."""
        if isinstance(target, Value):
            return target, [], None
        if target == BASE:
            return self.base(ep, fld, ignore_null=True)
        return self.baseline(ep)[(fld.loc, fld.name)]

    # --- 평가 ------------------------------------------------------------------------------------

    @staticmethod
    def holds(con: Con, value) -> bool | None:
        """값이 제약(위반 조건)을 참으로 만드는가. 판단할 수 없으면 None."""
        raw = None if value is OMIT else value.value if isinstance(value, Value) else value
        if con.op == "null":
            return raw is None
        if con.op == "notnull":
            return raw is not None
        if raw is None or isinstance(raw, (Uniq, Spread)) or con.op in ("count", "rel") or value in (BASE, KEEP):
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

    def violated(self, disjuncts, body, query, stored, skip=None) -> list[str]:
        """값 묶음이 참으로 만드는(모든 원자식 참) 해석된 오류 논리곱의 주소 목록."""
        hits = []
        for addr, cons in disjuncts:
            if addr == skip or addr.endswith("~"):
                continue
            values = [stored.get(c.field, OMIT) if c.stored else body.get(c.field, query.get(c.field, OMIT)) for c in cons]
            if all(self.holds(c, v) is True for c, v in zip(cons, values, strict=True)):
                hits.append(addr)
        return sorted(set(hits))
