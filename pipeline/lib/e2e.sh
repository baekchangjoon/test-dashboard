#!/usr/bin/env bash
# generation 하나의 Cucumber 실행(S07과 S10이 공유). common.sh, env.sh 다음에 source한다.
#
#   td_e2e_generation <stage> <genId> <gen_dir> <java_home>
#     1) td.scenarios prepare: javac로 glue 클래스별 컴파일 확인(실패 클래스 제외) -> testids.json -> SUT 없는 dry-run
#     2) td_sut_up -> e2e/runner(`-Pgen`) 실행 -> td_sut_down  (generation마다 SUT를 새로 띄운다. 병렬도 1)
#     3) td.scenarios finalize: 모든 시나리오가 scenario-results.json에 정확히 한 번 나오게 대조하고 .exec를 검증한다.
#     산출물: $TD_RUN_DIR/<stage>/<genId>/{compile-excluded.json, testids.json, dryrun.json, cucumber.ndjson, cucumber.json,
#             html/, junit.xml, scenario-results.json, summary.json, exec/, gradle.log}
#     결과 전역: E2E_STATUS(passed|failed), E2E_REASON, E2E_EXTRA(JSON). 실패해도 SUT는 이미 내려가 있다.
#   시나리오 실패(failed/undefined)는 generation 실패가 아니라 결과 데이터다. 실행 기반 문제(SUT 기동 실패, 출력 누락, 시나리오·.exec 누락)만
#   generation 실패다.
#   입력: TD_SUT_FILE. 인증 정보는 sut.yaml auth.user_env/pass_env가 가리키는 환경 변수(없으면 infra/local.env)다.
#   비밀번호는 명령줄이 아니라 환경 변수 TD_AUTH_PASS로만 하네스에 넘긴다.

E2E_STATUS="" E2E_REASON="" E2E_EXTRA="{}"

_e2e_fail() { # <사유> [extra-json]
  td_log "generation 실패: $1"
  td_sut_down
  E2E_STATUS=failed; E2E_REASON="${1:0:1500}"; E2E_EXTRA="${2:-{\}}"
  unset TD_AUTH_USER TD_AUTH_PASS
  return 1
}

td_e2e_generation() {
  local stage="${1:?stage}" gen_id="${2:?genId}" gen_dir="${3:?gen_dir}" java_home="${4:?java_home}"
  : "${TD_RUN_DIR:?}" "${TD_SUT_FILE:?}" "${TD_ROOT:?}"
  E2E_STATUS="" E2E_REASON="" E2E_EXTRA="{}"
  local out="$TD_RUN_DIR/$stage/$gen_id" prep_out pickles login
  rm -rf "$out"
  mkdir -p "$out"
  [[ -d "$gen_dir/features" ]] || { _e2e_fail "generation에 features 디렉터리가 없다: ${gen_dir##*/}"; return 1; }

  prep_out="$(td_py -m td.scenarios prepare "$gen_dir" "$out" "$gen_id" 2>"$out/prepare.log")" \
    || { _e2e_fail "컴파일 확인/dry-run 실패: $(tail -c 600 "$out/prepare.log")"; return 1; }
  pickles="$(jq -r '.pickles' <<< "$prep_out")"

  local gradle_rc=0
  if [[ "$pickles" -gt 0 ]]; then
    login="$(td_py -m td.sut_config get "$TD_SUT_FILE" auth.login)" || { _e2e_fail "sut.yaml auth.login을 읽지 못했다"; return 1; }
    eval "$(td_py -m td.scenarios auth-env "$TD_SUT_FILE" 2>"$out/auth.log")" \
      || { _e2e_fail "인증 정보를 읽지 못했다: $(tail -c 300 "$out/auth.log")"; return 1; }
    [[ -n "${TD_AUTH_PASS:-}" ]] || { _e2e_fail "인증 정보를 읽지 못했다: $(tail -c 300 "$out/auth.log")"; return 1; }
    td_sut_up "$TD_RUN_DIR" "$stage" "$gen_id" || { _e2e_fail "SUT 기동 실패: $TD_SUT_FAIL_REASON"; return 1; }
    # 이전 결과가 섞이지 않게 비운다(하네스는 scenario-results.json에 이어 쓴다).
    rm -f "$out/scenario-results.json" "$out/generation-meta.json"
    # e2e 프로젝트의 build 디렉터리는 하나라서 파이썬 쪽(S06 dry-run)과 같은 파일 잠금으로 직렬화한다(시간 제한은 td_run과 같다).
    (cd "$TD_ROOT/e2e" && td_py -m td.scenarios gradle-locked --timeout 1800 -- env JAVA_HOME="$java_home" ./gradlew --no-daemon --console=plain :runner:test \
      "-Pgen=$gen_dir" "-Pexcluded=$out/compile-excluded.json" "-Pout=$out" \
      "-Ptd.base-url=$TD_BASE_URL" "-Ptd.control-url=$TD_CONTROL_URL" "-Ptd.testids=$out/testids.json" \
      "-Ptd.results=$out/scenario-results.json" "-Ptd.auth.login=$login" "-Ptd.auth.user=$TD_AUTH_USER") \
      > "$out/gradle.log" 2>&1 || gradle_rc=$?
    # per-test .exec는 stop 때 쓰이지만 aggregate.exec는 JVM이 멈출 때 쓰이므로 세기 전에 SUT를 내린다.
    td_sut_down
    unset TD_AUTH_USER TD_AUTH_PASS
  fi

  local fin_out
  fin_out="$(td_py -m td.scenarios finalize "$gen_dir" "$out" "$gen_id" 2>"$out/finalize.log")" \
    || { _e2e_fail "결과 대조 실패: $(tail -c 600 "$out/finalize.log")"; return 1; }
  jq -e . >/dev/null 2>&1 <<< "$fin_out" || { _e2e_fail "finalize 출력이 JSON이 아니다: $(head -c 300 <<< "$fin_out")"; return 1; }
  E2E_STATUS="$(jq -r '.status' <<< "$fin_out")"
  E2E_REASON="$(jq -r '.reason // empty' <<< "$fin_out")"
  E2E_EXTRA="$(jq -c '.extra' <<< "$fin_out")"
  if [[ "$E2E_STATUS" == "failed" && "$gradle_rc" -ne 0 ]]; then
    E2E_REASON="${E2E_REASON:0:900} (gradle exit $gradle_rc: $(tail -c 400 "$out/gradle.log" | tr '\n' ' '))"
  fi
  [[ "$E2E_STATUS" == "passed" ]]
}
