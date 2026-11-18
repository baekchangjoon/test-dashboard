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


def _expected(tmp_path, tests):
    import yaml
    path = tmp_path / "expected-tests.yaml"
    path.write_text(yaml.safe_dump({"no_attribution": {"reason": "r", "tests": tests}}))
    return path


ALL = ["SampleIT#getA.exec", "SampleIT#plain.exec", "SampleIT#noted.exec", "aggregate.exec"]


def test_passed_when_all_have_exec_and_aggregate_present(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ALL, CASES)
    result = blackbox.evaluate(junit, exec_dir, src)
    assert result["status"] == "passed" and result["tcCount"] == result["execCount"] == 3
    assert result["missingExec"] == [] and result["aggregateExec"] is True


def test_passed_when_missing_is_documented(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ["SampleIT#getA.exec", "aggregate.exec"], CASES)
    expected = _expected(tmp_path, ["SampleIT#noted", "SampleIT#plain"])
    result = blackbox.evaluate(junit, exec_dir, src, expected)
    assert result["status"] == "passed" and result["missingExec"] == ["SampleIT#noted", "SampleIT#plain"]
    assert result["noAttribution"] == ["SampleIT#noted", "SampleIT#plain"]


def test_failed_on_undocumented_missing(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ["SampleIT#getA.exec", "aggregate.exec"], CASES)
    result = blackbox.evaluate(junit, exec_dir, src, _expected(tmp_path, ["SampleIT#noted"]))
    assert result["status"] == "failed" and "SampleIT#plain" in result["reason"]
    assert "SampleIT#noted" not in result["reason"]


def test_degraded_when_documented_has_exec(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ALL, CASES)
    result = blackbox.evaluate(junit, exec_dir, src, _expected(tmp_path, ["SampleIT#plain"]))
    assert result["status"] == "degraded" and result["reason"] == "expectation stale: SampleIT#plain"


def test_failed_without_aggregate_or_tcs(tmp_path):
    junit, exec_dir, src = _setup(tmp_path, ALL[:3], CASES)
    assert "aggregate.exec" in blackbox.evaluate(junit, exec_dir, src)["reason"]
    (tmp_path / "e").mkdir()
    assert blackbox.evaluate(_junit(tmp_path / "e", ""), exec_dir, src)["status"] == "failed"
