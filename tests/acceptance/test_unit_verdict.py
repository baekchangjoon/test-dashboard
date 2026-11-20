"""REQ-042: 판정 함수(설계 §6.12 사전 등록 기준) 단위 테스트. 모든 경계값을 고정 fixture로 검증한다."""
import pytest

from td import verdict
from td.verdict import ArmStats

GOOD = dict(compile=[0.95, 0.97, 0.99], undefined=[0.0, 0.02, 0.05], passed=[0.75, 0.8, 0.85], endpoint=[0.85, 0.9, 0.95],
            branch=[0.30, 0.32, 0.34], oracle=[0.5, 0.6, 0.7])
BASE_LOW = dict(compile=[0.95, 0.96, 0.97], undefined=[0.0, 0.0, 0.0], passed=[0.7, 0.72, 0.74], endpoint=[0.4, 0.45, 0.5],
                branch=[0.10, 0.12, 0.14], oracle=[0.1, 0.2, 0.3])


def arm(**overrides) -> ArmStats:
    return ArmStats(status="ok", metrics={**GOOD, **overrides})


def base_arm(**overrides) -> ArmStats:
    return ArmStats(status="ok", metrics={**BASE_LOW, **overrides})


def test_req042_verdict_rules():
    # 1) 성립 + 효과 있음: 온톨로지 arm이 모든 기준을 넘고 엔드포인트 범위가 base와 겹치지 않으며 더 높다
    result = verdict.judge({"base": base_arm(), "jqa": arm(), "owl": ArmStats(status="skipped", reason="S05 skipped")})
    assert (result.generation, result.effect) == ("성립", "효과 있음")
    assert result.exploratory_label == "탐색적 관찰"
    assert "jqa" in result.detail["generation"]["passingArms"] and "owl" not in result.detail["generation"]["passingArms"]
    assert result.detail["effect"]["metrics"]["jqa"]["endpoint"] == "higher"

    # 2) 불성립: 온톨로지 arm 모두 기준 하나라도 미달(통과율 0.69). 효과 판정은 별개로 계산된다
    result = verdict.judge({"base": base_arm(), "jqa": arm(passed=[0.69, 0.69, 0.69])})
    assert result.generation == "불성립"
    assert result.detail["generation"]["armChecks"]["jqa"]["passed"] is False

    # 3) 범위 겹침: 엔드포인트, 브랜치, 오라클 모두 base 범위와 겹침 -> 차이 불명확
    overlapping = arm(endpoint=[0.45, 0.99, 0.99], branch=[0.11, 0.2, 0.3], oracle=[0.25, 0.6, 0.7])
    result = verdict.judge({"base": base_arm(), "jqa": overlapping})
    assert (result.generation, result.effect) == ("성립", "차이 불명확")

    # 4) arm skip: base가 없거나 온톨로지 arm이 모두 skip이면 판정 불가
    result = verdict.judge({"base": ArmStats(status="skipped", reason="x"), "jqa": arm()})
    assert (result.generation, result.effect) == ("성립", "판정 불가")
    result = verdict.judge({"base": base_arm(), "jqa": ArmStats(status="skipped", reason="x"), "owl": ArmStats(status="skipped")})
    assert (result.generation, result.effect) == ("판정 불가", "판정 불가")
    assert verdict.judge({}) .generation == "판정 불가"
    assert verdict.judge({"base": base_arm()}).effect == "판정 불가"


@pytest.mark.parametrize("metric,good,bad", [
    ("compile", 0.90, 0.8999), ("undefined", 0.10, 0.1001), ("passed", 0.70, 0.6999), ("endpoint", 0.80, 0.7999)])
def test_req042_threshold_boundaries(metric, good, bad):
    """기준값 경계: compile >= 0.90, undefined <= 0.10, pass >= 0.70, endpoint >= 0.80(평균 기준, 경계 포함)."""
    assert verdict.judge({"base": base_arm(), "jqa": arm(**{metric: [good]})}).generation == "성립"
    assert verdict.judge({"base": base_arm(), "jqa": arm(**{metric: [bad]})}).generation == "불성립"


def test_req042_mean_not_min_decides_generation():
    """생성 가설은 arm의 평균으로 판정한다: 한 generation이 기준 아래여도 평균이 넘으면 성립이다."""
    assert verdict.judge({"base": base_arm(), "jqa": arm(endpoint=[0.70, 0.95, 0.95])}).generation == "성립"


def test_req042_effect_needs_disjoint_and_higher_on_one_metric():
    base = base_arm(endpoint=[0.4, 0.5], branch=[0.10, 0.20], oracle=[0.3, 0.4])
    # 분리돼 있지만 더 낮은 것은 효과가 아니다
    lower = arm(endpoint=[0.1, 0.2], branch=[0.01, 0.02], oracle=[0.0, 0.1])
    assert verdict.judge({"base": base, "jqa": lower}).effect == "차이 불명확"
    # 경계 접촉(min == base max)은 겹침이다
    touching = arm(endpoint=[0.5, 0.9], branch=[0.20, 0.3], oracle=[0.4, 0.5])
    assert verdict.judge({"base": base, "jqa": touching}).effect == "차이 불명확"
    # 오라클 하나에서만 분리돼 높아도 효과 있음
    only_oracle = arm(endpoint=[0.45, 0.9], branch=[0.15, 0.3], oracle=[0.41, 0.5])
    result = verdict.judge({"base": base, "jqa": only_oracle})
    assert result.effect == "효과 있음" and result.detail["effect"]["metrics"]["jqa"]["oracle"] == "higher"
    # 온톨로지 arm이 둘이면 하나라도 효과가 있으면 효과 있음
    assert verdict.judge({"base": base, "jqa": touching, "owl": only_oracle}).effect == "효과 있음"


def test_req042_empty_measured_arm_counts_as_skipped():
    """측정된 generation이 하나도 없는 arm(모두 S06/S07 실패)은 skip과 같게 취급한다."""
    empty = ArmStats(status="ok", metrics={name: [] for name in GOOD})
    assert verdict.judge({"base": base_arm(), "jqa": empty}).generation == "판정 불가"
    assert verdict.judge({"base": empty, "jqa": arm()}).effect == "판정 불가"
