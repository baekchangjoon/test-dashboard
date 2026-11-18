"""자원 정리 수용 테스트: REQ-009(누수 0), REQ-010(SIGINT 정리), REQ-011(PID·worktree·Gradle daemon)."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from helpers import PETCLINIC_SRC, make_stage_dir, pid_alive, run_pids
from td import envctl

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "env" / "docker-compose.sut.yml"
JAVA17 = "/usr/libexec/java_home"


def test_req009_compose_labels_on_every_resource(sut_env):
    """Int: 렌더링한 compose의 모든 서비스, 명시적 네트워크, 명시적 볼륨에 test-run 라벨이 있다."""
    env = sut_env("labels")
    result = env.bash(f'''
export TD_EXEC_DIR=/tmp TD_AGENT_ARGS=x
docker compose -f "{COMPOSE}" -p "$TD_PROJECT_NAME" config --format json
''')
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["services"] and config["networks"] and config["volumes"]
    assert "default" in config["networks"]
    assert envctl.unlabeled_resources(config, env.label) == []
    for kind in ("services", "networks", "volumes"):
        for name, spec in config[kind].items():
            assert spec["labels"]["test-run"] == env.label, (kind, name)


def test_req009_unlabeled_compose_fails_gate(sut_env, tmp_path):
    """부정 테스트: 라벨을 뺀 compose는 기동 전에 거부되고, 새고 있는 자원은 leak gate가 잡는다."""
    env = sut_env("nolabel")
    unlabeled = tmp_path / "unlabeled.yml"
    unlabeled.write_text("services:\n  sut:\n    image: alpine:latest\n    command: ['sleep', '300']\n"
                         "    ports: ['127.0.0.1::8080', '127.0.0.1::6310']\n"
                         "networks:\n  default: {}\nvolumes:\n  data: {}\n")
    before = envctl.snapshot()
    result = env.bash('td_sut_up "$TD_RUN_DIR" S01 blackbox; echo "RC=$?"; echo "REASON=$TD_SUT_FAIL_REASON"',
                      TD_COMPOSE_FILE=str(unlabeled))
    assert "RC=1" in result.stdout, result.stdout + result.stderr[-2000:]
    assert "test-run" in result.stdout.split("REASON=", 1)[1]
    assert envctl.diff(before, envctl.snapshot()).owned == [], "라벨 검사에 걸렸는데 자원이 만들어졌다"
    # leak gate는 라벨이 없어도 compose project 접두로 잔존 자원을 잡는다.
    subprocess_env = {**env.env, "TD_EXEC_DIR": "/tmp"}
    subprocess.run(["docker", "compose", "-f", str(unlabeled), "-p", env.project, "up", "-d"],
                   check=True, capture_output=True, env=subprocess_env, timeout=120)
    gate = env.bash(f'td_leak_gate "test-{env.label.removeprefix("td-test-")}"; echo "GATE_RC=$?"')
    assert "GATE_RC=1" in gate.stdout, gate.stdout + gate.stderr
    env.cleanup()
    gate_after = env.bash(f'td_leak_gate "test-{env.label.removeprefix("td-test-")}"; echo "GATE_RC=$?"')
    assert "GATE_RC=0" in gate_after.stdout, gate_after.stdout + gate_after.stderr


def test_req009_no_resource_leak(sut_env):
    """기동과 종료를 한 바퀴 돌린 뒤 새로 생겨 남은 컨테이너, 네트워크, 볼륨이 0이다(라벨과 무관한 차이 비교)."""
    env = sut_env("leak")
    before = envctl.snapshot()
    result = env.bash('''
td_sut_up "$TD_RUN_DIR" S01 blackbox || { echo "UPFAIL=$TD_SUT_FAIL_REASON"; td_sut_down; exit 1; }
td_sut_down
td_leak_gate "test-${TD_RUN_LABEL#td-test-}"
''')
    assert result.returncode == 0, result.stdout + result.stderr[-3000:]
    leak = envctl.diff(before, envctl.snapshot())
    assert leak.owned == [], leak
    # compose project가 td-/td-test- 계열이 아닌 새 자원은 경고로 분리한다(이 세션 Docker 호스트 공유 가정).
    if leak.foreign:
        print(f"WARN foreign resources appeared during test: {leak.foreign}")


def _wait_for(predicate, timeout: float, interval: float = 0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # macOS: 그룹에 좀비(회수 전 리더)만 남으면 EPERM이다
        return False
    return True


def test_req010_sigint_cleanup(stub_stages, tmp_path, sut_env):
    """S01 스텁이 컨테이너를 띄운 직후 프로세스 그룹에 SIGINT: 90초 안에 종료, 자원 0, pids 종료."""
    env = sut_env("sigint")
    stage_dir = make_stage_dir(tmp_path, "S01", '''
sleep 600 &
td_pid_register bgsleep $!
sleep 600
''', prologue=False)
    # 컨테이너 기동(health 대기 중)에도 걸리도록 prologue 대신 body에서 기동한다.
    stage_dir_script = next(stage_dir.glob("S01-*.sh"))
    stage_dir_script.write_text(stage_dir_script.read_text().replace(
        "sleep 600 &", 'sleep 600 &\ntd_pid_register bgsleep $!\ntd_sut_up "$TD_RUN_DIR" S01 blackbox\n', 1))
    work = tmp_path / "work-sigint"
    before = envctl.snapshot()
    run_env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    run_env.update(TD_WORK_DIR=str(work), TD_ROOT=str(REPO_ROOT), TD_SITE_PREFIX=stub_stages.site_prefix,
                   TD_STAGE_DIR=str(stage_dir), TD_RUN_LABEL=env.label, TD_PROJECT_NAME=env.project,
                   TD_SUT_JAR=env.env["TD_SUT_JAR"], TD_AGENT_JAR=env.env["TD_AGENT_JAR"],
                   TD_SUT_PACKAGES=env.env["TD_SUT_PACKAGES"], TD_SUT_PORT="8080", TD_SUT_HEALTH="/actuator/health")
    proc = subprocess.Popen(["bash", str(REPO_ROOT / "pipeline" / "run-all.sh"), "stub",
                             "--sut-file", str(stub_stages.sut_file), "--only", "S00,S01"],
                            env=run_env, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pgid = proc.pid
    try:
        seen = _wait_for(lambda: envctl.docker_lines("ps", "-aq", "--filter", f"label=test-run={env.label}"), 120)
        assert seen, "라벨이 붙은 컨테이너가 보이지 않았다"
        os.killpg(pgid, signal.SIGINT)
        started = time.time()
        gone = _wait_for(lambda: proc.poll() is not None and not _group_alive(pgid), 90, 0.5)
        elapsed = time.time() - started
        assert gone, f"SIGINT 90초 뒤에도 프로세스 그룹이 남았다({elapsed:.0f}s)"
    finally:
        if _group_alive(pgid):
            os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=30)
    runs = [p for p in (work / "runs").glob("*") if p.is_dir()]
    assert len(runs) == 1
    leak = envctl.diff(before, envctl.snapshot())
    assert leak.owned == [], leak
    pids = run_pids(runs[0])
    assert "bgsleep" in pids, pids
    assert not any(pid_alive(pid) for pid in pids.values()), pids


def _gradle_daemon_ids() -> set[tuple[int, str]]:
    return set(envctl.gradle_daemons())


def test_req011_pids_worktrees_daemons(stub_stages, tmp_path):
    """등록한 PID는 단계가 끝나면 모두 종료되고, worktree와 Gradle daemon이 남지 않는다."""
    java_home = subprocess.run([JAVA17, "-v", "17"], capture_output=True, text=True, check=True).stdout.strip()
    stage_dir = make_stage_dir(tmp_path, "S01", f'''
sleep 600 &
td_pid_register bgsleep $!
(cd "{PETCLINIC_SRC}" && td_run 600 -- env JAVA_HOME="{java_home}" ./gradlew --no-daemon -q help)
''', prologue=False)
    before_daemons = _gradle_daemon_ids()
    before_worktrees = subprocess.run(["git", "-C", str(PETCLINIC_SRC), "worktree", "list", "--porcelain"],
                                      capture_output=True, text=True).stdout
    result = stub_stages.run("--only", "S00,S01", TD_STAGE_DIR=str(stage_dir))
    assert result.returncode == 0, result.stderr[-3000:]
    pids = run_pids(result.run_dir)
    assert "bgsleep" in pids
    assert not any(pid_alive(pid) for pid in pids.values()), pids
    after_worktrees = subprocess.run(["git", "-C", str(PETCLINIC_SRC), "worktree", "list", "--porcelain"],
                                     capture_output=True, text=True).stdout
    assert after_worktrees == before_worktrees and "tia" not in after_worktrees.lower()
    new_daemons = _gradle_daemon_ids() - before_daemons
    assert new_daemons == set(), f"run 뒤 남은 Gradle daemon: {new_daemons}"
