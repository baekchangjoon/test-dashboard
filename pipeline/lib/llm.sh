#!/usr/bin/env bash
# 격리된 LLM 호출 래퍼(설계 §13.4). S05와 S06의 모든 claude 호출(수리 포함)은 이 스크립트 하나만 거친다.
# 사용: llm.sh <bundle_dir> <prompt_file> <out_json>
#   - 번들은 `td.bundle build`가 쓴 검사 서명(.td-bundle-verified.json)과 일치해야 한다(아니면 exit 2, claude 미호출).
#   - cwd는 번들을 복사한 임시 디렉터리다(번들 원본과 repo, SUT 어디도 아니다). 종료 시 지운다.
#   - 프롬프트(+ 번들 인라인)는 stdin으로만 넘긴다. argv에는 본문이 없다.
#   - 인자 목록은 td.prepare의 CLAUDE_ARGV_TEMPLATE 하나에서 받는다(S00의 검증 호출과 어긋나지 않게).
#     -p --tools "" --strict-mcp-config --mcp-config <빈 JSON> --setting-sources "" --system-prompt <고정> --output-format json --model <모델>
#   - 실제 claude는 claude-shim을 거쳐 부른다. shim이 호출 메타(플래그 이름, cwd)를 $TD_RUN_DIR/llm-calls.jsonl에 남긴다.
#   - 모델: TD_LLM_MODEL 또는 pipeline/config.yaml의 llm.model. 시간 제한 900초(td_run).
#   - 시험 전용: TD_SITE_PREFIX가 있을 때 TD_LLM_OUTPUT_FORMAT=stream-json이면 출력 형식을 바꾼다(카나리가 tool_use를 센다).
# 종료 코드: 0 성공, 2 사용법·입력 오류, 3 claude 응답이 오류이거나 JSON이 아님, 그 밖은 claude/td_run의 코드(시간 초과 124).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

LLM_SYSTEM_PROMPT="You generate test scenarios from the provided bundle only. Reply with exactly the requested output and nothing else."

bundle_dir="${1:-}"; prompt_file="${2:-}"; out_json="${3:-}"
if [[ -z "$bundle_dir" || -z "$prompt_file" || -z "$out_json" ]]; then
  echo "usage: llm.sh <bundle_dir> <prompt_file> <out_json>" >&2; exit 2
fi
[[ -d "$bundle_dir" ]] || { echo "llm.sh: 번들 디렉터리가 없다: $bundle_dir" >&2; exit 2; }
[[ -f "$prompt_file" ]] || { echo "llm.sh: 프롬프트 파일이 없다: $prompt_file" >&2; exit 2; }
mkdir -p "$(dirname "$out_json")"

# A1 심층 방어: td.bundle build가 검사하고 서명한 번들만 받는다(서명 없음, 파일 추가·변조, 심볼릭 링크는 claude 호출 전에 거부).
td_py -m td.bundle verify "$bundle_dir" || { echo "llm.sh: 검증되지 않은 번들이라 호출을 거부한다" >&2; exit 2; }

scratch="$(mktemp -d "${TMPDIR:-/tmp}/td-llm.XXXXXX")" || exit 2
cleanup_llm() { rm -rf "$scratch"; }
trap cleanup_llm EXIT
trap 'exit 143' INT TERM

mkdir "$scratch/cwd"
cp -R "$bundle_dir"/. "$scratch/cwd"/
rm -f "$scratch/cwd/.td-bundle-verified.json"
{ cat "$prompt_file"; printf '\n\n'; td_py -m td.bundle inline "$bundle_dir"; } > "$scratch/stdin.txt" \
  || { echo "llm.sh: 번들 인라인 실패" >&2; exit 2; }

model="$(td_py -m td.prepare model "$TD_ROOT/pipeline/config.yaml")" || { echo "llm.sh: 모델을 읽지 못했다" >&2; exit 2; }
argv=()
while IFS= read -r -d '' token; do argv+=("$token"); done < <(td_py -m td.prepare claude-argv \
  --mcp-config '{"mcpServers":{}}' --system-prompt "$LLM_SYSTEM_PROMPT" --model "$model")
[[ ${#argv[@]} -gt 0 ]] || { echo "llm.sh: claude 인자 목록을 얻지 못했다" >&2; exit 2; }

stream_mode=false
if [[ -n "${TD_SITE_PREFIX:-}" && -n "${TD_LLM_OUTPUT_FORMAT:-}" ]]; then
  for index in "${!argv[@]}"; do
    if [[ "${argv[$index]}" == "--output-format" ]]; then argv[$((index + 1))]="$TD_LLM_OUTPUT_FORMAT"; fi
  done
  if [[ "$TD_LLM_OUTPUT_FORMAT" == "stream-json" ]]; then argv+=(--verbose); fi
  stream_mode=true
fi

call_log="${TD_LLM_CALL_LOG:-}"
[[ -z "$call_log" && -n "${TD_RUN_DIR:-}" ]] && call_log="$TD_RUN_DIR/llm-calls.jsonl"

rc=0
( cd "$scratch/cwd" && \
  TD_LLM_CALL_LOG="$call_log" td_run "${TD_LLM_TIMEOUT:-900}" -- \
    env -u TD_SUT_USER -u TD_SUT_PASS -u SONAR_TOKEN -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \
    "$TD_ROOT/pipeline/lib/claude-shim" "${argv[@]}" < "$scratch/stdin.txt" > "$scratch/out.json" 2> "$scratch/err.txt" ) || rc=$?
if [[ $rc -ne 0 ]]; then
  echo "llm.sh: claude 호출 실패(rc=$rc): $(head -c 600 "$scratch/err.txt") $(head -c 300 "$scratch/out.json")" >&2
  exit "$rc"
fi
cp "$scratch/out.json" "$out_json"
if [[ "$stream_mode" == false ]]; then
  td_py -m td.prepare claude-result "$out_json" > /dev/null || { echo "llm.sh: claude 응답이 오류이거나 JSON이 아니다" >&2; exit 3; }
fi
exit 0
