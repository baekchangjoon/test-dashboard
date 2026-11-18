# test-dashboard 실증(PoC) 요구사항명세

> 출처(design spec): docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md (v3)
> 완료 정의(DoD): 커버리지 대상 요구사항마다 매트릭스에 지정된 검증 테스트가 하나 이상 있고, 그 테스트가 모두 통과한다(대상 매트릭스 전부 green).
> 버전: v2.1 (2-벤더 리뷰와 재리뷰 반영: Claude Fable, GPT 5.6 Sol. Gemini는 사용자 결정으로 이번 세션에서 제외)
> 기준 SUT 커밋: `baekchangjoon/spring-petclinic` `b6f939355e8790202ddfc71e3f3507252745ed37`. 기대 목록(`suts/petclinic/expected-*.yaml`)은 이 커밋에서 추출하고 사람이 검토해 커밋한다. SUT HEAD가 바뀌면 기대 목록 갱신 전까지 해당 테스트는 실패한다.

## 0. 검증 테스트 규약

- 모든 검증 테스트는 pytest이고 `tests/acceptance/`에 둔다. Java 하네스 IT는 pytest 래퍼가 Gradle로 실행한 뒤 JUnit XML을 확인한다. 함수 이름은 `test_req<NNN>_<요약>`이다.
- 레벨:
  - **E2E**: 기준 run의 산출물이나 배포 URL을 블랙박스로 검사한다.
  - **E2E-inj**: 장애나 신호를 주입한 별도 실행을 검사한다.
  - **Int**: 단일 단계나 스크립트를 실제 도구와 함께 실행한다.
  - **Unit**: 순수 함수를 검사한다(pytest).
- **독립 오라클 원칙**: 수용 테스트는 구현이 쓴 자기 보고(`bdd-gen.json` 등)만으로 판정하지 않는다. 외부 관측(가짜 실행 파일 캡처, Docker 자원 전후 비교, 사람이 검토한 기대 목록)을 함께 쓴다.

### 0.1 수용 테스트 실행 환경

| 구분 | 내용 |
|---|---|
| 기준 run (fixture `baseline_run`, session scope) | `run-all.sh petclinic` 1회. 운영 사이트(`TD_SITE_PREFIX=""`)에 게시한다. E2E 레벨 테스트가 공유한다. |
| 두 번째 run (fixture `second_run`) | S05와 S06 스냅샷을 재사용해 `run-all.sh petclinic`을 1회 실행한다. 실제 `claude` 앞에 둔 호출 기록 shim의 호출 수가 0이어야 한다(REQ-075). 운영 사이트에 게시한다. |
| 주입 실행 | `TD_SITE_PREFIX=_test/<sessionId>/`(S3)와 `/srv/dashboard/_test/<sessionId>/`(Lightsail)에 게시하고 **지우지 않는다**(나중에 과정을 확인하기 위한 보존, 사용자 결정 2026-11-18). 운영 인덱스의 SUT 목록과 KPI는 `_test/`를 집계하지 않고, 홈 하단의 "테스트 실행 기록" 링크로 `_test/index.html`(세션 목록)에 들어갈 수 있다. |
| mini-sut | `tests/fixtures/mini-sut`(작은 Spring Boot 앱)를 테스트 시점에 `work/fixtures/mini-sut`로 `git init`해 `file://` URL로 쓴다. 게시는 주입 실행 환경에만 하고 보존한다. |
| 테스트가 만든 잠금·토큰 | try/finally로 제거하고 잔존 0을 검증한다. |
| 전제 미충족 | AWS 자격, SSH, Docker, `claude` CLI가 없으면 해당 테스트는 **실패**로 처리한다. skip으로 green을 주장하지 않는다. |
| Sonar 격리 | 주입 실행은 `sonar.projectKey`를 `<key>-test-<sessionId>`로 바꾼다(프로젝트는 보존). 테스트가 DB에 직접 넣는 fixture 행(REQ-065)은 평문을 아무도 모르는 무작위 해시이고, 만료가 삽입 후 10분 이내이며, finally에서 지우고 0행을 검증한다. |
| 테스트가 띄운 자원 | 테스트가 직접 띄운 컨테이너·프로세스(REQ-007, 010, 074 등)는 `-p td-test-<sessionId>-<name>`과 `test-run=td-test-<sessionId>` 라벨로 표식한다. fixture teardown에서 `down -v --remove-orphans`를 실행하고, 세션 종료 훅에서 해당 라벨 자원과 PID가 0인지 확인한다. 남으면 세션 실패다. |
| Docker 호스트 전제 | 수용 세션 동안 이 맥에서 다른 Docker 작업을 하지 않는다. 전후 차이 중 `td-`/`td-test-` 계열 compose project에 속하지 않는 것은 경고로 분리해 보고한다. |
| 주입 훅 | 설계 §13.9의 `TD_FAIL_STAGE` 식별자 표를 따른다. `TD_SITE_PREFIX`가 없으면 훅은 거부된다. |
| 운영 사이트 집계 대상 | 이번 수용 세션이 운영 경로에 만든 run은 정확히 2개(기준, 두 번째)다. 이전 세션의 운영 run은 보존된다. 주입 실행과 mini-sut 기록은 `_test/` 아래에 보존되며 집계에서 빠진다. |

## 요구사항 목록

### A. 실행 골격

#### REQ-001 — SUT 전체 히스토리 clone과 커밋 고정
- 유형: Functional / 우선순위: Must
- 수용기준: Given `sut.yaml`, When S00을 실행하면, Then `git rev-parse --is-shallow-repository`가 `false`이고 `run.json.commit`이 clone의 HEAD 전체 sha와 같다.
- 검증 레벨: Int

#### REQ-058 — 도구 잠금 파일 완전성
- 유형: Functional / 우선순위: Must
- 수용기준: Given S00 완료, Then `tools.lock`에 pjacoco, jacococli, jQA CLI, jQA Spring 플러그인, hotspot, TIA, bbtg, `claude` CLI 버전, 생성 모델 id가 있다. jacococli 버전이 pjacoco jar에 내장된 jacoco-core 버전(jar 안의 메타데이터를 테스트가 직접 읽음)과 같다.
- 검증 레벨: Int

#### REQ-002 — 단계 상태 기록
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, When 로컬 `work/runs/<runId>/run.json`과 `stages/*.json`을 읽으면, Then S00~S13 14개가 모두 있다. `stages/*.json`의 상태는 `passed|failed|degraded|skipped` 중 하나다. `run.json.stages.S13`만 `publishing`을 허용한다. `passed`가 아닌 상태에는 비어 있지 않은 `reason`이 있다.
- 검증 레벨: E2E

#### REQ-003 — run-all 종료 코드 규칙
- 유형: Functional / 우선순위: Must
- 수용기준(`TD_FAIL_STAGE=<ID>` 테스트 훅으로 주입):
  - Given S01~S12 중 한 단계만 실패(단계별 parameterized), Then 종료 코드는 2다.
  - Given S13 실패, Then 1이다.
  - Given S00 실패, Then 1이다.
  - Given `TD_FAIL_STAGE=S09,S13`, Then 1이다(S00·S13 실패가 우선).
  - Given 실패 없이 passed, degraded, skipped만 있으면, Then 0이다.
- 검증 레벨: E2E-inj

#### REQ-004 — 단계 선택 실행
- 유형: Functional / 우선순위: Should
- 수용기준: Given `run-all.sh petclinic --only S00,S01`, Then 나머지 단계(S13 포함)는 `skipped`이고 `reason`은 `not-requested`이며, 종료 코드는 0이다.
- 검증 레벨: Int

#### REQ-059 — 의존 단계 건너뜀 전파
- 유형: Functional / 우선순위: Must
- 수용기준: Given `TD_FAIL_STAGE=S05`, Then `stages/S06.json.arms.owl.status`와 `stages/S07.json.generations.<owl genId>.status`가 `skipped`(reason에 `S05` 포함)이고, `base`와 `jqa`는 실행된다. S06과 S07의 단계 상태는 `degraded`, S04는 jQA만 시각화해 `degraded`, S12는 '판정 불가(arm 부족)'를 표시하고 `degraded`다. Given `TD_FAIL_STAGE=S02`, Then S06의 모든 arm이 `skipped`이고 S06은 `skipped`다.
- 검증 레벨: E2E-inj

#### REQ-005 — 고유 runId
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 커밋에서 같은 초에 runId 생성을 1,000회 병렬로 하면, Then 중복이 0이다. 형식은 `^\d{8}-\d{6}Z-[0-9a-f]{7}-(manual|pr|merge)-[0-9a-f]{8}$`이고 시각은 UTC다. Given 처음 N회(N≤4)는 같은 값을 내는 가짜 난수, Then 로컬 예약(`O_EXCL` 디렉터리 생성) 충돌로 N회 재생성한 뒤 성공한다. 5회를 넘기면 비-0으로 종료한다.
- 검증 레벨: Unit

#### REQ-006 — 트리거 자리 마련
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then `run.json.trigger="manual"`이고 `pr` 키가 있다(null).
- 검증 레벨: E2E

#### REQ-060 — 실행 시간 메타데이터
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then `startedAt`과 `finishedAt`은 ISO-8601 UTC이고 `startedAt < finishedAt`이며, `tz="Asia/Seoul"`이고 `sutDate`(SUT 기준 날짜)가 있다. `clockShift = date(startedAt, tz) != date(finishedAt, tz)`가 기록되고, true면 `compare.html`에 경고가 표시된다. 오케스트레이터 Clock 주입으로 자정 직전, 정확히 자정, 직후 경계를 Unit으로 검증한다.
- 검증 레벨: E2E, Unit

### B. SUT 실행 환경과 자원 정리

#### REQ-007 — 컨테이너 SUT에서 per-test 수집 가능
- 유형: Functional / 우선순위: Must
- 수용기준: Given SUT 컨테이너 기동, Then `docker compose port`의 결과가 SUT 포트와 제어 포트 모두 `127.0.0.1:<port>`다. When `POST /__coverage__/test/start?testId=T1`, `baggage: test.id=T1`을 붙인 `auth.probe` 요청 1회, `POST /__coverage__/test/stop?testId=T1&result=passed`를 차례로 호출하면, Then 제어 호출이 모두 2xx이고 `T1.exec`가 호스트의 마운트 경로에 생긴다. (pjacoco는 커버 클래스가 0개인 스토어는 쓰지 않는다.)
- 검증 레벨: Int

#### REQ-008 — TC 수와 .exec 수 일치 게이트
- 유형: Functional / 우선순위: Must
- 수용기준: Given S01 완료, Then JUnit XML에서 skipped를 뺀 TC 수가 `aggregate*.exec`를 뺀 `.exec` 수와 같다(기준 커밋 참고값 35, `suts/petclinic/expected-tests.yaml`). Given 제어 URL을 잘못 주는 주입, Then S01은 `failed`다.
- 검증 레벨: E2E, E2E-inj

#### REQ-009 — Docker 자원 누수 0 (외부 관측)
- 유형: Non-functional / 우선순위: Must
- 수용기준:
  - Given 기준 run 전후의 컨테이너, 네트워크, 볼륨 ID 목록, Then 새로 생겨 남은 ID가 0개다(라벨과 무관한 차이 비교).
  - `docker compose config`로 렌더링한 SUT compose의 모든 서비스, 명시적 네트워크, 명시적 볼륨에 `test-run` 라벨이 있다.
  - 라벨을 일부러 뺀 compose로 실행하면 검사가 실패한다(부정 테스트).
- 검증 레벨: E2E, Int

#### REQ-010 — 중단 시에도 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given S01과 S03 각각 실행 중, When 라벨이 붙은 컨테이너(S03은 jQA server PID 파일)가 보인 직후 프로세스 그룹에 SIGINT를 보내면, Then 90초 안에 종료되고, REQ-009의 차이가 0이며, `work/runs/<runId>/pids/`의 모든 PID가 종료돼 있다.
- 검증 레벨: E2E-inj

#### REQ-011 — 백그라운드 프로세스와 worktree 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 기준 run, Then `pids/`의 PID가 모두 종료됐고, `git worktree list`에 TIA base worktree가 없으며, run 시작 뒤 생성된 `GradleDaemon` PID(시작 시각으로 식별) 중 살아 있는 것이 0개다. Given S10 중단 주입, Then worktree가 남지 않는다.
- 검증 레벨: E2E, E2E-inj

### C. 기존 블랙박스 IT와 bbtg

#### REQ-012 — 기존 블랙박스 IT 실행
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then `work/runs/<runId>/S01/blackbox/exec/`에 TC별 `.exec`/`.json`과 `aggregate.exec`가 있고, JUnit XML이 `S01/blackbox/junit/`에 있다.
- 검증 레벨: E2E

#### REQ-013 — bbtg 7개 스킬 CLI 실행
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run의 `S02/bbtg/manifest.json`, Then 다음이 모두 있다.
  - inspect-stack, scan-test-assets, inspect-auth 각 1회
  - dependency-map과 find-external-calls는 `@RestController` 수(기대 목록 기준)만큼
  - plan-tests는 1회 이상
  - derive-test-data 1회(인자에 `sut.yaml.runtime.ddl` 경로가 있음)
  - 각 호출의 인자, 종료 코드, 산출물 경로
  - SUT clone에 `.bbtg/`가 없다.
  - `claude` 가짜 실행 파일(PATH 앞에 주입)이 S02 동안 한 번도 호출되지 않는다.
- 검증 레벨: E2E, Int

### D. 온톨로지

#### REQ-014 — jQA 엔드포인트 완전성 (독립 기대 목록)
- 유형: Functional / 우선순위: Must
- 수용기준: Given 사람이 검토한 `suts/petclinic/expected-endpoints.yaml`(기준 커밋의 `/api/**` 핸들러 17개, 메서드+정규화 경로. 생산 코드와 독립적으로 작성), When `ontology-jqa.json`의 `kind=Endpoint`, `props.view=false` 집합과 비교하면, Then 같다.
  - 정규화 규칙: 클래스와 메서드 경로 결합, 배열 값 전개, trailing slash 제거, path variable은 `{name}`
  - 기대 목록과 커밋이 다르면 테스트가 실패하고 기대 목록 갱신을 요구한다.
- 검증 레벨: E2E

#### REQ-015 — 온톨로지 스키마
- 유형: Functional / 우선순위: Must
- 수용기준: Given `ontology-jqa.json`과 `ontology-owl.json`, Then `site-gen/td/schemas/ontology.schema.json` 검증을 통과하고 `meta.commit` = `run.json.commit`이다. jQA 산출물에는 Endpoint 외에도 `Service`, `Repository`, `Entity`, `Exception` kind 노드가 각각 1개 이상 있다.
- 검증 레벨: E2E

#### REQ-016 — 온톨로지 HTML 오프라인 동작
- 유형: Functional / 우선순위: Must
- 수용기준: Given `ontology/jqa.html`과 `ontology/owl.html`, When 네트워크를 차단한 헤드리스 브라우저로 열면, Then 콘솔 오류가 0이고 렌더링된 노드 수가 각 JSON의 노드 수와 같다.
- 검증 레벨: E2E

#### REQ-017 — 온톨로지 HTML 반응형과 다크 모드
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 360px 뷰포트, Then `scrollWidth <= innerWidth`이고 속성 패널이 그래프 아래에 온다. `prefers-color-scheme: dark`에서 body 배경색이 라이트와 다르다.
- 검증 레벨: E2E

#### REQ-018 — OWL 온톨로지의 의미 있는 대응
- 유형: Functional / 우선순위: Must
- 수용기준: Given S05 완료, Then 다음을 만족한다.
  - `ontology-owl.ttl`이 rdflib로 파싱된다.
  - jQA `Entity` 노드의 90% 이상이 `owl:Class`로 대응하고, 각 클래스에 jQA 노드 id를 가리키는 provenance 속성이 있다.
  - 객체 속성이 3개 이상 있다.
  - `shapes.ttl` 검증이 conforms=true다.
  - 위반 fixture(필수 속성이 빠진 개체) 검증은 conforms=false다.
- 검증 레벨: E2E, Int

### E. 생성 입력 오염 차단 (S05, S06 공통)

#### REQ-019 — 입력 번들 경로 검사
- 유형: Functional / 우선순위: Must
- 수용기준: Given 보존된 번들(`S05/bundle/`, `S06/bundles/<arm>/`. 스냅샷 재사용 여부와 무관하게 항상 조립·검사·보존), Then 모든 파일이 허용 목록 안에 있다. Given SUT `docs/` 파일을 번들에 넣는 주입, Then LLM 호출 전에 단계가 실패한다.
- 검증 레벨: E2E, Int

#### REQ-020 — 입력 번들 내용 검사
- 유형: Functional / 우선순위: Must
- 수용기준: 정규화 절차는 다음과 같다. 각 번들 파일을 형식별로 파싱해 문자열 leaf를 추출하고, escape를 해제한다. CRLF를 LF로, 탭을 공백으로 바꾸고, 줄마다 앞뒤 공백을 지운 뒤 빈 줄을 버린다. 파일 단위로 leaf를 문서 순서대로 이어 붙여 한 시퀀스로 보고, 3자 이하 줄은 일치 계산에서 뺀다. 형식별 파서는 JSON, YAML, Turtle(literal), Markdown(코드 블록과 본문 줄), 그 밖은 텍스트 줄이다. 그 결과를 SUT `src/**`를 같은 방식으로 정규화한 줄 시퀀스와 비교한다.
  - Given 이 정규화, Then 연속 5줄이 일치하는 블록이 0개다.
  - Given escaped newline, CRLF, 탭, 빈 줄, 중첩 배열, 이름이 다른 필드, Unicode escape, 이중 escape에 SUT 소스 5줄을 숨긴 fixture 각각, Then 검사기가 모두 검출한다. 4줄만 숨긴 fixture는 통과한다(경계).
- 검증 레벨: E2E, Unit

#### REQ-021 — bbtg 산출물 허용 스키마
- 유형: Functional / 우선순위: Must
- 수용기준: Given 정제된 bbtg 산출물, Then 스킬별 허용 JSON Schema(`site-gen/td/bbtg_allow/*.schema.json`, `additionalProperties: false`)를 통과한다. `bdd-gen.json.strippedFields`는 스키마가 금지하는 경로 목록 전체이고 `interceptor_sources[].source`를 포함한다. 원본에 값이 있던 경로마다 `removedCount`가 기록된다.
- 검증 레벨: E2E

#### REQ-022 — LLM 호출 격리 (외부 캡처)
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given PATH 앞에 둔 가짜 `claude`가 argv, cwd, 환경 변수, stdin을 기록하는 상태, When S05와 S06(수리 호출 포함)을 실행하면, Then 모든 호출의 cwd가 번들 임시 디렉터리다.
  - argv에 도구 전부 비활성, MCP 설정 비움, 사용자·프로젝트 설정 미로딩 플래그가 있다(정확한 플래그 이름은 S00에서 CLI 버전별로 확인해 `tools.lock`에 기록).
  - stdin에 SUT `src/**` 내용이 없다.
  - 실제 `claude`로 하는 카나리 호출(번들에 "파일을 읽어라" 지시문 포함)의 출력에 tool_use 이벤트가 0건이다.
- 검증 레벨: Int

#### REQ-023 — 세 arm과 반복 generation
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then `run.json.arms.generations`에 `base`, `jqa`, `owl` 각각 `reps`(기본 3)개의 genId가 있고, 각 디렉터리 `e2e/generated/petclinic/<arm>/<genId>/`가 있다. genId 형식은 `^(base|jqa|owl)-[0-9a-f]{8}-r[1-9](-g[0-9]+)?$`다(`reps`는 1~9, 범위 밖이면 S00에서 오류). `reps`가 3보다 작으면 `compare.html`에 실제 횟수가 보인다.
- 검증 레벨: E2E

#### REQ-024 — 스냅샷 재사용과 보존
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given 같은 입력 해시의 스냅샷, When 기본 옵션으로 다시 실행하면, Then 가짜 `claude`가 호출되지 않고 같은 genId를 재사용한다.
  - When `--regenerate`로 실행하면, Then 기존 디렉터리의 파일 해시가 그대로이고 `-g<n>` 접미사의 새 genId가 추가된다. 두 `--regenerate`를 병렬로 실행하면 원자적 `mkdir` 예약으로 서로 다른 genId가 생긴다.
  - S05 OWL 산출물도 입력 해시(jQA JSON + 정제 bbtg + 프롬프트) 키로 스냅샷해 같은 규칙으로 재사용한다.
- 검증 레벨: Int

#### REQ-025 — 수리 루프 제한 (외부 캡처)
- 유형: Functional / 우선순위: Must
- 수용기준: Given 가짜 `claude` 캡처와 컴파일 오류를 내는 생성물 fixture, Then 한 generation의 수리 호출은 2회 이하이고, 수리 호출의 stdin에는 허용된 두 종류(컴파일러 출력, dry-run undefined 목록)만 있다. SUT 응답에 넣어 둔 표식 문자열이 없다.
- 검증 레벨: Int

#### REQ-061 — 생성 메타데이터 기록
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run의 `bdd-gen.json`과 `owl-gen.json`, Then `bdd-gen.schema.json` 검증을 통과한다. 필드는 입력 해시, 프롬프트 해시, 모델 id, CLI 버전, 플래그, 수리 횟수, 입력·출력 토큰, 소요 시간, strippedFields다.
- 검증 레벨: E2E

#### REQ-075 — 생성 입력 해시 안정성
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 SUT 커밋과 같은 `tools.lock`, When 서로 다른 체크아웃 경로에서 S02, S03, 번들 조립을 두 번 실행하면, Then arm별 입력 해시가 같다. 정제 단계에서 bbtg의 `timestamp`, `scan_duration_ms`, 생성 시각, 절대 경로를 제거하거나 상대화한다. Given 두 번째 run, Then 호출 기록 shim의 `claude` 호출 수가 0이다.
- 검증 레벨: Int, E2E

### F. E2E 하네스와 실행

#### REQ-026 — 인증 하네스
- 유형: Functional / 우선순위: Must
- 수용기준: Given SUT 기동과 `sut.yaml.auth`(`probe`, `unauthenticated_status`), When 하네스 `authed()`로 `auth.probe`를 호출하면, Then 2xx다. `anonymous()`로 호출하면 `auth.unauthenticated_status`(petclinic 실측값, 401 또는 403)다.
- 검증 레벨: Int (pytest 래퍼 → Gradle `HarnessAuthIT`)

#### REQ-027 — 결정적 testId
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 feature 파일, When testId 함수를 두 번 적용하고 dry-run을 두 번 실행하면, Then testId 집합이 같다. 모든 testId가 `^E2E_(base|jqa|owl)_[0-9a-f]{8}r[1-9](g[0-9]+)?_[A-Za-z0-9_]+#L\d+$`에 맞고, generation 안에서 중복이 0이다. 시나리오 단위는 pickle이다(Scenario Outline은 Examples 행마다 하나, `L<line>`은 pickle 위치). Outline fixture와, slug가 같은 feature 두 개 fixture(결정적 접미사 `_2`)에서도 중복이 0이다.
- 검증 레벨: Unit, Int

#### REQ-028 — 시나리오 수 보존
- 유형: Functional / 우선순위: Must
- 수용기준: Given generation별 결과, Then 다음이 성립한다.
  - `.feature`의 시나리오 수 = 결과 시나리오 수(`uncompilable` 포함) = `coverage.html` TC 행 수
  - 기준 파일은 generation별 `scenario-results.json`(testId마다 한 줄, `status`, `requests`, `exec` 경로)이다.
  - 하네스가 센 SUT 요청이 1회 이상인 시나리오 수 = `.exec` 수. 요청이 0회인 시나리오는 커버 0라인 TC로 분모에 남는다.
  - feature와 glue에서 `@ignore`, `@Disabled`, `@wip`가 0건
- 검증 레벨: E2E

#### REQ-029 — dry-run undefined 비율 기록
- 유형: Functional / 우선순위: Must
- 수용기준: Given generation별 결과, Then `undefinedRatio` = (step이 하나 이상 undefined이고 `uncompilable`이 아닌 pickle 수) / (uncompilable을 포함한 전체 pickle 수)가 기록되고, 그 값을 Cucumber dry-run JSON에서 테스트가 다시 계산한 값과 같다.
- 검증 레벨: E2E

#### REQ-030 — JUnit 대체 스타일
- 유형: Functional / 우선순위: Could
- 수용기준: Given `--style junit`, When S06·S07을 실행하면, Then JUnit 테스트가 생성·실행되고 `run.json.arms.style="junit"`이다.
- 검증 레벨: Int

#### REQ-062 — Cucumber 리포트 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run 게시, Then generation마다 `cucumber/<genId>/index.html`(Cucumber 내장 HTML)이 있고 run 페이지에서 링크된다.
- 검증 레벨: E2E

### G. 커버리지

#### REQ-031 — 스위트별 귀속·집계 커버리지
- 유형: Functional / 우선순위: Must
- 수용기준: Given S08 완료, Then 스위트(blackbox와 각 genId)마다 attributed와 aggregate의 HTML·XML·CSV가 있고, `run.json.kpis.<suite>`에 line·branch 비율이 있다.
- 검증 레벨: E2E

#### REQ-063 — 병합 집계 XML 단일 경로
- 유형: Functional / 우선순위: Must
- 수용기준: Given S08 완료, Then `S08/merged/aggregate.xml`이 있다. 포함된 스위트 목록이 `S08/merged/manifest.json`에 있고, 모든 입력 `.exec`가 같은 커밋의 classes로 리포트됐다. S09의 렌더링된 설정과 S11의 스캔 인자가 같은 파일(sha256 동일)을 가리킨다.
- 검증 레벨: E2E

#### REQ-032 — 커버리지 무결성
- 유형: Functional / 우선순위: Must
- 수용기준: Given S08 완료, Then 다음을 만족한다.
  - attributed의 커버 라인이 aggregate의 커버 라인에 포함된다(위반 0).
  - jacococli의 classId 불일치 경고가 0이다.
  - `sut.yaml.coverage.probes`에 지정한 두 TC와 두 컨트롤러의 probe 라인에서, 각 TC는 자기 probe 라인을 1개 이상 커버하고 상대 probe 라인은 0개 커버한다.
- 검증 레벨: E2E

#### REQ-033 — TC별 커버리지 화면
- 유형: Functional / 우선순위: Must
- 수용기준: Given `coverage.html`, When 헤드리스 브라우저로 TC 행 하나를 클릭하면, Then 그 TC의 커버 라인이 소스 뷰어에 하이라이트되고, 하이라이트된 라인 수가 TC JSON의 라인 수와 같다. TC 표에는 고유 커버 라인 열과 정렬·필터가 있고, TC × 클래스 히트맵이 있다.
- 검증 레벨: E2E

#### REQ-034 — 커버리지 화면 반응형
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 360px 뷰포트, Then `coverage.html`에 가로 페이지 스크롤이 없다(표는 자체 스크롤 컨테이너 안에 있다).
- 검증 레벨: E2E

### H. 분석 리포트

#### REQ-035 — hotspot 리포트
- 유형: Functional / 우선순위: Must
- 수용기준: Given S09 passed, Then run의 `hotspot/`에 `hotspots.html`과 `api_report.html`이 있고, run 페이지에서 링크된다.
- 검증 레벨: E2E

#### REQ-036 — TIA 리포트와 base 일치
- 유형: Functional / 우선순위: Must
- 수용기준: Given S10 passed, Then `tia.html`(TIA 도구 산출물)과 `scenarios.json`이 있다. 리포트에 내장된 커밋 값이 `stages/S10.json.base`(first-parent `HEAD~10`의 전체 sha)의 prefix다. TIA DB가 `work/runs/<runId>/S10/tia.db`에 있다. run 페이지에서 링크된다. (참고: base의 블랙박스 TC 수는 HEAD와 다를 수 있고, c37b2e4 기준 29개다.)
- 검증 레벨: E2E

#### REQ-037 — Sonar 전용 프로젝트 분석과 export
- 유형: Functional / 우선순위: Must
- 수용기준: Given S11 passed, Then `sonar.json`이 `sonar.schema.json`을 통과하고 다음이 성립한다.
  - projectKey = `sut.yaml.sonar.projectKey`
  - `qualityGate.status`가 있다(ERROR도 단계 성공).
  - issues와 hotspots 각각 `fetched == len(items)`, `fetched == min(total, 10000)`, `truncated == (total > fetched)`
  - 각 item에 key와 Sonar 링크가 있다.
  - `sonar.html`이 렌더링되고 run 페이지에서 링크된다.
  - 다중 페이지 fixture(가짜 API)에서도 같은 불변식이 성립한다(Unit).
  - CE 태스크가 FAILED, CANCELED이거나 10분 폴링 상한을 넘기면, 또는 `report-task.txt`가 없으면 S11은 `failed`이고 사유에 ceTaskId와 상태가 있다(가짜 API, Unit).
- 검증 레벨: E2E, Unit

#### REQ-038 — Sonar 자기 토큰 정리 (성공 경로)
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given S11 정상 종료, Then DB의 `user_tokens`에 `name='td-<runId>'` 행이 0개다.
- 검증 레벨: E2E

#### REQ-064 — Sonar 토큰 정리 (실패 경로)
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 토큰 발급 후 스캔을 강제로 실패시키는 주입(`TD_FAIL_STAGE=S11:scan`), Then `td-<runId>` 행이 0개다. Given 정리 SSH를 차단하는 주입, Then S11은 `failed`이고, 콘솔에 잔존 경고가 있으며, 해당 행의 `expiration_date`가 발급 시각 + 2시간 이하다(SSH 복구 후 테스트가 확인하고 지움).
- 검증 레벨: E2E-inj

#### REQ-065 — Sonar 토큰 사전 청소 범위
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 만료된 `td-old`와 만료되지 않은 `td-live` 행을 테스트가 넣어 둔 상태(둘 다 §0.1의 무작위 해시 규칙), When S11을 실행하면, Then `td-old`만 지워지고 `td-live`는 남는다(테스트 finally에서 지움).
- 검증 레벨: E2E-inj

#### REQ-066 — Sonar 토큰 비노출
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 주입 실행의 S11(`TD_SONAR_TOKEN_OBSERVE=<0600 파일 경로>` 훅이 토큰을 그 파일에 1회 쓰고, 테스트가 읽은 뒤 finally에서 지움), Then 다음이 성립한다.
  - 훅 파일을 뺀 `work/**` 전체와 단계 로그에서 토큰 문자열이 0건이다.
  - 스캐너 자식 프로세스의 argv에 토큰이 없다(환경 변수로만 전달).
- 검증 레벨: E2E-inj

#### REQ-039 — Sonar 장애 시 축소 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 잘못된 Sonar URL 주입(주입 실행 환경), Then S11은 `failed`, S13은 `passed`이고, 게시된 run 페이지에 S11 실패 사유가 보인다.
- 검증 레벨: E2E-inj

### I. 비교 실험

#### REQ-040 — 비교 데이터
- 유형: Functional / 우선순위: Must
- 수용기준: Given S12 passed, Then `compare.json`이 `compare.schema.json`을 통과한다.
  - 포함 지표(arm별 평균, 최소, 최대, generation별 값): 시나리오 수, 컴파일 가능 비율, undefined 비율, 통과율, 엔드포인트 커버 비율, attributed line·branch, blackbox 대비 증감, 고유 라인, 오라클 커버 분자·분모, Reservation 범위 지표, 토큰, 시간
  - 엔드포인트 분모 = `ontology-jqa.json`의 `view=false` Endpoint 수 = 기대 목록 수(17)
  - skip된 arm은 `status: skipped`와 사유로 표시된다.
- 검증 레벨: E2E

#### REQ-067 — 비교 화면 표시
- 유형: Functional / 우선순위: Must
- 수용기준: Given `compare.html`, Then arm × 지표 표, generation별 점 그래프, 판정 결과, 반복 횟수, "탐색적 관찰" 문구, 한계 서술(OWL 파생성, 모델 사전 지식)이 있다.
- 검증 레벨: E2E

#### REQ-041 — 오라클 격리와 실체성
- 유형: Functional / 우선순위: Must
- 수용기준: Given `suts/petclinic/oracle.yaml`, Then 다음이 성립한다.
  - 규칙 수가 7개 이상이고 설계 §6.12의 최소 규칙을 포함한다.
  - 각 규칙의 (class, line)이 고정 커밋에서 분기 probe가 있는 라인이다(jacoco XML로 확인).
  - 정규화한 각 규칙 `description`이 보존된 번들(E2E)과 가짜 `claude` stdin(Int)에 부분 문자열로 없다.
- 검증 레벨: E2E, Int

#### REQ-042 — 판정 규칙 계산
- 유형: Functional / 우선순위: Must
- 수용기준: Given 고정 지표 fixture(성립, 불성립, 범위 겹침, arm skip), When 판정 함수를 실행하면, Then 설계 §6.12 기준대로 `성립/불성립`, `효과 있음/차이 불명확`, `판정 불가(arm 부족)`가 나온다.
- 검증 레벨: Unit

### J. 게시와 누적

#### REQ-043 — run 게시 원자성
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given `S13:upload-first`, `S13:upload-mid`, `S13:complete`, `S13:index` 지점마다 장애를 주입한 뒤 같은 runId로 재시도하면, Then 최종적으로 run 하나만 노출된다. `_COMPLETE`가 없는 run은 인덱스에 나오지 않는다.
  - Given `_COMPLETE`가 있고 로컬 manifest 체크섬이 원격과 모두 같은 run을 재게시하면, Then 업로드를 건너뛰고 인덱스 재생성만 해서 성공한다.
  - Given `_COMPLETE`가 있고 내용이 하나라도 다른 run을 같은 runId로 재게시하면, Then S13이 실패하고 기존 객체 ETag가 그대로다.
- 검증 레벨: E2E-inj

#### REQ-044 — 이력 누적
- 유형: Functional / 우선순위: Must
- 수용기준: Given 두 번째 run 게시, Then 기준 run 객체의 ETag가 그대로이고, `runs.json`과 SUT 페이지 이력 표에 두 run이 모두 있다.
- 검증 레벨: E2E

#### REQ-045 — 인덱스 재생성 멱등
- 유형: Functional / 우선순위: Must
- 수용기준: Given 로컬 fixture 사이트 디렉터리, When 인덱스 재생성을 두 번 실행하면, Then 출력 바이트가 같다(인덱스에 실행 시각이 들어가지 않는다).
- 검증 레벨: Unit

#### REQ-046 — 게시 잠금
- 유형: Functional / 우선순위: Should
- 수용기준: Given 다른 attemptId의 잠금 객체(`<prefix>locks/publish`), When S13을 실행하면, Then 업로드 없이 실패하고 잠금 정보(attemptId, 소유자, 획득 시각)를 출력한다. `--force-unlock <attemptId>`는 잠금의 attemptId가 인자와 같을 때만 지우고(조회한 ETag로 조건부 삭제), 다르면 지우지 않고 비-0으로 종료한다. 정상 종료 후에는 잠금 객체가 없다.
- 검증 레벨: E2E-inj

#### REQ-068 — 캐시 헤더
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시 후 CloudFront 응답, Then 인덱스 HTML과 JSON의 `Cache-Control`은 `no-cache`이고, run 디렉터리 객체는 `max-age=31536000, immutable`이다.
- 검증 레벨: E2E

#### REQ-047 — 정적 호스트 서비스
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시 후, When `https://reports.<domain>/`에서 시작해 같은 호스트 링크를 새 run 페이지까지 포함해 전부 크롤링하면(자체 크롤러), Then 모두 200이고 홈에 최신 runId가 보인다.
- 검증 레벨: E2E

#### REQ-069 — S3 직접 접근 차단
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 버킷의 객체 URL, When 서명 없이 S3에 직접 요청하면, Then 403이다.
- 검증 레벨: E2E

#### REQ-048 — Lightsail 호스트 서비스
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시 후, When `https://dash.<domain>/`을 같은 방식으로 크롤링하면, Then 모두 200이고 `runs.json` 내용이 정적 호스트와 바이트 단위로 같다.
- 검증 레벨: E2E

#### REQ-070 — Lightsail 따라잡기
- 유형: Functional / 우선순위: Must
- 수용기준: Given `S13:lightsail` 주입 게시(S3와 인덱스는 성공했으므로 S13은 `degraded`, 그 run의 publish-log에 Lightsail 실패 기록), When 다음 게시를 실행하면, Then Lightsail `_test` 경로의 `runs.json`이 S3와 같아진다.
- 검증 레벨: E2E-inj

#### REQ-071 — 게시 상태의 기준 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run과 두 번째 run, Then 각 run에 대해 다음이 성립한다.
  - 게시된 `run.json`은 로컬 `run.json`과 바이트 단위로 같고, S13 상태는 `publishing`이다.
  - 최종 S13 결과는 로컬 `stages/S13.json`과 게시된 `suts/<sut>/publish-log/<runId>.json`에 있으며 서로 같다.
  - run 페이지는 S13 결과를 publish-log에서 읽어 표시한다.
- 검증 레벨: E2E

#### REQ-049 — 대시보드 홈과 SUT 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시된 사이트, Then 홈에 SUT별 최신 run의 KPI(테스트 통과율, attributed line coverage, Sonar 게이트, hotspot 1위)가 있고, SUT 페이지에 run 이력 표와 KPI 추이 차트가 있다. 각 run 페이지에 성공한 모든 리포트의 링크가 있다.
- 검증 레벨: E2E

#### REQ-050 — 멀티 SUT
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given mini-sut 설명 파일(`--sut-file tests/fixtures/mini-sut/sut.yaml`, 엔드포인트 2개 이상, per-test 확장이 달린 블랙박스 IT 2개 이상, `coverage.probes`, 자체 `auth`), Given 같은 접두에 petclinic의 `_COMPLETE` run이 있는 상태(fixture `injected_petclinic_run`: `--only S00,S01,S08,S13`), When 주입 실행 환경에서 mini-sut의 S00, S01, S08, S13을 실행하면, Then 그 환경의 홈에 SUT 2개가 나온다.
  - `pipeline/`, `site-gen/`, `e2e/harness/`, `e2e/runner/`, `ontology/`, `prompts/`, `env/` 코드에 `petclinic` 문자열과 `org.springframework.samples` 패키지 문자열이 0건이다.
- 검증 레벨: E2E-inj

#### REQ-072 — 설명 파일 값 사용
- 유형: Functional / 우선순위: Should
- 수용기준: Given `tia.range`, `sonar.projectKey`, `api.include`, `runtime.ddl`, `auth.probe`, `classes`를 기본값과 다르게 바꾼 설명 파일 fixture, When 각 값을 쓰는 단계의 인자 조립 함수를 실행하면, Then 조립된 인자에 바뀐 값이 들어간다.
- 검증 레벨: Unit

#### REQ-051 — 호스팅 정량 비교
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시 후, Then `hosting.json`이 스키마를 통과하고, 호스트마다 다음 숫자 값이 단위와 함께 있다.
  - 배포 소요 시간(초, 업로드 시작~완료)
  - TTFB 중앙값(ms, 표본 10, timeout 10초, 성공 표본만 사용, 짝수면 가운데 두 값의 평균, 실패 표본 수, 대상 URL, warm 상태 명시). 성공 표본이 7개 미만이면 값은 null이고 S13은 `degraded`다.
  - 홈 HTML 전송 시간(ms)
  - 게시 전후 서버 available 메모리(MB, Lightsail만)
  - `hosting.html`에 이 값이 표시된다.
- 검증 레벨: E2E

#### REQ-073 — 호스팅 정성 비교
- 유형: Functional / 우선순위: Must
- 수용기준: Given `hosting.json`, Then 호스트마다 다음이 비어 있지 않다.
  - 월 비용 추정: 가격표 출처, 리전, 기준일, 사용량 가정, 계산식
  - 운영 부담
  - 장애 영향 범위
  - `hosting.html`에 이 값이 표시된다.
- 검증 레벨: E2E

### K. 공유 인프라 안전

#### REQ-052 — Sonar 서버 건강
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 게시 완료, Then `https://sonar.<domain>/api/system/status`가 `UP`이고, Lightsail `free -m`의 available이 300MB 이상이다.
- 검증 레벨: E2E

#### REQ-053 — Route53 기존 레코드 보존
- 유형: Non-functional / 우선순위: Must
- 수용기준:
  - Given 적용 스크립트가 저장한 `work/infra/route53-before.json`과 `route53-after.json`, When 두 파일을 비교하면, Then before의 RRSet은 after에 전부 그대로 있고, 새 RRSet은 허용 목록(`reports`, `dash`, ACM 검증용 `_*.reports.<domain>` CNAME)뿐이다. 현재 zone에는 before의 RRSet이 지금도 있는지만 확인한다.
  - Given 대상 이름이 다른 값으로 이미 있는 상태(boto3 stub), Then 적용이 중단된다.
- 검증 레벨: E2E, Unit

#### REQ-054 — 인프라 식별자 비공개
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given `infra/local.env`(없으면 테스트 실패), Then `git check-ignore -q --no-index infra/local.env`가 성공한다. 그 파일의 `TD_AWS_ACCOUNT_ID`, `TD_LIGHTSAIL_IP`, `TD_IAM_USER`, `TD_SSH_KEY_PATH` 값(SUT 자격 증명은 제외)이 `git ls-files`의 내용, `git log -p` 전체, `work/site-mirror/**`에서 0건이다.
- 검증 레벨: Int

#### REQ-055 — aws-resource-controller 동기화
- 유형: Functional / 우선순위: Should
- 수용기준: Given Lightsail 적용 후, Then 서버의 Caddyfile과 docker-compose.yml이 `~/aws-resource-controller/sonarqube/`의 파일과 같고, 그 변경 커밋이 origin/main에 있다.
- 검증 레벨: Int

#### REQ-074 — Lightsail 변경 안전 적용
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 로컬 compose fixture(Caddy만, 서버 아님)에 잘못된 Caddyfile로 적용 스크립트를 실행하면, Then 새 파일을 마운트한 일회성 컨테이너의 validate가 실패하고, Caddyfile과 compose가 변경 전과 바이트 단위로 같게 복원된다. 정상 Caddyfile이면 적용 후 120초 안에 HTTPS 응답(로컬 fixture는 HTTP)을 확인한다.
- 검증 레벨: Int

### L. 범위 제외

#### REQ-056 — PR·머지 시 자동 실행
- 유형: Functional / 우선순위: Won't (자리만 REQ-006)

#### REQ-057 — 대시보드 접근 제어
- 유형: Non-functional / 우선순위: Won't

## 추적 매트릭스

경로는 모두 `tests/acceptance/` 기준이다.

| REQ-ID | 요구사항 | 수용 테스트 | Level | Status |
|---|---|---|---|---|
| REQ-001 | 전체 히스토리 clone·커밋 고정 | test_prepare.py::test_req001_full_clone_pinned_commit | Int | 🔴 planned |
| REQ-058 | tools.lock 완전성 | test_prepare.py::test_req058_tools_lock_complete | Int | 🔴 planned |
| REQ-002 | 단계 상태 기록 | test_run.py::test_req002_all_stages_recorded | E2E | 🔴 planned |
| REQ-003 | 종료 코드 규칙 | test_run.py::test_req003_exit_codes | E2E-inj | 🔴 planned |
| REQ-004 | 단계 선택 실행 | test_run.py::test_req004_only_marks_not_requested | Int | 🔴 planned |
| REQ-059 | 건너뜀 전파 | test_run.py::test_req059_skip_propagation | E2E-inj | 🔴 planned |
| REQ-005 | 고유 runId | test_unit_runid.py::test_req005_unique_runid | Unit | 🔴 planned |
| REQ-006 | 트리거 자리 | test_run.py::test_req006_trigger_placeholders | E2E | 🔴 planned |
| REQ-060 | 실행 시간 메타데이터 | test_run.py::test_req060_time_metadata | E2E/Unit | 🔴 planned |
| REQ-007 | 컨테이너 per-test 수집 | test_env.py::test_req007_control_endpoint_loopback | Int | 🔴 planned |
| REQ-008 | TC 수=.exec 수 게이트 | test_blackbox.py::test_req008_exec_count_gate | E2E/E2E-inj | 🔴 planned |
| REQ-009 | Docker 자원 누수 0 | test_cleanup.py::test_req009_no_resource_leak | E2E/Int | 🔴 planned |
| REQ-010 | 중단 시 정리 | test_cleanup.py::test_req010_sigint_cleanup | E2E-inj | 🔴 planned |
| REQ-011 | PID·worktree·데몬 정리 | test_cleanup.py::test_req011_pids_worktrees_daemons | E2E/E2E-inj | 🔴 planned |
| REQ-012 | 기존 BB IT 실행 | test_blackbox.py::test_req012_blackbox_artifacts | E2E | 🔴 planned |
| REQ-013 | bbtg 7개 스킬 | test_bbtg.py::test_req013_bbtg_seven_skills | E2E/Int | 🔴 planned |
| REQ-014 | 엔드포인트 완전성 | test_ontology.py::test_req014_endpoints_match_expected | E2E | 🔴 planned |
| REQ-015 | 온톨로지 스키마 | test_ontology.py::test_req015_schema_and_kinds | E2E | 🔴 planned |
| REQ-016 | 온톨로지 HTML 오프라인 | test_ontology.py::test_req016_offline_render | E2E | 🔴 planned |
| REQ-017 | 온톨로지 HTML 반응형 | test_ontology.py::test_req017_responsive_dark | E2E | 🔴 planned |
| REQ-018 | OWL 의미 대응 | test_ontology.py::test_req018_owl_correspondence | E2E/Int | 🔴 planned |
| REQ-019 | 번들 경로 검사 | test_isolation.py::test_req019_bundle_paths | E2E/Int | 🔴 planned |
| REQ-020 | 번들 내용 검사 | test_isolation.py::test_req020_bundle_content | E2E/Unit | 🔴 planned |
| REQ-021 | bbtg 허용 스키마 | test_isolation.py::test_req021_bbtg_allow_schema | E2E | 🔴 planned |
| REQ-022 | LLM 호출 격리 | test_isolation.py::test_req022_llm_isolation_captured | Int | 🔴 planned |
| REQ-023 | 세 arm·반복 | test_bdd_gen.py::test_req023_arms_and_reps | E2E | 🔴 planned |
| REQ-024 | 스냅샷 재사용·보존 | test_bdd_gen.py::test_req024_snapshot_reuse_preserve | Int | 🔴 planned |
| REQ-025 | 수리 루프 제한 | test_bdd_gen.py::test_req025_repair_bounded_captured | Int | 🔴 planned |
| REQ-061 | 생성 메타데이터 | test_bdd_gen.py::test_req061_gen_metadata_schema | E2E | 🔴 planned |
| REQ-075 | 입력 해시 안정성 | test_bdd_gen.py::test_req075_input_hash_stable | Int/E2E | 🔴 planned |
| REQ-026 | 인증 하네스 | test_harness.py::test_req026_auth_harness (→ HarnessAuthIT) | Int | 🔴 planned |
| REQ-027 | 결정적 testId | test_e2e.py::test_req027_deterministic_testids | Unit/Int | 🔴 planned |
| REQ-028 | 시나리오 수 보존 | test_e2e.py::test_req028_scenario_conservation | E2E | 🔴 planned |
| REQ-029 | undefined 비율 | test_e2e.py::test_req029_undefined_ratio | E2E | 🔴 planned |
| REQ-030 | JUnit 대체 스타일 | test_e2e.py::test_req030_junit_style | Int | 🔵 deferred (Could) |
| REQ-062 | Cucumber 리포트 게시 | test_e2e.py::test_req062_cucumber_reports | E2E | 🔴 planned |
| REQ-031 | 귀속·집계 커버리지 | test_coverage.py::test_req031_suite_coverage | E2E | 🔴 planned |
| REQ-063 | 병합 집계 XML | test_coverage.py::test_req063_merged_aggregate | E2E | 🔴 planned |
| REQ-032 | 커버리지 무결성 | test_coverage.py::test_req032_integrity | E2E | 🔴 planned |
| REQ-033 | TC별 커버리지 화면 | test_coverage.py::test_req033_per_tc_view | E2E | 🔴 planned |
| REQ-034 | 커버리지 반응형 | test_coverage.py::test_req034_responsive | E2E | 🔴 planned |
| REQ-035 | hotspot 리포트 | test_reports.py::test_req035_hotspot | E2E | 🔴 planned |
| REQ-036 | TIA base 일치 | test_reports.py::test_req036_tia_base | E2E | 🔴 planned |
| REQ-037 | Sonar export | test_reports.py::test_req037_sonar_export | E2E/Unit | 🔴 planned |
| REQ-038 | 토큰 정리(성공) | test_sonar.py::test_req038_own_token_removed | E2E | 🔴 planned |
| REQ-064 | 토큰 정리(실패) | test_sonar.py::test_req064_token_cleanup_on_failure | E2E-inj | 🔴 planned |
| REQ-065 | 사전 청소 범위 | test_sonar.py::test_req065_preclean_expired_only | E2E-inj | 🔴 planned |
| REQ-066 | 토큰 비노출 | test_sonar.py::test_req066_token_not_leaked | E2E-inj | 🔴 planned |
| REQ-039 | Sonar 장애 축소 게시 | test_sonar.py::test_req039_degraded_publish | E2E-inj | 🔴 planned |
| REQ-040 | 비교 데이터 | test_compare.py::test_req040_compare_json | E2E | 🔴 planned |
| REQ-067 | 비교 화면 | test_compare.py::test_req067_compare_html | E2E | 🔴 planned |
| REQ-041 | 오라클 격리·실체성 | test_compare.py::test_req041_oracle | E2E | 🔴 planned |
| REQ-042 | 판정 규칙 | test_unit_verdict.py::test_req042_verdict_rules | Unit | 🔴 planned |
| REQ-043 | 게시 원자성 | test_publish.py::test_req043_atomic_publish | E2E-inj | 🔴 planned |
| REQ-044 | 이력 누적 | test_publish.py::test_req044_history_accumulates | E2E | 🔴 planned |
| REQ-045 | 인덱스 멱등 | test_unit_index.py::test_req045_idempotent | Unit | 🔴 planned |
| REQ-046 | 게시 잠금 | test_publish.py::test_req046_lock | E2E-inj | 🔴 planned |
| REQ-068 | 캐시 헤더 | test_hosting.py::test_req068_cache_headers | E2E | 🔴 planned |
| REQ-047 | 정적 호스트 | test_hosting.py::test_req047_static_host_crawl | E2E | 🔴 planned |
| REQ-069 | S3 직접 접근 차단 | test_hosting.py::test_req069_s3_direct_forbidden | E2E | 🔴 planned |
| REQ-048 | Lightsail 호스트 | test_hosting.py::test_req048_lightsail_crawl | E2E | 🔴 planned |
| REQ-070 | Lightsail 따라잡기 | test_publish.py::test_req070_lightsail_catch_up | E2E-inj | 🔴 planned |
| REQ-071 | 게시 상태 기준 파일 | test_publish.py::test_req071_publish_status_files | E2E | 🔴 planned |
| REQ-049 | 홈·SUT 페이지 | test_site.py::test_req049_home_sut_run_pages | E2E | 🔴 planned |
| REQ-050 | 멀티 SUT | test_site.py::test_req050_multi_sut | E2E-inj | 🔴 planned |
| REQ-072 | 설명 파일 값 사용 | test_unit_config.py::test_req072_descriptor_driven | Unit | 🔴 planned |
| REQ-051 | 호스팅 정량 비교 | test_hosting.py::test_req051_quantitative | E2E | 🔴 planned |
| REQ-073 | 호스팅 정성 비교 | test_hosting.py::test_req073_qualitative | E2E | 🔴 planned |
| REQ-052 | Sonar 서버 건강 | test_infra.py::test_req052_sonar_healthy | E2E | 🔴 planned |
| REQ-053 | Route53 보존 | test_infra.py::test_req053_route53_preserved | E2E/Unit | 🔴 planned |
| REQ-054 | 식별자 비공개 | test_infra.py::test_req054_identifiers_private | Int | 🔴 planned |
| REQ-055 | arc 레포 동기화 | test_infra.py::test_req055_arc_repo_synced | Int | 🔴 planned |
| REQ-074 | Lightsail 안전 적용 | test_infra.py::test_req074_caddy_apply_rollback | Int | 🔴 planned |
| REQ-056 | CI 자동 실행 | – | – | 🔵 out-of-scope (Won't) |
| REQ-057 | 접근 제어 | – | – | 🔵 out-of-scope (Won't) |

Coverage: 0/72 green (0%) — target 100% (대상: Must 65 + Should 7). 제외: Could 1 deferred(🔵 REQ-030), Won't 2(🔵 REQ-056, REQ-057).

## 자기검토 결과

- **v1 → v2 변경**
  - 쪼갠 것: REQ-001→001/058, REQ-038→038/064/065/066, REQ-040→040/067, REQ-051→051/073
  - 추가한 것: REQ-059~074
  - ID 재번호는 하지 않았다.
- **설계 AT ↔ REQ 대응**
  - AT-01 → 002/003
  - AT-02 → 014
  - AT-03 → 016
  - AT-04 → 019~022
  - AT-05 → 028
  - AT-06 → 032
  - AT-07 → 035~037
  - AT-08 → 038/064/065
  - AT-09 → 009/010/011
  - AT-10 → 047/048/068
  - AT-11 → 043/044
  - AT-12 → 050
  - AT-13 → 040/067
  - AT-14 → 052/053
  - AT-15 → 039
  - AT-16 → 008
- **이번 범위에서 수용 테스트를 두지 않는 설계 항목**(관측 가치가 낮거나 다른 REQ에 흡수됨)
  - run 크기 KPI와 200MB 경고: 표시만 하고 REQ-049 화면에 포함
  - `teardown.sh`: 수동 철거 절차라서 자동 테스트하지 않음
  - testkit과 어댑터 중 어느 쪽을 썼는지의 기록: REQ-061 메타에 포함
- 각 REQ는 하나의 행위이고, 측정 가능한 Given-When-Then이 있으며, 판정 근거가 구현의 자기 보고에만 기대지 않는다(§0 원칙).
- Must 65, Should 7(REQ-004, 017, 034, 046, 055, 072, 074), Could 1, Won't 2. 총 75개.
- v2.1: 재리뷰 반영으로 REQ-075를 추가하고 REQ-002, 003, 005, 007, 008, 011, 014, 019~021, 023, 024, 027~029, 037, 041, 043, 046, 050, 051, 053, 054, 059, 060, 065, 066, 070, 071을 보정했다.
