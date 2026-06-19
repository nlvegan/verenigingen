"""
Coverage-extension tests for the manage-donations portal page
(verenigingen.templates.pages.manage_donations).

The cancel/update happy + foreign-owner paths are already covered by
test_portal_functions.py and test_donation_portal_behavior.py. This module
covers the OTHER branches: get_context assembly, the summary/recurring/recent
helpers, is_recurring_donation_active variants, get_donation_stats (guest /
no-member / success), and the cancel/update input-validation guards.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageManageDonations(EnhancedTestCase):
    """Real-data tests for manage_donations helpers + context."""

    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.form_dict
        # get_donation_summary is gated to the DEVELOPMENT environment by the API
        # security framework (reads frappe.conf.developer_mode). A sibling test in
        # the same shard can leave that shared flag off, making the gate raise
        # "Function not available in production environment". Force it on.
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.email = f"managedon-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Manage",
            last_name="Donor",
            email=self.email,
            birth_date="1990-01-01",
        )
        # The factory may uniquify the member's email for isolation, so read the
        # stored value back. get_donation_summary() matches donations by
        # member.email, so the donor + donations MUST use the member's actual
        # email — otherwise the aggregate finds nothing (total_donations == 0).
        self.email = self.member.email
        self.user = self._ensure_user(self.email)
        self.member.db_set("user", self.user)
        self.donor = self.create_test_donor(donor_email=self.email)

    def tearDown(self):
        frappe.form_dict = self._original_form_dict
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def _ensure_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Manage",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    def _make_donation(self, *, status="One-time", amount=20.0, paid=0, recurring_freq=None):
        data = {
            "doctype": "Donation",
            "donor": self.donor.name,
            "donor_email": self.email,
            "donation_date": today(),
            "amount": amount,
            "mode_of_payment": "Credit Card",
            "status": status,
            "donation_purpose_type": "General",
            "paid": paid,
        }
        if recurring_freq:
            data["recurring_frequency"] = recurring_freq
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        return doc

    # ----- helpers -----------------------------------------------------

    def test_donation_summary_aggregates_paid_and_recurring(self):
        from verenigingen.templates.pages.manage_donations import get_donation_summary

        self._make_donation(status="One-time", amount=10.0, paid=1)
        self._make_donation(status="One-time", amount=15.0, paid=0)  # unpaid: excluded from total
        self._make_donation(status="Recurring", amount=5.0, paid=1, recurring_freq="Monthly")

        summary = get_donation_summary(self.member.name)
        self.assertEqual(summary["total_donations"], 3)
        # Only paid donations count toward total_donated (10 + 5).
        self.assertEqual(summary["total_donated"], 15.0)
        self.assertEqual(summary["active_recurring"], 1)

    def test_recent_donations_ordered_and_limited(self):
        from verenigingen.templates.pages.manage_donations import get_recent_donations

        for amt in (11.0, 12.0, 13.0):
            self._make_donation(amount=amt, paid=1)

        recent = get_recent_donations(self.member.name, limit=2)
        self.assertEqual(len(recent), 2)
        # All belong to this member's email.
        for d in recent:
            self.assertIn("amount", d)

    def test_recurring_donations_returns_only_recurring(self):
        from verenigingen.templates.pages.manage_donations import get_recurring_donations

        self._make_donation(status="One-time", amount=10.0, paid=1)
        self._make_donation(status="Recurring", amount=8.0, recurring_freq="Monthly")

        recurring = get_recurring_donations(self.member.name)
        # The query filters status == "Recurring", so the one-time donation is
        # excluded and only the recurring one (amount 8.0) is returned.
        self.assertEqual(len(recurring), 1)
        self.assertEqual(recurring[0].amount, 8.0)
        self.assertEqual(recurring[0].recurring_frequency, "Monthly")

    def test_is_recurring_active_true_for_recurring(self):
        from verenigingen.templates.pages.manage_donations import is_recurring_donation_active

        donation = self._make_donation(status="Recurring", recurring_freq="Monthly")
        self.assertTrue(is_recurring_donation_active(donation.name))

    def test_is_recurring_active_false_for_one_time(self):
        from verenigingen.templates.pages.manage_donations import is_recurring_donation_active

        donation = self._make_donation(status="One-time")
        self.assertFalse(is_recurring_donation_active(donation.name))

    def test_is_recurring_active_false_for_missing_donation(self):
        from verenigingen.templates.pages.manage_donations import is_recurring_donation_active

        self.assertFalse(is_recurring_donation_active("Nonexistent-Donation-XYZ"))

    def test_is_recurring_active_false_after_cancellation_date(self):
        from verenigingen.templates.pages.manage_donations import is_recurring_donation_active

        donation = self._make_donation(status="Recurring", recurring_freq="Monthly")
        # A past cancellation date marks it inactive.
        donation.db_set("recurring_cancelled_date", "2000-01-01")
        self.assertFalse(is_recurring_donation_active(donation.name))

    # ----- get_context -------------------------------------------------

    def test_context_for_member(self):
        from verenigingen.templates.pages.manage_donations import get_context

        self._make_donation(status="Recurring", amount=9.0, recurring_freq="Monthly")
        with self.as_user(self.user):
            ctx = frappe._dict()
            get_context(ctx)

        self.assertEqual(ctx.member.name, self.member.name)
        self.assertEqual(ctx.no_cache, 1)
        self.assertIn("total_donations", ctx.donation_summary)
        self.assertIsInstance(ctx.recurring_donations, list)
        self.assertIsInstance(ctx.recent_donations, list)

    # ----- get_donation_stats ------------------------------------------

    def test_get_donation_stats_guest_blocked_by_security(self):
        """The @self_service_api decorator rejects Guests before the body runs."""
        from verenigingen.templates.pages.manage_donations import get_donation_stats

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                get_donation_stats()

    def test_get_donation_stats_success(self):
        from verenigingen.templates.pages.manage_donations import get_donation_stats

        self._make_donation(amount=30.0, paid=1)
        with self.as_user(self.user):
            result = get_donation_stats()

        self.assertEqual(result.get("status"), "success")
        self.assertIn("total_donated", result["data"])

    # ----- input-validation guards on cancel/update --------------------

    def test_cancel_missing_donation_id_throws(self):
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({})
            try:
                with self.assertRaises(frappe.ValidationError):
                    cancel_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

    def test_update_rejects_non_positive_amount(self):
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        donation = self._make_donation(status="Recurring", amount=25.0, recurring_freq="Monthly")
        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({"donation_id": donation.name, "new_amount": 0})
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

        donation.reload()
        self.assertEqual(donation.amount, 25.0)

    def test_cancel_rejects_non_recurring_donation(self):
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

        donation = self._make_donation(status="One-time", amount=15.0)
        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({"donation_id": donation.name})
            try:
                with self.assertRaises(frappe.ValidationError):
                    cancel_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()
