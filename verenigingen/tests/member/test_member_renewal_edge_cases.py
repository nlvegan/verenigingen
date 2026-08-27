# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Member Renewal Edge Cases Tests
This file restores critical member renewal edge case testing that was removed during Phase 4
Focus on complex renewal scenarios, edge cases, and error handling
"""

import unittest

import frappe
from frappe.utils import today, add_days, add_months, add_years, flt, date_diff, getdate
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.skip_reasons import VOLUNTEER_EXPENSE_ARCHIVED


class RenewalTestMixin:
    """Shared helpers for the renewal edge-case test cases."""

    def create_submitted_membership(self, **kwargs):
        """Create a membership and submit it so its status becomes Active.

        CoreTestDataFactory.create_test_membership only inserts a Draft; tests
        that assert status == "Active" need it submitted.
        """
        membership = self.create_test_membership(**kwargs)
        if membership.docstatus == 0:
            membership.submit()
        return membership


class TestMemberRenewalEdgeCases(RenewalTestMixin, VereningingenTestCase):
    """Edge case tests for member renewal scenarios"""

    def setUp(self):
        super().setUp()

        # Create test environment
        self.test_member = self.create_test_member()
        self.test_membership_type = self.create_test_membership_type(
            membership_type_name="Renewal Test Type", amount=50.00, billing_frequency="Annual"
        )

        # Create initial membership
        self.current_membership = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=add_days(today(), -300),  # Started 300 days ago
        )

    def test_early_renewal_edge_case(self):
        """Test renewal attempted very early in membership period"""
        # Attempt renewal when membership has months remaining
        early_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=self.current_membership.renewal_date,  # Start when current expires
        )

        # Verify early renewal is valid
        self.assertEqual(early_renewal.member, self.test_member.name)
        self.assertEqual(early_renewal.start_date, self.current_membership.renewal_date)

        # Verify no gap between memberships
        gap_days = date_diff(early_renewal.start_date, self.current_membership.renewal_date)
        self.assertEqual(gap_days, 0)

    def test_late_renewal_with_gap(self):
        """Test renewal after membership has expired (with gap)"""
        # Create expired membership
        expired_membership = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=add_days(today(), -400),
            status="Expired",
        )

        # Create renewal after gap
        late_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=today(),  # Start today
        )

        # Verify gap exists. The expired membership started 400 days ago with an
        # Annual term, so its computed renewal_date is 365 days later (= 35 days
        # ago); a renewal starting today leaves a 35-day gap.
        gap_days = date_diff(late_renewal.start_date, expired_membership.renewal_date)
        self.assertEqual(gap_days, 35)
        self.assertGreater(gap_days, 0)

    def test_membership_type_change_during_renewal(self):
        """Test changing membership type during renewal"""
        # Create different membership type
        premium_type = self.create_test_membership_type(
            membership_type_name="Premium Renewal Type", amount=100.00, billing_frequency="Annual"
        )

        # Renew with different membership type
        type_change_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=premium_type.name,  # Different type
            start_date=self.current_membership.renewal_date,
        )

        # Verify type change is valid
        self.assertEqual(type_change_renewal.membership_type, premium_type.name)
        self.assertNotEqual(type_change_renewal.membership_type, self.current_membership.membership_type)

    def test_billing_frequency_change_during_renewal(self):
        """Test changing billing frequency during renewal"""
        # Create monthly membership type
        monthly_type = self.create_test_membership_type(
            membership_type_name="Monthly Renewal Type", amount=10.00, billing_frequency="Monthly"
        )

        # Renew with different billing frequency
        frequency_change_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=monthly_type.name,
            start_date=self.current_membership.renewal_date,
        )

        self.assertEqual(frequency_change_renewal.membership_type, monthly_type.name)

    def test_multiple_concurrent_renewals(self):
        """Test handling of multiple renewal attempts"""
        # First renewal
        renewal_1 = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=self.current_membership.renewal_date,
        )

        # Second renewal (should chain from first)
        renewal_2 = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=renewal_1.renewal_date,
        )

        # Verify chaining
        self.assertEqual(renewal_2.start_date, renewal_1.renewal_date)

        # No gap between renewals
        gap_days = date_diff(renewal_2.start_date, renewal_1.renewal_date)
        self.assertEqual(gap_days, 0)

    def test_renewal_with_outstanding_payments(self):
        """Test renewal when member has outstanding payments"""
        # Create unpaid invoice for current membership
        outstanding_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer,
            is_membership_invoice=1,
            membership=self.current_membership.name,
        )

        # Attempt renewal despite outstanding payment
        renewal_with_debt = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=self.current_membership.renewal_date,
        )

        # Renewal should be created but may have special status
        self.assertEqual(renewal_with_debt.member, self.test_member.name)

        # Outstanding invoice should still exist
        self.assertTrue(frappe.db.exists("Sales Invoice", outstanding_invoice.name))

    def test_renewal_status_edge_cases(self):
        """Test renewal with various member statuses"""
        # Test renewal for suspended member
        self.test_member.status = "Suspended"
        self.test_member.save()

        suspended_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=self.current_membership.renewal_date,
        )

        # Renewal should be created even for suspended member
        self.assertEqual(suspended_renewal.member, self.test_member.name)

        # Restore member status for other tests
        self.test_member.status = "Active"
        self.test_member.save()

    def test_renewal_date_boundary_conditions(self):
        """Test renewal with boundary date conditions"""
        # Test renewal exactly on expiration date
        exact_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=self.current_membership.renewal_date,
        )

        self.assertEqual(exact_renewal.start_date, self.current_membership.renewal_date)

        # Test renewal one day before expiration
        early_by_one_day = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=add_days(self.current_membership.renewal_date, -1),
        )

        # Should overlap by one day
        overlap_days = date_diff(self.current_membership.renewal_date, early_by_one_day.start_date)
        self.assertEqual(overlap_days, 1)

    def test_renewal_amount_calculation_edge_cases(self):
        """Test renewal amount calculations in edge scenarios"""
        # Create membership with pro-rated amount
        prorated_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=add_days(self.current_membership.renewal_date, 15),  # Mid-month start
        )

        # Verify renewal created successfully
        self.assertEqual(prorated_renewal.member, self.test_member.name)

        # Test zero-amount renewal (scholarship/free membership)
        free_type = self.create_test_membership_type(
            membership_type_name="Free Renewal Type", amount=0.00, billing_frequency="Annual"
        )

        free_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=free_type.name,
            start_date=self.current_membership.renewal_date,
        )

        self.assertEqual(free_renewal.membership_type, free_type.name)

    def test_renewal_with_sepa_mandate_changes(self):
        """Test renewal when SEPA mandate details change"""
        # Create original SEPA mandate
        original_mandate = self.create_test_sepa_mandate(member=self.test_member.name, bank_code="TEST")

        # Create renewal
        renewal_with_sepa = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership_type.name,
            start_date=self.current_membership.renewal_date,
        )

        # Mark original as inactive FIRST. A bank change cancels the old mandate and
        # then activates the replacement -- since #584 a member holds at most one
        # Active mandate per purpose, so the reverse order (which this test used to
        # do) is rejected. That order is also what the sanctioned flow,
        # `api/member/sepa_api.setup_sepa_direct_debit`, has always done.
        original_mandate.status = "Cancelled"
        original_mandate.is_active = 0
        original_mandate.save()

        # Create updated SEPA mandate
        updated_mandate = self.create_test_sepa_mandate(
            member=self.test_member.name,
            bank_code="MOCK",  # Different bank
            scenario="normal",
        )

        # Verify renewal and mandate relationship
        self.assertEqual(renewal_with_sepa.member, self.test_member.name)
        self.assertEqual(updated_mandate.status, "Active")

    def test_bulk_member_renewals(self):
        """Test bulk renewal processing edge cases"""
        # Create multiple members for bulk renewal
        bulk_members = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Bulk{i}", last_name="RenewalMember", email=f"bulk{i}@example.com"
            )

            # Create expiring membership
            membership = self.create_test_membership(
                member=member.name,
                membership_type=self.test_membership_type.name,
                start_date=add_days(today(), -300),
            )

            bulk_members.append({"member": member, "membership": membership})

        # Process bulk renewals
        renewals = []
        for member_data in bulk_members:
            renewal = self.create_submitted_membership(
                member=member_data["member"].name,
                membership_type=self.test_membership_type.name,
                start_date=member_data["membership"].renewal_date,
            )
            renewals.append(renewal)

        # Verify all renewals created
        self.assertEqual(len(renewals), 5)

        # Verify each renewal is valid
        for renewal in renewals:
            self.assertEqual(renewal.status, "Active")

    def test_renewal_notification_edge_cases(self):
        """Test renewal notification scenarios"""
        # Create member with renewal notification preferences
        notification_member = self.create_test_member(
            first_name="Notification", last_name="TestMember", email="notification.test@example.com"
        )

        # Create membership expiring soon
        expiring_membership = self.create_test_membership(
            member=notification_member.name,
            membership_type=self.test_membership_type.name,
            start_date=add_days(today(), -330),
        )

        # Test various notification scenarios
        notification_scenarios = [
            {"days_before": 60, "description": "Early notification"},
            {"days_before": 30, "description": "Standard notification"},
            {"days_before": 7, "description": "Final notice"},
            {"days_before": -1, "description": "Overdue notice"},
        ]

        for scenario in notification_scenarios:
            notification_date = add_days(expiring_membership.renewal_date, -scenario["days_before"])

            # In a real system, this would trigger notification logic
            # For testing, we verify the date calculations
            if scenario["days_before"] > 0:
                self.assertLess(notification_date, expiring_membership.renewal_date)
            else:
                self.assertGreater(notification_date, expiring_membership.renewal_date)


class TestMemberRenewalDataIntegrity(RenewalTestMixin, VereningingenTestCase):
    """Data integrity tests for member renewals"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)

    def test_renewal_membership_chain_integrity(self):
        """Test integrity of membership renewal chains"""
        # Create chain of renewals
        previous_membership = self.test_membership
        renewals = []

        for i in range(3):
            renewal = self.create_test_membership(
                member=self.test_member.name,
                membership_type=previous_membership.membership_type,
                start_date=previous_membership.renewal_date,
            )
            renewals.append(renewal)
            previous_membership = renewal

        # Verify chain integrity
        current = self.test_membership
        for renewal in renewals:
            self.assertEqual(renewal.start_date, current.renewal_date)
            current = renewal

    def test_renewal_payment_history_integrity(self):
        """Test payment history integrity across renewals"""
        # Create renewal
        renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership.membership_type,
            start_date=self.test_membership.renewal_date,
        )

        # Create payments for both memberships
        original_payment = self.create_test_payment_entry(
            party=self.test_member.customer, party_type="Customer", paid_amount=50.00
        )

        renewal_payment = self.create_test_payment_entry(
            party=self.test_member.customer, party_type="Customer", paid_amount=50.00
        )

        # Verify payment integrity
        self.assertEqual(original_payment.party, self.test_member.customer)
        self.assertEqual(renewal_payment.party, self.test_member.customer)

    @unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)
    def test_renewal_volunteer_record_integrity(self):
        """Test volunteer record integrity across member renewals"""
        # Create volunteer record
        volunteer = self.create_test_volunteer(member=self.test_member.name)

        # Create renewal
        renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership.membership_type,
            start_date=self.test_membership.renewal_date,
        )

        # Verify volunteer record remains linked to member
        volunteer.reload()
        self.assertEqual(volunteer.member, self.test_member.name)

        # Verify volunteer can continue activities through renewal
        expense = self.create_test_volunteer_expense(
            volunteer=volunteer.name, amount=75.00, description="Expense during renewal period"
        )

        self.assertEqual(expense.volunteer, volunteer.name)


class TestMemberRenewalBusinessRules(RenewalTestMixin, VereningingenTestCase):
    """Business rule validation for member renewals"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()
        self.test_membership = self.create_test_membership(member=self.test_member.name)

    def test_renewal_eligibility_rules(self):
        """Test business rules for renewal eligibility"""
        # Test renewal for active member (should work)
        self.test_member.status = "Active"
        self.test_member.save()

        active_renewal = self.create_submitted_membership(
            member=self.test_member.name,
            membership_type=self.test_membership.membership_type,
            start_date=self.test_membership.renewal_date,
        )

        self.assertEqual(active_renewal.status, "Active")

        # The product enforces a single active membership per member, so cancel the
        # active renewal before creating the next-term one (mirrors a real renewal
        # where the prior term has lapsed). Reload first: submitting active_renewal
        # touched the member row (TimestampMismatchError otherwise).
        active_renewal.cancel()

        self.test_member.reload()
        self.test_member.status = "Suspended"
        self.test_member.save()

        suspended_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership.membership_type,
            start_date=add_months(self.test_membership.renewal_date, 12),
        )

        # Renewal should be created even for suspended member
        self.assertEqual(suspended_renewal.member, self.test_member.name)

    def test_renewal_payment_obligation_rules(self):
        """Test payment obligation rules for renewals"""
        # Create renewal with payment obligation
        paid_renewal = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership.membership_type,
            start_date=self.test_membership.renewal_date,
        )

        # Create invoice for renewal
        renewal_invoice = self.create_test_sales_invoice(
            customer=self.test_member.customer, is_membership_invoice=1, membership=paid_renewal.name
        )

        # Verify payment obligation linkage
        self.assertEqual(renewal_invoice.customer, self.test_member.customer)
        self.assertTrue(renewal_invoice.is_membership_invoice)

    def test_renewal_grace_period_rules(self):
        """Test grace period rules for renewals"""
        # Create expired membership
        expired_membership = self.create_test_membership(
            member=self.test_member.name,
            membership_type=self.test_membership.membership_type,
            start_date=add_days(today(), -400),
            status="Expired",
        )

        # Test renewal within grace period
        grace_renewal = self.create_submitted_membership(
            member=self.test_member.name,
            membership_type=expired_membership.membership_type,
            start_date=today(),
        )

        # Verify grace period renewal
        self.assertEqual(grace_renewal.member, self.test_member.name)
        self.assertEqual(grace_renewal.status, "Active")
