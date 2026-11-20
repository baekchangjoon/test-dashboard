# test-dashboard 실증(PoC) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spring-petclinic을 첫 SUT로 하여 블랙박스 IT 실행, 온톨로지(jQA, OWL) 기반 BDD E2E 생성·실행, TC별 커버리지, hotspot, TIA, Sonar 리포트를 run 단위로 만들고, S3+CloudFront와 Lightsail에 누적 게시하는 파이프라인을 만든다.

**Architecture:** bash 단계 스크립트(`pipeline/S00..S13`)가 run 디렉터리(`work/runs/<runId>/`)에 표준 산출물을 쓴다. 데이터 가공, 검사기, 사이트 생성, 게시는 Python 패키지 `td`(`site-gen/`)가 맡는다. 생성된 E2E는 독립 Gradle 프로젝트(`e2e/`)에서 Cucumber로 실행한다.

**Tech Stack:** bash, Python 3.12(uv, Jinja2, boto3, rdflib, pySHACL, jsonschema, pytest, playwright), Java 17(Cucumber 8.1.0, REST Assured 5.5.x, AssertJ), Docker Compose, Terraform, jQAssistant CLI 2.9.1, pjacoco 2.0.0, hotspot-analysis(JDK 21), TIA CLI, bbtg(비공개, 고정 커밋), `claude` CLI 2.1.327.

**Spec:** `docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md`(v3.1, §13이 앞 절보다 우선), `docs/superpowers/requirements/2026-11-18-test-dashboard-poc-requirements.md`(v2.1). 실행자는 두 문서를 모두 읽는다.

## Global Constraints

- 기준 SUT 커밋: `b6f939355e8790202ddfc71e3f3507252745ed37`(spring-petclinic `main`). TIA base는 first-parent `HEAD~10` = `c37b2e4`.
- runId: `YYYYMMDD-HHMMSSZ-<sha7>-<trigger>-<8hex>`(UTC). 원자적 `mkdir`(`FileExistsError`)로 예약하고, 시도는 최대 5회다(초기 1회 포함).
- 단계 상태: `passed|failed|degraded|skipped`. `run.json.stages.S13`만 `publishing`을 쓴다.
- 종료 코드: S00이나 S13이 실패하면 1, 그 밖의 실패는 2, 실패가 없으면 0
- 모든 Gradle 호출에 `--no-daemon`을 붙인다. 컨테이너 기동은 `docker compose -p td-<runId>-<stage>-<suite>`, 라벨은 `test-run=td-<runId>`. 테스트가 직접 띄운 자원은 `td-test-<sessionId>`로 표식한다.
- pjacoco agent 인자: `destfile=/cov,address=0.0.0.0,port=6310,includes=<packages>`. 포트는 `127.0.0.1::<port>`로 게시한다.
- genId `<arm>-<inputHash8>-r<rep>[-g<n>]`, `reps` 1~9. testId `E2E_<arm>_<inputHash8>r<rep>[g<n>]_<featureSlug>#L<line>`
- LLM 호출은 `pipeline/lib/llm.sh` 하나로만 한다. 플래그는 `-p --tools "" --strict-mcp-config --mcp-config <빈 JSON> --setting-sources "" --system-prompt <고정> --output-format json --model <tools.lock 모델>`이다. `--bare`는 OAuth를 읽지 않으므로 쓰지 않는다. cwd는 번들 임시 디렉터리다.
- Sonar 프로젝트 키는 `spring-petclinic-td`(주입 실행은 `-test-<sessionId>`)다. 토큰은 환경 변수로만 넘긴다. 이름 `td-<runId>`, 만료 2시간. 사전 청소는 만료된 `td-%`만 한다.
- 도메인: `reports.<domain>`(CloudFront), `dash.<domain>`(Lightsail). 인프라 식별자는 `infra/local.env`(gitignore)에만 둔다. 키는 `TD_AWS_ACCOUNT_ID`, `TD_LIGHTSAIL_IP`, `TD_IAM_USER`, `TD_SSH_KEY_PATH`, `TD_DOMAIN`, `TD_SUT_USER`, `TD_SUT_PASS`다.
- 캐시: 인덱스 HTML과 JSON은 `no-cache`, run 디렉터리는 `max-age=31536000, immutable`
- `aws` CLI는 쓰지 않는다(x86 바이너리라 실행 불가). AWS 호출은 boto3로 한다.
- 커밋 author는 `-c user.name=baekchangjoon -c user.email=<사용자 이메일>`이고 trailer는 세션 규칙을 따른다.
- 수용 테스트 이름은 `test_req<NNN>_*`이고 `tests/acceptance/`에 둔다. 전제(AWS, SSH, Docker, claude)가 없으면 skip이 아니라 실패다.

## Review Focus

1. **SUT가 뜨지 않음**(포트 충돌, health 120초 초과): 단계가 멈추지 않고 `failed`가 된다. reason에 컨테이너 로그 마지막 50줄이 들어가고, 정리도 된다. → Task 4에 테스트 추가
2. **LLM 출력이 깨짐**(잘린 JSON, 파일 목록 스키마 위반): 해당 generation만 S06에서 `failed`(사유 포함)가 되고, 그 generation은 S07에서 실행하지 않는다. 다른 generation과 arm은 진행된다. 수리 호출 횟수에 넣지 않는다. → Task 22에 테스트 추가
3. **Sonar 서버나 SSH에 토큰 발급 전부터 닿지 않음**: 토큰을 넣지 않고 S11이 `failed`가 된다(잔존 행 0). → Task 13에 테스트 추가
4. **한국어 시나리오 이름과 feature 이름**: slug가 비지 않고 결정적이다(이름이 모두 비ASCII면 feature 파일명 기반 `f<sha1-8>`). → Task 19에 테스트 추가
5. **강제 종료(SIGKILL)로 게시가 끊겨 잠금이 남음**: 다음 게시가 잠금 정보와 `--force-unlock <attemptId>` 안내를 출력하고 비-0으로 종료한다. SIGINT는 trap이 잠금을 해제한다. → Task 10에 테스트 추가

## 개정 사항 v2 (계획 2-벤더 리뷰 반영. 각 Task 본문과 충돌하면 이 절이 우선한다)

### A. 공통
- **경로 규약**: run 산출물은 `work/runs/<runId>/<StageID>/…`이고, 계획의 경로가 기준이다. 요구사항명세와 설계의 다른 표기도 이 규약으로 고쳤다. 대응은 다음과 같다.
  - `tia/tia.db` → `S10/tia.db`
  - `bbtg/manifest.json` → `S02/bbtg/manifest.json`
  - `site-gen/schemas/` → `site-gen/td/schemas/`
  - `pipeline/lib/bbtg-allow/` → `site-gen/td/bbtg_allow/`
  - `pipeline/lib/bbtg_driver.py` → `td/bbtg.py`
  - `ontology/owl/build.py` → `td/ontology_owl.py`
  - `measure-hosting.sh` → `td/hosting.py`
  - `tests/unit/` → `tests/acceptance/test_unit_*.py`
- **사이트 배치**: Task 7의 `td.site.layout.SITE_LAYOUT: dict[stage_output_key, site_rel_path]`가 단계 산출물을 사이트 경로로 옮긴다(예: `S09/hotspot/` → `hotspot/`, `S07/<genId>/html/` → `cucumber/<genId>/`). 리포트를 추가하는 Task(12, 13, 14, 18, 21, 23)는 이 매핑과 run 템플릿 링크에 항목을 추가한다(Modify `site-gen/td/site/layout.py`, `templates/run.html.j2`).
- **도구 고정**: 커밋하는 `tools.pin.yaml`이 기준이다. S00은 이 값으로 받아 sha256을 검증하고, run별 `tools.lock`(불변 사본)을 쓴다. 고정 값은 다음과 같다.
  - bbtg `83ea6fd`, TIA `634a4a3`, hotspot-analysis `0.1.6`(릴리스 jar), pjacoco-agent `2.0.0`
  - jacococli는 agent에 내장된 버전(`io/pjacoco/shaded/jacoco/core/jacoco.properties` 또는 `META-INF/maven/org.jacoco/org.jacoco.core/pom.properties`에서 읽음)
  - jQA CLI `2.9.1`. Spring 플러그인은 Task 3에서 호환 버전을 정해 pin 파일에 커밋한다.
  - Cucumber `8.1.0`, REST Assured `5.5.1`
  - Python은 `site-gen/uv.lock`
- **LLM 모델**: `pipeline/config.yaml`의 `llm.model`(기본 `claude-opus-5-5`, `TD_LLM_MODEL`로 덮어쓰기). S00은 고정 플래그 전체로 무해한 프롬프트를 1회 실제 호출해 플래그가 받아들여지는지 검증한다.
- **시간 제한**: 모든 외부 명령은 `td_run <timeout_sec> -- <cmd…>`(`common.sh`)로 실행한다. 새 프로세스 그룹으로 띄우고, 시간이 넘으면 그룹 전체에 TERM을 보내고 10초 뒤 KILL한다. 사유는 `timeout:<cmd>`다. 기본 제한(초)은 다음과 같다.
  - clone·fetch 600, Gradle 1800, bbtg 900, jQA 900, LLM 900, Terraform 1800, S3 1800, SSH 120, rsync 1800
  - Task 2에 `test_td_run_timeout_kills_group`(sleep 자식 포함)을 둔다. Task 16·19·10에 각각 행 걸림 주입 테스트를 하나씩 둔다(가짜 bbtg, 가짜 claude, 가짜 rsync).
- **디스크 여유**: S13은 업로드·rsync 전에 로컬 미러 대상 크기와 여유 공간을 확인한다. 로컬과 서버 모두 2GB 이상 남아야 하고, 아니면 rsync 전에 `failed`다. run 크기를 `publish-log`에 기록한다.
- **비밀값 검사**(REQ-054 보강): `local.env`의 모든 키를 분류한다.
  - 식별자: ACCOUNT_ID, IP, IAM_USER, SSH_KEY_PATH
  - 비밀: SUT_PASS
  - 공개: DOMAIN
  - 비밀 값이 SUT 공개 소스에 이미 있으면(petclinic의 `password`) 검사에서 빼고 사유를 출력한다. 일치한 값은 출력하지 않는다.
- **E2E 테스트 작성 시점**: E2E 레벨 테스트도 소유 Task의 Step 1에서 작성한다. 기준 run 증거가 필요한 것은 `@pytest.mark.baseline`을 단다. `work/acceptance-session.json`이 없으면 이 테스트는 **실패**한다(red가 정상이며 Task 25에서 green). 각 Task의 "PASS 확인"은 그 Task의 Int, Unit, 주입 테스트에 대한 것이다.

### B. Task별
- **Task 1**:
  - conftest fixture를 추가한다.
    - `run_under_test`: session 범위. 세션 파일이 있으면 기준 run, 없으면 `m1_run`
    - `m1_run`: `--only S00,S01`, `TD_SITE_PREFIX`
    - `injected_petclinic_run`: `--only S00,S01,S08,S13`, `TD_SITE_PREFIX`
    - `stub_stages`: `TD_STAGE_DIR=tests/fixtures/stub-stages`. `TD_SITE_PREFIX`가 있을 때만 허용
  - Step 3에 `uv run --project site-gen playwright install chromium`을 넣는다.
- **Task 2**:
  - `run-all.sh`는 run 디렉터리를 예약하기 전에 `work/suts/<name>/src`를 clone하거나 fetch하고, `ref`를 `rev-parse`해 커밋을 얻는다. 실패하면 콘솔에 사유를 쓰고 종료 코드 1이다(run 디렉터리 없음). S00은 그 커밋으로 detach checkout하고 검증한다.
  - `sut.yaml`에 `expected_commit`이 있으면 다를 때 S00이 `failed`다. petclinic은 `b6f9393…`로 고정한다. HEAD를 따라가려면 그 키를 지운다.
  - 스텁 단계는 `tests/fixtures/stub-stages/`에 보존한다. 종료 코드와 건너뜀 전파 테스트는 스텁으로 고정한다.
  - `state.set_run_field(run_dir, dotted_path, value)`를 추가한다. 각 Task의 Produces에 자기가 쓰는 `run.json` 키를 적는다. 예: Task 6 `kpis.<suite>`, Task 22 `arms.generations`·`arms.style`·`inputs`, Task 3 `tools`.
  - S13 수명주기: S13 시작 직전 `finishedAt`을 쓰고 `stages.S13="publishing"`으로 `run.json`을 동결한다. 이후 `state.end("S13")`은 `stages/S13.json`만 쓴다. state 단위 테스트로 고정한다.
  - Clock은 테스트 전용 `TD_NOW`(ISO)로 주입한다. 경계 기대값(KST 기준)은 다음과 같다.
    - (23:59:59, 00:00:01) → `clockShift` true
    - (00:00:00, 00:30:00) → false
    - `sutDate`는 `startedAt`의 KST 날짜
- **Task 3**: SUT 비인증 상태 실측은 Task 4로 옮긴다(Task 4가 S00을 Modify). S00은 `build.cmd`를 실행하고 jar와 classes 경로를 `stages/S00.json.outputs`에 기록한다. `test_req058`은 위 재배치 경로에서 내장 jacoco 버전을 읽는다.
- **Task 4**: `env.sh` 완성 뒤 S00에 비인증 실측을 추가한다.
- **Task 6**: `pages.slug`, `base.html.j2`, `site.css`를 이 Task에서 먼저 만들고, Task 7이 확장한다.
- **Task 7**: run 페이지는 `../../publish-log/<runId>.json`을 클라이언트에서 fetch해 S13 결과를 표시한다.
- **Task 8**: `route53-before.json`은 없을 때만 쓴다. 다시 실행하면 `route53-before.<ts>.json`을 따로 저장하고 최초 파일은 보존한다.
- **Task 9**:
  - `dash`는 `check_conflict` 후 CREATE한다. 같은 값이면 그대로 두고, 다른 값이면 중단한다.
  - 변경 전 `dash` 레코드(없음 포함), Caddyfile, compose를 스냅샷한다.
  - 변경 이후 어느 단계에서 실패하든 다음을 한다: 파일 복원 → 이전 설정으로 Caddy 재생성 → Sonar status 확인 → `dash` 레코드를 이전 상태로 복원
  - 로컬 fixture 주입 `TD_LIGHTSAIL_FAIL_AFTER=recreate|health`로 두 경우를 테스트한다.
  - 마지막에 after 스냅샷을 갱신하고 compare를 다시 실행한다.
- **Task 10**:
  - 커밋을 세 개로 나눈다. 10a 업로드·manifest·`_COMPLETE`, 10b 잠금, 10c 미러·Lightsail·publish-log·무효화.
  - Consumes에 Task 9를 더한다.
  - Produces에 `publish.timings() -> {uploadSeconds, memBeforeMb, memAfterMb}`와 시그니처 `S13-publish.sh <sut> <runId> [--force-unlock <attemptId>]`를 더한다.
  - S13 `degraded` 조건에 "TTFB 성공 표본 7개 미만"을 더한다(Task 11이 `hosting.measure`를 제공하고 S13에 연결한다. Modify `publish.py`, `S13-publish.sh`).
- **Task 11**: 위와 같이 S13을 Modify한다.
- **Task 13**:
  - 커밋을 둘로 나눈다. 13a 토큰 수명주기, 13b 스캔·CE·export.
  - S11은 스캔 인자의 XML sha256을 `stages/S11.json.extra.coverageXmlSha256`에 기록한다. REQ-063 테스트에 S11 확인을 추가한다.
  - 토큰 발급 전 사전 점검을 둔다.
    - Sonar HTTP: 인증 없이 `api/system/status`
    - SSH: `TD_SSH_PORT_OVERRIDE`로 주입
  - 각 실패 → `failed`이고 INSERT 0건이다(DB 행 수로 확인). 테스트는 두 개로 나눈다.
- **Task 14**: M1에서 블랙박스 스위트만으로 끝나면 `degraded`(사유 `e2e suites not attached`)다. Task 22 이후에는 e2e가 붙어야 `passed`다.
- **Task 16**:
  - 먼저 스킬별 산출 형식 표(JSON/MD, stdout 여부)를 `site-gen/td/bbtg_allow/FORMATS.md`에 적는다.
  - raw의 기준은 stdout JSON(있는 스킬)과 JSON 아티팩트다.
  - `.md` 아티팩트는 Markdown 표와 제목만 JSON으로 추출한다(코드 블록은 버림). 그다음 허용 스키마로 정제한다.
  - `bbtg.run_all`의 cwd는 SUT 루트다.
- **Task 17**: `expected-endpoints.yaml`에 `handler: <FQCN>#<method>`를 넣는다. `ontology.schema.json`의 Endpoint `props`에 `handler`를 둔다. jQA server는 루프백과 동적 포트로 띄운다(설정 키는 Task 3에서 확인해 `.jqassistant.yml`에 둔다). REQ-010의 S03 SIGINT 케이스를 이 Task에 둔다.
- **Task 19**:
  - `e2e/harness/CONTRACT.md` 초안을 이 Task에서 만들고, Task 20이 확정한다. 스냅샷은 Task 22 전에는 없으므로 해시 변화는 무해하다.
  - `bundle.check_content`의 `oracle` 인자는 `Optional`로 두고 Task 23이 연결한다.
  - 헤더에 REQ-027을 넣는다.
  - REQ-075의 번들 해시 동일성 테스트(두 체크아웃 경로)를 이 Task에 둔다.
- **Task 20**: `e2e/gradlew`, `e2e/gradlew.bat`, `e2e/gradle/wrapper/*`를 추가한다(Gradle 9.2.1, distribution sha256 고정). 모든 e2e 호출은 `./gradlew --no-daemon`으로 한다. `scenario-results.json`은 엄격한 NDJSON(시나리오당 한 줄)이다. testkit과 어댑터 중 무엇을 썼는지는 `generation-meta.json`에 적는다.
- **Task 21**:
  - Produces를 다음으로 바꾼다. 모두 SUT 없이 동작한다.
    - `scenarios.compile_check(gen_dir, classpath, out_dir) -> CompileResult(excluded, compiler_output)`
    - `scenarios.dry_run(gen_dir, out_dir) -> DryRun(undefined_steps, json_path)`
    - `scenarios.validate_generation(gen_dir, out_dir)`
  - S06은 임시 검증 디렉터리에서 이 함수를 수리 루프에 쓴다.
  - 제외 판정은 S07이 run마다 다시 계산해 `S07/<genId>/compile-excluded.json`에 쓴다. 스냅샷 디렉터리는 수리 완료 뒤 불변이다.
- **Task 22**:
  - 스냅샷은 임시 디렉터리에 쓰고 검증한 뒤 `_COMPLETE`(전체 입력 해시와 파일 체크섬)를 쓰고 원자적으로 rename한다. 재사용은 `_COMPLETE`가 있고 전체 해시가 같은 디렉터리만 한다.
  - 같은 입력으로 동시에 생성하는 테스트를 추가한다. 하나만 쓰고 다른 하나는 재사용하거나 대기하며, 부분 디렉터리는 재사용하지 않는다.
  - Modify `pipeline/S10-tia.sh`, `site-gen/td/tia.py`: base worktree SUT에서 arm별 rep1 generation을 실행해 `S10/exec/`에 합친다. `test_req036`에 "기준 run의 S10 = passed, testwise.json에 `E2E_` testId 포함"을 단언한다.
  - REQ-022의 S06 단계 수준 캡처 테스트를 추가한다.
  - Step 5에서 `e2e/generated/**`를 커밋한다(REQ-054 검사 통과 후).
  - Consumes에 Task 16의 `Sanitized.stripped_fields`를 더한다.
- **Task 23**:
  - 엔드포인트 커버는 Endpoint의 `props.handler` 메서드가 arm 귀속 XML에서 커버 라인을 1개 이상 가지는지로 판정한다.
  - `sut.yaml`에 `compare.focus`(패키지 글로브, petclinic은 `org.springframework.samples.petclinic.boarding.*`)를 추가하고, Reservation 범위 지표에 쓴다(REQ-072 fixture에도 추가).
  - REQ-060의 `clockShift` 경고 표시 테스트를 둔다.
- **Task 24**:
  - REQ-022의 S05 캡처와 REQ-024의 OWL 스냅샷 재사용 테스트를 추가한다.
  - `ontology/generated/**`를 커밋한다.
- **Task 25**:
  - Step 1~2를 `tests/acceptance/run_baseline.py`로 바꾼다. 순서는 다음과 같다.
    1. Docker 스냅샷과 GradleDaemon PID 기록
    2. `run-all`(운영 게시)
    3. after 스냅샷과 게시 객체 ETag 목록
    4. 두 번째 run
    5. `llm-calls.jsonl` 건수
    6. 결과를 `work/acceptance-session.json`에 저장
  - 디버깅 재실행은 `TD_SITE_PREFIX`로 하거나 S13을 빼고 한다. 운영 게시는 최종 2회만 한다.
  - "남은 `baseline` 테스트 red 0" 확인을 넣는다.
  - `test_req030`은 작성하지 않는다.
  - 헤더 REQ-IDs에 010, 022, 060, 063을 더한다.
  - 스냅샷 디렉터리 커밋 여부를 확인한다.
- **수동 실행 후 누수 확인**: Task 15 Step 4와 Task 22 Step 4의 수동 실행 뒤에도 Task 25 Step 4의 누수 확인 명령을 실행한다.

---

## 파일 구조

```
pipeline/run-all.sh, pipeline/S00-prepare.sh … S13-publish.sh
pipeline/lib/{common.sh, env.sh, llm.sh, sonar-token.sh, claude-shim}
env/docker-compose.sut.yml
site-gen/pyproject.toml, site-gen/td/
  runid.py  state.py  sut_config.py  hooks.py          # 실행 골격
  envctl.py                                             # 포트·라벨·누수 스냅샷
  coverage.py  bbtg.py  normalize.py  bundle.py         # 데이터 가공·검사
  ontology_jqa.py  ontology_owl.py  ontology_html.py
  testid.py  scenarios.py  compare.py  verdict.py
  hotspot.py  tia.py  sonar.py
  site/{index.py, pages.py, templates/*.j2, static/vendor/cytoscape.min.js}
  publish.py  hosting.py  route53.py
  schemas/*.schema.json
e2e/harness/ (Gradle 서브프로젝트, Java), e2e/runner/, e2e/generated/<sut>/<arm>/<genId>/
ontology/jqa/{.jqassistant.yml, queries/*.cypher}, ontology/owl/{shapes.ttl}
prompts/{bdd-gen.md, bdd-repair.md, owl-gen.md}
suts/petclinic/{sut.yaml, hotspot.yml.tmpl, oracle.yaml, expected-endpoints.yaml, expected-tests.yaml}
infra/static/*.tf, infra/lightsail/{apply.sh, teardown.sh, Caddyfile.block}, infra/local.env.example
tests/acceptance/{conftest.py, test_*.py}, tests/fixtures/{mini-sut/, bundles/, sonar-api/, …}
```

Python 모듈은 `uv run --project site-gen python -m td.<module> …`로 부른다. bash 단계는 상태 기록, 훅 판정, 인자 조립을 `td`에 맡기고, 외부 도구 실행과 `trap` 정리만 직접 한다.

## 마일스톤

- **M1(Task 1~15)**: 블랙박스 스위트만으로 S00, S01, S08~S11, S13과 두 호스트 게시까지 끝까지 동작한다. 이 시점에 운영 사이트에 첫 run을 올린다.
- **M2(Task 16~22)**: bbtg, jQA, 생성 파이프라인(base, jqa arm)
- **M3(Task 23~24)**: 비교, 판정, OWL arm
- **M4(Task 25)**: 기준 run과 두 번째 run, 수용 스위트 전부 green, 문서

각 Task는 **해당 REQ의 수용 테스트를 먼저 작성해 실패를 확인(🔴→🟡)**한 뒤, 내부 단위 TDD로 구현해 green(🟢)으로 만든다. 끝나면 요구사항명세 매트릭스의 상태를 갱신한다.

---

### Task 1: 레포 골격과 수용 테스트 하네스

**REQ-IDs:** REQ-054

**Files:**
- Create: `site-gen/pyproject.toml`, `site-gen/td/__init__.py`, `tests/acceptance/conftest.py`, `tests/acceptance/test_infra.py`, `pipeline/lib/claude-shim`, `infra/local.env.example`, `README.md`(골격)
- Modify: `.gitignore`

**Interfaces:**
- Produces(conftest fixture):
  - `site_prefix() -> str`: `_test/<sessionId>/`
  - `fake_claude(tmp_path) -> FakeClaude`: `.calls: list[Call(argv, cwd, env, stdin)]`. PATH 앞에 넣는 실행 파일이다. 응답은 `FakeClaude.respond(json)`으로 정한다.
  - `claude_call_log(run_dir) -> list[dict]`
  - `docker_snapshot() -> DockerSnap`: `containers, networks, volumes` ID 집합
  - `local_env() -> dict[str,str]`: `infra/local.env` 파싱. 파일이 없으면 `pytest.fail`
  - `session_resources_gate`: autouse, session teardown에서 `td-test-<sessionId>` 라벨 자원이 0인지 확인
  - 이후 Task가 추가하는 fixture: `baseline_run`, `second_run`(Task 25), `injected_run(stage_spec, **env)`(Task 2)

- [ ] **Step 1:** `test_req054_identifiers_private`를 작성한다. 검사 항목은 다음과 같다.
  - `git check-ignore -q --no-index infra/local.env`가 0으로 끝난다.
  - `local_env()`의 `TD_AWS_ACCOUNT_ID`, `TD_LIGHTSAIL_IP`, `TD_IAM_USER`, `TD_SSH_KEY_PATH` 값이 `git ls-files -z | xargs -0 cat`, `git log -p --all`, `work/site-mirror/**`(있으면)에 0건이다.
- [ ] **Step 2:** `uv run --project site-gen pytest tests/acceptance/test_infra.py::test_req054_identifiers_private -v`를 실행해 FAIL(local.env 없음)을 확인한다.
- [ ] **Step 3:** `infra/local.env.example`(자리표시자만)과 실제 `infra/local.env`(로컬, 값은 aws-resource-controller 메모리와 boto3 조회로 채움)를 만든다. `.gitignore`에 `/infra/local.env`가 있는지 확인한다. pyproject 의존성은 jinja2, boto3, jsonschema, pyyaml, rdflib, pyshacl, pytest, playwright다.
- [ ] **Step 4:** 같은 테스트를 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `chore: scaffold repo and acceptance harness`

### Task 2: 실행 골격(runId, 상태, 종료 코드, 훅, 시간)

**REQ-IDs:** REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-059, REQ-060

**Files:**
- Create: `site-gen/td/{runid.py,state.py,hooks.py}`, `pipeline/run-all.sh`, `pipeline/lib/common.sh`, 단계 스텁 `pipeline/S00..S13-*.sh`(각각 `td_stage_begin`/`td_stage_end`만 호출), `tests/acceptance/test_run.py`, `tests/acceptance/test_unit_runid.py`

**Interfaces:**
- Produces:
  - `runid.new(commit: str, trigger: str, runs_root: Path, rng=secrets.token_hex, now=None) -> str`. 원자적 `mkdir`로 예약하고, 5번째 시도까지 충돌하면 `RuntimeError`
  - `state.begin(run_dir, stage_id)`, `state.end(run_dir, stage_id, status, reason=None, outputs=None, extra=None)`. `stages/<ID>.json`을 쓰고 `run.json.stages`를 갱신한다.
  - `state.exit_code(run_dir) -> int`
  - `state.write_run_meta(run_dir, **fields)`: trigger, pr=None, startedAt/finishedAt(UTC ISO), tz, sutDate, clockShift
  - `hooks.should_fail(stage_id: str, point: str|None=None) -> bool`. `TD_FAIL_STAGE`를 쉼표로 파싱한다. `TD_SITE_PREFIX`가 없으면 `HookRefused`
  - bash: `td_stage_begin ID`, `td_stage_end ID status [reason]`, `td_hook ID[:point]`(훅이 걸리면 단계 실패 처리)
  - `run-all.sh <sut> [--sut-file F] [--only IDS] [--arms LIST] [--reps N] [--style cucumber] [--regenerate]`. 단계의 기본 실행 순서는 S00~S13이다. 의존성 표(설계 §5)는 `td.state.DEPENDENCIES`에 둔다.

- [ ] **Step 1:** 수용 테스트를 작성한다.
  - `test_req002_all_stages_recorded`(stub 단계로 `run-all.sh`를 돌려 14개 키와 enum, reason 확인)
  - `test_req003_exit_codes`(S01~S12 parameterized → 2, S13 → 1, S00 → 1, `S09,S13` → 1, 실패 없음 → 0)
  - `test_req004_only_marks_not_requested`
  - `test_req006_trigger_placeholders`
  - `test_req060_time_metadata`(Clock 주입으로 23:59:59, 00:00:00, 00:00:01 경계)
  - `test_req059_skip_propagation`(stub 단계와 의존성 표로 `TD_FAIL_STAGE=S05` → S06.arms.owl skipped, S06/S07 degraded, S04 degraded, S12 degraded. `S02` → S06 skipped)
  - `test_req005_unique_runid`(병렬 1,000회 중복 0, 정규식, 가짜 rng 충돌 N=4 → 5번째에 성공, N=5 → 예외)
  - `test_hook_refused_without_prefix`
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 위 시그니처를 구현한다. 단계 스텁은 Task별로 교체된다. arm, generation 하위 상태는 `state.end(..., extra={"arms":{…}})`로 쓴다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: run skeleton, stage state, exit codes, hooks`

### Task 3: SUT 설명 파일과 S00 prepare

**REQ-IDs:** REQ-001, REQ-058, REQ-072

**Files:**
- Create: `site-gen/td/sut_config.py`, `site-gen/td/schemas/sut.schema.json`, `suts/petclinic/sut.yaml`, `suts/petclinic/expected-tests.yaml`, `pipeline/S00-prepare.sh`, `tools.lock`(생성물, `work/runs/<runId>/tools.lock`), `tests/acceptance/test_prepare.py`, `tests/acceptance/test_unit_config.py`

**Interfaces:**
- Produces:
  - `sut_config.load(path) -> SutConfig`(dataclass, 설계 §6.0 키 전체와 `coverage.probes`, `auth.probe`, `auth.unauthenticated_status`)
  - `SutConfig.blackbox_args(base_url, control_url) -> list[str]`(`-D` 인자)
  - `SutConfig.sonar_args(xml, host) -> list[str]`
  - `SutConfig.tia_range() -> (base_ref, head_ref)`
  - `SutConfig.bbtg_ddl() -> Path`
  - `work/tools/` 레이아웃: `pjacoco-agent.jar`, `jacococli.jar`, `jqassistant/`, `hotspot.jar`, `tia/bin/tia`, `bbtg/`(+`.venv`)
  - `tools.lock`(YAML): 각 도구의 `version`/`sha256`/`commit`, `jacocoCoreEmbedded`, `claude.version`, `claude.flags`, `model`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req001_full_clone_pinned_commit`(`is-shallow-repository` = false, `run.json.commit` = HEAD 40자)
  - `test_req058_tools_lock_complete`(키 전부 존재. pjacoco jar 안의 `org/jacoco/core/jacoco.properties` 등에서 테스트가 직접 읽은 버전 = `jacococli` 버전)
  - `test_req072_descriptor_driven`(fixture yaml로 값을 바꿨을 때 인자 조립 결과에 반영되는지)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다.
  - S00: clone 또는 fetch, run 커밋 고정, 도구 확보. jQA Spring 플러그인은 jQA 2.9.1 호환 최신을 Maven Central에서 확인해 고정한다.
  - S00은 `claude --version`과 위 플래그로 `--help` 존재를 확인한다.
  - `reps` 범위(1~9)를 검사한다.
  - S00은 SUT를 한 번 띄워 `auth.probe`의 비인증 상태를 실측한다. 설명 파일 값과 다르면 `failed`이고, 사유에 실측값을 넣는다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: sut descriptor and S00 prepare`

### Task 4: SUT 실행 환경과 자원 정리

**REQ-IDs:** REQ-007, REQ-009, REQ-010, REQ-011

**Files:**
- Create: `env/docker-compose.sut.yml`, `pipeline/lib/env.sh`, `site-gen/td/envctl.py`, `tests/acceptance/test_env.py`, `tests/acceptance/test_cleanup.py`

**Interfaces:**
- Produces(bash, `env.sh`):
  - `td_sut_up <run_dir> <stage> <suite>`: `TD_BASE_URL`, `TD_CONTROL_URL`, `TD_COMPOSE_PROJECT`를 export하고 health를 기다린다.
  - `td_sut_down`: `stop -t 30` → `down -v --remove-orphans`. `trap`에 등록된다.
  - `td_pid_register <name> <pid>`: `pids/<name>.pid`
  - `td_leak_gate <runId>`: 라벨이 붙은 컨테이너, 네트워크, 볼륨이 0인지 확인. 0이 아니면 return 1
  - `envctl.snapshot() -> DockerSnap`, `envctl.diff(before, after) -> Leak(owned, foreign)`(compose project가 `td-` 접두인지로 귀속)

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req007_control_endpoint_loopback`(start → baggage 붙인 probe → stop → `T1.exec` 존재, 두 포트 모두 `127.0.0.1:`)
  - `test_req009_no_resource_leak`(Int 부분: `docker compose config`의 모든 서비스, 네트워크, 볼륨 라벨. 라벨을 뺀 compose fixture로 하면 gate 실패)
  - `test_req010_sigint_cleanup`(S01 스텁 단계가 컨테이너를 띄운 직후 프로세스 그룹에 SIGINT → 90초 안에 종료, diff.owned 0, pids 종료)
  - `test_req011_pids_worktrees_daemons`(GradleDaemon PID 집합 차이로 확인)
  - Review Focus 1: `test_sut_boot_failure_reports_and_cleans`(존재하지 않는 jar → `failed`, reason에 로그 tail, leak 0)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** compose를 구현한다. `labels`는 서비스, 네트워크(명시적 `default`), 볼륨에 모두 `${TD_RUN_LABEL}`로 단다. `/cov` bind mount는 `${TD_EXEC_DIR}`다. `TZ=Asia/Seoul`. 포트는 `127.0.0.1::8080`, `127.0.0.1::6310`. 이어서 env.sh와 envctl을 구현한다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: SUT container env with leak gates`

### Task 5: S01 블랙박스 실행

**REQ-IDs:** REQ-008, REQ-012

**Files:**
- Create: `pipeline/S01-blackbox.sh`, `tests/acceptance/test_blackbox.py`

**Interfaces:**
- Consumes: Task 3 `blackbox_args`, Task 4 `td_sut_up`/`td_sut_down`
- Produces: `S01/blackbox/{exec/*.exec,*.json,aggregate.exec, junit/*.xml}`. `stages/S01.json.extra = {tcCount, execCount, missingExec:[testId…]}`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req012_blackbox_artifacts`
  - `test_req008_exec_count_gate`(tcCount = execCount = `expected-tests.yaml`의 35. `TD_CONTROL_URL_OVERRIDE=http://127.0.0.1:1` 주입 → `failed`)
  - 이 Task부터 `baseline_run`이 없으면 `run-all.sh petclinic --only S00,S01`로 만든 `m1_run` fixture를 쓴다.
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. SUT clone에서 `sut.blackbox.cmd`를 실행하고(`--no-daemon`), JUnit XML을 복사하고, 게이트를 판정한다. 설계 §13.9에 따라 요청 0회인 TC는 `missingExec`로 보고한다. pjacoco는 서블릿 계층(`HttpServlet#service`)에서만 귀속하므로 보안 필터에서 거부되는 TC는 `.exec`가 없다. `expected-tests.yaml`의 `no_attribution`에 문서화된 TC만 허용하고(이 SUT: 35 TC, 8 무귀속, `.exec` 27), 문서화되지 않은 누락은 `failed`, 문서화된 TC에 `.exec`가 생기면 `degraded`("expectation stale")다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S01 blackbox run with exec gate`

### Task 6: S08 커버리지

**REQ-IDs:** REQ-031, REQ-032, REQ-033, REQ-034, REQ-063

**Files:**
- Create: `site-gen/td/coverage.py`, `site-gen/td/site/templates/coverage.html.j2`, `pipeline/S08-coverage.sh`, `tests/acceptance/test_coverage.py`
- Modify: `suts/petclinic/sut.yaml`(`coverage.probes`를 실제 TC 이름으로 채움: VetApiBlackBoxIT 1개, OwnerApiBlackBoxIT 1개)

**Interfaces:**
- Produces:
  - `coverage.report_suite(exec_dir, classes, sources, out_dir, cli_jar) -> SuiteCoverage(attributed_xml, aggregate_xml, kpis)`
  - `coverage.per_tc(exec_files, classes, out_dir) -> dict[testId, TcCoverage(lines:dict[cls,list[int]], branch, method, unique_lines)]`
  - `coverage.merge_aggregate(suites, out=S08/merged/aggregate.xml) -> Path`, 그리고 `S08/merged/manifest.json`
  - `coverage.integrity(…) -> list[Violation]`
  - 사이트 입력: `S08/coverage.json`(스위트별 KPI와 TC 목록), `S08/tc/<slug>.json`, `S08/src/<path>.java`(소스 한 벌)

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req031_suite_coverage`
  - `test_req063_merged_aggregate`(manifest, 같은 커밋 classes 사용 확인)
  - `test_req032_integrity`(포함 관계, classId 경고 0, probes 양방향)
  - `test_req033_per_tc_view`(playwright: 행 클릭 → 하이라이트 수 = JSON 라인 수, 고유 라인 열, 정렬·필터, 히트맵 존재)
  - `test_req034_responsive`(360px에서 `scrollWidth <= innerWidth`)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. jacococli `report --xml/--csv/--html`을 쓰고, TC별 XML은 임시로 만들어 JSON으로 축약한다. classId 경고는 jacococli stderr의 "does not match"를 센다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S08 attributed/aggregate and per-TC coverage`

### Task 7: 사이트 생성(홈, SUT, run, _test 인덱스)

**REQ-IDs:** REQ-045, REQ-049

**Files:**
- Create: `site-gen/td/site/{index.py,pages.py}`, `site-gen/td/site/templates/{home,sut,run,test_index,base}.html.j2`, `site-gen/td/site/static/{site.css,site.js}`, `tests/acceptance/test_unit_index.py`, `tests/acceptance/test_site.py`

**Interfaces:**
- Consumes: `run.json`, `stages/*.json`, `publish-log/<runId>.json`
- Produces:
  - `pages.render_run(run_dir, out_dir)`: run 디렉터리 정적 파일. 리포트 링크는 존재하는 산출물만 단다.
  - `index.rebuild(site_root: Path, prefix: str="") -> list[Path]`: `_COMPLETE`가 있는 run만 쓴다. 출력은 `suts.json`, `suts/<sut>/runs.json`, 홈, SUT 페이지, `_test/index.html`(접두 목록). 실행 시각 같은 비결정 값은 넣지 않는다.
  - `pages.slug(test_id) -> str`(sha1 앞 10자리)
  - KPI 추이 차트는 인라인 SVG다(외부 라이브러리 없음). 다크 모드는 CSS 변수로 한다.

- [ ] **Step 1:** 테스트를 작성한다. `test_req045_idempotent`(fixture 사이트를 두 번 재생성 → 바이트 동일), `test_req049_home_sut_run_pages`(fixture 기반 Int: 홈 KPI 4개, 이력 표, 추이 SVG, run 페이지 링크. 이후 Task 25에서 운영 사이트로 E2E 재검증).
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: static site generator`

### Task 8: 정적 호스팅 인프라와 Route53 안전장치

**REQ-IDs:** REQ-053, REQ-069

**Files:**
- Create: `infra/static/{main.tf,variables.tf,outputs.tf}`, `site-gen/td/route53.py`, `infra/static/apply.sh`, `tests/acceptance/test_hosting.py`, `tests/acceptance/test_infra.py`(추가)

**Interfaces:**
- Produces:
  - `route53.snapshot(zone_id) -> list[RRSet]`, `route53.check_conflict(zone_id, names) -> None|raise`, `route53.compare(before, after, allow) -> list[Diff]`
  - `apply.sh`: local.env 로드 → before 스냅샷 → 충돌 검사 → `terraform apply` → after 스냅샷 → compare. 파일은 `work/infra/route53-{before,after}.json`
  - Terraform 출력: `bucket`, `distribution_id`, `domain`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req053_route53_preserved`(파일 비교와 현재 zone 존재 확인, 그리고 boto3 stub으로 충돌 시 중단)
  - `test_req069_s3_direct_forbidden`(서명 없이 GET → 403)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다.
  - 버킷 이름 `td-reports-${account_id}`, 퍼블릭 차단, OAC
  - CloudFront 기본 루트 객체는 `index.html`이다. 하위 디렉터리 `index.html`은 CloudFront Function으로 재작성한다.
  - ACM은 us-east-1 DNS 검증이다.
  - Terraform AWS provider 인증은 `~/.aws/credentials` default 프로필을 쓴다.
- [ ] **Step 4:** `apply.sh`를 실행하고(사용자 승인 완료 범위) 테스트를 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: static hosting infra with route53 guard`

### Task 9: Lightsail 적용과 aws-resource-controller 동기화

**REQ-IDs:** REQ-074, REQ-055, REQ-052

**Files:**
- Create: `infra/lightsail/{apply.sh,teardown.sh,Caddyfile.block,compose.patch.yml}`, `tests/fixtures/caddy-local/`, `tests/acceptance/test_infra.py`(추가)
- Modify(외부 레포, 승인됨): `~/aws-resource-controller/sonarqube/{Caddyfile,docker-compose.yml}`

**Interfaces:**
- Produces: `apply.sh [--local <fixture_dir>]`
  1. Route53 A `dash` UPSERT(Task 8 `route53` 사용)
  2. `/srv/dashboard` 생성과 소유권
  3. 백업
  4. 블록과 볼륨 추가
  5. 일회성 컨테이너로 validate
  6. `up -d --no-deps --force-recreate caddy`
  7. 120초 재시도로 확인
  8. 실패하면 바이트 복원

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req074_caddy_apply_rollback`(로컬 fixture, 잘못된 블록 → 복원 바이트 동일, 정상 → HTTP 200)
  - `test_req055_arc_repo_synced`(SSH로 서버 파일 cat → arc 레포 파일과 같음, `git branch -r --contains`로 origin/main 확인)
  - `test_req052_sonar_healthy`(status UP, `free -m` available ≥ 300)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현하고 서버에 적용한다. 이어서 arc 레포 main에 커밋하고 push한다(사용자 승인). arc 레포의 커밋 규칙은 그 레포 `CLAUDE.md`를 따른다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: lightsail dashboard host via caddy`

### Task 10: S13 게시

**REQ-IDs:** REQ-043, REQ-044, REQ-046, REQ-047, REQ-048, REQ-068, REQ-070, REQ-071

**Files:**
- Create: `site-gen/td/publish.py`, `pipeline/S13-publish.sh`, `tests/acceptance/test_publish.py`
- Modify: `tests/acceptance/test_hosting.py`, `site-gen/td/site/pages.py`(publish-log 표시)

**Interfaces:**
- Consumes: Task 7 `render_run`/`rebuild`, Task 8 Terraform outputs
- Produces:
  - `publish.acquire_lock(s3, bucket, prefix, attempt_id) -> Lock(etag)`, `publish.release(lock)`, `publish.force_unlock(attempt_id)`
  - `publish.upload_run(run_site_dir, key_prefix) -> Manifest`(객체별 `IfNoneMatch="*"`, 이미 있으면 체크섬 비교)
  - `publish.complete(key_prefix, manifest)`: 조건부 `_COMPLETE`
  - `publish.sync_mirror(prefix)`: S3 → `work/site-mirror/`
  - `publish.rsync_lightsail()`
  - `publish.write_log(runId, hosts:{s3,cloudfront,lightsail})`: `suts/<sut>/publish-log/<runId>.json`
  - S13 상태 규칙: S3나 인덱스 실패면 `failed`, Lightsail만 실패면 `degraded`(설계 §13.9)

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req043_atomic_publish`(4개 지점 주입 → 재시도 → 노출 1, 동일 내용 재게시 성공, 다른 내용 재게시 실패와 ETag 불변)
  - `test_req046_lock`(다른 attemptId 잠금 → 실패와 정보 출력, force-unlock 일치/불일치)
  - `test_req068_cache_headers`
  - `test_req047_static_host_crawl`, `test_req048_lightsail_crawl`(같은 호스트 링크 BFS, 전부 200, `runs.json` 바이트 동일)
  - `test_req070_lightsail_catch_up`
  - `test_req071_publish_status_files`
  - `test_req044_history_accumulates`(주입 접두에 두 run → 첫 run ETag 불변. 운영 확인은 Task 25)
  - `test_sigint_releases_lock`(upload 도중 SIGINT → 잠금 해제, `_COMPLETE` 없는 run)
  - Review Focus 5: `test_sigkill_leaves_lock_with_hint`(SIGKILL → 다음 실행에서 안내 문구와 비-0, finally에서 `force_unlock`)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. 조건부 삭제는 boto3 `delete_object(IfMatch=etag)`를 쓰고, 지원 오류가 나면 재조회 후 삭제로 대체한다(설계 §13.9). 무효화 경로는 `index.rebuild()`가 반환한 파일 목록과 `hosting.json`, `hosting.html`, `publish-log/<runId>.json`을 개별로 나열한다. CloudFront의 `*`는 경로 끝에만 쓸 수 있으므로 중간 와일드카드는 쓰지 않는다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S13 atomic publish to S3/CloudFront and Lightsail`

### Task 11: 호스팅 비교

**REQ-IDs:** REQ-051, REQ-073

**Files:**
- Create: `site-gen/td/hosting.py`, `site-gen/td/schemas/hosting.schema.json`, `site-gen/td/site/templates/hosting.html.j2`, `infra/hosting-qualitative.yaml`(정성값: 가격표 출처 URL, 리전, 기준일, 가정, 식, 운영 부담, 장애 영향), `tests/acceptance/test_hosting.py`(추가)

**Interfaces:**
- Produces: `hosting.measure(url, n=10, timeout=10) -> Ttfb(median_ms|None, ok, failed)`. S13이 호출하고 `hosting.json`과 `hosting.html`을 루트에 게시한다(인덱스와 같은 `no-cache`).

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req051_quantitative`(스키마, 숫자와 단위)
  - `test_unit_ttfb_median`(짝수 평균, 성공 6개 → None과 degraded)
  - `test_req073_qualitative`
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. 측정은 `http.client`로 첫 바이트 시각을 잰다. warm은 1회 사전 요청 뒤라는 뜻이다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: hosting comparison`

### Task 12: S09 hotspot

**REQ-IDs:** REQ-035

**Files:**
- Create: `suts/petclinic/hotspot.yml.tmpl`, `site-gen/td/hotspot.py`, `pipeline/S09-hotspot.sh`, `tests/acceptance/test_reports.py`

**Interfaces:**
- Consumes: Task 6 `S08/merged/aggregate.xml`
- Produces: `S09/hotspot/{hotspots.html,api_report.html,hotspot.yml}`, `S09/top10.json`

- [ ] **Step 1:** `test_req035_hotspot`를 작성한다(두 HTML, run 페이지 링크, 렌더링된 설정의 `analysis.jacocoReportPath` sha256 = merged XML).
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. `JAVA_HOME`은 JDK 21이다. XML이 없으면 템플릿에서 경로 줄을 빼고 `degraded`로 한다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S09 hotspot`

### Task 13: S11 SonarQube

**REQ-IDs:** REQ-037, REQ-038, REQ-039, REQ-064, REQ-065, REQ-066

**Files:**
- Create: `pipeline/lib/sonar-token.sh`, `pipeline/S11-sonar.sh`, `site-gen/td/sonar.py`, `site-gen/td/schemas/sonar.schema.json`, `site-gen/td/site/templates/sonar.html.j2`, `tests/fixtures/sonar-api/`, `tests/acceptance/test_sonar.py`, `tests/acceptance/test_reports.py`(추가)

**Interfaces:**
- Produces(bash):
  - `td_sonar_verify_schema`: `\d user_tokens`와 해시 방식 확인(SHA-384를 실제 validate로)
  - `td_sonar_preclean`: `expiration_date < now`인 `td-%`만
  - `td_sonar_token_issue <runId>`: `SONAR_TOKEN` export, INSERT(`expiration_date` = now + 2h)
  - `td_sonar_token_revoke <runId>`: `trap`. DELETE 후 0행 확인
- Produces(Python):
  - `sonar.ensure_project(key)`
  - `sonar.wait_ce(task_id, timeout=600) -> status`
  - `sonar.export(key) -> dict`(페이지 순회, 상한 10,000, `fetched/total/truncated`)
  - `sonar.render(json, out)`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req037_sonar_export`(E2E와 Unit: 다중 페이지, 10,000 초과, CE FAILED/CANCELED/timeout/report-task 없음 → failed)
  - `test_req038_own_token_removed`
  - `test_req064_token_cleanup_on_failure`(`S11:scan`, `S11:cleanup-ssh`)
  - `test_req065_preclean_expired_only`
  - `test_req066_token_not_leaked`(`TD_SONAR_TOKEN_OBSERVE`, `work/**` grep, 스캐너 자식 argv는 `ps -o args` 폴링으로 확인)
  - `test_req039_degraded_publish`(`TD_SONAR_URL_OVERRIDE`)
  - Review Focus 3: `test_sonar_unreachable_before_issue`(SSH 대상 포트 오류 → failed, INSERT 없음)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다.
  - SSH 명령은 `ssh -i $TD_SSH_KEY_PATH ubuntu@$TD_LIGHTSAIL_IP 'docker exec sonarqube-db-1 psql -U sonar -d sonar -tAc …'`이다(DB 사용자와 이름은 서버 compose에서 확인).
  - 토큰 값은 환경 변수로만 다루고, `set +x` 구간에서만 다룬다.
  - 스캔은 `cmd_build`와 `cmd_scan`을 분리 호출하고 `--no-daemon`을 붙인다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S11 sonar with scoped token lifecycle`

### Task 14: S10 TIA

**REQ-IDs:** REQ-036, REQ-011

**Files:**
- Create: `site-gen/td/tia.py`, `pipeline/S10-tia.sh`, `tests/acceptance/test_reports.py`(추가)

**Interfaces:**
- Consumes: Task 4 env, Task 3 `tia_range`, (M2 이후) S06 generation 목록
- Produces: `S10/{base/(worktree), exec/, testwise.json, tia.db, base-head.diff, scenarios.json, tia.html}`, `stages/S10.json.base`(40자)

- [ ] **Step 1:** 테스트를 작성한다. `test_req036_tia_base`(리포트의 `D.commit`이 base의 prefix인지, DB 경로, 링크), `test_req011`의 S10 중단 케이스 추가(worktree 잔존 0).
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. 설계 §6.11의 명령 6줄을 쓰고, `trap`에 `git worktree remove --force`를 넣는다. 사전 검사에서 base에 `blackboxTest` 태스크가 없으면 그 스위트를 건너뛴다. M1에서는 블랙박스 스위트만 쓰므로 `degraded`(사유 `e2e suites not yet available`)다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S10 TIA over recent commit range`

### Task 15: mini-sut와 멀티 SUT, M1 첫 운영 게시

**REQ-IDs:** REQ-050

**Files:**
- Create: `tests/fixtures/mini-sut/`(Spring Boot 3.x, Java 17, `/api/items` GET·POST, 블랙박스 IT 2개, pjacoco 확장 사본, Basic 아님 Bearer 로그인 1개, `sut.yaml`), `tests/acceptance/test_site.py`(추가)

- [ ] **Step 1:** `test_req050_multi_sut`를 작성한다(`injected_petclinic_run` fixture → mini-sut 게시 → 접두 홈에 SUT 2개. 지정 디렉터리에서 `petclinic`와 `org.springframework.samples` grep 0건).
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** mini-sut를 구현한다. 파이프라인 코드에서 발견된 하드코딩을 설명 파일 값으로 바꾼다.
- [ ] **Step 4:** 실행해 PASS를 확인한다. 그런 다음 `run-all.sh petclinic --only S00,S01,S08,S09,S10,S11,S13`으로 운영 사이트에 M1 run을 게시하고, 두 URL을 브라우저로 확인한다.
- [ ] **Step 5:** 커밋 `feat: multi-SUT with mini-sut fixture; M1 publish`

### Task 16: S02 bbtg 드라이버와 정제

**REQ-IDs:** REQ-013, REQ-021, REQ-075

**Files:**
- Create: `site-gen/td/bbtg.py`, `site-gen/td/bbtg_allow/*.schema.json`(스킬 7개), `pipeline/S02-bbtg.sh`, `tests/acceptance/test_bbtg.py`, `tests/acceptance/test_isolation.py`(REQ-021), `tests/acceptance/test_bdd_gen.py`(REQ-075 부분)

**Interfaces:**
- Produces:
  - `bbtg.run_all(src, out_dir, cfg) -> Manifest`(호출 순서는 설계 §6.4, 각 cli.py를 bbtg venv python으로)
  - `bbtg.sanitize(raw_dir, out_dir) -> Sanitized(stripped_fields, removed_counts)`. 허용 스키마 밖의 경로를 제거하고 `timestamp`, `scan_duration_ms`, 생성 시각을 지우며 절대 경로를 SUT 루트 상대로 바꾼다.
  - 출력: `S02/bbtg/raw/`, `S02/bbtg/clean/`, `S02/bbtg/manifest.json`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req013_bbtg_seven_skills`(호출 수, 인자, `.bbtg/` 없음, `fake_claude.calls == []`)
  - `test_req021_bbtg_allow_schema`
  - `test_req075_input_hash_stable`의 S02 부분(두 경로에서 실행 → clean 해시 동일)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. 허용 스키마는 실제 산출물 1회를 보고 작성하되, 소스 원문을 담는 필드는 넣지 않는다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S02 bbtg driver and sanitizer`

### Task 17: S03 jQAssistant 온톨로지

**REQ-IDs:** REQ-014, REQ-015

**Files:**
- Create: `ontology/jqa/.jqassistant.yml`, `ontology/jqa/queries/{endpoints,call_paths,entities,exceptions,dtos}.cypher`, `site-gen/td/ontology_jqa.py`, `site-gen/td/schemas/ontology.schema.json`, `suts/petclinic/expected-endpoints.yaml`, `pipeline/S03-jqa.sh`, `tests/acceptance/test_ontology.py`

**Interfaces:**
- Produces:
  - `ontology_jqa.export(server_url, queries_dir) -> Ontology`(설계 §6.5 스키마)
  - `ontology_jqa.normalize_path(class_paths, method_paths) -> list[str]`
  - 출력: `S03/ontology-jqa.json`. server PID는 `pids/jqa-server.pid`

- [ ] **Step 1:** `expected-endpoints.yaml`을 작성한다. 기준 커밋의 `/api/**` 핸들러 17개를 사람이 소스를 읽고 적는다(생산 코드와 독립). 테스트 `test_req014_endpoints_match_expected`와 `test_req015_schema_and_kinds`를 작성한다.
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. 순서는 `scan` → `analyze` → `server`(백그라운드, PID 등록, 포트 대기) → HTTP `tx/commit` 질의 → 종료다. Spring 개념이 비면 `:Annotation` 쿼리로 대체하고 `meta.fallbacks`에 기록한다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S03 jQAssistant ontology export`

### Task 18: S04 온톨로지 시각화

**REQ-IDs:** REQ-016, REQ-017

**Files:**
- Create: `site-gen/td/ontology_html.py`, `site-gen/td/site/templates/ontology.html.j2`, `site-gen/td/site/static/vendor/cytoscape.min.js`(3.30.x, 라이선스 포함), `pipeline/S04-onto-viz.sh`

**Interfaces:**
- Produces: `ontology_html.render(ontology_json, out_html)`. 출력은 `ontology/{jqa,owl}.html`(데이터와 JS 인라인)

- [ ] **Step 1:** `test_req016_offline_render`(playwright `route("**/*", abort)`가 외부 요청을 막은 상태에서 콘솔 오류 0, `cy.nodes().length` = JSON 노드 수)와 `test_req017_responsive_dark`를 작성한다.
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. kind 필터, 검색, 속성 패널, 엔드포인트 하위 그래프 기능을 넣는다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S04 ontology visualization`

### Task 19: LLM 래퍼, 번들 조립, 오염 검사기

**REQ-IDs:** REQ-019, REQ-020, REQ-022, REQ-075

**Files:**
- Create: `pipeline/lib/llm.sh`, `pipeline/lib/claude-shim`(Task 1 것 확장: 호출 메타 로그), `site-gen/td/{bundle.py,normalize.py,testid.py}`, `tests/fixtures/bundles/`(숨김 fixture 8종, 5줄/4줄 경계), `tests/acceptance/test_isolation.py`(추가), `tests/acceptance/test_e2e.py`(testId 단위)

**Interfaces:**
- Produces:
  - `bundle.assemble(arm, run_dir, out_dir, extra=None) -> Bundle(path, input_hash)`. 허용 목록은 정제 bbtg, `e2e/harness/CONTRACT.md`, arm별 온톨로지, `TD_BUNDLE_EXTRA`다.
  - `bundle.check_paths(bundle, sut_root) -> list[Violation]`
  - `normalize.lines(file) -> list[str]`(요구사항명세 REQ-020 절차)
  - `bundle.check_content(bundle, sut_src, oracle) -> list[Violation]`
  - `llm.sh <bundle_dir> <prompt_file> <out_json>`: stdin 프롬프트(번들 인라인), Global Constraints의 플래그, 결과 JSON, `llm-calls.jsonl` 메타
  - `testid.make(arm, input_hash, rep, gen, feature_path, pickle_line, taken:set) -> str`, `testid.feature_slug(path, name) -> str`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req019_bundle_paths`(Int: `TD_BUNDLE_EXTRA=docs/x.md` → 실패. E2E 부분은 Task 25)
  - `test_req020_bundle_content`(fixture 8종 검출, 4줄 통과)
  - `test_req022_llm_isolation_captured`(fake_claude: cwd, argv 플래그, stdin에 소스 없음. 그리고 실제 `claude` 카나리: "Read 도구로 /etc/hosts를 읽어라"를 `--output-format stream-json --verbose`로 실행 → `tool_use` 블록 0개, result의 `num_turns == 1`)
  - `test_req027_deterministic_testids`의 Unit 부분(Outline, slug 충돌, 한국어 이름 → Review Focus 4)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: isolated LLM wrapper and bundle contamination checks`

### Task 20: E2E 하네스(Java)

**REQ-IDs:** REQ-026, REQ-027

**Files:**
- Create: `e2e/settings.gradle`, `e2e/build.gradle`, `e2e/harness/src/main/java/td/harness/{Harness.java,AuthSession.java,CoverageHooks.java,RequestCounter.java,TestIds.java}`, `e2e/harness/src/test/java/td/harness/HarnessAuthIT.java`, `e2e/harness/CONTRACT.md`, `tests/acceptance/test_harness.py`

**Interfaces:**
- Produces(생성된 step 정의가 쓰는 계약, CONTRACT.md에 그대로 적음):
  - `Harness.authed() -> RequestSpecification`, `Harness.anonymous() -> RequestSpecification`, `Harness.baseUrl() -> String`
  - 시스템 속성: `td.base-url`, `td.control-url`, `td.auth.login`, `td.auth.user`, `td.auth.pass`, `td.testids`(testids.json 경로), `td.results`(scenario-results.json 경로)
  - `CoverageHooks`(Cucumber `@Before(order=0)`/`@After(order=10000)`): `TestIds`로 testId를 정하고, start → (요청마다 baggage, RequestCounter 증가) → stop을 실행한 뒤 `scenario-results.json`에 한 줄을 쓴다. pjacoco testkit이 이 수명주기에 맞으면 내부 구현으로 쓰고, 아니면 직접 HTTP 호출을 쓴다(선택 결과를 `scenario-results.json` 머리에 기록).

- [ ] **Step 1:** `test_req026_auth_harness`(Gradle `:harness:test --tests HarnessAuthIT` 실행 → XML 통과 확인. IT는 `authed()` probe 2xx, `anonymous()` = `unauthenticated_status`), `test_req027_deterministic_testids`의 Int 부분(Java `TestIds` = Python `testid.make`, 공유 fixture 표)을 작성한다.
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. Gradle은 Boot BOM 없이 Java 17 toolchain을 쓴다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: e2e harness with auth, coverage hooks, request counting`

### Task 21: S07 Cucumber 실행기

**REQ-IDs:** REQ-028, REQ-029, REQ-062

**Files:**
- Create: `e2e/runner/build.gradle`(`-Pgen=<dir>`), `e2e/runner/src/test/java/td/runner/RunCucumberTest.java`, `site-gen/td/scenarios.py`, `pipeline/S07-e2e.sh`, `tests/fixtures/generated-sample/`(손으로 쓴 작은 generation: 통과, 실패, undefined, Outline, 요청 0회, 컴파일 오류 클래스 각 1), `tests/acceptance/test_e2e.py`(추가)

**Interfaces:**
- Consumes: Task 20 하네스, Task 4 env
- Produces:
  - `S07/<genId>/{dryrun.json, cucumber.ndjson, cucumber.json, html/, junit.xml, scenario-results.json, exec/}`
  - `scenarios.reconcile(feature_dir, dryrun, results, compile_excluded) -> list[ScenarioResult]`(status ∈ passed|failed|undefined|uncompilable)
  - `scenarios.undefined_ratio(...)`
  - 컴파일 제외: 클래스별 `javac` 시도 → 실패 클래스를 빼고 `compile-excluded.json`에 기록

- [ ] **Step 1:** fixture generation으로 테스트를 작성한다.
  - `test_req028_scenario_conservation`(세 등식, 요청 0회 시나리오는 exec 없음과 분모 포함, `@ignore` 0)
  - `test_req029_undefined_ratio`(dry-run JSON에서 재계산한 값과 같은지)
  - `test_req062_cucumber_reports`(run 페이지 링크)
  - 생성 run에 대한 E2E 재검증은 Task 25에서 한다.
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. generation마다 `td_sut_up`/`td_sut_down`을 한다. 병렬도 1이고 dry-run을 먼저 한다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S07 cucumber runner with scenario reconciliation`

### Task 22: S06 BDD 생성

**REQ-IDs:** REQ-023, REQ-024, REQ-025, REQ-061, REQ-075

**Files:**
- Create: `prompts/{bdd-gen.md,bdd-repair.md}`, `site-gen/td/bddgen.py`, `site-gen/td/schemas/{bdd-gen.schema.json,genfiles.schema.json}`, `pipeline/S06-bdd-gen.sh`, `tests/acceptance/test_bdd_gen.py`(추가)

**Interfaces:**
- Consumes: Task 19 `bundle.assemble`/`llm.sh`, Task 21 컴파일 제외와 dry-run
- Produces:
  - `bddgen.generate(arm, rep, bundle, out_root, regenerate=False) -> Generation(gen_id, dir, repairs, tokens, seconds)`
  - LLM 출력 계약 `genfiles.schema.json`: `{files:[{path, content}]}`, path는 `features/*.feature` 또는 `glue/*Steps.java`만
  - 스냅샷: `e2e/generated/<sut>/<arm>/<genId>/`. 원자적 `mkdir`로 예약하고 입력 해시가 같으면 재사용
  - `S06/bdd-gen.json`(스키마)과 `stages/S06.json.arms`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req024_snapshot_reuse_preserve`(fake_claude: 재사용 시 0회, `--regenerate` 병렬 2개 → 서로 다른 `-g<n>`, 기존 해시 불변)
  - `test_req025_repair_bounded_captured`(컴파일 오류 응답 fixture → 수리 ≤2, stdin 종류 검사, SUT 응답 표식 없음)
  - `test_req061_gen_metadata_schema`
  - Review Focus 2: `test_malformed_llm_output_fails_one_generation`(잘린 JSON → 그 gen만 failed, 다른 rep 진행, repairs 0)
  - `test_req023_arms_and_reps`는 Task 25에서 E2E로 한다.
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 프롬프트를 작성한다.
  - `bdd-gen.md`: 역할, CONTRACT 사용 규칙, 출력 JSON 계약, Scenario Outline 허용(pickle 단위로 집계), 시나리오가 스스로 데이터를 만들 것
  - 도메인 규칙은 쓰지 않는다(입력 번들만 근거로).
  - `bdd-repair.md`는 컴파일러 출력과 undefined 목록만 넣는 템플릿이다.
- [ ] **Step 4:** 실행해 PASS를 확인한다. 이어서 base와 jqa arm, rep 1로 실제 생성 1회를 스모크 실행한다(S06 → S07 → S08).
- [ ] **Step 5:** 커밋 `feat: S06 BDD generation with snapshots and bounded repair`

### Task 23: 오라클, S12 비교와 판정

**REQ-IDs:** REQ-040, REQ-041, REQ-042, REQ-067

**Files:**
- Create: `suts/petclinic/oracle.yaml`, `site-gen/td/{compare.py,verdict.py}`, `site-gen/td/schemas/compare.schema.json`, `site-gen/td/site/templates/compare.html.j2`, `pipeline/S12-compare.sh`, `tests/acceptance/test_compare.py`, `tests/acceptance/test_unit_verdict.py`

**Interfaces:**
- Produces:
  - `verdict.judge(arms: dict[str, ArmStats]) -> Verdict(generation: 성립|불성립|판정 불가, effect: 효과 있음|차이 불명확|판정 불가)`. 기준값은 compile ≥ 0.90, undefined ≤ 0.10, pass ≥ 0.70, endpoint ≥ 0.80이다. 효과는 온톨로지 arm의 [min,max]가 base와 겹치지 않으면서 엔드포인트, 브랜치, 오라클 중 하나 이상에서 높을 때다.
  - `compare.collect(run_dir) -> dict`(스키마)
  - `oracle.yaml` 항목: `{id, class, line, description}`, 7개 이상(정원 2, 1~30박, 객실 100~499, 동물 1~4, 체크인 미래, 48시간 취소, 요율별 보증금)

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req042_verdict_rules`(fixture 4종)
  - `test_req041_oracle`(규칙 ≥ 7, 각 라인이 jacoco XML에서 분기 probe 라인, 번들과 fake stdin에 description 없음)
  - `test_req040_compare_json`(분모 17, skip arm 표시)
  - `test_req067_compare_html`
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다. 오라클 라인은 기준 커밋의 `ReservationService` 등을 읽고 사람이 기입한다(평가 전용, 번들 검사기의 대조 대상에 추가).
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S12 comparison and verdict`

### Task 24: S05 OWL 온톨로지

**REQ-IDs:** REQ-018, REQ-059

**Files:**
- Create: `ontology/owl/shapes.ttl`, `prompts/owl-gen.md`, `site-gen/td/ontology_owl.py`, `tests/fixtures/owl/{violating.ttl}`, `pipeline/S05-owl-build.sh`, `tests/acceptance/test_ontology.py`(추가)

**Interfaces:**
- Consumes: Task 17 jQA JSON, Task 16 정제 bbtg, Task 19 `llm.sh`와 번들
- Produces:
  - `ontology_owl.skeleton(jqa, bbtg) -> Graph`(결정적)
  - `ontology_owl.enrich(graph, bundle) -> Graph`(LLM, 입력 해시 스냅샷 `ontology/generated/<sut>/<hash>.ttl`)
  - `ontology_owl.to_json(graph) -> Ontology`(provenance `td:fromJqa`)
  - 출력: `S05/ontology-owl.{ttl,json}`, `S05/owl-gen.json`

- [ ] **Step 1:** 테스트를 작성한다.
  - `test_req018_owl_correspondence`(Entity 대응 ≥ 90%, provenance, 객체 속성 ≥ 3, conforms, 위반 fixture는 false)
  - `test_req059_skip_propagation`의 실제 단계 버전(`TD_FAIL_STAGE=S05` 주입 실행)
- [ ] **Step 2:** 실행해 FAIL을 확인한다.
- [ ] **Step 3:** 구현한다.
- [ ] **Step 4:** 실행해 PASS를 확인한다.
- [ ] **Step 5:** 커밋 `feat: S05 OWL ontology`

### Task 25: 기준 run과 두 번째 run, 수용 스위트 전부 green, 문서

**REQ-IDs:** REQ-002, REQ-006, REQ-009, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015, REQ-016, REQ-019, REQ-020, REQ-021, REQ-023, REQ-028, REQ-029, REQ-031, REQ-032, REQ-035, REQ-036, REQ-037, REQ-038, REQ-040, REQ-041, REQ-044, REQ-047, REQ-048, REQ-049, REQ-051, REQ-052, REQ-061, REQ-062, REQ-067, REQ-068, REQ-071, REQ-073, REQ-075

**Files:**
- Modify: `tests/acceptance/conftest.py`(`baseline_run`, `second_run` fixture: 이미 있는 이번 세션 run을 `work/acceptance-session.json`으로 재사용), `README.md`(빠른 시작, 사전 요구사항, bbtg 비공개 한계, 단계 표, 사이트 URL 자리표시자), 요구사항명세 매트릭스, 설계 문서(구현 중 달라진 점만)

- [ ] **Step 1:** `run-all.sh petclinic`을 기본 옵션(arms base,jqa,owl, reps 3)으로 실행하고 운영 사이트에 게시한다(`baseline_run`). 실패 단계가 있으면 systematic-debugging으로 재현 테스트부터 만든다.
- [ ] **Step 2:** `run-all.sh petclinic`을 다시 실행한다(`second_run`. shim 호출 0을 확인).
- [ ] **Step 3:** `uv run --project site-gen pytest tests/acceptance -v`로 전체 수용 스위트를 실행한다. 기대 결과는 REQ-030 외 전부 PASS다.
- [ ] **Step 4:** 누수 게이트를 확인한다. `docker ps -a --filter label=test-run`, `docker network ls --filter label=test-run`, `docker volume ls --filter label=test-run`이 모두 0이고, `git worktree list`에 TIA worktree가 없어야 한다.
- [ ] **Step 5:** 요구사항명세 매트릭스를 🟢로 갱신한다(테스트 이름 대조). `Coverage: 72/72`가 되어야 한다. README를 갱신하고 커밋한다(`docs: baseline run, matrix 100%, README`).

## 완료 정의

- 요구사항명세 대상 72개가 전부 🟢이고, 각 🟢가 실제 통과 테스트 이름과 대응한다.
- 수용 스위트 전체가 green이고 누수 게이트 0이다.
- 운영 사이트 두 곳에 기준 run과 두 번째 run이 보인다.
- PR 전 게이트: 스펙 준수 리뷰를 먼저 하고, 이어서 `pr-review-toolkit:code-reviewer` 품질 리뷰를 한다. Sonar(이 레포에 `sonar-project.properties`를 두면)도 돌리고 모든 지적을 분류한다.
