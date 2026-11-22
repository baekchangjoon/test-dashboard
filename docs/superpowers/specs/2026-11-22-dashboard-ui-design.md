# test-dashboard 화면 재설계

- 작성일: 2026-11-22 (v2: 빌더 점검과 Claude·GPT 리뷰 반영, v2.1: Gemini 리뷰 반영, v2.2: 요구사항명세 리뷰의 역전파. 같은 날 구현 뒤 최종 리뷰에 맞춰 사실만 고침: §3 제약 5, §5.5 좁은 화면의 띠, §6.2 `run.durationSec`, §6.3 시간 제한·`projects/_collect.json`, §6.6 경로 목록)
- 상태: 승인됨 (2026-11-22)
- 저장소: `baekchangjoon/test-dashboard` (공개), 브랜치 `feat/dashboard-design`
- 앞선 문서: `docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md` (PoC 설계 v3)
- 시안(사용자가 확인함): `docs/superpowers/specs/assets/2026-11-22-dashboard-ui/home.html`(첫 화면), `project.html`(과제 페이지). 브라우저로 바로 열 수 있다. 같은 파일이 `https://reports.<domain>/_design/`에도 올라가 있고, 구현이 끝나면 그쪽은 지운다(§8.3).

인프라 식별자는 PoC 설계와 같은 규칙으로 이 문서에 쓰지 않는다.

**이 문서가 바꾸는 PoC 설계의 절**

| PoC 설계 | 바뀌는 내용 |
|---|---|
| §6.1 S00 | hotspot-analysis를 릴리스 jar가 아니라 커밋 고정 + 소스 빌드로 받는다 |
| §6.10 S09 | 도구가 만든 HTML에 공통 띠를 끼워 게시한다 |
| §6.11 S10 | `tia report`에 `--impact`를 넘긴다 |
| §6.13, §13.3 | Sonar 임시 토큰을 S11 밖(수집기)에서도 쓴다. 토큰 이름 규칙이 늘어난다 |
| §6.14, §13.1 | 사이트 구조, 인덱스 재생성의 입력(설정, 수집 스냅숏), run 없이 인덱스만 게시하는 경로 |
| §13.2 | 홈의 `_test` 목록 링크 위치 |

영향받는 PoC 요구사항은 적어도 REQ-035, 036, 045, 049, 050, 058, 064~066이다. 요구사항명세를 만들 때 각각을 어떻게 고치는지 적고, PR에서 PoC 설계의 위 절도 함께 고친다.

## 1. 의도와 배경

지금 사이트는 파이프라인이 만든 산출물을 링크로 늘어놓은 수준이다. 홈은 KPI 카드, 과제 페이지는 선 차트 두 개와 표, run 페이지는 링크 목록이 전부다. 스타일 76줄, 스크립트 29줄이다.

이 대시보드를 볼 사람은 프로덕트에 참여하는 모두이고, 우선순위는 다음 순서다(사용자 결정).

1. C레벨 리더
2. 팀장급 리더
3. PM급 리더
4. 전사 품질 담당자
5. 과제별 개발자, 과제 품질 담당자

그래서 화면은 "어느 과제가 문제인가"를 첫 화면에서 알아챌 수 있어야 하고, 리더가 읽는 내용이 앞에, 개발자가 파고드는 내용이 뒤에 와야 한다.

참고한 작업은 두 가지다.

- hotspot-analysis PR #53: 결론 문장을 먼저 말하고, 누르면 한 단계씩 들어가고, 점수가 어떻게 나왔는지 풀어 준다.
- test-impact-analysis PR #36: 페이지마다 질문 하나, 페이지마다 "이 탭 읽는 법" 한 줄, 외부 요청 0.

두 리포트는 지금 대시보드에 실리지 않는다. `tools.pin.yaml`이 리디자인 이전 버전(hotspot `v0.1.6`, tia `634a4a3`)을 가리키기 때문이다.

## 2. 목표 / 비목표 / 반목표

### 목표

1. 첫 화면에 과제 목록과 과제별 품질 상태, 주요 지표가 나온다. 문제 있는 과제가 위에 온다.
2. 파이프라인을 돌리지 않은 과제도 목록에 나온다. GitHub CI와 SonarQube에서 읽은 값으로 상태를 판정한다.
3. 과제 페이지는 결론 문장과 탭으로 구성하고, run별 지표를 시계열로 보여 준다.
4. 상태 판정 규칙과 화면 구성(첫 화면의 열, 과제 페이지의 탭과 순서, 시계열 지표)을 설정 파일로 바꿀 수 있다.
5. 새 디자인으로 게시된 run의 모든 리포트 HTML이 서로 링크로 이어진다. 어느 리포트에서든 과제 페이지와 같은 run의 다른 리포트로 갈 수 있다.
6. 새 hotspot 지도와 새 TIA 리포트가 대시보드에 실린다.
7. 본체 화면(홈, 과제, run, 커버리지, Sonar, 방식 비교, 온톨로지, 호스팅 비교)이 같은 디자인으로 보인다.
8. S3 + CloudFront에 올린 정적 HTML만으로 동작한다.

### 비목표

- 비공개 저장소를 목록에 넣는 것, 사이트 접근 제한(사용자 결정: 비공개는 뺀다).
- 과제를 원으로 그리는 지도 보기(시안 C). 표 보기만 만든다.
- 파이프라인 단계(S00~S13)의 측정 로직을 바꾸는 것. 도구 버전을 올리는 데 필요한 변경은 예외다.
- 이미 게시된 run 디렉터리를 새 디자인으로 다시 만드는 것(§3 제약 3). 옛 run은 옛 모습으로 남고, run 페이지 → SUT 안내 페이지 → 과제 페이지로 이어진다.
- 리포트 안의 개별 항목끼리 잇는 깊은 링크(예: hotspot의 메서드 → 커버리지의 그 파일). 지금 커버리지 리포트에는 파일 단위 주소가 없어 새 기능이 필요하다. 뒤로 미룬다.
- 서버 쪽 실행(API, 로그인, 검색 서버). 전부 정적 파일이다.

### 반목표 (동작해도 실패로 본다)

- 측정하지 않은 값을 지어내거나 0으로 채운다. 없는 값은 "측정 없음" 또는 "—"로 쓴다.
- 확인하지 않은 사실을 결론 문장이 단정한다.
- 외부 요청이 생긴다(CDN, 웹폰트, 분석 스크립트).
- 스크립트가 꺼지면 과제 목록, 수치, 과제 페이지의 탭 내용이 보이지 않는다.
- 비공개 저장소의 이름이나 설명이 사이트에 실리거나, 비공개로 바뀐 뒤에도 남는다.
- 상태가 왜 그렇게 판정됐는지 화면에서 알 수 없다.

## 3. 제약

1. **정적 호스팅.** S3 + CloudFront에 파일을 올리는 것이 전부다. 브라우저가 실행 중에 부르는 것은 같은 사이트의 정적 파일뿐이다.
2. **인덱스는 다시 만들고, run은 바꾸지 않는다.** 인덱스 수준 파일은 `Cache-Control: no-cache`로 매번 덮어쓰고, `suts/<sut>/runs/<runId>/` 아래는 `immutable`이다. 게시기는 이미 완료된 run을 다른 내용으로 다시 올리면 `ContentConflict`로 거부한다.
3. **run 페이지가 사이트 루트의 공용 스타일을 참조한다.** 게시된 run 페이지는 `static/site.css`와 `static/site.js`를 상대 경로로 불러온다. 이 파일을 새 디자인으로 덮어쓰면 옛 run 페이지가 깨진다. 같은 이유로, 이번에 만드는 파일도 다음 재설계 때 덮어쓰면 이번 run 페이지가 깨진다. 그래서 공용 자산은 버전 디렉터리에 두고 한 번 게시한 버전은 바꾸지 않는다(§6.7).
4. **게시기의 미러 규칙.** `sync_mirror`는 S3에 없는 미러 파일을 지우고, `upload_files`는 `rebuild`가 돌려준 목록만 올린다. 미러에 미리 써 둔 파일은 지워지고, 목록에 없는 파일은 올라가지 않는다. 수집 결과를 싣는 순서를 이 규칙에 맞춰야 한다(§6.4).
5. **재생성은 멱등이다(PoC REQ-045).** 인덱스 재생성은 실행 시각 같은 비결정 값을 쓰지 않는다. 그래서 날짜는 절대 날짜만 표시한다("3시간 전" 같은 상대 시각은 구현하지 않았다).
6. **게시 전 가리기 게이트.** 새로 만드는 모든 파일은 기존 공통 가리기(`td.redact`)와 업로드 게이트를 지난다.
7. **SonarQube API는 토큰이 필요하다.** 익명 요청은 401이다(2026-11-22 확인).
8. **hotspot-analysis는 PR #53 이후 릴리스 태그가 없다.** 지금의 "릴리스 jar + sha256" 고정 방식으로는 새 리포트를 받을 수 없다.

## 4. 방식 검토

| | A. 서버 렌더 + JSON 블록 + 순수 JS | B. 단일 페이지 앱(React 등) | C. 기성 대시보드 도구 |
|---|---|---|---|
| 방법 | 지금처럼 Jinja로 HTML을 만들고, 같은 데이터를 페이지 안 JSON 블록으로 싣는다. 거르기·정렬·펼치기·차트 툴팁은 작은 스크립트가 덧입힌다. | JSON만 게시하고 브라우저가 받아서 화면 전체를 그린다. | Evidence, Observable Framework 같은 도구로 사이트를 만든다. |
| 좋은 점 | 빌드 단계가 늘지 않는다. 스크립트 없이도 내용이 보인다. 기존 수용 테스트(Playwright)와 멱등 규칙을 그대로 쓴다. 참고한 두 리포트와 같은 구조다. | 화면 전환이 부드럽고 상호작용을 만들기 쉽다. | 차트와 표를 빨리 얻는다. |
| 나쁜 점 | 상호작용을 직접 짜야 한다. | Node 빌드 도구와 의존성이 들어온다. 스크립트가 꺼지면 빈 화면이다(반목표). | Node 빌드가 필요하고, 두 리포트와 모양을 맞추기 어렵다. 상태 판정 같은 로직을 도구 방식에 끼워 맞춰야 한다. |

**A를 고른다(작성자 판단, 사용자가 방식은 맡김).** 정적 호스팅 제약과 반목표를 그대로 만족하고, 지금 코드(`td.site`)와 테스트 위에 쌓을 수 있다.

## 5. 화면

### 5.1 첫 화면 (`index.html`)

위에서 아래로:

1. **결론 문장.** "과제 20개 중 5개가 위험, 6개가 주의입니다." 위험·주의가 없으면 "문제 있는 과제가 없습니다."
2. **요약 수치 4칸.** 전체 CI 성공률, Sonar 게이트 통과 과제 수, 커버리지가 0보다 큰 과제 수, 판정할 수 없는 과제 수. 어떤 칸을 둘지는 설정이다.
3. **거르기 도구.** 상태별 버튼(전체, 위험, 주의, 양호, 측정 없음. 각 버튼에 개수), 이름으로 거르기.
4. **과제 표.** 한 줄이 과제 하나다. 기본 정렬은 위험 → 주의 → 측정 없음 → 양호이고, 같은 상태 안에서는 이름순이다. 열 제목을 누르면 그 열로 정렬한다.
   - 기본 열: 상태, 과제(이름, 언어, 설명 한 줄), 왜 이 상태인가, CI 성공률, Sonar 게이트, 커버리지, 버그·취약점, 최근 CI 이력(실행마다 막대 하나), 최근 변경일.
   - 파이프라인을 돌린 과제는 이름 옆에 "파이프라인" 표시가 붙는다.
   - 두 출처(CI, Sonar) 가운데 하나만 읽힌 과제는 "부분 측정" 표시가 붙는다.
   - 값이 없는 칸의 글자: Sonar 프로젝트가 없으면 Sonar 게이트 칸은 "연결 없음", 수집이 실패해 값이 없으면 "측정 없음"(사유를 칸의 설명으로), 그 밖에 값이 없는 칸은 "—".
5. **행 펼침.** 과제를 누르면 그 행 바로 아래에 상세가 펼쳐진다(사용자 결정: 옆 패널이 아니라 목록 사이에). 판정 사유, 지표, "과제 페이지 열기" 버튼이 들어간다. 다시 누르면 닫힌다. 한 번에 하나만 열린다. 스크립트가 꺼져 있으면 펼침 없이 과제 이름이 과제 페이지 링크다.
6. **각주.** 지금 적용된 상태 판정 규칙을 수준마다 한 줄로 보여 준다. 규칙 하나는 조건을 `<지표 표시 이름> <기호> <값>`으로 적고(`all`은 " 그리고 "로 잇는다), 같은 수준의 규칙은 " / "로 잇는다. 예: "주의: CI 실행 수 ≥ 5 그리고 CI 성공률 < 90.0% / Sonar 취약점 > 0". Sonar 커버리지가 0인 과제가 하나라도 있으면 "0.0%는 커버리지 리포트를 Sonar에 보내지 않는다는 뜻일 수도 있습니다"를 덧붙인다. 그 아래에 "테스트 실행 기록"(`_test/index.html`)과 "호스팅 방식 비교"(`hosting.html`) 링크를 둔다.

### 5.2 과제 페이지 (`projects/<name>/index.html`)

위쪽은 고정이다: 경로(과제 › 이름), 상태 표시, 최근 실행 정보, 결론 문장, 탭.

탭마다 질문 하나에 답하고, 탭마다 "이 탭 읽는 법"이 한 줄 있다. 기본 탭과 순서(사용자 확인):

| 순서 | 탭 | 질문 | 내용 |
|---|---|---|---|
| 1 | 한눈에 | 지금 어떤 상태인가 | KPI 칸 5개와 작은 추세선, 먼저 손볼 곳 상위 5개, 이번 변경의 영향, 파이프라인 단계 띠, 리포트 바로가기 |
| 2 | 추이 | 지표가 어떻게 변해 왔나 | 시계열 차트(§5.3) |
| 3 | 테스트 | 무엇이 돌았고 얼마나 통과했나 | 기존 테스트 요약, 생성 묶음별 통과·실패 막대, Cucumber 리포트 링크 |
| 4 | 커버리지 | 코드의 얼마를 지키는가 | 묶음별 귀속·집계 막대, 테스트별 상세 링크 |
| 5 | 위험 지점 | 어디부터 손봐야 하나 | 상위 10개 메서드, hotspot 리포트(지도) 열기 |
| 6 | 코드 품질 | 정적 분석은 무엇을 말하나 | 게이트, 등급, 이슈의 종류 × 심각도 표 |
| 7 | 생성 실험 | AI가 만든 테스트는 쓸 만한가 | 판정, 방식별 평균과 기준 |
| 8 | 실행 이력 | 언제 무엇이 돌았나 | run 목록과 단계별 수행 여부 |

시안에는 "추이" 탭이 없었다. 사용자가 run별 시계열을 요청해 2번에 넣었다(작성자 판단). 탭 안의 세부 배치는 시안 `project.html`을 따른다.

**파이프라인을 돌리지 않은 과제**는 데이터가 있는 탭만 나온다: 한눈에(CI 성공률, Sonar 게이트, Sonar 커버리지, 취약점, 버그의 KPI 칸과 최근 CI 이력), 추이, 코드 품질(게이트와 측정값. 이슈 표는 없음).

**탭의 동작**: HTML에는 모든 탭 내용이 순서대로 놓인 구역으로 들어 있다. 스크립트가 켜지면 선택된 구역만 남기고 나머지를 숨긴다. 스크립트가 꺼져 있으면 전부 이어서 보인다. 탭은 WAI-ARIA 탭 규약을 따른다: `role="tablist"`, `role="tab"`, `role="tabpanel"`, `aria-controls`, `aria-selected`, 선택된 탭만 Tab 키 순서에 들어가고 좌우 방향키로 옮긴다. 선택한 탭은 주소의 `#` 부분에 남는다.

**결론 문장**은 §6.2의 순서로 정한다.

### 5.3 시계열 ("추이" 탭)

- 지표 하나에 작은 차트 하나를 두고 여러 개를 격자로 놓는다. 단위가 다른 지표를 한 축에 겹치지 않는다.
- 가로축의 점이 무엇인지는 과제 종류에 따라 다르다.

| 과제 | 한 점 | 그리는 지표 | 점을 누르면 |
|---|---|---|---|
| 파이프라인을 돌린 과제 | 완료된 run 하나 | run에서 나오는 지표 | 그 run 페이지 |
| 그 밖의 과제 | 날짜별 수집 스냅숏 하나(UTC 날짜) | 수집에서 나오는 지표 | 링크 없음 |

  한 차트에 두 종류의 점을 섞지 않는다.
- 차트에는 최근 30개 점까지 그린다. 차트 아래 표와 `series.json`에는 전부 둔다.
- 점에 마우스를 올리거나 초점을 주면 run 식별자(또는 날짜), 시각, 값이 나온다. 한 차트에서 점을 가리키면 다른 차트의 같은 run도 강조된다.
- 값이 없는 점은 선을 끊는다. 0으로 잇지 않는다.
- 세로축은 지표의 단위로 정한다. 비율은 0~100% 고정이다. 개수·초·점수는 0부터 최댓값까지이고 눈금은 0, 중간, 최댓값 셋이다. 비율이 아닌 지표에서 모든 값이 같으면 그 값이 가운데에 오게 한다(축은 0부터 값의 두 배까지). 소수 자릿수는 단위마다 고정한다(멱등).
- 차트 아래에 같은 값을 표로도 둔다.
- 서버가 선과 점을 SVG로 그린다. 스크립트는 툴팁과 강조만 덧입힌다.

### 5.4 run 페이지와 리포트

- run 페이지(`suts/<sut>/runs/<runId>/index.html`)는 단계 띠(칸 너비가 걸린 시간, 누르면 단계 설명), 리포트 카드, 게시 결과로 다시 만든다.
- 직접 만드는 리포트(커버리지, Sonar, 방식 비교, 온톨로지, 호스팅 비교)는 새 디자인의 공통 틀을 쓴다. 내용과 기존 기능은 유지한다.

### 5.5 리포트 간 링크 (공통 띠)

run 아래의 모든 페이지 맨 위에 **공통 띠**가 있다: `test-dashboard › <sut> › run › 지금 리포트` 경로와, 같은 run의 다른 리포트로 가는 메뉴.

- **링크 대상은 바뀌지 않는 주소만 쓴다.** run 페이지는 게시 뒤 바꿀 수 없으므로, 띠의 과제 링크는 `suts/<sut>/index.html`(안내 페이지)을 가리킨다. 그 페이지가 지금의 과제 페이지로 보낸다. 그래서 run을 렌더할 때는 `dashboard.yaml`이 필요 없고, 과제 이름을 나중에 바꿔도 옛 run의 링크가 죽지 않는다.
- 직접 만드는 페이지는 공통 틀 템플릿이 띠를 그린다.
- 외부 도구가 만든 HTML은 사이트로 복사한 뒤 띠를 끼워 넣는다.
  - 대상: hotspot의 `hotspots.html`과 `api_report.html`, TIA의 `tia.html`, 각 생성 묶음의 `cucumber/<genId>/index.html`.
  - 위치: 대소문자를 가리지 않고 처음 나오는 `<body ...>` 여는 태그 바로 뒤.
  - 형태: 스크립트 없음. `tdnav-` 접두 클래스와 인라인 `<style>` 하나. 높이가 고정이고 `position: static`이라 원래 화면을 가리지 않고 아래로 밀기만 한다.
  - 순서: 띠를 끼운 뒤에 가리기 게이트(`sanitize_site`)를 지난다.
  - `<body>`를 찾지 못하면 그 파일은 띠 없이 게시하고, run 페이지의 리포트 카드에 "공통 띠 없음"과 사유를 적고, S13을 `degraded`로 끝낸다.
  - 원본 파일은 run 작업 디렉터리에 그대로 남는다.
- 띠의 링크는 모두 상대 경로다. 접두(`_test/...`) 아래에 게시해도 동작한다.
- 화면 폭이 640px 이하이면 띠의 리포트 메뉴를 숨기고 경로만 보인다(경로의 run 링크로 run 페이지의 리포트 목록에 갈 수 있다).
- 과제 페이지의 각 탭은 해당 리포트로 가는 링크를 갖는다(위험 지점 → hotspot 리포트, 커버리지 → 커버리지 상세 등).

## 6. 구조

### 6.1 데이터 흐름

```
dashboard.yaml ──┐
                 ├─> 게시(S13 또는 인덱스 전용 게시)의 인덱스 단계:
pipeline run ────┤     sync_mirror → td.collect(미러에 기록) → td.site.index.rebuild → 업로드 → 무효화
(suts/.../runs)  ┘
```

`rebuild`는 미러에 있는 파일과 설정만 읽는다. 네트워크를 쓰는 것은 `td.collect`뿐이다.

### 6.2 설정 파일 `dashboard.yaml` (저장소 루트)

JSON Schema(`site-gen/td/schemas/dashboard.schema.json`)와 추가 검증으로 확인한다. 틀리면 `rebuild`와 `collect`가 어디가 왜 틀렸는지 내고 실패한다(기본값으로 넘어가지 않는다).

어느 설정을 쓸지는 호출하는 쪽이 넘긴다: `rebuild(site_root, prefix, config)`, 환경 변수 `TD_DASHBOARD_CONFIG`. 운영 게시는 저장소 루트의 파일을 쓴다. `TD_SITE_PREFIX`가 있는 실행(수용 테스트)은 넘겨받은 설정만 쓰고, 넘겨받지 않았으면 과제가 없는 빈 설정으로 본다.

```yaml
schema: 1
projects:
  - name: spring-petclinic
    repo: baekchangjoon/spring-petclinic
    sut: petclinic                  # 파이프라인을 돌리는 과제만
  - name: hotspot-analysis
    repo: baekchangjoon/hotspot-analysis
    sonarKey: hotspot-analysis      # 생략하면 저장소 이름
  # ... 처음에는 공개 저장소 20개(아래 표)

status:
  order: [crit, warn, none, good]
  labels: {crit: 위험, warn: 주의, good: 양호, none: 측정 없음}
  none: {allMissing: [ci.runs, sonar.gate, tests.passRate]}
  rules:
    - {level: crit, when: {metric: sonar.gate, op: eq, value: ERROR}, reason: "Sonar 품질 게이트 실패"}
    - {level: crit, when: {metric: ci.lastFailed, op: eq, value: true}, reason: "기본 브랜치의 최근 CI 실패"}
    - {level: crit, when: {metric: ci.failedChecks, op: gt, value: 0}, reason: "최신 커밋의 검사 실패: {ci.failedCheckNames}"}
    - {level: warn, when: {all: [{metric: ci.runs, op: ge, value: 5}, {metric: ci.successRate, op: lt, value: 0.9}]}, reason: "최근 CI {ci.runs}회 중 {ci.failures}회 실패"}
    - {level: warn, when: {metric: sonar.vulnerabilities, op: gt, value: 0}, reason: "Sonar 취약점 {sonar.vulnerabilities}건"}

home:
  summary: [ci.successRateAll, sonar.gatePassCount, sonar.coverageNonZeroCount, status.noneCount]
  columns: [status, project, why, ci.successRate, sonar.gate, sonar.coverage, sonar.issues, ci.history, repo.pushedAt]

project:
  tabs: [overview, trend, tests, coverage, hotspot, quality, generation, runs]
  trend:
    run: [tests.passRate, coverage.line, coverage.aggregateLine, e2e.passRate, sonar.coverage,
          sonar.vulnerabilities, sonar.bugs, hotspot.topScore, tia.selectedRatio, run.durationSec]
    snapshot: [ci.successRate, sonar.coverage, sonar.vulnerabilities, sonar.bugs]
  headline:                         # 상태가 "양호"일 때만 본다. 위에서부터 처음 걸린 문장
    - {when: {all: [{metric: tests.passRate, op: eq, value: 1}, {metric: coverage.line, op: lt, value: 0.5}]},
       text: "기존 테스트는 모두 통과하지만, 테스트가 지키는 코드는 {coverage.line}입니다"}
    - {text: "판정 규칙에 걸린 항목이 없습니다"}
```

**과제 등록 검증**

- `name`은 `^[A-Za-z0-9][A-Za-z0-9._-]*$`이고 `..`를 포함하지 않는다. 대소문자를 무시하고 유일하다. `repo`도 유일하다.
- `sut`는 `suts/<sut>/sut.yaml`이 있어야 하고, SUT 하나는 과제 하나에만 이어진다.
- 과제를 자동으로 긁지 않는다. 설정에 직접 적는다.

**설정에 없는 SUT**: 완료된 run이 있는데 어느 과제에도 이어지지 않은 SUT는 **암묵 과제**로 표에 넣는다. 이름은 SUT 이름이고, "파이프라인" 표시가 붙고, `repo`가 없어 수집하지 않는다(run 값만 쓴다). 과제 페이지도 만들고, 탭은 다른 파이프라인 과제와 같다. 상태 규칙과 결론 문장 규칙은 과제마다 따로 두지 않으므로 암묵 과제에도 같은 설정이 적용된다. 수용 테스트의 mini-sut과 접두 게시가 이 경로를 탄다. 설정의 과제 이름과 겹치면 검증 실패다.

**상태 판정 순서**

1. `none.allMissing`에 적힌 지표가 모두 없으면 "측정 없음"이다. 규칙을 평가하지 않는다. 기본값에 `tests.passRate`가 들어 있어, 저장소 정보 없이 파이프라인만 돌린 과제(암묵 과제)는 run 지표가 있으면 측정 없음이 아니다.
2. 그렇지 않으면 `rules`를 모두 평가한다. 규칙이 참조하는 값이 없으면 그 규칙은 걸리지 않는다(없는 값을 0으로 보지 않는다).
3. 걸린 규칙이 있으면 수준은 그 가운데 `order`에서 가장 앞선 것이고, 사유는 걸린 규칙 전부를 ` · `로 잇는다.
4. 걸린 규칙이 없으면 "양호"다.
5. "부분 측정"은 `repo`가 있는 과제에서 `ci.runs`와 `sonar.gate` 가운데 하나만 있을 때 붙는다. `repo`가 없는 암묵 과제에는 붙지 않는다.

**조건 문법**: `{metric, op, value}` 하나이거나 `{all: [조건, ...]}`(모두 참)이다. 연산자는 `eq, ne, lt, le, gt, ge`뿐이다. 설정에서 코드를 실행하지 않는다.

**문구 치환**: `{이름}`에는 과제 지표만 쓸 수 있다. 비율은 `41.5%`처럼, 목록은 `, `로 이어 쓴다. 치환할 값이 없으면 그 규칙(또는 그 결론 문장)은 걸리지 않은 것으로 본다.

**결론 문장을 정하는 순서** (과제 페이지)

1. 상태가 위험 또는 주의이면 판정 사유로 만든다: "위험: Sonar 품질 게이트 실패 · Sonar 취약점 2건".
2. 상태가 측정 없음이면 "측정된 지표가 없습니다".
3. 상태가 양호이면 `project.headline`에서 처음 걸린 문장을 쓴다.

**탭과 열**: 목록에 쓴 순서대로 나온다. 목록에서 빼면 화면에서 빠진다. 탭과 열의 종류 자체를 새로 만드는 것은 코드 변경이다.

**지표 카탈로그** (설정에서 쓸 수 있는 이름. 여기 없는 이름은 검증 실패다)

과제 지표, run에서 오는 것:

| 이름 | 단위 | 어디서 | 계산 |
|---|---|---|---|
| `tests.passRate` | 비율 | `run.json` `kpis.tests.passRate` | 그대로 |
| `coverage.line` | 비율 | `run.json` `kpis.blackbox.line` | 그대로 |
| `coverage.aggregateLine` | 비율 | `run.json` `kpis.blackbox.aggregate.line` | 그대로 |
| `e2e.passRate` | 비율 | `stages/S07.json` `generations.*.statusCounts` | 모든 묶음의 통과 수 합 ÷ 시나리오 수 합. 분모가 0이면 없음 |
| `sonar.gate` | 문자열 | `run.json` `kpis.sonar.gate` | `OK`, `ERROR` 등 그대로 |
| `sonar.coverage` | 퍼센트 값 | `run.json` `kpis.sonar.coverage` | 문자열을 수로 |
| `sonar.vulnerabilities`, `sonar.bugs`, `sonar.codeSmells` | 개수 | `run.json` `kpis.sonar`의 `vulnerabilities`, `bugs`, `codeSmells` | 문자열을 정수로 |
| `hotspot.topScore` | 점수 | `stages/S09.json` `top10[0].score` | 그대로 |
| `hotspot.topName` | 문자열 | `stages/S09.json` `top10[0].name` | 그대로 |
| `tia.selectedRatio` | 비율 | `stages/S10.json` `impact` | `selected ÷ indexedTests`. 분모가 0이면 없음 |
| `run.durationSec` | 초 | 단계 JSON의 시각 | S00~S12 가운데 가장 늦은 `finishedAt` − `run.json` `startedAt` |

단계 JSON의 `status`가 `passed`나 `degraded`가 아니거나 파일·필드가 없으면 그 지표는 없음이다(실패한 단계에 남은 값은 읽지 않는다). 예외: `run.durationSec`는 단계 상태와 무관하게 `finishedAt` 시각만 읽는다. 실패한 단계도 끝난 시각은 사실이고, 그 시각을 빼면 소요 시간이 실제보다 짧게 나온다.

과제 지표, 수집 스냅숏에서 오는 것:

| 이름 | 단위 | 계산 |
|---|---|---|
| `ci.runs` | 개수 | 집계 대상 실행 수(§6.3). 0이면 없음 |
| `ci.successes`, `ci.failures` | 개수 | 성공 수, 실패 수 |
| `ci.successRate` | 비율 | `successes ÷ runs` |
| `ci.lastFailed` | 참·거짓 | 가장 최근 집계 대상 실행이 실패인지 |
| `ci.failedChecks` | 개수 | 최신 커밋에서 실패한 검사 수 |
| `ci.failedCheckNames` | 목록 | 그 이름들 |
| `sonar.gate`, `sonar.coverage`, `sonar.vulnerabilities`, `sonar.bugs`, `sonar.codeSmells` | 위와 같음 | Sonar API |
| `repo.pushedAt`, `repo.language`, `repo.description` | 문자열 | GitHub |

**같은 이름이 두 출처에 있을 때**: 과제가 SUT와 이어져 있고 완료된 run이 하나라도 있으면 `sonar.*`는 최신 run의 값을 쓰고, 수집기는 그 과제의 Sonar를 읽지 않는다. 그래서 한 과제의 `sonar.*`는 항상 한 출처에서만 온다. SUT와 이어졌지만 완료된 run이 아직 없는 과제는 수집기가 읽고, `sonarKey`를 적지 않았으면 `suts/<sut>/sut.yaml`의 `sonar.projectKey`를 쓴다. Sonar API의 `code_smells`는 스냅숏에 `codeSmells`로 적는다. `ci.*`와 `repo.*`는 항상 스냅숏에서 온다.

집계 지표(`home.summary`에만 쓴다):

| 이름 | 계산 |
|---|---|
| `ci.successRateAll` | 모든 과제의 `ci.successes` 합 ÷ `ci.runs` 합. 과제 평균이 아니다 |
| `sonar.gatePassCount` | `sonar.gate`가 `OK`인 과제 수 / `sonar.gate`가 있는 과제 수 |
| `sonar.coverageNonZeroCount` | `sonar.coverage`가 0보다 큰 과제 수 / 전체 과제 수 |
| `status.noneCount` | 상태가 측정 없음인 과제 수 |

열 식별자(`home.columns`): `status`, `project`, `why`, `ci.successRate`, `sonar.gate`, `sonar.coverage`, `sonar.issues`(버그 · 취약점), `ci.history`, `repo.pushedAt`.
탭 식별자(`project.tabs`): `overview`, `trend`, `tests`, `coverage`, `hotspot`, `quality`, `generation`, `runs`.

**처음 등록할 과제 20개** (2026-11-22에 확인한 공개 저장소. 사용자가 "모든 저장소를 대상으로"라고 했고 비공개는 뺀다)

| 과제 | CI 기록 | Sonar 프로젝트 |
|---|---|---|
| spring-petclinic (`sut: petclinic`) | 있음 | 파이프라인용 `spring-petclinic-td` |
| hotspot-analysis, test-impact-analysis, graph-rag-test-generator, kn-estimator, spring-chaos-harness, CEF-Browser, atlassian-browser-skills, ManualTestCoverageMeasurement, CEF-Browser-Playwright, baekchangjoon, mock-oauth2-server-poc, sonarqube-ai-agent, token-stats, homebrew-tap | 있음 | 키가 저장소 이름과 같음 |
| MailosaurDemo, VcsStatistics | 있음 | 키의 대소문자가 저장소 이름과 다르다(`MailoSaurDemo`, `vcsstatistics`). `sonarKey`를 적는다 |
| parallel-per-test-coverage | 없음 | 있음 |
| test-dashboard, humanize-sepia | 없음 | 없음 |


### 6.3 수집기 `td.collect`

게시의 인덱스 단계 안에서만 돈다(§6.4). 따로 돌려 미러에 써 두는 방식은 쓰지 않는다(제약 4).

**실행 경계**: 게시기(Python)가 인덱스 단계에서 `pipeline/collect.sh`를 자식 프로세스로 부른다. `collect.sh`가 토큰 함수를 불러 발급하고, 정리를 종료 trap에 걸고, `python -m td.collect`를 실행한다. 토큰 정리의 책임은 `collect.sh`에 있다. 게시기가 신호를 받으면 자식에게 넘기고 자식이 끝나기를 기다린다. `td.collect`는 쓴 파일의 목록과 상태(`ok`, `degraded`)와 사유를 JSON으로 표준 출력에 내고, 게시기가 그 목록을 `rebuild`의 목록과 합쳐 올린다.

**GitHub** (`gh api`)

- 저장소 정보: 공개 여부, 기본 브랜치, 언어, 설명, 최근 push.
- 기본 브랜치의 완료된 Actions 실행 최근 30개. 모든 워크플로와 모든 이벤트를 본다.
- 결론값을 이렇게 나눈다.

| 분류 | 결론값 | 처리 |
|---|---|---|
| 성공 | `success` | 집계 대상 |
| 실패 | `failure`, `timed_out`, `startup_failure` | 집계 대상 |
| 제외 | `cancelled`, `skipped`, `neutral`, `action_required`, `stale` | 세지 않는다 |

- 최신 커밋의 검사 결과는 Check Runs API(`repos/<repo>/commits/<기본 브랜치>/check-runs`)로 읽는다. 같은 이름의 검사가 여러 번 돌았으면 가장 늦게 시작한 것만 본다. 실패로 세는 결론값은 위 표의 "실패"와 같다(`failure`, `timed_out`, `startup_failure`). 진행 중인 검사는 세지 않는다.

**SonarQube**

- 지금 `td.sonar`가 쓰는 두 엔드포인트를 그대로 쓴다: `api/qualitygates/project_status`(게이트), `api/measures/component`(커버리지, 버그, 취약점, 코드 스멜, 줄 수, 등급).
- 프로젝트가 없으면(404) 그 과제의 Sonar 값은 없음이다. 실패가 아니다.
- **토큰** (사용자 결정: 수집할 때마다 임시 토큰을 발급한다). S11과 같은 방식으로 SSH를 통해 Sonar DB에 2시간짜리 토큰의 해시를 넣고, 끝나면 그 행만 지우고 0행을 확인한다.
  - `pipeline/lib/sonar-token.sh`는 지금 S11에 묶여 있다(종료 처리에서 `stages/S11.json`을 읽고 `td_stage_end S11`을 부른다). 단계에 묶이지 않게 고친다: 호출자가 토큰 이름과, 정리가 실패했을 때 부를 함수를 넘긴다. S11은 지금과 같은 동작을 하도록 그 위에 얹는다.
  - 수집기의 토큰 이름은 `td-collect-<UTC시각>-<난수>`다. `td-` 접두라 기존 사전 청소(만료된 `td-%` 삭제)의 대상이 된다.
  - 정리는 모든 종료 경로(정상, 예외, SIGINT, SIGTERM)에 등록한다. 정리 SSH가 실패하면 "토큰이 남았을 수 있고 2시간 뒤 만료된다"는 경고를 크게 내고 수집을 `degraded`로 끝낸다.
  - Sonar를 읽을 과제가 하나도 없으면 토큰을 발급하지 않는다.

**공개 여부**

- 쓰기 전에 모든 과제의 공개 여부를 먼저 확인한다.
- 공개가 아닌 과제(가시성이 `public`이 아니거나 저장소 조회가 404)는 스냅숏을 쓰지 않고 제외 목록에 넣으며, 수집을 `degraded`로 끝낸다. 다른 과제는 계속한다.
- 제외한 과제의 이름은 표준 오류에만 낸다. 게시되는 파일(게시 기록 포함)에 들어가는 사유는 "비공개 과제 N개 제외"처럼 개수만 적는다.
- 공개 여부를 확인하지 못한 과제(시간 초과, 예산 초과, 5xx)는 새 스냅숏을 쓰지 않는다. 앞서 공개로 확인된 스냅숏이 있으면 그것으로 계속 그리고 "수집 실패"와 마지막 수집 날짜를 표시한다. 없으면 그리지 않는다. 지우지는 않는다.
- 스냅숏에 `visibility`를 적는다. `rebuild`는 `visibility`가 `public`인 스냅숏이 있는 과제와 암묵 과제만 그린다.
- 설정에서 빠졌거나 비공개가 된 과제의 `projects/<name>/`는 게시의 인덱스 단계가 S3와 Lightsail에서 지운다(§6.4).

**시간 제한과 재시도**

- 요청 하나: 읽기 30초(남은 전체 예산이 더 짧으면 그 안에서). 연결 시간을 따로 제한하지 않는다. 실패하면 2번까지 다시 시도하고 간격은 2초, 4초다.
- GitHub의 403/429는 `Retry-After`가 있으면 그만큼 기다리되 전체 예산 안에서만 기다린다.
- 수집 전체 예산은 5분이다. 넘으면 남은 과제는 읽지 않고 없음으로 둔다. 수집은 `degraded`다.

**출력**

- `projects/<name>/snapshots/<YYYYMMDD>.json` (UTC 날짜. 하루에 하나, 같은 날 다시 돌리면 덮어씀)과 `projects/<name>/latest.json`. 임시 파일에 쓴 뒤 `os.replace`로 바꾼다.
- 스키마는 `schemas/project-snapshot.schema.json`. `collectedAt`(UTC, ISO-8601)은 스냅숏 안에만 쓴다.
- 한 출처를 읽지 못한 과제는 그 부분을 `null`로 두고 사유를 적는다. 앞선 날짜의 값을 대신 채우지 않는다. 화면에는 "측정 없음"과 사유가 나온다.
- 설명 같은 외부 텍스트는 `td.redact`를 지난다.
- 사이트 수준 파일 `projects/_collect.json`(`{schema, date, unverified}`)을 매 수집 쓰고 게시한다. `unverified`는 이번에 공개 여부를 확인하지 못한 과제 가운데 **앞서 공개로 수집된 적이 있는 과제의 이름만** 담는다. 재생성은 이 목록으로 그 과제에 "수집 실패"와 마지막 수집 날짜를 붙인다. 한 번도 공개로 확인되지 않은 과제는 비공개일 수 있어 이름을 쓰지 않는다(게시되는 파일에 비공개 과제 이름을 남기지 않는 규칙).

### 6.4 게시와 인덱스 재생성

**게시의 인덱스 단계** (S13과 인덱스 전용 게시가 같이 쓴다)

```
접두 S3 잠금 → 미러 잠금 → sync_mirror
 → td.collect (미러의 projects/ 아래에 기록)
 → rebuild (설정 + 미러)
 → 설정에 없거나 공개가 아닌 과제의 projects/<name>/ 삭제 (S3, 미러)
 → 업로드: rebuild가 쓴 파일 + 수집이 쓴 파일 (no-cache, 누출 게이트)
 → 무효화 → Lightsail rsync
```

- S13과 인덱스 전용 게시는 같은 접두 잠금과 같은 미러 잠금을 잡는다. 수집이 그 잠금 안에서 돌기 때문에 두 게시가 같은 스냅숏을 동시에 쓰지 않는다. 잠금이 잡혀 있으면 나중 게시는 기다리지 않고 지금처럼 잠금 안내와 함께 실패한다(PoC REQ-046과 같은 동작). 수집 예산만큼(최대 5분) 잠금이 길어지는 것은 게시를 한 사람이 손으로 돌리는 지금 운영에서 받아들인다. 과제는 차례로 읽는다.
- **인덱스 전용 게시** `pipeline/publish-index.sh`(게시기의 `index-only`)를 새로 둔다. 파이프라인 run 없이 수집과 인덱스만 갱신한다. 결과(상태, 사유, 호스트별 결과)는 `<접두>publish-log/index.json`에 쓰고, `failed`일 때만 종료 코드가 0이 아니다. 과제 20개 가운데 19개는 파이프라인을 돌리지 않으므로 이 경로가 있어야 첫 화면이 갱신된다. 새 렌더러를 배포한 뒤 옛 run을 S13으로 다시 게시하면 `ContentConflict`가 나므로(제약 2), 화면만 갱신할 때도 이 경로를 쓴다.
- **수집 결과가 게시 상태에 주는 영향**: 수집이 `degraded`이거나 실패해도(자식 프로세스가 비정상으로 끝나거나 결과 JSON을 읽을 수 없는 경우 포함) 인덱스는 있는 스냅숏으로 다시 만들어 게시한다. S13(또는 인덱스 전용 게시)의 상태는 `degraded`이고 사유에 수집 결과를 적는다.
- **무효화**: 과제 파일은 `/<접두>projects/*` 한 경로로 묶는다. 파일마다 경로를 하나씩 내지 않는다.
- **삭제 범위**: `projects/` 바로 아래에서, 설정의 과제도 암묵 과제도 아닌 이름의 디렉터리만 지운다. 다른 곳은 건드리지 않는다. S3에는 디렉터리가 없으므로 그 접두의 객체를 나열해 묶어서 지운다(지금 게시기에는 객체 하나를 지우는 함수만 있어 새로 만든다). Lightsail 쪽은 그 디렉터리만 지우는 명령을 따로 보낸다(지금 rsync에는 삭제 옵션이 없다).
- `TD_SITE_PREFIX`가 있는 실행에서는 넘겨받은 설정에 `repo`가 있는 과제가 있을 때만 수집한다. 수집 대상 주소(GitHub는 `gh` 실행 파일 경로, Sonar는 URL과 SSH)는 환경 변수로 바꿀 수 있고, 테스트는 가짜로 바꾼다.

**`rebuild`가 더 하는 일**

- `summarize_run`이 §6.2 카탈로그의 run 지표를 읽는다.
- 과제마다 `projects/<name>/series.json`을 쓴다. 점의 배열이고, run은 runId 순, 스냅숏은 날짜 순이다. 값이 없으면 `null`이다.

  ```json
  {"schema": 1, "kind": "run", "metrics": ["tests.passRate", "coverage.line"],
   "points": [{"id": "20261120-131022Z-b6f9393-manual-036c288d", "at": "2026-11-20T13:10:22Z",
               "href": "../../suts/petclinic/runs/20261120-131022Z-b6f9393-manual-036c288d/index.html",
               "values": {"tests.passRate": 1.0, "coverage.line": 0.4152}}]}
  ```
- 상태 판정과 결론 문장을 여기서 정한다. 결과(수준, 사유 목록, 판정에 쓴 값)를 `projects.json`에 쓴다. 브라우저는 판정하지 않고 보여 주기만 한다.
- 홈과 과제 페이지는 표와 수치를 HTML로 먼저 그린다. 같은 데이터를 `<script type="application/json">` 블록으로도 싣고, 스크립트가 거르기·정렬·펼치기·툴팁을 덧입힌다.
- `suts/<sut>/index.html`은 과제 페이지로 가는 안내 페이지다. 이어진 과제(설정의 과제 또는 암묵 과제)가 항상 있으므로 갈 곳이 있다. 링크와 `<meta http-equiv="refresh">`를 같이 둔다.
- 기존 `suts.json`과 `suts/<sut>/runs.json`의 필드는 지우지 않는다. 추가만 한다.
- `_test/index.html`(접두 목록)도 새 틀로 그린다.

### 6.5 새 리포트 반영

| 도구 | 지금 | 바꿀 것 |
|---|---|---|
| test-impact-analysis | 커밋 `634a4a3f…` | 커밋 `c4e6e9e2c18f52e3315cc90a6f98fa16506c9199`로 올린다. S10이 `tia impact --format json`의 출력을 `tia report --impact`로 넘긴다. 기존 `--scenarios`는 유지한다. |
| hotspot-analysis | 릴리스 jar `v0.1.6` + sha256 | 커밋 `a5baac6c59273838374fe8a3cebf39ccc876d5c4`를 고정하고 소스에서 빌드한다(`./gradlew bootJar`, JDK 21, 결과 `build/libs/hotspot-*.jar`). tia와 같은 방식이다. |

- 고정 방식은 커밋 하나로 통일한다. hotspot에 새 릴리스가 나오면 그 태그의 커밋으로 올리면 된다.
- `tools.pin.yaml`의 `hotspot`은 `repo`, `commit`(40자), `jdk`, `gradleTask`, `jarGlob`을 갖는다. `load_pin`의 40자 SHA 검증에 hotspot을 넣고, 릴리스 내려받기 목록(`ARTIFACT_TOOLS`)에서 뺀다.
- 소스 받기와 빌드는 `pipeline/S00-prepare.sh`가 한다(지금 tia를 빌드하는 자리). 빌드한 jar를 지금과 같은 `<도구 디렉터리>/hotspot.jar`로 복사하므로 S09는 바꾸지 않는다. `tools.lock`에는 tia와 같은 모양으로 커밋과 빌드된 jar의 sha256을 적는다.
- 과제 페이지 "위험 지점" 탭의 상위 10개는 지금처럼 `hotspots.yml`에서 만든 `top10`을 쓴다. HTML 안의 JSON 블록은 읽지 않는다(도구의 화면 쪽에 묶이지 않기 위해서다).
- 새 버전의 리포트가 실제로 실렸는지는 수용 테스트가 확인한다(§8).

### 6.6 사이트 경로

```
index.html                              첫 화면
projects.json                           과제 목록 + 상태 판정 결과
projects/<name>/index.html              과제 페이지
projects/<name>/series.json             시계열
projects/<name>/latest.json             최신 수집 스냅숏 (repo가 있는 과제만)
projects/<name>/snapshots/<날짜>.json    수집 스냅숏
projects/_collect.json                  마지막 수집의 미확인 과제(앞서 공개였던 이름만, §6.3)
suts/<sut>/index.html                   과제 페이지로 안내 (기존 주소 유지)
suts/<sut>/runs.json, suts.json         기존 그대로 (필드 추가만)
suts/<sut>/runs/<runId>/...             기존 그대로 (새 run부터 새 디자인)
static/v2/app.css, static/v2/app.js     새 공통 스타일·스크립트
static/site.css, static/site.js         옛 run 페이지용. 내용을 바꾸지 않는다
_test/index.html, _test/static/v2/...   접두 목록
hosting.html                            호스팅 비교 (새 틀)
```

`projects/`와 `suts/`를 나눈 까닭: 과제는 화면에 올리는 단위이고, SUT는 파이프라인이 돌리는 대상이다. 과제 가운데 일부만 SUT와 이어진다.

### 6.7 디자인 체계

- **색과 글꼴**: test-impact-analysis 리포트의 값을 기준으로 삼는다. 배경, 면, 글자 3단계, 선, 강조(파랑), 주의(호박), 위험(빨강), 양호(초록). 시스템 글꼴만 쓴다. 밝은·어두운 테마는 OS 설정을 따른다.
- **상태 표시**: 색만으로 구분하지 않는다. 위험은 채운 원, 주의는 네모, 측정 없음은 빈 원으로 모양도 다르게 하고 글자를 같이 쓴다.
- **자산 버전**: 새 화면은 `static/v2/`의 파일을 쓴다. 한 번 운영에 게시한 버전 디렉터리의 파일은 고치지 않는다. run 페이지의 모양을 바꾸는 변경은 `static/v3/`을 새로 만든다. 옛 run 페이지는 계속 `static/site.css`(v1에 해당)를 쓴다.
- **반응형**: 360px 폭에서 페이지 가로 스크롤이 없다. 넓은 표는 자기 스크롤 영역 안에 둔다.
- **접근성**: 모든 조작을 키보드로 할 수 있다. 펼치는 행은 `aria-expanded`, 정렬 열은 `aria-sort`, 탭은 §5.2의 규약을 쓴다. `prefers-reduced-motion`이면 움직임을 끈다.
- **차트**: 직접 그리는 SVG다(작성자 판단). 지금 코드(`line_chart`)는 0~100% 비율만 그리므로, 단위별 세로축(§5.3)을 더한다. 외부 차트 라이브러리는 넣지 않는다.

## 7. 저장소 변경

```
dashboard.yaml                                         새 파일
pipeline/collect.sh, pipeline/publish-index.sh         새 파일
pipeline/S00-prepare.sh                                hotspot 소스 빌드
pipeline/S10-tia.sh                                    tia report --impact
pipeline/S13-publish.sh                                인덱스 단계에 수집
pipeline/lib/sonar-token.sh                            단계에 묶이지 않게
site-gen/td/collect.py                                 새 파일
site-gen/td/dashboard_config.py                        새 파일 (설정, 카탈로그, 상태 판정, 결론 문장)
site-gen/td/prepare.py                                 hotspot 커밋 고정, tools.lock
site-gen/td/publish.py                                 index-only, 수집 호출, 과제 삭제, 무효화 묶기
site-gen/td/site/index.py, pages.py, layout.py         재생성 확장, 공통 띠
site-gen/td/coverage.py, sonar.py, compare.py,
            ontology_html.py, hosting.py               새 틀과 static/v2 경로
site-gen/td/site/templates/*.j2                        전부 새 틀로
site-gen/td/site/static/v2/app.css, app.js             새 파일 (site.css, site.js는 그대로 둠)
site-gen/td/schemas/dashboard.schema.json,
                    project-snapshot.schema.json       새 파일
tools.pin.yaml                                         tia 커밋, hotspot 커밋 고정
tests/acceptance/test_dashboard_*.py                   새 파일
tests/acceptance/fake_sonar.py, 가짜 gh, 가짜 ssh       넓힘
docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md   머리말 표의 절 개정
README.md                                              설정, 수집, 과제 등록, 인덱스 전용 게시
.gitignore                                             .superpowers/
```

## 8. 테스트와 수용 기준 (E2E 명세)

### 8.1 방법

바깥 고리는 기존 방식 그대로다. 수용 테스트가 실제 명령(게시기의 인덱스 단계, `td.site.index`)을 돌려 만든 사이트 디렉터리를 로컬 `http.server`로 띄우고 헤드리스 chromium(Playwright)으로 확인한다. 외부 서비스는 가짜로 세운다.

- SonarQube HTTP: 기존 `fake_sonar.py`를 넓힌다(프로젝트별 응답, 404, 지연).
- Sonar 토큰(SSH + psql): 기존 단위 테스트처럼 가짜 `ssh` 실행 파일이 INSERT·DELETE·SELECT를 기록한다. 남은 행은 그 기록으로 확인한다.
- GitHub API: `gh`를 대신하는 가짜 실행 파일이 고정 응답을 준다(403/429, 지연 포함).

요구사항명세(REQ-ID와 추적 매트릭스)는 이 문서 승인 뒤에 따로 만든다. 그 명세가 아래 항목을 원자 단위로 쪼개고, 머리말에 적은 PoC 요구사항을 어떻게 고치는지도 적는다. 완료 정의는 그 매트릭스의 대상 요구사항이 모두 통과하는 것이다.

### 8.2 수용 테스트로 확인할 것

**첫 화면**
- 설정에 과제 N개가 있으면 표에 N줄이 나오고, 기본 정렬이 위험 → 주의 → 측정 없음 → 양호다.
- 결론 문장의 개수가 표의 상태 개수와 같다.
- 상태 버튼을 누르면 그 상태의 행만 남는다. 이름으로 거르면 맞는 행만 남는다. 열 제목을 누르면 정렬이 바뀌고 `aria-sort`가 바뀐다.
- 행을 누르면 그 행 **바로 다음 형제**로 상세 행이 생기고 `aria-expanded`가 `true`가 된다. 다시 누르면 사라진다. 다른 행을 누르면 앞의 것이 닫힌다. Enter 키로도 된다.
- 스크립트를 끈 브라우저에서 과제 N줄과 수치가 보이고, 과제 이름이 과제 페이지 링크다.
- 값이 없는 칸은 "측정 없음" 또는 "—"이고 숫자 0이 아니다.
- 각주에 지금 설정의 규칙 문장이 나오고, "파이프라인" 표시와 "부분 측정" 표시가 맞는 과제에만 붙는다.
- 설정에 없는 SUT(mini-sut)가 암묵 과제로 한 줄 나온다.

**상태 판정과 설정**
- 고정 입력에 대해 기대한 수준과 사유가 나온다: 게이트 실패, 최근 CI 실패, 검사 실패, 성공률 미달, 취약점, 여러 규칙이 함께 걸림(사유가 모두 나옴).
- 경계: CI 실행 0회(없음으로 취급), 4회에 실패가 많음(성공률 규칙 미적용), 5회(적용). CI와 Sonar가 모두 없으면 측정 없음, 하나만 있고 걸린 규칙이 없으면 양호와 "부분 측정".
- `cancelled`·`skipped`만 있는 과제가 "최근 CI 실패"로 판정되지 않는다.
- 임계값을 바꾼 설정으로 다시 만들면 같은 입력의 판정이 바뀐다.
- `project.tabs`에서 탭을 빼거나 순서를 바꾸면 과제 페이지의 탭이 그대로 따른다. `home.columns`도 같다.
- 모르는 지표 이름, 모르는 연산자, 스키마 위반, 잘못된 과제 이름(`..`, `/`), 겹치는 이름, 없는 `sut`, 한 SUT를 두 과제가 가리킴: 재생성이 0이 아닌 종료 코드와 사유로 실패한다.

**결론 문장**
- 위험 과제의 결론 문장이 판정 사유로 만들어진다. 기본 문장이 아니다.
- 테스트가 실패한 run(통과율 1 미만)에서 "모두 통과" 문구가 나오지 않는다.
- 측정 없음 과제는 "측정된 지표가 없습니다"다.

**과제 페이지와 시계열**
- 탭을 누르면 내용이 바뀌고 주소의 `#` 부분이 바뀐다. 그 주소로 직접 열면 같은 탭이 열린다. 좌우 방향키로 탭이 옮겨 가고 `aria-selected`가 따라간다.
- 스크립트를 끈 브라우저에서 모든 탭 구역이 순서대로 보인다.
- 탭마다 "이 탭 읽는 법"이 하나 있다.
- run이 K개인 과제의 "추이" 탭에서 지표마다 점이 K개(값이 없는 run은 제외)이고, 값이 없는 run에서 선이 끊긴다. run이 31개 이상이면 차트에는 30개, 표에는 전부 있다.
- 점에 초점을 주면 run 식별자와 값이 보이고, 점의 링크가 그 run 페이지를 가리킨다.
- 스냅숏이 2일치인 파이프라인 없는 과제는 점이 2개이고 링크가 없다.
- 비율이 아닌 지표(취약점 수, 소요 시간)의 세로축 최댓값이 데이터의 최댓값이다.
- 차트 아래 표의 값이 `series.json`과 같다.
- 파이프라인을 돌리지 않은 과제의 페이지에는 한눈에, 추이, 코드 품질 탭만 나온다.
- `suts/<sut>/index.html`의 링크가 그 과제 페이지를 가리킨다.

**리포트 간 링크**
- 새로 만든 run의 리포트 HTML(직접 만든 것, `hotspots.html`, `api_report.html`, `tia.html`, 각 Cucumber `index.html`)에 공통 띠가 있고, 띠의 SUT·run·다른 리포트 링크가 모두 200으로 열린다. 접두(`_test/<id>/`) 아래에서도 같다.
- 띠를 끼운 외부 리포트가 원래 기능을 유지한다(hotspot 지도가 그려지고, TIA 페이지 전환이 된다).
- `<body>`가 없는 HTML을 주입하면 그 파일은 띠 없이 게시되고, run 페이지에 사유가 나오고, S13이 `degraded`다.

**새 리포트와 도구 고정**
- 게시된 `hotspots.html`에 `#hotspot-map-data` 블록이 있고 지도 요소가 그려진다.
- 게시된 `tia.html`에 `tab-guide` 블록이 4개 있고 변경 영향 페이지가 있다.
- S00이 hotspot을 고정한 커밋에서 빌드하고 `tools.lock`에 그 커밋과 jar의 sha256을 적는다. 커밋이 40자가 아니면 S00이 실패한다.

**수집기와 게시**
- 가짜 GitHub·Sonar에 대해 스냅숏이 스키마를 지키고 기대한 값이 들어간다(결론값 분류, 같은 이름 검사의 최신 것만, Sonar 404는 없음).
- 인덱스 전용 게시가 run 없이 스냅숏과 홈을 갱신한다. 수집이 쓴 파일이 업로드 목록에 있고, `sync_mirror` 뒤에도 남아 있다.
- 비공개 저장소가 설정에 있으면 그 과제의 파일이 생기지 않고, 홈에 나오지 않고, 게시가 `degraded`다.
- 공개였던 과제를 비공개로 바꾸거나 설정에서 뺀 뒤 게시하면 그 과제가 홈과 `projects.json`에서 빠지고 `projects/<name>/`가 원본에서 지워진다. 다른 과제와 `suts/`는 그대로다.
- 한 과제의 Sonar 읽기가 실패하면 그 과제의 Sonar 부분만 `null`이고 다른 과제는 정상이며 게시가 `degraded`다.
- 가짜 GitHub가 응답하지 않으면 수집이 예산 안에 끝나고 남은 과제는 없음이다.
- 토큰: 수집이 정상으로 끝난 뒤, 중간에 예외가 난 뒤, SIGTERM을 받은 뒤 모두 가짜 ssh 기록에서 `td-collect-` 행이 0개다. 정리 SSH가 실패하면 경고가 나오고 `degraded`다. S11의 기존 토큰 테스트가 계속 통과한다.
- 수집한 외부 텍스트가 가리기를 지난다(작업 경로나 인프라 식별자 모양의 문자열을 넣은 설명이 가려져 게시된다).

**공통**
- 생성된 모든 HTML·CSS·JS에 외부 URL을 부르는 요소가 없다(`<a href>`는 제외).
- 360px 폭에서 홈, 과제 페이지, run 페이지에 가로 페이지 스크롤이 없다.
- 어두운 테마에서 배경색이 밝은 테마와 다르다.
- 같은 입력으로 재생성을 두 번 하면 모든 파일이 바이트 단위로 같다.
- 재생성 뒤 `static/site.css`와 `static/site.js`의 내용이 바뀌지 않는다. 옛 run 페이지 픽스처가 그대로 열린다.
- `suts.json`과 `runs.json`에 기존 필드가 모두 남아 있다.
- 기존 수용 테스트(PoC 매트릭스)가 계속 통과한다. 화면이 바뀌어 고쳐야 하는 테스트는 요구사항명세에 어느 REQ가 어떻게 바뀌는지와 함께 적는다.

테스트가 프로세스를 띄우는 경우(`http.server`, 가짜 Sonar)는 PID를 잡아 모든 종료 경로에서 정리하고, 끝난 뒤 남은 프로세스가 없음을 확인한다.

### 8.3 운영 확인

1. 파이프라인을 한 번 돌려 새 run을 게시하고, 인덱스 전용 게시를 한 번 돌린다.
2. `https://reports.<domain>/`에서 첫 화면 → 과제 페이지 → run → 각 리포트 → 띠로 돌아오기를 브라우저로 따라가 본다. 옛 run 하나도 열어 모양이 그대로인지 본다.
3. 시안을 지운다: S3의 `_design/` 접두와 Lightsail 쪽의 같은 디렉터리.

## 9. 위험과 대응

| 위험 | 대응 |
|---|---|
| 외부 리포트에 띠를 끼우다 그 리포트의 스타일이나 동작이 깨진다 | 접두 붙인 클래스, 스크립트 없음, 고정 높이. 수용 테스트로 원래 기능 확인 |
| 도구 버전을 올리면 기존 단계가 깨진다(tia 인자, hotspot 출력) | S09·S10의 기존 수용 테스트를 새 버전으로 먼저 돌린다. hotspot 소스 빌드로 S00이 느려진다 |
| 새 렌더러 배포 뒤 옛 run의 S13 재시도가 `ContentConflict`로 실패한다 | 화면만 갱신할 때는 인덱스 전용 게시를 쓴다. README에 적는다 |
| 커버리지 0.0%를 "테스트 없음"으로 읽는다 | Sonar가 준 값을 그대로 보이고, 각주에 "0.0%는 커버리지 리포트를 Sonar에 보내지 않는다는 뜻일 수도 있다"고 적는다 |
| 한 과제에 Sonar 프로젝트가 둘이다(저장소 자체, 파이프라인용) | 파이프라인을 돌린 과제는 최신 run의 값이 기준이다(§6.2) |
| 게시 때마다 운영 Sonar DB에 토큰 행을 쓰고 지운다 | 사용자가 고른 방식이다. 자기 행만 지우고 0행을 확인하며, 실패해도 2시간 뒤 만료된다. Sonar를 읽을 과제가 없으면 발급하지 않는다 |
| GitHub API 호출 한도, 느린 응답 | 과제당 요청 3개. 시간 제한과 5분 예산(§6.3) |
| 설정이 복잡해져 틀리기 쉽다 | 스키마 검증과 카탈로그 대조. 틀리면 실패하고 어디가 왜 틀렸는지 낸다 |
| 무효화 경로 수가 과제 수만큼 늘어난다 | `projects/*` 한 경로로 묶는다 |

## 10. 결정된 사항 (사용자)

- 첫 화면은 결론 한 줄 + 과제 표(시안 A).
- 과제 상세는 옆 패널이 아니라 눌린 행 바로 아래에 펼친다.
- 과제 목록은 등록한 모든 과제이고, 파이프라인을 돌리지 않은 과제는 GitHub CI와 SonarQube 값으로 채운다.
- 과제 페이지의 탭 구성과 순서, 상태 판정 규칙은 시안대로 하되 설정 파일로 바꿀 수 있게 한다.
- 비공개 저장소는 뺀다.
- S3 + CloudFront의 정적 HTML로 본다. 리포트 HTML끼리 링크로 잇는다. 과제 페이지에서 run별 지표를 시계열로 본다.
- 본체 디자인과 새 리포트 반영을 한 작업으로 한다.
- 수집기는 수집할 때마다 Sonar 임시 토큰을 발급하고 지운다(2026-11-22). PoC 설계에서 "세션 한정"으로 승인했던 방식을 수집기에 상시로 쓴다.

## 11. 작성자 판단 (승인할 때 확인 요청)

1. 방식 A(서버 렌더 + JSON 블록 + 순수 JS). §4.
2. 과제 페이지에 "추이" 탭을 2번으로 추가.
3. 과제 페이지 주소를 `projects/<name>/`로 새로 두고, `suts/<sut>/index.html`은 안내 페이지로 남김.
4. 이미 게시된 run은 다시 만들지 않음. 공용 자산은 `static/v2/`처럼 버전 디렉터리에 두고 게시한 버전은 고치지 않음.
5. hotspot-analysis를 릴리스 jar 대신 커밋 고정 + 소스 빌드로 받음. hotspot 저장소에 새 릴리스를 내는 방법도 있으나 다른 저장소를 건드리는 일이라 고르지 않음.
6. 외부 도구 리포트에는 띠를 끼워 넣음(iframe으로 감싸지 않음). 띠의 과제 링크는 바뀌지 않는 `suts/<sut>/index.html`.
7. 시계열 차트는 외부 라이브러리 없이 직접 그리는 SVG. 차트에는 최근 30개 점.
8. 상태 판정과 결론 문장은 재생성 때 서버 쪽에서 정함. 위험·주의 과제의 결론 문장은 판정 사유로 만듦.
9. 수집은 게시의 인덱스 단계 안에서만 돌고, run 없이 인덱스만 갱신하는 게시 명령을 새로 둠.
10. 비공개 저장소를 만나면 그 과제만 빼고 게시를 `degraded`로 끝냄. 비공개가 됐거나 설정에서 빠진 과제의 파일은 게시 때 지움.
11. 설정에 없는 SUT는 암묵 과제로 표에 넣음.
12. 파이프라인을 돌린 과제의 Sonar 값은 최신 run의 것을 씀(수집기가 따로 읽지 않음).
13. CI 집계에서 `cancelled`·`skipped` 등은 세지 않음. 실행 0회는 "없음".
14. 리포트 안 항목 간 깊은 링크와 hotspot 지도의 "위험 80%" 요약은 이번 범위에서 뺌.

## 12. 빌더에게 남긴 사항

- 수집 스냅숏과 `series.json`, `projects.json`의 스키마 세부(§6.2 카탈로그와 §6.4의 필드를 지키는 범위에서).
- `app.js`의 내부 구조, 차트 좌표 계산.
- 템플릿을 어떤 순서로 옮길지.
- 가짜 `gh`·가짜 `ssh` 실행 파일의 형태.
- 탭 안 세부 배치는 시안을 따르되, 360px에서의 배치는 빌더가 정한다.
- 인덱스 전용 게시와 S13이 게시기 코드를 어떻게 나눠 쓸지.
