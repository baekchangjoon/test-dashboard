"""결정적 testId(설계 §6.7, §13.5, REQ-027).

`E2E_<arm>_<inputHash8>r<rep>[g<n>]_<featureSlug>#L<line>`. 시나리오 단위는 pickle이다
(Scenario Outline은 Examples 데이터 행마다 하나이고 `L<line>`은 그 행의 줄이다).
같은 slug의 feature가 둘 이상이면 호출자가 feature 상대 경로 순으로 `make`를 부르고, 뒤에 오는 것에 `_2`, `_3`가 붙는다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

ARMS = ("base", "jqa", "owl")
MAX_SLUG_LENGTH = 60


def feature_slug(path: str, name: str | None) -> str:
    """feature 이름(없으면 파일 이름)에서 ASCII 영숫자와 `_`만 남긴 slug.
    남는 글자가 없으면(모두 비ASCII) feature 경로의 sha1 앞 8자리로 만든 `f<hash>`다."""
    source = name if name else PurePosixPath(str(path).replace("\\", "/")).stem
    slug = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", source)).strip("_")[:MAX_SLUG_LENGTH].strip("_")
    if not slug:
        slug = "f" + hashlib.sha1(str(path).replace("\\", "/").encode("utf-8")).hexdigest()[:8]
    return slug


def make(arm: str, input_hash: str, rep: int, gen: int | None, feature_path: str, pickle_line: int,
         taken: set[str], *, name: str | None = None) -> str:
    if arm not in ARMS:
        raise ValueError(f"알 수 없는 arm: {arm!r}")
    if not isinstance(rep, int) or not 1 <= rep <= 9:
        raise ValueError(f"rep는 1~9여야 한다: {rep!r}")
    hash8 = str(input_hash)[:8]
    if not re.fullmatch(r"[0-9a-f]{8}", hash8):
        raise ValueError(f"입력 해시가 16진수 8자리 이상이어야 한다: {input_hash!r}")
    if gen is not None and (not isinstance(gen, int) or gen < 1):
        raise ValueError(f"gen은 1 이상이어야 한다: {gen!r}")
    prefix = f"E2E_{arm}_{hash8}r{rep}{f'g{gen}' if gen else ''}_"
    slug = feature_slug(feature_path, name)
    candidate, serial = f"{prefix}{slug}#L{pickle_line}", 1
    while candidate in taken:
        serial += 1
        candidate = f"{prefix}{slug}_{serial}#L{pickle_line}"
    taken.add(candidate)
    return candidate


@dataclass(frozen=True)
class Pickle:
    line: int
    name: str
    outline: bool


_SCENARIO_RE = re.compile(r"^\s*(Scenario|Example)\s*:\s*(.*)$")
_OUTLINE_RE = re.compile(r"^\s*(Scenario Outline|Scenario Template)\s*:\s*(.*)$")
_EXAMPLES_RE = re.compile(r"^\s*(Examples|Scenarios)\s*:")
_STRUCTURAL_RE = re.compile(r"^\s*(Feature|Background|Rule)\s*:")


def pickles(feature_text: str) -> list[Pickle]:
    """feature 텍스트의 pickle 목록(줄 번호는 1부터)."""
    result: list[Pickle] = []
    outline_name: str | None = None
    in_examples, header_seen = False, False
    for number, line in enumerate(feature_text.splitlines(), start=1):
        outline = _OUTLINE_RE.match(line)
        if outline:
            outline_name, in_examples, header_seen = outline.group(2).strip(), False, False
            continue
        scenario = _SCENARIO_RE.match(line)
        if scenario:
            result.append(Pickle(number, scenario.group(2).strip(), False))
            outline_name, in_examples = None, False
            continue
        if _EXAMPLES_RE.match(line):
            in_examples, header_seen = outline_name is not None, False
            continue
        if _STRUCTURAL_RE.match(line):
            outline_name, in_examples = None, False
            continue
        if in_examples and line.strip().startswith("|"):
            if not header_seen:
                header_seen = True
            else:
                result.append(Pickle(number, outline_name or "", True))
    return result
