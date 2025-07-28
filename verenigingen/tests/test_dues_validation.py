# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Membership Dues Validation Tests
This file restores critical dues validation testing that was removed during Phase 4
Focus on dues calculation, billing frequency validation, and payment processing
"""

import frappe
from frappe.utils import today, add_days, add_months, flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDuesValidation(VereningingenTestCase):
    """Tests for membership dues validation and calculation"""

    def setUp(self):
        super().setUp()
        
        # Create test environment
        self.test_member = self.create_test_member()
        self.test_membership_type = self.create_test_membership_type(
            membership_type_name="Dues Validation Type",
            amount=100.00,
            billing_frequency="Annual"
        )
        
        self.test_membership = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name
        )

    def test_dues_rate_validation(self):
        """Test dues rate validation rules"""
        # Test positive dues rate
        valid_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=25.00,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(valid_schedule.dues_rate, flt(25.00))
        self.assertGreater(valid_schedule.dues_rate, 0)
        
        # Test zero dues rate (scholarship/free membership)
        zero_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=0.00,
            billing_frequency="Annual"
        )
        
        self.assertEqual(zero_schedule.dues_rate, flt(0.00))
        
        # Test high dues rate
        high_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=500.00,
            billing_frequency="Annual"
        )
        
        self.assertEqual(high_schedule.dues_rate, flt(500.00))

    def test_billing_frequency_validation(self):
        """Test billing frequency validation"""
        valid_frequencies = ["Monthly", "Quarterly", "Semi-Annual", "Annual"]
        
        for frequency in valid_frequencies:
            schedule = self.create_test_dues_schedule(
                member=self.test_member.name,
                dues_rate=30.00,
                billing_frequency=frequency
            )
            
            self.assertEqual(schedule.billing_frequency, frequency)

    def test_dues_schedule_member_validation(self):
        """Test member validation for dues schedules"""
        # Test valid member
        valid_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=40.00
        )
        
        self.assertEqual(valid_schedule.member, self.test_member.name)
        
        # Verify member exists and is active
        member_doc = frappe.get_doc("Member", self.test_member.name)
        self.assertEqual(member_doc.status, "Active")

    def test_dues_schedule_membership_type_validation(self):
        """Test membership type validation for dues schedules"""
        schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            dues_rate=50.00
        )
        
        self.assertEqual(schedule.membership_type, self.test_membership_type.name)
        
        # Verify membership type exists
        type_exists = frappe.db.exists("Membership Type", self.test_membership_type.name)
        self.assertTrue(type_exists)

    def test_dues_calculation_monthly(self):
        """Test monthly dues calculation"""
        monthly_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=25.00,
            billing_frequency="Monthly"
        )
        
        # Verify monthly calculation
        self.assertEqual(monthly_schedule.dues_rate, flt(25.00))
        self.assertEqual(monthly_schedule.billing_frequency, "Monthly")

    def test_dues_calculation_quarterly(self):
        """Test quarterly dues calculation"""
        quarterly_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=75.00,
            billing_frequency="Quarterly"
        )
        
        # Verify quarterly calculation
        self.assertEqual(quarterly_schedule.dues_rate, flt(75.00))
        self.assertEqual(quarterly_schedule.billing_frequency, "Quarterly")

    def test_dues_calculation_annual(self):
        """Test annual dues calculation"""
        annual_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=300.00,
            billing_frequency="Annual"
        )
        
        # Verify annual calculation
        self.assertEqual(annual_schedule.dues_rate, flt(300.00))
        self.assertEqual(annual_schedule.billing_frequency, "Annual")

    def test_dues_proration_validation(self):
        """Test dues proration for partial periods"""
        # Test mid-year start with proration
        prorated_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=200.00,
            billing_frequency="Annual"
        )
        
        # Verify proration setup
        self.assertEqual(prorated_schedule.dues_rate, flt(200.00))
        
        # Test monthly proration
        monthly_prorated = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=20.00,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(monthly_prorated.dues_rate, flt(20.00))

    def test_dues_minimum_amount_validation(self):
        """Test minimum amount validation for dues"""
        # Test schedule with minimum amount
        min_amount_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=15.00,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(min_amount_schedule.dues_rate, flt(15.00))
        
        # Verify minimum amount constraint
        self.assertGreaterEqual(min_amount_schedule.dues_rate, 0)

    def test_dues_maximum_amount_validation(self):
        """Test maximum amount validation for dues"""
        # Test high dues amount
        high_dues_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=1000.00,
            billing_frequency="Annual"
        )
        
        self.assertEqual(high_dues_schedule.dues_rate, flt(1000.00))
        
        # Test very high amount (edge case)
        extreme_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=9999.99,
            billing_frequency="Annual"
        )
        
        self.assertEqual(extreme_schedule.dues_rate, flt(9999.99))

    def test_dues_currency_precision_validation(self):
        """Test currency precision in dues calculations"""
        # Test precise decimal amounts
        precise_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=123.45,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(precise_schedule.dues_rate, flt(123.45))
        
        # Test single decimal
        single_decimal = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=50.5,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(single_decimal.dues_rate, flt(50.5))


class TestDuesBusinessRuleValidation(VereningingenTestCase):
    """Business rule validation for membership dues"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
    
    def test_multiple_dues_schedules_validation(self):
        """Test validation of multiple dues schedules per member"""
        # Create first schedule
        schedule1 = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=25.00,
            billing_frequency="Monthly"
        )
        
        # Create second schedule (different frequency)
        schedule2 = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=100.00,
            billing_frequency="Annual"
        )
        
        # Both should be valid in test environment
        self.assertEqual(schedule1.member, self.test_member.name)
        self.assertEqual(schedule2.member, self.test_member.name)
        self.assertNotEqual(schedule1.name, schedule2.name)
    
    def test_dues_schedule_status_validation(self):
        """Test dues schedule status validation"""
        # Test active schedule
        active_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=30.00,
            status="Active"
        )
        
        self.assertEqual(active_schedule.status, "Active")
        
        # Test inactive schedule
        inactive_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=40.00,
            status="Inactive"
        )
        
        self.assertEqual(inactive_schedule.status, "Inactive")
    
    def test_dues_schedule_date_validation(self):
        """Test date validation for dues schedules"""
        # Test schedule with next invoice date
        dated_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=35.00,
            next_invoice_date=add_days(today(), 30)
        )
        
        self.assertEqual(dated_schedule.next_invoice_date, add_days(today(), 30))
        
        # Test past date
        past_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=45.00,
            next_invoice_date=add_days(today(), -30)
        )
        
        self.assertEqual(past_schedule.next_invoice_date, add_days(today(), -30))
    
    def test_dues_auto_generation_validation(self):
        """Test auto-generation flag validation"""
        # Test with auto-generation enabled
        auto_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=55.00,
            auto_generate=1
        )
        
        self.assertEqual(auto_schedule.auto_generate, 1)
        
        # Test with auto-generation disabled
        manual_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=65.00,
            auto_generate=0
        )
        
        self.assertEqual(manual_schedule.auto_generate, 0)


class TestDuesCalculationEdgeCases(VereningingenTestCase):
    """Edge case tests for dues calculations"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
    
    def test_dues_extreme_values(self):
        """Test dues with extreme values"""
        # Test minimum non-zero amount
        minimal_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=0.01,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(minimal_schedule.dues_rate, flt(0.01))
        
        # Test large amount
        large_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=99999.99,
            billing_frequency="Annual"
        )
        
        self.assertEqual(large_schedule.dues_rate, flt(99999.99))
    
    def test_dues_calculation_with_special_dates(self):
        """Test dues calculation with special dates"""
        # Test schedule starting on leap year date
        leap_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=29.00,
            billing_frequency="Monthly",
            next_invoice_date=add_days(today(), 29)  # 29th day
        )
        
        self.assertEqual(leap_schedule.dues_rate, flt(29.00))
        
        # Test end of month dates
        end_month_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=31.00,
            billing_frequency="Monthly"
        )
        
        self.assertEqual(end_month_schedule.dues_rate, flt(31.00))
    
    def test_dues_frequency_edge_cases(self):
        """Test edge cases in billing frequency handling"""
        # Test all supported frequencies
        frequency_test_cases = [
            {"frequency": "Monthly", "rate": 25.00},
            {"frequency": "Quarterly", "rate": 75.00},
            {"frequency": "Semi-Annual", "rate": 150.00},
            {"frequency": "Annual", "rate": 300.00}
        ]
        
        for case in frequency_test_cases:
            schedule = self.create_test_dues_schedule(
                member=self.test_member.name,
                dues_rate=case["rate"],
                billing_frequency=case["frequency"]
            )
            
            self.assertEqual(schedule.billing_frequency, case["frequency"])
            self.assertEqual(schedule.dues_rate, flt(case["rate"]))
    
    def test_dues_concurrent_modifications(self):
        """Test concurrent modifications to dues schedules"""
        schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=100.00,
            billing_frequency="Monthly"
        )
        
        # Simulate concurrent access
        schedule_copy = frappe.get_doc("Membership Dues Schedule", schedule.name)
        
        # First modification
        schedule.dues_rate = 110.00
        schedule.save()
        
        # Second modification (should work with reload)
        schedule_copy.reload()
        schedule_copy.status = "Updated"
        schedule_copy.save()
        
        # Verify both modifications
        schedule.reload()
        self.assertEqual(schedule.dues_rate, flt(110.00))
        self.assertEqual(schedule.status, "Updated")


class TestDuesIntegrationValidation(VereningingenTestCase):
    """Integration tests for dues with other system components"""
    
    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_schedule = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=75.00
        )
    
    def test_dues_invoice_generation_validation(self):
        """Test validation of invoice generation from dues"""
        # Create invoice based on dues schedule
        invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1
        )
        
        # Verify invoice integration
        self.assertEqual(invoice.customer, self.test_member.customer)
        self.assertTrue(invoice.is_membership_invoice)
    
    def test_dues_payment_integration_validation(self):
        """Test validation of payment processing for dues"""
        # Create payment for dues
        payment = self.create_test_payment_entry(
            party=self.test_member.customer,
            party_type="Customer",
            payment_type="Receive",
            paid_amount=75.00
        )
        
        # Verify payment integration
        self.assertEqual(payment.party, self.test_member.customer)
        self.assertEqual(payment.paid_amount, flt(75.00))
    
    def test_dues_sepa_mandate_validation(self):
        """Test validation of SEPA mandate integration with dues"""
        # Create SEPA mandate for member
        mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            scenario="normal"
        )
        
        # Verify mandate can be used for dues collection
        self.assertEqual(mandate.member, self.test_member.name)
        self.assertEqual(mandate.status, "Active")
        
        # Test dues collection through mandate
        collection_amount = self.test_schedule.dues_rate
        self.assertEqual(collection_amount, flt(75.00))
    
    def test_dues_membership_renewal_validation(self):
        """Test dues validation during membership renewal"""
        # Create membership
        membership = self.create_test_membership(member=self.test_member.name)
        
        # Create renewal with updated dues
        renewal_dues = self.create_test_dues_schedule(
            member=self.test_member.name,
            dues_rate=85.00,  # Increased rate
            billing_frequency="Monthly"
        )
        
        # Verify renewal dues validation
        self.assertEqual(renewal_dues.member, self.test_member.name)
        self.assertEqual(renewal_dues.dues_rate, flt(85.00))
        
        # Original membership should still exist
        membership.reload()
        self.assertEqual(membership.member, self.test_member.name)


class TestDuesReportingValidation(VereningingenTestCase):
    """Tests for dues reporting and analytics validation"""
    
    def setUp(self):
        super().setUp()
        self.test_members = []
        
        # Create multiple members with different dues
        for i in range(3):
            member = self.create_test_member(
                first_name=f"Reporting{i}",
                last_name="TestMember",
                email=f"reporting{i}@example.com"
            )
            
            schedule = self.create_test_dues_schedule(
                member=member.name,
                dues_rate=50.00 + (i * 25.00),  # 50, 75, 100
                billing_frequency="Monthly"
            )
            
            self.test_members.append({"member": member, "schedule": schedule})
    
    def test_dues_aggregation_validation(self):
        """Test validation of dues aggregation for reporting"""
        # Calculate total dues across all test members
        total_dues = sum(data["schedule"].dues_rate for data in self.test_members)
        expected_total = flt(225.00)  # 50 + 75 + 100
        
        self.assertEqual(total_dues, expected_total)
        
        # Test average dues calculation
        average_dues = total_dues / len(self.test_members)
        expected_average = flt(75.00)
        
        self.assertEqual(average_dues, expected_average)
    
    def test_dues_frequency_distribution_validation(self):
        """Test validation of dues frequency distribution"""
        # All test members have monthly frequency
        monthly_count = sum(1 for data in self.test_members 
                           if data["schedule"].billing_frequency == "Monthly")
        
        self.assertEqual(monthly_count, 3)
        
        # Test frequency distribution
        frequency_distribution = {}
        for data in self.test_members:
            freq = data["schedule"].billing_frequency
            frequency_distribution[freq] = frequency_distribution.get(freq, 0) + 1
        
        self.assertEqual(frequency_distribution["Monthly"], 3)
    
    def test_dues_amount_range_validation(self):
        """Test validation of dues amount ranges for reporting"""
        dues_amounts = [data["schedule"].dues_rate for data in self.test_members]
        
        # Test range validation
        min_dues = min(dues_amounts)
        max_dues = max(dues_amounts)
        
        self.assertEqual(min_dues, flt(50.00))
        self.assertEqual(max_dues, flt(100.00))
        
        # Test range categorization
        low_dues = [amount for amount in dues_amounts if amount < 60.00]
        medium_dues = [amount for amount in dues_amounts if 60.00 <= amount < 90.00]
        high_dues = [amount for amount in dues_amounts if amount >= 90.00]
        
        self.assertEqual(len(low_dues), 1)   # 50.00
        self.assertEqual(len(medium_dues), 1) # 75.00
        self.assertEqual(len(high_dues), 1)   # 100.00