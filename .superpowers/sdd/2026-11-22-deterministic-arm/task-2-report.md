# Task 2 보고: det 번들 투영

상태: DONE (REQ-110, REQ-112)

## 구현
- `site-gen/td/detgen/inputs.py`: `project(run_dir, sut_file, out_dir) -> Projection`, `Bundle.open/read`, `DetInputError`.
  - 허용 필드만 복사(plans/keyparams/auth), ontology/ext는 스키마 검증 후 금지 키(file_path, interceptor_sources, artifact_path, key_params_path) 제거.
  - 문자열의 로컬 절대경로는 `<path>`로 치환 후 `redact_text`. 마지막에 `find_leaks`로 검사하고 남으면 fatal.
  - plan 항목 주소 = (file, index, conditionSha). conditionSha는 scrub된 condition의 sha256.
  - input_hash = 파일 이름순 (이름, sha256) 나열의 sha256. 경로·시각 미포함. STAMP.json = files/input_hash/missing/schema.
  - missing 슬롯명: `keyparams`, `keyparams:<file>`, `auth`, `plan:<file>` (정렬). 필수 누락/스키마 위반/plan 0개는 fatal이며 번들·STAMP를 쓰지 않는다(input_hash="").
  - harness: sut_config.load로 login/unauthenticatedStatus/apiInclude, timezone은 `<sut_file>/../../..` 기준 env/docker-compose.sut.yml의 TZ(없으면 state.TZ_NAME).
  - Bundle.read: STAMP 키와 정확히 일치하는 이름만 허용(경로 탈출 자동 거부) + sha256 변조 검사.
- fixture: `tests/fixtures/det/raw-min/`(합성, `/Users/example/sut/...` 가짜 경로와 interceptor_sources/file_path 포함, sut.yaml 사본),
  `tests/fixtures/det/petclinic/run/`(실제 S02 plan-tests 6개, key-params 6개, inspect-auth, S03 두 파일) + `petclinic/sut.yaml`.

## TDD
- RED: `ModuleNotFoundError: No module named 'td.detgen'` (collection error).
- GREEN: `tests/acceptance/test_unit_detgen.py` 14 passed.
- 전체: `-m "not baseline" -k unit` 405 passed, 336 deselected (144.99s).

## find_leaks 결과(커밋 fixture 트리 25개 파일)
- petclinic/ 전체 clean(홈 경로, ARN, 식별자 없음. 실제 raw에는 원래 절대경로가 없었음).
- raw-min 4개 파일만 `local-path` 플래그: 의도한 가짜 `/Users/example/` 경로. 저장소 전역 fixture leak 테스트는 없었고,
  `test_committed_fixtures_have_no_real_leaks`가 raw-min에서 `/Users/example/`만 제외하고 나머지를 검사한다.

## 우려
- petclinic fixture에서 `ontology.json`/`ext.json`과 `run/S03/*` 내용이 중복(70KB). Task 1 테스트가 기존 위치를 쓰므로 유지.
- keyparams.json의 reasons는 `{"detail"}`만 보존(type 등은 허용목록 밖이라 제외). 후속 Task가 type이 필요하면 허용목록 갱신 필요.
- 필수 파일이 없을 때 fatal 사유에 파일명이 들어가며, 번들 디렉터리는 만들어지되 STAMP는 지운다.

## 수정 라운드 1
1. keyparams: reason을 `{type, detail}`로, 파라미터에 `accessor` 추가. 테스트·raw-min fixture 갱신.
2. `sut_config.SutConfigError`(없음/형식 오류)를 `Projection.fatal`("sut.yaml 오류: ...")로 변환. 테스트 추가.
3. `_text()`로 비문자열/None -> "" (str(None) 제거). `param: null` 테스트 추가.
4. 실제로는 이전 구현이 `_scrub`(경로 치환 + redact_text)를 condition 등에 적용하고 있었다. 이제 plan/keyparams/auth 필드는 원문 그대로 두고
   (conditionSha = 원문 condition 해시), 누출은 `find_leaks` 게이트가 fatal로만 막는다. ontology/ext만 금지 키 제거 + scrub 유지. 테스트 추가.
결과: test_unit_detgen.py 17 passed.
