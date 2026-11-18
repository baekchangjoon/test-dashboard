"""가짜 Sonar API(로컬 HTTP 서버). 단위 테스트와 단계 수준 주입 테스트가 함께 쓴다."""
import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sonar-api"
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
        self.ce_errors: dict[str, int] = {}  # taskId -> HTTP 오류 코드

    def handle(self, method: str, path: str, query: dict, auth: str | None, body: dict) -> tuple[int, dict]:
        self.requests.append((method, path, query, auth))
        if path == "/api/system/status":
            return 200, {"id": "x", "version": "26.5", "status": self.status}
        if path == "/api/authentication/validate":
            return 200, {"valid": True}
        if path == "/api/projects/search":
            wanted = query.get("projects", [""])[0]
            return 200, {"components": [{"key": wanted}] if wanted in self.projects else []}
        if path == "/api/projects/create" and method == "POST":
            self.projects.add(body["project"][0])
            return 200, {"project": {"key": body["project"][0]}}
        if path == "/api/ce/task":
            task_id = query["id"][0]
            if task_id in self.ce_errors:
                return self.ce_errors[task_id], {"errors": [{"msg": "injected"}]}
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


def start_fake_sonar():
    """(FakeSonar 상태, 서버 종료 함수). state.url로 접근한다."""
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"

    def stop():
        server.shutdown()
        server.server_close()

    return state, stop
