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
HARNESS_IT_RESULTS = E2E_DIR / "harness" / "build" / "test-results" / "integrationTest"


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


def _testcases(report_name: str, results_dir: Path = HARNESS_RESULTS) -> list[ET.Element]:
    report = results_dir / f"TEST-td.harness.{report_name}.xml"
    assert report.is_file(), f"JUnit XML이 없다: {report}"
    return list(ET.parse(report).getroot().iter("testcase"))


def _assert_all_passed(report_name: str, minimum: int, results_dir: Path = HARNESS_RESULTS):
    cases = _testcases(report_name, results_dir)
    assert len(cases) >= minimum, [c.get("name") for c in cases]
    bad = [c.get("name") for c in cases if c.find("failure") is not None or c.find("error") is not None
           or c.find("skipped") is not None]
    assert not bad, bad


def test_req027_java_testids_match_python_table():
    """Int: Java TestIds가 공유 표(tests/fixtures/testids.json)에서 Python testid.make와 같은 id를 만든다."""
    result = _gradle([":harness:test", "--tests", "td.harness.TestIdsTest", "--rerun-tasks"])
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    _assert_all_passed("TestIdsTest", minimum=12)


def test_harness_unit_task_excludes_integration_tests():
    """Int: :harness:test는 *IT를 돌리지 않는다(SUT 없이 통과해야 한다). integrationTest 태스크가 따로 있다."""
    result = _gradle([":harness:test", "--rerun-tasks"])
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    assert not (HARNESS_RESULTS / "TEST-td.harness.HarnessAuthIT.xml").exists()
    listing = _gradle([":harness:tasks", "--all"])
    assert "integrationTest" in listing.stdout


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
JAVA_HOME="{java_home}" ./gradlew --no-daemon --console=plain :harness:integrationTest --tests td.harness.HarnessAuthIT --rerun-tasks \\
  -Ptd.base-url="$TD_BASE_URL" -Ptd.control-url="$TD_CONTROL_URL" -Ptd.auth.user="$AUTH_USER" {prop_args}
echo "GRADLE_RC=$?"
td_sut_down
'''
    result = env.bash(script, timeout=900, AUTH_USER=local_env["TD_SUT_USER"], TD_AUTH_PASS=local_env["TD_SUT_PASS"])
    assert "UPFAIL=" not in result.stdout, result.stdout[-2000:]
    assert "GRADLE_RC=0" in result.stdout, (result.stdout + result.stderr)[-4000:]
    _assert_all_passed("HarnessAuthIT", minimum=3, results_dir=HARNESS_IT_RESULTS)


def _exec_hits(path: Path) -> dict[str, int]:
    """JaCoCo .exec(0x01 헤더, 0x10 세션, 0x11 실행 데이터)에서 클래스 이름 -> 켜진 프로브 수."""
    import struct
    data, i, hits = path.read_bytes(), 0, {}

    def utf(pos):
        size = struct.unpack(">H", data[pos:pos + 2])[0]
        return data[pos + 2:pos + 2 + size].decode("utf-8", "replace"), pos + 2 + size

    while i < len(data):
        block, i = data[i], i + 1
        if block == 0x01:
            i += 4
        elif block == 0x10:
            _, i = utf(i)
            i += 16
        elif block == 0x11:
            i += 8
            name, i = utf(i)
            count = shift = 0
            while True:
                byte, i = data[i], i + 1
                count |= (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            bits = data[i:i + (count + 7) // 8]
            i += (count + 7) // 8
            hits[name] = hits.get(name, 0) + sum(bits[k // 8] >> (k % 8) & 1 for k in range(count))
        else:
            raise AssertionError(f"알 수 없는 exec 블록 {block:#x} @ {i}: {path}")
    return hits


def test_e2e_coverage_attribution_matches_direct_path(sut_env, local_env):
    """Int(실제 SUT): 하네스 경로(CoverageHooks + authed())의 per-test 귀속이 블랙박스 확장과 같은 직접 HTTP 경로와 같다.

    pjacoco 의미(설계 §13.9): recordedProbes는 store에 켜진 서로 다른 프로브 수, droppedProbes는 테스트 컨텍스트 없이 실행된
    프로브 '적중 횟수'다(active 테스트가 정확히 1개일 때만 그 테스트에 센다). 컨텍스트는 HttpServlet#service에서 묶이므로
    보안 필터 체인(JwtAuthenticationFilter 등) 코드는 요청마다 드롭되고, 직렬 실행에서는 그 테스트의 droppedProbes가 된다.
    그래서 incompleteAttribution=true는 하네스 결함이 아니라 SUT 구조의 결과이고, 하네스와 직접 경로가 같은 값을 내야 한다.
    하네스 고유의 드롭(로그인 요청이 시나리오 안에서 일어나 첫 시나리오에 붙는 것)은 없어야 한다."""
    from td import sut_config
    sut = sut_config.load(SUT_FILE)
    env = sut_env("attr")
    java_home = _java17_home()
    script = f'''
td_sut_up "$TD_RUN_DIR" S07 attr || {{ echo "UPFAIL=$TD_SUT_FAIL_REASON"; td_sut_down; exit 1; }}
cd "{E2E_DIR}"
JAVA_HOME="{java_home}" ./gradlew --no-daemon --console=plain :harness:integrationTest --tests td.harness.CoverageAttributionIT --rerun-tasks \\
  -Ptd.base-url="$TD_BASE_URL" -Ptd.control-url="$TD_CONTROL_URL" -Ptd.auth.user="$AUTH_USER" -Ptd.auth.login='{sut.auth_login}'
echo "GRADLE_RC=$?"
td_sut_down
'''
    result = env.bash(script, timeout=900, AUTH_USER=local_env["TD_SUT_USER"], TD_AUTH_PASS=local_env["TD_SUT_PASS"])
    assert "UPFAIL=" not in result.stdout, result.stdout[-2000:]
    assert "GRADLE_RC=0" in result.stdout, (result.stdout + result.stderr)[-4000:]
    _assert_all_passed("CoverageAttributionIT", minimum=3, results_dir=HARNESS_IT_RESULTS)

    exec_dir = env.run_dir / "S07" / "attr" / "exec"
    ids = ("ATTR_harness_first", "ATTR_harness_second", "ATTR_direct")
    sidecars = {tid: json.loads((exec_dir / f"{tid}.json").read_text()) for tid in ids}
    hits = {tid: _exec_hits(exec_dir / f"{tid}.exec") for tid in ids}
    summary = {tid: {k: s.get(k) for k in ("classCount", "recordedProbes", "droppedProbes", "incompleteAttribution")}
               for tid, s in sidecars.items()}

    # 컨트롤러 코드가 귀속된다(블랙박스 VetApiBlackBoxIT#listAllVets와 같은 클래스 집합).
    for tid in ids:
        assert any(name.endswith("/VetRestController") for name in hits[tid]), (tid, sorted(hits[tid]))
        assert sum(hits[tid].values()) > 0, summary
    # 하네스 경로와 직접 경로가 같은 커버리지를 기록한다. 첫 요청은 SUT의 @Cacheable("vets")가 비어 있어 엔티티 적재 코드가
    # 더 돌므로(같은 이유로 E2E 실행에서 같은 엔드포인트를 뒤에 부른 TC는 프로브가 더 적다) 첫 시나리오는 상위 집합만 요구한다.
    assert hits["ATTR_harness_second"] == hits["ATTR_direct"], summary
    first = hits["ATTR_harness_first"]
    assert all(first.get(name, 0) >= count for name, count in hits["ATTR_direct"].items()), summary
    # 드롭은 요청당 필터 체인 적중 수로 셋이 같다: 첫 시나리오에 로그인 드롭이 더해지지 않는다(하네스 결함 회귀 방지).
    dropped = {tid: sidecars[tid].get("droppedProbes", 0) for tid in ids}
    assert dropped["ATTR_harness_second"] == dropped["ATTR_direct"], summary
    assert dropped["ATTR_harness_first"] == dropped["ATTR_direct"], summary
    # 필터 체인이 HttpServlet#service 바깥이므로 인증된 요청의 TC는 직렬 실행에서 incompleteAttribution=true가 정확한 값이다.
    assert all(sidecars[tid].get("incompleteAttribution") is True for tid in ids), summary
    assert dropped["ATTR_direct"] > 0, summary
