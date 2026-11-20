"""td.bddgen 단위 테스트: LLM 출력 계약, 스냅샷 예약·재사용, 수리 상한(가짜 LLM·검증기 주입, Gradle 없음)."""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from td import bddgen, snapshot, state
from td.bundle import Bundle

FEATURE = "Feature: X\n  Scenario: s\n    When a\n"
STEPS = "package glue;\npublic class XSteps {}\n"
GOOD = json.dumps({"files": [{"path": "features/x.feature", "content": FEATURE},
                             {"path": "glue/XSteps.java", "content": STEPS}]})


# --- 출력 계약 -----------------------------------------------------------------------------------
def test_parse_output_accepts_contract_and_single_fence():
    assert [f["path"] for f in bddgen.parse_output(GOOD)] == ["features/x.feature", "glue/XSteps.java"]
    assert len(bddgen.parse_output("```json\n" + GOOD + "\n```")) == 2
    support = json.loads(GOOD)
    support["files"].append({"path": "glue/support/Util.java", "content": "package glue.support;\n"})
    support["files"].append({"path": "features/한글.feature", "content": FEATURE})
    assert len(bddgen.parse_output(json.dumps(support))) == 4


@pytest.mark.parametrize("text, needle", [
    (GOOD[:-20], "JSON"),                                                     # 잘린 출력
    ("Here are the files: " + GOOD, "JSON"),                                  # 설명문 섞임
    ("", "JSON"),
    (json.dumps({"files": []}), "스키마"),
    (json.dumps({"files": [{"path": "../x.feature", "content": "a"}]}), "스키마"),
    (json.dumps({"files": [{"path": "features/a/b.feature", "content": "a"}]}), "스키마"),
    (json.dumps({"files": [{"path": "features/.hidden.feature", "content": "a"}]}), "스키마"),
    (json.dumps({"files": [{"path": "glue/Helper.java", "content": "a"}]}), "스키마"),   # Steps도 support도 아님
    (json.dumps({"files": [{"path": "src/main/java/X.java", "content": "a"}]}), "스키마"),
    (json.dumps({"files": [{"path": "features/x.feature", "content": "a", "extra": 1}]}), "스키마"),
    (json.dumps({"files": [{"path": "glue/XSteps.java", "content": "a"}]}), "features"),
    (json.dumps({"files": [{"path": "features/x.feature", "content": "a"}] * 2}), "중복"),
    (json.dumps(["features/x.feature"]), "스키마"),
])
def test_parse_output_rejects(text, needle):
    with pytest.raises(bddgen.GenOutputError) as info:
        bddgen.parse_output(text)
    assert needle in str(info.value)


def test_render_repair_has_only_allowed_sections():
    template = (Path(bddgen.REPO_ROOT) / "prompts" / "bdd-repair.md").read_text()
    issues = bddgen.Issues("glue/XSteps.java:3: error: boom", ["glue/XSteps.java"],
                           [{"feature": "features/x.feature", "line": 3, "step": "a"}])
    text = bddgen.render_repair(template, issues, bddgen.parse_output(GOOD))
    assert "{{" not in text
    assert "glue/XSteps.java:3: error: boom" in text and "- features/x.feature:3: a" in text
    assert "--- path: glue/XSteps.java ---" in text and "=== FILE:" not in text


# --- 생성 흐름(가짜 LLM, 가짜 검증기) ---------------------------------------------------------------
class FakeLlm:
    def __init__(self, replies, delay: float = 0.0):
        self.replies, self.delay, self.calls = list(replies), delay, []
        self.lock = threading.Lock()

    def __call__(self, bundle_dir, prompt_file, out_json):
        with self.lock:
            self.calls.append(Path(prompt_file).read_text())
            text = self.replies[min(len(self.calls), len(self.replies)) - 1]
        time.sleep(self.delay)
        return bddgen.LlmReply(text, 10, 5, 0.01)


def clean_validator(gen_dir, out_dir):
    return bddgen.Issues()


def make_ctx(tmp_path, llm, validator=clean_validator, wait=30.0):
    return bddgen.GenContext(model="m", cli_version="v", flags=["-p"], stripped_fields=["a/b"],
                             work_dir=tmp_path / "work", llm=llm, validator=validator, wait_timeout=wait)


@pytest.fixture
def bundle(tmp_path):
    path = tmp_path / "bundle"
    path.mkdir()
    return Bundle(path=path, input_hash="ab" * 32, arm="base")


def test_generate_reuse_and_regenerate_numbering(tmp_path, bundle):
    llm = FakeLlm([GOOD])
    ctx = make_ctx(tmp_path, llm)
    out = tmp_path / "gen"
    first = bddgen.generate("base", 1, bundle, out, ctx=ctx)
    assert first.status == "passed" and not first.reused and len(llm.calls) == 1
    assert first.gen_id.endswith("-r1") and (out / "base" / first.gen_id / "_COMPLETE").is_file()
    again = bddgen.generate("base", 1, bundle, out, ctx=ctx)
    assert again.reused and again.gen_id == first.gen_id and len(llm.calls) == 1
    assert again.record["dir"] == str(out / "base" / first.gen_id)
    ids = [bddgen.generate("base", 1, bundle, out, regenerate=True, ctx=ctx).gen_id for _ in range(2)]
    assert ids == [f"{first.gen_id}-g1", f"{first.gen_id}-g2"]
    assert not list((out / "base").glob(".tmp-*")) and not list((out / "base" / ".reserve").iterdir())


def test_key_changes_with_prompt_or_model(tmp_path):
    key = bddgen.generation_key("h", b"p", b"r", "m")
    assert key != bddgen.generation_key("h", b"p2", b"r", "m")
    assert key != bddgen.generation_key("h", b"p", b"r", "m2")
    assert key != bddgen.generation_key("h2", b"p", b"r", "m")
    assert len(key) == 64


def test_concurrent_same_input_threads_write_once(tmp_path, bundle):
    llm = FakeLlm([GOOD], delay=0.5)
    ctx = make_ctx(tmp_path, llm)
    results = []
    threads = [threading.Thread(target=lambda: results.append(bddgen.generate("base", 2, bundle, tmp_path / "g", ctx=ctx)))
               for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(llm.calls) == 1
    assert len({r.gen_id for r in results}) == 1 and sorted(r.reused for r in results) == [False, True, True]


def test_parallel_regenerate_threads_get_distinct_suffixes(tmp_path, bundle):
    llm = FakeLlm([GOOD], delay=0.3)
    ctx = make_ctx(tmp_path, llm)
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        bddgen.generate("base", 1, bundle, tmp_path / "g", regenerate=True, ctx=ctx))) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r.gen_id.rsplit("-", 1)[1] for r in results) == ["g1", "g2", "g3"]


def test_stale_reservation_of_dead_owner_is_reclaimed(tmp_path, bundle):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    arm_dir = tmp_path / "g" / "base"
    key = bddgen.generation_key(bundle.input_hash, *(p.read_bytes() for p in bddgen.prompt_paths()), "m")
    lock = arm_dir / ".reserve" / bddgen.gen_id_for("base", key, 1)
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text(json.dumps({"pid": dead.pid, "host": __import__("socket").gethostname()}))
    result = bddgen.generate("base", 1, bundle, tmp_path / "g", ctx=make_ctx(tmp_path, FakeLlm([GOOD])))
    assert result.status == "passed" and not lock.exists()


def test_live_reservation_times_out_without_touching(tmp_path, bundle):
    arm_dir = tmp_path / "g" / "base"
    key = bddgen.generation_key(bundle.input_hash, *(p.read_bytes() for p in bddgen.prompt_paths()), "m")
    lock = arm_dir / ".reserve" / bddgen.gen_id_for("base", key, 1)
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text(json.dumps({"pid": os.getpid(), "host": __import__("socket").gethostname()}))
    llm = FakeLlm([GOOD])
    result = bddgen.generate("base", 1, bundle, tmp_path / "g", ctx=make_ctx(tmp_path, llm, wait=1.5))
    assert result.status == "failed" and "예약" in result.reason and llm.calls == [] and lock.exists()


def test_repairs_bounded_and_stop_when_clean(tmp_path, bundle):
    broken = bddgen.Issues("glue/XSteps.java:1: error: x", ["glue/XSteps.java"], [])
    seen = []

    def validator(gen_dir, out_dir):
        seen.append(out_dir.name)
        return broken

    llm = FakeLlm([GOOD])
    result = bddgen.generate("base", 3, bundle, tmp_path / "g", ctx=make_ctx(tmp_path, llm, validator))
    assert result.repairs == 2 and len(llm.calls) == 3 and result.status == "degraded"
    assert seen == ["validate-0", "validate-1", "validate-2"]
    assert result.record["remaining"] == {"uncompilableClasses": ["glue/XSteps.java"], "undefinedSteps": 0}
    # 수리 프롬프트에는 직전 검증 결과가 들어간다
    assert "glue/XSteps.java:1: error: x" in llm.calls[1]

    states = iter([broken, bddgen.Issues()])
    llm2 = FakeLlm([GOOD])
    ok = bddgen.generate("base", 4, bundle, tmp_path / "g", ctx=make_ctx(tmp_path, llm2, lambda g, o: next(states)))
    assert ok.repairs == 1 and ok.status == "passed" and len(llm2.calls) == 2


def test_layout_violation_left_after_repairs_fails(tmp_path, bundle):
    layout = bddgen.Issues(layout="layout violation: glue/Stray.java")
    result = bddgen.generate("base", 5, bundle, tmp_path / "g",
                             ctx=make_ctx(tmp_path, FakeLlm([GOOD]), lambda g, o: layout))
    assert result.status == "failed" and result.repairs == 2 and "배치" in result.reason
    assert not (tmp_path / "g" / "base" / result.gen_id).exists()


def test_malformed_repair_output_fails_generation(tmp_path, bundle):
    broken = bddgen.Issues("e", ["glue/XSteps.java"], [])
    result = bddgen.generate("base", 6, bundle, tmp_path / "g",
                             ctx=make_ctx(tmp_path, FakeLlm([GOOD, GOOD[:30]]), lambda g, o: broken))
    assert result.status == "failed" and "수리 1회차" in result.reason and result.repairs == 1


def test_tampered_snapshot_is_neither_reused_nor_overwritten(tmp_path, bundle):
    llm = FakeLlm([GOOD])
    ctx = make_ctx(tmp_path, llm)
    first = bddgen.generate("base", 1, bundle, tmp_path / "g", ctx=ctx)
    feature = first.dir / "features" / "x.feature"
    feature.write_text("changed")
    again = bddgen.generate("base", 1, bundle, tmp_path / "g", ctx=ctx)
    assert again.status == "failed" and "체크섬" in again.reason and feature.read_text() == "changed"
    (first.dir / "features" / "extra.feature").write_text(FEATURE)
    assert "파일 목록" in bddgen.complete_problem(first.dir, first.record["inputHash"])
    assert "입력 해시" in bddgen.complete_problem(first.dir, "0" * 64)
    assert len(llm.calls) == 1


# --- 리뷰 라운드 1 ------------------------------------------------------------------------------------------
TWO_SCENARIOS = FEATURE + "  Scenario: t\n    When a\n"


def test_repair_that_drops_scenarios_is_degraded(tmp_path, bundle):
    first = json.dumps({"files": [{"path": "features/x.feature", "content": TWO_SCENARIOS},
                                  {"path": "glue/XSteps.java", "content": STEPS}]})
    states = iter([bddgen.Issues("e", ["glue/XSteps.java"], []), bddgen.Issues()])
    result = bddgen.generate("base", 7, bundle, tmp_path / "g",
                             ctx=make_ctx(tmp_path, FakeLlm([first, GOOD]), lambda g, o: next(states)))
    assert result.record["scenarios"] == {"initial": 2, "final": 1}
    assert result.status == "degraded" and "repair dropped 1 scenarios" in result.reason
    clean = bddgen.generate("base", 8, bundle, tmp_path / "g", ctx=make_ctx(tmp_path, FakeLlm([first])))
    assert clean.status == "passed" and clean.record["scenarios"] == {"initial": 2, "final": 2}


def test_outline_rows_count_as_scenarios():
    outline = "Feature: O\n  Scenario Outline: o <n>\n    When <n>\n    Examples:\n      | n |\n      | 1 |\n      | 2 |\n"
    assert bddgen.count_scenarios([{"path": "features/o.feature", "content": outline},
                                   {"path": "glue/OSteps.java", "content": "Scenario: not a feature"}]) == 2


def test_stale_reclaim_backs_off_when_owner_changed(tmp_path, monkeypatch):
    """판정과 rename 사이에 다른 프로세스가 예약을 새로 잡았으면(옮겨 온 주인이 다르면) 되돌리고 포기한다."""
    arm_dir = tmp_path / "base"
    lock = arm_dir / ".reserve" / "base-00000000-r1"
    lock.mkdir(parents=True)
    owners = iter([{"pid": 999999, "host": "h"}, {"pid": 4242, "host": "h"}])
    monkeypatch.setattr(snapshot, "_owner", lambda path: next(owners))
    monkeypatch.setattr(snapshot, "_stale", lambda path, owner: True)
    assert bddgen.try_reserve(arm_dir, "base-00000000-r1") is None
    assert lock.is_dir() and not list((arm_dir / ".reserve").glob("*.stale-*"))


def test_unexpected_error_fails_only_that_generation(tmp_path, monkeypatch, bundle):
    """generate가 BddGenError가 아닌 예외를 내도 그 rep만 failed이고 bdd-gen.json은 쓰인다."""
    run_dir = tmp_path / "run"
    state.write_run_meta(run_dir, runId="r", sut="petclinic", commit="c", options={"arms": ["base"], "reps": 2})
    (run_dir / "stages").mkdir()
    (run_dir / "stages" / "S02.json").write_text(json.dumps({"id": "S02", "status": "passed"}))
    monkeypatch.setenv("TD_E2E_GENERATED_DIR", str(tmp_path / "generated"))
    monkeypatch.setattr(bddgen, "build_bundle", lambda *a: bundle)
    original = bddgen.generate

    def flaky(arm, rep, *args, **kwargs):
        if rep == 1:
            raise RuntimeError("boom")
        return original(arm, rep, *args, **kwargs)

    monkeypatch.setattr(bddgen, "generate", flaky)
    sut_file = Path(bddgen.REPO_ROOT) / "suts" / "petclinic" / "sut.yaml"
    result = bddgen.run_stage(run_dir, sut_file, tmp_path, False, llm=FakeLlm([GOOD]), validator=clean_validator)
    meta = json.loads((run_dir / "S06" / "bdd-gen.json").read_text())
    by_rep = {g["rep"]: g for g in meta["generations"]}
    assert by_rep[1]["status"] == "failed" and "RuntimeError: boom" in by_rep[1]["reason"]
    assert by_rep[2]["status"] == "passed"
    assert result["status"] == "degraded"


def test_stage_degraded_when_a_generation_is_degraded(tmp_path, monkeypatch, bundle):
    run_dir = tmp_path / "run"
    state.write_run_meta(run_dir, runId="r", sut="petclinic", commit="c", options={"arms": ["base"], "reps": 1})
    (run_dir / "stages").mkdir()
    (run_dir / "stages" / "S02.json").write_text(json.dumps({"id": "S02", "status": "passed"}))
    monkeypatch.setenv("TD_E2E_GENERATED_DIR", str(tmp_path / "generated"))
    monkeypatch.setattr(bddgen, "build_bundle", lambda *a: bundle)
    broken = bddgen.Issues("e", ["glue/XSteps.java"], [])
    sut_file = Path(bddgen.REPO_ROOT) / "suts" / "petclinic" / "sut.yaml"
    result = bddgen.run_stage(run_dir, sut_file, tmp_path, False, llm=FakeLlm([GOOD]), validator=lambda g, o: broken)
    assert result["status"] == "degraded" and "degraded" in result["reason"]
