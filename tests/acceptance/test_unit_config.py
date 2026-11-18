"""SUT 설명 파일 수용 테스트(Unit): REQ-072(설명 파일 값이 인자 조립에 반영됨)와 스키마 검증."""
import copy
import shutil
from pathlib import Path

import pytest
import yaml

from td import sut_config

REPO_ROOT = Path(__file__).resolve().parents[2]
PETCLINIC = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"


def _variant(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(PETCLINIC.read_text())
    data = copy.deepcopy(data)
    mutate(data)
    path = tmp_path / "sut.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def test_petclinic_descriptor_loads_all_design_keys():
    config = sut_config.load(PETCLINIC)
    assert config.name == "petclinic"
    assert config.expected_commit == "b6f939355e8790202ddfc71e3f3507252745ed37"
    assert config.java == 17 and config.port == 8080 and config.health == "/actuator/health"
    assert config.build_cmd.startswith("./gradlew --no-daemon")
    assert config.jar_glob == "build/libs/spring-petclinic-*-SNAPSHOT.jar"
    assert config.auth_probe == ("GET", "/api/vets")
    assert config.auth_unauthenticated_status == 403
    assert [probe.test for probe in config.coverage_probes] == [
        "VetApiBlackBoxIT#listAllVets", "OwnerApiBlackBoxIT#listAllOwners"]
    assert config.tia_range() == ("HEAD~10", "HEAD")
    assert config.sonar_project_key == "spring-petclinic-td"


def test_req072_descriptor_driven(tmp_path):
    def mutate(data):
        data["tia"] = {"range": "v1.0..v2.0", "first_parent": False}
        data["sonar"]["projectKey"] = "custom-key"
        data["api"]["include"] = "/v2/**"
        data["runtime"]["ddl"] = "db/custom/schema.sql"
        data["auth"]["probe"] = "GET /api/owners"
        data["auth"]["unauthenticated_status"] = 401
        data["classes"] = "out/classes"
        data["blackbox"]["props"] = {"custom.base": "{baseUrl}/x", "custom.ctl": "{controlUrl}", "plain": "1"}
        data["compare"] = {"focus": "org.example.focus.*"}

    config = sut_config.load(_variant(tmp_path, mutate))
    assert config.tia_range() == ("v1.0", "v2.0")
    assert config.tia_first_parent is False
    assert config.bbtg_ddl() == Path("db/custom/schema.sql")
    assert config.bbtg_ddl(Path("/src")) == Path("/src/db/custom/schema.sql")
    assert config.api_include == "/v2/**"
    assert config.auth_probe == ("GET", "/api/owners")
    assert config.auth_unauthenticated_status == 401
    assert config.classes_dir(Path("/src")) == Path("/src/out/classes")
    assert config.compare_focus == "org.example.focus.*"
    sonar = config.sonar_args("/tmp/jacoco.xml", "http://sonar.test:9000")
    assert "-Dsonar.projectKey=custom-key" in sonar
    assert "-Dsonar.host.url=http://sonar.test:9000" in sonar
    assert "-Dsonar.coverage.jacoco.xmlReportPaths=/tmp/jacoco.xml" in sonar
    assert not any("token" in arg.lower() for arg in sonar), "토큰은 인자가 아니라 환경 변수로만 넘긴다"
    assert config.sonar_args("/x.xml", "http://h", project_key="custom-key-test-abc")[0] == \
        "-Dsonar.projectKey=custom-key-test-abc"
    assert sorted(config.blackbox_args("http://127.0.0.1:1234", "http://127.0.0.1:5678")) == sorted([
        "-Dcustom.base=http://127.0.0.1:1234/x", "-Dcustom.ctl=http://127.0.0.1:5678", "-Dplain=1"])


def test_blackbox_args_default_petclinic_props():
    config = sut_config.load(PETCLINIC)
    assert config.blackbox_args("http://127.0.0.1:1111", "http://127.0.0.1:2222") == [
        "-Dpetclinic.base-url=http://127.0.0.1:1111", "-Dpjacoco.control-url=http://127.0.0.1:2222"]


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.pop("sonar"), "sonar"),
    (lambda d: d["auth"].update(unauthenticated_status=500), "unauthenticated_status"),
    (lambda d: d["tia"].update(range="HEAD~10"), "range"),
    (lambda d: d.update(expected_commit="b6f9393"), "expected_commit"),
    (lambda d: d.update(surprise=1), "surprise"),
    (lambda d: d["build"].update(cmd="./gradlew bootJar"), "--no-daemon"),
    (lambda d: d["coverage"].update(probes=[]), "probes"),
])
def test_invalid_descriptor_is_rejected_with_key_in_message(tmp_path, mutate, needle):
    with pytest.raises(sut_config.SutConfigError) as excinfo:
        sut_config.load(_variant(tmp_path, mutate))
    assert needle in str(excinfo.value)


def test_expected_commit_is_optional(tmp_path):
    config = sut_config.load(_variant(tmp_path, lambda d: d.pop("expected_commit")))
    assert config.expected_commit is None


def test_cli_get_prints_scalar_for_bash(tmp_path):
    import subprocess, sys, os
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "site-gen")}
    out = subprocess.run([sys.executable, "-m", "td.sut_config", "get", str(PETCLINIC), "build.cmd"],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0 and out.stdout.strip() == "./gradlew --no-daemon -q bootJar -x test"
    bad = subprocess.run([sys.executable, "-m", "td.sut_config", "get", str(PETCLINIC), "no.such.key"],
                         capture_output=True, text=True, env=env)
    assert bad.returncode != 0
