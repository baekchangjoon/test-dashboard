# test-dashboard 화면 재설계 요구사항명세

> 출처(design spec): docs/superpowers/specs/2026-11-22-dashboard-ui-design.md (v2, 승인 2026-11-22)
> 완료 정의(DoD): 커버리지 대상 요구사항마다 매트릭스에 지정된 검증 테스트가 하나 이상 있고, 그 테스트가 모두 통과한다(대상 매트릭스 전부 green). 아울러 §3에 적은 PoC 요구사항의 개정된 테스트와, 개정하지 않은 PoC 매트릭스가 계속 통과한다.
> 버전: v1

## 0. 규약

- REQ-ID는 PoC 요구사항명세(REQ-001~075)에 이어 REQ-076부터 쓴다. 번호를 다시 쓰지 않는다.
- 검증 테스트는 pytest이고 `tests/acceptance/`에 둔다. 함수 이름은 `test_req<NNN>_<요약>`이다. 레벨의 뜻(E2E, E2E-inj, Int, Unit)과 독립 오라클 원칙, 실행 환경(§0.1의 접두 게시, 자원 표식과 정리)은 PoC 요구사항명세 §0과 같다.
- 이 명세에서 쓰는 가짜:
  - **가짜 gh**: `gh`를 대신하는 실행 파일. 고정 응답, 403/429, 지연을 줄 수 있고 받은 호출을 기록한다.
  - **가짜 Sonar**: `tests/acceptance/fake_sonar.py`. 프로젝트별 응답, 404, 지연.
  - **가짜 ssh**: Sonar DB에 보내는 INSERT·DELETE·SELECT를 기록하고 행 상태를 흉내 낸다.
- **고정 사이트**: 테스트가 만든 로컬 사이트 디렉터리(run 픽스처 + 스냅숏 픽스처 + 설정)에 인덱스 재생성을 돌리고, 로컬 `http.server`로 띄워 헤드리스 chromium(Playwright)으로 본다.
- "화면에서"로 시작하는 수용기준은 브라우저에서 확인한다.

## 1. 요구사항 목록

### 1.1 설정 파일

#### REQ-076 — 설정 스키마 검증
- 유형: Functional / 우선순위: Must
- 수용기준: Given 스키마를 어긴 `dashboard.yaml`(필수 키 없음, 타입 오류, `schema`가 1이 아님), When 인덱스 재생성 또는 수집을 실행하면, Then 0이 아닌 종료 코드로 끝나고 표준 오류에 어긴 위치(키 경로)와 사유가 나오며 사이트 파일을 쓰지 않는다.
- 검증 레벨: Unit

#### REQ-077 — 과제 등록 검증
- 유형: Functional / 우선순위: Must
- 수용기준: Given 다음 가운데 하나가 있는 설정 — `name`에 `/` 또는 `..`, 대소문자만 다른 같은 `name` 둘, 같은 `repo` 둘, `suts/<sut>/sut.yaml`이 없는 `sut`, 한 `sut`를 가리키는 과제 둘, 완료된 run이 있는 미등록 SUT와 같은 `name` — Then 재생성이 0이 아닌 종료 코드와 사유로 끝난다.
- 검증 레벨: Unit

#### REQ-078 — 지표 카탈로그 대조
- 유형: Functional / 우선순위: Must
- 수용기준: Given 규칙·열·탭·요약·시계열·문구 치환에 카탈로그에 없는 이름이 있거나, `eq, ne, lt, le, gt, ge`가 아닌 연산자가 있는 설정, Then 재생성이 0이 아닌 종료 코드로 끝나고 그 이름이 사유에 나온다. Given 설계 §6.2의 예시 설정, Then 검증을 통과한다.
- 검증 레벨: Unit

#### REQ-079 — 접두 실행의 설정 격리
- 유형: Functional / 우선순위: Must
- 수용기준: Given `TD_SITE_PREFIX`가 있고 설정을 넘겨받지 않은 게시, Then 저장소 루트의 `dashboard.yaml`을 읽지 않고(홈에 그 과제가 하나도 없다) 가짜 gh의 호출 기록이 0건이다. Given `TD_DASHBOARD_CONFIG`로 넘겨받은 설정, Then 그 설정의 과제가 홈에 나온다.
- 검증 레벨: Int

#### REQ-080 — 설정으로 화면 구성 바꾸기
- 유형: Functional / 우선순위: Must
- 수용기준: Given `project.tabs`에서 탭 하나를 빼고 둘의 순서를 바꾼 설정, Then 화면에서 과제 페이지의 탭이 그 목록과 같은 순서로 나온다. Given `home.columns`에서 열 하나를 뺀 설정, Then 홈 표에 그 열이 없다. Given `project.trend.run`을 지표 둘로 줄인 설정, Then "추이" 탭의 차트가 둘이다.
- 검증 레벨: Int

### 1.2 상태 판정과 결론 문장

#### REQ-081 — 규칙별 판정
- 유형: Functional / 우선순위: Must
- 수용기준: Given 설계 §6.2의 기본 규칙과 고정 입력, Then 다음이 성립한다.
  - Sonar 게이트 `ERROR` → 위험, 사유 "Sonar 품질 게이트 실패".
  - 최근 CI 실패 → 위험. 최신 커밋의 검사 실패 → 위험이고 사유에 검사 이름이 있다.
  - CI 5회 이상이고 성공률 90% 미만 → 주의. Sonar 취약점 1건 이상 → 주의.
  - 위험 규칙과 주의 규칙이 함께 걸리면 수준은 위험이고 사유에 걸린 규칙이 모두 ` · `로 이어져 있다.
  - 걸린 규칙이 없으면 양호다.
- 검증 레벨: Unit

#### REQ-082 — 없는 값과 경계
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given CI 실행 0회이고 Sonar 값이 없는 과제, Then 측정 없음이다(양호가 아니다).
  - Given CI 4회 가운데 3회 실패이고 최근 실행은 성공, Then 성공률 규칙이 걸리지 않는다. Given 5회 가운데 1회 실패, Then 걸린다.
  - Given 규칙이 참조하는 값이 없는 과제, Then 그 규칙은 걸리지 않는다.
  - Given CI만 있고 Sonar가 없으며 걸린 규칙이 없는 과제, Then 양호이고 판정 결과에 부분 측정 표시가 있다.
- 검증 레벨: Unit

#### REQ-083 — 임계값 변경 반영
- 유형: Functional / 우선순위: Must
- 수용기준: Given 성공률 92%인 과제(기본 규칙에서 양호), When 임계값을 0.95로 바꾼 설정으로 다시 만들면, Then 그 과제가 주의이고 홈의 각주 문장에 새 임계값이 반영돼 있다.
- 검증 레벨: Int

#### REQ-084 — 결론 문장
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given 위험 또는 주의 과제, Then 과제 페이지의 결론 문장이 상태 이름과 판정 사유로 이루어져 있다.
  - Given 측정 없음 과제, Then "측정된 지표가 없습니다"다.
  - Given 양호이고 통과율 1, 귀속 커버리지 0.415인 과제, Then 설정의 첫 문장이 값 `41.5%`로 치환돼 나온다.
  - Given 양호이고 통과율이 1 미만이거나 없는 과제, Then "모두 통과"가 들어간 문장이 나오지 않는다.
- 검증 레벨: Unit

### 1.3 수집기

#### REQ-085 — GitHub CI 수집
- 유형: Functional / 우선순위: Must
- 수용기준: Given 가짜 gh가 결론값 `success` 3, `failure` 1, `timed_out` 1, `cancelled` 2, `skipped` 1인 실행 목록(가장 최근은 `cancelled`, 그다음이 `success`)을 주면, Then 스냅숏의 `ci.runs`는 5, `ci.successes`는 3, `ci.failures`는 2, `ci.lastFailed`는 거짓이다. Given 실행 0개, Then `ci.runs`가 `null`이다.
- 검증 레벨: Int

#### REQ-086 — 최신 커밋 검사 수집
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 이름의 검사가 실패(먼저 시작)와 성공(나중에 시작)으로 두 번 있고 진행 중인 검사가 하나 있는 응답, Then `ci.failedChecks`는 0이다. Given 나중 것이 실패, Then 1이고 `ci.failedCheckNames`에 그 이름이 있다. 결론값이 `cancelled`인 검사는 세지 않는다.
- 검증 레벨: Int

#### REQ-087 — SonarQube 수집
- 유형: Functional / 우선순위: Must
- 수용기준: Given 가짜 Sonar의 프로젝트 응답, Then 스냅숏의 `sonar.gate`, `sonar.coverage`, `sonar.vulnerabilities`, `sonar.bugs`, `sonar.codeSmells`가 응답과 같고 수 타입이다. Given 프로젝트 404, Then 그 과제의 `sonar`는 `null`이고 수집 상태는 정상이다. Sonar의 `code_smells`가 스냅숏의 `codeSmells`로 들어간다. Given `sonarKey`가 있는 과제, Then 가짜 Sonar가 받은 요청의 키가 그 값이다.
- 검증 레벨: Int

#### REQ-088 — 스냅숏 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given 수집 1회, Then `projects/<name>/snapshots/<UTC 날짜 YYYYMMDD>.json`과 `latest.json`이 있고 `project-snapshot.schema.json`을 지키며 `visibility`와 `collectedAt`(UTC ISO-8601)이 있다. Given 같은 날 두 번째 수집, Then 같은 파일을 덮어쓰고 스냅숏 수가 늘지 않는다.
- 검증 레벨: Int

#### REQ-089 — 비공개 저장소 제외
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 설정의 과제 3개 가운데 하나를 가짜 gh가 비공개로 답하면, Then 그 과제의 `projects/<name>/` 아래에 파일이 하나도 생기지 않고, 나머지 둘의 스냅숏은 있으며, 수집 상태가 `degraded`이고 사유에 그 과제 이름과 "비공개"가 있다. 재생성한 홈과 `projects.json`에 그 과제의 이름과 설명이 없다.
- 검증 레벨: Int

#### REQ-090 — 수집 부분 실패
- 유형: Functional / 우선순위: Must
- 수용기준: Given 한 과제의 Sonar 요청만 500을 주는 가짜 Sonar, Then 그 과제 스냅숏의 `sonar`는 `null`이고 실패 사유가 스냅숏에 있으며 `ci`는 채워져 있다. 다른 과제의 스냅숏은 온전하다. 수집 상태는 `degraded`다. 앞선 날짜 스냅숏의 값이 새 스냅숏에 복사되지 않는다.
- 검증 레벨: Int

#### REQ-091 — 수집 시간 예산
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 응답하지 않는 가짜 gh와 줄인 예산(테스트용 환경 변수), Then 수집이 예산 + 여유 10초 안에 끝나고, 읽지 못한 과제의 값은 `null`이며 상태는 `degraded`다. Given 429와 `Retry-After: 1`을 한 번 준 뒤 정상 응답, Then 값이 채워진다.
- 검증 레벨: Int

#### REQ-092 — 수집 토큰 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 가짜 ssh, Then 수집이 (a) 정상으로 끝난 뒤, (b) Sonar 읽기 도중 예외가 난 뒤, (c) 수집 도중 SIGTERM을 받은 뒤 모두 가짜 ssh의 행 상태에서 `td-collect-`로 시작하는 행이 0개다. 발급한 토큰 이름은 `td-collect-<UTC시각>-<난수>` 꼴이고 두 번의 수집에서 서로 다르다.
- 검증 레벨: Int

#### REQ-093 — 토큰 정리 실패의 표시
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 삭제 명령만 실패하는 가짜 ssh, Then 표준 오류에 토큰 이름과 "2시간 후 만료"가 들어간 경고가 나오고 수집 상태가 `degraded`다.
- 검증 레벨: Int

#### REQ-094 — 수집 토큰 비노출과 미발급
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 수집 1회, Then 수집이 쓴 모든 파일과 로그, 자식 프로세스의 인자에 토큰 평문이 없다(테스트용 관측 훅으로 토큰을 읽어 대조). Given Sonar를 읽을 과제가 하나도 없는 설정, Then 가짜 ssh의 호출 기록이 0건이다.
- 검증 레벨: Int

#### REQ-095 — 파이프라인 과제의 Sonar 출처
- 유형: Functional / 우선순위: Must
- 수용기준: Given `sut`가 있고 완료된 run이 있는 과제, Then 가짜 Sonar가 그 과제의 키로 받은 요청이 0건이고, `projects.json`의 그 과제 `sonar.*` 값이 최신 run의 `run.json` `kpis.sonar`와 같다. Given `sut`가 있지만 완료된 run이 없고 `sonarKey`를 적지 않은 과제, Then 수집기가 `sut.yaml`의 `sonar.projectKey`로 Sonar를 읽는다.
- 검증 레벨: Int

#### REQ-096 — 수집 텍스트 가리기
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 설명에 작업 디렉터리 경로와 ARN 모양 문자열을 넣은 가짜 gh 응답, Then 스냅숏과 홈에 그 문자열이 가려져 나오고 업로드 게이트를 통과한다.
- 검증 레벨: Int

#### REQ-097 — S11 토큰 동작 유지
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 단계에 묶이지 않게 고친 토큰 함수, Then PoC의 REQ-064, 065, 066 테스트가 고치지 않은 기대값으로 통과한다(S11의 토큰 이름은 `td-<runId>`이고 정리 실패 시 S11이 `failed`다).
- 검증 레벨: E2E-inj

### 1.4 게시

#### REQ-098 — 인덱스 전용 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 접두에 완료된 run이 하나 있는 상태와 과제 둘을 가진 설정, When `publish-index.sh`를 실행하면, Then 새 run 디렉터리가 생기지 않고, 원본에 두 과제의 `latest.json`·스냅숏·`index.html`·`series.json`과 갱신된 홈·`projects.json`이 `Cache-Control: no-cache`로 올라가 있다. 게시 뒤 미러에도 같은 파일이 남아 있다.
- 검증 레벨: E2E-inj

#### REQ-099 — 수집 문제와 게시 상태
- 유형: Functional / 우선순위: Must
- 수용기준: Given 수집이 `degraded`인 게시(S13과 인덱스 전용 각각), Then 홈과 과제 페이지는 있는 스냅숏으로 갱신돼 게시되고, 게시 상태가 `degraded`이며 게시 기록의 사유에 수집 사유가 들어 있다.
- 검증 레벨: E2E-inj

#### REQ-100 — 빠진 과제의 삭제
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 과제 A, B가 게시된 접두, When A를 설정에서 빼거나 가짜 gh가 A를 비공개로 답하게 한 뒤 게시하면, Then 원본과 미러에서 `projects/A/` 아래 객체가 0개이고 홈과 `projects.json`에 A가 없다. `projects/B/`, `suts/`, `static/`, `_test/`의 객체 수는 줄지 않는다.
- 검증 레벨: E2E-inj

#### REQ-101 — 무효화 경로 묶기
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 과제 20개를 다시 만든 게시, Then 무효화 요청의 경로 가운데 `projects/`로 시작하는 것은 `/<접두>projects/*` 하나다.
- 검증 레벨: Unit

### 1.5 인덱스 재생성과 데이터

#### REQ-102 — run 지표 추출
- 유형: Functional / 우선순위: Must
- 수용기준: Given 설계 §6.2 카탈로그의 run 지표에 대한 고정 run 픽스처, Then 각 지표가 기대값과 같다: `e2e.passRate`는 통과 수 합 ÷ 시나리오 수 합, `tia.selectedRatio`는 `selected ÷ indexedTests`, `run.durationSec`는 S00~S12의 가장 늦은 `finishedAt` − `startedAt`, Sonar 값은 수 타입. Given 해당 단계 JSON이 없거나 분모가 0인 run, Then 그 지표는 `null`이다.
- 검증 레벨: Unit

#### REQ-103 — 시계열 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given run 3개인 파이프라인 과제, Then `series.json`에 `kind: run`인 점 3개가 runId 순으로 있고 점마다 runId, 시각, 설정의 run 지표 값이 있다. Given 스냅숏 2일치인 과제, Then `kind: snapshot`인 점 2개가 날짜 순으로 있다. 한 파일에 두 종류가 섞이지 않는다.
- 검증 레벨: Unit

#### REQ-104 — 판정 결과 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given 재생성, Then `projects.json`에 과제마다 이름, 상태 수준, 사유 목록, 판정에 쓴 지표 값, 파이프라인 여부, 부분 측정 여부가 있고, 홈의 표가 보여 주는 상태와 사유가 이 파일과 같다.
- 검증 레벨: Int

#### REQ-105 — 기존 인덱스 파일 호환
- 유형: Functional / 우선순위: Must
- 수용기준: Given 재생성, Then `suts.json`과 `suts/<sut>/runs.json`에 PoC가 쓰던 필드(`runId`, `commit`, `trigger`, `startedAt`, `stages`, `kpis.passRate`, `kpis.line`, `kpis.sonarGate`, `kpis.hotspot1`, `runCount`, `latest`)가 같은 값으로 남아 있다.
- 검증 레벨: Unit

#### REQ-106 — 재생성 멱등 (새 파일 포함)
- 유형: Functional / 우선순위: Must
- 수용기준: Given run·스냅숏·설정이 있는 고정 사이트, When 재생성을 두 번 실행하면, Then `index.html`, `projects.json`, `projects/**`, `suts/**/index.html`, `static/v2/**`를 포함한 모든 출력의 바이트가 같다.
- 검증 레벨: Unit

#### REQ-107 — 암묵 과제
- 유형: Functional / 우선순위: Must
- 수용기준: Given 완료된 run이 있고 설정에 없는 SUT, Then 홈 표에 그 SUT 이름의 줄이 "파이프라인" 표시와 함께 나오고, `projects/<sut>/index.html`이 있으며, 가짜 gh가 그 이름으로 받은 호출이 0건이다.
- 검증 레벨: E2E-inj

#### REQ-108 — SUT 안내 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given 재생성, Then `suts/<sut>/index.html`에 그 SUT와 이어진 과제 페이지(설정의 과제 또는 암묵 과제)로 가는 링크와 `meta refresh`가 있고, 그 링크가 200으로 열린다.
- 검증 레벨: E2E

### 1.6 첫 화면

#### REQ-109 — 과제 표와 결론 문장
- 유형: Functional / 우선순위: Must
- 수용기준: Given 위험 2, 주의 1, 측정 없음 1, 양호 2인 고정 사이트, Then 화면에서 표에 6줄이 위험 → 주의 → 측정 없음 → 양호 순(같은 상태 안은 이름순)으로 나오고, 결론 문장에 "6", "2", "1"이 표의 개수와 같게 나온다. Given 위험·주의가 없는 사이트, Then "문제 있는 과제가 없습니다"다.
- 검증 레벨: E2E

#### REQ-110 — 거르기와 정렬
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 "위험" 버튼을 누르면 위험 행만 남고 버튼의 `aria-pressed`가 `true`다. 이름 칸에 글자를 넣으면 이름에 그 글자가 든 행만 남는다. 열 제목을 누르면 그 열 기준으로 순서가 바뀌고 `aria-sort`가 붙으며, 다시 누르면 반대 순서다. 값이 없는 행은 어느 방향에서도 뒤에 온다.
- 검증 레벨: E2E

#### REQ-111 — 행 펼침
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 과제 행을 누르면 그 행의 바로 다음 형제 요소로 상세 행이 생기고 눌린 행의 `aria-expanded`가 `true`다. 상세에 판정 사유와 "과제 페이지 열기" 링크가 있다. 같은 행을 다시 누르면 상세가 사라진다. 다른 행을 누르면 앞의 상세가 닫힌다. 행에 초점을 두고 Enter를 눌러도 같다.
- 검증 레벨: E2E

#### REQ-112 — 스크립트 없는 첫 화면
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 스크립트를 끈 브라우저, Then 과제 줄이 모두 보이고 상태·사유·수치가 읽히며, 과제 이름이 과제 페이지로 가는 링크다.
- 검증 레벨: E2E

#### REQ-113 — 없는 값의 표기
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given Sonar 값이 없는 과제와 CI가 없는 과제, Then 화면에서 해당 칸의 글자가 "측정 없음", "연결 없음" 또는 "—"이고 `0`, `0%`, `0.0%`가 아니다. Sonar 커버리지가 실제로 0인 과제는 `0.0%`로 나온다.
- 검증 레벨: E2E

#### REQ-114 — 표시와 각주
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 파이프라인을 돌린 과제에만 "파이프라인" 표시가, 한 출처만 읽힌 과제에만 "부분 측정" 표시가 있다. 각주에 설정의 규칙이 수준별 문장으로 나오고, `_test/index.html`과 `hosting.html`로 가는 링크가 있다.
- 검증 레벨: E2E

### 1.7 과제 페이지

#### REQ-115 — 탭 전환과 주소
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 탭을 누르면 그 탭의 구역만 보이고 `aria-selected`가 그 탭에만 `true`이며 주소의 `#` 부분이 탭 식별자가 된다. 그 주소로 새로 열면 같은 탭이 열려 있다. 탭에 초점을 두고 오른쪽 방향키를 누르면 다음 탭이 선택된다. 탭 요소에 `role="tab"`과 `aria-controls`가, 구역에 `role="tabpanel"`이 있다.
- 검증 레벨: E2E

#### REQ-116 — 스크립트 없는 과제 페이지
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 스크립트를 끈 브라우저, Then 모든 탭 구역이 설정의 순서대로 이어서 보이고 각 구역의 수치와 표가 읽힌다.
- 검증 레벨: E2E

#### REQ-117 — 탭마다 읽는 법
- 유형: Functional / 우선순위: Must
- 수용기준: Given 과제 페이지, Then 탭 구역마다 "이 탭 읽는 법" 블록이 정확히 하나 있다.
- 검증 레벨: E2E

#### REQ-118 — 탭 내용
- 유형: Functional / 우선순위: Must
- 수용기준: Given 고정 run을 가진 파이프라인 과제, Then 화면에서 다음 값이 픽스처와 같다: "한눈에"의 KPI 5칸과 상위 5개 위험 지점, "테스트"의 생성 묶음별 통과·실패 수, "커버리지"의 묶음별 귀속·집계 값, "위험 지점"의 상위 10개, "코드 품질"의 종류 × 심각도 이슈 수, "생성 실험"의 판정과 방식별 평균, "실행 이력"의 run 수. 각 탭에 해당 리포트로 가는 링크가 있고 200으로 열린다.
- 검증 레벨: E2E

#### REQ-119 — 파이프라인 없는 과제의 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given `sut`가 없는 과제, Then 과제 페이지의 탭이 한눈에, 추이, 코드 품질 셋뿐이고 "한눈에"에 CI 성공률·Sonar 게이트·Sonar 커버리지·취약점·버그가 스냅숏 값으로 나온다.
- 검증 레벨: E2E

#### REQ-120 — 시계열 점과 끊김
- 유형: Functional / 우선순위: Must
- 수용기준: Given run 5개 가운데 3번째 run에 통과율이 없는 과제, Then 화면에서 통과율 차트의 점이 4개이고 선이 두 조각이다. Given run 31개, Then 차트의 점은 최근 30개이고 차트 아래 표의 행은 31개다.
- 검증 레벨: E2E

#### REQ-121 — 시계열 점의 정보와 링크
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 run 점에 초점을 주면 runId와 값이 보이고, 다른 차트의 같은 run 점에 강조 표시가 붙는다. run 점의 링크는 그 run 페이지를 가리키고 200으로 열린다. 스냅숏 점에는 링크가 없고 초점을 주면 날짜와 값이 보인다.
- 검증 레벨: E2E

#### REQ-122 — 세로축 규칙
- 유형: Functional / 우선순위: Must
- 수용기준: Given 비율 지표, Then 세로축 눈금이 0%, 50%, 100%다. Given 값이 3, 18, 7인 개수 지표, Then 가장 위 눈금이 18이다. Given 모든 값이 같은 지표, Then 점이 차트 높이의 가운데에 있다. 같은 입력의 SVG가 두 번의 렌더에서 바이트로 같다.
- 검증 레벨: Unit

#### REQ-123 — 차트와 표의 값 일치
- 유형: Functional / 우선순위: Must
- 수용기준: Given "추이" 탭, Then 차트 아래 표의 각 칸이 `series.json`의 같은 점·같은 지표 값과 같고, 값이 없는 칸은 "—"다.
- 검증 레벨: E2E

### 1.8 run 페이지와 리포트 간 링크

#### REQ-124 — run 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given 새로 만든 run, Then 화면에서 run 페이지에 단계 14개의 띠가 있고 단계를 누르면 그 단계의 이름·상태·걸린 시간이 나온다. 성공한 리포트마다 카드가 있고 링크가 200으로 열린다. S13 게시 결과가 기존처럼 표시된다.
- 검증 레벨: E2E

#### REQ-125 — 공통 띠의 존재와 링크
- 유형: Functional / 우선순위: Must
- 수용기준: Given 접두(`_test/<id>/`) 아래에 새로 게시한 run, Then run 페이지, 커버리지, Sonar, 방식 비교, 온톨로지, `hotspots.html`, `api_report.html`, `tia.html`, 각 `cucumber/<genId>/index.html`에 공통 띠가 있고, 띠의 홈·SUT·run·다른 리포트 링크가 모두 그 접두 안에서 200으로 열린다. 띠의 SUT 링크는 `suts/<sut>/index.html`이다.
- 검증 레벨: E2E-inj

#### REQ-126 — 띠를 끼운 리포트의 기능 유지
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 띠를 끼운 `hotspots.html`, Then 화면에서 지도 SVG에 원이 그려지고 원을 누르면 옆 패널이 바뀐다. Given 띠를 끼운 `tia.html`, Then 페이지 전환 버튼을 누르면 내용이 바뀐다. 두 페이지 모두 콘솔 오류가 없고, 띠 요소에 `<script>`가 없다.
- 검증 레벨: E2E

#### REQ-127 — 띠를 넣을 수 없는 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given `<body>`가 없는 HTML을 리포트 진입 파일로 주입한 run, Then 그 파일은 원본 그대로 게시되고, run 페이지의 그 리포트 카드에 "공통 띠 없음"과 사유가 나오며, S13 상태가 `degraded`다. Given `<BODY class="x">`처럼 대문자와 속성이 있는 HTML, Then 띠가 그 태그 바로 뒤에 들어간다.
- 검증 레벨: Int

#### REQ-128 — 직접 만드는 리포트의 새 틀
- 유형: Functional / 우선순위: Must
- 수용기준: Given 새로 만든 run의 커버리지, Sonar, 방식 비교, 온톨로지 페이지와 `hosting.html`, Then 각 페이지가 `static/v2/app.css`를 불러오고, PoC 매트릭스에서 이 화면들을 검사하는 기존 테스트(REQ-017, 030~034, 037~044 가운데 화면을 보는 것)가 통과한다.
- 검증 레벨: E2E

### 1.9 도구 고정과 새 리포트

#### REQ-129 — hotspot 커밋 고정 빌드
- 유형: Functional / 우선순위: Must
- 수용기준: Given `tools.pin.yaml`의 hotspot이 40자 커밋, When S00을 실행하면, Then 그 커밋에서 빌드한 `hotspot.jar`가 도구 디렉터리에 있고 `tools.lock`의 hotspot에 그 커밋과 jar의 sha256이 있으며 그 sha256이 파일과 같다. Given 40자가 아닌 커밋, Then S00이 `failed`다.
- 검증 레벨: Int

#### REQ-130 — 새 hotspot 리포트 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then 게시된 `hotspots.html`에 `id="hotspot-map-data"`인 JSON 블록이 있고 그 `schemaVersion`이 1이며, 화면에서 지도 SVG에 원이 하나 이상 있다. `stages/S09.json`의 `top10`이 PoC와 같은 구조로 채워져 있다.
- 검증 레벨: E2E

#### REQ-131 — 새 TIA 리포트 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then 게시된 `tia.html`에 `tab-guide` 블록이 4개 있고, 데이터 블록의 `impact`가 `null`이 아니며 그 `changedFiles` 수가 `S10/impact.json`과 같다.
- 검증 레벨: E2E

### 1.10 공통

#### REQ-132 — 외부 요청 없음
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 고정 사이트의 홈, 과제 페이지(탭마다), run 페이지, 직접 만드는 리포트를 브라우저로 열 때, Then 사이트 밖 호스트로 나가는 네트워크 요청이 0건이다. 생성된 CSS·JS에 `http://`, `https://`, `@import`가 없다.
- 검증 레벨: E2E

#### REQ-133 — 좁은 화면
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 360px 폭, Then 홈, 과제 페이지(탭마다), run 페이지에서 `scrollWidth <= innerWidth`다.
- 검증 레벨: E2E

#### REQ-134 — 어두운 테마
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given `prefers-color-scheme: dark`, Then 홈과 과제 페이지의 body 배경색이 밝은 테마와 다르고, 상태 표시의 글자와 배경의 명암비가 4.5 이상이다.
- 검증 레벨: E2E

#### REQ-135 — 색에 기대지 않는 상태 표시
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 홈, Then 상태 표시마다 상태 이름 글자가 있고, 위험·주의·측정 없음의 표시 모양(클래스)이 서로 다르다.
- 검증 레벨: E2E

#### REQ-136 — 옛 자산 불변
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 재생성, Then `static/site.css`와 `static/site.js`의 sha256이 이 작업 전 커밋의 것과 같다. Given PoC 디자인으로 만든 run 페이지 픽스처, Then 재생성 뒤 화면에서 그 페이지의 표 머리 배경색과 본문 글꼴 크기가 재생성 전과 같다.
- 검증 레벨: E2E

#### REQ-137 — 새 자산 경로
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 새로 만든 run 페이지와 인덱스 페이지, Then 스타일과 스크립트를 `static/v2/` 아래에서만 불러온다(`static/site.css`를 불러오지 않는다).
- 검증 레벨: Unit

#### REQ-138 — 움직임 줄이기
- 유형: Non-functional / 우선순위: Could
- 수용기준: Given `prefers-reduced-motion: reduce`, Then 펼침 화살표와 탭 전환에 `transition`이 적용되지 않는다.
- 검증 레벨: E2E

#### REQ-139 — 운영 사이트 확인
- 유형: Functional / 우선순위: Must
- 수용기준: Given 운영 접두에 새 run 하나와 인덱스 전용 게시를 한 뒤, Then `https://reports.<domain>/`의 홈에 설정의 공개 과제 수만큼 줄이 있고, 과제 페이지 → 최신 run → `hotspots.html`과 `tia.html` → 띠의 SUT 링크 → 과제 페이지가 모두 200이다. 이 작업 전에 게시된 run 하나의 페이지가 200이고 `static/site.css`를 불러온다. `_design/` 아래 주소는 200이 아니다.
- 검증 레벨: E2E

## 2. 추적 매트릭스

| REQ-ID | 요구사항 | 수용 테스트 | Level | Status |
|---|---|---|---|---|
| REQ-076 | 설정 스키마 검증 | test_dashboard_config.py::test_req076_schema_violation_fails | Unit | 🔴 planned |
| REQ-077 | 과제 등록 검증 | test_dashboard_config.py::test_req077_project_registration_rules | Unit | 🔴 planned |
| REQ-078 | 지표 카탈로그 대조 | test_dashboard_config.py::test_req078_unknown_metric_or_operator | Unit | 🔴 planned |
| REQ-079 | 접두 실행의 설정 격리 | test_dashboard_publish.py::test_req079_prefix_run_uses_only_given_config | Int | 🔴 planned |
| REQ-080 | 설정으로 화면 구성 | test_dashboard_project.py::test_req080_tabs_columns_trend_follow_config | Int | 🔴 planned |
| REQ-081 | 규칙별 판정 | test_dashboard_status.py::test_req081_rule_levels_and_reasons | Unit | 🔴 planned |
| REQ-082 | 없는 값과 경계 | test_dashboard_status.py::test_req082_missing_and_boundaries | Unit | 🔴 planned |
| REQ-083 | 임계값 변경 반영 | test_dashboard_status.py::test_req083_threshold_change_changes_verdict | Int | 🔴 planned |
| REQ-084 | 결론 문장 | test_dashboard_status.py::test_req084_headline_selection | Unit | 🔴 planned |
| REQ-085 | GitHub CI 수집 | test_dashboard_collect.py::test_req085_ci_conclusion_classes | Int | 🔴 planned |
| REQ-086 | 최신 커밋 검사 | test_dashboard_collect.py::test_req086_latest_check_per_name | Int | 🔴 planned |
| REQ-087 | SonarQube 수집 | test_dashboard_collect.py::test_req087_sonar_values_and_404 | Int | 🔴 planned |
| REQ-088 | 스냅숏 파일 | test_dashboard_collect.py::test_req088_snapshot_files_and_schema | Int | 🔴 planned |
| REQ-089 | 비공개 제외 | test_dashboard_collect.py::test_req089_private_repo_excluded | Int | 🔴 planned |
| REQ-090 | 수집 부분 실패 | test_dashboard_collect.py::test_req090_partial_failure_null_not_carried | Int | 🔴 planned |
| REQ-091 | 수집 시간 예산 | test_dashboard_collect.py::test_req091_budget_and_retry_after | Int | 🔴 planned |
| REQ-092 | 수집 토큰 정리 | test_dashboard_collect.py::test_req092_token_removed_on_all_exits | Int | 🔴 planned |
| REQ-093 | 토큰 정리 실패 표시 | test_dashboard_collect.py::test_req093_cleanup_failure_warns_degraded | Int | 🔴 planned |
| REQ-094 | 토큰 비노출·미발급 | test_dashboard_collect.py::test_req094_token_not_leaked_and_not_issued_when_unneeded | Int | 🔴 planned |
| REQ-095 | 파이프라인 과제의 Sonar 출처 | test_dashboard_collect.py::test_req095_pipeline_project_sonar_from_run | Int | 🔴 planned |
| REQ-096 | 수집 텍스트 가리기 | test_dashboard_collect.py::test_req096_external_text_redacted | Int | 🔴 planned |
| REQ-097 | S11 토큰 동작 유지 | test_sonar.py::test_req064_*, test_req065_*, test_req066_* (기존, 기대값 불변) | E2E-inj | 🔴 planned |
| REQ-098 | 인덱스 전용 게시 | test_dashboard_publish.py::test_req098_index_only_publish | E2E-inj | 🔴 planned |
| REQ-099 | 수집 문제와 게시 상태 | test_dashboard_publish.py::test_req099_collect_degraded_still_publishes | E2E-inj | 🔴 planned |
| REQ-100 | 빠진 과제의 삭제 | test_dashboard_publish.py::test_req100_removed_or_private_project_deleted | E2E-inj | 🔴 planned |
| REQ-101 | 무효화 경로 묶기 | test_dashboard_publish.py::test_req101_projects_invalidation_wildcard | Unit | 🔴 planned |
| REQ-102 | run 지표 추출 | test_dashboard_index.py::test_req102_run_metrics | Unit | 🔴 planned |
| REQ-103 | 시계열 파일 | test_dashboard_index.py::test_req103_series_points | Unit | 🔴 planned |
| REQ-104 | 판정 결과 파일 | test_dashboard_index.py::test_req104_projects_json_matches_home | Int | 🔴 planned |
| REQ-105 | 기존 인덱스 파일 호환 | test_dashboard_index.py::test_req105_legacy_fields_kept | Unit | 🔴 planned |
| REQ-106 | 재생성 멱등 | test_dashboard_index.py::test_req106_idempotent_all_outputs | Unit | 🔴 planned |
| REQ-107 | 암묵 과제 | test_dashboard_publish.py::test_req107_unregistered_sut_listed | E2E-inj | 🔴 planned |
| REQ-108 | SUT 안내 페이지 | test_dashboard_project.py::test_req108_sut_page_leads_to_project | E2E | 🔴 planned |
| REQ-109 | 과제 표와 결론 문장 | test_dashboard_home.py::test_req109_rows_order_headline | E2E | 🔴 planned |
| REQ-110 | 거르기와 정렬 | test_dashboard_home.py::test_req110_filter_search_sort | E2E | 🔴 planned |
| REQ-111 | 행 펼침 | test_dashboard_home.py::test_req111_inline_expand | E2E | 🔴 planned |
| REQ-112 | 스크립트 없는 첫 화면 | test_dashboard_home.py::test_req112_no_script | E2E | 🔴 planned |
| REQ-113 | 없는 값의 표기 | test_dashboard_home.py::test_req113_missing_not_zero | E2E | 🔴 planned |
| REQ-114 | 표시와 각주 | test_dashboard_home.py::test_req114_badges_footnote_links | E2E | 🔴 planned |
| REQ-115 | 탭 전환과 주소 | test_dashboard_project.py::test_req115_tabs_hash_keyboard | E2E | 🔴 planned |
| REQ-116 | 스크립트 없는 과제 페이지 | test_dashboard_project.py::test_req116_no_script_all_panels | E2E | 🔴 planned |
| REQ-117 | 탭마다 읽는 법 | test_dashboard_project.py::test_req117_tab_guides | E2E | 🔴 planned |
| REQ-118 | 탭 내용 | test_dashboard_project.py::test_req118_tab_contents_match_fixture | E2E | 🔴 planned |
| REQ-119 | 파이프라인 없는 과제 | test_dashboard_project.py::test_req119_snapshot_only_project | E2E | 🔴 planned |
| REQ-120 | 시계열 점과 끊김 | test_dashboard_project.py::test_req120_trend_points_gaps_cap | E2E | 🔴 planned |
| REQ-121 | 시계열 점 정보와 링크 | test_dashboard_project.py::test_req121_trend_tooltip_links | E2E | 🔴 planned |
| REQ-122 | 세로축 규칙 | test_dashboard_index.py::test_req122_chart_axis_rules | Unit | 🔴 planned |
| REQ-123 | 차트와 표의 값 일치 | test_dashboard_project.py::test_req123_trend_table_equals_series | E2E | 🔴 planned |
| REQ-124 | run 페이지 | test_dashboard_nav.py::test_req124_run_page | E2E | 🔴 planned |
| REQ-125 | 공통 띠 | test_dashboard_nav.py::test_req125_nav_on_all_reports_under_prefix | E2E-inj | 🔴 planned |
| REQ-126 | 띠 뒤 기능 유지 | test_dashboard_nav.py::test_req126_external_reports_still_work | E2E | 🔴 planned |
| REQ-127 | 띠를 넣을 수 없는 파일 | test_dashboard_nav.py::test_req127_no_body_degraded | Int | 🔴 planned |
| REQ-128 | 직접 만드는 리포트의 새 틀 | test_dashboard_nav.py::test_req128_own_reports_new_frame | E2E | 🔴 planned |
| REQ-129 | hotspot 커밋 고정 빌드 | test_prepare.py::test_req129_hotspot_commit_build | Int | 🔴 planned |
| REQ-130 | 새 hotspot 리포트 | test_baseline.py::test_req130_hotspot_map_published | E2E | 🔴 planned |
| REQ-131 | 새 TIA 리포트 | test_baseline.py::test_req131_tia_report_published | E2E | 🔴 planned |
| REQ-132 | 외부 요청 없음 | test_dashboard_common.py::test_req132_no_external_requests | E2E | 🔴 planned |
| REQ-133 | 좁은 화면 | test_dashboard_common.py::test_req133_responsive_360 | E2E | 🔴 planned |
| REQ-134 | 어두운 테마 | test_dashboard_common.py::test_req134_dark_theme | E2E | 🔴 planned |
| REQ-135 | 색에 기대지 않는 상태 표시 | test_dashboard_common.py::test_req135_status_not_color_only | E2E | 🔴 planned |
| REQ-136 | 옛 자산 불변 | test_dashboard_common.py::test_req136_legacy_assets_unchanged | E2E | 🔴 planned |
| REQ-137 | 새 자산 경로 | test_dashboard_common.py::test_req137_v2_asset_paths | Unit | 🔴 planned |
| REQ-138 | 움직임 줄이기 | test_dashboard_common.py::test_req138_reduced_motion | E2E | 🔴 planned |
| REQ-139 | 운영 사이트 확인 | test_baseline.py::test_req139_production_site | E2E | 🔴 planned |

Coverage: 0/64 green (0%) — target 100% (대상: Must 59 + Should 4 + Could 1. 연기 없음)

## 3. PoC 요구사항의 개정

이 작업은 PoC 요구사항명세의 아래 항목을 바꾼다. 구현 PR에서 PoC 명세의 해당 항목과 테스트를 함께 고치고, PoC 매트릭스의 상태를 다시 green으로 확인한다.

| PoC REQ | 바뀌는 수용기준 | 테스트 처리 |
|---|---|---|
| REQ-035 hotspot 리포트 | 그대로 두고, 새 지도 블록은 REQ-130이 본다. run 페이지의 링크는 리포트 카드로 바뀐다 | 링크를 찾는 선택자만 고친다 |
| REQ-036 TIA 리포트 | 그대로 두고, 새 페이지 구성은 REQ-131이 본다. "리포트에 내장된 커밋 값" 확인은 새 템플릿의 데이터 블록에서 읽는다 | 값을 읽는 위치를 고친다 |
| REQ-045 인덱스 멱등 | 그대로. 새 출력까지 넓힌 것이 REQ-106이다 | 고치지 않는다 |
| REQ-049 홈과 SUT 페이지 | "홈에 SUT별 최신 run의 KPI"는 "홈의 과제 표에서 그 SUT와 이어진 과제를 펼치면 테스트 통과율, 귀속 라인 커버리지, Sonar 게이트, hotspot 1위가 나온다"로 바꾼다. "SUT 페이지에 run 이력 표와 KPI 추이 차트"는 "SUT 페이지가 안내하는 과제 페이지의 실행 이력 탭과 추이 탭"으로 바꾼다 | 세 테스트의 화면 탐색을 고친다 |
| REQ-050 멀티 SUT | "홈에 SUT 2개가 나온다"는 "홈의 과제 표에 두 SUT의 암묵 과제가 나온다"로 바꾼다(REQ-107과 같은 경로) | 선택자를 고친다 |
| REQ-058 tools.lock | hotspot 항목이 버전이 아니라 커밋과 jar의 sha256이다 | 기대값을 고친다. REQ-129가 빌드를 본다 |
| REQ-064~066 Sonar 토큰 | 수용기준은 그대로다. 구현이 공용 함수 위로 옮겨진다 | 고치지 않는다(REQ-097) |
| REQ-017, 034 반응형·다크 | 그대로. 새 틀에서 다시 통과해야 한다 | 고치지 않는다(REQ-128) |

PoC 설계 §13.2의 "홈 하단의 테스트 실행 기록 링크"는 REQ-114가 본다.

## 4. 자기검토

- 설계의 목표 8개가 모두 REQ에 이어진다: 목표 1 → 109~114, 목표 2 → 085~096·098·107, 목표 3 → 115~123, 목표 4 → 076~084, 목표 5 → 124~127, 목표 6 → 129~131, 목표 7 → 128·133~137, 목표 8 → 098·132.
- 반목표가 모두 REQ에 이어진다: 값 지어내기 → 113·090, 거짓 결론 → 084, 외부 요청 → 132, 스크립트 없음 → 112·116, 비공개 노출 → 089·100, 판정 사유 → 081·104·111.
- 수용 테스트를 두지 않는 설계 항목: 시안 삭제 절차 자체(결과는 REQ-139가 본다), README 갱신(문서 게이트에서 확인), 차트의 최근 30개 상한 값을 설정으로 바꾸는 것(설계에 없다).
- 각 REQ는 하나의 행위이고 측정 가능한 Given-When-Then이 있다. 수집과 판정은 가짜의 호출 기록과 고정 입력으로 판정하고, 구현의 자기 보고만으로 판정하지 않는다.
- Must 59, Should 4(REQ-101, 133, 134, 135), Could 1(REQ-138). 총 64개.
