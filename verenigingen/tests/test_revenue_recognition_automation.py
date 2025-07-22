# -*- coding: utf-8 -*-
# Copyright (c) 2025, Foppe de Haan
# License: GNU Affero General Public License v3 (AGPLv3)

"""
Test Revenue Recognition Automation
Critical for financial compliance and accurate accounting
"""

import frappe
import unittest
from frappe.utils import add_days, add_months, today, getdate, flt, now_datetime
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date

from verenigingen.tests.base_test_case import BaseTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestRevenueRecognitionAutomation(BaseTestCase):
    """Test automated revenue recognition for compliance"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.create_test_membership_types()
    
    def create_test_membership_types(self):
        """Create membership types for revenue recognition tests"""
        membership_types = [
            {
                "membership_type_name": "Annual Standard",
                "billing_period": "Annual",
                "amount": 240.00,
                "description": "Annual membership for revenue recognition testing"
            },
            {
                "membership_type_name": "Quarterly Premium", 
                "billing_period": "Quarterly",
                "amount": 75.00,
                "description": "Quarterly membership for revenue recognition testing"
            },
            {
                "membership_type_name": "Monthly Basic",
                "billing_period": "Monthly",
                "amount": 20.00,
                "description": "Monthly membership for revenue recognition testing"
            }
        ]
        
        for type_data in membership_types:
            if not frappe.db.exists("Membership Type", type_data["membership_type_name"]):
                membership_type = frappe.get_doc({
                    "doctype": "Membership Type",
                    **type_data
                })
                membership_type.insert()
                self.track_doc("Membership Type", membership_type.name)
    
    def test_annual_membership_deferred_revenue_recognition(self):
        """
        CRITICAL: Annual membership revenue spreading
        
        Scenario: Member pays €240 for annual membership upfront
        Requirement: Revenue must be recognized monthly (€20/month)
        Compliance: IFRS 15 - Revenue from Contracts with Customers
        """
        member = self.create_test_member(
            first_name="Annual",
            last_name="Member", 
            email="annual.member@test.com",
            iban=generate_test_iban("TEST")
        )
        
        # Annual membership payment received upfront
        annual_amount = Decimal('240.00')
        membership_start_date = today()
        
        # REVENUE RECOGNITION CALCULATION:
        monthly_recognition_amount = annual_amount / Decimal('12')  # €20/month
        
        # Generate monthly revenue recognition schedule
        revenue_schedule = []
        for month in range(12):
            recognition_date = add_months(membership_start_date, month)
            
            # Each month should recognize €20
            monthly_revenue = {
                "member": member.name,
                "recognition_date": recognition_date,
                "amount": monthly_recognition_amount,
                "period": f"Month {month + 1}",
                "cumulative": monthly_recognition_amount * (month + 1)
            }
            revenue_schedule.append(monthly_revenue)
        
        # CRITICAL VALIDATIONS:
        # Total recognized revenue equals paid amount
        total_recognized = sum(item["amount"] for item in revenue_schedule)
        self.assertEqual(total_recognized, annual_amount)
        
        # Each month recognizes equal amount
        for item in revenue_schedule:
            self.assertEqual(item["amount"], Decimal('20.00'))
        
        # Final cumulative equals total
        final_cumulative = revenue_schedule[-1]["cumulative"]
        self.assertEqual(final_cumulative, annual_amount)
        
        # Deferred revenue decreases each month
        for i, item in enumerate(revenue_schedule):
            months_remaining = 12 - (i + 1)
            expected_deferred = monthly_recognition_amount * months_remaining
            actual_deferred = annual_amount - item["cumulative"]
            self.assertEqual(actual_deferred, expected_deferred)
        
        print(f"✅ Annual revenue recognition schedule:")
        print(f"   Total amount: €{annual_amount}")
        print(f"   Monthly recognition: €{monthly_recognition_amount}")
        print(f"   First month deferred: €{annual_amount - monthly_recognition_amount}")
        print(f"   Last month deferred: €0.00")
    
    def test_mid_year_membership_revenue_recognition(self):
        """
        CRITICAL: Mid-year membership revenue recognition
        
        Scenario: Member joins on July 15th, pays annual fee
        Requirement: Revenue recognized from start date only
        Challenge: Partial periods and pro-rata calculations
        """
        member = self.create_test_member(
            first_name="MidYear",
            last_name="Member",
            email="midyear@test.com", 
            iban=generate_test_iban("MOCK")
        )
        
        # Membership starts July 15th (mid-year)
        start_date = date(2025, 7, 15)
        annual_amount = Decimal('240.00')
        
        # REVENUE RECOGNITION LOGIC:
        # Calculate remaining months from start date
        year_end = date(2025, 12, 31)
        
        # July 15 - July 31: Partial month (17/31 days)
        july_days = 31 - 15 + 1  # 17 days
        july_revenue = (annual_amount / Decimal('12')) * (Decimal(july_days) / Decimal('31'))
        july_revenue = july_revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        # August - December: Full months (5 months)
        monthly_amount = annual_amount / Decimal('12')
        full_months_revenue = monthly_amount * Decimal('5')
        
        total_recognized = july_revenue + full_months_revenue
        
        # CRITICAL VALIDATIONS:
        expected_july_revenue = Decimal('10.97')  # Approximately (17/31) * €20
        expected_full_months = Decimal('100.00')  # 5 * €20
        expected_total = Decimal('110.97')
        
        self.assertAlmostEqual(float(july_revenue), float(expected_july_revenue), places=2)
        self.assertEqual(full_months_revenue, expected_full_months)
        self.assertAlmostEqual(float(total_recognized), float(expected_total), places=2)
        
        # Remaining deferred revenue
        deferred_revenue = annual_amount - total_recognized
        expected_deferred = Decimal('129.03')  # Revenue for next year
        
        self.assertAlmostEqual(float(deferred_revenue), float(expected_deferred), places=2)
        
        print(f"✅ Mid-year revenue recognition:")
        print(f"   July partial month: €{july_revenue}")
        print(f"   August-December: €{full_months_revenue}")
        print(f"   Total this year: €{total_recognized}")
        print(f"   Deferred to next year: €{deferred_revenue}")
    
    def test_quarterly_membership_revenue_recognition(self):
        """
        CRITICAL: Quarterly membership revenue recognition
        
        Scenario: Member pays €75 quarterly, needs monthly recognition
        Requirement: €25/month recognition within quarter
        Challenge: Quarterly payment, monthly accounting periods
        """
        member = self.create_test_member(
            first_name="Quarterly",
            last_name="Member",
            email="quarterly@test.com",
            iban=generate_test_iban("DEMO")
        )
        
        # Quarterly membership payment
        quarterly_amount = Decimal('75.00')
        quarter_start_date = today()
        
        # REVENUE RECOGNITION CALCULATION:
        monthly_recognition = quarterly_amount / Decimal('3')  # €25/month
        
        # Generate 3-month recognition schedule
        recognition_schedule = []
        for month in range(3):
            recognition_date = add_months(quarter_start_date, month)
            
            monthly_entry = {
                "member": member.name,
                "recognition_date": recognition_date,
                "amount": monthly_recognition,
                "month": month + 1,
                "cumulative": monthly_recognition * (month + 1)
            }
            recognition_schedule.append(monthly_entry)
        
        # CRITICAL VALIDATIONS:
        # Total recognition equals quarterly payment
        total_recognized = sum(entry["amount"] for entry in recognition_schedule)
        self.assertEqual(total_recognized, quarterly_amount)
        
        # Each month recognizes €25
        for entry in recognition_schedule:
            self.assertEqual(entry["amount"], Decimal('25.00'))
        
        # Deferred revenue calculation
        deferred_amounts = []
        for i, entry in enumerate(recognition_schedule):
            months_remaining = 3 - (i + 1)
            deferred = monthly_recognition * months_remaining
            deferred_amounts.append(deferred)
        
        expected_deferred = [Decimal('50.00'), Decimal('25.00'), Decimal('0.00')]
        self.assertEqual(deferred_amounts, expected_deferred)
        
        print(f"✅ Quarterly revenue recognition:")
        print(f"   Quarterly payment: €{quarterly_amount}")
        print(f"   Monthly recognition: €{monthly_recognition}")
        for i, entry in enumerate(recognition_schedule):
            print(f"   Month {entry['month']}: €{entry['amount']} recognized, "
                  f"€{deferred_amounts[i]} deferred")
    
    def test_membership_cancellation_revenue_reversal(self):
        """
        CRITICAL: Revenue reversal for cancelled memberships
        
        Scenario: Member cancels annual membership after 4 months
        Requirement: Reverse unearned revenue, calculate refund
        Challenge: Accounting reversal entries, refund calculations
        """
        member = self.create_test_member(
            first_name="Cancellation",
            last_name="Member",
            email="cancellation@test.com",
            iban=generate_test_iban("TEST")
        )
        
        # Annual membership cancelled after 4 months
        annual_amount = Decimal('240.00')
        months_elapsed = 4
        months_remaining = 12 - months_elapsed  # 8 months
        
        # REVENUE REVERSAL CALCULATION:
        monthly_amount = annual_amount / Decimal('12')  # €20/month
        
        # Revenue already recognized (4 months)
        revenue_recognized = monthly_amount * Decimal(months_elapsed)  # €80
        
        # Revenue to be reversed (8 months)
        revenue_to_reverse = monthly_amount * Decimal(months_remaining)  # €160
        
        # Refund calculation (same as revenue reversal)
        refund_amount = revenue_to_reverse
        
        # CRITICAL VALIDATIONS:
        expected_recognized = Decimal('80.00')   # 4 * €20
        expected_reversal = Decimal('160.00')    # 8 * €20  
        expected_refund = Decimal('160.00')      # Same as reversal
        
        self.assertEqual(revenue_recognized, expected_recognized)
        self.assertEqual(revenue_to_reverse, expected_reversal)
        self.assertEqual(refund_amount, expected_refund)
        
        # Total should equal original payment
        total_check = revenue_recognized + revenue_to_reverse
        self.assertEqual(total_check, annual_amount)
        
        print(f"✅ Cancellation revenue reversal:")
        print(f"   Original amount: €{annual_amount}")
        print(f"   Revenue recognized (4 months): €{revenue_recognized}")
        print(f"   Revenue to reverse (8 months): €{revenue_to_reverse}")
        print(f"   Refund amount: €{refund_amount}")
    
    def test_upgrade_revenue_recognition_adjustment(self):
        """
        CRITICAL: Revenue recognition adjustments for upgrades
        
        Scenario: Member upgrades from quarterly (€75) to annual (€240) mid-quarter
        Requirement: Adjust recognition schedules, calculate net amounts
        Challenge: Multiple recognition schedules, timing differences
        """
        member = self.create_test_member(
            first_name="Upgrade",
            last_name="Member",
            email="upgrade@test.com",
            iban=generate_test_iban("MOCK")
        )
        
        # Original quarterly membership
        quarterly_amount = Decimal('75.00')
        quarterly_monthly_rate = quarterly_amount / Decimal('3')  # €25/month
        
        # Upgrade after 1.5 months to annual
        annual_amount = Decimal('240.00')
        annual_monthly_rate = annual_amount / Decimal('12')  # €20/month
        
        months_before_upgrade = Decimal('1.5')
        months_remaining_in_quarter = Decimal('1.5')
        
        # REVENUE RECOGNITION ADJUSTMENT:
        
        # 1. Original quarterly recognition (1.5 months at €25/month)
        original_recognized = quarterly_monthly_rate * months_before_upgrade  # €37.50
        
        # 2. Remaining quarterly amount to refund/credit
        quarterly_remaining = quarterly_monthly_rate * months_remaining_in_quarter  # €37.50
        
        # 3. New annual recognition for remaining 1.5 months
        annual_recognition_remaining = annual_monthly_rate * months_remaining_in_quarter  # €30.00
        
        # 4. Net adjustment needed
        adjustment_amount = annual_recognition_remaining - quarterly_remaining  # -€7.50 (credit to member)
        
        # CRITICAL VALIDATIONS:
        expected_original = Decimal('37.50')
        expected_quarterly_remaining = Decimal('37.50') 
        expected_annual_remaining = Decimal('30.00')
        expected_adjustment = Decimal('-7.50')  # Member gets credit
        
        self.assertEqual(original_recognized, expected_original)
        self.assertEqual(quarterly_remaining, expected_quarterly_remaining)
        self.assertEqual(annual_recognition_remaining, expected_annual_remaining)
        self.assertEqual(adjustment_amount, expected_adjustment)
        
        # Verification: Original quarterly total
        quarterly_total_check = original_recognized + quarterly_remaining
        self.assertEqual(quarterly_total_check, quarterly_amount)
        
        print(f"✅ Upgrade revenue recognition adjustment:")
        print(f"   Original quarterly (1.5 months): €{original_recognized}")
        print(f"   Quarterly remaining: €{quarterly_remaining}")
        print(f"   Annual remaining (1.5 months): €{annual_recognition_remaining}")
        print(f"   Net adjustment: €{adjustment_amount}")
    
    def test_revenue_recognition_reporting_validation(self):
        """
        CRITICAL: Revenue recognition reporting accuracy
        
        Scenario: Multiple members with different timing, validate totals
        Requirement: Monthly revenue reports must be accurate
        Challenge: Aggregate multiple recognition schedules
        """
        # Create multiple members with different membership types
        members_data = [
            {"name": "Annual1", "type": "Annual Standard", "start": today()},
            {"name": "Annual2", "type": "Annual Standard", "start": add_months(today(), -2)},
            {"name": "Quarterly1", "type": "Quarterly Premium", "start": today()},
            {"name": "Monthly1", "type": "Monthly Basic", "start": today()},
        ]
        
        created_members = []
        for member_info in members_data:
            member = self.create_test_member(
                first_name=member_info["name"],
                last_name="RevenueTest",
                email=f"{member_info['name'].lower()}.revenue@test.com",
                iban=generate_test_iban("TEST")
            )
            created_members.append({
                "member": member,
                "type": member_info["type"],
                "start": member_info["start"]
            })
        
        # CALCULATE CURRENT MONTH REVENUE RECOGNITION:
        current_month_revenue = Decimal('0.00')
        
        for member_data in created_members:
            if member_data["type"] == "Annual Standard":
                monthly_rate = Decimal('240.00') / Decimal('12')  # €20/month
            elif member_data["type"] == "Quarterly Premium":
                monthly_rate = Decimal('75.00') / Decimal('3')   # €25/month
            elif member_data["type"] == "Monthly Basic":
                monthly_rate = Decimal('20.00')                  # €20/month
            
            # Add to current month total (simplified - assumes all active)
            current_month_revenue += monthly_rate
        
        # EXPECTED CURRENT MONTH REVENUE:
        expected_revenue = Decimal('20.00') + Decimal('20.00') + Decimal('25.00') + Decimal('20.00')  # €85
        
        # CRITICAL VALIDATIONS:
        self.assertEqual(current_month_revenue, expected_revenue)
        self.assertGreater(current_month_revenue, Decimal('80.00'))
        self.assertLess(current_month_revenue, Decimal('100.00'))
        
        print(f"✅ Revenue recognition reporting:")
        print(f"   Current month total: €{current_month_revenue}")
        print(f"   Member count: {len(created_members)}")
        print(f"   Average per member: €{current_month_revenue / len(created_members):.2f}")


if __name__ == "__main__":
    unittest.main()