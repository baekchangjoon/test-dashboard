"""수용 테스트 공용 하네스.

전제(AWS, SSH, Docker, claude)가 없으면 skip이 아니라 실패한다.
이후 Task가 채우는 fixture는 pytest.fail("requires Task N")로 명시적으로 실패한다.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from helpers import claude_call_log as _claude_call_log
from helpers import docker_ids as _docker_ids
from helpers import find_leaked_resources

REPO_ROOT = Path(__file__).resolve().parents[2]
# 기준 run 증거(run_baseline.py가 쓴다). 디버깅 세션 파일은 TD_ACCEPTANCE_SESSION_FILE로 바꿔 끼울 수 있다.
SESSION_FILE = Path(os.environ.get("TD_ACCEPTANCE_SESSION_FILE") or REPO_ROOT / "work" / "acceptance-session.json")
# det arm E2E 증거(실제 run을 가리키는 세션 파일). TD_DET_SESSION_FILE로 바꿔 끼울 수 있다.
DET_SESSION_FILE = Path(os.environ.get("TD_DET_SESSION_FILE") or REPO_ROOT / "work" / "det-session.json")
# det 조합 시각화 E2E 증거. 형식 {"runDir", "previousCasesDir", "publishedDir", "publishedUrl"}(모두 필수).
DET_VIZ_SESSION_FILE = Path(os.environ.get("TD_DET_VIZ_SESSION_FILE", REPO_ROOT / "work" / "det-viz-session.json"))
DET_VIZ_SESSION_KEYS = ("runDir", "previousCasesDir", "publishedDir", "publishedUrl")
# det pairwise(PICT) E2E 증거. TD_DET_PAIRWISE_SESSION_FILE로 바꿔 끼울 수 있다.
DET_PAIRWISE_SESSION_FILE = Path(os.environ.get("TD_DET_PAIRWISE_SESSION_FILE")
                                 or REPO_ROOT / "work" / "det-pairwise-session.json")
DET_PAIRWISE_SESSION_KEYS = ("runDir", "order3RunDir", "previousCasesDir", "run3BundleDir", "run3RunDir")
LOCAL_ENV_PATH = REPO_ROOT / "infra" / "local.env"

_SESSION_ID = os.environ.get("TD_TEST_SESSION_ID") or uuid.uuid4().hex[:8]
_SESSION_RUN_IDS: list[str] = []  # 이 세션의 fixture가 시작한 실제 run의 runId(td-<runId> 라벨 누수 검사용)


# --- baseline 마커 (개정 A) ---------------------------------------------------
def pytest_configure(config):
    # 백그라운드 작업(`cmd &`)으로 띄운 pytest는 SIGINT를 SIG_IGN으로 물려받고, 자식 프로세스도 그 설정을 그대로 받는다.
    # bash는 "시작할 때 무시된 신호"를 trap할 수 없으므로 run-all.sh의 SIGINT trap이 죽고, 정리 테스트가 90초를 기다리게 된다
    # (test_req010_sigint_cleanup 플레이크의 근본 원인). 핸들러를 명시적으로 설치하면 자식은 exec 때 기본 동작(SIG_DFL)으로 시작한다.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    config.addinivalue_line(
        "markers",
        "baseline: 기준 run 증거(work/acceptance-session.json)가 필요한 E2E 테스트. 없으면 실패한다.",
    )
    config.addinivalue_line(
        "markers",
        "det_pairwise_e2e: det pairwise 실제 run 증거(work/det-pairwise-session.json)가 필요한 E2E 테스트. 없으면 실패한다.",
    )
    config.addinivalue_line(
        "markers",
        "det_e2e: det arm 실제 run 증거(work/det-session.json)가 필요한 E2E 테스트. 없으면 실패한다.",
    )
    config.addinivalue_line(
        "markers",
        "det_viz_e2e: det 조합 시각화 실제 run 증거(work/det-viz-session.json)가 필요한 E2E 테스트. 없으면 실패한다.",
    )


def pytest_runtest_setup(item):
    _require_det_session(item)
    _require_det_viz_session(item)
    _require_det_pairwise_session(item)
    if item.get_closest_marker("baseline") and not SESSION_FILE.exists():
        pytest.fail(
            "baseline 테스트는 work/acceptance-session.json(기준 run 증거)이 필요하다. "
            "기준 run 전에는 실패가 정상이며 Task 25에서 green이 된다.",
            pytrace=False,
        )


def _require_det_session(item):  # pragma: no cover - 아래 훅에서 호출
    if item.get_closest_marker("det_e2e") and not DET_SESSION_FILE.exists():
        pytest.fail(
            f"det_e2e 테스트는 {DET_SESSION_FILE}(실제 det run을 가리키는 세션 파일)이 필요하다. "
            "형식: {\"runDir\": \"<abs>\", \"baselineRunDir\": \"<abs>\"}. skip하지 않고 실패한다.",
            pytrace=False,
        )


def _require_det_viz_session(item):  # pragma: no cover - 위 훅에서 호출
    if not item.get_closest_marker("det_viz_e2e"):
        return
    if not DET_VIZ_SESSION_FILE.exists():
        pytest.fail(
            f"det_viz_e2e 테스트는 {DET_VIZ_SESSION_FILE}(실제 det 시각화 run을 가리키는 세션 파일)이 필요하다. "
            "형식: {\"runDir\", \"previousCasesDir\", \"publishedDir\", \"publishedUrl\"}. skip하지 않고 실패한다.",
            pytrace=False,
        )
    try:
        session = json.loads(DET_VIZ_SESSION_FILE.read_text(encoding="utf-8"))
    except ValueError as error:
        pytest.fail(f"{DET_VIZ_SESSION_FILE}이 JSON이 아니다: {error}", pytrace=False)
    missing = [key for key in DET_VIZ_SESSION_KEYS if not isinstance(session, dict) or not session.get(key)]
    if missing:
        pytest.fail(f"{DET_VIZ_SESSION_FILE}에 필수 키가 없다: {missing}", pytrace=False)
def _require_det_pairwise_session(item):  # pragma: no cover - 위 훅에서 호출
    if not item.get_closest_marker("det_pairwise_e2e"):
        return
    if not DET_PAIRWISE_SESSION_FILE.exists():
        pytest.fail(
            f"det_pairwise_e2e 테스트는 {DET_PAIRWISE_SESSION_FILE}(실제 pairwise run을 가리키는 세션 파일)이 필요하다. "
            f"키: {list(DET_PAIRWISE_SESSION_KEYS)}. skip하지 않고 실패한다.",
            pytrace=False,
        )
    session = json.loads(DET_PAIRWISE_SESSION_FILE.read_text(encoding="utf-8"))
    missing = [key for key in DET_PAIRWISE_SESSION_KEYS if not session.get(key)]
    if missing:
        pytest.fail(f"det pairwise 세션 파일에 필수 키가 없다: {missing}", pytrace=False)


# --- 세션 식별 -------------------------------------------------------------------
@pytest.fixture(scope="session")
def session_id() -> str:
    return _SESSION_ID


@pytest.fixture(scope="session")
def site_prefix(session_id) -> str:
    return f"_test/{session_id}/"


@pytest.fixture(scope="session")
def test_run_label(session_id) -> str:
    return f"td-test-{session_id}"


# --- local.env ---------------------------------------------------------------------
def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@pytest.fixture(scope="session")
def local_env() -> dict[str, str]:
    if not LOCAL_ENV_PATH.exists():
        pytest.fail("infra/local.env가 없다(infra/local.env.example을 복사해 채운다)", pytrace=False)
    return _parse_env(LOCAL_ENV_PATH)


# --- fake claude -----------------------------------------------------------------------
_FAKE_CLAUDE_SCRIPT = """#!{python}
import json, os, sys
base = os.path.dirname(os.path.abspath(__file__))
stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()
with open(os.path.join(base, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(),
                         "env": {{k: v for k, v in os.environ.items()
                                 if k.startswith("TD_") or k in ("PATH", "PWD")}}, "stdin": stdin_text}}) + "\\n")
delay_file = os.path.join(base, "delay.txt")
if os.path.exists(delay_file):
    import time
    time.sleep(float(open(delay_file).read().strip() or 0))
sequence_file = os.path.join(base, "responses.json")
if os.path.exists(sequence_file):
    # 응답 순서표: n번째 호출(1부터)은 n번째 항목, 표보다 많으면 마지막 항목. 문자열 항목은 그대로(비JSON 출력 재현용).
    with open(os.path.join(base, "calls.jsonl")) as fh:
        index = sum(1 for line in fh if line.strip()) - 1
    with open(sequence_file) as fh:
        items = json.load(fh)
    item = items[min(index, len(items) - 1)]
    sys.stdout.write(item if isinstance(item, str) else json.dumps(item))
else:
    with open(os.path.join(base, "response.json")) as fh:
        sys.stdout.write(fh.read())
"""


@dataclass
class Call:
    argv: list[str]
    cwd: str
    env: dict[str, str]
    stdin: str


@dataclass
class FakeClaude:
    bin_dir: Path
    _calls_file: Path = field(init=False)
    _response_file: Path = field(init=False)

    def __post_init__(self):
        self._calls_file = self.bin_dir / "calls.jsonl"
        self._response_file = self.bin_dir / "response.json"
        self.respond({})

    def respond(self, payload) -> None:
        """다음 호출부터 stdout으로 내보낼 JSON 응답을 정한다."""
        (self.bin_dir / "responses.json").unlink(missing_ok=True)
        self._response_file.write_text(json.dumps(payload))

    def respond_sequence(self, payloads: list) -> None:
        """호출 순서별 응답(n번째 호출 = n번째 항목, 넘치면 마지막 항목). 호출 수는 지금까지의 전체 호출 기준이다."""
        (self.bin_dir / "responses.json").write_text(json.dumps(payloads))

    def delay(self, seconds: float) -> None:
        """응답 전에 기다린다(동시 실행이 겹치게 하는 테스트용)."""
        (self.bin_dir / "delay.txt").write_text(str(seconds))

    @property
    def calls(self) -> list[Call]:
        if not self._calls_file.exists():
            return []
        rows = [json.loads(line) for line in self._calls_file.read_text().splitlines() if line]
        return [Call(r["argv"], r["cwd"], r["env"], r["stdin"]) for r in rows]


@pytest.fixture
def fake_claude(tmp_path, monkeypatch) -> FakeClaude:
    bin_dir = tmp_path / "fake-claude-bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(_FAKE_CLAUDE_SCRIPT.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return FakeClaude(bin_dir)


@pytest.fixture
def claude_call_log():
    """helpers.claude_call_log(run_dir)의 얇은 fixture 별칭."""
    return _claude_call_log


# --- 브라우저 ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def playwright_instance():
    """세션에 하나뿐인 `sync_playwright()`. 한 세션에서 sync_playwright를 두 번 열면 "Sync API inside the asyncio loop"로
    실패하므로, 브라우저가 필요한 fixture는 모두 이것에서 chromium을 띄운다."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        yield playwright


@pytest.fixture(scope="session")
def browser(playwright_instance):
    """세션 공용 chromium(playwright). 세션이 끝나면 닫는다."""
    instance = playwright_instance.chromium.launch()
    try:
        yield instance
    finally:
        instance.close()


# --- docker ----------------------------------------------------------------------------
@dataclass(frozen=True)
class DockerSnap:
    containers: frozenset[str]
    networks: frozenset[str]
    volumes: frozenset[str]


def take_docker_snapshot() -> DockerSnap:
    return DockerSnap(
        containers=_docker_ids("ps", "-aq", "--no-trunc"),
        networks=_docker_ids("network", "ls", "-q", "--no-trunc"),
        volumes=_docker_ids("volume", "ls", "-q"),
    )


@pytest.fixture
def docker_snapshot() -> DockerSnap:
    return take_docker_snapshot()


@pytest.fixture(scope="session", autouse=True)
def session_resources_gate(test_run_label):
    """세션 종료 시 `test-run=td-test-<sessionId>` 라벨 자원이 0인지 확인한다. 남으면 세션 실패."""
    yield
    remaining = find_leaked_resources(test_run_label)
    for run_id in _SESSION_RUN_IDS:
        leaked = find_leaked_resources(f"td-{run_id}")
        if leaked:
            remaining[f"td-{run_id}"] = leaked
    if remaining:
        pytest.fail(f"테스트 자원 누수(라벨 {test_run_label} 및 이 세션의 td-<runId>): {remaining}", pytrace=False)


@pytest.fixture(scope="session")
def repo_snapshot() -> dict[str, bytes]:
    """REQ-054 검사용: 추적 파일 내용, git log -p 전체, 사이트 미러 내용을 세션당 1회만 읽는다."""
    git = lambda *a: subprocess.run(["git", *a], cwd=REPO_ROOT, capture_output=True).stdout
    chunks = []
    for name in git("ls-files", "-z").split(b"\0"):
        path = REPO_ROOT / name.decode() if name else None
        if path is not None and path.is_file():
            chunks.append(path.read_bytes())
    mirror = REPO_ROOT / "work" / "site-mirror"
    mirror_chunks = [p.read_bytes() for p in mirror.rglob("*") if p.is_file()] if mirror.exists() else []
    return {
        "tracked": b"\n".join(chunks),
        "git_log": git("log", "-p", "--all"),
        "mirror": b"\n".join(mirror_chunks),
    }


# --- SUT 컨테이너 환경(Task 4) -------------------------------------------------------------
class SutEnv:
    """env.sh 함수를 부르는 bash 구동기. 프로젝트·라벨은 테스트 세션 규칙(td-test-<sessionId>)을 따른다."""

    def __init__(self, tmp_path: Path, session_id: str, name: str):
        from helpers import AGENT_JAR, SUT_PACKAGES, petclinic_jar
        self.tmp_path = tmp_path
        self.label = f"td-test-{session_id}"
        self.project = f"td-test-{session_id}-{name}"
        self.run_dir = tmp_path / "runs" / f"test-{session_id}-{name}"
        (self.run_dir / "pids").mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
        self.env.update(
            TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(REPO_ROOT / "work"), TD_RUN_DIR=str(self.run_dir),
            TD_RUN_LABEL=self.label, TD_PROJECT_NAME=self.project,
            TD_SUT_JAR=str(petclinic_jar()), TD_AGENT_JAR=str(AGENT_JAR), TD_SUT_PACKAGES=SUT_PACKAGES,
            TD_SUT_PORT="8080", TD_SUT_HEALTH="/actuator/health",
        )

    def bash(self, script: str, timeout: int = 300, **extra_env: str) -> subprocess.CompletedProcess:
        header = f'source "{REPO_ROOT}/pipeline/lib/common.sh"\nsource "{REPO_ROOT}/pipeline/lib/env.sh"\n'
        return subprocess.run(["bash", "-c", header + script], capture_output=True, text=True,
                              env={**self.env, **extra_env}, timeout=timeout)

    def cleanup(self) -> None:
        subprocess.run(["docker", "compose", "-p", self.project, "down", "-v", "--remove-orphans"],
                       capture_output=True, timeout=180)


@pytest.fixture
def sut_env(tmp_path, session_id, request):
    created: list[SutEnv] = []

    def make(name: str) -> SutEnv:
        sut = SutEnv(tmp_path, session_id, name)
        created.append(sut)
        return sut

    yield make
    for sut in created:
        sut.cleanup()


# --- 실제 파이프라인 run(Task 5) ---------------------------------------------------------------
@pytest.fixture(scope="session")
def real_pipeline_run(tmp_path_factory, site_prefix):
    """real_pipeline_run("S00,S01", args=("--arms", "base"), **env) -> RunResult. 호출마다 run 디렉터리용 work를 새로 만들고
    tools·suts는 실제 work 캐시를 공유한다. TD_SITE_PREFIX를 항상 주므로 S13이 없어도 게시는 일어나지 않는다."""
    real_work = REPO_ROOT / "work"
    counter = {"n": 0}

    def run(only: str, sut_file: str | None = None, args: tuple[str, ...] = (), **env: str) -> "RunResult":
        counter["n"] += 1
        work = tmp_path_factory.mktemp(f"real-run{counter['n']}")
        # infra(terraform 상태)와 site-mirror(게시 미러)도 공유한다: S13이 둘을 TD_WORK_DIR 아래에서 읽는다.
        for shared in ("tools", "suts", "infra", "site-mirror"):
            (real_work / shared).mkdir(parents=True, exist_ok=True)
            (work / shared).symlink_to(real_work / shared)
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
        # 커밋된 스냅샷이 없는(입력이 바뀐) generation은 claude를 부르지 않고 실패시킨다: 테스트가 실제 생성 비용을 쓰지 않는다.
        full_env.update(TD_BDDGEN_REQUIRE_SNAPSHOT="1", TD_OWLGEN_REQUIRE_SNAPSHOT="1")
        full_env.update(TD_WORK_DIR=str(work), TD_ROOT=str(REPO_ROOT), TD_SITE_PREFIX=site_prefix, **env)
        # 새 세션(프로세스 그룹)으로 띄우고, 시간이 넘으면 그룹에 TERM을 보내 파이프라인 trap이 컨테이너를 정리하게 한다.
        sut_args = ["--sut-file", sut_file] if sut_file else []
        sut_name = yaml.safe_load(Path(sut_file).read_text())["name"] if sut_file else "petclinic"
        proc = subprocess.Popen(["bash", str(RUN_ALL), sut_name, *sut_args, "--only", only, *args], env=full_env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            try:
                stdout, stderr = proc.communicate(timeout=3300)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.communicate()
                pytest.fail(f"real pipeline run timed out (only={only})", pytrace=False)
        finally:
            runs_dir = work / "runs"
            if runs_dir.exists():  # 세션 종료 시 라벨 td-<runId> 누수를 검사한다
                _SESSION_RUN_IDS.extend(p.name for p in runs_dir.iterdir() if p.is_dir())
        return RunResult(proc.returncode, stdout, stderr, work)

    return run


class AsyncRun:
    """비동기로 띄운 실제 파이프라인 run(중단 테스트용). 새 세션이므로 프로세스 그룹에 시그널을 보낼 수 있다."""

    def __init__(self, proc: subprocess.Popen, work: Path):
        self.proc, self.work = proc, work

    def interrupt(self) -> None:
        os.killpg(self.proc.pid, signal.SIGINT)

    def _group_alive(self) -> bool:
        try:
            os.killpg(self.proc.pid, 0)
        except ProcessLookupError:
            return False
        return True

    def wait(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None and not self._group_alive():
                return True
            time.sleep(0.5)
        return False

    def kill_if_alive(self) -> None:
        if self._group_alive():
            os.killpg(self.proc.pid, signal.SIGKILL)
        self.proc.wait(timeout=30)


@pytest.fixture(scope="session")
def real_pipeline_run_async(tmp_path_factory, site_prefix):
    """real_pipeline_run의 비동기판: run을 띄우고 AsyncRun을 돌려준다(호출자가 종료까지 책임진다)."""
    real_work = REPO_ROOT / "work"

    def start(only: str, **env: str) -> AsyncRun:
        work = tmp_path_factory.mktemp("real-run-async")
        for shared in ("tools", "suts"):
            (work / shared).symlink_to(real_work / shared)
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
        full_env.update(TD_BDDGEN_REQUIRE_SNAPSHOT="1", TD_OWLGEN_REQUIRE_SNAPSHOT="1")
        full_env.update(TD_WORK_DIR=str(work), TD_ROOT=str(REPO_ROOT), TD_SITE_PREFIX=site_prefix, **env)
        proc = subprocess.Popen(["bash", str(RUN_ALL), "petclinic", "--only", only], env=full_env, text=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        _ASYNC_WORKS.append(work)
        return AsyncRun(proc, work)

    yield start
    for work in _ASYNC_WORKS:
        runs_dir = work / "runs"
        if runs_dir.exists():
            _SESSION_RUN_IDS.extend(p.name for p in runs_dir.iterdir() if p.is_dir())


_ASYNC_WORKS: list[Path] = []


@pytest.fixture(scope="session")
def m1_run(real_pipeline_run):
    """`run-all.sh petclinic --only S00,S01`의 결과(세션 내 1회 실행해 재사용). S13을 돌리지 않으므로 게시는 없다."""
    return real_pipeline_run("S00,S01")


# --- S11 Sonar 수용 하네스(Task 13) ------------------------------------------------------------
import tempfile
import threading
import time


def sonar_ssh(local_env: dict, sql: str, *, port: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    """Sonar Postgres에 SQL 하나를 실행한다(허가된 user_tokens 점검·fixture 용도만). 결과는 -tA 형식."""
    ssh = ["ssh", "-i", local_env["TD_SSH_KEY_PATH"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "LogLevel=ERROR"]
    if port:
        ssh += ["-p", port]
    remote = f'docker exec sonarqube-db-1 psql -U sonar -d sonar -v ON_ERROR_STOP=1 -tAc "{sql}"'
    return subprocess.run([*ssh, f"ubuntu@{local_env['TD_LIGHTSAIL_IP']}", remote], capture_output=True, text=True, timeout=timeout)


def token_rows(local_env: dict, name_like: str) -> list[str]:
    done = sonar_ssh(local_env, f"select name||'|'||created_at||'|'||expiration_date from user_tokens where name like '{name_like}' order by name")
    assert done.returncode == 0, done.stderr[-300:]
    return [line for line in done.stdout.splitlines() if line]


def token_count(local_env: dict) -> int:
    done = sonar_ssh(local_env, "select count(*) from user_tokens")
    assert done.returncode == 0, done.stderr[-300:]
    return int(done.stdout.strip())


@dataclass
class ObservedRun:
    result: "RunResult"
    token: str
    ps_lines: set


@pytest.fixture(scope="session")
def s11_run(real_pipeline_run, local_env):
    """`--only S00,S01,S08,S11` 실제 run 1회(REQ-037/038/066/063 공유). 토큰 관측 훅 파일을 읽고, 실행 중 프로세스 argv를 폴링한다."""
    observe_dir = Path(tempfile.mkdtemp(prefix="td-observe-"))
    observe = observe_dir / "token"
    lines: set = set()
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            out = subprocess.run(["ps", "-axo", "args"], capture_output=True, text=True).stdout
            lines.update(out.splitlines())
            time.sleep(0.3)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    try:
        result = real_pipeline_run("S00,S01,S08,S11", TD_SONAR_TOKEN_OBSERVE=str(observe))
        token = observe.read_text() if observe.exists() else ""
    finally:
        stop.set()
        poller.join(timeout=5)
        shutil.rmtree(observe_dir, ignore_errors=True)
    return ObservedRun(result, token, lines)


# --- 이후 Task가 채우는 fixture ----------------------------------------------------------
@pytest.fixture(scope="session")
def injected_petclinic_run(real_pipeline_run):
    """주입 환경(TD_SITE_PREFIX=_test/<sessionId>/)에서 petclinic을 `--only S00,S01,S08,S13`으로 실제 실행·게시한다(세션당 1회)."""
    return real_pipeline_run("S00,S01,S08,S13")


MINI_SUT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mini-sut"
MINI_SUT_WORK = REPO_ROOT / "work" / "fixtures" / "mini-sut"


@pytest.fixture(scope="session")
def mini_sut_sut_file() -> Path:
    """(주의: 이 fixture와 mini_sut_run, injected_petclinic_run은 고정 경로 work/fixtures/mini-sut, work/suts/mini-sut를 쓰는 세션 fixture라
    pytest-xdist 병렬 실행에서는 안전하지 않다. 이 스위트는 단일 프로세스로 돌린다.)
    mini-sut fixture를 work/fixtures/mini-sut로 복사하고 git 저장소(커밋 2개)로 만든 뒤 repo를 채운 sut.yaml 경로를 돌려준다.
    설명 파일 디렉터리에는 expected-tests.yaml이 함께 있다. 이전 시도의 clone 캐시(work/suts/mini-sut)는 지운다."""
    shutil.rmtree(MINI_SUT_WORK, ignore_errors=True)
    shutil.rmtree(REPO_ROOT / "work" / "suts" / "mini-sut", ignore_errors=True)
    repo, desc = MINI_SUT_WORK / "repo", MINI_SUT_WORK / "desc"
    shutil.copytree(MINI_SUT_FIXTURE / "app", repo, ignore=shutil.ignore_patterns("build", ".gradle"))
    desc.mkdir(parents=True)
    for name in ("sut.yaml", "expected-tests.yaml"):
        shutil.copyfile(MINI_SUT_FIXTURE / name, desc / name)
    sut_yaml = desc / "sut.yaml"
    sut_yaml.write_text(sut_yaml.read_text().replace("__REPO__", str(repo)))
    git = lambda *a: subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *GIT_IDENTITY, *a], cwd=repo, check=True, capture_output=True)
    git("init", "-b", "main")
    git("add", ".")
    git("commit", "-m", "mini-sut: initial")
    (repo / "CHANGELOG.md").write_text("# mini-sut\n\n- tags endpoint\n")  # tia.range(HEAD~1..HEAD)가 유효하도록 두 번째 커밋을 둔다
    git("add", ".")
    git("commit", "-m", "mini-sut: changelog")
    return sut_yaml


@pytest.fixture(scope="session")
def mini_sut_run(real_pipeline_run, injected_petclinic_run, mini_sut_sut_file):
    """petclinic run이 먼저 게시된 같은 접두에 mini-sut를 `--sut-file`로 `--only S00,S01,S08,S13` 실행·게시한다."""
    return real_pipeline_run("S00,S01,S08,S13", sut_file=str(mini_sut_sut_file))


@pytest.fixture(scope="session")
def run_under_test(request):
    """세션 파일이 있으면 기준 run, 없으면 m1_run(`--only S00,S01`)."""
    if SESSION_FILE.exists():
        return request.getfixturevalue("baseline_run")
    return request.getfixturevalue("m1_run")


STUB_STAGE_DIR = REPO_ROOT / "tests" / "fixtures" / "stub-stages"
RUN_ALL = REPO_ROOT / "pipeline" / "run-all.sh"
GIT_IDENTITY = ["-c", "user.name=td-test", "-c", "user.email=td-test@example.invalid"]


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    work_dir: Path

    @property
    def run_dir(self) -> Path:
        runs = sorted(p for p in (self.work_dir / "runs").glob("*") if p.is_dir()) if (self.work_dir / "runs").exists() else []
        assert len(runs) == 1, f"run 디렉터리가 정확히 1개여야 한다: {runs}\n{self.stderr}"
        return runs[0]

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    @property
    def run_json(self) -> dict:
        return json.loads((self.run_dir / "run.json").read_text())

    def stage(self, stage_id: str) -> dict:
        return json.loads((self.run_dir / "stages" / f"{stage_id}.json").read_text())

    def stages(self) -> dict[str, dict]:
        return {p.stem: json.loads(p.read_text()) for p in sorted((self.run_dir / "stages").glob("S*.json"))}


@pytest.fixture(scope="session")
def mini_sut_repo(tmp_path_factory) -> Path:
    """스텁 run용 작은 로컬 git 저장소(원격 clone 없이 SUT 커밋을 해석한다)."""
    repo = tmp_path_factory.mktemp("stub-sut-repo")
    git = lambda *a: subprocess.run(["git", *GIT_IDENTITY, *a], cwd=repo, check=True, capture_output=True)
    git("init", "-b", "main")
    (repo / "README.md").write_text("stub sut\n")
    git("add", ".")
    git("commit", "-m", "init")
    return repo


class StubRunner:
    """tests/fixtures/stub-stages로 run-all.sh를 돌린다. 호출마다 work 디렉터리를 새로 만든다."""

    def __init__(self, tmp_path: Path, sut_repo: Path, site_prefix: str):
        self.tmp_path = tmp_path
        self.sut_repo = sut_repo
        self.site_prefix = site_prefix
        self.sut_file = tmp_path / "sut.yaml"
        self.sut_file.write_text(f"name: stub\nrepo: {sut_repo}\nref: main\n")
        self.calls = 0

    def run(self, *args: str, sut: str = "stub", use_prefix: bool = True, use_stub_dir: bool = True,
            **env: str) -> RunResult:
        self.calls += 1
        work_dir = self.tmp_path / f"work{self.calls}"
        full_env = {k: v for k, v in os.environ.items()
                    if k not in ("TD_FAIL_STAGE", "TD_NOW", "TD_NOW_FINISHED", "TD_SITE_PREFIX", "TD_STAGE_DIR")}
        full_env.update(TD_WORK_DIR=str(work_dir), TD_ROOT=str(REPO_ROOT))
        if use_stub_dir:
            full_env["TD_STAGE_DIR"] = str(STUB_STAGE_DIR)
        if use_prefix:
            full_env["TD_SITE_PREFIX"] = self.site_prefix
        full_env.update(env)
        done = subprocess.run(["bash", str(RUN_ALL), sut, "--sut-file", str(self.sut_file), *args],
                              capture_output=True, text=True, env=full_env, timeout=300)
        return RunResult(done.returncode, done.stdout, done.stderr, work_dir)


@pytest.fixture
def stub_stages(tmp_path, mini_sut_repo, site_prefix) -> StubRunner:
    return StubRunner(tmp_path, mini_sut_repo, site_prefix)


@dataclass
class SessionRun:
    """run_baseline.py가 기록한 run 하나(기준 또는 두 번째). RunResult와 같은 조회 메서드를 가진다."""
    record: dict
    session: dict

    @property
    def run_id(self) -> str:
        return self.record["runId"]

    @property
    def run_dir(self) -> Path:
        return REPO_ROOT / self.record["runDir"]

    @property
    def returncode(self) -> int:
        return self.record["exitCode"]

    @property
    def prefix(self) -> str:
        return self.session.get("prefix", "")

    @property
    def run_json(self) -> dict:
        return json.loads((self.run_dir / "run.json").read_text())

    def stage(self, stage_id: str) -> dict:
        return json.loads((self.run_dir / "stages" / f"{stage_id}.json").read_text())

    def stages(self) -> dict[str, dict]:
        return {p.stem: json.loads(p.read_text()) for p in sorted((self.run_dir / "stages").glob("S*.json"))}


def load_session_run(label: str) -> SessionRun:
    """세션 파일에서 `baseline` 또는 `second` 기록을 읽는다. 없거나 그 run 디렉터리가 없으면 실패한다."""
    if not SESSION_FILE.exists():
        pytest.fail(f"{SESSION_FILE}가 없다: tests/acceptance/run_baseline.py로 기준 run과 두 번째 run을 먼저 실행한다",
                    pytrace=False)
    session = json.loads(SESSION_FILE.read_text())
    # 기본 세션 파일은 운영 게시 증거만 담는다. 디버깅 세션(접두 게시)이 운영 기준 REQ(044, 047, 048, 049, 051, 068, 071,
    # 073)를 green으로 만들지 못하게, 세션 파일을 바꿔 끼우지 않았다면 접두가 비어 있어야 한다.
    if not os.environ.get("TD_ACCEPTANCE_SESSION_FILE") and session.get("prefix") != "":
        pytest.fail(f"기본 세션 파일의 prefix가 운영('')이 아니다: {session.get('prefix')!r} ({SESSION_FILE})", pytrace=False)
    record = session.get(label)
    if not record:
        detail = f" (secondError: {session['secondError']})" if label == "second" and session.get("secondError") else ""
        pytest.fail(f"세션 파일에 '{label}' run 기록이 없다: {SESSION_FILE}{detail}", pytrace=False)
    run = SessionRun(record, session)
    if not (run.run_dir / "run.json").exists():
        pytest.fail(f"세션 파일의 {label} run 디렉터리가 없다: {run.run_dir}", pytrace=False)
    return run


@pytest.fixture(scope="session")
def baseline_run() -> SessionRun:
    return load_session_run("baseline")


@pytest.fixture(scope="session")
def second_run() -> SessionRun:
    return load_session_run("second")


@dataclass
class BaselineSite:
    """기준 run 세션 뒤의 운영 사이트(화면 재설계 REQ-130/131/139/140). 경로는 사이트 루트(접두 포함) 기준 상대 경로다."""
    sut: str
    run_id: str
    project: str
    run_dir: Path
    domain: str
    prefix: str = ""

    @property
    def run_path(self) -> str:
        return f"suts/{self.sut}/runs/{self.run_id}/"

    def url(self, path: str) -> str:
        return f"https://reports.{self.domain}/{self.prefix}{path}"

    def dash_url(self, path: str) -> str:
        return f"https://dash.{self.domain}/{self.prefix}{path}"

    def get(self, path: str, host: str = "reports") -> tuple[int, bytes]:
        from helpers import https_get
        return https_get(f"{host}.{self.domain}", self.domain, f"/{self.prefix}{path}")


@pytest.fixture(scope="session")
def baseline_site(baseline_run, local_env) -> BaselineSite:
    """세션 파일의 기준 run과 운영 `projects.json`에서 찾은 그 SUT의 과제. 인덱스 전용 게시 기록이 없거나 failed면 실패한다
    (요구사항명세 §0: 기준 run 세션은 두 run 뒤 인덱스 전용 게시 한 번까지다)."""
    index_publish = baseline_run.session.get("indexPublish")
    if not index_publish or index_publish.get("status") not in ("passed", "degraded"):
        pytest.fail(f"세션 파일의 인덱스 전용 게시 기록이 없거나 성공이 아니다: {index_publish!r} ({SESSION_FILE})", pytrace=False)
    site = BaselineSite(sut=baseline_run.session["sut"], run_id=baseline_run.run_id, project="",
                        run_dir=baseline_run.run_dir, domain=local_env["TD_DOMAIN"], prefix=baseline_run.prefix)
    status, body = site.get("projects.json")
    if status != 200:
        pytest.fail(f"운영 projects.json을 읽지 못했다: HTTP {status}", pytrace=False)
    linked = [entry["name"] for entry in json.loads(body)["projects"] if entry.get("sut") == site.sut]
    if len(linked) != 1:
        pytest.fail(f"운영 projects.json에서 SUT {site.sut}와 이어진 과제가 하나가 아니다: {linked}", pytrace=False)
    site.project = linked[0]
    return site


@pytest.fixture
def injected_run(stub_stages):
    """injected_run("S05", args=(...), **env): TD_FAIL_STAGE=<stage_spec>으로 스텁 run을 돌린다."""

    def run(stage_spec: str, *, args=(), **env: str) -> RunResult:
        if stage_spec:
            env["TD_FAIL_STAGE"] = stage_spec
        return stub_stages.run(*args, **env)

    return run


# --- S13 게시 하네스(Task 10) --------------------------------------------------------------------
S13_SCRIPT = REPO_ROOT / "pipeline" / "S13-publish.sh"


@pytest.fixture(scope="session")
def infra_outputs() -> dict:
    state_file = REPO_ROOT / "work" / "infra" / "terraform.tfstate"
    if not state_file.exists():
        pytest.fail("work/infra/terraform.tfstate가 없다(infra/static/apply.sh를 먼저 실행한다)", pytrace=False)
    return {k: v["value"] for k, v in json.loads(state_file.read_text())["outputs"].items()}


@pytest.fixture(scope="session")
def s3_client():
    import boto3
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))


@pytest.fixture(scope="session")
def bucket(infra_outputs) -> str:
    return infra_outputs["bucket"]


class Publisher:
    """local run 디렉터리를 만들고 실제 S13-publish.sh를 돌린다(TD_SITE_PREFIX=_test/<sessionId>/, 실제 S3·CloudFront·Lightsail)."""

    def __init__(self, base: Path, site_prefix: str):
        self.base = base
        self.prefix = site_prefix
        self.counter = 0

    def new_run(self, sut: str, **kwargs) -> tuple[str, Path]:
        from helpers import make_local_run
        self.counter += 1
        run_id = f"20261119-{self.counter:06d}Z-b6f9393-manual-{uuid.uuid4().hex[:8]}"
        return run_id, make_local_run(self.base, sut, run_id, **kwargs)

    def env(self, run_dir: Path, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
        env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(REPO_ROOT / "work"), TD_RUN_DIR=str(run_dir),
                   TD_SITE_PREFIX=self.prefix, **extra)
        return env

    def s13(self, run_dir: Path, *args: str, timeout: int = 1200, **extra: str) -> subprocess.CompletedProcess:
        run = json.loads((run_dir / "run.json").read_text())
        return subprocess.run(["bash", str(S13_SCRIPT), run["sut"], run["runId"], *args], capture_output=True, text=True,
                              env=self.env(run_dir, **extra), timeout=timeout)

    def popen(self, run_dir: Path, **extra: str) -> subprocess.Popen:
        run = json.loads((run_dir / "run.json").read_text())
        return subprocess.Popen(["bash", str(S13_SCRIPT), run["sut"], run["runId"]], env=self.env(run_dir, **extra), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

    @staticmethod
    def stage13(run_dir: Path) -> dict:
        return json.loads((run_dir / "stages" / "S13.json").read_text())


@pytest.fixture(scope="session")
def publisher(tmp_path_factory, site_prefix) -> Publisher:
    return Publisher(tmp_path_factory.mktemp("s13-runs"), site_prefix)


@pytest.fixture(scope="session")
def published_runs(publisher, site_prefix):
    """세션 접두에 실제로 두 run을 게시한다(REQ-044/047/048/068/071이 공유). dict(sut, runs=[(runId, run_dir, result)...])."""
    sut = "td-pub"
    runs = []
    for _ in range(2):
        run_id, run_dir = publisher.new_run(sut)
        done = publisher.s13(run_dir)
        runs.append((run_id, run_dir, done))
    for run_id, run_dir, done in runs:
        assert done.returncode == 0, f"S13 실패: {done.stderr[-1500:]}"
    return {"sut": sut, "runs": runs, "prefix": site_prefix}


# --- S02 bbtg 스테이지 하네스(Task 16) --------------------------------------------------------------
S02_SCRIPT = REPO_ROOT / "pipeline" / "S02-bbtg.sh"
PETCLINIC_SUT_FILE = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"
BBTG_TOOLS_DIR = REPO_ROOT / "work" / "tools"
SUT_COPY_IGNORE = shutil.ignore_patterns("build", ".gradle", ".git", ".bbtg")


@dataclass
class S02Run:
    returncode: int
    stdout: str
    stderr: str
    run_dir: Path
    sut_src: Path

    @property
    def out_dir(self) -> Path:
        return self.run_dir / "S02" / "bbtg"

    @property
    def stage(self) -> dict:
        return json.loads((self.run_dir / "stages" / "S02.json").read_text())

    @property
    def manifest(self) -> dict:
        return json.loads((self.out_dir / "manifest.json").read_text())

    @property
    def clean_dir(self) -> Path:
        return self.out_dir / "clean"


@pytest.fixture(scope="session")
def petclinic_sut_master(tmp_path_factory) -> Path:
    """S00이 clone해 둔 petclinic 소스를 build 산출물 없이 한 번 복사해 두는 원본(테스트마다 다시 복사해 쓴다)."""
    source = REPO_ROOT / "work" / "suts" / "petclinic" / "src"
    if not (source / "src" / "main" / "java").is_dir() or not (BBTG_TOOLS_DIR / "bbtg" / ".venv" / "bin" / "python").exists():
        pytest.fail("S00이 준비한 petclinic clone과 bbtg venv가 필요하다(work/suts/petclinic/src, work/tools/bbtg/.venv)", pytrace=False)
    master = tmp_path_factory.mktemp("petclinic-master") / "src"
    shutil.copytree(source, master, ignore=SUT_COPY_IGNORE, symlinks=True)
    return master


@pytest.fixture
def s02_stage(tmp_path, petclinic_sut_master):
    """s02_stage(checkout=<tmp 하위 경로>, **env) -> S02Run. SUT 복사본에서 pipeline/S02-bbtg.sh를 단독 실행한다.
    S00 산출물은 실제 도구 경로를 가리키는 S00.json으로 대신한다. 호출마다 run 디렉터리가 새로 생긴다."""
    counter = {"n": 0}

    def run(checkout: str = "checkout", sut_file: Path = PETCLINIC_SUT_FILE, **env: str) -> S02Run:
        counter["n"] += 1
        sut_src = tmp_path / f"s02-{counter['n']}" / checkout
        sut_src.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(petclinic_sut_master, sut_src, symlinks=True)
        run_dir = tmp_path / f"s02-run-{counter['n']}" / "runs" / "20990101-000000Z-s02test0-manual-00000000"
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
        full_env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(run_dir.parents[1]), TD_RUN_DIR=str(run_dir),
                        TD_SUT_SRC=str(sut_src), TD_SUT_FILE=str(sut_file), TD_SITE_PREFIX="_test/s02-stage/")
        full_env.update(env)
        init = subprocess.run(
            [sys.executable, "-m", "td.state", "init", str(run_dir), "--run-id", run_dir.name, "--sut", "petclinic",
             "--commit", "b6f939355e8790202ddfc71e3f3507252745ed37"],
            capture_output=True, text=True, env={**full_env, "PYTHONPATH": str(REPO_ROOT / "site-gen")})
        assert init.returncode == 0, init.stderr
        (run_dir / "stages").mkdir(parents=True, exist_ok=True)
        (run_dir / "pids").mkdir(exist_ok=True)
        (run_dir / "stages" / "S00.json").write_text(json.dumps(
            {"id": "S00", "status": "passed", "reason": None, "outputs": {"toolsDir": str(BBTG_TOOLS_DIR)}}))
        done = subprocess.run(["bash", str(S02_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True,
                              env=full_env, timeout=1500)
        return S02Run(done.returncode, done.stdout, done.stderr, run_dir, sut_src)

    return run


@pytest.fixture
def s02_default(s02_stage, fake_claude):
    """가짜 claude를 PATH 앞에 둔 채 S02를 한 번 돌린다(REQ-013이 호출 0회를 검증한다)."""
    return s02_stage()
