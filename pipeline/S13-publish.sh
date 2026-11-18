#!/usr/bin/env bash
# S13 publish: run 사이트를 S3(원본)에 올리고 인덱스를 재생성한 뒤 CloudFront 무효화와 Lightsail 미러를 한다.
#   S13-publish.sh <sut> <runId> [--force-unlock <attemptId>]
# 접두: TD_SITE_PREFIX(운영은 비움, 테스트는 _test/<sessionId>/). 잠금·업로드·인덱스·무효화가 모두 이 접두로 한정된다.
# 상태: S3나 인덱스 실패 failed, CloudFront나 Lightsail만 실패하면 degraded. 최종 결과는 stages/S13.json과
#       suts/<sut>/publish-log/<runId>.json(둘이 같다). 게시된 run.json은 로컬과 같고 S13은 publishing이다.
# 시간 제한: S3 1800초, rsync 1800초, SSH 120초(td.publish 내부). SIGINT/SIGTERM은 잠금을 풀고 failed로 마감한다.
# 강제 종료(SIGKILL)로 남은 잠금은 다음 실행이 안내 문구와 비-0으로 알려 주며 --force-unlock으로 푼다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

SUT="${1:?usage: S13-publish.sh <sut> <runId> [--force-unlock <attemptId>]}"
RUN_ID="${2:?runId}"
shift 2
FORCE_ATTEMPT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force-unlock) FORCE_ATTEMPT="${2:?--force-unlock <attemptId>}"; shift 2 ;;
    *) td_log "알 수 없는 인자: $1"; exit 2 ;;
  esac
done

# 잠금 해제는 단계가 아니다: run 상태를 건드리지 않고 잠금만 처리한다.
if [[ -n "$FORCE_ATTEMPT" ]]; then
  td_py -m td.publish force-unlock --attempt "$FORCE_ATTEMPT"
  exit $?
fi

td_stage_begin S13 || exit 1
td_hook S13
: "${TD_RUN_DIR:?}"

# 신호는 td.publish(파이썬)가 받아 잠금을 풀고 단계를 마감한다. 같은 프로세스 그룹이면 이 스크립트에도 전달되지만
# bash는 전경 자식이 끝난 뒤에 처리하므로 먼저 빠져나가지 않는다.
td_py -m td.publish run --sut "$SUT" --run-id "$RUN_ID" --run-dir "$TD_RUN_DIR"
rc=$?
# 파이썬이 마감하지 못하고 죽었으면(예: 인터프리터 오류) 단계를 failed로 기록한다.
current="$(td_py -c "import sys;from td.state import stage_status;print(stage_status(sys.argv[1],'S13') or '')" "$TD_RUN_DIR" 2>/dev/null)"
if [[ "$current" == "running" || -z "$current" ]]; then
  td_stage_end S13 failed "td.publish exited $rc without recording a result" || true
  [[ $rc -ne 0 ]] || rc=1
fi
exit $rc
