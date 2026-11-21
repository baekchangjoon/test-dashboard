"""인덱스 재생성: `_COMPLETE`가 있는 run만 읽어 suts.json, runs.json, 홈, SUT 페이지, _test 목록을 쓴다.

멱등이다. 실행 시각 같은 비결정 값은 쓰지 않고, 모든 목록을 안정적으로 정렬한다(REQ-045).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from td import dashboard_config
from td.dashboard_config import Config, ConfigError
from td.site.pages import STATIC_DIR, jinja_env, read_json as _read

REPO_ROOT = Path(__file__).resolve().parents[3]

CHART_W, CHART_H = 520, 190
PAD_L, PAD_R, PAD_T, PAD_B = 44, 12, 12, 34


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
V2_DIR = STATIC_DIR / "v2"


def _copy_v2(base: Path, written: list[Path]) -> None:
    """새 디자인 자산(static/v2/의 파일)을 base/static/v2/에 복사한다(이름순)."""
    for source in sorted(p for p in V2_DIR.iterdir() if p.is_file()):
        target = base / "static" / "v2" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        written.append(target)


def rebuild(site_root, prefix: str = "", config: Config | None = None, *,
            exclude: frozenset[str] = frozenset()) -> list[Path]:
    """site_root/prefix 아래 인덱스를 다시 쓰고, 쓴 파일 목록을 돌려준다. _test 접두 목록은 site_root/_test에 쓴다.

    config가 없으면 `dashboard_config.resolve(os.environ, 저장소 루트)`로 고른다. 설정 검증과 암묵 과제 추가는
    파일을 하나라도 쓰기 전에 하고, 실패하면 `ConfigError`를 그대로 올려 아무것도 쓰지 않는다.
    exclude(제외 과제 이름)와 확정된 설정은 홈·과제 페이지(Task 9·10)에서 쓴다. 지금 쓰는 파일은 PoC와 같다.
    """
    site_root = Path(site_root)
    base = site_root / prefix if prefix else site_root
    suts = _collect(base)
    if config is None:
        config = dashboard_config.resolve(os.environ, REPO_ROOT)
    dashboard_config.with_implicit(config, suts.keys())
    written: list[Path] = []
    env = jinja_env()
    depth = len([part for part in Path(prefix).parts if part]) if prefix else 0
    test_index_href = "../" * depth + "_test/index.html"

    for name in ("site.css", "site.js"):  # 옛 run 페이지가 쓰는 v1 자산(바이트 그대로)
        target = base / "static" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATIC_DIR / name, target)
        written.append(target)
    _copy_v2(base, written)

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
    _copy_v2(test_dir, written)
    _write(test_dir / "index.html", env.get_template("test_index.html.j2").render(
        prefixes=prefixes, css_href="static/site.css", home_href="../index.html"), written)
    return written


def main(argv: list[str] | None = None) -> int:
    """`python -m td.site.index <site_root> [prefix] [--config <파일>]`. 설정 오류는 표준 오류에 내고 종료 코드 2."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m td.site.index <site_root> [prefix] [--config <file>]", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(prog="python -m td.site.index")
    parser.add_argument("site_root")
    parser.add_argument("prefix", nargs="?", default="")
    parser.add_argument("--config", help="dashboard.yaml 경로(없으면 환경 변수와 저장소 루트로 고른다)")
    options = parser.parse_args(args)
    try:
        if options.config:
            config = dashboard_config.resolve({**os.environ, "TD_DASHBOARD_CONFIG": options.config}, REPO_ROOT)
        else:
            config = dashboard_config.resolve(os.environ, REPO_ROOT)
        rebuild(options.site_root, options.prefix, config)
    except ConfigError as exc:
        print(f"dashboard config error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
