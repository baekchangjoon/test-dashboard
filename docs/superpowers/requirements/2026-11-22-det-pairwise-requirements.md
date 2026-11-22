# det pairwise(PICT) 요구사항명세

> 출처(design spec): `docs/superpowers/specs/2026-11-22-det-pairwise-design.md`
> 완료 정의: 대상 REQ(Must + 미연기 Should)마다 매트릭스의 검증 테스트가 있고, 모두 통과한다. 상위 REQ-103(LLM 0회)·REQ-105(근거)·REQ-108(통합)은 pict를 쓴 run에서도 다시 green이어야 한다.
> 규약: 상위 요구사항명세 `2026-11-18-test-dashboard-poc-requirements.md` §0(독립 오라클, 자원 정리). REQ-ID는 REQ-301부터(상위 REQ-001~, det REQ-101~, 시각화 REQ-201~).
> 테스트 파일은 `tests/acceptance/` 아래. E2E 마커 `det_pairwise_e2e`. 세션 파일 `work/det-pairwise-session.json`(`TD_DET_PAIRWISE_SESSION_FILE`로 대체 가능),
> 키 `{"runDir", "order3RunDir", "previousCasesDir", "run3BundleDir", "run3RunDir"}`(모두 필수, 없으면 fail. skip 아님).
> `previousCasesDir` = `e2e/generated/petclinic/det/det-da70932c-r1`(보존). E2E 공통 Given: `TD_SITE_PREFIX=_test/det-pairwise-<id>/ pipeline/run-all.sh petclinic --arms base,jqa,owl,det` run(`runDir`)과
> 같은 명령에 `--det-pairwise-order 3`을 붙인 run(`order3RunDir`). 전제: SUT 커밋 `b6f9393`, `pict` 항목이 더해진 `tools.pin.yaml`.
> run3 = 백서 §9의 det 기준 run `20261121-201248Z-b6f9393-manual-9d5ee1f4`(det 단독, 라인 31.1%, 브랜치 37.2%). `run3RunDir`은 그 run 디렉터리, `run3BundleDir`은 그 run의 `S06/bundles/det/`이다.
> `pict` 항목·`pairwise.schema.json`·`pairwise-kinds` fixture·E2E 테스트 파일은 이 작업이 만드는 산출물이다.
> 단위·통합 테스트의 pict는 세션 fixture가 고정 커밋을 `work/` 아래에 빌드한다(실패 시 fail).
> 이름 붙은 fixture: `tests/fixtures/det/{controlled,mutated,petclinic}`, 새로 `tests/fixtures/det/pairwise-kinds/`(후보 출처·종류·고정·부분 평가·enum 전용 엔드포인트 행을 모은 통제 번들).

## 1. 요구사항

### REQ-301 PICT 고정 빌드 (Must, Int+E2E)
- Given: `tools.pin.yaml` `pict.commit = d529bb1535b725c8f29704f183b23dd344895d02`, det가 요청된 run.
- Then: S00이 `work/tools/pict/pict`를 그 커밋에서 빌드하고, `.commit` 스탬프가 `{commit, binarySha256}`이며, 스모크 모델 출력이 내장 기대와 같고, `tools.lock`에 `pict.commit`·`pict.binarySha256`이 있다.
- 스탬프 커밋·바이너리 sha256이 모두 맞으면 다시 빌드하지 않는다(make 호출 0). 바이너리를 바꿔 놓으면(sha 불일치) 다시 빌드한다.

### REQ-302 S00 실패 격리 (Must, Int)
- det 미요청 run의 S00은 pict를 준비하지 않는다(pict 저장소·`pict-src`를 대상으로 한 git 호출 0, make 호출 0; proxy shim이 그 밖의 git은 실제 바이너리로 넘긴다).
- pict 준비는 독립 함수(`pipeline/lib/pict.sh`의 `td_prepare_pict <tools_dir> <out_json>`)로 테스트한다. 준비 실패 3종(pict 대상 git만 실패시키는 proxy shim, make 실패 shim, `TD_PICT_SMOKE_EXPECTED_OVERRIDE`로 스모크 불일치)에서 S00은 passed이고 `tools.lock`에 `pict: null`, `pictFailureReason`(고정 코드 `clone-failed|build-failed|smoke-mismatch`; 상세는 300자 이하·가림 적용으로 `S00/pict.json`에만)이 있다.

### REQ-303 pict 없음 상태 (Must, Int)
- det가 요청됐는데 `tools.lock`이 없거나 `pict` 키가 없거나 `pict: null`인 run에서 det generation은 `degraded`(사유 `pairwise-unavailable`)이고, `cases.json` `unresolved`에 `{source: "tool:pict", reason: "pairwise-unavailable", endpoint: null, rule: "pairwise"}` 1건이 있다.
- `bdd-gen.json` det 레코드 `generator.pict == null`이고, genId가 `det_key(input_hash, pict_tag="none")` 앞 8자로 만든 값과 같다.

### REQ-304 기존 출력 불변 (Must, Unit+E2E)
- 단위: `tests/fixtures/det/petclinic` 입력에서 `derive(bundle)`(disabled)의 `cases.json`·features·glue가 기준 스냅샷과 바이트 동일하다.
- 단위: 같은 번들로 available·unavailable 도출 시 규칙 ≠ pairwise인 `cases[]`·`unresolved[]` 항목이 disabled와 같다(병합으로 늘어난 `sources`만 예외). 위반 케이스의 `pair`도 같다.
  예외: `universe.bySlot.{total, generated, unresolved, deduplicated}`, `byReason`의 새 키 4개, `universe.byRule.pairwise`, `universe.pairwise`, 병합으로 늘어난 `sources`. 불변: 규칙 ≠ pairwise인 `cases[]`·`unresolved[]` 항목, `universe.theoretical`, `byRule`의 기존 키.
- E2E 입력 동일성(선행 단언): `runDir/S06/bundles/det/`의 `harness.json` 외 파일 sha256이 `run3BundleDir`과 같고, `harness.json`은 `pairwiseOrder` 키를 뺀 정규화 JSON이 같다. `run.json` SUT 커밋이 `b6f9393`으로 시작한다.
- E2E: 실제 run에서 규칙 ≠ pairwise 케이스가 `previousCasesDir`의 80개와 같다(같은 예외).

### REQ-305 후보 모델 (Must, Unit)
- pairwise-kinds fixture에서 후보 출처 행마다 기대 후보 목록과 같다: baseline 첫째, 단일 원자 유효 경계, 다원자 유효 경계+위반값(`violations[0]`), enum 상수(상태 전이 필드 제외), 분기 참 값. 후보는 중복 없이 출처 순서대로다.
- 후보 종류 literal·omit·null·uniq·spread의 동치·`holds` 평가·케이스 값 확정이 설계 표와 같다. uniq 후보는 필드당 최대 1개다. `BASE`는 `base(ignore_null=True)`로 바뀐다.
- 필터: 단일 원자 오류 조건이나 `~` 부분 제약을 참으로 만드는 후보가 빠지고 `dropped`에 `{address, reason}`으로 남는다.
- 고정 표 행마다(상태 전이 enum, count 인자, rel 종속, 저장 상태·미해결만, 후보 1개) 모델에서 빠지고 고정값을 쓴다.
- petclinic(Given: `priceTier`가 `state_fields`에 없음) POST /api/reservations에서 `priceTier`·`loyaltyPoints`가 모델 필드이고 loyaltyPoints 후보에 499가 있다. `roomNumber`(count 인자)는 고정이다.
- 후보 하한(독립 근거): 같은 엔드포인트의 기존 valid-boundary 케이스가 모델 필드에 쓴 값, 그 필드의 enum 상수(상태 전이 제외)는 모두 그 필드 후보에 있다(`cases.json`에서 확인).

### REQ-306 배제 조합 (Must, Unit)
- 부분 평가: 고정 원자식이 거짓이면 배제 없음. 남은 모델 원자식이 0개면 `pairwise-infeasible`, 1개면 해당 후보 제거와 `dropped` `{address, reason: "reduced-single-atom"}`, 2개 이상이면 `IF ... THEN [p] <> "v";` 배제. 판단 불가 고정 원자식은 참으로 본다. 행마다 pairwise-kinds fixture.
- petclinic에서 `priceTier=VIP` ∧ `loyaltyPoints=499` 라벨 조합이 배제된다.
- 배제 정당성(독립 평가): 각 배제 줄의 값 조합이 어떤 오류 논리곱을 참으로 만드는지 테스트 자체 평가기로 확인한다(과잉 배제 0건).
- `holds`가 None인 조합은 배제되지 않고, 그 조합을 담은 케이스 `assumes`에 `undetermined:<addr>`가 붙는다.

### REQ-307 PICT 실행·분류 (Must, Unit+Int)
- 모델 필드 0~1개 → PICT 호출 없음, `skipped: "fields<2"`, 슬롯 없음. 필드 수 < order → `effectiveOrder` = 필드 수.
- rc=5 → `pairwise-infeasible` 1건. rc=0이지만 출력 계약 위반(빈 출력, 잘린 행, 알 수 없는 라벨, 헤더 불일치, 중복 열; 가짜 pict로 주입), 그 밖 rc, 실행 시작 실패 → det generation failed, 스냅샷 없음, 사유에 rc·stderr 첫 줄(가림 적용).
- 크기 상한 초과(후보 > 12, 파라미터 > 24, 배제 > 20,000) → `pairwise-too-large` 1건, PICT 미호출.
- 시간 초과(Int): `TD_DET_PICT_TIMEOUT=1`과 sleep하는 가짜 pict로 det generation이 failed, `dir` null, 스냅샷 디렉터리 없음. 다른 arm은 계속된다.
- PICT 호출 인자는 정확히 `[model, "/o:<effectiveOrder>"]`이다(가짜 pict가 argv를 기록, `/r` 없음). 모델 파일에 필드명·후보 값 문자열이 없다(`p<i>`/`v<j>`만). 정상·rc≠0·시간 초과·예외 경로 모두에서 `work/` 아래 임시 디렉터리 잔존 0.

### REQ-308 pairwise 케이스 (Must, Unit)
- 케이스: 규칙 `pairwise`, 기대 `{strict: "2xx", class: "2xx", source: "rule"}`, oracle `status`, `sources`는 번들 주소만(상위 REQ-105 검증기 통과), 케이스 키 `pairwise: {order, labels}`. 값 `transform`은 후보의 것을 그대로 둔다.
- 정렬상 pairwise 초안은 기존 초안 뒤다. 라벨이 모두 v0(= baseline)인 행은 같은 엔드포인트의 baseline-valid(없으면 happy) 케이스로 병합한다(라벨 기준, `mergedInto`에 그 id). v0는 baseline 값이고 고정 필드도 baseline이라 요청이 같다는 전제이며, uniq·spread 자리표시는 케이스 id로만 달라진다(`test_req308_label_merge_premise`로 확인). 병합 행에 행 가정이 있으면 `pairwise.json` `rows[].assumes`에 남는다(`test_req308_merged_row_assumes_recorded`). 병합 대상이 없으면 pairwise 케이스로 남는다(pairwise-kinds의 enum 전용 엔드포인트로 확인).
- rel 상대편 필드가 baseline이 아닌 케이스 `assumes`에 `rel-combined:<addr>`, 종속 필드의 기존 가정이 실린다.
- `pairwise-row-invalid`는 controlled·mutated·petclinic·pairwise-kinds에서 0건이다.
- `REASONS`·`_REASON_PRIORITY` 끝에 새 사유 4개(`pairwise-unavailable, pairwise-too-large, pairwise-infeasible, pairwise-row-invalid`)가 이 순서로 있고, unavailable·available의 `byReason`에 나온다. 기존 테스트 중 갱신 대상: `test_unit_detgen.py`의 케이스 키 집합 검사(`pairwise` 선택 키 허용), det 키 기대식.

### REQ-309 실현 가능 상호작용 커버리지(독립 오라클) (Must, Unit+E2E)
- 테스트가 `pairwise.json`의 params·candidates·fixed·exclusions만 읽어 배제를 모두 만족하는 전체 행이 존재하는 order-way 값 튜플을 전수 탐색한다.
- 그 튜플이 모두 pairwise 케이스(또는 `mergedInto` 케이스)의 `cases.json` 값에서 나타난다(literal 값 일치, omit 필드 부재, null, uniq `uniq:` 접두, spread 범위 안·경계 밖). 커버율 100%.
- 반공허: petclinic POST /api/reservations의 실현 가능 2-way 튜플 수 > 0이고, 오라클 수가 `universe.pairwise.byEndpoint[*].interactionsFeasible`·`interactionsCovered`와 같다(엔드포인트별·합계).
- 단위: petclinic. E2E: `runDir`(order 2).

### REQ-310 오류 조건 회피(독립 평가) (Must, Unit+E2E)
- 번들 `plans.json`의 오류 항목(기대가 예외인 항목) 조건식 원문을 테스트 내 최소 평가기(지원: `<`, `<=`, `>`, `>=`, `==`, `!=`, `== null`, `!= null`, `&&`, `||`, 요청 필드·정수·enum 상수·`ext.json` 상수)로 `cases.json` 확정 값에 대해 평가한다.
- pairwise 케이스 어느 것도 평가 가능한 오류 조건을 참으로 만들지 않는다. 평가한 조건 수 ≥ 1이고 VIP×포인트 조건을 포함하며, 평가하지 못한 조건은 목록으로 단언에 남긴다.

### REQ-311 결정성 (Must, Unit)
- 같은 번들·같은 pict로 서로 다른 경로에서 두 번 생성하면 `cases.json`·`pairwise.json`이 바이트 동일하다.
- det 키가 `pict_tag`(`none` vs `commit:sha`)에 따라 다르다.

### REQ-312 실행 직전 무결성 (Must, Int)
- `tools.lock` `binarySha256`과 실제 바이너리 sha256이 다르면 det generation이 failed(사유 기록), 스냅샷 없음, 다른 arm 계속.

### REQ-313 order 옵션 (Must, Int)
- `run-all --det-pairwise-order 3` → det 번들 `harness.json` `pairwiseOrder == 3`, 입력 해시가 order 2와 다르다. 2·3 밖 값이면 run 디렉터리를 예약하기 전에 0이 아닌 종료 코드로 끝난다.

### REQ-314 보고·스키마 (Must, Unit+E2E)
- `pairwise.json`이 `pairwise.schema.json`을 통과하고 `_COMPLETE` 체크섬 목록에 있다. `universe.pairwise`가 있다.
- `compare.schema.json` `detSummary`에 필수 속성 `pairwise: object | null`을 더한다. compare det 블록: `summary.byRule.pairwise{generated, passedStrict}`와 `summary.pairwise{order, interactionsFeasible, interactionsCovered, undetermined, relCombined}`가 있고 `compare.schema.json`을 통과한다(disabled면 `pairwise: null`).
  교차 검증: `undetermined`·`relCombined` = 해당 `assumes` 접두를 가진 pairwise 케이스 수, `interactions*` = REQ-309 오라클 값.
- `compare.html` det 표에 `pairwise` 텍스트 행과 `interactionsCovered/interactionsFeasible` 숫자가 있다. `bdd-gen.json` det 레코드 `generator.pict`가 있고 `bdd-gen.schema.json`을 통과한다.
- E2E(`runDir`): `pairwise-*` 사유 슬롯 4종 모두 0건, `byRule.pairwise.generated ≥ 1`, POST /api/reservations pairwise 케이스 ≥ 1, `interactionsCovered == interactionsFeasible`.

### REQ-315 누출·게시 금지 (Must, Unit+E2E)
- det generation 산출물 전체에 홈·로컬 경로가 없다(`redact.find_leaks == []`). `bdd-gen.json`(게시하지 않는 run 기록, 모든 arm의 generation `dir`을 원래 담음)에는 pict 바이너리 경로가 없다.
- E2E: 게시 미러(`runDir/site`)에 `pairwise.json`이 없다.

### REQ-316 반하드코딩 (Must, Unit)
- mutated fixture로 available 도출 시 원본 SUT 이름이 산출물에 없다. `td/detgen/pairwise.py`에 SUT 리터럴이 없다(상위 REQ-106 검사에 포함).

### REQ-317 커버리지 비교 (Should, Unit/검토)
- `td/detgen/results.py`의 `coverage_comparison(current_run, run3_run) -> dict`: 두 run의 SUT 커밋과 `tools.lock` jacoco 항목이 **하나라도** 다르면 `{"comparable": false, "reason": ...}`, 모두 같으면 det 라인·브랜치와 차이. 단위 테스트로 두 경로를 확인한다.
- 백서 `docs/whitepaper/2026-11-21-test-dashboard-poc-whitepaper.md`에 9.6 뒤에 새 소절 "9.7 pairwise 추가 결과"가 있고(기존 9.1~9.6 번호는 바꾸지 않는다) 표 또는 "비교 불가"와 사유가 적혀 있다(문자열 검사).

### REQ-318 3-way (Should, E2E)
- `order3RunDir`의 `harness.json` `pairwiseOrder == 3`, `pairwise.json` order 3, REQ-309를 3-way로 적용해 커버율 100%. 백서 9.7에 3-way 케이스 수·통과율이 있다(문자열 검사).

### REQ-319 문서 갱신 (Should, Unit)
- README 전제 조건(Xcode CLT `clang++`, `make`)과 `--det-pairwise-order`, 상위 det 설계에 `Pairwise` 상태 모델·번들 외 입력 예외·`pairwise.json`이 적혀 있다(문자열 검사).

## 2. 추적 매트릭스

| REQ-ID | 요약 | 검증 테스트 | 레벨 | 상태 |
|---|---|---|---|---|
| REQ-301 | PICT 고정 빌드 | test_det_pairwise_tool.py::test_req301_s00_builds_pict<br>test_det_pairwise_tool.py::test_req301_stamp_reuse_and_rebuild<br>test_det_pairwise.py::test_req301_tools_lock_real | Int/E2E | 🟢 passed |
| REQ-302 | S00 실패 격리 | test_det_pairwise_tool.py::test_req302_not_requested<br>test_det_pairwise_tool.py::test_req302_prepare_failure (3종 parametrize) | Int | 🟢 passed |
| REQ-303 | pict 없음 상태 | test_det_pairwise_tool.py::test_req303_unavailable_degrades | Int | 🟢 passed |
| REQ-304 | 기존 출력 불변 | test_unit_pairwise.py::test_req304_disabled_identical<br>test_unit_pairwise.py::test_req304_existing_cases_kept<br>test_det_pairwise.py::test_req304_inputs_identical_real<br>test_det_pairwise.py::test_req304_existing_cases_real | Unit/E2E | 🟢 passed |
| REQ-305 | 후보 모델 | test_unit_pairwise.py::test_req305_candidate_sources (행별)<br>test_unit_pairwise.py::test_req305_kinds<br>test_unit_pairwise.py::test_req305_filter_and_fixed<br>test_unit_pairwise.py::test_req305_petclinic_model<br>test_unit_pairwise.py::test_req305_candidate_floor | Unit | 🟢 passed |
| REQ-306 | 배제 조합 | test_unit_pairwise.py::test_req306_partial_evaluation (행별)<br>test_unit_pairwise.py::test_req306_petclinic_vip_exclusion<br>test_unit_pairwise.py::test_req306_exclusions_justified<br>test_unit_pairwise.py::test_req306_undetermined | Unit | 🟢 passed |
| REQ-307 | 실행·분류 | test_unit_pairwise.py::test_req307_field_count<br>test_unit_pairwise.py::test_req307_rc_and_output_contract<br>test_unit_pairwise.py::test_req307_size_caps<br>test_det_pairwise_tool.py::test_req307_timeout_fails<br>test_unit_pairwise.py::test_req307_neutral_model_and_cleanup | Unit/Int | 🟢 passed |
| REQ-308 | pairwise 케이스 | test_unit_pairwise.py::test_req308_case_shape<br>test_unit_pairwise.py::test_req308_order_and_merge<br>test_unit_pairwise.py::test_req308_label_merge_premise<br>test_unit_pairwise.py::test_req308_merged_row_assumes_recorded<br>test_unit_pairwise.py::test_req308_rel_combined<br>test_unit_pairwise.py::test_req308_no_row_invalid<br>test_unit_pairwise.py::test_req308_reasons | Unit | 🟢 passed |
| REQ-309 | 실현 가능 상호작용 | test_unit_pairwise.py::test_req309_feasible_interactions<br>test_det_pairwise.py::test_req309_feasible_interactions_real | Unit/E2E | 🟢 passed |
| REQ-310 | 오류 회피 | test_unit_pairwise.py::test_req310_no_error_condition<br>test_det_pairwise.py::test_req310_real | Unit/E2E | 🟢 passed |
| REQ-311 | 결정성 | test_unit_pairwise.py::test_req311_deterministic<br>test_unit_pairwise.py::test_req311_pict_rows_deterministic<br>test_unit_pairwise.py::test_req311_key_tag | Unit | 🟢 passed |
| REQ-312 | 실행 직전 무결성 | test_det_pairwise_tool.py::test_req312_sha_mismatch | Int | 🟢 passed |
| REQ-313 | order 옵션 | test_det_pairwise_tool.py::test_req313_order_option | Int | 🟢 passed |
| REQ-314 | 보고·스키마 | test_unit_pairwise.py::test_req314_schemas_and_counters<br>test_det_pairwise.py::test_req314_report_real | Unit/E2E | 🟢 passed |
| REQ-315 | 누출·게시 금지 | test_unit_pairwise.py::test_req315_no_leaks<br>test_det_pairwise.py::test_req315_not_published_real | Unit/E2E | 🟢 passed |
| REQ-316 | 반하드코딩 | test_unit_pairwise.py::test_req316_mutated | Unit | 🟢 passed |
| REQ-317 | 커버리지 비교 | test_unit_pairwise.py::test_req317_comparability<br>test_unit_pairwise.py::test_req317_whitepaper | Unit | 🟢 passed |
| REQ-318 | 3-way | test_det_pairwise.py::test_req318_three_way_real<br>test_unit_pairwise.py::test_req318_whitepaper | E2E/Unit | 🟢 passed |
| REQ-319 | 문서 갱신 | test_unit_pairwise.py::test_req319_docs | Unit | 🟢 passed |

커버리지 대상: REQ-301~319(19건). 제외: 없음. 상태 기준: order 2 run `20261122-090040Z-b6f9393-manual-317f39ea`(게시 `_test/det-pairwise-20261122b/`, det `det-db8f978f-r1`), order 3 run `20261122-091719Z-b6f9393-manual-0984b273`(게시 `_test/det-pairwise-o3-20261122b/`, det `det-42c48e40-r1`), E2E 15 passed(det_pairwise_e2e 8 + det_e2e 7), 단위·통합 테스트. 매트릭스 커버리지 19/19.
