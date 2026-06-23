"""
Coverage tests for verenigingen/utils/migration/migration_performance.py

Exercises the pure performance machinery:
  * CacheManager          - get_or_set hit/miss accounting and stats.
  * ProgressTracker       - start/update/complete (publish_realtime side-effects
                            are harmless; we assert the tracked counters).
  * BatchProcessor        - batch splitting, success/failure tallies, per-batch
                            stats, and parallel processing of in-memory records.
  * MemoryOptimizer       - chunked dataset processing via a query callable.
  * PerformanceOptimizer  - monitoring start/stop and metric calculation.

All callables are in-memory; no eBoekhouden HTTP. BatchProcessor commits to the
DB between batches (no rows created here) and is safe under FrappeTestCase.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_performance
"""

import unittest

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.migration_performance import (
    BatchProcessor,
    CacheManager,
    MemoryOptimizer,
    PerformanceOptimizer,
    ProgressTracker,
)


class TestCacheManager(EnhancedTestCase):
    def test_miss_then_hit(self):
        cache = CacheManager()
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return "value"

        self.assertEqual(cache.get_or_set("k", fetch), "value")  # miss
        self.assertEqual(cache.get_or_set("k", fetch), "value")  # hit
        self.assertEqual(calls["n"], 1)  # fetch only ran once
        stats = cache.get_stats()
        self.assertEqual(stats["cache_hits"], 1)
        self.assertEqual(stats["cache_misses"], 1)
        self.assertEqual(stats["hit_rate"], 50.0)
        self.assertEqual(stats["cache_size"], 1)

    def test_clear_empties_cache(self):
        cache = CacheManager()
        cache.get_or_set("k", lambda: 1)
        cache.clear()
        self.assertEqual(cache.get_stats()["cache_size"], 0)

    def test_stats_with_no_requests(self):
        self.assertEqual(CacheManager().get_stats()["hit_rate"], 0)


class TestProgressTracker(EnhancedTestCase):
    def test_counters_advance(self):
        tracker = ProgressTracker()
        with self.assertNoErrorLog():
            tracker.start(10)
            tracker.update(4)
            tracker.update(6)
            tracker.complete()
        self.assertEqual(tracker.total, 10)
        self.assertEqual(tracker.processed, 10)

    def test_complete_with_zero_total_does_not_divide_by_zero(self):
        tracker = ProgressTracker()
        with self.assertNoErrorLog():
            tracker.start(0)
            tracker.complete()
        self.assertEqual(tracker.processed, 0)


class TestBatchProcessor(EnhancedTestCase):
    def _process_ok(self, record, context=None):
        return {"success": True}

    def test_all_records_processed_in_batches(self):
        processor = BatchProcessor(batch_size=10, parallel_workers=2)
        records = [{"i": i} for i in range(25)]
        with self.assertNoErrorLog():
            results = processor.process_in_batches(records, self._process_ok)
        self.assertEqual(results["successful"], 25)
        self.assertEqual(results["failed"], 0)
        # 25 records / batch_size 10 -> 3 batches.
        self.assertEqual(len(results["batch_stats"]), 3)
        self.assertEqual(results["batch_stats"][0]["size"], 10)
        self.assertEqual(results["batch_stats"][-1]["size"], 5)

    def test_failures_and_errors_are_tallied(self):
        def process(record, context=None):
            if record["i"] % 2 == 0:
                return {"success": False, "error": "even is bad"}
            return {"success": True}

        processor = BatchProcessor(batch_size=5, parallel_workers=2)
        records = [{"i": i} for i in range(10)]
        results = processor.process_in_batches(records, process)
        # 0,2,4,6,8 fail -> 5 failures, 5 successes.
        self.assertEqual(results["failed"], 5)
        self.assertEqual(results["successful"], 5)
        self.assertEqual(len(results["errors"]), 5)

    def test_exception_in_processor_counts_as_failure(self):
        def boom(record, context=None):
            raise RuntimeError("processor exploded")

        processor = BatchProcessor(batch_size=3, parallel_workers=2)
        results = processor.process_in_batches([{"i": 1}, {"i": 2}], boom)
        self.assertEqual(results["failed"], 2)
        self.assertEqual(results["successful"], 0)
        self.assertTrue(all("error" in e for e in results["errors"]))

    def test_empty_records_returns_zero(self):
        processor = BatchProcessor()
        results = processor.process_in_batches([], self._process_ok)
        self.assertEqual(results["successful"], 0)
        self.assertEqual(results["batch_stats"], [])


class TestMemoryOptimizer(EnhancedTestCase):
    def test_process_large_dataset_pages_through_chunks(self):
        # 23 records served in pages of 10 via a limit/offset query callable.
        data = [{"i": i} for i in range(23)]

        def query(limit, offset):
            return data[offset : offset + limit]

        def process(record):
            return {"success": True}

        with self.assertNoErrorLog():
            results = MemoryOptimizer.process_large_dataset(query, process, chunk_size=10)
        self.assertEqual(results["successful"], 23)
        self.assertEqual(results["failed"], 0)

    def test_process_large_dataset_records_failures(self):
        data = [{"i": i} for i in range(5)]

        def query(limit, offset):
            return data[offset : offset + limit]

        def process(record):
            if record["i"] == 3:
                raise ValueError("bad record 3")
            return {"success": True}

        results = MemoryOptimizer.process_large_dataset(query, process, chunk_size=10)
        self.assertEqual(results["successful"], 4)
        self.assertEqual(results["failed"], 1)
        self.assertEqual(len(results["errors"]), 1)

    def test_empty_dataset_breaks_immediately(self):
        results = MemoryOptimizer.process_large_dataset(
            lambda limit, offset: [], lambda r: {"success": True}, chunk_size=10
        )
        self.assertEqual(results["successful"], 0)


class TestPerformanceOptimizer(EnhancedTestCase):
    def test_monitoring_computes_rate(self):
        # Regression: PerformanceOptimizer.start/stop_monitoring delegated to
        # MemoryOptimizer.start/stop_monitoring, which did not exist -> every call
        # raised AttributeError. The optimizer lifecycle must now run cleanly.
        optimizer = PerformanceOptimizer()
        optimizer.start_monitoring()
        self.assertTrue(optimizer.memory_optimizer.monitoring)
        optimizer.metrics["records_processed"] = 100
        metrics = optimizer.stop_monitoring()
        self.assertFalse(optimizer.memory_optimizer.monitoring)
        self.assertIn("elapsed_time", metrics)
        self.assertIn("records_per_second", metrics)
        self.assertGreaterEqual(metrics["records_per_second"], 0)

    def test_get_current_metrics_before_start(self):
        # No start_monitoring() -> metrics dict returned without elapsed time keys.
        optimizer = PerformanceOptimizer()
        metrics = optimizer.get_current_metrics()
        self.assertEqual(metrics["records_processed"], 0)


if __name__ == "__main__":
    unittest.main()
