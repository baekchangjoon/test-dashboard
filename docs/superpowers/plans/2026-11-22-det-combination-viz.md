# det 조합 시각화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** det generation이 팩터·클래스·케이스 칸을 `factors.json`으로 내고, S12가 실행 결과와 합쳐 `compare/det.html`(추적 그래프·클래스 격자·2-way 히트맵)을 그린다.

**Architecture:** 생성기(`td/detgen/derive.py`)에 클래스 레지스트리와 칸 계산을 더하고 `render`가 `factors.json`을 쓴다. 결합·집계는 `td/detviz.py`(detgen 밖)가 하고, `compare.main`이 build를 한 번 해 `det-viz.json`을 쓰며 `render_page`가 `det.html`을 그린다. 화면은 Cytoscape와 `detviz.js`를 인라인한 정적 HTML이다.

**Tech Stack:** Python 3.12(uv, `site-gen`), jinja2, jsonschema, pytest, Playwright(chromium, 기존 의존성), Cytoscape(vendored), 바닐라 JS.

**Spec:** `docs/superpowers/specs/2026-11-22-det-combination-viz-design.md`
**Requirements:** `docs/superpowers/requirements/2026-11-22-det-combination-viz-requirements.md`(REQ-201~214)

## Global Constraints

- `cases.json`·`features/`·`glue/`는 바이트 단위로 바뀌지 않는다(REQ-203). 기준 스냅샷 `e2e/generated/petclinic/det/det-da70932c-r1/`은 지우지 않는다.
- 이론 상한 공식·`universe` 값은 바뀌지 않는다. 필드 매칭 의미(현재 `c.field == fld.name`)도 그대로다.
- `_field_classes(ep, fld)`는 valid를 **뺀** 클래스만 돌려준다. `_universe`는 `1 + len(...)`, `factors.json`은 valid(classKey `("valid",)`)를 맨 앞에 붙이고 나머지를 id 순으로 둔다.
- 클래스 id = `"c" + sha256(json.dumps([endpoint_label, f"{fld.loc}.{fld.name}", list(classKey)], ensure_ascii=False).encode()).hexdigest()[:12]`. 칸 키도 `loc.name`.
- kind 우선순위: count > contradicted > violation > branch > raw. 출처 주소는 `rstrip("~")` 후 기록.
- 집계는 `inModel=true` 케이스만 센다. inModel=false: auth, no-data, empty-body, filter-empty.
- 케이스 상태: passed/failed 외는 모두 notRun.
- 생성기 소스에 SUT 리터럴 금지(상위 REQ-106). det 번들 밖 파일 읽기 금지(상위 REQ-112).
- 화면 데이터는 `pages.json_for_script`로 싣고, 화면 문자열은 `textContent`로만 넣는다(`innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write` 금지).
- `det.html` 실패·부재가 S12·S13을 실패시키지 않는다. `compare.json` `viz.status == ok` ⇔ `det-viz.json`·`det.html` 존재.
- 실제 run은 반드시 `TD_SITE_PREFIX=_test/det-viz-<id>/`를 붙인다(접두 없이 실행 금지 — 운영 게시 방지).
- Task 5 run 이후 `td/detgen/*.py`를 고치면 run·스냅샷·세션 파일을 다시 만든다(genId가 바뀐다).
- 테스트 실행: `uv run --project site-gen pytest tests/acceptance/<file> -q`. Gradle 필요 시 `JAVA_HOME=$(/usr/libexec/java_home -v 17)`.
- 문서·주석은 한국어, 식별자는 영어. 커밋 메시지 끝에 세션 attribution 두 줄.

## Review Focus

- `||`, `<`, `</script>`, `<img onerror>`가 든 조건식 → id 안정·라벨 복원·DOM 주입 없음(Task 2, Task 4).
- `factors.json`이 없는 예전 generation, `viz` 키 없는 예전 `compare.json` 재게시 → `compare.html` 정상, 링크 없음, 낡은 `det.html` 삭제(Task 4).
- filter-empty가 enum-value로 병합된 실제 케이스(`list-enum-value-3`) → 칸 비교는 valid 정규화 후, `mergedRules`·`inModel`이 살아남은 규칙 기준(Task 2).
- 같은 정렬 키를 가진 생성 불가 슬롯 여러 개(실측 최대 4중복) → index가 `cases.json` 위치와 맞다(Task 2).
- 결과 줄이 없는 케이스만 있는 클래스 → `covered-notrun`(Task 3).

---

### Task 1: E2E 수용 테스트 먼저 작성(바깥 루프, red)

**REQ-IDs:** REQ-201, REQ-202, REQ-203, REQ-204, REQ-207, REQ-208, REQ-210, REQ-211, REQ-213

**Files:**
- Create: `tests/acceptance/test_det_viz.py`
- Modify: `tests/acceptance/conftest.py` — 마커 `det_viz_e2e`, `DET_VIZ_SESSION_FILE = Path(os.environ.get("TD_DET_VIZ_SESSION_FILE", REPO_ROOT / "work" / "det-viz-session.json"))`, 형식 `{"runDir", "previousCasesDir", "publishedDir", "publishedUrl"}`(모두 필수), 없으면 `pytest.fail`(skip 금지). 기존 `_require_det_session` 패턴을 따른다.

- [ ] **Step 1:** 테스트 작성(모두 `@pytest.mark.det_viz_e2e`). generation 디렉터리는 S06 `bdd-gen.json`의 det 항목 `dir`.
  - `test_req201_factors_real`: `factors.json` 스키마 통과, endpoints 17, cases 키 80, unresolved 50(index 0..49), id 재계산 일치·유일.
  - `test_req202_class_counts_real`: POST /api/reservations 필드별 고정값(petName 4, roomNumber 4, animalCount 3, checkInDate 3, nights 3, ownerEmail 3, priceTier 3, promoCode 3, depositAmount 2, loyaltyPoints 2), 이 표로 곱 46656·쌍 403을 테스트가 계산; `fields` 있는 factors 항목 전부 `len(classes) == fields[f]`.
  - `test_req203_cases_unchanged`: `cases.json`, `features/**`, `glue/**` 상대경로 집합·sha256이 `previousCasesDir`와 같다.
  - `test_req204_cells_real`: 모든 `cells` 값이 해당 필드 `classes[].id`에 있음, `cellConflicts == []`, 키 집합 일치, `unresolved[i]` rule·reason 대응.
  - `test_req207_page_and_links`: REQ-207 Then 전부(S12 파일·스키마, caseResults 80, `viz.status == "ok"`, `<publishedDir>/compare/det.html`, `<publishedDir>/index.html`의 `compare/det.html`·`<publishedDir>/compare/compare.html`의 `det.html` href, `urllib.request`로 `publishedUrl` 기준 `compare/det.html` 200).
  - `test_req208_recount`: 독립 구현(설계 §5.4; 상태는 `td.scenarios.pickle_refs`+`scenario-results.json`만, `detgen.results` 미사용)으로 클래스별 state·cases·boundaryCases·unresolved, 엔드포인트별 pairs total/covered/matrix, summary 전부 비교. POST pairs.total 403, outOfModel {auth 16, no-data 8, empty-body 1, filter-empty 2}, inModel 53, summary endpoints 17·fields 26·classes 55·pairsTotal 434.
  - `test_req210_no_leaks`: `<publishedDir>/compare/det.html`·`det-viz.json`의 `redact.find_leaks` 0, `pages.check_no_home(publishedDir)`.
  - `test_req211_browser`: `test_ontology.py`의 `sync_playwright` 패턴. `<runDir>/S12/compare/det.html`을 `route("**/*")`로 file: 외 차단해 열고 `window.__td_ready === true`를 기다림 → 외부 요청 0, 콘솔·pageerror 0; 그래프 노드 수·격자 칸 수(`[data-class-id]`)·히트맵 행렬 수(`[data-pair]`)가 det-viz.json과 같음; 엔드포인트 `select` 변경 시 노드 집합 변경; 케이스 노드 클릭(`cy` 이벤트를 `window.__detviz.select(caseId)` 훅으로 호출) 후 패널 `textContent`에 조건식·기대·관측; 히트맵 `details` 펼침; 라이트·다크(`emulate_media(color_scheme=...)`)·390px에서 `scrollWidth <= clientWidth`.
  - `test_req213_passed_matches_summary`: caseResults passed 수 == `compare.json` `deterministic.summary.passStrict.passed`.
- [ ] **Step 2:** `uv run --project site-gen pytest tests/acceptance/test_det_viz.py -q` → 세션 파일 없음으로 전부 FAIL(정상).
- [ ] **Step 3:** Commit `test(det-viz): E2E acceptance tests (red)`.

### Task 2: 클래스 레지스트리·칸 계산·`factors.json`

**REQ-IDs:** REQ-201, REQ-202, REQ-203, REQ-204, REQ-205, REQ-206

**Files:**
- Modify: `site-gen/td/detgen/endpoints.py` — `Endpoint.class_sources: dict`, `Endpoint.class_kinds: dict`(키 `(field_name, classKey)`, 기본 빈 dict)
- Modify: `site-gen/td/detgen/derive.py` — 레지스트리 채우기, `_field_classes`, `_cells`, `_Draft.cell_info`, `_skip`의 칸 쌍(`self._slot_cells` 병렬 목록, 같은 키로 안정 정렬), `_dedupe`의 boundaries·mergedRules·cellConflicts, `Derivation.factors`
- Modify: `site-gen/td/detgen/render.py` — `FACTORS_FILE = "factors.json"`; `derivation.factors`가 비어 있지 않으면 쓰고 반환 목록에 포함; `_cases_text` 불변
- Create: `site-gen/td/schemas/factors.schema.json`
- Create: `tests/fixtures/det/viz-kinds/`(controlled 형식 번들: 같은 필드에 오류 조건+같은 키의 분기 조건, count, 미변환 원자식, 모순 항목 쌍; 같은 이름의 body·query 필드; 조건식에 `||`·`<`·`</script>`; README에 의도 기재)
- Test: `tests/acceptance/test_unit_detviz.py`

**Interfaces:**
- Produces: `Derivation.factors: dict = field(default_factory=dict)`(`timezone` 뒤, 기존 위치 인자 생성 호환), 파일 `<gen>/factors.json`(설계 §5.3).
- `_field_classes(ep, fld) -> dict[tuple, tuple[str, frozenset[str]]]`(classKey → (kind, sources), valid 제외).
- `_disjunct`는 원자식별 `(Con | 사유, rawKey | None)` 목록을 돌려주도록 바꾼다(호출부 갱신). 미해결 count 필드는 `Constraints.con` 호출 전후 `ep.count_fields` 차이로 얻는다.
- `_cells(ep, draft, atoms, flip) -> CellInfo`(dataclass `cells: dict[str,str]`, `boundaries: list[str]`, `stored: list[str]`, `enum_value: dict | None`). 직렬화 키는 `cells, boundaries, stored, enumValue`.
- 사유가 있는 슬롯: 변환된 원자식과 raw 키가 있는 원자식만 칸을 적는다. flip 대상이 raw면 그 필드 칸은 `valid`, `boundaries`에 raw 클래스. 모순 슬롯은 raw 꼴 키(kind contradicted)로 잇는다.
- 병합: 칸 비교는 적지 않은 필드를 `valid`로 채운 dict끼리. 살아남은 쪽 `cells` 유지, 차이는 `cellConflicts`에 `{field, kept, merged, mergedRule}`.
- `factors.json` `unresolved[]` 항목은 `source`(`cases.json`과 같은 주소)를 가진다. 요청 필드 없는 엔드포인트의 `fields`는 `[]`.

- [ ] **Step 1: 실패하는 단위 테스트**(`test_unit_detviz.py`, 기존 `test_unit_detgen.py`의 `_controlled`/`_real_bundle` 헬퍼 재사용)
  - `test_req201_factors_schema`, `test_req201_valid_first_and_ids`(valid 첫째·1개, id 재계산·유일), `test_req201_kind_rules`(viz-kinds), `test_req201_qualified_field_ids`(viz-kinds body·query 동명 필드 id 분리), `test_req201_hostile_strings`(viz-kinds: 두 번 생성 id 동일, 라벨·condition JSON 복원).
  - `test_req202_class_counts`: petclinic 고정값 표 + controlled·petclinic에서 `len(classes) == fields[f]`.
  - `test_req203_petclinic_bytes`: `tests/fixtures/det/petclinic`으로 generation → `cases.json`·`features/`·`glue/`가 기준 스냅샷과 sha256 동일.
  - `test_req204_cells`: parametrize 행 = 위반·경계·branch·count 위반·count 경계·enum·생략 필드(controlled), rel·stored·raw·모순(petclinic). 행마다 대상 케이스/슬롯 id와 기대 칸을 테스트 안에 고정.
  - `test_req204_merge`: petclinic의 병합 케이스(filter-empty→enum-value)에서 boundaries 합집합·`mergedRules == ["filter-empty"]`·`cellConflicts == []`·`inModel` true; 의도적으로 칸이 다른 두 초안을 `_dedupe`에 직접 넣으면 `cellConflicts` 비지 않음.
  - `test_req204_unresolved_index`: petclinic에서 `factors.unresolved[i]`와 `cases.json` `unresolved[i]`의 rule·reason·source 일치, 초안 이전 슬롯 `draftKey is None and cells == {}`.
  - `test_req205_sources`: REQ-205 Then 전부.
  - `test_req206_deterministic`: 서로 다른 tmp 경로 두 번 → `factors.json` 바이트 동일, 필드 순서 = universe fields 키 순서.
- [ ] **Step 2:** 실행 → FAIL.
- [ ] **Step 3:** 구현. 클래스 라벨: 연산자 기호+값(length면 `length` 접두, date면 `today±N`), count `count ≥ N`, raw/contradicted `<op> <right>`, valid `유효`. 출처 원문은 번들 `plans.json`/`keyparams.json`.
- [ ] **Step 4:** 실행 → PASS. `test_unit_detgen.py`·`test_det_glue.py` 전부 통과.
- [ ] **Step 5:** Commit `feat(det-viz): class registry, cells and factors.json`.

### Task 3: `td/detviz.py` 결합·집계

**REQ-IDs:** REQ-206, REQ-208, REQ-212, REQ-213

**Files:**
- Create: `site-gen/td/detviz.py`, `site-gen/td/schemas/det-viz.schema.json`
- Modify: `site-gen/td/detgen/results.py` — `_case_statuses` → 공개 `case_statuses`(`summarize`가 사용, `__all__`에 추가). 반환 의미 불변.
- Test: `tests/acceptance/test_unit_detviz.py`

**Interfaces:**
- Consumes: `<gen>/factors.json`, `<gen>/cases.json`, `<s07>/scenario-results.json`, `<s07>/cucumber.json`.
- Produces: `class FactorsMissing(Exception)`, `build(gen_dir: Path, s07_dir: Path) -> dict`(설계 §5.4 `det-viz.json`), `validate(doc: dict) -> None`.

- [ ] **Step 1: 테스트**(S07 fixture는 `test_unit_detgen.make_det_results` 재사용)
  - `test_build_aggregates_small`: 필드 2개(클래스 2·3), 케이스 passed·failed·notRun·outOfModel → 상태 5종, boundaryCases, pairs total 6·covered 기대값, summary 각 키.
  - `test_req213_status_mapping`: passed/failed/undefined/uncompilable/결과 없음 → passed/failed/notRun×3; observed·expectStrict·endpoint 규칙.
  - `test_build_factors_missing`: `FactorsMissing`.
  - `test_build_schema`: `validate` 통과.
  - `test_req206_build_path_independent`: 같은 입력을 두 임시 경로에 복사해 build → 같은 dict.
  - `test_req212_source_checksum_unaffected`: `detgen.stage.source_checksum()`의 대상 파일 목록에 `detviz.py`·`detviz.js`·`det.html.j2`가 없다(구현 후 같은 값).
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** PASS(+ 기존 summarize 테스트) → **Step 5:** Commit `feat(det-viz): detviz build and aggregates`.

### Task 4: compare 통합·`det.html`·링크

**REQ-IDs:** REQ-207, REQ-209, REQ-211

**Files:**
- Modify: `site-gen/td/schemas/compare.schema.json` — `deterministic` measured 변형에 필수 `viz: {status: ok|absent|failed, reason: string|null}`
- Modify: `site-gen/td/compare.py` — `_deterministic`이 `viz`(ok|absent) 기록; `main`: validate → mkdir → (ok면) `detviz.build` 1회·`det-viz.json` 쓰기 → `render_page` → 예외 시 파일 삭제·`viz` failed·재검증 → (ok 아니면) 낡은 파일 삭제 → `compare.json` 쓰기; `render_page`: `det.html` 먼저(파일·`viz ok`일 때만), 예외면 삭제·메모리 `viz` failed, `viz` 키 없으면 absent 취급, 그다음 `compare.html`
- Modify: `site-gen/td/site/layout.py` — `REPORTS_EXTRA["compare/"] = [("det 조합 시각화", "det.html")]`, `LINK_ONLY_IF_PRESENT`에 `"compare/"`, `_rerender_compare`가 `render_page` 뒤 문서 `viz`가 바뀌었으면 `target/compare.json`을 다시 쓴다
- Create: `site-gen/td/site/templates/det.html.j2`, `site-gen/td/site/static/detviz.js`
- Modify: `site-gen/td/site/templates/compare.html.j2` — `det.html` 파일이 있을 때만 링크, absent/failed면 사유 문구
- Test: `tests/acceptance/test_unit_detviz.py`(compare 픽스처는 `test_compare.add_det_arm` 재사용)

**Interfaces:**
- Consumes: `detviz.build`, `detviz.FactorsMissing`, `detviz.validate`, `pages.json_for_script`, `ontology_html`의 인라인 방식(vendor `cytoscape.min.js`).
- Produces: `S12/compare/det-viz.json`, `S12/compare/det.html`; `render_page(out_dir, document, css_href, copy_css)` 시그니처 불변. 화면 훅 `window.__detviz.select(id)`(테스트용, 노드 선택과 같은 동작), 렌더 완료 플래그 `window.__td_ready = true`. 격자 칸 `data-class-id`, 행렬 `data-pair`, 그래프 노드 수 `data-node-count`.

- [ ] **Step 1: 테스트**
  - `test_req209_absent`, `test_req209_build_error`, `test_req209_write_error`(det-viz.json 쓰기에 OSError 주입), `test_req209_render_error`(det.html 템플릿 예외 → compare.html에 `href="det.html"` 없음), `test_req209_rerender_error`(`RERENDER["compare/"]` 경로, 게시 사본 compare.json viz failed), `test_req209_stale_removed`(factors 삭제·det 블록 null·failed 변형 재실행 각각), `test_req209_missing_viz_key` — 각 REQ-209 (a)~(g) 단정.
  - `test_req211_hostile_dom`: viz-kinds 기반 det.html을 Playwright로 열어 주입 요소(`img[onerror]` 등)·`window.__pwned` 없음, 패널 textContent에 원문.
  - `test_req211_static_rules`: `detviz.js`에 금지 sink 문자열 없음, det.html에 `<script src=` 0, cytoscape 인라인.
- [ ] **Step 2:** FAIL → **Step 3:** 구현(화면 구성 설계 §5.4 1~6, 기호 ✓ ✗ ○ ⊘ ·, `.scroll` 래핑, 라이트/다크 토큰) → **Step 4:** PASS + `test_compare.py`·`test_site.py`·`test_unit_index.py` 중 서버·인프라 불필요한 테스트 통과 → **Step 5:** Commit `feat(det-viz): det.html in S12 with links and isolation`.

### Task 5: 실제 run·게시·문서

**REQ-IDs:** REQ-201~REQ-214

**Files:**
- Modify: `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md`(§5.4 generation 구성에 `factors.json`, S12 산출물 `det-viz.json`·`det.html`)
- Modify: `README.md`(리포트 목록에 det 조합 시각화)
- Modify: 요구사항명세 매트릭스(상태)
- Test: `tests/acceptance/test_unit_detviz.py::test_req214_docs`
- Add: 새 det 스냅샷 `e2e/generated/petclinic/det/<새 genId>/`

- [ ] **Step 1: 준비** — det worktree에서 `work/infra/`(tfstate)·`work/site-mirror/`와 `infra/local.env`를 이 worktree 같은 경로로 복사(모두 gitignore, 내용 출력 금지). LLM arm 스냅샷은 저장소 `e2e/generated`에 있다.
- [ ] **Step 2: run** — `TD_SITE_PREFIX=_test/det-viz-<YYYYMMDD>/ pipeline/run-all.sh petclinic --arms base,jqa,owl,det`. 종료 코드 0, S06 `bdd-gen.json`에서 base/jqa/owl이 모두 스냅샷 재사용(claude 호출 0), SUT 커밋이 `b6f9393`인지 확인. 다르면 멈추고 원인 기록.
- [ ] **Step 3: 세션 파일** — `work/det-viz-session.json` = `{runDir, previousCasesDir: <abs>/e2e/generated/petclinic/det/det-da70932c-r1, publishedDir: <runDir>/site, publishedUrl: <run 페이지 URL>}`. 기존 `work/det-session.json`의 `runDir`도 새 run으로 갱신(`baselineRunDir`은 유지).
- [ ] **Step 4:** `uv run --project site-gen pytest tests/acceptance/test_det_viz.py tests/acceptance/test_det.py -m "det_viz_e2e or det_e2e" -q` → 전부 PASS.
- [ ] **Step 5:** 문서 갱신 + `test_req214_docs` PASS, 매트릭스 상태 갱신(테스트명은 매트릭스와 일치시킨다).
- [ ] **Step 6: 회귀** — `uv run --project site-gen pytest tests/acceptance -q -m "not baseline"`(baseline은 기준 run 세션이 없어 제외, 보고에 명시). 끝난 뒤 `docker ps -a --filter label=td-run` 등 이 세션 테스트 라벨 컨테이너 0, SUT PID 잔존 0 확인.
- [ ] **Step 7:** Commit `docs(det-viz): run results, matrix, design/README updates; add det snapshot`.
