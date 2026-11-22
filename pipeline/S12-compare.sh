#!/usr/bin/env bash
# S12 compare: arm별 generation 지표를 모아 compare.json(스키마 검증)과 compare.html을 만들고 판정한다(설계 §6.12).
# 입력: S03/ontology-jqa.json(엔드포인트 분모), S06/bdd-gen.json, S07/<genId>/summary.json, S08/coverage.json(+귀속 XML),
#       suts/<sut>/{oracle.yaml, sut.yaml(compare.focus)}. 오라클은 평가 전용이다(번들 쪽은 S06의 content 검사가 막는다).
# 산출물: S12/compare/{compare.json,compare.html}, det 시각화가 있으면 det-viz.json·det.html, run.json kpis.compare(판정 요약).
# 사용: S12-compare.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

td_stage_begin S12
td_hook S12
: "${TD_RUN_DIR:?}" "${TD_SUT_FILE:?}"

s12_fail() { td_log "S12 failed: $1"; td_stage_end S12 failed "${1:0:1500}"; exit 1; }
mkdir -p "$TD_RUN_DIR/S12"
RESULT="$(td_py -m td.compare run "$TD_RUN_DIR" --sut-file "$TD_SUT_FILE" 2>"$TD_RUN_DIR/S12/compare.log")" \
  || s12_fail "td.compare 실행 실패: $(tail -c 600 "$TD_RUN_DIR/S12/compare.log")"
jq -e . >/dev/null 2>&1 <<< "$RESULT" || s12_fail "td.compare 출력이 JSON이 아니다: $(head -c 300 <<< "$RESULT")"
STATUS="$(jq -r '.status' <<< "$RESULT")"
if [[ "$STATUS" != "passed" ]]; then
  s12_fail "$(jq -r '.reason // "알 수 없는 실패"' <<< "$RESULT")"
fi
td_stage_end S12 passed --outputs-json "$(jq -c '.outputs' <<< "$RESULT")" --extra-json "$(jq -c '.extra' <<< "$RESULT")"
