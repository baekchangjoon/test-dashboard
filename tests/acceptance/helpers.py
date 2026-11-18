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
