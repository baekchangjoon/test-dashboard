#!/usr/bin/env bash
# 정적 호스팅 인프라 적용(Route53 안전장치 포함).
#   local.env 로드 -> before 스냅샷 -> 충돌 검사 -> terraform apply -> after 스냅샷 -> 허용 밖 변경 비교
# 파일: work/infra/route53-{before,after}.json, 상태: work/infra/terraform.tfstate(gitignore)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/pipeline/lib/common.sh"

TF="${TD_TERRAFORM:-/opt/homebrew/bin/terraform}"
STATIC_DIR="$TD_ROOT/infra/static"
INFRA_WORK="$TD_WORK_DIR/infra"
STATE="$INFRA_WORK/terraform.tfstate"
mkdir -p "$INFRA_WORK"

set -a; source "$TD_ROOT/infra/local.env"; set +a
export TF_VAR_account_id="$TD_AWS_ACCOUNT_ID" TF_VAR_domain="$TD_DOMAIN"
export AWS_REGION="${AWS_REGION:-ap-northeast-2}"

td_run 600 -- "$TF" -chdir="$STATIC_DIR" init -input=false -lockfile=readonly >/dev/null

ZONE_ID="$(td_py -m td.route53 zone-id "$TD_DOMAIN")"

# 최초 before는 보존하고, 재실행이면 타임스탬프 파일을 따로 둔다.
BEFORE="$INFRA_WORK/route53-before.json"
[[ -e "$BEFORE" ]] && BEFORE="$INFRA_WORK/route53-before.$(date -u +%Y%m%dT%H%M%SZ).json"
td_py -m td.route53 snapshot "$ZONE_ID" "$BEFORE"
td_log "before 스냅샷: $BEFORE"

# 이전 적용분이면 우리 CloudFront 도메인을 기대 대상으로 넘긴다.
EXPECTED=()
if [[ -s "$STATE" ]]; then
  CURRENT_DOMAIN="$("$TF" -chdir="$STATIC_DIR" output -state="$STATE" -raw distribution_domain 2>/dev/null || true)"
  [[ -z "$CURRENT_DOMAIN" ]] || EXPECTED=(--expected-target "$CURRENT_DOMAIN")
fi
td_py -m td.route53 check "$ZONE_ID" reports ${EXPECTED[@]+"${EXPECTED[@]}"} \
  || { td_log "reports가 이미 다른 대상으로 있다: 적용 중단"; exit 4; }

td_run 1800 -- "$TF" -chdir="$STATIC_DIR" apply -input=false -auto-approve -state="$STATE" -lock-timeout=60s

BUCKET="$("$TF" -chdir="$STATIC_DIR" output -state="$STATE" -raw bucket)"
td_py "$STATIC_DIR/placeholder.py" "$BUCKET"

AFTER="$INFRA_WORK/route53-after.json"
td_py -m td.route53 snapshot "$ZONE_ID" "$AFTER"
# 비교 기준은 최초 before다(재실행 시에도 처음 상태 대비 허용 밖 변경이 없어야 한다).
td_py -m td.route53 compare "$INFRA_WORK/route53-before.json" "$AFTER" \
  --allow "reports.$TD_DOMAIN." --allow "_*.reports.$TD_DOMAIN." \
  || { td_log "허용 밖 Route53 변경 발견"; exit 5; }
td_log "완료: bucket=$BUCKET (Route53은 reports와 ACM 검증 CNAME만 변경됨)"
