"""S08 커버리지: 스위트별 귀속(attributed)/집계(aggregate) 리포트, TC별 라인 JSON, 병합 집계, 무결성 검사(REQ-031/032/033/063).

- 귀속 커버리지: TC별 `.exec`의 합집합. 집계 커버리지: `aggregate*.exec`(기동 시 실행된 코드 포함).
- 스위트는 디렉터리 탐색으로 찾는다: `S01/blackbox/exec`(스위트 `blackbox`), `S07/<genId>/exec`(스위트 `e2e-<genId>`).
- TC 라인의 키는 소스 경로(`org/.../VetRestController.java`)다. jacoco XML은 패키지 + sourcefile 이름으로 소스를 식별한다.
- 외부 명령(jacococli)은 모두 `td.proc run <timeout>`을 거친다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from td.site.pages import STATIC_DIR, jinja_env, json_for_script, slug

AGGREGATE_PREFIX = "aggregate"
JACOCO_TIMEOUT = 600
CLASS_ID_MARK = "does not match"


class CoverageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Probe:
    test: str
    controller: str


@dataclass(frozen=True)
class Violation:
    kind: str  # containment | classId | probe-own | probe-cross
    detail: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


@dataclass
class ParsedReport:
    covered: dict[str, list[int]]      # 소스 경로 -> 커버된 라인(ci>0 또는 cb>0)
    executable: dict[str, list[int]]   # 소스 경로 -> 명령이 있는 모든 라인
    ratios: dict[str, float]           # line/branch/method 비율(분모 0이면 0.0)
    counters: dict[str, tuple[int, int]]  # 종류 -> (covered, missed)


@dataclass
class TcCoverage:
    lines: dict[str, list[int]]
    line: float
    branch: float
    method: float
    unique_lines: dict[str, list[int]] = field(default_factory=dict)
    class_id_mismatches: set[str] = field(default_factory=set)


@dataclass
class SuiteCoverage:
    name: str
    attributed_xml: Path | None
    aggregate_xml: Path
    kpis: dict
    aggregate_execs: list[Path]
    class_id_mismatches: set[str] = field(default_factory=set)
    tc_exec_files: list[Path] = field(default_factory=list)


# --- jacococli ---------------------------------------------------------------------------
def _java() -> str:
    java_home = os.environ.get("JAVA_HOME")
    return str(Path(java_home) / "bin" / "java") if java_home else "java"


def run_jacococli(cli_jar, args: list[str], log_path: Path) -> int:
    """`td.proc`로 시간 제한을 걸어 jacococli를 실행한다. stdout/stderr는 log_path에 모은다."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    with open(log_path, "wb") as log:
        completed = subprocess.run(
            [sys.executable, "-m", "td.proc", "run", str(JACOCO_TIMEOUT), "--", _java(), "-jar", str(cli_jar), *map(str, args)],
            stdout=log, stderr=subprocess.STDOUT, env=env)
    return completed.returncode


_CLASS_ID_RE = re.compile(r"class (\S+) does not match")


def class_id_mismatches(log_path: Path) -> set[str]:
    """jacococli 로그에서 classId가 맞지 않는 클래스 이름 집합(같은 클래스의 반복 경고는 한 번만 센다)."""
    found: set[str] = set()
    for line in log_path.read_text(errors="replace").splitlines():
        if CLASS_ID_MARK in line:
            match = _CLASS_ID_RE.search(line)
            found.add(match.group(1) if match else line.strip())
    return found


def count_class_id_warnings(log_path: Path) -> int:
    return len(class_id_mismatches(log_path))


def _report(cli_jar, exec_files, classes, out_dir: Path, *, xml=None, csv=None, html=None, sources=None) -> set[str]:
    """리포트를 만들고 classId가 불일치한 클래스 집합을 돌려준다. 실패하면 CoverageError."""
    args = ["report", *map(str, exec_files), "--classfiles", str(classes)]
    if sources:
        args += ["--sourcefiles", str(sources)]
    for flag, target in (("--xml", xml), ("--csv", csv), ("--html", html)):
        if target:
            args += [flag, str(target)]
    log = out_dir / f".jacococli-{hashlib.sha1(' '.join(args).encode()).hexdigest()[:8]}.log"
    rc = run_jacococli(cli_jar, args, log)
    if rc != 0:
        raise CoverageError(f"jacococli report 실패(rc={rc}): {log.read_text(errors='replace')[-600:]}")
    mismatches = class_id_mismatches(log)
    log.unlink()
    return mismatches


# --- XML 파싱 ----------------------------------------------------------------------------
def parse_report(xml_path) -> ParsedReport:
    root = ET.parse(xml_path).getroot()
    covered: dict[str, list[int]] = {}
    executable: dict[str, list[int]] = {}
    for package in root.iter("package"):
        for sourcefile in package.iter("sourcefile"):
            key = f"{package.get('name')}/{sourcefile.get('name')}"
            for line in sourcefile.iter("line"):
                number = int(line.get("nr"))
                executable.setdefault(key, []).append(number)
                if int(line.get("ci")) > 0 or int(line.get("cb")) > 0:
                    covered.setdefault(key, []).append(number)
    counters = {c.get("type"): (int(c.get("covered")), int(c.get("missed"))) for c in root.findall("counter")}

    def ratio(kind: str) -> float:
        done, missed = counters.get(kind, (0, 0))
        return done / (done + missed) if done + missed else 0.0

    return ParsedReport(covered, executable, {"line": ratio("LINE"), "branch": ratio("BRANCH"), "method": ratio("METHOD")}, counters)


# --- TC별 ---------------------------------------------------------------------------------
def per_tc(exec_files, classes, out_dir, cli_jar) -> dict[str, TcCoverage]:
    """`.exec` 하나당 jacococli XML을 임시로 만들어 라인 JSON용 구조로 줄이고 임시 XML은 지운다.
    testId는 파일 이름(확장자 제외)이다. 고유 라인은 같은 스위트 안에서 이 TC만 커버한 라인이다."""
    tmp = Path(out_dir) / ".tc-tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    def one(exec_file: Path) -> tuple[str, TcCoverage]:
        xml_path = tmp / f"{slug(exec_file.stem)}.xml"
        mismatches = _report(cli_jar, [exec_file], classes, tmp, xml=xml_path)
        parsed = parse_report(xml_path)
        xml_path.unlink()
        return exec_file.stem, TcCoverage(parsed.covered, parsed.ratios["line"], parsed.ratios["branch"],
                                          parsed.ratios["method"], class_id_mismatches=mismatches)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(pool.map(one, sorted(Path(p) for p in exec_files)))
    shutil.rmtree(tmp, ignore_errors=True)
    for test_id, unique in unique_lines({t: c.lines for t, c in results.items()}).items():
        results[test_id].unique_lines = unique
    return results


def unique_lines(tc_lines: dict[str, dict[str, list[int]]]) -> dict[str, dict[str, list[int]]]:
    owners: dict[tuple[str, int], int] = {}
    for lines in tc_lines.values():
        for src, numbers in lines.items():
            for number in numbers:
                owners[(src, number)] = owners.get((src, number), 0) + 1
    result: dict[str, dict[str, list[int]]] = {}
    for test_id, lines in tc_lines.items():
        only = {src: [n for n in numbers if owners[(src, n)] == 1] for src, numbers in lines.items()}
        result[test_id] = {src: numbers for src, numbers in only.items() if numbers}
    return result


# --- 스위트 -------------------------------------------------------------------------------
def report_suite(exec_dir, classes, sources, out_dir, cli_jar, name: str = "blackbox") -> SuiteCoverage:
    exec_dir, out_dir = Path(exec_dir), Path(out_dir)
    tc_execs = sorted(p for p in exec_dir.glob("*.exec") if not p.name.startswith(AGGREGATE_PREFIX))
    aggregate_execs = sorted(exec_dir.glob(f"{AGGREGATE_PREFIX}*.exec"))
    if not aggregate_execs:
        raise CoverageError(f"{name}: aggregate*.exec가 없다({exec_dir})")
    mismatches: set[str] = set()
    kpis: dict = {"line": 0.0, "branch": 0.0}
    attributed_xml = None
    if tc_execs:
        base = out_dir / "attributed"
        base.mkdir(parents=True, exist_ok=True)
        mismatches |= _report(cli_jar, tc_execs, classes, base, xml=base / "jacoco.xml", csv=base / "jacoco.csv",
                            html=base / "html", sources=sources)
        attributed_xml = base / "jacoco.xml"
        parsed = parse_report(attributed_xml)
        kpis = {"line": parsed.ratios["line"], "branch": parsed.ratios["branch"]}
    base = out_dir / "aggregate"
    base.mkdir(parents=True, exist_ok=True)
    mismatches |= _report(cli_jar, aggregate_execs, classes, base, xml=base / "jacoco.xml", csv=base / "jacoco.csv",
                        html=base / "html", sources=sources)
    aggregate = parse_report(base / "jacoco.xml")
    kpis["aggregate"] = {"line": aggregate.ratios["line"], "branch": aggregate.ratios["branch"]}
    return SuiteCoverage(name, attributed_xml, base / "jacoco.xml", kpis, aggregate_execs, mismatches, tc_execs)


def _digest_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*.class")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def merge_aggregate(suites: list[SuiteCoverage], out, classes, cli_jar, commit: str) -> Path:
    """모든 스위트의 aggregate.exec를 같은 classes로 한 번에 리포트해 `out`(aggregate.xml)과 manifest.json을 만든다.
    S09(hotspot)와 S11(Sonar)이 이 파일 하나를 쓴다(REQ-063)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    execs = [path for s in suites for path in s.aggregate_execs]
    mismatches = _report(cli_jar, execs, classes, out.parent, xml=out)
    manifest = {
        "suites": [s.name for s in suites], "commit": commit, "classes": str(classes), "classesDigest": _digest_tree(Path(classes)),
        "execFiles": [{"suite": s.name, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                      for s in suites for path in s.aggregate_execs],
        "classIdMismatches": sorted(mismatches),
        "xml": out.name, "xmlSha256": hashlib.sha256(out.read_bytes()).hexdigest(),
    }
    (out.parent / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return out


# --- 무결성 -------------------------------------------------------------------------------
def check_containment(attributed, aggregate) -> list[Violation]:
    """귀속 커버 라인은 집계 커버 라인에 포함돼야 한다. 인자: 소스 경로 -> 커버 라인."""
    violations = []
    for src, numbers in attributed.items():
        extra = sorted(set(numbers) - set(aggregate.get(src, [])))
        if extra:
            violations.append(Violation("containment", f"{src}: attributed에만 있는 라인 {extra[:10]}"))
    return violations


def check_class_id(mismatched_classes) -> list[Violation]:
    """classId가 불일치한 클래스마다 위반 1건."""
    return [Violation("classId", f"classId 불일치: {name}") for name in sorted(mismatched_classes)]


def check_probes(tc_lines, probes: list[Probe], controller_lines) -> list[Violation]:
    """교차 오염 탐침. controller_lines: 컨트롤러 -> {소스 경로 -> 실행 가능 라인}. 각 TC는 자기 컨트롤러만 커버해야 한다."""
    violations = []
    for probe in probes:
        covered = {(src, n) for src, numbers in tc_lines.get(probe.test, {}).items() for n in numbers}
        for controller, by_src in controller_lines.items():
            executable = {(src, n) for src, numbers in by_src.items() for n in numbers}
            hits = covered & executable
            if controller == probe.controller and not hits:
                violations.append(Violation("probe-own", f"{probe.test}가 자기 컨트롤러 {controller} 라인을 커버하지 않았다"))
            if controller != probe.controller and hits:
                violations.append(Violation("probe-cross", f"{probe.test}가 {controller} 라인 {len(hits)}개를 커버했다(교차 오염)"))
    return violations


# --- 스위트 탐색과 전체 실행 ---------------------------------------------------------------
def discover_suites(run_dir) -> dict[str, Path]:
    """실행 디렉터리에서 스위트(이름 -> exec 디렉터리)를 찾는다. 새 스위트는 디렉터리만 있으면 꽂힌다."""
    run_dir = Path(run_dir)
    suites: dict[str, Path] = {}
    blackbox = run_dir / "S01" / "blackbox" / "exec"
    if list(blackbox.glob("*.exec")):
        suites["blackbox"] = blackbox
    s07 = run_dir / "S07"
    if s07.is_dir():
        for gen_dir in sorted(p for p in s07.iterdir() if p.is_dir() and list((p / "exec").glob("*.exec"))):
            suites[f"e2e-{gen_dir.name}"] = gen_dir / "exec"
    return suites


def _summary_for(exec_dir: Path) -> dict:
    summary = exec_dir.parent / "summary.json"
    return json.loads(summary.read_text()) if summary.is_file() else {}


def copy_sources(source_keys, sources_dir, out_dir: Path) -> int:
    count = 0
    for key in sorted(source_keys):
        source = Path(sources_dir) / key
        if source.is_file():
            target = out_dir / "src" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            count += 1
    return count


RESULT_VALUES = ("passed", "failed", "skipped", "undefined", "uncompilable")


def parse_scenario_results(path) -> dict[str, str]:
    """scenario-results.json은 엄격한 NDJSON이다: 줄마다 {"testId": str, "status": passed|failed|undefined|uncompilable,
    "requests": int, "exec": str|null}. 다른 모양은 줄 번호를 붙여 CoverageError로 거부한다."""
    results: dict[str, str] = {}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CoverageError(f"{path}:{number}: NDJSON 줄이 JSON이 아니다: {exc}") from exc
        if not isinstance(item, dict) or set(item) != {"testId", "status", "requests", "exec"}:
            raise CoverageError(f"{path}:{number}: 키가 testId,status,requests,exec여야 한다: {line[:120]}")
        if not isinstance(item["testId"], str) or item["status"] not in ("passed", "failed", "undefined", "uncompilable") \
                or not isinstance(item["requests"], int) or isinstance(item["requests"], bool) \
                or not (item["exec"] is None or isinstance(item["exec"], str)):
            raise CoverageError(f"{path}:{number}: 값 형식이 맞지 않는다: {line[:120]}")
        results[item["testId"]] = item["status"]
    return results


def load_results(run_dir, suite_name: str, test_sources=None) -> dict[str, str]:
    """스위트의 TC별 결과(testId -> 결과). 스위트 종류별 결과 소스를 여기서 고른다.
    - blackbox: S01 JUnit XML(passed|failed|skipped)
    - e2e-<genId>: S07/<genId>/scenario-results.json(NDJSON: 줄마다 {testId, status, requests, exec}, status는 passed|failed|undefined|uncompilable)
    소스가 없으면 빈 dict(그 TC의 결과는 알 수 없음으로 표시한다)."""
    run_dir = Path(run_dir)
    if suite_name == "blackbox":
        from td.blackbox import junit_results
        junit_dir = run_dir / "S01" / "blackbox" / "junit"
        return junit_results(junit_dir, test_sources) if junit_dir.is_dir() else {}
    if suite_name.startswith("e2e-"):
        path = run_dir / "S07" / suite_name[len("e2e-"):] / "scenario-results.json"
        if not path.is_file():
            return {}
        return parse_scenario_results(path)
    return {}


def build(run_dir, *, classes, sources, cli_jar, commit: str, probes: list[Probe], test_sources=None) -> dict:
    """S08 전체 실행: 스위트별 리포트, TC JSON, 병합 집계, 무결성 검사, coverage.json. 결과 요약을 돌려준다."""
    run_dir = Path(run_dir)
    out = run_dir / "S08"
    out.mkdir(parents=True, exist_ok=True)
    suite_dirs = discover_suites(run_dir)
    if not suite_dirs:
        raise CoverageError("스위트가 없다(S01/blackbox/exec, S07/<genId>/exec에 .exec가 없다)")
    suites: list[SuiteCoverage] = []
    suite_json: dict[str, dict] = {}
    all_tc_lines: dict[str, dict[str, list[int]]] = {}
    violations: list[Violation] = []
    mismatched: set[str] = set()
    all_sources: set[str] = set()
    all_classes: set[str] = set()
    tc_dir = out / "tc"
    tc_dir.mkdir(exist_ok=True)
    for name, exec_dir in suite_dirs.items():
        suite_out = out / name
        suite = report_suite(exec_dir, classes, sources, suite_out, cli_jar, name)
        suites.append(suite)
        tcs = per_tc(suite.tc_exec_files, classes, suite_out, cli_jar)
        mismatched |= suite.class_id_mismatches
        for tc in tcs.values():
            mismatched |= tc.class_id_mismatches
        aggregate = parse_report(suite.aggregate_xml)
        all_sources |= set(aggregate.executable)
        attributed_lines = parse_report(suite.attributed_xml).covered if suite.attributed_xml else {}
        violations += check_containment(attributed_lines, aggregate.covered)
        tc_entries = []
        for test_id, tc in sorted(tcs.items()):
            line_count = sum(len(v) for v in tc.lines.values())
            unique_count = sum(len(v) for v in tc.unique_lines.values())
            (tc_dir / f"{slug(test_id)}.json").write_text(json.dumps({
                "testId": test_id, "suite": name, "slug": slug(test_id), "lines": tc.lines, "lineCount": line_count,
                "uniqueLines": tc.unique_lines, "uniqueLineCount": unique_count,
                "line": tc.line, "branch": tc.branch, "method": tc.method}, ensure_ascii=False))
            all_classes |= set(tc.lines)
            tc_entries.append({"testId": test_id, "slug": slug(test_id), "attributed": True, "line": tc.line, "branch": tc.branch,
                               "method": tc.method, "lineCount": line_count, "uniqueLines": unique_count,
                               "classes": sorted(tc.lines), "classCounts": {k: len(v) for k, v in sorted(tc.lines.items())}})
        summary = _summary_for(exec_dir)
        no_attribution = set(summary.get("noAttribution") or [])
        missing = set(summary.get("missingExec") or [])
        results = load_results(run_dir, name, test_sources)
        for entry in tc_entries:
            entry["result"] = results.get(entry["testId"])
        for test_id in sorted((missing | set(results)) - set(tcs)):
            reason = "no-attribution" if test_id in no_attribution else "missing-exec" if test_id in missing else "no-exec"
            tc_entries.append({"testId": test_id, "slug": slug(test_id), "attributed": False, "reason": reason,
                               "result": results.get(test_id),
                               "line": 0.0, "branch": 0.0, "method": 0.0, "lineCount": 0, "uniqueLines": 0,
                               "classes": [], "classCounts": {}})
        all_tc_lines.update({t: c.lines for t, c in tcs.items()})
        suite_json[name] = {
            "kpis": suite.kpis, "tcCount": len(tc_entries), "attributedCount": len(tcs), "tcs": tc_entries,
            "paths": {kind: {"html": f"{name}/{kind}/html/index.html", "xml": f"{name}/{kind}/jacoco.xml",
                             "csv": f"{name}/{kind}/jacoco.csv"}
                      for kind in (["attributed"] if suite.attributed_xml else []) + ["aggregate"]},
        }
    merged = merge_aggregate(suites, out / "merged" / "aggregate.xml", classes, cli_jar, commit)
    mismatched |= set(json.loads((merged.parent / "manifest.json").read_text())["classIdMismatches"])
    merged_report = parse_report(merged)
    all_sources |= set(merged_report.executable)
    copy_sources(all_sources, sources, out)
    # 탐침은 blackbox 스위트의 aggregate XML에서 컨트롤러의 실행 가능 라인을 얻는다.
    probe_results = []
    if probes:
        blackbox = next((s for s in suites if s.name == "blackbox"), None)
        if blackbox is None:
            violations.append(Violation("probe-own", "blackbox 스위트가 없어 교차 오염 탐침을 실행할 수 없다"))
        else:
            executable = parse_report(blackbox.aggregate_xml).executable
            controller_lines = {p.controller: {src: nums for src, nums in executable.items() if Path(src).stem == p.controller}
                                for p in probes}
            for probe in probes:
                if not controller_lines[probe.controller]:
                    violations.append(Violation("probe-own", f"컨트롤러 {probe.controller} 소스를 리포트에서 찾지 못했다"))
            if all(p.test in all_tc_lines for p in probes):
                violations += check_probes(all_tc_lines, probes, controller_lines)
                probe_results = [{"test": p.test, "controller": p.controller,
                                  "ownLines": sum(len(set(v) & set(controller_lines[p.controller].get(k, [])))
                                                  for k, v in all_tc_lines[p.test].items()),
                                  "crossLines": sum(len(set(v) & set(lines.get(k, [])))
                                                    for c, lines in controller_lines.items() if c != p.controller
                                                    for k, v in all_tc_lines[p.test].items())} for p in probes]
            else:
                violations += [Violation("probe-own", f"탐침 TC {p.test}의 .exec가 없다") for p in probes if p.test not in all_tc_lines]
    violations += check_class_id(mismatched)
    warnings_total = len(mismatched)
    coverage = {"suites": suite_json, "classes": sorted(all_classes),
                "integrity": {"violations": [v.as_dict() for v in violations], "classIdWarnings": warnings_total, "probes": probe_results},
                "merged": {"xml": "merged/aggregate.xml", "manifest": "merged/manifest.json"}}
    (out / "coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False))
    render_page(out, coverage)
    return {"suites": {s.name: s.kpis for s in suites}, "violations": [v.as_dict() for v in violations],
            "classIdWarnings": warnings_total, "merged": str(merged), "tests": blackbox_pass_kpi(suite_json)}


def blackbox_pass_kpi(suite_json: dict, suite: str = "blackbox") -> dict | None:
    """홈 KPI '테스트 통과율'(REQ-049): 기존 블랙박스 IT의 TC 결과(skipped 제외) 중 passed 비율. 생성 E2E 스위트는 실험
    데이터라서 넣지 않는다(arm별 통과율은 compare.json). 스위트가 없거나 결과가 하나도 없으면 None."""
    tcs = (suite_json.get(suite) or {}).get("tcs") or []
    counted = [tc["result"] for tc in tcs if tc.get("result") in ("passed", "failed")]
    if not counted:
        return None
    passed = sum(1 for result in counted if result == "passed")
    return {"suite": suite, "passed": passed, "total": len(counted), "passRate": passed / len(counted)}


# --- 화면 ---------------------------------------------------------------------------------
def render_page(out_dir, coverage: dict, css_href: str = "site.css", copy_css: bool = True) -> Path:
    """coverage.json 내용으로 `coverage.html`을 만든다. 데이터는 페이지에 내장하고 TC 상세와 소스는 지연 로드한다."""
    out_dir = Path(out_dir)
    if copy_css:  # 단독 열람용: 같은 디렉터리의 site.css를 참조한다. 사이트 조립(Task 7)은 copy_css=False와 css_href를 넘긴다.
        shutil.copy2(STATIC_DIR / "site.css", out_dir / "site.css")
    template = jinja_env().get_template("coverage.html.j2")
    heat_max = max((n for suite in coverage["suites"].values() for tc in suite["tcs"] for n in tc["classCounts"].values()), default=1)
    html = template.render(coverage=coverage, css_href=css_href, heat_max=heat_max, data_json=json_for_script(coverage),
                           short=lambda src: Path(src).stem)
    target = out_dir / "coverage.html"
    target.write_text(html)
    return target


# --- CLI ----------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.coverage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("run_dir")
    run.add_argument("--sut-file", required=True)
    run.add_argument("--classes", required=True)
    run.add_argument("--sources", required=True)
    run.add_argument("--cli", required=True)
    run.add_argument("--commit", required=True)
    run.add_argument("--test-sources")
    args = parser.parse_args(argv)
    from td import sut_config, state
    config = sut_config.load(args.sut_file)
    probes = [Probe(p.test, p.controller) for p in config.coverage_probes]
    try:
        result = build(args.run_dir, classes=args.classes, sources=args.sources, cli_jar=args.cli, commit=args.commit, probes=probes,
                        test_sources=args.test_sources)
    except CoverageError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)[:1500]}, ensure_ascii=False))
        return 0
    for name, kpis in result["suites"].items():
        state.set_run_field(args.run_dir, f"kpis.{name}", kpis)
    if result["tests"] is not None:
        state.set_run_field(args.run_dir, "kpis.tests", result["tests"])
    status, reason = "passed", None
    if result["violations"]:
        status = "failed"
        reason = f"무결성 위반 {len(result['violations'])}건: " + "; ".join(f"{v['kind']}: {v['detail']}" for v in result["violations"][:5])
    print(json.dumps({"status": status, "reason": reason, "extra": {"suites": sorted(result["suites"]),
                                                                    "violations": len(result["violations"]),
                                                                    "classIdWarnings": result["classIdWarnings"]},
                      "merged": result["merged"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
