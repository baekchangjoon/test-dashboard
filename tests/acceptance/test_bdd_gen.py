"""BDD 생성 계열 수용 테스트: REQ-075(입력 해시 안정성)의 S02·번들 부분, Task 22의 S06 생성(REQ-022 단계 캡처,
REQ-024, REQ-025, REQ-061, Review Focus 2). REQ-023(세 arm·반복)은 Task 25의 E2E가 맡는다.
"""
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest

from test_isolation import FIXTURE_SUT, make_run_dir


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_req075_input_hash_stable(s02_stage, fake_claude):
    """S02 부분: 같은 SUT 커밋을 서로 다른 체크아웃 경로에 두고 두 번 돌리면 clean/의 sha256이 같다."""
    first = s02_stage(checkout="alpha/checkout-one")
    second = s02_stage(checkout="zz/much/deeper/other-name")
    assert first.stage["status"] == second.stage["status"] == "passed"
    assert first.sut_src != second.sut_src and len(str(first.sut_src)) != len(str(second.sut_src))
    first_hash, second_hash = _tree_sha256(first.clean_dir), _tree_sha256(second.clean_dir)
    assert first_hash == second_hash
    # 정제 결과 요약(제거 필드와 개수)도 같다
    assert first.manifest["sanitize"] == second.manifest["sanitize"]
    assert fake_claude.calls == []


def test_req075_bundle_hash_stable_across_checkouts(s02_stage, tmp_path, fake_claude):
    """번들 부분: 같은 SUT 커밋을 서로 다른 체크아웃 경로에서 S02 -> 번들 조립하면 arm별 입력 해시가 같다.
    S03/S05 산출물은 같은 고정 입력을 두 run에 둔다(S03 단독 안정성은 Task 3의 결정적 정렬이 맡는다)."""
    import shutil
    from td import bundle

    runs = [s02_stage(checkout="alpha/checkout-one"), s02_stage(checkout="zz/much/deeper/other-name")]
    ontology = '{"edges": [], "meta": {"commit": "b6f9393"}, "nodes": []}\n'
    for run in runs:
        assert run.stage["status"] == "passed", run.stage
        (run.run_dir / "S03").mkdir(exist_ok=True)
        (run.run_dir / "S03" / "ontology-jqa.json").write_text(ontology)
    assert runs[0].sut_src != runs[1].sut_src
    for arm in ("base", "jqa"):
        hashes = [bundle.assemble(arm, run.run_dir, tmp_path / f"b-{arm}-{index}").input_hash
                  for index, run in enumerate(runs)]
        assert hashes[0] == hashes[1], arm
        # 정제 산출물에 체크아웃 경로가 새지 않는다
        for run in runs:
            for path in (tmp_path / f"b-{arm}-0").rglob("*.json"):
                assert str(run.sut_src) not in path.read_text()
    assert bundle.assemble("base", runs[0].run_dir, tmp_path / "x").input_hash != \
        bundle.assemble("jqa", runs[0].run_dir, tmp_path / "y").input_hash
    assert fake_claude.calls == []


# =====================================================================================
# Task 22: S06 BDD 생성(REQ-022 S06 단계 캡처, REQ-024, REQ-025, REQ-061, Review Focus 2)
# 가짜 claude(PATH 앞)로 S06 단계 스크립트를 가짜 run 디렉터리에서 실행한다. 검증(컴파일 확인, dry-run)은 실제 Gradle/javac다.
# 스냅샷 루트는 TD_E2E_GENERATED_DIR(임시)로 돌려 repo의 e2e/generated를 건드리지 않는다.
# =====================================================================================
REPO_ROOT = Path(__file__).resolve().parents[2]
S06_SCRIPT = REPO_ROOT / "pipeline" / "S06-bdd-gen.sh"
PETCLINIC_SUT_FILE = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"
SCHEMAS = REPO_ROOT / "site-gen" / "td" / "schemas"
PROMPTS = REPO_ROOT / "prompts"
GEN_ID_RE = re.compile(r"^(base|jqa|owl)-[0-9a-f]{8}-r[1-9](-g[0-9]+)?$")
SUT_RESPONSE_MARKER = "SUT-RESPONSE-MARKER-7f3a9c"

VALID_FEATURE = """\
Feature: Sample flow

  Scenario: list items
    When I request the item list
    Then the item list status is 200
"""
VALID_STEPS = """\
package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class SampleFlowSteps {

    private Response response;

    @When("I request the item list")
    public void requestItemList() {
        response = Harness.authed().get("/api/items");
    }

    @Then("the item list status is {int}")
    public void statusIs(int expected) {
        assertThat(response.statusCode()).isEqualTo(expected);
    }
}
"""
BROKEN_STEPS = "package glue;\n\npublic class SampleFlowSteps {\n    this does not compile\n}\n"
UNDEFINED_FEATURE = VALID_FEATURE + "    And nothing defines this step\n"


def files_payload(steps: str = VALID_STEPS, feature: str = VALID_FEATURE, extra: list | None = None) -> str:
    files = [{"path": "features/sample_flow.feature", "content": feature},
             {"path": "glue/SampleFlowSteps.java", "content": steps}] + (extra or [])
    return json.dumps({"files": files})


def claude_result(text: str, tokens_in: int = 1000, tokens_out: int = 200) -> dict:
    """claude --output-format json 결과 모양(가짜)."""
    return {"type": "result", "subtype": "success", "is_error": False, "result": text, "duration_ms": 10,
            "usage": {"input_tokens": tokens_in, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 7,
                      "output_tokens": tokens_out},
            "modelUsage": {"claude-opus-5-5": {}}}


VALID = claude_result(files_payload())
BROKEN = claude_result(files_payload(steps=BROKEN_STEPS))


class S06Env:
    """가짜 run 디렉터리(S02 정제 산출물, S03/S05 온톨로지)를 만들고 pipeline/S06-bdd-gen.sh를 실행한다."""

    def __init__(self, tmp_path: Path, generated: Path | None = None):
        self.tmp_path = tmp_path
        self.generated = generated or tmp_path / "generated"
        self.count = 0

    def new_run(self, arms=("base",), reps: int = 1, regenerate: bool = False) -> Path:
        self.count += 1
        run_dir = make_run_dir(self.tmp_path, f"run-{self.count}")
        options = {"arms": list(arms), "reps": reps, "style": "cucumber", "regenerate": regenerate, "only": None}
        init = subprocess.run([sys.executable, "-m", "td.state", "init", str(run_dir), "--run-id", run_dir.name,
                               "--sut", "petclinic", "--commit", "b6f939355e8790202ddfc71e3f3507252745ed37",
                               "--options-json", json.dumps(options)],
                              capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "site-gen")})
        assert init.returncode == 0, init.stderr
        (run_dir / "stages").mkdir(exist_ok=True)
        for stage in ("S00", "S02", "S03"):
            (run_dir / "stages" / f"{stage}.json").write_text(json.dumps({"id": stage, "status": "passed", "reason": None, "outputs": {}}))
        (run_dir / "tools.lock").write_text("schema: 1\nclaude:\n  version: 9.9.9-test\n  model: claude-opus-5-5\n")
        # SUT 응답 표식: 이전 실행 결과처럼 run 디렉터리에 둔다. 수리 입력에 섞이면 안 된다(REQ-025).
        (run_dir / "S07" / "base-00000000-r1").mkdir(parents=True)
        (run_dir / "S07" / "base-00000000-r1" / "cucumber.json").write_text(json.dumps([{"body": SUT_RESPONSE_MARKER}]))
        (run_dir / "S07" / "base-00000000-r1" / "gradle.log").write_text(f"response body: {SUT_RESPONSE_MARKER}\n")
        return run_dir

    def env(self, run_dir: Path, **extra: str) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
        env.update(TD_ROOT=str(REPO_ROOT), TD_RUN_DIR=str(run_dir), TD_WORK_DIR=str(run_dir.parent),
                   TD_SUT_SRC=str(FIXTURE_SUT), TD_SUT_FILE=str(PETCLINIC_SUT_FILE),
                   TD_E2E_GENERATED_DIR=str(self.generated), TD_SITE_PREFIX="_test/s06/", **extra)
        return env

    def run(self, run_dir: Path, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(S06_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True,
                              env=self.env(run_dir, **extra), timeout=1500)

    def popen(self, run_dir: Path, **extra: str) -> subprocess.Popen:
        return subprocess.Popen(["bash", str(S06_SCRIPT), "petclinic", run_dir.name], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.env(run_dir, **extra))

    @staticmethod
    def stage(run_dir: Path) -> dict:
        return json.loads((run_dir / "stages" / "S06.json").read_text())

    @staticmethod
    def meta(run_dir: Path) -> dict:
        return json.loads((run_dir / "S06" / "bdd-gen.json").read_text())


def tree_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def leftovers(generated: Path) -> list[str]:
    """예약 잠금이나 임시 디렉터리가 남았는지(정상 종료 뒤에는 없어야 한다)."""
    return sorted(p.relative_to(generated).as_posix() for p in generated.rglob("*")
                  if p.is_dir() and (p.name.startswith(".tmp-") or p.parent.name == ".reserve"))


@pytest.fixture
def s06(tmp_path) -> S06Env:
    return S06Env(tmp_path)


def test_req024_snapshot_reuse_preserve(s06, fake_claude):
    fake_claude.respond(VALID)
    first_run = s06.new_run()
    done = s06.run(first_run)
    assert done.returncode == 0, done.stderr[-3000:]
    stage = s06.stage(first_run)
    assert stage["status"] == "passed", stage
    [(gen_id, gen)] = stage["generations"].items()
    assert GEN_ID_RE.match(gen_id) and gen_id.endswith("-r1") and gen["status"] == "passed" and gen["reused"] is False
    snapshot = s06.generated / "petclinic" / "base" / gen_id
    assert Path(gen["dir"]) == snapshot and (snapshot / "_COMPLETE").is_file()
    complete = json.loads((snapshot / "_COMPLETE").read_text())
    assert complete["inputHash"].startswith(gen_id.split("-")[1]) and len(complete["inputHash"]) == 64
    assert {item["path"] for item in complete["files"]} == {"features/sample_flow.feature", "glue/SampleFlowSteps.java"}
    assert len(fake_claude.calls) == 1
    before = tree_hashes(snapshot)

    # 같은 입력으로 다시 실행: claude 0회, 같은 genId 재사용
    second_run = s06.new_run()
    done = s06.run(second_run)
    assert done.returncode == 0, done.stderr[-3000:]
    again = s06.stage(second_run)
    assert list(again["generations"]) == [gen_id] and again["generations"][gen_id]["reused"] is True
    assert len(fake_claude.calls) == 1
    assert s06.meta(second_run)["generations"][0]["reused"] is True

    # --regenerate 두 개를 병렬로: 서로 다른 -g<n>, 기존 디렉터리는 바이트 그대로
    fake_claude.delay(3)
    runs = [s06.new_run(regenerate=True), s06.new_run(regenerate=True)]
    procs = [s06.popen(run_dir) for run_dir in runs]
    outs = [proc.communicate(timeout=1500) for proc in procs]
    assert all(proc.returncode == 0 for proc in procs), [out[1][-2000:] for out in outs]
    new_ids = [next(iter(s06.stage(run_dir)["generations"])) for run_dir in runs]
    assert sorted(new_ids) == [f"{gen_id}-g1", f"{gen_id}-g2"], new_ids
    assert len(fake_claude.calls) == 3
    assert tree_hashes(snapshot) == before
    for new_id in new_ids:
        assert (s06.generated / "petclinic" / "base" / new_id / "_COMPLETE").is_file()
    assert leftovers(s06.generated) == []

    # 스냅샷이 변조되면 재사용하지 않고 덮어쓰지도 않는다(그 generation만 failed, claude 0회)
    tampered = snapshot / "glue" / "SampleFlowSteps.java"
    tampered.write_text(tampered.read_text() + "// tampered\n")
    third_run = s06.new_run()
    done = s06.run(third_run)
    failed = s06.stage(third_run)
    assert failed["generations"][gen_id]["status"] == "failed" and "_COMPLETE" in failed["generations"][gen_id]["reason"]
    assert failed["status"] == "failed" and done.returncode != 0
    assert len(fake_claude.calls) == 3 and tampered.read_text().endswith("// tampered\n")


def test_req024_concurrent_same_input_writes_once(tmp_path, fake_claude):
    """같은 입력으로 동시에 생성하면 하나만 쓰고(claude 1회) 다른 하나는 기다렸다가 재사용한다. 부분 디렉터리는 재사용하지 않는다."""
    env = S06Env(tmp_path)
    fake_claude.respond(VALID)
    fake_claude.delay(4)
    # 이전 실행이 남긴 임시 디렉터리(부분 결과)는 무시돼야 한다
    stale_tmp = env.generated / "petclinic" / "base" / ".tmp-leftover"
    (stale_tmp / "features").mkdir(parents=True)
    (stale_tmp / "features" / "x.feature").write_text("Feature: partial\n")
    runs = [env.new_run(), env.new_run()]
    procs = [env.popen(run_dir) for run_dir in runs]
    outs = [proc.communicate(timeout=1500) for proc in procs]
    assert all(proc.returncode == 0 for proc in procs), [out[1][-2000:] for out in outs]
    stages = [env.stage(run_dir) for run_dir in runs]
    ids = [next(iter(stage["generations"])) for stage in stages]
    assert ids[0] == ids[1]
    assert sorted(stage["generations"][ids[0]]["reused"] for stage in stages) == [False, True]
    assert len(fake_claude.calls) == 1
    snapshot = env.generated / "petclinic" / "base" / ids[0]
    assert sorted(tree_hashes(snapshot)) == ["_COMPLETE", "features/sample_flow.feature", "glue/SampleFlowSteps.java"]


def _repair_sections(stdin: str) -> list[str]:
    return re.findall(r"^=== ([A-Z][A-Z ]+?) ===$", stdin, re.MULTILINE)


def test_req025_repair_bounded_captured(s06, fake_claude):
    # 생성(깨짐) -> 수리 1(깨짐) -> 수리 2(깨짐) -> 멈춤. 네 번째 응답(정상)은 쓰이지 않아야 한다.
    fake_claude.respond_sequence([BROKEN, BROKEN, BROKEN, VALID])
    run_dir = s06.new_run()
    done = s06.run(run_dir)
    assert done.returncode == 0, done.stderr[-3000:]
    calls = fake_claude.calls
    assert len(calls) == 3
    [gen] = s06.meta(run_dir)["generations"]
    assert gen["repairs"] == 2 and gen["status"] == "degraded"       # 남은 컴파일 실패는 S07에서 uncompilable로 집계
    assert s06.stage(run_dir)["status"] == "degraded" and "degraded" in s06.stage(run_dir)["reason"]
    gen_stdin, repairs = calls[0].stdin, calls[1:]
    assert gen_stdin.startswith((PROMPTS / "bdd-gen.md").read_text().rstrip()[:200])
    repair_template_head = (PROMPTS / "bdd-repair.md").read_text().splitlines()[0]
    sut_lines = [line.strip() for p in (FIXTURE_SUT / "src").rglob("*") if p.is_file()
                 for line in p.read_text(errors="replace").splitlines() if len(line.strip()) > 30]
    for call in repairs:
        stdin = call.stdin
        assert stdin.startswith(repair_template_head)
        # 수리 입력의 종류: 컴파일러 출력, undefined 목록, 이전 생성물(LLM 자신의 출력)뿐. 그 뒤는 llm.sh가 붙이는 번들이다.
        head = stdin.split("\n=== FILE: ", 1)[0]
        assert _repair_sections(head) == ["COMPILER OUTPUT", "UNDEFINED STEPS", "PREVIOUS FILES"], _repair_sections(head)
        compiler = head.split("=== COMPILER OUTPUT ===", 1)[1].split("=== UNDEFINED STEPS ===", 1)[0]
        assert "error:" in compiler and "SampleFlowSteps.java" in compiler
        bundle_paths = re.findall(r"^=== FILE: (\S+) ===$", stdin, re.MULTILINE)
        assert bundle_paths and all(p.startswith(("bbtg/", "harness/", "ontology/")) for p in bundle_paths), bundle_paths
        assert SUT_RESPONSE_MARKER not in stdin
        assert str(run_dir) not in stdin
        assert not [line for line in sut_lines if line in stdin]

    # 수리가 성공하면 그 자리에서 멈춘다: 생성(깨짐) -> 수리 1(정상)
    before = len(fake_claude.calls)
    fake_claude.respond_sequence([VALID] * before + [BROKEN, VALID])   # 순서표는 전체 호출 수 기준이다
    run_ok = s06.new_run(reps=2)
    done = s06.run(run_ok)
    assert done.returncode == 0, done.stderr[-3000:]
    gens = {g["rep"]: g for g in s06.meta(run_ok)["generations"]}
    # rep 1은 위 run과 같은 입력이라 재사용(claude 0회), rep 2가 새로 생성된다
    assert gens[1]["reused"] is True
    assert gens[2]["repairs"] == 1 and gens[2]["status"] == "passed"
    assert len(fake_claude.calls) - before == 2


def test_req025_undefined_steps_feed_repair(s06, fake_claude):
    """컴파일은 되지만 정의되지 않은 step이 있으면 dry-run undefined 목록이 수리 입력이 된다."""
    undefined = claude_result(files_payload(feature=UNDEFINED_FEATURE))
    fake_claude.respond_sequence([undefined, VALID])
    run_dir = s06.new_run()
    done = s06.run(run_dir)
    assert done.returncode == 0, done.stderr[-3000:]
    calls = fake_claude.calls
    assert len(calls) == 2
    head = calls[1].stdin.split("\n=== FILE: ", 1)[0]
    undefined_part = head.split("=== UNDEFINED STEPS ===", 1)[1].split("=== PREVIOUS FILES ===", 1)[0]
    assert "nothing defines this step" in undefined_part and "features/sample_flow.feature" in undefined_part
    [gen] = s06.meta(run_dir)["generations"]
    assert gen["repairs"] == 1 and gen["status"] == "passed"


def test_req061_gen_metadata_schema(s06, fake_claude):
    fake_claude.respond_sequence([claude_result(files_payload(steps=BROKEN_STEPS), 1000, 200),
                                  claude_result(files_payload(), 300, 400)])
    run_dir = s06.new_run(arms=("base", "jqa"))
    done = s06.run(run_dir)
    assert done.returncode == 0, done.stderr[-3000:]
    meta = s06.meta(run_dir)
    schema = json.loads((SCHEMAS / "bdd-gen.schema.json").read_text())
    jsonschema.validate(meta, schema)
    # 스키마가 필수 필드를 실제로 강제한다
    broken = json.loads(json.dumps(meta))
    del broken["generations"][0]["promptHash"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, schema)
    from td import prepare
    by_arm = {g["arm"]: g for g in meta["generations"]}
    assert set(by_arm) == {"base", "jqa"}
    base = by_arm["base"]
    assert base["repairs"] == 1
    assert base["tokens"] == {"in": 1000 + 5 + 7 + 300 + 5 + 7, "out": 200 + 400}
    assert base["promptHash"] == hashlib.sha256((PROMPTS / "bdd-gen.md").read_bytes()).hexdigest()
    assert base["model"] == "claude-opus-5-5" and base["cliVersion"] == "9.9.9-test"
    assert base["flags"] == prepare.CLAUDE_FLAGS
    assert base["strippedFields"] == ["a/b"] == meta["strippedFields"]
    assert base["seconds"] > 0 and len(base["inputHash"]) == 64
    assert base["scenarios"] == {"initial": 1, "final": 1}
    assert by_arm["jqa"]["bundleHash"] != base["bundleHash"]
    # 단계 JSON: arm 상태와 generation 목록, run.json arms.generations
    stage = s06.stage(run_dir)
    assert stage["arms"]["base"]["status"] == stage["arms"]["jqa"]["status"] == "passed"
    assert stage["arms"]["base"]["generations"] == [base["genId"]]
    run = json.loads((run_dir / "run.json").read_text())
    assert run["arms"]["generations"] == {"base": [base["genId"]], "jqa": [by_arm["jqa"]["genId"]]}
    assert run["arms"]["style"] == "cucumber"
    assert run["inputs"]["base"]["bundleHash"] == base["bundleHash"]
    # 번들은 S06/bundles/<arm>/에 보존된다
    assert (run_dir / "S06" / "bundles" / "jqa" / "ontology" / "ontology-jqa.json").is_file()


def test_malformed_llm_output_fails_one_generation(s06, fake_claude):
    """Review Focus 2: 잘린 JSON과 파일 목록 스키마 위반은 그 generation만 failed(사유 포함, 수리 0회)이고 다른 rep는 진행된다."""
    truncated = claude_result(files_payload()[:-25])
    bad_path = claude_result(json.dumps({"files": [{"path": "../outside/Evil.java", "content": "x"}]}))
    fake_claude.respond_sequence([truncated, bad_path, VALID])
    run_dir = s06.new_run(reps=3)
    done = s06.run(run_dir)
    assert done.returncode == 0, done.stderr[-3000:]
    assert len(fake_claude.calls) == 3                       # 깨진 출력에 수리 호출을 쓰지 않는다
    gens = {g["rep"]: g for g in s06.meta(run_dir)["generations"]}
    assert gens[1]["status"] == "failed" and gens[1]["repairs"] == 0 and "JSON" in gens[1]["reason"]
    assert gens[2]["status"] == "failed" and gens[2]["repairs"] == 0 and "path" in gens[2]["reason"]
    assert gens[3]["status"] == "passed"
    stage = s06.stage(run_dir)
    assert stage["status"] == "degraded"
    statuses = {gen_id: g["status"] for gen_id, g in stage["generations"].items()}
    assert sorted(statuses.values()) == ["failed", "failed", "passed"]
    # 실패한 generation은 스냅샷이 없고 임시 디렉터리나 예약도 남지 않는다
    for gen_id, g in stage["generations"].items():
        assert (s06.generated / "petclinic" / "base" / gen_id).exists() is (g["status"] == "passed")
    assert leftovers(s06.generated) == []
    # S07은 failed generation을 실행하지 않는다(실행 가능한 것만 고른다)
    from td import state
    assert sorted(state._runnable_generations(run_dir)) == [gid for gid, st in statuses.items() if st == "passed"]


def test_req022_s06_stage_level_capture(s06, fake_claude, claude_call_log):
    """S06 단계 수준: 생성과 수리를 포함한 모든 claude 호출이 llm.sh를 거친다(cwd = 번들 임시 디렉터리, 격리 플래그, stdin에 SUT 소스 없음)."""
    fake_claude.respond_sequence([BROKEN, VALID])
    run_dir = s06.new_run()
    done = s06.run(run_dir)
    assert done.returncode == 0, done.stderr[-3000:]
    calls = fake_claude.calls
    assert len(calls) == 2
    sut_text = [line.strip() for p in (FIXTURE_SUT / "src").rglob("*") if p.is_file()
                for line in p.read_text(errors="replace").splitlines() if len(line.strip()) > 30]
    cwds = set()
    for call in calls:
        cwd = Path(call.cwd).resolve()
        cwds.add(cwd)
        assert cwd.name == "cwd" and cwd.parent.name.startswith("td-llm.")
        for forbidden in (REPO_ROOT, FIXTURE_SUT, run_dir):
            assert not cwd.is_relative_to(Path(forbidden).resolve()), (cwd, forbidden)
        assert not cwd.exists()                                   # 호출 뒤 지워졌다
        argv = call.argv
        assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv
        assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
        assert argv[argv.index("--setting-sources") + 1] == ""
        assert not [line for line in sut_text if line in call.stdin]
        assert "TD_SUT_PASS" not in call.env and "TD_SUT_USER" not in call.env
    assert len(cwds) == 2                                         # 호출마다 새 임시 디렉터리
    records = claude_call_log(run_dir)
    assert len(records) == 2 and all("--tools" in r["argv"] for r in records)


def test_partial_final_dir_without_complete_is_not_reused(s06, fake_claude):
    """최종 경로에 `_COMPLETE` 없는 디렉터리(부분 결과)가 있으면 재사용하지도 덮어쓰지도 않는다(그 generation failed, claude 0회)."""
    fake_claude.respond(VALID)
    first = s06.new_run()
    assert s06.run(first).returncode == 0
    [gen_id] = s06.stage(first)["generations"]
    snapshot = s06.generated / "petclinic" / "base" / gen_id
    (snapshot / "_COMPLETE").unlink()
    before = tree_hashes(snapshot)
    second = s06.new_run()
    done = s06.run(second)
    gen = s06.stage(second)["generations"][gen_id]
    assert done.returncode != 0 and gen["status"] == "failed" and "_COMPLETE이 없다" in gen["reason"]
    assert len(fake_claude.calls) == 1 and tree_hashes(snapshot) == before
    assert s06.meta(second)["generations"][0]["status"] == "failed"     # bdd-gen.json은 실패해도 쓰인다


def test_sigterm_aborts_s06_and_cleans_up(s06, fake_claude):
    """claude 호출 중 S06 프로세스 그룹에 SIGTERM: 그 뒤 claude 호출 없음, 예약·임시 디렉터리 없음, 비-0 종료."""
    fake_claude.respond(VALID)
    fake_claude.delay(30)
    run_dir = s06.new_run(reps=2)
    proc = subprocess.Popen(["bash", str(S06_SCRIPT), "petclinic", run_dir.name], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=s06.env(run_dir), start_new_session=True)
    deadline = time.monotonic() + 300
    while not fake_claude.calls and time.monotonic() < deadline:
        time.sleep(0.5)
    assert fake_claude.calls, "claude 호출이 시작되지 않았다"
    assert list((s06.generated / "petclinic" / "base").glob(".tmp-*"))      # 생성 중에는 임시 디렉터리가 있다
    os.killpg(proc.pid, signal.SIGTERM)
    proc.communicate(timeout=120)
    # bash가 먼저 끝나도 파이썬 자식이 정리를 마칠 때까지(그룹이 빌 때까지) 기다린다
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.5)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
        pytest.fail("S06 프로세스 그룹이 SIGTERM 뒤 120초 안에 끝나지 않았다")
    time.sleep(1)
    assert proc.returncode != 0
    assert len(fake_claude.calls) == 1                                       # rep 2로 넘어가지 않았다
    assert leftovers(s06.generated) == []
    assert not list((s06.generated / "petclinic" / "base").glob("base-*"))   # 확정된 스냅샷도 없다
