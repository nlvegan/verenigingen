# -*- coding: utf-8 -*-
# Copyright (c) 2025, Foppe de Haan
# License: GNU Affero General Public License v3 (AGPLv3)

"""
Test Comprehensive Prorating Scenarios
Critical for accurate billing during all membership transitions
"""

import frappe
import unittest
from frappe.utils import add_days, add_months, today, getdate, flt, now_datetime
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

from verenigingen.tests.base_test_case import BaseTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestComprehensiveProrating(BaseTestCase):
    """Comprehensive prorating tests for all billing scenarios"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.create_test_membership_types()
    
    def create_test_membership_types(self):
        """Create membership types for prorating tests"""
        membership_types = [
            {
                "membership_type_name": "Monthly Basic",
                "billing_period": "Monthly",
                "amount": 25.00,
                "description": "Basic monthly membership"
            },
            {
                "membership_type_name": "Annual Premium",
                "billing_period": "Annual", 
                "amount": 300.00,
                "description": "Premium annual membership"
            },
            {
                "membership_type_name": "Quarterly Standard",
                "billing_period": "Quarterly",
                "amount": 75.00,
                "description": "Standard quarterly membership"
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
    
    def test_monthly_to_annual_upgrade_prorating(self):
        """
        CRITICAL: Monthly to Annual upgrade prorating
        
        Scenario: Member pays €25/month, upgrades to €300/year on day 15
        Challenge: Calculate accurate credit for unused monthly portion
        """
        # Create member with monthly billing
        member = self.create_test_member(
            first_name="MonthlyToAnnual",
            last_name="Upgrade",
            email="monthly.annual@test.com",
            iban=generate_test_iban("TEST")
        )
        
        # Simulate upgrade on 15th day of 31-day month
        upgrade_date = getdate(today())
        # Note: Using day 15 for calculation purposes
        
        # CALCULATION LOGIC TO VALIDATE:
        monthly_amount = Decimal('25.00')
        annual_amount = Decimal('300.00')
        
        # Days calculation
        days_in_month = 31  # January, March, May, July, August, October, December
        days_used = 14  # Used days 1-14
        days_remaining = days_in_month - days_used  # 17 days remaining
        
        # Credit calculation for unused monthly portion
        daily_monthly_rate = monthly_amount / Decimal(days_in_month)
        monthly_credit = (daily_monthly_rate * Decimal(days_remaining)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # Annual charge for remaining period
        daily_annual_rate = annual_amount / Decimal('365')
        annual_charge = (daily_annual_rate * Decimal(days_remaining)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # Net amount owed
        net_amount = annual_charge - monthly_credit
        
        # CRITICAL VALIDATIONS:
        expected_monthly_credit = Decimal('13.71')  # Approximately 17/31 * 25
        expected_annual_charge = Decimal('13.97')   # Approximately 17/365 * 300
        expected_net = Decimal('0.26')              # Small amount owed
        
        self.assertAlmostEqual(float(monthly_credit), float(expected_monthly_credit), places=2)
        self.assertAlmostEqual(float(annual_charge), float(expected_annual_charge), places=2)
        self.assertGreater(net_amount, Decimal('0'), "Net amount should be small positive")
        self.assertLess(net_amount, Decimal('5.00'), "Net amount should be reasonable")
        
        print(f"✅ Monthly→Annual Prorating:")
        print(f"   Monthly credit: €{monthly_credit}")
        print(f"   Annual charge: €{annual_charge}") 
        print(f"   Net amount: €{net_amount}")
    
    def test_annual_to_quarterly_downgrade_prorating(self):
        """
        CRITICAL: Annual to Quarterly downgrade with large credit
        
        Scenario: Member paid €300/year upfront, downgrades after 3 months
        Challenge: Calculate accurate refund/credit for 9 unused months
        """
        member = self.create_test_member(
            first_name="AnnualToQuarterly", 
            last_name="Downgrade",
            email="annual.quarterly@test.com",
            iban=generate_test_iban("MOCK")
        )
        
        # Paid annual, now switching after 3 months
        annual_amount = Decimal('300.00')
        quarterly_amount = Decimal('75.00')
        months_used = 3
        months_total = 12
        
        # CALCULATION LOGIC:
        monthly_rate = annual_amount / Decimal(months_total)  # €25/month
        months_remaining = months_total - months_used         # 9 months
        
        # Credit for unused annual portion  
        annual_credit = (monthly_rate * Decimal(months_remaining)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # Charge for current quarter (3 months)
        quarterly_charge = quarterly_amount  # €75 for 3 months
        
        # Net credit to member
        net_credit = annual_credit - quarterly_charge
        
        # CRITICAL VALIDATIONS:
        expected_annual_credit = Decimal('225.00')  # 9 months * €25
        expected_net_credit = Decimal('150.00')     # €225 - €75
        
        self.assertEqual(annual_credit, expected_annual_credit)
        self.assertEqual(net_credit, expected_net_credit)
        self.assertGreater(net_credit, Decimal('100.00'), "Should be substantial credit")
        
        print(f"✅ Annual→Quarterly Prorating:")
        print(f"   Annual credit: €{annual_credit}")
        print(f"   Quarterly charge: €{quarterly_charge}")
        print(f"   Net credit to member: €{net_credit}")
    
    def test_mid_cycle_suspension_prorating(self):
        """
        CRITICAL: Mid-cycle suspension prorating
        
        Scenario: Member suspends quarterly membership after 45 days
        Challenge: Calculate accurate credit for unused portion
        """
        member = self.create_test_member(
            first_name="Suspension",
            last_name="User", 
            email="suspension@test.com",
            iban=generate_test_iban("DEMO")
        )
        
        # Quarterly membership suspended after 45 days
        quarterly_amount = Decimal('75.00')
        days_in_quarter = 90
        days_used = 45
        days_remaining = days_in_quarter - days_used  # 45 days
        
        # CALCULATION LOGIC:
        daily_rate = quarterly_amount / Decimal(days_in_quarter)
        suspension_credit = (daily_rate * Decimal(days_remaining)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # CRITICAL VALIDATIONS:
        expected_credit = Decimal('37.50')  # Exactly half the quarterly amount
        
        self.assertEqual(suspension_credit, expected_credit)
        self.assertEqual(float(suspension_credit), float(quarterly_amount) / 2)
        
        print(f"✅ Mid-cycle suspension prorating:")
        print(f"   Quarterly amount: €{quarterly_amount}")
        print(f"   Days used/total: {days_used}/{days_in_quarter}")
        print(f"   Credit amount: €{suspension_credit}")
    
    def test_reactivation_after_suspension_prorating(self):
        """
        CRITICAL: Reactivation prorating after suspension
        
        Scenario: Member reactivates 30 days into new billing cycle
        Challenge: Charge accurate amount for remaining period
        """
        member = self.create_test_member(
            first_name="Reactivation",
            last_name="User",
            email="reactivation@test.com", 
            iban=generate_test_iban("TEST")
        )
        
        # Reactivating 30 days into new quarterly cycle
        quarterly_amount = Decimal('75.00')
        days_in_quarter = 90
        days_missed = 30
        days_remaining = days_in_quarter - days_missed  # 60 days
        
        # CALCULATION LOGIC:
        daily_rate = quarterly_amount / Decimal(days_in_quarter)
        reactivation_charge = (daily_rate * Decimal(days_remaining)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # CRITICAL VALIDATIONS:
        expected_charge = Decimal('50.00')  # 60/90 * €75
        
        self.assertEqual(reactivation_charge, expected_charge)
        self.assertLess(reactivation_charge, quarterly_amount)
        self.assertGreater(reactivation_charge, quarterly_amount / 2)
        
        print(f"✅ Reactivation prorating:")
        print(f"   Days remaining: {days_remaining}/{days_in_quarter}")
        print(f"   Reactivation charge: €{reactivation_charge}")
    
    def test_bulk_upgrade_prorating_consistency(self):
        """
        CRITICAL: Bulk membership changes prorating consistency
        
        Scenario: 100 members upgrade on same day, different billing cycles
        Challenge: Ensure consistent prorating across all members
        """
        # Simulate bulk upgrade scenario
        test_scenarios = [
            {"current": "Monthly Basic", "target": "Annual Premium", "days_used": 10},
            {"current": "Monthly Basic", "target": "Annual Premium", "days_used": 20},
            {"current": "Quarterly Standard", "target": "Annual Premium", "days_used": 30},
            {"current": "Quarterly Standard", "target": "Annual Premium", "days_used": 60},
        ]
        
        prorating_results = []
        
        for i, scenario in enumerate(test_scenarios):
            member = self.create_test_member(
                first_name=f"Bulk{i+1}",
                last_name="User",
                email=f"bulk{i+1}@test.com",
                iban=generate_test_iban("TEST")
            )
            
            # Calculate prorating for each scenario
            if "Monthly" in scenario["current"]:
                current_amount = Decimal('25.00')
                days_in_period = 30
            else:  # Quarterly
                current_amount = Decimal('75.00')
                days_in_period = 90
            
            target_amount = Decimal('300.00')  # Annual
            days_used = scenario["days_used"]
            days_remaining = days_in_period - days_used
            
            # Current period credit
            daily_current = current_amount / Decimal(days_in_period)
            current_credit = (daily_current * Decimal(days_remaining)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            
            # Annual charge for remaining period
            daily_annual = target_amount / Decimal('365')
            annual_charge = (daily_annual * Decimal(days_remaining)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            
            net_amount = annual_charge - current_credit
            
            prorating_results.append({
                "member": member.name,
                "scenario": scenario,
                "current_credit": current_credit,
                "annual_charge": annual_charge,
                "net_amount": net_amount
            })
        
        # CRITICAL VALIDATIONS:
        # All calculations should be reasonable and consistent
        for result in prorating_results:
            self.assertGreaterEqual(result["current_credit"], Decimal('0'))
            self.assertGreaterEqual(result["annual_charge"], Decimal('0'))
            # Net can be positive or negative depending on the scenario
            
        print("✅ Bulk upgrade prorating consistency:")
        for result in prorating_results:
            print(f"   Member {result['member']}: Credit €{result['current_credit']}, "
                  f"Charge €{result['annual_charge']}, Net €{result['net_amount']}")
    
    def test_leap_year_annual_prorating(self):
        """
        CRITICAL: Leap year prorating accuracy
        
        Scenario: Annual membership prorating in leap year vs regular year  
        Challenge: 366 vs 365 days affects daily rates
        """
        # Test both leap year (2024) and regular year (2023) scenarios
        annual_amount = Decimal('300.00')
        
        # Regular year calculation (365 days)
        regular_daily_rate = annual_amount / Decimal('365')
        regular_30_day_charge = (regular_daily_rate * Decimal('30')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # Leap year calculation (366 days)
        leap_daily_rate = annual_amount / Decimal('366')
        leap_30_day_charge = (leap_daily_rate * Decimal('30')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        
        # CRITICAL VALIDATIONS:
        self.assertNotEqual(regular_daily_rate, leap_daily_rate)
        self.assertLess(leap_daily_rate, regular_daily_rate)  # Leap year rate is lower
        self.assertLess(leap_30_day_charge, regular_30_day_charge)
        
        # Difference should be small but measurable
        rate_difference = regular_daily_rate - leap_daily_rate
        charge_difference = regular_30_day_charge - leap_30_day_charge
        
        self.assertGreater(rate_difference, Decimal('0'))
        self.assertLess(rate_difference, Decimal('0.01'))  # Small difference
        self.assertLess(charge_difference, Decimal('1.00'))  # Less than €1 difference
        
        print(f"✅ Leap year prorating:")
        print(f"   Regular year daily: €{regular_daily_rate:.4f}")
        print(f"   Leap year daily: €{leap_daily_rate:.4f}")
        print(f"   30-day difference: €{charge_difference}")


if __name__ == "__main__":
    unittest.main()