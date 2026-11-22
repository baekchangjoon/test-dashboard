# test-dashboard 화면 재설계 요구사항명세

> 출처(design spec): docs/superpowers/specs/2026-11-22-dashboard-ui-design.md (v2.2, 승인 2026-11-22)
> 완료 정의(DoD): 커버리지 대상 요구사항마다 매트릭스에 지정된 검증 테스트가 하나 이상 있고, 그 테스트가 모두 통과한다(대상 매트릭스 전부 green). 아울러 §3에 적은 대로 고친 PoC 테스트와, 고치지 않은 PoC 매트릭스가 계속 통과한다.
> 버전: v2 (Claude Fable, GPT 5.6 Sol 리뷰 반영)

## 0. 규약

- REQ-ID는 PoC 요구사항명세(REQ-001~075)에 이어 REQ-076부터 쓴다. 번호를 다시 쓰지 않는다.
- 검증 테스트는 pytest이고 `tests/acceptance/`에 둔다. 함수 이름은 `test_req<NNN>_<요약>`이다.
- 레벨은 PoC 요구사항명세 §0의 뜻 그대로다.
  - **E2E**: 기준 run의 산출물이나 배포 URL을 블랙박스로 검사한다.
  - **E2E-inj**: 접두(`_test/<sessionId>/`) 아래에 실제로 게시한 실행을 검사한다.
  - **Int**: 명령이나 모듈을 가짜 외부 서비스와 함께 실제로 실행한다. 고정 사이트를 브라우저로 보는 테스트가 여기에 든다.
  - **Unit**: 순수 함수를 검사한다.
- 독립 오라클 원칙과 자원 표식·정리 규칙은 PoC §0, §0.1과 같다.
- 이 명세에서 쓰는 가짜:
  - **가짜 gh**: `gh`를 대신하는 실행 파일. 고정 응답, 403/429와 `Retry-After`, 404, 지연을 줄 수 있고 받은 인자를 기록한다.
  - **가짜 Sonar**: `tests/acceptance/fake_sonar.py`. 프로젝트 키별 응답, 404, 500, 지연. 받은 요청을 기록한다. 주소는 기존 `TD_SONAR_URL_OVERRIDE`(`TD_SITE_PREFIX`가 있을 때만 유효)로 넣는다.
  - **가짜 ssh**: Sonar DB로 가는 `docker exec … psql` 명령만 가로채 INSERT·DELETE·SELECT를 기록하고 행 상태를 흉내 낸다. 그 밖의 명령은 실제 `ssh`로 넘긴다.
- **고정 사이트**: 테스트가 만든 로컬 사이트 디렉터리(run 픽스처 + 스냅숏 픽스처 + 설정)에 인덱스 재생성을 돌리고, 로컬 `http.server`로 띄워 헤드리스 chromium(Playwright)으로 본다. run 페이지와 리포트는 실제 도구(고정한 커밋)가 만든 표본 HTML(`tests/fixtures/reports/`)을 `pages.render_run`으로 렌더한 것이다.
- "화면에서"로 시작하는 수용기준은 브라우저에서 확인한다.
- 시각이 필요한 테스트는 기존 훅 `TD_NOW`(`TD_SITE_PREFIX`가 있을 때만 유효)로 고정한다.
- **기준 run 세션**: `tests/acceptance/run_baseline.py`가 기준 run과 두 번째 run 뒤에 `pipeline/publish-index.sh`를 한 번 돌리고 그 결과를 세션 파일에 남긴다. 시안(`_design/`) 삭제는 그 스크립트를 돌리기 전에 한다(계획 Task 14). E2E 테스트는 이 세션 파일을 읽는다.

## 1. 요구사항 목록

### 1.1 설정 파일

#### REQ-076 — 설정 스키마 검증
- 유형: Functional / 우선순위: Must
- 수용기준: Given 스키마를 어긴 `dashboard.yaml`(필수 키 없음, 타입 오류, `schema`가 1이 아님), When 인덱스 재생성을 실행하면, Then 0이 아닌 종료 코드로 끝나고 표준 오류에 어긴 위치(키 경로)와 사유가 나오며 사이트 파일을 쓰지 않는다.
- 검증 레벨: Unit

#### REQ-077 — 과제 등록 검증
- 유형: Functional / 우선순위: Must
- 수용기준: Given 다음 가운데 하나가 있는 설정 — `name`이 `a/b`, `..`, `bad name`, `-p`, `.p`, `과제`, 빈 문자열 / 대소문자만 다른 같은 `name` 둘 / 같은 `repo` 둘 / `suts/<sut>/sut.yaml`이 없는 `sut` / 한 `sut`를 가리키는 과제 둘 / 완료된 run이 있는 미등록 SUT와 같은 `name` — Then 검증이 실패하고 사유에 그 키 경로가 있다.
- 검증 레벨: Unit

#### REQ-078 — 지표 카탈로그 대조
- 유형: Functional / 우선순위: Must
- 수용기준: Given 규칙·열·탭·요약·시계열·문구 치환에 카탈로그에 없는 이름이 있는 설정, 여섯 연산자(`eq, ne, lt, le, gt, ge`)가 아닌 연산자가 있는 설정, 집계 지표를 규칙이나 열에 쓴 설정, run에서만 나오는 지표를 `project.trend.snapshot`에 쓴 설정, Then 검증이 실패하고 그 이름이 사유에 나온다. Given 저장소 루트의 `dashboard.yaml`, Then 검증을 통과한다.
- 검증 레벨: Unit

#### REQ-079 — 접두 실행의 설정 격리
- 유형: Functional / 우선순위: Must
- 수용기준: Given `TD_SITE_PREFIX`가 있고 설정을 넘겨받지 않은 게시, Then 저장소 루트의 `dashboard.yaml`을 읽지 않고(홈에 그 과제가 하나도 없다) 가짜 gh의 호출 기록이 0건이다. Given `TD_DASHBOARD_CONFIG`로 넘겨받은 설정, Then 그 설정의 과제가 홈에 나온다.
- 검증 레벨: E2E-inj

#### REQ-080 — 설정으로 화면 구성 바꾸기
- 유형: Functional / 우선순위: Must
- 수용기준: 고정 사이트에서 다음 설정 변경이 각각 화면에 반영된다.
  - `project.tabs`에서 탭 하나를 빼고 둘의 순서를 바꾸면 과제 페이지의 탭이 그 목록과 같다.
  - `home.columns`에서 열 하나를 빼면 홈 표에 그 열이 없다.
  - `home.summary`를 둘로 줄이고 순서를 바꾸면 요약 칸이 그 둘, 그 순서다.
  - `project.trend.run`을 지표 둘로 줄이면 파이프라인 과제의 "추이" 차트가 둘이다. `project.trend.snapshot`을 하나로 줄이면 그 밖의 과제의 차트가 하나다.
  - `status.labels.crit`를 "심각"으로 바꾸면 위험 과제의 상태 글자가 "심각"이다. `status.order`를 `[warn, crit, none, good]`으로 바꾸면 주의 행이 위험 행보다 위에 온다.
  - `status.none.allMissing`을 `[sonar.gate]`로 바꾸면 CI만 있는 과제가 측정 없음이 된다.
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
  - Given `ci.runs`, `sonar.gate`, `tests.passRate`가 모두 없는 과제, Then 측정 없음이다.
  - Given `ci.runs`와 `sonar.gate`가 없고 `tests.passRate`가 1.0인 과제(저장소 정보 없이 파이프라인만 돌린 과제), Then 측정 없음이 아니고 양호다.
  - Given CI 4회 가운데 3회 실패이고 최근 실행은 성공, Then 성공률 규칙이 걸리지 않는다. Given 5회 가운데 1회 실패, Then 걸린다.
  - Given CI 10회 가운데 1회 실패(정확히 90%), Then 걸리지 않는다. Given 10회 가운데 2회 실패, Then 걸린다.
  - Given 취약점 0, Then 취약점 규칙이 걸리지 않는다. Given 1, Then 걸린다.
  - Given 규칙이 참조하는 값이 없는 과제, Then 그 규칙은 걸리지 않는다.
  - Given `repo`가 있고 CI만 있으며 걸린 규칙이 없는 과제, Then 양호이고 부분 측정이다. Given `repo`가 없는 과제, Then 부분 측정이 아니다.
- 검증 레벨: Unit

#### REQ-083 — 임계값 변경 반영
- 유형: Functional / 우선순위: Must
- 수용기준: Given 성공률 92%인 과제(기본 규칙에서 양호), When 임계값을 0.95로 바꾼 설정으로 다시 만들면, Then 그 과제가 주의이고 홈 각주의 주의 줄에 `95.0%`가 있고 `90.0%`가 없다.
- 검증 레벨: Int

#### REQ-084 — 결론 문장
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given 위험 또는 주의 과제, Then 결론 문장이 `<상태 이름>: <사유 · 사유>`다.
  - Given 측정 없음 과제, Then "측정된 지표가 없습니다"다.
  - Given 양호이고 통과율 1, 귀속 커버리지 0.415인 과제, Then 설정의 첫 문장이 값 `41.5%`로 치환돼 나온다.
  - Given 양호이고 통과율이 1 미만이거나 없는 과제, Then "모두 통과"가 들어간 문장이 나오지 않는다.
  - 화면에서 과제 페이지 위쪽에 이 문장이 보인다.
- 검증 레벨: Int

### 1.3 수집기

#### REQ-085 — GitHub CI 수집
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given 가짜 gh가 최신순으로 `success, success, failure, cancelled, timed_out, success, startup_failure, skipped, neutral, action_required, stale`인 실행 목록을 주면, Then 스냅숏의 `ci.runs`는 6, `ci.successes`는 3, `ci.failures`는 3, `ci.lastFailed`는 거짓, `ci.history`(오래된 것부터, 집계 대상만)는 `[0, 1, 0, 0, 1, 1]`이다.
  - Given 실행 0개, 또는 `cancelled`와 `skipped`뿐인 목록, Then `ci.runs`, `ci.successes`, `ci.failures`, `ci.successRate`, `ci.lastFailed`가 모두 `null`이고 `ci.history`는 빈 배열이다.
  - 가짜 gh가 받은 실행 목록 요청에 기본 브랜치 이름, `status=completed`, `per_page=30`이 있다.
- 검증 레벨: Int

#### REQ-086 — 최신 커밋 검사 수집
- 유형: Functional / 우선순위: Must
- 수용기준: Given 같은 이름의 검사가 실패(먼저 시작)와 성공(나중에 시작)으로 두 번 있고 진행 중인 검사와 `cancelled`인 검사가 하나씩 있는 응답, Then `ci.failedChecks`는 0이다. Given 나중 것이 실패, Then 1이고 `ci.failedCheckNames`에 그 이름이 있다. 요청 경로는 `repos/<repo>/commits/<기본 브랜치>/check-runs`다.
- 검증 레벨: Int

#### REQ-087 — SonarQube 수집
- 유형: Functional / 우선순위: Must
- 수용기준: Given 가짜 Sonar의 프로젝트 응답(측정값은 숫자 문자열), Then 스냅숏의 `sonar.gate`는 응답의 상태 문자열(`OK`, `ERROR` 등)이고, `sonar.coverage`는 실수, `sonar.vulnerabilities`·`sonar.bugs`·`sonar.codeSmells`는 정수다(Sonar의 `code_smells`가 `codeSmells`로 들어간다). Given 프로젝트 404, Then 그 과제의 `sonar`는 `null`이고 출처 상태가 "없음"이며 수집 상태는 정상이다. Given `sonarKey`가 있는 과제, Then 가짜 Sonar가 받은 요청의 키가 그 값이다.
- 검증 레벨: Int

#### REQ-088 — 스냅숏 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given `TD_NOW`로 고정한 수집 1회, Then `projects/<name>/snapshots/<그 시각의 UTC 날짜 YYYYMMDD>.json`과 `latest.json`이 있고 `project-snapshot.schema.json`을 지키며 `visibility`와 `collectedAt`(UTC ISO-8601)이 있다. Given 같은 UTC 날짜의 다른 시각에 두 번째 수집, Then 같은 파일을 덮어쓰고 스냅숏 수가 늘지 않는다. Given 다음 날짜의 수집, Then 파일이 하나 는다.
- 검증 레벨: Int

#### REQ-089 — 비공개 저장소 제외
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 설정의 과제 4개 가운데 하나를 가짜 gh가 `private`으로, 하나를 404로 답하면, Then 그 둘의 `projects/<name>/` 아래에 파일이 하나도 생기지 않고, 나머지 둘의 스냅숏은 있으며, 수집 상태가 `degraded`다. 수집 결과의 사유는 "비공개 과제 2개 제외"이고 두 과제의 이름은 사유에 없으며 표준 오류에만 있다. 재생성한 사이트의 모든 파일에 그 두 과제의 이름·`repo`·설명 문자열이 0건이다.
- 검증 레벨: Int

#### REQ-090 — 수집 부분 실패
- 유형: Functional / 우선순위: Must
- 수용기준: Given 한 과제의 Sonar 요청만 500을 주는 가짜 Sonar, Then 그 과제 스냅숏의 `sonar`는 `null`이고 출처 상태가 "실패"이며 사유가 스냅숏에 있고 `ci`는 채워져 있다. 다른 과제의 스냅숏은 온전하다. 수집 상태는 `degraded`다. 앞선 날짜 스냅숏의 Sonar 값이 새 스냅숏에 복사되지 않는다. 화면에서 그 과제의 Sonar 칸이 "측정 없음"이고 칸의 설명에 사유가 있다.
- 검증 레벨: Int

#### REQ-091 — 수집 시간 예산과 재시도
- 유형: Non-functional / 우선순위: Must
- 수용기준:
  - 기본값이 요청당 읽기 30초(전체 예산 안에서, 따로 두는 연결 제한 없음), 재시도 2회(간격 2초, 4초), 전체 예산 300초다(모듈 상수).
  - Given 응답하지 않는 가짜 gh와 예산 3초(`TD_COLLECT_BUDGET_SEC`), Then 수집이 13초 안에 끝나고, 읽지 못한 과제의 값은 `null`이며 상태는 `degraded`이고, 끝난 뒤 가짜 gh 프로세스가 남아 있지 않다.
  - Given 429와 `Retry-After: 1`을 한 번 준 뒤 정상 응답, Then 값이 채워지고 두 요청의 간격이 1초 이상이다. 403도 같다.
  - Given `Retry-After`가 남은 예산보다 길면, Then 기다리지 않고 그 과제를 없음으로 둔다.
  - Given 계속 실패하는 요청, Then 같은 요청은 3번까지만 간다.
- 검증 레벨: Int

#### REQ-092 — 수집 토큰 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 가짜 ssh, Then `collect.sh`가 (a) 정상으로 끝난 뒤, (b) Sonar 읽기 도중 실패한 뒤, (c) 토큰 INSERT의 응답이 유실된 뒤(행은 생김) 모두 가짜 ssh의 행 상태에서 `td-collect-`로 시작하는 행이 0개다. 발급한 토큰 이름은 `td-collect-<UTC시각>-<16진수 8자>` 꼴이고 수집마다 다르다. INSERT 문의 만료는 생성 시각 + 7,200,000ms다.
- 검증 레벨: Int

#### REQ-093 — 토큰 정리 실패의 표시
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 삭제 명령만 실패하는 가짜 ssh, Then 표준 오류에 토큰 이름과 "토큰 잔존 가능", "2시간 후"가 들어간 경고가 한 번 나오고 수집 상태가 `degraded`다.
- 검증 레벨: Int

#### REQ-094 — 수집 토큰 비노출과 미발급
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 수집 1회(기존 관측 훅 `TD_SONAR_TOKEN_OBSERVE`로 토큰을 읽음), Then 수집이 쓴 모든 파일과 로그, 가짜 gh가 받은 인자, 가짜 Sonar가 받은 URL에 토큰 평문이 없다. Given Sonar를 읽을 과제가 하나도 없는 설정, Then 가짜 ssh의 호출 기록이 0건이다.
- 검증 레벨: Int

#### REQ-095 — 파이프라인 과제의 Sonar 출처
- 유형: Functional / 우선순위: Must
- 수용기준:
  - Given `sut`가 있고 완료된 run이 있는 과제, Then 가짜 Sonar가 그 과제의 키로 받은 요청이 0건이고, `projects.json`의 그 과제 `sonar.*` 값이 최신 run의 `run.json` `kpis.sonar`와 같다.
  - Given 최신 run에 `kpis.sonar`가 없는(S11을 돌리지 않은) 과제, Then `sonar.*`는 없음이고 수집기도 읽지 않는다.
  - Given `sut`가 있지만 완료된 run이 없고 `sonarKey`를 적지 않은 과제, Then 수집기가 `sut.yaml`의 `sonar.projectKey`로 Sonar를 읽는다.
- 검증 레벨: Int

#### REQ-096 — 수집 텍스트 가리기
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 설명에 작업 디렉터리 경로와 ARN 모양 문자열을 넣은 가짜 gh 응답, Then 스냅숏과 홈에 그 문자열이 가려져 나오고 업로드 게이트를 통과한다.
- 검증 레벨: Int

#### REQ-097 — S11 토큰과 수집 토큰의 공존
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 가짜 ssh에 만료되지 않은 `td-<runId>` 행(S11의 것)이 있는 상태, When 수집을 실행하면, Then 그 행이 남아 있고 `td-collect-` 행은 0개다. Given `td-collect-x` 행이 있는 상태에서 S11용 발급·정리 함수를 실행하면, Then `td-collect-x`가 남아 있다. PoC REQ-038, 064, 065, 066의 테스트가 기대값을 고치지 않고 통과한다.
- 검증 레벨: Int

#### REQ-143 — 공개 여부를 확인하지 못한 과제
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 어제 공개로 수집된 과제 A와 스냅숏이 없는 과제 B에 대해 가짜 gh가 저장소 조회에 응답하지 않으면, Then A와 B 모두 새 스냅숏이 쓰이지 않고 수집은 `degraded`다. 재생성한 홈에 A는 어제 값으로 나오고 "수집 실패"와 어제 날짜가 표시된다. B는 나오지 않는다. A의 `projects/A/`는 지워지지 않는다.
- 검증 레벨: Int

### 1.4 게시

#### REQ-098 — 인덱스 전용 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 접두에 완료된 run이 하나 있는 상태와 과제 둘을 가진 설정, When `publish-index.sh`를 실행하면, Then 새 run 디렉터리가 생기지 않고, 원본에 두 과제의 `latest.json`·스냅숏·`index.html`·`series.json`과 갱신된 홈·`projects.json`이 `Cache-Control: no-cache`로 올라가 있다. 게시 뒤 미러에도 같은 파일이 남아 있고, 접두의 잠금 객체가 없으며, `<접두>publish-log/index.json`에 상태와 사유가 있다. Lightsail 호스트(`dash.<domain>`)의 같은 접두 `projects.json`이 원본과 바이트로 같다.
- 검증 레벨: E2E-inj

#### REQ-099 — 수집 문제와 게시 상태
- 유형: Functional / 우선순위: Must
- 수용기준: Given 수집이 `degraded`를 돌려준 게시, 수집 자식이 비정상으로 끝난 게시, 수집 결과가 JSON이 아닌 게시(각각 S13과 인덱스 전용), Then 홈과 과제 페이지는 있는 스냅숏으로 갱신돼 게시되고, 게시 상태가 `degraded`이며, 게시 기록(S13은 `suts/<sut>/publish-log/<runId>.json`, 인덱스 전용은 `publish-log/index.json`)의 사유에 수집 사유가 들어 있다. 게시 기록에 제외된 과제의 이름이 없다.
- 검증 레벨: E2E-inj

#### REQ-100 — 빠진 과제의 삭제
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 과제 A, B가 게시된 접두, When (1) A를 설정에서 뺀 뒤 게시하면, 또 (2) A를 되돌려 게시한 다음 가짜 gh가 A를 비공개로 답하게 하고 게시하면, Then 두 경우 모두 원본과 미러에서 `projects/A/` 아래 객체가 0개이고, 홈과 `projects.json`에 A의 이름과 설명이 없으며, Lightsail의 `/srv/dashboard/<접두>projects/A`가 없다. `projects/B/`, `suts/`, `static/`의 객체 수는 줄지 않는다. Given Lightsail에 닿지 않는 상태, Then S3 쪽 삭제와 게시는 끝나고 게시 상태가 `degraded`다. `projects/<이름>/` 꼴이 아닌 접두에 대한 삭제 요청은 거부된다.
- 검증 레벨: E2E-inj

#### REQ-101 — 무효화 경로 묶기
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 과제 20개를 다시 만든 게시, Then 무효화 요청의 경로 가운데 `projects/`로 시작하는 것은 `/<접두>projects/*` 하나다.
- 검증 레벨: Unit

#### REQ-144 — 게시 중단 시 수집 정리
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 수집이 도는 중(가짜 Sonar가 응답을 늦춤)인 인덱스 전용 게시, When 게시기 프로세스에 SIGTERM을, 다른 실행에서는 SIGINT를 보내면, Then 게시가 0이 아닌 종료 코드로 끝난 뒤 가짜 ssh의 `td-collect-` 행이 0개이고, `collect.sh`와 `td.collect` 프로세스가 살아 있지 않으며, 접두의 잠금 객체가 없다.
- 검증 레벨: E2E-inj

#### REQ-145 — 두 게시의 잠금 공유
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 인덱스 전용 게시가 수집 중인 접두, When 같은 접두에 S13 게시를 시작하면, Then S13이 기다리지 않고 `failed`로 끝나며 사유에 잠금 안내(`--force-unlock`)가 있다. 먼저 돌던 인덱스 전용 게시는 정상으로 끝난다.
- 검증 레벨: E2E-inj

### 1.5 인덱스 재생성과 데이터

#### REQ-102 — run 지표 추출
- 유형: Functional / 우선순위: Must
- 수용기준: Given 설계 §6.2 카탈로그의 run 지표에 대한 고정 run 픽스처, Then 각 지표가 기대값과 같다: `e2e.passRate`는 통과 수 합 ÷ 시나리오 수 합, `tia.selectedRatio`는 `selected ÷ indexedTests`, `run.durationSec`는 `stages/S00~S12.json`의 가장 늦은 `finishedAt` − `run.json`의 `startedAt`, Sonar 측정값은 수 타입, `hotspot.topName`은 `top10[0].name`. Given 해당 단계 JSON이 없거나 분모가 0인 run, Then 그 지표는 `null`이다. Given 단계 JSON의 `status`가 `failed` 또는 `skipped`인데 `top10`·`impact`·`generations` 필드가 남아 있는 run, Then 그 지표는 `null`이다.
- 검증 레벨: Unit

#### REQ-103 — 시계열 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given run 3개인 파이프라인 과제, Then `series.json`에 `kind: run`인 점 3개가 runId 순으로 있고 점마다 id, 시각, run 페이지 주소, 설정의 run 지표 값이 있다. Given 스냅숏 2일치인 과제, Then `kind: snapshot`인 점 2개가 날짜 순으로 있고 주소가 없다. 한 파일에 두 종류가 섞이지 않는다.
- 검증 레벨: Unit

#### REQ-104 — 판정 결과 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given 재생성, Then `projects.json`에 과제마다 이름, 상태 수준, 사유 목록, 판정에 쓴 지표 값(파이프라인 과제는 `tests.passRate`, `coverage.line`, `sonar.gate`, `hotspot.topName` 포함), 파이프라인 여부, 부분 측정 여부가 있고, 홈의 표가 보여 주는 상태와 사유가 이 파일과 같다.
- 검증 레벨: Int

#### REQ-105 — 기존 인덱스 파일 호환
- 유형: Functional / 우선순위: Must
- 수용기준: Given 재생성, Then `suts.json`의 항목마다 `name`, `runCount`, `latest`가 있고 `latest`에 `runId`, `commit`, `trigger`, `startedAt`, `stages`, `kpis.passRate`, `kpis.line`, `kpis.sonarGate`, `kpis.hotspot1`이 PoC와 같은 값으로 있다. `suts/<sut>/runs.json`은 run 요약의 배열(최신이 먼저)이고 항목마다 같은 run 필드가 있다.
- 검증 레벨: Unit

#### REQ-106 — 재생성 멱등 (새 파일 포함)
- 유형: Functional / 우선순위: Must
- 수용기준: Given run·스냅숏·설정이 있는 고정 사이트, When 재생성을 두 번 실행하면, Then `index.html`, `projects.json`, `projects/**`, `suts/**/index.html`, `static/v2/**`를 포함한 모든 출력의 바이트가 같다.
- 검증 레벨: Unit

#### REQ-107 — 암묵 과제
- 유형: Functional / 우선순위: Must
- 수용기준: Given 접두에 게시된 완료 run이 있고 설정에 없는 SUT(S11을 돌리지 않음), Then 홈 표에 그 SUT 이름의 줄이 "파이프라인" 표시와 함께 나오고 "부분 측정" 표시는 없으며 상태가 측정 없음이 아니다. `projects/<sut>/index.html`이 있고, 가짜 gh의 호출 기록이 0건이다.
- 검증 레벨: E2E-inj

#### REQ-108 — SUT 안내 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given 재생성, Then `suts/<sut>/index.html`에 그 SUT와 이어진 과제 페이지(설정의 과제 또는 암묵 과제)로 가는 링크가 있고, `meta refresh`의 주소가 그 링크와 같으며, 그 주소가 200으로 열린다.
- 검증 레벨: Int

#### REQ-141 — 집계 지표 계산
- 유형: Functional / 우선순위: Must
- 수용기준: Given 과제 A(CI 9/10), B(CI 1/10), C(CI 없음, Sonar 게이트 `OK`, 커버리지 0), D(게이트 `ERROR`, 커버리지 57.1), Then `ci.successRateAll`은 50%(10 ÷ 20)이고 덧말이 "10 / 20회"다. `sonar.gatePassCount`는 "1 / 2", `sonar.coverageNonZeroCount`는 "1 / 4", `status.noneCount`는 측정 없음 과제 수다. Given 과제가 없으면, Then 0으로 나누지 않고 값이 없음이다.
- 검증 레벨: Unit

### 1.6 첫 화면

#### REQ-109 — 과제 표와 결론 문장
- 유형: Functional / 우선순위: Must
- 수용기준: Given 위험 2, 주의 1, 측정 없음 1, 양호 2인 고정 사이트, Then 화면에서 표에 6줄이 위험 → 주의 → 측정 없음 → 양호 순(같은 상태 안은 이름순)으로 나오고, 결론 문장이 "과제 6개 중 2개가 위험, 1개가 주의입니다"다. Given 위험·주의가 없는 사이트, Then "과제 N개 중 문제 있는 과제가 없습니다"다.
- 검증 레벨: Int

#### REQ-110 — 거르기와 정렬
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 "위험" 버튼을 누르면 위험 행만 남고 버튼의 `aria-pressed`가 `true`다. 이름 칸에 글자를 넣으면 이름에 그 글자가 든 행만 남는다. 열 제목을 누르면 그 열 기준으로 순서가 바뀌고 `aria-sort`가 붙으며, 다시 누르면 반대 순서다. 값이 없는 행은 어느 방향에서도 뒤에 온다.
- 검증 레벨: Int

#### REQ-111 — 행 펼침
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 과제 행을 누르면 그 행의 바로 다음 형제 요소로 상세 행이 생기고 눌린 행의 `aria-expanded`가 `true`다. 상세에 판정 사유, 그 과제의 지표, "과제 페이지 열기" 링크가 있다. 파이프라인 과제의 상세에는 테스트 통과율, 귀속 라인 커버리지, Sonar 게이트, hotspot 1위 이름이 있다. 같은 행을 다시 누르면 상세가 사라진다. 다른 행을 누르면 앞의 상세가 닫힌다. 행에 초점을 두고 Enter를 눌러도 같다.
- 검증 레벨: Int

#### REQ-112 — 스크립트 없는 첫 화면
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 스크립트를 끈 브라우저, Then 과제 줄이 모두 보이고 상태·사유·수치가 읽히며, 과제 이름이 과제 페이지로 가는 링크다.
- 검증 레벨: Int

#### REQ-113 — 없는 값의 표기
- 유형: Non-functional / 우선순위: Must
- 수용기준: 화면에서 Sonar 프로젝트가 없는 과제의 Sonar 게이트 칸은 "연결 없음", 그 과제의 다른 Sonar 칸과 CI가 없는 과제의 CI 칸은 "—"다. 수집이 실패한 출처의 칸은 "측정 없음"이다. 어느 것도 `0`, `0%`, `0.0%`가 아니다. Sonar 커버리지가 실제로 0인 과제는 `0.0%`로 나온다.
- 검증 레벨: Int

#### REQ-114 — 표시와 각주
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 파이프라인을 돌린 과제에만 "파이프라인" 표시가, `repo`가 있고 한 출처만 읽힌 과제에만 "부분 측정" 표시가 있다. 각주에 수준마다 한 줄이 있고 기본 설정에서 주의 줄은 "주의: CI 실행 수 ≥ 5 그리고 CI 성공률 < 90.0% / Sonar 취약점 > 0"이다. Sonar 커버리지가 0인 과제가 있는 사이트의 각주에 "0.0%는 커버리지 리포트를 Sonar에 보내지 않는다는 뜻일 수도 있습니다"가 있고, 없는 사이트에는 없다. `_test/index.html`과 `hosting.html`로 가는 링크가 있다.
- 검증 레벨: Int

#### REQ-142 — 요약 칸, 버튼 개수, CI 이력
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 요약 칸의 수와 순서가 `home.summary`와 같고 값이 `projects.json`의 `summary`와 같다. 상태 버튼마다 적힌 개수가 표에서 그 상태인 행 수와 같다. 과제 행의 "최근 CI 이력" 막대 수가 그 과제의 `ci.runs`와 같고, 실패 막대 수가 `ci.failures`와 같다.
- 검증 레벨: Int

### 1.7 과제 페이지

#### REQ-115 — 탭 전환과 주소
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 탭을 누르면 그 탭의 구역만 보이고 `aria-selected`가 그 탭에만 `true`이며 주소의 `#` 부분이 탭 식별자가 된다. 그 주소로 새로 열면 같은 탭이 열려 있다. 탭 묶음에 `role="tablist"`, 탭에 `role="tab"`과 `aria-controls`, 구역에 `role="tabpanel"`과 `aria-labelledby`가 있고 서로를 가리킨다. 선택된 탭만 `tabindex="0"`이고 나머지는 `-1`이다. 탭에 초점을 두고 오른쪽 방향키를 누르면 다음 탭이, 왼쪽 방향키를 누르면 앞 탭이 선택되고, 끝에서는 반대쪽 끝으로 돈다.
- 검증 레벨: Int

#### REQ-116 — 스크립트 없는 과제 페이지
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 스크립트를 끈 브라우저, Then 모든 탭 구역이 설정의 순서대로 이어서 보이고 각 구역의 수치와 표가 읽힌다.
- 검증 레벨: Int

#### REQ-117 — 탭마다 읽는 법
- 유형: Functional / 우선순위: Must
- 수용기준: Given 과제 페이지, Then 탭 구역마다 "이 탭 읽는 법" 블록이 정확히 하나 있다.
- 검증 레벨: Int

#### REQ-118 — 탭 내용
- 유형: Functional / 우선순위: Must
- 수용기준: Given 고정 run을 가진 파이프라인 과제, Then 화면에서 다음 값이 픽스처와 같다.
  - "한눈에": KPI 5칸, 상위 5개 위험 지점, 이번 변경의 영향(선택 수와 색인 수), 단계 띠(14칸, 누르면 그 단계의 이름과 걸린 시간), 리포트 바로가기.
  - "테스트": 생성 묶음별 통과·실패 수. "커버리지": 묶음별 귀속·집계 값. "위험 지점": 상위 10개. "코드 품질": 종류 × 심각도 이슈 수. "생성 실험": 판정과 방식별 평균. "실행 이력": run 수.
  - 각 탭에 해당 리포트로 가는 링크가 있고 200으로 열린다.
- 검증 레벨: Int

#### REQ-119 — 파이프라인 없는 과제의 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given `sut`가 없는 과제, Then 과제 페이지의 탭이 한눈에, 추이, 코드 품질 셋뿐이고 "한눈에"에 CI 성공률·Sonar 게이트·Sonar 커버리지·취약점·버그가 스냅숏 값으로 나온다.
- 검증 레벨: Int

#### REQ-120 — 시계열 점과 끊김
- 유형: Functional / 우선순위: Must
- 수용기준: Given run 5개 가운데 3번째 run에 통과율이 없는 과제, Then 화면에서 통과율 차트의 점이 4개이고 선이 두 조각이다. Given run 31개, Then 차트의 점은 최근 30개이고 차트 아래 표의 행은 31개다.
- 검증 레벨: Int

#### REQ-121 — 시계열 점의 정보와 링크
- 유형: Functional / 우선순위: Must
- 수용기준: 화면에서 run 점에 초점을 주면 툴팁에 runId와 값이 보이고, 다른 차트에서 `data-id`가 같은 점에 클래스 `hl`이 붙는다. run 점의 링크는 그 run 페이지를 가리키고 200으로 열린다. 스냅숏 점은 링크가 아니고 초점을 주면 날짜와 값이 보인다.
- 검증 레벨: Int

#### REQ-122 — 세로축 규칙
- 유형: Functional / 우선순위: Must
- 수용기준: Given 비율 지표, Then 세로축 눈금이 0%, 50%, 100%이고 값이 모두 20%여도 점이 20% 높이에 있다. Given 퍼센트 값 지표(Sonar 커버리지), Then 축이 0~100 고정이다. Given 값이 3, 18, 7인 개수 지표, Then 가장 위 눈금이 18이다. Given 모든 값이 2인 개수 지표, Then 점이 차트 높이의 가운데에 있다. Given 모든 값이 0인 개수 지표, Then 점이 바닥선에 있다. 같은 입력의 SVG가 두 번의 렌더에서 바이트로 같다.
- 검증 레벨: Unit

#### REQ-123 — 차트와 표의 값 일치
- 유형: Functional / 우선순위: Must
- 수용기준: Given "추이" 탭, Then 차트 아래 표의 각 칸이 `series.json`의 같은 점·같은 지표 값과 같고, 값이 없는 칸은 "—"다.
- 검증 레벨: Int

### 1.8 run 페이지와 리포트 간 링크

#### REQ-124 — run 페이지
- 유형: Functional / 우선순위: Must
- 수용기준: Given 고정 사이트의 run, Then 화면에서 run 페이지에 단계 14개의 띠가 있고 단계를 누르면 그 단계의 이름·상태·걸린 시간이 나온다. 성공한 리포트마다 카드가 있고 링크가 200으로 열린다. S13 게시 결과가 기존처럼 표시된다.
- 검증 레벨: Int

#### REQ-125 — 공통 띠의 존재와 링크
- 유형: Functional / 우선순위: Must
- 수용기준: Given 표본 리포트를 가진 로컬 run을 접두(`_test/<id>/`) 아래에 게시한 상태, Then run 페이지, `coverage/coverage.html`, `sonar/sonar.html`, `compare/compare.html`, `ontology/jqa.html`, `ontology/owl.html`, `hotspot/hotspots.html`, `hotspot/api_report.html`, `tia/tia.html`, 각 `cucumber/<genId>/index.html`에 공통 띠가 정확히 하나 있고, 띠의 홈·SUT·run·다른 리포트 링크가 모두 그 접두 안에서 200으로 열린다. 띠의 SUT 링크는 `suts/<sut>/index.html`이다.
- 검증 레벨: E2E-inj

#### REQ-126 — 띠를 끼운 리포트의 기능 유지
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 띠를 끼운 표본 `hotspots.html`, Then 화면에서 지도 SVG에 원이 그려지고 원을 누르면 옆 패널의 글이 바뀐다. Given 띠를 끼운 표본 `tia.html`, Then 페이지 전환 탭을 누르면 본문이 바뀐다. `api_report.html`과 Cucumber `index.html`을 포함해 네 페이지 모두 열 때 페이지 오류가 없고, 띠 요소에 `<script>`가 없다. run 작업 디렉터리의 원본 파일은 띠를 끼우기 전과 바이트로 같다.
- 검증 레벨: Int

#### REQ-127 — 띠를 넣을 수 없는 파일
- 유형: Functional / 우선순위: Must
- 수용기준: Given `<body>`가 없는 HTML을 리포트 진입 파일로 주입한 run, Then 그 파일은 원본 그대로 게시되고, run 페이지의 그 리포트 카드에 "공통 띠 없음"과 사유가 나오며, S13 상태가 `degraded`다. Given `<BODY class="x">`처럼 대문자와 속성이 있는 HTML, Then 띠가 그 태그 바로 뒤에 들어간다.
- 검증 레벨: Int

#### REQ-128 — 직접 만드는 리포트의 새 틀
- 유형: Functional / 우선순위: Must
- 수용기준: Given 고정 사이트의 run의 `coverage.html`, `sonar.html`, `compare.html`, `jqa.html`, `owl.html`과 `hosting.html`, Then 각 페이지가 새 디자인의 스타일(`static/v2/app.css`를 불러오거나, 온톨로지처럼 인라인이면 그 내용)을 쓰고 `static/site.css`를 불러오지 않는다. 이 화면들을 검사하는 PoC 테스트(REQ-016, 017, 033, 034, 037, 040, 051, 067, 073의 테스트)가 §3에 적은 자산 경로 기대값만 고친 채 통과한다.
- 검증 레벨: Int

### 1.9 도구 고정과 새 리포트

#### REQ-129 — hotspot 커밋 고정 빌드
- 유형: Functional / 우선순위: Must
- 수용기준: Given `tools.pin.yaml`의 hotspot이 40자 커밋, When S00을 실행하면, Then 도구 디렉터리의 hotspot 소스 체크아웃의 `git rev-parse HEAD`가 그 커밋이고, `hotspot.jar`가 있으며, `tools.lock`의 hotspot에 그 커밋과 jar의 sha256이 있고 그 sha256이 파일과 같다. Given 40자가 아닌 커밋, Then 핀 읽기가 실패한다.
- 검증 레벨: Int

#### REQ-130 — 새 hotspot 리포트 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then 게시된 `hotspots.html`에 `id="hotspot-map-data"`인 JSON 블록이 있고 그 `schemaVersion`이 1이며, 화면에서 지도 SVG에 원이 하나 이상 있다. `stages/S09.json`의 `top10`이 1~10개이고 항목마다 `name`, `file`, `score`가 있으며 점수 내림차순이다.
- 검증 레벨: E2E

#### REQ-131 — 새 TIA 리포트 게시
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run, Then 화면에서 게시된 `tia.html`의 페이지 전환 탭이 4개이고 첫 탭이 변경 영향이며, 탭마다 "읽는 법" 블록이 하나 보인다. 변경 영향 페이지의 변경 파일 수가 `S10/impact.json`의 `changedFiles` 길이와 같다.
- 검증 레벨: E2E

### 1.10 공통

#### REQ-132 — 외부 요청 없음
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 고정 사이트의 홈, 과제 페이지(탭마다), run 페이지, REQ-125에 적은 모든 리포트 진입 페이지와 `hosting.html`을 브라우저로 열 때, Then 사이트 밖 호스트로 나가는 네트워크 요청이 0건이다. `static/v2/app.css`에 `@import`와 `url(http`가 없고, 직접 만드는 HTML에 사이트 밖 주소를 가리키는 `<script src>`, `<link href>`, `<img src>`가 없다.
- 검증 레벨: Int

#### REQ-133 — 좁은 화면
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 360px 폭, Then 홈, 과제 페이지(탭마다), run 페이지, `sonar.html`, `compare.html`, `hosting.html`에서 `scrollWidth <= innerWidth`다. 이름 60자, 설명 200자인 과제가 있는 홈에서도 같다.
- 검증 레벨: Int

#### REQ-134 — 어두운 테마
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given `prefers-color-scheme: dark`, Then 홈, 과제 페이지, `sonar.html`, `compare.html`, `hosting.html`의 body 배경색이 밝은 테마와 다르다. 두 테마에서 상태 표시 요소의 계산된 글자색과 그 요소가 놓인 면의 배경색의 명암비가 4.5 이상이다.
- 검증 레벨: Int

#### REQ-135 — 색에 기대지 않는 상태 표시
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given 홈, Then 상태 표시마다 상태 이름 글자가 있다. 상태 표시 앞의 표식은 계산된 스타일로 위험이 채운 원(`border-radius` 50%, 배경색 있음), 주의가 네모(`border-radius`가 위험과 다름), 측정 없음이 빈 원(배경 투명, 테두리 있음)이다.
- 검증 레벨: Int

#### REQ-136 — 옛 자산 불변
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 재생성, Then 게시되는 `static/site.css`의 sha256이 `27166871ff7312b677dd65cb0b96baee7499f1b38cbb92cd4b8f2befcf42710f`, `static/site.js`의 sha256이 `8bd8e8f766db637afb9c3962982b7e21fdd5a9d746e7f7251d7d0582ce63e07e`다. Given 옛 템플릿으로 렌더해 커밋해 둔 run 페이지 픽스처(`tests/fixtures/legacy-run-page/index.html`), Then 재생성 뒤 화면에서 그 페이지의 표 머리 배경색과 본문 글꼴 크기가 픽스처와 함께 기록해 둔 값과 같다.
- 검증 레벨: Int

#### REQ-137 — 새 자산 경로
- 유형: Non-functional / 우선순위: Must
- 수용기준: Given 새로 만든 run 페이지와 인덱스 페이지, Then 스타일과 스크립트를 `static/v2/` 아래에서만 불러온다(`static/site.css`를 불러오지 않는다).
- 검증 레벨: Unit

#### REQ-138 — 움직임 줄이기
- 유형: Non-functional / 우선순위: Should
- 수용기준: Given `prefers-reduced-motion: reduce`, Then 펼침 화살표의 계산된 `transition-duration`이 `0s`다.
- 검증 레벨: Int

#### REQ-139 — 운영 사이트의 경로
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run 세션 뒤, Then `https://reports.<domain>/` 홈의 과제 줄 수가 운영 `projects.json`의 과제 수와 같고 그 수가 `dashboard.yaml`의 과제 수 이하다. 과제 페이지 → 최신 run → `hotspots.html`과 `tia.html` → 띠의 SUT 링크 → 과제 페이지가 `reports.<domain>`과 `dash.<domain>` 양쪽에서 모두 200이다. 띠의 SUT 링크는 run 페이지와 `hotspots.html`의 `a.tdnav-sut` href를 읽어 따라간다(SUT 안내 페이지를 거쳐 과제 페이지에 닿는다). 이 작업 전에 게시된 run `20261120-131022Z-b6f9393-manual-036c288d`의 페이지가 200이고 `static/site.css`를 불러온다. 두 호스트에서 `_design/home-repos/`와 `_design/project/`는 200이 아니다.
- 검증 레벨: E2E

#### REQ-140 — 운영 사이트의 값
- 유형: Functional / 우선순위: Must
- 수용기준: Given 기준 run 세션 뒤,
  - 운영 `projects/hotspot-analysis/latest.json`의 `ci.runs`가 수이고, 테스트가 실제 `gh api`로 같은 저장소의 실행 목록을 읽어 같은 규칙으로 센 값과 2 이내로 같다(수집과 테스트 사이에 실행이 늘 수 있다).
  - 화면에서 운영 홈의 파이프라인 과제 행의 상태와 사유가 운영 `projects.json`과 같다.
  - 화면에서 그 과제 페이지 "추이"의 통과율 차트 점 수가 운영 `runs.json`에서 통과율이 있는 run 수(최대 30)와 같다.
  - 화면에서 "한눈에"의 통과율과 귀속 라인 값이 운영 `runs.json`의 최신 run(과제 페이지가 보여 주는 run)의 값과 같다.
- 검증 레벨: E2E

## 2. 추적 매트릭스

| REQ-ID | 요구사항 | 수용 테스트 | Level | Status |
|---|---|---|---|---|
| REQ-076 | 설정 스키마 검증 | test_dashboard_config.py::test_req076_cli_fails_before_writing<br>test_dashboard_config.py::test_req076_schema_violation_fails | Unit | 🟢 passed |
| REQ-077 | 과제 등록 검증 | test_dashboard_config.py::test_req077_project_registration_rules | Unit | 🟢 passed |
| REQ-078 | 지표 카탈로그 대조 | test_dashboard_config.py::test_req078_unknown_metric_or_operator | Unit | 🟢 passed |
| REQ-079 | 접두 실행의 설정 격리 | test_dashboard_publish.py::test_req079_prefix_run_uses_only_given_config | E2E-inj | 🟢 passed |
| REQ-080 | 설정으로 화면 구성 | test_dashboard_project.py::test_req080_home_columns_and_summary_from_config<br>test_dashboard_project.py::test_req080_none_all_missing_from_config<br>test_dashboard_project.py::test_req080_status_labels_and_order_from_config<br>test_dashboard_project.py::test_req080_tabs_and_trend_from_config | Int | 🟢 passed |
| REQ-081 | 규칙별 판정 | test_dashboard_status.py::test_req081_rule_levels_and_reasons | Unit | 🟢 passed |
| REQ-082 | 없는 값과 경계 | test_dashboard_status.py::test_req082_missing_and_boundaries | Unit | 🟢 passed |
| REQ-083 | 임계값 변경 반영 | test_dashboard_status.py::test_req083_threshold_change_changes_verdict | Int | 🟢 passed |
| REQ-084 | 결론 문장 | test_dashboard_project.py::test_req084_headline_rendered<br>test_dashboard_status.py::test_req084_headline_selection | Int | 🟢 passed |
| REQ-085 | GitHub CI 수집 | test_dashboard_collect.py::test_req085_ci_conclusion_classes | Int | 🟢 passed |
| REQ-086 | 최신 커밋 검사 | test_dashboard_collect.py::test_req086_latest_check_per_name | Int | 🟢 passed |
| REQ-087 | SonarQube 수집 | test_dashboard_collect.py::test_req087_sonar_values_and_404 | Int | 🟢 passed |
| REQ-088 | 스냅숏 파일 | test_dashboard_collect.py::test_req088_snapshot_files_and_schema | Int | 🟢 passed |
| REQ-089 | 비공개 제외 | test_dashboard_collect.py::test_req089_invalid_repo_is_config_error<br>test_dashboard_collect.py::test_req089_private_repo_excluded<br>test_dashboard_home.py::test_req089_excluded_project_absent_from_site | Int | 🟢 passed |
| REQ-090 | 수집 부분 실패 | test_dashboard_collect.py::test_req090_partial_failure_null_not_carried<br>test_dashboard_home.py::test_req090_failed_source_cell_title | Int | 🟢 passed |
| REQ-091 | 수집 시간 예산과 재시도 | test_dashboard_collect.py::test_req091_at_most_three_attempts<br>test_dashboard_collect.py::test_req091_budget_and_retry<br>test_dashboard_collect.py::test_req091_retry_after_beyond_budget_not_awaited<br>test_dashboard_collect.py::test_req091_retry_after_is_honoured | Int | 🟢 passed |
| REQ-092 | 수집 토큰 정리 | test_dashboard_collect.py::test_req092_token_removed_on_all_exits | Int | 🟢 passed |
| REQ-093 | 토큰 정리 실패 표시 | test_dashboard_collect.py::test_req093_cleanup_failure_warns_degraded | Int | 🟢 passed |
| REQ-094 | 토큰 비노출·미발급 | test_dashboard_collect.py::test_req094_token_not_leaked_and_not_issued_when_unneeded | Int | 🟢 passed |
| REQ-095 | 파이프라인 과제의 Sonar 출처 | test_dashboard_collect.py::test_req095_pipeline_project_sonar_from_run | Int | 🟢 passed |
| REQ-096 | 수집 텍스트 가리기 | test_dashboard_collect.py::test_req096_external_text_redacted | Int | 🟢 passed |
| REQ-097 | 토큰 공존 | test_dashboard_collect.py::test_req097_named_issue_and_revoke_need_no_stage_state<br>test_dashboard_collect.py::test_req097_named_revoke_after_lost_insert_reply<br>test_dashboard_collect.py::test_req097_named_revoke_failure_warns_once<br>test_dashboard_collect.py::test_req097_named_revoke_hook_stage<br>test_dashboard_collect.py::test_req097_s11_and_collect_tokens_coexist<br>test_dashboard_collect.py::test_req097_s11_wrapper_leaves_collect_rows | Int | 🟢 passed |
| REQ-098 | 인덱스 전용 게시 | test_dashboard_publish.py::test_req098_index_only_publish | E2E-inj | 🟢 passed |
| REQ-099 | 수집 문제와 게시 상태 | test_dashboard_collect.py::test_req099_collect_sh_injection_points<br>test_dashboard_publish.py::test_req099_collect_trouble_still_publishes | E2E-inj | 🟢 passed (주: E2E는 수집이 degraded일 때 과제 페이지가 게시돼 있는지만 보고, 그 LastModified가 늘었는지는 보지 않는다) |
| REQ-100 | 빠진 과제의 삭제 | test_dashboard_publish.py::test_req100_removed_or_private_project_deleted<br>test_unit_publish.py::test_req100_delete_prefix_batches_and_reports_errors_without_names<br>test_unit_publish.py::test_req100_delete_prefix_guard<br>test_unit_publish.py::test_req100_delete_prefix_guard_and_lightsail_degraded<br>test_unit_publish.py::test_req100_failed_listing_is_degraded_without_removals<br>test_unit_publish.py::test_req100_lightsail_list_command_guard<br>test_unit_publish.py::test_req100_lightsail_remove_command_guard<br>test_unit_publish.py::test_req100_missing_remote_projects_dir_is_not_an_error<br>test_unit_publish.py::test_req100_no_prune_when_keep_set_cannot_be_computed<br>test_unit_publish.py::test_req100_preflight_error_skips_prune_and_next_publish_catches_up<br>test_unit_publish.py::test_req100_remote_prune_keeps_excluded_out_of_keep_set<br>test_unit_publish.py::test_req100_remote_prune_never_passes_unsafe_names_to_rm<br>test_unit_publish.py::test_req100_remote_prune_retries_failed_removal_on_next_publish | E2E-inj | 🟢 passed |
| REQ-101 | 무효화 경로 묶기 | test_unit_publish.py::test_req101_projects_invalidation_wildcard | Unit | 🟢 passed |
| REQ-102 | run 지표 추출 | test_dashboard_index.py::test_req102_run_metrics | Unit | 🟢 passed |
| REQ-103 | 시계열 파일 | test_dashboard_index.py::test_req103_series_points | Unit | 🟢 passed |
| REQ-104 | 판정 결과 파일 | test_dashboard_home.py::test_req104_projects_json_matches_table | Int | 🟢 passed |
| REQ-105 | 기존 인덱스 파일 호환 | test_dashboard_index.py::test_req105_legacy_fields_kept | Unit | 🟢 passed |
| REQ-106 | 재생성 멱등 | test_dashboard_index.py::test_req106_idempotent_all_outputs | Unit | 🟢 passed |
| REQ-107 | 암묵 과제 | test_dashboard_publish.py::test_req107_unregistered_sut_listed | E2E-inj | 🟢 passed |
| REQ-108 | SUT 안내 페이지 | test_dashboard_project.py::test_req108_sut_landing | Int | 🟢 passed |
| REQ-109 | 과제 표와 결론 문장 | test_dashboard_home.py::test_req109_headline_omits_zero_side<br>test_dashboard_home.py::test_req109_rows_order_headline | Int | 🟢 passed |
| REQ-110 | 거르기와 정렬 | test_dashboard_home.py::test_req110_filter_keeps_sort_and_hides_detail<br>test_dashboard_home.py::test_req110_filter_search_sort | Int | 🟢 passed |
| REQ-111 | 행 펼침 | test_dashboard_home.py::test_req111_inline_expand<br>test_dashboard_home.py::test_req111_name_link_expands_with_script | Int | 🟢 passed |
| REQ-112 | 스크립트 없는 첫 화면 | test_dashboard_home.py::test_req112_without_javascript | Int | 🟢 passed |
| REQ-113 | 없는 값의 표기 | test_dashboard_home.py::test_req113_failed_ci_source_cells<br>test_dashboard_home.py::test_req113_missing_not_zero | Int | 🟢 passed |
| REQ-114 | 표시와 각주 | test_dashboard_home.py::test_req114_tags_rules_links | Int | 🟢 passed |
| REQ-115 | 탭 전환과 주소 | test_dashboard_project.py::test_req115_tabs_hash_keyboard | Int | 🟢 passed |
| REQ-116 | 스크립트 없는 과제 페이지 | test_dashboard_project.py::test_req116_without_javascript | Int | 🟢 passed |
| REQ-117 | 탭마다 읽는 법 | test_dashboard_project.py::test_req117_one_guide_per_panel | Int | 🟢 passed |
| REQ-118 | 탭 내용 | test_dashboard_project.py::test_req118_other_tabs<br>test_dashboard_project.py::test_req118_overview<br>test_dashboard_project.py::test_req118_report_links_resolve | Int | 🟢 passed |
| REQ-119 | 파이프라인 없는 과제 | test_dashboard_project.py::test_req119_snapshot_only_project | Int | 🟢 passed |
| REQ-120 | 시계열 점과 끊김 | test_dashboard_project.py::test_req120_trend_points_gaps_cap | Int | 🟢 passed |
| REQ-121 | 시계열 점 정보와 링크 | test_dashboard_project.py::test_req121_point_tooltip_highlight_links | Int | 🟢 passed |
| REQ-122 | 세로축 규칙 | test_dashboard_index.py::test_req122_chart_axis_rules | Unit | 🟢 passed |
| REQ-123 | 차트와 표의 값 일치 | test_dashboard_project.py::test_req123_table_matches_series | Int | 🟢 passed |
| REQ-124 | run 페이지 | test_dashboard_nav.py::test_req124_run_page<br>test_dashboard_nav.py::test_req124_run_page_without_javascript_shows_every_stage<br>test_dashboard_nav.py::test_req124_strip_links_resolve_under_prefix | Int | 🟢 passed |
| REQ-125 | 공통 띠 | test_dashboard_publish.py::test_req125_nav_on_all_reports_under_prefix | E2E-inj | 🟢 passed |
| REQ-126 | 띠 뒤 기능 유지 | test_dashboard_nav.py::test_req126_external_reports_still_work<br>test_dashboard_nav.py::test_req126_nav_markup_contract | Int | 🟢 passed |
| REQ-127 | 띠를 넣을 수 없는 파일 | test_dashboard_nav.py::test_req127_clean_run_is_passed<br>test_dashboard_nav.py::test_req127_inject_finds_first_body_case_insensitively<br>test_dashboard_nav.py::test_req127_no_body_degraded<br>test_dashboard_nav.py::test_req127_render_json_is_not_published | Int | 🟢 passed |
| REQ-128 | 직접 만드는 리포트의 새 틀 | test_dashboard_nav.py::test_req128_own_reports_new_frame<br>test_dashboard_nav.py::test_req128_standalone_reports_copy_app_css | Int | 🟢 passed |
| REQ-129 | hotspot 커밋 고정 빌드 | test_prepare.py::test_req129_hotspot_commit_build<br>test_unit_tools.py::test_req129_short_hotspot_commit_fails | Int | 🟢 passed |
| REQ-130 | 새 hotspot 리포트 | test_baseline.py::test_req130_hotspot_map_published | E2E | 🟢 passed |
| REQ-131 | 새 TIA 리포트 | test_baseline.py::test_req131_tia_report_published | E2E | 🟢 passed |
| REQ-132 | 외부 요청 없음 | test_dashboard_common.py::test_req132_no_external_requests | Int | 🟢 passed |
| REQ-133 | 좁은 화면 | test_dashboard_common.py::test_req133_responsive_360 | Int | 🟢 passed |
| REQ-134 | 어두운 테마 | test_dashboard_common.py::test_req134_dark_theme | Int | 🟢 passed |
| REQ-135 | 색에 기대지 않는 상태 표시 | test_dashboard_common.py::test_req135_status_not_color_only | Int | 🟢 passed |
| REQ-136 | 옛 자산 불변 | test_dashboard_common.py::test_req136_legacy_assets_unchanged | Int | 🟢 passed |
| REQ-137 | 새 자산 경로 | test_dashboard_common.py::test_req137_app_css_tokens_and_no_external_requests<br>test_dashboard_common.py::test_req137_v2_asset_paths | Unit | 🟢 passed |
| REQ-138 | 움직임 줄이기 | test_dashboard_common.py::test_req138_reduced_motion | Int | 🟢 passed |
| REQ-139 | 운영 사이트의 경로 | test_baseline.py::test_req139_production_site_paths | E2E | 🟢 passed |
| REQ-140 | 운영 사이트의 값 | test_baseline.py::test_req140_production_site_values | E2E | 🟢 passed |
| REQ-141 | 집계 지표 계산 | test_dashboard_index.py::test_req141_aggregate_metrics<br>test_dashboard_index.py::test_req141_none_count_counts_unmeasured_projects | Unit | 🟢 passed |
| REQ-142 | 요약 칸·버튼 개수·CI 이력 | test_dashboard_home.py::test_req142_summary_counts_history | Int | 🟢 passed |
| REQ-143 | 공개 여부 미확인 과제 | test_dashboard_collect.py::test_req143_visibility_unknown_keeps_last_public<br>test_dashboard_home.py::test_stale_tag_shows_last_collected_date | Int | 🟢 passed |
| REQ-144 | 게시 중단 시 수집 정리 | test_dashboard_collect.py::test_req144_collect_sh_signal_revokes_token<br>test_dashboard_collect.py::test_req144_signal_during_revoke_still_removes_token<br>test_dashboard_publish.py::test_req144_interrupt_cleans_collect_token_and_lock | E2E-inj | 🟢 passed |
| REQ-145 | 두 게시의 잠금 공유 | test_dashboard_publish.py::test_req145_index_only_and_s13_share_lock | E2E-inj | 🟢 passed |

Coverage: 70/70 green (100%) — target 100% (대상: Must 65 + Should 5. Could 0, 연기 없음). 판정 근거: 2026-11-22 운영 기준 run 세션(`tests/acceptance/run_baseline.py`: 기준 run `20261122-012427Z-b6f9393-manual-f77d0b3f`, 두 번째 run `20261122-013901Z-b6f9393-manual-94bb8f06`, 인덱스 전용 게시 passed, 시안 `_design/` 삭제 뒤) 다음의 전체 실행(`pytest tests/acceptance -v`, 세션 `t14c`)이 880 passed, 0 failed이고 표의 테스트 이름이 모두 그 실행의 PASSED 목록에 있다. 최종 리뷰 수정 뒤 다시 돌린 전체 실행(세션 `t15a`, 같은 기준 run 세션 파일)도 903 passed, 0 failed이고 표의 테스트 이름이 모두 PASSED 목록에 있다.

## 3. PoC 요구사항과 테스트의 개정

이 작업은 PoC 요구사항명세의 아래 항목을 바꾼다. 구현 PR에서 PoC 명세의 해당 항목과 테스트를 함께 고치고, PoC 매트릭스의 상태를 다시 green으로 확인한다. 이 표에 없는 PoC 테스트가 깨지면 기대값이 아니라 구현을 고친다.

| PoC REQ | 바뀌는 수용기준 | 테스트 처리 |
|---|---|---|
| REQ-035 hotspot 리포트 | 그대로. 새 지도 블록은 REQ-130이 본다. run 페이지의 링크는 리포트 카드로 바뀐다 | 링크를 찾는 선택자만 고친다 |
| REQ-036 TIA 리포트 | 그대로. 새 페이지 구성은 REQ-131이 본다 | "리포트에 내장된 커밋 값"을 읽는 위치를 새 템플릿의 데이터에 맞춘다 |
| REQ-040 S12 사이트 | 비교 화면이 불러오는 스타일이 `static/v2/app.css`다 | `test_req040_s12_stage_site_and_run_json`의 `static/site.css` 단언을 고친다 |
| REQ-044 run 이력 누적 | "SUT 페이지 이력 표에 두 run"을 "그 SUT와 이어진 과제 페이지의 실행 이력 탭에 두 run, 그리고 `runs.json`에 두 run"으로 바꾼다 | `test_req044_history_accumulates`의 확인 위치를 고친다 |
| REQ-045 인덱스 멱등 | 그대로. 새 출력까지 넓힌 것이 REQ-106이다 | 고치지 않는다 |
| REQ-047, 048 호스팅 크롤 | "홈에 최신 runId"를 "과제 페이지의 실행 이력과 `runs.json`에 최신 runId"로 바꾼다. 크롤 범위에 `/projects/`와 `/projects.json`을 더한다 | `test_hosting.py`의 `_scope()`와 runId 확인 위치를 고친다 |
| REQ-049 홈과 SUT 페이지 | "홈에 SUT별 최신 run의 KPI"를 "홈의 과제 데이터(`projects.json`과 페이지 안 JSON 블록)에 그 SUT와 이어진 과제의 테스트 통과율, 귀속 라인 커버리지, Sonar 게이트, hotspot 1위가 있고, 과제 페이지 '한눈에'에 그 값이 서버 렌더로 보인다"로 바꾼다. "SUT 페이지에 run 이력 표와 KPI 추이 차트"를 "SUT 페이지가 안내하는 과제 페이지의 실행 이력 구역과 추이 구역(서버가 그린 SVG)"으로 바꾼다 | 세 테스트(`test_baseline`, `test_coverage`, `test_site`)는 지금처럼 HTML 문자열과 JSON을 읽는다. 읽는 파일과 선택자를 고친다 |
| REQ-050 멀티 SUT | "홈에 SUT 2개"를 "홈의 과제 표에 두 SUT의 암묵 과제가 나오고, 각 과제 페이지에 그 SUT의 runId가 있다"로 바꾼다 | `test_req050_multi_sut`와 `_sut_card`를 고친다 |
| REQ-051, 073 hosting.html | 불러오는 스타일이 `static/v2/app.css`다 | `test_unit_hosting.py`의 `href="static/site.css"` 단언을 고친다 |
| REQ-058 tools.lock | hotspot 항목이 버전이 아니라 커밋과 jar의 sha256이다. TIA 커밋이 `c4e6e9e2c18f52e3315cc90a6f98fa16506c9199`다 | `test_req058_*`의 hotspot·TIA 기대값을 고친다. 릴리스 jar의 sha256 변조를 보는 테스트(`test_s00_tampered_pin_sha256_fails_and_keeps_cache`, `test_unit_tools.py`의 `record_pin` 테스트)는 대상을 pjacoco로 바꾼다 |
| REQ-037 Sonar 화면 | 단독 열람용으로 옆에 복사하는 스타일 파일이 `app.css`다 | `test_unit_sonar.py`의 `site.css` 파일 단언을 고친다 |
| REQ-038, 064~066 Sonar 토큰 | 그대로. 구현이 공용 함수 위로 옮겨진다 | 고치지 않는다(REQ-097) |
| REQ-016, 017, 033, 034, 067 화면 | 그대로. 새 틀에서 다시 통과해야 한다 | `test_req067_*`가 `site.css`의 테마 토큰을 읽는 부분만 `static/v2/app.css`로 고친다. 나머지는 고치지 않는다 |
| REQ-046 게시 잠금 | 그대로. 인덱스 전용 게시도 같은 잠금을 쓴다(REQ-145) | 고치지 않는다 |
| REQ-071 run 페이지의 S13 표시 | 그대로. run 페이지의 단계 표가 단계 띠(`#stage-strip`)와 단계 상세(`#stage-detail`)로 바뀐다 | 매트릭스 밖 보조 테스트 `test_site.py::test_site_js_shows_publish_log_or_graceful_absence`의 S13 행 선택자(`#stages tr[data-stage=S13]`)를 단계 띠의 S13 버튼을 누른 뒤 `#stage-detail`을 읽는 것으로 고친다 |

PoC 설계 §13.2의 "홈 하단의 테스트 실행 기록 링크"는 REQ-114가 본다. PoC 요구사항명세 §0.1의 "기준 run" 줄에 인덱스 전용 게시 1회를 더한다.

## 4. 자기검토

- 설계의 목표 8개가 모두 REQ에 이어진다: 목표 1 → 109~114·141·142, 목표 2 → 085~096·098·107·143, 목표 3 → 115~123, 목표 4 → 076~084, 목표 5 → 124~127, 목표 6 → 129~131, 목표 7 → 128·133~137, 목표 8 → 098·132·139·140.
- 반목표가 모두 REQ에 이어진다: 값 지어내기 → 085·090·113, 거짓 결론 → 082·084, 외부 요청 → 132, 스크립트 없음 → 112·116, 비공개 노출 → 089·099·100·143, 판정 사유 → 081·104·111.
- 수용 테스트를 두지 않는 설계 항목:
  - README 갱신(문서 게이트에서 확인).
  - 최근 변경일은 절대 날짜만 표시한다(상대 시각은 구현하지 않았다. 서버가 그린 절대 날짜는 REQ-112가 본다).
  - `_test/index.html`의 새 틀(REQ-137이 자산 경로를 본다).
  - 공용 자산의 버전 규칙("게시한 버전은 고치지 않는다")은 운영 규칙이다. 옛 자산은 REQ-136이 지킨다.
  - 띠를 끼운 뒤 가리기 게이트를 지나는 순서(기존 가리기 테스트와 REQ-096이 결과를 본다).
- 고정 사이트와 가짜로 보는 요구사항은 Int로 적었다. 실제 `gh`, 실제 run, 운영 사이트로 확인하는 것은 REQ-130, 131, 139, 140이다.
- 각 REQ는 하나의 행위이고 측정 가능한 Given-When-Then이 있다. 수집과 판정은 가짜의 호출 기록과 고정 입력으로 판정하고, 구현의 자기 보고만으로 판정하지 않는다.
- Must 65, Should 5(REQ-101, 133, 134, 135, 138). 총 70개. REQ-097은 v1의 "S11 토큰 동작 유지"를 관측할 수 있는 행위로 다시 썼다(번호 유지).
