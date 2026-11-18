#!/usr/bin/env bash
# S01 blackbox: SUT 컨테이너(pjacoco agent)를 띄우고 SUT clone의 blackboxTest를 실행한다.
# 산출물: S01/blackbox/{exec/*.exec, exec/aggregate.exec, junit/*.xml, summary.json, gradle.log}
# 게이트(REQ-008): JUnit TC 수(skipped 제외) == .exec 수(aggregate 제외), 불일치는 failed이며 missingExec를 보고한다.
# 사용: S01-blackbox.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"

td_stage_begin S01
td_hook S01

: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"
OUT_DIR="$TD_RUN_DIR/S01/blackbox"
JUNIT_DIR="$OUT_DIR/junit"
mkdir -p "$JUNIT_DIR"

s01_fail() { # <사유> [extra-json]
  td_log "S01 failed: $1"
  td_sut_down
  if [[ -n "${2:-}" ]]; then td_stage_end S01 failed "${1:0:1500}" --extra-json "$2"
  else td_stage_end S01 failed "${1:0:1500}"; fi
  exit 1
}
sut_get() { td_py -m td.sut_config get "$TD_SUT_FILE" "$1"; }

SUT_JAVA_HOME="$(td_java_home "$(sut_get java)")" || true
[[ -n "$SUT_JAVA_HOME" ]] || s01_fail "SUT가 요구하는 JDK $(sut_get java)를 찾지 못했다"
BLACKBOX_CMD="$(sut_get blackbox.cmd)" || s01_fail "sut.yaml blackbox.cmd를 읽지 못했다"
JUNIT_REL="$(sut_get blackbox.junit_xml)" || s01_fail "sut.yaml blackbox.junit_xml을 읽지 못했다"
SUT_JUNIT_DIR="$TD_SUT_SRC/$JUNIT_REL"
TEST_SOURCES_REL="$(sut_get blackbox.test_sources)" || s01_fail "sut.yaml blackbox.test_sources를 읽지 못했다"

td_sut_up "$TD_RUN_DIR" S01 blackbox || s01_fail "SUT 기동 실패: $TD_SUT_FAIL_REASON"

# 제어 URL 주입(테스트 전용): 테스트가 .exec 경계를 열 수 없게 해 게이트 실패를 재현한다. 테스트 격리(TD_SITE_PREFIX) 없이는 무시한다.
CONTROL_URL="$TD_CONTROL_URL"
if [[ -n "${TD_CONTROL_URL_OVERRIDE:-}" ]]; then
  if [[ -n "${TD_SITE_PREFIX:-}" ]]; then CONTROL_URL="$TD_CONTROL_URL_OVERRIDE"
  else td_log "경고: TD_CONTROL_URL_OVERRIDE는 TD_SITE_PREFIX가 있는 테스트 실행에서만 쓴다(무시)"; fi
fi

PROP_ARGS=()
while IFS= read -r -d '' token; do PROP_ARGS+=("$token"); done < <(td_py - "$TD_SUT_FILE" "$TD_BASE_URL" "$CONTROL_URL" <<'PY'
import sys
from td.sut_config import load
for arg in load(sys.argv[1]).blackbox_args(sys.argv[2], sys.argv[3]):
    sys.stdout.write(arg + "\0")
PY
)
[[ ${#PROP_ARGS[@]} -gt 0 ]] || s01_fail "blackbox -D 인자를 만들지 못했다"

# 이전 결과가 섞이지 않게 SUT clone의 JUnit 결과를 비운다.
rm -rf "$SUT_JUNIT_DIR"
# 테스트 실패는 TC별 .exec 수량과 별개로 보고한다. Gradle 종료 코드는 기록만 하고 판정은 산출물로 한다.
GRADLE_RC=0
(cd "$TD_SUT_SRC" && td_run 1800 -- env JAVA_HOME="$SUT_JAVA_HOME" bash -c "$BLACKBOX_CMD \"\$@\"" _ "${PROP_ARGS[@]}") \
  > "$OUT_DIR/gradle.log" 2>&1 || GRADLE_RC=$?

# aggregate.exec는 JVM이 멈출 때 쓰이므로 세고 복사하기 전에 SUT를 내린다(stop -t 30).
td_sut_down

if compgen -G "$SUT_JUNIT_DIR/*.xml" >/dev/null; then cp "$SUT_JUNIT_DIR"/*.xml "$JUNIT_DIR/"; fi
# stdout만 JSON으로 파싱한다. stderr(경고 등)는 evaluate.log에 두고 실패 사유에만 붙인다.
EVAL="$(td_py -m td.blackbox evaluate "$JUNIT_DIR" "$OUT_DIR/exec" "$TD_SUT_SRC/$TEST_SOURCES_REL" "$(dirname "$TD_SUT_FILE")/expected-tests.yaml" 2>"$OUT_DIR/evaluate.log")" \
  || s01_fail "게이트 판정 실패: $(tail -c 600 "$OUT_DIR/evaluate.log")"
jq -e . >/dev/null 2>&1 <<< "$EVAL" || s01_fail "게이트 판정 출력이 JSON이 아니다: $(head -c 300 <<< "$EVAL") / $(tail -c 300 "$OUT_DIR/evaluate.log")"
echo "$EVAL" > "$OUT_DIR/summary.json"
EXTRA="$(jq -c '{tcCount, execCount, missingExec, noAttribution}' <<< "$EVAL")"
STATUS="$(jq -r '.status' <<< "$EVAL")"
REASON="$(jq -r '.reason // empty' <<< "$EVAL")"
if [[ "$GRADLE_RC" -ne 0 ]]; then
  STATUS=failed
  REASON="blackboxTest 종료 코드 $GRADLE_RC(gradle.log 참고)${REASON:+; $REASON}: $(tail -5 "$OUT_DIR/gradle.log" | tr '\n' ' ')"
fi
if [[ "$STATUS" == "passed" ]]; then
  td_stage_end S01 passed --outputs-json "$(jq -cn --arg dir "$OUT_DIR" '{blackbox: $dir}')" --extra-json "$EXTRA"
elif [[ "$STATUS" == "degraded" ]]; then
  td_stage_end S01 degraded "${REASON:0:1500}" --outputs-json "$(jq -cn --arg dir "$OUT_DIR" '{blackbox: $dir}')" --extra-json "$EXTRA"
else
  td_stage_end S01 failed "${REASON:0:1500}" --extra-json "$EXTRA"
  exit 1
fi
