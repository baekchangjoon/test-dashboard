"""det generation 결과 집계(설계 §2 G4, §5.3, §5.4; Task 8).

입력
- generation 디렉터리(`e2e/generated/<sut>/det/<genId>/`): `cases.json`과 `features/`.
- S07 generation 디렉터리(`<run>/S07/<genId>/`): `scenario-results.json`(NDJSON, testId별 status)과 `cucumber.json`.

판정
- 케이스 상태: feature의 `@case:<id>` 태그(없으면 첫 step `the case "<id>"`)로 pickle과 케이스를 잇고,
  `td.scenarios.pickle_refs`가 만든 testId로 `scenario-results.json`의 status를 찾는다. 줄이 없으면 실행 안 됨이다.
- strict 통과 = 시나리오 passed(단정이 strict 기대 하나뿐이다).
- class 통과 = strict 통과이거나, 실패 시나리오의 관측 코드(`DET-STATUS`, `td.detgen.observed`)가 `expect.class`에 든다.
  실패했는데 관측 코드를 못 찾으면 class 판정은 null이고 사유를 `classUnknownCases`에 남긴다.
- baseline-valid: 엔드포인트별 passed | failed | notRun. 위반(`violation`) 케이스 중 그 엔드포인트의 baseline이 failed인 것의 수가
  `blockedByBaseline`이다(실행 안 된 baseline은 막힘으로 세지 않는다).
- 검증된 위반 = 위반 케이스 strict 통과 + 짝(pair) 케이스 통과 + 엔드포인트 baseline 통과. pair가 없는 위반은 검증할 수 없어
  `unpaired`로 따로 센다.
- 상태 불일치: `expect.bbtgCode`와 `expect.graphStatus`가 모두 있고 서로 다른 케이스. observed는 관측 코드이고, 통과했고
  strict가 정수면 그 정수다(통과는 strict를 만족했다는 뜻).

- pairwise(det pairwise 설계 §5.5): `universe.pairwise`가 없거나(disabled) pict가 없었으면(unavailable: `pairwise-unavailable`
  생성 불가 슬롯) null. available이면 `{order, interactionsFeasible, interactionsCovered, undetermined, relCombined}`이고
  interactions는 `universe.pairwise.byEndpoint` 합, undetermined·relCombined는 해당 `assumes` 접두를 하나 이상 가진 pairwise 케이스 수다.
- `coverage_comparison(current_run, run3_run)`: SUT 커밋과 tools.lock jacoco 항목이 모두 같을 때만 det 라인·브랜치 차이를 낸다.

LLM을 부르지 않고 입력 파일만 읽는다. 같은 입력이면 같은 결과다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from td import scenarios
from td.detgen.observed import observed_codes

__all__ = ["summarize", "case_statuses", "coverage_comparison", "VIOLATION_RULE", "BASELINE_RULE"]

VIOLATION_RULE = "violation"
BASELINE_RULE = "baseline-valid"
CASES_FILE = "cases.json"
_CASE_TAG = re.compile(r"@case:(\S+)")
_CASE_STEP = re.compile(r'^\s*(?:Given|And|\*)\s+the case "([^"]+)"\s*$')
_SCENARIO = re.compile(r"^\s*Scenario( Outline)?\s*:")
PAIRWISE_RULE = "pairwise"
PAIRWISE_UNAVAILABLE = "pairwise-unavailable"
UNDETERMINED_PREFIX = "undetermined:"
REL_COMBINED_PREFIX = "rel-combined:"


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _case_by_line(feature_text: str) -> dict[int, str]:
    """Scenario 줄 번호(1부터) → 케이스 id. 바로 위 태그 줄의 `@case:`가 우선이고, 없으면 다음 step의 `the case "<id>"`."""
    lines = feature_text.splitlines()
    found: dict[int, str] = {}
    for index, line in enumerate(lines):
        if not _SCENARIO.match(line):
            continue
        case_id = None
        above = index - 1
        while above >= 0 and lines[above].strip().startswith("@"):
            match = _CASE_TAG.search(lines[above])
            if match:
                case_id = match.group(1)
            above -= 1
        if case_id is None:
            below = index + 1
            while below < len(lines) and not lines[below].strip():
                below += 1
            match = _CASE_STEP.match(lines[below]) if below < len(lines) else None
            case_id = match.group(1) if match else None
        if case_id is not None:
            found[index + 1] = case_id
    return found


def case_statuses(gen_dir: Path, s07_dir: Path) -> dict[str, str]:
    """케이스 id → 시나리오 status(passed|failed|undefined|uncompilable). 결과 줄이 없는 케이스는 빠진다."""
    results_path = s07_dir / "scenario-results.json"
    if not results_path.is_file():
        return {}
    by_test: dict[str, str] = {}
    for line in scenarios.parse_results_file(results_path):
        if isinstance(line, dict) and isinstance(line.get("testId"), str):
            by_test[line["testId"]] = line.get("status")
    ident = scenarios.GenIdent.from_gen_id(gen_dir.name)
    case_lines = {relative: _case_by_line((gen_dir / relative).read_text(encoding="utf-8"))
                  for relative in scenarios.feature_files(gen_dir)}
    statuses: dict[str, str] = {}
    for ref in scenarios.pickle_refs(gen_dir, ident):
        case_id = case_lines.get(ref.feature, {}).get(ref.line)
        if case_id is not None and ref.test_id in by_test:
            statuses[case_id] = by_test[ref.test_id]
    return statuses


def _in_class(code: int | None, klass) -> bool | None:
    if code is None or not isinstance(klass, str) or not re.fullmatch(r"[1-5]xx", klass):
        return None
    return str(code)[0] == klass[0]


def summarize(gen_dir: Path, s07_dir: Path) -> dict:
    """det generation 하나의 결과 블록(compare.json `deterministic.summary`)."""
    gen_dir, s07_dir = Path(gen_dir), Path(s07_dir)
    document = _read_json(gen_dir / CASES_FILE)
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise ValueError(f"{CASES_FILE}이 없거나 형식이 맞지 않는다")
    cases: list[dict] = document["cases"]
    statuses = case_statuses(gen_dir, s07_dir)
    cucumber = s07_dir / "cucumber.json"
    try:
        codes = observed_codes(cucumber.read_text(encoding="utf-8")) if cucumber.is_file() else {}
    except ValueError:
        codes = {}

    strict: dict[str, bool] = {}
    klass: dict[str, bool | None] = {}
    unknown: list[dict] = []
    not_run = 0
    for case in cases:
        case_id, status = case["id"], statuses.get(case["id"])
        strict[case_id] = status == "passed"
        if status == "passed":
            klass[case_id] = True
        elif status == "failed":
            klass[case_id] = _in_class(codes.get(case_id), (case.get("expect") or {}).get("class"))
            if klass[case_id] is None:
                unknown.append({"case": case_id, "reason": "실패 메시지에서 관측 코드(DET-STATUS)를 찾지 못했다"})
        else:
            not_run += 1
            klass[case_id] = None
            unknown.append({"case": case_id, "reason": f"실행되지 않았다({status or '결과 줄 없음'})"})

    baseline: dict[str, str] = {}
    for case in cases:
        if case.get("rule") == BASELINE_RULE:
            status = statuses.get(case["id"])
            baseline[case["endpoint"]] = "passed" if status == "passed" else ("failed" if status == "failed" else "notRun")

    blocked = verified = unpaired = 0
    for case in cases:
        if case.get("rule") != VIOLATION_RULE:
            continue
        endpoint_baseline = baseline.get(case["endpoint"])
        if endpoint_baseline == "failed":
            blocked += 1
        pair = case.get("pair")
        if pair is None:
            unpaired += 1
            continue
        if strict[case["id"]] and strict.get(pair, False) and endpoint_baseline == "passed":
            verified += 1

    by_rule: dict[str, dict[str, int]] = {}
    for case in cases:
        slot = by_rule.setdefault(case.get("rule") or "", {"generated": 0, "passedStrict": 0})
        slot["generated"] += 1
        slot["passedStrict"] += int(strict[case["id"]])

    mismatch = []
    for case in cases:
        expect = case.get("expect") or {}
        bbtg, graph = expect.get("bbtgCode"), expect.get("graphStatus")
        if bbtg is None or graph is None or bbtg == graph:
            continue
        observed = codes.get(case["id"])
        if observed is None and strict[case["id"]] and isinstance(expect.get("strict"), int):
            observed = expect["strict"]
        mismatch.append({"case": case["id"], "bbtgCode": bbtg, "graphStatus": graph, "observed": observed})

    total = len(cases)
    pairwise = _pairwise_summary(document, cases)
    return {
        "cases": total,
        "unresolved": len(document.get("unresolved") or []),
        "universe": document.get("universe") or {},
        "passStrict": {"passed": sum(strict.values()), "total": total},
        "passClass": {"passed": sum(1 for value in klass.values() if value), "total": total},
        "classUnknown": sum(1 for item in unknown if item["case"] in statuses and statuses[item["case"]] == "failed"),
        "notRun": not_run,
        "classUnknownCases": unknown,
        "baselineValid": dict(sorted(baseline.items())),
        "blockedByBaseline": blocked,
        "verifiedViolations": verified,
        "unpaired": unpaired,
        "byRule": dict(sorted(by_rule.items())),
        "statusMismatch": mismatch,
        "pairwise": pairwise,
    }


def _pairwise_summary(document: dict, cases: list[dict]) -> dict | None:
    """compare det 블록의 pairwise 객체. disabled·unavailable이면 None."""
    universe = (document.get("universe") or {}).get("pairwise")
    if not isinstance(universe, dict):
        return None
    if any(isinstance(item, dict) and item.get("reason") == PAIRWISE_UNAVAILABLE for item in document.get("unresolved") or []):
        return None
    by_endpoint = list((universe.get("byEndpoint") or {}).values())
    pairwise_cases = [case for case in cases if case.get("rule") == PAIRWISE_RULE]

    def with_prefix(prefix: str) -> int:
        return sum(1 for case in pairwise_cases if any(str(a).startswith(prefix) for a in case.get("assumes") or []))

    return {"order": universe.get("order"),
            "interactionsFeasible": sum(int(entry.get("interactionsFeasible") or 0) for entry in by_endpoint),
            "interactionsCovered": sum(int(entry.get("interactionsCovered") or 0) for entry in by_endpoint),
            "undetermined": with_prefix(UNDETERMINED_PREFIX),
            "relCombined": with_prefix(REL_COMBINED_PREFIX)}


# --- 커버리지 비교(det pairwise 설계 §5.5, REQ-317) ------------------------------------------------------
COMPARE_REL = Path("S12") / "compare" / "compare.json"
# 비교 키: (이름, tools.lock 안의 경로). path는 run마다 달라 비교하지 않는다
_LOCK_KEYS = (("jacocoCoreEmbedded", ("jacocoCoreEmbedded",)),
              ("pjacoco.version", ("pjacoco", "version")), ("pjacoco.sha256", ("pjacoco", "sha256")),
              ("jacococli.version", ("jacococli", "version")), ("jacococli.sha256", ("jacococli", "sha256")))


def _lock(run_dir: Path) -> dict:
    import yaml
    try:
        data = yaml.safe_load((run_dir / "tools.lock").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _dig(data, keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _sut_commit(run_dir: Path, lock: dict):
    """SUT 커밋: run.json `commit`, 없으면 tools.lock `sut.commit`."""
    run = _read_json(run_dir / "run.json", {}) or {}
    return run.get("commit") if isinstance(run, dict) and run.get("commit") else _dig(lock, ("sut", "commit"))


def _det_coverage(run_dir: Path) -> dict | None:
    """`S12/compare/compare.json` `arms.det.metrics`의 line·branch(stat이면 mean). 없으면 None."""
    document = _read_json(run_dir / COMPARE_REL)
    metrics = _dig(document, ("arms", "det", "metrics"))
    if not isinstance(metrics, dict):
        return None
    values = {}
    for name in ("line", "branch"):
        value = metrics.get(name)
        value = value.get("mean") if isinstance(value, dict) else value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        values[name] = value
    return values


def coverage_comparison(current_run: Path, run3_run: Path) -> dict:
    """두 run(새 run, run3 기준)의 det 커버리지 비교. SUT 커밋·jacoco 항목이 하나라도 다르면 비교 불가."""
    current_run, run3_run = Path(current_run), Path(run3_run)
    current_lock, run3_lock = _lock(current_run), _lock(run3_run)
    differ = []
    pairs = [("sut.commit", _sut_commit(current_run, current_lock), _sut_commit(run3_run, run3_lock))]
    pairs += [(name, _dig(current_lock, keys), _dig(run3_lock, keys)) for name, keys in _LOCK_KEYS]
    for name, mine, theirs in pairs:
        if mine is None or theirs is None or mine != theirs:
            differ.append(name)
    if differ:
        return {"comparable": False, "reason": f"비교 불가: 다른 키 {', '.join(differ)}"}
    current, run3 = _det_coverage(current_run), _det_coverage(run3_run)
    missing = [f"{run.name}/{COMPARE_REL.as_posix()}" for run, value in ((current_run, current), (run3_run, run3))
               if value is None]
    if missing:
        return {"comparable": False, "reason": f"비교 불가: compare.json의 det line·branch가 없다({', '.join(missing)})"}
    return {"comparable": True, "current": current, "run3": run3,
            "delta": {name: round(current[name] - run3[name], 6) for name in ("line", "branch")}}
