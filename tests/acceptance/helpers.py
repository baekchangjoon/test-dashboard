"""수용 테스트 공용 helper(conftest와 테스트에서 import)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def claude_call_log(run_dir) -> list[dict]:
    """shim이 `<run_dir>/llm-calls.jsonl`에 남긴 호출 기록을 읽는다."""
    log_file = Path(run_dir) / "llm-calls.jsonl"
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text().splitlines() if line]


def docker_ids(*args: str) -> frozenset[str]:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.fail(f"docker CLI를 쓸 수 없다: {type(exc).__name__}", pytrace=False)
    if result.returncode != 0:
        pytest.fail(f"docker {' '.join(args)} 실패: {result.stderr.strip()[:200]}", pytrace=False)
    return frozenset(line for line in result.stdout.split() if line)


def find_leaked_resources(label_value: str) -> dict[str, list[str]]:
    """`test-run=<label_value>` 라벨이 붙은 컨테이너·네트워크·볼륨 ID를 종류별로 돌려준다(없으면 빈 dict)."""
    flt = f"label=test-run={label_value}"
    found = {
        "containers": docker_ids("ps", "-aq", "--filter", flt),
        "networks": docker_ids("network", "ls", "-q", "--filter", flt),
        "volumes": docker_ids("volume", "ls", "-q", "--filter", flt),
    }
    return {kind: sorted(ids) for kind, ids in found.items() if ids}


# --- SUT 컨테이너 환경(Task 4) ------------------------------------------------------------
import glob
import os
import shutil
import stat
import textwrap

REPO_ROOT = Path(__file__).resolve().parents[2]
STUB_STAGE_SOURCE = REPO_ROOT / "tests" / "fixtures" / "stub-stages"
PETCLINIC_SRC = REPO_ROOT / "work" / "suts" / "petclinic" / "src"
AGENT_JAR = REPO_ROOT / "work" / "tools" / "pjacoco-agent.jar"
SUT_PACKAGES = "org.springframework.samples.petclinic.*"


def petclinic_jar() -> Path:
    """S00이 빌드해 둔 petclinic jar. 없으면 테스트가 실패한다(전제 누락)."""
    jars = sorted(glob.glob(str(PETCLINIC_SRC / "build" / "libs" / "spring-petclinic-*-SNAPSHOT.jar")))
    if len(jars) != 1 or not AGENT_JAR.exists():
        pytest.fail(f"S00이 빌드한 SUT jar와 pjacoco agent가 필요하다(jar={jars}, agent={AGENT_JAR.exists()})",
                    pytrace=False)
    return Path(jars[0])


def make_stage_dir(tmp_path: Path, stage_id: str, body: str, *, prologue: bool = True) -> Path:
    """스텁 단계 디렉터리를 복사하고 한 단계만 `body`로 바꾼 스크립트로 교체한다(S01 스텁: SUT를 띄우고 body 실행)."""
    stage_dir = tmp_path / "stages"
    shutil.copytree(STUB_STAGE_SOURCE, stage_dir)
    target = next(stage_dir.glob(f"{stage_id}-*.sh"))
    script = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        source "$TD_ROOT/pipeline/lib/common.sh"
        source "$TD_ROOT/pipeline/lib/env.sh"
        td_stage_begin {stage_id}
        """)
    if prologue:
        script += textwrap.dedent(f"""\
            td_sut_up "$TD_RUN_DIR" {stage_id} blackbox || {{ td_stage_end {stage_id} failed "$TD_SUT_FAIL_REASON"; exit 1; }}
            """)
    script += textwrap.dedent(body) + f"\ntd_stage_end {stage_id} passed\n"
    target.write_text(script)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return stage_dir


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_pids(run_dir: Path) -> dict[str, int]:
    pids_dir = Path(run_dir) / "pids"
    if not pids_dir.exists():
        return {}
    return {p.stem: int(p.read_text().strip()) for p in pids_dir.glob("*.pid")}


# --- 사이트 생성 fixture(Task 7) ---------------------------------------------------------
def make_site_run(site_base: Path, sut: str, run_id: str, *, complete: bool = True, kpis: dict | None = None,
                  stages: dict | None = None, s09_top10=None, coverage_dir: bool = False, commit: str = "b6f9393") -> Path:
    """`<site_base>/suts/<sut>/runs/<runId>/`에 게시된 run 모양의 디렉터리를 만든다(run.json, stages/, 선택 S08 산출물)."""
    run_dir = Path(site_base) / "suts" / sut / "runs" / run_id
    (run_dir / "stages").mkdir(parents=True)
    stage_status = stages or {"S00": "passed", "S01": "passed", "S08": "passed"}
    started = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}T{run_id[9:11]}:{run_id[11:13]}:{run_id[13:15]}Z"
    (run_dir / "run.json").write_text(json.dumps({
        "runId": run_id, "sut": sut, "commit": commit, "trigger": "manual", "startedAt": started,
        "finishedAt": started, "kpis": kpis or {}, "stages": {**stage_status, "S13": "publishing"}}))
    for stage_id, status in stage_status.items():
        data = {"id": stage_id, "status": status, "reason": None if status == "passed" else "x", "outputs": {}}
        if stage_id == "S09" and s09_top10 is not None:
            data["top10"] = s09_top10
        if stage_id == "S08" and coverage_dir:
            data["outputs"] = {"coverage": str(run_dir / "S08")}
        (run_dir / "stages" / f"{stage_id}.json").write_text(json.dumps(data))
    if coverage_dir:
        cov = run_dir / "S08"
        (cov / "blackbox" / "attributed" / "exec").mkdir(parents=True)
        (cov / "blackbox" / "attributed" / "exec" / "a.exec").write_bytes(b"\x00")
        (cov / "coverage.html").write_text("<html>stale</html>")
        (cov / "coverage.json").write_text(json.dumps({"suites": {}, "classes": [], "integrity": {"violations": [], "classIdWarnings": 0, "probes": []}, "merged": {}}))
        (cov / "site.css").write_text("/*dup*/")
    if complete:
        (run_dir / "_COMPLETE").write_text("")
    return run_dir


# --- 방금 만든 DNS 이름 접근(로컬 리졸버의 NXDOMAIN 음성 캐시 우회) -------------------------
import http.client
import socket
import ssl


def resolve_authoritative(host: str, zone_id: str) -> str:
    """Route53 권한 응답에서 A 레코드를 얻는다."""
    import boto3
    answer = boto3.client("route53").test_dns_answer(HostedZoneId=zone_id, RecordName=host, RecordType="A")
    ips = [value for value in answer["RecordData"] if value[:1].isdigit()]
    assert ips, f"{host}의 A 응답이 없다: {answer['ResponseCode']}"
    return ips[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS 검증과 SNI는 호스트 이름으로 하되 연결은 지정한 IP로 한다."""

    def __init__(self, host, ip, **kwargs):
        super().__init__(host, **kwargs)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)


def https_get(host: str, domain: str, path: str = "/", timeout: int = 30) -> tuple[int, bytes]:
    """getaddrinfo가 되면 그대로, gaierror면 Route53 권한 응답 IP로 고정해 GET한다(TLS 검증은 호스트 이름 기준)."""
    from td import route53
    try:
        socket.getaddrinfo(host, 443)
        ip = None
    except socket.gaierror:
        ip = resolve_authoritative(host, route53.find_zone_id(domain))
    if ip is None:
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(f"https://{host}{path}", timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, b""
    connection = PinnedHTTPSConnection(host, ip, timeout=timeout)
    connection.request("GET", path)
    response = connection.getresponse()
    return response.status, response.read()


def https_fetch(host: str, domain: str, path: str = "/", timeout: int = 30) -> tuple[int, dict[str, str], bytes]:
    """https_get과 같은 DNS 우회로 (상태, 소문자 헤더 dict, 본문)을 돌려준다(리다이렉트는 따라가지 않는다)."""
    from td import route53
    try:
        socket.getaddrinfo(host, 443)
        connection = http.client.HTTPSConnection(host, timeout=timeout)
    except socket.gaierror:
        connection = PinnedHTTPSConnection(host, resolve_authoritative(host, route53.find_zone_id(domain)), timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        connection.close()


def crawl(host: str, domain: str, start_path: str, scope_prefixes: tuple[str, ...], limit: int = 400) -> dict[str, int]:
    """같은 호스트 링크 BFS. scope_prefixes로 시작하는 경로만 따라간다. 경로 -> 상태 코드(HTML만 링크를 읽는다)."""
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlsplit

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.found: list[str] = []

        def handle_starttag(self, tag, attrs):
            for name, value in attrs:
                if name in ("href", "src") and value:
                    self.found.append(value)

    seen: dict[str, int] = {}
    queue = [start_path]
    while queue and len(seen) < limit:
        path = queue.pop(0)
        if path in seen:
            continue
        status, headers, body = https_fetch(host, domain, path)
        seen[path] = status
        if status != 200 or "text/html" not in headers.get("content-type", ""):
            continue
        parser = Links()
        parser.feed(body.decode("utf-8", "replace"))
        for link in parser.found:
            joined = urlsplit(urljoin(f"https://{host}{path}", link))
            if joined.scheme not in ("http", "https") or joined.netloc != host:
                continue
            target = joined.path or "/"
            if target not in seen and any(target.startswith(prefix) for prefix in scope_prefixes):
                queue.append(target)
    return seen


# --- S13 게시 테스트 보조(Task 10) ---------------------------------------------------------
import hashlib
import io

from botocore.exceptions import ClientError


def _client_error(code: str, status: int, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, op)


class FakeS3:
    """boto3 S3 클라이언트의 게시기 사용 부분만 흉내 내는 메모리 구현(조건부 쓰기·삭제 포함)."""

    def __init__(self, supports_conditional_delete: bool = True):
        self.objects: dict[str, dict] = {}
        self.supports_conditional_delete = supports_conditional_delete
        self.calls: list[tuple[str, str, dict]] = []

    @staticmethod
    def _body(body) -> bytes:
        if hasattr(body, "read"):
            return body.read()
        return body if isinstance(body, bytes) else str(body).encode()

    def put_object(self, Bucket, Key, Body=b"", IfNoneMatch=None, **kwargs):
        self.calls.append(("put", Key, {"IfNoneMatch": IfNoneMatch, **kwargs}))
        if IfNoneMatch == "*" and Key in self.objects:
            raise _client_error("PreconditionFailed", 412, "PutObject")
        data = self._body(Body)
        self.objects[Key] = {"data": data, "etag": hashlib.md5(data).hexdigest(), **kwargs}
        return {"ETag": f'"{self.objects[Key]["etag"]}"'}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("404", 404, "HeadObject")
        obj = self.objects[Key]
        return {"ETag": f'"{obj["etag"]}"', "ContentLength": len(obj["data"])}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _client_error("NoSuchKey", 404, "GetObject")
        obj = self.objects[Key]
        return {"ETag": f'"{obj["etag"]}"', "Body": io.BytesIO(obj["data"]), "ContentLength": len(obj["data"])}

    def delete_object(self, Bucket, Key, IfMatch=None):
        self.calls.append(("delete", Key, {"IfMatch": IfMatch}))
        if IfMatch is not None:
            if not self.supports_conditional_delete:
                raise _client_error("NotImplemented", 501, "DeleteObject")
            if Key in self.objects and self.objects[Key]["etag"] != IfMatch.strip('"'):
                raise _client_error("PreconditionFailed", 412, "DeleteObject")
        self.objects.pop(Key, None)
        return {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        fake = self

        class Paginator:
            def paginate(self, Bucket, Prefix=""):
                keys = sorted(k for k in fake.objects if k.startswith(Prefix))
                yield {"Contents": [{"Key": k, "Size": len(fake.objects[k]["data"]),
                                     "ETag": f'"{fake.objects[k]["etag"]}"'} for k in keys]}
        return Paginator()


def make_local_run(base: Path, sut: str, run_id: str, *, with_coverage: bool = True, passed: float = 0.9) -> Path:
    """게시 전 로컬 run 디렉터리(`<base>/<runId>`): run.json, stages/S00,S01,S08 JSON, S08 산출물."""
    from td import state
    run_dir = Path(base) / run_id
    run_dir.mkdir(parents=True)
    started = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}T{run_id[9:11]}:{run_id[11:13]}:{run_id[13:15]}Z"
    state.write_run_meta(run_dir, runId=run_id, sut=sut, commit="b6f939355e8790202ddfc71e3f3507252745ed37",
                         trigger="manual", startedAt=started)
    state.set_run_field(run_dir, "kpis", {"tests": {"passRate": passed}, "blackbox": {"line": 0.5}})
    state.end(run_dir, "S00", "passed")
    state.end(run_dir, "S01", "passed")
    outputs = None
    if with_coverage:
        cov = run_dir / "S08"
        (cov / "blackbox" / "attributed" / "exec").mkdir(parents=True)
        (cov / "blackbox" / "attributed" / "exec" / "a.exec").write_bytes(b"\x00" * 64)
        (cov / "coverage.html").write_text("<html>stale</html>")
        (cov / "coverage.json").write_text(json.dumps(
            {"suites": {}, "classes": [], "integrity": {"violations": [], "classIdWarnings": 0, "probes": []}, "merged": {}}))
        outputs = {"coverage": str(cov)}
    state.end(run_dir, "S08", "passed", outputs=outputs)
    return run_dir
