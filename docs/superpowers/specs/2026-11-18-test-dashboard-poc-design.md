# test-dashboard 실증(PoC) 설계

- 작성일: 2026-11-18 (v2: 3-벤더 리뷰와 빌더 점검 반영, v3: 요구사항명세 2-벤더 리뷰의 역전파. §13이 앞 절과 충돌하면 §13이 우선한다)
- 상태: 승인됨 (2026-11-18)
- 저장소: `baekchangjoon/test-dashboard` (공개, 로컬 `/Users/changjoonbaek/test-dashboard`)
- 첫 대상 SUT: `baekchangjoon/spring-petclinic` (`ref: main`. 각 run이 실제로 쓴 커밋은 `run.json`의 `commit`이 기준이다. 작성 시점 HEAD는 `b6f9393`)

인프라 식별자(AWS 계정 ID, 서버 IP, IAM 사용자, SSH 키 경로)는 이 문서와 레포에 쓰지 않는다. gitignore 대상인 `infra/local.env`에만 두고, 문서에는 `<ACCOUNT_ID>`, `<LIGHTSAIL_IP>` 같은 자리표시자를 쓴다(§6.13).

## 1. 의도와 배경

E2E 테스트를 만들고 그 결과와 품질 지표를 한 화면에서 보는 흐름이 실제로 동작하는지 실증한다. 검증할 가설은 두 가지다.

1. **생성 가설:** SUT 코드에서 추출한 온톨로지와 bbtg 분석 산출물만으로(설계 문서, SUT 소스 원문, 사람이 쓴 기존 테스트 원문 없이) 실행 가능한 BDD 스타일 E2E 테스트를 만들 수 있다. 온톨로지는 그 결과를 개선한다.
2. **종합 가설:** 테스트 결과, 전체 커버리지, TC별 커버리지, 핫스팟, TIA, SonarQube 지표를 SUT 단위로 모아 하나의 웹 대시보드에서 볼 수 있고, 같은 구조로 SUT를 추가할 수 있다.

온톨로지는 1차로 jQAssistant 코드 그래프, 2차로 OWL/RDF 도메인 온톨로지를 만든다. 생성 실험의 조건(arm)은 셋이다.

| arm | 생성 입력 |
|---|---|
| `base` | bbtg 산출물만 (대조군) |
| `jqa` | bbtg 산출물 + jQAssistant 온톨로지 |
| `owl` | bbtg 산출물 + OWL 온톨로지 |

## 2. 목표 / 비목표 / 반목표

### 목표
- G1. 아래 §5의 단계 전체(S00~S13)를 **사람이 로컬에서 수동 실행**해 끝까지 돌리고 결과를 웹에 게시한다.
- G2. 실행할 때마다 결과를 **run 단위로 누적**한다. run 메타데이터에는 PR·머지 트리거용 자리(`trigger`, `pr`)를 미리 둔다.
- G3. 정적 호스팅(S3+CloudFront, `reports.<domain>`)과 기존 Lightsail 서버(`dash.<domain>`)에 같은 번들을 배포하고, 장단점을 측정값으로 비교한다.
- G4. 세 arm으로 만든 E2E 테스트의 결과를 사전에 정한 기준(§6.12)으로 비교한다.
- G5. 대시보드는 SUT 여러 개를 전제로 한다. SUT 추가는 `suts/<name>/sut.yaml`과 하네스 설정을 추가하는 것으로 끝나야 하고, 파이프라인 코드에 SUT 이름을 하드코딩하지 않는다.

### 비목표
- PR 생성·머지 시 자동 실행(CI). 자리만 둔다.
- 접근 제어. SUT와 도구 코드는 공개 코드로 간주한다.
- 기존 블랙박스 IT의 재생성. 기존 IT는 S01의 실행 대상과 커버리지 기준선으로만 쓴다.
- 대시보드의 동적 기능(검색 API, 로그인, DB).

### 반목표 (기술적으로 동작해도 실패로 본다)
- A1. 생성 입력(S06, S05의 LLM 호출)에 설계 문서, SUT 소스 원문, 기존 테스트 원문이 들어가는 것. 경로 검사, 내용 검사, LLM 도구 차단의 세 겹으로 막는다(§6.6).
- A2. 실패하거나 컴파일되지 않는 시나리오를 지우거나 비활성화해 지표를 꾸미는 것. 생성된 모든 시나리오는 결과의 분모에 들어간다.
- A3. 테스트가 띄운 컨테이너, 네트워크, 볼륨, 프로세스, git worktree가 남는 것.
- A4. Sonar DB에 임시로 넣은 토큰이 남는 것.
- A5. 공유 인프라를 **되돌릴 수 없게** 망가뜨리는 것. 대상은 Sonar 데이터(DB 볼륨), Route53 기존 레코드다. 짧은 서비스 중단과 기존 CI의 일시적 깨짐은 사용자가 허용했다(2026-11-18).

## 3. 제약 (실측, 2026-11-18)

| 항목 | 내용 |
|---|---|
| SUT | Spring Boot 4.0.0, Java 17, Gradle 9.2.1과 Maven 병행. 기본 DB는 H2이고 hsqldb, mysql, postgres 프로필도 있다(PoC는 H2). 외부 HTTP 호출은 없다. `/api/**`는 JWT 인증이 필요하고 `/api/auth/login`으로 발급한다. `/actuator/health`는 인증 없이 열려 있다. |
| `@RestController` | Vet, Owner, Pet, Auth, Reservation(`/api/**`). 그 밖에 Thymeleaf `@Controller` 6~7개가 있다. |
| 기존 테스트 | `*BlackBoxIT` 7개 클래스(@Test 35개), 지원 클래스 2개(`ApiBlackBoxTestSupport`, `PerTestCoverageExtension`). Gradle `blackboxTest`(병렬 8). testId는 `SimpleName#method`. |
| pjacoco | `io.github.beltian.pjacoco:pjacoco-agent:2.0.0`. 제어 엔드포인트 기본 바인딩은 `127.0.0.1`(`address=` 옵션)이다. `destfile`은 출력 디렉터리이고, JVM 종료 시 `aggregate.exec`를 쓴다. testkit(`pjacoco-testkit`, `pjacoco-testkit-restassured`)이 있다. 내장 jacoco-core는 소스 기본값이 0.8.12다(S00에서 실제 값 확인). Gradle 빌드에는 JaCoCo 플러그인이 없다(0.8.14는 Maven pom에만 있음). |
| Cucumber | `cucumber-junit-platform-engine` 8.1.0 (pom 이름 "JUnit 6 - JUnit Platform Engine") |
| jQAssistant | CLI 2.9.1. Spring 플러그인은 별도 아티팩트라 버전을 고정한다. 로컬에 미설치. |
| bbtg | 비공개 레포(사용자 소유). 7개 분석 스킬은 모두 `skills/<name>/cli.py` 진입점이 있다. 대부분 파일·메서드 단위 인자를 받고(`--file`, `--method`, `--src-root`), 산출물을 SUT 루트의 `.bbtg/artifacts/`에 쓰며 서로 그 경로를 참조한다. Python 3.12와 tree-sitter가 필요하다. |
| hotspot-analysis | 실행에 JDK 21이 필요하다. 설정 키는 `analysis.*` 아래에 있고, 상대 경로는 실행 cwd 기준이다. |
| TIA | `convert --exec-dir --classes --out` → `index --report --repo --commit [--db]` → `impact --commit --db --diff-file --format json` → `report --testwise --scenarios --commit --out`. 한 인덱스 안에서는 testId 형식이 하나여야 한다(`ClassName#method`). `--db` 기본값은 git-common-dir 아래라 반드시 지정한다. |
| 로컬 도구 | JDK 17·21, Docker 29.8, Python 3.12, uv, Terraform(arm64), `claude` CLI. `aws` CLI는 실행되지 않으므로 boto3를 쓴다. |
| AWS 권한 | S3 전체, `cloudfront:*`, `acm:*`, `route53:*`. EC2 불가, Lightsail 조회만 가능. |
| Lightsail | 기존 SonarQube 서버(2vCPU/4GB, 남은 메모리 약 1.6GB). SSH 가능, 22번은 사용자 IP만 허용. Caddy(유일한 80/443 진입점, Caddyfile 단일 파일 bind mount), SonarQube, Postgres가 compose로 돈다. |
| SonarQube | 26.5 Community + branch plugin. 기존 프로젝트 `spring-petclinic`은 CI가 쓴다. API는 인증이 필요하다. |

## 4. 방식 검토

| 안 | 내용 | 판단 |
|---|---|---|
| **A (선택)** | `test-dashboard` 레포가 오케스트레이터. SUT는 설명 파일로 기술. 단계별 스크립트가 run 디렉터리에 표준 산출물을 쓰고, 정적 사이트 생성기가 누적 사이트를 만들어 두 호스트에 배포한다. | SUT와 도구가 분리되고 SUT 추가가 쉽다. 산출물이 정적이라 두 호스팅에 같은 번들을 올릴 수 있다. |
| B | 파이프라인과 E2E를 spring-petclinic 안에 넣는다. | SUT마다 복제해야 하고 종합 대시보드가 어렵다. 제외. |
| C | ReportPortal, Allure TestOps 같은 리포트 서버를 쓴다. | 권장 메모리 8GB 이상이라 4GB 서버에 Sonar와 같이 둘 수 없다. 커버리지·핫스팟·TIA 자리가 없다. 제외. |

세부 선택(작성자 판단):
- 오케스트레이션은 bash로 한다(단계 실행, `trap` 정리). 데이터 가공과 사이트 생성은 Python 3.12(uv, Jinja2)로 한다.
- 시각화는 단일 HTML과 vanilla JS로 한다. Cytoscape.js 3.30.x는 레포에 벤더링한다.
- 정적 호스팅 인프라는 Terraform(`infra/static/`, 로컬 state, gitignore)으로 만든다. ACM은 DNS 검증이므로 `_*.reports.<domain>` CNAME이 추가된다.
- E2E 테스트는 Cucumber-JVM으로 한다(§6.8). 대체 경로는 순수 JUnit이다.
- Gradle은 파이프라인의 모든 호출에 `--no-daemon`을 붙인다(누수 방지).

## 5. 단계와 의존성

| ID | 이름 | 필수 입력 | 선택 입력 | 입력이 없을 때 |
|---|---|---|---|---|
| S00 | prepare | sut.yaml | – | 실패 시 run 중단 |
| S01 | blackbox | S00 | – | 건너뜀 |
| S02 | bbtg | S00 | – | 건너뜀(이후 S06 전부 건너뜀) |
| S03 | jqa | S00 | – | 건너뜀 |
| S04 | onto-viz | S03 또는 S05 | – | 있는 것만 시각화 |
| S05 | owl-build | S03, S02 | – | 건너뜀(`owl` arm 건너뜀) |
| S06 | bdd-gen | S02 | S03, S05 | arm별 입력이 없으면 그 arm만 건너뜀 |
| S07 | e2e | S06의 generation | – | 그 generation 건너뜀 |
| S08 | coverage | S01 또는 S07 중 하나 이상 | 나머지 | 있는 스위트만으로 축소 실행 |
| S09 | hotspot | S00 | S08 XML | XML 없으면 커버리지 배수 1.0으로 축소 실행 |
| S10 | tia | S00 | S07 | 블랙박스 스위트만으로 축소 실행 |
| S11 | sonar | S00 | S08 XML | 서버나 토큰 실패 시 실패(사유 기록) |
| S12 | compare | S07, S08 | – | 건너뜀 |
| S13 | publish | run.json | 모든 리포트 | 항상 실행 |

- 상태값은 `passed | failed | degraded | skipped`이고, 모두 `reason`과 산출물 경로를 함께 기록한다. 기록 위치는 `work/runs/<runId>/stages/<ID>.json`이다.
- `run-all.sh`의 종료 코드는 S00이나 S13이 실패하면 1(우선), 그 밖의 단계가 실패하면 2(게시는 됨), 실패가 없으면 0이다(passed, degraded, skipped 허용).
- 각 단계는 `pipeline/<ID>-<name>.sh <sut> <runId>`로 따로 실행할 수 있다. `run-all.sh <sut> [--arms base,jqa,owl] [--reps 3] [--only S01,S08]`를 지원한다. 요청하지 않은 단계는 `skipped`(사유 `not-requested`)로 기록한다.
- runId는 `YYYYMMDD-HHMMSSZ-<sha7>-<trigger>-<8hex 난수>`(UTC)이고, `work/runs/<runId>`를 `O_EXCL`로 예약하며 충돌하면 다시 만든다. trigger는 이번에는 `manual`만 쓴다.

## 6. 단계별 설계

### 6.0 SUT 설명 파일 (`suts/<name>/sut.yaml`)

```yaml
name: petclinic
repo: https://github.com/baekchangjoon/spring-petclinic.git
ref: main
java: 17
build: { system: gradle, cmd: "./gradlew --no-daemon -q bootJar -x test" }
jar: build/libs/spring-petclinic-*-SNAPSHOT.jar
classes: build/classes/java/main
sources: src/main/java
packages: org.springframework.samples.petclinic.*
runtime: { profile: default, db: h2, ddl: src/main/resources/db/h2/schema.sql }
port: 8080
health: /actuator/health             # 확인됨: actuator 존재, permitAll
api: { include: "/api/**" }           # 엔드포인트 분모의 범위
auth: { type: bearer, login: "POST /api/auth/login", user_env: TD_SUT_USER, pass_env: TD_SUT_PASS, probe: "GET /api/vets", unauthenticated_status: 403 }  # 401/403은 S00에서 실측해 확정
coverage: { probes: [ { test: "VetApiBlackBoxIT#<method>", controller: VetRestController }, { test: "OwnerApiBlackBoxIT#<method>", controller: OwnerRestController } ] }
blackbox:
  cmd: "./gradlew --no-daemon blackboxTest"
  props: { petclinic.base-url: "{baseUrl}", pjacoco.control-url: "{controlUrl}" }  # -D로 전달
  junit_xml: build/test-results/blackboxTest
tia: { range: "HEAD~10..HEAD", first_parent: true }
sonar: { projectKey: spring-petclinic-td, cmd_build: "./gradlew --no-daemon build -x test", cmd_scan: "./gradlew --no-daemon sonar" }
```

- `{baseUrl}`, `{controlUrl}`은 단계가 동적으로 할당한 포트로 치환해 `-D<key>=<value>`로 넘긴다.
- 인증 정보는 환경 변수로만 받는다. petclinic 기본값은 `infra/local.env`에 둔다.

### 6.1 S00 prepare
- `work/suts/<name>/src`에 전체 히스토리로 clone하고 run의 `commit`을 고정한다.
- 도구를 `work/tools/`에 확보하고 `tools.lock`에 버전, 해시, 커밋을 기록한다.
  - pjacoco agent 2.0.0. 내장 jacoco-core 버전을 읽어 같은 버전의 jacococli를 받는다.
  - jQAssistant CLI 2.9.1과 Spring 플러그인(호환 버전 고정, `ontology/jqa/.jqassistant.yml`)
  - hotspot-analysis 릴리스 jar
  - TIA(고정 커밋 clone 후 `:tia-cli:installDist`)
  - bbtg(고정 커밋 clone, 전용 venv에 `requirements.txt` 설치)
- S00은 도구 버전과 jQA 플러그인 목록을 출력해 검증한다. bbtg는 비공개라서 공개 레포만으로는 재현할 수 없다. 이 한계는 README에 적는다.

### 6.2 SUT 실행 환경 (S01, S07, S10 공용)
- `env/docker-compose.sut.yml`: `eclipse-temurin:17-jre`에 SUT jar와 agent를 읽기 전용으로 마운트한다.
  - 기동 인자: `-javaagent:/agent.jar=destfile=/cov,address=0.0.0.0,port=6310,includes=<packages>`
  - 포트 게시: `127.0.0.1::8080`, `127.0.0.1::6310`. 호스트 포트를 동적으로 할당하고 루프백에만 묶는다(제어 엔드포인트가 무인증이기 때문).
  - `/cov`는 `work/runs/<runId>/<stage>/<suite>/exec`에 bind mount한다. 실행 전에 쓰기 가능 여부를 확인한다.
  - 서비스, 네트워크, 볼륨 모두 compose 파일 안에 `labels: [test-run=${TD_RUN_LABEL}]`를 둔다.
- 기동: `TD_RUN_LABEL=td-<runId> docker compose -p td-<runId>-<stage>-<suite> up -d`. 할당된 포트는 `docker compose port`로 읽는다. health 폴링은 최대 120초다.
- 종료:
  1. `docker compose stop -t 30`으로 정상 종료를 기다려 `aggregate.exec`가 기록되게 한다.
  2. `down -v --remove-orphans`를 실행한다.
  3. 이 정리는 `trap '…' EXIT INT TERM`으로 모든 종료 경로에서 실행한다.
- 누수 게이트: 단계 종료 후 `docker ps -a`, `docker network ls`, `docker volume ls`를 `--filter label=test-run=td-<runId>`로 조회해 모두 0개인지 확인한다. 남아 있으면 단계를 `failed`로 기록한다.
- 수량 게이트: 실행된 TC 수(JUnit XML 또는 Cucumber 결과)와 TC별 `.exec` 수가 같아야 한다. 다르면 `failed`로 기록한다(조용한 0개 실패 방지).
- 시간 고정: SUT는 `LocalDate.now()`를 쓰므로, 컨테이너 TZ(`Asia/Seoul`)와 run 시작 시각을 `run.json`에 기록한다.

### 6.3 S01 blackbox (기존 IT)
- SUT 소스에서 `blackbox.cmd`를 실행하고, 결과로 TC별 `.exec`/`.json`, `aggregate.exec`, JUnit XML을 얻는다.
- 기대 TC 수는 JUnit XML에서 얻는다(현재 35개).

### 6.4 S02 bbtg 산출물
- 열거 드라이버 `pipeline/lib/bbtg_driver.py`가 다음 순서로 실행한다.
  1. `inspect-stack --path <src>`, `scan-test-assets --path <src>`
  2. `@RestController` 파일을 정적으로 열거한다(bbtg `common_lib` 파서 사용). 컨트롤러마다 `dependency-map --file`, `find-external-calls --file`을 실행한다.
  3. `inspect-auth --src-root <src>`
  4. `derive-test-data`를 H2 `schema.sql`을 명시해 CLI 범위로만 실행한다(LLM 단계는 쓰지 않음).
  5. dependency-map 결과에서 컨트롤러가 호출하는 서비스 메서드를 뽑아 메서드마다 `plan-tests --file --method`를 실행한다.
- 스킬들은 SUT 루트의 `.bbtg/artifacts/`를 서로 참조하므로 기본 경로로 생성한다. 끝나면 `work/runs/<runId>/bbtg/`로 복사하고 `.bbtg/`를 지운다.
- 각 호출의 인자, 종료 코드, 산출물 목록을 `bbtg/manifest.json`에 기록한다. 개별 호출이 실패하면 기록하고 계속한다(단계는 `degraded`).
- 이 단계는 `claude -p`를 쓰지 않는다. 모두 CLI로 실행한다.

### 6.5 S03 jQAssistant 온톨로지와 S05 OWL 온톨로지

**S03 jQA**
- `jqassistant scan`(classes 디렉터리와 jar) 다음에 `analyze`(Spring 개념 적용)를 실행한다. 저장소는 `work/runs/<runId>/jqa/store`다.
- export: `jqassistant server`를 백그라운드로 띄운다. PID를 캡처하고 `trap`으로 그 PID만 종료한다. 고정 Cypher 묶음(`ontology/jqa/queries/*.cypher`)을 HTTP 트랜잭션 API로 실행해 JSON을 얻는다.
  - 대체 경로: server 모드가 안 되면 같은 Neo4j 버전 컨테이너에 store를 마운트해 질의한다(라벨, 누수 게이트 적용).
- 추출 대상:
  - Endpoint: `@RestController`와 `api.include` 범위의 핸들러. 클래스 수준 경로와 메서드 수준 경로를 결합하고, 배열 값은 펼치고, path variable은 `{name}`으로 표기한다. HTTP `@Controller` 핸들러도 넣되 `props.view=true`로 표시하고 분모에서 뺀다.
  - Controller → Service → Repository 호출 경로
  - JPA 엔티티, 연관관계, 검증 애노테이션
  - 예외와 `@ExceptionHandler` → HTTP 상태
- Spring 개념이 Boot 4에서 비면 원시 애노테이션 노드(`:Annotation`, `:Value`) 쿼리로 대체하고 그 사실을 기록한다.
- 스키마: `{nodes:[{id,kind,label,props}], edges:[{source,target,kind}], meta:{tool,version,commit,fallbacks}}`. kind는 `Endpoint|Controller|Service|Repository|Entity|Field|Exception|DTO`이고, OWL 결과도 같은 스키마로 변환한다.

**S05 OWL**
- `ontology/owl/build.py`(rdflib, pySHACL)가 만든다.
  1. 결정적 변환: jQA JSON과 bbtg 산출물을 RDF 골격(클래스, 속성, 제약)으로 바꾼다.
  2. LLM 보강: 도메인 개념 이름 짓기, 관계 의미 부여, 제약을 OWL 제한과 SHACL로 표현한다. §6.6과 같은 격리 방식(도구 없음, 인라인 입력)으로 호출한다.
  3. pySHACL로 형식을 검증한다.
- 출력은 `ontology-owl.ttl`과 시각화용 `ontology-owl.json`이다.
- 한계: OWL은 jQA 그래프의 파생물이다. 따라서 `owl`과 `jqa`의 차이는 "LLM 재구성 한 번을 더한 효과"로 해석한다.

### 6.6 S06 BDD 생성
- **입력 번들**(arm별로 만든다)
  - 공통: `bbtg/**` 산출물을 정제한 것. 원문 필드(`inspect-auth`의 `interceptor_sources[].source` 등)는 제거하고, 제거한 필드 목록을 기록한다. `scan-test-assets`의 메타데이터는 포함하되, 기존 테스트 원문은 넣지 않는다.
  - 하네스 계약: `e2e/harness/CONTRACT.md`. step 정의가 쓸 수 있는 하네스 API(인증된 요청, 비인증 요청, base URL)를 설명한다. 도메인 지식은 넣지 않는다.
  - `jqa` arm에는 `ontology-jqa.json`, `owl` arm에는 `ontology-owl.ttl`을 더한다.
- **A1 강제(세 겹)**
  1. 경로 검사: 허용 목록 밖의 파일이 있으면 실패한다. SUT의 `src/**`, `docs/**`, `*.md`(하네스 계약 제외)는 금지다.
  2. 내용 검사: 번들의 어떤 블록도 SUT `src/main/**`이나 `src/test/**` 파일과 공백 정규화 후 5줄 이상 연속 일치하면 실패한다.
  3. LLM 격리: 번들만 담긴 임시 디렉터리를 cwd로 하고 `claude -p`를 **도구 없이** 호출한다. 번들은 프롬프트에 인라인으로 넣고, 출력은 파일 목록 JSON으로 받아 스크립트가 쓴다. 사용한 플래그를 기록한다.
- 출력: `e2e/generated/<sut>/<arm>/<genId>/`에 `features/*.feature`와 feature별 step 정의 Java 클래스를 둔다. genId는 입력 해시와 반복 번호로 만든다. 스냅샷은 커밋한다. `--regenerate`를 쓰면 새 genId로 추가하고 기존 것을 덮어쓰지 않는다.
- 기본 반복은 arm마다 3회(총 9개 generation)다. 비용 때문에 줄이면 run 메타데이터와 리포트에 명시한다.
- **수리 루프**: 최대 2회. 수리 입력은 컴파일러 출력과 Cucumber dry-run의 undefined step 목록**만**이다. 실행 결과(SUT 응답)는 넣지 않는다.
  - 2회 뒤에도 컴파일되지 않는 step 클래스는 빌드에서 빼고, 그 feature의 시나리오를 `uncompilable`로 결과에 넣는다(분모에 포함).
- 기록(`bdd-gen.json`): 입력 해시, 프롬프트 해시, 모델 id, 플래그, 수리 횟수, 토큰 사용량, 소요 시간
- 한계: 모델이 원본 spring-petclinic을 학습했을 수 있다(사전 지식 오염). 그래서 이 fork 고유 기능(boarding/Reservation)의 지표를 따로 집계한다(§6.12).

### 6.7 E2E 하네스 (`e2e/`)
- `e2e/harness/`: 사람이 쓰는 고정 코드다. 생성 대상이 아니다.
  - **인증**: `sut.yaml`의 `auth`에 따라 스위트 시작 시 로그인해 토큰을 받고, `Harness.authed()`가 Bearer 헤더를 붙인다. `Harness.anonymous()`는 헤더 없이 요청한다.
  - **커버리지**: pjacoco testkit(`pjacoco-testkit-restassured`)의 start/stop과 baggage 연동을 1순위로 쓴다. testkit API가 Cucumber 수명주기나 testId 형식과 맞지 않으면, 같은 프로토콜을 쓰는 어댑터 `PjacocoHooks`(약 40줄)를 직접 둔다. 어느 쪽을 썼는지 기록한다.
- testId: TIA 단일 형식을 지키려고 `ClassName#method` 모양으로 만든다. `E2E_<arm>_<genId>_<featureSlug>#L<시나리오 시작 라인>`. 결정적이고 병렬과 무관하다. 표시용 이름(feature 이름, 시나리오 이름)은 `testids.json`에 둔다.
- 사이트 경로와 파일명에는 testId의 sha1 앞 10자리 slug를 쓴다. `#`이 들어간 링크를 피하기 위해서다.

### 6.8 S07 Cucumber 실행
- `e2e/runner`는 독립 Gradle 프로젝트이고 Spring Boot BOM을 쓰지 않는다. `-Pgen=<generation 경로>`로 feature와 glue 경로를 정한다.
- 의존성: Cucumber 8.1.0(`cucumber-java`, `cucumber-junit-platform-engine`), JUnit Platform Suite, REST Assured 5.5.x, AssertJ
- generation마다 SUT 컨테이너를 새로 띄운다. 데이터 오염이 generation 사이에 번지지 않게 하기 위해서다.
- 실행은 순차(병렬도 1)가 기본이다. 시나리오 간 데이터 경합이 생성 품질과 섞이지 않게 하기 위해서다. 병렬 per-test 분리는 S01이 이미 보여준다.
- 먼저 dry-run을 실행해 undefined step 비율을 잰다. 분모는 그 generation의 전체 시나리오 수다.
- 출력: Cucumber Messages(ndjson), JSON, 내장 HTML, JUnit XML
- **대체 경로**: 세 arm 전부에서 dry-run의 undefined step 비율이 30%를 넘으면, 생성 스타일을 `--style junit`으로 바꿔 다시 생성할 수 있다. 이 경우 Given/When/Then을 `@DisplayName`으로 쓰고 기존 확장 방식을 쓴다. 어느 쪽을 썼는지 run 메타데이터에 남긴다.

### 6.9 S08 커버리지
- 정의:
  - **귀속 커버리지(attributed)**: TC별 `.exec`의 합집합. 대시보드의 기본 수치이고 TC 분석에 쓴다.
  - **집계 커버리지(aggregate)**: `aggregate.exec`. 기동 시 실행된 코드도 포함한다. Sonar와 hotspot에 넘기는 XML은 이것으로 만든다("테스트 실행 중 실행된 코드"가 의미상 맞음).
- 스위트 단위로 만든다. 스위트는 `blackbox`, 그리고 `e2e-<arm>-<genId>` 각각이다. 스위트마다 HTML, XML, CSV를 만든다.
- TC별 지표: 라인·브랜치·메서드 커버리지, 커버한 클래스, 고유 커버 라인 수(같은 스위트 안에서 이 TC만 커버하는 라인), 결과(`passed|failed|uncompilable|undefined`)
- 무결성 검사(§8 AT-06):
  1. 귀속 커버리지의 커버 라인 집합이 집계 커버리지에 포함되는지(위반 0건)
  2. jacococli가 모든 `.exec`에 대해 classId 불일치 경고를 0건 내는지
  3. 교차 오염 탐침: S01에서 서로 다른 컨트롤러만 호출하는 두 TC가 상대 컨트롤러 라인을 0개 커버하는지
- 크기 절감: TC별 소스 하이라이트는 TC마다 jacococli HTML을 만들지 않는다. 클래스별 커버 라인 목록 JSON을 만들고, 한 개의 소스 뷰어가 이를 렌더링한다. 소스 파일은 run마다 한 벌만 둔다.
- `coverage.html`: 스위트 요약 카드, TC × 클래스 히트맵, TC 표(정렬·필터), TC 상세(소스 뷰어)

### 6.10 S09 hotspot
- JDK 21로 실행한다. `suts/<name>/hotspot.yml.tmpl`을 run별 절대 경로로 렌더링해 `work/runs/<runId>/hotspot/hotspot.yml`을 만든다. 설정 키는 `analysis.apiAnalysis.enabled: true`, `analysis.apiAnalysis.classpathDirectories: [<classes>]`, `analysis.jacocoReportPath: <S08 aggregate 병합 XML>`이다.
- 도구가 만든 HTML을 그대로 게시하고, 상위 10개를 카드용으로 요약한다.

### 6.11 S10 TIA
- 사전 검사: `tia.range`의 base를 first-parent로 해석해 기록한다. base에 `blackbox` 태스크와 per-test 확장이 없으면 블랙박스 스위트는 건너뛴다(사유 기록).
- 절차(`--db work/runs/<runId>/tia/tia.db`):
  1. base 커밋을 `work/runs/<runId>/tia/base`에 git worktree로 만든다. `trap`에 `git worktree remove --force`를 넣는다.
  2. base 빌드 → SUT 기동(§6.2) → base의 블랙박스 IT 실행 → 각 arm의 rep1 generation 실행. base에 없는 API를 부르는 시나리오는 실패하지만 커버리지는 수집한다.
  3. `tia convert --exec-dir <base exec> --classes <base>/build/classes/java/main --out testwise.json`
  4. `tia index --report testwise.json --repo <sut> --commit <base> --db …`
  5. HEAD clone에서 `git diff <base>..<head> > base-head.diff`를 만들고 `tia impact --db … --commit <base> --diff-file base-head.diff --format json > scenarios.json`을 실행한다.
  6. `tia report --testwise testwise.json --scenarios scenarios.json --commit <base> --out tia.html`
- 이번 범위(HEAD~10)는 사실상 Reservation 기능 추가 전체라서 신규 파일이 많다. TIA는 이런 경우 보수적으로 전체 선택하는 것이 정상 동작이며, 리포트 해석에 이를 적는다.

### 6.12 S12 비교와 판정 기준 (사전 등록)
- generation마다 지표를 집계한 뒤, arm별 평균과 범위(최소~최대)를 낸다.
  - 시나리오 수, 컴파일 가능 비율, undefined step 비율, 통과율
  - `/api/**` 엔드포인트 커버 비율(분모는 S03이 추출한 Endpoint 중 `view=false`)
  - 귀속 라인·브랜치 커버리지, 그리고 `blackbox` 스위트 대비 증감과 blackbox가 커버하지 않던 고유 라인 수
  - **규칙 오라클 커버 비율**: `suts/<name>/oracle.yaml`에 비즈니스 규칙 분기(클래스, 라인, 규칙 설명)를 적고, 그 분기가 arm의 귀속 브랜치 커버리지에서 커버되는지로 판정한다. 오라클은 평가 전용이라 생성 입력에 들어가지 않는다. 작성자가 SUT 코드를 읽고 만든다. 예: 객실 정원 2, 숙박 1~30박, 객실 번호 100~499, 동물 수 1~4, 체크인은 오늘 이후, 48시간 내 취소 금지, 요율별 보증금.
  - fork 고유 기능 지표: 위 지표를 Reservation 범위로만 다시 집계한다.
  - 비용: 토큰과 소요 시간
- 판정(작성자 제안 기준. 사용자가 승인 시 조정할 수 있다):
  - 생성 가설 **성립**: 최소 한 온톨로지 arm의 평균이 다음을 모두 만족한다.
    - 컴파일 가능 ≥ 90%
    - undefined ≤ 10%
    - 통과율 ≥ 70%
    - 엔드포인트 커버 ≥ 80%
  - 온톨로지 **효과 있음**: 온톨로지 arm의 범위가 `base` arm의 범위와 겹치지 않으면서, 엔드포인트 커버, 귀속 브랜치 커버리지, 오라클 커버 중 하나 이상에서 더 높다. 범위가 겹치면 "차이 불명확"으로 판정한다.
  - 표본은 3회라서 모든 비교는 **탐색적 관찰**로 표기한다.
- `compare.html`: arm × 지표 표, generation별 점 그래프, 판정 결과와 한계 서술

### 6.13 S11 SonarQube
- **전용 프로젝트 키 `spring-petclinic-td`**를 쓴다. 없으면 API로 만들고, 분석은 그 프로젝트의 main 브랜치에 누적한다. 사용자는 기존 CI가 일부 깨지는 것을 허용했지만, 전용 키가 비용 없이 이력 혼선을 막으므로 유지한다.
- 토큰 수명 관리(`pipeline/lib/sonar-token.sh`, 이번 세션 한정 승인):
  1. 사전 확인: DB에서 `user_tokens` 스키마를 조회하고 해시 방식을 확인한다. aws-resource-controller 세션 기록으로는 SHA-384이고, 만든 토큰으로 `api/authentication/validate`를 호출해 실제로 검증한다. 맞지 않으면 S11은 `failed`다.
  2. 사전 청소: `name LIKE 'td-%'`인 잔존 행을 지우고 기록한다.
  3. 발급: 무작위 토큰의 해시를 `admin` 사용자로 INSERT한다. 이름은 `td-<runId>`, `expiration_date`는 지금부터 2시간 뒤로 한다(2차 방어선).
  4. 정리: `trap`으로 DELETE한 뒤 0행인지 확인한다. 정리용 SSH가 실패하면 run을 `failed`로 하고, 콘솔에 "토큰 잔존 가능, 2시간 후 만료"를 크게 출력한다.
  5. 토큰 값은 로그와 산출물에 남기지 않는다(환경 변수로만 전달).
- 스캔: `cmd_build`와 `cmd_scan`을 따로 호출한다(Gradle 9 implicit-dependency 문제 회피). 인자는 다음과 같다.
  - `-Dsonar.host.url`, `-Dsonar.token`(환경 변수 `SONAR_TOKEN`), `-Dsonar.projectKey=spring-petclinic-td`
  - `-Dsonar.coverage.jacoco.xmlReportPaths=<S08 aggregate 병합 XML>`
  - 품질 게이트는 기다리지 않는다(`qualitygate.wait` 미사용). `report-task.txt`의 ceTaskId로 `api/ce/task`를 폴링해 SUCCESS 후 export한다. 품질 게이트 ERROR는 단계 실패가 아니다.
- export: CE 태스크가 끝난 뒤 실행한다.
  - `api/qualitygates/project_status`
  - `api/measures/component`(coverage, bugs, vulnerabilities, code_smells, duplicated_lines_density, ncloc, sqale_rating, reliability_rating, security_rating)
  - `api/issues/search`, `api/hotspots/search`는 끝 페이지까지 순회하되 상한은 10,000건이다. `total`, `fetched`, `truncated`를 기록한다.
  - 결과를 `sonar.json`으로 저장하고 `sonar.html`로 렌더링한다. 각 항목은 Sonar 서버 페이지로 링크한다.

### 6.14 S13 게시와 누적
- run 디렉터리는 **불변**이다. `run.json`을 포함해 한 번 올린 run 파일은 다시 쓰지 않는다.
  - `run.json` 필드: `{runId, sut, commit, branch, trigger, pr, startedAt, finishedAt, tz, stages, kpis:{<suite>:{…}}, arms, tools, inputs}`
- **원본은 S3**다. Lightsail은 미러다.
- 게시 절차(`pipeline/S13-publish.sh`):
  1. 잠금: S3 `locks/publish`에 조건부 PUT(`If-None-Match: *`, 30분 TTL 메타데이터)을 한다. 실패하면 중단한다.
  2. 새 run 디렉터리를 S3에 업로드한다. 객체마다 `If-None-Match: *`로 올린다. 이미 있으면 실패다.
  3. 인덱스 재생성: S3의 `suts/*/runs/*/run.json` 목록에서 `runs.json`, `suts.json`, 각 index HTML을 다시 만든다(덧붙이기가 아니라 재생성이므로 멱등).
  4. 인덱스를 업로드한다. `Cache-Control`은 인덱스와 JSON이 `no-cache`, run 디렉터리가 `max-age=31536000, immutable`이다. CloudFront는 인덱스 경로만 무효화한다.
  5. 로컬 미러 `work/site-mirror/`를 S3와 동기화한 뒤 Lightsail로 `rsync -az`한다. run 디렉터리는 `--ignore-existing`으로 올린다.
  6. 호스트별 결과를 `suts/<sut>/publish-log.json`에 기록한다(인덱스 파일이므로 갱신 가능). Lightsail이 실패해도 다음 게시의 5단계가 전체를 다시 동기화해 따라잡는다.
  7. 잠금을 해제한다(`trap`).
- 사이트 구조:
  ```
  index.html, suts.json, hosting.html
  suts/<sut>/index.html, runs.json, publish-log.json
  suts/<sut>/runs/<runId>/index.html, run.json
  suts/<sut>/runs/<runId>/{ontology,coverage,hotspot,tia,sonar,cucumber/<genId>,compare}/…
  ```
- 크기: run 크기를 KPI로 기록하고, 200MB를 넘으면 경고한다. 보존 정책은 이번에는 전부 보존한다.
- **정적 호스팅**(`infra/static/`, Terraform): 비공개 S3 버킷(퍼블릭 차단, OAC), CloudFront, ACM(us-east-1) `reports.<domain>`, Route53 alias
- **Lightsail**(짧은 중단 허용, 사용자 승인 2026-11-18):
  - 기존 compose의 `caddy` 서비스에 `/srv/dashboard:/srv/dashboard:ro` 볼륨을 추가한다. Caddyfile에는 `dash.<domain> { root * /srv/dashboard; encode gzip; file_server }` 블록을 추가한다.
  - `caddy validate`를 통과하면 `docker compose up -d --no-deps --force-recreate caddy`로 Caddy만 재생성한다. 이때 Sonar 앞단이 몇 초 끊기며, 이는 허용됐다.
  - 적용 순서: Route53 A 레코드 → `/srv/dashboard` 생성과 소유권(ubuntu) → Caddyfile과 compose 백업 → 변경 → validate → Caddy 재생성 → `api/system/status`와 `dash` 응답 확인
  - 롤백: 백업을 복원하고 Caddy를 재생성한다. 필요하면 스택 전체를 다시 띄울 수 있다(사용자 승인).
  - 철거 절차를 `infra/lightsail/teardown.sh`로 둔다.
  - 같은 변경을 `~/aws-resource-controller/sonarqube/`에 반영하고 그 레포의 main에 커밋·push한다(사용자 승인).
- **Route53 안전장치**: 변경 전에 전체 RRSet을 정규화해 스냅샷한다. 변경 후 `reports`, `dash` 외에는 이름·타입·값·TTL이 같은지 비교한다. 대상 이름이 이미 다른 값으로 있으면 중단한다.
- **호스팅 비교**(`hosting.html`, `pipeline/lib/measure-hosting.sh`):
  - 배포 소요 시간, TTFB(로컬에서 10회 중앙값), 전체 페이지 전송 시간
  - 월 비용 추정, 운영 부담, 장애 영향 범위(Lightsail은 Sonar와 같은 장애 영역), 게시 전후 서버 메모리(`free -m`)

## 7. 저장소 구조

```
test-dashboard/
  suts/petclinic/{sut.yaml, hotspot.yml.tmpl, oracle.yaml}
  pipeline/{run-all.sh, S00-prepare.sh … S13-publish.sh, lib/}
  env/docker-compose.sut.yml
  ontology/{jqa/.jqassistant.yml, jqa/queries/*.cypher, owl/build.py, owl/shapes.ttl}
  prompts/{bdd-gen.md, bdd-repair.md, owl-gen.md}
  e2e/{harness/, runner/, generated/<sut>/<arm>/<genId>/}
  site-gen/                 # Python 패키지 (uv), Jinja2 템플릿, 벤더 JS
  infra/{static/, lightsail/, local.env.example}
  tests/{unit/, acceptance/}
  docs/superpowers/{specs, requirements, plans}
  work/                     # gitignore
```

## 8. 테스트와 수용 기준 (E2E 명세)

E2E는 `pipeline/run-all.sh petclinic`을 실제로 실행한 뒤 산출물과 배포 URL만 보는 수용 스위트 `tests/acceptance/`(pytest)다. 외부 장애 주입이 필요한 항목은 단계별 실행(`--only`)으로 검증한다. 최종 명세는 요구사항명세의 REQ-ID로 옮긴다.

| ID | 검증 내용 |
|---|---|
| AT-01 | `run.json`에 S00~S13 14개 단계의 상태가 모두 있고, `failed`, `degraded`, `skipped`에는 사유가 있다. 종료 코드가 §5 규칙과 맞는다. |
| AT-02 | `ontology-jqa.json`의 `view=false` Endpoint 집합이 SUT `/api/**` 핸들러의 정적 추출 결과와 같다. |
| AT-03 | `ontology.html`이 네트워크를 차단한 상태에서 열리고, 렌더링된 노드 수가 JSON과 같다(헤드리스 브라우저). |
| AT-04 | 생성 입력 번들에 금지 경로와 5줄 이상 소스 일치가 없다. 금지 파일이나 소스 블록을 일부러 넣으면 S06이 실패한다(부정 테스트). LLM 호출 플래그에 도구가 없다. |
| AT-05 | generation마다 생성된 시나리오 수 = 결과의 시나리오 수 = `coverage.html`의 TC 행 수다. 실행된 시나리오 수 = `.exec` 수다. `@ignore`나 `@Disabled`는 0개다. |
| AT-06 | §6.9의 무결성 검사 세 가지(포함 관계, classId 경고 0, 교차 오염 탐침)가 통과한다. |
| AT-07 | 성공한 단계의 리포트(hotspot, tia, sonar, compare)가 run 디렉터리에 있고 run 페이지에서 링크된다. TIA 리포트의 base 커밋이 사전 검사에서 해석한 base와 같다. |
| AT-08 | S11이 끝나면 `user_tokens`의 `td-%` 행이 0개다. 이전 run이 남긴 행이 있으면 사전 청소가 지운다. |
| AT-09 | run이 끝나면 라벨이 붙은 컨테이너, 네트워크, 볼륨이 0개다. 기록한 PID(jQA server 등)가 모두 종료됐다. TIA worktree도 남아 있지 않다. 중간 단계에 SIGINT를 보내도 같다. |
| AT-10 | `https://reports.<domain>/`과 `https://dash.<domain>/`이 200을 반환하고, 새 run 페이지와 그 안의 모든 내부 링크가 깨지지 않는다. CloudFront를 거쳐서도 최신 run이 보인다. |
| AT-11 | 두 번째 run을 게시해도 첫 run의 객체가 바이트 단위로 그대로이고(S3 ETag 비교), 이력 표에 두 run이 모두 있다. 같은 run을 다시 올리면 거부된다. |
| AT-12 | 두 번째 최소 SUT fixture(`tests/fixtures/mini-sut`, 작은 Spring Boot 앱)로 S00, S01, S08, S13을 실행하면 `index.html`에 SUT 2개가 나온다. 파이프라인 코드에 `petclinic` 문자열이 없다. |
| AT-13 | `compare.html`에 세 arm의 §6.12 지표와 판정 결과가 모두 있고, 반복 횟수가 표기된다. |
| AT-14 | 게시 후에도 Sonar 서버가 정상이고(`api/system/status` UP), 서버 메모리 여유가 300MB 이상이며, Route53의 대상 외 RRSet이 변경 전 스냅샷과 같다.  |
| AT-15 | S11에 장애를 주입하면(잘못된 Sonar URL) S11은 `failed`가 되지만 나머지는 게시되고, run 페이지에 실패 사유가 보인다. |
| AT-16 | S01의 TC 수(JUnit XML) = TC별 `.exec` 수(현재 35개)다. |

단위 테스트:
- site-gen(pytest): 집계, 인덱스 재생성 멱등성, slug와 링크 생성(`#` 포함 testId), 캐시 헤더
- 번들 검사기: 경로 검사와 내용 일치 검사
- testId 생성 규칙
- bbtg 정제기
- `PjacocoHooks`(쓸 경우): JUnit + 가짜 제어 서버

## 9. 위험과 대응

| 위험 | 대응 |
|---|---|
| pjacoco 내장 jacoco-core, jacococli, Sonar 임포터 사이의 비호환 | jacococli를 내장 버전에 맞추고, classId 경고를 AT-06으로 검출한다. |
| jQA가 Boot 4/Spring 7 애노테이션을 일부 못 읽음 | AT-02로 검출하고, 원시 애노테이션 쿼리로 대체한 사실을 기록한다. |
| jQA server 모드 export 실패 | 같은 버전 Neo4j 컨테이너로 대체한다(라벨, 누수 게이트 적용). |
| LLM 생성물의 비결정성과 step 불일치 | 3회 반복, 스냅샷, 수리 2회 제한(정적 오류만), JUnit 대체 스타일 |
| 모델의 petclinic 사전 지식 | fork 고유 기능 지표를 따로 집계하고, 한계를 명시한다. |
| 4GB Sonar 서버 부하 | 기존 Caddy가 정적 파일만 추가로 서비스한다. AT-14로 확인한다. |
| SSH 22번이 사용자 IP 변경으로 막힘(현재 IAM으로 방화벽 수정 불가) | Lightsail 게시와 S11이 `failed`로 기록되고, 사용자에게 방화벽 갱신을 요청한다. 다음 게시에서 따라잡는다. |
| DB 토큰 직접 삽입이 Sonar 내부 스키마에 의존 | 사전 스키마·해시 확인, 만료 2시간, 사전 청소, `trap` 삭제, 0행 검사, 이번 세션 한정 |
| bbtg가 비공개라 재현성이 제한됨 | `tools.lock`에 커밋을 고정하고 README에 한계를 적는다. |

## 10. 결정된 사항 (사용자)

- 1차는 jQAssistant만, 2차에 OWL/RDF를 추가해 비교한다(요구사항에 포함).
- 생성 입력은 온톨로지와 bbtg 산출물만 쓴다. 설계 문서와 **기존 IT 원문은 넣지 않는다**(IT는 scan-test-assets 메타데이터로만 반영).
- 온톨로지 없는 대조군 `base` arm을 추가한다.
- 기존 블랙박스 IT를 활용한다(S01 실행과 기준선).
- TIA는 실제 최근 커밋 범위를 쓴다.
- 호스팅은 정적(S3+CloudFront)과 Lightsail(기존 Sonar 서버)을 모두 만들어 비교한다. 서브도메인은 `reports`와 `dash`다.
- 짧은 서비스 중단과 기존 CI의 일시적 깨짐은 허용한다. 필요하면 Sonar 스택을 다시 띄워도 된다.
- Sonar 토큰은 이번 세션에 한해 DB 직접 삽입 방식을 쓴다.
- aws-resource-controller의 sonarqube 스택 변경은 그 레포 main에 커밋하고 push한다.
- 실행은 로컬 수동으로 하고 업로드까지 한다. CI 트리거는 자리만 둔다. 결과는 run 단위로 누적한다.
- 공개 레포는 `baekchangjoon/test-dashboard`다. 코드는 공개로 간주한다.
- Cucumber가 호환되지 않으면 JUnit/RestAssured로 대체할 수 있다. 호환은 확인됐고 대체 조건은 §6.8에 있다.

## 11. 작성자 판단 (승인 시 확인 요청)

- Sonar는 전용 프로젝트 키 `spring-petclinic-td`를 쓴다.
- 이력 원본은 S3이고 Lightsail은 미러다.
- E2E는 순차 실행이고, generation마다 SUT를 새로 띄운다.
- 생성 가설과 온톨로지 효과의 판정 기준(§6.12의 수치)
- 인프라 식별자는 gitignore 대상 `infra/local.env`에만 둔다.
- 커버리지 정의: 기본 표시는 귀속 커버리지, Sonar와 hotspot에는 집계 커버리지

## 12. 빌더에게 남긴 사항
- Cypher 쿼리 세부, 시각화 레이아웃과 차트 표현
- jQA Spring 플러그인의 호환 버전 선택(S00에서 검증)
- pjacoco testkit과 직접 어댑터 중 선택(§6.7 기준)
- OWL 클래스·속성 이름 세부와 SHACL 범위
- `oracle.yaml`의 규칙 목록 세부(§6.12의 예시는 최소 포함)
- 두 번째 SUT fixture의 구성

## 13. v3 보정: 운영 계약 (요구사항명세 v2 리뷰 역전파)

### 13.1 게시 원자성과 잠금 (§6.14 대체)
- 업로드 순서: ① run 파일을 `suts/<sut>/runs/<runId>/`에 객체별 `If-None-Match: *`로 올린다. 이미 있는 객체는 체크섬이 같으면 건너뛰고(재시도 허용), 다르면 실패한다. ② 모든 객체를 체크섬 manifest와 대조한다. ③ `_COMPLETE` 표식을 조건부로 만든다. ④ 인덱스를 재생성한다.
- 인덱스는 `_COMPLETE`가 있는 run만 읽는다. 표식 없이 남은 run은 같은 runId로 재시도하면 이어서 완료할 수 있다. 표식이 있는 runId를 다시 게시하면 실패한다.
- 잠금: `locks/publish` 객체에 `{attemptId, owner(host,pid), acquiredAt}`를 조건부 PUT한다. 자동 만료는 없다. 남은 잠금은 `--force-unlock <attemptId>`로만 지우고, 지우기 전에 attemptId 일치를 확인한다. 지금은 수동 실행이라 자동 회수는 범위 밖이다.
- 게시된 `run.json`의 S13 상태는 `publishing`이다. 최종 S13 결과는 로컬 `stages/S13.json`과 `publish-log.json`이 기준이다. S13은 `--only`에 없으면 실행하지 않는다.

### 13.2 수용 테스트 격리
- `TD_SITE_PREFIX`가 있으면 S3 `<prefix>`와 Lightsail `/srv/dashboard/<prefix>` 아래에만 게시한다. 운영 인덱스는 `_test/`를 무시한다. 주입 실행과 mini-sut은 `_test/<sessionId>/`에만 게시하고, 테스트가 끝나면 지운다.
- 장애 주입 훅: `TD_FAIL_STAGE=<ID>[:<point>]`(예: `S11:scan`, `S13:upload-mid`, `S13:lightsail`). 운영 경로에서는 쓰지 않는다.
- mini-sut: `tests/fixtures/mini-sut`. 테스트 시점에 `work/fixtures/`로 복사해 `git init` 후 `--sut-file`로 지정한다.

### 13.3 Sonar 토큰 (§6.13 보정)
- 사전 청소는 `name LIKE 'td-%' AND expiration_date < now()`인 **만료된** 행만 지운다. 다른 run의 활성 토큰은 건드리지 않는다.
- 종료 정리는 자기 토큰 `td-<runId>`만 지운다. 정리 SSH가 실패하면 S11은 `failed`이고, 토큰은 발급 2시간 뒤 서버에서 만료된다.

### 13.4 LLM 격리 (§6.5 S05, §6.6 공통)
- S05와 S06의 모든 `claude` 호출(수리 포함)은 같은 래퍼 `pipeline/lib/llm.sh`를 거친다. 래퍼는 다음을 지킨다.
  - 번들 임시 디렉터리를 cwd로 한다.
  - 모든 도구를 비활성화한다.
  - MCP 설정을 비운다.
  - 사용자·프로젝트 설정과 CLAUDE.md를 로드하지 않는다.
  - 프롬프트는 stdin으로 넘긴다.
- 정확한 플래그는 S00에서 `claude --help`로 확인해 `tools.lock`에 기록한다. 검증은 가짜 `claude` 캡처와 실제 카나리 호출(tool_use 0건)로 한다.
- 번들 내용 검사의 정규화는 요구사항명세 REQ-020의 절차를 따른다. bbtg 산출물은 스킬별 허용 JSON Schema(`additionalProperties: false`)로 정제한다.

### 13.5 식별·경로 규약
- genId: `<arm>-<inputHash8>-r<rep>`. `--regenerate`를 쓰면 `-g<n>`을 붙인다. 같은 입력 해시의 스냅샷이 있으면 기본으로 재사용한다(두 번째 run은 LLM을 부르지 않음).
- testId: `E2E_<arm>_<inputHash8>r<rep>[g<n>]_<featureSlug>#L<line>`
- 백그라운드 PID 기록: `work/runs/<runId>/pids/<name>.pid`
- 병합 집계 XML: `S08/merged/aggregate.xml`(blackbox와 모든 e2e 스위트). S09와 S11은 이 파일 하나를 쓴다.
- 엔드포인트 기대 목록: `suts/<sut>/expected-endpoints.yaml`(사람이 검토, 커밋 고정). AT-02의 독립 기준이다.
- 시간: `startedAt`, `finishedAt`은 UTC이고, `sutDate`는 SUT TZ 기준 날짜다. run 도중 날짜가 바뀌면 `clockShift=true`로 기록하고 비교 화면에 경고를 띄운다. SUT 시계를 주입하는 기능은 SUT 변경이 필요해서 범위 밖이다.

### 13.6 Route53 (§6.14 보정)
- 기준: 적용 직전 스냅샷의 RRSet은 모두 그대로여야 하고, 새 RRSet은 허용 목록(`reports`, `dash`, ACM 검증 `_*.reports.<domain>` CNAME)만 가능하다.

### 13.7 Lightsail 적용 (§6.14 보정)
- `caddy validate`는 실행 중인 컨테이너가 아니라, 새 Caddyfile을 마운트한 일회성 컨테이너로 실행한다(`docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile`).
- Caddy를 재생성한 뒤 `dash` HTTPS 응답은 최대 120초 재시도로 확인한다(인증서 최초 발급 대기).
- validate가 실패하면 변경 전 Caddyfile과 compose로 바이트 단위 복원한다.

### 13.8 호스팅 비교 데이터
- `hosting.json`(스키마 고정)에 정량값과 정성값을 나눠 담는다.
  - 정량: 배포 초, TTFB 중앙값 ms(표본 10, 실패 수, URL, warm), 홈 전송 ms, 메모리 MB
  - 정성: 비용 추정 근거(가격표 출처, 리전, 기준일, 가정, 식), 운영 부담, 장애 영향 범위
