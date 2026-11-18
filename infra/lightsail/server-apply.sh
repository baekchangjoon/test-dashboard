#!/usr/bin/env bash
# 서버(또는 로컬 fixture)에서 실행되는 기계적 단계. apply.sh가 ssh로 stdin에 흘려 넣거나 로컬에서 직접 실행한다.
#   mkdir -> 백업 -> validate(일회성 컨테이너) -> 교체 -> caddy만 재생성 -> 120초 재시도 확인 -> 실패 시 바이트 복원
# 입력(환경 변수): STACK_DIR DASH_DIR SONAR_URL DASH_URL [SONAR_HOST DASH_HOST COMPOSE_PROJECT SUDO TEST_LABEL FAIL_AFTER]
# 입력 파일: $STACK_DIR/Caddyfile.td-new, $STACK_DIR/docker-compose.yml.td-new (apply.sh가 올려 둔 패치본)
# 종료 코드: 0 성공, 20 validate 실패(변경 없음), 30 변경 후 실패(복원함), 31 복원 후에도 Sonar가 UP이 아님
# sonarqube/db 컨테이너와 볼륨은 건드리지 않는다(`--no-deps`, caddy 서비스만).
set -uo pipefail

: "${STACK_DIR:?}" "${DASH_DIR:?}" "${SONAR_URL:?}" "${DASH_URL:?}"
SUDO="${SUDO:-}"
COMPOSE=(docker compose)
[[ -n "${COMPOSE_PROJECT:-}" ]] && COMPOSE=(docker compose -p "$COMPOSE_PROJECT")
cd "$STACK_DIR" || exit 1

log() { printf '[lightsail] %s\n' "$*" >&2; }
compose() { "${COMPOSE[@]}" "$@"; }

curl_url() {  # curl_url URL [HOST헤더] -> stdout 본문, 성공(2xx)이면 0
  local url="$1" host="${2:-}" args=(-fsS --max-time 10)
  [[ -n "$host" ]] && args+=(-H "Host: $host")
  curl "${args[@]}" "$url"
}

sonar_up() { curl_url "$SONAR_URL" "${SONAR_HOST:-}" 2>/dev/null | grep -q '"status":"UP"'; }
dash_ok() { curl_url "$DASH_URL" "${DASH_HOST:-}" >/dev/null 2>&1; }

wait_for() {  # wait_for 이름 함수 -- 120초 동안 5초 간격 재시도
  local name="$1" fn="$2" deadline=$((SECONDS + 120))
  while true; do
    "$fn" && { log "$name OK"; return 0; }
    (( SECONDS >= deadline )) && { log "$name 확인 실패(120초)"; return 1; }
    sleep 5
  done
}

recreate_caddy() { compose up -d --no-deps --force-recreate caddy >&2; }

BACKUP_DIR="$STACK_DIR/.td-backup/$(date -u +%Y%m%dT%H%M%SZ)"
MUTATED=0

restore() {
  log "복원 시작: 백업 바이트로 되돌리고 이전 설정으로 caddy 재생성"
  cat "$BACKUP_DIR/Caddyfile" > "$STACK_DIR/Caddyfile"
  cat "$BACKUP_DIR/docker-compose.yml" > "$STACK_DIR/docker-compose.yml"
  cmp -s "$BACKUP_DIR/Caddyfile" "$STACK_DIR/Caddyfile" && cmp -s "$BACKUP_DIR/docker-compose.yml" "$STACK_DIR/docker-compose.yml" \
    || log "경고: 복원 후 바이트 불일치"
  recreate_caddy || log "경고: 복원 후 caddy 재생성 실패"
  wait_for "복원 후 sonar" sonar_up || exit 31
}

fail_after_mutation() {
  log "실패: $1"
  restore
  rm -f "$STACK_DIR/Caddyfile.td-new" "$STACK_DIR/docker-compose.yml.td-new"
  exit 30
}

# 1. /srv/dashboard 생성과 소유권, 최초 1회 자리표시자
$SUDO install -d -o "$(id -un)" -g "$(id -gn)" "$DASH_DIR" || { log "dashboard 디렉터리 생성 실패"; exit 20; }
if [[ ! -e "$DASH_DIR/index.html" ]]; then
  printf '<!doctype html><meta charset="utf-8"><title>test-dashboard</title><p>준비 중</p>\n' > "$DASH_DIR/index.html"
fi

# 2. 변경 전 상태 확인과 백업
sonar_up || { log "변경 전부터 sonar가 UP이 아니다: 중단"; exit 20; }
mkdir -p "$BACKUP_DIR"
cp -p Caddyfile docker-compose.yml "$BACKUP_DIR/"
log "백업: $BACKUP_DIR"

# 3. 새 Caddyfile을 일회성 컨테이너로 검증한다(실서비스에 닿기 전)
LABEL_ARGS=()
[[ -n "${TEST_LABEL:-}" ]] && LABEL_ARGS=(--label "test-run=$TEST_LABEL")
if ! docker run --rm "${LABEL_ARGS[@]}" -v "$STACK_DIR/Caddyfile.td-new:/etc/caddy/Caddyfile:ro" \
      -v "$DASH_DIR:/srv/dashboard:ro" caddy:2 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >&2; then
  log "Caddyfile validate 실패: 변경하지 않고 중단"
  rm -f Caddyfile.td-new docker-compose.yml.td-new
  exit 20
fi
if ! compose -f docker-compose.yml.td-new config -q >&2; then
  log "compose 검증 실패: 변경하지 않고 중단"
  rm -f Caddyfile.td-new docker-compose.yml.td-new
  exit 20
fi

# 4. 교체(같은 inode에 덮어써 bind mount를 유지) -> caddy만 재생성 -> 확인
MUTATED=1
cat Caddyfile.td-new > Caddyfile
cat docker-compose.yml.td-new > docker-compose.yml
rm -f Caddyfile.td-new docker-compose.yml.td-new

recreate_caddy || fail_after_mutation "caddy 재생성 실패"
[[ "${FAIL_AFTER:-}" == "recreate" ]] && fail_after_mutation "주입 실패(recreate)"

if [[ "${FAIL_AFTER:-}" == "health" ]]; then
  fail_after_mutation "주입 실패(health)"
fi
wait_for "sonar" sonar_up || fail_after_mutation "sonar 상태 확인 실패"
wait_for "dash" dash_ok || fail_after_mutation "dash 응답 확인 실패"
log "완료"
