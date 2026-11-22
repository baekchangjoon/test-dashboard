"""det 번들 투영(설계 §3.1, §3.2).

`project`는 허용 목록의 필드만 run 산출물에서 뽑아 정규화 JSON으로 `out_dir`에 쓰고 STAMP.json(파일별 sha256)을 남긴다.
`Bundle`은 STAMP에 적힌 파일만 읽는다. detgen의 나머지 코드는 원본 raw 경로를 직접 열지 않고 `Bundle.read`만 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import yaml

from td import redact, sut_config
from td.state import TZ_NAME

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
STAMP_NAME = "STAMP.json"
BUNDLE_FILES = ("plans.json", "keyparams.json", "auth.json", "ontology.json", "ext.json", "harness.json")
# 온톨로지·보강 그래프에서도 제거하는 키(소스 위치·원문·절대경로를 담을 수 있는 필드)
FORBIDDEN_KEYS = frozenset({"file_path", "interceptor_sources", "artifact_path", "key_params_path"})
# 로컬 절대경로 토큰(redact.LOCAL_PREFIX_PATTERN과 같은 접두)을 경로 끝(공백·따옴표·구분자)까지 통째로 지운다.
ABS_PATH_PATTERN = re.compile(r"(?<![\w.\-~])(?:/Users|/home|/private/var|/var/folders)/[^\s\"'<>,;)]*")
PLAN_ITEM_FIELDS = ("condition", "expected", "branch_value", "param", "prefix")
# pairwise order(det pairwise 설계 §5.4): run-all `--det-pairwise-order`가 내보내는 값. 번들 harness.json `pairwiseOrder`로 싣는다
PAIRWISE_ORDER_ENV = "TD_DET_PAIRWISE_ORDER"
PAIRWISE_ORDERS = (2, 3)
DEFAULT_PAIRWISE_ORDER = 2


def pairwise_order() -> int:
    """`TD_DET_PAIRWISE_ORDER`(비었으면 2). 2·3 밖이면 ValueError(투영 fatal)."""
    raw = (os.environ.get(PAIRWISE_ORDER_ENV) or "").strip()
    if not raw:
        return DEFAULT_PAIRWISE_ORDER
    if raw not in {str(order) for order in PAIRWISE_ORDERS}:
        raise ValueError(f"{PAIRWISE_ORDER_ENV}는 2 또는 3이어야 한다: {raw[:20]}")
    return int(raw)


class DetInputError(RuntimeError):
    """번들 읽기 규칙 위반(STAMP에 없는 이름, 경로 탈출, 변조)."""


@dataclass
class Projection:
    dir: Path
    input_hash: str  # 64 hex. fatal이면 빈 문자열
    missing: list[str] = field(default_factory=list)
    fatal: str | None = None


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clean_text(value: str) -> str:
    return ABS_PATH_PATTERN.sub("<path>", value)


def _scrub(obj):
    """금지 키를 떨구고 문자열 값에서 절대경로를 지운 사본."""
    if isinstance(obj, str):
        return redact.redact_text(_clean_text(obj))
    if isinstance(obj, dict):
        return {key: _scrub(value) for key, value in obj.items() if key not in FORBIDDEN_KEYS}
    if isinstance(obj, list):
        return [_scrub(value) for value in obj]
    return obj


def _text(value) -> str:
    """JSON 값 -> 문자열. 문자열이 아니면(null, 숫자 등) 빈 문자열(str(None)=="None"이 되는 것을 막는다)."""
    return value if isinstance(value, str) else ""


def _string_leaks(obj) -> list[str]:
    """문서를 순회하며 모든 문자열 값과 키에 find_leaks를 적용한 누출 종류 목록."""
    if isinstance(obj, str):
        return redact.find_leaks(obj)
    if isinstance(obj, dict):
        return [kind for key, value in obj.items() for kind in _string_leaks(key) + _string_leaks(value)]
    if isinstance(obj, list):
        return [kind for value in obj for kind in _string_leaks(value)]
    return []


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _validated(path: Path, schema_name: str, label: str):
    """필수 S03 파일 읽기. (데이터, 오류 문구)."""
    if not path.is_file():
        return None, f"{label} 없음"
    try:
        data = _load_json(path)
        jsonschema.validate(data, _load_json(SCHEMA_DIR / schema_name))
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        return None, f"{label} 읽기/스키마 오류: {type(exc).__name__}"
    return data, None


def _plan_entry(path: Path) -> dict | None:
    try:
        data = _load_json(path)
        cases = data["test_cases"]
        if not isinstance(cases, list):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    stem = path.name[len("plan-tests-"):-len(".json")]
    class_name, _, method_name = stem.partition(".")
    items = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            return None
        # 조건식 등은 원문 그대로 둔다(redaction으로 고쳐 쓰지 않는다). 누출은 project 끝의 find_leaks 게이트가 fatal로 막는다.
        item = {name: _text(case.get(name)) for name in PLAN_ITEM_FIELDS}
        item["index"] = index
        item["conditionSha"] = _sha256(item["condition"].encode("utf-8"))
        items.append(item)
    return {"file": path.name, "class": _text(data.get("class")) or class_name,
            "method": _text(data.get("method")) or method_name, "items": items}


def _keyparams_entry(path: Path) -> dict | None:
    try:
        data = _load_json(path)
        raw_params = data["parameters"]
        parameters = []
        for param in raw_params:
            parameters.append({
                "name": _text(param.get("name")),
                "accessor": _text(param.get("accessor")),
                "http_name": _text(param.get("http_name")),
                "java_type": _text(param.get("java_type")),
                "reasons": [{"type": _text(reason.get("type")), "detail": _text(reason.get("detail"))}
                            for reason in param.get("reasons") or []],
            })
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return {"file": path.name, "class": _text(data.get("class")),
            "method": _text(data.get("method")), "parameters": parameters}


def _auth(path: Path) -> dict | None:
    try:
        headers = _load_json(path)["required_headers"]
        return {"required_headers": [{"name": _text(h["name"]), "required": bool(h.get("required", False))}
                                     for h in headers]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _timezone(sut_file: Path) -> str:
    compose = sut_file.resolve().parents[2] / "env" / "docker-compose.sut.yml"
    try:
        services = (yaml.safe_load(compose.read_text(encoding="utf-8")) or {}).get("services") or {}
    except (OSError, yaml.YAMLError, IndexError, AttributeError):
        return TZ_NAME
    for name in sorted(services):
        environment = (services[name] or {}).get("environment") or {}
        if isinstance(environment, list):
            environment = dict(item.split("=", 1) for item in environment if "=" in item)
        if environment.get("TZ"):
            return str(environment["TZ"])
    return TZ_NAME


def project(run_dir: Path, sut_file: Path, out_dir: Path) -> Projection:
    """허용 필드만 뽑아 `out_dir`에 det 번들을 쓴다. 필수 입력이 없거나 깨지면 `fatal`(번들은 쓰지 않는다)."""
    run_dir, sut_file, out_dir = Path(run_dir), Path(sut_file), Path(out_dir)
    raw = run_dir / "S02" / "bbtg" / "raw"
    s03 = run_dir / "S03"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / STAMP_NAME).unlink(missing_ok=True)
    missing: list[str] = []

    ontology, ontology_error = _validated(s03 / "ontology-jqa.json", "ontology.schema.json", "ontology-jqa.json")
    ext, ext_error = _validated(s03 / "ontology-jqa-ext.json", "ontology-ext.schema.json", "ontology-jqa-ext.json")
    plans = []
    for path in sorted((raw / "stdout").glob("plan-tests-*.json")):
        entry = _plan_entry(path)
        if entry is None:
            missing.append(f"plan:{path.name}")
        else:
            plans.append(entry)
    fatals = [error for error in (ontology_error, ext_error) if error]
    if not plans:
        fatals.append("plan-tests-*.json 없음")
    if fatals:
        return Projection(out_dir, "", sorted(missing), "; ".join(fatals))

    keyparams = []
    keyparams_dir = raw / "artifacts" / "key-params"
    for path in sorted(keyparams_dir.glob("*.json")) if keyparams_dir.is_dir() else []:
        entry = _keyparams_entry(path)
        if entry is None:
            missing.append(f"keyparams:{path.name}")
        else:
            keyparams.append(entry)
    if not keyparams and not any(m.startswith("keyparams:") for m in missing):
        missing.append("keyparams")
    auth_path = raw / "artifacts" / "inspect-auth" / "result.json"
    auth = _auth(auth_path) if auth_path.is_file() else None
    if auth is None:
        missing.append("auth")
        auth = {"required_headers": []}

    try:
        config = sut_config.load(sut_file)
    except sut_config.SutConfigError as exc:
        return Projection(out_dir, "", sorted(missing), f"sut.yaml 오류: {exc}")
    try:
        order = pairwise_order()
    except ValueError as exc:
        return Projection(out_dir, "", sorted(missing), str(exc))
    harness = {"login": config.auth_login, "unauthenticatedStatus": config.auth_unauthenticated_status,
               "apiInclude": config.api_include, "timezone": _timezone(sut_file), "pairwiseOrder": order}
    documents = {"plans.json": plans, "keyparams.json": keyparams, "auth.json": auth,
                 "ontology.json": _scrub(ontology), "ext.json": _scrub(ext), "harness.json": harness}
    texts = {name: _dumps(documents[name]) for name in BUNDLE_FILES}
    # 직렬화 텍스트만 검사하면 `\\n/Users/...`처럼 이스케이프 뒤의 경로가 lookbehind를 피할 수 있다. 원시 문자열(키 포함)을 직접 검사한다.
    leaks = sorted(set(_string_leaks(documents)) | set(redact.find_leaks("".join(texts.values()))))
    if leaks:
        return Projection(out_dir, "", sorted(missing), f"redaction 누출 남음: {','.join(leaks)}")

    digests = {name: _sha256(texts[name].encode("utf-8")) for name in BUNDLE_FILES}
    for name, text in texts.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    # 입력 해시: 파일 이름순 (이름, sha256) 나열 + 정렬한 누락 슬롯 목록. 경로·시각은 들어가지 않는다.
    # 누락 목록을 넣는 이유: 깨진 선택 파일(missing)과 아예 없는 파일은 번들 내용이 같아도 degraded 사유가 다르다.
    input_hash = _sha256(("".join(f"{name}\0{digests[name]}\n" for name in sorted(digests))
                          + "missing\0" + "\0".join(sorted(missing)) + "\n").encode("utf-8"))
    stamp = {"files": digests, "input_hash": input_hash, "missing": sorted(missing), "schema": 1}
    (out_dir / STAMP_NAME).write_text(_dumps(stamp), encoding="utf-8")
    return Projection(out_dir, input_hash, sorted(missing), None)


class Bundle:
    """STAMP에 적힌 파일만 읽는 입력 창구. 이름은 STAMP의 키와 정확히 같아야 하고, 내용 sha256도 맞아야 한다."""

    def __init__(self, directory: Path, stamp: dict):
        self.dir = directory
        self.stamp = stamp

    @classmethod
    def open(cls, directory: Path) -> "Bundle":
        directory = Path(directory)
        try:
            stamp = _load_json(directory / STAMP_NAME)
            files = stamp["files"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise DetInputError(f"{STAMP_NAME}을 읽을 수 없다: {type(exc).__name__}") from exc
        if not isinstance(files, dict):
            raise DetInputError(f"{STAMP_NAME}의 files가 매핑이 아니다")
        return cls(directory, stamp)

    @property
    def input_hash(self) -> str:
        return self.stamp["input_hash"]

    @property
    def missing(self) -> list[str]:
        return list(self.stamp.get("missing", []))

    def read(self, name: str):
        digest = self.stamp["files"].get(name) if isinstance(name, str) else None
        if digest is None:
            raise DetInputError(f"번들에 없는 입력: {name!r}")
        data = (self.dir / name).read_bytes()
        if _sha256(data) != digest:
            raise DetInputError(f"번들 파일이 STAMP와 다르다(변조): {name}")
        return json.loads(data.decode("utf-8"))
