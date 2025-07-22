# -*- coding: utf-8 -*-
# Copyright (c) 2025, Foppe de Haan
# License: GNU Affero General Public License v3 (AGPLv3)

"""
Billing Transition Test Personas for Verenigingen
Tests billing frequency changes to ensure no duplicate charges
"""

import frappe
from frappe.utils import add_days, add_months, add_years, today, getdate
from verenigingen.tests.utils.factories import TestDataBuilder
from verenigingen.utils.validation.iban_validator import generate_test_iban
from decimal import Decimal


class BillingTransitionPersonas:
    """Factory for creating test personas that validate billing transitions"""

    @staticmethod
    def create_monthly_to_annual_mike():
        """
        Create 'Monthly to Annual Mike' - Switches from monthly to annual billing
        
        Scenario: Mike pays €20/month, switches to annual (€200/year) mid-month
        Test: Ensure no double billing for the overlap period
        """
        builder = TestDataBuilder()
        
        # Create member with monthly billing
        test_data = (
            builder.with_chapter("Billing Test Chapter", postal_codes="4000-4099")
            .with_member(
                first_name="Mike",
                last_name="MonthlyToAnnual",
                email="mike.monthlyannual@test.com",
                contact_number="+31611111111",
                birth_date=add_days(today(), -365 * 35),
                street_name="Transitionstraat",
                house_number="100",
                postal_code="4001",
                city="Tilburg",
                country="Netherlands",
                payment_method="SEPA Direct Debit",
                iban=generate_test_iban("TEST"),
                bank_account_name="Mike MonthlyToAnnual",
                status="Active",
            )
            .with_membership(
                membership_type="Monthly Standard",  
                payment_method="SEPA Direct Debit",
                start_date=add_days(today(), -45)  # Started 45 days ago
            )
            .build()
        )
        
        # Create initial monthly dues schedule
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DUES-{test_data['member'].name}-MONTHLY",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "membership_type": test_data["membership"].membership_type,
            "billing_frequency": "Monthly",
            "amount": 20.00,
            "status": "Active",
            "effective_date": add_days(today(), -45),
            "next_invoice_date": add_days(today(), 15),  # Next bill in 15 days
            "last_invoice_date": add_days(today(), -15)  # Billed 15 days ago
        })
        dues_schedule.insert()
        test_data["monthly_schedule"] = dues_schedule
        
        # Create the billing transition record
        transition = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "amendment_type": "Billing Frequency Change",
            "current_billing_frequency": "Monthly",
            "requested_billing_frequency": "Annual",
            "current_membership_type": "Monthly Standard",
            "requested_membership_type": "Annual Standard",
            "current_amount": 20.00,
            "requested_amount": 200.00,  # Annual amount
            "effective_date": today(),  # Change happens today
            "prorated_credit": 10.00,  # Credit for unused portion of current month
            "reason": "Member requested annual billing for discount",
            "status": "Pending",
            "requested_by_member": 1
        })
        transition.insert()
        test_data["transition_request"] = transition
        
        return test_data

    @staticmethod
    def create_annual_to_quarterly_anna():
        """
        Create 'Annual to Quarterly Anna' - Switches from annual to quarterly billing
        
        Scenario: Anna paid €240/year upfront, switches to €80/quarter after 3 months
        Test: Ensure proper proration and credit for unused annual period
        """
        builder = TestDataBuilder()
        
        test_data = (
            builder.with_chapter("Billing Test Chapter", postal_codes="4000-4099")
            .with_member(
                first_name="Anna",
                last_name="AnnualToQuarterly",
                email="anna.annualquarterly@test.com",
                contact_number="+31622222222",
                birth_date=add_days(today(), -365 * 28),
                street_name="Kwartaalweg",
                house_number="200",
                postal_code="4002",
                city="Tilburg",
                country="Netherlands",
                payment_method="Bank Transfer",
                status="Active",
            )
            .with_membership(
                membership_type="Annual Premium",
                payment_method="Bank Transfer",
                start_date=add_days(today(), -90)  # Started 3 months ago
            )
            .build()
        )
        
        # Create annual dues schedule with payment history
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DUES-{test_data['member'].name}-ANNUAL",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "membership_type": test_data["membership"].membership_type,
            "billing_frequency": "Annual",
            "amount": 240.00,
            "status": "Active",
            "effective_date": add_days(today(), -90),
            "next_invoice_date": add_days(today(), 275),  # Next annual bill in 9 months
            "last_invoice_date": add_days(today(), -90),  # Paid 3 months ago
            "total_paid": 240.00  # Full year paid upfront
        })
        dues_schedule.insert()
        test_data["annual_schedule"] = dues_schedule
        
        # Calculate proration: 9 months remaining = 180.00 credit
        transition = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "amendment_type": "Billing Frequency Change",
            "current_billing_frequency": "Annual",
            "requested_billing_frequency": "Quarterly",
            "current_membership_type": "Annual Premium",
            "requested_membership_type": "Quarterly Premium",
            "current_amount": 240.00,
            "requested_amount": 80.00,  # Quarterly amount
            "effective_date": today(),
            "prorated_credit": 180.00,  # 9/12 * 240 = 180
            "unused_period_start": today(),
            "unused_period_end": add_days(today(), 275),
            "reason": "Member prefers quarterly payments",
            "status": "Pending",
            "requested_by_member": 1
        })
        transition.insert()
        test_data["transition_request"] = transition
        
        return test_data

    @staticmethod
    def create_quarterly_to_monthly_quinn():
        """
        Create 'Quarterly to Monthly Quinn' - Switches from quarterly to monthly billing
        
        Scenario: Quinn pays €75/quarter, switches to €30/month mid-quarter
        Test: Ensure credit for unused quarter is properly applied
        """
        builder = TestDataBuilder()
        
        test_data = (
            builder.with_chapter("Billing Test Chapter", postal_codes="4000-4099")
            .with_member(
                first_name="Quinn",
                last_name="QuarterlyToMonthly",
                email="quinn.quarterlymonthly@test.com",
                contact_number="+31633333333",
                birth_date=add_days(today(), -365 * 42),
                street_name="Maandelijkseweg",
                house_number="300",
                postal_code="4003",
                city="Tilburg",
                country="Netherlands",
                payment_method="SEPA Direct Debit",
                iban=generate_test_iban("MOCK"),
                bank_account_name="Quinn QuarterlyToMonthly",
                status="Active",
            )
            .with_membership(
                membership_type="Quarterly Basic",
                payment_method="SEPA Direct Debit",
                start_date=add_days(today(), -180)  # Started 6 months ago
            )
            .build()
        )
        
        # Create quarterly schedule - paid 1 month ago, 2 months remaining
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DUES-{test_data['member'].name}-QUARTERLY",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "membership_type": test_data["membership"].membership_type,
            "billing_frequency": "Quarterly",
            "amount": 75.00,
            "status": "Active",
            "effective_date": add_days(today(), -180),
            "next_invoice_date": add_days(today(), 60),  # Next quarterly bill in 2 months
            "last_invoice_date": add_days(today(), -30),  # Paid 1 month ago
            "total_paid": 150.00  # 2 quarters paid so far
        })
        dues_schedule.insert()
        test_data["quarterly_schedule"] = dues_schedule
        
        # Credit calculation: 2/3 of quarter remaining = 50.00
        transition = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "amendment_type": "Billing Frequency Change",
            "current_billing_frequency": "Quarterly",
            "requested_billing_frequency": "Monthly",
            "current_membership_type": "Quarterly Basic",
            "requested_membership_type": "Monthly Basic",
            "current_amount": 75.00,
            "requested_amount": 30.00,
            "effective_date": today(),
            "prorated_credit": 50.00,  # 2/3 * 75 = 50
            "unused_period_start": today(),
            "unused_period_end": add_days(today(), 60),
            "reason": "Member wants more flexible payment schedule",
            "status": "Pending",
            "requested_by_member": 1
        })
        transition.insert()
        test_data["transition_request"] = transition
        
        return test_data

    @staticmethod
    def create_daily_to_annual_diana():
        """
        Create 'Daily to Annual Diana' - Extreme case: daily to annual billing
        
        Scenario: Diana pays €1/day, switches to €300/year
        Test: Complex proration with many small payments
        """
        builder = TestDataBuilder()
        
        test_data = (
            builder.with_chapter("Billing Test Chapter", postal_codes="4000-4099")
            .with_member(
                first_name="Diana",
                last_name="DailyToAnnual",
                email="diana.dailyannual@test.com",
                contact_number="+31644444444",
                birth_date=add_days(today(), -365 * 25),
                street_name="Dagelijksestraat",
                house_number="400",
                postal_code="4004",
                city="Tilburg",
                country="Netherlands",
                payment_method="SEPA Direct Debit",
                iban=generate_test_iban("DEMO"),
                bank_account_name="Diana DailyToAnnual",
                status="Active",
            )
            .with_membership(
                membership_type="Daily Access",
                payment_method="SEPA Direct Debit",
                start_date=add_days(today(), -30)  # Started 30 days ago
            )
            .build()
        )
        
        # Create daily billing schedule
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DUES-{test_data['member'].name}-DAILY",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "membership_type": test_data["membership"].membership_type,
            "billing_frequency": "Daily",
            "amount": 1.00,
            "status": "Active",
            "effective_date": add_days(today(), -30),
            "next_invoice_date": add_days(today(), 1),  # Tomorrow
            "last_invoice_date": today(),  # Paid today
            "total_paid": 30.00  # 30 days paid
        })
        dues_schedule.insert()
        test_data["daily_schedule"] = dues_schedule
        
        # No credit needed - daily billing paid up to today
        transition = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "amendment_type": "Billing Frequency Change",
            "current_billing_frequency": "Daily",
            "requested_billing_frequency": "Annual",
            "current_membership_type": "Daily Access",
            "requested_membership_type": "Annual Access",
            "current_amount": 1.00,
            "requested_amount": 300.00,
            "effective_date": add_days(today(), 1),  # Starts tomorrow
            "prorated_credit": 0.00,  # No credit needed
            "reason": "Member wants predictable annual billing",
            "status": "Pending",
            "requested_by_member": 1
        })
        transition.insert()
        test_data["transition_request"] = transition
        
        return test_data

    @staticmethod
    def create_mid_period_switch_sam():
        """
        Create 'Mid-Period Switch Sam' - Changes billing frequency multiple times
        
        Scenario: Sam switches from monthly to quarterly to annual within 6 months
        Test: Multiple transitions with accumulated credits
        """
        builder = TestDataBuilder()
        
        test_data = (
            builder.with_chapter("Billing Test Chapter", postal_codes="4000-4099")
            .with_member(
                first_name="Sam",
                last_name="SwitchyMcSwitchface",
                email="sam.switchy@test.com",
                contact_number="+31655555555",
                birth_date=add_days(today(), -365 * 30),
                street_name="Wisselaarslaan",
                house_number="500",
                postal_code="4005",
                city="Tilburg",
                country="Netherlands",
                payment_method="Bank Transfer",
                status="Active",
            )
            .with_membership(
                membership_type="Flexible Membership",
                payment_method="Bank Transfer",
                start_date=add_days(today(), -180)  # 6 months ago
            )
            .build()
        )
        
        # First transition: Monthly to Quarterly (3 months ago)
        first_transition = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "amendment_type": "Billing Frequency Change",
            "current_billing_frequency": "Monthly",
            "requested_billing_frequency": "Quarterly",
            "current_amount": 25.00,
            "requested_amount": 70.00,
            "effective_date": add_days(today(), -90),
            "prorated_credit": 15.00,  # Half month credit
            "status": "Applied",
            "applied_date": add_days(today(), -90),
            "requested_by_member": 1
        })
        first_transition.insert()
        test_data["first_transition"] = first_transition
        
        # Current quarterly schedule
        quarterly_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DUES-{test_data['member'].name}-QUARTERLY",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "membership_type": test_data["membership"].membership_type,
            "billing_frequency": "Quarterly",
            "amount": 70.00,
            "status": "Active",
            "effective_date": add_days(today(), -90),
            "next_invoice_date": add_days(today(), 30),  # 1 month left in quarter
            "last_invoice_date": add_days(today(), -60),  # Paid 2 months ago
            "accumulated_credit": 15.00  # From previous transition
        })
        quarterly_schedule.insert()
        test_data["quarterly_schedule"] = quarterly_schedule
        
        # Second transition: Quarterly to Annual (today)
        second_transition = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "amendment_type": "Billing Frequency Change",
            "current_billing_frequency": "Quarterly",
            "requested_billing_frequency": "Annual",
            "current_amount": 70.00,
            "requested_amount": 250.00,
            "effective_date": today(),
            "prorated_credit": 23.33,  # 1/3 of quarter remaining
            "accumulated_credit": 15.00,  # Previous credit carried forward
            "total_credit": 38.33,  # Total credit to apply
            "status": "Pending",
            "requested_by_member": 1
        })
        second_transition.insert()
        test_data["second_transition"] = second_transition
        
        return test_data

    @staticmethod
    def create_backdated_change_betty():
        """
        Create 'Backdated Change Betty' - Requests billing change with past effective date
        
        Scenario: Betty wants to change from annual to monthly, backdated 2 months
        Test: Ensure proper handling of retroactive billing adjustments
        """
        builder = TestDataBuilder()
        
        test_data = (
            builder.with_chapter("Billing Test Chapter", postal_codes="4000-4099")
            .with_member(
                first_name="Betty",
                last_name="Backdated",
                email="betty.backdated@test.com",
                contact_number="+31666666666",
                birth_date=add_days(today(), -365 * 45),
                street_name="Terugwerkendekrachtweg",
                house_number="600",
                postal_code="4006",
                city="Tilburg",
                country="Netherlands",
                payment_method="Bank Transfer",
                status="Active",
            )
            .with_membership(
                membership_type="Annual Standard",
                payment_method="Bank Transfer",
                start_date=add_days(today(), -100)  # Started ~3 months ago
            )
            .build()
        )
        
        # Annual schedule paid 100 days ago
        dues_schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DUES-{test_data['member'].name}-ANNUAL",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "membership_type": test_data["membership"].membership_type,
            "billing_frequency": "Annual",
            "amount": 240.00,
            "status": "Active",
            "effective_date": add_days(today(), -100),
            "next_invoice_date": add_days(today(), 265),
            "last_invoice_date": add_days(today(), -100),
            "total_paid": 240.00
        })
        dues_schedule.insert()
        test_data["annual_schedule"] = dues_schedule
        
        # Backdated change request
        transition = frappe.get_doc({
            "doctype": "Contribution Amendment Request",
            "member": test_data["member"].name,
            "membership": test_data["membership"].name,
            "amendment_type": "Billing Frequency Change",
            "current_billing_frequency": "Annual",
            "requested_billing_frequency": "Monthly",
            "current_amount": 240.00,
            "requested_amount": 20.00,
            "effective_date": add_days(today(), -60),  # Backdated 2 months
            "prorated_credit": 180.00,  # 9/12 months remaining from effective date
            "retroactive_adjustment": -40.00,  # 2 months @ 20/month already passed
            "net_credit": 140.00,  # 180 - 40 = 140
            "reason": "Member had financial hardship starting 2 months ago",
            "status": "Pending",
            "requested_by_member": 1,
            "requires_approval": 1  # Backdated changes need approval
        })
        transition.insert()
        test_data["transition_request"] = transition
        
        return test_data

    @staticmethod
    def create_all_billing_personas():
        """Create all billing transition test personas"""
        personas = {
            "monthly_to_annual_mike": BillingTransitionPersonas.create_monthly_to_annual_mike(),
            "annual_to_quarterly_anna": BillingTransitionPersonas.create_annual_to_quarterly_anna(),
            "quarterly_to_monthly_quinn": BillingTransitionPersonas.create_quarterly_to_monthly_quinn(),
            "daily_to_annual_diana": BillingTransitionPersonas.create_daily_to_annual_diana(),
            "mid_period_switch_sam": BillingTransitionPersonas.create_mid_period_switch_sam(),
            "backdated_betty": BillingTransitionPersonas.create_backdated_change_betty()
        }
        
        return personas

    @staticmethod
    def validate_no_duplicate_billing(member_name, start_date, end_date):
        """
        Validate that a member has not been double-billed for any period
        
        Returns:
            dict: Validation results with any overlapping charges found
        """
        # Get all invoices for the member in the period
        customer = frappe.db.get_value("Member", member_name, "customer")
        if not customer:
            return {"valid": True, "message": "No customer linked to member"}
        
        invoices = frappe.db.sql("""
            SELECT 
                si.name,
                si.posting_date,
                si.grand_total,
                sii.item_name,
                sii.description,
                sii.rate,
                sii.qty
            FROM `tabSales Invoice` si
            INNER JOIN `tabSales Invoice Item` sii ON si.name = sii.parent
            WHERE si.customer = %(customer)s
            AND si.posting_date BETWEEN %(start_date)s AND %(end_date)s
            AND si.docstatus = 1
            AND sii.item_name LIKE '%%Membership%%'
            ORDER BY si.posting_date
        """, {
            "customer": customer,
            "start_date": start_date,
            "end_date": end_date
        }, as_dict=True)
        
        # Check for overlapping billing periods
        overlaps = []
        for i, inv1 in enumerate(invoices):
            # Extract period from description if available
            period1 = extract_billing_period(inv1.description)
            if not period1:
                continue
                
            for inv2 in invoices[i+1:]:
                period2 = extract_billing_period(inv2.description)
                if not period2:
                    continue
                    
                # Check if periods overlap
                if periods_overlap(period1, period2):
                    overlaps.append({
                        "invoice1": inv1.name,
                        "invoice2": inv2.name,
                        "period1": period1,
                        "period2": period2,
                        "overlap": calculate_overlap_days(period1, period2)
                    })
        
        return {
            "valid": len(overlaps) == 0,
            "overlaps": overlaps,
            "total_invoices": len(invoices),
            "message": "No duplicate billing found" if len(overlaps) == 0 else f"Found {len(overlaps)} overlapping billing periods"
        }


def extract_billing_period(description):
    """Extract billing period from invoice description"""
    import re
    
    # Look for patterns like "period: 2025-01-01 to 2025-01-31"
    pattern = r'period:\s*(\d{4}-\d{2}-\d{2})\s*to\s*(\d{4}-\d{2}-\d{2})'
    match = re.search(pattern, description, re.IGNORECASE)
    
    if match:
        return {
            "start": getdate(match.group(1)),
            "end": getdate(match.group(2))
        }
    
    # Look for single date pattern for daily billing
    pattern = r'for\s*(\d{4}-\d{2}-\d{2})'
    match = re.search(pattern, description, re.IGNORECASE)
    
    if match:
        date = getdate(match.group(1))
        return {
            "start": date,
            "end": date
        }
    
    return None


def periods_overlap(period1, period2):
    """Check if two billing periods overlap"""
    return not (period1["end"] < period2["start"] or period2["end"] < period1["start"])


def calculate_overlap_days(period1, period2):
    """Calculate number of overlapping days between two periods"""
    overlap_start = max(period1["start"], period2["start"])
    overlap_end = min(period1["end"], period2["end"])
    
    if overlap_end >= overlap_start:
        return (overlap_end - overlap_start).days + 1
    return 0