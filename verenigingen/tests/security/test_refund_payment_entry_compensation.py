"""
Tests for #863: a failed refund Payment Entry submit leaves docstatus=1, uncompensated
========================================================================================

`verenigingen/api/payment_processing.py::process_application_refund` creates a refund
Payment Entry and submits it via `secure_document_operation(operation="submit", ...)`.
Per #385/#864 (`SecureOperationResult.partial_write` / `.persisted_docstatus`),
`success=False` on a failed submit does NOT mean nothing happened: `Document.save()`
writes `db_update()` (flipping docstatus to 1) BEFORE `run_post_save_methods()` invokes
`on_submit`, so a Payment Entry whose `on_submit` (GL posting) raises has already
persisted docstatus=1 -- exactly the Journal Entry shape #385 was filed for, one
doctype over.

Unlike the three Mollie Journal Entry creators, there was no `discard_unposted_*`
helper for Payment Entry before this fix. `discard_unposted_refund_payment_entry`
(added alongside this test) cancels the stranded entry so it stops existing at
docstatus=1 with no compensating ledger action.

Cancelling turns out to have the SAME write-before-hook ordering as submitting: a
raising `on_cancel` does not, by itself, mean the cancel changed nothing --
`Document._cancel()` also writes `docstatus=2` via `db_update()` before running
`on_cancel`. So "cancel() raised" and "docstatus is still 1" are two different
facts, and only a DB re-read (not the exception) can tell them apart. Four things
are verified here, each with real ERPNext validation (no mocking):

* ``test_submit_against_group_account_reports_partial_write`` -- the PREMISE.
  A refund Payment Entry whose ``paid_to`` is a Group Account passes `insert()`
  (no group-account check in `PaymentEntry.validate()`) but fails `submit()`
  inside `on_submit`'s `make_gl_entries()`, exactly like the Journal Entry case:
  `GLEntry.on_update` validates *after* `db_insert()`. Confirms
  `persisted_docstatus == 1` and `partial_write is True` despite `success=False`,
  and that an invalid GL Entry was actually left behind.
* ``test_discard_cancels_a_cleanly_submittable_entry`` -- the common case:
  nothing wrong with the entry's own accounts, so the compensating cancel
  succeeds outright.
* ``test_discard_cancels_even_when_cancel_itself_raises`` -- the entry from the
  first test (paid_to is a Group Account) is fed to the discard helper:
  `cancel()` calls `make_gl_entries(cancel=1)`, which tries to post a reversal
  against the very same Group Account and raises identically -- BUT docstatus
  still ends up at 2, because that write already landed before `on_cancel` ran.
  The helper must report this as a successful compensation, not a stuck one.
* ``test_discard_reports_manual_reconciliation_when_cancel_cannot_even_run`` --
  the genuine stuck case: a real file-based document lock (`check_if_locked()`,
  which runs before any write) blocks `cancel()` entirely, so docstatus truly
  stays at 1 and the response says a human is needed.

See verenigingen/api/payment_processing.py and issue #863.
"""

import frappe
from frappe.utils import today

from verenigingen.api.payment_processing import (
    _compensate_failed_refund_submit,
    discard_unposted_refund_payment_entry,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.secure_operations import secure_document_operation


class TestRefundPaymentEntryCompensation(EnhancedTestCase):
    """Discriminate a partial refund-submit write from a clean submit failure, and
    verify the #863 compensation path for each."""

    def setUp(self):
        super().setUp()
        self.company = self._get_test_company()
        self.customer = self.factory.create_test_customer().name
        self.receivable_account = self._get_or_create_receivable_account(self.company)
        # The Group Account parent of the receivable account: posting a GL Entry
        # against it is rejected by GLEntry.validate_account_details, called from
        # GLEntry.on_update, which fires AFTER the Payment Entry's own docstatus
        # has already been written to the DB by db_update() -- the same ordering
        # #385 documented for Journal Entry.
        self.group_receivable_account = frappe.db.get_value(
            "Account", self.receivable_account, "parent_account"
        )
        self.assertTrue(
            self.group_receivable_account,
            "Test company's receivable account has no group parent -- CoA not initialized as expected",
        )
        self.bank_account = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Bank", "is_group": 0}, "name"
        )
        if not self.bank_account:
            self.bank_account = frappe.db.get_value(
                "Account", {"company": self.company, "account_type": "Cash", "is_group": 0}, "name"
            )
        self.assertTrue(self.bank_account, "Test company has no usable Bank/Cash account")

    def _make_refund_pe(self, paid_to):
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Pay",
                "company": self.company,
                "party_type": "Customer",
                "party": self.customer,
                "paid_from": self.bank_account,
                "paid_to": paid_to,
                "paid_amount": 10,
                "received_amount": 10,
                "reference_no": f"TEST-REFUND-{frappe.generate_hash()[:8]}",
                "reference_date": today(),
                "remarks": "test #863 refund compensation",
            }
        )
        pe.insert()
        self.track_doc("Payment Entry", pe.name)
        return pe

    def test_submit_against_group_account_reports_partial_write(self):
        pe = self._make_refund_pe(self.group_receivable_account)
        self.assertEqual(pe.docstatus, 0)

        # secure_document_operation itself logs an Error Log on the failure this
        # test deliberately provokes -- expected, not a swallowed error.
        self.expectErrorLog("Secure Operation Failed: submit on Payment Entry")
        result = secure_document_operation(
            operation="submit",
            doc=pe,
            justification="test #863 partial-write reproduction",
        )

        self.assertFalse(result.success, "submit against a group account must fail")

        # The discriminating assertion: docstatus was already flipped to 1 in the
        # DB before the group-account row's on_update threw.
        self.assertEqual(
            result.persisted_docstatus,
            1,
            "docstatus must already be persisted as 1 -- db_update() runs before on_submit",
        )
        self.assertTrue(
            result.partial_write,
            "result must flag that a write landed despite success=False",
        )

        # And the ledger itself was left holding an invalid posting: the GL row
        # for the group-account side is inserted (and validated, and rejected)
        # only after being written -- see GLEntry.on_update.
        gl_rows = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Payment Entry", "voucher_no": pe.name},
            fields=["account"],
        )
        self.assertTrue(
            any(row.account == self.group_receivable_account for row in gl_rows),
            f"expected an (invalid) GL Entry against the group account, got: {gl_rows}",
        )

    def test_discard_cancels_a_cleanly_submittable_entry(self):
        """The common case: nothing wrong with the entry's own accounts, so the
        compensating cancel succeeds and frees the entry for a retry."""
        pe = self._make_refund_pe(self.receivable_account)
        pe.submit()
        self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 1)

        self.expectErrorLog("Refund Payment Entry Not Posted")
        discard_unposted_refund_payment_entry(pe.name, "test-member-clean", "synthetic failure for #863 test")

        self.assertEqual(
            frappe.db.get_value("Payment Entry", pe.name, "docstatus"),
            2,
            "a stranded entry with valid accounts must be cancelled, not left at docstatus=1",
        )

    def test_discard_cancels_even_when_cancel_itself_raises(self):
        """cancel() re-runs make_gl_entries(cancel=1) against the SAME accounts, so
        a bad account fails identically on the way out as it did on the way in --
        BUT `_cancel()` writes docstatus=2 via db_update() before on_cancel runs,
        exactly the write-before-hook ordering #385/#863 are about, one level
        deeper. So a cancel that raises can still leave docstatus=2 behind; this
        is not a bug in the compensation, it just means the entry ends up
        genuinely cancelled despite the exception, and the helper must report
        that truth (read from the DB) rather than treating the exception as
        proof nothing changed."""
        pe = self._make_refund_pe(self.group_receivable_account)

        self.expectErrorLog("Secure Operation Failed: submit on Payment Entry")
        submit_result = secure_document_operation(
            operation="submit",
            doc=pe,
            justification="test #863 cancel-also-raises reproduction",
        )
        self.assertTrue(submit_result.partial_write)
        self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 1)

        self.expectErrorLog("Refund Payment Entry Not Posted")
        response = _compensate_failed_refund_submit(pe, submit_result, "test-member-broken")

        self.assertFalse(response["success"])
        self.assertNotIn(
            "requires_manual_reconciliation",
            response,
            f"cancel() raising is not proof docstatus stayed at 1 -- must re-read the DB: {response}",
        )
        self.assertEqual(
            frappe.db.get_value("Payment Entry", pe.name, "docstatus"),
            2,
            "cancel()'s own db_update() still lands even though on_cancel's GL posting raised again",
        )

    def test_discard_reports_manual_reconciliation_when_cancel_cannot_even_run(self):
        """The genuine 'stuck at docstatus=1' case: something blocks `cancel()`
        before its own db_update() -- here, a real (file-based) document lock
        held by another process, via `check_if_locked()`, which runs before any
        write. Unlike the bad-account case above, nothing is persisted by this
        failed cancel attempt, so docstatus truly stays at 1 and a human is
        needed."""
        pe = self._make_refund_pe(self.group_receivable_account)

        self.expectErrorLog("Secure Operation Failed: submit on Payment Entry")
        submit_result = secure_document_operation(
            operation="submit",
            doc=pe,
            justification="test #863 cancel-cannot-run reproduction",
        )
        self.assertTrue(submit_result.partial_write)
        self.assertEqual(frappe.db.get_value("Payment Entry", pe.name, "docstatus"), 1)

        lock_holder = frappe.get_doc("Payment Entry", pe.name)
        lock_holder.lock()
        try:
            self.expectErrorLog("Refund Payment Entry Not Posted")
            self.expectErrorLog("Refund Payment Entry Still Docstatus=1")
            response = _compensate_failed_refund_submit(pe, submit_result, "test-member-locked")
        finally:
            lock_holder.unlock()

        self.assertFalse(response["success"])
        self.assertTrue(
            response.get("requires_manual_reconciliation"),
            f"a compensation failure must be surfaced, not silently reported as a clean retry: {response}",
        )
        self.assertEqual(
            frappe.db.get_value("Payment Entry", pe.name, "docstatus"),
            1,
            "a cancel blocked before any write must leave docstatus=1, not 2",
        )
