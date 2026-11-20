#!/usr/bin/env bash
# S06 bdd-gen: arm별 입력 번들(td.bundle build: 조립 + A1 검사 + 서명) -> rep별 BDD generation(LLM, 최대 2회 수리).
# 실제 작업은 td.bddgen이 한다(설계 §6.6). 모든 claude 호출은 pipeline/lib/llm.sh 하나를 거친다.
# 산출물: S06/{bundles/<arm>/, bdd-gen.json, work/<genId>/(LLM 원본 응답, 검증 로그, 수리 프롬프트), stage.log}
#         스냅샷 e2e/generated/<sut>/<arm>/<genId>/{features/, glue/, _COMPLETE}
# 단계 JSON: arms.<arm>{status, reason, generations}, generations.<genId>{arm, rep, status, reason, reused, repairs, dir}
# run.json: arms.generations, arms.style, inputs
# 옵션: arms/reps는 run.json options, --regenerate는 TD_REGENERATE(run-all이 내보낸다).
# 사용: S06-bdd-gen.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

td_stage_begin S06
td_hook S06
: "${TD_RUN_DIR:?}" "${TD_SUT_FILE:?}" "${TD_SUT_SRC:?}"

mkdir -p "$TD_RUN_DIR/S06"
s06_fail() { td_log "S06 failed: $1"; td_stage_end S06 failed "${1:0:1500}"; exit 1; }

# 중단 신호는 파이썬 쪽으로도 전달돼(같은 프로세스 그룹) 임시 디렉터리와 예약이 정리된다.
RESULT="$(td_py -m td.bddgen stage --run-dir "$TD_RUN_DIR" --sut-file "$TD_SUT_FILE" --sut-src "$TD_SUT_SRC" \
  2> >(tee "$TD_RUN_DIR/S06/stage.log" >&2))" || s06_fail "td.bddgen 실행 실패: $(tail -c 600 "$TD_RUN_DIR/S06/stage.log")"
jq -e . >/dev/null 2>&1 <<< "$RESULT" || s06_fail "td.bddgen 출력이 JSON이 아니다: ${RESULT:0:300}"

STATUS="$(jq -r '.status' <<< "$RESULT")"
REASON="$(jq -r '.reason // empty' <<< "$RESULT")"
EXTRA="$(jq -c '.extra' <<< "$RESULT")"
OUTPUTS="$(jq -c '.outputs' <<< "$RESULT")"
td_log "S06 $STATUS ${REASON:0:300}"
if [[ "$STATUS" == "passed" ]]; then
  td_stage_end S06 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
else
  td_stage_end S06 "$STATUS" "${REASON:-$STATUS}" --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
fi
[[ "$STATUS" != "failed" ]] || exit 1
