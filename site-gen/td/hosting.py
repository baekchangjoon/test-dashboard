"""호스팅 비교(S13): TTFB·홈 전송 측정, hosting.json 조립과 스키마, hosting.html 렌더링.

설계 §13.8. 측정은 게시 직후 로컬에서 하고, 결과는 `<prefix>hosting.json`/`hosting.html`(no-cache)로 게시한다.
TTFB 정의: 새 연결(TCP+TLS 포함)을 맺고 요청을 보낸 시각부터 응답 상태줄과 헤더를 받은 시각(첫 응답 바이트)까지.
방금 만든 DNS 이름은 로컬 리졸버가 NXDOMAIN을 캐시할 수 있고 리졸버마다 응답도 달라, 두 호스트 모두 항상 Route53 권한 응답의
A 레코드 IP로 연결을 고정해 측정한다(TLS 검증과 SNI, Host 헤더는 호스트 이름 기준 그대로). IP 값은 게시하지 않고
고정했다는 사실과 출처(`route53-authoritative`)만 hosting.json에 남긴다.
"""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

SAMPLES = 10
TIMEOUT_SECONDS = 10
MIN_OK_SAMPLES = 7  # 이보다 성공 표본이 적으면 중앙값은 null이고 S13은 degraded다
SCHEMA_PATH = Path(__file__).parent / "schemas" / "hosting.schema.json"
QUALITATIVE_PATH = Path(__file__).resolve().parents[2] / "infra" / "hosting-qualitative.yaml"
HOST_NAMES = ("reports", "dash")


@dataclass(frozen=True)
class Ttfb:
    median_ms: float | None
    ok: int
    failed: int
    samples_ms: tuple[float, ...] = field(default=(), compare=False)


@dataclass(frozen=True)
class HomeTransfer:
    ms: float | None
    bytes: int | None


def median_ttfb(values_ms, min_ok: int = MIN_OK_SAMPLES) -> float | None:
    """성공 표본의 중앙값(짝수면 가운데 두 값의 평균). 성공 표본이 min_ok개 미만이면 None."""
    values = sorted(values_ms)
    if len(values) < min_ok:
        return None
    middle = len(values) // 2
    return float(values[middle]) if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


class _PinnedMixin:
    """연결은 지정한 IP로 하고 나머지(Host, SNI, 인증서 검증)는 호스트 이름을 쓴다."""
    _ip: str | None = None

    def _open_socket(self):
        return socket.create_connection((self._ip or self.host, self.port), self.timeout)


class _PinnedHTTP(_PinnedMixin, http.client.HTTPConnection):
    def __init__(self, host, ip, **kwargs):
        super().__init__(host, **kwargs)
        self._ip = ip

    def connect(self):
        self.sock = self._open_socket()


class _PinnedHTTPS(_PinnedMixin, http.client.HTTPSConnection):
    def __init__(self, host, ip, **kwargs):
        super().__init__(host, **kwargs)
        self._ip = ip

    def connect(self):
        self.sock = ssl.create_default_context().wrap_socket(self._open_socket(), server_hostname=self.host)


def _connection(url: str, timeout: float, connect_ip: str | None):
    parts = urlsplit(url)
    host, port = parts.hostname, parts.port
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    cls = _PinnedHTTPS if parts.scheme == "https" else _PinnedHTTP
    return cls(host, connect_ip, port=port, timeout=timeout), path


PIN_SOURCE = "route53-authoritative"


def resolve_ip(host: str, domain: str, zone_id: str | None = None, client=None) -> str:
    """Route53 권한 응답(test_dns_answer)의 A 레코드 IP. IP가 아닌 RecordData(CNAME 등)는 거르고, A 응답이 없으면 RuntimeError."""
    if client is None:
        import boto3
        client = boto3.client("route53")
    if zone_id is None:
        from td import route53
        zone_id = route53.find_zone_id(domain, client)
    answer = client.test_dns_answer(HostedZoneId=zone_id, RecordName=host, RecordType="A")
    ips = [value for value in answer.get("RecordData", []) if value[:1].isdigit()]
    if not ips:
        raise RuntimeError(f"{host}의 Route53 A 응답이 없다(응답 코드 {answer.get('ResponseCode')})")
    return ips[0]


def _first_byte_ms(url: str, timeout: float, connect_ip: str | None) -> float | None:
    """한 번 요청해 첫 응답 바이트(헤더 수신)까지 ms. 오류, timeout, 상태 400 이상이면 None."""
    connection, path = _connection(url, timeout, connect_ip)
    try:
        started = time.perf_counter()
        connection.request("GET", path, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        elapsed = (time.perf_counter() - started) * 1000
        response.read()
        return elapsed if response.status < 400 else None
    except (OSError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def measure(url: str, n: int = SAMPLES, timeout: float = TIMEOUT_SECONDS, connect_ip: str | None = None) -> Ttfb:
    """사전 요청 1회(warm, 집계 제외) 뒤 n회 측정한다. 성공 표본만으로 중앙값을 내고 7개 미만이면 median_ms는 None."""
    _first_byte_ms(url, timeout, connect_ip)
    values: list[float] = []
    failed = 0
    for _ in range(n):
        elapsed = _first_byte_ms(url, timeout, connect_ip)
        if elapsed is None:
            failed += 1
        else:
            values.append(elapsed)
    return Ttfb(median_ms=median_ttfb(values), ok=len(values), failed=failed, samples_ms=tuple(values))


def measure_home(url: str, timeout: float = TIMEOUT_SECONDS, connect_ip: str | None = None) -> HomeTransfer:
    """홈 HTML을 끝까지 받는 데 걸린 시간(ms)과 본문 바이트. 실패하면 둘 다 None."""
    connection, path = _connection(url, timeout, connect_ip)
    try:
        started = time.perf_counter()
        connection.request("GET", path, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        body = response.read()
        elapsed = (time.perf_counter() - started) * 1000
        if response.status >= 400:
            return HomeTransfer(None, None)
        return HomeTransfer(ms=elapsed, bytes=len(body))
    except (OSError, http.client.HTTPException):
        return HomeTransfer(None, None)
    finally:
        connection.close()


# --- 문서 ---------------------------------------------------------------------------------
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def load_qualitative(path=QUALITATIVE_PATH) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text())


DEPLOY_BASIS = {
    "reports": "S3 업로드 시작부터 인덱스 재생성 업로드까지(조건부 PUT, 검증, _COMPLETE 포함)",
    "dash": "미러에서 Lightsail로 rsync 두 번(새 파일, 인덱스)에 걸린 시간",
}
HOME_BASIS = ("홈 HTML을 끝까지 받는 데 걸린 시간의 단일 표본(중앙값이 아님, 새 연결). "
              "본문 읽기가 중간에 실패하면 실패로 세어 값이 없다.")


def build_document(*, sut: str, run_id: str, generated_at: str, measures: dict, timings: dict, qualitative: dict,
                   n: int = SAMPLES, timeout: float = TIMEOUT_SECONDS) -> dict:
    """호스트별 측정(`measures[name] = {url, ttfb: Ttfb, home: HomeTransfer}`), 게시 timings, 정성 yaml을 hosting.json으로 합친다."""
    deploy_seconds = {"reports": timings.get("uploadSeconds"), "dash": timings.get("rsyncSeconds")}
    hosts: dict = {}
    for name in HOST_NAMES:
        measured, ttfb, home = measures[name], measures[name]["ttfb"], measures[name]["home"]
        memory = None
        if name == "dash":
            memory = {"beforeMb": timings.get("memBeforeMb"), "afterMb": timings.get("memAfterMb"), "unit": "MB", "metric": "available"}
        info = qualitative["hosts"][name]
        hosts[name] = {
            "label": info["label"],
            "quantitative": {
                "deploy": {"seconds": deploy_seconds[name], "unit": "s", "basis": DEPLOY_BASIS[name]},
                "ttfb": {"medianMs": None if ttfb.median_ms is None else round(ttfb.median_ms, 1), "unit": "ms", "samples": n,
                         "ok": ttfb.ok, "failed": ttfb.failed, "timeoutSeconds": timeout, "url": measured["url"], "warm": True},
                "homeTransfer": {"ms": None if home.ms is None else round(home.ms, 1), "unit": "ms", "bytes": home.bytes,
                                 "url": measured["url"], "basis": HOME_BASIS},
                "connection": {"pinned": bool(measured.get("pinned")), "source": PIN_SOURCE if measured.get("pinned") else None},
                "memory": memory,
            },
            "qualitative": {"cost": info["cost"], "operations": info["operations"], "failureScope": info["failureScope"]},
        }
    return {"schemaVersion": 1, "generatedAt": generated_at, "runId": run_id, "sut": sut, "hosts": hosts}


def measurement_status(doc: dict) -> tuple[str, str | None]:
    """TTFB 중앙값이 null인 호스트가 있으면 ("failed", 사유). S13은 이를 degraded로 반영한다."""
    problems = []
    for name in HOST_NAMES:
        ttfb = doc["hosts"][name]["quantitative"]["ttfb"]
        if ttfb["medianMs"] is None:
            problems.append(f"{name} TTFB 성공 표본 {ttfb['ok']}/{ttfb['samples']} (<{MIN_OK_SAMPLES})")
    return ("failed", "; ".join(problems)) if problems else ("passed", None)


def render_html(doc: dict | None, css_href: str = "static/v2/app.css", reason: str | None = None) -> str:
    """doc가 None이면 "측정 없음" 안내 페이지(홈의 링크가 항상 열리게 한다). 접두 루트의 `hosting.html`이라 공통 띠는 없다."""
    from td.site import pages
    return pages.jinja_env().get_template("hosting.html.j2").render(doc=doc, css_href=css_href,
                                                                    static_href=pages.static_href_of(css_href), reason=reason)


def check_document(doc: dict) -> None:
    import jsonschema
    jsonschema.validate(doc, load_schema())
