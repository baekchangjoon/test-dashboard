#!/usr/bin/env bash
# S01 blackbox: SUT 컨테이너(pjacoco agent)를 띄우고 SUT clone의 blackboxTest를 실행한다.
# 산출물: S01/blackbox/{exec/*.exec, exec/aggregate.exec, junit/*.xml, summary.json, gradle.log}
# 게이트(REQ-008): JUnit TC 수(skipped 제외) == .exec 수(aggregate 제외), 불일치는 failed이며 missingExec를 보고한다.
# 사용: S01-blackbox.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/blackbox.sh"

td_stage_begin S01
td_hook S01

: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"
OUT_DIR="$TD_RUN_DIR/S01/blackbox"
JUNIT_DIR="$OUT_DIR/junit"
mkdir -p "$JUNIT_DIR"

s01_fail() { # <사유> [extra-json]
  td_log "S01 failed: $1"
  td_sut_down
  if [[ -n "${2:-}" ]]; then td_stage_end S01 failed "${1:0:1500}" --extra-json "$2"
  else td_stage_end S01 failed "${1:0:1500}"; fi
  exit 1
}

SUT_JAVA_HOME="$(td_java_home "$(td_py -m td.sut_config get "$TD_SUT_FILE" java)")" || true
[[ -n "$SUT_JAVA_HOME" ]] || s01_fail "SUT가 요구하는 JDK $(td_py -m td.sut_config get "$TD_SUT_FILE" java)를 찾지 못했다"

# SUT 기동, blackboxTest, 게이트 판정은 lib/blackbox.sh(S10과 공유)가 한다.
td_blackbox_suite S01 blackbox "$TD_SUT_SRC" "$SUT_JAVA_HOME" 0 || true
[[ -n "$BB_STATUS" ]] || s01_fail "블랙박스 스위트가 상태를 남기지 않았다"
OUTPUTS="$(jq -cn --arg dir "$OUT_DIR" '{blackbox: $dir}')"
if [[ "$BB_STATUS" == "passed" ]]; then
  td_stage_end S01 passed --outputs-json "$OUTPUTS" --extra-json "$BB_EXTRA"
elif [[ "$BB_STATUS" == "degraded" ]]; then
  td_stage_end S01 degraded "${BB_REASON:0:1500}" --outputs-json "$OUTPUTS" --extra-json "$BB_EXTRA"
else
  td_stage_end S01 failed "${BB_REASON:0:1500}" --extra-json "$BB_EXTRA"
  exit 1
fi
