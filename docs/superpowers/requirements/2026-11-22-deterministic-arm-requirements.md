# 결정적 생성 arm(det) 요구사항명세

> 출처(design spec): `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md`
> 완료 정의: 대상 REQ(Must + 미연기 Should)마다 매트릭스의 검증 테스트가 있고, 모두 통과한다.
> 규약: 상위 요구사항명세 `2026-11-18-test-dashboard-poc-requirements.md` §0(검증 테스트 규약, 독립 오라클 원칙, 실행 환경, 자원 정리)을 그대로 따른다. REQ-ID는 상위 명세와 겹치지 않도록 REQ-101부터 쓴다.

## 1. 요구사항

### REQ-101 jQA 보강 파일 (Must, E2E)
- Given: 기준 SUT 커밋에 S03을 실행한다.
- When: `S03/ontology-jqa-ext.json`을 읽는다.
- Then: 다음이 모두 들어 있고, 파일은 `ontology-ext.schema.json`을 통과한다.
  - DTO 필드: `CreateReservationRequest` 10, `UpdateReservationRequest` 2, `ReservationResponse` 12, `LoginRequest` 2
  - enum 상수: `PriceTier` 3, `ReservationStatus` 4
  - 상수: `ROOM_CAPACITY=2`
  - 핸들러→서비스 호출: 6건 이상(boarding 5건, 로그인 1건 포함)
  - 예외 상태: Validation=422, Conflict=409, NotFound=404, BadRequest=400
  - 음성 단정: `EMAIL` 상수와 nightly rate 값은 없다.

### REQ-102 기존 arm 입력 불변 (Must, E2E)
- Given: 보강 전 기준 run(`20261120-125628Z-…`)의 `ontology-jqa.json` sha256, base/jqa/owl 번들 해시, S05 inputHash가 있다.
- When: 보강 후 run을 실행한다.
- Then: 세 값이 모두 같다.

### REQ-103 LLM 호출 0회 (Must, Int)
- Given: S06을 det arm만으로 실행한다. 이때 `claude`와 `llm.sh` 앞에 호출 기록 shim을 둔다.
- When: det 생성이 끝난다.
- Then: shim 호출 수가 0이다.

### REQ-104 결정성 (Must, Unit)
- Given: 같은 det 번들이 있다.
- When: 서로 다른 임시 경로에서 두 번 생성한다.
- Then: 두 generation의 파일 체크섬과 hash8이 같다.

### REQ-105 근거 완전성 (Must, Unit+E2E)
- 모든 시나리오의 `@case` 태그가 `cases.json`에 있다.
- 각 case의 `sources`는 하나 이상이다.
- 각 source 주소 `{file, index, sha256(condition)}`가 번들 파일의 실제 항목과 일치한다.
- 각 값에는 `provenance`가 있다.

### REQ-106 반하드코딩 (Must, Unit)
- 주 기준: 변조 fixture를 쓴다. 임계값, 필드명, enum 이름, 경로를 모두 바꾼 입력으로 생성한다. 그 결과에 원본 SUT의 필드명, 경로, enum 이름이 하나도 없고, 변조값에서 파생한 값만 있어야 한다.
- 보조 기준: `site-gen/td/detgen*`와 `e2e/det-glue` 소스의 식별자와 문자열 리터럴에 SUT 필드명, 클래스명, enum 상수, `/api/` 경로가 없다.

### REQ-107 생성 불가 보고 (Must, Unit+E2E)
- `unresolved`의 모든 항목에 닫힌 목록의 reason 코드가 있다.
- 슬롯 기준으로 규칙 모수 = 생성 + 생성 불가가 성립한다.
- `universe.theoretical`에 `formula`와 `factors`가 있다.
- 작은 fixture에서 손으로 계산한 값과 일치한다.

### REQ-108 파이프라인 통합 (Must, E2E)
- `run-all --arms base,jqa,owl,det`가 S07~S13을 통과한다.
- `compare.json`에 det가 `requestedRepsByArm.det=1`과 입력 체제 표기와 함께 있다.
- verdict는 base, jqa, owl로만 계산된다. det는 `deterministic` 블록에 따로 나온다.
- 대시보드 비교 화면에 det 참고 열이 있다.
- 기존 arm은 스냅샷을 재사용해 LLM 호출이 0회다.

### REQ-109 통제 fixture (Must, Unit)
- 모든 값이 입력에서 해결되는 합성 번들에서 `unresolved`가 0건이다.
- 생성 케이스 목록(규칙, 값, 기대)이 기대 목록과 정확히 같다.

### REQ-110 det 실패 격리 (Must, Int)
- 필수 입력 누락이나 파서 예외가 나면 det arm만 failed이고 사유가 기록된다.
- base arm 처리는 계속된다.
- 선택 입력이 누락되면 det는 degraded이고 `input-missing` 슬롯이 기록된다.

### REQ-111 엔드포인트 대응 (Must, Unit+E2E)
- 기준 입력에서 bbtg 계획 메서드 6개가 각각 정확히 한 엔드포인트에 대응한다.
- fixture에서 대응이 0개이거나 여러 개면 `no-endpoint-mapping`이 된다.

### REQ-112 입력 투영 (Must, Unit)
- det 번들에 `interceptor_sources`가 없다.
- det 번들에 절대경로(`/Users/` 등의 접두)가 없다.
- detgen이 번들 밖 파일을 열려고 하면 예외가 난다.

### REQ-113 규칙 단위 동작 (Must, Unit)
- 연산자 정규화 표(`<`, `<=`, `>`, `>=`, `== null`, `!= null`, length, enum 결합, 날짜, 형식, equals, 상수 count)의 행마다 위반값과 유효 경계가 표와 일치한다.
- 피연산자 분류(요청 필드, 저장 상태, 시계, 상수, 미해결)가 fixture 조건식에서 기대대로 나온다.

### REQ-114 기대 상태 사전 등록 (Must, Unit)
- 예외 경로 case의 `expect.strict`는 그래프에서 도출한 예외 상태와 같다. 그래프에 없으면 bbtg 코드이고, `expect.source`에 출처가 기록된다.
- bbtg 코드와 그래프 상태가 다르면 둘 다 기록된다.
- 결과 보고에서 통과율은 strict와 class 두 기준으로 따로 계산된다.

### REQ-115 baseline 점검 (Must, Unit+E2E)
- 위반 case가 있는 엔드포인트마다(GET 포함) `baseline-valid` case가 1건 있다.
- 결과 집계는 `blocked-by-baseline`과 "검증된 위반"(위반 통과 + 짝 유효 경계 통과 + baseline 통과)을 따로 낸다.

### REQ-116 glue 배치 규약 (Must, Int)
- det generation의 Java 소스는 `glue/support/` 아래에만 있다.
- 컴파일이 성공한다.
- dry-run의 undefined step이 0이다.
- glue 체크섬이 저장소 `e2e/det-glue`와 같다.

### REQ-117 문서 갱신 (Should, 검토)
- 상위 설계(arm 목록·reps), README(`--arms det`), 백서 §5.3 정정과 det 결과 절이 갱신된다.

## 2. 추적 매트릭스

| REQ-ID | 요약 | 검증 테스트 | 레벨 | 상태 |
|---|---|---|---|---|
| REQ-101 | jQA 보강 파일 | test_det.py::test_req101_ext_ontology | E2E | ⚪ |
| REQ-102 | 기존 arm 입력 불변 | test_det.py::test_req102_existing_inputs_unchanged | E2E | ⚪ |
| REQ-103 | LLM 0회 | test_det.py::test_req103_no_llm_calls | Int | ⚪ |
| REQ-104 | 결정성 | test_unit_detgen.py::test_req104_deterministic | Unit | ⚪ |
| REQ-105 | 근거 완전성 | test_unit_detgen.py::test_req105_provenance<br>test_det.py::test_req105_provenance_real | Unit/E2E | ⚪ |
| REQ-106 | 반하드코딩 | test_unit_detgen.py::test_req106_mutated_fixture<br>test_unit_detgen.py::test_req106_no_sut_literals | Unit | ⚪ |
| REQ-107 | 생성 불가 보고 | test_unit_detgen.py::test_req107_universe<br>test_det.py::test_req107_universe_real | Unit/E2E | ⚪ |
| REQ-108 | 파이프라인 통합 | test_det.py::test_req108_pipeline_compare | E2E | ⚪ |
| REQ-109 | 통제 fixture | test_unit_detgen.py::test_req109_controlled_fixture | Unit | ⚪ |
| REQ-110 | 실패 격리 | test_det.py::test_req110_failure_isolated | Int | ⚪ |
| REQ-111 | 엔드포인트 대응 | test_unit_detgen.py::test_req111_mapping<br>test_det.py::test_req111_mapping_real | Unit/E2E | ⚪ |
| REQ-112 | 입력 투영 | test_unit_detgen.py::test_req112_projection | Unit | ⚪ |
| REQ-113 | 규칙 단위 | test_unit_detgen.py::test_req113_* | Unit | ⚪ |
| REQ-114 | 기대 상태 | test_unit_detgen.py::test_req114_expect | Unit | ⚪ |
| REQ-115 | baseline 점검 | test_unit_detgen.py::test_req115_baseline<br>test_det.py::test_req115_baseline_real | Unit/E2E | ⚪ |
| REQ-116 | glue 규약 | test_det.py::test_req116_glue_layout | Int | ⚪ |
| REQ-117 | 문서 갱신 | 검토 | – | ⚪ |

커버리지 대상: REQ-101~117(17건). 제외: 없음.
