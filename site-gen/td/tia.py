"""S10 TIA: base 커밋 해석, base 사전 검사, impact 결과 요약.

외부 도구 실행(git worktree, Gradle, SUT 기동, tia CLI)과 trap 정리는 pipeline/S10-tia.sh가 한다.
이 모듈은 값 해석과 판정만 한다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from td import sut_config

_RANGE_BASE = re.compile(r"^HEAD(?:~(\d+))?$")
PER_TEST_EXTENSION = "PerTestCoverageExtension"


class TiaError(RuntimeError):
    pass


def _git(repo, *args) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise TiaError(f"git {' '.join(args)} 실패: {done.stderr.strip()[-300:]}")
    return done.stdout.strip()


def resolve_base(repo, commit: str, range_spec: str, first_parent: bool) -> str:
    """`HEAD~N..HEAD` 범위의 base를 run 커밋 기준으로 해석한 40자 SHA.
    first_parent이면 `rev-list --first-parent --skip=N`으로 따라간다(머지 커밋의 두 번째 부모로 새지 않는다)."""
    base_ref, _, head_ref = range_spec.partition("..")
    match = _RANGE_BASE.match(base_ref)
    if not match or head_ref != "HEAD":
        raise TiaError(f"지원하지 않는 tia.range 형식: {range_spec!r}(HEAD~N..HEAD만 지원한다)")
    steps = int(match.group(1) or 0)
    if first_parent:
        out = _git(repo, "rev-list", "--first-parent", "-n", "1", f"--skip={steps}", commit)
    else:
        try:
            out = _git(repo, "rev-parse", "--verify", f"{commit}~{steps}^{{commit}}")
        except TiaError:
            out = ""
    if not out:
        raise TiaError(f"base를 해석하지 못했다: {base_ref}가 {commit[:7]}의 히스토리보다 깊다(shallow clone일 수 있다)")
    if not re.fullmatch(r"[0-9a-f]{40}", out):
        raise TiaError(f"base가 40자 SHA가 아니다: {out!r}")
    return out


def precheck(base_dir) -> list[str]:
    """base 체크아웃에 블랙박스 스위트를 돌릴 수단이 있는지 본다. 비어 있으면 실행 가능, 아니면 건너뛸 사유 목록."""
    base_dir = Path(base_dir)
    reasons = []
    build_files = [p for p in (base_dir / "build.gradle", base_dir / "build.gradle.kts") if p.is_file()]
    if not any("blackboxTest" in p.read_text(errors="replace") for p in build_files):
        reasons.append("base에 blackboxTest 태스크가 없다")
    if not any(base_dir.rglob(f"{PER_TEST_EXTENSION}.java")) and not any(base_dir.rglob(f"{PER_TEST_EXTENSION}.kt")):
        reasons.append(f"base에 {PER_TEST_EXTENSION}가 없다")
    return reasons


MAX_DIFF_LINES = 400  # 리포트에 싣는 diff 상한(전체는 base-head.diff에 있다)


def lost_attribution(testwise) -> list[str]:
    """testwise.json에서 in-process 귀속 손실 TC(`incompleteAttribution: true` 또는 `droppedProbes > 0`).
    tia convert의 stderr 대신 기계가 읽는 이 필드를 쓴다(tia의 isLoss 판정과 같은 기준)."""
    tests = testwise.get("tests") if isinstance(testwise, dict) else None
    if not isinstance(tests, list):
        raise TiaError("testwise.json에 tests 배열이 없다")
    return sorted(t["uniformPath"] for t in tests
                  if isinstance(t, dict) and (t.get("incompleteAttribution") is True or (t.get("droppedProbes") or 0) > 0))


def impact_summary(doc, indexed_tests: int) -> dict:
    """`tia impact --format json` 출력(`tests[{id, confidence}]`, `warnings[]`)에서 선택 현황을 뽑는다.
    allSelectedConservative: 선택된 테스트가 모두 CONSERVATIVE(= tia의 보수적 전체 선택 신호, 선택이 0개면 false)."""
    if not isinstance(doc, dict):
        raise TiaError(f"impact.json 최상위가 객체가 아니다: {type(doc).__name__}")
    tests = doc.get("tests")
    if not isinstance(tests, list):
        raise TiaError("impact.json에 tests 배열이 없다(tia impact --format json 출력이 아니다)")
    tests = tests if isinstance(tests, list) else []
    conservative = [t for t in tests if t.get("confidence") == "CONSERVATIVE"]
    return {"selected": len(tests), "indexedTests": indexed_tests, "deterministic": len(tests) - len(conservative),
            "conservative": len(conservative), "allSelectedConservative": bool(tests) and len(conservative) == len(tests)}


def build_scenarios(doc, diff_text: str, indexed_tests: int, base: str, head: str) -> list[dict]:
    """tia report가 읽는 시나리오 목록(템플릿 계약: id, title, diff, selected[{confidence,testId}], conservative, total, count, reasons).
    base..head 전체를 시나리오 하나로 본다."""
    summary = impact_summary(doc, indexed_tests)
    lines = diff_text.splitlines()
    shown = "\n".join(lines[:MAX_DIFF_LINES])
    if len(lines) > MAX_DIFF_LINES:
        shown += f"\n… (diff {len(lines)}줄 중 {MAX_DIFF_LINES}줄만 표시, 전체는 base-head.diff)"
    selected = [{"confidence": t.get("confidence"), "testId": t.get("id")} for t in (doc.get("tests") or [])]
    return [{"id": "R", "title": f"range {base[:7]}..{head[:7]} (base→HEAD 전체 변경)", "kind": "range",
             "diff": shown, "selected": selected, "conservative": summary["allSelectedConservative"],
             "total": indexed_tests, "count": len(selected), "reasons": list(doc.get("warnings") or [])}]


_REP1_RE = re.compile(r"^(base|jqa|owl|det)-[0-9a-f]{8}-r1(?:-g([0-9]+))?$")


def base_generations(s06_stage: dict) -> list[tuple[str, str, str]]:
    """S10이 base SUT에서 돌릴 generation: arm마다 실행 가능한(passed|degraded) rep 1 하나.
    같은 arm에 `-g<n>`(--regenerate)이 여럿이면 접미사 없는 것, 없으면 가장 작은 n을 고른다. [(genId, arm, dir)]"""
    chosen: dict[str, tuple[int, str, str]] = {}
    for gen_id, gen in (s06_stage.get("generations") or {}).items():
        match = _REP1_RE.match(gen_id)
        if not match or not isinstance(gen, dict) or gen.get("status") not in ("passed", "degraded"):
            continue
        arm, order = match.group(1), int(match.group(2) or 0)
        if arm not in chosen or order < chosen[arm][0]:
            chosen[arm] = (order, gen_id, str(gen.get("dir") or ""))
    return [(gen_id, arm, directory) for arm, (_, gen_id, directory) in sorted(chosen.items())]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.tia")
    sub = parser.add_subparsers(dest="cmd", required=True)
    resolve = sub.add_parser("resolve-base", help="sut.yaml tia.range의 base를 40자 SHA로 출력")
    resolve.add_argument("--sut-file", required=True)
    resolve.add_argument("--repo", required=True)
    resolve.add_argument("--commit", required=True)
    check = sub.add_parser("precheck", help="base 체크아웃의 blackboxTest/확장 존재 검사(사유를 줄마다 출력)")
    check.add_argument("base_dir")
    scen = sub.add_parser("scenarios", help="impact.json + diff -> tia report용 scenarios.json, 요약 JSON을 stdout에 출력")
    scen.add_argument("--impact", required=True)
    scen.add_argument("--diff", required=True)
    scen.add_argument("--testwise", required=True)
    scen.add_argument("--out", required=True)
    scen.add_argument("--base", required=True)
    scen.add_argument("--head", required=True)
    gens = sub.add_parser("e2e-generations", help="S06 단계 JSON에서 base에서 돌릴 arm별 rep1 generation(TSV: genId arm dir)")
    gens.add_argument("s06_json")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "e2e-generations":
            for row in base_generations(json.loads(Path(args.s06_json).read_text())):
                print("\t".join(row))
        elif args.cmd == "resolve-base":
            config = sut_config.load(args.sut_file)
            print(resolve_base(args.repo, args.commit, config.tia_range_spec, config.tia_first_parent))
        elif args.cmd == "scenarios":
            doc = json.loads(Path(args.impact).read_text())
            testwise = json.loads(Path(args.testwise).read_text())
            total = len(testwise.get("tests") or [])
            scenarios = build_scenarios(doc, Path(args.diff).read_text(errors="replace"), total, args.base, args.head)
            Path(args.out).write_text(json.dumps(scenarios, ensure_ascii=False, indent=1))
            print(json.dumps({**impact_summary(doc, total), "incompleteAttribution": lost_attribution(testwise)}))
        else:
            for reason in precheck(args.base_dir):
                print(reason)
    except (TiaError, sut_config.SutConfigError, OSError, ValueError) as exc:
        print(f"tia: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
