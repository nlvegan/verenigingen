"""
Test custom billing frequency functionality in Membership Dues Schedule
"""
import frappe
import unittest
from datetime import datetime
from frappe.utils import getdate, add_days, add_months, add_years
from verenigingen.tests.utils.base import VereningingenTestCase


class TestCustomBillingFrequency(VereningingenTestCase):
    """Test custom billing frequency calculations"""

    def test_daily_billing_frequency(self):
        """Test daily billing frequency"""
        # Create a test dues schedule with daily billing
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Daily-Schedule"
        schedule.is_template = 1
        schedule.membership_type = "Standard Member"
        schedule.billing_frequency = "Daily"
        schedule.dues_rate = 1.00  # €1 per day for testing
        schedule.auto_generate = 1
        schedule.status = "Active"
        
        # Set a specific start date for predictable testing
        start_date = getdate("2025-01-01")
        
        # Test daily calculation
        next_date = schedule.calculate_next_billing_date(start_date)
        expected_date = add_days(start_date, 1)
        
        self.assertEqual(next_date, expected_date)
        print(f"✅ Daily billing: {start_date} -> {next_date}")

    def test_custom_frequency_weeks(self):
        """Test custom frequency with weeks"""
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Custom-Weeks-Schedule"
        schedule.is_template = 1
        schedule.membership_type = "Standard Member"
        schedule.billing_frequency = "Custom"
        schedule.custom_frequency_number = 2
        schedule.custom_frequency_unit = "Weeks"
        schedule.dues_rate = 10.00
        schedule.auto_generate = 1
        schedule.status = "Active"
        
        start_date = getdate("2025-01-01")
        
        # Test custom weeks calculation (2 weeks = 14 days)
        next_date = schedule.calculate_next_billing_date(start_date)
        expected_date = add_days(start_date, 14)
        
        self.assertEqual(next_date, expected_date)
        print(f"✅ Custom 2 weeks: {start_date} -> {next_date}")

    def test_custom_frequency_months(self):
        """Test custom frequency with months"""
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Custom-Months-Schedule"
        schedule.is_template = 1
        schedule.membership_type = "Standard Member"
        schedule.billing_frequency = "Custom"
        schedule.custom_frequency_number = 3
        schedule.custom_frequency_unit = "Months"
        schedule.dues_rate = 30.00
        schedule.auto_generate = 1
        schedule.status = "Active"
        
        start_date = getdate("2025-01-01")
        
        # Test custom months calculation (3 months)
        next_date = schedule.calculate_next_billing_date(start_date)
        expected_date = add_months(start_date, 3)
        
        self.assertEqual(next_date, expected_date)
        print(f"✅ Custom 3 months: {start_date} -> {next_date}")

    def test_custom_frequency_validation(self):
        """Test custom frequency validation"""
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Custom-Validation"
        schedule.is_template = 1
        schedule.membership_type = "Standard Member"
        schedule.billing_frequency = "Custom"
        schedule.dues_rate = 10.00
        schedule.auto_generate = 1
        schedule.status = "Active"
        
        # Test validation without custom frequency number
        try:
            schedule.validate_custom_frequency()
            self.fail("Should have raised ValidationError for missing frequency number")
        except frappe.ValidationError:
            pass  # Expected
            
        # Test validation without custom frequency unit (set to None to test)
        schedule.custom_frequency_number = 2
        schedule.custom_frequency_unit = None
        try:
            schedule.validate_custom_frequency()
            self.fail("Should have raised ValidationError for missing frequency unit")
        except frappe.ValidationError:
            pass  # Expected
            
        # Test validation with zero frequency number
        schedule.custom_frequency_unit = "Months"
        schedule.custom_frequency_number = 0
        try:
            schedule.validate_custom_frequency()
            self.fail("Should have raised ValidationError for zero frequency number")
        except frappe.ValidationError:
            pass  # Expected
            
        # Test valid custom frequency
        schedule.custom_frequency_number = 2
        schedule.validate_custom_frequency()  # Should not raise
        
        print("✅ Custom frequency validation works correctly")

    def test_membership_dues_item_generation(self):
        """Test membership dues item generation for custom frequencies"""
        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = "Test-Item-Generation"
        schedule.is_template = 1
        schedule.membership_type = "Standard Member"
        schedule.billing_frequency = "Custom"
        schedule.custom_frequency_number = 2
        schedule.custom_frequency_unit = "Weeks"
        schedule.dues_rate = 20.00
        schedule.auto_generate = 1
        schedule.status = "Active"
        
        # Test item name generation
        item_name = schedule.get_membership_dues_item()
        expected_name = "Membership Dues - Custom (Every 2 Weeks)"
        
        self.assertEqual(item_name, expected_name)
        print(f"✅ Custom item generation: {item_name}")
        
        # Test standard frequency item generation
        schedule.billing_frequency = "Monthly"
        item_name = schedule.get_membership_dues_item()
        expected_name = "Membership Dues - Monthly"
        
        self.assertEqual(item_name, expected_name)
        print(f"✅ Standard item generation: {item_name}")

    def test_all_standard_frequencies(self):
        """Test all standard billing frequencies"""
        frequencies = {
            "Daily": (add_days, 1),
            "Monthly": (add_months, 1),
            "Quarterly": (add_months, 3),
            "Semi-Annual": (add_months, 6),
            "Annual": (add_years, 1)
        }
        
        start_date = getdate("2025-01-01")
        
        for frequency, (func, amount) in frequencies.items():
            schedule = frappe.new_doc("Membership Dues Schedule")
            schedule.billing_frequency = frequency
            
            next_date = schedule.calculate_next_billing_date(start_date)
            expected_date = func(start_date, amount)
            
            self.assertEqual(next_date, expected_date)
            print(f"✅ {frequency}: {start_date} -> {next_date}")


if __name__ == "__main__":
    unittest.main()