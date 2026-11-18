"""Lightsail 호스트(Caddy) 설정 패치: Caddyfile에 dash 사이트 블록, compose의 caddy 서비스에 읽기 전용 볼륨 추가.

순수 문자열 변환만 한다(서버 접근은 infra/lightsail/apply.sh). 둘 다 멱등이다.
CLI:
  python -m td.lightsail caddyfile <current> <block_template> <address> <out>
  python -m td.lightsail compose   <current> <volume_template> <dash_dir> <out>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CADDYFILE_MOUNT = "./Caddyfile:/etc/caddy/Caddyfile"


def patch_caddyfile(text: str, block_template: str, address: str) -> str:
    """block_template의 `__DASH_ADDR__`를 address로 바꿔 끝에 붙인다. 같은 주소 블록이 이미 있으면 그 블록만 새 내용으로 바꾼다(같으면 변화 없음)."""
    block = block_template.replace("__DASH_ADDR__", address)
    if not block.endswith("\n"):
        block += "\n"
    existing = re.search(rf"^{re.escape(address)}\s*\{{.*?^\}}[ \t]*\n?", text, re.MULTILINE | re.DOTALL)
    if existing:
        # 템플릿의 맨 앞 주석 줄은 서버에 이미 있는 것을 유지하고 블록 본문만 바꾼다.
        body = block[block.index(address):]
        return text[:existing.start()] + body + text[existing.end():]
    separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + separator + block


def patch_compose(text: str, volume_template: str, dash_dir: str) -> str:
    """caddy 서비스의 Caddyfile 마운트 바로 아래에 `<dash_dir>:/srv/dashboard:ro`를 넣는다(이미 있으면 그대로)."""
    volume_line = volume_template.replace("__DASH_DIR__", dash_dir)
    if not volume_line.endswith("\n"):
        volume_line += "\n"
    if volume_line.strip() in (line.strip() for line in text.splitlines()):
        return text
    lines = text.splitlines(keepends=True)
    in_caddy = False
    for index, line in enumerate(lines):
        if re.match(r"^  \S", line):  # 서비스 이름 줄
            in_caddy = re.match(r"^  caddy:\s*$", line) is not None
        elif in_caddy and CADDYFILE_MOUNT in line:
            lines.insert(index + 1, volume_line)
            return "".join(lines)
    raise ValueError("caddy 서비스의 Caddyfile 마운트를 compose에서 찾지 못했다")


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="td.lightsail")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_caddy = sub.add_parser("caddyfile")
    p_compose = sub.add_parser("compose")
    for sp, names in ((p_caddy, ("current", "template", "address", "out")),
                      (p_compose, ("current", "template", "dash_dir", "out"))):
        for name in names:
            sp.add_argument(name)
    args = parser.parse_args(argv)
    current = Path(args.current).read_text()
    template = Path(args.template).read_text()
    if args.cmd == "caddyfile":
        result = patch_caddyfile(current, template, args.address)
    else:
        result = patch_compose(current, template, args.dash_dir)
    Path(args.out).write_text(result)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
