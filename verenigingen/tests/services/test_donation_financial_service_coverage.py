"""
Coverage-extension integration tests for DonationFinancialService.

The sibling ``test_donation_financial_service.py`` covers the four live,
whitelisted donation-creation/reconcile paths. This module targets the large
remaining gaps: the payment-entry / payment-tracking / earmarking-journal-entry
cluster, the account/config resolvers, and the customer-from-donor helper.

IMPORTANT context surfaced while writing these tests (see the module-level
summary returned to the coordinator):

* ``process_financial_entries`` / ``create_payment_tracking_entry`` /
  ``create_payment_entry_for_sales_invoice`` / ``create_earmarking_journal_entry``
  have NO production callers (only the four create/reconcile wrappers in
  ``donation.py`` are wired). They are effectively dead code.
* ``_should_create_payment_entry`` reads ``donation.payment_status`` and several
  methods read ``donation.company`` — NEITHER is a Donation column. Tests that
  need those values inject them as in-memory attributes and note it explicitly.
* Every Verenigingen Settings account/item field these methods read
  (``default_receivable_account``, ``default_donation_income_account``,
  ``general_donations_account``, ``campaign_donations_account``,
  ``chapter_donations_account``, ``default_donation_item``, the fund-account
  fields) is a phantom field: ``.get()`` returns ``None``. So the "happy path"
  of the payment-entry and earmarking-JE methods is unreachable in production;
  the reachable behavior is the error/None branch, which is what we assert.

These are real integration tests against real Donor/Donation/Customer/Company
docs — no business logic is mocked.

Author: Verenigingen Development Team
"""

import frappe
from frappe.utils import today

from verenigingen.services.donation.financial_service import DonationFinancialService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestDonationFinancialServiceCoverage(EnhancedTestCase):
    """Extended coverage for the un-tested branches of DonationFinancialService."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.donor = self.create_test_donor(donor_name="FS Coverage Donor")

    # ------------------------------------------------------------------ #
    # _get_or_create_customer_from_donor
    # ------------------------------------------------------------------ #

    def test_get_or_create_customer_returns_none_without_donor(self):
        """No donor on the donation -> no customer to resolve."""
        donation = frappe.get_doc({"doctype": "Donation"})  # bare, unsaved
        donation.donor = None
        svc = DonationFinancialService(donation)
        self.assertIsNone(svc._get_or_create_customer_from_donor())

    def test_get_or_create_customer_creates_new_linked_customer(self):
        """
        A donor with no Customer yields a freshly created Customer that is
        linked back via the ``donor`` field and carries the donor's name/email.
        Regression guard for the documented ``donor``-vs-``donor_reference``
        column fix (financial_service.py:334-338).
        """
        # Sanity: no customer linked yet
        self.assertFalse(frappe.db.get_value("Customer", {"donor": self.donor.name}))

        donation = self.create_test_donation(donor=self.donor.name)
        svc = DonationFinancialService(donation)
        customer = svc._get_or_create_customer_from_donor()

        self.assertIsNotNone(customer)
        self.assertEqual(customer.donor, self.donor.name)
        self.assertEqual(customer.customer_name, self.donor.donor_name)
        self.assertEqual(customer.customer_type, "Individual")
        self.assertTrue(customer.customer_group)
        # customer_group must be a leaf (non-group) node
        self.assertEqual(frappe.db.get_value("Customer Group", customer.customer_group, "is_group"), 0)
        self.assertEqual(customer.email_id, self.donor.donor_email)
        self.assertTrue(frappe.db.exists("Customer", customer.name))

    def test_get_or_create_customer_returns_existing(self):
        """A donor that already has a linked Customer returns that same record."""
        existing = self._make_customer_for_donor(self.donor)
        donation = self.create_test_donation(donor=self.donor.name)
        svc = DonationFinancialService(donation)
        resolved = svc._get_or_create_customer_from_donor()
        self.assertEqual(resolved.name, existing.name)

    # ------------------------------------------------------------------ #
    # simple config resolvers
    # ------------------------------------------------------------------ #

    def test_get_default_territory_non_empty(self):
        """Territory resolves to the Selling Settings value or 'All Territories'."""
        svc = DonationFinancialService(frappe.get_doc({"doctype": "Donation"}))
        territory = svc._get_default_territory()
        self.assertTrue(territory)
        self.assertTrue(frappe.db.exists("Territory", territory))

    def test_get_donation_item_code_falls_back_to_DONATION(self):
        """
        ``default_donation_item`` is a phantom Verenigingen Settings field
        (.get() -> None), so the item code falls back to the 'DONATION' literal.
        """
        svc = DonationFinancialService(frappe.get_doc({"doctype": "Donation"}))
        self.assertEqual(svc._get_donation_item_code(), "DONATION")

    # ------------------------------------------------------------------ #
    # earmarking summary / requirement branches
    # ------------------------------------------------------------------ #

    def test_get_earmarking_summary_campaign_branch(self):
        """Campaign purpose reports a Campaign earmarking type + campaign fund label."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "amount": 55.0,
                "donation_purpose_type": "Campaign",
                "campaign": "Spring Drive",  # in-memory only; not persisted
            }
        )
        svc = DonationFinancialService(donation)
        summary = svc.get_earmarking_summary()
        self.assertTrue(summary["requires_earmarking"])
        self.assertEqual(summary["earmarking_type"], "Campaign")
        self.assertEqual(summary["destination_fund"], "Campaign: Spring Drive")
        self.assertEqual(summary["amount"], 55.0)

    def test_get_earmarking_summary_fund_designation_branch(self):
        """A fund-designated (non Campaign/Chapter) donation reports Fund Designation."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "amount": 30.0,
                "donation_purpose_type": "General",
                "fund_designation": "Emergency Fund",
            }
        )
        svc = DonationFinancialService(donation)
        summary = svc.get_earmarking_summary()
        self.assertTrue(summary["requires_earmarking"])
        self.assertEqual(summary["earmarking_type"], "Fund Designation")
        self.assertEqual(summary["destination_fund"], "Emergency Fund")

    def test_get_earmarking_summary_general_has_no_type(self):
        """A plain General donation requires no earmarking and reports no type."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "amount": 10.0,
                "donation_purpose_type": "General",
            }
        )
        svc = DonationFinancialService(donation)
        summary = svc.get_earmarking_summary()
        self.assertFalse(summary["requires_earmarking"])
        self.assertIsNone(summary["earmarking_type"])
        self.assertIsNone(summary["destination_fund"])

    def test_requires_earmarking_true_for_fund_designation(self):
        """Fund designation alone (General purpose) still requires earmarking."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "donation_purpose_type": "General",
                "fund_designation": "Research Fund",
            }
        )
        svc = DonationFinancialService(donation)
        self.assertTrue(svc._requires_earmarking())

    # ------------------------------------------------------------------ #
    # earmarking account resolution (all phantom -> None)
    # ------------------------------------------------------------------ #

    def test_get_earmarking_accounts_campaign_branch_returns_none(self):
        """Campaign earmarking accounts are unconfigured (phantom fields) -> None."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "donation_purpose_type": "Campaign",
                "campaign": "X",
            }
        )
        svc = DonationFinancialService(donation)
        self.assertIsNone(svc._get_earmarking_accounts())

    def test_get_earmarking_accounts_fund_designation_branch_returns_none(self):
        """Fund-designation earmarking uses the fund->account map (all phantom) -> None."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "donation_purpose_type": "General",
                "fund_designation": "General Fund",
            }
        )
        svc = DonationFinancialService(donation)
        self.assertIsNone(svc._get_earmarking_accounts())

    def test_get_fund_designation_accounts_all_none(self):
        """
        The fund-designation -> account map has an entry per known fund, but every
        value resolves from a phantom Verenigingen Settings field, i.e. None.
        """
        svc = DonationFinancialService(frappe.get_doc({"doctype": "Donation"}))
        mapping = svc._get_fund_designation_accounts()
        self.assertEqual(
            set(mapping.keys()),
            {
                "General Fund",
                "Emergency Fund",
                "Campaign Fund",
                "Chapter Fund",
                "Project Fund",
                "Research Fund",
            },
        )
        self.assertTrue(all(v is None for v in mapping.values()))

    # ------------------------------------------------------------------ #
    # _get_accounting_accounts -> always throws (phantom receivable field)
    # ------------------------------------------------------------------ #

    def test_get_accounting_accounts_throws_on_missing_account(self):
        """
        ``default_receivable_account`` is a phantom setting, so accounting-account
        resolution always throws a clear 'Missing ...' configuration error.
        (Documents that the payment-entry happy path is unreachable in prod.)
        """
        donation = frappe.get_doc({"doctype": "Donation", "donor": self.donor.name, "amount": 20.0})
        # company is NOT a Donation column; inject a real company in-memory so the
        # method reaches the settings/account validation it is being tested for.
        donation.company = get_eur_test_company()
        svc = DonationFinancialService(donation)
        with self.assertRaises(frappe.ValidationError) as ctx:
            svc._get_accounting_accounts()
        self.assertIn("Missing", str(ctx.exception))

    # ------------------------------------------------------------------ #
    # create_earmarking_journal_entry
    # ------------------------------------------------------------------ #

    def test_create_earmarking_journal_entry_returns_none_when_not_required(self):
        """No earmarking required (General) -> method short-circuits to None."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "amount": 10.0,
                "donation_purpose_type": "General",
            }
        )
        svc = DonationFinancialService(donation)
        self.assertIsNone(svc.create_earmarking_journal_entry())

    def test_create_earmarking_journal_entry_throws_when_accounts_unconfigured(self):
        """
        Earmarking IS required (Chapter) but the accounts are phantom/unconfigured,
        so the method throws 'Earmarking accounts not configured' rather than
        creating a bogus journal entry.
        """
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "amount": 10.0,
                "donation_purpose_type": "Chapter",
                "chapter_reference": "any-chapter",
            }
        )
        svc = DonationFinancialService(donation)
        with self.assertRaises(frappe.ValidationError) as ctx:
            svc.create_earmarking_journal_entry()
        self.assertIn("Earmarking accounts not configured", str(ctx.exception))

    # ------------------------------------------------------------------ #
    # create_payment_entry_for_sales_invoice error branches
    # ------------------------------------------------------------------ #

    def test_create_payment_entry_throws_when_customer_missing(self):
        """No Customer linked to the donor -> 'Customer not found' throw."""
        self.assertFalse(frappe.db.get_value("Customer", {"donor": self.donor.name}))
        donation = frappe.get_doc({"doctype": "Donation", "donor": self.donor.name, "amount": 42.0})
        svc = DonationFinancialService(donation)
        with self.assertRaises(frappe.ValidationError) as ctx:
            svc.create_payment_entry_for_sales_invoice()
        self.assertIn("Customer not found", str(ctx.exception))

    def test_create_payment_entry_throws_when_no_matching_invoice(self):
        """
        Customer exists but there is no matching unpaid Sales Invoice for the
        donation amount -> 'Sales Invoice not found' throw.
        """
        self._make_customer_for_donor(self.donor)
        donation = frappe.get_doc({"doctype": "Donation", "donor": self.donor.name, "amount": 987654.32})
        svc = DonationFinancialService(donation)
        with self.assertRaises(frappe.ValidationError) as ctx:
            svc.create_payment_entry_for_sales_invoice()
        self.assertIn("Sales Invoice not found", str(ctx.exception))

    # ------------------------------------------------------------------ #
    # create_payment_tracking_entry
    # ------------------------------------------------------------------ #

    def test_create_payment_tracking_entry_appends_row(self):
        """
        A donation with no existing tracking row gets a Donation Payment child
        row populated from the donation fields and persisted via save().
        """
        donation = self._make_unsubmitted_donation(amount=77.0, paid=1)
        svc = DonationFinancialService(donation)
        row = svc.create_payment_tracking_entry()

        self.assertIsNotNone(row)
        self.assertEqual(row.amount, 77.0)
        self.assertEqual(row.payment_method, "Bank Transfer")
        self.assertEqual(row.payment_status, "Paid")  # donation.paid == 1
        donation.reload()
        self.assertEqual(len(donation.payments), 1)
        self.assertEqual(donation.payments[0].amount, 77.0)

    def test_create_payment_tracking_entry_pending_when_unpaid(self):
        """An unpaid donation yields a 'Pending' tracking row."""
        donation = self._make_unsubmitted_donation(amount=12.0, paid=0)
        svc = DonationFinancialService(donation)
        row = svc.create_payment_tracking_entry()
        self.assertEqual(row.payment_status, "Pending")

    def test_create_payment_tracking_entry_is_idempotent_for_same_payment_id(self):
        """
        If a tracking row with the same payment_id already exists, the method
        returns it instead of appending a duplicate.
        """
        donation = self._make_unsubmitted_donation(amount=50.0, paid=1)
        donation.payment_id = "PAY-DUP-1"
        # Pre-seed a matching payment row
        existing = donation.append(
            "payments",
            {
                "payment_date": today(),
                "amount": 50.0,
                "payment_status": "Paid",
                "payment_id": "PAY-DUP-1",
            },
        )
        donation.save()

        svc = DonationFinancialService(donation)
        result = svc.create_payment_tracking_entry()
        self.assertEqual(result.payment_id, "PAY-DUP-1")
        # No duplicate row added
        self.assertEqual(len(donation.payments), 1)
        self.assertEqual(result.name, existing.name)

    # ------------------------------------------------------------------ #
    # process_financial_entries orchestrator
    # ------------------------------------------------------------------ #

    def test_process_financial_entries_no_actions_for_pending_general(self):
        """
        A non-Completed, General donation triggers no payment/earmarking work.

        NOTE: ``_should_create_payment_entry`` reads ``donation.payment_status``,
        which is NOT a Donation column; injected in-memory here to exercise the
        orchestrator's 'nothing to do' path.
        """
        donation = self._make_unsubmitted_donation(amount=10.0, paid=0)
        donation.payment_status = "Pending"  # phantom field, in-memory
        svc = DonationFinancialService(donation)
        results = svc.process_financial_entries()
        self.assertEqual(results, {})

    def test_process_financial_entries_captures_payment_entry_error(self):
        """
        When Completed, the orchestrator creates a tracking row and attempts a
        payment entry; the payment-entry failure (no Customer/invoice) is captured
        in results rather than propagated.

        NOTE: ``payment_status`` injected in-memory (phantom field).
        """
        donation = self._make_unsubmitted_donation(amount=64.0, paid=1)
        donation.payment_status = "Completed"  # phantom field, in-memory
        svc = DonationFinancialService(donation)
        results = svc.process_financial_entries()

        # tracking entry succeeded (no payment_id on donation -> "created" sentinel)
        self.assertIn("payment_tracking", results)
        # payment entry failed because donor has no Customer -> captured error
        self.assertIn("payment_entry_error", results)
        self.assertIn("Customer not found", results["payment_entry_error"])

    # ------------------------------------------------------------------ #
    # _get_campaign_project
    # ------------------------------------------------------------------ #

    def test_get_campaign_project_none_without_campaign(self):
        """No campaign on the donation -> no associated project."""
        donation = frappe.get_doc(
            {"doctype": "Donation", "donor": self.donor.name, "donation_purpose_type": "General"}
        )
        donation.campaign = None
        svc = DonationFinancialService(donation)
        self.assertIsNone(svc._get_campaign_project())

    # ------------------------------------------------------------------ #
    # helpers (privileged data creation lives here)
    # ------------------------------------------------------------------ #

    def _make_customer_for_donor(self, donor):
        """Insert a Customer linked to the given donor via the custom donor field."""
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"FS Cov Customer {frappe.generate_hash(length=6)}",
                "customer_type": "Individual",
                "donor": donor.name,
            }
        )
        customer.insert()
        return customer

    def _make_unsubmitted_donation(self, amount, paid):
        """Insert an editable (docstatus 0) General donation for tracking tests."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.donor.name,
                "donation_date": today(),
                "amount": amount,
                "mode_of_payment": "Bank Transfer",
                "donation_purpose_type": "General",
                "paid": paid,
            }
        )
        donation.insert()
        return donation
