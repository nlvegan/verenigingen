# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Donation Reporting Service API

Tests donation reporting API endpoints with OperationResult pattern.
Focus on type-safe error handling for donation analytics and reporting.

NOTE (2026-05-31): The whitelisted API functions are decorated with
@high_security_api, which converts the returned OperationResult into the
nested-schema dict via OperationResult.to_dict(scrub_sensitive=True) for
JSON serialization. Therefore the values returned to these tests are dicts,
not OperationResult objects. Tests use dict access:
  - success:  result["success"] (bool)
  - data:     result["data"]
  - failure:  result["error"]["message"], result["error"].get("errors")
"""

import unittest

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.services.donation.reporting_service import (
    DonationReportingService,
    create_donation_allocation_report,
    get_anbi_donations_for_reporting,
    get_donation_accounting_summary,
    get_donation_summary_by_purpose,
    get_donations_by_campaign,
    get_donations_by_chapter,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_donation_refund_journal_entry_creator_coverage import (
    COMPANY,
    _RefundFixtureMixin,
)


class TestDonationReportingAPI(EnhancedTestCase):
    """Unit tests for Donation Reporting Service API endpoints"""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_get_anbi_donations_for_reporting_returns_operation_result(self):
        """Test get_anbi_donations_for_reporting returns OperationResult dict"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        result = get_anbi_donations_for_reporting(from_date, to_date)

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], list)

    def test_get_anbi_donations_with_invalid_dates_returns_operation_result(self):
        """Test ANBI donations with invalid dates still returns OperationResult dict"""
        # Invalid date format should be handled gracefully
        result = get_anbi_donations_for_reporting("invalid", "dates")

        # Should return OperationResult dict (may succeed with empty list or fail)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

    def test_get_donations_by_chapter_returns_operation_result(self):
        """Test get_donations_by_chapter returns OperationResult dict"""
        result = get_donations_by_chapter("Test Chapter")

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], dict)
            self.assertIn("donations", result["data"])

    def test_get_donations_by_campaign_returns_operation_result(self):
        """Test get_donations_by_campaign returns OperationResult dict"""
        result = get_donations_by_campaign("Test Campaign")

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], dict)
            self.assertIn("donations", result["data"])

    def test_get_donation_summary_by_purpose_returns_operation_result(self):
        """Test get_donation_summary_by_purpose returns OperationResult dict"""
        result = get_donation_summary_by_purpose()

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], dict)

    def test_get_donation_accounting_summary_returns_operation_result(self):
        """Test get_donation_accounting_summary returns OperationResult dict"""
        result = get_donation_accounting_summary()

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], dict)

    def test_create_donation_allocation_report_returns_operation_result(self):
        """Test create_donation_allocation_report returns OperationResult dict"""
        result = create_donation_allocation_report()

        # OperationResult (serialized to nested-schema dict by decorator)
        self.assertIsNotNone(result)
        self.assertIn("success", result)

        if result["success"]:
            self.assertIsInstance(result["data"], dict)

    def test_donation_apis_never_throw_exceptions(self):
        """Test that donation reporting APIs never throw exceptions"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        # Test all APIs with valid inputs
        apis_to_test = [
            (get_anbi_donations_for_reporting, (from_date, to_date)),
            (get_donations_by_chapter, ("Test Chapter",)),
            (get_donations_by_campaign, ("Test Campaign",)),
            (get_donation_summary_by_purpose, ()),
            (get_donation_accounting_summary, ()),
            (create_donation_allocation_report, ()),
        ]

        for api_func, args in apis_to_test:
            result = api_func(*args)
            self.assertIsNotNone(result, f"{api_func.__name__} returned None")
            self.assertIn("success", result, f"{api_func.__name__} missing success key")

    def test_reporting_apis_with_date_range(self):
        """Test reporting APIs with date range parameters"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        # Test APIs that support date ranges
        result1 = get_donations_by_chapter("Test Chapter", from_date, to_date)
        self.assertIn("success", result1)

        result2 = get_donations_by_campaign("Test Campaign", from_date, to_date)
        self.assertIn("success", result2)

        result3 = get_donation_summary_by_purpose(from_date, to_date)
        self.assertIn("success", result3)

        result4 = get_donation_accounting_summary(from_date, to_date)
        self.assertIn("success", result4)

        result5 = create_donation_allocation_report("Test Chapter", from_date, to_date)
        self.assertIn("success", result5)

    def test_api_results_contain_proper_metadata(self):
        """Test that API results contain expected metadata structure"""
        from_date = str(getdate())
        to_date = str(add_days(getdate(), 30))

        result = get_anbi_donations_for_reporting(from_date, to_date)

        # Check OperationResult nested-schema structure
        self.assertIsNotNone(result)
        if result["success"]:
            self.assertIsInstance(result["data"], list)
        else:
            self.assertIn("error", result)
            self.assertIsNotNone(result["error"].get("message"))
            self.assertIsInstance(result["error"].get("errors", []), list)


class TestAccountingSummaryGLEntriesLinkage(_RefundFixtureMixin, EnhancedTestCase):
    """Regression tests for issue #369 item 1.

    ``get_donation_accounting_summary`` looked up GL entries with
    ``{"voucher_no": donation.name, "voucher_type": "Payment Entry"}``. That
    was doubly wrong: donations post via Journal Entry, not Payment Entry
    (``donation_journal_entry_creator.py``), AND a Journal Entry's own
    ``voucher_no`` is never the donation's name -- it is the Journal Entry's
    own name, which the creator writes back onto ``Donation.journal_entry``
    (see ``_update_donation_journal_entry``). So even repointing
    ``voucher_type`` at "Journal Entry" without also changing the join key
    would still return nothing. These tests build a real Journal Entry via
    ERPNext's own submit, so ``gl_entries`` below are real GL Entry rows.
    """

    def setUp(self):
        super().setUp()
        self.clearing_account = self._ensure_clearing_account()
        self.income_account = self._ensure_income_account()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _make_reporting_donor(self, donor_name):
        donor = frappe.new_doc("Donor")
        donor.donor_name = donor_name
        donor.donor_email = f"{frappe.generate_hash(length=6)}@example.org"
        donor.donor_type = "Individual"
        donor.preferred_communication_method = "Email"
        donor.insert(ignore_permissions=True)
        self.track_test_record("Donor", donor.name)
        return donor.name

    def _make_paid_donation(self, donor_name, amount):
        """Hand-rolled rather than routed through ``EnhancedTestCase.create_test_donation``
        (#988 item 3): that shared factory method force-sets ``docstatus = 1`` via
        ``frappe.db.set_value`` whenever ``frappe.flags.in_test`` is true
        (``enhanced_test_factory.py``'s ``EnhancedTestDataFactory.create_test_donation``),
        which is a state production can no longer reach post-#987 (Donation is not
        submittable). Routing this test through that factory would import that same
        drift instead of removing it. Filed separately as a factory-side defect;
        this fixture stays independent until that is fixed.

        ``flags.ignore_validate = True`` was also removed here (and on
        ``_make_reporting_donor`` above): both were previously bypassed, but
        re-running this module's tests with real ``validate()`` still passes --
        the bypass was not load-bearing for what this module tests (GL-entry
        linkage via ``get_donation_accounting_summary``).
        """
        donation = frappe.new_doc("Donation")
        donation.donor = donor_name
        donation.donation_date = today()
        donation.amount = amount
        donation.mode_of_payment = "Bank Transfer"
        donation.paid = 1
        donation.insert(ignore_permissions=True)
        self.track_test_record("Donation", donation.name)
        return donation

    def _make_and_submit_journal_entry(self, amount, reference):
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = COMPANY
        je.posting_date = today()
        je.cheque_no = reference
        je.cheque_date = today()
        je.user_remark = f"Donation payment: {reference}"
        cost_center = frappe.get_value("Company", COMPANY, "cost_center")
        for account, debit, credit in (
            (self.clearing_account, amount, 0),
            (self.income_account, 0, amount),
        ):
            je.append(
                "accounts",
                {
                    "account": account,
                    "debit_in_account_currency": debit,
                    "credit_in_account_currency": credit,
                    "cost_center": cost_center,
                },
            )
        je.insert(ignore_permissions=True)
        je.submit()
        self.track_test_record("Journal Entry", je.name)
        return je.name

    def test_gl_entries_are_found_via_the_donations_own_journal_entry(self):
        """A paid donation booked via Journal Entry must show up in
        ``gl_entries`` -- not always-empty as the Payment-Entry lookup made it."""
        donor_name = self._make_reporting_donor("GL Linkage Donor")
        donation = self._make_paid_donation(donor_name, 123.45)

        je_name = self._make_and_submit_journal_entry(123.45, donation.name)
        frappe.db.set_value("Donation", donation.name, "journal_entry", je_name, update_modified=False)

        result = DonationReportingService().get_donation_accounting_summary(
            from_date=today(), to_date=today()
        )

        rows_for_this_donation = [row for row in result["gl_entries"] if row["donation"] == donation.name]
        accounts_seen = {row["account"] for row in rows_for_this_donation}

        self.assertIn(
            self.income_account,
            accounts_seen,
            "the donation's own Journal Entry GL rows were not returned -- the "
            "query is still looking for a Payment Entry, or joining on the wrong "
            "voucher_no",
        )
        self.assertIn(self.clearing_account, accounts_seen)

    def test_donation_with_no_journal_entry_yet_contributes_no_gl_rows(self):
        """A paid donation not yet booked (``journal_entry`` unset) must not
        raise and must not surface another donation's GL rows under its name."""
        donor_name = self._make_reporting_donor("GL Linkage Unbooked Donor")
        donation = self._make_paid_donation(donor_name, 50.0)

        result = DonationReportingService().get_donation_accounting_summary(
            from_date=today(), to_date=today()
        )

        rows_for_this_donation = [row for row in result["gl_entries"] if row["donation"] == donation.name]
        self.assertEqual(rows_for_this_donation, [])


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDonationReportingAPI)
    unittest.TextTestRunner(verbosity=2).run(suite)
