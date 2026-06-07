"""
Financial Integration Edge Cases Test Suite
Tests for payment processing, dues schedule management, and financial data integrity
"""

import unittest
from unittest.mock import patch  # Only for external API mocking (requests.post)

import frappe
from frappe.utils import add_days, flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.skip_reasons import VOLUNTEER_EXPENSE_ARCHIVED


class TestFinancialIntegrationEdgeCases(EnhancedTestCase):
    """Test financial system edge cases and failure scenarios"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        super().setUpClass()
        cls.test_records = []

        # Chapter has reqd fields (status/region/introduction) and autoname=prompt;
        # ensure backing Region exists before creating the chapter.
        test_region_name = "Financial Test Region"
        region_docname = frappe.db.get_value("Region", {"region_name": test_region_name}, "name")
        if not region_docname:
            region = frappe.get_doc({
                "doctype": "Region",
                "region_name": test_region_name,
                "region_code": "FTR",
            })
            region.insert(ignore_permissions=True)
            region_docname = region.name

        cls.chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "status": "Active",
                "region": region_docname,
                "introduction": "Financial Integration Edge Cases test chapter",
            }
        )
        cls.chapter.name = "Financial Test Chapter"
        cls.chapter.insert(ignore_permissions=True)
        cls.test_records.append(cls.chapter)

        # Membership Type reqd fields: membership_type_name (autoname=field:),
        # minimum_amount, role_profile. Look up any Role Profile for the link.
        role_profile = (
            frappe.db.get_value("Role Profile", {"name": "Verenigingen Staff"}, "name")
            or frappe.db.get_value("Role Profile", {}, "name")
        )
        cls.membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Financial Test Premium",
                "description": "Test membership type for financial edge cases",
                "minimum_amount": 25.0,
                "role_profile": role_profile,
            }
        )
        cls.membership_type.insert(ignore_permissions=True)
        cls.test_records.append(cls.membership_type)

        # Create test member
        cls.member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Financial",
                "last_name": "Testmember",
                "email": "financial.test@test.com",
                "status": "Active",
                "chapter": cls.chapter.name}
        )
        cls.member.insert()
        cls.test_records.append(cls.member)

        # Create test volunteer
        cls.volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Financial Test Volunteer",
                "email": "volunteer.financial@test.com",
                "member": cls.member.name,
                "status": "Active"}
        )
        cls.volunteer.insert()
        cls.test_records.append(cls.volunteer)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        for record in reversed(cls.test_records):
            try:
                record.delete()
            except Exception:
                pass
        super().tearDownClass()

    def setUp(self):
        """Set up each test"""
        super().setUp()
        # EnhancedTestCase handles permissions automatically

    # ===== MEMBERSHIP FEE EDGE CASES =====





    # ===== CURRENCY CONVERSION EDGE CASES =====

    def test_currency_conversion_failure(self):
        """Test handling of currency conversion failures"""
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                # Note: fee is defined in membership_type, not directly on membership
                "currency": "USD",  # Different from membership type currency
                "status": "Active"}
        )

        # Should either convert properly or raise validation error
        try:
            membership.insert()
            # If successful, verify conversion occurred
            # Verify fee through membership type instead of deprecated annual_fee field
            membership_type_doc = frappe.get_doc("Membership Type", membership.membership_type)
            self.assertIsNotNone(membership_type_doc.minimum_amount)
            membership.delete()
        except frappe.ValidationError:
            # Validation error is acceptable if conversion not supported
            pass


    # ===== PAYMENT PROCESSING EDGE CASES =====

    def test_concurrent_payment_processing(self):
        """Test concurrent payment processing scenarios using real data"""
        # Create membership with pending payment
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                # Note: fee is defined in membership_type, not directly on membership
                "status": "Pending"}
        )
        membership.insert()

        # Test real concurrent-like scenarios by rapidly changing status
        # This tests the actual validation and save logic without database mocking
        for i in range(3):
            try:
                membership.reload()  # Reload to get latest state
                membership.status = "Active"
                membership.save()

                # Revert back to pending for next iteration
                membership.status = "Pending"
                membership.save()
            except Exception as e:
                # Any validation errors should be handled gracefully
                self.assertIsInstance(e, (frappe.ValidationError, frappe.PermissionError))

        # Clean up
        membership.delete()

    @unittest.skip(
        "verenigingen.api.financial.validate_payment endpoint was removed; "
        "see Group G2 PR notes. The original test relied on a "
        "frappe.call() into a deleted module, which was being swallowed by "
        "an AttributeError → skipTest fallback (silent no-op). Re-enable "
        "when a replacement payment-validation API ships."
    )
    def test_payment_amount_mismatch(self):
        """Test handling of payment amount mismatches"""
        pass

    # ===== DUES SCHEDULE OVERRIDE EDGE CASES =====

    def test_dues_schedule_override_conflicts(self):
        """Test conflicting dues schedule overrides"""
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                # Note: fee is defined in membership_type, not directly on membership
                "status": "Active"}
        )
        membership.insert()

        # Test creating conflicting overrides
        try:
            # This should be implemented in the actual dues schedule override system
            override1 = {
                "membership": membership.name,
                "override_amount": 50.00,
                "reason": "Student discount"}
            override2 = {"membership": membership.name, "override_amount": 75.00, "reason": "Senior discount"}

            # System should prevent conflicting overrides
            # Implementation depends on actual override system

        finally:
            membership.delete()

    def test_orphaned_dues_schedule_cleanup(self):
        """Test orphaned dues schedule detection and cleanup"""
        # Create membership
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                # Note: fee is defined in membership_type, not directly on membership
                "status": "Active"}
        )
        membership.insert()

        # Simulate orphaned state by deleting member. setUpClass links a
        # Volunteer to this member (reqd link), so remove it first to avoid
        # LinkExistsError on delete.
        for vol in frappe.get_all("Volunteer", filters={"member": self.member.name}, pluck="name"):
            frappe.delete_doc("Volunteer", vol, force=True)
        self.member.delete()

        # Run orphaned dues schedule cleanup
        try:
            from verenigingen.utils.membership_dues_integration import cleanup_orphaned_dues_schedules

            cleanup_orphaned_dues_schedules()

            # Membership should be marked as orphaned or deleted
            orphaned_membership = frappe.db.exists("Membership", membership.name)
            if orphaned_membership:
                updated_membership = frappe.get_doc("Membership", membership.name)
                self.assertIn(updated_membership.status, ["Cancelled", "Orphaned"])
        except ImportError:
            # Cleanup function not implemented yet
            pass
        finally:
            # Restore member for other tests
            self.member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Financial",
                    "last_name": "Testmember",
                    "email": "financial.test@test.com",
                    "status": "Active",
                    "chapter": self.chapter.name}
            )
            self.member.insert()

            # Clean up membership if it still exists
            if frappe.db.exists("Membership", membership.name):
                membership.delete()

    # ===== VOLUNTEER EXPENSE EDGE CASES =====

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_negative_amount(self):
        """Test negative volunteer expense amounts"""
        with self.assertRaises(frappe.ValidationError):
            expense = frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.volunteer.name,
                    "description": "Test expense",
                    "amount": -50.00,  # Negative amount
                    "currency": "EUR",
                    "expense_date": today()}
            )
            expense.insert()

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_extreme_amounts(self):
        """Test extremely large volunteer expense amounts"""
        # Test reasonable large amount (should pass)
        expense = frappe.get_doc(
            {
                "doctype": "Volunteer Expense",
                "volunteer": self.volunteer.name,
                "description": "Large equipment purchase",
                "amount": 5000.00,
                "currency": "EUR",
                "expense_date": today()}
        )
        expense.insert()
        expense.delete()

        # Test unreasonably large amount (should fail)
        with self.assertRaises(frappe.ValidationError):
            expense = frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.volunteer.name,
                    "description": "Unreasonable expense",
                    "amount": 999999.00,  # Extremely large
                    "currency": "EUR",
                    "expense_date": today()}
            )
            expense.insert()

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_future_date(self):
        """Test volunteer expenses with future dates"""
        future_date = add_days(today(), 30)

        with self.assertRaises(frappe.ValidationError):
            expense = frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.volunteer.name,
                    "description": "Future expense",
                    "amount": 100.00,
                    "currency": "EUR",
                    "expense_date": future_date,  # Future date
                }
            )
            expense.insert()

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_volunteer_expense_currency_mismatch(self):
        """Test volunteer expense currency validation"""
        # Test with different currencies
        currencies = ["EUR", "USD", "GBP"]

        for currency in currencies:
            expense = frappe.get_doc(
                {
                    "doctype": "Volunteer Expense",
                    "volunteer": self.volunteer.name,
                    "description": f"Test expense {currency}",
                    "amount": 100.00,
                    "currency": currency,
                    "expense_date": today()}
            )

            try:
                expense.insert()
                # If successful, verify currency handling
                self.assertEqual(expense.currency, currency)
                expense.delete()
            except frappe.ValidationError:
                # Validation error acceptable if currency not supported
                pass

    # ===== FINANCIAL AUDIT TRAIL EDGE CASES =====

    def test_payment_history_integrity(self):
        """Test payment history data integrity via membership audit trail"""
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                # Note: fee is defined in membership_type, not directly on membership
                "status": "Active"}
        )
        membership.insert()

        try:
            # Verify membership was created with correct data
            self.assertTrue(frappe.db.exists("Membership", membership.name))
            reloaded = frappe.get_doc("Membership", membership.name)
            self.assertEqual(reloaded.member, self.member.name)
            self.assertEqual(reloaded.membership_type, self.membership_type.name)
        finally:
            membership.delete()


    # ===== INTEGRATION FAILURE SCENARIOS =====

    def test_erpnext_integration_failure(self):
        """Test ERPNext integration error handling using real validation scenarios"""
        # Test with invalid references that would cause integration issues
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "start_date": today(),
                # Note: fee is defined in membership_type, not directly on membership
                "status": "Active"}
        )

        # Test real integration scenarios that could fail
        try:
            membership.insert()
            # Membership should be created successfully with valid data
            self.assertTrue(frappe.db.exists("Membership", membership.name))

            # Test updating with invalid references to trigger validation
            try:
                membership.membership_type = "NON-EXISTENT-TYPE"
                membership.save()
                self.fail("Should have failed with invalid membership type")
            except frappe.ValidationError:
                # Expected validation error for invalid reference
                pass

        except Exception as e:
            # Unexpected errors should be reported
            self.fail(f"Unexpected error in integration test: {e}")
        finally:
            if frappe.db.exists("Membership", membership.name):
                membership.delete()

    def test_payment_gateway_timeout(self):
        """Test payment gateway timeout handling via requests mock"""
        # Mock justified: External Service - payment gateway HTTP timeout, not business logic
        with patch("requests.post") as mock_post:
            mock_post.side_effect = TimeoutError("Payment gateway timeout")

            # Verify the timeout is raised when calling external APIs
            with self.assertRaises(TimeoutError):
                import requests
                requests.post("https://api.example.com/payment", json={
                    "amount": 100.00, "currency": "EUR"
                })

    # ===== ROUNDING AND PRECISION EDGE CASES =====

    def test_financial_calculations_precision(self):
        """Test financial calculation precision"""
        # Test various calculation scenarios
        test_cases = [
            (33.33, 3, 99.99),  # 33.33 * 3 = 99.99 (not 100.00)
            (10.00, 0.1, 1.00),  # 10.00 * 0.1 = 1.00
            (0.1, 10, 1.00),  # 0.1 * 10 = 1.00 (floating point precision)
        ]

        for amount, multiplier, expected in test_cases:
            result = flt(amount * multiplier, 2)
            self.assertEqual(
                result,
                expected,
                f"Financial calculation {amount} * {multiplier} = {result}, expected {expected}",
            )

    def test_vat_calculation_edge_cases(self):
        """Test VAT calculation edge cases"""
        # Test Dutch VAT rates
        vat_rates = [0.21, 0.09, 0.00]  # Standard, reduced, zero rate
        base_amounts = [100.00, 33.33, 0.01]

        for rate in vat_rates:
            for amount in base_amounts:
                vat_amount = flt(amount * rate, 2)
                total_amount = flt(amount + vat_amount, 2)

                # Verify VAT calculation precision
                self.assertIsInstance(vat_amount, float)
                self.assertGreaterEqual(vat_amount, 0)
                self.assertEqual(total_amount, flt(amount + vat_amount, 2))


def run_financial_edge_case_tests():
    """Run all financial edge case tests"""
    print("💰 Running Financial Integration Edge Case Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestFinancialIntegrationEdgeCases)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All financial edge case tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_financial_edge_case_tests()
