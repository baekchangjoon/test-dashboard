# det 조합 시각화 요구사항명세

> 출처(design spec): `docs/superpowers/specs/2026-11-22-det-combination-viz-design.md`
> 완료 정의: 대상 REQ(Must + 미연기 Should)마다 매트릭스의 검증 테스트가 있고, 모두 통과한다.
> 규약: 상위 요구사항명세 `2026-11-18-test-dashboard-poc-requirements.md` §0을 따른다. REQ-ID는 REQ-201부터 쓴다.

## 1. 요구사항

### REQ-201 factors.json 출력 (Must, Unit+E2E)
- Given: det 번들로 generation을 만든다.
- When: generation 디렉터리를 읽는다.
- Then: `factors.json`이 있고 `factors.schema.json`을 통과한다. 클래스 kind 규칙(count > contradicted > violation > branch > raw)이 fixture에서 기대대로 나온다. 엔드포인트·필드·클래스(유효 포함)·출처·케이스 칸·생성 불가 칸이 들어 있다.

### REQ-202 클래스 수 일치 (Must, Unit+E2E)
- 모든 엔드포인트·필드에서 `len(classes)`가 `cases.json` `universe.theoretical.factors[].fields[field]`와 같다.
- 실제 run에서 POST /api/reservations의 필드 클래스 수는 10개 필드에 대해 4,4,3,3,3,3,3,3,2,2(정렬 시)이고 곱은 46,656이다.

### REQ-203 생성 결과 불변 (Must, E2E)
- 새 generation의 `cases.json`이 이전 스냅샷 `det-da70932c-r1/cases.json`과 바이트 동일하다. feature 파일도 동일하다.

### REQ-204 케이스 칸 기록 (Must, Unit)
- 통제 fixture에서 위반 케이스는 해당 원자식 클래스 칸, 유효 경계 케이스는 `valid` 칸과 `boundaries`, enum-value는 `valid` 칸과 상수 표기, count는 `count` 클래스를 가진다.
- `factors.json` `cases`의 키 집합이 `cases.json` 케이스 id 집합과 같다.
- `inModel`은 규칙으로 정해진다(auth, no-data, empty-body, filter-empty → false, `outReason` 기록. happy를 포함한 나머지 → true).
- 병합된 케이스의 `boundaries`는 합집합이고 `cellConflicts`는 비어 있다.
- 생성 불가 슬롯의 `index`는 `cases.json` `unresolved` 위치와 일치하고, 초안 이전에 건너뛴 슬롯은 `draftKey: null`, `cells: {}`다.

### REQ-205 출처 원문 (Must, Unit)
- `cells`·`classes[].sources`가 가리키는 모든 계획 주소가 `factors.json` `sources`에 있고, 조건식 원문이 번들 `plans.json`/`keyparams.json`의 해당 항목과 같다.
- 출처 문자열에 절대경로가 없다.
- `</script>`를 포함한 조건식 fixture로 만든 `det.html`에서 데이터 script 요소가 깨지지 않는다(`json_for_script` 이스케이프).

### REQ-206 결정성 (Must, Unit)
- 같은 번들로 서로 다른 경로에서 두 번 생성하면 `factors.json`이 바이트 동일하다.

### REQ-207 det.html 생성과 링크 (Must, E2E)
- `run-all --arms base,jqa,owl,det` 실제 run에서 `S12` 산출물에 `det-viz.json`과 `det.html`이 있다.
- `det-viz.json`이 `det-viz.schema.json`을 통과하고, 케이스 80개가 모두 있고 각 케이스에 상태(passed|failed|notRun)가 있다.
- `compare.html` det 블록과 run 페이지 리포트 목록에서 `det.html`로 링크된다. 게시본(`_test/`)에서도 열린다.

### REQ-208 화면 숫자 재계산 일치 (Must, E2E)
- 테스트가 `cases.json`·`factors.json`·S07 결과에서 독립 구현으로 계산한 격자 칸 상태 수(covered-pass, covered-fail, unresolved, empty)와 2-way 덮인 쌍/전체 쌍이 `det-viz.json` 집계와 같다.
- POST /api/reservations의 2-way 전체 쌍 수는 403이다.

### REQ-209 실패 격리 (Must, Int)
- `factors.json`이 없는 generation이면 compare는 성공하고 `det.html`을 만들지 않으며 det 블록에 사유가 표시된다.
- viz 생성 중 예외가 나면 compare는 성공하고(`compare.validate` 통과) `deterministic.viz = {status: failed, reason}`이며 `det.html`이 없다. 다른 arm 결과는 변하지 않는다.
- `factors.json` 없음 → `deterministic.viz.status = absent`, run 페이지에 det 링크 없음.
- 재실행으로 viz가 absent/failed가 되면 이전 `det-viz.json`·`det.html`이 지워진다. `det.html` 렌더 예외(RERENDER 포함)는 `compare.html`을 막지 않는다.

### REQ-210 누출 없음 (Must, E2E)
- 게시 사본의 `det.html`·`det-viz.json`에 대해 `redact.find_leaks` 0건, `check_no_home` 통과.

### REQ-211 화면 동작 (Should, 수동)
- 게시본을 브라우저로 열어 추적 그래프·격자·히트맵이 그려지고 콘솔 오류가 0이다. 라이트/다크, 모바일 폭(390px)에서 가로 페이지 스크롤이 없다.

### REQ-212 문서 갱신 (Should, 검토)
- det 설계 문서에 산출물(`factors.json`, `det.html`) 추가, README의 리포트 목록 갱신.

## 2. 추적 매트릭스

| REQ-ID | 요약 | 검증 테스트 | 레벨 | 상태 |
|---|---|---|---|---|
| REQ-201 | factors.json 출력 | test_unit_detviz.py::test_req201_factors_schema<br>test_det_viz.py::test_req201_factors_real | Unit/E2E | ⚪ |
| REQ-202 | 클래스 수 일치 | test_unit_detviz.py::test_req202_class_counts<br>test_det_viz.py::test_req202_class_counts_real | Unit/E2E | ⚪ |
| REQ-203 | 생성 결과 불변 | test_det_viz.py::test_req203_cases_unchanged | E2E | ⚪ |
| REQ-204 | 케이스 칸 기록 | test_unit_detviz.py::test_req204_cells | Unit | ⚪ |
| REQ-205 | 출처 원문 | test_unit_detviz.py::test_req205_sources | Unit | ⚪ |
| REQ-206 | 결정성 | test_unit_detviz.py::test_req206_deterministic | Unit | ⚪ |
| REQ-207 | det.html 생성·링크 | test_det_viz.py::test_req207_page_and_links | E2E | ⚪ |
| REQ-208 | 숫자 재계산 일치 | test_det_viz.py::test_req208_recount | E2E | ⚪ |
| REQ-209 | 실패 격리 | test_unit_detviz.py::test_req209_isolation | Int | ⚪ |
| REQ-210 | 누출 없음 | test_det_viz.py::test_req210_no_leaks | E2E | ⚪ |
| REQ-211 | 화면 동작 | 수동(브라우저, 결과 보고 첨부) | – | ⚪ |
| REQ-212 | 문서 갱신 | 검토 | – | ⚪ |

커버리지 대상: REQ-201~212(12건). 제외: 없음.
