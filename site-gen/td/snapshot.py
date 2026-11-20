"""LLM 산출물 스냅샷과 격리 호출의 공용 부품(S05 OWL, S06 BDD 공통. 설계 §13.4, §13.5, §13.9 "입력 해시 안정성").

- `_COMPLETE`: 확정한 스냅샷 디렉터리의 표식. {inputHash(전체 64자), files:[{path, sha256}], meta}. 재사용은 표식이 있고
  입력 해시와 파일 체크섬이 모두 맞을 때만 한다. 맞지 않으면 재사용도 덮어쓰기도 하지 않는다(호출자가 failed로 둔다).
- 예약: `<parent>/.reserve/<name>`을 원자적 mkdir로 잡은 프로세스만 그 스냅샷을 만든다. 같은 호스트에서 주인 pid가 죽은
  예약은 rename으로 회수한다. 임시 디렉터리(`.tmp-*`)에서 만들고 검증한 뒤 `os.rename`으로 최종 경로에 확정한다.
- `call_llm`: `pipeline/lib/llm.sh`(모든 claude 호출의 유일한 통로) 한 번 호출. 결과 텍스트와 토큰 수를 돌려준다.
- `build_bundle`: `td.bundle build` CLI(조립 + A1 경로·내용 검사 + 서명)를 그대로 부른다.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPLETE_NAME = "_COMPLETE"
RESERVE_DIR = ".reserve"
TMP_PREFIX = ".tmp-"
LLM_TIMEOUT_SEC = 1000          # llm.sh 안의 td_run(기본 900초)보다 조금 길게
BUNDLE_TIMEOUT_SEC = 600


class LlmCallError(RuntimeError):
    """llm.sh가 비-0으로 끝났거나 결과가 claude JSON 모양이 아니다."""


class BundleBuildError(RuntimeError):
    """`td.bundle build`가 실패했다(A1 위반 또는 입력 오류). LLM은 부르지 않는다."""


def root() -> Path:
    return Path(os.environ.get("TD_ROOT") or REPO_ROOT)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_files(top: Path) -> list[str]:
    return sorted(p.relative_to(top).as_posix() for p in top.rglob("*") if p.is_file() and p.name != COMPLETE_NAME)


def write_complete(tmp: Path, key: str, meta: dict, **fields) -> None:
    """tmp의 파일 체크섬과 입력 해시, 메타를 `_COMPLETE`에 쓴다(fields는 식별용 추가 키, 예: genId)."""
    complete = {"schema": 1, **fields, "inputHash": key,
                "files": [{"path": rel, "sha256": sha256_bytes((tmp / rel).read_bytes())} for rel in tree_files(tmp)],
                "meta": meta}
    (tmp / COMPLETE_NAME).write_text(json.dumps(complete, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                     encoding="utf-8")


def read_complete_meta(final: Path) -> dict:
    return json.loads((final / COMPLETE_NAME).read_text(encoding="utf-8"))["meta"]


def complete_problem(final: Path, key: str) -> str | None:
    """재사용 가능한 완성 스냅샷이면 None, 아니면 사유."""
    marker = final / COMPLETE_NAME
    if not marker.is_file():
        return f"{COMPLETE_NAME}이 없다"
    try:
        recorded = json.loads(marker.read_text(encoding="utf-8"))
        expected = {item["path"]: item["sha256"] for item in recorded["files"]}
    except (ValueError, KeyError, TypeError):
        return f"{COMPLETE_NAME}을 읽을 수 없다"
    if recorded.get("inputHash") != key:
        return f"{COMPLETE_NAME}의 입력 해시가 다르다"
    actual = tree_files(final)
    if sorted(expected) != actual:
        return f"{COMPLETE_NAME}의 파일 목록과 실제 파일이 다르다"
    changed = [rel for rel in actual if sha256_bytes((final / rel).read_bytes()) != expected[rel]]
    if changed:
        return f"{COMPLETE_NAME} 체크섬과 다른 파일: {', '.join(changed)}"
    return None


def make_tmp(parent: Path, name: str) -> Path:
    tmp = parent / f"{TMP_PREFIX}{name}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True)
    return tmp


# --- 예약 ----------------------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owner(lock: Path) -> dict | None:
    try:
        data = json.loads((lock / "owner.json").read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _stale(lock: Path, owner: dict | None) -> bool:
    if owner is None:
        # 주인 정보를 쓰기 전의 순간이거나 깨진 예약이다. 오래된 것만 회수한다.
        try:
            return time.time() - lock.stat().st_mtime > 120
        except OSError:
            return False
    return owner.get("host") == socket.gethostname() and not _pid_alive(int(owner.get("pid") or 0))


def try_reserve(parent: Path, name: str) -> Path | None:
    """`.reserve/<name>`을 원자적 mkdir로 잡는다. 이미 있으면 None(죽은 주인의 예약은 회수 후 다시 시도).
    회수는 rename 하나로 한다(둘이 동시에 회수해도 한쪽만 성공). rename 뒤 옮겨 온 예약의 주인이 판정한 주인과 다르면
    (판정과 rename 사이에 다른 프로세스가 새로 잡은 예약) 되돌리고 포기한다."""
    reserve = parent / RESERVE_DIR
    reserve.mkdir(parents=True, exist_ok=True)
    lock = reserve / name
    for _ in range(2):
        try:
            lock.mkdir()
        except FileExistsError:
            judged = _owner(lock)
            if not _stale(lock, judged):
                return None
            graveyard = reserve / f"{name}.stale-{uuid.uuid4().hex[:8]}"
            try:
                lock.rename(graveyard)
            except OSError:
                return None
            if _owner(graveyard) != judged:
                try:
                    graveyard.rename(lock)
                except OSError:
                    pass
                return None
            shutil.rmtree(graveyard, ignore_errors=True)
            continue
        (lock / "owner.json").write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname()}))
        return lock
    return None


def release(lock: Path | None) -> None:
    if lock is not None:
        shutil.rmtree(lock, ignore_errors=True)


# --- LLM 호출 -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LlmReply:
    text: str
    tokens_in: int
    tokens_out: int
    seconds: float


def usage_tokens(data: dict) -> tuple[int, int]:
    usage = data.get("usage") or {}
    tokens_in = sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return tokens_in, int(usage.get("output_tokens") or 0)


def call_llm(bundle_dir: Path, prompt_file: Path, out_json: Path) -> LlmReply:
    """llm.sh로 한 번 부른다(격리, 서명 검사, 호출 기록은 llm.sh가 맡는다). 실패는 LlmCallError."""
    from td import proc
    out_json.parent.mkdir(parents=True, exist_ok=True)
    err_path = out_json.with_suffix(".err")
    started = time.monotonic()
    with err_path.open("w", encoding="utf-8") as err:
        status = proc.run_with_timeout(LLM_TIMEOUT_SEC, ["bash", str(root() / "pipeline" / "lib" / "llm.sh"),
                                                         str(bundle_dir), str(prompt_file), str(out_json)],
                                       stdout=subprocess.DEVNULL, stderr=err, reraise=True)
    seconds = time.monotonic() - started
    if status != 0:
        tail = err_path.read_text(encoding="utf-8", errors="replace")[-600:].strip()
        raise LlmCallError(f"llm.sh 실패(exit {status}): {tail}")
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LlmCallError(f"llm.sh 출력이 JSON이 아니다: {exc}") from exc
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, str):
        raise LlmCallError("claude 결과에 result 텍스트가 없다")
    tokens_in, tokens_out = usage_tokens(data)
    return LlmReply(result, tokens_in, tokens_out, seconds)


def cli_version(run_dir: Path) -> str:
    import yaml
    try:
        lock = yaml.safe_load((Path(run_dir) / "tools.lock").read_text()) or {}
        return str((lock.get("claude") or {}).get("version") or "unknown")
    except (OSError, yaml.YAMLError):
        return "unknown"


def sanitize_info(run_dir: Path) -> dict:
    """S02 manifest의 정제 요약(strippedFields, forbiddenDeclared). 없으면 빈 목록."""
    try:
        manifest = json.loads((Path(run_dir) / "S02" / "bbtg" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"strippedFields": [], "forbiddenDeclared": []}
    sanitize = manifest.get("sanitize") or {}
    return {"strippedFields": list(sanitize.get("strippedFields") or []),
            "forbiddenDeclared": list(sanitize.get("forbiddenDeclared") or [])}


def build_bundle(kind: str, run_dir: Path, out: Path, sut_src: Path, sut_file: Path, log_stem: Path):
    """`td.bundle build` CLI(조립 + 검사 + 서명)를 그대로 쓴다. 로그는 `<log_stem>.log`, 결과 JSON은 `<log_stem>.json`.
    실패면 BundleBuildError(사유)."""
    from td import bundle, proc
    log = log_stem.with_suffix(".log")
    stdout_path = log_stem.with_suffix(".json")
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "td.bundle", "build", "--arm", kind, "--run-dir", str(run_dir), "--out", str(out),
            "--sut-src", str(sut_src)]
    oracle = Path(sut_file).parent / "oracle.yaml"
    if oracle.is_file():
        argv += ["--oracle", str(oracle)]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    with stdout_path.open("w") as out_handle, log.open("w") as err_handle:
        status = proc.run_with_timeout(BUNDLE_TIMEOUT_SEC, argv, stdout=out_handle, stderr=err_handle, env=env, reraise=True)
    if status != 0:
        raise BundleBuildError(f"번들 검사 실패(exit {status}): {log.read_text(errors='replace')[-800:].strip()}")
    info = json.loads(stdout_path.read_text())
    return bundle.Bundle(path=Path(out), input_hash=info["inputHash"], arm=kind)


def on_term(signum, _frame):
    """SIGTERM을 SystemExit로 바꿔 finally 블록(임시 디렉터리 삭제, 예약 해제)이 돌게 한다."""
    raise SystemExit(128 + signum)
