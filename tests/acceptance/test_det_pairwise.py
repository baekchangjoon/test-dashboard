"""det pairwise(PICT) E2E 수용 테스트: REQ-301, 304, 309, 310, 314, 315, 318.

파이프라인은 이 테스트가 돌리지 않는다. 컨트롤러가 run-all을 돌리고(order 2 한 번, `--det-pairwise-order 3` 한 번)
work/det-pairwise-session.json에 run 경로를 적는다. 세션 파일이 없으면 conftest 훅이 skip이 아니라 실패시킨다.

독립 오라클(REQ-309)과 독립 평가기(REQ-310)는 `td.detgen`을 import하지 않고 이 파일 안에서 구현한다.
오라클은 `pairwise.json`(params·candidates·fixed·exclusions)과 `cases.json`만 읽는다.
"""
import hashlib
import itertools
import json
import re
from pathlib import Path

import jsonschema
import pytest

from conftest import DET_PAIRWISE_SESSION_FILE, REPO_ROOT
from td import redact

SCHEMAS = REPO_ROOT / "site-gen" / "td" / "schemas"
PICT_COMMIT = "d529bb1535b725c8f29704f183b23dd344895d02"
SUT_COMMIT_PREFIX = "b6f9393"
ENDPOINT_POST_RESERVATIONS = "POST /api/reservations"
PAIRWISE_REASONS = ("pairwise-unavailable", "pairwise-too-large", "pairwise-infeasible", "pairwise-row-invalid")


# --- 공통 헬퍼 ---------------------------------------------------------------------------------------
def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _session() -> dict:
    return _read_json(DET_PAIRWISE_SESSION_FILE)


@pytest.fixture
def run_dir() -> Path:
    return Path(_session()["runDir"])


@pytest.fixture
def order3_run_dir() -> Path:
    return Path(_session()["order3RunDir"])


@pytest.fixture
def previous_cases_dir() -> Path:
    return Path(_session()["previousCasesDir"])


@pytest.fixture
def run3_bundle_dir() -> Path:
    return Path(_session()["run3BundleDir"])


@pytest.fixture
def run3_run_dir() -> Path:
    return Path(_session()["run3RunDir"])


def _det_generation_dir(run: Path) -> Path:
    """S06 bdd-gen.json의 det generation 항목(`dir`)이 가리키는 스냅샷 디렉터리."""
    records = [g for g in _read_json(run / "S06" / "bdd-gen.json")["generations"] if g["arm"] == "det"]
    assert len(records) == 1, f"det generation이 정확히 1개여야 한다: {[g['genId'] for g in records]}"
    assert records[0]["status"] == "passed", records[0]
    gen_dir = Path(records[0]["dir"])
    assert (gen_dir / "_COMPLETE").is_file() and (gen_dir / "cases.json").is_file(), gen_dir
    return gen_dir


def _simple(name: str) -> str:
    return re.split(r"[.$]", name)[-1]


# --- 독립 오라클(REQ-309, REQ-318): td.detgen을 쓰지 않는다 ---------------------------------------------
def _candidate_matches(candidate: dict, values: dict, key: str) -> bool:
    """케이스 `values`가 후보 한 개를 구현하는지. 종류별로 literal/omit/null/uniq/spread를 따로 본다."""
    kind = candidate["kind"]
    if kind == "omit":
        return key not in values
    if key not in values:
        return False
    entry = values[key]
    actual = entry.get("value") if isinstance(entry, dict) else entry
    if kind == "null":
        return actual is None
    if kind == "uniq":
        return isinstance(actual, str) and actual.startswith("uniq:")
    if kind == "spread":
        bounds = candidate["range"]
        excluded = bounds.get("excluded") or []
        return isinstance(actual, (int, float)) and bounds["lo"] <= actual <= bounds["hi"] and actual not in excluded
    if kind == "literal":
        if actual == candidate.get("value"):
            return True
        # 값 변환(transform)이 붙은 후보는 케이스 값이 변환 결과다: 같은 transform이 기록된 경우만 인정한다
        transform = candidate.get("transform")
        return bool(transform) and isinstance(entry, dict) and entry.get("transform") == transform
    raise AssertionError(f"알 수 없는 후보 종류: {kind}")


def _feasible_tuples(endpoint_doc: dict, order: int) -> set[tuple]:
    """배제를 모두 만족하는 전체 행으로 확장 가능한 order-way (파라미터, 라벨) 튜플 집합(백트래킹 전수 탐색)."""
    params = endpoint_doc["params"]
    names = [p["param"] for p in params]
    labels = {p["param"]: [c["label"] for c in p["candidates"]] for p in params}
    exclusions = [{k: v for k, v in item.items() if k in labels} for item in endpoint_doc["exclusions"]]
    assert all(exclusions), "배제 항목에 파라미터 라벨이 없다"

    def violates(assignment: dict) -> bool:
        return any(all(assignment.get(k) == v for k, v in item.items()) for item in exclusions)

    def extendable(assignment: dict) -> bool:
        rest = [name for name in names if name not in assignment]
        if not rest:
            return not violates(assignment)
        head, tail = rest[0], rest[1:]
        for label in labels[head]:
            assignment[head] = label
            ok = not violates(assignment) and (not tail or extendable(assignment))
            del assignment[head]
            if ok:
                return True
        return False

    feasible = set()
    for subset in itertools.combinations(names, order):
        for combo in itertools.product(*(labels[name] for name in subset)):
            assignment = dict(zip(subset, combo))
            if not violates(assignment) and extendable(dict(assignment)):
                feasible.add(tuple(zip(subset, combo)))
    return feasible


def _oracle(gen_dir: Path, order: int | None = None) -> dict:
    """엔드포인트별 {feasible, covered, uncovered} (+ 파라미터·pairwise 케이스 수)."""
    pairwise = _read_json(gen_dir / "pairwise.json")
    cases = {case["id"]: case for case in _read_json(gen_dir / "cases.json")["cases"]}
    order = order or pairwise["order"]
    result = {}
    for label, doc in pairwise["endpoints"].items():
        if doc.get("skipped") or not doc.get("rows"):
            result[label] = {"feasible": 0, "covered": 0, "uncovered": [], "skipped": doc.get("skipped")}
            continue
        effective = min(order, doc.get("effectiveOrder") or order, len(doc["params"]))
        feasible = _feasible_tuples(doc, effective)
        candidates = {p["param"]: {c["label"]: c for c in p["candidates"]} for p in doc["params"]}
        keys = {p["param"]: f"{p['loc']}.{p['field']}" for p in doc["params"]}
        row_cases = []
        for row in doc["rows"]:
            case_id = row.get("caseId") or row.get("mergedInto")
            assert case_id in cases, f"{label}: 행이 가리키는 케이스가 cases.json에 없다: {case_id}"
            row_cases.append(cases[case_id]["values"])
        uncovered = []
        for tuple_ in sorted(feasible):
            if not any(all(_candidate_matches(candidates[param][value], values, keys[param]) for param, value in tuple_)
                       for values in row_cases):
                uncovered.append(tuple_)
        result[label] = {"feasible": len(feasible), "covered": len(feasible) - len(uncovered), "uncovered": uncovered}
    return result


def _assert_full_coverage(gen_dir: Path, order: int | None = None) -> dict:
    oracle = _oracle(gen_dir, order)
    missed = {label: item["uncovered"][:5] for label, item in oracle.items() if item["uncovered"]}
    assert not missed, f"실현 가능한 상호작용이 케이스 값에 나타나지 않는다: {missed}"
    return oracle


# --- REQ-301 -----------------------------------------------------------------------------------------
@pytest.mark.det_pairwise_e2e
def test_req301_tools_lock_real(run_dir):
    import yaml
    lock = yaml.safe_load((run_dir / "tools.lock").read_text(encoding="utf-8"))
    assert isinstance(lock.get("pict"), dict), f"tools.lock에 pict 항목이 없다: {lock.get('pict')}"
    assert lock["pict"]["commit"] == PICT_COMMIT, lock["pict"]
    assert re.fullmatch(r"[0-9a-f]{64}", lock["pict"]["binarySha256"]), lock["pict"]


# --- REQ-304 -----------------------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.det_pairwise_e2e
def test_req304_inputs_identical_real(run_dir, run3_bundle_dir, run3_run_dir):
    bundle = run_dir / "S06" / "bundles" / "det"
    names = sorted(p.name for p in bundle.iterdir() if p.is_file())
    assert names == sorted(p.name for p in run3_bundle_dir.iterdir() if p.is_file()), "번들 파일 목록이 run3과 다르다"
    for name in names:
        if name == "harness.json":
            continue
        assert _sha256(bundle / name) == _sha256(run3_bundle_dir / name), f"{name}이 run3 번들과 다르다"
    current = _read_json(bundle / "harness.json")
    assert "pairwiseOrder" in current, "harness.json에 pairwiseOrder가 없다"
    current.pop("pairwiseOrder")
    assert current == _read_json(run3_bundle_dir / "harness.json")
    commit = _read_json(run_dir / "run.json")["commit"]
    assert commit.startswith(SUT_COMMIT_PREFIX), commit
    assert commit == _read_json(run3_run_dir / "run.json")["commit"]


_EXISTING_EXCEPTION_KEYS = {"sources"}  # 병합으로 늘어난 sources만 예외


@pytest.mark.det_pairwise_e2e
def test_req304_existing_cases_real(run_dir, previous_cases_dir):
    previous = _read_json(previous_cases_dir / "cases.json")["cases"]
    assert len(previous) == 80, f"기준 스냅샷 케이스는 80개여야 한다: {len(previous)}"
    current = {case["id"]: case for case in _read_json(_det_generation_dir(run_dir) / "cases.json")["cases"]
               if case["rule"] != "pairwise"}
    assert set(current) == {case["id"] for case in previous}, "규칙 ≠ pairwise 케이스 id 집합이 기준과 다르다"
    for old in previous:
        new = current[old["id"]]
        assert set(old["sources"]) <= set(new["sources"]), f"{old['id']}: sources가 줄었다"
        strip = lambda case: {k: v for k, v in case.items() if k not in _EXISTING_EXCEPTION_KEYS}  # noqa: E731
        assert strip(new) == strip(old), f"{old['id']}: sources 외 항목이 바뀌었다"


# --- REQ-309 -----------------------------------------------------------------------------------------
@pytest.mark.det_pairwise_e2e
def test_req309_feasible_interactions_real(run_dir):
    gen_dir = _det_generation_dir(run_dir)
    oracle = _assert_full_coverage(gen_dir)
    assert oracle[ENDPOINT_POST_RESERVATIONS]["feasible"] > 0, "POST /api/reservations 실현 가능 2-way 튜플이 0개다(공허)"
    universe = _read_json(gen_dir / "cases.json")["universe"]["pairwise"]
    assert universe["order"] == 2, universe["order"]
    by_endpoint = universe["byEndpoint"]
    for label, item in oracle.items():
        if item.get("skipped"):
            continue
        reported = by_endpoint[label]
        assert (item["feasible"], item["covered"]) == (reported["interactionsFeasible"], reported["interactionsCovered"]), \
            f"{label}: 오라클 {item['feasible']}/{item['covered']} != universe {reported}"
    assert sum(i["feasible"] for i in oracle.values()) == sum(
        e["interactionsFeasible"] for e in by_endpoint.values())
    assert sum(i["covered"] for i in oracle.values()) == sum(e["interactionsCovered"] for e in by_endpoint.values())


# --- REQ-310: 최소 평가기(td.detgen 미사용) -------------------------------------------------------------
SUPPORTED_OPERATORS = ("<", "<=", ">", ">=", "==", "!=", "== null", "!= null", "&&", "||")


class Unsupported(Exception):
    """평가기가 지원하지 않는 문법·참조."""


_TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<op>&&|\|\||<=|>=|==|!=|<|>|\(|\)|\.|\*|\+|-|/|!|,)"
                    r"|(?P<id>[A-Za-z_]\w*)|(?P<other>\S))")


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(text) and text[pos:].strip():
        match = _TOKEN.match(text, pos)
        pos = match.end()
        kind = match.lastgroup
        if kind == "other":
            raise Unsupported(f"알 수 없는 문자: {match['other']}")
        tokens.append((kind, match.group(kind)))
    return tokens


class _Evaluator:
    """요청 필드(`req.x()`), 정수, enum 상수, ext.json 정수 상수, null만 다루는 3값 논리(True/False/None=판단 불가) 평가기."""

    def __init__(self, text: str, fields: set[str], constants: dict[str, int], enums: dict[str, set[str]]):
        self.tokens = _tokenize(text)
        self.pos = 0
        self.fields = fields
        self.constants = constants
        self.enums = enums
        self.used_fields: set[str] = set()
        self.tree = self._or()
        if self.pos != len(self.tokens):
            raise Unsupported(f"해석하지 못한 토큰: {self.tokens[self.pos:][:3]}")

    # 파서 --------------------------------------------------------------------------------------------
    def _peek(self, *values):
        return self.pos < len(self.tokens) and self.tokens[self.pos][1] in values

    def _take(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _or(self):
        node = self._and()
        while self._peek("||"):
            self._take()
            node = ("||", node, self._and())
        return node

    def _and(self):
        node = self._cmp()
        while self._peek("&&"):
            self._take()
            node = ("&&", node, self._cmp())
        return node

    def _cmp(self):
        left = self._operand()
        if self._peek("<", "<=", ">", ">=", "==", "!="):
            operator = self._take()[1]
            return (operator, left, self._operand())
        return left

    def _operand(self):
        if self.pos >= len(self.tokens):
            raise Unsupported("식이 끝났다")
        kind, value = self._take()
        if kind == "num":
            if "." in value:
                raise Unsupported(f"실수 리터럴: {value}")
            return ("lit", int(value))
        if kind == "id":
            return self._identifier(value)
        if value == "(":
            node = self._or()
            if not self._peek(")"):
                raise Unsupported("닫는 괄호가 없다")
            self._take()
            return node
        raise Unsupported(f"지원하지 않는 연산자/토큰: {value}")

    def _identifier(self, name: str):
        if name == "null":
            return ("lit", None)
        if name == "req" and self._peek("."):
            self._take()
            field = self._take()[1]
            if not (self._peek("(") and self.tokens[self.pos + 1][1] == ")"):
                raise Unsupported("req 접근은 req.x() 형태만 지원한다")
            self.pos += 2
            if self._peek("."):
                raise Unsupported(f"req.{field}() 뒤의 메서드 호출")
            if field not in self.fields:
                raise Unsupported(f"엔드포인트 요청 필드가 아니다: {field}")
            self.used_fields.add(field)
            return ("field", field)
        if name in self.enums and self._peek("."):
            self._take()
            constant = self._take()[1]
            if constant not in self.enums[name] or self._peek("(", "."):
                raise Unsupported(f"enum 상수가 아니다: {name}.{constant}")
            return ("lit", constant)
        if name in self.constants and not self._peek(".", "("):
            return ("lit", self.constants[name])
        raise Unsupported(f"지원하지 않는 식별자: {name}")

    # 평가 --------------------------------------------------------------------------------------------
    def evaluate(self, values: dict) -> bool | None:
        return self._eval(self.tree, values)

    def _eval(self, node, values):
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "field":
            for loc in ("body", "query", "path"):
                entry = values.get(f"{loc}.{node[1]}")
                if entry is not None:
                    return entry.get("value") if isinstance(entry, dict) else entry
            return None  # omit과 null은 req 필드에서 모두 null
        if kind == "&&":
            left, right = self._eval(node[1], values), self._eval(node[2], values)
            if left is False or right is False:
                return False
            return None if left is None or right is None else True
        if kind == "||":
            left, right = self._eval(node[1], values), self._eval(node[2], values)
            if left is True or right is True:
                return True
            return None if left is None or right is None else False
        left, right = self._eval(node[1], values), self._eval(node[2], values)
        if kind in ("==", "!="):
            if node[1] == ("lit", None) or node[2] == ("lit", None):
                same = left is None and right is None
                return same if kind == "==" else not same
            if left is None or right is None or isinstance(left, bool) != isinstance(right, bool):
                return None
            if isinstance(left, str) and isinstance(right, str) and (left.startswith("uniq:") or right.startswith("uniq:")):
                return None
            same = left == right
            return same if kind == "==" else not same
        if not (isinstance(left, int) and isinstance(right, int)) or isinstance(left, bool) or isinstance(right, bool):
            return None  # null·문자열과의 순서 비교는 판단 불가
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[kind]


_ERROR_EXPECTED = re.compile(r"Exception|code=4\d\d")


def _evaluate_error_conditions(run: Path, pairwise_cases: list[dict]) -> tuple[list[dict], list[dict], list[tuple]]:
    """번들 plans.json 오류 항목을 pairwise 케이스 값에 평가한다. (평가한 조건, 건너뛴 조건, 위반 목록)."""
    bundle = run / "S06" / "bundles" / "det"
    ext = _read_json(bundle / "ext.json")
    constants = {c["name"]: c["value"] for c in ext["constants"] if isinstance(c.get("value"), int)}
    enums = {_simple(name): {c if isinstance(c, str) else c["name"] for c in enum["constants"]}
             for name, enum in ext["enums"].items()}
    evaluated, skipped, violations = [], [], []
    for plan in _read_json(bundle / "plans.json"):
        service, method = plan["file"].removeprefix("plan-tests-").removesuffix(".json").rsplit(".", 1)
        endpoints = {call["endpoint"] for call in ext["calls"]
                     if _simple(call["service"]) == service and call["method"] == method}
        labels = {endpoint.removeprefix("endpoint:") for endpoint in endpoints}
        cases = [case for case in pairwise_cases if case["endpoint"] in labels]
        for item in plan["items"]:
            if not _ERROR_EXPECTED.search(item["expected"]):
                continue
            entry = {"file": plan["file"], "index": item["index"], "condition": " ".join(item["condition"].split())}
            if not cases:
                skipped.append({**entry, "why": "대응 pairwise 케이스 없음"})
                continue
            fields = {key.split(".", 1)[1] for case in cases for key in case["values"]}
            try:
                evaluator = _Evaluator(item["condition"], fields, constants, enums)
            except Unsupported as exc:
                skipped.append({**entry, "why": str(exc)})
                continue
            evaluated.append(entry)
            for case in cases:
                if evaluator.evaluate(case["values"]) is True:
                    violations.append((case["id"], entry["condition"]))
    return evaluated, skipped, violations


@pytest.mark.det_pairwise_e2e
def test_req310_real(run_dir):
    document = _read_json(_det_generation_dir(run_dir) / "cases.json")
    pairwise_cases = [case for case in document["cases"] if case["rule"] == "pairwise"]
    assert pairwise_cases, "pairwise 케이스가 없다"
    evaluated, skipped, violations = _evaluate_error_conditions(run_dir, pairwise_cases)
    detail = f"지원 연산자 {SUPPORTED_OPERATORS}; 평가 못한 조건 {len(skipped)}건: {skipped}"
    assert len(evaluated) >= 1, f"평가한 오류 조건이 없다. {detail}"
    assert any("PriceTier.VIP" in e["condition"] and "loyaltyPoints" in e["condition"] for e in evaluated), \
        f"VIP×loyaltyPoints 조건이 평가되지 않았다: 평가 {[e['condition'] for e in evaluated]}. {detail}"
    assert not violations, f"pairwise 케이스가 오류 조건을 참으로 만든다: {violations[:5]}. {detail}"


# --- REQ-314 -----------------------------------------------------------------------------------------
@pytest.mark.det_pairwise_e2e
def test_req314_report_real(run_dir):
    gen_dir = _det_generation_dir(run_dir)
    cases_doc = _read_json(gen_dir / "cases.json")
    # pairwise.json 스키마, _COMPLETE 체크섬 목록, bdd-gen generator.pict
    pairwise = _read_json(gen_dir / "pairwise.json")
    jsonschema.validate(pairwise, _read_json(SCHEMAS / "pairwise.schema.json"))
    assert "pairwise.json" in (gen_dir / "_COMPLETE").read_text(encoding="utf-8"), "_COMPLETE 체크섬 목록에 pairwise.json이 없다"
    meta = _read_json(run_dir / "S06" / "bdd-gen.json")
    jsonschema.validate(meta, _read_json(SCHEMAS / "bdd-gen.schema.json"))
    [det_record] = [g for g in meta["generations"] if g["arm"] == "det"]
    assert det_record["generator"]["pict"]["commit"] == PICT_COMMIT, det_record["generator"]
    # pairwise-* 사유 슬롯 4종은 모두 0건
    by_reason = cases_doc["universe"]["bySlot"]["byReason"]
    assert all(by_reason.get(reason) == 0 for reason in PAIRWISE_REASONS), {r: by_reason.get(r) for r in PAIRWISE_REASONS}
    assert not [e for e in cases_doc["unresolved"] if e["reason"] in PAIRWISE_REASONS]
    # compare.json 스키마와 det 블록
    compare = _read_json(run_dir / "S12" / "compare" / "compare.json")
    jsonschema.validate(compare, _read_json(SCHEMAS / "compare.schema.json"))
    summary = compare["deterministic"]["summary"]
    assert summary["byRule"]["pairwise"]["generated"] >= 1, summary["byRule"]
    block = summary["pairwise"]
    assert block is not None and block["order"] == 2, block
    pairwise_cases = [c for c in cases_doc["cases"] if c["rule"] == "pairwise"]
    assert len([c for c in pairwise_cases if c["endpoint"] == ENDPOINT_POST_RESERVATIONS]) >= 1
    assert summary["byRule"]["pairwise"]["generated"] == len(pairwise_cases)
    # 교차 검증: 독립 오라클 값, assumes 접두 개수
    oracle = _oracle(gen_dir)
    feasible = sum(i["feasible"] for i in oracle.values())
    covered = sum(i["covered"] for i in oracle.values())
    assert feasible > 0
    assert (block["interactionsFeasible"], block["interactionsCovered"]) == (feasible, covered), (block, feasible, covered)
    assert block["interactionsCovered"] == block["interactionsFeasible"]
    count_prefix = lambda prefix: sum(1 for c in pairwise_cases if any(a.startswith(prefix) for a in c["assumes"]))  # noqa: E731
    assert block["undetermined"] == count_prefix("undetermined:")
    assert block["relCombined"] == count_prefix("rel-combined:")
    # compare.html det 표: pairwise 텍스트 행과 covered/feasible 숫자
    html = (run_dir / "S12" / "compare" / "compare.html").read_text(encoding="utf-8")
    assert "pairwise" in html and f"{covered}/{feasible}" in re.sub(r"\s*/\s*", "/", html), \
        "compare.html에 pairwise 행 또는 interactionsCovered/interactionsFeasible 숫자가 없다"


# --- REQ-315 -----------------------------------------------------------------------------------------
@pytest.mark.det_pairwise_e2e
def test_req315_not_published_real(run_dir):
    site = run_dir / "site"
    assert site.is_dir(), f"게시 미러가 없다: {site}"
    assert not list(site.rglob("pairwise.json")), "게시 미러에 pairwise.json이 있다"
    gen_dir = _det_generation_dir(run_dir)
    for path in (gen_dir / "cases.json", gen_dir / "pairwise.json", run_dir / "S06" / "bdd-gen.json"):
        assert redact.find_leaks(path.read_text(encoding="utf-8")) == [], f"{path.name}에 누출이 있다"


# --- REQ-318 -----------------------------------------------------------------------------------------
@pytest.mark.det_pairwise_e2e
def test_req318_three_way_real(order3_run_dir):
    harness = _read_json(order3_run_dir / "S06" / "bundles" / "det" / "harness.json")
    assert harness["pairwiseOrder"] == 3, harness
    gen_dir = _det_generation_dir(order3_run_dir)
    assert _read_json(gen_dir / "pairwise.json")["order"] == 3
    oracle = _assert_full_coverage(gen_dir, order=3)
    assert oracle[ENDPOINT_POST_RESERVATIONS]["feasible"] > 0, "3-way 실현 가능 튜플이 0개다(공허)"
