"""REQ-043/044/046/070/071 + SIGINT/SIGKILL 잠금(Review Focus 5): 실제 S3(`_test/<sessionId>/`), CloudFront, Lightsail 게시 (E2E-inj).

테스트가 만든 게시물은 지우지 않는다(과정 확인용 보존, 설계 §13.2). 잠금과 run 디렉터리는 SUT 이름으로 격리한다.
"""
import json
import os
import re
import signal
import time

import pytest
from botocore.exceptions import ClientError

from td import publish
import helpers


def get_bytes(s3, bucket, key):
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def exists(s3, bucket, key) -> bool:
    return get_bytes(s3, bucket, key) is not None


def list_keys(s3, bucket, prefix) -> dict[str, str]:
    result = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            result[obj["Key"]] = obj["ETag"]
    return result


def run_ids_in(s3, bucket, prefix, sut) -> list[str]:
    raw = get_bytes(s3, bucket, f"{prefix}suts/{sut}/runs.json")
    return [r["runId"] for r in json.loads(raw)] if raw else []


# --- 재설계 사이트(요구사항명세 2026-11-22 §3)에서 SUT의 과제와 과제 페이지 구역을 찾는 도우미 ---
def linked_project(projects_doc: dict, sut: str) -> dict:
    """`projects.json`(또는 홈의 `#projects-data`)에서 그 SUT와 이어진 과제 항목을 찾는다. 없으면 실패한다."""
    linked = [entry for entry in projects_doc["projects"] if entry.get("sut") == sut]
    assert len(linked) == 1, f"SUT {sut}와 이어진 과제가 하나가 아니다: {[entry['name'] for entry in linked]}"
    return linked[0]


def projects_island(home_html: str) -> dict:
    """홈 HTML의 페이지 안 JSON 블록(`<script type="application/json" id="projects-data">`)을 읽는다."""
    found = re.search(r'<script type="application/json" id="projects-data">(.*?)</script>', home_html, re.S)
    assert found, "홈에 #projects-data 블록이 없다"
    return json.loads(found.group(1))


def runs_table(project_html: str) -> str:
    """과제 페이지 HTML에서 실행 이력 탭(`#panel-runs`)의 `table#runs`를 잘라낸다."""
    panel = project_html.index('id="panel-runs"')
    start = project_html.index('<table id="runs">', panel)
    return project_html[start:project_html.index("</table>", start)]


def trend_panel(project_html: str) -> str:
    """과제 페이지 HTML에서 추이 탭(`#panel-trend`) 구역을 잘라낸다."""
    start = project_html.index('id="panel-trend"')
    return project_html[start:project_html.index("</section>", start)]


@pytest.fixture
def unlock_after(s3_client, bucket, site_prefix):
    """어떤 경로로 끝나도 이 테스트가 남긴 접두 잠금을 풀어 다음 테스트가 막히지 않게 한다."""
    yield
    held = publish.read_lock(s3_client, bucket, site_prefix)
    if held:
        publish.force_unlock(s3_client, bucket, site_prefix, held[0]["attemptId"])


def test_req043_atomic_publish(publisher, s3_client, bucket, site_prefix, unlock_after):
    sut = "td-t043"
    lock_key = publish.lock_key(site_prefix)
    for point in ("upload-first", "upload-mid", "complete", "index"):
        run_id, run_dir = publisher.new_run(sut)
        key_prefix = f"{site_prefix}suts/{sut}/runs/{run_id}/"
        failed = publisher.s13(run_dir, TD_FAIL_STAGE=f"S13:{point}")
        assert failed.returncode == 1, failed.stderr[-800:]
        stage = publisher.stage13(run_dir)
        assert stage["status"] == "failed" and point in stage["reason"], stage
        assert not exists(s3_client, bucket, lock_key), "실패 뒤에도 잠금이 남았다"
        assert run_id not in run_ids_in(s3_client, bucket, site_prefix, sut), f"{point}: 완료되지 않은 run이 인덱스에 나온다"
        if point != "index":
            assert not exists(s3_client, bucket, key_prefix + "_COMPLETE")
            assert list_keys(s3_client, bucket, key_prefix), f"{point}: 부분 업로드가 있어야 재시도를 검증할 수 있다"
        else:
            assert exists(s3_client, bucket, key_prefix + "_COMPLETE")
        retried = publisher.s13(run_dir)  # 같은 runId 재시도
        assert retried.returncode == 0 and publisher.stage13(run_dir)["status"] == "passed", retried.stderr[-1500:]
        assert run_ids_in(s3_client, bucket, site_prefix, sut).count(run_id) == 1
        assert exists(s3_client, bucket, key_prefix + "_COMPLETE")

    # 완료된 run을 같은 내용으로 재게시: 업로드를 건너뛰고 성공, 객체 ETag 불변
    before = list_keys(s3_client, bucket, key_prefix)
    again = publisher.s13(run_dir)
    assert again.returncode == 0, again.stderr[-1500:]
    assert publisher.stage13(run_dir)["hosts"]["s3"]["uploaded"] == 0
    assert list_keys(s3_client, bucket, key_prefix) == before
    assert run_ids_in(s3_client, bucket, site_prefix, sut).count(run_id) == 1

    # 내용이 다른 재게시: 실패하고 기존 ETag는 그대로
    stage_file = run_dir / "stages" / "S01.json"
    stage_file.write_text(stage_file.read_text().replace('"status": "passed"', '"status": "passed", "note": "changed"'))
    other = publisher.s13(run_dir)
    assert other.returncode == 1
    stage = publisher.stage13(run_dir)
    assert stage["status"] == "failed" and "다르" in stage["reason"], stage
    assert list_keys(s3_client, bucket, key_prefix) == before
    log = json.loads(get_bytes(s3_client, bucket, f"{site_prefix}suts/{sut}/publish-log/{run_id}.json"))
    assert log["status"] == "passed", "실패한 재게시가 기존 성공 publish-log를 덮어쓰면 안 된다"
    assert not exists(s3_client, bucket, lock_key)


def test_req046_lock(publisher, s3_client, bucket, site_prefix, unlock_after):
    sut = "td-t046"
    run_id, run_dir = publisher.new_run(sut)
    key_prefix = f"{site_prefix}suts/{sut}/runs/{run_id}/"
    lock = publish.acquire_lock(s3_client, bucket, site_prefix, "att-other-owner")
    blocked = publisher.s13(run_dir)
    assert blocked.returncode != 0
    assert "att-other-owner" in blocked.stderr and "--force-unlock att-other-owner" in blocked.stderr
    assert publisher.stage13(run_dir)["status"] == "failed"
    assert list_keys(s3_client, bucket, key_prefix) == {}, "잠금이 있으면 업로드가 없어야 한다"
    assert s3_client.head_object(Bucket=bucket, Key=lock.key)["ETag"].strip('"') == lock.etag

    wrong = publisher.s13(run_dir, "--force-unlock", "att-wrong")
    assert wrong.returncode != 0 and "att-wrong" in wrong.stderr
    assert exists(s3_client, bucket, lock.key)
    right = publisher.s13(run_dir, "--force-unlock", "att-other-owner")
    assert right.returncode == 0, right.stderr
    assert not exists(s3_client, bucket, lock.key)

    done = publisher.s13(run_dir)
    assert done.returncode == 0, done.stderr[-1500:]
    assert not exists(s3_client, bucket, lock.key), "정상 종료 뒤에는 잠금 객체가 없어야 한다"


def _wait_for(predicate, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    pytest.fail(f"시간 초과: {what}", pytrace=False)


def test_sigint_releases_lock(publisher, s3_client, bucket, site_prefix, unlock_after):
    sut = "td-tsigint"
    run_id, run_dir = publisher.new_run(sut)
    key_prefix = f"{site_prefix}suts/{sut}/runs/{run_id}/"
    proc = publisher.popen(run_dir, TD_PUBLISH_PAUSE_SEC="2")
    try:
        _wait_for(lambda: bool(list_keys(s3_client, bucket, key_prefix)), 120, "업로드가 시작되지 않았다")
        assert exists(s3_client, bucket, publish.lock_key(site_prefix))
        os.killpg(proc.pid, signal.SIGINT)
        proc.communicate(timeout=120)
    except BaseException:
        os.killpg(proc.pid, signal.SIGKILL)
        raise
    assert proc.returncode != 0
    assert not exists(s3_client, bucket, publish.lock_key(site_prefix)), "SIGINT 뒤 잠금이 남았다"
    assert not exists(s3_client, bucket, key_prefix + "_COMPLETE")
    assert run_id not in run_ids_in(s3_client, bucket, site_prefix, sut)
    stage = publisher.stage13(run_dir)
    assert stage["status"] == "failed" and "interrupt" in stage["reason"]


def test_sigkill_leaves_lock_with_hint(publisher, s3_client, bucket, site_prefix, unlock_after):
    sut = "td-tsigkill"
    run_id, run_dir = publisher.new_run(sut)
    key_prefix = f"{site_prefix}suts/{sut}/runs/{run_id}/"
    proc = publisher.popen(run_dir, TD_PUBLISH_PAUSE_SEC="2")
    try:
        _wait_for(lambda: bool(list_keys(s3_client, bucket, key_prefix)), 120, "업로드가 시작되지 않았다")
    finally:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate(timeout=60)
    held = publish.read_lock(s3_client, bucket, site_prefix)
    assert held is not None, "SIGKILL이면 잠금이 남아야 한다"
    attempt = held[0]["attemptId"]
    try:
        blocked = publisher.s13(run_dir)
        assert blocked.returncode != 0
        assert attempt in blocked.stderr and f"--force-unlock {attempt}" in blocked.stderr
    finally:
        unlock = publisher.s13(run_dir, "--force-unlock", attempt)
    assert unlock.returncode == 0, unlock.stderr
    assert not exists(s3_client, bucket, publish.lock_key(site_prefix))
    resumed = publisher.s13(run_dir)  # 표식 없이 남은 run은 같은 runId로 이어서 완료된다
    assert resumed.returncode == 0, resumed.stderr[-1500:]
    assert run_ids_in(s3_client, bucket, site_prefix, sut) == [run_id]


def test_req044_history_accumulates(published_runs, s3_client, bucket, site_prefix):
    sut = published_runs["sut"]
    (first_id, _, _), (second_id, _, _) = published_runs["runs"]
    assert set(run_ids_in(s3_client, bucket, site_prefix, sut)) >= {first_id, second_id}
    first_etags = list_keys(s3_client, bucket, f"{site_prefix}suts/{sut}/runs/{first_id}/")
    assert first_etags and f"{site_prefix}suts/{sut}/runs/{first_id}/_COMPLETE" in first_etags
    # 두 run이 `runs.json`과, 그 SUT와 이어진 과제 페이지의 실행 이력 탭(`#panel-runs table#runs`)에 모두 있다.
    project = linked_project(json.loads(get_bytes(s3_client, bucket, f"{site_prefix}projects.json")), sut)
    page = get_bytes(s3_client, bucket, f"{site_prefix}{project['href']}").decode()
    table = runs_table(page)
    assert f'data-run="{first_id}"' in table and f'data-run="{second_id}"' in table


def test_req044_history_third_run_keeps_first_etags(publisher, published_runs, s3_client, bucket, site_prefix):
    sut = published_runs["sut"]
    first_id = published_runs["runs"][0][0]
    before = list_keys(s3_client, bucket, f"{site_prefix}suts/{sut}/runs/{first_id}/")
    run_id, run_dir = publisher.new_run(sut)
    done = publisher.s13(run_dir)
    assert done.returncode == 0, done.stderr[-1500:]
    assert list_keys(s3_client, bucket, f"{site_prefix}suts/{sut}/runs/{first_id}/") == before
    assert {first_id, run_id} <= set(run_ids_in(s3_client, bucket, site_prefix, sut))


def test_req071_publish_status_files(published_runs, s3_client, bucket, site_prefix, local_env):
    sut = published_runs["sut"]
    for run_id, run_dir, _ in published_runs["runs"]:
        key_prefix = f"{site_prefix}suts/{sut}/runs/{run_id}/"
        published = get_bytes(s3_client, bucket, key_prefix + "run.json")
        assert published == (run_dir / "run.json").read_bytes(), "게시된 run.json은 로컬과 바이트 단위로 같아야 한다"
        assert json.loads(published)["stages"]["S13"] == "publishing"
        stage = json.loads((run_dir / "stages" / "S13.json").read_text())
        log_raw = get_bytes(s3_client, bucket, f"{site_prefix}suts/{sut}/publish-log/{run_id}.json")
        log = json.loads(log_raw)
        for field in ("status", "reason", "hosts", "timings", "sizeBytes"):
            assert log[field] == stage[field], field
        assert log["status"] in ("passed", "degraded") and log["sizeBytes"] > 0
        assert set(log["hosts"]) == {"s3", "cloudfront", "lightsail", "hosting"}
        assert set(log["timings"]) == {"uploadSeconds", "rsyncSeconds", "memBeforeMb", "memAfterMb"}
        page = get_bytes(s3_client, bucket, key_prefix + "index.html").decode()
        assert f'data-url="../../publish-log/{run_id}.json"' in page
        # CloudFront로도 같은 publish-log가 나온다(run 페이지가 fetch하는 경로).
        status, body = helpers.https_get(f"reports.{local_env['TD_DOMAIN']}", local_env["TD_DOMAIN"],
                                         f"/{site_prefix}suts/{sut}/publish-log/{run_id}.json")
        assert status == 200 and json.loads(body) == log


def test_req070_lightsail_catch_up(publisher, s3_client, bucket, site_prefix, local_env, unlock_after):
    sut = "td-t070"
    domain = local_env["TD_DOMAIN"]
    first_id, first_dir = publisher.new_run(sut)
    degraded = publisher.s13(first_dir, TD_FAIL_STAGE="S13:lightsail")
    assert degraded.returncode == 0, degraded.stderr[-1500:]
    stage = publisher.stage13(first_dir)
    assert stage["status"] == "degraded" and stage["hosts"]["lightsail"]["status"] == "failed"
    assert stage["hosts"]["s3"]["status"] == "passed"
    log = json.loads(get_bytes(s3_client, bucket, f"{site_prefix}suts/{sut}/publish-log/{first_id}.json"))
    assert log["status"] == "degraded" and log["hosts"]["lightsail"]["status"] == "failed"
    runs_path = f"/{site_prefix}suts/{sut}/runs.json"
    assert helpers.https_get(f"dash.{domain}", domain, runs_path)[0] == 404, "주입한 실패라 Lightsail에는 아직 없어야 한다"

    second_id, second_dir = publisher.new_run(sut)
    done = publisher.s13(second_dir)
    assert done.returncode == 0 and publisher.stage13(second_dir)["status"] == "passed", done.stderr[-1500:]
    status, body = helpers.https_get(f"dash.{domain}", domain, runs_path)
    assert status == 200
    assert body == get_bytes(s3_client, bucket, runs_path.lstrip("/")), "Lightsail runs.json은 S3와 같아야 한다"
    assert {first_id, second_id} == set(r["runId"] for r in json.loads(body))
    assert helpers.https_get(f"dash.{domain}", domain, f"/{site_prefix}suts/{sut}/runs/{first_id}/index.html")[0] == 200


def test_disk_space_preflight_fails_before_upload(publisher, s3_client, bucket, site_prefix, unlock_after):
    sut = "td-tdisk"
    run_id, run_dir = publisher.new_run(sut)
    done = publisher.s13(run_dir, TD_MIN_FREE_GB="100000000")
    assert done.returncode == 1
    stage = publisher.stage13(run_dir)
    assert stage["status"] == "failed" and "여유" in stage["reason"], stage
    assert list_keys(s3_client, bucket, f"{site_prefix}suts/{sut}/") == {}
