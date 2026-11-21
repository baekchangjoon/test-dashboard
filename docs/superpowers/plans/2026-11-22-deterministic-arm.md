# 결정적 생성 arm(det) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** bbtg raw와 jQA 그래프(보강분 포함)만으로 LLM 없이 테스트 케이스를 최대한 펼쳐 실행하는 `det` arm을 파이프라인에 추가하고, 모수·생성 수·통과율·커버리지를 기존 arm과 나란히 보고한다.

**Architecture:** S03이 보강 질의 결과를 `ontology-jqa-ext.json`으로 따로 낸다. S06의 det 경로는 허용 필드만 투영한 det 번들을 만든다. 그다음 `td.detgen`(파서 → 도출 → 렌더)이 Gherkin과 `cases.json`을 만들고, 저장소의 고정 glue를 붙여 기존 스냅샷 규약으로 확정한다. S07 이후는 arm 목록 확장만으로 기존 경로를 그대로 쓴다.

**Tech Stack:** Python 3.12(site-gen, uv), pytest, jsonschema, neo4j bolt(jQA 2.9.1), Java 17 + Cucumber 8.1.0 + REST Assured 5.5.1 + AssertJ.

**Spec:** `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md` · 요구사항: `docs/superpowers/requirements/2026-11-22-deterministic-arm-requirements.md`

## Global Constraints

- 생성 경로 LLM 호출 0회. `td.detgen`은 `subprocess`로 `claude`나 `llm.sh`를 부르지 않는다.
- 생성기·glue 소스에 SUT 필드명, 클래스명, enum 상수, `/api/` 경로, 임계값을 쓰지 않는다. 허용 리터럴은 설계 §5.6뿐이다(`ResponseEntity`/`HttpStatus` 빌더→코드 표, Java 연산자·메서드 이름, `EMAIL` 토큰 형식 휴리스틱 `uniq@example.com`/`not-an-email`, `LARGE_NUMBER = 1000000`, step 정수 1·실수 0.01).
- 기존 `ontology-jqa.json`, 기존 질의 파일, `ontology.schema.json`, `td.bundle` 조립, `td.ontology_owl`, S04, S05는 바꾸지 않는다.
- det rep는 항상 1이다. genId는 `det-<hash8>-r1`이다.
- 기본 arms는 `base,jqa,owl` 그대로다. det는 `--arms`에 명시할 때만 돈다.
- det 번들과 산출물에 절대경로(`/Users/`, `/home/`, `/private/var/`, `/var/folders/`)와 인프라 식별자가 없어야 한다(`td.redact.find_leaks` 통과).
- 문서와 주석은 한국어로 쓰고, 식별자는 영어로 쓴다.
- 테스트가 띄운 컨테이너·프로세스는 상위 요구사항명세 §0.1 규약으로 정리하고 잔존 0을 확인한다.

## Review Focus

1. 조건식에 괄호·줄바꿈·탭이 섞인 bbtg 항목(update의 다중 줄 조건)이 들어오면, 파서는 예외 없이 `unparsed`로 분류해야 한다 → Task 3 `test_req113_multiline_condition_is_unparsed_not_crash`.
2. plan-tests의 `id`가 중복될 때(`errorPath_code400` ×8), case id가 충돌 없이 유일해야 한다 → Task 4 `test_case_ids_unique_with_duplicate_bbtg_ids`.
3. 경계값이 다른 규칙의 유효 범위를 깰 때(예: 유효 경계 roomNumber=100이 분산값과 충돌) 고유값 분산이 경계값을 피해야 한다 → Task 4 `test_spread_avoids_boundary_values`.
4. 그래프에 같은 이름의 상수가 두 클래스에 있으면, 조건식이 속한 클래스의 상수를 고르고 그것도 없으면 `unresolved-operand`여야 한다 → Task 4 `test_constant_resolution_prefers_owner_class`.
5. `--regenerate`로 det를 다시 만들 때 체크섬이 같으면 경고가 없어야 하고, 다르면 경고가 기록돼야 한다 → Task 6 `test_det_regenerate_checksum_warning`.

---

### Task 1: jQA 보강 질의와 `ontology-jqa-ext.json`

**REQ-IDs:** REQ-101, REQ-102

**Files:**
- Create: `ontology/jqa/queries/ext/dto_fields.cypher`, `enums.cypher`, `constants.cypher`, `handler_calls.cypher`, `handler_params.cypher`, `exception_status.cypher`, `response_dtos.cypher`
- Create: `site-gen/td/ontology_ext.py`, `site-gen/td/schemas/ontology-ext.schema.json`
- Modify: `pipeline/S03-jqa.sh` (기존 export 직후 ext export 1회 추가, outputs에 `ontologyExt`)
- Test: `tests/acceptance/test_unit_ontology_ext.py`

**Interfaces:**
- Produces: `td.ontology_ext.export_with_runner(run: Callable[[str], list[dict]], queries_dir: Path, *, base: dict) -> dict`. `base`는 기존 ontology dict이고 endpoint id·exception 대응에 쓴다.
- Produces: CLI `python -m td.ontology_ext export --bolt-port N --base <ontology-jqa.json> --out <ext.json>`
- Produces (파일 모양):
  ```json
  {"schema":1,
   "dtos":{"<fqn>":{"fields":[{"name":"...","type":"<fqn|prim>"}]}},
   "enums":{"<fqn>":{"constants":["..."]}},
   "constants":[{"owner":"<fqn>","name":"...","type":"int","value":2}],
   "calls":[{"endpoint":"endpoint:POST /x","handler":"<fqn>#m","service":"<fqn>","method":"m"}],
   "endpoints":{"endpoint:...":{"params":[{"index":0,"kind":"PathVariable|RequestParam|RequestBody","type":"<fqn|prim>","name":null,"defaultValue":null,"required":null}],"responseDto":"<fqn>|null"}},
   "exceptions":{"<fqn>":{"status":422,"handler":"<fqn>#m"}}}
  ```
  모든 배열은 키로 정렬하고, `json.dumps(..., sort_keys=True, indent=2)`로 쓴다.

- [ ] **Step 1: 실패 테스트 작성** — 가짜 runner(질의 파일 이름 → 행 목록)로 다음을 단정한다.
  - `test_ext_dto_fields`: DTO 행 2개 → `dtos[fqn].fields` 길이와 정렬
  - `test_ext_enum_excludes_synthetic`: `$VALUES` 제외
  - `test_ext_constant_value`: `{"owner":"a.B","name":"CAP","type":"int","value":2}`
  - `test_ext_exception_status_builders`: 빌더 이름 `unprocessableEntity` → 422, `badRequest` → 400, `notFound` → 404, `status` + READS `CONFLICT` → 409, 모르는 빌더 → `status` 키 없음
  - `test_ext_calls_map_endpoint`: handler `a.C#get` → base endpoint id
  - `test_ext_schema_valid`: 결과가 `ontology-ext.schema.json`을 통과
- [ ] **Step 2: 실행해 실패 확인** — `uv run --project site-gen pytest tests/acceptance/test_unit_ontology_ext.py -v` → ImportError
- [ ] **Step 3: 질의와 `export_with_runner` 구현**
  - 질의 근거는 설계 §5.1 표를 따른다.
  - 빌더 소유 타입은 `o.fqn STARTS WITH 'org.springframework.http.ResponseEntity'`로 맞춘다(`ResponseEntity$BodyBuilder` 포함).
  - 예외→핸들러 대응은 `base`의 Exception 노드 `props.handlers`를 쓴다.
  - 빌더→코드 표 `STATUS_BUILDERS = {"badRequest":400,"unprocessableEntity":422,"notFound":404,"ok":200,"noContent":204,"created":201,"accepted":202,"internalServerError":500}`
  - `HttpStatus` 상수 READS는 `HTTP_STATUS = {"BAD_REQUEST":400,"UNAUTHORIZED":401,"FORBIDDEN":403,"NOT_FOUND":404,"CONFLICT":409,"UNPROCESSABLE_ENTITY":422,"OK":200,"CREATED":201,"NO_CONTENT":204}`
  - 질의 실행은 `ontology_jqa.bolt_runner`를 재사용한다.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS
- [ ] **Step 5: S03 연결** — `pipeline/S03-jqa.sh`에서 기존 `EXPORT_OUT` 직후 ext export를 실행하고 스키마를 검사한다. 실패하면 S03을 degraded로 두고 사유 `ext export 실패: …`를 적는다(기존 산출물은 그대로). `OUTPUTS`에 `ontologyExt`를 추가한다.
- [ ] **Step 6: 실제 저장소 확인** — `work/runs/20261120-125628Z-…/S03/store` 복사본으로 jQA server를 띄워 ext export를 실행한다. 확인할 값은 다음과 같다. 확인 후 그 PID만 종료한다.
  - DTO 필드 10/2/12/2
  - `PriceTier` 3, `ReservationStatus` 4
  - `ROOM_CAPACITY` 2
  - calls 6
  - 예외 상태 422/409/404/400
- [ ] **Step 7: 커밋** — `git commit -m "feat(s03): export jQA extension graph (DTO fields, enums, constants, calls, params, exception status)"`

### Task 2: det 번들 투영

**REQ-IDs:** REQ-110, REQ-112

**Files:**
- Create: `site-gen/td/detgen/__init__.py`, `site-gen/td/detgen/inputs.py`
- Test: `tests/acceptance/test_unit_detgen.py` (이 파일은 Task 2~5가 함께 키운다), fixture `tests/fixtures/det/raw-min/`(합성 S02 raw + S03 두 파일, 절대경로 필드 포함)

**Interfaces:**
- Produces: `td.detgen.inputs.project(run_dir: Path, sut_file: Path, out_dir: Path) -> Projection`
  - `Projection(dataclass)`: `dir: Path`, `input_hash: str`(64 hex), `missing: list[str]`, `fatal: str | None`
  - 출력 파일: `out_dir/{plans.json, keyparams.json, auth.json, ontology.json, ext.json, harness.json, STAMP.json}`
  - `plans.json`: `[{"file":"plan-tests-X.m.json","class":"X","method":"m","items":[{"index":i,"condition":str,"expected":str,"branch_value":str,"param":str,"prefix":str,"conditionSha":sha256hex}]}]`
  - `harness.json`: `{"login":"POST /x","unauthenticatedStatus":403,"apiInclude":"/api/**","timezone":"Asia/Seoul"}`(timezone은 `env/docker-compose.sut.yml`의 `TZ`)
- Produces: `td.detgen.inputs.Bundle.open(dir: Path) -> Bundle`. `Bundle.read(name: str) -> object`는 STAMP에 없는 이름이면 `DetInputError`를 낸다. detgen은 이 객체로만 입력을 읽는다.
- Produces: `class DetInputError(RuntimeError)`

- [ ] **Step 1: 실패 테스트 작성**
  - `test_req112_projection`: 투영 결과 전체 텍스트에 `interceptor_sources`, `file_path`가 없고, `td.redact.find_leaks(text) == []`다.
  - `test_req112_bundle_rejects_unlisted_file`: `Bundle.read("../x")`와 `Bundle.read("raw.json")`이 `DetInputError`를 낸다.
  - `test_req110_missing_optional_inputs`: key-params 폴더를 지우면 `missing == ["keyparams"]`이고 `fatal is None`이다.
  - `test_req110_missing_required`: ext 파일을 지우면 `fatal`에 `ontology-jqa-ext.json`이 들어 있다.
  - `test_projection_hash_path_independent`: 같은 fixture를 두 임시 경로에 복사해 투영하면 `input_hash`가 같다.
- [ ] **Step 2: 실행해 실패 확인** — `uv run --project site-gen pytest tests/acceptance/test_unit_detgen.py -k "req112 or req110 or projection" -v` → FAIL
- [ ] **Step 3: `project`와 `Bundle` 구현**
  - 입력 위치는 `run_dir/S02/bbtg/raw/...`와 `run_dir/S03/...`이고, 실제 상대경로는 설계 §3.1을 따른다.
  - 허용 필드만 복사한다.
  - `input_hash`는 정규화 JSON(키 정렬, 구분자 `(",",":")`) 파일들의 이름순 sha256이다.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat(detgen): project allowed bbtg/ontology fields into a signed det bundle"`

### Task 3: 조건식 파서

**REQ-IDs:** REQ-113

**Files:**
- Create: `site-gen/td/detgen/parse.py`
- Test: `tests/acceptance/test_unit_detgen.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Operand: kind: Literal["request","stored","clock","constant","literal","enum","unresolved"]; name: str; detail: str = ""
  @dataclass(frozen=True)
  class Atom:
      op: Literal["<","<=",">",">=","==null","!=null","==","!=","isAfterNot","isBefore","matchesNot","equalsLit","countGe"]
      left: Operand; right: Operand | None; length: bool = False   # length=True면 left의 길이 비교
  @dataclass(frozen=True)
  class Parsed: disjuncts: tuple[tuple[Atom, ...], ...] | None; reason: str | None   # OR of ANDs. 실패 시 None + reason
  def parse(condition: str, request_var: str | None) -> Parsed
  ```
  `request_var`는 요청 DTO 변수 이름이다. bbtg `param` 또는 key-params `accessor`에서 얻고, 모르면 None이다.
- 피연산자 분류:
  - `req.f()`(request_var 일치) → request
  - `existing.getF()` → stored(name=`f`)
  - `LocalDate.now()`/`LocalDateTime.now()` → clock
  - 대문자 식별자 → constant
  - `E.X`(E가 대문자로 시작) → enum
  - 숫자 → literal
  - 그 외 → unresolved
- 피연산자 순서 정규화: `a > f`는 `f < a`로 바꾼다.

- [ ] **Step 1: 실패 테스트 작성**
  - `test_req113_range`: `parse("req.nights() < 1 || req.nights() > 30","req")` → disjuncts 2개, `Atom("<", request nights, literal 1)`, `Atom(">", …, 30)`
  - `test_req113_length`: `req.petName() == null || req.petName().length() < 2 || req.petName().length() > 50` → 3개, 뒤 둘은 `length=True`
  - `test_req113_enum_and`: `req.priceTier() == PriceTier.VIP && req.loyaltyPoints() < 500` → disjunct 1개 안에 Atom 2개, 첫 Atom right.kind=="enum"
  - `test_req113_date`: `req.checkInDate() == null || !req.checkInDate().isAfter(LocalDate.now())` → `isAfterNot`, right.kind=="clock"
  - `test_req113_stored`: `!LocalDate.now().isBefore(existing.getCheckInDate())` → stored `checkInDate`
  - `test_req113_count_const`: `repository.countByRoomNumberAndStatus(req.roomNumber(), ReservationStatus.CONFIRMED) >= ROOM_CAPACITY` → `countGe`, right constant `ROOM_CAPACITY`, detail에 enum `ReservationStatus.CONFIRMED`
  - `test_req113_equals_literal`: `"WELCOME10".equals(req.promoCode())` → `equalsLit`
  - `test_req113_local_variable_unresolved`: `checkIn.isBefore(LocalDateTime.now().plusHours(48))` → left.kind=="unresolved"
  - `test_req113_multiline_condition_is_unparsed_not_crash`: 줄바꿈·탭이 든 잘린 조건(`... && !existing.getStatus().canTransitionTo(req.`) → `disjuncts is None`, `reason == "unparsed"`
  - `test_req113_operand_reversed`: `30 < req.nights()` → `Atom(">", nights, 30)`
- [ ] **Step 2: 실행해 실패 확인** — `... pytest tests/acceptance/test_unit_detgen.py -k req113 -v` → FAIL
- [ ] **Step 3: 구현** — 정규식 토크나이저와 재귀 하강 파서(`||` < `&&` < `!` < 비교). 실패하면 예외를 밖으로 내지 않고 `Parsed(None, "unparsed")`를 돌려준다.
- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat(detgen): condition parser with operand classification"`

### Task 4: 케이스 도출(규칙, baseline, 기대, 생성 불가, 모수)

**REQ-IDs:** REQ-106, REQ-107, REQ-109, REQ-111, REQ-114, REQ-115

**Files:**
- Create: `site-gen/td/detgen/derive.py`
- Create fixture: `tests/fixtures/det/controlled/`(모든 값이 해결되는 합성 번들, 기대 목록 `expected-cases.json`), `tests/fixtures/det/mutated/`(petclinic 기준 투영의 필드명·임계값·enum·경로를 바꾼 번들)
- Test: `tests/acceptance/test_unit_detgen.py`

**Interfaces:**
- Consumes: `Bundle`(Task 2), `parse`(Task 3)
- Produces:
  ```python
  @dataclass
  class Value: value: object; provenance: Literal["input","derived","generic-sentinel"]; source: str | None = None; transform: str | None = None
  @dataclass
  class Case:
      id: str; endpoint: str; rule: str; sources: list[str]
      values: dict[str, Value]; query: dict[str, Value]; path: dict[str, Value]
      setup: list[dict]            # 선행 요청: {"endpoint":..., "values":{...}, "capture":{"var":"jsonField"}}
      auth: Literal["authed","anonymous"]
      expect: dict                 # {"strict":int|"2xx", "class":"2xx"|"4xx", "source":"graph|bbtg|harness-config|rule", "bbtgCode"?:int, "graphStatus"?:int}
      oracle: Literal["status","status-only","framework-reject"]; assumes: list[str]; baseline_proof: list[str]; pair: str | None
  @dataclass
  class Derivation: cases: list[Case]; unresolved: list[dict]; universe: dict
  def derive(bundle: Bundle) -> Derivation
  REASONS = ("no-endpoint-mapping","unparsed","unresolved-operand","unreachable-state","needs-state-transition",
             "param-name-unknown","no-id-ref","no-condition","no-body-schema","format-unknown","input-missing")
  ```
  - source 주소 문자열은 `"<file>#<index>@<conditionSha[:12]>"`이고, 그래프 출처는 `"graph:<node id>"`, 하네스는 `"harness:<key>"`다.
  - case id는 `<method-or-endpoint-slug>-<rule>-<n>`이다. n은 정렬 후 순번이고 중복이 없다.

- [ ] **Step 1: 실패 테스트 작성**
  - `test_req109_controlled_fixture`: `derive(controlled)` → `unresolved == []`. 각 case의 `(rule, endpoint, sorted values, expect.strict)` 목록이 `expected-cases.json`과 같다.
  - `test_req111_mapping`: controlled에서 계획 메서드마다 대응 엔드포인트가 정확히 1개다. 대응 calls를 지운 fixture 변형에서는 그 항목의 reason이 `no-endpoint-mapping`이다.
  - `test_req114_expect`: 그래프 예외 상태가 422이고 bbtg 코드가 400인 항목 → `expect.strict == 422`, `source == "graph"`, `bbtgCode == 400`, `graphStatus == 422`. ext에서 exceptions를 지우면 `strict == 400`, `source == "bbtg"`다.
  - `test_req115_baseline`: 본문 엔드포인트마다 `rule == "baseline-valid"` case가 정확히 1개다. 각 위반 case의 `pair`는 같은 원자식의 유효 경계 case id다.
  - `test_req107_universe`: controlled에서 `universe["bySlot"]["generated"] + universe["bySlot"]["unresolved"] == universe["bySlot"]["total"]`이다. `universe["theoretical"]["value"]`는 손으로 계산한 상수(fixture README에 계산식)와 같다.
  - `test_req106_mutated_fixture`: `derive(mutated)`의 모든 case 값·경로·필드명에 원본 이름 집합(`nights`, `roomNumber`, `PriceTier`, `VIP`, `/api/reservations` 등. fixture 파일 `original-names.txt`)이 하나도 없다. 변조 임계값에서 파생한 경계값이 있다.
  - `test_req106_no_sut_literals`: `site-gen/td/detgen/*.py`와 `e2e/det-glue/**/*.java`의 텍스트에 `original-names.txt`의 이름과 `/api/`가 없다.
  - `test_case_ids_unique_with_duplicate_bbtg_ids`: 같은 `id`를 가진 bbtg 항목 3개 → case id 중복이 없다.
  - `test_spread_avoids_boundary_values`: 유효 경계값과 같은 분산값이 생기지 않는다.
  - `test_constant_resolution_prefers_owner_class`: 같은 이름 상수 두 개(owner A, B), 조건 소유 클래스 A → A의 값을 쓴다. 소유 클래스에도 없고 이름이 둘이면 `unresolved-operand`다.
  - `test_needs_state_transition`: `countGe`에 상태 enum 상세가 있고 create 초기 상태 입력이 없으면 reason이 `needs-state-transition`이다.
  - `test_auth_cases_exclude_login`: harness login 엔드포인트에는 R-AUTH case가 없다. 나머지 api 엔드포인트마다 1개이고, `expect.strict == 403`, `assumes`에 `보호됨`이 있다.
- [ ] **Step 2: 실행해 실패 확인** → FAIL
- [ ] **Step 3: 구현** — 설계 §5.2·§5.3 규칙표를 그대로 구현한다. 결정이 필요한 세부는 다음과 같다.
  - baseline 필드 값 선택 순서: (1) 해당 필드 원자식들의 유효 경계 중 최솟값 쪽, (2) enum은 결합 제약이 가장 적은 상수(동률이면 선언 순서), (3) 형식 휴리스틱, (4) 타입 기본(`String`→`uniq:<caseId>`, `int`→1, `double`→`LARGE_NUMBER`, `LocalDate`→`today+7`, `boolean`→false)
  - 미해결 관계식은 만족 방향 극단값과 assumes, 위반 0과 assumes로 처리한다.
  - 고유 분산 대상은 "유효 범위가 있는 정수 필드 중 count 조건 인자로 쓰이는 필드"다. 범위 안에서 `sha256(caseId)` mod 폭으로 분산하고, 경계값 집합은 건너뛴다.
  - 그래프 전용 케이스(R-NODATA, R-HAPPY GET)는 ext/ontology의 api 엔드포인트 전체에 적용한다.
  - 모수 `bySlot`: `{"total","generated","unresolved","byReason":{...}}`. `byRule`: 규칙별 생성 수. `theoretical`: 엔드포인트별 Π(1 + 필드 위반 클래스 수)의 합, `formula`와 `factors`.
- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat(detgen): derive cases, baseline, expectations, unresolved slots and universe"`

### Task 5: 렌더러와 고정 glue

**REQ-IDs:** REQ-104, REQ-105, REQ-116

**Files:**
- Create: `site-gen/td/detgen/render.py`
- Create: `e2e/det-glue/support/DetSteps.java`, `e2e/det-glue/support/DetValues.java`(package `glue.support`)
- Test: `tests/acceptance/test_unit_detgen.py`, `tests/acceptance/test_det_glue.py`(Int: 컴파일 + dry-run)

**Interfaces:**
- Consumes: `Derivation`(Task 4)
- Produces: `td.detgen.render.render(derivation: Derivation, out_dir: Path) -> list[str]`. 반환값은 쓴 파일의 상대경로 목록이다.
  - 쓰는 파일: `features/<endpoint-slug>.feature`, `glue/support/*.java`(det-glue 복사), `cases.json`
- Produces: `td.detgen.render.GLUE_DIR = <repo>/e2e/det-glue`, `glue_checksum() -> str`(파일 이름순 sha256)
- Gherkin 스텝(전부 DetSteps에 정의된다):
  ```
  Given a request to "<METHOD> <path-template>"
  And path variable "<var>" is <json-literal|symbol>
  And query parameter "<name>" is <json-literal|symbol>
  And body field "<name>" is <json-literal|symbol>
  And the request is sent without authentication
  Given a prior request to "<METHOD> <path>" with body <json-object> capturing "<jsonField>" as "<var>"
  When the request is sent
  Then the response status is <int>
  Then the response status is in class "<2xx|4xx>"
  ```
  - 기호 문법은 문자열 리터럴 `"today+N"`/`"today-N"`, `"ref:<var>"`, `"uniq:<caseId>"`이다. `DetValues.resolve`가 해석하고, 날짜는 `ZoneId.of(System.getenv().getOrDefault("TD_SUT_TZ","Asia/Seoul"))`로 계산한다.
  - 시나리오마다 `@case:<id>` 태그를 달고, 단정 스텝은 strict 하나만 둔다(정상 경로의 strict가 `2xx`면 class 스텝을 쓴다). class 기준 판정은 결과 집계(Task 8)에서 관측 코드로 계산한다. 그래서 DetSteps는 응답을 받을 때마다 `System.out`에 `DET-STATUS <caseId> <code>` 한 줄을 남긴다(caseId는 시나리오 태그에서 읽는다).

- [ ] **Step 1: 실패 테스트 작성**
  - `test_req104_deterministic`: controlled 번들로 두 임시 경로에서 render → 두 트리의 파일별 sha256이 같다.
  - `test_req105_provenance`: 모든 `@case:` 태그가 `cases.json`의 id 집합과 같다. 모든 source 주소가 번들 항목(`conditionSha` 앞 12자리)과 맞는다. 모든 value에 provenance가 있다.
  - `test_req116_glue_layout`(Int): det-glue를 붙인 controlled 렌더 결과에 `td.scenarios.validate_generation`을 돌리면 layout 위반 0, 컴파일 excluded 0, undefined step 0이다. 실행: `uv run --project site-gen pytest tests/acceptance/test_det_glue.py -v`(Gradle 필요)
- [ ] **Step 2: 실행해 실패 확인** → FAIL
- [ ] **Step 3: 구현** — Java는 하네스 API(`Harness.authed()/anonymous()/baseUrl()`)와 REST Assured만 쓰고, `@Before`/`@After`는 쓰지 않는다. 시나리오 상태는 cucumber-picocontainer 없이 DetSteps 인스턴스 필드로 둔다(Cucumber는 시나리오마다 새 인스턴스).
- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat(detgen): render Gherkin + cases.json with fixed det glue"`

### Task 6: S06 det 경로와 스냅샷

**REQ-IDs:** REQ-103, REQ-110

**Files:**
- Create: `site-gen/td/detgen/stage.py`
- Modify: `site-gen/td/bddgen.py:run_stage`(arm == "det"이면 `td.detgen.stage.generate_det`로 위임하고 reps 루프를 건너뛴다)
- Modify: `site-gen/td/schemas/bdd-gen.schema.json`(genId 패턴에 `det`, arm enum에 `det`, generation 항목 `oneOf`: 기존 LLM 필드 세트 | `{generator:{name:"td.detgen",version:str,glueChecksum:str}, inputHash, cases:int, unresolved:int}`)
- Test: `tests/acceptance/test_unit_detgen.py`, `tests/acceptance/test_det.py`(Int 일부)

**Interfaces:**
- Consumes: `project`(Task 2), `derive`(Task 4), `render`(Task 5), `td.snapshot.try_reserve/make_tmp/write_complete/complete_problem/release`, `td.scenarios.validate_generation`
- Produces: `td.detgen.stage.generate_det(run_dir: Path, sut_file: Path, out_root: Path, regenerate: bool) -> DetResult`
  - `DetResult(dataclass)`: `status: Literal["passed","degraded","failed"]`, `reason: str | None`, `gen_id: str | None`, `dir: Path | None`, `record: dict`, `reused: bool`
  - `GENERATOR_VERSION = "1"`. `key = sha256(projection.input_hash + GENERATOR_VERSION + glue_checksum())`, `gen_id = f"det-{key[:8]}-r1"`

- [ ] **Step 1: 실패 테스트 작성**
  - `test_req103_no_llm_calls`(Int): `PATH` 앞에 `claude`와 `llm.sh` 호출 기록 shim을 둔다. controlled 투영을 가진 임시 run_dir로 `bddgen.run_stage`를 arms=`["det"]`로 실행한다. shim 기록 파일이 비어 있고, `S06/bdd-gen.json`이 스키마를 통과한다.
  - `test_req110_failure_isolated`(Int): arms=`["base","det"]`, det 필수 입력(ext)이 없고 base는 스텁 llm인 임시 run → `arms.det.status == "failed"`이고 reason에 `ontology-jqa-ext.json`이 들어 있다. `arms.base.status`는 failed가 아니다.
  - `test_det_reuse_snapshot`: 같은 입력으로 두 번 → 두 번째 `reused is True`.
  - `test_det_regenerate_checksum_warning`: regenerate=True로 같은 입력이면 경고가 없다. glue_checksum을 monkeypatch해 키를 고정한 채 렌더 결과를 바꾸면 `record["warnings"]`에 `checksum-changed`가 들어간다.
- [ ] **Step 2: 실행해 실패 확인** → FAIL
- [ ] **Step 3: 구현**
  - 기존 `_produce`의 예약, 임시 디렉터리, 검증, 원자적 rename 순서를 따른다.
  - 검증 실패(layout, 컴파일, undefined)는 det failed다. 수리 루프는 없다.
  - `projection.missing`이 비어 있지 않으면 degraded다.
  - `run.json`에 `requestedRepsByArm`을 기록한다: `{arm: (1 if arm=="det" else reps)}`.
- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat(s06): deterministic arm path with snapshot protocol and failure isolation"`

### Task 7: arm 목록 확장(실행·식별·CLI)

**REQ-IDs:** REQ-108

**Files:**
- Modify:
  - `site-gen/td/state.py` — `ARMS_ALL`에 `"det"`, `ARM_DEPENDENCIES["det"] = ("S02","S03")`, `requested_reps_by_arm(run_dir) -> dict[str,int]`
  - `site-gen/td/testid.py` — `ARMS`
  - `site-gen/td/scenarios.py:37`, `site-gen/td/tia.py:107` — genId 정규식 `(base|jqa|owl|det)`
  - `site-gen/td/bundle.py` — `ARMS`는 그대로 둔다. det는 bundle 조립을 쓰지 않으므로 `build_bundle`은 det에서 호출되지 않아야 한다. 단정만 추가한다.
  - `pipeline/run-all.sh:31` — arms 검증에 det 허용
  - `e2e/harness/src/main/java/td/harness/TestIds.java`와 `TestIdsTest.java` — ARMS에 det
  - `site-gen/td/schemas/compare.schema.json` — arm enum에 det, `requestedRepsByArm`, `deterministic` 블록
  - `site-gen/td/site/static/site.css` — `--arm-det` 토큰(라이트·다크 세 곳)
- Test: 기존 `test_unit_state.py`, `test_e2e.py`, `test_unit_tia.py`에 det 케이스 추가. Gradle `:harness:test`

**Interfaces:**
- Produces: `state.requested_reps_by_arm(run_dir) -> dict[str, int]`. run.json 값이 없으면 `{arm: requested_reps}`이고 det는 1이다.

- [ ] **Step 1: 실패 테스트 추가**
  - `test_unit_state.py::test_det_arm_dependencies`: `ARM_DEPENDENCIES["det"] == ("S02","S03")`. S03 failed run에서 `arm_plan(run_dir, ["det"])["det"]`에 `S03`이 들어 있다.
  - `test_e2e.py::test_testid_det`: `testid.make("det", HASH, 1, None, "a/x.feature", 3, set())`가 `E2E_det_` 접두로 시작한다.
  - `test_unit_tia.py::test_rep1_det`: `det-0123abcd-r1`이 rep1로 선택된다.
  - `test_run.py::test_arms_det_accepted`: 스텁 단계로 `run-all --arms det`가 검증을 통과한다.
- [ ] **Step 2: 실행해 실패 확인** → FAIL
- [ ] **Step 3: 구현** — 목록과 정규식만 바꾼다. 기본 arms는 `base,jqa,owl` 그대로 둔다.
- [ ] **Step 4: 통과 확인** — `uv run --project site-gen pytest tests/acceptance -m "not baseline" -q`와 `cd e2e && ./gradlew --no-daemon :harness:test` → 전부 PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat: register det arm across state, testids, TIA, CLI and harness"`

### Task 8: 비교·결과 집계·대시보드

**REQ-IDs:** REQ-108, REQ-114, REQ-115

**Files:**
- Modify: `site-gen/td/compare.py`
  - `ARMS_ORDER`에 det
  - `DOT_COLORS["det"]`
  - `collect`에서 `verdict.judge`에는 `{k: v for k in ("base","jqa","owl")}`만 넘긴다.
  - `deterministic` 블록을 추가한다.
  - arm별 `requestedReps`, 입력 체제 `inputRegime`을 기록한다.
- Create: `site-gen/td/detgen/results.py`
- Test: `tests/acceptance/test_compare.py`에 det 케이스, `tests/acceptance/test_unit_detgen.py`

**Interfaces:**
- Produces: `td.detgen.results.summarize(gen_dir: Path, scenario_results: list[dict], stdout_text: str) -> dict`
  ```json
  {"cases":N,"unresolved":M,"universe":{...},
   "passStrict":{"passed":a,"total":N},"passClass":{"passed":b,"total":N},
   "baselineValid":{"endpoint":"passed|failed"},"blockedByBaseline":k,"verifiedViolations":v,
   "byRule":{"R-RANGE":{"generated":..,"passedStrict":..}},
   "statusMismatch":[{"case":id,"bbtgCode":400,"graphStatus":422,"observed":422}]}
  ```
  - class 판정은 `DET-STATUS` 줄의 관측 코드를 `expect.class`와 비교한다.
- `inputRegime` 값:
  - base: `{"llm":true,"conditions":false,"graph":"none"}`
  - jqa: `{"llm":true,"conditions":false,"graph":"jqa"}`
  - owl: `{"llm":true,"conditions":false,"graph":"owl"}`
  - det: `{"llm":false,"conditions":true,"graph":"jqa+ext"}`

- [ ] **Step 1: 실패 테스트 작성**
  - `test_compare.py::test_det_excluded_from_verdict`: det 수치를 크게 바꿔도 `verdict`가 바뀌지 않는다.
  - `test_compare.py::test_det_reference_column`: 렌더 HTML에 `data-arm="det"` 열과 입력 체제 문구(`LLM 없음, 조건식 포함`)가 있다. 헤더는 `det (n=1/1)`이다.
  - `test_unit_detgen.py::test_results_summarize`: 합성 결과로 strict와 class 통과 수, blocked-by-baseline, verified violations가 계산 기대값과 같다.
- [ ] **Step 2: 실행해 실패 확인** → FAIL
- [ ] **Step 3: 구현** — S07의 det generation `exec` 로그에서 `DET-STATUS` 줄을 읽는다. 로그 위치는 S07 generation 디렉터리의 `gradle.log`다. 줄이 없으면 class 판정을 null로 두고 사유를 기록한다.
- [ ] **Step 4: 통과 확인** → PASS
- [ ] **Step 5: 커밋** — `git commit -m "feat(compare): det reference column, input regime, deterministic results block"`

### Task 9: 실제 실행, E2E 수용 테스트, 문서

**REQ-IDs:** REQ-101, REQ-102, REQ-105, REQ-107, REQ-108, REQ-111, REQ-115, REQ-117

**Files:**
- Create: `tests/acceptance/test_det.py`(E2E: 실제 run 산출물 검사)
- Modify:
  - `docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md`(arm 목록·reps 서술에 det 주석)
  - `README.md`(`--arms det` 사용법)
  - 요구사항 매트릭스 상태
- Add: `docs/whitepaper/2026-11-21-test-dashboard-poc-whitepaper.md`(main checkout의 미커밋본을 이 브랜치로 옮긴다. §5.3 DTO 필드 정정과 det 결과 절을 추가한다)

- [ ] **Step 1: E2E 테스트 작성**(최신 det run을 `work/det-session.json`이 가리킨다)
  - `test_req101_ext_ontology`: 설계 AT-1 값들
  - `test_req102_existing_inputs_unchanged`: 기준 run `20261120-125628Z-b6f9393-manual-c5748158` 대비 `ontology-jqa.json` sha256, 세 번들 해시, S05 inputHash가 같다.
  - `test_req105_provenance_real`, `test_req107_universe_real`, `test_req111_mapping_real`(계획 메서드 6개 → 엔드포인트 6개), `test_req115_baseline_real`
  - `test_req108_pipeline_compare`: S07~S13이 passed 또는 degraded(det 이외 사유 없음)다. `compare.json.arms.det`와 `deterministic` 블록이 있다. 두 번째 run 기록에서 `claude` shim 호출 0이다.
- [ ] **Step 2: 실행** — `pipeline/run-all.sh petclinic --arms base,jqa,owl,det --reps 3`(기존 arm은 스냅샷 재사용. 게시는 `TD_SITE_PREFIX=_test/det-<date>/`로 먼저 확인한 뒤 운영에 게시). 끝나면 `docker ps -a --filter label=test-run=…`과 run PID 잔존 0을 확인한다.
- [ ] **Step 3: E2E 실행** — `uv run --project site-gen pytest tests/acceptance/test_det.py -v` → PASS
- [ ] **Step 4: 문서 갱신** — 백서에 det 결과 절을 추가한다. 넣을 내용은 다음과 같다.
  - 생성 수, 규칙별 수, 생성 불가 reason별 수, 이론 모수
  - strict와 class 통과율, 검증된 위반 수
  - focus 라인/브랜치, 오라클 적중, 엔드포인트 커버
  - 기존 arm 대비 표와 입력 체제 차이 주석
  
  상위 설계·README·매트릭스도 갱신한다.
- [ ] **Step 5: 커밋** — `git commit -m "test(det): end-to-end acceptance on real run; docs and whitepaper"`
