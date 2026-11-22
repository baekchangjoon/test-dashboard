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

# td_java_home <version> — macOS는 /usr/libexec/java_home, 그 밖에는 JAVA_HOME_<version> 환경 변수. 없으면 return 1.
td_java_home() {
  local version="${1:?version}" found="" var="JAVA_HOME_${1}"
  if [[ -x /usr/libexec/java_home ]]; then found="$(/usr/libexec/java_home -v "$version" 2>/dev/null)" || found=""; fi
  [[ -n "$found" ]] || found="${!var:-}"
  [[ -n "$found" ]] || return 1
  printf '%s\n' "$found"
}

td_log() { printf '[td] %s\n' "$*" >&2; }

# td_tail_chars <n> — stdin의 마지막 n "문자"를 낸다(바이트가 아니다). 사유 문자열을 자를 때 쓴다.
# `tail -c`는 UTF-8 다중 바이트 문자를 쪼개 td.state 기록이 UnicodeEncodeError로 깨지고, `${var: -n}`은 n보다 짧으면 빈 문자열이 된다.
# 잘못된 바이트는 U+FFFD로 바꾼다.
td_tail_chars() {
  td_py -c 'import sys; n = int(sys.argv[1]); text = sys.stdin.buffer.read().decode("utf-8", "replace"); sys.stdout.write(text[-n:] if n > 0 else "")' "${1:?n}"
}

# td_arm_requested <arm> — 이 run(run.json options.arms, 없으면 td.state 기본 arm 목록)이 그 arm을 요청했으면 0, 아니면 1.
td_arm_requested() {
  td_py -c 'import sys
from td import state
sys.exit(0 if sys.argv[2] in state.requested_arms(sys.argv[1]) else 1)' "${TD_RUN_DIR:?TD_RUN_DIR가 필요하다}" "${1:?arm}"
}

# fetch_git_tool <dir> <gh|https> <repo-slug> <pin-commit>
# git 도구: 없으면 clone, 고정 커밋이 없으면 fetch, 그리고 detach checkout. 전체 sha를 stdout에 낸다(실패 return 1).
# (전역 git hook이 clone/checkout마다 .codegraph를 만들어 도구 소스를 오염시키므로 core.hooksPath를 끈다)
fetch_git_tool() {
  local dir="$1" mode="$2" slug="$3" pin="$4"
  if [[ ! -d "$dir/.git" ]]; then
    if [[ "$mode" == "gh" ]]; then td_run 600 -- gh repo clone "$slug" "$dir" -- --quiet -c core.hooksPath=/dev/null >&2
    else td_run 600 -- git -c core.hooksPath=/dev/null clone --quiet "https://github.com/$slug.git" "$dir" >&2; fi || return 1
  elif ! git -C "$dir" cat-file -e "${pin}^{commit}" 2>/dev/null; then
    td_run 600 -- git -c core.hooksPath=/dev/null -C "$dir" fetch --quiet --tags origin >&2 || return 1
  fi
  td_run 120 -- git -c core.hooksPath=/dev/null -C "$dir" checkout --detach --force --quiet "${pin}^{commit}" >&2 || return 1
  git -C "$dir" rev-parse HEAD
}

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
    3) td_stage_end "$stage_id" failed "hook refused: TD_FAIL_STAGE requires TD_SITE_PREFIX"; exit 1 ;;
    *) td_stage_end "$stage_id" failed "hook error: td.hooks exited $rc"; exit 1 ;;
  esac
}
