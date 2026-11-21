"""run 페이지와 공통 띠(Task 7): REQ-124 run 페이지, REQ-126 띠를 끼운 리포트의 기능 유지, REQ-127 띠를 넣을 수 없는 파일."""
import json
import re
from urllib.parse import urljoin

from dashboard_fixtures import (RUN_PATH, computed, http_status, make_local_run_with_reports, make_site, open_page,
                                render_site, run_fake_publication, serve, snapshot_bytes)
from td.site import index, layout, nav, pages


def test_req124_run_page(tmp_path, browser):
    site = render_site(tmp_path, make_local_run_with_reports(tmp_path))
    run_id = RUN_PATH.rstrip("/").split("/")[-1]
    log_dir = site / "suts/pet/publish-log"
    log_dir.mkdir(parents=True)
    (log_dir / f"{run_id}.json").write_text(json.dumps(
        {"status": "degraded", "reason": "lightsail: 실패", "hosts": {"s3": {"status": "passed"}, "lightsail": {"status": "failed"}}}))
    with serve(site) as url:
        page = open_page(browser, url + RUN_PATH)
        assert page.locator("nav.tdnav").count() == 1
        buttons = page.locator("#stage-strip button[data-stage]")
        assert buttons.count() == 14
        assert [buttons.nth(i).get_attribute("data-stage") for i in range(14)] == [f"S{n:02d}" for n in range(14)]
        page.click('#stage-strip button[data-stage="S07"]')
        assert page.get_attribute('#stage-strip button[data-stage="S07"]', "aria-pressed") == "true"
        assert page.locator('#stage-strip button[aria-pressed="true"]').count() == 1
        detail = page.inner_text("#stage-detail")
        assert all(t in detail for t in ("S07", "생성 E2E 실행", "passed", "4분 19초")), detail
        page.click('#stage-strip button[data-stage="S09"]')
        detail = page.inner_text("#stage-detail")
        assert "hotspot 분석" in detail and "2초" in detail and "생성 E2E 실행" not in detail
        # 성공한 리포트마다 카드, 링크는 모두 200
        hrefs = [c.get_attribute("href") for c in page.locator(".report-card a").all()]
        assert len(hrefs) >= 6 and all(http_status(urljoin(page.url, h)) == 200 for h in hrefs), hrefs
        reports = {c.get_attribute("data-report") for c in page.locator(".report-card[data-report]").all()}
        assert reports >= {"coverage/coverage.html", "hotspot/hotspots.html", "tia/tia.html", "sonar/sonar.html",
                           "compare/compare.html", "ontology/jqa.html", "ontology/owl.html", "cucumber/base-r1/index.html"}
        # S13 게시 결과는 기존처럼 publish-log에서 채운다
        assert page.locator("#publish-result").count() == 1
        page.wait_for_function("document.querySelector('#publish-result li')")
        result = page.inner_text("#publish-result")
        assert "상태: degraded" in result and "사유: lightsail: 실패" in result and "lightsail: failed" in result
        page.wait_for_function("document.querySelector('#stage-strip button[data-stage=S13]').dataset.status === 'degraded'")
        page.click('#stage-strip button[data-stage="S13"]')
        assert "degraded" in page.inner_text("#stage-detail") and "lightsail: 실패" in page.inner_text("#stage-detail")
        page.context.close()


def test_req124_run_page_without_javascript_shows_every_stage(tmp_path, browser):
    site = render_site(tmp_path, make_local_run_with_reports(tmp_path, with_own_reports=False))
    with serve(site) as url:
        page = open_page(browser, url + RUN_PATH, javascript=False)
        detail = page.inner_text("#stage-detail")
        assert all(label in detail for label in nav.STAGE_LABELS.values()), detail
        assert "4분 19초" in detail
        page.context.close()


def test_req124_strip_links_resolve_under_prefix(tmp_path, browser):
    """띠의 링크는 상대 경로라 접두(`_test/<id>/`) 아래에서도 열린다. SUT 링크는 suts/<sut>/index.html이다."""
    run_dir = make_local_run_with_reports(tmp_path, with_own_reports=False)
    site = make_site(tmp_path / "root")
    (site.parent / "suts/pet").mkdir(parents=True, exist_ok=True)
    (site.parent / "suts/pet/sut.yaml").write_text("name: pet\n")
    prefix = "_test/x/"
    target = site / prefix / RUN_PATH
    pages.render_run(run_dir, target)
    (target / "_COMPLETE").write_text("{}")
    from dashboard_fixtures import load_cfg
    index.rebuild(site, prefix, load_cfg(site))
    with serve(site) as url:
        for rel in ("", "hotspot/hotspots.html", "cucumber/base-r1/index.html"):
            page = open_page(browser, url + prefix + RUN_PATH + rel)
            links = page.locator("nav.tdnav a")
            hrefs = [links.nth(i).get_attribute("href") for i in range(links.count())]
            assert len(hrefs) >= 5
            for href in hrefs:
                absolute = urljoin(page.url, href)
                assert absolute.startswith(url + prefix), (rel, href)
                assert http_status(absolute) == 200, (rel, href)
            sut_link = urljoin(page.url, page.get_attribute("nav.tdnav a.tdnav-sut", "href"))
            assert sut_link == url + prefix + "suts/pet/index.html"
            page.context.close()


def test_req126_external_reports_still_work(tmp_path, browser):
    run_dir = make_local_run_with_reports(tmp_path)
    originals = snapshot_bytes(run_dir, ["S09", "S10"])
    with serve(render_site(tmp_path, run_dir)) as url:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(error))  # 내장 메서드는 playwright가 처리기로 받지 못한다
        try:
            page.goto(url + RUN_PATH + "hotspot/hotspots.html")
            assert page.locator("nav.tdnav").count() == 1 and page.locator("nav.tdnav script").count() == 0
            assert computed(page, "nav.tdnav", "position") == "static" and computed(page, "nav.tdnav", "height") == "40px"
            assert page.locator("#hm-map circle").count() >= 1
            before = page.inner_text("#hm-side")
            # 첫 원은 배경 고리(뿌리)라 그 위의 원이 클릭을 가로챈다. 다음 원(패키지)의 가운데를 실제 마우스로 누른다.
            # 지도를 화면 안으로 옮긴 뒤 원의 가운데를 실제 마우스로 누른다. 패키지 원은 패널을 바꾸지 않을 수 있어
            # 패널이 바뀔 때까지 앞쪽 원 몇 개를 차례로 누른다.
            page.locator("#hm-map").scroll_into_view_if_needed()
            circles = page.locator("#hm-map circle")
            for position in range(1, min(circles.count(), 20)):
                box = circles.nth(position).bounding_box()
                page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                if page.inner_text("#hm-side") != before:
                    break
            assert page.inner_text("#hm-side") != before
            page.goto(url + RUN_PATH + "tia/tia.html")
            assert page.locator("nav.tdnav").count() == 1 and page.locator("nav.tdnav script").count() == 0
            before = page.inner_text("main")
            page.locator("#seg [role=tab]").nth(1).click()
            # 탭 전환은 hashchange로 그리므로(주소가 #graph로 바뀐 뒤) 본문이 바뀔 때까지 기다린다.
            page.wait_for_function("old => document.querySelector('main').innerText !== old", arg=before, timeout=10000)
            assert page.get_attribute("#seg [role=tab] >> nth=1", "aria-selected") == "true"
            assert page.inner_text("main") != before
            for rel in ("hotspot/api_report.html", "cucumber/base-r1/index.html", "ontology/jqa.html", "ontology/owl.html"):
                page.goto(url + RUN_PATH + rel)
                assert page.locator("nav.tdnav").count() == 1 and page.locator("nav.tdnav script").count() == 0, rel
            assert errors == []
        finally:
            page.close()
    assert snapshot_bytes(run_dir, ["S09", "S10"]) == originals


def test_req126_nav_markup_contract():
    links = nav.links_for("cucumber/base-r1/index.html", [{"label": "TIA", "href": "tia/tia.html"},
                                                         {"label": "Cucumber 리포트 base-r1", "href": "cucumber/base-r1/index.html"}],
                          sut_name="pet")
    assert links["home"] == "../../../../../../index.html" and links["sut"] == "../../../../index.html"
    assert links["run"] == "../../index.html"
    assert links["reports"] == [{"label": "TIA", "href": "../../tia/tia.html", "current": False},
                                {"label": "Cucumber 리포트 base-r1", "href": "../../cucumber/base-r1/index.html", "current": True}]
    run_links = nav.links_for(None, [{"label": "TIA", "href": "tia/tia.html"}])
    assert (run_links["home"], run_links["sut"], run_links["run"]) == ("../../../../index.html", "../../index.html", "index.html")
    html = nav.render(links, "Cucumber 리포트 base-r1")
    assert html.startswith('<nav class="tdnav" aria-label="리포트 이동">') and html.endswith("</nav>")
    assert html.count("<style>") == 1 and "<script" not in html and "position:static" in html and "height:40px" in html
    assert all(cls.startswith("tdnav") for attr in re.findall(r'class="([^"]+)"', html) for cls in attr.split())
    assert 'aria-current="page"' in html
    assert layout.NAV_INJECT == {"hotspot/": ["hotspots.html", "api_report.html"], "tia/": ["tia.html"],
                                 "cucumber/*/": ["index.html"], "ontology/": ["jqa.html", "owl.html"]}
    assert list(nav.STAGE_LABELS) == [f"S{n:02d}" for n in range(14)] and nav.STAGE_LABELS["S10"] == "변경 영향 분석(TIA)"


def test_req127_inject_finds_first_body_case_insensitively(tmp_path):
    page = tmp_path / "a.html"
    page.write_text('<html><BODY class="x"><p>hi</p><body></html>')
    assert nav.inject(page, "<nav>N</nav>") is True
    assert page.read_text() == '<html><BODY class="x"><nav>N</nav><p>hi</p><body></html>'
    plain = tmp_path / "b.html"
    plain.write_text("<html><p>no body</p></html>")
    assert nav.inject(plain, "<nav>N</nav>") is False and plain.read_text() == "<html><p>no body</p></html>"


def test_req127_no_body_degraded(tmp_path):
    run_dir = make_local_run_with_reports(tmp_path, tia_html="<html><p>no body tag</p></html>",
                                          hotspot_html='<HTML><BODY class="x"><p>hi</p></BODY></HTML>')
    out = pages.render_run(run_dir, tmp_path / "out").parent
    assert (out / "tia/tia.html").read_text() == "<html><p>no body tag</p></html>"
    assert re.search(r'<BODY class="x"><nav class="tdnav"', (out / "hotspot/hotspots.html").read_text())
    missing = json.loads((out / "render.json").read_text())["navMissing"]
    assert [m["file"] for m in missing] == ["tia/tia.html"]
    assert missing[0]["reason"] == "<body>를 찾지 못했다" and missing[0]["report"]
    html = (out / "index.html").read_text()
    assert "공통 띠 없음" in html
    card = re.search(r'<div class="report-card[^"]*" data-report="tia/tia.html">(.*?)</div>', html, re.S).group(1)
    assert "nav-missing" in card and "공통 띠 없음" in card and "&lt;body&gt;를 찾지 못했다" in card
    result = run_fake_publication(run_dir)
    assert result["status"] == "degraded" and "tia/tia.html" in result["reason"] and "공통 띠 없음" in result["reason"]


def test_req127_render_json_is_not_published(tmp_path):
    from td import publish
    assert "render.json" in publish.EXCLUDED_SITE_FILES
    run_dir = make_local_run_with_reports(tmp_path, tia_html="<html>x</html>", with_own_reports=False)
    pages.render_run(run_dir, run_dir)
    assert (run_dir / "site/render.json").is_file()
    manifest = publish.build_manifest(run_dir / "site", "suts/pet/runs/r/", run_dir / "run.json")
    assert "render.json" not in manifest.entries


def test_req128_own_reports_new_frame(tmp_path):
    """직접 만드는 리포트(커버리지, Sonar, 방식 비교, 온톨로지, 호스팅 비교)가 v2 스타일을 쓰고 v1 site.css를 불러오지 않는다.
    run 아래 리포트에는 공통 띠가 정확히 하나 있다(커버리지·Sonar·비교는 템플릿이, 온톨로지는 주입이 그린다)."""
    from td import hosting
    out = pages.render_run(make_local_run_with_reports(tmp_path), tmp_path / "out").parent
    for rel in ("coverage/coverage.html", "sonar/sonar.html", "compare/compare.html"):
        html = (out / rel).read_text()
        assert "static/v2/app.css" in html and "static/site.css" not in html, rel
        assert html.count('<nav class="tdnav"') == 1, rel
        depth = "../" * (rel.count("/") + 4)
        assert f'href="{depth}static/v2/app.css"' in html and f'src="{depth}static/v2/app.js"' in html, rel
        assert re.search(r'<nav class="tdnav".*?<span class="tdnav-here">([^<]+)</span>', html, re.S).group(1) in (
            "커버리지", "Sonar 품질 결과", "arm 비교 판정"), rel
        assert not (out / rel).with_name("app.css").exists() and not (out / rel).with_name("site.css").exists(), rel
    for rel in ("ontology/jqa.html", "ontology/owl.html"):
        html = (out / rel).read_text()
        assert "--surface" in html and "static/site.css" not in html and html.count('<nav class="tdnav"') == 1, rel
        assert "--k-Endpoint" in html and "<link" not in html, rel  # 그래프 규칙까지 인라인(외부 요청 없음)
    hosting_html = hosting.render_html(None)
    assert 'href="static/v2/app.css"' in hosting_html and "static/site.css" not in hosting_html
    assert hosting_html.count('<nav class="tdnav"') == 0 and 'href="index.html"' in hosting_html


def test_req128_standalone_reports_copy_app_css(tmp_path):
    """단독 열람용(copy_css=True)은 리포트 옆에 app.css를 app.css 이름으로 두고 그것을 불러온다. 사이트 조립 때는 복사하지 않는다."""
    from td import sonar
    from td.site import layout
    assert "app.css" in layout.COPY_IGNORE and "site.css" not in layout.COPY_IGNORE
    run_dir = make_local_run_with_reports(tmp_path)
    doc = json.loads((run_dir / "S11/sonar/sonar.json").read_text())
    standalone = tmp_path / "standalone"
    html = sonar.render(doc, standalone).read_text()
    assert (standalone / "app.css").read_bytes() == (pages.STATIC_DIR / "v2/app.css").read_bytes()
    assert 'href="app.css"' in html and not (standalone / "site.css").exists()


def test_req127_clean_run_is_passed(tmp_path):
    result = run_fake_publication(make_local_run_with_reports(tmp_path, with_own_reports=False))
    assert result["status"] == "passed", result
