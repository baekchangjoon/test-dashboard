# det 조합 시각화 설계

> 상위 설계: `docs/superpowers/specs/2026-11-22-deterministic-arm-design.md`(det arm). 이 문서는 그 위에 얹는 별도 작업이다.
> 브랜치: `feat/det-viz`(기반 `feat/det-arm` df010de). pairwise 작업(`feat/det-pairwise`)과 따로 검증한다.
> 경로 표기: `td/…`는 `site-gen/td/…`, `site/static/…`는 `site-gen/td/site/static/…`를 줄여 쓴 것이다.

## 1. 의도

det arm은 bbtg 조건식과 jQA 그래프에서 케이스 80개를 만들었다. 지금은 결과가 숫자(80, 생성 불가 50, 이론 모수 46,689)로만 보인다.
사용자는 다음을 한 화면에서 따라가고 싶어 한다.

- 소스(어느 메서드의 어떤 조건식, 어떤 그래프 노드)에서 어떤 팩터(필드)와 클래스가 나왔는가
- 그 클래스들이 어떻게 조합되어 어떤 케이스가 되었고, 케이스는 통과했는가
- 어떤 조합이 비어 있는가(생성 불가 사유가 있는 칸, 사유도 없이 빈 칸)

## 2. 목표 / 비목표 / 반목표

- 목표
  - G1: 생성기가 팩터·클래스·케이스↔칸 대응을 기계가 읽는 파일(`factors.json`)로 낸다.
  - G2: run마다 `det.html` 한 장으로 추적 그래프, 클래스 격자, 조합(2-way) 히트맵을 보인다.
  - G3: 화면의 모든 숫자는 `factors.json`·`cases.json`·S07 결과에서 다시 계산할 수 있다.
- 비목표
  - 케이스 생성 로직 변경(80개 그대로, `cases.json` 바이트 동일).
  - 이론 상한 공식 변경(사용자 미결정). 격자는 현재 공식의 클래스를 그대로 보인다.
  - pairwise 생성(별도 브랜치).
- 반목표
  - 화면이 생성기와 다른 클래스 계산을 따로 갖는 것(숫자가 어긋나면 실패다). 클래스 목록은 생성기의 모수 계산과 같은 함수에서 나온다.
  - 게시 사본에 로컬 경로·인프라 식별자가 들어가는 것.

## 3. 현재 구조(바뀌는 곳)

- `td/detgen/derive.py::_Deriver._universe`가 필드별 클래스 집합을 계산하지만 개수만 남긴다.
  클래스 키는 `(op, str(value), length, date)`, count는 `("count",)`, 변환 못 한 원자식은 `("raw", …)`다.
- 초안(`_Draft`)은 `_fill`에서 원자식별로 위반값/유효 경계를 넣지만, 어느 클래스를 밟았는지 기록하지 않는다.
- `td/detgen/render.py::render`가 generation 디렉터리에 `features/`, `glue/`, `cases.json`을 쓴다.
- `td/compare.py::_deterministic`가 `results.summarize`로 det 블록을 만들고 `compare.html`에 표로 보인다.
- 사이트: S12 산출물 `compare/`가 게시되고 `RERENDER["compare/"]`가 게시 시 다시 그린다. Cytoscape는 `site/static/vendor`에 이미 있다(온톨로지 화면).

## 4. 접근

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A (선택) | 생성기가 `factors.json`을 내고, S12가 결과를 합쳐 `compare/det.html`을 그린다 | 클래스 정의가 생성기 한 곳. 결정적. 게시 경로 재사용 | 생성기 소스(`td/detgen/*.py`)가 바뀌어 `source_checksum`→det 키→genId가 한 번 바뀐다(재생성, LLM 없음) |
| B | 화면 쪽에서 `cases.json` 값만 보고 클래스를 역추론 | 생성기 무변경 | 클래스 판정 로직이 둘로 갈라져 숫자가 어긋날 위험(반목표) |
| C | 별도 단계(S12b) 신설 | 분리가 명확 | 단계·상태 기계·게시 매핑까지 늘어 비용 대비 이득 없음 |

A를 고른다. B는 반목표에 걸리고, C는 S12가 이미 det 블록을 다루므로 단계를 늘릴 이유가 없다.
결합·화면 모듈은 `td/detviz.py`로 `td/detgen/` 밖에 둔다. 화면을 고쳐도 det 키가 바뀌지 않게 하기 위해서다.

## 5. 설계

### 5.1 클래스 레지스트리(생성기 내부 변경)

지금은 raw 클래스(`ep.extra_classes`)와 count(`ep.count_fields`)가 출처 주소 없이 저장된다. 출처를 잃지 않도록 엔드포인트에
클래스 레지스트리를 둔다.

- `Endpoint.class_sources: dict[(field, classKey), set[addr]]`와 `Endpoint.class_kinds: dict[(field, classKey), set[kind]]`.
  `_disjunct`(변환된 원자식, 변환 못 한 원자식의 raw 키), `_contradictions` 처리(모순 항목), count 인자 기록 지점에서 함께 채운다.
  count 인자 기록(`Constraints.con`)에는 주소를 넘길 수 없으므로, `_disjunct`가 원자식 순회 중 count 원자식의 필드에 주소를 기록한다.
- 클래스 키는 지금 `_universe`의 키와 같다: 변환된 원자식 `(op, str(value), length, date)`, count `("count",)`, 그 밖 `("raw", …)`.
  `_field_classes(ep, fld) -> dict[classKey, (kind, sources)]`(valid 제외) 하나를 `_universe`(`1 + len`)와 `factors.json`(valid를 앞에 붙인 목록)이 같이 쓴다.
  필드 식별은 기존 매칭 의미를 그대로 둔다(개수 불변). 클래스 id·칸 키의 필드 문자열은 `loc.name`(예: `body.nights`)이다.
  출처 주소는 `rstrip("~")` 후 기록한다. 모순 항목의 키는 지금처럼 raw 꼴 `("raw", op, str(value), length)`이고 kind는 `contradicted`다.
  미변환 원자식의 raw 키를 칸 계산에 넘기도록 `_disjunct`는 원자식별 `(Con | 사유, rawKey | None)`을 돌려준다.
  미해결 count의 필드는 `Constraints.con` 호출 전후 `ep.count_fields` 차이로 얻어 그 원자식 주소와 함께 기록한다.
  개수 불변은 E3·E4로 지킨다(레지스트리는 기존 집합의 상위 정보이고 키 집합은 같아야 한다).
- `kind` 결정 규칙(우선순위 순):

  | 조건 | kind |
  |---|---|
  | count 키 | `count` |
  | 모순(input-contradiction) 항목에서 온 키 | `contradicted` |
  | 오류 항목(예외 기대)의 변환된 원자식 | `violation` |
  | 분기 진입 항목의 변환된 원자식(오류 항목에는 없음) | `branch` |
  | 변환 못 한 원자식(필드만 앎) | `raw` |

  한 키가 여러 조건에 걸리면 표의 위쪽이 이긴다. 필드마다 `kind: "valid"` 클래스 1개가 맨 앞에 붙는다. 그 classKey는 `("valid",)`이다.
- 클래스 id: `"c" + sha256(json.dumps([endpoint, field, list(classKey)], ensure_ascii=False))[:12]`(field = `f"{loc}.{name}"`). 사람이 읽는 `label`은 따로 둔다
  (예: `< 1`, `length < 1`, `== null`, `count ≥ 2`, `raw: isAfter(today)`). 조건식의 `||`와 구분자가 충돌하지 않는다.

### 5.2 케이스·슬롯 칸 규칙

칸 계산은 `_fill`과 분리한 함수 `_cells(ep, draft, cons, flip) -> CellInfo`로 한다. 입력은 초안(규칙, enum 대상 `targets`, 우선 건수),
변환된 `Con` 목록(변환 못 한 원자식은 raw 키), 뒤집은 원자식 위치다. `CellInfo`는 `cells, boundaries, stored, enumValue`를 담는다. 생성된 초안과 생성 불가 초안 모두에 적용한다(사유가 있어도 변환된 원자식이 있으면 칸이 있다).

| 원자식 상황 | 그 필드의 칸 |
|---|---|
| 위반값을 넣은 원자식 | 그 원자식의 클래스 |
| 유효 경계로 뒤집은 원자식(flip) | `valid`, `boundaries`에 그 원자식 클래스 |
| branch-entry(조건 참) | 그 원자식의 클래스(kind `branch`) |
| count 위반 | 그 필드의 `count` 클래스 |
| count 유효 경계(priors = C-1) | `valid`, `boundaries`에 `count` 클래스 |
| rel | `side[0]` 필드에만 칸을 적고 나머지 side 필드는 적지 않는다(값은 `cases.json` `assumes`로 추적) |
| 저장 상태(`stored`) 원자식 | 요청 필드 칸이 아니다. 위반으로 넣었으면 `stored: [classLabel]`, 유효 경계로 뒤집었으면 `storedBoundaries: [classLabel]`로 남긴다 |
| 변환 못 한 원자식(생성 불가 슬롯) | 그 필드의 raw 클래스 |
| enum-value | `valid`, `enumValue: {field, constant}` |
| 칸에 없는 필드 | `valid`로 해석(baseline 값) |

- `inModel`: 케이스를 필드 클래스 튜플로 투영할 수 있으면 `true`다.
  - `true`: violation, valid-boundary, baseline-valid, enum-value, branch-entry, happy(모든 필드 valid).
  - `false`: auth(요청을 보내지 않는 인증 차원), no-data(경로 변수에 없는 id, 공식에 클래스 없음), empty-body(본문 자체 없음),
    filter-empty(query 필드에 모델에 없는 센티널 값). `outReason`에 이 사유를 남긴다.
- 병합(`_dedupe`): 살아남은 케이스의 `boundaries`는 병합된 초안들과의 합집합, `mergedRules`에 병합된 규칙을 적는다.
  칸 비교는 적지 않은 필드를 valid로 채운 뒤 한다. 다르면 살아남은 쪽을 유지하고 `cellConflicts`에 `{field, kept, merged, mergedRule}`로 적는다(같은 요청이므로 정상이라면 비어 있다. 테스트로 확인).
  `inModel`은 살아남은 케이스 규칙으로 정한다.
- 생성 불가 슬롯의 위치: `_skip`이 항목과 함께 칸 정보(`cells`, `draftKey`)를 내부 쌍으로 들고, `cases.json` `unresolved`와
  같은 정렬(`source, rule, reason, endpoint`, 안정 정렬)을 쌍 목록에 적용한다. 그래서 `index`가 `cases.json` 위치와 일치한다.
  초안을 거치지 않고 건너뛴 항목(unparsed, no-condition, param-name-unknown, input-missing, 초안 이전 no-body-schema 등)은
  `draftKey: null`, `cells: {}`다. 초안에서 온 항목은 `draftKey: [d_index, kind, position]`(초안 `key`의 뒤 세 값)이다.
  `cases.json`에 쓰는 항목에는 칸 정보를 넣지 않으므로 순서와 내용이 바뀌지 않는다.
- 칸은 의도한 클래스 기준이다. 한 값이 다른 클래스도 함께 위반할 수 있다(`also-violates:` 가정). 현 스냅샷에는 0건이다.

- pairwise 케이스(det pairwise 브랜치 병합 후, REQ-215): 초안 경로가 아니라 PICT 행이므로 `_cells`를 쓰지 않고,
  값마다 그 필드의 원자식(오류·분기, `~` 제외)을 `Constraints.holds`로 평가해 참이면 그 클래스, 유효 경계값과 같으면 valid + `boundaries`, 그 밖은 valid로 둔다.

### 5.3 `factors.json`(generation 디렉터리, 스키마 `td/schemas/factors.schema.json`)

```json
{
  "version": 1,
  "endpoints": [
    {"endpoint": "POST /api/reservations", "methods": ["ReservationService#create"],
     "fields": [
       {"field": "body.nights", "classes": [
          {"id": "c0123456789ab", "kind": "valid", "label": "유효", "sources": []},
          {"id": "c…", "kind": "violation", "label": "< 1", "sources": ["<addr>"]}]}]}
  ],
  "sources": {"<addr>": {"kind": "plan", "methods": ["ReservationService#create"], "condition": "…", "expected": "…"}},
  "cases": {"<caseId>": {"rule": "violation", "cells": {"body.nights": "c…"}, "boundaries": [], "stored": [],
                         "enumValue": null, "inModel": true, "outReason": null, "mergedRules": [], "cellConflicts": []}},
  "unresolved": [{"index": 0, "source": "<addr>", "rule": "branch-entry", "reason": "unresolved-operand", "draftKey": [0, 0, 0],
                  "cells": {"body.x": "c…"}}]
}
```

- `methods`: 엔드포인트에 대응한 계획의 `클래스명#메서드명` 목록(0개 이상).
- 출처 kind별 필드:

  | kind | 주소 형태 | condition | expected | methods |
  |---|---|---|---|---|
  | plan | `plan-tests-*.json#i@sha` | 계획 항목 조건식 | 계획 항목 기대 | 1개 |
  | keyparams | `*.json#p.r@sha` | 분기 사유 원문 | null | 1개 |
  | graph | `graph:<노드 id>` | null | null | [] |
  | harness | `harness:<키>` | null | null | [] |
  | input | `input:<이름>` | null | null | [] |

  원문은 det 번들(`plans.json`, `keyparams.json`)에서만 읽는다(번들 밖 금지, 상위 REQ-112). 소스 줄 번호는 번들에 없어 싣지 않는다.
- 결정성: `sort_keys=True`, 목록은 엔드포인트 라벨 → 필드 순서(모수 계산과 같은 순서) → 클래스 id 순.
- `cases.json`·feature는 바꾸지 않는다. 생성기 소스가 바뀌므로 genId가 바뀌고 새 스냅샷 디렉터리가 생긴다.

### 5.4 결과 결합과 `det.html`(S12)

- `td.detviz.build(gen_dir, s07_dir) -> dict`가 `det-viz.json` 내용을 만든다(스키마 `td/schemas/det-viz.schema.json`).
  - `factors.json` 전체 + 케이스별 `{status, observed, expectStrict, endpoint}` + `aggregates` + `trace`.
  - `trace`(화면 추적 보조, `cases.json`에서 옮김): `caseSources`(케이스 id → 출처 주소, `~` 제거)와
    `unresolvedEndpoints`(`factors.unresolved[i]`의 엔드포인트, 없으면 null). factors.json에는 케이스의 출처와 칸이 빈
    생성 불가 슬롯의 엔드포인트가 없어서, 케이스 패널의 조건식 원문과 엔드포인트별 그래프 노드에 쓴다.
  - `status`: `passed`·`failed`는 그대로, 그 밖(`undefined`, `uncompilable`, 결과 줄 없음)은 `notRun`.
    `results.case_statuses`(지금의 `_case_statuses`를 공개 이름으로 바꿔 `summarize`와 같이 쓴다)를 쓴다.
  - `observed`: 실패 케이스는 `observed_codes`의 값, 통과 케이스는 `expect.strict`가 정수면 그 값, 아니면 null.
- 집계 정의(`aggregates`, E2의 독립 구현이 같은 식으로 다시 계산한다). 모두 `inModel=true` 케이스만 센다.
  - 클래스 칸 상태(엔드포인트·필드·클래스마다 하나):
    `covered-pass`(칸이 그 클래스인 케이스 중 passed가 하나 이상) > `covered-fail`(failed가 하나 이상, passed 없음) >
    `covered-notrun`(notRun만) > `unresolved`(케이스는 없고 생성 불가 슬롯 칸이 그 클래스) > `empty`.
    `valid` 클래스는 칸이 비었거나 `valid`인 모든 inModel 케이스로 덮인다.
  - `boundaryCases`: 클래스마다 `boundaries`에 그 클래스를 가진 케이스 수(덮임 판정과 별개).
  - 2-way: 엔드포인트 안 필드 쌍 (A, B)와 클래스 쌍 (a, b)마다, 칸 해석 결과(적지 않은 필드는 `valid`)가 A=a, B=b인 케이스 수.
    `pairsTotal = Σ_{A<B} |A|·|B|`, `pairsCovered` = 수가 1 이상인 쌍 수(통과 여부 무관).
  - 요약 띠: 엔드포인트 수, 필드 수, 클래스 수(valid 포함), 덮인 클래스 수(covered-* 셋의 합), pairsCovered/pairsTotal,
    모델 밖 케이스 수(규칙별).
  - `universe.theoretical.factors[]` 중 `fields`가 없는 항목(`concurrency-race`)은 대상이 아니다.
- 데이터 흐름(build는 한 번만, `main`에서): `_deterministic`(collect 안)은 파일을 쓰지 않고 `factors.json` 유무만 보아
  블록에 `viz: {status: ok|absent, reason}`을 적는다(`ok`는 "만들 예정"이다). `collect`의 출력은 지금처럼 스키마를 그대로 통과한다.
  `compare.main`은 `validate` 뒤에 다음 순서로 진행한다.
  1. `out_dir` 생성. `viz.status == ok`면 `detviz.build(gen_dir, s07_dir)`를 한 번 불러 `det-viz.json`을 쓰고, `render_page`가 `det.html`을 그린다.
  2. build·쓰기·렌더 중 예외가 나면 `det-viz.json`·`det.html`을 지우고 `viz`를 `{status: failed, reason}`으로 바꾼다.
  3. `viz.status != ok`면(absent·failed·det 블록 null·failed 변형 포함) 기존 `det-viz.json`·`det.html`을 지운다(낡은 파일 방지).
  4. 바뀐 문서를 다시 `validate`하고 `compare.json`·`compare.html`을 쓴다.
  따라서 `compare.json`의 `viz.status == ok`이면 `det-viz.json`과 `det.html`이 반드시 있다.
- 렌더 책임: `det.html`은 `compare.render_page` 안에서만 그린다(`main`과 `RERENDER["compare/"]`가 모두 `render_page`를 부른다).
  `render_page`는 `det.html`을 `compare.html`보다 먼저 그린다. `det-viz.json`이 있고 `viz.status == ok`일 때만 그리고, 그 밖에는
  `det.html`을 지운다. `det.html` 렌더 예외는 `render_page` 안에서 잡아 `det.html`을 지우고, 메모리 문서의 `viz`를 failed로 바꾼 뒤
  `compare.html`을 그린다(링크 없음). RERENDER 경로에서 이렇게 바뀌면 게시 사본의 `compare.json`도 바뀐 문서로 다시 쓴다.
- 링크 조건: `compare.html`과 run 페이지 모두 `det.html` 파일이 있을 때만 링크한다(`viz.status == ok`와 동치가 되도록 위 흐름이 보장).
  사이트 조립(`pages.render_run`)은 링크를 모은 뒤 리포트를 다시 렌더하므로, 다시 렌더하다 `det.html`이 지워지면 존재 조건부 링크를 다시 거르고 공통 띠를 한 번 더 그린다.
  S12 자체가 예외로 끝나면 이번 run의 `det-viz.json`·`det.html`을 지운다.
- 스키마: `compare.schema.json` `deterministic` measured 변형에 `viz: {status: ok|absent|failed, reason: string|null}`(필수)를
  추가한다. failed 변형에는 넣지 않는다(det 집계 자체가 실패하면 viz도 없다). `absent` = `factors.json` 없음.
- 링크: `compare.html` det 블록에 `viz.status == ok`일 때 `det.html` 링크를 단다. run 페이지는 `REPORTS_EXTRA["compare/"]`에
  `("det 조합 시각화", "det.html")`을 더하고 `LINK_ONLY_IF_PRESENT`에 `"compare/"`를 추가해 파일이 있을 때만 링크한다.
- 자산: 온톨로지 화면과 같이 `cytoscape.min.js`와 `site/static/detviz.js`를 `det.html`에 인라인한다(단독 열람본·게시본 모두 동작).
  CSS는 `css_href`(게시 시 `static/v2/app.css`, 단독 열람 시 같은 디렉터리의 `app.css`) 링크 + 화면 전용 규칙 인라인. 게시 사본에는 사이트 공통 띠(`nav_html`)를 넣는다. 데이터는 `pages.json_for_script`로 `<script type="application/json">`에
  싣고, 상세 패널 등 화면 문자열은 `textContent`로만 넣는다(`innerHTML` 금지).

화면 구성(위에서 아래):

1. 요약 띠(위 정의).
2. 추적 그래프(Cytoscape, 엔드포인트 선택 상자): 출처 노드(메서드·조건식) → 클래스 노드 → 케이스 노드(통과/실패/실행 안 됨).
   생성 불가 슬롯은 점선 노드와 사유. 노드를 누르면 옆 패널에 원문(조건식, 값, 기대·관측 상태).
3. 클래스 격자: 행=필드, 열=클래스. 상태 기호 ✓(covered-pass) ✗(covered-fail) ○(covered-notrun) ⊘(unresolved) ·(empty)와 색을 같이 쓴다.
   칸에 케이스 id, 경계 케이스 수, 생성 불가 사유.
4. 2-way 히트맵: 엔드포인트별 필드 쌍 행렬(쌍이 많으면 접어 둔다). 엔드포인트별 pairsCovered/pairsTotal.
5. 모델 밖 케이스: 규칙·`outReason`별 표.
6. 생성 불가 목록: 사유별 묶음, 출처 조건식 원문.

`det-viz.json` 구조:

```json
{
  "version": 1, "genId": "det-xxxxxxxx-r1",
  "factors": { "...": "factors.json 전체" },
  "caseResults": {"<caseId>": {"endpoint": "POST /api/reservations", "status": "passed|failed|notRun",
                                "observed": 422, "expectStrict": 422}},
  "trace": {"caseSources": {"<caseId>": ["plan:...#...:0"]}, "unresolvedEndpoints": ["POST /api/reservations", null]},
  "aggregates": {
    "summary": {"endpoints": 17, "fields": 0, "classes": 0, "classesCovered": 0, "pairsCovered": 0, "pairsTotal": 0,
                "outOfModel": {"auth": 16, "no-data": 8, "empty-body": 1, "filter-empty": 2}},
    "byEndpoint": {"POST /api/reservations": {
       "classes": {"<classId>": {"state": "covered-pass", "cases": ["<caseId>"], "boundaryCases": 1,
                                  "unresolved": [{"index": 3, "reason": "unresolved-operand"}]}},
       "pairs": {"total": 403, "covered": 0,
                 "matrix": [{"a": "body.nights", "b": "body.petName", "counts": [[0]]}]}}}
  }
}
```

`matrix[].counts[i][j]`는 필드 a의 i번째 클래스(목록 순서)와 필드 b의 j번째 클래스를 동시에 가진 inModel 케이스 수다.
`summary.fields`와 `classes`는 `fields`가 있는 엔드포인트의 필드·클래스(valid 포함) 합이다. 숫자 0은 자리표시다.

`detviz.js`는 렌더를 마치면 `window.__td_ready = true`를 설정한다(Playwright 대기용, 온톨로지 화면과 같은 규약).

라이트/다크는 v2 `app.css` 토큰(`--fg`, `--muted`, `--line`, `--surface`, `--accent`)을 따르고, 격자·히트맵은 `.scroll` 안에 둬 모바일 폭에서 페이지 가로 스크롤이 생기지 않게 한다.

### 5.5 문서 갱신 범위

상위 det 설계 §5.4의 generation 구성에 `factors.json`, S12 산출물에 `det-viz.json`·`det.html`을 추가한다. README 리포트 목록에 det 조합 시각화를 더한다.

## 6. 수용 테스트(E2E 우선, 이중 루프)

요구사항명세 `docs/superpowers/requirements/2026-11-22-det-combination-viz-requirements.md`(REQ-201~)가 테스트의 단일 출처다.
완료 정의: 매트릭스의 대상 REQ 테스트가 모두 통과한다.

가장 높은 실행 가능 수준은 실제 파이프라인 run(`run-all --arms base,jqa,owl,det`, LLM arm은 스냅샷 재사용)과 `_test/` 게시본이다.
전제: 기준 스냅샷과 같은 SUT 커밋·`tools.pin.yaml`이다(bbtg 결과와 det는 LLM 없이 결정적). 다르면 80 대신 `universe.bySlot.generated`와 비교한다.

- E1: 실제 run의 `S12/compare/det.html`·`det-viz.json`이 있고 케이스 80개가 모두 있다. run·compare 페이지에서 링크된다.
- E2: 격자 칸 상태 수·경계 수·2-way 덮인 쌍을 테스트의 독립 구현이 `cases.json`+`factors.json`+S07 결과에서 다시 계산해 `aggregates`와 같다.
  POST /api/reservations의 `pairsTotal`은 403이다.
- E3: 필드별 클래스 수가 `universe.theoretical.factors[].fields`와 같다(`fields`가 있는 항목 전부).
- E4: 새 generation의 `cases.json`·feature가 이전 스냅샷(`det-da70932c-r1`)과 바이트 동일하다.
- E5: 게시 사본의 누출 검사(`redact.find_leaks`) 0건, `check_no_home` 통과.
- 단위·통합: 클래스 레지스트리 kind 규칙, 칸 규칙 표의 행마다, 병합 케이스(boundaries 합집합·`cellConflicts` 빈 목록),
  생성 불가 슬롯 index·칸, 결정성, `</script>` 포함 조건식 fixture의 이스케이프, 실패 격리(factors 없음 → viz absent·링크 없음,
  viz 예외 → viz failed·S12 통과·`validate` 통과, 재실행 시 낡은 det.html 제거, RERENDER 예외 격리).
- 브라우저 확인(자동): 기존 `test_ontology.py`의 Playwright 패턴으로 네트워크 차단 열람, 콘솔 오류 0, 노드·칸·행렬 수, 상호작용, 라이트/다크·390px, 적대적 문자열 DOM 안전성을 확인한다.

## 7. 빌더 재량

- 그래프 배치(Cytoscape `breadthfirst` 권장), 색, 칸 크기, 히트맵 접기 방식, 클래스 라벨 표기 세부.
