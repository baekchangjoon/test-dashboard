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
