#!/usr/bin/env bash
# S04 onto-viz: S03(jQA)과 S05(OWL)가 만든 온톨로지 JSON을 단독으로 열리는 HTML 그래프(데이터와 Cytoscape 인라인)로 바꾼다.
# 입력: stages/S03.json, stages/S05.json의 outputs.ontology(둘 중 가용한 것). 산출물: S04/ontology/{jqa,owl}.html.
# 한쪽 입력만 있으면 그것만 그리고, 한쪽이 없다는 사실은 td.state post가 degraded로 기록한다(any_of 규칙).
# 사용: S04-onto-viz.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

td_stage_begin S04
td_hook S04
: "${TD_RUN_DIR:?}"

s04_fail() { td_log "S04 failed: $1"; td_stage_end S04 failed "${1:0:1500}"; exit 1; }

OUT_DIR="$TD_RUN_DIR/S04/ontology"
mkdir -p "$OUT_DIR"
RENDERED=()

# render_input <StageID> <variant> <기본 파일 이름>: 단계가 passed/degraded이고 산출물이 있으면 그린다.
render_input() {
  local stage_id="$1" variant="$2" default_name="$3" stage_json="$TD_RUN_DIR/stages/$1.json" status source rc=0
  [[ -f "$stage_json" ]] || return 0
  status="$(jq -r '.status // empty' "$stage_json")"
  [[ "$status" == "passed" || "$status" == "degraded" ]] || return 0
  source="$(jq -r '.outputs.ontology // empty' "$stage_json")"
  [[ -n "$source" ]] || source="$TD_RUN_DIR/$stage_id/$default_name"
  [[ -f "$source" ]] || s04_fail "$stage_id 산출물이 없다: $source"
  td_py -m td.ontology_html render "$source" "$OUT_DIR/$variant.html" --variant "$variant" 2>"$OUT_DIR/$variant.err" \
    || s04_fail "$variant 렌더 실패: $(tail -3 "$OUT_DIR/$variant.err")"
  rm -f "$OUT_DIR/$variant.err"
  RENDERED+=("$variant")
}

render_input S03 jqa ontology-jqa.json
render_input S05 owl ontology-owl.json
[[ ${#RENDERED[@]} -gt 0 ]] || s04_fail "시각화할 온톨로지 입력이 없다(S03, S05 모두 산출물 없음)"

OUTPUTS="$(jq -cn --arg ontology "$OUT_DIR" '{ontology: $ontology}')"
EXTRA="$(jq -cn '$ARGS.positional | {rendered: .}' --args "${RENDERED[@]}")"
td_stage_end S04 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
