"""기준 run과 두 번째 run을 실행하고 외부 관측 증거를 `work/acceptance-session.json`에 남긴다(Task 25, 개정 v2).

순서:
  1. Docker 자원(컨테이너·네트워크·볼륨 ID)과 GradleDaemon PID 스냅샷
  2. `run-all.sh petclinic`(기본 옵션: arms base,jqa,owl, reps 3) — 운영 게시(TD_SITE_PREFIX 없음)
  3. after 스냅샷과 기준 run의 게시 객체 ETag 목록
  4. 두 번째 run(같은 옵션, 운영 게시)
  5. 두 run의 shim 기록(`<run>/llm-calls.jsonl`) 건수
  6. 결과를 세션 파일에 저장

디버깅 재실행은 `--prefix _test/<id>/`(운영 경로가 아닌 곳에 게시)와 `--session-file`로 운영 기록과 분리한다.
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
        if "GradleDaemon" not in line or "org.gradle.launcher.daemon.bootstrap.GradleDaemon" not in line:
            continue
        parts = line.split()
        daemons.append({"pid": int(parts[0]), "lstart": " ".join(parts[1:6])})
    return daemons


def published_etags(prefix: str, run_id: str) -> dict[str, str]:
    """S3에 게시된 그 run 디렉터리 객체의 key -> ETag."""
    import boto3
    state = json.loads((REPO_ROOT / "work" / "infra" / "terraform.tfstate").read_text())
    bucket = state["outputs"]["bucket"]["value"]
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))
    key_prefix = f"{prefix}suts/{SUT}/runs/{run_id}/"
    etags: dict[str, str] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key_prefix):
        for item in page.get("Contents", []):
            etags[item["Key"]] = item["ETag"].strip('"')
    return etags


def run_pipeline(label: str, prefix: str, extra_args: list[str]) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{label}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(REPO_ROOT / "work"))
    if prefix:
        env["TD_SITE_PREFIX"] = prefix
    docker_before, daemons_before = docker_snapshot(), gradle_daemons()
    started_at, started = utc_now(), time.monotonic()
    with open(log_path, "w") as log:
        proc = subprocess.Popen(["bash", str(RUN_ALL), SUT, *extra_args], env=env, stdout=subprocess.PIPE, stderr=log,
                                text=True, start_new_session=True)
        try:
            stdout, _ = proc.communicate(timeout=RUN_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            stdout, _ = proc.communicate(timeout=300)
        except KeyboardInterrupt:
            os.killpg(proc.pid, signal.SIGINT)
            proc.communicate(timeout=300)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", default="", help="게시 접두(디버깅 전용, 예: _test/dbg1/). 비우면 운영 게시")
    parser.add_argument("--session-file", default=str(DEFAULT_SESSION_FILE))
    parser.add_argument("--skip-second", action="store_true", help="기준 run만 실행(디버깅)")
    parser.add_argument("run_all_args", nargs="*", help="run-all.sh에 넘길 추가 인자(기본 없음 = 기본 옵션)")
    args = parser.parse_args(argv)
    session_file = Path(args.session_file)
    if not args.prefix and session_file.resolve() != DEFAULT_SESSION_FILE.resolve():
        raise SystemExit("운영 게시는 기본 세션 파일에만 기록한다")
    session = {"schema": 1, "sut": SUT, "createdAt": utc_now(), "prefix": args.prefix}
    session["baseline"] = run_pipeline("baseline", args.prefix, args.run_all_args)
    if not args.skip_second:
        before_second = published_etags(args.prefix, session["baseline"]["runId"])
        session["second"] = run_pipeline("second", args.prefix, args.run_all_args)
        session["baselineEtagsAfterSecond"] = published_etags(args.prefix, session["baseline"]["runId"])
        session["baselineEtagsBeforeSecond"] = before_second
    session_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = session_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, session_file)
    print(f"session written: {session_file}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
