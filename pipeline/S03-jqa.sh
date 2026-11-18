#!/usr/bin/env bash
# S03 jqa: jQAssistant로 SUT classes를 scan -> analyze(Spring 개념) 하고, 루프백 server를 백그라운드로 띄워 고정 Cypher
# 묶음(ontology/jqa/queries)을 Bolt로 질의해 S03/ontology-jqa.json을 만든다.
# 입력: S00(tools/jqassistant, tools/jqa-repo), SUT classes 디렉터리(sut.yaml classes). 산출물: S03/{ontology-jqa.json, store/, *.log}.
# 모든 jQA 호출은 같은 전용 로컬 저장소(-Djqassistant.repositories.local=tools/jqa-repo)를 쓰고, 시작 전에 그 안의
# Spring 플러그인 jar가 tools.pin.yaml의 sha256과 같은지 확인한다. 외부 명령은 td_run으로 시간 제한을 건다(jQA 900초).
# server는 stdin이 열려 있는 동안만 산다(jQA 2.9.1은 Enter를 기다린다). fifo를 읽기/쓰기로 열어 stdin을 붙들고, 종료 시
# PID(pids/jqa-server.pid)만 정리한다.
# 사용: S03-jqa.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"

td_stage_begin S03
td_hook S03
: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_FILE:?}"

s03_fail() { td_log "S03 failed: $1"; td_stage_end S03 failed "${1:0:1500}"; exit 1; }

S00_JSON="$TD_RUN_DIR/stages/S00.json"
[[ -f "$S00_JSON" ]] || s03_fail "S00 산출물이 없다"
TOOLS_DIR="$(jq -r '.outputs.toolsDir // empty' "$S00_JSON")"
JQA_BIN="$TOOLS_DIR/jqassistant/bin/jqassistant"
JQA_REPO="$TOOLS_DIR/jqa-repo"
[[ -x "$JQA_BIN" ]] || s03_fail "jQA CLI가 없다: $JQA_BIN"
JQA_JAVA_HOME="$(td_java_home 17)" || JQA_JAVA_HOME="$(td_java_home 21)" || s03_fail "jQA를 돌릴 JDK 17 또는 21을 찾지 못했다"

# --- 1. 플러그인 검증(스캔 전): 전용 저장소의 Spring 플러그인 jar sha256 == pin -------------------------------------
VERIFY_OUT="$(td_py -m td.ontology_jqa verify-plugin --repo "$JQA_REPO" 2>&1)" || s03_fail "$VERIFY_OUT"

# --- 2. 입력 점검 ------------------------------------------------------------------------------------------------
CLASSES_REL="$(td_py -m td.sut_config get "$TD_SUT_FILE" classes 2>&1)" || s03_fail "sut.yaml classes를 읽지 못했다: $CLASSES_REL"
CLASSES_DIR="$TD_SUT_SRC/$CLASSES_REL"
[[ -d "$CLASSES_DIR" ]] || s03_fail "SUT classes 디렉터리가 없다($CLASSES_REL): S00의 SUT 빌드 산출물이 필요하다"
PY_BIN="$TD_ROOT/site-gen/.venv/bin/python"
[[ -x "$PY_BIN" ]] || s03_fail "site-gen venv 파이썬이 없다: $PY_BIN"

OUT_DIR="$TD_RUN_DIR/S03"
STORE_DIR="$OUT_DIR/store"
WORK_DIR="$OUT_DIR/work"   # jQA는 report를 cwd 아래 jqassistant/report에 쓴다
mkdir -p "$WORK_DIR"
CONFIG="$TD_ROOT/ontology/jqa/.jqassistant.yml"
JQA_ARGS=(-C "$CONFIG" "-Djqassistant.repositories.local=$JQA_REPO" "-Djqassistant.store.uri=file:$STORE_DIR")

jqa() { # <task> [옵션...]
  (cd "$WORK_DIR" && td_run "${TD_JQA_TIMEOUT:-900}" -- env JAVA_HOME="$JQA_JAVA_HOME" "$JQA_BIN" "$@" "${JQA_ARGS[@]}")
}

# --- 3. scan -> analyze ------------------------------------------------------------------------------------------
jqa scan -f "java:classpath::$CLASSES_DIR" > "$OUT_DIR/scan.log" 2>&1 \
  || s03_fail "jQA scan 실패: $(tail -5 "$OUT_DIR/scan.log")"
jqa analyze > "$OUT_DIR/analyze.log" 2>&1 \
  || s03_fail "jQA analyze 실패: $(tail -5 "$OUT_DIR/analyze.log")"

# --- 4. server(백그라운드) -> 포트 대기 -> 질의 -> 종료 -----------------------------------------------------------------
STDIN_FIFO="$OUT_DIR/server.stdin"
rm -f "$STDIN_FIFO"; mkfifo "$STDIN_FIFO"
exec 3<>"$STDIN_FIFO"
BOLT_PORT="$(td_py -m td.ontology_jqa free-port)"
HTTP_PORT="$(td_py -m td.ontology_jqa free-port)"
[[ -n "$BOLT_PORT" && -n "$HTTP_PORT" && "$BOLT_PORT" != "$HTTP_PORT" ]] || s03_fail "빈 포트를 고르지 못했다"

# 함수가 아닌 외부 명령을 직접 백그라운드로 띄워 $!가 그 프로세스의 PID가 되게 한다(td.proc = td_run의 구현).
# td.proc은 TERM/INT를 받으면 자식(jQA java)의 프로세스 그룹을 정리한다.
(cd "$WORK_DIR" && exec env PYTHONPATH="$TD_ROOT/site-gen" JAVA_HOME="$JQA_JAVA_HOME" "$PY_BIN" -m td.proc run 3600 -- \
  "$JQA_BIN" server "${JQA_ARGS[@]}" "-Djqassistant.store.embedded.bolt-port=$BOLT_PORT" \
  "-Djqassistant.store.embedded.http-port=$HTTP_PORT" <&3 > "$OUT_DIR/server.log" 2>&1) &
SERVER_PID=$!
td_pid_register jqa-server "$SERVER_PID"
td_log "S03 jQA server pid=$SERVER_PID bolt=127.0.0.1:$BOLT_PORT"

WAIT_OUT="$(td_py -m td.ontology_jqa wait-bolt --port "$BOLT_PORT" --pid "$SERVER_PID" --timeout "${TD_JQA_SERVER_WAIT:-180}" 2>&1)" \
  || s03_fail "$WAIT_OUT (server.log: $(tail -3 "$OUT_DIR/server.log" | tr '\n' ' '))"
# td.proc 아래의 java PID도 등록한다(td.proc이 먼저 죽는 경우에도 정리되게 한다).
JAVA_PID="$(pgrep -P "$SERVER_PID" 2>/dev/null | head -1 || true)"
[[ -z "$JAVA_PID" ]] || td_pid_register jqa-server-java "$JAVA_PID"

EXPORT_OUT="$(td_py -m td.ontology_jqa export --bolt-port "$BOLT_PORT" --run-dir "$TD_RUN_DIR" --sut-file "$TD_SUT_FILE" \
  --out "$OUT_DIR/ontology-jqa.json" 2>&1)" || s03_fail "$EXPORT_OUT"

# 질의가 끝났으니 server를 내린다(PID만). 비정상 종료 경로는 종료 trap(td_pids_reap)이 같은 PID를 정리한다.
td_pids_reap
wait "$SERVER_PID" 2>/dev/null || true
rm -f "$STDIN_FIFO"

SCHEMA_ERR="$(td_py - "$OUT_DIR/ontology-jqa.json" <<'PY' 2>&1
import json, sys
from pathlib import Path
import jsonschema
root = Path(__import__("os").environ["TD_ROOT"])
jsonschema.validate(json.loads(Path(sys.argv[1]).read_text()), json.loads((root / "site-gen/td/schemas/ontology.schema.json").read_text()))
PY
)" || s03_fail "ontology-jqa.json이 스키마를 통과하지 못했다: ${SCHEMA_ERR: -600}"

FALLBACKS="$(jq -c '.meta.fallbacks' "$OUT_DIR/ontology-jqa.json")"
EXTRA="$(jq -c '{nodes: (.nodes | length), edges: (.edges | length), fallbacks: .meta.fallbacks}' "$OUT_DIR/ontology-jqa.json")"
OUTPUTS="$(jq -cn --arg ontology "$OUT_DIR/ontology-jqa.json" '{ontology: $ontology}')"
if [[ "$FALLBACKS" == "[]" ]]; then
  td_stage_end S03 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
else
  td_stage_end S03 degraded "Spring 개념이 비어 :Annotation 쿼리로 대체: $FALLBACKS" --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
fi
