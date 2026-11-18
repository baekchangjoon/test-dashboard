#!/usr/bin/env bash
# apply.sh의 되돌리기: "대시보드 적용 전 원본" 백업으로 Caddyfile·compose를 바이트 그대로 복원하고 caddy만 재생성한 뒤
# Sonar가 UP인지 확인하고, dash A 레코드를 삭제한다. /srv/dashboard 디렉터리는 데이터 보존을 위해 남긴다.
# 원본 = .td-backup/original-pre-dashboard, 없으면(이 보존 규칙 이전에 적용한 서버) 가장 오래된 타임스탬프 백업.
# 최신 백업이 아니라 가장 오래된/원본을 쓰는 것은 의도다: 최신은 이미 dash가 들어간 설정일 수 있다.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/pipeline/lib/common.sh"
set -a; source "$TD_ROOT/infra/local.env"; set +a
export AWS_REGION="${AWS_REGION:-ap-northeast-2}"

SSH_OPTS=(-i "$TD_SSH_KEY_PATH" -o BatchMode=yes -o ConnectTimeout=20 -o LogLevel=ERROR)
td_run 300 -- ssh "${SSH_OPTS[@]}" "ubuntu@$TD_LIGHTSAIL_IP" 'set -e
  cd ~/sonarqube
  original=".td-backup/original-pre-dashboard"
  [ -d "$original" ] || original="$(ls -1d .td-backup/2* 2>/dev/null | sort | head -1)"
  if [ -z "$original" ] || [ ! -f "$original/Caddyfile" ] || [ ! -f "$original/docker-compose.yml" ]; then
    echo "원본 백업을 찾지 못했다: 복원하지 않는다" >&2; exit 1
  fi
  echo "복원 원본: $original" >&2
  cat "$original/Caddyfile" > Caddyfile
  cat "$original/docker-compose.yml" > docker-compose.yml
  docker compose up -d --no-deps --force-recreate caddy
  for i in $(seq 1 24); do
    curl -fsS --max-time 10 "https://sonar.'"$TD_DOMAIN"'/api/system/status" | grep -q "\"status\":\"UP\"" && exit 0
    sleep 5
  done
  echo "복원 후 sonar가 UP이 아니다" >&2; exit 1'
ZONE_ID="$(td_py -m td.route53 zone-id "$TD_DOMAIN")"
if [[ "$(td_py -m td.route53 state "$ZONE_ID" "dash.$TD_DOMAIN." "$TD_LIGHTSAIL_IP")" == same ]]; then
  td_py -m td.route53 delete-a "$ZONE_ID" "dash.$TD_DOMAIN." "$TD_LIGHTSAIL_IP"
fi
td_log "teardown 완료"
