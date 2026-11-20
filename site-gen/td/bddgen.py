"""S06 BDD 생성(설계 §6.6, §13.4, §13.5, REQ-022/023/024/025/061/075, Review Focus 2).

흐름(arm × rep 하나):
  1. 번들: S06 단계가 arm마다 `td.bundle build`(조립 + 경로·내용 검사 + 서명)로 `S06/bundles/<arm>/`을 만든다.
     실패하면 그 arm은 failed이고 LLM을 부르지 않는다.
  2. 생성: `pipeline/lib/llm.sh <bundle> prompts/bdd-gen.md <out>`(모든 claude 호출의 유일한 통로).
  3. 출력 파싱: 결과 텍스트는 `genfiles.schema.json`({files:[{path, content}]})이어야 한다. 잘린 JSON이나 스키마 위반이면
     그 generation은 failed다(사유 포함). 수리 호출로 고치지 않는다(수리 횟수에 넣지 않는다).
  4. 검증: 임시 디렉터리에 파일을 쓰고 `scenarios.validate_generation`(javac 컴파일 확인 + Cucumber dry-run, SUT 불필요).
  5. 수리: 문제가 남으면 최대 2회 `prompts/bdd-repair.md`로 다시 부른다. 수리 입력은 컴파일러 출력, dry-run undefined 목록,
     직전 생성물(LLM 자신의 출력)뿐이다. SUT 실행 결과는 넣지 않는다(llm.sh가 번들을 뒤에 붙이는 것은 같다).
  6. 확정: `_COMPLETE`(전체 입력 해시 + 파일별 sha256 + 생성 메타)를 쓰고 `e2e/generated/<sut>/<arm>/<genId>/`로 원자적 rename.

스냅샷 규칙:
- 입력 해시(전체 64자) = sha256({번들 해시, 생성 프롬프트 해시, 수리 프롬프트 해시, 모델, 수리 상한}). genId는
  `<arm>-<inputHash8>-r<rep>[-g<n>]`이다. 프롬프트나 모델이 바뀌면 새 genId가 되어 옛 스냅샷을 잘못 재사용하지 않는다.
- 재사용은 `_COMPLETE`가 있고 입력 해시와 파일 체크섬이 모두 맞는 디렉터리만 한다. 최종 경로에는 rename으로만 디렉터리가
  생기므로 부분 디렉터리는 최종 경로에 없다. 최종 경로가 있는데 `_COMPLETE`가 맞지 않으면(변조) 재사용도 덮어쓰기도 하지 않고
  그 generation을 failed로 둔다.
- 예약: `<arm>/.reserve/<genId>`를 원자적 `mkdir`로 잡은 프로세스만 그 genId를 만든다. 같은 입력의 다른 프로세스는 예약이
  풀릴 때까지 기다렸다가 완성된 스냅샷을 재사용한다. `--regenerate`는 비어 있는 가장 작은 `-g<n>`을 예약한다(기존 디렉터리는
  건드리지 않는다). 예약 주인이 SIGKILL로 죽어 남은 예약은 같은 호스트에서 pid가 없으면 rename으로 회수한다.
- 임시 디렉터리 `<arm>/.tmp-<genId>-…`와 `.reserve/`는 커밋하지 않는다(.gitignore).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

from td import snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
MAX_REPAIRS = 2
COMPLETE_NAME = snapshot.COMPLETE_NAME
RESERVE_DIR = snapshot.RESERVE_DIR
TMP_PREFIX = snapshot.TMP_PREFIX
COMPILER_OUTPUT_LIMIT = 20000   # 수리 프롬프트에 넣는 컴파일러 출력 상한(문자)
UNDEFINED_LIMIT = 200


class BddGenError(RuntimeError):
    """generation 하나를 실패로 만드는 오류(사유 문자열)."""


class GenOutputError(BddGenError):
    """LLM 출력이 파일 목록 계약을 어겼다(잘린 JSON, 스키마 위반). 수리하지 않고 그 generation을 실패로 둔다."""


class LlmCallError(BddGenError):
    pass


# --- 경로와 해시 ------------------------------------------------------------------------------------
_root = snapshot.root


def prompt_paths() -> tuple[Path, Path]:
    return _root() / "prompts" / "bdd-gen.md", _root() / "prompts" / "bdd-repair.md"


def generated_root(sut: str) -> Path:
    """`e2e/generated/<sut>`(TD_E2E_GENERATED_DIR가 있으면 그 아래). td.scenarios.generation_dir와 같은 규칙이다."""
    base = os.environ.get("TD_E2E_GENERATED_DIR") or str(_root() / "e2e" / "generated")
    return Path(base) / sut


sha256_bytes = snapshot.sha256_bytes


def generation_key(bundle_hash: str, gen_prompt: bytes, repair_prompt: bytes, model: str) -> str:
    material = {"bundle": bundle_hash, "prompt": sha256_bytes(gen_prompt), "repairPrompt": sha256_bytes(repair_prompt),
                "model": model, "maxRepairs": MAX_REPAIRS}
    return sha256_bytes(json.dumps(material, sort_keys=True).encode("utf-8"))


def gen_id_for(arm: str, key: str, rep: int, gen: int | None = None) -> str:
    if not 1 <= int(rep) <= 9:
        raise ValueError(f"rep은 1~9다: {rep}")
    return f"{arm}-{key[:8]}-r{rep}" + (f"-g{gen}" if gen else "")


# --- LLM 출력 계약 ---------------------------------------------------------------------------------
def _genfiles_schema() -> dict:
    return json.loads((SCHEMA_DIR / "genfiles.schema.json").read_text(encoding="utf-8"))


_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(?P<body>.*)\n```\s*$", re.DOTALL)


def parse_output(text: str) -> list[dict]:
    """LLM 결과 텍스트 -> [{path, content}]. 감싼 코드 펜스 하나는 벗긴다. 계약 위반이면 GenOutputError."""
    body = (text or "").strip()
    fenced = _FENCE_RE.match(body)
    if fenced:
        body = fenced.group("body").strip()
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise GenOutputError(f"LLM 출력이 JSON이 아니다(잘렸거나 형식 오류, {len(body)}자): {exc.msg} at char {exc.pos}") from exc
    try:
        jsonschema.validate(data, _genfiles_schema())
    except jsonschema.ValidationError as exc:
        where = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise GenOutputError(f"파일 목록 스키마 위반({where}): {exc.message[:300]}") from exc
    files = data["files"]
    paths = [item["path"] for item in files]
    duplicated = sorted({p for p in paths if paths.count(p) > 1})
    if duplicated:
        raise GenOutputError(f"파일 목록 스키마 위반(path 중복): {', '.join(duplicated)}")
    if not any(p.startswith("features/") for p in paths):
        raise GenOutputError("파일 목록 스키마 위반(features/*.feature가 하나도 없다)")
    return [{"path": item["path"], "content": item["content"]} for item in files]


def count_scenarios(files: list[dict]) -> int:
    """파일 목록의 시나리오(pickle) 수. Scenario Outline은 Examples 행마다 하나다(S07 집계 단위와 같다)."""
    from td import testid
    return sum(len(testid.pickles(item["content"])) for item in files if item["path"].endswith(".feature"))


def write_files(target: Path, files: list[dict]) -> None:
    """generation 파일을 target에 쓴다(features/, glue/만 비우고 다시 쓴다)."""
    for sub in ("features", "glue"):
        shutil.rmtree(target / sub, ignore_errors=True)
    for item in files:
        path = target / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item["content"], encoding="utf-8")


tree_files = snapshot.tree_files


# --- LLM 호출(td.snapshot.call_llm) -----------------------------------------------------------------
LlmReply = snapshot.LlmReply


def call_llm(bundle_dir: Path, prompt_file: Path, out_json: Path) -> LlmReply:
    """llm.sh로 한 번 부른다(격리, 서명 검사, 호출 기록은 llm.sh가 맡는다)."""
    try:
        return snapshot.call_llm(bundle_dir, prompt_file, out_json)
    except snapshot.LlmCallError as exc:
        raise LlmCallError(str(exc)) from exc


# --- 검증 -----------------------------------------------------------------------------------------
@dataclass
class Issues:
    compiler_output: str = ""
    excluded: list[str] = field(default_factory=list)
    undefined: list[dict] = field(default_factory=list)
    layout: str | None = None

    @property
    def clean(self) -> bool:
        return not self.excluded and not self.undefined and not self.layout and not self.compiler_output.strip()


_CLASSPATH_CACHE: dict[str, str] = {}


def _classpath(work: Path) -> str:
    """runner 컴파일 클래스패스(Gradle 1회). 한 프로세스 안에서는 다시 구하지 않는다."""
    from td import scenarios
    key = str(scenarios.e2e_dir())
    if key not in _CLASSPATH_CACHE:
        _CLASSPATH_CACHE[key] = scenarios.runner_classpath(work / "classpath.txt")
    return _CLASSPATH_CACHE[key]


def validate(gen_dir: Path, out_dir: Path) -> Issues:
    """SUT 없이 검증한다. 배치 규약 위반은 수리 대상(Issues.layout), 검증 도구 자체의 실패는 BddGenError다."""
    from td import scenarios
    try:
        result = scenarios.validate_generation(gen_dir, out_dir, classpath=_classpath(out_dir.parent))
    except scenarios.LayoutError as exc:
        return Issues(layout=f"layout violation: {exc}")
    except scenarios.ScenariosError as exc:
        raise BddGenError(f"검증 실행 실패: {str(exc)[:800]}") from exc
    return Issues(result.compile.compiler_output if result.compile.excluded else "", list(result.compile.excluded),
                  list(result.dry_run.undefined_steps))


def render_repair(template: str, issues: Issues, files: list[dict]) -> str:
    compiler = issues.compiler_output.strip()
    if issues.layout:
        compiler = (issues.layout + "\n" + compiler).strip()
    if len(compiler) > COMPILER_OUTPUT_LIMIT:
        compiler = compiler[:COMPILER_OUTPUT_LIMIT] + "\n... (truncated)"
    undefined = "\n".join(f"- {item.get('feature')}:{item.get('line')}: {item.get('step')}"
                          for item in issues.undefined[:UNDEFINED_LIMIT])
    previous = "\n".join(f"--- path: {item['path']} ---\n{item['content'].rstrip()}\n--- end: {item['path']} ---"
                         for item in files)
    return (template.replace("{{COMPILER_OUTPUT}}", compiler or "(none)")
            .replace("{{UNDEFINED_STEPS}}", undefined or "(none)")
            .replace("{{PREVIOUS_FILES}}", previous))


# --- 스냅샷: _COMPLETE와 예약(td.snapshot 공용 부품) -----------------------------------------------
complete_problem = snapshot.complete_problem
try_reserve = snapshot.try_reserve
release = snapshot.release


# --- generation 하나 --------------------------------------------------------------------------------
@dataclass
class Generation:
    gen_id: str
    dir: Path | None
    repairs: int
    tokens: dict
    seconds: float
    status: str = "passed"          # passed | degraded | failed
    reason: str | None = None
    reused: bool = False
    record: dict = field(default_factory=dict)


@dataclass
class GenContext:
    """generation이 공유하는 고정 입력(모델, CLI 버전, 플래그, 정제 필드)과 주입 가능한 호출자."""
    model: str
    cli_version: str
    flags: list[str]
    stripped_fields: list[str]
    work_dir: Path
    llm: object = call_llm
    validator: object = validate
    wait_timeout: float = 3600.0


def _base_record(arm: str, rep: int, gen: int | None, gen_id: str, key: str, bundle_hash: str, ctx: GenContext) -> dict:
    gen_prompt, repair_prompt = prompt_paths()
    return {"genId": gen_id, "arm": arm, "rep": rep, "gen": gen, "inputHash": key, "bundleHash": bundle_hash,
            "promptHash": sha256_bytes(gen_prompt.read_bytes()), "repairPromptHash": sha256_bytes(repair_prompt.read_bytes()),
            "model": ctx.model, "cliVersion": ctx.cli_version, "flags": list(ctx.flags),
            "strippedFields": list(ctx.stripped_fields), "repairs": 0, "tokens": {"in": 0, "out": 0}, "seconds": 0.0}


def _reuse(final: Path, key: str) -> Generation:
    meta = snapshot.read_complete_meta(final)
    record = {**meta, "reused": True, "dir": str(final)}
    return Generation(record["genId"], final, record["repairs"], record["tokens"], record["seconds"],
                      record["status"], record.get("reason"), True, record)


def _failed(record: dict, reason: str, started: float) -> Generation:
    record.update(status="failed", reason=reason[:1500], reused=False, seconds=round(time.monotonic() - started, 3), dir=None)
    return Generation(record["genId"], None, record["repairs"], record["tokens"], record["seconds"], "failed",
                      record["reason"], False, record)


def _produce(arm: str, rep: int, gen: int | None, gen_id: str, key: str, bundle_dir: Path, bundle_hash: str,
             arm_dir: Path, ctx: GenContext) -> Generation:
    """예약을 쥔 상태에서 실제로 생성한다. 성공하면 최종 경로로 rename, 실패하면 임시 디렉터리를 지운다."""
    started = time.monotonic()
    record = _base_record(arm, rep, gen, gen_id, key, bundle_hash, ctx)
    gen_prompt, repair_prompt = prompt_paths()
    work = ctx.work_dir / gen_id
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    tmp = snapshot.make_tmp(arm_dir, gen_id)
    try:
        def ask(prompt_file: Path, label: str) -> list[dict]:
            reply = ctx.llm(bundle_dir, prompt_file, work / f"{label}.json")
            record["tokens"]["in"] += reply.tokens_in
            record["tokens"]["out"] += reply.tokens_out
            return parse_output(reply.text)

        try:
            files = ask(gen_prompt, "llm-gen")
        except BddGenError as exc:
            return _failed(record, str(exc), started)
        initial_scenarios = count_scenarios(files)
        record["scenarios"] = {"initial": initial_scenarios, "final": initial_scenarios}
        attempt = 0
        while True:
            write_files(tmp, files)
            try:
                issues = ctx.validator(tmp, work / f"validate-{attempt}")
            except BddGenError as exc:
                return _failed(record, str(exc), started)
            if issues.clean or record["repairs"] >= MAX_REPAIRS:
                break
            attempt += 1
            prompt_file = work / f"repair-{attempt}.md"
            prompt_file.write_text(render_repair(repair_prompt.read_text(encoding="utf-8"), issues, files), encoding="utf-8")
            record["repairs"] += 1
            try:
                files = ask(prompt_file, f"llm-repair-{attempt}")
            except BddGenError as exc:
                return _failed(record, f"수리 {attempt}회차: {exc}", started)
        if issues.layout:
            return _failed(record, f"수리 {record['repairs']}회 뒤에도 glue 배치 규약 위반이 남았다: {issues.layout[:600]}", started)
        final_scenarios = count_scenarios(files)
        record["scenarios"] = {"initial": initial_scenarios, "final": final_scenarios}
        problems = []
        if not issues.clean:
            problems.append(f"수리 {record['repairs']}회 뒤 남은 문제: 컴파일 제외 클래스 {len(issues.excluded)}개"
                            f"({', '.join(issues.excluded)[:300]}), undefined step {len(issues.undefined)}개")
        if final_scenarios < initial_scenarios:
            # A2: 수리가 시나리오를 지워 지표를 좋게 만드는 것을 막는다(지운 수만큼 분모가 줄어든다).
            problems.append(f"repair dropped {initial_scenarios - final_scenarios} scenarios "
                            f"({initial_scenarios} -> {final_scenarios})")
        status, reason = ("degraded", "; ".join(problems)) if problems else ("passed", None)
        record.update(status=status, reason=reason, reused=False, seconds=round(time.monotonic() - started, 3),
                      remaining={"uncompilableClasses": issues.excluded, "undefinedSteps": len(issues.undefined)},
                      files=len(files))
        final = arm_dir / gen_id
        if final.exists():
            raise BddGenError(f"예약을 쥔 채로 최종 디렉터리가 이미 있다: {gen_id}")
        snapshot.write_complete(tmp, key, {**record, "dir": None}, genId=gen_id)
        os.rename(tmp, final)
        record["dir"] = str(final)
        return Generation(gen_id, final, record["repairs"], record["tokens"], record["seconds"], status, reason, False, record)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def generate(arm: str, rep: int, bundle, out_root, regenerate: bool = False, *, ctx: GenContext) -> Generation:
    """arm×rep 하나의 generation을 재사용하거나 만든다. bundle은 td.bundle.Bundle(검사·서명 완료), out_root는
    `e2e/generated/<sut>`다. 반환 Generation.record는 bdd-gen.json의 항목이다."""
    gen_prompt, repair_prompt = prompt_paths()
    key = generation_key(bundle.input_hash, gen_prompt.read_bytes(), repair_prompt.read_bytes(), ctx.model)
    arm_dir = Path(out_root) / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    base_id = gen_id_for(arm, key, rep)
    require_snapshot = os.environ.get("TD_BDDGEN_REQUIRE_SNAPSHOT") == "1"
    if regenerate and require_snapshot:
        record = _base_record(arm, rep, None, base_id, key, bundle.input_hash, ctx)
        return _failed(record, "TD_BDDGEN_REQUIRE_SNAPSHOT=1에서는 --regenerate(새 generation)를 할 수 없다", time.monotonic())
    if regenerate:
        gen = 1
        while True:
            gen_id = gen_id_for(arm, key, rep, gen)
            if not (arm_dir / gen_id).exists():
                lock = try_reserve(arm_dir, gen_id)
                if lock is not None:
                    try:
                        if not (arm_dir / gen_id).exists():
                            return _produce(arm, rep, gen, gen_id, key, Path(bundle.path), bundle.input_hash, arm_dir, ctx)
                    finally:
                        release(lock)
            gen += 1
    final = arm_dir / base_id
    deadline = time.monotonic() + ctx.wait_timeout
    while True:
        if final.exists():
            problem = complete_problem(final, key)
            if problem is None:
                return _reuse(final, key)
            record = _base_record(arm, rep, None, base_id, key, bundle.input_hash, ctx)
            return _failed(record, f"스냅샷이 있지만 재사용할 수 없다(덮어쓰지 않는다): {problem}", time.monotonic())
        if require_snapshot:
            record = _base_record(arm, rep, None, base_id, key, bundle.input_hash, ctx)
            return _failed(record, f"TD_BDDGEN_REQUIRE_SNAPSHOT=1인데 입력 키의 스냅샷이 없다(입력이 바뀌었다): {base_id}",
                           time.monotonic())
        lock = try_reserve(arm_dir, base_id)
        if lock is not None:
            try:
                if final.exists():
                    continue
                return _produce(arm, rep, None, base_id, key, Path(bundle.path), bundle.input_hash, arm_dir, ctx)
            finally:
                release(lock)
        if time.monotonic() > deadline:
            record = _base_record(arm, rep, None, base_id, key, bundle.input_hash, ctx)
            return _failed(record, f"다른 프로세스의 예약이 {int(ctx.wait_timeout)}초 동안 풀리지 않았다: {base_id}", time.monotonic())
        time.sleep(1.0)


# --- S06 단계 --------------------------------------------------------------------------------------
_cli_version = snapshot.cli_version
_sanitize_info = snapshot.sanitize_info


def build_bundle(arm: str, run_dir: Path, sut_src: Path, sut_file: Path):
    """`td.bundle build` CLI(조립 + 검사 + 서명)를 그대로 쓴다. 실패면 BddGenError(사유)."""
    try:
        return snapshot.build_bundle(arm, run_dir, run_dir / "S06" / "bundles" / arm, sut_src, sut_file,
                                     run_dir / "S06" / f"bundle-{arm}")
    except snapshot.BundleBuildError as exc:
        raise BddGenError(str(exc)) from exc


def _unexpected_failure(arm: str, rep: int, built, ctx: GenContext, exc: Exception) -> Generation:
    gen_prompt, repair_prompt = prompt_paths()
    key = generation_key(built.input_hash, gen_prompt.read_bytes(), repair_prompt.read_bytes(), ctx.model)
    record = _base_record(arm, rep, None, gen_id_for(arm, key, rep), key, built.input_hash, ctx)
    return _failed(record, f"예상하지 못한 오류: {type(exc).__name__}: {str(exc)[:1000]}", time.monotonic())


def run_stage(run_dir, sut_file, sut_src, regenerate: bool, *, llm=call_llm, validator=validate) -> dict:
    """S06 전체: arm별 번들 -> rep별 generation. 반환 {status, reason, extra, outputs}. bdd-gen.json과 run.json도 쓴다."""
    from td import prepare, state, sut_config
    run_dir, sut_src = Path(run_dir), Path(sut_src)
    (run_dir / "S06").mkdir(parents=True, exist_ok=True)
    sut = sut_config.load(sut_file).name
    out_root = generated_root(sut)
    reps = state.requested_reps(run_dir)
    sanitize = _sanitize_info(run_dir)
    ctx = GenContext(model=prepare.resolve_model(_root() / "pipeline" / "config.yaml"), cli_version=_cli_version(run_dir),
                     flags=list(prepare.CLAUDE_FLAGS), stripped_fields=sanitize["strippedFields"],
                     work_dir=run_dir / "S06" / "work", llm=llm, validator=validator,
                     wait_timeout=float(os.environ.get("TD_BDDGEN_WAIT_SEC", "3600")))
    arms: dict[str, dict] = {}
    generations: dict[str, dict] = {}
    records: list[dict] = []
    inputs: dict[str, dict] = {}
    for arm, skip_reason in state.arm_plan(run_dir).items():
        if skip_reason:
            arms[arm] = {"status": "skipped", "reason": skip_reason}
            continue
        try:
            built = build_bundle(arm, run_dir, sut_src, Path(sut_file))
        except BddGenError as exc:
            arms[arm] = {"status": "failed", "reason": str(exc)[:1500], "generations": []}
            continue
        inputs[arm] = {"bundleHash": built.input_hash, "bundle": f"S06/bundles/{arm}"}
        ids: list[str] = []
        failures: list[str] = []
        for rep in range(1, reps + 1):
            try:
                result = generate(arm, rep, built, out_root, regenerate, ctx=ctx)
            except Exception as exc:  # noqa: BLE001 - 예상 밖 오류도 그 generation의 실패로 기록하고 다른 rep는 진행한다
                result = _unexpected_failure(arm, rep, built, ctx, exc)
            records.append(result.record)
            inputs[arm]["inputHash"] = result.record["inputHash"]
            entry = {"arm": arm, "rep": rep, "status": result.status, "reused": result.reused, "repairs": result.repairs,
                     "dir": str(result.dir) if result.dir else None}
            if result.reason:
                entry["reason"] = result.reason
            generations[result.gen_id] = entry
            if result.status == "failed":
                failures.append(f"{result.gen_id}: {result.reason}")
            else:
                ids.append(result.gen_id)
        if not failures:
            arms[arm] = {"status": "passed", "generations": ids}
        elif ids:
            arms[arm] = {"status": "degraded", "reason": "; ".join(failures)[:1500], "generations": ids}
        else:
            arms[arm] = {"status": "failed", "reason": "; ".join(failures)[:1500], "generations": []}

    meta = {"schema": 1, "runId": state.read_run(run_dir).get("runId"), "sut": sut, "reps": reps, "regenerate": regenerate,
            "maxRepairs": MAX_REPAIRS, "strippedFields": sanitize["strippedFields"],
            "forbiddenDeclared": sanitize["forbiddenDeclared"], "generations": records}
    jsonschema.validate(meta, json.loads((SCHEMA_DIR / "bdd-gen.schema.json").read_text(encoding="utf-8")))
    (run_dir / "S06" / "bdd-gen.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runnable = {arm: state_["generations"] for arm, state_ in arms.items() if state_.get("generations")}
    state.set_run_field(run_dir, "arms.generations", runnable)
    state.set_run_field(run_dir, "arms.style", state.read_run(run_dir).get("options", {}).get("style") or "cucumber")
    state.set_run_field(run_dir, "inputs", inputs)

    attempted = [a for a in arms.values() if a["status"] != "skipped"]
    problems = [f"{arm}: {a['reason']}" for arm, a in arms.items() if a["status"] in ("failed", "degraded")]
    problems += [f"{gen_id} degraded: {g.get('reason')}" for gen_id, g in generations.items() if g["status"] == "degraded"]
    if not any(a.get("generations") for a in attempted):
        status, reason = "failed", "; ".join(problems)[:1500] or "생성된 generation이 없다"
    elif problems:
        status, reason = "degraded", "; ".join(problems)[:1500]
    else:
        status, reason = "passed", None
    return {"status": status, "reason": reason, "extra": {"arms": arms, "generations": generations},
            "outputs": {"bddGen": str(run_dir / "S06" / "bdd-gen.json")}}


def _regenerate_requested(run_dir: Path) -> bool:
    from td import state
    if os.environ.get("TD_REGENERATE"):
        return os.environ["TD_REGENERATE"] == "true"
    return bool(state.read_run(run_dir).get("options", {}).get("regenerate"))


_on_term = snapshot.on_term


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.bddgen")
    sub = parser.add_subparsers(dest="command", required=True)
    stage = sub.add_parser("stage", help="S06 전체 실행. stdout: {status, reason, extra, outputs}")
    stage.add_argument("--run-dir", required=True)
    stage.add_argument("--sut-file", required=True)
    stage.add_argument("--sut-src", required=True)
    parse = sub.add_parser("parse", help="LLM 결과 텍스트 파일을 파일 목록 계약으로 검사")
    parse.add_argument("file")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _on_term)
    if args.command == "parse":
        try:
            files = parse_output(Path(args.file).read_text(encoding="utf-8"))
        except GenOutputError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(json.dumps([item["path"] for item in files]))
        return 0
    try:
        result = run_stage(args.run_dir, args.sut_file, args.sut_src, _regenerate_requested(Path(args.run_dir)))
    except Exception as exc:  # noqa: BLE001 - 단계 실패 사유로 기록한다
        print(json.dumps({"status": "failed", "reason": f"S06 실행 오류: {type(exc).__name__}: {str(exc)[:1200]}",
                          "extra": {}, "outputs": {}}, ensure_ascii=False))
        return 0
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
