"""테스트 전용 장애 주입 훅.

`TD_FAIL_STAGE=<ID>[:<point>][,<ID>[:<point>]...]`. 운영 경로에서는 쓰지 않으며,
`TD_SITE_PREFIX`(테스트 게시 격리 접두사)가 없으면 거부한다.
점 없는 항목(S11)은 그 단계의 모든 point에 걸리고, 점 있는 항목(S11:scan)은 그 point에만 걸린다.
"""
from __future__ import annotations

import os
import sys

FAIL_EXIT = 10
REFUSED_EXIT = 3


class HookRefused(RuntimeError):
    """TD_SITE_PREFIX 없이 TD_FAIL_STAGE를 쓰려 할 때."""


def _entries(raw: str) -> list[tuple[str, str | None]]:
    result = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        stage, _, point = item.partition(":")
        result.append((stage, point or None))
    return result


def check_allowed(env=None) -> None:
    env = os.environ if env is None else env
    if env.get("TD_FAIL_STAGE", "").strip() and not env.get("TD_SITE_PREFIX", "").strip():
        raise HookRefused("TD_FAIL_STAGE는 TD_SITE_PREFIX가 있는 테스트 실행에서만 허용된다")


def should_fail(stage_id: str, point: str | None = None, env=None) -> bool:
    env = os.environ if env is None else env
    raw = env.get("TD_FAIL_STAGE", "")
    if not raw.strip():
        return False
    check_allowed(env)
    for stage, entry_point in _entries(raw):
        if stage != stage_id:
            continue
        if entry_point is None or entry_point == point:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[0] not in ("should-fail", "check"):
        print("usage: td.hooks should-fail <ID> [point] | check", file=sys.stderr)
        return 2
    try:
        if args[0] == "check":
            check_allowed()
            return 0
        return FAIL_EXIT if should_fail(args[1], args[2] if len(args) > 2 else None) else 0
    except HookRefused as exc:
        print(f"hooks: {exc}", file=sys.stderr)
        return REFUSED_EXIT


if __name__ == "__main__":
    sys.exit(main())
