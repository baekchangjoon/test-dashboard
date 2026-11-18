#!/usr/bin/env bash
# apply.sh의 되돌리기: 서버의 최신 백업(.td-backup/<ts>)으로 Caddyfile·compose를 바이트 그대로 복원하고 caddy만 재생성한 뒤,
# dash A 레코드를 삭제한다. /srv/dashboard 디렉터리는 데이터 보존을 위해 남긴다.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/pipeline/lib/common.sh"
set -a; source "$TD_ROOT/infra/local.env"; set +a
export AWS_REGION="${AWS_REGION:-ap-northeast-2}"

SSH_OPTS=(-i "$TD_SSH_KEY_PATH" -o BatchMode=yes -o ConnectTimeout=20)
td_run 300 -- ssh "${SSH_OPTS[@]}" "ubuntu@$TD_LIGHTSAIL_IP" 'set -e
  cd ~/sonarqube
  latest="$(ls -1d .td-backup/* | sort | head -1)"   # 가장 오래된 백업 = 적용 전 원본
  cat "$latest/Caddyfile" > Caddyfile
  cat "$latest/docker-compose.yml" > docker-compose.yml
  docker compose up -d --no-deps --force-recreate caddy'
ZONE_ID="$(td_py -m td.route53 zone-id "$TD_DOMAIN")"
if [[ "$(td_py -m td.route53 state "$ZONE_ID" "dash.$TD_DOMAIN." "$TD_LIGHTSAIL_IP")" == same ]]; then
  td_py -m td.route53 delete-a "$ZONE_ID" "dash.$TD_DOMAIN." "$TD_LIGHTSAIL_IP"
fi
td_log "teardown 완료"
