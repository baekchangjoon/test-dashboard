"""S03 jQA 보강 그래프: 실행 중인 jQA server(Bolt)에 ontology/jqa/queries/ext의 고정 Cypher 묶음을 질의해
`ontology-jqa-ext.json`(설계 2026-11-22-deterministic-arm §5.1, 스키마 schemas/ontology-ext.schema.json)을 만든다.

기존 `ontology-jqa.json`과 그 질의·스키마는 바꾸지 않는다(기존 arm 입력 불변, REQ-102). 엔드포인트 id, DTO 집합, 예외 -> 핸들러
대응은 기존 온톨로지(base)에서 가져온다. 질의 실행기는 td.ontology_jqa.bolt_runner를 그대로 쓴다.

사용:
  python -m td.ontology_ext export --bolt-port N --base <ontology-jqa.json> --out <ext.json> [--queries <dir>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable

from td import ontology_jqa

Row = dict
Runner = Callable[[str], list[Row]]

DEFAULT_QUERIES = ontology_jqa.DEFAULT_QUERIES / "ext"
QUERY_NAMES = ("dto_fields", "enums", "constants", "handler_calls", "handler_params", "exception_status", "response_dtos")
SPRING_BIND = "org.springframework.web.bind.annotation."
PARAM_KINDS = ("PathVariable", "RequestParam", "RequestBody")

# Spring 문법 지식(설계 §5.1, §5.6 허용 리터럴): ResponseEntity 정적 빌더 이름 -> 상태 코드.
STATUS_BUILDERS = {"badRequest": 400, "unprocessableEntity": 422, "notFound": 404, "ok": 200, "noContent": 204,
                   "created": 201, "accepted": 202, "internalServerError": 500}
# `ResponseEntity.status(HttpStatus.X)`에서 READS한 HttpStatus 상수 -> 상태 코드.
HTTP_STATUS = {"BAD_REQUEST": 400, "UNAUTHORIZED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404, "CONFLICT": 409,
               "UNPROCESSABLE_ENTITY": 422, "OK": 200, "CREATED": 201, "NO_CONTENT": 204}

_SIGNATURE_METHOD = re.compile(r"(?:^|\s)([\w$<>]+)\(")


class OntologyExtError(Exception):
    pass


def _member_name(value: str | None) -> str | None:
    """jQA 외부 멤버는 name 없이 signature만 있다. `R name(args)` -> name, `T NAME` -> NAME, 이미 이름이면 그대로."""
    if not value:
        return None
    if "(" in value:
        match = _SIGNATURE_METHOD.search(value)
        return match.group(1) if match else None
    return value.rsplit(" ", 1)[-1]


def _read(queries_dir: Path, name: str) -> str:
    path = Path(queries_dir) / f"{name}.cypher"
    if not path.is_file():
        raise OntologyExtError(f"Cypher 파일이 없다: {path}")
    return path.read_text()


def _base_index(base: dict) -> tuple[set[str], dict[str, list[str]], dict[str, list[str]]]:
    """(DTO fqn 집합, handler -> endpoint id 목록, 예외 fqn -> handler 목록)."""
    dtos: set[str] = set()
    endpoints_by_handler: dict[str, list[str]] = {}
    exceptions: dict[str, list[str]] = {}
    for node in base.get("nodes", []):
        props = node.get("props") or {}
        if node["kind"] == "DTO":
            dtos.add(props.get("fqn") or node["id"].removeprefix("dto:"))
        elif node["kind"] == "Endpoint":
            endpoints_by_handler.setdefault(props["handler"], []).append(node["id"])
        elif node["kind"] == "Exception":
            exceptions[props.get("fqn") or node["id"].removeprefix("exception:")] = sorted(props.get("handlers") or [])
    return dtos, endpoints_by_handler, exceptions


def _dtos(rows: list[Row], dto_set: set[str]) -> dict:
    result: dict[str, dict] = {fqn: {"fields": []} for fqn in dto_set}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["dto"], row["name"])
        if row["dto"] in result and key not in seen:
            seen.add(key)
            result[row["dto"]]["fields"].append({"name": row["name"], "type": row.get("type")})
    for entry in result.values():
        entry["fields"].sort(key=lambda f: f["name"])
    return result


def _enums(rows: list[Row]) -> dict:
    result: dict[str, set[str]] = {}
    for row in rows:
        if row.get("synthetic") is True or row["name"].startswith("$"):
            continue  # 합성 $VALUES 배열은 상수가 아니다
        result.setdefault(row["enum"], set()).add(row["name"])
    return {fqn: {"constants": sorted(names)} for fqn, names in result.items()}


def _constants(rows: list[Row]) -> list[dict]:
    result = {(row["owner"], row["name"]): {"owner": row["owner"], "name": row["name"], "type": row.get("type"),
                                            "value": row.get("value")}
              for row in rows if row.get("synthetic") is not True}
    return [result[key] for key in sorted(result)]


def _calls(rows: list[Row], endpoints_by_handler: dict[str, list[str]]) -> list[dict]:
    result = []
    for row in rows:
        handler = f"{row['controller']}#{row['handlerName']}"
        for endpoint in endpoints_by_handler.get(handler) or [None]:
            result.append({"endpoint": endpoint, "handler": handler, "service": row["service"], "method": row["method"]})
    unique = {json.dumps(call, sort_keys=True): call for call in result}
    return sorted(unique.values(), key=lambda c: (c["endpoint"] or "", c["handler"], c["service"], c["method"]))


def _param(row: Row) -> dict | None:
    annotation = row.get("annotation") or ""
    kind = annotation.removeprefix(SPRING_BIND)
    if not annotation.startswith(SPRING_BIND) or kind not in PARAM_KINDS:
        return None
    values = {v["name"]: v.get("value") for v in (row.get("values") or []) if v.get("name")}
    # HTTP 이름은 애노테이션의 name/value가 우선이고, 없으면 바이트코드의 파라미터 이름(-parameters 없으면 null)이다.
    name = values.get("name") or values.get("value") or row.get("parameterName")
    return {"index": row["index"], "kind": kind, "type": row.get("type"), "name": name,
            "defaultValue": values.get("defaultValue"), "required": values.get("required")}


def _params_by_handler(rows: list[Row]) -> dict[str, list[dict]]:
    by_handler: dict[str, dict[int, dict]] = {}
    for row in sorted(rows, key=lambda r: (r["controller"], r["handlerName"], r["index"], r.get("annotation") or "")):
        param = _param(row)
        if param is not None:
            # 같은 이름의 오버로드가 같은 index를 내면 먼저 온(정렬상 앞선) 행을 쓴다.
            by_handler.setdefault(f"{row['controller']}#{row['handlerName']}", {}).setdefault(param["index"], param)
    return {handler: [params[i] for i in sorted(params)] for handler, params in by_handler.items()}


def _response_dtos(rows: list[Row], dto_set: set[str]) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for row in rows:
        if row.get("type") in dto_set:
            candidates.setdefault(f"{row['controller']}#{row['handlerName']}", set()).add(row["type"])
    # 후보가 여럿이면 정하지 않는다(지어내지 않는다).
    return {handler: next(iter(types)) for handler, types in candidates.items() if len(types) == 1}


def _endpoints(base: dict, params: dict[str, list[dict]], responses: dict[str, str]) -> dict:
    result = {}
    for node in base.get("nodes", []):
        if node["kind"] == "Endpoint":
            handler = node["props"]["handler"]
            result[node["id"]] = {"params": params.get(handler, []), "responseDto": responses.get(handler)}
    return result


def handler_status(builders: list[str], status_fields: list[str]) -> int | None:
    """핸들러가 부른 ResponseEntity 빌더와 읽은 HttpStatus 상수로 상태 코드를 정한다. 하나로 정해지지 않으면 None."""
    names = {_member_name(b) for b in builders or []} - {None}
    codes = {STATUS_BUILDERS[n] for n in names if n in STATUS_BUILDERS}
    if "status" in names:
        codes |= {HTTP_STATUS[f] for f in {_member_name(s) for s in status_fields or []} if f in HTTP_STATUS}
    return codes.pop() if len(codes) == 1 else None


def _exceptions(rows: list[Row], exception_handlers: dict[str, list[str]]) -> dict:
    status_by_handler = {row["handler"]: handler_status(row.get("builders"), row.get("statusFields")) for row in rows}
    result = {}
    for fqn, handlers in exception_handlers.items():
        handler = handlers[0] if handlers else None  # 여럿이면 정렬상 첫 핸들러(base가 정렬해 둔다)
        entry: dict = {"handler": handler}
        status = status_by_handler.get(handler) if handler else None
        if status is not None:
            entry["status"] = status
        result[fqn] = entry
    return result


def export_with_runner(run: Runner, queries_dir: Path, *, base: dict) -> dict:
    """질의 실행기(Cypher -> 행 목록)와 기존 온톨로지(base)로 보강 그래프를 만든다. 서버 없이 시험할 수 있게 분리했다."""
    rows = {name: run(_read(queries_dir, name)) for name in QUERY_NAMES}
    dto_set, endpoints_by_handler, exception_handlers = _base_index(base)
    return {
        "schema": 1,
        "dtos": _dtos(rows["dto_fields"], dto_set),
        "enums": _enums(rows["enums"]),
        "constants": _constants(rows["constants"]),
        "calls": _calls(rows["handler_calls"], endpoints_by_handler),
        "endpoints": _endpoints(base, _params_by_handler(rows["handler_params"]), _response_dtos(rows["response_dtos"], dto_set)),
        "exceptions": _exceptions(rows["exception_status"], exception_handlers),
    }


def dumps(ext: dict) -> str:
    return json.dumps(ext, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def export(server_url: str, queries_dir: Path, *, base: dict) -> dict:
    run, close = ontology_jqa.bolt_runner(server_url)
    try:
        return export_with_runner(run, Path(queries_dir), base=base)
    finally:
        close()


def _cmd_export(args) -> int:
    try:
        base = json.loads(Path(args.base).read_text())
        ext = export(f"bolt://127.0.0.1:{args.bolt_port}", Path(args.queries), base=base)
    except Exception as exc:  # noqa: BLE001 - 질의·입력 실패는 호출자(S03)가 degraded 사유로 올린다
        print(f"보강 질의 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(ext))
    print(json.dumps({"dtos": len(ext["dtos"]), "enums": len(ext["enums"]), "constants": len(ext["constants"]),
                      "calls": len(ext["calls"]), "endpoints": len(ext["endpoints"]),
                      "exceptionsWithStatus": sum(1 for e in ext["exceptions"].values() if "status" in e)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.ontology_ext")
    sub = parser.add_subparsers(dest="cmd", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--bolt-port", type=int, required=True)
    exp.add_argument("--base", required=True)
    exp.add_argument("--queries", default=str(DEFAULT_QUERIES))
    exp.add_argument("--out", required=True)
    exp.set_defaults(func=_cmd_export)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
