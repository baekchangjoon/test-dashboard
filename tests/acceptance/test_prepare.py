"""S00 prepare 수용 테스트(Int): REQ-001(전체 clone·커밋 고정), REQ-058(tools.lock 완전성).

실제 S00을 한 번 돌린다(첫 실행은 도구 다운로드·TIA 빌드·SUT 빌드로 수 분 걸린다).
work/tools와 work/suts는 세션 사이에 캐시하고, run 디렉터리는 임시 work 디렉터리에 둔다.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ALL = REPO_ROOT / "pipeline" / "run-all.sh"
S00 = REPO_ROOT / "pipeline" / "S00-prepare.sh"
REAL_WORK = REPO_ROOT / "work"
BASE_COMMIT = "b6f939355e8790202ddfc71e3f3507252745ed37"
LOCK_TOOLS = ("pjacoco", "jacococli", "jqassistant", "jqassistantSpring", "hotspot", "tia", "bbtg")


def _isolated_work(tmp_path: Path) -> Path:
    """runs는 임시 디렉터리에 두고 tools·suts는 실제 work 캐시를 공유한다."""
    work = tmp_path / "work"
    work.mkdir()
    for shared in ("tools", "suts"):
        (REAL_WORK / shared).mkdir(parents=True, exist_ok=True)
        (work / shared).symlink_to(REAL_WORK / shared)
    return work


def _env(work: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(TD_WORK_DIR=str(work), TD_ROOT=str(REPO_ROOT), **extra)
    return env


class S00Result:
    def __init__(self, completed: subprocess.CompletedProcess, work: Path):
        self.returncode, self.stdout, self.stderr, self.work = (
            completed.returncode, completed.stdout, completed.stderr, work)

    @property
    def run_dir(self) -> Path:
        runs = [p for p in (self.work / "runs").glob("*") if p.is_dir()]
        assert len(runs) == 1, f"run 디렉터리가 1개여야 한다: {runs}\n{self.stderr[-2000:]}"
        return runs[0]

    @property
    def run_json(self) -> dict:
        return json.loads((self.run_dir / "run.json").read_text())

    @property
    def stage(self) -> dict:
        return json.loads((self.run_dir / "stages" / "S00.json").read_text())

    @property
    def lock(self) -> dict:
        return yaml.safe_load((self.run_dir / "tools.lock").read_text())


def _run_s00(work: Path, sut_file: Path | None = None, *extra_args: str, **env: str) -> S00Result:
    cmd = ["bash", str(RUN_ALL), "petclinic", "--only", "S00", *extra_args]
    if sut_file:
        cmd[3:3] = ["--sut-file", str(sut_file)]
    done = subprocess.run(cmd, capture_output=True, text=True, env=_env(work, **env), timeout=3300)
    return S00Result(done, work)


@pytest.fixture(scope="session")
def s00(tmp_path_factory) -> S00Result:
    result = _run_s00(_isolated_work(tmp_path_factory.mktemp("s00")))
    assert result.returncode == 0, f"S00 실패: rc={result.returncode}\n{result.stderr[-3000:]}"
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_req001_full_clone_pinned_commit(s00):
    assert s00.stage["status"] == "passed", s00.stage
    src = s00.work / "suts" / "petclinic" / "src"
    shallow = subprocess.run(["git", "-C", str(src), "rev-parse", "--is-shallow-repository"],
                             capture_output=True, text=True, check=True).stdout.strip()
    assert shallow == "false"
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{40}", head)
    assert s00.run_json["commit"] == head == BASE_COMMIT
    # 전체 히스토리: TIA base(HEAD~10은 first-parent를 따른다)가 실제로 존재해야 한다
    base = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD~10"],
                          capture_output=True, text=True)
    assert base.returncode == 0 and base.stdout.strip().startswith("c37b2e4")


def test_req001_s00_records_build_outputs(s00):
    outputs = s00.stage["outputs"]
    jar = Path(outputs["jar"])
    classes = Path(outputs["classes"])
    assert jar.is_file() and jar.name.startswith("spring-petclinic-") and jar.name.endswith("-SNAPSHOT.jar")
    assert "suts/petclinic/src/build/libs" in str(jar)
    assert classes.is_dir() and any(classes.rglob("*.class"))
    assert outputs["toolsLock"].endswith("tools.lock")


def test_req058_tools_lock_complete(s00):
    lock = s00.lock
    for tool in LOCK_TOOLS:
        assert tool in lock, f"tools.lock에 {tool}가 없다"
    for tool in ("pjacoco", "jacococli", "jqassistant", "jqassistantSpring", "hotspot"):
        assert lock[tool]["version"] and re.fullmatch(r"[0-9a-f]{64}", lock[tool]["sha256"]), (tool, lock[tool])
    for tool in ("tia", "bbtg"):
        assert re.fullmatch(r"[0-9a-f]{40}", lock[tool]["commit"]), (tool, lock[tool])
    assert lock["tia"]["commit"].startswith("634a4a3") and lock["bbtg"]["commit"].startswith("83ea6fd")
    assert lock["pjacoco"]["version"] == "2.0.0" and lock["jqassistant"]["version"] == "2.9.1"
    assert lock["hotspot"]["version"] == "0.1.6"
    assert lock["jqassistantSpring"]["coordinates"].startswith("org.jqassistant.plugin:jqassistant-spring-plugin:")
    assert any("Spring" in plugin for plugin in lock["jqassistantSpring"]["plugins"]), "플러그인 목록에 Spring이 없다"
    claude_version = subprocess.run(["bash", "-c", "command claude --version"], capture_output=True, text=True).stdout
    assert lock["claude"]["version"] == claude_version.split()[0]
    flags = " ".join(lock["claude"]["flags"])
    for needle in ("-p", "--tools", "--strict-mcp-config", "--mcp-config", "--setting-sources",
                   "--system-prompt", "--output-format json", "--model"):
        assert needle in flags, needle
    assert "--bare" not in flags
    assert lock["model"] == (os.environ.get("TD_LLM_MODEL") or "claude-opus-5-5")
    assert lock["claude"]["model"] == lock["model"]


def test_req058_jacococli_matches_pjacoco_embedded_jacoco(s00):
    lock = s00.lock
    agent = s00.work / "tools" / "pjacoco-agent.jar"
    with zipfile.ZipFile(agent) as archive:  # 테스트가 jar 안의 메타데이터를 직접 읽는다
        pom = archive.read("META-INF/maven/org.jacoco/org.jacoco.core/pom.properties").decode()
        props = archive.read("io/pjacoco/shaded/jacoco/core/jacoco.properties").decode()
    embedded_pom = re.search(r"^version=(.+)$", pom, re.M).group(1).strip()
    embedded_props = re.search(r"^VERSION=(\d+\.\d+\.\d+)", props, re.M).group(1)
    assert embedded_pom == embedded_props
    assert lock["jacocoCoreEmbedded"] == embedded_pom
    assert lock["jacococli"]["version"] == embedded_pom
    cli_jar = s00.work / "tools" / "jacococli.jar"
    with zipfile.ZipFile(cli_jar) as archive:  # 받은 jacococli가 실제로 그 버전인지 jar 안에서 확인
        names = archive.namelist()
        manifest = archive.read("META-INF/MANIFEST.MF").decode()
    assert any(n.startswith("org/jacoco/cli/") for n in names)
    assert embedded_pom in manifest


def test_req058_tools_layout_and_hashes_match_files(s00):
    tools = s00.work / "tools"
    lock = s00.lock
    assert _sha256(tools / "pjacoco-agent.jar") == lock["pjacoco"]["sha256"]
    assert _sha256(tools / "jacococli.jar") == lock["jacococli"]["sha256"]
    assert _sha256(tools / "hotspot.jar") == lock["hotspot"]["sha256"]
    assert (tools / "jqassistant" / "bin" / "jqassistant").is_file()
    assert (tools / "tia" / "bin" / "tia").is_file() and os.access(tools / "tia" / "bin" / "tia", os.X_OK)
    assert (tools / "bbtg" / ".venv" / "bin" / "python").exists()
    committed = yaml.safe_load((REPO_ROOT / "tools.pin.yaml").read_text())
    assert committed["pjacoco"]["sha256"] == lock["pjacoco"]["sha256"]  # pin 파일이 기준이다


def test_req058_tia_cli_and_bbtg_venv_work(s00):
    tools = s00.work / "tools"
    java17 = subprocess.run(["/usr/libexec/java_home", "-v", "17"], capture_output=True, text=True).stdout.strip()
    done = subprocess.run([str(tools / "tia" / "bin" / "tia"), "--help"], capture_output=True, text=True,
                          env={**os.environ, "JAVA_HOME": java17}, timeout=120)
    assert done.returncode in (0, 1, 2) and (done.stdout + done.stderr).strip(), "tia --help가 출력이 없다"
    venv_python = tools / "bbtg" / ".venv" / "bin" / "python"
    done = subprocess.run([str(venv_python), "-c", "import tree_sitter, tree_sitter_java; print('ok')"],
                          capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "ok", done.stderr


def test_s00_tools_lock_is_recorded_in_run_json(s00):
    tools = s00.run_json["tools"]
    assert tools["pjacoco"] == "2.0.0" and tools["jacococli"] == s00.lock["jacococli"]["version"]
    assert tools["model"] == s00.lock["model"]


def test_s00_expected_commit_mismatch_fails_with_both_short_shas(tmp_path):
    descriptor = yaml.safe_load((REPO_ROOT / "suts" / "petclinic" / "sut.yaml").read_text())
    descriptor["expected_commit"] = "1234567890abcdef1234567890abcdef12345678"
    sut_file = tmp_path / "sut.yaml"
    sut_file.write_text(yaml.safe_dump(descriptor, sort_keys=False))
    result = _run_s00(_isolated_work(tmp_path), sut_file)
    assert result.returncode == 1, result.stderr[-2000:]
    assert result.stage["status"] == "failed"
    reason = result.stage["reason"]
    assert "b6f9393" in reason and "1234567" in reason
    assert not (result.run_dir / "tools.lock").exists()


def test_s00_reps_out_of_range_fails(tmp_path):
    work = _isolated_work(tmp_path)
    run_dir = work / "runs" / "20261118-000000Z-b6f9393-manual-deadbeef"
    run_dir.mkdir(parents=True)
    env = _env(work)
    py_env = {**env, "PYTHONPATH": str(REPO_ROOT / "site-gen")}
    subprocess.run([sys.executable, "-m", "td.state", "init", str(run_dir), "--run-id", run_dir.name, "--sut", "petclinic",
                    "--commit", BASE_COMMIT, "--options-json", json.dumps({"arms": ["base"], "reps": 10})],
                   check=True, env=py_env)
    env.update(TD_RUN_DIR=str(run_dir), TD_RUN_ID=run_dir.name, TD_SUT_NAME="petclinic", TD_SUT_COMMIT=BASE_COMMIT,
               TD_SUT_FILE=str(REPO_ROOT / "suts" / "petclinic" / "sut.yaml"),
               TD_SUT_SRC=str(REAL_WORK / "suts" / "petclinic" / "src"))
    done = subprocess.run(["bash", str(S00), "petclinic", run_dir.name], capture_output=True, text=True, env=env, timeout=300)
    assert done.returncode != 0
    stage = json.loads((run_dir / "stages" / "S00.json").read_text())
    assert stage["status"] == "failed" and "reps" in stage["reason"]


def test_s00_tampered_pin_sha256_fails_and_keeps_cache(tmp_path):
    pin = yaml.safe_load((REPO_ROOT / "tools.pin.yaml").read_text())
    good_sha = pin["hotspot"]["sha256"]
    text = (REPO_ROOT / "tools.pin.yaml").read_text().replace(good_sha, "0" * 64)
    pin_file = tmp_path / "tools.pin.yaml"
    pin_file.write_text(text)
    result = _run_s00(_isolated_work(tmp_path), None, TD_TOOLS_PIN=str(pin_file))
    assert result.returncode == 1, result.stderr[-2000:]
    reason = result.stage["reason"]
    assert result.stage["status"] == "failed" and "hotspot.jar" in reason and "sha256" in reason
    assert not (result.run_dir / "tools.lock").exists()
    assert _sha256(REAL_WORK / "tools" / "hotspot.jar") == good_sha, "검증 실패가 정상 캐시를 망가뜨리면 안 된다"
