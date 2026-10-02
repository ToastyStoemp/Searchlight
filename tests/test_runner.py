from datetime import datetime

from searchlight.__main__ import seconds_until_active
from searchlight.store import Store


def test_active_hours():
    at = lambda h, m=0: datetime(2026, 10, 2, h, m)
    assert seconds_until_active((7, 23), at(12)) == 0
    assert seconds_until_active((7, 23), at(6, 30)) == 30 * 60
    assert seconds_until_active((7, 23), at(23, 0)) == 8 * 3600
    assert seconds_until_active((22, 6), at(2)) == 0  # window across midnight
    assert seconds_until_active((0, 0), at(3)) == 0


def test_block_backoff_doubles_and_resets(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    import time
    t0 = time.time()
    first = store.record_block("ricardo", 2) - t0
    second = store.record_block("ricardo", 2) - t0
    assert 2 * 3600 - 5 < first < 2 * 3600 + 5
    assert 4 * 3600 - 5 < second < 4 * 3600 + 5
    for _ in range(10):
        capped = store.record_block("ricardo", 2) - t0
    assert capped < 24 * 3600 + 5
    store.record_success("ricardo")
    assert store.blocked_until("ricardo") == 0
