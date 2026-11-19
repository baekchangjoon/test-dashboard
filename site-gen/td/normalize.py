"""번들 내용 검사용 줄 정규화(요구사항명세 REQ-020 절차).

번들 파일을 형식별로 파싱해 문자열 leaf를 문서 순서대로 뽑고, 각 leaf를 다음 순서로 정규화한다.
escape 해제(JSON/YAML escape, 유니코드 escape, 이중 escape는 변화가 없을 때까지 반복) -> CRLF를 LF로 -> 탭을 공백으로
-> 줄마다 앞뒤 공백 제거 -> 빈 줄 제거 -> 3자 이하 줄 제거. 파일 단위로 leaf를 이어 붙여 한 시퀀스로 본다.
SUT 소스는 파일 전체를 텍스트 leaf 하나로 보고 같은 정규화를 적용하므로 양쪽 시퀀스가 같은 규칙으로 만들어진다.
형식별 파서는 JSON, YAML, Turtle(literal과 주석), Markdown(코드 펜스 줄 제외), 그 밖은 텍스트 줄이다.
파싱에 실패한 파일은 텍스트로 읽는다(검출 쪽으로 보수적).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

import yaml

MIN_LINE_LENGTH = 4          # 3자 이하 줄은 일치 계산에서 뺀다
MAX_UNESCAPE_PASSES = 4
_ESCAPE_RE = re.compile(r'\\(?:u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|([nrt"\'\\/]))')
_SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "'": "'", "\\": "\\", "/": "/"}


def _decode_escape(match: re.Match) -> str:
    unicode_hex, byte_hex, simple = match.groups()
    if unicode_hex:
        return chr(int(unicode_hex, 16))
    if byte_hex:
        return chr(int(byte_hex, 16))
    return _SIMPLE_ESCAPES[simple]


def _join_surrogates(text: str) -> str:
    """\\ud83d\\ude00처럼 두 개로 풀린 대리쌍을 한 글자로 합친다."""
    if not any("\ud800" <= ch <= "\udfff" for ch in text):
        return text
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def unescape(text: str) -> str:
    for _ in range(MAX_UNESCAPE_PASSES):
        decoded = _join_surrogates(_ESCAPE_RE.sub(_decode_escape, text))
        if decoded == text:
            break
        text = decoded
    return text


def normalize_leaf(text: str) -> list[str]:
    text = unescape(text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    stripped = (line.strip() for line in text.split("\n"))
    return [line for line in stripped if len(line) >= MIN_LINE_LENGTH]


def _string_leaves(node) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _string_leaves(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _string_leaves(value)


_TURTLE_TOKEN_RE = re.compile(
    r'"""(?P<tdq>(?:[^"\\]|\\.|"(?!""))*)"""'
    r"|'''(?P<tsq>(?:[^'\\]|\\.|'(?!''))*)'''"
    r'|"(?P<dq>(?:[^"\\\n]|\\.)*)"'
    r"|'(?P<sq>(?:[^'\\\n]|\\.)*)'"
    r"|#(?P<comment>[^\n]*)"
    r"|<(?P<iri>[^>\s]*)>",
    re.DOTALL)


def _turtle_leaves(text: str) -> Iterator[str]:
    for match in _TURTLE_TOKEN_RE.finditer(text):
        if match.lastgroup == "iri":
            continue
        yield match.group(match.lastgroup)


def _markdown_leaves(text: str) -> Iterator[str]:
    body = [line for line in text.replace("\r\n", "\n").split("\n") if not line.lstrip().startswith("```")]
    yield "\n".join(body)


def leaves(path: Path) -> list[str]:
    raw = Path(path).read_bytes().decode("utf-8", errors="replace")
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".json":
            return list(_string_leaves(json.loads(raw)))
        if suffix in (".yaml", ".yml"):
            return [leaf for doc in yaml.safe_load_all(raw) for leaf in _string_leaves(doc)]
    except (ValueError, yaml.YAMLError):
        return [raw]
    if suffix in (".ttl", ".turtle"):
        return list(_turtle_leaves(raw))
    if suffix in (".md", ".markdown"):
        return list(_markdown_leaves(raw))
    return [raw]


def lines(file) -> list[str]:
    """파일 하나의 정규화된 줄 시퀀스(leaf를 문서 순서로 이어 붙인 것)."""
    sequence: list[str] = []
    for leaf in leaves(Path(file)):
        sequence.extend(normalize_leaf(leaf))
    return sequence


def text_lines(file) -> list[str]:
    """SUT 소스처럼 형식 파싱 없이 텍스트로만 읽는 파일의 정규화 시퀀스."""
    return normalize_leaf(Path(file).read_bytes().decode("utf-8", errors="replace"))
