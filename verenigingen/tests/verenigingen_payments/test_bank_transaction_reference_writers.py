"""Every writer that mints a system-issued Bank Transaction reference marks it (#1349).

The reference key is derived from `custom_reference_is_system_issued`, which the WRITER sets
(see `bank_transaction_reference_key.py`). A writer that forgets leaves its rows unconstrained,
quietly: a real duplicate is then accepted instead of refused. So each Mollie writer below is
driven through its own flow against a real Bank Account, and the row it wrote is read back from
the database: the flag is set, a key exists, and a second row with the same reference on the
same account is refused by the database.

Only the lookup of the Mollie bank-account CONFIGURATION is stubbed (this site has no Mollie
settings); the writer, the creator and the insert are all real. The e-Boekhouden writers are in
`tests/e_boekhouden/test_eboekhouden_reference_flag_1349.py`; the importer that must NOT mark
its rows (MT940) is in `tests/payment/test_mt940_import_reference_collision.py`.
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
from verenigingen.tests.utils.system_issued_reference_assertions import SystemIssuedReferenceAssertions
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import BulkTransactionImporter
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor
from verenigingen.verenigingen_payments.mollie.services.payment_processors import DonationPaymentProcessor
from verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified import (
    UnifiedWebhookWrapperService,
)
from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import build_reversal_key
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
    customer_for_member,
)
from verenigingen.verenigingen_payments.services.balance_transaction_processor import (
    BalanceTransactionProcessor,
)
from verenigingen.verenigingen_payments.services.bank_transaction_creator import BankTransactionCreator
from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    FIELDNAME,
    SYSTEM_ISSUED_FIELDNAME,
)


class TestMollieBankTransactionWritersMarkTheirReferences(
    SystemIssuedReferenceAssertions, _BankTxnFixtureMixin, EnhancedTestCase
):
    def setUp(self):
        super().setUp()
        self.company = COMPANY
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

    def test_create_from_mollie_payment(self):
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = SimpleNamespace(
            id=payment_id, amount={"value": "12.00", "currency": "EUR"}, paid_at=None, description="x"
        )
        bt = self.creator.create_from_mollie_payment(payment, self.bank_account, COMPANY)
        self._assert_written_as_system_issued(bt, payment_id)

    def test_create_from_settlement(self):
        settlement_id = f"stl_{frappe.generate_hash(length=10)}"
        bt = self.creator.create_from_settlement(
            SimpleNamespace(id=settlement_id),
            self.bank_account,
            COMPANY,
            settlement_amount=250.0,
            settlement_date=today(),
            currency="EUR",
            description="Mollie settlement payout",
        )
        self._assert_written_as_system_issued(bt, settlement_id)

    def test_balance_transaction_processor(self):
        balance_transaction_id = f"baltr_{frappe.generate_hash(length=10)}"
        amount = SimpleNamespace(decimal_value="30.00", currency="EUR")
        transaction = SimpleNamespace(
            id=balance_transaction_id,
            type="payment",
            context={},
            result_amount=amount,
            initial_amount=amount,
            created_at=None,
            get_total_deductions=lambda: 0,
        )
        result = BalanceTransactionProcessor()._process_single_transaction(transaction)
        self.assertEqual(result["status"], "success", result)
        self._assert_written_as_system_issued(result["bank_transaction"], balance_transaction_id)

    def test_dues_payment_processor(self):
        member = self.create_test_member(first_name="Dues", last_name="Writer", email="dues.1349@example.com")
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = SimpleNamespace(
            id=payment_id, amount={"value": "15.00", "currency": "EUR"}, paid_at=None, description="dues"
        )
        # create_test_member links a Customer through the member's own flow, as production does.
        customer_for_member(member)
        bt = DuesPaymentProcessor()._create_bank_transaction_for_dues(member.name, payment)
        self._assert_written_as_system_issued(bt, payment_id)

    def test_donation_payment_processor(self):
        member = self.create_test_member(first_name="Don", last_name="Writer", email="don.1349@example.com")
        customer = customer_for_member(member)
        donor = self.create_test_donor(donor_email="don.donor.1349@example.com")
        frappe.db.set_value("Donor", donor.name, "customer", customer)
        donation = self.create_test_donation(donor=donor.name, amount=15.0, paid=0)
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        bt = DonationPaymentProcessor()._create_bank_transaction_for_donation(
            donation, {"payment_id": payment_id, "amount": "15.00", "paid_at": None}
        )
        self._assert_written_as_system_issued(bt, payment_id)

    def test_bulk_importer_payment(self):
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        payment = {
            "id": payment_id,
            "amount": {"value": "20.00", "currency": "EUR"},
            "status": "paid",
            "method": "ideal",
            "description": "bulk payment",
        }
        importer = BulkTransactionImporter()
        doc = importer._create_bank_transaction_from_payment(
            payment, frappe.utils.now_datetime(), COMPANY, self.bank_account
        )
        self._assert_written_as_system_issued(doc.name if doc else None, payment_id)

    def test_bulk_importer_settlement(self):
        settlement_id = f"stl_{frappe.generate_hash(length=10)}"
        settlement = {
            "id": settlement_id,
            "reference": "1234567.2611.01",
            "amount": {"value": "75.00", "currency": "EUR"},
        }
        importer = BulkTransactionImporter()
        doc = importer._create_bank_transaction_from_settlement(
            settlement, frappe.utils.now_datetime(), COMPANY, self.bank_account
        )
        self._assert_written_as_system_issued(doc.name if doc else None, settlement_id)

    def test_mollie_reversal_writer(self):
        # The refund/chargeback webhook writer (donation and dues routes share it). Its reference
        # is `build_reversal_key(...)`, the webhook's idempotency key, so a concurrent duplicate
        # delivery must be refused by the database (#1267), whatever the key's shape.
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        reversal_id = f"re_{frappe.generate_hash(length=10)}"
        reference = build_reversal_key(payment_id, "refund", reversal_id)
        bt = UnifiedWebhookWrapperService()._create_reversal_bank_transaction_and_journal_entry(
            self.creator,
            {"bank_account": self.bank_account, "company": COMPANY},
            "SUBJECT-1349",
            lambda bank_transaction_name: "JE-STUB-1349",
            payment_id,
            "refund",
            reversal_id,
            7.5,
            reference,
            today(),
            "EUR",
            None,
            None,
            None,
        )
        self.assertEqual(bt, ("Journal Entry", "JE-STUB-1349"))
        bt_name = frappe.db.get_value("Bank Transaction", {"reference_number": reference}, "name")
        self._assert_written_as_system_issued(bt_name, reference)

    def test_manual_entry_is_not_marked(self):
        # Control: a writer of a caller-supplied reference (manual entry, bank_integration,
        # member_management) goes through create_from_dict WITHOUT the flag.
        reference = f"EB-{frappe.generate_hash(length=8)}"
        bt = self.creator.create_from_dict(
            {"date": today(), "amount": 5.0, "reference_number": reference, "description": "manual"},
            self.bank_account,
            COMPANY,
        )
        row = frappe.db.get_value("Bank Transaction", bt, [SYSTEM_ISSUED_FIELDNAME, FIELDNAME], as_dict=True)
        self.assertEqual(row[SYSTEM_ISSUED_FIELDNAME], 0)
        self.assertIsNone(row[FIELDNAME])
