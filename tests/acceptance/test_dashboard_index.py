"""run 지표, 과제 뷰, 시계열, 집계, 추이 차트 수용 테스트(Unit).

REQ-102(run 지표), REQ-103(시계열), REQ-105(기존 인덱스 파일 호환), REQ-122(세로축), REQ-141(집계).
"""
import json
import re

import pytest

from td import dashboard_config
from td.dashboard_config import CATALOG
from td.site import charts, metrics
from td.site.charts import CHART_BASE_Y, CHART_MID_Y, y_for
from dashboard_fixtures import (RUN_A, RUN_B, RUN_C, cfg_with, load_cfg, make_site, rebuild_site, snap,
                                write_collect_state, write_run)


def pts(values: list) -> list[dict]:
    """차트 입력 점. id·at은 순서대로 고정 값이다."""
    return [{"id": f"2026110{index + 1}", "at": f"2026-11-0{index + 1}T00:00:00Z", "value": value}
            for index, value in enumerate(values)]


def cys(svg: str) -> set[float]:
    """SVG 안 점(circle)의 세로 좌표 집합."""
    return {float(value) for value in re.findall(r'<circle[^>]*\bcy="([-\d.]+)"', svg)}


# --- REQ-102 ---------------------------------------------------------------------------------

def test_req102_run_metrics(tmp_path):
    run = write_run(tmp_path, "pet", "20261120-131022Z-b6f9393-manual-036c288d",
        tests_pass=1.0, line=0.4152, agg_line=0.6091, generations={"base-r1": (21, 31), "jqa-r1": (30, 40)},
        sonar={"gate": "OK", "coverage": "57.1", "bugs": "2", "vulnerabilities": "18", "codeSmells": "69"},
        top10=[{"name": "Owner.getPet", "file": "Owner.java", "score": 27.345}], impact={"selected": 68, "indexedTests": 134},
        started="2026-11-20T13:10:22Z", last_finished="2026-11-20T13:18:57Z")
    m = metrics.run_metrics(run)
    assert (m["tests.passRate"], m["coverage.line"], m["coverage.aggregateLine"]) == (1.0, 0.4152, 0.6091)
    assert m["e2e.passRate"] == pytest.approx(51 / 71)
    assert (m["sonar.gate"], m["sonar.coverage"], m["sonar.vulnerabilities"], m["sonar.bugs"], m["sonar.codeSmells"]) == ("OK", 57.1, 18, 2, 69)
    assert all(isinstance(m[name], int) for name in ("sonar.vulnerabilities", "sonar.bugs", "sonar.codeSmells"))
    assert isinstance(m["sonar.coverage"], float)
    assert (m["hotspot.topScore"], m["hotspot.topName"]) == (27.345, "Owner.getPet")
    assert m["tia.selectedRatio"] == pytest.approx(68 / 134) and m["run.durationSec"] == 515
    assert set(m) == {name for name, metric in CATALOG.items() if metric.scope in ("run", "both")}
    bare = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000000Z-aaaaaaa-manual-00000000",
                                         only_stages=["S00", "S01", "S08"], sonar=None))
    assert bare["e2e.passRate"] is None and bare["hotspot.topScore"] is None and bare["sonar.gate"] is None
    assert bare["hotspot.topName"] is None and bare["tia.selectedRatio"] is None and bare["sonar.coverage"] is None
    zero = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000001Z-aaaaaaa-manual-00000001", impact={"selected": 0, "indexedTests": 0}))
    assert zero["tia.selectedRatio"] is None
    no_scenarios = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000003Z-aaaaaaa-manual-00000003",
                                                 generations={"g": (0, 0)}))
    assert no_scenarios["e2e.passRate"] is None
    failed = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000002Z-aaaaaaa-manual-00000002",
        stage_status={"S07": "failed", "S09": "failed", "S10": "skipped"}, generations={"g": (1, 2)},
        top10=[{"name": "X", "file": "X.java", "score": 9.0}], impact={"selected": 1, "indexedTests": 2}))
    assert failed["e2e.passRate"] is None and failed["hotspot.topScore"] is None and failed["tia.selectedRatio"] is None
    assert failed["hotspot.topName"] is None
    degraded = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000004Z-aaaaaaa-manual-00000004",
        stage_status={"S09": "degraded"}, top10=[{"name": "Y", "file": "Y.java", "score": 3.5}]))
    assert (degraded["hotspot.topScore"], degraded["hotspot.topName"]) == (3.5, "Y")


# --- REQ-103 ---------------------------------------------------------------------------------

def test_req103_series_points(tmp_path):
    site = make_site(tmp_path, runs={"pet": [RUN_A, RUN_B, RUN_C]}, snapshots={"kn": [snap(date="20261121"), snap(date="20261122")]},
                     config=cfg_with(pipeline="pet", plain="kn"))
    cfg = load_cfg(site)
    projects = {p["name"]: p for p in metrics.build_projects(site, cfg)}
    s = metrics.series(projects["pet"], cfg)
    assert s["schema"] == 1
    assert s["kind"] == "run" and [p["id"] for p in s["points"]] == sorted(r["runId"] for r in (RUN_A, RUN_B, RUN_C))
    assert s["metrics"] == cfg.project["trend"]["run"]
    assert set(s["points"][0]["values"]) == set(s["metrics"]) and s["points"][0]["href"].endswith("/index.html")
    first = s["points"][0]
    assert first["href"] == f"../../suts/pet/runs/{first['id']}/index.html"
    assert first["at"] == RUN_A["started"] and first["values"]["tests.passRate"] == RUN_A["tests_pass"]
    k = metrics.series(projects["kn"], cfg)
    assert k["kind"] == "snapshot" and [p["id"] for p in k["points"]] == ["20261121", "20261122"] and "href" not in k["points"][0]
    assert k["metrics"] == cfg.project["trend"]["snapshot"] and set(k["points"][0]["values"]) == set(k["metrics"])
    assert all("href" not in point for point in k["points"]) and all("href" in point for point in s["points"])
    json.dumps(s), json.dumps(k)    # series.json으로 그대로 쓸 수 있다


# --- REQ-105 ---------------------------------------------------------------------------------

def test_req105_legacy_fields_kept(tmp_path):
    site = make_site(tmp_path, runs={"pet": [RUN_A, RUN_B]}); rebuild_site(site, dashboard_config.empty())
    suts = json.loads((site / "suts.json").read_text())
    assert set(suts[0]) >= {"name", "runCount", "latest"} and suts[0]["runCount"] == 2
    assert set(suts[0]["latest"]) >= {"runId", "commit", "trigger", "startedAt", "stages", "kpis"}
    assert set(suts[0]["latest"]["kpis"]) >= {"passRate", "line", "sonarGate", "hotspot1"}
    latest = suts[0]["latest"]
    assert (latest["runId"], latest["commit"], latest["trigger"], latest["startedAt"]) == (
        RUN_B["runId"], "b6f9393", "manual", RUN_B["started"])
    assert latest["kpis"] == {"passRate": RUN_B["tests_pass"], "line": RUN_B["line"], "sonarGate": "OK", "hotspot1": "Owner.getPet"}
    runs = json.loads((site / "suts/pet/runs.json").read_text())
    assert [r["runId"] for r in runs] == [RUN_B["runId"], RUN_A["runId"]] and set(runs[0]) >= {"runId", "commit", "stages", "kpis"}
    assert all(set(run) >= {"runId", "commit", "trigger", "startedAt", "stages", "kpis"} for run in runs)


# --- REQ-122 ---------------------------------------------------------------------------------

def test_req122_chart_axis_rules():
    ratio = charts.trend_svg(CATALOG["tests.passRate"], pts([0.2, 0.2]))
    assert all(t in ratio for t in (">0%<", ">50%<", ">100%<")) and cys(ratio) == {y_for(0.2, 0, 1)}
    coverage = charts.trend_svg(CATALOG["sonar.coverage"], pts([57.1, 60.0]))
    assert ">100%<" in coverage and cys(coverage) == {y_for(57.1, 0, 100), y_for(60.0, 0, 100)}
    count = charts.trend_svg(CATALOG["sonar.vulnerabilities"], pts([3, 18, 7])); assert ">18<" in count and ">0<" in count
    assert min(cys(count)) == y_for(18, 0, 18)
    flat = charts.trend_svg(CATALOG["sonar.bugs"], pts([2, 2, 2])); assert cys(flat) == {CHART_MID_Y}
    zeros = charts.trend_svg(CATALOG["sonar.bugs"], pts([0, 0])); assert cys(zeros) == {CHART_BASE_Y}
    assert charts.trend_svg(CATALOG["sonar.bugs"], pts([2, 2, 2])) == flat


def test_chart_points_carry_data_attributes_and_links():
    run_points = [{**point, "href": f"../../suts/pet/runs/{point['id']}/index.html"} for point in pts([0.5, None, 0.25])]
    svg = charts.trend_svg(CATALOG["tests.passRate"], run_points)
    assert svg.count('<a class="pt"') == 2 and 'href="../../suts/pet/runs/20261101/index.html"' in svg
    assert 'data-id="20261103"' in svg and 'data-at="2026-11-03T00:00:00Z"' in svg and 'data-value="25.0%"' in svg
    assert svg.count('<polyline class="ln"') == 0          # 값 없는 점이 선을 끊어 조각마다 점이 하나뿐
    snap_svg = charts.trend_svg(CATALOG["sonar.bugs"], pts([1, 2]))
    assert snap_svg.count('<g class="pt" tabindex="0"') == 2 and "<a " not in snap_svg and snap_svg.count('<polyline class="ln"') == 1
    many = charts.trend_svg(CATALOG["sonar.bugs"], pts([1] * 9) + [
        {"id": f"p{index:02d}", "at": "2026-11-30T00:00:00Z", "value": index} for index in range(31)])
    assert many.count("<circle") == 30 and 'data-id="p30"' in many and 'data-id="p00"' not in many


# --- REQ-141 ---------------------------------------------------------------------------------

def test_req141_aggregate_metrics(tmp_path):
    site = make_site(tmp_path, snapshots={"a": [snap(ci_runs=10, ci_successes=9, sonar=None, sonar_state="absent")],
        "b": [snap(ci_runs=10, ci_successes=1, sonar=None, sonar_state="absent")],
        "c": [snap(ci=None, ci_state="none", sonar={"gate": "OK", "coverage": 0.0})],
        "d": [snap(ci=None, ci_state="none", sonar={"gate": "ERROR", "coverage": 57.1})]}, config=cfg_with(plain=["a", "b", "c", "d"]))
    agg = metrics.aggregate(metrics.build_projects(site, load_cfg(site)), load_cfg(site))
    assert list(agg) == load_cfg(site).home["summary"]
    assert (agg["ci.successRateAll"]["value"], agg["ci.successRateAll"]["detail"]) == ("50.0%", "10 / 20회")
    assert agg["sonar.gatePassCount"]["value"] == "1 / 2" and agg["sonar.coverageNonZeroCount"]["value"] == "1 / 4"
    assert agg["status.noneCount"]["value"] == "0"
    assert all(entry["label"] == CATALOG[name].label for name, entry in agg.items())
    empty = metrics.aggregate([], dashboard_config.empty())
    assert empty["ci.successRateAll"]["value"] == "—"
    assert all(entry["value"] == "—" for entry in empty.values())


def test_req141_none_count_counts_unmeasured_projects(tmp_path):
    site = make_site(tmp_path, snapshots={"a": [snap(ci=None, ci_state="none", sonar=None, sonar_state="absent")],
                                          "b": [snap(ci_runs=5, ci_successes=5)]}, config=cfg_with(plain=["a", "b"]))
    agg = metrics.aggregate(metrics.build_projects(site, load_cfg(site)), load_cfg(site))
    assert agg["status.noneCount"]["value"] == "1"


# --- 과제 뷰 ------------------------------------------------------------------------------------

def test_build_projects_values_sources_and_order(tmp_path):
    site = make_site(tmp_path,
        runs={"pet": [RUN_A, RUN_B], "loose": [RUN_C]},
        snapshots={"withsut": [snap(date="20261122", ci_runs=10, ci_successes=10,
                                    sonar={"gate": "ERROR", "coverage": 12.0, "vulnerabilities": 3})],
                   "kn": [snap(date="20261122", ci_runs=10, ci_successes=10, sonar={"gate": "OK", "coverage": 80.0})]},
        config={**cfg_with(pipeline="pet", plain="kn"),
                "projects": [{"name": "pet", "sut": "pet"}, {"name": "kn", "repo": "o/kn"},
                             {"name": "withsut", "repo": "o/withsut", "sut": "loose"},
                             {"name": "nosnap", "repo": "o/nosnap"}]})
    cfg = load_cfg(site)
    projects = metrics.build_projects(site, cfg)
    by_name = {project["name"]: project for project in projects}
    assert "nosnap" not in by_name                                   # repo가 있는데 유효 스냅숏이 없다
    pet = by_name["pet"]
    assert pet["pipeline"] and not pet["implicit"] and pet["repo"] is None and pet["sut"] == "pet"
    assert pet["values"]["tests.passRate"] == RUN_B["tests_pass"] and pet["values"]["ci.runs"] is None
    assert [run["runId"] for run in pet["runs"]] == [RUN_B["runId"], RUN_A["runId"]]
    assert pet["latestRunDir"] == site / "suts/pet/runs" / RUN_B["runId"]
    withsut = by_name["withsut"]                                     # run이 있으면 sonar.*는 run에서만
    assert withsut["values"]["sonar.gate"] == "OK" and withsut["values"]["sonar.vulnerabilities"] == 18
    assert withsut["values"]["ci.runs"] == 10 and withsut["values"]["repo.pushedAt"] == "2026-11-20T00:00:00Z"
    kn = by_name["kn"]
    assert not kn["pipeline"] and kn["values"]["sonar.gate"] == "OK" and kn["values"]["sonar.coverage"] == 80.0
    assert kn["sources"] == {"ci": "ok", "sonar": "ok"} and kn["ciHistory"] == [1] * 10 and kn["stale"] is None
    assert kn["verdict"] == {"level": "good", "label": "양호", "reasons": [], "partial": False}
    assert kn["headline"] == "판정 규칙에 걸린 항목이 없습니다"
    assert pet["sources"] == {"ci": None, "sonar": None}
    # 정렬: 수준 순서(crit, warn, none, good) 안에서 이름(대소문자 무시)
    order = cfg.status["order"]
    assert [order.index(project["verdict"]["level"]) for project in projects] == sorted(
        order.index(project["verdict"]["level"]) for project in projects)
    assert [project["name"] for project in projects if project["verdict"]["level"] == "warn"] == ["pet", "withsut"]
    excluded = metrics.build_projects(site, cfg, exclude=frozenset({"kn"}))
    assert "kn" not in {project["name"] for project in excluded}


def test_build_projects_adds_implicit_project(tmp_path):
    site = make_site(tmp_path, runs={"mini": [RUN_A]})
    [mini] = metrics.build_projects(site, load_cfg(site))
    assert mini["name"] == "mini" and mini["implicit"] and mini["pipeline"] and mini["repo"] is None
    assert mini["verdict"]["partial"] is False


def test_unverified_project_is_marked_stale(tmp_path):
    site = make_site(tmp_path, snapshots={"a": [snap(date="20261121")]}, config=cfg_with(plain="a"))
    assert metrics.build_projects(site, load_cfg(site))[0]["stale"] is None
    write_collect_state(site, "20261122", ["a"])
    assert metrics.build_projects(site, load_cfg(site))[0]["stale"] == "20261121"
    (site / "projects/_collect.json").write_text("{broken")
    assert metrics.build_projects(site, load_cfg(site))[0]["stale"] is None


# 검토 초점 2, 4
def test_broken_snapshot_is_dropped_with_reason(tmp_path):
    site = make_site(tmp_path, snapshots={"kn": [snap(date="20261121")]}, config=cfg_with(plain="kn"))
    (site / "projects/kn/snapshots/20261122.json").write_text("{not json")
    kn = metrics.build_projects(site, load_cfg(site))[0]
    assert kn["snapshots"][-1]["date"] == "20261121" and any("20261122" in p for p in kn["problems"])


def test_schema_violating_snapshot_is_dropped_with_reason(tmp_path):
    site = make_site(tmp_path, snapshots={"kn": [snap(date="20261121"), snap(date="20261122")]}, config=cfg_with(plain="kn"))
    bad = site / "projects/kn/snapshots/20261122.json"
    data = json.loads(bad.read_text()); data["visibility"] = "private"; bad.write_text(json.dumps(data))
    snapshots, reasons = metrics.load_snapshots(site / "projects/kn")
    assert [item["date"] for item in snapshots] == ["20261121"] and len(reasons) == 1 and "20261122.json" in reasons[0]


def test_chart_single_point_and_all_missing():
    one = charts.trend_svg(CATALOG["tests.passRate"], pts([0.9])); assert one.count("<circle") == 1 and "<polyline" not in one
    none = charts.trend_svg(CATALOG["tests.passRate"], pts([None, None])); assert "<circle" not in none and "<svg" in none
