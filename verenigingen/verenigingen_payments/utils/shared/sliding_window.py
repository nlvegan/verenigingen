"""Sliding-window counter backed by a deque of timestamps.

Boundary semantics intentionally match ``webhook_rate_limiter.py`` (line 113)::

    while self.global_requests and current_time - self.global_requests[0] > self.time_window:

Entries are pruned when their age is *strictly greater than* ``window_seconds``
(i.e. ``now - timestamp > window_seconds``).  An entry whose age equals the
window boundary is **kept**.

No frappe import — pure Python, fully testable without a running site.
"""

from __future__ import annotations

from collections import deque


class SlidingWindowCounter:
    """Count events that occurred within the last ``window_seconds``."""

    def __init__(self, window_seconds: float) -> None:
        self.window_seconds: float = window_seconds
        self._timestamps: deque[float] = deque()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add(self, timestamp: float) -> None:
        """Append *timestamp* to the window, then prune stale entries."""
        self._timestamps.append(timestamp)
        self.prune(timestamp)

    def count(self, now: float) -> int:
        """Prune entries older than the window and return the live count."""
        self.prune(now)
        return len(self._timestamps)

    def prune(self, now: float) -> None:
        """Remove all entries whose age exceeds ``window_seconds``."""
        while self._timestamps and now - self._timestamps[0] > self.window_seconds:
            self._timestamps.popleft()

    def clear(self) -> None:
        """Discard all entries."""
        self._timestamps.clear()
