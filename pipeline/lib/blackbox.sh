#!/usr/bin/env bash
# 블랙박스 스위트 1회 실행(S01과 S10이 공유). common.sh, env.sh 다음에 source한다.
#
#   td_blackbox_suite <stage> <suite> <src_dir> <java_home> [lenient]
#     td_sut_up(pjacoco agent) -> <src_dir>에서 sut.yaml blackbox.cmd 실행 -> td_sut_down -> JUnit 복사 -> 판정.
#     산출물: $TD_RUN_DIR/<stage>/<suite>/{exec/, junit/, summary.json, gradle.log, evaluate.log}
#     결과 전역: BB_STATUS(passed|degraded|failed), BB_REASON, BB_EXTRA(JSON). 실패해도 SUT는 이미 내려가 있다.
#     lenient=1이면 과거 커밋(base)용이다: expected-tests와 대조하지 않고, 수량 불일치와 Gradle 종료 코드는 기록만 하며
#       실행된 TC가 없거나 .exec/aggregate.exec가 없을 때만 failed다.
#   TD_SUT_JAR가 있으면 그 jar로 기동한다(S10은 base jar를 지정한다).
#   TD_CONTROL_URL_OVERRIDE(테스트 전용): TD_SITE_PREFIX가 있을 때만 제어 URL을 바꾼다.

BB_STATUS="" BB_REASON="" BB_EXTRA="{}"

_bb_fail() { # <사유> [extra-json]
  td_log "블랙박스 스위트 실패: $1"
  td_sut_down
  BB_STATUS=failed; BB_REASON="${1:0:1500}"; BB_EXTRA="{}"
  [[ -z "${2:-}" ]] || BB_EXTRA="$2"
  return 1
}

td_blackbox_suite() {
  local stage="${1:?stage}" suite="${2:?suite}" src_dir="${3:?src_dir}" java_home="${4:?java_home}" lenient="${5:-0}"
  : "${TD_RUN_DIR:?}" "${TD_SUT_FILE:?}"
  BB_STATUS="" BB_REASON="" BB_EXTRA="{}"
  local out_dir="$TD_RUN_DIR/$stage/$suite" junit_dir
  junit_dir="$out_dir/junit"
  mkdir -p "$junit_dir"
  local blackbox_cmd junit_rel test_sources_rel
  blackbox_cmd="$(td_py -m td.sut_config get "$TD_SUT_FILE" blackbox.cmd)" || { _bb_fail "sut.yaml blackbox.cmd를 읽지 못했다"; return 1; }
  junit_rel="$(td_py -m td.sut_config get "$TD_SUT_FILE" blackbox.junit_xml)" || { _bb_fail "sut.yaml blackbox.junit_xml을 읽지 못했다"; return 1; }
  test_sources_rel="$(td_py -m td.sut_config get "$TD_SUT_FILE" blackbox.test_sources)" || { _bb_fail "sut.yaml blackbox.test_sources를 읽지 못했다"; return 1; }
  local src_junit_dir="$src_dir/$junit_rel"

  td_sut_up "$TD_RUN_DIR" "$stage" "$suite" || { _bb_fail "SUT 기동 실패: $TD_SUT_FAIL_REASON"; return 1; }

  # 제어 URL 주입(테스트 전용): 테스트가 .exec 경계를 열 수 없게 해 게이트 실패를 재현한다. 테스트 격리(TD_SITE_PREFIX) 없이는 무시한다.
  local control_url="$TD_CONTROL_URL"
  if [[ -n "${TD_CONTROL_URL_OVERRIDE:-}" ]]; then
    if [[ -n "${TD_SITE_PREFIX:-}" ]]; then control_url="$TD_CONTROL_URL_OVERRIDE"
    else td_log "경고: TD_CONTROL_URL_OVERRIDE는 TD_SITE_PREFIX가 있는 테스트 실행에서만 쓴다(무시)"; fi
  fi

  local prop_args=() token
  while IFS= read -r -d '' token; do prop_args+=("$token"); done < <(td_py - "$TD_SUT_FILE" "$TD_BASE_URL" "$control_url" <<'PY'
import sys
from td.sut_config import load
for arg in load(sys.argv[1]).blackbox_args(sys.argv[2], sys.argv[3]):
    sys.stdout.write(arg + "\0")
PY
)
  [[ ${#prop_args[@]} -gt 0 ]] || { _bb_fail "blackbox -D 인자를 만들지 못했다"; return 1; }

  # 이전 결과가 섞이지 않게 clone의 JUnit 결과를 비운다.
  rm -rf "$src_junit_dir"
  # 테스트 실패는 TC별 .exec 수량과 별개로 보고한다. Gradle 종료 코드는 기록만 하고 판정은 산출물로 한다.
  local gradle_rc=0
  (cd "$src_dir" && td_run 1800 -- env JAVA_HOME="$java_home" bash -c "$blackbox_cmd \"\$@\"" _ "${prop_args[@]}") \
    > "$out_dir/gradle.log" 2>&1 || gradle_rc=$?

  # aggregate.exec는 JVM이 멈출 때 쓰이므로 세고 복사하기 전에 SUT를 내린다(stop -t 30).
  td_sut_down

  if compgen -G "$src_junit_dir/*.xml" >/dev/null; then cp "$src_junit_dir"/*.xml "$junit_dir/"; fi
  local eval_out
  if [[ "$lenient" == "1" ]]; then
    eval_out="$(td_py -m td.blackbox summarize "$junit_dir" "$out_dir/exec" "$src_dir/$test_sources_rel" 2>"$out_dir/evaluate.log")" \
      || { _bb_fail "게이트 판정 실패: $(tail -c 600 "$out_dir/evaluate.log")"; return 1; }
  else
    eval_out="$(td_py -m td.blackbox evaluate "$junit_dir" "$out_dir/exec" "$src_dir/$test_sources_rel" "$(dirname "$TD_SUT_FILE")/expected-tests.yaml" 2>"$out_dir/evaluate.log")" \
      || { _bb_fail "게이트 판정 실패: $(tail -c 600 "$out_dir/evaluate.log")"; return 1; }
  fi
  jq -e . >/dev/null 2>&1 <<< "$eval_out" \
    || { _bb_fail "게이트 판정 출력이 JSON이 아니다: $(head -c 300 <<< "$eval_out") / $(tail -c 300 "$out_dir/evaluate.log")"; return 1; }
  echo "$eval_out" > "$out_dir/summary.json"
  BB_EXTRA="$(jq -c '{tcCount, execCount, missingExec, noAttribution}' <<< "$eval_out")"
  BB_STATUS="$(jq -r '.status' <<< "$eval_out")"
  BB_REASON="$(jq -r '.reason // empty' <<< "$eval_out")"
  if [[ "$gradle_rc" -ne 0 ]]; then
    if [[ "$lenient" == "1" ]]; then
      BB_EXTRA="$(jq -c --argjson rc "$gradle_rc" '. + {gradleExitCode: $rc}' <<< "$BB_EXTRA")"
    else
      BB_STATUS=failed
      BB_REASON="blackboxTest 종료 코드 $gradle_rc(gradle.log 참고)${BB_REASON:+; $BB_REASON}: $(tail -5 "$out_dir/gradle.log" | tr '\n' ' ')"
    fi
  fi
  [[ "$BB_STATUS" != "failed" ]]
}
