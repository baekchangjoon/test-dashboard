"""td.hotspot 단위 테스트: 설정 렌더링, 윈도우 계산, top10 추출."""
import json
from pathlib import Path

import pytest
import yaml

from td import hotspot

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "suts" / "petclinic" / "hotspot.yml.tmpl"


def _render(tmp_path, **overrides):
    values = dict(target=tmp_path / "src", sources="src/main/java", since="2025-08-07", until="2026-08-08",
                  classpath_dirs=[tmp_path / "classes", tmp_path / "libs"], jacoco_xml=tmp_path / "merged.xml", output=tmp_path / "out")
    values.update(overrides)
    return yaml.safe_load(hotspot.render_config(TEMPLATE, **values))


def test_render_with_jacoco_has_absolute_paths(tmp_path):
    config = _render(tmp_path)
    analysis = config["analysis"]
    assert analysis["jacocoReportPath"] == str(tmp_path / "merged.xml")
    assert analysis["target"]["path"] == str(tmp_path / "src")
    assert analysis["window"] == {"since": "2025-08-07", "until": "2026-08-08"}
    assert analysis["scope"]["include"] == ["src/main/java/**/*.java"]
    assert analysis["apiAnalysis"]["enabled"] is True and analysis["apiAnalysis"]["sharedComponentMode"] == "BOTH"
    assert analysis["apiAnalysis"]["classpathDirectories"] == [str(tmp_path / "classes"), str(tmp_path / "libs")]
    assert config["output"]["path"] == str(tmp_path / "out")


def test_render_without_jacoco_omits_path_line(tmp_path):
    config = _render(tmp_path, jacoco_xml=None)
    assert "jacocoReportPath" not in config["analysis"]


def test_window_anchors_on_commit_date():
    assert hotspot.window_for("2026-08-07T12:46:23+09:00") == ("2025-08-07", "2026-08-08")


def test_top10_prefers_methods_and_sorts_by_score(tmp_path):
    data = {"fileHotspots": [{"path": "a/B.java", "compositeScore": 3.0}],
            "methodHotspots": [{"fqcn": "x.Y", "method": "low", "file": "a/Y.java", "compositeScore": 1.0},
                               {"fqcn": "x.Z", "method": "high", "file": "a/Z.java", "compositeScore": 9.5}]}
    (tmp_path / "hotspots.yml").write_text(yaml.safe_dump(data))
    top = hotspot.top10(tmp_path / "hotspots.yml")
    assert [row["name"] for row in top] == ["Z.high", "Y.low"]
    assert top[0] == {"name": "Z.high", "file": "a/Z.java", "method": "high", "score": 9.5}


def test_top10_falls_back_to_files_and_caps_ten(tmp_path):
    files = [{"path": f"f{i}.java", "compositeScore": float(i)} for i in range(15)]
    (tmp_path / "hotspots.yml").write_text(yaml.safe_dump({"fileHotspots": files, "methodHotspots": []}))
    top = hotspot.top10(tmp_path / "hotspots.yml")
    assert len(top) == 10 and top[0]["name"] == "f14.java" and top[0]["file"] == "f14.java" and "method" not in top[0]


def test_top10_empty_is_empty_list(tmp_path):
    (tmp_path / "hotspots.yml").write_text(yaml.safe_dump({"fileHotspots": [], "methodHotspots": []}))
    assert hotspot.top10(tmp_path / "hotspots.yml") == []


def test_render_is_valid_yaml_for_awkward_paths(tmp_path):
    config = _render(tmp_path, target=tmp_path / "a: b #c" / "src")
    assert config["analysis"]["target"]["path"] == str(tmp_path / "a: b #c" / "src")


def test_xml_problem_cases(tmp_path):
    assert hotspot.xml_problem(None) and hotspot.xml_problem(tmp_path / "none.xml")
    (tmp_path / "bad.xml").write_text("<report")
    assert "파싱" in hotspot.xml_problem(tmp_path / "bad.xml")
    (tmp_path / "empty.xml").write_text('<report name="x"></report>')
    assert "비어" in hotspot.xml_problem(tmp_path / "empty.xml")
    (tmp_path / "ok.xml").write_text('<report name="x"><package name="p"/></report>')
    assert hotspot.xml_problem(tmp_path / "ok.xml") is None
