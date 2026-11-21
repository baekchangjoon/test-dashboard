"""dashboard.yaml 수용 테스트(Unit): REQ-076(스키마), REQ-077(과제 등록), REQ-078(카탈로그 대조)."""
import copy
import re
from pathlib import Path

import pytest
import yaml

from td import dashboard_config
from td.dashboard_config import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]
SUTS_DIR = REPO_ROOT / "suts"


def base_config() -> dict:
    """저장소 루트 설정에서 과제만 비운 기준 설정."""
    data = yaml.safe_load((REPO_ROOT / "dashboard.yaml").read_text())
    data["projects"] = []
    return data


def write(tmp_path: Path, body) -> Path:
    path = tmp_path / "dashboard.yaml"
    path.write_text(body if isinstance(body, str) else yaml.safe_dump(body, sort_keys=False, allow_unicode=True))
    return path


def with_projects(*projects: dict) -> dict:
    data = base_config()
    data["projects"] = list(projects)
    return data


def one_project(**fields) -> dict:
    return with_projects(fields)


def mutated(mutate) -> dict:
    data = copy.deepcopy(base_config())
    mutate(data)
    return data


CASES_076 = [
    ({"schema": 1}, "projects"),                                   # projects 키 없음
    (mutated(lambda data: data.update(schema=2)), "schema"),       # schema가 1이 아님
    (mutated(lambda data: data["status"].update(rules="x")), "status.rules"),   # 타입 오류
    (mutated(lambda data: data.update(extra=1)), "extra"),         # 모르는 키
    (mutated(lambda data: data["status"]["rules"][0]["when"].update(extra=1)), "status.rules[0].when"),
    ("projects: [", "YAML"),                                       # 문법 오류
    ("- 1\n- 2\n", "<root>"),                                      # 최상위가 목록
]

CASES_077 = [
    (with_projects({"name": "Foo"}, {"name": "foo"}), "foo"),
    (with_projects({"name": "a", "repo": "o/r"}, {"name": "b", "repo": "o/r"}), "o/r"),
    (one_project(name="a", sut="nope"), "nope"),
    (with_projects({"name": "a", "sut": "petclinic"}, {"name": "b", "sut": "petclinic"}), "petclinic"),
]


def rule_condition(condition: dict, reason: str = "사유") -> dict:
    return mutated(lambda data: data["status"]["rules"].append({"level": "warn", "when": condition, "reason": reason}))


def RULE_WITH(metric: str) -> dict:
    return rule_condition({"metric": metric, "op": "gt", "value": 0})


def RULE_OP(operator: str) -> dict:
    return rule_condition({"metric": "ci.runs", "op": operator, "value": 0})


def COLUMN(name: str) -> dict:
    return mutated(lambda data: data["home"]["columns"].append(name))


def TAB(name: str) -> dict:
    return mutated(lambda data: data["project"]["tabs"].append(name))


def REASON(text: str) -> dict:
    return rule_condition({"metric": "ci.runs", "op": "gt", "value": 0}, reason=text)


def TREND_SNAPSHOT(name: str) -> dict:
    return mutated(lambda data: data["project"]["trend"]["snapshot"].append(name))


def test_req076_schema_violation_fails(tmp_path):
    for body, where in CASES_076:
        with pytest.raises(ConfigError) as exc:
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
        assert where in str(exc.value)
    with pytest.raises(ConfigError):
        dashboard_config.load(tmp_path / "missing.yaml", SUTS_DIR)


def test_req077_project_registration_rules(tmp_path):
    for name in ("a/b", "..", "bad name", "-p", ".p", "과제", ""):
        with pytest.raises(ConfigError, match="projects"):
            dashboard_config.load(write(tmp_path, one_project(name=name)), SUTS_DIR)
    for body, word in CASES_077:
        with pytest.raises(ConfigError, match=re.escape(word)) as exc:
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
        assert "projects[" in str(exc.value)
    cfg = dashboard_config.load(write(tmp_path, one_project(name="mini")), SUTS_DIR)
    with pytest.raises(ConfigError, match="mini"):
        dashboard_config.with_implicit(cfg, ["mini"])
    with pytest.raises(ConfigError, match="MINI"):
        dashboard_config.with_implicit(cfg, ["MINI"])


def test_req078_unknown_metric_or_operator(tmp_path):
    cases = [(RULE_WITH("ci.nope"), "ci.nope"), (RULE_OP("between"), "between"), (COLUMN("foo"), "foo"),
             (TAB("foo"), "foo"), (REASON("{ci.nope}"), "ci.nope"), (RULE_WITH("ci.successRateAll"), "ci.successRateAll"),
             (COLUMN("status.noneCount"), "status.noneCount"), (TREND_SNAPSHOT("tia.selectedRatio"), "tia.selectedRatio"),
             (mutated(lambda data: data["home"]["summary"].append("ci.runs")), "ci.runs"),
             (mutated(lambda data: data["project"]["trend"]["run"].append("ci.runs")), "ci.runs"),
             (mutated(lambda data: data["project"]["headline"].append({"text": "{ci.nope}"})), "ci.nope"),
             (mutated(lambda data: data["project"]["headline"].insert(
                 0, {"when": {"metric": "ci.nope", "op": "eq", "value": 1}, "text": "x"})), "ci.nope"),
             (mutated(lambda data: data["status"]["none"].update(allMissing=["ci.nope"])), "ci.nope"),
             (rule_condition({"all": [{"metric": "ci.runs", "op": "gt", "value": 0},
                                      {"metric": "ci.nope", "op": "gt", "value": 0}]}), "ci.nope")]
    for body, word in cases:
        with pytest.raises(ConfigError, match=re.escape(word)):
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
    loaded = dashboard_config.load(REPO_ROOT / "dashboard.yaml", REPO_ROOT / "suts")
    assert len(loaded.projects) == 20
    by_name = {project.name: project for project in loaded.projects}
    assert by_name["spring-petclinic"].sut == "petclinic"
    assert by_name["MailosaurDemo"].sonar_key == "MailoSaurDemo"
    assert by_name["VcsStatistics"].sonar_key == "vcsstatistics"


def test_catalog_and_format_value():
    assert dashboard_config.CATALOG["hotspot.topName"].unit == "string"
    assert dashboard_config.CATALOG["ci.runs"].label == "CI 실행 수"
    assert dashboard_config.CATALOG["ci.successRateAll"].scope == "aggregate"
    assert dashboard_config.CATALOG["sonar.coverage"].scope == "both"
    fmt = dashboard_config.format_value
    assert fmt("coverage.line", 0.415) == "41.5%"
    assert fmt("sonar.coverage", 57.14) == "57.1%"
    assert fmt("ci.runs", 5) == "5"
    assert fmt("run.durationSec", 515) == "8분 35초"
    assert fmt("hotspot.topScore", 3.14159) == "3.1"
    assert fmt("sonar.gate", "OK") == "통과" and fmt("sonar.gate", "ERROR") == "실패"
    assert fmt("sonar.gate", "WARN") == "WARN"
    assert fmt("ci.lastFailed", True) == "예" and fmt("ci.lastFailed", False) == "아니오"
    assert fmt("ci.failedCheckNames", ["a", "b"]) == "a, b"
    assert fmt("ci.runs", None) == "—"


def test_empty_resolve_and_implicit(tmp_path):
    cfg = dashboard_config.empty()
    assert cfg.projects == () and cfg.path is None
    assert cfg.status["none"]["allMissing"] == ["ci.runs", "sonar.gate", "tests.passRate"]
    assert dashboard_config.resolve({"TD_SITE_PREFIX": "x"}, tmp_path).projects == ()
    custom = write(tmp_path, one_project(name="mini"))
    resolved = dashboard_config.resolve({"TD_DASHBOARD_CONFIG": str(custom), "TD_DASHBOARD_SUTS_DIR": str(SUTS_DIR)}, tmp_path)
    assert [project.name for project in resolved.projects] == ["mini"]
    assert len(dashboard_config.resolve({}, REPO_ROOT).projects) == 20
    linked = dashboard_config.load(REPO_ROOT / "dashboard.yaml", SUTS_DIR)
    added = dashboard_config.with_implicit(linked, ["petclinic", "mini-sut"])
    assert added.projects[-1] == dashboard_config.Project("mini-sut", None, None, "mini-sut", True)
    assert len(added.projects) == 21
