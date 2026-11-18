"""td.tia 단위 테스트: base 해석(first-parent), 사전 검사, 시나리오 요약."""
import json
import subprocess
from pathlib import Path

import pytest

from td import blackbox, tia

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def _git(repo, *args):
    return subprocess.run([*GIT, *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def linear_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    for index in range(12):
        (repo / "f.txt").write_text(f"{index}\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"c{index}")
    return repo


def test_resolve_base_head_minus_10(linear_repo):
    head = _git(linear_repo, "rev-parse", "HEAD")
    base = tia.resolve_base(linear_repo, head, "HEAD~10..HEAD", True)
    assert base == _git(linear_repo, "rev-parse", "HEAD~10") and len(base) == 40


def test_resolve_base_follows_first_parent_through_merge(linear_repo):
    _git(linear_repo, "checkout", "-b", "side", "HEAD~1")
    (linear_repo / "s.txt").write_text("side\n")
    _git(linear_repo, "add", ".")
    _git(linear_repo, "commit", "-m", "side")
    _git(linear_repo, "checkout", "main")
    _git(linear_repo, "merge", "--no-ff", "side", "-m", "merge")
    head = _git(linear_repo, "rev-parse", "HEAD")
    base = tia.resolve_base(linear_repo, head, "HEAD~2..HEAD", True)
    assert base == _git(linear_repo, "rev-list", "--first-parent", "-n", "1", "--skip=2", head)


def test_resolve_base_rejects_too_short_history(linear_repo):
    head = _git(linear_repo, "rev-parse", "HEAD")
    with pytest.raises(tia.TiaError, match="HEAD~50"):
        tia.resolve_base(linear_repo, head, "HEAD~50..HEAD", True)


def test_resolve_base_rejects_non_head_range(linear_repo):
    head = _git(linear_repo, "rev-parse", "HEAD")
    with pytest.raises(tia.TiaError):
        tia.resolve_base(linear_repo, head, "v1.0..HEAD", True)


def test_precheck_reports_missing_pieces(tmp_path):
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n")
    reasons = tia.precheck(tmp_path)
    assert any("blackboxTest" in reason for reason in reasons)
    assert any("PerTestCoverageExtension" in reason for reason in reasons)


def test_precheck_passes_with_task_and_extension(tmp_path):
    (tmp_path / "build.gradle").write_text("tasks.register('blackboxTest', Test) {}\n")
    test_dir = tmp_path / "src" / "test" / "java" / "x"
    test_dir.mkdir(parents=True)
    (test_dir / "PerTestCoverageExtension.java").write_text("class PerTestCoverageExtension {}\n")
    assert tia.precheck(tmp_path) == []


def test_summarize_is_lenient_about_counts(tmp_path):
    junit, exec_dir = tmp_path / "junit", tmp_path / "exec"
    junit.mkdir()
    exec_dir.mkdir()
    (junit / "a.xml").write_text('<testsuite><testcase classname="p.AIT" name="one"/><testcase classname="p.AIT" name="two"/></testsuite>')
    (exec_dir / "AIT#one.exec").write_bytes(b"x")
    (exec_dir / "aggregate.exec").write_bytes(b"x")
    result = blackbox.summarize(junit, exec_dir)
    assert result["status"] == "passed" and result["tcCount"] == 2 and result["execCount"] == 1
    assert result["missingExec"] == ["AIT#two"]


def test_summarize_fails_without_exec(tmp_path):
    junit, exec_dir = tmp_path / "junit", tmp_path / "exec"
    junit.mkdir()
    exec_dir.mkdir()
    (junit / "a.xml").write_text('<testsuite><testcase classname="p.AIT" name="one"/></testsuite>')
    assert blackbox.summarize(junit, exec_dir)["status"] == "failed"


def test_impact_summary_counts_selected_tests():
    doc = {"tests": [{"id": "A#x", "confidence": "DETERMINISTIC"}, {"id": "B#y", "confidence": "CONSERVATIVE"}]}
    summary = tia.impact_summary(doc, indexed_tests=5)
    assert summary["selected"] == 2 and summary["indexedTests"] == 5
    assert summary["deterministic"] == 1 and summary["conservative"] == 1 and summary["conservativeSelectAll"] is False


def test_impact_summary_select_all_when_every_test_conservative():
    doc = {"tests": [{"id": "A#x", "confidence": "CONSERVATIVE"}]}
    assert tia.impact_summary(doc, 1)["conservativeSelectAll"] is True


def test_build_scenarios_matches_report_contract_and_truncates_diff():
    doc = {"tests": [{"id": "A#x", "confidence": "CONSERVATIVE"}], "warnings": ["new file"]}
    diff = "\n".join(f"+line{i}" for i in range(tia.MAX_DIFF_LINES + 50))
    (scenario,) = tia.build_scenarios(doc, diff, 3, "a" * 40, "b" * 40)
    assert {"id", "title", "diff", "selected", "conservative", "total", "count", "reasons"} <= set(scenario)
    assert scenario["selected"] == [{"confidence": "CONSERVATIVE", "testId": "A#x"}]
    assert scenario["conservative"] is True and scenario["total"] == 3 and scenario["count"] == 1
    assert scenario["diff"].count("\n") <= tia.MAX_DIFF_LINES and "base-head.diff" in scenario["diff"]
    assert scenario["reasons"] == ["new file"]
