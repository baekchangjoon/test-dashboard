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


# --- Task 9: Lightsail 적용 (REQ-074, REQ-055, REQ-052) -----------------------------------
import json
import os
import shutil
import socket
import time
import urllib.error
import urllib.request

APPLY_SH = REPO_ROOT / "infra" / "lightsail" / "apply.sh"
CADDY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "caddy-local"
ARC_REPO = Path.home() / "aws-resource-controller"


class CaddyFixture:
    """로컬 Docker caddy:2를 고정 포트(loopback)에 띄우고 apply.sh --local로 적용해 보는 작업 디렉터리."""

    def __init__(self, tmp_path: Path, label: str, name: str):
        self.dir = tmp_path / "stack"
        shutil.copytree(CADDY_FIXTURE, self.dir)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.project = f"{label}-caddy-{name}"
        self.env = {**os.environ, "TD_CADDY_PORT": str(self.port), "TD_TEST_LABEL": label,
                    "COMPOSE_PROJECT_NAME": self.project}
        (self.dir / "fixture.env").write_text("\n".join([
            "DASH_ADDR=http://dash.fixture.test:18080",
            "SONAR_URL=http://127.0.0.1:%d/api/system/status" % self.port,
            "SONAR_HOST=sonar.fixture.test:18080",
            "DASH_URL=http://127.0.0.1:%d/" % self.port,
            "DASH_HOST=dash.fixture.test:18080",
            "DASH_DIR=%s" % (self.dir / "srv-dashboard"),
            "COMPOSE_PROJECT=%s" % self.project, ""]))
        self._compose("up", "-d")

    def _compose(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "compose", "-p", self.project, *args], cwd=self.dir, env=self.env,
                              capture_output=True, text=True, timeout=300)

    def apply(self, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(APPLY_SH), "--local", str(self.dir)], cwd=REPO_ROOT,
                              env={**self.env, **extra}, capture_output=True, text=True, timeout=400)

    def read(self, name: str) -> bytes:
        return (self.dir / name).read_bytes()

    def http(self, host: str, path: str = "/") -> tuple[int, bytes]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers={"Host": host})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, b""

    def teardown(self) -> None:
        self._compose("down", "-v", "--remove-orphans")


@pytest.fixture
def caddy_fixture(tmp_path, test_run_label, request):
    made: list[CaddyFixture] = []

    def make(name: str = "x") -> CaddyFixture:
        fixture = CaddyFixture(tmp_path, test_run_label, name)
        made.append(fixture)
        return fixture

    request.addfinalizer(lambda: [fixture.teardown() for fixture in made])
    return make


def test_req074_caddy_apply_success(caddy_fixture):
    """REQ-074: 정상 적용 시 dash 블록이 서빙되고(HTTP 200) 기존 사이트도 UP이며, 재실행해도 같다."""
    fixture = caddy_fixture("ok")
    result = fixture.apply()
    assert result.returncode == 0, result.stderr[-2000:]
    status, body = fixture.http("dash.fixture.test:18080")
    assert status == 200 and "준비 중".encode() in body
    assert b'"status":"UP"' in fixture.http("sonar.fixture.test:18080", "/api/system/status")[1]
    assert b"/srv/dashboard" in fixture.read("docker-compose.yml")
    rerun = fixture.apply()
    assert rerun.returncode == 0, rerun.stderr[-2000:]
    assert fixture.http("dash.fixture.test:18080")[0] == 200


def test_req074_caddy_apply_invalid_block_restores_bytes(caddy_fixture, tmp_path):
    """REQ-074: 잘못된 블록은 validate에서 막히고 파일 바이트가 그대로이며 기존 서비스는 계속 UP이다."""
    fixture = caddy_fixture("bad")
    before = {name: fixture.read(name) for name in ("Caddyfile", "docker-compose.yml")}
    bad_block = tmp_path / "bad.block"
    bad_block.write_text("__DASH_ADDR__ {\n\tno_such_directive nope\n}\n")
    result = fixture.apply(TD_LIGHTSAIL_BLOCK_FILE=str(bad_block))
    assert result.returncode == 20, result.stderr[-1500:]  # validate 단계에서 막힘(변경 없음)
    assert {name: fixture.read(name) for name in before} == before
    assert b'"status":"UP"' in fixture.http("sonar.fixture.test:18080", "/api/system/status")[1]
    assert "준비 중".encode() not in fixture.http("dash.fixture.test:18080")[1]  # dash 블록 없음(미매칭 호스트는 빈 응답)


@pytest.mark.parametrize("fail_after", ["recreate", "health"])
def test_req074_caddy_apply_failure_after_mutation_rolls_back(caddy_fixture, fail_after):
    """REQ-074: 변경 후(recreate/health) 실패하면 파일을 바이트 그대로 복원하고 이전 설정으로 Caddy를 재생성한다."""
    fixture = caddy_fixture(fail_after)
    before = {name: fixture.read(name) for name in ("Caddyfile", "docker-compose.yml")}
    result = fixture.apply(TD_LIGHTSAIL_FAIL_AFTER=fail_after)
    assert result.returncode != 0
    assert {name: fixture.read(name) for name in before} == before
    assert b'"status":"UP"' in fixture.http("sonar.fixture.test:18080", "/api/system/status")[1]
    assert "준비 중".encode() not in fixture.http("dash.fixture.test:18080")[1]  # 이전 설정으로 재생성됨


# --- 실제 서버 (REQ-055, REQ-052, REQ-074 live) --------------------------------------------
def _ssh(local_env: dict, command: str) -> str:
    result = subprocess.run(
        ["ssh", "-i", local_env["TD_SSH_KEY_PATH"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
         f"ubuntu@{local_env['TD_LIGHTSAIL_IP']}", command], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"ssh 실패(rc={result.returncode})"
    return result.stdout


def _get(url: str, retry_seconds: int = 120) -> tuple[int, bytes]:
    deadline = time.monotonic() + retry_seconds
    last: Exception | None = None
    while True:
        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                return response.status, response.read()
        except Exception as error:  # noqa: BLE001 - 재시도 후 마지막 오류를 보고한다
            last = error
        if time.monotonic() > deadline:
            pytest.fail(f"{url.split('//')[1].split('/')[0].split('.')[0]} 요청 실패: {type(last).__name__}", pytrace=False)
        time.sleep(5)


def test_req074_dash_site_live(local_env):
    """REQ-074: https://dash.<domain>/ 가 서버 디렉터리(/srv/dashboard)를 HTTPS 200으로 서빙한다."""
    status, _ = _get(f"https://dash.{local_env['TD_DOMAIN']}/")
    assert status == 200
    assert "/srv/dashboard" in _ssh(local_env, "cat ~/sonarqube/docker-compose.yml")
    assert _ssh(local_env, "stat -c %U /srv/dashboard").strip() == "ubuntu"


def test_req055_arc_repo_synced(local_env):
    """REQ-055: 서버의 Caddyfile·compose가 aws-resource-controller 레포 복사본과 같고 origin/main에 포함돼 있다."""
    for name in ("Caddyfile", "docker-compose.yml"):
        server_text = _ssh(local_env, f"cat ~/sonarqube/{name}")
        assert server_text == (ARC_REPO / "sonarqube" / name).read_text(), f"{name}가 서버와 다르다"
    commit = subprocess.run(["git", "-C", str(ARC_REPO), "log", "-1", "--format=%H", "--", "sonarqube/Caddyfile",
                             "sonarqube/docker-compose.yml"], capture_output=True, text=True).stdout.strip()
    assert commit, "arc 레포에 sonarqube 변경 커밋이 없다"
    remote = subprocess.run(["git", "-C", str(ARC_REPO), "branch", "-r", "--contains", commit],
                            capture_output=True, text=True).stdout
    assert "origin/main" in remote.split(), "커밋이 origin/main에 없다(push 필요)"
    assert "dash." in (ARC_REPO / "sonarqube" / "Caddyfile").read_text()


def test_req052_sonar_healthy(local_env):
    """REQ-052: Sonar status UP, 서버 available 메모리 300MB 이상."""
    _, body = _get(f"https://sonar.{local_env['TD_DOMAIN']}/api/system/status", retry_seconds=60)
    assert json.loads(body)["status"] == "UP"
    mem_line = next(line for line in _ssh(local_env, "free -m").splitlines() if line.startswith("Mem:"))
    assert int(mem_line.split()[6]) >= 300
