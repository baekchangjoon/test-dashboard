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
def viz_browser(playwright_instance):
    instance = playwright_instance.chromium.launch()
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


# =====================================================================================
# Task 24: S05 OWL 온톨로지(REQ-018, REQ-022 S05 캡처, REQ-024 OWL 스냅샷, REQ-061 owl-gen.json)
# 가짜 claude(PATH 앞)로 S05 단계 스크립트를 가짜 run 디렉터리에서 실행한다. 입력은 실제 run에서 복사한
# jQA JSON과 정제 bbtg(derive-test-data) fixture다. 스냅샷 루트는 TD_ONTOLOGY_GENERATED_DIR(임시)다.
# =====================================================================================
S05_SCRIPT = REPO_ROOT / "pipeline" / "S05-owl-build.sh"
OWL_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "owl"
SHAPES_FILE = REPO_ROOT / "ontology" / "owl" / "shapes.ttl"
OWL_GEN_SCHEMA = REPO_ROOT / "site-gen" / "td" / "schemas" / "owl-gen.schema.json"
TD_NS = "http://test-dashboard.local/ontology#"

VALID_ADDITIONS = """\
td:Owner rdfs:label "Pet owner"@en ;
    rdfs:comment "A person who registers pets and visits."@en ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty td:Owner_lastName ;
                      owl:minCardinality "1"^^xsd:nonNegativeInteger ] .
td:Pet_type a owl:FunctionalProperty ;
    rdfs:comment "The species classification of a pet."@en .
"""
BROKEN_TURTLE = 'td:Owner rdfs:label "unterminated .\n'
TAMPER_PROVENANCE = 'td:Owner td:fromJqa "entity:forged.Owner" .\n'
NEW_TERM = 'td:InventedConcept a owl:Class ; rdfs:label "Invented"@en .\n'


def owl_reply(text: str, tokens_in: int = 900, tokens_out: int = 150) -> dict:
    return {"type": "result", "subtype": "success", "is_error": False, "result": text, "duration_ms": 10,
            "usage": {"input_tokens": tokens_in, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4,
                      "output_tokens": tokens_out}}


class S05Env:
    """가짜 run 디렉터리(S02 정제 bbtg, S03 jQA JSON)를 만들고 pipeline/S05-owl-build.sh를 실행한다."""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.generated = tmp_path / "ontology-generated"
        self.count = 0

    def new_run(self) -> Path:
        from test_isolation import make_run_dir
        self.count += 1
        run_dir = make_run_dir(self.tmp_path, f"run-{self.count}")
        shutil.rmtree(run_dir / "S05")
        shutil.copyfile(OWL_FIXTURES / "ontology-jqa.json", run_dir / "S03" / "ontology-jqa.json")
        shutil.copyfile(OWL_FIXTURES / "derive-test-data.json", run_dir / "S02" / "bbtg" / "clean" / "derive-test-data.json")
        init = subprocess.run([sys.executable, "-m", "td.state", "init", str(run_dir), "--run-id", run_dir.name, "--sut",
                               "petclinic", "--commit", RUN_COMMIT], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "site-gen")})
        assert init.returncode == 0, init.stderr
        (run_dir / "stages").mkdir(exist_ok=True)
        for stage in ("S00", "S02", "S03"):
            (run_dir / "stages" / f"{stage}.json").write_text(json.dumps({"id": stage, "status": "passed", "reason": None,
                                                                          "outputs": {}}))
        (run_dir / "tools.lock").write_text("schema: 1\nclaude:\n  version: 9.9.9-test\n  model: claude-opus-5-5\n")
        return run_dir

    def env(self, run_dir: Path, **extra: str) -> dict:
        from test_isolation import FIXTURE_SUT
        env = {k: v for k, v in os.environ.items() if not k.startswith("TD_")}
        env.update(TD_ROOT=str(REPO_ROOT), TD_RUN_DIR=str(run_dir), TD_WORK_DIR=str(run_dir.parent),
                   TD_SUT_SRC=str(FIXTURE_SUT), TD_SUT_FILE=str(SUT_FILE), TD_ONTOLOGY_GENERATED_DIR=str(self.generated),
                   TD_SITE_PREFIX="_test/s05/", **extra)
        return env

    def run(self, run_dir: Path, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(S05_SCRIPT), "petclinic", run_dir.name], capture_output=True, text=True,
                              env=self.env(run_dir, **extra), timeout=600)

    def popen(self, run_dir: Path, **extra: str) -> subprocess.Popen:
        return subprocess.Popen(["bash", str(S05_SCRIPT), "petclinic", run_dir.name], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.env(run_dir, **extra))

    @staticmethod
    def stage(run_dir: Path) -> dict:
        return json.loads((run_dir / "stages" / "S05.json").read_text())

    @staticmethod
    def meta(run_dir: Path) -> dict:
        return json.loads((run_dir / "S05" / "owl-gen.json").read_text())

    def snapshots(self) -> list[Path]:
        root = self.generated / "petclinic"
        return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")) if root.exists() else []


@pytest.fixture
def s05(tmp_path) -> S05Env:
    return S05Env(tmp_path)


def _owl_tree_hashes(root: Path) -> dict[str, str]:
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*"))
            if p.is_file()}


def assert_owl_correspondence(ttl_path: Path, jqa: dict) -> dict:
    """REQ-018 판정을 rdflib/pySHACL로 직접 한다(구현 모듈의 집계 함수에 기대지 않는다)."""
    import rdflib
    from rdflib.namespace import OWL, RDF
    from pyshacl import validate
    graph = rdflib.Graph().parse(ttl_path, format="turtle")
    from_jqa = rdflib.URIRef(TD_NS + "fromJqa")
    node_ids = {n["id"] for n in jqa["nodes"]}
    entity_ids = {n["id"] for n in jqa["nodes"] if n["kind"] == "Entity"}
    classes = set(graph.subjects(RDF.type, OWL.Class))
    class_provenance = {str(o) for c in classes for o in graph.objects(c, from_jqa)}
    matched = entity_ids & class_provenance
    assert entity_ids and len(matched) / len(entity_ids) >= 0.9, (len(matched), len(entity_ids))
    object_properties = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    assert len(object_properties) >= 3
    terms = classes | object_properties | set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    for term in terms:   # 모든 클래스·속성에 jQA 노드 id를 가리키는 provenance가 있다
        values = {str(o) for o in graph.objects(term, from_jqa)}
        assert values and values <= node_ids, (term, values)
    shapes = rdflib.Graph().parse(SHAPES_FILE, format="turtle")
    conforms, _, report = validate(graph, shacl_graph=shapes)
    assert conforms, report
    violating = rdflib.Graph().parse(OWL_FIXTURES / "violating.ttl", format="turtle")
    bad_conforms, _, bad_report = validate(violating, shacl_graph=shapes)
    assert bad_conforms is False and "fromJqa" in bad_report and "range" in bad_report
    return {"graph": graph, "classes": classes, "objectProperties": object_properties}


def test_req018_owl_correspondence(s05, fake_claude):
    """S05 완료 뒤: ttl 파싱, Entity 대응 ≥ 90%와 provenance, 객체 속성 ≥ 3, shapes conforms, 위반 fixture는 false.
    LLM 보강(@en 라벨, 제약)이 골격에 합쳐지고, JSON이 온톨로지 스키마를 통과해 S04가 owl.html을 그린다."""
    import rdflib
    from td import ontology_html
    fake_claude.respond(owl_reply(VALID_ADDITIONS))
    run_dir = s05.new_run()
    done = s05.run(run_dir)
    assert done.returncode == 0, done.stderr[-3000:]
    stage = s05.stage(run_dir)
    assert stage["status"] == "passed", stage
    ttl = run_dir / "S05" / "ontology-owl.ttl"
    jqa = json.loads((OWL_FIXTURES / "ontology-jqa.json").read_text())
    checked = assert_owl_correspondence(ttl, jqa)
    graph = checked["graph"]
    owner = rdflib.URIRef(TD_NS + "Owner")
    assert rdflib.Literal("Pet owner", lang="en") in set(graph.objects(owner, rdflib.RDFS.label))
    assert (rdflib.URIRef(TD_NS + "Pet_type"), rdflib.RDF.type, rdflib.OWL.FunctionalProperty) in graph
    # 시각화용 JSON: 스키마 통과, Entity 노드와 객체 속성 간선, S04 렌더
    doc = json.loads((run_dir / "S05" / "ontology-owl.json").read_text())
    jsonschema.validate(doc, json.loads(SCHEMA_FILE.read_text()))
    assert doc["meta"]["tool"] == "owl" and doc["meta"]["commit"] == RUN_COMMIT
    entity_nodes = [n for n in doc["nodes"] if n["kind"] == "Entity"]
    assert len(entity_nodes) == len([n for n in jqa["nodes"] if n["kind"] == "Entity"])
    assert all(n["props"]["fromJqa"] for n in doc["nodes"])
    owner_node = next(n for n in entity_nodes if n["props"]["iri"] == TD_NS + "Owner")
    assert owner_node["label"] == "Pet owner" and owner_node["props"]["comment"]
    entity_iris = {n["id"] for n in entity_nodes}
    assert len([e for e in doc["edges"] if e["source"] in entity_iris and e["target"] in entity_iris]) >= 3
    assert any(n["kind"] == "Endpoint" for n in doc["nodes"])
    ontology_html.render(run_dir / "S05" / "ontology-owl.json", tmp := run_dir / "S04" / "owl.html", "owl")
    assert tmp.exists()
    # 단계 산출물 경로: S04가 outputs.ontology를 읽고, S06 owl arm은 S05/ontology-owl.ttl을 번들에 넣는다
    assert stage["outputs"]["ontology"] == str(run_dir / "S05" / "ontology-owl.json")
    assert stage["outputs"]["ttl"] == str(ttl)
    assert (run_dir / "S05" / "bundle" / "ontology" / "skeleton.ttl").is_file()


def test_req018_skeleton_is_deterministic_and_complete():
    """골격은 jQA JSON + 정제 bbtg의 결정적 함수다(두 번 만들면 바이트 동일). LLM 없이도 대응·provenance·shapes를 만족한다."""
    from td import ontology_owl
    jqa = json.loads((OWL_FIXTURES / "ontology-jqa.json").read_text())
    bbtg = {"derive-test-data": json.loads((OWL_FIXTURES / "derive-test-data.json").read_text())}
    first = ontology_owl.serialize(ontology_owl.skeleton(jqa, bbtg))
    second = ontology_owl.serialize(ontology_owl.skeleton(json.loads(json.dumps(jqa)), bbtg))
    assert first == second
    path = Path(__import__("tempfile").mkdtemp()) / "skeleton.ttl"
    path.write_text(first)
    checked = assert_owl_correspondence(path, jqa)
    names = {str(p).split("#")[1] for p in checked["objectProperties"]}
    # bbtg 관계(OneToMany 등)와 필드 이름으로 정한 속성 이름: 필드 타입 일치, bbtg 관계 유일 후보, 그 밖은 일반 이름
    assert {"Pet_type", "Owner_pets", "Pet_visits", "Vet_specialties"} <= names, names
    assert "petclinic" not in (REPO_ROOT / "site-gen" / "td" / "ontology_owl.py").read_text().lower()
    assert "petclinic" not in (REPO_ROOT / "prompts" / "owl-gen.md").read_text().lower()


def test_unit_owl_additions_contract():
    """LLM 추가분 계약: 골격의 기존 용어(또는 제한용 빈 노드)만 설명하고, provenance(td:fromJqa, td:kind)는 쓸 수 없다."""
    from td import ontology_owl
    jqa = json.loads((OWL_FIXTURES / "ontology-jqa.json").read_text())
    skeleton = ontology_owl.skeleton(jqa, {})
    merged, problems = ontology_owl.merge_additions(skeleton, VALID_ADDITIONS)
    assert problems == [] and len(merged) > len(skeleton)
    for text, needle in ((BROKEN_TURTLE, "Turtle"), (TAMPER_PROVENANCE, "fromJqa"), (NEW_TERM, "InventedConcept"),
                         ('td:Owner rdfs:subClassOf [ a owl:Restriction ; owl:onProperty td:NoSuchProperty ; '
                          'owl:maxCardinality 1 ] .\n', "NoSuchProperty"),
                         ('td:Owner rdfs:domain td:Pet .\n', "domain")):
        merged, problems = ontology_owl.merge_additions(skeleton, text)
        assert problems and any(needle in p for p in problems), (text, problems)
        assert merged is None
    # 골격의 provenance는 합친 뒤에도 그대로다
    merged, _ = ontology_owl.merge_additions(skeleton, VALID_ADDITIONS)
    from_jqa = __import__("rdflib").URIRef(TD_NS + "fromJqa")
    assert set(skeleton.triples((None, from_jqa, None))) == set(merged.triples((None, from_jqa, None)))


def test_unit_owl_additions_type_placement():
    """owl:Restriction 타입은 빈 노드에만, 속성 특성 타입(FunctionalProperty 등)은 골격의 속성에만 붙일 수 있다."""
    from td import ontology_owl
    jqa = json.loads((OWL_FIXTURES / "ontology-jqa.json").read_text())
    skeleton = ontology_owl.skeleton(jqa, {})
    for text, needle in (('td:Owner a owl:Restriction .\n', "owl:Restriction"),
                         ('td:Owner a owl:FunctionalProperty .\n', "FunctionalProperty"),
                         ('td:Owner rdfs:subClassOf [ a owl:Restriction , owl:TransitiveProperty ; '
                          'owl:onProperty td:Owner_lastName ; owl:minCardinality 1 ] .\n', "TransitiveProperty")):
        merged, problems = ontology_owl.merge_additions(skeleton, text)
        assert merged is None and any(needle in p for p in problems), (text, problems)
    merged, problems = ontology_owl.merge_additions(skeleton, VALID_ADDITIONS)
    assert problems == [] and merged is not None


def test_owl_unexpected_error_fails_stage_and_writes_meta(s05, fake_claude, monkeypatch):
    """OwlGenError가 아닌 예외(예: JSON 변환 오류)도 failed로 마감하고 owl-gen.json을 쓴다. 산출물은 남기지 않는다."""
    from td import ontology_owl
    fake_claude.respond(owl_reply(VALID_ADDITIONS))
    assert s05.run(s05.new_run()).returncode == 0   # 스냅샷을 만든다(이후 재사용 경로에서는 claude를 부르지 않는다)
    run_dir = s05.new_run()
    for key, value in s05.env(run_dir).items():
        monkeypatch.setenv(key, value)

    def boom(graph, meta=None):
        raise RuntimeError("boom-json")

    monkeypatch.setattr(ontology_owl, "to_json", boom)
    result = ontology_owl.run_stage(run_dir, os.environ["TD_SUT_FILE"], os.environ["TD_SUT_SRC"])
    assert result["status"] == "failed" and "boom-json" in result["reason"]
    meta = s05.meta(run_dir)
    assert meta["status"] == "failed" and "boom-json" in meta["reason"] and meta["reused"] is True
    assert not (run_dir / "S05" / "ontology-owl.json").exists() and not (run_dir / "S05" / ontology_owl.TTL_NAME).exists()
    assert len(fake_claude.calls) == 1


def test_owl_require_snapshot_fails_before_claude(s05, fake_claude):
    """TD_OWLGEN_REQUIRE_SNAPSHOT=1이면 입력 키의 스냅샷이 없을 때 claude를 부르지 않고 failed다(E2E 테스트의 비용 보호)."""
    fake_claude.respond(owl_reply(VALID_ADDITIONS))
    run_dir = s05.new_run()
    done = s05.run(run_dir, TD_OWLGEN_REQUIRE_SNAPSHOT="1")
    assert done.returncode != 0 and s05.stage(run_dir)["status"] == "failed"
    assert "TD_OWLGEN_REQUIRE_SNAPSHOT" in s05.stage(run_dir)["reason"]
    assert fake_claude.calls == [] and s05.snapshots() == []
    assert s05.meta(run_dir)["status"] == "failed"
    # 스냅샷이 있으면 같은 설정으로 재사용한다
    assert s05.run(s05.new_run()).returncode == 0 and len(fake_claude.calls) == 1
    again = s05.new_run()
    assert s05.run(again, TD_OWLGEN_REQUIRE_SNAPSHOT="1").returncode == 0 and len(fake_claude.calls) == 1
    assert s05.meta(again)["reused"] is True


def test_req022_s05_stage_level_capture(s05, fake_claude, claude_call_log):
    """S05 단계 수준: 생성과 수리 호출이 모두 llm.sh를 거친다(cwd = 번들 임시 디렉터리, 격리 플래그, stdin에 SUT 소스 없음).
    수리 입력은 오류 문구와 직전 출력뿐이다(번들은 llm.sh가 뒤에 붙인다)."""
    from test_isolation import FIXTURE_SUT
    fake_claude.respond_sequence([owl_reply(BROKEN_TURTLE), owl_reply(VALID_ADDITIONS)])
    run_dir = s05.new_run()
    done = s05.run(run_dir)
    assert done.returncode == 0, done.stderr[-3000:]
    calls = fake_claude.calls
    assert len(calls) == 2
    sut_text = [line.strip() for p in (FIXTURE_SUT / "src").rglob("*") if p.is_file()
                for line in p.read_text(errors="replace").splitlines() if len(line.strip()) > 30]
    cwds = set()
    for call in calls:
        cwd = Path(call.cwd).resolve()
        cwds.add(cwd)
        assert cwd.name == "cwd" and cwd.parent.name.startswith("td-llm.")
        for forbidden in (REPO_ROOT, FIXTURE_SUT, run_dir):
            assert not cwd.is_relative_to(Path(forbidden).resolve()), (cwd, forbidden)
        assert not cwd.exists()
        argv = call.argv
        assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv
        assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
        assert argv[argv.index("--setting-sources") + 1] == ""
        assert not [line for line in sut_text if line in call.stdin]
        assert "TD_SUT_PASS" not in call.env and "TD_SUT_USER" not in call.env
        assert "=== FILE: ontology/skeleton.ttl ===" in call.stdin and "=== FILE: bbtg/derive-test-data.json ===" in call.stdin
        assert "=== FILE: harness/CONTRACT.md ===" not in call.stdin
    assert len(cwds) == 2
    repair_head = calls[1].stdin.split("=== FILE:")[0]
    assert "=== ERRORS ===" in repair_head and "=== PREVIOUS OUTPUT ===" in repair_head
    assert BROKEN_TURTLE.strip() in repair_head and "Turtle" in repair_head
    assert len(claude_call_log(run_dir)) == 2
    meta = s05.meta(run_dir)
    assert meta["repairs"] == 1 and meta["status"] == "passed"


def test_req024_owl_snapshot_reuse_and_tamper(s05, fake_claude):
    """같은 입력 키의 스냅샷이 있으면 claude를 부르지 않고 재사용한다. 변조된 스냅샷은 재사용도 덮어쓰기도 하지 않는다."""
    fake_claude.respond(owl_reply(VALID_ADDITIONS))
    first = s05.new_run()
    assert s05.run(first).returncode == 0
    [snapshot] = s05.snapshots()
    assert (snapshot / "_COMPLETE").is_file() and (snapshot / "ontology-owl.ttl").is_file()
    key = s05.meta(first)["inputHash"]
    assert snapshot.name == key[:8] and len(key) == 64
    assert (first / "S05" / "ontology-owl.ttl").read_bytes() == (snapshot / "ontology-owl.ttl").read_bytes()
    second = s05.new_run()
    done = s05.run(second)
    assert done.returncode == 0, done.stderr[-2000:]
    assert len(fake_claude.calls) == 1                                 # 재사용: claude 0회
    meta = s05.meta(second)
    assert meta["reused"] is True and meta["inputHash"] == key and s05.stage(second)["status"] == "passed"
    assert (second / "S05" / "ontology-owl.ttl").read_bytes() == (snapshot / "ontology-owl.ttl").read_bytes()
    assert (second / "S05" / "bundle" / "ontology" / "skeleton.ttl").is_file()   # 재사용해도 번들은 조립·보존한다
    # 변조: 재사용·덮어쓰기 없이 failed
    ttl = snapshot / "ontology-owl.ttl"
    ttl.write_text(ttl.read_text() + "\n# tampered\n")
    before = _owl_tree_hashes(snapshot)
    third = s05.new_run()
    done = s05.run(third)
    assert done.returncode != 0 and s05.stage(third)["status"] == "failed"
    assert "_COMPLETE" in s05.stage(third)["reason"]
    assert len(fake_claude.calls) == 1 and _owl_tree_hashes(snapshot) == before
    leftovers = [p for p in (s05.generated / "petclinic").rglob("*") if p.is_dir() and
                 (p.name.startswith(".tmp-") or p.parent.name == ".reserve")]
    assert leftovers == []


def test_req024_owl_concurrent_same_input_writes_once(s05, fake_claude):
    """같은 입력의 S05 두 개를 동시에 돌리면 claude는 1회, 한쪽은 예약이 풀린 뒤 스냅샷을 재사용한다."""
    fake_claude.respond(owl_reply(VALID_ADDITIONS))
    fake_claude.delay(4)
    runs = [s05.new_run(), s05.new_run()]
    procs = [s05.popen(run_dir) for run_dir in runs]
    for proc in procs:
        _, err = proc.communicate(timeout=300)
        assert proc.returncode == 0, err[-2000:]
    assert len(fake_claude.calls) == 1
    assert sorted(s05.meta(run_dir)["reused"] for run_dir in runs) == [False, True]
    assert len(s05.snapshots()) == 1


def test_owl_repair_bounded_then_fails_without_snapshot(s05, fake_claude):
    """수리는 최대 2회다. [provenance 위조, 깨진 Turtle, 깨진 Turtle] -> 호출 3회, S05 failed, 스냅샷 없음.
    [새 용어, 정상] -> 수리 1회로 passed, 위조나 새 용어는 결과에 없다."""
    fake_claude.respond_sequence([owl_reply(TAMPER_PROVENANCE), owl_reply(BROKEN_TURTLE), owl_reply(BROKEN_TURTLE)])
    run_dir = s05.new_run()
    done = s05.run(run_dir)
    assert done.returncode != 0
    stage = s05.stage(run_dir)
    assert stage["status"] == "failed" and "2" in stage["reason"], stage
    assert len(fake_claude.calls) == 3 and s05.snapshots() == []
    meta = s05.meta(run_dir)
    assert meta["repairs"] == 2 and meta["status"] == "failed"
    assert not (run_dir / "S05" / "ontology-owl.ttl").exists()

    fake_claude.respond_sequence([owl_reply(NEW_TERM)] * 4 + [owl_reply(VALID_ADDITIONS)])  # 호출 수는 전체 기준(4번째부터)
    run_dir = s05.new_run()
    done = s05.run(run_dir)
    assert done.returncode == 0, done.stderr[-2000:]
    assert len(fake_claude.calls) == 5 and s05.meta(run_dir)["repairs"] == 1
    text = (run_dir / "S05" / "ontology-owl.ttl").read_text()
    assert "InventedConcept" not in text and "forged" not in text


def test_owl_malformed_llm_reply_fails_without_repair(s05, fake_claude):
    """claude 응답 자체가 오류(is_error)면 수리하지 않고 S05 failed(사유 포함), 스냅샷 없음."""
    fake_claude.respond({"type": "result", "subtype": "error", "is_error": True, "result": "boom"})
    run_dir = s05.new_run()
    done = s05.run(run_dir)
    assert done.returncode != 0 and s05.stage(run_dir)["status"] == "failed"
    assert len(fake_claude.calls) == 1 and s05.snapshots() == []
    assert s05.meta(run_dir)["repairs"] == 0


def test_req061_owl_gen_metadata_schema(s05, fake_claude):
    """owl-gen.json: 입력 해시, 프롬프트 해시, 모델, CLI 버전, 플래그, 수리 횟수, 토큰, 시간, strippedFields가 스키마를 통과한다."""
    fake_claude.respond(owl_reply(VALID_ADDITIONS, tokens_in=1200, tokens_out=300))
    run_dir = s05.new_run()
    assert s05.run(run_dir).returncode == 0
    meta = s05.meta(run_dir)
    schema = json.loads(OWL_GEN_SCHEMA.read_text())
    jsonschema.validate(meta, schema)
    import hashlib
    assert meta["promptHash"] == hashlib.sha256((REPO_ROOT / "prompts" / "owl-gen.md").read_bytes()).hexdigest()
    assert meta["model"] == "claude-opus-5-5" and meta["cliVersion"] == "9.9.9-test"
    assert any(flag.startswith("--tools") for flag in meta["flags"]) and meta["repairs"] == 0
    assert meta["tokens"] == {"in": 1207, "out": 300} and meta["seconds"] >= 0
    assert meta["strippedFields"] == ["a/b"] and meta["bundleHash"] and meta["conforms"] is True
    assert meta["stats"]["entityCoverage"] >= 0.9 and meta["stats"]["objectProperties"] >= 3
    for required in ("inputHash", "promptHash", "model", "cliVersion", "flags", "repairs", "tokens", "seconds",
                     "strippedFields"):
        broken = {k: v for k, v in meta.items() if k != required}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)


def test_s05_injected_bundle_contamination_fails_before_llm(s05, fake_claude, tmp_path):
    """S05 번들도 A1 검사를 거친다: SUT docs 파일을 주입하면 LLM 호출 전에 failed."""
    from test_isolation import FIXTURE_SUT
    fake_claude.respond(owl_reply(VALID_ADDITIONS))
    doc = tmp_path / "design.md"
    doc.write_text("# notes\n")
    run_dir = s05.new_run()
    done = s05.run(run_dir, TD_BUNDLE_EXTRA=str(doc))
    assert done.returncode != 0 and s05.stage(run_dir)["status"] == "failed"
    assert "A1" in s05.stage(run_dir)["reason"] and fake_claude.calls == []


# --- 실제 파이프라인: 커밋된 OWL 스냅샷 재사용(claude 0회), 실제 데이터 대응, owl.html 오프라인 렌더 -----------------
@pytest.fixture(scope="module")
def real_s05(real_pipeline_run):
    return real_pipeline_run("S00,S02,S03,S05,S04")


def test_req018_real_owl_snapshot_and_render(real_s05, viz_browser, claude_call_log):
    run_dir = real_s05.run_dir
    stages = {sid: json.loads((run_dir / "stages" / f"{sid}.json").read_text()) for sid in ("S03", "S05", "S04")}
    assert stages["S05"]["status"] == "passed", stages["S05"]
    meta = json.loads((run_dir / "S05" / "owl-gen.json").read_text())
    assert meta["reused"] is True, "커밋된 ontology/generated 스냅샷을 재사용해야 한다(입력 키가 바뀌었으면 스냅샷을 다시 만든다)"
    assert claude_call_log(run_dir) == []
    snapshot = REPO_ROOT / "ontology" / "generated" / "petclinic" / meta["inputHash"][:8]
    assert (snapshot / "_COMPLETE").is_file()
    jqa = json.loads((run_dir / "S03" / "ontology-jqa.json").read_text())
    assert_owl_correspondence(run_dir / "S05" / "ontology-owl.ttl", jqa)
    assert stages["S04"]["status"] == "passed", stages["S04"]
    html_path = run_dir / "S04" / "ontology" / "owl.html"
    doc = json.loads((run_dir / "S05" / "ontology-owl.json").read_text())
    context, page, blocked, console_errors, page_errors = _open_offline(viz_browser, html_path)
    try:
        assert page.evaluate("window.__td_cy.nodes().length") == len(doc["nodes"])
        assert blocked == [] and console_errors == [] and page_errors == []
    finally:
        context.close()
