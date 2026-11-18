"""사이트 페이지 Int 테스트(REQ-049). 운영 사이트 E2E 재검증은 Task 25."""
import json

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
    pages.render_run(latest, latest)
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

    run = (latest / "index.html").read_text()
    assert 'href="coverage/coverage.html"' in run
    assert "../../publish-log/" + R2 + ".json" in run
    assert (latest / "coverage/coverage.html").read_text() != "<html>stale</html>"
    assert not list((latest / "coverage").rglob("*.exec"))
    assert not (latest / "coverage/site.css").exists()
    # 산출물이 없는 리포트(S09 hotspot)에는 링크를 달지 않는다.
    assert "hotspot/" not in run


def test_run_page_without_reports_has_no_links(tmp_path):
    run_dir = make_site_run(tmp_path, "petclinic", R1)
    pages.render_run(run_dir, run_dir)
    run = (run_dir / "index.html").read_text()
    assert "coverage/coverage.html" not in run and "게시 결과 없음" in run
