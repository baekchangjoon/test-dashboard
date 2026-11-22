"""det pairwise 단위 테스트(Task 3: 후보 모델·배제·PICT 실행, REQ-305·306·307·311 / Task 4: derive 통합·`pairwise.json`,
REQ-304·308·309·310·311·315·316).

모델 수준 테스트는 `_Deriver`의 계획 해석 단계만 돌려 엔드포인트 제약을 채운 뒤 `build_model`을 부른다.
derive 통합 테스트는 `derive(bundle, pairwise=...)`와 `render`의 산출물(`cases.json`·`pairwise.json`)을 읽는다.
실제 PICT는 세션 fixture `pict_tool`(고정 커밋 빌드)을 쓰고, rc·출력 계약은 argv를 기록하는 가짜 pict로 주입한다.
"""
import itertools
import json
import os
import re
import stat
import time
from pathlib import Path

import pytest

from td import redact
from td.detgen import derive as derive_module
from td.detgen import pairwise as pw
from td.detgen import render as render_module
from td.detgen.constraints import OMIT, Spread, Uniq, Value
from test_unit_detgen import (CONTROLLED, FIXTURES, MUTATED, REPO_ROOT, _check_provenance, _load_docs,  # noqa: E402
                              _make_bundle, _real_bundle)

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
        assert _values(model, "credit") == [45, 40, 39, 44, 42, 41]
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
    assert pw.truth(eqlit, code[0]) is False  # uniq:<caseId>는 리터럴 VIPKIT과 같지 않다
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
    assert ("legacy", '"OLD"', "single-atom") in dropped  # #14 위반값 OLD는 #4 `legacy != null`을 참으로 만든다
    assert all(d["address"].startswith("plan-tests-KitService.make.json#") and not d["address"].endswith("~")
               for d in model.dropped)
    fixed = {name: entry["reason"] for name, entry in model.fixed.items()}
    assert fixed == {"body.phase": "state-field", "body.slot": "count-field", "body.deposit": "rel-dependent",
                     "body.shade": "stored-or-unresolved-only", "body.depth": "single-candidate",
                     "body.nick": "single-candidate"}
    assert model.fixed["body.deposit"]["candidate"].value.transform == "relation-satisfy"
    assert model.fixed["body.depth"]["candidate"].value.value == 4
    assert model.fixed["body.shade"]["candidate"].value.value == "LIGHT"  # baseline
    assert [p["field"] for p in model.params] == ["code", "credit", "grade", "legacy", "memo", "size"]
    assert [p["param"] for p in model.params] == ["p0", "p1", "p2", "p3", "p4", "p5"]


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
    else:  # 판단 불가 고정 원자식은 참으로 본다: 선행 baseline legacy는 생략 → `"Z".equals(existing.legacy)` 판단 불가
        def add(docs):
            items = next(p for p in docs["plans.json"] if p["method"] == "patch")["items"]
            items.append(dict(items[0], index=len(items),
                              condition='"Z".equals(existing.getLegacy()) && patch.width() > 6 && patch.height() > 5'))
        deriver = _kinds(tmp_path, add)
        ep, model = _model(deriver, PATCH_PUT)
        stored = next(c for _, cs in ep.error_disjuncts for c in cs if c.stored and c.op == "eqlit")
        assert pw.fixed_truth(deriver.cons, ep, stored, None) is None
        height, width = _param(model, "height")["param"], _param(model, "width")["param"]
        w7 = _label_of(model, "width", 7)
        assert model.exclusions == [{height: _label_of(model, "height", 7), width: w7},
                                    {height: _label_of(model, "height", 6), width: w7}]


def test_req306_uniq_literal_is_determinable(tmp_path):
    """선행 baseline이 uniq인 저장 필드의 `"X".equals(...)`는 거짓으로 판단 가능 → 논리곱을 버린다."""
    def add(docs):
        items = next(p for p in docs["plans.json"] if p["method"] == "patch")["items"]
        items.append(dict(items[0], index=len(items),
                          condition='"X".equals(existing.getCode()) && patch.width() > 6 && patch.height() > 5'))
    deriver = _kinds(tmp_path, add)
    ep, model = _model(deriver, PATCH_PUT)
    stored = next(c for _, cs in ep.error_disjuncts for c in cs if c.stored and c.op == "eqlit")
    assert pw.fixed_truth(deriver.cons, ep, stored, None) is False
    assert len(model.exclusions) == 1


def test_req306_zero_atoms_undetermined(tmp_path):
    """모델 원자식 0개로 줄었지만 고정 원자식이 판단 불가면 infeasible이 아니라 모든 행에 undetermined."""
    def add(docs):
        items = next(p for p in docs["plans.json"] if p["method"] == "patch")["items"]
        items.append(dict(items[0], index=len(items), condition='"Z".equals(existing.getLegacy())'))
    _, model = _model(_kinds(tmp_path, add), PATCH_PUT)
    assert model.reason is None and len(model.exclusions) == 1
    assert len(model.row_undetermined) == 1 and model.row_undetermined[0].startswith("plan-tests-KitService.patch.json#3@")
    row = {p["param"]: "v0" for p in model.params}
    assert pw.row_assumes_for(model, row) == [f"undetermined:{model.row_undetermined[0]}"]


def test_req306_probe_fixed_uniq_single_atom(tmp_path):
    """고정 uniq 필드(nick) + 단일 원자 `"BAD".equals(nick)`: uniq ≠ BAD로 판단 가능 → infeasible 아님(리뷰 probe)."""
    _, model = _model(_kinds(tmp_path), MAKE)
    nick = model.fixed["body.nick"]
    assert (nick["reason"], nick["candidate"].kind) == ("single-candidate", "uniq")
    assert model.reason is None and model.skipped is None and model.row_undetermined == []


def test_req306_exact_exclusions(tmp_path):
    """MAKE 배제 집합 전체(완전성): GOLD×39, VIPKIT×{40,39,44,42,41}, memo uniq×{40,39,41}(neqlit 위반 uniq, 리뷰 probe)."""
    _, model = _model(_kinds(tmp_path), MAKE)
    code, credit, grade, memo = (_param(model, f)["param"] for f in ("code", "credit", "grade", "memo"))

    def c(raw):
        return _label_of(model, "credit", raw)
    expected = [{credit: c(39), grade: _label_of(model, "grade", "GOLD")}]
    expected += [{code: _label_of(model, "code", "VIPKIT"), credit: c(raw)} for raw in (40, 39, 44, 42, 41)]
    expected += [{credit: c(raw), memo: _label_of(model, "memo", "<uniq>")} for raw in (40, 39, 41)]
    assert model.exclusions == expected


def test_req306_baseline_never_filtered(tmp_path):
    """baseline이 필터 조건을 참으로 만들어도 버리지 않고 `baseline-filter:<addr>`로 남긴다(dropped에는 없음)."""
    def add(docs):
        items = next(p for p in docs["plans.json"] if p["method"] == "make")["items"]
        items.append(dict(items[0], index=len(items),
                          condition="form.shade() != Shade.DARK && form.credit() > ledger.cap()"))
    _, model = _model(_kinds(tmp_path, add), MAKE)
    shade = model.fixed["body.shade"]["candidate"]
    assert shade.value.value == "DARK"  # baseline이 `!= DARK` 강제로 DARK가 되어 #10 `~`(shade == DARK)를 참으로 만든다
    assert not any(d["field"] == "shade" and d["candidate"].get("value") == "DARK" for d in model.dropped)
    hits = [e for e in model.row_assumes if e["field"] == "body.shade"]
    assert hits and all(e["assume"].startswith("baseline-filter:plan-tests-KitService.make.json#10@") for e in hits)
    row = {p["param"]: "v0" for p in model.params}
    assert hits[0]["assume"] in pw.row_assumes_for(model, row)


def test_req306_petclinic_vip_exclusion(tmp_path):
    deriver = _deriver(_real_bundle(tmp_path))
    _, model = _model(deriver, CREATE)
    tier, points = _param(model, "priceTier")["param"], _param(model, "loyaltyPoints")["param"]
    expected = {tier: _label_of(model, "priceTier", "VIP"), points: _label_of(model, "loyaltyPoints", 499)}
    assert expected in model.exclusions
    assert model.exclusions == [expected]


def _mini_eval(op, value, operand, length=False):
    """테스트 자체 평가기(지원: < <= > >= == != eqlit neqlit null notnull). 판단 불가면 None."""
    if op == "null":
        return value is None
    if op == "notnull":
        return value is not None and value != "<omit>"
    if value == "<uniq>" and op in ("eqlit", "neqlit") and not operand.startswith("uniq:"):
        return op == "neqlit"
    if op == "neqlit" and isinstance(value, str) and not value.startswith("<"):
        return value != operand
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
    """holds가 None인 조합(legacy 생략·null ∧ credit<42, `"OLD".equals`)은 배제에 없다."""
    deriver = _kinds(tmp_path)
    _, model = _model(deriver, MAKE)
    code, credit, legacy = (_param(model, f)["param"] for f in ("code", "credit", "legacy"))
    assert not any(legacy in e for e in model.exclusions)
    assert not any(e.get(code) == _label_of(model, "code", "<uniq>") for e in model.exclusions)
    # 판단 불가 조합은 행 평가로 알 수 있다(Task 4가 assumes `undetermined:<addr>`로 싣는다)
    row = {p["param"]: "v0" for p in model.params}
    row[credit] = _label_of(model, "credit", 39)
    undetermined = pw.undetermined(model, row)
    assert len(undetermined) == 1 and undetermined[0].startswith("plan-tests-KitService.make.json#14@")
    assert pw.row_assumes_for(model, row) == [f"undetermined:{undetermined[0]}"]
    row[credit] = _label_of(model, "credit", 45)
    assert pw.undetermined(model, row) == []


def test_req306_undetermined_cases(tmp_path, pict_tool):
    """Task 4 확장: 판단 불가 조합(credit<42 ∧ legacy 생략·null)을 담은 pairwise 케이스 assumes에 `undetermined:<#14>`가 붙는다."""
    _, cases_doc, pairwise_doc = _derive_render(_kinds_bundle(tmp_path), tmp_path, _available(tmp_path, pict_tool))
    make = [c for c in _pairwise_cases(cases_doc) if c["endpoint"] == MAKE]
    assert make
    tagged = 0
    for case in make:
        credit = case["values"]["body.credit"]["value"]
        legacy = case["values"].get("body.legacy", {"value": None})["value"]
        expected = credit < 42 and legacy is None
        marks = [a for a in case["assumes"] if a.startswith("undetermined:plan-tests-KitService.make.json#14@")]
        assert bool(marks) == expected, (case["id"], credit, legacy, case["assumes"])
        tagged += bool(marks)
    assert tagged >= 1
    assert pairwise_doc["endpoints"][MAKE]["rows"]


def test_truth_uniq_and_spread():
    uniq = pw.Candidate("v0", "uniq", Value(Uniq(), "generic-sentinel"))
    def con(**kw):
        return pw.Con(field="f", **kw)
    assert pw.truth(con(op=">", value=3, length=True), uniq) is False  # 길이는 baseline 형식
    assert pw.truth(con(op="fmt", value="EMAIL"), uniq) is False
    assert pw.truth(con(op="<", value=3), uniq) is None
    assert pw.truth(con(op="eqlit", value="BAD"), uniq) is False
    assert pw.truth(con(op="neqlit", value="BAD"), uniq) is True
    assert pw.truth(con(op="eqlit", value="uniq:x"), uniq) is None
    assert pw.truth(con(op="null"), uniq) is False and pw.truth(con(op="notnull"), uniq) is True
    for spread in (Spread(10, 20, (10, 20)), Spread(10, 20, (10, 11, 20)), Spread(5, 9, (5, 6, 7, 9))):
        rep = pw._representative(spread)
        assert spread.lo < rep < spread.hi and rep not in spread.excluded
    candidate = pw.Candidate("v0", "spread", Value(Spread(10, 20, (10, 20)), "derived"))
    assert pw.truth(con(op="<", value=11), candidate) is False and pw.truth(con(op="<", value=12), candidate) is True


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


@pytest.mark.parametrize("count, allowed", [(12, True), (13, False)])
def test_req307_candidate_cap_boundary(tmp_path, count, allowed):
    def constants(docs):
        docs["ext.json"]["enums"]["ex.kit.Grade"]["constants"] = [f"C{i:02d}" for i in range(count)]
    _, tags = _model(_kinds(tmp_path, constants), TAGS)
    assert len(_param(tags, "grade")["candidates"]) == count
    assert tags.reason == (None if allowed else "pairwise-too-large")


@pytest.mark.parametrize("count, allowed", [(24, True), (25, False)])
def test_req307_param_cap_boundary(tmp_path, count, allowed):
    def fields(docs):
        docs["ext.json"]["dtos"]["ex.kit.TagForm"]["fields"] = [{"name": f"g{i:02d}", "type": "ex.kit.Shade"} for i in range(count)]
    _, wide = _model(_kinds(tmp_path, fields), TAGS)
    assert len(wide.params) == count
    assert wide.reason == (None if allowed else "pairwise-too-large")


def test_req307_size_caps(tmp_path, monkeypatch):
    # 배제 곱 상한: 열거 전에 곱(Σ Π 후보 수)으로 판정한다 → 상한 초과면 열거 함수가 불리지 않는다
    calls = []
    original = pw._iter_exclusions
    monkeypatch.setattr(pw, "_iter_exclusions", lambda checks: calls.append(1) or original(checks))
    monkeypatch.setattr(pw, "MAX_EXCLUSIONS", 12)  # PUT: width 3 × height 4 = 12 → 정확히 상한이면 허용
    _, put = _model(_kinds(tmp_path / "c"), PATCH_PUT)
    assert put.reason is None and len(put.exclusions) == 1 and calls == [1]
    monkeypatch.setattr(pw, "MAX_EXCLUSIONS", 11)
    calls.clear()
    _, put = _model(_kinds(tmp_path / "d"), PATCH_PUT)
    assert put.reason == "pairwise-too-large" and calls == [] and put.exclusions == []
    monkeypatch.setattr(pw, "MAX_EXCLUSIONS", 20000)
    monkeypatch.setattr(pw, "_iter_exclusions", original)

    # 실제 상한 20,000: 곱 정확히 20,000은 모두 모이고 20,001은 거절된다
    def checks(n):
        return [("a", [("p0", {f"v{i}": True for i in range(n)}), ("p1", {"v0": True, "v1": True})])]
    assert pw._bound(checks(10000)) == 20000 and len(pw._collect_exclusions(checks(10000))) == 20000
    odd = [("a", [("p0", {f"v{i}": True for i in range(20001)}), ("p1", {"v0": True})])]
    assert pw._bound(odd) == 20001 and pw._collect_exclusions(odd) is None

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


BOUNDARY_COUNTS = {20000: [5, 5, 6, 6, 7, 8, 8, 9, 9, 9, 10, 10, 10, 10, 11, 11, 11, 12, 12, 12, 12, 12],
                   20001: [2, 2, 3, 3, 5, 5, 7, 8, 8, 8, 9, 10, 10, 10, 11, 11, 11, 11, 11, 12, 12, 12, 12, 12]}


def _wide_tags(counts):
    """TAGS 본문을 enum 필드(필드 i의 상수 counts[i]개)로 바꾼다. 오류 조건이 없어 후보 = 상수 전부."""
    def mutate(docs):
        enums = docs["ext.json"]["enums"]
        fields = []
        for index, count in enumerate(counts):
            enums[f"ex.kit.W{index:02d}"] = {"constants": [f"K{index:02d}x{j:02d}" for j in range(count)]}
            fields.append({"name": f"w{index:02d}", "type": f"ex.kit.W{index:02d}"})
        docs["ext.json"]["dtos"]["ex.kit.TagForm"]["fields"] = fields
    return mutate


@pytest.mark.parametrize("tuples, allowed", [(20000, True), (20001, False)])
def test_req307_interaction_cap_boundary(tmp_path, tuples, allowed):
    counts = BOUNDARY_COUNTS[tuples]
    assert pw.interaction_bound(counts, 2) == tuples and pw.MAX_INTERACTIONS == 20000
    _, wide = _model(_kinds(tmp_path, _wide_tags(counts)), TAGS)
    assert [len(p["candidates"]) for p in wide.params] == counts
    assert wide.reason == (None if allowed else "pairwise-too-large")


def test_req307_interaction_bound_saturates():
    assert pw.interaction_bound([3, 2], 2) == 6 and pw.interaction_bound([3, 2, 4], 3) == 24
    assert pw.interaction_bound([2, 2, 2], 2) == 12 and pw.interaction_bound([5], 2) == 0
    assert pw.interaction_bound([12] * 24, 2) == pw.MAX_INTERACTIONS + 1  # 39,744 → 포화
    assert pw.interaction_bound([12] * 24, 3) == pw.MAX_INTERACTIONS + 1


@pytest.mark.parametrize("order", [2, 3])
def test_req307_near_cap_is_too_large_fast(tmp_path, order):
    """24 파라미터 × 12 후보 모델은 상호작용 상한으로 PICT·통계 계산 전에 too-large가 된다(존재하지 않는 pict로 미호출 확인)."""
    def mutate(docs):
        _wide_tags([12] * 24)(docs)
        docs["harness.json"]["pairwiseOrder"] = order
    bundle = _kinds_bundle(tmp_path, mutate)
    missing = pw.Pairwise.available(pw.PictTool(tmp_path / "no-such-pict", "f" * 40, "0" * 64), tmp_path / "w", 120)
    started = time.monotonic()
    with pytest.raises(pw.PictFatal):  # 다른 엔드포인트(MAKE 등)는 PICT를 부르므로 시작 실패가 난다
        derive_module.derive(bundle, pairwise=missing)
    _, tags = _model(_kinds(tmp_path / "m", mutate), TAGS, order=order)
    assert tags.reason == "pairwise-too-large" and tags.exclusions == []
    assert time.monotonic() - started < 10


def test_req307_near_cap_slot(tmp_path, pict_tool):
    def mutate(docs):
        _wide_tags([12] * 24)(docs)
    started = time.monotonic()
    _, doc, pairwise_doc = _derive_render(_kinds_bundle(tmp_path, mutate), tmp_path, _available(tmp_path, pict_tool))
    assert time.monotonic() - started < 30
    assert [e for e in doc["unresolved"] if e["endpoint"] == TAGS and e["rule"] == "pairwise"] == [
        {"source": f"graph:endpoint:{TAGS}", "reason": "pairwise-too-large", "endpoint": TAGS, "rule": "pairwise"}]
    assert pairwise_doc["endpoints"][TAGS]["rows"] == [] and TAGS not in doc["universe"]["pairwise"]["byEndpoint"]


def test_distinct_fields_asserted():
    with pytest.raises(AssertionError):
        list(pw._iter_exclusions([("a", [("p0", {"v0": True}), ("p0", {"v1": True})])]))


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


# --- Task 4: derive 통합·pairwise.json (REQ-304·308·309·310·311·315·316) ------------------------------

SNAPSHOT = REPO_ROOT / "e2e" / "generated" / "petclinic" / "det" / "det-da70932c-r1"
NEW_REASONS = ("pairwise-unavailable", "pairwise-too-large", "pairwise-infeasible", "pairwise-row-invalid")
PAIRWISE_FILE = "pairwise.json"


def _available(tmp_path, pict_tool, name="pict-work") -> pw.Pairwise:
    return pw.Pairwise.available(_tool(pict_tool), tmp_path / name, 120)


def _kinds_bundle(tmp_path, mutate=None, name="kinds-b"):
    docs = _load_docs(KINDS)
    if mutate is not None:
        mutate(docs)
    return _make_bundle(tmp_path / name, docs)


def _bundle_of(which, tmp_path):
    if which == "petclinic":
        return _real_bundle(tmp_path / "pc")
    if which == "kinds":
        return _kinds_bundle(tmp_path)
    return _make_bundle(tmp_path / which, _load_docs(CONTROLLED if which == "controlled" else MUTATED))


def _derive_render(bundle, tmp_path, pairwise=None, name="out"):
    """derive → render. (Derivation, cases.json 문서, pairwise.json 문서|None)."""
    derivation = derive_module.derive(bundle) if pairwise is None else derive_module.derive(bundle, pairwise=pairwise)
    out = tmp_path / name
    written = render_module.render(derivation, out)
    cases_doc = json.loads((out / "cases.json").read_text(encoding="utf-8"))
    pairwise_doc = json.loads((out / PAIRWISE_FILE).read_text(encoding="utf-8")) if (out / PAIRWISE_FILE).exists() else None
    assert (PAIRWISE_FILE in written) == (pairwise_doc is not None)
    return derivation, cases_doc, pairwise_doc


def _pairwise_cases(cases_doc):
    return [c for c in cases_doc["cases"] if c["rule"] == "pairwise"]


def _schema_check(pairwise_doc):
    import jsonschema
    schema = json.loads((REPO_ROOT / "site-gen" / "td" / "schemas" / "pairwise.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(pairwise_doc, schema)


def test_req304_disabled_identical(tmp_path):
    """disabled(기본값) derive의 cases.json·features·glue는 커밋된 기준 스냅샷과 바이트 동일, pairwise.json 없음."""
    derivation = derive_module.derive(_real_bundle(tmp_path))
    out = tmp_path / "out"
    written = render_module.render(derivation, out)
    assert PAIRWISE_FILE not in written and not (out / PAIRWISE_FILE).exists()
    expected = sorted(p.relative_to(SNAPSHOT).as_posix() for p in SNAPSHOT.rglob("*") if p.is_file() and p.name != "_COMPLETE")
    assert written == expected
    for relative in written:
        assert (out / relative).read_bytes() == (SNAPSHOT / relative).read_bytes(), relative
    assert "pairwise" not in derivation.universe and derivation.pairwise_doc is None
    assert not set(NEW_REASONS) & set(derivation.universe["bySlot"]["byReason"])


def _without_pairwise(doc):
    cases = [c for c in doc["cases"] if c["rule"] != "pairwise"]
    unresolved = [e for e in doc["unresolved"] if e["rule"] != "pairwise"]
    return cases, unresolved


@pytest.mark.parametrize("which", ["petclinic", "kinds"])
def test_req304_existing_cases_kept(tmp_path, pict_tool, which):
    """available·unavailable에서도 규칙 ≠ pairwise 항목은 disabled와 같다(병합으로 늘어난 sources만 예외)."""
    bundle = _bundle_of(which, tmp_path)
    _, base, _ = _derive_render(bundle, tmp_path, None, "disabled")
    base_cases, base_unresolved = _without_pairwise(base)
    assert len(base_cases) == len(base["cases"]) and len(base_unresolved) == len(base["unresolved"])
    for mode in ("available", "unavailable"):
        state = _available(tmp_path, pict_tool) if mode == "available" else pw.Pairwise.unavailable("pict-not-prepared")
        _, doc, _ = _derive_render(bundle, tmp_path, state, mode)
        cases, unresolved = _without_pairwise(doc)
        assert unresolved == base_unresolved, mode
        assert [c["id"] for c in cases] == [c["id"] for c in base_cases], mode
        for got, want in zip(cases, base_cases):
            assert got["sources"][:len(want["sources"])] == want["sources"], (mode, got["id"])
            assert dict(got, sources=None) == dict(want, sources=None), (mode, got["id"])
            assert got.get("pair") == want.get("pair")
        universe, base_universe = doc["universe"], base["universe"]
        assert set(universe) == set(base_universe) | {"pairwise"}
        assert universe["theoretical"] == base_universe["theoretical"]
        assert {k: v for k, v in universe["byRule"].items() if k != "pairwise"} == base_universe["byRule"]
        by_reason = universe["bySlot"]["byReason"]
        assert set(by_reason) == set(base_universe["bySlot"]["byReason"]) | set(NEW_REASONS)  # 새 키 정확히 4개
        assert len(by_reason) == len(base_universe["bySlot"]["byReason"]) + 4
        assert {k: by_reason[k] for k in base_universe["bySlot"]["byReason"]} == base_universe["bySlot"]["byReason"]
        if mode == "unavailable":
            assert "pairwise" not in universe["byRule"] and universe["bySlot"]["generated"] == base_universe["bySlot"]["generated"]


def test_req308_case_shape(tmp_path, pict_tool):
    bundle = _kinds_bundle(tmp_path)
    _, cases_doc, pairwise_doc = _derive_render(bundle, tmp_path, _available(tmp_path, pict_tool))
    _schema_check(pairwise_doc)
    cases = _pairwise_cases(cases_doc)
    assert cases
    _check_provenance(bundle, derive_module.derive(bundle, pairwise=_available(tmp_path, pict_tool, "w2")), tmp_path / "out")
    by_id = {c["id"]: c for c in cases_doc["cases"]}
    transforms = 0
    for case in cases:
        assert case["expect"] == {"strict": "2xx", "class": "2xx", "source": "rule"} and case["oracle"] == "status"
        assert case["auth"] == "authed"
        assert all(s.startswith("graph:") or re.match(r"^[^#]+#[0-9.]+@[0-9a-f]{12}$", s) for s in case["sources"])
        assert not any(s.startswith("pict:") for s in case["sources"])
        endpoint = pairwise_doc["endpoints"][case["endpoint"]]
        assert set(case["pairwise"]) == {"order", "labels"} and case["pairwise"]["order"] == endpoint["effectiveOrder"]
        assert set(case["pairwise"]["labels"]) == {p["param"] for p in endpoint["params"]}
        assert [r for r in endpoint["rows"] if r["caseId"] == case["id"]][0]["labels"] == case["pairwise"]["labels"]
        for param in endpoint["params"]:
            candidate = next(c for c in param["candidates"] if c["label"] == case["pairwise"]["labels"][param["param"]])
            key = f"{param['loc']}.{param['field']}"
            if candidate["kind"] == "omit":
                assert key not in case["values"]
                continue
            entry = case["values"][key]
            assert entry["provenance"] == candidate["provenance"], (case["id"], key)
            assert entry.get("from") == candidate["source"] and entry.get("transform") == candidate["transform"], (case["id"], key)
            transforms += candidate["transform"] is not None
            if candidate["kind"] in ("literal", "null"):
                assert entry["value"] == candidate["value"]
            elif candidate["kind"] == "uniq":
                assert entry["value"] == f"uniq:{case['id']}"
    assert transforms >= 1  # 후보 transform 보존(예: credit 40-1)
    assert all("pairwise" not in c for c in cases_doc["cases"] if c["rule"] != "pairwise")
    for row in (r for e in pairwise_doc["endpoints"].values() for r in e["rows"]):
        assert not (row["caseId"] and row["mergedInto"])  # 케이스이거나, 병합됐거나, (row-invalid면) 둘 다 없다
        for ref in (row["caseId"], row["mergedInto"]):
            assert ref is None or ref in by_id


def _assert_slot_identity(doc, base_doc, pairwise_doc):
    """행 = 케이스 + 병합(dedupe 흡수·라벨 기준 모두-baseline) + row-invalid. 병합 행은 bySlot.deduplicated 증가분과 같다."""
    rows = [r for e in pairwise_doc["endpoints"].values() for r in e["rows"]]
    cases = sum(1 for r in rows if r["caseId"])
    merged = sum(1 for r in rows if r["mergedInto"])
    invalid = sum(1 for r in rows if not r["caseId"] and not r["mergedInto"])
    assert len(rows) == cases + merged + invalid
    assert cases == len(_pairwise_cases(doc))
    assert invalid == doc["universe"]["bySlot"]["byReason"]["pairwise-row-invalid"]
    assert doc["universe"]["bySlot"]["deduplicated"] == base_doc["universe"]["bySlot"]["deduplicated"] + merged
    by_endpoint = doc["universe"]["pairwise"]["byEndpoint"]
    for label, entry in pairwise_doc["endpoints"].items():
        if label in by_endpoint:
            assert by_endpoint[label]["rows"] == len(entry["rows"])
            assert by_endpoint[label]["cases"] == sum(1 for r in entry["rows"] if r["caseId"])
    return merged


def test_req308_order_and_merge(tmp_path, pict_tool, monkeypatch):
    _, base_kinds, _ = _derive_render(_kinds_bundle(tmp_path), tmp_path, None, "kinds-disabled")
    # (a) 정렬: pairwise 케이스는 기존 케이스 뒤
    _, doc, pairwise_doc = _derive_render(_kinds_bundle(tmp_path), tmp_path, _available(tmp_path, pict_tool))
    rules = [c["rule"] for c in doc["cases"]]
    first = rules.index("pairwise")
    assert all(r == "pairwise" for r in rules[first:]) and "pairwise" not in rules[:first]
    # (b) enum 전용 엔드포인트: 모두-baseline 행은 baseline-valid·happy가 없어 pairwise 케이스로 남고,
    #     enum-value와 같은 요청인 행은 dedupe로 흡수되어 mergedInto = 남은 enum-value 케이스
    tags = pairwise_doc["endpoints"][TAGS]
    by_id = {c["id"]: c for c in doc["cases"]}
    assert tags["skipped"] is None and tags["reason"] is None and len(tags["rows"]) == 6
    baseline_rows = [r for r in tags["rows"] if set(r["labels"].values()) == {"v0"}]
    assert len(baseline_rows) == 1 and baseline_rows[0]["mergedInto"] is None
    assert by_id[baseline_rows[0]["caseId"]]["rule"] == "pairwise"
    for row in tags["rows"]:
        changed = sum(label != "v0" for label in row["labels"].values())
        if changed == 1:
            assert row["caseId"] is None and by_id[row["mergedInto"]]["rule"] == "enum-value", row
        elif changed == 2:
            assert row["mergedInto"] is None and by_id[row["caseId"]]["rule"] == "pairwise", row
    assert _assert_slot_identity(doc, base_kinds, pairwise_doc) >= 3  # TAGS enum-value 흡수 3 (+ 다른 엔드포인트)
    # (c) 라벨 기준 모두-baseline(uniq 값이 있어 값 서명으로는 병합되지 않는 MAKE) → baseline-valid id
    real_run = pw.run_pict

    def with_baseline_row(model, tool, work_dir, timeout):
        rows = real_run(model, tool, work_dir, timeout)
        if any(p["field"] == "credit" for p in model.params) and isinstance(rows, list):
            rows = [{p["param"]: "v0" for p in model.params}] + rows
        return rows
    monkeypatch.setattr(pw, "run_pict", with_baseline_row)
    _, doc2, pairwise_doc2 = _derive_render(_kinds_bundle(tmp_path), tmp_path, _available(tmp_path, pict_tool), "merged")
    make_rows = pairwise_doc2["endpoints"][MAKE]["rows"]
    baseline_valid = [c["id"] for c in doc2["cases"] if c["endpoint"] == MAKE and c["rule"] == "baseline-valid"]
    assert len(baseline_valid) == 1
    assert make_rows[0] == {"labels": make_rows[0]["labels"], "caseId": None, "mergedInto": baseline_valid[0]}
    assert not any(set(c["pairwise"]["labels"].values()) == {"v0"} for c in _pairwise_cases(doc2) if c["endpoint"] == MAKE)
    # baseline-valid 케이스 자체는 그대로(출처도 늘지 않는다)
    assert next(c for c in doc2["cases"] if c["id"] == baseline_valid[0]) == next(c for c in doc["cases"] if c["id"] == baseline_valid[0])
    _assert_slot_identity(doc2, base_kinds, pairwise_doc2)  # 라벨 기준 병합 행도 deduplicated에 들어간다
    monkeypatch.setattr(pw, "run_pict", real_run)
    # (d) _materialize가 거부한 행은 종류와 무관하게 pairwise-row-invalid(배제를 지운 모델 → VIP×499 행이 오류 조건 위반)
    real_build = pw.build_model

    def without_exclusions(ep, cons, catalog, order):
        model = real_build(ep, cons, catalog, order)
        model.exclusions, model.checks = [], []
        return model
    monkeypatch.setattr(pw, "build_model", without_exclusions)
    derivation, doc3, pairwise_doc3 = _derive_render(_real_bundle(tmp_path / "r"), tmp_path, _available(tmp_path, pict_tool), "invalid")
    invalid = [e for e in doc3["unresolved"] if e["rule"] == "pairwise"]
    assert invalid and all(e == {"source": invalid[0]["source"], "reason": "pairwise-row-invalid", "endpoint": CREATE,
                                 "rule": "pairwise"} for e in invalid)
    assert doc3["universe"]["bySlot"]["byReason"]["pairwise-row-invalid"] == len(invalid)
    rows = pairwise_doc3["endpoints"][CREATE]["rows"]
    assert sum(1 for r in rows if r["caseId"] is None and r["mergedInto"] is None) == len(invalid)
    _, base_real, _ = _derive_render(_real_bundle(tmp_path / "r0"), tmp_path, None, "real-disabled")
    _assert_slot_identity(doc3, base_real, pairwise_doc3)
    # row-invalid로 빠진 행의 튜플(VIP×499)은 커버되지 않는다: covered < feasible, universe 값 = 테스트 자체 오라클
    oracle = _oracle(doc3, pairwise_doc3)[CREATE]
    stats = doc3["universe"]["pairwise"]["byEndpoint"][CREATE]
    assert (stats["interactionsFeasible"], stats["interactionsCovered"]) == (oracle["feasible"], oracle["covered"])
    assert oracle["covered"] < oracle["feasible"]


def test_req308_rel_combined(tmp_path, pict_tool):
    bundle = _real_bundle(tmp_path)
    deriver = _deriver(bundle)
    ep = next(e for e in deriver.endpoints.values() if e.label == CREATE)
    addr, rel = next((a, c) for a, cs in ep.error_disjuncts for c in cs if c.op == "rel")
    _, doc, pairwise_doc = _derive_render(bundle, tmp_path, _available(tmp_path, pict_tool))
    params = {p["field"]: p["param"] for p in pairwise_doc["endpoints"][CREATE]["params"]}
    combined = plain = 0
    for case in (c for c in _pairwise_cases(doc) if c["endpoint"] == CREATE):
        labels = case["pairwise"]["labels"]
        non_baseline = any(labels[params[name]] != "v0" for name in rel.others if name in params)
        assert (f"rel-combined:{addr}" in case["assumes"]) == non_baseline, case["id"]
        assert rel.assumes[1] in case["assumes"]  # 종속 필드의 기존 가정
        combined += non_baseline
        plain += not non_baseline
    assert combined >= 1


@pytest.mark.parametrize("which", ["controlled", "mutated", "petclinic", "kinds"])
def test_req308_no_row_invalid(tmp_path, pict_tool, which):
    _, doc, pairwise_doc = _derive_render(_bundle_of(which, tmp_path), tmp_path, _available(tmp_path, pict_tool))
    assert not [e for e in doc["unresolved"] if e["reason"] == "pairwise-row-invalid"]
    assert doc["universe"]["bySlot"]["byReason"]["pairwise-row-invalid"] == 0
    assert _pairwise_cases(doc)
    assert all(r["caseId"] or r["mergedInto"] for e in pairwise_doc["endpoints"].values() for r in e["rows"])
    _schema_check(pairwise_doc)


def test_req308_reasons(tmp_path, pict_tool, monkeypatch):
    assert derive_module.REASONS[-4:] == NEW_REASONS and derive_module._REASON_PRIORITY[-4:] == NEW_REASONS
    assert derive_module._VALID_RULES[-1] == "pairwise"
    bundle = _kinds_bundle(tmp_path)
    # unavailable: 슬롯 1건, 새 키 4개, universe.pairwise 빈 byEndpoint, pairwise.json 빈 endpoints
    _, doc, pairwise_doc = _derive_render(bundle, tmp_path, pw.Pairwise.unavailable("pict-not-prepared"), "unavail")
    assert [e for e in doc["unresolved"] if e["rule"] == "pairwise"] == [
        {"source": "tool:pict", "reason": "pairwise-unavailable", "endpoint": None, "rule": "pairwise"}]
    by_reason = doc["universe"]["bySlot"]["byReason"]
    assert {k: by_reason[k] for k in NEW_REASONS} == {"pairwise-unavailable": 1, "pairwise-too-large": 0,
                                                      "pairwise-infeasible": 0, "pairwise-row-invalid": 0}
    assert doc["universe"]["pairwise"] == {"order": 2, "byEndpoint": {}}
    assert pairwise_doc == {"schema": 1, "order": 2, "endpoints": {}}
    _schema_check(pairwise_doc)
    assert not _pairwise_cases(doc)
    # available: 모델로 정해지는 infeasible(TRIM) 1건
    _, doc, pairwise_doc = _derive_render(bundle, tmp_path, _available(tmp_path, pict_tool), "avail")
    slots = [e for e in doc["unresolved"] if e["rule"] == "pairwise"]
    assert slots == [{"source": slots[0]["source"], "reason": "pairwise-infeasible", "endpoint": TRIM, "rule": "pairwise"}]
    assert slots[0]["source"].startswith("graph:")
    assert {k: doc["universe"]["bySlot"]["byReason"][k] for k in NEW_REASONS} == {
        "pairwise-unavailable": 0, "pairwise-too-large": 0, "pairwise-infeasible": 1, "pairwise-row-invalid": 0}
    assert pairwise_doc["endpoints"][TRIM]["reason"] == "pairwise-infeasible" and pairwise_doc["endpoints"][TRIM]["rows"] == []
    assert doc["universe"]["byRule"]["pairwise"] == len(_pairwise_cases(doc))
    # 크기 상한 초과 → 엔드포인트마다 too-large 슬롯(PICT 미호출)
    monkeypatch.setattr(pw, "MAX_CANDIDATES", 2)
    _, doc, pairwise_doc = _derive_render(bundle, tmp_path, _available(tmp_path, pict_tool), "large")
    large = sorted(e["endpoint"] for e in doc["unresolved"] if e["reason"] == "pairwise-too-large")
    assert large == sorted([MAKE, PATCH_PUT, TAGS]) and all(e["rule"] == "pairwise" for e in doc["unresolved"] if e["reason"] == "pairwise-too-large")
    assert pairwise_doc["endpoints"][MAKE]["reason"] == "pairwise-too-large"
    assert MAKE not in doc["universe"]["pairwise"]["byEndpoint"]


# 독립 오라클(td.detgen.pairwise를 쓰지 않는다): pairwise.json의 params·candidates·exclusions만 읽는다

def _feasible_tuples(endpoint, order):
    """order는 문서 최상위 order. 유효 order는 문서 effectiveOrder를 믿지 않고 min(order, 파라미터 수)로 따로 계산한다."""
    params = [p["param"] for p in endpoint["params"]]
    order = min(order, len(params))
    labels = [[c["label"] for c in p["candidates"]] for p in endpoint["params"]]
    exclusions = [tuple(sorted(e.items())) for e in endpoint["exclusions"]]
    feasible = set()
    for combo in itertools.product(*labels):
        row = dict(zip(params, combo))
        if any(all(row[k] == v for k, v in exclusion) for exclusion in exclusions):
            continue
        for names in itertools.combinations(params, order):
            feasible.add(tuple((name, row[name]) for name in names))
    return feasible


def _matches(candidate, key, values) -> bool:
    kind = candidate["kind"]
    if kind == "omit":
        return key not in values
    if key not in values:
        return False
    value = values[key]["value"]
    if kind == "null":
        return value is None
    if kind == "uniq":
        return isinstance(value, str) and value.startswith("uniq:")
    if kind == "spread":
        rng = candidate["range"]
        return isinstance(value, int) and rng["lo"] <= value <= rng["hi"] and value not in rng["excluded"]
    expected = candidate["value"]
    return value is not None and isinstance(value, bool) == isinstance(expected, bool) and \
        isinstance(value, str) == isinstance(expected, str) and value == expected


def _oracle(cases_doc, pairwise_doc) -> dict:
    """엔드포인트별 {feasible, covered, uncovered}: 실현 가능 튜플 중 행 케이스(caseId·mergedInto)의 cases.json 값에 나타난 것."""
    by_id = {c["id"]: c for c in cases_doc["cases"]}
    out = {}
    for label, endpoint in sorted(pairwise_doc["endpoints"].items()):
        if endpoint["skipped"] or endpoint["reason"]:
            continue
        feasible = _feasible_tuples(endpoint, pairwise_doc["order"])
        by_param = {p["param"]: p for p in endpoint["params"]}
        row_cases = [by_id[r["caseId"] or r["mergedInto"]] for r in endpoint["rows"] if r["caseId"] or r["mergedInto"]]

        def hit(case, combo):
            return all(_matches(next(c for c in by_param[param]["candidates"] if c["label"] == lab),
                                f"{by_param[param]['loc']}.{by_param[param]['field']}", case["values"])
                       for param, lab in combo)
        uncovered = sorted(combo for combo in feasible if not any(hit(case, combo) for case in row_cases))
        out[label] = {"feasible": len(feasible), "covered": len(feasible) - len(uncovered), "uncovered": uncovered}
    return out


def test_req309_feasible_interactions(tmp_path, pict_tool):
    _, doc, pairwise_doc = _derive_render(_real_bundle(tmp_path), tmp_path, _available(tmp_path, pict_tool))
    universe = doc["universe"]["pairwise"]
    assert universe["order"] == pairwise_doc["order"] == 2
    totals = {"feasible": 0, "covered": 0}
    checked = []
    oracle = _oracle(doc, pairwise_doc)
    for label, endpoint in sorted(pairwise_doc["endpoints"].items()):
        if endpoint["skipped"] or endpoint["reason"]:
            assert label not in universe["byEndpoint"] and label not in oracle
            continue
        checked.append(label)
        feasible = oracle[label]["feasible"]
        assert oracle[label]["uncovered"] == [], (label, oracle[label]["uncovered"][:5])
        stats = universe["byEndpoint"][label]
        assert stats["interactionsFeasible"] == feasible == stats["interactionsCovered"], label
        assert stats["params"] == len(endpoint["params"])
        assert stats["candidates"] == sum(len(p["candidates"]) for p in endpoint["params"])
        assert stats["rows"] == len(endpoint["rows"]) and stats["cases"] == sum(1 for r in endpoint["rows"] if r["caseId"])
        assert stats["interactionsTotal"] >= stats["interactionsFeasible"]
        totals["feasible"] += feasible
        totals["covered"] += stats["interactionsCovered"]
    assert CREATE in checked and universe["byEndpoint"][CREATE]["interactionsFeasible"] > 0
    assert set(universe["byEndpoint"]) == set(checked)
    assert totals["feasible"] == totals["covered"] == sum(s["interactionsCovered"] for s in universe["byEndpoint"].values())


# 독립 평가기(지원 연산자: < <= > >= == != == null != null && ||, 피연산자: 요청 필드 접근자·정수·enum 상수·ext.json 상수)

_ACCESSOR = re.compile(r"^\w+\.(\w+)\(\)$")
_ATOM = re.compile(r"^(.+?)\s*(<=|>=|==|!=|<|>)\s*(.+)$")


def _operand(text, values, constants):
    text = text.strip()
    match = _ACCESSOR.match(text)
    if match:
        key = f"body.{match.group(1)}" if f"body.{match.group(1)}" in values else f"query.{match.group(1)}"
        return ("field", values[key]["value"] if key in values else None)
    if re.fullmatch(r"-?\d+", text):
        return ("int", int(text))
    if text == "null":
        return ("null", None)
    if re.fullmatch(r"[A-Z]\w*\.[A-Z][A-Z0-9_]*", text):
        return ("enum", text.split(".")[1])
    if text in constants:
        return ("int", constants[text])
    raise ValueError(text)


def _eval_atom(atom, values, constants):
    match = _ATOM.match(atom.strip())
    if not match or "(" in match.group(3) and not _ACCESSOR.match(match.group(3).strip()):
        raise ValueError(atom)
    (lk, left), op, (rk, right) = _operand(match.group(1), values, constants), match.group(2), _operand(match.group(3), values, constants)
    if rk == "null":
        if op not in ("==", "!="):
            raise ValueError(atom)
        return (left is None) == (op == "==")
    if left is None or right is None:
        raise ValueError(atom)  # null 비교(자바 NPE)는 평가하지 않는다
    if rk == "enum" or isinstance(left, str) or isinstance(right, str):
        if op not in ("==", "!="):
            raise ValueError(atom)
        return (left == right) == (op == "==")
    if isinstance(left, bool) or isinstance(right, bool):
        raise ValueError(atom)
    return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right,
            "==": left == right, "!=": left != right}[op]


def test_req310_no_error_condition(tmp_path, pict_tool):
    bundle = _real_bundle(tmp_path)
    _, doc, _ = _derive_render(bundle, tmp_path, _available(tmp_path, pict_tool))
    ext = bundle.read("ext.json")
    constants = {c["name"]: c["value"] for c in ext["constants"] if isinstance(c.get("value"), int)}
    endpoint_of = {(c["service"], c["method"]): c["endpoint"].split(":", 1)[1] for c in ext["calls"]}
    evaluated, unevaluated, checks, conditions = set(), set(), 0, set()
    cases = _pairwise_cases(doc)
    assert cases
    for plan in bundle.read("plans.json"):
        label = next((ep for (svc, method), ep in endpoint_of.items() if method == plan["method"] and svc.endswith("." + plan["class"])), None)
        targets = [c for c in cases if c["endpoint"] == label]
        for item in plan["items"]:
            if not re.fullmatch(r"[45]\d\d", item["branch_value"]):
                continue  # 기대가 예외인 항목만
            condition = " ".join(item["condition"].split())
            conditions.add(condition)
            disjuncts = [[a for a in d.split("&&")] for d in condition.split("||")]
            for case in targets:
                for atoms in disjuncts:
                    try:
                        result = all([_eval_atom(a, case["values"], constants) for a in atoms])
                    except (ValueError, KeyError):
                        unevaluated.add(condition)
                        continue
                    checks += 1
                    evaluated.add(condition)
                    assert result is False, (case["id"], condition)
    assert checks >= 1 and len(evaluated) >= 1
    assert any("VIP" in c and "loyaltyPoints" in c for c in evaluated)
    # 평가하지 못한 조건(원자식 일부가 지원 밖: 형식·날짜·관계식·count·길이)은 목록으로 남긴다
    recorded = sorted(unevaluated)
    assert set(recorded) <= conditions
    for marker in ("matcher(", "isAfter(", "getNightlyRate()", "countByRoomNumberAndStatus(", "length()"):
        assert any(marker in condition for condition in recorded), (marker, recorded)
    assert not any("VIP" in condition for condition in recorded)  # VIP×포인트 조건은 평가됐다


def test_req311_deterministic(tmp_path, pict_tool):
    outs = []
    for name in ("a", "b"):
        base = tmp_path / name / "nested"
        _derive_render(_real_bundle(base), base, pw.Pairwise.available(_tool(pict_tool), base / "w", 120), "out")
        outs.append(base / "out")
    for name in ("cases.json", PAIRWISE_FILE):
        assert (outs[0] / name).read_bytes() == (outs[1] / name).read_bytes(), name


def test_req315_no_leaks(tmp_path, pict_tool):
    _derive_render(_real_bundle(tmp_path), tmp_path, _available(tmp_path, pict_tool))
    for name in ("cases.json", PAIRWISE_FILE):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert redact.find_leaks(text) == [], name
        assert str(tmp_path) not in text and str(Path.home()) not in text and str(pict_tool["path"]) not in text, name


def test_req316_mutated(tmp_path, pict_tool):
    _, doc, _ = _derive_render(_make_bundle(tmp_path / "m", _load_docs(MUTATED)), tmp_path, _available(tmp_path, pict_tool))
    assert _pairwise_cases(doc)
    originals = [line.strip() for line in (MUTATED / "original-names.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    for name in ("cases.json", PAIRWISE_FILE):
        text = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert [o for o in originals if o in text] == [], name
    assert [o for o in originals if o in (REPO_ROOT / "site-gen" / "td" / "detgen" / "pairwise.py").read_text(encoding="utf-8")] == []
