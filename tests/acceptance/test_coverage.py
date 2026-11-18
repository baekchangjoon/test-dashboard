"""S08 커버리지 수용 테스트(Int/E2E): REQ-031, REQ-063, REQ-032, REQ-033, REQ-034.

`run-all.sh petclinic --only S00,S01,S08`을 세션당 한 번 돌려 재사용한다(S01의 .exec를 입력으로 쓴다).
화면 테스트는 생성된 S08 디렉터리를 로컬 http.server로 띄워 헤드리스 chromium(playwright)으로 본다.
"""
import functools
import hashlib
import http.server
import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SUT_YAML = yaml.safe_load((REPO_ROOT / "suts" / "petclinic" / "sut.yaml").read_text())
PROBES = SUT_YAML["coverage"]["probes"]


@pytest.fixture(scope="session")
def s08_run(real_pipeline_run):
    return real_pipeline_run("S00,S01,S08")


def _s08(run) -> Path:
    return run.run_dir / "S08"


def _coverage(run) -> dict:
    return json.loads((_s08(run) / "coverage.json").read_text())


def _tc_json(run, test_id: str) -> dict:
    tcs = _coverage(run)["suites"]["blackbox"]["tcs"]
    slug = next(tc["slug"] for tc in tcs if tc["testId"] == test_id)
    return json.loads((_s08(run) / "tc" / f"{slug}.json").read_text())


def _xml_lines(xml_path: Path, *, covered_only: bool, source_name: str | None = None) -> set[tuple[str, int]]:
    """jacoco XML의 (소스 경로, 라인). covered_only면 ci>0 또는 cb>0인 라인만."""
    lines = set()
    for package in ET.parse(xml_path).getroot().iter("package"):
        for sourcefile in package.iter("sourcefile"):
            if source_name and sourcefile.get("name") != source_name:
                continue
            for line in sourcefile.iter("line"):
                if not covered_only or int(line.get("ci")) > 0 or int(line.get("cb")) > 0:
                    lines.add((f"{package.get('name')}/{sourcefile.get('name')}", int(line.get("nr"))))
    return lines


def _counter_ratio(xml_path: Path, kind: str) -> float:
    for counter in ET.parse(xml_path).getroot().findall("counter"):
        if counter.get("type") == kind:
            covered, missed = int(counter.get("covered")), int(counter.get("missed"))
            return covered / (covered + missed)
    raise AssertionError(f"{kind} counter가 없다: {xml_path}")


def test_req031_suite_coverage(s08_run):
    assert s08_run.returncode == 0, s08_run.stderr[-3000:]
    stage = s08_run.stage("S08")
    assert stage["status"] == "passed", stage
    root = _s08(s08_run)
    for kind in ("attributed", "aggregate"):
        base = root / "blackbox" / kind
        assert (base / "html" / "index.html").is_file(), kind
        assert (base / "jacoco.xml").is_file(), kind
        assert (base / "jacoco.csv").is_file(), kind
    kpis = s08_run.run_json["kpis"]["blackbox"]
    for key in ("line", "branch"):
        assert 0 < kpis[key] <= 1 and 0 < kpis["aggregate"][key] <= 1
    assert kpis["line"] == pytest.approx(_counter_ratio(root / "blackbox" / "attributed" / "jacoco.xml", "LINE"))
    assert kpis["aggregate"]["branch"] == pytest.approx(_counter_ratio(root / "blackbox" / "aggregate" / "jacoco.xml", "BRANCH"))
    assert kpis["aggregate"]["line"] >= kpis["line"]
    suite = _coverage(s08_run)["suites"]["blackbox"]
    assert suite["tcCount"] == 35 and suite["attributedCount"] == 27
    assert sum(1 for tc in suite["tcs"] if tc["attributed"]) == 27
    assert (root / "coverage.html").is_file() and list((root / "src").rglob("*.java"))


def test_req063_merged_aggregate(s08_run):
    root = _s08(s08_run)
    merged = root / "merged" / "aggregate.xml"
    manifest = json.loads((root / "merged" / "manifest.json").read_text())
    assert merged.is_file()
    assert manifest["suites"] == ["blackbox"]
    assert manifest["commit"] == s08_run.run_json["commit"]
    s00 = s08_run.stage("S00")["outputs"]
    assert manifest["classes"] == s00["classes"], "병합 리포트는 S00이 빌드한 같은 커밋의 classes를 써야 한다"
    assert manifest["xmlSha256"] == hashlib.sha256(merged.read_bytes()).hexdigest()
    assert len(manifest["execFiles"]) == 1 and Path(manifest["execFiles"][0]["path"]).name == "aggregate.exec"
    # 병합본은 스위트 aggregate를 포함한다
    assert _xml_lines(root / "blackbox" / "aggregate" / "jacoco.xml", covered_only=True) <= _xml_lines(merged, covered_only=True)


def test_req032_integrity(s08_run):
    root = _s08(s08_run)
    integrity = _coverage(s08_run)["integrity"]
    assert integrity["violations"] == []
    assert integrity["classIdWarnings"] == 0
    attributed = _xml_lines(root / "blackbox" / "attributed" / "jacoco.xml", covered_only=True)
    aggregate = _xml_lines(root / "blackbox" / "aggregate" / "jacoco.xml", covered_only=True)
    assert attributed and attributed <= aggregate
    # 탐침: 각 TC는 자기 컨트롤러 라인을 1개 이상 커버하고 상대 컨트롤러 라인은 0개 커버한다
    assert len(PROBES) == 2
    probe_lines = {}
    for probe in PROBES:
        probe_lines[probe["controller"]] = {line for line in _xml_lines(root / "blackbox" / "aggregate" / "jacoco.xml",
                                                                        covered_only=False, source_name=f"{probe['controller']}.java")}
        assert probe_lines[probe["controller"]], probe
    for probe in PROBES:
        covered = {(path, line) for path, lines in _tc_json(s08_run, probe["test"])["lines"].items() for line in lines}
        for controller, executable in probe_lines.items():
            hits = covered & executable
            if controller == probe["controller"]:
                assert hits, f"{probe['test']}가 자기 컨트롤러 {controller} 라인을 커버하지 않았다"
            else:
                assert not hits, f"{probe['test']}가 상대 컨트롤러 {controller} 라인을 {len(hits)}개 커버했다(교차 오염)"
    assert len(integrity["probes"]) == 2


# --- 화면(REQ-033, REQ-034) -----------------------------------------------------------------
@pytest.fixture(scope="module")
def coverage_url(s08_run):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(_s08(s08_run)))
    handler.log_message = lambda *args, **kwargs: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/coverage.html"
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


def test_req033_per_tc_view(s08_run, coverage_url, browser):
    probe_test = PROBES[0]["test"]
    tc_json = _tc_json(s08_run, probe_test)
    expected_hits = sum(len(lines) for lines in tc_json["lines"].values())
    assert expected_hits > 0
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto(coverage_url)
        page.wait_for_selector("tr.tc-row")
        assert page.locator("#heatmap td.hm-cell").count() > 0, "TC x 클래스 히트맵이 없다"
        assert page.locator("th", has_text="고유 라인").count() >= 1
        assert page.locator("tr.tc-row").count() == 35
        # 행 클릭 -> 소스 뷰어에 하이라이트
        page.locator(f'tr.tc-row[data-testid="{probe_test}"]').click()
        page.wait_for_selector("#detail .src-line.hit")
        page.wait_for_function(f"document.querySelectorAll('#detail .src-line.hit').length === {expected_hits}")
        assert page.locator("#detail .src-line.hit").count() == expected_hits
        # 정렬: 고유 라인 내림차순
        page.locator('button.sort[data-key="unique"]').click()
        values = page.locator("tr.tc-row:not([hidden]) td[data-key='unique']").evaluate_all("els => els.map(e => Number(e.dataset.value))")
        assert values == sorted(values) or values == sorted(values, reverse=True)
        page.locator('button.sort[data-key="unique"]').click()
        values_again = page.locator("tr.tc-row:not([hidden]) td[data-key='unique']").evaluate_all("els => els.map(e => Number(e.dataset.value))")
        assert values_again == list(reversed(values)) or values_again != values
        # 필터
        page.fill("#tc-filter", "OwnerApi")
        shown = page.locator("tr.tc-row:not([hidden])").evaluate_all("els => els.map(e => e.dataset.testid)")
        assert shown and all("OwnerApi" in test_id for test_id in shown)
        owner_total = sum(1 for tc in _coverage(s08_run)["suites"]["blackbox"]["tcs"] if "OwnerApi" in tc["testId"])
        assert len(shown) == owner_total
        # 알려진 한계 문구
        assert "필터 체인" in page.locator("#filter-chain-note").inner_text()
    finally:
        page.close()


def test_req034_responsive(s08_run, coverage_url, browser):
    page = browser.new_page(viewport={"width": 360, "height": 800})
    try:
        page.goto(coverage_url)
        page.wait_for_selector("tr.tc-row")
        overflow = "[document.documentElement.scrollWidth, window.innerWidth]"
        scroll_width, inner_width = page.evaluate(overflow)
        assert scroll_width <= inner_width, f"가로 스크롤: {scroll_width} > {inner_width}"
        assert page.locator(".scroll >> table#tc-table").count() == 1, "TC 표는 자체 스크롤 컨테이너 안에 있어야 한다"
        page.locator("tr.tc-row").first.click()
        page.wait_for_selector("#detail .src-line.hit")
        scroll_width, inner_width = page.evaluate(overflow)
        assert scroll_width <= inner_width, f"상세 열람 후 가로 스크롤: {scroll_width} > {inner_width}"
    finally:
        page.close()
