"""게시물 공통 가림(redaction)과 업로드 전 누출 게이트.

게시되는 모든 텍스트(사이트 사본, publish-log, hosting.json/html, 단계 사유)는 쓰기 전에 `redact_text`를 거친다.
- 로컬 경로: run 디렉터리 → <run>, TD_WORK_DIR → <work>, 저장소 루트 → <repo>, 임시 디렉터리 → <tmp>, 홈 → ~
  (원본·resolve 표기 모두, 긴 것 먼저 치환해 중첩 경로가 가장 구체적인 이름으로 바뀐다)
- 인프라 식별자: TD_AWS_ACCOUNT_ID, TD_IAM_USER, TD_LIGHTSAIL_IP, TD_SSH_KEY_PATH 값(환경 우선, 없으면 infra/local.env) → <redacted>
- AWS ARN: arn:aws:... → <arn>
`find_leaks`는 치환 뒤에도 남은 것을 종류 이름으로만 돌려준다(값은 돌려주지 않는다 — 사유 문구에 값이 섞이지 않게).
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER_KEYS = ("TD_AWS_ACCOUNT_ID", "TD_IAM_USER", "TD_LIGHTSAIL_IP", "TD_SSH_KEY_PATH")
ARN_PATTERN = re.compile(r"arn:aws:[^\s\"'<>]+")
# 임시 디렉터리가 현재 TMPDIR과 다른 세션에서 만들어졌어도(macOS 사용자별 /var/folders/<a>/<b>/T) 가린다.
MAC_TMP_PATTERN = re.compile(r"(?:/private)?/var/folders/[^/\s\"'<>]+/[^/\s\"'<>]+/T(?=[/\s\"'<>]|$)")
# 게시물에 있으면 안 되는 로컬 절대 경로 접두. 앞이 단어 문자면(URL 경로 `example.com/home/`) 경로로 보지 않는다.
LOCAL_PREFIX_PATTERN = re.compile(r"(?<![\w.\-~])(?:/Users/|/home/|/private/var/|/var/folders/)")


def path_variants(path) -> list[str]:
    """경로의 원본·resolve 표기(중복 제거, 긴 것 먼저)."""
    path = Path(path)
    variants = {str(path), str(path.resolve())}
    return sorted((v for v in variants if len(v) > 1), key=len, reverse=True)


def _env_with_local(env: dict | None) -> dict:
    merged = dict(os.environ if env is None else env)
    root = Path(merged.get("TD_ROOT") or REPO_ROOT)
    local = root / "infra" / "local.env"
    if local.exists():
        for raw in local.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                merged.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return merged


def identifier_values(env: dict | None = None) -> dict[str, str]:
    """가려야 할 인프라 식별자 값(키 → 값). 비었거나 너무 짧은 값은 오탐을 막으려고 뺀다."""
    merged = _env_with_local(env)
    return {key: merged[key] for key in IDENTIFIER_KEYS if len(merged.get(key) or "") >= 4}


def _identifier_pattern(value: str) -> re.Pattern:
    # IP·계정 번호가 더 긴 숫자열의 일부일 때는 맞추지 않는다.
    return re.compile(r"(?<![0-9A-Za-z_.])" + re.escape(value) + r"(?![0-9A-Za-z_]|\.[0-9])")


def path_rules(run_dir=None, repo_root=None, env: dict | None = None) -> list[tuple[str, str]]:
    merged = dict(os.environ if env is None else env)
    repo = Path(repo_root or merged.get("TD_ROOT") or REPO_ROOT)
    work = Path(merged.get("TD_WORK_DIR") or repo / "work")
    rules: list[tuple[str, str]] = []
    if run_dir is not None:
        rules += [(v, "<run>") for v in path_variants(run_dir)]
    rules += [(v, "<work>") for v in path_variants(work)]
    rules += [(v, "<repo>") for v in path_variants(repo)]
    temp = tempfile.gettempdir()
    rules += [(v, "<tmp>") for v in path_variants(temp) + [os.path.realpath(temp)] if v not in ("/", "/tmp")]
    rules += [(v, "~") for v in path_variants(Path.home())]
    first: dict[str, str] = {}  # 같은 문자열이 둘이면 먼저 나온(더 구체적인) 이름을 쓴다
    for old, new in rules:
        first.setdefault(old, new)
    return sorted(first.items(), key=lambda item: len(item[0]), reverse=True)


def redact_text(text: str, run_dir=None, repo_root=None, env: dict | None = None) -> str:
    """경로·식별자·ARN을 가린 문자열. 식별자를 먼저 가린다(SSH 키 경로가 홈 치환으로 모양이 바뀌기 전에)."""
    for value in sorted(identifier_values(env).values(), key=len, reverse=True):
        text = _identifier_pattern(value).sub("<redacted>", text)
    text = ARN_PATTERN.sub("<arn>", text)
    for old, new in path_rules(run_dir, repo_root, env):
        text = text.replace(old, new)
    return MAC_TMP_PATTERN.sub("<tmp>", text)


def find_leaks(text: str, env: dict | None = None) -> list[str]:
    """남은 누출의 종류 이름 목록(값 없음): 'home', 'local-path', 'arn', 식별자 키 이름."""
    kinds = []
    if any(v in text for v in path_variants(Path.home())):
        kinds.append("home")
    if LOCAL_PREFIX_PATTERN.search(text):
        kinds.append("local-path")
    if ARN_PATTERN.search(text):
        kinds.append("arn")
    kinds += [key for key, value in identifier_values(env).items() if _identifier_pattern(value).search(text)]
    return kinds
