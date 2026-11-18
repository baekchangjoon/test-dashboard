"""인덱스 재생성: `_COMPLETE`가 있는 run만 읽어 suts.json, runs.json, 홈, SUT 페이지, _test 목록을 쓴다.

멱등이다. 실행 시각 같은 비결정 값은 쓰지 않고, 모든 목록을 안정적으로 정렬한다(REQ-045).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from td.site.pages import STATIC_DIR, jinja_env

CHART_W, CHART_H = 520, 190
PAD_L, PAD_R, PAD_T, PAD_B = 44, 12, 12, 34


def _read(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def _write(path: Path, text: str, written: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    written.append(path)


def _write_json(path: Path, data, written: list[Path]) -> None:
    _write(path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", written)


def _hotspot_first(run_dir: Path) -> str | None:
    top = (_read(run_dir / "stages" / "S09.json", {}) or {}).get("top10")
    if not top:
        return None
    first = top[0]
    if isinstance(first, dict):
        return first.get("name") or first.get("method") or first.get("id")
    return str(first)


def _attributed_line(kpis: dict) -> float | None:
    """blackbox 스위트의 귀속 라인이 우선이고, 없으면 가장 앞선 스위트의 값을 쓴다."""
    for name in ["blackbox", *sorted(k for k, v in kpis.items() if isinstance(v, dict) and k not in ("blackbox", "tests", "sonar"))]:
        suite = kpis.get(name)
        if isinstance(suite, dict) and isinstance(suite.get("line"), (int, float)):
            return suite["line"]
    return None


def summarize_run(run_dir: Path) -> dict:
    run = _read(run_dir / "run.json", {})
    kpis = run.get("kpis") or {}
    tests = kpis.get("tests") if isinstance(kpis.get("tests"), dict) else {}
    sonar = kpis.get("sonar") if isinstance(kpis.get("sonar"), dict) else {}
    return {
        "runId": run.get("runId", run_dir.name), "commit": run.get("commit"), "trigger": run.get("trigger"),
        "startedAt": run.get("startedAt"), "stages": dict(sorted((run.get("stages") or {}).items())),
        "kpis": {"passRate": tests.get("passRate"), "line": _attributed_line(kpis),
                 "sonarGate": sonar.get("gate"), "hotspot1": _hotspot_first(run_dir)},
    }


def _collect(base: Path) -> dict[str, list[dict]]:
    suts: dict[str, list[dict]] = {}
    suts_dir = base / "suts"
    for sut_dir in sorted(p for p in suts_dir.iterdir() if p.is_dir()) if suts_dir.is_dir() else []:
        runs_dir = sut_dir / "runs"
        runs = [summarize_run(r) for r in (sorted(runs_dir.iterdir()) if runs_dir.is_dir() else [])
                if r.is_dir() and (r / "_COMPLETE").exists()]
        if runs:
            suts[sut_dir.name] = sorted(runs, key=lambda r: r["runId"], reverse=True)
    return suts


# --- 추이 차트(인라인 SVG, 외부 라이브러리 없음) ---------------------------------------------------
def line_chart(title: str, desc: str, runs_oldest_first: list[dict], key: str) -> str:
    """값은 0~1 비율(y축 0~100%). 값이 없는 run은 선을 끊는다. 색은 CSS 변수라 다크 모드를 따른다."""
    plot_w, plot_h = CHART_W - PAD_L - PAD_R, CHART_H - PAD_T - PAD_B
    count = len(runs_oldest_first)

    def x_at(i: int) -> float:
        return PAD_L + (plot_w / 2 if count == 1 else plot_w * i / (count - 1))

    def y_at(value: float) -> float:
        return PAD_T + plot_h * (1 - max(0.0, min(1.0, value)))

    parts = [f'<svg class="chart" role="img" viewBox="0 0 {CHART_W} {CHART_H}" width="{CHART_W}" aria-labelledby="t-{key} d-{key}">',
             f'<title id="t-{key}">{_esc(title)}</title><desc id="d-{key}">{_esc(desc)}</desc>']
    for tick in (0, 0.5, 1):
        y = y_at(tick)
        parts.append(f'<line class="axis" x1="{PAD_L}" y1="{y:.1f}" x2="{CHART_W - PAD_R}" y2="{y:.1f}"/>')
        parts.append(f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
    segment: list[str] = []
    segments: list[list[str]] = []
    for i, run in enumerate(runs_oldest_first):
        value = run["kpis"].get(key)
        if isinstance(value, (int, float)):
            segment.append(f"{x_at(i):.1f},{y_at(value):.1f}")
        elif segment:
            segments.append(segment)
            segment = []
    if segment:
        segments.append(segment)
    for seg in segments:
        if len(seg) > 1:
            parts.append(f'<polyline class="line" points="{" ".join(seg)}"/>')
    for i, run in enumerate(runs_oldest_first):
        value = run["kpis"].get(key)
        if isinstance(value, (int, float)):
            parts.append(f'<circle class="dot" cx="{x_at(i):.1f}" cy="{y_at(value):.1f}" r="3.5">'
                         f'<title>{_esc(run["runId"])}: {value * 100:.1f}%</title></circle>')
    for i in sorted({0, count - 1}):
        anchor = "start" if i == 0 and count > 1 else "end" if count > 1 else "middle"
        parts.append(f'<text x="{x_at(i):.1f}" y="{CHART_H - 16}" text-anchor="{anchor}">{_esc(runs_oldest_first[i]["runId"][:8])}</text>')
    parts.append(f'<text x="{PAD_L + plot_w / 2:.1f}" y="{CHART_H - 2}" text-anchor="middle">run 날짜(오래된 순)</text>')
    parts.append("</svg>")
    return "".join(parts)


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# --- 재생성 ---------------------------------------------------------------------------------
def rebuild(site_root, prefix: str = "") -> list[Path]:
    """site_root/prefix 아래 인덱스를 다시 쓰고, 쓴 파일 목록을 돌려준다. _test 접두 목록은 site_root/_test에 쓴다."""
    site_root = Path(site_root)
    base = site_root / prefix if prefix else site_root
    written: list[Path] = []
    env = jinja_env()
    suts = _collect(base)
    depth = len([part for part in Path(prefix).parts if part]) if prefix else 0
    test_index_href = "../" * depth + "_test/index.html"

    for name in ("site.css", "site.js"):
        target = base / "static" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATIC_DIR / name, target)
        written.append(target)

    summary = [{"name": name, "runCount": len(runs), "latest": runs[0]} for name, runs in suts.items()]
    _write_json(base / "suts.json", summary, written)
    for name, runs in suts.items():
        _write_json(base / "suts" / name / "runs.json", runs, written)
        oldest_first = list(reversed(runs))
        charts = [
            line_chart("테스트 통과율 추이", f"{name}의 run별 테스트 통과율(0~100%)", oldest_first, "passRate"),
            line_chart("귀속 라인 커버리지 추이", f"{name}의 run별 귀속 라인 커버리지(0~100%)", oldest_first, "line"),
        ]
        _write(base / "suts" / name / "index.html", env.get_template("sut.html.j2").render(
            sut=name, runs=runs, charts=charts, css_href="../../static/site.css", home_href="../../index.html"), written)
    _write(base / "index.html", env.get_template("home.html.j2").render(
        suts=summary, css_href="static/site.css", test_index_href=test_index_href), written)

    test_dir = site_root / "_test"
    prefixes = sorted(p.name for p in test_dir.iterdir() if (p / "suts.json").exists()) if test_dir.is_dir() else []
    css = test_dir / "static" / "site.css"
    css.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STATIC_DIR / "site.css", css)
    written.append(css)
    _write(test_dir / "index.html", env.get_template("test_index.html.j2").render(
        prefixes=prefixes, css_href="static/site.css", home_href="../index.html"), written)
    return written


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m td.site.index <site_root> [prefix]", file=sys.stderr)
        return 1
    rebuild(args[0], args[1] if len(args) > 1 else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
