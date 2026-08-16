"""
Tests for portal functions - proper test class version

Tests the self-service donation portal endpoints in
verenigingen.templates.pages.manage_donations against their CURRENT
behavior:

- Donations are NOT submittable; their status enum is
  One-time / Promised / Recurring (there is no "Cancelled" value).
- cancel_recurring_donation()/update_recurring_donation() read
  donation_id (and new_amount) from frappe.form_dict and resolve the
  member from the session user, so the caller must be the donation's
  owner (matched via donor_email == member.email).
- Cancellation is tracked via the recurring_cancelled_date field, not a
  status change; get_recurring_donation_state() honours it.
"""

import frappe
from frappe.utils import today, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPortalFunctions(EnhancedTestCase):
    """Test portal donation functions using the Enhanced Test Factory."""

    def setUp(self):
        super().setUp()

        # A unique email shared by the member and the donor so the portal
        # ownership check (donation.donor_email == member.email) passes.
        self.shared_email = f"test-portal-{now_datetime().strftime('%H%M%S%f')}@example.com"

        # Member with a linked User account; the portal endpoints resolve the
        # member from frappe.session.user.
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Portal User",
            email=self.shared_email,
            birth_date="1990-01-01",
        )
        self.portal_user = self._ensure_member_user(self.test_member, self.shared_email)

        # Donor sharing the member's email (donor_email feeds onto the donation).
        self.test_donor = self.create_test_donor(
            donor_name="Test Portal Donor",
            donor_email=self.shared_email,
        )

    def _ensure_member_user(self, member, email):
        """Create (or reuse) a User and link it to the member."""
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Test",
                    "last_name": "Portal User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert(ignore_permissions=True)
        member.db_set("user", email)
        return email

    def create_test_recurring_donation(self):
        """Create an active recurring donation owned by the test member."""
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": self.test_donor.name,
                "donation_date": today(),
                "amount": 25.0,
                "mode_of_payment": "Credit Card",
                "status": "Recurring",
                "donation_purpose_type": "General",
                "recurring_frequency": "Monthly",
            }
        )
        donation.insert(ignore_permissions=True)
        frappe.db.commit()
        return donation

    def test_cancel_recurring_donation_function(self):
        """cancel_recurring_donation records a cancellation date for the owner."""
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_ACTIVE,
            cancel_recurring_donation,
            get_recurring_donation_state,
        )

        donation = self.create_test_recurring_donation()
        self.assertEqual(donation.status, "Recurring")
        self.assertEqual(get_recurring_donation_state(donation.name), RECURRING_STATE_ACTIVE)

        with self.as_user(self.portal_user):
            frappe.form_dict = frappe._dict({"donation_id": donation.name})
            try:
                result = cancel_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "success")

        # Cancellation is tracked via recurring_cancelled_date, not status.
        donation.reload()
        self.assertEqual(donation.status, "Recurring")
        self.assertEqual(str(donation.recurring_cancelled_date), today())

    def test_update_donation_amount_function(self):
        """update_recurring_donation changes the amount for the owner."""
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        donation = self.create_test_recurring_donation()
        self.assertEqual(donation.amount, 25.0)

        new_amount = 35.0
        with self.as_user(self.portal_user):
            frappe.form_dict = frappe._dict(
                {"donation_id": donation.name, "new_amount": new_amount}
            )
            try:
                result = update_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("new_amount"), new_amount)

        donation.reload()
        self.assertEqual(donation.amount, new_amount)
