"""det pairwise 단위 테스트(Task 3: 후보 모델·배제·PICT 실행, REQ-305·306·307·311).

모델 수준 테스트는 `_Deriver`의 계획 해석 단계만 돌려 엔드포인트 제약을 채운 뒤 `build_model`을 부른다(derive 통합은 Task 4).
실제 PICT는 세션 fixture `pict_tool`(고정 커밋 빌드)을 쓰고, rc·출력 계약은 argv를 기록하는 가짜 pict로 주입한다.
"""
import itertools
import json
import os
import stat
import time
from pathlib import Path

import pytest

from td.detgen import derive as derive_module
from td.detgen import pairwise as pw
from td.detgen.constraints import OMIT, Spread, Uniq, Value
from test_unit_detgen import CONTROLLED, FIXTURES, _load_docs, _make_bundle, _real_bundle  # noqa: E402

KINDS = FIXTURES / "pairwise-kinds"
MAKE = "POST /svc/kits"
PATCH_PUT = "PUT /svc/kits/{kitId}"
TRIM = "PATCH /svc/kits/{kitId}"
TAGS = "POST /svc/tags"
CREATE = "POST /api/reservations"


# --- 도우미 -------------------------------------------------------------------------------------

def _deriver(bundle):
    deriver = derive_module._Deriver(bundle)
    for plan in sorted(deriver.plans, key=lambda p: p["file"]):
        deriver._plan(plan)
    return deriver


def _kinds(tmp_path, mutate=None):
    docs = _load_docs(KINDS)
    if mutate is not None:
        mutate(docs)
    return _deriver(_make_bundle(tmp_path / "kinds", docs))


def _model(deriver, label, order=2):
    ep = next(e for e in deriver.endpoints.values() if e.label == label)
    return ep, pw.build_model(ep, deriver.cons, deriver.catalog, order)


def _raw(candidate):
    value = candidate.value
    if value is OMIT:
        return "<omit>"
    value = value.value
    if isinstance(value, Uniq):
        return "<uniq>"
    if isinstance(value, Spread):
        return ("<spread>", value.lo, value.hi)
    return value


def _param(model, field):
    return next(p for p in model.params if p["field"] == field)


def _values(model, field):
    return [_raw(c) for c in _param(model, field)["candidates"]]


def _label_of(model, field, raw):
    return next(c.label for c in _param(model, field)["candidates"] if _raw(c) == raw)


def _tool(pict_tool) -> pw.PictTool:
    return pw.PictTool(Path(pict_tool["path"]), pict_tool["commit"], pict_tool["binarySha256"])


def _fake_pict(tmp_path, stdout="", rc=0, stderr="", sleep=0) -> tuple[pw.PictTool, Path]:
    """argv와 모델 파일 경로를 기록하고 정해 둔 출력·종료 코드를 내는 가짜 pict."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "argv.json"
    out = tmp_path / "stdout.txt"
    out.write_text(stdout, encoding="utf-8")
    script = tmp_path / "fake-pict"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        f"model = open(sys.argv[1], encoding='utf-8').read() if len(sys.argv) > 1 and os.path.exists(sys.argv[1]) else None\n"
        f"json.dump({{'argv': sys.argv[1:], 'model': model}}, open({str(log)!r}, 'w'))\n"
        f"time.sleep({sleep})\n"
        f"sys.stdout.write(open({str(out)!r}, encoding='utf-8').read())\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.exit({rc})\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return pw.PictTool(script, "f" * 40, "0" * 64), log


def _two_param_model() -> pw.EndpointModel:
    def cands(*raws):
        return [pw.Candidate(f"v{i}", "literal", Value(raw, "input")) for i, raw in enumerate(raws)]
    params = [{"param": "p0", "loc": "body", "field": "a", "candidates": cands(1, 2)},
              {"param": "p1", "loc": "body", "field": "b", "candidates": cands("x", "y", "z")}]
    return pw.EndpointModel(params, {}, [], [{"p0": "v1", "p1": "v2"}], 2, 2, None, None)


def _work_leftovers(work: Path) -> list:
    return sorted(p.name for p in work.iterdir()) if work.exists() else []


# --- REQ-305 후보 모델 ------------------------------------------------------------------------------

@pytest.mark.parametrize("row", ["baseline", "single-atom", "multi-atom", "enum", "branch"])
def test_req305_candidate_sources(tmp_path, row):
    deriver = _kinds(tmp_path)
    _, model = _model(deriver, MAKE)
    if row == "baseline":  # 첫 후보는 항상 baseline
        assert _values(model, "size")[0] == 1
        assert _values(model, "credit")[0] == 45
        assert _values(model, "grade")[0] == "PLAIN"
        assert _values(model, "legacy")[0] == "<omit>"
        assert _values(model, "code")[0] == "<uniq>"
    elif row == "single-atom":  # `size < 1 || size > 8` 유효 경계 1·8(1은 baseline과 같아 한 번만)
        assert _values(model, "size") == [1, 8]
        assert _values(model, "legacy") == ["<omit>", None]  # `legacy != null`의 유효 경계는 null
    elif row == "multi-atom":  # 다원자 논리곱: 유효 경계 + 위반값(violations[0]), 출처 순서
        assert _values(model, "credit") == [45, 40, 39, 44]
        assert _values(model, "code") == ["<uniq>", "VIPKIT", "PROMO"]
    elif row == "enum":  # 상태 전이 필드가 아닌 enum은 모든 상수(RUBY는 `~` 필터로 빠진다)
        assert _values(model, "grade") == ["PLAIN", "GOLD"]
        _, tags = _model(deriver, TAGS)
        assert _values(tags, "grade") == ["PLAIN", "GOLD", "RUBY"]
        assert _values(tags, "shade") == ["DARK", "LIGHT"]
    else:  # 분기 진입 조건 참 값
        assert "PROMO" in _values(model, "code")
    for param in model.params:  # 중복 없음, 라벨은 v0..vn
        raws = [json.dumps(_raw(c), default=str) for c in param["candidates"]]
        assert len(raws) == len(set(raws))
        assert [c.label for c in param["candidates"]] == [f"v{i}" for i in range(len(raws))]


def test_req305_kinds(tmp_path):
    deriver = _kinds(tmp_path)
    ep, model = _model(deriver, MAKE)
    kinds = {c.kind for p in model.params for c in p["candidates"]} | {f["candidate"].kind for f in model.fixed.values()}
    assert kinds == {"literal", "omit", "null", "uniq", "spread"}
    legacy = _param(model, "legacy")["candidates"]
    assert [c.kind for c in legacy] == ["omit", "null"] and legacy[0].value is OMIT
    assert legacy[1].value.value is None
    code = _param(model, "code")["candidates"]
    assert [c.kind for c in code].count("uniq") == 1  # uniq는 필드당 최대 1개
    slot = model.fixed["body.slot"]["candidate"]
    assert slot.kind == "spread" and slot.value.value == Spread(10, 20, (10, 20))
    # Value를 그대로 담아 provenance·source·transform 보존
    credit = _param(model, "credit")["candidates"]
    assert credit[2].value.provenance == "derived" and credit[2].value.transform == "40-1"
    assert credit[2].value.source.startswith("plan-tests-KitService.make.json#1@")
    # 동치·평가: spread는 범위 대표(경계 제외 내부), uniq는 판단 불가(길이·형식은 baseline처럼 거짓)
    lt10 = next(c for a, cs in ep.error_disjuncts for c in cs if c.field == "slot" and c.op == "<")
    assert pw.truth(lt10, slot) is False
    eqlit = next(c for a, cs in ep.error_disjuncts for c in cs if c.op == "eqlit")
    assert pw.truth(eqlit, code[0]) is None
    # 직렬화: value | range, provenance, source, transform
    doc = pw.model_json(model)
    slot_doc = doc["fixed"]["body.slot"]
    assert slot_doc["range"] == {"lo": 10, "hi": 20, "excluded": [10, 20]} and "value" not in slot_doc
    legacy_doc = next(p for p in doc["params"] if p["field"] == "legacy")["candidates"]
    assert legacy_doc[0]["kind"] == "omit" and "value" not in legacy_doc[0]
    assert legacy_doc[1] == {"label": "v1", "kind": "null", "value": None, "provenance": "input",
                             "source": legacy_doc[1]["source"], "transform": "null"}
    assert set(doc) == {"params", "fixed", "dropped", "exclusions", "order", "effectiveOrder", "skipped", "reason"}
    json.dumps(doc)  # JSON 직렬화 가능


def test_req305_base_placeholder(tmp_path):
    """BASE 자리표시는 base(ignore_null=True) 값으로 바뀐다: `code != null && size > 5`의 위반값 BASE → uniq."""
    def add_notnull(docs):
        items = next(p for p in docs["plans.json"] if p["method"] == "make")["items"]
        items.append(dict(items[0], index=len(items), condition="form.code() != null && form.size() > 5"))
    deriver = _kinds(tmp_path, add_notnull)
    _, model = _model(deriver, MAKE)
    code = _param(model, "code")["candidates"]
    # baseline은 notnull 때문에 생략, `code != null`의 유효 경계는 null, 위반값 BASE는 uniq로 바뀌어 기존 uniq와 같다
    assert [c.kind for c in code] == ["omit", "uniq", "literal", "null", "literal"]
    assert all(c.value is OMIT or c.value != derive_module.BASE and c.value.value != derive_module.BASE for c in code)


def test_req305_filter_and_fixed(tmp_path):
    deriver = _kinds(tmp_path)
    _, model = _model(deriver, MAKE)
    dropped = {(d["field"], json.dumps(d["candidate"].get("value")), d["reason"]) for d in model.dropped}
    # (a) 원자식 하나짜리 오류 조건을 참으로 만드는 후보
    assert {("size", "10", "single-atom"), ("size", "9", "single-atom"),
            ("depth", "7", "single-atom"), ("depth", "6", "single-atom")} <= dropped
    # (b) 미해결 논리곱의 부분 제약(`~`)
    assert ("grade", '"RUBY"', "partial-constraint") in dropped
    assert all(d["address"].startswith("plan-tests-KitService.make.json#") and not d["address"].endswith("~")
               for d in model.dropped)
    fixed = {name: entry["reason"] for name, entry in model.fixed.items()}
    assert fixed == {"body.phase": "state-field", "body.slot": "count-field", "body.deposit": "rel-dependent",
                     "body.shade": "stored-or-unresolved-only", "body.depth": "single-candidate"}
    assert model.fixed["body.deposit"]["candidate"].value.transform == "relation-satisfy"
    assert model.fixed["body.depth"]["candidate"].value.value == 4
    assert model.fixed["body.shade"]["candidate"].value.value == "LIGHT"  # baseline
    assert [p["field"] for p in model.params] == ["code", "credit", "grade", "legacy", "size"]
    assert [p["param"] for p in model.params] == ["p0", "p1", "p2", "p3", "p4"]


def test_req305_rel_others(tmp_path):
    deriver = _kinds(tmp_path)
    ep = next(e for e in deriver.endpoints.values() if e.label == MAKE)
    rel = next(c for _, cs in ep.error_disjuncts for c in cs if c.op == "rel")
    assert rel.side == ("deposit",) and rel.others == ("size", "grade")


def test_req305_petclinic_model(tmp_path):
    deriver = _deriver(_real_bundle(tmp_path))
    ep, model = _model(deriver, CREATE)
    assert "priceTier" not in ep.state_fields
    fields = [p["field"] for p in model.params]
    assert "priceTier" in fields and "loyaltyPoints" in fields
    assert 499 in _values(model, "loyaltyPoints")
    assert _values(model, "priceTier") == ["BASIC", "VIP", "PREMIUM"]
    assert model.fixed["body.roomNumber"]["reason"] == "count-field"
    assert model.fixed["body.depositAmount"]["reason"] == "rel-dependent"
    rel = next(c for _, cs in ep.error_disjuncts for c in cs if c.op == "rel")
    assert set(rel.others) == {"nights", "priceTier"}
    assert model.skipped is None and model.reason is None and model.effective_order == 2


@pytest.mark.parametrize("which", ["controlled", "petclinic"])
def test_req305_candidate_floor(tmp_path, which):
    """후보 하한: 기존 valid-boundary 케이스가 모델 필드에 쓴 값, 그 필드의 enum 상수(상태 전이 제외) ⊆ 후보."""
    bundle = _make_bundle(tmp_path / "b", _load_docs(CONTROLLED)) if which == "controlled" else _real_bundle(tmp_path)
    cases = derive_module.derive(bundle).cases
    deriver = _deriver(bundle)
    checked = 0
    for ep in deriver.endpoints.values():
        model = pw.build_model(ep, deriver.cons, deriver.catalog, 2)
        for param in model.params:
            raws = [_raw(c) for c in param["candidates"]]
            mapping = "values" if param["loc"] == "body" else "query"
            for case in cases:
                if case.endpoint != ep.label or case.rule != "valid-boundary":
                    continue
                value = getattr(case, mapping).get(param["field"])
                if value is None or isinstance(value.value, str) and value.value.startswith("uniq:"):
                    continue
                assert value.value in raws, (ep.label, param["field"], value.value, raws)
                checked += 1
            fld = deriver.catalog.lookup(ep, param["field"])
            if fld.kind == "enum" and fld.name not in ep.state_fields:
                assert set(fld.constants) <= set(raws)
    assert checked > 0


# --- REQ-306 배제 조합 ------------------------------------------------------------------------------

@pytest.mark.parametrize("row", ["fixed-false", "zero", "one", "many", "undetermined-fixed"])
def test_req306_partial_evaluation(tmp_path, row):
    deriver = _kinds(tmp_path)
    if row == "fixed-false":  # depth(고정 4)로 `depth > 6`이 거짓 → 논리곱 버림, size 쪽 배제 없음
        _, model = _model(deriver, MAKE)
        size = _param(model, "size")["param"]
        assert all(size not in e for e in model.exclusions)
        _, put = _model(deriver, PATCH_PUT)  # 저장 상태 `size > 7`(선행 baseline 1) 거짓 → height 4 배제 없음
        height4 = _label_of(put, "height", 4)
        assert not any(e.get(_param(put, "height")["param"]) == height4 for e in put.exclusions)
    elif row == "zero":  # 저장 상태 `size < 5`가 참이고 모델 원자식 0개 → infeasible
        _, model = _model(deriver, TRIM)
        assert model.reason == "pairwise-infeasible" and model.exclusions == []
    elif row == "one":  # `size < 5 && width < 3` → width 2 제거, dropped reduced-single-atom
        _, model = _model(deriver, PATCH_PUT)
        assert _values(model, "width") == [3, 6, 7]  # 출처 순서: 유효 경계 다음 위반값
        reduced = [d for d in model.dropped if d["reason"] == "reduced-single-atom"]
        assert [(d["field"], d["candidate"]["value"]) for d in reduced] == [("width", 2)]
        assert reduced[0]["address"].startswith("plan-tests-KitService.patch.json#0@")
    elif row == "many":
        _, model = _model(deriver, PATCH_PUT)
        height, width = _param(model, "height")["param"], _param(model, "width")["param"]
        assert model.exclusions == [{height: _label_of(model, "height", 7), width: _label_of(model, "width", 7)}]
    else:  # 판단 불가 고정 원자식은 참으로 본다: 선행 baseline code는 uniq → `"X".equals(existing.code)` 판단 불가
        def add(docs):
            items = next(p for p in docs["plans.json"] if p["method"] == "patch")["items"]
            items.append(dict(items[0], index=len(items),
                              condition='"X".equals(existing.getCode()) && patch.width() > 6 && patch.height() > 5'))
        deriver = _kinds(tmp_path, add)
        ep, model = _model(deriver, PATCH_PUT)
        stored = next(c for _, cs in ep.error_disjuncts for c in cs if c.stored and c.op == "eqlit")
        assert pw.fixed_truth(deriver.cons, ep, stored, None) is None
        height, width = _param(model, "height")["param"], _param(model, "width")["param"]
        w7 = _label_of(model, "width", 7)
        assert model.exclusions == [{height: _label_of(model, "height", 7), width: w7},
                                    {height: _label_of(model, "height", 6), width: w7}]


def test_req306_petclinic_vip_exclusion(tmp_path):
    deriver = _deriver(_real_bundle(tmp_path))
    _, model = _model(deriver, CREATE)
    tier, points = _param(model, "priceTier")["param"], _param(model, "loyaltyPoints")["param"]
    expected = {tier: _label_of(model, "priceTier", "VIP"), points: _label_of(model, "loyaltyPoints", 499)}
    assert expected in model.exclusions
    assert model.exclusions == [expected]


def _mini_eval(op, value, operand, length=False):
    """테스트 자체 평가기(지원: < <= > >= == != eqlit null notnull). 판단 불가면 None."""
    if op == "null":
        return value is None
    if op == "notnull":
        return value is not None
    if value is None or value in ("<omit>", "<uniq>") or isinstance(value, tuple):
        return None
    if op == "eqlit":
        return value == operand
    if length:
        value = len(value)
    if isinstance(operand, str) != isinstance(value, str):
        return None
    return {"<": value < operand, "<=": value <= operand, ">": value > operand, ">=": value >= operand,
            "==": value == operand, "!=": value != operand}.get(op)


@pytest.mark.parametrize("which", ["kinds", "petclinic", "controlled"])
def test_req306_exclusions_justified(tmp_path, which):
    """각 배제 줄의 값 조합은 어떤 오류 논리곱의 모델 원자식을 모두 참으로 만든다(과잉 배제 0건)."""
    bundle = (_make_bundle(tmp_path / "k", _load_docs(KINDS)) if which == "kinds" else
              _make_bundle(tmp_path / "c", _load_docs(CONTROLLED)) if which == "controlled" else _real_bundle(tmp_path))
    deriver = _deriver(bundle)
    total = 0
    for ep in deriver.endpoints.values():
        model = pw.build_model(ep, deriver.cons, deriver.catalog, 2)
        by_param = {p["param"]: p for p in model.params}
        for exclusion in model.exclusions:
            values = {by_param[param]["field"]: _raw(next(c for c in by_param[param]["candidates"] if c.label == label))
                      for param, label in exclusion.items()}
            justified = False
            for _, cons in ep.error_disjuncts:
                atoms = [c for c in cons if not c.stored and c.field in values]
                if len(atoms) == len(values) and all(
                        _mini_eval(c.op, values[c.field], c.value, c.length) is True for c in atoms):
                    justified = True
            assert justified, (ep.label, exclusion, values)
            total += 1
    assert total >= 1


def test_req306_undetermined(tmp_path):
    """holds가 None인 조합(uniq ∧ credit<45)은 배제에 없다. 확정 조합(VIPKIT ∧ credit<45)만 배제된다."""
    deriver = _kinds(tmp_path)
    _, model = _model(deriver, MAKE)
    code, credit = _param(model, "code")["param"], _param(model, "credit")["param"]
    uniq = _label_of(model, "code", "<uniq>")
    vipkit = _label_of(model, "code", "VIPKIT")
    assert not any(e.get(code) == uniq for e in model.exclusions)
    pairs = sorted((e[code], e[credit]) for e in model.exclusions if code in e)
    assert pairs == sorted((vipkit, _label_of(model, "credit", raw)) for raw in (40, 39, 44))
    # 판단 불가 조합은 행 평가로 알 수 있다(Task 4가 assumes `undetermined:<addr>`로 싣는다)
    row = {p["param"]: "v0" for p in model.params}
    row[credit] = _label_of(model, "credit", 39)
    undetermined = pw.undetermined(model, row)
    assert len(undetermined) == 1 and undetermined[0].startswith("plan-tests-KitService.make.json#11@")
    row[code] = _label_of(model, "code", "PROMO")
    assert pw.undetermined(model, row) == []


# --- REQ-307 실행·분류 ------------------------------------------------------------------------------

def test_req307_field_count(tmp_path):
    deriver = _deriver(_real_bundle(tmp_path))
    _, put = _model(deriver, "PUT /api/reservations/{id}")
    assert put.skipped == "fields<2" and put.reason is None and put.exclusions == []
    _, listing = _model(deriver, "GET /api/reservations")
    assert listing.skipped == "fields<2"
    _, none = _model(deriver, "GET /api/vets")
    assert none.skipped == "fields<2" and none.params == []
    kinds = _kinds(tmp_path / "k")
    _, tags = _model(kinds, TAGS, order=3)  # 필드 2개 < order 3 → effectiveOrder 2
    assert tags.order == 3 and tags.effective_order == 2 and tags.skipped is None
    _, make = _model(kinds, MAKE, order=3)
    assert make.effective_order == 3


def test_req307_rc_and_output_contract(tmp_path):
    model = _two_param_model()
    work = tmp_path / "work"
    ok = "p0\tp1\nv0\tv0\nv1\tv1\n"
    tool, log = _fake_pict(tmp_path / "ok", stdout=ok)
    rows = pw.run_pict(model, tool, work, 10)
    assert rows == [{"p0": "v0", "p1": "v0"}, {"p0": "v1", "p1": "v1"}]
    record = json.loads(log.read_text())
    assert len(record["argv"]) == 2 and record["argv"][1] == "/o:2" and "/r" not in " ".join(record["argv"])
    assert Path(record["argv"][0]).parent.parent == work  # work/<임시>/model
    assert _work_leftovers(work) == []

    tool, _ = _fake_pict(tmp_path / "rc5", rc=5, stderr="Too restrictive constraints\n")
    assert pw.run_pict(model, tool, work, 10) == "pairwise-infeasible"

    bad_outputs = {"empty": "", "header-only": "p0\tp1\n", "truncated": "p0\tp1\nv0\n",
                   "unknown-label": "p0\tp1\nv0\tv9\n", "header-mismatch": "p0\tpX\nv0\tv0\n",
                   "duplicate-column": "p0\tp1\tp1\nv0\tv0\tv0\n", "missing-column": "p0\nv0\n"}
    for name, stdout in bad_outputs.items():
        tool, _ = _fake_pict(tmp_path / name, stdout=stdout)
        with pytest.raises(pw.PictFatal):
            pw.run_pict(model, tool, work, 10)
    secret_path = str(Path.home() / "secret" / "model.txt")
    tool, _ = _fake_pict(tmp_path / "rc1", rc=1, stderr=f"Input Error: {secret_path}\nsecond line\n")
    with pytest.raises(pw.PictFatal) as info:
        pw.run_pict(model, tool, work, 10)
    message = str(info.value)
    assert "rc=1" in message and "Input Error" in message and "second line" not in message
    assert str(Path.home()) not in message  # 가림 적용
    tool, _ = _fake_pict(tmp_path / "rc4", rc=4)
    with pytest.raises(pw.PictFatal, match="rc=4"):
        pw.run_pict(model, tool, work, 10)
    missing = pw.PictTool(tmp_path / "no-such-pict", "f" * 40, "0" * 64)
    with pytest.raises(pw.PictFatal):
        pw.run_pict(model, missing, work, 10)
    tool, _ = _fake_pict(tmp_path / "slow", stdout=ok, sleep=5)
    started = time.monotonic()
    with pytest.raises(pw.PictFatal, match="timed out"):
        pw.run_pict(model, tool, work, 0.5)
    assert time.monotonic() - started < 4
    assert _work_leftovers(work) == []


def test_req307_size_caps(tmp_path, monkeypatch):
    # 후보 > 12: 필드 값을 13개로 만드는 enum
    def many_constants(docs):
        docs["ext.json"]["enums"]["ex.kit.Grade"]["constants"] = [f"C{i:02d}" for i in range(13)]
    _, tags = _model(_kinds(tmp_path / "a", many_constants), TAGS)
    assert tags.reason == "pairwise-too-large" and tags.exclusions == []

    # 파라미터 > 24
    def many_fields(docs):
        dto = docs["ext.json"]["dtos"]["ex.kit.TagForm"]
        dto["fields"] = [{"name": f"g{i:02d}", "type": "ex.kit.Shade"} for i in range(25)]
    _, wide = _model(_kinds(tmp_path / "b", many_fields), TAGS)
    assert wide.reason == "pairwise-too-large" and len(wide.params) == 25

    # 배제 곱 상한: 열거 전에 곱(Σ Π 후보 수)으로 판정한다 → 열거 함수가 불리지 않는다
    calls = []
    original = pw._iter_exclusions
    monkeypatch.setattr(pw, "_iter_exclusions", lambda checks: calls.append(1) or original(checks))
    monkeypatch.setattr(pw, "MAX_EXCLUSIONS", 3)
    _, put = _model(_kinds(tmp_path / "c"), PATCH_PUT)  # width 3 × height 4 = 12 > 3
    assert put.reason == "pairwise-too-large" and calls == [] and put.exclusions == []
    monkeypatch.setattr(pw, "MAX_EXCLUSIONS", 20000)

    # 열거는 스트리밍이고 MAX_EXCLUSIONS+1에서 멈춘다
    produced = []

    def endless(checks):
        for i in itertools.count():
            produced.append(i)
            yield (("p0", f"v{i}"), ("p1", "v0"))
    monkeypatch.setattr(pw, "_iter_exclusions", endless)
    assert pw._collect_exclusions([]) is None
    assert len(produced) == pw.MAX_EXCLUSIONS + 1 == 20001
    assert (pw.MAX_CANDIDATES, pw.MAX_PARAMS, pw.MAX_EXCLUSIONS) == (12, 24, 20000)


def test_req307_neutral_model_and_cleanup(tmp_path):
    deriver = _deriver(_real_bundle(tmp_path))
    _, model = _model(deriver, CREATE)
    text = pw.render_model(model)
    import re
    tokens = set(re.findall(r"[A-Za-z_][\w@.]*", text)) - {"IF", "THEN", "AND"}
    assert tokens and all(re.fullmatch(r"[pv]\d+", t) for t in tokens), tokens
    for param in model.params:
        assert param["field"] not in text
    assert 'THEN [' in text and '<> "' in text
    assert "IF [" in text
    # 정상·rc≠0·예외 경로 모두 임시 디렉터리 잔존 0
    work = tmp_path / "work"
    for name, kwargs in (("ok", {"stdout": "p0\tp1\nv0\tv0\n"}), ("rc3", {"rc": 3}), ("bad", {"stdout": "x\n"})):
        tool, log = _fake_pict(tmp_path / name, **kwargs)
        try:
            pw.run_pict(_two_param_model(), tool, work, 10)
        except pw.PictFatal:
            pass
        model_text = json.loads(log.read_text())["model"]
        assert model_text.startswith("p0: v0, v1\np1: v0, v1, v2\n")
        assert 'IF [p0] = "v1" THEN [p1] <> "v2";' in model_text
        assert _work_leftovers(work) == []


def test_req307_render_three_atoms():
    def cands(n):
        return [pw.Candidate(f"v{i}", "literal", Value(i, "input")) for i in range(n)]
    params = [{"param": f"p{i}", "loc": "body", "field": f"f{i}", "candidates": cands(2)} for i in range(3)]
    model = pw.EndpointModel(params, {}, [], [{"p0": "v1", "p2": "v0", "p1": "v1"}], 2, 2, None, None)
    assert 'IF [p0] = "v1" AND [p1] = "v1" THEN [p2] <> "v0";' in pw.render_model(model)


def test_req307_real_pict(tmp_path, pict_tool):
    """실제 고정 PICT: petclinic 모델의 행은 배제 조합을 담지 않고 계약을 지킨다."""
    deriver = _deriver(_real_bundle(tmp_path))
    _, model = _model(deriver, CREATE)
    work = tmp_path / "work"
    rows = pw.run_pict(model, _tool(pict_tool), work, 120)
    assert rows and all(set(row) == {p["param"] for p in model.params} for row in rows)
    for exclusion in model.exclusions:
        assert not any(all(row[k] == v for k, v in exclusion.items()) for row in rows)
    assert _work_leftovers(work) == []
    # 실제 rc=5: 모든 조합을 막는 모델
    params = [{"param": "p0", "loc": "body", "field": "a", "candidates": [pw.Candidate("v0", "literal", Value(1, "input"))] * 1},
              {"param": "p1", "loc": "body", "field": "b", "candidates": [pw.Candidate("v0", "literal", Value(1, "input"))]}]
    blocked = pw.EndpointModel(params, {}, [], [{"p0": "v0", "p1": "v0"}], 2, 2, None, None)
    assert pw.run_pict(blocked, _tool(pict_tool), work, 120) == "pairwise-infeasible"
    assert _work_leftovers(work) == []


# --- REQ-311 결정성 ---------------------------------------------------------------------------------

def test_req311_pict_rows_deterministic(tmp_path, pict_tool):
    deriver = _deriver(_real_bundle(tmp_path))
    _, model = _model(deriver, CREATE)
    first = pw.run_pict(model, _tool(pict_tool), tmp_path / "w1", 120)
    second = pw.run_pict(model, _tool(pict_tool), tmp_path / "w2", 120)
    assert first == second
    again = _model(_deriver(_real_bundle(tmp_path / "again")), CREATE)[1]
    assert json.dumps(pw.model_json(again), sort_keys=True) == json.dumps(pw.model_json(model), sort_keys=True)


def test_pairwise_state_and_tool():
    disabled = pw.Pairwise.disabled()
    assert (disabled.mode, disabled.tool, disabled.reason) == ("disabled", None, None)
    unavailable = pw.Pairwise.unavailable("pict-not-prepared")
    assert (unavailable.mode, unavailable.reason) == ("unavailable", "pict-not-prepared")
    tool = pw.PictTool(Path("/x/pict"), "a" * 40, "b" * 64)
    available = pw.Pairwise.available(tool, Path("/w"), 120.0)
    assert (available.mode, available.tool, available.work_dir, available.timeout) == ("available", tool, Path("/w"), 120.0)
    with pytest.raises(Exception):
        tool.commit = "c"  # frozen


@pytest.mark.skipif(not os.environ.get("TD_PAIRWISE_TIMING"), reason="수동 계측(TD_PAIRWISE_TIMING=1)")
def test_near_cap_timing(tmp_path, pict_tool):
    """상한 근처 합성 모델(24 파라미터 × 12 후보, 배제 수천 줄)의 실제 PICT 소요 시간(보고서 기록용)."""
    def cands():
        return [pw.Candidate(f"v{i}", "literal", Value(i, "input")) for i in range(12)]
    params = [{"param": f"p{i}", "loc": "body", "field": f"f{i}", "candidates": cands()} for i in range(24)]
    exclusions = []
    for i in range(0, 24, 2):  # 인접 쌍마다 큰 값끼리 배제(12쌍 × 6 × 6 = 432) + 삼중 조합
        exclusions += [{f"p{i}": f"v{a}", f"p{i + 1}": f"v{b}"} for a in range(6, 12) for b in range(6, 12)]
    for i in range(0, 21, 3):
        exclusions += [{f"p{i}": f"v{a}", f"p{i + 1}": f"v{b}", f"p{i + 2}": f"v{c}"}
                       for a in range(0, 6) for b in range(0, 6) for c in range(0, 6)][:400]
    model = pw.EndpointModel(params, {}, [], exclusions, 2, 2, None, None)
    started = time.monotonic()
    rows = pw.run_pict(model, _tool(pict_tool), tmp_path / "w", 600)
    elapsed = time.monotonic() - started
    print(f"near-cap: exclusions={len(exclusions)} rows={len(rows) if isinstance(rows, list) else rows} seconds={elapsed:.2f}")
    assert isinstance(rows, list)
