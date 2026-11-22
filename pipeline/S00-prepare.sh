#!/usr/bin/env bash
# S00 prepare: 입력 점검, SUT 커밋 고정, 도구 확보(tools.pin.yaml 기준), SUT 빌드, tools.lock 작성.
# 사용: S00-prepare.sh <sut> <runId>   (run-all.sh가 TD_RUN_DIR, TD_SUT_SRC, TD_SUT_COMMIT, TD_SUT_FILE을 export한다)
# SUT를 한 번 띄워 비인증 응답 코드를 실측하고 sut.yaml auth.unauthenticated_status와 대조한다(Task 4).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/env.sh"

TOOLS_DIR="$TD_WORK_DIR/tools"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/td-s00.XXXXXX")"
td_on_exit 'rm -rf "$SCRATCH"'

td_stage_begin S00
td_hook S00

s00_fail() { # <사유>  — 단계를 failed로 기록하고 끝낸다(사유는 1500자까지)
  local msg="$*"
  td_log "S00 failed: $msg"
  td_stage_end S00 failed "${msg:0:1500}"
  exit 1
}
# 파이썬 점검을 실행하고 실패하면 그 stderr를 사유로 쓴다.
# 결과는 서브셸 없이 S00_OUT에 담는다(서브셸에서 실패하면 exit가 단계를 끝내지 못한다).
S00_OUT=""
s00_py() { local rc=0; S00_OUT="$(td_py -m td.prepare "$@" 2>&1)" || rc=$?; [[ $rc -eq 0 ]] || s00_fail "$S00_OUT"; }
java_home() { td_java_home "$1"; }

: "${TD_RUN_DIR:?}" "${TD_SUT_SRC:?}" "${TD_SUT_COMMIT:?}" "${TD_SUT_FILE:?}"
mkdir -p "$TOOLS_DIR" "$TD_RUN_DIR/S00"

# --- 1. 입력 점검(빠른 것부터) ---------------------------------------------------------------
s00_py check-reps "$TD_RUN_DIR"
SUT_CFG_ERR="$(td_py -m td.sut_config get "$TD_SUT_FILE" name 2>&1 >/dev/null)" || s00_fail "$SUT_CFG_ERR"
sut_get() { td_py -m td.sut_config get "$TD_SUT_FILE" "$1"; }
s00_py check-expected-commit "$TD_SUT_FILE" "$TD_SUT_COMMIT"

# --- 2. SUT 소스: 전체 히스토리 확인, 커밋 고정 ----------------------------------------------------
[[ -d "$TD_SUT_SRC/.git" ]] || s00_fail "SUT 소스가 없다: $TD_SUT_SRC"
shallow="$(git -C "$TD_SUT_SRC" rev-parse --is-shallow-repository 2>&1)" || s00_fail "git 실패: $shallow"
[[ "$shallow" == "false" ]] || s00_fail "SUT clone이 shallow다(전체 히스토리가 필요하다): $TD_SUT_SRC"
td_run 120 -- git -c core.hooksPath=/dev/null -C "$TD_SUT_SRC" checkout --detach --force --quiet "$TD_SUT_COMMIT" >&2 \
  || s00_fail "SUT 커밋 checkout 실패: ${TD_SUT_COMMIT:0:7}"
head_sha="$(git -C "$TD_SUT_SRC" rev-parse HEAD)"
[[ "$head_sha" == "$TD_SUT_COMMIT" ]] || s00_fail "checkout 뒤 HEAD(${head_sha:0:7})가 run 커밋(${TD_SUT_COMMIT:0:7})과 다르다"

# (전역 git hook이 clone/checkout마다 .codegraph를 만들어 SUT·도구 소스를 오염시키므로 core.hooksPath를 끈다)
# --- 3. 도구 확보 -------------------------------------------------------------------------------
JAVA17="$(java_home 17)"; [[ -n "$JAVA17" ]] || s00_fail "JDK 17을 찾지 못했다(/usr/libexec/java_home -v 17)"

s00_py fetch-artifacts "$TOOLS_DIR"
printf '%s\n' "$S00_OUT" > "$TD_RUN_DIR/S00/artifacts.json"
td_log "S00 artifacts: $(jq -r 'keys | join(",")' "$TD_RUN_DIR/S00/artifacts.json")"

# git 도구: 없으면 clone, 고정 커밋이 없으면 fetch, 그리고 detach checkout. 전체 sha를 돌려준다.
fetch_git_tool() { # <dir> <gh|https> <repo-slug> <pin-commit>
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

s00_py pin-get tia.commit; TIA_PIN="$S00_OUT"
s00_py pin-get tia.repo; TIA_REPO="$S00_OUT"
TIA_SRC="$TOOLS_DIR/tia-src"
TIA_COMMIT="$(fetch_git_tool "$TIA_SRC" https "$TIA_REPO" "$TIA_PIN")" || s00_fail "TIA 소스 확보 실패($TIA_REPO@$TIA_PIN)"
[[ "$TIA_COMMIT" == "$TIA_PIN" ]] || s00_fail "TIA 체크아웃 커밋 ${TIA_COMMIT}이 pin ${TIA_PIN}과 다르다"
if [[ "$(cat "$TOOLS_DIR/tia/.commit" 2>/dev/null)" != "$TIA_COMMIT" || ! -x "$TOOLS_DIR/tia/bin/tia" ]]; then
  td_run 1800 -- env JAVA_HOME="$JAVA17" "$TIA_SRC/gradlew" -p "$TIA_SRC" --no-daemon -q ":tia-cli:installDist" >&2 \
    || s00_fail "TIA 빌드 실패(:tia-cli:installDist, JDK 17)"
  built="$(find "$TIA_SRC/tia-cli/build/install" -maxdepth 3 -path '*/bin/tia' -type f | head -1)"
  [[ -n "$built" ]] || s00_fail "TIA installDist 산출물(bin/tia)을 찾지 못했다"
  rm -rf "$TOOLS_DIR/tia"
  cp -R "$(dirname "$(dirname "$built")")" "$TOOLS_DIR/tia"
  echo "$TIA_COMMIT" > "$TOOLS_DIR/tia/.commit"
fi

# hotspot-analysis: 고정 커밋을 clone해 JDK 21로 bootJar를 빌드하고 work/tools/hotspot.jar로 둔다(S09는 이 경로를 쓴다).
# hotspot.commit 표식이 커밋과 다르거나 jar가 없을 때만 다시 빌드한다.
s00_py pin-get hotspot.commit; HOTSPOT_PIN="$S00_OUT"
s00_py pin-get hotspot.repo; HOTSPOT_REPO="$S00_OUT"
s00_py pin-get hotspot.jdk; HOTSPOT_JDK="$S00_OUT"
s00_py pin-get hotspot.gradleTask; HOTSPOT_TASK="$S00_OUT"
s00_py pin-get hotspot.jarGlob; HOTSPOT_JAR_GLOB="$S00_OUT"
HOTSPOT_JAVA="$(td_java_home "$HOTSPOT_JDK")" || s00_fail "JDK ${HOTSPOT_JDK}을 찾지 못했다(hotspot-analysis 빌드에 필요)"
HOTSPOT_SRC="$TOOLS_DIR/hotspot-src"
HOTSPOT_JAR="$TOOLS_DIR/hotspot.jar"
HOTSPOT_COMMIT="$(fetch_git_tool "$HOTSPOT_SRC" https "$HOTSPOT_REPO" "$HOTSPOT_PIN")" \
  || s00_fail "hotspot 소스 확보 실패($HOTSPOT_REPO@$HOTSPOT_PIN)"
[[ "$HOTSPOT_COMMIT" == "$HOTSPOT_PIN" ]] || s00_fail "hotspot 체크아웃 커밋 ${HOTSPOT_COMMIT}이 pin ${HOTSPOT_PIN}과 다르다"
if [[ "$(cat "$TOOLS_DIR/hotspot.commit" 2>/dev/null)" != "$HOTSPOT_COMMIT" || ! -f "$HOTSPOT_JAR" ]]; then
  # 재사용 clone의 build/libs에 이전 커밋의 jar(다른 버전 이름)가 남으면 glob이 2개를 잡으므로 빌드 전에 비운다.
  rm -rf "$HOTSPOT_SRC/build/libs"
  td_run 1800 -- env JAVA_HOME="$HOTSPOT_JAVA" "$HOTSPOT_SRC/gradlew" -p "$HOTSPOT_SRC" --no-daemon -q "$HOTSPOT_TASK" >&2 \
    || s00_fail "hotspot 빌드 실패($HOTSPOT_TASK, JDK $HOTSPOT_JDK)"
  hotspot_jars=()
  shopt -s nullglob
  for candidate in "$HOTSPOT_SRC"/$HOTSPOT_JAR_GLOB; do
    [[ "$(basename "$candidate")" == *-plain* ]] || hotspot_jars+=("$candidate")
  done
  shopt -u nullglob
  [[ ${#hotspot_jars[@]} -eq 1 ]] || s00_fail "hotspot jar가 정확히 1개여야 한다(glob $HOTSPOT_JAR_GLOB, -plain 제외): ${#hotspot_jars[@]}개"
  cp "${hotspot_jars[0]}" "$HOTSPOT_JAR.part" && mv -f "$HOTSPOT_JAR.part" "$HOTSPOT_JAR" || s00_fail "hotspot jar 복사 실패"
  echo "$HOTSPOT_COMMIT" > "$TOOLS_DIR/hotspot.commit"
fi

s00_py pin-get bbtg.commit; BBTG_PIN="$S00_OUT"
s00_py pin-get bbtg.repo; BBTG_REPO="$S00_OUT"
BBTG_DIR="$TOOLS_DIR/bbtg"
BBTG_COMMIT="$(fetch_git_tool "$BBTG_DIR" gh "$BBTG_REPO" "$BBTG_PIN")" \
  || s00_fail "bbtg 소스 확보 실패($BBTG_REPO@$BBTG_PIN): 비공개 레포라 gh 인증이 필요하다"
[[ "$BBTG_COMMIT" == "$BBTG_PIN" ]] || s00_fail "bbtg 체크아웃 커밋 ${BBTG_COMMIT}이 pin ${BBTG_PIN}과 다르다"
s00_py pin-get bbtg.python; PY_VERSION="$S00_OUT"
PYTHON_BIN="$(command -v "python$PY_VERSION")" || s00_fail "python${PY_VERSION}이 없다(bbtg 전용 venv에 필요)"
REQ_SHA="$(shasum -a 256 "$BBTG_DIR/requirements.txt" | cut -d' ' -f1)"
VENV_STAMP="$REQ_SHA:$BBTG_COMMIT:$PY_VERSION"
if [[ "$(cat "$BBTG_DIR/.venv/.td-stamp" 2>/dev/null)" != "$VENV_STAMP" ]]; then
  rm -rf "$BBTG_DIR/.venv"
  td_run 300 -- "$PYTHON_BIN" -m venv "$BBTG_DIR/.venv" >&2 || s00_fail "bbtg venv 생성 실패"
  td_run 900 -- "$BBTG_DIR/.venv/bin/python" -m pip install --quiet -r "$BBTG_DIR/requirements.txt" >&2 \
    || s00_fail "bbtg requirements 설치 실패"
  echo "$VENV_STAMP" > "$BBTG_DIR/.venv/.td-stamp"
fi

# jQA: 설정 파일로 Spring 플러그인을 로딩해 보고 플러그인 목록을 얻는다(Maven Central에서 받아 온다).
JQA_VERIFY_DIR="$TOOLS_DIR/jqassistant-verify"
# 사용자 전역 ~/.jqassistant 대신 전용 로컬 저장소를 쓰고, 거기서 해석된 플러그인 jar의 sha256을 pin과 대조한다.
JQA_REPO="$TOOLS_DIR/jqa-repo"
mkdir -p "$JQA_VERIFY_DIR"
td_py -m td.prepare jqa-config > "$JQA_VERIFY_DIR/.jqassistant.yml" || s00_fail "jQA 검증 설정 생성 실패"
(cd "$JQA_VERIFY_DIR" && td_run 900 -- env JAVA_HOME="$JAVA17" "$TOOLS_DIR/jqassistant/bin/jqassistant" effective-configuration \
  -C "$JQA_VERIFY_DIR/.jqassistant.yml" -Djqassistant.repositories.local="$JQA_REPO") > "$SCRATCH/jqa-effective.txt" 2>&1 \
  || s00_fail "jQA 실행 실패: $(tail -5 "$SCRATCH/jqa-effective.txt")"
s00_py jqa-plugins "$SCRATCH/jqa-effective.txt" --repo "$JQA_REPO"
printf '%s\n' "$S00_OUT" > "$TD_RUN_DIR/S00/jqa-plugins.json"
td_log "S00 jQA plugins: $(jq -c '.plugins' "$TD_RUN_DIR/S00/jqa-plugins.json")"

# --- 4. claude CLI와 격리 플래그 검증 -------------------------------------------------------------
command -v claude >/dev/null 2>&1 || s00_fail "claude CLI를 찾지 못했다"
td_run 60 -- claude --version > "$SCRATCH/claude-version.txt" 2>/dev/null || s00_fail "claude --version 실패"
s00_py claude-version "$SCRATCH/claude-version.txt"; CLAUDE_VERSION="$S00_OUT"
td_run 60 -- claude --help > "$SCRATCH/claude-help.txt" 2>&1 || s00_fail "claude --help 실패"
s00_py claude-help "$SCRATCH/claude-help.txt"
s00_py model "$TD_ROOT/pipeline/config.yaml"; MODEL="$S00_OUT"
# 무해한 프롬프트 1회를 고정 플래그 전체로 실제 호출한다(cwd는 임시 디렉터리, --bare는 OAuth를 못 읽어 쓰지 않는다).
mkdir -p "$SCRATCH/llm-cwd"
echo '{"mcpServers":{}}' > "$SCRATCH/empty-mcp.json"
CLAUDE_ARGV=()
while IFS= read -r -d '' token; do CLAUDE_ARGV+=("$token"); done < <(td_py -m td.prepare claude-argv \
  --mcp-config "$SCRATCH/empty-mcp.json" --system-prompt "You are a terse assistant." --model "$MODEL")
[[ ${#CLAUDE_ARGV[@]} -gt 0 ]] || s00_fail "claude 인자 목록을 얻지 못했다(td.prepare claude-argv)"
(cd "$SCRATCH/llm-cwd" && td_run 900 -- claude "${CLAUDE_ARGV[@]}" "reply with OK") > "$SCRATCH/claude-call.json" 2> "$SCRATCH/claude-call.err" \
  || s00_fail "claude 격리 플래그 호출 실패(model=$MODEL): $(head -c 400 "$SCRATCH/claude-call.err") $(head -c 400 "$SCRATCH/claude-call.json")"
s00_py claude-result "$SCRATCH/claude-call.json" --model "$MODEL"

# --- 5. SUT 빌드 ------------------------------------------------------------------------------------
SUT_JAVA="$(sut_get java)"; SUT_JAVA_HOME="$(java_home "$SUT_JAVA")"
[[ -n "$SUT_JAVA_HOME" ]] || s00_fail "SUT가 요구하는 JDK ${SUT_JAVA}를 찾지 못했다"
BUILD_CMD="$(sut_get build.cmd)"
(cd "$TD_SUT_SRC" && td_run 1800 -- env JAVA_HOME="$SUT_JAVA_HOME" bash -c "$BUILD_CMD") > "$SCRATCH/sut-build.log" 2>&1 \
  || s00_fail "SUT 빌드 실패($BUILD_CMD): $(tail -15 "$SCRATCH/sut-build.log")"
JAR_GLOB="$(sut_get jar)"
shopt -s nullglob
jars=("$TD_SUT_SRC"/$JAR_GLOB)
shopt -u nullglob
[[ ${#jars[@]} -eq 1 ]] || s00_fail "SUT jar가 정확히 1개여야 한다(glob $JAR_GLOB): ${#jars[@]}개"
CLASSES_DIR="$TD_SUT_SRC/$(sut_get classes)"
[[ -d "$CLASSES_DIR" ]] || s00_fail "SUT classes 디렉터리가 없다: $CLASSES_DIR"

# --- 5b. 비인증 상태 실측 ---------------------------------------------------------------------------
# 설계 시점의 기대값(sut.yaml)을 믿지 않고 SUT를 실제로 띄워 토큰 없이 auth.probe를 호출해 본다.
# 항상 td_sut_down으로 내리며(실패 경로는 종료 trap이 내린다), 값이 다르면 단계는 failed다.
export TD_SUT_JAR="${jars[0]}" TD_AGENT_JAR="$TOOLS_DIR/pjacoco-agent.jar"
td_sut_up "$TD_RUN_DIR" S00 probe || s00_fail "SUT 기동 실패(비인증 실측): $TD_SUT_FAIL_REASON"
PROBE_SPEC="$(sut_get auth.probe)"
probe_method="${PROBE_SPEC%% *}"; probe_path="${PROBE_SPEC#* }"
measured_status="$(td_run 30 -- curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X "$probe_method" "$TD_BASE_URL$probe_path")"
td_sut_down
expected_status="$(sut_get auth.unauthenticated_status)"
td_log "S00 비인증 실측: $PROBE_SPEC -> $measured_status (sut.yaml 기대 $expected_status)"
[[ "$measured_status" == "$expected_status" ]] \
  || s00_fail "비인증 응답 코드가 sut.yaml과 다르다: 실측 $measured_status, 기대 $expected_status ($PROBE_SPEC). sut.yaml auth.unauthenticated_status를 실측값으로 고친다."

# --- 6. tools.lock과 run.json -------------------------------------------------------------------------
s00_py write-lock --run-dir "$TD_RUN_DIR" --run-id "$TD_RUN_ID" --sut "$TD_SUT_NAME" --sut-commit "$TD_SUT_COMMIT" \
  --artifacts "$TD_RUN_DIR/S00/artifacts.json" --tia-commit "$TIA_COMMIT" \
  --hotspot-commit "$HOTSPOT_COMMIT" --hotspot-jar "$HOTSPOT_JAR" --bbtg-commit "$BBTG_COMMIT" \
  --bbtg-requirements-sha256 "$REQ_SHA" --claude-version "$CLAUDE_VERSION" --model "$MODEL" \
  --jqa-plugins "$TD_RUN_DIR/S00/jqa-plugins.json" --python-version "$PY_VERSION" --claude-verified true
LOCK_FILE="$S00_OUT"
TOOLS_SUMMARY="$(jq -c --arg model "$MODEL" --arg cv "$CLAUDE_VERSION" \
  '{pjacoco: .pjacoco.version, jacococli: .jacococli.version, jqassistant: .jqassistant.version,
    jqassistantSpring: .jqassistantSpring.version, claude: $cv, model: $model}' \
  "$TD_RUN_DIR/S00/artifacts.json")"
TOOLS_SUMMARY="$(jq -c --arg hotspot "${HOTSPOT_COMMIT:0:7}" --arg tia "${TIA_COMMIT:0:7}" --arg bbtg "${BBTG_COMMIT:0:7}" \
  '. + {hotspot: $hotspot, tia: $tia, bbtg: $bbtg}' <<< "$TOOLS_SUMMARY")"
td_py -m td.state set "$TD_RUN_DIR" tools "$TOOLS_SUMMARY" || s00_fail "run.json tools 기록 실패"

OUTPUTS="$(jq -cn --arg jar "${jars[0]}" --arg classes "$CLASSES_DIR" --arg lock "$LOCK_FILE" --arg tools "$TOOLS_DIR" \
  --arg commit "$TD_SUT_COMMIT" --arg src "$TD_SUT_SRC" --argjson unauth "$measured_status" \
  '{jar: $jar, classes: $classes, toolsLock: $lock, toolsDir: $tools, commit: $commit, src: $src, unauthenticatedStatus: $unauth}')"
td_stage_end S00 passed --outputs-json "$OUTPUTS"
