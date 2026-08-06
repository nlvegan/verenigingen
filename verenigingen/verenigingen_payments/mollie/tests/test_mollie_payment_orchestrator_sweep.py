"""
Coverage sweep for the orphan-handling branches of MolliePaymentOrchestrator.

verenigingen/verenigingen_payments/services/mollie_payment_orchestrator.py

These complement the existing *_unit and *_db_integration modules (which cover
the precondition gates, the happy-path process_payment flow, and
get_processing_status). The branches targeted here are the *fallback* paths that
fire when a Mollie payment cannot be matched to a member:

  - _find_or_create_customer_from_mollie  (create-from-Mollie-data path, DB)
  - _get_or_create_orphan_customer        (fallback customer get-or-create, DB)
  - _create_orphan_invoice                (orphan Sales Invoice, DB, EUR company)
  - _create_orphan_bank_transaction       (party/description wiring)
  - _create_orphan_payment_entry          (error path)
  - process_orphaned_payment              (customer-linked success branch)
  - process_orphaned_payment_with_invoice (full SI+PE+BT orchestration sequence)

The only thing faked is the external boundary: the Mollie SDK client / customer
objects and (for the orchestration-sequencing tests) the orchestrator's own
already-tested DB-writing helpers, mirroring how
test_mollie_payment_orchestrator_flow_unit fakes find_matching_invoice to drive
process_payment. DB-backed tests use the Enhanced Test Factory against real
DocTypes (no mocks).
"""

import unittest
from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import (
    ensure_membership_dues_item,
    get_eur_test_company,
)
from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
    MolliePaymentOrchestrator,
    PaymentProcessingResult,
    ProcessingStatus,
)


# ---------------------------------------------------------------------------
# Boundary stubs (the external Mollie SDK surface only).
# ---------------------------------------------------------------------------
class _StubAmount:
    def __init__(self, value="25.00", currency="EUR"):
        self.value = value
        self.currency = currency


def _paid_payment(**kw):
    """A Mollie-shaped paid payment stand-in carrying a real amount dict."""
    kw.setdefault("amount", {"value": "25.00", "currency": "EUR"})
    kw.setdefault("id", "tr_sweep")
    kw.setdefault("status", "paid")
    kw.setdefault("description", "Membership renewal")
    kw.setdefault("paid_at", "2026-01-15T10:00:00+00:00")
    return SimpleNamespace(**kw)


class _FakeMollieClient:
    """Stands in for MollieClient: only the customers.get / get_payment surface."""

    def __init__(self, customer=None, payment=None):
        self._customer = customer
        self._payment = payment
        self.sdk_client = SimpleNamespace(
            customers=SimpleNamespace(get=lambda cid: self._customer),
            payments=SimpleNamespace(get=lambda pid: self._payment),
        )

    def get_payment(self, payment_id):
        return self._payment


class _FakeBTCreator:
    def __init__(self, bt_name="BT-FAKE", config=None):
        self.bt_name = bt_name
        self._config = config or {"bank_account": "Mollie", "company": "Test Co"}
        self.create_calls = []
        self.linked = []
        self.link_result = True

    def get_mollie_bank_account_config(self):
        return self._config

    def create_from_mollie_payment(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.bt_name

    def link_payment_entry(self, bt_name, pe_name):
        self.linked.append((bt_name, pe_name))
        return self.link_result


def _bare_orchestrator(*, mollie=None, bt=None):
    """Build an orchestrator with __init__ bypassed and boundary fakes attached."""
    orch = object.__new__(MolliePaymentOrchestrator)
    orch.mollie_client = mollie or _FakeMollieClient()
    orch.bt_creator = bt or _FakeBTCreator()
    orch._bank_config_cache = None
    return orch


# ===========================================================================
# _find_or_create_customer_from_mollie  (create-from-Mollie-data path)
# ===========================================================================
class TestFindOrCreateCustomerFromMollieCreate(EnhancedTestCase):
    """Exercises the real Customer-creation branch (DB) of the resolver."""

    def test_create_path_uses_mollie_name_with_orphaned_suffix(self):
        token = frappe.generate_hash()[:10]
        cid = f"cst_{token}"
        # Mollie customer with a name and no email. Real Customer gets created here.
        # (The email-present path is covered by test_email_present_still_creates_customer.)
        mollie_customer = SimpleNamespace(name="Jane Sweep", email=None)
        orch = _bare_orchestrator(mollie=_FakeMollieClient(customer=mollie_customer))
        result = PaymentProcessingResult(payment_id="tr_1")

        customer_name = orch._find_or_create_customer_from_mollie(cid, _paid_payment(), result)

        self.assertTrue(customer_name, "Resolver should return a created Customer name")
        # The new Customer carries the Mollie id and the '(Orphaned)' marker.
        self.assertEqual(frappe.db.get_value("Customer", customer_name, "custom_mollie_customer_id"), cid)
        self.assertEqual(
            frappe.db.get_value("Customer", customer_name, "customer_name"), "Jane Sweep (Orphaned)"
        )
        self.assertEqual(frappe.db.get_value("Customer", customer_name, "customer_type"), "Individual")
        self.assertTrue(any("Created Customer" in a for a in result.actions_taken))

    def test_create_path_no_name_no_email_falls_back_to_customer_id_label(self):
        token = frappe.generate_hash()[:10]
        cid = f"cst_{token}"
        mollie_customer = SimpleNamespace(name=None, email=None)
        orch = _bare_orchestrator(mollie=_FakeMollieClient(customer=mollie_customer))
        result = PaymentProcessingResult(payment_id="tr_1")

        customer_name = orch._find_or_create_customer_from_mollie(cid, _paid_payment(), result)

        self.assertTrue(customer_name)
        # Name falls back to "Mollie Customer <id>" then gets the (Orphaned) suffix.
        self.assertEqual(
            frappe.db.get_value("Customer", customer_name, "customer_name"),
            f"Mollie Customer {cid} (Orphaned)",
        )

    def test_existing_customer_with_mollie_id_short_circuits_creation(self):
        token = frappe.generate_hash()[:10]
        cid = f"cst_{token}"
        existing = self._make_customer_with_mollie_id(f"Pre Existing {token}", cid)
        # mollie_customer is set but should never be consulted: the DB lookup wins.
        orch = _bare_orchestrator(
            mollie=_FakeMollieClient(customer=SimpleNamespace(name="Should Not Use", email=None))
        )
        result = PaymentProcessingResult(payment_id="tr_1")

        out = orch._find_or_create_customer_from_mollie(cid, _paid_payment(), result)

        self.assertEqual(out, existing)
        self.assertTrue(any("Found existing Customer" in a for a in result.actions_taken))

    def test_duplicate_name_collision_is_handled_without_raising_to_caller(self):
        # A different Customer already owns the computed "(Orphaned)" name but with
        # a different (no) Mollie id. The initial id-lookup misses, insert raises
        # DuplicateEntryError, the re-lookup by id still misses, so the resolver
        # swallows it and reports a warning (returns None) rather than exploding.
        token = frappe.generate_hash()[:10]
        cid = f"cst_{token}"
        clash_label = f"Clash {token}"
        self._make_customer_plain(f"{clash_label} (Orphaned)")

        mollie_customer = SimpleNamespace(name=clash_label, email=None)
        orch = _bare_orchestrator(mollie=_FakeMollieClient(customer=mollie_customer))
        result = PaymentProcessingResult(payment_id="tr_1")

        out = orch._find_or_create_customer_from_mollie(cid, _paid_payment(), result)

        self.assertIsNone(out)
        # No customer with OUR mollie id was created.
        self.assertIsNone(frappe.db.get_value("Customer", {"custom_mollie_customer_id": cid}, "name"))
        self.assertTrue(any("Could not create Customer" in a for a in result.actions_taken))

    def test_email_present_still_creates_customer(self):
        # Regression guard for a fixed bug: mollie_payment_orchestrator.py:1390
        # used to append to a non-existent child table `email_ids` on Customer, so
        # any Mollie customer that HAD an email raised AttributeError, got swallowed
        # by the outer except, and NO Customer was created -> the orphaned Bank
        # Transaction was left unlinked. Fixed by dropping the bogus email attach;
        # a Customer must now be created (email is non-fatal / stored on Mollie).
        token = frappe.generate_hash()[:10]
        cid = f"cst_{token}"
        mollie_customer = SimpleNamespace(name="Eve Mailer", email="eve@example.com")
        orch = _bare_orchestrator(mollie=_FakeMollieClient(customer=mollie_customer))
        result = PaymentProcessingResult(payment_id="tr_1")

        out = orch._find_or_create_customer_from_mollie(cid, _paid_payment(), result)

        self.assertTrue(out, "A Customer should be created even when the Mollie customer has an email")
        self.assertEqual(frappe.db.get_value("Customer", {"custom_mollie_customer_id": cid}, "name"), out)

    # --- factory helpers (permission-bypass allowed: _make_/setUp pattern) ---
    def _make_customer_with_mollie_id(self, name, mollie_id):
        cust = frappe.new_doc("Customer")
        cust.customer_name = name
        cust.customer_type = "Individual"
        cust.custom_mollie_customer_id = mollie_id
        cust.insert(ignore_permissions=True)
        self.factory.track_document("Customer", cust.name)
        return cust.name

    def _make_customer_plain(self, name):
        cust = frappe.new_doc("Customer")
        cust.customer_name = name
        cust.customer_type = "Individual"
        cust.insert(ignore_permissions=True)
        self.factory.track_document("Customer", cust.name)
        return cust.name


# ===========================================================================
# _get_or_create_orphan_customer
# ===========================================================================
class TestGetOrCreateOrphanCustomer(EnhancedTestCase):
    """The fixed fallback "Orphaned Mollie Payments" customer (DB get-or-create)."""

    def test_get_or_create_returns_named_customer_with_review_note(self):
        orch = _bare_orchestrator()
        name = orch._get_or_create_orphan_customer()

        self.assertTrue(name)
        self.assertEqual(frappe.db.get_value("Customer", name, "customer_name"), "Orphaned Mollie Payments")
        self.assertEqual(frappe.db.get_value("Customer", name, "customer_type"), "Individual")
        details = frappe.db.get_value("Customer", name, "customer_details") or ""
        self.assertIn("AUTO-CREATED", details)

    def test_is_idempotent_across_calls(self):
        orch = _bare_orchestrator()
        first = orch._get_or_create_orphan_customer()
        second = orch._get_or_create_orphan_customer()
        self.assertEqual(first, second)


# ===========================================================================
# _create_orphan_invoice  (real Sales Invoice under a EUR company)
# ===========================================================================
class TestCreateOrphanInvoice(EnhancedTestCase):
    """Real orphan Sales Invoice creation against the app's EUR test company."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # EUR company with a current Fiscal Year + a valid Chart of Accounts, and
        # a membership-dues Item the orphan-invoice item lookup can resolve.
        cls.company = get_eur_test_company()
        ensure_membership_dues_item("Daily")
        cls.income = frappe.db.get_value(
            "Account",
            {"company": cls.company, "account_type": "Income Account", "is_group": 0},
            "name",
        )
        if cls.income and not frappe.db.get_value("Company", cls.company, "default_income_account"):
            frappe.db.set_value("Company", cls.company, "default_income_account", cls.income)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        # Point the orchestrator's settings.company at the EUR company for the
        # duration of this test; restored in tearDown (no commit -> rolled back too).
        self._orig_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", self.company)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")
        # The orphan invoice prefers Payments Settings.dues_income_account; on this
        # site it points at a different company's account, which ERPNext rejects.
        # Align it with the EUR company so the income account belongs to the company.
        self._orig_income = frappe.db.get_single_value(
            "Verenigingen Payments Settings", "dues_income_account"
        )
        frappe.db.set_single_value("Verenigingen Payments Settings", "dues_income_account", self.income)
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")

    def tearDown(self):
        frappe.db.set_single_value("Verenigingen Settings", "company", self._orig_company)
        frappe.db.set_single_value("Verenigingen Payments Settings", "dues_income_account", self._orig_income)
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")
        frappe.clear_document_cache("Verenigingen Payments Settings", "Verenigingen Payments Settings")
        super().tearDown()

    def test_creates_submitted_orphan_invoice_with_warning_remarks(self):
        orch = _bare_orchestrator()
        customer = orch._get_or_create_orphan_customer()
        payment_id = f"tr_inv_{frappe.generate_hash()[:8]}"

        invoice_name = orch._create_orphan_invoice(
            payment_id=payment_id,
            customer=customer,
            amount=25.0,
            payment_date=frappe.utils.today(),
            payment_description="Some Mollie payment",
        )

        self.assertTrue(invoice_name, "Orphan invoice should be created")
        si = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(si.docstatus, 1, "Orphan invoice should be submitted")
        self.assertEqual(si.customer, customer)
        self.assertEqual(si.is_membership_invoice, 1)
        self.assertIn("ORPHANED PAYMENT", si.remarks)
        self.assertIn(payment_id, si.remarks)
        # The single line carries the payment amount.
        self.assertEqual(len(si.items), 1)
        self.assertEqual(si.items[0].rate, 25.0)


# ===========================================================================
# _create_orphan_bank_transaction  (party/description wiring)
# ===========================================================================
class TestCreateOrphanBankTransaction(unittest.TestCase):
    def test_links_party_to_orphan_customer_with_orphan_description(self):
        bt = _FakeBTCreator(bt_name="BT-ORPH")
        orch = _bare_orchestrator(bt=bt)
        out = orch._create_orphan_bank_transaction(payment=_paid_payment(), customer="CUST-ORPHAN")

        self.assertEqual(out, "BT-ORPH")
        call = bt.create_calls[0]
        self.assertEqual(call["party_type"], "Customer")
        self.assertEqual(call["party"], "CUST-ORPHAN")
        self.assertIn("ORPHANED", call["additional_description"])

    def test_config_error_returns_none_without_creating(self):
        bt = _FakeBTCreator(config={"error": "no clearing account"})
        orch = _bare_orchestrator(bt=bt)
        out = orch._create_orphan_bank_transaction(payment=_paid_payment(), customer="CUST-ORPHAN")
        self.assertIsNone(out)
        self.assertEqual(bt.create_calls, [])


# ===========================================================================
# _create_orphan_payment_entry  (error path)
# ===========================================================================
class TestCreateOrphanPaymentEntryErrorPath(unittest.TestCase):
    def test_invalid_invoice_returns_none(self):
        orch = _bare_orchestrator()
        out = orch._create_orphan_payment_entry(
            payment_id="tr_x",
            customer="CUST-ORPHAN",
            invoice_name="SINV-DOES-NOT-EXIST",
            amount=25.0,
            payment_date=frappe.utils.today(),
        )
        self.assertIsNone(out)


# ===========================================================================
# process_orphaned_payment  (customer-linked success branch)
# ===========================================================================
class TestProcessOrphanedPaymentCustomerLinked(unittest.TestCase):
    def test_creates_bt_linked_to_resolved_customer(self):
        bt = _FakeBTCreator(bt_name="BT-LINKED")
        orch = _bare_orchestrator(bt=bt)
        # Boundary: no existing BT; customer resolved from Mollie data.
        original = frappe.db.get_value
        frappe.db.get_value = lambda *a, **k: None
        orch._find_or_create_customer_from_mollie = lambda cid, payment, result: "CUST-RESOLVED"
        try:
            out = orch.process_orphaned_payment("tr_1", payment=_paid_payment(customer_id="cst_9"))
        finally:
            frappe.db.get_value = original

        self.assertEqual(out.status, "success")
        self.assertEqual(out.bank_transaction, "BT-LINKED")
        self.assertEqual(bt.create_calls[0]["party"], "CUST-RESOLVED")
        self.assertEqual(bt.create_calls[0]["party_type"], "Customer")
        self.assertTrue(any("Linked to Customer: CUST-RESOLVED" in a for a in out.actions_taken))


# ===========================================================================
# process_orphaned_payment_with_invoice  (orchestration sequencing)
# ===========================================================================
class TestProcessOrphanedPaymentWithInvoice(unittest.TestCase):
    """Drives the SI->BT->PE->link sequence; the already-tested DB-writing
    helpers are faked, mirroring how the flow_unit module fakes find_matching_invoice."""

    def _orch_with_helpers(
        self,
        *,
        payment=None,
        orphan_customer="CUST-ORPHAN",
        invoice="SINV-1",
        bt="BT-1",
        pe="PE-1",
        existing_bt=None,
        existing_pe=None,
        existing_si=None,
        created_invoices=None,
        link_ok=True,
    ):
        orch = _bare_orchestrator(mollie=_FakeMollieClient(payment=payment))
        orch._get_or_create_orphan_customer = lambda: orphan_customer

        def _create_invoice(**kw):
            if created_invoices is not None:
                created_invoices.append(kw)
            return invoice

        orch._create_orphan_invoice = _create_invoice
        orch.get_processing_status = lambda pid: ProcessingStatus(
            payment_id=pid,
            has_bank_transaction=bool(existing_bt),
            bank_transaction=existing_bt,
            has_payment_entry=bool(existing_pe),
            payment_entry=existing_pe,
            has_sales_invoice=bool(existing_si),
            sales_invoice=existing_si,
        )
        orch._create_orphan_bank_transaction = lambda **kw: bt
        orch._create_orphan_payment_entry = lambda **kw: pe
        orch._link_bt_to_pe = lambda b, p: link_ok
        return orch

    def test_existing_payment_entry_short_circuits_without_creating_duplicates(self):
        """A redelivered webhook must not produce a second invoice and payment entry.

        Mollie retries a webhook until it gets a 2xx, and this path used to check
        nothing before writing: the other three gateway paths all guard (Mollie dues via
        UnifiedIdempotencyManager.payment_entry_exists, Ponto on reference_no, ING on
        transaction status), this one did not. get_processing_status() already reported
        has_payment_entry; the function simply never asked.
        """
        created = []
        orch = self._orch_with_helpers(
            payment=_paid_payment(),
            existing_pe="PE-ALREADY",
            existing_si="SINV-ALREADY",
            created_invoices=created,
        )
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment())

        self.assertEqual(out.status, "skipped")
        self.assertEqual(out.payment_entry, "PE-ALREADY")
        self.assertEqual(out.sales_invoice, "SINV-ALREADY")
        self.assertEqual(created, [], "no second orphan invoice may be created")

    def test_existing_invoice_is_reused_rather_than_duplicated(self):
        """A run that created the invoice then died must not create a second one.

        Without this, every retry of a partially-completed orphan payment left another
        orphan Sales Invoice behind.
        """
        created = []
        orch = self._orch_with_helpers(
            payment=_paid_payment(),
            existing_si="SINV-FROM-EARLIER-RUN",
            created_invoices=created,
        )
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment())

        self.assertEqual(out.sales_invoice, "SINV-FROM-EARLIER-RUN")
        self.assertEqual(created, [], "the existing invoice must be reused")
        self.assertTrue(any("Reusing existing" in a for a in out.actions_taken))

    def test_payment_not_found_is_error(self):
        orch = self._orch_with_helpers(payment=None)
        out = orch.process_orphaned_payment_with_invoice("tr_missing")
        self.assertEqual(out.status, "error")
        self.assertIn("not found", out.error)

    def test_unpaid_payment_is_skipped(self):
        orch = self._orch_with_helpers(payment=_paid_payment(status="open"))
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment(status="open"))
        self.assertEqual(out.status, "skipped")

    def test_orphan_customer_failure_is_error(self):
        orch = self._orch_with_helpers(payment=_paid_payment(), orphan_customer=None)
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment())
        self.assertEqual(out.status, "error")
        self.assertIn("orphan payments customer", out.error)

    def test_invoice_failure_is_error(self):
        orch = self._orch_with_helpers(payment=_paid_payment(), invoice=None)
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment())
        self.assertEqual(out.status, "error")
        self.assertIn("Failed to create orphan invoice", out.error)

    def test_payment_entry_failure_is_partial(self):
        orch = self._orch_with_helpers(payment=_paid_payment(), pe=None)
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment())
        self.assertEqual(out.status, "partial")
        self.assertEqual(out.sales_invoice, "SINV-1")
        self.assertIn("failed to create Payment Entry", out.error)

    def test_full_success_creates_si_bt_pe_and_links(self):
        orch = self._orch_with_helpers(payment=_paid_payment())
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment())
        self.assertEqual(out.status, "success")
        self.assertEqual(out.sales_invoice, "SINV-1")
        self.assertEqual(out.bank_transaction, "BT-1")
        self.assertEqual(out.payment_entry, "PE-1")
        self.assertTrue(any("Linked BT BT-1 to PE PE-1" in a for a in out.actions_taken))
        self.assertTrue(any("requires manual review" in a for a in out.actions_taken))

    def test_existing_bank_transaction_is_reused(self):
        orch = self._orch_with_helpers(payment=_paid_payment(), existing_bt="BT-PRE")
        out = orch.process_orphaned_payment_with_invoice("tr_1", payment=_paid_payment())
        self.assertEqual(out.status, "success")
        self.assertEqual(out.bank_transaction, "BT-PRE")
        self.assertTrue(any("Bank Transaction exists: BT-PRE" in a for a in out.actions_taken))


if __name__ == "__main__":
    unittest.main()
