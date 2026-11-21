"""td.sonar 단위 테스트(REQ-037 Unit): 가짜 Sonar API(로컬 HTTP 서버)로 페이지 순회, 상한, CE 폴링, 프로젝트 보장, 렌더링을 본다."""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from td import sonar

from fake_sonar import FIXTURES, KEY, FakeSonar, start_fake_sonar  # noqa: F401

SCHEMA = Path(__file__).resolve().parents[2] / "site-gen" / "td" / "schemas" / "sonar.schema.json"


@pytest.fixture
def fake():
    state, stop = start_fake_sonar()
    state.client = sonar.SonarClient(state.url, token="squ_unit_token_value")
    yield state
    stop()


def _invariants(doc: dict) -> None:
    for name in ("issues", "hotspots"):
        part = doc[name]
        assert part["fetched"] == len(part["items"]) == min(part["total"], 10000), name
        assert part["truncated"] == (part["total"] > part["fetched"]), name
        for item in part["items"]:
            assert item["key"] and item["link"].startswith(doc["serverUrl"]), item


# --- export: 페이지 순회와 상한 -------------------------------------------------------------------
def test_req037_export_multi_page_invariants(fake):
    fake.issue_total, fake.hotspot_total = 1234, 7
    doc = sonar.export(KEY, client=fake.client, ce_task_id="AZ-task-1")
    _invariants(doc)
    assert doc["issues"]["total"] == 1234 and doc["issues"]["truncated"] is False
    assert doc["hotspots"]["fetched"] == 7
    assert len({item["key"] for item in doc["issues"]["items"]}) == 1234  # 중복 없이 모두
    assert fake.max_ps_seen <= 500
    assert doc["projectKey"] == KEY and doc["ceTaskId"] == "AZ-task-1"
    assert doc["qualityGate"]["status"] == "ERROR"  # ERROR도 export는 성공


def test_req037_export_caps_at_10000_and_marks_truncated(fake):
    fake.issue_total, fake.hotspot_total = 10500, 10000
    doc = sonar.export(KEY, client=fake.client)
    _invariants(doc)
    assert doc["issues"] == {**doc["issues"], "total": 10500, "fetched": 10000, "truncated": True}
    assert doc["hotspots"]["truncated"] is False and doc["hotspots"]["fetched"] == 10000


def test_req037_export_empty_results(fake):
    doc = sonar.export(KEY, client=fake.client)
    _invariants(doc)
    assert doc["issues"]["items"] == [] and doc["hotspots"]["fetched"] == 0


def test_req037_export_matches_schema_and_measure_keys(fake):
    fake.issue_total, fake.hotspot_total = 3, 2
    doc = sonar.export(KEY, client=fake.client, ce_task_id="AZ-task-1")
    errors = list(Draft202012Validator(json.loads(SCHEMA.read_text())).iter_errors(doc))
    assert not errors, [e.message for e in errors]
    assert set(doc["measures"]) == {"coverage", "bugs", "vulnerabilities", "code_smells", "duplicated_lines_density",
                                    "ncloc", "sqale_rating", "reliability_rating", "security_rating"}
    assert doc["measures"]["coverage"] == "41.7"
    assert doc["qualityGate"]["conditions"][0]["metricKey"] == "new_coverage"


def test_req037_export_links_point_at_sonar_pages(fake):
    fake.issue_total, fake.hotspot_total = 1, 1
    doc = sonar.export(KEY, client=fake.client)
    assert doc["issues"]["items"][0]["link"] == f"{fake.url}/project/issues?id={KEY}&issues=ISS-0&open=ISS-0"
    assert doc["hotspots"]["items"][0]["link"] == f"{fake.url}/security_hotspots?id={KEY}&hotspots=HS-0"


def test_export_sends_bearer_token_header_only(fake):
    fake.issue_total = 1
    sonar.export(KEY, client=fake.client)
    assert all(auth == "Bearer squ_unit_token_value" for *_, auth in fake.requests)
    assert not any("squ_unit_token_value" in json.dumps([m, p, q]) for m, p, q, _ in fake.requests)  # URL/본문에 토큰이 없다


# --- CE 폴링 ----------------------------------------------------------------------------------
def test_wait_ce_success_after_pending(fake):
    fake.ce_sequence["T1"] = ["PENDING", "IN_PROGRESS", "SUCCESS"]
    assert sonar.wait_ce("T1", timeout=30, client=fake.client, sleep=lambda _s: None) == "SUCCESS"


@pytest.mark.parametrize("final", ["FAILED", "CANCELED"])
def test_req037_wait_ce_failed_or_canceled(fake, final):
    fake.ce_sequence["T2"] = ["IN_PROGRESS", final]
    assert sonar.wait_ce("T2", timeout=30, client=fake.client, sleep=lambda _s: None) == final


def test_req037_wait_ce_timeout_uses_cap(fake):
    fake.ce_sequence["T3"] = ["IN_PROGRESS"]
    clock = {"now": 0.0}

    def fake_sleep(seconds):
        clock["now"] += seconds

    status = sonar.wait_ce("T3", timeout=600, client=fake.client, sleep=fake_sleep, clock=lambda: clock["now"], interval=5)
    assert status == "TIMEOUT" and 600 <= clock["now"] < 620


def test_wait_ce_default_cap_is_600_seconds():
    assert sonar.CE_TIMEOUT_SECONDS == 600 and sonar.MAX_ITEMS == 10000


def test_ce_failure_reason_names_task_and_status():
    assert "AZ-1" in sonar.ce_failure_reason("AZ-1", "FAILED") and "FAILED" in sonar.ce_failure_reason("AZ-1", "FAILED")
    assert "TIMEOUT" in sonar.ce_failure_reason("AZ-1", "TIMEOUT") and "600" in sonar.ce_failure_reason("AZ-1", "TIMEOUT")


def test_read_report_task(tmp_path):
    assert sonar.read_report_task(FIXTURES / "report-task.txt")["ceTaskId"] == "AZ-task-1"
    with pytest.raises(sonar.SonarError, match="report-task"):
        sonar.read_report_task(tmp_path / "missing.txt")
    (tmp_path / "bad.txt").write_text("projectKey=x\n")
    with pytest.raises(sonar.SonarError, match="ceTaskId"):
        sonar.read_report_task(tmp_path / "bad.txt")


# --- 프로젝트 보장, 키, URL --------------------------------------------------------------------------
def test_ensure_project_creates_once(fake):
    sonar.ensure_project(KEY, client=fake.client)
    sonar.ensure_project(KEY, client=fake.client)
    creates = [r for r in fake.requests if r[1] == "/api/projects/create"]
    assert len(creates) == 1 and KEY in fake.projects


def test_project_key_isolated_for_test_prefix():
    assert sonar.project_key_for(KEY, "") == KEY
    assert sonar.project_key_for(KEY, "_test/abc123/") == f"{KEY}-test-abc123"
    assert sonar.project_key_for(KEY, "_test/abc123") == f"{KEY}-test-abc123"


def test_base_url_override_only_in_test_runs():
    env = {"TD_DOMAIN": "example.org", "TD_SONAR_URL_OVERRIDE": "http://127.0.0.1:1"}
    assert sonar.base_url(env) == "https://sonar.example.org"  # TD_SITE_PREFIX가 없으면 주입을 무시한다
    assert sonar.base_url({**env, "TD_SITE_PREFIX": "_test/x/"}) == "http://127.0.0.1:1"
    with pytest.raises(sonar.SonarError):
        sonar.base_url({})


def test_status_up_reports_down_and_unreachable(fake):
    assert sonar.status_up(fake.url) is None
    fake.status = "STARTING"
    assert "STARTING" in sonar.status_up(fake.url)
    assert sonar.status_up("http://127.0.0.1:1", timeout=2) is not None


def test_redact_removes_token():
    assert "squ_secret" not in sonar.redact("boom squ_secret end", "squ_secret")
    assert sonar.redact("plain", None) == "plain"


# --- 렌더링 ---------------------------------------------------------------------------------
def test_render_writes_html_with_links_and_gate(fake, tmp_path):
    fake.issue_total, fake.hotspot_total = 12, 3
    doc = sonar.export(KEY, client=fake.client, ce_task_id="AZ-task-1")
    html_path = sonar.render(doc, tmp_path)
    text = html_path.read_text()
    assert html_path.name == "sonar.html" and (tmp_path / "app.css").is_file()
    assert "<title>Sonar 품질 결과</title>" in text and "ERROR" in text
    assert doc["issues"]["items"][0]["link"] in text.replace("&amp;", "&") and "ISS-11" in text
    assert "41.7" in text


def test_render_marks_truncation(fake, tmp_path):
    fake.issue_total = 10050
    doc = sonar.export(KEY, client=fake.client)
    text = sonar.render(doc, tmp_path, css_href="../x.css", copy_css=False).read_text()
    assert "10050" in text and "10000" in text and 'href="../x.css"' in text and not (tmp_path / "site.css").exists()


# --- 리뷰 보강: 4xx 즉시 실패, 5xx 재시도, resolved=false ---------------------------------------------
def test_wait_ce_4xx_fails_immediately_with_error(fake):
    fake.ce_errors["T4"] = 401
    calls = []
    with pytest.raises(sonar.SonarError, match="HTTP 401") as info:
        sonar.wait_ce("T4", timeout=600, client=fake.client, sleep=calls.append)
    assert info.value.http_status == 401 and calls == [], "4xx는 재시도하지 않는다"
    assert len([r for r in fake.requests if r[1] == "/api/ce/task"]) == 1


def test_wait_ce_5xx_is_retried_until_timeout(fake):
    fake.ce_errors["T5"] = 503
    clock = {"now": 0.0}
    status = sonar.wait_ce("T5", timeout=20, client=fake.client, interval=5,
                           sleep=lambda s: clock.__setitem__("now", clock["now"] + s), clock=lambda: clock["now"])
    assert status == "TIMEOUT" and len([r for r in fake.requests if r[1] == "/api/ce/task"]) > 2


def test_ce_failure_reason_for_poll_error_has_task_and_detail():
    reason = sonar.ce_failure_reason("AZ-9", "ERROR", "HTTP 401 GET /api/ce/task")
    assert "AZ-9" in reason and "HTTP 401" in reason


def test_export_issue_search_excludes_resolved(fake):
    fake.issue_total = 2
    sonar.export(KEY, client=fake.client)
    issue_calls = [q for _m, p, q, _a in fake.requests if p == "/api/issues/search"]
    assert issue_calls and all(q.get("resolved") == ["false"] for q in issue_calls)


# --- 리뷰 보강: 정리가 SONAR_TOKEN을 지워도 사유에 토큰이 남지 않는다(S11 사유 가리기) -------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]


def _bash_with_fake_ssh(tmp_path, script: str, ssh_ok: bool = True) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ssh = bin_dir / "ssh"
    ssh.write_text("#!/usr/bin/env bash\n" + ("echo 0\n" if ssh_ok else "exit 255\n"))
    ssh.chmod(ssh.stat().st_mode | stat.S_IXUSR)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(PATH=f"{bin_dir}:{os.environ['PATH']}", TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(tmp_path),
               TD_RUN_DIR=str(tmp_path), TD_LIGHTSAIL_IP="203.0.113.1", TD_SSH_KEY_PATH="/nonexistent")
    header = (f'source "{REPO_ROOT}/pipeline/lib/common.sh"\nsource "{REPO_ROOT}/pipeline/lib/env.sh"\n'
              f'source "{REPO_ROOT}/pipeline/lib/sonar-token.sh"\n')
    return subprocess.run(["bash", "-c", header + script], capture_output=True, text=True, env=env, timeout=60)


def test_revoke_unsets_token_but_reason_stays_redacted(tmp_path):
    done = _bash_with_fake_ssh(tmp_path, '''
_TD_SONAR_ISSUED_RUN=r1
export SONAR_TOKEN=squ_secretvalue123
td_sonar_revoke_redact "scan failed: bad squ_secretvalue123 here"; echo "rc=$?"
echo "token_after=[${SONAR_TOKEN:-}]"
echo "reason=$TD_SONAR_REASON_OUT"
''')
    assert "rc=0" in done.stdout and "token_after=[]" in done.stdout, done.stdout + done.stderr
    assert "squ_secretvalue123" not in done.stdout and "reason=scan failed: bad <token> here" in done.stdout


def test_failed_revoke_text_is_redacted_too(tmp_path):
    done = _bash_with_fake_ssh(tmp_path, '''
_TD_SONAR_ISSUED_RUN=r1
export SONAR_TOKEN=squ_secretvalue123
td_sonar_revoke_redact "reason squ_secretvalue123"; echo "rc=$?"
echo "reason=$TD_SONAR_REASON_OUT"
''', ssh_ok=False)
    out = done.stdout + done.stderr
    assert "rc=1" in done.stdout and "토큰 잔존 가능" in done.stdout and "squ_secretvalue123" not in out, out
