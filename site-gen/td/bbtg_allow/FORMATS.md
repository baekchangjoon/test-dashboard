# bbtg 스킬별 산출 형식 (S02 드라이버 기준)

bbtg 고정 커밋(`tools.pin.yaml`)의 7개 스킬 `cli.py --help`와 `SKILL.md`, 그리고 기준 SUT(<SUT>)에서 실제로 실행해
확인한 값이다. 모든 호출은 cwd = SUT 루트에서 bbtg venv 파이썬으로 실행하므로 `.bbtg/artifacts/`는 SUT 루트 아래에 생긴다.

| 스킬 | 호출 단위 | stdout | 아티팩트(`.bbtg/artifacts/` 아래) | raw의 기준 | 소스 원문이 들어갈 수 있는 필드 |
|---|---|---|---|---|---|
| inspect-stack | 1회 (`--path .`) | JSON(전체 스택 정보, 끝에 `[Artifact saved] <절대경로>` 한 줄이 붙는다. 이 줄은 stderr가 아니라 stdout 끝이다) | `dev-stack/<프로젝트>.md` (stdout과 같은 정보를 Markdown으로) | stdout JSON | `test_env.database.username/password`(build/설정의 기본값 문자열), `analysis_meta.timestamp`, `analysis_meta.scan_duration_ms`(비결정 값) |
| scan-test-assets | 1회 (`--path .`) | JSON(= `test-assets/scan.json`) | `test-assets/scan.json` | stdout JSON | 기존 테스트의 메서드 이름·표시 이름·엔드포인트(메타데이터이며 본문은 없다). 절대 경로 `project_root` |
| dependency-map | 컨트롤러마다 1회 (`--file`) | JSON 아님(`Dependency tree saved: ...` 한 줄) | `dependency-map/<Controller>.md` | Markdown 아티팩트(표와 제목만 JSON 추출, 코드 블록 제외) | 의존성 트리는 코드 블록이라 clean에서 버린다. `> 생성...` 인용 줄도 버린다 |
| find-external-calls | 컨트롤러마다 1회 (`--file`) | JSON(= 아티팩트) | `find-external-calls/<Controller>.json` | stdout JSON | `external_calls[].deep_inspection`(호출 코드 단서가 들어갈 수 있어 금지), `wiremock_strategy`(bbtg가 만든 설명문) |
| inspect-auth | 1회 (`--src-root src/main/java`, 아티팩트는 `--save-artifact`로 지정) | JSON | `inspect-auth/result.json`(지정했을 때만) | stdout JSON | `interceptor_sources[].source`(인터셉터 소스 전문), `llm_delegation_guide`(LLM에게 주는 지시문) |
| derive-test-data | 1회 (`--project-root . --scan src/main/java --ddl-path <runtime.ddl> --format json --save-artifact`) | JSON(= `test-data/java_scan.json`, 끝에 `[Artifact saved]` 줄은 stderr) | `test-data/java_scan.json` | stdout JSON | `file_path`(절대 경로), `where_clause`/`sql_delete`(어노테이션 문자열) |
| plan-tests | 컨트롤러가 호출하는 서비스 메서드마다 1회 (`--file <Service.java> --method <m>`) | JSON | `test-plan/<Class>_<method>.md`, `key-params/<Class>_<method>.json` | stdout JSON | `test_cases[].condition`(분기 조건식 조각), `expected`. key-params JSON의 `reasons[].detail`도 조건식이라 clean에는 넣지 않고 raw에만 둔다 |

## 정제 규칙 요약

- clean은 스킬마다 한 파일(`clean/<skill>.json`)이고, 형태는 `{"skill": ..., "results": [{"source": <키>, "data": ...}]}`다.
  `source`는 컨트롤러 파일 경로, `Class.method`, 또는 `.`이다.
- `.md`는 제목(레벨 포함)과 표(헤더 + 행)만 추출한다. 코드 블록, 인용문, 일반 문단, 목록은 버린다.
- 허용 스키마(`<skill>.schema.json`)는 `additionalProperties: false`이다. 키를 모르는 동적 맵(엔드포인트별 커버리지 등)은
  `patternProperties`로 값 스키마만 허용한다. 스키마에 없는 키는 값이 있어도 제거하고 경로별 개수를 센다.
- 스키마의 `x-forbidden-paths`는 "넣지 않기로 한 경로"의 선언 목록이다. `stripped_fields`는 이 선언과 실제 제거된 경로의 합집합이다.
- 절대 경로는 SUT 루트 상대로 바꾼다(`/private` 접두가 붙은 실경로 포함). 변환 뒤에도 홈·임시 디렉터리 절대 경로 패턴이
  남으면 정제는 실패한다(체크아웃 경로가 입력 해시에 새면 안 된다).
- 제거: `timestamp`, `scan_duration_ms`, Markdown의 생성 시각 줄.

## 알려진 한계

- `plan-tests`의 `condition`은 소스의 분기 조건식 조각이다(예: `req.nights() < 1 || ...`). 테스트 설계의 핵심 정보라 유지하지만,
  엄밀히는 소스 일부다. 길이를 제한하지 않고 형식만 문자열로 제한한다(검토 대상으로 보고서에 적는다).
- `dependency-map`의 의존성 트리는 코드 블록이라 clean에 남지 않는다. 엔드포인트 표와 핸들러 제목만 남는다.
- `--include-di-analysis`는 stdout에 JSON 두 덩어리를 구분선으로 이어 붙이므로 쓰지 않는다.

## 수정 1차(A1 재정) 반영

통제자 판정: 식별자(클래스·메서드·필드·파라미터 이름, 타입, HTTP 경로, enum 값, 불리언, 숫자)는 허용하고, SUT 소스의 식·문장 텍스트(조건식,
어노테이션 식 문자열, SQL 조각, 호출 패턴, formula)는 금지한다.

- plan-tests: `condition`, `expected`(분기 설명문에 조건식이 섞인다), `description`은 금지. `expected`가 `<X>Exception code=<N>`이면
  `expected_exception`/`expected_code`로 구조화해 남긴다.
- derive-test-data: `where_clause`, `sql_delete`, `formula`는 금지하고 `has_where_clause`, `has_sql_delete`, `has_formula` 불리언으로 대체. `enumerated`는 enum.
- find-external-calls: `pattern`, `url_source`는 enum 값만 허용, `variable_name`, `wiremock_strategy`, `deep_inspection`은 금지.
- inspect-stack: `test_env.database.url`(자격 증명이 섞일 수 있다), `username`, `password`는 금지.
- 정제 관문(fail closed, 해당 스킬 clean 미작성, 오류 문구는 JSON 경로만): (1) 식 문자 `(){};=<>!&|+*"'`를 포함한 12자 이상 문자열이 SUT `src/**/*.java`에
  공백 정규화 후 그대로 있으면 위반(HTTP 경로, 제네릭 타입 표기, 사람이 쓴 `display_name`은 예외), (2) `password=`/`token=` 등과 URL·JDBC 질의의 `user=`,
  `://user:pass@` 모양이 있으면 위반.
- 이 관문은 "소스에 그대로 있는 식"만 잡는다. bbtg가 만든 가공 문장은 못 잡으므로 위 스키마 금지가 1차 방어선이다.

## 수정 2차: scan-test-assets는 구조 메타데이터만

사람이 쓴 기존 IT의 의도(`@DisplayName`, 테스트 메서드 이름, 이름에서 뽑은 `intent_tokens`/`signatures`)는 생성 입력이 아니다.
`test_classes[].methods`는 금지(클래스별 `test_method_count`는 남김), `endpoint_coverage`는 엔드포인트별 개수만 남긴다.
지원/헬퍼 클래스와 재사용 멤버 시그니처, 태그 규약, 빌드 필터는 그대로 남는다. A1 관문의 `display_name` 예외는 없앴다.
