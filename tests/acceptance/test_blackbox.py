"""S01 블랙박스 실행 수용 테스트(Int): REQ-012(산출물 구조), REQ-008(.exec 수량 게이트).

m1_run(`run-all.sh petclinic --only S00,S01`)을 세션당 한 번 돌려 재사용한다.
게이트 실패 주입 run은 TD_CONTROL_URL_OVERRIDE로 제어 URL을 죽은 주소로 바꿔 .exec가 0개가 되게 한다.
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = yaml.safe_load((REPO_ROOT / "suts" / "petclinic" / "expected-tests.yaml").read_text())
EXPECTED = _SPEC["blackbox"]["total"]
EXPECTED_EXEC = _SPEC["expected_exec"]
NO_ATTRIBUTION = sorted(_SPEC["no_attribution"]["tests"])


def _blackbox_dir(run) -> Path:
    return run.run_dir / "S01" / "blackbox"


def _exec_files(run) -> list[Path]:
    return sorted(p for p in (_blackbox_dir(run) / "exec").glob("*.exec") if not p.name.startswith("aggregate"))


def _junit_testcases(run) -> list[ET.Element]:
    cases = []
    for xml_file in sorted((_blackbox_dir(run) / "junit").glob("*.xml")):
        cases += [c for c in ET.parse(xml_file).getroot().iter("testcase") if c.find("skipped") is None]
    return cases


@pytest.fixture(scope="module")
def injected_gate_run(real_pipeline_run):
    return real_pipeline_run("S00,S01", TD_CONTROL_URL_OVERRIDE="http://127.0.0.1:1")


def test_req012_blackbox_artifacts(m1_run):
    assert m1_run.returncode == 0, m1_run.stderr[-3000:]
    stage = m1_run.stage("S01")
    assert stage["status"] == "passed", stage
    root = _blackbox_dir(m1_run)
    assert (root / "exec" / "aggregate.exec").is_file(), "SUT 정지 시 쓰이는 aggregate.exec가 없다"
    assert len(_exec_files(m1_run)) == EXPECTED_EXEC == EXPECTED - len(NO_ATTRIBUTION)
    assert list((root / "junit").glob("*.xml")), "JUnit XML이 복사되지 않았다"
    summary = json.loads((root / "summary.json").read_text())
    assert summary["tcCount"] == EXPECTED and summary["execCount"] == EXPECTED_EXEC
    assert summary["aggregateExec"] is True
    assert (root / "gradle.log").is_file()


def test_req008_exec_count_gate(m1_run, injected_gate_run):
    stage = m1_run.stage("S01")
    assert stage["tcCount"] == EXPECTED and stage["execCount"] == EXPECTED_EXEC
    assert sorted(stage["missingExec"]) == NO_ATTRIBUTION == sorted(stage["noAttribution"])
    assert len(_junit_testcases(m1_run)) == EXPECTED  # JUnit XML에서도 skipped 제외 35개

    bad = injected_gate_run
    bad_stage = bad.stage("S01")
    assert bad_stage["status"] == "failed", bad_stage
    assert bad_stage["tcCount"] == EXPECTED and bad_stage["execCount"] == 0
    assert len(bad_stage["missingExec"]) == EXPECTED
    assert all("#" in test_id for test_id in bad_stage["missingExec"])
    assert f"tcCount({EXPECTED})" in bad_stage["reason"] and "execCount(0)" in bad_stage["reason"]
    assert bad.returncode == 2  # S01만 실패: 종료 코드 2


def test_req012_evaluate_stderr_does_not_corrupt_summary(real_pipeline_run, tmp_path_factory):
    """evaluate 단계가 stderr에 경고를 내도 summary.json은 stdout JSON만 담고 S01은 passed다(경고는 evaluate.log)."""
    hook = tmp_path_factory.mktemp("stderr-hook")
    (hook / "sitecustomize.py").write_text(
        "import sys\nif 'evaluate' in sys.argv:\n    sys.stderr.write('WARNING: injected evaluate warning\\n')\n")
    run = real_pipeline_run("S00,S01", PYTHONPATH=str(hook))
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stage("S01")["status"] == "passed"
    root = _blackbox_dir(run)
    summary = json.loads((root / "summary.json").read_text())
    assert summary["status"] == "passed" and summary["tcCount"] == EXPECTED
    assert "injected evaluate warning" in (root / "evaluate.log").read_text()
