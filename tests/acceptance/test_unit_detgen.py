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
                                           "apiInclude": "/api/**", "timezone": "Asia/Seoul", "pairwiseOrder": 2}


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


def test_projection_hash_includes_missing_list(tmp_path):
    # 깨진 선택 파일(missing에 남음)과 아예 없는 파일: 번들 파일 내용은 같지만 누락 목록이 달라 해시도 달라야 한다(M2)
    absent = inputs.project(_copy(RAW_MIN, tmp_path / "a"), SUT_FILE, tmp_path / "o1")
    broken_run = _copy(RAW_MIN, tmp_path / "b")
    (broken_run / "S02" / "bbtg" / "raw" / "stdout" / "plan-tests-Zed.q.json").write_text("{not json", encoding="utf-8")
    broken = inputs.project(broken_run, SUT_FILE, tmp_path / "o2")
    assert absent.missing == [] and broken.missing == ["plan:plan-tests-Zed.q.json"]
    files = lambda p: json.loads((p.dir / "STAMP.json").read_text(encoding="utf-8"))["files"]  # noqa: E731
    assert files(absent) == files(broken)
    assert absent.input_hash != broken.input_hash


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
        # 유효 경계가 baseline-valid와 같은 요청이면 병합되어 pair가 baseline-valid를 가리킬 수 있다
        assert pair.expect["class"] == "2xx" and pair.endpoint == case.endpoint
        assert set(case.sources) <= set(pair.sources)


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
        "input-contradiction", "pairwise-unavailable", "pairwise-too-large", "pairwise-infeasible", "pairwise-row-invalid")


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
            assert by_id[case.pair].expect["class"] == "2xx"
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


# --- Task 4 fix round 2 ---------------------------------------------------------------------------

def test_merged_boundary_keeps_violation_pair(tmp_path):
    """문자열·분산 필드가 없으면 유효 경계가 baseline-valid와 같은 요청이 되어 병합된다. 위반의 pair는 끊기지 않아야 한다."""
    def concrete_only(docs):
        form = docs["ext.json"]["dtos"]["ex.shop.OrderForm"]
        form["fields"] = [f for f in form["fields"] if f["type"] != "java.lang.String"]
        plan = _plan(docs, "place")
        plan["items"] = [i for i in plan["items"] if "count" not in i["condition"]]

    derivation = derive_module.derive(_controlled(tmp_path, concrete_only))
    assert derivation.universe["bySlot"]["deduplicated"] > 0
    by_id = {case.id: case for case in derivation.cases}
    violations = [case for case in derivation.cases if case.rule == "violation"]
    assert violations and all(case.pair is not None for case in violations)
    for case in violations:  # 병합 시 남는 case는 같은 요청의 유효 계열(baseline-valid·enum-value 등)일 수 있다
        assert by_id[case.pair].expect["class"] == "2xx"
        assert set(case.sources) <= set(by_id[case.pair].sources)


def test_baseline_equality_avoidance_moves_down_under_upper_bound(tmp_path):
    def upper_only(docs):
        items = _plan(docs, "place")["items"]
        items[3]["condition"] = "form.credit() > 80"
        # 단일 원자식이면 입력 모순(`> 80`의 유효 경계 80을 막음)으로 빠지므로 논리곱으로 둔다
        items.append({"index": len(items), "condition": "form.credit() == 80 && form.quantity() > 0", "expected": "OrderInvalidException code=400",
                      "branch_value": "400", "param": "(from scenarios)", "prefix": "errorPath"})

    derivation = derive_module.derive(_controlled(tmp_path, upper_only))
    baseline = next(case for case in derivation.cases if case.rule == "baseline-valid" and case.endpoint == "POST /svc/orders")
    assert _plain(baseline.values["credit"]) == 79


def test_race_factor_per_count_atom(tmp_path):
    def two_counts(docs):
        _plan(docs, "place")["items"][6]["condition"] = (
            "repository.countByBay(form.bay()) >= BAY_LIMIT || repository.countByBay(form.bay()) >= BAY_LIMIT")

    universe = derive_module.derive(_controlled(tmp_path, two_counts)).universe
    races = [f for f in universe["theoretical"]["factors"] if f.get("kind") == "concurrency-race"]
    assert sorted(f["atom"] for f in races) == ["0.0", "1.0"]


# --- Task 5: 렌더러와 고정 glue(REQ-104, REQ-105, REQ-116 일부) ----------------------------------------

import re  # noqa: E402

from td.detgen import render as render_module  # noqa: E402

_PLAN_ADDR = re.compile(r"^(?P<file>[^#]+)#(?P<index>[0-9.]+)@(?P<sha>[0-9a-f]{12})$")
_CASE_TAG = re.compile(r"^\s*@case:(\S+)\s*$", re.MULTILINE)


def _tree_digest(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _render_controlled(tmp_path, name="out"):
    derivation = derive_module.derive(_controlled(tmp_path / f"{name}-bundle"))
    out = tmp_path / name
    return derivation, out, render_module.render(derivation, out)


def _bundle_addresses(bundle: inputs.Bundle) -> dict:
    """번들 항목 주소 → sha 앞 12자리. 계획 항목은 conditionSha, keyparams 분기 사유는 sha256(detail)이다."""
    known = {}
    for plan in bundle.read("plans.json"):
        for item in plan["items"]:
            known[f"{plan['file']}#{item['index']}"] = item["conditionSha"][:12]
    for keyparams in bundle.read("keyparams.json"):
        for p_index, param in enumerate(keyparams.get("parameters", [])):
            for r_index, reason in enumerate(param["reasons"]):
                known[f"{keyparams['file']}#{p_index}.{r_index}"] = hashlib.sha256(reason["detail"].encode("utf-8")).hexdigest()[:12]
    return known


def _check_provenance(bundle: inputs.Bundle, derivation, out: Path) -> None:
    cases_doc = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    ids = [case["id"] for case in cases_doc["cases"]]
    assert len(ids) == len(set(ids)) == len(derivation.cases)
    tags = []
    for feature in sorted((out / "features").glob("*.feature")):
        tags += _CASE_TAG.findall(feature.read_text(encoding="utf-8"))
    assert sorted(tags) == sorted(ids)
    known = _bundle_addresses(bundle)
    plan_sources = 0
    for case in cases_doc["cases"]:
        assert case["sources"], case["id"]
        for source in case["sources"]:
            match = _PLAN_ADDR.match(source)
            if source.startswith(("graph:", "harness:")):
                continue
            assert match, source
            assert known.get(f"{match['file']}#{match['index']}") == match["sha"], source
            plan_sources += 1
        entries = list(case["values"].values()) + [entry for prior in case["setup"] for entry in prior["values"].values()]
        for entry in entries:
            assert entry["provenance"] in ("input", "derived", "generic-sentinel"), (case["id"], entry)
            assert "value" in entry
    assert plan_sources > 0
    assert cases_doc["unresolved"] == derivation.unresolved
    assert cases_doc["universe"] == derivation.universe


def test_req104_deterministic(tmp_path):
    _, out_a, written_a = _render_controlled(tmp_path / "a")
    _, out_b, written_b = _render_controlled(tmp_path / "b")
    assert written_a == written_b == sorted(written_a)
    digest_a = _tree_digest(out_a)
    assert digest_a == _tree_digest(out_b)
    assert sorted(digest_a) == written_a
    assert "cases.json" in digest_a and any(name.startswith("features/") for name in digest_a)
    text = "\n".join((out_a / name).read_text(encoding="utf-8") for name in written_a)
    assert str(tmp_path) not in text and redact.find_leaks(text) == []


def test_req105_provenance(tmp_path):
    bundle = _controlled(tmp_path / "c")
    derivation = derive_module.derive(bundle)
    render_module.render(derivation, tmp_path / "c-out")
    _check_provenance(bundle, derivation, tmp_path / "c-out")
    real = _real_bundle(tmp_path / "r")
    real_derivation = derive_module.derive(real)
    render_module.render(real_derivation, tmp_path / "r-out")
    _check_provenance(real, real_derivation, tmp_path / "r-out")


def test_render_cases_json_shape(tmp_path):
    derivation, out, _ = _render_controlled(tmp_path)
    raw = (out / "cases.json").read_text(encoding="utf-8")
    doc = json.loads(raw)
    assert raw == json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert set(doc) == {"cases", "unresolved", "universe"}
    by_id = {case.id: case for case in derivation.cases}
    for row in doc["cases"]:
        case = by_id[row["id"]]
        assert {"id", "endpoint", "rule", "sources", "values", "expect", "oracle", "assumes", "baselineProof",
                "auth", "setup"} <= set(row) <= {"id", "endpoint", "rule", "sources", "values", "expect", "oracle",
                                                 "assumes", "baselineProof", "auth", "setup", "pair", "pairwise"}
        assert row.get("pair") == case.pair and row["baselineProof"] == case.baseline_proof
        expected_keys = ({f"body.{k}" for k in case.values} | {f"query.{k}" for k in case.query}
                         | {f"path.{k}" for k in case.path})
        assert set(row["values"]) == expected_keys
        for entry in row["values"].values():
            assert set(entry) <= {"value", "provenance", "from", "transform"}
    with_source = [entry for row in doc["cases"] for entry in row["values"].values() if "from" in entry]
    assert with_source


def _scenarios(text: str) -> dict:
    """@case 태그 → 그 시나리오의 step 줄 목록."""
    blocks, current = {}, None
    for line in text.splitlines():
        stripped = line.strip()
        tag = re.match(r"^@case:(\S+)$", stripped)
        if tag:
            current = blocks.setdefault(tag.group(1), [])
        elif current is not None and stripped and not stripped.startswith("Scenario:"):
            current.append(stripped)
    return blocks


def test_render_gherkin_steps(tmp_path):
    derivation, out, written = _render_controlled(tmp_path)
    features = [name for name in written if name.startswith("features/")]
    assert len(features) == len({case.endpoint for case in derivation.cases})
    steps = {}
    assert derivation.timezone == "UTC"  # 통제 fixture의 harness.json
    for name in features:
        text = (out / name).read_text(encoding="utf-8")
        assert text.startswith("Feature: ")
        # I1: 모든 feature가 Background로 번들의 SUT 타임존을 싣는다(첫 시나리오보다 앞)
        background = text.index("  Background:\n    Given the SUT timezone is \"UTC\"\n")
        assert background < text.index("  @case:")
        assert text.count("Background:") == 1
        steps.update(_scenarios(text))
    by_id = {case.id: case for case in derivation.cases}
    for case_id, lines in steps.items():
        case = by_id[case_id]
        assert lines[0] == f'Given the case "{case_id}"'
        method, path = case.endpoint.split(" ", 1)
        assert f'And a request to "{method} {path}"' in lines
        assert lines[-2] == "When the request is sent"
        strict = case.expect["strict"]
        expected_then = (f"Then the response status is {strict}" if isinstance(strict, int)
                         else f'Then the response status is in class "{strict}"')
        assert lines[-1] == expected_then
        assert ("And the request is sent without authentication" in lines) == (case.auth == "anonymous")
        assert ("And the request has no body" in lines) == (case.rule == "empty-body")
        priors = [line for line in lines if line.startswith("And a prior request to ")]
        assert len(priors) == len(case.setup)
        for field_name, value in case.values.items():
            assert f'And body field "{field_name}" is {json.dumps(value.value, ensure_ascii=False)}' in lines
        for name, value in case.query.items():
            assert f'And query parameter "{name}" is {json.dumps(value.value, ensure_ascii=False)}' in lines
        for name, value in case.path.items():
            assert f'And path variable "{name}" is {json.dumps(value.value, ensure_ascii=False)}' in lines
    assert sorted(steps) == sorted(by_id)
    captured = [case for case in derivation.cases if any(prior["capture"] for prior in case.setup)]
    assert captured
    lines = steps[captured[0].id]
    prior = captured[0].setup[0]
    var, json_field = sorted(prior["capture"].items())[0]
    assert any(line.endswith(f'capturing "{json_field}" as "{var}"') for line in lines)


def test_render_feature_slug_collision_and_errors(tmp_path):
    derivation = derive_module.derive(_controlled(tmp_path / "b"))
    base = derivation.cases[0]
    twin = copy.deepcopy(base)
    twin.id, twin.endpoint = base.id + "-twin", base.endpoint.replace("/", "-", 1).replace(" -", " /", 1) + "-"
    collided = render_module._feature_names([base.endpoint, twin.endpoint])
    assert len(set(collided.values())) == 2
    bad = copy.deepcopy(base)
    bad.expect = dict(bad.expect, strict="6xx")
    with pytest.raises(render_module.RenderError, match="strict"):
        render_module.render(derive_module.Derivation([bad], [], {}, "UTC"), tmp_path / "bad")
    spaced = copy.deepcopy(base)
    spaced.id = "has space"
    with pytest.raises(render_module.RenderError):
        render_module.render(derive_module.Derivation([spaced], [], {}, "UTC"), tmp_path / "bad2")


@pytest.mark.parametrize("klass", ["1xx", "2xx", "3xx", "4xx", "5xx"])
def test_render_accepts_any_status_class(tmp_path, klass):
    # M3: strict 클래스는 [1-5]xx 모두 렌더된다(3xx/5xx를 4xx로 바꾸지 않는다)
    base = copy.deepcopy(derive_module.derive(_controlled(tmp_path / "b")).cases[0])
    base.expect = dict(base.expect, strict=klass, **{"class": klass})
    render_module.render(derive_module.Derivation([base], [], {}, "UTC"), tmp_path / "out")
    text = next((tmp_path / "out" / "features").glob("*.feature")).read_text(encoding="utf-8")
    assert f'Then the response status is in class "{klass}"' in text


@pytest.mark.parametrize("timezone", ["", None, "Not A Zone", 'Asia/"x"'])
def test_render_requires_sut_timezone(tmp_path, timezone):
    # I1: 타임존이 없거나 형식이 맞지 않으면 기본값으로 대신하지 않고 RenderError
    derivation = derive_module.derive(_controlled(tmp_path / "b"))
    derivation.timezone = timezone
    with pytest.raises(render_module.RenderError, match="타임존"):
        render_module.render(derivation, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_glue_checksum_and_copy(tmp_path):
    _, out, written = _render_controlled(tmp_path)
    glue = sorted(path.relative_to(render_module.GLUE_DIR).as_posix() for path in render_module.GLUE_DIR.rglob("*.java"))
    assert glue and all(name.startswith("support/") for name in glue)
    assert [name for name in written if name.startswith("glue/")] == [f"glue/{name}" for name in glue]
    for name in glue:
        assert (out / "glue" / name).read_bytes() == (render_module.GLUE_DIR / name).read_bytes()
    checksum = render_module.glue_checksum()
    assert re.fullmatch(r"[0-9a-f]{64}", checksum)
    assert render_module.glue_checksum(out / "glue") == checksum
    (out / "glue" / glue[0]).write_text("// 변조\n", encoding="utf-8")
    assert render_module.glue_checksum(out / "glue") != checksum


def test_render_rejects_null_path_variable(tmp_path):
    derivation = derive_module.derive(_controlled(tmp_path / "b"))
    case = copy.deepcopy(next(case for case in derivation.cases if case.path))
    name = next(iter(case.path))
    case.path[name] = derive_module.Value(None, "generic-sentinel")
    with pytest.raises(render_module.RenderError):
        render_module.render(derive_module.Derivation([case], [], {}, "UTC"), tmp_path / "out")


def test_observed_codes_from_cucumber_json():
    from td.detgen import observed

    def step(name, status, message=None):
        result = {"status": status}
        if message is not None:
            result["error_message"] = message
        return {"name": name, "keyword": "And ", "result": result}

    report = [{"uri": "classpath:features/x.feature", "elements": [
        {"type": "background", "steps": [step("ignored", "passed")]},
        {"type": "scenario", "tags": [{"name": "@case:ok-1"}],
         "steps": [step('the case "ok-1"', "passed"), step("the request is sent", "passed"),
                   step("the response status is 201", "passed")]},
        {"type": "scenario", "tags": [{"name": "@case:bad-1"}],
         "steps": [step('the case "bad-1"', "passed"), step("the request is sent", "passed"),
                   step("the response status is 422", "failed",
                        "java.lang.AssertionError: [DET-STATUS bad-1 400] \nexpected: 422\n but was: 400")]},
        {"type": "scenario", "tags": [],
         "steps": [step('the case "notag-1"', "passed"),
                   step('the response status is in class "2xx"', "failed",
                        "org.opentest4j.AssertionFailedError: [DET-STATUS notag-1 500] expected: 2 but was: 5")]},
        {"type": "scenario", "tags": [{"name": "@case:prior-1"}],
         "steps": [step('the case "prior-1"', "passed"),
                   step("a prior request", "failed", "[prior-1: 선행 요청 실패(상태 409)]"),
                   step("the request is sent", "skipped")]},
        {"type": "scenario", "tags": [{"name": "@case:other-1"}],
         "steps": [step("x", "failed", "[DET-STATUS someone-else 418]")]},
    ]}]
    assert observed.observed_codes(json.dumps(report)) == {
        "ok-1": None, "bad-1": 400, "notag-1": 500, "prior-1": None, "other-1": None}


# =====================================================================================
# Task 6: S06 det 경로와 스냅샷(REQ-103, REQ-110). 검증기는 깨끗한 Issues를 돌려주는 스텁이다(Gradle 없이).
# 실제 컴파일·dry-run을 거치는 S06 실행은 test_det.py(Int)가 맡는다.
# =====================================================================================
from td import bddgen  # noqa: E402
from td.detgen import render as render_mod  # noqa: E402
from td.detgen import stage as det_stage  # noqa: E402


def _clean_validator(gen_dir, out_dir):
    return bddgen.Issues()


_ABSENT = object()  # tools.lock에 pict 키를 쓰지 않는다


def write_tools_lock(run_dir: Path, pict=_ABSENT, failure: str | None = None) -> Path:
    """run 디렉터리에 tools.lock(YAML)을 쓴다. pict: dict(available) | None(`pict: null`) | _ABSENT(키 없음)."""
    import yaml
    lock = {"schema": 1, "claude": {"version": "9.9.9-test", "model": "claude-opus-5-5"}}
    if pict is not _ABSENT:
        lock["pict"] = None if pict is None else {k: pict[k] for k in ("commit", "binarySha256", "path")}
        if pict is None:
            lock["pictFailureReason"] = failure or "build-failed"
    path = Path(run_dir) / "tools.lock"
    path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")
    return path


def _det_run(tmp_path, name="run", pict=_ABSENT):
    """petclinic det fixture run 사본. pict를 주면(세션 `pict_tool` 값) tools.lock에 available pict 항목을 쓴다."""
    run = _copy(PETCLINIC_RUN, tmp_path / name)
    if pict is not _ABSENT:
        write_tools_lock(run, pict)
    return run


def _snapshot_files(directory: Path) -> dict:
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def test_det_gen_id_and_record_shape(tmp_path, pict_tool):
    out_root = tmp_path / "generated" / "petclinic"
    result = det_stage.generate_det(_det_run(tmp_path, pict=pict_tool), SUT_FILE, out_root, False,
                                    validator=_clean_validator)
    assert result.status == "passed", result.reason
    key = result.record["inputHash"]
    assert len(key) == 64 and result.gen_id == f"det-{key[:8]}-r1"
    assert result.dir == out_root / "det" / result.gen_id and (result.dir / "_COMPLETE").is_file()
    assert result.record["generator"] == {"name": "td.detgen", "version": det_stage.GENERATOR_VERSION,
                                          "glueChecksum": render_mod.glue_checksum(),
                                          "sourceChecksum": det_stage.source_checksum(),
                                          "pict": {"commit": pict_tool["commit"],
                                                   "binarySha256": pict_tool["binarySha256"]}}
    assert result.record["rep"] == 1 and result.record["arm"] == "det" and result.record["cases"] > 0
    pict_tag = f"{pict_tool['commit']}:{pict_tool['binarySha256']}"
    expected_key = hashlib.sha256((result.record["bundleHash"] + det_stage.GENERATOR_VERSION + det_stage.source_checksum()
                                   + render_mod.glue_checksum() + pict_tag).encode("utf-8")).hexdigest()
    assert key == det_stage.det_key(result.record["bundleHash"], pict_tag)
    assert key == expected_key
    assert redact.find_leaks("".join(p.read_text(encoding="utf-8") for p in result.dir.rglob("*") if p.is_file())) == []
    assert not list((out_root / "det").glob(".tmp-*"))


# 아래 세 테스트는 스냅샷 재사용·변조·재생성 로직만 본다: pict 없는 unavailable 경로로 오프라인에서 돈다.
def _det_run_offline(tmp_path, name="run"):
    """tools.lock에 pict 키가 없는 run 사본(unavailable 경로, 네트워크·툴체인 불필요). det generation은 degraded다."""
    run = _det_run(tmp_path, name)
    write_tools_lock(run)
    return run


def test_det_reuse_snapshot(tmp_path):
    out_root = tmp_path / "generated" / "petclinic"
    calls = []

    def counting(gen_dir, out_dir):
        calls.append(gen_dir)
        return bddgen.Issues()

    first = det_stage.generate_det(_det_run_offline(tmp_path, "a"), SUT_FILE, out_root, False, validator=counting)
    before = _snapshot_files(first.dir)
    second = det_stage.generate_det(_det_run_offline(tmp_path, "b"), SUT_FILE, out_root, False, validator=counting)
    assert first.reused is False and second.reused is True
    assert second.gen_id == first.gen_id and second.status == "degraded"  # pict 없음 = unavailable 경로
    assert len(calls) == 1
    assert _snapshot_files(second.dir) == before


def test_det_tampered_snapshot_is_failed_not_overwritten(tmp_path):
    out_root = tmp_path / "generated" / "petclinic"
    first = det_stage.generate_det(_det_run_offline(tmp_path, "a"), SUT_FILE, out_root, False, validator=_clean_validator)
    target = first.dir / "cases.json"
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    second = det_stage.generate_det(_det_run_offline(tmp_path, "b"), SUT_FILE, out_root, False, validator=_clean_validator)
    assert second.status == "failed" and "_COMPLETE" in second.reason
    assert target.read_text(encoding="utf-8").endswith(" ")


def test_det_regenerate_checksum_warning(tmp_path, monkeypatch):
    out_root = tmp_path / "generated" / "petclinic"
    first = det_stage.generate_det(_det_run_offline(tmp_path, "a"), SUT_FILE, out_root, False, validator=_clean_validator)
    # 같은 입력 재생성: 체크섬이 같으면 경고가 없다
    same = det_stage.generate_det(_det_run_offline(tmp_path, "b"), SUT_FILE, out_root, True, validator=_clean_validator)
    assert same.status == "degraded" and same.reused is False and same.gen_id == first.gen_id
    assert "warnings" not in same.record or same.record["warnings"] == []
    # 키를 고정한 채(glue_checksum 고정) 렌더 결과를 바꾸면 checksum-changed 경고를 남기고 교체한다
    fixed = render_mod.glue_checksum()
    glue_copy = tmp_path / "glue-copy"
    shutil.copytree(render_mod.GLUE_DIR, glue_copy)
    java = sorted(glue_copy.rglob("*.java"))[0]
    java.write_text(java.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    monkeypatch.setattr(render_mod, "GLUE_DIR", glue_copy)
    monkeypatch.setattr(render_mod, "glue_checksum", lambda root=None: fixed)
    changed = det_stage.generate_det(_det_run_offline(tmp_path, "c"), SUT_FILE, out_root, True, validator=_clean_validator)
    assert changed.gen_id == first.gen_id and changed.status == "degraded"
    assert "checksum-changed" in changed.record["warnings"]
    assert java.read_bytes() in {p.read_bytes() for p in changed.dir.rglob("*.java")}
    assert bddgen.complete_problem(changed.dir, changed.record["inputHash"]) is None
    assert not list((out_root / "det").glob(".tmp-*")) and not list((out_root / "det").glob("*.old-*"))


def test_det_missing_optional_is_degraded(tmp_path, pict_tool):
    run = _det_run(tmp_path, pict=pict_tool)
    shutil.rmtree(run / "S02" / "bbtg" / "raw" / "artifacts" / "inspect-auth")
    result = det_stage.generate_det(run, SUT_FILE, tmp_path / "generated" / "petclinic", False,
                                    validator=_clean_validator)
    assert result.status == "degraded" and "auth" in result.reason and result.dir is not None


def test_det_missing_required_is_failed(tmp_path):
    run = _det_run(tmp_path)
    (run / "S03" / "ontology-jqa-ext.json").unlink()
    result = det_stage.generate_det(run, SUT_FILE, tmp_path / "generated" / "petclinic", False,
                                    validator=_clean_validator)
    assert result.status == "failed" and "ontology-jqa-ext.json" in result.reason
    assert result.dir is None and result.gen_id is None


def test_det_validation_issue_is_failed_without_repair(tmp_path):
    calls = []

    def dirty(gen_dir, out_dir):
        calls.append(gen_dir)
        return bddgen.Issues(undefined=[{"feature": "f", "line": 1, "step": "x"}])

    out_root = tmp_path / "generated" / "petclinic"
    result = det_stage.generate_det(_det_run(tmp_path), SUT_FILE, out_root, False, validator=dirty)
    assert result.status == "failed" and "undefined" in result.reason and len(calls) == 1
    assert not (out_root / "det" / result.gen_id).exists()
    assert not list((out_root / "det").glob(".tmp-*")) and not list((out_root / "det" / ".reserve").iterdir())


# --- Task 8: 결과 집계(td.detgen.results) ----------------------------------------------------------
_SUMMARY_GEN_ID = "det-0123abcd-r1"


def _case(case_id, endpoint, rule, strict, klass, pair=None, bbtg=None, graph=None):
    expect = {"strict": strict, "class": klass, "source": "rule"}
    if bbtg is not None:
        expect["bbtgCode"] = bbtg
    if graph is not None:
        expect["graphStatus"] = graph
    entry = {"id": case_id, "endpoint": endpoint, "rule": rule, "sources": [f"src:{case_id}"], "values": {}, "expect": expect,
             "oracle": "status", "assumes": [], "baselineProof": [], "auth": "authed", "setup": []}
    if pair is not None:
        entry["pair"] = pair
    return entry


# (case, endpoint, rule, strict, class, pair, bbtgCode, graphStatus, 실행 결과, 관측 코드)
_SUMMARY_CASES = [
    ("a-base", "POST /a", "baseline-valid", "2xx", "2xx", None, None, None, "passed", None),
    ("a-vb", "POST /a", "valid-boundary", "2xx", "2xx", None, None, None, "passed", None),
    ("a-v1", "POST /a", "violation", 400, "4xx", "a-vb", 400, 422, "failed", 422),     # strict 실패, class 통과, 상태 불일치
    ("a-v2", "POST /a", "violation", "4xx", "4xx", "a-vb", 400, 400, "passed", None),  # 검증된 위반
    ("a-v3", "POST /a", "violation", "4xx", "4xx", None, None, None, "passed", None),  # 짝 없음
    ("b-base", "PUT /b", "baseline-valid", "2xx", "2xx", None, None, None, "failed", 500),
    ("b-v1", "PUT /b", "violation", 400, "4xx", "b-vb", 400, 422, "passed", None),     # baseline 실패로 막힘
    ("b-vb", "PUT /b", "valid-boundary", "2xx", "2xx", None, None, None, "passed", None),
    ("b-v2", "PUT /b", "violation", "4xx", "4xx", "b-vb", None, None, "failed", None),  # 관측 코드 없음
    ("c-h", "GET /c", "happy", "2xx", "2xx", None, None, None, "undefined", None),      # 실행 안 됨
]


def make_det_results(root: Path, gen_id: str = _SUMMARY_GEN_ID, rows=None) -> tuple[Path, Path]:
    """합성 det generation 디렉터리와 S07 generation 디렉터리(cucumber.json, scenario-results.json)."""
    from td import scenarios
    rows = rows if rows is not None else _SUMMARY_CASES
    gen_dir = root / "generated" / gen_id
    s07_dir = root / "S07" / gen_id
    (gen_dir / "features").mkdir(parents=True)
    s07_dir.mkdir(parents=True)
    by_endpoint: dict[str, list] = {}
    for row in rows:
        by_endpoint.setdefault(row[1], []).append(row)
    features = []
    for index, (endpoint, items) in enumerate(sorted(by_endpoint.items())):
        lines = [f"Feature: {endpoint}", ""]
        elements = []
        for row in items:
            case_id, status, code = row[0], row[8], row[9]
            lines += [f"  @case:{case_id}", f"  Scenario: {case_id}", f'    Given the case "{case_id}"',
                      "    When the request is sent", "    Then the response status is in class \"2xx\"", ""]
            message = None
            if status == "failed":
                message = (f"java.lang.AssertionError: [DET-STATUS {case_id} {code}] expected" if code is not None
                           else "java.net.ConnectException: Connection refused")
            last = {"status": status if status != "undefined" else "undefined"}
            if message:
                last["error_message"] = message
            elements.append({"type": "scenario", "tags": [{"name": f"@case:{case_id}"}],
                             "steps": [{"name": f'the case "{case_id}"', "result": {"status": "passed"}},
                                       {"name": "the response status", "result": last}]})
        (gen_dir / "features" / f"f{index}.feature").write_text("\n".join(lines), encoding="utf-8")
        features.append({"uri": f"features/f{index}.feature", "elements": elements})
    (s07_dir / "cucumber.json").write_text(json.dumps(features), encoding="utf-8")
    statuses = {row[0]: row[8] for row in rows}
    ident = scenarios.GenIdent.from_gen_id(gen_id)
    refs = scenarios.pickle_refs(gen_dir, ident)
    with (s07_dir / "scenario-results.json").open("w", encoding="utf-8") as handle:
        for ref in refs:
            handle.write(json.dumps({"testId": ref.test_id, "status": statuses[ref.name], "requests": 1, "exec": None}) + "\n")
    cases = [_case(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rows]
    universe = {"bySlot": {"total": len(rows) + 1, "generated": len(rows), "unresolved": 1, "deduplicated": 0, "byReason": {}},
                "byRule": {}, "theoretical": {"value": 42, "formula": "f", "factors": [
                    {"endpoint": "POST /a", "fields": {"body.x": 3}, "product": 3},
                    {"endpoint": "PUT /b", "item": "src:b", "atom": "count", "kind": "concurrency-race", "outOfScope": True}]}}
    (gen_dir / "cases.json").write_text(json.dumps({"cases": cases, "unresolved": [{"source": "src:u", "reason": "unparsed"}],
                                                    "universe": universe}), encoding="utf-8")
    return gen_dir, s07_dir


def test_results_summarize(tmp_path):
    from td.detgen import results
    gen_dir, s07_dir = make_det_results(tmp_path)
    summary = results.summarize(gen_dir, s07_dir)
    assert summary["cases"] == 10 and summary["unresolved"] == 1
    assert summary["universe"]["theoretical"]["value"] == 42
    assert summary["passStrict"] == {"passed": 6, "total": 10}
    assert summary["passClass"] == {"passed": 7, "total": 10}  # a-v1은 관측 422가 4xx라 class 통과
    assert summary["baselineValid"] == {"POST /a": "passed", "PUT /b": "failed"}
    assert summary["blockedByBaseline"] == 2      # PUT /b의 위반 b-v1, b-v2
    assert summary["verifiedViolations"] == 1     # a-v2만(a-v1 실패, a-v3 짝 없음, b-v1 baseline 실패)
    assert summary["unpaired"] == 1
    assert summary["classUnknown"] == 1           # b-v2: 실패했지만 관측 코드가 없다
    assert summary["notRun"] == 1                 # c-h: undefined
    assert summary["byRule"] == {"baseline-valid": {"generated": 2, "passedStrict": 1},
                                 "happy": {"generated": 1, "passedStrict": 0},
                                 "valid-boundary": {"generated": 2, "passedStrict": 2},
                                 "violation": {"generated": 5, "passedStrict": 3}}
    assert summary["statusMismatch"] == [{"case": "a-v1", "bbtgCode": 400, "graphStatus": 422, "observed": 422},
                                         {"case": "b-v1", "bbtgCode": 400, "graphStatus": 422, "observed": 400}]
    reasons = {item["case"]: item["reason"] for item in summary["classUnknownCases"]}
    assert set(reasons) == {"b-v2", "c-h"} and "undefined" in reasons["c-h"]
    assert summary["pairwise"] is None  # universe.pairwise 없음(disabled) → null


def test_results_summarize_without_s07_outputs(tmp_path):
    """S07 결과가 없으면 모든 케이스가 실행 안 됨으로 집계되고 예외가 나지 않는다."""
    from td.detgen import results
    gen_dir, s07_dir = make_det_results(tmp_path)
    (s07_dir / "cucumber.json").unlink()
    (s07_dir / "scenario-results.json").unlink()
    summary = results.summarize(gen_dir, s07_dir)
    assert summary["passStrict"] == {"passed": 0, "total": 10} and summary["notRun"] == 10
    assert summary["verifiedViolations"] == 0 and summary["blockedByBaseline"] == 0
    assert summary["baselineValid"] == {"POST /a": "notRun", "PUT /b": "notRun"}


# --- 최종 리뷰 수정(I1, M3, M4, M5) ------------------------------------------------------------------
def test_status_class_follows_code():
    # M3: 엄격 코드의 클래스는 백의 자리를 따른다(3xx/5xx를 4xx로 바꾸지 않는다)
    from td.detgen.endpoints import Catalog, status_class
    assert [status_class(code) for code in (200, 201, 302, 404, 422, 503)] == ["2xx", "2xx", "3xx", "4xx", "4xx", "5xx"]
    assert status_class(None) == "4xx" and status_class(True) == "4xx" and status_class(700) == "4xx"
    catalog = Catalog({"nodes": []}, {"exceptions": {"x.Svc$Unavailable": {"status": 503, "handler": None}}}, {})
    assert catalog.expect("code=302") == {"strict": 302, "class": "3xx", "source": "bbtg", "bbtgCode": 302}
    graph = catalog.expect("Unavailable code=400")
    assert graph["strict"] == 503 and graph["class"] == "5xx" and graph["source"] == "graph"


def test_background_keeps_pickle_and_case_mapping(tmp_path):
    # I1: Background는 pickle이 아니다. testId·@case 매핑과 결과 집계가 Background가 있어도 시나리오 줄로 맞아야 한다
    from td import scenarios
    from td.detgen import results
    derivation = derive_module.derive(_controlled(tmp_path / "b"))
    gen_dir = tmp_path / "det-0123abcd-r1"
    render_module.render(derivation, gen_dir)
    ident = scenarios.GenIdent.from_gen_id(gen_dir.name)
    refs = scenarios.pickle_refs(gen_dir, ident)
    assert len(refs) == len(derivation.cases)
    for ref in refs:
        lines = (gen_dir / ref.feature).read_text(encoding="utf-8").splitlines()
        assert lines[ref.line - 1].strip() == f"Scenario: {ref.name}"
        assert results._case_by_line("\n".join(lines))[ref.line] == ref.name
    failed_case = derivation.cases[0].id
    s07_dir = tmp_path / "S07"
    s07_dir.mkdir()
    with (s07_dir / "scenario-results.json").open("w", encoding="utf-8") as handle:
        for ref in refs:
            status = "failed" if ref.name == failed_case else "passed"
            handle.write(json.dumps({"testId": ref.test_id, "status": status, "requests": 1, "exec": None}) + "\n")
    summary = results.summarize(gen_dir, s07_dir)
    total = len(derivation.cases)
    assert summary["passStrict"] == {"passed": total - 1, "total": total}
    assert summary["notRun"] == 0
    assert [item["case"] for item in summary["classUnknownCases"]] == [failed_case]


def test_det_key_includes_generator_source_checksum(tmp_path, monkeypatch):
    # M5: 생성기 소스(td/detgen/*.py) 한 바이트가 바뀌면 키(genId)가 바뀐다
    source_copy = tmp_path / "detgen"
    shutil.copytree(det_stage.SOURCE_DIR, source_copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(det_stage, "SOURCE_DIR", source_copy)
    input_hash = "0" * 64
    before_checksum, before_key = det_stage.source_checksum(), det_stage.det_key(input_hash, "none")
    assert before_checksum == det_stage.source_checksum(Path(det_stage.__file__).parent)
    target = source_copy / "render.py"
    target.write_bytes(target.read_bytes() + b"#")
    assert det_stage.source_checksum() != before_checksum
    changed_key = det_stage.det_key(input_hash, "none")
    assert changed_key != before_key
    (source_copy / "notes.txt").write_text("x", encoding="utf-8")  # *.py가 아닌 파일은 키에 들어가지 않는다
    assert det_stage.det_key(input_hash, "none") == changed_key


def test_bdd_gen_schema_separates_llm_and_det_records(tmp_path, pict_tool):
    # M4: det 기록은 detGeneration 분기로만 통과하고, LLM 모양의 det 기록은 거부된다
    import jsonschema
    schema = json.loads((REPO_ROOT / "site-gen" / "td" / "schemas" / "bdd-gen.schema.json").read_text(encoding="utf-8"))
    result = det_stage.generate_det(_det_run(tmp_path, pict=pict_tool), SUT_FILE, tmp_path / "generated" / "petclinic", False,
                                    validator=_clean_validator)
    document = {"schema": 1, "runId": None, "sut": "petclinic", "reps": 1, "regenerate": False, "maxRepairs": 0,
                "strippedFields": [], "generations": [result.record]}
    jsonschema.validate(document, schema)
    llm_record = {"genId": "base-0123abcd-r1", "arm": "base", "rep": 1, "gen": 1, "status": "passed", "reason": None,
                  "reused": False, "inputHash": "a" * 64, "bundleHash": "b" * 64, "promptHash": "c" * 64,
                  "repairPromptHash": "d" * 64, "model": "m", "cliVersion": "1", "flags": ["-p"], "repairs": 0,
                  "tokens": {"in": 1, "out": 1}, "seconds": 1.0, "strippedFields": [], "dir": None}
    jsonschema.validate({**document, "generations": [llm_record]}, schema)
    det_shaped_llm = {**llm_record, "genId": "det-0123abcd-r1", "arm": "det"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**document, "generations": [det_shaped_llm]}, schema)
    for key, value in (("genId", "det-0123abcd-r1"), ("arm", "det")):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**document, "generations": [{**llm_record, key: value}]}, schema)


def test_det_leak_check_joins_files_with_newline(tmp_path, monkeypatch, pict_tool):
    # L1: 누출 검사는 파일 내용을 줄바꿈으로 이어 붙인다(파일 경계에서 토큰이 붙어 생기는 오탐·미탐 방지)
    seen = []
    original = det_stage.redact.find_leaks

    def spy(text, *args, **kwargs):
        seen.append(text)
        return original(text, *args, **kwargs)

    monkeypatch.setattr(det_stage.redact, "find_leaks", spy)
    result = det_stage.generate_det(_det_run(tmp_path, pict=pict_tool), SUT_FILE, tmp_path / "generated" / "petclinic", False,
                                    validator=_clean_validator)
    assert result.status == "passed", result.reason
    joined = seen[-1]
    texts = [(result.dir / rel).read_text(encoding="utf-8") for rel in det_stage.snapshot.tree_files(result.dir)
             if rel != "_COMPLETE"]
    assert joined == "\n".join(texts)
