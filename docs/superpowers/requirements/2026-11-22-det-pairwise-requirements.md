# det pairwise(PICT) 요구사항명세

> 출처(design spec): `docs/superpowers/specs/2026-11-22-det-pairwise-design.md`
> 완료 정의: 대상 REQ(Must + 미연기 Should)마다 매트릭스의 검증 테스트가 있고, 모두 통과한다.
> 규약: 상위 요구사항명세 `2026-11-18-test-dashboard-poc-requirements.md` §0을 따른다(독립 오라클, 자원 정리). REQ-ID는 REQ-301부터 쓴다(상위는 REQ-001~, det는 REQ-101~, 시각화는 REQ-201~).
> 실제 run 전제(E2E): 기준 SUT 커밋 `b6f9393`, 현재 `tools.pin.yaml`, det 번들 파일이 run3 번들과 sha256 동일(`harness.json`의 `pairwiseOrder` 제외).
> E2E 공통 Given: 컨트롤러가 `TD_SITE_PREFIX=_test/det-pairwise-<id>/ pipeline/run-all.sh petclinic --arms base,jqa,owl,det`을 돌리고
> `work/det-pairwise-session.json`(`TD_DET_PAIRWISE_SESSION_FILE`로 대체 가능)에 `{"runDir", "previousCasesDir", "run3BundleDir", "run3RunDir"}`를 적는다.
> `previousCasesDir` = `e2e/generated/petclinic/det/det-da70932c-r1`(보존). 세션 파일이 없으면 E2E는 fail(skip 아님).

## 1. 요구사항

### REQ-301 PICT 고정 빌드 (Must, Int+E2E)
- Given: `tools.pin.yaml` `pict.commit = d529bb1535b725c8f29704f183b23dd344895d02`.
- When: det가 요청된 run의 S00.
- Then: `work/tools/pict/pict`가 그 커밋에서 빌드되고(`.commit` 스탬프 일치), 스모크 모델 출력이 내장 기대와 같으며, `tools.lock`에 `pict.commit`·`pict.binarySha256`이 있다. 스탬프가 맞으면 다시 빌드하지 않는다.

### REQ-302 S00 실패 격리 (Must, Int)
- det 미요청 run의 S00은 pict를 준비하지 않는다(clone·make 호출 0).
- pict 준비 실패(clone 실패·빌드 실패·스모크 불일치 주입)에서 S00은 passed이고 `tools.lock`에 `pict: null`과 사유가 있다.
- 그 run의 det generation은 기존 케이스만 만들고 `pairwise-unavailable` 슬롯이 1건이며, det 키의 `pict_tag`는 `"none"`이다.

### REQ-303 기존 출력 불변 (Must, Unit+E2E)
- 단위: 같은 번들로 `derive(bundle)`과 `derive(bundle, pict=None)`의 `cases.json`이 바이트 동일하고, `tests/fixtures/det/petclinic` 입력에서 기준 스냅샷과 같다.
- 단위: `pict=tool`로 도출해도 규칙 ≠ pairwise인 케이스의 id·내용이 `pict=None`과 같다(병합으로 늘어난 `sources`만 예외). 위반 케이스의 `pair`도 같다.
- E2E: 실제 run에서 규칙 ≠ pairwise 케이스가 `previousCasesDir`의 80개와 같다(같은 예외).

### REQ-304 후보 모델 (Must, Unit)
- 설계 §5.2 후보 출처 표의 행마다(baseline, 단일 원자 유효 경계, 다원자 유효 경계+위반값, enum, 분기 참 값) fixture에서 기대 후보가 나온다.
- 후보 종류(literal, omit, null, uniq, spread)의 동치·`holds` 평가·케이스 값 확정이 표대로다. `BASE`는 `base(ignore_null=True)`로 바뀐다.
- 필터: 단일 원자 오류 조건이나 `~` 부분 제약을 참으로 만드는 후보는 빠지고 `dropped`에 사유와 함께 남는다.
- 고정 필드 표의 행마다(상태 전이 enum, count 인자, rel 종속, 저장 상태·미해결만, 후보 1개) 모델에서 빠지고 고정값을 쓴다.
- petclinic POST /api/reservations에서 `priceTier`·`loyaltyPoints`가 모두 모델 필드이고 loyaltyPoints 후보에 위반값 499가 있다.

### REQ-305 배제 조합 (Must, Unit)
- 고정 원자식이 거짓인 논리곱은 배제를 만들지 않는다. 모두 참이면 남은 모델 원자식으로 줄인 배제만 만든다.
- 배제는 `IF ... THEN [p] <> "v";` 형식이고, petclinic에서 `priceTier=VIP`(그 후보 라벨) ∧ `loyaltyPoints=499`(그 후보 라벨) 조합이 배제된다.
- `holds`가 None인 조합은 배제하지 않고, 그 조합을 담은 케이스에 `undetermined:<addr>`가 붙는다.

### REQ-306 PICT 실행·분류 (Must, Unit)
- 모델 필드 0~1개 → PICT 호출 없음, `skipped: "fields<2"`, 슬롯 없음.
- 필드 수 < order → `effectiveOrder` = 필드 수로 실행.
- rc=5 → `pairwise-infeasible` 슬롯 1건, 다른 rc·실행 실패 → `pairwise-error` 1건, 크기 상한 초과(후보 > 12, 파라미터 > 24, 배제 > 20,000) → `pairwise-too-large` 1건(PICT 미호출).
- 120초 초과 → det generation failed, 스냅샷 없음.
- `/r` 옵션을 쓰지 않는다. 모델 파일에 필드명·후보 값 문자열이 없다(라벨 `p<i>`/`v<j>`만). 임시 모델 파일은 끝나면 지워진다.

### REQ-307 pairwise 케이스 (Must, Unit)
- 케이스: 규칙 `pairwise`, 기대 `{strict: "2xx", class: "2xx", source: "rule"}`, oracle `status`, 출처에 `pict:<order>-way`, 값 `transform: "pairwise"`, `pairwise: {param: label}`.
- 정렬상 pairwise 초안은 항상 기존 초안 뒤에 온다(기존 케이스가 dedupe 우선). 라벨이 모두 baseline인 행은 케이스가 되지 않고 `mergedInto`에 baseline-valid id가 적힌다.
- `pairwise-row-invalid`는 petclinic·controlled·viz 없는 기존 fixture에서 0건이다.
- REASONS와 `_REASON_PRIORITY`에 새 사유 5개가 설계 순서대로 있고 `universe.bySlot.byReason`에 나온다.

### REQ-308 실현 가능 쌍 커버리지(독립 오라클) (Must, Unit+E2E)
- 테스트가 `pairwise.json`의 params·candidates·fixed·exclusions만 읽어, 배제를 모두 만족하는 전체 행이 존재하는 값 쌍을 전수 탐색한다.
- 그 쌍이 모두 pairwise 케이스(또는 `mergedInto` 케이스)의 `cases.json` 값에서 나타난다(literal 값 일치, omit 필드 부재, null 값 null, uniq `uniq:` 접두, spread 범위 안·경계 밖). 커버율 100%.
- 단위: petclinic fixture. E2E: 실제 run generation.

### REQ-309 오류 조건 회피(독립 평가) (Must, Unit+E2E)
- pairwise 케이스 어느 것도 판단 가능한 오류 논리곱을 참으로 만들지 않는다. 테스트 자체 평가기(`Constraints.holds` 미사용)로 확인한다.

### REQ-310 결정성 (Must, Unit)
- 같은 번들·같은 pict로 서로 다른 경로에서 두 번 생성하면 `cases.json`·`pairwise.json`이 바이트 동일하다.
- det 키가 `pict_tag`에 따라 달라진다(`none` vs `commit:sha`).

### REQ-311 실행 직전 무결성 (Must, Int)
- `tools.lock`의 `binarySha256`과 실제 바이너리 sha256이 다르면 det generation이 failed(사유 기록)이고 스냅샷이 생기지 않는다. 다른 arm은 계속된다.

### REQ-312 order 옵션 (Must, Int)
- `run-all --det-pairwise-order 3`이면 det 번들 `harness.json`의 `pairwiseOrder`가 3이고 입력 해시가 order 2와 다르다. 2·3 밖의 값은 run 디렉터리 예약 전에 `die`.

### REQ-313 보고·스키마 (Must, Unit+E2E)
- `pairwise.json`이 `pairwise.schema.json`을 통과한다. `universe.pairwise`가 있다.
- compare det 블록 `summary.byRule.pairwise`와 `summary.pairwise{order, pairsFeasible, pairsCovered, undetermined, relCombined}`가 있고 `compare.schema.json`을 통과한다(pict 미사용이면 `pairwise: null`).
- `compare.html` det 표에 pairwise 행·요약이 보인다. `bdd-gen.json` det generation 레코드에 `generator.pict`가 있고 `bdd-gen.schema.json`을 통과한다.
- E2E: 실제 run에서 위 항목과 `pairsCovered == pairsFeasible`.

### REQ-314 반하드코딩 (Must, Unit)
- 변조 fixture(상위 REQ-106)로 pict를 써서 생성해도 원본 SUT 이름이 나오지 않는다. `td/detgen/pairwise.py`에 SUT 리터럴이 없다.

### REQ-315 커버리지 비교 보고 (Should, 검토+Unit)
- 백서 `docs/whitepaper/2026-11-21-test-dashboard-poc-whitepaper.md` §9 부록에 run3 대비 라인·브랜치 변화 표가 있다. SUT 커밋과 `tools.lock` jacoco 항목이 run3과 다르면 "비교 불가"와 사유가 있다.
  단위 테스트는 비교 함수가 조건 불일치 시 비교 불가를 내는지 확인한다.

### REQ-316 3-way 보고 (Should, E2E)
- `--det-pairwise-order 3` run에서 3-way 실현 가능 조합 커버율 100%(REQ-308을 3-way로)이고, 케이스 수·통과율을 백서 부록에 적는다.

### REQ-317 문서 갱신 (Should, Unit)
- README 전제 조건(Xcode CLT `clang++`, `make`)과 `--det-pairwise-order`, 상위 det 설계에 `PictTool` 예외·`pairwise.json`이 적혀 있다(문자열 검사).

## 2. 추적 매트릭스

| REQ-ID | 요약 | 검증 테스트 | 레벨 | 상태 |
|---|---|---|---|---|
| REQ-301 | PICT 고정 빌드 | test_det_pairwise_tool.py::test_req301_s00_builds_pict<br>test_det_pairwise.py::test_req301_tools_lock_real | Int/E2E | ⚪ |
| REQ-302 | S00 실패 격리 | test_det_pairwise_tool.py::test_req302_not_requested<br>test_det_pairwise_tool.py::test_req302_build_failure_degrades | Int | ⚪ |
| REQ-303 | 기존 출력 불변 | test_unit_pairwise.py::test_req303_no_pict_identical<br>test_unit_pairwise.py::test_req303_existing_cases_kept<br>test_det_pairwise.py::test_req303_existing_cases_real | Unit/E2E | ⚪ |
| REQ-304 | 후보 모델 | test_unit_pairwise.py::test_req304_candidates (행별)<br>test_unit_pairwise.py::test_req304_kinds<br>test_unit_pairwise.py::test_req304_filter_and_fixed<br>test_unit_pairwise.py::test_req304_petclinic_interaction | Unit | ⚪ |
| REQ-305 | 배제 조합 | test_unit_pairwise.py::test_req305_partial_evaluation<br>test_unit_pairwise.py::test_req305_petclinic_vip_exclusion<br>test_unit_pairwise.py::test_req305_undetermined | Unit | ⚪ |
| REQ-306 | 실행·분류 | test_unit_pairwise.py::test_req306_field_count<br>test_unit_pairwise.py::test_req306_rc_classification<br>test_unit_pairwise.py::test_req306_size_caps<br>test_unit_pairwise.py::test_req306_timeout_fails<br>test_unit_pairwise.py::test_req306_neutral_model | Unit | ⚪ |
| REQ-307 | pairwise 케이스 | test_unit_pairwise.py::test_req307_case_shape<br>test_unit_pairwise.py::test_req307_order_and_merge<br>test_unit_pairwise.py::test_req307_reasons | Unit | ⚪ |
| REQ-308 | 실현 가능 쌍 | test_unit_pairwise.py::test_req308_feasible_pairs<br>test_det_pairwise.py::test_req308_feasible_pairs_real | Unit/E2E | ⚪ |
| REQ-309 | 오류 회피 | test_unit_pairwise.py::test_req309_no_error_conjunction<br>test_det_pairwise.py::test_req309_real | Unit/E2E | ⚪ |
| REQ-310 | 결정성 | test_unit_pairwise.py::test_req310_deterministic<br>test_unit_pairwise.py::test_req310_key_tag | Unit | ⚪ |
| REQ-311 | 실행 직전 무결성 | test_det_pairwise_tool.py::test_req311_sha_mismatch | Int | ⚪ |
| REQ-312 | order 옵션 | test_det_pairwise_tool.py::test_req312_order_option | Int | ⚪ |
| REQ-313 | 보고·스키마 | test_unit_pairwise.py::test_req313_schemas<br>test_det_pairwise.py::test_req313_report_real | Unit/E2E | ⚪ |
| REQ-314 | 반하드코딩 | test_unit_pairwise.py::test_req314_mutated | Unit | ⚪ |
| REQ-315 | 커버리지 비교 | test_unit_pairwise.py::test_req315_comparability<br>검토(백서 부록) | Unit | ⚪ |
| REQ-316 | 3-way 보고 | test_det_pairwise.py::test_req316_three_way_real | E2E | ⚪ |
| REQ-317 | 문서 갱신 | test_unit_pairwise.py::test_req317_docs | Unit | ⚪ |

커버리지 대상: REQ-301~317(17건). 제외: 없음.
