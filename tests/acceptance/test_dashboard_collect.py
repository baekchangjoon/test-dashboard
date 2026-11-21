"""과제 수집과 수집용 Sonar 토큰(REQ-097 등). 가짜 ssh·가짜 Sonar만 쓰고 실제 서버에는 닿지 않는다."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from dashboard_fixtures import fake_ssh, token_env
from fake_sonar import start_fake_sonar

REPO_ROOT = Path(__file__).resolve().parents[2]


def bash_token(tmp_path: Path, script: str, env: dict) -> subprocess.CompletedProcess:
    """common.sh와 sonar-token.sh를 source한 뒤 script를 실행한다. TD_RUN_DIR은 주지 않는다(호출자가 env로 줄 때만 있다).

    S11 래퍼(td_sonar_token_issue)는 정리 등록에 env.sh의 td_on_exit를 쓰므로, env에 TD_RUN_DIR이 있으면
    S11.sh처럼 env.sh도 source한다.
    """
    base = {key: value for key, value in os.environ.items() if not key.startswith("TD_") and key != "SONAR_TOKEN"}
    base.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(tmp_path))
    base.update(env)
    libs = ["common.sh", "env.sh", "sonar-token.sh"] if "TD_RUN_DIR" in env else ["common.sh", "sonar-token.sh"]
    header = "".join(f'source "{REPO_ROOT}/pipeline/lib/{lib}"\n' for lib in libs)
    return subprocess.run(["bash", "-c", header + script], capture_output=True, text=True, env=base, timeout=120)


@pytest.fixture
def fake_sonar_url():
    state, stop = start_fake_sonar()
    try:
        yield state.url
    finally:
        stop()


@pytest.fixture
def run_dir_with_s11(tmp_path):
    """S11이 시작된 run 디렉터리(정리 trap이 읽는 stages/S11.json만 있다)."""
    run_dir = tmp_path / "run"
    (run_dir / "stages").mkdir(parents=True)
    (run_dir / "stages" / "S11.json").write_text(json.dumps({"stage": "S11", "status": "running"}))
    return run_dir


def test_req097_named_issue_and_revoke_need_no_stage_state(tmp_path, fake_sonar_url):
    ssh = fake_ssh(tmp_path)
    out = bash_token(tmp_path, '''
        export TD_SONAR_URL="$(td_py -m td.sonar url)"
        td_sonar_token_issue_named td-collect-20261122T000000Z-abcd1234 || exit 3
        [[ -n "$SONAR_TOKEN" ]] || exit 4
        td_sonar_token_revoke_named || exit 5
        [[ -z "${SONAR_TOKEN:-}" ]] || exit 6''', token_env(tmp_path, ssh, fake_sonar_url))
    assert out.returncode == 0 and ssh.rows() == [], out.stdout + out.stderr
    assert "td-collect-20261122T000000Z-abcd1234" in ssh.log() and "+ 7200000" in ssh.log()
    assert not (tmp_path / "stages").exists()


def test_req097_named_revoke_failure_warns_once(tmp_path, fake_sonar_url):
    ssh = fake_ssh(tmp_path, fail_delete=True)
    out = bash_token(tmp_path, 'export TD_SONAR_URL="$(td_py -m td.sonar url)"; td_sonar_token_issue_named td-collect-x; '
                               'td_sonar_token_revoke_named; echo rc=$?; td_sonar_token_revoke_named; echo rc2=$?',
                     token_env(tmp_path, ssh, fake_sonar_url))
    assert "rc=1" in out.stdout and "rc2=1" in out.stdout, out.stdout + out.stderr
    assert out.stderr.count("토큰 잔존 가능") == 1 and "2시간 후" in out.stderr
    assert "td-collect-x" in out.stderr and ssh.rows() == ["td-collect-x"]


def test_req097_named_revoke_after_lost_insert_reply(tmp_path, fake_sonar_url):
    """INSERT 응답이 유실돼 발급이 실패해도, 먼저 기억한 이름으로 정리하면 행이 지워진다."""
    ssh = fake_ssh(tmp_path, lose_insert_reply=True)
    out = bash_token(tmp_path, 'export TD_SONAR_URL="$(td_py -m td.sonar url)"; td_sonar_token_issue_named td-collect-y; '
                               'echo issue=$?; td_sonar_token_revoke_named; echo revoke=$?',
                     token_env(tmp_path, ssh, fake_sonar_url))
    assert "issue=1" in out.stdout and "revoke=0" in out.stdout, out.stdout + out.stderr
    assert ssh.rows() == []


def test_req097_named_revoke_hook_stage(tmp_path, fake_sonar_url):
    """장애 주입 지점은 TD_SONAR_HOOK_STAGE(기본 S11)의 cleanup-ssh다."""
    ssh = fake_ssh(tmp_path)
    env = {**token_env(tmp_path, ssh, fake_sonar_url), "TD_FAIL_STAGE": "COLLECT:cleanup-ssh"}
    script = ('export TD_SONAR_URL="$(td_py -m td.sonar url)"; td_sonar_token_issue_named td-collect-z; '
              'td_sonar_token_revoke_named; echo rc=$?; echo "reason=$TD_SONAR_FAIL_REASON"')
    default_stage = bash_token(tmp_path, script, env)
    assert "rc=0" in default_stage.stdout and ssh.rows() == [], default_stage.stdout + default_stage.stderr
    collect_stage = bash_token(tmp_path, script, {**env, "TD_SONAR_HOOK_STAGE": "COLLECT"})
    assert "rc=1" in collect_stage.stdout and "TD_FAIL_STAGE=COLLECT:cleanup-ssh" in collect_stage.stdout
    assert ssh.rows() == ["td-collect-z"]


def test_req097_s11_wrapper_leaves_collect_rows(tmp_path, fake_sonar_url, run_dir_with_s11):
    ssh = fake_ssh(tmp_path)
    ssh.seed("td-collect-x")
    out = bash_token(tmp_path, 'export TD_SONAR_URL="$(td_py -m td.sonar url)"; td_sonar_token_issue r1 && td_sonar_token_revoke',
                     {**token_env(tmp_path, ssh, fake_sonar_url), "TD_RUN_DIR": str(run_dir_with_s11)})
    assert out.returncode == 0 and ssh.rows() == ["td-collect-x"], out.stdout + out.stderr
    assert "delete from user_tokens where name='td-r1'" in ssh.log()
