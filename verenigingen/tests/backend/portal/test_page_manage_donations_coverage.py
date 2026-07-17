"""
Coverage-extension tests for the manage-donations portal page
(verenigingen.templates.pages.manage_donations).

The neighbouring module ``test_page_manage_donations.py`` already covers the
summary/recurring/recent helpers, get_donation_stats and the
cancel/update input-validation guards. This module fills the REMAINING
uncovered branches:

- get_donation_summary / get_recurring_donations / get_recent_donations
  exception path (missing member -> logged error, safe default returned)
- is_recurring_donation_active future-cancellation-date branch
- get_donation_stats guest / no-member error returns (decorator allows the
  body to run as a non-guest member)
- cancel/update foreign-ownership rejection + already-cancelled guard

Mollie-backed paths (get_mollie_subscription_info and the
update/cancel branches that hit the live Mollie API) are OUT OF SCOPE:
they require a configured Mollie gateway + real subscription, and the
HARD RULES forbid mocking the Mollie client.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageManageDonationsCoverage(EnhancedTestCase):
    """Real-data tests for the uncovered manage_donations branches."""

    def setUp(self):
        super().setUp()
        # get_donation_stats is gated to the DEVELOPMENT environment by the API
        # security framework (reads frappe.conf.developer_mode). A sibling test in
        # the same shard can leave that shared flag off, so force it on.
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.email = f"mdcov-{frappe.generate_hash()[:8]}@example.com"
        self.member = self.create_test_member(
            first_name="Cover",
            last_name="Donor",
            email=self.email,
            birth_date="1990-01-01",
        )
        # The factory may uniquify the email for isolation; read it back so the
        # donor + donations match the member's actual email (the helpers match
        # donations by member.email).
        self.email = self.member.email
        self.user = self._ensure_user(self.email)
        self.member.db_set("user", self.user)
        self.donor = self.create_test_donor(donor_email=self.email)

    def tearDown(self):
        # form_dict is a LocalProxy; never reassign it. Just clear our keys.
        frappe.local.form_dict.pop("donation_id", None)
        frappe.local.form_dict.pop("new_amount", None)
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
                    "first_name": "Cover",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return email

    def _make_user_without_member(self):
        """Create a Verenigingen Member User that has no linked Member record."""
        nomember = f"mdcov-nomember-{frappe.generate_hash()[:8]}@test.invalid"
        if not frappe.db.exists("User", nomember):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": nomember,
                    "first_name": "NoMember",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        return nomember

    def _ensure_foreign_donor(self):
        """A separate donor whose email differs from self.member's. The Donation
        controller overwrites donor_email from the linked Donor on validate, so a
        "foreign" donation must point at a DIFFERENT donor, not just a different
        donor_email string."""
        if getattr(self, "_foreign_donor", None) is None:
            self._foreign_email = f"foreign-{frappe.generate_hash()[:8]}@test.invalid"
            self._foreign_donor = self.create_test_donor(donor_email=self._foreign_email)
        return self._foreign_donor

    def _make_donation(
        self, *, status="One-time", amount=20.0, paid=0, recurring_freq=None, email=None, donor=None
    ):
        data = {
            "doctype": "Donation",
            "donor": donor.name if donor is not None else self.donor.name,
            "donor_email": email if email is not None else self.email,
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

    # ----- helper exception/default paths ------------------------------

    def test_donation_summary_missing_member_returns_zero_default(self):
        from verenigingen.templates.pages.manage_donations import get_donation_summary

        # frappe.get_doc on a missing member raises -> caught -> safe zero default,
        # and a single Error Log row is written (legitimate, so expect it).
        self.expectErrorLog("Manage Donations")
        summary = get_donation_summary("Nonexistent-Member-XYZ")
        self.assertEqual(summary["total_donated"], 0)
        self.assertEqual(summary["total_donations"], 0)
        self.assertEqual(summary["active_recurring"], 0)

    def test_recurring_donations_missing_member_returns_empty(self):
        from verenigingen.templates.pages.manage_donations import get_recurring_donations

        self.expectErrorLog("Manage Donations")
        self.assertEqual(get_recurring_donations("Nonexistent-Member-XYZ"), [])

    def test_recent_donations_missing_member_returns_empty(self):
        from verenigingen.templates.pages.manage_donations import get_recent_donations

        self.expectErrorLog("Manage Donations")
        self.assertEqual(get_recent_donations("Nonexistent-Member-XYZ", limit=5), [])

    def test_summary_excludes_other_members_donations(self):
        from verenigingen.templates.pages.manage_donations import get_donation_summary

        self._make_donation(amount=40.0, paid=1)
        # A donation under a different donor (different email) must not aggregate.
        foreign = self._ensure_foreign_donor()
        self._make_donation(amount=99.0, paid=1, donor=foreign, email=self._foreign_email)

        summary = get_donation_summary(self.member.name)
        self.assertEqual(summary["total_donations"], 1)
        self.assertEqual(summary["total_donated"], 40.0)

    # ----- is_recurring_donation_active future-date branch -------------

    def test_is_recurring_active_true_with_future_cancellation_date(self):
        from verenigingen.templates.pages.manage_donations import is_recurring_donation_active

        donation = self._make_donation(status="Recurring", recurring_freq="Monthly")
        # A FUTURE cancellation date means the subscription is still active until then.
        donation.db_set("recurring_cancelled_date", add_days(today(), 30))
        self.assertTrue(is_recurring_donation_active(donation.name))

    # ----- get_donation_stats body branches ----------------------------

    def test_get_donation_stats_guest_returns_not_logged_in(self):
        """The @self_service_api decorator rejects Guests before the body."""
        from verenigingen.templates.pages.manage_donations import get_donation_stats

        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                get_donation_stats()

    def test_get_donation_stats_member_without_record(self):
        """A logged-in user with NO Member record is rejected by the
        @self_service_api decorator (PermissionError) before the body's
        no-member branch can run -- the decorator resolves the caller's member
        for ownership enforcement and refuses when there is none."""
        from verenigingen.templates.pages.manage_donations import get_donation_stats

        nomember = self._make_user_without_member()

        with self.as_user(nomember):
            with self.assertRaises(frappe.PermissionError):
                get_donation_stats()

    # ----- cancel/update ownership + already-cancelled guards ----------

    def test_cancel_rejects_foreign_owner(self):
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

        # A recurring donation owned by a DIFFERENT donor (different email).
        foreign = self._ensure_foreign_donor()
        donation = self._make_donation(
            status="Recurring",
            amount=12.0,
            recurring_freq="Monthly",
            donor=foreign,
            email=self._foreign_email,
        )
        # The endpoint catches the ownership throw and re-raises after logging.
        self.expectErrorLog("Manage Donations")
        with self.as_user(self.user):
            frappe.local.form_dict["donation_id"] = donation.name
            try:
                with self.assertRaises(frappe.ValidationError):
                    cancel_recurring_donation()
            finally:
                frappe.local.form_dict.pop("donation_id", None)

    def test_update_rejects_foreign_owner(self):
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        foreign = self._ensure_foreign_donor()
        donation = self._make_donation(
            status="Recurring",
            amount=18.0,
            recurring_freq="Monthly",
            donor=foreign,
            email=self._foreign_email,
        )
        self.expectErrorLog("Manage Donations")
        with self.as_user(self.user):
            frappe.local.form_dict["donation_id"] = donation.name
            frappe.local.form_dict["new_amount"] = 25.0
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_recurring_donation()
            finally:
                frappe.local.form_dict.pop("donation_id", None)
                frappe.local.form_dict.pop("new_amount", None)

    def test_cancel_rejects_already_cancelled_recurring(self):
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

        donation = self._make_donation(status="Recurring", amount=14.0, recurring_freq="Monthly")
        # Mark it cancelled in the past -> is_recurring_donation_active() is False.
        donation.db_set("recurring_cancelled_date", "2000-01-01")
        self.expectErrorLog("Manage Donations")
        with self.as_user(self.user):
            frappe.local.form_dict["donation_id"] = donation.name
            try:
                with self.assertRaises(frappe.ValidationError):
                    cancel_recurring_donation()
            finally:
                frappe.local.form_dict.pop("donation_id", None)

    def test_update_missing_donation_id_throws(self):
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        self.expectErrorLog("Manage Donations")
        with self.as_user(self.user):
            frappe.local.form_dict["new_amount"] = 10.0
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_recurring_donation()
            finally:
                frappe.local.form_dict.pop("new_amount", None)
