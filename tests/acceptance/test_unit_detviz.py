"""det-viz 단위 테스트. Task 2: 클래스 레지스트리·칸 계산·factors.json(REQ-201~206).

번들은 `test_unit_detgen`의 헬퍼로 만든다(controlled·petclinic·viz-kinds). 기대값은 설계 §5.1~5.3의 규칙을
테스트 안에서 다시 계산하거나(클래스 id 공식) 행마다 고정한다(칸 규칙).
"""
import copy
import dataclasses
import hashlib
import json
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
