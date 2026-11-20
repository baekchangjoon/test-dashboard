"""S12 판정(설계 §6.12, 사전 등록 기준, REQ-042). 순수 함수만 둔다(입력은 arm별 generation 지표 목록).

- 생성 가설 **성립**: 최소 한 온톨로지 arm(`base` 아닌 arm)의 평균이 compile >= 0.90, undefined <= 0.10, pass >= 0.70,
  endpoint >= 0.80을 모두 만족한다(경계 포함). 온톨로지 arm이 모두 미달이면 **불성립**, 측정된 온톨로지 arm이 없으면 **판정 불가**.
- 온톨로지 **효과 있음**: 한 온톨로지 arm이 endpoint, branch, oracle 중 하나 이상에서 `base` 범위 [min,max]와 겹치지 않으면서
  더 높다(arm.min > base.max). 겹치거나(경계 접촉 포함) 낮으면 **차이 불명확**, base나 온톨로지 arm이 없으면 **판정 불가**.
- 모든 결과에 "탐색적 관찰" 꼬리표를 붙인다(표본 3회).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

BASE_ARM = "base"
EFFECT_METRICS = ("endpoint", "branch", "oracle")
# 이름 -> (비교, 기준값). `compile`은 컴파일 가능 비율, `passed`는 통과율이다.
THRESHOLDS: dict[str, tuple[str, float]] = {
    "compile": (">=", 0.90),
    "undefined": ("<=", 0.10),
    "passed": (">=", 0.70),
    "endpoint": (">=", 0.80),
}
GENERATION_OK, GENERATION_NO, UNDECIDABLE = "성립", "불성립", "판정 불가"
EFFECT_YES, EFFECT_UNCLEAR = "효과 있음", "차이 불명확"
EXPLORATORY = "탐색적 관찰"
_EPSILON = 1e-12  # 0.1 같은 경계값의 부동소수 오차를 흡수한다


@dataclass
class ArmStats:
    """arm 하나의 generation별 지표. metrics[이름] = generation 값 목록(측정 안 된 generation은 넣지 않는다)."""

    status: str = "ok"  # ok | skipped
    metrics: dict[str, list[float]] = field(default_factory=dict)
    reason: str | None = None

    def values(self, name: str) -> list[float]:
        return [value for value in self.metrics.get(name, []) if value is not None]

    def mean(self, name: str) -> float | None:
        values = self.values(name)
        return math.fsum(values) / len(values) if values else None

    def low(self, name: str) -> float | None:
        return min(self.values(name), default=None)

    def high(self, name: str) -> float | None:
        return max(self.values(name), default=None)

    @property
    def measured(self) -> bool:
        """skip가 아니고, 판정 지표가 하나라도 측정됐다."""
        return self.status == "ok" and any(self.values(name) for name in {*THRESHOLDS, *EFFECT_METRICS})


@dataclass
class Verdict:
    generation: str
    effect: str
    exploratory_label: str = EXPLORATORY
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"generation": self.generation, "effect": self.effect, "label": self.exploratory_label, "detail": self.detail}


def _meets(name: str, mean: float | None) -> bool:
    if mean is None:
        return False
    op, limit = THRESHOLDS[name]
    return mean >= limit - _EPSILON if op == ">=" else mean <= limit + _EPSILON


def _generation(ontology: dict[str, ArmStats]) -> tuple[str, dict]:
    checks = {}
    for name, stats in ontology.items():
        per_metric = {metric: {"mean": stats.mean(metric), "ok": _meets(metric, stats.mean(metric))} for metric in THRESHOLDS}
        checks[name] = {"passed": all(item["ok"] for item in per_metric.values()), "metrics": per_metric}
    passing = [name for name, check in checks.items() if check["passed"]]
    if not ontology:
        return UNDECIDABLE, {"armChecks": checks, "passingArms": passing, "thresholds": _threshold_doc()}
    return (GENERATION_OK if passing else GENERATION_NO), {"armChecks": checks, "passingArms": passing, "thresholds": _threshold_doc()}


def _threshold_doc() -> dict:
    return {name: f"{op} {limit:.2f}" for name, (op, limit) in THRESHOLDS.items()}


def _relation(arm: ArmStats, base: ArmStats, metric: str) -> str:
    """base 범위와의 관계: higher(분리되어 더 높음) | lower(분리되어 더 낮음) | overlap | missing."""
    arm_low, arm_high, base_low, base_high = arm.low(metric), arm.high(metric), base.low(metric), base.high(metric)
    if None in (arm_low, arm_high, base_low, base_high):
        return "missing"
    if arm_low > base_high:
        return "higher"
    if arm_high < base_low:
        return "lower"
    return "overlap"


def _effect(base: ArmStats | None, ontology: dict[str, ArmStats]) -> tuple[str, dict]:
    if base is None or not ontology:
        return UNDECIDABLE, {"metrics": {}, "reason": "base 또는 온톨로지 arm이 없다"}
    relations = {name: {metric: _relation(stats, base, metric) for metric in EFFECT_METRICS} for name, stats in ontology.items()}
    effective = [name for name, per_metric in relations.items() if "higher" in per_metric.values()]
    return (EFFECT_YES if effective else EFFECT_UNCLEAR), {"metrics": relations, "effectiveArms": effective}


def judge(arms: dict[str, ArmStats]) -> Verdict:
    """arm 이름 -> ArmStats로 판정한다. `base`가 비교 기준이고, 나머지(jqa, owl)가 온톨로지 arm이다."""
    base = arms.get(BASE_ARM)
    base = base if base is not None and base.measured else None
    ontology = {name: stats for name, stats in arms.items() if name != BASE_ARM and stats.measured}
    generation, generation_detail = _generation(ontology)
    effect, effect_detail = _effect(base, ontology)
    skipped = {name: stats.reason for name, stats in arms.items() if not stats.measured}
    return Verdict(generation, effect, EXPLORATORY, {"generation": generation_detail, "effect": effect_detail, "unmeasuredArms": skipped})
