"""runId 생성과 예약.

형식: YYYYMMDD-HHMMSSZ-<sha7>-<trigger>-<8hex> (UTC).
`work/runs/<runId>`를 원자적 mkdir로 예약하고, 충돌하면 난수를 다시 뽑는다(최대 5회, 초기 1회 포함).
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_ATTEMPTS = 5
TRIGGERS = ("manual", "pr", "merge")
RUNID_PATTERN = re.compile(r"^\d{8}-\d{6}Z-[0-9a-f]{7}-(manual|pr|merge)-[0-9a-f]{8}$")


def new(commit: str, trigger: str, runs_root: Path, rng=secrets.token_hex, now: datetime | None = None) -> str:
    """runId를 만들고 `runs_root/<runId>` 디렉터리를 예약해 돌려준다.

    rng(4)가 8자리 hex를 돌려주는 함수다. 5번 연속 충돌하면 RuntimeError.
    """
    if trigger not in TRIGGERS:
        raise ValueError(f"trigger must be one of {TRIGGERS}: {trigger!r}")
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        raise ValueError(f"commit must be a lowercase hex sha: {commit!r}")
    runs_root = Path(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = moment.strftime("%Y%m%d-%H%M%SZ")
    for _ in range(MAX_ATTEMPTS):
        run_id = f"{stamp}-{commit[:7]}-{trigger}-{rng(4)}"
        try:
            (runs_root / run_id).mkdir()
        except FileExistsError:
            continue
        return run_id
    raise RuntimeError(f"runId 예약 실패: {MAX_ATTEMPTS}회 연속 충돌")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.runid")
    sub = parser.add_subparsers(dest="cmd", required=True)
    new_cmd = sub.add_parser("new")
    new_cmd.add_argument("--commit", required=True)
    new_cmd.add_argument("--trigger", default="manual")
    new_cmd.add_argument("--runs-root", required=True)
    args = parser.parse_args(argv)
    from td.state import now as clock_now  # TD_NOW 주입을 따른다

    try:
        print(new(args.commit, args.trigger, Path(args.runs_root), now=clock_now()))
    except (RuntimeError, ValueError) as exc:
        print(f"runid: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
