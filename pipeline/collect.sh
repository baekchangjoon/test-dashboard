#!/usr/bin/env bash
# 과제 수집(설계 §6.3): 수집용 Sonar 토큰을 발급하고, td.collect를 자식으로 돌리고, 모든 종료 경로에서 토큰을 정리한다.
# 사용: collect.sh --config <dashboard.yaml> --site <접두까지 포함한 사이트 디렉터리> --suts-dir <dir>
# 표준 출력: td.collect의 결과 JSON 한 줄(정리 실패·발급 실패·주입은 amend로 degraded와 사유를 더한다).
# 종료 코드: td.collect를 따른다(설정 오류 2). 신호를 받으면 자식에 같은 신호를 보내고 기다린 뒤 정리하고 128+n.
# env.sh는 SUT 정리를 걸므로 쓰지 않는다. 장애 주입(TD_SITE_PREFIX가 있는 테스트 실행에서만):
#   TD_FAIL_STAGE=collect:exit1     출력 없이 종료 코드 1
#   TD_FAIL_STAGE=collect:garbage   JSON이 아닌 한 줄을 내고 종료 코드 0
#   TD_FAIL_STAGE=collect:degraded  정상으로 돌린 뒤 결과를 degraded(사유 "injected")로 바꾼다
#   TD_FAIL_STAGE=collect:cleanup-ssh  토큰 정리 SSH 실패(sonar-token.sh)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$TD_ROOT/pipeline/lib/sonar-token.sh"
export TD_SONAR_HOOK_STAGE=collect

collect_usage() { echo "usage: collect.sh --config <file> --site <dir> --suts-dir <dir>" >&2; exit 2; }
config_file="" site_dir="" suts_dir=""
while (($#)); do
  [[ $# -ge 2 ]] || collect_usage
  case "$1" in
    --config) config_file="$2" ;;
    --site) site_dir="$2" ;;
    --suts-dir) suts_dir="$2" ;;
    *) collect_usage ;;
  esac
  shift 2
done
[[ -n "$config_file" && -n "$site_dir" && -n "$suts_dir" ]] || collect_usage
collect_args=(--config "$config_file" --site "$site_dir" --suts-dir "$suts_dir")

# collect_hook <point>: 주입이 걸렸으면 0. 훅이 거부되면(TD_SITE_PREFIX 없음) 수집을 실패로 끝낸다.
collect_hook() {
  [[ -n "${TD_FAIL_STAGE:-}" ]] || return 1
  local rc=0
  td_py -m td.hooks should-fail collect "$1" || rc=$?
  case "$rc" in
    0) return 1 ;;
    10) return 0 ;;
    *) td_log "collect: 장애 주입 훅 거부 또는 오류(td.hooks 종료 코드 $rc)"; exit 1 ;;
  esac
}
if collect_hook exit1; then exit 1; fi
if collect_hook garbage; then echo "injected garbage: not a json line"; exit 0; fi

# --- 정리: 토큰 정리는 한 번만, 자식이 돌고 있으면 같은 신호를 넘기고 기다린다 ----------------------------
COLLECT_CHILD=""
COLLECT_OUT=""
COLLECT_REVOKED=""
COLLECT_REVOKE_FAILED=""

collect_revoke() {
  [[ -n "$COLLECT_REVOKED" ]] && return 0
  COLLECT_REVOKED=1
  td_sonar_token_revoke_named || COLLECT_REVOKE_FAILED=1
}

collect_cleanup() {
  collect_revoke
  [[ -z "$COLLECT_OUT" ]] || rm -f "$COLLECT_OUT"
}

collect_on_signal() { # <signal> <exit code>
  local signal_name="$1" exit_code="$2"
  if [[ -n "$COLLECT_CHILD" ]] && kill -0 "$COLLECT_CHILD" 2>/dev/null; then
    kill -"$signal_name" "$COLLECT_CHILD" 2>/dev/null
    wait "$COLLECT_CHILD" 2>/dev/null
  fi
  collect_cleanup
  trap - EXIT
  exit "$exit_code"
}

trap 'collect_cleanup' EXIT
trap 'collect_on_signal INT 130' INT
trap 'collect_on_signal TERM 143' TERM

# --- Sonar 토큰(읽을 과제가 있을 때만) ----------------------------------------------------------
sonar_count="$(td_py -m td.collect needs-sonar "${collect_args[@]}")" || exit $?

collect_issue_token() {
  td_sonar_load_env || return 1
  TD_SONAR_URL="$(td_py -m td.sonar url)" || { TD_SONAR_FAIL_REASON="Sonar URL을 알 수 없다"; return 1; }
  export TD_SONAR_URL
  td_sonar_verify_schema || return 1
  td_sonar_preclean || return 1
  td_sonar_token_issue_named "td-collect-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"
}

amend_reasons=()
if [[ "${sonar_count//[^0-9]/}" -gt 0 ]]; then
  if ! collect_issue_token; then
    td_log "collect: Sonar 토큰 없이 수집한다: ${TD_SONAR_FAIL_REASON:-}"
    unset SONAR_TOKEN
    amend_reasons+=("Sonar 토큰 발급 실패")
  fi
fi

# --- 수집(자식). 신호를 넘길 수 있게 백그라운드로 띄우고 exec로 파이썬이 자식 자체가 되게 한다 ---------------
collect_py_exec() {
  local venv_python="$TD_ROOT/site-gen/.venv/bin/python"
  export PYTHONPATH="$TD_ROOT/site-gen${PYTHONPATH:+:$PYTHONPATH}"
  if [[ -x "$venv_python" ]]; then
    exec "$venv_python" "$@"
  fi
  exec uv run --project "$TD_ROOT/site-gen" --quiet python "$@"
}

COLLECT_OUT="$(mktemp "${TMPDIR:-/tmp}/td-collect.XXXXXX")" || { td_log "collect: 임시 파일을 만들지 못했다"; exit 1; }
( collect_py_exec -m td.collect run "${collect_args[@]}" ) >"$COLLECT_OUT" &
COLLECT_CHILD=$!
collect_rc=0
wait "$COLLECT_CHILD" || collect_rc=$?
COLLECT_CHILD=""

collect_revoke
[[ -z "$COLLECT_REVOKE_FAILED" ]] || amend_reasons+=("Sonar 토큰 정리 실패")
result="$(cat "$COLLECT_OUT")"
if [[ $collect_rc -ne 0 ]]; then
  [[ -z "$result" ]] || printf '%s\n' "$result"
  exit "$collect_rc"
fi
if collect_hook degraded; then amend_reasons+=("injected"); fi
for reason in ${amend_reasons[@]+"${amend_reasons[@]}"}; do
  result="$(printf '%s' "$result" | td_py -m td.collect amend --status degraded --reason "$reason")" \
    || { td_log "collect: 수집 결과에 사유를 더하지 못했다"; exit 1; }
done
printf '%s\n' "$result"
exit 0
