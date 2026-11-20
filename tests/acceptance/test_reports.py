"""S09 hotspot 수용 테스트(Int/E2E): REQ-035.

`run-all.sh petclinic --only S00,S01,S08,S09`를 세션당 한 번 돌려 재사용한다(S08 병합 XML이 입력이다).
S08이 없는 run은 `--only S00,S09`로 따로 돌려 degraded 경로를 본다.
"""
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from helpers import PETCLINIC_SRC, pid_alive, run_pids
from td import envctl
from td.site import pages


@pytest.fixture(scope="session")
def s09_run(real_pipeline_run):
    return real_pipeline_run("S00,S01,S08,S09")


@pytest.fixture(scope="session")
def s09_without_coverage_run(real_pipeline_run):
    return real_pipeline_run("S00,S09")


def test_req035_hotspot(s09_run):
    assert s09_run.returncode == 0, s09_run.stderr[-3000:]
    stage = s09_run.stage("S09")
    assert stage["status"] == "passed", stage
    root = s09_run.run_dir / "S09"
    hotspot = root / "hotspot"
    for name in ("hotspots.html", "api_report.html", "hotspot.config.yml"):
        assert (hotspot / name).is_file(), name
        assert (hotspot / name).stat().st_size > 0, name
    # 렌더링된 설정의 jacocoReportPath가 S08 병합 XML을 가리키고 파일 해시가 같다
    config = yaml.safe_load((hotspot / "hotspot.config.yml").read_text())
    jacoco_path = Path(config["analysis"]["jacocoReportPath"])
    merged = s09_run.run_dir / "S08" / "merged" / "aggregate.xml"
    assert jacoco_path.is_absolute() and hashlib.sha256(jacoco_path.read_bytes()).hexdigest() == hashlib.sha256(merged.read_bytes()).hexdigest()
    assert config["analysis"]["apiAnalysis"]["enabled"] is True
    # top10
    top10 = json.loads((root / "top10.json").read_text())
    assert 1 <= len(top10) <= 10 and stage["top10"] == top10
    scores = [row["score"] for row in top10]
    assert scores == sorted(scores, reverse=True) and all(row["name"] and row["file"] for row in top10)
    # run 페이지는 hotspot 리포트에 링크하고, 게시용 사본에 두 HTML이 들어간다
    site_dir = pages.render_run(s09_run.run_dir, s09_run.run_dir).parent
    assert 'href="hotspot/hotspots.html"' in (site_dir / "index.html").read_text()
    assert (site_dir / "hotspot" / "hotspots.html").is_file() and (site_dir / "hotspot" / "api_report.html").is_file()
    # 게시 사본에는 run 디렉터리와 홈 경로가 없다(로컬 렌더 설정은 절대 경로 그대로다)
    home = str(Path.home())
    for path in (site_dir / "hotspot").rglob("*"):
        if path.is_file() and path.suffix in {".html", ".yml", ".csv", ".md"}:
            text = path.read_text()
            assert str(s09_run.run_dir) not in text and home not in text, path
    published_config = yaml.safe_load((site_dir / "hotspot" / "hotspot.config.yml").read_text())
    assert published_config["analysis"]["jacocoReportPath"].startswith("<run>/S08/merged/")


def test_req035_hotspot_degraded_without_merged_coverage(s09_without_coverage_run):
    run = s09_without_coverage_run
    stage = run.stage("S09")
    assert stage["status"] == "degraded" and "S08" in stage["reason"] and "aggregate.xml" in stage["reason"], stage
    hotspot = run.run_dir / "S09" / "hotspot"
    assert (hotspot / "hotspots.html").is_file() and (hotspot / "api_report.html").is_file()
    config = yaml.safe_load((hotspot / "hotspot.config.yml").read_text())
    assert "jacocoReportPath" not in config["analysis"]
    top10 = json.loads((run.run_dir / "S09" / "top10.json").read_text())
    assert 1 <= len(top10) <= 10 and stage["top10"] == top10
    assert all(set(row) >= {"name", "file", "score"} for row in top10)


# --- S11 Sonar(REQ-037, REQ-063 보강) ---------------------------------------------------------------
def test_req037_sonar_export(s11_run):
    from jsonschema import Draft202012Validator
    run = s11_run.result
    assert run.returncode in (0, 2), run.stderr[-3000:]
    stage = run.stage("S11")
    assert stage["status"] == "passed", stage
    sonar_dir = run.run_dir / "S11" / "sonar"
    doc = json.loads((sonar_dir / "sonar.json").read_text())
    schema = json.loads((Path(pages.__file__).parents[1] / "schemas" / "sonar.schema.json").read_text())
    assert not list(Draft202012Validator(schema).iter_errors(doc))
    assert doc["projectKey"].startswith("spring-petclinic-td-test-")  # 주입 실행은 세션 전용 프로젝트를 쓴다
    assert doc["qualityGate"]["status"] in ("OK", "ERROR", "WARN", "NONE")
    for name in ("issues", "hotspots"):
        part = doc[name]
        assert part["fetched"] == len(part["items"]) == min(part["total"], 10000)
        assert part["truncated"] == (part["total"] > part["fetched"])
        assert all(item["key"] and item["link"].startswith(doc["serverUrl"]) for item in part["items"])
    assert (sonar_dir / "sonar.html").is_file()
    # run 페이지가 링크하고, 게시 사본에 sonar.html이 있다
    site_dir = pages.render_run(run.run_dir, run.run_dir).parent
    assert 'href="sonar/sonar.html"' in (site_dir / "index.html").read_text()
    assert (site_dir / "sonar" / "sonar.html").is_file() and (site_dir / "sonar" / "sonar.json").is_file()
    assert run.run_json["kpis"]["sonar"]["gate"] == doc["qualityGate"]["status"]  # REQ-063 대응은 test_coverage.py
    assert stage["ceTaskId"] and stage["projectKey"] == doc["projectKey"]
    # 게시 사본에는 로컬 홈 경로가 없다
    home = str(Path.home())
    for path in site_dir.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".json"}:
            assert home not in path.read_text(), path


# --- S10 TIA(REQ-036, REQ-011) ---------------------------------------------------------------------
def _worktrees() -> str:
    return subprocess.run(["git", "-C", str(PETCLINIC_SRC), "worktree", "list", "--porcelain"],
                          capture_output=True, text=True).stdout


@pytest.fixture(scope="session")
def s10_run(real_pipeline_run):
    """`--only S00,S02,S06,S10 --arms base` 실제 run 1회. S06은 커밋된 스냅샷(e2e/generated/petclinic/base)을 재사용하므로
    입력 해시가 같으면 claude를 부르지 않는다(값싼 generation 하나). 실행 전후의 worktree 목록과 라벨 자원을 함께 기록한다."""
    before_worktrees = _worktrees()
    before = envctl.snapshot()
    result = real_pipeline_run("S00,S02,S06,S10", args=("--arms", "base", "--reps", "1"))
    return {"result": result, "before_worktrees": before_worktrees, "leak": envctl.diff(before, envctl.snapshot())}


def test_req036_tia_base(s10_run):
    run = s10_run["result"]
    assert run.returncode == 0, run.stderr[-3000:]
    stage = run.stage("S10")
    # base 블랙박스에 arm별 rep1 e2e generation이 붙으면 S10은 passed다(Task 22).
    assert run.stage("S06")["status"] == "passed", run.stage("S06")
    assert stage["status"] == "passed" and stage["reason"] is None, stage
    [(gen_id, e2e)] = stage["e2e"].items()
    assert gen_id.startswith("base-") and gen_id.endswith("-r1") and e2e["execMerged"] >= 1 and stage["e2eAttached"] == 1
    base = stage["base"]
    assert re.fullmatch(r"[0-9a-f]{40}", base)
    head = run.stage("S00")["outputs"]["commit"]
    expected = subprocess.run(["git", "-C", str(PETCLINIC_SRC), "rev-list", "--first-parent", "-n", "1", "--skip=10", head],
                              capture_output=True, text=True, check=True).stdout.strip()
    assert base == expected and base.startswith("c37b2e4")
    root = run.run_dir / "S10"
    assert (root / "tia.db").is_file() and (root / "tia.db").stat().st_size > 0
    testwise = json.loads((root / "testwise.json").read_text())
    assert testwise, "testwise.json이 비었다"
    assert (root / "base-head.diff").stat().st_size > 0
    # scenarios.json은 tia report 계약의 시나리오 목록이고, 선택 수가 단계 요약과 impact.json에 일치한다
    scenarios = json.loads((root / "scenarios.json").read_text())
    impact_doc = json.loads((root / "impact.json").read_text())
    assert isinstance(scenarios, list) and len(scenarios) == 1
    (scenario,) = scenarios
    assert scenario["count"] == len(scenario["selected"]) == len(impact_doc["tests"]) == stage["impact"]["selected"]
    # 인덱스 = 블랙박스 per-test .exec + base에서 돌린 e2e per-test .exec(testId가 E2E_로 시작)
    test_ids = [t["uniformPath"] for t in testwise["tests"]]
    e2e_ids = [t for t in test_ids if str(t).startswith("E2E_base_")]
    assert len(e2e_ids) == e2e["execMerged"], test_ids[:5]
    assert stage["impact"]["indexedTests"] == scenario["total"] == len(testwise["tests"]) == stage["execCount"] + len(e2e_ids)
    assert all(set(item) == {"confidence", "testId"} for item in scenario["selected"])
    assert scenario["conservative"] is stage["impact"]["allSelectedConservative"]
    html = (root / "tia" / "tia.html").read_text()
    # tia report는 --commit을 내장 데이터 D.commit에 채운다. 사전 검사에서 해석한 base와 같아야 한다.
    embedded, _ = json.JSONDecoder().raw_decode(html[html.index("const D = ") + len("const D = "):])
    assert embedded["commit"] == base and embedded["sut"] == "petclinic", {k: embedded[k] for k in ("commit", "sut")}
    assert isinstance(embedded["scenarios"], list) and len(embedded["scenarios"]) == 1
    # 블랙박스의 귀속 손실은 문서화된 1건뿐이다. e2e TC는 testkit이 필터 체인(HttpServlet#service 바깥) 프로브를
    # droppedProbes로 보고하므로 incompleteAttribution 목록에 함께 나온다(설계 §13.9 귀속 한계, 기록만 한다).
    assert [t for t in stage["incompleteAttribution"] if not t.startswith("E2E_")] == \
        ["ConcurrencyBlackBoxIT#concurrentPetCreatesForSameOwnerAreAllPersisted"]
    assert stage["tcCount"] >= 1 and stage["execCount"] >= 1
    # run 페이지가 TIA 리포트에 링크하고 게시 사본에 들어간다
    site_dir = pages.render_run(run.run_dir, run.run_dir).parent
    assert 'href="tia/tia.html"' in (site_dir / "index.html").read_text()
    assert (site_dir / "tia" / "tia.html").is_file()
    assert not (site_dir / "tia" / "base").exists() and not list(site_dir.rglob("tia.db"))
    # 게시 사본에는 run 디렉터리와 홈 경로가 없다(test_req037과 같은 검사)
    home = str(Path.home())
    for path in (site_dir / "tia").rglob("*"):
        if path.is_file() and path.suffix in {".html", ".json", ".txt"}:
            text = path.read_text()
            assert str(run.run_dir) not in text and home not in text, path
    # 정리: worktree와 라벨 자원이 남지 않는다
    assert not (root / "base").exists()
    assert _worktrees() == s10_run["before_worktrees"]
    assert s10_run["leak"].owned == [], s10_run["leak"]
