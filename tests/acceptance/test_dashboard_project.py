"""과제 페이지와 SUT 안내 페이지 수용 테스트(Task 10).

REQ-080, REQ-084(화면), REQ-108, REQ-115, REQ-116, REQ-117, REQ-118, REQ-119, REQ-120, REQ-121, REQ-123.
고정 사이트(`proj_site`)는 세션에서 한 번 만들어 한 번 띄운다(`proj_dir`, `proj`).
"""
import json
import re
from pathlib import Path

import pytest

from td.dashboard_config import format_value
from dashboard_fixtures import (PROJ_MANY_RUNS, PROJ_PET_OLDER, PROJ_PET_TOP10, REPORTS_RUN_ID, RUN_A, http_status,
                                make_site, open_page, proj, proj_dir, proj_site, rebuild_site, serve, snap, status_of,  # noqa: F401
                                write_collect_state)
from td import dashboard_config

PET = "projects/pet/index.html"
PLAIN = "projects/plain/index.html"
MANY = "projects/many/index.html"
ALL_TABS = ["overview", "trend", "tests", "coverage", "hotspot", "quality", "generation", "runs"]
PET_RUN_IDS = [run["runId"] for run in PROJ_PET_OLDER] + [REPORTS_RUN_ID]


@pytest.fixture()
def page_of(browser):
    """열어 본 페이지의 컨텍스트를 테스트가 끝나면 닫는다."""
    opened = []

    def opener(url, **options):
        page = open_page(browser, url, **options)
        opened.append(page)
        return page
    yield opener
    for page in opened:
        page.context.close()


def visible_panel(page) -> str:
    return page.locator("[role=tabpanel]:visible").get_attribute("id")


def selected_tab(page) -> str:
    return page.locator('button[role=tab][aria-selected="true"]').get_attribute("data-tab")


def kpi(page, panel: str, metric: str) -> str:
    return page.inner_text(f'#panel-{panel} .kpi[data-metric="{metric}"] b').strip()


# --- REQ-115 탭 전환, 주소, 키보드 ------------------------------------------------------------------

def test_req115_tabs_hash_keyboard(proj, page_of):
    page = page_of(proj + PET)
    assert page.locator("#tabs").get_attribute("role") == "tablist"
    assert visible_panel(page) == "panel-overview" and page.locator("[role=tabpanel]:visible").count() == 1
    page.click('button[role=tab][data-tab="coverage"]')
    assert visible_panel(page) == "panel-coverage" and page.url.endswith("#coverage")
    assert page.locator("[role=tabpanel]:visible").count() == 1
    assert page.locator('button[role=tab][aria-selected="true"]').count() == 1
    assert [t.get_attribute("tabindex") for t in page.locator("button[role=tab]").all()].count("0") == 1
    assert page.locator("#tab-coverage").get_attribute("tabindex") == "0"
    unselected = page.locator('button[role=tab][aria-selected="false"]')
    assert unselected.count() == len(ALL_TABS) - 1, "선택되지 않은 탭이 없으면 아래 단언이 빈 목록으로 통과한다"
    assert all(t.get_attribute("tabindex") == "-1" for t in unselected.all())
    for tab_id in ALL_TABS:
        tab = page.locator(f"#tab-{tab_id}")
        panel = page.locator(f"#panel-{tab_id}")
        assert tab.get_attribute("role") == "tab" and tab.get_attribute("aria-controls") == f"panel-{tab_id}"
        assert panel.get_attribute("role") == "tabpanel" and panel.get_attribute("aria-labelledby") == f"tab-{tab_id}"
    page2 = page_of(proj + PET + "#quality")
    assert visible_panel(page2) == "panel-quality" and selected_tab(page2) == "quality"
    page2.locator("#tab-quality").focus()
    page2.keyboard.press("ArrowRight")
    assert selected_tab(page2) == "generation" and visible_panel(page2) == "panel-generation"
    assert page2.evaluate("document.activeElement.id") == "tab-generation" and page2.url.endswith("#generation")
    page2.keyboard.press("ArrowLeft")
    page2.keyboard.press("ArrowLeft")
    assert selected_tab(page2) == "hotspot"
    page2.locator("#tab-overview").focus()
    page2.keyboard.press("ArrowLeft")
    assert selected_tab(page2) == "runs"
    page2.keyboard.press("ArrowRight")
    assert selected_tab(page2) == "overview"
    page2.keyboard.press("End")
    assert selected_tab(page2) == "runs"
    page2.keyboard.press("Home")
    assert selected_tab(page2) == "overview" and page2.evaluate("document.activeElement.id") == "tab-overview"


def test_unknown_hash_opens_first_tab(proj, page_of):
    assert visible_panel(page_of(proj + PET + "#nope")) == "panel-overview"
    assert visible_panel(page_of(proj + PLAIN + "#coverage")) == "panel-overview"     # 보이지 않는 탭
    assert visible_panel(page_of(proj + PET)) == "panel-overview"


def test_tab_link_inside_panel_selects_tab(proj, page_of):
    page = page_of(proj + PET)
    page.click('#panel-overview a[data-tab-link="hotspot"]')
    assert visible_panel(page) == "panel-hotspot" and page.url.endswith("#hotspot")


# --- REQ-116 스크립트 없는 과제 페이지, REQ-117 읽는 법 ----------------------------------------------

def test_req116_without_javascript(proj, page_of):
    page = page_of(proj + PET, javascript=False)
    panels = page.locator("section[role=tabpanel]")
    assert [panels.nth(i).get_attribute("id") for i in range(panels.count())] == [f"panel-{t}" for t in ALL_TABS]
    for i in range(panels.count()):
        assert panels.nth(i).is_visible(), panels.nth(i).get_attribute("id")
    assert kpi(page, "overview", "coverage.line") == "41.5%"
    assert page.locator("#trend-table tbody tr").count() == 5
    assert page.locator('#panel-trend figure.trend svg').count() == 10
    assert page.locator("table#runs tr[data-run]").count() == 5
    assert page.locator("#stage-detail .stage-item").count() == 14
    assert all(item.is_visible() for item in page.locator("#stage-detail .stage-item").all())
    plain = page_of(proj + PLAIN, javascript=False)
    assert [p.get_attribute("id") for p in plain.locator("section[role=tabpanel]").all()] == \
        ["panel-overview", "panel-trend", "panel-quality"]


def test_req117_one_guide_per_panel(proj, page_of):
    for path, expected in ((PET, len(ALL_TABS)), (PLAIN, 3), (MANY, len(ALL_TABS) - 1)):
        page = page_of(proj + path, javascript=False)
        panels = page.locator("section[role=tabpanel]").all()
        assert len(panels) == expected, path
        for panel in panels:
            guides = panel.locator(".tab-guide")
            assert guides.count() == 1, (path, panel.get_attribute("id"))
            assert guides.inner_text().startswith("이 탭 읽는 법"), (path, panel.get_attribute("id"))
    trend_guide = page_of(proj + PET).inner_text("#panel-trend .tab-guide")
    assert trend_guide.endswith("점을 누르면 그 실행으로 갑니다.")
    assert page_of(proj + PLAIN).inner_text("#panel-trend .tab-guide").endswith(
        "점 하나가 하루치 수집이고, 값이 없는 날에는 선이 끊깁니다.")


# --- REQ-118 탭 내용 ----------------------------------------------------------------------------

def test_req118_overview(proj, page_of):
    page = page_of(proj + PET)
    assert page.locator("#panel-overview .kpi[data-metric]").count() == 5
    assert kpi(page, "overview", "tests.passRate") == "100.0%"
    assert kpi(page, "overview", "coverage.line") == "41.5%"
    assert kpi(page, "overview", "sonar.gate") == "통과"
    assert kpi(page, "overview", "sonar.vulnerabilities") == "0"
    assert kpi(page, "overview", "tia.selectedRatio") == "68 / 134"
    hot = page.locator("#panel-overview ol.hot li")
    assert hot.count() == 5 and PROJ_PET_TOP10[0]["name"] in hot.first.inner_text()
    impact = page.locator("#panel-overview .impact")
    assert (impact.get_attribute("data-selected"), impact.get_attribute("data-indexed")) == ("68", "134")
    strip = page.locator("#stage-strip button[data-stage]")
    assert strip.count() == 14
    page.click('#stage-strip button[data-stage="S07"]')
    detail = page.locator("#stage-detail .stage-item:visible")
    assert detail.count() == 1 and "S07 생성 E2E 실행" in detail.inner_text() and "4분 19초" in detail.inner_text()
    page.click('#stage-strip button[data-stage="S08"]')
    assert "S08 커버리지 집계" in page.inner_text("#stage-detail .stage-item:visible")
    reports = {a.get_attribute("data-report") for a in page.locator("#panel-overview .links a.report-link").all()}
    assert reports == {"coverage/coverage.html", "hotspot/hotspots.html", "tia/tia.html", "sonar/sonar.html",
                       "compare/compare.html", "ontology/jqa.html", "ontology/owl.html"}


def test_req118_other_tabs(proj, page_of):
    page = page_of(proj + PET, javascript=False)
    gens = page.locator("table#gens tr[data-gen]")
    assert [g.get_attribute("data-gen") for g in gens.all()] == ["base-r1", "jqa-r1"]
    for row in gens.all():
        assert row.locator('td[data-col="passed"]').inner_text() == "21"
        assert row.locator('td[data-col="failed"]').inner_text() == "10"
    suites = page.locator("#panel-coverage tr[data-suite]")
    assert [s.get_attribute("data-suite") for s in suites.all()] == ["blackbox", "e2e-base-r1", "e2e-jqa-r1"]
    blackbox = page.locator('#panel-coverage tr[data-suite="blackbox"]')
    assert blackbox.locator('td[data-col="line"]').inner_text() == "41.5%"
    assert blackbox.locator('td[data-col="aggregate"]').inner_text() == "60.9%"
    assert blackbox.locator('td[data-col="tc"]').inner_text() == "35"
    assert page.locator('#panel-coverage tr[data-suite="e2e-jqa-r1"] td[data-col="aggregate"]').inner_text() == "39.2%"
    hot = page.locator("#panel-hotspot ol.hot li")
    assert hot.count() == 10 and PROJ_PET_TOP10[9]["name"] in hot.nth(9).inner_text()
    assert page.inner_text('table#issues td[data-type="CODE_SMELL"][data-sev="MINOR"]') == "3"
    assert page.inner_text('table#issues td[data-type="VULNERABILITY"][data-sev="BLOCKER"]') == "0"
    assert page.locator("table#issues td[data-type][data-sev]").count() == 15
    assert kpi(page, "quality", "sonar.gate") == "통과" and kpi(page, "quality", "sonar.codeSmells") == "37"
    assert "신뢰성 등급 C" in page.inner_text('#panel-quality .kpi[data-metric="sonar.bugs"]')
    verdict = page.inner_text("#panel-generation .verdict-title")
    assert "불성립" in verdict and "효과 있음" in verdict
    arms = page.locator("table#arms tr[data-arm]")
    assert [a.get_attribute("data-arm") for a in arms.all()] == ["base", "jqa", "owl"]
    base = page.locator('table#arms tr[data-arm="base"]')
    assert base.locator('td[data-col="passed"]').inner_text() == "60.0%"
    assert "bad" in base.locator('td[data-col="passed"]').get_attribute("class")
    assert "ok" in page.locator('table#arms tr[data-arm="jqa"] td[data-col="passed"]').get_attribute("class")
    assert page.locator('table#arms tr[data-arm="owl"] td[data-col="passed"]').inner_text() == "—"
    runs = page.locator("table#runs tr[data-run]")
    assert [r.get_attribute("data-run") for r in runs.all()] == list(reversed(PET_RUN_IDS))


def test_req118_report_links_resolve(proj, page_of):
    page = page_of(proj + PET, javascript=False)
    for tab_id in ALL_TABS:
        if tab_id == "trend":
            continue
        assert page.locator(f"#panel-{tab_id} a.report-link").count() >= 1, tab_id
    hrefs = {a.get_attribute("href") for a in page.locator("a.report-link").all()}
    assert hrefs
    for href in sorted(hrefs):
        assert not href.startswith(("http:", "https:", "/")), href
        assert http_status(proj + "projects/pet/" + href) == 200, href


def test_all_relative_links_resolve(proj, page_of):
    for path in (PET, PLAIN, MANY):
        page = page_of(proj + path, javascript=False)
        base = proj + path.rsplit("/", 1)[0] + "/"
        hrefs = {a.get_attribute("href") for a in page.locator("a[href]").all()}
        for href in sorted(hrefs):
            if href.startswith(("http:", "https:", "#")):
                continue
            assert http_status(base + href) == 200, (path, href)


def test_absent_report_has_no_link(tmp_path, page_of):
    """최신 run에 리포트가 없는 탭은 죽은 링크 대신 링크를 두지 않는다(그리고 데이터가 없는 탭은 나오지 않는다)."""
    site = make_site(tmp_path, runs={"solo": [RUN_A]})
    rebuild_site(site, dashboard_config.empty())
    with serve(site) as url:
        page = page_of(url + "projects/solo/index.html", javascript=False)
        assert page.locator("a.report-link").count() == 0
        tabs = [t.get_attribute("data-tab") for t in page.locator("button[role=tab]").all()]
        assert tabs == ["overview", "trend", "tests", "coverage", "hotspot", "quality", "runs"]   # 비교 리포트 없음
        assert page.locator("table#runs tr[data-run] a").count() == 0      # run 페이지가 없으면 링크도 없다
        assert page.locator("#panel-trend a.pt").count() == 0
        for a in page.locator("a[href]").all():
            href = a.get_attribute("href")
            if not href.startswith(("#", "http")):
                assert http_status(url + "projects/solo/" + href) == 200, href


# --- REQ-119 파이프라인 없는 과제 ---------------------------------------------------------------------

def test_req119_snapshot_only_project(proj, page_of):
    page = page_of(proj + PLAIN)
    assert [t.get_attribute("data-tab") for t in page.locator("button[role=tab]").all()] == ["overview", "trend", "quality"]
    values = tuple(kpi(page, "overview", m) for m in
                   ("ci.successRate", "sonar.gate", "sonar.coverage", "sonar.vulnerabilities", "sonar.bugs"))
    assert values == ("90.0%", "통과", "91.6%", "0", "0")
    assert page.locator("#panel-overview .hist i").count() == 20
    assert "18 / 20회" in page.inner_text('#panel-overview .kpi[data-metric="ci.successRate"]')
    assert page.locator("#panel-trend figure.trend").count() == 4
    assert page.locator("table#issues").count() == 0 and kpi(page, "quality", "sonar.gate") == "통과"


# --- REQ-120, 121, 123 추이 --------------------------------------------------------------------------

def test_req120_trend_points_gaps_cap(proj, page_of):
    page = page_of(proj + PET + "#trend")
    fig = page.locator('figure.trend[data-metric="tests.passRate"]')
    assert fig.locator(".pt").count() == 4 and fig.locator("polyline.ln").count() == 2
    assert page.locator('figure.trend[data-metric="coverage.line"] .pt').count() == 5
    many = page_of(proj + MANY + "#trend")
    assert many.locator('figure.trend[data-metric="coverage.line"] .pt').count() == 30
    assert many.locator("#trend-table tbody tr").count() == 31
    assert many.locator("#trend-table tbody tr").first.get_attribute("data-id") == PROJ_MANY_RUNS[-1]["runId"]


def test_req121_point_tooltip_highlight_links(proj, page_of):
    page = page_of(proj + PET + "#trend")
    latest = REPORTS_RUN_ID
    point = page.locator(f'figure.trend[data-metric="tests.passRate"] .pt[data-id="{latest}"]')
    point.focus()
    tip = page.locator("#trend-tip")
    assert tip.is_visible() and latest in tip.inner_text() and "100.0%" in tip.inner_text()
    other = page.locator(f'figure.trend[data-metric="coverage.line"] .pt[data-id="{latest}"]')
    assert "hl" in other.get_attribute("class")
    assert "hl" not in page.locator(f'figure.trend[data-metric="coverage.line"] .pt[data-id="{PET_RUN_IDS[0]}"]').get_attribute("class")
    assert page.locator(".pt.hl").count() == page.locator(f'.pt[data-id="{latest}"]').count()
    href = point.get_attribute("href")
    assert href == f"../../suts/pet/runs/{latest}/index.html" and http_status(proj + "projects/pet/" + href) == 200
    page.locator(f'figure.trend[data-metric="coverage.line"] .pt[data-id="{PET_RUN_IDS[0]}"]').hover()
    assert PET_RUN_IDS[0] in tip.inner_text() and "38.0%" in tip.inner_text()
    assert page.locator(".pt.hl").count() == page.locator(f'.pt[data-id="{PET_RUN_IDS[0]}"]').count()
    plain = page_of(proj + PLAIN + "#trend")
    snap_point = plain.locator('figure.trend[data-metric="ci.successRate"] .pt[data-id="20261122"]')
    assert snap_point.evaluate("element => element.tagName.toLowerCase()") == "g"
    assert snap_point.get_attribute("href") is None
    snap_point.focus()
    text = plain.inner_text("#trend-tip")
    assert "2026-11-22" in text and "90.0%" in text


def test_req123_table_matches_series(proj, proj_dir, page_of):
    for name in ("pet", "plain", "many"):
        doc = json.loads((proj_dir / "projects" / name / "series.json").read_text())
        page = page_of(proj + f"projects/{name}/index.html#trend")
        rows = page.locator("#trend-table tbody tr")
        assert rows.count() == len(doc["points"])
        header = [th.get_attribute("data-metric") for th in page.locator("#trend-table thead th[data-metric]").all()]
        assert header == doc["metrics"]
        cells = page.evaluate("""() => Array.from(document.querySelectorAll('#trend-table tbody tr')).map(tr =>
            [tr.dataset.id, Object.fromEntries(Array.from(tr.querySelectorAll('td[data-metric]')).map(td =>
                [td.dataset.metric, td.textContent.trim()]))])""")
        by_id = dict(cells)
        for point in doc["points"]:
            for metric in doc["metrics"]:
                assert by_id[point["id"]][metric] == format_value(metric, point["values"][metric]), (name, point["id"], metric)
    pet = json.loads((proj_dir / "projects/pet/series.json").read_text())
    third = next(p for p in pet["points"] if p["id"] == PET_RUN_IDS[2])
    assert third["values"]["tests.passRate"] is None
    page = page_of(proj + PET + "#trend")
    assert page.inner_text(f'#trend-table tr[data-id="{PET_RUN_IDS[2]}"] td[data-metric="tests.passRate"]') == "—"


# --- REQ-084 결론 문장(화면), 상태 표시 ------------------------------------------------------------------

def test_req084_headline_rendered(proj, page_of):
    assert page_of(proj + PET).inner_text("#headline") == "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 41.5%입니다"
    many = page_of(proj + MANY)
    assert many.inner_text("#headline") == "주의: Sonar 취약점 18건"
    assert many.inner_text(".top .st").strip() == "주의"
    assert page_of(proj + PLAIN).inner_text("#headline") == "판정 규칙에 걸린 항목이 없습니다"


def test_stale_project_shows_collect_failure(tmp_path, page_of):
    site = proj_site(tmp_path)
    write_collect_state(site, "20261123", ["plain"])
    rebuild_site(site)
    with serve(site) as url:
        page = page_of(url + PLAIN)
        assert "수집 실패 · 2026-11-22" in page.inner_text(".top")
        assert "수집 실패" not in page_of(url + PET).inner_text(".top")


# --- REQ-108 SUT 안내 페이지 ---------------------------------------------------------------------------

def _landing(site: Path, sut: str) -> tuple[str, str]:
    html = (site / "suts" / sut / "index.html").read_text()
    refresh = re.search(r'<meta http-equiv="refresh" content="0; url=([^"]+)">', html).group(1)
    link = re.search(r'<a id="to-project" href="([^"]+)"', html).group(1)
    return refresh, link


def test_req108_sut_landing(proj, proj_dir, tmp_path, page_of):
    for sut in ("pet", "many"):
        refresh, link = _landing(proj_dir, sut)
        assert refresh == link == f"../../projects/{sut}/index.html"
        assert http_status(proj + f"suts/{sut}/" + link) == 200
    page = page_of(proj + "suts/pet/index.html")
    page.wait_for_url("**/projects/pet/index.html")
    assert page.inner_text("#headline").startswith("기존 테스트는 모두 통과")
    # 과제 이름과 SUT 이름이 다른 설정 과제: 안내 페이지는 SUT 이름이 아니라 그 SUT를 가진 과제로 보낸다
    named = make_site(tmp_path / "named", runs={"pet2": [RUN_A]},
                      config={"schema": 1, "projects": [{"name": "petshop", "sut": "pet2"}]})
    rebuild_site(named)
    refresh, link = _landing(named, "pet2")
    assert refresh == link == "../../projects/petshop/index.html"
    assert not (named / "projects/pet2").exists()
    with serve(named) as url:
        assert http_status(url + "suts/pet2/" + link) == 200
    site = make_site(tmp_path, runs={"solo": [RUN_A]})          # 설정에 없는 SUT -> 암묵 과제
    rebuild_site(site, dashboard_config.empty())
    refresh, link = _landing(site, "solo")
    assert refresh == link == "../../projects/solo/index.html"
    with serve(site) as url:
        assert http_status(url + "suts/solo/" + link) == 200


def test_sut_landing_without_drawn_project_points_home(tmp_path):
    """이어진 과제가 그려지지 않으면(비공개 등) 안내 페이지는 과제 이름을 쓰지 않고 첫 화면으로 보낸다."""
    site = make_site(tmp_path, runs={"sec": [RUN_A]},
                     snapshots={"hidden": [snap(visibility="private")]},
                     config={"schema": 1, "projects": [{"name": "hidden", "repo": "o/hidden", "sut": "sec"}]})
    rebuild_site(site)
    html = (site / "suts/sec/index.html").read_text()
    assert "hidden" not in html and 'url=../../index.html' in html
    assert not (site / "projects/hidden/index.html").exists()


# --- REQ-080 설정으로 화면 구성 바꾸기 ------------------------------------------------------------------

def _status_section(**changes) -> dict:
    status = json.loads(json.dumps(dashboard_config.empty().status))
    status.update(changes)
    return status


def test_req080_tabs_and_trend_from_config(tmp_path, page_of):
    project = json.loads(json.dumps(dashboard_config.empty().project))
    project["tabs"] = ["overview", "tests", "trend", "coverage", "hotspot", "quality", "runs"]   # generation 빼고 둘 바꿈
    project["trend"] = {"run": ["coverage.line", "run.durationSec"], "snapshot": ["sonar.coverage"]}
    site = proj_site(tmp_path, project=project)
    with serve(site) as url:
        page = page_of(url + PET)
        assert [t.get_attribute("data-tab") for t in page.locator("button[role=tab]").all()] == project["tabs"]
        assert [p.get_attribute("id") for p in page.locator("section[role=tabpanel]").all()] == \
            [f"panel-{t}" for t in project["tabs"]]
        assert [f.get_attribute("data-metric") for f in page.locator("figure.trend").all()] == ["coverage.line", "run.durationSec"]
        plain = page_of(url + PLAIN)
        assert [f.get_attribute("data-metric") for f in plain.locator("figure.trend").all()] == ["sonar.coverage"]


def test_req080_home_columns_and_summary_from_config(tmp_path, page_of):
    home = json.loads(json.dumps(dashboard_config.empty().home))
    home["columns"] = [c for c in home["columns"] if c != "sonar.issues"]
    home["summary"] = ["status.noneCount", "ci.successRateAll"]
    site = proj_site(tmp_path, home=home)
    with serve(site) as url:
        page = page_of(url)
        assert page.locator('#projects th[data-col="sonar.issues"]').count() == 0
        assert [th.get_attribute("data-col") for th in page.locator("#projects thead th").all()] == home["columns"]
        assert [s.get_attribute("data-metric") for s in page.locator("#summary .sum-item").all()] == home["summary"]


def test_req080_status_labels_and_order_from_config(tmp_path, page_of):
    rules = [{"level": "crit", "when": {"metric": "sonar.vulnerabilities", "op": "gt", "value": 10}, "reason": "취약점 과다"},
             {"level": "warn", "when": {"metric": "ci.successRate", "op": "le", "value": 0.9}, "reason": "CI 불안정"}]
    labels = {"crit": "심각", "warn": "주의", "good": "양호", "none": "측정 없음"}
    site = proj_site(tmp_path / "a", status=_status_section(labels=labels, rules=rules))
    assert (status_of(site, "many"), status_of(site, "plain")) == ("crit", "warn")
    with serve(site) as url:
        home = page_of(url)
        assert home.inner_text('tr.proj[data-name="many"] .st').strip() == "심각"
        names = [r.get_attribute("data-name") for r in home.locator("tr.proj").all()]
        assert names.index("many") < names.index("plain")
        project = page_of(url + MANY)
        assert project.inner_text(".top .st").strip() == "심각" and project.inner_text("#headline") == "심각: 취약점 과다"
    site = proj_site(tmp_path / "b", status=_status_section(labels=labels, rules=rules, order=["warn", "crit", "none", "good"]))
    with serve(site) as url:
        names = [r.get_attribute("data-name") for r in page_of(url).locator("tr.proj").all()]
        assert names.index("plain") < names.index("many")


def test_req080_none_all_missing_from_config(tmp_path, page_of):
    extra = {"ci-only": [snap(ci_runs=10, sonar=None)]}
    site = proj_site(tmp_path / "a", extra_plain=extra)
    assert status_of(site, "ci-only") == "good"
    site = proj_site(tmp_path / "b", extra_plain=extra, status=_status_section(none={"allMissing": ["sonar.gate"]}))
    assert status_of(site, "ci-only") == "none"
    with serve(site) as url:
        page = page_of(url + "projects/ci-only/index.html")
        assert page.inner_text("#headline") == "측정된 지표가 없습니다"
        assert page.inner_text(".top .st").strip() == "측정 없음"


# --- 이스케이프, 멱등, 외부 요청 --------------------------------------------------------------------------

def test_project_page_escapes_text(tmp_path, page_of):
    evil = '<img src=x onerror=alert(1)> & "q" </script>'
    site = make_site(tmp_path, snapshots={"x": [snap(description=evil)]},
                     config={"schema": 1, "projects": [{"name": "x", "repo": "o/x"}]})
    rebuild_site(site)
    raw = (site / "projects/x/index.html").read_text()
    assert "<img src=x" not in raw and raw.count("</script>") == raw.count("<script")
    with serve(site) as url:
        page = page_of(url + "projects/x/index.html")
        assert page.locator("img").count() == 0 and evil in page.inner_text("body")
        data = json.loads(page.inner_text("#project-data"))
        assert data["project"]["name"] == "x"


def test_project_pages_idempotent(tmp_path):
    site = proj_site(tmp_path)

    def tree():
        return {p.relative_to(site).as_posix(): p.read_bytes() for p in sorted((site / "projects").rglob("*"))
                if p.is_file() and p.name in ("index.html", "series.json")}
    first = tree()
    assert {"projects/pet/index.html", "projects/pet/series.json", "projects/plain/index.html",
            "projects/many/series.json"} <= set(first)
    rebuild_site(site)
    assert tree() == first
    landing = (site / "suts/pet/index.html").read_bytes()
    rebuild_site(site)
    assert (site / "suts/pet/index.html").read_bytes() == landing


def test_project_page_has_no_external_requests(proj, page_of):
    for path in (PET, PLAIN):
        page = page_of(proj + path)
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        page.reload()
        page.wait_for_load_state("load")
        assert requests and all(url.startswith(proj) for url in requests), requests
        assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"), path
        narrow = page_of(proj + path, width=390)
        assert not narrow.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"), path


def test_overview_tab_link_only_when_target_tab_is_rendered(tmp_path, proj_dir):
    """'한눈에'의 "위험 지점 전체 →"는 위험 지점 탭이 그려질 때만 있다(없는 구역을 가리키지 않는다)."""
    assert 'href="#panel-hotspot"' in (proj_dir / PET).read_text()
    project = json.loads(json.dumps(dashboard_config.empty().project))
    project["tabs"] = ["overview", "trend", "runs"]
    site = proj_site(tmp_path, project=project)
    html = (site / PET).read_text()
    assert 'id="panel-overview"' in html and 'id="panel-hotspot"' not in html
    assert "#panel-hotspot" not in html and 'data-tab-link="hotspot"' not in html
