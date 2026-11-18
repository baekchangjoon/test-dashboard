"""S13 게시: S3(원본) 업로드, 잠금, 인덱스 재생성, CloudFront 무효화, Lightsail 미러, publish-log.

설계 §13.1, §13.9 참조. 구성
  10a  manifest, 조건부 업로드(`If-None-Match: *`), 검증, `_COMPLETE`
  10b  잠금(`<prefix>locks/publish`)
  10c  미러 동기화, 무효화, rsync, 상태 규칙, publish-log, 오케스트레이션

S3 클라이언트는 인자로 받아(boto3 호환 객체) 단위 테스트에서 메모리 구현으로 바꿀 수 있다.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from botocore.exceptions import ClientError

CACHE_IMMUTABLE = "max-age=31536000, immutable"
CACHE_NO_CACHE = "no-cache"
COMPLETE_NAME = "_COMPLETE"
# S3 조건부 쓰기가 이미 객체가 있을 때 돌려주는 코드(412), 동시 쓰기 충돌(409)
EXISTS_CODES = ("PreconditionFailed", "ConditionalRequestConflict")
# 게시본에서 뺀다: 최종 S13 결과는 publish-log가 기준이고, 재시도마다 시각이 달라져 재게시 비교를 깨뜨린다.
EXCLUDED_SITE_FILES = ("stages/S13.json",)


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
