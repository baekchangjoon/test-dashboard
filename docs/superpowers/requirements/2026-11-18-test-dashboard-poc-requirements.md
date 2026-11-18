# test-dashboard 실증(PoC) 요구사항명세

> 출처(design spec): docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md
> 완료 정의(DoD): 커버리지 대상 요구사항이 모두 1개 이상의 통과 수용 테스트를 가진다(대상 매트릭스 전부 green).

수용 테스트는 `tests/acceptance/`(pytest)에 둔다. 테스트 함수 이름은 `test_req<NNN>_<요약>`이다. 레벨 표기는 다음과 같다.
- **E2E**: 실제 `run-all.sh` 실행 산출물이나 배포 URL을 블랙박스로 검사한다.
- **E2E-inj**: 단계를 따로 실행하면서 장애나 신호를 주입한다.
- **Int**: 단일 단계 또는 스크립트를 실제 도구와 함께 실행한다.

## 요구사항 목록

### A. 실행 골격

#### REQ-001 — SUT 준비와 커밋 고정
- 유형: Functional / 우선순위: Must
- 수용기준: Given `suts/petclinic/sut.yaml`, When S00을 실행하면, Then 전체 히스토리 clone(`git rev-list --count HEAD` > 1000)과 `run.json.commit` = clone HEAD sha가 있고, `tools.lock`에 pjacoco, jacococli(내장 jacoco-core와 같은 버전), jQA와 Spring 플러그인, hotspot, TIA, bbtg 버전이 모두 기록된다.
- 검증 레벨: Int

#### REQ-002 — 단계 상태 기록
- 유형: Functional / 우선순위: Must
- 수용기준: Given 완료된 run, When `run.json`을 읽으면, Then S00~S13 14개 키가 모두 있고, 각 상태는 `passed|failed|degraded|skipped` 중 하나이며, `passed`가 아닌 상태에는 비어 있지 않은 `reason`이 있다.
- 검증 레벨: E2E

#### REQ-003 — run-all 종료 코드 규칙
- 유형: Functional / 우선순위: Must
- 수용기준: Given S00·S13 이외 단계가 하나 실패한 run, When `run-all.sh`가 끝나면, Then 종료 코드는 2다. Given 전부 passed/degraded, Then 0이다. Given S00 실패, Then 1이다.
- 검증 레벨: E2E-inj

#### REQ-004 — 단계 선택 실행
- 유형: Functional / 우선순위: Should
- 수용기준: Given `run-all.sh petclinic --only S00,S01`, When 실행하면, Then 나머지 단계는 `skipped`이고 `reason`은 `not-requested`다.
- 검증 레벨: Int

#### REQ-005 — 고유 runId
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 커밋에서 같은 초에 runId를 2개 만들면, Then 둘은 다르고 형식은 `^\d{8}-\d{6}-[0-9a-f]{7}-(manual|pr|merge)-[0-9a-f]{4}$`이다.
- 검증 레벨: Int(단위 수준)

#### REQ-006 — 트리거 자리 마련
- 유형: Functional / 우선순위: Must
- 수용기준: Given 수동 run, When `run.json`을 읽으면, Then `trigger="manual"`이고 `pr` 키가 있다(null).
- 검증 레벨: E2E

### B. SUT 실행 환경과 자원 정리

#### REQ-007 — 컨테이너 SUT에서 per-test 수집 가능
- 유형: Functional / 우선순위: Must
- 수용기준: Given SUT 컨테이너, When 기동하면, Then 제어 엔드포인트 호스트 포트가 `127.0.0.1`에만 게시되고(`docker compose port` 결과), 호스트에서 `/__coverage__/test/start`·`stop` 호출이 2xx를 반환한다.
- 검증 레벨: Int

#### REQ-008 — TC 수와 .exec 수 일치 게이트
- 유형: Functional / 우선순위: Must
- 수용기준: Given S01 완료, When JUnit XML의 TC 수와 per-test `.exec` 수를 비교하면, Then 둘이 같다(현재 35). Given 제어 URL이 끊긴 실행(주입), Then 그 단계는 `failed`다.
- 검증 레벨: E2E, E2E-inj

#### REQ-009 — 컨테이너·네트워크·볼륨 누수 0
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 완료된 run, When `docker ps -a`, `docker network ls`, `docker volume ls`를 `--filter label=test-run=td-<runId>`로 조회하면, Then 모두 0건이다.
- 검증 레벨: E2E

#### REQ-010 — 중단 시에도 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given S01 실행 중, When SIGINT를 보내면, Then 프로세스가 끝난 뒤 REQ-009의 조회가 0건이고, 그 단계가 기록한 PID가 모두 종료된 상태다.
- 검증 레벨: E2E-inj

#### REQ-011 — 백그라운드 프로세스와 worktree 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 완료된 run, When `work/runs/<runId>/pids/*`의 PID와 `git worktree list`를 확인하면, Then 살아 있는 PID는 0이고 TIA base worktree는 목록에 없다.
- 검증 레벨: E2E

### C. 기존 블랙박스 IT와 bbtg

#### REQ-012 — 기존 블랙박스 IT 실행
- 유형: Functional / 우선순위: Must
- 수용기준: Given S01 완료, Then JUnit XML과 TC별 `.exec`/`.json`, `aggregate.exec`가 `work/runs/<runId>/S01/blackbox/`에 있다.
- 검증 레벨: E2E

#### REQ-013 — bbtg 산출물 CLI 생성
- 유형: Functional / 우선순위: Must
- 수용기준: Given S02 완료, Then `bbtg/manifest.json`에 호출 목록과 종료 코드가 있다. inspect-stack, scan-test-assets, inspect-auth와 `@RestController`별 dependency-map·find-external-calls 산출물이 있다. SUT clone에는 `.bbtg/`가 남아 있지 않다. 호출 기록에 `claude`가 없다.
- 검증 레벨: E2E

### D. 온톨로지

#### REQ-014 — jQA 엔드포인트 완전성
- 유형: Functional / 우선순위: Must
- 수용기준: Given S03 완료, When `ontology-jqa.json`의 `kind=Endpoint`, `props.view=false` 집합(메서드+정규화 경로)을 SUT 소스의 `/api/**` 매핑 정적 추출 결과와 비교하면, Then 두 집합이 같다.
- 검증 레벨: E2E

#### REQ-015 — 온톨로지 스키마
- 유형: Functional / 우선순위: Must
- 수용기준: Given `ontology-jqa.json`과 `ontology-owl.json`, When JSON Schema(`site-gen/schemas/ontology.schema.json`)로 검증하면, Then 둘 다 통과하고 `meta.commit` = `run.json.commit`이다.
- 검증 레벨: E2E

#### REQ-016 — 온톨로지 HTML 오프라인 동작
- 유형: Functional / 우선순위: Must
- 수용기준: Given `ontology/jqa.html`, When 네트워크를 차단한 헤드리스 브라우저로 열면, Then 콘솔 오류가 0이고 렌더링된 노드 수가 JSON 노드 수와 같다.
- 검증 레벨: E2E

#### REQ-017 — 온톨로지 HTML 반응형
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 360px 폭 뷰포트, When 열면, Then 가로 스크롤이 없고(`scrollWidth <= innerWidth`) 속성 패널이 그래프 아래에 온다. `prefers-color-scheme: dark`에서 배경색이 바뀐다.
- 검증 레벨: E2E

#### REQ-018 — OWL 온톨로지 생성과 검증
- 유형: Functional / 우선순위: Must
- 수용기준: Given S05 완료, Then `ontology-owl.ttl`이 rdflib로 파싱되고, pySHACL 검증이 conforms=true이며, `owl:Class`가 1개 이상 있다.
- 검증 레벨: E2E

### E. BDD 생성 (입력 오염 차단)

#### REQ-019 — 입력 번들 경로 검사
- 유형: Functional / 우선순위: Must
- 수용기준: Given 각 arm의 번들, Then 모든 파일이 허용 목록 안에 있다. Given 번들에 SUT `docs/` 파일을 넣으면(주입), When S06을 실행하면, Then 생성 전에 실패한다.
- 검증 레벨: E2E, Int

#### REQ-020 — 입력 번들 내용 검사
- 유형: Functional / 우선순위: Must
- 수용기준: Given 각 arm의 번들, Then SUT `src/**` 파일과 공백 정규화 후 5줄 이상 연속 일치하는 블록이 없다. Given SUT 소스 6줄을 번들 JSON 문자열에 넣으면(주입), Then S06이 실패한다.
- 검증 레벨: E2E, Int

#### REQ-021 — bbtg 원문 필드 제거
- 유형: Functional / 우선순위: Must
- 수용기준: Given 정제된 bbtg 산출물, Then `interceptor_sources[].source` 같은 원문 필드가 없고, 제거한 필드 경로 목록이 `bdd-gen.json.strippedFields`에 있다.
- 검증 레벨: E2E

#### REQ-022 — LLM 호출 격리
- 유형: Functional / 우선순위: Must
- 수용기준: Given `bdd-gen.json`, Then 기록된 `claude` 호출 플래그가 모든 도구를 비활성화하고, cwd가 번들 임시 디렉터리다.
- 검증 레벨: E2E

#### REQ-023 — 세 arm과 반복 생성
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기본 설정 run, Then `e2e/generated/petclinic/{base,jqa,owl}/`에 각 3개 genId가 있다. 반복을 줄였다면 `run.json.arms.reps`와 `compare.html`에 실제 횟수가 표기된다.
- 검증 레벨: E2E

#### REQ-024 — 스냅샷 보존
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기존 genId 디렉터리, When `--regenerate`로 다시 실행하면, Then 기존 디렉터리의 파일 해시가 그대로이고 새 genId가 추가된다.
- 검증 레벨: Int

#### REQ-025 — 수리 루프 제한
- 유형: Functional / 우선순위: Must
- 수용기준: Given `bdd-gen.json`, Then generation마다 `repairs` ≤ 2이고, 수리 프롬프트 입력에는 컴파일러 출력과 dry-run undefined 목록만 있다(SUT 응답 본문 없음, 기록된 입력 종류로 확인).
- 검증 레벨: E2E

### F. E2E 하네스와 실행

#### REQ-026 — 인증 하네스
- 유형: Functional / 우선순위: Must
- 수용기준: Given SUT 기동, When 하네스 `authed()`로 `GET /api/vets`를 호출하면, Then 200이다. `anonymous()`로 호출하면 401이다.
- 검증 레벨: Int

#### REQ-027 — 결정적 testId
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 generation을 두 번 실행하면, Then testId 집합이 같고, 모든 testId가 `^E2E_[a-z]+_[0-9a-f]+_[A-Za-z0-9_]+#L\d+$`에 맞는다.
- 검증 레벨: E2E

#### REQ-028 — 시나리오 수 보존
- 유형: Functional / 우선순위: Must
- 수용기준: Given generation별 결과, Then `.feature`의 시나리오 수 = Cucumber 결과 시나리오 수(`uncompilable` 포함) = `coverage.html` TC 행 수다. 실행된 시나리오 수 = `.exec` 수다. `@ignore`·`@Disabled`는 0개다.
- 검증 레벨: E2E

#### REQ-029 — dry-run 지표 기록
- 유형: Functional / 우선순위: Should
- 수용기준: Given generation별 결과, Then `undefinedRatio`(dry-run 기준, 분모 = 전체 시나리오)가 기록된다.
- 검증 레벨: E2E

#### REQ-030 — JUnit 대체 스타일
- 유형: Functional / 우선순위: Could
- 수용기준: Given `--style junit`, When S06·S07을 실행하면, Then JUnit 테스트가 생성·실행되고 `run.json.arms.style="junit"`이다.
- 검증 레벨: Int

### G. 커버리지

#### REQ-031 — 스위트별 귀속·집계 커버리지
- 유형: Functional / 우선순위: Must
- 수용기준: Given S08 완료, Then 스위트(blackbox와 각 genId)마다 attributed와 aggregate의 XML·CSV가 있고, `run.json.kpis.<suite>`에 line·branch 비율이 있다.
- 검증 레벨: E2E

#### REQ-032 — 커버리지 무결성
- 유형: Functional / 우선순위: Must
- 수용기준: Given S08 완료, Then (a) attributed의 커버 라인 ⊆ aggregate의 커버 라인(위반 0), (b) jacococli classId 불일치 경고 0, (c) 교차 오염 탐침 TC 두 개가 상대 컨트롤러 라인을 0개 커버한다.
- 검증 레벨: E2E

#### REQ-033 — TC별 커버리지 화면
- 유형: Functional / 우선순위: Must
- 수용기준: Given `coverage.html`, When 헤드리스 브라우저로 TC 행 하나를 클릭하면, Then 그 TC의 커버 라인이 소스 뷰어에 하이라이트되고, 하이라이트된 라인 수가 TC JSON의 라인 수와 같다. TC 표에 고유 커버 라인 열이 있다.
- 검증 레벨: E2E

#### REQ-034 — 커버리지 화면 반응형
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 360px 뷰포트, Then `coverage.html`에 가로 페이지 스크롤이 없다(표는 자체 스크롤 컨테이너 안에 있다).
- 검증 레벨: E2E

### H. 분석 리포트

#### REQ-035 — hotspot 리포트
- 유형: Functional / 우선순위: Must
- 수용기준: Given S09 passed, Then run의 `hotspot/` 아래에 도구 HTML과 API 리포트가 있고, 렌더링된 설정의 `analysis.jacocoReportPath`가 S08 aggregate XML을 가리킨다.
- 검증 레벨: E2E

#### REQ-036 — TIA 리포트와 base 일치
- 유형: Functional / 우선순위: Must
- 수용기준: Given S10 passed, Then `tia.html`과 `scenarios.json`이 있고, 리포트에 표시된 base 커밋이 사전 검사에서 해석한 first-parent `HEAD~10` sha와 같으며, TIA DB가 `work/runs/<runId>/tia/tia.db`에 있다.
- 검증 레벨: E2E

#### REQ-037 — Sonar 전용 프로젝트 분석과 export
- 유형: Functional / 우선순위: Must
- 수용기준: Given S11 passed, Then `sonar.json`에 projectKey `spring-petclinic-td`, 품질 게이트 상태, 측정값, 그리고 issues·hotspots의 `total`, `fetched`, `truncated`가 있다. `sonar.html`이 렌더링된다.
- 검증 레벨: E2E

#### REQ-038 — Sonar 임시 토큰 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given S11 종료(성공·실패 모두), When DB에서 `user_tokens`의 `name LIKE 'td-%'`를 조회하면, Then 0행이다. Given 미리 넣어 둔 잔존 `td-old` 행, When S11을 실행하면, Then 사전 청소가 지운다.
- 검증 레벨: E2E, E2E-inj

#### REQ-039 — Sonar 장애 시 축소 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 잘못된 Sonar URL(주입), When run을 실행하면, Then S11은 `failed`이고 S13은 `passed`이며, 게시된 run 페이지에 S11 실패 사유가 보인다.
- 검증 레벨: E2E-inj

### I. 비교 실험

#### REQ-040 — 비교 리포트
- 유형: Functional / 우선순위: Must
- 수용기준: Given S12 passed, Then `compare.html`과 `compare.json`에 세 arm 각각의 지표가 있다(시나리오 수, 컴파일 가능 비율, undefined 비율, 통과율, 엔드포인트 커버 비율, attributed line·branch, blackbox 대비 증감, 고유 라인, 오라클 커버 비율, Reservation 범위 지표, 토큰·시간). 평균과 범위, 반복 횟수, 판정 결과, "탐색적 관찰" 문구도 있다.
- 검증 레벨: E2E

#### REQ-041 — 오라클 격리
- 유형: Functional / 우선순위: Must
- 수용기준: Given `suts/petclinic/oracle.yaml`, Then 어떤 arm의 번들에도 오라클 파일이나 그 규칙 문구가 없고(REQ-020 검사기에 오라클도 대조 대상으로 넣음), `compare.json`의 오라클 커버 비율이 0~1 값이다.
- 검증 레벨: E2E

#### REQ-042 — 판정 규칙 계산
- 유형: Functional / 우선순위: Must
- 수용기준: Given 고정 지표 fixture(성립 사례, 불성립 사례, 범위 겹침 사례), When 판정 함수를 실행하면, Then 설계 §6.12의 기준대로 `성립/불성립`, `효과 있음/차이 불명확`이 나온다.
- 검증 레벨: Int(단위 수준)

### J. 게시와 누적

#### REQ-043 — run 디렉터리 불변
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시된 run, When 같은 runId로 다시 게시하면, Then S13이 실패하고 S3 객체 ETag가 그대로다.
- 검증 레벨: E2E-inj

#### REQ-044 — 이력 누적
- 유형: Functional / 우선순위: Must
- 수용기준: Given 두 번째 run 게시, Then 첫 run 객체들의 ETag가 그대로이고 `runs.json`과 SUT 페이지 이력 표에 두 run이 모두 있다.
- 검증 레벨: E2E

#### REQ-045 — 인덱스 재생성 멱등
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 S3 상태, When 인덱스 재생성을 두 번 실행하면, Then 출력 바이트가 같다.
- 검증 레벨: Int

#### REQ-046 — 게시 잠금
- 유형: Functional / 우선순위: Should
- 수용기준: Given S3 `locks/publish`가 유효한 상태, When S13을 실행하면, Then 업로드 없이 실패한다. 정상 종료 후에는 잠금 객체가 없다.
- 검증 레벨: E2E-inj

#### REQ-047 — 정적 호스트 서비스
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시 후, When `https://reports.<domain>/`과 새 run 페이지를 요청하면, Then 200이고 링크 검사기가 내부 링크 깨짐 0건을 보고한다. 인덱스 응답의 `Cache-Control`은 `no-cache`이고, 최신 runId가 보인다.
- 검증 레벨: E2E

#### REQ-048 — Lightsail 호스트 서비스
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시 후, When `https://dash.<domain>/`과 새 run 페이지를 요청하면, Then 200이고 링크 깨짐이 0건이며, 정적 호스트와 같은 `runs.json` 내용이 나온다.
- 검증 레벨: E2E

#### REQ-049 — 대시보드 홈과 SUT 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시된 사이트, Then 홈에 SUT별 최신 run의 KPI(테스트 통과율, attributed line coverage, Sonar 게이트, hotspot 1위)가 있고, SUT 페이지에 run 이력 표와 KPI 추이 차트가 있다.
- 검증 레벨: E2E

#### REQ-050 — 멀티 SUT
- 유형: Functional / 우선순위: Must
- 수용기준: Given `tests/fixtures/mini-sut`와 그 설명 파일, When S00, S01, S08, S13을 실행하면, Then 홈에 SUT 2개가 나온다. `pipeline/`, `site-gen/`, `e2e/harness/`, `e2e/runner/` 코드에 `petclinic` 문자열이 0건이다.
- 검증 레벨: E2E

#### REQ-051 — 호스팅 비교 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given 게시 후, Then `hosting.html`에 두 호스트 각각의 배포 소요 시간, TTFB 10회 중앙값, 페이지 전송 시간, 월 비용 추정, 운영 부담, 장애 영향 범위, 게시 전후 서버 메모리가 실측값으로 있다.
- 검증 레벨: E2E

### K. 공유 인프라 안전

#### REQ-052 — Sonar 서버 건강
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 게시 완료, Then `https://sonar.<domain>/api/system/status`가 `UP`이고, Lightsail `free -m`의 available이 300MB 이상이다.
- 검증 레벨: E2E

#### REQ-053 — Route53 대상 외 레코드 불변
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 변경 전 RRSet 스냅샷, When 인프라 적용 후 비교하면, Then `reports`, `dash` 외 RRSet은 이름·타입·값·TTL이 모두 같다. Given 대상 이름이 다른 값으로 이미 있으면, Then 적용이 중단된다.
- 검증 레벨: E2E, Int

#### REQ-054 — 인프라 식별자 비공개
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 레포의 추적 파일(`git ls-files`), When `infra/local.env`의 값(계정 ID, IP, IAM 사용자명)을 grep하면, Then 0건이다.
- 검증 레벨: Int

#### REQ-055 — aws-resource-controller 동기화
- 유형: Functional / 우선순위: Should
- 수용기준: Given Lightsail 적용 후, When 서버의 Caddyfile과 docker-compose.yml을 `~/aws-resource-controller/sonarqube/`의 파일과 비교하면, Then 같고 해당 커밋이 origin/main에 있다.
- 검증 레벨: Int

### L. 범위 제외

#### REQ-056 — PR·머지 시 자동 실행
- 유형: Functional / 우선순위: Won't (이번 범위 제외, 자리만 REQ-006)

#### REQ-057 — 대시보드 접근 제어
- 유형: Non-functional / 우선순위: Won't

## 추적 매트릭스

| REQ-ID | 요구사항 | 수용 테스트 | Level | Status |
|---|---|---|---|---|
| REQ-001 | SUT 준비와 커밋 고정 | tests/acceptance/test_prepare.py::test_req001_prepare_pins_commit_and_tools | Int | 🔴 planned |
| REQ-002 | 단계 상태 기록 | test_run.py::test_req002_all_stages_recorded | E2E | 🔴 planned |
| REQ-003 | 종료 코드 규칙 | test_run.py::test_req003_exit_codes | E2E-inj | 🔴 planned |
| REQ-004 | 단계 선택 실행 | test_run.py::test_req004_only_marks_not_requested | Int | 🔴 planned |
| REQ-005 | 고유 runId | tests/unit/test_runid.py::test_req005_unique_runid | Int | 🔴 planned |
| REQ-006 | 트리거 자리 | test_run.py::test_req006_trigger_placeholders | E2E | 🔴 planned |
| REQ-007 | 컨테이너 per-test 수집 | test_env.py::test_req007_control_endpoint_loopback | Int | 🔴 planned |
| REQ-008 | TC 수=.exec 수 게이트 | test_blackbox.py::test_req008_exec_count_matches_tc_count | E2E | 🔴 planned |
| REQ-009 | 자원 누수 0 | test_cleanup.py::test_req009_no_labeled_resources | E2E | 🔴 planned |
| REQ-010 | 중단 시 정리 | test_cleanup.py::test_req010_sigint_cleans_up | E2E-inj | 🔴 planned |
| REQ-011 | PID·worktree 정리 | test_cleanup.py::test_req011_no_pids_or_worktrees | E2E | 🔴 planned |
| REQ-012 | 기존 BB IT 실행 | test_blackbox.py::test_req012_blackbox_artifacts | E2E | 🔴 planned |
| REQ-013 | bbtg CLI 산출물 | test_bbtg.py::test_req013_bbtg_manifest | E2E | 🔴 planned |
| REQ-014 | jQA 엔드포인트 완전성 | test_ontology.py::test_req014_endpoints_complete | E2E | 🔴 planned |
| REQ-015 | 온톨로지 스키마 | test_ontology.py::test_req015_schema_valid | E2E | 🔴 planned |
| REQ-016 | 온톨로지 HTML 오프라인 | test_ontology.py::test_req016_offline_render | E2E | 🔴 planned |
| REQ-017 | 온톨로지 HTML 반응형 | test_ontology.py::test_req017_responsive_dark | E2E | 🔴 planned |
| REQ-018 | OWL 생성·검증 | test_ontology.py::test_req018_owl_shacl | E2E | 🔴 planned |
| REQ-019 | 번들 경로 검사 | test_bdd_gen.py::test_req019_bundle_paths | E2E/Int | 🔴 planned |
| REQ-020 | 번들 내용 검사 | test_bdd_gen.py::test_req020_bundle_content | E2E/Int | 🔴 planned |
| REQ-021 | bbtg 원문 필드 제거 | test_bdd_gen.py::test_req021_stripped_fields | E2E | 🔴 planned |
| REQ-022 | LLM 호출 격리 | test_bdd_gen.py::test_req022_toolless_invocation | E2E | 🔴 planned |
| REQ-023 | 세 arm·반복 생성 | test_bdd_gen.py::test_req023_arms_and_reps | E2E | 🔴 planned |
| REQ-024 | 스냅샷 보존 | test_bdd_gen.py::test_req024_regenerate_preserves | Int | 🔴 planned |
| REQ-025 | 수리 루프 제한 | test_bdd_gen.py::test_req025_repair_bounded | E2E | 🔴 planned |
| REQ-026 | 인증 하네스 | e2e/harness HarnessAuthIT (`@DisplayName("REQ-026: …")`) | Int | 🔴 planned |
| REQ-027 | 결정적 testId | test_e2e.py::test_req027_deterministic_testids | E2E | 🔴 planned |
| REQ-028 | 시나리오 수 보존 | test_e2e.py::test_req028_scenario_conservation | E2E | 🔴 planned |
| REQ-029 | dry-run 지표 | test_e2e.py::test_req029_undefined_ratio | E2E | 🔴 planned |
| REQ-030 | JUnit 대체 스타일 | test_e2e.py::test_req030_junit_style | Int | 🔵 deferred (Could) |
| REQ-031 | 귀속·집계 커버리지 | test_coverage.py::test_req031_suite_coverage | E2E | 🔴 planned |
| REQ-032 | 커버리지 무결성 | test_coverage.py::test_req032_integrity | E2E | 🔴 planned |
| REQ-033 | TC별 커버리지 화면 | test_coverage.py::test_req033_per_tc_view | E2E | 🔴 planned |
| REQ-034 | 커버리지 화면 반응형 | test_coverage.py::test_req034_responsive | E2E | 🔴 planned |
| REQ-035 | hotspot 리포트 | test_reports.py::test_req035_hotspot | E2E | 🔴 planned |
| REQ-036 | TIA 리포트 base 일치 | test_reports.py::test_req036_tia_base | E2E | 🔴 planned |
| REQ-037 | Sonar 분석·export | test_reports.py::test_req037_sonar_export | E2E | 🔴 planned |
| REQ-038 | Sonar 토큰 정리 | test_sonar.py::test_req038_token_cleanup | E2E/E2E-inj | 🔴 planned |
| REQ-039 | Sonar 장애 축소 게시 | test_sonar.py::test_req039_degraded_publish | E2E-inj | 🔴 planned |
| REQ-040 | 비교 리포트 | test_compare.py::test_req040_compare_report | E2E | 🔴 planned |
| REQ-041 | 오라클 격리 | test_compare.py::test_req041_oracle_isolated | E2E | 🔴 planned |
| REQ-042 | 판정 규칙 | tests/unit/test_verdict.py::test_req042_verdict_rules | Int | 🔴 planned |
| REQ-043 | run 불변 | test_publish.py::test_req043_rerun_rejected | E2E-inj | 🔴 planned |
| REQ-044 | 이력 누적 | test_publish.py::test_req044_history_accumulates | E2E | 🔴 planned |
| REQ-045 | 인덱스 멱등 | tests/unit/test_index.py::test_req045_idempotent | Int | 🔴 planned |
| REQ-046 | 게시 잠금 | test_publish.py::test_req046_lock | E2E-inj | 🔴 planned |
| REQ-047 | 정적 호스트 | test_hosting.py::test_req047_static_host | E2E | 🔴 planned |
| REQ-048 | Lightsail 호스트 | test_hosting.py::test_req048_lightsail_host | E2E | 🔴 planned |
| REQ-049 | 홈·SUT 페이지 | test_site.py::test_req049_home_and_sut_page | E2E | 🔴 planned |
| REQ-050 | 멀티 SUT | test_site.py::test_req050_multi_sut | E2E | 🔴 planned |
| REQ-051 | 호스팅 비교 페이지 | test_hosting.py::test_req051_hosting_compare | E2E | 🔴 planned |
| REQ-052 | Sonar 서버 건강 | test_infra.py::test_req052_sonar_healthy | E2E | 🔴 planned |
| REQ-053 | Route53 불변 | test_infra.py::test_req053_route53_untouched | E2E/Int | 🔴 planned |
| REQ-054 | 식별자 비공개 | test_infra.py::test_req054_no_identifiers_tracked | Int | 🔴 planned |
| REQ-055 | arc 레포 동기화 | test_infra.py::test_req055_arc_repo_synced | Int | 🔴 planned |
| REQ-056 | CI 자동 실행 | – | – | 🔵 out-of-scope (Won't) |
| REQ-057 | 접근 제어 | – | – | 🔵 out-of-scope (Won't) |

Coverage: 0/54 green (0%) — target 100% (대상: Must 48 + Should 6). 제외: Could 1 deferred(🔵 REQ-030), Won't 2(🔵 REQ-056, REQ-057).

## 자기검토 결과
- 설계 §2~§8의 행위·계약·제약을 모두 REQ로 옮겼다. 설계 AT-01~AT-16은 REQ-002/003, 014, 016, 019~022, 028, 032, 035~037, 038, 047/048, 044/043, 050, 040, 052/053, 039, 008로 대응한다.
- 복합 요구는 쪼갰다. 예: 정적 호스트와 Lightsail 호스트, 경로 검사와 내용 검사, 토큰 정리와 장애 축소 게시.
- 모든 REQ에 측정 가능한 수용기준이 있다. Won't 항목만 수용기준이 없다.
- REQ-030(JUnit 대체)은 Cucumber 호환이 확인돼 Could로 낮추고 연기했다. 대체 발동 조건(§6.8)이 실제로 충족되면 역전파 절차로 Should로 올린다.
