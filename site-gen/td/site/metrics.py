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
        snapshots, dropped = load_snapshots(base / "projects" / project.name) if project.repo else ([], [])
        latest_snapshot = snapshots[-1] if snapshots else None
        if project.repo is not None and (latest_snapshot is None or latest_snapshot.get("visibility") != "public"):
            continue    # repo가 있는 과제는 최신 유효 스냅숏이 공개일 때만 그린다
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

def series(project: dict, cfg: Config) -> dict:
    """설계 §6.4 `series.json`. 파이프라인 과제는 run 점(runId 순), 그 밖은 스냅숏 점(날짜 순)."""
    if project["pipeline"]:
        names = list(cfg.project["trend"]["run"])
        runs_dir = Path(project["latestRunDir"]).parent
        points = []
        for run in sorted(project["runs"], key=lambda item: item["runId"]):
            run_values = run_metrics(runs_dir / run["runId"])
            points.append({
                "id": run["runId"], "at": run.get("startedAt"),
                "href": f"../../suts/{project['sut']}/runs/{run['runId']}/index.html",
                "values": {name: run_values.get(name) for name in names},
            })
        return {"schema": 1, "kind": "run", "metrics": names, "points": points}
    names = list(cfg.project["trend"]["snapshot"])
    points = []
    for snapshot in project["snapshots"]:
        snap_values = snapshot_metrics(snapshot)
        points.append({"id": snapshot["date"], "at": snapshot.get("collectedAt"),
                       "values": {name: snap_values.get(name) for name in names}})
    return {"schema": 1, "kind": "snapshot", "metrics": names, "points": points}


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
