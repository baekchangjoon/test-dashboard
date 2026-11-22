# det 조합 시각화 요구사항명세

> 출처(design spec): `docs/superpowers/specs/2026-11-22-det-combination-viz-design.md`
> 완료 정의: 대상 REQ(Must + 미연기 Should)마다 매트릭스의 검증 테스트가 있고, 모두 통과한다.
> 규약: 상위 요구사항명세 `2026-11-18-test-dashboard-poc-requirements.md` §0을 따른다. REQ-ID는 REQ-201부터 쓴다.
> 실제 run 전제(E2E): 기준 SUT 커밋 `b6f9393`과 현재 `tools.pin.yaml`. 전제가 깨지면 E2E는 실패한다(숫자 80·46,656·403은 이 전제의 값이다).
> E2E 공통 Given: 컨트롤러가 `TD_SITE_PREFIX=_test/det-viz-<id>/ pipeline/run-all.sh petclinic --arms base,jqa,owl,det`을 돌리고
> 세션 파일 `work/det-viz-session.json`(`TD_DET_VIZ_SESSION_FILE`로 대체 가능)에 `{"runDir", "previousCasesDir", "publishedDir", "publishedUrl"}`를 적는다.
> `previousCasesDir` = `e2e/generated/petclinic/det/det-da70932c-r1`(저장소에 보존), `publishedDir` = `<runDir>/site`(가림 적용 게시 미러), `publishedUrl` = 게시된 run 페이지 URL.
> 세션 파일이 없으면 E2E는 skip이 아니라 fail이다.

## 1. 요구사항

### REQ-201 factors.json 출력과 클래스 목록 (Must, Unit+E2E)
- Given: det 번들로 generation을 만든다.
- When: generation 디렉터리를 읽는다.
- Then:
  - `factors.json`이 있고 `factors.schema.json`을 통과한다.
  - 모든 필드에서 `classes[0].kind == "valid"`이고 valid는 정확히 1개다. 나머지는 클래스 id 순이다.
  - 클래스 id가 설계 공식(`"c" + sha256(json.dumps([endpoint, field, list(classKey)], ensure_ascii=False))[:12]`, field는 `f"{loc}.{name}"` 문자열)의 재계산과 같고 문서 전체에서 유일하다.
  - kind 우선순위(count > contradicted > violation > branch > raw): 오류 항목과 분기 항목에 동시에 걸리는 키는 `violation`, 모순 항목 키는 `contradicted`, count 키는 `count`, 미변환 원자식 키는 `raw`다(전용 fixture).
  - 같은 이름의 body·query 필드가 한 엔드포인트에 있으면 클래스 id가 분리된다.
  - `||`, `<`, `</script>`가 든 조건식에서 id가 안정적(두 번 생성 동일)이고 라벨·원문이 JSON에서 그대로 복원된다.
  - 요청 필드가 없는 엔드포인트의 `fields`는 빈 배열이다.
  - 실제 run: `endpoints` 17개(필드 없는 엔드포인트 6개 포함), `cases` 키 80개, `unresolved` 50개(`index` 0..49, 각 항목에 `source`).

### REQ-202 클래스 수(독립 기대값) (Must, Unit+E2E)
- Given: petclinic 입력(단위: `tests/fixtures/det/petclinic`, E2E: 실제 run).
- Then:
  - POST /api/reservations의 필드별 클래스 수(valid 포함)가 고정 기대값과 같다: petName 4, roomNumber 4, animalCount 3, checkInDate 3, nights 3, ownerEmail 3, priceTier 3, promoCode 3, depositAmount 2, loyaltyPoints 2. 테스트가 이 표에서 곱 46,656과 쌍 수 403을 직접 계산한다.
  - `fields` 키가 있는 `universe.theoretical.factors[]` 항목(빈 dict 포함)마다 필드별 `len(classes)`(valid 포함)가 `fields[field]`와 같다. `fields`가 없는 `concurrency-race` 항목 2개는 비교·집계 대상이 아니다.

### REQ-203 생성 결과 불변 (Must, Unit+E2E)
- Given: 기준 스냅샷 `e2e/generated/petclinic/det/det-da70932c-r1/`(지우지 않는다).
- Then: 새 generation의 `cases.json`과 `features/` 아래 모든 파일의 상대경로 집합·sha256이 기준과 같다. `glue/`도 같다(고정 glue).
  det pairwise가 켜진 run이면: pairwise가 아닌 케이스 항목은 기준과 같고, pairwise 시나리오가 붙은 feature는 기준 내용이 앞부분이며 나머지 파일은 바이트 동일하다.
  단위는 `tests/fixtures/det/petclinic` 입력으로, E2E는 실제 run의 generation으로 확인한다.

### REQ-204 케이스 칸 규칙 (Must, Unit+E2E)
- 설계 §5.2 표의 행마다 fixture 케이스 하나로 `cells`·`boundaries`·`stored`·`enumValue`가 기대와 같다:
  위반, 유효 경계(flip), branch-entry(kind branch), count 위반, count 유효 경계(`valid`+`boundaries`에 count), rel(`side[0]`만),
  stored(`stored` 기록, 요청 칸 아님), raw(생성 불가 슬롯), enum-value(`valid`+`enumValue`), 칸에 없는 필드(valid 해석), 모순 슬롯(contradicted 키).
  행별 fixture: 위반·경계·branch·count·enum·병합은 controlled, rel·stored·raw·모순·unresolved index는 petclinic.
- 모든 `cases`·`unresolved`의 `cells` 값은 같은 엔드포인트·필드의 `classes[].id`에 있다(매달린 참조 0).
- `inModel`: auth, no-data, empty-body, filter-empty → `false`와 `outReason`. 그 밖(happy 포함) → `true`. 병합 케이스는 살아남은 규칙 기준.
- 병합: `boundaries`는 합집합, `mergedRules`는 병합된 규칙 목록. 칸 비교는 적지 않은 필드를 valid로 해석한 뒤 하고, 실제 데이터에서 `cellConflicts`는 빈 목록이다.
  의도적으로 칸이 다른 병합 fixture에서는 `cellConflicts`가 비지 않는다. 항목 형식은 `{field, kept, merged, mergedRule}`(kept·merged는 클래스 id)이다.
- 생성 불가 슬롯: `factors.unresolved[i]`의 `rule`·`reason`이 `cases.json` `unresolved[i]`와 같다(같은 정렬 키 여러 개 포함). 초안 이전에 건너뛴 슬롯은 `draftKey: null`, `cells: {}`.
- E2E: 실제 run에서 위 참조 무결성, `cellConflicts == []`, 키 집합 일치, unresolved 대응.

### REQ-205 출처 원문 (Must, Unit)
- `classes[].sources`, `cases.json` `cases[].sources`, `factors.json` `unresolved[].source`의 모든 주소(`~` 제거)가 `factors.json` `sources` 키에 있다.
- kind별: plan은 `condition`·`expected`가 번들 `plans.json` 항목과 같고 `methods` 1개. keyparams는 `condition`이 분기 사유 원문, `expected` null, `methods` 1개. graph·harness·input은 `condition`·`expected` null, `methods` [].
- 엔드포인트 `methods`는 대응 계획의 `클래스명#메서드명` 목록과 같다.
- 출처 문자열에 절대경로(`/Users/`, `/home/`, `/private/`)가 없다.

### REQ-206 결정성 (Must, Unit)
- 같은 번들로 서로 다른 경로에서 두 번 생성하면 `factors.json`이 바이트 동일하다. 필드 순서는 `universe.theoretical.factors[].fields`의 키 순서와 같다.
- 같은 입력을 서로 다른 임시 경로에 복사해 `detviz.build`를 부르면 결과가 같다(경로·시각 미포함).

### REQ-207 det.html 생성과 링크 (Must, E2E)
- Given: E2E 공통 Given의 run.
- Then:
  - `<runDir>/S12/compare/det.html`·`det-viz.json`이 있고 `det-viz.json`이 `det-viz.schema.json`을 통과한다.
  - `caseResults` 키 = `cases.json` id 80개.
  - `compare.json` `deterministic.viz.status == "ok"`.
  - `<publishedDir>/compare/det.html`이 있고, `<publishedDir>/index.html`에 `compare/det.html`, `<publishedDir>/compare/compare.html`에 `det.html`을 가리키는 href가 있다.
  - `publishedUrl` 기준 `compare/det.html` GET이 200이다.

### REQ-208 화면 숫자 재계산 일치 (Must, E2E)
- 테스트 안의 독립 구현(설계 §5.4 식. 상태는 `td.scenarios` pickle 매핑과 `scenario-results.json`만으로 구하고 `detgen.results`를 쓰지 않는다)이 `cases.json`·`factors.json`·S07 결과에서 계산한 값이 `aggregates`와 같다:
  - 클래스 id마다 `state`(covered-pass, covered-fail, covered-notrun, unresolved, empty), `cases` 목록, `boundaryCases`, `unresolved` 목록.
  - 엔드포인트별 `pairs.total`·`pairs.covered`·모든 `matrix.counts`. POST /api/reservations `pairs.total == 403`.
  - `summary`의 endpoints, fields, classes, classesCovered, pairsCovered, pairsTotal, outOfModel. 기준값: endpoints 17, fields 26, classes 55, pairsTotal 434. `outOfModel`은 auth 16, no-data 8, empty-body 1, filter-empty 2이고 inModel 케이스는 53건이다.
- 집계는 inModel 케이스만 세고, 칸에 없는 필드는 valid로 해석한다.

### REQ-209 실패 격리 (Must, Int)
- (a) absent: `factors.json`이 없는 generation → compare 성공, `viz = {status: absent, reason: null}`, `det.html`·`det-viz.json` 없음, `compare.html`에 det.html 링크 없음, run 페이지에 링크 없음.
- (b) build 예외(`detviz.build` monkeypatch) → compare 성공, `validate` 통과, `viz = {status: failed, reason: <문자열>}`, 파일·링크 없음. `deterministic.viz`를 뺀 `compare.json`이 예외 주입 없는 실행과 같다.
- (c) 쓰기 예외(`det-viz.json` 쓰기 실패 주입) → (b)와 같은 결과.
- (d) 렌더 예외(`det.html` 템플릿 예외 주입) → `compare.html`은 생기고 링크 없음, `det.html` 없음, `viz.status == failed`.
- (e) RERENDER 예외 → 게시 사본에서 `compare.html` 정상, `det.html` 없음, 게시 사본 `compare.json`의 `viz.status == failed`.
- (f) 낡은 파일: ok로 만든 뒤 factors를 지우고 재실행, 또는 det 블록이 null·failed 변형이 되는 재실행 → 이전 `det-viz.json`·`det.html`이 지워진다.
- (g) 하위 호환: `viz` 키가 없는 measured 블록으로 `render_page`를 부르면 `compare.html`이 정상이고 링크가 없다.

### REQ-210 누출 없음 (Must, E2E)
- `<publishedDir>/compare/det.html`·`det-viz.json`에 `redact.find_leaks` 0건, `pages.check_no_home(<publishedDir>)` 통과.

### REQ-211 화면 동작 (Must, E2E·Playwright)
- 기존 `test_ontology.py`의 Playwright 패턴으로 다음을 자동 확인한다. `detviz.js`는 데이터 파싱과 그래프 렌더가 끝나면 `window.__td_ready = true`를 설정하고 테스트는 이를 기다린다.
  - `<runDir>/S12/compare/det.html`을 네트워크 차단 상태로 열어 외부 요청 0건, 콘솔·페이지 오류 0.
  - 그래프 노드 수, 격자 칸 수, 히트맵 행렬 수가 `det-viz.json`과 같다.
  - 엔드포인트 선택을 바꾸면 그래프가 바뀌고, 케이스 노드를 누르면 패널에 조건식 원문·기대·관측이 표시된다. 히트맵 펼침이 동작한다.
  - 라이트·다크, 390px 폭에서 `scrollWidth <= clientWidth`(페이지 가로 스크롤 없음).
  - 적대적 문자열 fixture(`</script>`, `<img onerror>`, 이벤트 속성)로 만든 det.html에서 주입된 요소·실행 표식이 없고 원문이 textContent로 보인다.
- 정적 검사: `site/static/detviz.js`에 `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write`가 없다. `det.html`에 `<script src=`가 0개이고 Cytoscape가 인라인돼 있다.

### REQ-212 모듈 경계 (Must, Unit)
- `td/detviz.py`·`site/static/detviz.js`·`det.html.j2`를 바꿔도 `detgen.stage.source_checksum()`이 같다(detgen 밖).

### REQ-213 결과 결합 규칙 (Must, Unit+E2E)
- 단위: S07 fixture(passed, failed, undefined, uncompilable, 결과 줄 없음)에서 `caseResults.status`가 passed, failed, notRun, notRun, notRun이다.
  `observed`는 통과 시 `expect.strict`가 정수면 그 값, 실패 시 `observed_codes`에 코드가 있으면 그 값, 그 밖(코드 미발견, notRun)은 null. `expectStrict`·`endpoint`가 cases.json과 같다.
- E2E: 실제 run에서 `caseResults`의 passed 수가 `compare.json` `deterministic.summary.passStrict.passed`와 같다.

### REQ-214 문서 갱신 (Should, Unit)
- `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md` §5.4에 `factors.json`, S12 산출물에 `det-viz.json`·`det.html`이 적혀 있고, `README.md` 리포트 목록에 det 조합 시각화가 있다(문자열 검사 테스트).

### REQ-215 pairwise 케이스 표시 (Must, Unit+E2E)
- det pairwise가 켜진 generation에서 `pairwise` 규칙 케이스도 `factors.json` `cases`에 칸을 가진다(`inModel: true`).
- 칸은 기존 평가기로 정한다: 값이 그 필드의 원자식(오류·분기, `~` 제외)을 참으로 만들면 그 클래스, 원자식의 유효 경계값과 같으면 valid + `boundaries`, 그 밖은 valid.
- petclinic에서 포인트 499 행은 `< 500` 클래스 칸, 500 행은 valid 칸과 `< 500` 경계를 가진다. 모든 칸의 클래스 id가 해당 필드의 `classes`에 있다.
- E2E: pairwise가 켜진 실제 run에서 REQ-208 재계산이 pairwise 케이스를 포함해 `aggregates`와 같다.

## 2. 추적 매트릭스

| REQ-ID | 요약 | 검증 테스트 | 레벨 | 상태 |
|---|---|---|---|---|
| REQ-201 | factors.json·클래스 목록 | test_unit_detviz.py::test_req201_factors_schema<br>test_unit_detviz.py::test_req201_valid_first_and_ids<br>test_unit_detviz.py::test_req201_kind_rules<br>test_unit_detviz.py::test_req201_qualified_field_ids<br>test_unit_detviz.py::test_req201_hostile_strings<br>test_det_viz.py::test_req201_factors_real | Unit/E2E | 🟢 passed |
| REQ-202 | 클래스 수 | test_unit_detviz.py::test_req202_class_counts<br>test_det_viz.py::test_req202_class_counts_real | Unit/E2E | 🟢 passed |
| REQ-203 | 생성 결과 불변 | test_unit_detviz.py::test_req203_petclinic_bytes<br>test_det_viz.py::test_req203_cases_unchanged | Unit/E2E | 🟢 passed |
| REQ-204 | 칸 규칙 | test_unit_detviz.py::test_req204_cells (행별 parametrize)<br>test_unit_detviz.py::test_req204_merge<br>test_unit_detviz.py::test_req204_unresolved_index<br>test_unit_detviz.py::test_req204_references_and_in_model<br>test_det_viz.py::test_req204_cells_real | Unit/E2E | 🟢 passed |
| REQ-205 | 출처 원문 | test_unit_detviz.py::test_req205_sources | Unit | 🟢 passed |
| REQ-206 | 결정성 | test_unit_detviz.py::test_req206_deterministic<br>test_unit_detviz.py::test_req206_build_path_independent | Unit | 🟢 passed |
| REQ-207 | det.html·링크 | test_det_viz.py::test_req207_page_and_links | E2E | 🟢 passed |
| REQ-208 | 숫자 재계산 | test_det_viz.py::test_req208_recount | E2E | 🟢 passed |
| REQ-209 | 실패 격리 | test_unit_detviz.py::test_req209_ok_baseline<br>test_unit_detviz.py::test_req209_absent<br>test_unit_detviz.py::test_req209_build_error<br>test_unit_detviz.py::test_req209_write_error<br>test_unit_detviz.py::test_req209_render_error<br>test_unit_detviz.py::test_req209_rerender_error<br>test_unit_detviz.py::test_req209_stale_removed<br>test_unit_detviz.py::test_req209_missing_viz_key | Int | 🟢 passed |
| REQ-210 | 누출 없음 | test_det_viz.py::test_req210_no_leaks | E2E | 🟢 passed |
| REQ-211 | 화면 동작 | test_det_viz.py::test_req211_browser<br>test_unit_detviz.py::test_req211_hostile_dom<br>test_unit_detviz.py::test_req211_static_rules<br>test_unit_detviz.py::test_req211_no_page_scroll_390 | E2E/Unit | 🟢 passed |
| REQ-212 | 모듈 경계 | test_unit_detviz.py::test_req212_source_checksum_unaffected | Unit | 🟢 passed |
| REQ-213 | 결과 결합 | test_unit_detviz.py::test_req213_status_mapping<br>test_det_viz.py::test_req213_passed_matches_summary | Unit/E2E | 🟢 passed |
| REQ-215 | pairwise 케이스 표시 | test_unit_pairwise.py::test_req215_pairwise_cases_in_factors<br>test_det_viz.py::test_req208_recount(pairwise run) | Unit/E2E | 🟢 passed |
| REQ-214 | 문서 갱신 | test_unit_detviz.py::test_req214_docs | Unit | 🟢 passed |

커버리지 대상: REQ-201~215(15건). 제외: 없음. 상태 기준(시각화·pairwise 병합 후): run `20261122-143840Z-b6f9393-manual-0f579dc7`(게시 `_test/det-combined-20261122b/`, det `det-45f35ad4-r1`, pairwise 8케이스 포함), E2E 24 passed(det_viz_e2e 9 + det_pairwise_e2e 8 + det_e2e 7). 매트릭스 커버리지 15/15.
