"""
Real-integration tests for the Membership doctype controller and its
whitelisted helper endpoints in
``verenigingen/verenigingen/doctype/membership/membership.py``.

The controller was only ~58% covered: most of the standalone whitelisted
endpoints (payment history, invoices, SEPA-mandate query, billing amount,
status-processing scheduler, signature verification, grace-period helpers)
had no coverage. These tests create real Members, Membership Types,
Memberships and SEPA Mandates via the factory (no business-logic mocking)
and run as Administrator.

Note on the ``dues_schedule`` field: Membership has no ``dues_schedule``
column (verified against the DB schema), so ``membership.dues_schedule``
is falsy for normally-created memberships. The payment-history / invoice
endpoints therefore exercise their "no dues schedule" branches plus the
direct- and customer-invoice lookup paths.
"""

import json

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.membership import membership as mship

IBAN_TEST = "NL13TEST0123456789"
IBAN_MOCK = "NL82MOCK0123456789"


class TestMembershipEndpoints(VereningingenTestCase):
    """Exercise the Membership controller + whitelisted endpoints end to end."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Membership",
            last_name="Endpoint",
            email=f"membership.endpoint.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"MShipType{frappe.generate_hash(length=6)}",
        )
        # The base factory inserts the Membership as a Draft (docstatus 0) and does
        # NOT submit it, so on_submit (which creates the member's dues schedule)
        # never runs. Submit it here so the active-membership / dues-schedule
        # code paths are reachable. Membership Type.after_insert auto-creates the
        # dues-schedule template at the default 15.0 rate.
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.membership_type.name,
        )
        self.membership.submit()
        self.membership.reload()
        # The default dues-schedule template suggested_amount (in EUR).
        self.template_amount = 15.0

    # ------------------------------------------------------------------ get_billing_amount

    def test_get_billing_amount_from_dues_schedule(self):
        # The submitted membership created a dues schedule for the member; the
        # billing amount must come from that schedule's dues_rate.
        amount = self.membership.get_billing_amount()
        self.assertIsNotNone(amount)
        self.assertGreater(float(amount), 0)

    def test_get_billing_amount_no_member_falls_back_to_template(self):
        # A membership with a type but no member (no dues schedule) falls back to
        # the membership type template's suggested_amount.
        m = frappe.new_doc("Membership")
        m.membership_type = self.membership_type.name
        amount = m.get_billing_amount()
        self.assertEqual(float(amount), self.template_amount)

    def test_get_billing_amount_no_member_no_type_returns_zero(self):
        m = frappe.new_doc("Membership")
        self.assertEqual(m.get_billing_amount(), 0)

    # ------------------------------------------------------------------ calculate_effective_amount

    def test_calculate_effective_amount_deprecated_uses_template(self):
        # Deprecated path: pulls suggested_amount from the type template.
        amount = self.membership.calculate_effective_amount()
        self.assertEqual(float(amount), self.template_amount)

    def test_calculate_effective_amount_no_type_returns_zero(self):
        m = frappe.new_doc("Membership")
        self.assertEqual(m.calculate_effective_amount(), 0)

    # ------------------------------------------------------------------ get_dues_schedule / pause

    def test_get_dues_schedule_returns_active_schedule(self):
        schedule = self.membership.get_dues_schedule()
        self.assertTrue(schedule)
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule))

    def test_get_dues_schedule_no_member_returns_none(self):
        m = frappe.new_doc("Membership")
        self.assertIsNone(m.get_dues_schedule())

    def test_pause_dues_schedule_no_member_noop(self):
        # Guard clause: no member -> returns without touching anything.
        m = frappe.new_doc("Membership")
        self.assertIsNone(m.pause_dues_schedule())

    def test_pause_dues_schedule_pauses_active(self):
        schedule_name = self.membership.get_dues_schedule()
        self.assertTrue(schedule_name)
        self.membership.pause_dues_schedule()
        status = frappe.db.get_value("Membership Dues Schedule", schedule_name, "status")
        self.assertEqual(status, "Paused")

    # ------------------------------------------------------------------ show_payment_history

    def test_show_payment_history_no_dues_schedule(self):
        # Normal membership has no dues_schedule field set -> empty history.
        result = mship.show_payment_history(self.membership.name)
        self.assertEqual(result, [])

    # ------------------------------------------------------------------ show_all_invoices

    def test_show_all_invoices_empty(self):
        result = mship.show_all_invoices(self.membership.name)
        self.assertIsInstance(result, list)

    def test_show_all_invoices_includes_customer_invoice(self):
        # A submitted Sales Invoice for the member's customer, dated within the
        # membership period, must be returned via the Member/Customer lookup path.
        invoice = self.create_test_sales_invoice(member=self.member.name)
        invoice.submit()

        result = mship.show_all_invoices(self.membership.name)
        self.assertTrue(
            any(row["invoice"] == invoice.name for row in result),
            "the member's submitted invoice should be returned",
        )

    # ------------------------------------------------------------------ sync_membership_payments

    def test_sync_membership_payments_with_name_deprecated(self):
        # Deprecated stub: returns True for a specific membership.
        self.assertTrue(mship.sync_membership_payments(self.membership.name))

    def test_sync_membership_payments_all_returns_count(self):
        # Deprecated stub: returns a count (0) when no name is given.
        self.assertEqual(mship.sync_membership_payments(), 0)

    # ------------------------------------------------------------------ get_member_sepa_mandates

    def test_get_member_sepa_mandates_returns_active_membership_mandate(self):
        mandate = self.create_test_sepa_mandate(
            member=self.member.name,
            iban=IBAN_TEST,
            used_for_memberships=1,
        )
        rows = mship.get_member_sepa_mandates(
            doctype="SEPA Mandate",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters=json.dumps({"member": self.member.name}),
        )
        names = [r[0] for r in rows]
        self.assertIn(mandate.name, names)

    def test_get_member_sepa_mandates_resolves_member_from_membership(self):
        mandate = self.create_test_sepa_mandate(
            member=self.member.name,
            iban=IBAN_TEST,
            used_for_memberships=1,
        )
        # No "member" filter -> the function resolves it from the Membership doc.
        rows = mship.get_member_sepa_mandates(
            doctype="SEPA Mandate",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters=json.dumps({"doctype": "Membership", "name": self.membership.name}),
        )
        names = [r[0] for r in rows]
        self.assertIn(mandate.name, names)

    def test_get_member_sepa_mandates_no_member_returns_empty(self):
        rows = mship.get_member_sepa_mandates(
            doctype="SEPA Mandate",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters=json.dumps({}),
        )
        self.assertEqual(rows, [])

    def test_get_member_sepa_mandates_excludes_donation_only_mandate(self):
        # A mandate that is not flagged used_for_memberships must not appear.
        self.create_test_sepa_mandate(
            member=self.member.name,
            iban=IBAN_MOCK,
            used_for_memberships=0,
            used_for_donations=1,
        )
        rows = mship.get_member_sepa_mandates(
            doctype="SEPA Mandate",
            txt="",
            searchfield="name",
            start=0,
            page_len=20,
            filters=json.dumps({"member": self.member.name}),
        )
        statuses = [r for r in rows]
        # Only membership mandates qualify; none created here -> empty.
        self.assertEqual(statuses, [])

    # ------------------------------------------------------------------ verify_signature

    def test_verify_signature_valid(self):
        import hashlib
        import hmac

        secret = "test-secret-key"
        data = {"order": "123", "amount": "10.00"}
        import json

        payload = json.dumps(data).encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        self.assertTrue(mship.verify_signature(data, expected, secret_key=secret))

    def test_verify_signature_invalid(self):
        self.assertFalse(
            mship.verify_signature({"a": "b"}, "deadbeef", secret_key="test-secret-key")
        )

    def test_verify_signature_string_data(self):
        import hashlib
        import hmac

        secret = "abc"
        data = "raw-string-payload"
        expected = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()
        self.assertTrue(mship.verify_signature(data, expected, secret_key=secret))

    def test_verify_signature_no_secret_key_returns_false(self):
        # No secret_key passed and none in config -> logs and returns False.
        if frappe.conf.get("webhook_secret_key"):
            self.skipTest("webhook_secret_key configured in this environment")
        self.assertFalse(mship.verify_signature({"a": "b"}, "sig"))

    # ------------------------------------------------------------------ process_membership_statuses

    def test_process_membership_statuses_expires_past_renewal(self):
        # Force this membership past its renewal date, then run the scheduler.
        past = add_days(today(), -5)
        frappe.db.set_value(
            "Membership",
            self.membership.name,
            "renewal_date",
            past,
            update_modified=False,
        )
        result = mship.process_membership_statuses()
        self.assertTrue(result)
        self.assertEqual(
            frappe.db.get_value("Membership", self.membership.name, "status"), "Expired"
        )

    # ------------------------------------------------------------------ revert_to_standard_amount

    def test_revert_to_standard_amount_returns_standard(self):
        result = mship.revert_to_standard_amount(self.membership.name, reason="test revert")
        self.assertTrue(result["success"])
        self.assertEqual(float(result["new_amount"]), self.template_amount)
        self.assertIn("message", result)

    # ------------------------------------------------------------------ allow_multiple_memberships

    def test_allow_multiple_memberships_sets_flag(self):
        frappe.flags.allow_multiple_memberships = False
        self.assertTrue(mship.allow_multiple_memberships(self.member.name))
        self.assertTrue(frappe.flags.allow_multiple_memberships)
        # Clean up flag so it does not leak into other tests.
        frappe.flags.allow_multiple_memberships = False

    # ------------------------------------------------------------------ grace period

    def test_validate_grace_period_requires_expiry(self):
        m = frappe.new_doc("Membership")
        m.grace_period_status = "Grace Period"
        m.grace_period_expiry_date = None
        with self.assertRaises(frappe.ValidationError):
            m.validate_grace_period()

    def test_validate_grace_period_rejects_past_expiry(self):
        m = frappe.new_doc("Membership")
        m.grace_period_status = "Grace Period"
        m.grace_period_expiry_date = add_days(today(), -1)
        with self.assertRaises(frappe.ValidationError):
            m.validate_grace_period()

    def test_validate_grace_period_accepts_future_expiry(self):
        m = frappe.new_doc("Membership")
        m.grace_period_status = "Grace Period"
        m.grace_period_expiry_date = add_days(today(), 10)
        # Should not raise.
        m.validate_grace_period()

    def test_set_grace_period_expiry_autofills_from_settings(self):
        m = frappe.new_doc("Membership")
        m.grace_period_status = "Grace Period"
        frappe.flags.suppress_grace_period_message = True
        try:
            m.set_grace_period_expiry()
        finally:
            frappe.flags.suppress_grace_period_message = False
        self.assertTrue(m.grace_period_expiry_date)
        # Expiry is in the future (default 30 days from today).
        self.assertGreaterEqual(getdate(m.grace_period_expiry_date), getdate(today()))

    def test_set_grace_period_expiry_no_status_clears(self):
        m = frappe.new_doc("Membership")
        m.grace_period_status = ""
        m.set_grace_period_expiry()
        self.assertIsNone(m.grace_period_expiry_date)

    # ------------------------------------------------------------- auto_apply_grace_period_if_enabled

    def test_auto_apply_grace_period_disabled(self):
        original = frappe.db.get_single_value("Verenigingen Settings", "grace_period_auto_apply")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "grace_period_auto_apply", 0)
            self.assertFalse(
                mship.Membership.auto_apply_grace_period_if_enabled(self.member.name)
            )
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "grace_period_auto_apply", original or 0
            )

    def test_auto_apply_grace_period_no_active_membership(self):
        original = frappe.db.get_single_value("Verenigingen Settings", "grace_period_auto_apply")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "grace_period_auto_apply", 1)
            # A member with no active membership -> False.
            lonely = self.create_test_member(
                first_name="Lonely",
                last_name="NoMembership",
                email=f"lonely.{frappe.generate_hash(length=6)}@test.invalid",
                status="Active",
            )
            self.assertFalse(
                mship.Membership.auto_apply_grace_period_if_enabled(lonely.name)
            )
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "grace_period_auto_apply", original or 0
            )

    def test_auto_apply_grace_period_applies(self):
        original = frappe.db.get_single_value("Verenigingen Settings", "grace_period_auto_apply")
        try:
            frappe.db.set_single_value("Verenigingen Settings", "grace_period_auto_apply", 1)
            applied = mship.Membership.auto_apply_grace_period_if_enabled(self.member.name)
            self.assertTrue(applied)
            self.membership.reload()
            self.assertEqual(self.membership.grace_period_status, "Grace Period")
            # A second call is a no-op (already in grace period).
            self.assertFalse(
                mship.Membership.auto_apply_grace_period_if_enabled(self.member.name)
            )
        finally:
            frappe.db.set_single_value(
                "Verenigingen Settings", "grace_period_auto_apply", original or 0
            )

    # ------------------------------------------------------------------ validate_dates

    def test_validate_dates_renewal_before_start_throws(self):
        m = frappe.new_doc("Membership")
        m.start_date = today()
        m.renewal_date = add_days(today(), -10)
        with self.assertRaises(frappe.ValidationError):
            m.validate_dates()
