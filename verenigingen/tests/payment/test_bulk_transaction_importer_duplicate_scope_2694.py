"""#2694: the bulk importer's "already imported" check must be scoped like #2620's.

``reference_number`` is unique per bank account only (#1267), and a cancelled Bank Transaction
is not an import. The importer skipped a real import when ANOTHER bank account's row, or a
CANCELLED row, carried the Mollie payment/settlement id.

Rows are seeded directly (the importer's own writer is what is under test, not the seed).
"""

from datetime import datetime, timezone

import frappe

from verenigingen.tests.payment.test_bulk_transaction_importer_sweep import (
    _BulkImporterSweepBase,
    _payment,
    _StubPaymentsClient,
    _StubSettlementsClient,
)
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import BulkTransactionImporter
from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank


class TestBulkImporterDuplicateScope2694(_BulkImporterSweepBase):
    def setUp(self):
        super().setUp()
        self.imp = BulkTransactionImporter()
        self.imp.settlements_client = _StubSettlementsClient([])

    def _decoy_bank_account_2694(self):
        ba = frappe.new_doc("Bank Account")
        ba.account_name = f"Dup Scope Decoy {self.uid}"
        ba.bank = get_or_create_unknown_bank()
        ba.company = self.company
        ba.bank_account_no = f"NL00DUPS{self.uid}"
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))
        return ba.name

    def _seed_bt_2694(self, bank_account, mollie_id, field="custom_mollie_payment_id", cancel=False):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.bank_account = bank_account
        bt.company = self.company
        bt.currency = "EUR"
        bt.deposit = 25.0
        bt.reference_number = mollie_id
        setattr(bt, field, mollie_id)
        bt.insert()
        self.created_records.append(("Bank Transaction", bt.name))
        bt.submit()
        if cancel:
            bt.cancel()
        return bt

    def _run_payment_import_2694(self, payment_id):
        self.imp.payments_client = _StubPaymentsClient([_payment(payment_id, value="25.00")])
        return self.imp.import_transactions(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            "payments",
            self.company,
            self.bank_account,
        )["transactions"]

    def test_another_accounts_row_does_not_skip_the_import(self):
        pid = f"tr_dupscope_other_{self.uid}"
        self._seed_bt_2694(self._decoy_bank_account_2694(), pid)
        tx = self._run_payment_import_2694(pid)
        self.assertEqual((tx["payments_imported"], tx["duplicates_skipped"]), (1, 0))

    def test_a_cancelled_row_does_not_skip_the_import(self):
        pid = f"tr_dupscope_cancelled_{self.uid}"
        self._seed_bt_2694(self.bank_account, pid, cancel=True)
        tx = self._run_payment_import_2694(pid)
        self.assertEqual((tx["payments_imported"], tx["duplicates_skipped"]), (1, 0))

    def test_a_live_row_on_the_target_account_still_skips_the_import(self):
        """Control: the scope must not turn the duplicate check off."""
        pid = f"tr_dupscope_live_{self.uid}"
        self._seed_bt_2694(self.bank_account, pid)
        tx = self._run_payment_import_2694(pid)
        self.assertEqual((tx["payments_imported"], tx["duplicates_skipped"]), (0, 1))

    def test_settlement_id_check_ignores_a_cancelled_row_but_not_a_live_one(self):
        sid = f"stl_dupscope_{self.uid}"
        self._seed_bt_2694(self.bank_account, sid, field="custom_mollie_settlement_id", cancel=True)
        data = {"custom_mollie_settlement_id": sid}
        self.assertFalse(self.imp._validate_duplicate_transaction(data))
        sid_live = f"stl_dupscope_live_{self.uid}"
        self._seed_bt_2694(self.bank_account, sid_live, field="custom_mollie_settlement_id")
        self.assertTrue(
            self.imp._validate_duplicate_transaction({"custom_mollie_settlement_id": sid_live})
        )

    def test_amount_date_reference_check_ignores_another_accounts_row(self):
        pid = f"tr_dupscope_amt_{self.uid}"
        self._seed_bt_2694(self._decoy_bank_account_2694(), pid)
        data = {
            "deposit": 25.0,
            "date": frappe.utils.getdate(),
            "reference_number": pid,
        }
        self.assertFalse(
            self.imp._validate_duplicate_transaction(
                data, bank_account=self.bank_account, company=self.company
            )
        )
        self._seed_bt_2694(self.bank_account, pid)
        self.assertTrue(
            self.imp._validate_duplicate_transaction(
                data, bank_account=self.bank_account, company=self.company
            )
        )

    def test_check_existing_payment_is_scoped_to_the_account(self):
        pid = f"tr_dupscope_exists_{self.uid}"
        self._seed_bt_2694(self._decoy_bank_account_2694(), pid, cancel=False)
        kw = {"bank_account": self.bank_account, "company": self.company}
        self.assertFalse(self.imp._check_existing_payment_transaction({"id": pid}, **kw))
        self._seed_bt_2694(self.bank_account, pid)
        self.assertTrue(self.imp._check_existing_payment_transaction({"id": pid}, **kw))
