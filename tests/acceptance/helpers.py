"""수용 테스트 공용 helper(conftest와 테스트에서 import)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def claude_call_log(run_dir) -> list[dict]:
    """shim이 `<run_dir>/llm-calls.jsonl`에 남긴 호출 기록을 읽는다."""
    log_file = Path(run_dir) / "llm-calls.jsonl"
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text().splitlines() if line]


def docker_ids(*args: str) -> frozenset[str]:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.fail(f"docker CLI를 쓸 수 없다: {type(exc).__name__}", pytrace=False)
    if result.returncode != 0:
        pytest.fail(f"docker {' '.join(args)} 실패: {result.stderr.strip()[:200]}", pytrace=False)
    return frozenset(line for line in result.stdout.split() if line)


def find_leaked_resources(label_value: str) -> dict[str, list[str]]:
    """`test-run=<label_value>` 라벨이 붙은 컨테이너·네트워크·볼륨 ID를 종류별로 돌려준다(없으면 빈 dict)."""
    flt = f"label=test-run={label_value}"
    found = {
        "containers": docker_ids("ps", "-aq", "--filter", flt),
        "networks": docker_ids("network", "ls", "-q", "--filter", flt),
        "volumes": docker_ids("volume", "ls", "-q", "--filter", flt),
    }
    return {kind: sorted(ids) for kind, ids in found.items() if ids}
