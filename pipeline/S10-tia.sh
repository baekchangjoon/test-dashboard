#!/usr/bin/env bash
# S10 tia: 최근 커밋 범위(base = first-parent HEAD~10)의 TIA 리포트를 만든다.
# 절차(설계 §6.11): base worktree -> base 빌드 -> SUT 기동 -> base의 blackboxTest(per-test .exec) ->
#   tia convert -> tia index -> git diff base..HEAD -> tia impact -> tia report.
# 산출물: S10/{base/(실행 중에만), tia-base/{exec,junit,...}, testwise.json, tia.db, base-head.diff, impact.json, scenarios.json, tia/tia.html}
# 사용: S10-tia.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/blackbox.sh"

td_stage_begin S10
td_hook S10
: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"

S10_DIR="$TD_RUN_DIR/S10"
BASE_DIR="$S10_DIR/base"
TIA_OUT="$S10_DIR/tia"
mkdir -p "$S10_DIR" "$TIA_OUT"

# base worktree는 어떤 종료 경로(실패, 시그널)에서도 지운다. 명시 호출도 하므로 멱등이어야 한다(REQ-011).
s10_cleanup() {
  td_sut_down
  if [[ -e "$BASE_DIR" ]] || git -C "$TD_SUT_SRC" worktree list --porcelain 2>/dev/null | grep -qF "worktree $BASE_DIR"; then
    td_run 120 -- git -C "$TD_SUT_SRC" worktree remove --force "$BASE_DIR" >/dev/null 2>&1 || true
    rm -rf "$BASE_DIR"
    td_run 60 -- git -C "$TD_SUT_SRC" worktree prune >/dev/null 2>&1 || true
  fi
}
td_on_exit 's10_cleanup'

s10_fail() { td_log "S10 failed: $1"; s10_cleanup; td_stage_end S10 failed "${1:0:1500}"; exit 1; }
sut_get() { td_py -m td.sut_config get "$TD_SUT_FILE" "$1"; }

S00_JSON="$TD_RUN_DIR/stages/S00.json"
[[ -f "$S00_JSON" ]] || s10_fail "S00 산출물이 없다"
TOOLS_DIR="$(jq -r '.outputs.toolsDir // empty' "$S00_JSON")"
HEAD_COMMIT="$(jq -r '.outputs.commit // empty' "$S00_JSON")"
TIA_BIN="$TOOLS_DIR/tia/bin/tia"
[[ -x "$TIA_BIN" ]] || s10_fail "tia CLI가 없다: $TIA_BIN"
[[ -n "$HEAD_COMMIT" ]] || s10_fail "S00 commit 출력이 없다"
TIA_JAVA="$(td_java_home 17)" || s10_fail "JDK 17을 찾지 못했다(tia CLI 실행에 필요)"
SUT_JAVA_HOME="$(td_java_home "$(sut_get java)")" || s10_fail "SUT가 요구하는 JDK $(sut_get java)를 찾지 못했다"
tia() { (cd "$S10_DIR" && td_run "${TIA_TIMEOUT:-300}" -- env JAVA_HOME="$TIA_JAVA" "$TIA_BIN" "$@"); }

# --- base 해석 ----------------------------------------------------------------------------------
BASE="$(td_py -m td.tia resolve-base --sut-file "$TD_SUT_FILE" --repo "$TD_SUT_SRC" --commit "$HEAD_COMMIT" 2>"$S10_DIR/resolve-base.log")" \
  || s10_fail "base 해석 실패: $(tail -c 500 "$S10_DIR/resolve-base.log")"
td_log "S10 base=$BASE head=$HEAD_COMMIT"

# --- base worktree(훅 비활성, detach) -----------------------------------------------------------------
td_run 300 -- git -c core.hooksPath=/dev/null -C "$TD_SUT_SRC" worktree add --detach "$BASE_DIR" "$BASE" >"$S10_DIR/worktree.log" 2>&1 \
  || s10_fail "base worktree 생성 실패: $(tail -c 500 "$S10_DIR/worktree.log")"

REASONS=()
BB_RAN=0
BB_EXTRA_JSON='{}'
PRECHECK="$(td_py -m td.tia precheck "$BASE_DIR" 2>&1)" || s10_fail "base 사전 검사 실패: ${PRECHECK:0:500}"
if [[ -n "$PRECHECK" ]]; then
  REASONS+=("blackbox suite skipped: $(tr '\n' ';' <<< "$PRECHECK" | sed 's/;$//')")
  td_log "S10 ${REASONS[0]}"
else
  # --- base 빌드(JDK 17, --no-daemon은 sut.yaml build.cmd에 있다) ---------------------------------------
  BUILD_CMD="$(sut_get build.cmd)" || s10_fail "sut.yaml build.cmd를 읽지 못했다"
  (cd "$BASE_DIR" && td_run 1800 -- env JAVA_HOME="$SUT_JAVA_HOME" bash -c "$BUILD_CMD") >"$S10_DIR/base-build.log" 2>&1 \
    || s10_fail "base 빌드 실패: $(tail -c 500 "$S10_DIR/base-build.log" | tr '\n' ' ')"
  BASE_JAR="$(compgen -G "$BASE_DIR/$(sut_get jar)" | head -1)"
  [[ -f "$BASE_JAR" ]] || s10_fail "base jar를 찾지 못했다: $(sut_get jar)"

  # --- SUT 기동 + base 블랙박스(관대한 판정: 수량은 기록만) ------------------------------------------------
  TD_SUT_JAR="$BASE_JAR" td_blackbox_suite S10 tia-base "$BASE_DIR" "$SUT_JAVA_HOME" 1 || true
  [[ "$BB_STATUS" == "passed" ]] || s10_fail "base 블랙박스 실패: ${BB_REASON:-상태 없음}"
  BB_RAN=1
  BB_EXTRA_JSON="$BB_EXTRA"
fi

# M1에는 e2e 스위트가 없다(Task 22가 붙인다). e2e가 붙기 전에는 블랙박스만으로 끝나므로 degraded다.
REASONS+=("e2e suites not attached")
REASON_TEXT="$(printf '%s; ' "${REASONS[@]}")"; REASON_TEXT="${REASON_TEXT%; }"

if [[ "$BB_RAN" != "1" ]]; then
  s10_cleanup
  td_stage_end S10 degraded "$REASON_TEXT" --extra-json "$(jq -cn --arg base "$BASE" --arg head "$HEAD_COMMIT" '{base: $base, head: $head, blackboxSkipped: true}')"
  exit 0
fi

# --- convert, index ------------------------------------------------------------------------------------
CLASSES_REL="$(sut_get classes)"
# in-process 스레드 커버리지 손실 TC(ConcurrencyBlackBoxIT 등, expected-tests.yaml no_attribution)는 convert를 막지 않고 기록만 한다.
tia convert --allow-incomplete --exec-dir "$S10_DIR/tia-base/exec" --classes "$BASE_DIR/$CLASSES_REL" --out "$S10_DIR/testwise.json" >"$S10_DIR/convert.log" 2>&1 \
  || s10_fail "tia convert 실패: $(tail -c 500 "$S10_DIR/convert.log" | tr '\n' ' ')"
INCOMPLETE="$(sed -n 's/^ *incomplete  *//p' "$S10_DIR/convert.log" | jq -R . | jq -cs .)"
rm -f "$S10_DIR/tia.db"
tia index --report "$S10_DIR/testwise.json" --repo "$(sut_get name)" --commit "$BASE" --db "$S10_DIR/tia.db" >"$S10_DIR/index.log" 2>&1 \
  || s10_fail "tia index 실패: $(tail -c 500 "$S10_DIR/index.log" | tr '\n' ' ')"

# --- diff, impact --------------------------------------------------------------------------------------
# tia는 diff의 old-side 라인이 인덱싱 커밋(base)과 같은 공간이어야 한다. 라인 번호 대조용이라 --unified=0을 쓴다.
td_run 120 -- git -C "$TD_SUT_SRC" diff --unified=0 "$BASE" "$HEAD_COMMIT" >"$S10_DIR/base-head.diff" 2>"$S10_DIR/diff.log" \
  || s10_fail "git diff 실패: $(tail -c 300 "$S10_DIR/diff.log")"
tia impact --db "$S10_DIR/tia.db" --commit "$BASE" --diff-file "$S10_DIR/base-head.diff" --format json >"$S10_DIR/impact.json" 2>"$S10_DIR/impact.log" \
  || s10_fail "tia impact 실패: $(tail -c 500 "$S10_DIR/impact.log" | tr '\n' ' ')"
SUMMARY="$(td_py -m td.tia scenarios --impact "$S10_DIR/impact.json" --diff "$S10_DIR/base-head.diff" --testwise "$S10_DIR/testwise.json" \
  --out "$S10_DIR/scenarios.json" --base "$BASE" --head "$HEAD_COMMIT" 2>"$S10_DIR/scenarios.log")" \
  || s10_fail "scenarios.json 생성 실패: $(tail -c 500 "$S10_DIR/scenarios.log")"

# --- report ---------------------------------------------------------------------------------------------
(cd "$BASE_DIR/$(sut_get sources)" && find . -name '*.java' | sed 's#^\./##' | sort) >"$S10_DIR/prod-files.txt"
PACKAGE_PREFIX="$(sut_get packages)"; PACKAGE_PREFIX="${PACKAGE_PREFIX%.\*}"; PACKAGE_PREFIX="${PACKAGE_PREFIX//.//}/"
tia report --testwise "$S10_DIR/testwise.json" --scenarios "$S10_DIR/scenarios.json" --prod-files "$S10_DIR/prod-files.txt" \
  --commit "$BASE" --out "$TIA_OUT/tia.html" --sut-name "$(sut_get name)" --prefix-strip "$PACKAGE_PREFIX" >"$S10_DIR/report.log" 2>&1 \
  || s10_fail "tia report 실패: $(tail -c 500 "$S10_DIR/report.log" | tr '\n' ' ')"
[[ -s "$TIA_OUT/tia.html" ]] || s10_fail "tia.html이 비었다"

s10_cleanup  # 단계 JSON을 쓰기 전에 worktree를 지우고, 남았는지 확인한다(REQ-011)
if git -C "$TD_SUT_SRC" worktree list --porcelain | grep -qF "$BASE_DIR" || [[ -e "$BASE_DIR" ]]; then
  s10_fail "base worktree가 남아 있다: $BASE_DIR"
fi
EXTRA="$(jq -cn --arg base "$BASE" --arg head "$HEAD_COMMIT" --arg range "$(sut_get tia.range)" --argjson bb "$BB_EXTRA_JSON" --argjson impact "$SUMMARY" --argjson incomplete "${INCOMPLETE:-[]}" \
  '$bb + {base: $base, head: $head, range: $range, impact: $impact, incompleteAttribution: $incomplete}')"
td_stage_end S10 degraded "$REASON_TEXT" --outputs-json "$(jq -cn --arg dir "$TIA_OUT" '{tia: $dir}')" --extra-json "$EXTRA"
