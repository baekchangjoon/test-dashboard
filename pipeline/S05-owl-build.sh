#!/usr/bin/env bash
# S05 owl-build: jQA JSON(S03) + 정제 bbtg(S02) -> 결정적 OWL 골격 -> LLM 보강(llm.sh, 최대 2회 수리) -> pySHACL 검증.
# 실제 작업은 td.ontology_owl이 한다(설계 §6.5 S05). LLM 결과는 입력 키 스냅샷(ontology/generated/<sut>/<key8>/)으로
# 재사용한다(같은 입력이면 claude 0회).
# 산출물: S05/{skeleton.ttl, bundle/, ontology-owl.ttl, ontology-owl.json, owl-gen.json, work/, stage.log}
# 사용: S05-owl-build.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

td_stage_begin S05
td_hook S05
: "${TD_RUN_DIR:?}" "${TD_SUT_FILE:?}" "${TD_SUT_SRC:?}"

mkdir -p "$TD_RUN_DIR/S05"
s05_fail() { td_log "S05 failed: $1"; td_stage_end S05 failed "${1:0:1500}"; exit 1; }

# 중단 신호는 파이썬 쪽으로도 전달돼(같은 프로세스 그룹) 임시 디렉터리와 예약이 정리된다.
RESULT="$(td_py -m td.ontology_owl stage --run-dir "$TD_RUN_DIR" --sut-file "$TD_SUT_FILE" --sut-src "$TD_SUT_SRC" \
  2> >(tee "$TD_RUN_DIR/S05/stage.log" >&2))" || s05_fail "td.ontology_owl 실행 실패: $(tail -c 600 "$TD_RUN_DIR/S05/stage.log")"
jq -e . >/dev/null 2>&1 <<< "$RESULT" || s05_fail "td.ontology_owl 출력이 JSON이 아니다: ${RESULT:0:300}"

STATUS="$(jq -r '.status' <<< "$RESULT")"
REASON="$(jq -r '.reason // empty' <<< "$RESULT")"
EXTRA="$(jq -c '.extra' <<< "$RESULT")"
OUTPUTS="$(jq -c '.outputs' <<< "$RESULT")"
td_log "S05 $STATUS ${REASON:0:300}"
if [[ "$STATUS" == "passed" ]]; then
  td_stage_end S05 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
else
  td_stage_end S05 "$STATUS" "${REASON:-$STATUS}" --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
fi
[[ "$STATUS" != "failed" ]] || exit 1
