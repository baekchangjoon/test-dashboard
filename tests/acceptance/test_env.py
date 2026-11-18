"""SUT 컨테이너 환경 수용 테스트(Int): REQ-007(컨테이너 per-test 수집), Review Focus 1(SUT가 뜨지 않음)."""
import json
import re
import time
from pathlib import Path

import pytest

from helpers import make_stage_dir
from td import sut_config

REPO_ROOT = Path(__file__).resolve().parents[2]
SUT_FILE = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"


def _kv(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines() if re.match(r"^[A-Z0-9_]+=", line))


def test_req007_control_endpoint_loopback(sut_env):
    env = sut_env("req007")
    _method, probe_path = sut_config.load(SUT_FILE).auth_probe
    result = env.bash(f'''
td_sut_up "$TD_RUN_DIR" S01 blackbox || {{ echo "UPFAIL=$TD_SUT_FAIL_REASON"; td_sut_down; exit 1; }}
echo "BASE=$TD_BASE_URL"
echo "CONTROL=$TD_CONTROL_URL"
echo "PORT_SUT=$(docker compose -p "$TD_COMPOSE_PROJECT" port sut 8080)"
echo "PORT_CTL=$(docker compose -p "$TD_COMPOSE_PROJECT" port sut 6310)"
code() {{ curl -s -o /dev/null -w '%{{http_code}}' "$@"; }}
echo "START=$(code -X POST "$TD_CONTROL_URL/__coverage__/test/start?testId=T1")"
echo "PROBE=$(code -H 'baggage: test.id=T1' "$TD_BASE_URL{probe_path}")"
echo "STOP=$(code -X POST "$TD_CONTROL_URL/__coverage__/test/stop?testId=T1&result=passed")"
echo "EXECDIR=$TD_EXEC_DIR"
td_sut_down
''')
    assert result.returncode == 0, result.stdout + result.stderr[-3000:]
    values = _kv(result.stdout)
    assert re.fullmatch(r"127\.0\.0\.1:\d+", values["PORT_SUT"]), values
    assert re.fullmatch(r"127\.0\.0\.1:\d+", values["PORT_CTL"]), values
    assert values["BASE"] == f"http://{values['PORT_SUT']}"
    assert values["CONTROL"] == f"http://{values['PORT_CTL']}"
    for call in ("START", "STOP"):
        assert values[call].startswith("2"), (call, values)
    exec_file = Path(values["EXECDIR"]) / "T1.exec"
    assert exec_file.exists() and exec_file.stat().st_size > 0, list(Path(values["EXECDIR"]).iterdir())


def test_sut_boot_failure_reports_and_cleans(stub_stages, tmp_path, sut_env):
    """존재하지 않는 jar: 단계는 멈추지 않고 failed, reason에 로그 tail, 정리까지 끝난다(Review Focus 1)."""
    from td import envctl
    env = sut_env("bootfail")
    stage_dir = make_stage_dir(tmp_path, "S01", "echo should-not-reach", prologue=True)
    before = envctl.snapshot()
    result = stub_stages.run("--only", "S00,S01", TD_STAGE_DIR=str(stage_dir),
                             TD_SUT_JAR=str(tmp_path / "no-such.jar"), TD_AGENT_JAR=env.env["TD_AGENT_JAR"],
                             TD_SUT_PACKAGES=env.env["TD_SUT_PACKAGES"], TD_SUT_PORT="8080",
                             TD_SUT_HEALTH="/actuator/health", TD_RUN_LABEL=env.label,
                             TD_PROJECT_NAME=env.project)
    assert result.returncode == 2, result.stderr[-2000:]
    stage = result.stage("S01")
    assert stage["status"] == "failed"
    assert "no-such.jar" in stage["reason"], stage["reason"]
    assert "should-not-reach" not in result.stdout
    assert envctl.diff(before, envctl.snapshot()).owned == [], "실패한 기동 뒤에 자원이 남았다"
    # 컨테이너가 떴다가 죽는 경우(깨진 jar)에는 컨테이너 로그 마지막 줄이 reason에 들어간다.
    corrupt = tmp_path / "corrupt.jar"
    corrupt.write_text("not a jar")
    result2 = stub_stages.run("--only", "S00,S01", TD_STAGE_DIR=str(stage_dir),
                              TD_SUT_JAR=str(corrupt), TD_AGENT_JAR=env.env["TD_AGENT_JAR"],
                              TD_SUT_PACKAGES=env.env["TD_SUT_PACKAGES"], TD_SUT_PORT="8080",
                              TD_SUT_HEALTH="/actuator/health", TD_RUN_LABEL=env.label,
                              TD_PROJECT_NAME=env.project)
    assert result2.returncode == 2
    reason = result2.stage("S01")["reason"]
    assert result2.stage("S01")["status"] == "failed"
    assert "corrupt" in reason.lower() or "invalid" in reason.lower(), reason
    assert envctl.diff(before, envctl.snapshot()).owned == []
