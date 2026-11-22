"""det-viz 단위 테스트. Task 2: 클래스 레지스트리·칸 계산·factors.json(REQ-201~206).

번들은 `test_unit_detgen`의 헬퍼로 만든다(controlled·petclinic·viz-kinds). 기대값은 설계 §5.1~5.3의 규칙을
테스트 안에서 다시 계산하거나(클래스 id 공식) 행마다 고정한다(칸 규칙).
"""
import copy
import dataclasses
import hashlib
import json
import re
from pathlib import Path

import jsonschema
import pytest

from test_unit_detgen import FIXTURES, REPO_ROOT, _controlled, _load_docs, _make_bundle, _real_bundle
from td.detgen import derive as derive_module
from td.detgen import render as render_module

VIZ_KINDS = FIXTURES / "viz-kinds"
SNAPSHOT = REPO_ROOT / "e2e" / "generated" / "petclinic" / "det" / "det-da70932c-r1"
FACTORS_SCHEMA = REPO_ROOT / "site-gen" / "td" / "schemas" / "factors.schema.json"
RESERVATION = "POST /api/reservations"
RESERVATION_CLASS_COUNTS = {"petName": 4, "roomNumber": 4, "animalCount": 3, "checkInDate": 3, "nights": 3,
                            "ownerEmail": 3, "priceTier": 3, "promoCode": 3, "depositAmount": 2, "loyaltyPoints": 2}
ORDERS = "POST /svc/orders"
ITEMS = "POST /vk/items"
UPDATE = "PUT /api/reservations/{id}"


def _cid(endpoint: str, field: str, key) -> str:
    """설계 §5.1 클래스 id 공식(독립 구현)."""
    text = json.dumps([endpoint, field, list(key)], ensure_ascii=False)
    return "c" + hashlib.sha256(text.encode()).hexdigest()[:12]


def _valid(endpoint: str, field: str) -> str:
    return _cid(endpoint, field, ("valid",))


def _viz_kinds(directory: Path):
    return _make_bundle(directory, _load_docs(VIZ_KINDS))


class _Generated:
    """번들 하나의 도출·렌더 결과(내부 도출기, Derivation, 출력 디렉터리, factors.json)."""

    def __init__(self, bundle, out: Path):
        self.bundle = bundle
        self.deriver = derive_module._Deriver(bundle)
        self.derivation = self.deriver.run()
        self.out = out
        self.written = render_module.render(self.derivation, out)
        self.text = (out / "factors.json").read_text(encoding="utf-8")
        self.factors = json.loads(self.text)
        self.cases_doc = json.loads((out / "cases.json").read_text(encoding="utf-8"))

    def classes(self, endpoint: str, field: str) -> list[dict]:
        entry = next(e for e in self.factors["endpoints"] if e["endpoint"] == endpoint)
        return next(f["classes"] for f in entry["fields"] if f["field"] == field)

    def by_label(self, endpoint: str, field: str) -> dict[str, dict]:
        return {klass["label"]: klass for klass in self.classes(endpoint, field)}


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    cache: dict[str, _Generated] = {}

    def make(name: str) -> _Generated:
        if name not in cache:
            root = tmp_path_factory.mktemp(name)
            bundle = {"controlled": lambda: _controlled(root / "c"), "petclinic": lambda: _real_bundle(root / "p"),
                      "viz-kinds": lambda: _viz_kinds(root / "v")}[name]()
            cache[name] = _Generated(bundle, root / "out")
        return cache[name]
    return make


ALL = ("controlled", "petclinic", "viz-kinds")


# --- REQ-201 -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ALL)
def test_req201_factors_schema(generated, name):
    gen = generated(name)
    schema = json.loads(FACTORS_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(gen.factors, schema)
    assert gen.factors["version"] == 1
    assert "factors.json" in gen.written
    labels = [entry["endpoint"] for entry in gen.factors["endpoints"]]
    assert labels == sorted(labels) == sorted(ep.label for ep in gen.deriver.endpoints.values())
    empty = {"controlled": "GET /svc/catalog", "viz-kinds": "GET /vk/ping", "petclinic": "GET /api/owners"}[name]
    assert next(e for e in gen.factors["endpoints"] if e["endpoint"] == empty)["fields"] == []
    assert set(gen.factors["cases"]) == {case.id for case in gen.derivation.cases}
    assert [item["index"] for item in gen.factors["unresolved"]] == list(range(len(gen.derivation.unresolved)))
    if name == "petclinic":
        assert len(gen.factors["endpoints"]) == 17
        assert sum(1 for e in gen.factors["endpoints"] if e["fields"] == []) == 6
        assert len(gen.factors["cases"]) == 80 and len(gen.factors["unresolved"]) == 50
        assert all(item["source"] for item in gen.factors["unresolved"])


@pytest.mark.parametrize("name", ALL)
def test_req201_valid_first_and_ids(generated, name):
    gen = generated(name)
    seen = set()
    for ep in gen.deriver.endpoints.values():
        entry = next(e for e in gen.factors["endpoints"] if e["endpoint"] == ep.label)
        fields = ep.path_vars + list((ep.body or {}).values()) + list(ep.query.values())
        assert [f["field"] for f in entry["fields"]] == [f"{fld.loc}.{fld.name}" for fld in fields]
        for fld, field_entry in zip(fields, entry["fields"], strict=True):
            name_ = f"{fld.loc}.{fld.name}"
            classes = field_entry["classes"]
            assert classes[0] == {"id": _valid(ep.label, name_), "kind": "valid", "label": "유효", "sources": []}
            assert sum(1 for klass in classes if klass["kind"] == "valid") == 1
            rest = [klass["id"] for klass in classes[1:]]
            assert rest == sorted(rest)
            expected = {_cid(ep.label, name_, key) for key in gen.deriver._field_classes(ep, fld)}
            assert set(rest) == expected
            for klass in classes:
                assert klass["id"] not in seen
                seen.add(klass["id"])


def test_req201_kind_rules(generated):
    gen = generated("viz-kinds")
    plan = "plan-tests-ItemService.put.json#"
    qty = gen.by_label(ITEMS, "body.qty")
    assert {label: klass["kind"] for label, klass in qty.items()} == {"유효": "valid", "< 1": "violation",
                                                                       "> 99": "violation", "> 50": "branch"}
    assert [s.split("@")[0] for s in qty["< 1"]["sources"]] == [plan + "0", plan + "1"]  # 오류·분기 항목 둘 다 출처
    assert [s.split("@")[0] for s in qty["> 50"]["sources"]] == [plan + "2"]
    slot = gen.by_label(ITEMS, "body.slot")
    assert {label: klass["kind"] for label, klass in slot.items()} == {"유효": "valid", "count ≥ 3": "count"}
    assert slot["count ≥ 3"]["id"] == _cid(ITEMS, "body.slot", ("count",))
    code = gen.by_label(ITEMS, "body.code")
    assert {label: klass["kind"] for label, klass in code.items()} == {
        "유효": "valid", "length > maxLen": "raw", '== "</script><img onerror=x>"': "violation"}
    assert code["length > maxLen"]["id"] == _cid(ITEMS, "body.code", ("raw", ">", "maxLen", True))
    note = gen.by_label(ITEMS, "body.note")
    assert {label: klass["kind"] for label, klass in note.items()} == {
        "유효": "valid", "length < 2": "violation", "length > 10": "violation", "!= null": "contradicted"}
    assert note["!= null"]["id"] == _cid(ITEMS, "body.note", ("raw", "notnull", "None", False))
    assert [s.split("@")[0] for s in note["!= null"]["sources"]] == [plan + "6"]
    for field in ("body.qty", "body.slot", "body.code", "body.note"):
        for klass in gen.classes(ITEMS, field):
            assert all("~" not in source for source in klass["sources"])


def test_req201_qualified_field_ids(generated):
    gen = generated("viz-kinds")
    body, query = gen.by_label(ITEMS, "body.q"), gen.by_label(ITEMS, "query.q")
    assert set(body) == set(query) == {"유효", "== null"}
    assert body["유효"]["id"] == _valid(ITEMS, "body.q") != query["유효"]["id"] == _valid(ITEMS, "query.q")
    key = ("null", "None", False, False)
    assert body["== null"]["id"] == _cid(ITEMS, "body.q", key)
    assert query["== null"]["id"] == _cid(ITEMS, "query.q", key)
    assert body["== null"]["id"] != query["== null"]["id"]


def test_req201_hostile_strings(tmp_path, generated):
    first = generated("viz-kinds")
    second = _Generated(_viz_kinds(tmp_path / "again" / "bundle"), tmp_path / "again" / "out")
    assert second.text == first.text
    hostile = '"</script><img onerror=x>".equals(form.code())'
    labels = set(first.by_label(ITEMS, "body.code"))
    assert '== "</script><img onerror=x>"' in labels
    conditions = {entry["condition"] for entry in first.factors["sources"].values()}
    assert hostile in conditions
    assert "form.qty() < 1 || form.qty() > 99" in conditions
    assert json.loads(first.text) == first.factors  # 문자열이 JSON 왕복에서 그대로 복원된다


# --- REQ-202 -------------------------------------------------------------------------------------------------------

def test_req202_class_counts(generated):
    pet = generated("petclinic")
    reservation = {f["field"].split(".", 1)[1]: len(f["classes"])
                   for e in pet.factors["endpoints"] if e["endpoint"] == RESERVATION for f in e["fields"]}
    assert reservation == RESERVATION_CLASS_COUNTS
    counts = list(RESERVATION_CLASS_COUNTS.values())
    product = 1
    for count in counts:
        product *= count
    pairs = sum(counts[i] * counts[j] for i in range(len(counts)) for j in range(i + 1, len(counts)))
    assert (product, pairs) == (46656, 403)
    for name in ("controlled", "petclinic"):
        gen = generated(name)
        by_endpoint = {e["endpoint"]: e for e in gen.factors["endpoints"]}
        compared = 0
        assert gen.cases_doc["universe"] == gen.derivation.universe
        # 순서는 모수 계산 순서(Derivation.universe 삽입 순서)다. cases.json은 키를 정렬해 쓰므로 순서 비교에 쓰지 않는다
        for item in gen.derivation.universe["theoretical"]["factors"]:
            if "fields" not in item:
                assert item["kind"] == "concurrency-race"
                continue
            compared += 1
            actual = {f["field"]: len(f["classes"]) for f in by_endpoint[item["endpoint"]]["fields"]}
            assert actual == item["fields"], item["endpoint"]
            assert list(actual) == list(item["fields"])
        assert compared == len(gen.factors["endpoints"])


# --- REQ-203 -------------------------------------------------------------------------------------------------------

def _digests(root: Path) -> dict[str, str]:
    files = [root / "cases.json"]
    for sub in ("features", "glue"):
        files += [path for path in (root / sub).rglob("*") if path.is_file()]
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def test_req203_petclinic_bytes(generated):
    assert SNAPSHOT.is_dir()
    current, baseline = _digests(generated("petclinic").out), _digests(SNAPSHOT)
    assert sorted(current) == sorted(baseline)
    assert current == baseline


# --- REQ-204 -------------------------------------------------------------------------------------------------------

def _num(op, value):
    return (op, str(value), False, False)


# (fixture, 대상(case id | (출처 접두, rule, draftKey)), 엔드포인트, 기대 cells(필드 → 클래스 키 | "valid"),
#  boundaries((필드, 키) 목록), stored, enumValue). 생성 불가 슬롯은 cells만 본다.
# storedBoundaries는 STORED_BOUNDARIES에 없으면 []를 기대한다
CELL_ROWS = {
    "violation": ("controlled", "place-violation-1", ORDERS, {"body.quantity": _num("<", 1)}, [], [], None),
    "violation-conjunction": ("controlled", "place-violation-5", ORDERS,
                              {"body.tone": _num("==", "NEON"), "body.credit": _num("<", 50)}, [], [], None),
    "boundary": ("controlled", "place-valid-boundary-1", ORDERS, {"body.quantity": "valid"}, [("body.quantity", _num("<", 1))], [], None),
    "boundary-conjunction": ("controlled", "place-valid-boundary-6", ORDERS,
                             {"body.tone": _num("==", "NEON"), "body.credit": "valid"}, [("body.credit", _num("<", 50))], [], None),
    "branch": ("controlled", "place-branch-entry-1", ORDERS, {"body.voucher": ("eqlit", "FREESHIP", False, False)},
               [], [], None),
    "count-violation": ("controlled", "place-violation-9", ORDERS, {"body.bay": ("count",)}, [], [], None),
    "count-boundary": ("controlled", "place-valid-boundary-9", ORDERS, {"body.bay": "valid"}, [("body.bay", ("count",))], [], None),
    "enum": ("controlled", "place-enum-value-1", ORDERS, {"body.tone": "valid"}, [], [],
             {"field": "body.tone", "constant": "GLOSS"}),
    "omitted-baseline": ("controlled", "place-baseline-valid-1", ORDERS, {}, [], [], None),
    "rel": ("petclinic", "create-violation-1", RESERVATION, {"body.depositAmount": ("rel", "(0, 1000000)", False, False)},
            [], [], None),
    "stored": ("petclinic", "update-valid-boundary-1", UPDATE, {}, [], [], None),
    "raw": ("petclinic", ("plan-tests-ReservationService.update.json#5@", "violation", [0, 0, 0]), UPDATE,
            {"body.nights": ("raw", "!=", "nights", False)}, None, None, None),
    "unresolved-count": ("petclinic", ("plan-tests-ReservationService.create.json#11@", "violation", [0, 0, 0]),
                         RESERVATION, {"body.roomNumber": ("count",)}, None, None, None),
    "contradicted": ("petclinic", ("plan-tests-ReservationService.update.json#3@", "violation", [0, 0, 0]), UPDATE,
                     {"body.nights": ("raw", "notnull", "None", False)}, None, None, None),
}


# 유효 경계로 뒤집은 저장 상태 원자식은 stored가 아니라 storedBoundaries에 적는다
STORED_BOUNDARIES = {"stored": ["<= today"]}


@pytest.mark.parametrize("row", list(CELL_ROWS))
def test_req204_cells(generated, row):
    name, target, endpoint, cells, boundaries, stored, enum_value = CELL_ROWS[row]
    gen = generated(name)
    expected_cells = {field: _valid(endpoint, field) if key == "valid" else _cid(endpoint, field, key)
                      for field, key in cells.items()}
    if isinstance(target, str):
        entry = gen.factors["cases"][target]
        assert entry["cells"] == expected_cells
        assert entry["boundaries"] == sorted(_cid(endpoint, field, key) for field, key in boundaries)
        assert entry["stored"] == stored
        assert entry["storedBoundaries"] == STORED_BOUNDARIES.get(row, [])
        assert entry["enumValue"] == enum_value
        assert entry["inModel"] is True and entry["outReason"] is None
    else:
        prefix, rule, draft_key = target
        hits = [item for item in gen.factors["unresolved"]
                if item["source"].startswith(prefix) and item["rule"] == rule and item["draftKey"] == draft_key]
        assert len(hits) == 1
        assert hits[0]["cells"] == expected_cells
    if row == "omitted-baseline":  # 칸에 없는 필드는 valid로 해석한다(적지 않는다)
        assert gen.factors["cases"]["place-violation-1"]["cells"].keys() == {"body.quantity"}


@pytest.mark.parametrize("name", ALL)
def test_req204_references_and_in_model(generated, name):
    gen = generated(name)
    ids = {e["endpoint"]: {f["field"]: {k["id"] for k in f["classes"]} for f in e["fields"]}
           for e in gen.factors["endpoints"]}
    by_case = {case["id"]: case for case in gen.cases_doc["cases"]}
    for case_id, entry in gen.factors["cases"].items():
        endpoint = by_case[case_id]["endpoint"]
        for field, class_id in entry["cells"].items():
            assert class_id in ids[endpoint][field], (case_id, field)
        for class_id in entry["boundaries"]:
            assert any(class_id in field_ids for field_ids in ids[endpoint].values()), case_id
        out = by_case[case_id]["rule"] in ("auth", "no-data", "empty-body", "filter-empty")
        assert entry["inModel"] is (not out)
        assert entry["outReason"] == (by_case[case_id]["rule"] if out else None)
    for item, source in zip(gen.factors["unresolved"], gen.cases_doc["unresolved"], strict=True):
        for field, class_id in item["cells"].items():
            assert class_id in ids[source["endpoint"]][field], item


def test_req204_merge(generated):
    gen = generated("petclinic")
    entry = gen.factors["cases"]["list-enum-value-3"]
    assert entry["mergedRules"] == ["filter-empty"]
    assert entry["cellConflicts"] == []
    assert entry["inModel"] is True and entry["outReason"] is None
    assert entry["boundaries"] == []
    assert entry["enumValue"]["field"].startswith("query.")
    assert all(e["cellConflicts"] == [] for e in gen.factors["cases"].values())
    assert sum(len(e["mergedRules"]) for e in gen.factors["cases"].values()) == \
        gen.cases_doc["universe"]["bySlot"]["deduplicated"]

    # 의도적으로 칸이 다른 두 초안(같은 요청, 다른 규칙)을 직접 병합한다
    con = generated("controlled")
    deriver = derive_module._Deriver(con.bundle)
    deriver.run()
    source = next(d for d in deriver.drafts if d.case is not None and d.case.id == "place-violation-1")
    first = dataclasses.replace(source, case=copy.deepcopy(source.case), merged=False, survivor=None,
                                merged_rules=[], cell_conflicts=[],
                                cell_info=dataclasses.replace(source.cell_info, boundaries=["cA"]))
    second = dataclasses.replace(source, rule="valid-boundary", case=copy.deepcopy(source.case), merged=False,
                                 survivor=None, merged_rules=[], cell_conflicts=[],
                                 cell_info=derive_module.CellInfo(cells={}, boundaries=["cB"], stored=[], stored_boundaries=[],
                                                                  enum_value=None))
    kept = deriver._dedupe([first, second])
    assert kept == [first] and second.merged and second.survivor is first
    assert first.merged_rules == ["valid-boundary"]
    assert first.cell_info.boundaries == ["cA", "cB"]
    assert first.cell_conflicts == [{"field": "body.quantity", "kept": _cid(ORDERS, "body.quantity", _num("<", 1)),
                                     "merged": _valid(ORDERS, "body.quantity"), "mergedRule": "valid-boundary"}]


def test_req204_unresolved_index(generated):
    gen = generated("petclinic")
    unresolved = gen.factors["unresolved"]
    assert len(unresolved) == len(gen.cases_doc["unresolved"])
    # 생성 불가 초안: (출처, 규칙, 엔드포인트, key 뒤 세 값) → 초안. 겹치지 않아야 역대응이 성립한다
    drafts = {}
    for draft in gen.deriver.drafts:
        if draft.reason is not None:
            address = (draft.sources[0], draft.rule, draft.ep.label, tuple(draft.key[1:]))
            assert address not in drafts, address
            drafts[address] = draft
    matched = set()
    for index, (item, source) in enumerate(zip(unresolved, gen.cases_doc["unresolved"], strict=True)):
        assert item["index"] == index
        assert (item["rule"], item["reason"], item["source"]) == (source["rule"], source["reason"], source["source"])
        assert set(source) <= {"source", "reason", "endpoint", "rule", "cause"}  # cases.json 항목은 필드가 늘지 않는다
        if source["rule"] in ("item", "param") or source["source"].startswith("input:"):
            assert item["draftKey"] is None and item["cells"] == {}
        if item["draftKey"] is None:
            assert item["cells"] == {}
        else:
            address = (source["source"], source["rule"], source["endpoint"], tuple(item["draftKey"]))
            draft = drafts[address]
            assert item["cells"] == draft.cell_info.cells and item["draftKey"] == list(draft.key[1:])
            assert address not in matched
            matched.add(address)
    assert matched == set(drafts)  # 초안에서 온 슬롯은 모두 draftKey를 갖고, 나머지는 초안 이전 건너뜀이다
    assert sum(1 for item in unresolved if item["draftKey"] is None) == len(unresolved) - len(drafts)
    # 같은 정렬 키가 겹치는 슬롯(enum-value 4건): 위치가 cases.json과 맞고 draftKey가 초안 순서를 따른다
    duplicates = [item for item in unresolved
                  if item["source"] == f"graph:endpoint:{UPDATE}" and item["rule"] == "enum-value"]
    assert len(duplicates) == 4
    positions = [item["draftKey"][1] for item in duplicates]
    assert positions == sorted(positions) and len(set(positions)) == 4
    assert all(item["cells"] == {"body.status": _valid(UPDATE, "body.status")} for item in duplicates)


# --- REQ-205 -------------------------------------------------------------------------------------------------------

def _expected_methods(bundle) -> dict[str, list[str]]:
    """엔드포인트 라벨 → 대응 계획 `클래스#메서드`(ext.calls에서 정확히 하나에 대응하는 것만, 독립 구현)."""
    calls = bundle.read("ext.json").get("calls", [])
    out: dict[str, set] = {}
    for plan in bundle.read("plans.json"):
        hits = {c["endpoint"] for c in calls
                if c["service"].replace("$", ".").split(".")[-1] == plan["class"] and c["method"] == plan["method"]}
        if len(hits) == 1:
            out.setdefault(next(iter(hits)).split(":", 1)[1], set()).add(f"{plan['class']}#{plan['method']}")
    return {label: sorted(methods) for label, methods in out.items()}


@pytest.mark.parametrize("name", ("controlled", "petclinic", "missing"))
def test_req205_sources(tmp_path, generated, name):
    if name == "missing":
        gen = _Generated(_make_bundle(tmp_path / "m", _load_docs(FIXTURES / "controlled"), missing=["auth"]),
                         tmp_path / "m-out")
        assert gen.factors["sources"]["input:auth"] == {"kind": "input", "methods": [], "condition": None,
                                                        "expected": None}
    else:
        gen = generated(name)
    sources = gen.factors["sources"]
    addresses = {s for e in gen.factors["endpoints"] for f in e["fields"] for k in f["classes"] for s in k["sources"]}
    addresses |= {s.rstrip("~") for case in gen.cases_doc["cases"] for s in case["sources"]}
    addresses |= {item["source"] for item in gen.factors["unresolved"]}
    assert addresses <= set(sources)
    plans = {f"{plan['file']}#{item['index']}@{item['conditionSha'][:12]}": (plan, item)
             for plan in gen.bundle.read("plans.json") for item in plan["items"]}
    keyparams = {}
    for kp in gen.bundle.read("keyparams.json"):
        for p_index, param in enumerate(kp.get("parameters", [])):
            for r_index, reason in enumerate(param["reasons"]):
                sha = hashlib.sha256(reason["detail"].encode("utf-8")).hexdigest()[:12]
                keyparams[f"{kp['file']}#{p_index}.{r_index}@{sha}"] = (kp, reason)
    kinds = set()
    for address, entry in sources.items():
        kinds.add(entry["kind"])
        if address in plans:
            plan, item = plans[address]
            assert entry == {"kind": "plan", "methods": [f"{plan['class']}#{plan['method']}"],
                             "condition": item["condition"], "expected": item["expected"]}
        elif address in keyparams:
            kp, reason = keyparams[address]
            assert entry == {"kind": "keyparams", "methods": [f"{kp['class']}#{kp['method']}"],
                             "condition": reason["detail"], "expected": None}
        else:
            prefix = address.split(":", 1)[0]
            assert prefix in ("graph", "harness", "input"), address
            assert entry == {"kind": prefix, "methods": [], "condition": None, "expected": None}
    assert {"plan", "graph"} <= kinds
    if name == "petclinic":
        assert {"keyparams", "harness"} <= kinds
    expected = _expected_methods(gen.bundle)
    for endpoint in gen.factors["endpoints"]:
        assert endpoint["methods"] == expected.get(endpoint["endpoint"], []), endpoint["endpoint"]
    for marker in ("/Users/", "/home/", "/private/"):
        assert marker not in gen.text


# --- REQ-206 -------------------------------------------------------------------------------------------------------

def test_req206_deterministic(tmp_path):
    first = _Generated(_real_bundle(tmp_path / "a" / "deep"), tmp_path / "a" / "deep" / "out")
    second = _Generated(_real_bundle(tmp_path / "b"), tmp_path / "b" / "out")
    assert (first.out / "factors.json").read_bytes() == (second.out / "factors.json").read_bytes()
    universe = {item["endpoint"]: list(item["fields"]) for item in first.derivation.universe["theoretical"]["factors"]
                if "fields" in item}  # 모수 계산 순서(cases.json은 키 정렬본이라 순서 기준이 아니다)
    for entry in first.factors["endpoints"]:
        assert [f["field"] for f in entry["fields"]] == universe[entry["endpoint"]]
    assert str(tmp_path) not in first.text


def test_factors_omitted_when_empty(tmp_path, generated):
    derivation = generated("controlled").derivation
    bare = dataclasses.replace(derivation, factors={})
    written = render_module.render(bare, tmp_path / "bare")
    assert "factors.json" not in written and not (tmp_path / "bare" / "factors.json").exists()
    positional = derive_module.Derivation(derivation.cases, derivation.unresolved, derivation.universe, "UTC")
    assert positional.factors == {}


# --- Task 3: td.detviz 결합·집계(REQ-206, 208, 212, 213) ---------------------------------------------------------
def _vid(endpoint: str, field: str, name: str) -> str:
    return _cid(endpoint, field, ("count", name))


def _small_rows():
    """(case, endpoint, rule, strict, class, pair, bbtg, graph, status, code). a-vb는 undefined(notRun)로 바꾼다."""
    from test_unit_detgen import _SUMMARY_CASES
    rows = [list(row) for row in _SUMMARY_CASES]
    for row in rows:
        if row[0] == "a-vb":
            row[8] = "undefined"
    return [tuple(row) for row in rows]


def _small_factors():
    """POST /a: body.x(valid,x1,x2) × body.y(valid,y1) → 쌍 6. PUT /b: body.z(valid,z1,z2). GET /c: 필드 없음."""
    ids = {}
    endpoints = []
    for label, field, names in (("POST /a", "body.x", ["x1", "x2"]), ("POST /a", "body.y", ["y1"]),
                                ("PUT /b", "body.z", ["z1", "z2"])):
        ids[(field, label)] = (_valid(label, field), {name: _vid(label, field, name) for name in names})
    def klasses(label, field):
        valid, rest = ids[(field, label)]
        out = [{"id": valid, "kind": "valid", "label": "valid", "sources": []}]
        for name, class_id in sorted(rest.items(), key=lambda item: item[1]):
            out.append({"id": class_id, "kind": "count", "label": name, "sources": []})
        return out
    endpoints = [
        {"endpoint": "POST /a", "methods": [], "fields": [{"field": "body.x", "classes": klasses("POST /a", "body.x")},
                                                          {"field": "body.y", "classes": klasses("POST /a", "body.y")}]},
        {"endpoint": "PUT /b", "methods": [], "fields": [{"field": "body.z", "classes": klasses("PUT /b", "body.z")}]},
        {"endpoint": "GET /c", "methods": [], "fields": []}]
    x1, x2 = ids[("body.x", "POST /a")][1]["x1"], ids[("body.x", "POST /a")][1]["x2"]
    y1 = ids[("body.y", "POST /a")][1]["y1"]
    z1 = ids[("body.z", "PUT /b")][1]["z1"]

    def case(cells, boundaries=(), out=None):
        return {"rule": "r", "cells": cells, "boundaries": list(boundaries), "stored": [], "storedBoundaries": [],
                "enumValue": None, "inModel": out is None, "outReason": out, "mergedRules": [], "cellConflicts": []}
    cases = {"a-base": case({}), "a-vb": case({"body.x": x1}, [x1]), "a-v1": case({"body.y": y1}, [y1, x1]),
             "a-v2": case({}), "a-v3": case({}, out="auth"), "b-base": case({}), "b-v1": case({}), "b-vb": case({}),
             "b-v2": case({}, out="no-data"), "c-h": case({})}
    unresolved = [{"index": 0, "source": "src:u", "rule": "r", "reason": "unparsed", "draftKey": None,
                   "cells": {"body.z": z1}},
                  {"index": 1, "source": "src:v", "rule": "r", "reason": "unresolved-operand", "draftKey": None,
                   "cells": {"body.x": x2}}]
    return {"version": 1, "endpoints": endpoints, "sources": {}, "cases": cases, "unresolved": unresolved}, \
        {"x1": x1, "x2": x2, "y1": y1, "z1": z1, "z2": ids[("body.z", "PUT /b")][1]["z2"]}


def _small(tmp_path):
    from test_unit_detgen import make_det_results
    gen_dir, s07_dir = make_det_results(tmp_path, rows=_small_rows())
    factors, ids = _small_factors()
    # 실제 cases.json처럼 생성 불가 항목이 endpoint를 갖게 한다(집계는 칸의 클래스로 판정하므로 둘이 일치해야 한다).
    cases_doc = json.loads((gen_dir / "cases.json").read_text(encoding="utf-8"))
    owner = {0: "PUT /b", 1: "POST /a"}
    cases_doc["unresolved"] = [{"source": f"src:{i}", "reason": "r", "endpoint": owner[i]} for i in (0, 1)]
    (gen_dir / "cases.json").write_text(json.dumps(cases_doc), encoding="utf-8")
    (gen_dir / "factors.json").write_text(json.dumps(factors, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return gen_dir, s07_dir, factors, ids


def test_build_aggregates_small(tmp_path):
    from td import detviz
    gen_dir, s07_dir, factors, ids = _small(tmp_path)
    doc = detviz.build(gen_dir, s07_dir)
    assert doc["version"] == 1 and doc["genId"] == gen_dir.name and doc["factors"] == factors
    a = doc["aggregates"]["byEndpoint"]["POST /a"]
    valid_x, valid_y = _valid("POST /a", "body.x"), _valid("POST /a", "body.y")
    state = {class_id: info["state"] for class_id, info in a["classes"].items()}
    assert state[valid_x] == "covered-pass" and state[valid_y] == "covered-pass"
    assert state[ids["x1"]] == "covered-notrun"    # a-vb만(undefined)
    assert state[ids["y1"]] == "covered-fail"      # a-v1만(failed)
    assert state[ids["x2"]] == "unresolved"        # 케이스 없음 + 생성 불가 슬롯 1
    b = doc["aggregates"]["byEndpoint"]["PUT /b"]
    assert b["classes"][ids["z1"]]["state"] == "unresolved" and b["classes"][ids["z2"]]["state"] == "empty"
    assert {info["state"] for info in [*a["classes"].values(), *b["classes"].values()]} == {
        "covered-pass", "covered-fail", "covered-notrun", "unresolved", "empty"}
    assert a["classes"][ids["x2"]]["unresolved"] == [{"index": 1, "reason": "unresolved-operand"}]
    # valid는 칸이 비었거나 valid인 inModel 케이스: a-base, a-vb(x=x1이라 제외), a-v1, a-v2 → x: a-base, a-v1, a-v2
    assert a["classes"][valid_x]["cases"] == ["a-base", "a-v1", "a-v2"]      # a-v3은 모델 밖
    assert a["classes"][ids["x1"]]["cases"] == ["a-vb"]
    assert a["classes"][ids["x1"]]["boundaryCases"] == 2 and a["classes"][ids["y1"]]["boundaryCases"] == 1
    assert a["classes"][valid_x]["boundaryCases"] == 0
    # 쌍: x(valid,x1,x2) × y(valid,y1)
    assert a["pairs"]["total"] == 6 and a["pairs"]["covered"] == 3
    order = [klass["id"] for klass in factors["endpoints"][0]["fields"][0]["classes"]]   # valid 다음은 id 순
    counts = [[0, 0] for _ in order]
    counts[0] = [2, 1]
    counts[order.index(ids["x1"])] = [1, 0]
    assert a["pairs"]["matrix"] == [{"a": "body.x", "b": "body.y", "counts": counts}]
    assert b["pairs"] == {"total": 0, "covered": 0, "matrix": []}
    assert doc["aggregates"]["byEndpoint"]["GET /c"] == {"classes": {}, "pairs": {"total": 0, "covered": 0, "matrix": []}}
    summary = doc["aggregates"]["summary"]
    assert summary == {"endpoints": 3, "fields": 3, "classes": 8, "classesCovered": 5, "pairsCovered": 3, "pairsTotal": 6,
                       "outOfModel": {"auth": 1, "no-data": 1}}


def test_req213_status_mapping(tmp_path):
    from td import detviz
    from test_unit_detgen import make_det_results
    rows = [("p", "POST /a", "happy", 201, "2xx", None, None, None, "passed", None),
            ("p2", "POST /a", "happy", "2xx", "2xx", None, None, None, "passed", None),
            ("f", "POST /a", "violation", 400, "4xx", None, None, None, "failed", 422),
            ("f2", "POST /a", "violation", 400, "4xx", None, None, None, "failed", None),
            ("u", "POST /a", "happy", 200, "2xx", None, None, None, "undefined", None),
            ("c", "POST /a", "happy", 200, "2xx", None, None, None, "uncompilable", None),
            ("m", "GET /m", "happy", 200, "2xx", None, None, None, "passed", None)]
    gen_dir, s07_dir = make_det_results(tmp_path, rows=rows)
    # 결과 줄 없음: m의 결과 줄을 지운다
    lines = (s07_dir / "scenario-results.json").read_text(encoding="utf-8").splitlines()
    from td import scenarios
    ident = scenarios.GenIdent.from_gen_id(gen_dir.name)
    missing = next(ref.test_id for ref in scenarios.pickle_refs(gen_dir, ident) if ref.name == "m")
    kept = [line for line in lines if json.loads(line)["testId"] != missing]
    assert len(kept) == len(lines) - 1
    (s07_dir / "scenario-results.json").write_text("\n".join(kept) + "\n", encoding="utf-8")
    factors = {"version": 1, "endpoints": [], "sources": {}, "cases": {}, "unresolved": []}
    (gen_dir / "factors.json").write_text(json.dumps(factors), encoding="utf-8")
    results = detviz.build(gen_dir, s07_dir)["caseResults"]
    assert results["p"] == {"endpoint": "POST /a", "status": "passed", "observed": 201, "expectStrict": 201}
    assert results["p2"] == {"endpoint": "POST /a", "status": "passed", "observed": None, "expectStrict": None}
    assert results["f"] == {"endpoint": "POST /a", "status": "failed", "observed": 422, "expectStrict": 400}
    assert results["f2"]["status"] == "failed" and results["f2"]["observed"] is None
    for case_id in ("u", "c", "m"):
        assert results[case_id]["status"] == "notRun" and results[case_id]["observed"] is None, case_id
    assert results["m"]["endpoint"] == "GET /m"


def test_build_factors_missing(tmp_path):
    from td import detviz
    from test_unit_detgen import make_det_results
    gen_dir, s07_dir = make_det_results(tmp_path)
    with pytest.raises(detviz.FactorsMissing):
        detviz.build(gen_dir, s07_dir)


def test_build_schema(tmp_path):
    from td import detviz
    gen_dir, s07_dir, _factors, _ids = _small(tmp_path)
    doc = detviz.build(gen_dir, s07_dir)
    detviz.validate(doc)
    broken = copy.deepcopy(doc)
    broken["aggregates"]["summary"]["extra"] = 1
    with pytest.raises(jsonschema.ValidationError):
        detviz.validate(broken)
    broken = copy.deepcopy(doc)
    next(iter(broken["caseResults"].values()))["status"] = "undefined"
    with pytest.raises(jsonschema.ValidationError):
        detviz.validate(broken)


def test_req206_build_path_independent(tmp_path):
    import shutil
    from td import detviz
    gen_dir, s07_dir, _factors, _ids = _small(tmp_path / "one")
    # genId는 디렉터리 이름이라 같은 이름을 다른 상위 경로에 복사한다.
    other = tmp_path / "two" / "deeper"
    shutil.copytree(tmp_path / "one", other)
    first = detviz.build(gen_dir, s07_dir)
    second = detviz.build(other / "generated" / gen_dir.name, other / "S07" / s07_dir.name)
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert str(tmp_path) not in json.dumps(first)


def test_req212_source_checksum_unaffected():
    from td.detgen import stage
    names = {path.name for path in stage.SOURCE_DIR.glob("*.py")}
    assert "detviz.py" not in names
    assert not any(name in ("detviz.js", "det.html.j2") for name in names)
    td_dir = stage.SOURCE_DIR.parent
    assert (td_dir / "detviz.py").is_file()
    before = stage.source_checksum()
    scratch = td_dir / "detviz_scratch_probe.py"
    try:
        scratch.write_text("# 체크섬 대상이 아님을 보이는 임시 파일\n", encoding="utf-8")
        assert stage.source_checksum() == before
    finally:
        scratch.unlink(missing_ok=True)
    assert stage.source_checksum() == before


def test_build_rejects_bad_cases_json(tmp_path):
    from td import detviz
    gen_dir, s07_dir, _factors, _ids = _small(tmp_path)
    cases_path = gen_dir / "cases.json"
    good = cases_path.read_text(encoding="utf-8")
    for bad in ("not json", "[]", json.dumps({"cases": "x"}),
                json.dumps({"cases": [{"id": "a"}]})):
        cases_path.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            detviz.build(gen_dir, s07_dir)
    cases_path.unlink()
    with pytest.raises(ValueError):
        detviz.build(gen_dir, s07_dir)
    cases_path.write_text(good, encoding="utf-8")
    detviz.build(gen_dir, s07_dir)

def test_validate_composes_factors_schema(tmp_path):
    """det-viz 스키마가 factors.schema.json을 실제로 합성한다: factors가 어긋난 문서는 거부된다."""
    from td import detviz
    gen_dir, s07_dir, _factors, _ids = _small(tmp_path)
    doc = detviz.build(gen_dir, s07_dir)
    assert "$defs" not in json.loads(detviz.SCHEMA_PATH.read_text(encoding="utf-8"))
    broken = copy.deepcopy(doc)
    broken["factors"]["endpoints"][0]["fields"][0]["classes"][1]["id"] = "not-a-class-id"
    with pytest.raises(jsonschema.ValidationError):
        detviz.validate(broken)
    broken = copy.deepcopy(doc)
    broken["factors"]["version"] = 2
    with pytest.raises(jsonschema.ValidationError):
        detviz.validate(broken)


def test_unresolved_endpoint_mapping_petclinic(generated):
    """칸의 클래스로 정한 생성 불가 슬롯의 엔드포인트가 cases.json unresolved[index].endpoint와 같다."""
    made = generated("petclinic")
    owners = {}
    for entry in made.factors["endpoints"]:
        for field in entry["fields"]:
            for klass in field["classes"]:
                owners[klass["id"]] = entry["endpoint"]
    checked = 0
    for slot in made.factors["unresolved"]:
        if not slot["cells"]:
            continue
        by_cells = {owners[class_id] for class_id in slot["cells"].values()}
        assert by_cells == {made.cases_doc["unresolved"][slot["index"]]["endpoint"]}, slot["index"]
        checked += 1
    assert checked > 0


# --- Task 4: compare 통합·det.html·링크(REQ-209, REQ-211) ---------------------------------------------------------
def test_build_trace(tmp_path):
    """화면 추적용 `trace`: 케이스별 출처 주소(`~` 제거)와 생성 불가 항목의 엔드포인트(cases.json 순서)."""
    from td import detviz
    gen_dir, s07_dir, _factors, _ids = _small(tmp_path)
    cases_doc = json.loads((gen_dir / "cases.json").read_text(encoding="utf-8"))
    cases_doc["cases"][0]["sources"] = ["plan:A#m:0~", "plan:A#m:1"]
    (gen_dir / "cases.json").write_text(json.dumps(cases_doc), encoding="utf-8")
    doc = detviz.build(gen_dir, s07_dir)
    trace = doc["trace"]
    assert set(trace["caseSources"]) == set(doc["caseResults"])
    assert trace["caseSources"][cases_doc["cases"][0]["id"]] == ["plan:A#m:0", "plan:A#m:1"]
    assert trace["unresolvedEndpoints"] == ["PUT /b", "POST /a"]
    detviz.validate(doc)


def _det_compare_run(tmp_path: Path, monkeypatch, *, factors: bool = True) -> tuple[Path, Path]:
    """합성 compare run + det arm(test_compare.add_det_arm). factors=True면 generation에 factors.json을 둔다."""
    from test_compare import add_det_arm, make_compare_run
    from td import scenarios
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_dir = make_compare_run(tmp_path)
    add_det_arm(run_dir, tmp_path, monkeypatch)
    gen_dir = scenarios.generation_dir("petclinic", "det-cccccccc-r1")
    if factors:
        small, _ids = _small_factors()
        cases_doc = json.loads((gen_dir / "cases.json").read_text(encoding="utf-8"))
        cases_doc["unresolved"] = [{"source": f"src:{i}", "reason": "r", "endpoint": owner}
                                   for i, owner in enumerate(("PUT /b", "POST /a"))]
        (gen_dir / "cases.json").write_text(json.dumps(cases_doc), encoding="utf-8")
        (gen_dir / "factors.json").write_text(json.dumps(small, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    state_file = run_dir / "stages" / "S12.json"
    state_file.write_text(json.dumps({"id": "S12", "status": "passed", "reason": None,
                                      "outputs": {"compare": str(run_dir / "S12" / "compare")}}))
    from td import state
    state.set_run_field(run_dir, "stages.S12", "passed")
    return run_dir, gen_dir


def _run_compare(run_dir: Path) -> Path:
    from test_compare import SUT_FILE
    from td import compare
    assert compare.main(["run", str(run_dir), "--sut-file", str(SUT_FILE)]) == 0
    return run_dir / "S12" / "compare"


def _compare_doc(out: Path) -> dict:
    return json.loads((out / "compare.json").read_text(encoding="utf-8"))


def _assert_no_det_page(out: Path):
    assert not (out / "det.html").exists() and not (out / "det-viz.json").exists()
    assert 'href="det.html"' not in (out / "compare.html").read_text(encoding="utf-8")


def _without_viz(document: dict) -> dict:
    document = copy.deepcopy(document)
    document["deterministic"].pop("viz", None)
    return document


def test_req209_ok_baseline(tmp_path, monkeypatch):
    """정상 경로(대조군): viz ok ⇔ det-viz.json·det.html 존재, compare.html·run 페이지 링크."""
    from td import compare, detviz
    from td.site import pages
    run_dir, _gen = _det_compare_run(tmp_path, monkeypatch)
    out = _run_compare(run_dir)
    document = _compare_doc(out)
    compare.validate(document)
    assert document["deterministic"]["viz"] == {"status": "ok", "reason": None}
    detviz.validate(json.loads((out / "det-viz.json").read_text(encoding="utf-8")))
    html = (out / "det.html").read_text(encoding="utf-8")
    assert 'href="site.css"' in html and "Cytoscape Consortium" in html
    assert 'href="det.html"' in (out / "compare.html").read_text(encoding="utf-8")
    site = tmp_path / "site"
    index = pages.render_run(run_dir, site).read_text(encoding="utf-8")
    assert 'href="compare/det.html"' in index and 'href="compare/compare.html"' in index
    assert (site / "compare" / "det.html").is_file()
    assert "static/site.css" in (site / "compare" / "det.html").read_text(encoding="utf-8")
    assert 'href="det.html"' in (site / "compare" / "compare.html").read_text(encoding="utf-8")


def test_req209_absent(tmp_path, monkeypatch):
    """(a) factors.json 없음 → viz absent, 파일·링크 없음, run 페이지 링크 없음."""
    from td import compare
    from td.site import pages
    run_dir, _gen = _det_compare_run(tmp_path, monkeypatch, factors=False)
    out = _run_compare(run_dir)
    document = _compare_doc(out)
    compare.validate(document)
    assert document["deterministic"]["status"] == "measured"
    assert document["deterministic"]["viz"] == {"status": "absent", "reason": None}
    _assert_no_det_page(out)
    assert "factors.json" in (out / "compare.html").read_text(encoding="utf-8")   # 사유 한 줄
    site = tmp_path / "site"
    index = pages.render_run(run_dir, site).read_text(encoding="utf-8")
    assert "compare/det.html" not in index and 'href="compare/compare.html"' in index


def test_req209_build_error(tmp_path, monkeypatch):
    """(b) detviz.build 예외 → compare 성공, viz failed(사유 문자열, 홈 경로 없음), 파일·링크 없음, 나머지 문서 동일."""
    from td import compare, detviz
    run_dir, _gen = _det_compare_run(tmp_path, monkeypatch)
    healthy = _compare_doc(_run_compare(run_dir))
    assert healthy["deterministic"]["viz"]["status"] == "ok"

    def broken(gen_dir, s07_dir):
        raise RuntimeError(f"boom at {Path.home()}/secret/factors.json")
    monkeypatch.setattr(detviz, "build", broken)
    out = _run_compare(run_dir)
    document = _compare_doc(out)
    compare.validate(document)
    viz = document["deterministic"]["viz"]
    assert viz["status"] == "failed" and isinstance(viz["reason"], str) and "RuntimeError" in viz["reason"]
    assert str(Path.home()) not in viz["reason"]
    _assert_no_det_page(out)
    assert _without_viz(document) == _without_viz(healthy)


def test_req209_write_error(tmp_path, monkeypatch):
    """(c) det-viz.json 쓰기 OSError → (b)와 같은 결과."""
    from td import compare
    run_dir, _gen = _det_compare_run(tmp_path, monkeypatch)
    healthy = _compare_doc(_run_compare(run_dir))
    original = Path.write_text

    def failing(self, *args, **kwargs):
        if self.name == "det-viz.json":
            raise OSError("disk full")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", failing)
    out = _run_compare(run_dir)
    monkeypatch.setattr(Path, "write_text", original)
    document = _compare_doc(out)
    compare.validate(document)
    assert document["deterministic"]["viz"]["status"] == "failed"
    assert "OSError" in document["deterministic"]["viz"]["reason"]
    _assert_no_det_page(out)
    assert _without_viz(document) == _without_viz(healthy)


def test_req209_render_error(tmp_path, monkeypatch):
    """(d) det.html 템플릿 예외 → compare.html은 생기고 링크 없음, det.html 없음, viz failed."""
    from td import compare

    def broken(viz_doc, css_href):
        raise RuntimeError("template exploded")
    monkeypatch.setattr(compare, "render_det_html", broken)
    run_dir, _gen = _det_compare_run(tmp_path, monkeypatch)
    out = _run_compare(run_dir)
    document = _compare_doc(out)
    compare.validate(document)
    assert (out / "compare.html").is_file()
    assert document["deterministic"]["viz"]["status"] == "failed"
    assert "template exploded" in document["deterministic"]["viz"]["reason"]
    _assert_no_det_page(out)


def test_req209_rerender_error(tmp_path, monkeypatch):
    """(e) RERENDER["compare/"] 경로의 det.html 예외 → 게시 사본 compare.html 정상, det.html 없음, 게시 compare.json viz failed."""
    from td import compare
    from td.site import layout, pages
    run_dir, _gen = _det_compare_run(tmp_path, monkeypatch)
    out = _run_compare(run_dir)
    assert (out / "det.html").is_file()

    def broken(viz_doc, css_href):
        raise RuntimeError("rerender exploded")
    monkeypatch.setattr(compare, "render_det_html", broken)
    assert layout.RERENDER["compare/"] is layout._rerender_compare
    site = tmp_path / "site"
    index = pages.render_run(run_dir, site).read_text(encoding="utf-8")
    published = site / "compare"
    html = (published / "compare.html").read_text(encoding="utf-8")
    assert "탐색적 관찰" in html and 'href="det.html"' not in html
    assert not (published / "det.html").exists() and not (published / "det-viz.json").exists()
    document = json.loads((published / "compare.json").read_text(encoding="utf-8"))
    compare.validate(document)
    assert document["deterministic"]["viz"]["status"] == "failed"
    assert "compare/det.html" not in index
    # 원본 run 디렉터리는 건드리지 않는다
    assert _compare_doc(out)["deterministic"]["viz"]["status"] == "ok" and (out / "det.html").is_file()


@pytest.mark.parametrize("change", ["factors-removed", "det-null", "det-failed"])
def test_req209_stale_removed(tmp_path, monkeypatch, change):
    """(f) ok로 만든 뒤 factors 삭제·det 블록 null·failed 변형으로 재실행 → 이전 det-viz.json·det.html이 지워진다."""
    from td import compare
    from td.detgen import results as det_results
    run_dir, gen_dir = _det_compare_run(tmp_path, monkeypatch)
    out = _run_compare(run_dir)
    assert (out / "det.html").is_file() and (out / "det-viz.json").is_file()
    if change == "factors-removed":
        (gen_dir / "factors.json").unlink()
    elif change == "det-null":
        stage_path = run_dir / "stages" / "S06.json"
        stage = json.loads(stage_path.read_text(encoding="utf-8"))
        stage["arms"]["det"] = {"status": "skipped", "reason": "det 건너뜀"}
        stage_path.write_text(json.dumps(stage), encoding="utf-8")
    else:
        def broken(gen_dir, s07_dir):
            raise ValueError("summary broke")
        monkeypatch.setattr(det_results, "summarize", broken)
    document = _compare_doc(_run_compare(run_dir))
    compare.validate(document)
    det = document["deterministic"]
    if change == "factors-removed":
        assert det["viz"] == {"status": "absent", "reason": None}
    elif change == "det-null":
        assert det is None
    else:
        assert det["status"] == "failed" and "viz" not in det
    _assert_no_det_page(out)


def test_req209_missing_viz_key(tmp_path, monkeypatch):
    """(g) viz 키 없는 measured 블록(예전 compare.json) → compare.html 정상, 링크 없음, 낡은 det.html 삭제."""
    from td import compare
    run_dir, _gen = _det_compare_run(tmp_path, monkeypatch)
    out = _run_compare(run_dir)
    document = _without_viz(_compare_doc(out))
    assert (out / "det.html").is_file()
    compare.render_page(out, document)
    html = (out / "compare.html").read_text(encoding="utf-8")
    assert 'id="deterministic"' in html and 'href="det.html"' not in html
    assert not (out / "det.html").exists()
    assert "viz" not in document["deterministic"]


# --- REQ-211: 화면 -----------------------------------------------------------------------------------------------
HOSTILE_EXTRA = '<img src=x onerror="window.__pwned=1"> <b onclick="window.__pwned=2">x</b></script>'


@pytest.fixture(scope="module")
def det_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def _open_det(browser, html_path: Path, **context_kwargs):
    context = browser.new_context(**context_kwargs)
    blocked, errors = [], []

    def guard(route):
        if route.request.url.startswith(("file:", "data:")):
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort()
    context.route("**/*", guard)
    page = context.new_page()
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(html_path.as_uri())
    page.wait_for_function("window.__td_ready === true", timeout=30000)
    return context, page, blocked, errors


def _hostile_page(tmp_path: Path, generated) -> tuple[Path, dict, dict, str, str]:
    """viz-kinds generation으로 det-viz 문서를 만들고, 케이스 하나의 출처 조건식에 적대적 조각을 덧붙여 det.html을 그린다."""
    import shutil
    from td import compare, detviz
    made = generated("viz-kinds")
    gen_dir = tmp_path / "det-0000beef-r1"
    shutil.copytree(made.out, gen_dir)
    s07_dir = tmp_path / "S07"
    s07_dir.mkdir()
    doc = detviz.build(gen_dir, s07_dir)
    case = next(c for c in made.cases_doc["cases"] if c["endpoint"] == ITEMS and c["sources"]
                and doc["factors"]["sources"].get(c["sources"][0].rstrip("~"), {}).get("condition"))
    address = case["sources"][0].rstrip("~")
    doc["factors"]["sources"][address]["condition"] += HOSTILE_EXTRA
    detviz.validate(doc)
    out = tmp_path / "compare"
    out.mkdir()
    (out / "det-viz.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    html_path = out / "det.html"
    html_path.write_text(compare.render_det_html(doc, "site.css"), encoding="utf-8")
    shutil.copy2(REPO_ROOT / "site-gen" / "td" / "site" / "static" / "site.css", out / "site.css")
    return html_path, doc, made.cases_doc, case["id"], doc["factors"]["sources"][address]["condition"]


def test_req211_hostile_dom(tmp_path, generated, det_browser):
    """적대적 문자열이 든 det.html: 주입 요소·실행 표식 없음, 원문은 textContent로 보인다. DOM 계약(노드 수·칸·행렬)도 맞다."""
    html_path, doc, cases_doc, case_id, condition = _hostile_page(tmp_path, generated)
    context, page, blocked, errors = _open_det(det_browser, html_path)
    try:
        assert page.evaluate("window.__pwned") is None
        assert page.locator("img, [onerror], [onclick]").count() == 0
        page.evaluate("id => window.__detviz.select(id)", case_id)
        assert condition in page.locator('#panel [data-k="condition"]').first.text_content()
        result = doc["caseResults"][case_id]
        expect = "-" if result["expectStrict"] is None else str(result["expectStrict"])
        assert page.locator('#panel [data-k="expect"]').first.text_content() == expect
        assert page.locator('#panel [data-k="observed"]').first.text_content() == "-"
        assert page.evaluate("window.__pwned") is None
        assert page.locator("img, [onerror], [onclick]").count() == 0
        assert '== "</script><img onerror=x>"' in page.locator("body").text_content()
        # DOM 계약: 격자 칸·행렬 수, 선택 엔드포인트의 노드 수와 id
        factors = doc["factors"]
        classes = sum(len(f["classes"]) for e in factors["endpoints"] for f in e["fields"])
        matrices = sum(len(e["pairs"]["matrix"]) for e in doc["aggregates"]["byEndpoint"].values())
        assert page.locator("[data-class-id]").count() == classes
        assert page.locator("details [data-pair]").count() == matrices == page.locator("[data-pair]").count()
        options = page.eval_on_selector_all("select option", "els => els.map(e => e.value)")
        assert options == [e["endpoint"] for e in factors["endpoints"]]
        for label in (ITEMS, "GET /vk/ping"):
            page.locator("select").first.select_option(value=label)
            entry = next(e for e in factors["endpoints"] if e["endpoint"] == label)
            klasses = [k for f in entry["fields"] for k in f["classes"]]
            want = (len({a.rstrip("~") for k in klasses for a in k["sources"]}) + len(klasses)
                    + sum(1 for r in doc["caseResults"].values() if r["endpoint"] == label)
                    + sum(1 for item in cases_doc["unresolved"] if item["endpoint"] == label))
            node = page.locator("[data-node-count]").first
            ids = [x for x in (node.get_attribute("data-node-ids") or "").split(",") if x]
            assert int(node.get_attribute("data-node-count")) == want == len(ids) == len(set(ids)), label
            assert ids == sorted(ids)
        details = page.locator("details:has([data-pair])").first
        assert details.evaluate("e => e.open") is False
        details.locator("summary").first.click()
        assert details.evaluate("e => e.open") is True
        assert blocked == [] and errors == []
    finally:
        context.close()


def test_req211_static_rules(tmp_path):
    """정적 검사: detviz.js에 금지 sink 없음, det.html에 <script src= 0개, Cytoscape·detviz.js 인라인."""
    from td import compare, detviz
    static = REPO_ROOT / "site-gen" / "td" / "site" / "static"
    script = (static / "detviz.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in script, sink
    assert "window.__td_ready = true" in script and "__detviz" in script
    gen_dir, s07_dir, _factors, _ids = _small(tmp_path)
    html = compare.render_det_html(detviz.build(gen_dir, s07_dir), "site.css")
    assert "<script src=" not in html and not re.search(r"<script[^>]*\bsrc\s*=", html)
    assert "Cytoscape Consortium" in html and script.strip()[:200] in html
    assert html.count('<script type="application/json"') == 1
