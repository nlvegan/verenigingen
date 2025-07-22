# -*- coding: utf-8 -*-
# Copyright (c) 2025, Foppe de Haan
# License: GNU Affero General Public License v3 (AGPLv3)

"""
Test Billing Transitions
Ensures no duplicate billing when members switch between billing frequencies
"""

import frappe
import unittest
from frappe.utils import add_days, today, getdate, flt
from decimal import Decimal

from verenigingen.tests.base_test_case import BaseTestCase
from verenigingen.tests.fixtures.billing_transition_personas import (
    BillingTransitionPersonas,
    extract_billing_period,
    periods_overlap,
    calculate_overlap_days
)


class TestBillingTransitions(BaseTestCase):
    """Test billing frequency transitions to prevent duplicate charges"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        self.personas = {}
        
        # Create required membership types for testing
        self.create_test_membership_types()
        
    def tearDown(self):
        """Clean up test data"""
        # Clean up personas
        for persona_name, persona_data in self.personas.items():
            if persona_data:
                # Clean up in reverse order
                for doc_type in ["Contribution Amendment Request", "Membership Dues Schedule", 
                               "Sales Invoice", "Membership", "Member"]:
                    if doc_type in persona_data:
                        try:
                            doc = persona_data[doc_type]
                            if hasattr(doc, 'name'):
                                frappe.delete_doc(doc_type, doc.name, force=True)
                        except Exception:
                            pass
        
        super().tearDown()
    
    def create_test_membership_types(self):
        """Create the membership types needed for billing transition tests"""
        membership_types = [
            {
                "membership_type_name": "Monthly Standard",
                "billing_period": "Monthly",
                "amount": 20.00,
                "description": "Standard monthly membership"
            },
            {
                "membership_type_name": "Annual Standard",
                "billing_period": "Annual", 
                "amount": 200.00,
                "description": "Standard annual membership"
            },
            {
                "membership_type_name": "Annual Premium",
                "billing_period": "Annual",
                "amount": 240.00,
                "description": "Premium annual membership"
            },
            {
                "membership_type_name": "Quarterly Premium",
                "billing_period": "Quarterly",
                "amount": 80.00,
                "description": "Premium quarterly membership"
            },
            {
                "membership_type_name": "Quarterly Basic",
                "billing_period": "Quarterly",
                "amount": 75.00,
                "description": "Basic quarterly membership"
            },
            {
                "membership_type_name": "Monthly Basic",
                "billing_period": "Monthly",
                "amount": 30.00,
                "description": "Basic monthly membership"
            },
            {
                "membership_type_name": "Daily Access",
                "billing_period": "Daily",
                "amount": 1.00,
                "description": "Daily access membership"
            },
            {
                "membership_type_name": "Annual Access",
                "billing_period": "Annual",
                "amount": 300.00,
                "description": "Annual access membership"
            },
            {
                "membership_type_name": "Flexible Membership",
                "billing_period": "Monthly",
                "amount": 25.00,
                "description": "Flexible membership for testing transitions"
            }
        ]
        
        for type_data in membership_types:
            # Check if it already exists
            if not frappe.db.exists("Membership Type", type_data["membership_type_name"]):
                membership_type = frappe.get_doc({
                    "doctype": "Membership Type",
                    **type_data
                })
                membership_type.insert()
                self.track_doc("Membership Type", membership_type.name)
    
    def test_monthly_to_annual_transition(self):
        """Test transition from monthly to annual billing"""
        # Create test persona
        mike = BillingTransitionPersonas.create_monthly_to_annual_mike()
        self.personas["mike"] = mike
        
        # Track for cleanup
        self.track_doc("Member", mike["member"].name)
        self.track_doc("Membership", mike["membership"].name)
        self.track_doc("Membership Dues Schedule", mike["monthly_schedule"].name)
        self.track_doc("Contribution Amendment Request", mike["transition_request"].name)
        
        # Simulate approval of transition
        transition = mike["transition_request"]
        transition.status = "Approved"
        transition.approved_by = frappe.session.user
        transition.approved_date = today()
        transition.save()
        
        # Apply the transition
        self._apply_billing_transition(transition)
        
        # Validate no duplicate billing
        validation = BillingTransitionPersonas.validate_no_duplicate_billing(
            mike["member"].name,
            add_days(today(), -60),
            add_days(today(), 60)
        )
        
        self.assertTrue(validation["valid"], 
                       f"Duplicate billing detected: {validation.get('message')}")
        
        # Verify new annual schedule created
        new_schedule = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": mike["member"].name,
                "billing_frequency": "Annual",
                "status": "Active"
            },
            limit=1
        )
        
        self.assertEqual(len(new_schedule), 1, "Annual schedule should be created")
        
        # Verify old monthly schedule is inactive
        old_schedule = frappe.get_doc("Membership Dues Schedule", mike["monthly_schedule"].name)
        self.assertEqual(old_schedule.status, "Inactive", "Monthly schedule should be inactive")
        
        # Verify credit applied
        annual_schedule = frappe.get_doc("Membership Dues Schedule", new_schedule[0].name)
        self.assertEqual(flt(annual_schedule.accumulated_credit), 10.00, 
                        "Prorated credit should be applied")
    
    def test_annual_to_quarterly_with_credit(self):
        """Test transition from annual to quarterly with proper credit calculation"""
        # Create test persona
        anna = BillingTransitionPersonas.create_annual_to_quarterly_anna()
        self.personas["anna"] = anna
        
        # Track for cleanup
        self.track_doc("Member", anna["member"].name)
        self.track_doc("Membership", anna["membership"].name)
        self.track_doc("Membership Dues Schedule", anna["annual_schedule"].name)
        self.track_doc("Contribution Amendment Request", anna["transition_request"].name)
        
        # Apply transition
        transition = anna["transition_request"]
        transition.status = "Approved"
        transition.save()
        
        self._apply_billing_transition(transition)
        
        # Check credit calculation
        # Anna paid 240 for year, used 3 months (60), should get 180 credit
        self.assertEqual(flt(transition.prorated_credit), 180.00, 
                        "Credit calculation incorrect")
        
        # Verify quarterly schedule with credit
        quarterly_schedule = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": anna["member"].name,
                "billing_frequency": "Quarterly",
                "status": "Active"
            },
            fields=["name", "accumulated_credit", "next_invoice_date"],
            limit=1
        )
        
        self.assertEqual(len(quarterly_schedule), 1, "Quarterly schedule should exist")
        self.assertEqual(flt(quarterly_schedule[0].accumulated_credit), 180.00,
                        "Credit should be transferred to new schedule")
        
        # With 180 credit and 80/quarter, next 2 quarters are covered
        # So next invoice should be ~6 months out
        expected_next_invoice = add_days(today(), 180)  # Approximately
        actual_next_invoice = getdate(quarterly_schedule[0].next_invoice_date)
        days_diff = abs((actual_next_invoice - expected_next_invoice).days)
        
        self.assertLess(days_diff, 10, 
                       "Next invoice date should account for credit balance")
    
    def test_multiple_transitions_no_overlap(self):
        """Test multiple billing transitions ensure no billing overlap"""
        # Create test persona with multiple transitions
        sam = BillingTransitionPersonas.create_mid_period_switch_sam()
        self.personas["sam"] = sam
        
        # Track for cleanup
        self.track_doc("Member", sam["member"].name)
        self.track_doc("Membership", sam["membership"].name)
        self.track_doc("Membership Dues Schedule", sam["quarterly_schedule"].name)
        self.track_doc("Contribution Amendment Request", sam["first_transition"].name)
        self.track_doc("Contribution Amendment Request", sam["second_transition"].name)
        
        # Apply second transition
        transition = sam["second_transition"]
        transition.status = "Approved"
        transition.save()
        
        self._apply_billing_transition(transition)
        
        # Validate entire billing history
        validation = BillingTransitionPersonas.validate_no_duplicate_billing(
            sam["member"].name,
            add_days(today(), -180),  # From start
            add_days(today(), 30)     # To future
        )
        
        self.assertTrue(validation["valid"],
                       f"Billing overlap found in multiple transitions: {validation.get('message')}")
        
        # Verify accumulated credits
        annual_schedule = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": sam["member"].name,
                "billing_frequency": "Annual",
                "status": "Active"
            },
            fields=["accumulated_credit"],
            limit=1
        )
        
        # Should have credits from both transitions
        total_expected_credit = 15.00 + 23.33  # From both transitions
        self.assertAlmostEqual(
            flt(annual_schedule[0].accumulated_credit),
            total_expected_credit,
            places=2,
            msg="Accumulated credits should carry forward through transitions"
        )
    
    def test_backdated_transition_validation(self):
        """Test backdated billing changes require approval and calculate correctly"""
        # Create test persona
        betty = BillingTransitionPersonas.create_backdated_change_betty()
        self.personas["betty"] = betty
        
        # Track for cleanup
        self.track_doc("Member", betty["member"].name)
        self.track_doc("Membership", betty["membership"].name)
        self.track_doc("Membership Dues Schedule", betty["annual_schedule"].name)
        self.track_doc("Contribution Amendment Request", betty["transition_request"].name)
        
        # Verify backdated change requires approval
        transition = betty["transition_request"]
        self.assertTrue(transition.requires_approval,
                       "Backdated changes should require approval")
        
        # Verify retroactive calculation
        self.assertEqual(flt(transition.prorated_credit), 180.00,
                        "Initial credit calculation incorrect")
        self.assertEqual(flt(transition.retroactive_adjustment), -40.00,
                        "Retroactive adjustment should be negative (member owes)")
        self.assertEqual(flt(transition.net_credit), 140.00,
                        "Net credit calculation incorrect")
        
        # Apply transition
        transition.status = "Approved"
        transition.save()
        self._apply_billing_transition(transition)
        
        # Verify retroactive invoices created
        retroactive_invoices = self._get_member_invoices(
            betty["member"].name,
            add_days(today(), -60),  # From effective date
            today()
        )
        
        # Should have 2 monthly invoices for the retroactive period
        membership_invoices = [inv for inv in retroactive_invoices 
                             if any("Membership" in item.item_name 
                                   for item in inv.items)]
        
        self.assertGreaterEqual(len(membership_invoices), 2,
                               "Retroactive monthly invoices should be created")
    
    def test_daily_to_annual_no_gaps(self):
        """Test extreme transition from daily to annual billing"""
        # Create test persona
        diana = BillingTransitionPersonas.create_daily_to_annual_diana()
        self.personas["diana"] = diana
        
        # Track for cleanup
        self.track_doc("Member", diana["member"].name)
        self.track_doc("Membership", diana["membership"].name)
        self.track_doc("Membership Dues Schedule", diana["daily_schedule"].name)
        self.track_doc("Contribution Amendment Request", diana["transition_request"].name)
        
        # Apply transition
        transition = diana["transition_request"]
        transition.status = "Approved"
        transition.save()
        
        self._apply_billing_transition(transition)
        
        # Verify no billing gap
        # Daily billing should stop today, annual should start tomorrow
        daily_schedule = frappe.get_doc("Membership Dues Schedule", diana["daily_schedule"].name)
        self.assertEqual(daily_schedule.status, "Inactive",
                        "Daily schedule should be inactive")
        
        annual_schedule = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": diana["member"].name,
                "billing_frequency": "Annual",
                "status": "Active"
            },
            fields=["effective_date"],
            limit=1
        )
        
        self.assertEqual(getdate(annual_schedule[0].effective_date), 
                        add_days(today(), 1),
                        "Annual billing should start day after daily ends")
        
        # Validate no gaps or overlaps
        validation = BillingTransitionPersonas.validate_no_duplicate_billing(
            diana["member"].name,
            add_days(today(), -30),
            add_days(today(), 30)
        )
        
        self.assertTrue(validation["valid"],
                       "No billing gaps or overlaps should exist")
    
    def test_billing_period_extraction(self):
        """Test utility functions for period extraction"""
        # Test various description formats
        test_cases = [
            {
                "description": "Monthly membership fee - Monthly period: 2025-01-01 to 2025-01-31",
                "expected": {"start": getdate("2025-01-01"), "end": getdate("2025-01-31")}
            },
            {
                "description": "Daily fee for 2025-01-15",
                "expected": {"start": getdate("2025-01-15"), "end": getdate("2025-01-15")}
            },
            {
                "description": "Quarterly Period: 2025-01-01 to 2025-03-31",
                "expected": {"start": getdate("2025-01-01"), "end": getdate("2025-03-31")}
            }
        ]
        
        for case in test_cases:
            result = extract_billing_period(case["description"])
            self.assertIsNotNone(result, f"Should extract period from: {case['description']}")
            self.assertEqual(result["start"], case["expected"]["start"])
            self.assertEqual(result["end"], case["expected"]["end"])
    
    def test_period_overlap_detection(self):
        """Test period overlap calculation"""
        # Test overlapping periods
        period1 = {"start": getdate("2025-01-15"), "end": getdate("2025-02-15")}
        period2 = {"start": getdate("2025-02-01"), "end": getdate("2025-02-28")}
        
        self.assertTrue(periods_overlap(period1, period2),
                       "Should detect overlap")
        
        overlap_days = calculate_overlap_days(period1, period2)
        self.assertEqual(overlap_days, 15, "Should calculate 15 days overlap")
        
        # Test non-overlapping periods
        period3 = {"start": getdate("2025-01-01"), "end": getdate("2025-01-31")}
        period4 = {"start": getdate("2025-02-01"), "end": getdate("2025-02-28")}
        
        self.assertFalse(periods_overlap(period3, period4),
                        "Should not detect overlap for adjacent periods")
    
    def _apply_billing_transition(self, transition):
        """
        Helper to apply a billing transition
        Simulates the actual transition process
        """
        member = frappe.get_doc("Member", transition.member)
        
        # Deactivate old schedule
        old_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": member.name,
                "status": "Active",
                "billing_frequency": transition.current_billing_frequency
            }
        )
        
        for schedule in old_schedules:
            doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
            doc.status = "Inactive"
            doc.end_date = today()
            doc.save()
        
        # Create new schedule
        new_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DUES-{member.name}-{transition.requested_billing_frequency.upper()}",
            "member": member.name,
            "membership": transition.membership,
            "membership_type": transition.requested_membership_type,
            "billing_frequency": transition.requested_billing_frequency,
            "amount": transition.requested_amount,
            "status": "Active",
            "effective_date": transition.effective_date,
            "accumulated_credit": flt(transition.get("total_credit") or transition.prorated_credit),
            "previous_schedule_reference": old_schedules[0].name if old_schedules else None
        })
        
        # Calculate next invoice date based on credit
        if new_schedule.accumulated_credit > 0:
            periods_covered = int(new_schedule.accumulated_credit / new_schedule.amount)
            if new_schedule.billing_frequency == "Monthly":
                new_schedule.next_invoice_date = add_days(today(), periods_covered * 30)
            elif new_schedule.billing_frequency == "Quarterly":
                new_schedule.next_invoice_date = add_days(today(), periods_covered * 90)
            elif new_schedule.billing_frequency == "Annual":
                new_schedule.next_invoice_date = add_days(today(), periods_covered * 365)
            else:
                new_schedule.next_invoice_date = add_days(today(), 1)
        else:
            new_schedule.next_invoice_date = transition.effective_date
        
        new_schedule.insert()
        
        # Handle retroactive adjustments if needed
        if hasattr(transition, 'retroactive_adjustment') and transition.retroactive_adjustment < 0:
            # Create retroactive invoices
            self._create_retroactive_invoices(
                member,
                transition.effective_date,
                today(),
                transition.requested_amount,
                transition.requested_billing_frequency
            )
        
        # Mark transition as applied
        transition.status = "Applied"
        transition.applied_date = today()
        transition.save()
    
    def _create_retroactive_invoices(self, member, start_date, end_date, amount, frequency):
        """Create retroactive invoices for backdated changes"""
        current_date = start_date
        
        while current_date < end_date:
            # Create invoice for the period
            if frequency == "Monthly":
                period_end = add_days(current_date, 30)
            elif frequency == "Quarterly":
                period_end = add_days(current_date, 90)
            else:
                period_end = add_days(current_date, 1)
            
            if period_end > end_date:
                period_end = end_date
            
            # Create a simple test invoice (simplified for testing)
            invoice = frappe.get_doc({
                "doctype": "Sales Invoice",
                "customer": member.customer,
                "posting_date": current_date,
                "due_date": add_days(current_date, 7),
                "items": [{
                    "item_code": "Membership Fee",
                    "item_name": "Membership Fee",
                    "description": f"Retroactive {frequency} fee - period: {current_date} to {period_end}",
                    "qty": 1,
                    "rate": amount
                }]
            })
            
            # In real implementation, this would be properly created
            # For testing, we just track the concept
            
            current_date = add_days(period_end, 1)
    
    def _get_member_invoices(self, member_name, start_date, end_date):
        """Get all invoices for a member in date range"""
        customer = frappe.db.get_value("Member", member_name, "customer")
        if not customer:
            return []
        
        return frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": customer,
                "posting_date": ["between", [start_date, end_date]],
                "docstatus": ["!=", 2]
            },
            fields=["name", "posting_date", "grand_total", "status"]
        )


def run_tests():
    """Run the test suite"""
    frappe.connect()
    unittest.main(module=__name__, verbosity=2)