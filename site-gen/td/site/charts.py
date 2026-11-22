"""시계열 SVG(설계 §5.3). 서버가 선과 점을 그리고, 스크립트는 툴팁과 강조만 덧입힌다.

- 한 차트에 지표 하나. 최근 `max_points`개 점까지 그린다.
- 값이 없는 점은 선을 끊는다(0으로 잇지 않는다).
- 세로축: ratio는 0~1, percent는 0~100 고정. 그 밖은 0~최댓값이고, 모든 값이 같고 0보다 크면 0~값×2,
  모든 값이 0(또는 값이 하나도 없음)이면 0~1. 눈금은 0, 가운데, 위 셋.
- 좌표는 소수 1자리로 적어 같은 입력이면 바이트로 같은 SVG가 나온다.
"""
from __future__ import annotations

from html import escape

from td.dashboard_config import Metric, format_value

# 크기와 여백은 기존 index.line_chart와 같다.
CHART_W, CHART_H = 520, 190
PAD_L, PAD_R, PAD_T, PAD_B = 44, 12, 12, 34
PLOT_W = CHART_W - PAD_L - PAD_R
PLOT_H = CHART_H - PAD_T - PAD_B
CHART_BASE_Y = float(PAD_T + PLOT_H)          # 값이 축의 바닥일 때의 세로 좌표
CHART_MID_Y = float(PAD_T + PLOT_H / 2)       # 값이 축의 가운데일 때의 세로 좌표
POINT_RADIUS = 3.5


def y_for(value: float, low: float, high: float) -> float:
    """값의 세로 좌표(소수 1자리). 축 범위 밖은 가장자리에 붙인다."""
    share = (value - low) / (high - low) if high > low else 0.0
    share = max(0.0, min(1.0, share))
    return round(PAD_T + PLOT_H * (1 - share), 1)


def _axis_top(unit: str, values: list[float]) -> float:
    if unit == "ratio":
        return 1.0
    if unit == "percent":
        return 100.0
    highest = max(values, default=0.0)
    if highest <= 0:
        return 1.0
    if min(values) == highest:
        return highest * 2
    return highest


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _tick_text(unit: str, value: float) -> str:
    if unit == "ratio":
        return f"{_number_text(value * 100)}%"
    if unit == "percent":
        return f"{_number_text(value)}%"
    if unit == "seconds":
        return f"{_number_text(value)}초"
    return _number_text(value)


def _attr(text) -> str:
    return escape(str(text), quote=True)


def _numeric(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _description(metric: Metric, shown: list[dict], numbers: list[float | None]) -> str:
    """차트의 글 설명(<desc>): 그린 점 수와 마지막 값. 값이 없으면 그 사실."""
    measured = [(point, number) for point, number in zip(shown, numbers) if number is not None]
    if not measured:
        return f"{metric.label}: 측정된 값이 없습니다"
    last_point = measured[-1][0]
    return (f"{metric.label}: 점 {len(measured)}개, 마지막 값 {format_value(metric.name, last_point.get('value'))}"
            f" ({last_point.get('id', '')})")


def trend_svg(metric: Metric, points: list[dict], max_points: int = 30) -> str:
    """지표 하나의 추이 차트. 점은 `{"id", "at", "value", "href"(run만)}`이고 오래된 것부터다."""
    shown = points[-max_points:] if max_points > 0 else []
    numbers = [_numeric(point.get("value")) for point in shown]
    present = [number for number in numbers if number is not None]
    top = _axis_top(metric.unit, present)
    count = len(shown)

    def x_at(position: int) -> float:
        return round(PAD_L + (PLOT_W / 2 if count == 1 else PLOT_W * position / (count - 1)), 1)

    label = f"{metric.label} 추이"
    parts = [f'<svg class="trend" role="img" viewBox="0 0 {CHART_W} {CHART_H}" width="{CHART_W}" '
             f'data-metric="{_attr(metric.name)}" aria-label="{_attr(label)}">',
             f"<title>{_attr(label)}</title>", f"<desc>{_attr(_description(metric, shown, numbers))}</desc>"]
    for tick in (0.0, top / 2, top):
        y = y_for(tick, 0.0, top)
        parts.append(f'<line class="axis" x1="{PAD_L}" y1="{y:.1f}" x2="{CHART_W - PAD_R}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end">{_tick_text(metric.unit, tick)}</text>')

    segments: list[list[str]] = [[]]
    for position, number in enumerate(numbers):
        if number is None:
            segments.append([])
        else:
            segments[-1].append(f"{x_at(position):.1f},{y_for(number, 0.0, top):.1f}")
    for segment in segments:
        if len(segment) > 1:
            parts.append(f'<polyline class="ln" points="{" ".join(segment)}"/>')

    for position, (point, number) in enumerate(zip(shown, numbers)):
        if number is None:
            continue
        data = (f'data-id="{_attr(point.get("id", ""))}" data-at="{_attr(point.get("at", ""))}" '
                f'data-value="{_attr(format_value(metric.name, point.get("value")))}"')
        circle = f'<circle cx="{x_at(position):.1f}" cy="{y_for(number, 0.0, top):.1f}" r="{POINT_RADIUS}"/>'
        if point.get("href"):
            parts.append(f'<a class="pt" href="{_attr(point["href"])}" {data}>{circle}</a>')
        else:
            parts.append(f'<g class="pt" tabindex="0" {data}>{circle}</g>')

    if count:
        for position in sorted({0, count - 1}):
            anchor = "middle" if count == 1 else ("start" if position == 0 else "end")
            parts.append(f'<text class="x-label" x="{x_at(position):.1f}" y="{CHART_H - 16}" text-anchor="{anchor}">'
                         f'{_attr(str(shown[position].get("id", ""))[:8])}</text>')
    parts.append("</svg>")
    return "".join(parts)
