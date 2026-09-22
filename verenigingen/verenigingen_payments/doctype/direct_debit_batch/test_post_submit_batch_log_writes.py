"""
Regression coverage for #1230.

`DirectDebitBatch.add_to_batch_log()` (via `BatchLoggingUtilities.
add_to_document_batch_log`) only mutates `self.batch_log` in memory -- it
never persists. Two callers rely on a subsequent write to make the entry
stick, and neither does it safely on an already-submitted (docstatus=1)
document, because `batch_log` carries no `allow_on_submit` in
`direct_debit_batch.json`:

* `process_batch()` (~line 498) mutates `self.batch_log` then calls
  `self.save()`. On a submitted doc, `validate_update_after_submit` raises
  "Not allowed to change Batch Log after submission" -- so `process_batch()`
  ALWAYS throws for a submitted batch (the only kind `process_batch()` is
  ever called on: the module-level `process_batch()` API rejects
  `docstatus != 1` before calling it), and `self.status = "Submitted"` never
  reaches the DB either, because the same failed `save()` also drops it.
* `on_cancel()` (~line 479) mutates `self.batch_log` and `self.status`, but
  is invoked BY the submit/cancel machinery itself, after `db_update()` has
  already run (`run_post_save_methods` calls `on_cancel` post-write) -- so
  there is no second `.save()` to raise on, and the in-memory mutations are
  silently lost: no exception, no "Batch cancelled" note, no
  `status="Cancelled"` in the DB.

Review round 2 (skeptical review of the first fix): `db_set()` bypasses
Select validation entirely, so the first fix silently wrote `status =
"Cancelled"`, a value `direct_debit_batch.json`'s `status` field never
declared as a valid Select option. Before that fix, this value never reached
the DB at all (that was the silent no-op above), so the fix is what made the
illegal write real for the first time -- and the FIRST version of
`test_on_cancel_persists_cancelled_status_and_log` below asserted exactly
that illegal value as correct, which would have locked it in as "tested
behaviour" forever. Fixed by adding `Cancelled` to the field's declared
options (`direct_debit_batch.json`, one line) and adding
`test_status_writes_are_valid_select_options` below, which reads the
allowed values from the doctype's own meta rather than hardcoding them, so
it would catch the next db_set() of an undeclared value regardless of what
that value is.

Run:
  cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_2 run-tests \
    --app verenigingen --module verenigingen.verenigingen_payments.doctype.direct_debit_batch.test_post_submit_batch_log_writes
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_configuration import apply_sepa_test_configuration


class TestPostSubmitBatchLogWrites(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        # Needed for on_submit()'s own generate_sepa_xml() call to succeed --
        # otherwise the default "_Test Company" name/underscore fails SEPA XML
        # validation before either method under test runs (see
        # sepa_test_configuration's own docstring for why this exists).
        apply_sepa_test_configuration()
        self._sepa = SEPATestDataFactory(seed=123099, use_faker=True)

    def _make_submitted_batch(self):
        batch = self._sepa.create_test_direct_debit_batch(invoice_count=1)
        batch.submit()
        batch.reload()
        return batch

    def test_process_batch_persists_status_and_log_on_a_submitted_batch(self):
        """The core defect: process_batch() must not raise on its own
        self.save(), and its status/batch_log writes must actually land in
        the DB, not just the in-memory object."""
        batch = self._make_submitted_batch()
        if not batch.sepa_file_generated:
            batch.generate_sepa_xml()
            batch.reload()

        batch.process_batch()  # must NOT raise "Not allowed to change Batch Log"

        batch.reload()
        self.assertEqual(
            batch.status,
            "Submitted",
            "process_batch() must persist status='Submitted' to the DB, not just set it in memory.",
        )
        self.assertIn(
            "Batch submitted for processing",
            batch.batch_log or "",
            "process_batch()'s batch_log note must be persisted to the DB.",
        )

    def test_on_cancel_persists_cancelled_status_and_log(self):
        """on_cancel()'s in-memory mutations of status/batch_log must reach
        the DB -- today they are silently dropped because on_cancel() runs
        after db_update() with no second save() to persist them."""
        batch = self._make_submitted_batch()

        batch.cancel()

        batch.reload()
        self.assertEqual(batch.docstatus, 2)
        self.assertEqual(
            batch.status,
            "Cancelled",
            "on_cancel() must persist status='Cancelled' to the DB.",
        )
        self.assertIn(
            "Batch cancelled",
            batch.batch_log or "",
            "on_cancel()'s batch_log note must be persisted to the DB.",
        )

    def test_status_writes_are_valid_select_options(self):
        """The reviewer's finding on round 1: db_set() bypasses Select
        validation, so a persisted status value can silently be one the
        field's own DocType JSON never declared. Read the allowed values
        from the doctype's own meta (not hardcoded) so this generalises to
        the next db_set()'d value, whatever it is -- not just "Cancelled"."""
        allowed = set((frappe.get_meta("Direct Debit Batch").get_field("status").options or "").split("\n"))
        self.assertIn(
            "Cancelled",
            allowed,
            "This test's own premise: 'Cancelled' must be a declared option, or "
            "on_cancel() persisting it is the same illegal-value bug being tested for.",
        )

        batch = self._make_submitted_batch()
        batch.cancel()
        batch.reload()

        self.assertIn(
            batch.status,
            allowed,
            f"on_cancel() persisted status={batch.status!r}, which is not one of "
            f"this doctype's own declared Select options {sorted(allowed)}. db_set() "
            "bypasses Select validation, so an illegal value here writes silently "
            "-- and Frappe's own _validate_selects() raises for ANY later save() "
            "of a document carrying it (verified empirically on test_site_2: "
            "status='Cancelled' before the JSON fix raised "
            "'Status cannot be \"Cancelled\". It should be one of ...' from "
            "doc._validate_selects() directly), so an illegal value here is not "
            "just cosmetic -- it can make the document unsaveable by any future "
            "code path that reaches ordinary Select validation.",
        )
