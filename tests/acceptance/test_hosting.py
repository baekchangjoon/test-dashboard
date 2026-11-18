"""REQ-053 / REQ-069: 정적 호스팅 인프라와 Route53 안전장치 (Int).

Task 10이 게시 후 검사(REQ 추가)를 이 파일에 덧붙인다.
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

from td import route53

import helpers

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_WORK = REPO_ROOT / "work" / "infra"


def _allow(domain: str) -> list[tuple[str, str]]:
    return [(f"reports.{domain}.", "A"), (f"reports.{domain}.", "AAAA"),
            (f"_*.reports.{domain}.", "CNAME"), (f"dash.{domain}.", "A")]


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


def test_hosting_reports_domain_serves_https(local_env):
    status, _ = helpers.https_get(f"reports.{local_env['TD_DOMAIN']}", local_env["TD_DOMAIN"])
    assert status == 200


# --- 게시 후 검사(Task 10): 세션 접두(`_test/<sessionId>/`)에 실제로 게시한 두 run을 두 호스트에서 확인한다. ---
# 운영 루트(reports.<domain>/ 자체) 크롤링은 Task 25의 기준 run 게시 뒤에 한다.
def _scope(site_prefix: str) -> tuple[str, ...]:
    return (f"/{site_prefix}", "/_test/index.html", "/_test/static/")


def test_req068_cache_headers(published_runs, local_env, site_prefix):
    domain, sut = local_env["TD_DOMAIN"], published_runs["sut"]
    run_id = published_runs["runs"][0][0]
    host = f"reports.{domain}"
    for path in (f"/{site_prefix}index.html", f"/{site_prefix}suts.json", f"/{site_prefix}suts/{sut}/runs.json",
                 f"/{site_prefix}suts/{sut}/index.html"):
        status, headers, _ = helpers.https_fetch(host, domain, path)
        assert status == 200 and headers.get("cache-control") == "no-cache", (path, status, headers.get("cache-control"))
    for path in (f"/{site_prefix}suts/{sut}/runs/{run_id}/index.html", f"/{site_prefix}suts/{sut}/runs/{run_id}/run.json",
                 f"/{site_prefix}suts/{sut}/runs/{run_id}/stages/S01.json"):
        status, headers, _ = helpers.https_fetch(host, domain, path)
        assert status == 200 and headers.get("cache-control") == "max-age=31536000, immutable", (path, status, headers.get("cache-control"))


def test_req047_static_host_crawl(published_runs, local_env, site_prefix):
    domain, sut = local_env["TD_DOMAIN"], published_runs["sut"]
    seen = helpers.crawl(f"reports.{domain}", domain, f"/{site_prefix}index.html", _scope(site_prefix))
    bad = {path: status for path, status in seen.items() if status != 200}
    assert not bad, bad
    for run_id, _, _ in published_runs["runs"]:
        assert f"/{site_prefix}suts/{sut}/runs/{run_id}/index.html" in seen, "새 run 페이지까지 도달해야 한다"
    status, _, body = helpers.https_fetch(f"reports.{domain}", domain, f"/{site_prefix}index.html")
    assert status == 200 and sut in body.decode()
    sut_page = helpers.https_fetch(f"reports.{domain}", domain, f"/{site_prefix}suts/{sut}/index.html")[2].decode()
    assert published_runs["runs"][-1][0] in sut_page, "SUT 페이지에 최신 runId가 보여야 한다"


def test_req048_lightsail_crawl(published_runs, local_env, site_prefix, s3_client, bucket):
    domain, sut = local_env["TD_DOMAIN"], published_runs["sut"]
    seen = helpers.crawl(f"dash.{domain}", domain, f"/{site_prefix}index.html", _scope(site_prefix))
    bad = {path: status for path, status in seen.items() if status != 200}
    assert not bad, bad
    for run_id, _, _ in published_runs["runs"]:
        assert f"/{site_prefix}suts/{sut}/runs/{run_id}/index.html" in seen
    runs_path = f"/{site_prefix}suts/{sut}/runs.json"
    dash = helpers.https_fetch(f"dash.{domain}", domain, runs_path)
    static = helpers.https_fetch(f"reports.{domain}", domain, runs_path)
    assert dash[0] == static[0] == 200 and dash[2] == static[2], "runs.json은 두 호스트에서 바이트 단위로 같아야 한다"
    assert dash[2] == s3_client.get_object(Bucket=bucket, Key=runs_path.lstrip("/"))["Body"].read()


# --- 호스팅 비교(Task 11): 게시된 hosting.json/hosting.html을 두 호스트에서 읽어 검사한다(E2E) ---
def _hosting_doc(local_env, site_prefix, host_name: str) -> dict:
    domain = local_env["TD_DOMAIN"]
    status, headers, body = helpers.https_fetch(f"{host_name}.{domain}", domain, f"/{site_prefix}hosting.json")
    assert status == 200, f"{host_name} hosting.json {status}"
    if host_name == "reports":  # Lightsail Caddy는 캐시 헤더를 달지 않는다(REQ-068도 reports만 검사)
        assert headers.get("cache-control") == "no-cache", headers.get("cache-control")
    return json.loads(body)


def _hosting_html(local_env, site_prefix, host_name: str) -> str:
    domain = local_env["TD_DOMAIN"]
    status, headers, body = helpers.https_fetch(f"{host_name}.{domain}", domain, f"/{site_prefix}hosting.html")
    assert status == 200, status
    if host_name == "reports":
        assert headers.get("cache-control") == "no-cache", headers.get("cache-control")
    return body.decode()


def test_req051_quantitative(published_runs, local_env, site_prefix):
    import jsonschema
    from td import hosting
    last_log = json.loads((published_runs["runs"][-1][1] / "stages" / "S13.json").read_text())
    doc = _hosting_doc(local_env, site_prefix, "reports")
    assert doc == _hosting_doc(local_env, site_prefix, "dash"), "두 호스트의 hosting.json은 같아야 한다"
    jsonschema.validate(doc, hosting.load_schema())
    html = _hosting_html(local_env, site_prefix, "reports")
    assert "호스팅 방식 비교" in html
    for name in ("reports", "dash"):
        quant = doc["hosts"][name]["quantitative"]
        assert quant["deploy"]["unit"] == "s" and quant["deploy"]["seconds"] is not None and quant["deploy"]["seconds"] >= 0
        ttfb = quant["ttfb"]
        assert ttfb["unit"] == "ms" and ttfb["samples"] == 10 and ttfb["timeoutSeconds"] == 10 and ttfb["warm"] is True
        assert ttfb["ok"] + ttfb["failed"] == 10 and ttfb["url"].startswith(f"https://{name}.{local_env['TD_DOMAIN']}/")
        assert quant["homeTransfer"]["unit"] == "ms" and quant["homeTransfer"]["ms"] > 0
        assert str(quant["deploy"]["seconds"]) in html
        if ttfb["ok"] >= 7:
            assert ttfb["medianMs"] > 0 and f"{ttfb['medianMs']:.1f}" in html
        else:
            assert ttfb["medianMs"] is None and last_log["status"] == "degraded"
    memory = doc["hosts"]["dash"]["quantitative"]["memory"]
    assert memory["unit"] == "MB" and memory["metric"] == "available" and memory["beforeMb"] > 0 and memory["afterMb"] > 0
    assert doc["hosts"]["reports"]["quantitative"]["memory"] is None
    assert str(memory["afterMb"]) in html


def test_req073_qualitative(published_runs, local_env, site_prefix):
    doc = _hosting_doc(local_env, site_prefix, "dash")
    html = _hosting_html(local_env, site_prefix, "dash")
    for name in ("reports", "dash"):
        qual = doc["hosts"][name]["qualitative"]
        cost = qual["cost"]
        assert cost["source"] and all(item["url"].startswith("https://") for item in cost["source"])
        for field in ("region", "asOf", "formula", "priceBasis"):
            assert str(cost[field]).strip(), (name, field)
        assert cost["assumptions"] and all(str(a).strip() for a in cost["assumptions"])
        assert qual["operations"].strip() and qual["failureScope"].strip()
        for text in (cost["formula"], qual["operations"], qual["failureScope"], cost["region"], cost["asOf"]):
            assert text.split("\n")[0].strip()[:20] in html or text.strip()[:20] in html, text[:30]
    assert "Sonar" in doc["hosts"]["dash"]["qualitative"]["failureScope"]
