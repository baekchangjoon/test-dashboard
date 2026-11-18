"""route53 비교 로직 단위 테스트."""
from td import route53


def _a(name, value="192.0.2.1", rtype="A"):
    return {"Name": name, "Type": rtype, "TTL": 60, "ResourceRecords": [{"Value": value}]}


ALLOW = ["reports.example.test.", "_*.reports.example.test."]


def test_identical_has_no_diff():
    rrsets = [_a("www.example.test.")]
    assert route53.compare(rrsets, list(rrsets), ALLOW) == []


def test_allowed_additions_ignored():
    before = [_a("www.example.test.")]
    after = before + [_a("reports.example.test."), _a("_abc.reports.example.test.", "x", "CNAME")]
    assert route53.compare(before, after, ALLOW) == []


def test_unexpected_addition_removal_change_reported():
    before = [_a("www.example.test."), _a("mx.example.test.")]
    after = [_a("www.example.test.", "192.0.2.9"), _a("new.example.test.")]
    diffs = {(d.kind, d.name) for d in route53.compare(before, after, ALLOW)}
    assert diffs == {("changed", "www.example.test."), ("removed", "mx.example.test."), ("added", "new.example.test.")}


def test_allowed_name_changing_existing_record_still_allowed_only_for_allowed():
    before = [_a("reports.example.test.")]
    after = [_a("reports.example.test.", "192.0.2.5")]
    assert route53.compare(before, after, ALLOW) == []
    assert route53.compare(before, after, []) != []


def test_wildcard_escape_normalized():
    before = [_a("\\052.example.test.")]
    after = [_a("*.example.test.")]
    assert route53.compare(before, after, ALLOW) == []


def test_conflict_allows_matching_expected_target():
    import pytest
    from botocore.stub import Stubber
    import boto3
    client = boto3.client("route53", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    alias = {"Name": "reports.example.test.", "Type": "A",
             "AliasTarget": {"HostedZoneId": "Z2FDTNDATAQYW2", "DNSName": "d1.cloudfront.net.", "EvaluateTargetHealth": False}}
    with Stubber(client) as stubber:
        for _ in range(2):
            stubber.add_response("get_hosted_zone", {
                "HostedZone": {"Id": "/hostedzone/Z1", "Name": "example.test.", "CallerReference": "c"},
                "DelegationSet": {"NameServers": ["ns.example.test"]}}, {"Id": "Z1"})
            stubber.add_response("list_resource_record_sets", {
                "ResourceRecordSets": [alias], "IsTruncated": False, "MaxItems": "300"}, {"HostedZoneId": "Z1"})
        route53.check_conflict("Z1", ["reports"], client, expected_target="d1.cloudfront.net")
        with pytest.raises(route53.Route53Conflict):
            route53.check_conflict("Z1", ["reports"], client, expected_target="other.cloudfront.net")
