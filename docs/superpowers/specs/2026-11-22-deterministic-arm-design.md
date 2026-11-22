# 결정적 생성 arm(det) 설계

작성일: 2026-11-22 · 상위 문서: `2026-11-18-test-dashboard-poc-design.md` · 백서: `docs/whitepaper/2026-11-21-test-dashboard-poc-whitepaper.md`(이 브랜치에 함께 커밋)

## 1. 의도와 이유

기존 실험(base/jqa/owl arm)은 LLM이 bbtg·온톨로지 번들을 읽고 시나리오를 "약 25–45개" 예산 안에서 만들었다. 결과는 28–43개, 오라클 0/10이었다. 원인 조사에서 두 가지가 드러났다.

- bbtg는 분기 조건식(임계값 포함)을 얻었지만 파이프라인이 A1 판정(Task 16)으로 지웠다.
- jQA 저장소에는 DTO 필드(`CreateReservationRequest` 10개 등), enum 값, 상수값(`ROOM_CAPACITY=2`), 핸들러→서비스 호출, 예외 핸들러가 호출하는 `ResponseEntity` 빌더가 있었지만 질의가 꺼내지 않았다.

사용자의 질문: **bbtg와 온톨로지가 결정적으로 준 값만으로, 생성 개수 제한 없이, 최대 몇 개의 테스트 케이스를 만들 수 있고, 그것이 실제로 통과하고 커버리지를 올리는가.** LLM으로 개수를 늘리는 것은 목적이 아니다(사용자 명시).

## 2. 목표 · 비목표 · 반목표

목표
- G1. 생성 경로에 LLM 호출 0회인 새 arm `det`. 같은 입력이면 바이트 단위로 같은 산출물.
- G2. 케이스마다 근거(입력 항목 주소, 그래프 노드, 규칙)를 기록한다. 모수는 근거의 합계로 설명된다.
- G3. 만들 수 없는 케이스도 reason 코드와 함께 센다. 규칙 모수 = 생성 + 생성 불가.
- G4. 기존 S07(실행)·S08(커버리지)·S12(비교)를 거쳐 base/jqa/owl과 같은 지표를 낸다. 단 det는 입력 체제가 다르므로(조건식 포함, LLM 없음) **참고 열**로 표기하고 사전 등록 판정(verdict) 계산에서 제외한다.
- G5. jQA 보강 질의 결과를 **별도 파일** `S03/ontology-jqa-ext.json`으로 낸다.

비목표
- bbtg 분석 대상 클래스를 넓히지 않는다(사용자 결정 (a)). det는 **현재 run**의 `S02/bbtg/raw`를 읽는다(S02는 평소대로 실행된다).
- 조합 전체(데카르트 곱) 생성. 이론값으로만 보고한다.
- 시나리오 문장의 자연스러움.

반목표(돌아가도 실패로 본다)
- 생성기 안에 SUT 지식 하드코딩(필드명, 클래스명, enum 상수, 경로, 임계값). 값은 입력 파일에서 와야 하고, 생성기는 문법 수준 지식만 가진다. 허용 리터럴은 §5.6의 닫힌 목록뿐이다.
- LLM이 케이스 목록·값·기대 상태에 관여.
- 실행 결과를 보고 기대값을 사후 조정.

## 3. 제약과 입력

### 3.1 입력 허용 목록(det 한정, 닫힌 목록)

1. 현재 run의 bbtg raw
   - `S02/bbtg/raw/stdout/plan-tests-*.json`: `test_cases[]`의 `condition`, `expected`, `branch_value`, `param`, `prefix` (주 원천)
   - `S02/bbtg/raw/artifacts/key-params/*.json`: `parameters[]`의 `name`, `accessor`, `http_name`, `java_type`, `reasons[].{type,detail}`(plan-tests에 없는 조건 보충. `type`으로 `BRANCH_CONDITION`과 잡음(`DB_WHERE`, `ERROR_TRIGGER`)을 가른다)
   - `S02/bbtg/raw/artifacts/inspect-auth/result.json`: `required_headers`만
   - 읽지 않음: `derive-test-data.json`(columns의 `is_nullable`이 전부 true라 정보 없음, 절대경로 포함), `interceptor_sources`(소스 원문)
2. `S03/ontology-jqa.json`(기존) + `S03/ontology-jqa-ext.json`(신규, §5.1)
3. SUT 서술자 `suts/<sut>/sut.yaml`의 `api.include`·`auth` 블록(로그인 엔드포인트, `unauthenticated_status`)과 SUT 타임존(`env/docker-compose.sut.yml`의 `TZ`, 없으면 `td.state.TZ_NAME`). 이는 모든 arm의 하네스가 실행 시점에 이미 쓰는 테스트 인프라 설정이며, `cases.json`에 `harness-config` 출처로 표기한다.

금지: SUT 소스 원문, 기존 IT 원문, 설계 문서, OWL의 LLM 보강분, `oracle.yaml`.

**det 번들(투영)**: S06 det 경로에서 `td.detgen.inputs.project`가 위 목록에서 허용된 필드만 뽑아 `S06/bundles/det/`에 정규화 JSON으로 복사하고 STAMP(파일별 sha256)를 쓴다. 절대경로를 제거한 뒤 redaction 검사를 한다. 기존 `td.bundle`(LLM arm 번들 조립)은 det를 다루지 않는다. `td.detgen`은 이 번들만 읽는다. 원본 raw 경로를 직접 열지 않는다.

**필수/선택과 누락 처리**:
- 필수: `ontology-jqa.json`, `ontology-jqa-ext.json`, plan-tests 1개 이상. 없거나 스키마가 깨지면 det는 failed다.
- 선택: plan-tests 개별 파일, key-params, inspect-auth. 빠지면 해당 슬롯을 `input-missing`으로 기록하고 det는 degraded다.
- S02나 S03이 degraded여도 남은 입력으로 생성하고, 누락분을 사유에 적는다.

A1과의 관계: 상위 설계의 A1은 "LLM 호출의 생성 입력"에 대한 규칙이다. det는 LLM을 부르지 않으므로 A1 적용 대상 밖이다. 다만 조건식을 읽는다는 정보 비대칭을 비교 산출물과 대시보드에 표기한다(G4).

### 3.2 결정성

- 해시: 생성기가 실제로 읽는 필드만 뽑아 키 정렬 JSON으로 정규화한 뒤 sha256(누락 슬롯 목록 `missing`도 포함한다). 절대경로 필드는 읽지도 해시하지도 않는다. hash8 = 정규화 입력 + 생성기 버전 + 생성기 소스 체크섬(`site-gen/td/detgen/*.py`, `generator.sourceChecksum`) + glue 체크섬.
- 실행 시점에 풀리는 값은 기호로 내보낸다. 닫힌 기호 목록: `today±N`(SUT 타임존), `ref:<var>`(선행 요청의 `capture`가 응답 JSON 필드를 담아 둔 변수), `uniq:<caseId>`(케이스 id에서 파생한 고유 문자열, 도메인 제약이 없는 자유 문자열 필드 전용). 범위 제약이 있는 수치 고유값(방 번호 등)은 생성기가 생성 시점에 구체 리터럴로 확정한다(§5.3).
- 정렬은 입력 주소 기준.

## 4. 접근 방식(검토한 안)

| 안 | 내용 | 득실 | 결정 |
|---|---|---|---|
| A. 코드만으로 생성 | 파이썬 생성기가 규칙으로 케이스를 펼치고 Gherkin + 고정 glue로 실행 | 결정적·근거 추적·LLM 0회 / 문장 기계적, 그래프에 없는 값은 생성 불가 | **채택(사용자 선택)** |
| B. 목록은 코드, 문장은 LLM | 코드가 정한 케이스를 LLM이 1:1 렌더 | 문장 자연스러움 / LLM 잡음·비용 | 기각 |
| C. 세기만 함 | 모수·목록만 산출 | 가장 쌈 / 통과·커버리지 미검증 | 기각 |

## 5. 설계

### 5.1 jQA 보강 질의 → `ontology-jqa-ext.json` (G5)

기존 `ontology-jqa.json`, 질의, 스키마, S04, S05 skeleton, td.bundle은 **바꾸지 않는다**(기존 arm 입력과 해시 불변). 새 질의는 `ontology/jqa/queries/ext/` 아래에 두고 S03이 추가로 실행해 별도 파일을 쓴다. 스키마 `site-gen/td/schemas/ontology-ext.schema.json` 신설.

| 항목 | 질의 근거(jQA) | 산출 |
|---|---|---|
| DTO 필드 | DTO 타입 `-[:DECLARES]->(:Field)` 비정적 | `dtos[fqn].fields[{name,type}]` |
| enum 상수 | `:Enum` 타입의 공개 정적 상수(합성 `$VALUES` 제외), SUT 아티팩트 한정 | `enums[fqn].constants[]` |
| 정적 상수값 | 정적 final `(:Field)-[:HAS]->(:Value)` — 바이트코드 ConstantValue라 원시·String만 잡힌다(`Pattern`, enum 생성자 인자는 안 잡힘) | `constants[{owner, name, type, value}]` |
| 핸들러→서비스 | Controller 메서드 `-[:INVOKES]->` Service 메서드 | `calls[{endpoint, service, method}]` |
| 핸들러 파라미터 | `(:Method)-[:HAS]->(:Parameter)`의 index, 타입, 애노테이션(`PathVariable`/`RequestParam`/`RequestBody`)과 값(`defaultValue`, `required`). 이름은 바이트코드에 없으면 null | `endpoints[id].params[]` |
| 예외 → 상태 | `@ExceptionHandler` 메서드가 INVOKES하는 `ResponseEntity` 정적 빌더(`badRequest`=400, `unprocessableEntity`=422, `notFound`=404, `ok`=200, `noContent`=204, `created`=201, `status(HttpStatus.X)`는 READS한 `HttpStatus` 필드) → 기존 Exception 노드의 `handlers`로 예외에 연결 | `exceptions[fqn].status` |
| 응답 DTO | 핸들러 `RETURNS_GENERIC`의 타입 인자 중 DTO | `endpoints[id].responseDto` |

`ResponseEntity`/`HttpStatus` 빌더 이름→코드 표는 Spring 문법 지식이므로 생성기의 허용 리터럴(§5.6)에 둔다.

### 5.2 케이스 도출

**엔드포인트 대응**: bbtg (class, method) → ext `calls`로 핸들러 엔드포인트를 찾는다. 없으면 이름 일치를 보조로 쓰고, 그래도 없으면 `no-endpoint-mapping`.

**항목 주소와 계수 단위**: 입력 항목 주소 = `{file, index, sha256(condition)}`(plan-tests `id`는 중복되므로 쓰지 않는다). 계수 단위는 **슬롯** = (엔드포인트, 원자식, 규칙이 낳는 케이스 하나). 원자식을 파싱하지 못해 슬롯 수를 모르면 항목 1건 = 생성 불가 1건으로 센다. key-params `reasons[].detail`은 정규화 문자열(공백 제거)로 plan-tests와 중복을 제거한 뒤 남는 것만 보충한다.

**피연산자 분류**: 조건식의 각 피연산자를
- 요청 필드(`req.f()`, 파라미터명),
- 저장 상태(`existing.getF()`),
- 시계(`LocalDate.now()`, `LocalDateTime.now()`),
- 상수(그래프 Constant: 같은 클래스 우선, 없으면 전역 유일 이름일 때만),
- 지역 변수·미해결 메서드(그 외)
로 분류한다. 지역 변수나 미해결 메서드가 위반 방향을 정하면 `unresolved-operand`.

**저장 상태**: `existing.getF()`는 같은 이름의 create DTO 필드로 선행 생성 시 설정할 수 있으면 선행 단계로 만든다. 설정할 수 없거나 create 규칙과 모순되면(예: 과거 체크인) `unreachable-state`.

**연산자 정규화와 경계** (정수는 step 1, 실수는 step 0.01, 길이는 0 미만이면 생성 불가):

| 원자식(위반 조건) | 위반 값 | 유효 경계 |
|---|---|---|
| `f < a` | a-step | a |
| `f <= a` | a | a+step |
| `f > b` | b+step | b |
| `f >= b` | b | b-step |
| `f == null` | null (원시 타입이면 `oracle: framework-reject`, 기대 4xx) | baseline 값 |
| `f != null`(위반 조건으로 쓰인 경우) | 값 있음 | null |
| `f.length() <op> k` | 길이 기준 위와 같음, 문자열은 `uniq` 접두 + 채움 | 같음 |
| `f == E.X` 결합 | X | 다른 상수 |
| `!f.isAfter(now)` / `f.isBefore(now)` | today, today-1 / today-1 | today+1 / today |
| `!P.matcher(f).matches()` | 형식 휴리스틱 위반값(§5.6) | 형식 휴리스틱 유효값 |
| `"LIT".equals(f)` | f=LIT | f≠LIT(`uniq`) |
| `count(...) >= C`(C 상수 해석) | 선행 C건 + 1건 | 선행 C-1건 + 1건 |

논리합은 원자식마다, 논리곱은 다른 항을 만족시킨 채 한 항만 뒤집어 펼친다. 피연산자 순서가 뒤집힌 식은 정규화한다.

**기대 상태(사전 등록)**: 케이스마다 둘을 기록한다.
- `expect.strict`: 예외 경로면 ext `exceptions[fqn].status`(그래프 도출). 그래프에 없으면 bbtg `expected`의 코드. 정상 경로는 2xx.
- `expect.class`: 4xx 또는 2xx.
- bbtg 코드와 그래프 상태가 다르면 둘 다 기록한다(`bbtgCode`, `graphStatus`).
- 통과율은 strict와 class 두 기준으로 따로 보고한다.

**특수 항목**:
- `req = null/empty`: 빈 본문 1건, `oracle: framework-reject`, 기대 4xx.
- list의 `no_data`(필터 파라미터): 결과가 비게 되는 필터값 1건, 기대 2xx, `oracle: status-only`.
- `no_data`(id): 존재하지 않는 id 1건, 기대 = 그래프의 NotFound 예외 상태, 없으면 4xx.
- 조건 없는 항목(`General Bad Request` 등): `no-condition`.
- 입력 모순: 단독 오류 항목의 위반값이 같은 필드의 다른 항목 유효 경계를 도달 불가로 만들면(예: `f != null`→오류 대 `f < a || f > b`) 단독 항목 슬롯을 `input-contradiction`으로 둔다.
- 로그인 엔드포인트(`harness.login`)의 유효 계열(2xx 기대) 케이스는 자격 증명이 입력에 없으므로 `input-missing`(원인 credentials)이다.
- 상태코드로 분기 진입을 구별할 수 없는 케이스(예: promo 분기)는 `oracle: status-only`로 표시한다.

**R-AUTH**: `required_headers`에 `Authorization`이 있으면 sut.yaml `api.include`에 드는 REST 엔드포인트 전체에서 `auth.login` 엔드포인트를 뺀 나머지마다, 토큰 없이 호출하는 케이스 1건씩 만든다. 기대는 `auth.unauthenticated_status`이고 근거는 `harness-config`다. 엔드포인트별 보호 범위는 입력에 없다. Security matcher 문자열은 jQA 그래프에 남지 않기 때문이다. 그래서 각 케이스에 `assumes: "보호됨"`을 기록한다. 공개 엔드포인트(예: 로그인 외의 `/api/auth/*`)가 실패하면 "보호 범위 정보 부족"으로 분류한다.

**그래프 전용 케이스(bbtg 계획 없는 엔드포인트, Owner/Pet/Vet 포함)**:
- R-NODATA: `{var}` 경로 변수가 있는 엔드포인트마다 존재하지 않는 id, 기대 4xx.
- R-HAPPY: 본문이 필요 없는 GET만. 본문이 필요한데 DTO 필드가 그래프에 없으면 `no-body-schema`.

**R-ENUMVAL**: enum 타입 요청 필드의 상수마다 유효 요청 1건씩 만든다. 단 그 필드가 조건식에서 미해결 메서드의 인자나 수신자로 쓰이면(예: `canTransitionTo`) 상태 전이 지식이 필요하다. 이 경우 상수별 케이스는 `needs-state-transition`으로 생성하지 않는다.

**R-CONST의 상태 전제**: `count...(..., Status.X) >= C`처럼 특정 상태를 세는 조건은, 선행 생성한 예약이 상태 X가 된다는 근거가 입력에 있을 때만 생성한다. 근거가 없으면 `needs-state-transition`으로 기록한다. 이 SUT에서는 create 직후 상태가 입력에 없다. 동시 요청 경쟁 케이스는 범위 밖으로 두고, 이론 모수에만 항목으로 기록한다.

**파라미터**: 이름이 null인 파라미터는 bbtg key-params `http_name`으로 이름을 얻는다(타입·순서 대응). 못 얻은 필수 파라미터, 또는 기본값으로는 대상 분기에 못 가는 파라미터는 `param-name-unknown`. 예를 들어 delete의 `confirm`은 기본값 false이고 이름이 입력에 없어서 생성 불가로 기록된다.

**선행 응답 id**: 경로 변수명과 같은 이름의 응답 DTO 최상위 필드를 `ref:`로 쓴다. 없으면 관례 규칙으로 `{<x>Id}` 형태의 경로 변수를 응답의 최상위 `id`에 대응한다(허용 리터럴 §5.6). 둘 다 없으면 `no-id-ref`.

### 5.3 유효 기준 요청(baseline)

- 필드 값은 그 필드에 걸린 모든 원자식을 동시에 만족하도록 고른다. enum은 결합 제약이 가장 적은 상수, 같으면 선언 순서상 첫 상수를 쓴다. 다른 상수 케이스(R-ENUMVAL)는 결합 제약(예: VIP면 `loyaltyPoints >= k`)을 만족시킨 해로 만든다.
- 값이 미해결인 관계식(`deposit*1.1 < nights*rate`, rate 미해결)은 만족 방향의 극단값(허용 리터럴 `LARGE_NUMBER`)을 쓰고 `assumes: "rate 유한"`을 기록한다. 위반 쪽은 0을 쓰고 `assumes: "rate>0"`을 기록한다.
- 형식 제약 필드는 §5.6의 형식 휴리스틱으로 채우고 `assumes: format-heuristic`을 기록한다.
- 고유값(방 번호 등 충돌 가능 필드)은 유효 범위 안에서 caseId 해시로 분산하되, 경계값(유효 경계 케이스가 쓰는 값)은 분산 대상에서 뺀다.
- update 계열 boxed/nullable 필드는 최소 요청이다. 대상 필드만 채우고 나머지는 생략한다.
- **baseline 점검 케이스**: 위반 케이스가 하나라도 있는 엔드포인트마다(본문 유무와 무관, GET의 파라미터 위반 포함) 기본 유효 값으로 `baseline-valid` 1건(기대 2xx). 이 케이스가 실패하면 같은 엔드포인트의 위반 케이스 통과는 `blocked-by-baseline`으로 따로 집계한다. "검증된 위반" = 위반 케이스 통과 + 짝 유효 경계 케이스 통과 + baseline 통과.

### 5.4 산출물과 실행 규약

- 위치: `e2e/generated/<sut>/det/det-<hash8>-r1/{features/, glue/support/, cases.json, factors.json, _COMPLETE}`. `factors.json`은 조합 시각화용 팩터·클래스·케이스 칸이다(`2026-11-22-det-combination-viz-design.md`). S12는 이것과 S07 결과를 합쳐 `S12/compare/det-viz.json`·`det.html`을 만든다.
- `features/`: 엔드포인트별 feature 파일. 시나리오 태그 `@case:<id>`. 모든 feature는 `Background:`에 `Given the SUT timezone is "<tz>"`를 둔다(tz는 번들 harness.json). glue는 이 값으로 `today±N`을 풀고 기본 타임존은 두지 않는다(없으면 step 실패).
- `glue/support/`: 저장소 고정 소스 `e2e/det-glue/`를 복사하고 체크섬을 기록한다. feature별 Steps 클래스는 만들지 않는다(중복 step 방지). 이는 `e2e/harness/CONTRACT.md`의 "feature마다 Steps 클래스" 규약에 대한 det 전용 예외이며, `glue/support/` 아래 배치만 허용하는 `td.scenarios.layout_violations`는 그대로 통과한다. 이 예외는 `e2e/det-glue/README.md`에 적는다(CONTRACT.md는 LLM arm 번들에 들어가므로 바꾸지 않는다, REQ-102). 하네스 API(`baseUrl/authed/anonymous`)와 허용 의존성(Cucumber 8.1.0, REST Assured 5.5.1, AssertJ)만 쓴다. `@Before`/`@After`는 쓰지 않는다. 기호 해석(`today±N`은 SUT 타임존, `ref:`, `uniq:`)은 glue가 맡는다.
- S06 det 경로: `td.detgen`이 생성한 뒤 기존 `td.scenarios` 컴파일 확인과 dry-run을 돌린다. undefined step 0과 컴파일 성공일 때만 `_COMPLETE`를 기록한다. 입력 누락, 스키마 불일치, 파서 예외가 나면 det arm은 failed이고 사유를 기록한다. 다른 arm에는 영향이 없다.
- 시나리오 첫 step은 `Given the case "<id>"`이다(Scenario 객체는 훅 없이 얻을 수 없어서 케이스 id를 step으로 넘긴다). glue는 주 요청마다 `DET-STATUS <caseId> <code>`를 표준 출력에 남긴다. 선행 요청의 `uniq:`에는 `#prior<k>` 접미를 붙여 본 요청과 충돌하지 않게 한다.
- `cases.json`(values 키는 `body.`/`query.`/`path.` 접두, `auth`·`setup` 포함): `{cases:[{id, endpoint, rule, sources:[addr], values:{field:{value, provenance: input|derived|generic-sentinel, from?, transform?}}, expect:{strict,class,bbtgCode?,graphStatus?,source}, oracle, assumes[], baselineProof, pair?}], unresolved:[{source, reason}], universe:{bySlot, byRule, theoretical:{value, formula, factors}}}`.
  - `provenance`: `input`은 입력값 그대로, `derived`는 입력값에 경계 연산(±step)을 한 값, `generic-sentinel`은 §5.6 허용 리터럴과 `uniq:` 값이다.
  - `baselineProof`: 이 케이스의 나머지 필드가 만족한다고 본 원자식 목록과 `assumes`.
- 이론 모수: 엔드포인트마다 요청 필드별 동치 클래스 수(유효 1 + 그 필드 원자식의 위반 클래스 수)를 곱해 합한다. 교차 필드 제약과 불가능 조합을 포함하는 **상한**이다. `formula`와 `factors`를 함께 저장한다.
- reps: det는 요청 reps와 무관하게 항상 1이다. run.json과 compare에 `requestedRepsByArm`(예: `{base:3, jqa:3, owl:3, det:1}`)을 기록하고, 화면은 arm별 분모를 쓴다. `--reps`는 det에 적용되지 않는다.
- 스냅샷: 기존 `.reserve` 예약, 임시 디렉터리, 원자적 rename, `_COMPLETE` 검증 프로토콜을 그대로 쓴다. `--regenerate`를 주면 det도 다시 만들고, 기존 스냅샷과 체크섬이 다르면 경고를 기록한다(결정성 위반 신호).

### 5.4.1 Pairwise 확장

pairwise 케이스 생성은 별도 설계 `docs/superpowers/specs/2026-11-22-det-pairwise-design.md`가 정한다. 이 문서에 영향을 주는 점만 적는다.

- `derive`는 `Pairwise` 상태 모델을 받는다. 상태는 `disabled`(기본값, 기존 출력과 동일), `unavailable`(det를 요청했지만 `tools.lock`의 `pict`가 null), `available`(PICT 사용 가능) 세 가지다.
- §3.1의 "detgen은 번들만 읽는다"에 명시적 예외가 하나 있다. stage가 `tools.lock`의 PictTool을 `Pairwise`로 detgen에 넘긴다. 번들 밖 파일을 detgen이 직접 열지는 않는다.
- 생성 디렉터리에 `pairwise.json`을 함께 쓴다.
- det 스냅샷 키에 `pict_tag`가 들어간다. available이면 `<commit>:<binary sha256>`, unavailable이면 `none`이다.

### 5.5 통합 변경 목록

- arm 목록·패턴: `site-gen/td/bundle.py`(ARMS — det 번들 없음, det는 번들 조립 대상에서 제외), `testid.py`, `compare.py`(ARMS_ORDER, DOT_COLORS, 입력 체제 표기; `verdict.judge`에는 base·jqa·owl만 명시적으로 넘기고, det는 별도 `deterministic` 결과 블록으로 보고), `state.py`(ARMS_DEFAULT=base,jqa,owl 기본 유지 / ARMS_KNOWN=+det, `ARM_DEPENDENCIES["det"]=("S03",)` — S02는 모든 arm 공통으로 앞에 붙는다), `scenarios.py`·`tia.py`(genId 정규식), `pipeline/run-all.sh`(arms 검증), `site-gen/td/schemas/bdd-gen.schema.json`(genId 패턴, arm enum, det 분기: LLM 필드 대신 `generator{name,version,glueChecksum,sourceChecksum}`), `site-gen/td/schemas/compare.schema.json`, `e2e/harness/.../TestIds.java`와 `TestIdsTest`, `site.css`(`--arm-det` 토큰).
- 기본 arms는 `base,jqa,owl` 그대로 두고, det는 `--arms`로 명시할 때만 돈다.
- S03: ext 질의 실행과 ext 파일 기록. S04, S05는 변경 없음.
- 문서: 상위 설계(§5, §6.6, §6.12, §13.5의 arm 목록·reps 서술), 요구사항명세(det REQ 추가), README(`--arms det`), 백서 §5.3(DTO 필드 정정)과 det 결과 절.
- 대시보드 디자인 worktree(`feat/dashboard-design`)와 site 템플릿 충돌 가능성이 있다. 이 브랜치는 arm 목록 데이터와 CSS 토큰만 건드린다.

### 5.6 생성기 허용 리터럴(닫힌 목록)

- HTTP 표준: 헤더 이름 `Authorization`, 메서드 이름(GET/POST/PUT/DELETE).
- bbtg 표지: `null/empty`, `no_data`, `code=`, `BRANCH_CONDITION`.
- Java 타입 기본값 표(String/int/long/double/boolean/LocalDate/LocalDateTime, 박싱 타입).
- REST 관례: `POST <parent>`가 `<parent>/{v}` 자원을 만든다(선행 생성 엔드포인트 탐색).
- Spring 문법: `ResponseEntity`/`HttpStatus` 빌더→코드 표, 매핑 애노테이션 이름.
- Java 문법: 비교 연산자, `length()`, `equals`, `isAfter`/`isBefore`, `LocalDate`/`LocalDateTime`의 `now()`와 `plus*`/`minus*`/`atStartOfDay` 연쇄, `matcher().matches()`, `== null`, Spring Data 파생 질의 접두사 `count`.
- bbtg 관례: 저장 상태 수신자 이름 `existing`(bbtg 조건식이 쓰는 이름, §5.2 피연산자 분류).
- 경로 변수 관례: 접미사 `Id`(`{<x>Id}` → 응답 `id`).
- 형식 휴리스틱: 패턴 상수 이름에 `EMAIL` 토큰이 있으면 유효 `uniq@example.com`, 위반 `not-an-email`. 그 외 패턴은 `format-unknown`(생성 불가).
- 수치: `LARGE_NUMBER = 1000000`, step(정수 1, 실수 0.01).

## 6. 결정된 것과 빌더에게 남긴 것

사용자가 정한 것: 범위 (a)(기존 bbtg 분석 범위), jQA 질의 보강 포함, 접근 A. 이후 판단은 작성자 추천으로 진행하라고 위임했다.

작성자 판단:
- 보강분은 별도 파일로 둔다. 기존 arm 입력과 해시가 바뀌지 않는다.
- det rep 1회. 비교에서는 참고 열로 두고 verdict에서 제외한다.
- 기대 상태는 그래프에서 도출한 값을 우선하고, strict와 class를 함께 보고한다.
- sut.yaml `auth`와 타임존은 하네스 설정으로 입력에 허용한다.
- 형식 휴리스틱(EMAIL)과 `LARGE_NUMBER`를 허용 리터럴로 둔다. 이에 의존하는 케이스는 `assumes`로 따로 집계한다.

빌더에게 남긴 것: 파서 구현 방식, glue 스텝 문구, feature 분할, 분산 해시 방식.

## 7. E2E / 수용 테스트

- AT-1 질의 보강: S03을 SUT에 돌리면 `ontology-jqa-ext.json`에 아래가 있다. 음성 단정으로 `EMAIL` 상수와 rate 값은 없다.
  - DTO 필드: `CreateReservationRequest` 10, `UpdateReservationRequest` 2, `ReservationResponse` 12, `LoginRequest` 2
  - enum: `PriceTier` 3, `ReservationStatus` 4
  - 상수: `ROOM_CAPACITY=2`
  - 핸들러→서비스 호출 6건
  - 예외 상태: Validation=422 등 예외 4개의 상태
- AT-2 기존 arm 불변: 보강 후 `ontology-jqa.json`과 base/jqa/owl 번들 해시, S05 inputHash가 기준 run과 같다.
- AT-3 LLM 0회: S06 det 생성 경로에서 `llm.sh`와 claude 호출이 0회다. S06 단독 fixture와 스텁 카운터로 잰다. S00의 도구 확인 호출은 범위 밖이다.
- AT-4 결정성: 같은 입력으로 두 번 생성한 generation 디렉터리 체크섬이 같다. 체크아웃 경로가 달라도 hash8이 같다.
- AT-5 근거 완전성: 모든 `@case`가 `cases.json`에 있고, 각 case의 `sources`가 입력 파일의 실제 항목(주소의 sha256 일치)을 가리킨다.
- AT-6 반하드코딩: (주 기준) 변조 fixture(임계값, 필드명, enum 이름, 경로를 모두 바꾼 입력)를 주면 생성 값과 이름이 따라 바뀌고 원본 값이 하나도 남지 않는다. (보조) 생성기 소스의 식별자와 문자열 리터럴에 SUT 필드명, 클래스명, enum 상수, 경로가 없다.
- AT-7 생성 불가 보고: `unresolved`의 모든 항목에 reason 코드가 있고, 슬롯 기준으로 규칙 모수 = 생성 + 생성 불가.
- AT-8 파이프라인 통합: `run-all --arms base,jqa,owl,det`가 S07~S12를 통과한다. 비교 결과와 대시보드에 det가 입력 체제 표기와 함께 참고 열로 나온다. 기존 arm은 스냅샷 재사용으로 LLM 0회다.
- AT-9 통제 fixture: 모든 값이 입력에서 해결되는 합성 입력(생성기 단위)에서 unresolved 0건이고, 기대 케이스 목록과 정확히 일치한다.
- AT-10 S06 det 실패 처리: 입력 파일 누락이나 파서 예외가 나면 det arm만 failed이고 사유가 기록되며, 다른 arm은 계속 진행한다.
- AT-11 엔드포인트 대응: bbtg 계획 메서드 6개가 각각 정확히 한 엔드포인트에 대응한다. 대응이 0개이거나 여러 개면 `no-endpoint-mapping`이 된다.
- AT-12 입력 투영: det 번들에 금지 필드(`interceptor_sources`, 절대경로)가 없다. detgen이 번들 밖 파일을 열면 실패한다(주입 테스트).
- 각 규칙과 연산자 정규화는 fixture 기반 단위 테스트를 둔다.

완료 정의: 위 AT 전부 green, 요구사항명세 매트릭스 100%, 스위트 종료 후 테스트가 띄운 컨테이너·프로세스 잔존 0, 백서 갱신.

## 8. 위험

- 파서의 지원 문법이 이 SUT에 과적합될 수 있다. AT-6으로 값 하드코딩은 막지만 문법 과적합은 남는다. 그래서 지원 문법 목록을 결과에 공개한다.
- 상태 전제가 필요한 케이스(409 정원, 상태 전이)는 입력에 근거가 없어서 `needs-state-transition`으로 빠진다. 오라클 일부가 구조적으로 생성 불가로 남는 것은 예상된 결과이고, 그 자체를 측정값으로 보고한다.
- bbtg가 잘못 추출한 조건(update `req.nights() != null → 400`)도 그대로 생성한다. 실패하면 bbtg 추출 오류로 분류해 보고한다.
- 자정 전후 실행은 날짜 기호가 흔들릴 수 있다. 재실행 사유로 기록한다.
