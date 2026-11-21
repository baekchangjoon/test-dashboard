#!/usr/bin/env bash
# Sonar 토큰 수명주기(설계 §6.13, §13.3). common.sh와 env.sh(td_on_exit) 다음에 source한다. 이번 세션 한정 승인된 DB 직접 삽입이다.
#
#   td_sonar_load_env                 infra/local.env의 TD_LIGHTSAIL_IP, TD_SSH_KEY_PATH, TD_DOMAIN을 환경에 채운다(환경 값이 우선)
#   td_sonar_psql <sql>               SSH로 Sonar Postgres에 SQL 하나를 실행(-tA). TD_SSH_PORT_OVERRIDE는 테스트 실행에서만 쓴다
#   td_sonar_verify_schema            `\d user_tokens`로 필요한 열과 bigint 만료 열을 확인(해시 방식은 발급 직후 validate가 검증)
#   td_sonar_preclean                 만료된 `td-%` 행만 지운다(다른 run의 활성 토큰과 td-가 아닌 토큰은 건드리지 않는다)
#   td_sonar_token_issue_named <name> 무작위 토큰의 SHA-384 해시를 admin으로 INSERT(만료 = 지금 + 2시간), SONAR_TOKEN export, validate.
#                                     단계에 묶이지 않는다(TD_RUN_DIR 불필요). 정리 trap은 호출자가 건다
#   td_sonar_token_revoke_named       기억한 이름의 행만 DELETE하고 0행을 확인, SONAR_TOKEN unset. 실패는 경고 1회 + return 1.
#                                     장애 주입 지점은 TD_SONAR_HOOK_STAGE(기본 S11)의 cleanup-ssh
#   td_sonar_token_issue <runId>      S11 래퍼: 정리 trap(_td_sonar_revoke_on_exit)을 등록하고 td-<runId>로 issue_named
#   td_sonar_token_revoke             S11 래퍼: 자기 행(td-<runId>)만 revoke_named. 정리 SSH 실패는 return 1
#
# 토큰 평문은 환경 변수 SONAR_TOKEN으로만 다룬다(명령줄·로그·산출물에 쓰지 않는다). DB에는 해시만 간다.
# 실패 사유는 TD_SONAR_FAIL_REASON에 둔다. 정리는 td_on_exit로 모든 종료 경로(실패, 시그널)에 등록된다.

TD_SONAR_DB_CONTAINER="${TD_SONAR_DB_CONTAINER:-sonarqube-db-1}"
TD_SONAR_TOKEN_LIFETIME_MS=7200000
TD_SONAR_FAIL_REASON=""
_TD_SONAR_ISSUED_RUN=""    # S11 래퍼가 발급한 runId
_TD_SONAR_TOKEN_NAME=""    # issue_named가 기억한 토큰 행 이름(revoke_named가 지운다)
_TD_SONAR_REVOKE_STATE=""   # ""(미시도) | done | failed

td_sonar_load_env() {
  local exports
  exports="$(td_py -m td.sonar local-env)" || { TD_SONAR_FAIL_REASON="infra/local.env를 읽지 못했다"; return 1; }
  eval "$exports"
  local key
  for key in TD_LIGHTSAIL_IP TD_SSH_KEY_PATH TD_DOMAIN; do
    [[ -n "${!key:-}" ]] || { TD_SONAR_FAIL_REASON="$key가 설정돼 있지 않다(infra/local.env)"; return 1; }
  done
}

td_sonar_psql() { # <sql>
  local sql="$1" port_args=()
  if [[ -n "${TD_SSH_PORT_OVERRIDE:-}" && -n "${TD_SITE_PREFIX:-}" ]]; then port_args=(-p "$TD_SSH_PORT_OVERRIDE"); fi
  td_run 120 -- ssh -i "$TD_SSH_KEY_PATH" -o BatchMode=yes -o ConnectTimeout=20 -o LogLevel=ERROR \
    ${port_args[@]+"${port_args[@]}"} "ubuntu@$TD_LIGHTSAIL_IP" \
    "docker exec $TD_SONAR_DB_CONTAINER psql -U sonar -d sonar -v ON_ERROR_STOP=1 -tA -c \"$sql\""
}

td_sonar_verify_schema() {
  local desc column
  desc="$(td_sonar_psql '\d user_tokens')" || { TD_SONAR_FAIL_REASON="ssh로 user_tokens 스키마를 조회하지 못했다"; return 1; }
  for column in uuid user_uuid name token_hash type; do
    grep -q "^${column}|" <<< "$desc" || { TD_SONAR_FAIL_REASON="user_tokens에 ${column} 열이 없다(스키마 변경?)"; return 1; }
  done
  for column in created_at expiration_date; do
    grep -q "^${column}|bigint" <<< "$desc" || { TD_SONAR_FAIL_REASON="user_tokens.${column}이 bigint가 아니다(스키마 변경?)"; return 1; }
  done
}

td_sonar_preclean() {
  local deleted
  deleted="$(td_sonar_psql "with gone as (delete from user_tokens where name like 'td-%' and expiration_date is not null and expiration_date < (extract(epoch from now())*1000)::bigint returning 1) select count(*) from gone")" \
    || { TD_SONAR_FAIL_REASON="ssh로 만료 토큰 사전 청소에 실패했다"; return 1; }
  td_log "Sonar 사전 청소: 만료된 td-% 토큰 ${deleted//[^0-9]/}개 삭제"
}

# 정리 trap용: 발급을 시도한 뒤 어떤 경로로 끝나든 자기 행을 지운다. 이미 끝났으면 아무것도 하지 않는다.
_td_sonar_revoke_on_exit() {
  [[ "$_TD_SONAR_REVOKE_STATE" == "failed" ]] && return 0  # 명시 정리가 이미 실패를 기록하고 경고했다
  local previous
  previous="$(jq -r '.reason // empty' "$TD_RUN_DIR/stages/S11.json" 2>/dev/null)"
  td_sonar_revoke_redact "$previous" && return 0
  td_log "S11 정리 실패: ${TD_SONAR_REASON_OUT:0:300}"
  td_stage_end S11 failed "${TD_SONAR_REASON_OUT:0:1500}"
}

# 정리(revoke)는 SONAR_TOKEN을 unset하므로, 사유의 토큰 가리기는 정리 전에 복사해 둔 값으로 한다.
# 정리가 덧붙인 문구까지 가린 최종 사유를 TD_SONAR_REASON_OUT에 두고, 정리가 실패했으면 return 1.
TD_SONAR_REASON_OUT=""
td_sonar_revoke_redact() { # <reason>
  local token_copy="${SONAR_TOKEN:-}" reason="${1:-}" rc=0
  td_sonar_token_revoke || { rc=1; reason="${reason:+$reason; }$TD_SONAR_FAIL_REASON"; }
  [[ -z "$token_copy" ]] || reason="${reason//"$token_copy"/<token>}"
  TD_SONAR_REASON_OUT="$reason"
  return $rc
}

# 이름 그대로 발급한다. 발급 도중 실패해도 td_sonar_token_revoke_named가 지울 수 있게 이름을 먼저 기억한다.
td_sonar_token_issue_named() { # <name>
  local name="${1:?name}" token hash row_uuid inserted
  _TD_SONAR_TOKEN_NAME="$name"
  _TD_SONAR_REVOKE_STATE=""
  token="squ_$(openssl rand -hex 20)" || { TD_SONAR_FAIL_REASON="난수 생성 실패"; return 1; }
  hash="$(printf '%s' "$token" | openssl dgst -sha384 | awk '{print $NF}')"
  row_uuid="$(openssl rand -hex 10)"
  [[ ${#hash} -eq 96 && -n "$row_uuid" ]] || { TD_SONAR_FAIL_REASON="토큰 해시 계산 실패"; return 1; }
  td_sonar_psql "insert into user_tokens (uuid, user_uuid, name, token_hash, created_at, type, expiration_date) select '$row_uuid', u.uuid, '$name', '$hash', t.ms, 'USER_TOKEN', t.ms + $TD_SONAR_TOKEN_LIFETIME_MS from users u, (select (extract(epoch from now())*1000)::bigint as ms) t where u.login='admin'" >/dev/null \
    || { TD_SONAR_FAIL_REASON="ssh로 토큰 행을 INSERT하지 못했다"; return 1; }
  inserted="$(td_sonar_psql "select count(*) from user_tokens where name='$name'")" || inserted=""
  [[ "${inserted//[^0-9]/}" == "1" ]] || { TD_SONAR_FAIL_REASON="토큰 행이 삽입되지 않았다(admin 사용자 없음?)"; return 1; }
  export SONAR_TOKEN="$token"
  # 테스트 전용: 토큰을 0600 파일에 1회 쓴다(TD_SITE_PREFIX가 있는 주입 실행에서만).
  if [[ -n "${TD_SONAR_TOKEN_OBSERVE:-}" && -n "${TD_SITE_PREFIX:-}" ]]; then
    (umask 077; printf '%s' "$token" > "$TD_SONAR_TOKEN_OBSERVE")
  fi
  # 해시 방식(SHA-384)은 실제 validate로 검증한다. 맞지 않으면 실패(행은 호출자의 정리가 지운다).
  if ! td_py -m td.sonar validate --url "$TD_SONAR_URL"; then
    TD_SONAR_FAIL_REASON="발급한 토큰이 api/authentication/validate를 통과하지 못했다(해시 방식 불일치?)"
    return 1
  fi
}

# 기억한 이름의 행만 지운다. 이미 지웠으면 아무것도 하지 않는다. 실패하면 경고는 한 번만 크게 내고 return 1.
td_sonar_token_revoke_named() {
  [[ -n "$_TD_SONAR_TOKEN_NAME" ]] || return 0
  [[ "$_TD_SONAR_REVOKE_STATE" == "done" ]] && return 0
  local name="$_TD_SONAR_TOKEN_NAME" hook_stage="${TD_SONAR_HOOK_STAGE:-S11}" left rc=0
  td_py -m td.hooks should-fail "$hook_stage" cleanup-ssh || rc=$?
  if [[ $rc -eq 10 ]]; then
    TD_SONAR_FAIL_REASON="정리 SSH 실패(injected, TD_FAIL_STAGE=$hook_stage:cleanup-ssh)"
  elif td_sonar_psql "delete from user_tokens where name='$name'" >/dev/null \
      && left="$(td_sonar_psql "select count(*) from user_tokens where name='$name'")" && [[ "${left//[^0-9]/}" == "0" ]]; then
    _TD_SONAR_REVOKE_STATE="done"
    unset SONAR_TOKEN
    return 0
  else
    TD_SONAR_FAIL_REASON="토큰 정리 SSH/삭제 실패 또는 잔존 행 확인 실패"
  fi
  if [[ "$_TD_SONAR_REVOKE_STATE" != "failed" ]]; then  # 경고는 한 번만 크게
    _TD_SONAR_REVOKE_STATE="failed"
    TD_SONAR_FAIL_REASON="$TD_SONAR_FAIL_REASON; 토큰 잔존 가능($name), 발급 2시간 후 서버에서 만료된다"
    {
      echo "[td] ============================================================"
      echo "[td] !!! Sonar 토큰 잔존 가능: $name (발급 2시간 후 만료) !!!"
      echo "[td] ============================================================"
    } >&2
  fi
  return 1
}

# S11 래퍼. INSERT가 일부만 적용돼도(응답 유실 등) 정리되도록 발급 전에 정리 trap을 먼저 등록한다.
td_sonar_token_issue() { # <runId>
  local run_id="${1:?runId}"
  _TD_SONAR_ISSUED_RUN="$run_id"
  td_on_exit '_td_sonar_revoke_on_exit'
  td_sonar_token_issue_named "td-$run_id"
}

# S11 래퍼. 장애 주입 지점은 S11:cleanup-ssh로 고정한다.
td_sonar_token_revoke() {
  [[ -n "$_TD_SONAR_ISSUED_RUN" ]] || return 0
  _TD_SONAR_TOKEN_NAME="td-$_TD_SONAR_ISSUED_RUN"
  local TD_SONAR_HOOK_STAGE=S11
  td_sonar_token_revoke_named
}
