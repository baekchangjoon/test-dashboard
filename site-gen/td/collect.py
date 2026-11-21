"""과제 수집기: GitHub CI와 SonarQube 스냅숏(설계 §6.3).

순서:
  1. 저장소(`repo`)가 있는 모든 과제의 `repos/<repo>`를 읽어 공개 여부를 확정한다. `public`이 아니거나 404면 제외,
     그 밖의 실패(시간 초과, 5xx, 예산 초과)는 미확인이다. 제외·미확인 과제는 쓰지 않는다.
  2. 공개 과제마다 기본 브랜치의 완료된 Actions 실행(최근 30개)과 최신 커밋의 Check Runs를 읽는다.
  3. Sonar 대상 과제마다 `td.sonar`의 클라이언트로 게이트·측정값을 읽는다.
  4. 공개로 확정된 과제의 `projects/<name>/snapshots/<YYYYMMDD>.json`과 `latest.json`, 사이트 수준
     `projects/_collect.json`(미확인 과제 이름)을 임시 파일 뒤 `os.replace`로 쓴다.

모든 GitHub 호출은 `[gh, "api", "-i", path]`(셸 없음)이고 상태 줄·헤더·본문을 함께 읽는다. 수집 전체는 한 번 정한
마감 시각(예산) 안에서만 돈다. Sonar 토큰은 환경 변수 `SONAR_TOKEN`으로만 받는다. 게시되는 파일과 표준 출력에는
제외된 과제의 이름을 쓰지 않는다(이름은 표준 오류에만 낸다).

CLI:
  python -m td.collect run --config <파일> --site <사이트 디렉터리> --suts-dir <dir>   결과 JSON 한 줄
  python -m td.collect needs-sonar --config … --site … --suts-dir …                    Sonar를 읽을 과제 수
  python -m td.collect amend --status degraded --reason <문장>                         표준 입력의 결과에 상태·사유를 더한다
종료 코드: 설정 오류 2, 그 밖 0(신호로 끊기면 128 + 신호 번호).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import yaml

from td import dashboard_config, redact, state
from td import sonar as sonar_api
from td.dashboard_config import Config, ConfigError, Project
from td.site.metrics import COLLECT_STATE_FILE, load_snapshots

CONNECT_TIMEOUT_SEC = 10
READ_TIMEOUT_SEC = 30
RETRIES = 2
RETRY_DELAYS_SEC = (2, 4)
BUDGET_SEC = 300

RUNS_PER_PAGE = 30
CHECKS_PER_PAGE = 100
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
SUCCESS_CONCLUSIONS = frozenset({"success"})
FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
RATING_LETTERS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}
SONAR_MEASURES = ("coverage", "bugs", "vulnerabilities", "code_smells", "ncloc",
                  "reliability_rating", "security_rating", "sqale_rating")
REASON_EXCLUDED = "비공개 과제 {count}개 제외"
REASON_FAILED = "수집 실패 {count}개 과제"
REASON_BUDGET = "수집 예산 초과"
REASON_NO_TOKEN = "Sonar 토큰 없음"


class FetchError(Exception):
    """한 요청을 끝내 읽지 못했다(재시도 포함). 메시지는 게시해도 되는 사유다(토큰·이름 없음)."""


class Interrupted(BaseException):
    """SIGINT/SIGTERM을 받았다. 진행 중인 gh 자식은 호출 쪽 finally가 죽인다."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


# --- 예산과 재시도 ------------------------------------------------------------------------------

@dataclass
class Budget:
    """수집 전체의 마감 시각. 한 번 정하고 모든 요청·대기가 이 안에서만 돈다."""
    seconds: float
    clock: Callable[[], float] = time.monotonic
    deadline: float = 0.0
    exceeded: bool = False

    def __post_init__(self):
        self.deadline = self.clock() + self.seconds

    def remaining(self) -> float:
        return self.deadline - self.clock()


@dataclass
class _Attempt:
    """요청 한 번의 결과. kind: ok | retry | fail | timeout."""
    kind: str
    value: object = None
    reason: str = ""
    retry_after: float | None = None


def _with_retries(budget: Budget, delays: tuple[float, ...], attempt_fn: Callable[[float], _Attempt]) -> object:
    """attempt_fn(timeout)을 최대 1 + RETRIES번 부른다. 대기(재시도 간격, Retry-After)는 남은 예산 안에서만 한다."""
    attempts = 0
    while True:
        remaining = budget.remaining()
        if remaining <= 0:
            budget.exceeded = True
            raise FetchError(REASON_BUDGET)
        timeout = min(READ_TIMEOUT_SEC, remaining)
        attempts += 1
        result = attempt_fn(timeout)
        if result.kind == "ok":
            return result.value
        if result.kind == "fail":
            raise FetchError(result.reason)
        if result.kind == "timeout" and timeout < READ_TIMEOUT_SEC:
            budget.exceeded = True      # 남은 예산으로 줄인 시간 제한이 다 됐다
            raise FetchError(f"{result.reason}; {REASON_BUDGET}")
        if attempts > RETRIES:
            raise FetchError(f"{result.reason} ({attempts}회 시도)")
        wait = result.retry_after if result.retry_after is not None else delays[min(attempts - 1, len(delays) - 1)]
        if wait >= budget.remaining():
            if result.retry_after is not None:
                raise FetchError(f"{result.reason}; Retry-After {result.retry_after:g}초가 남은 예산보다 길다")
            budget.exceeded = True
            raise FetchError(f"{result.reason}; 다시 시도할 예산이 없다")
        time.sleep(wait)


# --- gh ---------------------------------------------------------------------------------------

def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    process.wait()


def parse_gh_output(raw: bytes) -> tuple[int, dict[str, str], object] | None:
    """`gh api -i`의 출력(상태 줄, 헤더, 빈 줄, 본문)을 (상태 코드, 헤더(소문자 키), JSON 본문)으로. 모양이 틀리면 None."""
    text = raw.decode("utf-8", "replace")
    match = re.search(r"\r?\n\r?\n", text)
    head, body = (text[:match.start()], text[match.end():]) if match else (text, "")
    lines = head.splitlines()
    status_match = re.match(r"HTTP/\S+\s+(\d{3})\b", lines[0]) if lines else None
    if not status_match:
        return None
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    try:
        payload = json.loads(body) if body.strip() else None
    except ValueError:
        payload = None
    return int(status_match.group(1)), headers, payload


def _retry_after(headers: dict[str, str]) -> float | None:
    try:
        value = float(headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def _gh_attempt(gh_bin: str, path: str, timeout: float) -> _Attempt:
    """gh 한 번. 새 세션으로 띄우고, 시간이 넘거나 신호로 끊기면 그룹째 죽이고 기다린다."""
    try:
        process = subprocess.Popen([gh_bin, "api", "-i", path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        return _Attempt("fail", reason=f"gh를 실행하지 못했다({type(exc).__name__})")
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        return _Attempt("timeout", reason=f"GitHub 응답 시간 초과({timeout:.0f}초)")
    finally:
        if process.poll() is None:
            _kill_group(process)
    parsed = parse_gh_output(stdout)
    if parsed is None:
        return _Attempt("retry", reason=f"gh 실패(종료 코드 {process.returncode})")
    status, headers, payload = parsed
    if 200 <= status < 300:
        if payload is None:
            return _Attempt("retry", reason=f"GitHub 응답이 JSON이 아니다(HTTP {status})")
        return _Attempt("ok", value=(status, payload))
    if status == 404:
        return _Attempt("ok", value=(404, None))
    if status in (403, 429):
        return _Attempt("retry", reason=f"GitHub HTTP {status}", retry_after=_retry_after(headers))
    if status >= 500:
        return _Attempt("retry", reason=f"GitHub HTTP {status}")
    return _Attempt("fail", reason=f"GitHub HTTP {status}")


# --- Sonar ------------------------------------------------------------------------------------

def _sonar_attempt(url: str, token: str, path: str, params: dict, timeout: float) -> _Attempt:
    client = sonar_api.SonarClient(url, token=token, timeout=timeout)
    try:
        return _Attempt("ok", value=client.get(path, **params))
    except sonar_api.SonarError as exc:
        reason = sonar_api.redact(str(exc), token)
        if exc.http_status == 404:
            return _Attempt("ok", value=None)
        if exc.http_status is None or exc.http_status >= 500:
            return _Attempt("retry", reason=f"Sonar {reason}")
        return _Attempt("fail", reason=f"Sonar {reason}")


def _rating(value) -> str | None:
    number = _to_float(value)
    return RATING_LETTERS.get(int(number)) if number is not None and number.is_integer() else None


def _to_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None and number.is_integer() else None


# --- 수집 문맥 ----------------------------------------------------------------------------------

@dataclass
class _Context:
    env: Mapping[str, str]
    budget: Budget
    gh_bin: str
    retry_delays: tuple[float, ...]
    sonar_url: str | None
    sonar_url_error: str | None
    sonar_token: str

    def gh(self, path: str) -> tuple[int, object]:
        return _with_retries(self.budget, self.retry_delays, lambda timeout: _gh_attempt(self.gh_bin, path, timeout))

    def sonar(self, path: str, params: dict) -> dict | None:
        return _with_retries(self.budget, self.retry_delays,
                             lambda timeout: _sonar_attempt(self.sonar_url, self.sonar_token, path, params, timeout))


def _retry_delays(env: Mapping[str, str]) -> tuple[float, ...]:
    """테스트 전용 `TD_COLLECT_RETRY_DELAYS`(쉼표 구분 초)는 `TD_SITE_PREFIX`가 있을 때만 따른다."""
    raw = (env.get("TD_COLLECT_RETRY_DELAYS") or "").strip()
    if raw and (env.get("TD_SITE_PREFIX") or "").strip():
        try:
            values = tuple(float(part) for part in raw.split(",") if part.strip())
        except ValueError:
            values = ()
        if values and all(value >= 0 for value in values):
            return values
    return tuple(float(delay) for delay in RETRY_DELAYS_SEC)


def _budget_seconds(env: Mapping[str, str]) -> float:
    try:
        value = float(env.get("TD_COLLECT_BUDGET_SEC") or BUDGET_SEC)
    except ValueError:
        return float(BUDGET_SEC)
    return value if value > 0 else float(BUDGET_SEC)


def _context(env: Mapping[str, str]) -> _Context:
    sonar_url, sonar_url_error = (env.get("TD_SONAR_URL") or "").strip() or None, None
    if sonar_url is None:
        try:
            sonar_url = sonar_api.base_url(env)
        except sonar_api.SonarError as exc:
            sonar_url_error = str(exc)
    return _Context(env=env, budget=Budget(_budget_seconds(env)), gh_bin=env.get("TD_GH_BIN") or "gh",
                    retry_delays=_retry_delays(env), sonar_url=sonar_url, sonar_url_error=sonar_url_error,
                    sonar_token=env.get("SONAR_TOKEN") or "")


# --- 설정 ------------------------------------------------------------------------------------

def check_repos(cfg: Config) -> None:
    """`repo` 값이 gh 경로에 들어가도 되는 모양인지 확인한다. 아니면 `ConfigError`(`projects[i].repo: …`)."""
    where_file = f"{cfg.path}: " if cfg.path else ""
    for index, project in enumerate(cfg.projects):
        if project.repo is None:
            continue
        segments = project.repo.split("/")
        if not REPO_PATTERN.match(project.repo) or any(segment in (".", "..") for segment in segments):
            raise ConfigError(f"{where_file}projects[{index}].repo: 'owner/name' 모양({REPO_PATTERN.pattern})이어야 하고 "
                              f"'.'·'..' 구간은 쓸 수 없다: {project.repo!r}")


def _has_complete_run(site: Path, sut: str) -> bool:
    return any((site / "suts" / sut / "runs").glob("*/_COMPLETE"))


def is_sonar_target(project: Project, site: Path) -> bool:
    """`repo`가 있고, `sut`가 없거나 그 SUT에 완료된 run이 없는 과제(완료된 run이 있으면 Sonar 값은 run에서 온다)."""
    return project.repo is not None and (project.sut is None or not _has_complete_run(site, project.sut))


def sonar_key(project: Project, suts_dir: Path) -> str:
    """`sonarKey` → `<suts_dir>/<sut>/sut.yaml`의 `sonar.projectKey` → 저장소 이름(슬래시 뒤)."""
    if project.sonar_key:
        return project.sonar_key
    if project.sut:
        try:
            data = yaml.safe_load((Path(suts_dir) / project.sut / "sut.yaml").read_text())
        except (OSError, yaml.YAMLError):
            data = None
        key = ((data or {}).get("sonar") or {}).get("projectKey") if isinstance(data, dict) else None
        if isinstance(key, str) and key.strip():
            return key.strip()
    return project.repo.split("/", 1)[1]


# --- CI ---------------------------------------------------------------------------------------

def summarize_runs(conclusions_newest_first: list) -> dict:
    """설계 §6.3 표로 나눈 실행 집계. 집계 대상이 없으면 수치는 모두 None, 이력은 빈 배열."""
    counted = [conclusion for conclusion in conclusions_newest_first
               if conclusion in SUCCESS_CONCLUSIONS or conclusion in FAILURE_CONCLUSIONS]
    if not counted:
        return {"runs": None, "successes": None, "failures": None, "successRate": None, "lastFailed": None, "history": []}
    successes = sum(1 for conclusion in counted if conclusion in SUCCESS_CONCLUSIONS)
    return {"runs": len(counted), "successes": successes, "failures": len(counted) - successes,
            "successRate": successes / len(counted), "lastFailed": counted[0] in FAILURE_CONCLUSIONS,
            "history": [1 if conclusion in SUCCESS_CONCLUSIONS else 0 for conclusion in reversed(counted)]}


def failed_checks(check_runs: list) -> list[str]:
    """이름마다 가장 늦게 시작한 검사만 본다. 그것이 끝났고 결론이 실패 분류면 그 이름을 센다(진행 중은 세지 않는다)."""
    latest: dict[str, dict] = {}
    for check in check_runs:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            continue
        started = check.get("started_at") or ""
        current = latest.get(check["name"])
        if current is None or started > (current.get("started_at") or ""):
            latest[check["name"]] = check
    return sorted(name for name, check in latest.items()
                  if check.get("status") == "completed" and check.get("conclusion") in FAILURE_CONCLUSIONS)


def _collect_ci(ctx: _Context, repo: str, branch: str) -> tuple[dict | None, str, list[dict]]:
    """(ci 값, 출처 상태 ok|none|failed, 문제 목록)."""
    problems: list[dict] = []
    run_summary = None
    query = urllib.parse.urlencode({"branch": branch, "status": "completed", "per_page": RUNS_PER_PAGE})
    try:
        status, payload = ctx.gh(f"repos/{repo}/actions/runs?{query}")
        runs = (payload or {}).get("workflow_runs") if status != 404 else []
        if not isinstance(runs, list):
            raise FetchError("Actions 실행 목록의 모양이 틀리다")
        run_summary = summarize_runs([run.get("conclusion") for run in runs if isinstance(run, dict)])
    except FetchError as exc:
        problems.append({"source": "ci", "reason": f"Actions 실행 목록을 읽지 못했다: {exc}"})
    check_names: list[str] | None = None
    branch_path = urllib.parse.quote(branch, safe="")
    try:
        status, payload = ctx.gh(f"repos/{repo}/commits/{branch_path}/check-runs?per_page={CHECKS_PER_PAGE}")
        if status != 404:
            check_runs = (payload or {}).get("check_runs")
            if not isinstance(check_runs, list):
                raise FetchError("Check Runs 응답의 모양이 틀리다")
            check_names = failed_checks(check_runs)
    except FetchError as exc:
        problems.append({"source": "ci", "reason": f"최신 커밋의 검사 결과를 읽지 못했다: {exc}"})
    if run_summary is None and check_names is None and problems:
        return None, "failed", problems
    ci = dict(run_summary or {"runs": None, "successes": None, "failures": None, "successRate": None,
                              "lastFailed": None, "history": []})
    ci["failedChecks"] = len(check_names) if check_names is not None else None
    ci["failedCheckNames"] = check_names or []
    if problems:
        return ci, "failed", problems
    return ci, ("ok" if ci["runs"] else "none"), problems


# --- Sonar 수집 ---------------------------------------------------------------------------------

def _collect_sonar(ctx: _Context, key: str) -> tuple[dict | None, str, list[dict]]:
    """(sonar 값, 출처 상태 ok|absent|failed, 문제 목록). 프로젝트 404는 실패가 아니라 없음이다."""
    if ctx.sonar_url is None:
        return None, "failed", [{"source": "sonar", "reason": f"Sonar URL을 알 수 없다: {ctx.sonar_url_error}"}]
    if not ctx.sonar_token:
        return None, "failed", [{"source": "sonar", "reason": REASON_NO_TOKEN}]
    try:
        gate_doc = ctx.sonar("/api/qualitygates/project_status", {"projectKey": key})
        if gate_doc is None:
            return None, "absent", []
        measures_doc = ctx.sonar("/api/measures/component", {"component": key, "metricKeys": ",".join(SONAR_MEASURES)})
        if measures_doc is None:
            return None, "absent", []
    except FetchError as exc:
        return None, "failed", [{"source": "sonar", "reason": f"Sonar 값을 읽지 못했다: {exc}"}]
    gate = (gate_doc.get("projectStatus") or {}).get("status")
    measures = {item.get("metric"): item.get("value")
                for item in (measures_doc.get("component") or {}).get("measures") or [] if isinstance(item, dict)}
    return {
        "gate": gate if isinstance(gate, str) and gate else "NONE",
        "coverage": _to_float(measures.get("coverage")),
        "bugs": _to_int(measures.get("bugs")),
        "vulnerabilities": _to_int(measures.get("vulnerabilities")),
        "codeSmells": _to_int(measures.get("code_smells")),
        "ncloc": _to_int(measures.get("ncloc")),
        "ratings": {"reliability": _rating(measures.get("reliability_rating")),
                    "security": _rating(measures.get("security_rating")),
                    "maintainability": _rating(measures.get("sqale_rating"))},
    }, "ok", []


# --- 쓰기 ------------------------------------------------------------------------------------

def _write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _log(message: str) -> None:
    print(f"collect: {message}", file=sys.stderr)


@dataclass
class _Visible:
    project: Project
    info: dict
    ci: dict | None = None
    ci_state: str = "none"
    sonar: dict | None = None
    sonar_state: str = "skipped"
    problems: list[dict] = field(default_factory=list)


def collect(cfg: Config, site: Path, suts_dir: Path, *, now: datetime, env: Mapping[str, str]) -> dict:
    """수집 1회. 결과 dict(status, reasons, written, excluded, unverified). 설정 오류는 `ConfigError`."""
    check_repos(cfg)
    site, suts_dir = Path(site), Path(suts_dir)
    ctx = _context(env)
    redact_env = dict(env)
    moment = now.astimezone(timezone.utc)
    date, collected_at = moment.strftime("%Y%m%d"), state.fmt_utc(moment)

    def clean(text: str) -> str:
        return redact.redact_text(sonar_api.redact(text, ctx.sonar_token), env=redact_env)

    # 1. 공개 여부
    visible: list[_Visible] = []
    excluded: list[str] = []
    unverified: list[str] = []
    for project in (item for item in cfg.projects if item.repo):
        try:
            status, info = ctx.gh(f"repos/{project.repo}")
            if status != 404 and not isinstance(info, dict):
                raise FetchError("저장소 정보의 모양이 틀리다")
        except FetchError as exc:
            unverified.append(project.name)
            _log(f"공개 여부를 확인하지 못해 쓰지 않는다: {project.name} ({clean(str(exc))})")
            continue
        if status == 404 or info.get("visibility") != "public" or info.get("private"):
            excluded.append(project.name)
            _log(f"비공개이거나 없는 저장소라 제외한다: {project.name}")
            continue
        visible.append(_Visible(project, info))

    # 2. CI
    for item in visible:
        branch = item.info.get("default_branch") or "main"
        item.ci, item.ci_state, problems = _collect_ci(ctx, item.project.repo, branch)
        item.problems += problems

    # 3. Sonar
    for item in visible:
        if is_sonar_target(item.project, site):
            item.sonar, item.sonar_state, problems = _collect_sonar(ctx, sonar_key(item.project, suts_dir))
            item.problems += problems

    # 4. 쓰기(공개로 확정된 과제만)
    written: list[str] = []
    failed_names: list[str] = list(unverified)
    for item in visible:
        info = item.info
        snapshot = {
            "schema": 1, "name": item.project.name, "repo": item.project.repo, "visibility": "public",
            "collectedAt": collected_at, "date": date,
            "repoInfo": {"pushedAt": info.get("pushed_at") or "", "language": info.get("language"),
                         "description": info.get("description"), "defaultBranch": info.get("default_branch") or "main"},
            "sources": {"ci": item.ci_state, "sonar": item.sonar_state},
            "ci": item.ci, "sonar": item.sonar,
            "problems": [{"source": problem["source"], "reason": clean(problem["reason"])} for problem in item.problems],
        }
        snapshot = redact.redact_obj(snapshot, env=redact_env)
        project_dir = site / "projects" / item.project.name
        for relative in (f"snapshots/{date}.json", "latest.json"):
            _write_json_atomic(project_dir / relative, snapshot)
            written.append(f"projects/{item.project.name}/{relative}")
        if "failed" in (item.ci_state, item.sonar_state):
            failed_names.append(item.project.name)
            _log(f"일부 출처를 읽지 못했다: {item.project.name}")
    # 파일에는 앞서 공개로 수집된 과제만 적는다(한 번도 확인하지 못한 과제는 비공개일 수 있어 이름을 쓰지 않는다).
    _write_json_atomic(site / "projects" / COLLECT_STATE_FILE,
                       {"schema": 1, "date": date,
                        "unverified": sorted(name for name in unverified if _was_public(site, name))})
    written.append(f"projects/{COLLECT_STATE_FILE}")

    reasons = []
    if excluded:
        reasons.append(REASON_EXCLUDED.format(count=len(excluded)))
    if failed_names:
        reasons.append(REASON_FAILED.format(count=len(failed_names)))
    if ctx.budget.exceeded:
        reasons.append(REASON_BUDGET)
    return {"status": "degraded" if reasons else "ok", "reasons": reasons, "written": written,
            "excluded": sorted(excluded), "unverified": sorted(unverified)}


def _was_public(site: Path, name: str) -> bool:
    """디스크에 유효한 스냅숏이 있고 그 최신 것이 공개인가(인덱스가 그리는 조건과 같다)."""
    snapshots, _dropped = load_snapshots(site / "projects" / name)
    return bool(snapshots) and snapshots[-1].get("visibility") == "public"


def needs_sonar(cfg: Config, site: Path) -> int:
    """Sonar를 읽을 과제 수(공개 여부 확인 전, 설정과 사이트의 완료 run만으로 정한다)."""
    return sum(1 for project in cfg.projects if is_sonar_target(project, Path(site)))


# --- CLI ------------------------------------------------------------------------------------

def _raise_interrupted(signum, _frame):
    raise Interrupted(signum)


def _load(args) -> Config:
    cfg = dashboard_config.load(Path(args.config), Path(args.suts_dir))
    check_repos(cfg)
    return cfg


def cmd_run(args) -> int:
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _raise_interrupted)     # 백그라운드로 띄워져 SIGINT가 무시된 채 시작해도 받는다
    cfg = _load(args)
    result = collect(cfg, Path(args.site), Path(args.suts_dir), now=state.now(), env=os.environ)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_needs_sonar(args) -> int:
    print(needs_sonar(_load(args), Path(args.site)))
    return 0


def cmd_amend(args) -> int:
    try:
        result = json.loads(sys.stdin.read())
        if not isinstance(result, dict):
            raise ValueError("JSON 객체가 아니다")
    except ValueError as exc:
        print(f"collect amend: 수집 결과를 읽지 못했다: {exc}", file=sys.stderr)
        return 1
    result["status"] = args.status
    reasons = result.get("reasons") if isinstance(result.get("reasons"), list) else []
    if args.reason not in reasons:
        reasons.append(args.reason)
    result["reasons"] = reasons
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.collect")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("run", cmd_run), ("needs-sonar", cmd_needs_sonar)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--config", required=True)
        cmd.add_argument("--site", required=True)
        cmd.add_argument("--suts-dir", required=True)
        cmd.set_defaults(fn=fn)
    amend = sub.add_parser("amend")
    amend.add_argument("--status", required=True, choices=("ok", "degraded"))
    amend.add_argument("--reason", required=True)
    amend.set_defaults(fn=cmd_amend)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as exc:
        print(f"collect: 설정 오류: {exc}", file=sys.stderr)
        return 2
    except Interrupted as exc:
        _log(f"신호 {exc.signum}을 받아 멈춘다")
        return 128 + exc.signum


if __name__ == "__main__":
    sys.exit(main())
