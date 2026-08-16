"""
Tests for donation portal behavior - proper test class version

This tests the specific functions in manage_donations.py that interact with the donation portal:
- cancel_recurring_donation
- update_recurring_donation_amount

Converted from script-style test to proper unittest with Enhanced Test Factory.
"""

import frappe
# unittest.TestCase import removed - using EnhancedTestCase
from frappe.utils import today, now_datetime, getdate
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationPortalBehavior(EnhancedTestCase):
    """Test donation portal behavior using Enhanced Test Factory"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory.

        The portal endpoints (manage_donations.update_recurring_donation /
        cancel_recurring_donation) authorise by matching the logged-in Member's
        email against the Donation's donor_email, and read their parameters from
        frappe.form_dict. So we need: a Member with a real User, a Donor whose
        email equals that Member's email, and a Recurring-status Donation linked
        to that Donor. The endpoints are then invoked as the Member's user with
        the parameters placed in form_dict (mirroring a real portal request).
        """
        super().setUp()

        # cancel_recurring_donation is gated to the DEVELOPMENT environment by the
        # API security framework (reads frappe.conf.developer_mode). A sibling test
        # in the same shard can leave that shared flag toggled off, making the gate
        # raise "Function not available in production environment". Force it on
        # (save/restore the raw key — frappe.conf is a frappe._dict).
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Portal User",
            email=f"test-portal-{now_datetime().strftime('%H%M%S')}@example.com",
            birth_date="1990-01-01"
        )

        # Ensure the member has a usable login user matching its email so the
        # ownership lookup (get_current_user_member_name -> by email/user) works.
        self.member_email = self.test_member.email
        self.member_user = self._ensure_member_user(self.member_email)
        if self.test_member.user != self.member_user:
            self.test_member.db_set("user", self.member_user, update_modified=False)

        # Donation.donor links to Donor (not Member). Give the donor the same
        # email as the member so the portal ownership check passes.
        self.test_donor = self.create_test_donor(donor_email=self.member_email)

        # Recurring donation owned by this donor. "Recurring" is the only valid
        # recurring status in the Donation schema (One-time / Promised / Recurring).
        self.test_donation = self._create_recurring_donation(amount=25.0)

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    # The portal endpoints are @self_service_api(FINANCIAL, implicit_allowed=True):
    # any authenticated user passes auth (LOW), and access to a specific donation
    # is gated by the endpoint's own donor_email == member.email ownership check.
    # So the owning user is a PLAIN member (no elevated role) — exactly what a real
    # portal user is. Running as a plain member is what proves the lockout is fixed.
    _MEMBER_ROLE = "Verenigingen Member"

    def _ensure_member_user(self, email):
        """Create (idempotently) an enabled plain-member User (no elevated role)."""
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": email,
                "first_name": "Portal",
                "send_welcome_email": 0,
                "enabled": 1,
                "roles": [{"role": self._MEMBER_ROLE}],
            })
            user.insert(ignore_permissions=True)
        else:
            user = frappe.get_doc("User", email)
            if self._MEMBER_ROLE not in [r.role for r in user.roles]:
                user.add_roles(self._MEMBER_ROLE)
        return email

    def _create_recurring_donation(self, amount):
        """Insert a Recurring-status Donation linked to the test donor."""
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": self.test_donor.name,
            # amount and mode_of_payment are mandatory on Donation
            "amount": amount,
            "mode_of_payment": "Credit Card",
            "company": frappe.get_list("Company", limit=1)[0].name,
            "status": "Recurring",
            "payment_method": "Credit Card",
            "donation_date": today(),
        })
        donation.insert(ignore_permissions=True)
        return donation

    def test_update_donation_amount_behavior(self):
        """update_recurring_donation updates the donation amount via the portal."""
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        self.assertEqual(self.test_donation.amount, 25.0)

        new_amount = 35.0
        current_user = frappe.session.user
        try:
            frappe.set_user(self.member_user)
            frappe.form_dict = frappe._dict(
                donation_id=self.test_donation.name, new_amount=new_amount
            )
            result = update_recurring_donation()
        finally:
            frappe.form_dict = frappe._dict()
            frappe.set_user(current_user)

        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "success")

        self.test_donation.reload()
        self.assertEqual(self.test_donation.amount, new_amount)

    def test_update_rejects_foreign_donation(self):
        """The portal must refuse to update a donation owned by another donor."""
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        other_donor = self.create_test_donor(donor_email="someone-else@example.com")
        other_donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": other_donor.name,
            "amount": 50.0,
            "mode_of_payment": "Credit Card",
            "company": frappe.get_list("Company", limit=1)[0].name,
            "status": "Recurring",
            "donation_date": today(),
        })
        other_donation.insert(ignore_permissions=True)

        current_user = frappe.session.user
        try:
            frappe.set_user(self.member_user)
            frappe.form_dict = frappe._dict(
                donation_id=other_donation.name, new_amount=99.0
            )
            # Endpoint wraps failures and re-raises a generic ValidationError.
            with self.assertRaises(frappe.ValidationError):
                update_recurring_donation()
        finally:
            frappe.form_dict = frappe._dict()
            frappe.set_user(current_user)

        # Amount must be unchanged.
        other_donation.reload()
        self.assertEqual(other_donation.amount, 50.0)

    def test_is_recurring_donation_active(self):
        """A Recurring-status, non-Mollie donation is reported active."""
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_ACTIVE,
            get_recurring_donation_state,
        )

        self.assertEqual(
            get_recurring_donation_state(self.test_donation.name), RECURRING_STATE_ACTIVE
        )

    def test_cancel_own_donation_happy_path(self):
        """A member cancels their own recurring donation via the portal.

        Cancellation is recorded via recurring_cancelled_date (the Donation status
        enum has no "Cancelled" value); status stays "Recurring" and
        get_recurring_donation_state() then reports the donation inactive.
        """
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_ACTIVE,
            RECURRING_STATE_INACTIVE,
            cancel_recurring_donation,
            get_recurring_donation_state,
        )

        self.assertEqual(
            get_recurring_donation_state(self.test_donation.name), RECURRING_STATE_ACTIVE
        )

        current_user = frappe.session.user
        try:
            frappe.set_user(self.member_user)
            frappe.form_dict = frappe._dict(donation_id=self.test_donation.name)
            result = cancel_recurring_donation()
        finally:
            frappe.form_dict = frappe._dict()
            frappe.set_user(current_user)

        self.assertEqual(result.get("status"), "success")
        self.test_donation.reload()
        self.assertEqual(self.test_donation.recurring_cancelled_date, getdate(today()))
        # Status is unchanged (no invalid value) but the donation is now inactive.
        self.assertEqual(self.test_donation.status, "Recurring")
        self.assertEqual(
            get_recurring_donation_state(self.test_donation.name), RECURRING_STATE_INACTIVE
        )

    def test_cancel_rejects_foreign_donation(self):
        """The portal must refuse to cancel a donation owned by another donor."""
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

        other_donor = self.create_test_donor(donor_email="not-the-member@example.com")
        foreign_donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": other_donor.name,
            "amount": 40.0,
            "mode_of_payment": "Credit Card",
            "company": frappe.get_list("Company", limit=1)[0].name,
            "status": "Recurring",
            "donation_date": today(),
        })
        foreign_donation.insert(ignore_permissions=True)

        current_user = frappe.session.user
        try:
            frappe.set_user(self.member_user)
            frappe.form_dict = frappe._dict(donation_id=foreign_donation.name)
            with self.assertRaises(frappe.ValidationError):
                cancel_recurring_donation()
        finally:
            frappe.form_dict = frappe._dict()
            frappe.set_user(current_user)

        foreign_donation.reload()
        self.assertEqual(foreign_donation.status, "Recurring")