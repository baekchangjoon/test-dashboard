"""대시보드 화면 재설계의 공용 테스트 기반(Task 3에서 만들고 뒤 Task가 넓힌다).

사이트 디렉터리 구조:
  <root>/dashboard.yaml              설정(load_cfg가 읽는다)
  <root>/suts/<sut>/sut.yaml         설정 검증용 SUT 기술자(최소 내용)
  <root>/site/                       게시 사이트(미러) — make_site가 돌려주는 경로
    suts/<sut>/runs/<runId>/          완료 run
    projects/<name>/snapshots/<date>.json   수집 스냅숏
    projects/_collect.json            마지막 수집 상태(write_collect_state)
"""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

import yaml

from helpers import make_site_run
from td import dashboard_config
from td.dashboard_config import Config
from td.site import index

ALL_STAGES = [f"S{number:02d}" for number in range(13)]     # S00~S12 (S13은 게시 단계)
STAGE_STEP = timedelta(seconds=30)

DEFAULT_SONAR = {"gate": "OK", "coverage": "57.1", "bugs": "2", "vulnerabilities": "18", "codeSmells": "69",
                 "issues": 89, "hotspots": 1}
DEFAULT_TOP10 = [{"name": "Owner.getPet", "file": "Owner.java", "method": "getPet", "score": 27.345}]
DEFAULT_IMPACT = {"selected": 68, "indexedTests": 134}
DEFAULT_GENERATIONS = {"base-r1": (21, 31)}

# runs 인자에 넣는 run 정의: runId와 write_run overrides. runId 순서 = A < B < C.
RUN_A = {"runId": "20261118-101500Z-aaaaaaa-manual-0000000a", "started": "2026-11-18T10:15:00Z",
         "tests_pass": 0.9, "line": 0.38, "agg_line": 0.55}
RUN_B = {"runId": "20261119-101500Z-bbbbbbb-manual-0000000b", "started": "2026-11-19T10:15:00Z",
         "tests_pass": 0.95, "line": 0.4, "agg_line": 0.58}
RUN_C = {"runId": "20261120-131022Z-ccccccc-manual-0000000c", "started": "2026-11-20T13:10:22Z",
         "tests_pass": 1.0, "line": 0.4152, "agg_line": 0.6091}


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _started_from_run_id(run_id: str) -> str:
    return f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}T{run_id[9:11]}:{run_id[11:13]}:{run_id[13:15]}Z"


# --- run ---------------------------------------------------------------------------------------

def write_run(base: Path, sut: str, run_id: str, *, tests_pass: float | None = 1.0, line: float | None = 0.4152,
              agg_line: float | None = 0.6091, generations: dict | None = None, sonar: dict | None = DEFAULT_SONAR,
              top10: list | None = None, impact: dict | None = None, started: str | None = None,
              last_finished: str | None = None, only_stages: Iterable[str] | None = None,
              stage_status: dict | None = None) -> Path:
    """`<base>/suts/<sut>/runs/<runId>/`에 완료 run을 만든다(run.json kpis, 단계 JSON 시각, S07·S09·S10 내용).

    단계는 S00~S12(only_stages로 줄인다)이고 상태는 passed(stage_status로 덮는다)이다. 단계 시각은 started부터
    30초 간격이고, 마지막 단계의 finishedAt은 last_finished(없으면 started + 단계 수 × 30초)다.
    """
    stage_ids = list(only_stages) if only_stages is not None else list(ALL_STAGES)
    statuses = {stage_id: "passed" for stage_id in stage_ids}
    statuses.update({stage_id: status for stage_id, status in (stage_status or {}).items() if stage_id in statuses})
    started = started or _started_from_run_id(run_id)
    kpis: dict = {
        "tests": {"suite": "blackbox", "passed": 35, "total": 35, "passRate": tests_pass},
        "blackbox": {"line": line, "branch": 0.308, "aggregate": {"line": agg_line, "branch": 0.34}},
    }
    if sonar is not None:
        kpis["sonar"] = dict(sonar)
    run_dir = make_site_run(base, sut, run_id, kpis=kpis, stages=statuses)
    run_file = run_dir / "run.json"
    run = json.loads(run_file.read_text())
    run["startedAt"] = started
    run_file.write_text(json.dumps(run))

    start_moment = _parse_iso(started)
    final_moment = _parse_iso(last_finished) if last_finished else start_moment + STAGE_STEP * len(stage_ids)
    generations = DEFAULT_GENERATIONS if generations is None else generations
    for position, stage_id in enumerate(stage_ids):
        stage_file = run_dir / "stages" / f"{stage_id}.json"
        data = json.loads(stage_file.read_text())
        stage_start = start_moment + STAGE_STEP * position
        stage_end = final_moment if position == len(stage_ids) - 1 else min(stage_start + STAGE_STEP, final_moment)
        data.update(startedAt=_iso(stage_start), finishedAt=_iso(stage_end))
        if stage_id == "S07":
            data["generations"] = {
                gen_id: {"arm": "base", "status": "passed", "scenarios": scenarios,
                         "statusCounts": {"passed": passed, "failed": scenarios - passed, "undefined": 0, "uncompilable": 0}}
                for gen_id, (passed, scenarios) in generations.items()}
        if stage_id == "S09":
            data["top10"] = DEFAULT_TOP10 if top10 is None else top10
        if stage_id == "S10":
            data["impact"] = dict(DEFAULT_IMPACT if impact is None else impact)
        stage_file.write_text(json.dumps(data))
    return run_dir


# --- 스냅숏 -------------------------------------------------------------------------------------

def _full_ci(partial: dict) -> dict:
    ci = {"runs": None, "successes": None, "failures": None, "successRate": None, "lastFailed": None,
          "failedChecks": None, "failedCheckNames": [], "history": []}
    ci.update(partial)
    return ci


def _full_sonar(partial: dict) -> dict:
    sonar = {"gate": "OK", "coverage": None, "bugs": None, "vulnerabilities": None, "codeSmells": None, "ncloc": None,
             "ratings": {"reliability": None, "security": None, "maintainability": None}}
    sonar.update(partial)
    return sonar


_UNSET = object()


def write_snapshot(base: Path, name: str, date: str, *, visibility: str = "public", description: str | None = "설명",
                   language: str | None = "Java", ci: dict | None = _UNSET, sonar: dict | None = _UNSET,
                   ci_state: str | None = None, sonar_state: str | None = None, problems: list | None = None) -> Path:
    """`<base>/projects/<name>/snapshots/<date>.json`을 쓴다. ci·sonar는 부분 dict를 받아 나머지 필드를 null로 채운다.

    기본값: CI 10/10 성공, Sonar 게이트 OK·커버리지 80.0. 상태(ci_state·sonar_state)를 주지 않으면 값이 있으면 ok,
    없으면 CI는 none, Sonar는 absent.
    """
    if ci is _UNSET:
        ci = {"runs": 10, "successes": 10, "failures": 0, "successRate": 1.0, "lastFailed": False,
              "failedChecks": 0, "history": [1] * 10}
    if sonar is _UNSET:
        sonar = {"gate": "OK", "coverage": 80.0}
    snapshot = {
        "schema": 1, "name": name, "repo": f"o/{name}", "visibility": visibility,
        "collectedAt": f"{date[:4]}-{date[4:6]}-{date[6:8]}T00:10:00Z", "date": date,
        "repoInfo": {"pushedAt": "2026-11-20T00:00:00Z", "language": language, "description": description,
                     "defaultBranch": "main"},
        "sources": {"ci": ci_state or ("ok" if ci is not None else "none"),
                    "sonar": sonar_state or ("ok" if sonar is not None else "absent")},
        "ci": None if ci is None else _full_ci(ci),
        "sonar": None if sonar is None else _full_sonar(sonar),
        "problems": list(problems or []),
    }
    path = Path(base) / "projects" / name / "snapshots" / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return path


def snap(**overrides) -> dict:
    """write_snapshot에 넘길 dict(`date` 포함, 기본 20261122).

    지름길 `ci_runs`, `ci_successes`: 나머지 CI 필드를 계산한다. 이력은 실패를 앞에, 성공을 뒤에 두어
    성공이 하나라도 있으면 `lastFailed`가 거짓이다.
    """
    data = {"date": "20261122", **overrides}
    if "ci_runs" in data or "ci_successes" in data:
        runs = data.pop("ci_runs", 10)
        successes = data.pop("ci_successes", runs)
        failures = runs - successes
        history = [0] * failures + [1] * successes
        data["ci"] = {"runs": runs, "successes": successes, "failures": failures,
                      "successRate": successes / runs if runs else None,
                      "lastFailed": (history[-1] == 0) if history else None, "failedChecks": 0, "history": history}
    return data


def write_collect_state(base: Path, date: str, unverified: Iterable[str]) -> Path:
    """`<base>/projects/_collect.json`(마지막 수집 상태)을 쓴다. unverified는 이번 수집에서 확인하지 못한 과제 이름."""
    path = Path(base) / "projects" / "_collect.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "date": date, "unverified": list(unverified)}))
    return path


# --- 설정과 사이트 ---------------------------------------------------------------------------------

def _names(value: str | Iterable[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def cfg_with(*, pipeline: str | Iterable[str] = (), plain: str | Iterable[str] = (), **sections) -> dict:
    """dashboard.yaml 내용. pipeline은 `sut`만 가진 과제, plain은 `repo: o/<name>`만 가진 과제."""
    projects = [{"name": name, "sut": name} for name in _names(pipeline)]
    projects += [{"name": name, "repo": f"o/{name}"} for name in _names(plain)]
    return {"schema": 1, "projects": projects, **sections}


def make_site(root: Path, *, runs: dict[str, list[dict]] | None = None, snapshots: dict[str, list[dict]] | None = None,
              config: dict | None = None) -> Path:
    """`<root>/site`(사이트), `<root>/dashboard.yaml`, 필요한 SUT마다 `<root>/suts/<sut>/sut.yaml`을 만든다."""
    root = Path(root)
    site = root / "site"
    site.mkdir(parents=True, exist_ok=True)
    runs = runs or {}
    snapshots = snapshots or {}
    config = config if config is not None else {"schema": 1, "projects": []}
    (root / "dashboard.yaml").write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    needed_suts = set(runs) | {project["sut"] for project in config.get("projects", []) if project.get("sut")}
    for sut in sorted(needed_suts):
        descriptor = root / "suts" / sut / "sut.yaml"
        descriptor.parent.mkdir(parents=True, exist_ok=True)
        descriptor.write_text(f"name: {sut}\n")
    for sut, run_list in runs.items():
        for run in run_list:
            overrides = {key: value for key, value in run.items() if key != "runId"}
            write_run(site, sut, run["runId"], **overrides)
    for name, snapshot_list in snapshots.items():
        for item in snapshot_list:
            overrides = {key: value for key, value in item.items() if key != "date"}
            write_snapshot(site, name, item["date"], **overrides)
    return site


def load_cfg(site: Path) -> Config:
    site = Path(site)
    return dashboard_config.load(site.parent / "dashboard.yaml", site.parent / "suts")


def rebuild_site(site: Path, cfg: Config | None = None) -> list[Path]:
    """사이트를 다시 만든다. cfg가 없으면 사이트 옆 dashboard.yaml을 쓴다."""
    return index.rebuild(site, "", cfg if cfg is not None else load_cfg(site))


def status_of(site: Path, name: str) -> str:
    """`projects.json`(Task 9가 쓴다)에서 과제의 상태 수준을 읽는다."""
    data = json.loads((Path(site) / "projects.json").read_text())
    for project in data["projects"]:
        if project["name"] == name:
            return project["status"]["level"]
    raise KeyError(name)


# --- 로컬 서버와 브라우저 ---------------------------------------------------------------------------

@contextlib.contextmanager
def serve(directory: Path) -> Iterator[str]:
    """`directory`를 로컬 http.server 자식 프로세스로 띄운다. URL은 `/`로 끝난다. 모든 종료 경로에서 PID를 정리한다."""
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "http.server", "0", "--bind", "127.0.0.1", "--directory", str(directory)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        line = process.stdout.readline()        # "Serving HTTP on 127.0.0.1 port 54321 (http://127.0.0.1:54321/) ..."
        if " port " not in line:
            raise RuntimeError(f"http.server가 시작되지 않았다: {line!r}")
        port = int(line.split(" port ")[1].split()[0])
        url = f"http://127.0.0.1:{port}/"
        urllib.request.urlopen(url, timeout=10).close()
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        if process.stdout:
            process.stdout.close()
        assert process.poll() is not None, f"http.server(pid {process.pid})가 남았다"


def open_page(browser, url: str, *, javascript: bool = True, scheme: str = "light", width: int = 1280):
    """새 컨텍스트에서 페이지를 연다. 컨텍스트는 `page.context.close()`로 닫거나 세션 끝에 브라우저와 함께 닫힌다."""
    context = browser.new_context(java_script_enabled=javascript, color_scheme=scheme,
                                  viewport={"width": width, "height": 900})
    page = context.new_page()
    page.goto(url)
    page.wait_for_load_state("load")
    return page
