"""케이스 도출(설계 §5.2 케이스 도출, §5.3 baseline, §5.4 모수).

입력은 det 번들(`Bundle`)뿐이다. SUT 이름·임계값은 모두 번들에서 읽고, 이 모듈에는 bbtg 관례 표지
(`null/empty`, `no_data`, `BRANCH_CONDITION`)와 RFC 헤더 이름 `Authorization`만 둔다.

흐름: 엔드포인트 표(`endpoints`) → 계획 항목마다 파싱·제약 변환(`constraints`) → 초안(draft) → 1차 구체화(baseline·선행 요청·충돌 점검)
→ baseline/R-HAPPY 추가 → 같은 요청 병합 → 정렬·id 부여 → 기호(uniq·분산) 확정 → 모수 계산.
계수 단위는 슬롯이다. 초안 하나가 슬롯 하나이고, 생성되면 case, 아니면 `unresolved` 한 줄이 된다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal

from td.detgen.constraints import BASE, LARGE_NUMBER, OMIT, UNIQ, Con, Constraints, Spread, Uniq, Value
from td.detgen.endpoints import Catalog, Endpoint, simple, slug
from td.detgen.inputs import Bundle
from td.detgen.parse import parse

__all__ = ["REASONS", "Case", "Derivation", "Value", "derive"]

REASONS = ("no-endpoint-mapping", "unparsed", "unresolved-operand", "unreachable-state", "needs-state-transition",
           "param-name-unknown", "no-id-ref", "no-condition", "no-body-schema", "format-unknown", "input-missing",
           "input-contradiction")
# 한 슬롯에 사유가 여럿이면 앞선 것을 쓴다(근본 원인 우선)
_REASON_PRIORITY = ("input-missing", "input-contradiction", "needs-state-transition", "unresolved-operand",
                    "format-unknown", "no-body-schema", "param-name-unknown", "no-id-ref", "unreachable-state")
# bbtg 관례 표지(설계 §5.2 특수 항목)
EMPTY_BODY_MARK = "null/empty"
NO_DATA_MARK = "no_data"
BRANCH_REASON = "BRANCH_CONDITION"
# RFC 7235 인증 헤더 이름
AUTH_HEADER = "Authorization"
_CONDITION_SIGNS = re.compile(r"[=<>!≠.]")
_VALID = {"strict": "2xx", "class": "2xx", "source": "rule"}
_VALID_RULES = ("valid-boundary", "baseline-valid", "enum-value", "happy", "branch-entry", "filter-empty")


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


@dataclass
class _Draft:
    ep: Endpoint
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
    cause: str | None = None
    pair_key: tuple | None = None
    case: Case | None = None
    merged: bool = False
    survivor: "_Draft | None" = None  # 병합되어 대신 남은 초안


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _best_reason(reasons) -> str:
    return min(reasons, key=_REASON_PRIORITY.index)


class _Deriver:
    def __init__(self, bundle: Bundle) -> None:
        self.plans = bundle.read("plans.json")
        self.keyparams = {(kp["class"], kp["method"]): kp for kp in bundle.read("keyparams.json")}
        self.auth = bundle.read("auth.json")
        self.harness = bundle.read("harness.json")
        self.missing = bundle.missing
        self.catalog = Catalog(bundle.read("ontology.json"), bundle.read("ext.json"), self.harness)
        self.cons = Constraints(self.catalog)
        self.endpoints = self.catalog.endpoints
        self.drafts: list[_Draft] = []
        self.unresolved: list[dict] = []
        self.nodata: dict[str, _Draft] = {}
        self.races: list[tuple] = []  # (엔드포인트 라벨, 항목 주소, 원자식 위치): count 조건의 동시 요청 경쟁(범위 밖)

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

    def _skip(self, addr, reason, ep=None, rule="item", cause=None) -> None:
        entry = {"source": addr, "reason": reason, "endpoint": ep.label if ep else None, "rule": rule}
        if cause:
            entry["cause"] = cause
        self.unresolved.append(entry)

    def _plan(self, plan) -> None:
        keyparams = self.keyparams.get((plan["class"], plan["method"]))
        ep = self.catalog.map(plan)
        items = self._items(plan, keyparams)
        if ep is None:
            for item in items:
                self._skip(item["addr"], "no-endpoint-mapping")
            return
        if not ep.mapped:
            ep.mapped, ep.slug = True, slug(plan["method"])
        self.catalog.name_query(ep, keyparams)  # 같은 엔드포인트에 대응한 두 번째 계획도 이름을 보탠다
        params = (keyparams or {}).get("parameters", [])
        body_simple = simple(ep.body_type) if ep.body_type else None
        var = next((p["accessor"] for p in params if body_simple and simple(p["java_type"]) == body_simple), None)
        scalars = {}
        for param in params:
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
                    continue
                graph = self.catalog.expect(item["expected"]) or {}
                expect = {"strict": "4xx", "class": "4xx", "source": "rule"}
                expect.update({k: graph[k] for k in ("bbtgCode", "graphStatus") if k in graph})
                self.drafts.append(_Draft(ep, "empty-body", [addr], (addr, 0, 0, 0), expect=expect, oracle="framework-reject"))
            elif not _CONDITION_SIGNS.search(item["condition"]):
                self._skip(addr, "no-condition", ep)
            else:
                parsed = parse(item["condition"], var)
                if parsed.disjuncts is None:
                    self._skip(addr, "unparsed", ep)
                    continue
                expect = self.catalog.expect(item["expected"])
                disjuncts = [self._disjunct(ep, addr, expect, atoms, var, scalars, plan["class"], no_keyparams, d_index)
                             for d_index, atoms in enumerate(parsed.disjuncts)]
                parsed_items.append((item, expect, disjuncts))
        contradicted = self._contradictions(ep, parsed_items)
        for addr, cons in ep.error_disjuncts:  # 모순 항목은 제약에서 빼되 이론 모수(상한)에는 남긴다
            if addr.rstrip("~") in contradicted:
                ep.extra_classes.update((c.field, c.op, str(c.value), c.length) for c in cons if not c.stored)
        ep.error_disjuncts[:] = [d for d in ep.error_disjuncts if d[0].rstrip("~") not in contradicted]
        for item, expect, disjuncts in parsed_items:
            for d_index, (cons, reason) in enumerate(disjuncts):
                self._expand(ep, item, expect, d_index, cons, "input-contradiction" if item["addr"] in contradicted else reason)

    def _disjunct(self, ep, addr, expect, atoms, var, scalars, owner, no_keyparams, d_index=0):
        """논리곱 하나 → (원자식별 Con|사유 목록, 슬롯 사유|None). 엔드포인트 제약 목록도 갱신한다."""
        cons = [self.cons.con(atom, ep, var, scalars, owner) for atom in atoms]
        for a_index, (atom, con) in enumerate(zip(atoms, cons, strict=True)):
            if atom.op == "countGe":  # count 원자식마다 하나(논리곱 위치.원자식 위치)
                self.races.append((ep.label, addr, f"{d_index}.{a_index}"))
            left = self.cons.remap(atom.left, scalars)
            if isinstance(con, str) and atom.op != "countGe" and left.kind == "request" and self.catalog.lookup(ep, left.name):
                right = self.cons.remap(atom.right, scalars)
                ep.extra_classes.add((left.name, atom.op, right.name if right else "", atom.length))
        reasons = [c for c in cons if isinstance(c, str)]
        if no_keyparams and "unresolved-operand" in reasons:
            reasons.append("input-missing")
        fields = [(c.stored, c.field) for c in cons if not isinstance(c, str)]
        if not reasons and len(set(fields)) != len(fields):
            reasons.append("unresolved-operand")  # 한 논리곱에서 같은 필드를 두 번 묶는 식은 다루지 않는다
        ok = [c for c in cons if not isinstance(c, str)]
        if expect is None:
            ep.branch_disjuncts.append((addr, ok))
        elif ok and not reasons:
            ep.error_disjuncts.append((addr, ok))
        elif ok:  # 미해결 논리곱이라도 baseline 제약(원자식별 거짓)에는 쓴다
            ep.error_disjuncts.append((addr + "~", [c for c in ok if c.op != "count"]))
        return cons, _best_reason(reasons) if reasons else None

    def _contradictions(self, ep: Endpoint, parsed_items) -> set[str]:
        """입력 모순: 원자식 하나짜리 오류 항목 X의 위반 조건이 같은 필드의 다른 오류 항목 Y의 유효 경계를 모두 참으로
        만들면(예: `f != null` vs `f < a || f > b`) Y의 유효 요청을 만들 수 없다. X를 모순 항목으로 표시한다."""
        flagged = set()
        for item, expect, disjuncts in parsed_items:
            if expect is None or len(disjuncts) != 1 or disjuncts[0][1] is not None or len(disjuncts[0][0]) != 1:
                continue
            x = disjuncts[0][0][0]
            if x.stored:
                continue
            for other, other_expect, other_disjuncts in parsed_items:
                if other is item or other_expect is None or other["addr"] in flagged:
                    continue
                boundaries = []
                for cons, reason in other_disjuncts:
                    if reason is None and len(cons) == 1 and isinstance(cons[0], Con) and not cons[0].stored \
                            and cons[0].field == x.field:
                        sides = self.cons.sides(ep, cons[0], other["addr"])
                        if not isinstance(sides, str) and isinstance(sides[1], Value):
                            boundaries.append(sides[1])
                            if cons[0].op == "==" and isinstance(sides[1].value, (int, float)):  # `f == a`의 유효 쪽은 a±step 둘 다
                                boundaries.append(Value(2 * cons[0].value - sides[1].value, "derived"))
                if boundaries and all(self.cons.holds(x, b) is True for b in boundaries):
                    flagged.add(item["addr"])
                    break
        return flagged

    def _no_data(self, ep: Endpoint, item, scalars) -> None:
        param = item["param"]
        if param in {f.name for f in ep.path_vars}:
            draft = self.nodata.get(ep.id)
            if draft is None:
                draft = _Draft(ep, "no-data", [], (item["addr"], 0, 0, 0), expect=self.catalog.not_found(ep), path_mode="missing")
                self.nodata[ep.id] = draft
                self.drafts.append(draft)
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
        self.drafts.append(_Draft(ep, "filter-empty", [item["addr"]], (item["addr"], 0, 0, 0),
                                  targets={("query", name): value}, expect=dict(_VALID), oracle="status-only"))

    def _expand(self, ep, item, expect, d_index, cons, reason) -> None:
        addr = item["addr"]
        sides = [] if reason else [self.cons.sides(ep, c, addr) for c in cons]
        reason = reason or next((s for s in sides if isinstance(s, str)), None)
        if expect is None:  # 분기 진입(예외 없음): 조건 참 1건, 상태로 구별 불가
            draft = _Draft(ep, "branch-entry", [addr], (addr, d_index, 0, 0), expect=dict(_VALID), oracle="status-only",
                           reason=reason)
            if reason is None:
                self._fill(draft, ep, cons, sides, None)
            self.drafts.append(draft)
            return
        violation_count = len(sides[0][0]) if not reason and len(cons) == 1 else 1
        boundary_keys = [(addr, d_index, 1, i) for i in range(len(cons))]
        for variant in range(violation_count):
            draft = _Draft(ep, "violation", [addr], (addr, d_index, 0, variant), expect=dict(expect),
                           pair_key=boundary_keys[-1], reason=reason)
            if not reason:
                self._fill(draft, ep, cons, sides, None, variant)
                if any(c.op == "null" and self.cons.field_of(ep, c).primitive for c in cons):
                    draft.oracle = "framework-reject"
                    draft.expect.update({"strict": "4xx", "class": "4xx"})
            self.drafts.append(draft)
        for index, key in enumerate(boundary_keys):
            draft = _Draft(ep, "valid-boundary", [addr], key, expect=dict(_VALID), reason=reason)
            if not reason:
                self._fill(draft, ep, cons, sides, index)
            self.drafts.append(draft)

    def _fill(self, draft, ep, cons, sides, flip, variant=0) -> None:
        """논리곱의 원자식 값을 초안에 넣는다. flip이 정해지면 그 원자식만 유효 경계로 뒤집는다."""
        for index, (con, (violations, valid)) in enumerate(zip(cons, sides, strict=True)):
            value = valid if index == flip else violations[variant if len(cons) == 1 else 0]
            if con.op == "count":
                draft.priors = con.value - 1 if index == flip else con.value
                continue
            targets = draft.stored if con.stored else draft.targets
            for name in con.side if con.op == "rel" else (con.field,):
                targets[name if con.stored else (self.catalog.lookup(ep, name).loc, name)] = value
            if con.op == "rel":
                draft.assumes.append(con.assumes[1] if index == flip else con.assumes[0])
            if con.op == "fmt":
                draft.assumes.append("format-heuristic")

    # --- 그래프·하네스 규칙 -------------------------------------------------------------------------

    def _graph_rules(self) -> None:
        protected = any(h.get("name") == AUTH_HEADER and h.get("required") for h in self.auth.get("required_headers", []))
        for ep in self.endpoints.values():
            source = f"graph:{ep.id}"
            if ep.mapped:
                for _ in ep.unnamed_query:  # 이름을 못 얻은 query 파라미터 하나 = 생성 불가 슬롯 하나
                    self._skip(source, "param-name-unknown", ep, "param")
            if ep.path_vars:
                if ep.id in self.nodata:
                    self.nodata[ep.id].sources.append(source)
                else:
                    self.drafts.append(_Draft(ep, "no-data", [source], (source, 0, 0, 0), path_mode="missing",
                                              expect=self.catalog.not_found(ep)))
            if protected and ep.label != self.catalog.login:
                self.drafts.append(_Draft(ep, "auth", ["harness:unauthenticatedStatus", source], (source, 0, 0, 0),
                                          path_mode="missing", assumes=["보호됨"],
                                          expect={"strict": self.harness.get("unauthenticatedStatus"), "class": "4xx",
                                                  "source": "harness-config"}))
            if ep.body_type is not None and ep.body is None and not ep.mapped and ep.method != "GET":
                self._skip(source, "no-body-schema", ep, "happy")
            for fld in [f for f in list((ep.body or {}).values()) + list(ep.query.values()) if f.kind == "enum"]:
                base = self.cons.baseline(ep).get((fld.loc, fld.name), (OMIT,))[0]
                chosen = base.value if isinstance(base, Value) else None
                for position, constant in enumerate(fld.constants):
                    if constant != chosen:
                        self.drafts.append(_Draft(
                            ep, "enum-value", [source], (source, 1, position, 0), expect=dict(_VALID),
                            targets={(fld.loc, fld.name): Value(constant, "input", source)},
                            reason="needs-state-transition" if fld.name in ep.state_fields else None))

    def _late_rules(self) -> None:
        """위반 case가 생긴 엔드포인트의 baseline-valid, 그리고 그 밖의 GET에 R-HAPPY."""
        with_violation = {d.ep.id for d in self.drafts if d.rule == "violation" and d.reason is None}
        for ep in self.endpoints.values():
            source = f"graph:{ep.id}"
            if ep.id in with_violation:
                addrs = sorted({addr.rstrip("~") for addr, _ in ep.error_disjuncts})
                draft = _Draft(ep, "baseline-valid", [source] + addrs, (source, 0, 0, 0), expect=dict(_VALID))
            elif ep.method == "GET" and ep.body_type is None:
                draft = _Draft(ep, "happy", [source], (source, 0, 0, 0), expect=dict(_VALID))
            else:
                continue
            self._materialize(draft)
            self.drafts.append(draft)

    # --- 구체화 ----------------------------------------------------------------------------------

    def _fields(self, ep, fields, targets, loc, assumes, reasons) -> dict:
        out = {}
        for name, fld in fields.items():
            value, extra, reason = self.cons.value(ep, fld, targets.get((loc, name)) if loc else targets.get(name))
            assumes += extra
            reasons += [reason] if reason else []
            if value is not OMIT:
                out[name] = value
        return out

    def _materialize(self, draft: _Draft) -> None:
        """1차 구체화: 값·선행 요청을 채우고 충돌을 점검한다. 실패하면 draft.reason을 정한다."""
        if draft.reason or draft.case:
            return
        ep, reasons, assumes = draft.ep, [], list(draft.assumes)
        if ep.label == self.catalog.login and draft.expect.get("class") == "2xx":
            draft.reason, draft.cause = "input-missing", "credentials"  # 번들에 자격 증명이 없어 성공 요청을 만들 수 없다
            return
        body, query, path, setup, stored_values = {}, {}, {}, [], {}
        if draft.rule not in ("empty-body", "auth") and ep.body_type is not None:
            if ep.body is not None:
                body = self._fields(ep, ep.body, draft.targets, "body", assumes, reasons)
            elif draft.rule != "no-data":  # 없는 id 조회는 본문 없이도 4xx를 기대한다
                reasons.append("no-body-schema")
        if draft.rule != "auth":
            query = self._fields(ep, ep.query, draft.targets, "query", assumes, reasons)
            if any(f.required for f in ep.unnamed_query):
                reasons.append("param-name-unknown")
        if any(name in ep.state_fields and (v == BASE or isinstance(v, Value) and v.value is not None)
               for (loc, name), v in draft.targets.items() if loc == "body"):
            reasons.append("needs-state-transition")  # 상태 전이 규칙을 모르면 상태 필드에 구체 상수를 넣을 수 없다
        for var in ep.path_vars:
            if draft.path_mode == "missing":
                path[var.name] = Value(LARGE_NUMBER if var.kind in ("int", "real", "other") else UNIQ,
                                       "generic-sentinel", None, "nonexistent-id")
                continue
            creator = self.catalog.creator(ep)
            capture = self.catalog.capture(creator, var.name)
            if capture is None:
                reasons.append("no-id-ref")
                continue
            if creator.body is None:
                reasons.append("no-body-schema")
                continue
            if not setup:
                stored_values = self._fields(creator, creator.body, draft.stored, None, assumes, reasons)
                if self.cons.violated(creator.error_disjuncts, stored_values, {}, {}):
                    reasons.append("unreachable-state")  # 선행 생성이 거부될 값(저장 상태 설정 불가)
                setup.append({"endpoint": creator.label, "values": stored_values, "capture": {}})
            setup[0]["capture"][var.name] = capture
            path[var.name] = Value(f"ref:{var.name}", "input", f"graph:{creator.id}", f"capture {capture}")
        setup += [{"endpoint": ep.label, "values": body, "capture": {}} for _ in range(draft.priors)]
        if reasons:
            draft.reason = _best_reason(reasons)
            return
        # 본문을 보내지 않거나 서버 진입 전 거부를 기대하는 규칙은 다른 조건과의 충돌을 따지지 않는다
        hits = [] if draft.rule in ("auth", "empty-body", "no-data") else self.cons.violated(
            ep.error_disjuncts, body, query, stored_values, skip=draft.sources[0] if draft.rule == "violation" else None)
        if draft.rule in _VALID_RULES and hits:
            draft.reason = "unreachable-state"  # 다른 조건이 같은 필드를 막아 유효 요청을 만들 수 없다
            return
        assumes += [f"also-violates:{h}" for h in hits]
        checked = sorted({addr.rstrip("~") for addr, _ in ep.error_disjuncts} - set(hits) - set(draft.sources))
        draft.case = Case("", ep.label, draft.rule, list(draft.sources), body, query, path, setup,
                          "anonymous" if draft.rule == "auth" else "authed", draft.expect,
                          draft.oracle, sorted(set(assumes)), checked + sorted(set(assumes)), None)

    # --- 마무리 ----------------------------------------------------------------------------------

    @staticmethod
    def _signature(draft: _Draft) -> str | None:
        """같은 요청 판정용 서명. case id에 따라 값이 달라지는 자리표시(uniq·분산)가 있으면 None(병합하지 않음)."""
        case = draft.case

        def plain(values):
            out = {}
            for name, value in values.items():
                if isinstance(value.value, (Uniq, Spread)):
                    raise ValueError
                out[name] = value.value
            return out
        try:
            return json.dumps([draft.ep.id, draft.rule == "empty-body", case.auth, plain(case.values), plain(case.query),
                               plain(case.path), [[s["endpoint"], plain(s["values"]), s["capture"]] for s in case.setup],
                               case.expect.get("strict")], sort_keys=True, default=str)
        except ValueError:
            return None

    def _dedupe(self, made: list[_Draft]) -> list[_Draft]:
        """다른 규칙이 똑같은 요청을 낳으면 정렬상 앞의 case 하나만 남기고 뒤의 출처를 sources에 더한다."""
        seen: dict[str, _Draft] = {}
        kept = []
        for draft in made:
            signature = self._signature(draft)
            first = seen.get(signature) if signature else None
            if first is not None and first.rule != draft.rule:
                first.case.sources += [s for s in draft.sources if s not in first.case.sources]
                draft.merged, draft.survivor = True, first
                continue
            if signature:
                seen.setdefault(signature, draft)
            kept.append(draft)
        return kept

    @staticmethod
    def _finalize(draft: _Draft, case_id: str) -> None:
        case = draft.case
        case.id = case_id
        seen = {}

        def resolve(value):
            if not isinstance(value, Value):
                return value
            if isinstance(value.value, Uniq):
                return Value(f"uniq:{case_id}", value.provenance, value.source, value.transform)
            if isinstance(value.value, Spread):
                if id(value) not in seen:  # 같은 Value(본문과 선행 요청이 공유)는 같은 수로 확정
                    seen[id(value)] = Value(value.value.pick(case_id), value.provenance, value.source, value.transform)
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
        made = self._dedupe(made)
        counters: dict[tuple, int] = {}
        by_key = {}
        for draft in made:
            group = (draft.ep.slug, draft.rule)
            counters[group] = counters.get(group, 0) + 1
            self._finalize(draft, f"{draft.ep.slug}-{draft.rule}-{counters[group]}")
            by_key[(draft.ep.id, draft.key)] = draft.case.id
        for draft in self.drafts:  # 병합된 초안의 주소는 남은 case를 가리킨다(위반의 pair가 끊기지 않게)
            if draft.merged:
                by_key[(draft.ep.id, draft.key)] = draft.survivor.case.id
        for draft in made:
            if draft.rule == "violation" and draft.pair_key is not None:
                draft.case.pair = by_key.get((draft.ep.id, draft.pair_key))
        for draft in self.drafts:
            if draft.reason is not None:
                self._skip(draft.sources[0], draft.reason, draft.ep, draft.rule, draft.cause)
        self.unresolved.sort(key=lambda e: (e["source"], e["rule"], e["reason"], e["endpoint"] or ""))
        cases = [d.case for d in made]
        merged = sum(1 for d in self.drafts if d.merged)
        return Derivation(cases, self.unresolved, self._universe(cases, merged))

    def _universe(self, cases, merged: int) -> dict:
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
                # count는 해석 여부(상태 전제)와 무관하게 한 클래스, 변환 못 한 원자식도 필드를 알면 한 클래스로 센다
                classes = {("count",) if c.op == "count" else (c.op, str(c.value), c.length, c.date)
                           for _, cons in ep.error_disjuncts + ep.branch_disjuncts
                           for c in cons if not c.stored and (c.field == fld.name if c.op != "rel" else c.side[0] == fld.name)}
                if fld.loc != "path":
                    classes |= {("count",)} if fld.name in ep.count_fields else set()
                    classes |= {("raw",) + extra[1:] for extra in ep.extra_classes if extra[0] == fld.name}
                fields[f"{fld.loc}.{fld.name}"] = 1 + len(classes)
            product = 1
            for count in fields.values():
                product *= count
            total += product
            factors.append({"endpoint": ep.label, "fields": fields, "product": product})
            terms.append("*".join(str(v) for v in fields.values()) or "1")
        # 동시 요청 경쟁은 범위 밖 항목으로만 기록한다(value에 넣지 않는다)
        factors += [{"endpoint": label, "item": addr, "atom": atom, "kind": "concurrency-race", "outOfScope": True}
                    for label, addr, atom in sorted(self.races)]
        return {"bySlot": {"total": len(cases) + len(self.unresolved), "generated": len(cases),
                           "unresolved": len(self.unresolved), "deduplicated": merged, "byReason": by_reason},
                "byRule": dict(sorted(by_rule.items())),
                "theoretical": {"value": total, "formula": "Σ_endpoint Π_field (1 + 위반 클래스 수(field)) = " + " + ".join(terms),
                                "factors": factors}}


def derive(bundle: Bundle) -> Derivation:
    """det 번들에서 케이스·생성 불가 슬롯·모수를 도출한다. 같은 번들이면 결과가 같다."""
    return _Deriver(bundle).run()
