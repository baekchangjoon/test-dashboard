"""S11 Sonar 토큰 수명주기와 주입 수용 테스트(REQ-038/039/064/065/066, Review Focus 3).

실제 Sonar 서버(Lightsail)와 SSH를 쓴다. 전제가 없으면 실패한다(skip 없음).
DB에 직접 넣는 fixture 행은 평문을 아무도 모르는 무작위 해시이고, 만료는 삽입 후 10분 이내이며, finally에서 지우고 0행을 확인한다.
"""
import os
import secrets
import time
from pathlib import Path

import pytest

from conftest import sonar_ssh, token_count, token_rows

REPO_ROOT = Path(__file__).resolve().parents[2]
TWO_HOURS_MS = 2 * 60 * 60 * 1000


def _insert_fixture_token(local_env, name: str, expires_in_ms: int) -> None:
    """admin 사용자의 USER_TOKEN 행 하나(무작위 해시: 평문을 아무도 모른다). 만료는 서버 시계 기준 상대값이다."""
    sql = (
        "insert into user_tokens (uuid, user_uuid, name, token_hash, created_at, type, expiration_date) "
        f"select '{secrets.token_hex(10)}', uuid, '{name}', '{secrets.token_hex(48)}', "
        f"(extract(epoch from now())*1000)::bigint, 'USER_TOKEN', (extract(epoch from now())*1000)::bigint + ({expires_in_ms}) "
        "from users where login='admin'"
    )
    done = sonar_ssh(local_env, sql)
    assert done.returncode == 0, done.stderr[-300:]


def _delete_tokens(local_env, *names: str) -> None:
    listed = ",".join(f"'{n}'" for n in names)
    sonar_ssh(local_env, f"delete from user_tokens where name in ({listed})")


def _s11(result):
    return result.stage("S11")


# --- REQ-038: 성공 경로에서 자기 토큰이 지워진다(공유 실제 run) ------------------------------------------
def test_req038_own_token_removed(s11_run, local_env):
    result = s11_run.result
    assert _s11(result)["status"] in ("passed", "degraded"), _s11(result)
    assert s11_run.token.startswith("squ_"), "토큰 관측 훅이 토큰을 쓰지 않았다(발급되지 않음)"
    assert token_rows(local_env, f"td-{result.run_id}") == []


# --- REQ-066: 토큰 비노출 ------------------------------------------------------------------------
def test_req066_token_not_leaked(s11_run):
    token = s11_run.token
    assert token, "토큰 관측 훅 파일이 비어 있다"
    # 실행 중 모든 프로세스 argv 폴링에서 토큰이 한 번도 보이지 않았다(스캐너·gradle·ssh·curl 포함).
    assert any("sonar" in line for line in s11_run.ps_lines), "폴링이 스캐너 프로세스를 보지 못했다(검사가 무의미)"
    assert not [line for line in s11_run.ps_lines if token in line]
    # work/** 전체(관측 훅 파일은 이미 지웠다)와 단계 로그에 토큰 문자열이 없다.
    leaked = []
    for path in (REPO_ROOT / "work").rglob("*"):
        if not path.is_file() or path.is_symlink() or "site-mirror" in path.parts:
            continue
        try:
            if token.encode() in path.read_bytes():
                leaked.append(str(path))
        except OSError:
            continue
    assert not leaked, leaked
    for log in (s11_run.result.run_dir).rglob("*.log"):
        assert token not in log.read_text(errors="replace"), log
    assert token not in s11_run.result.stdout and token not in s11_run.result.stderr


# --- REQ-064: 실패 경로 -------------------------------------------------------------------------
def test_req064_token_cleanup_on_failure(real_pipeline_run, local_env):
    result = real_pipeline_run("S00,S11", TD_FAIL_STAGE="S11:scan")
    assert _s11(result)["status"] == "failed" and "injected" in _s11(result)["reason"], _s11(result)
    assert token_rows(local_env, f"td-{result.run_id}") == [], "스캔 실패 뒤에도 자기 토큰이 지워져야 한다"


def test_req064_cleanup_ssh_failure_leaves_token_expiring(real_pipeline_run, local_env):
    result = None
    run_id = None
    try:
        result = real_pipeline_run("S00,S11", TD_FAIL_STAGE="S11:scan,S11:cleanup-ssh")
        run_id = result.run_id
        stage = _s11(result)
        assert stage["status"] == "failed" and "토큰 잔존 가능" in stage["reason"], stage
        assert "토큰 잔존 가능" in result.stderr, "콘솔에 잔존 경고가 있어야 한다"
        rows = token_rows(local_env, f"td-{run_id}")
        assert len(rows) == 1, rows
        _name, created, expires = rows[0].split("|")
        assert 0 < int(expires) - int(created) <= TWO_HOURS_MS
    finally:
        if run_id:
            _delete_tokens(local_env, f"td-{run_id}")
            assert token_rows(local_env, f"td-{run_id}") == []


# --- REQ-065: 사전 청소는 만료된 td-% 행만 -------------------------------------------------------------
def test_req065_preclean_expired_only(real_pipeline_run, local_env, session_id):
    old, live = f"td-old-{session_id}", f"td-live-{session_id}"
    other_before = token_rows(local_env, "%")
    other_before = [row for row in other_before if not row.startswith("td-")]
    try:
        _insert_fixture_token(local_env, old, -60 * 60 * 1000)  # 이미 만료
        _insert_fixture_token(local_env, live, 10 * 60 * 1000)  # 10분 뒤 만료
        result = real_pipeline_run("S00,S11")
        assert _s11(result)["status"] in ("passed", "degraded"), _s11(result)
        assert token_rows(local_env, old) == [], "만료된 td-old는 지워져야 한다"
        assert len(token_rows(local_env, live)) == 1, "만료되지 않은 td-live는 남아야 한다"
        assert [row for row in token_rows(local_env, "%") if not row.startswith("td-")] == other_before, "td-가 아닌 토큰은 그대로여야 한다"
    finally:
        _delete_tokens(local_env, old, live)
        assert token_rows(local_env, f"td-%-{session_id}") == []


# --- Review Focus 3: 토큰 발급 전 사전 점검 ---------------------------------------------------------------
def test_sonar_unreachable_before_issue_ssh(real_pipeline_run, local_env):
    before = token_count(local_env)
    result = real_pipeline_run("S00,S11", TD_SSH_PORT_OVERRIDE="1")  # 닫힌 포트
    stage = _s11(result)
    assert stage["status"] == "failed" and "ssh" in stage["reason"].lower(), stage
    assert token_count(local_env) == before, "SSH 불가인데 행이 늘었다"
    assert token_rows(local_env, f"td-{result.run_id}") == []


def test_sonar_unreachable_before_issue_http(real_pipeline_run, local_env):
    before = token_count(local_env)
    result = real_pipeline_run("S00,S11", TD_SONAR_URL_OVERRIDE="http://127.0.0.1:1")
    stage = _s11(result)
    assert stage["status"] == "failed" and "status" in stage["reason"].lower(), stage
    assert token_count(local_env) == before, "Sonar HTTP 불가인데 행이 늘었다"


# --- REQ-039: 잘못된 Sonar URL이어도 나머지는 게시된다 ----------------------------------------------------
def test_req039_degraded_publish(real_pipeline_run, local_env, site_prefix):
    # S13까지 포함해 실제로 게시한다(TD_SITE_PREFIX=_test/<sessionId>/).
    result = real_pipeline_run("S00,S01,S08,S11,S13", TD_SONAR_URL_OVERRIDE="http://127.0.0.1:1",
                               TD_INFRA_STATE=str(REPO_ROOT / "work" / "infra" / "terraform.tfstate"))
    stages = result.stages()
    assert stages["S11"]["status"] == "failed", stages["S11"]
    assert stages["S13"]["status"] == "passed", stages["S13"]
    mirror = result.work_dir / "site-mirror" / site_prefix / "suts" / "petclinic" / "runs" / result.run_id / "index.html"
    html = mirror.read_text()
    assert 'data-stage="S11"' in html and "Sonar" in html
