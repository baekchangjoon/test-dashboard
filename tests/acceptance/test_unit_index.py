"""td.site.index 단위 테스트(REQ-045): 멱등, _COMPLETE만, 결정적 정렬, _test 접두 목록."""
import json
from pathlib import Path

from td.site import index
from td.site.index import line_chart
from helpers import make_site_run

KPIS = {"tests": {"passRate": 0.95}, "blackbox": {"line": 0.5}, "sonar": {"gate": "OK"}}


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def build_site(root: Path):
    make_site_run(root, "petclinic", "20261101-010000Z-aaaaaaa-manual-00000001", kpis=KPIS)
    make_site_run(root, "petclinic", "20261102-010000Z-bbbbbbb-manual-00000002", kpis={**KPIS, "blackbox": {"line": 0.6}})
    make_site_run(root, "petclinic", "20261103-010000Z-ccccccc-manual-00000003", complete=False)
    make_site_run(root, "mini", "20261101-020000Z-ddddddd-manual-00000004", kpis=KPIS)


def test_req045_idempotent(tmp_path):
    build_site(tmp_path)
    first_paths = index.rebuild(tmp_path)
    first = snapshot(tmp_path)
    second_paths = index.rebuild(tmp_path)
    assert snapshot(tmp_path) == first
    assert first_paths == second_paths
    assert "suts.json" in first and "suts/petclinic/runs.json" in first and "_test/index.html" in first


def test_only_complete_runs_sorted_desc_and_no_wall_clock(tmp_path):
    build_site(tmp_path)
    index.rebuild(tmp_path)
    runs = json.loads((tmp_path / "suts/petclinic/runs.json").read_text())
    assert [r["runId"][:8] for r in runs] == ["20261102", "20261101"]
    suts = json.loads((tmp_path / "suts.json").read_text())
    assert [s["name"] for s in suts] == ["mini", "petclinic"]
    assert suts[1]["latest"]["runId"].startswith("20261102")
    assert runs[0]["kpis"]["line"] == 0.6


def test_test_index_lists_prefixes_with_suts_json(tmp_path):
    make_site_run(tmp_path / "_test" / "td-test-a", "petclinic", "20261101-010000Z-aaaaaaa-manual-00000001", kpis=KPIS)
    (tmp_path / "_test" / "empty").mkdir(parents=True)
    index.rebuild(tmp_path, prefix="_test/td-test-a/")
    html = (tmp_path / "_test/index.html").read_text()
    assert 'href="td-test-a/index.html"' in html and "empty" not in html
    assert (tmp_path / "_test/td-test-a/suts.json").exists()


def _runs(*values):
    return [{"runId": f"2026110{i + 1}-010000Z-aaaaaaa-manual-0000000{i}", "kpis": {"passRate": v}} for i, v in enumerate(values)]


def test_line_chart_single_run_draws_a_dot_without_line():
    svg = line_chart("제목", "설명", _runs(0.5), "passRate")
    assert svg.count("<circle") == 1 and "<polyline" not in svg and "<title" in svg and "<desc" in svg


def test_line_chart_missing_value_breaks_the_line():
    svg = line_chart("제목", "설명", _runs(0.2, None, 0.4, 0.6), "passRate")
    assert svg.count("<circle") == 3
    assert svg.count("<polyline") == 1  # 끊긴 앞쪽은 점 하나라 선이 없고, 뒤쪽 두 점만 선이 된다


def test_line_chart_all_missing_has_axes_only():
    svg = line_chart("제목", "설명", _runs(None, None), "passRate")
    assert "<circle" not in svg and "<polyline" not in svg and 'class="axis"' in svg
