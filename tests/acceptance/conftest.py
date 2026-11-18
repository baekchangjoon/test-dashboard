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
                         "env": dict(os.environ), "stdin": stdin_text}}) + "\\n")
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
    """claude_call_log(run_dir) -> list[dict]: shim이 남긴 호출 기록(llm-calls.jsonl)을 읽는다."""

    def read(run_dir) -> list[dict]:
        log_file = Path(run_dir) / "llm-calls.jsonl"
        if not log_file.exists():
            return []
        return [json.loads(line) for line in log_file.read_text().splitlines() if line]

    return read


# --- docker ----------------------------------------------------------------------------
@dataclass(frozen=True)
class DockerSnap:
    containers: frozenset[str]
    networks: frozenset[str]
    volumes: frozenset[str]


def _docker_ids(*args: str) -> frozenset[str]:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.fail(f"docker CLI를 쓸 수 없다: {type(exc).__name__}", pytrace=False)
    if result.returncode != 0:
        pytest.fail(f"docker {' '.join(args)} 실패: {result.stderr.strip()[:200]}", pytrace=False)
    return frozenset(line for line in result.stdout.split() if line)


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
    flt = f"label={'test-run=' + test_run_label}"
    leaked = {
        "containers": _docker_ids("ps", "-aq", "--filter", flt),
        "networks": _docker_ids("network", "ls", "-q", "--filter", flt),
        "volumes": _docker_ids("volume", "ls", "-q", "--filter", flt),
    }
    remaining = {kind: sorted(ids) for kind, ids in leaked.items() if ids}
    if remaining:
        pytest.fail(f"테스트 자원 누수(라벨 {test_run_label}): {remaining}", pytrace=False)


# --- 이후 Task가 채우는 fixture ----------------------------------------------------------
@pytest.fixture(scope="session")
def m1_run():
    pytest.fail("requires Task 2 (run-all.sh --only S00,S01 실행 helper)", pytrace=False)


@pytest.fixture(scope="session")
def injected_petclinic_run():
    pytest.fail("requires Task 2 (run-all.sh --only S00,S01,S08,S13 + TD_SITE_PREFIX)", pytrace=False)


@pytest.fixture(scope="session")
def run_under_test():
    pytest.fail("requires Task 2 (세션 파일이 있으면 기준 run, 없으면 m1_run)", pytrace=False)


@pytest.fixture
def stub_stages():
    pytest.fail("requires Task 2 (TD_STAGE_DIR=tests/fixtures/stub-stages, TD_SITE_PREFIX 필요)", pytrace=False)


@pytest.fixture(scope="session")
def baseline_run():
    pytest.fail("requires Task 25 (기준 run)", pytrace=False)


@pytest.fixture(scope="session")
def second_run():
    pytest.fail("requires Task 25 (두 번째 run)", pytrace=False)


@pytest.fixture
def injected_run():
    pytest.fail("requires Task 2 (injected_run(stage_spec, **env))", pytrace=False)
