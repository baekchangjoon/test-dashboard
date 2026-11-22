#!/usr/bin/env bash
# PICT(pairwise 조합 생성기) 고정 빌드. S00-prepare.sh와 테스트가 source한다.
# td_prepare_pict는 실패해도 종료 코드 0이고 결과는 <out_json>에만 쓴다(S00 실패 격리, 설계 §5.6).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

# _td_pict_sha256 <file> — 파일 sha256(hex).
_td_pict_sha256() { shasum -a 256 "$1" | cut -d' ' -f1; }

# td_prepare_pict <tools_dir> <out_json>
# <tools_dir>/pict-src에 고정 커밋을 받고, 스탬프(<tools_dir>/pict/.commit = {commit, binarySha256})가
# 커밋·현재 바이너리 sha와 모두 맞으면 재사용, 아니면 clean -fdx 후 make로 빌드해 <tools_dir>/pict/pict에 둔다.
# 그 뒤 내장 스모크 모델 출력이 기대와 같아야 스탬프를 쓴다.
# 결과 JSON: 성공 {commit, binarySha256, path} | 실패 {failure: clone-failed|build-failed|smoke-mismatch, detail}.
td_prepare_pict() {
  local tools_dir="${1:?tools_dir}" out_json="${2:?out_json}"
  local src="$tools_dir/pict-src" bin_dir="$tools_dir/pict" bin="$tools_dir/pict/pict"
  local stamp="$tools_dir/pict/.commit" log pin repo commit sha stamp_commit="" stamp_sha=""
  log="$(mktemp "${TMPDIR:-/tmp}/td-pict.XXXXXX")" || return 0
  mkdir -p "$(dirname "$out_json")" "$tools_dir"

  _td_pict_fail() { # <code> — 로그 끝부분을 상세로 결과를 쓴다
    td_log "pict 준비 실패($1): det pairwise는 unavailable이 된다"
    td_py -m td.prepare pict-result --out "$out_json" --failure "$1" --detail-file "$log" \
      || printf '{"failure": "%s", "detail": ""}\n' "$1" > "$out_json"
    rm -f "$log"
    return 0
  }

  pin="$(td_py -m td.prepare pin-get pict.commit 2>>"$log")" || { _td_pict_fail clone-failed; return 0; }
  repo="$(td_py -m td.prepare pin-get pict.repo 2>>"$log")" || { _td_pict_fail clone-failed; return 0; }
  commit="$(fetch_git_tool "$src" https "$repo" "$pin" 2>>"$log")" || { _td_pict_fail clone-failed; return 0; }
  if [[ "$commit" != "$pin" ]]; then
    echo "체크아웃 커밋 $commit이 pin $pin과 다르다" >> "$log"
    _td_pict_fail clone-failed; return 0
  fi

  if [[ -f "$stamp" && -x "$bin" ]]; then
    stamp_commit="$(jq -r '.commit // ""' "$stamp" 2>/dev/null)" || stamp_commit=""
    stamp_sha="$(jq -r '.binarySha256 // ""' "$stamp" 2>/dev/null)" || stamp_sha=""
  fi
  if [[ -n "$stamp_sha" && "$stamp_commit" == "$pin" && "$(_td_pict_sha256 "$bin")" == "$stamp_sha" ]]; then
    td_log "pict 재사용(${pin:0:7})"
  else
    rm -f "$stamp"
    git -c core.hooksPath=/dev/null -C "$src" clean -fdxq >>"$log" 2>&1 || { _td_pict_fail build-failed; return 0; }
    (cd "$src" && td_run 300 -- make -j4) >>"$log" 2>&1 || { _td_pict_fail build-failed; return 0; }
    if [[ ! -x "$src/pict" ]]; then
      echo "make 뒤 pict 바이너리가 없다" >> "$log"
      _td_pict_fail build-failed; return 0
    fi
    mkdir -p "$bin_dir"
    { cp "$src/pict" "$bin.part" && mv -f "$bin.part" "$bin"; } >>"$log" 2>&1 || { _td_pict_fail build-failed; return 0; }
  fi

  if ! td_py -m td.prepare pict-smoke "$bin" >>"$log" 2>&1; then
    rm -f "$stamp"
    _td_pict_fail smoke-mismatch; return 0
  fi
  sha="$(_td_pict_sha256 "$bin")"
  jq -n --arg commit "$pin" --arg sha "$sha" '{commit: $commit, binarySha256: $sha}' > "$stamp"
  td_py -m td.prepare pict-result --out "$out_json" --commit "$pin" --binary-sha256 "$sha" --path "$bin" \
    || { _td_pict_fail build-failed; return 0; }
  rm -f "$log"
  return 0
}

# td_s00_prepare_pict <tools_dir> <out_json> — S00의 det 분기. det가 요청된 run(td_arm_requested det)에서만
# td_prepare_pict를 부르고, 실패면 경고를 남긴다. 미요청이면 아무것도 하지 않는다(<out_json>도 만들지 않는다).
td_s00_prepare_pict() {
  local tools_dir="${1:?tools_dir}" out_json="${2:?out_json}"
  td_arm_requested det || return 0
  td_prepare_pict "$tools_dir" "$out_json"
  if jq -e 'has("failure")' "$out_json" >/dev/null 2>&1; then
    td_log "S00 경고: pict 준비 실패($(jq -r '.failure' "$out_json")) — 상세 $out_json, 다른 arm은 영향 없음"
  fi
  return 0
}
