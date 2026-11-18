#!/usr/bin/env bash
# SUT 컨테이너 기동과 자원 정리(Task 4). common.sh 다음에 source한다.
#
#   td_sut_up <run_dir> <stage> <suite>  컨테이너 기동, TD_BASE_URL/TD_CONTROL_URL/TD_COMPOSE_PROJECT/TD_EXEC_DIR export,
#                                        health 대기. 실패하면 정리까지 끝내고 return 1, 사유는 TD_SUT_FAIL_REASON.
#   td_sut_down                          stop -t 30 → down -v --remove-orphans (멱등)
#   td_pid_register <name> <pid>         pids/<name>.pid 기록, 종료 시 reap 대상
#   td_leak_gate <runId>                 test-run 라벨/프로젝트 접두 자원이 남아 있으면 return 1
#   td_on_exit <cmd>                     종료 정리 명령 등록(EXIT/INT/TERM 공통, LIFO)
#
# 입력(없으면 sut.yaml과 S00 출력에서 해석): TD_SUT_JAR, TD_AGENT_JAR, TD_SUT_PORT, TD_SUT_HEALTH, TD_SUT_PACKAGES,
#   TD_COMPOSE_FILE, TD_RUN_LABEL(기본 td-<runId>), TD_PROJECT_NAME(기본 td-<runId>-<stage>-<suite> 소문자),
#   TD_SUT_HEALTH_TIMEOUT(기본 120초)

TD_COMPOSE_FILE_DEFAULT="$TD_ROOT/env/docker-compose.sut.yml"
TD_SUT_FAIL_REASON=""

# --- 종료 정리 등록부 -----------------------------------------------------------------------
# 단계 스크립트마다 trap이 따로 있으면 서로 덮어쓴다. 명령을 모아 한 번에 LIFO로 실행한다.
TD_EXIT_CMDS=()
_TD_CLEANING=""
_td_run_exit_cmds() {
  [[ -z "$_TD_CLEANING" ]] || return 0
  _TD_CLEANING=1
  local index
  for ((index = ${#TD_EXIT_CMDS[@]} - 1; index >= 0; index--)); do
    eval "${TD_EXIT_CMDS[$index]}" || true
  done
}
td_on_exit() { TD_EXIT_CMDS+=("$1"); }
trap '_td_run_exit_cmds' EXIT
trap 'td_log "SIGINT: 정리 후 종료"; exit 130' INT
trap 'td_log "SIGTERM: 정리 후 종료"; exit 143' TERM

# --- 보조 -------------------------------------------------------------------------------------
_td_compose() {
  td_run "${TD_COMPOSE_TIMEOUT:-300}" -- docker compose -f "$TD_COMPOSE_FILE" -p "$TD_COMPOSE_PROJECT" "$@"
}

_td_sut_resolve() { # <run_dir>  — 입력 변수를 env 우선, 없으면 sut.yaml/S00 출력에서 채운다
  local run_dir="$1"
  if [[ -z "${TD_SUT_JAR:-}" && -f "$run_dir/stages/S00.json" ]]; then
    TD_SUT_JAR="$(jq -r '.outputs.jar // empty' "$run_dir/stages/S00.json")"
  fi
  : "${TD_AGENT_JAR:=$TD_WORK_DIR/tools/pjacoco-agent.jar}"
  if [[ -n "${TD_SUT_FILE:-}" && -f "${TD_SUT_FILE:-}" ]]; then
    [[ -n "${TD_SUT_PORT:-}" ]] || TD_SUT_PORT="$(td_py -m td.sut_config get "$TD_SUT_FILE" port 2>/dev/null)"
    [[ -n "${TD_SUT_HEALTH:-}" ]] || TD_SUT_HEALTH="$(td_py -m td.sut_config get "$TD_SUT_FILE" health 2>/dev/null)"
    [[ -n "${TD_SUT_PACKAGES:-}" ]] || TD_SUT_PACKAGES="$(td_py -m td.sut_config get "$TD_SUT_FILE" packages 2>/dev/null)"
  fi
  : "${TD_SUT_PORT:=8080}" "${TD_SUT_HEALTH:=/}"
}

_td_log_tail() { # <file> [bytes]
  [[ -s "$1" ]] && tail -n 50 "$1" | tail -c "${2:-1000}"
}

_td_sut_fail() { # <사유>  — 사유를 남기고 정리한 뒤 return 1
  TD_SUT_FAIL_REASON="${*:0:1400}"
  td_log "SUT 기동 실패: $TD_SUT_FAIL_REASON"
  td_sut_down
  return 1
}

_td_sut_fail_with_logs() { # <사유> <out_dir>  — 컨테이너 로그 마지막 50줄을 사유에 붙인다
  _td_compose logs --no-color --no-log-prefix --tail 50 sut >"$2/sut.log" 2>&1
  _td_sut_fail "$1. 로그 마지막: $(_td_log_tail "$2/sut.log")"
}

# --- td_sut_up ----------------------------------------------------------------------------------
td_sut_up() { # <run_dir> <stage> <suite>
  local run_dir="${1:?run_dir}" stage="${2:?stage}" suite="${3:?suite}"
  TD_SUT_FAIL_REASON=""
  _td_sut_resolve "$run_dir"
  local run_id label out_dir
  run_id="$(basename "$run_dir")"
  label="${TD_RUN_LABEL:-td-$run_id}"
  out_dir="$run_dir/$stage/$suite"
  mkdir -p "$out_dir/exec" "$run_dir/pids"

  export TD_RUN_LABEL="$label"
  export TD_COMPOSE_FILE="${TD_COMPOSE_FILE:-$TD_COMPOSE_FILE_DEFAULT}"
  export TD_COMPOSE_PROJECT="${TD_PROJECT_NAME:-$(printf 'td-%s-%s-%s' "$run_id" "$stage" "$suite" | tr 'A-Z' 'a-z')}"
  export TD_EXEC_DIR="$out_dir/exec"
  export TD_SUT_JAR TD_AGENT_JAR TD_SUT_PORT
  export TD_AGENT_ARGS="destfile=/cov,address=0.0.0.0,port=6310,includes=${TD_SUT_PACKAGES:-*}"

  [[ -f "${TD_SUT_JAR:-}" ]] || { _td_sut_fail "SUT jar가 없다: ${TD_SUT_JAR:-<unset>}"; return 1; }
  [[ -f "$TD_AGENT_JAR" ]] || { _td_sut_fail "pjacoco agent가 없다: $TD_AGENT_JAR"; return 1; }

  # 라벨 검사: 모든 서비스, 네트워크, 볼륨에 test-run 라벨이 있어야 한다. 없으면 아무것도 만들지 않고 거부한다.
  local config_json check_out
  config_json="$(_td_compose config --format json 2>"$out_dir/compose-config.err")" \
    || { _td_sut_fail "compose 설정 렌더링 실패: $(_td_log_tail "$out_dir/compose-config.err" 600)"; return 1; }
  check_out="$(printf '%s' "$config_json" | td_py -m td.envctl check-labels "$label" 2>&1)" \
    || { _td_sut_fail "$check_out"; return 1; }

  # td_sut_down은 source 시점에 종료 정리로 등록돼 있다(기동 도중 중단돼도 같은 프로젝트를 내린다).
  if ! _td_compose up -d >"$out_dir/compose-up.log" 2>&1; then
    _td_sut_fail "compose up 실패: $(_td_log_tail "$out_dir/compose-up.log" 800)"; return 1
  fi

  local sut_addr control_addr
  sut_addr="$(_td_compose port sut "$TD_SUT_PORT" 2>/dev/null)"
  control_addr="$(_td_compose port sut 6310 2>/dev/null)"
  if [[ ! "$sut_addr" =~ ^127\.0\.0\.1:[0-9]+$ || ! "$control_addr" =~ ^127\.0\.0\.1:[0-9]+$ ]]; then
    _td_sut_fail_with_logs "게시 포트가 루프백이 아니다(컨테이너가 일찍 종료했을 수 있다): sut='$sut_addr' control='$control_addr'" "$out_dir"; return 1
  fi
  export TD_BASE_URL="http://$sut_addr" TD_CONTROL_URL="http://$control_addr"

  local container_id deadline running
  container_id="$(_td_compose ps -q sut 2>/dev/null | head -1)"
  deadline=$((SECONDS + ${TD_SUT_HEALTH_TIMEOUT:-120}))
  while true; do
    if td_run 15 -- curl -fsS -o /dev/null --max-time 5 "$TD_BASE_URL$TD_SUT_HEALTH" >/dev/null 2>&1; then
      td_log "SUT 기동 완료: $TD_BASE_URL (control $TD_CONTROL_URL, project $TD_COMPOSE_PROJECT)"
      return 0
    fi
    running="$(td_run 30 -- docker inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null)"
    if [[ "$running" != "true" ]]; then
      _td_sut_fail_with_logs "SUT 컨테이너가 종료됐다" "$out_dir"; return 1
    fi
    if ((SECONDS >= deadline)); then
      _td_sut_fail_with_logs "health ${TD_SUT_HEALTH_TIMEOUT:-120}초 초과($TD_SUT_HEALTH)" "$out_dir"; return 1
    fi
    sleep 2
  done
}

# --- td_sut_down: stop -t 30 → down -v --remove-orphans (멱등) ----------------------------------------
td_sut_down() {
  [[ -n "${TD_COMPOSE_PROJECT:-}" ]] || return 0
  _td_compose stop -t 30 >/dev/null 2>&1 || true
  _td_compose down -v --remove-orphans >/dev/null 2>&1 \
    || td_log "경고: compose down 실패(project $TD_COMPOSE_PROJECT)"
  unset TD_COMPOSE_PROJECT TD_BASE_URL TD_CONTROL_URL
}

# --- PID 관리 ----------------------------------------------------------------------------------------
TD_OWN_PIDS=()
td_pid_register() { # <name> <pid>
  local name="${1:?name}" pid="${2:?pid}" run_dir="${TD_RUN_DIR:?TD_RUN_DIR가 필요하다}"
  mkdir -p "$run_dir/pids"
  echo "$pid" > "$run_dir/pids/$name.pid"
  TD_OWN_PIDS+=("$pid")
}

# 이 셸이 등록한 PID만 정리한다(TERM → 10초 → KILL). 이미 없는 PID는 무시한다.
td_pids_reap() {
  local pid tries
  for pid in ${TD_OWN_PIDS[@]+"${TD_OWN_PIDS[@]}"}; do
    kill -0 "$pid" 2>/dev/null || continue
    kill -TERM "$pid" 2>/dev/null || true
    for tries in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
  done
  TD_OWN_PIDS=()
  return 0
}

# --- 누수 게이트 ----------------------------------------------------------------------------------------
td_leak_gate() { # <runId>
  local run_id="${1:?runId}" out
  if out="$(td_py -m td.envctl leak-gate "$run_id" 2>&1)"; then
    return 0
  fi
  td_log "leak gate 실패(run $run_id): $out"
  return 1
}

# source 시점에 기본 정리를 등록한다(컨테이너와 PID는 어느 종료 경로에서도 정리된다).
td_on_exit 'td_sut_down'
td_on_exit 'td_pids_reap'
