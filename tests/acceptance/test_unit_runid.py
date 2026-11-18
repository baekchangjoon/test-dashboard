"""REQ-005: 고유 runId (Unit)."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from td import runid

COMMIT = "b6f939355e8790202ddfc71e3f3507252745ed37"
NOW = datetime(2026, 11, 18, 5, 4, 3, tzinfo=timezone.utc)


def test_req005_unique_runid(tmp_path):
    with ThreadPoolExecutor(max_workers=32) as pool:
        ids = list(pool.map(lambda _: runid.new(COMMIT, "manual", tmp_path, now=NOW), range(1000)))
    assert len(set(ids)) == 1000
    assert len(list(tmp_path.iterdir())) == 1000
    pattern = re.compile(r"^\d{8}-\d{6}Z-[0-9a-f]{7}-(manual|pr|merge)-[0-9a-f]{8}$")
    assert all(pattern.match(i) for i in ids)
    assert ids[0].startswith("20261118-050403Z-b6f9393-manual-")


@pytest.mark.parametrize("collisions", [0, 1, 2, 3, 4])
def test_req005_collision_retries_then_succeeds(tmp_path, collisions):
    (tmp_path / "20261118-050403Z-b6f9393-manual-deadbeef").mkdir(exist_ok=True)
    values = iter(["deadbeef"] * collisions + ["cafe0001"])
    run_id = runid.new(COMMIT, "manual", tmp_path, rng=lambda _n: next(values), now=NOW)
    assert run_id.endswith("-cafe0001")
    assert (tmp_path / run_id).is_dir()


def test_req005_fifth_collision_raises(tmp_path):
    (tmp_path / "20261118-050403Z-b6f9393-manual-deadbeef").mkdir()
    calls = []

    def always_same(_n):
        calls.append(1)
        return "deadbeef"

    with pytest.raises(RuntimeError):
        runid.new(COMMIT, "manual", tmp_path, rng=always_same, now=NOW)
    assert len(calls) == 5  # 초기 1회 포함 최대 5회


def test_runid_uses_utc_for_aware_non_utc_now(tmp_path):
    from datetime import timedelta
    kst = timezone(timedelta(hours=9))
    run_id = runid.new(COMMIT, "manual", tmp_path, now=datetime(2026, 11, 18, 14, 4, 3, tzinfo=kst))
    assert run_id.startswith("20261118-050403Z-")


def test_runid_rejects_bad_trigger(tmp_path):
    with pytest.raises(ValueError):
        runid.new(COMMIT, "cron", tmp_path)
