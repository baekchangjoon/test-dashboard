"""Task 11 단위: TTFB 측정(중앙값 규칙, 첫 바이트 시각, 실패 표본), hosting 문서 조립과 스키마, S13 상태 규칙."""
import datetime
import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import pytest
import yaml

from td import hosting, publish

REPO_ROOT = Path(__file__).resolve().parents[2]


class Script:
    """요청마다 (상태, 헤더까지 지연, 본문 전송 지연)을 순서대로 돌려주는 로컬 서버."""

    def __init__(self, steps, default=(200, 0.0, 0.0)):
        self.steps, self.default, self.lock, self.count = list(steps), default, threading.Lock(), 0
        script = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with script.lock:
                    script.count += 1
                    status, head_delay, body_delay = script.steps.pop(0) if script.steps else script.default
                time.sleep(head_delay)
                body = b"<html>" + b"x" * 1000 + b"</html>"
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body[:500])
                    time.sleep(body_delay)
                    self.wfile.write(body[500:])
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/index.html"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def script_server():
    servers = []

    def make(steps, **kwargs):
        servers.append(Script(steps, **kwargs))
        return servers[-1]
    yield make
    for server in servers:
        server.close()


def test_unit_ttfb_median():
    assert hosting.median_ttfb([1, 2, 3, 4, 5, 6, 7]) == 4          # 홀수
    assert hosting.median_ttfb([4, 1, 3, 2, 5, 6, 7, 8]) == 4.5     # 짝수: 가운데 두 값의 평균
    assert hosting.median_ttfb([1, 2, 3, 4, 5, 6]) is None          # 성공 6개 < 7 -> None
    assert hosting.median_ttfb([]) is None
    assert hosting.median_ttfb([10] * 10) == 10


def test_unit_measure_all_ok_counts_warmup_separately(script_server):
    server = script_server([])
    ttfb = hosting.measure(server.url, n=10, timeout=5)
    assert (ttfb.ok, ttfb.failed) == (10, 0) and ttfb.median_ms is not None
    assert server.count == 11, "사전(warm) 요청 1회 + 표본 10회"


def test_unit_measure_six_ok_is_none(script_server):
    server = script_server([(200, 0, 0)] + [(500, 0, 0)] * 4)  # warm-up 1 + 실패 4, 이후 기본 200 6개
    ttfb = hosting.measure(server.url, n=10, timeout=5)
    assert (ttfb.ok, ttfb.failed) == (6, 4)
    assert ttfb.median_ms is None


def test_unit_measure_seven_ok_has_value(script_server):
    server = script_server([(200, 0, 0)] + [(500, 0, 0)] * 3)
    ttfb = hosting.measure(server.url, n=10, timeout=5)
    assert (ttfb.ok, ttfb.failed) == (7, 3)
    assert ttfb.median_ms is not None


def test_unit_measure_timeout_sample_is_failure(script_server):
    server = script_server([(200, 0, 0)] + [(200, 1.5, 0)] * 2)  # 표본 2개가 timeout(0.5초) 초과
    ttfb = hosting.measure(server.url, n=10, timeout=0.5)
    assert (ttfb.ok, ttfb.failed) == (8, 2)


def test_unit_ttfb_is_first_byte_not_full_transfer(script_server):
    server = script_server([], default=(200, 0.3, 0.6))
    ttfb = hosting.measure(server.url, n=7, timeout=5)
    assert ttfb.median_ms is not None and 250 <= ttfb.median_ms < 700, ttfb
    home = hosting.measure_home(server.url, timeout=5)
    assert home.ms is not None and home.ms >= 850, "전체 전송은 본문 지연까지 포함한다"
    assert home.bytes == len(b"<html>" + b"x" * 1000 + b"</html>")


def test_unit_measure_pinned_ip_keeps_host_header(script_server):
    server = script_server([])
    url = f"http://never-resolves.invalid:{server.port}/index.html"
    assert hosting.measure(url, n=7, timeout=5, connect_ip="127.0.0.1").ok == 7


def test_unit_measure_unreachable_is_failures_not_exception():
    ttfb = hosting.measure("http://127.0.0.1:1/index.html", n=7, timeout=1)
    assert (ttfb.ok, ttfb.failed, ttfb.median_ms) == (0, 7, None)


# --- 문서 조립 -----------------------------------------------------------------------------
def _measures(ok=10, failed=0, median=42.0):
    ttfb = hosting.Ttfb(median_ms=median, ok=ok, failed=failed)
    home = hosting.HomeTransfer(ms=120.5, bytes=2048)
    return {name: {"url": f"https://{name}.example.com/p/index.html", "ttfb": ttfb, "home": home, "pinned": True}
            for name in ("reports", "dash")}


def _build(measures=None, **kw):
    qualitative = hosting.load_qualitative(REPO_ROOT / "infra" / "hosting-qualitative.yaml")
    return hosting.build_document(
        sut="petclinic", run_id="20261119-000000Z-b6f9393-manual-deadbeef", generated_at="2026-11-19T00:00:00Z",
        measures=measures or _measures(), timings={"uploadSeconds": 3.21, "rsyncSeconds": 1.5, "memBeforeMb": 900, "memAfterMb": 880},
        qualitative=qualitative, **kw)


def test_unit_document_matches_schema():
    doc = _build()
    jsonschema.validate(doc, hosting.load_schema())
    assert doc["hosts"]["reports"]["quantitative"]["deploy"] == {"seconds": 3.21, "unit": "s", "basis": doc["hosts"]["reports"]["quantitative"]["deploy"]["basis"]}
    assert doc["hosts"]["dash"]["quantitative"]["deploy"]["seconds"] == 1.5
    ttfb = doc["hosts"]["dash"]["quantitative"]["ttfb"]
    assert ttfb["medianMs"] == 42.0 and ttfb["unit"] == "ms" and ttfb["samples"] == 10 and ttfb["warm"] is True
    assert ttfb["ok"] == 10 and ttfb["failed"] == 0 and ttfb["timeoutSeconds"] == 10 and ttfb["url"].startswith("https://dash.")
    assert doc["hosts"]["dash"]["quantitative"]["memory"] == {"beforeMb": 900, "afterMb": 880, "unit": "MB", "metric": "available"}
    assert doc["hosts"]["reports"]["quantitative"]["memory"] is None, "메모리는 Lightsail만"
    for name in ("reports", "dash"):
        quant = doc["hosts"][name]["quantitative"]
        assert quant["connection"] == {"pinned": True, "source": "route53-authoritative"}
        assert "단일 표본" in quant["homeTransfer"]["basis"] and "실패" in quant["homeTransfer"]["basis"]
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", json.dumps(doc)), "IP 값은 게시하지 않는다"


def test_unit_document_null_ttfb_valid_and_degraded():
    measures = _measures(ok=6, failed=4, median=None)
    doc = _build(measures)
    jsonschema.validate(doc, hosting.load_schema())
    assert doc["hosts"]["reports"]["quantitative"]["ttfb"]["medianMs"] is None
    status, reason = hosting.measurement_status(doc)
    assert status == "failed" and "reports" in reason and "TTFB" in reason
    assert hosting.measurement_status(_build())[0] == "passed"


def test_unit_schema_rejects_missing_values():
    doc = _build()
    del doc["hosts"]["dash"]["quantitative"]["ttfb"]["unit"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, hosting.load_schema())
    doc = _build()
    doc["hosts"]["reports"]["qualitative"]["cost"]["source"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, hosting.load_schema())
    doc = _build()
    doc["hosts"]["dash"]["qualitative"]["failureScope"] = ""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, hosting.load_schema())


def test_unit_qualitative_yaml_complete():
    raw = yaml.safe_load((REPO_ROOT / "infra" / "hosting-qualitative.yaml").read_text())
    for host in ("reports", "dash"):
        item = raw["hosts"][host]
        cost = item["cost"]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cost["asOf"]) and datetime.date.fromisoformat(cost["asOf"])
        for field in ("region", "formula", "priceBasis"):
            assert str(cost[field]).strip(), (host, field)
        assert cost["source"] and all(s["url"].startswith("https://") for s in cost["source"])
        assert any(s["url"].startswith("https://aws.amazon.com/") for s in cost["source"])
        assert cost["assumptions"]
        assert str(item["operations"]).strip() and str(item["failureScope"]).strip()
    assert "Sonar" in raw["hosts"]["dash"]["failureScope"], "Lightsail은 Sonar와 장애 영역을 공유한다"
    assert raw["hosts"]["dash"]["cost"]["monthlyUsdIncremental"] == 0


def test_unit_html_shows_values_and_follows_site_style():
    doc = _build()
    html = hosting.render_html(doc)
    assert "<title>호스팅 방식 비교</title>" in html
    for needle in ("42.0", "120.5", "3.21", "900", "880", "Sonar", doc["hosts"]["dash"]["qualitative"]["cost"]["asOf"],
                   'href="static/v2/app.css"', "viewport", "단일 표본", "route53-authoritative"):
        assert needle in html, needle
    assert "var(--" in (REPO_ROOT / "site-gen/td/site/static/site.css").read_text()
    null_html = hosting.render_html(_build(_measures(ok=6, failed=4, median=None)))
    assert "측정 실패" in null_html or "—" in null_html


# --- resolve_ip(항상 Route53 권한 응답, boto3 스텁) --------------------------------------------
class StubRoute53:
    def __init__(self, record_data, code="NOERROR"):
        self.record_data, self.code, self.calls = record_data, code, []

    def test_dns_answer(self, **kwargs):
        self.calls.append(kwargs)
        return {"RecordData": self.record_data, "ResponseCode": self.code}


def test_unit_resolve_ip_filters_non_ip_record_data():
    client = StubRoute53(["d111.cloudfront.net.", "203.0.113.7", "203.0.113.8"])
    assert hosting.resolve_ip("reports.example.com", "example.com", zone_id="Z1", client=client) == "203.0.113.7"
    assert client.calls == [{"HostedZoneId": "Z1", "RecordName": "reports.example.com", "RecordType": "A"}]


def test_unit_resolve_ip_no_a_answer_raises_clear_error():
    with pytest.raises(RuntimeError, match=r"reports\.example\.com.*A 응답이 없다.*NXDOMAIN"):
        hosting.resolve_ip("reports.example.com", "example.com", zone_id="Z1", client=StubRoute53(["alias.cloudfront.net."], "NXDOMAIN"))
    with pytest.raises(RuntimeError, match="A 응답이 없다"):
        hosting.resolve_ip("dash.example.com", "example.com", zone_id="Z1", client=StubRoute53([]))


def test_unit_resolve_ip_always_queries_route53_even_if_local_dns_resolves(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [("x",)])  # 로컬 DNS가 풀려도 쓰지 않는다
    client = StubRoute53(["198.51.100.4"])
    assert hosting.resolve_ip("dash.example.com", "example.com", zone_id="Z1", client=client) == "198.51.100.4"
    assert len(client.calls) == 1


def test_unit_html_without_measurement_is_notice_page():
    html = hosting.render_html(None, reason="TD_DOMAIN이 설정돼 있지 않다")
    assert "<title>호스팅 방식 비교</title>" in html and "측정 없음" in html and "TD_DOMAIN" in html


# --- S13 상태 규칙 -------------------------------------------------------------------------
def _hosts(hosting_status=None):
    hosts = {"s3": {"status": "passed"}, "cloudfront": {"status": "passed"}, "lightsail": {"status": "passed"}}
    if hosting_status:
        hosts["hosting"] = {"status": hosting_status, "reason": "reports TTFB 성공 표본 6/10 (<7)"}
    return hosts


def test_unit_overall_status_hosting_measurement_degrades():
    assert publish.overall_status(_hosts()) == ("passed", None)
    assert publish.overall_status(_hosts("passed")) == ("passed", None)
    status, reason = publish.overall_status(_hosts("failed"))
    assert status == "degraded" and "hosting" in reason and "TTFB" in reason


def test_unit_overall_status_s3_failure_still_failed_with_hosting():
    hosts = _hosts("failed")
    hosts["s3"] = {"status": "failed", "reason": "x"}
    assert publish.overall_status(hosts)[0] == "failed"


# --- S13 hosting_phase(가짜 S3/CloudFront, 측정 대체) -------------------------------------------
from test_unit_publish import BUCKET, FakeS3, OkCloudFront, exec_env  # noqa: E402,F401  (fixture 재사용)


def _fake_measurer(ok=10):
    def measurer(url, connect_ip):
        median = 12.5 if ok >= 7 else None
        return hosting.Ttfb(median, ok, 10 - ok), hosting.HomeTransfer(33.3, 1234)
    return measurer


def _run(exec_env, monkeypatch, ok=10):
    run_id, run_dir, env, _ = exec_env
    env = {**env, "TD_DOMAIN": "example.com"}
    s3, cf = FakeS3(), OkCloudFront()
    monkeypatch.setattr(hosting, "resolve_ip", lambda host, domain, zone_id=None, client=None: "203.0.113.1")
    result = publish.Publication("sutx", run_id, run_dir, env, s3, cf, hosting_measurer=_fake_measurer(ok)).execute()
    return result, s3, cf, run_id


def test_unit_hosting_phase_publishes_json_html_no_cache_and_invalidates(exec_env, monkeypatch):
    result, s3, cf, _ = _run(exec_env, monkeypatch)
    assert result["status"] == "passed", result
    assert result["hosts"]["hosting"]["status"] == "passed"
    for name in ("hosting.json", "hosting.html"):
        obj = s3.objects[f"_test/u/{name}"]
        assert obj["CacheControl"] == "no-cache"
    doc = json.loads(s3.objects["_test/u/hosting.json"]["data"])
    jsonschema.validate(doc, hosting.load_schema())
    assert doc["hosts"]["dash"]["quantitative"]["ttfb"]["url"] == "https://dash.example.com/_test/u/index.html"
    assert doc["hosts"]["dash"]["quantitative"]["memory"]["afterMb"] == 99999999999  # ssh 스텁이 돌려준 available 값
    assert any(paths == ["/_test/u/hosting.html", "/_test/u/hosting.json"] for paths in cf.paths)
    cloudfront = result["hosts"]["cloudfront"]
    assert cloudfront["invalidationId"] and cloudfront["hostingInvalidationId"] and cloudfront["paths"] > 0, "앞선 무효화 정보를 보존한다"
    assert all(h["quantitative"]["connection"]["pinned"] for h in doc["hosts"].values())
    assert result["timings"]["rsyncSeconds"] is not None and result["timings"]["uploadSeconds"] >= 0
    assert "호스팅 방식 비교" in s3.objects["_test/u/hosting.html"]["data"].decode()


def test_unit_hosting_phase_null_ttfb_makes_s13_degraded_and_logged(exec_env, monkeypatch):
    result, s3, _, run_id = _run(exec_env, monkeypatch, ok=6)
    assert result["status"] == "degraded" and "hosting" in result["reason"] and "TTFB" in result["reason"]
    doc = json.loads(s3.objects["_test/u/hosting.json"]["data"])
    assert doc["hosts"]["reports"]["quantitative"]["ttfb"]["medianMs"] is None
    log = json.loads(s3.objects[f"_test/u/suts/sutx/publish-log/{run_id}.json"]["data"])
    assert log["status"] == "degraded" and log["hosts"]["hosting"]["status"] == "failed"
    assert result["hosts"]["s3"]["status"] == "passed"


def test_unit_hosting_phase_error_text_in_reason_and_notice_page_kept(exec_env, monkeypatch):
    run_id, run_dir, env, _ = exec_env
    env = {**env, "TD_DOMAIN": "example.com"}
    s3, cf = FakeS3(), OkCloudFront()

    def boom(host, domain, zone_id=None, client=None):
        raise RuntimeError(f"{host}의 Route53 A 응답이 없다(응답 코드 NXDOMAIN)")
    monkeypatch.setattr(hosting, "resolve_ip", boom)
    result = publish.Publication("sutx", run_id, run_dir, env, s3, cf, hosting_measurer=_fake_measurer()).execute()
    assert result["status"] == "degraded"
    reason = result["hosts"]["hosting"]["reason"]
    assert "RuntimeError" in reason and "NXDOMAIN" in reason and "reports" in reason and "dash" in reason
    doc = json.loads(s3.objects["_test/u/hosting.json"]["data"])
    assert not doc["hosts"]["dash"]["quantitative"]["connection"]["pinned"]


def test_unit_hosting_phase_missing_domain_writes_notice_page(exec_env):
    run_id, run_dir, env, _ = exec_env  # TD_DOMAIN 없음
    s3 = FakeS3()
    result = publish.Publication("sutx", run_id, run_dir, env, s3, OkCloudFront(), hosting_measurer=_fake_measurer()).execute()
    assert result["status"] == "degraded" and "TD_DOMAIN" in result["hosts"]["hosting"]["reason"]
    assert "측정 없음" in s3.objects["_test/u/hosting.html"]["data"].decode()
    assert "_test/u/hosting.json" not in s3.objects
