"""
Integration tests (Tier-2) for the database-driven logic in the Mollie bulk
payment checker and payment orchestrator, against REAL DocTypes via the
Enhanced Test Factory. No mocks of any kind.

The methods under test read/query the database (Member, Bank Transaction,
Payment Entry, Sales Invoice) and contain no Mollie-API calls, so they can be
exercised without credentials by invoking them as unbound methods — sidestepping
the constructors, which build a MollieClient that requires Mollie Settings keys.

Targets:
  bulk_payment_checker.py
    - BulkPaymentChecker.get_members_with_mollie_customers   (pagination + filter)
    - BulkPaymentChecker._batch_check_already_processed       (idempotency batch)
  mollie_payment_orchestrator.py
    - MolliePaymentOrchestrator.get_processing_status         (document-state probe)
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.error_log_assertions import assert_error_log
from verenigingen.tests.support.invoice_payments import member_with_customer
from verenigingen.utils.bank_utils import get_or_create_unknown_bank
from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import BulkPaymentChecker
from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
    MolliePaymentOrchestrator,
)


def _get_test_company():
    return frappe.db.get_single_value(
        "Verenigingen Settings", "company"
    ) or frappe.defaults.get_global_default("company")


def _bank_account_currency(bank_account):
    """Resolve the account currency of a Bank Account's linked GL account.

    Bank Transaction validation requires the transaction currency to match the
    Bank Account's account currency; the shared _Test Company bank account is INR.
    """
    gl = frappe.db.get_value("Bank Account", bank_account, "account")
    currency = None
    if gl:
        currency = frappe.db.get_value("Account", gl, "account_currency")
    return currency or "EUR"


def _ensure_bank_account(test_case):
    """Return a usable Bank Account, creating one (linked to a real bank GL
    account) if the site has none. Tracked for cleanup when created here."""
    company = _get_test_company()
    existing = frappe.db.get_value("Bank Account", {"company": company}, "name") or frappe.db.get_value(
        "Bank Account", {}, "name"
    )
    if existing:
        return existing

    gl_account = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
    )
    if not gl_account:
        return None

    ba = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Mollie Test {frappe.generate_hash()[:6]}",
            "bank": get_or_create_unknown_bank(),
            "account": gl_account,
            "company": company,
        }
    )
    ba.insert(ignore_permissions=True)
    # EnhancedTestCase rolls back per-method; also register for the factory drain
    # in case anything commits during the test.
    factory = getattr(test_case, "factory", None)
    if factory is not None and hasattr(factory, "track_document"):
        factory.track_document("Bank Account", ba.name)
    return ba.name


def _create_bank_transaction(test_case, bank_account, reference_number, *, party_type=None, party=None):
    """Factory helper: create+track a Bank Transaction referencing a Mollie payment.

    Currency is matched to the Bank Account's GL account to satisfy validation.
    Lives at module scope (not a test method) so the permission-bypass on insert
    is a recognised factory/setup pattern.
    """
    company = frappe.db.get_value("Bank Account", bank_account, "company")
    bt = frappe.get_doc(
        {
            "doctype": "Bank Transaction",
            "date": frappe.utils.today(),
            "bank_account": bank_account,
            "company": company,
            "deposit": 25.0,
            "withdrawal": 0.0,
            "currency": _bank_account_currency(bank_account),
            "reference_number": reference_number,
            "party_type": party_type,
            "party": party,
        }
    )
    bt.insert(ignore_permissions=True)
    factory = getattr(test_case, "factory", None)
    if factory is not None and hasattr(factory, "track_document"):
        factory.track_document("Bank Transaction", bt.name)
    return bt.name


class TestGetMembersWithMollieCustomers(EnhancedTestCase):
    """BulkPaymentChecker.get_members_with_mollie_customers — real DB filtering."""

    def test_only_returns_members_with_mollie_customer_id(self):
        token = frappe.generate_hash()[:8]
        cid_a = f"cst_int_{token}_a"
        cid_b = f"cst_int_{token}_b"

        m_with_a = self.create_test_member(
            first_name="Mollie", last_name=f"WithA{token}", email=f"mw.a.{token}@example.com"
        )
        m_with_b = self.create_test_member(
            first_name="Mollie", last_name=f"WithB{token}", email=f"mw.b.{token}@example.com"
        )
        m_without = self.create_test_member(
            first_name="Mollie", last_name=f"Without{token}", email=f"mw.no.{token}@example.com"
        )

        frappe.db.set_value("Member", m_with_a.name, "mollie_customer_id", cid_a)
        frappe.db.set_value("Member", m_with_b.name, "mollie_customer_id", cid_b)
        # m_without intentionally left with no mollie_customer_id

        # Unbound call — method uses only frappe.db, no self attributes.
        data = BulkPaymentChecker.get_members_with_mollie_customers(None, limit=1000)

        returned_names = {m["name"] for m in data["members"]}
        self.assertIn(m_with_a.name, returned_names)
        self.assertIn(m_with_b.name, returned_names)
        self.assertNotIn(m_without.name, returned_names)
        # The returned member dicts carry the mollie_customer_id we set.
        by_name = {m["name"]: m for m in data["members"]}
        self.assertEqual(by_name[m_with_a.name]["mollie_customer_id"], cid_a)
        self.assertEqual(by_name[m_with_b.name]["mollie_customer_id"], cid_b)

    def test_pagination_has_more_flag(self):
        token = frappe.generate_hash()[:8]
        names = []
        for i in range(3):
            m = self.create_test_member(
                first_name="Page", last_name=f"M{i}{token}", email=f"page.{i}.{token}@example.com"
            )
            frappe.db.set_value("Member", m.name, "mollie_customer_id", f"cst_pg_{token}_{i}")
            names.append(m.name)

        # Request a small page; there are at least 3 matching members site-wide,
        # so has_more must be True when limit is below the total.
        data = BulkPaymentChecker.get_members_with_mollie_customers(None, limit=1)
        self.assertEqual(data["count"], 1)
        self.assertTrue(data["has_more"])


class TestBatchCheckAlreadyProcessed(EnhancedTestCase):
    """BulkPaymentChecker._batch_check_already_processed — real Bank Transaction lookup."""

    def _bank_account(self):
        return _ensure_bank_account(self)

    def test_empty_input_returns_empty(self):
        self.assertEqual(BulkPaymentChecker._batch_check_already_processed([]), [])

    def test_unprocessed_ids_pass_through(self):
        token = frappe.generate_hash()[:10]
        ids = [f"tr_unproc_{token}_{i}" for i in range(3)]
        result = BulkPaymentChecker._batch_check_already_processed(ids)
        # None of these references exist anywhere -> all returned as unprocessed
        self.assertEqual(set(result), set(ids))

    def test_processed_id_is_filtered_out(self):
        token = frappe.generate_hash()[:10]
        ba = self._bank_account()
        if not ba:
            self.skipTest("No Bank Account configured on this site")

        processed_id = f"tr_proc_{token}"
        unprocessed_id = f"tr_unproc_{token}"

        _create_bank_transaction(self, ba, processed_id)

        result = BulkPaymentChecker._batch_check_already_processed([processed_id, unprocessed_id])
        self.assertNotIn(processed_id, result)
        self.assertIn(unprocessed_id, result)


class TestGetProcessingStatus(EnhancedTestCase):
    """MolliePaymentOrchestrator.get_processing_status — document-state probe."""

    def _bank_account(self):
        return _ensure_bank_account(self)

    def test_unprocessed_payment(self):
        token = frappe.generate_hash()[:10]
        payment_id = f"tr_status_none_{token}"

        # Call as unbound method: get_processing_status uses only frappe.db /
        # frappe.get_doc and no instance attributes, so no MollieClient needed.
        status = MolliePaymentOrchestrator.get_processing_status(None, payment_id)

        self.assertEqual(status.payment_id, payment_id)
        self.assertEqual(status.status, "unprocessed")
        self.assertFalse(status.has_bank_transaction)
        self.assertFalse(status.has_payment_entry)
        self.assertIn("Bank Transaction", status.missing_documents)
        self.assertFalse(status.is_complete)

    def test_bank_transaction_only_is_partial_and_resolves_member(self):
        token = frappe.generate_hash()[:10]
        ba = self._bank_account()
        if not ba:
            self.skipTest("No Bank Account configured on this site")

        payment_id = f"tr_status_bt_{token}"

        # Create a member (auto-creates a Customer) and a Bank Transaction
        # referencing that payment and party = the member's Customer.
        member = self.create_test_member(
            first_name="Status", last_name=f"BT{token}", email=f"status.bt.{token}@example.com"
        )
        customer = frappe.db.get_value("Member", member.name, "customer")
        self.assertTrue(customer, "Member should have an auto-created Customer")

        bt_name = _create_bank_transaction(self, ba, payment_id, party_type="Customer", party=customer)

        status = MolliePaymentOrchestrator.get_processing_status(None, payment_id)

        self.assertTrue(status.has_bank_transaction)
        self.assertEqual(status.bank_transaction, bt_name)
        self.assertFalse(status.has_payment_entry)
        self.assertEqual(status.status, "partial")
        self.assertIn("Payment Entry", status.missing_documents)
        # Member should be resolved from the BT's Customer party
        self.assertEqual(status.member, member.name)
        self.assertFalse(status.is_complete)

    def _invoice_on_the_calculated_window(self, member, customer, amount):
        """A submitted, outstanding invoice on the window this member's payment maps to.

        The window is ASKED of the production calculator rather than hard-coded: whether
        it is the calendar period depends on the member's own coverage sequence, which is
        a property of the fixture, not of the code under test.
        """
        from verenigingen.services.billing.coverage_calculator import (
            calculate_coverage_for_payment_date,
        )

        start, end = calculate_coverage_for_payment_date(member.name, frappe.utils.today())
        invoice = self.create_test_sales_invoice(
            customer=customer,
            grand_total=amount,
            company=frappe.db.get_value("Bank Account", self._bank_account(), "company"),
            is_membership_invoice=1,
        )
        invoice.db_set("custom_coverage_start_date", frappe.utils.getdate(start))
        invoice.db_set("custom_coverage_end_date", frappe.utils.getdate(end))
        invoice.reload()
        return invoice

    def test_one_unlinked_invoice_on_the_coverage_window_is_resolved(self):
        """The working case for the coverage branch, pinned before the refusal below."""
        token = frappe.generate_hash()[:10]
        ba = self._bank_account()
        if not ba:
            self.skipTest("No Bank Account configured on this site")
        payment_id = f"tr_cov_one_{token}"

        # The SHARED helper, not a twelfth private copy of it: `_member_with_customer`
        # already has ten, and the duplicate-helper ratchet caught the eleventh.
        member = member_with_customer(self, f"Cov{token}")
        customer = frappe.db.get_value("Member", member.name, "customer")
        self.assertTrue(customer, "Member should have an auto-created Customer")
        _create_bank_transaction(self, ba, payment_id, party_type="Customer", party=customer)
        invoice = self._invoice_on_the_calculated_window(member, customer, 25.0)

        status = MolliePaymentOrchestrator.get_processing_status(None, payment_id)

        self.assertTrue(status.has_sales_invoice)
        self.assertEqual(status.sales_invoice, invoice.name)

    def test_two_invoices_on_the_coverage_window_are_refused(self):
        """#578 item 2. This status is not read-only: `_resolve_invoice` returns
        `status.sales_invoice` straight to `_create_payment_entry_for_dues`, so the
        invoice named here is the one the money lands on.

        The pick was `frappe.db.get_value` with no `order_by`, i.e. `creation DESC` --
        the most recently created of however many invoices share the window. Both
        invoices carry the Bank Transaction's own amount, which is the ordinary flat-fee
        case and exactly the one where the amount can separate nothing.
        """
        self.expectErrorLog("Mollie Payment Status Invoice Ambiguous")
        token = frappe.generate_hash()[:10]
        ba = self._bank_account()
        if not ba:
            self.skipTest("No Bank Account configured on this site")
        payment_id = f"tr_cov_two_{token}"

        # The SHARED helper, not a twelfth private copy of it: `_member_with_customer`
        # already has ten, and the duplicate-helper ratchet caught the eleventh.
        member = member_with_customer(self, f"Cov{token}")
        customer = frappe.db.get_value("Member", member.name, "customer")
        self.assertTrue(customer, "Member should have an auto-created Customer")
        _create_bank_transaction(self, ba, payment_id, party_type="Customer", party=customer)
        first = self._invoice_on_the_calculated_window(member, customer, 25.0)
        second = self._invoice_on_the_calculated_window(member, customer, 25.0)

        status = MolliePaymentOrchestrator.get_processing_status(None, payment_id)

        self.assertFalse(
            status.has_sales_invoice,
            f"two invoices share this coverage window; got {status.sales_invoice}",
        )
        self.assertNotIn(status.sales_invoice, (first.name, second.name))
        assert_error_log(
            self,
            "Mollie Payment Status Invoice Ambiguous",
            customer,
            must_contain=(customer, payment_id, first.name, second.name),
        )
