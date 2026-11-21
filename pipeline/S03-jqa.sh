#!/usr/bin/env bash
# S03 jqa: jQAssistant로 SUT classes를 scan -> analyze(Spring 개념) 하고, 루프백 server를 백그라운드로 띄워 고정 Cypher
# 묶음(ontology/jqa/queries)을 Bolt로 질의해 S03/ontology-jqa.json을 만든다.
# 입력: S00(tools/jqassistant, tools/jqa-repo), SUT classes 디렉터리(sut.yaml classes). 산출물: S03/{ontology-jqa.json, store/, *.log}.
# 보강: 같은 server에 ontology/jqa/queries/ext를 질의해 S03/ontology-jqa-ext.json(det arm 입력)을 쓴다. 실패하면 det를 요청한
# run에서만 S03을 degraded로 둔다(det를 요청하지 않은 run은 로그만 남기고 ext 파일을 지운 채 원래 상태를 유지한다).
# 모든 jQA 호출은 같은 전용 로컬 저장소(-Djqassistant.repositories.local=tools/jqa-repo)를 쓰고, 시작 전에 그 안의
# Spring 플러그인 jar가 tools.pin.yaml의 sha256과 같은지 확인한다. 외부 명령은 td_run으로 시간 제한을 건다(jQA 900초).
# server는 stdin이 열려 있는 동안만 산다(jQA 2.9.1은 Enter를 기다린다). fifo를 읽기/쓰기로 열어 stdin을 붙들고, 종료 시
# PID(pids/jqa-server.pid)만 정리한다.
# 사용: S03-jqa.sh <sut> <runId>
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"

TD_PIDS_SCOPE="jqa-server jqa-server-java"   # 종료 trap도 이 단계가 등록한 PID만 정리한다
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
# 함수가 아닌 외부 명령을 직접 백그라운드로 띄워 $!가 그 프로세스의 PID가 되게 한다(td.proc = td_run의 구현).
# td.proc은 TERM/INT를 받으면 자식(jQA java)의 프로세스 그룹을 정리한다.
# HTTP 포트는 -1로 꺼 둔다(jQA 2.9.1의 HTTP는 브라우저 정적 파일만 서빙하고 와일드카드에 바인드된다). 질의는 Bolt(루프백)만 쓴다.
# 빈 포트는 고른 뒤 다른 프로세스가 가로챌 수 있으므로 기동 실패(서버 조기 종료)에 한해 최대 3번 다시 고른다.
SERVER_PID="" ; BOLT_PORT=""
for attempt in 1 2 3; do
  BOLT_PORT="$(td_py -m td.ontology_jqa free-ports 1)"
  [[ -n "$BOLT_PORT" ]] || s03_fail "빈 포트를 고르지 못했다"
  (cd "$WORK_DIR" && exec env PYTHONPATH="$TD_ROOT/site-gen" JAVA_HOME="$JQA_JAVA_HOME" "$PY_BIN" -m td.proc run 3600 -- \
    "$JQA_BIN" server "${JQA_ARGS[@]}" "-Djqassistant.store.embedded.bolt-port=$BOLT_PORT" \
    "-Djqassistant.store.embedded.http-port=-1" <&3 > "$OUT_DIR/server.log" 2>&1) &
  SERVER_PID=$!
  td_pid_register jqa-server "$SERVER_PID"
  td_log "S03 jQA server pid=$SERVER_PID bolt=127.0.0.1:$BOLT_PORT (attempt $attempt)"
  WAIT_RC=0
  WAIT_OUT="$(td_py -m td.ontology_jqa wait-bolt --port "$BOLT_PORT" --pid "$SERVER_PID" --timeout "${TD_JQA_SERVER_WAIT:-180}" 2>&1)" || WAIT_RC=$?
  [[ $WAIT_RC -ne 0 ]] || break
  td_pids_reap_named jqa-server jqa-server-java
  [[ "$WAIT_OUT" == *"종료되었다"* && $attempt -lt 3 ]] || s03_fail "$WAIT_OUT (server.log: $(tail -3 "$OUT_DIR/server.log" | tr '\n' ' '))"
done
# td.proc 아래의 java PID도 등록한다(td.proc이 먼저 죽는 경우에도 정리되게 한다).
JAVA_PID="$(pgrep -P "$SERVER_PID" 2>/dev/null | head -1 || true)"
[[ -n "$JAVA_PID" ]] || s03_fail "jQA server의 java 프로세스를 찾지 못했다"
td_pid_register jqa-server-java "$JAVA_PID"
LISTENERS="$(td_py -m td.ontology_jqa check-loopback --pid "$JAVA_PID" 2>&1)" || s03_fail "$LISTENERS"

EXPORT_OUT="$(td_py -m td.ontology_jqa export --bolt-port "$BOLT_PORT" --run-dir "$TD_RUN_DIR" --sut-file "$TD_SUT_FILE" \
  --out "$OUT_DIR/ontology-jqa.json" 2>&1)" || s03_fail "$EXPORT_OUT"

# 보강 그래프(ontology/jqa/queries/ext -> ontology-jqa-ext.json, det arm 입력). 기존 산출물과 별도 파일이며, 실패해도 S03을
# 실패시키지 않는다. det를 요청한 run이면 degraded로 두고, 아니면 로그만 남긴다(기존 ontology-jqa.json은 그대로 쓴다).
EXT_FILE="$OUT_DIR/ontology-jqa-ext.json"
EXT_REASON=""
rm -f "$EXT_FILE"
EXT_OUT="$(td_py -m td.ontology_ext export --bolt-port "$BOLT_PORT" --base "$OUT_DIR/ontology-jqa.json" \
  --out "$EXT_FILE" 2>&1)" || { EXT_REASON="ext export 실패: $(printf '%s' "$EXT_OUT" | td_tail_chars 600)"; rm -f "$EXT_FILE"; }

# 질의가 끝났으니 server를 내린다(S03이 등록한 PID만 정리하고 그 파일을 지운다). 비정상 종료 경로는 종료 trap(td_pids_reap)이 정리한다.
td_pids_reap_named jqa-server jqa-server-java
wait "$SERVER_PID" 2>/dev/null || true
rm -f "$STDIN_FIFO"

SCHEMA_ERR="$(td_py - "$OUT_DIR/ontology-jqa.json" <<'PY' 2>&1
import json, sys
from pathlib import Path
import jsonschema
root = Path(__import__("os").environ["TD_ROOT"])
jsonschema.validate(json.loads(Path(sys.argv[1]).read_text()), json.loads((root / "site-gen/td/schemas/ontology.schema.json").read_text()))
PY
)" || s03_fail "ontology-jqa.json이 스키마를 통과하지 못했다: $(printf '%s' "$SCHEMA_ERR" | td_tail_chars 600)"

if [[ -z "$EXT_REASON" ]]; then
  EXT_SCHEMA_ERR="$(td_py - "$EXT_FILE" <<'PY' 2>&1
import json, sys
from pathlib import Path
import jsonschema
root = Path(__import__("os").environ["TD_ROOT"])
jsonschema.validate(json.loads(Path(sys.argv[1]).read_text()), json.loads((root / "site-gen/td/schemas/ontology-ext.schema.json").read_text()))
PY
)" || { EXT_REASON="ext export 실패: ontology-jqa-ext.json이 스키마를 통과하지 못했다: $(printf '%s' "$EXT_SCHEMA_ERR" | td_tail_chars 600)"; rm -f "$EXT_FILE"; }
fi

FALLBACKS="$(jq -c '.meta.fallbacks' "$OUT_DIR/ontology-jqa.json")"
EXTRA="$(jq -c --argjson listeners "$LISTENERS" '{nodes: (.nodes | length), edges: (.edges | length), fallbacks: .meta.fallbacks, listeners: $listeners}' "$OUT_DIR/ontology-jqa.json")"
if [[ -z "$EXT_REASON" ]]; then
  OUTPUTS="$(jq -cn --arg ontology "$OUT_DIR/ontology-jqa.json" --arg ext "$EXT_FILE" '{ontology: $ontology, ontologyExt: $ext}')"
else
  OUTPUTS="$(jq -cn --arg ontology "$OUT_DIR/ontology-jqa.json" '{ontology: $ontology}')"
fi
REASONS=()   # ext 실패 사유가 있으면 맨 앞에 둔다(사유 접두사 `ext export 실패:`로 판별할 수 있게)
if [[ -n "$EXT_REASON" ]]; then
  td_log "S03 $EXT_REASON"
  rm -f "$EXT_FILE"
  if td_arm_requested det; then
    REASONS+=("$EXT_REASON")
  else
    td_log "S03 det를 요청하지 않은 run이라 ext 실패로 degraded 처리하지 않는다"
  fi
fi
[[ "$FALLBACKS" == "[]" ]] || REASONS+=("Spring 개념이 비어 :Annotation 쿼리로 대체: $FALLBACKS")
if [[ ${#REASONS[@]} -eq 0 ]]; then
  td_stage_end S03 passed --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
else
  REASON="$(printf '%s; ' "${REASONS[@]}")"
  td_stage_end S03 degraded "${REASON%; }" --outputs-json "$OUTPUTS" --extra-json "$EXTRA"
fi
