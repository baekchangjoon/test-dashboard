"""S00 prepare의 파이썬 쪽 로직: 도구 pin 읽기, sha256 검증 다운로드, tools.lock 작성, 사전 점검.

외부 명령(git, gradle, pip, jQA, claude) 실행은 S00-prepare.sh가 td_run으로 한다.
이 모듈은 네트워크 다운로드(urllib)와 파일·메타데이터 처리만 맡고, 실패는 PrepareError로 올린다.
CLI 진입점은 `python -m td.prepare <cmd>`이고 오류는 `prepare: <사유>`로 stderr에 쓴 뒤 종료 코드 1이다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

MAVEN_CENTRAL = "https://repo1.maven.org/maven2"
DOWNLOAD_TIMEOUT_SEC = 600
# claude 격리 호출의 고정 인자(단일 정의). S00은 `claude-argv`로 이 목록을 받아 실제 호출하고,
# tools.lock에는 같은 목록의 서술형(CLAUDE_FLAGS)을 기록한다. Task 19가 llm.sh로 옮긴다.
CLAUDE_ARGV_TEMPLATE = ["-p", "--tools", "", "--strict-mcp-config", "--mcp-config", "{mcp_config}",
                        "--setting-sources", "", "--system-prompt", "{system_prompt}",
                        "--output-format", "json", "--model", "{model}"]
CLAUDE_FLAG_NAMES = [token for token in CLAUDE_ARGV_TEMPLATE if token.startswith("-")]


def claude_argv(mcp_config: str, system_prompt: str, model: str) -> list[str]:
    return [token.format(mcp_config=mcp_config, system_prompt=system_prompt, model=model)
            for token in CLAUDE_ARGV_TEMPLATE]


def _describe_flags() -> list[str]:
    described, tokens = [], list(CLAUDE_ARGV_TEMPLATE)
    placeholder = {"{mcp_config}": "<empty-mcp-config>", "{system_prompt}": "<fixed>", "{model}": "<model>"}
    index = 0
    while index < len(tokens):
        flag = tokens[index]
        if index + 1 < len(tokens) and not tokens[index + 1].startswith("-") and flag != "-p":
            value = placeholder.get(tokens[index + 1], tokens[index + 1])
            described.append(f'{flag} {value}' if value else f'{flag} ""')
            index += 2
        else:
            described.append(flag)
            index += 1
    return described


CLAUDE_FLAGS = _describe_flags()
ARTIFACT_TOOLS = ("pjacoco", "jacococli", "jqassistant", "jqassistantSpring", "hotspot")


class PrepareError(RuntimeError):
    pass


# --- 해시와 다운로드 ------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_verified(url: str, dest: Path, expected_sha256: str, record: bool = False) -> str:
    """url을 dest로 받아 sha256을 검증하고 실제 sha256을 돌려준다.

    expected가 비어 있으면 record 모드(TD_PIN_RECORD=1)에서만 허용한다. 이미 받은 dest가 expected와 같으면 다시 받지 않는다.
    다르면(손상 캐시) 한 번 다시 받는다. 새로 받은 파일도 sha256이 다르면 PrepareError를 내고, 임시 파일만 지우며
    기존 dest는 건드리지 않는다.
    """
    dest = Path(dest)
    if not expected_sha256 and not record:
        raise PrepareError(f"{dest.name}: pin에 sha256이 없다. 첫 fetch는 TD_PIN_RECORD=1로 S00을 실행해 기록한다")
    if dest.is_file() and expected_sha256 and sha256_file(dest) == expected_sha256:
        return expected_sha256
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part{os.getpid()}")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "td-prepare"})
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SEC) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
        actual = sha256_file(tmp)
        if expected_sha256 and actual != expected_sha256:
            raise PrepareError(f"{dest.name}: sha256 불일치 (pin {expected_sha256[:12]}…, 실제 {actual[:12]}…) url={url}")
        os.replace(tmp, dest)
        return actual
    except OSError as exc:
        raise PrepareError(f"{dest.name}: 다운로드 실패 {url}: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)


def maven_url(group: str, artifact: str, version: str, classifier: str | None = None, ext: str = "jar") -> str:
    suffix = f"-{classifier}" if classifier else ""
    return f"{MAVEN_CENTRAL}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}{suffix}.{ext}"


# --- pin 파일 -------------------------------------------------------------------------------
def pin_path() -> Path:
    return Path(os.environ.get("TD_TOOLS_PIN") or Path(__file__).resolve().parents[2] / "tools.pin.yaml")


def load_pin(path: Path | None = None) -> dict:
    path = path or pin_path()
    try:
        data = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise PrepareError(f"tools.pin.yaml을 읽을 수 없다({path}): {exc}") from exc
    missing = [tool for tool in (*ARTIFACT_TOOLS, "tia", "bbtg") if tool not in (data or {})]
    if missing:
        raise PrepareError(f"tools.pin.yaml에 항목이 없다: {missing}")
    for tool in ("tia", "bbtg"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(data[tool].get("commit", ""))):
            raise PrepareError(f"tools.pin.yaml: {tool}.commit은 40자 전체 sha여야 한다(짧은 sha 접두사 금지)")
    return data


def record_pin(pin_file: Path, tool: str, sha256: str) -> None:
    """pin 파일에 sha256을 기록한다. 이미 다른 값이 있으면 덮어쓰지 않고 실패한다.

    주석을 보존하려고 YAML을 다시 덤프하지 않고 해당 도구 블록의 `sha256:` 줄만 고친다.
    """
    pin_file = Path(pin_file)
    data = yaml.safe_load(pin_file.read_text())
    current = (data.get(tool) or {}).get("sha256") or ""
    if current and current != sha256:
        raise PrepareError(f"{tool}: pin sha256({current[:12]}…)과 다르다({sha256[:12]}…). 덮어쓰지 않는다")
    if current == sha256:
        return
    lines = pin_file.read_text().splitlines(keepends=True)
    in_block = False
    for index, line in enumerate(lines):
        if re.match(r"^\S", line):
            in_block = line.startswith(f"{tool}:")
        elif in_block and re.match(r"^\s+sha256:", line):
            lines[index] = re.sub(r"sha256:.*", f"sha256: '{sha256}'", line.rstrip("\n")) + "\n"
            pin_file.write_text("".join(lines))
            return
    raise PrepareError(f"{tool}: pin 파일에 sha256 줄이 없다")


# --- 사전 점검 --------------------------------------------------------------------------------
def check_reps(reps) -> None:
    try:
        value = int(reps)
    except (TypeError, ValueError):
        raise PrepareError(f"reps가 정수가 아니다: {reps!r}") from None
    if not 1 <= value <= 9:
        raise PrepareError(f"reps는 1~9여야 한다: {value}")


def check_expected_commit(expected: str | None, resolved: str) -> None:
    if expected and expected != resolved:
        raise PrepareError(f"expected_commit 불일치: sut.yaml {expected[:7]}, 해석된 커밋 {resolved[:7]} "
                           f"(HEAD를 따라가려면 sut.yaml의 expected_commit을 지운다)")


def resolve_model(config_path: Path) -> str:
    override = os.environ.get("TD_LLM_MODEL")
    if override:
        return override
    try:
        model = yaml.safe_load(Path(config_path).read_text())["llm"]["model"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise PrepareError(f"{config_path}의 llm.model을 읽을 수 없다: {exc}") from exc
    if not isinstance(model, str) or not model:
        raise PrepareError(f"{config_path}: llm.model이 비었다")
    return model


def parse_claude_version(text: str) -> str:
    match = re.match(r"\s*(\d+\.\d+\.\d+\S*)", text or "")
    if not match:
        raise PrepareError(f"claude --version 출력을 해석할 수 없다: {text!r}")
    return match.group(1)


def check_claude_help(help_text: str) -> None:
    missing = [flag for flag in CLAUDE_FLAG_NAMES if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text)]
    if missing:
        raise PrepareError(f"claude --help에 필요한 플래그가 없다: {missing}")


def check_claude_model(parsed: dict, model: str) -> None:
    """응답 모델이 요청 모델과 같은지 확인한다. modelUsage가 비어 확인할 수 없으면 실패한다."""
    if not parsed["models"]:
        raise PrepareError("claude 응답에 modelUsage가 없어 모델을 검증할 수 없다")
    if model not in parsed["models"]:
        raise PrepareError(f"claude가 요청한 모델 {model}이 아닌 {parsed['models']}로 응답했다")


def parse_claude_result(text: str) -> dict:
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise PrepareError(f"claude 응답이 JSON이 아니다: {(text or '')[:200]!r}") from exc
    if not isinstance(data, dict) or data.get("is_error"):
        raise PrepareError(f"claude 호출이 오류를 돌려줬다: {str(data.get('result') if isinstance(data, dict) else data)[:300]}")
    result = data.get("result")
    if not isinstance(result, str) or not result.strip():
        raise PrepareError("claude 응답의 result가 비었다")
    return {"result": result.strip(), "models": sorted((data.get("modelUsage") or {}).keys())}


# --- jacoco 내장 버전 -----------------------------------------------------------------------------
JACOCO_PROPS = "io/pjacoco/shaded/jacoco/core/jacoco.properties"
JACOCO_POM = "META-INF/maven/org.jacoco/org.jacoco.core/pom.properties"


def embedded_jacoco_version(agent_jar: Path) -> str:
    """pjacoco agent jar에 내장된 jacoco-core 버전. 두 메타데이터가 모두 있어야 하고 서로 같아야 한다."""
    try:
        with zipfile.ZipFile(agent_jar) as archive:
            names = set(archive.namelist())
            props = archive.read(JACOCO_PROPS).decode() if JACOCO_PROPS in names else None
            pom = archive.read(JACOCO_POM).decode() if JACOCO_POM in names else None
    except (OSError, zipfile.BadZipFile) as exc:
        raise PrepareError(f"{agent_jar}: jar를 읽을 수 없다: {exc}") from exc
    from_props = re.search(r"^VERSION=(\d+\.\d+\.\d+)", props or "", re.M)
    from_pom = re.search(r"^version=(\S+)$", pom or "", re.M)
    if not from_props or not from_pom:
        raise PrepareError(f"{Path(agent_jar).name}: 내장 jacoco 버전 메타데이터가 없다({JACOCO_PROPS}, {JACOCO_POM})")
    if from_props.group(1) != from_pom.group(1):
        raise PrepareError(f"내장 jacoco 버전 메타데이터가 서로 다르다: {from_props.group(1)} vs {from_pom.group(1)}")
    return from_pom.group(1)


# --- 산출물 확보 ---------------------------------------------------------------------------------------
def _extract_zip_preserving_modes(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)
        for info in archive.infolist():
            mode = info.external_attr >> 16
            if mode:
                (dest / info.filename).chmod(mode)


def fetch_artifacts(pin: dict, tools_dir: Path, pin_file: Path | None = None, record: bool = False) -> dict:
    """Maven Central/GitHub release 산출물을 받아 work/tools 레이아웃으로 놓고 {tool: 정보}를 돌려준다."""
    tools_dir = Path(tools_dir)
    cache = tools_dir / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    def get(tool: str, url: str, dest: Path) -> str:
        actual = fetch_verified(url, dest, pin[tool].get("sha256") or "", record=record)
        if record and not pin[tool].get("sha256"):
            record_pin(pin_file or pin_path(), tool, actual)
            pin[tool]["sha256"] = actual
        return actual

    spec = pin["pjacoco"]
    agent = tools_dir / "pjacoco-agent.jar"
    sha = get("pjacoco", maven_url(spec["group"], spec["artifact"], spec["version"]), agent)
    results["pjacoco"] = {"version": spec["version"], "sha256": sha, "path": str(agent),
                          "coordinates": f"{spec['group']}:{spec['artifact']}:{spec['version']}"}

    embedded = embedded_jacoco_version(agent)
    expected = pin["jacococli"].get("expectedVersion")
    if expected and expected != embedded:
        raise PrepareError(f"내장 jacoco {embedded}가 pin의 jacococli.expectedVersion {expected}과 다르다")
    spec = pin["jacococli"]
    cli = tools_dir / "jacococli.jar"
    sha = get("jacococli", maven_url(spec["group"], spec["artifact"], embedded, spec.get("classifier")), cli)
    results["jacococli"] = {"version": embedded, "sha256": sha, "path": str(cli),
                            "coordinates": f"{spec['group']}:{spec['artifact']}:{embedded}:{spec.get('classifier', '')}"}
    results["jacocoCoreEmbedded"] = embedded

    spec = pin["jqassistant"]
    zip_path = cache / f"{spec['artifact']}-{spec['version']}-{spec['classifier']}.zip"
    sha = get("jqassistant", maven_url(spec["group"], spec["artifact"], spec["version"], spec["classifier"], spec["type"]),
              zip_path)
    jqa_home = tools_dir / "jqassistant"
    marker = jqa_home / ".sha256"
    if not (marker.is_file() and marker.read_text().strip() == sha and (jqa_home / "bin" / "jqassistant").is_file()):
        staging = Path(tempfile.mkdtemp(prefix="jqa-", dir=tools_dir))
        try:
            _extract_zip_preserving_modes(zip_path, staging)
            roots = [p for p in staging.iterdir() if p.is_dir()]
            if len(roots) != 1 or not (roots[0] / "bin" / "jqassistant").is_file():
                raise PrepareError("jQAssistant distribution zip의 구조가 예상과 다르다(bin/jqassistant 없음)")
            shutil.rmtree(jqa_home, ignore_errors=True)
            roots[0].rename(jqa_home)
            marker.write_text(sha + "\n")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    results["jqassistant"] = {"version": spec["version"], "sha256": sha, "path": str(jqa_home),
                              "coordinates": f"{spec['group']}:{spec['artifact']}:{spec['version']}"}

    spec = pin["jqassistantSpring"]
    plugin = tools_dir / "jqassistant-plugins" / f"{spec['artifact']}-{spec['version']}.jar"
    sha = get("jqassistantSpring", maven_url(spec["group"], spec["artifact"], spec["version"]), plugin)
    results["jqassistantSpring"] = {"version": spec["version"], "sha256": sha, "path": str(plugin),
                                    "coordinates": f"{spec['group']}:{spec['artifact']}:{spec['version']}"}

    spec = pin["hotspot"]
    hotspot = tools_dir / "hotspot.jar"
    url = f"https://github.com/{spec['repo']}/releases/download/{spec['tag']}/{spec['asset']}"
    sha = get("hotspot", url, hotspot)
    results["hotspot"] = {"version": spec["version"], "sha256": sha, "path": str(hotspot), "source": url}
    return results


# --- jQA 플러그인 확인 ------------------------------------------------------------------------------------
PLUGIN_LINE = re.compile(r"PluginRepositoryImpl - (jQAssistant .+? Plugin) (\S+) \[([^\]]+)\]")


def parse_jqa_plugins(text: str) -> list[str]:
    """`jqassistant effective-configuration` 출력에서 로딩된 플러그인 목록(이름 버전)을 뽑는다."""
    return [f"{name} {version}" for name, version, _plugin_id in PLUGIN_LINE.findall(text)]


def jqa_verify_config(pin: dict) -> str:
    spec = pin["jqassistantSpring"]
    return yaml.safe_dump({"jqassistant": {"plugins": [
        {"group-id": spec["group"], "artifact-id": spec["artifact"], "version": spec["version"]}]}}, sort_keys=False)


def check_jqa_spring_plugin(plugins: list[str], pin: dict) -> None:
    wanted = f"Spring Plugin {pin['jqassistantSpring']['version']}"
    if not any(wanted in plugin for plugin in plugins):
        raise PrepareError(f"jQA가 Spring 플러그인 {pin['jqassistantSpring']['version']}을 로딩하지 못했다. 로딩된 목록: {plugins}")


def resolved_plugin_jar(spec: dict, repo: Path) -> Path:
    return (Path(repo) / spec["group"].replace(".", "/") / spec["artifact"] / spec["version"]
            / f"{spec['artifact']}-{spec['version']}.jar")


def check_resolved_plugin_jar(spec: dict, expected_sha: str, repo: Path) -> str:
    """jQA가 실제로 로딩하는 플러그인 jar(전용 로컬 저장소)가 있고 pin한 sha256과 같은지 확인한다. 아니면 실패한다."""
    jar = resolved_plugin_jar(spec, repo)
    if not jar.is_file():
        raise PrepareError(f"jQA가 해석한 Spring 플러그인 jar를 찾지 못해 검증할 수 없다: {jar}")
    actual = sha256_file(jar)
    if actual != expected_sha:
        raise PrepareError(f"jQA가 로딩하는 Spring 플러그인 jar의 sha256이 pin과 다르다({actual[:12]}… vs {expected_sha[:12]}…)")
    return str(jar)


# --- tools.lock ---------------------------------------------------------------------------------------------
def build_lock(pin: dict, artifacts: dict, *, run_id: str, sut_name: str, sut_commit: str, tia_commit: str,
               bbtg_commit: str, bbtg_requirements_sha256: str, claude_version: str, model: str,
               jqa_plugins: list[str], jqa_resolved_jar: str, jqa_spring_verified: bool, claude_verified: bool,
               python_version: str) -> dict:
    lock = {
        "schema": 1,
        "runId": run_id,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sut": {"name": sut_name, "commit": sut_commit},
        "pjacoco": artifacts["pjacoco"],
        "jacocoCoreEmbedded": artifacts["jacocoCoreEmbedded"],
        "jacococli": artifacts["jacococli"],
        "jqassistant": artifacts["jqassistant"],
        "jqassistantSpring": {**artifacts["jqassistantSpring"], "plugins": jqa_plugins,
                              "resolvedJar": jqa_resolved_jar, "verified": jqa_spring_verified},
        "hotspot": artifacts["hotspot"],
        "tia": {"repo": pin["tia"]["repo"], "commit": tia_commit, "jdk": pin["tia"]["jdk"],
                "gradleTask": pin["tia"]["gradleTask"], "version": tia_commit[:7], "sha256": None},
        "bbtg": {"repo": pin["bbtg"]["repo"], "commit": bbtg_commit, "python": python_version,
                 "requirementsSha256": bbtg_requirements_sha256, "version": bbtg_commit[:7], "sha256": None},
        "libraries": dict(pin.get("libraries") or {}),
        "claude": {"version": claude_version, "model": model, "flags": list(CLAUDE_FLAGS), "verified": claude_verified},
        "model": model,
    }
    for tool in ("tia", "bbtg"):
        if lock[tool]["commit"] != pin[tool]["commit"]:
            raise PrepareError(f"{tool}: 체크아웃 커밋 {lock[tool]['commit']}이 pin {pin[tool]['commit']}과 다르다")
    return lock


def write_lock(run_dir: Path, lock: dict) -> Path:
    """run별 tools.lock을 쓴다(읽기 전용 0444). 같은 run에서 S00을 다시 돌려 이미 있으면
    generatedAt을 뺀 내용이 같을 때만 그대로 두고, 다르면 불변 위반으로 실패한다."""
    path = Path(run_dir) / "tools.lock"
    if path.exists():
        existing = yaml.safe_load(path.read_text())
        strip = lambda data: {k: v for k, v in data.items() if k != "generatedAt"}
        if strip(existing) != strip(lock):
            raise PrepareError(f"tools.lock이 이미 있고 내용이 다르다(불변이라 덮어쓰지 않는다): {path}")
        return path
    path.write_text("# run별 도구 잠금(불변 사본). 기준은 tools.pin.yaml이다.\n" + yaml.safe_dump(lock, sort_keys=False, allow_unicode=True))
    path.chmod(0o444)
    return path


# --- CLI ------------------------------------------------------------------------------------------------------
def _cmd_pin_get(args) -> int:
    value = load_pin()
    for part in args.key.split("."):
        value = value[part]
    print(value)
    return 0


def _cmd_fetch(args) -> int:
    pin = load_pin()
    record = os.environ.get("TD_PIN_RECORD") == "1"
    print(json.dumps(fetch_artifacts(pin, Path(args.tools_dir), record=record), indent=2))
    return 0


def _cmd_check_reps(args) -> int:
    options = json.loads((Path(args.run_dir) / "run.json").read_text()).get("options", {})
    check_reps(options.get("reps", 1))
    return 0


def _cmd_check_expected(args) -> int:
    from td import sut_config
    check_expected_commit(sut_config.load(args.sut_file).expected_commit, args.commit)
    return 0


def _cmd_model(args) -> int:
    print(resolve_model(Path(args.config)))
    return 0


def _cmd_claude_version(args) -> int:
    print(parse_claude_version(Path(args.file).read_text()))
    return 0


def _cmd_claude_help(args) -> int:
    check_claude_help(Path(args.file).read_text())
    return 0


def _cmd_claude_result(args) -> int:
    parsed = parse_claude_result(Path(args.file).read_text())
    if args.model:
        check_claude_model(parsed, args.model)
    print(json.dumps(parsed, ensure_ascii=False))
    return 0


def _cmd_claude_argv(args) -> int:
    sys.stdout.write("".join(token + "\0" for token in claude_argv(args.mcp_config, args.system_prompt, args.model)))
    return 0


def _cmd_jqa_config(args) -> int:
    print(jqa_verify_config(load_pin()), end="")
    return 0


def _cmd_jqa_plugins(args) -> int:
    plugins = parse_jqa_plugins(Path(args.file).read_text())
    pin = load_pin()
    check_jqa_spring_plugin(plugins, pin)
    resolved = check_resolved_plugin_jar(pin["jqassistantSpring"], pin["jqassistantSpring"]["sha256"], Path(args.repo))
    print(json.dumps({"plugins": plugins, "resolvedJar": resolved, "verified": True}))
    return 0


def _cmd_write_lock(args) -> int:
    pin = load_pin()
    artifacts = json.loads(Path(args.artifacts).read_text())
    jqa = json.loads(Path(args.jqa_plugins).read_text())
    lock = build_lock(
        pin, artifacts, run_id=args.run_id, sut_name=args.sut, sut_commit=args.sut_commit,
        tia_commit=args.tia_commit, bbtg_commit=args.bbtg_commit,
        bbtg_requirements_sha256=args.bbtg_requirements_sha256, claude_version=args.claude_version,
        model=args.model, jqa_plugins=jqa["plugins"], jqa_resolved_jar=jqa["resolvedJar"],
        jqa_spring_verified=jqa.get("verified") is True, claude_verified=args.claude_verified == "true",
        python_version=args.python_version)
    path = write_lock(Path(args.run_dir), lock)
    print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.prepare")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, func, *arguments, **options):
        cmd = sub.add_parser(name)
        for arg in arguments:
            cmd.add_argument(arg)
        for flag, required in options.items():
            cmd.add_argument("--" + flag.replace("_", "-"), required=bool(required))
        cmd.set_defaults(func=func)

    add("pin-get", _cmd_pin_get, "key")
    add("fetch-artifacts", _cmd_fetch, "tools_dir")
    add("check-reps", _cmd_check_reps, "run_dir")
    add("check-expected-commit", _cmd_check_expected, "sut_file", "commit")
    add("model", _cmd_model, "config")
    add("claude-version", _cmd_claude_version, "file")
    add("claude-help", _cmd_claude_help, "file")
    add("claude-result", _cmd_claude_result, "file", model=False)
    add("claude-argv", _cmd_claude_argv, mcp_config=True, system_prompt=True, model=True)
    add("jqa-config", _cmd_jqa_config)
    add("jqa-plugins", _cmd_jqa_plugins, "file", repo=True)
    add("write-lock", _cmd_write_lock, run_dir=True, run_id=True, sut=True, sut_commit=True, artifacts=True,
        tia_commit=True, bbtg_commit=True, bbtg_requirements_sha256=True, claude_version=True, model=True,
        jqa_plugins=True, python_version=True, claude_verified=True)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (PrepareError, KeyError, OSError, ValueError) as exc:
        print(f"prepare: {type(exc).__name__ + ': ' if not isinstance(exc, PrepareError) else ''}{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
