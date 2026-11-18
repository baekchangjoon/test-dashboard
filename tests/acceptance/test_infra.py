"""REQ-054: 인프라 식별자 비공개 (Int)."""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER_KEYS = ["TD_AWS_ACCOUNT_ID", "TD_LIGHTSAIL_IP", "TD_IAM_USER", "TD_SSH_KEY_PATH"]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True)


def _tracked_content() -> bytes:
    files = _git("ls-files", "-z").stdout.split(b"\0")
    chunks = []
    for name in files:
        if not name:
            continue
        path = REPO_ROOT / name.decode()
        if path.is_file():
            chunks.append(path.read_bytes())
    return b"\n".join(chunks)


def _mirror_content() -> bytes:
    mirror = REPO_ROOT / "work" / "site-mirror"
    if not mirror.exists():
        return b""
    return b"\n".join(p.read_bytes() for p in mirror.rglob("*") if p.is_file())


def test_req054_local_env_is_gitignored():
    result = _git("check-ignore", "-q", "--no-index", "infra/local.env")
    assert result.returncode == 0


@pytest.mark.parametrize("key", IDENTIFIER_KEYS)
def test_req054_identifiers_private(key, local_env):
    # 값은 출력하지 않는다(assert 메시지에도 넣지 않는다).
    value = local_env[key].encode()
    assert value, f"{key} 값이 비어 있다"
    assert value not in _tracked_content(), f"{key} 값이 추적 파일에 있다"
    assert value not in _git("log", "-p", "--all").stdout, f"{key} 값이 git 이력에 있다"
    assert value not in _mirror_content(), f"{key} 값이 work/site-mirror에 있다"
