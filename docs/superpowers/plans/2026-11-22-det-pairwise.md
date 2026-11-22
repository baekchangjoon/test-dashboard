# det pairwise(PICT) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** det arm이 bbtg·jQA에서 얻은 결정적 유효 후보 값으로 PICT 2-way(옵션 3-way) 조합을 만들어 `pairwise` 케이스를 더하고, 실현 가능 상호작용을 100% 덮는다.

**Architecture:** S00이 det 요청 run에서만 PICT를 고정 커밋 소스로 빌드해 `tools.lock`에 기록한다. `td/detgen/pairwise.py`가 후보 모델·배제·PICT 실행·결과 해석을 맡고, `derive`가 `Pairwise` 상태(disabled|unavailable|available)를 받아 기존 케이스 뒤에 pairwise 초안을 더한다. stage가 `tools.lock`을 읽어 상태를 만들고 키에 `pict_tag`를 넣는다. compare·결과·백서가 수치를 보고한다.

**Tech Stack:** Python 3.12(uv, `site-gen`), bash(pipeline), PICT 3.7.4(`make`, clang++), jsonschema, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-det-pairwise-design.md`
**Requirements:** `docs/superpowers/requirements/2026-11-22-det-pairwise-requirements.md`(REQ-301~319)

## Global Constraints

- PICT pin: `microsoft/pict` commit `d529bb1535b725c8f29704f183b23dd344895d02`(tag v3.7.4). brew 바이너리·PATH 탐색 금지, `tools.lock` 경로만 쓴다.
- `derive(bundle)`(disabled)의 `cases.json` 전체는 지금과 바이트 동일. available·unavailable에서도 규칙 ≠ pairwise 항목은 동일(예외: `byReason` 새 키 4개, `universe.pairwise`, 병합으로 늘어난 `sources`).
- PICT `/r` 금지. 모델 파일에는 `p<i>`/`v<j>` 라벨만. 크기 상한: 필드당 후보 ≤ 12, 파라미터 ≤ 24, 배제 줄 ≤ 20,000. 프로세스 상한 120초(`TD_DET_PICT_TIMEOUT`), 초과 시 det failed·스냅샷 없음.
- 새 사유(`REASONS`·`_REASON_PRIORITY` 모두 끝에 이 순서): `pairwise-unavailable`, `pairwise-too-large`, `pairwise-infeasible`, `pairwise-row-invalid`.
- 스냅샷에 남는 pairwise 결과는 모델로 결정되는 것뿐(크기 초과, rc=5, 필드 수 부족). PICT 기타 rc·시작 실패·출력 계약 위반·시간 초과·sha 불일치는 det failed·스냅샷 없음.
- PICT argv는 정확히 `[model, "/o:<effectiveOrder>"]`.
- 상태 결정표(stage): det 미요청 → det 없음 / det 요청 + `tools.lock` 없음 또는 `pict` 키 없음 → **unavailable**(사유 `pict-not-prepared`) / `pict: null` → unavailable(사유 `pictFailureReason` 코드) / `pict: {…}` → sha 대조 후 available. 단위 테스트의 `derive(bundle)`은 disabled.
- order는 번들 `harness.json` `pairwiseOrder` 한 곳에서만 읽는다(기본 2).
- 케이스 출처는 번들 주소만(상위 REQ-105). order·라벨은 케이스 키 `pairwise: {order, labels}`.
- det 키 `pict_tag` = `f"{commit}:{binary_sha256}"` | `"none"`.
- S00의 pict 준비 실패는 S00을 실패시키지 않는다(`pict: null`, `pictFailureReason`).
- 생성기 소스에 SUT 리터럴 금지(상위 REQ-106). pict 경로·홈 경로는 산출물에 쓰지 않는다. `pairwise.json`은 게시하지 않는다.
- 실제 run은 반드시 `TD_SITE_PREFIX=_test/det-pairwise-<id>/` 를 붙인다(운영 게시 금지).
- 세션 fixture `pict_tool`(`tests/acceptance/conftest.py`)이 고정 커밋을 `work/test-tools/pict`에 빌드한다(스탬프 재사용, 실패 시 fail).
- 테스트: `uv run --project site-gen pytest tests/acceptance/<file> -q`. 문서·주석 한국어, 식별자 영어, 커밋 끝 세션 attribution 두 줄.

## Review Focus

- 다원자 조건(VIP ∧ 포인트<500)에서 위반값 후보와 배제가 함께 들어가 499·VIP 조합만 빠지는지(Task 3).
- 고정 필드로 부분 평가했을 때 0·1·2+ 원자식 경우(Task 3).
- pict 없음(unavailable)에서 genId가 available과 겹치지 않고 기존 케이스가 그대로인지(Task 5).
- 정렬·dedupe에서 기존 케이스 id·pair가 바뀌지 않는지(Task 4).
- 시간 초과·sha 불일치에서 스냅샷이 남지 않는지(Task 5).

---

### Task 1: E2E 수용 테스트 먼저(red)

**REQ-IDs:** REQ-301, REQ-304, REQ-309, REQ-310, REQ-314, REQ-315, REQ-318

**Files:**
- Create: `tests/acceptance/test_det_pairwise.py`
- Modify: `tests/acceptance/conftest.py` — 마커 `det_pairwise_e2e`, `DET_PAIRWISE_SESSION_FILE`(`TD_DET_PAIRWISE_SESSION_FILE` 대체), 필수 키 `runDir, order3RunDir, previousCasesDir, run3BundleDir, run3RunDir`, 없으면 `pytest.fail`.

- [ ] **Step 1:** 테스트(모두 `@pytest.mark.det_pairwise_e2e`): `test_req301_tools_lock_real`(runDir `tools.lock` pict commit·binarySha256), `test_req304_inputs_identical_real`(번들 sha·`pairwiseOrder` 뺀 harness 정규화·SUT 커밋), `test_req304_existing_cases_real`(규칙 ≠ pairwise 80개가 `previousCasesDir`과 같음, `sources` 증가만 허용), `test_req309_feasible_interactions_real`(독립 전수 탐색, 커버율 100%, `universe.pairwise` 수와 일치), `test_req310_real`(테스트 내 최소 평가기로 `plans.json` 오류 조건 평가, 지원 연산자 목록 명시, 평가 수 ≥ 1·VIP 조건 포함, 미평가 목록 기록), `test_req314_report_real`(compare det 블록·스키마·`pairwise-*` 슬롯 0·generated ≥ 1·POST ≥ 1·covered == feasible), `test_req315_not_published_real`(`runDir/site`에 pairwise.json 없음, 산출물 find_leaks 0), `test_req318_three_way_real`(order3RunDir: harness pairwiseOrder 3, pairwise.json order 3, 3-way 오라클 100%).
  독립 오라클·평가기는 `td.detgen` 모듈을 import하지 않는다(테스트 안 구현).
- [ ] **Step 2:** 실행 → 세션 파일 없음으로 FAIL(정상). **Step 3:** Commit `test(det-pairwise): E2E acceptance tests (red)`.

### Task 2: PICT 준비 함수·S00·tools.lock

**REQ-IDs:** REQ-301, REQ-302

**Files:**
- Modify: `tools.pin.yaml`(`pict: {repo: microsoft/pict, commit: d529bb1535b725c8f29704f183b23dd344895d02, tag: v3.7.4}`)
- Modify: `pipeline/lib/common.sh` — `fetch_git_tool`을 `S00-prepare.sh`에서 옮긴다(S00은 그대로 호출).
- Modify: `tests/acceptance/conftest.py` — 세션 fixture `pict_tool`(고정 커밋을 `work/test-tools/pict`에 `td_prepare_pict`로 빌드, 스탬프 재사용, 실패 시 fail)을 이 Task에서 만든다.
- Create: `pipeline/lib/pict.sh`(`common.sh`를 source) — `td_prepare_pict <tools_dir> <out_json>`: `fetch_git_tool "<tools_dir>/pict-src" https microsoft/pict <commit>` → 스탬프(`<tools_dir>/pict/.commit` = `{commit, binarySha256}`) 검사: 커밋·sha 일치면 재사용 → 아니면 `git -C pict-src clean -fdx` + `td_run 300 -- make -j4` → `<tools_dir>/pict/pict` → 스모크(`td_py -m td.prepare pict-smoke <bin>`) → 스탬프 기록. 결과 JSON: 성공 `{commit, binarySha256, path}` | 실패 `{failure: "clone-failed|build-failed|smoke-mismatch", detail}`. 실패해도 종료 코드 0.
- Modify: `pipeline/S00-prepare.sh` — `td_arm_requested det`일 때만 `td_prepare_pict "${TD_PICT_TOOLS_DIR:-$TD_WORK_DIR/tools}" "$TD_RUN_DIR/S00/pict.json"`, 경고 출력. write-lock에 `--pict-json`(파일 있을 때).
- Modify: `site-gen/td/prepare.py` — `load_pin()`이 `pict.commit` 40자 hex를 검증(tia·bbtg와 같은 규칙); `pict-smoke <bin>` 서브커맨드(상수 `PICT_SMOKE_MODEL`, `PICT_SMOKE_EXPECTED`; `TD_PICT_SMOKE_EXPECTED_OVERRIDE`가 있으면 그 값으로 비교 — 테스트 전용), `build_lock`·`write-lock`의 `--pict-json`: 성공 → `pict: {commit, binarySha256, path}`, 실패 → `pict: null`, `pictFailureReason: <코드>`(상세는 `S00/pict.json`에만, lock은 고정 코드라 재실행 불변 비교가 흔들리지 않는다), 미요청 → `pict` 키 없음. 같은 run 재실행에서 pict 상태가 바뀌면 기존 lock을 유지하고 경고.
- Test: `tests/acceptance/test_det_pairwise_tool.py` — `td_prepare_pict`를 임시 `tools_dir`로 bash에서 직접 호출. git proxy shim(PATH 앞): 인자에 `microsoft/pict` 또는 `pict-src`가 있으면 기록(실패 모드면 rc 1), 아니면 실제 git으로 exec. make shim은 실패 모드에서만 PATH 앞에 둔다.

- [ ] **Step 1:** `test_req301_s00_builds_pict`(실제 clone·make, 스탬프·결과 JSON·스모크; 그리고 `write-lock` 단위로 tools.lock `pict` 확인), `test_req301_stamp_reuse_and_rebuild`(두 번째 호출 make 0회, 바이너리 바꿔치기 후 재빌드), `test_req302_not_requested`(S00 bash의 det 분기를 `td_arm_requested`가 1을 내는 run 디렉터리로 실행 → proxy shim의 pict 대상 기록 0, make 0; S00 전체가 아니라 분기 스니펫만 source해서 실행), `test_req302_prepare_failure`(3종 parametrize → 종료 코드 0, `failure` 코드, `write-lock` 결과 `pict: null`·`pictFailureReason` 코드), `test_unit_tools.py`에 lock 불변 비교 케이스 추가.
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** PASS + `test_unit_tools.py` 통과 → **Step 5:** Commit `feat(det-pairwise): pinned PICT preparation in S00 when det is requested`.

### Task 3: `td/detgen/pairwise.py` 후보·배제·실행

**REQ-IDs:** REQ-305, REQ-306, REQ-307, REQ-311

**Files:**
- Create: `site-gen/td/detgen/pairwise.py`
- Create: `tests/fixtures/det/pairwise-kinds/`(controlled 형식 번들 + README: 후보 출처 5행, 종류 5종, 필터 2종, 고정 5행, 부분 평가 0/1/2+ 원자식, enum 전용 엔드포인트(오류 조건 없음, baseline-valid 없음))
- Test: `tests/acceptance/test_unit_pairwise.py`(세션 fixture `pict_tool`이 `work/test-tools/pict`에 고정 커밋을 빌드; 실패 시 fail)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class PictTool: path: Path; commit: str; binary_sha256: str`
  - `class Pairwise`: `disabled()`, `unavailable(reason: str)`, `available(tool: PictTool, work_dir: Path, timeout: float)`; 속성 `mode`, `tool`, `work_dir`, `timeout`, `reason`
  - `@dataclass class Candidate: label: str; kind: Literal["literal","omit","null","uniq","spread"]; value: Value | object`(기존 `Value`를 그대로 담아 `provenance`·`source`·`transform` 보존; omit은 `OMIT`)
  - `pairwise.json` 직렬화: params `[{param, loc, field, candidates: [{label, kind, value | range: {lo, hi, excluded}, provenance, source, transform}]}]`, exclusions는 구조화 `[{param: label, ...}]`(PICT 줄은 실행 때 렌더)
  - `@dataclass class EndpointModel: params: list[dict]; fixed: dict; dropped: list[dict]; exclusions: list[dict[str, str]]; order: int; effective_order: int; skipped: str | None; reason: str | None`
  - `build_model(ep, cons: Constraints, catalog: Catalog, order: int) -> EndpointModel`(PICT 호출 없음)
  - `run_pict(model: EndpointModel, tool: PictTool, work_dir: Path, timeout: float) -> list[dict[str, str]] | Literal["pairwise-infeasible"]`
  - `class PictFatal(Exception)`(시간 초과·기타 rc·시작 실패·출력 계약 위반; 메시지에 rc·stderr 첫 줄 가림 적용), 상수 `MAX_CANDIDATES = 12`, `MAX_PARAMS = 24`, `MAX_EXCLUSIONS = 20000`
- Modify: `site-gen/td/detgen/constraints.py` — `Con.others: tuple = ()`(rel 상대편 요청 필드), `_relation`이 채움(disabled 출력 불변).
- Consumes: `Constraints.baseline/sides/holds/base`, `Endpoint.error_disjuncts/branch_disjuncts/state_fields/count_fields`, `Field.constants`.

- [ ] **Step 1:** 테스트: `test_req305_candidate_sources`(행별), `test_req305_kinds`, `test_req305_filter_and_fixed`, `test_req305_petclinic_model`(priceTier·loyaltyPoints 모델, 499 후보, roomNumber 고정), `test_req305_candidate_floor`(기존 valid-boundary 값·enum 상수 ⊆ 후보), `test_req306_partial_evaluation`(0/1/2+ 행), `test_req306_petclinic_vip_exclusion`, `test_req306_exclusions_justified`(테스트 자체 평가기), `test_req306_undetermined`(모델 수준: 판단 불가 조합이 배제에 없음; Task 4에서 케이스 `assumes` 단언 추가), `test_req307_field_count`(모델 수준: `skipped`, `effective_order`), `test_req307_rc_and_output_contract`(argv를 기록하는 가짜 pict: argv == [model, "/o:N"]; rc=5 → infeasible; 빈 출력·잘린 행·알 수 없는 라벨·헤더 불일치·중복 열·rc=1 → `PictFatal`), `test_req307_size_caps`(곱 상한 사전 계산: 열거 전에 too-large, 열거는 20,001에서 정지), `test_req307_neutral_model_and_cleanup`, `test_req311_pict_rows_deterministic`(같은 모델 두 번 → 같은 행). 상한 근처 합성 모델(24×12, 배제 수천 줄)의 소요 시간을 한 번 재서 보고서에 적는다(120초 여유 확인).
- [ ] **Step 2:** FAIL → **Step 3:** 구현(설계 §5.2–5.4 표 그대로) → **Step 4:** PASS + `test_unit_detgen.py::test_req106_no_sut_literals` 통과 → **Step 5:** Commit `feat(det-pairwise): candidate model, exclusions and PICT runner`.

### Task 4: derive 통합·`pairwise.json`

**REQ-IDs:** REQ-304, REQ-308, REQ-309, REQ-310, REQ-311, REQ-315, REQ-316

**Files:**
- Modify: `site-gen/td/detgen/derive.py` — `derive(bundle, pairwise=Pairwise.disabled())`; 정렬 키 앞 규칙 우선순위(`pairwise` 1); `_VALID_RULES` 끝에 `pairwise`; 행→초안(`_materialize` 재사용, pairwise 초안의 실패 사유는 종류와 무관하게 `pairwise-row-invalid`), 모두-baseline 판정은 **라벨 기준**(값 비교 아님) → 같은 엔드포인트 baseline-valid → happy → 없음이면 케이스로 남김, `_dedupe`로 흡수된 pairwise 초안은 `rows[].mergedInto = survivor id`, `assumes`의 `undetermined:`·`rel-combined:`; 새 사유; unavailable 슬롯; disabled에서는 새 사유 키·`universe.pairwise` 미출력; `Derivation.pairwise_doc`
- Modify: `site-gen/td/detgen/render.py` — 케이스 키 `pairwise`(있을 때만), `pairwise.json`(available·unavailable일 때) 쓰기
- Create: `site-gen/td/schemas/pairwise.schema.json` — 최상위 `{schema: 1, order: int, endpoints: {<label>: {params, fixed, dropped, exclusions, effectiveOrder, skipped, reason, rows: [{labels, caseId, mergedInto}]}}}`
- Modify: `tests/acceptance/test_unit_detgen.py` — 케이스 키 집합 검사에 선택 키 `pairwise` 허용, `test_reasons_tuple_is_closed`를 16개로 갱신
- Test: `tests/acceptance/test_unit_pairwise.py`

- [ ] **Step 1:** 테스트: `test_req304_disabled_identical`(petclinic → 기준 스냅샷 바이트 동일), `test_req304_existing_cases_kept`(available·unavailable vs disabled 항목 비교, 예외 목록 정확히), `test_req308_case_shape`, `test_req308_order_and_merge`(pairwise-kinds enum 전용 엔드포인트, 라벨 기준 모두-baseline, dedupe 흡수 시 mergedInto, row-invalid 사유 변환), `test_req308_rel_combined`, `test_req308_no_row_invalid`(controlled·mutated·petclinic·pairwise-kinds), `test_req308_reasons`, `test_req309_feasible_interactions`(petclinic; 테스트 자체 전수 탐색, `universe.pairwise`와 일치, POST feasible > 0), `test_req310_no_error_condition`(테스트 내 최소 평가기), `test_req311_deterministic`(경로 두 곳, cases.json·pairwise.json 바이트 동일), `test_req315_no_leaks`(cases.json·pairwise.json; bdd-gen.json 부분은 Task 5), `test_req316_mutated`, candidate transform 보존 단언.
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** PASS + 기존 `test_unit_detgen.py`·`test_det_glue.py` 통과 → **Step 5:** Commit `feat(det-pairwise): pairwise cases in derive and pairwise.json`.

### Task 5: stage·입력·run-all·compare·보고

**REQ-IDs:** REQ-303, REQ-307, REQ-311, REQ-312, REQ-313, REQ-314, REQ-317

**Files:**
- Modify: `site-gen/td/detgen/stage.py` — 순서: `tools.lock` 읽기 → 상태 결정표 → (available이면) 바이너리 sha256 대조, 불일치면 lock 값으로 만든 genId의 failed 레코드(`dir: null`), 재사용 안 함 → `det_key(input_hash, pict_tag)` → 재사용/생성. unavailable → generation `degraded`, 사유는 기존 선택 입력 누락 사유와 `"; "`로 이어 붙임. `PictFatal` → failed·임시 출력 삭제·스냅샷 없음. `_base_record.generator.pict` = `{commit, binarySha256} | null`.
- Modify: `site-gen/td/detgen/inputs.py` — `harness.json`에 `pairwiseOrder`(`TD_DET_PAIRWISE_ORDER`, 기본 2)
- Modify: `pipeline/run-all.sh` — `--det-pairwise-order 2|3`(그 밖이면 예약 전 종료 코드 1), `TD_DET_PAIRWISE_ORDER` export
- Modify: `site-gen/td/schemas/bdd-gen.schema.json`(generator.pict), `site-gen/td/schemas/compare.schema.json`(detSummary 필수 `pairwise: object|null`), `site-gen/td/detgen/results.py`(`summarize`의 pairwise 블록, `coverage_comparison(current_run, run3_run) -> dict`), `site-gen/td/site/templates/compare.html.j2`(pairwise 행·요약)
- Modify(기존 테스트 갱신): `tests/acceptance/test_unit_detgen.py`(`_det_run` 헬퍼가 `pict_tool`로 available `pict` 항목을 가진 `tools.lock`을 쓰게 해 passed 기대 테스트(`test_det_gen_id_and_record_shape`, `test_det_reuse_snapshot`, `test_det_tampered_snapshot_is_failed_not_overwritten`)가 유지됨; `test_det_gen_id_and_record_shape`의 generator dict·키 기대식 `det_key(input_hash, pict_tag)`, harness 키 집합에 `pairwiseOrder`, summarize 테스트의 `pairwise` 키), `tests/acceptance/test_det.py`(`_det_run_dir`의 tools.lock에 pict 항목: 세션 `pict_tool` 사용 → available; REQ-103 기대 상태 passed 유지), `tests/acceptance/test_compare.py`(det 요약 fixture에 `pairwise: null`)
- Test: `tests/acceptance/test_det_pairwise_tool.py`: `test_req303_*`, `test_req307_timeout_fails`, `test_req312_*`, `test_req313_*` / `tests/acceptance/test_unit_pairwise.py`: `test_req311_key_tag`, `test_req314_*`, `test_req317_*`, `test_req315_no_leaks`의 bdd-gen 단언
- summarize 상태별: disabled → `universe.pairwise` 없음·`summary.pairwise: null`; unavailable → `universe.pairwise = {order, byEndpoint: {}}`·`summary.pairwise: null`; available → 값.
- `coverage_comparison`: 비교 키 `sut.commit`, `jacocoCoreEmbedded`, `pjacoco.{version, sha256}`, `jacococli.{version, sha256}`(`path` 제외); 커버리지 값은 각 run의 `S12/compare/compare.json` `arms.det`의 `line`·`branch`. 호출처는 Task 6 백서 작성 절차.

- [ ] **Step 1:** 테스트: `test_req303_unavailable_degrades`(`pict: null`과 `pict` 키 없음 두 경우, 사유 결합 포함), `test_req307_timeout_fails`(`TD_DET_PICT_TIMEOUT=1` + sleep 가짜 pict → failed, dir null, 스냅샷 없음, base arm 계속), `test_req311_key_tag`, `test_req312_sha_mismatch`(기존 스냅샷이 있어도 재사용하지 않음), `test_req313_order_option`(harness pairwiseOrder, 입력 해시 차이, 잘못된 값 종료 코드), `test_req314_schemas_and_counters`(pairwise.json·bdd-gen·compare 스키마, undetermined/relCombined 교차, compare.html 텍스트), `test_req317_comparability`, `test_req317_whitepaper`·`test_req318`의 백서 3-way 문자열 검사는 Task 6.
- [ ] **Step 2:** FAIL → **Step 3:** 구현 → **Step 4:** PASS + `test_det.py`(Int 부분)·`test_compare.py` 단위 부분 → **Step 5:** Commit `feat(det-pairwise): stage, order option, compare and report wiring`.

### Task 6: 실제 run·백서·문서

**REQ-IDs:** REQ-301~REQ-319

**Files:**
- Modify: `docs/whitepaper/2026-11-21-test-dashboard-poc-whitepaper.md`(9.6 뒤 "9.7 pairwise 추가 결과": 케이스 수·통과율·상호작용 커버·라인/브랜치 비교 또는 비교 불가, 3-way 결과)
- Modify: `README.md`(전제 조건 clang++·make, `--det-pairwise-order`), `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md`(Pairwise 상태·번들 외 입력 예외·`pairwise.json`), 요구사항명세 매트릭스
- Test: `test_unit_pairwise.py::test_req317_whitepaper`, `::test_req318_whitepaper`, `::test_req319_docs`
- Add: 새 det 스냅샷 2개(order 2, order 3)

- [ ] **Step 1: 준비** — `/Users/changjoonbaek/test-dashboard-det`(feat/det-arm)의 `work/{infra,site-mirror,suts,tools,fixtures}`와 `infra/local.env`를 이 worktree로 복사(gitignore, 내용 출력 금지). run3(`20261121-201248Z-b6f9393-manual-9d5ee1f4`)과 det 기준 run은 det worktree의 `work/runs/` 아래 절대 경로를 그대로 가리킨다(복사하지 않음). 두 run의 존재·SUT 커밋·`_COMPLETE`를 먼저 확인한다.
- [ ] **Step 2: run** — `TD_SITE_PREFIX=_test/det-pairwise-<YYYYMMDD>/ pipeline/run-all.sh petclinic --arms base,jqa,owl,det` 그리고 같은 명령 `--det-pairwise-order 3`. 각각 종료 코드 0, LLM arm 스냅샷 재사용, SUT 커밋 `b6f9393` 확인.
- [ ] **Step 3: 세션 파일** `work/det-pairwise-session.json` = `{runDir, order3RunDir, previousCasesDir: <abs>/e2e/generated/petclinic/det/det-da70932c-r1, run3BundleDir: <det worktree>/work/runs/<run3>/S06/bundles/det, run3RunDir: <det worktree>/work/runs/<run3>}`; `work/det-session.json` = `{runDir: <order 2 run>, baselineRunDir: <det worktree의 det-session.json baselineRunDir 값>}`.
- [ ] **Step 3b: 백서 초안** — `coverage_comparison(runDir, run3RunDir)` 결과와 3-way 수치로 9.7을 먼저 쓴다(Step 4의 문자열 검사 대상).
- [ ] **Step 4:** `pytest tests/acceptance/test_det_pairwise.py tests/acceptance/test_det.py -m "det_pairwise_e2e or det_e2e" -q` 전부 PASS.
- [ ] **Step 5:** 백서 9.7·README·상위 설계·매트릭스 갱신, `test_req317_whitepaper`·`test_req318_whitepaper`·`test_req319_docs` PASS.
- [ ] **Step 6: 회귀** `uv run --project site-gen pytest tests/acceptance -q -m "not baseline"`(baseline 제외 명시), 이 세션 테스트 라벨 컨테이너·SUT PID 잔존 0. `_test/det-pairwise-*` 게시물은 보존한다(사용자 지침: 게시물은 지우지 않는다).
- [ ] **Step 7:** Commit `docs(det-pairwise): run results, whitepaper 9.7, README and design; add det snapshots`.
