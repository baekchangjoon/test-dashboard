"""실행 골격 수용 테스트: REQ-002, 003, 004, 006, 059, 060, td_run, 훅 거부. 스텁 단계(tests/fixtures/stub-stages)로 돈다."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from td import hooks

REPO_ROOT = Path(__file__).resolve().parents[2]
ALL_STAGES = [f"S{i:02d}" for i in range(14)]
ENUM = {"passed", "failed", "degraded", "skipped"}


def test_req002_all_stages_recorded(stub_stages):
    result = stub_stages.run()
    assert result.returncode == 0, result.stderr
    run = result.run_json
    stages = result.stages()
    assert sorted(stages) == ALL_STAGES
    assert sorted(run["stages"]) == ALL_STAGES
    for stage_id, data in stages.items():
        assert data["status"] in ENUM, (stage_id, data)
        if data["status"] != "passed":
            assert data["reason"] and data["reason"].strip()
    # run.json에서는 S13만 publishing을 허용한다(동결 시점의 값).
    assert run["stages"]["S13"] == "publishing"
    assert all(run["stages"][sid] in ENUM for sid in ALL_STAGES if sid != "S13")


@pytest.mark.parametrize("failing", [f"S{i:02d}" for i in range(1, 13)])
def test_req003_exit_codes_single_stage_2(injected_run, failing):
    result = injected_run(failing)
    assert result.returncode == 2, result.stderr
    assert result.stage(failing)["status"] == "failed"
    assert "TD_FAIL_STAGE" in result.stage(failing)["reason"]


def test_req003_exit_codes_publish_and_prepare_1(injected_run):
    assert injected_run("S13").returncode == 1
    result = injected_run("S00")
    assert result.returncode == 1
    # S00 실패는 run 중단: 나머지는 skipped, 14개 기록은 유지된다.
    assert sorted(result.stages()) == ALL_STAGES
    assert result.stage("S01")["status"] == "skipped" and "S00" in result.stage("S01")["reason"]


def test_req003_exit_codes_combined_and_clean(injected_run, stub_stages):
    assert injected_run("S09,S13").returncode == 1
    assert stub_stages.run().returncode == 0


def test_req003_point_hooks_only_match_their_point(injected_run):
    # 스텁은 점 없는 훅만 호출하므로 S11:scan은 걸리지 않는다.
    assert injected_run("S11:scan").returncode == 0


def test_req004_only_marks_not_requested(stub_stages):
    result = stub_stages.run("--only", "S00,S01")
    assert result.returncode == 0, result.stderr
    stages = result.stages()
    assert stages["S00"]["status"] == "passed" and stages["S01"]["status"] == "passed"
    for stage_id in ALL_STAGES[2:]:
        assert stages[stage_id]["status"] == "skipped"
        assert stages[stage_id]["reason"] == "not-requested"
    assert result.run_json["stages"]["S13"] == "skipped"


def test_req006_trigger_placeholders(stub_stages):
    run = stub_stages.run().run_json
    assert run["trigger"] == "manual"
    assert "pr" in run and run["pr"] is None
    assert re.match(r"^\d{8}-\d{6}Z-[0-9a-f]{7}-manual-[0-9a-f]{8}$", run["runId"])


def test_req060_time_metadata(stub_stages):
    run = stub_stages.run().run_json
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    assert iso.match(run["startedAt"]) and iso.match(run["finishedAt"])
    assert run["startedAt"] <= run["finishedAt"]
    assert run["tz"] == "Asia/Seoul"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", run["sutDate"])
    assert run["clockShift"] is False


@pytest.mark.parametrize("started,finished,shift", [
    ("2026-11-18T14:59:59Z", "2026-11-18T15:00:01Z", True),   # KST 23:59:59 -> 00:00:01
    ("2026-11-18T14:59:59Z", "2026-11-18T15:00:00Z", True),   # KST 23:59:59 -> 00:00:00
    ("2026-11-18T15:00:00Z", "2026-11-18T15:30:00Z", False),  # KST 00:00:00 -> 00:30:00
])
def test_req060_time_metadata_midnight_boundaries(stub_stages, started, finished, shift):
    result = stub_stages.run(TD_NOW=started, TD_NOW_FINISHED=finished)
    run = result.run_json
    assert run["startedAt"] == started and run["finishedAt"] == finished
    assert run["clockShift"] is shift
    assert run["sutDate"] == ("2026-11-18" if started.startswith("2026-11-18T14") else "2026-11-19")


def test_req059_skip_propagation_s05(injected_run):
    result = injected_run("S05")
    assert result.returncode == 2
    s06, s07 = result.stage("S06"), result.stage("S07")
    assert s06["arms"]["owl"]["status"] == "skipped" and "S05" in s06["arms"]["owl"]["reason"]
    assert s06["arms"]["base"]["status"] == "passed" and s06["arms"]["jqa"]["status"] == "passed"
    assert s06["status"] == "degraded" and s07["status"] == "degraded"
    owl_gens = {g: v for g, v in s07["generations"].items() if v["arm"] == "owl"}
    assert owl_gens and all(v["status"] == "skipped" and "S05" in v["reason"] for v in owl_gens.values())
    other = [v for v in s07["generations"].values() if v["arm"] != "owl"]
    assert other and all(v["status"] == "passed" for v in other)
    assert result.stage("S04")["status"] == "degraded"
    assert result.stage("S12")["status"] == "degraded"
    assert "arm" in result.stage("S12")["reason"]


def test_req059_skip_propagation_s02(injected_run):
    result = injected_run("S02")
    assert result.returncode == 2
    s06 = result.stage("S06")
    assert s06["status"] == "skipped" and "S02" in s06["reason"]
    assert all(a["status"] == "skipped" for a in s06["arms"].values())
    assert result.stage("S07")["status"] == "skipped"
    assert result.stage("S05")["status"] == "skipped"  # S05는 S02에도 의존한다
    assert result.stage("S12")["status"] == "skipped"
    assert result.stage("S08")["status"] == "degraded"  # S01만으로 축소 실행


def test_req059_skip_propagation_s03_jqa_arm(injected_run):
    result = injected_run("S03")
    s06 = result.stage("S06")
    assert s06["arms"]["jqa"]["status"] == "skipped" and "S03" in s06["arms"]["jqa"]["reason"]
    assert s06["arms"]["owl"]["status"] == "skipped"  # S05가 S03 때문에 건너뜀
    assert s06["arms"]["base"]["status"] == "passed"
    assert result.stage("S04")["status"] == "skipped"  # S03, S05 모두 없음


def test_hook_refused_without_prefix(stub_stages):
    with pytest.raises(hooks.HookRefused):
        hooks.should_fail("S05", env={"TD_FAIL_STAGE": "S05"})
    assert hooks.should_fail("S05", env={"TD_FAIL_STAGE": "S05", "TD_SITE_PREFIX": "_test/x/"}) is True
    assert hooks.should_fail("S05", env={}) is False  # 훅을 안 쓰면 거부도 없다
    # run-all도 run 디렉터리 예약 전에 거부한다.
    result = stub_stages.run(use_prefix=False, TD_FAIL_STAGE="S05")
    assert result.returncode == 1
    assert "TD_SITE_PREFIX" in result.stderr
    assert not (result.work_dir / "runs").exists()


def test_hook_parsing_points():
    env = {"TD_FAIL_STAGE": "S09, S11:scan,S13:upload-mid", "TD_SITE_PREFIX": "_test/x/"}
    assert hooks.should_fail("S09", env=env) and hooks.should_fail("S09", "anything", env=env)
    assert hooks.should_fail("S11", "scan", env=env) and not hooks.should_fail("S11", env=env)
    assert not hooks.should_fail("S11", "other", env=env)
    assert hooks.should_fail("S13", "upload-mid", env=env) and not hooks.should_fail("S13", "lightsail", env=env)
    assert not hooks.should_fail("S01", env=env)


def test_run_all_unresolvable_ref_exits_1_without_run_dir(stub_stages):
    stub_stages.sut_file.write_text(f"name: stub\nrepo: {stub_stages.sut_repo}\nref: no-such-ref\n")
    result = stub_stages.run()
    assert result.returncode == 1
    assert "no-such-ref" in result.stderr
    assert not (result.work_dir / "runs").exists()


def test_run_all_records_resolved_commit(stub_stages):
    head = subprocess.run(["git", "-C", str(stub_stages.sut_repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    result = stub_stages.run()
    assert result.run_json["commit"] == head
    assert result.run_id.split("-")[2] == head[:7]


# --- td_run -----------------------------------------------------------------------
COMMON = REPO_ROOT / "pipeline" / "lib" / "common.sh"


def _td_run(script: str, **env):
    full_env = {**os.environ, "TD_ROOT": str(REPO_ROOT), **env}
    return subprocess.run(["bash", "-c", f'source "{COMMON}"; {script}'], capture_output=True, text=True,
                          env=full_env, timeout=60)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pid: int, seconds: float = 15) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_td_run_passes_through_output_and_exit_code():
    done = _td_run('td_run 30 -- bash -c "echo hi; exit 7"')
    assert done.returncode == 7 and done.stdout.strip() == "hi"


def test_td_run_timeout_kills_group(tmp_path):
    pid_file = tmp_path / "child.pid"
    started = time.time()
    done = _td_run(f'td_run 1 -- bash -c "sleep 300 & echo \\$! > {pid_file}; wait"')
    assert done.returncode == 124
    assert re.search(r"timeout:.*bash", done.stderr)
    assert time.time() - started < 20
    assert _wait_dead(int(pid_file.read_text())), "sleep 자식이 그룹 종료 뒤에도 남아 있다"


def test_td_run_timeout_escalates_to_kill_when_term_ignored(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = f"trap '' TERM; sleep 300 & echo \\$! > {pid_file}; while true; do sleep 1; done"
    done = _td_run(f'td_run 1 -- bash -c "{script}"', TD_KILL_GRACE="1")
    assert done.returncode == 124
    assert _wait_dead(int(pid_file.read_text())), "TERM을 무시한 자손이 KILL 뒤에도 남아 있다"
