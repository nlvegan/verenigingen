"""The backfill patch's duplicate detection and its refusal to proceed (#809, #746).

#746 is what a quiet decline costs: the patch logged a warning, returned normally, was
recorded as executed, and the guarantee stayed absent for months. These tests pin the two
properties that prevent a repeat -- the detector SEES a duplicate, and the abort RAISES
while naming it.

They exercise the detector and the abort directly rather than calling `execute()`. DDL
autocommits, so a test that ran the whole patch would leave a column and a unique index
behind after the transaction rolled back -- the orphan state that Frappe's schema sync
later drops silently, which is the very failure mode this issue exists to avoid creating.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.patches.v2_2 import add_mollie_payment_entry_idempotency_key as patch
from verenigingen.verenigingen_payments.utils import mollie_idempotency_key as key_module
from verenigingen.verenigingen_payments.utils.mollie_idempotency_key import build_idempotency_key


class TestMollieIdempotencyBackfill(EnhancedTestCase):
    def _seed(self, name, reference_no, payment_type="Receive", party="PROBE-PARTY", docstatus=1):
        frappe.db.sql(
            """INSERT INTO `tabPayment Entry`
               (name, creation, modified, owner, modified_by, docstatus,
                reference_no, payment_type, party)
               VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', %s, %s, %s, %s)""",
            (name, docstatus, reference_no, payment_type, party),
        )
        self.addCleanup(frappe.db.sql, "DELETE FROM `tabPayment Entry` WHERE name = %s", name)

    def test_detector_finds_a_mollie_duplicate(self):
        reference_no = f"tr_{frappe.generate_hash()[:10]}"
        self._seed("TEST-809-DUP-A", reference_no)
        self._seed("TEST-809-DUP-B", reference_no)

        groups = {d.reference_no: d.count for d in patch._find_duplicates()}
        self.assertEqual(groups.get(reference_no), 2)

    def test_detector_counts_a_cancelled_row(self):
        # A unique index has no docstatus predicate, so a cancelled Payment Entry still
        # occupies the key. migration_duplicate_detection.py cancels a duplicate and only
        # deletes it when it has no GL Entries, so "one cancelled, one submitted" is the
        # common shape -- a detector that filtered docstatus would call this resolved and
        # then fail on the CREATE UNIQUE INDEX.
        reference_no = f"tr_{frappe.generate_hash()[:10]}"
        self._seed("TEST-809-CANC-A", reference_no, docstatus=1)
        self._seed("TEST-809-CANC-B", reference_no, docstatus=2)

        groups = {d.reference_no: d.count for d in patch._find_duplicates()}
        self.assertEqual(groups.get(reference_no), 2)

    def test_detector_ignores_a_repeated_non_mollie_reference(self):
        # 221 groups of these on veg11 -- legitimate reuse of invoice and payroll batch
        # references. If this test fails the scope has widened and the patch will refuse
        # to run on any real site.
        reference_no = f"nlvf-standfacturen-{frappe.generate_hash()[:6]}"
        self._seed("TEST-809-OK-A", reference_no)
        self._seed("TEST-809-OK-B", reference_no)

        self.assertNotIn(reference_no, {d.reference_no for d in patch._find_duplicates()})

    def test_abort_raises_and_names_the_offending_group(self):
        duplicates = [
            frappe._dict(reference_no="tr_deadbeef", payment_type="Receive", party="CUST-0001", count=42)
        ]
        # _abort_on_duplicates logs before it raises; declare it so the harness's
        # "errors logged during test" guard does not treat it as an unexpected error.
        # expectErrorLog marks patterns for that check -- it is not a context manager.
        self.expectErrorLog("Mollie idempotency key: duplicates block unique index")
        with self.assertRaises(frappe.ValidationError) as caught:
            patch._abort_on_duplicates(duplicates)

        message = str(caught.exception)
        self.assertIn("tr_deadbeef", message)
        self.assertIn("x42", message)
        # It must say what to do next: this patch stays unrecorded and retries, which is
        # the whole difference from #746's silent success.
        self.assertIn("bench migrate", message)

    def test_patch_and_hook_derive_the_key_with_the_same_function(self):
        # The patch and the before_save hook must derive the SAME key, or a backfilled row
        # and a freshly saved one would occupy two different slots for one payment. This
        # asserts identity, not equality on a sample: a re-implementation inside the patch
        # would pass any corpus test the day it was written and drift afterwards.
        self.assertIs(patch.build_idempotency_key, key_module.build_idempotency_key)
        self.assertIs(
            key_module.set_payment_entry_idempotency_key.__globals__["build_idempotency_key"],
            key_module.build_idempotency_key,
        )
