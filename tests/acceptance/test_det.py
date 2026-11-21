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


# === E2E: 실제 run 산출물 검사 (work/det-session.json이 가리키는 run) ==============================
# 파이프라인은 이 테스트가 돌리지 않는다. 컨트롤러가 먼저 run-all을 돌리고 세션 파일에 run 경로를 적는다.
import hashlib  # noqa: E402
import re  # noqa: E402

from conftest import DET_SESSION_FILE  # noqa: E402
from td.detgen.derive import REASONS  # noqa: E402

_PLAN_PREFIX = "plan-tests-"


def _session() -> dict:
    return json.loads(DET_SESSION_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def det_run() -> Path:
    return Path(_session()["runDir"])


@pytest.fixture
def baseline_run() -> Path:
    return Path(_session()["baselineRunDir"])


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _det_generation_dir(run_dir: Path) -> Path:
    """S06 bdd-gen.json의 det generation 항목(`dir`)이 가리키는 스냅샷 디렉터리."""
    records = [g for g in _read_json(run_dir / "S06" / "bdd-gen.json")["generations"] if g["arm"] == "det"]
    assert len(records) == 1, f"det generation이 정확히 1개여야 한다: {[g['genId'] for g in records]}"
    assert records[0]["status"] == "passed", records[0]
    gen_dir = Path(records[0]["dir"])
    assert (gen_dir / "_COMPLETE").is_file() and (gen_dir / "cases.json").is_file(), gen_dir
    return gen_dir


def _det_cases(run_dir: Path) -> dict:
    return _read_json(_det_generation_dir(run_dir) / "cases.json")


def _simple(name: str) -> str:
    return re.split(r"[.$]", name)[-1]


@pytest.mark.det_e2e
def test_req101_ext_ontology(det_run):
    ext = _read_json(det_run / "S03" / "ontology-jqa-ext.json")
    field_counts = {_simple(name): len(dto["fields"]) for name, dto in ext["dtos"].items()}
    expected_fields = {"CreateReservationRequest": 10, "UpdateReservationRequest": 2, "ReservationResponse": 12,
                       "LoginRequest": 2}
    for name, count in expected_fields.items():
        assert field_counts.get(name) == count, f"{name}: {field_counts.get(name)} != {count}"
    enum_counts = {_simple(name): len(enum["constants"]) for name, enum in ext["enums"].items()}
    assert enum_counts.get("PriceTier") == 3 and enum_counts.get("ReservationStatus") == 4, enum_counts
    room_capacity = [c for c in ext["constants"] if c["name"] == "ROOM_CAPACITY"]
    assert [c["value"] for c in room_capacity] == [2], room_capacity
    assert len(ext["calls"]) >= 6, len(ext["calls"])
    statuses = {item["status"] for item in ext["exceptions"].values()}
    assert {422, 409, 404, 400} <= statuses, statuses
    # 음성 단정: EMAIL 상수와 nightly rate 값은 보강 파일에 없다
    assert not [c for c in ext["constants"] if "EMAIL" in c["name"].upper()], "EMAIL 상수가 있으면 안 된다"
    assert not re.search(r"nightly|NIGHTLY|_RATE\b", json.dumps(ext)), "nightly rate가 보강 파일에 있으면 안 된다"


@pytest.mark.det_e2e
def test_req102_existing_inputs_unchanged(det_run, baseline_run):
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    assert sha256(det_run / "S03" / "ontology-jqa.json") == sha256(baseline_run / "S03" / "ontology-jqa.json")
    for arm in ("base", "jqa", "owl"):
        current = _read_json(det_run / "S06" / f"bundle-{arm}.json")["inputHash"]
        reference = _read_json(baseline_run / "S06" / f"bundle-{arm}.json")["inputHash"]
        assert current == reference, f"{arm} 번들 inputHash가 기준 run과 다르다"
    assert (_read_json(det_run / "S05" / "owl-gen.json")["inputHash"]
            == _read_json(baseline_run / "S05" / "owl-gen.json")["inputHash"])


def _resolve_address(address: str, plans: dict[str, dict], keyparams: dict[str, dict]) -> bool:
    """`<file>#<index>@<sha12>`가 det 번들 입력 항목을 가리키는지. 계획은 conditionSha, keyparams(`p.r`)는 detail sha256."""
    match = re.fullmatch(r"(?P<file>[^#]+)#(?P<index>[\d.]+)@(?P<sha>[0-9a-f]{12})", address)
    assert match, f"주소 형식이 아니다: {address}"
    file, index, sha = match["file"], match["index"], match["sha"]
    if file in plans:
        return any(str(item["index"]) == index and item["conditionSha"].startswith(sha) for item in plans[file]["items"])
    if file in keyparams and re.fullmatch(r"\d+\.\d+", index):
        p_index, r_index = (int(part) for part in index.split("."))
        try:
            detail = keyparams[file]["parameters"][p_index]["reasons"][r_index]["detail"]
        except IndexError:
            return False
        return hashlib.sha256(detail.encode("utf-8")).hexdigest().startswith(sha)
    return False


@pytest.mark.det_e2e
def test_req105_provenance_real(det_run):
    gen_dir = _det_generation_dir(det_run)
    document = _read_json(gen_dir / "cases.json")
    case_ids = {case["id"] for case in document["cases"]}
    assert case_ids and len(case_ids) == len(document["cases"]), "case id는 비어 있지 않고 유일해야 한다"
    tagged = []
    for feature in sorted((gen_dir / "features").glob("*.feature")):
        tagged += re.findall(r"@case:(\S+)", feature.read_text(encoding="utf-8"))
    assert set(tagged) <= case_ids, f"cases.json에 없는 @case: {sorted(set(tagged) - case_ids)}"
    assert set(tagged) == case_ids, f"feature에 태그가 없는 case: {sorted(case_ids - set(tagged))}"

    bundle = det_run / "S06" / "bundles" / "det"
    plans = {plan["file"]: plan for plan in _read_json(bundle / "plans.json")}
    keyparams = {entry["file"]: entry for entry in _read_json(bundle / "keyparams.json")}
    bad = []
    for case in document["cases"]:
        assert case["sources"], f"{case['id']}: sources가 비었다"
        for source in case["sources"]:
            if source.startswith(("graph:", "harness:")):
                continue
            if not _resolve_address(source, plans, keyparams):
                bad.append((case["id"], source))
    for entry in document["unresolved"]:
        if entry["source"].startswith(("graph:", "harness:")):
            continue
        if not _resolve_address(entry["source"], plans, keyparams):
            bad.append(("unresolved", entry["source"]))
    assert not bad, f"입력 파일에서 해석되지 않는 근거 주소: {bad[:5]} (총 {len(bad)}건)"


@pytest.mark.det_e2e
def test_req107_universe_real(det_run):
    document = _det_cases(det_run)
    slots = document["universe"]["bySlot"]
    assert slots["generated"] + slots["unresolved"] == slots["total"], slots
    assert slots["generated"] == len(document["cases"]) and slots["unresolved"] == len(document["unresolved"]), slots
    assert sum(slots["byReason"].values()) == slots["unresolved"], slots["byReason"]
    assert set(slots["byReason"]) == set(REASONS)
    for entry in document["unresolved"]:
        assert entry["reason"] in REASONS, entry
    theoretical = document["universe"]["theoretical"]
    assert theoretical["formula"] and theoretical["factors"], theoretical.keys()
    assert theoretical["value"] > 0


@pytest.mark.det_e2e
def test_req111_mapping_real(det_run):
    bundle = det_run / "S06" / "bundles" / "det"
    plan_files = [plan["file"] for plan in _read_json(bundle / "plans.json")]
    assert len(plan_files) == 6, plan_files
    calls = _read_json(bundle / "ext.json")["calls"]
    mapped = set()
    for file in plan_files:
        service, method = file.removeprefix(_PLAN_PREFIX).removesuffix(".json").rsplit(".", 1)
        endpoints = {call["endpoint"] for call in calls if _simple(call["service"]) == service and call["method"] == method}
        assert len(endpoints) == 1, f"{file}: 대응 엔드포인트가 정확히 1개여야 한다: {endpoints}"
        mapped |= endpoints
    assert len(mapped) == 6, f"서로 다른 엔드포인트 6개여야 한다: {sorted(mapped)}"
    document = _det_cases(det_run)
    assert document["universe"]["bySlot"]["byReason"]["no-endpoint-mapping"] == 0
    assert not [e for e in document["unresolved"] if e["reason"] == "no-endpoint-mapping"]
    case_endpoints = {case["endpoint"] for case in document["cases"]}
    assert {label.removeprefix("endpoint:") for label in mapped} <= case_endpoints, "대응된 엔드포인트의 case가 없다"


@pytest.mark.det_e2e
def test_req115_baseline_real(det_run):
    document = _det_cases(det_run)
    cases = document["cases"]
    violated = {case["endpoint"] for case in cases if case["rule"] == "violation"}
    assert violated, "위반 case가 하나도 없다"
    for endpoint in sorted(violated):
        baselines = [case["id"] for case in cases if case["endpoint"] == endpoint and case["rule"] == "baseline-valid"]
        # 설계 판정: baseline 슬롯이 사유와 함께 생성 불가로 기록되면(unresolved 항목의 rule이 baseline-valid) 대체 허용
        skipped = [entry for entry in document["unresolved"]
                   if entry["endpoint"] == endpoint and entry["rule"] == "baseline-valid"]
        assert len(baselines) + len(skipped) == 1, f"{endpoint}: baseline 슬롯은 case 1건 또는 생성 불가 1건: {baselines} {skipped}"
        if skipped:
            assert skipped[0]["reason"] in REASONS, skipped[0]


def _stage(run_dir: Path, stage: str) -> dict:
    return _read_json(run_dir / "stages" / f"{stage}.json")


def _mentions_det(text: str | None) -> bool:
    return bool(text) and re.search(r"\bdet\b", text) is not None  # det-<hash> generation id도 \bdet\b로 잡힌다


@pytest.mark.det_e2e
def test_req108_pipeline_compare(det_run):
    for number in range(7, 14):
        stage = _stage(det_run, f"S{number:02d}")
        assert stage["status"] in ("passed", "degraded"), f"S{number:02d}: {stage['status']} {stage.get('reason')}"
        assert not _mentions_det(stage.get("reason")), f"S{number:02d} 사유가 det와 관련 있다: {stage['reason']}"
    compare = _read_json(det_run / "S12" / "compare" / "compare.json")
    det_arm = compare["arms"]["det"]
    assert det_arm["requestedReps"] == 1 and det_arm["measured"] == 1, det_arm  # reps는 run 전체 값(3)이라 보지 않는다
    assert det_arm["inputRegime"] == {"llm": False, "conditions": True, "graph": "jqa+ext"}
    assert compare["deterministic"] is not None and compare["deterministic"]["status"] == "measured", compare["deterministic"]
    verdict_text = json.dumps(compare["verdict"], ensure_ascii=False)
    assert not _mentions_det(verdict_text), "판정에 det가 들어가면 안 된다(참고 열)"
    # LLM 호출 0회: 기존 arm은 스냅샷 재사용이므로 이 run 전체의 claude shim 호출 기록이 없다
    calls = claude_call_log_for(det_run)
    assert calls == [], f"이 run에서 claude 호출이 기록됐다: {calls[:3]}"


def claude_call_log_for(run_dir: Path) -> list[dict]:
    from helpers import claude_call_log
    return claude_call_log(run_dir)
