# pairwise-kinds fixture (det pairwise Task 3·4, REQ-305·306·307·308)

controlled와 같은 형식의 합성 det 번들이다. 실제 SUT와 무관한 이름(`ex.kit.*`, `/svc/*`)만 쓴다.
테스트는 6개 JSON을 읽어 STAMP를 붙인 번들로 쓴 뒤(`test_unit_detgen._make_bundle`) 계획 해석 단계를 돌려 `pairwise.build_model`을 부른다.
`conditionSha`는 `_make_bundle`이 조건 원문에서 다시 계산한다.

## 엔드포인트

| 엔드포인트 | 본문 | 쓰임 |
|---|---|---|
| `POST /svc/kits` | `KitForm` 10필드 | 후보 출처 5행, 종류 5종, 필터 2종, 고정 5행, 고정 거짓 부분 평가, 판단 불가 조합 |
| `PUT /svc/kits/{kitId}` | `PatchForm`(height, width) | 부분 평가: 고정 원자식 거짓, 1개로 줄어듦, 2개 이상 |
| `PATCH /svc/kits/{kitId}` | `TrimForm`(grade, trim) | 부분 평가: 모델 원자식 0개 → `pairwise-infeasible` |
| `POST /svc/tags` | `TagForm`(grade, shade) | enum 전용 엔드포인트: 오류 조건 없음, baseline-valid 없음, GET이 아니라 happy도 없음(Task 4: 모두-baseline 행이 pairwise 케이스로 남는다) |

선행 생성 요청은 `POST /svc/kits`(응답 `KitView.id`)다. 저장 상태 원자식(`existing.getSize()`)은 그 baseline(`size = 1`)으로 평가한다.

## `POST /svc/kits` 조건(`plans.json` make)

| # | 조건 | 쓰임 |
|---|---|---|
| 0 | `size < 1 \|\| size > 8` | 단일 원자 유효 경계 1·8 |
| 1 | `grade == GOLD && credit < 40` | 다원자: 유효 경계 + 위반값(GOLD, 39), 배제 `GOLD ∧ 39` |
| 2 | `depth > 6 && size > 9` | 필터 (a): 위반값·유효 경계 7·6, 10·9가 #3·#0을 참으로 만들어 빠짐. depth 고정 4로 이 논리곱은 버림(고정 거짓) |
| 3 | `depth > 4` | depth 후보가 4 하나만 남음 → 고정(후보 1개) |
| 4 | `legacy != null` | omit(baseline) · null(유효 경계) 종류 |
| 5 | `"PROMO".equals(code)` (분기) | 분기 참 값 PROMO, code baseline은 uniq |
| 6 | `countBySlot(slot) >= SLOT_LIMIT` | slot은 count 인자 → 고정(spread baseline) |
| 7 | `slot < 10 \|\| slot > 20` | spread 범위 [10, 20], 경계 제외 |
| 8 | `deposit * 1.5 < size * grade.getWeight()` | rel: deposit 종속 → 고정(relation-satisfy), `Con.others = (size, grade)` |
| 9 | `!existing.getPhase().canMoveTo(phase)` | phase는 상태 전이 enum → 고정 |
| 10 | `grade == RUBY && shade == DARK && credit > ledger.cap()` | 미해결 논리곱(`~`): 필터 (b)로 grade RUBY 빠짐, shade는 미해결 원자식만 걸려 고정(baseline LIGHT) |
| 11 | `"VIPKIT".equals(code) && credit < 45` | 판단 불가: uniq ∧ credit<45는 배제하지 않음, VIPKIT ∧ {40, 39, 44}만 배제 |

기대 모델: 파라미터 `p0..p4` = code `[uniq, VIPKIT, PROMO]`, credit `[45, 40, 39, 44]`, grade `[PLAIN, GOLD]`, legacy `[omit, null]`, size `[1, 8]`.
고정: phase(state-field), slot(count-field), deposit(rel-dependent), shade(stored-or-unresolved-only), depth(single-candidate).
배제 4줄: `GOLD ∧ 39`, `VIPKIT ∧ 40`, `VIPKIT ∧ 39`, `VIPKIT ∧ 44`.

## `PUT /svc/kits/{kitId}` 조건(`plans.json` patch)

| # | 조건 | 부분 평가 |
|---|---|---|
| 0 | `existing.getSize() < 5 && width < 3` | 저장 상태 참(1 < 5) → 원자식 1개 → width 2 제거(`reduced-single-atom`) |
| 1 | `existing.getSize() > 7 && height > 3` | 저장 상태 거짓 → 버림(height 4는 배제 없음) |
| 2 | `width > 6 && height > 6` | 원자식 2개 → 배제 `height 7 ∧ width 7` |

기대 모델: height `[3, 4, 6, 7]`, width `[3, 6, 7]`.

## `PATCH /svc/kits/{kitId}` 조건(`plans.json` trim)

`existing.getSize() < 5` 하나만으로 참이 되는 논리곱이 있어 모든 행이 오류다 → `reason = pairwise-infeasible`.
모델 필드는 grade `[omit, PLAIN, GOLD, RUBY]`, trim `[1, 3]` 두 개라 `fields<2`로 건너뛰지 않는다.
