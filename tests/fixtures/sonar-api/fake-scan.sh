#!/usr/bin/env bash
# 단계 수준 테스트용 가짜 스캐너: 실제 분석 없이 report-task.txt만 쓴다(cwd = SUT 소스).
set -e
mkdir -p build/sonar
cp "$(cd "$(dirname "$0")" && pwd)/report-task.txt" build/sonar/report-task.txt
