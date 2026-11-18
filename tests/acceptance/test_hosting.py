"""REQ-053 / REQ-069: 정적 호스팅 인프라와 Route53 안전장치 (Int).

Task 10이 게시 후 검사(REQ 추가)를 이 파일에 덧붙인다.
"""
import http.client
import json
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

from td import route53

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_WORK = REPO_ROOT / "work" / "infra"


def _allow(domain: str) -> list[str]:
    return [f"reports.{domain}.", f"_*.reports.{domain}."]


def _zone_id(local_env) -> str:
    return route53.find_zone_id(local_env["TD_DOMAIN"], boto3.client("route53"))


def _get_status(url: str) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_req053_route53_preserved(local_env):
    before_file = INFRA_WORK / "route53-before.json"
    after_file = INFRA_WORK / "route53-after.json"
    assert before_file.exists(), "apply.sh가 만든 route53-before.json이 없다"
    assert after_file.exists(), "apply.sh가 만든 route53-after.json이 없다"
    before = json.loads(before_file.read_text())
    after = json.loads(after_file.read_text())
    allow = _allow(local_env["TD_DOMAIN"])

    # 1) 파일 비교: reports와 ACM 검증 CNAME 외에는 차이가 없다.
    assert route53.compare(before, after, allow) == []

    # 2) 현재 zone에도 적용 전 RRSet이 모두 그대로 있다.
    current = route53.snapshot(_zone_id(local_env), boto3.client("route53"))
    assert route53.compare(before, current, allow) == []
    kept = {(r["Name"], r["Type"]) for r in current}
    assert {(r["Name"], r["Type"]) for r in before} <= kept
    assert any(r["Name"] == f"reports.{local_env['TD_DOMAIN']}." for r in current), "reports 레코드가 없다"


def test_req053_conflict_aborts_with_stub():
    client = boto3.client("route53", region_name="us-east-1",
                          aws_access_key_id="x", aws_secret_access_key="x")
    existing = {"Name": "reports.example.test.", "Type": "A", "TTL": 60,
                "ResourceRecords": [{"Value": "192.0.2.1"}]}
    with Stubber(client) as stubber:
        stubber.add_response("get_hosted_zone", {
            "HostedZone": {"Id": "/hostedzone/Z1", "Name": "example.test.", "CallerReference": "c"},
            "DelegationSet": {"NameServers": ["ns.example.test"]}}, {"Id": "Z1"})
        stubber.add_response("list_resource_record_sets", {
            "ResourceRecordSets": [existing], "IsTruncated": False, "MaxItems": "300"}, {"HostedZoneId": "Z1"})
        with pytest.raises(route53.Route53Conflict, match="reports"):
            route53.check_conflict("Z1", ["reports"], client)


def test_req053_no_conflict_when_name_free():
    client = boto3.client("route53", region_name="us-east-1",
                          aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(client) as stubber:
        stubber.add_response("get_hosted_zone", {
            "HostedZone": {"Id": "/hostedzone/Z1", "Name": "example.test.", "CallerReference": "c"},
            "DelegationSet": {"NameServers": ["ns.example.test"]}}, {"Id": "Z1"})
        stubber.add_response("list_resource_record_sets", {
            "ResourceRecordSets": [{"Name": "www.example.test.", "Type": "A", "TTL": 60,
                                    "ResourceRecords": [{"Value": "192.0.2.1"}]}],
            "IsTruncated": False, "MaxItems": "300"}, {"HostedZoneId": "Z1"})
        route53.check_conflict("Z1", ["reports"], client)


def test_req069_s3_direct_forbidden(local_env):
    bucket = f"td-reports-{local_env['TD_AWS_ACCOUNT_ID']}"
    status = _get_status(f"https://{bucket}.s3.ap-northeast-2.amazonaws.com/index.html")
    assert status == 403


def _resolve_authoritative(host: str, zone_id: str) -> str:
    """Route53 권한 응답에서 A 레코드를 얻는다(로컬 리졸버의 NXDOMAIN 음성 캐시를 우회)."""
    answer = boto3.client("route53").test_dns_answer(HostedZoneId=zone_id, RecordName=host, RecordType="A")
    ips = [value for value in answer["RecordData"] if value[:1].isdigit()]
    assert ips, f"{host}의 A 응답이 없다: {answer['ResponseCode']}"
    return ips[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS 검증과 SNI는 호스트 이름으로 하되 연결은 지정한 IP로 한다."""

    def __init__(self, host, ip, **kwargs):
        super().__init__(host, **kwargs)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)


def test_hosting_reports_domain_serves_https(local_env):
    host = f"reports.{local_env['TD_DOMAIN']}"
    try:
        socket.getaddrinfo(host, 443)
        ip = None
    except socket.gaierror:  # 방금 만든 이름이면 로컬 리졸버가 NXDOMAIN을 캐시했을 수 있다
        ip = _resolve_authoritative(host, _zone_id(local_env))
    if ip is None:
        assert _get_status(f"https://{host}/") == 200
        return
    connection = _PinnedHTTPSConnection(host, ip, timeout=30)
    connection.request("GET", "/")
    assert connection.getresponse().status == 200
