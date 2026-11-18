"""S02 bbtg 드라이버와 정제기.

bbtg의 7개 분석 스킬 `skills/<name>/cli.py`를 bbtg 전용 venv 파이썬으로, cwd = SUT 루트에서 실행한다(LLM 호출 없음).
스킬들은 SUT 루트의 `.bbtg/artifacts/`를 서로 참조하므로 기본 경로로 만들고, 끝나면 raw로 복사한 뒤 `.bbtg/`를 지운다.

산출물(`out_dir` = `S02/bbtg`):
- `raw/`: 호출별 stdout(JSON일 때)·stderr, `.bbtg/artifacts` 복사본, `calls.json`(정제기 입력). 로컬 전용이며 게시하지 않는다.
- `clean/<skill>.json`: 허용 스키마(`bbtg_allow/<skill>.schema.json`)로 정제한 산출물. 7개 스킬당 1파일.
- `manifest.json`: 호출별 argv(SUT 루트 기준 상대), 종료 코드, 산출물, 정제 결과(제거 필드 목록과 개수).

@RestController 열거는 bbtg `common_lib` 파서(tree-sitter, bbtg venv 전용)를 import하지 않고 정규식(`^\\s*@RestController\\b`)으로 한다.
드라이버가 site-gen venv에서 돌고 bbtg 파서는 bbtg venv에만 설치돼 있기 때문이다.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

from td import proc, sut_config

SKILLS = ("inspect-stack", "scan-test-assets", "dependency-map", "find-external-calls", "inspect-auth",
          "derive-test-data", "plan-tests")
ALLOW_DIR = Path(__file__).resolve().parent / "bbtg_allow"
DEFAULT_TIMEOUT = 900
BBTG_DIRNAME = ".bbtg"
# 정제 뒤에도 남으면 안 되는 절대 경로(체크아웃 위치가 입력 해시로 새는 것을 막는다).
ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s\"'(=:\[,])/(?:Users|home|private|tmp|var|root|opt|mnt|srv)/")
SERVICE_LINE_RE = re.compile(r"\[(?:DI|Service)\]\s+([A-Za-z_][\w$]*)\.([A-Za-z_][\w$]*)")
REST_CONTROLLER_RE = re.compile(r"^\s*@RestController\b", re.MULTILINE)
# 스킬별로 clean의 원천이 되는 raw: "stdout"(JSON) 또는 "md"(Markdown 아티팩트).
CLEAN_SOURCE = {skill: "stdout" for skill in SKILLS} | {"dependency-map": "md"}


class SanitizeError(RuntimeError):
    pass


@dataclass(frozen=True)
class BbtgConfig:
    bbtg_dir: Path
    sources: str = "src/main/java"          # SUT 루트 기준 상대 경로(sut.yaml sources)
    ddl: str = "src/main/resources/db/h2/schema.sql"  # SUT 루트 기준 상대 경로(sut.yaml runtime.ddl)
    timeout: float = DEFAULT_TIMEOUT
    python: Path | None = None

    @property
    def python_bin(self) -> Path:
        return self.python or Path(self.bbtg_dir) / ".venv" / "bin" / "python"

    @classmethod
    def from_sut(cls, sut_file, bbtg_dir, timeout: float | None = None) -> "BbtgConfig":
        sut = sut_config.load(sut_file)
        return cls(bbtg_dir=Path(bbtg_dir), sources=sut.sources, ddl=sut.runtime_ddl,
                   timeout=float(os.environ.get("TD_BBTG_TIMEOUT", DEFAULT_TIMEOUT)) if timeout is None else timeout)


@dataclass
class Sanitized:
    stripped_fields: list[str] = field(default_factory=list)
    removed_counts: dict[str, int] = field(default_factory=dict)
    forbidden_declared: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    data: dict

    @property
    def status(self) -> str:
        return self.data["status"]

    @property
    def reason(self) -> str | None:
        return self.data.get("reason")

    @property
    def calls(self) -> list[dict]:
        return self.data["calls"]


# --- 열거 ---------------------------------------------------------------------------------------
def enumerate_controllers(src: Path, sources: str) -> list[str]:
    """`@RestController`가 붙은 .java 파일을 SUT 루트 기준 상대 경로로 정렬해 돌려준다."""
    found = []
    for path in sorted((Path(src) / sources).rglob("*.java")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if REST_CONTROLLER_RE.search(text):
            found.append(path.relative_to(src).as_posix())
    return found


def _class_index(src: Path, sources: str) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for path in sorted((Path(src) / sources).rglob("*.java")):
        index.setdefault(path.stem, []).append(path.relative_to(src).as_posix())
    return index


def service_methods(dependency_map_md: str) -> list[tuple[str, str]]:
    """dependency-map 의존성 트리에서 `[DI]`/`[Service]` 항목(Class, method)을 순서대로 중복 없이 뽑는다."""
    seen: dict[tuple[str, str], None] = {}
    for match in SERVICE_LINE_RE.finditer(dependency_map_md):
        seen.setdefault((match.group(1), match.group(2)), None)
    return list(seen)


# --- 드라이버 -----------------------------------------------------------------------------------
def _artifact_files(root: Path) -> dict[str, tuple[int, int]]:
    base = root / BBTG_DIRNAME / "artifacts"
    if not base.exists():
        return {}
    return {p.relative_to(base).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(base.rglob("*")) if p.is_file()}


def _parse_first_json(text: str):
    """stdout 앞쪽의 첫 JSON 값. 뒤에 `[Artifact saved] ...` 같은 줄이 붙어도 읽는다. 없으면 None."""
    start = len(text) - len(text.lstrip())
    if not text[start:start + 1] in ("{", "["):
        return None  # 본문 중간의 "[]" 같은 조각을 JSON으로 오인하지 않는다(dependency-map은 Markdown을 stdout에 찍는다)
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


def run_all(src, out_dir, cfg: BbtgConfig) -> Manifest:
    src, out_dir = Path(src), Path(out_dir)
    raw_dir, clean_dir = out_dir / "raw", out_dir / "clean"
    for stale in (raw_dir, clean_dir):
        shutil.rmtree(stale, ignore_errors=True)
    (raw_dir / "stdout").mkdir(parents=True)
    (raw_dir / "logs").mkdir()
    shutil.rmtree(src / BBTG_DIRNAME, ignore_errors=True)  # 이전 실행의 잔재가 산출물에 섞이지 않게 한다
    calls: list[dict] = []
    skipped: list[dict] = []
    # 자식(bbtg)에는 필요한 최소 환경만 준다(TD_*, 토큰, 자격 증명 변수를 넘기지 않는다).
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
    env.update(PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
    python_bin = str(Path(cfg.python_bin).absolute())  # resolve()는 venv 심볼릭 링크를 풀어 venv를 잃는다

    def call(skill: str, call_id: str, key: str, args: list[str]) -> dict:
        cli = Path(cfg.bbtg_dir).absolute() / "skills" / skill / "cli.py"
        before = _artifact_files(src)
        stdout_path, stderr_path = raw_dir / "logs" / f"{call_id}.stdout.txt", raw_dir / "logs" / f"{call_id}.stderr.txt"
        with stdout_path.open("wb") as out_fh, stderr_path.open("wb") as err_fh:
            rc = proc.run_with_timeout(cfg.timeout, [python_bin, str(cli), *args], cwd=src, stdout=out_fh,
                                       stderr=err_fh, env=env)
        after = _artifact_files(src)
        artifacts = sorted(rel for rel, stat in after.items() if before.get(rel) != stat)
        record = {"id": call_id, "skill": skill, "key": key, "argv": [f"skills/{skill}/cli.py", *args], "rc": rc,
                  "stdout": None, "artifacts": [f"artifacts/{rel}" for rel in artifacts]}
        if rc == proc.TIMEOUT_EXIT:
            record["reason"] = f"timeout:{skill} (>{cfg.timeout:g}s)"
        elif rc != 0:
            record["reason"] = f"exit {rc}: see raw/logs/{call_id}.stderr.txt"  # stderr 본문은 절대 경로·비밀이 섞일 수 있어 옮기지 않는다
        parsed = _parse_first_json(stdout_path.read_text(encoding="utf-8", errors="replace"))
        if parsed is not None:
            json_path = raw_dir / "stdout" / f"{call_id}.json"
            json_path.write_text(json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            record["stdout"] = f"stdout/{call_id}.json"
        calls.append(record)
        return record

    try:
        call("inspect-stack", "inspect-stack", ".", ["--path", "."])
        call("scan-test-assets", "scan-test-assets", ".", ["--path", "."])
        controllers = enumerate_controllers(src, cfg.sources)
        classes = _class_index(src, cfg.sources)
        service_targets: dict[tuple[str, str], str] = {}
        for controller in controllers:
            stem = Path(controller).stem
            record = call("dependency-map", f"dependency-map-{stem}", controller, ["--file", controller])
            call("find-external-calls", f"find-external-calls-{stem}", controller, ["--file", controller])
            md_rel = f"dependency-map/{stem}.md"
            md_path = src / BBTG_DIRNAME / "artifacts" / md_rel
            if record["rc"] == 0 and md_path.exists():
                for class_name, method in service_methods(md_path.read_text(encoding="utf-8", errors="replace")):
                    files = classes.get(class_name, [])
                    if len(files) == 1:
                        service_targets.setdefault((class_name, method), files[0])
                    else:
                        skipped.append({"class": class_name, "method": method, "controller": controller,
                                        "reason": "source file not found" if not files else "ambiguous class name"})
        call("inspect-auth", "inspect-auth", ".", ["--src-root", cfg.sources, "--save-artifact",
                                                    f"{BBTG_DIRNAME}/artifacts/inspect-auth/result.json"])
        call("derive-test-data", "derive-test-data", ".", ["--project-root", ".", "--scan", cfg.sources,
                                                           "--ddl-path", cfg.ddl, "--format", "json", "--save-artifact"])
        for (class_name, method), service_file in sorted(service_targets.items()):
            call("plan-tests", f"plan-tests-{class_name}.{method}", f"{class_name}.{method}",
                 ["--file", service_file, "--method", method])
        artifacts_root = src / BBTG_DIRNAME / "artifacts"
        if artifacts_root.exists():
            shutil.copytree(artifacts_root, raw_dir / "artifacts")
    finally:
        shutil.rmtree(src / BBTG_DIRNAME, ignore_errors=True)

    (raw_dir / "calls.json").write_text(json.dumps({"calls": calls}, indent=2, sort_keys=True) + "\n")
    (raw_dir / "meta.json").write_text(json.dumps({"sutRoot": str(src)}) + "\n")  # 로컬 전용(정제기가 상대화 기준으로 쓴다)
    sanitized = sanitize(raw_dir, clean_dir, sut_root=src)
    failed = [c for c in calls if c["rc"] != 0]
    problems = [f"{c['id']}: {c.get('reason', 'failed')}" for c in failed] + sanitized.errors
    if not calls or len(failed) == len(calls):
        status, reason = "failed", "모든 bbtg 호출이 실패했다: " + "; ".join(problems[:5])
    elif problems:
        status, reason = "degraded", f"bbtg 호출 {len(failed)}건 실패, 정제 오류 {len(sanitized.errors)}건: " + "; ".join(problems[:5])
    else:
        status, reason = "passed", None
    manifest = {
        "status": status, "reason": reason, "calls": calls, "skipped": skipped,
        "controllers": controllers,
        "summary": {"total": len(calls), "failed": len(failed), "bySkill": dict(Counter(c["skill"] for c in calls))},
        "sanitize": {"strippedFields": sanitized.stripped_fields, "forbiddenDeclared": sanitized.forbidden_declared, "removedCounts": sanitized.removed_counts,
                     "errors": sanitized.errors, "written": sanitized.written},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    return Manifest(manifest)


# --- Markdown -> JSON ---------------------------------------------------------------------------
def md_to_json(text: str) -> dict:
    """제목과 표만 추출한다. 코드 블록(``` 펜스), 인용문, 문단, 목록은 버린다."""
    sections: list[dict] = []
    in_code = False
    table_lines: list[str] = []

    def flush_table():
        if len(table_lines) >= 2 and sections:
            header = _cells(table_lines[0])
            rows = [_cells(line) for line in table_lines[2:]]
            sections[-1]["tables"].append({"columns": header, "rows": rows})
        table_lines.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_table()
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if heading:
            flush_table()
            sections.append({"level": len(heading.group(1)), "heading": heading.group(2), "tables": []})
        elif stripped.startswith("|"):
            table_lines.append(stripped)
        else:
            flush_table()
    flush_table()
    return {"sections": sections}


def _cells(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [cell.strip().strip("`").strip() for cell in body.split("|")]


# --- 정제 ---------------------------------------------------------------------------------------
def load_schema(skill: str) -> dict:
    return json.loads((ALLOW_DIR / f"{skill}.schema.json").read_text(encoding="utf-8"))


def declared_forbidden_paths() -> list[str]:
    """스키마들의 `x-forbidden-paths`(넣지 않기로 한 경로 선언)를 `<skill>:<경로>`로 모은다."""
    paths = []
    for skill in SKILLS:
        paths.extend(f"{skill}:{p}" for p in load_schema(skill).get("x-forbidden-paths", []))
    return sorted(paths)


def _resolve(schema: dict, root: dict) -> dict:
    while "$ref" in schema:
        node = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def _has_value(value) -> bool:
    return value not in (None, "", [], {})


def prune(value, schema: dict, root: dict, path: str, removed: Counter):
    """스키마에 없는 키를 값과 함께 제거한다. 제거 경로(배열은 `[]`)별로 값이 있던 건수를 센다."""
    schema = _resolve(schema, root)
    if isinstance(value, dict) and ("properties" in schema or "patternProperties" in schema):
        properties = schema.get("properties", {})
        patterns = [(re.compile(p), s) for p, s in schema.get("patternProperties", {}).items()]
        result = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in properties:
                result[key] = prune(child, properties[key], root, child_path, removed)
                continue
            matched = next((s for pattern, s in patterns if pattern.search(key)), None)
            if matched is not None:
                result[key] = prune(child, matched, root, f"{path}.*" if path else "*", removed)
            elif _has_value(child):
                removed[child_path] += 1
        return result
    if isinstance(value, list) and "items" in schema:
        return [prune(item, schema["items"], root, f"{path}[]", removed) for item in value]
    return value


def _load_raw(raw_dir: Path, record: dict, kind: str):
    if kind == "md":
        md_files = [a for a in record["artifacts"] if a.endswith(".md")]
        if not md_files:
            raise ValueError("markdown artifact missing")
        return md_to_json((raw_dir / md_files[0]).read_text(encoding="utf-8", errors="replace"))
    if not record.get("stdout"):
        raise ValueError("stdout JSON missing")
    return json.loads((raw_dir / record["stdout"]).read_text(encoding="utf-8"))


def _relativize(value, roots: list[str]):
    """SUT 루트(경로 경계에서만)를 걷어낸다: `<root>/x` -> `x`, `<root>` -> `.`. `<root>foo` 같은 접두 일치는 건드리지 않는다."""
    if isinstance(value, dict):
        return {key: _relativize(child, roots) for key, child in value.items()}
    if isinstance(value, list):
        return [_relativize(child, roots) for child in value]
    if isinstance(value, str):
        for root in roots:
            pattern = re.compile(r"(?<![\w.\-/])" + re.escape(root) + r"(/|(?![\w.\-]))")
            value = pattern.sub(lambda m: "" if m.group(1) == "/" else ".", value)
        return value
    return value


def _find_absolute(value, path: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            found = _find_absolute(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_absolute(child, f"{path}[{index}]")
            if found:
                return found
    elif isinstance(value, str) and ABSOLUTE_PATH_RE.search(value):
        return path
    return None


def _roots(sut_root: Path) -> list[str]:
    candidates = {str(sut_root), str(Path(sut_root).resolve()), os.path.realpath(sut_root)}
    return sorted(candidates, key=len, reverse=True)


# --- 정제 관문(fail closed) ---------------------------------------------------------------------
EXPRESSION_CHARS = set("(){};=<>!&|+*\"'")
A1_MIN_LENGTH = 12
PATH_SHAPE_RE = re.compile(r"^/[\w\-./{}*?&=%:,]+$")  # HTTP 경로(질의 문자열 포함)는 식별자다
TYPE_SHAPE_RE = re.compile(r"^[\w.$<>\[\],? ]+$")
# user=/username=은 URL·JDBC 질의 문맥(`?`, `&`, `;` 뒤)에서만 본다: bbtg가 만드는 "username=admin 경로" 같은 분기 설명은 자격 증명이 아니다.
CREDENTIAL_RE = re.compile(r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key)\s*=|[?&;]\s*(?:user(?:name)?|uid)\s*=|://[^/\s:@]+:[^/\s@]*@")
# 사람이 쓴 테스트 표시 이름(@DisplayName 문장)은 메타데이터라서 A1 관문에서 뺀다(설계 6.6: scan-test-assets 메타데이터는 포함).
A1_EXEMPT_SUFFIXES = (".display_name",)


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def source_corpus(sut_root: Path) -> str:
    """SUT의 src/** 아래 .java 전부를 공백 정규화해 이어 붙인다(A1 관문용). 루트가 없으면 빈 문자열이다."""
    sut_root = Path(sut_root)
    if not sut_root.is_dir():
        return ""
    parts = []
    for path in sorted(sut_root.rglob("*.java")):
        rel = path.relative_to(sut_root).parts
        if "src" in rel and not {"build", ".gradle", BBTG_DIRNAME} & set(rel):
            parts.append(_normalize_ws(path.read_text(encoding="utf-8", errors="replace")))
    return "\n".join(parts)


def _string_leaves(node, path: str = ""):
    if isinstance(node, dict):
        for key, child in node.items():
            yield from _string_leaves(child, f"{path}.{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _string_leaves(child, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def a1_violations(document, corpus: str) -> list[str]:
    """식 문자(`(){};=<>!&|+*"'`)를 포함하는 12자 이상 문자열이 SUT 소스에 그대로(공백 정규화) 있으면 그 JSON 경로를 돌려준다.
    식별자(HTTP 경로, 제네릭 타입 표기)는 허용한다."""
    if not corpus:
        return []
    found = []
    for path, text in _string_leaves(document):
        if len(text) < A1_MIN_LENGTH or not EXPRESSION_CHARS & set(text) or path.endswith(A1_EXEMPT_SUFFIXES):
            continue
        if PATH_SHAPE_RE.match(text) or (EXPRESSION_CHARS & set(text) <= {"<", ">"} and TYPE_SHAPE_RE.match(text)):
            continue
        if _normalize_ws(text) in corpus:
            found.append(path)
    return found


def credential_violations(document) -> list[str]:
    return [path for path, text in _string_leaves(document) if CREDENTIAL_RE.search(text)]


def _derive_flags(data):
    """derive-test-data: 어노테이션 식 문자열(where/delete SQL, formula)은 지우고 존재 여부만 불리언으로 남긴다."""
    if not isinstance(data, list):
        return data
    for entity in data:
        if isinstance(entity, dict):
            entity["has_where_clause"] = bool(entity.get("where_clause"))
            entity["has_sql_delete"] = bool(entity.get("sql_delete"))
            for column in entity.get("columns") or []:
                if isinstance(column, dict):
                    column["has_formula"] = bool(column.get("formula"))
    return data


EXCEPTION_EXPECTED_RE = re.compile(r"^([A-Za-z_]\w*Exception) code=(\d+)$")


def _plan_flags(data):
    """plan-tests: `expected`(분기 설명문에 조건식 조각이 섞인다)와 `description`은 버리고, 예외 이름과 코드만 구조화해 남긴다."""
    if isinstance(data, dict):
        for case in data.get("test_cases") or []:
            if isinstance(case, dict):
                match = EXCEPTION_EXPECTED_RE.match(str(case.get("expected", "")))
                if match:
                    case["expected_exception"], case["expected_code"] = match.group(1), int(match.group(2))
    return data


TRANSFORMS = {"derive-test-data": _derive_flags, "plan-tests": _plan_flags}


def sanitize(raw_dir, out_dir, sut_root=None) -> Sanitized:
    """raw를 허용 스키마로 정제해 `out_dir/<skill>.json`을 쓴다. 호출이 실패했거나 정제 오류가 나면 그 스킬 파일은 쓰지 않는다."""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    if sut_root is None:
        sut_root = Path(json.loads((raw_dir / "meta.json").read_text())["sutRoot"])
    roots = _roots(Path(sut_root))
    corpus = source_corpus(Path(sut_root))
    calls = json.loads((raw_dir / "calls.json").read_text())["calls"]
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    removed: Counter = Counter()
    result = Sanitized()
    for skill in SKILLS:
        schema = load_schema(skill)
        results = []
        errors_before = len(result.errors)
        for record in sorted((c for c in calls if c["skill"] == skill and c["rc"] == 0), key=lambda c: c["key"]):
            try:
                data = _load_raw(raw_dir, record, CLEAN_SOURCE[skill])
            except (OSError, ValueError) as exc:
                result.errors.append(f"{record['id']}: raw unreadable ({type(exc).__name__})")
                continue
            data = TRANSFORMS.get(skill, lambda value: value)(_relativize(data, roots))
            results.append({"source": record["key"], "data": data})
        if not results:
            continue  # 성공한 호출이 없으면 파일을 쓰지 않는다(호출 실패는 manifest.calls에 이미 있다)
        document = {"skill": skill, "results": results}
        local_removed: Counter = Counter()
        document = prune(document, schema, schema, "", local_removed)
        problems = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.absolute_path))
        if problems:
            where = "/".join(str(p) for p in problems[0].absolute_path)
            result.errors.append(f"{skill}: schema validation failed at {where or '<root>'}")  # 검증기 메시지는 값 조각을 담을 수 있어 옮기지 않는다
        leak = _find_absolute(document)
        if leak:
            result.errors.append(f"{skill}: absolute path remained at {leak}")
        for path in a1_violations(document, corpus)[:3]:
            result.errors.append(f"{skill}: A1 gate (source text) at {path}")
        for path in credential_violations(document)[:3]:
            result.errors.append(f"{skill}: credential gate at {path}")
        if len(result.errors) > errors_before:
            continue
        for path, count in local_removed.items():
            removed[f"{skill}:{re.sub(r'^results\[\]\.data\.?', '', path)}"] += count
        (out_dir / f"{skill}.json").write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        result.written.append(f"{skill}.json")
    result.removed_counts = dict(sorted(removed.items()))
    result.stripped_fields = sorted(removed)  # 실제로 값이 있어 제거한 경로만
    result.forbidden_declared = sorted(set(declared_forbidden_paths()) - set(removed))  # 선언했지만 이번 입력에는 값이 없던 경로
    return result


# --- CLI ----------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.bbtg")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("out_dir", type=Path)
    run.add_argument("--src", type=Path, required=True)
    run.add_argument("--sut-file", type=Path, required=True)
    run.add_argument("--bbtg-dir", type=Path, required=True)
    run.add_argument("--python", type=Path, help="bbtg venv 파이썬 대신 쓸 인터프리터(테스트용 가짜 bbtg)")
    args = parser.parse_args(argv)
    cfg = BbtgConfig.from_sut(args.sut_file, args.bbtg_dir)
    if args.python:
        cfg = dataclasses.replace(cfg, python=args.python)
    manifest = run_all(args.src, args.out_dir, cfg)
    print(json.dumps({"status": manifest.status, "reason": manifest.reason,
                      "extra": {"bbtg": manifest.data["summary"]}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
