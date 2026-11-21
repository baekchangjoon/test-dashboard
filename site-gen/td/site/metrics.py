"""run 지표 추출, 수집 스냅숏 읽기, 과제 뷰 조립, 시계열, 집계(설계 §6.2, §6.4).

사이트 디렉터리 아래 파일만 읽는다(외부 서비스·게시 모듈을 쓰지 않는다). 측정하지 않은 값은 None이다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from td import dashboard_config
from td.dashboard_config import CATALOG, Config, format_value

SNAPSHOT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "project-snapshot.schema.json"
GOOD_STAGE_STATUSES = ("passed", "degraded")
DURATION_STAGES = tuple(f"S{number:02d}" for number in range(13))     # S00~S12
RUN_METRICS = tuple(name for name, metric in CATALOG.items() if metric.scope in ("run", "both"))
SNAPSHOT_METRICS = tuple(name for name, metric in CATALOG.items() if metric.scope in ("snapshot", "both"))
PROJECT_METRICS = tuple(name for name, metric in CATALOG.items() if metric.scope in ("run", "snapshot", "both"))
SONAR_METRICS = tuple(name for name in PROJECT_METRICS if name.startswith("sonar."))
COLLECT_STATE_FILE = "_collect.json"
MISSING = "—"


# --- 작은 도우미 ----------------------------------------------------------------------------------

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _to_float(value) -> float | None:
    """Sonar 측정값(문자열 또는 수)을 실수로. 바꿀 수 없으면 None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None and number.is_integer() else None


def _parse_time(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stage(run_dir: Path, stage_id: str) -> dict | None:
    """단계 JSON. 상태가 passed·degraded가 아니거나 파일이 없으면 None(실패한 단계에 남은 값은 읽지 않는다)."""
    data = _read_json(run_dir / "stages" / f"{stage_id}.json")
    if not isinstance(data, dict) or data.get("status") not in GOOD_STAGE_STATUSES:
        return None
    return data


# --- run 지표 ---------------------------------------------------------------------------------------

def _e2e_pass_rate(stage: dict | None) -> float | None:
    if stage is None:
        return None
    passed_total = scenario_total = 0
    for generation in _dict(stage.get("generations")).values():
        counts = _dict(_dict(generation).get("statusCounts"))
        passed_total += _number(counts.get("passed")) or 0
        scenario_total += sum(_number(count) or 0 for count in counts.values())
    return passed_total / scenario_total if scenario_total else None


def _hotspot_top(stage: dict | None) -> tuple[float | None, str | None]:
    top = (stage or {}).get("top10")
    if not isinstance(top, list) or not top or not isinstance(top[0], dict):
        return None, None
    name = top[0].get("name")
    return _number(top[0].get("score")), name if isinstance(name, str) else None


def _tia_ratio(stage: dict | None) -> float | None:
    impact = _dict((stage or {}).get("impact"))
    selected, indexed = _number(impact.get("selected")), _number(impact.get("indexedTests"))
    if selected is None or not indexed:
        return None
    return selected / indexed


def _duration_seconds(run_dir: Path, started_at) -> int | float | None:
    """S00~S12 가운데 가장 늦은 finishedAt − run 시작. 단계 상태와 무관하게 시각만 본다(끝난 단계는 실패여도 끝난 것이다)."""
    started = _parse_time(started_at)
    if started is None:
        return None
    finishes = []
    for stage_id in DURATION_STAGES:
        data = _read_json(run_dir / "stages" / f"{stage_id}.json")
        finished = _parse_time(_dict(data).get("finishedAt"))
        if finished is not None:
            finishes.append(finished)
    if not finishes:
        return None
    seconds = (max(finishes) - started).total_seconds()
    return int(seconds) if seconds.is_integer() else seconds


def run_metrics(run_dir: Path) -> dict[str, object]:
    """설계 §6.2 "run에서 오는 것" 표의 지표 전부. 없는 값은 None."""
    run_dir = Path(run_dir)
    run = _dict(_read_json(run_dir / "run.json"))
    kpis = _dict(run.get("kpis"))
    blackbox = _dict(kpis.get("blackbox"))
    sonar = _dict(kpis.get("sonar"))
    gate = sonar.get("gate")
    top_score, top_name = _hotspot_top(_stage(run_dir, "S09"))
    values = {
        "tests.passRate": _number(_dict(kpis.get("tests")).get("passRate")),
        "coverage.line": _number(blackbox.get("line")),
        "coverage.aggregateLine": _number(_dict(blackbox.get("aggregate")).get("line")),
        "e2e.passRate": _e2e_pass_rate(_stage(run_dir, "S07")),
        "hotspot.topScore": top_score,
        "hotspot.topName": top_name,
        "tia.selectedRatio": _tia_ratio(_stage(run_dir, "S10")),
        "run.durationSec": _duration_seconds(run_dir, run.get("startedAt")),
        "sonar.gate": gate if isinstance(gate, str) else None,
        "sonar.coverage": _to_float(sonar.get("coverage")),
        "sonar.vulnerabilities": _to_int(sonar.get("vulnerabilities")),
        "sonar.bugs": _to_int(sonar.get("bugs")),
        "sonar.codeSmells": _to_int(sonar.get("codeSmells")),
    }
    return {name: values[name] for name in RUN_METRICS}


# --- 스냅숏 -----------------------------------------------------------------------------------------

_snapshot_validator: Draft202012Validator | None = None


def _validator() -> Draft202012Validator:
    global _snapshot_validator
    if _snapshot_validator is None:
        _snapshot_validator = Draft202012Validator(json.loads(SNAPSHOT_SCHEMA_PATH.read_text(encoding="utf-8")))
    return _snapshot_validator


def load_snapshots(project_dir: Path) -> tuple[list[dict], list[str]]:
    """`projects/<name>/snapshots/*.json`을 날짜순으로 읽는다. 깨졌거나 스키마를 어긴 파일은 버리고 사유를 남긴다."""
    snapshots_dir = Path(project_dir) / "snapshots"
    kept: list[dict] = []
    reasons: list[str] = []
    files = sorted(snapshots_dir.glob("*.json")) if snapshots_dir.is_dir() else []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            reasons.append(f"스냅숏 {path.name}을 버렸다: JSON을 읽을 수 없다({type(exc).__name__})")
            continue
        errors = sorted(_validator().iter_errors(data), key=lambda err: [str(part) for part in err.absolute_path])
        if errors:
            first = errors[0]
            where = ".".join(str(part) for part in first.absolute_path) or "<root>"
            reasons.append(f"스냅숏 {path.name}을 버렸다: {where}: {first.message}")
            continue
        if data["date"] != path.stem:
            reasons.append(f"스냅숏 {path.name}을 버렸다: date {data['date']}가 파일 이름과 다르다")
            continue
        kept.append(data)
    kept.sort(key=lambda item: item["date"])
    return kept, reasons


def newer_snapshot_hides(project_dir: Path, after_date: str | None) -> bool:
    """`after_date`보다 뒤 날짜(파일 이름)의 스냅숏 파일 가운데 공개가 아니라고 말하는 것이 있는가.

    JSON 객체로 읽히고 `visibility` 키가 있는데 값이 "public"이 아니면 공개가 아니라고 말하는 것으로 본다.
    읽을 수 없거나 `visibility`가 없는 파일은 공개 여부를 말하지 않으므로 막지 않는다(앞선 유효 스냅숏으로 그린다).
    """
    snapshots_dir = Path(project_dir) / "snapshots"
    files = sorted(snapshots_dir.glob("*.json")) if snapshots_dir.is_dir() else []
    for path in files:
        if after_date is not None and path.stem <= after_date:
            continue
        data = _read_json(path)
        if isinstance(data, dict) and "visibility" in data and data["visibility"] != "public":
            return True
    return False


def snapshot_metrics(snapshot: dict) -> dict[str, object]:
    """스냅숏에서 오는 과제 지표(ci.*, sonar.*, repo.*). `ci.runs`가 0이면 없음."""
    ci = snapshot.get("ci")
    sonar = snapshot.get("sonar")
    repo_info = _dict(snapshot.get("repoInfo"))
    values: dict[str, object] = {name: None for name in SNAPSHOT_METRICS}
    if isinstance(ci, dict):
        runs = ci.get("runs")
        values.update({
            "ci.runs": runs or None,
            "ci.successes": ci.get("successes"),
            "ci.failures": ci.get("failures"),
            "ci.successRate": ci.get("successRate") if runs else None,
            "ci.lastFailed": ci.get("lastFailed"),
            "ci.failedChecks": ci.get("failedChecks"),
            "ci.failedCheckNames": list(ci.get("failedCheckNames") or []),
        })
    if isinstance(sonar, dict):
        values.update({
            "sonar.gate": sonar.get("gate"),
            "sonar.coverage": sonar.get("coverage"),
            "sonar.vulnerabilities": sonar.get("vulnerabilities"),
            "sonar.bugs": sonar.get("bugs"),
            "sonar.codeSmells": sonar.get("codeSmells"),
        })
    values.update({
        "repo.pushedAt": repo_info.get("pushedAt"),
        "repo.language": repo_info.get("language"),
        "repo.description": repo_info.get("description"),
    })
    return values


def _unverified_names(base: Path) -> frozenset[str]:
    """`projects/_collect.json`의 unverified. 파일이 없거나 모양이 틀리면 빈 집합."""
    state = _read_json(base / "projects" / COLLECT_STATE_FILE)
    names = _dict(state).get("unverified")
    if not isinstance(names, list):
        return frozenset()
    return frozenset(name for name in names if isinstance(name, str))


# --- 과제 뷰 ----------------------------------------------------------------------------------------

def _completed_runs(base: Path) -> dict[str, list[dict]]:
    # index가 metrics를 쓰므로 순환 가져오기를 피하려고 함수 안에서 가져온다.
    from td.site.index import _collect
    return _collect(base)


def build_projects(base: Path, cfg: Config, *, exclude: frozenset[str] = frozenset()) -> list[dict]:
    """그리는 과제마다 뷰 dict를 만든다. 정렬은 status.order, 그 안에서 이름(대소문자 무시)."""
    base = Path(base)
    runs_by_sut = _completed_runs(base)
    cfg = dashboard_config.with_implicit(cfg, runs_by_sut.keys())
    unverified = _unverified_names(base)
    labels = cfg.status["labels"]
    views = []
    for project in cfg.projects:
        if project.name in exclude:
            continue
        project_dir = base / "projects" / project.name
        snapshots, dropped = load_snapshots(project_dir) if project.repo else ([], [])
        latest_snapshot = snapshots[-1] if snapshots else None
        if project.repo is not None and (
                latest_snapshot is None or latest_snapshot.get("visibility") != "public"
                or latest_snapshot.get("repo") != project.repo
                or newer_snapshot_hides(project_dir, latest_snapshot["date"])):
            # repo가 있는 과제는 최신 유효 스냅숏이 공개이고 그 repo가 설정과 같으며, 그보다 뒤 날짜의 파일 가운데
            # 공개가 아니라고 말하는 것이 없을 때만 그린다(비공개로 바뀐 과제가 옛 공개 스냅숏으로 그려지지 않게).
            continue
        runs = runs_by_sut.get(project.sut, []) if project.sut else []
        latest_run_dir = base / "suts" / project.sut / "runs" / runs[0]["runId"] if runs else None

        values: dict[str, object] = {name: None for name in PROJECT_METRICS}
        if latest_snapshot is not None:
            values.update(snapshot_metrics(latest_snapshot))
        if latest_run_dir is not None:
            # 완료된 run이 있으면 sonar.*는 최신 run에서만 온다(스냅숏 값은 쓰지 않는다).
            values.update({name: None for name in SONAR_METRICS})
            values.update(run_metrics(latest_run_dir))

        verdict = dashboard_config.evaluate(values, cfg, has_repo=project.repo is not None)
        snapshot_problems = [f"{item['source']}: {item['reason']}" for item in (latest_snapshot or {}).get("problems", [])]
        # stale: 이번 수집에서 확인하지 못한(unverified) 설정 과제는 마지막으로 수집한 스냅숏 날짜를 표시한다.
        stale = latest_snapshot["date"] if (latest_snapshot and not project.implicit and project.name in unverified) else None
        ci_snapshot = _dict((latest_snapshot or {}).get("ci"))
        repo_info = _dict((latest_snapshot or {}).get("repoInfo"))
        sources = _dict((latest_snapshot or {}).get("sources"))
        views.append({
            "name": project.name, "repo": project.repo, "sut": project.sut,
            "pipeline": bool(runs), "implicit": project.implicit,
            "values": values,
            "verdict": {"level": verdict.level, "label": labels[verdict.level],
                        "reasons": list(verdict.reasons), "partial": verdict.partial},
            "headline": dashboard_config.headline(values, verdict, cfg),
            "runs": runs, "latestRunDir": latest_run_dir,
            "snapshots": snapshots,
            "sources": {"ci": sources.get("ci"), "sonar": sources.get("sonar")},
            "stale": stale,
            "problems": dropped + snapshot_problems,
            "description": repo_info.get("description"),
            "language": repo_info.get("language"),
            "ciHistory": list(ci_snapshot.get("history") or []),
        })
    order = cfg.status["order"]
    views.sort(key=lambda view: (order.index(view["verdict"]["level"]), view["name"].lower()))
    return views


# --- 시계열 -----------------------------------------------------------------------------------------

def _run_href(project: dict, run_id: str) -> str:
    """과제 페이지(`projects/<name>/`)에서 본 run 페이지 주소."""
    return f"../../suts/{project['sut']}/runs/{run_id}/index.html"


def series_points(project: dict, names) -> list[dict]:
    """시계열 점(오래된 것부터). 파이프라인 과제는 완료 run마다(`href` 포함), 그 밖은 스냅숏마다. 값은 names만."""
    names = list(names)
    if project["pipeline"]:
        runs_dir = Path(project["latestRunDir"]).parent
        points = []
        for run in sorted(project["runs"], key=lambda item: item["runId"]):
            run_values = run_metrics(runs_dir / run["runId"])
            points.append({"id": run["runId"], "at": run.get("startedAt"), "href": _run_href(project, run["runId"]),
                           "values": {name: run_values.get(name) for name in names}})
        return points
    points = []
    for snapshot in project["snapshots"]:
        snap_values = snapshot_metrics(snapshot)
        points.append({"id": snapshot["date"], "at": snapshot.get("collectedAt"),
                       "values": {name: snap_values.get(name) for name in names}})
    return points


def series(project: dict, cfg: Config) -> dict:
    """설계 §6.4 `series.json`. 파이프라인 과제는 run 점(runId 순), 그 밖은 스냅숏 점(날짜 순)."""
    kind = "run" if project["pipeline"] else "snapshot"
    names = list(cfg.project["trend"][kind])
    return {"schema": 1, "kind": kind, "metrics": names, "points": series_points(project, names)}


# --- 과제 페이지의 탭 데이터(설계 §5.2) ---------------------------------------------------------------

STAGE_IDS = tuple(f"S{number:02d}" for number in range(14))      # S00~S13
SEVERITIES = ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO")
ISSUE_TYPES = ("VULNERABILITY", "BUG", "CODE_SMELL")
RATING_LETTERS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}
COMPARE_METRICS = ("scenarios", "compile", "passed", "endpoint", "line", "tokens", "seconds")
# "한눈에"의 리포트 바로가기(시안 project.html): 표시 이름, run 디렉터리 기준 경로, 한 줄 설명
OVERVIEW_REPORTS = (
    ("커버리지", "coverage/coverage.html", "테스트별로 지키는 코드"),
    ("hotspot", "hotspot/hotspots.html", "먼저 손볼 코드"),
    ("변경 영향(TIA)", "tia/tia.html", "변경에 영향받는 테스트"),
    ("Sonar 품질 결과", "sonar/sonar.html", "정적 분석 이슈"),
    ("방식 비교", "compare/compare.html", "생성 방식 판정"),
    ("jQA 온톨로지", "ontology/jqa.html", "코드 구조 그래프"),
    ("OWL 온톨로지", "ontology/owl.html", "도메인 지식 그래프"),
)
NON_SUITE_KPIS = ("tests", "sonar", "compare")


def _report_link(run_dir: Path, run_href: str, rel: str, label: str = "", note: str = "") -> dict | None:
    """run 디렉터리에 그 파일이 있을 때만 링크(과제 페이지 기준 상대 주소). 없으면 None(죽은 링크를 두지 않는다)."""
    if not (run_dir / rel).is_file():
        return None
    return {"report": rel, "href": f"{run_href}{rel}", "label": label, "note": note}


def _rating(value) -> str | None:
    number = _to_float(value)
    return RATING_LETTERS.get(int(number)) if number is not None and number.is_integer() else None


def _stage_seconds(stage: dict) -> float | None:
    started, finished = _parse_time(stage.get("startedAt")), _parse_time(stage.get("finishedAt"))
    if started is None or finished is None or finished < started:
        return None
    seconds = (finished - started).total_seconds()
    return int(seconds) if seconds.is_integer() else seconds


def _stages(base: Path, project: dict, run_dir: Path, run: dict) -> list[dict]:
    """단계 띠 14칸: `{id, status, sec, reason}`. 실행하지 않은 단계는 status None.
    S13(게시)은 run 디렉터리의 값이 렌더 시점이라, 게시 기록(`suts/<sut>/publish-log/<runId>.json`)이 있으면 그 값을 쓴다."""
    items = []
    recorded = _dict(run.get("stages"))
    for stage_id in STAGE_IDS:
        stage = _dict(_read_json(run_dir / "stages" / f"{stage_id}.json"))
        status = stage.get("status") if stage else recorded.get(stage_id)
        reason = stage.get("reason") or ""
        seconds = _stage_seconds(stage) if stage else None
        if stage_id == "S13":
            log = _dict(_read_json(base / "suts" / project["sut"] / "publish-log" / f"{run_dir.name}.json"))
            status, reason = (log.get("status"), log.get("reason") or "") if log.get("status") else (None, "")
        items.append({"id": stage_id, "status": status if isinstance(status, str) else None,
                      "sec": seconds, "reason": str(reason)})
    return items


def _issue_counts(items: list) -> dict[str, dict[str, int]]:
    counts = {issue_type: {severity: 0 for severity in SEVERITIES} for issue_type in ISSUE_TYPES}
    for item in items:
        item = _dict(item)
        issue_type, severity = item.get("type"), item.get("severity")
        if issue_type in counts and severity in counts[issue_type]:
            counts[issue_type][severity] += 1
    return counts


def _sonar_from_report(doc: dict) -> dict:
    measures = _dict(doc.get("measures"))
    issues = _dict(doc.get("issues"))
    items = issues.get("items") if isinstance(issues.get("items"), list) else []
    gate = _dict(doc.get("qualityGate"))
    conditions = [_dict(item) for item in gate.get("conditions") or []]
    dashboard = doc.get("dashboardUrl")
    hotspots = _dict(doc.get("hotspots"))
    return {
        "source": "report", "gate": gate.get("status") if isinstance(gate.get("status"), str) else None,
        "conditions": len(conditions), "failedConditions": sum(1 for item in conditions if item.get("status") == "ERROR"),
        "coverage": _to_float(measures.get("coverage")), "bugs": _to_int(measures.get("bugs")),
        "vulnerabilities": _to_int(measures.get("vulnerabilities")), "codeSmells": _to_int(measures.get("code_smells")),
        "ncloc": _to_int(measures.get("ncloc")),
        "ratings": {"security": _rating(measures.get("security_rating")),
                    "reliability": _rating(measures.get("reliability_rating")),
                    "maintainability": _rating(measures.get("sqale_rating"))},
        "issues": _issue_counts(items), "issueTotal": _number(issues.get("total")), "issueFetched": len(items),
        "issuesTruncated": bool(issues.get("truncated")),
        "hotspots": [str(_dict(item).get("message") or "") for item in hotspots.get("items") or []],
        "dashboardUrl": dashboard if isinstance(dashboard, str) and dashboard.startswith(("https://", "http://")) else None,
    }


def _sonar_from_values(values: dict, ratings: dict | None = None, ncloc=None) -> dict | None:
    """sonar.json이 없을 때(스냅숏 과제, 또는 리포트 없는 run): 과제 값의 게이트와 측정값만(이슈 표 없음)."""
    if all(values.get(name) is None for name in SONAR_METRICS):
        return None
    ratings = _dict(ratings)
    return {
        "source": "values", "gate": values.get("sonar.gate"), "conditions": 0, "failedConditions": 0,
        "coverage": values.get("sonar.coverage"), "bugs": values.get("sonar.bugs"),
        "vulnerabilities": values.get("sonar.vulnerabilities"), "codeSmells": values.get("sonar.codeSmells"),
        "ncloc": ncloc if isinstance(ncloc, int) else None,
        "ratings": {key: ratings.get(key) for key in ("security", "reliability", "maintainability")},
        "issues": None, "issueTotal": None, "issueFetched": 0, "issuesTruncated": False, "hotspots": [],
        "dashboardUrl": None,
    }


def _threshold_check(text) -> tuple[str, float] | None:
    """`">= 0.90"` 같은 기준을 (연산자, 값)으로. 읽을 수 없으면 None."""
    if not isinstance(text, str):
        return None
    parts = text.split()
    if len(parts) != 2 or parts[0] not in (">=", "<=", ">", "<"):
        return None
    number = _to_float(parts[1])
    return (parts[0], number) if number is not None else None


def _meets(value, check: tuple[str, float] | None) -> bool | None:
    if value is None or check is None:
        return None
    operator_text, limit = check
    return {">=": value >= limit, "<=": value <= limit, ">": value > limit, "<": value < limit}[operator_text]


def _overview_snapshot(project: dict) -> dict:
    return {"kind": "snapshot", "values": dict(project["values"]), "ciHistory": list(project["ciHistory"]),
            "points": series_points(project, ("ci.successRate", "sonar.coverage"))}


def _run_view(project: dict, run_dir: Path, run_href: str) -> dict:
    """실행 이력의 한 줄: 값, 단계별 상태, run 페이지 링크(있을 때만)."""
    summary = next(run for run in project["runs"] if run["runId"] == run_dir.name)
    values = run_metrics(run_dir)
    page = _report_link(run_dir, run_href, "index.html", "실행 결과")
    return {"id": run_dir.name, "at": summary.get("startedAt"), "values": values,
            "stages": [summary["stages"].get(stage_id) for stage_id in STAGE_IDS], "page": page}


def tab_data(project: dict, base: Path, cfg: Config) -> dict[str, dict | None]:
    """탭 식별자 -> 템플릿 데이터. 데이터가 없는 탭은 None(화면에 나오지 않는다).

    파이프라인 과제는 미러의 최신 완료 run 디렉터리(`suts/<sut>/runs/<runId>/`)의 run.json, 단계 JSON, 게시된 리포트
    JSON(coverage/, sonar/, compare/)을 읽는다. 리포트 링크는 그 파일이 있을 때만 둔다. 그 밖의 과제는 스냅숏 값만 쓴다.
    """
    base = Path(base)
    kind = "run" if project["pipeline"] else "snapshot"
    trend_names = list(cfg.project["trend"][kind])
    data: dict[str, dict | None] = {tab: None for tab in dashboard_config.TAB_IDS}
    trend_points = series_points(project, trend_names)
    if not project["pipeline"]:
        data["overview"] = _overview_snapshot(project)
        latest = project["snapshots"][-1] if project["snapshots"] else {}
        sonar = _dict(latest.get("sonar"))
        data["quality"] = _sonar_from_values(project["values"], sonar.get("ratings"), sonar.get("ncloc"))
        if trend_points:
            data["trend"] = {"kind": kind, "metrics": trend_names, "points": trend_points}
        return data

    run_dir = Path(project["latestRunDir"])
    runs_dir = run_dir.parent
    run_href = f"../../suts/{project['sut']}/runs/{run_dir.name}/"
    run = _dict(_read_json(run_dir / "run.json"))
    kpis = _dict(run.get("kpis"))
    s07, s09, s10 = _stage(run_dir, "S07"), _stage(run_dir, "S09"), _stage(run_dir, "S10")
    top10 = [_dict(item) for item in (s09 or {}).get("top10") or [] if isinstance(item, dict)][:10]
    impact = _dict((s10 or {}).get("impact"))
    run_views = [_run_view(project, runs_dir / summary["runId"], f"../../suts/{project['sut']}/runs/{summary['runId']}/")
                 for summary in project["runs"]]          # 최신부터
    pages_present = {view["id"] for view in run_views if view["page"]}
    for point in trend_points:      # run 페이지가 없는 점은 링크로 그리지 않는다(series.json에는 남긴다)
        if point["id"] not in pages_present:
            point.pop("href", None)

    data["overview"] = {
        "kind": "run", "values": dict(project["values"]), "top": top10[:5],
        "impact": {"selected": _number(impact.get("selected")), "indexedTests": _number(impact.get("indexedTests")),
                   "deterministic": _number(impact.get("deterministic")), "range": (s10 or {}).get("range")}
        if _number(impact.get("selected")) is not None and _number(impact.get("indexedTests")) else None,
        "stages": _stages(base, project, run_dir, run),
        "reports": [link for link in (_report_link(run_dir, run_href, rel, label, note)
                                      for label, rel, note in OVERVIEW_REPORTS) if link],
        "runPage": _report_link(run_dir, run_href, "index.html", "실행 결과"),
        "commit": run.get("commit"), "startedAt": run.get("startedAt"), "runCount": len(project["runs"]),
        "testsTotal": _number(_dict(kpis.get("tests")).get("total")),
        "points": series_points(project, ("tests.passRate", "coverage.line")),
        "hotspotLink": _report_link(run_dir, run_href, "hotspot/hotspots.html", "hotspot 리포트"),
        "tiaLink": _report_link(run_dir, run_href, "tia/tia.html", "TIA 리포트"),
        "vulnerabilityCounts": None,
    }
    sonar_doc = _read_json(run_dir / "sonar" / "sonar.json")
    sonar = _sonar_from_report(sonar_doc) if isinstance(sonar_doc, dict) else _sonar_from_values(project["values"])
    if sonar is not None:
        sonar["link"] = _report_link(run_dir, run_href, "sonar/sonar.html", "Sonar 품질 결과")
        data["overview"]["vulnerabilityCounts"] = (sonar["issues"] or {}).get("VULNERABILITY")
    data["quality"] = sonar

    if trend_points:
        data["trend"] = {"kind": kind, "metrics": trend_names, "points": trend_points}

    coverage_doc = _dict(_read_json(run_dir / "coverage" / "coverage.json"))
    coverage_suites = _dict(coverage_doc.get("suites"))
    generations = []
    for gen_id, generation in sorted(_dict((s07 or {}).get("generations")).items()):
        generation = _dict(generation)
        counts = _dict(generation.get("statusCounts"))
        passed, failed = _number(counts.get("passed")), _number(counts.get("failed"))
        scenarios = _number(generation.get("scenarios"))
        if scenarios is None and counts:
            scenarios = sum(_number(value) or 0 for value in counts.values())
        generations.append({
            "id": gen_id, "arm": generation.get("arm") if isinstance(generation.get("arm"), str) else None,
            "scenarios": scenarios, "passed": passed, "failed": failed,
            "undefined": _number(counts.get("undefined")), "uncompilable": _number(counts.get("uncompilable")),
            "rate": passed / scenarios if passed is not None and scenarios else None,
            "link": _report_link(run_dir, run_href, f"cucumber/{gen_id}/index.html", "Cucumber 리포트"),
        })
    tests = _dict(kpis.get("tests"))
    blackbox_counts = _dict(coverage_suites.get("blackbox"))
    if tests or generations:
        data["tests"] = {"tests": {"passed": _number(tests.get("passed")), "total": _number(tests.get("total")),
                                   "passRate": _number(tests.get("passRate"))},
                         "attributed": _number(blackbox_counts.get("attributedCount")), "generations": generations}

    suite_names = [name for name in ["blackbox", *sorted(kpis)] if name not in NON_SUITE_KPIS
                   and isinstance(kpis.get(name), dict) and _number(kpis[name].get("line")) is not None]
    suites = []
    for name in dict.fromkeys(suite_names):
        suite = kpis[name]
        counts = _dict(coverage_suites.get(name))
        suites.append({"name": name, "line": _number(suite.get("line")), "branch": _number(suite.get("branch")),
                       "aggregate": _number(_dict(suite.get("aggregate")).get("line")),
                       "tc": _number(counts.get("tcCount")), "attributed": _number(counts.get("attributedCount"))})
    if suites:
        data["coverage"] = {"suites": suites,
                            "link": _report_link(run_dir, run_href, "coverage/coverage.html", "테스트별 상세")}
    if top10:
        data["hotspot"] = {"top": top10, "link": _report_link(run_dir, run_href, "hotspot/hotspots.html", "hotspot 리포트")}

    compare_doc = _read_json(run_dir / "compare" / "compare.json")
    if isinstance(compare_doc, dict):
        verdict = _dict(compare_doc.get("verdict"))
        thresholds = _dict(_dict(_dict(verdict.get("detail")).get("generation")).get("thresholds"))
        checks = {name: _threshold_check(thresholds.get(name)) for name in ("compile", "passed", "endpoint")}
        arms = []
        for arm_name, arm in _dict(compare_doc.get("arms")).items():
            arm = _dict(arm)
            arm_metrics = _dict(arm.get("metrics"))
            means = {name: _number(_dict(arm_metrics.get(name)).get("mean")) for name in COMPARE_METRICS}
            arms.append({"arm": str(arm_name), "status": arm.get("status"), "reason": arm.get("reason"), "means": means,
                         "meets": {name: _meets(means[name], check) for name, check in checks.items()}})
        data["generation"] = {
            "generation": verdict.get("generation"), "effect": verdict.get("effect"),
            "label": verdict.get("label") or compare_doc.get("label"), "reps": _number(compare_doc.get("reps")),
            "thresholds": {name: thresholds.get(name) for name in ("compile", "passed", "endpoint")}, "arms": arms,
            "link": _report_link(run_dir, run_href, "compare/compare.html", "비교 리포트"),
        }
    data["runs"] = {"runs": run_views}
    return data


# --- 집계 -------------------------------------------------------------------------------------------

def _aggregate_one(name: str, projects: list[dict]) -> tuple[str, str]:
    values = [project["values"] for project in projects]
    if not projects:
        return MISSING, "등록된 과제 없음"
    if name == "ci.successRateAll":
        runs = sum(item.get("ci.runs") or 0 for item in values)
        successes = sum(item.get("ci.successes") or 0 for item in values if item.get("ci.runs"))
        if not runs:
            return MISSING, "CI 실행 기록 없음"
        return format_value(name, successes / runs), f"{successes} / {runs}회"
    if name == "sonar.gatePassCount":
        gated = [item for item in values if item.get("sonar.gate") is not None]
        if not gated:
            return MISSING, "Sonar 게이트가 있는 과제 없음"
        passed = sum(1 for item in gated if item["sonar.gate"] == "OK")
        return f"{passed} / {len(gated)}", "게이트가 있는 과제 중 통과"
    if name == "sonar.coverageNonZeroCount":
        nonzero = sum(1 for item in values if (_number(item.get("sonar.coverage")) or 0) > 0)
        return f"{nonzero} / {len(values)}", "Sonar 커버리지가 0보다 큰 과제"
    if name == "status.noneCount":
        unmeasured = sum(1 for project in projects if project["verdict"]["level"] == "none")
        return format_value(name, unmeasured), f"전체 {len(projects)}개 중"
    raise KeyError(name)


def aggregate(projects: list[dict], cfg: Config) -> dict[str, dict]:
    """`home.summary`의 집계 지표마다 `{"label", "value", "detail"}`. 과제가 없으면 값은 "—"."""
    result = {}
    for name in cfg.home["summary"]:
        value, detail = _aggregate_one(name, projects)
        result[name] = {"label": CATALOG[name].label, "value": value, "detail": detail}
    return result
