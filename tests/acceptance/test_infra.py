"""REQ-054: 인프라 식별자와 비밀 비공개 (Int)."""
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_VALUES_FILE = Path(__file__).with_name("public-values.yaml")

# local.env 키 분류. 새 키는 여기에 분류해야 한다(test_req054_all_keys_classified).
IDENTIFIER_KEYS = ["TD_AWS_ACCOUNT_ID", "TD_LIGHTSAIL_IP", "TD_IAM_USER", "TD_SSH_KEY_PATH"]
SECRET_KEYS = ["TD_SUT_USER", "TD_SUT_PASS"]
PUBLIC_KEYS = ["TD_DOMAIN"]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True)


def _assert_value_absent(key: str, value: str, snapshot: dict) -> None:
    # 값은 출력하지 않는다(assert 메시지에도 넣지 않는다).
    needle = value.encode()
    assert needle, f"{key} 값이 비어 있다"
    assert needle not in snapshot["tracked"], f"{key} 값이 추적 파일에 있다"
    assert needle not in snapshot["git_log"], f"{key} 값이 git 이력에 있다"
    assert needle not in snapshot["mirror"], f"{key} 값이 work/site-mirror에 있다"


def test_req054_local_env_is_gitignored():
    assert _git("check-ignore", "-q", "--no-index", "infra/local.env").returncode == 0


def test_req054_all_keys_classified(local_env):
    classified = set(IDENTIFIER_KEYS) | set(SECRET_KEYS) | set(PUBLIC_KEYS)
    unclassified = sorted(set(local_env) - classified)
    assert not unclassified, f"분류되지 않은 local.env 키: {unclassified}"


@pytest.mark.parametrize("key", IDENTIFIER_KEYS)
def test_req054_identifiers_private(key, local_env, repo_snapshot):
    _assert_value_absent(key, local_env[key], repo_snapshot)


@pytest.mark.parametrize("key", SECRET_KEYS)
def test_req054_secrets_private(key, local_env, repo_snapshot):
    exemptions = yaml.safe_load(PUBLIC_VALUES_FILE.read_text()) or {}
    if key in exemptions:
        print(f"{key}: 검사 제외 - {exemptions[key]}")
        return
    _assert_value_absent(key, local_env[key], repo_snapshot)
