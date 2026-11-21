# test-dashboard 화면 재설계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 첫 화면을 과제 목록과 품질 상태 중심으로 다시 만들고, 과제 페이지·run 페이지·리포트를 한 디자인으로 잇고, 새 hotspot·TIA 리포트를 싣는다.

**구조:** 지금의 Jinja 정적 생성(`td.site`)을 넓힌다. 설정(`dashboard.yaml`)과 수집 스냅숏(GitHub CI, SonarQube)과 run 산출물을 `td.site.index.rebuild`가 읽어 HTML과 JSON을 만든다. 상호작용은 `static/v2/app.js` 하나가 서버가 그린 HTML에 덧입힌다. 수집은 게시의 인덱스 단계 안에서만 돈다.

**기술:** Python 3.12(uv, `site-gen/`), Jinja2, jsonschema, PyYAML, boto3, bash, 순수 JS/CSS/SVG, pytest + Playwright(chromium).

**설계:** `docs/superpowers/specs/2026-11-22-dashboard-ui-design.md` (v2.2)
**요구사항명세:** `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md` (v2, REQ-076~145)
**시안:** `docs/superpowers/specs/assets/2026-11-22-dashboard-ui/home.html`, `project.html` — 배치·색·문구의 기준이다.

각 Task의 테스트는 요구사항명세에서 그 REQ의 수용기준을 **전부** 단언한다. 이 계획의 코드 블록은 이름·픽스처·대표 단언을 정해 주는 것이고, 수용기준의 나머지 Given도 같은 방식으로 더한다.

## 전역 제약

- 생성물에 외부 요청이 없다: CDN, 웹폰트, `@import`, 사이트 밖 `<script src>`·`<link>`·`<img>` 금지. 외부 라이브러리를 새로 넣지 않는다.
- 스크립트가 꺼져도 과제 목록·수치·모든 탭 구역이 보인다. 서버가 HTML을 먼저 그리고 `app.js`는 덧입히기만 한다.
- 측정하지 않은 값은 `null`로 다루고 화면에는 "측정 없음"·"연결 없음"·"—"로 쓴다. 0으로 채우지 않는다.
- 인덱스 재생성은 멱등이다. 실행 시각·난수·정렬되지 않은 순회를 출력에 쓰지 않는다. 수는 단위별 고정 자릿수로 적는다.
- `site-gen/td/site/static/site.css`와 `site.js`는 한 글자도 바꾸지 않는다. 새 화면은 `static/v2/app.css`, `static/v2/app.js`만 쓴다. `static/v2/`는 이 작업이 운영에 게시된 뒤로는 run 페이지의 모양을 깨는 변경을 하지 않는다(그런 변경은 `static/v3/`).
- `suts/<sut>/runs/<runId>/` 아래 페이지의 링크는 바뀌지 않는 주소만 가리킨다(SUT는 `suts/<sut>/index.html`). run 렌더는 `dashboard.yaml`을 읽지 않는다.
- 제외된(비공개·404) 과제의 이름·`repo`·설명은 게시되는 어떤 파일에도 쓰지 않는다. 게시 기록의 사유에는 개수만 쓰고 이름은 표준 오류에만 낸다.
- 새로 쓰는 모든 게시 파일은 `td.redact`와 업로드 게이트를 지난다. 토큰 평문은 환경 변수 `SONAR_TOKEN`으로만 다룬다.
- `pipeline/`, `site-gen/` 코드에 `petclinic`, `org.springframework.samples` 문자열을 넣지 않는다(PoC REQ-050).
- 테스트는 `tests/acceptance/`의 pytest, 이름은 `test_req<NNN>_<요약>`. 테스트가 띄운 프로세스는 PID를 잡아 모든 종료 경로에서 정리한다. 전제가 없으면 skip이 아니라 실패다.
- 기존 PoC 테스트의 기대값은 요구사항명세 §3 표에 적힌 것만 고친다. 표에 없는 테스트가 깨지면 구현을 고친다.
- 산문·주석·문서는 한국어, 식별자·커밋 메시지는 영어.
- 실행 명령: `uv run --project site-gen pytest tests/acceptance/<파일> -v`.
- 범위가 늘면 멈추고 요구사항명세에 REQ를 추가한 뒤 재개한다.

## 검토 초점

설계가 말하지 않지만 실제로 만날 입력이다. 각 줄의 테스트는 괄호 안 Task에 넣었다.

1. 과제 이름·설명·검사 이름에 `<`, `&`, 따옴표가 있다 → HTML과 JSON 블록 양쪽에서 이스케이프돼 그대로 글자로 보인다. (Task 9)
2. 미러의 스냅숏 파일이 깨졌거나 스키마를 어긴다 → 재생성이 죽지 않고 그 파일만 버리며 `projects.json`에 사유를 적는다. (Task 3)
3. 과제가 0개다(빈 설정, run 없음) → 홈이 "등록된 과제가 없습니다"를 보이고 결론 문장·요약이 0으로 나누지 않는다. (Task 9)
4. run이 하나뿐이거나 모든 run에 값이 없다 → 차트가 점 하나(선 없음) 또는 축만 그린다. (Task 3)
5. 주소의 `#`이 없는 탭이거나 설정에서 뺀 탭이다 → 첫 탭이 열린다. (Task 10)

## 파일 구조

| 파일 | 책임 |
|---|---|
| `dashboard.yaml` | 운영 설정(과제 20개, 기본 규칙) |
| `site-gen/td/dashboard_config.py` | 설정 읽기·검증, 지표 카탈로그, 값·칸 표기, 상태 판정, 결론 문장, 각주 |
| `site-gen/td/schemas/dashboard.schema.json`, `project-snapshot.schema.json` | 스키마 |
| `site-gen/td/collect.py` | GitHub·Sonar 수집, 스냅숏 쓰기 |
| `pipeline/collect.sh` | Sonar 환경 준비, 토큰 발급·정리, `td.collect` 실행 |
| `pipeline/publish-index.sh` | 인덱스 전용 게시 진입점 |
| `pipeline/lib/sonar-token.sh` | 단계에 묶이지 않는 토큰 함수 + S11용 덮개 |
| `site-gen/td/site/metrics.py` | run 지표 추출, 과제 뷰 조립, 시계열, 집계, 탭 데이터 |
| `site-gen/td/site/charts.py` | 시계열 SVG |
| `site-gen/td/site/nav.py` | 공통 띠 HTML과 외부 리포트 주입 |
| `site-gen/td/site/index.py` | `rebuild` (조립만) |
| `site-gen/td/site/pages.py`, `layout.py` | run 렌더, 리포트 카드 |
| `site-gen/td/site/templates/*.j2` | 새 틀 |
| `site-gen/td/site/static/v2/app.css`, `app.js` | 새 디자인 |
| `site-gen/td/publish.py` | 인덱스 단계 공용화, 인덱스 전용 게시, 과제 삭제 |
| `tests/acceptance/dashboard_fixtures.py` | 고정 사이트 빌더, 서버, 가짜 gh·ssh |
| `tests/acceptance/conftest.py` | 공용 `browser` fixture, 기준 세션 fixture |

## 공용 테스트 기반 (Task 3에서 만들고 뒤 Task가 넓힌다)

`tests/acceptance/dashboard_fixtures.py`:

| 이름 | 서명과 뜻 |
|---|---|
| `write_run` | `write_run(base: Path, sut: str, run_id: str, **overrides) -> Path` — `helpers.make_site_run`으로 완료 run 뼈대를 만들고 `run.json` `kpis`와 `stages/S07·S09·S10.json`을 더한다. `overrides`: `tests_pass`, `line`, `agg_line`, `generations`(`{genId: (통과, 시나리오)}`), `sonar`(dict 또는 `None`), `top10`, `impact`, `started`, `last_finished`, `only_stages`, `stage_status`(`{"S09": "failed"}`) |
| `write_snapshot` | `write_snapshot(base: Path, name: str, date: str, **overrides) -> Path` — `overrides`: `visibility`, `description`, `language`, `ci`(dict 또는 `None`), `sonar`(dict 또는 `None`), `ci_state`, `sonar_state`, `problems` |
| `snap` | `snap(**overrides) -> dict` — `write_snapshot`에 넘길 dict. 지름길 `ci_runs`, `ci_successes`(나머지 CI 필드를 계산) |
| `cfg_with` | `cfg_with(*, pipeline: Iterable[str] = (), plain: Iterable[str] = (), **sections) -> dict` — `pipeline`은 `repo` 없이 `sut`만 가진 과제(스냅숏 없이 run으로 그려진다), `plain`은 `repo: o/<name>`만 가진 과제. `sections`로 `status`·`home`·`project`를 덮어쓴다. 한 이름만 줄 때는 문자열도 받는다 |
| `make_site` | `make_site(root: Path, *, runs: dict[str, list[dict]] = {}, snapshots: dict[str, list[dict]] = {}, config: dict | None = None) -> Path` — 사이트 디렉터리와 `root/dashboard.yaml`, `root/suts/<sut>/sut.yaml`(필요한 SUT마다 최소 내용)을 만든다 |
| `load_cfg` | `load_cfg(site: Path) -> Config` — `site.parent/dashboard.yaml`을 `site.parent/suts` 기준으로 읽는다 |
| `rebuild_site` | `rebuild_site(site: Path, cfg: Config | None = None) -> list[Path]` |
| `serve` | `serve(directory: Path) -> ContextManager[str]` — 로컬 `http.server`, 끝이 `/`인 URL. 종료 시 PID 정리와 잔존 확인 |
| `open_page` | `open_page(browser, url: str, *, javascript: bool = True, scheme: str = "light", width: int = 1280)` |
| `status_of` | `status_of(site: Path, name: str) -> str` — `projects.json`에서 읽은 수준 |
| `fake_gh`, `fake_ssh` | Task 5·6에서 정의 |
| `home_site`, `proj_site` | Task 9·10에서 정의하는 고정 사이트 빌더 |

`tests/acceptance/conftest.py`에 session 범위 `browser` fixture(chromium)를 둔다. `test_site.py`의 지역 `browser` fixture는 이것으로 바꾼다.

---

### Task 1: 설정 파일과 지표 카탈로그

**REQ-IDs:** REQ-077, REQ-078 (REQ-076의 검증 부분)

**Files:**
- Create: `site-gen/td/dashboard_config.py`, `site-gen/td/schemas/dashboard.schema.json`, `dashboard.yaml`
- Test: `tests/acceptance/test_dashboard_config.py`

**Interfaces:**
- Produces:
  - `class ConfigError(Exception)` — 메시지는 `<키 경로>: <사유>`.
  - `@dataclass(frozen=True) class Project: name: str; repo: str | None; sonar_key: str | None; sut: str | None; implicit: bool = False`
  - `@dataclass(frozen=True) class Config: projects: tuple[Project, ...]; status: dict; home: dict; project: dict; path: Path | None`
  - `@dataclass(frozen=True) class Metric: name: str; label: str; unit: str; scope: str` — `unit`은 `ratio|percent|count|seconds|score|string|bool|list|gate`, `scope`는 `run|snapshot|both|aggregate`.
  - `CATALOG: dict[str, Metric]` — 설계 §6.2의 과제 지표(`hotspot.topName` 포함)와 집계 지표 전부. 표시 이름은 각주에 쓰인다: `ci.runs` "CI 실행 수", `ci.successRate` "CI 성공률", `sonar.vulnerabilities` "Sonar 취약점", `sonar.gate` "Sonar 게이트", `ci.lastFailed` "최근 CI 실패", `ci.failedChecks` "실패한 검사 수".
  - `COLUMN_IDS`, `TAB_IDS`: 설계의 열·탭 식별자 튜플.
  - `load(path: Path, suts_dir: Path) -> Config` — 스키마와 등록 규칙 검증.
  - `empty() -> Config` — 과제 없음, `status`·`home`·`project`는 설계 §6.2 예시 값(`none.allMissing`은 `[ci.runs, sonar.gate, tests.passRate]`).
  - `resolve(env: Mapping[str, str], repo_root: Path) -> Config` — `TD_DASHBOARD_CONFIG`가 있으면 그 파일(`suts_dir`은 `repo_root/suts`, `TD_DASHBOARD_SUTS_DIR`로 바꿀 수 있다), 없고 `TD_SITE_PREFIX`가 있으면 `empty()`, 둘 다 없으면 `repo_root/dashboard.yaml`.
  - `with_implicit(cfg: Config, suts_with_runs: Iterable[str]) -> Config` — 어느 과제에도 이어지지 않은 SUT를 `Project(name=sut, repo=None, sonar_key=None, sut=sut, implicit=True)`로 더한다. 이름이 겹치면 `ConfigError`.
  - `format_value(metric: str, value) -> str` — `ratio`는 `41.5%`(소수 1자리), `percent`는 `57.1%`, `count`는 정수, `seconds`는 `8분 35초`, `score`는 소수 1자리, `gate`는 `OK`→"통과"·`ERROR`→"실패"·그 밖은 원문, `bool`은 "예"·"아니오", `list`는 `, `로 이음, `None`은 `—`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_req076_schema_violation_fails(tmp_path):
    for body, where in CASES_076:        # projects 키 없음 / schema: 2 / status.rules가 문자열
        with pytest.raises(ConfigError) as exc:
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
        assert where in str(exc.value)   # 예: "status.rules"

def test_req077_project_registration_rules(tmp_path):
    for name in ("a/b", "..", "bad name", "-p", ".p", "과제", ""):
        with pytest.raises(ConfigError, match="projects"):
            dashboard_config.load(write(tmp_path, one_project(name=name)), SUTS_DIR)
    for body, word in CASES_077:         # Foo+foo, 같은 repo 둘, sut: nope, 한 sut를 둘이 가리킴
        with pytest.raises(ConfigError, match=word):
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
    cfg = dashboard_config.load(write(tmp_path, one_project(name="mini")), SUTS_DIR)
    with pytest.raises(ConfigError, match="mini"):
        dashboard_config.with_implicit(cfg, ["mini"])

def test_req078_unknown_metric_or_operator(tmp_path):
    for body, word in [(RULE_WITH("ci.nope"), "ci.nope"), (RULE_OP("between"), "between"), (COLUMN("foo"), "foo"),
                       (TAB("foo"), "foo"), (REASON("{ci.nope}"), "ci.nope"), (RULE_WITH("ci.successRateAll"), "ci.successRateAll"),
                       (COLUMN("status.noneCount"), "status.noneCount"), (TREND_SNAPSHOT("tia.selectedRatio"), "tia.selectedRatio")]:
        with pytest.raises(ConfigError, match=re.escape(word)):
            dashboard_config.load(write(tmp_path, body), SUTS_DIR)
    assert len(dashboard_config.load(REPO_ROOT / "dashboard.yaml", REPO_ROOT / "suts").projects) == 20
```

- [ ] **Step 2: 실패를 확인한다** → `ModuleNotFoundError: td.dashboard_config`
- [ ] **Step 3: 스키마와 `dashboard_config.py`를 쓴다.** 스키마는 `additionalProperties: false`. 조건은 `{metric, op, value}` 또는 `{all: [조건...]}`의 재귀 정의. 스키마 뒤의 추가 검증: 이름 문법 `^[A-Za-z0-9][A-Za-z0-9._-]*$`와 `..` 금지, 대소문자 무시 유일, `repo` 유일, `sut`의 `suts_dir/<sut>/sut.yaml` 존재와 유일, 규칙·치환 이름이 `CATALOG`의 과제 지표인지, `home.summary`가 집계 지표인지, `trend.run`·`trend.snapshot`이 그 `scope`에 맞는지, 열·탭 이름이 `COLUMN_IDS`·`TAB_IDS`에 있는지.
- [ ] **Step 4: `dashboard.yaml`을 쓴다.** 설계 §6.2의 예시 그대로에, 과제는 설계의 표 20개. `spring-petclinic`은 `sut: petclinic`, `MailosaurDemo`는 `sonarKey: MailoSaurDemo`, `VcsStatistics`는 `sonarKey: vcsstatistics`.
- [ ] **Step 5: 통과를 확인한다** — 3개 PASS
- [ ] **Step 6: 커밋** — `feat(config): dashboard.yaml schema, metric catalog and registration checks`

### Task 2: 상태 판정, 결론 문장, 각주

**REQ-IDs:** REQ-081, REQ-082, REQ-084(문장 선택 부분)

**Files:**
- Modify: `site-gen/td/dashboard_config.py`
- Test: `tests/acceptance/test_dashboard_status.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `@dataclass(frozen=True) class Verdict: level: str; reasons: tuple[str, ...]; partial: bool`
  - `evaluate(values: Mapping[str, object], cfg: Config, *, has_repo: bool = True) -> Verdict` — 순서는 설계 §6.2 "상태 판정 순서". `partial`은 `has_repo`이고 `ci.runs`와 `sonar.gate` 가운데 정확히 하나만 있을 때 참.
  - `headline(values: Mapping[str, object], verdict: Verdict, cfg: Config) -> str` — 위험·주의면 `"<상태 이름>: <사유 · 사유>"`, 측정 없음이면 `"측정된 지표가 없습니다"`, 양호면 `project.headline`의 처음 걸린 문장(치환할 값이 없으면 건너뜀).
  - `rules_text(cfg: Config) -> list[str]` — 각주. 수준마다 한 줄(규칙이 없는 수준은 줄이 없다). 조건은 `<CATALOG 표시 이름> <기호> <format_value>`, 기호는 `eq =`, `ne ≠`, `lt <`, `le ≤`, `gt >`, `ge ≥`. `all`은 `" 그리고 "`, 같은 수준의 규칙은 `" / "`. 기본 설정의 주의 줄: `"주의: CI 실행 수 ≥ 5 그리고 CI 성공률 < 90.0% / Sonar 취약점 > 0"`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
CFG = dashboard_config.empty()
OKCI = {"ci.runs": 9, "ci.successRate": 1.0, "ci.lastFailed": False, "ci.failedChecks": 0}

@pytest.mark.parametrize("values, level, reasons", [
    ({**OKCI, "sonar.gate": "ERROR"}, "crit", ("Sonar 품질 게이트 실패",)),
    ({**OKCI, "sonar.gate": "OK", "ci.lastFailed": True}, "crit", ("기본 브랜치의 최근 CI 실패",)),
    ({**OKCI, "sonar.gate": "OK", "ci.failedChecks": 1, "ci.failedCheckNames": ["build-and-test"]},
     "crit", ("최신 커밋의 검사 실패: build-and-test",)),
    ({"sonar.gate": "OK", "ci.runs": 11, "ci.failures": 6, "ci.successRate": 5 / 11, "ci.lastFailed": False, "ci.failedChecks": 0},
     "warn", ("최근 CI 11회 중 6회 실패",)),
    ({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 8}, "warn", ("Sonar 취약점 8건",)),
    ({**OKCI, "sonar.gate": "ERROR", "sonar.vulnerabilities": 2}, "crit", ("Sonar 품질 게이트 실패", "Sonar 취약점 2건")),
    ({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 0}, "good", ()),
])
def test_req081_rule_levels_and_reasons(values, level, reasons):
    verdict = dashboard_config.evaluate(values, CFG)
    assert (verdict.level, verdict.reasons) == (level, reasons)

def test_req082_missing_and_boundaries():
    ev = lambda v, **kw: dashboard_config.evaluate(v, CFG, **kw)
    ci = lambda runs, fails: {"ci.runs": runs, "ci.failures": fails, "ci.successRate": (runs - fails) / runs,
                              "ci.lastFailed": False, "ci.failedChecks": 0}
    assert ev({}).level == "none" and ev({"ci.runs": None, "sonar.gate": None, "tests.passRate": None}).level == "none"
    pipeline_only = ev({"tests.passRate": 1.0, "coverage.line": 0.9}, has_repo=False)
    assert pipeline_only.level == "good" and pipeline_only.partial is False
    assert ev(ci(4, 3)).level == "good" and ev({**ci(5, 1), "sonar.gate": "OK"}).level == "warn"
    assert ev({**ci(10, 1), "sonar.gate": "OK"}).level == "good" and ev({**ci(10, 2), "sonar.gate": "OK"}).level == "warn"
    assert ev({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 0}).level == "good"
    assert ev({**OKCI, "sonar.gate": "OK", "sonar.vulnerabilities": 1}).level == "warn"
    assert ev({"sonar.gate": "OK"}).level == "good"
    assert ev(ci(4, 0)).partial is True and ev({**ci(4, 0), "sonar.gate": "OK"}).partial is False
    assert ev({"sonar.gate": "OK"}, has_repo=False).partial is False

def test_req084_headline_selection():
    hl = lambda v: dashboard_config.headline(v, dashboard_config.evaluate(v, CFG), CFG)
    assert hl({"sonar.gate": "ERROR", "sonar.vulnerabilities": 2}) == "위험: Sonar 품질 게이트 실패 · Sonar 취약점 2건"
    assert hl({}) == "측정된 지표가 없습니다"
    assert hl({"sonar.gate": "OK", "tests.passRate": 1.0, "coverage.line": 0.415}) == "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 41.5%입니다"
    for rate in (0.97, None):
        assert "모두 통과" not in hl({"sonar.gate": "OK", "tests.passRate": rate, "coverage.line": 0.415})

def test_rules_text_shows_thresholds():
    lines = dashboard_config.rules_text(CFG)
    assert "주의: CI 실행 수 ≥ 5 그리고 CI 성공률 < 90.0% / Sonar 취약점 > 0" in lines
    assert lines[0].startswith("위험: Sonar 게이트 = 실패")
```

- [ ] **Step 2: 실패를 확인한다** → `AttributeError: evaluate`
- [ ] **Step 3: `evaluate`, `headline`, `rules_text`를 쓴다.** 연산은 `operator` 모듈의 여섯 함수 표. 값이 `None`이거나 비교할 수 없는 타입이면 조건은 거짓.
- [ ] **Step 4: 통과를 확인한다**
- [ ] **Step 5: 커밋** — `feat(config): status verdict, headline selection and rules footnote`

### Task 3: run 지표, 과제 뷰, 시계열, 차트, 설정을 받는 재생성

**REQ-IDs:** REQ-076, REQ-102, REQ-103, REQ-105, REQ-122, REQ-141

**Files:**
- Create: `site-gen/td/site/metrics.py`, `site-gen/td/site/charts.py`, `site-gen/td/schemas/project-snapshot.schema.json`, `tests/acceptance/dashboard_fixtures.py`
- Modify: `site-gen/td/site/index.py`, `tests/acceptance/conftest.py`, `tests/acceptance/test_site.py`(지역 `browser` fixture 제거)
- Test: `tests/acceptance/test_dashboard_index.py`, `tests/acceptance/test_dashboard_config.py`

**Interfaces:**
- Consumes: Task 1·2.
- Produces:
  - 스냅숏 스키마(`project-snapshot.schema.json`). 필수 필드와 타입:
    - `schema`(1), `name`, `repo`, `visibility`("public"), `collectedAt`, `date`(`YYYYMMDD`)
    - `repoInfo`: `pushedAt`, `language`(문자열 또는 `null`), `description`(문자열 또는 `null`), `defaultBranch`
    - `sources`: `{"ci": "ok"|"none"|"failed", "sonar": "ok"|"absent"|"failed"|"skipped"}` — `none`은 실행 0회, `absent`는 프로젝트 없음(404), `skipped`는 run 값을 쓰는 과제, `failed`는 읽기 실패
    - `ci`: 객체 또는 `null`. 객체면 `runs`, `successes`, `failures`(정수 또는 `null`), `successRate`(수 또는 `null`), `lastFailed`(참·거짓 또는 `null`), `failedChecks`(정수 또는 `null`), `failedCheckNames`(문자열 배열), `history`(0|1 배열, 오래된 것부터)
    - `sonar`: 객체 또는 `null`. 객체면 `gate`(문자열), `coverage`(수 또는 `null`), `bugs`, `vulnerabilities`, `codeSmells`, `ncloc`(정수 또는 `null`), `ratings`: `{reliability, security, maintainability}`(각 "A"~"E" 또는 `null`)
    - `problems`: `[{"source": "ci"|"sonar"|"repo", "reason": 문자열}]`
  - `metrics.run_metrics(run_dir: Path) -> dict[str, object]` — 설계 §6.2 "run에서 오는 것" 표의 이름 전부. 단계 JSON의 `status`가 `passed`·`degraded`가 아니면 그 단계에서 오는 지표는 `None`.
  - `metrics.load_snapshots(project_dir: Path) -> tuple[list[dict], list[str]]` — 날짜순 스냅숏(스키마를 지키는 것)과 버린 파일의 사유 목록.
  - `metrics.snapshot_metrics(snapshot: dict) -> dict[str, object]`
  - `metrics.build_projects(base: Path, cfg: Config, *, exclude: frozenset[str] = frozenset()) -> list[dict]` — 과제마다 `{"name", "repo", "sut", "pipeline": bool, "implicit": bool, "values": {...}, "verdict": {"level", "label", "reasons", "partial"}, "headline", "runs": [summarize_run 결과...], "latestRunDir": Path | None, "snapshots": [...], "sources": {"ci", "sonar"}, "stale": <마지막 수집 날짜> | None, "problems": [...], "description", "language", "ciHistory": [...]}`.
    - **그리는 대상**: 암묵 과제, `repo`가 없는 설정 과제(run으로 그린다), `repo`가 있고 최신 유효 스냅숏의 `visibility`가 `public`인 설정 과제. `exclude`의 이름과 그 밖의 과제는 목록에 없다.
    - `values`: 완료된 run이 있으면 run 지표를 넣고 `sonar.*`는 최신 run의 값만 쓴다. `ci.*`·`repo.*`는 최신 스냅숏. run이 없으면 스냅숏의 `sonar`.
    - `verdict`: `evaluate(values, cfg, has_repo=project.repo is not None)`.
    - 정렬: `status.order`, 그 안에서 이름(대소문자 무시).
  - `metrics.series(project: dict, cfg: Config) -> dict` — 설계 §6.4의 `series.json` 모양. `pipeline`이면 `kind: run`(점의 `href`는 과제 페이지 기준 상대 경로), 아니면 `kind: snapshot`.
  - `metrics.aggregate(projects: list[dict], cfg: Config) -> dict[str, dict]` — `home.summary`의 집계 지표마다 `{"label", "value": 표기 문자열 또는 "—", "detail": 덧말}`.
  - `charts.trend_svg(metric: Metric, points: list[dict], max_points: int = 30) -> str` — 점은 `<a class="pt" href=…>`(run) 또는 `<g class="pt" tabindex="0">`(스냅숏) 안의 `<circle>`. 속성 `data-id`, `data-at`, `data-value`(표기 문자열). 선 조각마다 `<polyline class="ln">`. 세로축: `ratio`는 0~1, `percent`는 0~100 고정. 그 밖은 0~최댓값이고, 모든 값이 같고 0보다 크면 0~값×2, 모든 값이 0이면 0~1.
  - `index.rebuild(site_root, prefix: str = "", config: Config | None = None, *, exclude: frozenset[str] = frozenset()) -> list[Path]` — `config`가 `None`이면 `dashboard_config.resolve(os.environ, repo_root)`. 설정 검증과 `with_implicit`을 **파일을 쓰기 전에** 한다. 이 Task에서는 인자를 받고 검증까지만 하고, 쓰는 파일은 지금과 같다(홈과 과제 페이지는 Task 9·10).
  - CLI: `python -m td.site.index <site_root> [prefix] [--config <파일>]`. `ConfigError`는 표준 오류에 내고 종료 코드 2.
  - 위 "공용 테스트 기반" 표의 함수들과 `conftest.py`의 `browser` fixture.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_req102_run_metrics(tmp_path):
    run = write_run(tmp_path, "pet", "20261120-131022Z-b6f9393-manual-036c288d",
        tests_pass=1.0, line=0.4152, agg_line=0.6091, generations={"base-r1": (21, 31), "jqa-r1": (30, 40)},
        sonar={"gate": "OK", "coverage": "57.1", "bugs": "2", "vulnerabilities": "18", "codeSmells": "69"},
        top10=[{"name": "Owner.getPet", "file": "Owner.java", "score": 27.345}], impact={"selected": 68, "indexedTests": 134},
        started="2026-11-20T13:10:22Z", last_finished="2026-11-20T13:18:57Z")
    m = metrics.run_metrics(run)
    assert (m["tests.passRate"], m["coverage.line"], m["coverage.aggregateLine"]) == (1.0, 0.4152, 0.6091)
    assert m["e2e.passRate"] == pytest.approx(51 / 71)
    assert (m["sonar.gate"], m["sonar.coverage"], m["sonar.vulnerabilities"], m["sonar.bugs"], m["sonar.codeSmells"]) == ("OK", 57.1, 18, 2, 69)
    assert (m["hotspot.topScore"], m["hotspot.topName"]) == (27.345, "Owner.getPet")
    assert m["tia.selectedRatio"] == pytest.approx(68 / 134) and m["run.durationSec"] == 515
    bare = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000000Z-aaaaaaa-manual-00000000",
                                         only_stages=["S00", "S01", "S08"], sonar=None))
    assert bare["e2e.passRate"] is None and bare["hotspot.topScore"] is None and bare["sonar.gate"] is None
    zero = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000001Z-aaaaaaa-manual-00000001", impact={"selected": 0, "indexedTests": 0}))
    assert zero["tia.selectedRatio"] is None
    failed = metrics.run_metrics(write_run(tmp_path, "pet", "20261118-000002Z-aaaaaaa-manual-00000002",
        stage_status={"S07": "failed", "S09": "failed", "S10": "skipped"}, generations={"g": (1, 2)},
        top10=[{"name": "X", "file": "X.java", "score": 9.0}], impact={"selected": 1, "indexedTests": 2}))
    assert failed["e2e.passRate"] is None and failed["hotspot.topScore"] is None and failed["tia.selectedRatio"] is None

def test_req103_series_points(tmp_path):
    site = make_site(tmp_path, runs={"pet": [RUN_A, RUN_B, RUN_C]}, snapshots={"kn": [snap(date="20261121"), snap(date="20261122")]},
                     config=cfg_with(pipeline="pet", plain="kn"))
    projects = {p["name"]: p for p in metrics.build_projects(site, load_cfg(site))}
    s = metrics.series(projects["pet"], load_cfg(site))
    assert s["kind"] == "run" and [p["id"] for p in s["points"]] == sorted(r["runId"] for r in (RUN_A, RUN_B, RUN_C))
    assert set(s["points"][0]["values"]) == set(s["metrics"]) and s["points"][0]["href"].endswith("/index.html")
    k = metrics.series(projects["kn"], load_cfg(site))
    assert k["kind"] == "snapshot" and [p["id"] for p in k["points"]] == ["20261121", "20261122"] and "href" not in k["points"][0]

def test_req105_legacy_fields_kept(tmp_path):
    site = make_site(tmp_path, runs={"pet": [RUN_A, RUN_B]}); rebuild_site(site, dashboard_config.empty())
    suts = json.loads((site / "suts.json").read_text())
    assert set(suts[0]) >= {"name", "runCount", "latest"} and suts[0]["runCount"] == 2
    assert set(suts[0]["latest"]) >= {"runId", "commit", "trigger", "startedAt", "stages", "kpis"}
    assert set(suts[0]["latest"]["kpis"]) >= {"passRate", "line", "sonarGate", "hotspot1"}
    runs = json.loads((site / "suts/pet/runs.json").read_text())
    assert [r["runId"] for r in runs] == [RUN_B["runId"], RUN_A["runId"]] and set(runs[0]) >= {"runId", "commit", "stages", "kpis"}

def test_req122_chart_axis_rules():
    ratio = charts.trend_svg(CATALOG["tests.passRate"], pts([0.2, 0.2]))
    assert all(t in ratio for t in (">0%<", ">50%<", ">100%<")) and cys(ratio) == {y_for(0.2, 0, 1)}
    assert ">100%<" in charts.trend_svg(CATALOG["sonar.coverage"], pts([57.1, 60.0]))
    count = charts.trend_svg(CATALOG["sonar.vulnerabilities"], pts([3, 18, 7])); assert ">18<" in count and ">0<" in count
    flat = charts.trend_svg(CATALOG["sonar.bugs"], pts([2, 2, 2])); assert cys(flat) == {CHART_MID_Y}
    zeros = charts.trend_svg(CATALOG["sonar.bugs"], pts([0, 0])); assert cys(zeros) == {CHART_BASE_Y}
    assert charts.trend_svg(CATALOG["sonar.bugs"], pts([2, 2, 2])) == flat

def test_req141_aggregate_metrics(tmp_path):
    site = make_site(tmp_path, snapshots={"a": [snap(ci_runs=10, ci_successes=9, sonar=None, sonar_state="absent")],
        "b": [snap(ci_runs=10, ci_successes=1, sonar=None, sonar_state="absent")],
        "c": [snap(ci=None, ci_state="none", sonar={"gate": "OK", "coverage": 0.0})],
        "d": [snap(ci=None, ci_state="none", sonar={"gate": "ERROR", "coverage": 57.1})]}, config=cfg_with(plain=["a", "b", "c", "d"]))
    agg = metrics.aggregate(metrics.build_projects(site, load_cfg(site)), load_cfg(site))
    assert (agg["ci.successRateAll"]["value"], agg["ci.successRateAll"]["detail"]) == ("50.0%", "10 / 20회")
    assert agg["sonar.gatePassCount"]["value"] == "1 / 2" and agg["sonar.coverageNonZeroCount"]["value"] == "1 / 4"
    assert agg["status.noneCount"]["value"] == "0"
    assert metrics.aggregate([], dashboard_config.empty())["ci.successRateAll"]["value"] == "—"

def test_req076_cli_fails_before_writing(tmp_path):          # test_dashboard_config.py
    site = make_site(tmp_path, runs={"pet": [RUN_A]})
    bad = tmp_path / "bad.yaml"; bad.write_text("schema: 1\nprojects: []\nstatus: {rules: nope}\n")
    proc = subprocess.run([sys.executable, "-m", "td.site.index", str(site), "--config", str(bad)], capture_output=True, text=True, cwd=SITE_GEN)
    assert proc.returncode == 2 and "status.rules" in proc.stderr and not (site / "index.html").exists()

# 검토 초점 2, 4
def test_broken_snapshot_is_dropped_with_reason(tmp_path):
    site = make_site(tmp_path, snapshots={"kn": [snap(date="20261121")]}, config=cfg_with(plain="kn"))
    (site / "projects/kn/snapshots/20261122.json").write_text("{not json")
    kn = metrics.build_projects(site, load_cfg(site))[0]
    assert kn["snapshots"][-1]["date"] == "20261121" and any("20261122" in p for p in kn["problems"])

def test_chart_single_point_and_all_missing():
    one = charts.trend_svg(CATALOG["tests.passRate"], pts([0.9])); assert one.count("<circle") == 1 and "<polyline" not in one
    none = charts.trend_svg(CATALOG["tests.passRate"], pts([None, None])); assert "<circle" not in none and "<svg" in none
```

- [ ] **Step 2: 실패를 확인한다** → `ModuleNotFoundError: td.site.metrics`
- [ ] **Step 3: `dashboard_fixtures.py`와 `conftest.py`의 `browser`를 쓴다.**
- [ ] **Step 4: 스냅숏 스키마, `metrics.py`, `charts.py`를 쓴다.** 차트 크기는 지금 `index.py`의 `CHART_W, CHART_H`(520×190)와 여백을 옮겨 쓴다. 좌표는 소수 1자리.
- [ ] **Step 5: `index.rebuild`와 `main`에 `config`·`exclude`·`--config`를 더한다.** 검증을 먼저 하고 실패하면 아무것도 쓰지 않는다.
- [ ] **Step 6: 통과를 확인한다** — 새 테스트 8개 PASS, `pytest tests/acceptance/test_unit_index.py tests/acceptance/test_site.py -v` PASS(기존 `line_chart`는 지우지 않는다)
- [ ] **Step 7: 커밋** — `feat(site): run metrics, project views, series, trend charts; rebuild takes config`

### Task 4: 도구 고정 (hotspot 커밋 빌드, tia 올리기)

**REQ-IDs:** REQ-129 (REQ-130·131의 준비. PoC REQ-036, 058 개정)

**Files:**
- Modify: `tools.pin.yaml`, `site-gen/td/prepare.py`, `pipeline/S00-prepare.sh`, `pipeline/S10-tia.sh`, `tests/acceptance/test_prepare.py`, `tests/acceptance/test_unit_tools.py`, `tests/acceptance/test_reports.py`
- Create: `tests/fixtures/reports/{hotspots.html,api_report.html,tia.html,README.md}`

**Interfaces:**
- Produces: `tools.pin.yaml`의 `hotspot: {repo: baekchangjoon/hotspot-analysis, commit: a5baac6c59273838374fe8a3cebf39ccc876d5c4, jdk: 21, gradleTask: bootJar, jarGlob: 'build/libs/hotspot-*.jar'}`, `tia.commit: c4e6e9e2c18f52e3315cc90a6f98fa16506c9199`. `tools.lock`의 `hotspot`: `{commit, sha256, path}`. `run.json` `tools.hotspot`은 커밋 앞 7자. 표본 리포트 3개(뒤 Task의 화면 테스트 입력).

- [ ] **Step 1: 실패하는 테스트를 쓴다.** 기존 fixture `s00`(`test_prepare.py`)을 쓴다: `.lock`은 `run_dir/tools.lock`을 읽은 dict, 도구 디렉터리는 `s00.work / "tools"`.

```python
def test_req129_hotspot_commit_build(s00):                       # test_prepare.py
    pin = yaml.safe_load((REPO_ROOT / "tools.pin.yaml").read_text())["hotspot"]["commit"]
    tools = s00.work / "tools"
    head = subprocess.check_output(["git", "-C", str(tools / "hotspot-src"), "rev-parse", "HEAD"], text=True).strip()
    assert len(pin) == 40 and head == pin and s00.lock["hotspot"]["commit"] == pin
    assert s00.lock["hotspot"]["sha256"] == hashlib.sha256((tools / "hotspot.jar").read_bytes()).hexdigest()

def test_req129_short_hotspot_commit_fails(tmp_path):            # test_unit_tools.py
    pin = yaml.safe_load((REPO_ROOT / "tools.pin.yaml").read_text()); pin["hotspot"]["commit"] = "a5baac6"
    path = tmp_path / "tools.pin.yaml"; path.write_text(yaml.safe_dump(pin))
    with pytest.raises(prepare.PrepareError, match="hotspot.commit"):
        prepare.load_pin(path)
```

- [ ] **Step 2: 실패를 확인한다** — 첫 번째는 `KeyError: 'commit'`, 두 번째는 `DID NOT RAISE`
- [ ] **Step 3: `prepare.py`를 고친다.** `ARTIFACT_TOOLS`에서 `hotspot`을 빼고, `load_pin`의 필수 도구와 40자 검증 대상에 `hotspot`을 넣고, `tools.lock`의 hotspot을 S00이 넘긴 커밋과 jar sha256으로 쓴다(tia 항목과 같은 경로).
- [ ] **Step 4: `S00-prepare.sh`에 hotspot 빌드를 넣는다.** tia 블록과 같은 모양: `JAVA21="$(td_java_home 21)" || s00_fail …`, `fetch_git_tool "$TOOLS_DIR/hotspot-src" https …`, 커밋 대조, `$TOOLS_DIR/hotspot.commit` 표식이 다르거나 jar가 없을 때만 `JAVA_HOME="$JAVA21" "$SRC/gradlew" -p "$SRC" --no-daemon -q bootJar`, `jarGlob`에 맞는 jar 가운데 이름에 `-plain`이 없는 것 하나를 `$TOOLS_DIR/hotspot.jar`로 복사(S09는 이 경로를 그대로 쓴다). 실패는 `s00_fail`. 도구 요약의 hotspot 값은 커밋 앞 7자.
- [ ] **Step 5: `S10-tia.sh`의 `tia report` 호출에 `--impact "$S10_DIR/impact.json"`을 더한다.** `--scenarios`는 유지.
- [ ] **Step 6: `tools.pin.yaml`을 바꾸고 요구사항명세 §3의 REQ-058 줄대로 기존 테스트를 고친다.** `test_req058_*`의 hotspot·TIA 기대값, sha256 변조 테스트와 `record_pin` 테스트의 대상을 pjacoco로.
- [ ] **Step 7: 통과를 확인한다** — `pytest tests/acceptance/test_prepare.py tests/acceptance/test_unit_tools.py -v` 전부 PASS. 이어서 `pytest tests/acceptance/test_reports.py -k "req035 or req036" -v`. `tia.html`에서 커밋을 읽는 위치가 바뀌어 `req036`이 깨지면 요구사항명세 §3의 REQ-036 줄대로 그 읽는 위치만 고친다.
- [ ] **Step 8: 표본 리포트를 고정한다.** Step 7의 `test_reports.py`가 petclinic으로 돌린 S09·S10 산출물(`hotspots.html`, `api_report.html`, `tia.html`)을 `pages.sanitize_site`와 같은 가리기를 거쳐 `tests/fixtures/reports/`에 둔다. `README.md`에 만든 명령과 도구 커밋을 적는다. 세 파일에서 다음을 확인해 README에 적는다(뒤 Task의 선택자가 된다): hotspot 지도의 SVG id(`hm-map`)와 옆 패널 id(`hm-side`), TIA의 페이지 전환 탭 선택자(`#seg [role=tab]`)와 "읽는 법" 블록 선택자, 변경 파일 목록의 선택자. 이 계획에 적힌 선택자와 다르면 README의 것이 맞다.
- [ ] **Step 9: 커밋** — `build(tools): pin hotspot by commit with source build; bump tia to report redesign`

### Task 5: 단계에 묶이지 않는 Sonar 토큰 함수

**REQ-IDs:** REQ-097 (S11 쪽 절반)

**Files:**
- Modify: `pipeline/lib/sonar-token.sh`, `tests/acceptance/dashboard_fixtures.py`
- Test: `tests/acceptance/test_dashboard_collect.py`

**Interfaces:**
- Produces (bash):
  - `td_sonar_token_issue_named <name>` — 이름 그대로 발급(만료 = 지금 + `TD_SONAR_TOKEN_LIFETIME_MS`), 행 수 1 확인, `SONAR_TOKEN` export, `td.sonar validate`. 정리 trap은 걸지 않는다(호출자가 건다). 발급 도중 실패해도 `td_sonar_token_revoke_named`가 그 이름을 지울 수 있게 이름을 먼저 기억한다.
  - `td_sonar_token_revoke_named` — 기억한 이름의 행을 지우고 0행 확인, `SONAR_TOKEN` unset. 실패하면 "토큰 잔존 가능(<name>), 발급 2시간 후 서버에서 만료된다" 경고를 한 번 내고 `return 1`. 장애 주입 지점은 `TD_SONAR_HOOK_STAGE`(기본 `S11`)의 `cleanup-ssh`.
  - 기존 `td_sonar_token_issue <runId>`, `td_sonar_token_revoke`, `td_sonar_revoke_redact`, `_td_sonar_revoke_on_exit`는 이름과 관측되는 동작을 유지하고 위 둘 위에 얹는다.
- Produces (Python): `dashboard_fixtures.fake_ssh(tmp_path, *, fail_delete: bool = False, lose_insert_reply: bool = False) -> FakeSsh` — `.bin_dir`(PATH 앞에 둘 디렉터리. 안의 `ssh`가 인자에 `psql`이 있으면 가로채고, 없으면 실제 `ssh`를 `exec`한다), `.rows() -> list[str]`(남은 토큰 이름), `.log() -> str`(받은 SQL 전부), `.seed(name, *, expired=False)`. `\d user_tokens`에는 실제 스키마 모양으로 답한다. `dashboard_fixtures.token_env(tmp_path, ssh, sonar_url) -> dict` — `TD_SITE_PREFIX`, `TD_SONAR_URL_OVERRIDE`, `TD_LIGHTSAIL_IP`, `TD_SSH_KEY_PATH`, `PATH`.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** 가짜 Sonar는 `fake_sonar.start_fake_sonar()`로 띄우고 `api/authentication/validate`에 `{"valid": true}`로 답하게 한다.

```python
def bash_token(tmp_path, script, env):       # common.sh와 sonar-token.sh를 source한 뒤 script 실행. TD_RUN_DIR은 주지 않는다
    ...

def test_named_issue_and_revoke_need_no_stage_state(tmp_path, fake_sonar_url):
    ssh = fake_ssh(tmp_path)
    out = bash_token(tmp_path, '''
        export TD_SONAR_URL="$(td_py -m td.sonar url)"
        td_sonar_token_issue_named td-collect-20261122T000000Z-abcd1234 || exit 3
        [[ -n "$SONAR_TOKEN" ]] || exit 4
        td_sonar_token_revoke_named || exit 5
        [[ -z "${SONAR_TOKEN:-}" ]] || exit 6''', token_env(tmp_path, ssh, fake_sonar_url))
    assert out.returncode == 0 and ssh.rows() == []
    assert "td-collect-20261122T000000Z-abcd1234" in ssh.log() and "+ 7200000" in ssh.log()

def test_named_revoke_failure_warns_once(tmp_path, fake_sonar_url):
    ssh = fake_ssh(tmp_path, fail_delete=True)
    out = bash_token(tmp_path, 'export TD_SONAR_URL="$(td_py -m td.sonar url)"; td_sonar_token_issue_named td-collect-x; '
                               'td_sonar_token_revoke_named; echo rc=$?; td_sonar_token_revoke_named; echo rc2=$?', token_env(tmp_path, ssh, fake_sonar_url))
    assert "rc=1" in out.stdout and out.stderr.count("토큰 잔존 가능") == 1 and "2시간 후" in out.stderr

def test_s11_wrapper_leaves_collect_rows(tmp_path, fake_sonar_url, run_dir_with_s11):
    ssh = fake_ssh(tmp_path); ssh.seed("td-collect-x")
    out = bash_token(tmp_path, 'export TD_SONAR_URL="$(td_py -m td.sonar url)"; td_sonar_token_issue r1 && td_sonar_token_revoke',
                     {**token_env(tmp_path, ssh, fake_sonar_url), "TD_RUN_DIR": str(run_dir_with_s11)})
    assert out.returncode == 0 and ssh.rows() == ["td-collect-x"]
```

- [ ] **Step 2: 실패를 확인한다** → `td_sonar_token_issue_named: command not found` (종료 코드 127)
- [ ] **Step 3: 함수를 나눈다.** SQL과 `td.sonar validate` 호출은 그대로 옮긴다.
- [ ] **Step 4: 통과를 확인한다** — 새 테스트 3개와 `pytest tests/acceptance/test_unit_sonar.py -v` 전부 PASS(기존 `_bash_with_fake_ssh`와 그 테스트는 고치지 않는다)
- [ ] **Step 5: S11 회귀를 확인한다** — `pytest tests/acceptance/test_sonar.py -k "req038 or req064 or req065 or req066" -v` PASS(기대값을 고치지 않는다)
- [ ] **Step 6: 커밋** — `refactor(sonar): stage-neutral token issue/revoke under the S11 wrappers`

### Task 6: 수집기

**REQ-IDs:** REQ-085, REQ-086, REQ-087, REQ-088, REQ-089, REQ-090, REQ-091, REQ-092, REQ-093, REQ-094, REQ-095, REQ-096, REQ-097, REQ-143 (089·090의 화면 부분은 Task 9)

**Files:**
- Create: `site-gen/td/collect.py`, `pipeline/collect.sh`
- Modify: `tests/acceptance/fake_sonar.py`, `tests/acceptance/dashboard_fixtures.py`
- Test: `tests/acceptance/test_dashboard_collect.py`

**Interfaces:**
- Consumes: Task 1(`Config`), Task 3(스냅숏 스키마, `load_snapshots`), Task 5(토큰 함수, `fake_ssh`, `token_env`).
- Produces:
  - `python -m td.collect run --config <파일> --site <접두까지 포함한 사이트 디렉터리> --suts-dir <dir>` — 표준 출력에 JSON 한 줄:
    `{"status": "ok"|"degraded", "reasons": [<게시해도 되는 문장>...], "written": [<사이트 상대 경로>...], "excluded": [<과제 이름>...], "unverified": [<과제 이름>...]}`.
    `reasons`에는 과제 이름을 넣지 않는다("비공개 과제 2개 제외", "수집 실패 1개 과제", "수집 예산 초과"). 이름은 표준 오류에만 낸다. 종료 코드는 설정 오류만 2, 그 밖은 0.
  - `python -m td.collect needs-sonar --config … --site … --suts-dir …` — Sonar를 읽을 과제 수를 출력.
  - `python -m td.collect amend --status degraded --reason <문장>` — 표준 입력의 결과 JSON에 상태와 사유를 더해 표준 출력으로 낸다.
  - `collect.collect(cfg: Config, site: Path, suts_dir: Path, *, now: datetime, env: Mapping[str, str]) -> dict`. `now`는 `td.state.now()`(기존 `TD_NOW` 훅을 따른다).
  - 모듈 상수: `CONNECT_TIMEOUT_SEC = 10`, `READ_TIMEOUT_SEC = 30`, `RETRIES = 2`, `RETRY_DELAYS_SEC = (2, 4)`, `BUDGET_SEC = 300`.
  - 환경 변수: `TD_GH_BIN`(기본 `gh`), `TD_SONAR_URL`, `SONAR_TOKEN`, `TD_COLLECT_BUDGET_SEC`, `TD_COLLECT_RETRY_DELAYS`(테스트용, `TD_SITE_PREFIX`가 있을 때만).
  - `pipeline/collect.sh --config <파일> --site <dir> --suts-dir <dir>`:
    1. `common.sh`, `sonar-token.sh`를 source한다(`env.sh`는 SUT 정리를 걸므로 쓰지 않는다). `TD_SONAR_HOOK_STAGE=collect`.
    2. `needs-sonar`가 0보다 크면: `td_sonar_load_env` → `export TD_SONAR_URL="$(td_py -m td.sonar url)"`(테스트의 `TD_SONAR_URL_OVERRIDE`는 이 명령이 기존 규칙대로 반영한다) → `td_sonar_verify_schema` → `td_sonar_preclean` → `trap cleanup EXIT INT TERM` → `td_sonar_token_issue_named "td-collect-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"`. 이 가운데 하나라도 실패하면 토큰 없이 수집을 계속하고(Sonar 값은 실패로 기록된다) 사유를 더한다.
    3. `td_py -m td.collect run …`의 표준 출력을 받아, 정리가 실패했으면 `amend`로 `degraded`와 "Sonar 토큰 정리 실패"를 더해 낸다.
    4. `cleanup`은 `td_sonar_token_revoke_named`를 한 번만 부른다. 신호를 받으면 돌고 있는 `td.collect` 자식에 같은 신호를 보내고 기다린 뒤 정리한다.
  - `dashboard_fixtures.fake_gh(tmp_path, repos: dict[str, dict]) -> FakeGh` — `.path`(실행 파일), `.calls`(받은 인자 목록), `.set(repo, **fields)`. 저장소마다 `visibility`("public"|"private"|"internal"), `missing`(404), `runs`(최신순 결론값 목록), `checks`(`[{name, conclusion, started_at, status}]`), `fail`(`{"status": 429, "retry_after": 1, "times": 1}`), `hang`(초), `description`, `language`, `default_branch`. `gh api -i <path>` 형식에 실제 `gh`처럼 상태 줄·헤더·빈 줄·본문으로 답한다.
  - `fake_sonar`: 프로젝트 키별 게이트·측정값, 404, 500, 지연, `.requests`(받은 `(경로, 키)` 목록).

- [ ] **Step 1: 가짜를 넓히고 실패하는 테스트를 쓴다.** REQ마다 `test_req<NNN>_…` 하나(이름은 요구사항명세 매트릭스). 대표:

```python
def test_req085_ci_conclusion_classes(tmp_path, collect_env):
    newest_first = ["success", "success", "failure", "cancelled", "timed_out", "success", "startup_failure",
                    "skipped", "neutral", "action_required", "stale"]
    gh = fake_gh(tmp_path, {"o/a": {"runs": newest_first, "default_branch": "trunk"}, "o/b": {"runs": []}, "o/c": {"runs": ["cancelled", "skipped"]}})
    run_collect(tmp_path, cfg_with(plain=["a", "b", "c"]), gh=gh, env=collect_env)
    ci = snapshot(tmp_path, "a")["ci"]
    assert (ci["runs"], ci["successes"], ci["failures"], ci["lastFailed"]) == (6, 3, 3, False)
    assert ci["history"] == [0, 1, 0, 0, 1, 1]
    for name in ("b", "c"):
        ci = snapshot(tmp_path, name)["ci"]
        assert [ci[k] for k in ("runs", "successes", "failures", "successRate", "lastFailed")] == [None] * 5 and ci["history"] == []
    call = next(c for c in gh.calls if "actions/runs" in " ".join(c) and "o/a" in " ".join(c))
    assert all(part in " ".join(call) for part in ("branch=trunk", "status=completed", "per_page=30"))

def test_req089_private_repo_excluded(tmp_path, collect_env):
    gh = fake_gh(tmp_path, {"o/a": {}, "o/secret": {"visibility": "private", "description": "internal thing"}, "o/gone": {"missing": True}, "o/d": {}})
    out, err = run_collect(tmp_path, cfg_with(plain=["a", "secret", "gone", "d"]), gh=gh, env=collect_env, with_stderr=True)
    assert out["status"] == "degraded" and sorted(out["excluded"]) == ["gone", "secret"] and out["reasons"] == ["비공개 과제 2개 제외"]
    assert "secret" in err and "gone" in err
    assert not (tmp_path / "site/projects/secret").exists() and not (tmp_path / "site/projects/gone").exists()
    assert (tmp_path / "site/projects/a/latest.json").exists() and (tmp_path / "site/projects/d/latest.json").exists()

def test_req092_token_removed_on_all_exits(tmp_path, collect_env):
    names = []
    for mode in ("ok", "sonar-500", "lost-insert-reply"):
        ssh = fake_ssh(tmp_path / mode, lose_insert_reply=(mode == "lost-insert-reply"))
        proc = run_collect_sh(tmp_path / mode, mode, ssh=ssh, env=collect_env)
        assert proc.returncode == 0 and ssh.rows() == [], mode
        names += re.findall(r"td-collect-\d{8}T\d{6}Z-[0-9a-f]{8}", ssh.log())
        assert "+ 7200000" in ssh.log()
    assert len(set(names)) == 3

def test_req143_visibility_unknown_keeps_last_public(tmp_path, collect_env):
    site = tmp_path / "site"; write_snapshot(site, "a", "20261121")
    gh = fake_gh(tmp_path, {"o/a": {"hang": 30}, "o/b": {"hang": 30}})
    out = run_collect(tmp_path, cfg_with(plain=["a", "b"]), gh=gh, env={**collect_env, "TD_COLLECT_BUDGET_SEC": "3", "TD_NOW": "2026-11-22T01:00:00Z"})
    assert out["status"] == "degraded" and sorted(out["unverified"]) == ["a", "b"] and out["written"] == []
    assert sorted(p.name for p in (site / "projects/a/snapshots").iterdir()) == ["20261121.json"] and not (site / "projects/b").exists()
    views = {p["name"]: p for p in metrics.build_projects(site, load_cfg(site))}
    assert list(views) == ["a"] and views["a"]["stale"] == "20261121"
```

  나머지(086, 087, 088, 090, 091, 093, 094, 095, 096, 097)도 요구사항명세의 수용기준을 그대로 단언한다. 091의 재시도 간격은 `TD_COLLECT_RETRY_DELAYS`를 쓰지 않고 `Retry-After: 1`의 실제 대기를 `gh.calls`의 시각 차로 본다. 097의 수집 쪽 절반: `ssh.seed("td-r1")` 뒤 수집을 돌리면 `ssh.rows() == ["td-r1"]`.

- [ ] **Step 2: 실패를 확인한다** → `No module named td.collect`
- [ ] **Step 3: `collect.py`를 쓴다.**
  - 순서: ① 모든 `repo` 과제의 `repos/<repo>`를 읽어 공개 여부를 확정한다. `public`이 아니거나 404면 제외, 그 밖의 실패(시간 초과, 5xx, 예산 초과)는 미확인. ② 공개 과제마다 실행 목록(`repos/<repo>/actions/runs?branch=<기본>&status=completed&per_page=30`)과 검사(`repos/<repo>/commits/<기본>/check-runs?per_page=100`). ③ Sonar 대상 과제마다 `td.sonar`의 게이트·측정값 호출. ④ 공개로 확정된 과제만 쓴다.
  - Sonar 대상: `repo`가 있고, (`sut`가 없거나 `site/suts/<sut>/runs/*/_COMPLETE`가 없는) 과제. 키는 `sonar_key` → `suts_dir/<sut>/sut.yaml`의 `sonar.projectKey` → 저장소 이름(슬래시 뒤). 대상이 아니면 `sources.sonar`는 `skipped`.
  - 결론값 분류와 검사 규칙은 설계 §6.3의 표.
  - 모든 `gh` 호출은 `[gh, "api", "-i", path]`로 해서 상태 줄과 헤더를 같이 읽는다. 시작할 때 `deadline = time.monotonic() + budget`을 하나 정하고, 호출마다 `timeout = min(READ_TIMEOUT_SEC, 남은 시간)`, 재시도 대기와 `Retry-After` 대기는 남은 시간 안에서만 한다. `Retry-After`가 남은 시간보다 길면 기다리지 않는다. 시간 초과한 자식은 죽이고 `wait`한다.
  - 쓰기는 임시 파일 뒤 `os.replace`. 외부 문자열은 `redact.redact_text`를 지난다. `date`는 `now`의 UTC `YYYYMMDD`.
- [ ] **Step 4: `collect.sh`를 쓴다.**
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_collect.py -v` 전부 PASS. 끝난 뒤 가짜 Sonar·가짜 gh 프로세스가 남아 있지 않다.
- [ ] **Step 6: 커밋** — `feat(collect): GitHub CI and SonarQube snapshots with per-collect token`

### Task 7: 새 디자인 자산, 공통 틀, 외부 리포트의 띠, run 페이지

**REQ-IDs:** REQ-124, REQ-126, REQ-127, REQ-136, REQ-137

**Files:**
- Create: `tests/fixtures/legacy-run-page/{index.html,EXPECTED.json}`, `site-gen/td/site/static/v2/app.css`, `site-gen/td/site/static/v2/app.js`, `site-gen/td/site/nav.py`, `site-gen/td/site/templates/base_v2.html.j2`
- Modify: `site-gen/td/site/templates/run.html.j2`, `site-gen/td/site/pages.py`, `site-gen/td/site/layout.py`, `site-gen/td/site/index.py`(v2 자산 복사), `site-gen/td/publish.py`(`render`가 띠 누락을 읽음), `tests/acceptance/dashboard_fixtures.py`, `tests/acceptance/test_site.py`(run 페이지 선택자)
- Test: `tests/acceptance/test_dashboard_nav.py`, `tests/acceptance/test_dashboard_common.py`

**Interfaces:**
- Consumes: Task 3(공용 테스트 기반), Task 4(표본 리포트).
- Produces:
  - `nav.STAGE_LABELS: dict[str, str]` — `S00` 준비, `S01` 기존 블랙박스 테스트, `S02` bbtg 정적 분석, `S03` jQA 온톨로지, `S04` 온톨로지 시각화, `S05` OWL 온톨로지, `S06` BDD 시나리오 생성, `S07` 생성 E2E 실행, `S08` 커버리지 집계, `S09` hotspot 분석, `S10` 변경 영향 분석(TIA), `S11` SonarQube, `S12` 방식 비교, `S13` 게시.
  - `nav.links_for(report_rel: str | None, reports: list[dict]) -> dict` — run 디렉터리 기준 `report_rel`(run 페이지면 `None`)에서 본 상대 링크: `home`, `sut`(`suts/<sut>/index.html`에 해당), `run`, `reports`(`[{label, href, current}]`).
  - `nav.render(links: dict, current_label: str) -> str` — `<nav class="tdnav" aria-label="리포트 이동">…</nav>` 한 덩어리. 안에 `<style>` 하나, `<script>` 없음, 높이 40px, `position: static`. 클래스는 모두 `tdnav-` 접두.
  - `nav.inject(html_path: Path, nav_html: str) -> bool` — 처음 나오는 `<body[^>]*>`(대소문자 무시) 바로 뒤에 넣는다. 없으면 파일을 그대로 두고 `False`.
  - `layout.NAV_INJECT: dict[str, list[str]]` — 띠를 주입할 파일: `"hotspot/": ["hotspots.html", "api_report.html"]`, `"tia/": ["tia.html"]`, `"cucumber/*/": ["index.html"]`, `"ontology/": ["jqa.html", "owl.html"]`. 그 밖의 자체 리포트(커버리지, Sonar, 방식 비교)는 Task 8에서 템플릿이 띠를 그린다.
  - `pages.render_run(run_dir, out_dir) -> Path` — 서명은 그대로. 순서: 복사 → RERENDER → 띠 주입 → run 페이지 렌더 → `sanitize_site`. `out_dir/render.json`에 `{"navMissing": [{"report": <label>, "file": <rel>, "reason": "<body>를 찾지 못했다"}]}`를 쓴다(없으면 빈 배열). `publish.EXCLUDED_SITE_FILES`에 `render.json`을 더해 게시하지 않는다. `Publication.render`가 이 파일을 읽어 `self.render_warnings`에 담고, 비어 있지 않으면 `log_phase`가 내는 최종 상태를 적어도 `degraded`로 하고 사유에 `"공통 띠 없음: <file>"`을 넣는다.
  - 템플릿 `base_v2.html.j2` 블록: `title`, `crumbs`, `content`, `scripts`. 변수: `static_href`(끝이 `/`인 `…/static/v2/`), `nav_html`(문자열 또는 없음).
  - DOM 계약(run 페이지): `nav.tdnav`, `#stage-strip button[data-stage]`(14개, `aria-pressed`), `#stage-detail`, `.report-card[data-report]`, `.report-card .nav-missing`, `#publish-result[data-url]`(기존 동작 유지).
  - `app.js`는 페이지에 있는 요소만 보고 동작한다: `#stage-strip`, `#publish-result`, (Task 9) `#projects`, (Task 10) `#tabs`·`.trend`. 시작할 때 `document.documentElement.classList.add("js")`.
  - CSS 변수와 값은 시안 `home.html`의 `:root` 블록 그대로. 상태 표시 클래스 `.st.s-crit|s-warn|s-good|s-none`.
  - `dashboard_fixtures.make_local_run_with_reports(tmp_path, *, sut="pet", tia_html: str | None = None, hotspot_html: str | None = None, with_own_reports: bool = True, gens: tuple[str, ...] = ("base-r1",)) -> Path` — `helpers.make_local_run`으로 만든 run에 `tests/fixtures/reports/`의 표본(hotspot, tia), 최소 Cucumber `index.html`, 그리고 `with_own_reports`면 실제 렌더 함수로 만든 Sonar·방식 비교·온톨로지 산출물을 더하고, 14단계의 단계 JSON에 시작·종료 시각을 넣는다(S07은 259초). `dashboard_fixtures.render_site(tmp_path, run_dir, *, config: dict | None = None) -> Path` — run을 사이트 디렉터리의 `suts/<sut>/runs/<runId>/`로 렌더하고 재생성한다. `RUN_PATH`는 그 run의 사이트 상대 경로.

- [ ] **Step 1: 옛 run 페이지 픽스처를 먼저 고정한다(템플릿을 고치기 전).** 지금 템플릿으로 `pages.render_run(helpers.make_local_run(…))`을 돌려 나온 `index.html`을 `tests/fixtures/legacy-run-page/index.html`로 둔다. 그 페이지를 지금의 `site.css`로 열어 `th`의 계산된 `background-color`와 `body`의 `font-size`를 읽어 `EXPECTED.json`에 적는다. 이 단계만 먼저 커밋한다 — `test: freeze a legacy run page fixture before the template change`.
- [ ] **Step 2: 실패하는 테스트를 쓴다**

```python
def test_req124_run_page(tmp_path, browser):
    with serve(render_site(tmp_path, make_local_run_with_reports(tmp_path))) as url:
        page = open_page(browser, url + RUN_PATH)
        assert page.locator("#stage-strip button[data-stage]").count() == 14
        page.click('#stage-strip button[data-stage="S07"]')
        detail = page.inner_text("#stage-detail")
        assert all(t in detail for t in ("S07", "생성 E2E 실행", "passed", "4분 19초"))
        hrefs = [c.get_attribute("href") for c in page.locator(".report-card a").all()]
        assert len(hrefs) >= 6 and all(http_status(urljoin(page.url, h)) == 200 for h in hrefs)
        assert page.locator("#publish-result").count() == 1

def test_req126_external_reports_still_work(tmp_path, browser):
    run_dir = make_local_run_with_reports(tmp_path); originals = snapshot_bytes(run_dir, ["S09", "S10"])
    with serve(render_site(tmp_path, run_dir)) as url:
        page = browser.new_page(); errors = []; page.on("pageerror", errors.append)
        page.goto(url + RUN_PATH + "hotspot/hotspots.html")
        assert page.locator("nav.tdnav").count() == 1 and page.locator("nav.tdnav script").count() == 0
        assert page.locator("#hm-map circle").count() >= 1
        before = page.inner_text("#hm-side"); page.locator("#hm-map circle").first.click(); assert page.inner_text("#hm-side") != before
        page.goto(url + RUN_PATH + "tia/tia.html")
        before = page.inner_text("main"); page.locator("#seg [role=tab]").nth(1).click(); assert page.inner_text("main") != before
        for rel in ("hotspot/api_report.html", "cucumber/base-r1/index.html"):
            page.goto(url + RUN_PATH + rel); assert page.locator("nav.tdnav").count() == 1
        assert errors == []
    assert snapshot_bytes(run_dir, ["S09", "S10"]) == originals

def test_req127_no_body_degraded(tmp_path):
    run_dir = make_local_run_with_reports(tmp_path, tia_html="<html><p>no body tag</p></html>", hotspot_html='<HTML><BODY class="x"><p>hi</p></BODY></HTML>')
    out = pages.render_run(run_dir, tmp_path / "out").parent
    assert (out / "tia/tia.html").read_text() == "<html><p>no body tag</p></html>"
    assert re.search(r'<BODY class="x"><nav class="tdnav"', (out / "hotspot/hotspots.html").read_text())
    assert [m["file"] for m in json.loads((out / "render.json").read_text())["navMissing"]] == ["tia/tia.html"]
    assert "공통 띠 없음" in (out / "index.html").read_text()
    result = run_fake_publication(run_dir)                 # test_unit_publish.py가 쓰는 helpers.FakeS3 경로로 Publication.execute
    assert result["status"] == "degraded" and "tia/tia.html" in result["reason"]

def test_req136_legacy_assets_unchanged(tmp_path, browser):          # test_dashboard_common.py
    site = make_site(tmp_path, runs={"pet": [RUN_A]}); rebuild_site(site, dashboard_config.empty())
    assert sha256(site / "static/site.css") == "27166871ff7312b677dd65cb0b96baee7499f1b38cbb92cd4b8f2befcf42710f"
    assert sha256(site / "static/site.js") == "8bd8e8f766db637afb9c3962982b7e21fdd5a9d746e7f7251d7d0582ce63e07e"
    legacy = site / "suts/pet/runs/legacy/index.html"; legacy.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "legacy-run-page/index.html", legacy); expected = json.loads((FIXTURES / "legacy-run-page/EXPECTED.json").read_text())
    with serve(site) as url:
        page = open_page(browser, url + "suts/pet/runs/legacy/index.html")
        assert computed(page, "th", "background-color") == expected["thBackground"] and computed(page, "body", "font-size") == expected["bodyFontSize"]

def test_req137_v2_asset_paths(tmp_path):
    out = pages.render_run(make_local_run_with_reports(tmp_path), tmp_path / "out").parent
    html = (out / "index.html").read_text()
    assert "static/v2/app.css" in html and "static/v2/app.js" in html and "static/site.css" not in html
    site = make_site(tmp_path / "s", runs={"pet": [RUN_A]}); rebuild_site(site, dashboard_config.empty())
    assert (site / "static/v2/app.css").is_file() and (site / "_test/static/v2/app.css").is_file()
```

- [ ] **Step 3: 실패를 확인한다** → `ModuleNotFoundError: td.site.nav`
- [ ] **Step 4: `app.css`, `app.js`, `base_v2.html.j2`, `nav.py`를 쓰고 `run.html.j2`와 `render_run`을 옮긴다.** `index.rebuild`는 `static/v2/`를 `base/static/v2/`와 `_test/static/v2/`에 복사하고 `site.css`·`site.js`도 지금처럼 복사한다. 이 Task에서 커버리지·Sonar·방식 비교 페이지는 아직 옛 틀이다.
- [ ] **Step 5: 통과를 확인한다** — 5개 PASS. `pytest tests/acceptance/test_site.py tests/acceptance/test_unit_publish.py -v`에서 run 페이지의 링크·단계 표 선택자가 바뀌어 깨진 단언만 새 DOM 계약에 맞게 고친다(요구사항명세 §3의 REQ-035, 049 줄의 범위).
- [ ] **Step 6: 커밋** — `feat(site): v2 assets, shared frame, nav strip for external reports, run page`

### Task 8: 직접 만드는 리포트를 새 틀로

**REQ-IDs:** REQ-128 (PoC REQ-037, 040, 051, 067, 073의 자산 경로 개정)

**Files:**
- Modify: `site-gen/td/coverage.py`, `sonar.py`, `compare.py`, `ontology_html.py`, `hosting.py`, `site-gen/td/site/layout.py`(`RERENDER`, `COPY_IGNORE`), `site-gen/td/site/pages.py`, `site-gen/td/site/templates/{coverage,sonar,compare,ontology,hosting,test_index}.html.j2`, `site-gen/td/site/static/v2/app.css`, `tests/acceptance/test_compare.py`, `test_unit_hosting.py`, `test_unit_sonar.py`
- Test: `tests/acceptance/test_dashboard_nav.py`

**Interfaces:**
- Consumes: Task 7의 `base_v2.html.j2`, `nav.links_for`, `nav.render`.
- Produces:
  - 렌더 함수의 `css_href` 키워드 인자는 이름을 유지한다. 뜻은 "불러올 스타일 파일의 주소"이고 게시 때는 `…/static/v2/app.css`가 넘어온다. 선택 인자 `nav_html: str | None = None`을 더한다.
  - 단독 열람용으로 리포트 옆에 복사하던 스타일은 `app.css`를 `app.css`라는 이름으로 복사한다(`copy_css=True`일 때). `COPY_IGNORE`의 `site.css`는 `app.css`로 바꾼다.
  - `layout.RERENDER`의 함수 서명은 `fn(target: Path, css_href: str, nav_html: str)`.
  - 온톨로지는 지금처럼 스타일을 인라인으로 넣되 `static/v2/app.css`의 내용을 읽는다. 띠는 Task 7의 주입으로 들어간다.
  - 기존 화면의 요소 id와 스크립트(`ontology.js`, 커버리지 히트맵·소스 뷰어)는 그대로다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
def test_req128_own_reports_new_frame(tmp_path):
    out = pages.render_run(make_local_run_with_reports(tmp_path), tmp_path / "out").parent
    for rel in ("coverage/coverage.html", "sonar/sonar.html", "compare/compare.html"):
        html = (out / rel).read_text()
        assert "static/v2/app.css" in html and "static/site.css" not in html and html.count('<nav class="tdnav"') == 1
    for rel in ("ontology/jqa.html", "ontology/owl.html"):
        html = (out / rel).read_text()
        assert "--surface" in html and "static/site.css" not in html and html.count('<nav class="tdnav"') == 1
    hosting_html = render_hosting(tmp_path)           # hosting.render_html의 기본 인자로
    assert 'href="static/v2/app.css"' in hosting_html
```

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: 템플릿을 `base_v2.html.j2` 상속으로 옮기고 렌더 함수와 `RERENDER`를 고친다.** 히트맵·소스 뷰어·그래프의 전용 규칙은 `app.css`의 끝에 옮긴다(선택자 이름 유지).
- [ ] **Step 4: 요구사항명세 §3대로 자산 경로 단언만 고친다.** `test_compare.py::test_req040_s12_stage_site_and_run_json`의 `"static/site.css" in html` → `static/v2/app.css`, `test_req067_*`가 토큰을 읽는 파일 → `static/v2/app.css`, `test_unit_hosting.py`의 `href="static/site.css"` → `href="static/v2/app.css"`, `test_unit_sonar.py`의 `(tmp_path / "site.css").is_file()` → `app.css`. 다른 기대값은 건드리지 않는다.
- [ ] **Step 5: 통과를 확인한다** — 새 테스트 PASS, 그리고 `pytest tests/acceptance/test_coverage.py tests/acceptance/test_ontology.py tests/acceptance/test_compare.py tests/acceptance/test_unit_sonar.py tests/acceptance/test_unit_hosting.py -v` PASS(REQ-016, 017, 033, 034 포함)
- [ ] **Step 6: 커밋** — `feat(site): move own reports onto the v2 frame`

### Task 9: 첫 화면

**REQ-IDs:** REQ-089(화면), REQ-090(화면), REQ-104, REQ-109, REQ-110, REQ-111, REQ-112, REQ-113, REQ-114, REQ-142

**Files:**
- Modify: `site-gen/td/site/index.py`, `site-gen/td/dashboard_config.py`(`cell_text`), `site-gen/td/site/templates/home.html.j2`, `site-gen/td/site/static/v2/app.js`, `app.css`, `tests/acceptance/dashboard_fixtures.py`
- Test: `tests/acceptance/test_dashboard_home.py`

**Interfaces:**
- Consumes: Task 1~3, Task 7의 틀.
- Produces:
  - `dashboard_config.cell_text(column: str, project: dict) -> tuple[str, str]` — 칸의 글자와 설명(title). 규칙: 값이 있으면 `format_value`. `sonar.gate` 칸에서 `sources.sonar == "absent"`면 "연결 없음". 그 출처가 `failed`면 "측정 없음"이고 설명에 사유. 그 밖에 값이 없으면 "—".
  - `rebuild`가 `projects.json`과 새 홈을 쓴다.
  - `projects.json`: `{"schema": 1, "projects": [{"name", "repo", "sut", "pipeline", "implicit", "status": {"level", "label", "reasons", "partial"}, "values": {...}, "headline", "href": "projects/<name>/index.html", "stale": …, "problems": [...]}], "summary": {<집계 지표>: {"label", "value", "detail"}}, "rules": [...]}`.
  - DOM 계약(홈): `#headline`, `#summary .sum-item[data-metric]`(안에 `b`), `button[data-filter]`(`aria-pressed`, 안에 `.count`), `input#proj-search`, `table#projects`, `th button[data-sort]`, `tbody tr.proj[data-name][data-status][tabindex=0][aria-expanded]`, 그 안 `a.proj-link`, `.st`, `.caret`, `.tag-pipeline`, `.tag-partial`, `.tag-stale`, `td[data-col][data-sort-value]`, `.hist i`(실패는 `i.f`), 펼친 행 `tr.proj-detail`(안에 `.detail-reasons`, `.detail-kpi[data-metric]`, `a.open-project`), `#rules li`, `#rules .zero-note`, `footer a[href$="_test/index.html"]`, `a[href$="hosting.html"]`, 과제 0개일 때 `#empty`.
  - 페이지 안 데이터: `<script type="application/json" id="projects-data">`(`pages.json_for_script`). 내용은 `projects.json`과 같다.
  - `dashboard_fixtures.home_site(tmp_path) -> Path` — 과제 6개:

| 이름 | 구성 | 상태 |
|---|---|---|
| `a-crit` | CI 9/9, Sonar 게이트 `ERROR`, 취약점 2 | 위험 |
| `b-crit` | CI 최근 실패(4회 중 3회 성공), Sonar 게이트 `OK` | 위험 |
| `zero-cov` | CI 17/17, 게이트 `OK`, 커버리지 0.0, 취약점 8 | 주의 |
| `no-data` | `repo`는 있고 CI 0회, Sonar 없음(`absent`) | 측정 없음 |
| `no-sonar` | CI 10/10, Sonar 없음(`absent`) | 양호, 부분 측정 |
| `pet` | `repo` 없이 `sut: pet`, run 2개(게이트 `OK`, 통과율 1.0, 귀속 0.4152, hotspot 1위 `Owner.getPet`) | 양호, 파이프라인 |

    `dashboard_fixtures.sonar_failed_site(tmp_path)` — `sources.sonar == "failed"`인 과제 `flaky`와 CI가 없는(`none`) Sonar만 있는 과제 `no-ci`.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `home` fixture는 `serve(home_site(tmp_path))`의 URL이다. 대표:

```python
def test_req109_rows_order_headline(home, browser, tmp_path):
    page = open_page(browser, home)
    assert [r.get_attribute("data-name") for r in page.locator("tr.proj").all()] == ["a-crit", "b-crit", "zero-cov", "no-data", "no-sonar", "pet"]
    assert page.inner_text("#headline") == "과제 6개 중 2개가 위험, 1개가 주의입니다"
    with serve(all_good_site(tmp_path)) as good:
        assert open_page(browser, good).inner_text("#headline") == "과제 2개 중 문제 있는 과제가 없습니다"

def test_req111_inline_expand(home, browser):
    page = open_page(browser, home); row = page.locator('tr.proj[data-name="b-crit"]'); row.click()
    assert row.get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.querySelector('tr.proj[data-name=\"b-crit\"]').nextElementSibling.className") == "proj-detail"
    assert "기본 브랜치의 최근 CI 실패" in page.inner_text("tr.proj-detail .detail-reasons")
    assert page.locator("tr.proj-detail a.open-project").get_attribute("href") == "projects/b-crit/index.html"
    page.locator('tr.proj[data-name="pet"]').click()
    assert page.locator("tr.proj-detail").count() == 1 and row.get_attribute("aria-expanded") == "false"
    kpi = lambda m: page.inner_text(f'tr.proj-detail .detail-kpi[data-metric="{m}"]')
    assert "100.0%" in kpi("tests.passRate") and "41.5%" in kpi("coverage.line") and "통과" in kpi("sonar.gate") and "Owner.getPet" in kpi("hotspot.topName")
    page.locator('tr.proj[data-name="pet"]').click(); assert page.locator("tr.proj-detail").count() == 0
    row.focus(); page.keyboard.press("Enter"); assert page.locator("tr.proj-detail").count() == 1

def test_req113_missing_not_zero(home, browser, tmp_path):
    page = open_page(browser, home)
    cell = lambda p, name, col: p.inner_text(f'tr.proj[data-name="{name}"] td[data-col="{col}"]').strip()
    assert cell(page, "no-sonar", "sonar.gate") == "연결 없음" and cell(page, "no-sonar", "sonar.coverage") == "—"
    assert cell(page, "zero-cov", "sonar.coverage") == "0.0%"
    with serve(sonar_failed_site(tmp_path)) as url:
        other = open_page(browser, url)
        assert cell(other, "no-ci", "ci.successRate") == "—" and cell(other, "flaky", "sonar.gate") == "측정 없음"

def test_req089_excluded_project_absent_from_site(tmp_path):
    site = make_site(tmp_path, snapshots={"a": [snap()], "secret": [snap(description="internal thing")]}, config=cfg_with(plain=["a", "secret"]))
    index.rebuild(site, "", load_cfg(site), exclude=frozenset({"secret"}))
    blob = "".join(p.read_text(errors="ignore") for p in site.rglob("*") if p.is_file() and "projects/secret/" not in p.as_posix())
    assert "secret" not in blob and "internal thing" not in blob and '"a"' in (site / "projects.json").read_text()

def test_req142_summary_counts_history(home, browser):
    page = open_page(browser, home); data = json.loads(urlopen(home + "projects.json").read())
    items = page.locator("#summary .sum-item").all()
    assert [i.get_attribute("data-metric") for i in items] == list(load_cfg_from(home)["home"]["summary"])
    assert [i.locator("b").inner_text() for i in items] == [data["summary"][i.get_attribute("data-metric")]["value"] for i in items]
    for level in ("crit", "warn", "good", "none"):
        assert int(page.inner_text(f'button[data-filter="{level}"] .count')) == page.locator(f'tr.proj[data-status="{level}"]').count()
    assert page.locator('tr.proj[data-name="b-crit"] .hist i').count() == 4 and page.locator('tr.proj[data-name="b-crit"] .hist i.f').count() == 1

# 검토 초점 1, 3
def test_special_characters_are_escaped(tmp_path, browser):
    site = make_site(tmp_path, snapshots={"x": [snap(description='<img src=x onerror=alert(1)> & "q"')]}, config=cfg_with(plain="x"))
    rebuild_site(site)
    with serve(site) as url:
        page = open_page(browser, url)
        assert page.locator("tr.proj img").count() == 0 and "<img src=x" in page.inner_text('tr.proj[data-name="x"]')
        assert json.loads(page.inner_text("#projects-data"))["projects"][0]["name"] == "x"

def test_empty_site_home(tmp_path, browser):
    site = make_site(tmp_path); rebuild_site(site, dashboard_config.empty())
    with serve(site) as url:
        page = open_page(browser, url)
        assert page.inner_text("#empty") == "등록된 과제가 없습니다" and page.locator("tr.proj").count() == 0
```

  090(화면: `flaky`의 Sonar 칸이 "측정 없음"이고 `title`에 사유), 104(홈의 `data-status`와 `.detail-reasons`가 `projects.json`과 같고 `pet`의 `values`에 네 지표가 있다), 110(거르기·검색·정렬, 값 없는 행은 항상 뒤), 112(`javascript=False`에서 6줄과 `a.proj-link`), 114(표시가 `pet`·`no-sonar`에만, `#rules`의 주의 줄 문자열, `.zero-note`가 `home_site`에는 있고 `all_good_site`에는 없다, 하단 링크 둘)도 쓴다.

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: `rebuild`를 넓히고 `home.html.j2`를 쓴다.** 표는 서버가 정렬된 순서로 다 그린다. 결론 문장: 위험·주의가 있으면 `"과제 N개 중 X개가 위험, Y개가 주의입니다"`(0인 쪽은 뺀다), 없으면 `"과제 N개 중 문제 있는 과제가 없습니다"`. 상세 행의 내용은 서버가 `<template data-detail-for="<name>">`으로 넣어 두고 `app.js`가 옮겨 붙인다. `stale`이 있으면 `.tag-stale`에 "수집 실패 · <날짜>"를 쓴다.
- [ ] **Step 4: `app.js`의 홈 동작을 쓴다.** 정렬은 `td[data-sort-value]`로 한다. 값이 없는 칸은 `data-sort-value=""`이고 방향과 무관하게 뒤다.
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_home.py -v`
- [ ] **Step 6: 커밋** — `feat(site): project list home with verdicts, filters and inline detail`

### Task 10: 과제 페이지와 SUT 안내 페이지

**REQ-IDs:** REQ-080, REQ-083, REQ-084(화면), REQ-108, REQ-115, REQ-116, REQ-117, REQ-118, REQ-119, REQ-120, REQ-121, REQ-123

**Files:**
- Create: `site-gen/td/site/templates/project.html.j2`, `site-gen/td/site/templates/tabs/{overview,trend,tests,coverage,hotspot,quality,generation,runs}.html.j2`
- Modify: `site-gen/td/site/index.py`, `site-gen/td/site/metrics.py`, `site-gen/td/site/templates/sut.html.j2`, `site-gen/td/site/static/v2/app.js`, `app.css`, `tests/acceptance/dashboard_fixtures.py`
- Test: `tests/acceptance/test_dashboard_project.py`, `tests/acceptance/test_dashboard_status.py`

**Interfaces:**
- Consumes: Task 3(`series`, `trend_svg`), Task 7(`make_local_run_with_reports`, `render_site`), Task 9(`rebuild`).
- Produces:
  - `metrics.tab_data(project: dict, base: Path, cfg: Config) -> dict[str, dict | None]` — 탭 식별자 → 템플릿 데이터, 데이터가 없는 탭은 `None`. 미러의 최신 완료 run 디렉터리에서 읽는다.
    - `overview`: `values`, S09 `top10` 앞 5개, S10 `impact`(`selected`, `indexedTests`), 단계별 `{id, label, status, sec}`, 리포트 링크. 파이프라인이 없는 과제는 스냅숏의 CI·Sonar 값과 `ciHistory`.
    - `tests`: `run.json` `kpis.tests`, S07 `generations`(`arm`, `scenarios`, `statusCounts`).
    - `coverage`: `run.json` `kpis`의 묶음별 `line`·`branch`·`aggregate.line`, `coverage/coverage.json`의 `tcCount`·`attributedCount`.
    - `hotspot`: S09 `top10`.
    - `quality`: `sonar/sonar.json`의 `qualityGate`, `measures`(등급은 1~5를 A~E로), `issues.items`의 종류 × 심각도 개수, `dashboardUrl`. 파이프라인이 없는 과제는 스냅숏의 `sonar`(이슈 표 없음).
    - `generation`: `compare/compare.json`의 `verdict.generation`·`verdict.effect`·기준값, 방식별 `metrics.<이름>.mean`(`scenarios, compile, passed, endpoint, line, tokens, seconds`).
    - `runs`: `runs`.
  - `rebuild`가 과제마다 `projects/<name>/index.html`, `projects/<name>/series.json`을 쓰고, `suts/<sut>/index.html`을 안내 페이지로 쓴다(`<meta http-equiv="refresh" content="0; url=../../projects/<name>/index.html">`과 같은 주소의 `a#to-project`).
  - 보이는 탭 = `cfg.project["tabs"]` 가운데 `tab_data`가 `None`이 아닌 것. 파이프라인 없는 과제는 `overview`, `trend`, `quality`만.
  - DOM 계약: `#headline`, `.st`, `[role=tablist]#tabs`, `button[role=tab]#tab-<id>[data-tab][aria-controls="panel-<id>"][aria-selected][tabindex]`, `section[role=tabpanel]#panel-<id>[aria-labelledby="tab-<id>"]`, 구역마다 `.tab-guide` 하나, `figure.trend[data-metric]` 안 `svg`와 `.pt`, 툴팁 `#trend-tip`, 강조 클래스 `.pt.hl`, `table#trend-table`(`tr[data-id]`, `td[data-metric]`), KPI 칸 `.kpi[data-metric] b`, `ol.hot li`, `.impact[data-selected][data-indexed]`, `#stage-strip`과 `#stage-detail`(run 페이지와 같은 계약), `table#gens tr[data-gen]`, `table#issues td[data-type][data-sev]`, `table#arms tr[data-arm]`, `table#runs tr[data-run]`, 리포트 링크 `a.report-link[data-report]`.
  - CSS는 `.js [role=tabpanel][hidden]`만 숨긴다.
  - `dashboard_fixtures.proj_site(tmp_path) -> Path` — 과제 셋: `pet`(`repo` 없이 `sut: pet`. run 5개이고 3번째 run은 `tests.passRate`가 없다. 최신 run은 `make_local_run_with_reports`로 만들어 `render_site`로 렌더한 것이라 run 페이지와 리포트가 실제로 있다), `plain`(스냅숏 2일치: CI 18/20, 게이트 `OK`, 커버리지 91.6, 취약점 0, 버그 0), `many`(`sut: many`, run 31개). `proj` fixture는 `serve(proj_site(tmp_path))`의 URL.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** 대표:

```python
def test_req115_tabs_hash_keyboard(proj, browser):
    page = open_page(browser, proj + "projects/pet/index.html")
    assert page.locator("#tabs").get_attribute("role") == "tablist"
    page.click('button[role=tab][data-tab="coverage"]')
    assert page.locator('[role=tabpanel]:visible').get_attribute("id") == "panel-coverage" and page.url.endswith("#coverage")
    assert page.locator('button[role=tab][aria-selected="true"]').count() == 1
    assert [t.get_attribute("tabindex") for t in page.locator("button[role=tab]").all()].count("0") == 1
    assert page.locator("#panel-coverage").get_attribute("aria-labelledby") == "tab-coverage"
    page2 = open_page(browser, proj + "projects/pet/index.html#quality")
    assert page2.locator('[role=tabpanel]:visible').get_attribute("id") == "panel-quality"
    tab = lambda: page2.locator('button[role=tab][aria-selected="true"]').get_attribute("data-tab")
    page2.locator("#tab-quality").focus(); page2.keyboard.press("ArrowRight"); assert tab() == "generation"
    page2.keyboard.press("ArrowLeft"); page2.keyboard.press("ArrowLeft"); assert tab() == "hotspot"
    page2.locator("#tab-overview").focus(); page2.keyboard.press("ArrowLeft"); assert tab() == "runs"

def test_req120_trend_points_gaps_cap(proj, browser):
    page = open_page(browser, proj + "projects/pet/index.html#trend")
    fig = page.locator('figure.trend[data-metric="tests.passRate"]')
    assert fig.locator(".pt").count() == 4 and fig.locator("polyline.ln").count() == 2
    many = open_page(browser, proj + "projects/many/index.html#trend")
    assert many.locator('figure.trend[data-metric="coverage.line"] .pt').count() == 30 and many.locator("#trend-table tbody tr").count() == 31

def test_req119_snapshot_only_project(proj, browser):
    page = open_page(browser, proj + "projects/plain/index.html")
    assert [t.get_attribute("data-tab") for t in page.locator("button[role=tab]").all()] == ["overview", "trend", "quality"]
    kpi = lambda m: page.inner_text(f'#panel-overview .kpi[data-metric="{m}"] b')
    assert (kpi("ci.successRate"), kpi("sonar.gate"), kpi("sonar.coverage"), kpi("sonar.vulnerabilities"), kpi("sonar.bugs")) == ("90.0%", "통과", "91.6%", "0", "0")

def test_req083_threshold_change_changes_verdict(tmp_path):          # test_dashboard_status.py
    site = make_site(tmp_path, snapshots={"p": [snap(ci_runs=25, ci_successes=23, sonar={"gate": "OK", "vulnerabilities": 0})]}, config=cfg_with(plain="p"))
    rebuild_site(site); assert status_of(site, "p") == "good"
    rebuild_site(site, set_threshold(load_cfg(site), "ci.successRate", 0.95))
    warn_line = next(l for l in json.loads((site / "projects.json").read_text())["rules"] if l.startswith("주의"))
    assert status_of(site, "p") == "warn" and "95.0%" in warn_line and "90.0%" not in warn_line and warn_line in (site / "index.html").read_text()

def test_req084_headline_rendered(proj, browser):
    assert open_page(browser, proj + "projects/pet/index.html").inner_text("#headline") == "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 41.5%입니다"

# 검토 초점 5
def test_unknown_hash_opens_first_tab(proj, browser):
    assert open_page(browser, proj + "projects/pet/index.html#nope").locator('[role=tabpanel]:visible').get_attribute("id") == "panel-overview"
```

  080(요구사항명세의 여섯 경우를 각각 다른 설정으로 `proj_site`를 다시 만들어 확인), 108(`a#to-project`의 href가 200이고 `meta refresh`의 주소와 같다. 설정 과제와 암묵 과제 둘 다), 116(`javascript=False`에서 `section[role=tabpanel]`이 설정 순서로 모두 보인다), 117(구역마다 `.tab-guide` 하나), 118(요구사항명세의 값 전부와 `a.report-link` 200, 단계 띠 14칸과 누른 단계의 이름·시간), 121(점에 `focus()` 뒤 `#trend-tip`에 runId와 값, 다른 차트의 같은 `data-id` 점에 `.hl`, run 점 href 200, 스냅숏 점은 `a`가 아니고 툴팁에 날짜), 123(`#trend-table`의 칸이 `series.json`과 같고 없는 값은 "—")도 쓴다.

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: `proj_site`, `tab_data`, 템플릿, `rebuild`의 과제 페이지 쓰기를 넣는다.** 탭 안 배치와 "이 탭 읽는 법" 문구는 시안 `project.html`의 것을 그대로 쓴다. "추이" 탭의 읽는 법: "지표 하나에 차트 하나입니다. 점 하나가 실행 한 번이고, 값이 없는 실행에서는 선이 끊깁니다. 점을 누르면 그 실행으로 갑니다."(스냅숏 과제는 "점 하나가 하루치 수집이고, 값이 없는 날에는 선이 끊깁니다."로 끝낸다).
- [ ] **Step 4: `app.js`의 탭·추이 동작을 쓴다.** 탭: 클릭, 좌우 방향키(끝에서 돈다), Home/End, `history.replaceState`로 `#`. 추이: `.pt`의 `focus`/`mouseenter`에 툴팁과 `data-id`가 같은 점 강조.
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_project.py tests/acceptance/test_dashboard_status.py -v`
- [ ] **Step 6: 커밋** — `feat(site): project page with tabs, trends and SUT landing`

### Task 11: 게시 (인덱스 단계에 수집, 인덱스 전용 게시, 과제 삭제)

**REQ-IDs:** REQ-079, REQ-098, REQ-099, REQ-100, REQ-101, REQ-106, REQ-107, REQ-125, REQ-144, REQ-145

**Files:**
- Create: `pipeline/publish-index.sh`
- Modify: `site-gen/td/publish.py`, `pipeline/S13-publish.sh`(머리 주석), `tests/acceptance/helpers.py`(`FakeS3.delete_objects`), `tests/acceptance/dashboard_fixtures.py`
- Test: `tests/acceptance/test_dashboard_publish.py`, `tests/acceptance/test_dashboard_index.py`, `tests/acceptance/test_unit_publish.py`

**Interfaces:**
- Consumes: Task 6(`collect.sh`의 표준 출력 JSON), Task 9·10(`rebuild`).
- Produces:
  - `publish.delete_prefix(s3, bucket: str, key_prefix: str) -> int` — 그 접두의 객체를 나열해 묶어 지우고 지운 수를 돌려준다. `key_prefix`가 `(<접두>)projects/<이름>/` 꼴이 아니면 `PublishError`.
  - `publish.run_collect(env: dict, cfg: Config, site_dir: Path) -> dict` — `cfg`에 `repo`가 있는 과제가 없으면 실행하지 않고 `{"status": "ok", "reasons": [], "written": [], "excluded": [], "unverified": []}`. 있으면 `pipeline/collect.sh`를 `subprocess.Popen`으로 띄워 기다린다. 기다리는 동안 `PublishInterrupted`가 나면 자식에 SIGTERM을 보내고 60초까지 기다린 뒤(넘으면 SIGKILL) 예외를 다시 올린다. 자식이 0이 아닌 코드로 끝났거나 표준 출력이 JSON이 아니면 `{"status": "degraded", "reasons": ["수집 실행 실패"], …}`.
  - `publish.publish_index(s3, bucket, mirror: Path, prefix: str, env: dict) -> IndexOutcome` — 순서:
    1. `sync_mirror`
    2. `cfg = resolve(env, root)`, `run_collect(env, cfg, mirror/prefix)`
    3. 지울 과제를 정한다: 수집 결과의 `excluded` + `mirror/<prefix>projects/` 바로 아래에서 `with_implicit` 뒤의 과제 이름이 아닌 디렉터리. 그 미러 디렉터리를 `shutil.rmtree`한다.
    4. `index.rebuild(mirror, prefix, cfg, exclude=frozenset(excluded))`
    5. 지울 과제마다 `delete_prefix`
    6. `upload_files(rebuild 목록 + 수집의 written)`
    
    `@dataclass class IndexOutcome: written: list[Path]; collect_status: str; collect_reasons: list[str]; deleted: list[str]`. `deleted`의 이름은 로그에 쓰지 않는다.
  - `Publication.index_phase`가 `publish_index`를 쓰고 결과를 `self.index_outcome`에 둔다. `collect_status`가 `degraded`면 `self.hosts["collect"] = {"status": "failed", "reason": " · ".join(collect_reasons)}`로 기록하고 `overall_status`가 이를 `degraded`로 센다(S3 실패만 `failed`).
  - `Publication.lightsail_phase`가 rsync 전에 `self.index_outcome.deleted`마다 `ssh_output(… "rm -rf -- /srv/dashboard/<prefix>projects/<name>")`을 실행한다(이름은 설정 검증의 문법을 지난 것만). `ssh_target`이 없거나 실패하면 지금의 Lightsail 실패와 같이 `hosts["lightsail"]`에 기록하고 계속한다.
  - `publish.index_log_key(prefix: str) -> str` — `<prefix>publish-log/index.json`. `publish.write_index_log(s3, bucket, mirror, prefix, result, env)`.
  - `publish.run_index_only(env=None, s3=None, cf=None) -> int`, CLI `td.publish index-only`. `Publication`의 단계를 run 없이 쓰는 `IndexPublication`: 접두 잠금(`acquire_lock`, 잡혀 있으면 `LockHeld`로 `failed`) → 미러 잠금 → `publish_index` → 무효화(CallerReference는 `index-<attempt_id>`) → Lightsail 삭제와 `rsync_lightsail(runs=False)` → `write_index_log` → 표준 오류에 한 줄. 종료 코드는 `failed`만 1. 신호 처리와 잠금 해제는 `run_publish`·`Publication.execute`와 같다.
  - `invalidation_paths`: `projects/` 아래 경로는 `/<prefix>projects/*` 하나로 묶는다.
  - `dashboard_fixtures.publish_fakes(tmp_path, repos, *, sonar=…) -> Fakes` — 가짜 gh, 가짜 Sonar, 가짜 ssh를 묶고 `.env`(`TD_GH_BIN`, `TD_SONAR_URL_OVERRIDE`, `PATH`)와 `.gh`, `.sonar`, `.ssh`를 준다. 가짜 ssh는 `psql`이 아닌 명령을 실제 `ssh`로 넘기므로 Lightsail rsync와 삭제는 실제로 돈다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `E2E-inj` 테스트는 기존 `site_prefix`, `s3_client`, `bucket`, `local_env`, `injected_petclinic_run`, `mini_sut_run` fixture와 `publish_fakes`를 쓴다. 테스트마다 `site_prefix` 아래에 자기 하위 접두(`<site_prefix>dash-<테스트 이름>/`)를 써서 서로 섞이지 않게 한다. 대표:

```python
def test_req098_index_only_publish(seeded_prefix, s3_client, bucket, tmp_path, local_env):      # seeded_prefix: 완료 run 하나를 게시해 둔 하위 접두
    fakes = publish_fakes(tmp_path, {"o/alpha": {}, "o/beta": {}}); cfg = write_cfg(tmp_path, cfg_with(plain=["alpha", "beta"]))
    before = set(list_keys(s3_client, bucket, seeded_prefix + "suts/"))
    proc = run_script("pipeline/publish-index.sh", TD_SITE_PREFIX=seeded_prefix, TD_DASHBOARD_CONFIG=str(cfg), **fakes.env)
    assert proc.returncode == 0 and set(list_keys(s3_client, bucket, seeded_prefix + "suts/")) - before <= index_level_keys(seeded_prefix)
    for key in ("projects/alpha/latest.json", "projects/alpha/index.html", "projects/alpha/series.json", "projects/beta/latest.json", "projects.json", "index.html"):
        assert s3_client.head_object(Bucket=bucket, Key=seeded_prefix + key)["CacheControl"] == "no-cache"
    assert any("/projects/alpha/snapshots/" in k for k in list_keys(s3_client, bucket, seeded_prefix + "projects/"))
    assert (mirror_dir(proc) / seeded_prefix / "projects/alpha/latest.json").exists()
    assert read_lock(s3_client, bucket, seeded_prefix) is None
    log = s3_json(s3_client, bucket, seeded_prefix + "publish-log/index.json"); assert log["status"] in ("passed", "degraded")
    assert dash_fetch(local_env, seeded_prefix + "projects.json") == s3_bytes(s3_client, bucket, seeded_prefix + "projects.json")

def test_req100_removed_or_private_project_deleted(seeded_prefix, s3_client, bucket, tmp_path, local_env):
    fakes = publish_fakes(tmp_path, {"o/alpha": {"description": "alpha desc"}, "o/beta": {}}); both = cfg_with(plain=["alpha", "beta"])
    publish_index(seeded_prefix, both, fakes); counts = {p: count_keys(p) for p in ("projects/beta/", "suts/", "static/")}
    def gone():
        blob = s3_text("index.html") + s3_text("projects.json")
        return count_keys("projects/alpha/") == 0 and "alpha" not in blob and "alpha desc" not in blob and not dash_exists(local_env, seeded_prefix + "projects/alpha")
    publish_index(seeded_prefix, cfg_with(plain=["beta"]), fakes); assert gone()
    publish_index(seeded_prefix, both, fakes); assert count_keys("projects/alpha/") > 0
    fakes.gh.set("o/alpha", visibility="private"); publish_index(seeded_prefix, both, fakes); assert gone()
    assert all(count_keys(p) >= n for p, n in counts.items())
    assert "alpha" not in json.dumps(s3_json(s3_client, bucket, seeded_prefix + "publish-log/index.json"), ensure_ascii=False)

def test_req144_interrupt_cleans_collect_token_and_lock(seeded_prefix, s3_client, bucket, tmp_path):
    for sig in (signal.SIGTERM, signal.SIGINT):
        fakes = publish_fakes(tmp_path / sig.name, {"o/alpha": {}}, sonar={"delay": 20})
        proc = start_script("pipeline/publish-index.sh", TD_SITE_PREFIX=seeded_prefix, TD_DASHBOARD_CONFIG=str(write_cfg(tmp_path / sig.name, cfg_with(plain="alpha"))), **fakes.env)
        wait_until(lambda: fakes.ssh.rows() != [], timeout=60); proc.send_signal(sig); assert proc.wait(timeout=120) != 0
        assert fakes.ssh.rows() == [] and read_lock(s3_client, bucket, seeded_prefix) is None
        assert not processes_matching("pipeline/collect.sh", "td.collect", marker=str(tmp_path / sig.name))

def test_req145_index_only_and_s13_share_lock(seeded_prefix, publisher, tmp_path):
    fakes = publish_fakes(tmp_path, {"o/alpha": {}}, sonar={"delay": 15})
    first = start_script("pipeline/publish-index.sh", TD_SITE_PREFIX=seeded_prefix, TD_DASHBOARD_CONFIG=str(write_cfg(tmp_path, cfg_with(plain="alpha"))), **fakes.env)
    wait_until(lambda: fakes.ssh.rows() != [], timeout=60)
    second = publisher.s13(prefix=seeded_prefix)                     # 기존 Publisher 헬퍼
    assert second.status == "failed" and "--force-unlock" in second.reason and second.seconds < 30
    assert first.wait(timeout=180) == 0

def test_req101_projects_invalidation_wildcard(tmp_path):            # test_unit_publish.py
    written = [tmp_path / "p" / f"projects/n{i}/{f}" for i in range(20) for f in ("index.html", "series.json", "latest.json")] + [tmp_path / "p/index.html"]
    paths = publish.invalidation_paths(tmp_path, written, "p/", "", "", include_log=False)
    assert [x for x in paths if "/projects/" in x] == ["/p/projects/*"]

def test_req100_delete_prefix_guard_and_lightsail_degraded(tmp_path):   # test_unit_publish.py
    s3 = FakeS3(); s3.put("p/projects/a/index.html"); s3.put("p/projects/ab/index.html"); s3.put("p/suts/x")
    assert publish.delete_prefix(s3, "b", "p/projects/a/") == 1 and s3.keys() == ["p/projects/ab/index.html", "p/suts/x"]
    for bad in ("p/projects/", "p/suts/x/", "p/", "p/projects/a/../"):
        with pytest.raises(publish.PublishError):
            publish.delete_prefix(s3, "b", bad)
    result = run_fake_index_publication(tmp_path, deleted=["a"], ssh_fails=True)
    assert result["status"] == "degraded" and result["hosts"]["s3"]["status"] == "passed"

def test_req106_idempotent_all_outputs(tmp_path):                     # test_dashboard_index.py
    site = proj_site(tmp_path); cfg = load_cfg(site)
    rebuild_site(site, cfg); first = snapshot_tree(site); rebuild_site(site, cfg)
    assert snapshot_tree(site) == first and any(p.startswith("projects/") for p in first) and "static/v2/app.css" in first
```

  079(접두 실행에 설정을 안 넘기면 홈에 운영 과제가 없고 `fakes.gh.calls == []`, 넘기면 그 과제가 나온다), 099(수집 `degraded` / 수집 자식이 종료 코드 1 / 표준 출력이 깨짐의 세 경우를 `TD_FAIL_STAGE=collect:<지점>` 주입으로 만들고, S13과 인덱스 전용 게시 각각에서 홈이 갱신되고 상태 `degraded`, 게시 기록 사유에 수집 사유, 제외된 이름 없음), 107(mini-sut이 설정 없이 홈에 `.tag-pipeline`으로 나오고 `.tag-partial`이 없고 `data-status`가 `none`이 아니며 `projects/<sut>/index.html`이 있고 gh 호출 0건), 125(`make_local_run_with_reports`의 run을 기존 `Publisher` 헬퍼로 하위 접두에 게시하고, 요구사항명세에 적힌 모든 진입 파일에 `<nav class="tdnav"`가 정확히 하나, 띠의 링크가 CloudFront에서 200, SUT 링크가 `suts/<sut>/index.html`로 끝남)도 쓴다.

- [ ] **Step 2: 실패를 확인한다**
- [ ] **Step 3: `publish.py`를 고친다.** `Publication.index_phase`의 몸을 `publish_index`로 옮기고 인덱스 전용 게시를 더한다. 잠금, 미러 잠금, 무효화, 로그 쓰기는 기존 함수를 쓴다. 주입 지점 `collect:exit1`, `collect:garbage`, `collect:degraded`는 `collect.sh`가 `td.hooks should-fail collect <지점>`으로 본다.
- [ ] **Step 4: `publish-index.sh`를 쓴다.** `common.sh`를 source하고 `td_py -m td.publish index-only`를 전경으로 실행하는 것이 전부다. `S13-publish.sh`의 머리 주석에 수집을 한 줄 더한다.
- [ ] **Step 5: 통과를 확인한다** — `pytest tests/acceptance/test_dashboard_publish.py tests/acceptance/test_unit_publish.py tests/acceptance/test_publish.py tests/acceptance/test_dashboard_index.py -v`. 끝난 뒤 가짜 프로세스 잔존 0, 테스트 접두의 잠금 객체 0.
- [ ] **Step 6: 커밋** — `feat(publish): collect inside the index phase, index-only publish, project pruning`

### Task 12: 공통 비기능

**REQ-IDs:** REQ-132, REQ-133, REQ-134, REQ-135, REQ-138

**Files:**
- Modify: `site-gen/td/site/static/v2/app.css`, `app.js`
- Test: `tests/acceptance/test_dashboard_common.py`

**Interfaces:**
- Consumes: Task 9의 `home_site`, Task 10의 `proj_site`·`proj`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
TABS = ["overview", "trend", "tests", "coverage", "hotspot", "quality", "generation", "runs"]

def report_pages(site: Path) -> list[str]:          # 렌더된 run 디렉터리에서 실제로 찾는다
    run = next((site / "suts/pet/runs").iterdir())
    rels = ["index.html", "coverage/coverage.html", "sonar/sonar.html", "compare/compare.html", "ontology/jqa.html", "ontology/owl.html",
            "hotspot/hotspots.html", "hotspot/api_report.html", "tia/tia.html"] + [p.relative_to(run).as_posix() for p in run.glob("cucumber/*/index.html")]
    assert all((run / r).is_file() for r in rels)
    return [f"{run.relative_to(site).as_posix()}/{r}" for r in rels]

def test_req132_no_external_requests(proj, proj_dir, browser):
    page = browser.new_page(); outside = []
    page.on("request", lambda r: outside.append(r.url) if not r.url.startswith((proj, "data:", "about:")) else None)
    for rel in ["", "projects/pet/index.html", "projects/plain/index.html", "hosting.html"] + report_pages(proj_dir): page.goto(proj + rel)
    for tab in TABS: page.goto(proj + "projects/pet/index.html#" + tab)
    assert outside == []
    assert not re.search(r"@import|url\(\s*['\"]?https?:", (STATIC_DIR / "v2/app.css").read_text())
    for html in own_html_files(proj_dir):            # 띠를 주입한 외부 리포트는 뺀다
        assert not re.search(r'<(script|img)[^>]+src="https?://|<link[^>]+href="https?://', html.read_text()), html

def test_req133_responsive_360(proj, proj_dir, browser, tmp_path):
    page = browser.new_page(viewport={"width": 360, "height": 740})
    own = [r for r in report_pages(proj_dir) if r.endswith(("index.html", "sonar.html", "compare.html")) and "cucumber" not in r]
    with serve(long_names_site(tmp_path)) as long_url:               # 이름 60자, 설명 200자
        for url in [proj, proj + "projects/plain/index.html", proj + "hosting.html", long_url] + [proj + r for r in own] + [proj + "projects/pet/index.html#" + t for t in TABS]:
            page.goto(url); assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), url

def test_req134_dark_theme(proj, proj_dir, browser):
    for rel in ["", "projects/pet/index.html", "hosting.html"] + [r for r in report_pages(proj_dir) if r.endswith(("sonar.html", "compare.html"))]:
        assert body_bg(browser, proj + rel, "light") != body_bg(browser, proj + rel, "dark"), rel
    for scheme in ("light", "dark"):
        page = open_page(browser, proj, scheme=scheme)
        for sel in (".st.s-crit", ".st.s-warn", ".st.s-good", ".st.s-none"):
            assert contrast(page, sel) >= 4.5, (scheme, sel)      # 요소의 color와, 투명이 아닌 가장 가까운 조상의 background-color

def test_req135_status_not_color_only(home, browser):
    page = open_page(browser, home)
    mark = lambda s: page.evaluate(f"(() => {{ const c = getComputedStyle(document.querySelector('.st.s-{s}'), '::before'); return [c.borderRadius, c.backgroundColor, c.borderTopWidth]; }})()")
    crit, warn, none = mark("crit"), mark("warn"), mark("none")
    assert crit[0] == "50%" and crit[1] != "rgba(0, 0, 0, 0)" and warn[0] != crit[0] and none[1] == "rgba(0, 0, 0, 0)" and none[2] != "0px"
    assert all(page.locator(f".st.s-{s}").first.inner_text().strip() for s in ("crit", "warn", "none", "good"))

def test_req138_reduced_motion(home, browser):
    ctx = browser.new_context(reduced_motion="reduce"); page = ctx.new_page(); page.goto(home)
    assert page.evaluate("getComputedStyle(document.querySelector('.caret')).transitionDuration") == "0s"
    ctx.close()
```

- [ ] **Step 2: 실패를 확인한다** (보통 133의 일부 탭과 134의 명암비)
- [ ] **Step 3: `app.css`를 고친다.** 넓은 표는 `.scroll` 안에, 긴 이름은 `overflow-wrap: anywhere`, 탭 줄은 가로 스크롤. 상태 표시의 글자색은 `--ink`.
- [ ] **Step 4: 통과를 확인한다**
- [ ] **Step 5: 커밋** — `feat(site): responsive, dark theme and motion rules for v2 pages`

### Task 13: PoC 테스트·문서 개정

**REQ-IDs:** 없음(새 REQ 없음). 요구사항명세 §3의 PoC REQ-035, 036, 044, 047, 048, 049, 050 개정과 문서 동기화.

**Files:**
- Modify: `tests/acceptance/test_site.py`, `test_baseline.py`, `test_coverage.py`, `test_reports.py`, `test_publish.py`, `test_hosting.py`, `docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md`, `docs/superpowers/requirements/2026-11-18-test-dashboard-poc-requirements.md`, `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md`, `README.md`

- [ ] **Step 1: 깨진 PoC 테스트를 찾는다** — `uv run --project site-gen pytest tests/acceptance -m "not baseline" -q`를 돌려 실패 목록을 적고, `grep -rn "suts/.*index.html\|kpi-item\|<svg\|site\.css\|_scope" tests/acceptance`로 옛 화면에 기대는 단언을 찾는다.
- [ ] **Step 2: 요구사항명세 §3의 표대로만 고친다.**
  - REQ-044 `test_req044_history_accumulates`: 두 runId를 `suts/<sut>/runs.json`과 과제 페이지 HTML의 `table#runs`에서 본다.
  - REQ-047/048 `test_hosting.py`: `_scope()`에 `/projects/`와 `/projects.json`을 더하고, 최신 runId를 `suts/<sut>/runs.json`과 과제 페이지에서 본다.
  - REQ-049의 세 테스트: `projects.json`(또는 홈의 `#projects-data`)에서 그 SUT와 이어진 과제의 `values`(`tests.passRate`, `coverage.line`, `sonar.gate`, `hotspot.topName`)를 읽고, 과제 페이지 HTML에서 `#panel-runs table#runs`와 `#panel-trend svg`를 본다.
  - REQ-050 `test_req050_multi_sut`와 `_sut_card`: 홈의 `tr.proj[data-name]`에 두 SUT의 이름이 있고 각 `projects/<sut>/index.html`에 그 SUT의 runId가 있다.
  - 표에 없는 테스트가 깨졌으면 구현을 고친다.
- [ ] **Step 3: PoC 설계와 PoC 요구사항명세의 해당 절·항목 문장을 고친다.** 설계 머리말의 표에 적힌 절(§6.1, §6.10, §6.11, §6.13, §13.3, §6.14, §13.1, §13.2)과 요구사항명세 §3 표의 REQ 수용기준, §0.1의 기준 run 줄.
- [ ] **Step 4: README를 고친다.** `writing-documentation` 스킬을 따른다. 더할 절: `dashboard.yaml`로 과제 등록하기, 상태 규칙과 탭·열 바꾸기, `pipeline/publish-index.sh`(run 없이 과제 목록 갱신. 화면만 바꾼 뒤에도 이 명령), 수집이 쓰는 것(`gh` 로그인, Sonar 임시 토큰과 SSH), 옛 run은 옛 모습으로 남는다는 것, 두 게시를 동시에 돌리면 나중 것이 실패한다는 것.
- [ ] **Step 5: 전체 로컬 스위트를 확인한다** — `uv run --project site-gen pytest tests/acceptance -m "not baseline" -q` 전부 PASS
- [ ] **Step 6: 새 요구사항명세의 매트릭스 상태를 실제 결과로 고친다**(통과한 것은 🟢).
- [ ] **Step 7: 커밋** — `test,docs: amend PoC tests and docs for the redesigned site`

### Task 14: 운영 게시와 확인

**REQ-IDs:** REQ-130, REQ-131, REQ-139, REQ-140

**Files:**
- Modify: `tests/acceptance/test_baseline.py`, `tests/acceptance/run_baseline.py`, `tests/acceptance/conftest.py`, `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md`

**Interfaces:**
- Consumes: 기존 `baseline_run` fixture(세션 파일), Task 4의 `tests/fixtures/reports/README.md`(선택자).
- Produces:
  - `run_baseline.py`가 두 번째 run 뒤에 `pipeline/publish-index.sh`를 한 번 돌리고 세션 파일에 `indexPublish: {"status", "reason"}`를 더한다.
  - `conftest.py`의 `baseline_site` fixture(`@pytest.mark.baseline` 테스트용): `.sut`(SUT 이름), `.run_id`, `.run_path`(`suts/<sut>/runs/<runId>/`), `.project`(그 SUT와 이어진 과제 이름), `.run_dir`(로컬 run 디렉터리), `.url(path) -> str`(`https://reports.<domain>/…`), `.dash_url(path)`, `.get(path, host="reports") -> (status, bytes)`.
  - 상수 `OLD_RUN_ID = "20261120-131022Z-b6f9393-manual-036c288d"`.

- [ ] **Step 1: 실패하는 테스트를 쓴다** — `@pytest.mark.baseline`

```python
def test_req130_hotspot_map_published(baseline_site, browser):
    status, body = baseline_site.get(baseline_site.run_path + "hotspot/hotspots.html")
    block = re.search(r'<script type="application/json" id="hotspot-map-data">(.*?)</script>', body.decode(), re.S)
    assert status == 200 and json.loads(block.group(1))["schemaVersion"] == 1
    top = json.loads(baseline_site.get(baseline_site.run_path + "stages/S09.json")[1])["top10"]
    assert 1 <= len(top) <= 10 and all({"name", "file", "score"} <= set(t) for t in top) and [t["score"] for t in top] == sorted((t["score"] for t in top), reverse=True)
    assert open_page(browser, baseline_site.url(baseline_site.run_path + "hotspot/hotspots.html")).locator("#hm-map circle").count() >= 1

def test_req131_tia_report_published(baseline_site, browser):
    page = open_page(browser, baseline_site.url(baseline_site.run_path + "tia/tia.html")); tabs = page.locator("#seg [role=tab]")
    assert tabs.count() == 4 and "변경 영향" in tabs.first.inner_text()
    for i in range(4):
        tabs.nth(i).click(); assert page.locator(TIA_GUIDE_SELECTOR + ":visible").count() == 1
    tabs.first.click(); changed = json.loads((baseline_site.run_dir / "S10/impact.json").read_text())["changedFiles"]
    assert page.locator(TIA_CHANGED_FILE_SELECTOR).count() == len(changed)

def test_req139_production_site_paths(baseline_site, browser):
    cfg = dashboard_config.load(REPO_ROOT / "dashboard.yaml", REPO_ROOT / "suts")
    listed = json.loads(baseline_site.get("projects.json")[1])["projects"]
    assert open_page(browser, baseline_site.url("")).locator("tr.proj").count() == len(listed) and 1 <= len(listed) <= len(cfg.projects)
    walk = [f"projects/{baseline_site.project}/index.html", baseline_site.run_path + "index.html", baseline_site.run_path + "hotspot/hotspots.html",
            baseline_site.run_path + "tia/tia.html", f"suts/{baseline_site.sut}/index.html"]
    for host in ("reports", "dash"):
        assert all(baseline_site.get(p, host=host)[0] == 200 for p in walk), host
        assert baseline_site.get("_design/home-repos/", host=host)[0] != 200 and baseline_site.get("_design/project/", host=host)[0] != 200
    old = baseline_site.get(f"suts/{baseline_site.sut}/runs/{OLD_RUN_ID}/index.html")
    assert old[0] == 200 and b"static/site.css" in old[1]

def test_req140_production_site_values(baseline_site, browser):
    latest = json.loads(baseline_site.get("projects/hotspot-analysis/latest.json")[1])
    assert isinstance(latest["ci"]["runs"], int) and abs(latest["ci"]["runs"] - count_runs_with_real_gh("baekchangjoon/hotspot-analysis")) <= 2
    data = json.loads(baseline_site.get("projects.json")[1]); mine = next(p for p in data["projects"] if p["name"] == baseline_site.project)
    home = open_page(browser, baseline_site.url("")); row = home.locator(f'tr.proj[data-name="{baseline_site.project}"]')
    assert row.get_attribute("data-status") == mine["status"]["level"]; row.click()
    assert all(r in home.inner_text("tr.proj-detail .detail-reasons") for r in mine["status"]["reasons"])
    runs = json.loads(baseline_site.get(f"suts/{baseline_site.sut}/runs.json")[1])
    page = open_page(browser, baseline_site.url(f"projects/{baseline_site.project}/index.html#trend"))
    assert page.locator('figure.trend[data-metric="tests.passRate"] .pt').count() == min(30, sum(1 for r in runs if r["kpis"]["passRate"] is not None))
    run = json.loads((baseline_site.run_dir / "run.json").read_text()); page.click("#tab-overview")
    assert page.inner_text('#panel-overview .kpi[data-metric="tests.passRate"] b') == f'{run["kpis"]["tests"]["passRate"] * 100:.1f}%'
    assert page.inner_text('#panel-overview .kpi[data-metric="coverage.line"] b') == f'{run["kpis"]["blackbox"]["line"] * 100:.1f}%'
```

  `TIA_GUIDE_SELECTOR`, `TIA_CHANGED_FILE_SELECTOR`는 `tests/fixtures/reports/README.md`에 적어 둔 값이다. `count_runs_with_real_gh`는 실제 `gh api`로 기본 브랜치의 완료 실행 30개를 읽어 설계 §6.3의 분류로 센다(수집기의 코드를 부르지 않는다).

- [ ] **Step 2: `run_baseline.py`와 `baseline_site` fixture를 고친다.**
- [ ] **Step 3: 시안을 지운다.** S3의 `_design/home-layout/index.html`, `_design/home-repos/index.html`, `_design/project/index.html` 세 객체와 Lightsail의 `/srv/dashboard/_design`. 지운 뒤 CloudFront에서 `/_design/*`를 무효화한다.
- [ ] **Step 4: 기준 run 세션을 돌린다** — `uv run --project site-gen python tests/acceptance/run_baseline.py`. 운영 사이트에 새 run 둘과 인덱스 전용 게시 한 번이 실린다.
- [ ] **Step 5: 전체 스위트를 돌린다** — `uv run --project site-gen pytest tests/acceptance -v`. 전부 PASS. 이어서 누수 확인: `docker ps -a --filter label=test-run=<세션 라벨>`이 비어 있고, 테스트가 띄운 PID가 없고, 테스트 접두의 잠금 객체가 없고, Sonar DB에 `td-collect-%`와 이번 세션의 `td-<runId>` 행이 0개다.
- [ ] **Step 6: 브라우저로 따라가 본다.** 첫 화면 → 위험 과제 펼침 → 과제 페이지의 탭 여덟 → 추이의 점 → run → hotspot 지도에서 원을 눌러 들어가기 → 띠로 SUT → 과제 페이지. 옛 run 하나를 열어 옛 모습인지 본다. 본 것을 한 줄씩 기록한다.
- [ ] **Step 7: 매트릭스를 100% green으로 맞추고 커밋** — `docs: matrix 70/70 after production run`

---

## 완료 정의

- 요구사항명세의 매트릭스가 대상 70개 모두 🟢이고, 각 행의 테스트 이름이 실제 통과한 테스트와 같다.
- PoC 매트릭스가 개정된 항목을 포함해 다시 전부 통과한다.
- 누수 확인(컨테이너, 프로세스, 잠금 객체, Sonar 토큰 행)이 0이다.
- README와 PoC 설계·요구사항명세가 새 동작과 맞다.

## 자기검토 기록

- 요구사항명세의 70개 REQ가 모두 Task에 있다: T1 077·078, T2 081·082·084, T3 076·102·103·105·122·141, T4 129, T5 097, T6 085~097·143, T7 124·126·127·136·137, T8 128, T9 089·090·104·109~114·142, T10 080·083·084·108·115~121·123, T11 079·098~101·106·107·125·144·145, T12 132~135·138, T14 130·131·139·140.
- Task 순서의 의존: T3이 `rebuild`의 `config`·`exclude` 인자와 공용 테스트 기반을 먼저 만든다. T5가 가짜 ssh를, T6이 가짜 gh를 만든다. T7이 run 렌더 빌더를, T9·T10이 고정 사이트 빌더를 만든다. 앞 Task의 테스트는 뒤 Task가 만드는 것에 기대지 않는다.
- 리뷰에서 받아들이지 않은 것: `static/v2/`를 게시기가 변경 불가로 강제하는 것(이 브랜치에서 아직 만들어 가는 자산이라 전역 제약의 규칙으로만 둔다).
