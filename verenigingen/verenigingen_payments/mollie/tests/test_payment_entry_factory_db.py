"""
Payment Entry Factory DB Integration Tests
==========================================

End-to-end / database-level tests for the LIVE shared PaymentEntryFactory
(services/shared/payment_entry_factory.py). The existing
``test_payment_entry_factory.py`` covers pure-unit validation/sanitization and
the orphan-cleanup unit path; this module covers the parts that need real
accounts/parties:

  - create_payment_entry full flow for a membership (real Member + Customer)
  - create_payment_entry resolves a customer from context when not provided
  - create_payment_entry is idempotent (existing PE -> returns None)
  - _get_accounts resolution (donation vs membership receivable; Mollie bank
    account via the named-account fallback)
  - _resolve_customer_for_context for donation (donor.customer) and membership
  - _create_customer_for_member creates + links a Customer
  - _generate_payment_title / _extract_record_reference / _generate_remarks
  - the idempotency lock acquire/release helpers (real Redis-backed lock)

No mocks of the logic under test. The Mollie SDK boundary is never touched here
because the factory does not call Mollie; it only reads mollie_data dicts.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
    PaymentEntryFactory,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
    customer_for_member,
    ensure_mollie_bank_gl_account,
    ensure_mollie_mode_of_payment,
    get_test_company,
)


class TestPaymentEntryFactoryDB(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.pe_factory = PaymentEntryFactory()
        self.company = get_test_company()
        # Ensure master data the factory needs to actually build a PE.
        self.mollie_account = ensure_mollie_bank_gl_account(self.company)
        ensure_mollie_mode_of_payment()

    def _mollie_data(self, payment_id, amount="42.50", **extra):
        data = {
            "payment_id": payment_id,
            "amount": amount,
            "method": "ideal",
            "paid_at": "2025-02-10T09:00:00+00:00",
        }
        data.update(extra)
        return data

    # ----- _get_accounts -------------------------------------------------

    def test_get_accounts_membership_uses_company_receivable_and_mollie_bank(self):
        accounts = self.pe_factory._get_accounts(self.company, "membership")
        self.assertEqual(
            accounts["receivable_account"],
            frappe.db.get_value("Company", self.company, "default_receivable_account"),
        )
        # Mollie bank account resolves via the named-"Mollie" account fallback.
        self.assertEqual(accounts["bank_account"], self.mollie_account)

    def test_get_accounts_donation_prefers_settings_receivable(self):
        # When donation_receivable_account is configured it must be preferred.
        configured = frappe.db.get_value("Company", self.company, "default_receivable_account")
        frappe.db.set_single_value("Verenigingen Settings", "donation_receivable_account", configured)
        accounts = self.pe_factory._get_accounts(self.company, "donation")
        self.assertEqual(accounts["receivable_account"], configured)

    # ----- title / remarks generation -----------------------------------

    def test_extract_record_reference_prefers_metadata(self):
        context = PaymentContext("membership", "Member", "MEM-FALLBACK")
        ref = self.pe_factory._extract_record_reference({"metadata": {"record_id": "REC-FROM-META"}}, context)
        self.assertEqual(ref, "REC-FROM-META")

    def test_extract_record_reference_from_description_json(self):
        context = PaymentContext("membership", "Member", "MEM-FALLBACK")
        ref = self.pe_factory._extract_record_reference(
            {"description": '{"record_id": "REC-FROM-DESC"}'}, context
        )
        self.assertEqual(ref, "REC-FROM-DESC")

    def test_extract_record_reference_falls_back_to_target_name(self):
        context = PaymentContext("membership", "Member", "MEM-TARGET")
        ref = self.pe_factory._extract_record_reference({"description": "not-json"}, context)
        self.assertEqual(ref, "MEM-TARGET")

    def test_generate_remarks_includes_type_and_method(self):
        context = PaymentContext("membership", "Member", "MEM-1")
        remarks = self.pe_factory._generate_remarks(context, {"method": "ideal"})
        self.assertIn("Membership", remarks)
        self.assertIn("MEM-1", remarks)
        self.assertIn("ideal", remarks)

    def test_generate_payment_title_uses_customer_name(self):
        member = self.create_test_member(
            first_name="Title", last_name="Probe", email="title.probe@example.com"
        )
        customer = customer_for_member(member)
        context = PaymentContext("membership", "Member", member.name)
        title = self.pe_factory._generate_payment_title(
            context, {"metadata": {"record_id": "INV-9"}}, customer
        )
        customer_name = frappe.db.get_value("Customer", customer, "customer_name")
        self.assertIn(customer_name, title)
        self.assertIn("INV-9", title)

    # ----- _resolve_customer_for_context ---------------------------------

    def test_resolve_customer_for_membership_returns_linked_customer(self):
        member = self.create_test_member(
            first_name="Resolve", last_name="Member", email="resolve.member@example.com"
        )
        customer = customer_for_member(member)
        context = PaymentContext("membership", "Member", member.name)
        resolved = self.pe_factory._resolve_customer_for_context(context)
        self.assertEqual(resolved, customer)

    def test_resolve_customer_for_membership_creates_when_missing(self):
        member = self.create_test_member(
            first_name="Create", last_name="Cust", email="create.cust@example.com"
        )
        # Member.after_insert auto-links a Customer; unlink it to drive the
        # factory's _create_customer_for_member path (it should re-link the
        # existing member-linked Customer rather than create a duplicate).
        existing_customer = frappe.db.get_value("Member", member.name, "customer")
        self.assertTrue(existing_customer)
        frappe.db.set_value("Member", member.name, "customer", None)
        member.reload()

        context = PaymentContext("membership", "Member", member.name)
        resolved = self.pe_factory._resolve_customer_for_context(context)
        self.assertTrue(resolved, "factory must re-link/create a Customer for the member")
        # The customer must be linked back to the member after resolution.
        self.assertEqual(frappe.db.get_value("Member", member.name, "customer"), resolved)
        self.assertEqual(frappe.db.get_value("Customer", resolved, "member"), member.name)
        # It must re-use the existing member-linked Customer, not create a duplicate.
        self.assertEqual(resolved, existing_customer)

    def test_resolve_customer_for_donation_uses_donor_customer(self):
        member = self.create_test_member(
            first_name="DonorLink", last_name="Test", email="donorlink.test@example.com"
        )
        customer = customer_for_member(member)
        donor = self.create_test_donor(donor_email="resolve.donor@example.com")
        frappe.db.set_value("Donor", donor.name, "customer", customer)
        donation = self.create_test_donation(donor=donor.name, amount=30.0, paid=0)
        context = PaymentContext("donation", "Donation", donation.name)
        resolved = self.pe_factory._resolve_customer_for_context(context)
        self.assertEqual(resolved, customer)

    def test_resolve_customer_unknown_type_returns_none(self):
        context = PaymentContext("settlement", "Mollie Settlement", "stl_x")
        self.assertIsNone(self.pe_factory._resolve_customer_for_context(context))

    # ----- create_payment_entry (end to end) -----------------------------

    def test_create_payment_entry_membership_end_to_end(self):
        member = self.create_test_member(first_name="E2E", last_name="Member", email="e2e.member@example.com")
        customer = customer_for_member(member)
        context = PaymentContext("membership", "Member", member.name)
        payment_id = f"tr_e2e_member_{frappe.generate_hash()[:10]}"

        pe = self.pe_factory.create_payment_entry(
            context=context, mollie_data=self._mollie_data(payment_id, amount="42.50"), customer=customer
        )

        self.assertIsNotNone(pe, "Factory should create a Payment Entry against real accounts")
        self.assertEqual(pe.docstatus, 1, "PE should be submitted")
        self.assertEqual(pe.reference_no, payment_id)
        self.assertEqual(pe.party, customer)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertAlmostEqual(float(pe.paid_amount), 42.50, places=2)
        self.assertEqual(pe.paid_to, self.mollie_account)
        # reference_date AND posting_date come from the paid_at timestamp.
        # (posting_date is mandatory; the factory must set it explicitly.)
        self.assertEqual(str(pe.reference_date), "2025-02-10")
        self.assertEqual(str(pe.posting_date), "2025-02-10")

    def test_create_payment_entry_resolves_customer_when_not_provided(self):
        member = self.create_test_member(
            first_name="AutoResolve", last_name="Member", email="autoresolve.member@example.com"
        )
        customer = customer_for_member(member)
        context = PaymentContext("membership", "Member", member.name)
        payment_id = f"tr_autoresolve_{frappe.generate_hash()[:10]}"

        pe = self.pe_factory.create_payment_entry(context=context, mollie_data=self._mollie_data(payment_id))
        self.assertIsNotNone(pe)
        self.assertEqual(pe.party, customer)

    def test_create_payment_entry_is_idempotent(self):
        member = self.create_test_member(
            first_name="Idem", last_name="Member", email="idem.member@example.com"
        )
        customer = customer_for_member(member)
        context = PaymentContext("membership", "Member", member.name)
        payment_id = f"tr_idem_e2e_{frappe.generate_hash()[:10]}"

        first = self.pe_factory.create_payment_entry(
            context=context, mollie_data=self._mollie_data(payment_id), customer=customer
        )
        self.assertIsNotNone(first)

        # Second call with the same payment_id must be a no-op (returns None) and
        # must NOT create a duplicate Payment Entry.
        second = self.pe_factory.create_payment_entry(
            context=context, mollie_data=self._mollie_data(payment_id), customer=customer
        )
        self.assertIsNone(second)
        pe_count = frappe.db.count("Payment Entry", {"reference_no": payment_id, "docstatus": ["!=", 2]})
        self.assertEqual(pe_count, 1)

    def test_create_payment_entry_invalid_data_returns_none(self):
        context = PaymentContext("membership", "Member", "MEM-BAD")
        # Missing amount -> validation error -> None (not raised).
        pe = self.pe_factory.create_payment_entry(
            context=context, mollie_data={"payment_id": "tr_bad_data_xxxxxxxxxx"}
        )
        self.assertIsNone(pe)

    # ----- idempotency lock helpers --------------------------------------

    def test_idempotency_lock_acquire_then_reentry_blocked(self):
        payment_id = f"tr_lock_{frappe.generate_hash()[:10]}"
        acquired = self.pe_factory._acquire_idempotency_lock(payment_id)
        self.assertTrue(acquired)
        try:
            # A second acquisition of the same lock must fail while held.
            second = self.pe_factory._acquire_idempotency_lock(payment_id)
            self.assertFalse(second)
        finally:
            self.pe_factory._release_idempotency_lock(payment_id)

        # After release, the lock can be acquired again.
        re_acquired = self.pe_factory._acquire_idempotency_lock(payment_id)
        self.assertTrue(re_acquired)
        self.pe_factory._release_idempotency_lock(payment_id)

    def test_release_lock_with_empty_id_is_noop(self):
        # Should not raise.
        self.pe_factory._release_idempotency_lock("")

    def test_get_company_returns_configured_company(self):
        self.assertEqual(self.pe_factory._get_company(), self.company)
