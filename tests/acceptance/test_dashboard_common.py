"""새 디자인 자산과 옛 자산(Task 7): REQ-136 옛 자산 불변, REQ-137 새 자산 경로."""
import json
import re
import shutil

from dashboard_fixtures import (FIXTURES, RUN_A, computed, make_local_run_with_reports, make_site, open_page,
                                rebuild_site, serve, sha256)
from td import dashboard_config
from td.site import pages


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
