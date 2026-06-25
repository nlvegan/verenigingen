"""
Coverage gap-fill for
verenigingen_payments/mollie/services/shared/payment_entry_factory.py

Complements test_mollie_shared_payment_entry_factory.py (which already covers
validation/sanitization/account-resolution/end-to-end create + duplicate
idempotency). This module targets the previously-uncovered branches:

- _acquire_idempotency_lock / _release_idempotency_lock: REAL Redis-backed
  distributed lock (acquire, re-acquire-while-held denial, release, empty-id noop).
- _payment_entry_exists: True for a real submitted PE, False for unknown id,
  ignores cancelled (docstatus 2) entries.
- create_payment_entry: the "could not acquire lock and PE already created by
  another worker" branch (lock held externally + PE exists -> returns None,
  idempotent) and the "lock held + no PE" branch (returns None).
- _generate_payment_title: real Customer display-name + record reference.

Real DB + real Redis throughout; no business-logic mocks.

Run:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_payment_entry_factory_coverage_b1
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
    PaymentEntryFactory,
)


def _ensure_mollie_named_account(company: str) -> str:
    """Ensure an Account named 'Mollie' exists so the bank-account fallback resolves."""
    existing = frappe.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
    if existing:
        return existing

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


class TestIdempotencyLockHelpers(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()
        self.payment_id = f"tr_lock_{frappe.generate_hash(length=10)}"
        # Defensive: ensure no stale lock from a prior run.
        self.pe_factory._release_idempotency_lock(self.payment_id)

    def tearDown(self):
        self.pe_factory._release_idempotency_lock(self.payment_id)
        super().tearDown()

    def test_acquire_then_held_then_release(self):
        with self.assertNoErrorLog():
            self.assertTrue(self.pe_factory._acquire_idempotency_lock(self.payment_id))
            # Second acquisition while the lock is held must fail.
            self.assertFalse(self.pe_factory._acquire_idempotency_lock(self.payment_id))
            self.pe_factory._release_idempotency_lock(self.payment_id)
            # After release the lock is free again.
            self.assertTrue(self.pe_factory._acquire_idempotency_lock(self.payment_id))

    def test_release_empty_id_is_noop(self):
        # Should not raise.
        self.assertIsNone(self.pe_factory._release_idempotency_lock(""))


class TestPaymentEntryExists(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()
        self.company = self.pe_factory._get_company()
        _ensure_mollie_named_account(self.company)
        self.member = self.create_test_member(
            first_name="Exists",
            last_name="Probe",
            email=f"exists.{frappe.generate_hash(length=6)}@example.com",
        )
        self.member.reload()
        self.customer = self.member.customer
        self.assertTrue(self.customer)

    def test_exists_false_for_unknown(self):
        self.assertFalse(self.pe_factory._payment_entry_exists(f"tr_unknown_{frappe.generate_hash(length=8)}"))

    def test_exists_true_for_real_submitted_pe(self):
        payment_id = f"tr_exists_{frappe.generate_hash(length=10)}"
        ctx = PaymentContext("membership", "Member", self.member.name)
        pe = self.pe_factory.create_payment_entry(
            ctx, {"payment_id": payment_id, "amount": "11.00"}, customer=self.customer
        )
        self.assertIsNotNone(pe)
        self.assertTrue(self.pe_factory._payment_entry_exists(payment_id))

    def test_exists_ignores_cancelled_pe(self):
        payment_id = f"tr_cancel_{frappe.generate_hash(length=10)}"
        ctx = PaymentContext("membership", "Member", self.member.name)
        pe = self.pe_factory.create_payment_entry(
            ctx, {"payment_id": payment_id, "amount": "13.00"}, customer=self.customer
        )
        self.assertIsNotNone(pe)
        # Cancel it -> docstatus 2 -> the exists check (docstatus != 2) should ignore it.
        doc = frappe.get_doc("Payment Entry", pe.name)
        doc.cancel()
        self.assertFalse(self.pe_factory._payment_entry_exists(payment_id))


class TestLockHeldByAnotherWorker(EnhancedTestCase):
    """Exercise create_payment_entry's 'lock not acquired' branches by holding the
    distributed lock externally before calling the factory."""

    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()
        self.company = self.pe_factory._get_company()
        _ensure_mollie_named_account(self.company)
        self.member = self.create_test_member(
            first_name="Locked",
            last_name="Worker",
            email=f"locked.{frappe.generate_hash(length=6)}@example.com",
        )
        self.member.reload()
        self.customer = self.member.customer
        self.ctx = PaymentContext("membership", "Member", self.member.name)
        self.held_ids = []

    def tearDown(self):
        from verenigingen.api.sepa_duplicate_prevention import release_processing_lock

        for pid in self.held_ids:
            release_processing_lock("payment_entry", pid)
        super().tearDown()

    def _hold_lock(self, payment_id):
        from verenigingen.api.sepa_duplicate_prevention import acquire_processing_lock

        self.assertTrue(acquire_processing_lock("payment_entry", payment_id, timeout=30))
        self.held_ids.append(payment_id)

    def test_lock_held_and_no_pe_returns_none(self):
        payment_id = f"tr_held_nope_{frappe.generate_hash(length=10)}"
        self._hold_lock(payment_id)
        # Factory cannot acquire the lock; after a short wait there is still no PE.
        result = self.pe_factory.create_payment_entry(
            self.ctx, {"payment_id": payment_id, "amount": "9.00"}, customer=self.customer
        )
        self.assertIsNone(result)
        self.assertFalse(self.pe_factory._payment_entry_exists(payment_id))

    def test_lock_held_but_pe_already_exists_returns_none(self):
        payment_id = f"tr_held_exists_{frappe.generate_hash(length=10)}"
        # First create a real PE (releases its own lock when done).
        pe = self.pe_factory.create_payment_entry(
            self.ctx, {"payment_id": payment_id, "amount": "8.00"}, customer=self.customer
        )
        self.assertIsNotNone(pe)
        # Now hold the lock externally and call again: the "created by another
        # worker" branch should detect the existing PE and return None.
        self._hold_lock(payment_id)
        result = self.pe_factory.create_payment_entry(
            self.ctx, {"payment_id": payment_id, "amount": "8.00"}, customer=self.customer
        )
        self.assertIsNone(result)
        # Still exactly one active PE.
        count = frappe.db.count("Payment Entry", {"reference_no": payment_id, "docstatus": ["!=", 2]})
        self.assertEqual(count, 1)


class TestGeneratePaymentTitle(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()
        self.member = self.create_test_member(
            first_name="Title",
            last_name="Gen",
            email=f"title.{frappe.generate_hash(length=6)}@example.com",
        )
        self.member.reload()
        self.customer = self.member.customer

    def test_title_uses_customer_name_and_metadata_reference(self):
        ctx = PaymentContext("membership", "Member", self.member.name)
        mollie_data = {"payment_id": "tr_x", "amount": "5.00", "metadata": {"record_id": "INV-9000"}}
        title = self.pe_factory._generate_payment_title(ctx, mollie_data, self.customer)
        customer_name = frappe.get_value("Customer", self.customer, "customer_name")
        self.assertIn(customer_name, title)
        self.assertIn("INV-9000", title)

    def test_title_falls_back_to_target_on_bad_customer(self):
        ctx = PaymentContext("membership", "Member", self.member.name)
        # Nonexistent customer -> get_doc raises inside -> fallback title.
        title = self.pe_factory._generate_payment_title(
            ctx, {"payment_id": "tr_y", "amount": "5.00"}, "Customer-Does-Not-Exist-B1"
        )
        self.assertIn(self.member.name, title)
