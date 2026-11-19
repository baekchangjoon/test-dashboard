"""S07 Cucumber 실행기의 파이썬 쪽(REQ-028, REQ-029, REQ-062).

generation 배치(S06이 쓰고 S07이 읽는다): `<gen>/features/**/*.feature`, `<gen>/glue/**/*.java`. step 정의 클래스는
feature마다 하나이고 이름은 `glue/<Pascal(feature 파일 stem)>Steps.java`다(예: `vet_lookup.feature` -> `VetLookupSteps.java`).
glue 소스는 `package` 선언이 있어야 한다.

SUT 없이 동작하는 검증 함수(S06 수리 루프가 임시 디렉터리에서 쓴다):
- `compile_check(gen_dir, classpath, out_dir) -> CompileResult`: 클래스별로 javac를 시도해 실패한 클래스를 뺀다.
- `dry_run(gen_dir, out_dir) -> DryRun`: Cucumber dry-run으로 undefined step을 모은다.
- `validate_generation(gen_dir, out_dir)`: 위 둘을 차례로 실행한다.
generation 스냅샷 디렉터리는 수리가 끝난 뒤 불변이므로 제외 판정은 S07이 run마다 다시 계산해 `S07/<genId>/compile-excluded.json`에 쓴다.

S07 단계가 쓰는 함수: `write_testids`(td.testids 입력), `reconcile`/`append_missing`(모든 시나리오가 scenario-results.json에
정확히 한 번 나오게 한다), `verify_exec`(.exec 수와 경로 검증), `finalize`(summary.json). 시나리오 단위는 pickle이다
(Scenario Outline은 Examples 데이터 행마다 하나).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from td import testid

FEATURES_DIR = "features"
GLUE_DIR = "glue"
RESULT_STATUSES = ("passed", "failed", "undefined", "uncompilable")
GEN_ID_RE = re.compile(r"^(base|jqa|owl)-([0-9a-f]{8})-r([1-9])(?:-g([0-9]+))?$")
GRADLE_TIMEOUT_SEC = 1800


class ScenariosError(RuntimeError):
    """실행 환경이나 입력이 잘못돼 계속할 수 없는 경우(시나리오 실패가 아니다)."""


class ReconcileError(ScenariosError):
    """시나리오 보존 위반(누락, 중복, 알 수 없는 testId)."""


# --- 식별 ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GenIdent:
    arm: str
    input_hash: str
    rep: int
    gen: int | None

    @classmethod
    def from_gen_id(cls, gen_id: str) -> "GenIdent":
        match = GEN_ID_RE.match(gen_id)
        if not match:
            raise ScenariosError(f"genId 형식이 아니다(<arm>-<inputHash8>-r<rep>[-g<n>]): {gen_id!r}")
        arm, input_hash, rep, gen = match.groups()
        return cls(arm, input_hash, int(rep), int(gen) if gen else None)


def generation_dir(sut: str, gen_id: str, root: Path | None = None) -> Path:
    """`e2e/generated/<sut>/<arm>/<genId>`(스냅샷 위치)."""
    ident = GenIdent.from_gen_id(gen_id)
    base = Path(os.environ.get("TD_E2E_GENERATED_DIR") or (root or _repo_root()) / "e2e" / "generated")
    return base / sut / ident.arm / gen_id


# --- feature 목록과 testId ------------------------------------------------------------------------
@dataclass(frozen=True)
class PickleRef:
    test_id: str
    feature: str       # generation 루트 기준 상대 경로(`features/a.feature`)
    line: int
    name: str
    feature_name: str | None


def feature_files(gen_dir) -> list[str]:
    """generation 루트 기준 feature 상대 경로(정렬)."""
    root = Path(gen_dir)
    return sorted(path.relative_to(root).as_posix() for path in (root / FEATURES_DIR).rglob("*.feature"))


def feature_name(text: str) -> str | None:
    for line in text.splitlines():
        match = re.match(r"^\s*Feature\s*:\s*(.*)$", line)
        if match:
            return match.group(1).strip() or None
    return None


def pickle_refs(gen_dir, ident: GenIdent) -> list[PickleRef]:
    """모든 feature(컴파일 제외 feature 포함)의 pickle과 testId. feature는 상대 경로 순으로 불러
    slug가 Python/Java에서 같다. 제외 feature도 넣는 이유: slug 충돌 접미사가 실행 여부에 따라 바뀌면 안 되기 때문이다."""
    root = Path(gen_dir)
    taken: set[str] = set()
    slugs: dict[str, str] = {}
    refs: list[PickleRef] = []
    for relative in feature_files(root):
        text = (root / relative).read_text(encoding="utf-8")
        name = feature_name(text)
        for pickle in testid.pickles(text):
            test_id = testid.make(ident.arm, ident.input_hash, ident.rep, ident.gen, relative, pickle.line, taken,
                                  name=name, slugs=slugs)
            refs.append(PickleRef(test_id, relative, pickle.line, pickle.name, name))
    return refs


def write_testids(gen_dir, ident: GenIdent, out_path) -> Path:
    """하네스 `td.testids` 입력. 모양은 e2e/harness CoverageHooks/TestIds.Registry가 읽는 것이다."""
    features: dict[str, dict] = {}
    for ref in pickle_refs(gen_dir, ident):
        entry = features.setdefault(ref.feature, {"path": ref.feature, "name": ref.feature_name, "pickles": []})
        entry["pickles"].append({"line": ref.line, "name": ref.name})
    payload = {"arm": ident.arm, "inputHash": ident.input_hash, "rep": ident.rep, "gen": ident.gen,
               "features": list(features.values())}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def glue_class_for_feature(feature_relative: str) -> str:
    """feature에 대응하는 glue 클래스 파일(generation 루트 기준)."""
    stem = PurePosixPath(feature_relative).stem
    pascal = "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", stem) if part)
    return f"{GLUE_DIR}/{pascal}Steps.java"


# --- 실행 환경 ------------------------------------------------------------------------------------
def _repo_root() -> Path:
    return Path(os.environ.get("TD_ROOT") or Path(__file__).resolve().parents[2])


def e2e_dir() -> Path:
    return Path(os.environ.get("TD_E2E_DIR") or _repo_root() / "e2e")


def java_home(version: int = 17) -> str:
    """JDK 홈. macOS는 /usr/libexec/java_home, 아니면 JAVA_HOME_<version>, JAVA_HOME 순이다."""
    java_home_tool = Path("/usr/libexec/java_home")
    if java_home_tool.exists():
        found = subprocess.run([str(java_home_tool), "-v", str(version)], capture_output=True, text=True)
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    for key in (f"JAVA_HOME_{version}", "JAVA_HOME"):
        if os.environ.get(key):
            return os.environ[key]
    raise ScenariosError(f"JDK {version}을 찾지 못했다")


def run_gradle(args: list[str], log_path: Path, *, timeout: float = GRADLE_TIMEOUT_SEC, extra_env: dict | None = None) -> int:
    """e2e/gradlew --no-daemon. 시간 제한과 프로세스 그룹 정리는 td.proc가 맡는다. 출력은 log_path로 간다."""
    from td import proc
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "JAVA_HOME": java_home(17), **(extra_env or {})}
    with log_path.open("w", encoding="utf-8") as log:
        return proc.run_with_timeout(timeout, ["./gradlew", "--no-daemon", "--console=plain", *args], cwd=e2e_dir(),
                                     stdout=log, stderr=subprocess.STDOUT, env=env)


def runner_classpath(out_file) -> str:
    """runner의 컴파일 클래스패스(하네스, Cucumber, REST Assured, AssertJ)를 Gradle에게 받아 파일에 쓰고 돌려준다."""
    out = Path(out_file).resolve()
    log = out.with_suffix(".log")
    status = run_gradle([":runner:writeCompileClasspath", f"-PclasspathOut={out}"], log, timeout=600)
    if status != 0 or not out.is_file() or not out.read_text().strip():
        raise ScenariosError(f"runner 클래스패스를 얻지 못했다(exit {status}): {log.read_text()[-600:] if log.exists() else ''}")
    return out.read_text().strip()


# --- compile_check --------------------------------------------------------------------------------
@dataclass(frozen=True)
class CompileResult:
    excluded: list[str]               # 컴파일되지 않아 뺀 glue 클래스(generation 루트 기준 상대 경로)
    compiler_output: str
    excluded_features: list[str] = field(default_factory=list)   # 그 클래스에 대응하는 feature(시나리오는 uncompilable)


_ERROR_FILE_RE = re.compile(r"^(?P<file>.+?\.java):\d+: error:", re.MULTILINE)


def compile_check(gen_dir, classpath: str, out_dir) -> CompileResult:
    """glue 클래스를 javac로 확인해 컴파일되지 않는 클래스를 가린다. 오류가 난 파일을 빼고 남은 것을 다시 컴파일하는 것을
    오류가 없을 때까지 되풀이한다(다른 클래스가 깨진 클래스를 참조하면 그 클래스도 빠진다). 결과를 `compile-excluded.json`과
    `compile.log`로 out_dir에 쓴다."""
    root, out = Path(gen_dir).resolve(), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    remaining = sorted(path.relative_to(root).as_posix() for path in (root / GLUE_DIR).rglob("*.java"))
    excluded: list[str] = []
    outputs: list[str] = []
    javac = str(Path(java_home(17)) / "bin" / "javac")
    with tempfile.TemporaryDirectory(prefix="td-javac-") as classes_dir:
        while remaining:
            result = subprocess.run([javac, "-proc:none", "-implicit:none", "-encoding", "UTF-8", "-Xmaxerrs", "100000",
                                     "-cp", classpath, "-d", classes_dir, *[str(root / item) for item in remaining]],
                                    capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                break
            text = result.stderr.replace(str(root) + "/", "")
            outputs.append(text)
            failing = {Path(match.group("file")).as_posix() if not Path(match.group("file")).is_absolute()
                       else Path(match.group("file")).resolve().relative_to(root).as_posix()
                       for match in _ERROR_FILE_RE.finditer(result.stderr)}
            failing &= set(remaining)
            if not failing:
                raise ScenariosError(f"javac가 실패했지만 오류 파일을 가리지 못했다: {text[:600]}")
            excluded.extend(sorted(failing))
            remaining = [item for item in remaining if item not in failing]
    excluded_set = set(excluded)
    features = [item for item in feature_files(root) if glue_class_for_feature(item) in excluded_set]
    compiler_output = "".join(outputs)
    (out / "compile.log").write_text(compiler_output, encoding="utf-8")
    (out / "compile-excluded.json").write_text(json.dumps(
        {"classes": sorted(excluded_set), "features": features}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return CompileResult(sorted(excluded_set), compiler_output, features)


# --- dry-run ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DryRun:
    undefined_steps: list[dict]                     # {"feature","line","step"}
    json_path: Path
    undefined_pickles: frozenset[tuple[str, int]] = frozenset()   # (feature 상대 경로, pickle 줄)
    pickle_count: int = 0                           # dry-run이 본 pickle 수(컴파일 제외 feature 제외)


def _feature_path(uri: str) -> str:
    """dry-run JSON의 uri(`classpath:features/a.feature`)를 generation 루트 기준 상대 경로로 바꾼다."""
    return uri[len("classpath:"):].lstrip("/") if uri.startswith("classpath:") else uri


def parse_dryrun(json_path) -> DryRun:
    """Cucumber JSON(dry-run)에서 undefined step과 pickle을 뽑는다. 배경(Background) step이 undefined면 그 뒤 시나리오도 undefined다."""
    path = Path(json_path)
    try:
        features = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenariosError(f"dry-run JSON을 읽지 못했다({path.name}): {exc}") from exc
    steps_out: list[dict] = []
    pickles: set[tuple[str, int]] = set()
    count = 0
    for feature in features:
        feature_path = _feature_path(feature["uri"])
        background_undefined = False
        for element in feature.get("elements", []):
            undefined = [step for step in element.get("steps", []) if step.get("result", {}).get("status") == "undefined"]
            for step in undefined:
                steps_out.append({"feature": feature_path, "line": step.get("line"), "step": step.get("name")})
            if element.get("type") == "background":
                background_undefined = bool(undefined)
                continue
            count += 1
            if undefined or background_undefined:
                pickles.add((feature_path, element["line"]))
    return DryRun(steps_out, path, frozenset(pickles), count)


def _resolve_exclusions(gen_dir: Path, out_dir: Path, classpath: str | None) -> CompileResult:
    excluded_file = out_dir / "compile-excluded.json"
    if excluded_file.is_file():
        data = json.loads(excluded_file.read_text(encoding="utf-8"))
        return CompileResult(data["classes"], (out_dir / "compile.log").read_text() if (out_dir / "compile.log").exists() else "",
                             data["features"])
    return compile_check(gen_dir, classpath or runner_classpath(out_dir / "classpath.txt"), out_dir)


def dry_run(gen_dir, out_dir, *, classpath: str | None = None) -> DryRun:
    """SUT 없이 Cucumber dry-run을 돌려 undefined step을 모은다. out_dir/compile-excluded.json이 있으면 그 제외를 쓰고,
    없으면 먼저 compile_check로 만든다. 결과 JSON은 out_dir/dryrun.json이다."""
    root, out = Path(gen_dir).resolve(), Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not feature_files(root):
        raise ScenariosError(f"feature가 없다: {root / FEATURES_DIR}")
    exclusions = _resolve_exclusions(root, out, classpath)
    dryrun_json = out / "dryrun.json"
    dryrun_json.unlink(missing_ok=True)
    if set(feature_files(root)) <= set(exclusions.excluded_features):
        dryrun_json.write_text("[]\n")   # 실행할 feature가 없다(전부 uncompilable)
        return parse_dryrun(dryrun_json)
    status = run_gradle([":runner:test", f"-Pgen={root}", f"-Pexcluded={out / 'compile-excluded.json'}",
                         f"-Pout={out}", "-Pdryrun=true"], out / "dryrun-gradle.log")
    if status != 0 or not dryrun_json.is_file() or dryrun_json.stat().st_size == 0:
        log = out / "dryrun-gradle.log"
        raise ScenariosError(f"dry-run이 결과를 만들지 못했다(exit {status}): {log.read_text()[-600:] if log.exists() else ''}")
    return parse_dryrun(dryrun_json)


@dataclass(frozen=True)
class ValidationResult:
    compile: CompileResult
    dry_run: DryRun


def validate_generation(gen_dir, out_dir) -> ValidationResult:
    """S06 수리 루프용: 컴파일 확인과 dry-run을 차례로 한다(SUT 불필요). out_dir은 호출자의 임시 디렉터리다."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "compile-excluded.json").unlink(missing_ok=True)
    classpath = runner_classpath(out / "classpath.txt")
    compile_result = compile_check(gen_dir, classpath, out)
    return ValidationResult(compile_result, dry_run(gen_dir, out, classpath=classpath))


# --- 대조(reconcile) ------------------------------------------------------------------------------
@dataclass(frozen=True)
class ScenarioResult:
    test_id: str
    status: str            # passed | failed | undefined | uncompilable
    requests: int
    exec: str | None
    feature: str
    line: int
    source: str = "run"    # run(하네스가 씀) | dryrun | compile(S07이 덧붙임)

    def as_line(self) -> dict:
        return {"testId": self.test_id, "status": self.status, "requests": self.requests, "exec": self.exec}


def parse_results_file(path) -> list[dict]:
    """scenario-results.json(NDJSON)의 줄. 없으면 빈 목록. 모양 검증은 S08(coverage.parse_scenario_results)이 엄격히 한다."""
    path = Path(path)
    if not path.is_file():
        return []
    lines = []
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            lines.append(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ReconcileError(f"{path.name}:{number}: NDJSON 줄이 JSON이 아니다: {exc}") from exc
    return lines


def reconcile(feature_dir, dryrun: DryRun, results: list[dict], compile_excluded, *, ident: GenIdent) -> list[ScenarioResult]:
    """모든 시나리오(pickle)가 정확히 한 번 나오는 결과 목록을 만든다(순서는 testId 생성 순서).
    - 하네스가 쓴 줄이 있으면 그대로 쓴다(passed|failed|undefined).
    - 컴파일 제외 feature의 시나리오는 실행하지 않았으므로 `uncompilable`로 덧붙인다.
    - 줄이 없고 dry-run에서 undefined인 시나리오는 `undefined`로 덧붙인다.
    - 그 밖의 누락, 중복 줄, 알 수 없는 testId는 ReconcileError(사유에 testId 목록)다."""
    gen_dir = Path(feature_dir).resolve().parent
    uncompilable = set(compile_excluded.excluded_features if isinstance(compile_excluded, CompileResult) else compile_excluded)
    refs = pickle_refs(gen_dir, ident)
    known = {ref.test_id for ref in refs}
    by_id: dict[str, dict] = {}
    problems: list[str] = []
    for line in results:
        test_id = line.get("testId")
        if test_id not in known:
            problems.append(f"알 수 없는 testId: {test_id}")
        elif test_id in by_id:
            problems.append(f"중복 줄: {test_id}")
        else:
            by_id[test_id] = line
    merged: list[ScenarioResult] = []
    missing: list[str] = []
    for ref in refs:
        line = by_id.get(ref.test_id)
        if ref.feature in uncompilable:
            if line is not None and line.get("status") != "uncompilable":   # 이미 덧붙인 줄(재실행)은 허용한다
                problems.append(f"컴파일 제외 feature의 시나리오가 실행됐다: {ref.test_id}")
            merged.append(ScenarioResult(ref.test_id, "uncompilable", 0, None, ref.feature, ref.line,
                                         "run" if line is not None else "compile"))
        elif line is not None:
            if line.get("status") not in ("passed", "failed", "undefined"):
                problems.append(f"허용되지 않는 status {line.get('status')!r}: {ref.test_id}")
            merged.append(ScenarioResult(ref.test_id, line["status"], int(line["requests"]), line["exec"], ref.feature,
                                         ref.line, "run"))
        elif (ref.feature, ref.line) in dryrun.undefined_pickles:
            merged.append(ScenarioResult(ref.test_id, "undefined", 0, None, ref.feature, ref.line, "dryrun"))
        else:
            missing.append(ref.test_id)
    if missing:
        problems.append("결과 줄이 없는 시나리오: " + ", ".join(missing))
    if problems:
        raise ReconcileError("; ".join(problems))
    return merged


def append_missing(results_path, merged: list[ScenarioResult]) -> int:
    """하네스가 쓰지 않은 줄(uncompilable, dry-run undefined)을 scenario-results.json 끝에 덧붙인다(엄격한 NDJSON). 덧붙인 수."""
    added = [item for item in merged if item.source != "run"]
    if added:
        path = Path(results_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for item in added:
                handle.write(json.dumps(item.as_line(), ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(added)


def undefined_ratio(results: list[ScenarioResult]) -> float:
    """REQ-029: (undefined이고 uncompilable이 아닌 pickle 수) / (uncompilable을 포함한 전체 pickle 수). 비어 있으면 0.0."""
    return sum(1 for item in results if item.status == "undefined") / len(results) if results else 0.0


# --- .exec 검증 -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class ExecCheck:
    missing: list[str]          # exec 경로가 적혔지만 파일이 없는 testId
    unexpected: list[str]       # requests가 0인데 exec가 적힌 testId
    expected_count: int         # requests > 0인 시나리오 수
    actual_count: int           # exec 디렉터리의 .exec 수(aggregate.exec 제외)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.unexpected and self.expected_count == self.actual_count


def verify_exec(results: list[ScenarioResult], results_path, exec_dir) -> ExecCheck:
    """exec 경로는 결과 파일 기준 상대 경로이고 파일 이름에 '#'이 들어간다. 요청 1회 이상인 시나리오 수 = .exec 수(REQ-028)."""
    base = Path(results_path).parent
    missing = [item.test_id for item in results if item.exec is not None and not (base / item.exec).is_file()]
    unexpected = [item.test_id for item in results if item.exec is not None and item.requests == 0]
    expected = sum(1 for item in results if item.requests > 0)
    actual = len([path for path in Path(exec_dir).glob("*.exec") if path.name != "aggregate.exec"]) if Path(exec_dir).is_dir() else 0
    # requests>0인데 exec가 null인 경우도 수량 불일치로 드러난다(expected != actual 또는 missing)
    no_path = [item.test_id for item in results if item.requests > 0 and item.exec is None]
    return ExecCheck(sorted(set(missing + no_path)), unexpected, expected, actual)


# --- S07 마무리 -----------------------------------------------------------------------------------
REQUIRED_OUTPUTS = ("cucumber.ndjson", "cucumber.json", "junit.xml", "html/index.html")


def finalize(gen_dir, out_dir, ident: GenIdent) -> dict:
    """실행이 끝난 generation의 결과를 대조해 `scenario-results.json`을 완성하고 summary.json을 쓴다.
    반환: {"status": "passed"|"failed", "reason": str|None, "extra": {...}}. 시나리오 실패는 generation 실패가 아니다
    (결과 데이터다). 실행 기반 문제(출력 누락, 시나리오 누락, .exec 누락)가 generation 실패다."""
    root, out = Path(gen_dir).resolve(), Path(out_dir)
    results_path = out / "scenario-results.json"
    summary: dict = {}
    exclusions = _resolve_exclusions(root, out, None)
    dryrun = parse_dryrun(out / "dryrun.json")
    # 실행할 feature가 하나도 없으면(전부 uncompilable) Cucumber를 돌리지 않았으므로 출력이 없는 것이 정상이다.
    absent = [name for name in REQUIRED_OUTPUTS if not (out / name).is_file()] if dryrun.pickle_count else []
    if absent:
        return {"status": "failed", "reason": f"Cucumber 출력이 없다: {', '.join(absent)}", "extra": {}}
    try:
        merged = reconcile(root / FEATURES_DIR, dryrun, parse_results_file(results_path), exclusions, ident=ident)
    except ReconcileError as exc:
        return {"status": "failed", "reason": f"시나리오 대조 실패: {str(exc)[:1200]}", "extra": {}}
    append_missing(results_path, merged)
    check = verify_exec(merged, results_path, out / "exec")
    counts = {status: sum(1 for item in merged if item.status == status) for status in RESULT_STATUSES}
    ratio = undefined_ratio(merged)
    summary = {"scenarios": len(merged), "statusCounts": counts, "undefinedRatio": ratio,
               "requestsPositive": check.expected_count, "execCount": check.actual_count,
               "uncompilableClasses": exclusions.excluded}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extra = {"scenarios": len(merged), "undefinedRatio": ratio, "statusCounts": counts, "execCount": check.actual_count}
    if not check.ok:
        parts = []
        if check.missing:
            parts.append(".exec 파일 누락: " + ", ".join(check.missing))
        if check.unexpected:
            parts.append("요청 0회인데 exec 경로가 있다: " + ", ".join(check.unexpected))
        if check.expected_count != check.actual_count:
            parts.append(f"요청 1회 이상 시나리오 {check.expected_count}개 != .exec {check.actual_count}개")
        return {"status": "failed", "reason": "; ".join(parts)[:1400], "extra": extra}
    return {"status": "passed", "reason": None, "extra": extra}


# --- 인증 환경 ------------------------------------------------------------------------------------
def auth_env_exports(sut_file) -> str:
    """sut.yaml auth.user_env/pass_env가 가리키는 환경 변수 값(환경 우선, 없으면 infra/local.env)을 하네스 이름으로 내보낸다.
    값은 stdout으로만 나가고(eval용) 명령줄에는 실리지 않는다."""
    from td import sut_config
    from td.publish import load_local_env
    sut = sut_config.load(sut_file)
    local = load_local_env(_repo_root() / "infra" / "local.env")
    lines = []
    for source, target in ((sut.auth_user_env, "TD_AUTH_USER"), (sut.auth_pass_env, "TD_AUTH_PASS")):
        value = os.environ.get(source) or local.get(source)
        if not value:
            raise ScenariosError(f"{source}가 환경과 infra/local.env에 없다")
        lines.append(f"export {target}={shlex.quote(value)}")
    return "\n".join(lines)


# --- CLI ------------------------------------------------------------------------------------------
def _cmd_prepare(args) -> int:
    """compile_check -> testids.json -> dry-run. 결과 요약을 JSON으로 낸다."""
    ident = GenIdent.from_gen_id(args.gen_id)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "compile-excluded.json").unlink(missing_ok=True)
    classpath = runner_classpath(out / "classpath.txt")
    compile_result = compile_check(args.gen_dir, classpath, out)
    write_testids(args.gen_dir, ident, out / "testids.json")
    dryrun = dry_run(args.gen_dir, out, classpath=classpath)
    print(json.dumps({"excludedClasses": compile_result.excluded, "excludedFeatures": compile_result.excluded_features,
                      "undefinedSteps": len(dryrun.undefined_steps), "pickles": dryrun.pickle_count}))
    return 0


def _cmd_finalize(args) -> int:
    print(json.dumps(finalize(args.gen_dir, args.out_dir, GenIdent.from_gen_id(args.gen_id)), ensure_ascii=False))
    return 0


def _cmd_validate(args) -> int:
    result = validate_generation(args.gen_dir, args.out_dir)
    print(json.dumps({"excluded": result.compile.excluded, "compilerOutput": result.compile.compiler_output,
                      "undefinedSteps": result.dry_run.undefined_steps}, ensure_ascii=False))
    return 0


def _cmd_auth_env(args) -> int:
    print(auth_env_exports(args.sut_file))
    return 0


def _cmd_gen_dir(args) -> int:
    print(generation_dir(args.sut, args.gen_id))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.scenarios")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("prepare", _cmd_prepare), ("finalize", _cmd_finalize), ("validate", _cmd_validate)):
        command = sub.add_parser(name)
        command.add_argument("gen_dir")
        command.add_argument("out_dir")
        if name != "validate":
            command.add_argument("gen_id")
        command.set_defaults(fn=fn)
    auth = sub.add_parser("auth-env")
    auth.add_argument("sut_file")
    auth.set_defaults(fn=_cmd_auth_env)
    gen = sub.add_parser("gen-dir")
    gen.add_argument("sut")
    gen.add_argument("gen_id")
    gen.set_defaults(fn=_cmd_gen_dir)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except ScenariosError as exc:
        print(f"td.scenarios: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
