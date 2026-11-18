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


# --- 미러 --------------------------------------------------------------------------------
def test_sync_mirror_downloads_skips_runs_and_prunes(tmp_path):
    s3 = FakeS3()
    mirror = tmp_path / "mirror"
    for key, body in {"suts.json": b"1", "suts/s/runs/r1/index.html": b"run", "suts/s/runs/r1/_COMPLETE": b"{}",
                      "locks/publish": b"lock", "_test/x/locks/publish": b"lock"}.items():
        s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    stats = publish.sync_mirror(s3, BUCKET, mirror)
    assert (mirror / "suts.json").read_bytes() == b"1" and (mirror / "suts/s/runs/r1/_COMPLETE").exists()
    assert not (mirror / "locks").exists() and not (mirror / "_test").exists()
    assert stats.downloaded == 3
    # 불변 run 객체는 있으면 다시 받지 않고, 인덱스 파일은 내용이 바뀌면 받는다. S3에 없는 파일은 지운다.
    (mirror / "suts/s/runs/r1/index.html").write_bytes(b"RUN")  # 같은 크기: 건너뛰어 그대로
    s3.put_object(Bucket=BUCKET, Key="suts.json", Body=b"22")
    (mirror / "stray.json").write_text("x")
    stats = publish.sync_mirror(s3, BUCKET, mirror)
    assert (mirror / "suts/s/runs/r1/index.html").read_bytes() == b"RUN"
    assert (mirror / "suts.json").read_bytes() == b"22" and not (mirror / "stray.json").exists()
    assert stats.downloaded == 1 and stats.pruned == 1


def test_sync_mirror_does_not_prune_without_marker_dir(tmp_path):
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    (mirror / "keep.txt").write_text("mine")
    publish.sync_mirror(FakeS3(), BUCKET, mirror)
    assert (mirror / "keep.txt").exists()


# --- 무효화 경로 ---------------------------------------------------------------------------
def test_invalidation_paths_are_explicit_without_mid_wildcards(tmp_path):
    mirror = tmp_path
    (mirror / "_test/x").mkdir(parents=True)
    (mirror / "_test/x/hosting.json").write_text("{}")
    written = [mirror / "_test/x/index.html", mirror / "_test/x/suts.json", mirror / "_test/x/suts/s/runs.json"]
    paths = publish.invalidation_paths(mirror, written, "_test/x/", "s", "r1")
    assert "/_test/x/index.html" in paths and "/_test/x/" in paths and "/_test/x/suts/s/runs.json" in paths
    assert "/_test/x/hosting.json" in paths and "/_test/x/hosting.html" not in paths  # 있는 것만
    assert "/_test/x/suts/s/publish-log/r1.json" in paths
    assert all(p.startswith("/") and "*" not in p for p in paths) and len(paths) == len(set(paths))


# --- 디스크 여유 -----------------------------------------------------------------------------
def test_disk_check_fails_below_minimum():
    publish.check_free_space("local", 3 * 1024**3, 2 * 1024**3)
    with pytest.raises(publish.PublishError, match="local.*2.0"):
        publish.check_free_space("local", 1 * 1024**3, 2 * 1024**3)


# --- rsync(가짜 실행 파일) ---------------------------------------------------------------------
def fake_rsync(tmp_path: Path, body: str) -> dict:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "rsync"
    script.write_text(f"#!/usr/bin/env bash\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}"}


def test_rsync_runs_new_runs_first_then_overwrites_index_files(tmp_path, monkeypatch):
    log = tmp_path / "rsync.log"
    monkeypatch.setenv("PATH", fake_rsync(tmp_path, f'echo "$@" >> {log}')["PATH"])
    publish.rsync_lightsail(tmp_path / "mirror", "ubuntu@203.0.113.1", "/key", timeout=30)
    first, second = log.read_text().splitlines()
    assert "--ignore-existing" in first and "--exclude=runs/" not in first
    assert "--ignore-existing" not in second and "--exclude=runs/" in second
    assert all("--delete" not in line and "locks/" in line and "ubuntu@203.0.113.1:/srv/dashboard/" in line for line in (first, second))
    assert "BatchMode=yes" in first and "-i /key" in first


def test_rsync_hang_times_out_and_kills_group(tmp_path, monkeypatch):
    pid_file = tmp_path / "child.pid"
    monkeypatch.setenv("PATH", fake_rsync(tmp_path, f"sleep 300 & echo $! > {pid_file}; wait")["PATH"])
    monkeypatch.setenv("TD_KILL_GRACE", "1")
    started = time.time()
    with pytest.raises(publish.PublishError, match="timeout"):
        publish.rsync_lightsail(tmp_path / "mirror", "ubuntu@203.0.113.1", "/key", timeout=1)
    assert time.time() - started < 20
    child = int(pid_file.read_text())
    for _ in range(40):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.25)
    else:
        pytest.fail("rsync 자식(sleep)이 시간 초과 뒤에도 남아 있다")


def test_rsync_failure_exit_code_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", fake_rsync(tmp_path, "exit 23")["PATH"])
    with pytest.raises(publish.PublishError, match="23"):
        publish.rsync_lightsail(tmp_path / "mirror", "ubuntu@203.0.113.1", "/key", timeout=30)


# --- 상태 규칙(설계 §13.9) -----------------------------------------------------------------------
def host(status, reason=None):
    return {"status": status, **({"reason": reason} if reason else {})}


@pytest.mark.parametrize("s3,cf,ls,expected", [
    ("passed", "passed", "passed", "passed"),
    ("passed", "passed", "failed", "degraded"),
    ("passed", "failed", "passed", "degraded"),
    ("failed", "passed", "passed", "failed"),
    ("failed", "skipped", "failed", "failed"),
])
def test_overall_status_rules(s3, cf, ls, expected):
    status, reason = publish.overall_status({"s3": host(s3, "s3 down"), "cloudfront": host(cf, "cf down"),
                                             "lightsail": host(ls, "ls down")})
    assert status == expected
    assert (reason is None) == (expected == "passed")
    if expected == "failed":
        assert "s3 down" in reason
    if expected == "degraded":
        assert ("ls down" in reason) or ("cf down" in reason)


def test_timings_default_shape():
    assert set(publish.timings()) == {"uploadSeconds", "memBeforeMb", "memAfterMb"}


def test_log_payload_has_shared_fields():
    result = publish.build_result("failed", "x", {"s3": host("failed", "x")}, {"uploadSeconds": 1.5, "memBeforeMb": None, "memAfterMb": None}, 123)
    assert result == {"status": "failed", "reason": "x", "hosts": {"s3": {"status": "failed", "reason": "x"}},
                      "timings": {"uploadSeconds": 1.5, "memBeforeMb": None, "memAfterMb": None}, "sizeBytes": 123}


# --- 경로 순회 방어(보안 리뷰) ------------------------------------------------------------------
@pytest.mark.parametrize("key", ["../evil", "a/../../evil", "/abs", "a\\b", "a//b", "./x", "a/./b", "..", ""])
def test_safe_local_path_rejects_malicious_keys(tmp_path, key):
    assert publish.safe_local_path(tmp_path / "m", key) is None


def test_safe_local_path_rejects_symlink_escape(tmp_path):
    mirror = tmp_path / "m"
    mirror.mkdir()
    (mirror / "link").symlink_to(tmp_path)
    assert publish.safe_local_path(mirror, "link/x") is None
    assert publish.safe_local_path(mirror, "ok/x.json") == mirror / "ok/x.json"


def test_sync_mirror_skips_malicious_keys_and_logs(tmp_path, capsys):
    s3 = FakeS3()
    for key in ("../escape.txt", "/abs.txt", "a/../../escape2.txt", "good.json"):
        s3.put_object(Bucket=BUCKET, Key=key, Body=b"x")
    mirror = tmp_path / "mirror"
    publish.sync_mirror(s3, BUCKET, mirror)
    assert (mirror / "good.json").exists()
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "escape2.txt").exists()
    err = capsys.readouterr().err
    assert "../escape.txt" in err and "/abs.txt" in err


# --- Publication.execute 상태(CloudFront 실패, Lightsail 사전 점검 실패, 잠금 해제 실패) ---------------------
import signal as _signal

from helpers import make_local_run
from td import state


class FailingCloudFront:
    def create_invalidation(self, **kwargs):
        raise RuntimeError("cloudfront down")


class OkCloudFront:
    def __init__(self):
        self.paths = []

    def create_invalidation(self, DistributionId, InvalidationBatch):
        self.paths.append(InvalidationBatch["Paths"]["Items"])
        return {"Invalidation": {"Id": f"I{len(self.paths)}"}}


@pytest.fixture
def exec_env(tmp_path, monkeypatch):
    saved = {sig: _signal.getsignal(sig) for sig in (_signal.SIGINT, _signal.SIGTERM)}
    work = tmp_path / "work"
    (work / "infra").mkdir(parents=True)
    (work / "infra" / "terraform.tfstate").write_text(json.dumps(
        {"outputs": {"bucket": {"value": BUCKET}, "distribution_id": {"value": "DIST"}}}))
    run_id = "20261119-000001Z-b6f9393-manual-0000000a"
    run_dir = make_local_run(tmp_path / "runs", "sutx", run_id)
    state.begin(run_dir, "S13")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("ssh", "echo 99999999999"), ("rsync", "exit 0")):
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    env = {"TD_WORK_DIR": str(work), "TD_ROOT": str(tmp_path), "TD_SITE_PREFIX": "_test/u/",
           "TD_LIGHTSAIL_IP": "203.0.113.9", "TD_SSH_KEY_PATH": "/key", "PATH": os.environ["PATH"]}
    yield run_id, run_dir, env, tmp_path
    for sig, handler in saved.items():
        _signal.signal(sig, handler)


def execute(run_id, run_dir, env, s3, cf):
    return publish.Publication("sutx", run_id, run_dir, env, s3, cf).execute()


def test_execute_all_ok_invalidates_log_after_it_is_written(exec_env):
    run_id, run_dir, env, _ = exec_env
    s3, cf = FakeS3(), OkCloudFront()
    result = execute(run_id, run_dir, env, s3, cf)
    assert result["status"] == "passed", result
    assert len(cf.paths) == 2
    assert not any("publish-log" in p for p in cf.paths[0]), "첫 무효화에는 아직 없는 publish-log가 없어야 한다"
    assert cf.paths[1] == [f"/_test/u/suts/sutx/publish-log/{run_id}.json"]
    assert "_test/u/locks/publish" not in s3.objects


def test_execute_cloudfront_failure_is_degraded(exec_env):
    run_id, run_dir, env, _ = exec_env
    s3 = FakeS3()
    result = execute(run_id, run_dir, env, s3, FailingCloudFront())
    assert result["status"] == "degraded" and "cloudfront" in result["reason"]
    assert result["hosts"]["s3"]["status"] == "passed" and result["hosts"]["cloudfront"]["status"] == "failed"
    log = json.loads(s3.objects[f"_test/u/suts/sutx/publish-log/{run_id}.json"]["data"])
    assert log["status"] == "degraded" and log["hosts"]["cloudfront"]["status"] == "failed"


def test_execute_lightsail_unreachable_preflight_is_degraded(exec_env):
    run_id, run_dir, env, tmp_path = exec_env
    (tmp_path / "bin" / "ssh").write_text("#!/usr/bin/env bash\necho 'no route' >&2\nexit 255\n")
    result = execute(run_id, run_dir, env, FakeS3(), OkCloudFront())
    assert result["status"] == "degraded", result
    assert result["hosts"]["lightsail"]["status"] == "failed" and "사전 점검" in result["hosts"]["lightsail"]["reason"]
    assert result["hosts"]["s3"]["status"] == "passed"


def test_execute_lock_release_failure_is_recorded_in_log(exec_env):
    run_id, run_dir, env, _ = exec_env

    class ReleaseFails(FakeS3):
        def delete_object(self, Bucket, Key, IfMatch=None):
            if Key.endswith("locks/publish"):
                raise RuntimeError("boom")
            return super().delete_object(Bucket, Key, IfMatch)

    s3 = ReleaseFails()
    result = execute(run_id, run_dir, env, s3, OkCloudFront())
    assert result["status"] == "passed" and "잠금 해제 실패" in result["reason"]
    assert "--force-unlock" in result["hosts"]["s3"]["warning"]
    log = json.loads(s3.objects[f"_test/u/suts/sutx/publish-log/{run_id}.json"]["data"])
    assert log["reason"] == result["reason"] and "warning" in log["hosts"]["s3"]


# --- 미러 경로 표기(상대, 심볼릭 링크)에서도 prune이 받은 파일을 지우지 않는다 ---------------------------------
def _seeded_s3():
    s3 = FakeS3()
    for key in ("suts.json", "suts/s/runs/r1/index.html", "suts/s/runs/r1/_COMPLETE"):
        s3.put_object(Bucket=BUCKET, Key=key, Body=b"x")
    return s3


def test_sync_mirror_relative_path_keeps_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    publish.sync_mirror(_seeded_s3(), BUCKET, "rel-mirror")
    assert (tmp_path / "rel-mirror/suts.json").exists() and (tmp_path / "rel-mirror/suts/s/runs/r1/_COMPLETE").exists()
    stats = publish.sync_mirror(_seeded_s3(), BUCKET, "rel-mirror")  # 두 번째 동기화(prune 경로)도 유지
    assert stats.pruned == 0 and (tmp_path / "rel-mirror/suts.json").exists()


def test_sync_mirror_symlinked_dir_keeps_files(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    publish.sync_mirror(_seeded_s3(), BUCKET, link)
    stats = publish.sync_mirror(_seeded_s3(), BUCKET, link)
    assert stats.pruned == 0 and (real / "suts.json").exists() and (real / "suts/s/runs/r1/index.html").exists()


# --- release()가 False일 때와 publish-log 재기록 후 후속 동기화 ---------------------------------------------------
def test_release_returns_false_when_lock_object_is_gone():
    s3 = FakeS3()
    lock = publish.acquire_lock(s3, BUCKET, "", "att-1")
    del s3.objects["locks/publish"]
    assert publish.release(s3, lock) is False


def test_release_false_is_recorded_and_log_resynced_and_reinvalidated(exec_env):
    run_id, run_dir, env, tmp_path = exec_env
    rsync_log = tmp_path / "rsync.calls"
    (tmp_path / "bin" / "rsync").write_text(f'#!/usr/bin/env bash\necho x >> {rsync_log}\nexit 0\n')

    class LockStolen(FakeS3):
        def delete_object(self, Bucket, Key, IfMatch=None):
            if Key.endswith("locks/publish"):
                self.objects.pop(Key, None)
                raise_not_found = publish.ClientError({"Error": {"Code": "PreconditionFailed"}}, "DeleteObject")
                raise raise_not_found
            return super().delete_object(Bucket, Key, IfMatch)

    cf = OkCloudFront()
    s3 = LockStolen()
    result = execute(run_id, run_dir, env, s3, cf)
    assert result["status"] == "passed" and "잠금이 이미" in result["reason"]
    assert cf.paths[-1] == [f"/_test/u/suts/sutx/publish-log/{run_id}.json"] and len(cf.paths) == 3
    assert len(rsync_log.read_text().splitlines()) == 2 + 1 + 1 + 1 - 1  # A, B, 로그 B, 재기록 B
    mirror_log = json.loads((tmp_path / "work/site-mirror/_test/u/suts/sutx/publish-log" / f"{run_id}.json").read_text())
    assert "warning" in mirror_log["hosts"]["s3"]
