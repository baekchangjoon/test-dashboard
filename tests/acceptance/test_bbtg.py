"""REQ-013: S02 bbtg 7개 스킬 CLI 실행(Int/E2E), 행 걸림·부분 실패 주입.

실제 bbtg(work/tools/bbtg, 전용 venv)를 petclinic 소스 복사본에서 실행한다. 전제(S00이 준비한 clone·venv)가 없으면 실패한다.
"""
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
import yaml

from td import bbtg

REPO_ROOT = Path(__file__).resolve().parents[2]
# 기대 컨트롤러 목록은 사람이 소스를 읽고 적은 suts/petclinic/expected-endpoints.yaml에서 읽는다(Task 17).
PETCLINIC_CONTROLLERS = {fqcn.rsplit(".", 1)[-1] for fqcn in yaml.safe_load(
    (REPO_ROOT / "suts" / "petclinic" / "expected-endpoints.yaml").read_text())["controllers"]}


def _grep_rest_controllers(src: Path) -> set[str]:
    """드라이버와 다른 수단(grep)으로 센 기대 컨트롤러 목록."""
    done = subprocess.run(["grep", "-rl", "--include=*.java", "@RestController", str(src / "src" / "main" / "java")],
                          capture_output=True, text=True)
    return {Path(line).stem for line in done.stdout.splitlines()}


# --- REQ-013 -------------------------------------------------------------------------------
def test_req013_bbtg_seven_skills(s02_default, fake_claude):
    run = s02_default
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stage["status"] == "passed", run.stage
    calls = run.manifest["calls"]
    by_skill: dict[str, list[dict]] = {}
    for call in calls:
        by_skill.setdefault(call["skill"], []).append(call)
    assert set(by_skill) == set(bbtg.SKILLS)
    for skill in ("inspect-stack", "scan-test-assets", "inspect-auth", "derive-test-data"):
        assert len(by_skill[skill]) == 1, skill
    expected = _grep_rest_controllers(run.sut_src)
    assert expected == PETCLINIC_CONTROLLERS
    for skill in ("dependency-map", "find-external-calls"):
        assert {Path(c["key"]).stem for c in by_skill[skill]} == expected, skill
        assert len(by_skill[skill]) == len(expected)
    assert len(by_skill["plan-tests"]) >= 1
    ddl = yaml.safe_load(Path(REPO_ROOT / "suts" / "petclinic" / "sut.yaml").read_text())["runtime"]["ddl"]
    derive_argv = by_skill["derive-test-data"][0]["argv"]
    assert "--ddl-path" in derive_argv and derive_argv[derive_argv.index("--ddl-path") + 1] == ddl
    for call in calls:
        assert call["argv"] and call["argv"][0] == f"skills/{call['skill']}/cli.py"
        assert call["rc"] == 0, call
        assert call["artifacts"] or call["stdout"], call
        for rel in call["artifacts"]:
            assert (run.out_dir / "raw" / rel).is_file(), rel
    # manifest에 홈·임시 디렉터리 절대 경로가 없다
    text = (run.out_dir / "manifest.json").read_text()
    assert str(run.sut_src) not in text and "/Users/" not in text
    # SUT clone에 .bbtg/가 남지 않는다
    assert not (run.sut_src / ".bbtg").exists()
    # S02는 claude를 쓰지 않는다
    assert fake_claude.calls == []
    assert run.stage["outputs"]["clean"] == str(run.clean_dir)


def test_req013_failed_skill_degrades_stage(s02_stage, tmp_path):
    """개별 스킬 실패는 manifest에 기록하고 계속한다(단계 degraded)."""
    fake = _fake_bbtg(tmp_path, {"inspect-auth": "sys.exit(3)"})
    run = s02_stage(TD_BBTG_FAKE_DIR=str(fake))
    assert run.returncode == 0, run.stderr[-1500:]
    assert run.stage["status"] == "degraded", run.stage
    failed = [c for c in run.manifest["calls"] if c["rc"] != 0]
    assert [c["skill"] for c in failed] == ["inspect-auth"] and failed[0]["rc"] == 3
    assert len(run.manifest["calls"]) > 1
    assert not (run.sut_src / ".bbtg").exists()


def test_req013_all_skills_failed_is_failed(s02_stage, tmp_path):
    fake = _fake_bbtg(tmp_path, {name: "sys.exit(2)" for name in bbtg.SKILLS})
    run = s02_stage(TD_BBTG_FAKE_DIR=str(fake))
    assert run.stage["status"] == "failed", run.stage
    assert "bbtg" in run.stage["reason"]
    assert not (run.sut_src / ".bbtg").exists()


def test_req013_hung_skill_times_out_and_is_killed(s02_stage, tmp_path):
    """행 걸림 주입: 가짜 bbtg 스킬이 자식 프로세스까지 멈추면 시간 제한이 그룹째 정리하고 단계는 멈추지 않는다."""
    pid_file = tmp_path / "hung-child.pid"
    hang = f"import subprocess,time; c=subprocess.Popen(['sleep','300']); open({str(pid_file)!r},'w').write(str(c.pid)); time.sleep(300)"
    fake = _fake_bbtg(tmp_path, {"inspect-stack": hang})
    started = time.monotonic()
    run = s02_stage(TD_BBTG_FAKE_DIR=str(fake), TD_BBTG_TIMEOUT="3", TD_KILL_GRACE="1")
    assert time.monotonic() - started < 120
    assert run.stage["status"] == "degraded", run.stage
    hung = [c for c in run.manifest["calls"] if c["skill"] == "inspect-stack"][0]
    assert hung["rc"] == 124 and hung["reason"].startswith("timeout:inspect-stack")
    child_pid = int(pid_file.read_text())
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        import os
        os.kill(child_pid, 0)


def test_req013_failure_reasons_do_not_carry_stderr(s02_stage, tmp_path):
    """스킬이 stderr에 절대 경로·비밀처럼 보이는 문자열을 써도 manifest와 단계 사유에는 고정 문구만 남는다."""
    noisy = "sys.stderr.write('/Users/someone/private/app.properties password=hunter2 token=squ_abc\\n'); sys.exit(3)"
    fake = _fake_bbtg(tmp_path, {"inspect-auth": noisy})
    run = s02_stage(TD_BBTG_FAKE_DIR=str(fake))
    failed = [c for c in run.manifest["calls"] if c["rc"] != 0][0]
    assert failed["reason"] == "exit 3: see raw/logs/inspect-auth.stderr.txt"
    blob = json.dumps(run.manifest) + json.dumps(run.stage) + run.stderr
    assert "hunter2" not in blob and "squ_abc" not in blob and "/Users/someone" not in blob
    assert "hunter2" in (run.out_dir / "raw" / "logs" / "inspect-auth.stderr.txt").read_text()  # 원본은 raw 로그에만 있다


def test_req013_children_get_minimal_environment(s02_stage, tmp_path):
    """bbtg 자식 프로세스는 TD_*와 비밀 환경 변수를 받지 않는다."""
    dump = "import os,json; print(json.dumps({'env': sorted(os.environ)}))"
    fake = _fake_bbtg(tmp_path, {"inspect-stack": dump})
    run = s02_stage(TD_BBTG_FAKE_DIR=str(fake), AWS_SECRET_ACCESS_KEY="sekret", TD_SONAR_TOKEN="squ_x")
    env_names = json.loads((run.out_dir / "raw" / "stdout" / "inspect-stack.json").read_text())["env"]
    assert not [n for n in env_names if n.startswith("TD_") or n.startswith("AWS_") or "TOKEN" in n]


def test_req013_injected_failure_hook(s02_stage):
    run = s02_stage(TD_FAIL_STAGE="S02")
    assert run.stage["status"] == "failed" and "injected failure" in run.stage["reason"]


def test_req013_in_real_pipeline_run(real_pipeline_run):
    """실제 run-all(S00,S02): 단계 JSON·출력 경로와 SUT clone 청결."""
    result = real_pipeline_run("S00,S02")
    assert result.returncode == 0, result.stderr[-3000:]
    stage = result.stage("S02")
    assert stage["status"] == "passed", stage
    out_dir = Path(stage["outputs"]["bbtg"])
    assert (out_dir / "manifest.json").is_file() and (out_dir / "clean").is_dir()
    assert not (REPO_ROOT / "work" / "suts" / "petclinic" / "src" / ".bbtg").exists()


def _fake_bbtg(tmp_path: Path, behaviors: dict[str, str]) -> Path:
    """실제 bbtg 대신 쓸 가짜: 스킬별 cli.py가 behaviors의 코드를 실행하고(없으면 빈 JSON을 낸다) 종료한다.
    TD_BBTG_FAKE_DIR로 S02 스크립트에 넘기면 bbtg 경로와 파이썬만 바뀐다."""
    root = tmp_path / "fake-bbtg"
    for skill in bbtg.SKILLS:
        cli = root / "skills" / skill / "cli.py"
        cli.parent.mkdir(parents=True, exist_ok=True)
        body = behaviors.get(skill, "print('[]' if %r == 'derive-test-data' else '{}')" % skill)
        cli.write_text("import sys\n" + textwrap.dedent(body) + "\n")
    return root
