"""#2694: the bulk importer's "already imported" check must be scoped like #2620's.

``reference_number`` is unique per bank account only (#1267), and a cancelled Bank Transaction
is not an import. The importer skipped a real import when ANOTHER bank account's row, or a
CANCELLED row, carried the Mollie payment/settlement id.

The amount/date/reference filter is deliberately NOT account-scoped (it is what matches the
orchestrator's rows, which carry the payment id only as ``reference_number`` on the Mollie
account), and neither is the settlement-id check.

Rows are seeded directly (the importer's own writer is what is under test, not the seed).
"""

from datetime import datetime, timezone
from unittest.mock import patch

import frappe

from verenigingen.tests.payment.test_bulk_transaction_importer_sweep import (
    _BulkImporterSweepBase,
    _payment,
    _StubPaymentsClient,
    _StubSettlementsClient,
)
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import BulkTransactionImporter
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    get_bank_transaction_creator,
)
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

    def _seed_bt_2694(
        self, bank_account, mollie_id, field="custom_mollie_payment_id", cancel=False, date=None
    ):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date or frappe.utils.today()
        bt.bank_account = bank_account
        bt.company = self.company
        bt.currency = "EUR"
        bt.deposit = 25.0
        bt.reference_number = mollie_id
        if field:
            setattr(bt, field, mollie_id)
        bt.insert()
        self.created_records.append(("Bank Transaction", bt.name))
        bt.submit()
        if cancel:
            bt.cancel()
        return bt

    def _run_payment_import_2694(self, payment_id, bank_account="default"):
        self.imp.payments_client = _StubPaymentsClient([_payment(payment_id, value="25.00")])
        return self.imp.import_transactions(
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
            "payments",
            self.company,
            self.bank_account if bank_account == "default" else bank_account,
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
        with patch.object(
            type(get_bank_transaction_creator()), "get_mollie_bank_account_config"
        ) as mollie_config:
            # No account given: the target resolves from the company alone (#2694 F5).
            self.assertFalse(self.imp._validate_duplicate_transaction(data))
            sid_live = f"stl_dupscope_live_{self.uid}"
            self._seed_bt_2694(self.bank_account, sid_live, field="custom_mollie_settlement_id")
            self.assertTrue(
                self.imp._validate_duplicate_transaction({"custom_mollie_settlement_id": sid_live})
            )
        mollie_config.assert_not_called()

    def test_settlement_id_on_another_account_still_skips(self):
        """Control (decision recorded in #2694): the settlement-id check is NOT account-scoped,
        as in #2620. A settlement-scoped mutant reddens this."""
        sid = f"stl_dupscope_other_{self.uid}"
        self._seed_bt_2694(self._decoy_bank_account_2694(), sid, field="custom_mollie_settlement_id")
        self.assertTrue(
            self.imp._validate_duplicate_transaction(
                {"custom_mollie_settlement_id": sid},
                bank_account=self.bank_account,
                company=self.company,
            )
        )

    def test_amount_date_reference_check_is_not_account_scoped(self):
        """Decision (#2694): the orchestrator and webhook write ``reference_number = payment_id``
        on the Mollie account with NO custom_mollie_payment_id, so this filter is the only
        thing that matches them. Scoping it would import one payment onto a second account."""
        pid = f"tr_dupscope_amt_{self.uid}"
        data = {"deposit": 25.0, "date": frappe.utils.getdate(), "reference_number": pid}
        kw = {"bank_account": self.bank_account, "company": self.company}
        self.assertFalse(self.imp._validate_duplicate_transaction(data, **kw))
        self._seed_bt_2694(self._decoy_bank_account_2694(), pid, field=None)
        self.assertTrue(self.imp._validate_duplicate_transaction(data, **kw))

    def test_orchestrator_style_row_on_another_account_still_skips_the_import(self):
        pid = f"tr_dupscope_orch_{self.uid}"
        # reference_number only, on the "Mollie" account; payment day per _payment().
        self._seed_bt_2694(self._decoy_bank_account_2694(), pid, field=None, date="2024-03-15")
        tx = self._run_payment_import_2694(pid)
        self.assertEqual((tx["payments_imported"], tx["duplicates_skipped"]), (0, 1))

    def test_no_account_import_is_scoped_to_the_writers_account(self):
        """With no bank_account the row lands on the company's default account, not on the
        Mollie config account. A re-run must skip it (F1: scoping to the Mollie account
        imported it again and reported it)."""
        pid = f"tr_dupscope_noacct_{self.uid}"
        first = self._run_payment_import_2694(pid, bank_account=None)
        self.assertEqual(first["payments_imported"], 1)
        decoy = self._decoy_bank_account_2694()
        with patch.object(
            type(get_bank_transaction_creator()),
            "get_mollie_bank_account_config",
            return_value={"bank_account": decoy, "company": self.company},
        ) as mollie_config:
            # A fresh importer: the re-run of a later job, not a cache of the first one's.
            self.imp = BulkTransactionImporter()
            self.imp.settlements_client = _StubSettlementsClient([])
            again = self._run_payment_import_2694(pid, bank_account=None)
        self.assertEqual((again["payments_imported"], again["duplicates_skipped"]), (0, 1))
        mollie_config.assert_not_called()

    def test_check_existing_payment_is_scoped_to_the_account(self):
        pid = f"tr_dupscope_exists_{self.uid}"
        self._seed_bt_2694(self._decoy_bank_account_2694(), pid, cancel=False)
        kw = {"bank_account": self.bank_account, "company": self.company}
        self.assertFalse(self.imp._check_existing_payment_transaction({"id": pid}, **kw))
        self._seed_bt_2694(self.bank_account, pid)
        self.assertTrue(self.imp._check_existing_payment_transaction({"id": pid}, **kw))
