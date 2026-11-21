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
import functools
import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pytest
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


# --- 첫 화면 고정 사이트(Task 9) ------------------------------------------------------------------------

HOME_PET_RUNS = [  # pet 과제의 run 2개. 게이트 OK, 취약점 0(양호가 되도록), 최신 run의 통과율 1.0·귀속 0.4152
    {"runId": RUN_B["runId"], "started": RUN_B["started"], "tests_pass": 0.95, "line": 0.4,
     "sonar": {**DEFAULT_SONAR, "vulnerabilities": "0"}},
    {"runId": RUN_C["runId"], "started": RUN_C["started"], "tests_pass": 1.0, "line": 0.4152,
     "sonar": {**DEFAULT_SONAR, "vulnerabilities": "0"}},
]


def home_site(tmp_path: Path) -> Path:
    """과제 6개(위험 2, 주의 1, 측정 없음 1, 양호 2)의 사이트를 만들고 재생성한다. 사이트 경로를 돌려준다.

    a-crit: CI 9/9, 게이트 ERROR, 취약점 2 / b-crit: CI 4회 중 3회 성공, 마지막 실행 실패, 게이트 OK /
    zero-cov: CI 17/17, 게이트 OK, 커버리지 0.0, 취약점 8 / no-data: CI 0회, Sonar 없음 /
    no-sonar: CI 10/10, Sonar 없음(부분 측정) / pet: repo 없이 sut만, run 2개(파이프라인).
    """
    b_crit_ci = {"runs": 4, "successes": 3, "failures": 1, "successRate": 0.75, "lastFailed": True,
                 "failedChecks": 0, "history": [1, 1, 1, 0]}
    site = make_site(tmp_path, runs={"pet": HOME_PET_RUNS}, snapshots={
        "a-crit": [snap(ci_runs=9, sonar={"gate": "ERROR", "coverage": 71.0, "bugs": 1, "vulnerabilities": 2})],
        "b-crit": [snap(ci=b_crit_ci, sonar={"gate": "OK", "coverage": 80.0, "bugs": 0, "vulnerabilities": 0})],
        "zero-cov": [snap(ci_runs=17, sonar={"gate": "OK", "coverage": 0.0, "bugs": 3, "vulnerabilities": 8})],
        "no-data": [snap(ci_runs=0, sonar=None)],
        "no-sonar": [snap(ci_runs=10, sonar=None)],
    }, config=cfg_with(pipeline="pet", plain=["a-crit", "b-crit", "zero-cov", "no-data", "no-sonar"]))
    rebuild_site(site)
    return site


def all_good_site(tmp_path: Path) -> Path:
    """위험·주의가 없는 과제 2개(둘 다 양호, Sonar 커버리지 0 없음)의 사이트를 만들고 재생성한다."""
    site = make_site(tmp_path / "all-good", snapshots={
        "g1": [snap(ci_runs=10, sonar={"gate": "OK", "coverage": 80.0, "bugs": 0, "vulnerabilities": 0})],
        "g2": [snap(ci_runs=6, sonar={"gate": "OK", "coverage": 55.5, "bugs": 1, "vulnerabilities": 0})],
    }, config=cfg_with(plain=["g1", "g2"]))
    rebuild_site(site)
    return site


SONAR_FAILED_REASON = "Sonar API가 HTTP 500으로 답했다"
CI_FAILED_REASON = "Actions 실행 목록을 읽지 못했다: HTTP 502"


def sonar_failed_site(tmp_path: Path) -> Path:
    """Sonar 수집이 실패한(`sources.sonar == "failed"`) 과제 `flaky`, CI가 없는(`none`) Sonar만 있는 과제 `no-ci`,
    CI 수집이 실패한(`sources.ci == "failed"`, `ci: null`) 과제 `ci-broken`."""
    site = make_site(tmp_path / "sonar-failed", snapshots={
        "flaky": [snap(ci_runs=10, sonar=None, sonar_state="failed",
                       problems=[{"source": "sonar", "reason": SONAR_FAILED_REASON}])],
        "no-ci": [snap(ci=None, sonar={"gate": "OK", "coverage": 64.0, "bugs": 0, "vulnerabilities": 0})],
        "ci-broken": [snap(ci=None, ci_state="failed", problems=[{"source": "ci", "reason": CI_FAILED_REASON}],
                           sonar={"gate": "OK", "coverage": 64.0, "bugs": 0, "vulnerabilities": 0})],
    }, config=cfg_with(plain=["flaky", "no-ci", "ci-broken"]))
    rebuild_site(site)
    return site


# --- 로컬 서버와 브라우저 ---------------------------------------------------------------------------

class _LocalHTTPServer(http.server.ThreadingHTTPServer):
    """127.0.0.1 전용 서버. 표준 `HTTPServer.server_bind`는 `socket.getfqdn`(역방향 DNS)을 불러 수십 초가 걸릴 수 있어
    이름 조회 없이 주소만 기록한다."""
    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - 표준 서명
        pass


@contextlib.contextmanager
def serve(directory: Path) -> Iterator[str]:
    """`directory`를 127.0.0.1의 로컬 HTTP 서버(같은 프로세스의 스레드)로 띄운다. URL은 `/`로 끝난다.
    모든 종료 경로에서 서버를 멈추고 소켓을 닫고 스레드가 끝났는지 확인한다."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = _LocalHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, name=f"serve:{directory}", daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        urllib.request.urlopen(url, timeout=10).close()
        yield url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        assert not thread.is_alive(), f"로컬 HTTP 서버 스레드({thread.name})가 남았다"


def open_page(browser, url: str, *, javascript: bool = True, scheme: str = "light", width: int = 1280):
    """새 컨텍스트에서 페이지를 연다. 컨텍스트는 `page.context.close()`로 닫거나 세션 끝에 브라우저와 함께 닫힌다."""
    context = browser.new_context(java_script_enabled=javascript, color_scheme=scheme,
                                  viewport={"width": width, "height": 900})
    page = context.new_page()
    page.goto(url)
    page.wait_for_load_state("load")
    return page


# --- 가짜 ssh(Sonar 토큰 DB) ------------------------------------------------------------------------

# `psql -tA -c '\d user_tokens'`가 실제 서버에서 내는 모양(열|형식|정렬|널 허용|기본값).
_USER_TOKENS_SCHEMA = "\n".join([
    "uuid|character varying(40)||not null|",
    "user_uuid|character varying(255)||not null|",
    "name|character varying(100)||not null|",
    "token_hash|character varying(255)||not null|",
    "last_connection_date|bigint|||",
    "created_at|bigint||not null|",
    "project_uuid|character varying(40)|||",
    "type|character varying(100)||not null|",
    "expiration_date|bigint|||",
])

# 가짜 ssh 본체. 원격 명령에 psql이 있으면 user_tokens를 상태 파일로 흉내 내고, 없으면 PATH에서 실제 ssh를 찾아 exec한다.
_FAKE_SSH_SCRIPT = r'''
import json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE.parent
CONFIG = json.loads((STATE / "config.json").read_text())


def real_ssh():
    own_dir = os.path.realpath(HERE)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or os.path.realpath(entry) == own_dir:
            continue
        candidate = os.path.join(entry, "ssh")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            os.execv(candidate, [candidate] + sys.argv[1:])
    print("fake ssh: 실제 ssh를 PATH에서 찾지 못했다", file=sys.stderr)
    sys.exit(127)


remote = sys.argv[-1] if len(sys.argv) > 1 else ""
if "psql" not in remote:
    real_ssh()
match = re.search(r'-c "(.*)"\s*$', remote, re.S)
if not match:
    print("fake ssh: SQL을 찾지 못했다", file=sys.stderr)
    sys.exit(2)
sql = match.group(1)
with open(STATE / "sql.log", "a") as log:
    log.write(sql + "\n")
rows_file = STATE / "rows.json"
rows = json.loads(rows_file.read_text())


def save():
    rows_file.write_text(json.dumps(rows))


if sql.strip() == r"\d user_tokens":
    print(CONFIG["schema"])
elif sql.strip() == "select 1":
    print(1)
elif sql.startswith("with gone as (delete from user_tokens where name like 'td-%'"):
    kept = [row for row in rows if not (row["name"].startswith("td-") and row["expired"])]
    print(len(rows) - len(kept))
    rows[:] = kept
    save()
elif sql.startswith("insert into user_tokens"):
    name = re.search(r"select '[^']*', u\.uuid, '([^']*)'", sql).group(1)
    rows.append({"name": name, "expired": False})
    save()
    if CONFIG["lose_insert_reply"]:
        print("Connection reset by peer", file=sys.stderr)
        sys.exit(255)
    print("INSERT 0 1")
elif (found := re.fullmatch(r"select count\(\*\) from user_tokens where name='([^']*)'", sql.strip())):
    print(sum(1 for row in rows if row["name"] == found.group(1)))
elif (found := re.fullmatch(r"delete from user_tokens where name='([^']*)'", sql.strip())):
    if CONFIG.get("delete_delay"):
        import time
        time.sleep(CONFIG["delete_delay"])   # 이 사이에 신호를 받으면 행을 지우지 않고 끝난다
    if CONFIG["fail_delete"]:
        print("Connection closed by remote host", file=sys.stderr)
        sys.exit(255)
    kept = [row for row in rows if row["name"] != found.group(1)]
    print(f"DELETE {len(rows) - len(kept)}")
    rows[:] = kept
    save()
else:
    print(f"fake ssh: 모르는 SQL: {sql[:200]}", file=sys.stderr)
    sys.exit(1)
'''


class FakeSsh:
    """상태를 가진 가짜 ssh. `bin_dir`을 PATH 앞에 둔다."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.bin_dir = state_dir / "bin"

    def _rows(self) -> list[dict]:
        return json.loads((self.state_dir / "rows.json").read_text())

    def rows(self) -> list[str]:
        """남아 있는 토큰 행의 이름(삽입 순서)."""
        return [row["name"] for row in self._rows()]

    def log(self) -> str:
        """받은 SQL 전부(한 줄에 하나)."""
        log_file = self.state_dir / "sql.log"
        return log_file.read_text() if log_file.exists() else ""

    def seed(self, name: str, *, expired: bool = False) -> None:
        """토큰 행 하나를 미리 넣는다(`expired`면 사전 청소 대상)."""
        current = self._rows()
        current.append({"name": name, "expired": expired})
        (self.state_dir / "rows.json").write_text(json.dumps(current))


def fake_ssh(tmp_path: Path, *, fail_delete: bool = False, lose_insert_reply: bool = False,
             delete_delay: float = 0) -> FakeSsh:
    """`fail_delete`: DELETE가 SSH 오류(255)로 실패한다. `lose_insert_reply`: INSERT는 적용되지만 응답이 유실된다(255).
    `delete_delay`: DELETE를 받은 뒤(sql.log에 남긴 뒤) 지우기 전에 기다리는 초."""
    state_dir = tmp_path / "fake-ssh"
    bin_dir = state_dir / "bin"
    bin_dir.mkdir(parents=True)
    (state_dir / "config.json").write_text(json.dumps(
        {"fail_delete": fail_delete, "lose_insert_reply": lose_insert_reply, "delete_delay": delete_delay,
         "schema": _USER_TOKENS_SCHEMA}))
    (state_dir / "rows.json").write_text("[]")
    script = bin_dir / "ssh"
    script.write_text(f"#!{sys.executable}\n{_FAKE_SSH_SCRIPT}")
    script.chmod(0o755)
    return FakeSsh(state_dir)


def token_env(tmp_path: Path, ssh: FakeSsh, sonar_url: str) -> dict:
    """가짜 ssh와 가짜 Sonar로 토큰 함수를 돌리는 환경 변수(테스트 접두사가 있어야 URL 덮어쓰기가 먹는다)."""
    return {
        "TD_SITE_PREFIX": f"_test/token-{tmp_path.name}/",
        "TD_SONAR_URL_OVERRIDE": sonar_url,
        "TD_LIGHTSAIL_IP": "203.0.113.1",
        "TD_SSH_KEY_PATH": "/nonexistent",
        "PATH": f"{ssh.bin_dir}{os.pathsep}{os.environ['PATH']}",
    }


# --- 가짜 gh(GitHub API) ---------------------------------------------------------------------------

# 가짜 gh 본체. `gh api -i <path>`에 실제 gh처럼 답한다: 상태 줄, 헤더, 빈 줄, JSON 본문(끝 줄바꿈 없음).
# HTTP 오류면 본문까지 표준 출력에 내고 `gh: <메시지> (HTTP <코드>)`를 표준 오류에 낸 뒤 종료 코드 1.
_FAKE_GH_SCRIPT = r'''
import json, os, sys, time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
STATE = HERE.parent
REASONS = {200: "OK", 403: "Forbidden", 404: "Not Found", 429: "Too Many Requests",
           500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable"}
args = sys.argv[1:]
with open(STATE / "calls.jsonl", "a") as log:
    log.write(json.dumps({"args": args, "at": time.time(), "pid": os.getpid()}) + "\n")


def respond(status, body, headers=()):
    lines = [f"HTTP/2.0 {status} {REASONS.get(status, 'Error')}", "Content-Type: application/json; charset=utf-8",
             "X-Github-Media-Type: github.v3; format=json"] + [f"{key}: {value}" for key, value in headers]
    sys.stdout.write("\n".join(lines) + "\n\n" + json.dumps(body))
    sys.stdout.flush()
    if status >= 400:
        print(f"gh: {body.get('message', 'error')} (HTTP {status})", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if len(args) != 3 or args[:2] != ["api", "-i"]:
    print(f"fake gh: 모르는 인자 {args}", file=sys.stderr)
    sys.exit(2)
parts = urlsplit(args[2])
query = parse_qs(parts.query)
segments = parts.path.strip("/").split("/")
not_found = {"message": "Not Found", "documentation_url": "https://docs.github.com/rest", "status": "404"}
if segments[0] != "repos" or len(segments) < 3:
    respond(404, not_found)
repo, rest = "/".join(segments[1:3]), segments[3:]
if not rest:
    kind = "repo"
elif rest[:2] == ["actions", "runs"]:
    kind = "runs"
elif len(rest) == 3 and rest[0] == "commits" and rest[2] == "check-runs":
    kind = "checks"
else:
    kind = "other"
spec = json.loads((STATE / "repos.json").read_text()).get(repo)
if spec is None or spec.get("missing"):
    respond(404, not_found)
if spec.get("hang") and spec.get("hang_on") in (None, kind):
    time.sleep(spec["hang"])
fail = spec.get("fail")
if fail and fail.get("on") in (None, kind):
    counters_file = STATE / "counters.json"
    counters = json.loads(counters_file.read_text())
    counter_key = f"{repo}:{fail.get('on') or '*'}"
    used = counters.get(counter_key, 0)
    if used < fail.get("times", 1):
        counters[counter_key] = used + 1
        counters_file.write_text(json.dumps(counters))
        headers = [("Retry-After", str(fail["retry_after"]))] if fail.get("retry_after") is not None else []
        respond(fail["status"], {"message": "injected failure", "status": str(fail["status"])}, headers)
if kind == "repo":
    visibility = spec.get("visibility", "public")
    respond(200, {"name": segments[2], "full_name": repo, "private": visibility != "public", "visibility": visibility,
                  "description": spec.get("description", "fake repo"), "language": spec.get("language", "Java"),
                  "default_branch": spec.get("default_branch", "main"),
                  "pushed_at": spec.get("pushed_at", "2026-11-20T05:05:15Z")})
if kind == "runs":
    branch = query.get("branch", [""])[0]
    runs = [{"id": 1000 + index, "name": "ci", "head_branch": branch, "event": "push", "status": "completed",
             "conclusion": conclusion} for index, conclusion in enumerate(spec.get("runs", ["success"]))]
    respond(200, {"total_count": len(runs), "workflow_runs": runs})
if kind == "checks":
    checks = [{"id": 2000 + index, "name": item["name"], "status": item.get("status", "completed"),
               "conclusion": item.get("conclusion"), "started_at": item.get("started_at", "2026-11-20T00:00:00Z")}
              for index, item in enumerate(spec.get("checks", []))]
    respond(200, {"total_count": len(checks), "check_runs": checks})
respond(404, not_found)
'''


class GhCall(list):
    """가짜 gh가 받은 인자 목록(`["api", "-i", path]`). `.at`은 받은 시각(epoch 초), `.pid`는 그 프로세스."""

    def __init__(self, args: list[str], at: float, pid: int):
        super().__init__(args)
        self.at = at
        self.pid = pid


class FakeGh:
    """상태를 가진 가짜 gh. `.path`를 `TD_GH_BIN`으로 준다."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.path = state_dir / "bin" / "gh"

    @property
    def calls(self) -> list[GhCall]:
        log_file = self.state_dir / "calls.jsonl"
        if not log_file.exists():
            return []
        return [GhCall(item["args"], item["at"], item["pid"])
                for item in (json.loads(line) for line in log_file.read_text().splitlines() if line.strip())]

    def set(self, repo: str, **fields) -> None:
        """저장소 하나의 응답 필드를 바꾼다(없으면 만든다)."""
        repos_file = self.state_dir / "repos.json"
        repos = json.loads(repos_file.read_text())
        repos.setdefault(repo, {}).update(fields)
        repos_file.write_text(json.dumps(repos))

    def alive_pids(self) -> list[int]:
        """받은 호출의 프로세스 가운데 아직 살아 있는 것."""
        alive = []
        for call in self.calls:
            try:
                os.kill(call.pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
            alive.append(call.pid)
        return alive


def fake_gh(tmp_path: Path, repos: dict[str, dict]) -> FakeGh:
    """저장소(`owner/name`)마다 응답을 정한 가짜 gh.

    필드: `visibility`("public"|"private"|"internal", 기본 public), `missing`(404), `runs`(최신순 결론값, 기본
    ["success"]), `checks`(`[{name, conclusion, started_at, status}]`), `fail`(`{"status", "retry_after", "times", "on"}`:
    처음 times번을 그 상태로 실패, `on`은 "repo"|"runs"|"checks"로 한정), `hang`(초, `hang_on`으로 한정),
    `description`, `language`, `default_branch`, `pushed_at`. 설정에 없는 저장소는 404다.
    """
    state_dir = tmp_path / "fake-gh"
    bin_dir = state_dir / "bin"
    bin_dir.mkdir(parents=True)
    (state_dir / "repos.json").write_text(json.dumps(repos))
    (state_dir / "counters.json").write_text("{}")
    script = bin_dir / "gh"
    script.write_text(f"#!{sys.executable}\n{_FAKE_GH_SCRIPT}")
    script.chmod(0o755)
    return FakeGh(state_dir)


# --- 표본 리포트를 가진 로컬 run과 렌더된 사이트(Task 7) ---------------------------------------------------

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPORT_FIXTURES = FIXTURES / "reports"
REPORTS_RUN_ID = "20261120-131022Z-b6f9393-manual-0000007a"
REPORTS_SUT = "pet"
RUN_PATH = f"suts/{REPORTS_SUT}/runs/{REPORTS_RUN_ID}/"     # render_site가 만든 run의 사이트 상대 경로
# 단계별 걸린 시간(초). S07은 259초(4분 19초), 나머지는 작은 값.
REPORT_STAGE_SECONDS = {"S00": 20, "S01": 18, "S02": 4, "S03": 20, "S04": 1, "S05": 0, "S06": 1, "S07": 259,
                        "S08": 30, "S09": 2, "S10": 12, "S11": 40, "S12": 3, "S13": 25}
MINIMAL_CUCUMBER_HTML = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Cucumber 리포트</title></head>'
                         '<body><main><h1>Cucumber 리포트</h1><p>시나리오 31개</p></main></body></html>')


def _report_dir(run_dir: Path, rel: str, files: dict[str, str | Path]) -> Path:
    """run 디렉터리 아래 `rel`에 파일을 둔다. 값이 Path면 그 파일을 복사, 문자열이면 그 내용을 쓴다."""
    target = run_dir / rel
    target.mkdir(parents=True, exist_ok=True)
    for name, source in files.items():
        if isinstance(source, Path):
            (target / name).write_bytes(source.read_bytes())
        else:
            (target / name).write_text(source)
    return target


def _own_sonar(run_dir: Path) -> Path:
    """가짜 Sonar API로 sonar.export를 돌려 실제 sonar.render로 sonar.json·sonar.html을 만든다."""
    from fake_sonar import KEY, start_fake_sonar
    from td import sonar
    fake, stop = start_fake_sonar()
    try:
        fake.issue_total, fake.hotspot_total = 3, 1
        doc = sonar.export(KEY, client=sonar.SonarClient(fake.url, token="squ_fixture_token_value"), ce_task_id="AZ-task-7")
    finally:
        stop()
    target = run_dir / "S11" / "sonar"
    target.mkdir(parents=True, exist_ok=True)
    (target / "sonar.json").write_text(json.dumps(doc, ensure_ascii=False))
    sonar.render(doc, target, copy_css=False)
    return target


def _own_compare(run_dir: Path, scratch: Path) -> Path:
    """helpers의 합성 방식 비교 run으로 compare.collect를 돌려 실제 compare.render_page로 compare.json·compare.html을 만든다."""
    from td import compare
    from helpers import collect, make_compare_run
    scratch.mkdir(parents=True, exist_ok=True)
    document = collect(make_compare_run(scratch))
    target = run_dir / "S12" / "compare"
    target.mkdir(parents=True, exist_ok=True)
    (target / "compare.json").write_text(json.dumps(document, ensure_ascii=False))
    compare.render_page(target, document, copy_css=False)
    return target


def _own_ontology(run_dir: Path) -> Path:
    """표본 온톨로지 JSON으로 실제 ontology_html.render를 돌려 jqa.html·owl.html을 만든다."""
    from td import ontology_html
    target = run_dir / "S04" / "ontology"
    source = FIXTURES / "owl" / "ontology-jqa.json"
    ontology_html.render(source, target / "jqa.html", "jqa")
    ontology_html.render(source, target / "owl.html", "owl")
    return target


def make_local_run_with_reports(tmp_path: Path, *, sut: str = REPORTS_SUT, tia_html: str | None = None,
                                hotspot_html: str | None = None, with_own_reports: bool = True,
                                gens: tuple[str, ...] = ("base-r1",)) -> Path:
    """게시 전 로컬 run(`helpers.make_local_run`)에 표본 리포트를 더한다.

    hotspot(`hotspots.html`·`api_report.html`)과 TIA(`tia.html`)는 tests/fixtures/reports/의 표본(tia_html·hotspot_html을
    주면 그 내용), 생성 묶음마다 최소 Cucumber `index.html`, with_own_reports면 실제 렌더 함수로 만든 Sonar·방식 비교·온톨로지.
    14단계 단계 JSON에 시작·종료 시각을 넣는다(REPORT_STAGE_SECONDS, S07은 259초). S13은 시작한 상태다.
    """
    from helpers import make_local_run
    from td import state
    tmp_path = Path(tmp_path)
    run_dir = make_local_run(tmp_path / "runs", sut, REPORTS_RUN_ID)
    hotspot_dir = _report_dir(run_dir, "S09/hotspot", {
        "hotspots.html": hotspot_html if hotspot_html is not None else REPORT_FIXTURES / "hotspots.html",
        "api_report.html": REPORT_FIXTURES / "api_report.html"})
    tia_dir = _report_dir(run_dir, "S10/tia", {
        "tia.html": tia_html if tia_html is not None else REPORT_FIXTURES / "tia.html"})
    gen_outputs = {f"html:{gen}": str(_report_dir(run_dir, f"S07/{gen}/html", {"index.html": MINIMAL_CUCUMBER_HTML}))
                   for gen in gens}
    generations = {gen: {"arm": gen.split("-")[0], "status": "passed", "scenarios": 31,
                         "statusCounts": {"passed": 21, "failed": 10, "undefined": 0, "uncompilable": 0}} for gen in gens}
    outputs: dict[str, dict] = {"S07": gen_outputs, "S09": {"hotspot": str(hotspot_dir)}, "S10": {"tia": str(tia_dir)}}
    if with_own_reports:
        outputs["S04"] = {"ontology": str(_own_ontology(run_dir))}
        outputs["S11"] = {"sonar": str(_own_sonar(run_dir))}
        outputs["S12"] = {"compare": str(_own_compare(run_dir, tmp_path / "compare-src"))}
    for stage_id in ("S02", "S03", "S04", "S05", "S06", "S07", "S09", "S10", "S11", "S12"):
        extra = {"generations": generations} if stage_id == "S07" else None
        state.end(run_dir, stage_id, "passed", outputs=outputs.get(stage_id), extra=extra)
    state.begin(run_dir, "S13")
    moment = _parse_iso(_started_from_run_id(REPORTS_RUN_ID))
    for stage_id, seconds in REPORT_STAGE_SECONDS.items():
        stage_file = run_dir / "stages" / f"{stage_id}.json"
        data = json.loads(stage_file.read_text())
        data.update(startedAt=_iso(moment), finishedAt=_iso(moment + timedelta(seconds=seconds)))
        stage_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        moment += timedelta(seconds=seconds)
    return run_dir


def render_site(tmp_path: Path, run_dir: Path, *, config: dict | None = None) -> Path:
    """run을 사이트 디렉터리의 `suts/<sut>/runs/<runId>/`로 렌더하고(완료 표시 `_COMPLETE`) 재생성한다. 사이트 경로를 돌려준다."""
    from td.site import pages
    run = json.loads((Path(run_dir) / "run.json").read_text())
    site = make_site(Path(tmp_path) / "site-root", config=config)
    descriptor = site.parent / "suts" / run["sut"] / "sut.yaml"
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(f"name: {run['sut']}\n")
    target = site / "suts" / run["sut"] / "runs" / run["runId"]
    pages.render_run(run_dir, target)
    (target / "_COMPLETE").write_text("{}")
    rebuild_site(site)
    return site


# --- 과제 페이지 고정 사이트(Task 10) ----------------------------------------------------------------------

# pet의 앞선 run 4개(runId 순). 3번째 run(전체 5개 중 3번째)은 테스트 통과율이 없다.
PROJ_PET_OLDER = [
    {"runId": "20261116-101500Z-ppppppp-manual-00000011", "tests_pass": 0.9, "line": 0.38, "agg_line": 0.55},
    {"runId": "20261117-101500Z-ppppppp-manual-00000012", "tests_pass": 0.95, "line": 0.39, "agg_line": 0.56},
    {"runId": "20261118-101500Z-ppppppp-manual-00000013", "tests_pass": None, "line": 0.4, "agg_line": 0.58},
    {"runId": "20261119-101500Z-ppppppp-manual-00000014", "tests_pass": 0.97, "line": 0.41, "agg_line": 0.6},
]
PROJ_PET_GENS = ("base-r1", "jqa-r1")
# 최신 pet run의 kpis: 통과율 1, 귀속 라인 0.415 -> 결론 문장 "… 41.5%입니다"(게이트 OK·취약점 0이라 양호)
PROJ_PET_KPIS = {
    "tests": {"suite": "blackbox", "passed": 35, "total": 35, "passRate": 1.0},
    "blackbox": {"line": 0.415, "branch": 0.308, "aggregate": {"line": 0.609, "branch": 0.34}},
    "e2e-base-r1": {"line": 0.198, "branch": 0.122, "aggregate": {"line": 0.433, "branch": 0.162}},
    "e2e-jqa-r1": {"line": 0.16, "branch": 0.087, "aggregate": {"line": 0.392, "branch": 0.123}},
    "sonar": {"gate": "OK", "coverage": "41.7", "bugs": "2", "vulnerabilities": "0", "codeSmells": "37",
              "issues": 3, "hotspots": 1},
}
# coverage.json의 묶음별 TC 수와 귀속 수
PROJ_PET_COVERAGE_COUNTS = {"blackbox": (35, 27), "e2e-base-r1": (31, 31), "e2e-jqa-r1": (31, 30)}
PROJ_PET_TOP10 = [{"name": f"Klass{rank}.method{rank}", "file": f"src/main/java/app/Klass{rank}.java",
                   "method": f"method{rank}", "score": round(30.0 - rank * 2.5, 4)} for rank in range(1, 11)]
PROJ_PET_IMPACT = {"selected": 68, "indexedTests": 134, "deterministic": 0, "conservative": 68,
                   "allSelectedConservative": True}
PROJ_MANY_RUNS = [{"runId": f"202610{day:02d}-090000Z-mmmmmmm-manual-{day:08d}", "tests_pass": 1.0,
                   "line": round(0.3 + day * 0.005, 4), "agg_line": round(0.5 + day * 0.004, 4)} for day in range(1, 32)]
PROJ_PLAIN_SNAPSHOTS = [
    snap(date="20261121", ci_runs=20, ci_successes=17, sonar={"gate": "OK", "coverage": 90.2, "bugs": 0, "vulnerabilities": 1}),
    snap(date="20261122", ci_runs=20, ci_successes=18, sonar={"gate": "OK", "coverage": 91.6, "bugs": 0, "vulnerabilities": 0}),
]
PLACEHOLDER_RUN_PAGE = '<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>run 페이지</title></head><body></body></html>'


def _edit_json(path: Path, change) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _prepare_pet_run(run_dir: Path) -> None:
    """make_local_run_with_reports가 만든 로컬 run을 과제 페이지 고정 값으로 맞춘다(렌더 전에 부른다)."""
    _edit_json(run_dir / "run.json", lambda run: run.update(kpis=json.loads(json.dumps(PROJ_PET_KPIS))))

    def gate_ok(doc):  # 게이트를 통과로(run.json kpis.sonar와 같은 출처 값이 되게)
        doc["qualityGate"] = {"status": "OK", "conditions": [
            {"status": "OK", "metricKey": "new_violations", "comparator": "GT", "errorThreshold": "0", "actualValue": "0"}]}
    _edit_json(run_dir / "S11" / "sonar" / "sonar.json", gate_ok)
    suites = {name: {"kpis": {key: value for key, value in PROJ_PET_KPIS[name].items()},
                     "tcCount": tc_count, "attributedCount": attributed, "tcs": [], "paths": {}}
              for name, (tc_count, attributed) in PROJ_PET_COVERAGE_COUNTS.items()}
    _edit_json(run_dir / "S08" / "coverage.json", lambda doc: doc.update(suites=suites))
    _edit_json(run_dir / "stages" / "S09.json", lambda stage: stage.update(top10=PROJ_PET_TOP10))
    _edit_json(run_dir / "stages" / "S10.json", lambda stage: stage.update(impact=dict(PROJ_PET_IMPACT), range="HEAD~10..HEAD"))


def proj_site(tmp_path: Path, *, extra_plain: dict[str, list[dict]] | None = None, **sections) -> Path:
    """과제 페이지 고정 사이트를 만들고 재생성한다. 사이트 경로를 돌려준다.

    pet: `repo` 없이 `sut: pet`. run 5개이고 3번째 run은 `tests.passRate`가 없다. 최신 run은
         make_local_run_with_reports로 만들어 render_site로 렌더한 것이라 run 페이지와 리포트가 실제로 있다(양호).
    plain: 스냅숏 2일치(최신: CI 18/20, 게이트 OK, 커버리지 91.6, 취약점 0, 버그 0. 양호).
    many: `sut: many`, run 31개(최신 run의 Sonar 취약점 18 -> 주의).
    `extra_plain`은 `repo`만 가진 과제를 더하고(이름 -> 스냅숏 목록), `sections`는 설정의 status·home·project를 덮는다.
    write_run으로 만든 run에는 run 페이지 자리에 최소 index.html을 둔다(게시된 run에는 항상 run 페이지가 있다).
    """
    tmp_path = Path(tmp_path)
    extra_plain = extra_plain or {}
    config = cfg_with(pipeline=["pet", "many"], plain=["plain", *extra_plain], **sections)
    run_dir = make_local_run_with_reports(tmp_path / "local", gens=PROJ_PET_GENS)
    _prepare_pet_run(run_dir)
    site = render_site(tmp_path, run_dir, config=config)
    for sut, run_list in (("pet", PROJ_PET_OLDER), ("many", PROJ_MANY_RUNS)):
        for run in run_list:
            overrides = {key: value for key, value in run.items() if key != "runId"}
            written = write_run(site, sut, run["runId"], sonar={**DEFAULT_SONAR, "vulnerabilities": "0"} if sut == "pet"
                                else DEFAULT_SONAR, **overrides)
            (written / "index.html").write_text(PLACEHOLDER_RUN_PAGE)
    for name, snapshot_list in {"plain": PROJ_PLAIN_SNAPSHOTS, **extra_plain}.items():
        for item in snapshot_list:
            write_snapshot(site, name, item["date"], **{key: value for key, value in item.items() if key != "date"})
    rebuild_site(site)
    return site


def set_threshold(cfg: Config, metric: str, value) -> Config:
    """상태 규칙에서 `metric`을 비교하는 조건의 값을 모두 `value`로 바꾼 설정."""
    import copy
    import dataclasses
    status = copy.deepcopy(cfg.status)

    def visit(condition: dict) -> None:
        if "all" in condition:
            for child in condition["all"]:
                visit(child)
        elif condition["metric"] == metric:
            condition["value"] = value
    for rule in status["rules"]:
        visit(rule["when"])
    return dataclasses.replace(cfg, status=status)


@pytest.fixture(scope="session")
def proj_dir(tmp_path_factory) -> Path:
    """과제 페이지 고정 사이트(proj_site)의 디렉터리. 테스트 모듈이 가져다 쓴다."""
    return proj_site(tmp_path_factory.mktemp("proj"))


@pytest.fixture(scope="session")
def proj(proj_dir) -> Iterator[str]:
    """proj_dir을 띄운 로컬 서버의 URL(`/`로 끝난다)."""
    with serve(proj_dir) as url:
        yield url


def run_fake_publication(run_dir: Path) -> dict:
    """test_unit_publish.py의 exec_env와 같은 방식(helpers.FakeS3, 가짜 ssh·rsync, 정상 CloudFront)으로 Publication.execute를 돌린다."""
    import signal
    from helpers import FakeS3
    from td import publish

    class _OkCloudFront:
        def create_invalidation(self, DistributionId, InvalidationBatch):
            return {"Invalidation": {"Id": "I1"}}

    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text())
    scratch = run_dir.parent / f"_publish-{run['runId']}"
    work = scratch / "work"
    (work / "infra").mkdir(parents=True)
    (work / "infra" / "terraform.tfstate").write_text(json.dumps(
        {"outputs": {"bucket": {"value": "td-reports-test"}, "distribution_id": {"value": "DIST"}}}))
    bin_dir = scratch / "bin"
    bin_dir.mkdir()
    for name, body in (("ssh", "echo 99999999999"), ("rsync", "exit 0")):
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    saved_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    saved_path = os.environ["PATH"]
    os.environ["PATH"] = f"{bin_dir}:{saved_path}"
    env = {"TD_WORK_DIR": str(work), "TD_ROOT": str(scratch), "TD_SITE_PREFIX": "_test/u/",
           "TD_LIGHTSAIL_IP": "203.0.113.9", "TD_SSH_KEY_PATH": "/key", "PATH": os.environ["PATH"]}
    try:
        return publish.Publication(run["sut"], run["runId"], run_dir, env, FakeS3(), _OkCloudFront(),
                                   measure_hosting=False).execute()
    finally:
        os.environ["PATH"] = saved_path
        for sig, handler in saved_signals.items():
            signal.signal(sig, handler)


# --- 작은 검사 보조 ---------------------------------------------------------------------------------------

def sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot_bytes(run_dir: Path, stage_dirs: Iterable[str]) -> dict[str, bytes]:
    """run 디렉터리 아래 단계 디렉터리(`S09` 등)의 모든 파일 바이트(run 상대 경로 -> 바이트)."""
    run_dir = Path(run_dir)
    return {path.relative_to(run_dir).as_posix(): path.read_bytes()
            for stage in stage_dirs for path in sorted((run_dir / stage).rglob("*")) if path.is_file()}


def http_status(url: str) -> int:
    import urllib.error
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def computed(page, selector: str, prop: str) -> str:
    """첫 `selector` 요소의 계산된 CSS 값."""
    return page.eval_on_selector(selector, "(element, name) => getComputedStyle(element).getPropertyValue(name)", prop)
