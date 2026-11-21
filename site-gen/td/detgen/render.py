"""렌더러(설계 §5.4): `Derivation` → `features/<endpoint-slug>.feature`, `glue/support/*.java`(고정 glue 복사), `cases.json`.

규약
- feature는 엔드포인트마다 하나다. 파일 이름은 엔드포인트 라벨의 slug이고(겹치면 `-2`, `-3`), Feature 제목은 라벨 그대로다.
  feature와 시나리오 순서는 엔드포인트 라벨 순, 그 안에서는 도출 순서(입력 주소 기준 정렬)다.
- 시나리오: 태그 `@case:<id>`, 첫 step `Given the case "<id>"`(하네스 계약상 훅을 쓸 수 없어 케이스 id를 step으로 넘긴다),
  선행 요청 → 요청 대상 → 경로 변수 → 쿼리 → 본문 → 인증·본문 표지 → `When the request is sent` → 단정 하나.
- 값은 JSON 리터럴로 쓴다(수는 따옴표 없이, 문자열은 따옴표, null/true/false). 기호(`today±N`, `ref:<var>`, `uniq:<id>`)는
  문자열 리터럴이고 glue의 `DetValues.resolve`가 실행 시점에 푼다.
- 첫 step 뒤의 Given 계열 step은 모두 `And`로 쓴다(Cucumber에서 같은 뜻이다).
- 선행 요청: `And a prior request to "<METHOD> <path>" with body <json-object>[ capturing "<jsonField>" as "<var>"]`.
  capture가 둘 이상이면 변수 이름 순으로 첫째를 같은 줄에, 나머지를 `And the prior response field "<f>" is captured as "<v>"`로 쓴다.
- 단정: `expect.strict`가 정수면 `Then the response status is <n>`, `"[1-5]xx"`면 `Then the response status is in class "<c>"`.
- 모든 feature는 `Background:`에 `Given the SUT timezone is "<tz>"` 한 step을 둔다(tz는 번들 harness.json, `Derivation.timezone`).
  glue는 이 값으로 `today±N`을 푼다. Background는 pickle이 아니므로 testId·`@case:` 매핑은 시나리오 줄만 본다.
- `empty-body` 규칙은 본문 없이 보낸다(`And the request has no body`). 그 밖의 POST/PUT/PATCH는 본문 필드가 없어도 `{}`를 보낸다(glue).
- `cases.json`: 키 정렬·들여쓰기 2·끝 줄바꿈. values는 `body.<f>`/`query.<f>`/`path.<f>` 키(통제 fixture의 기대 목록과 같은 표기)로
  모으고, 재현에 필요한 `auth`와 `setup`을 덧붙인다.

이 모듈에는 SUT 이름·값을 두지 않는다. 모든 이름과 값은 `Derivation`에서 온다.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from td.detgen.constraints import Value
from td.detgen.derive import Case, Derivation
from td.detgen.endpoints import slug

__all__ = ["GLUE_DIR", "RenderError", "glue_checksum", "render"]

GLUE_DIR = Path(__file__).resolve().parents[3] / "e2e" / "det-glue"
FEATURES_DIR = "features"
GLUE_OUT_DIR = "glue"
CASES_FILE = "cases.json"
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_FIELD_NAME = re.compile(r'^[^"\s]+$')
_PATH_VARIABLE = re.compile(r"\{([^}/]+)}")
_STATUS_CLASS = re.compile(r"^[1-5]xx$")
_TIMEZONE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z0-9_+\-]+)*$")
_NO_BODY_RULE = "empty-body"


class RenderError(ValueError):
    """도출 결과를 Gherkin으로 옮길 수 없다(규약 밖의 값). 생성기 버그 신호라 det arm을 failed로 만든다."""


# --- glue ------------------------------------------------------------------------------------------

def _glue_files(root: Path) -> list[tuple[str, Path]]:
    return sorted((path.relative_to(root).as_posix(), path) for path in root.rglob("*.java") if path.is_file())


def glue_checksum(root: Path | None = None) -> str:
    """glue 소스 체크섬: 상대 경로 이름순으로 `경로 NUL 바이트 NUL`을 이어 sha256. 기본은 저장소 고정 glue(`GLUE_DIR`)다.
    렌더 결과의 `<out>/glue`를 넘기면 복사본이 원본과 같은지 확인할 수 있다."""
    digest = hashlib.sha256()
    for relative, path in _glue_files(Path(root) if root is not None else GLUE_DIR):
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


# --- 값과 step -------------------------------------------------------------------------------------

def _literal(value: object, where: str) -> str:
    if value is None or isinstance(value, (bool, int, float, str)):
        try:
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        except ValueError as exc:
            raise RenderError(f"{where}: JSON으로 쓸 수 없는 값 {value!r}") from exc
    raise RenderError(f"{where}: 지원하지 않는 값 형식 {type(value).__name__}")


def _plain(value: object, where: str) -> object:
    if not isinstance(value, Value):
        raise RenderError(f"{where}: Value가 아니다({type(value).__name__})")
    _literal(value.value, where)
    return value.value


def _name(name: str, where: str) -> str:
    if not isinstance(name, str) or not _FIELD_NAME.match(name):
        raise RenderError(f"{where}: step에 쓸 수 없는 이름 {name!r}")
    return name


def _split_endpoint(label: str, where: str) -> tuple[str, str]:
    parts = label.split(" ", 1)
    if len(parts) != 2 or not parts[0].isalpha() or not parts[0].isupper() or not parts[1].startswith("/") or '"' in parts[1]:
        raise RenderError(f"{where}: 엔드포인트 라벨 형식이 아니다 {label!r}")
    return parts[0], parts[1]


def _object_literal(values: dict, where: str) -> str:
    plain = {_name(key, where): _plain(value, f"{where}.{key}") for key, value in values.items()}
    return json.dumps(plain, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _prior_steps(case: Case) -> list[str]:
    lines = []
    for index, prior in enumerate(case.setup):
        where = f"{case.id}.setup[{index}]"
        method, path = _split_endpoint(prior["endpoint"], where)
        body = _object_literal(prior.get("values") or {}, where)
        captures = sorted((prior.get("capture") or {}).items())
        head = f'And a prior request to "{method} {path}" with body {body}'
        if captures:
            var, json_field = captures[0]
            head += f' capturing "{_name(json_field, where)}" as "{_name(var, where)}"'
        lines.append(head)
        for var, json_field in captures[1:]:
            lines.append(f'And the prior response field "{_name(json_field, where)}" is captured as "{_name(var, where)}"')
    return lines


def _assert_step(case: Case) -> str:
    strict = case.expect.get("strict")
    if isinstance(strict, int) and not isinstance(strict, bool) and 100 <= strict <= 599:
        return f"Then the response status is {strict}"
    if isinstance(strict, str) and _STATUS_CLASS.match(strict):
        return f'Then the response status is in class "{strict}"'
    raise RenderError(f"{case.id}: expect.strict는 상태 코드 정수 또는 \"[1-5]xx\" 클래스여야 한다({strict!r})")


def _scenario(case: Case) -> list[str]:
    if not isinstance(case.id, str) or not _CASE_ID.match(case.id):
        raise RenderError(f"태그로 쓸 수 없는 case id {case.id!r}")
    method, path = _split_endpoint(case.endpoint, case.id)
    template_vars = _PATH_VARIABLE.findall(path)
    missing = [name for name in template_vars if name not in case.path]
    if missing:
        raise RenderError(f"{case.id}: 경로 변수 값이 없다 {missing}")
    if case.auth not in ("authed", "anonymous"):
        raise RenderError(f"{case.id}: 알 수 없는 auth {case.auth!r}")
    steps = [f'Given the case "{case.id}"', *_prior_steps(case)]
    steps.append(f'And a request to "{method} {path}"')
    for name in template_vars:
        if _plain(case.path[name], case.id) is None:
            raise RenderError(f"{case.id}: 경로 변수 {name!r} 값이 null이다")
        steps.append(f'And path variable "{_name(name, case.id)}" is {_literal(_plain(case.path[name], case.id), case.id)}')
    for name in sorted(set(case.path) - set(template_vars)):
        raise RenderError(f"{case.id}: 경로 템플릿에 없는 경로 변수 {name!r}")
    for name in sorted(case.query):
        steps.append(f'And query parameter "{_name(name, case.id)}" is {_literal(_plain(case.query[name], case.id), case.id)}')
    for name in sorted(case.values):
        steps.append(f'And body field "{_name(name, case.id)}" is {_literal(_plain(case.values[name], case.id), case.id)}')
    if case.auth == "anonymous":
        steps.append("And the request is sent without authentication")
    if case.rule == _NO_BODY_RULE:
        steps.append("And the request has no body")
    steps.append("When the request is sent")
    steps.append(_assert_step(case))
    return [f"  @case:{case.id}", f"  Scenario: {case.id}", *(f"    {line}" for line in steps)]


def _feature_names(endpoints: list[str]) -> dict[str, str]:
    """엔드포인트 라벨 → feature 파일 이름. 라벨 순으로 slug를 주고, 겹치면 `-2`, `-3`을 붙인다."""
    names: dict[str, str] = {}
    used: set[str] = set()
    for label in sorted(set(endpoints)):
        base = slug(label) or "endpoint-" + hashlib.sha1(label.encode("utf-8")).hexdigest()[:8]
        name, serial = base, 1
        while name in used:
            serial += 1
            name = f"{base}-{serial}"
        used.add(name)
        names[label] = f"{name}.feature"
    return names


def _timezone_step(timezone: object) -> str:
    """Background step. 타임존이 없거나 IANA 이름 꼴이 아니면 RenderError(glue가 기본값으로 대신하지 않는다)."""
    if not isinstance(timezone, str) or not _TIMEZONE.match(timezone):
        raise RenderError(f"SUT 타임존이 없거나 형식이 맞지 않는다: {timezone!r}")
    return f'Given the SUT timezone is "{timezone}"'


def _feature_text(label: str, cases: list[Case], timezone_step: str) -> str:
    lines = [f"Feature: {label}", "  Deterministic cases derived from the analysis inputs for one endpoint.", "",
             "  Background:", f"    {timezone_step}", ""]
    for case in cases:
        lines += _scenario(case) + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


# --- cases.json -------------------------------------------------------------------------------------

def _value_entry(value: Value, where: str) -> dict:
    entry = {"value": _plain(value, where), "provenance": value.provenance}
    if value.provenance not in ("input", "derived", "generic-sentinel"):
        raise RenderError(f"{where}: 알 수 없는 provenance {value.provenance!r}")
    if value.source is not None:
        entry["from"] = value.source
    if value.transform is not None:
        entry["transform"] = value.transform
    return entry


def _case_entry(case: Case) -> dict:
    values = {}
    for prefix, group in (("path", case.path), ("query", case.query), ("body", case.values)):
        for name, value in group.items():
            values[f"{prefix}.{name}"] = _value_entry(value, f"{case.id}.{prefix}.{name}")
    setup = [{"endpoint": prior["endpoint"],
              "values": {name: _value_entry(value, f"{case.id}.setup.{name}") for name, value in (prior.get("values") or {}).items()},
              "capture": dict(prior.get("capture") or {})} for prior in case.setup]
    entry = {"id": case.id, "endpoint": case.endpoint, "rule": case.rule, "sources": list(case.sources), "values": values,
             "expect": dict(case.expect), "oracle": case.oracle, "assumes": list(case.assumes),
             "baselineProof": list(case.baseline_proof), "auth": case.auth, "setup": setup}
    if case.pair is not None:
        entry["pair"] = case.pair
    return entry


def _cases_text(derivation: Derivation) -> str:
    doc = {"cases": [_case_entry(case) for case in derivation.cases], "unresolved": derivation.unresolved,
           "universe": derivation.universe}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


# --- 진입점 ----------------------------------------------------------------------------------------

def render(derivation: Derivation, out_dir: Path) -> list[str]:
    """generation 디렉터리(`out_dir`)에 feature, glue, cases.json을 쓰고 쓴 파일의 상대 경로(정렬)를 돌려준다.
    모든 내용을 먼저 만든 뒤 쓴다(규약 위반이면 RenderError로 아무것도 쓰지 않는다)."""
    ids = [case.id for case in derivation.cases]
    if len(ids) != len(set(ids)):
        raise RenderError("case id가 겹친다")
    by_endpoint: dict[str, list[Case]] = {}
    for case in derivation.cases:
        by_endpoint.setdefault(case.endpoint, []).append(case)
    names = _feature_names(list(by_endpoint))
    timezone_step = _timezone_step(derivation.timezone)
    contents: dict[str, bytes] = {}
    for label in sorted(by_endpoint):
        contents[f"{FEATURES_DIR}/{names[label]}"] = _feature_text(label, by_endpoint[label], timezone_step).encode("utf-8")
    contents[CASES_FILE] = _cases_text(derivation).encode("utf-8")
    glue = _glue_files(GLUE_DIR)
    if not glue:
        raise RenderError(f"고정 glue가 없다: {GLUE_DIR.name}")
    out = Path(out_dir)
    for relative, data in contents.items():
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for relative, source in glue:
        target = out / GLUE_OUT_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return sorted([*contents, *(f"{GLUE_OUT_DIR}/{relative}" for relative, _ in glue)])
