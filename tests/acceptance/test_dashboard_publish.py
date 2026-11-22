"""게시의 인덱스 단계(수집·삭제·재생성)와 인덱스 전용 게시(E2E-inj, Task 11).

REQ-079(접두 실행의 설정 격리), 098(인덱스 전용 게시), 099(수집 문제와 게시 상태), 100(빠진 과제의 삭제),
107(암묵 과제), 125(공통 띠), 144(중단 시 수집 정리), 145(두 게시의 잠금 공유).

실제 S3·CloudFront·Lightsail에 게시한다. 모든 게시는 세션 접두(`_test/<sessionId>/`) 아래에서만 한다. 테스트마다
자기 하위 접두(`<세션 접두>dash-<테스트 이름>/`)를 써서 서로 섞이지 않는다. 수집은 가짜 gh·가짜 Sonar·가짜 ssh(`psql`만)로
돌고, Lightsail rsync와 삭제는 실제 ssh로 돈다. 테스트가 만든 게시물은 기존 정책대로 지우지 않는다(잠금만 정리한다).
"""
from __future__ import annotations

import html
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest
import yaml
from botocore.exceptions import ClientError

import helpers
from conftest import Publisher
from dashboard_fixtures import (REPORTS_RUN_ID, cfg_with, make_local_run_with_reports, publish_fakes,
                                stop_publish_fakes)
from td import publish

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_INDEX = REPO_ROOT / "pipeline" / "publish-index.sh"
MIRROR = REPO_ROOT / "work" / "site-mirror"
SEED_SUT = "td-dash"
SCRIPT_TIMEOUT = 1500


# --- 공용 도우미 -------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _stop_fakes():
    yield
    stop_publish_fakes()


_STARTED: list[subprocess.Popen] = []


@pytest.fixture(autouse=True)
def _reap_started_scripts():
    """start_script로 띄운 게시기가 테스트 실패로 남으면 그 프로세스 그룹(자기 세션)만 죽인다."""
    yield
    while _STARTED:
        proc = _STARTED.pop()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=30)


def script_env(**extra: str) -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith("TD_") and key != "SONAR_TOKEN"}
    env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(REPO_ROOT / "work"))
    env.update({key: str(value) for key, value in extra.items()})
    assert env.get("TD_SITE_PREFIX", "").startswith("_test/"), "실제 게시는 _test/ 접두에서만 한다"
    return env


def run_script(script: Path, **extra) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=script_env(**extra),
                          timeout=SCRIPT_TIMEOUT)


def start_script(script: Path, **extra) -> subprocess.Popen:
    """새 세션(프로세스 그룹)으로 띄운다. publish-index.sh는 게시기 파이썬을 exec하므로 이 PID가 곧 게시기다."""
    proc = subprocess.Popen(["bash", str(script)], env=script_env(**extra), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    _STARTED.append(proc)
    return proc


def write_cfg(directory: Path, data: dict) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dashboard.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    return path


def wait_until(predicate, timeout: float, what: str = "조건") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.3)
    pytest.fail(f"시간 초과: {what}", pytrace=False)


def processes_matching(*patterns: str, marker: str) -> list[str]:
    """명령줄에 marker가 있고 patterns 가운데 하나가 있는 프로세스(ps)."""
    out = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if marker in line and any(pattern in line for pattern in patterns)]


class Site:
    """한 하위 접두의 S3·미러·Lightsail 조회."""

    def __init__(self, s3, bucket: str, prefix: str, local_env: dict):
        self.s3, self.bucket, self.prefix, self.local_env = s3, bucket, prefix, local_env

    def keys(self, rel: str = "") -> list[str]:
        found = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.prefix + rel):
            found += [obj["Key"] for obj in page.get("Contents", [])]
        return found

    def count(self, rel: str) -> int:
        return len(self.keys(rel))

    def bytes(self, rel: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=self.prefix + rel)["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def text(self, rel: str) -> str:
        return (self.bytes(rel) or b"").decode()

    def json(self, rel: str):
        return json.loads(self.bytes(rel))

    def head(self, rel: str) -> dict:
        return self.s3.head_object(Bucket=self.bucket, Key=self.prefix + rel)

    def lock(self):
        return publish.read_lock(self.s3, self.bucket, self.prefix)

    def project_names(self) -> list[str]:
        return [project["name"] for project in self.json("projects.json")["projects"]]

    def dash(self, rel: str) -> tuple[int, bytes]:
        domain = self.local_env["TD_DOMAIN"]
        return helpers.https_get(f"dash.{domain}", domain, f"/{self.prefix}{rel}")

    def cdn(self, path: str) -> tuple[int, bytes]:
        domain = self.local_env["TD_DOMAIN"]
        return helpers.https_get(f"reports.{domain}", domain, path)

    def _lightsail(self, remote: str) -> subprocess.CompletedProcess:
        env = self.local_env
        return subprocess.run(["ssh", "-i", env["TD_SSH_KEY_PATH"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                               "-o", "LogLevel=ERROR", f"ubuntu@{env['TD_LIGHTSAIL_IP']}", remote],
                              capture_output=True, text=True, timeout=60)

    def lightsail_make_dir(self, rel: str) -> None:
        """이 테스트의 하위 접두 안에만 디렉터리를 만든다(앞선 게시가 지우지 못한 과제 디렉터리를 흉내 낸다)."""
        assert self.prefix.startswith("_test/") and re.fullmatch(r"[A-Za-z0-9_./-]+", self.prefix + rel) and ".." not in rel
        done = self._lightsail(f"mkdir -p '/srv/dashboard/{self.prefix}{rel}' && touch '/srv/dashboard/{self.prefix}{rel}/index.html'")
        assert done.returncode == 0, done.stderr

    def lightsail_exists(self, rel: str) -> bool:
        """`/srv/dashboard/<접두><rel>`이 Lightsail에 있는가(읽기 전용 `test -e`)."""
        assert re.fullmatch(r"[A-Za-z0-9_./-]+", self.prefix + rel) and ".." not in rel
        env = self.local_env
        done = subprocess.run(["ssh", "-i", env["TD_SSH_KEY_PATH"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                               "-o", "LogLevel=ERROR", f"ubuntu@{env['TD_LIGHTSAIL_IP']}",
                               f"test -e '/srv/dashboard/{self.prefix}{rel}' && echo yes || echo no"],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0 and done.stdout.strip() in ("yes", "no"), done.stderr
        return done.stdout.strip() == "yes"


def _sub_prefix(site_prefix: str, request) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", request.node.name.removeprefix("test_")).strip("-")
    return f"{site_prefix}dash-{name}/"


def _unlock_own(s3, bucket: str, prefix: str) -> None:
    """이 테스트의 하위 접두에 남은 잠금만 푼다(다른 접두는 건드리지 않는다)."""
    held = publish.read_lock(s3, bucket, prefix)
    if held:
        publish.force_unlock(s3, bucket, prefix, held[0]["attemptId"])


@pytest.fixture
def seeded_prefix(request, site_prefix, s3_client, bucket, tmp_path_factory):
    """완료 run 하나(SUT td-dash)를 실제 S13으로 게시해 둔 이 테스트만의 하위 접두."""
    prefix = _sub_prefix(site_prefix, request)
    seeder = Publisher(tmp_path_factory.mktemp("seed-runs"), prefix)
    _run_id, run_dir = seeder.new_run(SEED_SUT)
    done = seeder.s13(run_dir)
    assert done.returncode == 0, f"씨앗 run 게시 실패: {done.stderr[-2000:]}"
    try:
        yield prefix
    finally:
        _unlock_own(s3_client, bucket, prefix)


@pytest.fixture
def site_of(s3_client, bucket, local_env):
    return lambda prefix: Site(s3_client, bucket, prefix, local_env)


def index_publish(prefix: str, cfg: dict | None, fakes, tmp_path: Path, **extra) -> subprocess.CompletedProcess:
    """publish-index.sh 한 번. cfg가 None이면 설정을 넘기지 않는다. 종료 코드 0을 확인한다."""
    env = {"TD_SITE_PREFIX": prefix, **fakes.env, **extra}
    if cfg is not None:
        index_publish.counter += 1
        env["TD_DASHBOARD_CONFIG"] = write_cfg(tmp_path / f"cfg{index_publish.counter}", cfg)
    proc = run_script(PUBLISH_INDEX, **env)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return proc


index_publish.counter = 0


# --- REQ-098 ---------------------------------------------------------------------------------
def test_req098_index_only_publish(seeded_prefix, site_of, tmp_path):
    site = site_of(seeded_prefix)
    fakes = publish_fakes(tmp_path / "fakes", {"o/alpha": {}, "o/beta": {}})
    before_suts = set(site.keys("suts/"))
    index_publish(seeded_prefix, cfg_with(plain=["alpha", "beta"]), fakes, tmp_path)
    new_keys = set(site.keys("suts/")) - before_suts
    assert not [key for key in new_keys if "/runs/" in key], f"새 run 디렉터리가 생겼다: {sorted(new_keys)[:5]}"
    for rel in ("projects/alpha/latest.json", "projects/alpha/index.html", "projects/alpha/series.json",
                "projects/beta/latest.json", "projects/beta/index.html", "projects/beta/series.json",
                "projects.json", "index.html"):
        assert site.head(rel)["CacheControl"] == "no-cache", rel
    for name in ("alpha", "beta"):
        assert site.keys(f"projects/{name}/snapshots/"), name
    assert {"alpha", "beta"} <= set(site.project_names())
    mirrored = MIRROR / seeded_prefix / "projects/alpha/latest.json"
    assert mirrored.exists() and mirrored.read_bytes() == site.bytes("projects/alpha/latest.json")
    assert site.lock() is None
    log = site.json("publish-log/index.json")
    assert log["status"] in ("passed", "degraded") and "reason" in log and {"s3", "cloudfront", "lightsail"} <= set(log["hosts"])
    assert site.dash("projects.json") == (200, site.bytes("projects.json"))


# --- REQ-079 ---------------------------------------------------------------------------------
def test_req079_prefix_run_uses_only_given_config(seeded_prefix, site_of, tmp_path):
    site = site_of(seeded_prefix)
    fakes = publish_fakes(tmp_path / "fakes", {"o/alpha": {}})
    production = [item["name"] for item in yaml.safe_load((REPO_ROOT / "dashboard.yaml").read_text())["projects"]]
    index_publish(seeded_prefix, None, fakes, tmp_path)
    home = site.text("index.html")
    assert site.project_names() == [SEED_SUT], "설정을 넘기지 않은 접두 실행에는 암묵 과제만 나온다"
    assert not [name for name in production if f'data-name="{name}"' in home]
    assert fakes.gh.calls == []
    index_publish(seeded_prefix, cfg_with(plain="alpha"), fakes, tmp_path)
    assert "alpha" in site.project_names() and 'data-name="alpha"' in site.text("index.html")
    assert fakes.gh.calls, "넘겨받은 설정의 과제는 수집한다"


# --- REQ-099 ---------------------------------------------------------------------------------
COLLECT_POINTS = {"degraded": "injected", "exit1": publish.COLLECT_FAILED_REASON, "garbage": publish.COLLECT_FAILED_REASON}


def test_req099_collect_trouble_still_publishes(seeded_prefix, site_of, tmp_path, tmp_path_factory):
    site = site_of(seeded_prefix)
    fakes = publish_fakes(tmp_path / "fakes", {"o/alpha": {"description": "alpha desc"}, "o/hush": {"visibility": "private"}})
    index_publish(seeded_prefix, cfg_with(plain="alpha"), fakes, tmp_path)            # 앞선 스냅숏
    assert site.keys("projects/alpha/snapshots/")
    with_private = cfg_with(plain=["alpha", "hush"])
    publisher = Publisher(tmp_path_factory.mktemp("s13-collect"), seeded_prefix)
    for mode in ("index", "s13"):
        for point, reason in COLLECT_POINTS.items():
            label = f"{mode}/{point}"
            before = site.head("index.html")["LastModified"]
            time.sleep(1.1)
            cfg_path = write_cfg(tmp_path / f"cfg-{mode}-{point}", with_private)
            injected = {"TD_DASHBOARD_CONFIG": cfg_path, "TD_FAIL_STAGE": f"collect:{point}", **fakes.env}
            if mode == "index":
                proc = run_script(PUBLISH_INDEX, TD_SITE_PREFIX=seeded_prefix, **injected)
                log = site.json("publish-log/index.json")
                published_texts = [json.dumps(log, ensure_ascii=False)]
            else:
                run_id, run_dir = publisher.new_run(SEED_SUT)
                proc = publisher.s13(run_dir, **{key: str(value) for key, value in injected.items()})
                log = site.json(f"suts/{SEED_SUT}/publish-log/{run_id}.json")
                stage = Publisher.stage13(run_dir)
                assert stage["status"] == "degraded" and reason in stage["reason"], (label, stage)
                published_texts = [json.dumps(log, ensure_ascii=False), (run_dir / "stages/S13.json").read_text(),
                                   (run_dir / "run.json").read_text()]
            assert proc.returncode == 0, (label, proc.stderr[-2000:])
            assert log["status"] == "degraded" and reason in log["reason"], (label, log)
            assert log["hosts"]["collect"]["status"] == "failed" and log["hosts"]["s3"]["status"] == "passed", label
            if point == "degraded":
                assert "비공개 과제 1개 제외" in log["reason"], (label, log["reason"])
            assert all("hush" not in text for text in published_texts), f"{label}: 제외된 과제 이름이 게시 기록에 있다"
            assert site.head("index.html")["LastModified"] > before, f"{label}: 홈이 다시 게시되지 않았다"
            assert "alpha" in site.project_names() and site.bytes("projects/alpha/index.html"), label
            assert "hush" not in site.text("projects.json") + site.text("index.html"), label


# --- REQ-100 ---------------------------------------------------------------------------------
def test_req100_removed_or_private_project_deleted(seeded_prefix, site_of, tmp_path):
    site = site_of(seeded_prefix)
    fakes = publish_fakes(tmp_path / "fakes", {"o/alpha": {"description": "alpha desc"}, "o/beta": {}})
    both = cfg_with(plain=["alpha", "beta"])
    index_publish(seeded_prefix, both, fakes, tmp_path)
    assert site.count("projects/alpha/") > 0 and site.lightsail_exists("projects/alpha")
    counts = {rel: site.count(rel) for rel in ("projects/beta/", "suts/", "static/")}

    def gone() -> bool:
        blob = site.text("index.html") + site.text("projects.json")
        return (site.count("projects/alpha/") == 0 and not (MIRROR / seeded_prefix / "projects/alpha").exists()
                and "alpha" not in blob and "alpha desc" not in blob and not site.lightsail_exists("projects/alpha"))

    index_publish(seeded_prefix, cfg_with(plain=["beta"]), fakes, tmp_path)          # (1) 설정에서 뺀다
    assert gone(), "설정에서 뺀 과제가 남았다"
    index_publish(seeded_prefix, both, fakes, tmp_path)                              # 되돌린다
    assert site.count("projects/alpha/") > 0 and site.lightsail_exists("projects/alpha")
    fakes.gh.set("o/alpha", visibility="private")                                     # (2) 비공개가 된다
    index_publish(seeded_prefix, both, fakes, tmp_path)
    assert gone(), "비공개가 된 과제가 남았다"
    assert all(site.count(rel) >= count for rel, count in counts.items()), counts
    assert "alpha" not in json.dumps(site.json("publish-log/index.json"), ensure_ascii=False)
    # 따라잡기: S3·미러에는 없고 Lightsail에만 남은 과제 디렉터리(앞선 게시의 원격 삭제 실패)를 다음 게시가 원격 목록에서 지운다
    site.lightsail_make_dir("projects/stray")
    assert site.lightsail_exists("projects/stray") and site.count("projects/stray/") == 0
    index_publish(seeded_prefix, both, fakes, tmp_path)
    assert not site.lightsail_exists("projects/stray") and site.lightsail_exists("projects/beta")
    assert "stray" not in json.dumps(site.json("publish-log/index.json"), ensure_ascii=False)


# --- REQ-107 ---------------------------------------------------------------------------------
def test_req107_unregistered_sut_listed(mini_sut_run, site_prefix, site_of, tmp_path):
    assert mini_sut_run.returncode == 0, mini_sut_run.stderr[-2000:]
    site = site_of(site_prefix)
    fakes = publish_fakes(tmp_path / "fakes", {})
    index_publish(site_prefix, None, fakes, tmp_path)
    home = site.text("index.html")
    row = re.search(r'<tr class="proj" data-name="mini-sut" data-status="([a-z]+)"[^>]*>(.*?)</tr>', home, re.S)
    assert row, "홈 표에 mini-sut 줄이 없다"
    assert row.group(1) != "none" and "tag-pipeline" in row.group(2) and "tag-partial" not in row.group(2)
    assert site.bytes("projects/mini-sut/index.html")
    assert fakes.gh.calls == []
    assert site.lock() is None


# --- REQ-125 ---------------------------------------------------------------------------------
ENTRY_FILES = ("index.html", "coverage/coverage.html", "sonar/sonar.html", "compare/compare.html", "ontology/jqa.html",
               "ontology/owl.html", "hotspot/hotspots.html", "hotspot/api_report.html", "tia/tia.html",
               "cucumber/base-r1/index.html")


def test_req125_nav_on_all_reports_under_prefix(request, site_prefix, site_of, s3_client, bucket, tmp_path):
    prefix = _sub_prefix(site_prefix, request)
    site = site_of(prefix)
    publisher = Publisher(tmp_path / "runs", prefix)
    run_dir = make_local_run_with_reports(tmp_path / "local")
    try:
        done = publisher.s13(run_dir)
    finally:
        _unlock_own(s3_client, bucket, prefix)
    assert done.returncode == 0, done.stderr[-2000:]
    run_path = f"/{prefix}suts/pet/runs/{REPORTS_RUN_ID}/"
    statuses: dict[str, int] = {}
    for rel in ENTRY_FILES:
        status, body = site.cdn(run_path + rel)
        assert status == 200, rel
        page = body.decode(errors="replace")
        assert page.count('<nav class="tdnav"') == 1, rel
        strip = re.search(r'<nav class="tdnav".*?</nav>', page, re.S).group(0)
        hrefs = [html.unescape(href) for href in re.findall(r'href="([^"]+)"', strip)]
        assert len(hrefs) >= 5, (rel, hrefs)
        base = f"https://reports.example{run_path}{rel}"
        for href in hrefs:
            path = urlsplit(urljoin(base, href)).path
            assert path.startswith(f"/{prefix}"), (rel, href)
            if path not in statuses:
                statuses[path] = site.cdn(path)[0]
            assert statuses[path] == 200, (rel, href, path)
        sut_href = re.search(r'<a class="tdnav-sut" href="([^"]+)"', strip).group(1)
        assert urlsplit(urljoin(base, html.unescape(sut_href))).path == f"/{prefix}suts/pet/index.html", rel


# --- REQ-144 ---------------------------------------------------------------------------------
def test_req144_interrupt_cleans_collect_token_and_lock(seeded_prefix, site_of, tmp_path):
    site = site_of(seeded_prefix)
    for sig in (signal.SIGTERM, signal.SIGINT):
        scratch = tmp_path / sig.name
        fakes = publish_fakes(scratch, {"o/alpha": {}}, sonar={"delay": 20})
        proc = start_script(PUBLISH_INDEX, TD_SITE_PREFIX=seeded_prefix,
                            TD_DASHBOARD_CONFIG=write_cfg(scratch, cfg_with(plain="alpha")), **fakes.env)
        wait_until(lambda: fakes.ssh.rows() != [] and fakes.sonar.keyed_requests != [], 120, "수집이 Sonar 읽기에 닿지 않았다")
        assert fakes.ssh.rows()[0].startswith("td-collect-")
        proc.send_signal(sig)
        _out, err = proc.communicate(timeout=180)
        assert proc.returncode != 0, (sig.name, err[-2000:])
        assert "interrupted" in err, (sig.name, err[-2000:])
        assert fakes.ssh.rows() == [], (sig.name, err[-2000:])
        assert site.lock() is None, sig.name
        assert not processes_matching("pipeline/collect.sh", "td.collect", marker=str(scratch)), sig.name
        assert fakes.gh.alive_pids() == []


# --- REQ-145 ---------------------------------------------------------------------------------
def test_req145_index_only_and_s13_share_lock(seeded_prefix, site_of, tmp_path, tmp_path_factory):
    site = site_of(seeded_prefix)
    fakes = publish_fakes(tmp_path / "fakes", {"o/alpha": {}}, sonar={"delay": 15})
    first = start_script(PUBLISH_INDEX, TD_SITE_PREFIX=seeded_prefix,
                         TD_DASHBOARD_CONFIG=write_cfg(tmp_path, cfg_with(plain="alpha")), **fakes.env)
    wait_until(lambda: fakes.ssh.rows() != [], 120, "인덱스 전용 게시의 수집이 시작되지 않았다")
    assert site.lock() is not None
    publisher = Publisher(tmp_path_factory.mktemp("s13-lock"), seeded_prefix)
    _run_id, run_dir = publisher.new_run(SEED_SUT)
    started = time.monotonic()
    second = publisher.s13(run_dir)
    seconds = time.monotonic() - started
    stage = Publisher.stage13(run_dir)
    assert second.returncode != 0 and stage["status"] == "failed", stage
    assert "--force-unlock" in stage["reason"] and seconds < 30, (seconds, stage["reason"])
    _out, err = first.communicate(timeout=300)
    assert first.returncode == 0, err[-2000:]
    assert site.lock() is None
