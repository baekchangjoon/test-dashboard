"""td.coverage 단위 테스트(REQ-031/032/033): 순수 함수와 jacoco XML 파서, 슬러그."""
import pytest

from td import coverage
from td.site.pages import slug


def test_slug_is_deterministic_sha1_prefix():
    assert slug("VetApiBlackBoxIT#listAllVets") == slug("VetApiBlackBoxIT#listAllVets")
    assert len(slug("x")) == 10 and slug("a") != slug("b")
    import hashlib
    assert slug("x") == hashlib.sha1(b"x").hexdigest()[:10]


XML = """<?xml version="1.0"?><report name="r">
<package name="p/q"><class name="p/q/A" sourcefilename="A.java"><method name="m" desc="()V" line="1"><counter type="METHOD" missed="0" covered="1"/></method></class>
<sourcefile name="A.java"><line nr="1" mi="0" ci="2" mb="0" cb="0"/><line nr="2" mi="3" ci="0" mb="2" cb="0"/><line nr="3" mi="1" ci="1" mb="1" cb="1"/></sourcefile></package>
<counter type="BRANCH" missed="3" covered="1"/><counter type="LINE" missed="1" covered="2"/><counter type="METHOD" missed="0" covered="1"/></report>"""


def test_parse_report_xml_covered_executable_and_ratios(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text(XML)
    parsed = coverage.parse_report(path)
    assert parsed.covered == {"p/q/A.java": [1, 3]}
    assert parsed.executable == {"p/q/A.java": [1, 2, 3]}
    assert parsed.ratios["line"] == pytest.approx(2 / 3)
    assert parsed.ratios["branch"] == pytest.approx(1 / 4)
    assert parsed.ratios["method"] == 1.0


def test_unique_lines_only_this_tc_covers():
    tcs = {"a": {"X.java": [1, 2, 3]}, "b": {"X.java": [2], "Y.java": [5]}}
    assert coverage.unique_lines(tcs) == {"a": {"X.java": [1, 3]}, "b": {"Y.java": [5]}}


def test_check_containment_class_id_and_probes():
    probes = [coverage.Probe("A#a", "CtrlA"), coverage.Probe("B#b", "CtrlB")]
    ctrl_lines = {"CtrlA": {"a/CtrlA.java": [1, 2]}, "CtrlB": {"b/CtrlB.java": [7]}}
    tc_lines = {"A#a": {"a/CtrlA.java": [1], "b/CtrlB.java": [7]}, "B#b": {"a/CtrlA.java": [2]}}
    assert [v.kind for v in coverage.check_containment({"X.java": [1, 9]}, {"X.java": [1]})] == ["containment"]
    assert coverage.check_containment({"X.java": [1]}, {"X.java": [1, 2]}) == []
    assert [v.kind for v in coverage.check_class_id({"a/B", "a/C"})] == ["classId", "classId"]
    assert sorted(v.kind for v in coverage.check_probes(tc_lines, probes, ctrl_lines)) == ["probe-cross", "probe-cross", "probe-own"]
    clean = {"A#a": {"a/CtrlA.java": [1]}, "B#b": {"b/CtrlB.java": [7]}}
    assert coverage.check_probes(clean, probes, ctrl_lines) == []


def test_junit_results_pass_fail_skip_and_display_name_recovery(tmp_path):
    from td.blackbox import junit_results
    (tmp_path / "r.xml").write_text("""<testsuite>
      <testcase classname="x.AIT" name="ok()"/>
      <testcase classname="x.AIT" name="bad()"><failure message="m"/></testcase>
      <testcase classname="x.AIT" name="err()"><error message="m"/></testcase>
      <testcase classname="x.AIT" name="skip()"><skipped/></testcase>
      <testcase classname="x.BIT" name="Shows a name (detail)"/></testsuite>""")
    src = tmp_path / "src"
    src.mkdir()
    (src / "BIT.java").write_text('class BIT {\n @Test\n @DisplayName("Shows a name (detail)")\n void realMethod() {}\n}')
    assert junit_results(tmp_path, src) == {"AIT#ok": "passed", "AIT#bad": "failed", "AIT#err": "failed",
                                            "AIT#skip": "skipped", "BIT#realMethod": "passed"}


def test_class_id_mismatches_dedup_per_class(tmp_path):
    log = tmp_path / "j.log"
    log.write_text("[WARN] Execution data for class a/B does not match.\n[WARN] Execution data for class a/B does not match.\n")
    assert coverage.class_id_mismatches(log) == {"a/B"}


def test_class_id_warnings_counted_from_jacococli_log(tmp_path):
    log = tmp_path / "j.log"
    log.write_text("[INFO] Analyzing 45 classes.\n[WARN] Execution data for class a/B does not match.\n"
                   "[WARN] Execution data for class a/C does not match.\n")
    assert coverage.count_class_id_warnings(log) == 2


def test_discover_suites_by_directory(tmp_path):
    (tmp_path / "S01" / "blackbox" / "exec").mkdir(parents=True)
    (tmp_path / "S01" / "blackbox" / "exec" / "A#a.exec").write_bytes(b"x")
    (tmp_path / "S07" / "base-1234abcd-r1" / "exec").mkdir(parents=True)
    (tmp_path / "S07" / "base-1234abcd-r1" / "exec" / "E2E_x.exec").write_bytes(b"x")
    (tmp_path / "S07" / "owl-00000000-r1" / "exec").mkdir(parents=True)  # .exec 없음: 제외
    assert sorted(coverage.discover_suites(tmp_path)) == ["blackbox", "e2e-base-1234abcd-r1"]


def test_load_results_e2e_scenario_results_plugin(tmp_path):
    import json
    gen = tmp_path / "S07" / "base-1234abcd-r1"
    gen.mkdir(parents=True)
    (gen / "scenario-results.json").write_text(json.dumps({"E2E_a#L3": "passed", "E2E_a#L9": "undefined"}))
    assert coverage.load_results(tmp_path, "e2e-base-1234abcd-r1") == {"E2E_a#L3": "passed", "E2E_a#L9": "undefined"}
    assert coverage.load_results(tmp_path, "e2e-owl-00000000-r1") == {}
