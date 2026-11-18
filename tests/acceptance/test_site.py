"""사이트 페이지 Int 테스트(REQ-049). 운영 사이트 E2E 재검증은 Task 25."""
import functools
import http.server
import json
import re
import threading

import pytest

from td.site import index, pages
from helpers import make_site_run

R1 = "20261101-010000Z-aaaaaaa-manual-00000001"
R2 = "20261102-010000Z-bbbbbbb-manual-00000002"


def test_req049_home_sut_run_pages(tmp_path):
    make_site_run(tmp_path, "petclinic", R1, kpis={"tests": {"passRate": 0.9}, "blackbox": {"line": 0.4}})
    latest = make_site_run(tmp_path, "petclinic", R2, coverage_dir=True,
                           stages={"S00": "passed", "S01": "passed", "S08": "passed", "S09": "degraded"},
                           kpis={"tests": {"passRate": 0.97}, "blackbox": {"line": 0.61}, "sonar": {"gate": "OK"}},
                           s09_top10=[{"name": "OwnerController.processFindForm"}])
    site_dir = pages.render_run(latest, latest).parent
    assert site_dir == latest / "site"
    index.rebuild(tmp_path)

    home = (tmp_path / "index.html").read_text()
    for needle in ("97.0%", "61.0%", "OK", "OwnerController.processFindForm", 'href="suts/petclinic/index.html"',
                   'href="_test/index.html"'):
        assert needle in home, needle
    assert home.count('class="kpi-item"') == 4

    sut = (tmp_path / "suts/petclinic/index.html").read_text()
    assert R1 in sut and R2 in sut and sut.count("<svg") >= 2
    assert f'href="runs/{R2}/index.html"' in sut
    assert "<title" in sut and "<desc" in sut

    run = (site_dir / "index.html").read_text()
    assert 'href="coverage/coverage.html"' in run
    assert "../../publish-log/" + R2 + ".json" in run
    assert (site_dir / "coverage/coverage.html").read_text() != "<html>stale</html>"
    assert not list((site_dir / "coverage").rglob("*.exec"))
    assert not (site_dir / "coverage/site.css").exists()
    for html in (home, sut, run):
        title = re.search(r"<title>(.*?)</title>", html).group(1)
        assert 2 <= len(title.split()) <= 4, title
    assert R2 not in re.search(r"<title>(.*?)</title>", run).group(1) and R2 in run
    # 매핑 밖 산출물(exec)과 단계 디렉터리는 게시 디렉터리로 복사하지 않는다.
    assert not (site_dir / "S08").exists()
    # 산출물이 없는 리포트(S09 hotspot)에는 링크를 달지 않는다.
    assert "hotspot/" not in run


def test_run_page_without_reports_has_no_links(tmp_path):
    run_dir = make_site_run(tmp_path, "petclinic", R1)
    run = pages.render_run(run_dir, run_dir).read_text()
    assert "coverage/coverage.html" not in run and "게시 결과 없음" in run


def test_published_stage_json_has_no_absolute_local_paths(tmp_path):
    run_dir = make_site_run(tmp_path, "petclinic", R2, coverage_dir=True)
    stage_file = run_dir / "stages" / "S01.json"
    stage = json.loads(stage_file.read_text())
    stage["outputs"] = {"blackbox": str(run_dir / "S01" / "blackbox"), "classes": "/elsewhere/classes", "note": "x"}
    stage_file.write_text(json.dumps(stage))
    site_dir = pages.render_run(run_dir, run_dir).parent
    published = {p: p.read_text() for p in site_dir.rglob("*.json")}
    assert published
    for path, text in published.items():
        assert str(tmp_path) not in text and "/elsewhere" not in text, path
    assert json.loads((site_dir / "stages/S01.json").read_text())["outputs"] == {"blackbox": "S01/blackbox", "note": "x"}
    assert json.loads((site_dir / "stages/S08.json").read_text())["outputs"]["coverage"] == "S08"


def test_render_run_to_separate_out_dir_copies_only_mapped(tmp_path):
    run_dir = make_site_run(tmp_path / "w", "petclinic", R2, coverage_dir=True)
    (run_dir / "S99").mkdir()
    (run_dir / "S99" / "secret.txt").write_text("x")
    out = tmp_path / "out"
    pages.render_run(run_dir, out)
    assert sorted(p.name for p in out.iterdir()) == ["coverage", "index.html", "run.json", "stages"]


@pytest.fixture
def publish_log_server(tmp_path):
    """run 페이지를 `suts/<sut>/runs/<runId>/` 위치로 띄우는 로컬 서버(정적 파일은 site.js만 필요)."""
    run_dir = make_site_run(tmp_path, "petclinic", R2)
    pages.render_run(run_dir, run_dir)
    index.rebuild(tmp_path)
    (tmp_path / "suts/petclinic/runs" / R2).joinpath("index.html").write_text((run_dir / "site/index.html").read_text())
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *args, **kwargs: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield tmp_path, f"http://127.0.0.1:{server.server_address[1]}/suts/petclinic/runs/{R2}/index.html"
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def test_site_js_shows_publish_log_or_graceful_absence(publish_log_server, browser):
    root, url = publish_log_server
    page = browser.new_page()
    try:
        page.goto(url)
        page.wait_for_load_state("networkidle")
        assert "게시 결과 없음" in page.locator("#publish-result").inner_text()  # 로그 없음 -> 404 -> 유지
        log_dir = root / "suts/petclinic/publish-log"
        log_dir.mkdir(parents=True)
        (log_dir / f"{R2}.json").write_text(json.dumps({"status": "degraded", "reason": "lightsail 실패", "hosts": {"s3": "ok", "lightsail": {"status": "failed"}}}))
        page.goto(url)
        page.wait_for_function("document.querySelector('#publish-result li')")
        text = page.locator("#publish-result").inner_text()
        assert "상태: degraded" in text and "사유: lightsail 실패" in text and "lightsail: failed" in text and "s3: ok" in text
        assert "게시 결과 없음" not in text
    finally:
        page.close()
