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


