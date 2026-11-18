"""Route53 안전장치: 적용 전후 RRSet 스냅샷, 이름 충돌 검사, 허용 목록 밖 변경 탐지.

reports·ACM 검증 레코드는 Terraform만 바꾼다. 이 모듈이 직접 바꾸는 것은 Lightsail용 `dash` A 레코드
(create_a_record/delete_a_record)뿐이며, CREATE/DELETE만 쓰고 UPSERT는 쓰지 않는다.
CLI: python -m td.route53 {zone-id|snapshot|check|compare|state|create-a|delete-a} ...
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path

RRSet = dict


class Route53Conflict(Exception):
    """같은 이름의 레코드가 이미 있어 적용을 중단해야 할 때."""


@dataclass(frozen=True)
class Diff:
    kind: str  # added | removed | changed
    name: str
    type: str


def _client(client=None):
    if client is not None:
        return client
    import boto3
    return boto3.client("route53")


def _norm_name(name: str) -> str:
    return name.replace("\\052", "*").lower()


def _key(rrset: RRSet) -> tuple:
    return (_norm_name(rrset["Name"]), rrset["Type"], rrset.get("SetIdentifier", ""))


def _bare_id(zone_id: str) -> str:
    return zone_id.rsplit("/", 1)[-1]


def find_zone_id(domain: str, client=None) -> str:
    """도메인 이름으로 공개 호스팅 zone 한 개를 찾는다. 없거나 모호하면 예외."""
    client = _client(client)
    wanted = domain.rstrip(".").lower() + "."
    zones = []
    for page in client.get_paginator("list_hosted_zones").paginate():
        zones += [z for z in page["HostedZones"]
                  if z["Name"].lower() == wanted and not z["Config"].get("PrivateZone")]
    if len(zones) != 1:
        raise LookupError(f"공개 hosted zone {len(zones)}개 발견(1개여야 한다)")
    return _bare_id(zones[0]["Id"])


def snapshot(zone_id: str, client=None) -> list[RRSet]:
    client = _client(client)
    rrsets: list[RRSet] = []
    for page in client.get_paginator("list_resource_record_sets").paginate(HostedZoneId=_bare_id(zone_id)):
        rrsets += page["ResourceRecordSets"]
    return sorted(rrsets, key=_key)


def _target(rrset: RRSet) -> str:
    if "AliasTarget" in rrset:
        return rrset["AliasTarget"]["DNSName"].rstrip(".").lower()
    return ",".join(sorted(r["Value"] for r in rrset.get("ResourceRecords", [])))


def check_conflict(zone_id: str, names: list[str], client=None, expected_target: str | None = None) -> None:
    """상대 이름(예: "reports")이 zone에 이미 있으면 Route53Conflict.

    expected_target(우리 배포의 CloudFront 도메인)과 같은 alias면 재실행으로 보고 통과시킨다."""
    client = _client(client)
    zone_name = client.get_hosted_zone(Id=_bare_id(zone_id))["HostedZone"]["Name"].lower()
    wanted = {f"{name.rstrip('.').lower()}.{zone_name}" for name in names}
    for rrset in snapshot(zone_id, client):
        if _norm_name(rrset["Name"]) not in wanted:
            continue
        if expected_target and _target(rrset) == expected_target.rstrip(".").lower():
            continue
        raise Route53Conflict(f"{_norm_name(rrset['Name'])} ({rrset['Type']})가 이미 다른 대상으로 있다")


def record_state(zone_id: str, name: str, ip: str, client=None) -> str:
    """name의 기존 레코드 상태: absent(없음) | same(A가 ip 하나) | different(그 밖의 모든 경우)."""
    wanted = _norm_name(name)
    existing = [r for r in snapshot(zone_id, client) if _norm_name(r["Name"]) == wanted]
    if not existing:
        return "absent"
    return "same" if len(existing) == 1 and existing[0]["Type"] == "A" and _target(existing[0]) == ip else "different"


def parse_allow(values: list[str]) -> list[tuple[str, str]]:
    """CLI 값 `이름패턴,타입`을 (이름패턴, 타입) 쌍으로 바꾼다."""
    pairs = []
    for value in values:
        name, sep, rtype = value.rpartition(",")
        if not sep or not name or not rtype:
            raise ValueError(f"--allow는 '이름,타입' 형식이어야 한다: {value!r}")
        pairs.append((name, rtype))
    return pairs


def compare(before: list[RRSet], after: list[RRSet], allow: list[tuple[str, str]]) -> list[Diff]:
    """allow((이름 fnmatch 패턴, 레코드 타입) 쌍) 밖의 추가·삭제·변경만 돌려준다."""
    patterns = [(_norm_name(name), rtype.upper()) for name, rtype in allow]
    allowed = lambda name, rtype: any(
        fnmatch.fnmatchcase(name, pattern) and rtype.upper() == allowed_type for pattern, allowed_type in patterns)
    before_map = {_key(r): r for r in before}
    after_map = {_key(r): r for r in after}
    diffs: list[Diff] = []
    for key in sorted(before_map.keys() | after_map.keys()):
        name, rtype, _ = key
        if allowed(name, rtype):
            continue
        old, new = before_map.get(key), after_map.get(key)
        if old is None:
            diffs.append(Diff("added", name, rtype))
        elif new is None:
            diffs.append(Diff("removed", name, rtype))
        elif _normalize(old) != _normalize(new):
            diffs.append(Diff("changed", name, rtype))
    return diffs


def _normalize(rrset: RRSet) -> dict:
    out = dict(rrset)
    out["Name"] = _norm_name(out["Name"])
    if "ResourceRecords" in out:
        out["ResourceRecords"] = sorted(out["ResourceRecords"], key=lambda r: r["Value"])
    return out


def _change_a_record(action: str, comment: str, zone_id: str, name: str, ip: str, client) -> None:
    client = _client(client)
    client.change_resource_record_sets(HostedZoneId=_bare_id(zone_id), ChangeBatch={
        "Comment": comment,
        "Changes": [{"Action": action, "ResourceRecordSet": {
            "Name": name, "Type": "A", "TTL": 300, "ResourceRecords": [{"Value": ip}]}}]})


def create_a_record(zone_id: str, name: str, ip: str, client=None) -> None:
    """A 레코드를 CREATE한다(이미 있으면 Route53이 거부하므로 덮어쓰지 않는다)."""
    _change_a_record("CREATE", "td dash", zone_id, name, ip, client)


def delete_a_record(zone_id: str, name: str, ip: str, client=None) -> None:
    """우리가 만든 A 레코드를 정확한 값으로 DELETE한다(롤백용)."""
    _change_a_record("DELETE", "td dash rollback", zone_id, name, ip, client)


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="td.route53")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_zone = sub.add_parser("zone-id"); p_zone.add_argument("domain")
    p_snap = sub.add_parser("snapshot"); p_snap.add_argument("zone_id"); p_snap.add_argument("out")
    p_chk = sub.add_parser("check"); p_chk.add_argument("zone_id"); p_chk.add_argument("names", nargs="+")
    p_chk.add_argument("--expected-target")
    p_cmp = sub.add_parser("compare"); p_cmp.add_argument("before"); p_cmp.add_argument("after")
    p_cmp.add_argument("--allow", action="append", default=[])
    p_state = sub.add_parser("state"); p_state.add_argument("zone_id"); p_state.add_argument("name"); p_state.add_argument("ip")
    for cmd in ("create-a", "delete-a"):
        p_rec = sub.add_parser(cmd); p_rec.add_argument("zone_id"); p_rec.add_argument("name"); p_rec.add_argument("ip")
    args = parser.parse_args(argv)
    if args.cmd == "zone-id":
        print(find_zone_id(args.domain))
    elif args.cmd == "snapshot":
        Path(args.out).write_text(json.dumps(snapshot(args.zone_id), indent=2, sort_keys=True))
    elif args.cmd == "check":
        try:
            check_conflict(args.zone_id, args.names, expected_target=args.expected_target)
        except Route53Conflict as error:
            print(f"충돌: {error}", file=sys.stderr)
            return 4
    elif args.cmd == "state":
        print(record_state(args.zone_id, args.name, args.ip))
    elif args.cmd in ("create-a", "delete-a"):
        (create_a_record if args.cmd == "create-a" else delete_a_record)(args.zone_id, args.name, args.ip)
    else:
        diffs = compare(json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text()),
                        parse_allow(args.allow))
        for diff in diffs:
            print(f"허용 밖 변경: {diff.kind} {diff.name} {diff.type}", file=sys.stderr)
        return 5 if diffs else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
