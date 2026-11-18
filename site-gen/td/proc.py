"""외부 명령 시간 제한 실행기(`td_run`의 구현).

새 세션(프로세스 그룹)으로 띄우고, 시간이 넘으면 그룹 전체에 TERM, 유예(기본 10초) 뒤 KILL한다.
macOS에는 setsid 명령이 없고 bash job control은 비대화형에서 믿기 어려워 파이썬으로 구현한다.
종료 코드: 명령의 종료 코드, 시간 초과는 124. 사유는 stderr에 `timeout:<cmd>`로 쓴다.
"""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys

TIMEOUT_EXIT = 124


def run_with_timeout(timeout_sec: float, argv: list[str], kill_grace: float | None = None) -> int:
    grace = float(os.environ.get("TD_KILL_GRACE", "10")) if kill_grace is None else kill_grace
    try:
        proc = subprocess.Popen(argv, start_new_session=True)
    except OSError as exc:
        print(f"td_run: 실행 실패 {argv[0]}: {exc}", file=sys.stderr)
        return 127

    def forward(signum, _frame):
        # 호출자가 TERM/INT를 받으면 자식 그룹도 정리한다.
        _kill_group(proc, signal.SIGTERM)

    old_term = signal.signal(signal.SIGTERM, forward)
    old_int = signal.signal(signal.SIGINT, forward)
    try:
        try:
            return proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            print(f"timeout:{shlex.join(argv)} (>{timeout_sec:g}s)", file=sys.stderr)
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


def _kill_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
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
