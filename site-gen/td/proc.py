"""외부 명령 시간 제한 실행기(`td_run`의 구현).

새 세션(프로세스 그룹)으로 띄우고, 시간이 넘으면 그룹 전체에 TERM, 유예(기본 10초) 뒤 KILL한다.
macOS에는 setsid 명령이 없고 bash job control은 비대화형에서 믿기 어려워 파이썬으로 구현한다.
종료 코드: 명령의 종료 코드, 시간 초과는 124. 사유는 stderr에 `timeout:<cmd>`로 쓴다.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys

TIMEOUT_EXIT = 124


def redacted_command(argv: list[str]) -> str:
    """사유 문구용 명령 표기: 프로그램 이름만 남기고 인자(토큰·URL 등 비밀값이 섞일 수 있다)는 가린다."""
    program = os.path.basename(argv[0]) if argv else "?"
    return program if len(argv) < 2 else f"{program} [args redacted]"


def run_with_timeout(timeout_sec: float, argv: list[str], kill_grace: float | None = None,
                     reraise: bool = False, *, cwd=None, stdout=None, stderr=None, env=None) -> int:
    """reraise=True이면 대기 중 받은 TERM/INT로 자식 그룹을 정리한 뒤 같은 신호를 자신에게 다시 보내
    호출자의 핸들러(예: 게시기의 잠금 해제)가 실행되게 한다.
    cwd/stdout/stderr/env는 파이썬 호출자(예: td.bbtg)가 출력을 파일로 받을 때 쓴다(기본은 상속)."""
    grace = float(os.environ.get("TD_KILL_GRACE", "10")) if kill_grace is None else kill_grace
    proc: subprocess.Popen | None = None
    received: list[int] = []

    def forward(signum, _frame):
        # 호출자가 TERM/INT를 받으면 자식 그룹도 정리한다. 자식을 띄우기 전에 받은 신호는 띄운 직후에 처리한다
        # (백그라운드로 띄운 서버를 곧바로 끄는 경우, 자식이 신호 핸들러 설치 전에 고아가 되지 않게 한다).
        received.append(signum)
        if proc is not None:
            _kill_group(proc, signal.SIGTERM)

    old_term = signal.signal(signal.SIGTERM, forward)
    old_int = signal.signal(signal.SIGINT, forward)
    try:
        try:
            proc = subprocess.Popen(argv, start_new_session=True, cwd=cwd, stdout=stdout, stderr=stderr, env=env)
        except OSError as exc:
            print(f"td_run: 실행 실패 {argv[0]}: {exc}", file=sys.stderr)
            return 127
        if received:
            _kill_group(proc, signal.SIGTERM)
        try:
            return proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            print(f"timeout:{redacted_command(argv)} (>{timeout_sec:g}s)", file=sys.stderr)
            _kill_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
            # 리더가 죽었어도 TERM을 무시하는 자손이 남을 수 있으므로 그룹에 KILL을 보낸다.
            _kill_group(proc, signal.SIGKILL)
            proc.wait()
            return TIMEOUT_EXIT
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
        if reraise and received:
            os.kill(os.getpid(), received[0])


def _kill_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        # PermissionError: macOS는 좀비만 남은 그룹에 신호를 보내면 EPERM을 돌려준다(이미 끝난 그룹과 같다).
        pass


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 3 or args[0] != "run" or "--" not in args:
        print("usage: td.proc run <timeout_sec> -- cmd...", file=sys.stderr)
        return 2
    sep = args.index("--")
    return run_with_timeout(float(args[1]), args[sep + 1:])


if __name__ == "__main__":
    sys.exit(main())
