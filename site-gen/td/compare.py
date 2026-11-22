"""S12 비교: arm별 generation 지표를 모아 `compare.json`을 만들고 판정한다(설계 §6.12, REQ-040/041/042/067).

입력은 앞 단계 산출물뿐이다: S06/bdd-gen.json(토큰, 시간), S07/<genId>/summary.json(시나리오 결과), S08/coverage.json과
S08/<suite>/attributed/jacoco.xml(귀속 커버리지), S03/ontology-jqa.json(엔드포인트 분모), suts/<sut>/{oracle.yaml, sut.yaml}.
오라클은 평가 전용이라 이 모듈만 읽는다(번들 조립 쪽은 `td.bundle`의 content 검사 대상으로만 쓴다).

지표 정의(표본 수가 작아 전부 "탐색적 관찰"이다):
- compile: 1 - uncompilable 시나리오 / 시나리오 수, undefined: undefined 시나리오 비율, passed: passed / 시나리오 수.
- endpoint: view=false Endpoint 중 `props.handler` 메서드가 그 generation의 귀속 XML에서 커버 라인을 1개 이상 가진 비율.
- line/branch: 귀속 라인·브랜치 비율. lineDelta/branchDelta: blackbox 스위트 대비 증감. uniqueLines: blackbox가 커버하지 않던 라인 수.
- oracle: oracle.yaml 규칙 중 (class, line)의 귀속 브랜치 커버(cb > 0)가 있는 비율.
- focus: sut.yaml compare.focus(패키지 글로브)에 드는 클래스만 다시 집계한 line/branch/endpoint/oracle(통과율은 시나리오-클래스 대응이 없어 제외).
- tokens(입력+출력), seconds: S06 생성 호출 비용.
S06/S07에서 실패해 측정되지 못한 generation은 평균에서 빼고 `failed`로 표시한다(요청 reps 대비 n을 함께 적는다).

det arm(결정적 생성, LLM 없음, 조건식 포함)은 입력 체제가 달라 **참고 열**이다(설계 §2 G4). 같은 지표를 내지만 사전 등록 판정
(`verdict.judge`)에는 base·jqa·owl만 명시적으로 넘긴다. det 고유 결과(strict/class 통과, baseline, 검증된 위반)는
`deterministic` 블록(`td.detgen.results.summarize`)으로 따로 보고한다. det를 요청하지 않은 run에서는 det 열과 블록이 없다(null).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema

from td import state, verdict
from td.verdict import ArmStats

SCHEMA_PATH = Path(__file__).parent / "schemas" / "compare.schema.json"
DET_FACTORS_FILE = "factors.json"   # det generation의 조합 시각화 입력(td.detviz.FACTORS_FILE과 같다)
DET_VIZ_FILE = "det-viz.json"
DET_HTML_FILE = "det.html"
ARMS_ORDER = ("base", "jqa", "owl", "det")
VERDICT_ARMS = ("base", "jqa", "owl")   # 사전 등록 판정 대상. det는 참고 열이라 넣지 않는다
REFERENCE_ARMS = ("det",)
# arm별 입력 체제: LLM 사용 여부, 조건식(분기 조건 원문) 입력 여부, 그래프 입력
INPUT_REGIMES = {
    "base": {"llm": True, "conditions": False, "graph": "none"},
    "jqa": {"llm": True, "conditions": False, "graph": "jqa"},
    "owl": {"llm": True, "conditions": False, "graph": "owl"},
    "det": {"llm": False, "conditions": True, "graph": "jqa+ext"},
}
METRIC_KEYS = ("scenarios", "compile", "undefined", "passed", "endpoint", "line", "branch", "lineDelta", "branchDelta",
               "uniqueLines", "oracle", "oracleCovered", "focusLine", "focusBranch", "focusEndpoint", "focusOracle",
               "tokens", "seconds")
LIMITATIONS = [
    "온톨로지(OWL)는 jQA가 SUT 소스에서 뽑은 그래프에서 파생한다. jqa와 owl arm은 같은 정보원을 다른 형식으로 줄 뿐 독립 정보가 아니다.",
    "모델이 SUT의 원본(upstream) 공개 프로젝트를 학습했을 수 있다(사전 지식 오염). 그래서 fork 고유 기능 범위(sut.yaml compare.focus)의 지표를 따로 집계한다.",
    "귀속 한계: 보안 필터 체인 등 요청 경로의 일부 커버리지는 TC에 귀속되지 않고 집계(aggregate)에만 남는다.",
    "표본이 작다(arm당 reps회). 평균과 범위는 탐색적 관찰이며 통계적 유의성을 주장하지 않는다.",
    "오라클은 작성자가 기준 커밋 소스를 읽고 쓴 평가 전용 목록이다. 목록에 없는 규칙의 커버는 측정하지 않는다.",
]


class CompareError(RuntimeError):
    pass


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# --- 입력: 온톨로지 엔드포인트, 오라클 -----------------------------------------------------------
def api_endpoints(ontology: dict) -> list[dict]:
    """S03 온톨로지의 view=false Endpoint(분모). 정렬해 결정적으로 돌려준다."""
    found = []
    for node in ontology.get("nodes", []):
        props = node.get("props") or {}
        if node.get("kind") == "Endpoint" and props.get("view") is False and props.get("handler"):
            found.append({"id": node["id"], "handler": props["handler"]})
    return sorted(found, key=lambda item: item["id"])


def load_oracle(path) -> list[dict]:
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = data.get("rules") or []
    for rule in rules:
        missing = {"id", "class", "line", "description"} - set(rule)
        if missing:
            raise CompareError(f"oracle 규칙에 필드가 없다({sorted(missing)}): {rule.get('id')}")
    return rules


def _expected_endpoint_count(sut_file) -> int | None:
    path = Path(sut_file).parent / "expected-endpoints.yaml"
    if not path.is_file():
        return None
    import yaml
    return len((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("endpoints") or [])


# --- 귀속 XML 사실 -----------------------------------------------------------------------------
class XmlFacts:
    """jacoco XML 하나에서 비교에 필요한 사실만 뽑는다: 커버 라인, 브랜치 커버 라인, 메서드 커버, 클래스별 카운터."""

    def __init__(self, xml_path):
        root = ET.parse(xml_path).getroot()
        self.covered_lines: set[tuple[str, int]] = set()
        self.branch_lines: set[tuple[str, int]] = set()
        self.branch_probe_lines: set[tuple[str, int]] = set()
        self.method_covered: dict[tuple[str, str], bool] = {}
        self.class_counters: dict[str, dict[str, tuple[int, int]]] = {}
        for package in root.iter("package"):
            package_name = package.get("name")
            for sourcefile in package.findall("sourcefile"):
                key = f"{package_name}/{sourcefile.get('name')}"
                for line in sourcefile.findall("line"):
                    number = int(line.get("nr"))
                    if int(line.get("cb")) + int(line.get("mb")) > 0:
                        self.branch_probe_lines.add((key, number))
                    if int(line.get("cb")) > 0:
                        self.branch_lines.add((key, number))
                    if int(line.get("ci")) > 0 or int(line.get("cb")) > 0:
                        self.covered_lines.add((key, number))
            for klass in package.findall("class"):
                fqcn = klass.get("name").replace("/", ".")
                self.class_counters[fqcn] = {c.get("type"): (int(c.get("covered")), int(c.get("missed")))
                                             for c in klass.findall("counter")}
                for method in klass.findall("method"):
                    line_counter = next((c for c in method.findall("counter") if c.get("type") == "LINE"), None)
                    covered = line_counter is not None and int(line_counter.get("covered")) > 0
                    slot = (fqcn, method.get("name"))
                    self.method_covered[slot] = self.method_covered.get(slot, False) or covered

    def handler_known(self, handler: str) -> bool:
        klass, _, method = handler.partition("#")
        return (klass, method) in self.method_covered

    def handler_covered(self, handler: str) -> bool:
        klass, _, method = handler.partition("#")
        return self.method_covered.get((klass, method), False)

    def oracle_covered(self, rule: dict) -> bool:
        return (_source_key(rule["class"]), int(rule["line"])) in self.branch_lines

    def has_branch_probe(self, rule: dict) -> bool:
        return (_source_key(rule["class"]), int(rule["line"])) in self.branch_probe_lines

    def focus_counts(self, focus: str | None) -> dict[str, tuple[int, int]]:
        totals = {"LINE": [0, 0], "BRANCH": [0, 0]}
        for fqcn, counters in self.class_counters.items():
            if focus and fnmatch.fnmatchcase(fqcn, focus):
                for kind in totals:
                    covered, missed = counters.get(kind, (0, 0))
                    totals[kind][0] += covered
                    totals[kind][1] += missed
        return {kind: (pair[0], pair[1]) for kind, pair in totals.items()}


def _source_key(fqcn: str) -> str:
    return fqcn.split("$", 1)[0].replace(".", "/") + ".java"


def _delta(value, base) -> float | None:
    return None if value is None or base is None else value - base


def _ratio(covered: int, total: int) -> float | None:
    return covered / total if total else None


def _in_focus(name: str, focus: str | None) -> bool:
    return bool(focus) and fnmatch.fnmatchcase(name.partition("#")[0], focus)


# --- generation 하나 ---------------------------------------------------------------------------
def _generation_entry(gen_id: str, arm: str, ctx: dict) -> dict:
    run_dir: Path = ctx["run_dir"]
    s06 = ctx["bddgen"].get(gen_id, {})
    s06_stage = ctx["s06_stage"].get(gen_id, {})
    entry: dict = {"genId": gen_id, "arm": arm, "rep": s06.get("rep") or s06_stage.get("rep"), "status": "measured", "reason": None}
    tokens = s06.get("tokens") or {}
    entry["tokens"] = (tokens.get("in") or 0) + (tokens.get("out") or 0) if tokens else None
    entry["seconds"] = s06.get("seconds")
    if s06.get("status") == "failed" or s06_stage.get("status") == "failed":
        return {**entry, "status": "failed", "reason": s06.get("reason") or s06_stage.get("reason") or "S06 실패"}
    summary = _read_json(run_dir / "S07" / gen_id / "summary.json")
    if summary is None:
        return {**entry, "status": "failed", "reason": "S07 결과가 없다(실행하지 않았거나 실패)"}
    counts = summary.get("statusCounts") or {}
    scenarios = int(summary.get("scenarios") or 0)
    entry["scenarios"] = scenarios
    entry["compile"] = _ratio(scenarios - int(counts.get("uncompilable", 0)), scenarios)
    entry["undefined"] = summary.get("undefinedRatio") if summary.get("undefinedRatio") is not None else _ratio(int(counts.get("undefined", 0)), scenarios)
    entry["passed"] = _ratio(int(counts.get("passed", 0)), scenarios)
    suite = ctx["suites"].get(f"e2e-{gen_id}")
    xml_rel = (((suite or {}).get("paths") or {}).get("attributed") or {}).get("xml")
    entry.update({"endpoint": None, "endpointCovered": None, "uncoveredEndpoints": [], "line": None, "branch": None,
                  "lineDelta": None, "branchDelta": None, "uniqueLines": None, "oracle": None, "oracleCovered": None,
                  "oracleRules": [], "focusLine": None, "focusBranch": None, "focusEndpoint": None, "focusOracle": None})
    if not suite or not xml_rel or not (run_dir / "S08" / xml_rel).is_file():
        entry["coverageNote"] = "S08 귀속 커버리지가 없다"
        return entry
    facts = XmlFacts(run_dir / "S08" / xml_rel)
    kpis = suite.get("kpis") or {}
    entry["line"], entry["branch"] = kpis.get("line"), kpis.get("branch")
    endpoints, rules, focus = ctx["endpoints"], ctx["rules"], ctx["focus"]
    for item in endpoints:
        if not facts.handler_known(item["handler"]):
            ctx["warnings"].add(f"핸들러가 jacoco XML에 없다(커버 0으로 센다): {item['handler']} ({gen_id})")
    hit = [item for item in endpoints if facts.handler_covered(item["handler"])]
    entry["endpointCovered"] = len(hit)
    entry["endpoint"] = _ratio(len(hit), len(endpoints))
    entry["uncoveredEndpoints"] = [item["id"] for item in endpoints if item not in hit]
    entry["oracleRules"] = [{"id": rule["id"], "covered": facts.oracle_covered(rule)} for rule in rules]
    entry["oracleCovered"] = sum(1 for item in entry["oracleRules"] if item["covered"])
    entry["oracle"] = _ratio(entry["oracleCovered"], len(rules))
    blackbox = ctx.get("blackbox")
    if blackbox:
        entry["lineDelta"] = _delta(kpis.get("line"), blackbox["kpis"].get("line"))
        entry["branchDelta"] = _delta(kpis.get("branch"), blackbox["kpis"].get("branch"))
        entry["uniqueLines"] = len(facts.covered_lines - blackbox["facts"].covered_lines)
    if focus:
        counts_focus = facts.focus_counts(focus)
        entry["focusLine"] = _ratio(counts_focus["LINE"][0], sum(counts_focus["LINE"]))
        entry["focusBranch"] = _ratio(counts_focus["BRANCH"][0], sum(counts_focus["BRANCH"]))
        focus_endpoints = [item for item in endpoints if _in_focus(item["handler"], focus)]
        entry["focusEndpoint"] = _ratio(sum(1 for item in focus_endpoints if item in hit), len(focus_endpoints))
        focus_rules = [rule for rule in rules if _in_focus(rule["class"], focus)]
        covered_rules = {item["id"] for item in entry["oracleRules"] if item["covered"]}
        entry["focusOracle"] = _ratio(sum(1 for rule in focus_rules if rule["id"] in covered_rules), len(focus_rules))
    return entry


# --- arm 집계 ----------------------------------------------------------------------------------
def _stat(values: list[float]) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"mean": None, "min": None, "max": None, "n": 0}
    return {"mean": math.fsum(values) / len(values), "min": min(values), "max": max(values), "n": len(values)}


def _arm_entry(arm: str, status: str, reason: str | None, generations: list[dict], reps, requested_reps=None) -> dict:
    measured = [g for g in generations if g["status"] == "measured"]
    metrics = {key: {**_stat([g.get(key) for g in measured]), "values": [g.get(key) for g in measured]} for key in METRIC_KEYS}
    entry = {"arm": arm, "status": status, "reason": reason, "reps": reps,
             "requestedReps": requested_reps if requested_reps is not None else reps,
             "inputRegime": dict(INPUT_REGIMES[arm]), "measured": len(measured),
             "failedGenerations": [{"genId": g["genId"], "reason": g["reason"]} for g in generations if g["status"] == "failed"],
             "metrics": metrics, "generations": generations}
    if status == "ok" and not measured:
        entry["status"], entry["reason"] = "skipped", reason or "측정된 generation이 없다"
    return entry


def arm_stats(arm_entry: dict) -> ArmStats:
    """compare.json의 arm 항목을 판정 함수 입력으로 바꾼다."""
    if arm_entry["status"] != "ok":
        return ArmStats(status="skipped", reason=arm_entry.get("reason"))
    mapping = {"compile": "compile", "undefined": "undefined", "passed": "passed", "endpoint": "endpoint", "branch": "branch",
               "oracle": "oracle"}
    metrics = {name: [v for v in arm_entry["metrics"][key]["values"] if v is not None] for name, key in mapping.items()}
    return ArmStats(status="ok", metrics=metrics)


# --- 수집 --------------------------------------------------------------------------------------
def collect(run_dir, *, sut_file=None, oracle_path=None) -> dict:
    run_dir = Path(run_dir)
    run = state.read_run(run_dir)
    coverage = _read_json(run_dir / "S08" / "coverage.json")
    if coverage is None:
        raise CompareError("S08/coverage.json이 없다(S08이 실행되지 않았다)")
    ontology = _read_json(run_dir / "S03" / "ontology-jqa.json")
    if ontology is None:
        raise CompareError("S03/ontology-jqa.json이 없다(엔드포인트 분모를 알 수 없다)")
    endpoints = api_endpoints(ontology)
    if not endpoints:
        raise CompareError("온톨로지에 view=false Endpoint가 없다")
    focus = rules = None
    expected = None
    if sut_file:
        from td import sut_config
        focus = sut_config.load(sut_file).compare_focus
        expected = _expected_endpoint_count(sut_file)
        oracle_path = oracle_path or Path(sut_file).parent / "oracle.yaml"
    rules = load_oracle(oracle_path) if oracle_path and Path(oracle_path).is_file() else []
    bddgen = {g["genId"]: g for g in (_read_json(run_dir / "S06" / "bdd-gen.json", {}) or {}).get("generations", [])}
    s06 = _read_json(run_dir / "stages" / "S06.json", {}) or {}
    s06_arms = s06.get("arms") or {}
    s06_generations = s06.get("generations") or {}
    suites = coverage.get("suites") or {}
    blackbox = None
    bb_suite = suites.get("blackbox")
    bb_xml = (((bb_suite or {}).get("paths") or {}).get("attributed") or {}).get("xml")
    if bb_suite and bb_xml and (run_dir / "S08" / bb_xml).is_file():
        blackbox = {"kpis": bb_suite["kpis"], "facts": XmlFacts(run_dir / "S08" / bb_xml)}
    ctx = {"run_dir": run_dir, "bddgen": bddgen, "s06_stage": s06_generations, "suites": suites, "endpoints": endpoints,
           "rules": rules, "focus": focus, "blackbox": blackbox, "warnings": set()}

    options = run.get("options") or {}
    requested = options.get("arms") or list(s06_arms) or ["base"]
    reps = options.get("reps") or (_read_json(run_dir / "S06" / "bdd-gen.json", {}) or {}).get("reps")
    reps_by_arm = state.requested_reps_by_arm(run_dir)
    arms: dict[str, dict] = {}
    for arm in ARMS_ORDER:
        stage_arm = s06_arms.get(arm)
        if arm not in requested and stage_arm is None:
            if arm in REFERENCE_ARMS:
                continue  # 참고 열은 요청했을 때만 보인다
            arms[arm] = _arm_entry(arm, "skipped", state.NOT_REQUESTED, [], reps, reps_by_arm.get(arm))
            continue
        arm_reps = reps_by_arm.get(arm, state.reps_by_arm([arm], reps or 1)[arm])
        if stage_arm and stage_arm.get("status") == "skipped":
            arms[arm] = _arm_entry(arm, "skipped", stage_arm.get("reason") or "S06에서 건너뜀", [], reps, arm_reps)
            continue
        gen_ids = [gid for gid, g in bddgen.items() if g.get("arm") == arm] or list((stage_arm or {}).get("generations") or [])
        if not gen_ids:
            arms[arm] = _arm_entry(arm, "skipped", (stage_arm or {}).get("reason") or "generation이 없다", [], reps, arm_reps)
            continue
        generations = [_generation_entry(gid, arm, ctx) for gid in sorted(gen_ids)]
        arms[arm] = _arm_entry(arm, "ok", None, generations, reps, arm_reps)
    warnings = sorted(ctx["warnings"])
    if expected is not None and expected != len(endpoints):
        warnings.insert(0, f"엔드포인트 분모({len(endpoints)})가 기대 목록 수({expected})와 다르다")
    result = verdict.judge({name: arm_stats(arms[name]) for name in VERDICT_ARMS if name in arms})

    # clockShift는 run.json 기록(clockShift, 없으면 startedAt/finishedAt)만 쓴다. 현재 시각과 비교하지 않으므로
    # 다른 날 다시 렌더링해도 값이 바뀌지 않는다.
    tz = run.get("tz") or state.TZ_NAME
    started, finished = run.get("startedAt"), run.get("finishedAt")
    shift = bool(run.get("clockShift"))
    if not shift and started and finished:
        from zoneinfo import ZoneInfo
        shift = state.parse_utc(started).astimezone(ZoneInfo(tz)).date() != state.parse_utc(finished).astimezone(ZoneInfo(tz)).date()
    document = {
        "schema": 1, "runId": run.get("runId"), "sut": run.get("sut"), "commit": run.get("commit"),
        "label": verdict.EXPLORATORY, "reps": reps,
        "endpoints": {"denominator": len(endpoints), "expected": expected, "ids": [item["id"] for item in endpoints]},
        "oracle": {"rules": len(rules), "ids": [rule["id"] for rule in rules]},
        "focus": focus, "blackbox": ({"line": blackbox["kpis"].get("line"), "branch": blackbox["kpis"].get("branch")} if blackbox else None),
        "requestedRepsByArm": {arm: reps_by_arm[arm] for arm in ARMS_ORDER if arm in reps_by_arm},
        "arms": arms, "verdict": result.as_dict(), "deterministic": _deterministic(run_dir, run, arms.get("det")),
        "warnings": warnings,
        "clock": {"clockShift": shift, "tz": tz, "startedAt": started, "finishedAt": finished},
        "limitations": LIMITATIONS,
    }
    return document


def _deterministic(run_dir: Path, run: dict, det_entry: dict | None) -> dict | None:
    """det generation의 결과 블록. det를 돌리지 않았으면 None, 집계할 수 없으면 status=failed와 사유."""
    if det_entry is None or det_entry["status"] != "ok" or not det_entry["generations"]:
        return None
    from td import scenarios
    from td.detgen import results
    generation = det_entry["generations"][0]
    gen_id = generation["genId"]
    block = {"genId": gen_id, "status": "failed", "reason": None, "summary": None}
    if generation["status"] != "measured":
        return {**block, "reason": generation.get("reason") or "측정되지 않은 generation"}
    try:
        gen_dir = scenarios.generation_dir(run.get("sut") or "", gen_id)
        summary = results.summarize(gen_dir, run_dir / "S07" / gen_id)
    except Exception as exc:  # noqa: BLE001 - det 집계의 어떤 실패도 다른 arm·판정에 번지지 않게 이 블록의 failed로 가둔다
        return {**block, "reason": _failure_reason("det 결과 집계 실패", exc)}
    # 조합 시각화는 여기서 만들지 않는다(파일 쓰기 없음). factors.json 유무만 보고 "만들 예정(ok)"/absent를 적는다.
    viz_status = "ok" if (gen_dir / DET_FACTORS_FILE).is_file() else "absent"
    return {**block, "status": "measured", "summary": summary, "viz": {"status": viz_status, "reason": None}}


def _failure_reason(prefix: str, exc: BaseException) -> str:
    """예외를 한 줄 사유로(첫 줄 300자, 홈 경로·식별자 가림)."""
    from td import redact
    first_line = str(exc).splitlines()[0][:300] if str(exc) else ""
    detail = f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
    return redact.redact_text(f"{prefix}: {detail}")


def validate(document: dict) -> None:
    jsonschema.validate(document, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def write_document(out_dir, document: dict) -> Path:
    target = Path(out_dir) / "compare.json"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


# --- det 조합 시각화(det-viz.json, det.html) ---------------------------------------------------------
def _viz_block(document: dict) -> dict | None:
    """measured 변형 deterministic 블록의 `viz`(없으면 None: det 없음·failed 변형·예전 문서의 viz 키 없음)."""
    det = document.get("deterministic")
    if not isinstance(det, dict) or det.get("status") != "measured":
        return None
    viz = det.get("viz")
    return viz if isinstance(viz, dict) else None


def _mark_viz_failed(document: dict, reason: str) -> None:
    det = document["deterministic"]
    det["viz"] = {"status": "failed", "reason": reason}


def _remove_det_files(out_dir: Path) -> None:
    for name in (DET_VIZ_FILE, DET_HTML_FILE):
        (out_dir / name).unlink(missing_ok=True)


def render_det_html(viz_doc: dict, css_href: str, nav_html: str | None = None) -> str:
    """det-viz 문서 → 단독으로 열리는 det.html 문자열. Cytoscape와 detviz.js를 인라인하고 데이터는 JSON 스크립트에 싣는다."""
    from td.site.pages import STATIC_DIR, jinja_env, json_for_script
    summary = viz_doc["aggregates"]["summary"]
    return jinja_env().get_template("det.html.j2").render(
        gen_id=viz_doc.get("genId"), summary=summary, css_href=css_href, nav_html=nav_html, data_json=json_for_script(viz_doc),
        cytoscape_js=(STATIC_DIR / "vendor" / "cytoscape.min.js").read_text(encoding="utf-8"),
        viz_js=(STATIC_DIR / "detviz.js").read_text(encoding="utf-8"))


def _render_det_page(out_dir: Path, document: dict, css_href: str, nav_html: str | None = None) -> None:
    """det.html을 그리거나 지운다. det-viz.json이 있고 viz ok일 때만 그린다. viz 키가 없으면 absent로 보고 문서는 그대로 둔다.
    렌더 실패(또는 ok인데 det-viz.json이 없음)는 det 파일을 지우고 메모리 문서의 viz를 failed로 바꾼다(compare.html은 계속)."""
    viz = _viz_block(document)
    data_path = out_dir / DET_VIZ_FILE
    if viz is None or viz.get("status") != "ok":
        _remove_det_files(out_dir)
        return
    try:
        if not data_path.is_file():
            raise FileNotFoundError(f"{DET_VIZ_FILE}이 없다")
        from td import detviz
        viz_doc = json.loads(data_path.read_text(encoding="utf-8"))
        detviz.validate(viz_doc)
        (out_dir / DET_HTML_FILE).write_text(render_det_html(viz_doc, css_href, nav_html), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - 시각화 실패는 compare 결과를 실패시키지 않는다(REQ-209)
        _remove_det_files(out_dir)
        _mark_viz_failed(document, _failure_reason("det 조합 시각화 렌더 실패", exc))


def _build_det_viz(run_dir: Path, out_dir: Path, document: dict) -> None:
    """viz ok면 detviz.build를 한 번 불러 det-viz.json을 쓴다. 실패는 viz failed(파일 삭제), factors.json이 사라졌으면 absent."""
    viz = _viz_block(document)
    if viz is None or viz.get("status") != "ok":
        return
    from td import detviz, scenarios
    gen_id = document["deterministic"]["genId"]
    try:
        gen_dir = scenarios.generation_dir(state.read_run(run_dir).get("sut") or "", gen_id)
        viz_doc = detviz.build(gen_dir, run_dir / "S07" / gen_id)
        detviz.validate(viz_doc)
        (out_dir / DET_VIZ_FILE).write_text(json.dumps(viz_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except detviz.FactorsMissing:
        _remove_det_files(out_dir)
        document["deterministic"]["viz"] = {"status": "absent", "reason": None}
    except Exception as exc:  # noqa: BLE001 - 시각화 실패는 compare 결과를 실패시키지 않는다(REQ-209)
        _remove_det_files(out_dir)
        _mark_viz_failed(document, _failure_reason("det 조합 시각화 생성 실패", exc))


# --- 화면 ---------------------------------------------------------------------------------------
def render_page(out_dir, document: dict, css_href: str = "app.css", copy_css: bool = True, nav_html: str | None = None) -> Path:
    """`compare.html`을 쓴다. copy_css=True면 단독 열람용으로 app.css를 같은 디렉터리에 둔다(사이트 조립은 False와
    `…/static/v2/app.css`, 공통 띠 nav_html). det.html을 먼저 그리고(또는 지우고), compare.html은 det.html 파일이 있을 때만
    링크한다. det.html 실패는 `document`의 deterministic.viz를 failed로 바꿀 수 있다(호출자가 바뀐 문서를 저장한다)."""
    from td.site.pages import copy_app_css, jinja_env, static_href_of
    out_dir = Path(out_dir)
    if copy_css:
        copy_app_css(out_dir)
    _render_det_page(out_dir, document, css_href, nav_html)
    template = jinja_env().get_template("compare.html.j2")
    html = template.render(doc=document, css_href=css_href, static_href=static_href_of(css_href), nav_html=nav_html,
                           rows=display_rows(document), dots=dot_plots(document),
                           regime_labels={arm: regime_label(entry.get("inputRegime")) for arm, entry in document["arms"].items()},
                           reference_arms=REFERENCE_ARMS, det_viz=_viz_block(document),
                           det_link=(out_dir / DET_HTML_FILE).is_file())
    target = out_dir / "compare.html"
    target.write_text(html, encoding="utf-8")
    return target


# 표에 보일 지표: (키, 이름, 형식). 형식 pct는 비율(%), int는 정수, dpct는 %p 증감, sec는 초.
DISPLAY = [
    ("scenarios", "시나리오 수", "int"), ("compile", "컴파일 가능 비율", "pct"), ("undefined", "undefined 비율", "pct"),
    ("passed", "통과율", "pct"), ("endpoint", "엔드포인트 커버 비율", "pct"), ("line", "귀속 라인 커버", "pct"),
    ("branch", "귀속 브랜치 커버", "pct"), ("lineDelta", "라인 blackbox 대비", "dpct"), ("branchDelta", "브랜치 blackbox 대비", "dpct"),
    ("uniqueLines", "blackbox에 없던 고유 라인", "int"), ("oracle", "오라클 커버 비율", "pct"),
    ("focusLine", "Focus 범위 라인", "pct"), ("focusBranch", "Focus 범위 브랜치", "pct"),
    ("focusEndpoint", "Focus 범위 엔드포인트", "pct"), ("focusOracle", "Focus 범위 오라클", "pct"),
    ("tokens", "토큰(입력+출력)", "int"), ("seconds", "생성 시간(초)", "sec"),
]


def regime_label(regime: dict | None) -> str:
    """입력 체제 표기(예: det → `LLM 없음, 조건식 포함`)."""
    if not regime:
        return ""
    return f"{'LLM 사용' if regime.get('llm') else 'LLM 없음'}, {'조건식 포함' if regime.get('conditions') else '조건식 없음'}"


def format_value(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "dpct":
        return f"{value * 100:+.1f}%p"
    if kind == "sec":
        return f"{value:.0f}"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def display_rows(document: dict) -> list[dict]:
    rows = []
    for key, label, kind in DISPLAY:
        cells = {}
        for arm, entry in document["arms"].items():
            stat = entry["metrics"][key]
            if entry["status"] != "ok" or stat["n"] == 0:
                cells[arm] = None
            else:
                cells[arm] = {"mean": format_value(stat["mean"], kind), "min": format_value(stat["min"], kind),
                              "max": format_value(stat["max"], kind), "n": stat["n"]}
        if key.startswith("focus") and document.get("focus"):
            label = label.replace("Focus 범위", f"Focus 범위 ({document['focus']})")
        rows.append({"key": key, "label": label, "cells": cells})
    return rows


DOT_METRICS = [("endpoint", "엔드포인트 커버"), ("branch", "귀속 브랜치"), ("oracle", "오라클 커버"), ("passed", "통과율")]
DOT_COLORS = {"base": "var(--arm-base)", "jqa": "var(--arm-jqa)", "owl": "var(--arm-owl)", "det": "var(--arm-det)"}  # static/v2/app.css 토큰(라이트/다크)  # 색만으로 구분하지 않도록 arm 이름도 라벨로 적는다.


def dot_plots(document: dict) -> list[dict]:
    """지표마다 arm 행 하나씩, generation 값을 0..1 가로축의 점으로 찍는 인라인 SVG 좌표를 만든다."""
    width, left, right, row_h = 560, 70, 20, 28
    plots = []
    for key, label in DOT_METRICS:
        rows = []
        for index, (arm, entry) in enumerate(document["arms"].items()):
            values = entry["metrics"][key]["values"] if entry["status"] == "ok" else []
            points = [round(left + v * (width - left - right), 1) for v in values if v is not None]
            stat = entry["metrics"][key]
            rows.append({"arm": arm, "y": 20 + index * row_h, "color": DOT_COLORS[arm], "points": points,
                         "values": [f"{v * 100:.1f}%" for v in values if v is not None], "skipped": entry["status"] != "ok",
                         "range": (round(left + stat["min"] * (width - left - right), 1),
                                   round(left + stat["max"] * (width - left - right), 1)) if stat["n"] else None})
        plots.append({"key": key, "label": label, "width": width, "left": left, "right": right,
                      "height": 20 + len(rows) * row_h + 18, "axis_y": 20 + len(rows) * row_h - 6, "rows": rows,
                      "ticks": [{"x": round(left + t * (width - left - right), 1), "text": f"{int(t * 100)}%"} for t in (0, .25, .5, .75, 1)]})
    return plots


# --- CLI ----------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.compare")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="compare.json과 compare.html을 S12/compare에 만들고 run.json kpis.compare를 쓴다")
    run.add_argument("run_dir")
    run.add_argument("--sut-file", required=True)
    args = parser.parse_args(argv)
    out_dir = Path(args.run_dir) / "S12" / "compare"
    try:
        document = collect(args.run_dir, sut_file=args.sut_file)
        validate(document)
    except (CompareError, jsonschema.ValidationError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc).splitlines()[0][:1500]}, ensure_ascii=False))
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        _build_det_viz(Path(args.run_dir), out_dir, document)   # viz ok일 때만 build 1회
        render_page(out_dir, document)                           # det.html(실패 시 viz failed) → compare.html
        viz = _viz_block(document)
        if viz is None or viz.get("status") != "ok":
            _remove_det_files(out_dir)   # absent·failed·det 블록 null·failed 변형: 이전 run의 낡은 파일 방지
        validate(document)
        write_document(out_dir, document)
    except BaseException:
        _remove_det_files(out_dir)   # S12가 실패로 끝나면 이번 run의 det 파일을 남기지 않는다
        raise
    summary = {"generation": document["verdict"]["generation"], "effect": document["verdict"]["effect"],
               "label": document["label"], "arms": {name: entry["status"] for name, entry in document["arms"].items()},
               "endpointDenominator": document["endpoints"]["denominator"], "oracleRules": document["oracle"]["rules"],
               "clockShift": document["clock"]["clockShift"]}
    state.set_run_field(args.run_dir, "kpis.compare", summary)
    degraded = [name for name, entry in document["arms"].items() if entry["status"] != "ok" and entry["reason"] != state.NOT_REQUESTED]
    print(json.dumps({"status": "passed", "reason": None, "outputs": {"compare": str(out_dir)},
                      "extra": {"verdict": document["verdict"]["generation"] + "/" + document["verdict"]["effect"],
                                "skippedArms": degraded}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
