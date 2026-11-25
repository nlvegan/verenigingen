"""A cancelled Bank Transaction frees its #1267 unique reference key (#2626, #2608).

`custom_reference_number_key` is set only in `validate`, which a cancel never runs, so a
cancelled row kept the key and a rebooking of the same Mollie reference died on
IntegrityError 1062. Maintainer ruling 2026-11-25: a cancelled row frees the key, for every
creator (donation, dues, settlement).

Each creator below is driven through the real BankTransactionCreator against a real Bank
Account (only the Mollie bank-account CONFIG lookup is stubbed, as in
test_bank_transaction_reference_writers). The control tests pin that an ACTIVE duplicate is
still refused: the fix must narrow the guard to non-cancelled rows, not remove it.
"""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_bank_transaction_creator_coverage import (
    COMPANY,
    _BankTxnFixtureMixin,
)
from verenigingen.verenigingen_payments.services.bank_transaction_creator import BankTransactionCreator
from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    FIELDNAME,
    SYSTEM_ISSUED_FIELDNAME,
)


class TestCancelledBankTransactionFreesItsKey(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)
        self.creator = BankTransactionCreator()
        config = {"bank_account": self.bank_account, "company": COMPANY}
        patcher = patch.object(BankTransactionCreator, "get_mollie_bank_account_config", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _make_submitted(self, reference_number, system_issued=True):
        doc = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": today(),
                "bank_account": self.bank_account,
                "company": COMPANY,
                "deposit": 10.0,
                "withdrawal": 0.0,
                "currency": "EUR",
                "reference_number": reference_number,
                "description": "PROBE 2626",
                "status": "Unreconciled",
                "unallocated_amount": 10.0,
                "allocated_amount": 0.0,
                SYSTEM_ISSUED_FIELDNAME: 1 if system_issued else 0,
            }
        )
        doc.insert(ignore_permissions=True)
        doc.submit()
        return doc

    def _key(self, name):
        return frappe.db.get_value("Bank Transaction", name, FIELDNAME)

    def _cancel(self, name):
        frappe.get_doc("Bank Transaction", name).cancel()
        self.assertEqual(frappe.db.get_value("Bank Transaction", name, "docstatus"), 2)

    def test_cancel_clears_the_key_and_the_reference_can_be_booked_again(self):
        ref = f"SYSREF-{self._ref('cancel')}"
        first = self._make_submitted(ref)
        self.assertIsNotNone(self._key(first.name), "fixture problem: no key before the cancel")

        self._cancel(first.name)

        self.assertIsNone(self._key(first.name), "a cancelled Bank Transaction still holds its key")
        second = self._make_submitted(ref)
        self.assertNotEqual(second.name, first.name)
        self.assertIsNotNone(self._key(second.name))

    def test_an_active_duplicate_is_still_refused_beside_a_cancelled_row(self):
        # Control with a real candidate: a cancelled row AND a live row share the reference.
        ref = f"SYSREF-{self._ref('control')}"
        cancelled = self._make_submitted(ref)
        self._cancel(cancelled.name)
        self._make_submitted(ref)

        with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
            self._make_submitted(ref)

    def test_cancelling_one_row_does_not_release_a_different_rows_key(self):
        keep = self._make_submitted(f"SYSREF-{self._ref('keep')}")
        drop = self._make_submitted(f"SYSREF-{self._ref('drop')}")
        self._cancel(drop.name)
        self.assertIsNotNone(self._key(keep.name))

    def test_settlement_creator_rebooks_after_a_cancel(self):
        settlement_id = f"stl_{frappe.generate_hash(length=10)}"

        def create():
            return self.creator.create_from_settlement(
                SimpleNamespace(id=settlement_id),
                self.bank_account,
                COMPANY,
                settlement_amount=250.0,
                settlement_date=today(),
                currency="EUR",
                description="Mollie settlement payout",
            )

        first = create()
        self.assertTrue(first, "fixture problem: settlement BT not created")
        self._cancel(first)
        second = create()
        self.assertTrue(second, "the settlement could not be booked again after a cancel")
        self.assertNotEqual(second, first)

    def test_payment_creator_rebooks_after_a_cancel(self):
        # Covers the donation and dues creators: both write through create_from_mollie_payment.
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = SimpleNamespace(
            id=payment_id, amount={"value": "12.00", "currency": "EUR"}, paid_at=None, description="x"
        )
        first = self.creator.create_from_mollie_payment(payment, self.bank_account, COMPANY)
        self.assertTrue(first, "fixture problem: payment BT not created")
        self._cancel(first)
        second = self.creator.create_from_mollie_payment(payment, self.bank_account, COMPANY)
        self.assertTrue(second, "the payment could not be booked again after a cancel")
        self.assertNotEqual(second, first)

    def test_the_patch_releases_keys_held_by_rows_cancelled_before_the_fix(self):
        from verenigingen.patches.v2_2.release_cancelled_bank_transaction_reference_keys_2626 import execute

        ref = f"SYSREF-{self._ref('patch')}"
        old_cancelled = self._make_submitted(ref)
        live = self._make_submitted(f"SYSREF-{self._ref('patchlive')}")
        # Probe shortcut: reproduce a row cancelled BEFORE the hook existed (cancel, then put
        # the key back), since the real cancel flow now releases it.
        self._cancel(old_cancelled.name)
        frappe.db.set_value("Bank Transaction", old_cancelled.name, FIELDNAME, "x" * 64)

        execute()

        self.assertIsNone(self._key(old_cancelled.name))
        self.assertIsNotNone(self._key(live.name), "the patch released a LIVE row's key")
