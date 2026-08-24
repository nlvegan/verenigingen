"""
Coverage-extension tests for the manage-donations portal page
(verenigingen.templates.pages.manage_donations).

The cancel/update happy + foreign-owner paths are already covered by
test_portal_functions.py and test_donation_portal_behavior.py. This module
covers the OTHER branches: get_context assembly, the summary/recurring/recent
helpers, get_recurring_donation_state variants, get_donation_stats (guest /
no-member / success), and the cancel/update input-validation guards.

It also carries the regression tests for #348 (the recurring filter used to mutate
the list it iterated) and #349 (an undeterminable Mollie status used to collapse to
"inactive" and silently drop the donation from the donor's portal).
"""

import frappe
from frappe.utils import add_days, today

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

    def _make_donation(
        self,
        *,
        status="One-time",
        amount=20.0,
        paid=0,
        recurring_freq=None,
        donation_date=None,
        **extra,
    ):
        data = {
            "doctype": "Donation",
            "donor": self.donor.name,
            "donor_email": self.email,
            "donation_date": donation_date or today(),
            "amount": amount,
            "mode_of_payment": "Credit Card",
            "status": status,
            "donation_purpose_type": "General",
            "paid": paid,
        }
        if recurring_freq:
            data["recurring_frequency"] = recurring_freq
        data.update(extra)
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        return doc

    def _setup_origin_and_charge(self):
        """A recurring donation and one of the charges booked under it.

        A charge Donation (recurring_origin_donation set) is what the Mollie
        webhook creates for each period; it carries the origin's donor_email and
        status "Recurring" and the same subscription.
        """
        origin = self._make_donation(status="Recurring", amount=25.0, recurring_freq="Monthly")
        charge = self._make_donation(
            status="Recurring",
            amount=25.0,
            paid=1,
            recurring_freq="Monthly",
            recurring_origin_donation=origin.name,
        )
        return origin, charge

    def _make_recurring(self, *, amount, days_ago=0, cancelled=False, mollie_subscription_id=None):
        """Insert a Recurring donation.

        ``days_ago`` drives donation_date, which get_recurring_donations orders by
        (desc) -- the POSITION of a donation in that list is what makes the
        mutate-while-iterating bug of #348 observable, so it must be pinned.
        """
        doc = self._make_donation(
            status="Recurring",
            amount=amount,
            recurring_freq="Monthly",
            donation_date=add_days(today(), -days_ago),
        )
        if mollie_subscription_id:
            doc.db_set("mollie_subscription_id", mollie_subscription_id)
        if cancelled:
            # A cancellation date in the past is the deterministic, Mollie-free way
            # to make a recurring donation confirmed-inactive.
            doc.db_set("recurring_cancelled_date", "2000-01-01")
        return doc

    def _unresolvable_subscription_id(self):
        """A Mollie subscription id no Member carries.

        get_mollie_subscription_info() then cannot resolve a customer, fails, finds
        no local fallback row and reports subscription_status "unknown" -- exactly
        the value a real Mollie outage produces, and without any network call, so
        the test behaves identically on a bench with Mollie credentials and on CI
        without them.
        """
        return f"sub_{frappe.generate_hash()[:12]}"

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

    # ----- #348: the filter must not mutate the list it iterates ---------

    def test_recurring_list_drops_every_confirmed_inactive_donation(self):
        """Two cancelled recurring donations in a row must BOTH be dropped.

        Regression for #348: the filter removed from the list it was iterating, so
        the element right after a removed one was never examined -- a cancelled
        donation directly following another cancelled one stayed in the donor's
        "Active Recurring Donations" list.
        """
        from verenigingen.templates.pages.manage_donations import get_recurring_donations

        self._make_recurring(amount=10.0, days_ago=0, cancelled=True)
        self._make_recurring(amount=20.0, days_ago=1, cancelled=True)
        active = self._make_recurring(amount=30.0, days_ago=2)

        result = get_recurring_donations(self.member.name)

        self.assertEqual([d.name for d in result], [active.name])

    def test_recurring_list_enriches_donation_following_a_dropped_one(self):
        """The donation after a dropped one must still receive its Mollie fields.

        Regression for #348: enrichment and the active-check shared one loop, so
        the element the iterator skipped lost its subscription_status as well --
        the portal then rendered a live subscription as "Unknown" with no
        update/cancel buttons.
        """
        from verenigingen.templates.pages.manage_donations import get_recurring_donations

        # get_mollie_subscription_info logs its failed lookup before falling back.
        self.expectErrorLog("Manage Donations")

        self._make_recurring(amount=10.0, days_ago=0, cancelled=True)
        mollie = self._make_recurring(
            amount=25.0, days_ago=1, mollie_subscription_id=self._unresolvable_subscription_id()
        )

        result = get_recurring_donations(self.member.name)

        self.assertEqual([d.name for d in result], [mollie.name])
        self.assertIn("subscription_status", result[0])

    # ----- #349: "could not determine" is not "inactive" -----------------

    def test_undeterminable_mollie_status_keeps_donation_in_portal(self):
        """A donation whose Mollie status cannot be established stays listed.

        Regression for #349: an unresolvable/unreachable Mollie subscription used to
        read as "not active", and the donor's healthy recurring donation vanished
        from the portal as if it had been cancelled.
        """
        from verenigingen.templates.pages.manage_donations import get_recurring_donations

        self.expectErrorLog("Manage Donations")

        donation = self._make_recurring(
            amount=15.0, mollie_subscription_id=self._unresolvable_subscription_id()
        )

        result = get_recurring_donations(self.member.name)

        self.assertEqual([d.name for d in result], [donation.name])
        # The template renders this as the (red) "Unknown" status and hides the
        # action buttons -- "status unavailable", not "gone".
        self.assertEqual(result[0].subscription_status, "unknown")

    def test_undeterminable_mollie_status_counts_as_active_recurring(self):
        """The summary counter must agree with the list it summarises."""
        from verenigingen.templates.pages.manage_donations import get_donation_summary

        self.expectErrorLog("Manage Donations")

        self._make_recurring(amount=15.0, mollie_subscription_id=self._unresolvable_subscription_id())

        summary = get_donation_summary(self.member.name)

        self.assertEqual(summary["active_recurring"], 1)

    def test_state_is_unknown_and_logged_when_lookup_raises(self):
        """A raising Mollie lookup yields UNKNOWN and leaves a trace.

        Regression for #349: the bare ``except Exception: return False`` turned a
        transient outage into "inactive" and logged nothing at all.
        """
        from unittest.mock import patch

        from verenigingen.templates.pages import manage_donations

        donation = self._make_recurring(amount=12.0, mollie_subscription_id="sub_unreachable")
        self.expectErrorLog("Manage Donations")

        # Patch our own Mollie wrapper (not business logic, and no network call) to
        # simulate the outage the real API raises on.
        with patch.object(
            manage_donations,
            "get_mollie_subscription_info",
            side_effect=ConnectionError("Mollie unreachable"),
        ):
            state = manage_donations.get_recurring_donation_state(donation.name)

        self.assertEqual(state, manage_donations.RECURRING_STATE_UNKNOWN)

        # This module calls frappe.log_error(message, title), i.e. positionally
        # swapped against frappe's (title, message) signature -- so the message
        # lands in Error Log.method and the title in Error Log.error.
        logged = frappe.get_all(
            "Error Log", filters={"method": ["like", f"%{donation.name}%"]}, fields=["method", "error"]
        )
        self.assertTrue(
            any("Mollie unreachable" in f"{row.method}\n{row.error}" for row in logged),
            f"the swallowed exception was not logged (rows naming the donation: {len(logged)})",
        )

    def test_state_is_inactive_for_missing_donation(self):
        """A donation that does not exist is definitively inactive, not unknown."""
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_INACTIVE,
            get_recurring_donation_state,
        )

        self.assertEqual(get_recurring_donation_state("Nonexistent-Donation-XYZ"), RECURRING_STATE_INACTIVE)

    def test_is_recurring_active_true_for_recurring(self):
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_ACTIVE,
            get_recurring_donation_state,
        )

        donation = self._make_donation(status="Recurring", recurring_freq="Monthly")
        self.assertEqual(get_recurring_donation_state(donation.name), RECURRING_STATE_ACTIVE)

    def test_is_recurring_active_false_for_one_time(self):
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_INACTIVE,
            get_recurring_donation_state,
        )

        donation = self._make_donation(status="One-time")
        self.assertEqual(get_recurring_donation_state(donation.name), RECURRING_STATE_INACTIVE)

    def test_is_recurring_active_false_after_cancellation_date(self):
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_INACTIVE,
            get_recurring_donation_state,
        )

        donation = self._make_donation(status="Recurring", recurring_freq="Monthly")
        # A past cancellation date marks it inactive.
        donation.db_set("recurring_cancelled_date", "2000-01-01")
        self.assertEqual(get_recurring_donation_state(donation.name), RECURRING_STATE_INACTIVE)

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

    # ----- a charge donation is not the subscription -------------------
    #
    # Task 9 gave the two READ paths the recurring_origin_donation
    # discriminator and left the two WRITE paths without it. A charge satisfies
    # every gate those writers have (see the precondition test below), and the
    # donor is handed the charge's exact document name every period --
    # send_payment_confirmation_email puts it in the mail context -- so this is
    # reachable without guessing an id.

    def test_a_charge_donation_satisfies_every_pre_existing_gate(self):
        """Precondition, without which the two rejections below prove nothing.

        If a charge failed the ownership / status / liveness checks anyway, a
        rejection would not tell us the new guard is what did it.
        """
        # is_recurring_donation_active was replaced on develop by the tri-state
        # get_recurring_donation_state: the liveness gate now rejects only what is
        # CONFIRMED inactive, so "would pass" means "is not confirmed inactive".
        from verenigingen.templates.pages.manage_donations import (
            RECURRING_STATE_INACTIVE,
            get_recurring_donation_state,
        )

        _origin, charge = self._setup_origin_and_charge()
        self.assertEqual(charge.donor_email, self.email, "ownership check would pass")
        self.assertEqual(charge.status, "Recurring", "the status check would pass")
        self.assertNotEqual(
            get_recurring_donation_state(charge.name),
            RECURRING_STATE_INACTIVE,
            "the liveness check would pass",
        )

    def test_update_rejects_a_charge_donation(self):
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        _origin, charge = self._setup_origin_and_charge()
        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({"donation_id": charge.name, "new_amount": 99.0})
            try:
                with self.assertRaises(frappe.ValidationError):
                    update_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

        charge.reload()
        self.assertEqual(
            charge.amount,
            25.0,
            "the historical amount of a settled charge must not be rewritten -- its Journal "
            "Entry, the GL and the agreement's child row all keep the real figure",
        )

    def test_update_still_accepts_the_origin_donation(self):
        """CONTROL. Without it, a broken endpoint reads as a working guard."""
        from verenigingen.templates.pages.manage_donations import update_recurring_donation

        origin, _charge = self._setup_origin_and_charge()
        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({"donation_id": origin.name, "new_amount": 99.0})
            try:
                result = update_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

        self.assertEqual(result.get("status"), "success", f"the origin must still be updatable: {result}")
        origin.reload()
        self.assertEqual(origin.amount, 99.0)

    def test_cancel_rejects_a_charge_donation(self):
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

        _origin, charge = self._setup_origin_and_charge()
        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({"donation_id": charge.name})
            try:
                with self.assertRaises(frappe.ValidationError):
                    cancel_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

        charge.reload()
        self.assertFalse(
            charge.recurring_cancelled_date,
            "cancelling a past charge stamps one payment and leaves the subscription charging",
        )

    def test_cancel_still_accepts_the_origin_donation(self):
        """CONTROL, as above."""
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation

        origin, _charge = self._setup_origin_and_charge()
        with self.as_user(self.user):
            frappe.form_dict = frappe._dict({"donation_id": origin.name})
            try:
                result = cancel_recurring_donation()
            finally:
                frappe.form_dict = frappe._dict()

        self.assertEqual(result.get("status"), "success", f"the origin must still be cancellable: {result}")
        origin.reload()
        self.assertTrue(origin.recurring_cancelled_date)
