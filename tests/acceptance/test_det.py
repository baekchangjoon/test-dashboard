"""det arm S06 실행(Int, Gradle·JDK 필요): REQ-103(LLM 호출 0회), REQ-110(det 실패 격리).

`bddgen.run_stage`를 임시 run 디렉터리에서 프로세스 안으로 부른다. 검증(컴파일 확인, dry-run)은 실제 Gradle/javac다.
스냅샷 루트는 TD_E2E_GENERATED_DIR(임시)로 돌려 repo의 e2e/generated를 건드리지 않는다.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bdd_gen import VALID  # noqa: E402
from test_isolation import FIXTURE_SUT, make_run_dir  # noqa: E402

from td import bddgen, snapshot  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "det"
PETCLINIC_RUN = FIXTURES / "petclinic" / "run"
SUT_FILE = FIXTURES / "petclinic" / "sut.yaml"
SCHEMAS = REPO_ROOT / "site-gen" / "td" / "schemas"

_SHIM = """#!/bin/sh
# 호출 기록 shim: 이름과 인자를 기록 파일에 한 줄로 남긴다.
echo "$(basename "$0") $*" >> "{log}"
exit 97
"""


def _det_run_dir(tmp_path: Path, arms: list[str], name: str = "run") -> Path:
    """S02 정제·raw 산출물과 S03 온톨로지(petclinic det fixture)를 가진 임시 run 디렉터리."""
    run_dir = make_run_dir(tmp_path, name)
    shutil.copytree(PETCLINIC_RUN / "S02" / "bbtg" / "raw", run_dir / "S02" / "bbtg" / "raw")
    for path in (PETCLINIC_RUN / "S03").iterdir():
        shutil.copyfile(path, run_dir / "S03" / path.name)
    options = {"arms": arms, "reps": 2, "style": "cucumber", "regenerate": False, "only": None}
    init = subprocess.run([sys.executable, "-m", "td.state", "init", str(run_dir), "--run-id", run_dir.name,
                           "--sut", "petclinic", "--commit", "b6f939355e8790202ddfc71e3f3507252745ed37",
                           "--options-json", json.dumps(options)],
                          capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "site-gen")})
    assert init.returncode == 0, init.stderr
    (run_dir / "stages").mkdir(exist_ok=True)
    for stage in ("S00", "S02", "S03"):
        (run_dir / "stages" / f"{stage}.json").write_text(json.dumps({"id": stage, "status": "passed", "reason": None,
                                                                       "outputs": {}}))
    (run_dir / "tools.lock").write_text("schema: 1\nclaude:\n  version: 9.9.9-test\n  model: claude-opus-5-5\n")
    return run_dir


@pytest.fixture
def det_env(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("TD_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("TD_E2E_GENERATED_DIR", str(tmp_path / "generated"))
    return tmp_path


def _meta(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "S06" / "bdd-gen.json").read_text(encoding="utf-8"))
    jsonschema.validate(meta, json.loads((SCHEMAS / "bdd-gen.schema.json").read_text(encoding="utf-8")))
    return meta


def test_req103_no_llm_calls(det_env, monkeypatch):
    log = det_env / "llm-calls.log"
    log.touch()
    shim_dir = det_env / "shim-bin"
    shim_dir.mkdir()
    for name in ("claude", "llm.sh"):
        shim = shim_dir / name
        shim.write_text(_SHIM.format(log=log))
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    # 저장소 llm.sh 통로(td.snapshot.call_llm)와 주입 llm 모두 호출 기록으로 바꾼다
    in_process: list = []

    def recording(*args, **kwargs):
        in_process.append(args)
        raise AssertionError("det 경로가 LLM을 불렀다")

    monkeypatch.setattr(snapshot, "call_llm", recording)
    run_dir = _det_run_dir(det_env, ["det"])
    result = bddgen.run_stage(run_dir, SUT_FILE, FIXTURE_SUT, False, llm=recording)

    assert log.read_text() == "" and in_process == []
    assert result["status"] == "passed", result
    meta = _meta(run_dir)
    [record] = meta["generations"]
    assert record["arm"] == "det" and record["rep"] == 1 and record["status"] == "passed"
    assert record["genId"] == f"det-{record['inputHash'][:8]}-r1"
    assert result["extra"]["arms"]["det"] == {"status": "passed", "generations": [record["genId"]]}
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["requestedRepsByArm"] == {"det": 1}
    assert run["arms"]["generations"] == {"det": [record["genId"]]}
    assert run["inputs"]["det"]["bundle"] == "S06/bundles/det"
    assert (run_dir / "S06" / "bundles" / "det" / "STAMP.json").is_file()
    snapshot_dir = det_env / "generated" / "petclinic" / "det" / record["genId"]
    assert (snapshot_dir / "_COMPLETE").is_file() and (snapshot_dir / "cases.json").is_file()


def test_req110_failure_isolated(det_env):
    run_dir = _det_run_dir(det_env, ["base", "det"])
    (run_dir / "S03" / "ontology-jqa-ext.json").unlink()

    def stub_llm(bundle_dir, prompt_file, out_json):
        return snapshot.LlmReply(VALID["result"], 10, 5, 0.0)

    result = bddgen.run_stage(run_dir, SUT_FILE, FIXTURE_SUT, False, llm=stub_llm)
    arms = result["extra"]["arms"]
    assert arms["det"]["status"] == "failed" and "ontology-jqa-ext.json" in arms["det"]["reason"]
    assert arms["base"]["status"] != "failed", arms["base"]
    assert len(arms["base"]["generations"]) == 2
    meta = _meta(run_dir)
    assert {record["arm"] for record in meta["generations"]} == {"base"}
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert run["requestedRepsByArm"] == {"base": 2, "det": 1}
    assert "det" not in run["arms"]["generations"]
