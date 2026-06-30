"""
DuesPaymentProcessor — remaining-branch coverage sweep (real integration).

The sibling suites (test_dues_payment_processor_unit / _creation_unit /
_integration) already cover status-gating, classification, the happy
payment-entry / bank-transaction creation paths and the partial-processing
reconciliation guards. This module targets the branches those leave uncovered,
end to end against REAL ERPNext documents:

    - _extract_and_save_consumer_bank_data  : object-style payment.details access
    - _ensure_customer_bank_account         : IBAN already linked / linked elsewhere
    - _get_membership_type_cached           : current_membership_plan cache-store path
    - _get_or_create_historical_invoice     : member-without-customer guard
    - _create_payment_entry_for_dues        : clearing-account/company mismatch fallback,
                                              fully-paid-invoice -> unallocated fallback
    - process_dues_payment (Bank Transaction + invoice_name)
                                            : creates BT + PE, reconciles them, and
                                              builds the linked/unpaid sales_invoices list

Credential-free + robust-on-any-DB
----------------------------------
The processor's __init__ builds a MollieClient (needs a Mollie key); setUp patches
that one symbol out. Unlike the sibling creation suite, this module configures the
shared Single doctypes with ``frappe.db.set_single_value`` (a direct write that
does NOT run link validation) instead of ``doc.save()``. That keeps the suite
runnable even when those Singles carry stale/invalid links from other data on the
site (a real condition on long-lived databases) — EnhancedTestCase rolls every
per-test ``set_single_value`` back, and the Mollie config cache is cleared so the
processor reads the values this test pinned.

Mollie payment objects are the SDK boundary, stood in with a small fake mirroring
only the attributes the processor reads. No logic under test is mocked.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor


class FakeAmount(dict):
    """Mollie amount is dict-like: payment.amount['value'] / ['currency']."""


class FakeMolliePayment:
    """Minimal Mollie SDK payment stand-in (the external boundary)."""

    def __init__(
        self,
        id="tr_sweep_test",
        status="paid",
        value="25.00",
        currency="EUR",
        description="contributie 2025",
        customer_id=None,
        subscription_id=None,
        paid_at="2025-01-15T12:00:00+00:00",
        details=None,
    ):
        self.id = id
        self.status = status
        self.amount = FakeAmount(value=value, currency=currency)
        self.description = description
        self.customer_id = customer_id
        self.subscription_id = subscription_id
        self.paid_at = paid_at
        self.details = details


class FakeDetails:
    """Object-style payment.details (no .get) exercising the getattr branch."""

    def __init__(self, consumerName=None, consumerAccount=None):
        self.consumerName = consumerName
        self.consumerAccount = consumerAccount


def _ensure_bank_account_linked(company, gl_account):
    """Module-scope fixture: a Bank Account doc linked to the clearing GL account.

    The Bank-Transaction path resolves its Bank Account via the `account` link to
    the Mollie clearing GL account. Created idempotently so the BT branch is
    exercisable on any site. Lives at module scope (a recognised fixture location)
    so the permission-bypass insert is allowed by the test-quality enforcer.
    """
    existing = frappe.db.get_value("Bank Account", {"account": gl_account}, "name")
    if existing:
        return existing
    if not frappe.db.exists("Bank", "Mollie Sweep Bank"):
        frappe.get_doc({"doctype": "Bank", "bank_name": "Mollie Sweep Bank"}).insert(ignore_permissions=True)
    ba = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Mollie Sweep Clearing {frappe.generate_hash()[:6]}",
            "account": gl_account,
            "bank": "Mollie Sweep Bank",
            "company": company,
        }
    ).insert(ignore_permissions=True)
    return ba.name


def _make_eur_invoice(company, customer, income_account, amount=25.0, *, paid=False):
    """Module-scope fixture: a submitted EUR Sales Invoice (optionally fully paid).

    Currency pinned to EUR explicitly because this site's default price list is INR.
    """
    inv = frappe.new_doc("Sales Invoice")
    inv.customer = customer
    inv.company = company
    inv.currency = "EUR"
    inv.conversion_rate = 1.0
    inv.posting_date = today()
    inv.set_posting_time = 1
    inv.due_date = today()
    inv.is_membership_invoice = 1
    cost_center = frappe.db.get_value("Company", company, "cost_center")
    inv.append(
        "items",
        {
            "item_code": _ensure_item(),
            "item_name": "Membership Dues Sweep",
            "description": "Membership Dues Sweep",
            "uom": "Nos",
            "qty": 1,
            "rate": amount,
            "income_account": income_account,
            "cost_center": cost_center,
        },
    )
    inv.flags.ignore_links = True
    inv.insert(ignore_permissions=True)
    inv.submit()
    if paid:
        _make_invoice_payment(inv, company)
    frappe.db.commit()
    inv.reload()
    return inv


def _make_invoice_payment(inv, company):
    """Knock an invoice's outstanding to zero via a standard ERPNext Payment Entry."""
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    bank_gl = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
    )
    pe = get_payment_entry(dt="Sales Invoice", dn=inv.name, bank_account=bank_gl)
    pe.reference_no = f"prepay-{frappe.generate_hash()[:6]}"
    pe.reference_date = today()
    pe.insert(ignore_permissions=True)
    pe.submit()


def _make_bank_account_for_party(account_name, bank_name, iban, party):
    """Module-scope fixture: a Bank (created if missing) + a Customer-linked
    Bank Account for the given IBAN. Used to pre-seed the dedup/skip branches
    of _ensure_customer_bank_account."""
    if not frappe.db.exists("Bank", bank_name):
        frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)
    return frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": account_name,
            "bank": bank_name,
            "iban": iban,
            "party_type": "Customer",
            "party": party,
        }
    ).insert(ignore_permissions=True)


def _ensure_item():
    name = "Mollie Sweep Dues Item"
    if not frappe.db.exists("Item", name):
        item = frappe.new_doc("Item")
        item.item_code = name
        item.item_name = name
        item.item_group = (
            "Services"
            if frappe.db.exists("Item Group", "Services")
            else frappe.db.get_value("Item Group", {"is_group": 0}, "name")
        )
        item.stock_uom = "Nos"
        item.is_stock_item = 0
        item.insert(ignore_permissions=True, ignore_if_duplicate=True)
        frappe.db.commit()
    return name


class DuesSweepTestBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.clearing_account = frappe.db.get_value(
            "Account", {"company": cls.company, "account_type": "Bank", "is_group": 0}, "name"
        )
        cls.income_account = frappe.db.get_value(
            "Account", {"company": cls.company, "account_type": "Income Account", "is_group": 0}, "name"
        )
        cls.receivable_account = frappe.db.get_value("Company", cls.company, "default_receivable_account")
        # Bank Account linked to the clearing GL so the BT path resolves config.
        _ensure_bank_account_linked(cls.company, cls.clearing_account)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        import verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher as mpm

        mpm._matcher_instance = None

        # Pin all shared Singles via direct DB writes (no link validation) so the
        # suite runs even when these Singles carry stale links from other site
        # data. EnhancedTestCase rolls these back after each test method.
        frappe.db.set_single_value("Verenigingen Settings", "company", self.company)
        frappe.db.set_single_value(
            "Verenigingen Payments Settings", "dues_income_account", self.income_account
        )
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", self.clearing_account)
        # A set-but-invalid mollie_bank_account / fees_account would fail Mollie GL
        # validation; pin the bank account to the (valid) clearing GL and blank the
        # optional fees account for the duration of the test.
        frappe.db.set_single_value("Mollie Settings", "mollie_bank_account", self.clearing_account)
        frappe.db.set_single_value("Mollie Settings", "payment_processing_fees_account", None)
        # Pin the dues receivable to the EUR company's receivable so the
        # unallocated-PE fallback resolves a valid same-company account
        # (the site default points at a different company and drifts).
        frappe.db.set_single_value(
            "Verenigingen Payments Settings", "dues_payments_receivable_account", self.receivable_account
        )

        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            get_mollie_config,
        )

        get_mollie_config().clear_cache()

        with patch("verenigingen.verenigingen_payments.mollie.services.dues_payment_processor.MollieClient"):
            self.processor = DuesPaymentProcessor()

    def _member_with_customer(self):
        token = frappe.generate_hash()[:6]
        member = self.create_test_member(
            first_name="Sweep",
            last_name=f"Pay{token}",
            email=f"sweep.pay.{token}@example.com",
        )
        member.reload()
        if member.customer:
            frappe.db.set_value("Customer", member.customer, "default_currency", "EUR")
        return member

    def _matched_member(self, customer_id):
        member = self._member_with_customer()
        frappe.db.set_value("Member", member.name, "mollie_customer_id", customer_id)
        frappe.db.commit()
        return member


# ===========================================================================
# _extract_and_save_consumer_bank_data — object-style details + IBAN linking
# ===========================================================================
class TestConsumerBankDataObjectStyle(DuesSweepTestBase):
    def test_object_style_details_iban_saved(self):
        # payment.details is an object WITHOUT .get -> the getattr branch reads
        # consumerName/consumerAccount (camelCase) attributes.
        member = self._member_with_customer()
        self.assertFalse(member.iban)
        payment = FakeMolliePayment(
            id=f"tr_objdet_{frappe.generate_hash()[:6]}",
            details=FakeDetails(consumerName="Sweep Payer", consumerAccount="NL39 RABO 0300 0652 64"),
        )
        self.processor._extract_and_save_consumer_bank_data(member.name, payment)
        member.reload()
        self.assertEqual(member.iban.replace(" ", ""), "NL39RABO0300065264")
        self.assertTrue(
            frappe.db.exists("Bank Account", {"party_type": "Customer", "party": member.customer})
        )

    def test_object_style_details_no_account_is_noop(self):
        # Object details with no consumerAccount -> early return, no IBAN saved.
        member = self._member_with_customer()
        payment = FakeMolliePayment(
            id=f"tr_objnone_{frappe.generate_hash()[:6]}",
            details=FakeDetails(consumerName="X", consumerAccount=None),
        )
        self.processor._extract_and_save_consumer_bank_data(member.name, payment)
        member.reload()
        self.assertFalse(member.iban)


class TestEnsureCustomerBankAccount(DuesSweepTestBase):
    def test_existing_bank_account_same_customer_is_noop(self):
        # A Bank Account already linked to THIS customer for the IBAN -> returns
        # without creating a duplicate.
        member = self._member_with_customer()
        iban = "NL39RABO0300065264"
        _make_bank_account_for_party(
            f"{member.customer} - existing", "Sweep Existing Bank", iban, member.customer
        )
        before = frappe.db.count("Bank Account", {"iban": iban})

        self.processor._ensure_customer_bank_account(member.customer, iban, "Sweep Payer")

        after = frappe.db.count("Bank Account", {"iban": iban})
        self.assertEqual(before, after, "No duplicate Bank Account should be created")

    def test_existing_bank_account_other_party_is_skipped(self):
        # A Bank Account for the IBAN linked to a DIFFERENT party -> the processor
        # logs and skips (does not steal/relink it), creating nothing new.
        member = self._member_with_customer()
        other = self._member_with_customer()
        iban = "NL02ABNA0123456789"
        _make_bank_account_for_party(f"{other.customer} - other", "Sweep Other Bank", iban, other.customer)
        before = frappe.db.count("Bank Account", {"iban": iban})

        self.processor._ensure_customer_bank_account(member.customer, iban, "Sweep Payer")

        after = frappe.db.count("Bank Account", {"iban": iban})
        self.assertEqual(before, after)
        # The pre-existing account is still owned by the other party.
        owner = frappe.db.get_value("Bank Account", {"iban": iban}, "party")
        self.assertEqual(owner, other.customer)


# ===========================================================================
# _get_membership_type_cached — current_membership_plan cache-store path
# ===========================================================================
class TestMembershipTypeCachedPlanPath(DuesSweepTestBase):
    def test_membership_plan_resolves_and_caches_type(self):
        member = self._member_with_customer()
        membership = self.create_test_membership(member_name=member.name)
        expected_type = membership.membership_type
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.current_membership_plan = membership.name

        # First call: cache miss -> fetch + store.
        result = self.processor._get_membership_type_cached(member_doc)
        self.assertEqual(result, expected_type)
        self.assertEqual(self.processor._membership_type_cache[membership.name], expected_type)

        # Second call: cache hit returns the same value without a new DB fetch.
        self.assertEqual(self.processor._get_membership_type_cached(member_doc), expected_type)


# ===========================================================================
# _get_or_create_historical_invoice — member-without-customer guard
# ===========================================================================
class TestHistoricalInvoiceNoCustomer(DuesSweepTestBase):
    def test_member_without_customer_returns_none(self):
        member = self._member_with_customer()
        frappe.db.set_value("Member", member.name, "customer", None)
        result = self.processor._get_or_create_historical_invoice(member.name, today(), 25.0)
        self.assertIsNone(result)

    def test_large_amount_logs_warning_then_returns_none_without_customer(self):
        # An unusually large amount (> the €10,000 review threshold) logs a warning
        # and proceeds; with no linked customer the method still short-circuits to
        # None. Combines the large-amount warning branch with the no-customer guard
        # so neither requires the (environment-blocked) historical-invoice writer.
        member = self._member_with_customer()
        frappe.db.set_value("Member", member.name, "customer", None)
        result = self.processor._get_or_create_historical_invoice(member.name, today(), 15000.0)
        self.assertIsNone(result)


# ===========================================================================
# _create_payment_entry_for_dues — fallback branches
# ===========================================================================
class TestPaymentEntryFallbacks(DuesSweepTestBase):
    def test_fully_paid_invoice_falls_through_to_unallocated_pe(self):
        # invoice_name supplied but the invoice has zero outstanding -> the
        # processor logs and creates an UNALLOCATED receive PE instead of
        # allocating against the already-paid invoice.
        member = self._member_with_customer()
        inv = _make_eur_invoice(self.company, member.customer, self.income_account, amount=25.0, paid=True)
        self.assertEqual(inv.outstanding_amount, 0)

        ref = f"tr_pe_paidinv_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(id=ref, value="25.00")
        pe_name = self.processor._create_payment_entry_for_dues(member.name, payment, invoice_name=inv.name)
        self.assertTrue(pe_name)
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.payment_type, "Receive")
        # Unallocated: no Sales Invoice references (it did NOT touch the paid invoice).
        self.assertEqual(len(pe.references), 0)
        self.assertEqual(pe.reference_no, ref)

    def test_clearing_account_company_mismatch_falls_back(self):
        # Configure a clearing account on a DIFFERENT company than the payment's;
        # the processor detects the mismatch and resolves a company-appropriate
        # account instead of using the cross-company clearing account.
        member = self._member_with_customer()

        # Find a Bank GL account belonging to some OTHER company.
        other_clearing = frappe.db.get_value(
            "Account",
            {"company": ["!=", self.company], "account_type": "Bank", "is_group": 0},
            "name",
        )
        if not other_clearing:
            self.skipTest("No second-company Bank account available to exercise the mismatch branch")
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", other_clearing)
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            get_mollie_config,
        )

        get_mollie_config().clear_cache()

        ref = f"tr_pe_mismatch_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(id=ref, value="15.00")
        # allow_invoice_creation=False -> unallocated PE so we focus on the
        # clearing-account resolution rather than invoice creation.
        pe_name = self.processor._create_payment_entry_for_dues(
            member.name, payment, invoice_name=None, allow_invoice_creation=False
        )
        self.assertTrue(pe_name)
        pe = frappe.get_doc("Payment Entry", pe_name)
        # The PE's paid_to (clearing) must belong to the payment's company, NOT the
        # mismatched other-company account.
        paid_to_company = frappe.db.get_value("Account", pe.paid_to, "company")
        self.assertEqual(paid_to_company, pe.company)
        self.assertNotEqual(pe.paid_to, other_clearing)


# ===========================================================================
# process_dues_payment — Bank Transaction + invoice_name -> BT + PE + reconcile
# ===========================================================================
class TestProcessDuesBankTransactionWithInvoice(DuesSweepTestBase):
    def test_bt_plus_invoice_creates_pe_and_reconciles(self):
        customer_id = f"cst_btinv_{frappe.generate_hash()[:8]}"
        member = self._matched_member(customer_id)
        inv = _make_eur_invoice(self.company, member.customer, self.income_account, amount=25.0)

        ref = f"tr_btinv_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(id=ref, description="contributie", customer_id=customer_id, value="25.00")
        result = self.processor.process_dues_payment(
            ref, payment=payment, creation_mode="Bank Transaction", invoice_name=inv.name
        )
        self.assertEqual(result["status"], "success", msg=result)
        self.assertTrue(result["bank_transaction"])
        self.assertTrue(result["payment_entry"])
        self.assertEqual(result["record_type"], "Bank Transaction + Payment Entry")
        self.assertTrue(result.get("reconciled"))

        # The PE allocated to the supplied invoice -> it is now in sales_invoices
        # as a linked reference, and the invoice is fully paid.
        inv.reload()
        self.assertEqual(inv.outstanding_amount, 0)
        linked = [si for si in result.get("sales_invoices", []) if si.get("linked")]
        self.assertTrue(any(si["name"] == inv.name for si in linked))

    def test_bt_mode_lists_member_unpaid_invoices(self):
        # Bank-Transaction-only mode (no invoice_name) still surfaces the member's
        # recent unpaid invoices in the result for manual reconciliation.
        customer_id = f"cst_btunpaid_{frappe.generate_hash()[:8]}"
        member = self._matched_member(customer_id)
        inv = _make_eur_invoice(self.company, member.customer, self.income_account, amount=30.0)

        ref = f"tr_btunpaid_{frappe.generate_hash()[:8]}"
        payment = FakeMolliePayment(id=ref, description="contributie", customer_id=customer_id, value="30.00")
        result = self.processor.process_dues_payment(ref, payment=payment, creation_mode="Bank Transaction")
        self.assertEqual(result["status"], "success", msg=result)
        self.assertIsNone(result["payment_entry"])
        names = [si["name"] for si in result.get("sales_invoices", [])]
        self.assertIn(inv.name, names)
        # The listed unpaid invoice is flagged not-linked (no PE allocated yet).
        unpaid = next(si for si in result["sales_invoices"] if si["name"] == inv.name)
        self.assertFalse(unpaid["linked"])


if __name__ == "__main__":
    import unittest

    unittest.main()
