"""run 상태 기록: `run.json`, `stages/<ID>.json`, 의존성 표, 종료 코드.

의존성 표(설계 §5)는 DEPENDENCIES에 두고, 건너뜀·축소(degraded) 전파는 이 표로만 판정한다.
단계 스크립트는 begin/end만 호출하고, 오케스트레이터(run-all.sh)가 prepare/post로 표를 적용한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

STAGE_IDS = [f"S{i:02d}" for i in range(14)]
# 실행 순서: S04(onto-viz)는 S03/S05 산출물을 시각화하므로 S05 뒤에 돈다(번호 순서와 다른 유일한 자리).
EXECUTION_ORDER = ["S00", "S01", "S02", "S03", "S05", "S04", "S06", "S07", "S08", "S09", "S10", "S11", "S12", "S13"]
STATUSES = ("passed", "failed", "degraded", "skipped")
TZ_NAME = "Asia/Seoul"
ARMS_ALL = ("base", "jqa", "owl")
PUBLISH_STAGE = "S13"
ABORT_STAGE = "S00"  # 실패하면 run 중단, 종료 코드 1
STUB_INPUT_HASH = "00000000"
NOT_REQUESTED = "not-requested"


@dataclass(frozen=True)
class Dep:
    """required: 모두 가용해야 실행. any_of: 하나 이상 가용해야 실행(일부만 가용이면 degraded).
    optional: 가용하지 않으면 축소 실행(degraded). degrade_with: 이 단계가 degraded이면 함께 degraded."""

    required: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    degrade_with: tuple[str, ...] = ()


DEPENDENCIES: dict[str, Dep] = {
    "S00": Dep(),
    "S01": Dep(required=("S00",)),
    "S02": Dep(required=("S00",)),
    "S03": Dep(required=("S00",)),
    "S04": Dep(any_of=("S03", "S05")),
    "S05": Dep(required=("S03", "S02")),
    "S06": Dep(required=("S02",)),  # arm별 의존은 ARM_DEPENDENCIES
    "S07": Dep(required=("S06",)),  # generation별 의존은 S06 결과
    "S08": Dep(any_of=("S01", "S07")),
    "S09": Dep(required=("S00",), optional=("S08",)),
    "S10": Dep(required=("S00",), optional=("S07",)),
    "S11": Dep(required=("S00",), optional=("S08",)),
    "S12": Dep(required=("S07", "S08"), degrade_with=("S07",)),
    "S13": Dep(),
}
# 모든 arm은 S02(bbtg)에 의존한다. 그 밖의 추가 의존.
ARM_DEPENDENCIES: dict[str, tuple[str, ...]] = {"base": (), "jqa": ("S03",), "owl": ("S05",)}


# --- 시간 -----------------------------------------------------------------------
def now(finished: bool = False) -> datetime:
    """UTC 현재 시각. 테스트는 TD_NOW(시작), TD_NOW_FINISHED(종료)로 Clock을 주입한다."""
    raw = (os.environ.get("TD_NOW_FINISHED") if finished else None) or os.environ.get("TD_NOW")
    if raw and os.environ.get("TD_SITE_PREFIX"):  # Clock 주입은 테스트 전용
        return parse_utc(raw)
    if raw:
        print("state: TD_NOW/TD_NOW_FINISHED는 TD_SITE_PREFIX가 없으면 무시한다", file=sys.stderr)
    return datetime.now(timezone.utc)


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def fmt_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- 파일 입출력 ---------------------------------------------------------------------
def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n")
    os.replace(tmp, path)


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def run_json_path(run_dir) -> Path:
    return Path(run_dir) / "run.json"


def stage_path(run_dir, stage_id: str) -> Path:
    return Path(run_dir) / "stages" / f"{stage_id}.json"


def read_run(run_dir) -> dict:
    return _read_json(run_json_path(run_dir), {})


def read_stage(run_dir, stage_id: str) -> dict | None:
    return _read_json(stage_path(run_dir, stage_id))


def stage_status(run_dir, stage_id: str) -> str | None:
    data = read_stage(run_dir, stage_id)
    return data["status"] if data else None


# --- run.json -----------------------------------------------------------------------
def write_run_meta(run_dir, **fields) -> dict:
    """run.json에 필드를 병합한다. startedAt/finishedAt이 있으면 sutDate, clockShift를 계산한다."""
    run = read_run(run_dir)
    run.setdefault("pr", None)
    run.setdefault("tz", TZ_NAME)
    run.update(fields)
    tz = ZoneInfo(run["tz"])
    if run.get("startedAt") and "sutDate" not in fields:
        run["sutDate"] = parse_utc(run["startedAt"]).astimezone(tz).date().isoformat()
    if run.get("startedAt") and run.get("finishedAt"):
        started = parse_utc(run["startedAt"]).astimezone(tz).date()
        finished = parse_utc(run["finishedAt"]).astimezone(tz).date()
        run["clockShift"] = started != finished
    run.setdefault("stages", {})
    _write_json(run_json_path(run_dir), run)
    return run


def set_run_field(run_dir, dotted_path: str, value) -> None:
    """`kpis.blackbox` 같은 점 경로로 run.json 값을 쓴다(중간 dict는 만든다)."""
    run = read_run(run_dir)
    cursor = run
    *parents, leaf = dotted_path.split(".")
    for key in parents:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = cursor[key] = {}
        cursor = nxt
    cursor[leaf] = value
    _write_json(run_json_path(run_dir), run)


def _set_run_stage(run_dir, stage_id: str, status: str) -> None:
    run = read_run(run_dir)
    run.setdefault("stages", {})[stage_id] = status
    _write_json(run_json_path(run_dir), run)


def _frozen(run_dir) -> bool:
    return read_run(run_dir).get("stages", {}).get(PUBLISH_STAGE) == "publishing"


def finalize(run_dir) -> None:
    """finishedAt이 아직 없으면(S13이 동결하지 않았으면) 지금 시각으로 기록한다."""
    run = read_run(run_dir)
    if not run.get("finishedAt"):
        write_run_meta(run_dir, finishedAt=fmt_utc(now(finished=True)))


# --- 단계 상태 ------------------------------------------------------------------------
def begin(run_dir, stage_id: str) -> None:
    _check_stage(stage_id)
    if stage_id == PUBLISH_STAGE:
        # S13 수명주기: 시작 직전 finishedAt을 쓰고 run.json을 'publishing'으로 동결한다.
        # 같은 run의 S13 재시도에서는 처음 동결한 값을 유지한다(게시된 run.json과 바이트 단위로 같아야 한다).
        if not read_run(run_dir).get("finishedAt"):
            write_run_meta(run_dir, finishedAt=fmt_utc(now(finished=True)))
        _set_run_stage(run_dir, PUBLISH_STAGE, "publishing")
    _write_json(stage_path(run_dir, stage_id), {
        "id": stage_id, "status": "running", "reason": None,
        "startedAt": fmt_utc(now()), "outputs": {},
    })


def end(run_dir, stage_id: str, status: str, reason: str | None = None,
        outputs: dict | None = None, extra: dict | None = None) -> dict:
    _check_stage(stage_id)
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}: {status!r}")
    if status != "passed" and not (reason and reason.strip()):
        raise ValueError(f"status {status} requires a non-empty reason")
    data = read_stage(run_dir, stage_id) or {"id": stage_id, "startedAt": fmt_utc(now())}
    data.update({"id": stage_id, "status": status, "reason": reason or None,
                 "finishedAt": fmt_utc(now(finished=True))})
    data["outputs"] = {**data.get("outputs", {}), **(outputs or {})}
    data.update(extra or {})
    _write_json(stage_path(run_dir, stage_id), data)
    if not _frozen(run_dir):  # 동결된 뒤의 S13 결과는 stages/S13.json만 기준이다
        _set_run_stage(run_dir, stage_id, status)
    return data


def skip(run_dir, stage_id: str, reason: str, extra: dict | None = None) -> dict:
    return end(run_dir, stage_id, "skipped", reason, extra=extra)


def _check_stage(stage_id: str) -> None:
    if stage_id not in STAGE_IDS:
        raise ValueError(f"unknown stage id: {stage_id!r}")


def exit_code(run_dir) -> int:
    """S00이나 S13이 failed면 1, 그 밖의 failed가 있으면 2, 없으면 0."""
    failed = {sid for sid in STAGE_IDS if stage_status(run_dir, sid) == "failed"}
    if failed & {ABORT_STAGE, PUBLISH_STAGE}:
        return 1
    return 2 if failed else 0


# --- 의존성 판정 -------------------------------------------------------------------------
def _available(run_dir, stage_id: str) -> bool:
    return stage_status(run_dir, stage_id) in ("passed", "degraded")


def _neutral(run_dir, stage_id: str) -> bool:
    """--only로 요청하지 않아 건너뛴 단계. 선택·any_of·degrade_with 의존에서는 중립이다."""
    data = read_stage(run_dir, stage_id)
    return bool(data) and data["status"] == "skipped" and data.get("reason") == NOT_REQUESTED


def _why(run_dir, stage_id: str) -> str:
    if _neutral(run_dir, stage_id):
        return f"{stage_id} {NOT_REQUESTED}"
    return f"{stage_id} {stage_status(run_dir, stage_id) or 'not-run'}"


def _stub_mode() -> bool:
    """스텁 단계(TD_STAGE_DIR) 실행에서만 generation id를 만들어 낸다."""
    return bool(os.environ.get("TD_STAGE_DIR"))


def requested_arms(run_dir) -> list[str]:
    arms = read_run(run_dir).get("options", {}).get("arms")
    return list(arms) if arms else list(ARMS_ALL)


def requested_reps(run_dir) -> int:
    return int(read_run(run_dir).get("options", {}).get("reps") or 1)


def arm_plan(run_dir, arms: list[str] | None = None) -> dict[str, str | None]:
    """arm -> None(실행 가능) 또는 건너뜀 사유. 모든 arm은 S02에 의존하고 arm별 추가 의존이 있다."""
    result: dict[str, str | None] = {}
    for arm in arms if arms is not None else requested_arms(run_dir):
        missing = [dep for dep in ("S02", *ARM_DEPENDENCIES.get(arm, ())) if not _available(run_dir, dep)]
        result[arm] = f"dependency {_why(run_dir, missing[0])}" if missing else None
    return result


def stub_gen_id(arm: str, rep: int) -> str:
    return f"{arm}-{STUB_INPUT_HASH}-r{rep}"


def _s06_extra(run_dir) -> dict:
    plan = arm_plan(run_dir)
    arms = {}
    generations = {}
    for arm, skip_reason in plan.items():
        arms[arm] = {"status": "skipped", "reason": skip_reason} if skip_reason else {"status": "passed"}
        if _stub_mode():
            for rep in range(1, requested_reps(run_dir) + 1):
                generations[stub_gen_id(arm, rep)] = {"arm": arm, **arms[arm]}
    extra = {"arms": arms}
    if generations:
        extra["generations"] = generations
    return extra


def prepare(run_dir, stage_id: str) -> str | None:
    """실행 전 판정. 건너뛰어야 하면 사유를 돌려준다(None이면 실행)."""
    dep = DEPENDENCIES[stage_id]
    for needed in dep.required:
        if not _available(run_dir, needed):
            return f"dependency {_why(run_dir, needed)}"
    if dep.any_of and not any(_available(run_dir, sid) for sid in dep.any_of):
        return "dependency none available: " + ", ".join(_why(run_dir, sid) for sid in dep.any_of)
    if stage_id == "S06" and all(plan is not None for plan in arm_plan(run_dir).values()):
        return "dependency all arms skipped: " + "; ".join(f"{arm} ({why})" for arm, why in arm_plan(run_dir).items())
    if stage_id == "S07" and not _runnable_generations(run_dir):
        return "no runnable generation from S06"
    return None


def prepare_and_record(run_dir, stage_id: str) -> str | None:
    reason = prepare(run_dir, stage_id)
    if reason:
        extra = _s06_extra(run_dir) if stage_id == "S06" else None
        if stage_id == "S07":
            extra = _s07_extra(run_dir, {})
        skip(run_dir, stage_id, reason, extra=extra)
    return reason


def _runnable_generations(run_dir) -> dict[str, dict]:
    s06 = read_stage(run_dir, "S06") or {}
    return {gid: g for gid, g in s06.get("generations", {}).items() if g.get("status") in ("passed", "degraded")}


def _s07_extra(run_dir, own: dict) -> dict:
    """S06 generation 결과를 S07로 옮긴다. 그 generation이 건너뜀/실패였으면 S07에서도 skipped."""
    s06 = read_stage(run_dir, "S06") or {}
    merged = {}
    for gid, gen in s06.get("generations", {}).items():
        if gen.get("status") in ("passed", "degraded"):
            merged[gid] = own.get(gid) or {"arm": gen.get("arm"), "status": "passed"}
        else:
            merged[gid] = {"arm": gen.get("arm"), "status": "skipped",
                           "reason": f"S06 {gid} {gen.get('status')}: {gen.get('reason')}"}
    return {"generations": merged}


def post(run_dir, stage_id: str) -> None:
    """단계 종료 뒤 후처리: 비정상 종료 보정, arm/generation 하위 상태, degraded 전파."""
    data = read_stage(run_dir, stage_id)
    if data is None or data["status"] not in STATUSES:
        end(run_dir, stage_id, "failed", "stage ended without recording a final status")
        return
    if data["status"] in ("failed", "skipped"):
        return
    dep = DEPENDENCIES[stage_id]
    reasons: list[str] = []
    extra: dict = {}
    if stage_id == "S06":
        extra = _s06_extra(run_dir)
        for arm, state in (data.get("arms") or {}).items():  # 단계가 직접 쓴 값이 우선
            extra["arms"][arm] = state
        if data.get("generations"):  # 실제 S06이 쓴 generation이 우선
            extra["generations"] = data["generations"]
        skipped = [f"{arm} ({st.get('reason')})" for arm, st in extra["arms"].items() if st["status"] == "skipped"]
        if skipped:
            reasons.append("arm skipped: " + "; ".join(skipped))
    if stage_id == "S07":
        extra = _s07_extra(run_dir, data.get("generations") or {})
        skipped = [f"{gid} ({g['reason']})" for gid, g in extra["generations"].items() if g["status"] == "skipped"]
        if skipped:
            reasons.append("generation skipped: " + "; ".join(skipped))
    if dep.any_of:
        gone = [_why(run_dir, sid) for sid in dep.any_of
                if not _available(run_dir, sid) and not _neutral(run_dir, sid)]
        if gone:
            reasons.append("reduced input: " + ", ".join(gone))
    gone_optional = [_why(run_dir, sid) for sid in dep.optional
                     if not _available(run_dir, sid) and not _neutral(run_dir, sid)]
    if gone_optional:
        reasons.append("optional input missing: " + ", ".join(gone_optional))
    shrunk = [sid for sid in dep.degrade_with if stage_status(run_dir, sid) == "degraded"]
    if shrunk:
        reasons.append("판정 불가(arm 부족): " + ", ".join(f"{sid} degraded" for sid in shrunk))
    status, reason = data["status"], data.get("reason")
    if reasons:
        status, reason = "degraded", " | ".join(([reason] if reason else []) + reasons)
    if reasons or extra:
        end(run_dir, stage_id, status, reason, extra=extra)


# --- CLI ---------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.state")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("begin", "post", "prepare"):
        cmd = sub.add_parser(name)
        cmd.add_argument("run_dir")
        cmd.add_argument("stage")
    for name in ("end", "skip"):
        cmd = sub.add_parser(name)
        cmd.add_argument("run_dir")
        cmd.add_argument("stage")
        if name == "end":
            cmd.add_argument("status")
        cmd.add_argument("reason", nargs="?", default=None)
        cmd.add_argument("--outputs-json")
        cmd.add_argument("--extra-json")
    for name in ("exit-code", "finalize"):
        cmd = sub.add_parser(name)
        cmd.add_argument("run_dir")
    init = sub.add_parser("init")
    init.add_argument("run_dir")
    init.add_argument("--run-id", required=True)
    init.add_argument("--sut", required=True)
    init.add_argument("--commit", required=True)
    init.add_argument("--trigger", default="manual")
    init.add_argument("--options-json", default="{}")
    setter = sub.add_parser("set")
    setter.add_argument("run_dir")
    setter.add_argument("path")
    setter.add_argument("value_json")
    args = parser.parse_args(argv)
    try:
        _maybe_inject_fault(args)
        if args.cmd == "begin":
            begin(args.run_dir, args.stage)
        elif args.cmd == "end":
            end(args.run_dir, args.stage, args.status, args.reason,
                json.loads(args.outputs_json) if args.outputs_json else None,
                json.loads(args.extra_json) if args.extra_json else None)
        elif args.cmd == "skip":
            skip(args.run_dir, args.stage, args.reason or "", json.loads(args.extra_json) if args.extra_json else None)
        elif args.cmd == "prepare":  # stdout: 'run' 또는 'skip'
            print("skip" if prepare_and_record(args.run_dir, args.stage) else "run")
        elif args.cmd == "post":
            post(args.run_dir, args.stage)
        elif args.cmd == "exit-code":
            print(exit_code(args.run_dir))
        elif args.cmd == "finalize":
            finalize(args.run_dir)
        elif args.cmd == "set":
            set_run_field(args.run_dir, args.path, json.loads(args.value_json))
        elif args.cmd == "init":
            write_run_meta(args.run_dir, runId=args.run_id, sut=args.sut, commit=args.commit,
                           trigger=args.trigger, pr=None, startedAt=fmt_utc(now()),
                           options=json.loads(args.options_json))
    except Exception as exc:  # noqa: BLE001 - 호출자(run-all.sh)가 비-0을 보고 단계를 failed로 기록한다
        print(f"state: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def _maybe_inject_fault(args) -> None:
    """테스트 전용: TD_STATE_FAULT=<cmd>:<stage>(예: prepare:S03)이면 그 호출을 예외로 실패시킨다."""
    spec = os.environ.get("TD_STATE_FAULT")
    if spec and os.environ.get("TD_SITE_PREFIX") and spec == f"{args.cmd}:{getattr(args, 'stage', '')}":
        raise RuntimeError(f"injected state fault {spec}")


if __name__ == "__main__":
    sys.exit(main())
