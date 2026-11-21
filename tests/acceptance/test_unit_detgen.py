"""td.detgen 단위 테스트(Task 2~5가 함께 키운다). Task 2: det 번들 투영(REQ-110, REQ-112)."""
import json
import shutil
from pathlib import Path

import pytest

from td import redact
from td.detgen import inputs

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "det"
RAW_MIN = FIXTURES / "raw-min"
PETCLINIC_RUN = FIXTURES / "petclinic" / "run"
SUT_FILE = FIXTURES / "petclinic" / "sut.yaml"


def _copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def _bundle_text(directory: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(directory.iterdir()))


def test_req112_projection(tmp_path):
    projection = inputs.project(RAW_MIN, SUT_FILE, tmp_path / "out")
    assert projection.fatal is None and projection.missing == []
    text = _bundle_text(projection.dir)
    assert "interceptor_sources" not in text and "file_path" not in text
    assert "/Users/" not in text
    assert redact.find_leaks(text) == []
    assert len(projection.input_hash) == 64
    stamp = json.loads((projection.dir / "STAMP.json").read_text(encoding="utf-8"))
    assert set(stamp["files"]) == {"plans.json", "keyparams.json", "auth.json", "ontology.json", "ext.json", "harness.json"}


def test_projection_keeps_only_allowed_fields(tmp_path):
    projection = inputs.project(RAW_MIN, SUT_FILE, tmp_path / "out")
    bundle = inputs.Bundle.open(projection.dir)
    plans = bundle.read("plans.json")
    assert [plan["file"] for plan in plans] == ["plan-tests-Foo.bar.json", "plan-tests-Foo.baz.json"]
    first = plans[0]
    assert (first["class"], first["method"]) == ("Foo", "bar")
    assert [item["index"] for item in first["items"]] == [0, 1, 2]
    # 같은 id(errorPath_code400)가 반복돼도 주소(index, conditionSha)로 구분된다
    assert first["items"][0]["conditionSha"] != first["items"][1]["conditionSha"]
    assert set(first["items"][0]) == {"index", "condition", "expected", "branch_value", "param", "prefix", "conditionSha"}
    assert bundle.read("auth.json") == {"required_headers": [{"name": "Authorization", "required": True}]}
    keyparams = bundle.read("keyparams.json")
    assert keyparams[0]["parameters"][0]["reasons"][0] == {"type": "BRANCH_CONDITION", "detail": "req.nights() < 1 || req.nights() > 30"}
    assert keyparams[0]["parameters"][0]["accessor"] == "req"
    assert set(keyparams[0]["parameters"][0]) == {"name", "accessor", "http_name", "java_type", "reasons"}
    assert bundle.read("harness.json") == {"login": "POST /api/auth/login", "unauthenticatedStatus": 403,
                                           "apiInclude": "/api/**", "timezone": "Asia/Seoul"}


def test_req112_bundle_rejects_unlisted_file(tmp_path):
    projection = inputs.project(RAW_MIN, SUT_FILE, tmp_path / "out")
    (projection.dir / "raw.json").write_text("{}", encoding="utf-8")  # 디스크에 있어도 STAMP에 없으면 거부
    bundle = inputs.Bundle.open(projection.dir)
    for name in ("../x", "raw.json", "/etc/passwd", "plans.json/../raw.json"):
        with pytest.raises(inputs.DetInputError):
            bundle.read(name)
    assert bundle.read("plans.json")


def test_bundle_rejects_tampered_file(tmp_path):
    projection = inputs.project(RAW_MIN, SUT_FILE, tmp_path / "out")
    (projection.dir / "auth.json").write_text("{}", encoding="utf-8")
    with pytest.raises(inputs.DetInputError):
        inputs.Bundle.open(projection.dir).read("auth.json")


def test_req110_missing_optional_inputs(tmp_path):
    run = _copy(RAW_MIN, tmp_path / "run")
    shutil.rmtree(run / "S02" / "bbtg" / "raw" / "artifacts" / "key-params")
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    assert projection.missing == ["keyparams"]
    assert projection.fatal is None
    assert inputs.Bundle.open(projection.dir).read("keyparams.json") == []


def test_req110_missing_optional_auth_and_broken_plan(tmp_path):
    run = _copy(RAW_MIN, tmp_path / "run")
    raw = run / "S02" / "bbtg" / "raw"
    (raw / "artifacts" / "inspect-auth" / "result.json").unlink()
    (raw / "stdout" / "plan-tests-Foo.baz.json").write_text("{not json", encoding="utf-8")
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    assert projection.fatal is None
    assert projection.missing == ["auth", "plan:plan-tests-Foo.baz.json"]


def test_req110_missing_required(tmp_path):
    run = _copy(RAW_MIN, tmp_path / "run")
    (run / "S03" / "ontology-jqa-ext.json").unlink()
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    assert projection.fatal and "ontology-jqa-ext.json" in projection.fatal


def test_req110_missing_all_plans_is_fatal(tmp_path):
    run = _copy(RAW_MIN, tmp_path / "run")
    for plan in (run / "S02" / "bbtg" / "raw" / "stdout").glob("plan-tests-*.json"):
        plan.unlink()
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    assert projection.fatal and "plan-tests" in projection.fatal


def test_req110_broken_required_json_is_fatal(tmp_path):
    run = _copy(RAW_MIN, tmp_path / "run")
    (run / "S03" / "ontology-jqa.json").write_text("{}", encoding="utf-8")  # 스키마 위반
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    assert projection.fatal and "ontology-jqa.json" in projection.fatal


def test_projection_hash_path_independent(tmp_path):
    first = inputs.project(_copy(RAW_MIN, tmp_path / "a" / "deep" / "run"), SUT_FILE, tmp_path / "out1")
    second = inputs.project(_copy(RAW_MIN, tmp_path / "b" / "run"), SUT_FILE, tmp_path / "out2")
    assert first.input_hash == second.input_hash
    assert (first.dir / "STAMP.json").read_bytes() == (second.dir / "STAMP.json").read_bytes()


def test_projection_hash_changes_with_input(tmp_path):
    run = _copy(RAW_MIN, tmp_path / "run")
    before = inputs.project(run, SUT_FILE, tmp_path / "o1").input_hash
    plan = run / "S02" / "bbtg" / "raw" / "stdout" / "plan-tests-Foo.baz.json"
    plan.write_text(plan.read_text(encoding="utf-8").replace('"flag"', '"flag2"'), encoding="utf-8")
    assert inputs.project(run, SUT_FILE, tmp_path / "o2").input_hash != before


def test_timezone_from_compose_env(tmp_path):
    root = tmp_path / "repo"
    sut_dir = root / "suts" / "x"
    sut_dir.mkdir(parents=True)
    shutil.copy(SUT_FILE, sut_dir / "sut.yaml")
    (root / "env").mkdir()
    (root / "env" / "docker-compose.sut.yml").write_text("services:\n  sut:\n    environment:\n      TZ: America/New_York\n", encoding="utf-8")
    projection = inputs.project(RAW_MIN, sut_dir / "sut.yaml", tmp_path / "out")
    assert inputs.Bundle.open(projection.dir).read("harness.json")["timezone"] == "America/New_York"


def test_petclinic_real_fixture_projection(tmp_path):
    projection = inputs.project(PETCLINIC_RUN, SUT_FILE, tmp_path / "out")
    assert projection.fatal is None and projection.missing == []
    bundle = inputs.Bundle.open(projection.dir)
    plans = bundle.read("plans.json")
    assert len(plans) == 6 and sum(len(plan["items"]) for plan in plans) > 20
    text = _bundle_text(projection.dir)
    assert "interceptor_sources" not in text and redact.find_leaks(text) == []


def test_committed_fixtures_have_no_real_leaks():
    """합성 raw-min은 가짜 경로(/Users/example/)만 허용한다. 실제 홈 경로·식별자는 어느 fixture에도 없어야 한다."""
    for path in sorted(FIXTURES.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if path.is_relative_to(RAW_MIN):
            text = text.replace("/Users/example/", "")  # 절대경로 제거 동작을 증명하기 위한 의도적 가짜 경로
        assert redact.find_leaks(text) == [], path


def test_missing_or_malformed_sut_yaml_is_fatal(tmp_path):
    missing = inputs.project(RAW_MIN, tmp_path / "nope" / "sut.yaml", tmp_path / "o1")
    assert missing.fatal and "sut.yaml" in missing.fatal
    bad = tmp_path / "sut.yaml"
    bad.write_text("name: [", encoding="utf-8")
    assert inputs.project(RAW_MIN, bad, tmp_path / "o2").fatal


def test_null_fields_become_empty_string(tmp_path):
    run = _copy(RAW_MIN, tmp_path / "run")
    plan = run / "S02" / "bbtg" / "raw" / "stdout" / "plan-tests-Foo.baz.json"
    data = json.loads(plan.read_text(encoding="utf-8"))
    data["test_cases"][0]["param"] = None
    plan.write_text(json.dumps(data), encoding="utf-8")
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    item = inputs.Bundle.open(projection.dir).read("plans.json")[1]["items"][0]
    assert item["param"] == ""


def test_condition_not_rewritten_and_leak_is_fatal(tmp_path):
    """조건식은 redaction으로 고쳐 쓰지 않는다(conditionSha는 원문 해시). 경로가 섞여 있으면 게이트가 fatal로 막는다."""
    run = _copy(RAW_MIN, tmp_path / "run")
    plan = run / "S02" / "bbtg" / "raw" / "stdout" / "plan-tests-Foo.baz.json"
    data = json.loads(plan.read_text(encoding="utf-8"))
    data["test_cases"][0]["condition"] = 'x.startsWith("/Users/example/a")'
    plan.write_text(json.dumps(data), encoding="utf-8")
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    assert projection.fatal and "redaction" in projection.fatal
    data["test_cases"][0]["condition"] = "a < b && \"/api/x\".equals(p)"
    plan.write_text(json.dumps(data), encoding="utf-8")
    ok = inputs.project(run, SUT_FILE, tmp_path / "out2")
    item = inputs.Bundle.open(ok.dir).read("plans.json")[1]["items"][0]
    assert item["condition"] == data["test_cases"][0]["condition"]
    import hashlib
    assert item["conditionSha"] == hashlib.sha256(item["condition"].encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Task 3: 조건식 파서(REQ-113). 아래 조건 문자열은 SUT fixture에서 온 테스트 데이터다(생성기 소스에는 없다).
# ---------------------------------------------------------------------------
from td.detgen import parse as detparse  # noqa: E402
from td.detgen.parse import Atom, Operand  # noqa: E402

PETCLINIC_PLANS = PETCLINIC_RUN / "S02" / "bbtg" / "raw" / "stdout"


def _request(name):
    return Operand("request", name)


def _number(text):
    return Operand("literal", text, "number")


def _single(parsed):
    assert parsed.reason is None and parsed.disjuncts is not None
    return parsed.disjuncts


def test_req113_range():
    disjuncts = _single(detparse.parse("req.nights() < 1 || req.nights() > 30", "req"))
    assert disjuncts == ((Atom("<", _request("nights"), _number("1")),),
                         (Atom(">", _request("nights"), _number("30")),))


def test_req113_length():
    condition = "req.petName() == null || req.petName().length() < 2 || req.petName().length() > 50"
    disjuncts = _single(detparse.parse(condition, "req"))
    assert disjuncts == ((Atom("==null", _request("petName"), None),),
                         (Atom("<", _request("petName"), _number("2"), length=True),),
                         (Atom(">", _request("petName"), _number("50"), length=True),))


def test_req113_enum_and():
    disjuncts = _single(detparse.parse("req.priceTier() == PriceTier.VIP && req.loyaltyPoints() < 500", "req"))
    assert len(disjuncts) == 1 and len(disjuncts[0]) == 2
    first, second = disjuncts[0]
    assert first.op == "==" and first.left == _request("priceTier")
    assert first.right == Operand("enum", "VIP", "PriceTier")
    assert second == Atom("<", _request("loyaltyPoints"), _number("500"))


def test_req113_date():
    disjuncts = _single(detparse.parse("req.checkInDate() == null || !req.checkInDate().isAfter(LocalDate.now())", "req"))
    assert disjuncts[0] == (Atom("==null", _request("checkInDate"), None),)
    (atom,) = disjuncts[1]
    assert atom.op == "isAfterNot" and atom.left == _request("checkInDate")
    assert atom.right.kind == "clock" and atom.right.name == "LocalDate.now()"


def test_req113_stored():
    # !now.isBefore(x) == !x.isAfter(now): 시계를 오른쪽으로 정규화한다
    (conjunct,) = _single(detparse.parse("!LocalDate.now().isBefore(existing.getCheckInDate())", None))
    (atom,) = conjunct
    assert atom.op == "isAfterNot"
    assert atom.left == Operand("stored", "checkInDate")
    assert atom.right.kind == "clock"


def test_req113_count_const():
    condition = "repository.countByRoomNumberAndStatus(req.roomNumber(), ReservationStatus.CONFIRMED) >= ROOM_CAPACITY"
    ((atom,),) = _single(detparse.parse(condition, "req"))
    assert atom.op == "countGe"
    assert atom.right == Operand("constant", "ROOM_CAPACITY")
    assert atom.left.kind == "request" and atom.left.name == "roomNumber"
    assert "ReservationStatus.CONFIRMED" in atom.left.detail


def test_req113_count_without_request_arg_is_unresolved():
    condition = ("req.nights() != existing.getNights() && repository.countByRoomNumberAndStatus(existing.getRoomNumber(),"
                 "\n\t\t\t\t\tReservationStatus.CONFIRMED) >= ROOM_CAPACITY")
    ((first, second),) = _single(detparse.parse(condition, "req"))
    assert first == Atom("!=", _request("nights"), Operand("stored", "nights"))
    assert second.op == "countGe" and second.left.kind == "unresolved"
    assert "\n" not in second.left.name and "ReservationStatus.CONFIRMED" in second.left.detail


def test_req113_equals_literal():
    ((atom,),) = _single(detparse.parse('"WELCOME10".equals(req.promoCode())', "req"))
    assert atom == Atom("equalsLit", _request("promoCode"), Operand("literal", "WELCOME10", "string"))


def test_req113_equals_literal_bare_request_variable():
    ((atom,),) = _single(detparse.parse('"user".equals(username)', "username"))
    assert atom == Atom("equalsLit", _request("username"), Operand("literal", "user", "string"))


def test_req113_local_variable_unresolved():
    ((atom,),) = _single(detparse.parse("checkIn.isBefore(LocalDateTime.now().plusHours(48))", "req"))
    assert atom.op == "isBefore"
    assert atom.left == Operand("unresolved", "checkIn")
    assert atom.right.kind == "clock" and atom.right.detail == ".plusHours(48)"


def test_req113_multiline_condition_is_unparsed_not_crash():
    condition = "req.status() != null && req.status() != existing.getStatus()\n\t\t\t\t&& !existing.getStatus().canTransitionTo(req."
    parsed = detparse.parse(condition, "req")
    assert parsed.disjuncts is None and parsed.reason == "unparsed"


def test_req113_operand_reversed():
    ((atom,),) = _single(detparse.parse("30 < req.nights()", "req"))
    assert atom == Atom(">", _request("nights"), _number("30"))


def test_req113_matcher_not():
    disjuncts = _single(detparse.parse("req.ownerEmail() == null || !EMAIL.matcher(req.ownerEmail()).matches()", "req"))
    assert disjuncts == ((Atom("==null", _request("ownerEmail"), None),),
                         (Atom("matchesNot", _request("ownerEmail"), Operand("constant", "EMAIL")),))


def test_req113_arithmetic_relation_has_unresolved_operands():
    condition = "req.depositAmount() * 1.1 < req.nights() * req.priceTier().getNightlyRate()"
    ((atom,),) = _single(detparse.parse(condition, "req"))
    assert atom == Atom("<", Operand("unresolved", "req.depositAmount() * 1.1"),
                        Operand("unresolved", "req.nights() * req.priceTier().getNightlyRate()"))


def test_req113_not_null():
    assert _single(detparse.parse("req.nights() != null", "req")) == ((Atom("!=null", _request("nights"), None),),)


def test_req113_unknown_boolean_call_full_multiline():
    condition = ("req.status() != null && req.status() != existing.getStatus()\n\t\t\t\t"
                 "&& !existing.getStatus().canTransitionTo(req.status())")
    ((first, second, third),) = _single(detparse.parse(condition, "req"))
    assert first == Atom("!=null", _request("status"), None)
    assert second == Atom("!=", _request("status"), Operand("stored", "status"))
    assert third == Atom("==", Operand("unresolved", "existing.getStatus().canTransitionTo(req.status())"),
                         Operand("literal", "false", "boolean"))


def test_req113_foreign_receiver_and_boolean_local():
    ((first, second),) = _single(detparse.parse("!includeStale && r.getCheckInDate().isBefore(LocalDate.now())", "req"))
    assert first == Atom("==", Operand("unresolved", "includeStale"), Operand("literal", "false", "boolean"))
    assert second.op == "isBefore" and second.left == Operand("unresolved", "r.getCheckInDate()")
    assert second.right.kind == "clock"


def test_req113_stored_enum_conjunction():
    condition = "existing.getStatus() != ReservationStatus.PENDING && existing.getStatus() != ReservationStatus.CANCELLED"
    ((first, second),) = _single(detparse.parse(condition, None))
    assert first == Atom("!=", Operand("stored", "status"), Operand("enum", "PENDING", "ReservationStatus"))
    assert second.right == Operand("enum", "CANCELLED", "ReservationStatus")


def test_req113_negated_group_uses_de_morgan():
    disjuncts = _single(detparse.parse("!(req.a() >= 1 && req.b() == null)", "req"))
    assert disjuncts == ((Atom("<", _request("a"), _number("1")),), (Atom("!=null", _request("b"), None),))


def test_req113_request_var_unknown_makes_accessor_unresolved():
    ((atom,),) = _single(detparse.parse("req.nights() < 1", None))
    assert atom.left == Operand("unresolved", "req.nights()")


@pytest.mark.parametrize("condition", [
    "username = admin", "username ≠ admin, user", "req = null/empty", "Happy Path (POST — x)",
    "DB에 id 조건에 맞는 데이터 없음 (repository.findById)", "General Bad Request (400)", "", "   ",
    "a <", "(a < 1", "a < 1)", "x -> x > 1", "!", "a < b < c", "1", '"x"', None,
])
def test_req113_garbage_is_unparsed(condition):
    parsed = detparse.parse(condition, "req")
    assert parsed.disjuncts is None and parsed.reason == "unparsed"


def _real_conditions():
    found = []
    for path in sorted(PETCLINIC_PLANS.glob("plan-tests-*.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        for case in plan["test_cases"]:
            found.append(case.get("condition"))
    return found


def test_req113_all_real_fixture_conditions_never_raise():
    conditions = _real_conditions()
    assert len(conditions) > 30
    parsed_count = 0
    for condition in conditions:
        for request_var in ("req", None):
            parsed = detparse.parse(condition, request_var)
            assert (parsed.disjuncts is None) == (parsed.reason == "unparsed")
            if request_var == "req" and parsed.disjuncts is not None:
                parsed_count += 1
    # 실제 조건 중 Java 식인 것(자연어 설명 제외)은 모두 파싱된다
    assert parsed_count >= 20


@pytest.mark.parametrize("condition", ["a\n/Users/example/x", "x\t/home/example/y"])
def test_leak_after_escape_sequence_is_fatal(tmp_path, condition):
    """이스케이프(\\n, \\t) 바로 뒤의 경로도 원시 문자열 검사로 잡아 fatal이 된다."""
    run = _copy(RAW_MIN, tmp_path / "run")
    plan = run / "S02" / "bbtg" / "raw" / "stdout" / "plan-tests-Foo.baz.json"
    data = json.loads(plan.read_text(encoding="utf-8"))
    data["test_cases"][0]["condition"] = condition
    plan.write_text(json.dumps(data), encoding="utf-8")
    projection = inputs.project(run, SUT_FILE, tmp_path / "out")
    assert projection.fatal and "redaction" in projection.fatal


@pytest.mark.parametrize("condition, expected", [
    ("req.count() < 1 || req.count() > 10",
     ((Atom("<", Operand("request", "count"), Operand("literal", "1", "number")),),
      (Atom(">", Operand("request", "count"), Operand("literal", "10", "number")),))),
    ("req.countryCode() >= 5", ((Atom(">=", Operand("request", "countryCode"), Operand("literal", "5", "number")),),)),
    ("req.counter() >= MAX", ((Atom(">=", Operand("request", "counter"), Operand("constant", "MAX")),),)),
])
def test_req113_count_prefixed_request_field_is_not_count_query(condition, expected):
    assert _single(detparse.parse(condition, "req")) == expected


def test_req113_count_prefixed_stored_field_is_not_count_query():
    ((atom,),) = _single(detparse.parse("existing.getCountLimit() >= 3", None))
    assert atom == Atom(">=", Operand("stored", "countLimit"), Operand("literal", "3", "number"))


def test_req113_clock_chain_only_shift_methods_stay_clock():
    ((atom,),) = _single(detparse.parse("req.year() < LocalDate.now().getYear()", "req"))
    assert atom.right == Operand("unresolved", "LocalDate.now().getYear()")
    ((shifted,),) = _single(detparse.parse("req.d().isBefore(LocalDate.now().minusDays(1).atStartOfDay())", "req"))
    assert shifted.right == Operand("clock", "LocalDate.now()", ".minusDays(1).atStartOfDay()")


def test_req113_internal_error_is_swallowed(monkeypatch):
    def boom(self, pred):
        raise ZeroDivisionError("내부 버그 모사")
    monkeypatch.setattr(detparse._Classifier, "atom", boom)
    assert detparse.parse("req.nights() < 1", "req") == detparse.Parsed(None, "unparsed")
