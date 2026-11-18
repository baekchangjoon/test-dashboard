"""SUT 설명 파일(suts/<name>/sut.yaml) 로더와 인자 조립 함수(설계 §6.0).

각 단계는 SUT별 값을 코드에 박지 않고 이 모듈이 조립한 값만 쓴다(REQ-072).
검증은 schemas/sut.schema.json으로 하고, 오류 메시지에는 문제가 된 키 경로를 넣는다.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).parent / "schemas" / "sut.schema.json"


DEFAULT_TEST_SOURCES = "src/test/java"


class SutConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CoverageProbe:
    test: str
    controller: str


@dataclass(frozen=True)
class SutConfig:
    name: str
    repo: str
    ref: str
    java: int
    build_system: str
    build_cmd: str
    jar_glob: str
    classes: str
    sources: str
    packages: str
    runtime_profile: str
    runtime_db: str
    runtime_ddl: str
    port: int
    health: str
    api_include: str
    auth_type: str
    auth_login: str
    auth_user_env: str
    auth_pass_env: str
    auth_probe_spec: str
    auth_unauthenticated_status: int
    coverage_probes: tuple[CoverageProbe, ...]
    blackbox_cmd: str
    blackbox_props: dict[str, str]
    blackbox_junit_xml: str
    blackbox_test_sources: str
    tia_range_spec: str
    tia_first_parent: bool
    sonar_project_key: str
    sonar_cmd_build: str
    sonar_cmd_scan: str
    expected_commit: str | None = None
    compare_focus: str | None = None
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    # --- 인자 조립 ---------------------------------------------------------------------
    def blackbox_args(self, base_url: str, control_url: str) -> list[str]:
        """blackbox.props의 `{baseUrl}`, `{controlUrl}`을 치환해 `-D<key>=<value>` 목록으로 만든다."""
        values = {"{baseUrl}": base_url, "{controlUrl}": control_url}
        args = []
        for key, template in self.blackbox_props.items():
            for placeholder, replacement in values.items():
                template = template.replace(placeholder, replacement)
            args.append(f"-D{key}={template}")
        return args

    def sonar_args(self, xml: str, host: str, project_key: str | None = None) -> list[str]:
        """Sonar 스캔 인자. 토큰은 인자가 아니라 환경 변수(SONAR_TOKEN)로만 넘긴다."""
        return [
            f"-Dsonar.projectKey={project_key or self.sonar_project_key}",
            f"-Dsonar.host.url={host}",
            f"-Dsonar.coverage.jacoco.xmlReportPaths={xml}",
        ]

    def tia_range(self) -> tuple[str, str]:
        base_ref, _, head_ref = self.tia_range_spec.partition("..")
        return base_ref, head_ref

    def bbtg_ddl(self, src_dir: Path | None = None) -> Path:
        ddl = Path(self.runtime_ddl)
        return Path(src_dir) / ddl if src_dir else ddl

    def classes_dir(self, src_dir: Path) -> Path:
        return Path(src_dir) / self.classes

    def sources_dir(self, src_dir: Path) -> Path:
        return Path(src_dir) / self.sources

    @property
    def auth_probe(self) -> tuple[str, str]:
        method, _, path = self.auth_probe_spec.partition(" ")
        return method, path

    @property
    def auth_login_request(self) -> tuple[str, str]:
        method, _, path = self.auth_login.partition(" ")
        return method, path


def _validate(data, source: Path) -> None:
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.absolute_path))
    if errors:
        lines = []
        for err in errors:
            where = ".".join(str(part) for part in err.absolute_path) or "<root>"
            lines.append(f"{where}: {err.message}")
        raise SutConfigError(f"{source}: " + "; ".join(lines))


def _extra_rules(data: dict, source: Path) -> None:
    build_cmds = {"build.cmd": data["build"]["cmd"], "blackbox.cmd": data["blackbox"]["cmd"],
                  "sonar.cmd_build": data["sonar"]["cmd_build"], "sonar.cmd_scan": data["sonar"]["cmd_scan"]}
    for key, cmd in build_cmds.items():
        if "gradlew" in cmd and "--no-daemon" not in cmd:
            raise SutConfigError(f"{source}: {key}: Gradle 호출에는 --no-daemon이 있어야 한다: {cmd!r}")


def load(path) -> SutConfig:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise SutConfigError(f"{path}: 읽을 수 없다: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SutConfigError(f"{path}: YAML 파싱 실패: {exc}") from exc
    if not isinstance(data, dict):
        raise SutConfigError(f"{path}: 최상위가 매핑이 아니다")
    _validate(data, path)
    _extra_rules(data, path)
    data["blackbox"].setdefault("test_sources", DEFAULT_TEST_SOURCES)  # 선택 키의 기본값(sut_config get에서도 보이게)
    return SutConfig(
        name=data["name"], repo=data["repo"], ref=data["ref"], java=data["java"],
        build_system=data["build"]["system"], build_cmd=data["build"]["cmd"],
        jar_glob=data["jar"], classes=data["classes"], sources=data["sources"], packages=data["packages"],
        runtime_profile=data["runtime"]["profile"], runtime_db=data["runtime"]["db"],
        runtime_ddl=data["runtime"]["ddl"], port=data["port"], health=data["health"],
        api_include=data["api"]["include"],
        auth_type=data["auth"]["type"], auth_login=data["auth"]["login"],
        auth_user_env=data["auth"]["user_env"], auth_pass_env=data["auth"]["pass_env"],
        auth_probe_spec=data["auth"]["probe"],
        auth_unauthenticated_status=data["auth"]["unauthenticated_status"],
        coverage_probes=tuple(CoverageProbe(p["test"], p["controller"]) for p in data["coverage"]["probes"]),
        blackbox_cmd=data["blackbox"]["cmd"], blackbox_props=dict(data["blackbox"]["props"]),
        blackbox_junit_xml=data["blackbox"]["junit_xml"],
        blackbox_test_sources=data["blackbox"].get("test_sources", DEFAULT_TEST_SOURCES),
        tia_range_spec=data["tia"]["range"], tia_first_parent=bool(data["tia"].get("first_parent", True)),
        sonar_project_key=data["sonar"]["projectKey"], sonar_cmd_build=data["sonar"]["cmd_build"],
        sonar_cmd_scan=data["sonar"]["cmd_scan"],
        expected_commit=data.get("expected_commit"),
        compare_focus=(data.get("compare") or {}).get("focus"),
        raw=data,
    )


def get_key(data: dict, dotted: str):
    cursor = data
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            raise KeyError(dotted)
        cursor = cursor[part]
    return cursor


def main(argv: list[str] | None = None) -> int:
    """`python -m td.sut_config get <sut.yaml> <dotted.key>`: 검증 후 스칼라 값을 출력한다(bash용)."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or args[0] != "get":
        print("usage: td.sut_config get <sut.yaml> <dotted.key>", file=sys.stderr)
        return 2
    try:
        config = load(args[1])
        value = get_key(config.raw, args[2])
    except SutConfigError as exc:
        print(f"sut_config: {exc}", file=sys.stderr)
        return 1
    except KeyError:
        print(f"sut_config: 키가 없다: {args[2]}", file=sys.stderr)
        return 1
    print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
