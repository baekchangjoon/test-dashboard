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
