"""사이트 페이지 Int 테스트(REQ-049). 운영 사이트 E2E 재검증은 Task 25."""
import functools
import http.server
import json
import re
import subprocess
import threading
from pathlib import Path

import pytest

from td import dashboard_config
from td.site import index, pages
from helpers import make_site_run
from test_publish import linked_project, projects_island, runs_table, trend_panel

R1 = "20261101-010000Z-aaaaaaa-manual-00000001"
R2 = "20261102-010000Z-bbbbbbb-manual-00000002"


def test_req049_home_sut_run_pages(tmp_path):
    make_site_run(tmp_path, "petclinic", R1, kpis={"tests": {"passRate": 0.9}, "blackbox": {"line": 0.4}})
    latest = make_site_run(tmp_path, "petclinic", R2, coverage_dir=True,
                           stages={"S00": "passed", "S01": "passed", "S08": "passed", "S09": "degraded"},
                           kpis={"tests": {"passRate": 0.97}, "blackbox": {"line": 0.61}, "sonar": {"gate": "OK"}},
                           s09_top10=[{"name": "OwnerController.processFindForm"}])
    # 커버리지 단계가 단독 열람용으로 옆에 두는 스타일 사본은 이제 `app.css`다(게시 사본에는 들어가지 않는다).
    (latest / "S08" / "app.css").write_text("/*dup*/")
    site_dir = pages.render_run(latest, latest).parent
    assert site_dir == latest / "site"
    # 게시된 배치처럼 run 페이지를 run 디렉터리 바로 아래에도 둔다(과제 페이지 실행 이력의 run 링크 대상).
    (latest / "index.html").write_text((site_dir / "index.html").read_text())
    # 등록된 과제가 없는 설정: petclinic은 SUT 이름의 암묵 과제로 그려진다(요구사항명세 2026-11-22 §3 REQ-049).
    index.rebuild(tmp_path, config=dashboard_config.empty())

    # 홈의 과제 데이터(`projects.json`과 페이지 안 JSON 블록)에 그 SUT와 이어진 과제의 최신 run 값 네 가지가 있다.
    home = (tmp_path / "index.html").read_text()
    document = json.loads((tmp_path / "projects.json").read_text())
    assert projects_island(home) == document
    project = linked_project(document, "petclinic")
    expected_values = {"tests.passRate": 0.97, "coverage.line": 0.61, "sonar.gate": "OK",
                       "hotspot.topName": "OwnerController.processFindForm"}
    assert {name: project["values"][name] for name in expected_values} == expected_values
    assert f'href="{project["href"]}"' in home and 'href="_test/index.html"' in home

    # 과제 페이지: '한눈에'에 그 값이 서버 렌더로 보이고, 실행 이력 구역에 두 run, 추이 구역에 서버가 그린 SVG가 있다.
    project_page = (tmp_path / project["href"]).read_text()
    for metric, text in (("tests.passRate", "97.0%"), ("coverage.line", "61.0%"), ("sonar.gate", "통과")):
        assert re.search(rf'class="card kpi[^"]*" data-metric="{re.escape(metric)}"><div><span>[^<]*</span><b>{re.escape(text)}</b>',
                         project_page), metric
    assert "OwnerController.processFindForm" in project_page
    table = runs_table(project_page)
    assert f'data-run="{R1}"' in table and f'data-run="{R2}"' in table
    assert f'href="../../suts/petclinic/runs/{R2}/index.html"' in table
    trend = trend_panel(project_page)
    assert trend.count("<svg") >= 2 and "<title" in trend

    # SUT 페이지는 그 과제 페이지로 안내한다.
    sut = (tmp_path / "suts/petclinic/index.html").read_text()
    assert 'id="to-project" href="../../projects/petclinic/index.html"' in sut

    run = (site_dir / "index.html").read_text()
    assert 'href="coverage/coverage.html"' in run
    assert "../../publish-log/" + R2 + ".json" in run
    assert (site_dir / "coverage/coverage.html").read_text() != "<html>stale</html>"
    assert not list((site_dir / "coverage").rglob("*.exec"))
    assert not (site_dir / "coverage/app.css").exists()
    for html in (project_page, sut, run):
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
        # S13 단계(단계 띠): 로그를 읽기 전에는 run.json과 같은 publishing, 읽은 뒤에는 로그의 status/reason으로 바뀐다.
        page.wait_for_function("document.querySelector('#stage-strip button[data-stage=S13]').dataset.status === 'degraded'")
        page.click("#stage-strip button[data-stage=S13]")
        row = page.locator("#stage-detail").inner_text()
        assert "degraded" in row and "lightsail 실패" in row and "publishing" not in row
    finally:
        page.close()


def test_run_page_renders_s13_row_as_publishing_before_fetch(tmp_path):
    run_dir = make_site_run(tmp_path, "petclinic", R2)
    pages.render_run(run_dir, run_dir)
    html = (run_dir / "site/index.html").read_text()
    row = [line for line in html.splitlines() if 'data-stage="S13"' in line][0]
    assert "publishing" in row


def test_sanitize_replaces_run_repo_and_home_paths(tmp_path, monkeypatch):
    home = tmp_path / "home" / "me"
    repo = home / "repo"
    run_dir = repo / "work" / "runs" / "r1"
    out = tmp_path / "out"
    out.mkdir()
    (home).mkdir(parents=True)
    monkeypatch.setattr(pages.Path, "home", classmethod(lambda cls: home))
    (out / "a.html").write_text(f"<p>{run_dir}/S09 {repo}/suts {home}/.cache</p>")
    (out / "b.yml").write_text(f"path: {run_dir}\n")
    (out / "c.bin").write_bytes(f"{home}".encode())
    changed = pages.sanitize_site(out, run_dir, repo_root=repo)
    assert (out / "a.html").read_text() == "<p><run>/S09 <repo>/suts ~/.cache</p>"
    assert (out / "b.yml").read_text() == "path: <run>\n"
    assert (out / "c.bin").read_bytes() == str(home).encode()  # 바이너리는 그대로
    assert {p.name for p in changed} == {"a.html", "b.yml"}


def test_sanitize_gate_raises_on_residual_home_path(tmp_path, monkeypatch):
    home = tmp_path / "home" / "me"
    out = tmp_path / "out"
    out.mkdir()
    home.mkdir(parents=True)
    monkeypatch.setattr(pages.Path, "home", classmethod(lambda cls: home))
    (out / "ok.txt").write_text("clean")
    pages.check_no_home(out)
    (out / "y.txt").write_text(f"see {home}")
    with pytest.raises(pages.SanitizeError):
        pages.check_no_home(out)


def test_render_run_ignores_outputs_of_failed_stage(tmp_path):
    run_dir = make_site_run(tmp_path, "petclinic", R2, coverage_dir=True, stages={"S00": "passed", "S08": "failed"})
    out = pages.render_run(run_dir, run_dir).parent
    assert not (out / "coverage").exists()
    assert "coverage/coverage.html" not in (out / "index.html").read_text()


# --- REQ-050 멀티 SUT(E2E-inj) ---------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
# ontology/generated/<sut>/는 e2e/generated처럼 SUT별 생성 산출물(스냅샷)이라 검사 대상이 아니다.
SUT_NEUTRAL_DIRS = ("pipeline", "site-gen", "e2e/harness", "e2e/runner", "ontology/jqa", "ontology/owl", "prompts", "env")


def _s3_bytes(s3, bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def test_req050_multi_sut(injected_petclinic_run, mini_sut_run, s3_client, bucket, site_prefix):
    """같은 접두에 petclinic run이 먼저 게시된 상태에서 mini-sut(설명 파일만 다름)를 게시하면 홈 과제 표에 두 SUT의 과제가 나온다."""
    pet, mini = injected_petclinic_run, mini_sut_run
    for label, result in (("petclinic", pet), ("mini-sut", mini)):
        assert result.returncode == 0, f"{label} run 실패(exit {result.returncode}): {result.stderr[-2000:]}"
        stages = result.stages()
        for stage_id in ("S00", "S01", "S08", "S13"):
            assert stages[stage_id]["status"] in ("passed", "degraded"), (label, stage_id, stages[stage_id].get("reason"))
        assert stages["S01"]["status"] == "passed", (label, stages["S01"].get("reason"))
    assert pet.run_json["sut"] == "petclinic" and mini.run_json["sut"] == "mini-sut"

    summary = json.loads(_s3_bytes(s3_client, bucket, f"{site_prefix}suts.json"))
    assert {entry["name"] for entry in summary} >= {"petclinic", "mini-sut"}
    for sut, result in (("petclinic", pet), ("mini-sut", mini)):
        assert _s3_bytes(s3_client, bucket, f"{site_prefix}suts/{sut}/runs/{result.run_id}/_COMPLETE")
    # 홈의 과제 표에 두 SUT의 암묵 과제(SUT 이름)가 나오고, 각 과제 페이지에 그 SUT의 runId가 있다.
    # 같은 세션 접두에 다른 테스트가 다른 SUT 이름으로도 게시하므로, 두 SUT의 행만 골라 본다.
    home = _s3_bytes(s3_client, bucket, f"{site_prefix}index.html").decode()
    for sut in ("petclinic", "mini-sut"):
        row = _project_row(home, sut)
        assert f'href="projects/{sut}/index.html"' in row, f"{sut} 행에 과제 페이지 링크"
    pet_page = _s3_bytes(s3_client, bucket, f"{site_prefix}projects/petclinic/index.html").decode()
    mini_page = _s3_bytes(s3_client, bucket, f"{site_prefix}projects/mini-sut/index.html").decode()
    assert pet.run_id in pet_page and mini.run_id not in pet_page
    assert mini.run_id in mini_page and pet.run_id not in mini_page


def _project_row(home: str, name: str) -> str:
    """홈 HTML의 과제 표에서 `tr.proj[data-name=<name>]` 행(그 행의 `</tr>`까지)을 잘라낸다. 없으면 실패한다."""
    marker = f'<tr class="proj" data-name="{name}"'
    assert home.count(marker) == 1, f"홈 과제 표에 {name} 행이 하나여야 한다"
    start = home.index(marker)
    return home[start:home.index("</tr>", start)]


def test_req050_no_sut_hardcode_in_pipeline_code():
    """파이프라인 코드에는 특정 SUT(petclinic)의 이름과 패키지가 없다. 값은 설명 파일에서만 온다."""
    existing = [d for d in SUT_NEUTRAL_DIRS if (REPO_ROOT / d).is_dir()]
    found = subprocess.run(
        ["grep", "-rIlE", "--exclude-dir=.venv", "--exclude-dir=__pycache__", "--exclude-dir=build", "--exclude-dir=.gradle",
         "--exclude-dir=node_modules", "petclinic|org\\.springframework\\.samples", *existing],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert found.returncode == 1 and found.stdout == "", f"SUT 하드코딩: {found.stdout}"


def test_mini_sut_descriptor_is_valid_and_uses_own_values():
    from td import sut_config
    config = sut_config.load(REPO_ROOT / "tests/fixtures/mini-sut/sut.yaml")
    assert config.name == "mini-sut" and config.sonar_project_key == "minisut-td-test"
    assert len(config.coverage_probes) >= 2 and len({p.controller for p in config.coverage_probes}) >= 2
    assert config.auth_login == "POST /api/auth/login" and config.auth_type == "bearer"
    assert "petclinic" not in config.packages and "org.springframework.samples" not in config.packages
