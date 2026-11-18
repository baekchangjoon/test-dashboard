"""S01 수량 게이트: JUnit XML의 TC 목록과 pjacoco가 쓴 `<testId>.exec` 목록을 대조한다(REQ-008).

testId는 블랙박스 IT의 PerTestCoverageExtension이 만드는 `<SimpleName>#<method>`다.
pjacoco가 파일명에 `#`를 어떻게 쓰는지는 `exec_file_key`가 한 곳에서 흡수한다.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

AGGREGATE_PREFIX = "aggregate"


_ANNOTATION = r'@\w+(?:\((?:"(?:[^"\\]|\\.)*"|[^)"])*\))?'
_METHOD_RE = re.compile(rf'((?:\s*{_ANNOTATION})+)\s*(?:public\s+|protected\s+|private\s+)?void\s+(\w+)\s*\(')
_DISPLAY_RE = re.compile(r'@DisplayName\(\s*"((?:[^"\\]|\\.)*)"\s*\)')


def _report_name(name: str) -> str:
    """Gradle은 JUnit XML name에서 첫 `(` 뒤를 메서드 시그니처로 보고 잘라낸다(DisplayName의 괄호 설명도 사라진다)."""
    return name.split("(", 1)[0]


def display_name_methods(sources_dir) -> dict[tuple[str, str], str]:
    """(SimpleName, @DisplayName 문구) -> 메서드 이름. Gradle JUnit XML의 name은 DisplayName이라 메서드를 복원할 때 쓴다."""
    mapping: dict[tuple[str, str], str] = {}
    if not sources_dir:
        return mapping
    for java_file in Path(sources_dir).rglob("*.java"):
        text = java_file.read_text(errors="replace")
        for match in _METHOD_RE.finditer(text):
            display = _DISPLAY_RE.search(match.group(1))
            if display:
                mapping[(java_file.stem, _report_name(display.group(1).replace('\\"', '"')))] = match.group(2)
    return mapping


def junit_test_ids(junit_dir, sources_dir=None) -> list[str]:
    """skipped를 뺀 모든 TC의 testId(`SimpleName#method`). name이 DisplayName이면 소스로 메서드를 복원하고,
    못 찾으면 `(...)`를 뗀 name을 쓴다. 중복은 유지한다."""
    methods = display_name_methods(sources_dir)
    ids: list[str] = []
    for xml_file in sorted(Path(junit_dir).glob("*.xml")):
        for case in ET.parse(xml_file).getroot().iter("testcase"):
            if case.find("skipped") is not None:
                continue
            simple_name = case.get("classname", "").rsplit(".", 1)[-1]
            name = _report_name(case.get("name", ""))
            method = methods.get((simple_name, name)) or name
            ids.append(f"{simple_name}#{method}")
    return ids


def exec_file_key(test_id: str) -> str:
    """testId가 .exec 파일 이름(확장자 제외)이 되는 규칙. pjacoco가 `#`를 그대로 쓰는지 실측해 맞춘다."""
    return test_id


def exec_names(exec_dir) -> set[str]:
    """aggregate*.exec를 뺀 .exec 파일의 이름(확장자 제외)."""
    return {p.stem for p in Path(exec_dir).glob("*.exec") if not p.name.startswith(AGGREGATE_PREFIX)}


def load_no_attribution(expected_file) -> list[str]:
    """SUT 설명 디렉터리의 expected-tests.yaml `no_attribution.tests`(없으면 빈 목록)."""
    if not expected_file or not Path(expected_file).is_file():
        return []
    import yaml
    data = yaml.safe_load(Path(expected_file).read_text()) or {}
    return list((data.get("no_attribution") or {}).get("tests") or [])


def evaluate(junit_dir, exec_dir, sources_dir=None, expected_file=None) -> dict:
    """게이트 판정. 누락(.exec 없는 TC) 중 문서화되지 않은 것이 있으면 failed, 문서화된 TC가 .exec를 가지면 degraded,
    정확히 일치하면 passed. missingExec는 실제 누락 전부, noAttribution은 문서화된 목록이다."""
    test_ids = junit_test_ids(junit_dir, sources_dir)
    names = exec_names(exec_dir)
    documented = load_no_attribution(expected_file)
    missing = sorted({t for t in test_ids if exec_file_key(t) not in names})
    aggregate = any(Path(exec_dir).glob(f"{AGGREGATE_PREFIX}*.exec"))
    undocumented = [t for t in missing if t not in documented]
    known_keys = {exec_file_key(t) for t in test_ids}
    orphans = sorted(names - known_keys)
    duplicates = sorted({t for t in test_ids if test_ids.count(t) > 1})
    stale = sorted(t for t in documented if t in set(test_ids) and exec_file_key(t) in names)
    absent = sorted(t for t in documented if t not in set(test_ids))
    result = {"tcCount": len(test_ids), "execCount": len(names), "missingExec": missing,
              "noAttribution": documented, "aggregateExec": aggregate}
    problems = []
    if not test_ids:
        problems.append("JUnit XML에 실행된 TC가 없다")
    if undocumented:
        problems.append(f"tcCount({len(test_ids)}) execCount({len(names)}): 문서화되지 않은 missingExec {len(undocumented)}건: "
                        f"{', '.join(undocumented[:5])}{' …' if len(undocumented) > 5 else ''}")
    if orphans:
        problems.append(f"TC가 없는 .exec(orphan) {len(orphans)}건: {', '.join(orphans[:5])}{' …' if len(orphans) > 5 else ''}")
    if not aggregate:
        problems.append("aggregate.exec가 없다")
    result["orphanExec"] = orphans
    result["duplicateTestIds"] = duplicates
    if problems:
        result["status"], result["reason"] = "failed", "; ".join(problems)
    elif stale or absent or duplicates:
        parts = []
        if stale:
            parts.append(f"documented but has exec: {', '.join(stale)}")
        if absent:
            parts.append(f"documented but not in JUnit: {', '.join(absent)}")
        if duplicates:
            parts.append(f"duplicate testIds: {', '.join(duplicates)}")
        result["status"], result["reason"] = "degraded", "expectation stale: " + "; ".join(parts)
    else:
        result["status"] = "passed"
    return result


def main(argv: list[str] | None = None) -> int:
    """`python -m td.blackbox evaluate <junit_dir> <exec_dir> [<test_sources_dir> [<expected_tests.yaml>]]`: 판정 JSON을 stdout에 낸다."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (3, 4, 5) or args[0] != "evaluate":
        print("usage: td.blackbox evaluate <junit_dir> <exec_dir> [<test_sources_dir> [<expected_tests.yaml>]]", file=sys.stderr)
        return 2
    print(json.dumps(evaluate(args[1], args[2], args[3] if len(args) > 3 else None, args[4] if len(args) > 4 else None), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
