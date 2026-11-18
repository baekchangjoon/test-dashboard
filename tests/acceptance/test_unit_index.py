"""td.site.index 단위 테스트(REQ-045): 멱등, _COMPLETE만, 결정적 정렬, _test 접두 목록."""
import json
from pathlib import Path

from td.site import index
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
