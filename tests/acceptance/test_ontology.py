"""REQ-014/015: S03 jQAssistant 온톨로지(실제 jQA CLI·Spring 플러그인·petclinic classes), REQ-010의 S03 SIGINT 케이스.

전제(S00이 준비한 work/tools/jqassistant, work/tools/jqa-repo, work/suts/petclinic/src/build/classes)가 없으면 실패한다.
S03 한 번(수십 초~2분)을 모듈 단위로 공유한다. 주입 테스트(플러그인 sha 불일치, SIGINT)는 따로 돌린다.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import pytest
import yaml

from helpers import find_leaked_resources, pid_alive
from td import envctl, ontology_jqa, prepare

REPO_ROOT = Path(__file__).resolve().parents[2]
S03_SCRIPT = REPO_ROOT / "pipeline" / "S03-jqa.sh"
TOOLS_DIR = REPO_ROOT / "work" / "tools"
SUT_SRC = REPO_ROOT / "work" / "suts" / "petclinic" / "src"
SUT_FILE = REPO_ROOT / "suts" / "petclinic" / "sut.yaml"
EXPECTED_FILE = REPO_ROOT / "suts" / "petclinic" / "expected-endpoints.yaml"
SCHEMA_FILE = REPO_ROOT / "site-gen" / "td" / "schemas" / "ontology.schema.json"
RUN_COMMIT = "b6f939355e8790202ddfc71e3f3507252745ed37"


@dataclass
class S03Run:
    returncode: int
    stdout: str
    stderr: str
    run_dir: Path
    bystander_alive_after: bool | None = None

    @property
    def stage(self) -> dict:
        return json.loads((self.run_dir / "stages" / "S03.json").read_text())

    @property
    def ontology_path(self) -> Path:
        return self.run_dir / "S03" / "ontology-jqa.json"

    @property
    def ontology(self) -> dict:
        return json.loads(self.ontology_path.read_text())


def _prepare_run(base: Path, tools_dir: Path) -> tuple[Path, dict]:
    run_dir = base / "runs" / "20990101-000000Z-s03test-manual-00000000"
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(base), TD_RUN_DIR=str(run_dir), TD_SUT_SRC=str(SUT_SRC),
               TD_SUT_FILE=str(SUT_FILE), TD_SUT_COMMIT=RUN_COMMIT, TD_SITE_PREFIX="_test/s03-stage/")
    init = subprocess.run(
        [sys.executable, "-m", "td.state", "init", str(run_dir), "--run-id", run_dir.name, "--sut", "petclinic",
         "--commit", RUN_COMMIT],
        capture_output=True, text=True, env={**env, "PYTHONPATH": str(REPO_ROOT / "site-gen")})
    assert init.returncode == 0, init.stderr
    (run_dir / "stages").mkdir(parents=True, exist_ok=True)
    (run_dir / "pids").mkdir(exist_ok=True)
    (run_dir / "stages" / "S00.json").write_text(json.dumps(
        {"id": "S00", "status": "passed", "reason": None, "outputs": {"toolsDir": str(tools_dir)}}))
    return run_dir, env


def _require_prerequisites() -> None:
    needed = [TOOLS_DIR / "jqassistant" / "bin" / "jqassistant", TOOLS_DIR / "jqa-repo",
              SUT_SRC / "build" / "classes" / "java" / "main"]
    missing = [str(p.relative_to(REPO_ROOT)) for p in needed if not p.exists()]
    if missing:
        pytest.fail(f"S00이 준비한 산출물이 없다: {missing}", pytrace=False)


def _run_s03(base: Path, tools_dir: Path = TOOLS_DIR, **extra_env: str) -> S03Run:
    run_dir, env = _prepare_run(base, tools_dir)
    env.update(extra_env)
    done = subprocess.run(["bash", str(S03_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True,
                          env=env, timeout=1200)
    return S03Run(done.returncode, done.stdout, done.stderr, run_dir)


@pytest.fixture(scope="module")
def s03_run(tmp_path_factory) -> S03Run:
    """S03 한 번. 다른 단계가 등록한 PID(other.pid)가 S03 종료 때 건드려지지 않는지 보려고 살아 있는 프로세스를 미리 등록해 둔다."""
    _require_prerequisites()
    base = tmp_path_factory.mktemp("s03-default")
    run_dir, env = _prepare_run(base, TOOLS_DIR)
    bystander = subprocess.Popen(["sleep", "600"])
    (run_dir / "pids" / "other.pid").write_text(f"{bystander.pid}\n")
    try:
        done = subprocess.run(["bash", str(S03_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True,
                              env=env, timeout=1200)
        run = S03Run(done.returncode, done.stdout, done.stderr, run_dir)
        run.bystander_alive_after = bystander.poll() is None
        yield run
    finally:
        bystander.kill()
        bystander.wait(timeout=10)


def _expected() -> dict:
    return yaml.safe_load(EXPECTED_FILE.read_text())


# --- REQ-014 -----------------------------------------------------------------------------------
def test_req014_endpoints_match_expected(s03_run):
    """REQ-014: view=false Endpoint 집합(메서드, 경로, 핸들러)이 사람이 적은 기대 목록 17개와 같다."""
    assert s03_run.returncode == 0, s03_run.stderr[-3000:]
    assert s03_run.stage["status"] == "passed", s03_run.stage
    expected = _expected()
    assert expected["commit"] == RUN_COMMIT, "기대 목록의 commit이 run 커밋과 다르다: 소스를 다시 읽고 expected-endpoints.yaml을 갱신하라"
    assert len(expected["endpoints"]) == 17
    nodes = s03_run.ontology["nodes"]
    actual = {(n["props"]["method"], n["props"]["path"], n["props"]["handler"])
              for n in nodes if n["kind"] == "Endpoint" and n["props"]["view"] is False}
    wanted = {(e["method"], e["path"], e["handler"]) for e in expected["endpoints"]}
    assert actual == wanted, (sorted(actual - wanted), sorted(wanted - actual))
    controllers = {n["label"] for n in nodes if n["kind"] == "Controller" and n["props"].get("rest") is True}
    assert controllers == {fqcn.rsplit(".", 1)[-1] for fqcn in expected["controllers"]}
    # HTML @Controller 핸들러는 view=true로 들어가고, /api 범위 밖이다.
    views = [n for n in nodes if n["kind"] == "Endpoint" and n["props"]["view"] is True]
    assert views and all(not n["props"]["path"].startswith("/api/") for n in views)


# --- REQ-015 -----------------------------------------------------------------------------------
def test_req015_schema_and_kinds(s03_run):
    """REQ-015: 스키마 통과, meta.commit = run commit, 필수 kind 노드, 절대 경로 없음, 폴백 없음."""
    assert s03_run.returncode == 0, s03_run.stderr[-3000:]
    ontology = s03_run.ontology
    jsonschema.validate(ontology, json.loads(SCHEMA_FILE.read_text()))
    run_commit = json.loads((s03_run.run_dir / "run.json").read_text())["commit"]
    assert ontology["meta"]["commit"] == run_commit == RUN_COMMIT
    assert ontology["meta"]["tool"] == "jqassistant" and ontology["meta"]["version"] == "2.9.1"
    assert ontology["meta"]["fallbacks"] == []
    kinds = {n["kind"] for n in ontology["nodes"]}
    assert {"Endpoint", "Controller", "Service", "Repository", "Entity", "Field", "Exception", "DTO"} <= kinds
    ids = [n["id"] for n in ontology["nodes"]]
    assert len(ids) == len(set(ids))
    id_set = set(ids)
    assert ontology["edges"] and all(e["source"] in id_set and e["target"] in id_set for e in ontology["edges"])
    # Controller → Service → Repository 경로가 최소 하나 있다.
    by_id = {n["id"]: n["kind"] for n in ontology["nodes"]}
    depends = [(by_id[e["source"]], by_id[e["target"]]) for e in ontology["edges"] if e["kind"] == "dependsOn"]
    assert ("Controller", "Service") in depends and ("Service", "Repository") in depends
    text = s03_run.ontology_path.read_text()
    assert "/Users/" not in text and str(s03_run.run_dir) not in text and str(SUT_SRC) not in text
    assert s03_run.stage["outputs"]["ontology"] == str(s03_run.ontology_path)


def test_req015_server_listens_on_loopback_only_and_pids_scoped(s03_run):
    """server의 LISTEN 소켓은 루프백뿐이다(HTTP 브라우저 포트는 꺼져 있다). 종료 때 S03 PID만 정리하고 파일을 지운다."""
    assert s03_run.returncode == 0, s03_run.stderr[-3000:]
    listeners = s03_run.stage["listeners"]
    assert listeners and ontology_jqa.non_loopback(listeners) == [], listeners
    assert len(listeners) == 1, f"Bolt 외의 포트가 열렸다: {listeners}"  # HTTP 포트 -1이면 Bolt 하나뿐이다
    pids_dir = s03_run.run_dir / "pids"
    assert not (pids_dir / "jqa-server.pid").exists() and not (pids_dir / "jqa-server-java.pid").exists()
    assert (pids_dir / "other.pid").exists() and s03_run.bystander_alive_after, "다른 단계의 PID가 정리되었다"


def test_req015_schema_rejects_bad_documents():
    schema = json.loads(SCHEMA_FILE.read_text())
    good = {"nodes": [{"id": "a", "kind": "Service", "label": "A", "props": {}}], "edges": [],
            "meta": {"tool": "t", "version": "1", "commit": "c", "fallbacks": []}}
    jsonschema.validate(good, schema)
    bad_kind = json.loads(json.dumps(good)); bad_kind["nodes"][0]["kind"] = "Widget"
    no_meta = {k: v for k, v in good.items() if k != "meta"}
    bad_edge = json.loads(json.dumps(good)); bad_edge["edges"] = [{"source": "a", "target": "a"}]
    for broken in (bad_kind, no_meta, bad_edge):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)
    endpoint_without_handler = json.loads(json.dumps(good))
    endpoint_without_handler["nodes"][0] = {"id": "e", "kind": "Endpoint", "label": "GET /x",
                                            "props": {"method": "GET", "path": "/x", "view": False}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(endpoint_without_handler, schema)


# --- 단위: 경로 정규화, Cypher 묶음, 폴백 ----------------------------------------------------------------
@pytest.mark.parametrize("class_paths,method_paths,expected", [
    (["/api/owners"], ["/{ownerId}"], ["/api/owners/{ownerId}"]),
    (["/api/owners"], [], ["/api/owners"]),
    ([], ["/welcome"], ["/welcome"]),
    ([], [], ["/"]),
    (["/api/owners/"], ["/"], ["/api/owners"]),
    (["api/owners"], ["{id}/"], ["/api/owners/{id}"]),
    (["/a", "/b"], ["/x", "/y"], ["/a/x", "/a/y", "/b/x", "/b/y"]),
    (["/api//owners"], ["//{id}"], ["/api/owners/{id}"]),
    (["/api"], ["/{id:[0-9]+}"], ["/api/{id}"]),
])
def test_unit_normalize_path(class_paths, method_paths, expected):
    assert ontology_jqa.normalize_path(class_paths, method_paths) == expected


def test_unit_listener_parsing_flags_non_loopback():
    lsof = "p123\nf494\nn127.0.0.1:17687\nf495\nn*:59518\nn[::1]:1234\n"
    listeners = ontology_jqa.parse_listeners(lsof)
    assert listeners == ["127.0.0.1:17687", "*:59518", "[::1]:1234"]
    assert ontology_jqa.non_loopback(listeners) == ["*:59518"]


def test_unit_free_ports_are_distinct_and_bindable():
    ports = ontology_jqa.free_ports(5)
    assert len(set(ports)) == 5


def test_unit_request_mapping_without_method_is_marked_any(tmp_path):
    queries = tmp_path / "queries"
    queries.mkdir()
    for name in ("endpoints", "call_paths", "entities", "exceptions", "dtos"):
        (queries / f"{name}.cypher").write_text(f"// primary {name}\nRETURN 1")
    row = {"controller": "a.B", "rest": True, "classPaths": ["/api"], "methodPaths": ["/x"], "handlerName": "h",
           "annotation": "org.springframework.web.bind.annotation.RequestMapping", "httpMethods": []}
    ontology = ontology_jqa.export_with_runner(_fake_runner({"primary endpoints": [row]}), queries, commit="c",
                                               version="2.9.1", api_include="/api/**")
    (endpoint,) = [n for n in ontology["nodes"] if n["kind"] == "Endpoint"]
    assert endpoint["props"]["anyMethod"] is True and endpoint["props"]["method"] == "GET"


def test_unit_queries_dir_has_five_cypher_files():
    names = {p.stem for p in (REPO_ROOT / "ontology" / "jqa" / "queries").glob("*.cypher")}
    assert {"endpoints", "call_paths", "entities", "exceptions", "dtos"} <= names


def _fake_runner(rows_by_query: dict[str, list[dict]]):
    def run(cypher: str) -> list[dict]:
        for marker, rows in rows_by_query.items():
            if marker in cypher:
                return rows
        return []
    return run


def test_unit_export_falls_back_to_annotation_query_and_records_it(tmp_path):
    """Spring 개념이 비어 있으면 :Annotation 쿼리로 대체하고 meta.fallbacks에 기록한다."""
    queries = tmp_path / "queries"
    (queries / "fallback").mkdir(parents=True)
    for name in ("endpoints", "call_paths", "entities", "exceptions", "dtos"):
        (queries / f"{name}.cypher").write_text(f"// primary {name}\nRETURN 1")
    (queries / "fallback" / "endpoints.cypher").write_text("// fallback endpoints\nRETURN 1")
    row = {"controller": "a.B", "rest": True, "classPaths": ["/api/x"], "methodPaths": ["/{id}"],
           "annotation": "org.springframework.web.bind.annotation.GetMapping", "httpMethods": [], "handlerName": "one"}
    ontology = ontology_jqa.export_with_runner(
        _fake_runner({"fallback endpoints": [row]}), queries, commit="c0ffee", version="2.9.1", api_include="/api/**")
    assert ontology["meta"]["fallbacks"] == ["endpoints"]
    endpoints = [n for n in ontology["nodes"] if n["kind"] == "Endpoint"]
    assert [(n["props"]["method"], n["props"]["path"], n["props"]["handler"], n["props"]["view"]) for n in endpoints] == [
        ("GET", "/api/x/{id}", "a.B#one", False)]
    jsonschema.validate(ontology, json.loads(SCHEMA_FILE.read_text()))


def test_unit_export_without_fallback_when_primary_has_rows(tmp_path):
    queries = tmp_path / "queries"
    queries.mkdir()
    for name in ("endpoints", "call_paths", "entities", "exceptions", "dtos"):
        (queries / f"{name}.cypher").write_text(f"// primary {name}\nRETURN 1")
    row = {"controller": "a.B", "rest": False, "classPaths": [], "methodPaths": ["/home"],
           "annotation": "org.springframework.web.bind.annotation.GetMapping", "httpMethods": [], "handlerName": "show"}
    ontology = ontology_jqa.export_with_runner(
        _fake_runner({"primary endpoints": [row]}), queries, commit="c0ffee", version="2.9.1", api_include="/api/**")
    assert ontology["meta"]["fallbacks"] == []
    (endpoint,) = [n for n in ontology["nodes"] if n["kind"] == "Endpoint"]
    assert endpoint["props"]["view"] is True and endpoint["props"]["path"] == "/home"


# --- 플러그인 sha 검증 --------------------------------------------------------------------------------
def test_unit_verify_plugin_detects_tampered_jar(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(TOOLS_DIR / "jqa-repo", repo)
    jar = next(repo.rglob("jqassistant-spring-plugin-*.jar"))
    ontology_jqa.verify_plugin(repo)  # 원본은 통과한다
    jar.write_bytes(jar.read_bytes() + b"x")
    with pytest.raises(prepare.PrepareError, match="sha256이 pin과 다르다"):
        ontology_jqa.verify_plugin(repo)


def test_unit_verify_plugin_detects_config_version_mismatch(tmp_path):
    config = tmp_path / ".jqassistant.yml"
    config.write_text((REPO_ROOT / "ontology" / "jqa" / ".jqassistant.yml").read_text().replace("version: 2.9.0", "version: 2.8.0"))
    with pytest.raises(prepare.PrepareError, match=r"2\.8\.0.*pin"):
        ontology_jqa.verify_plugin(TOOLS_DIR / "jqa-repo", config)


def test_req015_tampered_plugin_jar_fails_stage_before_scan(tmp_path):
    """Task 3 carry: 전용 저장소의 플러그인 jar가 pin과 다르면 S03은 스캔 전에 failed다."""
    _require_prerequisites()
    fake_tools = tmp_path / "tools"
    fake_tools.mkdir()
    (fake_tools / "jqassistant").symlink_to(TOOLS_DIR / "jqassistant")
    shutil.copytree(TOOLS_DIR / "jqa-repo", fake_tools / "jqa-repo")
    jar = next((fake_tools / "jqa-repo").rglob("jqassistant-spring-plugin-*.jar"))
    jar.write_bytes(jar.read_bytes() + b"x")
    started = time.time()
    run = _run_s03(tmp_path / "work", tools_dir=fake_tools)
    assert run.returncode == 1, run.stderr[-2000:]
    assert run.stage["status"] == "failed" and "sha256" in run.stage["reason"]
    assert not (run.run_dir / "S03" / "ontology-jqa.json").exists()
    assert not (run.run_dir / "S03" / "store").exists(), "플러그인 검증 전에 스캔이 시작되었다"
    assert time.time() - started < 60


def test_req015_missing_classes_dir_fails_stage(tmp_path):
    _require_prerequisites()
    run_dir, env = _prepare_run(tmp_path, TOOLS_DIR)
    empty_src = tmp_path / "empty-src"
    empty_src.mkdir()
    env["TD_SUT_SRC"] = str(empty_src)
    done = subprocess.run(["bash", str(S03_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True, env=env,
                          timeout=300)
    assert done.returncode == 1
    stage = json.loads((run_dir / "stages" / "S03.json").read_text())
    assert stage["status"] == "failed" and "classes" in stage["reason"]


# --- REQ-010: S03 SIGINT ------------------------------------------------------------------------------
def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _jqa_processes(marker: str) -> list[str]:
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if marker in line and "jqassistant" in line]


def test_req010_s03_sigint_cleanup(tmp_path, test_run_label):
    """REQ-010(S03): jQA server PID 파일이 생기자마자 SIGINT -> 90초 안에 종료, 살아 있는 PID 0, 라벨 자원 0."""
    _require_prerequisites()
    run_dir, env = _prepare_run(tmp_path, TOOLS_DIR)
    env["TD_RUN_LABEL"] = test_run_label
    proc = subprocess.Popen(["bash", str(S03_SCRIPT), "petclinic", run_dir.name], env=env, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pgid = proc.pid
    pid_file = run_dir / "pids" / "jqa-server.pid"
    try:
        deadline = time.time() + 300
        while time.time() < deadline and not pid_file.exists() and proc.poll() is None:
            time.sleep(0.1)
        assert pid_file.exists(), f"jqa-server.pid가 생기지 않았다: {proc.poll()}"
        registered = [int(p.read_text().split()[0]) for p in (run_dir / "pids").glob("*.pid")]
        os.killpg(pgid, signal.SIGINT)
        started = time.time()
        while time.time() - started < 90 and (proc.poll() is None or _group_alive(pgid)):
            time.sleep(0.5)
        elapsed = time.time() - started
        assert proc.poll() is not None and not _group_alive(pgid), f"SIGINT 뒤 {elapsed:.0f}초가 지나도 남아 있다"
    finally:
        if _group_alive(pgid):
            os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=30)
    assert registered, "등록된 PID가 없다"
    assert [pid for pid in registered if pid_alive(pid)] == []
    assert _jqa_processes(str(run_dir)) == [], "이 run의 jQA 프로세스가 남았다"
    leaked = find_leaked_resources(test_run_label)
    assert not any(leaked.values()), leaked


def test_unit_reap_pids_by_name_removes_only_those_files(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "pids").mkdir(parents=True)
    mine = subprocess.Popen(["sleep", "600"])
    other = subprocess.Popen(["sleep", "600"])
    try:
        time.sleep(0.3)
        (run_dir / "pids" / "mine.pid").write_text(f"{mine.pid}\n")
        (run_dir / "pids" / "other.pid").write_text(f"{other.pid}\n")
        envctl.reap_pids(run_dir, term_wait=5, names=["mine"])
        mine.wait(timeout=10)
        assert other.poll() is None
        assert not (run_dir / "pids" / "mine.pid").exists() and (run_dir / "pids" / "other.pid").exists()
    finally:
        other.kill()
        other.wait(timeout=10)


# --- Task 18: S04 온톨로지 시각화(REQ-016, REQ-017) --------------------------------------------------------------
# 합성 온톨로지(스키마 통과)로 렌더 결과를 본다. 실제 S03/S05 산출물이 없어도 돌고, 네트워크는 전부 막는다.
S04_SCRIPT = REPO_ROOT / "pipeline" / "S04-onto-viz.sh"
HOSTILE_LABEL = "<img src=x onerror=window.__pwned=1>&amp;</script><script>window.__pwned=2</script>"


def _synthetic_ontology(tool: str = "jqassistant", extra_nodes: int = 40) -> dict:
    kinds = ["Controller", "Service", "Repository", "Entity", "Field", "Exception", "DTO"]
    nodes = [{"id": "ep:GET /owners", "kind": "Endpoint", "label": "GET /owners",
              "props": {"method": "GET", "path": "/owners", "handler": "OwnerController#list", "view": False}},
             {"id": "ep:GET /vets", "kind": "Endpoint", "label": "GET /vets",
              "props": {"method": "GET", "path": "/vets", "handler": "VetController#list", "view": False}},
             {"id": "c:OwnerController", "kind": "Controller", "label": "OwnerController", "props": {"fqn": "a.OwnerController"}},
             {"id": "c:VetController", "kind": "Controller", "label": "VetController", "props": {}},
             {"id": "s:OwnerService", "kind": "Service", "label": "OwnerService", "props": {"n": 3, "nested": {"k": [1, 2]}}},
             {"id": "r:OwnerRepository", "kind": "Repository", "label": "OwnerRepository", "props": {}},
             {"id": "e:Owner", "kind": "Entity", "label": "Owner", "props": {}},
             {"id": "x:hostile", "kind": "Exception", "label": HOSTILE_LABEL, "props": {"note": HOSTILE_LABEL}}]
    edges = [{"source": "ep:GET /owners", "target": "c:OwnerController", "kind": "HANDLED_BY"},
             {"source": "ep:GET /vets", "target": "c:VetController", "kind": "HANDLED_BY"},
             {"source": "c:OwnerController", "target": "s:OwnerService", "kind": "DEPENDS_ON"},
             {"source": "s:OwnerService", "target": "r:OwnerRepository", "kind": "DEPENDS_ON"},
             {"source": "r:OwnerRepository", "target": "e:Owner", "kind": "MANAGES"},
             {"source": "s:OwnerService", "target": "x:hostile", "kind": "THROWS"},
             {"source": "c:OwnerController", "target": "missing:node", "kind": "DANGLING"}]  # 끝점이 없는 간선은 무시된다
    for index in range(extra_nodes):
        nodes.append({"id": f"n{index}", "kind": kinds[index % len(kinds)], "label": f"Node{index}", "props": {}})
        edges.append({"source": "c:VetController", "target": f"n{index}", "kind": "REL"})
    doc = {"nodes": nodes, "edges": edges, "meta": {"tool": tool, "version": "1", "commit": "b6f9393", "fallbacks": []}}
    jsonschema.validate(doc, json.loads(SCHEMA_FILE.read_text()))
    return doc


@pytest.fixture(scope="module")
def viz_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture(scope="module")
def viz_pages(tmp_path_factory):
    """jqa.html, owl.html을 합성 데이터로 만든다."""
    from td import ontology_html
    base = tmp_path_factory.mktemp("viz")
    out = {}
    for name, tool in (("jqa", "jqassistant"), ("owl", "owl")):
        doc = _synthetic_ontology(tool)
        source = base / f"ontology-{name}.json"
        source.write_text(json.dumps(doc))
        target = base / "ontology" / f"{name}.html"
        ontology_html.render(source, target)
        out[name] = (target, doc)
    return out


def _open_offline(browser, html_path: Path, **context_kwargs):
    """http(s) 등 file/data 이외의 요청은 모두 막고, 시도된 외부 요청과 콘솔 오류를 모은다."""
    context = browser.new_context(**context_kwargs)
    blocked, console_errors, page_errors = [], [], []

    def guard(route):
        if route.request.url.startswith(("file:", "data:")):
            route.continue_()
        else:
            blocked.append(route.request.url)
            route.abort()
    context.route("**/*", guard)
    page = context.new_page()
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.goto(html_path.as_uri())
    page.wait_for_function("window.__td_cy && window.__td_ready === true", timeout=30000)
    return context, page, blocked, console_errors, page_errors


@pytest.mark.parametrize("name", ["jqa", "owl"])
def test_req016_offline_render(viz_browser, viz_pages, name):
    """REQ-016: 네트워크를 막아도 콘솔 오류 0, 렌더된 노드 수 == JSON 노드 수. 외부 요청 시도도 0이다."""
    html_path, doc = viz_pages[name]
    context, page, blocked, console_errors, page_errors = _open_offline(viz_browser, html_path)
    try:
        assert page.evaluate("window.__td_cy.nodes().length") == len(doc["nodes"])
        assert page.evaluate("window.__td_cy.edges().length") == len(doc["edges"]) - 1  # 끝점 없는 간선 1개 제외
        assert blocked == [] and console_errors == [] and page_errors == []
        assert page.title() in ("jQA 온톨로지 그래프", "OWL 온톨로지 그래프")
    finally:
        context.close()


def test_req016_html_is_self_contained(viz_pages):
    text = viz_pages["jqa"][0].read_text()
    import re
    assert not re.search(r"""(src|href)\s*=\s*["']https?:""", text), "외부 URL을 참조한다"
    assert "<link " not in text and "<script src" not in text, "외부 파일을 참조한다"
    assert "Cytoscape Consortium" in text  # 라이브러리와 라이선스 머리말이 인라인된다


def test_req016_hostile_text_is_escaped(viz_browser, viz_pages):
    """데이터의 HTML·script 조각은 텍스트로만 보이고 실행되지 않는다."""
    html_path, _ = viz_pages["jqa"]
    context, page, blocked, console_errors, page_errors = _open_offline(viz_browser, html_path)
    try:
        page.evaluate("window.__td_select('x:hostile')")
        panel = page.locator("#panel")
        assert HOSTILE_LABEL in panel.inner_text()
        assert page.evaluate("window.__pwned") is None
        assert page.locator("#panel img, #legend img, #panel script").count() == 0
        assert console_errors == [] and page_errors == []
    finally:
        context.close()


def test_req016_filter_search_panel_and_endpoint_subgraph(viz_browser, viz_pages):
    html_path, doc = viz_pages["jqa"]
    context, page, *_ = _open_offline(viz_browser, html_path)
    try:
        visible = "window.__td_cy.nodes().filter(n => n.style('display') !== 'none').length"
        total = len(doc["nodes"])
        assert page.evaluate(visible) == total
        # kind 필터: Service 체크 해제 -> Service 노드가 숨고, 다시 켜면 돌아온다.
        service_count = sum(1 for n in doc["nodes"] if n["kind"] == "Service")
        page.locator('#legend input[data-kind="Service"]').uncheck()
        assert page.evaluate(visible) == total - service_count
        page.locator('#legend input[data-kind="Service"]').check()
        assert page.evaluate(visible) == total
        assert page.locator("#legend li").count() >= 8  # kind별 색 범례(합성 데이터는 8종 전부)
        # 검색: 일치 노드 강조와 개수 표시
        page.fill("#search", "owner")
        page.wait_for_function("window.__td_cy.nodes('.match').length > 0")
        matched = page.evaluate("window.__td_cy.nodes('.match').map(n => n.id()).sort()")
        expected = sorted(n["id"] for n in doc["nodes"] if "owner" in (n["label"] + n["id"]).lower())
        assert matched == expected
        page.fill("#search", "")
        page.wait_for_function("window.__td_cy.nodes('.match').length === 0")
        # 노드 클릭 -> 속성 패널(키·값)
        page.evaluate("window.__td_cy.getElementById('s:OwnerService').emit('tap')")
        panel_text = page.locator("#panel").inner_text()
        assert "OwnerService" in panel_text and "Service" in panel_text and "nested" in panel_text
        # 엔드포인트 하위 그래프: GET /vets 선택 -> 그 엔드포인트에서 닿는 노드만 보인다(vet 컨트롤러 + 연결된 40개 + 자신)
        page.select_option("#endpoint-select", "ep:GET /vets")
        shown = page.evaluate(f"{visible}")
        reachable = 1 + 1 + 40
        assert shown == reachable
        assert page.evaluate("window.__td_cy.getElementById('ep:GET /owners').style('display')") == "none"
        page.click("#reset-view")
        assert page.evaluate(visible) == total
    finally:
        context.close()


def test_req017_responsive_dark(viz_browser, viz_pages):
    html_path, _ = viz_pages["jqa"]
    context, page, *_ = _open_offline(viz_browser, html_path, viewport={"width": 360, "height": 740})
    try:
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        graph_box = page.locator("#cy").bounding_box()
        panel_box = page.locator("#panel").bounding_box()
        assert panel_box["y"] >= graph_box["y"] + graph_box["height"] - 1, "패널이 그래프 아래에 오지 않는다"
        assert graph_box["width"] > 200 and graph_box["height"] >= 240
        light_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        page.emulate_media(color_scheme="dark")
        dark_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert light_bg != dark_bg
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        context.close()
    # 데스크톱 폭에서는 패널이 그래프 오른쪽이다(좁을 때만 아래로 내려간다).
    context, page, *_ = _open_offline(viz_browser, html_path, viewport={"width": 1280, "height": 800})
    try:
        graph_box, panel_box = page.locator("#cy").bounding_box(), page.locator("#panel").bounding_box()
        assert panel_box["x"] >= graph_box["x"] + graph_box["width"] - 1
    finally:
        context.close()


def test_unit_ontology_html_render_escapes_script_terminator(tmp_path):
    from td import ontology_html
    doc = _synthetic_ontology()
    source = tmp_path / "o.json"
    source.write_text(json.dumps(doc))
    target = ontology_html.render(source, tmp_path / "out" / "jqa.html")
    text = Path(target).read_text()
    assert HOSTILE_LABEL not in text and "<img src=x" not in text  # 원문이 그대로 들어가면 </script>가 문서를 깬다
    assert text.count("</script>") == text.count("<script")


def test_unit_ontology_html_rejects_schema_violation(tmp_path):
    from td import ontology_html
    source = tmp_path / "bad.json"
    source.write_text(json.dumps({"nodes": [{"id": "a"}], "edges": [], "meta": {}}))
    with pytest.raises(Exception):
        ontology_html.render(source, tmp_path / "jqa.html")
    assert not (tmp_path / "jqa.html").exists()


def _s04_run(tmp_path: Path, *, jqa: bool, owl: bool, s05_status: str = "skipped") -> tuple[Path, subprocess.CompletedProcess]:
    base = tmp_path / "work"
    run_dir = base / "runs" / "20990101-000000Z-s04test-manual-00000000"
    env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
    env.update(TD_ROOT=str(REPO_ROOT), TD_WORK_DIR=str(base), TD_RUN_DIR=str(run_dir), TD_SUT_FILE=str(SUT_FILE),
               TD_SUT_COMMIT=RUN_COMMIT, TD_SITE_PREFIX="_test/s04-stage/")
    init = subprocess.run([sys.executable, "-m", "td.state", "init", str(run_dir), "--run-id", run_dir.name, "--sut",
                           "petclinic", "--commit", RUN_COMMIT], capture_output=True, text=True,
                          env={**env, "PYTHONPATH": str(REPO_ROOT / "site-gen")})
    assert init.returncode == 0, init.stderr
    (run_dir / "stages").mkdir(parents=True, exist_ok=True)

    def put(stage: str, name: str, tool: str, status: str) -> None:
        out = run_dir / stage
        out.mkdir()
        (out / name).write_text(json.dumps(_synthetic_ontology(tool)))
        (run_dir / "stages" / f"{stage}.json").write_text(json.dumps(
            {"id": stage, "status": status, "reason": None, "outputs": {"ontology": str(out / name)}}))
    if jqa:
        put("S03", "ontology-jqa.json", "jqassistant", "passed")
    else:
        (run_dir / "stages" / "S03.json").write_text(json.dumps({"id": "S03", "status": "failed", "reason": "x", "outputs": {}}))
    if owl:
        put("S05", "ontology-owl.json", "owl", "passed")
    else:
        (run_dir / "stages" / "S05.json").write_text(json.dumps({"id": "S05", "status": s05_status, "reason": "x", "outputs": {}}))
    done = subprocess.run(["bash", str(S04_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True, env=env, timeout=120)
    subprocess.run([sys.executable, "-m", "td.state", "post", str(run_dir), "S04"], capture_output=True, text=True,
                   env={**env, "PYTHONPATH": str(REPO_ROOT / "site-gen")})
    return run_dir, done


def test_s04_stage_both_inputs_passed_and_published_in_run_page(tmp_path):
    from td.site import pages
    run_dir, done = _s04_run(tmp_path, jqa=True, owl=True)
    assert done.returncode == 0, done.stderr[-1500:]
    stage = json.loads((run_dir / "stages" / "S04.json").read_text())
    assert stage["status"] == "passed", stage
    out = Path(stage["outputs"]["ontology"])
    assert (out / "jqa.html").exists() and (out / "owl.html").exists()
    site = tmp_path / "site"
    pages.render_run(run_dir, site)
    assert (site / "ontology" / "jqa.html").exists() and (site / "ontology" / "owl.html").exists()
    index = (site / "index.html").read_text()
    assert 'href="ontology/jqa.html"' in index and 'href="ontology/owl.html"' in index


def test_s04_stage_only_jqa_is_degraded(tmp_path):
    from td.site import pages
    run_dir, done = _s04_run(tmp_path, jqa=True, owl=False)
    assert done.returncode == 0, done.stderr[-1500:]
    stage = json.loads((run_dir / "stages" / "S04.json").read_text())
    assert stage["status"] == "degraded" and "S05" in stage["reason"], stage
    out = Path(stage["outputs"]["ontology"])
    assert (out / "jqa.html").exists() and not (out / "owl.html").exists()
    site = tmp_path / "site"
    pages.render_run(run_dir, site)
    index = (site / "index.html").read_text()
    assert 'href="ontology/jqa.html"' in index and "owl.html" not in index


def test_s04_stage_without_inputs_fails(tmp_path):
    run_dir, done = _s04_run(tmp_path, jqa=False, owl=False)
    stage = json.loads((run_dir / "stages" / "S04.json").read_text())
    assert done.returncode != 0 and stage["status"] == "failed", stage


# --- Task 18 보강: 실제 파이프라인(S00,S03,S04)의 진짜 ontology-jqa.json으로 REQ-016 --------------------------------
@pytest.fixture(scope="module")
def real_s04(real_pipeline_run):
    return real_pipeline_run("S00,S03,S04")


def test_req016_real_s03_ontology_renders_offline(real_s04, viz_browser):
    run_dir = real_s04.run_dir
    stages = {sid: json.loads((run_dir / "stages" / f"{sid}.json").read_text()) for sid in ("S03", "S04")}
    assert stages["S03"]["status"] in ("passed", "degraded"), stages["S03"]
    assert stages["S04"]["status"] in ("passed", "degraded"), stages["S04"]
    real_json = json.loads((run_dir / "S03" / "ontology-jqa.json").read_text())
    html_path = run_dir / "S04" / "ontology" / "jqa.html"
    assert html_path.exists() and len(real_json["nodes"]) > 10
    context, page, blocked, console_errors, page_errors = _open_offline(viz_browser, html_path)
    try:
        assert page.evaluate("window.__td_cy.nodes().length") == len(real_json["nodes"])
        assert blocked == [] and console_errors == [] and page_errors == []
        endpoint_id = next(n["id"] for n in real_json["nodes"] if n["kind"] == "Endpoint")
        page.select_option("#endpoint-select", endpoint_id)
        shown = page.evaluate("window.__td_cy.nodes().filter(n => n.style('display') !== 'none').length")
        assert 1 < shown < len(real_json["nodes"])
    finally:
        context.close()
