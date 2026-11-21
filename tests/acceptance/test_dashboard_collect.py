"""과제 수집과 수집용 Sonar 토큰(REQ-085~097, 143 등). 가짜 gh·가짜 ssh·가짜 Sonar만 쓰고 실제 서버에는 닿지 않는다."""
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dashboard_fixtures import (RUN_C, cfg_with, fake_gh, fake_ssh, load_cfg, make_site, rebuild_site, token_env,
                                write_snapshot)
from fake_sonar import start_fake_sonar
from td import collect
from td.publish import check_no_home_in_file
from td.site import metrics

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


# --- 수집기 공용 도우미 ---------------------------------------------------------------------------

COLLECT_SH = REPO_ROOT / "pipeline" / "collect.sh"
TOKEN_NAME_PATTERN = r"td-collect-\d{8}T\d{6}Z-[0-9a-f]{8}"
CI_VALUE_KEYS = ("runs", "successes", "failures", "successRate", "lastFailed")


def _base_env() -> dict:
    return {key: value for key, value in os.environ.items() if not key.startswith("TD_") and key != "SONAR_TOKEN"}


class CollectEnv(dict):
    """수집기 환경 변수. `.sonar`는 이 환경이 가리키는 가짜 Sonar 상태다."""
    sonar = None


@pytest.fixture
def collect_env(tmp_path):
    """가짜 Sonar를 띄우고 `td.collect`를 돌릴 환경(테스트 접두, 고정 시각, 짧은 재시도 간격, 테스트 토큰)."""
    sonar_state, stop = start_fake_sonar()
    env = CollectEnv(TD_SITE_PREFIX=f"_test/collect-{tmp_path.name}/", TD_SONAR_URL=sonar_state.url,
                     TD_SONAR_URL_OVERRIDE=sonar_state.url, SONAR_TOKEN="squ_collect_test_token_value",
                     TD_COLLECT_RETRY_DELAYS="0.1,0.2", TD_NOW="2026-11-22T01:00:00Z")
    env.sonar = sonar_state
    try:
        yield env
    finally:
        stop()


def _collect_proc(root: Path, command: str, *, gh, env: dict) -> subprocess.CompletedProcess:
    full_env = {**_base_env(), "TD_ROOT": str(REPO_ROOT), "PYTHONPATH": str(REPO_ROOT / "site-gen"),
                "TD_GH_BIN": str(gh.path), **env}
    return subprocess.run([sys.executable, "-m", "td.collect", command, "--config", str(root / "dashboard.yaml"),
                           "--site", str(root / "site"), "--suts-dir", str(root / "suts")],
                          capture_output=True, text=True, env=full_env, timeout=120)


def run_collect(root: Path, cfg: dict | None, *, gh, env: dict, runs: dict | None = None, with_stderr: bool = False):
    """`<root>/dashboard.yaml`·`<root>/suts`·`<root>/site`를 만들고(cfg가 None이면 이미 만든 것을 쓴다) `td.collect run`을
    돌려 결과 JSON을 돌려준다. 종료 코드가 0이 아니면 실패한다."""
    if cfg is not None:
        make_site(root, config=cfg, runs=runs)
    proc = _collect_proc(root, "run", gh=gh, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    return (out, proc.stderr) if with_stderr else out


def snapshot(root: Path, name: str, date: str | None = None) -> dict:
    """수집이 쓴 스냅숏(date가 없으면 latest.json)."""
    project_dir = root / "site" / "projects" / name
    path = project_dir / "snapshots" / f"{date}.json" if date else project_dir / "latest.json"
    return json.loads(path.read_text())


def run_collect_sh(root: Path, mode: str = "ok", *, ssh, env: CollectEnv, cfg: dict | None = None, gh=None,
                   extra: dict | None = None) -> subprocess.CompletedProcess:
    """가짜 ssh·가짜 Sonar로 `pipeline/collect.sh`를 돌린다. mode: ok | sonar-500(Sonar가 500) | lost-insert-reply(ssh가 맡음)."""
    root.mkdir(parents=True, exist_ok=True)
    if cfg is None:
        cfg = cfg_with(plain="a")
    if gh is None:
        gh = fake_gh(root, {"o/a": {"runs": ["success"]}})
    make_site(root, config=cfg)
    full_env = {**_base_env(), "TD_ROOT": str(REPO_ROOT), "TD_WORK_DIR": str(root / "work"),
                **{key: value for key, value in env.items() if key != "SONAR_TOKEN"},
                **token_env(root, ssh, env.sonar.url), "TD_DOMAIN": "example.invalid", "TD_GH_BIN": str(gh.path),
                **(extra or {})}
    if mode == "sonar-500":
        env.sonar.error_keys["a"] = 500
    try:
        return subprocess.run(["bash", str(COLLECT_SH), "--config", str(root / "dashboard.yaml"), "--site",
                               str(root / "site"), "--suts-dir", str(root / "suts")],
                              capture_output=True, text=True, env=full_env, timeout=180)
    finally:
        env.sonar.error_keys.pop("a", None)


def _calls_to(gh, fragment: str) -> list:
    return [call for call in gh.calls if fragment in call[2]]


# --- REQ-085 ~ 088: 수집 값과 파일 -------------------------------------------------------------------

def test_req085_ci_conclusion_classes(tmp_path, collect_env):
    newest_first = ["success", "success", "failure", "cancelled", "timed_out", "success", "startup_failure",
                    "skipped", "neutral", "action_required", "stale"]
    gh = fake_gh(tmp_path, {"o/a": {"runs": newest_first, "default_branch": "trunk"}, "o/b": {"runs": []},
                            "o/c": {"runs": ["cancelled", "skipped"]}})
    run_collect(tmp_path, cfg_with(plain=["a", "b", "c"]), gh=gh, env=collect_env)
    ci = snapshot(tmp_path, "a")["ci"]
    assert (ci["runs"], ci["successes"], ci["failures"], ci["lastFailed"]) == (6, 3, 3, False)
    assert ci["successRate"] == 0.5 and ci["history"] == [0, 1, 0, 0, 1, 1]
    assert snapshot(tmp_path, "a")["sources"]["ci"] == "ok"
    for name in ("b", "c"):
        ci = snapshot(tmp_path, name)["ci"]
        assert [ci[key] for key in CI_VALUE_KEYS] == [None] * 5 and ci["history"] == []
        assert snapshot(tmp_path, name)["sources"]["ci"] == "none"
    call = next(c for c in gh.calls if "actions/runs" in " ".join(c) and "o/a" in " ".join(c))
    assert call[:2] == ["api", "-i"]
    assert all(part in " ".join(call) for part in ("branch=trunk", "status=completed", "per_page=30"))


def test_req086_latest_check_per_name(tmp_path, collect_env):
    noise = [{"name": "lint", "status": "in_progress", "conclusion": None, "started_at": "2026-11-20T03:00:00Z"},
             {"name": "docs", "conclusion": "cancelled", "started_at": "2026-11-20T01:30:00Z"}]
    recovered = [{"name": "build", "conclusion": "failure", "started_at": "2026-11-20T01:00:00Z"},
                 {"name": "build", "conclusion": "success", "started_at": "2026-11-20T02:00:00Z"}] + noise
    regressed = [{"name": "build", "conclusion": "success", "started_at": "2026-11-20T01:00:00Z"},
                 {"name": "build", "conclusion": "failure", "started_at": "2026-11-20T02:00:00Z"}] + noise
    gh = fake_gh(tmp_path, {"o/a": {"checks": recovered}, "o/b": {"checks": regressed, "default_branch": "dev"}})
    run_collect(tmp_path, cfg_with(plain=["a", "b"]), gh=gh, env=collect_env)
    ci_a, ci_b = snapshot(tmp_path, "a")["ci"], snapshot(tmp_path, "b")["ci"]
    assert ci_a["failedChecks"] == 0 and ci_a["failedCheckNames"] == []
    assert ci_b["failedChecks"] == 1 and ci_b["failedCheckNames"] == ["build"]
    assert _calls_to(gh, "repos/o/a/commits/main/check-runs") and _calls_to(gh, "repos/o/b/commits/dev/check-runs")


def test_req087_sonar_values_and_404(tmp_path, collect_env):
    collect_env.sonar.set_project("custom-key", gate="ERROR", coverage="41.7", bugs="2", vulnerabilities="3",
                                  code_smells="37", ncloc="2100", sqale_rating="1.0", reliability_rating="3.0",
                                  security_rating="2.0")
    collect_env.sonar.set_project("c", gate="OK", coverage="80.0", bugs="0", vulnerabilities="0", code_smells="5")
    collect_env.sonar.missing_keys.add("b")
    cfg = {"schema": 1, "projects": [{"name": "a", "repo": "o/a", "sonarKey": "custom-key"},
                                     {"name": "b", "repo": "o/b"}, {"name": "c", "repo": "o/c"}]}
    gh = fake_gh(tmp_path, {"o/a": {}, "o/b": {}, "o/c": {}})
    out = run_collect(tmp_path, cfg, gh=gh, env=collect_env)
    sonar_a = snapshot(tmp_path, "a")["sonar"]
    assert sonar_a == {"gate": "ERROR", "coverage": 41.7, "bugs": 2, "vulnerabilities": 3, "codeSmells": 37,
                       "ncloc": 2100, "ratings": {"reliability": "C", "security": "B", "maintainability": "A"}}
    assert isinstance(sonar_a["coverage"], float)
    assert all(type(sonar_a[key]) is int for key in ("bugs", "vulnerabilities", "codeSmells"))
    assert snapshot(tmp_path, "c")["sonar"]["gate"] == "OK"
    snap_b = snapshot(tmp_path, "b")
    assert snap_b["sonar"] is None and snap_b["sources"]["sonar"] == "absent" and snap_b["problems"] == []
    assert out["status"] == "ok" and out["reasons"] == []
    requested = {key for _path, key in collect_env.sonar.keyed_requests}
    assert requested == {"custom-key", "b", "c"}


def test_req088_snapshot_files_and_schema(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {"o/a": {}})
    out = run_collect(tmp_path, cfg_with(plain="a"), gh=gh, env={**collect_env, "TD_NOW": "2026-11-22T01:00:00Z"})
    project_dir = tmp_path / "site" / "projects" / "a"
    first = snapshot(tmp_path, "a", "20261122")
    assert first == snapshot(tmp_path, "a")
    assert first["visibility"] == "public" and first["collectedAt"] == "2026-11-22T01:00:00Z" and first["date"] == "20261122"
    assert list(metrics._validator().iter_errors(first)) == []
    kept, dropped = metrics.load_snapshots(project_dir)
    assert len(kept) == 1 and dropped == []
    assert out["written"] == ["projects/a/snapshots/20261122.json", "projects/a/latest.json", "projects/_collect.json"]
    assert json.loads((tmp_path / "site/projects/_collect.json").read_text()) == {
        "schema": 1, "date": "20261122", "unverified": []}

    run_collect(tmp_path, None, gh=gh, env={**collect_env, "TD_NOW": "2026-11-22T23:59:00Z"})
    assert [p.name for p in (project_dir / "snapshots").iterdir()] == ["20261122.json"]
    assert snapshot(tmp_path, "a", "20261122")["collectedAt"] == "2026-11-22T23:59:00Z"

    run_collect(tmp_path, None, gh=gh, env={**collect_env, "TD_NOW": "2026-11-23T00:00:01Z"})
    assert sorted(p.name for p in (project_dir / "snapshots").iterdir()) == ["20261122.json", "20261123.json"]
    assert snapshot(tmp_path, "a")["date"] == "20261123"
    assert not [p for p in (tmp_path / "site").rglob("*") if p.name.endswith(".tmp")]


# --- REQ-089, 090, 143: 제외·부분 실패·미확인 ------------------------------------------------------------

def test_req089_private_repo_excluded(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {"o/a": {}, "o/secret": {"visibility": "private", "description": "internal thing"},
                            "o/gone": {"missing": True}, "o/d": {}})
    out, err = run_collect(tmp_path, cfg_with(plain=["a", "secret", "gone", "d"]), gh=gh, env=collect_env,
                           with_stderr=True)
    assert out["status"] == "degraded" and sorted(out["excluded"]) == ["gone", "secret"]
    assert out["reasons"] == ["비공개 과제 2개 제외"]
    assert "secret" in err and "gone" in err
    site = tmp_path / "site"
    assert not (site / "projects/secret").exists() and not (site / "projects/gone").exists()
    assert (site / "projects/a/latest.json").exists() and (site / "projects/d/latest.json").exists()
    assert not any("secret" in path or "gone" in path for path in out["written"])
    rebuild_site(site)
    for path in (p for p in site.rglob("*") if p.is_file()):
        text = path.read_text(errors="replace")
        for needle in ("secret", "o/secret", "internal thing", "gone", "o/gone"):
            assert needle not in text, (path, needle)


def test_req090_partial_failure_null_not_carried(tmp_path, collect_env):
    site = tmp_path / "site"
    write_snapshot(site, "a", "20261121", sonar={"gate": "OK", "coverage": 80.0, "bugs": 1})
    collect_env.sonar.error_keys["a"] = 500
    collect_env.sonar.set_project("b", gate="OK", coverage="70.0", bugs="0", vulnerabilities="0", code_smells="1")
    gh = fake_gh(tmp_path, {"o/a": {"runs": ["success", "failure"]}, "o/b": {}})
    out = run_collect(tmp_path, cfg_with(plain=["a", "b"]), gh=gh, env=collect_env)
    snap_a = snapshot(tmp_path, "a")
    assert snap_a["sonar"] is None and snap_a["sources"]["sonar"] == "failed"
    assert [problem["source"] for problem in snap_a["problems"]] == ["sonar"]
    assert "HTTP 500" in snap_a["problems"][0]["reason"]
    assert snap_a["ci"]["runs"] == 2 and snap_a["sources"]["ci"] == "ok"
    snap_b = snapshot(tmp_path, "b")
    assert snap_b["sonar"]["coverage"] == 70.0 and snap_b["sources"] == {"ci": "ok", "sonar": "ok"}
    assert snap_b["problems"] == []
    assert out["status"] == "degraded" and out["reasons"] == ["수집 실패 1개 과제"]
    assert snapshot(tmp_path, "a", "20261121")["sonar"]["coverage"] == 80.0     # 어제 파일은 그대로
    gate_calls = [key for path, key in collect_env.sonar.keyed_requests
                  if key == "a" and path == "/api/qualitygates/project_status"]
    assert len(gate_calls) == 3


def test_req143_visibility_unknown_keeps_last_public(tmp_path, collect_env):
    site = tmp_path / "site"
    write_snapshot(site, "a", "20261121")
    gh = fake_gh(tmp_path, {"o/a": {"hang": 30}, "o/b": {"hang": 30}})
    out = run_collect(tmp_path, cfg_with(plain=["a", "b"]), gh=gh,
                      env={**collect_env, "TD_COLLECT_BUDGET_SEC": "3", "TD_NOW": "2026-11-22T01:00:00Z"})
    assert out["status"] == "degraded" and sorted(out["unverified"]) == ["a", "b"]
    # 조정자 결정: 사이트 수준 `projects/_collect.json`은 매번 쓰고 written에 넣는다. 스냅숏은 하나도 쓰지 않는다.
    assert out["written"] == ["projects/_collect.json"]
    assert json.loads((site / "projects/_collect.json").read_text()) == {
        "schema": 1, "date": "20261122", "unverified": ["a", "b"]}
    assert sorted(p.name for p in (site / "projects/a/snapshots").iterdir()) == ["20261121.json"]
    assert not (site / "projects/b").exists()
    views = {p["name"]: p for p in metrics.build_projects(site, load_cfg(site))}
    assert list(views) == ["a"] and views["a"]["stale"] == "20261121"
    assert gh.alive_pids() == []


# --- REQ-091: 시간 예산과 재시도 ------------------------------------------------------------------------

def test_req091_budget_and_retry(tmp_path, collect_env):
    assert (collect.CONNECT_TIMEOUT_SEC, collect.READ_TIMEOUT_SEC, collect.RETRIES, collect.RETRY_DELAYS_SEC,
            collect.BUDGET_SEC) == (10, 30, 2, (2, 4), 300)
    gh = fake_gh(tmp_path, {"o/a": {"hang": 30, "hang_on": "runs"}, "o/b": {}})
    started = time.monotonic()
    out = run_collect(tmp_path, cfg_with(plain=["a", "b"]), gh=gh, env={**collect_env, "TD_COLLECT_BUDGET_SEC": "3"})
    assert time.monotonic() - started < 13
    assert out["status"] == "degraded" and "수집 예산 초과" in out["reasons"]
    for name in ("a", "b"):
        snap = snapshot(tmp_path, name)
        assert snap["ci"] is None or all(snap["ci"][key] is None for key in CI_VALUE_KEYS)
        assert snap["sources"]["ci"] == "failed" and snap["sonar"] is None and snap["sources"]["sonar"] == "failed"
    assert not _calls_to(gh, "repos/o/b/actions/runs")      # 예산이 끝난 뒤에는 읽지 않는다
    assert gh.alive_pids() == []


@pytest.mark.parametrize("status", [429, 403])
def test_req091_retry_after_is_honoured(tmp_path, collect_env, status):
    env = {key: value for key, value in collect_env.items() if key != "TD_COLLECT_RETRY_DELAYS"}
    gh = fake_gh(tmp_path, {"o/a": {"runs": ["success"],
                                    "fail": {"status": status, "retry_after": 1, "times": 1, "on": "runs"}}})
    out = run_collect(tmp_path, cfg_with(plain="a"), gh=gh, env=env)
    calls = _calls_to(gh, "repos/o/a/actions/runs")
    assert len(calls) == 2 and calls[1].at - calls[0].at >= 1.0
    assert snapshot(tmp_path, "a")["ci"]["runs"] == 1 and out["status"] == "ok"


def test_req091_retry_after_beyond_budget_not_awaited(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {"o/a": {"fail": {"status": 429, "retry_after": 30, "times": 1, "on": "runs"}}})
    started = time.monotonic()
    out = run_collect(tmp_path, cfg_with(plain="a"), gh=gh, env={**collect_env, "TD_COLLECT_BUDGET_SEC": "10"})
    assert time.monotonic() - started < 10
    assert len(_calls_to(gh, "repos/o/a/actions/runs")) == 1
    snap = snapshot(tmp_path, "a")
    assert snap["ci"]["runs"] is None and snap["sources"]["ci"] == "failed" and out["status"] == "degraded"
    assert "Retry-After" in snap["problems"][0]["reason"]


def test_req091_at_most_three_attempts(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {"o/a": {"fail": {"status": 500, "times": 99, "on": "runs"}},
                            "o/b": {"fail": {"status": 502, "times": 99, "on": "repo"}}})
    out = run_collect(tmp_path, cfg_with(plain=["a", "b"]), gh=gh, env=collect_env)
    assert len(_calls_to(gh, "repos/o/a/actions/runs")) == 3
    assert snapshot(tmp_path, "a")["sources"]["ci"] == "failed"
    assert len([call for call in gh.calls if call[2] == "repos/o/b"]) == 3
    assert out["unverified"] == ["b"] and not (tmp_path / "site/projects/b").exists()


# --- REQ-092 ~ 094, 097: 수집 토큰 ----------------------------------------------------------------------

def test_req092_token_removed_on_all_exits(tmp_path, collect_env):
    names = []
    for mode in ("ok", "sonar-500", "lost-insert-reply"):
        ssh = fake_ssh(tmp_path / mode, lose_insert_reply=(mode == "lost-insert-reply"))
        proc = run_collect_sh(tmp_path / mode, mode, ssh=ssh, env=collect_env)
        assert proc.returncode == 0 and ssh.rows() == [], (mode, proc.stdout, proc.stderr)
        names += sorted(set(re.findall(TOKEN_NAME_PATTERN, ssh.log())))
        assert "+ 7200000" in ssh.log()
        out = json.loads(proc.stdout)
        if mode == "sonar-500":
            assert snapshot(tmp_path / mode, "a")["sources"]["sonar"] == "failed" and out["status"] == "degraded"
        if mode == "lost-insert-reply":
            assert "Sonar 토큰 발급 실패" in out["reasons"]
            assert snapshot(tmp_path / mode, "a")["problems"][-1]["reason"] == "Sonar 토큰 없음"
    assert len(names) == 3 and len(set(names)) == 3


def test_req093_cleanup_failure_warns_degraded(tmp_path, collect_env):
    ssh = fake_ssh(tmp_path, fail_delete=True)
    proc = run_collect_sh(tmp_path, ssh=ssh, env=collect_env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["status"] == "degraded" and "Sonar 토큰 정리 실패" in out["reasons"]
    name = re.search(TOKEN_NAME_PATTERN, ssh.log()).group(0)
    assert proc.stderr.count("토큰 잔존 가능") == 1 and "2시간 후" in proc.stderr and name in proc.stderr
    assert name not in proc.stdout


def test_req094_token_not_leaked_and_not_issued_when_unneeded(tmp_path, collect_env):
    root = tmp_path / "with-sonar"
    ssh = fake_ssh(root)
    observed = tmp_path / "observed-token"
    proc = run_collect_sh(root, ssh=ssh, env=collect_env, extra={"TD_SONAR_TOKEN_OBSERVE": str(observed)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    token = observed.read_text()
    assert token.startswith("squ_") and token != collect_env["SONAR_TOKEN"]
    assert token not in proc.stdout and token not in proc.stderr
    for path in (p for p in (root / "site").rglob("*") if p.is_file()):
        assert token not in path.read_text(errors="replace"), path
    gh_args = (root / "fake-gh" / "calls.jsonl").read_text()
    assert gh_args and token not in gh_args
    assert collect_env.sonar.urls and not any(token in url for url in collect_env.sonar.urls)
    used = [auth for _method, path, _query, auth in collect_env.sonar.requests
            if path == "/api/qualitygates/project_status"]
    assert used and all(auth == f"Bearer {token}" for auth in used)      # 발급한 토큰으로 읽었다(헤더로만)
    assert snapshot(root, "a")["sources"]["sonar"] == "ok"

    quiet_root = tmp_path / "no-sonar"
    quiet_ssh = fake_ssh(quiet_root)
    quiet_gh = fake_gh(quiet_root, {})
    proc = run_collect_sh(quiet_root, ssh=quiet_ssh, env=collect_env, cfg=cfg_with(pipeline="p"), gh=quiet_gh)
    assert proc.returncode == 0 and json.loads(proc.stdout)["status"] == "ok", proc.stdout + proc.stderr
    assert quiet_ssh.log() == "" and quiet_gh.calls == []


def test_req097_s11_and_collect_tokens_coexist(tmp_path, collect_env):
    ssh = fake_ssh(tmp_path)
    ssh.seed("td-r1")
    proc = run_collect_sh(tmp_path, ssh=ssh, env=collect_env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ssh.rows() == ["td-r1"] and re.search(TOKEN_NAME_PATTERN, ssh.log())


# --- REQ-095, 096: Sonar 출처와 가리기 ----------------------------------------------------------------

def test_req095_pipeline_project_sonar_from_run(tmp_path, collect_env):
    cfg = {"schema": 1, "projects": [{"name": "p1", "repo": "o/p1", "sut": "p1"},
                                     {"name": "p2", "repo": "o/p2", "sut": "p2"},
                                     {"name": "p3", "repo": "o/p3", "sut": "p3"}]}
    site = make_site(tmp_path, config=cfg, runs={"p1": [{"runId": RUN_C["runId"]}],
                                                 "p2": [{"runId": RUN_C["runId"], "sonar": None}]})
    (tmp_path / "suts/p3/sut.yaml").write_text("name: p3\nsonar:\n  projectKey: key-from-sut\n")
    collect_env.sonar.set_project("key-from-sut", gate="OK", coverage="66.6", bugs="1", vulnerabilities="0",
                                  code_smells="2")
    gh = fake_gh(tmp_path, {"o/p1": {}, "o/p2": {}, "o/p3": {}})
    needs = _collect_proc(tmp_path, "needs-sonar", gh=gh, env=collect_env)
    assert needs.returncode == 0 and needs.stdout.strip() == "1", needs.stderr
    run_collect(tmp_path, None, gh=gh, env=collect_env)
    assert {key for _path, key in collect_env.sonar.keyed_requests} == {"key-from-sut"}
    for name in ("p1", "p2"):
        snap = snapshot(tmp_path, name)
        assert snap["sonar"] is None and snap["sources"]["sonar"] == "skipped"
    assert snapshot(tmp_path, "p3")["sonar"]["coverage"] == 66.6
    views = {view["name"]: view["values"] for view in metrics.build_projects(site, load_cfg(site))}
    run_sonar = json.loads((site / f"suts/p1/runs/{RUN_C['runId']}/run.json").read_text())["kpis"]["sonar"]
    assert (views["p1"]["sonar.gate"], views["p1"]["sonar.coverage"], views["p1"]["sonar.bugs"],
            views["p1"]["sonar.vulnerabilities"], views["p1"]["sonar.codeSmells"]) == (
        run_sonar["gate"], float(run_sonar["coverage"]), int(run_sonar["bugs"]), int(run_sonar["vulnerabilities"]),
        int(run_sonar["codeSmells"]))
    assert all(views["p2"][name] is None for name in metrics.SONAR_METRICS)
    assert views["p3"]["sonar.coverage"] == 66.6


def test_req096_external_text_redacted(tmp_path, collect_env):
    work_path = f"{REPO_ROOT}/work/private-build/output"
    arn = "arn:aws:iam::123456789012:role/collector"
    gh = fake_gh(tmp_path, {"o/a": {"description": f"built at {work_path} by {arn}"}})
    out = run_collect(tmp_path, cfg_with(plain="a"), gh=gh, env=collect_env)
    site = tmp_path / "site"
    description = snapshot(tmp_path, "a")["repoInfo"]["description"]
    assert description == "built at <work>/private-build/output by <arn>"
    written = [site / relative for relative in out["written"]] + rebuild_site(site)
    for path in written:
        text = path.read_text(errors="replace")
        assert work_path not in text and arn not in text, path
        check_no_home_in_file(path, path.name)


# --- 설정 오류, 주입 지점, 신호 ---------------------------------------------------------------------------

def test_req089_invalid_repo_is_config_error(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {})
    make_site(tmp_path, config={"schema": 1, "projects": [{"name": "a", "repo": "o/a"},
                                                          {"name": "b", "repo": "o/b?per_page=1"}]})
    proc = _collect_proc(tmp_path, "run", gh=gh, env=collect_env)
    assert proc.returncode == 2 and "projects[1].repo" in proc.stderr and proc.stdout == ""
    assert gh.calls == [] and not (tmp_path / "site/projects").exists()
    make_site(tmp_path, config={"schema": 1, "projects": [{"name": "a", "repo": "o/.."}]})
    proc = _collect_proc(tmp_path, "needs-sonar", gh=gh, env=collect_env)
    assert proc.returncode == 2 and "projects[0].repo" in proc.stderr


def test_req099_collect_sh_injection_points(tmp_path, collect_env):
    """Task 11이 쓰는 수집 쪽 주입 지점: exit1, garbage, degraded. 접두 없이 쓰면 거부된다."""
    results = {}
    for point in ("exit1", "garbage", "degraded"):
        ssh = fake_ssh(tmp_path / point)
        results[point] = (run_collect_sh(tmp_path / point, ssh=ssh, env=collect_env,
                                         extra={"TD_FAIL_STAGE": f"collect:{point}"}), ssh)
    proc, ssh = results["exit1"]
    assert proc.returncode == 1 and proc.stdout == "" and ssh.log() == ""
    proc, ssh = results["garbage"]
    assert proc.returncode == 0 and proc.stdout.strip() and ssh.log() == ""
    with pytest.raises(ValueError):
        json.loads(proc.stdout)
    proc, ssh = results["degraded"]
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["status"] == "degraded" and out["reasons"][-1] == "injected"
    assert (tmp_path / "degraded/site/projects/a/latest.json").exists() and ssh.rows() == []

    ssh = fake_ssh(tmp_path / "refused")
    gh = fake_gh(tmp_path / "refused", {"o/a": {}})
    make_site(tmp_path / "refused", config=cfg_with(plain="a"))
    env = {**_base_env(), "TD_ROOT": str(REPO_ROOT), "TD_GH_BIN": str(gh.path), "TD_FAIL_STAGE": "collect:exit1"}
    proc = subprocess.run(["bash", str(COLLECT_SH), "--config", str(tmp_path / "refused/dashboard.yaml"), "--site",
                           str(tmp_path / "refused/site"), "--suts-dir", str(tmp_path / "refused/suts")],
                          capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 1 and "거부" in proc.stderr and gh.calls == []


@pytest.mark.parametrize("signal_number", [signal.SIGTERM, signal.SIGINT])
def test_req144_collect_sh_signal_revokes_token(tmp_path, collect_env, signal_number):
    """collect.sh 자신의 trap: 신호를 받으면 td.collect 자식에 넘기고 기다린 뒤 토큰을 정리한다."""
    ssh = fake_ssh(tmp_path)
    gh = fake_gh(tmp_path, {"o/a": {}})
    make_site(tmp_path, config=cfg_with(plain="a"))
    collect_env.sonar.delays["a"] = 8
    env = {**_base_env(), "TD_ROOT": str(REPO_ROOT), "TD_WORK_DIR": str(tmp_path / "work"),
           **{key: value for key, value in collect_env.items() if key != "SONAR_TOKEN"},
           **token_env(tmp_path, ssh, collect_env.sonar.url), "TD_DOMAIN": "example.invalid", "TD_GH_BIN": str(gh.path)}
    process = subprocess.Popen(["bash", str(COLLECT_SH), "--config", str(tmp_path / "dashboard.yaml"), "--site",
                                str(tmp_path / "site"), "--suts-dir", str(tmp_path / "suts")],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                               start_new_session=True)
    try:
        deadline = time.monotonic() + 60
        while not collect_env.sonar.keyed_requests and time.monotonic() < deadline:
            time.sleep(0.1)
        assert collect_env.sonar.keyed_requests, "수집이 Sonar 읽기에 닿지 않았다"
        assert ssh.rows() and ssh.rows()[0].startswith("td-collect-")
        process.send_signal(signal_number)
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 128 + signal_number, stdout + stderr
        assert ssh.rows() == [], stderr
        assert not (tmp_path / "site/projects/a").exists()
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)       # collect.sh와 td.collect가 모두 끝났다
        assert gh.alive_pids() == []
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
