"""생성 입력 번들 조립과 오염 검사(설계 §6.6, §13.4, REQ-019/020/075, 반목표 A1).

번들 레이아웃(허용 목록 그 자체):
- `bbtg/<skill>.json`: S02 정제 산출물, `bbtg/manifest.json`: 원문 필드 없는 요약(summary, sanitize 목록과 개수만)
- `harness/CONTRACT.md`: 하네스 API 계약(도메인 지식 없음). 번들에서 허용되는 유일한 `.md`다.
- `ontology/ontology-jqa.json`(jqa arm), `ontology/ontology-owl.ttl`(owl arm)
- `extra/<name>`: `TD_BUNDLE_EXTRA` 주입용(수용 테스트 전용). 출처가 금지 경로면 경로 검사가 실패시킨다.
번들은 항상 `out_dir`에 보존한다(S06은 `S06/bundles/<arm>/`, S05는 `S05/bundle/`).
입력 해시는 번들 파일의 (상대 경로, 바이트)를 정렬해 sha256으로 만든다. 체크아웃 경로와 무관하다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from td import normalize

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SRC = Path("e2e") / "harness" / "CONTRACT.md"
ARMS = ("base", "jqa", "owl")
WINDOW_LINES = 5
BBTG_FILE_RE = re.compile(r"^bbtg/[a-z][a-z0-9-]*\.json$")
STAMP_NAME = ".td-bundle-verified.json"   # build가 검사 통과 뒤 쓰는 서명. llm.sh가 호출 전에 대조한다


class BundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Violation:
    kind: str       # "path" | "content"
    path: str       # 번들 기준 상대 경로
    detail: str


@dataclass(frozen=True)
class Bundle:
    path: Path
    input_hash: str                      # 전체 sha256 hex. genId에는 앞 8자리(hash8)를 쓴다
    arm: str = "base"
    extra_origins: dict[str, str] = field(default_factory=dict)   # 번들 상대 경로 -> 출처 절대 경로

    @property
    def hash8(self) -> str:
        return self.input_hash[:8]

    def files(self) -> list[str]:
        return sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob("*")
                      if p.is_file() and p.name != STAMP_NAME)


def hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file() and p.name != STAMP_NAME):
        data = path.read_bytes()
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode() + b"\0")
        digest.update(data + b"\0")
    return digest.hexdigest()


def _write_filtered_manifest(source: Path, target: Path) -> None:
    manifest = json.loads(source.read_text(encoding="utf-8"))
    sanitize = manifest.get("sanitize", {})
    filtered = {"summary": manifest.get("summary", {}),
                "sanitize": {key: sanitize.get(key, []) for key in ("strippedFields", "forbiddenDeclared", "removedCounts")}}
    target.write_text(json.dumps(filtered, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def assemble(arm: str, run_dir, out_dir, extra=None) -> Bundle:
    """arm의 입력 번들을 out_dir에 새로 만든다(기존 내용은 지운다). extra는 주입할 파일 경로 목록(수용 테스트용)."""
    if arm not in ARMS:
        raise BundleError(f"알 수 없는 arm: {arm!r}")
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    clean_dir = run_dir / "S02" / "bbtg" / "clean"
    clean_files = sorted(clean_dir.glob("*.json")) if clean_dir.is_dir() else []
    if not clean_files:
        raise BundleError(f"S02 정제 산출물이 없다: {clean_dir}")
    contract = REPO_ROOT / CONTRACT_SRC
    if not contract.is_file():
        raise BundleError(f"하네스 계약이 없다: {contract}")
    shutil.rmtree(out_dir, ignore_errors=True)
    (out_dir / "bbtg").mkdir(parents=True)
    for source in clean_files:
        shutil.copyfile(source, out_dir / "bbtg" / source.name)
    manifest = run_dir / "S02" / "bbtg" / "manifest.json"
    if manifest.is_file():
        _write_filtered_manifest(manifest, out_dir / "bbtg" / "manifest.json")
    (out_dir / "harness").mkdir()
    shutil.copyfile(contract, out_dir / "harness" / "CONTRACT.md")
    ontology_source = {"jqa": run_dir / "S03" / "ontology-jqa.json", "owl": run_dir / "S05" / "ontology-owl.ttl"}.get(arm)
    if ontology_source is not None:
        if not ontology_source.is_file():
            raise BundleError(f"{arm} arm의 온톨로지가 없다: {ontology_source}")
        (out_dir / "ontology").mkdir()
        shutil.copyfile(ontology_source, out_dir / "ontology" / ontology_source.name)
    origins: dict[str, str] = {}
    for item in extra or []:
        origin = Path(item).resolve()
        if not origin.is_file():
            raise BundleError(f"TD_BUNDLE_EXTRA 파일이 없다: {item}")
        rel = f"extra/{origin.name}"
        (out_dir / "extra").mkdir(exist_ok=True)
        shutil.copyfile(origin, out_dir / rel)
        origins[rel] = str(origin)
    return Bundle(path=out_dir, input_hash=hash_tree(out_dir), arm=arm, extra_origins=origins)


# --- 경로 검사 ---------------------------------------------------------------------------
def _allowed(arm: str) -> set[str]:
    allowed = {"bbtg/manifest.json", "harness/CONTRACT.md"}
    if arm == "jqa":
        allowed.add("ontology/ontology-jqa.json")
    if arm == "owl":
        allowed.add("ontology/ontology-owl.ttl")
    return allowed


def _origin_violation(origin: str, sut_root: Path) -> str | None:
    """주입물의 출처가 SUT 체크아웃 안(확장자 무관)이거나 이 repo의 docs/ 아래이거나 Markdown이면 사유를 돌려준다."""
    origin_path = Path(origin).resolve()
    for label, root in (("SUT", Path(sut_root).resolve()), ("repo docs", (REPO_ROOT / "docs").resolve())):
        try:
            relative = origin_path.relative_to(root)
        except ValueError:
            continue
        return f"출처가 {label} 아래다: {relative.as_posix()}"
    if origin_path.suffix.lower() in (".md", ".markdown"):
        return f"출처가 Markdown 문서다: {origin_path.name}"
    return None


def check_paths(bundle: Bundle, sut_root) -> list[Violation]:
    """번들의 모든 파일이 허용 목록 안인지, `extra/` 주입물의 출처가 금지 경로(SUT src/docs, *.md)가 아닌지 본다."""
    violations: list[Violation] = []
    allowed = _allowed(bundle.arm)
    for path in sorted(p for p in bundle.path.rglob("*") if (p.is_file() or p.is_symlink()) and p.name != STAMP_NAME):
        rel = path.relative_to(bundle.path).as_posix()
        if path.is_symlink():
            violations.append(Violation("path", rel, "심볼릭 링크는 번들에 둘 수 없다"))
        elif rel in bundle.extra_origins:
            reason = _origin_violation(bundle.extra_origins[rel], sut_root)
            if reason:
                violations.append(Violation("path", rel, reason))
        elif rel not in allowed and not BBTG_FILE_RE.match(rel):
            violations.append(Violation("path", rel, "허용 목록 밖의 파일이다"))
        elif rel.lower().endswith((".md", ".markdown")) and rel != "harness/CONTRACT.md":
            violations.append(Violation("path", rel, "하네스 계약 이외의 Markdown은 금지다"))
    return violations


# --- 내용 검사 ---------------------------------------------------------------------------
def _window_key(sequence: list[str], position: int) -> bytes:
    return hashlib.sha1("\n".join(sequence[position:position + WINDOW_LINES]).encode("utf-8")).digest()


def _window_keys(sequence: list[str]) -> set[bytes]:
    return {_window_key(sequence, i) for i in range(len(sequence) - WINDOW_LINES + 1)}


def sut_window_index(sut_src) -> dict[bytes, str]:
    """SUT `src/**`(main과 test) 모든 텍스트 파일의 5줄 창 해시 -> 첫 출처 파일(SUT 기준 상대 경로)."""
    sut_src = Path(sut_src)
    index: dict[bytes, str] = {}
    for path in sorted(p for p in (sut_src / "src").rglob("*") if p.is_file()):
        rel = path.relative_to(sut_src).as_posix()
        for key in _window_keys(normalize.text_lines(path)):
            index.setdefault(key, rel)
    return index


def check_content(bundle: Bundle, sut_src, oracle=None) -> list[Violation]:
    """번들 파일마다 정규화한 줄 시퀀스의 5줄 연속 창이 SUT src와 같으면 위반이다.
    oracle(문자열 목록, 사람이 쓴 기대 설명)이 있으면 번들 정규화 텍스트에 그 문장이 들어 있는지도 본다(부분 문자열)."""
    index = sut_window_index(sut_src)
    oracle_lines = [" ".join(normalize.normalize_leaf(text)) for text in (oracle or [])]
    violations: list[Violation] = []
    for path in sorted(p for p in bundle.path.rglob("*") if p.is_file() and p.name != STAMP_NAME):
        rel = path.relative_to(bundle.path).as_posix()
        sequence = normalize.lines(path)
        for position in range(len(sequence) - WINDOW_LINES + 1):
            key = _window_key(sequence, position)
            if key in index:
                violations.append(Violation("content", rel, f"SUT 소스({index[key]})와 연속 {WINDOW_LINES}줄이 일치한다(정규화 줄 {position + 1})"))
                break
        joined = " ".join(sequence)
        for needle in oracle_lines:
            if needle and needle in joined:
                violations.append(Violation("content", rel, "SUT 설명(oracle) 문장이 번들에 들어 있다"))
                break
    return violations


# --- 검사 서명(A1 심층 방어) ---------------------------------------------------------------
def write_stamp(bundle: Bundle) -> Path:
    """검사를 통과한 번들 내용의 서명을 번들 안에 쓴다: {inputHash, files:[{path, sha256}]}(시각 없음, 결정적)."""
    files = [{"path": rel, "sha256": hashlib.sha256((bundle.path / rel).read_bytes()).hexdigest()} for rel in bundle.files()]
    stamp = bundle.path / STAMP_NAME
    stamp.write_text(json.dumps({"inputHash": bundle.input_hash, "files": files}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return stamp


def verify_stamp(bundle_dir) -> list[str]:
    """번들이 서명과 일치하는지 본다. 문제 목록(비면 통과). 서명 없음, 파일 추가·삭제·변조, 심볼릭 링크가 모두 문제다."""
    root = Path(bundle_dir)
    stamp = root / STAMP_NAME
    if not root.is_dir():
        return [f"번들 디렉터리가 없다: {root}"]
    if not stamp.is_file() or stamp.is_symlink():
        return ["검사 서명이 없다(td.bundle build를 통과한 번들이어야 한다)"]
    try:
        recorded = json.loads(stamp.read_text(encoding="utf-8"))
        expected = {item["path"]: item["sha256"] for item in recorded["files"]}
    except (ValueError, KeyError, TypeError):
        return ["검사 서명을 읽을 수 없다"]
    problems: list[str] = []
    actual: set[str] = set()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.name == STAMP_NAME and path.parent == root:
            continue
        if path.is_symlink():
            problems.append(f"심볼릭 링크: {rel}")
        elif path.is_file():
            actual.add(rel)
            if rel not in expected:
                problems.append(f"서명에 없는 파일: {rel}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected[rel]:
                problems.append(f"내용이 서명과 다르다: {rel}")
    problems += [f"서명에 있는 파일이 없다: {rel}" for rel in sorted(set(expected) - actual)]
    if not problems and hash_tree(root) != recorded.get("inputHash"):
        problems.append("입력 해시가 서명과 다르다")
    return problems


# --- CLI ---------------------------------------------------------------------------------
def _cmd_build(args) -> int:
    extra_env = os.environ.get("TD_BUNDLE_EXTRA")
    extra = [item for item in (extra_env or "").split(os.pathsep) if item]
    if extra and not os.environ.get("TD_SITE_PREFIX"):
        print("TD_BUNDLE_EXTRA는 TD_SITE_PREFIX가 있을 때(수용 테스트)만 쓸 수 있다", file=sys.stderr)
        return 2
    extra = [item if os.path.isabs(item) else str(Path(args.sut_src) / item) for item in extra]
    try:
        built = assemble(args.arm, args.run_dir, args.out, extra=extra)
    except BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    oracle = None
    if args.oracle:
        oracle = json.loads(Path(args.oracle).read_text(encoding="utf-8"))
    violations = check_paths(built, args.sut_src) + check_content(built, args.sut_src, oracle)
    if violations:
        for violation in violations:
            print(f"A1 위반({violation.kind}): {violation.path}: {violation.detail}", file=sys.stderr)
        return 1
    write_stamp(built)
    print(json.dumps({"path": str(built.path), "inputHash": built.input_hash, "hash8": built.hash8,
                      "files": built.files()}, ensure_ascii=False))
    return 0


def inline(bundle_dir: Path) -> str:
    """번들 파일을 프롬프트에 인라인할 텍스트로 만든다(정렬된 상대 경로 순)."""
    parts = []
    for path in sorted(Path(bundle_dir).rglob("*")):
        if path.is_symlink():
            raise BundleError(f"번들에 심볼릭 링크가 있다: {path.relative_to(bundle_dir).as_posix()}")
        if not path.is_file() or path.name == STAMP_NAME:
            continue
        rel = path.relative_to(bundle_dir).as_posix()
        parts.append(f"=== FILE: {rel} ===\n{path.read_text(encoding='utf-8', errors='replace').rstrip()}\n=== END FILE ===\n")
    return "\n".join(parts)


def _cmd_inline(args) -> int:
    try:
        sys.stdout.write(inline(Path(args.bundle)))
    except BundleError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _cmd_verify(args) -> int:
    problems = verify_stamp(args.bundle)
    for problem in problems:
        print(f"번들 검증 실패: {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.bundle")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="번들 조립 + 경로·내용 검사(위반이면 1, 입력 오류면 2)")
    build.add_argument("--arm", required=True, choices=ARMS)
    build.add_argument("--run-dir", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--sut-src", required=True)
    build.add_argument("--oracle", help="oracle 설명 문자열 목록(JSON)")
    build.set_defaults(func=_cmd_build)
    inline_cmd = sub.add_parser("inline", help="번들을 프롬프트용 텍스트로 출력")
    inline_cmd.add_argument("bundle")
    inline_cmd.set_defaults(func=_cmd_inline)
    verify = sub.add_parser("verify", help="번들이 build가 쓴 검사 서명과 같은지 확인(다르면 1)")
    verify.add_argument("bundle")
    verify.set_defaults(func=_cmd_verify)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
