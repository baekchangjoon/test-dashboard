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
import java.util.*;

public class Probe {
    public static void main(String[] args) {
        Map<String, Object> vars = new HashMap<>();
        vars.put("orderId", 42);
        System.out.println(DetValues.resolve(DetValues.parse("\"today+3\""), vars));
        System.out.println(DetValues.resolve(DetValues.parse("\"today-2\""), vars));
        System.out.println(DetValues.resolve(DetValues.parse("\"today\""), vars));
        System.out.println(DetValues.resolve(DetValues.parse("\"ref:orderId\""), vars));
        System.out.println(DetValues.resolve(DetValues.parse("\"uniq:case-1\""), vars));
        System.out.println(DetValues.toJson(DetValues.resolve(
            DetValues.parse("{\"a\": 1000000, \"b\": null, \"c\": true, \"d\": \"x\\\"y\\u00e9\", \"e\": 0.01, \"f\": \"ref:orderId\", \"g\": [1, \"today+0\"]}"), vars)));
        System.out.println(DetValues.text(DetValues.parse("-12")));
        System.out.println(DetValues.resolve("uniq:case-1", vars, "#prior0"));
        try {
            DetValues.resolve("ref:missing", vars);
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
    ran = subprocess.run([str(java_home / "bin" / "java"), "-cp", str(classes), "Probe"], capture_output=True,
                         text=True, timeout=120, env={"TD_SUT_TZ": zone, "PATH": "/usr/bin:/bin"})
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.splitlines()
    today = datetime.now(ZoneInfo(zone)).date()
    assert lines[0] == (today + timedelta(days=3)).isoformat()
    assert lines[1] == (today - timedelta(days=2)).isoformat()
    assert lines[2] == today.isoformat()
    assert lines[3] == "42"
    assert lines[4] == "u" + hashlib.sha1(b"case-1").hexdigest()[:10]
    assert json.loads(lines[5]) == {"a": 1000000, "b": None, "c": True, "d": "x\"yé", "e": 0.01, "f": 42,
                                    "g": [1, today.isoformat()]}
    assert re.search(r'"e":\s*0\.01', lines[5])
    assert lines[6] == "-12"
    assert lines[7] == "u" + hashlib.sha1(b"case-1#prior0").hexdigest()[:10]
    assert lines[8:] == ["MISSING-REF", "BAD-JSON"]
