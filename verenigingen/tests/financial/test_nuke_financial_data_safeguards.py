#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safeguard tests for the destructive financial-data utilities in
verenigingen/utils/nuke_financial_data.py

``nuke_all_financial_data`` is a whitelisted @critical_api(ADMIN) endpoint that
permanently deletes every financial transaction for the company. Actually
running the deletion is out of scope for a unit suite (it is destructive by
design), but the ONE invariant we must never regress is its confirmation guard:

    a wrong / missing ``confirm`` value must return the safety-check error and
    perform NO destructive action whatsoever.

Design notes (why these tests look the way they do):

* We exercise the RAW function (``nuke_all_financial_data.__wrapped__``), i.e.
  the guard as written, NOT the decorated HTTP entrypoint. The @critical_api
  input sanitizer strips surrounding whitespace, so a padded token like
  " YES_DELETE_ALL_FINANCIAL_DATA " reaches the body as the exact token and
  legitimately passes the guard. Testing the raw body isolates the guard's
  exact-match contract from that orthogonal (and harmless) sanitization.

* Every call runs with ``frappe.db`` fully replaced by a MagicMock, plus
  ``get_doc``/``delete_doc``/``clear_cache`` patched out. This makes the tests
  destruction-proof: even if a regression broke the guard, the deletion body
  would hit the mock, never a real database. A broken guard is then caught by
  ``mock_db.sql.assert_not_called()`` on the reject path rather than by wiping
  data.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.financial.test_nuke_financial_data_safeguards
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import nuke_financial_data
from verenigingen.utils.nuke_financial_data import nuke_all_financial_data, nuke_gl_entries_older_than

# The accepted confirmation tokens, one per destructive function. Duplicated
# here on purpose: if someone changes a token in the source, this test should
# force a conscious update.
VALID_CONFIRM = "YES_DELETE_ALL_FINANCIAL_DATA"
VALID_CONFIRM_GL = "YES_DELETE_GL_ENTRIES"


def _fully_unwrap(fn):
    """Peel every decorator layer down to the pure guard body.

    A single ``__wrapped__`` only removes the outermost wrapper, which still
    includes the @critical_api input sanitizer (it strips surrounding
    whitespace). We want the raw exact-match guard, so unwind all the way.
    """
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


# The raw, undecorated guard bodies — exact-match, no input sanitization.
_raw_nuke = _fully_unwrap(nuke_all_financial_data)
_raw_nuke_gl = _fully_unwrap(nuke_gl_entries_older_than)

# Values the exact-match guard must reject. Covers the default, empty, case and
# whitespace near-misses, and truncation.
REJECTED_CONFIRMS = [
    "NO",
    "",
    "no",
    "yes_delete_all_financial_data",  # wrong case
    " YES_DELETE_ALL_FINANCIAL_DATA ",  # padded (raw guard does NOT strip)
    "YES_DELETE_ALL_FINANCIAL_DAT",  # truncated
    "YES",
]


@contextmanager
def _destruction_proof_db():
    """
    Replace the whole destructive surface with mocks and yield the db mock.

    All COUNT(*) queries return 0 and all row-list queries (as_dict=True) return
    [], so if execution ever reaches the deletion body it is a harmless no-op
    against the mock — never the real database.
    """
    mock_db = MagicMock()

    def _sql(*_args, **kwargs):
        return [] if kwargs.get("as_dict") else [[0]]

    mock_db.sql.side_effect = _sql

    with patch.object(nuke_financial_data.frappe, "db", mock_db), patch.object(
        nuke_financial_data.frappe, "get_doc"
    ), patch.object(nuke_financial_data.frappe, "delete_doc"), patch.object(
        nuke_financial_data.frappe, "clear_cache"
    ):
        yield mock_db


class TestNukeFinancialDataSafeguards(EnhancedTestCase):
    """The confirmation guard must block every non-exact confirm value."""

    def test_rejected_confirms_return_safety_error_and_touch_nothing(self):
        """Every non-exact confirm returns the safety error and runs no DB op."""
        for confirm in REJECTED_CONFIRMS:
            with self.subTest(confirm=repr(confirm)):
                with _destruction_proof_db() as mock_db:
                    result = _raw_nuke(confirm=confirm)

                self.assertIsInstance(result, dict)
                self.assertEqual(result.get("error"), "Safety check failed")
                # Must NOT look like a successful run.
                self.assertNotIn("success", result)
                self.assertNotIn("deleted", result)
                # The strong invariant: the guard returned before any DB access.
                mock_db.sql.assert_not_called()

    def test_default_confirm_is_safe(self):
        """Calling with no confirm argument (default) must not proceed."""
        with _destruction_proof_db() as mock_db:
            result = _raw_nuke()

        self.assertEqual(result.get("error"), "Safety check failed")
        mock_db.sql.assert_not_called()

    def test_exact_token_passes_guard(self):
        """
        Positive control / guard-boundary check.

        The exact token must be ACCEPTED by the guard: execution proceeds into
        the (fully mocked) deletion body, so the return is NOT the safety-check
        error and the db mock IS exercised. This proves the ``assert_not_called``
        checks above are meaningful — the mock can be reached, and only the guard
        keeps the reject paths away from it.
        """
        with _destruction_proof_db() as mock_db:
            result = _raw_nuke(confirm=VALID_CONFIRM)

        self.assertNotEqual(result.get("error"), "Safety check failed")
        self.assertTrue(mock_db.sql.called)


class TestNukeGLEntriesSafeguards(EnhancedTestCase):
    """`nuke_gl_entries_older_than` must also refuse to run without its token.

    This function is the more dangerous of the two: no per-entry token existed
    before, and a mistaken small ``minutes`` deletes essentially all GL entries.
    """

    # Every value here must be rejected — including VALID_CONFIRM, the OTHER
    # function's token, which must not unlock this one.
    REJECTED = REJECTED_CONFIRMS + [VALID_CONFIRM]

    def test_rejected_confirms_return_safety_error_and_touch_nothing(self):
        for confirm in self.REJECTED:
            with self.subTest(confirm=repr(confirm)):
                with _destruction_proof_db() as mock_db:
                    result = _raw_nuke_gl(minutes=0, confirm=confirm)

                self.assertEqual(result.get("error"), "Safety check failed")
                self.assertNotIn("success", result)
                self.assertNotIn("deleted", result)
                mock_db.sql.assert_not_called()

    def test_default_confirm_is_safe(self):
        """Default call (and the risky minutes=0) must not proceed."""
        with _destruction_proof_db() as mock_db:
            result = _raw_nuke_gl(minutes=0)

        self.assertEqual(result.get("error"), "Safety check failed")
        mock_db.sql.assert_not_called()

    def test_exact_token_passes_guard(self):
        """Positive control: the exact GL token proceeds into the mocked body."""
        with _destruction_proof_db() as mock_db:
            result = _raw_nuke_gl(minutes=30, confirm=VALID_CONFIRM_GL)

        self.assertNotEqual(result.get("error"), "Safety check failed")
        self.assertTrue(mock_db.sql.called)
