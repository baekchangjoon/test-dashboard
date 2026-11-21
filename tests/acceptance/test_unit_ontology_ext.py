"""td.ontology_ext 단위 테스트: 가짜 runner(질의 파일 이름 -> 행 목록)로 jQA 보강 그래프 조립을 확인한다(REQ-101 단위 근거)."""
import json
from pathlib import Path

import jsonschema
import pytest

from td import ontology_ext

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT_QUERIES = REPO_ROOT / "ontology" / "jqa" / "queries" / "ext"
SCHEMA = REPO_ROOT / "site-gen" / "td" / "schemas" / "ontology-ext.schema.json"
QUERY_NAMES = ("dto_fields", "enums", "constants", "handler_calls", "handler_params", "exception_status", "response_dtos")
HANDLER_TYPE = "a.C$Handler"


def _fake_runner(rows_by_name: dict[str, list[dict]]):
    """질의 본문을 실제 ext 질의 파일과 맞춰 파일 이름을 찾고, 그 이름에 준비한 행을 돌려준다."""
    text_to_name = {(EXT_QUERIES / f"{name}.cypher").read_text(): name for name in QUERY_NAMES}

    def run(cypher: str) -> list[dict]:
        name = text_to_name.get(cypher)
        if name is None:
            raise AssertionError("ext 질의 파일이 아닌 질의가 실행되었다")
        return rows_by_name.get(name, [])
    return run


def _base(*, dtos=(), endpoints=(), exceptions=()):
    nodes = [{"id": f"dto:{fqn}", "kind": "DTO", "label": fqn, "props": {"fqn": fqn}} for fqn in dtos]
    for node_id, handler in endpoints:
        method, path = node_id.removeprefix("endpoint:").split(" ", 1)
        nodes.append({"id": node_id, "kind": "Endpoint", "label": f"{method} {path}",
                      "props": {"method": method, "path": path, "handler": handler, "view": False}})
    for fqn, handlers in exceptions:
        nodes.append({"id": f"exception:{fqn}", "kind": "Exception", "label": fqn,
                      "props": {"fqn": fqn, "handlers": list(handlers)}})
    return {"nodes": nodes, "edges": [], "meta": {"tool": "jqassistant", "version": "2.9.1", "commit": "c", "fallbacks": []}}


def _export(rows_by_name, base=None):
    return ontology_ext.export_with_runner(_fake_runner(rows_by_name), EXT_QUERIES, base=base or _base())


def test_unit_ext_queries_exist():
    assert {p.stem for p in EXT_QUERIES.glob("*.cypher")} == set(QUERY_NAMES)


def test_ext_dto_fields():
    rows = [{"dto": "a.Req", "name": "nights", "type": "int"},
            {"dto": "a.Req", "name": "checkIn", "type": "java.time.LocalDate"}]
    ext = _export({"dto_fields": rows}, _base(dtos=["a.Req"]))
    fields = ext["dtos"]["a.Req"]["fields"]
    assert len(fields) == 2
    assert fields == [{"name": "checkIn", "type": "java.time.LocalDate"}, {"name": "nights", "type": "int"}]


def test_ext_dto_fields_ignore_types_not_in_base_dtos():
    ext = _export({"dto_fields": [{"dto": "a.Other", "name": "x", "type": "int"}]}, _base(dtos=["a.Req"]))
    assert ext["dtos"] == {"a.Req": {"fields": []}}


def test_ext_enum_excludes_synthetic():
    rows = [{"enum": "a.Tier", "name": "VIP", "synthetic": None},
            {"enum": "a.Tier", "name": "$VALUES", "synthetic": True},
            {"enum": "a.Tier", "name": "BASIC", "synthetic": None}]
    ext = _export({"enums": rows})
    assert ext["enums"] == {"a.Tier": {"constants": ["BASIC", "VIP"]}}


def test_ext_constant_value():
    rows = [{"owner": "a.B", "name": "CAP", "type": "int", "value": 2, "synthetic": None}]
    ext = _export({"constants": rows})
    assert ext["constants"] == [{"owner": "a.B", "name": "CAP", "type": "int", "value": 2}]


@pytest.mark.parametrize("builders, status_fields, expected", [
    (["unprocessableEntity", "body"], [], 422),
    (["badRequest", "body"], [], 400),
    (["notFound", "build"], [], 404),
    (["status", "body"], ["CONFLICT"], 409),
    # 실제 jQA는 외부 메서드에 name이 없고 signature만 있다. 시그니처에서 이름을 뽑는다.
    (["org.springframework.http.ResponseEntity$BodyBuilder unprocessableEntity()",
      "org.springframework.http.ResponseEntity body(java.lang.Object)"], [], 422),
    (["org.springframework.http.ResponseEntity$BodyBuilder status(org.springframework.http.HttpStatusCode)"],
     ["org.springframework.http.HttpStatus NOT_FOUND"], 404),
    (["teapot", "body"], [], None),
    (["status"], [], None),                         # status(...)인데 읽은 HttpStatus 상수가 없다
    (["badRequest", "notFound"], [], None),         # 서로 다른 코드가 둘이면 정하지 않는다
])
def test_ext_exception_status_builders(builders, status_fields, expected):
    handler = f"{HANDLER_TYPE}#on"
    rows = [{"handler": handler, "builders": builders, "statusFields": status_fields}]
    ext = _export({"exception_status": rows}, _base(exceptions=[("a.Ex", [handler])]))
    entry = ext["exceptions"]["a.Ex"]
    assert entry["handler"] == handler
    if expected is None:
        assert "status" not in entry
    else:
        assert entry["status"] == expected


def test_ext_exception_without_handler_has_null_handler():
    ext = _export({}, _base(exceptions=[("a.Ex", [])]))
    assert ext["exceptions"] == {"a.Ex": {"handler": None}}


def test_ext_calls_map_endpoint():
    rows = [{"controller": "a.C", "handlerName": "get", "service": "a.S", "method": "getById"},
            {"controller": "a.C", "handlerName": "helper", "service": "a.S", "method": "list"}]
    base = _base(endpoints=[("endpoint:GET /api/x/{id}", "a.C#get")])
    ext = _export({"handler_calls": rows}, base)
    assert ext["calls"] == [
        {"endpoint": None, "handler": "a.C#helper", "service": "a.S", "method": "list"},
        {"endpoint": "endpoint:GET /api/x/{id}", "handler": "a.C#get", "service": "a.S", "method": "getById"},
    ]


def test_ext_endpoint_params_and_response_dto():
    base = _base(dtos=["a.Resp"], endpoints=[("endpoint:GET /api/x/{id}", "a.C#get"), ("endpoint:GET /", "a.W#home")])
    params = [
        {"controller": "a.C", "handlerName": "get", "index": 1, "type": "boolean",
         "annotation": "org.springframework.web.bind.annotation.RequestParam", "values": [{"name": "defaultValue", "value": "true"}]},
        {"controller": "a.C", "handlerName": "get", "index": 0, "type": "java.lang.Integer",
         "annotation": "org.springframework.web.bind.annotation.PathVariable", "values": [{"name": "value", "value": "id"}]},
        {"controller": "a.C", "handlerName": "get", "index": 2, "type": "a.Model",
         "annotation": "jakarta.validation.Valid", "values": []},
    ]
    responses = [{"controller": "a.C", "handlerName": "get", "type": "a.Resp"},
                 {"controller": "a.C", "handlerName": "get", "type": "a.Entity"}]
    ext = _export({"handler_params": params, "response_dtos": responses}, base)
    assert ext["endpoints"]["endpoint:GET /api/x/{id}"] == {
        "params": [
            {"index": 0, "kind": "PathVariable", "type": "java.lang.Integer", "name": "id", "defaultValue": None, "required": None},
            {"index": 1, "kind": "RequestParam", "type": "boolean", "name": None, "defaultValue": "true", "required": None},
        ],
        "responseDto": "a.Resp",
    }
    assert ext["endpoints"]["endpoint:GET /"] == {"params": [], "responseDto": None}


def test_ext_schema_valid():
    handler = f"{HANDLER_TYPE}#onValidation"
    base = _base(dtos=["a.Req"], endpoints=[("endpoint:POST /api/x", "a.C#create")], exceptions=[("a.Ex", [handler])])
    ext = _export({
        "dto_fields": [{"dto": "a.Req", "name": "nights", "type": "int"}],
        "enums": [{"enum": "a.Tier", "name": "VIP", "synthetic": None}],
        "constants": [{"owner": "a.S", "name": "CAP", "type": "int", "value": 2, "synthetic": None}],
        "handler_calls": [{"controller": "a.C", "handlerName": "create", "service": "a.S", "method": "create"}],
        "handler_params": [{"controller": "a.C", "handlerName": "create", "index": 0, "type": "a.Req",
                            "annotation": "org.springframework.web.bind.annotation.RequestBody",
                            "values": [{"name": "required", "value": False}]}],
        "exception_status": [{"handler": handler, "builders": ["unprocessableEntity"], "statusFields": []}],
        "response_dtos": [],
    }, base)
    assert ext["schema"] == 1
    jsonschema.validate(ext, json.loads(SCHEMA.read_text()))


def test_ext_output_is_sorted_and_deterministic(tmp_path):
    rows = {"constants": [{"owner": "b.B", "name": "Y", "type": "int", "value": 1, "synthetic": None},
                          {"owner": "a.A", "name": "X", "type": "java.lang.String", "value": "s", "synthetic": None}]}
    first = ontology_ext.dumps(_export(rows))
    rows["constants"].reverse()
    assert ontology_ext.dumps(_export(rows)) == first
    assert [c["owner"] for c in json.loads(first)["constants"]] == ["a.A", "b.B"]


def test_unit_ext_cli_failure_returns_1_without_output(tmp_path, capsys):
    out = tmp_path / "ext.json"
    rc = ontology_ext.main(["export", "--bolt-port", "1", "--base", str(tmp_path / "missing.json"), "--out", str(out)])
    assert rc == 1 and not out.exists()
    assert "보강 질의 실패" in capsys.readouterr().err


def test_unit_ext_missing_query_error_has_no_absolute_path(tmp_path):
    with pytest.raises(ontology_ext.OntologyExtError) as caught:
        ontology_ext.export_with_runner(lambda cypher: [], tmp_path / "nowhere", base=_base())
    assert str(tmp_path) not in str(caught.value) and "ext/dto_fields.cypher" in str(caught.value)


def test_ext_exception_status_conflicting_overload_rows_emit_no_status():
    handler = f"{HANDLER_TYPE}#on"
    rows = [{"handler": handler, "builders": ["badRequest"], "statusFields": []},
            {"handler": handler, "builders": ["notFound"], "statusFields": []}]
    ext = _export({"exception_status": rows}, _base(exceptions=[("a.Ex", [handler])]))
    assert ext["exceptions"]["a.Ex"] == {"handler": handler}


# --- 실제 저장소 fixture(REQ-101 값) -----------------------------------------------------------------------------
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "det" / "petclinic"
BOARDING = "org.springframework.samples.petclinic.boarding."


def test_unit_ext_fixture_matches_req101():
    ext = json.loads((FIXTURE / "ext.json").read_text())
    jsonschema.validate(ext, json.loads(SCHEMA.read_text()))
    field_counts = {fqn.rsplit("$", 1)[-1]: len(entry["fields"]) for fqn, entry in ext["dtos"].items()}
    assert field_counts == {"CreateReservationRequest": 10, "UpdateReservationRequest": 2,
                            "ReservationResponse": 12, "LoginRequest": 2}
    assert len(ext["enums"][BOARDING + "PriceTier"]["constants"]) == 3
    assert len(ext["enums"][BOARDING + "ReservationStatus"]["constants"]) == 4
    assert {"owner": BOARDING + "ReservationService", "name": "ROOM_CAPACITY", "type": "int", "value": 2} in ext["constants"]
    assert len(ext["calls"]) >= 6 and all(call["endpoint"] for call in ext["calls"])
    statuses = {fqn.rsplit("$", 1)[-1]: entry.get("status") for fqn, entry in ext["exceptions"].items()}
    assert statuses == {"ReservationValidationException": 422, "ReservationConflictException": 409,
                        "ReservationNotFoundException": 404, "ReservationBadRequestException": 400}


# --- S03 사유 자르기(td_tail_chars) ------------------------------------------------------------------------------
def _bash(script: str, tmp_path) -> "subprocess.CompletedProcess":
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(tmp_path), TD_RUN_DIR=str(tmp_path))
    header = f'source "{REPO_ROOT}/pipeline/lib/common.sh"\n'
    return subprocess.run(["bash", "-c", header + script], capture_output=True, env=env, timeout=60)


def test_unit_tail_chars_keeps_multibyte_boundary_intact(tmp_path):
    # '가나다 error'는 15바이트다. 바이트 11개로 자르면 '나'가 쪼개지지만 문자 단위로는 마지막 7자 '다 error'다.
    done = _bash("printf '%s' '가나다 error' | td_tail_chars 7; echo '|'; printf 'short' | td_tail_chars 600", tmp_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout.decode("utf-8") == "다 error|\nshort"


def test_unit_tail_chars_reason_records_in_stage_state(tmp_path):
    """잘린 사유가 td_stage_end -> td.state로 그대로 기록된다(실패 격리 경로, REQ-110)."""
    done = _bash('td_stage_begin S03\n'
                 'REASON="ext export 실패: $(printf \'%s\' "가나다 error" | td_tail_chars 7)"\n'
                 'td_stage_end S03 degraded "$REASON"', tmp_path)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert json.loads((tmp_path / "stages" / "S03.json").read_text(encoding="utf-8"))["reason"] == "ext export 실패: 다 error"
