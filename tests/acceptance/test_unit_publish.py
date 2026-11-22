"""td.publish 단위 테스트(FakeS3, 외부 접근 없음): manifest, 조건부 업로드, 잠금, 미러, rsync, 상태 규칙(REQ-043/046/070 보조)."""
import hashlib
import json
import os
import stat
import sys
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
    assert set(publish.timings()) == {"uploadSeconds", "rsyncSeconds", "memBeforeMb", "memAfterMb"}


def test_log_payload_has_shared_fields():
    result = publish.build_result("failed", "x", {"s3": host("failed", "x")}, {"uploadSeconds": 1.5, "rsyncSeconds": None, "memBeforeMb": None, "memAfterMb": None}, 123)
    assert result == {"status": "failed", "reason": "x", "hosts": {"s3": {"status": "failed", "reason": "x"}},
                      "timings": {"uploadSeconds": 1.5, "rsyncSeconds": None, "memBeforeMb": None, "memAfterMb": None}, "sizeBytes": 123}


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
    for name, body in (("ssh", 'case "${@: -1}" in *find*) exit 0;; esac\necho 99999999999'), ("rsync", "exit 0")):
        (bin_dir / name).write_text(f"#!/usr/bin/env bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    env = {"TD_WORK_DIR": str(work), "TD_ROOT": str(tmp_path), "TD_SITE_PREFIX": "_test/u/",
           "TD_LIGHTSAIL_IP": "203.0.113.9", "TD_SSH_KEY_PATH": "/key", "PATH": os.environ["PATH"]}
    yield run_id, run_dir, env, tmp_path
    for sig, handler in saved.items():
        _signal.signal(sig, handler)


def execute(run_id, run_dir, env, s3, cf):
    return publish.Publication("sutx", run_id, run_dir, env, s3, cf, measure_hosting=False).execute()


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


def test_mirror_lock_serializes_work_dirs_sharing_a_symlinked_mirror(tmp_path):
    """테스트 run은 TD_WORK_DIR을 따로 쓰고 site-mirror만 심볼릭 링크로 공유한다. 미러 잠금이 TD_WORK_DIR마다 따로 잡히면
    두 게시의 sync_mirror가 같은 키를 같은 `.part` 이름으로 받다가 한쪽 os.replace가 FileNotFoundError로 실패한다."""
    import threading
    shared_work, other_work = tmp_path / "work", tmp_path / "other-work"
    (shared_work / "site-mirror").mkdir(parents=True)
    other_work.mkdir()
    (other_work / "site-mirror").symlink_to(shared_work / "site-mirror")
    entered = threading.Event()

    def second_publication():
        with publish.mirror_lock(other_work):
            entered.set()

    with publish.mirror_lock(shared_work):
        worker = threading.Thread(target=second_publication, daemon=True)
        worker.start()
        assert not entered.wait(0.5), "같은 미러를 쓰는 다른 TD_WORK_DIR의 게시가 미러 잠금 안으로 들어왔다"
    worker.join(timeout=5)
    assert entered.is_set()


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


# --- S13 홈 경로 게이트(Task 12 이월): 업로드되는 run.json과 publish-log에 Path.home()이 없다 ---------------------------
def test_execute_fails_before_upload_when_run_json_contains_home(exec_env):
    run_id, run_dir, env, _ = exec_env
    state.set_run_field(run_dir, "kpis.note", f"built in {Path.home()}/work")
    s3 = FakeS3()
    result = execute(run_id, run_dir, env, s3, OkCloudFront())
    assert result["status"] == "failed" and "홈 경로" in result["reason"] and "run.json" in result["reason"], result
    assert str(Path.home()) not in result["reason"]
    assert not [k for k in s3.objects if "/runs/" in k and not k.endswith("publish-log.json")], "업로드가 일어나면 안 된다"


def test_publish_log_redacts_home_path(exec_env):
    run_id, run_dir, env, _ = exec_env
    s3 = FakeS3()
    key = publish.write_log(s3, BUCKET, run_dir / "mirror", "_test/u/", "sutx", run_id,
                            publish.build_result("failed", f"boom at {Path.home()}/x", {"s3": {"status": "failed"}}, {}, 0))
    text = s3.objects[key]["data"].decode()
    assert str(Path.home()) not in text and "~/x" in text
    assert str(Path.home()) not in (run_dir / "mirror" / key).read_text()


# --- PR 게이트 수정: JSON 안의 인용된 ARN, 자르기 경계의 식별자 ------------------------------------------------
QUOTED_ARN_TEXT = ('An error occurred (AccessDenied): User: arn:aws:iam::999988887777:user/fake-publisher-user is not '
                   'authorized to perform: s3:PutObject on resource: "arn:aws:s3:::fake-bucket/key" because no policy')


class QuotedArnCloudFront:
    def create_invalidation(self, **kwargs):
        raise RuntimeError(QUOTED_ARN_TEXT)


def _assert_clean(text):
    assert "arn:aws:" not in text and "999988887777" not in text and "fake-publisher-user" not in text


def test_write_log_with_quoted_arn_reason_is_valid_json(exec_env):
    run_id, run_dir, env, _ = exec_env
    s3 = FakeS3()
    key = publish.write_log(s3, BUCKET, run_dir / "mirror", "_test/u/", "sutx", run_id,
                            publish.build_result("degraded", QUOTED_ARN_TEXT, {"cloudfront": {"status": "failed", "reason": QUOTED_ARN_TEXT}}, {}, 0),
                            env={**env, "TD_AWS_ACCOUNT_ID": "999988887777", "TD_IAM_USER": "fake-publisher-user"})
    text = s3.objects[key]["data"].decode()
    doc = json.loads(text)
    _assert_clean(text)
    assert "<arn>" in doc["reason"]


def test_run_publish_with_quoted_arn_reason_keeps_valid_json(exec_env, monkeypatch):
    run_id, run_dir, env, _ = exec_env
    env = {**env, "TD_AWS_ACCOUNT_ID": "999988887777", "TD_IAM_USER": "fake-publisher-user"}
    monkeypatch.setattr(publish.Publication, "hosting_phase", lambda self: None)
    s3 = FakeS3()
    code = publish.run_publish("sutx", run_id, run_dir, env, s3, QuotedArnCloudFront())
    assert code == 0
    stage_text = (run_dir / "stages" / "S13.json").read_text()
    stage = json.loads(stage_text)
    assert stage["status"] == "degraded"
    _assert_clean(stage_text)
    log_text = s3.objects[f"_test/u/suts/sutx/publish-log/{run_id}.json"]["data"].decode()
    json.loads(log_text)
    _assert_clean(log_text)


def test_identifier_cut_at_truncation_boundary_is_still_masked(exec_env):
    run_id, run_dir, env, _ = exec_env
    env = {**env, "TD_AWS_ACCOUNT_ID": "999988887777"}

    class BoundaryCloudFront:
        def create_invalidation(self, **kwargs):
            raise RuntimeError("x" * 193 + " 999988887777 tail")  # str(exc)[:200]이 계정 번호를 6자리에서 자른다

    s3 = FakeS3()
    result = execute(run_id, run_dir, env, s3, BoundaryCloudFront())
    log_text = s3.objects[f"_test/u/suts/sutx/publish-log/{run_id}.json"]["data"].decode()
    assert "999988" not in log_text and "999988" not in json.dumps(result)


# =====================================================================================
# Task 11: 인덱스 단계의 수집, 과제 삭제, 인덱스 전용 게시(REQ-079, 098~101, 144, 145 보조)
# =====================================================================================
# --- 삭제 가드(실제 삭제 경로보다 먼저 확인한다) -------------------------------------------------
def test_req100_delete_prefix_guard(tmp_path):
    s3 = FakeS3()
    for key in ("p/projects/a/index.html", "p/projects/a/snapshots/20261122.json", "p/projects/ab/index.html",
                "p/suts/x", "projects/a/index.html"):
        s3.put(key)
    assert publish.delete_prefix(s3, "b", "p/", "p/projects/a/") == 2
    assert s3.keys() == ["p/projects/ab/index.html", "p/suts/x", "projects/a/index.html"]
    assert publish.delete_prefix(s3, "b", "", "projects/a/") == 1          # 운영 루트(빈 접두)도 같은 꼴이다
    for bad in ("p/projects/", "p/suts/x/", "p/", "", "projects/", "p/projects/a/../", "p/projects/a", "p/projects/a/b/",
                "../projects/a/", "p/../projects/a/", "/p/projects/a/", "p//projects/a/", "p/projects/../a/",
                "p/projects/.a/", "p/projects/a b/", "p/projects/-rf/", "p q/projects/a/", "p/projects/a\n/"):
        with pytest.raises(publish.PublishError):
            publish.delete_prefix(s3, "b", "p/", bad)
    assert s3.keys() == ["p/projects/ab/index.html", "p/suts/x"], "거부된 요청은 아무것도 지우지 않는다"


def test_req100_delete_prefix_batches_and_reports_errors_without_names():
    s3 = FakeS3()
    for index in range(2345):
        s3.put(f"p/projects/many/f{index:05d}.json")
    assert publish.delete_prefix(s3, "b", "p/", "p/projects/many/") == 2345
    batches = [call for call in s3.calls if call[0] == "delete_objects"]
    assert [len(call[1].split(",")) for call in batches] == [1000, 1000, 345] and s3.keys() == []

    class PartlyFails(FakeS3):
        def delete_objects(self, Bucket, Delete):
            return {"Errors": [{"Key": Delete["Objects"][0]["Key"], "Code": "AccessDenied", "Message": "denied"}]}

    failing = PartlyFails()
    failing.put("p/projects/hush/latest.json")
    with pytest.raises(publish.PublishError) as raised:
        publish.delete_prefix(failing, "b", "p/", "p/projects/hush/")
    assert "hush" not in str(raised.value) and "AccessDenied" in str(raised.value)


def test_req100_lightsail_remove_command_guard():
    assert publish.lightsail_remove_command("_test/u/", "alpha") == "rm -rf -- '/srv/dashboard/_test/u/projects/alpha'"
    assert publish.lightsail_remove_command("", "spring-petclinic.v2_x") == \
        "rm -rf -- '/srv/dashboard/projects/spring-petclinic.v2_x'"
    for prefix, name in (("_test/u/", ""), ("_test/u/", ".."), ("_test/u/", "../x"), ("_test/u/", "a/b"),
                         ("_test/u/", "a b"), ("_test/u/", "-rf"), ("_test/u/", "a'b"), ("_test/u/", "a;rm"),
                         ("_test/u/", "*"), ("../", "a"), ("_test/../", "a"), ("_test//u/", "a"), ("/_test/u/", "a"),
                         ("_test/u", "a"), ("_test/u x/", "a"), ("_test/u'/", "a"), ("_test/$(id)/", "a"),
                         ("_test/./", "a")):
        with pytest.raises(publish.PublishError):
            publish.lightsail_remove_command(prefix, name)


# --- 무효화 경로 묶기 ------------------------------------------------------------------------
def test_req101_projects_invalidation_wildcard(tmp_path):
    written = [tmp_path / "p" / f"projects/n{i}/{f}" for i in range(20) for f in ("index.html", "series.json", "latest.json")]
    written += [tmp_path / "p/index.html", tmp_path / "p/projects.json"]
    paths = publish.invalidation_paths(tmp_path, written, "p/", "", "", include_log=False)
    assert [x for x in paths if "/projects/" in x] == ["/p/projects/*"]
    assert "/p/projects.json" in paths and "/p/index.html" in paths and "/p/" in paths
    root = publish.invalidation_paths(tmp_path, [tmp_path / "projects/a/index.html"], "", "", "", include_log=False)
    assert root == ["/projects/*"]


def test_overall_status_counts_collect_as_degraded():
    hosts = {"s3": {"status": "passed"}, "cloudfront": {"status": "passed"}, "lightsail": {"status": "passed"},
             "collect": {"status": "failed", "reason": "수집 실행 실패"}}
    assert publish.overall_status(hosts) == ("degraded", "collect: 수집 실행 실패")
    hosts["s3"] = {"status": "failed", "reason": "x"}
    assert publish.overall_status(hosts)[0] == "failed"


# --- 인덱스 단계의 수집(run_collect)과 인덱스 전용 게시(가짜 collect.sh·ssh·rsync, FakeS3) --------------------------
import textwrap

from dashboard_fixtures import cfg_with, write_snapshot
from td import dashboard_config

INDEX_PREFIX = "_test/u/"
INDEX_LOG_KEY = f"{INDEX_PREFIX}publish-log/index.json"
# 기본 가짜 ssh: 과제 목록 조회(find)는 빈 목록, 그 밖(서버 사전 점검의 df·free)은 큰 수
EMPTY_REMOTE_SSH = 'case "${@: -1}" in *find*) exit 0;; esac\necho 99999999999'


def write_fake_collect(root: Path, body: str) -> Path:
    """`<root>/pipeline/collect.sh` 자리에 가짜 수집 스크립트를 둔다(TD_ROOT=root로 게시기가 부른다). 받은 인자는 args.log에."""
    script = root / "pipeline" / "collect.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/usr/bin/env bash\n" f'echo "$@" >> "{root}/collect-args.log"\n' + textwrap.dedent(body))
    script.chmod(0o755)
    return script


def write_dashboard_cfg(root: Path, data: dict) -> Path:
    import yaml
    path = root / "dashboard.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    (root / "suts").mkdir(exist_ok=True)
    return path


def index_env(tmp_path: Path, monkeypatch, *, ssh_body: str = EMPTY_REMOTE_SSH, rsync_body: str = "exit 0", **extra) -> dict:
    """인덱스 전용 게시를 가짜 실행 파일로 돌리는 환경. ssh의 인자는 ssh.log에 줄마다(마지막 인자 = 원격 명령).
    게시기는 ssh·rsync를 프로세스 PATH에서 찾으므로 monkeypatch로 PATH 앞에 가짜를 둔다(실제 서버에 닿지 않게)."""
    work = tmp_path / "work"
    (work / "infra").mkdir(parents=True, exist_ok=True)
    (work / "infra" / "terraform.tfstate").write_text(json.dumps(
        {"outputs": {"bucket": {"value": BUCKET}, "distribution_id": {"value": "DIST"}}}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ssh_log = tmp_path / "ssh.log"
    (bin_dir / "ssh").write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "${{@: -1}}" >> "{ssh_log}"\n{ssh_body}\n')
    (bin_dir / "rsync").write_text(f"#!/usr/bin/env bash\n{rsync_body}\n")
    for name in ("ssh", "rsync"):
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return {"TD_WORK_DIR": str(work), "TD_ROOT": str(tmp_path), "TD_SITE_PREFIX": INDEX_PREFIX,
            "TD_LIGHTSAIL_IP": "203.0.113.9", "TD_SSH_KEY_PATH": "/key",
            "PATH": f"{bin_dir}:{os.environ['PATH']}", **extra}


@pytest.fixture
def restore_signals():
    saved = {sig: _signal.getsignal(sig) for sig in (_signal.SIGINT, _signal.SIGTERM, _signal.SIGALRM)}
    yield
    _signal.setitimer(_signal.ITIMER_REAL, 0)
    for sig, handler in saved.items():
        _signal.signal(sig, handler)


_FAKE_REMOTE_SSH = r'''
import json, re, sys
from pathlib import Path
STATE = Path(__file__).resolve().parent.parent
command = sys.argv[-1]
with open(STATE / "ssh.log", "a") as log:
    log.write(command.replace("\n", " ") + "\n")
state = json.loads((STATE / "remote.json").read_text())
if state.get("unreachable"):
    print("ssh: connect to host port 22: Operation timed out", file=sys.stderr)
    sys.exit(255)
removal = re.fullmatch(r"rm -rf -- '/srv/dashboard/(.*)projects/([^']*)'", command)
if removal:
    name = removal.group(2)
    if name in state.get("fail_rm", []):
        print(f"rm: cannot remove '/srv/dashboard/{removal.group(1)}projects/{name}': Permission denied", file=sys.stderr)
        sys.exit(1)
    state["names"] = [item for item in state["names"] if item != name]
    (STATE / "remote.json").write_text(json.dumps(state))
    sys.exit(0)
if "find " in command:
    if state.get("fail_list"):
        print("find: Permission denied", file=sys.stderr)
        sys.exit(1)
    directory = re.search(r"d='([^']*)'", command).group(1)
    if state.get("exists", True):
        sys.stdout.write("".join(f"{directory}/{name}\0" for name in state["names"]))
    sys.exit(0)
print(99999999999)
'''


class FakeRemote:
    """Lightsail 쪽 `/srv/dashboard/<접두>projects/` 아래 디렉터리 이름을 상태 파일로 흉내 내는 가짜 ssh."""

    def __init__(self, tmp_path: Path):
        self.state_file = tmp_path / "remote.json"
        self.log_file = tmp_path / "ssh.log"

    def set(self, **fields) -> None:
        state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        state.update(fields)
        self.state_file.write_text(json.dumps(state))

    @property
    def names(self) -> list[str]:
        return json.loads(self.state_file.read_text())["names"]

    def commands(self) -> list[str]:
        return self.log_file.read_text().splitlines() if self.log_file.exists() else []

    def removals(self) -> list[str]:
        return [command for command in self.commands() if command.startswith("rm ")]

    def listings(self) -> list[str]:
        return [command for command in self.commands() if "find " in command]

    def clear_log(self) -> None:
        self.log_file.unlink(missing_ok=True)


def fake_remote(tmp_path: Path, monkeypatch, names=(), **fields) -> FakeRemote:
    """index_env의 bin/ssh를 상태를 가진 가짜로 바꾼다(index_env를 먼저 부른다)."""
    script = tmp_path / "bin" / "ssh"
    script.write_text(f"#!{sys.executable}\n{_FAKE_REMOTE_SSH}")
    script.chmod(0o755)
    remote = FakeRemote(tmp_path)
    remote.set(**{"names": list(names), "fail_rm": [], "exists": True, "fail_list": False, "unreachable": False, **fields})
    return remote


def run_fake_index_publication(tmp_path: Path, monkeypatch, *, deleted=(), remote_names=None, s3=None, cf=None,
                               remote_fields: dict | None = None, **extra) -> dict:
    """미러에 `deleted`의 과제 디렉터리가 있는(설정에는 없는) 접두로 IndexPublication을 돌린다.
    Lightsail 쪽은 FakeRemote(이름은 remote_names, 기본은 deleted와 같다)."""
    s3 = s3 if s3 is not None else FakeS3()
    for name in deleted:
        s3.put(f"{INDEX_PREFIX}projects/{name}/latest.json", b"{}")
        s3.put(f"{INDEX_PREFIX}projects/{name}/index.html", b"<html></html>")
    env = index_env(tmp_path, monkeypatch, **extra)
    fake_remote(tmp_path, monkeypatch, list(deleted) if remote_names is None else remote_names, **(remote_fields or {}))
    return publish.IndexPublication(env, s3, cf or OkCloudFront()).execute()


def test_req100_delete_prefix_guard_and_lightsail_degraded(tmp_path, monkeypatch, restore_signals):
    s3 = FakeS3()
    s3.put(f"{INDEX_PREFIX}projects/ab/latest.json")    # 이름이 접두로 겹치는 다른 과제
    s3.put(f"{INDEX_PREFIX}suts/x/runs.json")
    result = run_fake_index_publication(tmp_path, monkeypatch, deleted=["a"], remote_names=["a", "ab"], s3=s3,
                                        remote_fields={"fail_rm": ["a", "ab"]})
    assert result["status"] == "degraded" and result["hosts"]["s3"]["status"] == "passed", result
    assert result["hosts"]["lightsail"]["status"] == "failed"
    assert not [key for key in s3.keys() if key.startswith(f"{INDEX_PREFIX}projects/a/")]
    assert f"{INDEX_PREFIX}suts/x/runs.json" in s3.keys()
    assert not (tmp_path / "work/site-mirror" / INDEX_PREFIX / "projects/a").exists()
    remote = FakeRemote(tmp_path).removals()
    assert "rm -rf -- '/srv/dashboard/_test/u/projects/a'" in remote and "rm -rf -- '/srv/dashboard/_test/u/projects/ab'" in remote
    log_text = s3.objects[INDEX_LOG_KEY]["data"].decode()
    log = json.loads(log_text)
    assert log["status"] == "degraded" and log["hosts"]["lightsail"]["status"] == "failed"
    assert "projects/a" not in log_text and "cannot remove" not in log_text, "삭제한 과제 이름과 원격 오류 문구를 쓰지 않는다"
    assert f"{INDEX_PREFIX}locks/publish" not in s3.objects


def test_index_publication_passes_invalidates_and_logs(tmp_path, monkeypatch, restore_signals):
    s3, cf = FakeS3(), OkCloudFront()
    s3.put(f"{INDEX_PREFIX}projects/gone/latest.json")
    calls: list = []

    class RecordingCloudFront(OkCloudFront):
        def create_invalidation(self, DistributionId, InvalidationBatch):
            calls.append(InvalidationBatch["CallerReference"])
            return super().create_invalidation(DistributionId, InvalidationBatch)

    cf = RecordingCloudFront()
    result = run_fake_index_publication(tmp_path, monkeypatch, s3=s3, cf=cf)
    assert result["status"] == "passed", result
    assert set(result["hosts"]) == {"s3", "cloudfront", "lightsail"}
    assert f"/{INDEX_PREFIX}projects/*" in cf.paths[0] and f"/{INDEX_PREFIX}index.html" in cf.paths[0]
    assert cf.paths[-1] == [f"/{INDEX_LOG_KEY}"]
    assert all(reference.startswith("index-") for reference in calls)
    log = json.loads(s3.objects[INDEX_LOG_KEY]["data"])
    assert {"status", "reason", "hosts", "timings"} <= set(log) and log["status"] == "passed"
    assert s3.objects[INDEX_LOG_KEY]["CacheControl"] == publish.CACHE_NO_CACHE
    assert (tmp_path / "work/site-mirror" / INDEX_LOG_KEY).exists()
    assert s3.objects[f"{INDEX_PREFIX}index.html"]["CacheControl"] == publish.CACHE_NO_CACHE
    assert not [key for key in s3.keys() if "/runs/" in key], "인덱스 전용 게시는 run을 만들지 않는다"
    assert f"{INDEX_PREFIX}locks/publish" not in s3.objects


def test_run_index_only_lock_held_fails_without_touching_lock(tmp_path, monkeypatch, restore_signals, capsys):
    s3 = FakeS3()
    other = publish.acquire_lock(s3, BUCKET, INDEX_PREFIX, "att-other")
    code = publish.run_index_only(index_env(tmp_path, monkeypatch), s3, OkCloudFront())
    assert code == 1
    assert "--force-unlock att-other" in capsys.readouterr().err
    assert s3.objects[other.key]["etag"] == other.etag and INDEX_LOG_KEY not in s3.objects


def test_run_index_only_exit_codes(tmp_path, monkeypatch, restore_signals, capsys):
    assert publish.run_index_only(index_env(tmp_path / "ok", monkeypatch), FakeS3(), OkCloudFront()) == 0
    assert "index-only passed" in capsys.readouterr().err
    assert publish.run_index_only(index_env(tmp_path / "cf", monkeypatch), FakeS3(), FailingCloudFront()) == 0   # degraded

    class S3Down(FakeS3):
        def put_object(self, Bucket, Key, Body=b"", IfNoneMatch=None, **kwargs):
            if not Key.endswith("locks/publish"):
                raise RuntimeError("s3 down")
            return super().put_object(Bucket, Key, Body, IfNoneMatch, **kwargs)

    s3 = S3Down()
    assert publish.run_index_only(index_env(tmp_path / "s3", monkeypatch), s3, OkCloudFront()) == 1
    assert f"{INDEX_PREFIX}locks/publish" not in s3.objects


def test_index_log_key():
    assert publish.index_log_key("") == "publish-log/index.json"
    assert publish.index_log_key(INDEX_PREFIX) == INDEX_LOG_KEY


# --- run_collect ----------------------------------------------------------------------------
def _collect_cfg(tmp_path: Path, data: dict):
    path = write_dashboard_cfg(tmp_path, data)
    return dashboard_config.load(path, tmp_path / "suts")


def test_run_collect_skips_without_repo_projects(tmp_path):
    write_fake_collect(tmp_path, "echo '{}'\n")
    env = {"TD_ROOT": str(tmp_path), "PATH": os.environ["PATH"]}
    empty = {"status": "ok", "reasons": [], "written": [], "excluded": [], "unverified": []}
    assert publish.run_collect(env, dashboard_config.empty(), tmp_path / "site") == empty
    assert publish.run_collect(env, _collect_cfg(tmp_path, cfg_with(pipeline=[])), tmp_path / "site") == empty
    assert not (tmp_path / "collect-args.log").exists(), "repo가 있는 과제가 없으면 수집을 띄우지 않는다"


@pytest.mark.parametrize("body", ["exit 1\n", "echo 'not json'\nexit 0\n", "echo '[1, 2]'\n", "echo '{\"status\": \"weird\"}'\n"])
def test_run_collect_failures_are_degraded(tmp_path, body):
    write_fake_collect(tmp_path, body)
    cfg = _collect_cfg(tmp_path, cfg_with(plain="alpha"))
    out = publish.run_collect({"TD_ROOT": str(tmp_path), "PATH": os.environ["PATH"]}, cfg, tmp_path / "site")
    assert out == {"status": "degraded", "reasons": ["수집 실행 실패"], "written": [], "excluded": [], "unverified": []}


def test_run_collect_passes_config_site_and_suts_and_returns_result(tmp_path):
    result = {"status": "degraded", "reasons": ["비공개 과제 1개 제외"], "written": ["projects/alpha/latest.json"],
              "excluded": ["hush"], "unverified": []}
    write_fake_collect(tmp_path, f"echo 'names go to stderr: hush' >&2\necho '{json.dumps(result)}'\n")
    cfg = _collect_cfg(tmp_path, cfg_with(plain=["alpha", "hush"]))
    out = publish.run_collect({"TD_ROOT": str(tmp_path), "PATH": os.environ["PATH"]}, cfg, tmp_path / "site")
    assert out == result
    args = (tmp_path / "collect-args.log").read_text().split()
    assert args == ["--config", str(tmp_path / "dashboard.yaml"), "--site", str(tmp_path / "site"),
                    "--suts-dir", str(tmp_path / "suts")]


def test_run_collect_interrupt_terminates_child_and_reraises(tmp_path, restore_signals):
    marker = tmp_path / "child-got-term"
    pid_file = tmp_path / "child.pid"
    write_fake_collect(tmp_path, f"""\
        echo $$ > "{pid_file}"
        trap 'kill "$sleeper" 2>/dev/null; echo term > "{marker}"; exit 143' TERM
        sleep 30 & sleeper=$!
        echo "$sleeper" > "{pid_file}.sleep"
        wait
        """)
    cfg = _collect_cfg(tmp_path, cfg_with(plain="alpha"))
    _signal.signal(_signal.SIGALRM, publish._raise_interrupted)
    _signal.setitimer(_signal.ITIMER_REAL, 1.5)
    started = time.monotonic()
    with pytest.raises(publish.PublishInterrupted):
        publish.run_collect({"TD_ROOT": str(tmp_path), "PATH": os.environ["PATH"]}, cfg, tmp_path / "site")
    assert time.monotonic() - started < 20 and marker.read_text().strip() == "term"
    for leftover in (pid_file, Path(f"{pid_file}.sleep")):     # collect.sh도 그 sleep 자식도 남지 않는다
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(int(leftover.read_text()), 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        with pytest.raises(ProcessLookupError):
            os.kill(int(leftover.read_text()), 0)


# --- publish_index: 수집 파일도 업로드 게이트를 지난다(규칙 1), 수집 결과가 게시 상태에 준다 -------------------------
def test_publish_index_gate_stops_leaked_path_in_collected_description(tmp_path, monkeypatch, restore_signals):
    staged = tmp_path / "staged"
    write_snapshot(staged, "alpha", "20261122", description=f"built in {Path.home()}/secret-checkout")
    leaked = staged / "projects/alpha/snapshots/20261122.json"
    (staged / "projects/alpha/latest.json").write_text(leaked.read_text())
    written = ["projects/alpha/snapshots/20261122.json", "projects/alpha/latest.json"]
    write_fake_collect(tmp_path, f"""\
        while (($#)); do [[ "$1" == --site ]] && site="$2"; shift; done
        cp -R "{staged}/projects" "$site/"
        echo '{json.dumps({"status": "ok", "reasons": [], "written": written, "excluded": [], "unverified": []})}'
        """)
    cfg_path = write_dashboard_cfg(tmp_path, cfg_with(plain="alpha"))
    env = index_env(tmp_path, monkeypatch, TD_DASHBOARD_CONFIG=str(cfg_path))
    s3 = FakeS3()
    with pytest.raises(publish.PublishError, match="게이트"):
        publish.publish_index(s3, BUCKET, tmp_path / "work/site-mirror", INDEX_PREFIX, env)
    assert not [key for key in s3.keys() if "projects" in key], "게이트에 걸리면 아무것도 올리지 않는다"


def test_publication_degraded_collect_is_recorded(exec_env):
    run_id, run_dir, env, tmp_path = exec_env
    write_fake_collect(tmp_path, "exit 1\n")
    env = {**env, "TD_DASHBOARD_CONFIG": str(write_dashboard_cfg(tmp_path, cfg_with(plain="alpha")))}
    s3 = FakeS3()
    result = execute(run_id, run_dir, env, s3, OkCloudFront())
    assert result["status"] == "degraded" and result["hosts"]["collect"] == {"status": "failed", "reason": "수집 실행 실패"}
    log = json.loads(s3.objects[f"_test/u/suts/sutx/publish-log/{run_id}.json"]["data"])
    assert "수집 실행 실패" in log["reason"] and log["status"] == "degraded"


def test_publish_index_deletes_excluded_and_unconfigured_but_keeps_implicit(tmp_path, monkeypatch, restore_signals):
    s3 = FakeS3()
    for key, body in ((f"{INDEX_PREFIX}suts/s1/runs/r1/_COMPLETE", b"{}"),
                      (f"{INDEX_PREFIX}suts/s1/runs/r1/run.json", json.dumps({"runId": "r1", "sut": "s1"}).encode()),
                      (f"{INDEX_PREFIX}projects/s1/series.json", b"{}"),       # 암묵 과제: 지우지 않는다
                      (f"{INDEX_PREFIX}projects/alpha/latest.json", b"{}"),     # 설정의 과제: 지우지 않는다
                      (f"{INDEX_PREFIX}projects/hush/latest.json", b"{}"),      # 수집이 제외: 지운다
                      (f"{INDEX_PREFIX}projects/old/latest.json", b"{}"),       # 설정에서 빠짐: 지운다
                      (f"{INDEX_PREFIX}projects/_collect.json", b"{}")):
        s3.put(key, body)
    result = {"status": "degraded", "reasons": ["비공개 과제 1개 제외"], "written": [], "excluded": ["hush"], "unverified": []}
    write_fake_collect(tmp_path, f"echo '{json.dumps(result)}'\n")
    env = index_env(tmp_path, monkeypatch, TD_DASHBOARD_CONFIG=str(write_dashboard_cfg(tmp_path, cfg_with(plain=["alpha", "hush"]))))
    mirror = tmp_path / "work/site-mirror"
    outcome = publish.publish_index(s3, BUCKET, mirror, INDEX_PREFIX, env)
    assert outcome.deleted == ["hush", "old"] and outcome.collect_status == "degraded"
    assert outcome.collect_reasons == ["비공개 과제 1개 제외"]
    keys = s3.keys()
    assert not [k for k in keys if "/projects/hush/" in k or "/projects/old/" in k]
    assert f"{INDEX_PREFIX}projects/alpha/latest.json" in keys and f"{INDEX_PREFIX}projects/s1/index.html" in keys
    assert not (mirror / INDEX_PREFIX / "projects/old").exists() and (mirror / INDEX_PREFIX / "projects/alpha").exists()
    for name in ("hush", "old"):
        assert name not in s3.objects[f"{INDEX_PREFIX}projects.json"]["data"].decode()


# --- 수정 1차: Lightsail 과제 정리는 매 게시 원격 목록에서 정한다 -----------------------------------------
OK_COLLECT = json.dumps({"status": "ok", "reasons": [], "written": [], "excluded": [], "unverified": []})


def test_req100_lightsail_list_command_guard():
    assert publish.lightsail_list_command("_test/u/") == (
        "d='/srv/dashboard/_test/u/projects'; if [ -d \"$d\" ]; then find \"$d\" -mindepth 1 -maxdepth 1 -type d -print0; fi")
    assert publish.lightsail_list_command("").startswith("d='/srv/dashboard/projects';")
    for bad in ("../", "_test/../", "_test//u/", "/_test/u/", "_test/u", "_test/u x/", "_test/u'/", "_test/$(id)/"):
        with pytest.raises(publish.PublishError):
            publish.lightsail_list_command(bad)


def _alpha_env(tmp_path: Path, monkeypatch, collect_output: str = OK_COLLECT) -> dict:
    write_fake_collect(tmp_path, f"echo '{collect_output}'\n")
    return index_env(tmp_path, monkeypatch, TD_DASHBOARD_CONFIG=str(write_dashboard_cfg(tmp_path, cfg_with(plain="alpha"))))


def _publish(env: dict, s3: FakeS3) -> dict:
    return publish.IndexPublication(env, s3, OkCloudFront()).execute()


def test_req100_remote_prune_retries_failed_removal_on_next_publish(tmp_path, monkeypatch, restore_signals):
    env, s3 = _alpha_env(tmp_path, monkeypatch), FakeS3()
    remote = fake_remote(tmp_path, monkeypatch, ["alpha", "old"], fail_rm=["old"])
    first = _publish(env, s3)
    assert first["status"] == "degraded" and first["hosts"]["lightsail"]["status"] == "failed", first
    assert remote.removals() == ["rm -rf -- '/srv/dashboard/_test/u/projects/old'"], "keep 집합의 alpha는 지우지 않는다"
    assert "old" not in s3.objects[INDEX_LOG_KEY]["data"].decode()
    remote.set(fail_rm=[])
    remote.clear_log()
    second = _publish(env, s3)                                   # 같은 설정, 다음 게시가 따라잡는다
    assert second["status"] == "passed", second
    assert remote.removals() == ["rm -rf -- '/srv/dashboard/_test/u/projects/old'"] and remote.names == ["alpha"]


def test_req100_remote_prune_keeps_excluded_out_of_keep_set(tmp_path, monkeypatch, restore_signals):
    excluded = json.dumps({"status": "degraded", "reasons": ["비공개 과제 1개 제외"], "written": [], "excluded": ["alpha"],
                           "unverified": []})
    env = _alpha_env(tmp_path, monkeypatch, excluded)
    remote = fake_remote(tmp_path, monkeypatch, ["alpha"])
    result = _publish(env, FakeS3())
    assert remote.removals() == ["rm -rf -- '/srv/dashboard/_test/u/projects/alpha'"] and remote.names == []
    assert result["status"] == "degraded" and result["hosts"]["lightsail"]["status"] == "passed"


def test_req100_remote_prune_never_passes_unsafe_names_to_rm(tmp_path, monkeypatch, restore_signals):
    env, s3 = _alpha_env(tmp_path, monkeypatch), FakeS3()
    remote = fake_remote(tmp_path, monkeypatch, ["..", "a b", "-rf", ".hidden", "alpha", "old"])
    result = _publish(env, s3)
    assert remote.removals() == ["rm -rf -- '/srv/dashboard/_test/u/projects/old'"]
    assert result["status"] == "passed" and "4개" in result["hosts"]["lightsail"]["warning"], result
    log_text = s3.objects[INDEX_LOG_KEY]["data"].decode()
    assert all(name not in log_text for name in ("a b", "-rf", ".hidden", "projects/old"))


def test_req100_preflight_error_skips_prune_and_next_publish_catches_up(tmp_path, monkeypatch, restore_signals):
    env, s3 = _alpha_env(tmp_path, monkeypatch), FakeS3()
    remote = fake_remote(tmp_path, monkeypatch, ["alpha", "old"], unreachable=True)
    first = _publish(env, s3)
    assert first["status"] == "degraded" and first["hosts"]["lightsail"]["status"] == "failed"
    assert remote.listings() == [] and remote.removals() == []
    remote.set(unreachable=False)
    second = _publish(env, s3)
    assert second["status"] == "passed" and remote.names == ["alpha"]
    assert remote.removals() == ["rm -rf -- '/srv/dashboard/_test/u/projects/old'"]


def test_req100_missing_remote_projects_dir_is_not_an_error(tmp_path, monkeypatch, restore_signals):
    env = _alpha_env(tmp_path, monkeypatch)
    remote = fake_remote(tmp_path, monkeypatch, [], exists=False)
    result = _publish(env, FakeS3())
    assert result["status"] == "passed" and len(remote.listings()) == 1 and remote.removals() == []


def test_req100_failed_listing_is_degraded_without_removals(tmp_path, monkeypatch, restore_signals):
    env = _alpha_env(tmp_path, monkeypatch)
    remote = fake_remote(tmp_path, monkeypatch, ["old"], fail_list=True)
    result = _publish(env, FakeS3())
    assert result["status"] == "degraded" and result["hosts"]["lightsail"]["status"] == "failed"
    assert remote.removals() == [] and remote.names == ["old"]


def test_req100_no_prune_when_keep_set_cannot_be_computed(tmp_path, monkeypatch, restore_signals):
    env = index_env(tmp_path, monkeypatch, TD_DASHBOARD_CONFIG=str(tmp_path / "missing.yaml"))   # 설정 오류
    remote = fake_remote(tmp_path, monkeypatch, ["old"])
    result = _publish(env, FakeS3())
    assert result["status"] == "failed"
    assert remote.listings() == [] and remote.removals() == [] and remote.names == ["old"]


def test_s13_publication_prunes_from_remote_listing_too(exec_env):
    run_id, run_dir, env, tmp_path = exec_env
    remote = fake_remote(tmp_path, None, ["old"])          # exec_env의 bin/ssh를 바꾼다(PATH는 이미 앞에 있다)
    result = execute(run_id, run_dir, env, FakeS3(), OkCloudFront())
    assert result["status"] == "passed", result
    assert remote.removals() == ["rm -rf -- '/srv/dashboard/_test/u/projects/old'"]


def test_write_index_log_refuses_local_absolute_path(tmp_path):
    s3 = FakeS3()
    result = publish.build_result("degraded", "failed at /Users/someone/checkout/x.txt", {"s3": {"status": "passed"}}, {}, 0)
    with pytest.raises(publish.PublishError, match="게이트"):
        publish.write_index_log(s3, BUCKET, tmp_path / "mirror", INDEX_PREFIX, result)
    assert [call for call in s3.calls if call[0] == "put"] == [] and not (tmp_path / "mirror").exists()


# --- 최종 리뷰 수정: 접두 "/"는 운영 루트다(빈 테스트 설정으로 정리하지 않는다), 설정 오류 문구는 기록에 남기지 않는다 ----
def _seed_root_projects(s3: FakeS3) -> list[str]:
    keys = [f"projects/{name}/{file}" for name in ("alpha", "beta")
            for file in ("latest.json", "snapshots/20261122.json", "index.html")]
    for key in keys:
        s3.put(key, b"{}")
    return keys


@pytest.mark.parametrize("slash_prefix", ["/", "//"])
def test_slash_prefix_without_root_config_fails_without_deleting(tmp_path, monkeypatch, restore_signals, slash_prefix):
    """접두 "/"는 정규화하면 운영 루트("")다. 설정 선택도 같은 접두로 정해 저장소 루트 설정을 읽고, 없으면 실패한다."""
    s3 = FakeS3()
    seeded = _seed_root_projects(s3)
    write_fake_collect(tmp_path, f"echo '{OK_COLLECT}'\n")
    env = index_env(tmp_path, monkeypatch, TD_SITE_PREFIX=slash_prefix)     # TD_ROOT(tmp_path)에 dashboard.yaml 없음
    remote = fake_remote(tmp_path, monkeypatch, ["alpha", "beta"])
    result = _publish(env, s3)
    assert result["status"] == "failed", result
    assert [call for call in s3.calls if call[0] == "delete_objects"] == [], "운영 과제 디렉터리를 지우지 않는다"
    assert all(key in s3.keys() for key in seeded)
    assert remote.removals() == [] and remote.names == ["alpha", "beta"]
    assert "locks/publish" not in s3.objects


def test_slash_prefix_reads_repo_root_config_and_keeps_its_projects(tmp_path, monkeypatch, restore_signals):
    s3 = FakeS3()
    seeded = _seed_root_projects(s3)
    write_fake_collect(tmp_path, f"echo '{OK_COLLECT}'\n")
    write_dashboard_cfg(tmp_path, cfg_with(plain=["alpha", "beta"]))       # 저장소 루트(TD_ROOT)의 설정
    env = index_env(tmp_path, monkeypatch, TD_SITE_PREFIX="/")
    remote = fake_remote(tmp_path, monkeypatch, ["alpha", "beta"])
    result = _publish(env, s3)
    assert result["status"] == "passed", result
    assert [call for call in s3.calls if call[0] == "delete_objects"] == []
    assert all(key in s3.keys() for key in seeded) and remote.removals() == []
    assert "publish-log/index.json" in s3.objects and "projects.json" in s3.objects, "운영 루트에 게시했다"


def test_publish_index_refuses_root_prefix_without_config_file(tmp_path, monkeypatch, restore_signals):
    """경로 없는(빈 테스트) 설정으로 운영 루트를 정리하려 하면 어떤 삭제보다 먼저 PublishError."""
    s3 = FakeS3()
    seeded = _seed_root_projects(s3)
    write_fake_collect(tmp_path, f"echo '{OK_COLLECT}'\n")
    env = index_env(tmp_path, monkeypatch)
    monkeypatch.setattr(dashboard_config, "resolve", lambda *args, **kwargs: dashboard_config.empty())
    mirror = tmp_path / "work/site-mirror"
    seeded_calls = len(s3.calls)
    with pytest.raises(publish.PublishError):
        publish.publish_index(s3, BUCKET, mirror, "", env)
    assert [call for call in s3.calls[seeded_calls:] if call[0] in ("delete_objects", "put")] == []
    assert all(key in s3.keys() for key in seeded) and (mirror / "projects/alpha/latest.json").exists()


def test_delete_prefix_requires_the_site_prefix():
    s3 = FakeS3()
    for key in ("p/suts/x/projects/a/f.json", "p/projects/a/f.json", "projects/a/f.json"):
        s3.put(key)
    for site_prefix, key_prefix in (("p/", "p/suts/x/projects/a/"), ("p/", "projects/a/"), ("", "p/projects/a/"),
                                    ("q/", "p/projects/a/")):
        with pytest.raises(publish.PublishError):
            publish.delete_prefix(s3, "b", site_prefix, key_prefix)
    assert len(s3.keys()) == 3, "접두가 맞지 않는 요청은 아무것도 지우지 않는다"
    assert publish.delete_prefix(s3, "b", "p/", "p/projects/a/") == 1
    assert publish.delete_prefix(s3, "b", "", "projects/a/") == 1
    assert s3.keys() == ["p/suts/x/projects/a/f.json"]


SECRET_REPO = "hush-owner/hush-secret-repo"


def _duplicate_repo_cfg(tmp_path: Path) -> Path:
    data = cfg_with(plain=["alpha", "beta"])
    for project in data["projects"]:
        project["repo"] = SECRET_REPO                                     # 같은 repo 두 번 → ConfigError(repo 문구 포함)
    return write_dashboard_cfg(tmp_path, data)


def test_config_error_text_stays_out_of_index_publish_log(tmp_path, monkeypatch, restore_signals, capsys):
    write_fake_collect(tmp_path, f"echo '{OK_COLLECT}'\n")
    env = index_env(tmp_path, monkeypatch, TD_DASHBOARD_CONFIG=str(_duplicate_repo_cfg(tmp_path)))
    fake_remote(tmp_path, monkeypatch, [])
    s3 = FakeS3()
    result = _publish(env, s3)
    assert result["status"] == "failed" and result["reason"] == publish.CONFIG_ERROR_REASON, result
    log_text = s3.objects[INDEX_LOG_KEY]["data"].decode()
    assert "hush" not in log_text and "hush" not in json.dumps(result)
    assert publish.CONFIG_ERROR_REASON in log_text
    assert SECRET_REPO in capsys.readouterr().err, "전체 문구는 표준 오류에만 낸다"


def test_config_error_text_stays_out_of_s13_publish_log(exec_env, capsys):
    run_id, run_dir, env, tmp_path = exec_env
    write_fake_collect(tmp_path, f"echo '{OK_COLLECT}'\n")
    env = {**env, "TD_DASHBOARD_CONFIG": str(_duplicate_repo_cfg(tmp_path))}
    s3 = FakeS3()
    code = publish.run_publish("sutx", run_id, run_dir, env, s3, OkCloudFront())
    assert code == 1
    log_text = s3.objects[f"_test/u/suts/sutx/publish-log/{run_id}.json"]["data"].decode()
    stage_text = (run_dir / "stages" / "S13.json").read_text()
    for text in (log_text, stage_text):
        assert "hush" not in text and publish.CONFIG_ERROR_REASON in text
    assert SECRET_REPO in capsys.readouterr().err


def test_run_collect_kill_path_reaps_the_whole_child_group(tmp_path, monkeypatch, restore_signals):
    """collect.sh가 SIGTERM을 무시하면 기다린 뒤 SIGKILL을 그 자식의 프로세스 그룹 전체에 보낸다(손자 td.collect도 남지 않는다)."""
    pid_file = tmp_path / "child.pid"
    write_fake_collect(tmp_path, f"""\
        trap '' TERM
        echo $$ > "{pid_file}"
        sleep 30 & echo $! > "{pid_file}.grandchild"
        wait
        """)
    cfg = _collect_cfg(tmp_path, cfg_with(plain="alpha"))
    monkeypatch.setattr(publish, "COLLECT_STOP_WAIT", 1)
    _signal.signal(_signal.SIGALRM, publish._raise_interrupted)
    _signal.setitimer(_signal.ITIMER_REAL, 1.5)
    pids: list[int] = []
    try:
        with pytest.raises(publish.PublishInterrupted):
            publish.run_collect({"TD_ROOT": str(tmp_path), "PATH": os.environ["PATH"]}, cfg, tmp_path / "site")
        pids = [int(pid_file.read_text()), int(Path(f"{pid_file}.grandchild").read_text())]
        for pid in pids:
            deadline = time.monotonic() + 5
            while _alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            assert not _alive(pid), f"pid {pid}가 남았다"
    finally:
        for pid in pids:
            if _alive(pid):
                os.kill(pid, _signal.SIGKILL)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
