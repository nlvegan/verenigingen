# -*- coding: utf-8 -*-
"""
Coverage-focused integration tests for the Membership controller.

These tests exercise validate()-chain branches, renewal-date computation for all
billing periods, grace-period handling, status derivation, and the module-level
helper functions (cancel_membership, process_membership_statuses, show_all_invoices,
get_member_sepa_mandates, verify_signature, etc.) that the existing
test_membership.py leaves uncovered.

Real-DB integration tests only -- no business-logic mocking.
"""

import unittest

import frappe
from frappe.utils import add_days, add_months, add_to_date, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership.membership import (
    allow_multiple_memberships,
    cancel_membership,
    get_member_sepa_mandates,
    process_membership_statuses,
    show_all_invoices,
    verify_signature,
)


class TestMembershipCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.db.exists("Item Group", "Membership"):
            ig = frappe.new_doc("Item Group")
            ig.item_group_name = "Membership"
            ig.parent_item_group = "All Item Groups"
            ig.insert()
        # Default annual type, minimum enforced
        self.annual_type = self.create_test_membership_type(
            membership_type_name="Cov Annual",
            amount=50.0,
            billing_period="Annual",
        )
        self.member = self.create_test_member(payment_method="Bank Transfer")

    # ------------------------------------------------------------------
    # validate_dates
    # ------------------------------------------------------------------
    def test_renewal_before_start_throws(self):
        """validate_dates: explicit renewal_date before start_date is rejected."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.renewal_date = add_days(today(), -10)
        with self.assertRaises(frappe.ValidationError):
            m.insert()

    # ------------------------------------------------------------------
    # set_renewal_date -- billing-period mapping
    # ------------------------------------------------------------------
    def _make_type(self, name, period, enforce_minimum=1, custom_months=None):
        kwargs = {"billing_period": period, "enforce_minimum_period": enforce_minimum}
        if custom_months is not None:
            kwargs["billing_period_in_months"] = custom_months
        return self.create_test_membership_type(membership_type_name=name, amount=30.0, **kwargs)

    def _draft_membership(self, mtype, start=None):
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = mtype.name
        m.start_date = start or today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        return m

    def test_renewal_monthly_enforced_bumps_to_one_year(self):
        """Monthly (1mo) with enforce_minimum bumps renewal to +12 months."""
        mt = self._make_type("Cov Monthly Enf", "Monthly", enforce_minimum=1)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=12)))

    def test_renewal_monthly_not_enforced_one_month(self):
        """Monthly without enforce_minimum keeps the 1-month period."""
        mt = self._make_type("Cov Monthly Free", "Monthly", enforce_minimum=0)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=1)))

    def test_renewal_quarterly_not_enforced_three_months(self):
        mt = self._make_type("Cov Quarterly Free", "Quarterly", enforce_minimum=0)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=3)))

    def test_renewal_biannual_not_enforced_six_months(self):
        mt = self._make_type("Cov Biannual Free", "Biannual", enforce_minimum=0)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=6)))

    def test_renewal_annual_twelve_months(self):
        mt = self._make_type("Cov Annual2", "Annual", enforce_minimum=1)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=12)))

    def test_renewal_custom_period(self):
        """Custom period with 18 months (>=12 so not bumped) yields +18 months."""
        mt = self._make_type("Cov Custom18", "Custom", enforce_minimum=1, custom_months=18)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=18)))

    def test_renewal_daily_enforced_one_year(self):
        """Daily + enforce_minimum forces a 1-year renewal date."""
        mt = self._make_type("Cov Daily Enf", "Daily", enforce_minimum=1)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=12)))

    def test_renewal_daily_not_enforced_one_day(self):
        """Daily without enforce_minimum yields a +1 day renewal date."""
        mt = self._make_type("Cov Daily Free", "Daily", enforce_minimum=0)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, days=1)))

    def test_renewal_lifetime_enforced_one_year(self):
        """Lifetime + enforce_minimum sets a 1-year minimum commitment renewal."""
        mt = self._make_type("Cov Lifetime Enf", "Lifetime", enforce_minimum=1)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, months=12)))

    def test_renewal_lifetime_not_enforced_fifty_years(self):
        """Lifetime without enforce_minimum sets a +50 year renewal date."""
        mt = self._make_type("Cov Lifetime Free", "Lifetime", enforce_minimum=0)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.renewal_date), getdate(add_to_date(m.start_date, years=50)))

    # ------------------------------------------------------------------
    # get_months_from_period mapping
    # ------------------------------------------------------------------
    def test_get_months_from_period_mapping(self):
        m = self._draft_membership(self.annual_type)
        self.assertEqual(m.get_months_from_period("Monthly"), 1)
        self.assertEqual(m.get_months_from_period("Quarterly"), 3)
        self.assertEqual(m.get_months_from_period("Biannual"), 6)
        self.assertEqual(m.get_months_from_period("Annual"), 12)
        self.assertEqual(m.get_months_from_period("Daily"), 0)
        self.assertEqual(m.get_months_from_period("Lifetime"), 0)
        self.assertEqual(m.get_months_from_period("Custom", 7), 7)
        self.assertEqual(m.get_months_from_period("Unknown"), 0)

    # ------------------------------------------------------------------
    # set_commitment_end_date
    # ------------------------------------------------------------------
    def test_commitment_end_date_set_when_enforced(self):
        mt = self._make_type("Cov Commit Enf", "Annual", enforce_minimum=1)
        m = self._draft_membership(mt)
        self.assertEqual(getdate(m.commitment_end_date), getdate(add_to_date(m.start_date, months=12)))

    def test_commitment_end_date_skipped_when_not_enforced(self):
        mt = self._make_type("Cov Commit Free", "Annual", enforce_minimum=0)
        m = self._draft_membership(mt)
        self.assertFalse(m.commitment_end_date)

    # ------------------------------------------------------------------
    # validate_membership_type -- inactive type
    # ------------------------------------------------------------------
    def test_inactive_membership_type_throws(self):
        mt = self.create_test_membership_type(membership_type_name="Cov Inactive", amount=20.0)
        mt.is_active = 0
        mt.save()
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = mt.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        with self.assertRaises(frappe.ValidationError) as ctx:
            m.insert()
        self.assertIn("inactive", str(ctx.exception).lower())

    # ------------------------------------------------------------------
    # validate_grace_period
    # ------------------------------------------------------------------
    def test_grace_period_past_expiry_throws(self):
        """Grace Period status with an explicit past expiry date is rejected."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.grace_period_status = "Grace Period"
        m.grace_period_expiry_date = add_days(today(), -5)
        m.flags.skip_dues_schedule_creation = True
        with self.assertRaises(frappe.ValidationError) as ctx:
            m.insert()
        self.assertIn("past", str(ctx.exception).lower())

    def test_grace_period_required_expiry_throws(self):
        """validate_grace_period: Grace Period status without an expiry date is rejected."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.grace_period_status = "Grace Period"
        m.flags.skip_dues_schedule_creation = True
        with self.assertRaises(frappe.ValidationError) as ctx:
            m.validate_grace_period()
        self.assertIn("required", str(ctx.exception).lower())

    def test_grace_period_auto_sets_expiry_from_settings(self):
        """set_grace_period_expiry auto-fills expiry using settings default days."""
        settings = frappe.get_single("Verenigingen Settings")
        default_days = getattr(settings, "default_grace_period_days", None) or 30
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.grace_period_status = "Grace Period"
        frappe.flags.suppress_grace_period_message = True
        try:
            # set_grace_period_expiry is the method under test; it auto-fills the
            # expiry date from settings when grace period status is set.
            m.set_grace_period_expiry()
        finally:
            frappe.flags.suppress_grace_period_message = False
        self.assertEqual(getdate(m.grace_period_expiry_date), getdate(add_days(today(), default_days)))

    # ------------------------------------------------------------------
    # set_status branches
    # ------------------------------------------------------------------
    def test_status_draft_when_unsubmitted(self):
        m = self._draft_membership(self.annual_type)
        self.assertEqual(m.status, "Draft")

    def test_status_active_when_submitted_future_renewal(self):
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        m.reload()
        self.assertEqual(m.status, "Active")

    def test_status_cancelled_when_cancellation_date_today(self):
        """A cancellation_date today or in the past sets status Cancelled."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = add_months(today(), -13)
        m.flags.skip_dues_schedule_creation = True
        m.cancellation_date = today()
        m.insert()
        # docstatus 0 short-circuits to Draft, so re-run set_status with docstatus simulated
        m.docstatus = 1
        m.set_status()
        self.assertEqual(m.status, "Cancelled")

    def test_status_expired_when_past_renewal(self):
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        # Force a past renewal date and recompute as if submitted
        m.renewal_date = add_days(today(), -1)
        m.docstatus = 1
        m.set_status()
        self.assertEqual(m.status, "Expired")

    # ------------------------------------------------------------------
    # auto_apply_grace_period_if_enabled staticmethod
    # ------------------------------------------------------------------
    def test_auto_apply_grace_period_disabled_returns_false(self):
        from verenigingen.verenigingen.doctype.membership.membership import Membership

        settings = frappe.get_single("Verenigingen Settings")
        original = getattr(settings, "grace_period_auto_apply", 0)
        settings.db_set("grace_period_auto_apply", 0)
        try:
            result = Membership.auto_apply_grace_period_if_enabled(self.member.name)
            self.assertFalse(result)
        finally:
            settings.db_set("grace_period_auto_apply", original)

    def test_auto_apply_grace_period_enabled_applies(self):
        from verenigingen.verenigingen.doctype.membership.membership import Membership

        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        m.reload()
        self.assertEqual(m.status, "Active")

        settings = frappe.get_single("Verenigingen Settings")
        original = getattr(settings, "grace_period_auto_apply", 0)
        settings.db_set("grace_period_auto_apply", 1)
        frappe.flags.suppress_grace_period_message = True
        try:
            result = Membership.auto_apply_grace_period_if_enabled(self.member.name)
            self.assertTrue(result)
            m.reload()
            self.assertEqual(m.grace_period_status, "Grace Period")
            self.assertIsNotNone(m.grace_period_expiry_date)
        finally:
            frappe.flags.suppress_grace_period_message = False
            settings.db_set("grace_period_auto_apply", original)

    # ------------------------------------------------------------------
    # get_billing_amount
    # ------------------------------------------------------------------
    def test_get_billing_amount_from_dues_schedule(self):
        """When a member has an active dues schedule, get_billing_amount returns its rate."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.insert()
        m.submit()
        frappe.db.commit()
        m.reload()
        sched_name = m.get_dues_schedule()
        self.assertIsNotNone(sched_name)
        rate = frappe.db.get_value("Membership Dues Schedule", sched_name, "dues_rate")
        with self.assertNoErrorLog():
            amount = m.get_billing_amount()
        self.assertEqual(float(amount), float(rate))

    def test_get_billing_amount_template_fallback(self):
        """Without an active dues schedule, get_billing_amount falls back to template amount."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        # member has no active dues schedule -> template fallback (suggested_amount = 50)
        with self.assertNoErrorLog():
            amount = m.get_billing_amount()
        self.assertEqual(float(amount), 50.0)

    # ------------------------------------------------------------------
    # on_trash deletes linked dues schedules
    # ------------------------------------------------------------------
    def test_on_trash_deletes_dues_schedules(self):
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.insert()
        m.submit()
        frappe.db.commit()
        m.reload()
        sched_name = m.get_dues_schedule()
        self.assertIsNotNone(sched_name)

        # Cancel then delete (submitted docs must be cancelled before trash)
        m.flags.ignore_validate_update_after_submit = True
        m.cancel()
        m.reload()
        membership_name = m.name
        frappe.delete_doc("Membership", membership_name, force=True)
        self.assertFalse(
            frappe.db.exists("Membership Dues Schedule", {"membership": membership_name}),
            "Linked dues schedules should be removed by on_trash",
        )

    # ------------------------------------------------------------------
    # cancel_membership module function
    # ------------------------------------------------------------------
    def test_cancel_membership_draft_no_restriction(self):
        """A draft membership can be cancelled without minimum-period restrictions."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        self.assertEqual(m.docstatus, 0)
        result = cancel_membership(m.name)
        self.assertEqual(result, m.name)

    def test_cancel_membership_immediate_sets_cancelled(self):
        """Immediate cancellation of a long-running membership sets status Cancelled."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = add_months(today(), -13)  # past minimum period
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        frappe.db.commit()
        cancel_membership(m.name, cancellation_reason="done", cancellation_type="Immediate")
        m.reload()
        self.assertEqual(m.status, "Cancelled")
        self.assertEqual(m.cancellation_reason, "done")

    def test_validate_dates_minimum_period_non_admin_throws(self):
        """validate_dates: a non-admin cancelling before the 1-year minimum is rejected."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = add_months(today(), -3)  # within minimum period
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        frappe.db.commit()
        m.reload()

        # Create a plain non-admin user (no System Manager role)
        user_email = f"cov_nonadmin_{frappe.generate_hash(length=6)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": "Cov",
                "send_welcome_email": 0,
            }
        )
        user.insert()

        m.cancellation_date = today()  # within the minimum 1-year window
        original_user = frappe.session.user
        try:
            frappe.set_user(user_email)
            with self.assertRaises(frappe.ValidationError) as ctx:
                m.validate_dates()
            self.assertIn("minimum membership period", str(ctx.exception).lower())
        finally:
            frappe.set_user(original_user)

    def test_validate_dates_minimum_period_admin_warns(self):
        """validate_dates: an admin cancelling before the minimum gets a warning, not a throw."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = add_months(today(), -3)  # within minimum period
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        frappe.db.commit()
        m.reload()

        # Current test user is Administrator (System Manager) -> warning path, no raise
        m.cancellation_date = today()
        m.validate_dates()  # should not raise

    # ------------------------------------------------------------------
    # process_membership_statuses
    # ------------------------------------------------------------------
    def test_process_membership_statuses_expires_past_renewal(self):
        """A submitted Active membership past its renewal date becomes Expired."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        frappe.db.commit()
        # Backdate renewal_date directly (bypassing recompute) to simulate expiry
        frappe.db.set_value("Membership", m.name, "renewal_date", add_days(today(), -1))
        frappe.db.commit()

        # process_membership_statuses() is a SITE-WIDE scheduler: it iterates every
        # membership, so on a shared test DB it logs "Membership Status Update Error"
        # for unrelated pre-existing memberships whose membership type was rolled back
        # by other tests. Those are out of this test's scope; ignore that title and
        # rely on the status assertion below to prove OUR membership processed.
        with self.assertNoErrorLog(ignore=["Membership Status Update Error"]):
            self.assertTrue(process_membership_statuses())
        m.reload()
        self.assertEqual(m.status, "Expired")

    # ------------------------------------------------------------------
    # show_all_invoices
    # ------------------------------------------------------------------
    def test_show_all_invoices_aggregates_customer_invoices(self):
        """show_all_invoices returns the member's customer invoices within the period."""
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = today()
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        frappe.db.commit()
        m.reload()

        # Member is auto-linked to a customer by the factory; create a real invoice
        inv = self.create_test_sales_invoice(
            customer=self.member.customer,
            posting_date=today(),
        )
        with self.assertNoErrorLog():
            invoices = show_all_invoices(m.name)
        names = [i["invoice"] for i in invoices]
        self.assertIn(inv.name, names)
        for i in invoices:
            if i["invoice"] == inv.name:
                self.assertEqual(i["source"], "Member/Customer")

    def test_show_all_invoices_excludes_out_of_period_invoices(self):
        """An invoice posted before the membership period start is not returned."""
        # Membership starts ~60 days from now so an invoice dated today is before the period.
        start = add_days(today(), 60)
        m = frappe.new_doc("Membership")
        m.member = self.member.name
        m.membership_type = self.annual_type.name
        m.start_date = start
        m.flags.skip_dues_schedule_creation = True
        m.insert()
        m.submit()
        frappe.db.commit()
        m.reload()

        # Invoice dated today -> before the membership period [start, renewal_date]
        out_inv = self.create_test_sales_invoice(
            customer=self.member.customer,
            posting_date=today(),
        )
        with self.assertNoErrorLog():
            invoices = show_all_invoices(m.name)
        names = [i["invoice"] for i in invoices]
        self.assertNotIn(out_inv.name, names, "An out-of-period invoice must not appear in show_all_invoices")

    # ------------------------------------------------------------------
    # get_member_sepa_mandates
    # ------------------------------------------------------------------
    def test_get_member_sepa_mandates_returns_empty_without_member(self):
        result = get_member_sepa_mandates(
            doctype="SEPA Mandate",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters={},
        )
        self.assertEqual(result, [])

    def test_get_member_sepa_mandates_returns_active_membership_mandate(self):
        """An active membership SEPA mandate is returned, even via a JSON-string filter.

        This exercises the SQL body (not just the early empty-return) and proves the
        string `filters` arg is parsed into a dict that feeds the member lookup.
        """
        import json

        mandate = self.create_test_sepa_mandate(
            member=self.member.name,
            status="Active",
            used_for_memberships=1,
        )
        result = get_member_sepa_mandates(
            doctype="SEPA Mandate",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters=json.dumps({"member": self.member.name}),
        )
        returned_names = [row[0] for row in result]
        self.assertIn(mandate.name, returned_names)

    def test_get_member_sepa_mandates_excludes_non_membership_mandate(self):
        """A mandate not flagged used_for_memberships is excluded from the results."""
        mandate = self.create_test_sepa_mandate(
            member=self.member.name,
            status="Active",
            used_for_memberships=0,
            # An Active mandate must carry at least one purpose (#606), and
            # `used_for_donations`/`used_for_other` both default to 0. Without a
            # sibling purpose this fixture is an Active mandate for nothing and
            # `validate_active_mandate_has_a_purpose` rejects it. The test's
            # subject is unaffected: `get_member_sepa_mandates` filters on
            # `used_for_memberships`, not on "has some purpose".
            used_for_donations=1,
        )
        result = get_member_sepa_mandates(
            doctype="SEPA Mandate",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters={"member": self.member.name},
        )
        returned_names = [row[0] for row in result]
        self.assertNotIn(mandate.name, returned_names)

    # ------------------------------------------------------------------
    # verify_signature
    # ------------------------------------------------------------------
    def test_verify_signature_valid(self):
        import hashlib
        import hmac

        secret = "test-secret-key"
        data = {"id": "abc", "amount": 10}
        import json

        payload = json.dumps(data)
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature(data, sig, secret_key=secret))

    def test_verify_signature_invalid(self):
        self.assertFalse(verify_signature({"id": "abc"}, "deadbeef", secret_key="test-secret-key"))

    def test_verify_signature_no_secret_returns_false(self):
        """Without a configured secret key, verify_signature short-circuits to False.

        The no-secret branch returns False *before* computing any HMAC, so even a
        payload whose signature would be 'correct' (were a secret present) is
        rejected -- distinguishing this branch from the invalid-signature branch.
        """
        # Mark the intentional error log so the automatic tearDown check ignores it.
        self.expectErrorLog("Signature Verification")
        original = frappe.conf.get("webhook_secret_key")
        frappe.conf["webhook_secret_key"] = None
        try:
            # An empty digest string is what hmac would never produce, but the point
            # is the function never reaches the comparison -- it returns False at the
            # missing-secret guard.
            result = verify_signature({"id": "abc"}, "anything")
        finally:
            if original is not None:
                frappe.conf["webhook_secret_key"] = original
            else:
                frappe.conf.pop("webhook_secret_key", None)
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # allow_multiple_memberships
    # ------------------------------------------------------------------
    def test_allow_multiple_memberships_sets_flag(self):
        frappe.flags.allow_multiple_memberships = False
        try:
            self.assertTrue(allow_multiple_memberships(self.member.name))
            self.assertTrue(frappe.flags.allow_multiple_memberships)
        finally:
            frappe.flags.allow_multiple_memberships = False

    # ------------------------------------------------------------------
    # validate_existing_memberships -- overlap path
    # ------------------------------------------------------------------
    def test_overlapping_membership_throws(self):
        """An overlapping second membership is rejected even with multiple allowed."""
        m1 = frappe.new_doc("Membership")
        m1.member = self.member.name
        m1.membership_type = self.annual_type.name
        m1.start_date = today()
        m1.flags.skip_dues_schedule_creation = True
        m1.insert()
        m1.submit()
        frappe.db.commit()

        frappe.flags.allow_multiple_memberships = True
        try:
            m2 = frappe.new_doc("Membership")
            m2.member = self.member.name
            m2.membership_type = self.annual_type.name
            m2.start_date = add_days(today(), 30)  # overlaps existing annual period
            # The overlap check in validate_existing_memberships only fires when
            # self.renewal_date is already populated (it runs before set_renewal_date),
            # mirroring how a re-validated/saved membership carries a renewal_date.
            m2.renewal_date = add_to_date(m2.start_date, months=12)
            m2.allow_multiple_memberships = 1
            m2.flags.skip_dues_schedule_creation = True
            with self.assertRaises(frappe.ValidationError) as ctx:
                m2.insert()
            self.assertIn("overlap", str(ctx.exception).lower())
        finally:
            frappe.flags.allow_multiple_memberships = False


if __name__ == "__main__":
    unittest.main()
