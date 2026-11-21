"""det 고정 glue(Int, Gradle·JDK 필요): 렌더 결과의 배치·컴파일·dry-run(REQ-116)과 DetValues 런타임 해석."""
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_unit_detgen import _controlled  # noqa: E402

from td import scenarios  # noqa: E402
from td.detgen import derive as derive_module  # noqa: E402
from td.detgen import render as render_module  # noqa: E402


@pytest.fixture(scope="module")
def runner_classpath(tmp_path_factory) -> str:
    return scenarios.runner_classpath(tmp_path_factory.mktemp("classpath") / "classpath.txt")


def test_req116_glue_layout(tmp_path, runner_classpath):
    derivation = derive_module.derive(_controlled(tmp_path / "bundle"))
    gen_dir = tmp_path / "gen"
    render_module.render(derivation, gen_dir)
    assert scenarios.layout_violations(gen_dir) == []
    assert all(name.startswith("glue/support/") for name in scenarios.glue_files(gen_dir))
    result = scenarios.validate_generation(gen_dir, tmp_path / "validate", classpath=runner_classpath)
    assert result.compile.excluded == [], result.compile.compiler_output
    assert result.dry_run.undefined_steps == []
    assert result.dry_run.pickle_count == len(derivation.cases)
    # dry-run은 undefined만 따로 센다. 모호한(ambiguous) step도 없어야 한다(모든 step이 정확히 하나의 정의에 맞는다)
    statuses = {step["result"]["status"] for feature in json.loads(result.dry_run.json_path.read_text(encoding="utf-8"))
                for element in feature["elements"] for step in element["steps"]}
    assert statuses <= {"passed", "skipped"}, statuses
    assert render_module.glue_checksum(gen_dir / "glue") == render_module.glue_checksum()


_PROBE = r"""
import glue.support.DetValues;
import java.time.ZoneId;
import java.util.*;

public class Probe {
    public static void main(String[] args) {
        Map<String, Object> vars = new HashMap<>();
        vars.put("orderId", 42);
        ZoneId zone = DetValues.zone(args[0]);
        System.out.println(DetValues.resolve(DetValues.parse("\"today+3\""), vars, zone));
        System.out.println(DetValues.resolve(DetValues.parse("\"today-2\""), vars, zone));
        System.out.println(DetValues.resolve(DetValues.parse("\"today\""), vars, zone));
        System.out.println(DetValues.resolve(DetValues.parse("\"ref:orderId\""), vars, zone));
        System.out.println(DetValues.resolve(DetValues.parse("\"uniq:case-1\""), vars, zone));
        System.out.println(DetValues.toJson(DetValues.resolve(
            DetValues.parse("{\"a\": 1000000, \"b\": null, \"c\": true, \"d\": \"x\\\"y\\u00e9\", \"e\": 0.01, \"f\": \"ref:orderId\", \"g\": [1, \"today+0\"]}"), vars, zone)));
        System.out.println(DetValues.text(DetValues.parse("-12")));
        System.out.println(DetValues.resolve("uniq:case-1", vars, "#prior0", zone));
        try {
            DetValues.resolve("today+1", vars, null);
            System.out.println("NO-ERROR");
        } catch (IllegalStateException expected) {
            System.out.println("NO-ZONE");
        }
        for (String bad : new String[] {"", "Not/AZone"}) {
            try {
                DetValues.zone(bad);
                System.out.println("NO-ERROR");
            } catch (IllegalStateException expected) {
                System.out.println("BAD-ZONE");
            }
        }
        System.out.println(DetValues.resolve("uniq:case-1", vars, null));
        try {
            DetValues.resolve("ref:missing", vars, zone);
            System.out.println("NO-ERROR");
        } catch (IllegalStateException expected) {
            System.out.println("MISSING-REF");
        }
        try {
            DetValues.parse("{\"a\": }");
            System.out.println("NO-ERROR");
        } catch (IllegalArgumentException expected) {
            System.out.println("BAD-JSON");
        }
    }
}
"""


def test_det_values_runtime(tmp_path):
    java_home = Path(scenarios.java_home(17))
    probe = tmp_path / "Probe.java"
    probe.write_text(_PROBE, encoding="utf-8")
    classes = tmp_path / "classes"
    compiled = subprocess.run([str(java_home / "bin" / "javac"), "-encoding", "UTF-8", "-d", str(classes),
                               str(render_module.GLUE_DIR / "support" / "DetValues.java"), str(probe)],
                              capture_output=True, text=True, timeout=300)
    assert compiled.returncode == 0, compiled.stderr
    zone = "America/New_York"
    before = datetime.now(ZoneInfo(zone)).date()
    # 타임존은 인자(=feature Background 값)로만 받는다. 환경변수 기본값은 없다(TZ를 다른 값으로 두어 섞이지 않음을 본다)
    ran = subprocess.run([str(java_home / "bin" / "java"), "-cp", str(classes), "Probe", zone], capture_output=True,
                         text=True, timeout=120, env={"TZ": "Asia/Tokyo", "PATH": "/usr/bin:/bin"})
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.splitlines()
    after = datetime.now(ZoneInfo(zone)).date()
    # 자정 경계: Java가 본 오늘은 실행 전 또는 실행 후의 오늘 중 하나다
    today = next((day for day in (before, after) if lines[2] == day.isoformat()), None)
    assert today is not None, (lines[2], before, after)
    assert lines[0] == (today + timedelta(days=3)).isoformat()
    assert lines[1] == (today - timedelta(days=2)).isoformat()
    assert lines[3] == "42"
    assert lines[4] == "u" + hashlib.sha1(b"case-1").hexdigest()[:10]
    assert json.loads(lines[5]) == {"a": 1000000, "b": None, "c": True, "d": "x\"yé", "e": 0.01, "f": 42,
                                    "g": [1, today.isoformat()]}
    assert re.search(r'"e":\s*0\.01', lines[5])
    assert lines[6] == "-12"
    assert lines[7] == "u" + hashlib.sha1(b"case-1#prior0").hexdigest()[:10]
    assert lines[8:12] == ["NO-ZONE", "BAD-ZONE", "BAD-ZONE", "u" + hashlib.sha1(b"case-1").hexdigest()[:10]]
    assert lines[12:] == ["MISSING-REF", "BAD-JSON"]


def test_det_glue_has_no_default_timezone():
    # I1: glue에 하드코딩 기본 타임존이나 환경변수 경로가 없다(Background step으로만 정한다)
    sources = "".join(path.read_text(encoding="utf-8") for path in render_module.GLUE_DIR.rglob("*.java"))
    assert "Asia/Seoul" not in sources and "TD_SUT_TZ" not in sources and "getenv" not in sources
    assert '@Given("^the SUT timezone is' in sources
