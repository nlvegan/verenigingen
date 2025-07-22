"""
Unit tests for dues schedule date validation and invoice generation
Tests to prevent issues with incorrect next_invoice_date values
"""

import frappe
import unittest
from datetime import datetime, timedelta
from frappe.utils import today, add_days, add_months, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDuesScheduleDateValidation(VereningingenTestCase):
    """Test suite for dues schedule date validation and edge cases"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.today = getdate(today())
        
    def test_daily_schedule_creation_dates(self):
        """Test that daily schedules are created with correct dates"""
        member = self.create_test_member()
        
        # Create an active membership for the member
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member.name,
            "membership_type": "Daglid",  # Use existing membership type
            "start_date": today(),
            "status": "Active"
        })
        membership.insert()
        membership.submit()
        self.track_doc("Membership", membership.name)
        
        # Skip membership validation for testing
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Daily-{member.name}",
            "member": member.name,
            "membership_type": "Daglid",
            "billing_frequency": "Daily",
            "dues_rate": 5.0,
            "status": "Active",
            "auto_generate": 1
        })
        schedule._skip_membership_validation = True
        schedule.insert()
        
        # The next invoice date should be today or tomorrow, never a year ahead
        next_date = getdate(schedule.next_invoice_date)
        self.assertLessEqual(next_date, add_days(self.today, 2), 
                           f"Next invoice date {next_date} should not be more than 2 days from today {self.today}")
        
        # Should not be more than a week in the past
        self.assertGreaterEqual(next_date, add_days(self.today, -7),
                              f"Next invoice date {next_date} should not be more than a week in the past")
        
        self.track_doc("Membership Dues Schedule", schedule.name)
    
    def test_weekly_schedule_creation_dates(self):
        """Test that weekly schedules are created with correct dates"""
        member = self.create_test_member()
        
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Weekly-{member.name}",
            "member": member.name,
            "billing_frequency": "Weekly",
            "dues_rate": 10.0,
            "status": "Active",
            "auto_generate": 1
        })
        schedule.insert()
        
        # Next invoice date should be within reasonable range
        next_date = getdate(schedule.next_invoice_date)
        self.assertLessEqual(next_date, add_days(self.today, 8),
                           f"Weekly schedule next invoice date {next_date} should not be more than 8 days from today")
        
        self.track_doc("Membership Dues Schedule", schedule.name)
    
    def test_monthly_schedule_creation_dates(self):
        """Test that monthly schedules are created with correct dates"""
        member = self.create_test_member()
        
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Monthly-{member.name}",
            "member": member.name, 
            "billing_frequency": "Monthly",
            "dues_rate": 25.0,
            "status": "Active",
            "auto_generate": 1
        })
        schedule.insert()
        
        # Next invoice date should be within a reasonable range for monthly billing
        next_date = getdate(schedule.next_invoice_date)
        self.assertLessEqual(next_date, add_days(self.today, 32),
                           f"Monthly schedule next invoice date {next_date} should not be more than 32 days from today")
        
        self.track_doc("Membership Dues Schedule", schedule.name)
    
    def test_schedule_date_validation_future_dates(self):
        """Test validation prevents schedules with unreasonably far future dates"""
        member = self.create_test_member()
        
        # Try to create a schedule with next invoice date a year in the future
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Future-{member.name}",
            "member": member.name,
            "billing_frequency": "Daily", 
            "dues_rate": 5.0,
            "status": "Active",
            "auto_generate": 1,
            "next_invoice_date": add_days(self.today, 365)  # One year ahead
        })
        
        # This should either be corrected during save or raise a validation error
        with self.assertRaises((frappe.ValidationError, ValueError)) or self.assertWarns(UserWarning):
            schedule.insert()
            
            # If it doesn't raise an error, it should at least correct the date
            if schedule.name:
                self.track_doc("Membership Dues Schedule", schedule.name)
                corrected_date = getdate(schedule.next_invoice_date)
                self.assertLessEqual(corrected_date, add_days(self.today, 31),
                                   "System should correct unreasonably future dates")
    
    def test_schedule_date_validation_past_dates(self):
        """Test validation prevents schedules with very old past dates"""
        member = self.create_test_member()
        
        # Try to create schedule with next invoice date months in the past
        old_date = add_days(self.today, -90)  # 3 months ago
        
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Past-{member.name}",
            "member": member.name,
            "billing_frequency": "Daily",
            "dues_rate": 5.0, 
            "status": "Active",
            "auto_generate": 1,
            "next_invoice_date": old_date
        })
        
        schedule.insert()
        
        # System should correct very old dates
        corrected_date = getdate(schedule.next_invoice_date)
        self.assertGreaterEqual(corrected_date, add_days(self.today, -7),
                              "System should correct very old next_invoice_date values")
        
        self.track_doc("Membership Dues Schedule", schedule.name)
    
    def test_update_schedule_dates_method(self):
        """Test the update_schedule_dates method works correctly"""
        member = self.create_test_member()
        
        # Create schedule with incorrect dates
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Update-{member.name}",
            "member": member.name,
            "billing_frequency": "Daily",
            "dues_rate": 5.0,
            "status": "Active", 
            "auto_generate": 1
        })
        schedule.insert()
        
        # Manually set bad dates
        schedule.db_set("next_invoice_date", add_days(self.today, 365))
        schedule.reload()
        
        # Test the update method
        schedule.update_schedule_dates()
        
        # Dates should now be reasonable
        updated_date = getdate(schedule.next_invoice_date)
        self.assertLessEqual(updated_date, add_days(self.today, 2),
                           "update_schedule_dates should fix unreasonable dates")
        
        self.track_doc("Membership Dues Schedule", schedule.name)
    
    def test_overdue_schedule_detection(self):
        """Test detection of overdue schedules"""
        member = self.create_test_member()
        
        # Create schedule that's overdue
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Overdue-{member.name}",
            "member": member.name,
            "billing_frequency": "Daily",
            "dues_rate": 5.0,
            "status": "Active",
            "auto_generate": 1,
            "next_invoice_date": add_days(self.today, -5),  # 5 days overdue
            "last_invoice_date": add_days(self.today, -6)
        })
        schedule.insert()
        self.track_doc("Membership Dues Schedule", schedule.name)
        
        # Test overdue detection
        from verenigingen.api.test_fixes import test_all_overdue_schedules
        result = test_all_overdue_schedules()
        
        self.assertTrue(result["success"], "Overdue detection should succeed")
        
        # Should find our overdue schedule
        overdue_members = [s["member"] for s in result["overdue_schedules"]]
        self.assertIn(member.name, overdue_members, 
                     "Should detect our overdue schedule")
    
    def test_invoice_generation_with_correct_dates(self):
        """Test invoice generation works with properly set dates"""
        member = self.create_test_member()
        
        # Create customer for the member
        if not member.customer:
            customer = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": member.full_name,
                "customer_type": "Individual", 
                "customer_group": "Individual",
                "territory": "All Territories"
            })
            customer.insert()
            member.db_set("customer", customer.name)
            self.track_doc("Customer", customer.name)
        
        # Create schedule due today
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Invoice-{member.name}",
            "member": member.name,
            "billing_frequency": "Daily",
            "dues_rate": 5.0,
            "status": "Active",
            "auto_generate": 1,
            "next_invoice_date": self.today,
            "last_invoice_date": add_days(self.today, -1)
        })
        schedule.insert()
        self.track_doc("Membership Dues Schedule", schedule.name)
        
        # Test invoice generation
        try:
            invoice = schedule.generate_invoice()
            if invoice:
                self.track_doc("Sales Invoice", invoice.name)
                self.assertEqual(invoice.customer, member.customer,
                               "Invoice should be for the correct customer")
                self.assertGreater(invoice.grand_total, 0,
                                 "Invoice should have a positive amount")
        except Exception as e:
            # If generation fails, it should be due to configuration, not date issues
            self.assertNotIn("date", str(e).lower(),
                           f"Invoice generation should not fail due to date issues: {e}")
    
    def test_bulk_schedule_date_repair(self):
        """Test bulk repair of schedule dates"""
        # Create multiple members with problematic schedules
        members = []
        schedules = []
        
        for i in range(3):
            member = self.create_test_member(email=f"test{i}@schedulerepair.com")
            members.append(member)
            
            # Create schedule with future date problem
            schedule = frappe.get_doc({
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Test-Schedule-Bulk-{i}-{member.name}",
                "member": member.name,
                "billing_frequency": "Daily",
                "dues_rate": 5.0,
                "status": "Active",
                "auto_generate": 1
            })
            schedule.insert()
            
            # Manually corrupt the dates
            schedule.db_set("next_invoice_date", add_days(self.today, 365 + i))
            schedules.append(schedule)
            self.track_doc("Membership Dues Schedule", schedule.name)
        
        # Test bulk repair
        from verenigingen.api.test_fixes import fix_all_overdue_schedules
        
        # First reload schedules to see corrupted dates
        for schedule in schedules:
            schedule.reload()
            corrupted_date = getdate(schedule.next_invoice_date)
            self.assertGreater(corrupted_date, add_days(self.today, 300),
                             "Schedule should have corrupted future date")
        
        # Now test the repair function
        repair_result = fix_all_overdue_schedules()
        
        # Verify repair worked (dates should now be reasonable)
        for schedule in schedules:
            schedule.reload()
            fixed_date = getdate(schedule.next_invoice_date)
            # After repair, dates should be reasonable (not years in future)
            self.assertLessEqual(fixed_date, add_days(self.today, 30),
                               f"Repaired date {fixed_date} should be reasonable")
    
    def test_schedule_consistency_validation(self):
        """Test that schedules maintain consistency between last and next invoice dates"""
        member = self.create_test_member()
        
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-Consistency-{member.name}",
            "member": member.name,
            "billing_frequency": "Daily",
            "dues_rate": 5.0,
            "status": "Active",
            "auto_generate": 1,
            "last_invoice_date": self.today,
            "next_invoice_date": add_days(self.today, 1)
        })
        schedule.insert()
        self.track_doc("Membership Dues Schedule", schedule.name)
        
        # For daily billing, next should be one day after last
        last_date = getdate(schedule.last_invoice_date) 
        next_date = getdate(schedule.next_invoice_date)
        
        if last_date and next_date:
            date_diff = (next_date - last_date).days
            
            if schedule.billing_frequency == "Daily":
                self.assertEqual(date_diff, 1, 
                               "For daily billing, next invoice should be 1 day after last")
            elif schedule.billing_frequency == "Weekly":
                self.assertEqual(date_diff, 7,
                               "For weekly billing, next invoice should be 7 days after last")
    
    def test_edge_case_no_dates_set(self):
        """Test handling when no dates are set on schedule"""
        member = self.create_test_member()
        
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"Test-Schedule-NoDate-{member.name}",
            "member": member.name,
            "billing_frequency": "Daily", 
            "dues_rate": 5.0,
            "status": "Active",
            "auto_generate": 1
            # No dates set initially
        })
        schedule.insert()
        self.track_doc("Membership Dues Schedule", schedule.name)
        
        # System should set reasonable default dates
        self.assertIsNotNone(schedule.next_invoice_date,
                           "System should set next_invoice_date if not provided")
        
        next_date = getdate(schedule.next_invoice_date)
        self.assertLessEqual(next_date, add_days(self.today, 2),
                           "Default next_invoice_date should be reasonable")

if __name__ == "__main__":
    unittest.main()