"""S13 게시: S3(원본) 업로드, 잠금, 인덱스 재생성, CloudFront 무효화, Lightsail 미러, publish-log.

설계 §13.1, §13.9 참조. 구성
  10a  manifest, 조건부 업로드(`If-None-Match: *`), 검증, `_COMPLETE`
  10b  잠금(`<prefix>locks/publish`)
  10c  미러 동기화, 무효화, rsync, 상태 규칙, publish-log, 오케스트레이션

S3 클라이언트는 인자로 받아(boto3 호환 객체) 단위 테스트에서 메모리 구현으로 바꿀 수 있다.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from botocore.exceptions import ClientError, ParamValidationError

from td.dashboard_config import ConfigError

CACHE_IMMUTABLE = "max-age=31536000, immutable"
CACHE_NO_CACHE = "no-cache"
COMPLETE_NAME = "_COMPLETE"
# S3 조건부 쓰기가 이미 객체가 있을 때 돌려주는 코드(412), 동시 쓰기 충돌(409)
EXISTS_CODES = ("PreconditionFailed", "ConditionalRequestConflict")
# 게시본에서 뺀다: 최종 S13 결과는 publish-log가 기준이고, 재시도마다 시각이 달라져 재게시 비교를 깨뜨린다.
EXCLUDED_SITE_FILES = ("stages/S13.json", "render.json")  # render.json: 렌더 기록(공통 띠 누락), 게시하지 않는다


class PublishError(Exception):
    """게시 실패(사유는 메시지)."""


class ContentConflict(PublishError):
    """이미 게시된 객체와 내용이 다르다."""


class InjectedFailure(PublishError):
    """TD_FAIL_STAGE로 주입한 실패."""


def normalize_prefix(raw: str) -> str:
    """접두를 `a/b/` 꼴로 맞춘다(빈 문자열 = 운영 루트). `..` 구간은 거부한다."""
    parts = [part for part in (raw or "").split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise ValueError(f"접두에 '.'/'..' 구간을 쓸 수 없다: {raw!r}")
    return "/".join(parts) + "/" if parts else ""


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _etag(value: str | None) -> str:
    return (value or "").strip('"')


def content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    if path.suffix == ".json":
        return "application/json"
    if path.suffix in (".js", ".mjs"):
        return "text/javascript; charset=utf-8"
    guessed = guessed or "application/octet-stream"
    return f"{guessed}; charset=utf-8" if guessed.startswith("text/") or guessed.endswith(("xml", "svg+xml")) else guessed


def _file_digests(path: Path) -> tuple[int, str, str]:
    md5, sha256, size = hashlib.md5(), hashlib.sha256(), 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            md5.update(chunk)
            sha256.update(chunk)
            size += len(chunk)
    return size, md5.hexdigest(), sha256.hexdigest()


# --- 10a: manifest --------------------------------------------------------------------------
@dataclass(frozen=True)
class ManifestEntry:
    path: Path
    size: int
    md5: str
    sha256: str


@dataclass
class Manifest:
    key_prefix: str
    entries: dict[str, ManifestEntry]

    def key(self, rel: str) -> str:
        return self.key_prefix + rel

    def digest(self) -> str:
        """경로 순으로 이어 붙인 `경로, sha256, 크기`의 sha256. `_COMPLETE`가 이 값을 담아 게시본을 봉인한다."""
        lines = "".join(f"{rel}\t{e.sha256}\t{e.size}\n" for rel, e in sorted(self.entries.items()))
        return hashlib.sha256(lines.encode()).hexdigest()

    @property
    def total_bytes(self) -> int:
        return sum(e.size for e in self.entries.values())


def build_manifest(site_dir, key_prefix: str, run_json: Path | None = None) -> Manifest:
    """site_dir의 파일을 key_prefix 아래 객체로 올릴 목록으로 만든다. run_json을 주면 사이트 안의 run.json 대신 쓴다
    (게시된 run.json은 로컬 run.json과 바이트 단위로 같아야 한다)."""
    site_dir = Path(site_dir)
    entries: dict[str, ManifestEntry] = {}
    for path in sorted(p for p in site_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(site_dir).as_posix()
        if rel in EXCLUDED_SITE_FILES or (run_json is not None and rel == "run.json"):
            continue
        entries[rel] = ManifestEntry(path, *_file_digests(path))
    if run_json is not None:
        entries["run.json"] = ManifestEntry(Path(run_json), *_file_digests(Path(run_json)))
    return Manifest(key_prefix, dict(sorted(entries.items())))


# --- 10a: 업로드와 검증 -----------------------------------------------------------------------
@dataclass
class UploadStats:
    uploaded: int = 0
    skipped: int = 0
    seconds: float = 0.0


def _remote_matches(s3, bucket: str, key: str, entry: ManifestEntry) -> bool:
    head = s3.head_object(Bucket=bucket, Key=key)
    return _etag(head.get("ETag")) == entry.md5 and int(head.get("ContentLength", -1)) == entry.size


def upload_run(s3, bucket: str, manifest: Manifest, inject: Callable[[str], None] | None = None,
               pause: float = 0.0, deadline: float | None = None) -> UploadStats:
    """객체마다 `If-None-Match: *`로 올린다. 이미 있으면 체크섬이 같을 때만 건너뛰고(재시도 허용) 다르면 ContentConflict.
    inject(point)는 `upload-first`(첫 객체 직후), `upload-mid`(절반 직후)에서 불린다."""
    stats = UploadStats()
    started = time.monotonic()
    total = len(manifest.entries)
    middle = max(1, total // 2)
    for index, (rel, entry) in enumerate(manifest.entries.items(), start=1):
        if deadline is not None and time.monotonic() > deadline:
            raise PublishError("timeout:s3 upload")
        key = manifest.key(rel)
        try:
            with entry.path.open("rb") as handle:
                s3.put_object(Bucket=bucket, Key=key, Body=handle, IfNoneMatch="*", CacheControl=CACHE_IMMUTABLE,
                              ContentType=content_type(Path(rel)))
            stats.uploaded += 1
        except ClientError as exc:
            if _error_code(exc) not in EXISTS_CODES:
                raise
            if not _remote_matches(s3, bucket, key, entry):
                raise ContentConflict(f"이미 게시된 객체와 내용이 다르다: {rel}") from exc
            stats.skipped += 1
        if pause:
            time.sleep(pause)
        if inject is not None:
            if index == 1:
                inject("upload-first")
            if index == middle:
                inject("upload-mid")
    stats.seconds = time.monotonic() - started
    return stats


def _list_remote(s3, bucket: str, key_prefix: str) -> dict[str, tuple[str, int]]:
    listed: dict[str, tuple[str, int]] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key_prefix):
        for obj in page.get("Contents", []):
            listed[obj["Key"][len(key_prefix):]] = (_etag(obj.get("ETag")), int(obj["Size"]))
    return listed


def verify_remote(s3, bucket: str, manifest: Manifest) -> list[str]:
    """원격 run 디렉터리를 manifest와 대조해 차이를 `missing:`, `differs:`, `extra:` 문장으로 돌려준다(`_COMPLETE`는 제외)."""
    remote = _list_remote(s3, bucket, manifest.key_prefix)
    remote.pop(COMPLETE_NAME, None)
    problems = []
    for rel, entry in manifest.entries.items():
        if rel not in remote:
            problems.append(f"missing: {rel}")
        elif remote[rel] != (entry.md5, entry.size):
            problems.append(f"differs: {rel}")
    problems.extend(f"extra: {rel}" for rel in sorted(set(remote) - set(manifest.entries)))
    return problems


def _complete_body(manifest: Manifest) -> bytes:
    return (json.dumps({"manifestSha256": manifest.digest(), "objects": len(manifest.entries), "bytes": manifest.total_bytes},
                       sort_keys=True) + "\n").encode()


def read_complete(s3, bucket: str, key_prefix: str) -> dict | None:
    try:
        body = s3.get_object(Bucket=bucket, Key=key_prefix + COMPLETE_NAME)["Body"].read()
    except ClientError as exc:
        if _error_code(exc) in ("NoSuchKey", "404"):
            return None
        raise
    try:
        return json.loads(body)
    except ValueError:
        return {"manifestSha256": None, "raw": body[:200].decode(errors="replace")}


def complete(s3, bucket: str, manifest: Manifest) -> None:
    """`_COMPLETE`를 조건부로 만든다. 이미 있으면 같은 manifest일 때만 성공한다."""
    key = manifest.key(COMPLETE_NAME)
    body = _complete_body(manifest)
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=body, IfNoneMatch="*", CacheControl=CACHE_IMMUTABLE,
                      ContentType="application/json")
    except ClientError as exc:
        if _error_code(exc) not in EXISTS_CODES:
            raise
        existing = read_complete(s3, bucket, manifest.key_prefix) or {}
        if existing.get("manifestSha256") != manifest.digest():
            raise ContentConflict("_COMPLETE가 이미 있고 내용(manifest)이 다르다") from exc


# --- 10b: 잠금 -----------------------------------------------------------------------------
class LockHeld(PublishError):
    """다른 게시가 잠금을 잡고 있다(메시지에 잠금 정보와 --force-unlock 안내)."""

    def __init__(self, info: dict, prefix: str):
        self.info = info
        super().__init__(format_lock_hint(info, prefix))


class LockMismatch(PublishError):
    """--force-unlock의 attemptId가 잠금의 attemptId와 다르다."""


@dataclass
class Lock:
    bucket: str
    key: str
    etag: str
    attempt_id: str


def lock_key(prefix: str) -> str:
    return f"{prefix}locks/publish"


def format_lock_hint(info: dict, prefix: str = "") -> str:
    owner = info.get("owner") or {}
    attempt = info.get("attemptId", "?")
    return (f"다른 게시가 잠금을 잡고 있다: attemptId={attempt} 소유자={owner.get('host', '?')}:{owner.get('pid', '?')} "
            f"획득={info.get('acquiredAt', '?')} (접두 '{prefix}'). 그 게시가 비정상 종료됐다면 확인 뒤 "
            f"`S13-publish.sh <sut> <runId> --force-unlock {attempt}`로 푼다(자동 만료는 없다).")


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_lock(s3, bucket: str, prefix: str) -> tuple[dict, str] | None:
    """(잠금 정보, ETag). 없으면 None."""
    try:
        response = s3.get_object(Bucket=bucket, Key=lock_key(prefix))
    except ClientError as exc:
        if _error_code(exc) in ("NoSuchKey", "404"):
            return None
        raise
    try:
        info = json.loads(response["Body"].read())
    except ValueError:
        info = {"attemptId": "?", "note": "잠금 내용을 읽지 못했다"}
    return info, _etag(response.get("ETag"))


def acquire_lock(s3, bucket: str, prefix: str, attempt_id: str) -> Lock:
    """`<prefix>locks/publish`를 조건부 PUT(`If-None-Match: *`)으로 만든다. 이미 있으면 LockHeld."""
    info = {"attemptId": attempt_id, "owner": {"host": socket.gethostname(), "pid": os.getpid()}, "acquiredAt": _utc_now()}
    body = (json.dumps(info, sort_keys=True) + "\n").encode()
    for _ in range(2):  # 확인하는 사이 풀린 잠금이면 한 번 더 시도한다
        try:
            response = s3.put_object(Bucket=bucket, Key=lock_key(prefix), Body=body, IfNoneMatch="*",
                                     ContentType="application/json", CacheControl=CACHE_NO_CACHE)
            return Lock(bucket, lock_key(prefix), _etag(response.get("ETag")), attempt_id)
        except ClientError as exc:
            if _error_code(exc) not in EXISTS_CODES:
                raise
        held = read_lock(s3, bucket, prefix)
        if held is not None:
            raise LockHeld(held[0], prefix)
    raise PublishError("잠금을 잡지 못했다(동시 갱신 충돌)")


def _conditional_delete(s3, bucket: str, key: str, etag: str) -> bool:
    """조회한 ETag와 같을 때만 지운다. 지웠으면 True, 이미 바뀌었거나 없으면 False.
    S3가 조건부 삭제를 지원하지 않으면(오류) 재조회 후 ETag가 같을 때만 삭제한다(경합은 수동 실행이라 수용, 설계 §13.9)."""
    try:
        s3.delete_object(Bucket=bucket, Key=key, IfMatch=f'"{etag}"')
        return True
    except ClientError as exc:
        code = _error_code(exc)
        if code in ("PreconditionFailed", "NoSuchKey", "404"):
            return False
        if code not in ("NotImplemented", "InvalidArgument", "MethodNotAllowed", "UnsupportedOperation", "XNotImplemented"):
            raise
    except ParamValidationError:
        pass  # 이 botocore가 IfMatch를 모른다
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if _error_code(exc) in ("NoSuchKey", "404"):
            return False
        raise
    if _etag(head.get("ETag")) != etag:
        return False
    s3.delete_object(Bucket=bucket, Key=key)
    return True


def release(s3, lock: Lock) -> bool:
    """내가 잡은 잠금(획득 시 ETag)만 지운다. 남이 교체했거나 이미 없으면 건드리지 않고 False."""
    return _conditional_delete(s3, lock.bucket, lock.key, lock.etag)


def force_unlock(s3, bucket: str, prefix: str, attempt_id: str) -> str:
    """잠금의 attemptId가 인자와 같을 때만 지운다(조회한 ETag로 조건부 삭제). 'released' 또는 'absent', 다르면 LockMismatch."""
    held = read_lock(s3, bucket, prefix)
    if held is None:
        return "absent"
    info, etag = held
    if info.get("attemptId") != attempt_id:
        raise LockMismatch(f"잠금의 attemptId({info.get('attemptId')})가 인자({attempt_id})와 달라 지우지 않는다. "
                           + format_lock_hint(info, prefix))
    return "released" if _conditional_delete(s3, bucket, lock_key(prefix), etag) else "absent"


# =====================================================================================
# 10c: 미러 동기화, 무효화, Lightsail, 상태 규칙, publish-log, 오케스트레이션
# =====================================================================================
GIB = 1024 ** 3
MIRROR_MARKER = ".td-site-mirror"
DASH_DIR = "/srv/dashboard/"
RSYNC_TIMEOUT = 1800
S3_TIMEOUT = 1800
SSH_TIMEOUT = 120


@dataclass
class MirrorStats:
    downloaded: int = 0
    skipped: int = 0
    pruned: int = 0


def _is_run_key(key: str) -> bool:
    """`.../runs/<runId>/...` 아래 객체는 불변이라 있으면 다시 받지 않는다."""
    return "runs" in key.split("/")[:-1]


def _is_lock_key(key: str) -> bool:
    return "locks" in key.split("/")[:-1]


def _file_md5(path: Path) -> str:
    return _file_digests(path)[1]


def safe_local_path(mirror_dir, key: str) -> Path | None:
    """원격 키를 미러 안의 로컬 경로로 바꾼다. 절대 경로, 역슬래시, '.'/'..' 구간, 빈 구간, 미러 밖으로 풀리는 키는 None(경로 순회 방어)."""
    if not key or key.startswith("/") or "\\" in key or "\x00" in key:
        return None
    if any(part in ("", ".", "..") for part in key.split("/")):
        return None
    mirror = Path(mirror_dir).resolve()
    target = (mirror / key).resolve()
    return mirror / key if target.is_relative_to(mirror) and target != mirror else None


@contextlib.contextmanager
def mirror_lock(work_dir):
    """미러(work/site-mirror)와 Lightsail /srv/dashboard는 접두와 무관하게 하나라서, 미러 동기화부터 rsync까지를
    로컬 flock 하나로 직렬화한다(접두별 S3 잠금과 별개). 다른 게시가 끝날 때까지 기다린다.
    잠금 파일은 미러의 실제 위치 옆에 둔다: 테스트 run처럼 TD_WORK_DIR은 따로이고 `site-mirror`만 심볼릭 링크로
    공유하면, work_dir 기준 잠금은 서로를 막지 못해 두 sync_mirror가 같은 `.part`를 받다 한쪽이 깨진다."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = (work_dir / "site-mirror").resolve().parent  # 링크가 아니거나 아직 없으면 work_dir 그대로
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / ".site-mirror.flock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def sync_mirror(s3, bucket: str, mirror_dir) -> MirrorStats:
    """S3 버킷 전체(운영 + `_test/`, 잠금 제외)를 mirror_dir에 맞춘다(S3가 원본). run 객체는 있으면 건너뛰고,
    그 밖의 파일은 ETag(단일 PUT은 md5)나 크기가 다르면 받는다. S3에 없는 로컬 파일은 지운다(마커가 있는 미러만)."""
    mirror = Path(mirror_dir).resolve()  # 한 번만 resolve해 다운로드 대상과 prune 순회가 같은 경로 표기를 쓴다
    fresh = not mirror.exists() or not any(mirror.iterdir())
    mirror.mkdir(parents=True, exist_ok=True)
    if fresh:
        (mirror / MIRROR_MARKER).write_text("test-dashboard site mirror: S3 bucket mirror, files not in S3 are pruned\n")
    stats = MirrorStats()
    keep: set[Path] = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/") or _is_lock_key(key):
                continue
            target = safe_local_path(mirror, key)
            if target is None:
                print(f"[td] 미러: 안전하지 않은 S3 키를 건너뛴다: {key!r}", file=sys.stderr)
                stats.skipped += 1
                continue
            keep.add(target)
            size, etag = int(obj["Size"]), _etag(obj.get("ETag"))
            if target.is_file() and target.stat().st_size == size:
                if _is_run_key(key) or "-" in etag or _file_md5(target) == etag:
                    stats.skipped += 1
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".part")
            with partial.open("wb") as handle:
                shutil.copyfileobj(s3.get_object(Bucket=bucket, Key=key)["Body"], handle)
            os.replace(partial, target)
            stats.downloaded += 1
    if (mirror / MIRROR_MARKER).exists():
        for path in sorted((p for p in mirror.rglob("*") if p.is_file()), reverse=True):
            if path not in keep and path.name != MIRROR_MARKER:
                path.unlink()
                stats.pruned += 1
        for directory in sorted((p for p in mirror.rglob("*") if p.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    return stats


def upload_files(s3, bucket: str, mirror_dir, paths, env: dict | None = None) -> list[str]:
    """인덱스 파일(재생성되는 파일)을 덮어쓴다. `Cache-Control: no-cache`. 올린 키 목록을 돌려준다.
    텍스트 파일은 올리기 전에 누출 게이트를 지난다(하나라도 걸리면 아무것도 올리지 않는다)."""
    from td.site.pages import TEXT_SUFFIXES
    mirror = Path(mirror_dir)
    files = [Path(path) for path in paths if Path(path).is_file()]
    for path in files:
        if path.suffix.lower() in TEXT_SUFFIXES:
            check_no_home_in_file(path, path.relative_to(mirror).as_posix(), env)
    keys = []
    for path in files:
        key = path.relative_to(mirror).as_posix()
        with path.open("rb") as handle:
            s3.put_object(Bucket=bucket, Key=key, Body=handle, CacheControl=CACHE_NO_CACHE, ContentType=content_type(path))
        keys.append(key)
    return keys


# --- 과제 디렉터리 삭제(설계 §6.4 삭제 범위) -------------------------------------------------------
DELETE_BATCH = 1000                                         # S3 DeleteObjects 한 번의 최대 개수
_PREFIX_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")  # 접두 구간: '.'·'..'·빈 구간·공백·따옴표 없음
_PROJECT_KEY_PREFIX = re.compile(r"(.*/)?projects/([^/]+)/")


def _checked_prefix(prefix: str) -> str:
    """삭제에 쓰는 접두를 확인한다: 빈 문자열(운영 루트) 또는 안전한 구간들로 된 `a/b/` 꼴. 아니면 PublishError."""
    if prefix == "":
        return prefix
    if not isinstance(prefix, str) or not prefix.endswith("/") or \
            not all(_PREFIX_SEGMENT.fullmatch(part) for part in prefix[:-1].split("/")):
        raise PublishError("삭제 요청의 접두가 안전한 꼴이 아니라 거부한다")
    return prefix


def _checked_project_name(name: str) -> str:
    from td.dashboard_config import NAME_PATTERN
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise PublishError("삭제 요청의 과제 이름이 설정 이름 문법에 맞지 않아 거부한다")
    return name


def delete_prefix(s3, bucket: str, site_prefix: str, key_prefix: str) -> int:
    """`<사이트 접두>projects/<과제 이름>/` 아래 객체를 나열해 1000개씩 묶어 지우고 지운 수를 돌려준다.
    key_prefix가 정확히 그 꼴이 아니면(다른 접두, 다른 디렉터리, 이름 없음, '..', 접두만) 아무것도 지우지 않고 PublishError.
    오류 사유에는 키(과제 이름)를 쓰지 않는다(제외된 과제의 이름이 게시 기록에 남지 않게)."""
    match = _PROJECT_KEY_PREFIX.fullmatch(key_prefix) if isinstance(key_prefix, str) else None
    if match is None:
        raise PublishError("삭제 요청이 `(<접두>)projects/<이름>/` 꼴이 아니라 거부한다")
    site_prefix = _checked_prefix(site_prefix)
    name = _checked_project_name(match.group(2))
    if key_prefix != f"{site_prefix}projects/{name}/":
        raise PublishError("삭제 요청이 이번 게시 접두의 `projects/<이름>/`가 아니라 거부한다")
    keys = [obj["Key"] for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=key_prefix)
            for obj in page.get("Contents", [])]
    if any(not key.startswith(key_prefix) for key in keys):
        raise PublishError("삭제 대상 나열에 접두 밖 키가 섞여 거부한다")
    for start in range(0, len(keys), DELETE_BATCH):
        batch = keys[start:start + DELETE_BATCH]
        response = s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True})
        errors = response.get("Errors") or []
        if errors:
            codes = ", ".join(sorted({str(error.get("Code") or "?") for error in errors}))
            raise PublishError(f"S3 객체 삭제 실패 {len(errors)}건({codes})")
    return len(keys)


def lightsail_list_command(prefix: str) -> str:
    """Lightsail `/srv/dashboard/<접두>projects/` 바로 아래 디렉터리를 NUL로 구분해 나열하는 읽기 전용 원격 명령.
    디렉터리가 없으면 아무것도 내지 않고 성공한다."""
    return (f"d='{DASH_DIR}{_checked_prefix(prefix)}projects'; "
            "if [ -d \"$d\" ]; then find \"$d\" -mindepth 1 -maxdepth 1 -type d -print0; fi")


def lightsail_remove_command(prefix: str, name: str) -> str:
    """Lightsail에서 과제 디렉터리 하나만 지우는 원격 명령. 확인한 접두와 설정 문법의 이름으로만 만들고, 경로는 작은따옴표로
    묶는다(허용 문자에 따옴표·공백·`$`가 없다). 경로는 항상 `/srv/dashboard/<접두>projects/<이름>`이다."""
    return f"rm -rf -- '{DASH_DIR}{_checked_prefix(prefix)}projects/{_checked_project_name(name)}'"


def invalidation_paths(mirror_dir, written, prefix: str, sut: str, run_id: str, include_log: bool = True) -> list[str]:
    """무효화 경로: 재생성한 인덱스 파일(디렉터리형 `/dir/`도), hosting.json/html(있으면), publish-log.
    `<prefix>projects/` 아래 파일은 `/<prefix>projects/*` 한 경로로 묶는다(설계 §6.4). 그 밖에 중간 와일드카드는 쓰지 않는다."""
    mirror = Path(mirror_dir)
    projects_root = f"{prefix}projects/"
    paths: list[str] = []
    for path in written:
        key = Path(path).relative_to(mirror).as_posix()
        if key.startswith(projects_root):
            paths.append(f"/{projects_root}*")
            continue
        paths.append("/" + key)
        if key.endswith("index.html"):
            paths.append("/" + key[: -len("index.html")])
    for name in ("hosting.json", "hosting.html"):
        if (mirror / prefix / name).exists():
            paths.append(f"/{prefix}{name}")
    if include_log:
        paths.append(f"/{prefix}suts/{sut}/publish-log/{run_id}.json")
    return list(dict.fromkeys(paths))


def invalidate(cf, distribution_id: str, paths: list[str], run_id: str) -> str:
    response = cf.create_invalidation(DistributionId=distribution_id, InvalidationBatch={
        "Paths": {"Quantity": len(paths), "Items": paths}, "CallerReference": f"{run_id}-{uuid.uuid4().hex[:8]}"})
    return response["Invalidation"]["Id"]


def check_free_space(label: str, free_bytes: int, minimum_bytes: int) -> None:
    if free_bytes < minimum_bytes:
        raise PublishError(f"{label} 디스크 여유가 부족하다: {free_bytes / GIB:.1f}GB 남음 < 최소 {minimum_bytes / GIB:.1f}GB")


# --- Lightsail -------------------------------------------------------------------------------
def _ssh_opts(key_path: str) -> list[str]:
    return ["-i", key_path, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "LogLevel=ERROR"]


def ssh_output(target: str, key_path: str, remote_cmd: str, timeout: float = SSH_TIMEOUT) -> str:
    try:
        done = subprocess.run(["ssh", *_ssh_opts(key_path), target, remote_cmd], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PublishError("timeout:ssh") from exc
    except OSError as exc:
        raise PublishError(f"ssh 실행 실패: {exc}") from exc
    if done.returncode != 0:
        raise PublishError(f"ssh 종료 코드 {done.returncode}: {done.stderr.strip()[-200:]}")
    return done.stdout


def server_free_bytes(target: str, key_path: str) -> int:
    return int(ssh_output(target, key_path, f"df -Pk {DASH_DIR} | awk 'NR==2{{print $4}}'").strip()) * 1024


def server_mem_available_mb(target: str, key_path: str) -> int:
    """`free -m`의 available(MB). 호스팅 비교와 REQ-052가 보는 값이다."""
    return int(ssh_output(target, key_path, "free -m | awk '/^Mem:/{print $7}'").strip())


def rsync_lightsail(mirror_dir, target: str, key_path: str, timeout: float = RSYNC_TIMEOUT, runs: bool = True) -> None:
    """로컬 미러를 Lightsail `/srv/dashboard/`로 올린다(`--delete` 없음).
    1) run 디렉터리 등 새 파일: `--ignore-existing`(불변 run은 덮어쓰지 않는다)  2) 인덱스 파일: `runs/`를 빼고 덮어쓴다.
    인덱스를 마지막에 올려 인덱스가 아직 없는 run을 가리키지 않게 한다. runs=False면 2)만 한다."""
    from td.proc import TIMEOUT_EXIT, run_with_timeout
    base = ["rsync", "-rltz", "--exclude=.*", "--exclude=locks/", "-e", "ssh " + " ".join(_ssh_opts(key_path))]
    destination = f"{target}:{DASH_DIR}"
    source = f"{Path(mirror_dir)}/"
    passes = ([["--ignore-existing"]] if runs else []) + [["--exclude=runs/"]]
    for extra in passes:
        code = run_with_timeout(timeout, [*base, *extra, source, destination], reraise=True)
        if code == TIMEOUT_EXIT:
            raise PublishError(f"timeout:rsync (>{timeout:g}s)")
        if code != 0:
            raise PublishError(f"rsync 종료 코드 {code}")


# --- 상태 규칙과 publish-log -----------------------------------------------------------------
_TIMINGS: dict = {"uploadSeconds": None, "rsyncSeconds": None, "memBeforeMb": None, "memAfterMb": None}


def timings() -> dict:
    """가장 최근 게시의 `{uploadSeconds(S3), rsyncSeconds(Lightsail), memBeforeMb(게시 전 서버 available MB), memAfterMb}`."""
    return dict(_TIMINGS)


def overall_status(hosts: dict) -> tuple[str, str | None]:
    """설계 §13.9: S3(인덱스 포함)가 실패하면 failed, S3는 성공이고 CloudFront나 Lightsail이 실패하면 degraded.
    render(공통 띠를 넣지 못한 리포트, 설계 §5.5), collect(인덱스 단계의 수집, 화면 재설계 §6.4)와 hosting(비교 측정)의
    실패도 degraded다."""
    if hosts["s3"]["status"] != "passed":
        return "failed", f"s3: {hosts['s3'].get('reason') or hosts['s3']['status']}"
    problems = [f"{name}: {hosts[name].get('reason') or 'failed'}" for name in ("render", "collect", "cloudfront", "lightsail", "hosting")
                if hosts.get(name, {}).get("status") == "failed"]  # hosting: TTFB 성공 표본 부족 등 비교 측정 실패
    return ("degraded", "; ".join(problems)) if problems else ("passed", None)


def build_result(status: str, reason: str | None, hosts: dict, timing: dict, size_bytes: int) -> dict:
    """stages/S13.json과 publish-log가 공유하는 필드."""
    return {"status": status, "reason": reason, "hosts": hosts, "timings": timing, "sizeBytes": size_bytes}


def log_key(prefix: str, sut: str, run_id: str) -> str:
    return f"{prefix}suts/{sut}/publish-log/{run_id}.json"


def redact_home(text: str, env: dict | None = None) -> str:
    """게시 전 공통 가림(td.redact): 로컬 경로(홈·작업·임시·저장소), 인프라 식별자, ARN."""
    from td import redact
    return redact.redact_text(text, env=env)


def redact_obj(obj, env: dict | None = None):
    from td import redact
    return redact.redact_obj(obj, env=env)


def exc_text(exc: BaseException, limit: int, env: dict | None = None) -> str:
    """예외 문구를 먼저 가린 뒤 자른다(자르기가 식별자를 반쯤 남겨 가림을 피하지 않게)."""
    return redact_home(str(exc), env)[:limit]


def check_no_home_in_file(path, label: str, env: dict | None = None) -> None:
    """업로드 전 게이트: 올릴 파일에 홈 경로·로컬 절대 경로·인프라 식별자·ARN이 있으면 PublishError
    (사유에는 값을 쓰지 않고 종류 이름만 쓴다)."""
    check_no_home_in_text(Path(path).read_text(errors="replace"), label, env)


def check_no_home_in_text(text: str, label: str, env: dict | None = None) -> None:
    """check_no_home_in_file의 문자열판(파일로 쓰기 전에 거른다)."""
    from td import redact
    kinds = redact.find_leaks(text, env=env)
    if kinds:
        raise PublishError(f"{label}에 로컬 홈 경로·절대 경로·식별자({', '.join(kinds)})가 들어 있어 게시하지 않는다(업로드 전 게이트)")


def write_log(s3, bucket: str, mirror_dir, prefix: str, sut: str, run_id: str, result: dict, to_mirror: bool = True,
              env: dict | None = None) -> str:
    """`suts/<sut>/publish-log/<runId>.json`(갱신 가능한 인덱스 파일)을 S3에, 그리고 미러에 쓴다.
    사유 등 예외 문구에서 온 값은 공통 가림기로 가린 뒤 쓴다."""
    key = log_key(prefix, sut, run_id)
    text = json.dumps(redact_obj({"runId": run_id, "sut": sut, **result}, env), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if to_mirror:
        path = Path(mirror_dir) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    s3.put_object(Bucket=bucket, Key=key, Body=text.encode(), CacheControl=CACHE_NO_CACHE, ContentType="application/json")
    return key


# --- 설정 읽기 ---------------------------------------------------------------------------------
def load_local_env(path) -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(path)
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_hosting(work_dir, env) -> dict:
    state_file = Path(env.get("TD_INFRA_STATE") or Path(work_dir) / "infra" / "terraform.tfstate")
    if not state_file.exists():
        raise PublishError(f"정적 호스팅 인프라 상태가 없다({state_file.name}): infra/static/apply.sh를 먼저 실행한다")
    outputs = json.loads(state_file.read_text()).get("outputs", {})
    try:
        return {"bucket": outputs["bucket"]["value"], "distribution_id": outputs["distribution_id"]["value"]}
    except KeyError as exc:
        raise PublishError(f"인프라 출력에 {exc}가 없다") from exc


def _make_clients(env):
    import boto3
    from botocore.config import Config
    config = Config(retries={"max_attempts": 5, "mode": "standard"}, connect_timeout=10, read_timeout=60)
    region = env.get("AWS_REGION", "ap-northeast-2")
    return boto3.client("s3", region_name=region, config=config), boto3.client("cloudfront", config=config)


class PublishInterrupted(KeyboardInterrupt):
    """SIGINT/SIGTERM을 받아 정리 경로(잠금 해제)로 들어가기 위한 예외."""


def _raise_interrupted(signum, _frame):
    raise PublishInterrupted(signal.Signals(signum).name)


def hosting_default_qualitative() -> Path:
    from td import hosting
    return hosting.QUALITATIVE_PATH


def _measure_both(url: str, connect_ip: str | None) -> tuple:
    from td import hosting
    return hosting.measure(url, connect_ip=connect_ip), hosting.measure_home(url, connect_ip=connect_ip)


# --- 인덱스 단계: 수집 → 삭제 대상 → 재생성 → 삭제 → 업로드 (화면 재설계 §6.3, §6.4) -----------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECT_FAILED_REASON = "수집 실행 실패"
# 설정 오류의 게시 기록 사유. ConfigError 문구에는 과제 이름·repo가 들어 있어 기록에는 이 문장만 쓰고 전체는 표준 오류에 낸다.
CONFIG_ERROR_REASON = "dashboard config error (details on stderr)"
COLLECT_STOP_WAIT = 60          # 중단 신호 뒤 collect.sh가 토큰을 정리하고 끝나기를 기다리는 초(넘으면 SIGKILL)


def _collect_result(status: str = "ok", reasons: list[str] | None = None) -> dict:
    return {"status": status, "reasons": list(reasons or []), "written": [], "excluded": [], "unverified": []}


def _parse_collect_output(text: str) -> dict | None:
    """collect.sh 표준 출력(JSON 한 줄)을 확인한다. 모양이 틀리면 None."""
    try:
        data = json.loads(text.strip())
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("status") not in ("ok", "degraded"):
        return None
    lists = {key: data.get(key, []) for key in ("reasons", "written", "excluded", "unverified")}
    if not all(isinstance(value, list) and all(isinstance(item, str) for item in value) for value in lists.values()):
        return None
    return {"status": data["status"], **lists}


def _stop_child(proc: subprocess.Popen) -> None:
    """자식(collect.sh)에 SIGTERM을 보내고 COLLECT_STOP_WAIT초까지 기다린다(토큰 정리는 collect.sh의 trap이 한다).
    넘으면 그 자식이 이끄는 프로세스 그룹(자식을 새 세션으로 띄웠다) 전체에 SIGKILL을 보내 손자(td.collect, gh)도 남기지 않는다.
    다른 그룹에는 신호를 보내지 않는다. 기다리는 동안 다시 온 신호는 무시한다."""
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    deadline = time.monotonic() + COLLECT_STOP_WAIT
    while True:
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
            return
        except subprocess.TimeoutExpired:
            # 아직 거두지 않은 자식의 pid = 그 그룹 번호(start_new_session)라 다른 프로세스를 가리킬 수 없다
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            proc.wait()
            return
        except PublishInterrupted:
            continue  # 정리 중 중복 신호: 계속 기다린다


def run_collect(env: dict, cfg, site_dir: Path) -> dict:
    """설정에 `repo`가 있는 과제가 있을 때만 `pipeline/collect.sh`를 자식으로 띄워 결과 JSON을 돌려준다.
    자식이 0이 아닌 코드로 끝나거나 표준 출력이 결과 JSON이 아니면 `degraded`(사유 "수집 실행 실패").
    기다리는 동안 PublishInterrupted가 나면 자식에 SIGTERM을 보내 토큰 정리를 기다린 뒤 다시 올린다.
    표준 오류(제외 과제 이름이 나올 수 있다)는 게시기의 표준 오류로 그대로 흘려보내고 결과에 담지 않는다."""
    if not any(project.repo for project in cfg.projects):
        return _collect_result()
    root = Path(env.get("TD_ROOT") or REPO_ROOT)
    if cfg.path is None:
        print("[td] 수집: 설정 파일 경로가 없어 수집하지 않는다", file=sys.stderr)
        return _collect_result("degraded", [COLLECT_FAILED_REASON])
    suts_dir = Path(env.get("TD_DASHBOARD_SUTS_DIR") or root / "suts")
    command = ["bash", str(root / "pipeline" / "collect.sh"), "--config", str(cfg.path), "--site", str(site_dir),
               "--suts-dir", str(suts_dir)]
    Path(site_dir).mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        print(f"[td] 수집: collect.sh를 띄우지 못했다: {exc}", file=sys.stderr)
        return _collect_result("degraded", [COLLECT_FAILED_REASON])
    try:
        stdout, _ = proc.communicate()
    except PublishInterrupted:
        _stop_child(proc)
        raise
    parsed = _parse_collect_output(stdout or "") if proc.returncode == 0 else None
    if parsed is None:
        print(f"[td] 수집: collect.sh 종료 코드 {proc.returncode}, 결과를 읽지 못했다", file=sys.stderr)
        return _collect_result("degraded", [COLLECT_FAILED_REASON])
    return parsed


@dataclass
class IndexOutcome:
    written: list[Path]           # 올린 파일(rebuild가 쓴 파일 + 수집이 쓴 파일)
    collect_status: str           # ok | degraded
    collect_reasons: list[str]    # 이름 없는 사유(개수만)
    deleted: list[str]            # 지운 과제 이름. 게시 기록에 쓰지 않는다
    keep: frozenset[str]          # 남길 과제 이름(설정·암묵 과제 - 이번 제외). Lightsail 정리가 같은 집합을 쓴다
    collect_seconds: float = 0.0  # 수집에 든 시간(S3 업로드 시간에서 뺀다)


def _suts_with_complete_runs(base: Path) -> list[str]:
    """`_COMPLETE`가 있는 run을 가진 SUT(재생성의 암묵 과제와 같은 기준)."""
    suts_dir = base / "suts"
    if not suts_dir.is_dir():
        return []
    return sorted(sut.name for sut in suts_dir.iterdir() if sut.is_dir() and any((sut / "runs").glob("*/_COMPLETE")))


def _keep_names(base: Path, cfg, excluded: list[str]) -> frozenset[str]:
    """남길 과제 이름: 설정의 과제와 암묵 과제(완료 run이 있는 미등록 SUT)에서 이번 수집이 제외한 과제를 뺀 것."""
    from td import dashboard_config
    names = {project.name for project in dashboard_config.with_implicit(cfg, _suts_with_complete_runs(base)).projects}
    return frozenset(names - set(excluded))


def _projects_to_delete(base: Path, keep: frozenset[str], excluded: list[str]) -> list[str]:
    """수집이 제외한 과제 + `projects/` 바로 아래에서 남길 과제가 아닌 디렉터리. 이름 문법에 맞는 것만."""
    from td import dashboard_config
    projects_dir = base / "projects"
    present = [entry.name for entry in projects_dir.iterdir() if entry.is_dir()] if projects_dir.is_dir() else []
    candidates = set(excluded) | {name for name in present if name not in keep}
    names = []
    for name in sorted(candidates):
        if dashboard_config.NAME_PATTERN.fullmatch(name):
            names.append(name)
        else:
            print(f"[td] 삭제: 이름 문법에 맞지 않는 과제 디렉터리는 건드리지 않는다: {name!r}", file=sys.stderr)
    return names


def publish_index(s3, bucket: str, mirror: Path, prefix: str, env: dict) -> IndexOutcome:
    """게시의 인덱스 단계(S13과 인덱스 전용 게시가 같이 쓴다). 접두 잠금과 미러 잠금은 호출자가 잡는다.
    1) 미러 동기화 2) 수집 3) 지울 과제를 정하고 미러에서 지움 4) 재생성 5) S3에서 지움 6) 업로드(no-cache, 누출 게이트)."""
    from td import dashboard_config
    from td.site import index
    mirror = Path(mirror)
    base = mirror / prefix if prefix else mirror
    sync_mirror(s3, bucket, mirror)
    cfg = dashboard_config.resolve(env, Path(env.get("TD_ROOT") or REPO_ROOT), site_prefix=prefix)
    if prefix == "" and cfg.path is None:
        # 운영 루트를 설정 파일 없는(빈) 설정으로 정리하면 설정의 과제 디렉터리가 모두 지워진다. 어떤 삭제보다 먼저 멈춘다.
        raise PublishError("운영 루트 게시에 설정 파일이 없다(빈 테스트 설정으로는 운영 과제를 정리하지 않는다)")
    collect_started = time.monotonic()
    collected = run_collect(env, cfg, base)
    collect_seconds = time.monotonic() - collect_started
    excluded = [name for name in collected["excluded"] if dashboard_config.NAME_PATTERN.fullmatch(name)]
    keep = _keep_names(base, cfg, excluded)
    deleted = _projects_to_delete(base, keep, excluded)
    for name in deleted:
        shutil.rmtree(base / "projects" / name, ignore_errors=True)
    written = index.rebuild(mirror, prefix, cfg, exclude=frozenset(excluded))
    for name in deleted:
        try:
            delete_prefix(s3, bucket, prefix, f"{prefix}projects/{name}/")
        except PublishError:
            raise
        except Exception as exc:  # noqa: BLE001 - 사유에 키(과제 이름)가 들어가지 않게 종류만 남긴다
            print(f"[td] 삭제 실패({name}): {exc}", file=sys.stderr)
            raise PublishError(f"과제 디렉터리 삭제 실패: {type(exc).__name__}") from None
    collected_files = []
    for relative in collected["written"]:
        target = safe_local_path(base, relative)
        if target is not None and target.is_file() and target not in written:
            collected_files.append(target)
    uploads = [*written, *collected_files]
    upload_files(s3, bucket, mirror, uploads, env)
    return IndexOutcome(uploads, collected["status"], list(collected["reasons"]), deleted, keep, collect_seconds)


# --- 오케스트레이션 -----------------------------------------------------------------------------
class Publication:
    def __init__(self, sut: str, run_id: str, run_dir, env: dict, s3=None, cf=None, measure_hosting: bool = True,
                 hosting_measurer: Callable[[str, str | None], tuple] | None = None):
        # measure_hosting=False는 단위 테스트가 네트워크 측정을 끄는 용도, hosting_measurer(url, connect_ip)->(Ttfb, HomeTransfer)는 측정 대체용.
        self.measure_hosting, self.hosting_measurer = measure_hosting, hosting_measurer
        from td import hooks
        self.hooks = hooks
        self.sut, self.run_id, self.run_dir, self.env = sut, run_id, Path(run_dir), env
        self.work_dir = Path(env.get("TD_WORK_DIR") or Path(env.get("TD_ROOT", ".")) / "work")
        self.mirror = self.work_dir / "site-mirror"
        self.prefix = normalize_prefix(env.get("TD_SITE_PREFIX", ""))
        self.key_prefix = f"{self.prefix}suts/{sut}/runs/{run_id}/"
        self.s3, self.cf = s3, cf
        self.bucket = self.distribution_id = ""
        self.lock: Lock | None = None
        self.attempt_id = uuid.uuid4().hex[:12]
        self.hosts: dict = {"s3": {"status": "failed", "reason": "not reached"},
                            "cloudfront": {"status": "skipped", "reason": "not reached"},
                            "lightsail": {"status": "skipped", "reason": "not reached"}}
        self.size_bytes = 0
        self.upload_seconds = 0.0
        self.rsync_seconds: float | None = None
        self.mem_before: int | None = None
        self.mem_after: int | None = None
        self.sealed_before = False  # 이번 시도 전에 이미 _COMPLETE가 있었다
        key, ip = env.get("TD_SSH_KEY_PATH"), env.get("TD_LIGHTSAIL_IP")
        self.ssh_target = f"ubuntu@{ip}" if ip else None
        self.ssh_key = key
        self.min_free = int(float(env.get("TD_MIN_FREE_GB", "2")) * GIB)
        self.lightsail_preflight_error: str | None = None
        self.render_warnings: list[dict] = []  # 렌더 기록(render.json)의 navMissing: 공통 띠를 넣지 못한 리포트
        # 테스트 전용: 객체마다 잠깐 멈춰 SIGINT/SIGKILL을 끼워 넣는다(운영 실행은 TD_SITE_PREFIX가 없어 무시된다).
        self.pause = float(env.get("TD_PUBLISH_PAUSE_SEC", "0") or 0) if env.get("TD_SITE_PREFIX") else 0.0
        self.index_outcome: IndexOutcome | None = None  # 인덱스 단계 결과(지운 과제는 Lightsail 단계가 쓴다)
        self.rsync_runs = True                          # Lightsail에 run 디렉터리도 싣는다(인덱스 전용 게시는 False)
        self.caller_reference = run_id                  # CloudFront 무효화의 CallerReference 머리

    def inject(self, point: str) -> None:
        if self.hooks.should_fail("S13", point, self.env):
            raise InjectedFailure(f"injected failure (TD_FAIL_STAGE=S13:{point})")

    def result(self, status: str, reason: str | None) -> dict:
        timing = {"uploadSeconds": round(self.upload_seconds, 2),
                  "rsyncSeconds": None if self.rsync_seconds is None else round(self.rsync_seconds, 2),
                  "memBeforeMb": self.mem_before, "memAfterMb": self.mem_after}
        return build_result(status, reason, self.hosts, timing, self.size_bytes)

    # -- 단계 ----------------------------------------------------------------------------------
    def preflight(self) -> None:
        self.mirror.parent.mkdir(parents=True, exist_ok=True)
        check_free_space("로컬", shutil.disk_usage(self.mirror.parent).free, self.min_free)
        if not (self.ssh_target and self.ssh_key):
            self.lightsail_preflight_error = "TD_LIGHTSAIL_IP/TD_SSH_KEY_PATH가 설정돼 있지 않다"
            return
        try:
            self.mem_before = server_mem_available_mb(self.ssh_target, self.ssh_key)
            free = server_free_bytes(self.ssh_target, self.ssh_key)
        except (PublishError, ValueError) as exc:
            self.lightsail_preflight_error = f"서버 사전 점검 실패: {exc}"  # 서버에 닿지 않는 것은 Lightsail만의 실패(degraded)
            return
        check_free_space("Lightsail 서버", free, self.min_free)  # 닿는데 모자라면 rsync 전에 S13 failed

    def render(self) -> Manifest:
        from td.site import pages
        site_dir = self.run_dir / pages.PUBLISH_SUBDIR
        shutil.rmtree(site_dir, ignore_errors=True)  # 이전 시도의 낡은 파일이 manifest에 섞이지 않게
        pages.render_run(self.run_dir, self.run_dir)
        record = site_dir / pages.RENDER_RECORD
        self.render_warnings = list(json.loads(record.read_text()).get("navMissing") or []) if record.exists() else []
        if self.render_warnings:  # overall_status가 render 항목의 실패를 degraded로 센다(S3 실패만 failed)
            self.hosts["render"] = {"status": "failed", "reason": "; ".join(
                f"공통 띠 없음: {item.get('file')}" for item in self.render_warnings)}
        check_no_home_in_file(self.run_dir / "run.json", "run.json", self.env)  # run.json은 로컬 원본이 그대로 올라간다
        manifest = build_manifest(site_dir, self.key_prefix, self.run_dir / "run.json")
        self.size_bytes = manifest.total_bytes
        return manifest

    def s3_phase(self, manifest: Manifest) -> None:
        marker = read_complete(self.s3, self.bucket, self.key_prefix)
        if marker is not None:
            self.sealed_before = True
            problems = verify_remote(self.s3, self.bucket, manifest)
            if marker.get("manifestSha256") != manifest.digest():
                problems.append("_COMPLETE의 manifest 체크섬이 다르다")
            if problems:
                raise ContentConflict("이미 게시된 run과 내용이 다르다(업로드하지 않음): " + "; ".join(problems[:5]))
            stats = UploadStats(0, len(manifest.entries), 0.0)
        else:
            stats = upload_run(self.s3, self.bucket, manifest, inject=self.inject, pause=self.pause,
                               deadline=time.monotonic() + S3_TIMEOUT)
            problems = verify_remote(self.s3, self.bucket, manifest)
            if problems:
                raise PublishError("업로드 검증 실패: " + "; ".join(problems[:5]))
            self.inject("complete")
            complete(self.s3, self.bucket, manifest)
        self.upload_seconds += stats.seconds
        self.hosts["s3"] = {"status": "failed", "reason": "index not published", "uploaded": stats.uploaded,
                            "skipped": stats.skipped, "objects": len(manifest.entries)}

    def index_phase(self) -> list[Path]:
        """인덱스 단계(publish_index). 수집이 degraded면 hosts.collect를 failed로 적어 게시 상태를 degraded로 만든다."""
        self.inject("index")
        started = time.monotonic()
        outcome = publish_index(self.s3, self.bucket, self.mirror, self.prefix, self.env)
        self.index_outcome = outcome
        if outcome.collect_status == "degraded":
            self.hosts["collect"] = {"status": "failed", "reason": " · ".join(outcome.collect_reasons) or COLLECT_FAILED_REASON}
        self.upload_seconds += max(0.0, time.monotonic() - started - outcome.collect_seconds)
        self.hosts["s3"] = {**self.hosts["s3"], "status": "passed"}
        self.hosts["s3"].pop("reason", None)
        return outcome.written

    def cloudfront_phase(self, written: list[Path]) -> None:
        try:
            paths = invalidation_paths(self.mirror, written, self.prefix, self.sut, self.run_id, include_log=False)
            if self.index_outcome is not None and self.index_outcome.deleted:
                paths = list(dict.fromkeys([*paths, f"/{self.prefix}projects/*"]))  # 지운 과제 페이지도 캐시에서 뺀다
            invalidation = invalidate(self.cf, self.distribution_id, paths, self.caller_reference)
            self.hosts["cloudfront"] = {"status": "passed", "invalidationId": invalidation, "paths": len(paths)}
        except Exception as exc:  # noqa: BLE001 - 무효화 실패는 degraded(인덱스는 no-cache라 곧 갱신된다)
            self.hosts["cloudfront"] = {"status": "failed", "reason": f"invalidation: {type(exc).__name__}: {exc_text(exc, 200, self.env)}"}

    def _prune_lightsail_projects(self) -> str | None:
        """Lightsail `/srv/dashboard/<접두>projects/` 바로 아래를 원격에서 나열하고, 이름 문법에 맞으면서 남길 과제(IndexOutcome.keep)가
        아닌 디렉터리를 하나씩 지운다. 매 게시 원격 목록에서 정하므로, 앞선 게시가 지우지 못한 디렉터리도 다음 게시가 다시 지운다.
        남길 집합을 정하지 못했으면(인덱스 단계 전 실패) 아무것도 지우지 않는다.
        문법에 맞지 않는 이름은 건드리지 않고 개수만 담은 경고 문장을 돌려준다. 나열·삭제 실패는 개수만 담은 PublishError
        (원격 오류 문구에는 경로, 곧 과제 이름이 들어 있어 게시 기록에 쓰지 않고 표준 오류에만 낸다)."""
        from td.dashboard_config import NAME_PATTERN
        if self.index_outcome is None:
            return None
        directory = f"{DASH_DIR}{self.prefix}projects"
        try:
            listing = ssh_output(self.ssh_target, self.ssh_key, lightsail_list_command(self.prefix))
        except PublishError as exc:
            print(f"[td] Lightsail 과제 목록 조회 실패: {exc}", file=sys.stderr)
            raise PublishError("Lightsail 과제 목록 조회 실패") from None
        unsafe, failures = 0, 0
        for entry in (item for item in listing.split("\0") if item):
            name = entry[len(directory) + 1:] if entry.startswith(directory + "/") else None
            if name is None or not NAME_PATTERN.fullmatch(name):
                unsafe += 1
                continue
            if name in self.index_outcome.keep:
                continue
            try:
                ssh_output(self.ssh_target, self.ssh_key, lightsail_remove_command(self.prefix, name))
            except PublishError as exc:
                failures += 1
                print(f"[td] Lightsail 과제 디렉터리 삭제 실패({name}): {exc}", file=sys.stderr)
        if failures:
            raise PublishError(f"Lightsail 과제 디렉터리 삭제 실패 {failures}개")
        if unsafe:
            print(f"[td] Lightsail: 이름 문법에 맞지 않는 과제 디렉터리 {unsafe}개는 건드리지 않았다", file=sys.stderr)
            return f"이름 문법에 맞지 않는 과제 디렉터리 {unsafe}개는 건드리지 않았다"
        return None

    def lightsail_phase(self) -> None:
        prune_error: PublishError | None = None
        warning: str | None = None
        try:
            self.inject("lightsail")
            if self.lightsail_preflight_error:
                raise PublishError(self.lightsail_preflight_error)
            try:
                warning = self._prune_lightsail_projects()
            except PublishError as exc:
                prune_error = exc  # 정리가 실패해도 나머지 파일은 싣는다(다음 게시가 원격 목록에서 다시 지운다)
            rsync_started = time.monotonic()
            rsync_lightsail(self.mirror, self.ssh_target, self.ssh_key, RSYNC_TIMEOUT, runs=self.rsync_runs)
            self.rsync_seconds = time.monotonic() - rsync_started
            try:
                self.mem_after = server_mem_available_mb(self.ssh_target, self.ssh_key)
            except (PublishError, ValueError):
                self.mem_after = None  # 메모리 측정 실패는 게시 실패가 아니다
            if prune_error is not None:
                raise prune_error
            self.hosts["lightsail"] = {"status": "passed", **({"warning": warning} if warning else {})}
        except (PublishError, OSError) as exc:
            self.hosts["lightsail"] = {"status": "failed", "reason": exc_text(exc, 300, self.env)}

    def _qualitative_path(self) -> Path:
        candidate = Path(self.env.get("TD_ROOT", ".")) / "infra" / "hosting-qualitative.yaml"
        return candidate if candidate.exists() else hosting_default_qualitative()

    def _publish_hosting_files(self, hosting_mod, doc: dict | None, reason: str | None = None) -> None:
        """hosting.json(문서가 있을 때)과 hosting.html(없으면 "측정 없음" 안내)을 미러에 쓰고 S3에 올린 뒤 명시 무효화한다.
        hosting 무효화 결과는 cloudfront 항목의 별도 필드(hostingInvalidationId)에 남겨 앞선 invalidationId/paths를 보존한다."""
        target = self.mirror / self.prefix
        target.mkdir(parents=True, exist_ok=True)
        files = [target / "hosting.html"]
        (target / "hosting.html").write_text(redact_home(hosting_mod.render_html(doc, reason=reason), self.env))
        if doc is not None:
            (target / "hosting.json").write_text(json.dumps(redact_obj(doc, self.env), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            files.append(target / "hosting.json")
        upload_files(self.s3, self.bucket, self.mirror, files, self.env)
        paths = [f"/{self.prefix}{path.name}" for path in files]
        try:
            invalidation = invalidate(self.cf, self.distribution_id, paths, self.caller_reference)
            self.hosts["cloudfront"] = {**self.hosts["cloudfront"], "hostingInvalidationId": invalidation}
        except Exception as exc:  # noqa: BLE001
            problem = f"hosting invalidation: {type(exc).__name__}: {exc_text(exc, 200, self.env)}"
            previous = self.hosts["cloudfront"].get("reason")
            self.hosts["cloudfront"] = {**self.hosts["cloudfront"], "status": "failed",
                                        "reason": f"{previous}; {problem}" if previous else problem}

    def hosting_phase(self) -> None:
        """게시 직후 두 호스트의 TTFB·홈 전송을 재고 hosting.json/hosting.html을 접두 루트에 올린다(no-cache, 명시 무효화).
        Lightsail 쪽은 이어지는 log_phase의 rsync가 함께 싣는다. TTFB 성공 표본 부족이나 측정 오류는 hosts.hosting=failed(degraded)이고
        사유에 예외 문구를 담는다. 측정이 불가능해도 hosting.html(측정 없음 안내)은 남겨 홈 링크가 끊기지 않게 한다."""
        from td import hosting as hosting_mod
        if not self.measure_hosting:
            return
        errors: list[str] = []
        try:
            domain = self.env.get("TD_DOMAIN")
            if not domain:
                raise PublishError("TD_DOMAIN이 설정돼 있지 않다")
            measures = {}
            for name in hosting_mod.HOST_NAMES:
                host = f"{name}.{domain}"
                url = f"https://{host}/{self.prefix}index.html"
                try:
                    ip = hosting_mod.resolve_ip(host, domain)  # 항상 Route53 권한 응답으로 고정(두 호스트 비교 가능성)
                    ttfb, home = (self.hosting_measurer or _measure_both)(url, ip)
                    measures[name] = {"url": url, "ttfb": ttfb, "home": home, "pinned": True}
                except Exception as exc:  # noqa: BLE001 - 이 호스트 표본은 모두 실패로 센다
                    errors.append(f"{name}: {type(exc).__name__}: {exc_text(exc, 200, self.env)}")
                    measures[name] = {"url": url, "ttfb": hosting_mod.Ttfb(None, 0, hosting_mod.SAMPLES),
                                      "home": hosting_mod.HomeTransfer(None, None), "pinned": False}
            doc = hosting_mod.build_document(
                sut=self.sut, run_id=self.run_id, generated_at=_utc_now(), measures=measures, timings=self.result("", None)["timings"],
                qualitative=hosting_mod.load_qualitative(self._qualitative_path()))
            hosting_mod.check_document(doc)
            self._publish_hosting_files(hosting_mod, doc)
            status, reason = hosting_mod.measurement_status(doc)
            if errors:
                status, reason = "failed", "; ".join(x for x in (reason, *errors) if x)
            self.hosts["hosting"] = {"status": status, **({"reason": reason} if reason else {})}
        except Exception as exc:  # noqa: BLE001 - 비교 측정이 게시 자체를 막지 않는다
            reason = f"hosting 측정/게시 실패: {type(exc).__name__}: {exc_text(exc, 200, self.env)}"
            self.hosts["hosting"] = {"status": "failed", "reason": reason}
            try:
                self._publish_hosting_files(hosting_mod, None, reason)
            except Exception:  # noqa: BLE001 - 안내 페이지도 최선 노력
                pass

    # -- 기록(게시 기록 하나를 쓰고, Lightsail에 싣고, 그 경로를 무효화한다) ---------------------------------
    def _write_result(self, result: dict, to_mirror: bool = True) -> None:
        """게시 기록을 쓴다(S13: `suts/<sut>/publish-log/<runId>.json`). IndexPublication은 이 훅과 _log_path만 바꾼다."""
        write_log(self.s3, self.bucket, self.mirror, self.prefix, self.sut, self.run_id, result, to_mirror=to_mirror,
                  env=self.env)

    def _log_path(self) -> str:
        """게시 기록의 무효화 경로."""
        return f"/{log_key(self.prefix, self.sut, self.run_id)}"

    def log_phase(self) -> dict:
        status, reason = overall_status(self.hosts)
        self._write_result(self.result(status, reason))
        if self.hosts["lightsail"]["status"] == "passed":
            try:  # 방금 쓴 publish-log를 Lightsail에도 싣는다(run 페이지가 같은 호스트에서 읽는다)
                rsync_lightsail(self.mirror, self.ssh_target, self.ssh_key, RSYNC_TIMEOUT, runs=False)
            except PublishError as exc:
                self.hosts["lightsail"] = {"status": "failed", "reason": f"publish-log 동기화: {exc_text(exc, 300, self.env)}"[:300]}
                status, reason = overall_status(self.hosts)
                self._write_result(self.result(status, reason))
        self.invalidate_log()
        status, reason = overall_status(self.hosts)
        return self.result(status, reason)

    def invalidate_log(self) -> None:
        """publish-log는 인덱스 뒤에 쓰이므로 쓴 다음에 그 경로만 무효화한다. 실패하면 CloudFront를 failed로 고쳐 로그를 다시 쓴다."""
        try:
            invalidate(self.cf, self.distribution_id, [self._log_path()], self.caller_reference)
            return
        except Exception as exc:  # noqa: BLE001
            self.hosts["cloudfront"] = {"status": "failed", "reason": f"publish-log invalidation: {type(exc).__name__}: {exc_text(exc, 200, self.env)}"}
        status, reason = overall_status(self.hosts)
        self.rewrite_log(self.result(status, reason), reinvalidate=False, locked=True)

    def rewrite_log(self, result: dict, reinvalidate: bool = True, locked: bool = False) -> None:
        """이미 게시한 publish-log를 고쳐 쓴 뒤 Lightsail에도 다시 싣고, 그 경로 하나를 다시 무효화한다(각 단계 최선 노력)."""
        self._write_result(result)
        if self.hosts["lightsail"]["status"] == "passed" and self.ssh_target and self.ssh_key:
            try:
                with contextlib.nullcontext() if locked else mirror_lock(self.work_dir):  # flock은 재진입 불가
                    rsync_lightsail(self.mirror, self.ssh_target, self.ssh_key, RSYNC_TIMEOUT, runs=False)
            except PublishError as exc:
                print(f"[td] publish-log 재동기화(Lightsail) 실패: {exc}", file=sys.stderr)
        if reinvalidate:
            try:
                invalidate(self.cf, self.distribution_id, [self._log_path()], self.caller_reference)
            except Exception as exc:  # noqa: BLE001
                print(f"[td] publish-log 재무효화 실패: {type(exc).__name__}", file=sys.stderr)

    def write_failure_log(self) -> None:
        """실패 사유를 S3 publish-log에 남긴다(잠금을 잡았고, 이미 봉인된 run이 아닐 때만 — 성공 기록을 덮어쓰지 않는다)."""
        if self.lock is None or self.sealed_before or self.s3 is None:
            return
        status, reason = overall_status(self.hosts)
        try:
            self._write_result(self.result(status, reason), to_mirror=False)
        except Exception:  # noqa: BLE001 - 실패 기록은 최선 노력
            pass

    # -- 실행 ----------------------------------------------------------------------------------
    def steps(self) -> dict:
        """사전 점검 뒤의 단계: 렌더 → 접두 잠금 → run 업로드 → (미러 잠금 안에서) 인덱스·무효화·Lightsail·호스팅·기록."""
        manifest = self.render()
        self.lock = acquire_lock(self.s3, self.bucket, self.prefix, self.attempt_id)
        self.s3_phase(manifest)
        with mirror_lock(self.work_dir):
            written = self.index_phase()
            self.cloudfront_phase(written)
            self.lightsail_phase()
            self.hosting_phase()
            return self.log_phase()

    def execute(self) -> dict:
        global _TIMINGS
        _TIMINGS = {"uploadSeconds": None, "rsyncSeconds": None, "memBeforeMb": None, "memAfterMb": None}
        release_warning = ""
        try:
            self.hooks.check_allowed(self.env)
            infra = load_hosting(self.work_dir, self.env)
            self.bucket, self.distribution_id = infra["bucket"], infra["distribution_id"]
            if self.s3 is None or self.cf is None:
                self.s3, self.cf = _make_clients(self.env)
            self.preflight()
            result = self.steps()
        except LockHeld as exc:
            self.hosts["s3"] = {"status": "failed", "reason": str(exc)}
            result = self.result("failed", str(exc))
        except PublishInterrupted as exc:
            self.hosts["s3"] = {**self.hosts["s3"], "status": "failed", "reason": f"interrupted ({exc})"}
            self.write_failure_log()
            result = self.result("failed", f"interrupted ({exc})")
        except ConfigError as exc:
            print(f"[td] 대시보드 설정 오류: {exc}", file=sys.stderr)
            self.hosts["s3"] = {**self.hosts["s3"], "status": "failed", "reason": CONFIG_ERROR_REASON}
            self.write_failure_log()
            result = self.result("failed", CONFIG_ERROR_REASON)
        except (PublishError, self.hooks.HookRefused) as exc:
            self.hosts["s3"] = {**self.hosts["s3"], "status": "failed", "reason": exc_text(exc, 600, self.env)}
            self.write_failure_log()
            result = self.result("failed", exc_text(exc, 600, self.env))
        except Exception as exc:  # noqa: BLE001 - 예상 밖 오류도 단계를 failed로 기록한다
            reason = f"internal error: {type(exc).__name__}: {exc_text(exc, 400, self.env)}"
            self.hosts["s3"] = {**self.hosts["s3"], "status": "failed", "reason": reason}
            self.write_failure_log()
            result = self.result("failed", reason)
        finally:
            signal.signal(signal.SIGINT, signal.SIG_IGN)  # 정리 도중의 중복 신호로 잠금 해제가 끊기지 않게 한다
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if self.lock is not None:
                try:
                    if not release(self.s3, self.lock):
                        release_warning = "잠금이 이미 다른 소유자로 바뀌었거나 없어 해제하지 않았다"
                except Exception as exc:  # noqa: BLE001
                    release_warning = f"잠금 해제 실패(수동 --force-unlock {self.lock.attempt_id} 필요): {type(exc).__name__}"
        if release_warning:
            print(f"[td] {release_warning}", file=sys.stderr)
            if result["status"] != "failed":
                self.hosts["s3"]["warning"] = release_warning
                reason = "; ".join(x for x in (result["reason"], release_warning) if x)
                result = self.result(result["status"], reason)
                try:
                    self.rewrite_log(result)
                except Exception:  # noqa: BLE001
                    pass
        _TIMINGS = dict(result["timings"])
        return result


def run_publish(sut: str, run_id: str, run_dir, env: dict | None = None, s3=None, cf=None) -> int:
    """S13 본체. stages/S13.json을 마감하고 종료 코드(failed 1, 그 밖 0)를 돌려준다."""
    from td import state
    env = dict(os.environ if env is None else env)
    root = Path(env.get("TD_ROOT", Path(__file__).resolve().parents[2]))
    for key, value in load_local_env(root / "infra" / "local.env").items():
        env.setdefault(key, value)  # 실제 환경 변수가 우선
    signal.signal(signal.SIGINT, _raise_interrupted)
    signal.signal(signal.SIGTERM, _raise_interrupted)
    publication = Publication(sut, run_id, run_dir, env, s3, cf)
    result = publication.execute()
    result = redact_obj(result, env)  # S13.json·run.json도 다음 게시에 실린다
    extra = {k: result[k] for k in ("hosts", "timings", "sizeBytes")}
    state.end(run_dir, "S13", result["status"], result["reason"], extra=extra)
    print(f"[td] S13 {result['status']}" + (f": {result['reason']}" if result["reason"] else ""), file=sys.stderr)
    return 1 if result["status"] == "failed" else 0


# --- 인덱스 전용 게시(화면 재설계 §6.4): run 없이 수집과 인덱스만 갱신한다 ----------------------------------------
def index_log_key(prefix: str) -> str:
    return f"{prefix}publish-log/index.json"


def write_index_log(s3, bucket: str, mirror, prefix: str, result: dict, env: dict | None = None,
                    to_mirror: bool = True) -> str:
    """인덱스 전용 게시의 기록(`<접두>publish-log/index.json`: 상태, 사유, 호스트별 결과, 시간)을 가린 뒤 누출 게이트를 지나
    S3(no-cache)에, 그리고 미러에 쓴다. 지운 과제 이름과 수집의 제외·미확인 목록은 결과에 넣지 않는다(호출자가 지킨다)."""
    key = index_log_key(prefix)
    text = json.dumps(redact_obj({"kind": "index", **result}, env), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    check_no_home_in_text(text, key, env)
    if to_mirror:
        path = Path(mirror) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    s3.put_object(Bucket=bucket, Key=key, Body=text.encode(), CacheControl=CACHE_NO_CACHE, ContentType="application/json")
    return key


class IndexPublication(Publication):
    """`td.publish index-only`: 접두 잠금 → 미러 잠금 → publish_index → 무효화 → Lightsail(원격 목록 기준 정리, 인덱스 rsync) → 기록.
    잠금·신호·해제와 기록 쓰기 순서는 Publication을 그대로 쓰고 기록 훅(_write_result, _log_path)만 바꾼다. run을 만들지 않는다."""

    def __init__(self, env: dict, s3=None, cf=None):
        super().__init__("", "index", ".", env, s3, cf, measure_hosting=False)
        self.rsync_runs = False
        self.caller_reference = f"index-{self.attempt_id}"

    def steps(self) -> dict:
        self.lock = acquire_lock(self.s3, self.bucket, self.prefix, self.attempt_id)
        with mirror_lock(self.work_dir):
            written = self.index_phase()
            self.cloudfront_phase(written)
            self.lightsail_phase()
            return self.log_phase()

    def _write_result(self, result: dict, to_mirror: bool = True) -> None:
        write_index_log(self.s3, self.bucket, self.mirror, self.prefix, result, self.env, to_mirror=to_mirror)

    def _log_path(self) -> str:
        return f"/{index_log_key(self.prefix)}"


def run_index_only(env: dict | None = None, s3=None, cf=None) -> int:
    """인덱스 전용 게시 본체. 표준 오류에 한 줄을 내고 종료 코드(failed 1, 그 밖 0)를 돌려준다."""
    env = dict(os.environ if env is None else env)
    root = Path(env.get("TD_ROOT") or REPO_ROOT)
    for key, value in load_local_env(root / "infra" / "local.env").items():
        env.setdefault(key, value)  # 실제 환경 변수가 우선
    signal.signal(signal.SIGINT, _raise_interrupted)
    signal.signal(signal.SIGTERM, _raise_interrupted)
    result = redact_obj(IndexPublication(env, s3, cf).execute(), env)
    print(f"[td] index-only {result['status']}" + (f": {result['reason']}" if result["reason"] else ""), file=sys.stderr)
    return 1 if result["status"] == "failed" else 0


def run_force_unlock(attempt_id: str, env: dict | None = None, s3=None) -> int:
    env = dict(os.environ if env is None else env)
    work_dir = Path(env.get("TD_WORK_DIR") or Path(env.get("TD_ROOT", ".")) / "work")
    prefix = normalize_prefix(env.get("TD_SITE_PREFIX", ""))
    try:
        bucket = load_hosting(work_dir, env)["bucket"]
        s3 = s3 or _make_clients(env)[0]
        outcome = force_unlock(s3, bucket, prefix, attempt_id)
    except LockMismatch as exc:
        print(f"[td] {exc}", file=sys.stderr)
        return 4
    except PublishError as exc:
        print(f"[td] force-unlock 실패: {exc}", file=sys.stderr)
        return 1
    print(f"[td] force-unlock {attempt_id}: {outcome}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.publish")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--sut", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--run-dir", required=True)
    unlock = sub.add_parser("force-unlock")
    unlock.add_argument("--attempt", required=True)
    sub.add_parser("index-only")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        return run_publish(args.sut, args.run_id, args.run_dir)
    if args.cmd == "index-only":
        return run_index_only()
    return run_force_unlock(args.attempt)


if __name__ == "__main__":
    sys.exit(main())
