"""Tests for SlidingWindowCounter.

Boundary semantics match webhook_rate_limiter.py (line 113):
    while deque and current_time - deque[0] > window:
i.e. prune entries where (now - front) > window_seconds.
An entry exactly AT the window boundary (age == window_seconds) is KEPT.
"""

import unittest

from verenigingen.verenigingen_payments.utils.shared.sliding_window import SlidingWindowCounter


class TestSlidingWindowCounterBasic(unittest.TestCase):
    """Basic add/count/prune behaviour."""

    def test_empty_counter_returns_zero(self):
        c = SlidingWindowCounter(window_seconds=2)
        self.assertEqual(c.count(0), 0)

    def test_count_without_pruning(self):
        """All three timestamps within window at now=2."""
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.add(1)
        c.add(2)
        # now=2, window=2 → threshold age = 2; ages are 2,1,0 → 2 is NOT > 2 → all kept
        self.assertEqual(c.count(2), 3)

    def test_count_prunes_oldest(self):
        """At now=3, t=0 has age 3 > 2 → pruned; t=1 age 2 (not > 2) → kept."""
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.add(1)
        c.add(2)
        self.assertEqual(c.count(3), 2)

    def test_count_all_expired(self):
        """At now=5, window=2 → threshold age 2; ages 5,4,3 all > 2 → all pruned."""
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.add(1)
        c.add(2)
        self.assertEqual(c.count(5), 0)

    def test_clear_resets_to_zero(self):
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.add(1)
        c.add(2)
        c.clear()
        self.assertEqual(c.count(5), 0)


class TestSlidingWindowCounterBoundary(unittest.TestCase):
    """Exact boundary behaviour: entry at age == window_seconds is KEPT."""

    def test_entry_exactly_at_boundary_is_kept(self):
        """t=0, window=2, now=2: age=2, NOT > 2 → kept."""
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        self.assertEqual(c.count(2), 1)

    def test_entry_one_tick_past_boundary_is_pruned(self):
        """t=0, window=2, now=2.001: age=2.001 > 2 → pruned."""
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        self.assertEqual(c.count(2.001), 0)

    def test_fractional_window(self):
        """Fractional window_seconds work correctly."""
        c = SlidingWindowCounter(window_seconds=0.5)
        c.add(0.0)
        c.add(0.3)
        # now=0.5: ages 0.5 (not >0.5 → kept) and 0.2 (kept)
        self.assertEqual(c.count(0.5), 2)
        # now=0.51: t=0 age 0.51 > 0.5 → pruned; t=0.3 age 0.21 → kept
        self.assertEqual(c.count(0.51), 1)


class TestSlidingWindowCounterPrune(unittest.TestCase):
    """prune() mutates the deque independently of count()."""

    def test_prune_removes_old_entries(self):
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.add(1)
        c.add(2)
        c.prune(3)
        # After pruning at now=3: t=0 (age 3>2) removed; t=1 (age 2 not>2) kept
        self.assertEqual(c.count(3), 2)

    def test_prune_is_idempotent(self):
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.prune(10)
        c.prune(10)
        self.assertEqual(c.count(10), 0)

    def test_count_calls_prune_internally(self):
        """count() prunes stale entries so subsequent count() reflects removal."""
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.add(1)
        c.add(2)
        _ = c.count(3)  # prunes t=0 (age 3>2); t=1 (age 2, not>2) and t=2 kept
        # Both t=1 and t=2 remain within window at now=3
        self.assertEqual(c.count(3), 2)


class TestSlidingWindowCounterAdd(unittest.TestCase):
    """add() appends and implicitly prunes."""

    def test_add_prunes_old_on_insert(self):
        """add() prunes before appending so the deque stays compact."""
        c = SlidingWindowCounter(window_seconds=2)
        c.add(0)
        c.add(1)
        # add at t=3 — old entry t=0 (age 3>2) pruned during add; t=1 age 2 kept
        c.add(3)
        self.assertEqual(c.count(3), 2)

    def test_add_multiple_same_timestamp(self):
        c = SlidingWindowCounter(window_seconds=5)
        for _ in range(3):
            c.add(1.0)
        self.assertEqual(c.count(1.0), 3)

    def test_window_slides_correctly_over_time(self):
        c = SlidingWindowCounter(window_seconds=60)
        for t in range(10):
            c.add(float(t))
        # now=70: only t in [8,9] within window (ages 62..61 both >60; ages 60 not>60)
        # t=10..69 doesn't exist, t=9 age=61>60 → pruned, t=8 age=62>60 → pruned
        # Actually: age of t=9 at now=70 is 70-9=61 > 60 → pruned
        # All 10 entries pruned at now=70
        self.assertEqual(c.count(70), 0)

    def test_window_slides_keeps_recent(self):
        c = SlidingWindowCounter(window_seconds=60)
        for t in range(10):
            c.add(float(t))
        # now=65: threshold age 60; t=4 age=61>60 pruned; t=5 age=60 not>60 → kept
        # kept: t=5..9 → 5 entries
        self.assertEqual(c.count(65), 5)


class TestSlidingWindowCounterWindowSeconds(unittest.TestCase):
    """window_seconds attribute is accessible."""

    def test_window_seconds_stored(self):
        c = SlidingWindowCounter(window_seconds=30)
        self.assertEqual(c.window_seconds, 30)

    def test_zero_window_prunes_all_past(self):
        """window=0: entries at exactly now are kept (age 0, not > 0)."""
        c = SlidingWindowCounter(window_seconds=0)
        c.add(5.0)
        # at now=5.0, age=0, not >0 → kept
        self.assertEqual(c.count(5.0), 1)
        # at now=5.001, age=0.001 > 0 → pruned
        self.assertEqual(c.count(5.001), 0)
