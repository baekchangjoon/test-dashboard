#!/usr/bin/env bash
# S00 스텁(테스트 전용). 실제 단계와 같은 td_stage_begin/td_hook/td_stage_end API를 쓴다.
source "$TD_ROOT/pipeline/lib/common.sh"
td_stage_begin S00
td_hook S00
td_stage_end S00 passed
