#!/usr/bin/env bash
# S07 e2e: S06이 만든 generation마다 SUT 컨테이너(pjacoco agent)를 새로 띄우고 Cucumber를 실행한다(병렬도 1, dry-run 먼저).
# 산출물: S07/<genId>/{dryrun.json, cucumber.ndjson, cucumber.json, html/, junit.xml, scenario-results.json, summary.json, exec/, ...}
# 게이트(REQ-028): 모든 시나리오가 scenario-results.json에 한 번씩 나온다(컴파일 제외는 uncompilable), 요청 1회 이상 시나리오 수 = .exec 수.
# generation 위치: S06 단계 JSON의 generations.<genId>.dir, 없으면 e2e/generated/<sut>/<arm>/<genId>.
# 사용: S07-e2e.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/e2e.sh"

td_stage_begin S07
td_hook S07

: "${TD_RUN_DIR:?}" "${TD_SUT_FILE:?}"

s07_fail() { td_log "S07 failed: $1"; td_sut_down; td_stage_end S07 failed "${1:0:1500}"; exit 1; }

S06_JSON="$TD_RUN_DIR/stages/S06.json"
[[ -f "$S06_JSON" ]] || s07_fail "S06 산출물이 없다(실행할 generation을 알 수 없다)"
SUT_NAME="$(td_py -m td.sut_config get "$TD_SUT_FILE" name)" || s07_fail "sut.yaml name을 읽지 못했다"
JAVA17="$(td_java_home 17)" || s07_fail "JDK 17을 찾지 못했다(e2e 실행기 toolchain)"

GENERATIONS="{}"
OUTPUTS="{}"
PASSED=0
FAILED=0
FAILED_NOTES=""
while IFS=$'\t' read -r GEN_ID ARM GEN_DIR; do
  [[ -n "$GEN_ID" ]] || continue
  [[ -n "$GEN_DIR" ]] || GEN_DIR="$(td_py -m td.scenarios gen-dir "$SUT_NAME" "$GEN_ID")"
  td_log "S07 generation $GEN_ID ($GEN_DIR)"
  if [[ -d "$GEN_DIR" ]]; then
    td_e2e_generation S07 "$GEN_ID" "$GEN_DIR" "$JAVA17" || true
  else
    E2E_STATUS=failed; E2E_REASON="generation 디렉터리가 없다: $GEN_DIR"; E2E_EXTRA="{}"
  fi
  [[ -n "$E2E_STATUS" ]] || { E2E_STATUS=failed; E2E_REASON="generation 실행이 상태를 남기지 않았다"; }
  if [[ "$E2E_STATUS" == "passed" ]]; then
    PASSED=$((PASSED + 1))
    GENERATIONS="$(jq -c --arg id "$GEN_ID" --arg arm "$ARM" --argjson extra "$E2E_EXTRA" \
      '. + {($id): ({arm: $arm, status: "passed"} + $extra)}' <<< "$GENERATIONS")"
    [[ ! -d "$TD_RUN_DIR/S07/$GEN_ID/html" ]] || OUTPUTS="$(jq -c --arg key "html:$GEN_ID" --arg dir "$TD_RUN_DIR/S07/$GEN_ID/html" '. + {($key): $dir}' <<< "$OUTPUTS")"
  else
    FAILED=$((FAILED + 1))
    FAILED_NOTES="${FAILED_NOTES:+$FAILED_NOTES | }$GEN_ID: $E2E_REASON"
    GENERATIONS="$(jq -c --arg id "$GEN_ID" --arg arm "$ARM" --arg reason "$E2E_REASON" \
      '. + {($id): {arm: $arm, status: "failed", reason: $reason}}' <<< "$GENERATIONS")"
  fi
done < <(jq -r '.generations // {} | to_entries[] | select(.value.status == "passed" or .value.status == "degraded") | [.key, (.value.arm // ""), (.value.dir // "")] | @tsv' "$S06_JSON")

EXTRA="$(jq -cn --argjson generations "$GENERATIONS" '{generations: $generations}')"
if [[ "$FAILED" -eq 0 && "$PASSED" -gt 0 ]]; then
  td_stage_end S07 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
elif [[ "$PASSED" -gt 0 ]]; then
  td_stage_end S07 degraded "generation 실패 ${FAILED}개: ${FAILED_NOTES:0:1200}" --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
else
  td_stage_end S07 failed "${FAILED_NOTES:-실행한 generation이 없다}" --extra-json "$EXTRA"
  exit 1
fi
