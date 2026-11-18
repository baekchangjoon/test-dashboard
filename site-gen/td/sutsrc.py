"""sut.yaml에서 SUT 소스 해석에 필요한 키만 읽는다(스키마 검증은 Task 3의 sut_config.py).

run-all.sh가 run 디렉터리를 예약하기 전에 name/repo/ref를 쉘 변수로 받아 간다.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import yaml

REQUIRED = ("name", "repo", "ref")


def read_minimal(sut_file: Path) -> dict[str, str]:
    data = yaml.safe_load(Path(sut_file).read_text()) or {}
    missing = [key for key in REQUIRED if not data.get(key)]
    if missing:
        raise ValueError(f"{sut_file}: 필수 키 누락 {missing}")
    return {key: str(data[key]) for key in REQUIRED}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        values = read_minimal(Path(args[0]))
    except (OSError, ValueError, IndexError) as exc:
        print(f"sutsrc: {exc}", file=sys.stderr)
        return 1
    for key, value in values.items():
        print(f"SUT_{key.upper()}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
