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

    def _set_seat_active_via_chapter_save(self, active):
        chapter = frappe.get_doc("Chapter", self.chapter_a.name)
        for row in chapter.board_members:
            if row.name == self.board_position.name:
                row.is_active = active
        chapter.save()

    def test_revoking_seat_through_chapter_save_is_seen_immediately(self):
        """The SECOND revoke is the discriminating one. The first Chapter.save() creates the
        board user's Employee stub, whose insert calls ``frappe.clear_cache()`` and wipes
        ``frappe.local.cache`` as a side effect, which would hide a missing invalidation.
        Once the Employee exists, only an explicit invalidation can keep the memo honest."""
        self._set_seat_active_via_chapter_save(0)  # first revoke: creates the Employee
        self._set_seat_active_via_chapter_save(1)  # re-grant
        for fn in (get_user_chapter_memberships_cached, get_user_treasurer_chapters_cached):
            self.assertIn(self.chapter_a.name, self._seat_chapters(fn))  # primes the memo

        self._set_seat_active_via_chapter_save(0)  # second revoke: no Employee wipe

        for fn in (get_user_chapter_memberships_cached, get_user_treasurer_chapters_cached):
            self.assertNotIn(self.chapter_a.name, self._seat_chapters(fn), fn.__name__)

    def test_a_failed_lookup_is_neither_swallowed_nor_memoised(self):
        """A real DB error (a list as the user renders ``m.user = 'a', 'b'``, a syntax error)
        must raise, and must leave nothing in the memo that could read as "no seats"."""
        frappe.local.cache = {}  # Mock justified: execution-context reset, what frappe.init does per request
        bad_user = ["a@example.com", "b@example.com"]
        with self.assertRaises(Exception):
            get_user_chapter_memberships_cached(bad_user)
        self.assertEqual(frappe.local.cache.get("verenigingen_board_seat_lookups", {}), {})
        self.assertIn(self.chapter_a.name, self._seat_chapters(get_user_chapter_memberships_cached))

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
