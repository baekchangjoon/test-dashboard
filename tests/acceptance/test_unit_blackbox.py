"""td.blackbox 단위 테스트: DisplayName→메서드 복원, skipped 제외, aggregate 제외, 게이트 판정."""
from pathlib import Path

from td import blackbox

JAVA = '''package x;
class SampleIT {
\t@Test
\t@DisplayName("GET /a returns \\"ok\\"")
\tvoid getA() {}
\t@Test
\tvoid plain() {}
\t@Test
\t@DisplayName("with note (documented behavior)")
\tvoid noted() {}
}
'''


def _junit(tmp_path: Path, cases: str) -> Path:
    junit = tmp_path / "junit"
    junit.mkdir()
    (junit / "TEST-x.SampleIT.xml").write_text(f'<testsuite name="x.SampleIT">{cases}</testsuite>')
    return junit


def _setup(tmp_path, execs, cases):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SampleIT.java").write_text(JAVA)
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()
    for name in execs:
        (exec_dir / name).write_bytes(b"x")
    return _junit(tmp_path, cases), exec_dir, src


CASES = ('<testcase name="GET /a returns &quot;ok&quot;" classname="x.SampleIT"/>'
         '<testcase name="plain()" classname="x.SampleIT"/>'
         '<testcase name="with note " classname="x.SampleIT"/>'
         '<testcase name="gone" classname="x.SampleIT"><skipped/></testcase>')


def test_display_name_restored_and_skipped_excluded(tmp_path):
    junit, _, src = _setup(tmp_path, [], CASES)
    assert blackbox.junit_test_ids(junit, src) == ["SampleIT#getA", "SampleIT#plain", "SampleIT#noted"]


def test_passed_when_counts_match_and_aggregate_present(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ["SampleIT#getA.exec", "SampleIT#plain.exec", "SampleIT#noted.exec", "aggregate.exec"], CASES)
    result = blackbox.evaluate(junit, exec_dir, src)
    assert result["status"] == "passed" and result["tcCount"] == result["execCount"] == 3
    assert result["missingExec"] == [] and result["aggregateExec"] is True


def test_failed_reports_missing_exec(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ["SampleIT#getA.exec", "aggregate.exec"], CASES)
    result = blackbox.evaluate(junit, exec_dir, src)
    assert result["status"] == "failed" and result["missingExec"] == ["SampleIT#noted", "SampleIT#plain"]
    assert "tcCount(3) != execCount(1)" in result["reason"]


def test_failed_without_aggregate_or_tcs(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ["SampleIT#getA.exec", "SampleIT#plain.exec", "SampleIT#noted.exec"], CASES)
    assert "aggregate.exec" in blackbox.evaluate(junit, exec_dir, src)["reason"]
    empty = _junit(tmp_path / "e", "") if (tmp_path / "e").mkdir() is None else None
    assert blackbox.evaluate(empty, exec_dir, src)["status"] == "failed"
