"""S00 도구 확보 로직 단위 테스트: sha256 검증, 내장 jacoco 버전 읽기, pin 기록, reps 범위, lock 조립."""
import hashlib
import io
import zipfile
from pathlib import Path

import pytest
import yaml

from td import prepare

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_fetch_verified_rejects_sha_mismatch_and_keeps_no_file(tmp_path):
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"real bytes")
    dest = tmp_path / "out" / "artifact.bin"
    with pytest.raises(prepare.PrepareError) as excinfo:
        prepare.fetch_verified(source.as_uri(), dest, expected_sha256="0" * 64)
    assert "sha256" in str(excinfo.value) and "artifact.bin" in str(excinfo.value)
    assert not dest.exists()


def test_fetch_verified_accepts_match_and_reuses_cached_file(tmp_path):
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"real bytes")
    dest = tmp_path / "artifact.copy"
    assert prepare.fetch_verified(source.as_uri(), dest, expected_sha256=_sha(b"real bytes")) == _sha(b"real bytes")
    source.unlink()  # 원본이 사라져도 sha가 맞는 캐시는 다시 받지 않는다
    assert prepare.fetch_verified(source.as_uri(), dest, expected_sha256=_sha(b"real bytes")) == _sha(b"real bytes")


def test_fetch_verified_redownloads_when_cache_is_corrupt(tmp_path):
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"good")
    dest = tmp_path / "artifact.copy"
    dest.write_bytes(b"corrupt")
    prepare.fetch_verified(source.as_uri(), dest, expected_sha256=_sha(b"good"))
    assert dest.read_bytes() == b"good"


def test_fetch_verified_without_pin_requires_record_mode(tmp_path):
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"x")
    with pytest.raises(prepare.PrepareError) as excinfo:
        prepare.fetch_verified(source.as_uri(), tmp_path / "d", expected_sha256="")
    assert "TD_PIN_RECORD" in str(excinfo.value)
    assert prepare.fetch_verified(source.as_uri(), tmp_path / "d", expected_sha256="", record=True) == _sha(b"x")


def _agent_jar(path: Path, properties: str | None, pom: str | None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        if properties is not None:
            zf.writestr("io/pjacoco/shaded/jacoco/core/jacoco.properties", properties)
        if pom is not None:
            zf.writestr("META-INF/maven/org.jacoco/org.jacoco.core/pom.properties", pom)
    return path


def test_embedded_jacoco_version_reads_jar_metadata(tmp_path):
    jar = _agent_jar(tmp_path / "a.jar", "VERSION=0.8.12.202403310830\nCOMMITID=abc\n",
                     "artifactId=org.jacoco.core\nversion=0.8.12\n")
    assert prepare.embedded_jacoco_version(jar) == "0.8.12"


def test_embedded_jacoco_version_rejects_disagreeing_metadata(tmp_path):
    jar = _agent_jar(tmp_path / "a.jar", "VERSION=0.8.12.202403310830\n", "version=0.8.11\n")
    with pytest.raises(prepare.PrepareError):
        prepare.embedded_jacoco_version(jar)


def test_embedded_jacoco_version_missing_metadata_fails(tmp_path):
    with pytest.raises(prepare.PrepareError):
        prepare.embedded_jacoco_version(_agent_jar(tmp_path / "a.jar", None, None))


@pytest.mark.parametrize("reps, ok", [(0, False), (1, True), (9, True), (10, False), (-1, False)])
def test_check_reps_range(reps, ok):
    if ok:
        prepare.check_reps(reps)
    else:
        with pytest.raises(prepare.PrepareError) as excinfo:
            prepare.check_reps(reps)
        assert "reps" in str(excinfo.value) and "1" in str(excinfo.value) and "9" in str(excinfo.value)


def test_expected_commit_mismatch_message_has_both_short_shas():
    with pytest.raises(prepare.PrepareError) as excinfo:
        prepare.check_expected_commit("b6f939355e8790202ddfc71e3f3507252745ed37",
                                      "c37b2e4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    message = str(excinfo.value)
    assert "b6f9393" in message and "c37b2e4" in message
    prepare.check_expected_commit(None, "c37b2e4aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")  # 키가 없으면 통과
    prepare.check_expected_commit("b6f939355e8790202ddfc71e3f3507252745ed37", "b6f939355e8790202ddfc71e3f3507252745ed37")


def test_record_pins_writes_sha_and_is_idempotent(tmp_path):
    pin_file = tmp_path / "tools.pin.yaml"
    original = yaml.safe_load((REPO_ROOT / "tools.pin.yaml").read_text())
    text = (REPO_ROOT / "tools.pin.yaml").read_text().replace(f"'{original['hotspot']['sha256']}'", "''")
    pin_file.write_text(text)
    assert yaml.safe_load(pin_file.read_text())["hotspot"]["sha256"] == ""
    prepare.record_pin(pin_file, "hotspot", "a" * 64)
    recorded = yaml.safe_load(pin_file.read_text())
    assert recorded["hotspot"]["sha256"] == "a" * 64
    assert recorded["pjacoco"] == original["pjacoco"]  # 다른 도구는 건드리지 않는다
    assert "# jQA 2.x의 Spring 플러그인" in pin_file.read_text()  # 주석 보존
    prepare.record_pin(pin_file, "hotspot", "a" * 64)
    with pytest.raises(prepare.PrepareError):  # 다른 값으로 덮어쓰지 않는다
        prepare.record_pin(pin_file, "hotspot", "b" * 64)


def test_committed_pin_file_is_fully_pinned():
    pin = yaml.safe_load((REPO_ROOT / "tools.pin.yaml").read_text())
    for tool in ("pjacoco", "jacococli", "jqassistant", "jqassistantSpring", "hotspot"):
        assert len(pin[tool]["sha256"]) == 64, f"{tool}: sha256 미기록(TD_PIN_RECORD=1로 S00 실행)"
    assert pin["tia"]["commit"] and pin["bbtg"]["commit"]
    assert pin["pjacoco"]["version"] == "2.0.0" and pin["jqassistant"]["version"] == "2.9.1"
    assert pin["hotspot"]["version"] == "0.1.6"


def test_resolve_model_prefers_env_override(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("llm:\n  model: claude-opus-5-5\n")
    monkeypatch.delenv("TD_LLM_MODEL", raising=False)
    assert prepare.resolve_model(config) == "claude-opus-5-5"
    monkeypatch.setenv("TD_LLM_MODEL", "claude-test-model")
    assert prepare.resolve_model(config) == "claude-test-model"


def test_parse_claude_result_requires_non_error_json():
    ok = '{"type":"result","is_error":false,"result":"OK","modelUsage":{"claude-opus-5-5":{}}}'
    assert prepare.parse_claude_result(ok) == {"result": "OK", "models": ["claude-opus-5-5"]}
    for bad in ('{"is_error":true,"result":"auth"}', "not json", '{"is_error":false,"result":""}'):
        with pytest.raises(prepare.PrepareError):
            prepare.parse_claude_result(bad)


def test_claude_version_parsing():
    assert prepare.parse_claude_version("2.1.327 (Claude Code)\n") == "2.1.327"
    with pytest.raises(prepare.PrepareError):
        prepare.parse_claude_version("")
