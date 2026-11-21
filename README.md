# test-dashboard

Spring Boot SUT(기본: spring-petclinic fork)를 대상으로 테스트·분석 파이프라인을 실행하고, 결과를 정적 대시보드 두 곳에 게시하는 PoC다. 대시보드 첫 화면에는 `dashboard.yaml`에 등록한 과제(GitHub 저장소)가 한 줄씩 나오고, 과제마다 GitHub CI와 SonarQube 값으로 정한 상태(위험, 주의, 측정 없음, 양호)가 붙는다. 파이프라인은 다음을 한 번에 실행한다.

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

운영 사이트에 올리지 않고 확인하려면 `TD_SITE_PREFIX`를 준다. 이때도 게시는 한다. 다만 S3 `_test/<prefix>`와 Lightsail `/srv/dashboard/_test/<prefix>` 아래에 올리고, 운영 첫 화면의 과제 목록에는 넣지 않는다. 접두를 준 실행은 `dashboard.yaml`을 읽지 않는다. 등록된 과제가 없는 것으로 보고, run이 있는 SUT를 SUT 이름의 과제로 그린다(`TD_DASHBOARD_CONFIG`로 설정 파일을 넘기면 그 파일을 쓴다. 그 파일의 `sut`가 가리키는 `sut.yaml`은 `TD_DASHBOARD_SUTS_DIR`에서 찾고, 지정하지 않으면 저장소의 `suts/`에서 찾는다). `/`처럼 구간이 없는 접두는 운영 루트로 보고 `dashboard.yaml`을 읽는다. 아예 게시하지 않으려면 `--only`로 S13을 뺀다.

```bash
TD_SITE_PREFIX=_test/my-try/ pipeline/run-all.sh petclinic          # _test/my-try/ 아래에 게시(운영 집계에서 빠진다)
pipeline/run-all.sh petclinic --only S00,S01,S08                      # 지정한 단계만 실행(나머지는 skipped, 게시 없음)
```

`--style`은 생성 테스트의 형식이다. 지금은 `cucumber`(기본값)만 지원한다. `--style junit`은 REQ-030이 연기돼 바로 오류로 끝난다.

### 실행 멈추기

- 앞에서 실행 중이면 Ctrl-C를 한 번 누른다. 현재 단계의 자식 프로세스를 끝내고 컨테이너 정리(`docker compose down -v`)와 Sonar 토큰 폐기를 마친 뒤 종료한다. 정리 중에 다시 누른 Ctrl-C는 무시된다.
- 백그라운드로 띄웠다면 프로세스 그룹 전체에 TERM을 보낸다: `kill -TERM -- -<pgid>`. `<pgid>`는 `ps -o pgid= -p <run-all의 pid>`로 찾는다. run-all의 pid 하나에만 TERM을 보내면 bash가 현재 단계 명령이 끝날 때까지 기다린 뒤에야 정리를 시작한다.

한 번에 하나의 run만 실행한다고 가정한다(게시 잠금은 있지만 컨테이너 포트와 `work/` 아래 공유 파일은 동시 실행을 고려하지 않았다). 실행이 끝난 뒤 남은 컨테이너가 없는지 확인하려면 다음을 실행한다. 출력이 헤더 한 줄뿐이면 정상이다.

```bash
docker ps -a --filter label=test-run
```

## 대시보드 과제와 화면

### 사이트 구성

| 주소 | 내용 |
|---|---|
| `index.html` | 첫 화면. 과제 표, 상태별 개수, 판정 규칙 각주, "테스트 실행 기록"(`_test/index.html`) 링크 |
| `projects.json` | 과제 목록과 상태 판정 결과(첫 화면과 같은 데이터) |
| `projects/<과제>/index.html` | 과제 페이지. 한눈에, 추이, 테스트, 커버리지, 위험 지점, 코드 품질, 생성 실험, 실행 이력 탭 |
| `suts/<sut>/index.html` | 그 SUT와 이어진 과제 페이지로 보내는 안내 페이지 |
| `suts/<sut>/runs/<runId>/index.html` | run 페이지와 그 run의 리포트 |

### `dashboard.yaml`로 과제 등록하기

과제는 저장소 루트의 `dashboard.yaml`에 직접 적는다. GitHub 계정의 저장소를 자동으로 읽어 오지 않는다.

```yaml
projects:
  - name: spring-petclinic
    repo: baekchangjoon/spring-petclinic
    sut: petclinic            # 파이프라인을 돌리는 과제만 적는다. suts/petclinic/sut.yaml이 있어야 한다
  - name: VcsStatistics
    repo: baekchangjoon/VcsStatistics
    sonarKey: vcsstatistics   # SonarQube 프로젝트 키가 저장소 이름과 다를 때만 적는다
```

- `name`은 영문자, 숫자, `.`, `_`, `-`만 쓰고, 대소문자를 무시하고 겹치지 않아야 한다. `repo`도 겹치지 않아야 한다.
- 공개 저장소만 화면에 나온다. 비공개이거나 찾을 수 없는 저장소는 수집에서 빠지고, 이미 게시된 그 과제의 파일은 다음 게시에서 지워진다.
- 등록하지 않은 SUT라도 완료된 run이 있으면 SUT 이름의 과제로 나온다. 이 이름이 등록한 과제 이름과 겹치면 설정 오류다.

설정이 틀리면 인덱스를 만들지 않고 어디가 왜 틀렸는지 낸다. 게시하기 전에 빈 디렉터리에 그려 보면 설정을 확인할 수 있다(수집 스냅숏이 없으므로 과제 표는 비어 있다).

```bash
uv run --project site-gen python -m td.site.index "$(mktemp -d)" --config dashboard.yaml   # 틀리면 종료 코드 2와 틀린 위치
```

### 상태 규칙과 탭·열 바꾸기

`dashboard.yaml`의 `status`, `home`, `project` 절이 화면을 정한다. 세 절은 생략할 수 있고, 생략한 절은 기본값(설계 문서 §6.2의 예시, 지금 저장소의 `dashboard.yaml`과 같은 값)을 쓴다. 절을 적으면 그 절 전체를 적은 내용으로 바꾼다(절 안의 일부 키만 덮어쓰지 않는다).

- `status.rules`: 규칙 하나는 `{level, when, reason}`이다. `when`은 `{metric, op, value}` 하나이거나 `{all: [...]}`(모두 참)이고, `op`는 `eq, ne, lt, le, gt, ge` 가운데 하나다. 걸린 규칙 가운데 `status.order`에서 가장 앞선 수준이 그 과제의 상태가 된다. 규칙이 쓰는 값이 없으면 그 규칙은 걸리지 않는다.
- `status.none.allMissing`: 여기 적은 값이 모두 없으면 그 과제는 "측정 없음"이다.
- `home.columns`, `home.summary`: 첫 화면의 열과 위쪽 요약 칸. 적은 순서대로 나오고, 빼면 화면에서 빠진다.
- `project.tabs`, `project.trend`, `project.headline`: 과제 페이지의 탭, 추이 차트에 그릴 값, 상태가 "양호"일 때 쓰는 결론 문장.

규칙과 열에 쓸 수 있는 값의 이름(`ci.successRate`, `sonar.gate`, `tests.passRate` 등)은 설계 문서 `docs/superpowers/specs/2026-11-22-dashboard-ui-design.md` §6.2의 지표 카탈로그에 있다. 카탈로그에 없는 이름을 쓰면 설정 오류다. 열이나 탭의 종류를 새로 만드는 것은 코드를 바꿔야 한다.

### run 없이 과제 목록 갱신하기

```bash
pipeline/publish-index.sh
```

파이프라인 run 없이 과제 수집과 인덱스(첫 화면, `projects.json`, 과제 페이지, SUT 안내 페이지)만 다시 만들어 두 사이트에 올린다. 설정에서 빠졌거나 공개가 아닌 과제의 `projects/<과제>/`는 S3와 Lightsail에서 지운다. 결과(상태, 사유, 호스트별 결과)는 `publish-log/index.json`에 남는다. 종료 코드는 상태가 `failed`일 때만 1이다. 수집 문제, CloudFront나 Lightsail 실패는 `degraded`이고 종료 코드는 0이다.

- 파이프라인을 돌리지 않는 과제의 값은 이 명령(또는 S13)을 돌릴 때만 새로 읽힌다.
- `dashboard.yaml`을 고쳤거나 화면 코드(`site-gen/td/site/`)만 바꾼 뒤에도 이 명령으로 다시 게시한다. 게시된 run 디렉터리는 바꿀 수 없어서, 화면 코드를 바꾼 뒤 옛 run을 `S13-publish.sh`로 다시 올리면 run 페이지 내용이 달라져 게시가 거부된다(`ContentConflict`).
- `TD_SITE_PREFIX`를 주면 그 접두 아래만 갱신한다.

### 수집이 쓰는 것

게시(S13과 `publish-index.sh`)는 인덱스를 만들기 전에 `pipeline/collect.sh`로 과제마다 GitHub와 SonarQube 값을 읽어 `projects/<과제>/snapshots/<날짜>.json`에 남긴다.

- GitHub: `gh api`로 저장소 정보, 기본 브랜치의 최근 Actions 실행 30개, 최신 커밋의 검사 결과를 읽는다. `gh auth login`이 되어 있어야 한다.
- SonarQube: S11과 같은 방식으로 Lightsail 서버에 SSH로 들어가 Sonar DB에 2시간짜리 임시 토큰(`td-collect-<시각>-<난수>`)을 넣고, 수집이 끝나면 지운다. `infra/local.env`의 `TD_LIGHTSAIL_IP`와 `TD_SSH_KEY_PATH`가 필요하다. 토큰을 지우지 못하면 경고를 내고 수집은 `degraded`가 된다(토큰은 2시간 뒤 만료된다). Sonar를 읽을 과제가 없으면 토큰을 만들지 않는다.
- SUT와 이어진 과제에 완료된 run이 있으면 그 과제의 Sonar 값은 수집하지 않고 최신 run의 S11 결과를 쓴다.
- 읽지 못한 값은 0으로 채우지 않고 화면에 "측정 없음"과 사유로 나온다. 수집 전체가 5분을 넘으면 남은 과제는 읽지 않는다(`TD_COLLECT_BUDGET_SEC`로 초 단위로 바꿀 수 있다). 수집에 문제가 있어도 인덱스는 있는 스냅숏으로 다시 만들어 게시하고, 게시 상태는 `degraded`다.

### 옛 run 페이지

이미 게시된 run 디렉터리는 바뀌지 않으므로, 화면 재설계 전에 게시된 run의 페이지와 리포트는 옛 모양 그대로 남는다(옛 스타일 `static/site.css`를 계속 쓴다). 새로 게시하는 run부터 새 모양이다. 옛 run 페이지의 SUT 링크는 `suts/<sut>/index.html`을 거쳐 지금의 과제 페이지로 이어진다.

### 두 게시를 동시에 돌리지 않는다

S13과 `publish-index.sh`는 같은 접두에서 같은 게시 잠금을 잡는다. 하나가 도는 동안 다른 게시를 시작하면 기다리지 않고 잠금 정보(attemptId, 소유자, 획득 시각)와 함께 실패한다. 앞 게시가 비정상으로 끝나 잠금이 남았다면, 출력된 안내대로 `--force-unlock <attemptId>`로 푼다.

## 사전 요구사항

| 항목 | 용도 |
|---|---|
| macOS, Docker | SUT 컨테이너 실행(S01, S07, S10) |
| JDK 17과 JDK 21(`/usr/libexec/java_home -v 17`, `-v 21`로 찾는다) | SUT 빌드·실행은 17, hotspot-analysis는 21 |
| Python 3.12, [uv](https://docs.astral.sh/uv/) | `site-gen`(파이프라인 Python 모듈), bbtg 전용 venv |
| `jq`, `git`, `rsync`, `ssh` | 단계 스크립트, Lightsail 미러 |
| Terraform | `infra/static/apply.sh` |
| AWS 자격 증명(boto3가 읽는 기본 자격) | S3 업로드, CloudFront 무효화, Route53 조회 |
| `gh` CLI 로그인(`gh auth login`) | 비공개 저장소 `baekchangjoon/bbtg`를 받는다(S00). 게시할 때 과제의 GitHub 값을 읽는다 |
| `claude` CLI 로그인 | S05·S06 생성(`pipeline/config.yaml`의 `llm.model`, `TD_LLM_MODEL`로 바꿀 수 있다) |
| Lightsail 서버 SSH 키(`TD_SSH_KEY_PATH`) | dash 사이트 게시, Sonar 토큰 관리(S11, 게시할 때의 수집) |

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
| S10 | `S10-tia.sh` | TIA(base = first-parent `HEAD~10`) | `S10/tia/tia.html`, `S10/tia.db` |
| S11 | `S11-sonar.sh` | 전용 프로젝트 `spring-petclinic-td` 분석과 결과 export | `S11/sonar/sonar.json`, `S11/sonar/sonar.html` |
| S12 | `S12-compare.sh` | arm 비교 지표와 판정 | `S12/compare/compare.json`, `S12/compare/compare.html` |
| S13 | `S13-publish.sh` | S3 게시, 과제 수집과 인덱스 재생성, CloudFront 무효화, Lightsail 미러 | `stages/S13.json` |

단계 상태는 `passed`, `failed`, `degraded`, `skipped` 중 하나이고 `stages/<ID>.json`에 남는다. `run-all.sh`의 종료 코드는 S00이나 S13이 실패하면 1, 다른 단계가 실패하면 2, 실패가 없으면 0이다.

### 주요 옵션

```
pipeline/run-all.sh <sut> [--sut-file F] [--only IDS] [--arms base,jqa,owl[,det]] [--reps 1..9] [--regenerate]
```

- `--arms`: 실행할 arm 목록(기본 `base,jqa,owl`). `det`를 더하면 LLM 없이 bbtg 조건식과 jQA 그래프(보강 질의 `S03/ontology-jqa-ext.json` 포함)만으로 케이스를 펼치는 결정적 arm이 함께 돈다. det는 `--reps`와 무관하게 1회만 생성하고, 비교 화면에는 참고 열(입력 체제: LLM 없음, 조건식 포함)로 나오며 판정 계산에서는 빠진다. 설계: `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md`.

- `--reps`: arm별 생성 반복 횟수(기본 3). 줄이면 `compare.html`에 실제 횟수가 표시된다.
- `--regenerate`: 같은 입력이어도 새 generation(`-g<n>`)을 추가한다. 기존 스냅샷은 바꾸지 않는다. det arm은 같은 genId로 다시 만들고, 내용이 달라졌으면 `checksum-changed` 경고를 남긴다.
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
- 알려진 한계: 호스팅 크롤 테스트(`test_hosting.py`의 크롤 테스트와 `test_baseline.py`의 같은 검사)는 시작 페이지에서 너비 우선으로 호스트당 400쪽까지만 확인한다. 운영 사이트는 이보다 커서 크롤이 사이트 전체를 돌지 않는다. 과제 페이지와 그 아래 run 페이지는 깊이 2라 이 범위 안에 든다.

요구사항과 테스트의 대응은 `docs/superpowers/requirements/2026-11-18-test-dashboard-poc-requirements.md`(PoC)와 `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md`(화면 재설계)의 추적 매트릭스에 있다.

## 문서

- 설계: `docs/superpowers/specs/2026-11-18-test-dashboard-poc-design.md`
- 요구사항명세: `docs/superpowers/requirements/2026-11-18-test-dashboard-poc-requirements.md`
- 구현 계획: `docs/superpowers/plans/2026-11-18-test-dashboard-poc.md`
- 화면 재설계: 설계 `docs/superpowers/specs/2026-11-22-dashboard-ui-design.md`, 요구사항명세 `docs/superpowers/requirements/2026-11-22-dashboard-ui-requirements.md`, 구현 계획 `docs/superpowers/plans/2026-11-22-dashboard-ui.md`
