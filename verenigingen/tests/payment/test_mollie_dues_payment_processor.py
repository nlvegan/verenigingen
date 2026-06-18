"""
Tests for the Mollie DuesPaymentProcessor.

Covers ``verenigingen_payments/mollie/services/dues_payment_processor.py``:
- identify_payment_type (delegates to PaymentClassifier; real DB lookups)
- _get_membership_type_cached (member plan -> settings default; caching)
- _resolve_chapter_cost_center (chapter -> company fallback)
- _get_or_create_dues_item (idempotent item creation)
- _get_member_with_customer (validation throw on missing customer)
- process_dues_payment branch logic: non-paid skip, wrong-type skip,
  already-processed idempotency (Payment Entry + Bank Transaction), and
  no-member error -- using a stubbed bank-transaction creator so no real
  Mollie/bank docs are needed for those branches.
- _create_payment_entry_for_dues end-to-end: builds a REAL submitted Payment
  Entry allocated against a real Sales Invoice and asserts party/amount/
  reference_no/custom_member/invoice-allocation are correct. This is the path
  that historically hid wrong-linking bugs.

The Mollie SDK client is never hit: instances are built via object.__new__ and
given test doubles, or the end-to-end path passes a pre-fetched payment object
plus an explicit invoice_name (no SDK fetch).

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_dues_payment_processor
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import PaymentType
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
    DuesPaymentProcessor,
)


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
    """Stand-in for BankTransactionCreator with controllable idempotency."""

    def __init__(self, already=None):
        self._already = already or {"payment_entry": None, "bank_transaction": None}

    def check_already_processed(self, payment_id, check_payment_entry=True):
        return self._already


def _bare_processor(classifier=None, bank_tx_creator=None):
    """Build a DuesPaymentProcessor without triggering MollieClient() init."""
    from verenigingen.verenigingen_payments.mollie.domain.payment_classification import (
        PaymentClassifier,
    )

    proc = object.__new__(DuesPaymentProcessor)
    proc.mollie_client = SimpleNamespace(sdk_client=None)
    proc.classifier = classifier or PaymentClassifier()
    proc.bank_tx_creator = bank_tx_creator or _StubBankTxCreator()
    return proc


def _ensure_mollie_clearing_on_test_company():
    """Create/point Mollie clearing account at _Test Company so PE company
    matches the invoice company in the end-to-end PE test."""
    company = "_Test Company"
    name = frappe.get_value("Account", {"company": company, "account_name": "Mollie Clearing"}, "name")
    if not name:
        parent = frappe.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.get_value("Account", {"company": company, "is_group": 1}, "name")
        acct = frappe.new_doc("Account")
        acct.account_name = "Mollie Clearing"
        acct.company = company
        acct.parent_account = parent
        acct.account_type = "Bank"
        acct.account_currency = frappe.get_value("Company", company, "default_currency")
        acct.insert(ignore_permissions=True)
        name = acct.name
    return name


class TestIdentifyPaymentType(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()
        self.member = self.create_test_member(
            first_name="Dues", last_name="Member", email=f"dues.{frappe.generate_hash(length=6)}@example.com"
        )

    def test_dues_by_customer_id(self):
        cust_id = f"cst_{frappe.generate_hash(length=8)}"
        frappe.db.set_value(
            "Member", self.member.name, "mollie_customer_id", cust_id, update_modified=False
        )
        self.assertEqual(self.proc.identify_payment_type(_payment(customer_id=cust_id)), PaymentType.DUES)

    def test_unknown_when_no_match(self):
        self.assertEqual(
            self.proc.identify_payment_type(_payment(description="mystery")), PaymentType.UNKNOWN
        )


class TestMembershipTypeAndCostCenter(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()

    def test_membership_type_falls_back_to_settings_default(self):
        # Member with no current_membership_plan -> settings default returned.
        member_doc = SimpleNamespace(current_membership_plan=None)
        default = frappe.get_single("Verenigingen Settings").default_membership_type
        self.assertEqual(self.proc._get_membership_type_cached(member_doc), default)

    def test_membership_type_caches_default(self):
        member_doc = SimpleNamespace(current_membership_plan=None)
        first = self.proc._get_membership_type_cached(member_doc)
        # second call should use the cached _default_membership_type attribute
        self.assertTrue(hasattr(self.proc, "_default_membership_type"))
        self.assertEqual(self.proc._get_membership_type_cached(member_doc), first)

    def test_resolve_cost_center_company_fallback(self):
        # Member with no chapter -> company default cost center (or None).
        member = self.create_test_member(
            first_name="CC", last_name="Member", email=f"cc.{frappe.generate_hash(length=6)}@example.com"
        )
        company = frappe.get_single("Verenigingen Settings").company
        member_doc = frappe.get_doc("Member", member.name)
        result = self.proc._resolve_chapter_cost_center(member_doc, company)
        expected = frappe.db.get_value("Company", company, "cost_center")
        if expected and frappe.db.exists("Cost Center", expected):
            self.assertEqual(result, expected)
        else:
            self.assertIsNone(result)


class TestDuesItem(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()
        self.company = frappe.get_single("Verenigingen Settings").company
        self.income = frappe.get_value("Company", self.company, "default_income_account")

    def test_get_or_create_dues_item_idempotent(self):
        item_name = f"Membership Dues - Test {frappe.generate_hash(length=5)}"
        created = self.proc._get_or_create_dues_item(item_name, self.company, self.income)
        self.assertEqual(created, item_name)
        self.assertTrue(frappe.db.exists("Item", item_name))
        # second call returns same name, does not error
        again = self.proc._get_or_create_dues_item(item_name, self.company, self.income)
        self.assertEqual(again, item_name)


class TestGetMemberWithCustomer(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()

    def test_throws_when_no_customer(self):
        member = self.create_test_member(
            first_name="NoCust", last_name="Member", email=f"nc.{frappe.generate_hash(length=6)}@example.com"
        )
        # Strip the auto-created customer link to exercise the throw branch.
        frappe.db.set_value("Member", member.name, "customer", None, update_modified=False)
        with self.assertRaises(frappe.ValidationError):
            self.proc._get_member_with_customer(member.name)

    def test_returns_member_and_customer(self):
        member = self.create_test_member(
            first_name="WithCust", last_name="Member", email=f"wc.{frappe.generate_hash(length=6)}@example.com"
        )
        member.reload()
        m, cust = self.proc._get_member_with_customer(member.name)
        self.assertEqual(m.name, member.name)
        self.assertEqual(cust, member.customer)


class TestProcessDuesPaymentBranches(EnhancedTestCase):
    def test_skips_non_paid_payment(self):
        proc = _bare_processor()
        result = proc.process_dues_payment("tr_x", payment=_payment(status="open"))
        self.assertEqual(result["status"], "skipped")
        self.assertIn("not 'paid'", result["skipped_reason"])

    def test_already_processed_both(self):
        proc = _bare_processor(
            bank_tx_creator=_StubBankTxCreator(
                already={"payment_entry": "PE-1", "bank_transaction": "BT-1"}
            )
        )
        result = proc.process_dues_payment("tr_x", payment=_payment())
        self.assertEqual(result["status"], "already_processed")
        self.assertEqual(result["payment_entry"], "PE-1")
        self.assertEqual(result["bank_transaction"], "BT-1")

    def test_already_processed_pe_only(self):
        proc = _bare_processor(
            bank_tx_creator=_StubBankTxCreator(
                already={"payment_entry": "PE-9", "bank_transaction": None}
            )
        )
        result = proc.process_dues_payment("tr_x", payment=_payment())
        self.assertEqual(result["status"], "already_processed")
        self.assertEqual(result["payment_entry"], "PE-9")
        self.assertIn("legacy mode", result["skipped_reason"])

    def test_skips_non_dues_type(self):
        # No member/donor matches -> classifier returns UNKNOWN -> skipped.
        proc = _bare_processor()
        result = proc.process_dues_payment("tr_x", payment=_payment(description="random"))
        self.assertEqual(result["status"], "skipped")
        self.assertIn("not membership dues", result["skipped_reason"])

    def test_no_member_found_error(self):
        # Force classification to 'dues' via a member match, then delete the
        # matching member's customer mapping so find_member resolves but... we
        # instead use a customer that classifies as dues but whose member lookup
        # via matcher fails. Simpler: a description keyword 'contributie' makes
        # the classifier return DUES with no member_id, and the matcher finds no
        # member -> error branch.
        proc = _bare_processor()
        result = proc.process_dues_payment(
            "tr_x", payment=_payment(description="contributie 2025")
        )
        # classifier -> dues (low confidence keyword), matcher -> no member
        self.assertEqual(result["payment_type"], PaymentType.DUES)
        self.assertEqual(result["status"], "error")
        self.assertIn("No member found", result["error"])


class TestCreatePaymentEntryForDuesEndToEnd(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.proc = _bare_processor()
        self.company = "_Test Company"
        self.clearing = _ensure_mollie_clearing_on_test_company()

        # Member + auto-created customer
        self.member = self.create_test_member(
            first_name="PE", last_name="Member", email=f"pe.{frappe.generate_hash(length=6)}@example.com"
        )
        self.member.reload()
        self.customer = self.member.customer
        self.assertTrue(self.customer)

        # Build a real submitted Sales Invoice with an outstanding amount.
        self.invoice_name = self._make_invoice(amount=25.00)

    def _make_invoice(self, amount):
        income = frappe.get_value("Company", self.company, "default_income_account")
        item_name = f"PE Dues Item {frappe.generate_hash(length=5)}"
        if not frappe.db.exists("Item", item_name):
            item = frappe.new_doc("Item")
            item.item_code = item_name
            item.item_name = item_name
            item.item_group = "Services" if frappe.db.exists("Item Group", "Services") else frappe.get_value("Item Group", {"is_group": 0}, "name")
            item.stock_uom = "Unit" if frappe.db.exists("UOM", "Unit") else frappe.get_value("UOM", {}, "name")
            item.is_stock_item = 0
            item.insert(ignore_permissions=True)

        inv = frappe.new_doc("Sales Invoice")
        inv.customer = self.customer
        inv.company = self.company
        inv.member = self.member.name
        inv.is_membership_invoice = 1
        inv.append(
            "items",
            {"item_code": item_name, "qty": 1, "rate": amount, "income_account": income},
        )
        inv.flags.ignore_permissions = True
        inv.insert(ignore_permissions=True)
        inv.submit()
        return inv.name

    def test_creates_pe_allocated_to_invoice(self):
        payment = _payment(amount={"value": "25.00", "currency": "EUR"})
        pe_name = self.proc._create_payment_entry_for_dues(
            self.member.name, payment, invoice_name=self.invoice_name
        )
        self.assertIsNotNone(pe_name, "Should create a Payment Entry")
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.party_type, "Customer")
        self.assertEqual(pe.party, self.customer)
        self.assertEqual(pe.reference_no, payment.id)
        # custom_member must carry the member link (regression guard)
        self.assertEqual(pe.custom_member, self.member.name)
        # allocated against our invoice
        refs = [r.reference_name for r in pe.references if r.reference_doctype == "Sales Invoice"]
        self.assertIn(self.invoice_name, refs)
        # invoice should now be (partly/fully) paid
        inv = frappe.get_doc("Sales Invoice", self.invoice_name)
        self.assertLess(inv.outstanding_amount, 25.00)

    def test_idempotent_returns_existing_pe(self):
        payment = _payment(amount={"value": "25.00", "currency": "EUR"})
        first = self.proc._create_payment_entry_for_dues(
            self.member.name, payment, invoice_name=self.invoice_name
        )
        self.assertIsNotNone(first)
        # Same payment id -> idempotency manager returns existing PE
        second = self.proc._create_payment_entry_for_dues(
            self.member.name, payment, invoice_name=self.invoice_name
        )
        self.assertEqual(second, first)
