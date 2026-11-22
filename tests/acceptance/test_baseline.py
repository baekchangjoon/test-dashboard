"""기준 run과 두 번째 run의 E2E 검사(Task 25). 모두 @pytest.mark.baseline이다.

증거는 `tests/acceptance/run_baseline.py`가 쓴 `work/acceptance-session.json`(fixture `baseline_run`, `second_run`)이다.
세션 파일이 없으면 conftest가 이 테스트들을 실패시킨다(skip이 아니다). 판정은 run 디렉터리 산출물, 사람이 검토한 기대 목록,
실행 전후 Docker 목록, 게시된 URL과 S3 객체로 한다. 기존 Int/E2E-inj 테스트의 판정 함수를 다시 쓸 수 있으면 그대로 부른다.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import jsonschema
import pytest
import yaml
from playwright.sync_api import expect

import helpers
from conftest import token_rows
from dashboard_fixtures import open_page
from td import bbtg, bundle, dashboard_config, testid

pytestmark = pytest.mark.baseline

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "site-gen" / "td" / "schemas"
SUT_DIR = REPO_ROOT / "suts" / "petclinic"
SUT_SRC = REPO_ROOT / "work" / "suts" / "petclinic" / "src"
SUT_YAML = yaml.safe_load((SUT_DIR / "sut.yaml").read_text())
EXPECTED_TESTS = yaml.safe_load((SUT_DIR / "expected-tests.yaml").read_text())
EXPECTED_ENDPOINTS = yaml.safe_load((SUT_DIR / "expected-endpoints.yaml").read_text())
GEN_ID_RE = re.compile(r"^(base|jqa|owl)-[0-9a-f]{8}-r[1-9](-g[0-9]+)?$")
ARMS = ("base", "jqa", "owl")
STATUSES = {"passed", "failed", "degraded", "skipped"}
# 이 작업 전에 게시된 run(옛 화면 그대로 남는다, REQ-139)
OLD_RUN_ID = "20261120-131022Z-b6f9393-manual-036c288d"
# tests/fixtures/reports/README.md "확인한 선택자"의 값
TIA_GUIDE_SELECTOR = "#view details.tab-guide"
TIA_CHANGED_FILE_SELECTOR = "#s-list .scrow:not(.all)"


def _runs(baseline_run, second_run):
    return (("baseline", baseline_run), ("second", second_run))


def _json(path: Path):
    return json.loads(path.read_text())


def _generations(run) -> dict[str, dict]:
    return run.stage("S06")["generations"]


def _executed_generations(run) -> dict[str, dict]:
    return run.stage("S07").get("generations") or {}


# --- A. 실행 골격 -------------------------------------------------------------------------------
def test_req002_baseline_all_stages_recorded(baseline_run, second_run):
    for label, run in _runs(baseline_run, second_run):
        assert run.returncode == 0, f"{label}: run-all 종료 코드 {run.returncode} (로그 {run.record['log']})"
        stages = run.stages()
        assert sorted(stages) == [f"S{i:02d}" for i in range(14)], label
        for stage_id, stage in stages.items():
            assert stage["id"] == stage_id and stage["status"] in STATUSES, (label, stage_id, stage["status"])
            if stage["status"] != "passed":
                assert str(stage.get("reason") or "").strip(), (label, stage_id, stage)
        run_stages = run.run_json["stages"]
        assert sorted(run_stages) == sorted(stages)
        for stage_id, status in run_stages.items():
            allowed = STATUSES | ({"publishing"} if stage_id == "S13" else set())
            assert status in allowed, (label, stage_id, status)
        # 기준 run은 실패 단계 없이 끝난다(종료 코드 0과 같은 뜻을 단계 기록으로 다시 확인)
        assert not [s for s, st in stages.items() if st["status"] == "failed"], label


def test_req006_baseline_trigger_placeholders(baseline_run, second_run):
    for label, run in _runs(baseline_run, second_run):
        data = run.run_json
        assert data["trigger"] == "manual" and "pr" in data and data["pr"] is None, label
        assert re.fullmatch(r"\d{8}-\d{6}Z-[0-9a-f]{7}-manual-[0-9a-f]{8}", run.run_id), run.run_id


def test_req060_baseline_time_metadata(baseline_run, second_run):
    import datetime as dt
    from zoneinfo import ZoneInfo
    for label, run in _runs(baseline_run, second_run):
        data = run.run_json
        started = dt.datetime.strptime(data["startedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        finished = dt.datetime.strptime(data["finishedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        assert started < finished, label
        assert data["tz"] == "Asia/Seoul" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["sutDate"]), label
        seoul = ZoneInfo("Asia/Seoul")
        assert data["clockShift"] is (started.astimezone(seoul).date() != finished.astimezone(seoul).date()), label
        html = (run.run_dir / "S12" / "compare" / "compare.html").read_text()
        assert ("clock-shift" in html) is data["clockShift"], label


# --- B. 자원 정리 --------------------------------------------------------------------------------
def test_req009_baseline_no_docker_leak(baseline_run, second_run):
    """라벨과 무관한 외부 관측: run 전후 컨테이너·네트워크·볼륨 ID 목록에서 새로 생겨 남은 것이 0개다."""
    for label, run in _runs(baseline_run, second_run):
        before, after = run.record["dockerBefore"], run.record["dockerAfter"]
        for kind in ("containers", "networks", "volumes"):
            assert before[kind] is not None and sorted(set(after[kind]) - set(before[kind])) == [], (label, kind)
        assert helpers.find_leaked_resources(f"td-{run.run_id}") == {}, label


def test_req011_baseline_pids_worktrees_daemons(baseline_run, second_run):
    for label, run in _runs(baseline_run, second_run):
        pids = helpers.run_pids(run.run_dir)
        assert not [name for name, pid in pids.items() if helpers.pid_alive(pid)], (label, pids)
        before = {(d["pid"], d["lstart"]) for d in run.record["gradleDaemonsBefore"]}
        new_alive = [d for d in run.record["gradleDaemonsAfter"] if (d["pid"], d["lstart"]) not in before]
        assert new_alive == [], (label, new_alive)
    worktrees = subprocess.run(["git", "-C", str(SUT_SRC), "worktree", "list", "--porcelain"], capture_output=True,
                               text=True, check=True).stdout
    assert worktrees.count("worktree ") == 1, worktrees  # 주 체크아웃만 남는다(TIA base worktree 없음)
    for _, run in _runs(baseline_run, second_run):
        assert not (run.run_dir / "S10" / "base").exists()


# --- C. 블랙박스 IT와 bbtg -------------------------------------------------------------------------
def test_req012_baseline_blackbox_artifacts(baseline_run):
    root = baseline_run.run_dir / "S01" / "blackbox"
    stage = baseline_run.stage("S01")
    assert stage["status"] == "passed", stage
    exec_files = [p for p in (root / "exec").glob("*.exec") if p.name != "aggregate.exec"]
    assert (root / "exec" / "aggregate.exec").is_file()
    assert len(exec_files) == EXPECTED_TESTS["expected_exec"]
    assert all((p.with_suffix(".json")).is_file() for p in exec_files)
    assert list((root / "junit").glob("*.xml"))


def test_req008_baseline_exec_count_gate(baseline_run):
    stage = baseline_run.stage("S01")
    total, no_attr = EXPECTED_TESTS["blackbox"]["total"], sorted(EXPECTED_TESTS["no_attribution"]["tests"])
    cases = []
    for xml in (baseline_run.run_dir / "S01" / "blackbox" / "junit").glob("*.xml"):
        for case in ET.parse(xml).getroot().iter("testcase"):
            if case.find("skipped") is None:
                cases.append(case)
    assert len(cases) == total == stage["tcCount"]
    assert stage["execCount"] == total - len(no_attr) and sorted(stage["missingExec"]) == no_attr


def test_req013_baseline_bbtg_manifest(baseline_run):
    manifest = _json(baseline_run.run_dir / "S02" / "bbtg" / "manifest.json")
    calls = manifest["calls"]
    by_skill: dict[str, list[dict]] = {}
    for call in calls:
        by_skill.setdefault(call["skill"], []).append(call)
    for skill in ("inspect-stack", "scan-test-assets", "inspect-auth", "derive-test-data"):
        assert len(by_skill.get(skill, [])) == 1, skill
    controllers = len(EXPECTED_ENDPOINTS["controllers"])
    assert len(by_skill["dependency-map"]) == len(by_skill["find-external-calls"]) == controllers
    assert len(by_skill["plan-tests"]) >= 1
    assert SUT_YAML["runtime"]["ddl"] in " ".join(map(str, by_skill["derive-test-data"][0]["argv"]))
    for call in calls:  # 인자, 종료 코드, 산출물 경로
        assert call["argv"] and call["rc"] == 0 and (call.get("stdout") or call.get("artifacts")), call
    assert not (SUT_SRC / ".bbtg").exists()
    # S02 동안 claude 호출 0: shim 기록 중 S02 구간에 든 것이 없다
    s02 = baseline_run.stage("S02")
    inside = [c for c in helpers.claude_call_log(baseline_run.run_dir) if s02["startedAt"] <= c["ts"] <= s02["finishedAt"]]
    assert inside == []


# --- D. 온톨로지 -------------------------------------------------------------------------------------
def test_req014_baseline_endpoints_match_expected(baseline_run):
    from test_ontology import S03Run, test_req014_endpoints_match_expected
    test_req014_endpoints_match_expected(S03Run(0, "", "", baseline_run.run_dir))


def test_req015_baseline_schema_and_kinds(baseline_run):
    schema = _json(SCHEMAS / "ontology.schema.json")
    commit = baseline_run.run_json["commit"]
    jqa = _json(baseline_run.run_dir / "S03" / "ontology-jqa.json")
    owl = _json(baseline_run.run_dir / "S05" / "ontology-owl.json")
    for doc in (jqa, owl):
        jsonschema.validate(doc, schema)
        assert doc["meta"]["commit"] == commit
    assert {"Endpoint", "Service", "Repository", "Entity", "Exception"} <= {n["kind"] for n in jqa["nodes"]}


@pytest.fixture(scope="module")
def browser(playwright_instance):
    instance = playwright_instance.chromium.launch()
    yield instance
    instance.close()


def test_req016_baseline_offline_render(baseline_run, browser):
    from test_ontology import _open_offline
    for name, source in (("jqa", "S03/ontology-jqa.json"), ("owl", "S05/ontology-owl.json")):
        nodes = _json(baseline_run.run_dir / source)["nodes"]
        context, page, blocked, console_errors, page_errors = _open_offline(
            browser, baseline_run.run_dir / "S04" / "ontology" / f"{name}.html")
        try:
            assert page.evaluate("window.__td_cy.nodes().length") == len(nodes), name
            assert blocked == [] and console_errors == [] and page_errors == [], (name, blocked, console_errors, page_errors)
        finally:
            context.close()


def test_req018_baseline_owl_correspondence(baseline_run):
    from test_ontology import assert_owl_correspondence
    assert baseline_run.stage("S05")["status"] == "passed"
    assert_owl_correspondence(baseline_run.run_dir / "S05" / "ontology-owl.ttl",
                              _json(baseline_run.run_dir / "S03" / "ontology-jqa.json"))


# --- E. 생성 입력 오염 차단 -------------------------------------------------------------------------
def _preserved_bundles(run) -> dict[str, Path]:
    bundles = {arm: run.run_dir / "S06" / "bundles" / arm for arm in ARMS}
    bundles["owlgen"] = run.run_dir / "S05" / "bundle"
    return bundles


def _allowed(arm: str, rel: str) -> bool:
    """사람이 정한 허용 목록(구현의 허용 표를 쓰지 않는다)."""
    if rel == "bbtg/manifest.json" or rel in {f"bbtg/{skill}.json" for skill in bbtg.SKILLS}:
        return True
    extra = {"base": {"harness/CONTRACT.md"}, "jqa": {"harness/CONTRACT.md", "ontology/ontology-jqa.json"},
             "owl": {"harness/CONTRACT.md", "ontology/ontology-owl.ttl"}, "owlgen": {"ontology/skeleton.ttl"}}[arm]
    return rel in extra


def test_req019_baseline_bundle_paths(baseline_run, second_run):
    for label, run in _runs(baseline_run, second_run):
        for arm, path in _preserved_bundles(run).items():
            # 검사 서명(.td-bundle-verified.json)은 번들 내용이 아니라 llm.sh가 대조하고 호출 전에 지우는 표식이다
            assert (path / bundle.STAMP_NAME).is_file(), (label, arm)
            files = sorted(p.relative_to(path).as_posix() for p in path.rglob("*")
                           if p.is_file() and p.name != bundle.STAMP_NAME)
            assert files, (label, arm)
            assert [f for f in files if not _allowed(arm, f)] == [], (label, arm)
            assert "bbtg/manifest.json" in files, (label, arm)


def test_req020_baseline_bundle_content(baseline_run):
    oracle = bundle.load_oracle_descriptions(SUT_DIR / "oracle.yaml")
    for arm, path in _preserved_bundles(baseline_run).items():
        built = bundle.Bundle(path=path, input_hash="", arm=arm if arm != "owlgen" else "owlgen", extra_origins={})
        assert bundle.check_content(built, SUT_SRC, oracle=oracle) == [], arm


def test_req021_baseline_bbtg_allow_schema(baseline_run):
    from jsonschema import Draft202012Validator
    clean = baseline_run.run_dir / "S02" / "bbtg" / "clean"
    allow_dir = REPO_ROOT / "site-gen" / "td" / "bbtg_allow"
    for skill in bbtg.SKILLS:
        document = _json(clean / f"{skill}.json")
        errors = list(Draft202012Validator(_json(allow_dir / f"{skill}.schema.json")).iter_errors(document))
        assert errors == [], (skill, errors[:1])
    sanitize = _json(baseline_run.run_dir / "S02" / "bbtg" / "manifest.json")["sanitize"]
    meta = _json(baseline_run.run_dir / "S06" / "bdd-gen.json")
    assert meta["strippedFields"] == sanitize["strippedFields"]
    assert "inspect-auth:interceptor_sources[].source" in meta["strippedFields"]
    assert set(sanitize["strippedFields"]) == set(sanitize["removedCounts"])
    assert all(count > 0 for count in sanitize["removedCounts"].values())


def test_req022_baseline_llm_calls_isolated(baseline_run, second_run):
    """shim이 남긴 실제 claude 호출 기록(이 작업 공간의 모든 run): 격리 플래그가 모두 있고 cwd가 번들 임시 디렉터리다."""
    logs = sorted((REPO_ROOT / "work" / "runs").glob("*/llm-calls.jsonl"))
    calls = [call for log in logs for call in helpers.claude_call_log(log.parent)]
    assert calls, "shim 호출 기록이 하나도 없다"
    for call in calls:
        argv = call["argv"]
        for flag in ("-p", "--tools", "--strict-mcp-config", "--mcp-config", "--setting-sources", "--system-prompt",
                     "--output-format", "--model"):
            assert flag in argv, (flag, call)
        cwd = Path(call["cwd"])
        assert not cwd.is_relative_to(REPO_ROOT) and not cwd.is_relative_to(SUT_SRC), call
    generation_calls = [c for c in calls if Path(c["cwd"]).name == "cwd" and Path(c["cwd"]).parent.name.startswith("td-llm.")]
    assert generation_calls, "번들 임시 디렉터리에서 한 생성 호출이 없다"


def test_req023_arms_and_reps(baseline_run):
    data = baseline_run.run_json
    reps = data["options"]["reps"]
    assert reps == 3 and data["options"]["arms"] == list(ARMS)
    generations = data["arms"]["generations"]
    assert sorted(generations) == sorted(ARMS)
    for arm in ARMS:
        ids = generations[arm]
        assert len(ids) == reps and all(GEN_ID_RE.match(i) and i.startswith(f"{arm}-") for i in ids), (arm, ids)
        assert sorted(int(re.search(r"-r(\d)", i).group(1)) for i in ids) == [1, 2, 3]
        for gen_id in ids:
            assert (REPO_ROOT / "e2e" / "generated" / "petclinic" / arm / gen_id / "_COMPLETE").is_file(), gen_id
    assert re.search(r'id="reps">3</b>', (baseline_run.run_dir / "S12" / "compare" / "compare.html").read_text())


def test_req061_baseline_gen_metadata_schema(baseline_run, second_run):
    for label, run in _runs(baseline_run, second_run):
        bdd = _json(run.run_dir / "S06" / "bdd-gen.json")
        owl = _json(run.run_dir / "S05" / "owl-gen.json")
        jsonschema.validate(bdd, _json(SCHEMAS / "bdd-gen.schema.json"))
        jsonschema.validate(owl, _json(SCHEMAS / "owl-gen.schema.json"))
        assert len(bdd["generations"]) == 9, label
        for record in [*bdd["generations"], owl]:
            for key in ("inputHash", "promptHash", "model", "cliVersion", "flags", "repairs", "tokens", "seconds"):
                assert record.get(key) is not None, (label, key)
            assert record["tokens"]["in"] > 0 and record["tokens"]["out"] > 0, (label, record.get("genId"))
        assert owl["strippedFields"] == bdd["strippedFields"]


def test_req075_baseline_second_run_reuses_snapshots(baseline_run, second_run):
    assert second_run.record["llmCalls"] == 0 == len(helpers.claude_call_log(second_run.run_dir))
    first, again = _generations(baseline_run), _generations(second_run)
    assert sorted(first) == sorted(again) and len(again) == 9
    assert all(g["reused"] is True for g in again.values())
    assert second_run.stage("S05")["owl"]["reused"] is True
    assert second_run.stage("S05")["owl"]["inputHash"] == baseline_run.stage("S05")["owl"]["inputHash"]
    assert second_run.run_json["inputs"] == baseline_run.run_json["inputs"]


# --- F. E2E 실행 ------------------------------------------------------------------------------------
def _feature_files(gen_dir: Path) -> list[Path]:
    return sorted(gen_dir.glob("features/**/*.feature"))


def test_req028_baseline_scenario_conservation(baseline_run):
    coverage = _json(baseline_run.run_dir / "S08" / "coverage.json")
    executed = _executed_generations(baseline_run)
    assert len(executed) == 9
    banned = re.compile(r"@ignore|@Disabled|@wip", re.IGNORECASE)
    for gen_id, gen in _generations(baseline_run).items():
        gen_dir = Path(gen["dir"])
        out = baseline_run.run_dir / "S07" / gen_id
        pickles = sum(len(testid.pickles(p.read_text())) for p in _feature_files(gen_dir))
        lines = [json.loads(line) for line in (out / "scenario-results.json").read_text().splitlines() if line]
        suite = coverage["suites"][f"e2e-{gen_id}"]
        assert pickles == len(lines) == suite["tcCount"] == len(suite["tcs"]), gen_id
        positive = [l for l in lines if l["requests"] > 0]
        exec_files = [p for p in (out / "exec").glob("*.exec") if p.name != "aggregate.exec"]
        assert len(positive) == len(exec_files), gen_id
        sources = [*_feature_files(gen_dir), *gen_dir.glob("glue/**/*.java")]
        assert not [p.name for p in sources if banned.search(p.read_text())], gen_id


def test_req029_baseline_undefined_ratio(baseline_run):
    for gen_id, gen in _generations(baseline_run).items():
        out = baseline_run.run_dir / "S07" / gen_id
        summary = _json(out / "summary.json")
        dry = _json(out / "dryrun.json")
        elements = [e for feature in dry for e in feature.get("elements", []) if e["type"] != "background"]
        undefined = [e for e in elements if any(s["result"]["status"] == "undefined" for s in e.get("steps", []))]
        excluded = _json(out / "compile-excluded.json")["features"]
        uncompilable = sum(len(testid.pickles((Path(gen["dir"]) / f).read_text())) for f in excluded)
        total = len(elements) + uncompilable
        assert total > 0, gen_id
        assert summary["undefinedRatio"] == pytest.approx(len(undefined) / total), gen_id


def test_req062_baseline_cucumber_reports(baseline_run):
    site = baseline_run.run_dir / "site"
    run_page = (site / "index.html").read_text()
    for gen_id in _executed_generations(baseline_run):
        page = site / "cucumber" / gen_id / "index.html"
        assert page.is_file() and "<html" in page.read_text().lower(), gen_id
        assert f'href="cucumber/{gen_id}/index.html"' in run_page, gen_id


# --- G. 커버리지 ---------------------------------------------------------------------------------------
def _counter_ratio(xml_path: Path, kind: str) -> float:
    for counter in ET.parse(xml_path).getroot().findall("counter"):
        if counter.get("type") == kind:
            covered, missed = int(counter.get("covered")), int(counter.get("missed"))
            return covered / (covered + missed)
    raise AssertionError(f"{kind} counter가 없다: {xml_path}")


def _covered_lines(xml_path: Path) -> set[tuple[str, int]]:
    lines = set()
    for package in ET.parse(xml_path).getroot().iter("package"):
        for sourcefile in package.iter("sourcefile"):
            for line in sourcefile.iter("line"):
                if int(line.get("ci")) > 0 or int(line.get("cb")) > 0:
                    lines.add((f"{package.get('name')}/{sourcefile.get('name')}", int(line.get("nr"))))
    return lines


def _suite_dir(run, suite: str) -> Path:
    return run.run_dir / "S08" / suite


def test_req031_baseline_suite_coverage(baseline_run):
    assert baseline_run.stage("S08")["status"] == "passed", baseline_run.stage("S08")
    suites = ["blackbox", *(f"e2e-{g}" for g in _executed_generations(baseline_run))]
    kpis = baseline_run.run_json["kpis"]
    for suite in suites:
        for kind in ("attributed", "aggregate"):
            base = _suite_dir(baseline_run, suite) / kind
            for name in ("html/index.html", "jacoco.xml", "jacoco.csv"):
                assert (base / name).is_file(), (suite, kind, name)
        assert kpis[suite]["line"] == pytest.approx(_counter_ratio(_suite_dir(baseline_run, suite) / "attributed" / "jacoco.xml", "LINE"))
        assert 0 <= kpis[suite]["branch"] <= 1, suite


def test_req063_baseline_merged_aggregate(baseline_run):
    root = baseline_run.run_dir / "S08" / "merged"
    manifest = _json(root / "manifest.json")
    merged = root / "aggregate.xml"
    digest = hashlib.sha256(merged.read_bytes()).hexdigest()
    assert sorted(manifest["suites"]) == sorted(["blackbox", *(f"e2e-{g}" for g in _executed_generations(baseline_run))])
    assert manifest["commit"] == baseline_run.run_json["commit"] and manifest["xmlSha256"] == digest
    assert manifest["classes"] == baseline_run.stage("S00")["outputs"]["classes"]
    config = yaml.safe_load((baseline_run.run_dir / "S09" / "hotspot" / "hotspot.config.yml").read_text())
    assert hashlib.sha256(Path(config["analysis"]["jacocoReportPath"]).read_bytes()).hexdigest() == digest
    assert baseline_run.stage("S11")["coverageXmlSha256"] == digest


def test_req032_baseline_integrity(baseline_run):
    integrity = _json(baseline_run.run_dir / "S08" / "coverage.json")["integrity"]
    assert integrity["violations"] == [] and integrity["classIdWarnings"] == 0
    for suite in ["blackbox", *(f"e2e-{g}" for g in _executed_generations(baseline_run))]:
        attributed = _covered_lines(_suite_dir(baseline_run, suite) / "attributed" / "jacoco.xml")
        aggregate = _covered_lines(_suite_dir(baseline_run, suite) / "aggregate" / "jacoco.xml")
        assert attributed <= aggregate, suite


# --- H. 분석 리포트 ------------------------------------------------------------------------------------
def test_req035_baseline_hotspot(baseline_run):
    assert baseline_run.stage("S09")["status"] == "passed", baseline_run.stage("S09")
    site = baseline_run.run_dir / "site"
    for name in ("hotspots.html", "api_report.html"):
        assert (site / "hotspot" / name).stat().st_size > 0, name
    assert 'href="hotspot/hotspots.html"' in (site / "index.html").read_text()


def test_req036_baseline_tia_base(baseline_run):
    stage = baseline_run.stage("S10")
    assert stage["status"] == "passed", stage
    head = baseline_run.run_json["commit"]
    expected = subprocess.run(["git", "-C", str(SUT_SRC), "rev-list", "--first-parent", "-n", "1", "--skip=10", head],
                              capture_output=True, text=True, check=True).stdout.strip()
    assert stage["base"] == expected and expected.startswith("c37b2e4")
    root = baseline_run.run_dir / "S10"
    assert (root / "tia.db").stat().st_size > 0 and (root / "scenarios.json").is_file()
    html = (root / "tia" / "tia.html").read_text()
    embedded, _ = json.JSONDecoder().raw_decode(html[html.index("const D = ") + len("const D = "):])
    assert stage["base"].startswith(embedded["commit"])
    testwise = _json(root / "testwise.json")
    assert any(str(t["uniformPath"]).startswith("E2E_") for t in testwise["tests"])
    assert 'href="tia/tia.html"' in (baseline_run.run_dir / "site" / "index.html").read_text()


def test_req037_baseline_sonar_export(baseline_run):
    from jsonschema import Draft202012Validator
    stage = baseline_run.stage("S11")
    assert stage["status"] == "passed", stage
    doc = _json(baseline_run.run_dir / "S11" / "sonar" / "sonar.json")
    assert not list(Draft202012Validator(_json(SCHEMAS / "sonar.schema.json")).iter_errors(doc))
    assert doc["projectKey"] == SUT_YAML["sonar"]["projectKey"] == "spring-petclinic-td"
    assert doc["qualityGate"]["status"]
    for name in ("issues", "hotspots"):
        part = doc[name]
        assert part["fetched"] == len(part["items"]) == min(part["total"], 10000)
        assert part["truncated"] == (part["total"] > part["fetched"])
        assert all(item["key"] and item["link"].startswith(doc["serverUrl"]) for item in part["items"])
    assert 'href="sonar/sonar.html"' in (baseline_run.run_dir / "site" / "index.html").read_text()


def test_req038_baseline_own_token_removed(baseline_run, second_run, local_env):
    for _, run in _runs(baseline_run, second_run):
        assert run.stage("S11")["status"] == "passed"
        assert token_rows(local_env, f"td-{run.run_id}") == []


# --- I. 비교 실험 --------------------------------------------------------------------------------------
def test_req040_baseline_compare_json(baseline_run):
    doc = _json(baseline_run.run_dir / "S12" / "compare" / "compare.json")
    jsonschema.validate(doc, _json(SCHEMAS / "compare.schema.json"))
    jqa = _json(baseline_run.run_dir / "S03" / "ontology-jqa.json")
    endpoints = [n for n in jqa["nodes"] if n["kind"] == "Endpoint" and n["props"]["view"] is False]
    assert doc["endpoints"]["denominator"] == len(endpoints) == len(EXPECTED_ENDPOINTS["endpoints"]) == 17
    assert doc["reps"] == 3
    for arm in ARMS:
        entry = doc["arms"][arm]
        assert entry["status"] == "ok", (arm, entry.get("reason"))
        for metric in ("scenarios", "compile", "undefined", "passed", "endpoint", "line", "branch", "lineDelta",
                       "branchDelta", "uniqueLines", "oracle", "focusLine", "tokens", "seconds"):
            assert metric in entry["metrics"], (arm, metric)
            values = entry["metrics"][metric]
            assert {"mean", "min", "max"} <= set(values), (arm, metric)


def test_req067_baseline_compare_html(baseline_run):
    html = (baseline_run.run_dir / "S12" / "compare" / "compare.html").read_text()
    header = re.search(r'<table id="compare-table">.*?</thead>', html, re.S).group(0)
    for arm in ARMS:
        assert f"{arm} (n=3/3)" in header, (arm, header[-400:])
    assert "탐색적 관찰" in html and re.search(r'id="reps">3</b>', html)
    assert re.search(r'data-verdict="[^"]+"', html)
    assert html.count("<svg") >= 4
    limitations = re.search(r'<ul id="limitations">(.*?)</ul>', html, re.S).group(1)
    for needle in ("OWL", "사전 지식"):
        assert needle in limitations
    assert 'href="compare/compare.html"' in (baseline_run.run_dir / "site" / "index.html").read_text()


def test_req041_baseline_oracle_absent_from_bundles(baseline_run):
    from test_compare import _normalize
    descriptions = bundle.load_oracle_descriptions(SUT_DIR / "oracle.yaml")
    assert len(descriptions) >= 7
    for arm, path in _preserved_bundles(baseline_run).items():
        text = " ".join(_normalize(p.read_text(errors="replace")) for p in path.rglob("*") if p.is_file())
        assert not [d for d in descriptions if _normalize(d) in text], arm


# --- J. 게시와 누적 -------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def prod_published(baseline_run, second_run):
    """test_hosting/test_publish의 published_runs와 같은 모양(운영 접두)."""
    return {"sut": "petclinic", "prefix": baseline_run.prefix,
            "runs": [(run.run_id, run.run_dir, None) for _, run in _runs(baseline_run, second_run)]}


def test_req044_baseline_history_accumulates(baseline_run, prod_published, s3_client, bucket):
    from test_publish import test_req044_history_accumulates
    session = baseline_run.session
    assert session["baselineEtagsBeforeSecond"] and session["baselineEtagsAfterSecond"] == session["baselineEtagsBeforeSecond"]
    assert session["baselineEtagsBeforeSecond"] == baseline_run.record["publishedEtags"]
    test_req044_history_accumulates(prod_published, s3_client, bucket, prod_published["prefix"])


def test_req068_baseline_cache_headers(prod_published, local_env):
    from test_hosting import test_req068_cache_headers
    test_req068_cache_headers(prod_published, local_env, prod_published["prefix"])


def test_req047_baseline_static_host_crawl(prod_published, local_env):
    from test_hosting import test_req047_static_host_crawl
    test_req047_static_host_crawl(prod_published, local_env, prod_published["prefix"])


def test_req048_baseline_lightsail_crawl(prod_published, local_env, s3_client, bucket):
    from test_hosting import test_req048_lightsail_crawl
    test_req048_lightsail_crawl(prod_published, local_env, prod_published["prefix"], s3_client, bucket)


def test_req071_baseline_publish_status_files(prod_published, s3_client, bucket, local_env):
    from test_publish import test_req071_publish_status_files
    test_req071_publish_status_files(prod_published, s3_client, bucket, prod_published["prefix"], local_env)


def test_req051_baseline_quantitative(prod_published, local_env):
    from test_hosting import test_req051_quantitative
    test_req051_quantitative(prod_published, local_env, prod_published["prefix"])


def test_req073_baseline_qualitative(prod_published, local_env):
    from test_hosting import test_req073_qualitative
    test_req073_qualitative(prod_published, local_env, prod_published["prefix"])


def test_req049_baseline_home_sut_run_pages(baseline_run, second_run, local_env):
    """홈의 과제 데이터와 과제 페이지(요구사항명세 2026-11-22 §3 REQ-049). 값은 최신 run(두 번째 run)에서 온다."""
    from markupsafe import escape
    from test_publish import linked_project, projects_island, runs_table, trend_panel
    domain = local_env["TD_DOMAIN"]
    prefix = baseline_run.prefix
    top = second_run.stage("S09")["top10"][0]["name"]
    for host in (f"reports.{domain}", f"dash.{domain}"):
        status, home = helpers.https_get(host, domain, f"/{prefix}index.html")
        home = home.decode()
        assert status == 200, host
        status, projects_body = helpers.https_get(host, domain, f"/{prefix}projects.json")
        assert status == 200, host
        document = json.loads(projects_body)
        assert projects_island(home) == document, host
        # 그 SUT와 이어진 과제의 네 값(테스트 통과율, 귀속 라인 커버리지, Sonar 게이트, hotspot 1위)이 모두 있다
        project = linked_project(document, "petclinic")
        values = {name: project["values"][name] for name in ("tests.passRate", "coverage.line", "sonar.gate", "hotspot.topName")}
        assert all(value is not None for value in values.values()), (host, values)
        assert values["hotspot.topName"] == top, (host, values)
        assert f'href="{project["href"]}"' in home, host
        status, project_page = helpers.https_get(host, domain, f"/{prefix}{project['href']}")
        project_page = project_page.decode()
        assert status == 200, host
        # '한눈에'에 그 값이 서버 렌더로 보인다(값이 없으면 템플릿이 "—"를 쓴다)
        for metric in ("tests.passRate", "coverage.line", "sonar.gate"):
            shown = re.search(rf'data-metric="{re.escape(metric)}"><div><span>[^<]*</span><b>([^<]*)</b>', project_page)
            assert shown and shown.group(1).strip() not in ("", "—"), (host, metric)
        assert str(escape(top)) in project_page, host
        # 실행 이력 구역에 두 run, 추이 구역에 서버가 그린 SVG
        table = runs_table(project_page)
        assert f'data-run="{baseline_run.run_id}"' in table and f'data-run="{second_run.run_id}"' in table, host
        assert trend_panel(project_page).count("<svg") >= 2, host
        # SUT 페이지는 그 과제 페이지로 안내한다
        status, sut_page = helpers.https_get(host, domain, f"/{prefix}suts/petclinic/index.html")
        assert status == 200 and f'id="to-project" href="../../{project["href"]}"' in sut_page.decode(), host
    # run 페이지: 성공(passed/degraded)한 리포트 단계마다 링크가 있다
    links = {"S04": "ontology/jqa.html", "S08": "coverage/coverage.html", "S09": "hotspot/hotspots.html",
             "S10": "tia/tia.html", "S11": "sonar/sonar.html", "S12": "compare/compare.html"}
    for _, run in _runs(baseline_run, second_run):
        status, page = helpers.https_get(f"reports.{domain}", domain, f"/{prefix}suts/petclinic/runs/{run.run_id}/index.html")
        page = page.decode()
        assert status == 200
        for stage_id, href in links.items():
            if run.stage(stage_id)["status"] in ("passed", "degraded"):
                assert f'href="{href}"' in page, (run.run_id, stage_id)


# --- K. 공유 인프라 ------------------------------------------------------------------------------------
def test_req052_baseline_sonar_healthy(baseline_run, local_env):
    from test_infra import test_req052_sonar_healthy
    assert baseline_run.stage("S13")["status"] in ("passed", "degraded")
    test_req052_sonar_healthy(local_env)


# --- L. 운영 사이트(화면 재설계 REQ-130, 131, 139, 140) ----------------------------------------------------
def count_runs_with_real_gh(repo: str) -> int:
    """실제 `gh api`로 기본 브랜치의 완료된 Actions 실행 최근 30개를 읽어 설계 §6.3의 분류로 센다(성공 + 실패, 제외는 빼고).
    수집기 코드를 부르지 않는 독립 오라클이다."""
    def gh(path: str) -> dict:
        done = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr[-300:]
        return json.loads(done.stdout)
    branch = gh(f"repos/{repo}")["default_branch"]
    runs = gh(f"repos/{repo}/actions/runs?branch={branch}&status=completed&per_page=30")["workflow_runs"]
    counted = {"success", "failure", "timed_out", "startup_failure"}
    return sum(1 for run in runs[:30] if run.get("conclusion") in counted)


def test_req130_hotspot_map_published(baseline_site, browser):
    status, body = baseline_site.get(baseline_site.run_path + "hotspot/hotspots.html")
    assert status == 200
    block = re.search(r'<script type="application/json" id="hotspot-map-data">(.*?)</script>', body.decode(), re.S)
    assert block and json.loads(block.group(1))["schemaVersion"] == 1
    top = json.loads(baseline_site.get(baseline_site.run_path + "stages/S09.json")[1])["top10"]
    assert 1 <= len(top) <= 10 and all({"name", "file", "score"} <= set(t) for t in top)
    assert [t["score"] for t in top] == sorted((t["score"] for t in top), reverse=True)
    page = open_page(browser, baseline_site.url(baseline_site.run_path + "hotspot/hotspots.html"))
    try:
        assert page.locator("#hm-map circle").count() >= 1
    finally:
        page.context.close()


def test_req131_tia_report_published(baseline_site, browser):
    page = open_page(browser, baseline_site.url(baseline_site.run_path + "tia/tia.html"))
    try:
        tabs = page.locator("#seg [role=tab]")
        assert tabs.count() == 4 and "변경 영향" in tabs.first.inner_text()
        # 리포트는 탭을 바꾸면 새 페이지를 비동기로 다시 그린다(클릭 직후에는 목록이 비어 있다). count()는 기다리지 않으므로
        # 다시 그려질 때까지 재시도하는 expect로 같은 값을 단언한다.
        for i in range(4):
            tabs.nth(i).click()
            expect(tabs.nth(i)).to_have_attribute("aria-selected", "true")
            expect(page.locator(TIA_GUIDE_SELECTOR + ":visible")).to_have_count(1)
        tabs.first.click()
        changed = json.loads((baseline_site.run_dir / "S10" / "impact.json").read_text())["changedFiles"]
        expect(page.locator(TIA_CHANGED_FILE_SELECTOR)).to_have_count(len(changed))
    finally:
        page.context.close()


def test_req139_production_site_paths(baseline_site, browser):
    cfg = dashboard_config.load(REPO_ROOT / "dashboard.yaml", REPO_ROOT / "suts")
    listed = json.loads(baseline_site.get("projects.json")[1])["projects"]
    home = open_page(browser, baseline_site.url(""))
    try:
        assert home.locator("tr.proj").count() == len(listed) and 1 <= len(listed) <= len(cfg.projects)
    finally:
        home.context.close()
    walk = [f"projects/{baseline_site.project}/index.html", baseline_site.run_path + "index.html",
            baseline_site.run_path + "hotspot/hotspots.html", baseline_site.run_path + "tia/tia.html",
            f"suts/{baseline_site.sut}/index.html"]
    for host in ("reports", "dash"):
        statuses = {p: baseline_site.get(p, host=host)[0] for p in walk}
        assert all(code == 200 for code in statuses.values()), (host, statuses)
        assert baseline_site.get("_design/home-repos/", host=host)[0] != 200, host
        assert baseline_site.get("_design/project/", host=host)[0] != 200, host
    old = baseline_site.get(f"suts/{baseline_site.sut}/runs/{OLD_RUN_ID}/index.html")
    assert old[0] == 200 and b"static/site.css" in old[1]
    # 띠의 SUT 링크: run 페이지와 띠를 끼운 리포트에서 `a.tdnav-sut`의 href를 읽어 그 주소를 따라가면 과제 페이지에 닿는다
    project_path = f"projects/{baseline_site.project}/index.html"
    landing_path = f"suts/{baseline_site.sut}/index.html"
    for host, page_url in (("reports", baseline_site.url), ("dash", baseline_site.dash_url)):
        for report in ("index.html", "hotspot/hotspots.html"):
            source = baseline_site.run_path + report
            status, body = baseline_site.get(source, host=host)
            href = re.search(r'<a class="tdnav-sut" href="([^"]+)"', body.decode())
            assert status == 200 and href, (host, source)
            target = posixpath.normpath(posixpath.join(posixpath.dirname(source), href.group(1)))
            assert target == landing_path, (host, source, href.group(1))
            landing_status, landing = baseline_site.get(target, host=host)
            assert landing_status == 200 and f'id="to-project" href="../../{project_path}"' in landing.decode(), (host, target)
        page = open_page(browser, page_url(baseline_site.run_path + "index.html"))
        try:
            page.click("a.tdnav-sut")
            page.wait_for_url(page_url(project_path), timeout=15000)
            assert page.locator("#tabs [role=tab]").count() >= 1, host
        finally:
            page.context.close()
        assert baseline_site.get(project_path, host=host)[0] == 200, host


def test_req140_production_site_values(baseline_site, browser):
    latest = json.loads(baseline_site.get("projects/hotspot-analysis/latest.json")[1])
    real_count = count_runs_with_real_gh("baekchangjoon/hotspot-analysis")
    assert isinstance(latest["ci"]["runs"], int) and abs(latest["ci"]["runs"] - real_count) <= 2, (latest["ci"]["runs"], real_count)
    data = json.loads(baseline_site.get("projects.json")[1])
    mine = next(p for p in data["projects"] if p["name"] == baseline_site.project)
    home = open_page(browser, baseline_site.url(""))
    try:
        row = home.locator(f'tr.proj[data-name="{baseline_site.project}"]')
        assert row.get_attribute("data-status") == mine["status"]["level"]
        row.click()
        reasons_text = home.inner_text("tr.proj-detail .detail-reasons")
        assert all(reason in reasons_text for reason in mine["status"]["reasons"]), (mine["status"], reasons_text)
    finally:
        home.context.close()
    runs = json.loads(baseline_site.get(f"suts/{baseline_site.sut}/runs.json")[1])
    page = open_page(browser, baseline_site.url(f"projects/{baseline_site.project}/index.html#trend"))
    try:
        with_rate = sum(1 for r in runs if r["kpis"]["passRate"] is not None)
        assert page.locator('figure.trend[data-metric="tests.passRate"] .pt').count() == min(30, with_rate)
        # '한눈에'는 최신 run(runs.json에서 runId가 가장 큰 run)의 값을 보여 준다. 기준 run이 아니라 그 run과 비교한다
        latest_run = max(runs, key=lambda entry: entry["runId"])
        assert latest_run["kpis"]["passRate"] is not None and latest_run["kpis"]["line"] is not None, latest_run
        page.click("#tab-overview")
        assert page.inner_text('#panel-overview .kpi[data-metric="tests.passRate"] b') == f'{latest_run["kpis"]["passRate"] * 100:.1f}%'
        assert page.inner_text('#panel-overview .kpi[data-metric="coverage.line"] b') == f'{latest_run["kpis"]["line"] * 100:.1f}%'
    finally:
        page.context.close()
