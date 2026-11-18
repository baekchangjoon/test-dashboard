"""td.state 단위 테스트(REQ-002/003/059/060 보조): 검증, S13 수명주기, 시간 경계, 의존성 표."""
import json

import pytest

from td import state


@pytest.fixture
def run_dir(tmp_path):
    state.write_run_meta(tmp_path, runId="r", startedAt="2026-11-18T01:00:00Z")
    return tmp_path


def test_end_requires_reason_unless_passed(run_dir):
    state.end(run_dir, "S01", "passed")
    for status in ("failed", "degraded", "skipped"):
        with pytest.raises(ValueError):
            state.end(run_dir, "S01", status)
        with pytest.raises(ValueError):
            state.end(run_dir, "S01", status, "   ")
    with pytest.raises(ValueError):
        state.end(run_dir, "S01", "publishing", "x")
    with pytest.raises(ValueError):
        state.end(run_dir, "S99", "passed")


def test_end_writes_stage_file_and_run_json(run_dir):
    state.begin(run_dir, "S01")
    assert state.stage_status(run_dir, "S01") == "running"
    state.end(run_dir, "S01", "degraded", "why", outputs={"a": "b"}, extra={"arms": {"x": 1}})
    data = state.read_stage(run_dir, "S01")
    assert (data["status"], data["reason"], data["outputs"], data["arms"]) == ("degraded", "why", {"a": "b"}, {"x": 1})
    assert state.read_run(run_dir)["stages"]["S01"] == "degraded"


def test_s13_lifecycle_freezes_run_json(run_dir):
    state.begin(run_dir, "S13")
    run = state.read_run(run_dir)
    assert run["stages"]["S13"] == "publishing" and run["finishedAt"]
    frozen = json.dumps(run, sort_keys=True)
    state.end(run_dir, "S13", "failed", "upload died")
    assert json.dumps(state.read_run(run_dir), sort_keys=True) == frozen  # run.json은 그대로
    assert state.stage_status(run_dir, "S13") == "failed"


def test_set_run_field_dotted_path(run_dir):
    state.set_run_field(run_dir, "kpis.blackbox", {"tc": 3})
    state.set_run_field(run_dir, "kpis.e2e", {"tc": 5})
    assert state.read_run(run_dir)["kpis"] == {"blackbox": {"tc": 3}, "e2e": {"tc": 5}}


@pytest.mark.parametrize("started,finished,shift,sut_date", [
    ("2026-11-18T14:59:59Z", "2026-11-18T15:00:01Z", True, "2026-11-18"),
    ("2026-11-18T15:00:00Z", "2026-11-18T15:30:00Z", False, "2026-11-19"),
    ("2026-11-18T14:59:59Z", "2026-11-18T14:59:59Z", False, "2026-11-18"),
])
def test_req060_clock_shift_boundaries(tmp_path, started, finished, shift, sut_date):
    run = state.write_run_meta(tmp_path, startedAt=started, finishedAt=finished)
    assert run["clockShift"] is shift and run["sutDate"] == sut_date and run["tz"] == "Asia/Seoul"


def test_td_now_injection(monkeypatch):
    monkeypatch.setenv("TD_SITE_PREFIX", "_test/x/")  # Clock 주입은 테스트 전용
    monkeypatch.setenv("TD_NOW", "2026-11-18T14:59:59Z")
    assert state.fmt_utc(state.now()) == "2026-11-18T14:59:59Z"
    assert state.fmt_utc(state.now(finished=True)) == "2026-11-18T14:59:59Z"
    monkeypatch.setenv("TD_NOW_FINISHED", "2026-11-18T15:00:01Z")
    assert state.fmt_utc(state.now(finished=True)) == "2026-11-18T15:00:01Z"


@pytest.mark.parametrize("failed,expected", [
    ([], 0), (["S05"], 2), (["S12"], 2), (["S00"], 1), (["S13"], 1), (["S09", "S13"], 1), (["S00", "S05"], 1),
])
def test_req003_exit_code_function(tmp_path, failed, expected):
    state.write_run_meta(tmp_path)
    for sid in state.STAGE_IDS:
        if sid in failed:
            state.end(tmp_path, sid, "failed", "x")
        else:
            state.end(tmp_path, sid, "skipped", "not-requested")
    assert state.exit_code(tmp_path) == expected


def test_dependencies_table_matches_design():
    assert set(state.DEPENDENCIES) == set(state.STAGE_IDS)
    assert set(state.DEPENDENCIES["S05"].required) == {"S03", "S02"}
    assert set(state.DEPENDENCIES["S04"].any_of) == {"S03", "S05"}
    assert set(state.DEPENDENCIES["S08"].any_of) == {"S01", "S07"}
    assert state.DEPENDENCIES["S06"].required == ("S02",)
    assert state.ARM_DEPENDENCIES == {"base": (), "jqa": ("S03",), "owl": ("S05",)}
    order = state.EXECUTION_ORDER
    assert sorted(order) == state.STAGE_IDS
    for sid, dep in state.DEPENDENCIES.items():  # 실행 순서는 의존성의 위상 순서다
        for upstream in (*dep.required, *dep.any_of, *dep.optional):
            assert order.index(upstream) < order.index(sid), (upstream, sid)


def test_post_marks_crashed_stage_failed(run_dir):
    state.begin(run_dir, "S01")  # end 없이 죽은 단계
    state.post(run_dir, "S01")
    data = state.read_stage(run_dir, "S01")
    assert data["status"] == "failed" and data["reason"]


def test_stub_generation_ids_only_in_stub_mode(tmp_path, monkeypatch):
    state.write_run_meta(tmp_path, options={"arms": ["base"], "reps": 1})
    state.end(tmp_path, "S02", "passed")
    monkeypatch.delenv("TD_STAGE_DIR", raising=False)
    state.end(tmp_path, "S06", "passed")
    state.post(tmp_path, "S06")
    assert "generations" not in state.read_stage(tmp_path, "S06")  # 지어내지 않는다
    monkeypatch.setenv("TD_STAGE_DIR", "/stub")
    state.post(tmp_path, "S06")
    assert list(state.read_stage(tmp_path, "S06")["generations"]) == ["base-00000000-r1"]
