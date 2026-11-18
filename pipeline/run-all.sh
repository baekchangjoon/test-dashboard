#!/usr/bin/env bash
# run-all.sh <sut> [--sut-file F] [--only IDS] [--arms LIST] [--reps N] [--style cucumber] [--regenerate]
# 종료 코드: S00 또는 S13 실패 1, 그 밖의 단계 실패 2, 실패 없음 0. SUT 해석 실패는 1(run 디렉터리 없음).
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

usage() { echo "usage: run-all.sh <sut> [--sut-file F] [--only IDS] [--arms LIST] [--reps N] [--style cucumber] [--regenerate]" >&2; exit 1; }
die() { echo "run-all: $*" >&2; exit 1; }

[[ $# -ge 1 ]] || usage
SUT="$1"; shift
SUT_FILE="" ONLY="" ARMS="base,jqa,owl" REPS=1 STYLE="cucumber" REGENERATE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sut-file) SUT_FILE="${2:?}"; shift 2 ;;
    --only) ONLY="${2:?}"; shift 2 ;;
    --arms) ARMS="${2:?}"; shift 2 ;;
    --reps) REPS="${2:?}"; shift 2 ;;
    --style) STYLE="${2:?}"; shift 2 ;;
    --regenerate) REGENERATE=true; shift ;;
    *) usage ;;
  esac
done
[[ "$REPS" =~ ^[1-9]$ ]] || die "--reps는 1~9여야 한다: $REPS"
[[ -n "$SUT_FILE" ]] || SUT_FILE="$TD_ROOT/suts/$SUT/sut.yaml"
[[ -f "$SUT_FILE" ]] || die "sut 파일이 없다: $SUT_FILE"

# 테스트 전용 훅·스텁 단계는 TD_SITE_PREFIX(테스트 격리) 없이는 거부한다.
if [[ -n "${TD_FAIL_STAGE:-}" || -n "${TD_STAGE_DIR:-}" ]]; then
  [[ -n "${TD_SITE_PREFIX:-}" ]] || die "TD_FAIL_STAGE/TD_STAGE_DIR는 TD_SITE_PREFIX가 있는 테스트 실행에서만 허용된다"
fi
STAGE_DIR="${TD_STAGE_DIR:-$TD_ROOT/pipeline}"

# --- SUT 커밋 해석(run 디렉터리 예약 전) -------------------------------------------------
eval "$(td_py -m td.sutsrc "$SUT_FILE")" || die "sut 파일을 읽지 못했다: $SUT_FILE"
SRC_DIR="$TD_WORK_DIR/suts/$SUT_NAME/src"
mkdir -p "$(dirname "$SRC_DIR")"
if [[ -d "$SRC_DIR/.git" ]]; then
  td_run 600 -- git -C "$SRC_DIR" fetch --tags --prune origin >&2 || die "SUT fetch 실패: $SUT_REPO"
else
  td_run 600 -- git -c init.templateDir= clone "$SUT_REPO" "$SRC_DIR" >&2 || die "SUT clone 실패: $SUT_REPO"
fi
COMMIT=""
for candidate in "origin/$SUT_REF" "refs/tags/$SUT_REF" "$SUT_REF"; do
  COMMIT="$(git -C "$SRC_DIR" rev-parse --verify --quiet "${candidate}^{commit}")" && break
  COMMIT=""
done
[[ -n "$COMMIT" ]] || die "ref를 커밋으로 해석하지 못했다: $SUT_REF ($SUT_REPO)"

# --- run 예약과 메타 ------------------------------------------------------------------
TRIGGER="${TD_TRIGGER:-manual}"
RUN_ID="$(td_py -m td.runid new --commit "$COMMIT" --trigger "$TRIGGER" --runs-root "$TD_WORK_DIR/runs")" || die "runId 예약 실패"
RUN_DIR="$TD_WORK_DIR/runs/$RUN_ID"
OPTIONS_JSON="$(td_py - "$ARMS" "$REPS" "$STYLE" "$REGENERATE" "$ONLY" <<'PY'
import json, sys
arms, reps, style, regenerate, only = sys.argv[1:6]
print(json.dumps({"arms": arms.split(","), "reps": int(reps), "style": style,
                  "regenerate": regenerate == "true", "only": only.split(",") if only else None}))
PY
)"
td_py -m td.state init "$RUN_DIR" --run-id "$RUN_ID" --sut "$SUT_NAME" --commit "$COMMIT" \
  --trigger "$TRIGGER" --options-json "$OPTIONS_JSON" || die "run.json 초기화 실패"
mkdir -p "$RUN_DIR/stages" "$RUN_DIR/pids"
echo "run-all: runId=$RUN_ID sut=$SUT_NAME commit=${COMMIT:0:7}" >&2

export TD_RUN_DIR="$RUN_DIR" TD_RUN_ID="$RUN_ID" TD_SUT_NAME="$SUT_NAME" TD_SUT_COMMIT="$COMMIT" \
  TD_SUT_FILE="$SUT_FILE" TD_SUT_SRC="$SRC_DIR" TD_ARMS="$ARMS" TD_REPS="$REPS" TD_STYLE="$STYLE" \
  TD_REGENERATE="$REGENERATE"

# 실행 순서는 td.state.EXECUTION_ORDER가 정한다(S04는 S05 뒤).
# (macOS 기본 bash 3.2에는 mapfile이 없다)
ORDER=()
while IFS= read -r line; do ORDER+=("$line"); done < <(td_py -c 'from td.state import EXECUTION_ORDER; print("\n".join(EXECUTION_ORDER))')
requested() { [[ -z "$ONLY" ]] || [[ ",$ONLY," == *",$1,"* ]]; }
ABORTED=""
for stage_id in "${ORDER[@]}"; do
  if ! requested "$stage_id"; then
    td_py -m td.state skip "$RUN_DIR" "$stage_id" "not-requested"; continue
  fi
  if [[ -n "$ABORTED" ]]; then
    td_py -m td.state skip "$RUN_DIR" "$stage_id" "aborted: $ABORTED failed"; continue
  fi
  decision="$(td_py -m td.state prepare "$RUN_DIR" "$stage_id")"
  [[ "$decision" == "run" ]] || continue
  script=("$STAGE_DIR/$stage_id"-*.sh)
  if [[ ! -x "${script[0]}" ]]; then
    td_py -m td.state end "$RUN_DIR" "$stage_id" failed "stage script not found in $STAGE_DIR"; continue
  fi
  "${script[0]}" "$SUT" "$RUN_ID"
  script_rc=$?
  if [[ $script_rc -ne 0 ]] && [[ "$(td_py -c "import sys;from td.state import stage_status;print(stage_status(sys.argv[1],sys.argv[2]) or '')" "$RUN_DIR" "$stage_id")" != "failed" ]]; then
    td_py -m td.state end "$RUN_DIR" "$stage_id" failed "stage script exited $script_rc"
  fi
  td_py -m td.state post "$RUN_DIR" "$stage_id"
  if [[ "$stage_id" == "S00" ]] && [[ "$(td_py -m td.state exit-code "$RUN_DIR")" == "1" ]]; then
    ABORTED="S00"
  fi
done

td_py -m td.state finalize "$RUN_DIR"
RC="$(td_py -m td.state exit-code "$RUN_DIR")"
echo "run-all: finished runId=$RUN_ID exit=$RC" >&2
echo "$RUN_ID"
exit "$RC"
