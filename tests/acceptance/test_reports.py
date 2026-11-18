"""S09 hotspot 수용 테스트(Int/E2E): REQ-035.

`run-all.sh petclinic --only S00,S01,S08,S09`를 세션당 한 번 돌려 재사용한다(S08 병합 XML이 입력이다).
S08이 없는 run은 `--only S00,S09`로 따로 돌려 degraded 경로를 본다.
"""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

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
    for name in ("hotspots.html", "api_report.html", "hotspot.yml"):
        assert (hotspot / name).is_file(), name
        assert (hotspot / name).stat().st_size > 0, name
    # 렌더링된 설정의 jacocoReportPath가 S08 병합 XML을 가리키고 파일 해시가 같다
    config = yaml.safe_load((hotspot / "hotspot.yml").read_text())
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


def test_req035_hotspot_degraded_without_merged_coverage(s09_without_coverage_run):
    run = s09_without_coverage_run
    stage = run.stage("S09")
    assert stage["status"] == "degraded" and "S08" in stage["reason"] and "aggregate.xml" in stage["reason"], stage
    hotspot = run.run_dir / "S09" / "hotspot"
    assert (hotspot / "hotspots.html").is_file() and (hotspot / "api_report.html").is_file()
    config = yaml.safe_load((hotspot / "hotspot.yml").read_text())
    assert "jacocoReportPath" not in config["analysis"]
    assert json.loads((run.run_dir / "S09" / "top10.json").read_text())
