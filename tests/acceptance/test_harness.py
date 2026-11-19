"""하네스 자체 검증(Unit/Int). REQ 직접 대응 없음."""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "pipeline" / "lib" / "claude-shim"


def test_site_prefix_format(site_prefix, session_id):
    assert site_prefix == f"_test/{session_id}/"


def test_local_env_has_required_keys(local_env):
    for key in ["TD_AWS_ACCOUNT_ID", "TD_LIGHTSAIL_IP", "TD_IAM_USER", "TD_SSH_KEY_PATH",
                "TD_DOMAIN", "TD_SUT_USER", "TD_SUT_PASS"]:
        assert key in local_env


def test_fake_claude_records_and_responds(fake_claude, tmp_path):
    fake_claude.respond({"result": "ok"})
    out = subprocess.run(["claude", "-p", "--model", "m"], input="hello", capture_output=True,
                         text=True, cwd=tmp_path)
    assert json.loads(out.stdout) == {"result": "ok"}
    [call] = fake_claude.calls
    assert call.argv == ["-p", "--model", "m"]
    assert call.cwd == str(tmp_path.resolve()) or call.cwd == str(tmp_path)
    assert call.stdin == "hello"
    assert "PATH" in call.env


def test_claude_call_log_reads_jsonl(claude_call_log, tmp_path):
    assert claude_call_log(tmp_path) == []
    (tmp_path / "llm-calls.jsonl").write_text('{"a":1}\n{"a":2}\n')
    assert claude_call_log(tmp_path) == [{"a": 1}, {"a": 2}]


def test_shim_logs_flags_without_prompt_and_execs_real(tmp_path):
    real = tmp_path / "real-claude"
    real.write_text('#!/usr/bin/env bash\necho "real:$*"\n')
    real.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    env = {"PATH": "/usr/bin:/bin", "TD_REAL_CLAUDE": str(real), "TD_LLM_CALL_LOG": str(log)}
    out = subprocess.run([str(SHIM), "-p", "SECRET PROMPT", "--output-format", "json"],
                         env=env, capture_output=True, text=True, cwd=tmp_path)
    assert out.returncode == 0
    assert "real:-p SECRET PROMPT --output-format json" in out.stdout
    record = json.loads(log.read_text().splitlines()[0])
    assert "SECRET PROMPT" not in log.read_text()
    assert record["argv"] == ["-p", "<other>", "--output-format"]
    assert record["cwd"] and record["ts"]


def test_shim_does_not_log_inline_values_or_dash_prompts(tmp_path):
    real = tmp_path / "real-claude"
    real.write_text("#!/usr/bin/env bash\nexit 0\n")
    real.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    env = {"PATH": "/usr/bin:/bin", "TD_REAL_CLAUDE": str(real), "TD_LLM_CALL_LOG": str(log)}
    subprocess.run([str(SHIM), "--model=SECRETMODEL", "--system-prompt", "SECRETSYS", "--evil=SECRETX",
                    "-p", "--SECRET-dash-prompt"], env=env, cwd=tmp_path, check=True)
    text = log.read_text()
    assert "SECRET" not in text
    assert json.loads(text)["argv"] == ["--model", "--system-prompt", "<other>", "-p", "<other>"]


def test_shim_skips_itself_on_path(tmp_path):
    shim_dir = tmp_path / "shimbin"
    shim_dir.mkdir()
    (shim_dir / "claude").symlink_to(SHIM)
    real_dir = tmp_path / "realbin"
    real_dir.mkdir()
    real = real_dir / "claude"
    real.write_text('#!/usr/bin/env bash\necho real-found\n')
    real.chmod(0o755)
    env = {"PATH": f"{shim_dir}:{real_dir}:/usr/bin:/bin"}
    out = subprocess.run([str(shim_dir / "claude"), "-p"], env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "real-found"


def test_docker_snapshot_has_id_sets(docker_snapshot):
    assert isinstance(docker_snapshot.containers, frozenset)
    assert docker_snapshot.networks, "기본 네트워크(bridge 등)가 있어야 한다"


def _conftest_module():
    import sys
    return next(m for n, m in sys.modules.items() if n.endswith("conftest") and hasattr(m, "SESSION_FILE"))


class _FakeItem:
    def __init__(self, marked):
        self._marked = marked

    def get_closest_marker(self, name):
        return object() if self._marked and name == "baseline" else None


def test_baseline_marker_fails_without_session_file(monkeypatch, tmp_path):
    conftest = _conftest_module()
    monkeypatch.setattr(conftest, "SESSION_FILE", tmp_path / "missing.json")
    with pytest.raises(pytest.fail.Exception):
        conftest.pytest_runtest_setup(_FakeItem(marked=True))
    conftest.pytest_runtest_setup(_FakeItem(marked=False))  # 마커가 없으면 통과


def test_baseline_marker_passes_with_session_file(monkeypatch, tmp_path):
    conftest = _conftest_module()
    session_file = tmp_path / "acceptance-session.json"
    session_file.write_text("{}")
    monkeypatch.setattr(conftest, "SESSION_FILE", session_file)
    conftest.pytest_runtest_setup(_FakeItem(marked=True))


@pytest.mark.parametrize("name", ["run_under_test",
                                  "baseline_run", "second_run"])
def test_pending_fixtures_fail_with_clear_message(name, request):
    with pytest.raises(pytest.fail.Exception, match="requires Task"):
        request.getfixturevalue(name)


def test_gate_detects_labeled_container(session_id):
    from helpers import find_leaked_resources
    label_value = f"td-test-{session_id}"
    run = subprocess.run(["docker", "run", "--rm", "-d", "--label", f"test-run={label_value}",
                          "busybox", "sleep", "30"], capture_output=True, text=True)
    container_id = run.stdout.strip()
    try:
        assert run.returncode == 0, f"docker run 실패: {run.stderr.strip()[:200]}"
        leaked = find_leaked_resources(label_value)
        assert any(cid.startswith(container_id[:12]) for cid in leaked.get("containers", []))
    finally:
        if container_id:
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
    assert find_leaked_resources(label_value) == {}


# --- E2E 하네스(Task 20, REQ-026/027): Gradle 서브프로젝트를 실제로 실행한다 -----------------------------------
import os
import xml.etree.ElementTree as ET

import yaml

E2E_DIR = REPO_ROOT / "e2e"
SUT_FILE = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"
HARNESS_RESULTS = E2E_DIR / "harness" / "build" / "test-results" / "test"


def _java17_home() -> str:
    out = subprocess.run(["/usr/libexec/java_home", "-v", "17"], capture_output=True, text=True)
    assert out.returncode == 0, f"JDK 17이 필요하다: {out.stderr.strip()}"
    return out.stdout.strip()


def _gradle(args: list[str], *, properties: dict[str, str] | None = None, timeout: int = 900,
            env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """e2e/gradlew --no-daemon. 시스템 속성은 -D로 넘기지 않고 JAVA_TOOL_OPTIONS 없이 build.gradle이 전달하는 -Ptd.* 로 넘긴다."""
    command = ["./gradlew", "--no-daemon", "--console=plain", *args]
    for key, value in (properties or {}).items():
        command.append(f"-P{key}={value}")
    env = {**os.environ, "JAVA_HOME": _java17_home(), **(env_extra or {})}
    return subprocess.run(command, cwd=E2E_DIR, capture_output=True, text=True, env=env, timeout=timeout)


def _testcases(report_name: str) -> list[ET.Element]:
    report = HARNESS_RESULTS / f"TEST-td.harness.{report_name}.xml"
    assert report.is_file(), f"JUnit XML이 없다: {report}"
    return list(ET.parse(report).getroot().iter("testcase"))


def _assert_all_passed(report_name: str, minimum: int):
    cases = _testcases(report_name)
    assert len(cases) >= minimum, [c.get("name") for c in cases]
    bad = [c.get("name") for c in cases if c.find("failure") is not None or c.find("error") is not None
           or c.find("skipped") is not None]
    assert not bad, bad


def test_req027_java_testids_match_python_table():
    """Int: Java TestIds가 공유 표(tests/fixtures/testids.json)에서 Python testid.make와 같은 id를 만든다."""
    result = _gradle([":harness:test", "--tests", "td.harness.TestIdsTest", "--rerun-tasks"])
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    _assert_all_passed("TestIdsTest", minimum=12)


def test_harness_unit_suites_pass():
    """Int: 요청 계수, 시나리오 결과 NDJSON, 커버리지 수명주기를 가짜 서버로 검증하는 단위 테스트."""
    result = _gradle([":harness:test", "--tests", "td.harness.RequestCounterTest",
                      "--tests", "td.harness.CoverageHooksTest",
                      "--tests", "td.harness.CucumberLifecycleTest", "--rerun-tasks"])
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    _assert_all_passed("RequestCounterTest", minimum=2)
    _assert_all_passed("CoverageHooksTest", minimum=5)
    _assert_all_passed("CucumberLifecycleTest", minimum=1)


def test_req026_auth_harness(sut_env, local_env):
    """Int: 실제 SUT 컨테이너에서 authed() probe는 2xx, anonymous()는 sut.yaml의 unauthenticated_status다(HarnessAuthIT)."""
    from td import sut_config
    sut = sut_config.load(SUT_FILE)
    env = sut_env("req026")
    login = sut.auth_login
    probe = sut.auth_probe_spec
    props = {
        "td.auth.login": login, "td.auth.probe": probe,
        "td.auth.unauthenticated-status": str(sut.auth_unauthenticated_status),
    }
    prop_args = " ".join(f"-P{key}='{value}'" for key, value in props.items())
    java_home = _java17_home()
    script = f'''
td_sut_up "$TD_RUN_DIR" S07 req026 || {{ echo "UPFAIL=$TD_SUT_FAIL_REASON"; td_sut_down; exit 1; }}
cd "{E2E_DIR}"
JAVA_HOME="{java_home}" ./gradlew --no-daemon --console=plain :harness:test --tests td.harness.HarnessAuthIT --rerun-tasks \\
  -Ptd.base-url="$TD_BASE_URL" -Ptd.control-url="$TD_CONTROL_URL" -Ptd.auth.user="$AUTH_USER" -Ptd.auth.pass="$AUTH_PASS" {prop_args}
echo "GRADLE_RC=$?"
td_sut_down
'''
    result = env.bash(script, timeout=900, AUTH_USER=local_env["TD_SUT_USER"], AUTH_PASS=local_env["TD_SUT_PASS"])
    assert "UPFAIL=" not in result.stdout, result.stdout[-2000:]
    assert "GRADLE_RC=0" in result.stdout, (result.stdout + result.stderr)[-4000:]
    _assert_all_passed("HarnessAuthIT", minimum=3)
