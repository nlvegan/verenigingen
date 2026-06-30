"""
Coverage sweep for
``verenigingen_payments/mollie/services/shared/payment_entry_factory.py``.

Complements the existing factory tests (tests/payment/test_mollie_shared_*
and *_coverage_b1) by exercising the previously-uncovered branches with REAL
DB integration (no business-logic mocks):

- end-to-end create for a membership and a donation, asserting real money
  direction (paid_from = receivable, paid_to = Mollie bank), company and
  cost_center on the submitted Payment Entry;
- early-return guards in ``create_payment_entry`` (unresolvable customer,
  invalid mollie_data);
- ``_resolve_customer_for_context`` donation paths (donor with a Customer,
  donor without a Customer -> creates one, and the exception/None path);
- ``_create_customer_for_member`` AND ``_create_customer_for_member_without_lock``:
  the double-check-after-lock hit, the "existing Customer linked via member"
  relink, and the fresh-creation path;
- ``_handle_orphan_cleanup`` success and cleanup-failure audit trails;
- ``_get_accounts`` donation-receivable-configured branch.

A "Mollie" Mode of Payment and a "Mollie" named bank Account are seeded so the
real create path resolves end to end (neither is an app fixture).

Run:
    bench --site veg11.veganisme.org run-tests --app verenigingen --module \\
      verenigingen.verenigingen_payments.mollie.services.shared.test_payment_entry_factory_coverage
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
    PaymentEntryFactory,
)


def _make_named_bank_account(company: str, account_name: str) -> str:
    """Module-scope fixture: a Bank-type Account with the given name (idempotent)."""
    existing = frappe.get_value("Account", {"company": company, "account_name": account_name}, "name")
    if existing:
        return existing

    parent = frappe.get_value("Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name")
    if not parent:
        parent = frappe.get_value("Account", {"company": company, "is_group": 1}, "name")

    acct = frappe.new_doc("Account")
    acct.account_name = account_name
    acct.company = company
    acct.parent_account = parent
    acct.account_type = "Bank"
    acct.account_currency = frappe.get_value("Company", company, "default_currency")
    acct.insert(ignore_permissions=True)
    return acct.name


def _ensure_mollie_named_account(company: str) -> str:
    """Ensure an Account named 'Mollie' exists so the bank-account fallback resolves."""
    return _make_named_bank_account(company, "Mollie")


class _FactoryBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.factory_obj = PaymentEntryFactory()
        self.company = self.factory_obj._get_company()
        _ensure_mollie_named_account(self.company)
        # "Mollie" Mode of Payment is required by create_payment_entry; not seeded
        # by the data factory, so create it here (survives 12-shard rebucketing).
        self.ensure_mode_of_payment("Mollie")
        self.ensure_mode_of_payment("Bank Transfer")
        self._ensure_valid_company_receivable()
        self._ensure_valid_mollie_bank_account()

    def _ensure_valid_mollie_bank_account(self):
        """Point Mollie Settings.mollie_bank_account at a company-valid Account.

        The factory now reads the configured Mollie bank account (via
        MollieConfigurationService -> Mollie Settings) verbatim instead of
        silently falling back. On long-lived sites that field references an
        Account belonging to a DIFFERENT company, so the real Payment Entry
        submit would fail with "does not belong to Company". Seed the company's
        own 'Mollie' Account here (rolled back at tearDown) and clear the
        in-memory config cache before and after each test so neither the seeded
        value nor a stale read leaks across tests.
        """
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            get_mollie_config,
        )

        mollie_account = _ensure_mollie_named_account(self.company)
        frappe.db.set_value("Mollie Settings", None, "mollie_bank_account", mollie_account)
        get_mollie_config().clear_cache()
        self.addCleanup(get_mollie_config().clear_cache)

    def _ensure_valid_company_receivable(self):
        """Point the company's default receivable account at a real Account.

        On some environments Company.default_receivable_account references a
        renamed/stale Account name that no longer exists, which makes the real
        Payment Entry insert fail with LinkValidationError. The factory trusts
        this configured name verbatim, so seed a valid one for the test
        transaction (rolled back at tearDown -- no commit).
        """
        current = frappe.get_value("Company", self.company, "default_receivable_account")
        if current and frappe.db.exists("Account", current):
            return
        valid = frappe.get_value(
            "Account",
            {"company": self.company, "account_type": "Receivable", "is_group": 0, "disabled": 0},
            "name",
        )
        if valid:
            frappe.db.set_value("Company", self.company, "default_receivable_account", valid)

    def _new_member_with_customer(self, first="Sweep"):
        member = self.create_test_member(
            first_name=first,
            last_name="Member",
            email=f"{first.lower()}.{frappe.generate_hash(length=8)}@example.com",
        )
        member.reload()
        self.assertTrue(member.customer, "Test member should auto-link a Customer")
        return member


class TestCreatePaymentEntryEndToEnd(_FactoryBase):
    def test_membership_payment_money_direction(self):
        member = self._new_member_with_customer("Mem")
        ctx = PaymentContext("membership", "Member", member.name)
        payment_id = f"tr_{frappe.generate_hash(length=12)}"
        pe = self.factory_obj.create_payment_entry(
            ctx,
            {
                "payment_id": payment_id,
                "amount": "42.00",
                "paid_at": "2025-04-01T10:00:00+00:00",
                "method": "ideal",
            },
            customer=member.customer,
        )
        self.assertIsNotNone(pe, "Factory must return a submitted Payment Entry")
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.payment_type, "Receive")
        self.assertEqual(pe.company, self.company)
        # Receive: money flows FROM the customer's receivable INTO the Mollie bank.
        self.assertEqual(
            pe.paid_from, frappe.get_value("Company", self.company, "default_receivable_account")
        )
        self.assertEqual(
            pe.paid_to,
            frappe.get_value("Account", {"company": self.company, "account_name": "Mollie"}, "name"),
        )
        self.assertTrue(pe.cost_center, "P&L/PE row must carry a cost center")
        self.assertEqual(float(pe.paid_amount), 42.00)
        self.assertEqual(pe.reference_no, payment_id)
        self.assertEqual(pe.reference_date.isoformat(), "2025-04-01")
        self.assertEqual(pe.posting_date.isoformat(), "2025-04-01")

    def test_donation_payment_resolves_company_receivable_fallback(self):
        # Donor WITH a customer so the donation create path resolves without
        # creating one; exercises the donation branch of _get_accounts (falls
        # back to company default receivable when donation_receivable_account unset).
        customer = self.factory.create_test_customer()
        donor = self.create_test_donor(donor_name="Sweep Donor", customer=customer.name)
        ctx = PaymentContext("donation", "Donor", donor.name)
        payment_id = f"tr_{frappe.generate_hash(length=12)}"
        pe = self.factory_obj.create_payment_entry(
            ctx, {"payment_id": payment_id, "amount": "15.50", "method": "creditcard"}, customer=customer.name
        )
        self.assertIsNotNone(pe)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.party, customer.name)
        self.assertEqual(
            pe.paid_from, frappe.get_value("Company", self.company, "default_receivable_account")
        )


class TestCreatePaymentEntryGuards(_FactoryBase):
    def test_unresolvable_customer_returns_none(self):
        # payment_type that _resolve_customer_for_context cannot map -> None.
        ctx = PaymentContext("subscription", "Member", "Nonexistent-Member-XYZ")
        result = self.factory_obj.create_payment_entry(
            ctx, {"payment_id": f"tr_{frappe.generate_hash(length=8)}", "amount": "5.00"}, customer=None
        )
        self.assertIsNone(result)

    def test_invalid_mollie_data_returns_none(self):
        self.expectErrorLog("Payment Entry Factory - Validation Error")
        member = self._new_member_with_customer("Bad")
        ctx = PaymentContext("membership", "Member", member.name)
        # Missing 'amount' -> MollieDataValidationError -> logged -> None.
        result = self.factory_obj.create_payment_entry(
            ctx, {"payment_id": "tr_invalid"}, customer=member.customer
        )
        self.assertIsNone(result)

    def test_duplicate_inside_lock_returns_none(self):
        # Second call (same reference_no) acquires the lock, then the
        # defense-in-depth duplicate check inside the lock returns None.
        member = self._new_member_with_customer("Dup")
        ctx = PaymentContext("membership", "Member", member.name)
        payment_id = f"tr_{frappe.generate_hash(length=12)}"
        pe1 = self.factory_obj.create_payment_entry(
            ctx, {"payment_id": payment_id, "amount": "7.00"}, customer=member.customer
        )
        self.assertIsNotNone(pe1)
        pe2 = self.factory_obj.create_payment_entry(
            ctx, {"payment_id": payment_id, "amount": "7.00"}, customer=member.customer
        )
        self.assertIsNone(pe2)
        self.assertEqual(
            frappe.db.count("Payment Entry", {"reference_no": payment_id, "docstatus": ["!=", 2]}), 1
        )


class TestResolveCustomerForContext(_FactoryBase):
    def test_donation_with_existing_donor_customer(self):
        customer = self.factory.create_test_customer()
        donor = self.create_test_donor(donor_name="Linked Donor", customer=customer.name)
        donation = self.create_test_donation(donor=donor.name, donation_purpose_type="General")
        ctx = PaymentContext("donation", "Donation", donation.name)
        resolved = self.factory_obj._resolve_customer_for_context(ctx)
        self.assertEqual(resolved, customer.name)

    def test_donation_without_customer_creates_one(self):
        donor = self.create_test_donor(donor_name="Unlinked Donor")
        self.assertFalse(donor.customer)
        donation = self.create_test_donation(donor=donor.name, donation_purpose_type="General")
        ctx = PaymentContext("donation", "Donation", donation.name)
        resolved = self.factory_obj._resolve_customer_for_context(ctx)
        self.assertTrue(resolved, "A Customer should be created for the donor")
        self.assertTrue(frappe.db.exists("Customer", resolved))

    def test_donation_customer_creation_is_linked_back_and_not_duplicated(self):
        # Regression: _resolve_customer_for_context used to create a Customer
        # for an unlinked donor but never write donor.customer back, so a SECOND
        # donation for the same donor created a DUPLICATE Customer.
        donor = self.create_test_donor(donor_name="Dup Guard Donor")
        self.assertFalse(donor.customer)
        d1 = self.create_test_donation(donor=donor.name, donation_purpose_type="General")
        first = self.factory_obj._resolve_customer_for_context(
            PaymentContext("donation", "Donation", d1.name)
        )
        self.assertTrue(first)
        # The new Customer must be persisted onto the donor.
        self.assertEqual(frappe.db.get_value("Donor", donor.name, "customer"), first)
        # A second resolve reuses it instead of minting a duplicate. Compare the
        # global Customer count across the second resolve (environment-agnostic;
        # the custom_donor link field is not present on every site).
        customers_before = frappe.db.count("Customer")
        d2 = self.create_test_donation(donor=donor.name, donation_purpose_type="General")
        second = self.factory_obj._resolve_customer_for_context(
            PaymentContext("donation", "Donation", d2.name)
        )
        self.assertEqual(second, first)
        self.assertEqual(
            frappe.db.count("Customer"),
            customers_before,
            "Resolving a customer twice for the same donor must not duplicate the Customer",
        )

    def test_membership_with_existing_member_customer(self):
        member = self._new_member_with_customer("Resolve")
        ctx = PaymentContext("membership", "Member", member.name)
        self.assertEqual(self.factory_obj._resolve_customer_for_context(ctx), member.customer)

    def test_membership_without_customer_triggers_creation(self):
        # Member whose customer link is missing -> resolve delegates to
        # _create_customer_for_member (relinks the still-existing Customer).
        member = self._new_member_with_customer("ResolveCreate")
        cust = member.customer
        frappe.db.set_value("Member", member.name, "customer", None)
        ctx = PaymentContext("membership", "Member", member.name)
        self.assertEqual(self.factory_obj._resolve_customer_for_context(ctx), cust)

    def test_context_exception_returns_none(self):
        # Donation target does not exist -> get_doc raises -> caught -> None.
        ctx = PaymentContext("donation", "Donation", "Donation-Does-Not-Exist-XYZ")
        self.assertIsNone(self.factory_obj._resolve_customer_for_context(ctx))


class TestCreateCustomerForMember(_FactoryBase):
    def test_double_check_returns_existing_customer(self):
        member = self._new_member_with_customer("DblCheck")
        existing = member.customer
        # Lock acquired, reload finds the already-linked customer -> returns it.
        result = self.factory_obj._create_customer_for_member(member)
        self.assertEqual(result, existing)

    def test_relink_existing_customer_when_member_unlinked(self):
        member = self._new_member_with_customer("Relink")
        cust = member.customer
        # Simulate a member whose customer link was lost but the Customer (with
        # member=... link) still exists -> factory should relink, not duplicate.
        frappe.db.set_value("Member", member.name, "customer", None)
        member.reload()
        self.assertFalse(member.customer)
        result = self.factory_obj._create_customer_for_member(member)
        self.assertEqual(result, cust)
        member.reload()
        self.assertEqual(member.customer, cust)

    def test_lock_held_returns_customer_created_by_other_worker(self):
        # Hold the member_customer lock externally so the factory's acquire
        # fails; it then waits, reloads, and finds the already-linked Customer.
        from verenigingen.api.sepa_duplicate_prevention import (
            acquire_processing_lock,
            release_processing_lock,
        )

        member = self._new_member_with_customer("LockHeld")
        existing = member.customer
        self.assertTrue(acquire_processing_lock("member_customer", member.name, timeout=30))
        try:
            result = self.factory_obj._create_customer_for_member(member)
        finally:
            release_processing_lock("member_customer", member.name)
        self.assertEqual(result, existing)

    def test_fresh_customer_created(self):
        member = self._new_member_with_customer("Fresh")
        cust = member.customer
        # Remove the auto-created Customer entirely and unlink, forcing the
        # fresh-creation path (insert_customer_with_duplicate_retry).
        frappe.db.set_value("Member", member.name, "customer", None)
        frappe.delete_doc("Customer", cust, force=True, ignore_permissions=True)
        member.reload()
        result = self.factory_obj._create_customer_for_member(member)
        self.assertTrue(result)
        self.assertTrue(frappe.db.exists("Customer", result))
        self.assertEqual(frappe.get_value("Customer", result, "member"), member.name)


class TestCreateCustomerForMemberWithoutLock(_FactoryBase):
    def test_without_lock_relinks_existing(self):
        member = self._new_member_with_customer("NoLockRelink")
        cust = member.customer
        frappe.db.set_value("Member", member.name, "customer", None)
        member.reload()
        result = self.factory_obj._create_customer_for_member_without_lock(member)
        self.assertEqual(result, cust)

    def test_without_lock_creates_fresh(self):
        member = self._new_member_with_customer("NoLockFresh")
        cust = member.customer
        frappe.db.set_value("Member", member.name, "customer", None)
        frappe.delete_doc("Customer", cust, force=True, ignore_permissions=True)
        member.reload()
        result = self.factory_obj._create_customer_for_member_without_lock(member)
        self.assertTrue(result)
        self.assertEqual(frappe.get_value("Customer", result, "member"), member.name)


class TestOrphanCleanup(_FactoryBase):
    def _build_draft_pe(self, member, payment_id):
        accounts = self.factory_obj._get_accounts(self.company, "membership")
        cost_center = self.factory_obj.cost_center_resolver.resolve_for_context(
            PaymentContext("membership", "Member", member.name), self.company
        )
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": member.customer,
                "paid_amount": 5.0,
                "received_amount": 5.0,
                "reference_no": payment_id,
                "reference_date": frappe.utils.getdate(),
                "posting_date": frappe.utils.getdate(),
                "company": self.company,
                "paid_from": accounts["receivable_account"],
                "paid_to": accounts["bank_account"],
                "cost_center": cost_center,
            }
        )
        pe.insert(ignore_permissions=True)
        return pe

    def test_cleanup_deletes_orphan_and_audits(self):
        self.expectErrorLog("Payment Entry Orphan Cleanup")
        member = self._new_member_with_customer("Orphan")
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        pe = self._build_draft_pe(member, payment_id)
        pe_name = pe.name
        ctx = PaymentContext("membership", "Member", member.name)
        self.factory_obj._handle_orphan_cleanup(
            pe, Exception("submit boom"), ctx, {"payment_id": payment_id, "amount": "5.00"}
        )
        # Orphan deleted...
        self.assertFalse(frappe.db.exists("Payment Entry", pe_name))
        # ...and an audit Comment was added to the member.
        self.assertTrue(
            frappe.db.exists(
                "Comment",
                {"reference_doctype": "Member", "reference_name": member.name, "comment_type": "Info"},
            )
        )

    def test_cleanup_failure_is_audited(self):
        self.expectErrorLog("Payment Entry Orphan Cleanup")
        member = self._new_member_with_customer("OrphanFail")
        payment_id = f"tr_{frappe.generate_hash(length=10)}"
        pe = self._build_draft_pe(member, payment_id)
        ctx = PaymentContext("membership", "Member", member.name)
        # Delete the PE first so the cleanup delete inside the handler fails,
        # exercising the cleanup-error audit branch.
        frappe.delete_doc("Payment Entry", pe.name, force=True, ignore_permissions=True)
        # Should not raise even though the internal delete fails.
        self.factory_obj._handle_orphan_cleanup(
            pe, Exception("submit boom"), ctx, {"payment_id": payment_id, "amount": "5.00"}
        )


class TestGetAccountsDonationConfigured(_FactoryBase):
    def test_donation_receivable_account_configured(self):
        receivable = frappe.get_value("Company", self.company, "default_receivable_account")
        # Set the configured donation receivable account (rolled back at tearDown).
        frappe.db.set_value("Verenigingen Settings", None, "donation_receivable_account", receivable)
        accounts = self.factory_obj._get_accounts(self.company, "donation")
        self.assertEqual(accounts["receivable_account"], receivable)


class TestGetAccountsConfiguredMollieBankAccount(_FactoryBase):
    def test_configured_mollie_bank_account_is_honored_over_fallback(self):
        # Regression: _get_accounts read mollie_bank_account off Verenigingen
        # Settings, but the field was migrated (patch v2_1) to Mollie Settings,
        # so a configured account was silently ignored and the "Mollie" named
        # fallback (seeded by _FactoryBase.setUp) was used instead. The read now
        # goes through the canonical MollieConfigurationService (Mollie Settings).
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            get_mollie_config,
        )

        configured = _make_named_bank_account(self.company, "Mollie Configured Test Bank")
        fallback = frappe.get_value("Account", {"company": self.company, "account_name": "Mollie"}, "name")
        self.assertNotEqual(configured, fallback, "configured account must differ from the fallback")

        # Single write is rolled back at tearDown; the config cache is in-memory
        # and is NOT, so clear it before reading and again on cleanup so the
        # rolled-back value cannot leak into sibling tests.
        frappe.db.set_value("Mollie Settings", None, "mollie_bank_account", configured)
        get_mollie_config().clear_cache()
        self.addCleanup(get_mollie_config().clear_cache)

        accounts = self.factory_obj._get_accounts(self.company, "membership")
        self.assertEqual(
            accounts["bank_account"],
            configured,
            "the configured Mollie Settings bank account must be used, not the 'Mollie' fallback",
        )


class TestGeneratePaymentTitleFallback(_FactoryBase):
    def test_title_falls_back_on_bad_customer(self):
        member = self._new_member_with_customer("TitleFb")
        ctx = PaymentContext("membership", "Member", member.name)
        title = self.factory_obj._generate_payment_title(
            ctx, {"payment_id": "tr_x", "amount": "5.00"}, "Customer-Does-Not-Exist"
        )
        self.assertIn(member.name, title)
