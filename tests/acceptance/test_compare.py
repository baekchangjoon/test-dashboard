"""S12 비교(Task 23): REQ-040 compare.json, REQ-041 오라클 격리·실체성, REQ-067 compare.html, REQ-060 clockShift 경고.
합성 run 디렉터리(손으로 만든 작은 jacoco XML)로 지표 값을 정확히 검증하고, 실제 파일럿 run(work/runs)의 S07/S08 산출물로
분모 17, 오라클 라인 실체성, 보존된 번들 검사를 확인한다(파일럿 run이 없으면 실패한다)."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

from td import bundle, compare, state

REPO_ROOT = Path(__file__).resolve().parents[2]
SUT_FILE = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"
ORACLE_FILE = REPO_ROOT / "suts" / "petclinic" / "oracle.yaml"
EXPECTED_ENDPOINTS = REPO_ROOT / "suts" / "petclinic" / "expected-endpoints.yaml"
SCHEMA = REPO_ROOT / "site-gen" / "td" / "schemas" / "compare.schema.json"
S12_SCRIPT = REPO_ROOT / "pipeline" / "S12-compare.sh"
COMMIT = "b6f939355e8790202ddfc71e3f3507252745ed37"
SERVICE = "org.springframework.samples.petclinic.boarding.ReservationService"
PKG = "org/springframework/samples/petclinic"


# --- 합성 run ----------------------------------------------------------------------------------
def _handlers() -> list[tuple[str, str, str]]:
    data = yaml.safe_load(EXPECTED_ENDPOINTS.read_text())
    return [(item["method"], item["path"], item["handler"]) for item in data["endpoints"]]


def _write_xml(path: Path, *, covered_methods: set[str], oracle_lines: set[int], service_line, service_branch, rrc_line,
               vet_line: bool = True) -> None:
    by_class: dict[str, list[tuple[str, bool]]] = {}
    for _, _, handler in _handlers():
        klass, _, method = handler.partition("#")
        by_class.setdefault(klass, []).append((method, handler in covered_methods))
    packages: dict[str, list[str]] = {}
    for klass, methods in sorted(by_class.items()):
        package, _, simple = klass.rpartition(".")
        counters = {"LINE": rrc_line} if simple == "ReservationRestController" else {"LINE": (1, 1)}
        body = "".join(
            f'<method name="{m}" desc="()V" line="10"><counter type="LINE" missed="{0 if cov else 1}" covered="{1 if cov else 0}"/></method>'
            for m, cov in methods)
        counter_xml = "".join(f'<counter type="{k}" covered="{v[0]}" missed="{v[1]}"/>' for k, v in counters.items())
        packages.setdefault(package.replace(".", "/"), []).append(
            f'<class name="{package.replace(".", "/")}/{simple}" sourcefilename="{simple}.java">{body}{counter_xml}</class>')
    service_lines = "".join(
        f'<line nr="{nr}" mi="{0 if nr in oracle_lines else 1}" ci="{1 if nr in oracle_lines else 0}" mb="{4 - (2 if nr in oracle_lines else 0)}" cb="{2 if nr in oracle_lines else 0}"/>'
        for nr in (49, 52, 55, 64, 70, 73, 76, 124, 128, 159))
    boarding = packages.setdefault(f"{PKG}/boarding", [])
    boarding.append(
        f'<class name="{PKG}/boarding/ReservationService" sourcefilename="ReservationService.java">'
        f'<counter type="LINE" covered="{service_line[0]}" missed="{service_line[1]}"/>'
        f'<counter type="BRANCH" covered="{service_branch[0]}" missed="{service_branch[1]}"/></class>'
        f'<sourcefile name="ReservationService.java">{service_lines}</sourcefile>')
    vet = packages.setdefault(f"{PKG}/vet", [])
    vet.append('<sourcefile name="VetRestController.java">' +
               (f'<line nr="36" mi="0" ci="1" mb="0" cb="0"/>' if vet_line else '<line nr="36" mi="1" ci="0" mb="0" cb="0"/>') +
               "</sourcefile>")
    package_xml = "".join(f'<package name="{name}">{"".join(items)}</package>' for name, items in sorted(packages.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<?xml version="1.0"?><report name="r">{package_xml}</report>')


BASE_COVERED = {"org.springframework.samples.petclinic.vet.VetRestController#getAllVets",
                "org.springframework.samples.petclinic.vet.VetRestController#getVet",
                "org.springframework.samples.petclinic.owner.OwnerRestController#getAllOwners",
                "org.springframework.samples.petclinic.security.AuthController#login",
                "org.springframework.samples.petclinic.boarding.ReservationRestController#create"}
JQA_COVERED = BASE_COVERED | {f"org.springframework.samples.petclinic.boarding.ReservationRestController#{m}"
                              for m in ("get", "list", "update", "delete")} | {
    "org.springframework.samples.petclinic.owner.OwnerRestController#createOwner",
    "org.springframework.samples.petclinic.owner.PetRestController#getPet",
    "org.springframework.samples.petclinic.owner.PetRestController#createPet"}


def make_compare_run(tmp_path: Path, *, with_blackbox: bool = True, started="2026-11-19T01:00:00Z", finished=None, clock_shift=None,
                     owl_skipped: bool = True) -> Path:
    run_dir = tmp_path / "20261119-010000Z-b6f9393-manual-aaaaaaaa"
    run_dir.mkdir()
    state.write_run_meta(run_dir, runId=run_dir.name, sut="petclinic", commit=COMMIT, trigger="manual", startedAt=started,
                         **({"finishedAt": finished} if finished else {}), options={"arms": ["base", "jqa", "owl"], "reps": 2, "style": "cucumber"})
    if clock_shift is not None:
        state.set_run_field(run_dir, "clockShift", clock_shift)
    # S03: view=false 17개(+ 화면 2개)
    nodes = [{"id": f"endpoint:{m} {p}", "kind": "Endpoint", "label": f"{m} {p}",
              "props": {"method": m, "path": p, "handler": h, "view": False}} for m, p, h in _handlers()]
    nodes += [{"id": f"endpoint:GET /owners{i}", "kind": "Endpoint", "label": "v",
               "props": {"method": "GET", "path": f"/owners{i}", "handler": "x.Y#z", "view": True}} for i in range(2)]
    (run_dir / "S03").mkdir()
    (run_dir / "S03" / "ontology-jqa.json").write_text(json.dumps({"nodes": nodes, "edges": [], "meta": {}}))
    # S06
    generations = [
        {"genId": "base-aaaaaaaa-r1", "arm": "base", "rep": 1, "tokens": {"in": 1000, "out": 500}, "seconds": 100.0, "status": "passed", "reason": None},
        {"genId": "jqa-bbbbbbbb-r1", "arm": "jqa", "rep": 1, "tokens": {"in": 2000, "out": 800}, "seconds": 200.0, "status": "passed", "reason": None},
        {"genId": "jqa-bbbbbbbb-r2", "arm": "jqa", "rep": 2, "tokens": {"in": 2000, "out": 100}, "seconds": 50.0, "status": "failed", "reason": "LLM 출력이 깨졌다"}]
    (run_dir / "S06").mkdir()
    (run_dir / "S06" / "bdd-gen.json").write_text(json.dumps({"schema": 1, "reps": 2, "generations": generations}))
    (run_dir / "stages").mkdir()
    s06_arms = {"base": {"status": "passed", "generations": ["base-aaaaaaaa-r1"]},
                "jqa": {"status": "degraded", "reason": "jqa-bbbbbbbb-r2: LLM 출력이 깨졌다", "generations": ["jqa-bbbbbbbb-r1"]}}
    if owl_skipped:
        s06_arms["owl"] = {"status": "skipped", "reason": "S05(OWL 온톨로지) 건너뜀"}
    (run_dir / "stages" / "S06.json").write_text(json.dumps({
        "id": "S06", "status": "degraded", "reason": None, "outputs": {}, "arms": s06_arms,
        "generations": {g["genId"]: {"arm": g["arm"], "rep": g["rep"], "status": "failed" if g["status"] == "failed" else "passed"}
                        for g in generations}}))
    # S07
    for gen, counts in (("base-aaaaaaaa-r1", {"passed": 6, "failed": 4, "undefined": 0, "uncompilable": 0}),
                        ("jqa-bbbbbbbb-r1", {"passed": 16, "failed": 0, "undefined": 2, "uncompilable": 2})):
        total = sum(counts.values())
        (run_dir / "S07" / gen).mkdir(parents=True)
        (run_dir / "S07" / gen / "summary.json").write_text(json.dumps({
            "scenarios": total, "statusCounts": counts, "undefinedRatio": counts["undefined"] / total}))
    # S08
    suites = {}

    def add_suite(name, kpis, **xml_args):
        _write_xml(run_dir / "S08" / name / "attributed" / "jacoco.xml", **xml_args)
        suites[name] = {"kpis": kpis, "tcCount": 1, "attributedCount": 1,
                        "paths": {"attributed": {"xml": f"{name}/attributed/jacoco.xml"}}}

    add_suite("e2e-base-aaaaaaaa-r1", {"line": 0.20, "branch": 0.10}, covered_methods=BASE_COVERED, oracle_lines={49, 52},
              service_line=(4, 12), service_branch=(2, 22), rrc_line=(1, 7))
    add_suite("e2e-jqa-bbbbbbbb-r1", {"line": 0.25, "branch": 0.15}, covered_methods=JQA_COVERED,
              oracle_lines={49, 52, 55, 64, 70, 73, 76, 159}, service_line=(8, 8), service_branch=(6, 18), rrc_line=(4, 4))
    if with_blackbox:
        add_suite("blackbox", {"line": 0.30, "branch": 0.20}, covered_methods=set(), oracle_lines={49}, service_line=(1, 15),
                  service_branch=(1, 23), rrc_line=(0, 8))
    (run_dir / "S08" / "coverage.json").write_text(json.dumps({"suites": suites, "classes": [], "integrity": {"violations": []}, "merged": {}}))
    return run_dir


def collect(run_dir, **kwargs) -> dict:
    return compare.collect(run_dir, sut_file=SUT_FILE, **kwargs)


def test_req040_compare_json(tmp_path):
    run_dir = make_compare_run(tmp_path)
    document = collect(run_dir)
    jsonschema.validate(document, json.loads(SCHEMA.read_text()))
    # 분모: view=false Endpoint 수 = 기대 목록 수 = 17
    assert document["endpoints"]["denominator"] == 17 == document["endpoints"]["expected"] == len(_handlers())
    assert document["label"] == "탐색적 관찰" and document["reps"] == 2
    assert document["oracle"]["rules"] == 10 and document["focus"] == "org.springframework.samples.petclinic.boarding.*"
    assert document["blackbox"] == {"line": 0.30, "branch": 0.20}
    arms = document["arms"]
    # skip된 arm은 status와 사유로 표시된다
    assert arms["owl"]["status"] == "skipped" and "S05" in arms["owl"]["reason"]
    assert [a for a in arms if arms[a]["status"] == "ok"] == ["base", "jqa"]
    # base(generation 1개)
    base = arms["base"]["metrics"]
    assert base["scenarios"]["mean"] == 10 and base["passed"]["mean"] == 0.6 and base["undefined"]["mean"] == 0.0
    assert base["compile"]["mean"] == 1.0
    assert base["endpoint"]["mean"] == pytest.approx(5 / 17) and base["oracle"]["mean"] == 0.2
    assert base["focusEndpoint"]["mean"] == pytest.approx(0.2) and base["focusOracle"]["mean"] == 0.2
    assert base["focusLine"]["mean"] == pytest.approx(5 / 24) and base["focusBranch"]["mean"] == pytest.approx(2 / 24)
    assert base["uniqueLines"]["mean"] == 1  # blackbox는 49와 Vet 36을 커버, base는 49, 52와 Vet 36
    assert base["lineDelta"]["mean"] == pytest.approx(-0.10) and base["branchDelta"]["mean"] == pytest.approx(-0.10)
    assert base["tokens"]["mean"] == 1500 and base["seconds"]["mean"] == 100.0
    # jqa: 두 번째 generation은 S06에서 실패 -> 평균에서 빠지고 사유와 함께 표시된다
    jqa = arms["jqa"]
    assert jqa["measured"] == 1 and jqa["reps"] == 2
    assert jqa["failedGenerations"] == [{"genId": "jqa-bbbbbbbb-r2", "reason": "LLM 출력이 깨졌다"}]
    metrics = jqa["metrics"]
    assert metrics["compile"]["mean"] == pytest.approx(0.9) and metrics["undefined"]["mean"] == pytest.approx(0.1)
    assert metrics["passed"]["mean"] == pytest.approx(0.8)
    assert metrics["endpoint"]["mean"] == pytest.approx(12 / 17) and metrics["endpoint"]["min"] == metrics["endpoint"]["max"]
    assert metrics["oracle"]["mean"] == 0.8 and metrics["oracleCovered"]["mean"] == 8
    assert metrics["focusEndpoint"]["mean"] == 1.0 and metrics["focusLine"]["mean"] == pytest.approx(0.5)
    assert metrics["focusBranch"]["mean"] == pytest.approx(0.25)
    assert metrics["uniqueLines"]["mean"] == 7 and metrics["lineDelta"]["mean"] == pytest.approx(-0.05)
    assert metrics["tokens"]["mean"] == 2800 and metrics["seconds"]["mean"] == 200.0
    assert metrics["endpoint"]["values"] == [pytest.approx(12 / 17)]
    first = jqa["generations"][0]
    assert first["genId"] == "jqa-bbbbbbbb-r1" and len(first["uncoveredEndpoints"]) == 5
    assert not [e for e in first["uncoveredEndpoints"] if "reservations" in e]
    assert {r["id"]: r["covered"] for r in first["oracleRules"]}["ORC-01"] is True
    assert {r["id"]: r["covered"] for r in first["oracleRules"]}["ORC-06"] is True
    assert {r["id"]: r["covered"] for r in first["oracleRules"]}["ORC-09"] is False
    # 판정: jqa 엔드포인트 평균 0.706 < 0.80 이라 불성립이지만 범위는 base와 분리돼 효과 있음
    verdict = document["verdict"]
    assert (verdict["generation"], verdict["effect"], verdict["label"]) == ("불성립", "효과 있음", "탐색적 관찰")


def test_req040_no_blackbox_leaves_deltas_empty(tmp_path):
    document = collect(make_compare_run(tmp_path, with_blackbox=False))
    jsonschema.validate(document, json.loads(SCHEMA.read_text()))
    assert document["blackbox"] is None
    assert document["arms"]["base"]["metrics"]["lineDelta"]["n"] == 0
    assert document["arms"]["base"]["metrics"]["uniqueLines"]["mean"] is None


def test_req040_missing_inputs_fail_clearly(tmp_path):
    run_dir = make_compare_run(tmp_path)
    (run_dir / "S08" / "coverage.json").unlink()
    with pytest.raises(compare.CompareError, match="S08/coverage.json"):
        collect(run_dir)


def test_req040_all_ontology_arms_skipped_is_undecidable(tmp_path):
    run_dir = make_compare_run(tmp_path)
    stage = json.loads((run_dir / "stages" / "S06.json").read_text())
    stage["arms"]["jqa"] = {"status": "skipped", "reason": "S03 건너뜀"}
    (run_dir / "stages" / "S06.json").write_text(json.dumps(stage))
    bdd = json.loads((run_dir / "S06" / "bdd-gen.json").read_text())
    bdd["generations"] = [g for g in bdd["generations"] if g["arm"] != "jqa"]
    (run_dir / "S06" / "bdd-gen.json").write_text(json.dumps(bdd))
    document = collect(run_dir)
    assert document["arms"]["jqa"]["status"] == "skipped" and document["arms"]["jqa"]["reason"] == "S03 건너뜀"
    assert (document["verdict"]["generation"], document["verdict"]["effect"]) == ("판정 불가", "판정 불가")


# --- 화면 ----------------------------------------------------------------------------------------
def test_req067_compare_html(tmp_path):
    run_dir = make_compare_run(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    page = compare.render_page(out, collect(run_dir))
    html = page.read_text()
    assert "<title>arm 비교 판정</title>" in html and len(re.search(r"<title>(.*?)</title>", html).group(1).split()) in (2, 3, 4)
    assert "탐색적 관찰" in html
    # arm x 지표 표: 모든 arm 열(skipped 표기)과 17개 지표 행
    header = re.search(r'<table id="compare-table">.*?</thead>', html, re.S).group(0)
    assert "base (n=1/2)" in header and "jqa (n=1/2)" in header and "owl (skipped)" in header
    rows = re.findall(r'<tr data-metric="(\w+)"', html)
    assert {"scenarios", "compile", "undefined", "passed", "endpoint", "line", "branch", "lineDelta", "branchDelta", "uniqueLines",
            "oracle", "focusLine", "focusEndpoint", "focusOracle", "tokens", "seconds"} <= set(rows)
    assert "29.4%" in html and "70.6%" in html  # 엔드포인트 평균 5/17, 12/17
    assert 'data-skipped-arm="owl"' in html and "S05(OWL 온톨로지) 건너뜀" in html
    assert 'data-failed-generation="jqa-bbbbbbbb-r2"' in html
    # generation별 점 그래프(인라인 SVG): 지표 4개 x 측정된 generation 2개
    assert html.count("<svg") == 4 and len(re.findall(r"<circle ", html)) == 8
    # 판정 결과와 반복 횟수
    assert 'data-verdict="불성립"' in html and 'data-verdict="효과 있음"' in html
    assert re.search(r'id="reps">2</b>', html)
    # 한계 서술: OWL 파생성, 모델 사전 지식, 귀속 한계, 작은 표본
    limitations = re.search(r'<ul id="limitations">(.*?)</ul>', html, re.S).group(1)
    for needle in ("OWL", "사전 지식", "귀속", "표본"):
        assert needle in limitations, needle
    # 외부 자원 없이 열린다(인라인 SVG, 같은 디렉터리 CSS만)
    assert not re.search(r'(src|href)="https?://', html)
    assert "clock-shift" not in html


def test_req060_clock_shift_warning_shown_on_compare_html(tmp_path):
    """clockShift는 run.json(clockShift 또는 startedAt/finishedAt)만으로 정해진다. 경계: 자정 직전/정각/직후."""
    cases = [  # (finishedAt, 경고 여부): Asia/Seoul 자정 = 15:00:00Z, 시작은 23:59 KST
        ("2026-11-19T14:59:59Z", False),  # 자정 직전
        ("2026-11-19T15:00:00Z", True),   # 정확히 자정
        ("2026-11-19T15:00:01Z", True),   # 자정 직후
    ]
    for index, (finished, expected) in enumerate(cases):
        base = tmp_path / f"c{index}"
        base.mkdir()
        run_dir = make_compare_run(base, started="2026-11-19T14:59:00Z", finished=finished)
        document = collect(run_dir)
        assert document["clock"]["clockShift"] is expected, finished
        out = tmp_path / f"html{index}"
        out.mkdir()
        html = compare.render_page(out, document).read_text()
        assert ('id="clock-shift"' in html) is expected
        if expected:
            assert "Asia/Seoul" in html and "시계 경계 경고" in html
    # run.json에 clockShift=true가 기록돼 있으면 경고한다
    flag_base = tmp_path / "flag"
    flag_base.mkdir()
    assert collect(make_compare_run(flag_base, clock_shift=True))["clock"]["clockShift"] is True
    # 종료 시각이 아직 없으면(S12는 S13 앞) 현재 시각과 비교하지 않는다: 아주 오래전 시작이어도 false이고, 다시 렌더링해도 같다
    open_base = tmp_path / "open"
    open_base.mkdir()
    old = make_compare_run(open_base, started="2020-01-01T00:00:00Z")
    first = collect(old)
    assert first["clock"]["clockShift"] is False and collect(old)["clock"] == first["clock"]


# --- 단계 스크립트와 사이트 --------------------------------------------------------------------------
def _stage_env(run_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(TD_ROOT=str(REPO_ROOT), TD_RUN_DIR=str(run_dir), TD_RUN_ID=run_dir.name, TD_WORK_DIR=str(run_dir.parent),
               TD_SUT_FILE=str(SUT_FILE), TD_SITE_PREFIX="_test/s12/", TD_NOW="2026-11-19T02:00:00Z")
    return env


def _run_s12(run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(S12_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True,
                          env=_stage_env(run_dir), timeout=120)


def test_req040_s12_stage_site_and_run_json(tmp_path):
    from td.site import pages
    run_dir = make_compare_run(tmp_path)
    done = _run_s12(run_dir)
    assert done.returncode == 0, done.stderr
    stage = json.loads((run_dir / "stages" / "S12.json").read_text())
    assert stage["status"] == "passed" and Path(stage["outputs"]["compare"]) == run_dir / "S12" / "compare"
    document = json.loads((run_dir / "S12" / "compare" / "compare.json").read_text())
    jsonschema.validate(document, json.loads(SCHEMA.read_text()))
    summary = json.loads((run_dir / "run.json").read_text())["kpis"]["compare"]
    assert summary["generation"] == "불성립" and summary["effect"] == "효과 있음" and summary["label"] == "탐색적 관찰"
    assert summary["arms"] == {"base": "ok", "jqa": "ok", "owl": "skipped"} and summary["endpointDenominator"] == 17
    # 사이트: compare/ 디렉터리와 run 페이지 링크, 공통 CSS로 다시 렌더링
    site = tmp_path / "site"
    index = pages.render_run(run_dir, site)
    html = (site / "compare" / "compare.html").read_text()
    assert "탐색적 관찰" in html and "static/site.css" in html and not (site / "compare" / "site.css").exists()
    assert 'href="compare/compare.html"' in index.read_text()


def test_req040_s12_fails_without_coverage_and_records_reason(tmp_path):
    run_dir = make_compare_run(tmp_path)
    (run_dir / "S08" / "coverage.json").unlink()
    done = _run_s12(run_dir)
    assert done.returncode == 1
    stage = json.loads((run_dir / "stages" / "S12.json").read_text())
    assert stage["status"] == "failed" and "coverage.json" in stage["reason"]


# --- 오라클(REQ-041) -----------------------------------------------------------------------------
def _pilot_runs() -> list[Path]:
    runs = sorted((REPO_ROOT / "work" / "runs").glob("*/S08/coverage.json"))
    return [path.parents[1] for path in runs if (path.parents[1] / "S03" / "ontology-jqa.json").is_file()
            and (path.parents[1] / "S06" / "bdd-gen.json").is_file()]


def _pilot_run() -> Path:
    runs = _pilot_runs()
    if not runs:
        pytest.fail("파일럿 run(work/runs/*/ S03, S06, S08)이 없다: M2 실행 산출물이 필요하다", pytrace=False)
    return runs[-1]


def _normalize(text: str) -> str:
    return " ".join(bundle.normalize.normalize_leaf(text))


def test_req041_oracle_rules_have_substance():
    data = yaml.safe_load(ORACLE_FILE.read_text())
    rules = data["rules"]
    assert len(rules) >= 7 and data["commit"] == COMMIT
    assert len({r["id"] for r in rules}) == len(rules)
    for rule in rules:
        assert set(rule) == {"id", "class", "line", "description"}, rule
        assert isinstance(rule["line"], int) and rule["class"].startswith("org.springframework.samples.petclinic.")
        assert len(rule["description"].split()) >= 6
    # 설계 §6.12의 최소 규칙: 정원 2, 1~30박, 객실 100~499, 동물 1~4, 체크인 미래, 48시간 취소, 요율별 보증금
    # (각 규칙을 소스에서 확인한 라인에 둔다)
    wanted = {49: "nights", 52: "room", 55: "animals", 70: "check-in", 73: "deposit", 76: "capacity", 159: "48 hours"}
    source = (REPO_ROOT / "work" / "suts" / "petclinic" / "src" / "src" / "main" / "java" / "org" / "springframework" / "samples" /
              "petclinic" / "boarding" / "ReservationService.java").read_text().splitlines()
    assert subprocess.run(["git", "-C", str(REPO_ROOT / "work" / "suts" / "petclinic" / "src"), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip() == COMMIT
    by_line = {r["line"]: r for r in rules}
    probes = {49: "nights()", 52: "roomNumber()", 55: "animalCount()", 70: "checkInDate()", 73: "depositAmount()",
              76: "ROOM_CAPACITY", 159: "plusHours(48)"}
    for line, probe in probes.items():
        assert line in by_line, f"규칙이 없다: {wanted[line]}"
        assert probe in source[line - 1], f"{line}행이 {wanted[line]} 규칙의 조건이 아니다: {source[line - 1].strip()}"


def test_req041_oracle_lines_are_branch_probes_in_jacoco_xml():
    """각 규칙의 (class, line)은 고정 커밋의 jacoco XML에서 분기 probe(cb+mb > 0)가 있는 라인이다."""
    run_dir = _pilot_run()
    xml = run_dir / "S08" / "merged" / "aggregate.xml"
    assert xml.is_file(), xml
    commit = json.loads((run_dir / "S08" / "merged" / "manifest.json").read_text())["commit"]
    assert commit == COMMIT
    facts = compare.XmlFacts(xml)
    for rule in compare.load_oracle(ORACLE_FILE):
        assert facts.has_branch_probe(rule), f"{rule['id']}: {rule['class']}:{rule['line']}는 분기 probe 라인이 아니다"


def test_req041_oracle_descriptions_absent_from_preserved_bundles():
    """E2E: 보존된 실제 번들(S06/bundles/<arm>)에 정규화한 description이 부분 문자열로 없다."""
    run_dir = _pilot_run()
    descriptions = bundle.load_oracle_descriptions(ORACLE_FILE)
    assert len(descriptions) >= 7
    bundles = sorted((run_dir / "S06" / "bundles").glob("*"))
    assert bundles, "보존된 번들이 없다"
    for path in bundles:
        built = bundle.Bundle(path=path, input_hash="", arm=path.name, extra_origins={})
        hits = bundle.check_content(built, REPO_ROOT / "work" / "suts" / "petclinic" / "src", oracle=descriptions)
        assert not [v for v in hits if "oracle" in v.detail], f"{path.name}: {hits}"
        text = " ".join(_normalize(p.read_text(errors="replace")) for p in path.rglob("*") if p.is_file())
        assert not [d for d in descriptions if _normalize(d) in text]


def test_req041_oracle_rejected_in_bundle_cli(tmp_path):
    """주입된 파일에 description이 있으면 번들 검사가 LLM 호출 전에 비-0으로 끝난다(oracle.yaml을 --oracle로 받는다)."""
    from test_isolation import FIXTURE_SUT, make_run_dir
    run_dir = make_run_dir(tmp_path, "run-oracle")
    description = yaml.safe_load(ORACLE_FILE.read_text())["rules"][0]["description"]
    leak = tmp_path / "leak.txt"
    leak.write_text(f"hint for the model\n{description}\nmore text\n")
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "site-gen")}
    cmd = [sys.executable, "-m", "td.bundle", "build", "--arm", "base", "--run-dir", str(run_dir), "--out", str(tmp_path / "out"),
           "--sut-src", str(FIXTURE_SUT), "--oracle", str(ORACLE_FILE)]
    clean = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert clean.returncode == 0, clean.stderr
    injected = subprocess.run(cmd, capture_output=True, text=True,
                              env={**env, "TD_BUNDLE_EXTRA": str(leak), "TD_SITE_PREFIX": "_test/unit/"})
    assert injected.returncode == 1 and "oracle" in injected.stderr


def test_req041_fake_claude_stdin_has_no_oracle_text(fake_claude, tmp_path):
    """Int: S06이 실제 suts/petclinic/sut.yaml(옆의 oracle.yaml 포함)로 도는 동안 claude stdin에 description이 없다."""
    from test_bdd_gen import S06Env, VALID
    env = S06Env(tmp_path)
    fake_claude.respond(VALID)
    run_dir = env.new_run(arms=("base",))
    done = env.run(run_dir)
    assert done.returncode == 0, done.stderr + done.stdout
    assert fake_claude.calls, "claude 호출이 없었다"
    descriptions = [_normalize(d) for d in bundle.load_oracle_descriptions(ORACLE_FILE)]
    for call in fake_claude.calls:
        stdin = _normalize(call.stdin)
        assert not [d for d in descriptions if d in stdin]
    # S06이 oracle.yaml을 번들 검사에 실제로 넘겼는지: 번들 빌드 로그 대신, 같은 경로 규약을 코드로 확인한다
    from td import bddgen
    assert 'oracle.yaml' in Path(bddgen.__file__).read_text()


# --- 실제 파일럿 run --------------------------------------------------------------------------------
def test_req040_compare_json_on_pilot_run():
    run_dir = _pilot_run()
    document = collect(run_dir)
    jsonschema.validate(document, json.loads(SCHEMA.read_text()))
    assert document["endpoints"]["denominator"] == 17 == document["endpoints"]["expected"]
    measured = {name: entry for name, entry in document["arms"].items() if entry["status"] == "ok"}
    assert "base" in measured and "jqa" in measured
    for entry in measured.values():
        metrics = entry["metrics"]
        assert 0.0 <= metrics["endpoint"]["mean"] <= 1.0 and 0.0 <= metrics["oracle"]["mean"] <= 1.0
        assert metrics["scenarios"]["mean"] > 0 and metrics["focusLine"]["mean"] is not None
    assert document["arms"]["owl"]["status"] == "skipped" and document["arms"]["owl"]["reason"]
    assert document["verdict"]["label"] == "탐색적 관찰"


# --- 리뷰 보완: 연결, 경고, 라벨 ---------------------------------------------------------------------
def test_req041_s06_blocks_oracle_text_before_any_claude_call(fake_claude, tmp_path):
    """E2E 연결: 주입 파일에 oracle description이 있으면 S06 arm이 번들 조립에서 실패하고 claude는 한 번도 호출되지 않는다."""
    from test_bdd_gen import S06Env, VALID
    description = yaml.safe_load(ORACLE_FILE.read_text())["rules"][1]["description"]
    leak = tmp_path / "leak.txt"
    leak.write_text(f"unrelated line one\n{description}\nunrelated line two\n")  # 줄 사이에 끼워 정규화로 일치시킨다
    env = S06Env(tmp_path)
    fake_claude.respond(VALID)
    run_dir = env.new_run(arms=("base",))
    done = env.run(run_dir, TD_BUNDLE_EXTRA=str(leak))
    stage = env.stage(run_dir)
    assert stage["status"] == "failed", (stage, done.stderr)
    assert stage["arms"]["base"]["status"] == "failed" and "oracle" in stage["arms"]["base"]["reason"]
    assert fake_claude.calls == []


def test_req041_build_bundle_passes_oracle_yaml_of_sut_dir(tmp_path, monkeypatch):
    """단위: bddgen.build_bundle이 sut.yaml 옆 oracle.yaml을 --oracle로 넘기고, 없으면 넘기지 않는다."""
    from td import bddgen, proc
    seen = []

    def fake_run(timeout, argv, **kwargs):
        seen.append(list(argv))
        return 1  # 번들 검사 실패로 끝내 BddGenError를 받는다

    monkeypatch.setattr(proc, "run_with_timeout", fake_run)
    run_dir = tmp_path / "run"
    (run_dir / "S06").mkdir(parents=True)
    sut_dir = tmp_path / "sut"
    sut_dir.mkdir()
    (sut_dir / "sut.yaml").write_text("name: x\n")
    for with_oracle in (False, True):
        if with_oracle:
            (sut_dir / "oracle.yaml").write_text("rules: []\n")
        with pytest.raises(bddgen.BddGenError):
            bddgen.build_bundle("base", run_dir, tmp_path / "src", sut_dir / "sut.yaml")
    assert "--oracle" not in seen[0]
    assert seen[1][seen[1].index("--oracle") + 1] == str(sut_dir / "oracle.yaml")


def test_req041_empty_oracle_file_is_an_error(tmp_path):
    empty = tmp_path / "oracle.yaml"
    empty.write_text("rules: []\n")
    with pytest.raises(bundle.BundleError, match="description"):
        bundle.load_oracle_descriptions(empty)
    empty.write_text("[]\n")
    empty.rename(tmp_path / "o.json")
    with pytest.raises(bundle.BundleError):
        bundle.load_oracle_descriptions(tmp_path / "o.json")


def test_req040_null_blackbox_kpis_are_schema_valid(tmp_path):
    run_dir = make_compare_run(tmp_path)
    coverage = json.loads((run_dir / "S08" / "coverage.json").read_text())
    coverage["suites"]["blackbox"]["kpis"] = {"line": None}
    coverage["suites"]["e2e-base-aaaaaaaa-r1"]["kpis"] = {"line": 0.2, "branch": None}
    (run_dir / "S08" / "coverage.json").write_text(json.dumps(coverage))
    document = collect(run_dir)
    jsonschema.validate(document, json.loads(SCHEMA.read_text()))
    assert document["blackbox"] == {"line": None, "branch": None}
    base = document["arms"]["base"]["metrics"]
    assert base["lineDelta"]["n"] == 0 and base["branchDelta"]["n"] == 0
    out = tmp_path / "out"
    out.mkdir()
    compare.render_page(out, document)


def test_req040_endpoint_warnings_in_json_and_page(tmp_path):
    run_dir = make_compare_run(tmp_path)
    ontology = json.loads((run_dir / "S03" / "ontology-jqa.json").read_text())
    ontology["nodes"].append({"id": "endpoint:GET /api/ghost", "kind": "Endpoint", "label": "g",
                              "props": {"method": "GET", "path": "/api/ghost", "handler": "x.Ghost#gone", "view": False}})
    (run_dir / "S03" / "ontology-jqa.json").write_text(json.dumps(ontology))
    document = collect(run_dir)
    jsonschema.validate(document, json.loads(SCHEMA.read_text()))
    assert document["endpoints"]["denominator"] == 18
    joined = " ".join(document["warnings"])
    assert "18" in joined and "17" in joined and "x.Ghost#gone" in joined
    out = tmp_path / "out"
    out.mkdir()
    html = compare.render_page(out, document).read_text()
    assert 'id="compare-warnings"' in html and "x.Ghost#gone" in html
    clean_base = tmp_path / "clean"
    clean_base.mkdir()
    clean = collect(make_compare_run(clean_base))
    assert clean["warnings"] == []


def test_req067_focus_labels_and_theme_tokens(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    html = compare.render_page(out, collect(make_compare_run(tmp_path))).read_text()
    assert "Reservation 범위" not in html
    assert "Focus 범위 (org.springframework.samples.petclinic.boarding.*) 라인" in html
    # SVG 색은 사이트 테마 토큰이다(하드코딩 색 없음)
    assert "var(--arm-jqa)" in html and "#0969da" not in html
    css = (REPO_ROOT / "site-gen" / "td" / "site" / "static" / "site.css").read_text()
    assert css.count("--arm-jqa") >= 3  # 라이트, 어두운 모드(OS), data-theme=dark
