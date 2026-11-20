# test-dashboard

Spring Boot SUT(기본: spring-petclinic fork)를 대상으로 테스트·분석 파이프라인을 실행하고, 결과를 정적 대시보드 두 곳에 게시하는 PoC다. 파이프라인은 다음을 한 번에 실행한다.

- 기존 블랙박스 IT 실행과 테스트별 커버리지 수집
- bbtg 정적 분석, jQAssistant 온톨로지, LLM으로 보강한 OWL 온톨로지
- 세 가지 입력 조건(arm)으로 BDD E2E 테스트 생성과 실행
- hotspot, TIA, SonarQube 리포트
- arm 비교 판정과 게시

## 빠른 시작

사전 요구사항(아래)을 갖춘 뒤 다음 순서로 실행한다.

```bash
# 1. 인프라 식별자 파일을 만든다(gitignore 대상, 값은 커밋하지 않는다)
cp infra/local.env.example infra/local.env   # 실제 값으로 채운다

# 2. 정적 호스팅(S3 + CloudFront + ACM + Route53 reports 레코드)을 만든다. 처음 한 번만 실행한다.
infra/static/apply.sh

# 3. 기존 Lightsail 서버의 Caddy에 dash.<domain> 정적 사이트를 추가한다. 처음 한 번만 실행한다.
#    (서버는 SonarQube가 이미 돌고 있는 공유 서버다. 실패하면 Caddyfile과 DNS를 이전 상태로 되돌린다.)
infra/lightsail/apply.sh

# 4. 파이프라인 전체를 실행하고 두 사이트에 게시한다
pipeline/run-all.sh petclinic
```

마지막 줄이 runId다. 결과는 로컬 `work/runs/<runId>/`와 다음 두 사이트에서 볼 수 있다(`<domain>`은 `infra/local.env`의 `TD_DOMAIN`).

- `https://reports.<domain>/` (S3 + CloudFront)
- `https://dash.<domain>/` (Lightsail 서버의 Caddy)

게시하지 않고 확인하려면 `TD_SITE_PREFIX`를 주거나 S13을 뺀다.

```bash
TD_SITE_PREFIX=_test/my-try/ pipeline/run-all.sh petclinic          # _test/my-try/ 아래에 게시(운영 집계에서 빠진다)
pipeline/run-all.sh petclinic --only S00,S01,S08                      # 지정한 단계만 실행(나머지는 skipped)
```

## 사전 요구사항

| 항목 | 용도 |
|---|---|
| macOS, Docker | SUT 컨테이너 실행(S01, S07, S10) |
| JDK 17과 JDK 21(`/usr/libexec/java_home -v 17`, `-v 21`로 찾는다) | SUT 빌드·실행은 17, hotspot-analysis는 21 |
| Python 3.12, [uv](https://docs.astral.sh/uv/) | `site-gen`(파이프라인 Python 모듈), bbtg 전용 venv |
| `jq`, `git`, `rsync`, `ssh` | 단계 스크립트, Lightsail 미러 |
| Terraform | `infra/static/apply.sh` |
| AWS 자격 증명(boto3가 읽는 기본 자격) | S3 업로드, CloudFront 무효화, Route53 조회 |
| `gh` CLI 로그인(`gh auth login`) | 비공개 저장소 `baekchangjoon/bbtg`를 받는다(S00) |
| `claude` CLI 로그인 | S05·S06 생성(`pipeline/config.yaml`의 `llm.model`, `TD_LLM_MODEL`로 바꿀 수 있다) |
| Lightsail 서버 SSH 키(`TD_SSH_KEY_PATH`) | dash 사이트 게시, Sonar 토큰 관리(S11) |

`aws` CLI는 쓰지 않는다. 모든 AWS 호출은 boto3로 한다.

### 재현성 한계: bbtg는 비공개 저장소다

S00은 `tools.pin.yaml`에 고정한 커밋의 bbtg를 `gh`로 받는다. 이 저장소에 접근 권한이 없으면 S00이 실패하고 run 전체가 중단된다(종료 코드 1). 같은 결과를 재현하려면 저장소 접근 권한이 필요하다. 생성 입력에 들어가는 bbtg 산출물은 정제된 형태로 각 run의 `S06/bundles/<arm>/`에 보존되므로, 권한이 없어도 기존 run의 입력은 확인할 수 있다.

## 단계

| ID | 스크립트 | 하는 일 | 주요 산출물(`work/runs/<runId>/`) |
|---|---|---|---|
| S00 | `S00-prepare.sh` | SUT 전체 clone과 커밋 고정, 도구 받기와 sha256 검증, SUT 빌드, `claude` 플래그 확인 | `tools.lock`, `S00/` |
| S01 | `S01-blackbox.sh` | 기존 블랙박스 IT를 컨테이너 SUT에 실행하고 테스트별 `.exec` 수집 | `S01/blackbox/` |
| S02 | `S02-bbtg.sh` | bbtg 7개 스킬 실행과 산출물 정제 | `S02/bbtg/` |
| S03 | `S03-jqa.sh` | jQAssistant 스캔과 온톨로지 추출 | `S03/ontology-jqa.json` |
| S05 | `S05-owl-build.sh` | 결정적 OWL 골격 + LLM 보강(스냅샷 재사용) | `S05/ontology-owl.ttl`, `owl-gen.json` |
| S04 | `S04-onto-viz.sh` | 온톨로지 HTML(오프라인 동작). S05 뒤에 실행한다 | `S04/` |
| S06 | `S06-bdd-gen.sh` | arm(base, jqa, owl) × 반복(기본 3)으로 Cucumber 시나리오 생성 | `e2e/generated/<sut>/<arm>/<genId>/`, `S06/bdd-gen.json` |
| S07 | `S07-e2e.sh` | 생성한 시나리오를 컨테이너 SUT에 실행 | `S07/<genId>/` |
| S08 | `S08-coverage.sh` | 스위트별 귀속·집계 커버리지와 TC별 화면 | `S08/coverage.html` |
| S09 | `S09-hotspot.sh` | hotspot 리포트 | `S09/hotspot/` |
| S10 | `S10-tia.sh` | TIA(base = first-parent `HEAD~10`) | `S10/tia.html`, `S10/tia.db` |
| S11 | `S11-sonar.sh` | 전용 프로젝트 `spring-petclinic-td` 분석과 결과 export | `S11/sonar.json` |
| S12 | `S12-compare.sh` | arm 비교 지표와 판정 | `S12/compare.json`, `compare.html` |
| S13 | `S13-publish.sh` | S3 게시, 인덱스 재생성, CloudFront 무효화, Lightsail 미러 | `stages/S13.json` |

단계 상태는 `passed`, `failed`, `degraded`, `skipped` 중 하나이고 `stages/<ID>.json`에 남는다. `run-all.sh`의 종료 코드는 S00이나 S13이 실패하면 1, 다른 단계가 실패하면 2, 실패가 없으면 0이다.

### 주요 옵션

```
pipeline/run-all.sh <sut> [--sut-file F] [--only IDS] [--arms base,jqa,owl] [--reps 1..9] [--regenerate]
```

- `--reps`: arm별 생성 반복 횟수(기본 3). 줄이면 `compare.html`에 실제 횟수가 표시된다.
- `--regenerate`: 같은 입력이어도 새 generation(`-g<n>`)을 추가한다. 기존 스냅샷은 바꾸지 않는다.
- 생성 결과는 입력 해시(번들, 프롬프트, 모델)로 스냅샷해 커밋한다. 입력이 같으면 다음 run은 `claude`를 부르지 않고 스냅샷을 재사용한다.

### 다른 SUT 추가

`suts/<name>/sut.yaml`(스키마: `site-gen/td/schemas/sut.schema.json`)과 기대 목록 파일을 만들고 `pipeline/run-all.sh <name>`으로 실행한다. 파이프라인 코드에는 SUT 이름이 들어가지 않는다. 예: `tests/fixtures/mini-sut/`.

## 결과 해석에서 알아 둘 한계

- 테스트별 커버리지는 pjacoco가 `HttpServlet#service`에서 시작한다. Spring Security 필터 체인에서 거절된 요청(예: 인증 실패 테스트)은 테스트에 귀속되지 않고 집계 커버리지에만 남는다. petclinic에서 이런 블랙박스 TC 8개는 `suts/petclinic/expected-tests.yaml`의 `no_attribution`에 적혀 있다.
- arm 비교는 arm마다 generation 3개라서 통계적 결론이 아니라 탐색적 관찰이다. OWL 온톨로지는 jQA 결과에서 파생되고, 생성 모델이 petclinic을 사전에 알고 있을 수 있다(`compare.html` 한계 서술 참고).
- 생성 시나리오가 SUT 요청 본문 형식을 잘못 만들어 400을 받는 경우도 실험 결과로 그대로 기록한다.

## 수용 테스트

```bash
uv run --project site-gen playwright install chromium        # 처음 한 번
uv run --project site-gen python tests/acceptance/run_baseline.py   # 기준 run과 두 번째 run(운영 게시 2회)
uv run --project site-gen pytest tests/acceptance -v
```

- `run_baseline.py`는 기준 run과 두 번째 run을 실행해 Docker 자원 전후 목록, GradleDaemon PID, 게시 객체 ETag, `claude` 호출 수를 `work/acceptance-session.json`에 남긴다. `@pytest.mark.baseline` 테스트는 이 파일을 읽어 검사하고, 파일이 없으면 실패한다. 디버깅할 때는 `--prefix _test/<id>/ --session-file work/<id>.json`으로 운영 경로와 분리한다.
- 다른 테스트는 장애 주입 실행과 단계별 실행을 `_test/<sessionId>/` 접두에 게시한다(보존한다).
- 전제(AWS, SSH, Docker, `claude`)가 없으면 skip하지 않고 실패한다. 전체 실행은 40분 이상 걸린다.
- 테스트 실행 중에는 같은 맥에서 다른 Docker 작업을 하지 않는다(자원 누수 검사가 전후 차이를 본다).

요구사항과 테스트의 대응은 `docs/superpowers/requirements/2026-11-18-test-dashboard-poc-requirements.md`의 추적 매트릭스에 있다.

## 문서

- 설계: `docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md`
- 요구사항명세: `docs/superpowers/requirements/2026-11-18-test-dashboard-poc-requirements.md`
- 구현 계획: `docs/superpowers/plans/2026-11-18-test-dashboard-poc.md`
