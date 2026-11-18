#!/usr/bin/env bash
# 파이프라인 공통 함수. 단계 스크립트와 run-all.sh가 source한다.
# 상태 기록, 훅 판정, 시간 제한은 td(파이썬)에 맡기고 여기서는 얇은 래퍼만 둔다.

TD_ROOT="${TD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
TD_WORK_DIR="${TD_WORK_DIR:-$TD_ROOT/work}"
export TD_ROOT TD_WORK_DIR

# site-gen의 venv 파이썬을 직접 쓰고(호출당 수십 ms), 없으면 uv가 만든다.
# PYTHONPATH로 `python -m td.<module>`이 항상 동작한다.
td_py() {
  local venv_python="$TD_ROOT/site-gen/.venv/bin/python"
  if [[ -x "$venv_python" ]]; then
    PYTHONPATH="$TD_ROOT/site-gen${PYTHONPATH:+:$PYTHONPATH}" "$venv_python" "$@"
  else
    PYTHONPATH="$TD_ROOT/site-gen${PYTHONPATH:+:$PYTHONPATH}" \
      uv run --project "$TD_ROOT/site-gen" --quiet python "$@"
  fi
}

# td_run <timeout_sec> -- cmd...
# 새 프로세스 그룹으로 실행하고, 시간이 넘으면 그룹에 TERM, 10초 뒤 KILL한다.
# 시간 초과: 종료 코드 124, stderr에 `timeout:<cmd>` 사유.
td_run() {
  local timeout_sec="$1"
  shift
  [[ "${1:-}" == "--" ]] && shift
  td_py -m td.proc run "$timeout_sec" -- "$@"
}

td_log() { printf '[td] %s\n' "$*" >&2; }

# --- 단계 수명주기 ------------------------------------------------------------------
td_stage_begin() { td_py -m td.state begin "${TD_RUN_DIR:?TD_RUN_DIR가 필요하다}" "$1"; }

# td_stage_end ID status [reason]   (status: passed|failed|degraded|skipped)
td_stage_end() { td_py -m td.state end "${TD_RUN_DIR:?TD_RUN_DIR가 필요하다}" "$@"; }

# td_hook ID[:point] — TD_FAIL_STAGE에 걸리면 단계를 failed로 기록하고 이 단계 스크립트를 끝낸다.
td_hook() {
  local spec="$1" stage_id point=""
  stage_id="${spec%%:*}"
  [[ "$spec" == *:* ]] && point="${spec#*:}"
  local rc=0
  td_py -m td.hooks should-fail "$stage_id" $point || rc=$?
  case "$rc" in
    0) return 0 ;;
    10) td_stage_end "$stage_id" failed "injected failure (TD_FAIL_STAGE=$spec)"; exit 1 ;;
    *) td_stage_end "$stage_id" failed "hook refused: TD_FAIL_STAGE requires TD_SITE_PREFIX"; exit 1 ;;
  esac
}
