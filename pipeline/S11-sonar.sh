#!/usr/bin/env bash
# S11 sonar: 전용 프로젝트(spring-petclinic-td, 주입 실행은 -test-<sessionId>)를 스캔하고 결과를 export한다.
# 흐름: 사전 점검(HTTP, SSH) -> 스키마 확인 -> 만료 토큰 청소 -> 빌드 -> 토큰 발급 -> 스캔 -> CE 폴링 -> export -> 토큰 정리.
# 입력: S00(SUT 소스, JDK), S08/merged/aggregate.xml(선택). 품질 게이트 ERROR는 단계 실패가 아니다.
# 산출물: S11/sonar/{sonar.json,sonar.html}, S11/{build,scan}.log. 토큰은 환경 변수 SONAR_TOKEN으로만 다룬다.
# 사용: S11-sonar.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$TD_ROOT/pipeline/lib/env.sh"
source "$TD_ROOT/pipeline/lib/sonar-token.sh"

td_stage_begin S11
td_hook S11
: "${TD_RUN_DIR:?}" "${TD_RUN_ID:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"

# 모든 종료는 여기를 지난다: 토큰을 먼저 정리하고(실패하면 failed), 단계를 마감한다.
s11_done() { # <status> [reason] [outputs-json] [extra-json]
  local status="$1" reason="${2:-}" outputs="${3:-}" extra="${4:-}"
  [[ -n "$outputs" ]] || outputs='{}'
  [[ -n "$extra" ]] || extra='{}'
  if ! td_sonar_token_revoke; then
    status=failed
    reason="${reason:+$reason; }$TD_SONAR_FAIL_REASON"
  fi
  [[ -z "${SONAR_TOKEN:-}" ]] || reason="${reason//$SONAR_TOKEN/<token>}"
  local args=(S11 "$status")
  [[ -z "$reason" ]] || args+=("${reason:0:1500}")
  [[ "$status" == "passed" ]] && td_log "S11 passed" || td_log "S11 $status: ${reason:0:300}"
  td_stage_end "${args[@]}" --outputs-json "$outputs" --extra-json "$extra"
  if [[ "$status" == "failed" ]]; then exit 1; fi
  exit 0
}
s11_fail() { s11_done failed "$1"; }
log_tail() { tail -c 500 "$1" 2>/dev/null | tr '\n' ' '; }

td_sonar_load_env || s11_fail "Sonar 설정 실패: $TD_SONAR_FAIL_REASON"
TD_SONAR_URL="$(td_py -m td.sonar url 2>&1)" || s11_fail "Sonar URL을 알 수 없다: $TD_SONAR_URL"
export TD_SONAR_URL
PROJECT_KEY="$(td_py -m td.sonar key "$TD_SUT_FILE" 2>&1)" || s11_fail "Sonar 프로젝트 키를 읽지 못했다: $PROJECT_KEY"
S11_DIR="$TD_RUN_DIR/S11"
mkdir -p "$S11_DIR"

# 토큰을 발급하기 전에 서버와 SSH에 닿는지 본다(닿지 않으면 INSERT 0건).
preflight_reason="$(td_py -m td.sonar preflight --url "$TD_SONAR_URL" 2>&1)" \
  || s11_fail "Sonar 사전 점검 실패(HTTP): $preflight_reason"
td_sonar_psql "select 1" >/dev/null 2>"$S11_DIR/preflight-ssh.log" \
  || s11_fail "Sonar 사전 점검 실패(ssh로 DB에 닿지 않는다): $(log_tail "$S11_DIR/preflight-ssh.log")"
td_sonar_verify_schema || s11_fail "Sonar 토큰 스키마 확인 실패: $TD_SONAR_FAIL_REASON"
td_sonar_preclean || s11_fail "Sonar 토큰 사전 청소 실패: $TD_SONAR_FAIL_REASON"

# 스캔 인자 조립(커버리지 XML은 S08 병합 집계 하나만 쓴다)
MERGED_XML="$TD_RUN_DIR/S08/merged/aggregate.xml"
PREP="$(td_py -m td.sonar prepare --sut-file "$TD_SUT_FILE" --url "$TD_SONAR_URL" --key "$PROJECT_KEY" --xml "$MERGED_XML" 2>&1)" \
  || s11_fail "스캔 인자 조립 실패: ${PREP:0:300}"
COVERAGE_SHA="$(jq -r '.coverageXmlSha256 // empty' <<< "$PREP")"
BUILD_CMD=(); while IFS= read -r part; do BUILD_CMD+=("$part"); done < <(jq -r '.build[]' <<< "$PREP")
SCAN_CMD=(); while IFS= read -r part; do SCAN_CMD+=("$part"); done < <(jq -r '.scan[]' <<< "$PREP")
SCAN_ARGS=(); while IFS= read -r part; do SCAN_ARGS+=("$part"); done < <(jq -r '.args[]' <<< "$PREP")
SUT_JAVA_HOME="$(td_java_home "$(td_py -m td.sut_config get "$TD_SUT_FILE" java)")" || s11_fail "SUT가 요구하는 JDK를 찾지 못했다"

# 빌드는 토큰 없이(스캔과 분리해 Gradle 9 implicit-dependency 문제를 피한다)
(cd "$TD_SUT_SRC" && JAVA_HOME="$SUT_JAVA_HOME" td_run 1800 -- "${BUILD_CMD[@]}") >"$S11_DIR/build.log" 2>&1 \
  || s11_fail "SUT 빌드 실패(${BUILD_CMD[*]}): $(log_tail "$S11_DIR/build.log")"

td_sonar_token_issue "$TD_RUN_ID" || s11_fail "Sonar 토큰 발급 실패: $TD_SONAR_FAIL_REASON"
td_hook S11:scan
td_py -m td.sonar ensure-project --url "$TD_SONAR_URL" --key "$PROJECT_KEY" >"$S11_DIR/ensure-project.json" 2>&1 \
  || s11_fail "Sonar 프로젝트를 만들지 못했다: $(log_tail "$S11_DIR/ensure-project.json")"

REPORT_TASK="$TD_SUT_SRC/build/sonar/report-task.txt"
rm -f "$REPORT_TASK"  # 이전 스캔의 낡은 파일을 CE 폴링에 쓰지 않는다
# Gradle은 sonar 태스크 입력(SONAR_TOKEN에서 온 sonar.token 포함)을 프로젝트 캐시의 executionHistory.bin에 남긴다.
# SUT의 .gradle에 토큰이 남지 않게 스캔 전용 캐시 디렉터리를 쓰고 끝나면 지운다(REQ-066).
SCAN_CACHE="$S11_DIR/gradle-cache"
scan_rc=0
(cd "$TD_SUT_SRC" && JAVA_HOME="$SUT_JAVA_HOME" td_run 1800 -- "${SCAN_CMD[@]}" "${SCAN_ARGS[@]}" --project-cache-dir "$SCAN_CACHE") >"$S11_DIR/scan.log" 2>&1 || scan_rc=$?
rm -rf "$SCAN_CACHE"
[[ $scan_rc -eq 0 ]] || s11_fail "Sonar 스캔 실패(종료 코드 $scan_rc): $(log_tail "$S11_DIR/scan.log")"

TASK_ID="$(td_py -m td.sonar report-task "$REPORT_TASK" 2>&1)" || s11_fail "Sonar 스캔 결과를 알 수 없다: $TASK_ID"
CE_STATUS="$(td_py -m td.sonar wait-ce --url "$TD_SONAR_URL" --task-id "$TASK_ID" --timeout 600 2>/dev/null)" || true
if [[ "$CE_STATUS" != "SUCCESS" ]]; then
  s11_fail "$(td_py -c 'import sys;from td.sonar import ce_failure_reason;print(ce_failure_reason(sys.argv[1], sys.argv[2]))' "$TASK_ID" "${CE_STATUS:-TIMEOUT}")"
fi

RESULT="$(td_py -m td.sonar finish "$TD_RUN_DIR" --url "$TD_SONAR_URL" --key "$PROJECT_KEY" --task-id "$TASK_ID" 2>"$S11_DIR/finish.log")" \
  || s11_fail "Sonar export 실패: $(log_tail "$S11_DIR/finish.log")"
[[ "$(jq -r '.status' <<< "$RESULT")" == "passed" ]] || s11_fail "$(jq -r '.reason' <<< "$RESULT")"
EXTRA="$(jq -c --arg sha "$COVERAGE_SHA" '.extra + {coverageXmlSha256: (if $sha == "" then null else $sha end)}' <<< "$RESULT")"
s11_done passed "" "$(jq -c '.outputs' <<< "$RESULT")" "$EXTRA"
