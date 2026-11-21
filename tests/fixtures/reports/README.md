# 표본 리포트 (hotspot·TIA)

뒤 Task의 화면 테스트가 입력으로 쓰는 외부 도구 리포트 3개다. 실제 파이프라인을 spring-petclinic SUT로 돌려 얻은 산출물을
게시 가리기(`td.redact`)를 거쳐 그대로 둔다. 손으로 고치지 않는다.

| 파일 | 원본 위치(run 디렉터리 기준) | 만든 단계 |
|---|---|---|
| `hotspots.html` | `S09/hotspot/hotspots.html` | S09 (`--only S00,S01,S08,S09`, S09 passed) |
| `api_report.html` | `S09/hotspot/api_report.html` | S09 (같은 run) |
| `tia.html` | `S10/tia/tia.html` | S10 (`--only S00,S02,S06,S10 --arms base --reps 1`, S10 passed) |

## 만든 방법

도구 커밋(`tools.pin.yaml`):

- hotspot-analysis `a5baac6c59273838374fe8a3cebf39ccc876d5c4` (S00이 JDK 21로 `./gradlew bootJar` 빌드)
- test-impact-analysis `c4e6e9e2c18f52e3315cc90a6f98fa16506c9199` (S10이 `tia report --impact impact.json`으로 호출)
- SUT: spring-petclinic `b6f939355e8790202ddfc71e3f3507252745ed37`, TIA base `c37b2e4`

명령:

```bash
uv run --project site-gen pytest tests/acceptance/test_reports.py -k "req035 or req036" -v --basetemp=<임시 디렉터리>
```

`test_req035_hotspot`(S00,S01,S08,S09)과 `test_req036_tia_base`(S00,S02,S06,S10)가 만든 run 디렉터리에서 위 세 파일을 꺼내
`td.redact.redact_text(text, run_dir=<run>, repo_root=<repo>, env=…)`로 가렸다. `env`에는 파이프라인이 넘기는 것처럼
`TD_WORK_DIR=<run의 work 디렉터리>`와 `TD_ROOT=<repo>`를 넣었다(`pages.sanitize_site`와 같은 치환). 가린 뒤
`td.redact.find_leaks`가 세 파일 모두 빈 목록이다. `hotspots.html`·`api_report.html`의 SUT 경로는 `<work>/suts/…`로 바뀌었다.

## 확인한 선택자

Playwright(headless Chromium)로 파일을 열어 각 선택자가 맞는지 확인했다. 계획에 적힌 선택자와 다르면 이 표가 맞다.

| 대상 | 선택자 | 확인 결과 |
|---|---|---|
| hotspot 지도 SVG | `svg#hm-map` | 1개 |
| hotspot 옆 패널 | `#hm-side` | 1개 |
| API 핫스팟 표 행 (`api_report.html`) | `#api-hotspots tbody tr` | 34개 |
| TIA 페이지 전환 탭 | `#seg [role=tab]` | 4개: 변경 영향(`data-k="impact"`), 연결 구조(`graph`), 커버리지 지도(`matrix`), 안정성(`stability`). 선택된 탭은 `aria-selected="true"` |
| TIA "읽는 법" 블록 | `#view details.tab-guide` | 페이지마다 1개(요약 `이 탭 읽는 법`). 탭을 바꿔도 새 페이지에 1개 |
| TIA 변경 영향 페이지의 변경 파일 항목 | `#s-list .scrow:not(.all)` | 8개. 첫 항목의 `title`은 파일 경로, `data-id`는 `c0`…`c7` |

TIA 리포트는 처음 열면 변경 영향 페이지(`data-k="impact"`)가 선택돼 있다. `#s-list .scrow.all`은 "이번 변경 전체" 묶음 항목이라
변경 파일 항목에서 뺀다. 이 SUT의 base..HEAD 변경 파일 8개는 모두 커버리지에 매핑되지 않아 보수적 전체 실행(34/34)이다.
리포트 내장 데이터는 `const D = {…}`이며 `D.commit`이 TIA base 커밋이다.
