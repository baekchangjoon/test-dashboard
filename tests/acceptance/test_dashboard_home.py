"""첫 화면 수용 테스트(Task 9).

REQ-089(화면), REQ-090(화면), REQ-104, REQ-109, REQ-110, REQ-111, REQ-112, REQ-113, REQ-114, REQ-142.
고정 사이트(`home_site`)는 모듈에서 한 번 만들어 한 번 띄운다.
"""
import json
from urllib.request import urlopen

import pytest

from td import dashboard_config
from td.dashboard_config import cell_text
from td.site import index
from dashboard_fixtures import (CI_FAILED_REASON, SONAR_FAILED_REASON, all_good_site, cfg_with, home_site, load_cfg, make_site,
                                open_page, rebuild_site, serve, snap, sonar_failed_site)

HOME_ORDER = ["a-crit", "b-crit", "zero-cov", "no-data", "no-sonar", "pet"]


@pytest.fixture(scope="module")
def home_dir(tmp_path_factory):
    return home_site(tmp_path_factory.mktemp("home"))


@pytest.fixture(scope="module")
def home(home_dir):
    with serve(home_dir) as url:
        yield url


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


def cell(page, name: str, col: str) -> str:
    return page.inner_text(f'tr.proj[data-name="{name}"] td[data-col="{col}"]').strip()


def visible_names(page) -> list[str]:
    return page.eval_on_selector_all("tr.proj", "rows => rows.filter(r => !r.hidden).map(r => r.dataset.name)")


# --- REQ-109 ---------------------------------------------------------------------------------

def test_req109_rows_order_headline(home, page_of, tmp_path):
    page = page_of(home)
    assert [r.get_attribute("data-name") for r in page.locator("tr.proj").all()] == HOME_ORDER
    assert page.inner_text("#headline") == "과제 6개 중 2개가 위험, 1개가 주의입니다"
    assert [r.get_attribute("data-status") for r in page.locator("tr.proj").all()] == [
        "crit", "crit", "warn", "none", "good", "good"]
    with serve(all_good_site(tmp_path)) as good:
        assert page_of(good).inner_text("#headline") == "과제 2개 중 문제 있는 과제가 없습니다"


def test_req109_headline_omits_zero_side(tmp_path):
    site = make_site(tmp_path, snapshots={"w": [snap(ci_runs=10, sonar={"gate": "OK", "vulnerabilities": 3})],
                                          "g": [snap(ci_runs=10)]}, config=cfg_with(plain=["w", "g"]))
    rebuild_site(site)
    html = (site / "index.html").read_text()
    assert "과제 2개 중 " in html and "1개가 주의</i>입니다" in html and "위험" not in html.split('id="headline"')[1].split("</h1>")[0]


# --- REQ-110 ---------------------------------------------------------------------------------

def test_req110_filter_search_sort(home, page_of):
    page = page_of(home)
    crit = page.locator('button[data-filter="crit"]')
    crit.click()
    assert crit.get_attribute("aria-pressed") == "true"
    assert page.locator('button[data-filter="all"]').get_attribute("aria-pressed") == "false"
    assert visible_names(page) == ["a-crit", "b-crit"]
    page.locator('button[data-filter="all"]').click()
    assert visible_names(page) == HOME_ORDER
    page.fill("input#proj-search", "SON")
    assert visible_names(page) == ["no-sonar"]
    page.fill("input#proj-search", "")
    assert visible_names(page) == HOME_ORDER

    # CI 성공률: a-crit 1.0, b-crit 0.75, zero-cov 1.0, no-sonar 1.0, no-data·pet 값 없음
    ci_button = page.locator('th button[data-sort="ci.successRate"]')
    ci_button.click()
    th = page.locator('th:has(button[data-sort="ci.successRate"])')
    assert th.get_attribute("aria-sort") == "ascending"
    ascending = visible_names(page)
    assert ascending == ["b-crit", "a-crit", "no-sonar", "zero-cov", "no-data", "pet"]
    ci_button.click()
    assert th.get_attribute("aria-sort") == "descending"
    descending = visible_names(page)
    assert descending == ["a-crit", "no-sonar", "zero-cov", "b-crit", "no-data", "pet"]
    assert page.locator("th[aria-sort]").count() == 1

    # 커버리지: 값 없는 행(no-data, no-sonar, pet은 run에서 57.1)… 어느 방향이든 뒤
    cov_button = page.locator('th button[data-sort="sonar.coverage"]')
    cov_button.click()
    up = visible_names(page)
    cov_button.click()
    down = visible_names(page)
    for order in (up, down):
        assert set(order[-2:]) == {"no-data", "no-sonar"}, order
    assert up[0] == "zero-cov" and down[0] == "b-crit"

    # 이름 정렬
    page.locator('th button[data-sort="project"]').click()
    assert visible_names(page) == sorted(HOME_ORDER)


def test_req110_filter_keeps_sort_and_hides_detail(home, page_of):
    page = page_of(home)
    page.locator('tr.proj[data-name="no-sonar"]').click()
    assert page.locator("tr.proj-detail").count() == 1
    page.locator('button[data-filter="crit"]').click()
    assert page.locator("tr.proj-detail").count() == 0
    page.fill("input#proj-search", "zzz")
    assert visible_names(page) == [] and page.locator("#no-match").is_visible()


# --- REQ-111 ---------------------------------------------------------------------------------

def test_req111_inline_expand(home, page_of):
    page = page_of(home)
    row = page.locator('tr.proj[data-name="b-crit"]')
    row.click()
    assert row.get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.querySelector('tr.proj[data-name=\"b-crit\"]').nextElementSibling.className") == "proj-detail"
    assert "기본 브랜치의 최근 CI 실패" in page.inner_text("tr.proj-detail .detail-reasons")
    assert page.locator("tr.proj-detail a.open-project").get_attribute("href") == "projects/b-crit/index.html"
    assert page.url == home
    page.locator('tr.proj[data-name="pet"]').click()
    assert page.locator("tr.proj-detail").count() == 1 and row.get_attribute("aria-expanded") == "false"
    assert page.locator('tr.proj[data-name="pet"]').get_attribute("aria-expanded") == "true"

    def kpi(metric):
        return page.inner_text(f'tr.proj-detail .detail-kpi[data-metric="{metric}"]')
    assert "100.0%" in kpi("tests.passRate") and "41.5%" in kpi("coverage.line")
    assert "통과" in kpi("sonar.gate") and "Owner.getPet" in kpi("hotspot.topName")
    page.locator('tr.proj[data-name="pet"]').click()
    assert page.locator("tr.proj-detail").count() == 0
    row.focus()
    page.keyboard.press("Enter")
    assert page.locator("tr.proj-detail").count() == 1 and row.get_attribute("aria-expanded") == "true"
    page.keyboard.press("Enter")
    assert page.locator("tr.proj-detail").count() == 0


def test_req111_name_link_expands_with_script(home, page_of):
    page = page_of(home)
    page.locator('tr.proj[data-name="a-crit"] a.proj-link').click()
    assert page.url == home and page.locator("tr.proj-detail").count() == 1
    page.locator("tr.proj-detail button.detail-close").click()
    assert page.locator("tr.proj-detail").count() == 0
    assert page.locator('tr.proj[data-name="a-crit"]').get_attribute("aria-expanded") == "false"


# --- REQ-112 ---------------------------------------------------------------------------------

def test_req112_without_javascript(home, page_of):
    page = page_of(home, javascript=False)
    rows = page.locator("tr.proj")
    assert rows.count() == 6
    for name in HOME_ORDER:
        row = page.locator(f'tr.proj[data-name="{name}"]')
        assert row.is_visible()
        assert row.locator("a.proj-link").get_attribute("href") == f"projects/{name}/index.html"
        assert row.locator(".st").inner_text().strip() in ("위험", "주의", "양호", "측정 없음")
    assert "Sonar 품질 게이트 실패" in cell(page, "a-crit", "why")
    assert cell(page, "a-crit", "ci.successRate").startswith("100.0%")
    assert page.locator("#summary .sum-item b").first.inner_text() == "97.5%"
    assert page.locator("tr.proj-detail").count() == 0


# --- REQ-113, REQ-090(화면) --------------------------------------------------------------------

def test_req113_missing_not_zero(home, page_of, tmp_path):
    page = page_of(home)
    assert cell(page, "no-sonar", "sonar.gate") == "연결 없음" and cell(page, "no-sonar", "sonar.coverage") == "—"
    assert cell(page, "no-sonar", "sonar.issues") == "—"
    assert cell(page, "no-data", "ci.successRate") == "—" and cell(page, "no-data", "ci.history") == "—"
    assert cell(page, "pet", "ci.successRate") == "—"
    assert cell(page, "zero-cov", "sonar.coverage") == "0.0%"
    for name in ("no-sonar", "no-data"):
        for col in ("ci.successRate", "sonar.gate", "sonar.coverage", "sonar.issues"):
            assert cell(page, name, col) not in ("0", "0%", "0.0%"), (name, col)
    with serve(sonar_failed_site(tmp_path)) as url:
        other = page_of(url)
        assert cell(other, "no-ci", "ci.successRate") == "—" and cell(other, "flaky", "sonar.gate") == "측정 없음"
        assert cell(other, "flaky", "sonar.coverage") == "측정 없음"


def test_req090_failed_source_cell_title(tmp_path, page_of):
    with serve(sonar_failed_site(tmp_path)) as url:
        page = page_of(url)
        title = page.get_attribute('tr.proj[data-name="flaky"] td[data-col="sonar.gate"]', "title")
        assert SONAR_FAILED_REASON in title


def test_req113_failed_ci_source_cells(tmp_path, page_of):
    with serve(sonar_failed_site(tmp_path)) as url:
        page = page_of(url)
        for col in ("ci.successRate", "ci.history"):
            assert cell(page, "ci-broken", col) == "측정 없음", col
            title = page.get_attribute(f'tr.proj[data-name="ci-broken"] td[data-col="{col}"]', "title")
            assert title and CI_FAILED_REASON in title, col
        assert cell(page, "no-ci", "ci.history") == "—"


def test_ci_sub_line_omitted_without_successes(tmp_path):
    ci = {"runs": 5, "successes": None, "failures": None, "successRate": None, "lastFailed": False,
          "failedChecks": 0, "history": []}
    site = make_site(tmp_path, snapshots={"x": [snap(ci=ci)]}, config=cfg_with(plain="x"))
    rebuild_site(site)
    html = (site / "index.html").read_text()
    row = html.split('<tr class="proj" data-name="x"')[1].split("</tr>")[0]
    ci_cell = row.split('data-col="ci.successRate"')[1].split("</td>")[0]
    assert "회" not in ci_cell and "0 / " not in ci_cell, ci_cell


def test_cell_text_rules():
    base = {"values": {}, "sources": {"ci": None, "sonar": None}, "problems": [], "ciHistory": []}
    assert cell_text("sonar.gate", {**base, "values": {"sonar.gate": "ERROR"}}) == ("실패", "")
    assert cell_text("sonar.gate", {**base, "sources": {"ci": "ok", "sonar": "absent"}})[0] == "연결 없음"
    assert cell_text("sonar.coverage", {**base, "sources": {"ci": "ok", "sonar": "absent"}})[0] == "—"
    failed = {**base, "sources": {"ci": "failed", "sonar": "ok"}, "problems": ["ci: 실행 목록을 읽지 못했다"]}
    assert cell_text("ci.successRate", failed) == ("측정 없음", "ci: 실행 목록을 읽지 못했다")
    assert cell_text("sonar.coverage", {**base, "values": {"sonar.coverage": 0.0}})[0] == "0.0%"
    assert cell_text("ci.successRate", base)[0] == "—"
    assert cell_text("repo.pushedAt", {**base, "values": {"repo.pushedAt": "2026-11-20T05:05:15Z"}})[0] == "2026-11-20"
    assert cell_text("sonar.issues", {**base, "values": {"sonar.bugs": 3, "sonar.vulnerabilities": 0}})[0] == "3 · 0"


# --- REQ-089(화면) ------------------------------------------------------------------------------

def test_req089_excluded_project_absent_from_site(tmp_path):
    site = make_site(tmp_path, snapshots={"a": [snap()], "secret": [snap(description="internal thing")]},
                     config=cfg_with(plain=["a", "secret"]))
    index.rebuild(site, "", load_cfg(site), exclude=frozenset({"secret"}))
    blob = "".join(p.read_text(errors="ignore") for p in site.rglob("*")
                   if p.is_file() and "projects/secret/" not in p.as_posix())
    assert "secret" not in blob and "internal thing" not in blob and '"a"' in (site / "projects.json").read_text()


# --- REQ-104 ---------------------------------------------------------------------------------

def test_req104_projects_json_matches_table(home, home_dir, page_of):
    data = json.loads((home_dir / "projects.json").read_text())
    assert data["schema"] == 1 and [p["name"] for p in data["projects"]] == HOME_ORDER
    by_name = {p["name"]: p for p in data["projects"]}
    for item in data["projects"]:
        assert set(item) >= {"name", "repo", "sut", "pipeline", "implicit", "status", "values", "headline", "href",
                             "stale", "problems"}
        assert set(item["status"]) == {"level", "label", "reasons", "partial"}
        assert item["href"] == f"projects/{item['name']}/index.html"
    pet = by_name["pet"]["values"]
    assert (pet["tests.passRate"], pet["coverage.line"], pet["sonar.gate"], pet["hotspot.topName"]) == (
        1.0, 0.4152, "OK", "Owner.getPet")
    assert by_name["pet"]["pipeline"] and not by_name["a-crit"]["pipeline"]
    assert by_name["no-sonar"]["status"]["partial"] and not by_name["a-crit"]["status"]["partial"]
    assert by_name["a-crit"]["status"]["reasons"] == ["Sonar 품질 게이트 실패", "Sonar 취약점 2건"]
    page = page_of(home)
    island = json.loads(page.inner_text("#projects-data"))
    assert island == data
    for item in data["projects"]:
        row = page.locator(f'tr.proj[data-name="{item["name"]}"]')
        assert row.get_attribute("data-status") == item["status"]["level"]
        assert cell(page, item["name"], "why") == (" · ".join(item["status"]["reasons"]) or "—")
        row.click()
        reasons = page.locator("tr.proj-detail .detail-reasons li").all_inner_texts()
        assert reasons == item["status"]["reasons"], item["name"]
        row.click()


# --- REQ-114 ---------------------------------------------------------------------------------

def test_req114_tags_rules_links(home, home_dir, page_of, tmp_path):
    page = page_of(home)
    assert [r.get_attribute("data-name") for r in page.locator("tr.proj:has(.tag-pipeline)").all()] == ["pet"]
    assert [r.get_attribute("data-name") for r in page.locator("tr.proj:has(.tag-partial)").all()] == ["no-sonar"]
    assert page.inner_text("tr.proj .tag-pipeline").strip() == "파이프라인"
    assert page.inner_text("tr.proj .tag-partial").strip() == "부분 측정"
    rules = page.locator("#rules li").all_inner_texts()
    cfg = load_cfg(home_dir)
    assert rules == dashboard_config.rules_text(cfg)
    assert "주의: CI 실행 수 ≥ 5 그리고 CI 성공률 < 90.0% / Sonar 취약점 > 0" in rules
    assert "0.0%는 커버리지 리포트를 Sonar에 보내지 않는다는 뜻일 수도 있습니다" in page.inner_text("#rules .zero-note")
    assert page.locator('footer a[href$="_test/index.html"]').count() == 1
    assert page.locator('footer a[href$="hosting.html"]').count() == 1
    with serve(all_good_site(tmp_path)) as good:
        assert page_of(good).locator("#rules .zero-note").count() == 0


def test_stale_tag_shows_last_collected_date(tmp_path):
    from dashboard_fixtures import write_collect_state
    site = make_site(tmp_path, snapshots={"a": [snap(date="20261121")]}, config=cfg_with(plain="a"))
    write_collect_state(site, "20261122", ["a"])
    rebuild_site(site)
    html = (site / "index.html").read_text()
    assert 'class="tag tag-stale"' in html and "수집 실패 · 2026-11-21" in html


# --- REQ-142 ---------------------------------------------------------------------------------

def test_req142_summary_counts_history(home, home_dir, page_of):
    page = page_of(home)
    data = json.loads(urlopen(home + "projects.json").read())
    items = page.locator("#summary .sum-item").all()
    assert [i.get_attribute("data-metric") for i in items] == list(load_cfg(home_dir).home["summary"])
    assert [i.locator("b").inner_text() for i in items] == [
        data["summary"][i.get_attribute("data-metric")]["value"] for i in items]
    assert int(page.inner_text('button[data-filter="all"] .count')) == 6
    for level in ("crit", "warn", "good", "none"):
        assert int(page.inner_text(f'button[data-filter="{level}"] .count')) == page.locator(
            f'tr.proj[data-status="{level}"]').count()
    assert page.locator('tr.proj[data-name="b-crit"] .hist i').count() == 4
    assert page.locator('tr.proj[data-name="b-crit"] .hist i.f').count() == 1
    assert page.locator('tr.proj[data-name="zero-cov"] .hist i').count() == 17
    assert page.locator('tr.proj[data-name="zero-cov"] .hist i.f').count() == 0


# --- 특수 문자, 빈 사이트, 멱등 -------------------------------------------------------------------

def test_special_characters_are_escaped(tmp_path, page_of):
    site = make_site(tmp_path, snapshots={"x": [snap(description='<img src=x onerror=alert(1)> & "q" </script>')]},
                     config=cfg_with(plain="x"))
    rebuild_site(site)
    with serve(site) as url:
        page = page_of(url)
        assert page.locator("img").count() == 0 and "<img src=x" in page.inner_text('tr.proj[data-name="x"]')
        island = json.loads(page.inner_text("#projects-data"))
        assert island["projects"][0]["name"] == "x"
        assert island["projects"][0]["values"]["repo.description"].endswith("</script>")
    raw = (site / "index.html").read_text()
    assert "<img src=x" not in raw and raw.count("</script>") == raw.count("<script")


def test_empty_site_home(tmp_path, page_of):
    site = make_site(tmp_path)
    rebuild_site(site, dashboard_config.empty())
    data = json.loads((site / "projects.json").read_text())
    assert data["projects"] == [] and all(item["value"] == "—" for item in data["summary"].values())
    with serve(site) as url:
        page = page_of(url)
        assert page.inner_text("#empty") == "등록된 과제가 없습니다" and page.locator("tr.proj").count() == 0
        assert page.locator("#summary .sum-item").count() == 4
        nojs = page_of(url, javascript=False)
        assert nojs.inner_text("#empty") == "등록된 과제가 없습니다"


def test_home_rebuild_is_idempotent(tmp_path):
    site = home_site(tmp_path)
    first = {name: (site / name).read_bytes() for name in ("index.html", "projects.json")}
    rebuild_site(site)
    assert {name: (site / name).read_bytes() for name in ("index.html", "projects.json")} == first


def test_home_has_no_external_requests(home, page_of):
    page = page_of(home)
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.reload()
    page.wait_for_load_state("load")
    assert requests and all(url.startswith(home) for url in requests), requests
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
