"""S03 jQAssistant 온톨로지: 실행 중인 jQA server(Bolt)에 고정 Cypher 묶음을 질의해 설계 §6.5 스키마의 JSON을 만든다.

외부 도구 실행(scan, analyze, server 기동·종료)은 pipeline/S03-jqa.sh가 td_run으로 한다. 이 모듈은 질의 결과를
그래프로 바꾸는 일, 플러그인 jar 검증, 빈 포트 고르기, 서버 포트 대기만 한다.

질의 경로: jQA 2.9.1의 server는 HTTP 트랜잭션 API(tx/commit)를 열지 않는다. HTTP 포트는 Neo4j 브라우저 정적 파일만 서빙하고
질의는 Bolt(루프백)로만 가능하다. 그래서 neo4j 파이썬 드라이버로 Bolt를 쓴다.

사용:
  python -m td.ontology_jqa verify-plugin --repo <jqa-repo> [--config ontology/jqa/.jqassistant.yml]
  python -m td.ontology_jqa free-ports [count]
  python -m td.ontology_jqa check-loopback --pid <pid> [--pid ...]
  python -m td.ontology_jqa wait-bolt --port <p> --pid <pid> --timeout <sec>
  python -m td.ontology_jqa export --bolt-port <p> --queries <dir> --run-dir <dir> --sut-file <sut.yaml> --out <file>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Callable

import yaml

from td import prepare, state

Row = dict
Runner = Callable[[str], list[Row]]
Ontology = dict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "ontology" / "jqa" / ".jqassistant.yml"
DEFAULT_QUERIES = REPO_ROOT / "ontology" / "jqa" / "queries"
MAPPING_HTTP_METHODS = {
    "RequestMapping": None,
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}


class OntologyError(Exception):
    pass


# --- 경로 정규화 ---------------------------------------------------------------------------------------
def _clean_segment_path(path: str) -> str:
    """슬래시 중복·양끝 슬래시를 정리하고 path variable의 정규식(`{id:[0-9]+}`)을 `{id}`로 줄인다."""
    path = re.sub(r"\{([^}:]+):[^}]*\}", r"{\1}", path.strip())
    return "/".join(part for part in path.split("/") if part)


def normalize_path(class_paths: list[str], method_paths: list[str]) -> list[str]:
    """클래스 수준과 메서드 수준 경로를 곱집합으로 결합한다(배열 값 전개). 항상 `/`로 시작하고 trailing slash가 없다.
    한쪽이 비면 다른 쪽만, 둘 다 비면 `/`다."""
    classes = list(class_paths) or [""]
    methods = list(method_paths) or [""]
    combined = []
    for class_path in classes:
        for method_path in methods:
            joined = "/".join(part for part in (_clean_segment_path(class_path), _clean_segment_path(method_path)) if part)
            combined.append("/" + joined)
    return combined


def _api_matcher(api_include: str) -> Callable[[str], bool]:
    """`/api/**` 같은 Ant 스타일 포함 패턴을 경로 판정 함수로 만든다(`**`는 하위 전부, `*`는 한 단계)."""
    regex = re.escape(api_include)
    regex = regex.replace(r"/\*\*", r"(?:/.*)?").replace(r"\*\*", r".*").replace(r"\*", r"[^/]*")
    compiled = re.compile(f"^{regex}$")
    return lambda path: compiled.match(path) is not None


# --- 그래프 조립 ------------------------------------------------------------------------------------------
def _simple(fqn: str) -> str:
    return fqn.rsplit(".", 1)[-1]


class _Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: set[tuple[str, str, str]] = set()

    def node(self, node_id: str, kind: str, label: str, props: dict | None = None) -> str:
        existing = self.nodes.get(node_id)
        if existing is None:
            self.nodes[node_id] = {"id": node_id, "kind": kind, "label": label, "props": dict(props or {})}
        else:
            existing["props"].update(props or {})
        return node_id

    def edge(self, source: str, target: str, kind: str) -> None:
        if source in self.nodes and target in self.nodes and source != target:
            self.edges.add((source, target, kind))

    def result(self) -> tuple[list[dict], list[dict]]:
        nodes = sorted(self.nodes.values(), key=lambda n: (n["kind"], n["id"]))
        edges = [{"source": s, "target": t, "kind": k} for s, t, k in sorted(self.edges)]
        return nodes, edges


def _http_methods(row: Row) -> tuple[list[str], bool]:
    """(HTTP 메서드 목록, any 여부). @RequestMapping에 method가 없으면 모든 메서드를 받으므로 대표로 GET을 쓰고 any=True로 표시한다."""
    fixed = MAPPING_HTTP_METHODS.get(_simple(row["annotation"]))
    if fixed:
        return [fixed], False
    methods = [m.upper() for m in (row.get("httpMethods") or [])]
    return (methods, False) if methods else (["GET"], True)


def _add_endpoints(graph: _Graph, rows: list[Row], api_include: str) -> None:
    in_api = _api_matcher(api_include)
    for row in rows:
        methods, any_method = _http_methods(row)
        for method in methods:
            for path in normalize_path(row.get("classPaths") or [], row.get("methodPaths") or []):
                handler = f"{row['controller']}#{row['handlerName']}"
                view = not (row.get("rest") is True and in_api(path))
                node_id = f"endpoint:{method} {path}"
                if node_id in graph.nodes and graph.nodes[node_id]["props"]["handler"] != handler:
                    node_id = f"{node_id} [{handler}]"
                graph.node(node_id, "Endpoint", f"{method} {path}",
                           {"method": method, "path": path, "handler": handler, "view": view, "anyMethod": any_method})
                controller_id = f"controller:{row['controller']}"
                graph.node(controller_id, "Controller", _simple(row["controller"]),
                           {"fqn": row["controller"], "rest": row.get("rest") is True})
                graph.edge(controller_id, node_id, "declares")


def _add_call_paths(graph: _Graph, rows: list[Row]) -> None:
    prefix = {"Controller": "controller", "Service": "service", "Repository": "repository"}
    for row in rows:
        if row["rowType"] == "node":
            kind = row["sourceKind"]
            props = {"fqn": row["source"]}
            if kind == "Controller":
                props["rest"] = row.get("rest") is True
            graph.node(f"{prefix[kind]}:{row['source']}", kind, _simple(row["source"]), props)
    for row in rows:
        if row["rowType"] == "edge":
            graph.edge(f"{prefix[row['sourceKind']]}:{row['source']}", f"{prefix[row['targetKind']]}:{row['target']}", "dependsOn")


def _add_entities(graph: _Graph, rows: list[Row]) -> None:
    for row in rows:
        if row["rowType"] == "entity":
            graph.node(f"entity:{row['source']}", "Entity", _simple(row["source"]), {"fqn": row["source"]})
    for row in rows:
        entity_id = f"entity:{row['source']}"
        if row["rowType"] == "field":
            field_id = f"field:{row['source']}#{row['name']}"
            annotations = sorted({_simple(a) for a in (row.get("annotations") or [])
                                  if a.startswith(("jakarta.", "javax."))})
            graph.node(field_id, "Field", f"{_simple(row['source'])}.{row['name']}",
                       {"name": row["name"], "type": row.get("type"), "annotations": annotations})
            graph.edge(entity_id, field_id, "hasField")
        elif row["rowType"] == "reference":
            graph.edge(entity_id, f"entity:{row['target']}", "references")
        elif row["rowType"] == "manages":
            graph.edge(f"repository:{row['source']}", f"entity:{row['target']}", "manages")


def _add_exceptions(graph: _Graph, rows: list[Row]) -> None:
    handlers: dict[str, list[str]] = {}
    for row in rows:
        if row["rowType"] == "handler":
            handlers.setdefault(row["source"], []).append(row["handler"])
    for row in rows:
        if row["rowType"] == "exception":
            graph.node(f"exception:{row['source']}", "Exception", _simple(row["source"]),
                       {"fqn": row["source"], "handlers": sorted(handlers.get(row["source"], []))})
    for row in rows:
        if row["rowType"] == "throws":
            for prefix in ("controller", "service"):
                graph.edge(f"{prefix}:{row['source']}", f"exception:{row['target']}", "throws")


def _add_dtos(graph: _Graph, rows: list[Row]) -> None:
    for row in rows:
        if row["rowType"] == "dto":
            graph.node(f"dto:{row['source']}", "DTO", _simple(row["source"]), {"fqn": row["source"]})
    for row in rows:
        if row["rowType"] == "uses":
            for endpoint in list(graph.nodes.values()):
                if endpoint["kind"] == "Endpoint" and endpoint["props"]["handler"] == f"{row['source']}#{row['handlerName']}":
                    graph.edge(endpoint["id"], f"dto:{row['target']}", "uses")


def _read_query(queries_dir: Path, name: str, *, fallback: bool = False) -> str | None:
    path = (queries_dir / "fallback" / f"{name}.cypher") if fallback else (queries_dir / f"{name}.cypher")
    return path.read_text() if path.is_file() else None


def _query_with_fallback(run: Runner, queries_dir: Path, name: str, fallbacks: list[str]) -> list[Row]:
    primary = _read_query(queries_dir, name)
    if primary is None:
        raise OntologyError(f"Cypher 파일이 없다: {queries_dir / (name + '.cypher')}")
    rows = run(primary)
    if rows:
        return rows
    alternative = _read_query(queries_dir, name, fallback=True)
    if alternative is None:
        return rows
    rows = run(alternative)
    if rows:
        fallbacks.append(name)  # Spring 개념이 비어 원시 :Annotation 쿼리로 대체했다는 사실을 남긴다.
    return rows


def export_with_runner(run: Runner, queries_dir: Path, *, commit: str, version: str, api_include: str) -> Ontology:
    """질의 실행기(Cypher -> 행 목록)로 온톨로지를 만든다. 서버 없이 시험할 수 있게 분리했다."""
    queries_dir = Path(queries_dir)
    fallbacks: list[str] = []
    graph = _Graph()
    _add_call_paths(graph, _query_with_fallback(run, queries_dir, "call_paths", fallbacks))
    _add_endpoints(graph, _query_with_fallback(run, queries_dir, "endpoints", fallbacks), api_include)
    _add_entities(graph, run(_require(queries_dir, "entities")))
    _add_exceptions(graph, run(_require(queries_dir, "exceptions")))
    _add_dtos(graph, run(_require(queries_dir, "dtos")))
    nodes, edges = graph.result()
    return {"nodes": nodes, "edges": edges,
            "meta": {"tool": "jqassistant", "version": version, "commit": commit, "fallbacks": sorted(fallbacks)}}


def _require(queries_dir: Path, name: str) -> str:
    text = _read_query(queries_dir, name)
    if text is None:
        raise OntologyError(f"Cypher 파일이 없다: {queries_dir / (name + '.cypher')}")
    return text


def bolt_runner(server_url: str):
    """Bolt 질의 실행기와 닫는 함수를 돌려준다. server_url 예: bolt://127.0.0.1:7687 (jQA server는 인증이 없다)."""
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(server_url, auth=None)

    def run(cypher: str) -> list[Row]:
        with driver.session() as session:
            return [record.data() for record in session.run(cypher)]

    return run, driver.close


def export(server_url: str, queries_dir: Path, *, commit: str, version: str | None = None,
           api_include: str = "/api/**") -> Ontology:
    """실행 중인 jQA server에서 온톨로지를 내보낸다."""
    run, close = bolt_runner(server_url)
    try:
        return export_with_runner(run, Path(queries_dir), commit=commit,
                                  version=version or prepare.load_pin()["jqassistant"]["version"], api_include=api_include)
    finally:
        close()


# --- 플러그인 검증, 포트 ------------------------------------------------------------------------------------
def verify_plugin(repo: Path, config: Path = DEFAULT_CONFIG) -> str:
    """설정 파일의 Spring 플러그인 버전이 pin과 같고, 전용 저장소의 jar가 pin한 sha256과 같은지 확인한다. 아니면 예외."""
    pin = prepare.load_pin()
    spec = pin["jqassistantSpring"]
    declared = yaml.safe_load(Path(config).read_text())["jqassistant"]["plugins"]
    versions = [p["version"] for p in declared if p.get("artifact-id") == spec["artifact"]]
    if versions != [str(spec["version"])]:
        raise prepare.PrepareError(f"{config}의 Spring 플러그인 버전 {versions}이 pin({spec['version']})과 다르다")
    return prepare.check_resolved_plugin_jar(spec, spec["sha256"], Path(repo))


def free_ports(count: int = 1) -> list[int]:
    """루프백의 빈 포트 count개를 서로 다르게 고른다(전부 연 채로 고르므로 같은 포트가 두 번 나오지 않는다)."""
    socks = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socks.append(sock)
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in socks]
    finally:
        for sock in socks:
            sock.close()


def free_port() -> int:
    return free_ports(1)[0]


LOOPBACK_HOSTS = {"127.0.0.1", "[::1]", "localhost"}


def parse_listeners(lsof_field_output: str) -> list[str]:
    """`lsof -Fn` 출력에서 LISTEN 주소(`host:port`)만 뽑는다."""
    return [line[1:] for line in lsof_field_output.splitlines() if line.startswith("n")]


def non_loopback(listeners: list[str]) -> list[str]:
    return [addr for addr in listeners if addr.rsplit(":", 1)[0] not in LOOPBACK_HOSTS]


def check_loopback_only(pids: list[int]) -> list[str]:
    """pids의 TCP LISTEN 소켓이 모두 루프백이면 그 목록을, 아니면 OntologyError를 낸다. 목록이 비면 서버가 안 떠 있는 것이다."""
    import subprocess

    done = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", ",".join(str(p) for p in pids), "-Fn"],
                          capture_output=True, text=True, timeout=30)
    listeners = parse_listeners(done.stdout)
    if not listeners:
        raise OntologyError(f"PID {pids}의 LISTEN 소켓을 찾지 못했다(lsof rc={done.returncode})")
    exposed = non_loopback(listeners)
    if exposed:
        raise OntologyError(f"jQA server가 루프백이 아닌 주소에서 LISTEN한다: {exposed}")
    return listeners


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_bolt(port: int, pid: int, timeout: float, interval: float = 0.5) -> str:
    """서버 PID가 살아 있는 동안 Bolt 포트가 열리고 질의가 통할 때까지 기다린다. 성공하면 빈 문자열, 아니면 사유."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return "jQA server가 포트를 열기 전에 종료되었다"
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
            run, close = bolt_runner(f"bolt://127.0.0.1:{port}")
            try:
                run("RETURN 1 AS ok")
                return ""
            finally:
                close()
        except Exception:  # noqa: BLE001 - 아직 기동 중이다. 마감 시각까지 다시 시도한다.
            time.sleep(interval)
    return f"jQA server Bolt 포트 {port}가 {timeout:g}초 안에 열리지 않았다"


# --- CLI ------------------------------------------------------------------------------------------------------
def _cmd_verify_plugin(args) -> int:
    try:
        jar = verify_plugin(Path(args.repo), Path(args.config))
    except (prepare.PrepareError, OSError, KeyError, yaml.YAMLError) as exc:
        print(f"jQA Spring 플러그인 검증 실패(sha256 또는 설정): {exc}", file=sys.stderr)
        return 1
    print(jar)
    return 0


def _cmd_check_loopback(args) -> int:
    try:
        listeners = check_loopback_only(args.pid)
    except OntologyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(sorted(set(listeners))))
    return 0


def _cmd_wait_bolt(args) -> int:
    reason = wait_bolt(args.port, args.pid, args.timeout)
    if reason:
        print(reason, file=sys.stderr)
        return 1
    return 0


def _cmd_export(args) -> int:
    sut = yaml.safe_load(Path(args.sut_file).read_text())
    commit = state.read_run(args.run_dir).get("commit")
    if not commit:
        print("run.json에 commit이 없다", file=sys.stderr)
        return 1
    try:
        ontology = export(f"bolt://127.0.0.1:{args.bolt_port}", Path(args.queries), commit=commit,
                          api_include=sut["api"]["include"])
    except Exception as exc:  # noqa: BLE001 - 질의 실패는 단계 실패 사유로 올린다
        print(f"온톨로지 질의 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ontology, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"nodes": len(ontology["nodes"]), "edges": len(ontology["edges"]),
                      "fallbacks": ontology["meta"]["fallbacks"]}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="td.ontology_jqa")
    sub = parser.add_subparsers(dest="cmd", required=True)
    verify = sub.add_parser("verify-plugin")
    verify.add_argument("--repo", required=True)
    verify.add_argument("--config", default=str(DEFAULT_CONFIG))
    verify.set_defaults(func=_cmd_verify_plugin)
    port = sub.add_parser("free-ports")
    port.add_argument("count", type=int, nargs="?", default=2)
    port.set_defaults(func=lambda a: print(*free_ports(a.count)) or 0)
    loop = sub.add_parser("check-loopback")
    loop.add_argument("--pid", type=int, action="append", required=True)
    loop.set_defaults(func=_cmd_check_loopback)
    wait = sub.add_parser("wait-bolt")
    wait.add_argument("--port", type=int, required=True)
    wait.add_argument("--pid", type=int, required=True)
    wait.add_argument("--timeout", type=float, required=True)
    wait.set_defaults(func=_cmd_wait_bolt)
    exp = sub.add_parser("export")
    exp.add_argument("--bolt-port", type=int, required=True)
    exp.add_argument("--queries", default=str(DEFAULT_QUERIES))
    exp.add_argument("--run-dir", required=True)
    exp.add_argument("--sut-file", required=True)
    exp.add_argument("--out", required=True)
    exp.set_defaults(func=_cmd_export)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
