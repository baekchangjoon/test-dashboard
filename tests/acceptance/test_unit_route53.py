"""route53 비교 로직 단위 테스트."""
import pytest
from td import route53


def _a(name, value="192.0.2.1", rtype="A"):
    return {"Name": name, "Type": rtype, "TTL": 60, "ResourceRecords": [{"Value": value}]}


ALLOW = [("reports.example.test.", "A"), ("reports.example.test.", "AAAA"),
         ("_*.reports.example.test.", "CNAME"), ("dash.example.test.", "A")]


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


def test_allowed_name_with_unlisted_type_is_reported():
    before = [_a("www.example.test.")]
    after = before + [_a("reports.example.test.", "x", "TXT"), _a("dash.example.test.", "x", "CNAME")]
    diffs = {(d.kind, d.name, d.type) for d in route53.compare(before, after, ALLOW)}
    assert diffs == {("added", "reports.example.test.", "TXT"), ("added", "dash.example.test.", "CNAME")}


def test_cli_allow_pairs_parsed():
    assert route53.parse_allow(["reports.example.test.,A", "_*.reports.example.test.,CNAME"]) == [
        ("reports.example.test.", "A"), ("_*.reports.example.test.", "CNAME")]


def _stub_client():
    import boto3
    return boto3.client("route53", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")


def test_create_a_record_sends_create_action():
    from botocore.stub import Stubber
    client = _stub_client()
    change = {"Comment": "td dash", "Changes": [{"Action": "CREATE", "ResourceRecordSet": {
        "Name": "dash.example.test.", "Type": "A", "TTL": 300, "ResourceRecords": [{"Value": "192.0.2.7"}]}}]}
    with Stubber(client) as stubber:
        stubber.add_response("change_resource_record_sets", {"ChangeInfo": {
            "Id": "/change/C1", "Status": "PENDING", "SubmittedAt": "2026-01-01T00:00:00Z"}},
            {"HostedZoneId": "Z1", "ChangeBatch": change})
        route53.create_a_record("Z1", "dash.example.test.", "192.0.2.7", client)
        stubber.assert_no_pending_responses()


def test_delete_a_record_sends_delete_with_exact_value():
    from botocore.stub import Stubber
    client = _stub_client()
    change = {"Comment": "td dash rollback", "Changes": [{"Action": "DELETE", "ResourceRecordSet": {
        "Name": "dash.example.test.", "Type": "A", "TTL": 300, "ResourceRecords": [{"Value": "192.0.2.7"}]}}]}
    with Stubber(client) as stubber:
        stubber.add_response("change_resource_record_sets", {"ChangeInfo": {
            "Id": "/change/C1", "Status": "PENDING", "SubmittedAt": "2026-01-01T00:00:00Z"}},
            {"HostedZoneId": "Z1", "ChangeBatch": change})
        route53.delete_a_record("Z1", "dash.example.test.", "192.0.2.7", client)
        stubber.assert_no_pending_responses()


def _client_with(rrsets):
    from botocore.stub import Stubber
    client = _stub_client()
    stubber = Stubber(client)
    stubber.add_response("list_resource_record_sets", {
        "ResourceRecordSets": rrsets, "IsTruncated": False, "MaxItems": "300"}, {"HostedZoneId": "Z1"})
    stubber.activate()
    return client


@pytest.mark.parametrize("existing,expected", [
    ([], "absent"),
    ([_a("dash.example.test.", "192.0.2.7")], "same"),
    ([_a("dash.example.test.", "192.0.2.8")], "different"),
    ([_a("dash.example.test.", "192.0.2.7", "TXT")], "different"),
])
def test_record_state(existing, expected):
    client = _client_with(existing + [_a("www.example.test.")])
    assert route53.record_state("Z1", "dash.example.test.", "192.0.2.7", client) == expected
