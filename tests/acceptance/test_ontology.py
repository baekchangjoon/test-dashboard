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
from td import ontology_jqa

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
    _require_prerequisites()
    return _run_s03(tmp_path_factory.mktemp("s03-default"))


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
    with pytest.raises(Exception, match="sha256"):
        ontology_jqa.verify_plugin(repo)


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
    assert find_leaked_resources(test_run_label) == {} or not any(find_leaked_resources(test_run_label).values())
