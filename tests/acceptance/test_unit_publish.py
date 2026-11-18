"""td.publish 단위 테스트(FakeS3, 외부 접근 없음): manifest, 조건부 업로드, 잠금, 미러, rsync, 상태 규칙(REQ-043/046/070 보조)."""
import hashlib
import json
import os
import stat
import time
from pathlib import Path

import pytest

from td import publish
from helpers import FakeS3

BUCKET = "td-reports-test"
KEY_PREFIX = "_test/x/suts/s/runs/r1/"


def make_site(tmp_path: Path, files: dict[str, str]) -> Path:
    site = tmp_path / "site"
    for rel, text in files.items():
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return site


@pytest.fixture
def site(tmp_path):
    return make_site(tmp_path, {"index.html": "<html>1</html>", "run.json": "{\"stale\": 1}", "a/b.html": "b",
                                "stages/S01.json": "{}", "stages/S13.json": "{\"status\": \"running\"}"})


@pytest.fixture
def run_json(tmp_path):
    path = tmp_path / "run.json"
    path.write_text('{"runId": "r1"}\n')
    return path


# --- manifest ----------------------------------------------------------------------------
def test_manifest_uses_local_run_json_and_skips_s13_stage(site, run_json):
    manifest = publish.build_manifest(site, KEY_PREFIX, run_json)
    assert sorted(manifest.entries) == ["a/b.html", "index.html", "run.json", "stages/S01.json"]
    entry = manifest.entries["run.json"]
    assert entry.md5 == hashlib.md5(run_json.read_bytes()).hexdigest() and entry.path == run_json
    again = publish.build_manifest(site, KEY_PREFIX, run_json)
    assert again.digest() == manifest.digest()
    (site / "index.html").write_text("changed")
    assert publish.build_manifest(site, KEY_PREFIX, run_json).digest() != manifest.digest()


def test_content_type_and_cache_constants():
    assert publish.content_type(Path("x.html")).startswith("text/html")
    assert publish.content_type(Path("x.json")).startswith("application/json")
    assert publish.CACHE_IMMUTABLE == "max-age=31536000, immutable" and publish.CACHE_NO_CACHE == "no-cache"


# --- 업로드 ------------------------------------------------------------------------------
def test_upload_uses_conditional_put_and_immutable_cache(site, run_json):
    s3 = FakeS3()
    manifest = publish.build_manifest(site, KEY_PREFIX, run_json)
    stats = publish.upload_run(s3, BUCKET, manifest)
    assert stats.uploaded == 4 and stats.skipped == 0
    puts = [c for c in s3.calls if c[0] == "put"]
    assert all(c[2]["IfNoneMatch"] == "*" and c[2]["CacheControl"] == publish.CACHE_IMMUTABLE for c in puts)
    assert s3.objects[KEY_PREFIX + "run.json"]["data"] == run_json.read_bytes()
    assert publish.verify_remote(s3, BUCKET, manifest) == []


def test_reupload_same_content_skips_and_different_content_fails_without_overwrite(site, run_json):
    s3 = FakeS3()
    manifest = publish.build_manifest(site, KEY_PREFIX, run_json)
    publish.upload_run(s3, BUCKET, manifest)
    stats = publish.upload_run(s3, BUCKET, manifest)
    assert (stats.uploaded, stats.skipped) == (0, 4)
    etags = {k: v["etag"] for k, v in s3.objects.items()}
    (site / "a" / "b.html").write_text("different")
    changed = publish.build_manifest(site, KEY_PREFIX, run_json)
    with pytest.raises(publish.ContentConflict, match="a/b.html"):
        publish.upload_run(s3, BUCKET, changed)
    assert {k: v["etag"] for k, v in s3.objects.items()} == etags


def test_injection_points_leave_partial_upload_and_retry_completes(site, run_json):
    s3 = FakeS3()
    manifest = publish.build_manifest(site, KEY_PREFIX, run_json)
    points: list[str] = []

    def inject(point):
        points.append(point)
        if len(points) == 1 or point == "upload-mid":
            raise publish.InjectedFailure(point)

    with pytest.raises(publish.InjectedFailure):
        publish.upload_run(s3, BUCKET, manifest, inject=inject)
    assert points == ["upload-first"] and len(s3.objects) == 1
    points.clear()
    with pytest.raises(publish.InjectedFailure):
        publish.upload_run(s3, BUCKET, manifest, inject=lambda p: (_ for _ in ()).throw(publish.InjectedFailure(p)) if p == "upload-mid" else None)
    assert 1 < len(s3.objects) < 4
    stats = publish.upload_run(s3, BUCKET, manifest)
    assert stats.uploaded + stats.skipped == 4 and publish.verify_remote(s3, BUCKET, manifest) == []


def test_verify_remote_reports_missing_extra_and_different(site, run_json):
    s3 = FakeS3()
    manifest = publish.build_manifest(site, KEY_PREFIX, run_json)
    publish.upload_run(s3, BUCKET, manifest)
    del s3.objects[KEY_PREFIX + "index.html"]
    s3.put_object(Bucket=BUCKET, Key=KEY_PREFIX + "a/b.html.bak", Body=b"x")
    s3.objects[KEY_PREFIX + "a/b.html"]["etag"] = "0" * 32
    problems = " | ".join(publish.verify_remote(s3, BUCKET, manifest))
    assert "missing: index.html" in problems and "extra: a/b.html.bak" in problems and "differs: a/b.html" in problems


def test_complete_is_conditional_and_idempotent(site, run_json):
    s3 = FakeS3()
    manifest = publish.build_manifest(site, KEY_PREFIX, run_json)
    publish.upload_run(s3, BUCKET, manifest)
    assert publish.read_complete(s3, BUCKET, KEY_PREFIX) is None
    publish.complete(s3, BUCKET, manifest)
    first = s3.objects[KEY_PREFIX + "_COMPLETE"]["etag"]
    publish.complete(s3, BUCKET, manifest)  # 같은 내용이면 성공
    assert s3.objects[KEY_PREFIX + "_COMPLETE"]["etag"] == first
    assert publish.read_complete(s3, BUCKET, KEY_PREFIX)["manifestSha256"] == manifest.digest()
    (site / "index.html").write_text("changed")
    with pytest.raises(publish.ContentConflict):
        publish.complete(s3, BUCKET, publish.build_manifest(site, KEY_PREFIX, run_json))


# --- 잠금 --------------------------------------------------------------------------------
def test_lock_acquire_conflict_release():
    s3 = FakeS3()
    lock = publish.acquire_lock(s3, BUCKET, "_test/x/", "att-1")
    assert "_test/x/locks/publish" in s3.objects
    info = json.loads(s3.objects["_test/x/locks/publish"]["data"])
    assert info["attemptId"] == "att-1" and info["owner"]["pid"] == os.getpid() and info["acquiredAt"]
    with pytest.raises(publish.LockHeld) as held:
        publish.acquire_lock(s3, BUCKET, "_test/x/", "att-2")
    message = str(held.value)
    assert "att-1" in message and "--force-unlock att-1" in message and info["owner"]["host"] in message
    assert publish.release(s3, lock) is True
    assert "_test/x/locks/publish" not in s3.objects
    publish.acquire_lock(s3, BUCKET, "_test/x/", "att-3")  # 해제 뒤에는 다시 잡을 수 있다


def test_lock_is_scoped_by_prefix():
    s3 = FakeS3()
    publish.acquire_lock(s3, BUCKET, "", "prod")
    publish.acquire_lock(s3, BUCKET, "_test/x/", "test")
    assert {"locks/publish", "_test/x/locks/publish"} <= set(s3.objects)


def test_release_does_not_delete_someone_elses_lock():
    s3 = FakeS3()
    lock = publish.acquire_lock(s3, BUCKET, "", "att-1")
    publish.force_unlock(s3, BUCKET, "", "att-1")
    other = publish.acquire_lock(s3, BUCKET, "", "att-2")
    assert publish.release(s3, lock) is False
    assert "locks/publish" in s3.objects and other.etag == s3.objects["locks/publish"]["etag"]


def test_release_falls_back_when_conditional_delete_unsupported():
    s3 = FakeS3(supports_conditional_delete=False)
    lock = publish.acquire_lock(s3, BUCKET, "", "att-1")
    assert publish.release(s3, lock) is True
    assert "locks/publish" not in s3.objects
    assert any(call[0] == "delete" and call[2]["IfMatch"] for call in s3.calls)  # 먼저 조건부를 시도했다


def test_fallback_delete_refuses_when_lock_changed():
    s3 = FakeS3(supports_conditional_delete=False)
    lock = publish.acquire_lock(s3, BUCKET, "", "att-1")
    s3.objects["locks/publish"]["etag"] = "f" * 32  # 다른 소유자가 교체
    assert publish.release(s3, lock) is False and "locks/publish" in s3.objects


def test_force_unlock_matches_attempt_id_only():
    s3 = FakeS3()
    publish.acquire_lock(s3, BUCKET, "", "att-1")
    with pytest.raises(publish.LockMismatch, match="att-1"):
        publish.force_unlock(s3, BUCKET, "", "att-other")
    assert "locks/publish" in s3.objects
    assert publish.force_unlock(s3, BUCKET, "", "att-1") == "released"
    assert publish.force_unlock(s3, BUCKET, "", "att-1") == "absent"


# --- 접두 정규화 ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [("", ""), ("/", ""), ("_test/x", "_test/x/"), ("/_test/x/", "_test/x/")])
def test_normalize_prefix(raw, expected):
    assert publish.normalize_prefix(raw) == expected


def test_normalize_prefix_rejects_parent_segments():
    with pytest.raises(ValueError):
        publish.normalize_prefix("_test/../x")


