#!/usr/bin/env bash
# S09 hotspot: hotspot-analysis(jar, JDK 21)로 파일/메서드/API 핫스팟 리포트를 만든다.
# 입력: S00(tools, SUT jar/classes), S08/merged/aggregate.xml(선택 — 없으면 커버리지 배수 없이 degraded).
# 산출물: S09/hotspot/{hotspots.html,api_report.html,hotspot.yml,...}, S09/top10.json (단계 JSON의 top10에도 복사)
# 사용: S09-hotspot.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

td_stage_begin S09
td_hook S09
: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"

s09_fail() { td_log "S09 failed: $1"; td_stage_end S09 failed "${1:0:1500}"; exit 1; }
S00_JSON="$TD_RUN_DIR/stages/S00.json"
[[ -f "$S00_JSON" ]] || s09_fail "S00 산출물이 없다"
TOOLS_DIR="$(jq -r '.outputs.toolsDir // empty' "$S00_JSON")"
HOTSPOT_JAR="$TOOLS_DIR/hotspot.jar"
[[ -f "$HOTSPOT_JAR" ]] || s09_fail "hotspot.jar가 없다: $TOOLS_DIR"
JAVA21="$(td_java_home 21)" || s09_fail "JDK 21을 찾지 못했다(hotspot-analysis 실행에 필요)"
TEMPLATE="$(dirname "$TD_SUT_FILE")/hotspot.yml.tmpl"
[[ -f "$TEMPLATE" ]] || s09_fail "hotspot.yml.tmpl이 없다: $TEMPLATE"

MERGED_XML="$TD_RUN_DIR/S08/merged/aggregate.xml"
mkdir -p "$TD_RUN_DIR/S09"
PREP="$(td_py -m td.hotspot prepare "$TD_RUN_DIR" --sut-file "$TD_SUT_FILE" --src "$TD_SUT_SRC" --template "$TEMPLATE" \
  --merged-xml "$MERGED_XML" 2>"$TD_RUN_DIR/S09/prepare.log")" || s09_fail "설정 준비 실패: $(tail -c 600 "$TD_RUN_DIR/S09/prepare.log")"
CONFIG="$(jq -r '.config' <<< "$PREP")"
JACOCO="$(jq -r '.jacoco' <<< "$PREP")"

# 상대 경로는 cwd 기준이므로 설정은 절대 경로만 쓰고, cwd는 run의 S09 디렉터리로 둔다.
(cd "$TD_RUN_DIR/S09" && JAVA_HOME="$JAVA21" td_run 600 -- "$JAVA21/bin/java" -jar "$HOTSPOT_JAR" analyze --config "$CONFIG" --quiet) \
  >"$TD_RUN_DIR/S09/hotspot.log" 2>&1 || s09_fail "hotspot-analysis 실패: $(tail -c 600 "$TD_RUN_DIR/S09/hotspot.log")"
rm -rf "$TD_RUN_DIR/S09/deps"  # 의존 jar 사본은 분석 후 필요 없다(수십 MB)

RESULT="$(td_py -m td.hotspot finish "$TD_RUN_DIR" --jacoco "$JACOCO" --merged-xml "$MERGED_XML" 2>"$TD_RUN_DIR/S09/finish.log")" \
  || s09_fail "결과 가공 실패: $(tail -c 600 "$TD_RUN_DIR/S09/finish.log")"
STATUS="$(jq -r '.status' <<< "$RESULT")"
REASON="$(jq -r '.reason // empty' <<< "$RESULT")"
EXTRA="$(jq -c '.extra' <<< "$RESULT")"
OUTPUTS="$(jq -cn --arg dir "$TD_RUN_DIR/S09/hotspot" --arg top10 "$TD_RUN_DIR/S09/top10.json" '{hotspot: $dir, top10: $top10}')"
if [[ "$STATUS" == "degraded" ]]; then
  td_stage_end S09 degraded "$REASON" --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
else
  td_stage_end S09 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
fi
