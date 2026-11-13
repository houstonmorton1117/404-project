# Load test for the shared connection pool - Obi Achebe 11/12/26
# Skipped unless LOAD_TEST_URL is set, so it never runs in normal pytest.

import os
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

BASE = os.getenv("LOAD_TEST_URL")
REQUESTS = int(os.getenv("LOAD_TEST_REQUESTS", 100))
CONCURRENCY = int(os.getenv("LOAD_TEST_CONCURRENCY", 10))

pytestmark = pytest.mark.skipif(
    not BASE, reason="set LOAD_TEST_URL to run the load test"
)


def _hit(path):
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as r:
            status = r.status
    except Exception:
        status = 0
    return status, time.perf_counter() - start


def _run(path):
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        return list(ex.map(lambda _: _hit(path), range(REQUESTS)))


def _report(name, results):
    times = sorted(t for _, t in results)
    ok = sum(1 for s, _ in results if s == 200)
    p95 = times[int(len(times) * 0.95) - 1]
    print(
        f"\n{name}: {ok}/{len(results)} ok | "
        f"median {statistics.median(times):.3f}s | p95 {p95:.3f}s"
    )
    return ok, p95


def test_health_under_load():
    ok, p95 = _report("/health", _run("/health"))
    assert ok == REQUESTS
    assert p95 < 2.0


def test_storefronts_under_load():
    ok, p95 = _report("/api/storefronts", _run("/api/storefronts"))
    assert ok == REQUESTS
    assert p95 < 3.0
