# test-dashboard 화면 재설계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 첫 화면을 과제 목록과 품질 상태 중심으로 다시 만들고, 과제 페이지·run 페이지·리포트를 한 디자인으로 잇고, 새 hotspot·TIA 리포트를 싣는다.

**구조:** 지금의 Jinja 정적 생성(`td.site`)을 넓힌다. 설정(`dashboard.yaml`)과 수집 스냅숏(GitHub CI, SonarQube)과 run 산출물을 `td.site.index.rebuild`가 읽어 HTML과 JSON을 만든다. 상호작용은 `static/v2/app.js` 하나가 서버가 그린 HTML에 덧입힌다. 수집은 게시의 인덱스 단계 안에서만 돈다.

**기술:** Python 3.12(uv, `site-gen/`), Jinja2, jsonschema, PyYAML, boto3, bash, 순수 JS/CSS/SVG, pytest + Playwright(chromium).

**설계:** `docs/superpowers/specs/2026-11-22-dashboard-ui-design.md` (v2.1)
**요구사항명세:** `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md` (REQ-076~139)
**시안:** `docs/superpowers/specs/assets/2026-11-22-dashboard-ui/home.html`, `project.html` — 배치·색·문구의 기준이다.

## 전역 제약

- 생성물에 외부 요청이 없다: CDN, 웹폰트, `@import`, 사이트 밖 `<script src>`·`<link>` 금지. 외부 라이브러리를 새로 넣지 않는다.
- 스크립트가 꺼져도 과제 목록·수치·모든 탭 구역이 보인다. 서버가 HTML을 먼저 그리고 `app.js`는 덧입히기만 한다.
- 측정하지 않은 값은 `null`로 다루고 화면에는 "측정 없음"·"연결 없음"·"—"로 쓴다. 0으로 채우지 않는다.
- 인덱스 재생성은 멱등이다. 실행 시각·난수·정렬되지 않은 순회를 출력에 쓰지 않는다. 수는 단위별 고정 자릿수로 적는다.
- `site-gen/td/site/static/site.css`와 `site.js`는 한 글자도 바꾸지 않는다. 새 화면은 `static/v2/app.css`, `static/v2/app.js`만 쓴다.
- `suts/<sut>/runs/<runId>/` 아래 페이지의 링크는 바뀌지 않는 주소만 가리킨다(SUT는 `suts/<sut>/index.html`). run 렌더는 `dashboard.yaml`을 읽지 않는다.
- 새로 쓰는 모든 게시 파일은 `td.redact`와 업로드 게이트를 지난다. 토큰 평문은 환경 변수 `SONAR_TOKEN`으로만 다룬다.
- `pipeline/`, `site-gen/` 코드에 `petclinic`, `org.springframework.samples` 문자열을 넣지 않는다(PoC REQ-050).
- 테스트는 `tests/acceptance/`의 pytest, 이름은 `test_req<NNN>_<요약>`. 테스트가 띄운 프로세스는 PID를 잡아 모든 종료 경로에서 정리한다. 전제가 없으면 skip이 아니라 실패다.
- 산문·주석·문서는 한국어, 식별자·커밋 메시지는 영어. 커밋 메시지 끝에 저장소의 Co-Authored-By 규칙을 따른다.
- 실행 명령: `uv run --project site-gen pytest tests/acceptance/<파일> -v`.
- 범위가 늘면 멈추고 요구사항명세에 REQ를 추가한 뒤 재개한다.

## 검토 초점

설계가 말하지 않지만 실제로 만날 입력이다. 각 줄의 테스트는 괄호 안 Task에 넣었다.

1. 과제 이름·설명·검사 이름에 `<`, `&`, 따옴표가 있다 → HTML과 JSON 블록 양쪽에서 이스케이프돼 그대로 글자로 보인다. (Task 9)
2. 미러의 스냅숏 파일이 깨졌거나 스키마를 어긴다 → 재생성이 죽지 않고 그 과제의 수집 값만 없음으로 두며 `projects.json`에 사유를 적는다. (Task 3)
3. 과제가 0개다(빈 설정, run 없음) → 홈이 "등록된 과제가 없습니다"를 보이고 결론 문장·요약이 0으로 나누지 않는다. (Task 9)
4. run이 하나뿐이거나 모든 run에 값이 없다 → 차트가 점 하나(선 없음) 또는 축만 그린다. (Task 3)
5. 주소의 `#`이 없는 탭이거나 설정에서 뺀 탭이다 → 첫 탭이 열린다. (Task 10)

## 파일 구조

| 파일 | 책임 |
|---|---|
| `dashboard.yaml` | 운영 설정(과제 20개, 기본 규칙) |
| `site-gen/td/dashboard_config.py` | 설정 읽기·검증, 지표 카탈로그, 값 표기, 상태 판정, 결론 문장 |
| `site-gen/td/schemas/dashboard.schema.json`, `project-snapshot.schema.json` | 스키마 |
| `site-gen/td/collect.py` | GitHub·Sonar 수집, 스냅숏 쓰기 |
| `pipeline/collect.sh` | 토큰 발급·정리 + `td.collect` 실행 |
| `pipeline/publish-index.sh` | 인덱스 전용 게시 진입점 |
| `pipeline/lib/sonar-token.sh` | 단계에 묶이지 않는 토큰 함수 + S11용 얇은 덮개 |
| `site-gen/td/site/metrics.py` | run 지표 추출, 과제 뷰 조립, 시계열 |
| `site-gen/td/site/charts.py` | 시계열 SVG |
| `site-gen/td/site/nav.py` | 공통 띠 HTML과 외부 리포트 주입 |
| `site-gen/td/site/index.py` | `rebuild` (조립만) |
| `site-gen/td/site/pages.py`, `layout.py` | run 렌더, 리포트 카드 |
| `site-gen/td/site/templates/*.j2` | 새 틀 |
| `site-gen/td/site/static/v2/app.css`, `app.js` | 새 디자인 |
| `site-gen/td/publish.py` | 인덱스 단계 공용화, 인덱스 전용 게시, 과제 삭제 |
| `tests/acceptance/dashboard_fixtures.py` | 고정 사이트, 서버, 가짜 gh·ssh |

`index.py`는 지금 173줄이다. 지표·차트·띠를 새 모듈로 빼서 조립만 남긴다.

---

### Task 1: 설정 파일과 지표 카탈로그

**REQ-IDs:** REQ-076, REQ-077, REQ-078

**Files:**
- Create: `site-gen/td/dashboard_config.py`, `site-gen/td/schemas/dashboard.schema.json`, `dashboard.yaml`
- Test: `tests/acceptance/test_dashboard_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(Exception)` — 메시지는 `<키 경로>: <사유>`.
  - `@dataclass(frozen=True) class Project: name: str; repo: str | None; sonar_key: str | None; sut: str | None; implicit: bool = False`
  - `@dataclass(frozen=True) class Config: projects: tuple[Project, ...]; status: dict; home: dict; project: dict`
  - `@dataclass(frozen=True) class Metric: name: str; label: str; unit: str; scope: str` — `unit`은 `ratio|percent|count|seconds|score|string|bool|list`, `scope`는 `run|snapshot|both|aggregate`.
  - `CATALOG: dict[str, Metric]` — 설계 §6.2의 과제 지표와 집계 지표 전부. `COLUMN_IDS`, `TAB_IDS`: 설계의 열·탭 식별자 튜플.
  - `load(path: Path, suts_dir: Path) -> Config` — 스키마와 등록 규칙 검증.
  - `empty() -> Config` — 과제 없음, 기본 `status`·`home`·`project`(설계 §6.2 예시 값).
  - `resolve(env: Mapping[str, str], repo_root: Path) -> Config` — `TD_DASHBOARD_CONFIG`가 있으면 그 파일, 없고 `TD_SITE_PREFIX`가 있으면 `empty()`, 둘 다 없으면 `repo_root/dashboard.yaml`.
  - `with_implicit(cfg: Config, suts_with_runs: Iterable[str]) -> Config` — 어느 과제에도 이어지지 않은 SUT를 `Project(name=sut, repo=None, sonar_key=None, sut=sut, implicit=True)`로 더한다. 이름이 겹치면 `ConfigError`.
  - `format_value(metric: str, value) -> str` — `ratio`는 `41.5%`(소수 1자리), `percent`는 `57.1%`, `count`는 정수, `seconds`는 `8분 35초`, `score`는 소수 1자리, `list`는 `, `로 이음, `None`은 `—`.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `test_dashboard_config.py`

```python
def test_req076_schema_violation_fails(tmp_path):
    # 각각: projects 키 없음 / schema: 2 / status.rules가 문자열
    for body, where in CASES_076:
        path = write(tmp_path, body)
        with pytest.raises(ConfigError) as exc:
            dashboard_config.load(path, SUTS_DIR)
        assert where in str(exc.value)          # 예: "status.rules"
    proc = run_rebuild(tmp_path / "site", config=path)   # python -m td.site.index <site> --config <path>
    assert proc.returncode != 0 and "status.rules" in proc.stderr
    assert not (tmp_path / "site" / "index.html").exists()

def test_req077_project_registration_rules(tmp_path):
    # name "a/b", name "..", name "Foo"+"foo", 같은 repo 둘, sut: nope, 한 sut를 둘이 가리킴
    for body, word in CASES_077:
        with pytest.raises(ConfigError, match=word):
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
    cfg = dashboard_config.load(write(tmp_path, ONE_PROJECT_NAMED_MINI), SUTS_DIR)
    with pytest.raises(ConfigError, match="mini"):
        dashboard_config.with_implicit(cfg, ["mini"])

def test_req078_unknown_metric_or_operator(tmp_path):
    for body, word in [(RULE_WITH("ci.nope"), "ci.nope"), (RULE_OP("between"), "between"),
                       (COLUMN("foo"), "foo"), (TAB("foo"), "foo"), (REASON("{ci.nope}"), "ci.nope")]:
        with pytest.raises(ConfigError, match=re.escape(word)):
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
    assert dashboard_config.load(REPO_ROOT / "dashboard.yaml", REPO_ROOT / "suts").projects
```

- [ ] **Step 2: 실패를 확인한다** — `uv run --project site-gen pytest tests/acceptance/test_dashboard_config.py -v` → `ModuleNotFoundError: td.dashboard_config`
- [ ] **Step 3: 스키마와 `dashboard_config.py`를 쓴다.** 스키마는 `additionalProperties: false`. 조건은 `{metric, op, value}` 또는 `{all: [조건...]}`의 재귀 정의. 스키마 뒤의 추가 검증: 이름 문법 `^[A-Za-z0-9][A-Za-z0-9._-]*$`와 `..` 금지, 대소문자 무시 유일, `repo` 유일, `sut`의 `suts_dir/<sut>/sut.yaml` 존재와 유일, 규칙·요약·시계열·치환 이름이 `CATALOG`에(집계 지표는 `home.summary`에만), 열·탭 이름이 `COLUMN_IDS`·`TAB_IDS`에 있는지.
- [ ] **Step 4: `dashboard.yaml`을 쓴다.** 설계 §6.2의 예시 그대로에, 과제는 설계의 표 20개. `spring-petclinic`은 `sut: petclinic`, `MailosaurDemo`는 `sonarKey: MailoSaurDemo`, `VcsStatistics`는 `sonarKey: vcsstatistics`.
- [ ] **Step 5: 통과를 확인한다** — 같은 명령, 3개 PASS
- [ ] **Step 6: 커밋** — `feat(config): dashboard.yaml schema, metric catalog and registration checks`

### Task 2: 상태 판정과 결론 문장

**REQ-IDs:** REQ-081, REQ-082, REQ-084

**Files:**
- Modify: `site-gen/td/dashboard_config.py`
- Test: `tests/acceptance/test_dashboard_status.py`

**Interfaces:**
- Consumes: Task 1의 `Config`, `CATALOG`, `format_value`.
- Produces:
  - `@dataclass(frozen=True) class Verdict: level: str; reasons: tuple[str, ...]; partial: bool`
  - `evaluate(values: Mapping[str, object], cfg: Config) -> Verdict` — `values`는 지표 이름 → 값(없으면 키가 없거나 `None`). 순서는 설계 §6.2 "상태 판정 순서". `partial`은 `ci.runs`와 `sonar.gate` 가운데 정확히 하나만 있을 때 참.
  - `headline(values: Mapping[str, object], verdict: Verdict, cfg: Config) -> str` — 위험·주의면 `"<상태 이름>: <사유 · 사유>"`, 측정 없음이면 `"측정된 지표가 없습니다"`, 양호면 `project.headline`의 처음 걸린 문장(치환할 값이 없으면 건너뜀).
  - `rules_text(cfg: Config) -> list[str]` — 각주용. 수준마다 한 문장: `"위험: Sonar 품질 게이트 실패 / 기본 브랜치의 최근 CI 실패 / …"`. 조건의 임계값을 문장에 넣는다(`ci.successRate < 90.0%`).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
CFG = dashboard_config.empty()   # 설계 §6.2의 기본 규칙

@pytest.mark.parametrize("values, level, reasons", [
    ({"sonar.gate": "ERROR", "ci.runs": 9, "ci.successRate": 1.0, "ci.lastFailed": False, "ci.failedChecks": 0},
     "crit", ("Sonar 품질 게이트 실패",)),
    ({"sonar.gate": "OK", "ci.runs": 9, "ci.successRate": 1.0, "ci.lastFailed": True, "ci.failedChecks": 0},
     "crit", ("기본 브랜치의 최근 CI 실패",)),
    ({"sonar.gate": "OK", "ci.runs": 2, "ci.lastFailed": False, "ci.failedChecks": 1, "ci.failedCheckNames": ["build-and-test"]},
     "crit", ("최신 커밋의 검사 실패: build-and-test",)),
    ({"sonar.gate": "OK", "ci.runs": 11, "ci.failures": 6, "ci.successRate": 5 / 11, "ci.lastFailed": False, "ci.failedChecks": 0},
     "warn", ("최근 CI 11회 중 6회 실패",)),
    ({"sonar.gate": "OK", "sonar.vulnerabilities": 8, "ci.runs": 17, "ci.successRate": 1.0, "ci.lastFailed": False, "ci.failedChecks": 0},
     "warn", ("Sonar 취약점 8건",)),
    ({"sonar.gate": "ERROR", "sonar.vulnerabilities": 2, "ci.runs": 30, "ci.successRate": 0.9, "ci.lastFailed": False, "ci.failedChecks": 0},
     "crit", ("Sonar 품질 게이트 실패", "Sonar 취약점 2건")),
    ({"sonar.gate": "OK", "sonar.vulnerabilities": 0, "ci.runs": 30, "ci.successRate": 1.0, "ci.lastFailed": False, "ci.failedChecks": 0},
     "good", ()),
])
def test_req081_rule_levels_and_reasons(values, level, reasons):
    verdict = dashboard_config.evaluate(values, CFG)
    assert (verdict.level, verdict.reasons) == (level, reasons)

def test_req082_missing_and_boundaries():
    ev = lambda v: dashboard_config.evaluate(v, CFG)
    assert ev({}).level == "none"
    assert ev({"ci.runs": None, "sonar.gate": None}).level == "none"
    four = {"ci.runs": 4, "ci.failures": 3, "ci.successRate": 0.25, "ci.lastFailed": False, "ci.failedChecks": 0}
    assert ev(four).level == "good" and ev(four).partial is True
    five = {"ci.runs": 5, "ci.failures": 1, "ci.successRate": 0.8, "ci.lastFailed": False, "ci.failedChecks": 0, "sonar.gate": "OK"}
    assert ev(five).level == "warn" and ev(five).partial is False
    assert ev({"sonar.gate": "OK"}).level == "good"      # sonar.vulnerabilities 없음 → 그 규칙은 안 걸림

def test_req084_headline_selection():
    hl = lambda v: dashboard_config.headline(v, dashboard_config.evaluate(v, CFG), CFG)
    assert hl({"sonar.gate": "ERROR", "sonar.vulnerabilities": 2}) == "위험: Sonar 품질 게이트 실패 · Sonar 취약점 2건"
    assert hl({}) == "측정된 지표가 없습니다"
    good = {"sonar.gate": "OK", "tests.passRate": 1.0, "coverage.line": 0.415}
    assert hl(good) == "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 41.5%입니다"
    for rate in (0.97, None):
        assert "모두 통과" not in hl({"sonar.gate": "OK", "tests.passRate": rate, "coverage.line": 0.415})
```

- [ ] **Step 2: 실패를 확인한다** → `AttributeError: evaluate`
- [ ] **Step 3: `evaluate`, `headline`, `rules_text`를 쓴다.** 연산은 `operator` 모듈의 여섯 함수 표. 값이 `None`이거나 타입이 비교할 수 없으면 조건은 거짓.
- [ ] **Step 4: 통과를 확인한다**
- [ ] **Step 5: 커밋** — `feat(config): status verdict and headline selection`

### Task 3: run 지표, 과제 뷰, 시계열, 차트

**REQ-IDs:** REQ-102, REQ-103, REQ-105, REQ-122

**Files:**
- Create: `site-gen/td/site/metrics.py`, `site-gen/td/site/charts.py`, `site-gen/td/schemas/project-snapshot.schema.json`, `tests/acceptance/dashboard_fixtures.py`
- Modify: `site-gen/td/site/index.py` (`summarize_run`은 그대로 두고 호출만 유지)
- Test: `tests/acceptance/test_dashboard_index.py`

**Interfaces:**
- Consumes: Task 1·2.
- Produces:
  - `metrics.run_metrics(run_dir: Path) -> dict[str, object]` — 설계 §6.2 "run에서 오는 것" 표의 이름 전부. 없으면 `None`.
  - `metrics.load_snapshots(project_dir: Path) -> tuple[list[dict], list[str]]` — 날짜순 스냅숏(스키마를 지키고 `visibility == "public"`인 것)과 버린 파일의 사유 목록.
  - `metrics.snapshot_metrics(snapshot: dict) -> dict[str, object]` — "수집 스냅숏에서 오는 것" 표의 이름.
  - `metrics.build_projects(base: Path, cfg: Config) -> list[dict]` — 과제마다 `{"name", "repo", "sut", "pipeline": bool, "implicit": bool, "values": {...}, "verdict": {"level", "reasons", "partial"}, "headline", "runs": [summarize_run 결과...], "latestRunDir": Path | None, "snapshots": [...], "problems": [...], "description", "language", "ciHistory": [0|1,...]}`. `values`는 설계의 출처 규칙대로 합친다: 완료된 run이 있으면 `sonar.*`는 최신 run, `ci.*`·`repo.*`는 최신 스냅숏. 표에 낼 순서(`status.order`, 이름순)로 정렬해 돌려준다.
  - `metrics.series(project: dict, cfg: Config) -> dict` — 설계 §6.4의 `series.json` 모양. `kind`는 `pipeline`이면 `run`, 아니면 `snapshot`.
  - `metrics.aggregate(projects: list[dict], cfg: Config) -> dict[str, dict]` — 집계 지표마다 `{"value", "detail"}` (`detail`은 `"239 / 262회"` 같은 덧말).
  - `charts.trend_svg(metric: Metric, points: list[dict], max_points: int = 30) -> str` — 점은 `<a class="pt" href=…>`(run) 또는 `<g class="pt">`(스냅숏) 안의 `<circle>`. 속성 `data-id`, `data-value`. 선 조각마다 `<polyline class="ln">`.
  - `dashboard_fixtures.make_site(root: Path, *, runs: dict[str, list[dict]] = …, snapshots: dict[str, list[dict]] = …, config: dict | None = None) -> Path`, `write_run(base, sut, run_id, **overrides) -> Path`(S07·S09·S10 단계 JSON과 `run.json` `kpis`를 가진 완료 run), `write_snapshot(base, name, date, **overrides) -> Path`, `serve(directory) -> ContextManager[str]`(로컬 `http.server`, 종료 시 PID 정리), `page(browser, url, *, javascript=True)`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_req102_run_metrics(tmp_path):
    run = write_run(tmp_path, "petclinic", "20261120-131022Z-b6f9393-manual-036c288d",
        tests_pass=1.0, line=0.4152, agg_line=0.6091,
        generations={"base-r1": (21, 31), "jqa-r1": (30, 40)},     # (통과, 시나리오)
        sonar={"gate": "OK", "coverage": "57.1", "bugs": "2", "vulnerabilities": "18", "codeSmells": "69"},
        top10=[{"name": "Owner.getPet", "score": 27.345}], impact={"selected": 68, "indexedTests": 134},
        started="2026-11-20T13:10:22Z", last_finished="2026-11-20T13:18:57Z")
    m = metrics.run_metrics(run)
    assert m["tests.passRate"] == 1.0 and m["coverage.line"] == 0.4152 and m["coverage.aggregateLine"] == 0.6091
    assert m["e2e.passRate"] == pytest.approx(51 / 71)
    assert (m["sonar.gate"], m["sonar.coverage"], m["sonar.vulnerabilities"], m["sonar.codeSmells"]) == ("OK", 57.1, 18, 69)
    assert m["hotspot.topScore"] == 27.345 and m["tia.selectedRatio"] == pytest.approx(68 / 134) and m["run.durationSec"] == 515
    bare = write_run(tmp_path, "petclinic", "20261118-000000Z-aaaaaaa-manual-00000000", only_stages=["S00", "S01", "S08"],
                     impact={"selected": 0, "indexedTests": 0})
    m = metrics.run_metrics(bare)
    assert m["e2e.passRate"] is None and m["tia.selectedRatio"] is None and m["hotspot.topScore"] is None

def test_req103_series_points(tmp_path):
    site = make_site(tmp_path, runs={"petclinic": [RUN_A, RUN_B, RUN_C]}, snapshots={"kn": [SNAP_1121, SNAP_1122]},
                     config=cfg_with(pipeline="petclinic", plain="kn"))
    projects = {p["name"]: p for p in metrics.build_projects(site, load_cfg(site))}
    s = metrics.series(projects["petclinic"], load_cfg(site))
    assert s["kind"] == "run" and [p["id"] for p in s["points"]] == sorted(p["id"] for p in s["points"]) and len(s["points"]) == 3
    assert set(s["points"][0]["values"]) == set(s["metrics"]) and s["points"][0]["href"].endswith("/index.html")
    k = metrics.series(projects["kn"], load_cfg(site))
    assert k["kind"] == "snapshot" and [p["id"] for p in k["points"]] == ["20261121", "20261122"] and "href" not in k["points"][0]

def test_req105_legacy_fields_kept(tmp_path):
    site = make_site(tmp_path, runs={"petclinic": [RUN_A, RUN_B]})
    index.rebuild(site, "", dashboard_config.empty())
    suts = json.loads((site / "suts.json").read_text())
    assert set(suts[0]) >= {"name", "runCount", "latest"}
    assert set(suts[0]["latest"]) >= {"runId", "commit", "trigger", "startedAt", "stages", "kpis"}
    assert set(suts[0]["latest"]["kpis"]) >= {"passRate", "line", "sonarGate", "hotspot1"}
    assert json.loads((site / "suts/petclinic/runs.json").read_text())[0]["runId"] == RUN_B["runId"]

def test_req122_chart_axis_rules():
    ratio = charts.trend_svg(CATALOG["tests.passRate"], pts([1.0, 0.9]))
    assert all(t in ratio for t in (">0%<", ">50%<", ">100%<"))
    count = charts.trend_svg(CATALOG["sonar.vulnerabilities"], pts([3, 18, 7]))
    assert ">18<" in count and ">0<" in count
    flat = charts.trend_svg(CATALOG["sonar.bugs"], pts([2, 2, 2]))
    ys = {float(y) for y in re.findall(r'<circle[^>]* cy="([\d.]+)"', flat)}
    assert len(ys) == 1 and abs(ys.pop() - CHART_MID_Y) < 0.6
    assert charts.trend_svg(CATALOG["sonar.bugs"], pts([2, 2, 2])) == flat

# 검토 초점 2, 4
def test_broken_snapshot_is_dropped_with_reason(tmp_path):
    site = make_site(tmp_path, snapshots={"kn": [SNAP_1121]}, config=cfg_with(plain="kn"))
    (site / "projects/kn/snapshots/20261122.json").write_text("{not json")
    kn = metrics.build_projects(site, load_cfg(site))[0]
    assert kn["snapshots"][-1]["date"] == "20261121" and any("20261122" in p for p in kn["problems"])

def test_chart_single_point_and_all_missing():
    one = charts.trend_svg(CATALOG["tests.passRate"], pts([0.9]))
    assert one.count("<circle") == 1 and "<polyline" not in one
    none = charts.trend_svg(CATALOG["tests.passRate"], pts([None, None]))
    assert "<circle" not in none and "<svg" in none
```

- [ ] **Step 2: 실패를 확인한다** → `ModuleNotFoundError: td.site.metrics`
- [ ] **Step 3: `dashboard_fixtures.py`를 쓴다.** `write_run`은 기존 `helpers.make_site_run`을 불러 뼈대를 만들고 단계 JSON을 더한다.
- [ ] **Step 4: `project-snapshot.schema.json`을 쓴다.** 필수: `schema`(1), `name`, `repo`, `visibility`, `collectedAt`, `date`, `repoInfo`(`pushedAt`, `language`, `description`, `defaultBranch`), `ci`(객체 또는 `null`), `sonar`(객체 또는 `null`), `problems`(문자열 배열). `ci`: `runs`, `successes`, `failures`, `successRate`, `lastFailed`, `failedChecks`, `failedCheckNames`, `history`(오래된 것부터 0|1).
- [ ] **Step 5: `metrics.py`와 `charts.py`를 쓴다.** 차트 크기는 지금 `index.py`의 `CHART_W, CHART_H`(520×190)와 여백을 옮겨 쓴다. 세로축: `ratio`는 0~1 고정, 그 밖은 0~최댓값(모두 같으면 0~값×2), 눈금 셋. 좌표는 소수 1자리.
- [ ] **Step 6: 통과를 확인한다** — 6개 PASS, 그리고 `pytest tests/acceptance/test_unit_index.py -v`도 PASS(기존 `line_chart`를 지우지 않았다)
- [ ] **Step 7: 커밋** — `feat(site): run metrics, project views, series and trend charts`

### Task 4: 도구 고정 (hotspot 커밋 빌드, tia 올리기)

**REQ-IDs:** REQ-129 (REQ-130·131의 준비. PoC REQ-058 개정)

**Files:**
- Modify: `tools.pin.yaml`, `site-gen/td/prepare.py`, `pipeline/S00-prepare.sh`, `pipeline/S10-tia.sh`, `tests/acceptance/test_prepare.py`, `tests/acceptance/test_unit_tools.py`

**Interfaces:**
- Produces: `tools.pin.yaml`의 `hotspot: {repo: baekchangjoon/hotspot-analysis, commit: a5baac6c59273838374fe8a3cebf39ccc876d5c4, jdk: 21, gradleTask: bootJar, jarGlob: 'build/libs/hotspot-*.jar'}`, `tia.commit: c4e6e9e2c18f52e3315cc90a6f98fa16506c9199`. `tools.lock`의 `hotspot`: `{commit, sha256, path}`. `run.json` `tools.hotspot`은 커밋 앞 7자.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `test_prepare.py`

```python
def test_req129_hotspot_commit_build(s00_result):      # 기존 S00 fixture
    lock = yaml.safe_load((s00_result.tools_dir / "tools.lock").read_text())
    pin = yaml.safe_load((REPO_ROOT / "tools.pin.yaml").read_text())
    jar = s00_result.tools_dir / "hotspot.jar"
    assert lock["hotspot"]["commit"] == pin["hotspot"]["commit"] and len(pin["hotspot"]["commit"]) == 40
    assert lock["hotspot"]["sha256"] == hashlib.sha256(jar.read_bytes()).hexdigest()
    assert (s00_result.tools_dir / "hotspot-src" / ".git").is_dir()

def test_req129_short_hotspot_commit_fails(tmp_path):
    pin = mutate_pin(tmp_path, lambda d: d["hotspot"].update(commit="a5baac6"))
    with pytest.raises(prepare.PrepareError, match="hotspot.commit"):
        prepare.load_pin(pin)
```

- [ ] **Step 2: 실패를 확인한다** — 두 번째는 `DID NOT RAISE`, 첫 번째는 `KeyError: 'commit'`
- [ ] **Step 3: `prepare.py`를 고친다.** `ARTIFACT_TOOLS`에서 `hotspot`을 빼고, `load_pin`의 40자 검증 대상에 `hotspot`을 넣고, `tools.lock`의 hotspot을 S00이 넘긴 커밋과 jar sha256으로 쓴다(tia 항목이 쓰는 경로와 같은 방식).
- [ ] **Step 4: `S00-prepare.sh`에 hotspot 빌드를 넣는다.** tia 블록(66~78행)과 같은 모양: `fetch_git_tool "$TOOLS_DIR/hotspot-src" https …`, 커밋 대조, `.commit` 표식이 다를 때만 `JAVA_HOME=$JAVA21 ./gradlew -p … --no-daemon -q bootJar`, `jarGlob`에 맞는 jar 하나를 `$TOOLS_DIR/hotspot.jar`로 복사(둘 이상이면 `-plain`이 아닌 것). 실패는 `s00_fail`.
- [ ] **Step 5: `S10-tia.sh`의 `tia report` 호출에 `--impact "$S10_DIR/impact.json"`을 더한다.** `--scenarios`는 유지.
- [ ] **Step 6: `tools.pin.yaml`을 바꾸고, 기존 REQ-058 테스트의 hotspot 기대값을 고친다**(버전·자산 이름 대신 커밋과 sha256).
- [ ] **Step 7: 통과를 확인한다** — `pytest tests/acceptance/test_prepare.py tests/acceptance/test_unit_tools.py -v` 전부 PASS. 이어서 `pytest tests/acceptance/test_reports.py -k "req035 or req036" -v`로 S09·S10이 새 도구로 도는지 본다. `tia.html`에서 커밋을 읽는 위치가 바뀌어 `req036`이 깨지면 새 템플릿의 데이터 블록에서 읽도록 그 테스트를 고친다.
- [ ] **Step 8: 커밋** — `build(tools): pin hotspot by commit with source build; bump tia to report redesign`

### Task 5: 단계에 묶이지 않는 Sonar 토큰 함수

**REQ-IDs:** REQ-097

**Files:**
- Modify: `pipeline/lib/sonar-token.sh`, `pipeline/S11-sonar.sh`, `site-gen/td/hooks.py`(필요하면)
- Test: `tests/acceptance/test_unit_sonar.py`

**Interfaces:**
- Produces (bash):
  - `td_sonar_token_issue_named <name>` — 이름 그대로 발급, `SONAR_TOKEN` export, validate. 정리 trap은 걸지 않는다.
  - `td_sonar_token_revoke_named` — 발급한 이름의 행을 지우고 0행 확인. 실패하면 경고를 한 번 내고 `return 1`. 장애 주입은 `TD_SONAR_HOOK_STAGE`(기본 `S11`)의 `cleanup-ssh`.
  - 기존 `td_sonar_token_issue <runId>`, `td_sonar_token_revoke`, `td_sonar_revoke_redact`, `_td_sonar_revoke_on_exit`는 이름과 동작을 유지하고 위 둘 위에 얹는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `test_unit_sonar.py`의 `_bash_with_fake_ssh`를 쓴다.

```python
def test_named_issue_and_revoke_do_not_touch_stage_state(tmp_path):
    out = _bash_with_fake_ssh(tmp_path, '''
        td_sonar_token_issue_named td-collect-20261122T000000Z-abcd || exit 3
        [[ -n "$SONAR_TOKEN" ]] || exit 4
        td_sonar_token_revoke_named || exit 5
        [[ -z "${SONAR_TOKEN:-}" ]] || exit 6
    ''', run_dir=None)                      # TD_RUN_DIR 없이도 돈다
    assert out.returncode == 0
    assert fake_ssh_rows(tmp_path) == [] and "td-collect-20261122T000000Z-abcd" in fake_ssh_log(tmp_path)

def test_named_revoke_failure_warns_once(tmp_path):
    out = _bash_with_fake_ssh(tmp_path, 'td_sonar_token_issue_named td-collect-x; td_sonar_token_revoke_named; echo rc=$?',
                              fail_delete=True, run_dir=None)
    assert "rc=1" in out.stdout and out.stderr.count("토큰 잔존 가능") == 1 and "2시간 후 만료" in out.stderr
```

- [ ] **Step 2: 실패를 확인한다** → `command not found: td_sonar_token_issue_named`
- [ ] **Step 3: 함수를 나눈다.** `td.sonar validate` 호출과 SQL은 그대로 옮긴다.
- [ ] **Step 4: 통과를 확인한다** — 새 테스트 2개와 `pytest tests/acceptance/test_unit_sonar.py -v` 전부 PASS
- [ ] **Step 5: S11 회귀를 확인한다** — `pytest tests/acceptance/test_sonar.py -k "req064 or req065 or req066" -v` PASS(기대값을 고치지 않는다)
- [ ] **Step 6: 커밋** — `refactor(sonar): stage-neutral token issue/revoke under the S11 wrappers`

### Task 6: 수집기

**REQ-IDs:** REQ-085, REQ-086, REQ-087, REQ-088, REQ-089, REQ-090, REQ-091, REQ-092, REQ-093, REQ-094, REQ-095, REQ-096

**Files:**
- Create: `site-gen/td/collect.py`, `pipeline/collect.sh`
- Modify: `tests/acceptance/fake_sonar.py`, `tests/acceptance/dashboard_fixtures.py`
- Test: `tests/acceptance/test_dashboard_collect.py`

**Interfaces:**
- Consumes: Task 1(`Config`), Task 3(스냅숏 스키마), Task 5(토큰 함수).
- Produces:
  - `python -m td.collect run --config <파일> --site <접두까지 포함한 사이트 디렉터리> --suts-dir <dir> [--now <ISO UTC>]` — 표준 출력에 JSON 한 줄 `{"status": "ok"|"degraded", "reasons": [...], "written": [<사이트 상대 경로>...], "excluded": [<과제 이름>...]}`. 종료 코드는 설정 오류만 2, 그 밖은 0.
  - `python -m td.collect needs-sonar --config … --site … --suts-dir …` — Sonar를 읽을 과제 수를 출력.
  - `collect.collect(cfg: Config, site: Path, suts_dir: Path, *, now: datetime, env: Mapping[str, str]) -> dict` — 위 JSON과 같은 dict.
  - 환경 변수: `TD_GH_BIN`(기본 `gh`), `TD_SONAR_URL`, `SONAR_TOKEN`, `TD_COLLECT_BUDGET_SEC`(기본 300), `TD_COLLECT_TIMEOUT_SEC`(요청 하나, 기본 30).
  - `pipeline/collect.sh --config <파일> --site <dir>` — `needs-sonar`가 0보다 크면 `td_sonar_token_issue_named "td-collect-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"`, `trap … EXIT INT TERM`에 정리, `td.collect run` 실행. 표준 출력은 `td.collect`의 JSON을 그대로 내되 정리가 실패했으면 `status`를 `degraded`로 바꾸고 사유를 더한다(`td_py -m td.collect amend`).
  - `dashboard_fixtures.fake_gh(tmp_path, repos: dict[str, dict]) -> FakeGh` — `.path`(실행 파일), `.calls`(받은 인자 목록), 저장소마다 `visibility`, `runs`(결론값 목록), `checks`, `status`(403/429), `hang`(초), `description`. `dashboard_fixtures.fake_ssh(tmp_path, *, fail_delete=False) -> FakeSsh` — `.path`(PATH 앞에 둘 디렉터리), `.rows()`, `.log()`.
  - `fake_sonar`: 프로젝트 키별 응답과 404·500·지연, `.requests`(받은 `(경로, 키)` 목록).

- [ ] **Step 1: 가짜를 넓히고 실패하는 테스트를 쓴다.** REQ마다 하나, 요구사항명세의 수용기준을 그대로 단언한다. 대표 셋:

```python
def test_req085_ci_conclusion_classes(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {"o/a": {"runs": ["cancelled", "success", "failure", "success", "timed_out", "skipped", "success", "cancelled"]},
                            "o/b": {"runs": []}})
    out = run_collect(tmp_path, cfg(projects=[("a", "o/a"), ("b", "o/b")]), gh=gh, env=collect_env)
    ci = snapshot(tmp_path, "a")["ci"]
    assert (ci["runs"], ci["successes"], ci["failures"], ci["lastFailed"]) == (5, 3, 2, False)
    assert ci["history"] == [1, 1, 0, 1, 0][::-1] or len(ci["history"]) == 5     # 오래된 것부터, 제외한 결론값은 없다
    assert snapshot(tmp_path, "b")["ci"]["runs"] is None

def test_req089_private_repo_excluded(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {"o/a": {}, "o/secret": {"visibility": "private", "description": "internal thing"}, "o/c": {}})
    out = run_collect(tmp_path, cfg(projects=[("a", "o/a"), ("secret", "o/secret"), ("c", "o/c")]), gh=gh, env=collect_env)
    assert out["status"] == "degraded" and out["excluded"] == ["secret"] and any("secret" in r and "비공개" in r for r in out["reasons"])
    assert not (tmp_path / "site/projects/secret").exists()
    assert (tmp_path / "site/projects/a/latest.json").exists() and (tmp_path / "site/projects/c/latest.json").exists()
    index.rebuild(tmp_path / "site", "", load(tmp_path))
    blob = (tmp_path / "site/index.html").read_text() + (tmp_path / "site/projects.json").read_text()
    assert "secret" not in blob and "internal thing" not in blob

def test_req092_token_removed_on_all_exits(tmp_path, collect_env):
    ssh = fake_ssh(tmp_path)
    for mode in ("ok", "sonar-500", "sigterm"):
        proc = start_collect_sh(tmp_path, mode, ssh=ssh, env=collect_env)      # sigterm: Sonar 응답을 5초 늦추고 1초 뒤 신호
        finish(proc, mode)
        assert ssh.rows() == [], mode
    names = re.findall(r"td-collect-\d{8}T\d{6}Z-[0-9a-f]{8}", ssh.log())
    assert len(set(names)) == 3
```

  나머지(086, 087, 088, 090, 091, 093, 094, 095, 096)도 같은 방식으로 쓴다. 091은 `TD_COLLECT_BUDGET_SEC=3`, `hang=30`으로 `time.monotonic()` 차이가 13초 미만임을 본다. 094는 `TD_SONAR_TOKEN_OBSERVE`(기존 훅, `TD_SITE_PREFIX`가 있을 때만 동작)로 토큰을 읽어 `site/`와 로그 전체에서 0건임을 보고, `ps` 대신 가짜 gh·가짜 Sonar가 받은 인자·URL에 토큰이 없음을 본다. 096은 설명에 `str(tmp_path)`와 `arn:aws:iam::123456789012:user/x`를 넣는다.

- [ ] **Step 2: 실패를 확인한다** → `No module named td.collect`
- [ ] **Step 3: `collect.py`를 쓴다.**
  - 순서: ① 모든 `repo` 과제의 `repos/<repo>`를 읽어 공개 여부를 확정 ② 공개 과제마다 실행 목록(`repos/<repo>/actions/runs?branch=<기본>&status=completed&per_page=30`)과 검사(`repos/<repo>/commits/<기본>/check-runs?per_page=100`) ③ Sonar 대상 과제마다 `td.sonar`의 두 호출 ④ 쓰기.
  - Sonar 대상: `repo`가 있고, (`sut`가 없거나 `site/suts/<sut>/runs/*/_COMPLETE`가 없는) 과제. 키는 `sonar_key` → `sut.yaml`의 `sonar.projectKey` → 저장소 이름(슬래시 뒤).
  - 결론값 분류와 검사 규칙은 설계 §6.3의 표. `history`는 집계 대상만, 오래된 것부터.
  - `gh` 호출은 `subprocess.run([gh, "api", path], timeout=…)`. 재시도 2번(2초, 4초). 표준 오류에 `HTTP 403`/`HTTP 429`가 있으면 `gh api -i`로 `Retry-After`를 읽어 예산 안에서만 기다린다.
  - 예산은 `time.monotonic()` 기준. 넘으면 남은 과제는 `ci: null`, `sonar: null`과 사유 "수집 예산 초과".
  - 쓰기는 임시 파일 뒤 `os.replace`. 외부 문자열은 `redact.redact_text`를 지난다. `date`는 `now`의 UTC `YYYYMMDD`.
- [ ] **Step 4: `collect.sh`를 쓴다.** `common.sh`와 `sonar-token.sh`만 source한다(`env.sh`는 SUT 정리를 걸므로 쓰지 않는다). `TD_SONAR_HOOK_STAGE=collect`.
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_collect.py -v` 12개 PASS. 끝난 뒤 `pgrep -f fake_sonar` 결과가 비어 있다.
- [ ] **Step 6: 커밋** — `feat(collect): GitHub CI and SonarQube snapshots with per-collect token`

### Task 7: 새 디자인 자산, 공통 틀, 공통 띠, run 페이지

**REQ-IDs:** REQ-124, REQ-126, REQ-127, REQ-136, REQ-137 (REQ-125의 로컬 부분)

**Files:**
- Create: `site-gen/td/site/static/v2/app.css`, `site-gen/td/site/static/v2/app.js`, `site-gen/td/site/nav.py`, `site-gen/td/site/templates/base_v2.html.j2`
- Modify: `site-gen/td/site/templates/run.html.j2`, `site-gen/td/site/pages.py`, `site-gen/td/site/layout.py`, `site-gen/td/site/index.py`(v2 자산 복사), `site-gen/td/publish.py`(`render`가 띠 누락을 읽음)
- Test: `tests/acceptance/test_dashboard_nav.py`, `tests/acceptance/test_dashboard_common.py`

**Interfaces:**
- Produces:
  - `nav.NAV_STAGE_LABELS: dict[str, str]` — `S00`~`S13`의 한국어 이름(설계 시안의 단계 이름).
  - `nav.links_for(report_rel: str, reports: list[dict]) -> dict` — 띠에 넣을 상대 링크: `home`, `sut`(`…/suts/<sut>/index.html`에 해당하는 상대 경로), `run`, `reports`(`[{label, href, current}]`).
  - `nav.render(links: dict, current_label: str) -> str` — `<nav class="tdnav" …>` 한 덩어리. `<style>` 하나 포함, `<script>` 없음, 높이 40px, `position: static`.
  - `nav.inject(html_path: Path, nav_html: str) -> bool` — 처음 나오는 `<body[^>]*>`(대소문자 무시) 뒤에 넣는다. 없으면 파일을 그대로 두고 `False`.
  - `pages.render_run(run_dir, out_dir) -> Path` — 서명은 그대로. `out_dir/render.json`에 `{"navMissing": [{"report": <label>, "file": <rel>, "reason": "…"}]}`를 쓴다. `Publication.render`가 이 파일을 읽어 `self.render_warnings`에 담고, 비어 있지 않으면 최종 상태를 적어도 `degraded`로 하고 사유에 넣는다. `render.json`은 게시하지 않는다(`EXCLUDED_SITE_FILES`).
  - 템플릿 `base_v2.html.j2` 블록: `title`, `crumbs`, `content`, `scripts`. 변수: `static_href`(`…/static/v2/`), `nav`(dict 또는 없음).
  - DOM 계약(run 페이지): `#stage-strip button[data-stage]`(14개, `aria-pressed`), `#stage-detail`, `.report-card[data-report]`, `.report-card .nav-missing`, `#publish-result[data-url]`(기존 동작 유지).
  - `app.js`는 페이지에 있는 요소만 보고 동작한다: `#stage-strip`, `#publish-result`, (Task 9) `#projects`, (Task 10) `#tabs`·`.trend`.
  - CSS 변수와 값은 시안 `home.html`의 `:root` 블록 그대로. 상태 표시 클래스 `.st.s-crit|s-warn|s-good|s-none`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_req124_run_page(tmp_path, browser):
    run_dir = make_local_run_with_reports(tmp_path)          # helpers.make_local_run + hotspot/tia/cucumber 표본 HTML
    with serve(render_site(tmp_path, run_dir)) as url:
        page = browser.new_page(); page.goto(url + RUN_PATH)
        assert page.locator("#stage-strip button[data-stage]").count() == 14
        page.click('#stage-strip button[data-stage="S07"]')
        detail = page.inner_text("#stage-detail")
        assert "S07" in detail and "생성 E2E 실행" in detail and "4분 19초" in detail
        for card in page.locator(".report-card a").all():
            assert requests.get(urljoin(page.url, card.get_attribute("href"))).status_code == 200

def test_req126_external_reports_still_work(tmp_path, browser):
    # 표본은 tests/fixtures/reports/{hotspots.html,tia.html}: 실제 도구(Task 4의 커밋)가 만든 파일을 고정해 둔 것
    with serve(render_site(tmp_path, make_local_run_with_reports(tmp_path))) as url:
        page = browser.new_page(); errors = []; page.on("pageerror", errors.append)
        page.goto(url + RUN_PATH + "hotspot/hotspots.html")
        assert page.locator("nav.tdnav").count() == 1 and page.locator("nav.tdnav script").count() == 0
        assert page.locator("#hm-map circle").count() >= 1
        before = page.inner_text("#hm-side"); page.locator("#hm-map circle").first.click()
        assert page.inner_text("#hm-side") != before
        page.goto(url + RUN_PATH + "tia/tia.html")
        before = page.inner_text("main"); page.locator(".seg button").nth(1).click()
        assert page.inner_text("main") != before and errors == []

def test_req127_no_body_degraded(tmp_path):
    run_dir = make_local_run_with_reports(tmp_path, tia_html="<html><p>no body tag</p></html>",
                                          hotspot_html='<HTML><BODY class="x"><p>hi</p></BODY></HTML>')
    out = pages.render_run(run_dir, tmp_path / "out").parent
    assert (out / "tia/tia.html").read_text() == "<html><p>no body tag</p></html>"
    assert re.search(r'<BODY class="x"><nav class="tdnav"', (out / "hotspot/hotspots.html").read_text())
    missing = json.loads((out / "render.json").read_text())["navMissing"]
    assert [m["file"] for m in missing] == ["tia/tia.html"]
    assert "공통 띠 없음" in (out / "index.html").read_text()
    result = run_fake_publication(run_dir)                    # test_unit_publish.py의 가짜 S3 경로
    assert result["status"] == "degraded" and "tia/tia.html" in result["reason"]

def test_req136_legacy_assets_unchanged(tmp_path, browser):
    for name in ("site.css", "site.js"):
        committed = subprocess.check_output(["git", "show", f"c52b5d3:site-gen/td/site/static/{name}"], cwd=REPO_ROOT)
        assert (STATIC_DIR / name).read_bytes() == committed
    site = make_site(tmp_path, runs={"petclinic": [RUN_A]}); legacy = add_legacy_run_page(site)   # tests/fixtures/legacy-run/index.html
    with serve(site) as url:
        before = computed(browser, url + legacy, "th", "background-color"), computed(browser, url + legacy, "body", "font-size")
        index.rebuild(site, "", dashboard_config.empty())
        assert (computed(browser, url + legacy, "th", "background-color"), computed(browser, url + legacy, "body", "font-size")) == before

def test_req137_v2_asset_paths(tmp_path):
    out = pages.render_run(make_local_run_with_reports(tmp_path), tmp_path / "out").parent
    html = (out / "index.html").read_text()
    assert "static/v2/app.css" in html and "static/v2/app.js" in html and "static/site.css" not in html
```

- [ ] **Step 2: 실패를 확인한다** → `ModuleNotFoundError: td.site.nav`
- [ ] **Step 3: 표본 리포트를 고정한다.** Task 4의 도구로 mini-sut에 S09·S10을 돌려 나온 `hotspots.html`, `api_report.html`, `tia.html`을 `tests/fixtures/reports/`에 둔다(가리기를 지난 사본). 지금 게시된 run 페이지 HTML 하나를 `tests/fixtures/legacy-run/index.html`로 둔다.
- [ ] **Step 4: `app.css`, `app.js`, `base_v2.html.j2`, `nav.py`를 쓰고 `run.html.j2`와 `render_run`을 옮긴다.** 띠를 넣는 대상은 `REPORTS`와 `REPORTS_EXTRA`의 진입 파일과 `hotspot/api_report.html`. 순서는 복사 → (자체 리포트는 RERENDER) → 띠 주입 → `sanitize_site`. `index.rebuild`는 `static/v2/`를 `base/static/v2/`와 `_test/static/v2/`에 복사하고 `site.css`·`site.js`도 지금처럼 복사한다.
- [ ] **Step 5: 통과를 확인한다** — 5개 PASS, `pytest tests/acceptance/test_site.py tests/acceptance/test_unit_publish.py -v`에서 화면 선택자가 바뀌어 깨진 것만 새 DOM 계약에 맞게 고친다(REQ-049 관련은 Task 13에서 한꺼번에 다룬다. 여기서는 run 페이지 관련만).
- [ ] **Step 6: 커밋** — `feat(site): v2 assets, shared frame, report nav strip and run page`

### Task 8: 직접 만드는 리포트를 새 틀로

**REQ-IDs:** REQ-128

**Files:**
- Modify: `site-gen/td/coverage.py`, `sonar.py`, `compare.py`, `ontology_html.py`, `hosting.py`, `site-gen/td/site/layout.py`(`RERENDER`, `COPY_IGNORE`), `site-gen/td/site/templates/{coverage,sonar,compare,ontology,hosting,test_index}.html.j2`, `site-gen/td/site/static/v2/app.css`
- Test: `tests/acceptance/test_dashboard_nav.py`

**Interfaces:**
- Consumes: Task 7의 `base_v2.html.j2`, `nav.render`.
- Produces: 각 렌더 함수의 `css_href` 인자는 `static_href`(디렉터리)로 바뀐다. 단독 열람용으로 리포트 옆에 복사하던 스타일은 `app.css`를 복사한다. 온톨로지는 지금처럼 스타일을 인라인으로 넣되 `app.css`를 읽는다. 기존 화면의 요소 id와 스크립트(`ontology.js`, 커버리지 히트맵·소스 뷰어)는 그대로다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_req128_own_reports_new_frame(tmp_path):
    out = pages.render_run(make_local_run_with_reports(tmp_path, with_own_reports=True), tmp_path / "out").parent
    for rel in ("coverage/coverage.html", "sonar/sonar.html", "compare/compare.html", "ontology/jqa.html"):
        html = (out / rel).read_text()
        assert "static/v2/app.css" in html or "--surface" in html      # 온톨로지는 인라인
        assert 'class="tdnav"' in html and "static/site.css" not in html
    hosting_html = render_hosting(tmp_path)
    assert "static/v2/app.css" in hosting_html
```

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: 템플릿을 `base_v2.html.j2` 상속으로 옮기고 렌더 함수의 경로 인자를 바꾼다.** 히트맵·소스 뷰어·그래프의 전용 규칙은 `app.css`의 끝에 옮긴다(선택자 이름 유지).
- [ ] **Step 4: 통과를 확인한다** — 새 테스트 PASS, 그리고 `pytest tests/acceptance/test_coverage.py tests/acceptance/test_ontology.py tests/acceptance/test_compare.py tests/acceptance/test_unit_sonar.py tests/acceptance/test_unit_hosting.py -v`가 기대값을 고치지 않고 PASS(REQ-017, 034 포함)
- [ ] **Step 5: 커밋** — `feat(site): move own reports onto the v2 frame`

### Task 9: 첫 화면

**REQ-IDs:** REQ-104, REQ-109, REQ-110, REQ-111, REQ-112, REQ-113, REQ-114

**Files:**
- Modify: `site-gen/td/site/index.py`, `site-gen/td/site/templates/home.html.j2`, `site-gen/td/site/static/v2/app.js`, `app.css`
- Test: `tests/acceptance/test_dashboard_home.py`, `tests/acceptance/test_dashboard_index.py`

**Interfaces:**
- Consumes: Task 1~3, Task 7의 틀.
- Produces:
  - `index.rebuild(site_root, prefix: str = "", config: Config | None = None) -> list[Path]` — `config`가 `None`이면 `dashboard_config.resolve(os.environ, repo_root)`. `with_implicit`을 적용한다. `projects.json`과 홈을 쓴다(과제 페이지는 Task 10).
  - CLI: `python -m td.site.index <site_root> [prefix] [--config <파일>]`. `ConfigError`는 표준 오류에 내고 종료 코드 2, 아무 파일도 쓰지 않는다(검증을 쓰기보다 먼저 한다).
  - `projects.json`: `{"schema": 1, "projects": [{"name", "repo", "sut", "pipeline", "implicit", "status": {"level", "label", "reasons", "partial"}, "values": {...}, "headline", "href": "projects/<name>/index.html", "problems": [...]}], "summary": {...}}`.
  - DOM 계약(홈): `#headline`, `#summary .sum-item[data-metric]`, `button[data-filter]`(`aria-pressed`), `input#proj-search`, `table#projects`, `th button[data-sort]`, `tbody tr.proj[data-name][data-status][tabindex=0][aria-expanded]`, 그 안 `a.proj-link`, `.tag-pipeline`, `.tag-partial`, `td[data-col]`, 펼친 행 `tr.proj-detail`(안에 `.detail-reasons`, `a.open-project`), `#rules li`, `footer a[href$="_test/index.html"]`, `a[href$="hosting.html"]`, 과제 0개일 때 `#empty`.
  - 페이지 안 데이터: `<script type="application/json" id="projects-data">`(`pages.json_for_script`).

- [ ] **Step 1: 실패하는 테스트를 쓴다** — 고정 사이트 `HOME_SITE`: 위험 2(`b-crit`, `a-crit`), 주의 1, 측정 없음 1, 양호 2(하나는 CI만 있어 부분 측정, 하나는 파이프라인). 대표:

```python
def test_req109_rows_order_headline(home, browser):          # home: serve된 HOME_SITE URL
    page = open_page(browser, home)
    assert [r.get_attribute("data-status") for r in page.locator("tr.proj").all()] == ["crit", "crit", "warn", "none", "good", "good"]
    assert [r.get_attribute("data-name") for r in page.locator('tr.proj[data-status="crit"]').all()] == ["a-crit", "b-crit"]
    assert page.inner_text("#headline") == "과제 6개 중 2개가 위험, 1개가 주의입니다"
    assert open_page(browser, all_good_site_url).inner_text("#headline") == "과제 2개 중 문제 있는 과제가 없습니다"

def test_req111_inline_expand(home, browser):
    page = open_page(browser, home)
    row = page.locator('tr.proj[data-name="b-crit"]'); row.click()
    assert row.get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.querySelector('tr.proj[data-name=\"b-crit\"]').nextElementSibling.className") == "proj-detail"
    assert "Sonar 품질 게이트 실패" in page.inner_text("tr.proj-detail .detail-reasons")
    assert page.locator("tr.proj-detail a.open-project").get_attribute("href") == "projects/b-crit/index.html"
    page.locator('tr.proj[data-name="a-crit"]').click()
    assert page.locator("tr.proj-detail").count() == 1 and row.get_attribute("aria-expanded") == "false"
    page.locator('tr.proj[data-name="a-crit"]').click(); assert page.locator("tr.proj-detail").count() == 0
    row.focus(); page.keyboard.press("Enter"); assert page.locator("tr.proj-detail").count() == 1

def test_req113_missing_not_zero(home, browser):
    page = open_page(browser, home)
    cell = lambda name, col: page.inner_text(f'tr.proj[data-name="{name}"] td[data-col="{col}"]').strip()
    assert cell("no-sonar", "sonar.gate") == "연결 없음" and cell("no-sonar", "sonar.coverage") == "—"
    assert cell("no-ci", "ci.successRate") == "—"
    assert cell("zero-cov", "sonar.coverage") == "0.0%"

# 검토 초점 1, 3
def test_special_characters_are_escaped(tmp_path, browser):
    site = make_site(tmp_path, snapshots={"x": [snap(description='<img src=x onerror=alert(1)> & "q"')]}, config=cfg_with(plain="x"))
    index.rebuild(site, "", load_cfg(site))
    with serve(site) as url:
        page = open_page(browser, url)
        assert page.locator("tr.proj img").count() == 0 and '<img src=x' in page.inner_text('tr.proj[data-name="x"]')
        assert json.loads(page.inner_text("#projects-data"))["projects"][0]["name"] == "x"

def test_empty_site_home(tmp_path, browser):
    site = make_site(tmp_path); index.rebuild(site, "", dashboard_config.empty())
    with serve(site) as url:
        page = open_page(browser, url)
        assert page.locator("#empty").inner_text() == "등록된 과제가 없습니다" and page.locator("tr.proj").count() == 0
```

  104(홈의 상태·사유가 `projects.json`과 같다), 110(거르기·검색·정렬, 값 없는 행은 항상 뒤), 112(`javascript_enabled=False` 컨텍스트에서 6줄과 `a.proj-link`), 114(표시가 맞는 행에만, `#rules`에 수준별 문장, 하단 링크 둘)도 같은 방식으로 쓴다.

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: `rebuild`를 넓히고 `home.html.j2`를 쓴다.** 표는 서버가 정렬된 순서로 다 그린다. 결론 문장: 위험·주의가 있으면 `"과제 N개 중 X개가 위험, Y개가 주의입니다"`(0인 쪽은 뺀다), 없으면 `"과제 N개 중 문제 있는 과제가 없습니다"`. 상세 행의 내용은 서버가 `<template data-detail-for="<name>">`으로 넣어 두고 `app.js`가 옮겨 붙인다(스크립트가 없으면 보이지 않고, 과제 이름 링크로 대신한다).
- [ ] **Step 4: `app.js`의 홈 동작을 쓴다.** 정렬은 `td[data-sort-value]`로 한다. 값이 없는 칸은 `data-sort-value=""`이고 방향과 무관하게 뒤다.
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_home.py tests/acceptance/test_dashboard_index.py -v`
- [ ] **Step 6: 커밋** — `feat(site): project list home with verdicts, filters and inline detail`

### Task 10: 과제 페이지와 SUT 안내 페이지

**REQ-IDs:** REQ-080, REQ-083, REQ-108, REQ-115, REQ-116, REQ-117, REQ-118, REQ-119, REQ-120, REQ-121, REQ-123

**Files:**
- Create: `site-gen/td/site/templates/project.html.j2`, `site-gen/td/site/templates/tabs/{overview,trend,tests,coverage,hotspot,quality,generation,runs}.html.j2`
- Modify: `site-gen/td/site/index.py`, `site-gen/td/site/metrics.py`, `site-gen/td/site/templates/sut.html.j2`, `site-gen/td/site/static/v2/app.js`, `app.css`
- Test: `tests/acceptance/test_dashboard_project.py`, `tests/acceptance/test_dashboard_status.py`

**Interfaces:**
- Consumes: Task 3(`series`, `trend_svg`), Task 9(`rebuild`).
- Produces:
  - `metrics.tab_data(project: dict, base: Path, cfg: Config) -> dict[str, dict | None]` — 탭 식별자 → 템플릿 데이터, 데이터가 없는 탭은 `None`. 출처: `overview`는 `values`와 S09 `top10`·S10 `impact`·단계 JSON 시각, `tests`는 S07 `generations`와 `run.json` `kpis.tests`, `coverage`는 `run.json` `kpis`의 묶음별 값과 `coverage/coverage.json`의 `tcCount`·`attributedCount`, `hotspot`은 S09 `top10`, `quality`는 `sonar/sonar.json`(이슈의 종류 × 심각도 집계, 등급)이고 파이프라인이 없는 과제는 스냅숏의 `sonar`, `generation`은 `compare/compare.json`의 `verdict`와 방식별 `metrics.*.mean`, `runs`는 `runs`. 모두 미러의 최신 완료 run 디렉터리에서 읽는다.
  - `rebuild`가 과제마다 `projects/<name>/index.html`, `projects/<name>/series.json`을 쓰고, `suts/<sut>/index.html`을 안내 페이지로 쓴다(`<meta http-equiv="refresh" content="0; url=../../projects/<name>/index.html">`과 `a#to-project`).
  - 보이는 탭 = `cfg.project["tabs"]` 가운데 `tab_data`가 `None`이 아닌 것. 파이프라인 없는 과제는 `overview`, `trend`, `quality`만.
  - DOM 계약: `#headline`, `.st`, `[role=tablist]#tabs`, `button[role=tab][data-tab][aria-controls="panel-<id>"][aria-selected]`(선택된 것만 `tabindex=0`), `section[role=tabpanel]#panel-<id>[aria-labelledby]`, 구역마다 `.tab-guide` 하나, `figure.trend[data-metric]` 안 `svg`와 `.pt`, 툴팁 `#trend-tip`, 강조 클래스 `.pt.hl`, `table#trend-table` (`tr[data-id]`, `td[data-metric]`), KPI 칸 `.kpi[data-metric] b`, `ol.hot li`, `table#gens tr[data-gen]`, `table#issues td[data-type][data-sev]`, `table#arms tr[data-arm]`, `table#runs tr[data-run]`, 리포트 링크 `a.report-link[data-report]`.
  - 스크립트가 켜지면 `document.documentElement.classList.add("js")`를 하고, CSS는 `.js [role=tabpanel][hidden]`만 숨긴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** 고정 사이트 `PROJ_SITE`: 파이프라인 과제 `pet`(run 5개, 3번째 run은 `tests.passRate` 없음, 최신 run에 모든 단계 JSON), 스냅숏 2일치인 `plain`, run 31개인 `many`. 대표:

```python
def test_req115_tabs_hash_keyboard(proj, browser):
    page = open_page(browser, proj + "projects/pet/index.html")
    page.click('button[role=tab][data-tab="coverage"]')
    assert page.locator('[role=tabpanel]:visible').get_attribute("id") == "panel-coverage"
    assert page.locator('button[role=tab][aria-selected="true"]').count() == 1 and page.url.endswith("#coverage")
    page2 = open_page(browser, proj + "projects/pet/index.html#quality")
    assert page2.locator('[role=tabpanel]:visible').get_attribute("id") == "panel-quality"
    page2.locator('button[role=tab][data-tab="quality"]').focus(); page2.keyboard.press("ArrowRight")
    assert page2.locator('button[role=tab][aria-selected="true"]').get_attribute("data-tab") == "generation"
    assert page2.locator('button[role=tab][data-tab="quality"]').get_attribute("aria-controls") == "panel-quality"

def test_req120_trend_points_gaps_cap(proj, browser):
    page = open_page(browser, proj + "projects/pet/index.html#trend")
    fig = page.locator('figure.trend[data-metric="tests.passRate"]')
    assert fig.locator(".pt").count() == 4 and fig.locator("polyline.ln").count() == 2
    many = open_page(browser, proj + "projects/many/index.html#trend")
    assert many.locator('figure.trend[data-metric="coverage.line"] .pt').count() == 30
    assert many.locator("#trend-table tbody tr").count() == 31

def test_req119_snapshot_only_project(proj, browser):
    page = open_page(browser, proj + "projects/plain/index.html")
    assert [t.get_attribute("data-tab") for t in page.locator("button[role=tab]").all()] == ["overview", "trend", "quality"]
    kpi = lambda m: page.inner_text(f'#panel-overview .kpi[data-metric="{m}"] b')
    assert (kpi("ci.successRate"), kpi("sonar.gate"), kpi("sonar.coverage"), kpi("sonar.vulnerabilities"), kpi("sonar.bugs")) == ("90.0%", "통과", "91.6%", "0", "0")

def test_req083_threshold_change_changes_verdict(tmp_path):
    site = make_site(tmp_path, snapshots={"p": [snap(ci_runs=25, ci_successes=23)]}, config=cfg_with(plain="p"))
    index.rebuild(site, "", load_cfg(site)); assert status_of(site, "p") == "good"
    cfg2 = set_threshold(load_cfg(site), "ci.successRate", 0.95); index.rebuild(site, "", cfg2)
    assert status_of(site, "p") == "warn" and "95.0%" in (site / "index.html").read_text()

# 검토 초점 5
def test_unknown_hash_opens_first_tab(proj, browser):
    page = open_page(browser, proj + "projects/pet/index.html#nope")
    assert page.locator('[role=tabpanel]:visible').get_attribute("id") == "panel-overview"
```

  080(탭을 빼고 순서를 바꾼 설정, 열을 뺀 설정, `trend.run`을 둘로 줄인 설정), 108(`a#to-project`의 href가 200이고 `meta refresh`가 있다. 암묵 과제도), 116(스크립트를 끄면 `section[role=tabpanel]`이 설정 순서로 모두 보인다), 117(구역마다 `.tab-guide` 하나), 118(각 탭의 값이 픽스처와 같고 `a.report-link`가 200), 121(점에 `focus()` 뒤 `#trend-tip`에 runId와 값, 다른 차트의 같은 `data-id` 점에 `.hl`, run 점 href 200, 스냅숏 점은 `a`가 아니고 툴팁에 날짜), 123(`#trend-table`의 칸이 `series.json`과 같고 없는 값은 "—")도 쓴다.

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: `tab_data`, 템플릿, `rebuild`의 과제 페이지 쓰기를 넣는다.** 탭 안 배치와 "이 탭 읽는 법" 문구는 시안 `project.html`의 것을 그대로 쓴다. "추이" 탭의 읽는 법: "지표 하나에 차트 하나입니다. 점 하나가 실행 한 번이고, 값이 없는 실행에서는 선이 끊깁니다. 점을 누르면 그 실행으로 갑니다."(스냅숏 과제는 "실행" 대신 "하루치 수집", 마지막 문장 없음).
- [ ] **Step 4: `app.js`의 탭·추이 동작을 쓴다.** 탭: 클릭, 좌우 방향키, Home/End, `history.replaceState`로 `#`. 추이: `.pt`의 `focus`/`mouseenter`에 툴팁과 `data-id`가 같은 점 강조.
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_project.py tests/acceptance/test_dashboard_status.py -v`
- [ ] **Step 6: 커밋** — `feat(site): project page with tabs, trends and SUT landing`

### Task 11: 게시 (인덱스 단계에 수집, 인덱스 전용 게시, 과제 삭제)

**REQ-IDs:** REQ-079, REQ-098, REQ-099, REQ-100, REQ-101, REQ-106, REQ-107, REQ-125

**Files:**
- Create: `pipeline/publish-index.sh`
- Modify: `site-gen/td/publish.py`, `pipeline/S13-publish.sh`(주석만)
- Test: `tests/acceptance/test_dashboard_publish.py`, `tests/acceptance/test_dashboard_index.py`, `tests/acceptance/test_dashboard_nav.py`, `tests/acceptance/test_unit_publish.py`

**Interfaces:**
- Consumes: Task 6(`collect.sh`의 표준 출력 JSON), Task 9·10(`rebuild`).
- Produces:
  - `publish.delete_prefix(s3, bucket: str, key_prefix: str) -> int` — 나열 후 묶어 삭제, 지운 수. `key_prefix`가 `…projects/<이름>/` 꼴이 아니면 `PublishError`.
  - `publish.run_collect(env: dict, cfg_path: Path | None, site_dir: Path) -> dict` — `pipeline/collect.sh`를 새 프로세스 그룹 없이 자식으로 실행하고 JSON을 돌려준다. `cfg`에 `repo`가 있는 과제가 없으면 실행하지 않고 `{"status": "ok", "written": [], "reasons": [], "excluded": []}`. 실행 자체가 실패하면 `{"status": "degraded", "reasons": ["수집 실행 실패: …"], …}`.
  - `publish.publish_index(s3, bucket, mirror: Path, prefix: str, env: dict, *, ssh_target, ssh_key) -> IndexOutcome` — `sync_mirror` → `run_collect` → `rebuild` → 삭제(S3는 `delete_prefix`, 미러는 `shutil.rmtree`, Lightsail은 `ssh_output(… "rm -rf -- /srv/dashboard/<prefix>projects/<name>")`) → `upload_files(rebuild 목록 + 수집 목록)`. `@dataclass class IndexOutcome: written: list[Path]; collect_status: str; collect_reasons: list[str]; deleted: list[str]`.
  - 삭제 대상: `mirror/<prefix>projects/` 바로 아래 디렉터리 가운데 `with_implicit` 뒤의 과제 이름이 아닌 것과, 수집 결과의 `excluded`.
  - `Publication.index_phase`가 `publish_index`를 쓴다. `collect_status`가 `degraded`면 최종 상태를 적어도 `degraded`로 하고 사유에 넣는다(`overall_status`에 수집 항목 `hosts["collect"] = {"status", "reason"}`을 더한다).
  - `publish.run_index_only(env=None, s3=None, cf=None) -> int`, CLI `td.publish index-only`. 순서: 접두 잠금 → 미러 잠금 → `publish_index` → 무효화 → `rsync_lightsail(runs=False)` → 결과를 `<prefix>publish-log/index.json`(no-cache)에 쓰고 표준 오류에 한 줄. 종료 코드는 `failed`만 1. 신호 처리는 `run_publish`와 같다.
  - `invalidation_paths`: `projects/` 아래 경로는 `/<prefix>projects/*` 하나로 묶는다.
  - 설정 경로: `dashboard_config.resolve(env, root)`가 쓰는 규칙 그대로. `publish_index`는 `TD_DASHBOARD_CONFIG`(또는 운영 기본 경로)를 `collect.sh --config`에 넘긴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `E2E-inj` 테스트는 기존 `site_prefix`, `s3_client`, `bucket`, `injected_petclinic_run`, `mini_sut_run` fixture와 가짜 gh·Sonar·ssh를 쓴다(환경 변수 `TD_GH_BIN`, `TD_SONAR_URL`, PATH 앞의 가짜 ssh). 대표:

```python
def test_req098_index_only_publish(injected_petclinic_run, s3_client, bucket, site_prefix, tmp_path, fakes):
    cfg = write_cfg(tmp_path, projects=[("alpha", "o/alpha"), ("beta", "o/beta")])
    before = list_keys(s3_client, bucket, site_prefix + "suts/")
    proc = run_script("pipeline/publish-index.sh", TD_SITE_PREFIX=site_prefix, TD_DASHBOARD_CONFIG=str(cfg), **fakes.env)
    assert proc.returncode == 0
    assert list_keys(s3_client, bucket, site_prefix + "suts/") >= before and no_new_run_dirs(before, s3_client, bucket, site_prefix)
    for key in ("projects/alpha/latest.json", "projects/alpha/index.html", "projects/alpha/series.json",
                "projects/beta/latest.json", "projects.json", "index.html"):
        head = s3_client.head_object(Bucket=bucket, Key=site_prefix + key)
        assert head["CacheControl"] == "no-cache"
    assert any(k.startswith(site_prefix + "projects/alpha/snapshots/") for k in list_keys(s3_client, bucket, site_prefix + "projects/"))
    assert (mirror_dir() / site_prefix / "projects/alpha/latest.json").exists()

def test_req100_removed_or_private_project_deleted(…):
    publish_index(cfg(["alpha", "beta"]))
    counts = {p: count_keys(p) for p in ("projects/beta/", "suts/", "static/")}
    publish_index(cfg(["beta"]))                                   # alpha를 설정에서 뺌
    assert count_keys("projects/alpha/") == 0 and "alpha" not in home() + projects_json()
    assert all(count_keys(p) >= n for p, n in counts.items())
    publish_index(cfg(["alpha", "beta"])); fakes.gh.set("o/alpha", visibility="private"); publish_index(cfg(["alpha", "beta"]))
    assert count_keys("projects/alpha/") == 0

def test_req101_projects_invalidation_wildcard(tmp_path):
    written = [tmp_path / "p" / f"projects/n{i}/{f}" for i in range(20) for f in ("index.html", "series.json", "latest.json")] + [tmp_path / "p/index.html"]
    paths = publish.invalidation_paths(tmp_path, written, "p/", "", "", include_log=False)
    assert [x for x in paths if "/projects/" in x] == ["/p/projects/*"]

def test_req106_idempotent_all_outputs(tmp_path):
    site = PROJ_SITE(tmp_path); cfg = load_cfg(site)
    index.rebuild(site, "", cfg); first = snapshot_tree(site); index.rebuild(site, "", cfg)
    assert snapshot_tree(site) == first and any(p.startswith("projects/") for p in first) and "static/v2/app.css" in first
```

  079(접두 실행에 설정을 안 넘기면 홈에 운영 과제가 없고 `fakes.gh.calls == []`, 넘기면 그 과제가 나온다), 099(수집 `degraded`인 S13과 인덱스 전용 게시가 각각 홈을 갱신하고 상태 `degraded`, 게시 기록 사유에 수집 사유), 107(mini-sut이 설정 없이 홈에 "파이프라인" 표시로 나오고 `projects/<sut>/index.html`이 있고 gh 호출 0건), 125(접두 아래 새 run의 모든 리포트에 `nav.tdnav`가 있고 띠의 링크가 CloudFront에서 200, SUT 링크가 `suts/<sut>/index.html`로 끝남)도 쓴다.

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: `publish.py`를 고친다.** `Publication.index_phase`의 몸을 `publish_index`로 옮기고 인덱스 전용 게시를 더한다. 기존 `write_log`, 잠금, 미러 잠금, 무효화 함수를 그대로 쓴다.
- [ ] **Step 4: `publish-index.sh`를 쓴다.** `common.sh`를 source하고 `td_py -m td.publish index-only`를 실행하는 것이 전부다. `S13-publish.sh`의 머리 주석에 수집을 한 줄 더한다.
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_publish.py tests/acceptance/test_unit_publish.py tests/acceptance/test_publish.py -v`. 끝난 뒤 가짜 프로세스 잔존 0, 테스트 접두의 잠금 객체 0.
- [ ] **Step 6: 커밋** — `feat(publish): collect inside the index phase, index-only publish, project pruning`

### Task 12: 공통 비기능

**REQ-IDs:** REQ-132, REQ-133, REQ-134, REQ-135, REQ-138

**Files:**
- Modify: `site-gen/td/site/static/v2/app.css`, `app.js`
- Test: `tests/acceptance/test_dashboard_common.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
PAGES = ["", "projects/pet/index.html", "projects/plain/index.html", RUN_PATH, RUN_PATH + "coverage/coverage.html"]
TABS = ["overview", "trend", "tests", "coverage", "hotspot", "quality", "generation", "runs"]

def test_req132_no_external_requests(proj, browser):
    page = browser.new_page(); outside = []
    page.on("request", lambda r: outside.append(r.url) if not r.url.startswith(proj) and not r.url.startswith("data:") else None)
    for rel in PAGES: page.goto(proj + rel)
    for tab in TABS: page.goto(proj + "projects/pet/index.html#" + tab)
    assert outside == []
    for asset in (STATIC_DIR / "v2").iterdir():
        assert not re.search(r"https?://|@import", asset.read_text())

def test_req133_responsive_360(proj, browser):
    page = browser.new_page(viewport={"width": 360, "height": 740})
    for url in [proj + p for p in PAGES[:4]] + [proj + "projects/pet/index.html#" + t for t in TABS] + [long_names_site_url]:
        page.goto(url); assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), url

def test_req134_dark_theme(proj, browser):
    light, dark = body_bg(browser, proj, "light"), body_bg(browser, proj, "dark")
    assert light != dark
    for scheme in ("light", "dark"):
        for sel in (".st.s-crit", ".st.s-warn", ".st.s-good", ".st.s-none"):
            assert contrast(browser, proj, sel, scheme) >= 4.5

def test_req135_status_not_color_only(proj, browser):
    page = open_page(browser, proj)
    marks = {s: page.evaluate(f"getComputedStyle(document.querySelector('.st.s-{s}'), '::before').borderRadius + '|' + getComputedStyle(document.querySelector('.st.s-{s}'), '::before').backgroundColor") for s in ("crit", "warn", "none")}
    assert len({m.split('|')[0] for m in (marks['crit'], marks['warn'])}) == 2 and "rgba(0, 0, 0, 0)" in marks["none"]
    assert all(page.inner_text(f".st.s-{s}").strip() for s in ("crit", "warn", "none", "good"))

def test_req138_reduced_motion(proj, browser):
    ctx = browser.new_context(reduced_motion="reduce"); page = ctx.new_page(); page.goto(proj)
    assert page.evaluate("getComputedStyle(document.querySelector('.caret')).transitionDuration") == "0s"
```

  `long_names_site_url`은 이름 60자, 설명 200자인 과제를 가진 사이트다.
- [ ] **Step 2: 실패를 확인한다** (보통 133의 일부 탭과 134의 명암비)
- [ ] **Step 3: `app.css`를 고친다.** 넓은 표는 `.scroll` 안에, 긴 이름은 `overflow-wrap: anywhere`, 탭 줄은 가로 스크롤. 상태 표시의 글자색은 `--ink`.
- [ ] **Step 4: 통과를 확인한다**
- [ ] **Step 5: 커밋** — `feat(site): responsive, dark theme and motion rules for v2 pages`

### Task 13: PoC 테스트·문서 개정

**REQ-IDs:** (PoC REQ-035, 036, 049, 050, 058 개정. 새 REQ 없음. 요구사항명세 §3)

**Files:**
- Modify: `tests/acceptance/test_site.py`, `test_baseline.py`, `test_coverage.py`, `test_reports.py`, `docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md`, `docs/superpowers/requirements/2026-11-18-test-dashboard-poc-requirements.md`, `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md`, `README.md`

- [ ] **Step 1: 깨진 PoC 테스트를 찾는다** — `uv run --project site-gen pytest tests/acceptance -m "not baseline" -x -q`를 돌려 실패 목록을 적는다.
- [ ] **Step 2: 요구사항명세 §3의 표대로만 고친다.** REQ-049의 세 테스트는 "홈의 과제 표에서 그 SUT와 이어진 과제를 펼치면 네 KPI가 나온다"와 "SUT 페이지가 안내하는 과제 페이지의 실행 이력 탭과 추이 탭"을 본다. REQ-050은 "홈의 과제 표에 두 SUT의 암묵 과제"를 본다. 표에 없는 테스트가 깨졌으면 구현을 고친다(기대값을 고치지 않는다).
- [ ] **Step 3: PoC 설계와 PoC 요구사항명세의 해당 절·항목 문장을 고친다.** 설계 머리말의 표에 적힌 절(§6.1, §6.10, §6.11, §6.13, §13.3, §6.14, §13.1, §13.2)과 REQ-035, 036, 049, 050, 058의 수용기준.
- [ ] **Step 4: README를 고친다.** 더할 절: `dashboard.yaml`로 과제 등록하기, 상태 규칙과 탭·열 바꾸기, `pipeline/publish-index.sh`(run 없이 과제 목록 갱신. 화면만 바꾼 뒤에도 이 명령), 수집이 쓰는 것(`gh` 로그인, Sonar 임시 토큰과 SSH), 옛 run은 옛 모습으로 남는다는 것. 문서 규칙은 `writing-documentation` 스킬을 따른다.
- [ ] **Step 5: 전체 로컬 스위트를 확인한다** — `uv run --project site-gen pytest tests/acceptance -m "not baseline" -q` 전부 PASS
- [ ] **Step 6: 새 요구사항명세의 매트릭스 상태를 실제 결과로 고친다**(통과한 것은 🟢).
- [ ] **Step 7: 커밋** — `test,docs: amend PoC tests and docs for the redesigned site`

### Task 14: 운영 게시와 확인

**REQ-IDs:** REQ-130, REQ-131, REQ-139

**Files:**
- Modify: `tests/acceptance/test_baseline.py`, `tests/acceptance/run_baseline.py`(인덱스 전용 게시 1회 추가), `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md`

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `@pytest.mark.baseline`

```python
def test_req130_hotspot_map_published(baseline):
    status, body = https_get(HOST, DOMAIN, baseline.run_path + "hotspot/hotspots.html")
    block = re.search(r'<script type="application/json" id="hotspot-map-data">(.*?)</script>', body.decode(), re.S)
    assert status == 200 and json.loads(block.group(1))["schemaVersion"] == 1
    assert len(json.loads(fetch(baseline.run_path + "stages/S09.json"))["top10"]) == 10
    assert circles_in_browser(baseline.run_url + "hotspot/hotspots.html") >= 1

def test_req131_tia_report_published(baseline):
    html = fetch(baseline.run_path + "tia/tia.html")
    assert html.count('class="tab-guide"') == 4
    impact = embedded_model(html)["impact"]
    assert impact is not None and len(impact["changedFiles"]) == len(baseline.impact_json["changedFiles"])

def test_req139_production_site(baseline, browser):
    cfg = dashboard_config.load(REPO_ROOT / "dashboard.yaml", REPO_ROOT / "suts")
    page = open_page(browser, f"https://{HOST}.{DOMAIN}/")
    assert page.locator("tr.proj").count() == len(cfg.projects)
    walk = [f"projects/{pipeline_project(cfg)}/index.html", baseline.run_path, baseline.run_path + "hotspot/hotspots.html",
            baseline.run_path + "tia/tia.html", f"suts/{baseline.sut}/index.html"]
    assert all(https_get(HOST, DOMAIN, "/" + p)[0] == 200 for p in walk)
    old = https_get(HOST, DOMAIN, "/" + OLD_RUN_PATH)       # 20261120-131022Z-b6f9393-manual-036c288d
    assert old[0] == 200 and b"static/site.css" in old[1]
    assert https_get(HOST, DOMAIN, "/_design/home-repos/")[0] != 200 and https_get(HOST, DOMAIN, "/_design/project/")[0] != 200
```

- [ ] **Step 2: 기준 run을 돌린다** — `uv run --project site-gen python tests/acceptance/run_baseline.py`. 운영 사이트에 새 run 둘과 인덱스 전용 게시 한 번이 실린다.
- [ ] **Step 3: 시안을 지운다.** S3의 `_design/` 접두 객체(`home-layout/`, `home-repos/`, `project/`의 `index.html` 셋)와 Lightsail의 `/srv/dashboard/_design`. 지운 뒤 CloudFront에서 `/_design/*`를 무효화한다.
- [ ] **Step 4: 전체 스위트를 돌린다** — `uv run --project site-gen pytest tests/acceptance -v`. 전부 PASS. 이어서 누수 확인: `docker ps -a --filter label=test-run=<세션 라벨>`이 비어 있고, 테스트가 띄운 PID가 없고, Sonar에 `td-collect-%`·`td-<runId>` 행이 0개다.
- [ ] **Step 5: 브라우저로 따라가 본다.** 첫 화면 → 위험 과제 펼침 → 과제 페이지의 탭 여덟 → 추이의 점 → run → hotspot 지도에서 원을 눌러 들어가기 → 띠로 SUT → 과제 페이지. 옛 run 하나를 열어 옛 모습인지 본다.
- [ ] **Step 6: 매트릭스를 100% green으로 맞추고 커밋** — `docs: matrix 64/64 after production run`

---

## 완료 정의

- 요구사항명세의 매트릭스가 대상 64개 모두 🟢이고, 각 행의 테스트 이름이 실제 통과한 테스트와 같다.
- PoC 매트릭스가 개정된 항목을 포함해 다시 전부 통과한다.
- 누수 확인(컨테이너, 프로세스, 잠금 객체, Sonar 토큰 행)이 0이다.
- README와 PoC 설계·요구사항명세가 새 동작과 맞다.
