"""run_baseline.py와 세션 로더의 안전장치(Unit, 실제 파이프라인 없이 가짜 runner로)."""
from __future__ import annotations

import json
import signal
import subprocess
import time

import pytest

import run_baseline


def _record(label: str) -> dict:
    return {"label": label, "runId": f"R-{label}", "runDir": f"work/runs/R-{label}", "exitCode": 0}


@pytest.fixture
def default_file(tmp_path, monkeypatch):
    path = tmp_path / "acceptance-session.json"
    monkeypatch.setattr(run_baseline, "DEFAULT_SESSION_FILE", path)
    return path


def test_check_target_refuses_mismatched_session_file(default_file, tmp_path):
    with pytest.raises(SystemExit, match="--prefix"):
        run_baseline.check_target("_test/dbg/", default_file)
    with pytest.raises(SystemExit, match="운영 게시"):
        run_baseline.check_target("", tmp_path / "other.json")
    run_baseline.check_target("", default_file)
    run_baseline.check_target("_test/dbg/", tmp_path / "other.json")


def test_run_session_prefix_with_default_file_never_runs(default_file):
    calls = []
    with pytest.raises(SystemExit):
        run_baseline.run_session("_test/dbg/", default_file, [], runner=lambda *a: calls.append(a), etags=lambda *a: {})
    assert calls == [] and not default_file.exists()


def test_run_session_writes_after_baseline_then_after_second(default_file):
    seen_during_second = {}

    def runner(label, prefix, args):
        if label == "second":
            seen_during_second.update(json.loads(default_file.read_text()))
        return _record(label)

    session = run_baseline.run_session("", default_file, [], runner=runner, etags=lambda prefix, run_id: {"k": "e1"})
    # 두 번째 run이 도는 동안 파일에는 기준 run만 있다(증분 기록)
    assert seen_during_second["baseline"]["runId"] == "R-baseline" and "second" not in seen_during_second
    final = json.loads(default_file.read_text())
    assert final == session and final["second"]["runId"] == "R-second" and final["prefix"] == ""
    assert final["baselineEtagsBeforeSecond"] == final["baselineEtagsAfterSecond"] == {"k": "e1"}
    assert not list(default_file.parent.glob("*.tmp"))


@pytest.mark.parametrize("error", [SystemExit("second: runId를 얻지 못했다"), RuntimeError("boto3 ListObjects failed"),
                                   KeyboardInterrupt()])
def test_run_session_records_second_error_and_still_writes(default_file, error):
    def runner(label, prefix, args):
        if label == "second":
            raise error
        return _record(label)

    with pytest.raises(type(error)):
        run_baseline.run_session("", default_file, [], runner=runner, etags=lambda *a: {})
    saved = json.loads(default_file.read_text())
    assert saved["baseline"]["runId"] == "R-baseline" and "second" not in saved
    assert saved["secondError"].startswith(type(error).__name__)


def test_run_session_etag_failure_after_second_is_recorded(default_file):
    calls = {"n": 0}

    def etags(prefix, run_id):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("botocore EndpointConnectionError")
        return {}

    with pytest.raises(RuntimeError):
        run_baseline.run_session("", default_file, [], runner=lambda label, *a: _record(label), etags=etags)
    assert "EndpointConnectionError" in json.loads(default_file.read_text())["secondError"]


def test_stop_group_kills_term_ignoring_group():
    proc = subprocess.Popen(["bash", "-c", 'trap "" TERM; sleep 60 & wait'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.5)
    started = time.monotonic()
    run_baseline.stop_group(proc, signal.SIGTERM, grace_sec=1.0)
    assert proc.returncode is not None and time.monotonic() - started < 10
    # macOS는 좀비만 남은 그룹에 EPERM을 돌려주기도 한다(이미 끝난 그룹과 같다).
    with pytest.raises((ProcessLookupError, PermissionError)):
        import os
        os.killpg(proc.pid, 0)


# --- 세션 로더: 기본 세션 파일은 운영(prefix '') 증거만 받는다 ---------------------------------------------
def _conftest():
    import sys
    return next(m for n, m in sys.modules.items() if n.endswith("conftest") and hasattr(m, "SESSION_FILE"))


def test_loader_rejects_prefixed_session_without_override(tmp_path, monkeypatch):
    conftest = _conftest()
    run_dir = tmp_path / "runs" / "R1"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{}")
    session_file = tmp_path / "s.json"
    session_file.write_text(json.dumps({"prefix": "_test/dbg/", "baseline": {"runId": "R1", "runDir": str(run_dir)}}))
    monkeypatch.setattr(conftest, "SESSION_FILE", session_file)
    monkeypatch.delenv("TD_ACCEPTANCE_SESSION_FILE", raising=False)
    with pytest.raises(pytest.fail.Exception, match="prefix"):
        conftest.load_session_run("baseline")
    monkeypatch.setenv("TD_ACCEPTANCE_SESSION_FILE", str(session_file))  # 디버깅 세션을 명시적으로 끼우면 읽는다
    assert conftest.load_session_run("baseline").prefix == "_test/dbg/"


def test_loader_reports_second_error(tmp_path, monkeypatch):
    conftest = _conftest()
    session_file = tmp_path / "s.json"
    session_file.write_text(json.dumps({"prefix": "", "baseline": {"runId": "R1", "runDir": "x"},
                                        "secondError": "SystemExit: boom"}))
    monkeypatch.setattr(conftest, "SESSION_FILE", session_file)
    monkeypatch.delenv("TD_ACCEPTANCE_SESSION_FILE", raising=False)
    with pytest.raises(pytest.fail.Exception, match="secondError: SystemExit: boom"):
        conftest.load_session_run("second")


# --- 인덱스 전용 게시 기록(화면 재설계 요구사항명세 §0 "기준 run 세션") ------------------------------------------
def test_record_index_publish_adds_status_and_reason(default_file):
    session = run_baseline.run_session("", default_file, [], runner=lambda label, *a: _record(label), etags=lambda *a: {})
    seen = []
    publisher = lambda prefix: seen.append(prefix) or {"status": "degraded", "reason": "수집 degraded", "exitCode": 0}
    run_baseline.record_index_publish("", default_file, session, publisher=publisher)
    saved = json.loads(default_file.read_text())
    assert seen == [""] and saved["indexPublish"] == {"status": "degraded", "reason": "수집 degraded", "exitCode": 0}
    assert saved["second"]["runId"] == "R-second"


def test_record_index_publish_failure_is_recorded_then_raised(default_file):
    session = run_baseline.run_session("", default_file, [], runner=lambda label, *a: _record(label), etags=lambda *a: {})

    def publisher(prefix):
        raise SystemExit("index: 1800초 제한을 넘겨 중단했다")

    with pytest.raises(SystemExit):
        run_baseline.record_index_publish("", default_file, session, publisher=publisher)
    saved = json.loads(default_file.read_text())
    assert saved["indexPublish"]["status"] is None and "1800초" in saved["indexPublish"]["reason"]


def test_main_skip_second_does_not_publish_index(default_file, monkeypatch):
    monkeypatch.setattr(run_baseline, "run_pipeline", lambda label, prefix, args: _record(label))
    monkeypatch.setattr(run_baseline, "run_index_publish", lambda prefix: pytest.fail("인덱스 게시를 부르면 안 된다"))
    assert run_baseline.main(["--session-file", str(default_file), "--skip-second"]) == 0
    assert "indexPublish" not in json.loads(default_file.read_text())


def test_main_returns_nonzero_when_index_publish_failed(default_file, monkeypatch):
    monkeypatch.setattr(run_baseline, "run_pipeline", lambda label, prefix, args: _record(label))
    monkeypatch.setattr(run_baseline, "published_etags", lambda prefix, run_id: {})
    monkeypatch.setattr(run_baseline, "run_index_publish", lambda prefix: {"status": "failed", "reason": "잠금", "exitCode": 1})
    assert run_baseline.main(["--session-file", str(default_file)]) == 1
    assert json.loads(default_file.read_text())["indexPublish"]["status"] == "failed"
