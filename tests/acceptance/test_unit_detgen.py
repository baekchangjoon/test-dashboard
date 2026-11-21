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


# --- Task 4: 케이스 도출(REQ-106, REQ-107, REQ-109, REQ-111, REQ-114, REQ-115) ---------------------------

import copy
import hashlib

from td.detgen import derive as derive_module

CONTROLLED = FIXTURES / "controlled"
MUTATED = FIXTURES / "mutated"
PETCLINIC_SUT = FIXTURES / "petclinic" / "sut.yaml"


def _load_docs(directory: Path) -> dict:
    return {name: json.loads((directory / name).read_text(encoding="utf-8")) for name in inputs.BUNDLE_FILES}


def _make_bundle(directory: Path, docs: dict, missing=()) -> inputs.Bundle:
    """문서 묶음을 STAMP가 있는 det 번들로 쓴다(투영과 같은 직렬화·conditionSha 규칙)."""
    directory.mkdir(parents=True, exist_ok=True)
    for plan in docs["plans.json"]:
        for item in plan["items"]:
            item["conditionSha"] = hashlib.sha256(item["condition"].encode("utf-8")).hexdigest()
    digests = {}
    for name in inputs.BUNDLE_FILES:
        text = inputs._dumps(docs[name])
        (directory / name).write_text(text, encoding="utf-8")
        digests[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    stamp = {"files": digests, "input_hash": "0" * 64, "missing": sorted(missing), "schema": 1}
    (directory / inputs.STAMP_NAME).write_text(inputs._dumps(stamp), encoding="utf-8")
    return inputs.Bundle.open(directory)


def _controlled(tmp_path, mutate=None) -> inputs.Bundle:
    docs = _load_docs(CONTROLLED)
    if mutate is not None:
        mutate(docs)
    return _make_bundle(tmp_path / "bundle", docs)


def _plan(docs, method):
    return next(plan for plan in docs["plans.json"] if plan["method"] == method)


def _plain(value):
    return value.value if isinstance(value, derive_module.Value) else value


def _case_row(case) -> str:
    values = {f"path.{k}": _plain(v) for k, v in case.path.items()}
    values.update({f"query.{k}": _plain(v) for k, v in case.query.items()})
    values.update({f"body.{k}": _plain(v) for k, v in case.values.items()})
    return json.dumps({"rule": case.rule, "endpoint": case.endpoint, "values": values,
                       "strict": case.expect["strict"]}, sort_keys=True, ensure_ascii=False)


def _source_of(case, plan_file, index):
    return any(source.startswith(f"{plan_file}#{index}@") for source in case.sources)


def _derivation_text(derivation) -> str:
    from dataclasses import asdict
    return json.dumps({"cases": [asdict(case) for case in derivation.cases], "unresolved": derivation.unresolved},
                      ensure_ascii=False, sort_keys=True, default=str)


def _real_bundle(tmp_path) -> inputs.Bundle:
    projection = inputs.project(PETCLINIC_RUN, PETCLINIC_SUT, tmp_path / "real")
    assert projection.fatal is None
    return inputs.Bundle.open(projection.dir)


def test_req109_controlled_fixture(tmp_path):
    derivation = derive_module.derive(_controlled(tmp_path))
    assert derivation.unresolved == []
    expected = json.loads((CONTROLLED / "expected-cases.json").read_text(encoding="utf-8"))["cases"]
    expected_rows = sorted(json.dumps({key: row[key] for key in ("rule", "endpoint", "values", "strict")},
                                      sort_keys=True, ensure_ascii=False) for row in expected)
    assert sorted(_case_row(case) for case in derivation.cases) == expected_rows


def test_req111_mapping(tmp_path):
    docs = _load_docs(CONTROLLED)
    derivation = derive_module.derive(_make_bundle(tmp_path / "a", copy.deepcopy(docs)))
    for plan in docs["plans.json"]:
        endpoints = {case.endpoint for case in derivation.cases
                     if any(source.startswith(plan["file"] + "#") for source in case.sources)}
        assert len(endpoints) == 1, plan["file"]

    def drop_fetch_calls(target):
        target["ext.json"]["calls"] = [call for call in target["ext.json"]["calls"] if call["method"] != "fetch"]

    def duplicate_fetch_calls(target):
        fetch = next(call for call in target["ext.json"]["calls"] if call["method"] == "fetch")
        target["ext.json"]["calls"].append(dict(fetch, endpoint="endpoint:POST /svc/orders"))

    for index, mutate in enumerate((drop_fetch_calls, duplicate_fetch_calls)):
        variant = copy.deepcopy(docs)
        mutate(variant)
        result = derive_module.derive(_make_bundle(tmp_path / f"v{index}", variant))
        fetch_file = _plan(variant, "fetch")["file"]
        entries = [entry for entry in result.unresolved if entry["source"].startswith(fetch_file + "#")]
        assert len(entries) == len(_plan(variant, "fetch")["items"])
        assert {entry["reason"] for entry in entries} == {"no-endpoint-mapping"}
        assert not any(source.startswith(fetch_file) for case in result.cases for source in case.sources)

    # 기준 입력: 계획 메서드 6개가 각각 엔드포인트 하나에 대응한다
    real = derive_module.derive(_real_bundle(tmp_path))
    assert not [entry for entry in real.unresolved if entry["reason"] == "no-endpoint-mapping"]
    planned = {case.endpoint for case in real.cases
               if any(source.startswith("plan-tests-") for source in case.sources)}
    planned |= {entry["endpoint"] for entry in real.unresolved if entry["source"].startswith("plan-tests-")}
    assert len(planned) == 6


def test_req114_expect(tmp_path):
    docs = _load_docs(CONTROLLED)
    place = _plan(docs, "place")["file"]
    derivation = derive_module.derive(_make_bundle(tmp_path / "a", copy.deepcopy(docs)))
    violations = [case for case in derivation.cases if case.rule == "violation" and _source_of(case, place, 1)]
    assert violations
    for case in violations:
        assert case.expect["strict"] == 422 and case.expect["source"] == "graph"
        assert case.expect["bbtgCode"] == 400 and case.expect["graphStatus"] == 422
        assert case.expect["class"] == "4xx"
    variant = copy.deepcopy(docs)
    variant["ext.json"]["exceptions"] = {}
    stripped = derive_module.derive(_make_bundle(tmp_path / "b", variant))
    violations = [case for case in stripped.cases if case.rule == "violation" and _source_of(case, place, 1)]
    assert violations
    for case in violations:
        assert case.expect["strict"] == 400 and case.expect["source"] == "bbtg"
        assert "graphStatus" not in case.expect


def test_req115_baseline(tmp_path):
    derivation = derive_module.derive(_controlled(tmp_path))
    by_id = {case.id: case for case in derivation.cases}
    violation_endpoints = {case.endpoint for case in derivation.cases if case.rule == "violation"}
    assert "GET /svc/orders/{orderId}" in violation_endpoints  # GET의 파라미터 위반 포함
    for endpoint in violation_endpoints:
        baselines = [case for case in derivation.cases if case.endpoint == endpoint and case.rule == "baseline-valid"]
        assert len(baselines) == 1, endpoint
        assert baselines[0].expect["class"] == "2xx"
    for case in derivation.cases:
        if case.rule != "violation":
            continue
        pair = by_id[case.pair]
        assert pair.rule == "valid-boundary" and pair.sources == case.sources and pair.endpoint == case.endpoint


def test_req107_universe(tmp_path):
    universe = derive_module.derive(_controlled(tmp_path)).universe
    slots = universe["bySlot"]
    assert slots["generated"] + slots["unresolved"] == slots["total"]
    assert slots["unresolved"] == 0
    readme = (CONTROLLED / "README.md").read_text(encoding="utf-8")
    assert universe["theoretical"]["value"] == 868 and "868" in readme
    assert universe["theoretical"]["formula"] and universe["theoretical"]["factors"]
    assert sum(universe["byRule"].values()) == slots["generated"]

    real = derive_module.derive(_real_bundle(tmp_path))
    assert {entry["reason"] for entry in real.unresolved} <= set(derive_module.REASONS)
    real_slots = real.universe["bySlot"]
    assert real_slots["generated"] + real_slots["unresolved"] == real_slots["total"]
    assert real_slots["generated"] == len(real.cases) and real_slots["unresolved"] == len(real.unresolved)
    assert sum(real_slots["byReason"].values()) == real_slots["unresolved"]


def test_req106_mutated_fixture(tmp_path):
    derivation = derive_module.derive(_make_bundle(tmp_path / "m", _load_docs(MUTATED)))
    assert derivation.cases
    text = _derivation_text(derivation)
    originals = [line.strip() for line in (MUTATED / "original-names.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [name for name in originals if name in text] == []
    stays = {_plain(case.values["stays"]) for case in derivation.cases if "stays" in case.values}
    assert {46, 45, 2, 1} <= stays  # 변조 임계값(2..45)에서 파생한 경계
    slots = {_plain(case.values["kennelSlot"]) for case in derivation.cases if "kennelSlot" in case.values}
    assert {199, 200, 777, 778} <= slots


def test_req106_no_sut_literals():
    originals = [line.strip() for line in (MUTATED / "original-names.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    sources = sorted((REPO_ROOT / "site-gen" / "td" / "detgen").glob("*.py"))
    sources += sorted((REPO_ROOT / "e2e" / "det-glue").glob("**/*.java"))
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "/api/" not in text, path
        assert [name for name in originals if name in text] == [], path


def test_case_ids_unique_with_duplicate_bbtg_ids(tmp_path):
    def triplicate(docs):
        items = _plan(docs, "place")["items"]
        source = items[1]
        for offset in (1, 2):
            items.append(dict(source, index=len(items)))

    derivation = derive_module.derive(_controlled(tmp_path, triplicate))
    ids = [case.id for case in derivation.cases]
    assert len(ids) == len(set(ids))
    condition = "form.quantity() < 1 || form.quantity() > 9"
    sources = {source for case in derivation.cases if case.rule == "violation" for source in case.sources
               if "plan-tests-OrderService.place.json#" in source}
    sha12 = hashlib.sha256(condition.encode("utf-8")).hexdigest()[:12]
    assert len({source for source in sources if source.endswith(sha12)}) == 3


def test_spread_avoids_boundary_values(tmp_path):
    derivation = derive_module.derive(_controlled(tmp_path))
    boundary = {_plain(case.values["bay"]) for case in derivation.cases
                if case.rule in ("valid-boundary", "violation") and "bay" in case.values
                and any("#7@" in source for source in case.sources)}
    assert boundary == {9, 10, 20, 21}
    spread = [case.values["bay"] for case in derivation.cases
              if "bay" in case.values and (case.values["bay"].transform or "").startswith("spread")]
    assert len(spread) > 10
    for value in spread:
        assert value.provenance == "derived"
        assert 10 < value.value < 20 and value.value not in boundary


def test_constant_resolution_prefers_owner_class(tmp_path):
    def two_owners(docs):
        docs["ext.json"]["constants"].append({"owner": "ex.other.Thing", "name": "BAY_LIMIT", "type": "int", "value": 5})

    derivation = derive_module.derive(_controlled(tmp_path / "a", two_owners))
    counted = [case for case in derivation.cases if case.rule == "violation" and any("#6@" in s for s in case.sources)]
    assert len(counted) == 1 and len(counted[0].setup) == 2

    def foreign_owners(docs):
        docs["ext.json"]["constants"] = [
            {"owner": "ex.other.Alpha", "name": "BAY_LIMIT", "type": "int", "value": 2},
            {"owner": "ex.other.Beta", "name": "BAY_LIMIT", "type": "int", "value": 5}]

    derivation = derive_module.derive(_controlled(tmp_path / "b", foreign_owners))
    entries = [entry for entry in derivation.unresolved if "#6@" in entry["source"]]
    assert entries and {entry["reason"] for entry in entries} == {"unresolved-operand"}


def test_needs_state_transition(tmp_path):
    def stateful_count(docs):
        _plan(docs, "place")["items"][6]["condition"] = "repository.countByBayAndTone(form.bay(), Tone.MATTE) >= BAY_LIMIT"

    derivation = derive_module.derive(_controlled(tmp_path, stateful_count))
    entries = [entry for entry in derivation.unresolved if "#6@" in entry["source"]]
    assert entries and {entry["reason"] for entry in entries} == {"needs-state-transition"}


def test_auth_cases_exclude_login(tmp_path):
    derivation = derive_module.derive(_controlled(tmp_path))
    auth = [case for case in derivation.cases if case.rule == "auth"]
    assert sorted(case.endpoint for case in auth) == ["GET /svc/catalog", "GET /svc/orders/{orderId}", "POST /svc/orders"]
    for case in auth:
        assert case.expect["strict"] == 403 and case.expect["source"] == "harness-config"
        assert "보호됨" in case.assumes and case.auth == "anonymous"


# --- Task 4 fix round 1 ---------------------------------------------------------------------------

def test_reasons_tuple_is_closed():
    assert derive_module.REASONS == (
        "no-endpoint-mapping", "unparsed", "unresolved-operand", "unreachable-state", "needs-state-transition",
        "param-name-unknown", "no-id-ref", "no-condition", "no-body-schema", "format-unknown", "input-missing",
        "input-contradiction")


def test_input_contradiction_keeps_other_boundaries(tmp_path):
    def add_contradiction(docs):
        items = _plan(docs, "place")["items"]
        items.append({"index": len(items), "condition": "form.quantity() != null", "expected": "OrderInvalidException code=400",
                      "branch_value": "400", "param": "(from scenarios)", "prefix": "errorPath"})

    derivation = derive_module.derive(_controlled(tmp_path, add_contradiction))
    entries = [entry for entry in derivation.unresolved if "#8@" in entry["source"]]
    assert len(entries) == 2 and {entry["reason"] for entry in entries} == {"input-contradiction"}
    place = "plan-tests-OrderService.place.json#1@"
    boundaries = [case for case in derivation.cases if case.rule == "valid-boundary" and any(place in s for s in case.sources)]
    assert sorted(_plain(case.values["quantity"]) for case in boundaries) == [1, 9]
    by_id = {case.id: case for case in derivation.cases}
    for case in derivation.cases:
        if case.rule == "violation" and any(place in s for s in case.sources):
            assert by_id[case.pair].rule == "valid-boundary"
            assert not [a for a in case.assumes if a.startswith("also-violates")]


def test_concurrency_race_factor_out_of_scope(tmp_path):
    universe = derive_module.derive(_controlled(tmp_path)).universe
    races = [f for f in universe["theoretical"]["factors"] if f.get("kind") == "concurrency-race"]
    assert len(races) == 1 and races[0]["outOfScope"] is True and "#6@" in races[0]["item"]
    assert races[0]["endpoint"] == "POST /svc/orders"
    assert universe["theoretical"]["value"] == 868


def test_baseline_avoids_numeric_equality_violation(tmp_path):
    def add_equality(docs):
        items = _plan(docs, "place")["items"]
        items.append({"index": len(items), "condition": "form.credit() == 50", "expected": "OrderInvalidException code=400",
                      "branch_value": "400", "param": "(from scenarios)", "prefix": "errorPath"})

    derivation = derive_module.derive(_controlled(tmp_path, add_equality))
    baseline = next(case for case in derivation.cases if case.rule == "baseline-valid" and case.endpoint == "POST /svc/orders")
    assert _plain(baseline.values["credit"]) == 51


def test_auth_requires_authorization_header(tmp_path):
    def other_header(docs):
        docs["auth.json"] = {"required_headers": [{"name": "X-Api-Token", "required": True}]}

    derivation = derive_module.derive(_controlled(tmp_path, other_header))
    assert not [case for case in derivation.cases if case.rule == "auth"]


def test_second_plan_on_same_endpoint_names_its_params(tmp_path):
    def second_plan(docs):
        fetch = docs["ext.json"]["endpoints"]["endpoint:GET /svc/orders/{orderId}"]
        fetch["params"].append({"index": 2, "kind": "RequestParam", "type": "boolean", "name": None,
                                "defaultValue": "false", "required": None})
        docs["ext.json"]["calls"].append({"endpoint": "endpoint:GET /svc/orders/{orderId}", "handler": "ex.shop.OrderController#fetch",
                                          "service": "ex.shop.OrderService", "method": "peek"})
        docs["keyparams.json"].append({"file": "OrderService_peek.json", "class": "OrderService", "method": "peek", "parameters": [
            {"name": "verbose", "accessor": "verbose", "http_name": "verbose", "java_type": "boolean", "reasons": []}]})
        docs["plans.json"].append({"file": "plan-tests-OrderService.peek.json", "class": "OrderService", "method": "peek", "items": [
            {"index": 0, "condition": "verbose == true", "expected": "OrderInvalidException code=400", "branch_value": "400",
             "param": "(from scenarios)", "prefix": "errorPath"}]})

    derivation = derive_module.derive(_controlled(tmp_path, second_plan))
    assert not [entry for entry in derivation.unresolved if entry["reason"] == "param-name-unknown"]
    peek = [case for case in derivation.cases if any("peek" in s for s in case.sources) and case.rule == "violation"]
    assert len(peek) == 1 and _plain(peek[0].query["verbose"]) is True


def test_real_fixture_regression(tmp_path):
    """기준 petclinic 입력의 슬롯 수 고정(규칙 변경 시 의도적으로 갱신한다)."""
    derivation = derive_module.derive(_real_bundle(tmp_path))
    slots = derivation.universe["bySlot"]
    assert (slots["total"], slots["generated"], slots["unresolved"], slots["deduplicated"]) == (130, 80, 50, 1)
    assert {k: v for k, v in slots["byReason"].items() if v} == {
        "unparsed": 5, "unresolved-operand": 6, "unreachable-state": 5, "needs-state-transition": 14,
        "param-name-unknown": 1, "no-id-ref": 3, "no-condition": 7, "no-body-schema": 4, "input-missing": 3,
        "input-contradiction": 2}
    assert derivation.universe["theoretical"]["value"] == 46689
    login = [entry for entry in derivation.unresolved if entry["reason"] == "input-missing"]
    assert {entry["rule"] for entry in login} == {"baseline-valid", "valid-boundary", "branch-entry"}
    assert {entry["cause"] for entry in login} == {"credentials"}
    assert [case for case in derivation.cases if case.endpoint == login[0]["endpoint"] and case.rule == "violation"]
    # 다른 규칙의 같은 요청은 하나만 남고 출처가 합쳐진다(list tier 필터 vs enum-value)
    rows = [_case_row(case) for case in derivation.cases]
    assert len(rows) == len(set(rows))
    assert any(case.rule == "enum-value" and any(s.startswith("plan-tests-") for s in case.sources) for case in derivation.cases)
