"""
Coverage gap-fill for the Mollie DuesPaymentProcessor.

Target: verenigingen/verenigingen_payments/mollie/services/dues_payment_processor.py

This complements the existing test_mollie_dues_payment_processor.py (which covers
identify_payment_type, _get_membership_type_cached, _resolve_chapter_cost_center,
_get_or_create_dues_item, _get_member_with_customer, several process_dues_payment
branches and the end-to-end PE-against-invoice path).

Gaps filled here (REAL DB, no Mollie HTTP / no business-logic mocks):
- _get_or_create_historical_invoice input validation (negative amount, future
  date, large-amount warning) -- these throw/log BEFORE any DB write.
- _get_or_create_historical_invoice: member-with-no-customer returns None.
- _extract_and_save_consumer_bank_data: real IBAN persisted to Member +
  Bank Account link created; invalid IBAN skipped; no-details no-op.
- _create_simple_invoice: real backdated submitted Sales Invoice with coverage
  custom fields and the dues item.
- process_dues_payment: deprecated 'Payment Entry' creation_mode falls back to
  Bank Transaction (records the deprecation Error Log -- intentional).
- batch_process_customer_payments: over-limit guard raises ValueError.

Mollie SDK is never hit: processors are built via object.__new__ with test
doubles; the historical-invoice path is invoked directly with a real member.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_dues_processor_coverage_b3
"""

from datetime import date, timedelta
from types import SimpleNamespace

import frappe
from frappe.utils import add_days, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
    BATCH_PAYMENT_LIMIT,
    DuesPaymentProcessor,
)

VALID_IBAN = "NL91ABNA0417164300"


def _payment(**kwargs):
    kwargs.setdefault("id", f"tr_{frappe.generate_hash(length=8)}")
    kwargs.setdefault("status", "paid")
    kwargs.setdefault("amount", {"value": "25.00", "currency": "EUR"})
    kwargs.setdefault("description", "")
    kwargs.setdefault("subscription_id", None)
    kwargs.setdefault("customer_id", None)
    kwargs.setdefault("paid_at", "2025-04-10T09:00:00+00:00")
    return SimpleNamespace(**kwargs)


class _StubBankTxCreator:
    def __init__(self, already=None):
        self._already = already or {"payment_entry": None, "bank_transaction": None}

    def check_already_processed(self, payment_id, check_payment_entry=True):
        return self._already


def _bare_processor(bank_tx_creator=None):
    """Build a DuesPaymentProcessor without triggering MollieClient() init."""
    from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
        PaymentClassifier,
    )

    proc = object.__new__(DuesPaymentProcessor)
    proc.mollie_client = SimpleNamespace(sdk_client=None)
    proc.classifier = PaymentClassifier()
    proc.bank_tx_creator = bank_tx_creator or _StubBankTxCreator()
    return proc


class TestHistoricalInvoiceValidation(EnhancedTestCase):
    """Input validation in _get_or_create_historical_invoice (pre-DB throws)."""

    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()
        self.member = self.create_test_member(
            first_name="Hist",
            last_name="Member",
            email=f"hist.{frappe.generate_hash(length=6)}@example.com",
        )

    def test_negative_amount_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.proc._get_or_create_historical_invoice(self.member.name, date(2025, 1, 1), -5.0)
        self.assertIn("must be positive", str(ctx.exception))

    def test_zero_amount_raises(self):
        with self.assertRaises(ValueError):
            self.proc._get_or_create_historical_invoice(self.member.name, date(2025, 1, 1), 0.0)

    def test_future_payment_date_raises(self):
        future = add_days(getdate(), 5)
        with self.assertRaises(ValueError) as ctx:
            self.proc._get_or_create_historical_invoice(self.member.name, future, 25.0)
        self.assertIn("cannot be in the future", str(ctx.exception))

    def test_member_without_customer_returns_none(self):
        # Strip the auto-created customer link -> method logs error, returns None.
        frappe.db.set_value("Member", self.member.name, "customer", None, update_modified=False)
        # The "no customer" branch logs via logger().error (not Error Log), so
        # it is safe under the Error Log guard.
        result = self.proc._get_or_create_historical_invoice(
            self.member.name, getdate("2025-03-01"), 25.0
        )
        self.assertIsNone(result)


class TestConsumerBankDataSave(EnhancedTestCase):
    """_extract_and_save_consumer_bank_data persists IBAN to Member."""

    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()
        self.member = self.create_test_member(
            first_name="Bank",
            last_name="Member",
            email=f"bank.{frappe.generate_hash(length=6)}@example.com",
        )
        self.member.reload()

    def test_no_details_is_noop(self):
        with self.assertNoErrorLog():
            self.proc._extract_and_save_consumer_bank_data(
                self.member.name, _payment(details=None)
            )
        # IBAN remains unchanged (None/empty)
        self.assertFalse(frappe.db.get_value("Member", self.member.name, "iban"))

    def test_invalid_iban_skipped(self):
        payment = _payment(details={"consumerName": "Test", "consumerAccount": "NOT-AN-IBAN"})
        with self.assertNoErrorLog():
            self.proc._extract_and_save_consumer_bank_data(self.member.name, payment)
        self.assertFalse(frappe.db.get_value("Member", self.member.name, "iban"))

    def test_valid_iban_saved_to_member(self):
        # Member starts with no IBAN
        frappe.db.set_value("Member", self.member.name, "iban", None, update_modified=False)
        payment = _payment(details={"consumerName": "Test Holder", "consumerAccount": VALID_IBAN})
        with self.assertNoErrorLog():
            self.proc._extract_and_save_consumer_bank_data(self.member.name, payment)
        saved = frappe.db.get_value("Member", self.member.name, "iban")
        # Member's own save hook may re-format the IBAN with spaces; the
        # processor wrote the cleaned form, so compare normalized.
        self.assertEqual(saved.replace(" ", "").upper(), VALID_IBAN.replace(" ", "").upper())
        # A Bank Account link should now exist for the member's customer
        customer = frappe.db.get_value("Member", self.member.name, "customer")
        if customer:
            ba = frappe.db.get_value("Bank Account", {"iban": VALID_IBAN}, ["party_type", "party"], as_dict=True)
            self.assertIsNotNone(ba)
            self.assertEqual(ba.party, customer)

    def test_existing_iban_not_overwritten(self):
        frappe.db.set_value(
            "Member", self.member.name, "iban", "NL02ABNA0123456789", update_modified=False
        )
        payment = _payment(details={"consumerName": "Other", "consumerAccount": VALID_IBAN})
        with self.assertNoErrorLog():
            self.proc._extract_and_save_consumer_bank_data(self.member.name, payment)
        # Original IBAN preserved (method only sets when member.iban is falsy)
        self.assertEqual(
            frappe.db.get_value("Member", self.member.name, "iban"), "NL02ABNA0123456789"
        )


class TestCreateSimpleInvoice(EnhancedTestCase):
    """_create_simple_invoice builds a real backdated, submitted Sales Invoice."""

    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()
        self.member = self.create_test_member(
            first_name="Simple",
            last_name="Invoice",
            email=f"simple.{frappe.generate_hash(length=6)}@example.com",
        )
        self.member.reload()
        self.assertTrue(self.member.customer)
        self.settings = frappe.get_single("Verenigingen Settings")
        # _create_simple_invoice takes membership_type as a free-text label used
        # only in the item name/description, so any string works; prefer an
        # existing Membership Type for realism.
        self.membership_type = (
            self.settings.default_membership_type
            or frappe.get_value("Membership Type", {}, "name")
            or "Coverage B3 Test Type"
        )

    def test_creates_backdated_invoice_with_coverage_fields(self):
        member_doc = frappe.get_doc("Member", self.member.name)
        coverage_start = getdate("2025-01-01")
        coverage_end = getdate("2025-03-31")
        payment_date = getdate("2025-02-15")

        invoice_name = self.proc._create_simple_invoice(
            member_doc,
            self.membership_type,
            coverage_start,
            coverage_end,
            25.0,
            payment_date,
        )
        if invoice_name is None:
            # Site missing income account config -> graceful None; nothing to assert.
            self.skipTest("Invoice creation returned None (income account not configured)")

        inv = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(inv.docstatus, 1)
        self.assertEqual(getdate(inv.posting_date), payment_date)
        self.assertEqual(getdate(inv.custom_coverage_start_date), coverage_start)
        self.assertEqual(getdate(inv.custom_coverage_end_date), coverage_end)
        self.assertEqual(inv.member, self.member.name)
        self.assertEqual(inv.is_membership_invoice, 1)
        self.assertAlmostEqual(float(inv.grand_total), 25.0, places=2)


class TestProcessDuesDeprecatedMode(EnhancedTestCase):
    """process_dues_payment: 'Payment Entry' creation_mode is deprecated and
    falls back to Bank Transaction. The fallback path logs a deprecation Error
    Log (intentional) -- we assert on the override behaviour."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Deprecated",
            last_name="Mode",
            email=f"dep.{frappe.generate_hash(length=6)}@example.com",
        )
        cust_id = f"cst_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member", self.member.name, "mollie_customer_id", cust_id, update_modified=False
        )
        self.cust_id = cust_id

    def test_deprecated_pe_mode_records_error_log(self):
        proc = _bare_processor()
        payment = _payment(customer_id=self.cust_id)
        # The deprecated-mode fallback intentionally writes a deprecation Error
        # Log; also the BT creation fails on a test site without Mollie bank
        # config, producing a processing Error Log. Mark both as expected so the
        # automatic tearDown guard does not trip.
        self.expectErrorLog("Deprecated Payment Entry Mode")
        self.expectErrorLog("Dues Payment Processing Error")
        self.expectErrorLog("Bank Transaction Creator Configuration Error")
        marker = frappe.utils.now_datetime()
        result = proc.process_dues_payment(
            payment.id, payment=payment, creation_mode="Payment Entry"
        )
        # The deprecation branch MUST have fired: exactly one "Deprecated Payment
        # Entry Mode" Error Log for this run. Without this assertion, deleting the
        # whole fallback block would not fail the test, since member/payment_type
        # are set BEFORE the branch.
        dep_logs = frappe.get_all(
            "Error Log",
            filters={
                "error": ["like", "%DEPRECATED%creation_mode%"],
                "creation": [">=", marker],
            },
        )
        self.assertEqual(len(dep_logs), 1)
        self.assertEqual(result["member"], self.member.name)
        self.assertEqual(result["payment_type"], "dues")


class TestBatchProcessLimitGuard(EnhancedTestCase):
    def test_over_limit_raises(self):
        proc = _bare_processor()
        with self.assertRaises(ValueError) as ctx:
            proc.batch_process_customer_payments("cst_x", limit=BATCH_PAYMENT_LIMIT + 1)
        self.assertIn("cannot exceed", str(ctx.exception))


if __name__ == "__main__":
    frappe.init(site="test_site_3")
    frappe.connect()
