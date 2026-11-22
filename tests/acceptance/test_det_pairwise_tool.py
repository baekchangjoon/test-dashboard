"""det pairwise(PICT) 통합 테스트: S00의 PICT 고정 빌드·스탬프 재사용·실패 격리(REQ-301, REQ-302).

`pipeline/lib/pict.sh`의 `td_prepare_pict <tools_dir> <out_json>`을 임시 tools_dir로 bash에서 직접 호출한다.
공유 캐시(work/tools)는 건드리지 않는다. pict 대상 git 호출은 PATH 앞의 proxy shim이 기록하고(실패 모드면 rc 1),
그 밖의 git은 실제 바이너리로 넘긴다. make shim은 호출 횟수를 셀 때(통과)와 make 실패를 흉내 낼 때(rc 1)만 둔다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from td import prepare

REPO_ROOT = Path(__file__).resolve().parents[2]
PICT_SH = REPO_ROOT / "pipeline" / "lib" / "pict.sh"
PICT_COMMIT = "d529bb1535b725c8f29704f183b23dd344895d02"
FAILURE_CODES = ("clone-failed", "build-failed", "smoke-mismatch")


# --- 하네스 ---------------------------------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _real(name: str) -> str:
    found = shutil.which(name)
    assert found, f"{name}이 PATH에 없다"
    return found


def _make_shims(tmp_path: Path, *, git_fail: bool = False, make_mode: str | None = None) -> tuple[Path, Path, Path]:
    """shim 디렉터리와 git·make 호출 기록 파일을 만든다. make_mode: None(shim 없음) | "count"(기록 후 통과) | "fail"(기록 후 rc 1)."""
    shim_dir = tmp_path / "shims"
    shim_dir.mkdir(exist_ok=True)
    git_log, make_log = tmp_path / "git-calls.log", tmp_path / "make-calls.log"
    git_log.touch()
    make_log.touch()
    real_git = _real("git")
    (shim_dir / "git").write_text(
        "#!/bin/bash\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in *microsoft/pict*|*pict-src*)\n'
        f'    printf "%s\\n" "$*" >> "{git_log}"\n'
        f'    {"exit 1" if git_fail else "break"} ;;\n'
        "  esac\n"
        "done\n"
        f'exec "{real_git}" "$@"\n')
    (shim_dir / "git").chmod(0o755)
    if make_mode:
        real_make = _real("make")
        tail = "exit 1" if make_mode == "fail" else f'exec "{real_make}" "$@"'
        (shim_dir / "make").write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> "{make_log}"\n{tail}\n')
        (shim_dir / "make").chmod(0o755)
    return shim_dir, git_log, make_log


def _env(shim_dir: Path | None, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "TD_PICT_SMOKE_EXPECTED_OVERRIDE"}
    if shim_dir is not None:
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    env.update(extra)
    return env


def _prepare(tools_dir: Path, out_json: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; td_prepare_pict "$2" "$3"', "_", str(PICT_SH), str(tools_dir), str(out_json)],
        env=env, capture_output=True, text=True, timeout=900)


def _lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.strip()]


def _seed_source(pict_tool: dict, tools_dir: Path) -> None:
    """네트워크 clone을 줄이려고 pict_tool의 고정 커밋 소스를 임시 tools_dir에 복사한다(빌드 산출물은 td_prepare_pict가 clean -fdx로 지운다)."""
    shutil.copytree(Path(pict_tool["path"]).parent.parent / "pict-src", tools_dir / "pict-src", symlinks=True)


def _write_lock_with(tmp_path: Path, pict_json: Path | None) -> dict:
    """write-lock 서브커맨드를 최소 입력으로 실행해 tools.lock을 읽어 돌려준다."""
    pin = prepare.load_pin()
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    artifacts = {k: {"version": "1", "sha256": "a" * 64, "path": "/x"} for k in
                 ("pjacoco", "jacococli", "jqassistant", "jqassistantSpring")}
    artifacts["jacocoCoreEmbedded"] = "0.8.12"
    (tmp_path / "artifacts.json").write_text(json.dumps(artifacts))
    (tmp_path / "jqa.json").write_text(json.dumps({"plugins": ["x"], "resolvedJar": "/j", "verified": True}))
    (tmp_path / "hotspot.jar").write_bytes(b"jar")
    argv = ["write-lock", "--run-dir", str(run_dir), "--run-id", "r", "--sut", "s", "--sut-commit", "c" * 40,
            "--artifacts", str(tmp_path / "artifacts.json"), "--tia-commit", pin["tia"]["commit"],
            "--hotspot-commit", pin["hotspot"]["commit"], "--hotspot-jar", str(tmp_path / "hotspot.jar"),
            "--bbtg-commit", pin["bbtg"]["commit"], "--bbtg-requirements-sha256", "b" * 64,
            "--claude-version", "2.1.0", "--model", "m", "--jqa-plugins", str(tmp_path / "jqa.json"),
            "--python-version", "3.12", "--claude-verified", "true"]
    if pict_json is not None:
        argv += ["--pict-json", str(pict_json)]
    assert prepare.main(argv) == 0
    return yaml.safe_load((run_dir / "tools.lock").read_text())


# --- REQ-301 -----------------------------------------------------------------------------------------
def test_req301_pin_has_pict():
    pin = prepare.load_pin()
    assert pin["pict"] == {"repo": "microsoft/pict", "commit": PICT_COMMIT, "tag": "v3.7.4"}


def test_req301_s00_builds_pict(tmp_path):
    tools_dir, out_json = tmp_path / "tools", tmp_path / "S00" / "pict.json"
    out_json.parent.mkdir()
    shim_dir, git_log, _ = _make_shims(tmp_path)
    result = _prepare(tools_dir, out_json, _env(shim_dir))
    assert result.returncode == 0, result.stderr[-2000:]
    data = json.loads(out_json.read_text())
    binary = tools_dir / "pict" / "pict"
    assert data == {"commit": PICT_COMMIT, "binarySha256": _sha256(binary), "path": str(binary)}, data
    assert os.access(binary, os.X_OK)
    stamp = json.loads((tools_dir / "pict" / ".commit").read_text())
    assert stamp == {"commit": PICT_COMMIT, "binarySha256": _sha256(binary)}
    head = subprocess.run(["git", "-C", str(tools_dir / "pict-src"), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert head == PICT_COMMIT
    assert any("microsoft/pict" in line for line in _lines(git_log)), "pict clone이 proxy shim을 거치지 않았다"
    # 스모크: 같은 바이너리로 내장 기대와 비교(직접 호출)
    smoke = subprocess.run(["bash", "-c", 'source "$1"; td_py -m td.prepare pict-smoke "$2"', "_",
                            str(REPO_ROOT / "pipeline" / "lib" / "common.sh"), str(binary)],
                           capture_output=True, text=True, env=_env(None))
    assert smoke.returncode == 0, smoke.stderr
    # tools.lock
    lock = _write_lock_with(tmp_path, out_json)
    assert lock["pict"] == {"commit": PICT_COMMIT, "binarySha256": _sha256(binary), "path": str(binary)}
    assert "pictFailureReason" not in lock


def test_req301_stamp_reuse_and_rebuild(tmp_path, pict_tool):
    tools_dir = tmp_path / "tools"
    _seed_source(pict_tool, tools_dir)
    shim_dir, _, make_log = _make_shims(tmp_path, make_mode="count")
    env = _env(shim_dir)
    first = _prepare(tools_dir, tmp_path / "first.json", env)
    assert first.returncode == 0, first.stderr[-2000:]
    assert "failure" not in json.loads((tmp_path / "first.json").read_text())
    builds = len(_lines(make_log))
    assert builds >= 1
    binary = tools_dir / "pict" / "pict"
    sha_before, inode_before = _sha256(binary), binary.stat().st_ino

    second = _prepare(tools_dir, tmp_path / "second.json", env)
    assert second.returncode == 0, second.stderr[-2000:]
    assert len(_lines(make_log)) == builds, "스탬프가 맞는데 make를 다시 불렀다"
    assert binary.stat().st_ino == inode_before
    assert json.loads((tmp_path / "second.json").read_text())["binarySha256"] == sha_before

    binary.chmod(0o755)
    binary.write_bytes(b"#!/bin/sh\necho tampered\n")  # 바꿔치기: sha 불일치
    third = _prepare(tools_dir, tmp_path / "third.json", env)
    assert third.returncode == 0, third.stderr[-2000:]
    assert len(_lines(make_log)) > builds, "바이너리 sha가 스탬프와 다른데 다시 빌드하지 않았다"
    data = json.loads((tmp_path / "third.json").read_text())
    assert data["binarySha256"] == _sha256(binary) != hashlib.sha256(b"#!/bin/sh\necho tampered\n").hexdigest()
    assert json.loads((tools_dir / "pict" / ".commit").read_text())["binarySha256"] == data["binarySha256"]


# --- REQ-302 -----------------------------------------------------------------------------------------
def test_req302_s00_uses_branch_function():
    """S00은 아래 테스트가 직접 실행하는 분기 함수를 부르고, 그 결과가 있을 때만 write-lock에 --pict-json을 넘긴다."""
    text = (REPO_ROOT / "pipeline" / "S00-prepare.sh").read_text()
    assert re.search(r'^source .*lib/pict\.sh"$', text, re.M)
    assert re.search(r'^td_s00_prepare_pict "\$\{TD_PICT_TOOLS_DIR:-\$TOOLS_DIR\}" "\$PICT_JSON"$', text, re.M)
    assert "--pict-json" in text
    assert "fetch_git_tool()" not in text  # common.sh로 옮겨졌다
    assert "fetch_git_tool()" in (REPO_ROOT / "pipeline" / "lib" / "common.sh").read_text()


def test_req302_not_requested(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "S00").mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"options": {"arms": ["base", "jqa"]}}))
    tools_dir, out_json = tmp_path / "tools", run_dir / "S00" / "pict.json"
    shim_dir, git_log, make_log = _make_shims(tmp_path, make_mode="count")
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; td_s00_prepare_pict "$2" "$3"; git --version >/dev/null', "_",
         str(PICT_SH), str(tools_dir), str(out_json)],
        env=_env(shim_dir, TD_RUN_DIR=str(run_dir)), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert _lines(git_log) == [] and _lines(make_log) == []
    assert not out_json.exists() and not tools_dir.exists()
    lock = _write_lock_with(tmp_path, None)
    assert "pict" not in lock and "pictFailureReason" not in lock


def test_req302_requested_branch_prepares(tmp_path, pict_tool):
    """det가 요청되면 같은 분기 함수가 td_prepare_pict를 부른다(소스는 복사본, clone 없음)."""
    run_dir = tmp_path / "run"
    (run_dir / "S00").mkdir(parents=True)
    (run_dir / "run.json").write_text(json.dumps({"options": {"arms": ["base", "det"]}}))
    tools_dir, out_json = tmp_path / "tools", run_dir / "S00" / "pict.json"
    _seed_source(pict_tool, tools_dir)
    shim_dir, git_log, _ = _make_shims(tmp_path)
    result = subprocess.run(["bash", "-c", 'source "$1"; td_s00_prepare_pict "$2" "$3"', "_",
                             str(PICT_SH), str(tools_dir), str(out_json)],
                            env=_env(shim_dir, TD_RUN_DIR=str(run_dir)), capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, result.stderr[-2000:]
    assert json.loads(out_json.read_text())["commit"] == PICT_COMMIT
    assert _lines(git_log)


@pytest.mark.parametrize("failure", FAILURE_CODES)
def test_req302_prepare_failure(tmp_path, pict_tool, failure):
    tools_dir, out_json = tmp_path / "tools", tmp_path / "S00" / "pict.json"
    out_json.parent.mkdir()
    extra = {}
    if failure == "clone-failed":
        shim_dir, git_log, _ = _make_shims(tmp_path, git_fail=True)
    else:
        _seed_source(pict_tool, tools_dir)
        shim_dir, git_log, make_log = _make_shims(tmp_path, make_mode="fail" if failure == "build-failed" else None)
        if failure == "smoke-mismatch":
            extra["TD_PICT_SMOKE_EXPECTED_OVERRIDE"] = "not the expected output\n"
    result = _prepare(tools_dir, out_json, _env(shim_dir, **extra))
    assert result.returncode == 0, result.stderr[-2000:]
    data = json.loads(out_json.read_text())
    assert data["failure"] == failure, data
    assert isinstance(data["detail"], str) and len(data["detail"]) <= 300
    assert str(Path.home()) not in data["detail"]
    assert not (tools_dir / "pict" / ".commit").exists(), "실패했는데 스탬프가 남았다"
    if failure == "clone-failed":
        assert _lines(git_log), "pict 대상 git 호출이 shim을 거치지 않았다"
    if failure == "build-failed":
        assert _lines(make_log)
    lock = _write_lock_with(tmp_path, out_json)
    assert lock["pict"] is None
    assert lock["pictFailureReason"] == failure
