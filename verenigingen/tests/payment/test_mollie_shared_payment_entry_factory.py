"""
Tests for the shared Mollie PaymentEntryFactory.

Covers ``verenigingen_payments/mollie/services/shared/payment_entry_factory.py``:
- mollie_data validation/extraction (_validate_and_extract_mollie_data)
- title/remarks sanitization & truncation
- reference-date resolution from paid_at
- record-reference extraction (metadata / description JSON / fallback)
- account resolution (_get_accounts) with donation vs membership
- customer resolution from context (member with existing customer)
- end-to-end create_payment_entry producing a real, submitted Payment Entry
  with correct party / amount / reference_no, plus idempotency (duplicate
  reference_no returns None).

The Payment Entry is created for real against an ERPNext company. A "Mollie"
named Account is ensured so the factory's bank-account fallback resolves.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_shared_payment_entry_factory
"""

from decimal import Decimal

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
    MollieDataValidationError,
    PaymentEntryFactory,
)


def _ensure_mollie_named_account(company: str) -> str:
    """Ensure an Account named 'Mollie' exists for the company.

    The factory's _get_accounts() falls back to an Account with account_name
    'Mollie' when no mollie_bank_account is configured. Create one under the
    company's bank-account parent group so PE creation can resolve a paid_to.
    """
    existing = frappe.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
    if existing:
        return existing

    abbr = frappe.get_value("Company", company, "abbr")
    # Find a non-group Bank-type parent group; fall back to any group account.
    parent = frappe.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
    )
    if not parent:
        parent = frappe.get_value("Account", {"company": company, "is_group": 1}, "name")

    acct = frappe.new_doc("Account")
    acct.account_name = "Mollie"
    acct.company = company
    acct.parent_account = parent
    acct.account_type = "Bank"
    acct.account_currency = frappe.get_value("Company", company, "default_currency")
    acct.insert(ignore_permissions=True)
    return acct.name


class TestMollieDataValidation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()

    def test_valid_data_extracted(self):
        pid, amount = self.pe_factory._validate_and_extract_mollie_data(
            {"payment_id": "tr_1", "amount": "25.50"}
        )
        self.assertEqual(pid, "tr_1")
        self.assertEqual(amount, Decimal("25.50"))

    def test_amount_rounds_half_up(self):
        _, amount = self.pe_factory._validate_and_extract_mollie_data(
            {"payment_id": "tr_1", "amount": "10.005"}
        )
        self.assertEqual(amount, Decimal("10.01"))

    def test_not_a_dict(self):
        with self.assertRaises(MollieDataValidationError):
            self.pe_factory._validate_and_extract_mollie_data("nope")

    def test_missing_payment_id(self):
        with self.assertRaises(MollieDataValidationError):
            self.pe_factory._validate_and_extract_mollie_data({"amount": "5"})

    def test_payment_id_not_string(self):
        with self.assertRaises(MollieDataValidationError):
            self.pe_factory._validate_and_extract_mollie_data({"payment_id": 123, "amount": "5"})

    def test_missing_amount(self):
        with self.assertRaises(MollieDataValidationError):
            self.pe_factory._validate_and_extract_mollie_data({"payment_id": "tr_1"})

    def test_invalid_amount(self):
        with self.assertRaises(MollieDataValidationError):
            self.pe_factory._validate_and_extract_mollie_data({"payment_id": "tr_1", "amount": "abc"})

    def test_non_positive_amount(self):
        with self.assertRaises(MollieDataValidationError):
            self.pe_factory._validate_and_extract_mollie_data({"payment_id": "tr_1", "amount": "0"})


class TestSanitizationAndExtraction(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()

    def test_sanitize_title_collapses_whitespace(self):
        self.assertEqual(self.pe_factory._sanitize_title("  a   b\tc  "), "a b c")

    def test_sanitize_title_empty_defaults(self):
        self.assertEqual(self.pe_factory._sanitize_title(""), "Payment")

    def test_sanitize_title_truncates(self):
        long = "x" * 200
        out = self.pe_factory._sanitize_title(long)
        self.assertEqual(len(out), 140)
        self.assertTrue(out.endswith("..."))

    def test_sanitize_remarks_empty(self):
        self.assertEqual(self.pe_factory._sanitize_remarks(""), "")

    def test_sanitize_remarks_truncates(self):
        out = self.pe_factory._sanitize_remarks("y" * 600)
        self.assertEqual(len(out), 500)
        self.assertTrue(out.endswith("..."))

    def test_reference_date_from_paid_at(self):
        d = self.pe_factory._get_reference_date({"paid_at": "2025-03-15T12:00:00+00:00"})
        self.assertEqual(d.isoformat(), "2025-03-15")

    def test_reference_date_bad_paid_at_falls_back_today(self):
        d = self.pe_factory._get_reference_date({"paid_at": "not-a-date"})
        self.assertEqual(d, frappe.utils.getdate())

    def test_reference_date_no_paid_at(self):
        self.assertEqual(self.pe_factory._get_reference_date({}), frappe.utils.getdate())

    def test_extract_reference_from_metadata(self):
        ctx = PaymentContext("membership", "Member", "M-1")
        ref = self.pe_factory._extract_record_reference({"metadata": {"record_id": "REC-99"}}, ctx)
        self.assertEqual(ref, "REC-99")

    def test_extract_reference_from_description_json(self):
        ctx = PaymentContext("membership", "Member", "M-1")
        ref = self.pe_factory._extract_record_reference(
            {"description": '{"record_id": "DESC-7"}'}, ctx
        )
        self.assertEqual(ref, "DESC-7")

    def test_extract_reference_fallback_to_target(self):
        ctx = PaymentContext("membership", "Member", "M-FALLBACK")
        ref = self.pe_factory._extract_record_reference({"description": "not json"}, ctx)
        self.assertEqual(ref, "M-FALLBACK")

    def test_generate_remarks(self):
        ctx = PaymentContext("membership", "Member", "M-1")
        remarks = self.pe_factory._generate_remarks(ctx, {"method": "ideal"})
        self.assertIn("Membership", remarks)
        self.assertIn("M-1", remarks)
        self.assertIn("ideal", remarks)


class TestGetAccounts(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()
        self.company = self.pe_factory._get_company()
        _ensure_mollie_named_account(self.company)

    def test_membership_uses_company_receivable_and_mollie_bank(self):
        accounts = self.pe_factory._get_accounts(self.company, "membership")
        self.assertTrue(accounts["receivable_account"])
        self.assertTrue(accounts["bank_account"])
        self.assertEqual(
            accounts["receivable_account"],
            frappe.get_value("Company", self.company, "default_receivable_account"),
        )

    def test_donation_falls_back_to_company_receivable_when_unset(self):
        # donation_receivable_account is not configured on the test site, so it
        # should fall back to the company default receivable account.
        accounts = self.pe_factory._get_accounts(self.company, "donation")
        self.assertEqual(
            accounts["receivable_account"],
            frappe.get_value("Company", self.company, "default_receivable_account"),
        )


class TestCreatePaymentEntryEndToEnd(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()
        self.company = self.pe_factory._get_company()
        _ensure_mollie_named_account(self.company)
        # Member WITH an existing customer so customer resolution does not have
        # to create one (keeps the test focused on PE creation).
        self.member = self.create_test_member(
            first_name="Factory",
            last_name="Member",
            email=f"factory.{frappe.generate_hash(length=6)}@example.com",
        )
        # create_test_member auto-creates and links a Customer; reuse it.
        self.member.reload()
        customer_name = self.member.customer
        self.assertTrue(customer_name, "Test member should have an auto-linked Customer")
        self.customer = frappe.get_doc("Customer", customer_name)

    def test_creates_submitted_payment_entry_with_correct_fields(self):
        ctx = PaymentContext("membership", "Member", self.member.name)
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        mollie_data = {
            "payment_id": payment_id,
            "amount": "42.00",
            "paid_at": "2025-04-01T10:00:00+00:00",
            "method": "ideal",
            "metadata": {"record_id": "INV-TEST"},
        }
        pe = self.pe_factory.create_payment_entry(ctx, mollie_data, customer=self.customer.name)
        self.assertIsNotNone(pe, "Factory should return a Payment Entry document")
        self.assertEqual(pe.docstatus, 1, "Payment Entry should be submitted")
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.party_type, "Customer")
        self.assertEqual(pe.party, self.customer.name)
        self.assertEqual(float(pe.paid_amount), 42.00)
        self.assertEqual(pe.reference_no, payment_id)
        self.assertEqual(pe.reference_date.isoformat(), "2025-04-01")
        self.assertEqual(pe.posting_date.isoformat(), "2025-04-01")
        # Track for cleanup
        self.assertTrue(frappe.db.exists("Payment Entry", pe.name))

    def test_idempotent_duplicate_reference_returns_none(self):
        ctx = PaymentContext("membership", "Member", self.member.name)
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        mollie_data = {"payment_id": payment_id, "amount": "10.00"}
        pe1 = self.pe_factory.create_payment_entry(ctx, mollie_data, customer=self.customer.name)
        self.assertIsNotNone(pe1)
        # Second call with same reference_no must be a no-op (idempotent)
        pe2 = self.pe_factory.create_payment_entry(ctx, mollie_data, customer=self.customer.name)
        self.assertIsNone(pe2)
        # Only one Payment Entry exists with that reference_no
        count = frappe.db.count("Payment Entry", {"reference_no": payment_id, "docstatus": ["!=", 2]})
        self.assertEqual(count, 1)

    def test_resolve_customer_from_member_context(self):
        # When customer is not passed, factory resolves it from the member.
        ctx = PaymentContext("membership", "Member", self.member.name)
        resolved = self.pe_factory._resolve_customer_for_context(ctx)
        self.assertEqual(resolved, self.customer.name)
