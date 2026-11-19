"""E2E 계열 수용 테스트. 이 파일에는 REQ-027(결정적 testId)의 Unit 부분이 있다.
Int 부분(dry-run 두 번의 testId 집합 비교)은 러너를 만드는 Task가 덧붙인다.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import SutEnv
from helpers import find_leaked_resources, make_site_run
from td import coverage, scenarios, testid
from td.site import pages

TEST_ID_RE = re.compile(r"^E2E_(base|jqa|owl)_[0-9a-f]{8}r[1-9](g[0-9]+)?_[A-Za-z0-9_]+#L\d+$")
HASH = "0123456789abcdef" * 4

OUTLINE_FEATURE = """\
Feature: Owner search
  Background:
    Given a thing

  Scenario: plain
    When I search
    Then ok

  @tag
  Scenario Outline: by name <name>
    When I search for "<name>"
    Then I see <count>

    Examples: first
      | name  | count |
      | Davis | 2     |
      | Black | 1     |

    Examples: second
      | name | count |
      | Lee  | 0     |

  Rule: some rule
    Scenario: in rule
      When x
"""


def test_req027_deterministic_testids():
    # Scenario Outline은 Examples 데이터 행마다 하나, L<line>은 그 행의 줄이다. Background와 헤더 행은 시나리오가 아니다.
    picks = testid.pickles(OUTLINE_FEATURE)
    assert [p.line for p in picks] == [5, 16, 17, 21, 24]
    assert picks[1].name == "by name <name>" and picks[0].outline is False and picks[1].outline is True

    def build():
        taken: set[str] = set()
        return [testid.make("jqa", HASH, 2, None, "features/owner.feature", p.line, taken, name="Owner search")
                for p in picks]

    first, second = build(), build()
    assert first == second                      # 같은 입력 -> 같은 집합과 순서
    assert len(set(first)) == len(first)        # 중복 0
    assert all(TEST_ID_RE.match(t) for t in first), first
    assert first[0] == "E2E_jqa_01234567r2_Owner_search#L5"


def test_req027_generation_suffix_and_validation():
    taken: set[str] = set()
    assert testid.make("base", HASH, 1, 2, "a.feature", 3, taken, name="X") == "E2E_base_01234567r1g2_X#L3"
    for bad in [("zzz", HASH, 1, None), ("jqa", HASH, 0, None), ("jqa", HASH, 10, None), ("jqa", "xyz", 1, None)]:
        with pytest.raises(ValueError):
            testid.make(*bad, "a.feature", 3, set())


def test_req027_slug_collision_suffix_per_feature():
    # a/owner.feature {L5, L9}, b/owner.feature {L5, L7}: slug는 feature 단위. b의 모든 id가 owner_2를 쓴다.
    features = {"a/owner.feature": [5, 9], "b/owner.feature": [5, 7], "c/owner.feature": [1]}

    def build():
        slugs: dict[str, str] = {}
        taken: set[str] = set()
        return {path: [testid.make("owl", HASH, 1, None, path, line, taken, slugs=slugs) for line in lines]
                for path, lines in sorted(features.items())}

    ids = build()
    assert ids["a/owner.feature"] == ["E2E_owl_01234567r1_owner#L5", "E2E_owl_01234567r1_owner#L9"]
    assert ids["b/owner.feature"] == ["E2E_owl_01234567r1_owner_2#L5", "E2E_owl_01234567r1_owner_2#L7"]
    assert ids["c/owner.feature"] == ["E2E_owl_01234567r1_owner_3#L1"]
    assert build() == ids
    flat = [t for group in ids.values() for t in group]
    assert len(set(flat)) == len(flat) and all(TEST_ID_RE.match(t) for t in flat)
    # 호출 순서가 아니라 feature가 slug를 소유한다: b를 먼저 말해도 같은 feature 안에서는 일정하다
    slugs: dict[str, str] = {}
    first = testid.make("owl", HASH, 1, None, "b/owner.feature", 5, set(), slugs=slugs)
    again = testid.make("owl", HASH, 1, None, "b/owner.feature", 7, set(), slugs=slugs)
    assert first.split("#")[0] == again.split("#")[0]


def test_req027_duplicate_id_without_registry_is_error():
    taken: set[str] = set()
    testid.make("owl", HASH, 1, None, "a/owner.feature", 5, taken)
    with pytest.raises(ValueError):
        testid.make("owl", HASH, 1, None, "a/owner.feature", 5, taken)


def test_req027_korean_names_use_path_hash():
    # Review Focus 4: 이름이 모두 비ASCII이면 feature 경로의 sha1 앞 8자리로 만든 f<hash>다. 비지 않고 결정적이다.
    slug = testid.feature_slug("features/소유자_조회.feature", "소유자 조회")
    assert re.fullmatch(r"f[0-9a-f]{8}", slug)
    assert slug == testid.feature_slug("features/소유자_조회.feature", "소유자 조회")
    assert slug != testid.feature_slug("features/수의사_조회.feature", "수의사 조회")
    # 혼합 이름은 ASCII 부분만 남는다
    assert testid.feature_slug("f.feature", "Owner 조회 API!") == "Owner_API"
    # 이름이 없으면 파일 이름에서 만든다
    assert testid.feature_slug("features/vet-list.feature", None) == "vet_list"
    taken: set[str] = set()
    made = testid.make("base", HASH, 3, None, "features/소유자.feature", 4, taken, name="소유자 조회")
    assert TEST_ID_RE.match(made) and "_f" in made


def test_req027_nonascii_slug_is_checkout_independent():
    # 해시는 generation 루트 기준 상대 경로만 쓴다: 체크아웃(루트)이 달라도 같고, 절대 경로는 명확한 오류다.
    relative = "features/소유자_조회.feature"
    roots = ["/tmp/checkout-one/gen", "/var/other/deeper/path/gen"]
    slugs = {root: testid.feature_slug(relative, "소유자 조회") for root in roots}
    assert len(set(slugs.values())) == 1
    for root in roots:
        with pytest.raises(ValueError, match="상대 경로"):
            testid.feature_slug(f"{root}/{relative}", "소유자 조회")
        with pytest.raises(ValueError, match="상대 경로"):
            testid.make("base", HASH, 1, None, f"{root}/{relative}", 3, set())


FIXTURE_TABLE = Path(__file__).resolve().parents[1] / "fixtures" / "testids.json"


def _table() -> dict:
    return json.loads(FIXTURE_TABLE.read_text())


@pytest.mark.parametrize("case", _table()["cases"], ids=lambda case: case["name"])
def test_req027_python_matches_shared_table(case):
    """Java TestIds와 공유하는 표(tests/fixtures/testids.json)의 Python 쪽 검증. feature는 상대 경로 순서로 부른다."""
    slugs: dict[str, str] = {}
    taken: set[str] = set()
    made = [testid.make(case["arm"], case["inputHash"], case["rep"], case["gen"], feature["path"], line, taken,
                        name=feature["name"], slugs=slugs)
            for feature in sorted(case["features"], key=lambda f: f["path"]) for line in feature["pickles"]]
    assert made == case["expected"]
    assert len(set(made)) == len(made) and all(TEST_ID_RE.match(item) for item in made)


@pytest.mark.parametrize("error", _table()["errors"], ids=lambda error: error["name"])
def test_req027_python_rejects_shared_table_errors(error):
    with pytest.raises(ValueError):
        testid.make(error["arm"], error["inputHash"], error["rep"], error["gen"], error["path"], error["line"], set())


# --- S07 Cucumber 실행기(Task 21, REQ-028, REQ-029, REQ-062) ------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_GENERATION = REPO_ROOT / "tests" / "fixtures" / "generated-sample"
SUT_FILE = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"
SAMPLE_GEN_ID = "base-01234567-r1"
SAMPLE_IDENT = scenarios.GenIdent.from_gen_id(SAMPLE_GEN_ID)
# 샘플 generation의 정답표(손으로 센 값): feature별 pickle과 결과
EXPECTED_STATUS = {
    "features/vet_lookup.feature": ["passed", "failed"],
    "features/outline.feature": ["passed", "passed"],      # Examples 행 2개
    "features/undefined.feature": ["undefined"],
    "features/zero_request.feature": ["passed"],           # 요청 0회
    "features/broken.feature": ["uncompilable"],           # glue 클래스가 컴파일되지 않는다
}
SAMPLE_PICKLE_COUNT = 7


def _copy_sample(parent: Path) -> Path:
    target = parent / SAMPLE_GEN_ID
    shutil.copytree(SAMPLE_GENERATION, target)
    return target


@pytest.fixture(scope="module")
def runner_classpath(tmp_path_factory) -> str:
    return scenarios.runner_classpath(tmp_path_factory.mktemp("classpath") / "classpath.txt")


# --- SUT 없이 되는 부분(Unit/Int) ----------------------------------------------------------------------------------------
def test_req028_compile_check_excludes_only_the_broken_class(tmp_path, runner_classpath):
    gen_dir = _copy_sample(tmp_path)
    result = scenarios.compile_check(gen_dir, runner_classpath, tmp_path / "out")
    assert result.excluded == ["glue/BrokenSteps.java"]
    assert result.excluded_features == ["features/broken.feature"]
    assert "BrokenSteps.java" in result.compiler_output and "incompatible types" in result.compiler_output
    assert str(tmp_path) not in result.compiler_output      # 경로는 generation 루트 기준 상대 경로다
    written = json.loads((tmp_path / "out" / "compile-excluded.json").read_text())
    assert written == {"classes": ["glue/BrokenSteps.java"], "features": ["features/broken.feature"]}
    # 스냅샷은 불변이다
    assert (gen_dir / "glue" / "BrokenSteps.java").read_text() == (SAMPLE_GENERATION / "glue" / "BrokenSteps.java").read_text()


def test_req029_dry_run_finds_undefined_steps_without_sut(tmp_path, runner_classpath):
    gen_dir = _copy_sample(tmp_path)
    result = scenarios.validate_generation(gen_dir, tmp_path / "validate")
    assert result.compile.excluded == ["glue/BrokenSteps.java"]
    dry = result.dry_run
    assert [(item["feature"], item["step"]) for item in dry.undefined_steps] == [
        ("features/undefined.feature", "a step that no glue class defines")]
    assert dry.pickle_count == SAMPLE_PICKLE_COUNT - 1       # 컴파일 제외 feature는 dry-run에 없다
    assert dry.undefined_pickles == {("features/undefined.feature", 3)}
    assert dry.json_path == (tmp_path / "validate" / "dryrun.json").resolve()


def test_req028_testids_json_matches_python_ids(tmp_path):
    gen_dir = _copy_sample(tmp_path)
    path = scenarios.write_testids(gen_dir, SAMPLE_IDENT, tmp_path / "testids.json")
    data = json.loads(path.read_text())
    assert (data["arm"], data["inputHash"], data["rep"], data["gen"]) == ("base", "01234567", 1, None)
    assert {f["path"] for f in data["features"]} == set(EXPECTED_STATUS)
    outline = next(f for f in data["features"] if f["path"] == "features/outline.feature")
    assert [p["line"] for p in outline["pickles"]] == [9, 10]    # Examples 데이터 행의 줄
    refs = scenarios.pickle_refs(gen_dir, SAMPLE_IDENT)
    assert len(refs) == SAMPLE_PICKLE_COUNT and len({r.test_id for r in refs}) == SAMPLE_PICKLE_COUNT
    assert all(TEST_ID_RE.match(r.test_id) for r in refs), [r.test_id for r in refs]


def _dryrun(tmp_path, undefined=frozenset()):
    return scenarios.DryRun([], tmp_path / "dryrun.json", frozenset(undefined), 0)


def test_req028_reconcile_appends_uncompilable_and_undefined(tmp_path):
    gen_dir = _copy_sample(tmp_path)
    refs = {(r.feature, r.line): r.test_id for r in scenarios.pickle_refs(gen_dir, SAMPLE_IDENT)}
    run_lines = [
        {"testId": refs[("features/vet_lookup.feature", 3)], "status": "passed", "requests": 1, "exec": "exec/a.exec"},
        {"testId": refs[("features/vet_lookup.feature", 7)], "status": "failed", "requests": 1, "exec": "exec/b.exec"},
        {"testId": refs[("features/outline.feature", 9)], "status": "passed", "requests": 1, "exec": "exec/c.exec"},
        {"testId": refs[("features/outline.feature", 10)], "status": "passed", "requests": 1, "exec": "exec/d.exec"},
        {"testId": refs[("features/zero_request.feature", 3)], "status": "passed", "requests": 0, "exec": None},
    ]
    merged = scenarios.reconcile(gen_dir / "features", _dryrun(tmp_path, {("features/undefined.feature", 3)}), run_lines,
                                 ["features/broken.feature"], ident=SAMPLE_IDENT)
    assert len(merged) == SAMPLE_PICKLE_COUNT and len({m.test_id for m in merged}) == SAMPLE_PICKLE_COUNT
    by_feature = {}
    for item in merged:
        by_feature.setdefault(item.feature, []).append(item.status)
    assert by_feature == EXPECTED_STATUS
    assert scenarios.undefined_ratio(merged) == pytest.approx(1 / SAMPLE_PICKLE_COUNT)
    results_file = tmp_path / "scenario-results.json"
    results_file.write_text("".join(json.dumps(line) + "\n" for line in run_lines))
    assert scenarios.append_missing(results_file, merged) == 2          # uncompilable 1 + undefined 1
    assert len(coverage.parse_scenario_results(results_file)) == SAMPLE_PICKLE_COUNT   # S08이 읽는 엄격한 NDJSON


def test_req028_reconcile_rejects_missing_duplicate_and_unknown(tmp_path):
    gen_dir = _copy_sample(tmp_path)
    refs = {(r.feature, r.line): r.test_id for r in scenarios.pickle_refs(gen_dir, SAMPLE_IDENT)}
    vet = {"testId": refs[("features/vet_lookup.feature", 3)], "status": "passed", "requests": 0, "exec": None}
    with pytest.raises(scenarios.ReconcileError, match="결과 줄이 없는") as missing:
        scenarios.reconcile(gen_dir / "features", _dryrun(tmp_path), [vet], ["features/broken.feature"], ident=SAMPLE_IDENT)
    assert refs[("features/outline.feature", 9)] in str(missing.value)
    with pytest.raises(scenarios.ReconcileError, match="중복"):
        scenarios.reconcile(gen_dir / "features", _dryrun(tmp_path), [vet, vet], [], ident=SAMPLE_IDENT)
    with pytest.raises(scenarios.ReconcileError, match="알 수 없는"):
        scenarios.reconcile(gen_dir / "features", _dryrun(tmp_path), [{**vet, "testId": "UNMAPPED:x"}], [], ident=SAMPLE_IDENT)


def test_req028_verify_exec_counts_and_missing(tmp_path):
    (tmp_path / "exec").mkdir()
    (tmp_path / "exec" / "T1#L3.exec").write_bytes(b"x")
    (tmp_path / "exec" / "aggregate.exec").write_bytes(b"x")     # aggregate는 세지 않는다
    make = lambda test_id, requests, exec_path: scenarios.ScenarioResult(test_id, "passed", requests, exec_path, "f", 1)
    ok = scenarios.verify_exec([make("T1#L3", 2, "exec/T1#L3.exec"), make("T2#L4", 0, None)], tmp_path / "scenario-results.json",
                               tmp_path / "exec")
    assert ok.ok and ok.expected_count == ok.actual_count == 1
    gone = scenarios.verify_exec([make("T1#L3", 2, "exec/T1#L3.exec"), make("T9#L9", 1, "exec/T9#L9.exec")],
                                 tmp_path / "scenario-results.json", tmp_path / "exec")
    assert gone.missing == ["T9#L9"] and not gone.ok
    nopath = scenarios.verify_exec([make("T1#L3", 2, "exec/T1#L3.exec"), make("T5#L1", 3, None)],
                                   tmp_path / "scenario-results.json", tmp_path / "exec")
    assert nopath.missing == ["T5#L1"] and not nopath.ok


# --- 실제 SUT 컨테이너에서 샘플 generation을 실행한다 ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def s07_run(tmp_path_factory, session_id, local_env):
    """샘플 generation을 pipeline/lib/e2e.sh의 td_e2e_generation으로 한 번 실행한다(SUT 컨테이너 기동과 정리 포함)."""
    work = tmp_path_factory.mktemp("s07")
    env = SutEnv(work, session_id, "s07")
    gen_dir = _copy_sample(work / "generated")
    java_home = scenarios.java_home(17)
    script = f'''
source "{REPO_ROOT}/pipeline/lib/e2e.sh"
td_e2e_generation S07 {SAMPLE_GEN_ID} "{gen_dir}" "{java_home}"
echo "E2E_STATUS=$E2E_STATUS"
echo "E2E_REASON=$E2E_REASON"
echo "E2E_EXTRA=$E2E_EXTRA"
'''
    result = env.bash(script, timeout=1500, TD_SUT_FILE=str(SUT_FILE),
                      TD_SUT_USER=local_env["TD_SUT_USER"], TD_SUT_PASS=local_env["TD_SUT_PASS"])
    try:
        yield type("S07Run", (), {"result": result, "env": env, "gen_dir": gen_dir,
                                  "out": env.run_dir / "S07" / SAMPLE_GEN_ID})()
    finally:
        env.cleanup()


def _status(run) -> str:
    line = next((l for l in run.result.stdout.splitlines() if l.startswith("E2E_STATUS=")), "E2E_STATUS=<none>")
    assert line == "E2E_STATUS=passed", (run.result.stdout + run.result.stderr)[-3000:]
    return line


def _results(run) -> list[dict]:
    _status(run)
    return [json.loads(line) for line in (run.out / "scenario-results.json").read_text().splitlines()]


def test_req028_scenario_conservation(s07_run):
    lines = _results(s07_run)
    out = s07_run.out
    # 등식 1: .feature 시나리오 수 = 결과 시나리오 수(uncompilable 포함), 줄마다 한 번씩
    expected_ids = [r.test_id for r in scenarios.pickle_refs(s07_run.gen_dir, SAMPLE_IDENT)]
    pickles = sum(len(testid.pickles((s07_run.gen_dir / f).read_text())) for f in EXPECTED_STATUS)
    assert pickles == len(expected_ids) == len(lines) == SAMPLE_PICKLE_COUNT
    assert sorted(l["testId"] for l in lines) == sorted(expected_ids)
    assert all(set(l) == {"testId", "status", "requests", "exec"} for l in lines)
    by_status = {}
    for line in lines:
        by_status[line["status"]] = by_status.get(line["status"], 0) + 1
    assert by_status == {"passed": 4, "failed": 1, "undefined": 1, "uncompilable": 1}
    # 등식 2: S08이 TC 행으로 쓰는 결과(스위트 e2e-<genId>)도 같은 수다
    suites = coverage.discover_suites(out.parent.parent)
    assert suites[f"e2e-{SAMPLE_GEN_ID}"] == out / "exec"
    assert len(coverage.load_results(out.parent.parent, f"e2e-{SAMPLE_GEN_ID}")) == SAMPLE_PICKLE_COUNT
    # 등식 3: 요청 1회 이상 시나리오 수 = .exec 수. 요청 0회 시나리오는 exec가 없고 분모에 남는다.
    positive = [l for l in lines if l["requests"] > 0]
    exec_files = sorted(p.name for p in (out / "exec").glob("*.exec") if p.name != "aggregate.exec")
    assert len(positive) == len(exec_files) == 4
    for line in positive:
        assert (out / line["exec"]).is_file() and line["exec"].endswith(".exec") and "#" in line["exec"]
    zero = [l for l in lines if l["requests"] == 0]
    assert len(zero) == 3 and all(l["exec"] is None for l in zero)
    assert {l["status"] for l in zero} == {"passed", "undefined", "uncompilable"}
    # 실행 제외 표식 0건
    banned = re.compile(r"@ignore|@Disabled|@wip", re.IGNORECASE)
    sources = [*s07_run.gen_dir.glob("features/**/*.feature"), *s07_run.gen_dir.glob("glue/**/*.java")]
    assert sources and not [p.name for p in sources if banned.search(p.read_text())]


def test_req029_undefined_ratio(s07_run):
    _status(s07_run)
    summary = json.loads((s07_run.out / "summary.json").read_text())
    # dry-run JSON에서 다시 센다: undefined step이 있는 pickle(uncompilable 제외) / (dry-run pickle + uncompilable pickle)
    dry = json.loads((s07_run.out / "dryrun.json").read_text())
    elements = [e for feature in dry for e in feature["elements"] if e["type"] != "background"]
    undefined = [e for e in elements if any(s["result"]["status"] == "undefined" for s in e["steps"])]
    uncompilable = json.loads((s07_run.out / "compile-excluded.json").read_text())["features"]
    uncompilable_pickles = sum(len(testid.pickles((s07_run.gen_dir / f).read_text())) for f in uncompilable)
    recomputed = len(undefined) / (len(elements) + uncompilable_pickles)
    assert recomputed == pytest.approx(1 / SAMPLE_PICKLE_COUNT)
    assert summary["undefinedRatio"] == pytest.approx(recomputed)
    assert f'"undefinedRatio": {summary["undefinedRatio"]}' in (s07_run.out / "summary.json").read_text()
    assert json.loads(s07_run.result.stdout.split("E2E_EXTRA=")[1].splitlines()[0])["undefinedRatio"] == pytest.approx(recomputed)


def test_req062_cucumber_reports(s07_run, tmp_path):
    _status(s07_run)
    for name in ("cucumber.ndjson", "cucumber.json", "junit.xml", "html/index.html", "dryrun.json"):
        assert (s07_run.out / name).stat().st_size > 0, name
    assert "<html" in (s07_run.out / "html" / "index.html").read_text().lower()
    # 사이트: S07/<genId>/html -> cucumber/<genId>/ 이고 run 페이지에서 링크된다
    run_dir = make_site_run(tmp_path, "petclinic", "20261101-010000Z-aaaaaaa-manual-00000001")
    stage_file = run_dir / "stages" / "S07.json"
    stage_file.write_text(json.dumps({"id": "S07", "status": "passed", "reason": None,
                                      "outputs": {f"html:{SAMPLE_GEN_ID}": str(s07_run.out / "html")}}))
    (run_dir / "run.json").write_text(json.dumps({**json.loads((run_dir / "run.json").read_text()),
                                                  "stages": {"S00": "passed", "S01": "passed", "S07": "passed", "S08": "passed",
                                                             "S13": "publishing"}}))
    site = pages.render_run(run_dir, run_dir)
    assert (site.parent / "cucumber" / SAMPLE_GEN_ID / "index.html").is_file()
    assert f'href="cucumber/{SAMPLE_GEN_ID}/index.html"' in site.read_text()


def test_req028_resources_cleaned_up(s07_run, session_id):
    _status(s07_run)
    assert find_leaked_resources(f"td-test-{session_id}") == {}


def test_req028_password_not_on_command_lines():
    # 비밀번호는 환경 변수(TD_AUTH_PASS)로만 넘긴다: 실행 스크립트에 -Ptd.auth.pass가 없다
    sources = [REPO_ROOT / "pipeline" / "lib" / "e2e.sh", REPO_ROOT / "pipeline" / "S07-e2e.sh",
               REPO_ROOT / "site-gen" / "td" / "scenarios.py", REPO_ROOT / "e2e" / "runner" / "build.gradle"]
    for source in sources:
        assert source.is_file(), source
        assert "td.auth.pass" not in source.read_text(), source


def test_req028_finalize_fails_listing_testids_when_exec_is_missing(tmp_path):
    """주입: 결과 줄은 exec 경로를 적었는데 파일이 없다 -> generation은 failed이고 사유에 testId가 들어간다."""
    gen_dir = _copy_sample(tmp_path)
    out = tmp_path / "out"
    (out / "html").mkdir(parents=True)
    for name in ("cucumber.ndjson", "cucumber.json", "junit.xml", "html/index.html"):
        (out / name).write_text("x")
    refs = {(r.feature, r.line): r.test_id for r in scenarios.pickle_refs(gen_dir, SAMPLE_IDENT)}
    (out / "compile-excluded.json").write_text(json.dumps({"classes": ["glue/BrokenSteps.java"], "features": ["features/broken.feature"]}))
    (out / "dryrun.json").write_text(json.dumps([{"uri": "classpath:features/undefined.feature", "elements": [
        {"type": "scenario", "line": 3, "name": "x", "steps": [{"name": "s", "line": 4, "result": {"status": "undefined"}}]}]}]))
    gone = refs[("features/vet_lookup.feature", 3)]
    lines = [{"testId": gone, "status": "passed", "requests": 1, "exec": f"exec/{gone}.exec"}]
    for feature, line in (("features/vet_lookup.feature", 7), ("features/outline.feature", 9), ("features/outline.feature", 10)):
        test_id = refs[(feature, line)]
        lines.append({"testId": test_id, "status": "passed", "requests": 1, "exec": f"exec/{test_id}.exec"})
        (out / "exec").mkdir(exist_ok=True)
        (out / "exec" / f"{test_id}.exec").write_bytes(b"x")
    lines.append({"testId": refs[("features/zero_request.feature", 3)], "status": "passed", "requests": 0, "exec": None})
    (out / "scenario-results.json").write_text("".join(json.dumps(line) + "\n" for line in lines))
    result = scenarios.finalize(gen_dir, out, SAMPLE_IDENT)
    assert result["status"] == "failed" and gone in result["reason"] and ".exec" in result["reason"]
    assert (out / "summary.json").is_file()
    # 파일을 만들어 주면 같은 입력이 통과한다(대조 대상은 정확히 그 파일이다)
    (out / "exec" / f"{gone}.exec").write_bytes(b"x")
    assert scenarios.finalize(gen_dir, out, SAMPLE_IDENT)["status"] == "passed"


def test_req028_sut_start_failure_fails_generation_and_cleans_up(tmp_path_factory, session_id, local_env):
    """주입: SUT jar가 없어 기동할 수 없다 -> 멈추지 않고 failed, 사유에 SUT, 남은 컨테이너 없음."""
    work = tmp_path_factory.mktemp("s07fail")
    env = SutEnv(work, session_id, "s07fail")
    gen_dir = _copy_sample(work / "generated")
    script = f'''
source "{REPO_ROOT}/pipeline/lib/e2e.sh"
td_e2e_generation S07 {SAMPLE_GEN_ID} "{gen_dir}" "{scenarios.java_home(17)}"
echo "E2E_STATUS=$E2E_STATUS"; echo "E2E_REASON=$E2E_REASON"
'''
    try:
        result = env.bash(script, timeout=900, TD_SUT_FILE=str(SUT_FILE), TD_SUT_JAR=str(work / "no-such.jar"),
                          TD_SUT_USER=local_env["TD_SUT_USER"], TD_SUT_PASS=local_env["TD_SUT_PASS"])
        assert "E2E_STATUS=failed" in result.stdout and "SUT" in result.stdout, result.stdout[-1500:]
        assert not (work / "runs" / f"test-{session_id}-s07fail" / "S07" / SAMPLE_GEN_ID / "scenario-results.json").exists()
    finally:
        env.cleanup()
    assert find_leaked_resources(f"td-test-{session_id}") == {}


def test_req028_stage_script_records_generations_and_degrades_on_failed_one(tmp_path_factory, session_id, local_env):
    """S07-e2e.sh: S06 generation 중 하나가 실패(디렉터리 없음)해도 다른 generation은 진행되고 단계는 degraded다."""
    work = tmp_path_factory.mktemp("s07stage")
    env = SutEnv(work, session_id, "s07stage")
    gen_dir = _copy_sample(work / "generated")
    run_dir = env.run_dir
    subprocess.run(["bash", "-c", f'source "{REPO_ROOT}/pipeline/lib/common.sh"; td_py -m td.state init "{run_dir}" '
                    f'--run-id test-{session_id}-s07stage --sut petclinic --commit b6f9393'], check=True, env=env.env)
    (run_dir / "stages").mkdir(exist_ok=True)
    missing_id = "jqa-01234567-r1"
    (run_dir / "stages" / "S06.json").write_text(json.dumps({"id": "S06", "status": "passed", "outputs": {}, "generations": {
        SAMPLE_GEN_ID: {"arm": "base", "status": "passed", "dir": str(gen_dir)},
        missing_id: {"arm": "jqa", "status": "passed", "dir": str(work / "nowhere")},
        "owl-01234567-r1": {"arm": "owl", "status": "failed", "reason": "S06 repair failed"}}}))
    try:
        done = subprocess.run(["bash", str(REPO_ROOT / "pipeline" / "S07-e2e.sh"), "petclinic", run_dir.name], capture_output=True,
                              text=True, timeout=1500, env={**env.env, "TD_SUT_FILE": str(SUT_FILE),
                                                            "TD_SUT_USER": local_env["TD_SUT_USER"],
                                                            "TD_SUT_PASS": local_env["TD_SUT_PASS"]})
        subprocess.run(["bash", "-c", f'source "{REPO_ROOT}/pipeline/lib/common.sh"; td_py -m td.state post "{run_dir}" S07'],
                       check=True, env=env.env)
        stage = json.loads((run_dir / "stages" / "S07.json").read_text())
        assert stage["status"] == "degraded", (stage, done.stdout[-500:], done.stderr[-1500:])
        generations = stage["generations"]
        assert generations[SAMPLE_GEN_ID]["status"] == "passed" and generations[SAMPLE_GEN_ID]["scenarios"] == SAMPLE_PICKLE_COUNT
        assert generations[SAMPLE_GEN_ID]["undefinedRatio"] == pytest.approx(1 / SAMPLE_PICKLE_COUNT)
        assert generations[missing_id]["status"] == "failed" and "nowhere" in generations[missing_id]["reason"]
        assert generations["owl-01234567-r1"]["status"] == "skipped"          # S06에서 이미 실패한 generation은 실행하지 않는다
        assert stage["outputs"] == {f"html:{SAMPLE_GEN_ID}": str(run_dir / "S07" / SAMPLE_GEN_ID / "html")}
        assert not (run_dir / "S07" / "owl-01234567-r1").exists()
    finally:
        env.cleanup()


# --- glue 배치 규약과 제외 범위(리뷰 라운드 1) ---------------------------------------------------------------------------------
def test_req028_glue_mapping_ascii_and_non_ascii_stems():
    import hashlib
    assert scenarios.glue_class_for_feature("features/sample_flow.feature") == "glue/SampleFlowSteps.java"
    relative = "features/소유자_조회.feature"
    sha = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:8]
    assert scenarios.glue_class_for_feature(relative) == f"glue/F{sha}Steps.java"


def test_req028_stray_glue_class_is_a_layout_error(tmp_path):
    gen_dir = _copy_sample(tmp_path)
    (gen_dir / "glue" / "Helper.java").write_text("package glue;\npublic class Helper {}\n")
    assert scenarios.layout_violations(gen_dir) == ["glue/Helper.java"]
    with pytest.raises(scenarios.LayoutError, match="glue/Helper.java"):
        scenarios.validate_generation(gen_dir, tmp_path / "validate")
    with pytest.raises(scenarios.LayoutError):
        scenarios.compile_check(gen_dir, "", tmp_path / "out")
    (gen_dir / "glue" / "Helper.java").rename(gen_dir / "glue" / "support_helper.java")  # 여전히 규약 밖
    assert scenarios.layout_violations(gen_dir)
    (gen_dir / "glue" / "support_helper.java").unlink()
    (gen_dir / "glue" / "support").mkdir()
    (gen_dir / "glue" / "support" / "Helper.java").write_text("package glue.support;\npublic class Helper {}\n")
    assert scenarios.layout_violations(gen_dir) == []


def test_req028_broken_support_class_makes_every_scenario_uncompilable(tmp_path, runner_classpath):
    gen_dir = _copy_sample(tmp_path)
    (gen_dir / "glue" / "support").mkdir()
    (gen_dir / "glue" / "support" / "Shared.java").write_text("package glue.support;\npublic class Shared { int x = \"no\"; }\n")
    result = scenarios.compile_check(gen_dir, runner_classpath, tmp_path / "out")
    assert "glue/support/Shared.java" in result.excluded
    assert result.excluded_features == scenarios.feature_files(gen_dir)       # generation 전체
    refs = scenarios.pickle_refs(gen_dir, SAMPLE_IDENT)
    merged = scenarios.reconcile(gen_dir / "features", _dryrun(tmp_path), [], result, ident=SAMPLE_IDENT)
    assert len(merged) == len(refs) == SAMPLE_PICKLE_COUNT and {m.status for m in merged} == {"uncompilable"}
    dry = scenarios.dry_run(gen_dir, tmp_path / "out")                        # 실행할 feature가 없으므로 Gradle 없이 빈 결과
    assert dry.pickle_count == 0 and dry.undefined_steps == []


def test_req028_non_ascii_feature_with_broken_steps_class_is_uncompilable_not_undefined(tmp_path, runner_classpath):
    gen_dir = _copy_sample(tmp_path)
    feature = "features/소유자_조회.feature"
    (gen_dir / feature).write_text("Feature: 소유자 조회\n\n  Scenario: 목록\n    When 한글 단계\n")
    glue_path = gen_dir / scenarios.glue_class_for_feature(feature)
    glue_path.write_text("package glue;\nimport io.cucumber.java.en.When;\npublic class "
                         + glue_path.stem + " { @When(\"한글 단계\") public void step() { int n = \"x\"; } }\n")
    result = scenarios.compile_check(gen_dir, runner_classpath, tmp_path / "out")
    assert set(result.excluded) == {"glue/BrokenSteps.java", glue_path.relative_to(gen_dir).as_posix()}
    assert set(result.excluded_features) == {"features/broken.feature", feature}
    dry = scenarios.dry_run(gen_dir, tmp_path / "out")
    assert [item["feature"] for item in dry.undefined_steps] == ["features/undefined.feature"]   # 제외 feature는 undefined로 새지 않는다


def test_req028_reconcile_rejects_malformed_harness_lines(tmp_path):
    gen_dir = _copy_sample(tmp_path)
    for bad in ({"testId": "x", "status": "passed"}, {"testId": "x", "status": "passed", "requests": "1", "exec": None},
                {"testId": "x", "status": "passed", "requests": 1, "exec": 5}):
        with pytest.raises(scenarios.ReconcileError, match="모양"):
            scenarios.reconcile(gen_dir / "features", _dryrun(tmp_path), [bad], [], ident=SAMPLE_IDENT)
