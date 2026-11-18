#!/usr/bin/env bash
# Lightsail(sonar 호스트)에 dash.<domain> 정적 사이트를 붙인다.
#   apply.sh                  실제 서버(infra/local.env 사용)
#   apply.sh --local <dir>    로컬 fixture(<dir>/{Caddyfile,docker-compose.yml,fixture.env}): Route53·ssh 없이 같은 절차를 돌린다
# 순서: (읽기) 현재 파일 가져와 패치 -> Route53 dash A CREATE -> 서버 단계(server-apply.sh: 백업/validate/교체/재생성/확인)
#       -> 성공: after 스냅샷 갱신 + compare / 실패: 파일 복원(서버 단계가 수행) + dash 레코드를 이전 상태로 복원
# 실패 주입(--local 전용): TD_LIGHTSAIL_FAIL_AFTER=recreate|health, TD_LIGHTSAIL_BLOCK_FILE=<잘못된 블록 파일>
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/pipeline/lib/common.sh"

HERE="$TD_ROOT/infra/lightsail"
LOCAL_DIR=""
if [[ "${1:-}" == "--local" ]]; then
  LOCAL_DIR="$(cd "${2:?--local <fixture_dir>}" && pwd)"
elif [[ $# -gt 0 ]]; then
  echo "usage: apply.sh [--local <fixture_dir>]" >&2; exit 2
fi

SCRATCH="$(mktemp -d)"
DNS_CREATED=0
ZONE_ID=""
cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

BLOCK_FILE="$HERE/Caddyfile.block"
SERVER_ENV=()

if [[ -n "$LOCAL_DIR" ]]; then
  set -a; source "$LOCAL_DIR/fixture.env"; set +a
  [[ -n "${TD_LIGHTSAIL_BLOCK_FILE:-}" ]] && BLOCK_FILE="$TD_LIGHTSAIL_BLOCK_FILE"
  STACK_DIR="$LOCAL_DIR"
  cp "$STACK_DIR/Caddyfile" "$SCRATCH/Caddyfile.cur"
  cp "$STACK_DIR/docker-compose.yml" "$SCRATCH/docker-compose.yml.cur"
  SERVER_ENV=(STACK_DIR="$STACK_DIR" DASH_DIR="$DASH_DIR" SONAR_URL="$SONAR_URL" SONAR_HOST="$SONAR_HOST"
              DASH_URL="$DASH_URL" DASH_HOST="$DASH_HOST" COMPOSE_PROJECT="$COMPOSE_PROJECT"
              TEST_LABEL="$TD_TEST_LABEL" FAIL_AFTER="${TD_LIGHTSAIL_FAIL_AFTER:-}"
              WAIT_SECONDS="${TD_LIGHTSAIL_WAIT_SECONDS:-120}")
  remote_stage() { td_run 600 -- env "${SERVER_ENV[@]}" bash "$HERE/server-apply.sh"; }
  put_files() { cp "$SCRATCH/Caddyfile.new" "$STACK_DIR/Caddyfile.td-new"; cp "$SCRATCH/docker-compose.yml.new" "$STACK_DIR/docker-compose.yml.td-new"; }
else
  set -a; source "$TD_ROOT/infra/local.env"; set +a
  export AWS_REGION="${AWS_REGION:-ap-northeast-2}"
  DASH_ADDR="dash.$TD_DOMAIN"
  DASH_DIR="/srv/dashboard"
  SSH_OPTS=(-i "$TD_SSH_KEY_PATH" -o BatchMode=yes -o ConnectTimeout=20)
  SSH_TARGET="ubuntu@$TD_LIGHTSAIL_IP"
  td_run 120 -- ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'cat ~/sonarqube/Caddyfile' > "$SCRATCH/Caddyfile.cur"
  td_run 120 -- ssh "${SSH_OPTS[@]}" "$SSH_TARGET" 'cat ~/sonarqube/docker-compose.yml' > "$SCRATCH/docker-compose.yml.cur"
  SERVER_ENV=(STACK_DIR='$HOME/sonarqube' DASH_DIR="$DASH_DIR" SUDO=sudo
              SONAR_URL="https://sonar.$TD_DOMAIN/api/system/status" DASH_URL="https://$DASH_ADDR/")
  # 서버 단계는 120초 재시도(2회)와 컨테이너 재생성을 포함하므로 SSH 기본 120초보다 길게 둔다.
  remote_stage() { td_run 600 -- ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "env ${SERVER_ENV[*]} bash -s" < "$HERE/server-apply.sh"; }
  put_files() {
    td_run 120 -- scp "${SSH_OPTS[@]}" -q "$SCRATCH/Caddyfile.new" "$SSH_TARGET:sonarqube/Caddyfile.td-new"
    td_run 120 -- scp "${SSH_OPTS[@]}" -q "$SCRATCH/docker-compose.yml.new" "$SSH_TARGET:sonarqube/docker-compose.yml.td-new"
  }
fi

# 1. (읽기 전용) 패치본 만들기
td_py -m td.lightsail caddyfile "$SCRATCH/Caddyfile.cur" "$BLOCK_FILE" "$DASH_ADDR" "$SCRATCH/Caddyfile.new"
td_py -m td.lightsail compose "$SCRATCH/docker-compose.yml.cur" "$HERE/compose.patch.yml" "$DASH_DIR" "$SCRATCH/docker-compose.yml.new"

# 2. Route53 dash A: 충돌 검사 후 CREATE(같은 값이면 그대로, 다른 값이면 중단). 로컬 모드는 건너뛴다.
INFRA_WORK="$TD_WORK_DIR/infra"
if [[ -z "$LOCAL_DIR" ]]; then
  mkdir -p "$INFRA_WORK"
  ZONE_ID="$(td_py -m td.route53 zone-id "$TD_DOMAIN")"
  # 변경 전 dash 상태(없음 포함)를 롤백용으로 남긴다.
  td_py -m td.route53 snapshot "$ZONE_ID" "$INFRA_WORK/route53-before-dash.$(date -u +%Y%m%dT%H%M%SZ).json"
  td_py -m td.route53 check "$ZONE_ID" dash --expected-target "$TD_LIGHTSAIL_IP" \
    || { td_log "dash가 이미 다른 값으로 있다: 적용 중단"; exit 4; }
  if [[ "$(td_py -m td.route53 state "$ZONE_ID" "dash.$TD_DOMAIN." "$TD_LIGHTSAIL_IP")" == absent ]]; then
    td_py -m td.route53 create-a "$ZONE_ID" "dash.$TD_DOMAIN." "$TD_LIGHTSAIL_IP"
    DNS_CREATED=1
    td_log "dash A 레코드 생성"
  else
    td_log "dash A 레코드가 이미 같은 값으로 있다: 그대로 둔다"
  fi
fi

rollback_dns() {  # 우리가 만든 레코드만 지운다(이미 있던 같은 값 레코드는 건드리지 않는다)
  if [[ "$DNS_CREATED" == 1 ]]; then
    td_log "dash 레코드를 이전 상태(없음)로 복원"
    td_py -m td.route53 delete-a "$ZONE_ID" "dash.$TD_DOMAIN." "$TD_LIGHTSAIL_IP" || td_log "경고: dash 레코드 삭제 실패(수동 확인 필요)"
  fi
}

# 3. 서버 단계(변경 이후 실패·시그널 복원은 server-apply.sh의 trap이 담당, DNS 복원은 여기서)
# 서버 단계는 백그라운드로 돌리고 HUP/INT/TERM을 그쪽으로 넘겨, 중단돼도 서버 쪽 trap이 복원하게 한다.
rc=0
put_files || rc=$?
if (( rc == 0 )); then
  remote_stage &
  STAGE_PID=$!
  trap 'kill -TERM "$STAGE_PID" 2>/dev/null' HUP INT TERM
  wait "$STAGE_PID" || rc=$?
  if (( rc > 128 )); then rc=0; wait "$STAGE_PID" || rc=$?; fi  # 시그널로 깨어났으면 실제 종료까지 기다린다
  trap - HUP INT TERM
fi
if (( rc != 0 )); then
  td_log "서버 단계 실패(rc=$rc)"
  rollback_dns
  exit "$rc"
fi

# 4. 성공: after 스냅샷 갱신과 허용 밖 변경 비교
if [[ -z "$LOCAL_DIR" ]]; then
  AFTER="$INFRA_WORK/route53-after.json"
  td_py -m td.route53 snapshot "$ZONE_ID" "$AFTER"
  td_py -m td.route53 compare "$INFRA_WORK/route53-before.json" "$AFTER" \
    --allow "reports.$TD_DOMAIN.,A" --allow "reports.$TD_DOMAIN.,AAAA" --allow "_*.reports.$TD_DOMAIN.,CNAME" \
    --allow "dash.$TD_DOMAIN.,A" || { td_log "허용 밖 Route53 변경 발견"; exit 5; }
fi
td_log "완료: $DASH_ADDR"
