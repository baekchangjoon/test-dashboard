#!/usr/bin/env bash
# S08 coverage: 스위트별 귀속/집계 리포트, TC별 라인 JSON, 병합 집계 XML, 무결성 검사, coverage.html.
# 입력: S01/blackbox/exec, S07/<genId>/exec(있는 스위트만). classes는 S00이 빌드한 같은 커밋의 것이다.
# 산출물: S08/{<suite>/{attributed,aggregate}/{html,jacoco.xml,jacoco.csv}, merged/{aggregate.xml,manifest.json}, coverage.json, tc/, src/, coverage.html}
# 사용: S08-coverage.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

td_stage_begin S08
td_hook S08
: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"

s08_fail() { td_log "S08 failed: $1"; td_stage_end S08 failed "${1:0:1500}"; exit 1; }
S00_JSON="$TD_RUN_DIR/stages/S00.json"
[[ -f "$S00_JSON" ]] || s08_fail "S00 산출물이 없다(classes를 알 수 없다)"
CLASSES="$(jq -r '.outputs.classes // empty' "$S00_JSON")"
TOOLS_DIR="$(jq -r '.outputs.toolsDir // empty' "$S00_JSON")"
COMMIT="$(jq -r '.outputs.commit // empty' "$S00_JSON")"
[[ -d "$CLASSES" ]] || s08_fail "S00 classes 디렉터리가 없다: $CLASSES"
[[ -f "$TOOLS_DIR/jacococli.jar" ]] || s08_fail "jacococli.jar가 없다: $TOOLS_DIR"
[[ -n "$COMMIT" ]] || s08_fail "S00 commit 출력이 없다"
SOURCES="$(td_py -c 'import sys;from td.sut_config import load;print(load(sys.argv[1]).sources_dir(sys.argv[2]))' "$TD_SUT_FILE" "$TD_SUT_SRC")" \
  || s08_fail "sut.yaml sources를 읽지 못했다"
SUT_JAVA_HOME="$(td_java_home "$(td_py -m td.sut_config get "$TD_SUT_FILE" java)")" || s08_fail "SUT가 요구하는 JDK를 찾지 못했다"
mkdir -p "$TD_RUN_DIR/S08"
RESULT="$(JAVA_HOME="$SUT_JAVA_HOME" td_py -m td.coverage run "$TD_RUN_DIR" --sut-file "$TD_SUT_FILE" --classes "$CLASSES" \
  --sources "$SOURCES" --cli "$TOOLS_DIR/jacococli.jar" --commit "$COMMIT" 2>"$TD_RUN_DIR/S08/coverage.log")" \
  || s08_fail "td.coverage 실행 실패: $(tail -c 600 "$TD_RUN_DIR/S08/coverage.log")"
jq -e . >/dev/null 2>&1 <<< "$RESULT" || s08_fail "td.coverage 출력이 JSON이 아니다: $(head -c 300 <<< "$RESULT")"
STATUS="$(jq -r '.status' <<< "$RESULT")"
REASON="$(jq -r '.reason // empty' <<< "$RESULT")"
EXTRA="$(jq -c '.extra // {}' <<< "$RESULT")"
if [[ "$STATUS" == "passed" ]]; then
  td_stage_end S08 passed --outputs-json "$(jq -cn --arg dir "$TD_RUN_DIR/S08" --arg merged "$TD_RUN_DIR/S08/merged/aggregate.xml" '{coverage: $dir, mergedXml: $merged}')" --extra-json "$EXTRA"
else
  td_stage_end S08 failed "${REASON:-알 수 없는 실패}" --extra-json "$EXTRA"
  exit 1
fi
