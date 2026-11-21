"""과제 페이지(설계 §5.2, §5.3)와 SUT 안내 페이지 조립. `index.rebuild`가 부른다.

데이터는 `metrics.tab_data`가 미러에서 읽고, 여기서는 화면에 그릴 글자·막대 너비·차트를 정한다.
서버가 모든 탭 구역을 설정 순서대로 HTML로 그리고, `app.js`는 탭 전환과 추이 툴팁만 덧입힌다.
값의 글자는 `dashboard_config.format_value`/`cell_text`로 적어 단위마다 자릿수가 고정된다(멱등).
"""
from __future__ import annotations

import math
from pathlib import Path

from td import dashboard_config
from td.dashboard_config import CATALOG, Config, cell_text, format_value
from td.site import charts, metrics
from td.site.nav import STAGE_LABELS
from td.site.pages import format_duration, json_for_script

TAB_LABELS = {"overview": "한눈에", "trend": "추이", "tests": "테스트", "coverage": "커버리지", "hotspot": "위험 지점",
              "quality": "코드 품질", "generation": "생성 실험", "runs": "실행 이력"}
TAB_QUESTIONS = {
    "overview": "이 과제는 지금 어떤 상태인가", "trend": "지표가 어떻게 변해 왔나",
    "tests": "어떤 테스트가 돌았고 얼마나 통과했나", "coverage": "테스트가 코드의 얼마를 지키는가",
    "hotspot": "어디부터 손봐야 하나", "quality": "정적 분석은 무엇을 말하나",
    "generation": "AI가 만든 테스트는 쓸 만한가", "runs": "언제 무엇이 돌았나",
}
# "이 탭 읽는 법"(시안 project.html의 문구, "추이"는 brief의 문구)
GUIDE_TRENDS = {
    "run": "지표 하나에 차트 하나입니다. 점 하나가 실행 한 번이고, 값이 없는 실행에서는 선이 끊깁니다. 점을 누르면 그 실행으로 갑니다.",
    "snapshot": "지표 하나에 차트 하나입니다. 점 하나가 하루치 수집이고, 값이 없는 날에는 선이 끊깁니다.",
}
GUIDES = {
    "tests": "위는 사람이 관리하는 기존 테스트, 아래는 AI가 생성한 E2E 시나리오입니다. 생성 시나리오의 실패는 제품 결함이 아니라 생성된 테스트의 품질 문제일 수 있습니다.",
    "coverage": "진한 막대는 그 테스트가 직접 실행한 것으로 확인된 코드(귀속), 연한 막대는 준비 과정까지 포함해 실행된 코드(집계)입니다. 둘의 차이가 크면 검증 없이 지나가기만 한 코드가 많다는 뜻입니다.",
    "hotspot": "점수가 높을수록 복잡하고, 최근에 자주 바뀌었고, 테스트가 덜 지키는 코드입니다. 위에서부터 테스트를 보강하면 됩니다.",
    "runs": "한 줄이 한 번의 실행입니다. 작은 칸 14개는 파이프라인 단계이고 비어 있는 칸은 그 실행에서 건너뛴 단계입니다.",
}
GUIDE_QUALITY_TABLE = "게이트는 새로 추가된 위반만 봅니다. 그래서 게이트가 통과여도 이미 쌓여 있는 취약점은 아래 표에 남아 있습니다."
GUIDE_QUALITY_VALUES = "게이트는 새로 추가된 위반만 봅니다. 그래서 게이트가 통과여도 이미 쌓여 있는 취약점은 아래 칸에 남아 있습니다."
SEVERITY_LABELS = {"BLOCKER": "차단", "CRITICAL": "심각", "MAJOR": "주요", "MINOR": "경미", "INFO": "참고"}
ISSUE_TYPE_LABELS = {"VULNERABILITY": ("취약점", "var(--crit)"), "BUG": ("버그", "var(--warn)"),
                     "CODE_SMELL": ("코드 스멜", "var(--accent)")}
STATUS_CLASS = {"passed": "s-good", "degraded": "s-warn", "failed": "s-crit"}
S13_NOTE = "게시 결과는 별도 기록"
SPARK_POINTS = 30


# --- 작은 도우미 --------------------------------------------------------------------------------------

def pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _width(value, top) -> str:
    """막대 너비(%, 소수 1자리). 값이 없으면 0."""
    if value is None or not top:
        return "0.0"
    return f"{max(0.0, min(1.0, value / top)) * 100:.1f}"


def _date_text(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}" if len(compact) == 8 and compact.isdigit() else compact


def _time_text(iso) -> str:
    """`2026-11-20T13:10:22Z` -> `2026-11-20 13:10`. 값이 없으면 "—"."""
    if not isinstance(iso, str) or len(iso) < 16:
        return "—"
    return iso[:16].replace("T", " ")


def _spark(points: list[dict], metric: str) -> dict | None:
    """KPI 칸 아래 작은 추세선(최근 30점). `{"lines": [좌표 문자열], "dot": (x, y)}`. 그릴 값이 없으면 None.
    비율은 0~1, 퍼센트 값은 0~100을 세로 범위로 쓴다. 값이 없는 점에서 선을 끊는다."""
    unit = CATALOG[metric].unit
    scale = {"ratio": 1.0, "percent": 100.0}.get(unit)
    shown = points[-SPARK_POINTS:]
    if scale is None or not shown:
        return None
    count = len(shown)
    lines, current, last = [], [], None
    for position, point in enumerate(shown):
        value = point["values"].get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            if current:
                lines.append(current)
            current = []
            continue
        x = 4 + position * (92 / max(1, count - 1))
        y = 22 - max(0.0, min(1.0, value / scale)) * 18
        last = (f"{x:.1f}", f"{y:.1f}")
        current.append(f"{x:.1f},{y:.1f}")
    if current:
        lines.append(current)
    if last is None:
        return None
    return {"lines": [" ".join(line) for line in lines if len(line) > 1], "dot": last}


def _kpi(metric: str, label: str, project: dict, *, text: str | None = None, sub: str = "", level: str = "",
         spark: dict | None = None) -> dict:
    return {"metric": metric, "label": label, "text": text if text is not None else cell_text(metric, project)[0],
            "sub": sub, "level": level, "spark": spark}


def _gate_level(gate) -> str:
    return {"OK": "s-good", "ERROR": "s-crit"}.get(gate, "") if gate else ""


def _count_level(count) -> str:
    return "" if count is None else ("s-crit" if count > 0 else "s-good")


# --- 탭별 화면 값 -------------------------------------------------------------------------------------

def _stage_view(stages: list[dict], duration_value) -> dict:
    items = []
    for stage in stages:
        status = stage["status"]
        if stage["id"] == "S13" and status is None:
            status_text = S13_NOTE
        else:
            status_text = status or "실행 안 함"
        seconds = stage["sec"]
        items.append({"id": stage["id"], "label": STAGE_LABELS[stage["id"]], "status": status, "statusText": status_text,
                      "css": STATUS_CLASS.get(status, "s-none"), "reason": stage["reason"],
                      "duration": format_duration(seconds) if seconds is not None or stage["id"] != "S13" else "—",
                      "width": f"{max(1.0, math.sqrt((seconds or 0) + 1)):.2f}"})
    troubled = [item["id"] for item in items[:-1] if item["status"] in ("failed", "degraded")]
    measured = [stage for stage in stages[:-1] if stage["sec"] is not None]
    selected = troubled[0] if troubled else (max(measured, key=lambda stage: stage["sec"])["id"] if measured else "S00")
    return {"items": items, "selected": selected, "total": format_duration(duration_value)}


def _overview_view(data: dict, project: dict) -> dict:
    values = project["values"]
    points = data["points"]
    if data["kind"] == "snapshot":
        ci_sub = (f"{values['ci.successes']} / {values['ci.runs']}회"
                  if values.get("ci.runs") and values.get("ci.successes") is not None else "")
        kpis = [
            _kpi("ci.successRate", "CI 성공률", project, sub=ci_sub, spark=_spark(points, "ci.successRate")),
            _kpi("sonar.gate", "Sonar 품질 게이트", project, level=_gate_level(values.get("sonar.gate"))),
            _kpi("sonar.coverage", "Sonar 커버리지", project, spark=_spark(points, "sonar.coverage")),
            _kpi("sonar.vulnerabilities", "열린 취약점", project, level=_count_level(values.get("sonar.vulnerabilities"))),
            _kpi("sonar.bugs", "버그", project),
        ]
        history = data["ciHistory"]
        return {"kind": "snapshot", "kpis": kpis, "history": history,
                "historyFailures": sum(1 for outcome in history if not outcome),
                "historyNote": cell_text("ci.history", project)[0], "pointCount": len(points)}
    pass_rate = values.get("tests.passRate")
    vulnerability_counts = data["vulnerabilityCounts"]
    impact = data["impact"]
    kpis = [
        _kpi("tests.passRate", "기존 테스트 통과율", project,
             sub=f"블랙박스 {data['testsTotal']}개" if data["testsTotal"] is not None else "",
             level="" if pass_rate is None else ("s-good" if pass_rate >= 1 else "s-warn"),
             spark=_spark(points, "tests.passRate")),
        _kpi("coverage.line", "테스트가 지키는 코드(라인)", project,
             sub=(f"실행만 된 코드까지 {format_value('coverage.aggregateLine', values['coverage.aggregateLine'])}"
                  if values.get("coverage.aggregateLine") is not None else ""),
             spark=_spark(points, "coverage.line")),
        _kpi("sonar.gate", "Sonar 품질 게이트", project, level=_gate_level(values.get("sonar.gate"))),
        _kpi("sonar.vulnerabilities", "열린 취약점", project, level=_count_level(values.get("sonar.vulnerabilities")),
             sub=" · ".join(f"{SEVERITY_LABELS[severity]} {vulnerability_counts[severity]}"
                            for severity in ("BLOCKER", "CRITICAL", "MAJOR")) if vulnerability_counts else ""),
        _kpi("tia.selectedRatio", "변경 시 다시 돌릴 테스트", project,
             text=f"{impact['selected']} / {impact['indexedTests']}" if impact else "—",
             sub=f"정밀 선별 {impact['deterministic']}개" if impact and impact["deterministic"] is not None else ""),
    ]
    top = data["top"]
    top_score = max((item.get("score") or 0 for item in top), default=0)
    ring = None
    if impact:
        share = impact["selected"] / impact["indexedTests"]
        circumference = 2 * math.pi * 45
        ring = {"dasharray": f"{circumference:.1f}", "dashoffset": f"{circumference * (1 - share):.1f}",
                "share": pct(share, 0)}
    return {"kind": "run", "kpis": kpis, "top": _hot_rows(top, top_score), "impact": impact, "ring": ring,
            "stages": _stage_view(data["stages"], values.get("run.durationSec")), "reports": data["reports"],
            "runPage": data["runPage"], "hotspotLink": data["hotspotLink"], "tiaLink": data["tiaLink"],
            "pointCount": len(points)}


def _hot_rows(top: list[dict], top_score) -> list[dict]:
    rows = []
    for rank, item in enumerate(top, start=1):
        score = item.get("score") if isinstance(item.get("score"), (int, float)) else None
        rows.append({"rank": rank, "name": str(item.get("name") or item.get("method") or "—"),
                     "file": str(item.get("file") or ""), "score": "—" if score is None else f"{score:.1f}",
                     "width": _width(score, top_score)})
    return rows


def _trend_view(data: dict) -> dict:
    kind, names, points = data["kind"], data["metrics"], data["points"]
    figures = []
    for name in names:
        chart_points = [{"id": point["id"], "at": point.get("at") or "", "href": point.get("href"),
                         "value": point["values"].get(name)} for point in points]
        figures.append({"metric": name, "label": CATALOG[name].label, "svg": charts.trend_svg(CATALOG[name], chart_points)})
    rows = [{"id": point["id"], "idText": point["id"] if kind == "run" else _date_text(point["id"]),
             "at": _time_text(point.get("at")), "href": point.get("href"),
             "cells": [{"metric": name, "text": format_value(name, point["values"].get(name))} for name in names]}
            for point in reversed(points)]
    return {"kind": kind, "figures": figures, "rows": rows,
            "columns": [{"metric": name, "label": CATALOG[name].label} for name in names],
            "guide": GUIDE_TRENDS[kind], "count": len(points), "shown": min(len(points), 30)}


def _tests_view(data: dict) -> dict:
    tests, generations = data["tests"], data["generations"]
    scenario_total = sum(gen["scenarios"] or 0 for gen in generations)
    passed_total = sum(gen["passed"] or 0 for gen in generations)
    arms = sorted({gen["arm"] for gen in generations if gen["arm"]})
    rows = [{**gen, "rateText": pct(gen["rate"]), "passedWidth": _width(gen["passed"], gen["scenarios"]),
             "failedWidth": _width(gen["failed"], gen["scenarios"])} for gen in generations]
    blackbox_sub = [f"통과율 {pct(tests['passRate'], 0)}"]
    if data["attributed"] is not None:
        blackbox_sub.append(f"커버리지가 귀속된 테스트 {data['attributed']}개")
    return {
        "blackbox": {"text": f"{tests['total']}개" if tests["total"] is not None else "—", "sub": " · ".join(blackbox_sub),
                     "level": "" if tests["passRate"] is None else ("s-good" if tests["passRate"] >= 1 else "s-warn")},
        "generated": {"text": f"{scenario_total}개" if generations else "—",
                      "sub": f"방식 {len(arms)}가지 · 묶음 {len(generations)}개" if generations else "생성 묶음 없음"},
        "generatedRate": {"text": pct(passed_total / scenario_total) if scenario_total else "—",
                          "sub": (f"컴파일 실패 {sum(gen['uncompilable'] or 0 for gen in generations)} · "
                                  f"정의 안 된 스텝 {sum(gen['undefined'] or 0 for gen in generations)}") if generations else ""},
        "rows": rows,
    }


def _coverage_view(data: dict) -> dict:
    rows = [{**suite, "lineText": pct(suite["line"]), "aggregateText": pct(suite["aggregate"]),
             "branchText": pct(suite["branch"]), "lineWidth": _width(suite["line"], 1.0),
             "aggregateWidth": _width(suite["aggregate"], 1.0),
             "tcText": "—" if suite["tc"] is None else str(suite["tc"])} for suite in data["suites"]]
    return {"rows": rows, "link": data["link"]}


def _hotspot_view(data: dict) -> dict:
    top = data["top"]
    return {"top": _hot_rows(top, max((item.get("score") or 0 for item in top), default=0)), "link": data["link"]}


def _quality_view(data: dict) -> dict:
    ratings = data["ratings"]

    def rating_sub(kind: str, label: str) -> str:
        return f"{label} 등급 {ratings[kind]}" if ratings.get(kind) else ""
    gate_sub = ""
    if data["conditions"]:
        gate_sub = f"조건 {data['conditions']}개 중 실패 {data['failedConditions']}개"
    values = {"sonar.gate": data["gate"], "sonar.vulnerabilities": data["vulnerabilities"], "sonar.bugs": data["bugs"],
              "sonar.codeSmells": data["codeSmells"], "sonar.coverage": data["coverage"]}
    shown = {"values": values}
    kpis = [
        _kpi("sonar.gate", "품질 게이트", shown, sub=gate_sub, level=_gate_level(data["gate"])),
        _kpi("sonar.vulnerabilities", "취약점", shown, sub=rating_sub("security", "보안"),
             level=_count_level(data["vulnerabilities"])),
        _kpi("sonar.bugs", "버그", shown, sub=rating_sub("reliability", "신뢰성")),
        _kpi("sonar.codeSmells", "코드 스멜", shown, sub=rating_sub("maintainability", "유지보수")),
        _kpi("sonar.coverage", "Sonar 커버리지", shown, sub=f"코드 {data['ncloc']:,}줄" if data["ncloc"] is not None else ""),
    ]
    matrix = None
    if data["issues"] is not None:
        top = max((count for row in data["issues"].values() for count in row.values()), default=0)
        matrix = [{"type": issue_type, "label": ISSUE_TYPE_LABELS[issue_type][0], "cells": [
            {"severity": severity, "count": count, "color": ISSUE_TYPE_LABELS[issue_type][1],
             "heat": f"{(0.25 + 0.75 * count / top) if count and top else 0:.2f}"}
            for severity, count in data["issues"][issue_type].items()]} for issue_type in data["issues"]]
    return {"kpis": kpis, "matrix": matrix, "severities": [(key, SEVERITY_LABELS[key]) for key in SEVERITY_LABELS],
            "issueTotal": data["issueTotal"], "issueFetched": data["issueFetched"], "truncated": data["issuesTruncated"],
            "hotspots": data["hotspots"], "dashboardUrl": data["dashboardUrl"], "link": data.get("link"),
            "guide": GUIDE_QUALITY_TABLE if matrix is not None else GUIDE_QUALITY_VALUES}


def _generation_view(data: dict) -> dict:
    rows = []
    for arm in data["arms"]:
        means, meets = arm["means"], arm["meets"]

        def cell(name: str, text: str) -> dict:
            ok = meets.get(name)
            return {"name": name, "text": text, "css": "" if ok is None else ("ok" if ok else "bad")}
        tokens, seconds = means["tokens"], means["seconds"]
        rows.append({"arm": arm["arm"], "status": arm["status"], "reason": arm["reason"], "cells": [
            cell("scenarios", "—" if means["scenarios"] is None else f"{means['scenarios']:.1f}"),
            cell("compile", pct(means["compile"], 0)), cell("passed", pct(means["passed"])),
            cell("endpoint", pct(means["endpoint"])), cell("line", pct(means["line"])),
            cell("tokens", "—" if tokens is None else f"{round(tokens):,}"),
            cell("seconds", "—" if seconds is None else format_duration(seconds)),
        ]})
    reps = data["reps"]
    guide = (f"코드 구조 정보를 주지 않은 방식(base)과 준 방식 둘(jqa, owl)을 {reps}회씩 돌린 평균입니다. "
             if reps else "코드 구조 정보를 주지 않은 방식(base)과 준 방식 둘(jqa, owl)을 돌린 평균입니다. ")
    guide += "기준을 넘은 칸은 초록, 못 넘은 칸은 빨강입니다."
    return {"generation": data["generation"] or "—", "effect": data["effect"] or "—", "label": data["label"],
            "thresholds": data["thresholds"], "rows": rows, "link": data["link"], "guide": guide}


def _runs_view(data: dict) -> dict:
    rows = []
    for run in data["runs"]:
        values = run["values"]
        rows.append({"id": run["id"], "at": _time_text(run["at"]), "page": run["page"],
                     "stages": [{"id": stage_id, "status": status or "", "css": STATUS_CLASS.get(status, "")}
                                for stage_id, status in zip(metrics.STAGE_IDS, run["stages"])],
                     "passRate": format_value("tests.passRate", values.get("tests.passRate")),
                     "line": format_value("coverage.line", values.get("coverage.line")),
                     "gate": format_value("sonar.gate", values.get("sonar.gate"))})
    return {"rows": rows}


VIEW_BUILDERS = {
    "overview": _overview_view, "trend": lambda data, project: _trend_view(data),
    "tests": lambda data, project: _tests_view(data), "coverage": lambda data, project: _coverage_view(data),
    "hotspot": lambda data, project: _hotspot_view(data), "quality": lambda data, project: _quality_view(data),
    "generation": lambda data, project: _generation_view(data), "runs": lambda data, project: _runs_view(data),
}


# --- 페이지 ------------------------------------------------------------------------------------------

def visible_tabs(cfg: Config, data: dict) -> list[str]:
    """보이는 탭 = 설정의 `project.tabs` 가운데 데이터가 있는 것(설정 순서)."""
    return [tab for tab in cfg.project["tabs"] if data.get(tab) is not None]


def _guide(tab: str, view: dict, kind: str) -> str:
    if tab == "overview":
        unit = "실행" if kind == "run" else "수집"
        count = min(view["pointCount"], SPARK_POINTS)       # KPI 칸은 두 종류 모두 다섯이다
        return (f"위 문장이 결론이고, 아래 다섯 칸이 근거입니다. 칸 아래 작은 선은 최근 {count}회 {unit}의 흐름입니다. "
                "더 알고 싶은 항목은 위 탭에서 들어갑니다.")
    if tab in ("trend", "quality", "generation"):
        return view["guide"]
    return GUIDES[tab]


def render_project(env, project: dict, cfg: Config, base: Path, entry: dict) -> tuple[str, dict]:
    """과제 페이지 HTML과 `series.json` 내용을 돌려준다. entry는 `projects.json`의 그 과제 항목이다."""
    data = metrics.tab_data(project, base, cfg)
    series_doc = metrics.series(project, cfg)
    kind = "run" if project["pipeline"] else "snapshot"
    tabs = []
    for tab in visible_tabs(cfg, data):
        view = VIEW_BUILDERS[tab](data[tab], project)
        tabs.append({"id": tab, "label": TAB_LABELS[tab], "question": TAB_QUESTIONS[tab], "view": view,
                     "guide": _guide(tab, view, kind)})
    overview = data.get("overview") or {}
    stale = project["stale"]
    meta = []
    if project["pipeline"]:
        if overview.get("commit"):
            meta.append(f"커밋 {str(overview['commit'])[:7]}")
        meta.append(f"최근 실행 {_time_text(overview.get('startedAt'))} UTC")
        meta.append(f"실행 {overview.get('runCount', 0)}회")
    elif project["snapshots"]:
        meta.append(f"최근 수집 {_date_text(project['snapshots'][-1]['date'])}")
        meta.append(f"수집 {len(project['snapshots'])}일치")
    html = env.get_template("project.html.j2").render(
        static_href="../../static/v2/", home_href="../../index.html", project=project, tabs=tabs,
        verdict=project["verdict"], headline=project["headline"], meta=" · ".join(meta),
        run_page=overview.get("runPage") if project["pipeline"] else None,
        stale=_date_text(stale) if stale else None,
        data_json=json_for_script({"schema": 1, "project": entry, "series": series_doc}))
    return html, series_doc


def render_landing(env, sut: str, project_name: str | None) -> str:
    """`suts/<sut>/index.html`: 이어진 과제 페이지로 보내는 안내 페이지(링크와 meta refresh가 같은 주소).
    이어진 과제가 그려지지 않았으면(비공개 등) 과제 이름을 쓰지 않고 첫 화면으로 보낸다."""
    target = f"../../projects/{project_name}/index.html" if project_name else "../../index.html"
    return env.get_template("sut.html.j2").render(sut=sut, project_name=project_name, target=target,
                                                  static_href="../../static/v2/")
