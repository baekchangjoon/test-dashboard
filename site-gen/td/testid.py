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


def _relative_posix(path: str) -> str:
    text = str(path).replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        raise ValueError(f"feature 경로는 generation 루트 기준 상대 경로여야 한다(절대 경로 금지): {path!r}")
    return text


def feature_slug(path: str, name: str | None) -> str:
    """feature 이름(없으면 파일 이름)에서 ASCII 영숫자와 `_`만 남긴 slug.
    남는 글자가 없으면(모두 비ASCII) generation 루트 기준 상대 경로의 sha1 앞 8자리로 만든 `f<hash>`다
    (체크아웃 위치와 무관하다). 절대 경로는 ValueError."""
    relative = _relative_posix(path)
    source = name if name else PurePosixPath(relative).stem
    slug = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", source)).strip("_")[:MAX_SLUG_LENGTH].strip("_")
    if not slug:
        slug = "f" + hashlib.sha1(relative.encode("utf-8")).hexdigest()[:8]
    return slug


def make(arm: str, input_hash: str, rep: int, gen: int | None, feature_path: str, pickle_line: int,
         taken: set[str], *, name: str | None = None, slugs: dict[str, str] | None = None) -> str:
    """testId 하나. slug는 feature 단위로 정해진다: `slugs`(feature 경로 -> slug, 호출자가 한 generation 동안 공유)에
    처음 등장한 feature가 기본 slug를, 같은 slug를 가진 뒤따르는 feature가 `_2`, `_3`을 받고 그 feature의 모든 pickle이
    같은 slug를 쓴다. feature를 상대 경로 순으로 넘기면 결정적이다. `slugs`가 없으면 중복 testId는 ValueError다."""
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
    key = _relative_posix(feature_path)
    if slugs is None:
        slug = feature_slug(key, name)
    elif key in slugs:
        slug = slugs[key]
    else:
        base = feature_slug(key, name)
        used, slug, serial = set(slugs.values()), base, 1
        while slug in used:
            serial += 1
            slug = f"{base}_{serial}"
        slugs[key] = slug
    candidate = f"{prefix}{slug}#L{pickle_line}"
    if candidate in taken:
        raise ValueError(f"중복 testId: {candidate}")
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
