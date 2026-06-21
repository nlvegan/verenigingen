# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""
Coverage for ``verenigingen/events/subscribers/subscriber_utils.py``.

These two helpers (``get_doc_if_exists`` and ``should_skip_for_bulk``) are the
shared building blocks every member/chapter/team subscriber relies on, so a
regression here silently breaks the whole event-bus. They are pure-ish, so we
exercise them directly against real records and real ``frappe.flags`` rather
than through a subscriber.
"""

from contextlib import contextmanager

import frappe

from verenigingen.events.subscribers.subscriber_utils import (
    get_doc_if_exists,
    should_skip_for_bulk,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSubscriberUtils(EnhancedTestCase):
    """Direct tests for the shared subscriber helpers."""

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _flags(self, **values):
        """Temporarily set frappe.flags, restoring originals afterwards.

        EnhancedTestCase.setUp forces frappe.flags.in_import = True, which makes
        should_skip_for_bulk() return True unconditionally; we must control these
        flags explicitly to test each branch.
        """
        saved = {k: getattr(frappe.flags, k, None) for k in values}
        for k, v in values.items():
            setattr(frappe.flags, k, v)
        try:
            yield
        finally:
            for k, v in saved.items():
                setattr(frappe.flags, k, v)

    # --------------------------------------------------- get_doc_if_exists
    def test_get_doc_if_exists_returns_real_document(self):
        """An existing record is returned as a live, usable Document object."""
        member = self.create_test_member(first_name="Sub", last_name="Util", birth_date="1990-01-01")
        with self.assertNoErrorLog():
            doc = get_doc_if_exists("Member", member.name, "unit test")
        self.assertIsNotNone(doc)
        # Prove it is the real doc, not a truthy sentinel: a field round-trips.
        self.assertEqual(doc.name, member.name)
        self.assertEqual(doc.doctype, "Member")

    def test_get_doc_if_exists_missing_returns_none(self):
        """A non-existent name returns None (the not-yet-committed branch) and
        only writes a logger().warning, NOT an Error Log row."""
        with self.assertNoErrorLog():
            doc = get_doc_if_exists("Member", "Member-does-not-exist-zzz999", "unit test")
        self.assertIsNone(doc)

    def test_get_doc_if_exists_default_log_prefix(self):
        """Default log_prefix branch is reachable without raising."""
        with self.assertNoErrorLog():
            self.assertIsNone(get_doc_if_exists("Member", "Member-nope-abc123"))

    # --------------------------------------------------- should_skip_for_bulk
    def test_should_skip_for_bulk_explicit_parameter(self):
        """Explicit is_bulk_import=True short-circuits regardless of flags."""
        with self._flags(in_import=False, in_bulk_import=False):
            self.assertTrue(should_skip_for_bulk(is_bulk_import=True))

    def test_should_skip_for_bulk_all_clear_returns_false(self):
        """With every signal cleared the helper must return a real False so
        downstream subscribers actually run."""
        with self._flags(in_import=False, in_bulk_import=False):
            self.assertFalse(should_skip_for_bulk())
            self.assertFalse(should_skip_for_bulk(is_bulk_import=False))

    def test_should_skip_for_bulk_in_import_flag(self):
        """frappe.flags.in_import alone triggers the skip (backwards compat)."""
        with self._flags(in_import=True, in_bulk_import=False):
            self.assertTrue(should_skip_for_bulk(is_bulk_import=False))

    def test_should_skip_for_bulk_in_bulk_import_flag(self):
        """frappe.flags.in_bulk_import alone triggers the skip."""
        with self._flags(in_import=False, in_bulk_import=True):
            self.assertTrue(should_skip_for_bulk(is_bulk_import=False))

    def test_should_skip_for_bulk_returns_truthy_not_none(self):
        """Guard against a regression that returns None (falsy) instead of True:
        the result must be usable as a real boolean by `if should_skip(...)`."""
        with self._flags(in_import=True, in_bulk_import=False):
            result = should_skip_for_bulk(is_bulk_import=False)
        self.assertIs(bool(result), True)
