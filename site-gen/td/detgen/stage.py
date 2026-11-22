"""S06 det 경로(설계 §5.4, REQ-103, REQ-110): 투영 → 도출 → 렌더 → 검증 → `_COMPLETE` → 원자적 rename.

- LLM을 부르지 않는다. `claude`나 `llm.sh`를 실행하는 코드가 이 모듈에는 없다.
- 번들: `<run>/S06/bundles/det/`(`inputs.project`). 필수 입력이 없거나 깨지면(fatal) failed이고 genId도 없다.
  선택 입력이 빠지면(missing) generation은 만들되 degraded이고 사유에 빠진 슬롯을 적는다.
- 키: `sha256(projection.input_hash + GENERATOR_VERSION + source_checksum() + glue_checksum() + pict_tag)`, genId `det-<key8>-r1`(rep는 항상 1).
  `pict_tag`는 pict available이면 `"<commit>:<binarySha256>"`(tools.lock 값), unavailable이면 `"none"`이다(det pairwise 설계 §5.1).
  `source_checksum`은 생성기 소스(`td/detgen/*.py`)의 체크섬이다. GENERATOR_VERSION을 올리지 않고 생성 규칙을 바꿔도
  키가 바뀌어 낡은 스냅샷을 재사용하지 않는다.
- 스냅샷: `td.snapshot`의 예약(`.reserve`), 임시 디렉터리, `_COMPLETE`, rename을 LLM 경로(`bddgen._produce`)와 같은 순서로 쓴다.
  재사용은 `_COMPLETE`의 입력 해시와 파일 체크섬이 모두 맞을 때만 한다. 맞지 않으면(변조) 재사용도 덮어쓰기도 하지 않고 failed다.
- 검증: `bddgen.validate`(`td.scenarios.validate_generation`: 배치 규약, javac 컴파일, dry-run). 문제가 하나라도 있으면 failed다.
  수리 루프는 없다.
- pict 상태 결정표(det pairwise 설계 §5.1, §5.6): `<run>/tools.lock`이 없거나 `pict` 키가 없으면 unavailable(`pict-not-prepared`),
  `pict: null`이면 unavailable(`pictFailureReason`), `pict: {commit, binarySha256, path}`면 실행 직전에 바이너리 sha256을 다시 대조한다.
  불일치면 lock 값으로 만든 genId의 failed 레코드(`dir: null`)이고 기존 스냅샷이 있어도 재사용하지 않는다(대조가 재사용보다 먼저다).
  unavailable이면 generation은 degraded(사유 `pairwise-unavailable`, 선택 입력 누락 사유와 `"; "`로 잇는다).
  PICT의 환경 의존 실패(`PictFatal`: 시간 초과·기타 rc·출력 계약 위반)는 failed이고 스냅샷을 만들지 않는다.
  이것은 상위 설계의 "detgen은 번들만 읽는다"의 명시적 예외다(도구 위치는 번들·산출물에 쓰지 않는다).
- `--regenerate`: 같은 genId를 임시 디렉터리에서 다시 만든다. 기존 스냅샷과 파일 체크섬이 다르면 `checksum-changed` 경고를
  기록하고 교체한다(결정성 위반 신호). 같으면 경고 없이 교체한다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from td import redact, snapshot
from td.detgen import inputs
from td.detgen import render as render_mod
from td.detgen.derive import derive
from td.detgen.pairwise import Pairwise, PictFatal, PictTool

GENERATOR_NAME = "td.detgen"
GENERATOR_VERSION = "1"
ARM = "det"
REP = 1
CHECKSUM_CHANGED = "checksum-changed"
BUNDLE_REL = Path("S06") / "bundles" / ARM
REASON_LIMIT = 1500
TMP_RETIRED = snapshot.TMP_PREFIX + "retired-"   # 재생성 교체 중 잠시 옮겨 두는 기존 스냅샷(.gitignore의 .tmp-*)
PICT_TAG_NONE = "none"
PICT_NOT_PREPARED = "pict-not-prepared"   # det가 요청됐는데 tools.lock이 없거나 pict 키가 없다
PAIRWISE_UNAVAILABLE = "pairwise-unavailable"
PICT_TIMEOUT_ENV = "TD_DET_PICT_TIMEOUT"
PICT_TIMEOUT_DEFAULT = 120.0
PICT_WORK_REL = Path("S06") / "work" / "pict"


@dataclass
class DetResult:
    status: Literal["passed", "degraded", "failed"]
    reason: str | None
    gen_id: str | None
    dir: Path | None
    record: dict = field(default_factory=dict)   # bdd-gen.json의 generation 항목. fatal(genId 없음)이면 빈 dict
    reused: bool = False


SOURCE_DIR = Path(__file__).resolve().parent   # 생성기 소스(td/detgen). 체크섬 대상은 이 디렉터리의 *.py


def source_checksum(root: Path | None = None) -> str:
    """생성기 소스 체크섬: 파일 이름순으로 `이름 NUL 바이트 NUL`을 이어 sha256(경로는 디렉터리 기준 상대 이름만)."""
    digest = hashlib.sha256()
    for path in sorted(Path(root if root is not None else SOURCE_DIR).glob("*.py"), key=lambda item: item.name):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def det_key(input_hash: str, pict_tag: str) -> str:
    """det 키. pict_tag는 `"<commit>:<binarySha256>"`(available) 또는 `"none"`(unavailable)."""
    return hashlib.sha256((input_hash + GENERATOR_VERSION + source_checksum()
                           + render_mod.glue_checksum() + pict_tag).encode("utf-8")).hexdigest()


def det_gen_id(key: str) -> str:
    return f"{ARM}-{key[:8]}-r{REP}"


@dataclass(frozen=True)
class PictState:
    """tools.lock에서 읽은 pict 상태. lock_entry는 레코드의 `generator.pict`({commit, binarySha256}) 또는 None.
    mismatch가 있으면(실행 직전 sha 불일치·잘못된 항목) det generation은 failed다."""
    pairwise: Pairwise
    tag: str
    lock_entry: dict | None
    mismatch: str | None = None


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def pict_timeout() -> float:
    """PICT 프로세스 상한(초). `TD_DET_PICT_TIMEOUT`(테스트용)이 비었으면 120. 양수가 아니면 ValueError."""
    raw = os.environ.get(PICT_TIMEOUT_ENV) or ""
    value = float(raw) if raw.strip() else PICT_TIMEOUT_DEFAULT
    if not value > 0:
        raise ValueError(f"{PICT_TIMEOUT_ENV}는 양수여야 한다: {raw}")
    return value


def read_pict_state(run_dir: Path, timeout: float) -> PictState:
    """상태 결정표(det가 요청된 run에서만 부른다). 경로는 Pairwise.tool에만 담고 레코드·산출물에는 쓰지 않는다."""
    lock_path = Path(run_dir) / "tools.lock"
    try:
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else None
    except (OSError, yaml.YAMLError):
        lock = None
    if not isinstance(lock, dict) or "pict" not in lock:
        return PictState(Pairwise.unavailable(PICT_NOT_PREPARED), PICT_TAG_NONE, None)
    entry = lock["pict"]
    if entry is None:
        return PictState(Pairwise.unavailable(str(lock.get("pictFailureReason") or PICT_NOT_PREPARED)), PICT_TAG_NONE, None)
    fields = entry if isinstance(entry, dict) else {}
    commit, expected, path = fields.get("commit"), fields.get("binarySha256"), fields.get("path")
    tag = f"{commit}:{expected}"
    if not all(isinstance(value, str) and value for value in (commit, expected, path)):
        return PictState(Pairwise.disabled(), tag, None, "tools.lock의 pict 항목이 올바르지 않다(commit, binarySha256, path 필요)")
    lock_entry = {"commit": commit, "binarySha256": expected}
    actual = _file_sha256(Path(path))
    if actual != expected:
        found = "바이너리를 읽을 수 없다" if actual is None else f"실제 {actual[:12]}"
        return PictState(Pairwise.disabled(), tag, lock_entry,
                         f"pict 바이너리 sha256이 tools.lock과 다르다(lock {expected[:12]}, {found})")
    tool = PictTool(Path(path), commit, expected)
    return PictState(Pairwise.available(tool, Path(run_dir) / PICT_WORK_REL, timeout), tag, lock_entry)


def _base_record(gen_id: str, key: str, bundle_hash: str, pict: dict | None = None) -> dict:
    return {"genId": gen_id, "arm": ARM, "rep": REP, "status": "passed", "reason": None, "reused": False,
            "inputHash": key, "bundleHash": bundle_hash,
            "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION,
                          "glueChecksum": render_mod.glue_checksum(), "sourceChecksum": source_checksum(),
                          "pict": dict(pict) if pict else None},
            "cases": 0, "unresolved": 0, "seconds": 0.0, "dir": None}


def _failed(record: dict, reason: str, started: float) -> DetResult:
    record.update(status="failed", reason=reason[:REASON_LIMIT], reused=False, dir=None,
                  seconds=round(time.monotonic() - started, 3))
    return DetResult("failed", record["reason"], record["genId"], None, record, False)


def _reuse(final: Path) -> DetResult:
    record = {**snapshot.read_complete_meta(final), "reused": True, "dir": str(final)}
    return DetResult(record["status"], record.get("reason"), record["genId"], final, record, True)


def _tree_checksums(top: Path) -> dict[str, str]:
    return {rel: snapshot.sha256_bytes((top / rel).read_bytes()) for rel in snapshot.tree_files(top)}


def _issues_text(issues) -> str | None:
    """검증 결과의 문제를 한 줄로. 깨끗하면 None."""
    problems = []
    if issues.layout:
        problems.append(issues.layout[:600])
    if issues.excluded or issues.compiler_output.strip():
        problems.append(f"컴파일 제외 클래스 {len(issues.excluded)}개({', '.join(issues.excluded)[:300]})")
    if issues.undefined:
        problems.append(f"undefined step {len(issues.undefined)}개")
    return "; ".join(problems) or None


def _produce(projection: inputs.Projection, gen_id: str, key: str, arm_dir: Path, work: Path, validator,
             regenerate: bool, pict: PictState) -> DetResult:
    """예약을 쥔 상태에서 만든다. 성공하면 최종 경로로 rename(재생성이면 교체), 실패하면 임시 디렉터리를 지운다."""
    started = time.monotonic()
    record = _base_record(gen_id, key, projection.input_hash, pict.lock_entry)
    final = arm_dir / gen_id
    tmp = snapshot.make_tmp(arm_dir, gen_id)
    try:
        try:
            derivation = derive(inputs.Bundle.open(projection.dir), pairwise=pict.pairwise)
            record.update(cases=len(derivation.cases), unresolved=len(derivation.unresolved))
            render_mod.render(derivation, tmp)
        except PictFatal as exc:  # 환경 의존 PICT 실패: 스냅샷을 만들지 않는다(임시 출력은 finally에서 지운다)
            return _failed(record, f"PICT 실패: {str(exc)[:1000]}", started)
        except Exception as exc:  # noqa: BLE001 - 입력·파서·렌더 예외는 det arm의 실패 사유다(다른 arm에 번지지 않는다)
            return _failed(record, f"det 생성 실패: {type(exc).__name__}: {str(exc)[:1000]}", started)
        leaks = redact.find_leaks("\n".join((tmp / rel).read_text(encoding="utf-8", errors="replace")
                                          for rel in snapshot.tree_files(tmp)))
        if leaks:
            return _failed(record, f"산출물에 누출이 남았다: {','.join(sorted(set(leaks)))[:300]}", started)
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        try:
            issues = validator(tmp, work / "validate")
        except Exception as exc:  # noqa: BLE001 - 검증 도구 실패(BddGenError 등)도 det 실패로 기록한다
            return _failed(record, f"검증 실패: {str(exc)[:1000]}", started)
        problem = _issues_text(issues)
        if problem:
            return _failed(record, f"검증 문제(수리하지 않는다): {problem}", started)
        degraded = []
        if projection.missing:
            degraded.append(f"선택 입력 누락: {', '.join(projection.missing)}")
        if pict.pairwise.mode == "unavailable":
            degraded.append(PAIRWISE_UNAVAILABLE)
        if degraded:
            record.update(status="degraded", reason="; ".join(degraded)[:REASON_LIMIT])
        record["seconds"] = round(time.monotonic() - started, 3)
        snapshot.write_complete(tmp, key, {**record, "dir": None}, genId=gen_id)
        warnings: list[str] = []
        if final.exists():
            if not regenerate:
                raise RuntimeError(f"예약을 쥔 채로 최종 디렉터리가 이미 있다: {gen_id}")
            if _tree_checksums(final) != _tree_checksums(tmp):
                warnings.append(CHECKSUM_CHANGED)
            # 교체: 기존 디렉터리를 옆 이름으로 옮긴 뒤 rename하고 지운다(최종 경로에는 늘 완성 디렉터리만 있다).
            retired = arm_dir / f"{TMP_RETIRED}{gen_id}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
            os.rename(final, retired)
            try:
                os.rename(tmp, final)
            finally:
                shutil.rmtree(retired, ignore_errors=True)
        else:
            os.rename(tmp, final)
        record["dir"] = str(final)
        if warnings:
            record["warnings"] = warnings
        return DetResult(record["status"], record["reason"], gen_id, final, record, False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



def generate_det(run_dir: Path, sut_file: Path, out_root: Path, regenerate: bool, *, validator=None,
                 wait_timeout: float | None = None) -> DetResult:
    """det generation 하나를 재사용하거나 만든다. out_root는 `e2e/generated/<sut>`다."""
    if validator is None:
        from td import bddgen
        validator = bddgen.validate
    if wait_timeout is None:
        wait_timeout = float(os.environ.get("TD_BDDGEN_WAIT_SEC", "3600"))
    run_dir = Path(run_dir)
    projection = inputs.project(run_dir, Path(sut_file), run_dir / BUNDLE_REL)
    if projection.fatal:
        return DetResult("failed", f"det 입력 오류: {projection.fatal}"[:REASON_LIMIT], None, None, {}, False)
    try:
        timeout = pict_timeout()
    except ValueError as exc:
        return DetResult("failed", f"det 설정 오류: {exc}"[:REASON_LIMIT], None, None, {}, False)
    pict = read_pict_state(run_dir, timeout)
    key = det_key(projection.input_hash, pict.tag)
    gen_id = det_gen_id(key)
    if pict.mismatch:
        # 실행 직전 무결성(REQ-312): 스냅샷 재사용·예약보다 먼저 판정하고 아무것도 쓰지 않는다
        return _failed(_base_record(gen_id, key, projection.input_hash, pict.lock_entry), pict.mismatch, time.monotonic())
    arm_dir = Path(out_root) / ARM
    arm_dir.mkdir(parents=True, exist_ok=True)
    final = arm_dir / gen_id
    work = run_dir / "S06" / "work" / gen_id
    deadline = time.monotonic() + wait_timeout
    while True:
        if final.exists() and not regenerate:
            problem = snapshot.complete_problem(final, key)
            if problem is None:
                return _reuse(final)
            return _failed(_base_record(gen_id, key, projection.input_hash, pict.lock_entry),
                           f"스냅샷이 있지만 재사용할 수 없다(덮어쓰지 않는다): {problem}", time.monotonic())
        lock = snapshot.try_reserve(arm_dir, gen_id)
        if lock is not None:
            try:
                if final.exists() and not regenerate:
                    continue
                return _produce(projection, gen_id, key, arm_dir, work, validator, regenerate, pict)
            finally:
                snapshot.release(lock)
        if time.monotonic() > deadline:
            return _failed(_base_record(gen_id, key, projection.input_hash, pict.lock_entry),
                           f"다른 프로세스의 예약이 {int(wait_timeout)}초 동안 풀리지 않았다: {gen_id}", time.monotonic())
        time.sleep(1.0)
