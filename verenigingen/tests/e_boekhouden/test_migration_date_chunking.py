"""
Coverage tests for verenigingen/utils/migration/migration_date_chunking.py

The DateRangeChunker splits a date range into chunks that respect an API record
limit. Everything tested here is pure/computational - no eBoekhouden HTTP. We
drive the chunker with in-memory fetch/process callables so the adaptive and
single-chunk paths run for real against deterministic data.

Run with:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_date_chunking
"""

import unittest

from frappe.utils import add_days, date_diff, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.migration.migration_date_chunking import (
    DateRangeChunker,
    process_with_date_chunks,
)


class TestDateRangeChunkerCalculate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chunker = DateRangeChunker(api_limit=500, safety_margin=0.9)

    def test_effective_limit_applies_safety_margin(self):
        self.assertEqual(self.chunker.effective_limit, 450)

    def test_chunks_cover_entire_range_without_gaps_or_overlap(self):
        from_date = getdate("2024-01-01")
        to_date = getdate("2024-03-31")
        with self.assertNoErrorLog():
            chunks = self.chunker.calculate_optimal_chunks(from_date, to_date)

        # First chunk starts at from_date, last ends at to_date.
        self.assertEqual(chunks[0]["from_date"], from_date)
        self.assertEqual(chunks[-1]["to_date"], to_date)

        # No gaps: each chunk starts the day after the previous one ends.
        for prev, nxt in zip(chunks, chunks[1:]):
            self.assertEqual(nxt["from_date"], add_days(prev["to_date"], 1))
            # No overlap / inversion.
            self.assertLessEqual(prev["from_date"], prev["to_date"])

    def test_high_volume_produces_more_chunks_than_low_volume(self):
        from_date = getdate("2024-01-01")
        to_date = getdate("2024-12-31")
        low = self.chunker.calculate_optimal_chunks(from_date, to_date, estimated_records_per_day=1)
        high = self.chunker.calculate_optimal_chunks(from_date, to_date, estimated_records_per_day=100)
        self.assertGreater(len(high), len(low))

    def test_single_day_range_returns_one_chunk(self):
        d = getdate("2024-06-15")
        chunks = self.chunker.calculate_optimal_chunks(d, d)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["from_date"], d)
        self.assertEqual(chunks[0]["to_date"], d)


class TestDateRangeChunkerSplits(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.chunker = DateRangeChunker()

    def test_split_by_month_spans_calendar_months(self):
        chunks = self.chunker.split_by_month("2024-01-15", "2024-03-10")
        # Jan (from the 15th), Feb (full), Mar (to the 10th).
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["from_date"], getdate("2024-01-15"))
        self.assertEqual(chunks[0]["to_date"], getdate("2024-01-31"))
        self.assertEqual(chunks[1]["from_date"], getdate("2024-02-01"))
        self.assertEqual(chunks[1]["to_date"], getdate("2024-02-29"))  # leap year
        self.assertEqual(chunks[2]["to_date"], getdate("2024-03-10"))
        # Human label present.
        self.assertEqual(chunks[0]["label"], "January 2024")

    def test_split_by_month_crosses_year_boundary(self):
        chunks = self.chunker.split_by_month("2023-12-01", "2024-01-31")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["to_date"], getdate("2023-12-31"))
        self.assertEqual(chunks[1]["from_date"], getdate("2024-01-01"))

    def test_estimate_optimal_strategy_single_request_for_low_volume(self):
        # Sample returns 3 records over a 7-day sample window -> tiny volume.
        def sample_fetch(from_date, to_date):
            return {"invoices": [{}, {}, {}]}

        result = self.chunker.estimate_optimal_strategy("2024-01-01", "2024-01-31", sample_fetch)
        self.assertEqual(result["recommended_strategy"], "single_request")
        self.assertEqual(result["chunks_needed"], 1)
        self.assertIn(result["confidence"], ("low", "medium", "high"))

    def test_estimate_optimal_strategy_daily_for_high_volume(self):
        # ~70 records/day sample -> daily strategy.
        def sample_fetch(from_date, to_date):
            days = date_diff(getdate(to_date), getdate(from_date)) + 1
            return {"invoices": [{}] * (70 * days)}

        result = self.chunker.estimate_optimal_strategy("2024-01-01", "2024-12-31", sample_fetch)
        self.assertEqual(result["recommended_strategy"], "daily")

    def test_estimate_optimal_strategy_handles_fetch_exception(self):
        def boom(from_date, to_date):
            raise RuntimeError("sample fetch failed")

        # The estimator catches the error and returns a safe weekly fallback.
        result = self.chunker.estimate_optimal_strategy("2024-01-01", "2024-02-01", boom)
        self.assertEqual(result["recommended_strategy"], "weekly")
        self.assertEqual(result["confidence"], "low")
        self.assertIn("error", result)


class TestProcessWithDateChunks(EnhancedTestCase):
    """Exercise the high-level orchestrator with deterministic callables."""

    def _fetch(self, from_date, to_date):
        # One record per day in the chunk.
        days = date_diff(getdate(to_date), getdate(from_date)) + 1
        return {"rows": [{"day": i} for i in range(days)]}

    def _process(self, data):
        return {"processed": len(data["rows"]), "errors": []}

    def test_monthly_strategy_processes_all_records(self):
        with self.assertNoErrorLog():
            results = process_with_date_chunks(
                "2024-01-01", "2024-02-29", self._fetch, self._process, chunk_strategy="monthly"
            )
        # Jan(31) + Feb(29) = 60 records across 2 chunks.
        self.assertEqual(results["chunks_processed"], 2)
        self.assertEqual(results["total_processed"], 60)
        self.assertEqual(results["failed_chunks"], [])

    def test_weekly_strategy_chunk_count(self):
        results = process_with_date_chunks(
            "2024-01-01", "2024-01-21", self._fetch, self._process, chunk_strategy="weekly"
        )
        # 21 days / 7 = exactly 3 weekly chunks.
        self.assertEqual(results["chunks_processed"], 3)
        self.assertEqual(results["total_processed"], 21)

    def test_daily_strategy_one_chunk_per_day(self):
        results = process_with_date_chunks(
            "2024-01-01", "2024-01-05", self._fetch, self._process, chunk_strategy="daily"
        )
        self.assertEqual(results["chunks_processed"], 5)
        self.assertEqual(results["total_processed"], 5)

    def test_fetch_exception_recorded_as_failed_chunk(self):
        def boom(from_date, to_date):
            raise ValueError("api down")

        # Single (unknown strategy) chunk that raises -> recorded as a failure,
        # not propagated. _process_single_chunk only logs via frappe.logger() (no
        # Error Log row is written), so the guard stays clean.
        with self.assertNoErrorLog():
            results = process_with_date_chunks(
                "2024-01-01", "2024-01-03", boom, self._process, chunk_strategy="single"
            )
        self.assertEqual(results["chunks_processed"], 1)
        self.assertEqual(results["total_processed"], 0)
        self.assertEqual(len(results["failed_chunks"]), 1)
        self.assertEqual(results["failed_chunks"][0]["reason"], "exception")

    def test_limit_exceeded_marks_chunk_failed(self):
        # Fetch returns >= api_limit records for a single chunk -> limit_exceeded.
        def flood(from_date, to_date):
            return {"rows": [{} for _ in range(600)]}

        results = process_with_date_chunks(
            "2024-01-01", "2024-01-01", flood, self._process, chunk_strategy="single", api_limit=500
        )
        self.assertEqual(len(results["failed_chunks"]), 1)
        self.assertEqual(results["failed_chunks"][0]["reason"], "limit_exceeded")

    def test_adaptive_strategy_processes_full_range(self):
        with self.assertNoErrorLog():
            results = process_with_date_chunks(
                "2024-01-01", "2024-01-28", self._fetch, self._process, chunk_strategy="adaptive"
            )
        # Adaptive resizes chunks but must still process every day exactly once.
        self.assertEqual(results["total_processed"], 28)
        self.assertEqual(results["failed_chunks"], [])


if __name__ == "__main__":
    unittest.main()
