# det pairwise(PICT) 설계

> 상위 설계: `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md`(det arm).
> 브랜치: `feat/det-pairwise`(기반 `feat/det-arm` df010de). 시각화 작업(`feat/det-viz`)과 따로 검증한다.
> 경로 표기: `td/…`는 `site-gen/td/…`를 줄여 쓴 것이다.

## 1. 의도

det arm은 지금 단일 결함 원칙으로 케이스를 만든다. 한 케이스는 필드 하나만 위반이나 경계로 바꾸고, 나머지 필드는 baseline 값으로 둔다.
그래서 **유효한 값들끼리의 조합**은 거의 시험하지 않는다. 예를 들어 `priceTier=VIP`와 `loyaltyPoints=500` 경계는 따로따로만 나온다.

사용자 목표는 "bbtg와 온톨로지에서 얻은 결정적인 값만으로 최대한 많이 덮는 것"이다. LLM으로 케이스 수를 늘리는 것이 아니다.
Pairwise(2-way)는 모든 필드 쌍의 모든 값 쌍을 최소 행 수로 덮는다. 같은 결정적 입력에서 커버리지를 넓히는 표준 기법이다.
도구는 사용자가 지정한 Microsoft PICT다.

## 2. 목표 / 비목표 / 반목표

- 목표
  - G1: 엔드포인트마다 필드별 **유효 구간 값**을 입력(bbtg 조건식, jQA 그래프·보강)에서 결정적으로 뽑는다.
  - G2: PICT로 2-way 조합을 만들어 새 규칙 `pairwise` 케이스로 생성한다. 기대 상태는 2xx다.
  - G3: 같은 입력이면 같은 케이스가 나온다(PICT `/r` 미사용, 도구 커밋 고정).
  - G4: 결과 보고에 pairwise 케이스 수, 통과율, 커버리지(라인·브랜치) 변화가 나온다. 3-way는 옵션 run으로 수치만 보고한다.
- 비목표
  - 위반 클래스 조합(이중 결함). 첫 위반에서 거부되면 둘째 위반이 가려지는 마스킹 때문에 판정할 수 없다. 위반은 지금처럼 하나씩만 깬다.
  - 이론 상한 공식 변경(사용자 미결정).
  - 시각화(별도 브랜치).
- 반목표
  - SUT 이름·값을 생성기 소스에 하드코딩(상위 REQ-106 위반).
  - LLM 호출.
  - 기존 80개 케이스의 내용·id가 바뀌는 것(pairwise는 추가만 한다).

## 3. 현재 구조(바뀌는 곳)

- `td/detgen/derive.py`: 계획 항목 → 제약(`Con`) → 초안 → 케이스. `Constraints.sides(ep, con, addr)`가 원자식별 (위반값 목록, 유효 경계값)을 주고,
  `Constraints.baseline(ep)`가 필드별 baseline 값을 준다. 값 출처(`provenance`)는 `input`, `derived`, `generic-sentinel`이다.
- enum 필드는 `Field.constants`가 있고, 상태 전이 필드(`ep.state_fields`)는 구체 상수를 넣으면 `needs-state-transition`이 된다.
- `td/detgen/stage.py`: det 키 = `sha256(input_hash + GENERATOR_VERSION + source_checksum + glue_checksum)`.
- `tools.pin.yaml` + `pipeline/S00-prepare.sh`: 도구를 고정하고 `tools.lock`에 기록한다. git 커밋으로 고정하는 도구(tia, bbtg)는 `fetch_git_tool`로 받는다.

## 4. 접근

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A (선택) | 값 모델은 Python이 만들고 PICT에는 값 라벨(`v0`, `v1`…)과 배제 조합만 넘긴다. 결과 행을 라벨→구체값으로 되돌린다 | 제약 평가를 기존 `Constraints.holds`로 한다(한 곳). PICT 문법에 SUT 문자열이 들어가지 않아 이스케이프 문제 없음 | 배제 조합 수가 필드 쌍 수만큼 늘 수 있다 |
| B | 조건식을 PICT 제약식(`IF [a]="VIP" THEN [b] >= 500`)으로 번역 | 모델이 읽기 쉽다 | 연산자·길이·날짜·rel 번역을 따로 구현해야 하고, 번역 오류가 결과를 바꾼다 |
| C | PICT 대신 Python greedy | 의존성 없음 | 사용자가 PICT를 지정했다 |

A를 고른다. 제약 판정을 기존 평가기 하나로 유지하고, PICT는 순수 조합기로만 쓴다.
PICT 확보는 brew가 아니라 **고정 커밋 소스 빌드**로 한다(`microsoft/pict` `d529bb1535b725c8f29704f183b23dd344895d02` = 태그 v3.7.4).
`make`로 2초 안에 빌드되고, brew 3.7.4 바이너리와 출력이 바이트 동일함을 확인했다. brew 설치본은 쓰지 않는다(이미 설치된 것은 무해).

## 5. 설계

### 5.1 도구 고정(S00)과 연결

- `tools.pin.yaml`: `pict: {repo: microsoft/pict, commit: d529bb1535b725c8f29704f183b23dd344895d02, tag: v3.7.4}`.
- S00은 **det가 요청된 run에서만**(`td_arm_requested det`, S03 보강과 같은 선례) pict를 준비한다.
  `fetch_git_tool`(https)로 `work/tools/pict-src`에 받고 커밋을 확인한 뒤 `td_run 300 -- make -j4`로 빌드해 `work/tools/pict/pict`에 둔다.
  `work/tools/pict/.commit` 스탬프가 고정 커밋과 같고 바이너리가 있으면 다시 빌드하지 않는다. 빌드 후 내장 스모크 모델(3필드, 제약 1개)의
  출력이 내장 기대 행과 같아야 한다.
- 준비 실패(clone·빌드·스모크)는 S00을 실패시키지 않는다. `tools.lock`에 `pict: null`, `pictFailureReason: <가림 적용, 300자 이하>`를 적고 경고만 남긴다(다른 arm 무영향).
- 캐시 무결성: `.commit` 스탬프는 `{commit, binarySha256}`을 담는다. 스탬프 커밋이 pin과 같고 현재 바이너리 sha256이 스탬프 값과 같을 때만 재사용하고, 다르면 소스를 `git clean -fdx` 후 다시 빌드한다.
  플랫폼별 기대 sha256은 pin하지 않는다(로컬 단일 맥 실증 범위; 잔여 위험으로 기록).
  성공하면 `tools.lock`에 `pict: {commit, binarySha256, path}`. 수정 대상: `tools.pin.yaml`, `pipeline/S00-prepare.sh`,
  `td/prepare.py`(`build_lock`/`write-lock` 인자), README 전제 조건(Xcode CLT의 `clang++`, `make`).
- 연결: `stage.generate_det`가 `<run>/tools.lock`에서 pict 항목을 읽고 실행 직전 바이너리 sha256을 다시 대조한 뒤
  `derive(bundle, pict=PictTool(path, commit, sha256))`로 넘긴다. 이것은 상위 설계의 "detgen은 번들만 읽는다"의 **명시적 예외**이며 상위 설계에 주석한다.
- 관계식 상대편 필드: `Con`(rel)에 상대편 요청 필드 튜플 `others`를 더하고 `Constraints._relation`이 상대편 원문에서 요청 필드를 찾아 채운다(`rel-combined` 판정용). disabled 출력에는 영향이 없다.
- order는 번들 `harness.json` `pairwiseOrder` 한 곳에서만 읽는다. `Pairwise.available(tool, work_dir, timeout)`은 도구·임시 위치·시간 상한만 담는다.
  경로는 번들·산출물에 쓰지 않는다(누출 게이트).
- 상태 모델(`td/detgen/pairwise.py`): `PictTool`(frozen dataclass `path: Path, commit: str, binary_sha256: str`)와 세 상태
  `Pairwise.disabled()`(기본값, 단위 테스트·기존 호출), `Pairwise.unavailable(reason)`(det가 요청됐는데 `tools.lock` `pict: null`),
  `Pairwise.available(tool, order)`. `derive(bundle, pairwise: Pairwise = Pairwise.disabled())`.
  - disabled: `cases.json` 전체가 지금과 바이트 동일하다(새 사유 키·`universe.pairwise`를 쓰지 않는다).
  - unavailable: 기존 케이스만 만들고, `unresolved`에 `{source: "tool:pict", reason: "pairwise-unavailable", endpoint: null, rule: "pairwise"}` 1건. generation은 `degraded`(사유 `pairwise-unavailable`).
  - available: pairwise 케이스를 더한다.
  - unavailable·available에서는 `byReason`에 새 사유 5개 키가 생기고 `universe.pairwise`가 생긴다. 그 밖의 `cases[]`·`unresolved[]` 항목(규칙 ≠ pairwise)은 disabled와 같다.
- det 키: `sha256(input_hash + GENERATOR_VERSION + source_checksum + glue_checksum + pict_tag)`이고 `pict_tag`는 available이면 `f"{commit}:{binary_sha256}"`, unavailable이면 문자열 리터럴 `"none"`. 실제 run의 stage는 det가 요청되면 항상 둘 중 하나다.
  pict가 없을 때와 있을 때 genId가 겹치지 않는다. `_base_record.generator`에 `pict: {commit, binarySha256} | null`을 더한다(`bdd-gen.schema.json` 갱신).
- `pict=None`이면 `derive` 출력은 지금과 바이트 동일하다(기존 테스트 불변).

### 5.2 후보 값 모델

엔드포인트의 body·query 필드마다 후보 목록을 만든다. 모든 후보는 기존 경로(`Constraints.baseline`, `Constraints.sides`, `Field.constants`,
분기 진입 값)에서 나온 결정적 값이다.

후보 출처(순서대로 추가하고 같은 후보는 한 번만):

| 출처 | 후보 |
|---|---|
| baseline | 항상 첫 후보 |
| 원자식 하나짜리 오류 조건 | 그 원자식의 유효 경계값(`sides` valid) |
| 원자식 여러 개인 오류 논리곱 | 각 원자식의 유효 경계값 **과 위반값**(`sides` violations[0]). 다른 원자식이 거짓이면 유효하므로 후보가 되고, 모두 참인 조합은 §5.3 배제로 막는다 |
| enum(상태 전이 필드 아님) | 모든 상수 |
| 분기 진입 조건 | 조건 참 값 |

후보 종류와 동치·평가 규칙:

| 종류 | 예 | 동치 판정 | `holds` 평가 | 케이스 값 확정 |
|---|---|---|---|---|
| literal | 1, "VIP", "today+1" | 값 같음 | 그 값 | 그대로 |
| omit | 필드 생략 | omit끼리 같음 | `OMIT` | 보내지 않음 |
| null | 명시 null | null끼리 같음 | None 값 | null |
| uniq | `Uniq` | 기호로 비교: uniq 후보는 필드당 최대 1개이고 서로 같다 | `eqlit`/`neqlit`은 판단 가능(`uniq:<caseId>`는 `uniq:`로 시작하지 않는 리터럴과 같지 않다 → eqlit 거짓, neqlit 참). 길이·형식은 baseline이 이미 만족시킨 형식으로 평가. 그 밖은 판단 불가 | `uniq:<caseId>` |
| spread | `Spread(lo,hi,excluded)` | 같은 범위끼리 같음 | 범위 대표(경계 제외 내부)로 평가 | 기존 `_finalize`와 같이 caseId 해시 |

`BASE` 자리표시는 `base(ignore_null=True)` 값으로 바꿔 넣는다.

후보 필터(생성 직후, 필드 단위): 다음을 참으로 만드는 후보는 버리고 `pairwise.json` `dropped`에 사유와 함께 남긴다.
(a) 원자식 하나짜리 오류 조건, (b) 미해결 논리곱의 부분 제약(`~` 주소) 원자식. baseline과 같은 보수 원칙이다.

모델에서 빼고 고정하는 필드(후보 1개로 취급):

| 필드 | 이유 | 고정값 |
|---|---|---|
| 상태 전이 enum(`ep.state_fields`) | 상태 전이 규칙을 모름 | baseline |
| count 인자 필드(`ep.count_fields`) | 같은 값을 여러 행이 쓰면 누적 건수 충돌 | baseline(Spread) |
| rel 종속 필드(`con.side`) | 관계식 상대편을 계산할 수 없음 | 기존 고정 극단값(`relation-satisfy`) |
| 저장 상태·미해결 원자식만 걸린 필드 | 값을 정할 근거 없음 | baseline |
| 필터 후 후보가 1개인 필드 | 조합할 것이 없음 | 그 후보 |

rel 가정: 종속 필드는 고정 극단값(예: 1,000,000)을 그대로 쓰고 기존 `assumes`(예: `… 유한`)를 케이스에 싣는다.
관계식 상대편에 쓰이는 필드(예: 박 수, 등급)를 조합하면 가정이 약해질 수 있으므로, 그 필드가 baseline이 아닌 행은 `assumes`에
`rel-combined:<addr>`를 더하고 보고에서 따로 센다(§5.5).

파라미터·값 라벨: PICT 모델에는 파라미터 `p<i>`(필드 순서), 값 `v<j>`(후보 순서)만 쓴다. `pairwise.json`에 `{param, loc, field}`와
`{label, kind, value|range, provenance, source}` 역매핑을 둔다. 모델 파일에는 필드명·값이 들어가지 않는다.

### 5.3 배제 조합

- 오류 논리곱마다 먼저 **고정 필드로 부분 평가**한다. 고정 원자식 중 하나라도 거짓이면 그 논리곱은 어떤 행에서도 참이 될 수 없으므로 버린다.
  모두 참이면(또는 고정 원자식이 없으면) 남은 모델 원자식만으로 논리곱을 줄인다. 고정 원자식이 판단 불가면 보수적으로 "참"으로 본다. 단 count(pairwise 행은 선행 건수 0 → 거짓)·rel(고정 극단값과 기존 가정 → 거짓)·저장 상태(선행 생성 요청의 baseline 값으로 평가)는 고정 조건에서 판단 가능하므로 그 값을 쓴다.
- 줄인 논리곱의 필드 후보 데카르트 곱을 열거해, `holds`로 모든 원자식이 참이 되는 조합마다 PICT 제약
  `IF [p0] = "v1" AND [p2] = "v0" THEN [p3] <> "v2";` 한 줄을 쓴다(PICT는 단독 `NOT (...)` 문장을 받지 않는다. 3.7.4에서 확인).
  모델 원자식이 0개로 줄면: 고정 원자식이 모두 판단 가능하게 참이면 모든 행이 오류이므로 `pairwise-infeasible`, 판단 불가가 섞여 있으면 infeasible로 보지 않고 모든 행에 `undetermined:<addr>`를 단다. 1개로 줄면 그 원자식을 참으로 만드는 후보를 필드에서 빼고 `dropped`에 `{address, reason: "reduced-single-atom"}`로 남긴다. 2개 이상이면 배제 줄을 만든다(한 논리곱의 원자식은 서로 다른 필드다. 같은 필드 논리곱은 derive가 이미 `~`로 강등한다 — 코드에 assert).
- `holds`가 None인 조합은 배제하지 않는다. 그 조합을 담은 행은 `assumes`에 `undetermined:<addr>`를 달고 보고에서 따로 센다.
- 잔여 위험: 배제 줄 수 상한은 PICT 실행 시간을 제한하지 않는다. 24×12 모델에 쌍·삼중 배제를 섞은 실측에서 1,944줄이 154초였다(120초 초과 → det failed, 스냅샷 없음). 이번 SUT의 배제는 1~4줄이다.
- 복잡도 상한(결정적): 필드당 후보 ≤ 12, 모델 파라미터 ≤ 24, 엔드포인트당 배제 줄 ≤ 20,000(`Σ_논리곱 Π_필드 후보 수`).
  넘으면 그 엔드포인트는 PICT를 부르지 않고 생성 불가 슬롯 `pairwise-too-large` 1건. 시간이 아니라 크기로 끊으므로 결과가 결정적이다.

### 5.4 생성

- 모델 필드 수 0~1: PICT를 부르지 않는다(슬롯 없음, `pairwise.json`에 `skipped: "fields<2"`).
  모델 필드 수 < order: 유효 order = 필드 수로 낮추고 `pairwise.json` `effectiveOrder`에 기록한다.
- 엔드포인트마다 모델 파일을 `work/` 아래 임시 디렉터리에 쓰고(finally에서 삭제) `pict <model> /o:<effectiveOrder>`를 부른다. `/r`은 쓰지 않는다.
  - rc=0: 출력 계약을 검사한다(헤더 = 모델 파라미터 집합과 정확히 같음, 각 행은 파라미터마다 알려진 후보 라벨 하나, 1행 이상, 중복 열 없음). 위반이면 **det generation failed**(스냅샷 없음). 통과하면 행을 라벨→후보로 되돌린다.
  - rc=5(`Too restrictive constraints`): 생성 불가 슬롯 `pairwise-infeasible` 1건.
  - rc=4(입력 오류, 예: order > 파라미터 수)는 위의 유효 order 조정으로 생기지 않아야 한다. 생기면 생성기 결함이므로 det generation failed(스냅샷 없음).
  - 그 밖의 rc·실행 시작 실패: det generation failed(스냅샷 없음), 사유에 rc와 stderr 첫 줄(가림 적용).
  - 원칙: 스냅샷에 남는 결과는 모델에서 결정적으로 정해지는 것(크기 초과, rc=5, 필드 수 부족)뿐이다. 환경에 따라 달라질 수 있는 실패는 스냅샷으로 고정하지 않는다.
  - 프로세스 상한 120초(안전장치, 테스트용으로 `TD_DET_PICT_TIMEOUT` 초로 바꿀 수 있다). 넘으면 **det generation 전체를 failed로 하고 스냅샷을 만들지 않는다**(시간 의존 결과를 고정하지 않기 위해).
- order: `run-all --det-pairwise-order 2|3`(기본 2, 그 밖이면 `die`). run-all이 `TD_DET_PAIRWISE_ORDER`로 내보내고
  `inputs.project`가 det 번들 `harness.json`의 `pairwiseOrder`로 싣는다(입력 해시에 들어간다).
- 행마다 초안 하나: 규칙 `pairwise`, 기대 `{strict: "2xx", class: "2xx", source: "rule"}`, oracle `status`(오류 조건을 모두 피한 요청의 2xx 단정은
  상태 코드로 판정 가능하다. 분기 진입 값이 섞여도 예외가 없는 분기이므로 같다), 출처 = 모델에 기여한 번들 주소(상위 REQ-105 형식 유지).
  order 정보는 출처가 아니라 케이스 키 `pairwise: {order, labels: {param: label}}`에 둔다. 값의 `transform`은 바꾸지 않는다.
  `pairwise`는 `_VALID_RULES` 끝에 넣는다. 경로 변수·setup은 `_materialize`가 baseline-valid와 같이 채운다.
- 케이스 키 `pairwise`는 `cases.json` 케이스 항목의 새 선택 키다(기존 케이스에는 없음 → 기존 80개 바이트 불변 조건과 충돌하지 않도록,
  `_case_entry`는 pairwise 라벨이 없으면 키 자체를 쓰지 않는다).
- 기존 케이스 우선: 정렬 키 앞에 규칙 우선순위(`pairwise`만 1, 나머지 0)를 둬 pairwise 초안이 항상 뒤에 온다. 따라서 기존 dedupe에서 기존 케이스가 남고
  기존 id·pair는 바뀌지 않는다. 라벨이 모두 baseline인 행은 같은 엔드포인트의 기존 유효 케이스(baseline-valid, 없으면 happy) 중 요청이 같은 것이 있으면 만들지 않고 `rows[].mergedInto`에 그 id를 적는다. 없으면 pairwise 케이스로 남긴다.
- 방어선: `_materialize`가 행을 거부하면(다른 조건 위반) 슬롯 `pairwise-row-invalid`. 기대값은 0건이고 E3·단위 테스트가 0건을 단언한다.
- `REASONS`와 `_REASON_PRIORITY` 끝에 모두 `pairwise-unavailable, pairwise-too-large, pairwise-infeasible, pairwise-row-invalid` 순으로 4개를 더한다. `pairwise-unavailable`은 pict가 없을 때(det가 요청됐는데 `tools.lock` `pict: null`) 엔드포인트와 무관한 슬롯 1건이다.
- 산출물 `pairwise.json`(스키마 `td/schemas/pairwise.schema.json`, 버전 1, `_COMPLETE` 체크섬 대상, 사이트에는 게시하지 않음):
  엔드포인트별 `{params: [{param, loc, field, candidates[]}], fixed: {field: label}, dropped: [...], exclusions: [...], order, effectiveOrder,
  skipped, rows: [{labels, caseId | null, mergedInto | null}]}`.

### 5.5 보고

- `universe.pairwise = {order, byEndpoint: {label: {params, candidates, interactionsTotal, interactionsFeasible, interactionsCovered, rows, cases}}}`. `theoretical`은 바꾸지 않는다.
- 통과율은 기존 `byRule.pairwise`(`generated`, `passedStrict`)를 쓴다. compare det 블록에는 `byRule`에 없는 것만 `pairwise` 객체로 더한다:
  `{order, interactionsFeasible, interactionsCovered, undetermined, relCombined}`(모두 정수, order는 2|3. interactions는 order-way 값 튜플 수,
  undetermined·relCombined는 해당 `assumes` 접두를 하나 이상 가진 pairwise 케이스 수; `detSummary`에 선택이 아닌 필수 속성 `pairwise: object|null`로 추가, pict 미사용이면 null). 수정 대상: `compare.schema.json`(`detSummary`), `compare.html.j2`, `results.summarize`, 관련 테스트.
- 커버리지 변화: 비교 기준은 run3(det 단독, 라인 31.1%, 브랜치 37.2%; 백서 `docs/whitepaper/2026-11-21-test-dashboard-poc-whitepaper.md` §9).
  새 run의 SUT 커밋과 `tools.lock`의 jacoco 항목이 run3과 같을 때만 차이를 적고, 다르면 "비교 불가"로 적는다. pairwise만의 기여는 같은 커밋에서
  pairwise 포함 generation과 run3 generation의 귀속 커버리지 차이로 본다(같은 bbtg·jQA 입력이 전제, E2가 입력 동일성을 확인).

### 5.6 실패 격리 요약

| 상황 | S00 | det generation | 다른 arm |
|---|---|---|---|
| det 미요청 | pict 준비 안 함 | 없음 | 영향 없음 |
| pict 준비 실패 | passed(경고), `pict: null`·`pictFailureReason` | degraded: 기존 케이스만 + `pairwise-unavailable` 1슬롯, 키에 `none` | 영향 없음 |
| 실행 직전 sha256 불일치 | – | failed(사유 기록), 스냅샷 없음 | 영향 없음 |
| PICT rc=5 / 크기 초과 | – | 그 엔드포인트 슬롯 1건, 나머지 정상 | 영향 없음 |
| PICT 기타 rc·시작 실패·출력 계약 위반 | – | failed, 스냅샷 없음 | 영향 없음 |
| PICT 120초 초과 | – | failed, 스냅샷 없음 | 영향 없음 |
| 산출물 누출 방지 | – | pict 경로·홈 경로가 산출물(`cases.json`, `pairwise.json`, `bdd-gen.json`)에 없다(`redact.find_leaks`). `pairwise.json`은 사이트에 게시하지 않는다 | – |

## 6. 수용 테스트(E2E 우선, 이중 루프)

요구사항명세 `docs/superpowers/requirements/2026-11-22-det-pairwise-requirements.md`(REQ-301~, 이 설계 승인 뒤 작성)가 단일 출처다.
완료 정의: 매트릭스 대상 REQ 테스트 전부 통과. 실행 자원 정리는 상위 명세 §0 규약을 따른다.
가장 높은 실행 수준은 실제 run(`TD_SITE_PREFIX=_test/det-pairwise-<id>/ pipeline/run-all.sh petclinic --arms base,jqa,owl,det`)이다.
전제: 기준 SUT 커밋 `b6f9393`, det 번들 파일(`pairwiseOrder` 제외)이 run3 번들과 sha256 동일(E2가 먼저 확인).

- E1: S00이 pict를 고정 커밋으로 빌드하고 `tools.lock`에 커밋·sha256이 있다. det 미요청 run에서는 pict를 준비하지 않는다.
- E2: 새 generation에서 규칙 ≠ pairwise인 케이스가 `det-da70932c-r1`의 80개와 내용·id가 같다(병합으로 늘어난 `sources`만 예외).
  단위 수준에서도 같은 번들로 `pict=None`과 `pict=tool`을 도출해 비교한다.
- E3(독립 오라클): 테스트가 `pairwise.json`의 후보·배제만 읽고, 배제를 모두 만족하는 전체 행이 하나라도 존재하는 값 쌍(실현 가능 쌍)을 전수 탐색한다.
  그 쌍이 모두 pairwise 케이스(또는 `mergedInto` 케이스)의 `cases.json` 값에서 실제로 나타나는지 확인한다(literal은 값 일치, omit은 필드 부재,
  uniq는 `uniq:` 접두, spread는 범위 안·경계 밖). 실현 가능 쌍 커버율 100%. `pairwise-row-invalid` 0건.
- E4: pairwise 케이스 어느 것도 판단 가능한 오류 논리곱을 참으로 만들지 않는다(테스트 자체 평가기, `Constraints.holds` 미사용).
- E5: 결정성 — 같은 번들·같은 pict로 두 번 생성하면 `cases.json`·`pairwise.json` 바이트 동일.
- E6: compare det 블록에 `byRule.pairwise`와 `pairwise` 객체가 있고 `compare.schema.json`을 통과한다. 백서 부록에 커버리지 비교표(또는 "비교 불가"와 사유).
- E7(Should, 별도 run): `--det-pairwise-order 3` run에서 3-way 실현 가능 조합 커버율 100%와 케이스 수·통과율을 보고한다.
- 단위: 후보 출처·종류·필터·고정 표의 행마다, 부분 평가 배제, PICT rc 분류(rc=4 order, rc=5), 필드 수 < order, 크기 상한, 라벨 모델에 필드명·값 없음,
  변조 fixture(상위 REQ-106), pict 없음 → 출력 불변, S00 실패 격리(det 미요청·준비 실패).
  테스트용 pict는 세션 fixture가 고정 커밋을 `work/` 아래에 빌드한다(빌드 실패 시 fail, skip 아님).

## 7. 빌더 재량

- 모델 파일 이름, 후보 정렬 세부(결정적이기만 하면 됨), PICT stderr 가림 형식.
