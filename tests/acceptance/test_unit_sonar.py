"""td.sonar 단위 테스트(REQ-037 Unit): 가짜 Sonar API(로컬 HTTP 서버)로 페이지 순회, 상한, CE 폴링, 프로젝트 보장, 렌더링을 본다."""
import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from jsonschema import Draft202012Validator

from td import sonar

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sonar-api"
SCHEMA = Path(__file__).resolve().parents[2] / "site-gen" / "td" / "schemas" / "sonar.schema.json"
KEY = "spring-petclinic-td"


class FakeSonar:
    """상태를 가진 가짜 Sonar. issues/hotspots는 total 건을 즉석에서 만들어 페이지 단위로 돌려준다."""

    def __init__(self):
        self.status = "UP"
        self.projects: set[str] = set()
        self.issue_total = 0
        self.hotspot_total = 0
        self.ce_sequence: dict[str, list[str]] = {}
        self.requests: list[tuple[str, str, dict, str | None]] = []  # (method, path, query, authorization)
        self.max_ps_seen = 0

    def handle(self, method: str, path: str, query: dict, auth: str | None, body: dict) -> tuple[int, dict]:
        self.requests.append((method, path, query, auth))
        if path == "/api/system/status":
            return 200, {"id": "x", "version": "26.5", "status": self.status}
        if path == "/api/projects/search":
            wanted = query.get("projects", [""])[0]
            return 200, {"components": [{"key": wanted}] if wanted in self.projects else []}
        if path == "/api/projects/create" and method == "POST":
            self.projects.add(body["project"][0])
            return 200, {"project": {"key": body["project"][0]}}
        if path == "/api/ce/task":
            task_id = query["id"][0]
            states = self.ce_sequence.get(task_id, ["SUCCESS"])
            status = states.pop(0) if len(states) > 1 else states[0]
            return 200, {"task": {"id": task_id, "status": status, "analysisId": "AN-1", "componentKey": KEY}}
        if path == "/api/qualitygates/project_status":
            return 200, json.loads((FIXTURES / "project_status.json").read_text())
        if path == "/api/measures/component":
            return 200, json.loads((FIXTURES / "measures.json").read_text())
        if path in ("/api/issues/search", "/api/hotspots/search"):
            return 200, self._page(path, query)
        return 404, {"errors": [{"msg": f"unknown {path}"}]}

    def _page(self, path: str, query: dict) -> dict:
        page, size = int(query.get("p", ["1"])[0]), int(query.get("ps", ["100"])[0])
        self.max_ps_seen = max(self.max_ps_seen, size)
        issues = path.endswith("issues/search")
        total = self.issue_total if issues else self.hotspot_total
        if page * size > 10000 and page > 20 or size > 500:
            return {"errors": [{"msg": "Can return only the first 10000 results"}]}
        start = (page - 1) * size
        rows = []
        for index in range(start, min(total, start + size, 10000)):
            if issues:
                rows.append({"key": f"ISS-{index}", "rule": "java:S1135", "severity": "MINOR", "type": "CODE_SMELL",
                             "component": f"{KEY}:src/main/java/A{index % 7}.java", "line": index % 300 + 1,
                             "message": f"issue {index}", "status": "OPEN"})
            else:
                rows.append({"key": f"HS-{index}", "ruleKey": "java:S5122", "vulnerabilityProbability": "MEDIUM",
                             "component": f"{KEY}:src/main/java/B.java", "line": index % 50 + 1,
                             "message": f"hotspot {index}", "status": "TO_REVIEW"})
        paging = {"pageIndex": page, "pageSize": size, "total": total}
        return {"total": total, "p": page, "ps": size, "paging": paging, ("issues" if issues else "hotspots"): rows}


@pytest.fixture
def fake():
    state = FakeSonar()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self, method):
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = parse_qs(self.rfile.read(length).decode()) if length else {}
            status, payload = state.handle(method, parts.path, parse_qs(parts.query), self.headers.get("Authorization"), body)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = lambda self: self._serve("GET")  # noqa: E731
        do_POST = lambda self: self._serve("POST")  # noqa: E731

        def log_message(self, *args):
            pass

    class QuickServer(ThreadingHTTPServer):
        def server_bind(self):  # HTTPServer.server_bind의 getfqdn(역방향 DNS)이 macOS에서 수십 초 걸린다
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = "127.0.0.1", self.server_address[1]

    server = QuickServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    state.client = sonar.SonarClient(state.url, token="squ_unit_token_value")
    yield state
    server.shutdown()
    server.server_close()


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
    assert html_path.name == "sonar.html" and (tmp_path / "site.css").is_file()
    assert "<title>Sonar 품질 결과</title>" in text and "ERROR" in text
    assert doc["issues"]["items"][0]["link"] in text.replace("&amp;", "&") and "ISS-11" in text
    assert "41.7" in text


def test_render_marks_truncation(fake, tmp_path):
    fake.issue_total = 10050
    doc = sonar.export(KEY, client=fake.client)
    text = sonar.render(doc, tmp_path, css_href="../x.css", copy_css=False).read_text()
    assert "10050" in text and "10000" in text and 'href="../x.css"' in text and not (tmp_path / "site.css").exists()
