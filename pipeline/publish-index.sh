#!/usr/bin/env bash
# 인덱스 전용 게시(설계 §6.4): 파이프라인 run 없이 과제 수집과 인덱스(홈, projects.json, 과제 페이지)만 갱신한다.
#   publish-index.sh
# 접두: TD_SITE_PREFIX(운영은 비움, 테스트는 _test/<sessionId>/). 설정: TD_DASHBOARD_CONFIG(없으면 접두 실행은 빈 설정,
#       운영은 저장소 루트 dashboard.yaml). S13과 같은 접두 S3 잠금과 미러 잠금을 잡고, 잡혀 있으면 기다리지 않고 실패한다.
# 순서: 잠금 → 미러 동기화 → 수집(pipeline/collect.sh) → 설정에 없거나 공개가 아닌 과제 삭제 → 재생성 → 업로드
#       → 무효화(/<접두>projects/* 묶음) → Lightsail 삭제와 인덱스 rsync → <접두>publish-log/index.json.
# 종료 코드: 상태가 failed일 때만 1(수집 문제·CloudFront·Lightsail 실패는 degraded이고 0).
# 신호: 게시기(파이썬)가 직접 받도록 exec한다. 받으면 수집 자식에 넘겨 토큰 정리를 기다리고 잠금을 푼 뒤 failed로 끝난다.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

export PYTHONPATH="$TD_ROOT/site-gen${PYTHONPATH:+:$PYTHONPATH}"
venv_python="$TD_ROOT/site-gen/.venv/bin/python"
if [[ -x "$venv_python" ]]; then
  exec "$venv_python" -m td.publish index-only
fi
exec uv run --project "$TD_ROOT/site-gen" --quiet python -m td.publish index-only
