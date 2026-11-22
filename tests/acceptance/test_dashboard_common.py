"""새 디자인 자산과 옛 자산(Task 7): REQ-136 옛 자산 불변, REQ-137 새 자산 경로."""
import json
import re
import shutil

from pathlib import Path

from dashboard_fixtures import (FIXTURES, REPORTS_RUN_ID, RUN_A, cfg_with, computed, home_site, make_local_run_with_reports, make_site,
                                open_page, proj, proj_dir, rebuild_site, serve, sha256, snap)  # noqa: F401
from td import dashboard_config, hosting
from td.site import pages

STATIC_DIR = pages.STATIC_DIR


def test_req136_legacy_assets_unchanged(tmp_path, browser):
    site = make_site(tmp_path, runs={"pet": [RUN_A]})
    rebuild_site(site, dashboard_config.empty())
    assert sha256(site / "static/site.css") == "27166871ff7312b677dd65cb0b96baee7499f1b38cbb92cd4b8f2befcf42710f"
    assert sha256(site / "static/site.js") == "8bd8e8f766db637afb9c3962982b7e21fdd5a9d746e7f7251d7d0582ce63e07e"
    assert sha256(pages.STATIC_DIR / "site.css") == sha256(site / "static/site.css")
    assert sha256(pages.STATIC_DIR / "site.js") == sha256(site / "static/site.js")
    legacy = site / "suts/pet/runs/legacy/index.html"
    legacy.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "legacy-run-page/index.html", legacy)
    expected = json.loads((FIXTURES / "legacy-run-page/EXPECTED.json").read_text())
    with serve(site) as url:
        page = open_page(browser, url + "suts/pet/runs/legacy/index.html")
        assert computed(page, "th", "background-color") == expected["thBackground"]
        assert computed(page, "body", "font-size") == expected["bodyFontSize"]
        page.context.close()


def test_req137_v2_asset_paths(tmp_path):
    out = pages.render_run(make_local_run_with_reports(tmp_path), tmp_path / "out").parent
    html = (out / "index.html").read_text()
    assert "static/v2/app.css" in html and "static/v2/app.js" in html and "static/site.css" not in html
    assert "static/site.js" not in html
    loaded = re.findall(r'<(?:link|script)[^>]+(?:href|src)="([^"]+)"', html)
    assert loaded and all("/static/v2/" in ref for ref in loaded), loaded
    site = make_site(tmp_path / "s", runs={"pet": [RUN_A]})
    rebuild_site(site, dashboard_config.empty())
    assert (site / "static/v2/app.css").is_file() and (site / "_test/static/v2/app.css").is_file()
    assert (site / "static/v2/app.js").is_file() and (site / "_test/static/v2/app.js").is_file()
    assert (site / "static/v2/app.css").read_bytes() == (pages.STATIC_DIR / "v2/app.css").read_bytes()
    # 인덱스 페이지(홈, _test 목록)도 static/v2/에서만 불러온다
    for index_page, expected_prefix in ((site / "index.html", "static/v2/"), (site / "_test/index.html", "static/v2/")):
        index_html = index_page.read_text()
        refs = re.findall(r'<(?:link|script)[^>]+(?:href|src)="([^"]+)"', index_html)
        assert refs and all(ref.startswith(expected_prefix) for ref in refs), (index_page, refs)
        assert "static/site.css" not in index_html and "site.js" not in index_html, index_page
    # 과제 페이지와 SUT 안내 페이지도 static/v2/에서만 불러온다(Task 10)
    for new_page in (site / "projects/pet/index.html", site / "suts/pet/index.html"):
        new_html = new_page.read_text()
        refs = re.findall(r'<(?:link|script)[^>]+(?:href|src)="([^"]+)"', new_html)
        assert refs and all(ref.startswith("../../static/v2/") for ref in refs), (new_page, refs)
        assert "static/site.css" not in new_html and "site.js" not in new_html, new_page


def test_req137_app_css_tokens_and_no_external_requests():
    css = (pages.STATIC_DIR / "v2/app.css").read_text()
    js = (pages.STATIC_DIR / "v2/app.js").read_text()
    for token in ("--bg:#f4f6f9", "--surface:#fff", "--ink:#131a24", "--accent:#2a78d6", "--warn:#b97a00",
                  "--crit:#cf3d3d", "--good:#16855a", "--bg:#0b1017", "--accent:#4a94ee"):
        assert token in css, token
    assert "prefers-color-scheme:dark" in css.replace(" ", "")
    for cls in (".s-crit", ".s-warn", ".s-good", ".s-none"):
        assert cls in css
    for text in (css, js):
        assert "@import" not in text and "http://" not in text and "https://" not in text and "url(" not in text
    assert 'classList.add("js")' in js


# --- Task 12: 공통 비기능(REQ-132~135, 138) ------------------------------------------------------------------

TABS = ["overview", "trend", "tests", "coverage", "hotspot", "quality", "generation", "runs"]
EXTERNAL_TOOL_PAGES = ("hotspot/", "tia/", "cucumber/")  # 공통 띠를 주입한 외부 도구 리포트: 직접 만든 HTML이 아니다


def ensure_hosting_page(site: Path) -> None:
    """proj_site는 hosting.html을 만들지 않으므로 게시와 같은 렌더 함수로 사이트 루트에 둔다(이미 있으면 그대로)."""
    target = site / "hosting.html"
    if not target.exists():
        target.write_text(hosting.render_html(None))


def report_pages(site: Path) -> list[str]:
    """렌더된 run 디렉터리에서 실제로 있는 리포트 진입 페이지(사이트 루트 기준 상대 경로)."""
    run = site / "suts/pet/runs" / REPORTS_RUN_ID  # 렌더된 최신 run(나머지 pet run은 뼈대)
    rels = ["index.html", "coverage/coverage.html", "sonar/sonar.html", "compare/compare.html", "ontology/jqa.html",
            "ontology/owl.html", "hotspot/hotspots.html", "hotspot/api_report.html", "tia/tia.html"]
    rels += [path.relative_to(run).as_posix() for path in run.glob("cucumber/*/index.html")]
    assert all((run / rel).is_file() for rel in rels), [rel for rel in rels if not (run / rel).is_file()]
    return [f"{run.relative_to(site).as_posix()}/{rel}" for rel in rels]


def own_html_files(site: Path) -> list[Path]:
    """사이트 안에서 직접 만든 HTML(외부 도구 리포트와 _design 제외)."""
    found = []
    for html in sorted(site.rglob("*.html")):
        rel = html.relative_to(site).as_posix()
        if rel.startswith("_design/") or any(f"/{marker}" in rel for marker in EXTERNAL_TOOL_PAGES):
            continue
        found.append(html)
    return found


LONG_NAME = "x" * 60
LONG_DESCRIPTION = ("긴 설명 " * 40).strip()[:200].strip()


def long_names_site(tmp_path: Path) -> Path:
    """이름 60자(끊을 곳 없음), 설명 200자인 과제가 있는 홈 사이트."""
    site = make_site(tmp_path / "long", config=cfg_with(plain=[LONG_NAME]),
                     snapshots={LONG_NAME: [snap(description=LONG_DESCRIPTION)]})
    rebuild_site(site)
    return site


def body_bg(browser, url: str, scheme: str) -> str:
    page = open_page(browser, url, scheme=scheme)
    try:
        return computed(page, "body", "background-color")
    finally:
        page.context.close()


def contrast(page, selector: str, index: int = 0) -> float:
    """요소의 computed color와 투명이 아닌 가장 가까운 조상의 background-color의 WCAG 명암비."""
    pair = page.evaluate("""([sel, idx]) => {
        const el = document.querySelectorAll(sel)[idx];
        const parse = (c) => c.match(/[\\d.]+/g).map(Number);
        let bg = [255, 255, 255, 1], node = el;
        while (node) { const c = parse(getComputedStyle(node).backgroundColor);
            if ((c.length < 4 ? 1 : c[3]) > 0) { bg = c; break; } node = node.parentElement; }
        return [parse(getComputedStyle(el).color), bg];
    }""", [selector, index])

    def luminance(rgb):
        lin = [(v / 255) / 12.92 if v / 255 <= 0.03928 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in rgb[:3]]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    lighter, darker = sorted((luminance(pair[0]), luminance(pair[1])), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


KNOWN_SAME_ORIGIN_404 = "suts/pet/publish-log/20261120-131022Z-b6f9393-manual-0000007a.json"  # run 페이지가 부르는 게시 기록(픽스처에 없음)


def load_page(page, url: str):
    """페이지를 열고 200이며 본문이 그려졌는지 확인한다(goto는 404에서도 예외를 내지 않는다)."""
    response = page.goto(url)
    try:
        body = response.text()  # 안내 페이지는 곧 이동하므로 이동 전에 응답 본문을 읽는다
    except Exception:
        body = None
    page.wait_for_load_state("load")
    assert response is not None and response.status == 200, (url, response and response.status)
    assert body is None or ("<title>" in body and "</body>" in body), url
    return response


def assert_tab_visible(context, url: str, tab: str) -> None:
    """새 문서로 `#<tab>`을 열어 app.js가 해시를 읽게 하고, 보이는 탭 구역이 `panel-<tab>` 하나인지 확인한다."""
    page = context.new_page()
    try:
        load_page(page, url + "#" + tab)
        visible = page.locator('[role="tabpanel"]:visible')
        assert visible.count() == 1 and visible.first.get_attribute("id") == "panel-" + tab, (url, tab)
    finally:
        page.close()


def test_req132_no_external_requests(proj, proj_dir, browser):
    ensure_hosting_page(proj_dir)
    context = browser.new_context()
    page = context.new_page()
    outside, not_found = [], []
    page.on("request", lambda req: outside.append(req.url) if not req.url.startswith((proj, "data:", "about:")) else None)
    page.on("response", lambda resp: not_found.append(resp.url) if resp.status == 404 and resp.url.startswith(proj) else None)
    visited = ["", "projects/pet/index.html", "projects/plain/index.html", "hosting.html", "suts/pet/index.html"]
    for rel in visited + report_pages(proj_dir):
        load_page(page, proj + rel)
    for tab in TABS:
        assert_tab_visible(context, proj + "projects/pet/index.html", tab)
    context.close()
    assert outside == [], outside
    assert [url for url in not_found if not url.endswith(KNOWN_SAME_ORIGIN_404)] == [], not_found
    assert not re.search(r"@import|url\(\s*['\"]?https?:", (STATIC_DIR / "v2/app.css").read_text())
    html_files = own_html_files(proj_dir)
    assert html_files
    for html in html_files:
        assert not re.search(r'<(script|img)[^>]+src="https?://|<link[^>]+href="https?://', html.read_text()), html


def test_req133_responsive_360(proj, proj_dir, browser, tmp_path):
    ensure_hosting_page(proj_dir)
    context = browser.new_context(viewport={"width": 360, "height": 740})
    page = context.new_page()
    own = [rel for rel in report_pages(proj_dir)
           if rel.endswith(("index.html", "sonar.html", "compare.html")) and "cucumber" not in rel]
    long_site = long_names_site(tmp_path)
    with serve(long_site) as long_url:
        urls = [proj, proj + "projects/plain/index.html", proj + "projects/pet/index.html", proj + "hosting.html",
                long_url] + [proj + rel for rel in own]
        for url in urls:
            load_page(page, url)
            width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert width[0] <= width[1], (url, width)
            if url == long_url:  # 이름 60자와 설명 200자가 실제로 이 페이지에 있다
                text = page.inner_text("body")
                assert LONG_NAME in text and LONG_DESCRIPTION in text
        for tab in TABS:
            tab_page = context.new_page()
            try:
                load_page(tab_page, proj + "projects/pet/index.html#" + tab)
                visible = tab_page.locator('[role="tabpanel"]:visible')
                assert visible.count() == 1 and visible.first.get_attribute("id") == "panel-" + tab, tab
                width = tab_page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
                assert width[0] <= width[1], (tab, width)
            finally:
                tab_page.close()
    context.close()


def test_req134_dark_theme(proj, proj_dir, browser, tmp_path):
    ensure_hosting_page(proj_dir)
    for rel in ["", "projects/pet/index.html", "hosting.html"] + [
            rel for rel in report_pages(proj_dir) if rel.endswith(("sonar.html", "compare.html"))]:
        assert body_bg(browser, proj + rel, "light") != body_bg(browser, proj + rel, "dark"), rel
    # 네 상태가 모두 있는 홈(home_site)에서 잰다. proj 사이트의 홈에는 위험·측정 없음 줄이 없다.
    with serve(home_site(tmp_path)) as home_url:
        for scheme in ("light", "dark"):
            page = open_page(browser, home_url, scheme=scheme)
            for selector in (".st.s-crit", ".st.s-warn", ".st.s-good", ".st.s-none"):
                count = page.locator(selector).count()
                assert count > 0, (scheme, selector)
                for index in range(count):
                    ratio = contrast(page, selector, index)
                    assert ratio >= 4.5, (scheme, selector, index, ratio)
            page.context.close()


def test_req135_status_not_color_only(tmp_path, browser):
    home = home_site(tmp_path)
    with serve(home) as url:
        page = open_page(browser, url)
        mark = lambda state: page.evaluate(
            f"(() => {{ const c = getComputedStyle(document.querySelector('.st.s-{state}'), '::before');"
            " return [c.borderRadius, c.backgroundColor, c.borderTopWidth]; })()")
        crit, warn, none = mark("crit"), mark("warn"), mark("none")
        assert crit[0] == "50%" and crit[1] != "rgba(0, 0, 0, 0)"
        assert warn[0] != crit[0]
        assert none[1] == "rgba(0, 0, 0, 0)" and none[2] != "0px"
        for state in ("crit", "warn", "none", "good"):
            labels = page.locator(f".st.s-{state}")
            assert labels.count() > 0, state
            assert all(labels.nth(index).inner_text().strip() for index in range(labels.count())), state
        page.context.close()


def test_req138_reduced_motion(tmp_path, browser):
    home = home_site(tmp_path)
    with serve(home) as url:
        read_duration = "getComputedStyle(document.querySelector('.caret')).transitionDuration"
        normal_context = browser.new_context(reduced_motion="no-preference")
        normal_page = normal_context.new_page()
        normal_page.goto(url)
        normal_duration = normal_page.evaluate(read_duration)
        normal_context.close()
        assert normal_duration != "0s", normal_duration  # 기본값이 0s가 아니어야 줄임 문맥의 0s가 규칙에서 온 것이다
        context = browser.new_context(reduced_motion="reduce")
        page = context.new_page()
        page.goto(url)
        assert page.evaluate(read_duration) == "0s"
        context.close()
