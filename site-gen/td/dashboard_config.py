"""대시보드 설정 파일(dashboard.yaml) 로더, 지표 카탈로그, 값 표시 형식(설계 §6.2).

구성:
  1. 지표 카탈로그와 열·탭 식별자
  2. 데이터 클래스
  3. 로딩과 검증(스키마 + 등록 규칙 + 카탈로그 대조)
  4. 설정 선택(resolve)과 암묵 과제
  5. 값 표시 형식
  6. 상태 판정, 결론 문장, 규칙 각주
오류 메시지는 `<키 경로>: <사유>` 형식이다.
"""
from __future__ import annotations

import copy
import json
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).parent / "schemas" / "dashboard.schema.json"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]*)\}")


class ConfigError(Exception):
    """설정 오류. 메시지는 `<키 경로>: <사유>`."""


# --- 1. 지표 카탈로그 -------------------------------------------------------------------

@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    unit: str    # ratio|percent|count|seconds|score|string|bool|list|gate
    scope: str   # run|snapshot|both|aggregate


def _metrics(*rows: tuple[str, str, str, str]) -> dict[str, Metric]:
    return {name: Metric(name, label, unit, scope) for name, label, unit, scope in rows}


CATALOG: dict[str, Metric] = _metrics(
    # run에서 오는 과제 지표
    ("tests.passRate", "테스트 통과율", "ratio", "run"),
    ("coverage.line", "라인 커버리지", "ratio", "run"),
    ("coverage.aggregateLine", "누적 라인 커버리지", "ratio", "run"),
    ("e2e.passRate", "E2E 통과율", "ratio", "run"),
    ("hotspot.topScore", "핫스팟 최고 점수", "score", "run"),
    ("hotspot.topName", "핫스팟 1위", "string", "run"),
    ("tia.selectedRatio", "TIA 선택 비율", "ratio", "run"),
    ("run.durationSec", "run 소요 시간", "seconds", "run"),
    # run과 스냅숏 양쪽에서 올 수 있는 과제 지표(한 과제에서는 한 출처뿐)
    ("sonar.gate", "Sonar 게이트", "gate", "both"),
    ("sonar.coverage", "Sonar 커버리지", "percent", "both"),
    ("sonar.vulnerabilities", "Sonar 취약점", "count", "both"),
    ("sonar.bugs", "Sonar 버그", "count", "both"),
    ("sonar.codeSmells", "Sonar 코드 스멜", "count", "both"),
    # 수집 스냅숏에서 오는 과제 지표
    ("ci.runs", "CI 실행 수", "count", "snapshot"),
    ("ci.successes", "CI 성공 수", "count", "snapshot"),
    ("ci.failures", "CI 실패 수", "count", "snapshot"),
    ("ci.successRate", "CI 성공률", "ratio", "snapshot"),
    ("ci.lastFailed", "최근 CI 실패", "bool", "snapshot"),
    ("ci.failedChecks", "실패한 검사 수", "count", "snapshot"),
    ("ci.failedCheckNames", "실패한 검사 이름", "list", "snapshot"),
    ("repo.pushedAt", "최근 푸시", "string", "snapshot"),
    ("repo.language", "주 언어", "string", "snapshot"),
    ("repo.description", "저장소 설명", "string", "snapshot"),
    # 집계 지표(home.summary에만 쓴다)
    ("ci.successRateAll", "전체 CI 성공률", "ratio", "aggregate"),
    ("sonar.gatePassCount", "Sonar 게이트 통과", "string", "aggregate"),
    ("sonar.coverageNonZeroCount", "Sonar 커버리지 측정", "string", "aggregate"),
    ("status.noneCount", "측정 없음 과제 수", "count", "aggregate"),
)

COLUMN_IDS: tuple[str, ...] = (
    "status", "project", "why", "ci.successRate", "sonar.gate",
    "sonar.coverage", "sonar.issues", "ci.history", "repo.pushedAt",
)
TAB_IDS: tuple[str, ...] = (
    "overview", "trend", "tests", "coverage", "hotspot", "quality", "generation", "runs",
)


# --- 2. 데이터 클래스 -------------------------------------------------------------------

@dataclass(frozen=True)
class Project:
    name: str
    repo: str | None
    sonar_key: str | None
    sut: str | None
    implicit: bool = False


@dataclass(frozen=True)
class Config:
    projects: tuple[Project, ...]
    status: dict
    home: dict
    project: dict
    path: Path | None


# --- 3. 로딩과 검증 ---------------------------------------------------------------------

def _key_path(parts: Iterable) -> str:
    text = ""
    for part in parts:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text or "<root>"


def _check_schema(data) -> None:
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    errors = sorted(validator.iter_errors(data), key=lambda err: [str(part) for part in err.absolute_path])
    if errors:
        raise ConfigError("; ".join(f"{_key_path(err.absolute_path)}: {err.message}" for err in errors))


def _check_projects(projects: list[dict], suts_dir: Path) -> None:
    seen_names: dict[str, int] = {}
    seen_repos: dict[str, int] = {}
    seen_suts: dict[str, int] = {}
    for index, project in enumerate(projects):
        name = project["name"]
        where = f"projects[{index}]"
        if not NAME_PATTERN.match(name) or ".." in name:
            raise ConfigError(f"{where}.name: 과제 이름은 {NAME_PATTERN.pattern} 이어야 하고 '..'를 포함할 수 없다: {name!r}")
        if name.lower() in seen_names:
            raise ConfigError(f"{where}.name: 대소문자를 무시하면 projects[{seen_names[name.lower()]}]와 같은 이름이다: {name!r}")
        seen_names[name.lower()] = index
        repo = project.get("repo")
        if repo is not None:
            if repo in seen_repos:
                raise ConfigError(f"{where}.repo: projects[{seen_repos[repo]}]와 같은 repo다: {repo!r}")
            seen_repos[repo] = index
        sut = project.get("sut")
        if sut is not None:
            if not NAME_PATTERN.match(sut) or ".." in sut or not (suts_dir / sut / "sut.yaml").is_file():
                raise ConfigError(f"{where}.sut: {suts_dir / sut / 'sut.yaml'} 파일이 없다: {sut!r}")
            if sut in seen_suts:
                raise ConfigError(f"{where}.sut: projects[{seen_suts[sut]}]가 이미 가리키는 sut다: {sut!r}")
            seen_suts[sut] = index


def _check_metric(name: str, where: str, allowed_scopes: tuple[str, ...], role: str) -> None:
    metric = CATALOG.get(name)
    if metric is None:
        raise ConfigError(f"{where}: 지표 카탈로그에 없는 이름이다: {name!r}")
    if metric.scope not in allowed_scopes:
        raise ConfigError(f"{where}: {role}에 쓸 수 없는 지표다(scope={metric.scope}): {name!r}")


PROJECT_SCOPES = ("run", "snapshot", "both")


def _check_condition(condition: dict, where: str) -> None:
    if "all" in condition:
        for index, child in enumerate(condition["all"]):
            _check_condition(child, f"{where}.all[{index}]")
    else:
        _check_metric(condition["metric"], f"{where}.metric", PROJECT_SCOPES, "판정 조건")


def _check_placeholders(text: str, where: str) -> None:
    for name in PLACEHOLDER_PATTERN.findall(text):
        _check_metric(name, where, PROJECT_SCOPES, "문구 치환")


def _check_catalog(data: dict) -> None:
    status, home, project = data["status"], data["home"], data["project"]
    for index, name in enumerate(status["none"]["allMissing"]):
        _check_metric(name, f"status.none.allMissing[{index}]", PROJECT_SCOPES, "측정 없음 판정")
    for index, rule in enumerate(status["rules"]):
        _check_condition(rule["when"], f"status.rules[{index}].when")
        _check_placeholders(rule["reason"], f"status.rules[{index}].reason")
    for index, name in enumerate(home["summary"]):
        _check_metric(name, f"home.summary[{index}]", ("aggregate",), "요약")
    for index, name in enumerate(home["columns"]):
        if name not in COLUMN_IDS:
            raise ConfigError(f"home.columns[{index}]: 알 수 없는 열 식별자다: {name!r}")
    for index, name in enumerate(project["tabs"]):
        if name not in TAB_IDS:
            raise ConfigError(f"project.tabs[{index}]: 알 수 없는 탭 식별자다: {name!r}")
    for index, name in enumerate(project["trend"]["run"]):
        _check_metric(name, f"project.trend.run[{index}]", ("run", "both"), "run 시계열")
    for index, name in enumerate(project["trend"]["snapshot"]):
        _check_metric(name, f"project.trend.snapshot[{index}]", ("snapshot", "both"), "스냅숏 시계열")
    for index, headline in enumerate(project["headline"]):
        if "when" in headline:
            _check_condition(headline["when"], f"project.headline[{index}].when")
        _check_placeholders(headline["text"], f"project.headline[{index}].text")


def _defaults() -> dict:
    """설계 §6.2 예시의 status·home·project 값. 저장소 루트 dashboard.yaml과 같은 내용이다."""
    return {
        "status": {
            "order": ["crit", "warn", "none", "good"],
            "labels": {"crit": "위험", "warn": "주의", "good": "양호", "none": "측정 없음"},
            "none": {"allMissing": ["ci.runs", "sonar.gate", "tests.passRate"]},
            "rules": [
                {"level": "crit", "when": {"metric": "sonar.gate", "op": "eq", "value": "ERROR"},
                 "reason": "Sonar 품질 게이트 실패"},
                {"level": "crit", "when": {"metric": "ci.lastFailed", "op": "eq", "value": True},
                 "reason": "기본 브랜치의 최근 CI 실패"},
                {"level": "crit", "when": {"metric": "ci.failedChecks", "op": "gt", "value": 0},
                 "reason": "최신 커밋의 검사 실패: {ci.failedCheckNames}"},
                {"level": "warn",
                 "when": {"all": [{"metric": "ci.runs", "op": "ge", "value": 5},
                                  {"metric": "ci.successRate", "op": "lt", "value": 0.9}]},
                 "reason": "최근 CI {ci.runs}회 중 {ci.failures}회 실패"},
                {"level": "warn", "when": {"metric": "sonar.vulnerabilities", "op": "gt", "value": 0},
                 "reason": "Sonar 취약점 {sonar.vulnerabilities}건"},
            ],
        },
        "home": {
            "summary": ["ci.successRateAll", "sonar.gatePassCount", "sonar.coverageNonZeroCount", "status.noneCount"],
            "columns": ["status", "project", "why", "ci.successRate", "sonar.gate", "sonar.coverage",
                        "sonar.issues", "ci.history", "repo.pushedAt"],
        },
        "project": {
            "tabs": list(TAB_IDS),
            "trend": {
                "run": ["tests.passRate", "coverage.line", "coverage.aggregateLine", "e2e.passRate",
                        "sonar.coverage", "sonar.vulnerabilities", "sonar.bugs", "hotspot.topScore",
                        "tia.selectedRatio", "run.durationSec"],
                "snapshot": ["ci.successRate", "sonar.coverage", "sonar.vulnerabilities", "sonar.bugs"],
            },
            "headline": [
                {"when": {"all": [{"metric": "tests.passRate", "op": "eq", "value": 1},
                                  {"metric": "coverage.line", "op": "lt", "value": 0.5}]},
                 "text": "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 {coverage.line}입니다"},
                {"text": "판정 규칙에 걸린 항목이 없습니다"},
            ],
        },
    }


def load(path: Path, suts_dir: Path) -> Config:
    """설정 파일을 읽어 스키마, 과제 등록 규칙, 카탈로그 대조를 모두 통과시킨 `Config`를 돌려준다."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigError(f"{path}: 읽을 수 없다: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML 파싱 실패: {exc}") from exc
    try:
        _check_schema(data)
        data = {**_defaults(), **data}      # 생략한 최상위 구역은 기본값
        data["project"].setdefault("headline", [])
        _check_projects(data["projects"], Path(suts_dir))
        _check_catalog(data)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    return Config(
        projects=tuple(
            Project(item["name"], item.get("repo"), item.get("sonarKey"), item.get("sut"))
            for item in data["projects"]),
        status=data["status"], home=data["home"], project=data["project"], path=path)


# --- 4. 설정 선택과 암묵 과제 -----------------------------------------------------------

def empty() -> Config:
    """과제가 없는 설정. status·home·project는 설계 §6.2 예시 값."""
    defaults = copy.deepcopy(_defaults())
    return Config((), defaults["status"], defaults["home"], defaults["project"], None)


def resolve(env: Mapping[str, str], repo_root: Path) -> Config:
    """환경에 맞는 설정을 고른다. TD_DASHBOARD_CONFIG, 없으면 TD_SITE_PREFIX(빈 설정), 없으면 저장소 루트."""
    repo_root = Path(repo_root)
    if env.get("TD_DASHBOARD_CONFIG"):
        suts_dir = Path(env.get("TD_DASHBOARD_SUTS_DIR") or repo_root / "suts")
        return load(Path(env["TD_DASHBOARD_CONFIG"]), suts_dir)
    if env.get("TD_SITE_PREFIX"):
        return empty()
    return load(repo_root / "dashboard.yaml", repo_root / "suts")


def with_implicit(cfg: Config, suts_with_runs: Iterable[str]) -> Config:
    """어느 과제에도 이어지지 않은 SUT를 암묵 과제로 더한다. 이름이 겹치면 `ConfigError`."""
    linked = {project.sut for project in cfg.projects if project.sut}
    taken = {project.name.lower(): index for index, project in enumerate(cfg.projects)}
    added = []
    for sut in sorted(set(suts_with_runs) - linked):
        if sut.lower() in taken:
            raise ConfigError(
                f"projects[{taken[sut.lower()]}].name: 완료된 run이 있는 미등록 SUT와 이름이 겹친다: {sut!r}")
        added.append(Project(name=sut, repo=None, sonar_key=None, sut=sut, implicit=True))
    return Config(cfg.projects + tuple(added), cfg.status, cfg.home, cfg.project, cfg.path)


# --- 5. 값 표시 형식 --------------------------------------------------------------------

def _format_seconds(value) -> str:
    total = round(value)
    minutes, seconds = divmod(total, 60)
    return f"{minutes}분 {seconds}초" if minutes else f"{seconds}초"


def format_value(metric: str, value) -> str:
    """지표 값을 화면 문자열로 바꾼다. 값이 없으면 `—`."""
    if value is None:
        return "—"
    unit = CATALOG[metric].unit
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    if unit == "percent":
        return f"{float(value):.1f}%"
    if unit == "count":
        return str(int(value))
    if unit == "seconds":
        return _format_seconds(float(value))
    if unit == "score":
        return f"{float(value):.1f}"
    if unit == "gate":
        return {"OK": "통과", "ERROR": "실패"}.get(value, str(value))
    if unit == "bool":
        return "예" if value else "아니오"
    if unit == "list":
        return ", ".join(str(item) for item in value)
    return str(value)


# --- 6. 상태 판정, 결론 문장, 규칙 각주 ---------------------------------------------------

OPERATORS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
             "le": operator.le, "gt": operator.gt, "ge": operator.ge}
OPERATOR_SYMBOLS = {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}
HEADLINE_NO_METRICS = "측정된 지표가 없습니다"


@dataclass(frozen=True)
class Verdict:
    level: str
    reasons: tuple[str, ...]
    partial: bool


def _holds(condition: dict, values: Mapping[str, object]) -> bool:
    """조건이 참인가. 값이 없거나 비교할 수 없는 타입이면 거짓."""
    if "all" in condition:
        return all(_holds(child, values) for child in condition["all"])
    actual = values.get(condition["metric"])
    if actual is None:
        return False
    try:
        return bool(OPERATORS[condition["op"]](actual, condition["value"]))
    except TypeError:
        return False


def _substitute(text: str, values: Mapping[str, object]) -> str | None:
    """`{지표}`를 표시 형식의 값으로 바꾼다. 치환할 값이 하나라도 없으면 None."""
    missing = False

    def replace(match: re.Match) -> str:
        nonlocal missing
        value = values.get(match.group(1))
        if value is None:
            missing = True
            return ""
        return format_value(match.group(1), value)

    result = PLACEHOLDER_PATTERN.sub(replace, text)
    return None if missing else result


def evaluate(values: Mapping[str, object], cfg: Config, *, has_repo: bool = True) -> Verdict:
    """설계 §6.2 "상태 판정 순서"대로 판정한다."""
    status = cfg.status
    all_missing = status["none"]["allMissing"]
    if all_missing and all(values.get(name) is None for name in all_missing):
        return Verdict("none", (), False)
    order = status["order"]
    fired = []
    for rule in status["rules"]:
        if not _holds(rule["when"], values):
            continue
        reason = _substitute(rule["reason"], values)
        if reason is not None:
            fired.append((order.index(rule["level"]), rule["level"], reason))
    partial = has_repo and (values.get("ci.runs") is None) != (values.get("sonar.gate") is None)
    if not fired:
        return Verdict("good", (), partial)
    return Verdict(min(fired)[1], tuple(reason for _, _, reason in fired), partial)


def headline(values: Mapping[str, object], verdict: Verdict, cfg: Config) -> str:
    """과제 페이지의 결론 문장."""
    if verdict.level in ("crit", "warn"):
        return f"{cfg.status['labels'][verdict.level]}: {' · '.join(verdict.reasons)}"
    if verdict.level == "none":
        return HEADLINE_NO_METRICS
    for item in cfg.project["headline"]:
        if "when" in item and not _holds(item["when"], values):
            continue
        text = _substitute(item["text"], values)
        if text is not None:
            return text
    return ""


def _condition_text(condition: dict) -> str:
    if "all" in condition:
        return " 그리고 ".join(_condition_text(child) for child in condition["all"])
    metric = condition["metric"]
    return f"{CATALOG[metric].label} {OPERATOR_SYMBOLS[condition['op']]} {format_value(metric, condition['value'])}"


def rules_text(cfg: Config) -> list[str]:
    """각주: 수준마다 한 줄. 규칙이 없는 수준은 줄이 없다."""
    lines = []
    for level in cfg.status["order"]:
        conditions = [_condition_text(rule["when"]) for rule in cfg.status["rules"] if rule["level"] == level]
        if conditions:
            lines.append(f"{cfg.status['labels'][level]}: {' / '.join(conditions)}")
    return lines
