"""상태 판정 수용 테스트(Unit): REQ-081(규칙별 판정), REQ-082(없는 값과 경계), REQ-084(결론 문장 선택)."""
import pytest

from td import dashboard_config

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


def test_req084_headline_selection():
    hl = lambda v: dashboard_config.headline(v, dashboard_config.evaluate(v, CFG), CFG)
    assert hl({"sonar.gate": "ERROR", "sonar.vulnerabilities": 2}) == "위험: Sonar 품질 게이트 실패 · Sonar 취약점 2건"
    assert hl({}) == "측정된 지표가 없습니다"
    assert hl({"sonar.gate": "OK", "tests.passRate": 1.0, "coverage.line": 0.415}) == "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 41.5%입니다"
    for rate in (0.97, None):
        assert "모두 통과" not in hl({"sonar.gate": "OK", "tests.passRate": rate, "coverage.line": 0.415})


def test_rules_text_shows_thresholds():
    lines = dashboard_config.rules_text(CFG)
    assert "주의: CI 실행 수 ≥ 5 그리고 CI 성공률 < 90.0% / Sonar 취약점 > 0" in lines
    assert lines[0].startswith("위험: Sonar 게이트 = 실패")
