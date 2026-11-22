"""pairwise 후보 모델·배제 조합·PICT 실행(설계 §5.2 후보 값 모델, §5.3 배제 조합, §5.4 생성).

엔드포인트의 body·query 필드마다 기존 경로(`Constraints.baseline`·`sides`·`Field.constants`·분기 진입 값)에서 결정적 후보를 모으고,
모델에서 뺄 필드를 고정한 뒤, 오류 논리곱을 고정 필드로 부분 평가해 PICT 배제 줄을 만든다.
PICT 모델 파일에는 파라미터 `p<i>`·값 `v<j>` 라벨만 쓰고 필드명·값은 `pairwise.json` 역매핑에만 둔다.
이 모듈은 PICT 문법과 설계 상한만 안다(SUT 이름을 모른다).
"""
from __future__ import annotations

import itertools
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from td.detgen.constraints import BASE, KEEP, OMIT, Con, Constraints, Spread, Uniq, Value
from td.detgen.endpoints import Catalog, Endpoint, Field
from td.redact import redact_text

# 설계 §5.3 복잡도 상한(결정적: 시간이 아니라 크기로 끊는다)
MAX_CANDIDATES = 12
MAX_PARAMS = 24
MAX_EXCLUSIONS = 20000
# PICT 종료 코드: 제약이 모든 조합을 막음(3.7.4에서 확인)
PICT_RC_TOO_RESTRICTIVE = 5
INFEASIBLE = "pairwise-infeasible"
TOO_LARGE = "pairwise-too-large"
FEW_FIELDS = "fields<2"
UNIQ_PREFIX = "uniq:"  # 케이스 확정 때 uniq 자리표시가 되는 값의 접두사(derive._finalize)

Kind = Literal["literal", "omit", "null", "uniq", "spread"]


class PictFatal(Exception):
    """환경에 따라 달라질 수 있는 PICT 실패(시간 초과·기타 rc·시작 실패·출력 계약 위반). det generation 전체가 failed가 된다."""


@dataclass(frozen=True)
class PictTool:
    path: Path
    commit: str
    binary_sha256: str


@dataclass(frozen=True)
class Pairwise:
    """derive에 넘기는 pairwise 상태: disabled(det 단위 테스트 기본) | unavailable(pict 없음) | available."""
    mode: Literal["disabled", "unavailable", "available"]
    tool: PictTool | None = None
    work_dir: Path | None = None
    timeout: float | None = None
    reason: str | None = None

    @classmethod
    def disabled(cls) -> "Pairwise":
        return cls("disabled")

    @classmethod
    def unavailable(cls, reason: str) -> "Pairwise":
        return cls("unavailable", reason=reason)

    @classmethod
    def available(cls, tool: PictTool, work_dir: Path, timeout: float) -> "Pairwise":
        return cls("available", tool=tool, work_dir=Path(work_dir), timeout=float(timeout))


@dataclass
class Candidate:
    """후보 값 하나. value는 기존 `Value`(provenance·source·transform 보존) 또는 `OMIT`."""
    label: str
    kind: Kind
    value: Value | object


@dataclass
class EndpointModel:
    params: list[dict]  # [{param, loc, field, candidates: [Candidate]}]
    fixed: dict  # {"<loc>.<field>": {"reason", "candidate": Candidate}}
    dropped: list[dict]  # [{loc, field, candidate: {...}, address, reason}]
    exclusions: list[dict[str, str]]  # [{param: label}] (PICT 줄은 실행 때 렌더)
    order: int
    effective_order: int
    skipped: str | None
    reason: str | None
    # 행 평가용(직렬화하지 않음): (주소, [(param, {label: True|False|None})]) — 배제 줄을 만든 논리곱과 한 원자식으로 줄어든 논리곱
    checks: list = field(default_factory=list, repr=False, compare=False)
    # 모든 행에 붙는 `undetermined:<addr>`: 모델 원자식 0개로 줄었지만 고정 원자식에 판단 불가가 섞인 논리곱(설계 §5.3)
    row_undetermined: list[str] = field(default_factory=list)
    # baseline이 필터 조건을 참으로 만들어도 버리지 않고 남긴 기록: [{field: "<loc>.<name>", label, assume: "baseline-filter:<addr>"}]
    # 모델 필드면 그 라벨을 쓴 행에만, 고정 필드면 모든 행에 붙는다(row_assumes_for)
    row_assumes: list[dict] = field(default_factory=list)


# --- 후보 종류·동치·평가 -----------------------------------------------------------------------------

def kind_of(value) -> Kind:
    if value is OMIT:
        return "omit"
    raw = value.value
    if raw is None:
        return "null"
    if isinstance(raw, Uniq):
        return "uniq"
    if isinstance(raw, Spread):
        return "spread"
    return "literal"


def _key(value) -> tuple:
    """동치 판정 키: omit·null·uniq(필드당 하나)는 종류끼리 같고, spread는 같은 범위끼리, literal은 값 같음."""
    kind = kind_of(value)
    if kind in ("omit", "null", "uniq"):
        return (kind,)
    raw = value.value
    if kind == "spread":
        return (kind, raw.lo, raw.hi, raw.excluded)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return (kind, type(raw).__name__, raw)
    return (kind, "number", float(raw))


def _representative(spread: Spread) -> int:
    """범위 대표: lo·hi와 제외 집합을 뺀 첫 내부 값(내부가 비면 제외 집합 밖 첫 값)."""
    inner = (n for n in range(spread.lo + 1, spread.hi) if n not in spread.excluded)
    return next(inner, next((n for n in range(spread.lo, spread.hi + 1) if n not in spread.excluded), spread.lo))


def truth(con: Con, candidate: Candidate) -> bool | None:
    """후보가 요청 필드 원자식(위반 조건)을 참으로 만드는가. 판단 불가면 None."""
    if con.op == "count":
        return False  # pairwise 행은 선행 건수 0(분산 값)이라 count 조건은 거짓
    if con.op == "rel":
        return False  # 종속 필드는 고정 극단값이고 그 가정(assumes)을 케이스에 싣는다
    value = candidate.value
    if con.op in ("null", "notnull"):
        return Constraints.holds(con, value)  # null 여부는 종류만으로 정해진다(uniq·spread는 null이 아니다)
    if candidate.kind == "spread":
        return Constraints.holds(con, Value(_representative(value.value), value.provenance))
    if candidate.kind == "uniq":
        if con.length or con.op == "fmt":
            return False  # 길이·형식은 baseline이 만족시킨 형식으로 본다
        if con.op in ("eqlit", "neqlit") and not str(con.value).startswith(UNIQ_PREFIX):
            return con.op == "neqlit"  # `uniq:<caseId>`는 `uniq:`로 시작하지 않는 리터럴과 같지 않다
        return None
    return Constraints.holds(con, value)


def fixed_truth(cons: Constraints, ep: Endpoint, con: Con, candidate: Candidate | None) -> bool | None:
    """고정 원자식 평가: 저장 상태는 선행 생성 요청의 baseline 값으로, 그 밖은 고정 후보로 평가한다."""
    if con.stored:
        creator = cons.catalog.creator(ep)
        fld = (creator.body or {}).get(con.field) if creator is not None else None
        if fld is None:
            return None
        return truth(con, _candidate("", cons.baseline(creator)[(fld.loc, fld.name)][0]))
    return truth(con, candidate) if candidate is not None else None


def _candidate(label: str, value) -> Candidate:
    return Candidate(label, kind_of(value), value)


# --- 후보 생성 ------------------------------------------------------------------------------------

def _request_atoms(cons: list[Con], name: str) -> list[Con]:
    return [c for c in cons if not c.stored and c.field == name and c.op not in ("count", "rel")]


def _raw_candidates(ep: Endpoint, cons: Constraints, fld: Field) -> list:
    """출처 순서(baseline → 단일 원자 유효 경계 → 다원자 유효 경계·위반값 → enum 상수 → 분기 참 값)로 값을 모은다."""
    values = [cons.baseline(ep)[(fld.loc, fld.name)][0]]
    resolved = [(addr, cs) for addr, cs in ep.error_disjuncts if not addr.endswith("~")]
    for multi in (False, True):
        for addr, cs in resolved:
            if (len(cs) > 1) != multi:
                continue
            for con in _request_atoms(cs, fld.name):
                sides = cons.sides(ep, con, addr)
                if isinstance(sides, str):
                    continue
                violations, valid = sides
                values.append(valid)
                if multi and violations:
                    values.append(violations[0])
    if fld.kind == "enum" and fld.name not in ep.state_fields:
        values += [Value(constant, "input", f"graph:{ep.id}") for constant in fld.constants]
    for addr, cs in ep.branch_disjuncts:
        for con in _request_atoms(cs, fld.name):
            sides = cons.sides(ep, con, addr)
            if not isinstance(sides, str) and sides[0]:
                values.append(sides[0][0])
    out, seen = [], set()
    for value in values:
        if value is KEEP:
            continue
        if value == BASE:
            value = cons.base(ep, fld, ignore_null=True)[0]
        key = _key(value)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _candidate_json(candidate: Candidate, with_label: bool = True) -> dict:
    value = candidate.value
    doc = {"label": candidate.label} if with_label else {}
    doc["kind"] = candidate.kind
    if candidate.kind == "spread":
        spread = value.value
        doc["range"] = {"lo": spread.lo, "hi": spread.hi, "excluded": list(spread.excluded)}
    elif candidate.kind in ("literal", "null"):
        doc["value"] = value.value
    is_value = isinstance(value, Value)
    doc.update({"provenance": value.provenance if is_value else None, "source": value.source if is_value else None,
                "transform": value.transform if is_value else None})
    return doc


# --- 모델 ---------------------------------------------------------------------------------------

def _fixed_reason(ep: Endpoint, fld: Field, resolved_fields: set, unresolved_fields: set, rel_sides: set,
                  count: int) -> str | None:
    if fld.name in ep.state_fields and fld.kind == "enum":
        return "state-field"
    if fld.name in ep.count_fields:
        return "count-field"
    if fld.name in rel_sides:
        return "rel-dependent"
    if fld.name in unresolved_fields and fld.name not in resolved_fields:
        return "stored-or-unresolved-only"
    if count <= 1:
        return "single-candidate"
    return None


def build_model(ep: Endpoint, cons: Constraints, catalog: Catalog, order: int) -> EndpointModel:
    """엔드포인트 pairwise 모델(PICT 호출 없음). 같은 엔드포인트 제약이면 결과가 같다."""
    del catalog  # 필드 조회는 cons.catalog와 같다(인터페이스 대칭용)
    fields = list((ep.body or {}).values()) + list(ep.query.values())
    resolved = [(addr, cs) for addr, cs in ep.error_disjuncts if not addr.endswith("~")]
    partial = [(addr.rstrip("~"), cs) for addr, cs in ep.error_disjuncts if addr.endswith("~")]
    resolved_fields = {c.field for _, cs in resolved + list(ep.branch_disjuncts) for c in cs if not c.stored}
    resolved_fields |= {name for _, cs in resolved for c in cs if c.op == "rel" for name in c.side}
    unresolved_fields = {c.field for _, cs in partial for c in cs if not c.stored} | {e[0] for e in ep.extra_classes}
    rel_sides = {name for _, cs in resolved for c in cs if c.op == "rel" for name in c.side}

    dropped: list[dict] = []
    baseline_hits: list[tuple] = []  # ((loc, name), addr): baseline이 참으로 만든 필터·축소 조건
    pools: dict[tuple, list[Candidate]] = {}
    for fld in fields:
        kept = []
        for index, value in enumerate(_raw_candidates(ep, cons, fld)):
            candidate = _candidate("", value)
            hits = [addr for addr, cs in resolved if len(cs) == 1
                    for c in _request_atoms(cs, fld.name) if truth(c, candidate) is True]
            reason = "single-atom"
            if not hits:
                hits = [addr for addr, cs in partial for c in _request_atoms(cs, fld.name) if truth(c, candidate) is True]
                reason = "partial-constraint"
            if hits and index == 0:  # baseline(첫 후보)은 버리지 않는다. 가정으로 남긴다
                baseline_hits += [((fld.loc, fld.name), addr) for addr in dict.fromkeys(hits)]
                kept.append(candidate)
                continue
            hit = (hits[0], reason) if hits else None
            if hit:
                dropped.append({"loc": fld.loc, "field": fld.name, "candidate": _candidate_json(candidate, False),
                                "address": hit[0], "reason": hit[1]})
            else:
                kept.append(candidate)
        pools[(fld.loc, fld.name)] = kept

    baseline = cons.baseline(ep)
    while True:  # 한 원자식으로 줄어든 논리곱의 후보 제거가 고정 여부를 바꾸면 다시 평가한다(고정점)
        fixed, model_fields = {}, []
        for fld in fields:
            pool = pools[(fld.loc, fld.name)]
            reason = _fixed_reason(ep, fld, resolved_fields, unresolved_fields, rel_sides, len(pool))
            if reason is None:
                model_fields.append(fld)
                continue
            value = pool[0].value if reason == "single-candidate" and pool else baseline[(fld.loc, fld.name)][0]
            fixed[f"{fld.loc}.{fld.name}"] = {"reason": reason, "candidate": _candidate("v0", value)}
        model_names = {f.name for f in model_fields}
        reduced, infeasible, removed, row_undetermined = [], False, False, []
        for addr, cs in resolved:
            fixed_atoms = [c for c in cs if c.stored or c.op in ("count", "rel") or c.field not in model_names]
            fixed_values = [fixed_truth(cons, ep, c, (fixed.get(_fixed_key(ep, c)) or {}).get("candidate"))
                            for c in fixed_atoms]
            if any(v is False for v in fixed_values):
                continue  # 고정 원자식 하나라도 거짓 → 어떤 행에서도 참이 될 수 없다(판단 불가는 참으로 본다)
            atoms = [c for c in cs if c not in fixed_atoms]
            if not atoms:
                if all(v is True for v in fixed_values):
                    infeasible = True  # 판단 가능하게 모두 참 → 모든 행이 오류
                else:
                    row_undetermined.append(addr)  # 판단 불가가 섞이면 모든 행에 undetermined
            elif len(atoms) == 1:
                fld = cons.catalog.lookup(ep, atoms[0].field)
                pool = pools[(fld.loc, fld.name)]
                if pool and truth(atoms[0], pool[0]) is True and ((fld.loc, fld.name), addr) not in baseline_hits:
                    baseline_hits.append(((fld.loc, fld.name), addr))  # baseline은 남기고 가정으로 기록
                for candidate in [c for c in pool[1:] if truth(atoms[0], c) is True]:
                    pool.remove(candidate)
                    removed = True
                    dropped.append({"loc": fld.loc, "field": fld.name, "candidate": _candidate_json(candidate, False),
                                    "address": addr, "reason": "reduced-single-atom"})
                reduced.append((addr, atoms))
            else:
                reduced.append((addr, atoms))
        if not removed:
            break

    params = []
    for index, fld in enumerate(model_fields):
        candidates = [Candidate(f"v{j}", c.kind, c.value) for j, c in enumerate(pools[(fld.loc, fld.name)])]
        params.append({"param": f"p{index}", "loc": fld.loc, "field": fld.name, "candidates": candidates})
    by_field = {p["field"]: p for p in params}
    checks = [(addr, [(by_field[c.field]["param"], {cand.label: truth(c, cand) for cand in by_field[c.field]["candidates"]})
                      for c in atoms])
              for addr, atoms in reduced]
    effective = min(order, len(params))
    model = EndpointModel(params, fixed, dropped, [], order, effective, None, None, checks,
                          sorted(set(row_undetermined)),
                          [{"field": f"{loc}.{name}", "label": "v0", "assume": f"baseline-filter:{addr}"}
                           for (loc, name), addr in baseline_hits])
    if len(params) < 2:
        model.skipped = FEW_FIELDS
    elif infeasible:
        model.reason = INFEASIBLE
    elif len(params) > MAX_PARAMS or any(len(p["candidates"]) > MAX_CANDIDATES for p in params):
        model.reason = TOO_LARGE
    elif _bound(checks) > MAX_EXCLUSIONS:
        model.reason = TOO_LARGE  # 열거 전에 곱으로 판정한다
    else:
        exclusions = _collect_exclusions([c for c in checks if len(c[1]) >= 2])
        if exclusions is None:
            model.reason = TOO_LARGE
        else:
            model.exclusions = exclusions
    return model


def _fixed_key(ep: Endpoint, con: Con) -> str:
    fld = (ep.body or {}).get(con.field) or ep.query.get(con.field)
    return f"{fld.loc}.{fld.name}" if fld is not None else ""


def _bound(checks) -> int:
    """Σ_논리곱 Π_필드 후보 수(배제 줄 상한). MAX_EXCLUSIONS+1에서 포화한다."""
    total = 0
    for _, atoms in checks:
        if len(atoms) < 2:
            continue
        product = 1
        for _, truths in atoms:
            product = min(product * len(truths), MAX_EXCLUSIONS + 1)
        total = min(total + product, MAX_EXCLUSIONS + 1)
    return total


def _iter_exclusions(checks):
    """배제 조합을 하나씩 낸다: 원자식마다 필드가 달라 조합이 참인 것은 원자식별 참 후보의 곱과 같다."""
    for _, atoms in checks:
        # 한 논리곱의 원자식은 서로 다른 필드다(같은 필드를 두 번 묶는 논리곱은 derive가 `~` 부분 제약으로 강등한다)
        assert len({param for param, _ in atoms}) == len(atoms), "conjunction atoms must be on distinct fields"
        trues = [[(param, label) for label, value in truths.items() if value is True] for param, truths in atoms]
        yield from itertools.product(*trues)


def _collect_exclusions(checks) -> list[dict[str, str]] | None:
    """스트리밍으로 모으고 MAX_EXCLUSIONS를 넘는 순간(MAX_EXCLUSIONS+1번째) 멈춘다. 넘으면 None."""
    seen, out = set(), []
    count = 0
    for combo in _iter_exclusions(checks):
        count += 1
        if count > MAX_EXCLUSIONS:
            return None
        key = tuple(sorted(combo, key=lambda pair: int(pair[0][1:])))
        if key not in seen:
            seen.add(key)
            out.append(dict(key))
    return out


def undetermined(model: EndpointModel, labels: dict[str, str]) -> list[str]:
    """행(라벨)에서 판단 불가로 남은 논리곱 주소: 모든 원자식이 참 또는 판단 불가이고 하나 이상 판단 불가."""
    hits = []
    for addr, atoms in model.checks:
        values = [truths.get(labels.get(param)) for param, truths in atoms]
        if all(v is not False for v in values) and any(v is None for v in values):
            hits.append(addr)
    return sorted(set(hits))


def row_assumes_for(model: EndpointModel, labels: dict[str, str]) -> list[str]:
    """행에 붙일 가정: 모든 행 공통 `undetermined:` + 그 행이 쓴 baseline 라벨의 `baseline-filter:` + 행별 `undetermined:`."""
    params = {f"{p['loc']}.{p['field']}": p["param"] for p in model.params}
    out = [f"undetermined:{addr}" for addr in model.row_undetermined]
    for entry in model.row_assumes:
        param = params.get(entry["field"])
        if param is None or labels.get(param) == entry["label"]:
            out.append(entry["assume"])
    out += [f"undetermined:{addr}" for addr in undetermined(model, labels)]
    return sorted(set(out))


def model_json(model: EndpointModel) -> dict:
    """`pairwise.json` 엔드포인트 항목(rows는 derive가 더한다)."""
    return {
        "params": [{"param": p["param"], "loc": p["loc"], "field": p["field"],
                    "candidates": [_candidate_json(c) for c in p["candidates"]]} for p in model.params],
        "fixed": {name: dict(_candidate_json(entry["candidate"]), reason=entry["reason"])
                  for name, entry in model.fixed.items()},
        "dropped": [dict(d) for d in model.dropped],
        "exclusions": [dict(e) for e in model.exclusions],
        "order": model.order,
        "effectiveOrder": model.effective_order,
        "skipped": model.skipped,
        "reason": model.reason,
    }


# --- PICT ------------------------------------------------------------------------------------------

def render_model(model: EndpointModel) -> str:
    """PICT 모델 텍스트(`p<i>`/`v<j>` 라벨만). 배제는 `IF ... THEN [p] <> "v";`(단독 NOT 문장은 PICT가 받지 않는다)."""
    lines = [f"{p['param']}: " + ", ".join(c.label for c in p["candidates"]) for p in model.params]
    if model.exclusions:
        lines.append("")
    for exclusion in model.exclusions:
        pairs = sorted(exclusion.items(), key=lambda pair: int(pair[0][1:]))
        head = " AND ".join(f'[{param}] = "{label}"' for param, label in pairs[:-1])
        lines.append(f'IF {head} THEN [{pairs[-1][0]}] <> "{pairs[-1][1]}";')
    return "\n".join(lines) + "\n"


def _first_line(text: str) -> str:
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def run_pict(model: EndpointModel, tool: PictTool, work_dir: Path, timeout: float) -> list[dict[str, str]] | Literal["pairwise-infeasible"]:
    """모델을 work_dir 아래 새 임시 디렉터리에 쓰고(항상 삭제) `pict <model> /o:<effectiveOrder>`를 부른다."""
    if model.skipped or model.reason:
        raise ValueError("실행할 수 없는 모델(skipped/reason)")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="pict-", dir=work_dir)).resolve()
    try:
        model_path = temp / "model.txt"
        model_path.write_text(render_model(model), encoding="utf-8")
        argv = [str(tool.path), str(model_path), f"/o:{model.effective_order}"]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise PictFatal(f"pict timed out after {timeout:g}s") from exc
        except OSError as exc:
            raise PictFatal(f"pict launch failed (rc=None): {redact_text(type(exc).__name__ + ': ' + str(exc))}") from exc
        if proc.returncode == PICT_RC_TOO_RESTRICTIVE:
            return INFEASIBLE
        if proc.returncode != 0:
            raise PictFatal(f"pict failed (rc={proc.returncode}): {redact_text(_first_line(proc.stderr))}")
        return _parse_output(model, proc.stdout)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def _parse_output(model: EndpointModel, stdout: str) -> list[dict[str, str]]:
    """출력 계약: 헤더 = 파라미터 집합(정확히, 중복 열 없음), 행마다 파라미터별 알려진 라벨 하나, 1행 이상."""
    lines = [line.rstrip("\r") for line in stdout.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        raise PictFatal("pict output contract violated (rc=0): empty output")
    header = lines[0].split("\t")
    known = {p["param"]: {c.label for c in p["candidates"]} for p in model.params}
    if len(header) != len(set(header)):
        raise PictFatal("pict output contract violated (rc=0): duplicate columns")
    if set(header) != set(known):
        raise PictFatal("pict output contract violated (rc=0): header mismatch")
    rows = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != len(header) or any(cell not in known[name] for name, cell in zip(header, cells)):
            raise PictFatal("pict output contract violated (rc=0): bad row")
        row = dict(zip(header, cells))
        rows.append({p["param"]: row[p["param"]] for p in model.params})
    if not rows:
        raise PictFatal("pict output contract violated (rc=0): no rows")
    return rows
