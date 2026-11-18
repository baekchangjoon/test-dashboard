"""번들·LLM 격리 계열 수용 테스트. 이 파일에는 REQ-021(bbtg 허용 스키마)이 있다.
REQ-019/020/022는 소유 Task(번들 조립, S06)가 이 파일에 덧붙인다.
"""
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from td import bbtg

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "site-gen" / "td" / "bbtg_allow"


def _object_schemas(node, path=""):
    """스키마 트리의 모든 object 스키마를 (경로, 스키마)로 낸다."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node or "patternProperties" in node:
            yield path, node
        for key, child in node.items():
            yield from _object_schemas(child, f"{path}/{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _object_schemas(child, f"{path}/{index}")


def _all_keys(node):
    if isinstance(node, dict):
        for key, child in node.items():
            yield key
            yield from _all_keys(child)
    elif isinstance(node, list):
        for child in node:
            yield from _all_keys(child)


def _all_strings(node):
    if isinstance(node, dict):
        for child in node.values():
            yield from _all_strings(child)
    elif isinstance(node, list):
        for child in node:
            yield from _all_strings(child)
    elif isinstance(node, str):
        yield node


def _keyed_strings(node, key=""):
    if isinstance(node, dict):
        for child_key, child in node.items():
            yield from _keyed_strings(child, child_key)
    elif isinstance(node, list):
        for child in node:
            yield from _keyed_strings(child, key)
    elif isinstance(node, str):
        yield key, node


def test_req021_bbtg_allow_schema(s02_default):
    run = s02_default
    assert run.stage["status"] == "passed", run.stage
    # 스킬 7개마다 허용 스키마가 있고, 모든 object 스키마가 additionalProperties: false이다(동적 맵은 patternProperties로 값만 허용).
    schema_files = sorted(p.name for p in SCHEMA_DIR.glob("*.schema.json"))
    assert schema_files == sorted(f"{skill}.schema.json" for skill in bbtg.SKILLS)
    for skill in bbtg.SKILLS:
        schema = json.loads((SCHEMA_DIR / f"{skill}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        for path, sub in _object_schemas(schema):
            if "properties" in sub or "patternProperties" in sub:
                assert sub.get("additionalProperties") is False, f"{skill}{path}"
        # 정제된 산출물이 자기 스키마를 통과한다
        document = json.loads((run.clean_dir / f"{skill}.json").read_text())
        errors = list(Draft202012Validator(schema).iter_errors(document))
        assert errors == [], f"{skill}: {errors[0].message[:200] if errors else ''}"
        assert document["skill"] == skill and document["results"], skill
    assert sorted(p.name for p in run.clean_dir.iterdir()) == sorted(f"{skill}.json" for skill in bbtg.SKILLS)

    # 금지 경로: 값이 있어 실제로 제거한 경로는 strippedFields, 선언만 하고 이번 입력에는 값이 없던 경로는 forbiddenDeclared다.
    sanitize = run.manifest["sanitize"]
    stripped, declared_only = sanitize["strippedFields"], sanitize["forbiddenDeclared"]
    assert "inspect-auth:interceptor_sources[].source" in stripped
    assert "plan-tests:test_cases[].condition" in stripped  # 식 텍스트(A1 재정): petclinic raw에 값이 있다
    assert set(stripped) == set(sanitize["removedCounts"])
    assert not set(stripped) & set(declared_only)
    assert set(bbtg.declared_forbidden_paths()) <= set(stripped) | set(declared_only)
    # 원본에 값이 있던 경로마다 removedCount가 기록된다(raw와 대조).
    raw_auth = json.loads((run.out_dir / "raw" / "stdout" / "inspect-auth.json").read_text())
    sources_with_value = [item for item in raw_auth["interceptor_sources"] if item.get("source")]
    assert sources_with_value, "petclinic 기준 raw에 인터셉터 원문이 있어야 이 검사가 의미 있다"
    assert sanitize["removedCounts"]["inspect-auth:interceptor_sources[].source"] == len(sources_with_value)
    raw_stack = json.loads((run.out_dir / "raw" / "stdout" / "inspect-stack.json").read_text())
    assert sanitize["removedCounts"]["inspect-stack:analysis_meta.timestamp"] == 1 and raw_stack["analysis_meta"]["timestamp"]
    raw_plans = [json.loads(p.read_text()) for p in sorted((run.out_dir / "raw" / "stdout").glob("plan-tests-*.json"))]
    raw_conditions = sum(1 for plan in raw_plans for case in plan["test_cases"] if case.get("condition"))
    assert raw_conditions and sanitize["removedCounts"]["plan-tests:test_cases[].condition"] == raw_conditions
    for path, count in sanitize["removedCounts"].items():
        assert count >= 1 and path in stripped, path
    assert sanitize["errors"] == []

    # 정제 결과에 원문·시각·절대 경로가 없다.
    for skill in bbtg.SKILLS:
        document = json.loads((run.clean_dir / f"{skill}.json").read_text())
        keys = set(_all_keys(document))
        assert not keys & {"timestamp", "scan_duration_ms", "llm_delegation_guide", "deep_inspection", "condition", "where_clause",
                           "sql_delete", "formula", "variable_name", "wiremock_strategy", "display_name",
                           "intent_tokens", "signatures", "methods"}, skill
        for text in _all_strings(document):
            assert "package org.springframework" not in text, f"{skill}: 소스 원문 조각"
            assert str(run.sut_src) not in text and not text.startswith("/Users/") and "/private/" not in text, f"{skill}: {text[:80]}"
    # A1(식·문장 텍스트 금지): 식 문자를 포함한 12자 이상 문자열이 SUT 소스에 그대로 있으면 안 된다(관문과 독립으로 다시 센다).
    corpus = " ".join(re.sub(r"\s+", " ", p.read_text(errors="replace")) for p in run.sut_src.rglob("*.java") if "src" in p.parts)
    special = set("(){};=<>!&|+*\"'")
    for skill in bbtg.SKILLS:
        for key, text in _keyed_strings(json.loads((run.clean_dir / f"{skill}.json").read_text())):
            if key == "display_name":  # 사람이 쓴 @DisplayName 메타데이터는 A1 대상이 아니다(보고서에 명시)
                continue
            normalized = re.sub(r"\s+", " ", text)
            if len(text) >= 12 and special & set(text) and not re.fullmatch(r"/[\w\-./{}*?&=%:,]+|[\w.$<>\[\],? ]+", text):
                assert normalized not in corpus, f"{skill}: 소스 식 텍스트 {text[:60]!r}"
    # 자격 증명 모양 문자열이 없다
    for skill in bbtg.SKILLS:
        assert not bbtg.credential_violations(json.loads((run.clean_dir / f"{skill}.json").read_text())), skill
    # 기존 IT의 의도(@DisplayName, 테스트 메서드 이름)는 구조 메타데이터로만 남는다: 이름·표시 이름이 clean 어디에도 없다.
    scan = json.loads((run.clean_dir / "scan-test-assets.json").read_text())["results"][0]["data"]
    raw_scan = json.loads((run.out_dir / "raw" / "stdout" / "scan-test-assets.json").read_text())
    clean_text = json.dumps(scan, ensure_ascii=False)
    raw_methods = [m for tc in raw_scan["test_classes"] for m in tc["methods"]]
    assert raw_methods
    for method in raw_methods:
        assert method["name"] not in clean_text, method["name"]
        if method.get("display_name"):
            assert method["display_name"] not in clean_text
    assert [tc["test_method_count"] for tc in scan["test_classes"]] == [tc["test_method_count"] for tc in raw_scan["test_classes"]]
    assert scan["support_classes"] and all(isinstance(n, int) for n in scan["endpoint_coverage"].values())
    clean_auth = json.loads((run.clean_dir / "inspect-auth.json").read_text())["results"][0]["data"]
    assert clean_auth["interceptor_sources"] and all("source" not in item for item in clean_auth["interceptor_sources"])
    # 원문이 raw에는 남아 있다(로컬 전용): 제거는 정제 단계의 일이다.
    assert "package org.springframework" in sources_with_value[0]["source"]
