"""#1873: board-seat lookups must not outlive the seat.

``get_user_chapter_memberships_cached`` / ``get_user_treasurer_chapters_cached`` used to be
process-wide ``lru_cache``s keyed by (user, 5-minute bucket): no site in the key, and the
only invalidation lived in Chapter Board Member's own controller hooks, which Frappe does
not run when the row is saved as part of its parent Chapter.
"""

import frappe

from verenigingen.permissions import (
    get_cache_key,
    get_user_chapter_memberships_cached,
    get_user_treasurer_chapters_cached,
)
from verenigingen.tests.security.test_permissions_coverage import PermissionsCoverageBase


class TestBoardSeatCache(PermissionsCoverageBase):
    def _seat_chapters(self, fn):
        return fn(self.board_user.name, get_cache_key())

    def test_revoking_seat_through_chapter_save_is_seen_immediately(self):
        for fn in (get_user_chapter_memberships_cached, get_user_treasurer_chapters_cached):
            self.assertIn(self.chapter_a.name, self._seat_chapters(fn))  # primes the cache

        chapter = frappe.get_doc("Chapter", self.chapter_a.name)
        for row in chapter.board_members:
            if row.name == self.board_position.name:
                row.is_active = 0
        chapter.save()

        for fn in (get_user_chapter_memberships_cached, get_user_treasurer_chapters_cached):
            self.assertNotIn(self.chapter_a.name, self._seat_chapters(fn), fn.__name__)

    def test_cache_does_not_survive_a_request_boundary(self):
        """Probe shortcut: a raw ``db.set_value`` stands in for ANOTHER worker revoking the
        seat (its hooks cannot reach this process), and ``frappe.local.cache = {}`` stands
        in for the per-request reset Frappe performs in ``frappe.init``."""
        for fn in (get_user_chapter_memberships_cached, get_user_treasurer_chapters_cached):
            self.assertIn(self.chapter_a.name, self._seat_chapters(fn))

        frappe.db.set_value("Chapter Board Member", self.board_position.name, "is_active", 0)
        frappe.local.cache = {}  # Mock justified: execution-context reset, what frappe.init does per request

        for fn in (get_user_chapter_memberships_cached, get_user_treasurer_chapters_cached):
            self.assertNotIn(self.chapter_a.name, self._seat_chapters(fn), fn.__name__)

    def test_repeat_reads_in_one_request_cost_one_query(self):
        """Counts real SELECTs via the server's own Com_select counter (no patching)."""

        def selects():
            return int(frappe.db.sql("SHOW SESSION STATUS LIKE 'Com_select'")[0][1])

        frappe.local.cache = {}  # Mock justified: execution-context reset, what frappe.init does per request
        before = selects()
        for _ in range(5):
            self._seat_chapters(get_user_chapter_memberships_cached)
        self.assertEqual(selects() - before, 1)
