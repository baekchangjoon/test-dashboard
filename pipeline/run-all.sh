#!/usr/bin/env bash
# run-all.sh <sut> [--sut-file F] [--only IDS] [--arms LIST] [--reps N] [--style cucumber] [--regenerate]
# 종료 코드: S00 또는 S13 실패 1, 그 밖의 단계 실패 2, 실패 없음 0. SUT 해석 실패는 1(run 디렉터리 없음).
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

usage() { echo "usage: run-all.sh <sut> [--sut-file F] [--only IDS] [--arms LIST] [--reps N] [--style cucumber] [--regenerate]" >&2; exit 1; }
die() { echo "run-all: $*" >&2; exit 1; }

[[ $# -ge 1 ]] || usage
SUT="$1"; shift
SUT_FILE="" ONLY="" ARMS="base,jqa,owl" REPS=3 STYLE="cucumber" REGENERATE=false
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
# 옵션 검증(run 디렉터리 예약 전)
[[ "$REPS" =~ ^[1-9]$ ]] || die "--reps는 1~9여야 한다: $REPS"
[[ "$STYLE" != "junit" ]] || die "--style junit은 아직 지원하지 않는다(REQ-030 연기): 지금은 cucumber만 생성한다"
[[ "$STYLE" == "cucumber" ]] || die "--style은 cucumber여야 한다: $STYLE"
IFS=',' read -r -a arm_list <<< "$ARMS"
[[ ${#arm_list[@]} -gt 0 ]] || die "--arms가 비었다"
for arm in "${arm_list[@]}"; do
  [[ "$arm" == "base" || "$arm" == "jqa" || "$arm" == "owl" ]] || die "--arms는 base,jqa,owl 중에서만 고른다: '$arm'"
done
if [[ -n "$ONLY" ]]; then
  IFS=',' read -r -a only_list <<< "$ONLY"
  for stage_id in "${only_list[@]}"; do
    [[ "$stage_id" =~ ^S(0[0-9]|1[0-3])$ ]] || die "--only는 S00..S13만 받는다: '$stage_id'"
  done
fi
[[ -n "$SUT_FILE" ]] || SUT_FILE="$TD_ROOT/suts/$SUT/sut.yaml"
[[ -f "$SUT_FILE" ]] || die "sut 파일이 없다: $SUT_FILE"

# 테스트 전용 훅·스텁 단계는 TD_SITE_PREFIX(테스트 격리) 없이는 거부한다.
if [[ -n "${TD_FAIL_STAGE:-}" || -n "${TD_STAGE_DIR:-}" ]]; then
  [[ -n "${TD_SITE_PREFIX:-}" ]] || die "TD_FAIL_STAGE/TD_STAGE_DIR는 TD_SITE_PREFIX가 있는 테스트 실행에서만 허용된다"
fi
STAGE_DIR="${TD_STAGE_DIR:-$TD_ROOT/pipeline}"

# --- SUT 커밋 해석(run 디렉터리 예약 전) -------------------------------------------------
SUT_VARS="$(td_py -m td.sutsrc "$SUT_FILE")" || die "sut 파일을 읽지 못했다: $SUT_FILE"
eval "$SUT_VARS"
# 게시 경로와 단계 인자는 인자 $SUT를 쓰므로 설명 파일의 name과 다르면 다른 SUT 이름으로 게시된다. 시작 전에 거부한다.
[[ "$SUT" == "$SUT_NAME" ]] || die "sut 인자($SUT)가 설명 파일 name($SUT_NAME)과 다르다: $SUT_FILE"
SRC_DIR="$TD_WORK_DIR/suts/$SUT_NAME/src"
mkdir -p "$(dirname "$SRC_DIR")"
if [[ -d "$SRC_DIR/.git" ]]; then
  td_run 600 -- git -c core.hooksPath=/dev/null -C "$SRC_DIR" fetch --tags --prune origin >&2 || die "SUT fetch 실패: $SUT_REPO"
else
  td_run 600 -- git -c init.templateDir= -c core.hooksPath=/dev/null clone "$SUT_REPO" "$SRC_DIR" >&2 || die "SUT clone 실패: $SUT_REPO"
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

# 상태 기록이 실패하면 단계를 조용히 빠뜨리지 않는다. 단계를 failed로 기록하고, 그것마저 안 되면
# run.json 자체를 쓸 수 없는 것이므로 run을 종료 코드 1로 중단한다.
state_failed() { # <stage_id> <what> <message>
  local msg="state error: $2: $3"
  td_log "$1 $msg"
  td_py -m td.state end "$RUN_DIR" "$1" failed "$msg" 2>/dev/null \
    || { echo "run-all: run.json을 쓸 수 없어 run을 중단한다 ($msg)" >&2; exit 1; }
}

# Ctrl-C/TERM: 바로 종료하지 않고 표시만 한다. 단계 스크립트(같은 프로세스 그룹)가 컨테이너와 PID를 정리하고
# 돌아오면 그 단계를 failed, 남은 단계를 skipped로 기록하고 run.json을 마감한 뒤 계약 종료 코드(0/1/2)로 끝낸다.
# (bash는 전경 자식이 끝난 뒤에 trap을 실행하므로 정리 중에 run-all이 먼저 빠져나가지 않는다)
INTERRUPTED=""
trap 'INTERRUPTED=1; echo "run-all: interrupted, 단계 정리 후 기록하고 종료" >&2' INT TERM

ABORTED=""
for stage_id in "${ORDER[@]}"; do
  if ! requested "$stage_id"; then
    out="$(td_py -m td.state skip "$RUN_DIR" "$stage_id" "not-requested" 2>&1)" || state_failed "$stage_id" skip "$out"
    continue
  fi
  if [[ -n "$INTERRUPTED" ]]; then
    out="$(td_py -m td.state skip "$RUN_DIR" "$stage_id" "run interrupted" 2>&1)" || state_failed "$stage_id" skip "$out"
    continue
  fi
  if [[ -n "$ABORTED" ]]; then
    out="$(td_py -m td.state skip "$RUN_DIR" "$stage_id" "aborted: $ABORTED failed" 2>&1)" || state_failed "$stage_id" skip "$out"
    continue
  fi
  decision="$(td_py -m td.state prepare "$RUN_DIR" "$stage_id" 2>&1)"
  prepare_rc=$?
  if [[ $prepare_rc -ne 0 ]]; then state_failed "$stage_id" prepare "$decision"; continue; fi
  case "$decision" in
    run) ;;
    skip) continue ;;
    *) state_failed "$stage_id" prepare "unexpected output '$decision'"; continue ;;
  esac
  script=("$STAGE_DIR/$stage_id"-*.sh)
  if [[ ! -x "${script[0]}" ]]; then
    state_failed "$stage_id" run "stage script not found in $STAGE_DIR"; continue
  fi
  "${script[0]}" "$SUT" "$RUN_ID"
  script_rc=$?
  if [[ -n "$INTERRUPTED" ]]; then
    # 신호로 끊긴 단계: 아직 running이면 failed로 마감한다(이미 끝난 상태는 그대로 둔다). post 훅은 건너뛴다.
    current="$(td_py -c "import sys;from td.state import stage_status;print(stage_status(sys.argv[1],sys.argv[2]) or '')" "$RUN_DIR" "$stage_id" 2>&1)" || current=""
    if [[ "$current" == "running" || -z "$current" ]]; then
      td_py -m td.state end "$RUN_DIR" "$stage_id" failed "interrupted (signal)" || state_failed "$stage_id" interrupt "end failed"
    fi
    continue
  fi
  if [[ $script_rc -ne 0 ]]; then
    current="$(td_py -c "import sys;from td.state import stage_status;print(stage_status(sys.argv[1],sys.argv[2]) or '')" "$RUN_DIR" "$stage_id" 2>&1)" \
      || { state_failed "$stage_id" read "$current"; continue; }
    if [[ "$current" != "failed" ]]; then
      state_failed "$stage_id" run "stage script exited $script_rc"
    fi
  fi
  out="$(td_py -m td.state post "$RUN_DIR" "$stage_id" 2>&1)" || state_failed "$stage_id" post "$out"
  if [[ "$stage_id" == "S00" ]]; then
    code="$(td_py -m td.state exit-code "$RUN_DIR" 2>&1)" || die "exit-code 판정 실패: $code"
    [[ "$code" == "1" ]] && ABORTED="S00"
  fi
done

# 모든 단계에 기록이 있어야 한다.
missing="$(td_py -c 'import sys;from td.state import STAGE_IDS,stage_path;print(" ".join(s for s in STAGE_IDS if not stage_path(sys.argv[1],s).exists()))' "$RUN_DIR" 2>&1)" \
  || die "단계 기록 점검 실패: $missing"
for stage_id in $missing; do state_failed "$stage_id" record "no stage record was written"; done

out="$(td_py -m td.state finalize "$RUN_DIR" 2>&1)" || die "finalize 실패: $out"
RC="$(td_py -m td.state exit-code "$RUN_DIR" 2>&1)" || die "exit-code 판정 실패: $RC"
[[ "$RC" =~ ^[0-2]$ ]] || die "exit-code 판정 결과가 이상하다: $RC"
echo "run-all: finished runId=$RUN_ID exit=$RC" >&2
echo "$RUN_ID"
exit "$RC"
