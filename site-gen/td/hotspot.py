"""S09 hotspot: hotspot-analysis 설정 렌더링과 결과 요약.

jar 실행(JDK 21, td_run 시간 제한)은 pipeline/S09-hotspot.sh가 한다. 이 모듈은 인자 조립(`prepare`)과
결과 가공(`finish`)만 한다. 분석 대상은 전체 히스토리를 가진 SUT clone이고, 윈도우는 "지금"이 아니라
SUT 커밋 날짜에 맞춘다(재실행해도 같은 결과가 나오게 하려는 것이다).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from td import sut_config

WINDOW_DAYS = 365
TOP_N = 10
DEPS_ZIP_PREFIX = "BOOT-INF/lib/"


class HotspotError(RuntimeError):
    pass


def window_for(commit_iso: str) -> tuple[str, str]:
    """(since, until) ISO 날짜. until은 커밋 다음 날(경계 포함), since는 그 해 전이다."""
    commit_day = datetime.fromisoformat(commit_iso).date()
    return (commit_day - timedelta(days=WINDOW_DAYS)).isoformat(), (commit_day + timedelta(days=1)).isoformat()


def render_config(template: Path, *, target: Path, sources: str, since: str, until: str,
                  classpath_dirs: list[Path], jacoco_xml: Path | None, output: Path) -> str:
    """템플릿의 ${NAME}을 채운다. jacoco_xml이 None이면 jacocoReportPath 줄을 뺀다."""
    jacoco_line = f"  jacocoReportPath: {jacoco_xml}" if jacoco_xml else None
    values = {
        "TARGET_PATH": str(target), "SOURCES": sources.strip("/"), "SINCE": since, "UNTIL": until, "OUTPUT_PATH": str(output),
        "CLASSPATH_LINES": "\n".join(f"      - {path}" for path in classpath_dirs),
    }
    lines = []
    for line in Path(template).read_text().splitlines():
        if "${JACOCO_LINE}" in line:
            if jacoco_line:
                lines.append(jacoco_line)
            continue
        for key, value in values.items():
            line = line.replace("${" + key + "}", value)
        lines.append(line)
    return "\n".join(lines) + "\n"


def extract_dependencies(jar: Path, dest: Path) -> Path:
    """부트 jar의 BOOT-INF/lib를 풀어 콜그래프 심볼 해석용 classpath 디렉터리로 만든다."""
    lib_dir = dest / "BOOT-INF" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar) as archive:
        for entry in archive.namelist():
            if entry.startswith(DEPS_ZIP_PREFIX) and entry.endswith(".jar"):
                (lib_dir / Path(entry).name).write_bytes(archive.read(entry))
    return lib_dir


def top10(hotspots_yml: Path, limit: int = TOP_N) -> list[dict]:
    """복합 점수 상위 목록. 메서드 단위가 있으면 메서드, 없으면 파일 단위다.
    홈 KPI(td.site.index)가 `name`을 읽는다."""
    data = yaml.safe_load(Path(hotspots_yml).read_text()) or {}
    methods = data.get("methodHotspots") or []
    if methods:
        rows = [{"name": f"{str(m['fqcn']).rsplit('.', 1)[-1]}.{m['method']}", "file": m["file"], "method": m["method"],
                 "score": m["compositeScore"]} for m in methods]
    else:
        rows = [{"name": Path(f["path"]).name, "file": f["path"], "score": f["compositeScore"]}
                for f in data.get("fileHotspots") or []]
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows[:limit]


def _git(src: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(src), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise HotspotError(f"git {' '.join(args)} 실패: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def prepare(run_dir: Path, sut_file: Path, src: Path, template: Path, merged_xml: Path | None) -> dict:
    """설정과 classpath를 만들어 JSON으로 돌려준다. 전체 히스토리가 아니면 실패한다."""
    sut = sut_config.load(sut_file)
    if _git(src, "rev-parse", "--is-shallow-repository") == "true":
        raise HotspotError("SUT clone이 얕다(shallow). hotspot 분석은 전체 히스토리가 필요하다")
    since, until = window_for(_git(src, "log", "-1", "--format=%cI"))
    jars = sorted(src.glob(sut.jar_glob))
    if not jars:
        raise HotspotError(f"SUT jar가 없다: {src / sut.jar_glob}")
    root = Path(run_dir) / "S09"
    output = root / "hotspot"
    output.mkdir(parents=True, exist_ok=True)
    lib_dir = extract_dependencies(jars[-1], root / "deps")
    use_xml = merged_xml is not None and merged_xml.is_file()
    config = output / "hotspot.yml"
    config.write_text(render_config(template, target=src, sources=sut.sources, since=since, until=until,
                                    classpath_dirs=[sut.classes_dir(src), lib_dir], jacoco_xml=merged_xml if use_xml else None,
                                    output=output))
    return {"config": str(config), "output": str(output), "jacoco": bool(use_xml),
            "mergedXml": str(merged_xml) if merged_xml else None}


def finish(run_dir: Path, jacoco: bool, merged_xml: str | None) -> dict:
    output = Path(run_dir) / "S09" / "hotspot"
    missing = [name for name in ("hotspots.html", "api_report.html", "hotspots.yml") if not (output / name).is_file()]
    if missing:
        raise HotspotError(f"hotspot 산출물이 없다: {', '.join(missing)}")
    rows = top10(output / "hotspots.yml")
    (Path(run_dir) / "S09" / "top10.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    result = {"status": "passed", "extra": {"top10": rows, "coverageApplied": jacoco}}
    if not jacoco:
        result["status"] = "degraded"
        result["reason"] = f"S08 병합 커버리지(merged/aggregate.xml)가 없어 커버리지 배수 없이 분석했다: {merged_xml or 'S08 not run'}"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.hotspot")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("run_dir", type=Path)
    prep.add_argument("--sut-file", type=Path, required=True)
    prep.add_argument("--src", type=Path, required=True)
    prep.add_argument("--template", type=Path, required=True)
    prep.add_argument("--merged-xml", type=Path)
    fin = sub.add_parser("finish")
    fin.add_argument("run_dir", type=Path)
    fin.add_argument("--jacoco", choices=("true", "false"), required=True)
    fin.add_argument("--merged-xml")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.run_dir, args.sut_file, args.src, args.template, args.merged_xml)
        else:
            result = finish(args.run_dir, args.jacoco == "true", args.merged_xml)
    except (HotspotError, sut_config.SutConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
