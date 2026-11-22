"""기준 run과 두 번째 run을 실행하고 외부 관측 증거를 `work/acceptance-session.json`에 남긴다(Task 25, 개정 v2).

순서:
  1. Docker 자원(컨테이너·네트워크·볼륨 ID)과 GradleDaemon PID 스냅샷
  2. `run-all.sh petclinic`(기본 옵션: arms base,jqa,owl, reps 3) — 운영 게시(TD_SITE_PREFIX 없음)
  3. after 스냅샷과 기준 run의 게시 객체 ETag 목록
  4. 두 번째 run(같은 옵션, 운영 게시)
  5. 두 run의 shim 기록(`<run>/llm-calls.jsonl`) 건수
  6. 결과를 세션 파일에 저장
  7. 인덱스 전용 게시(`pipeline/publish-index.sh`) 한 번. 그 게시 기록(`<접두>publish-log/index.json`)의 상태와 사유를
     세션 파일의 `indexPublish`에 더한다(화면 재설계 요구사항명세 §0 "기준 run 세션")

디버깅 재실행은 `--prefix _test/<id>/`(운영 경로가 아닌 곳에 게시)와 `--session-file`로 운영 기록과 분리한다.
`--skip-second`면 인덱스 전용 게시도 하지 않는다.
실행: uv run --project site-gen python tests/acceptance/run_baseline.py [--prefix P] [--session-file F] [--skip-second]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import claude_call_log, docker_ids  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ALL = REPO_ROOT / "pipeline" / "run-all.sh"
PUBLISH_INDEX = REPO_ROOT / "pipeline" / "publish-index.sh"
INDEX_TIMEOUT_SEC = 1800
DEFAULT_SESSION_FILE = REPO_ROOT / "work" / "acceptance-session.json"
LOG_DIR = REPO_ROOT / "work" / "acceptance-logs"
SUT = "petclinic"
RUN_TIMEOUT_SEC = 4 * 3600


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def docker_snapshot() -> dict[str, list[str]]:
    return {"containers": sorted(docker_ids("ps", "-aq", "--no-trunc")),
            "networks": sorted(docker_ids("network", "ls", "-q", "--no-trunc")),
            "volumes": sorted(docker_ids("volume", "ls", "-q"))}


def gradle_daemons() -> list[dict]:
    """살아 있는 GradleDaemon 프로세스(PID와 시작 시각). 시작 시각으로 PID 재사용을 구별한다."""
    out = subprocess.run(["ps", "-axo", "pid=,lstart=,args="], capture_output=True, text=True,
                         env={**os.environ, "LC_ALL": "C"}).stdout
    daemons = []
    for line in out.splitlines():
        if "org.gradle.launcher.daemon.bootstrap.GradleDaemon" not in line:
            continue
        parts = line.split()
        daemons.append({"pid": int(parts[0]), "lstart": " ".join(parts[1:6])})
    return daemons


def _s3_and_bucket():
    import boto3
    state = json.loads((REPO_ROOT / "work" / "infra" / "terraform.tfstate").read_text())
    bucket = state["outputs"]["bucket"]["value"]
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-northeast-2")), bucket


def published_etags(prefix: str, run_id: str) -> dict[str, str]:
    """S3에 게시된 그 run 디렉터리 객체의 key -> ETag."""
    s3, bucket = _s3_and_bucket()
    key_prefix = f"{prefix}suts/{SUT}/runs/{run_id}/"
    etags: dict[str, str] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key_prefix):
        for item in page.get("Contents", []):
            etags[item["Key"]] = item["ETag"].strip('"')
    return etags


def stop_group(proc: subprocess.Popen, first_signal: int, grace_sec: float = 10.0) -> None:
    """td_run과 같은 정리: 프로세스 그룹에 first_signal(TERM/INT), grace_sec 뒤에도 살아 있으면 KILL."""
    try:
        os.killpg(proc.pid, first_signal)
    except ProcessLookupError:
        return
    try:
        proc.communicate(timeout=grace_sec)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()


def run_pipeline(label: str, prefix: str, extra_args: list[str]) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{label}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    env = pipeline_env(prefix)
    docker_before, daemons_before = docker_snapshot(), gradle_daemons()
    started_at, started = utc_now(), time.monotonic()
    with open(log_path, "w") as log:
        proc = subprocess.Popen(["bash", str(RUN_ALL), SUT, *extra_args], env=env, stdout=subprocess.PIPE, stderr=log,
                                text=True, start_new_session=True)
        try:
            stdout, _ = proc.communicate(timeout=RUN_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            stop_group(proc, signal.SIGTERM)
            raise SystemExit(f"{label}: {RUN_TIMEOUT_SEC}초 제한을 넘겨 중단했다. 로그: {log_path}")
        except KeyboardInterrupt:
            stop_group(proc, signal.SIGINT)
            raise
    seconds = round(time.monotonic() - started, 1)
    finished_at = utc_now()
    lines = [line for line in (stdout or "").splitlines() if line.strip()]
    run_id = lines[-1].strip() if lines else ""
    run_dir = REPO_ROOT / "work" / "runs" / run_id
    if not run_id or not (run_dir / "run.json").exists():
        raise SystemExit(f"{label}: runId를 얻지 못했다(rc={proc.returncode}). 로그: {log_path}")
    record = {
        "label": label, "runId": run_id, "runDir": str(run_dir.relative_to(REPO_ROOT)), "args": extra_args,
        "prefix": prefix, "exitCode": proc.returncode, "startedAt": started_at, "finishedAt": finished_at,
        "seconds": seconds, "log": str(log_path.relative_to(REPO_ROOT)),
        "dockerBefore": docker_before, "dockerAfter": docker_snapshot(),
        "gradleDaemonsBefore": daemons_before, "gradleDaemonsAfter": gradle_daemons(),
        "llmCalls": len(claude_call_log(run_dir)),
    }
    record["publishedEtags"] = published_etags(prefix, run_id)
    print(f"{label}: runId={run_id} exit={proc.returncode} {seconds}s llmCalls={record['llmCalls']} "
          f"published={len(record['publishedEtags'])}", file=sys.stderr)
    return record


def pipeline_env(prefix: str) -> dict[str, str]:
    """run-all.sh와 publish-index.sh에 넘길 환경: 바깥의 TD_* 변수는 버리고 저장소·작업 경로와 접두만 준다."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(REPO_ROOT / "work"))
    if prefix:
        env["TD_SITE_PREFIX"] = prefix
    return env


def read_index_log(prefix: str, not_before: dt.datetime) -> tuple[dict | None, str | None]:
    """S3의 `<접두>publish-log/index.json`을 읽어 (기록, 문제)를 돌려준다. 읽지 못했거나(오류 코드를 문제에 담는다)
    not_before보다 먼저 쓴 것(이번 게시가 쓰지 않은 기록)이면 기록은 None이고 문제에 까닭을 적는다."""
    from botocore.exceptions import ClientError
    s3, bucket = _s3_and_bucket()
    try:
        response = s3.get_object(Bucket=bucket, Key=f"{prefix}publish-log/index.json")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code") or "?"
        return None, f"publish-log/index.json을 읽지 못했다(S3 {code})"
    if response["LastModified"] < not_before:
        return None, "publish-log/index.json이 이번 게시 시작 이전에 쓴 것이다(이번 게시가 기록을 쓰지 않았다)"
    return json.loads(response["Body"].read()), None


def run_index_publish(prefix: str) -> dict:
    """`pipeline/publish-index.sh`를 한 번 돌리고 그 게시 기록의 상태·사유와 종료 코드를 돌려준다."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"index-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    # S3 LastModified는 초 단위로 잘리므로 시작 시각도 초 단위로 내려 비교한다
    started = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    with open(log_path, "w") as log:
        proc = subprocess.Popen(["bash", str(PUBLISH_INDEX)], env=pipeline_env(prefix), stdout=log, stderr=log,
                                text=True, start_new_session=True)
        try:
            proc.wait(timeout=INDEX_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            stop_group(proc, signal.SIGTERM)
            raise SystemExit(f"index: {INDEX_TIMEOUT_SEC}초 제한을 넘겨 중단했다. 로그: {log_path}")
        except KeyboardInterrupt:
            stop_group(proc, signal.SIGINT)
            raise
    document, problem = read_index_log(prefix, started)
    record = {"exitCode": proc.returncode, "log": str(log_path.relative_to(REPO_ROOT))}
    if document is None:
        record.update(status=None, reason=problem)
    else:
        record.update(status=document.get("status"), reason=document.get("reason"))
    print(f"index: status={record['status']} exit={proc.returncode} reason={record['reason']}", file=sys.stderr)
    return record


def record_index_publish(prefix: str, session_file: Path, session: dict, *, publisher=None) -> dict:
    """두 번째 run 뒤 인덱스 전용 게시를 한 번 돌리고 `indexPublish`를 세션 파일에 더한다. 게시가 예외로 끝나도 그 사실을
    `indexPublish.status=None`과 사유로 남긴 뒤 다시 올린다. publisher는 테스트용 대체 지점이다."""
    publisher = publisher or run_index_publish
    try:
        session["indexPublish"] = publisher(prefix)
    except BaseException as exc:  # noqa: BLE001 - 증거를 남긴 뒤 다시 올린다
        session["indexPublish"] = {"status": None, "reason": f"{type(exc).__name__}: {exc}"[:2000]}
        write_session(session_file, session)
        raise
    write_session(session_file, session)
    return session


def write_session(session_file: Path, session: dict) -> None:
    """세션 파일을 원자적으로 쓴다(임시 파일 + rename)."""
    session_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = session_file.with_name(session_file.name + ".tmp")
    tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, session_file)


def check_target(prefix: str, session_file: Path) -> None:
    """운영 게시(접두 없음)는 기본 세션 파일에만, 접두 게시는 기본이 아닌 세션 파일에만 기록한다."""
    is_default = session_file.resolve() == DEFAULT_SESSION_FILE.resolve()
    if not prefix and not is_default:
        raise SystemExit("운영 게시(--prefix 없음)는 기본 세션 파일에만 기록한다")
    if prefix and is_default:
        raise SystemExit("--prefix 디버깅 실행은 기본 세션 파일(work/acceptance-session.json)에 쓸 수 없다: --session-file을 준다")


def run_session(prefix: str, session_file: Path, run_all_args: list[str], skip_second: bool = False, *,
                runner=None, etags=None) -> dict:
    """기준 run 직후 세션 파일을 한 번 쓰고(두 번째 기록 없음), 두 번째 run 뒤 다시 쓴다. 두 번째 run이 실패하면
    `secondError`를 남기고 그래도 쓴다. runner/etags는 테스트용 대체 지점이다."""
    runner = runner or run_pipeline
    etags = etags or published_etags
    check_target(prefix, session_file)
    session = {"schema": 1, "sut": SUT, "createdAt": utc_now(), "prefix": prefix}
    session["baseline"] = runner("baseline", prefix, run_all_args)
    write_session(session_file, session)
    if skip_second:
        return session
    try:
        session["baselineEtagsBeforeSecond"] = etags(prefix, session["baseline"]["runId"])
        session["second"] = runner("second", prefix, run_all_args)
        session["baselineEtagsAfterSecond"] = etags(prefix, session["baseline"]["runId"])
    except BaseException as exc:  # noqa: BLE001 - SystemExit, boto3 오류, Ctrl-C도 증거로 남긴 뒤 다시 올린다
        session["secondError"] = f"{type(exc).__name__}: {exc}"[:2000]
        write_session(session_file, session)
        raise
    write_session(session_file, session)
    return session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", default="", help="게시 접두(디버깅 전용, 예: _test/dbg1/). 비우면 운영 게시")
    parser.add_argument("--session-file", default=str(DEFAULT_SESSION_FILE))
    parser.add_argument("--skip-second", action="store_true", help="기준 run만 실행(디버깅)")
    parser.add_argument("run_all_args", nargs="*", help="run-all.sh에 넘길 추가 인자(기본 없음 = 기본 옵션)")
    args = parser.parse_args(argv)
    session_file = Path(args.session_file)
    session = run_session(args.prefix, session_file, args.run_all_args, args.skip_second)
    if args.skip_second:
        print(f"session written: {session_file}", file=sys.stderr)
        return 0
    record_index_publish(args.prefix, session_file, session)
    print(f"session written: {session_file}", file=sys.stderr)
    # 인덱스 전용 게시가 passed·degraded가 아니거나(baseline_site fixture와 같은 기준) 그 기록을 읽지 못했으면
    # 세션은 남기되 0이 아닌 코드로 알린다
    return 0 if session["indexPublish"]["status"] in ("passed", "degraded") else 1


if __name__ == "__main__":
    sys.exit(main())
