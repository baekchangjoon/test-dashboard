#!/usr/bin/env bash
# S02 bbtg: 7개 분석 스킬(inspect-stack, scan-test-assets, dependency-map, find-external-calls, inspect-auth,
# derive-test-data, plan-tests)을 bbtg 전용 venv 파이썬으로 SUT 루트에서 실행하고 산출물을 정제한다. claude는 쓰지 않는다.
# 입력: S00(tools/bbtg), SUT clone(TD_SUT_SRC). 산출물: S02/bbtg/{raw/, clean/, manifest.json}. SUT clone의 .bbtg/는 지운다.
# 외부 명령 시간 제한(스킬당 900초, TD_BBTG_TIMEOUT)은 td.bbtg가 td.proc(td_run과 같은 실행기)로 건다.
# 사용: S02-bbtg.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

td_stage_begin S02
td_hook S02
: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"

s02_fail() { td_log "S02 failed: $1"; td_stage_end S02 failed "${1:0:1500}"; exit 1; }
S00_JSON="$TD_RUN_DIR/stages/S00.json"
[[ -f "$S00_JSON" ]] || s02_fail "S00 산출물이 없다"
TOOLS_DIR="$(jq -r '.outputs.toolsDir // empty' "$S00_JSON")"
BBTG_DIR="$TOOLS_DIR/bbtg"
EXTRA_ARGS=()
# 테스트 전용: 가짜 bbtg(행 걸림·부분 실패 주입). TD_SITE_PREFIX(테스트 격리)가 없으면 거부한다.
if [[ -n "${TD_BBTG_FAKE_DIR:-}" ]]; then
  [[ -n "${TD_SITE_PREFIX:-}" ]] || s02_fail "TD_BBTG_FAKE_DIR는 TD_SITE_PREFIX가 있는 테스트 실행에서만 허용된다"
  BBTG_DIR="$TD_BBTG_FAKE_DIR"
  EXTRA_ARGS=(--python "$(command -v python3)")
elif [[ ! -x "$BBTG_DIR/.venv/bin/python" ]]; then
  s02_fail "bbtg venv 파이썬이 없다: $BBTG_DIR/.venv/bin/python"
fi

OUT_DIR="$TD_RUN_DIR/S02/bbtg"
mkdir -p "$TD_RUN_DIR/S02"
RESULT="$(td_py -m td.bbtg run "$OUT_DIR" --src "$TD_SUT_SRC" --sut-file "$TD_SUT_FILE" --bbtg-dir "$BBTG_DIR" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
  2>"$TD_RUN_DIR/S02/bbtg.log")" || s02_fail "td.bbtg 실행 실패(로그: S02/bbtg.log)"
rm -rf "$TD_SUT_SRC/.bbtg"  # run_all이 지웠지만, 중간에 죽은 경우에도 clone을 깨끗이 둔다
jq -e . >/dev/null 2>&1 <<< "$RESULT" || s02_fail "td.bbtg 출력이 JSON이 아니다(로그: S02/bbtg.log)"
STATUS="$(jq -r '.status' <<< "$RESULT")"
REASON="$(jq -r '.reason // empty' <<< "$RESULT")"
EXTRA="$(jq -c '.extra // {}' <<< "$RESULT")"
OUTPUTS="$(jq -cn --arg dir "$OUT_DIR" --arg clean "$OUT_DIR/clean" --arg manifest "$OUT_DIR/manifest.json" '{bbtg: $dir, clean: $clean, manifest: $manifest}')"
case "$STATUS" in
  passed) td_stage_end S02 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA" ;;
  degraded) td_stage_end S02 degraded "$REASON" --outputs-json "$OUTPUTS" --extra-json "$EXTRA" ;;
  *) td_stage_end S02 failed "${REASON:-알 수 없는 실패}" --outputs-json "$OUTPUTS" --extra-json "$EXTRA"; exit 1 ;;
esac
