"""수용 테스트 공용 하네스.

전제(AWS, SSH, Docker, claude)가 없으면 skip이 아니라 실패한다.
이후 Task가 채우는 fixture는 pytest.fail("requires Task N")로 명시적으로 실패한다.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from helpers import claude_call_log as _claude_call_log
from helpers import docker_ids as _docker_ids
from helpers import find_leaked_resources

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_FILE = REPO_ROOT / "work" / "acceptance-session.json"
LOCAL_ENV_PATH = REPO_ROOT / "infra" / "local.env"

_SESSION_ID = os.environ.get("TD_TEST_SESSION_ID") or uuid.uuid4().hex[:8]


# --- baseline 마커 (개정 A) ---------------------------------------------------
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "baseline: 기준 run 증거(work/acceptance-session.json)가 필요한 E2E 테스트. 없으면 실패한다.",
    )


def pytest_runtest_setup(item):
    if item.get_closest_marker("baseline") and not SESSION_FILE.exists():
        pytest.fail(
            "baseline 테스트는 work/acceptance-session.json(기준 run 증거)이 필요하다. "
            "기준 run 전에는 실패가 정상이며 Task 25에서 green이 된다.",
            pytrace=False,
        )


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
        self._response_file.write_text(json.dumps(payload))

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
    if remaining:
        pytest.fail(f"테스트 자원 누수(라벨 {test_run_label}): {remaining}", pytrace=False)


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


# --- 이후 Task가 채우는 fixture ----------------------------------------------------------
@pytest.fixture(scope="session")
def m1_run():
    pytest.fail("requires Task 5 (run-all.sh --only S00,S01 실행 helper)", pytrace=False)


@pytest.fixture(scope="session")
def injected_petclinic_run():
    pytest.fail("requires Task 15 (run-all.sh --only S00,S01,S08,S13 + TD_SITE_PREFIX)", pytrace=False)


@pytest.fixture(scope="session")
def run_under_test():
    pytest.fail("requires Task 25 (세션 파일이 있으면 기준 run, 없으면 m1_run)", pytrace=False)


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


@pytest.fixture(scope="session")
def baseline_run():
    pytest.fail("requires Task 25 (기준 run)", pytrace=False)


@pytest.fixture(scope="session")
def second_run():
    pytest.fail("requires Task 25 (두 번째 run)", pytrace=False)


@pytest.fixture
def injected_run(stub_stages):
    """injected_run("S05", args=(...), **env): TD_FAIL_STAGE=<stage_spec>으로 스텁 run을 돌린다."""

    def run(stage_spec: str, *, args=(), **env: str) -> RunResult:
        if stage_spec:
            env["TD_FAIL_STAGE"] = stage_spec
        return stub_stages.run(*args, **env)

    return run
