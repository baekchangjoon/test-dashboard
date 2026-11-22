"""상태 판정 수용 테스트: REQ-081(규칙별 판정), REQ-082(없는 값과 경계), REQ-084(결론 문장 선택), REQ-083(임계값 변경, Int)."""
import html
import json

import pytest

from td import dashboard_config
from dashboard_fixtures import cfg_with, load_cfg, make_site, rebuild_site, set_threshold, snap, status_of

CFG = dashboard_config.empty()
OKCI = {"ci.runs": 9, "ci.successRate": 1.0, "ci.lastFailed": False, "ci.failedChecks": 0}


@pytest.mark.parametrize("values, level, reasons", [
    ({**OKCI, "sonar.gate": "ERROR"}, "crit", ("Sonar 품질 게이트 실패",)),
    ({**OKCI, "sonar.gate": "OK", "ci.lastFailed": True}, "crit", ("기본 브랜치의 최근 CI 실패",)),
    ({**OKCI, "sonar.gate": "OK", "ci.failedChecks": 1, "ci.failedCheckNames": ["build-and-test"]},
     "crit", ("최신 커밋의 검사 실패: build-and-test",)),
    ({"sonar.gate": "OK", "ci.runs": 11, "ci.failures": 6, "ci.successRate": 5 / 11, "ci.lastFailed": False, "ci.failedChecks": 0},
     "warn", ("최근 CI 11회 중 6회 실패",)),
    ({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 8}, "warn", ("Sonar 취약점 8건",)),
    ({**OKCI, "sonar.gate": "ERROR", "sonar.vulnerabilities": 2}, "crit", ("Sonar 품질 게이트 실패", "Sonar 취약점 2건")),
    ({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 0}, "good", ()),
])
def test_req081_rule_levels_and_reasons(values, level, reasons):
    verdict = dashboard_config.evaluate(values, CFG)
    assert (verdict.level, verdict.reasons) == (level, reasons)


def test_req082_missing_and_boundaries():
    ev = lambda v, **kw: dashboard_config.evaluate(v, CFG, **kw)
    ci = lambda runs, fails: {"ci.runs": runs, "ci.failures": fails, "ci.successRate": (runs - fails) / runs,
                              "ci.lastFailed": False, "ci.failedChecks": 0}
    assert ev({}).level == "none" and ev({"ci.runs": None, "sonar.gate": None, "tests.passRate": None}).level == "none"
    pipeline_only = ev({"tests.passRate": 1.0, "coverage.line": 0.9}, has_repo=False)
    assert pipeline_only.level == "good" and pipeline_only.partial is False
    assert ev(ci(4, 3)).level == "good" and ev({**ci(5, 1), "sonar.gate": "OK"}).level == "warn"
    assert ev({**ci(10, 1), "sonar.gate": "OK"}).level == "good" and ev({**ci(10, 2), "sonar.gate": "OK"}).level == "warn"
    assert ev({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 0}).level == "good"
    assert ev({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 1}).level == "warn"
    assert ev({"sonar.gate": "OK"}).level == "good"
    assert ev(ci(4, 0)).partial is True and ev({**ci(4, 0), "sonar.gate": "OK"}).partial is False
    assert ev({"sonar.gate": "OK"}, has_repo=False).partial is False
    # 경계에서 걸린 규칙의 사유도 그 값으로 채워지고, 비교할 수 없는 타입(문자열 "3")은 규칙에 걸리지 않는다
    assert ev({**ci(5, 1), "sonar.gate": "OK"}).reasons == ("최근 CI 5회 중 1회 실패",)
    assert ev({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": "3"}).level == "good"


def test_req084_headline_selection():
    hl = lambda v: dashboard_config.headline(v, dashboard_config.evaluate(v, CFG), CFG)
    assert hl({"sonar.gate": "ERROR", "sonar.vulnerabilities": 2}) == "위험: Sonar 품질 게이트 실패 · Sonar 취약점 2건"
    assert hl({}) == "측정된 지표가 없습니다"
    assert hl({"sonar.gate": "OK", "tests.passRate": 1.0, "coverage.line": 0.415}) == "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 41.5%입니다"
    for rate in (0.97, None):
        assert "모두 통과" not in hl({"sonar.gate": "OK", "tests.passRate": rate, "coverage.line": 0.415})


def test_rules_text_shows_thresholds():
    assert dashboard_config.rules_text(CFG) == [
        "위험: Sonar 게이트 = 실패 / 최근 CI 실패 = 예 / 실패한 검사 수 > 0",
        "주의: CI 실행 수 ≥ 5 그리고 CI 성공률 < 90.0% / Sonar 취약점 > 0",
    ], "규칙이 없는 수준(측정 없음, 양호)은 줄이 없다"


def test_req083_threshold_change_changes_verdict(tmp_path):
    site = make_site(tmp_path, snapshots={"p": [snap(ci_runs=25, ci_successes=23, sonar={"gate": "OK", "vulnerabilities": 0})]},
                     config=cfg_with(plain="p"))
    rebuild_site(site)
    assert status_of(site, "p") == "good"
    rebuild_site(site, set_threshold(load_cfg(site), "ci.successRate", 0.95))
    rules = json.loads((site / "projects.json").read_text())["rules"]
    warn_line = next(line for line in rules if line.startswith("주의"))
    assert status_of(site, "p") == "warn" and "95.0%" in warn_line and "90.0%" not in warn_line
    # 홈 각주는 HTML이라 "<"가 "&lt;"로 적힌다. 글자로 되돌려 비교한다.
    assert warn_line in html.unescape((site / "index.html").read_text())
    page = (site / "projects/p/index.html").read_text()
    assert "주의: 최근 CI 25회 중 2회 실패" in html.unescape(page)
