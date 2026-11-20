"""td.proc 단위 테스트: 시간 초과 메시지의 argv 비밀값 제거(Task 9 이월), 신호 재전달."""
import signal
import subprocess
import sys

from td import proc


def test_timeout_message_redacts_args(capfd):
    secret = "hunter2-token"
    rc = proc.run_with_timeout(0.5, ["bash", "-c", "sleep 30", secret], kill_grace=0.5)
    assert rc == proc.TIMEOUT_EXIT
    err = capfd.readouterr().err
    assert "timeout:bash [args redacted]" in err and secret not in err and "sleep 30" not in err


def test_timeout_message_uses_program_basename(capfd):
    proc.run_with_timeout(0.5, ["/bin/sleep", "30"], kill_grace=0.5)
    err = capfd.readouterr().err
    assert "timeout:sleep [args redacted]" in err and "/bin/" not in err


def test_reraise_redelivers_signal_after_child_cleanup():
    code = (
        "import signal, sys\n"
        "from td import proc\n"
        "signal.signal(signal.SIGTERM, lambda s, f: (print('got-term', flush=True), sys.exit(0)))\n"
        "proc.run_with_timeout(60, ['sleep', '60'], reraise=True)\n"
        "print('not-reached', flush=True)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    import time
    time.sleep(1.5)
    child.send_signal(signal.SIGTERM)
    out, _ = child.communicate(timeout=30)
    assert "got-term" in out and "not-reached" not in out


def test_signal_before_child_start_still_kills_child(monkeypatch):
    """자식을 띄우기 전에 TERM을 받아도(핸들러는 이미 설치됨) 띄운 직후 그 그룹이 정리된다(고아 방지)."""
    import os
    from td import proc

    real_popen = subprocess.Popen
    spawned = []

    def popen_after_signal(*args, **kwargs):
        os.kill(os.getpid(), signal.SIGTERM)  # 핸들러는 proc이 아직 없으므로 신호만 기록한다
        child = real_popen(*args, **kwargs)
        spawned.append(child)
        return child

    monkeypatch.setattr(proc.subprocess, "Popen", popen_after_signal)
    started = __import__("time").time()
    rc = proc.run_with_timeout(60, ["sleep", "60"], kill_grace=2)
    assert rc != 0 and __import__("time").time() - started < 20
    assert spawned and spawned[0].poll() is not None


def test_inherited_sig_ign_is_preserved_so_cleanup_survives_second_ctrl_c():
    """정리 중(`trap '' INT TERM`)에 띄운 td_run은 상속받은 SIG_IGN을 유지해야 한다.
    전달 핸들러로 덮어쓰면 두 번째 Ctrl-C가 `docker compose down -v` 같은 정리 명령을 죽인다(I-1)."""
    import time
    code = (
        "import signal, sys\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "from td import proc\n"
        "rc = proc.run_with_timeout(30, ['bash', '-c', 'sleep 3; echo child-done'])\n"
        "print('rc=%d' % rc, flush=True)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    time.sleep(1.5)
    child.send_signal(signal.SIGINT)
    child.send_signal(signal.SIGTERM)
    out, _ = child.communicate(timeout=30)
    assert "child-done" in out and "rc=0" in out
