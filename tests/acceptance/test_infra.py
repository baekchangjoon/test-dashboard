"""REQ-054: 인프라 식별자와 비밀 비공개 (Int)."""
import subprocess
from pathlib import Path

import pytest
import yaml

import helpers

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
        (self.dir / "srv-dashboard").mkdir()
        (self.dir / "srv-dashboard" / ".env").write_text("SECRET=1\n")  # hide 규칙 검증용
        (self.dir / "srv-dashboard" / "x.bak").write_text("old\n")
        self._compose("up", "-d")

    def _compose(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "compose", "-p", self.project, *args], cwd=self.dir, env=self.env,
                              capture_output=True, text=True, timeout=300)

    def apply(self, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(APPLY_SH), "--local", str(self.dir)], cwd=REPO_ROOT,
                              env={**self.env, **extra}, capture_output=True, text=True, timeout=400)

    def container_id(self) -> str:
        return self._compose("ps", "-q", "caddy").stdout.strip()

    def backups(self) -> list[str]:
        root = self.dir / ".td-backup"
        return sorted(p.name for p in root.glob("2*")) if root.exists() else []

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
    assert fixture.http("dash.fixture.test:18080", "/.env")[0] == 404  # hide .*  *.env
    assert fixture.http("dash.fixture.test:18080", "/x.bak")[0] == 404  # hide *.bak
    assert (fixture.dir / ".td-backup" / "original-pre-dashboard" / "Caddyfile").exists()
    container, backups = fixture.container_id(), fixture.backups()
    rerun = fixture.apply()
    assert rerun.returncode == 0, rerun.stderr[-2000:]
    assert fixture.http("dash.fixture.test:18080")[0] == 200
    # 이미 적용된 설정이면 백업도 재생성도 하지 않는다(무중단 재실행).
    assert fixture.container_id() == container and fixture.backups() == backups


def test_req074_caddy_backups_pruned_to_five(caddy_fixture):
    """REQ-074: 타임스탬프 백업은 최근 5개만 남고 원본 보존본은 유지된다."""
    fixture = caddy_fixture("prune")
    assert fixture.apply().returncode == 0
    root = fixture.dir / ".td-backup"
    for index in range(8):
        (root / f"2000010{index}T000000Z").mkdir()
    # 설정을 바꿔야 백업 경로를 탄다: 블록을 gzip 없는 변형으로 교체.
    variant = fixture.dir / "variant.block"
    variant.write_text("__DASH_ADDR__ {\n\troot * /srv/dashboard\n\tfile_server {\n\t\thide .* *.env *.bak\n\t}\n}\n")
    assert fixture.apply(TD_LIGHTSAIL_BLOCK_FILE=str(variant)).returncode == 0
    assert len(fixture.backups()) == 5
    assert (root / "original-pre-dashboard").is_dir()


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
    result = fixture.apply(TD_LIGHTSAIL_FAIL_AFTER=fail_after, TD_LIGHTSAIL_WAIT_SECONDS="6")
    assert result.returncode == 30, result.stderr[-1500:]
    # recreate는 확인 이전 단계, health는 확인 단계에서 실패해야 서로 다른 경로를 검증한다.
    assert ("주입 실패(recreate)" in result.stderr) == (fail_after == "recreate")
    assert ("dash 확인 실패(6초)" in result.stderr) == (fail_after == "health")
    assert {name: fixture.read(name) for name in before} == before
    assert b'"status":"UP"' in fixture.http("sonar.fixture.test:18080", "/api/system/status")[1]
    assert "준비 중".encode() not in fixture.http("dash.fixture.test:18080")[1]  # 이전 설정으로 재생성됨


def test_req074_caddy_apply_sigterm_after_mutation_restores(caddy_fixture):
    """REQ-074: 변경 후 확인 대기 중 TERM을 받아도 서버 쪽 trap이 바이트 그대로 복원한다."""
    import signal
    fixture = caddy_fixture("sigterm")
    before = {name: fixture.read(name) for name in ("Caddyfile", "docker-compose.yml")}
    proc = subprocess.Popen(["bash", str(APPLY_SH), "--local", str(fixture.dir)], cwd=REPO_ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            env={**fixture.env, "TD_LIGHTSAIL_FAIL_AFTER": "health", "TD_LIGHTSAIL_WAIT_SECONDS": "90"})
    deadline = time.monotonic() + 120
    while fixture.read("Caddyfile") == before["Caddyfile"]:  # 교체가 일어난 뒤(= health 대기 구간)에 신호를 보낸다
        assert proc.poll() is None and time.monotonic() < deadline, "교체 전에 끝났다"
        time.sleep(0.2)
    time.sleep(8)  # recreate와 sonar 확인을 지나 dash 대기에 들어가도록
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=120)
    assert proc.returncode != 0
    assert {name: fixture.read(name) for name in before} == before
    assert b'"status":"UP"' in fixture.http("sonar.fixture.test:18080", "/api/system/status")[1]


def test_req074_apply_rolls_back_created_dns_record(tmp_path):
    """REQ-074: 원격 모드에서 서버 단계가 실패하면 우리가 만든 dash A 레코드를 DELETE한다(스텁 ssh/boto3)."""
    stub_bin, stub_py, calls = tmp_path / "bin", tmp_path / "py", tmp_path / "route53-calls.jsonl"
    stub_bin.mkdir(); stub_py.mkdir()
    (tmp_path / "Caddyfile").write_text("sonar.example.test {\n\treverse_proxy sonarqube:9000\n}\n")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  caddy:\n    volumes:\n      - ./Caddyfile:/etc/caddy/Caddyfile:ro\n")
    ssh = stub_bin / "ssh"
    ssh.write_text(f"""#!/usr/bin/env bash
last="${{@: -1}}"
case "$last" in
  *Caddyfile*) cat "{tmp_path}/Caddyfile" ;;
  *docker-compose.yml*) cat "{tmp_path}/docker-compose.yml" ;;
  *) cat >/dev/null; exit 30 ;;   # 서버 단계(bash -s) 실패
esac
""")
    scp = stub_bin / "scp"
    scp.write_text("#!/usr/bin/env bash\nexit 0\n")
    for script in (ssh, scp):
        script.chmod(0o755)
    (stub_py / "sitecustomize.py").write_text(f"""
import json, boto3
class _Pager:
    def __init__(self, op): self.op = op
    def paginate(self, **kw):
        if self.op == "list_hosted_zones":
            yield {{"HostedZones": [{{"Id": "/hostedzone/Z1", "Name": "example.test.", "Config": {{}}}}]}}
        else:
            yield {{"ResourceRecordSets": []}}
class _Client:
    def get_paginator(self, op): return _Pager(op)
    def get_hosted_zone(self, Id): return {{"HostedZone": {{"Name": "example.test."}}}}
    def change_resource_record_sets(self, HostedZoneId, ChangeBatch):
        with open({str(calls)!r}, "a") as fh:
            fh.write(json.dumps([c["Action"] for c in ChangeBatch["Changes"]]) + "\\n")
boto3.client = lambda *a, **k: _Client()
""")
    env_file = tmp_path / "local.env"
    env_file.write_text("TD_DOMAIN=example.test\nTD_LIGHTSAIL_IP=192.0.2.7\nTD_SSH_KEY_PATH=/nonexistent\n")
    apply_copy = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "infra" / "lightsail", apply_copy / "infra" / "lightsail")
    (apply_copy / "infra" / "local.env").write_text(env_file.read_text())
    (apply_copy / "pipeline").symlink_to(REPO_ROOT / "pipeline")
    (apply_copy / "site-gen").symlink_to(REPO_ROOT / "site-gen")
    result = subprocess.run(["bash", str(apply_copy / "infra" / "lightsail" / "apply.sh")], cwd=tmp_path, capture_output=True,
                            text=True, timeout=120, env={**os.environ, "PATH": f"{stub_bin}:{os.environ['PATH']}",
                                                         "PYTHONPATH": str(stub_py), "TD_WORK_DIR": str(tmp_path / "work")})
    assert result.returncode == 30, result.stderr[-1500:]
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert recorded == [["CREATE"], ["DELETE"]]


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
    """REQ-074: https://dash.<domain>/ 가 서버 디렉터리(/srv/dashboard)를 HTTPS 200으로 서빙한다.

    로컬 리졸버가 NXDOMAIN을 캐시했으면 Route53 권한 응답 IP로 연결한다(TLS 검증은 호스트 이름 기준)."""
    domain = local_env["TD_DOMAIN"]
    status, _ = helpers.https_get(f"dash.{domain}", domain)
    assert status == 200
    assert "/srv/dashboard" in _ssh(local_env, "cat ~/sonarqube/docker-compose.yml")
    assert _ssh(local_env, "stat -c %U /srv/dashboard").strip() == "ubuntu"


def test_req055_arc_repo_synced(local_env):
    """REQ-055: 서버 파일이 origin/main에 push된 커밋의 sonarqube/ 파일과 바이트 단위로 같다(작업 트리가 아니라 커밋 기준)."""
    def git(*args: str) -> str:
        result = subprocess.run(["git", "-C", str(ARC_REPO), *args], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, f"git {args[0]} 실패"
        return result.stdout

    git("fetch", "origin", "main")
    commit = git("log", "-1", "--format=%H", "origin/main", "--", "sonarqube/Caddyfile", "sonarqube/docker-compose.yml").strip()
    assert commit, "origin/main에 sonarqube 변경 커밋이 없다"
    assert "origin/main" in git("branch", "-r", "--contains", commit).split()
    for name in ("Caddyfile", "docker-compose.yml"):
        assert _ssh(local_env, f"cat ~/sonarqube/{name}") == git("show", f"{commit}:sonarqube/{name}"), f"{name}가 push된 커밋과 다르다"
    assert "dash." in git("show", f"{commit}:sonarqube/Caddyfile")
    assert git("status", "--porcelain", "--", "sonarqube/") == "", "sonarqube/에 미커밋 변경이 있다"


def test_req052_sonar_healthy(local_env):
    """REQ-052: Sonar status UP, 서버 available 메모리 300MB 이상."""
    _, body = _get(f"https://sonar.{local_env['TD_DOMAIN']}/api/system/status", retry_seconds=60)
    assert json.loads(body)["status"] == "UP"
    mem_line = next(line for line in _ssh(local_env, "free -m").splitlines() if line.startswith("Mem:"))
    assert int(mem_line.split()[6]) >= 300
