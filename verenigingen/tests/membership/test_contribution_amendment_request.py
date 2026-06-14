"""
Real-integration tests for the Contribution Amendment Request controller and its
whitelisted helper endpoints in
``verenigingen/verenigingen/doctype/contribution_amendment_request/contribution_amendment_request.py``.

The controller was only ~63% covered. Untested areas included the scheduled
processor (``process_pending_amendments``), the reject endpoint, dues-schedule /
fee-change application delegators, the Mollie-sync-failure handler, the
error-formatting helper, the fee-change-amendment factory endpoint, the
pending-amendments query, the impact-preview generator, and the
detail-population helpers (set_current_details / set_default_effective_date /
before_insert).

These tests create real Members, Membership Types and Memberships via the
factory (no business-logic mocking) and run as Administrator. Mollie sync and
notification paths are exercised only via their guard/early-return branches; no
real Mollie API or email delivery is invoked.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
    ERROR_MESSAGE_MAX_LENGTH,
    create_fee_change_amendment,
    format_error_for_logging,
    get_member_pending_contribution_amendments,
    process_pending_amendments,
)


class TestContributionAmendmentRequest(VereningingenTestCase):
    """Exercise the Contribution Amendment Request controller + endpoints end to end."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Amendment",
            last_name="Endpoint",
            email=f"amendment.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"AmendType{frappe.generate_hash(length=6)}",
        )
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.membership_type.name,
        )
        self.membership.submit()
        self.membership.reload()

    def _make_amendment(self, **overrides):
        """Build (but do not insert) an amendment doc for this member."""
        data = {
            "doctype": "Contribution Amendment Request",
            "membership": self.membership.name,
            "member": self.member.name,
            "amendment_type": "Fee Change",
            "requested_amount": 25.0,
            "reason": "test amendment",
            "effective_date": add_days(today(), 30),
            "status": "Draft",
        }
        data.update(overrides)
        return frappe.get_doc(data)

    def _insert_amendment(self, **overrides):
        amendment = self._make_amendment(**overrides)
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        return amendment

    # ------------------------------------------------------------------ format_error_for_logging

    def test_format_error_for_logging_short(self):
        result = format_error_for_logging(ValueError("boom"), context="ctx")
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(result["error_message"], "boom")
        self.assertFalse(result["full_error_logged"])
        self.assertEqual(result["context"], "ctx")

    def test_format_error_for_logging_truncates_long(self):
        long_msg = "x" * (ERROR_MESSAGE_MAX_LENGTH + 50)
        result = format_error_for_logging(Exception(long_msg))
        self.assertEqual(len(result["error_message"]), ERROR_MESSAGE_MAX_LENGTH)
        self.assertTrue(result["full_error_logged"])

    def test_format_error_for_logging_string_input(self):
        result = format_error_for_logging("plain string error")
        self.assertEqual(result["error_type"], "str")
        self.assertEqual(result["error_message"], "plain string error")

    # ------------------------------------------------------------------ before_insert / details

    def test_before_insert_sets_requested_date_and_details(self):
        amendment = self._insert_amendment()
        # requested_date is auto-populated even though get_doc({...}) skips the
        # field "Today" default.
        self.assertTrue(amendment.requested_date)
        # set_current_details ran -> current type + requested-by populated.
        self.assertEqual(amendment.current_membership_type, self.membership_type.name)
        self.assertTrue(amendment.requested_by)

    def test_set_current_details_uses_active_dues_schedule(self):
        amendment = self._insert_amendment()
        # The submitted membership created a dues schedule; current_amount should
        # be pulled from it (a positive number) and current_dues_schedule linked.
        self.assertIsNotNone(amendment.current_amount)
        self.assertTrue(amendment.current_dues_schedule)
        self.assertTrue(amendment.current_billing_interval)

    def test_set_default_effective_date_when_absent(self):
        # Omit effective_date -> the controller derives one (next billing period
        # or today+30), never in the past.
        amendment = self._make_amendment(effective_date=None)
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        self.assertTrue(amendment.effective_date)
        self.assertGreaterEqual(getdate(amendment.effective_date), getdate(today()))

    # ------------------------------------------------------------------ create_fee_change_amendment

    def test_create_fee_change_amendment_creates_request(self):
        amendment = create_fee_change_amendment(
            self.member.name,
            new_amount=22.0,
            reason="endpoint fee change",
            effective_date=add_days(today(), 30),
        )
        self.track_doc("Contribution Amendment Request", amendment.name)
        self.assertEqual(amendment.amendment_type, "Fee Change")
        self.assertEqual(float(amendment.requested_amount), 22.0)
        self.assertEqual(amendment.member, self.member.name)

    def test_create_fee_change_amendment_default_effective_date(self):
        amendment = create_fee_change_amendment(
            self.member.name,
            new_amount=23.0,
            reason="default date",
        )
        self.track_doc("Contribution Amendment Request", amendment.name)
        self.assertTrue(amendment.effective_date)

    def test_create_fee_change_amendment_no_active_membership_throws(self):
        lonely = self.create_test_member(
            first_name="NoMembership",
            last_name="Member",
            email=f"nomem.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        with self.assertRaises(frappe.ValidationError):
            create_fee_change_amendment(lonely.name, new_amount=20.0, reason="x")

    # ------------------------------------------------------------------ get_member_pending_contribution_amendments

    def test_get_member_pending_contribution_amendments_includes_pending(self):
        # before_insert auto-approves a minimum-respecting fee increase, but a
        # future-dated Approved amendment still counts as pending in this query.
        amendment = self._insert_amendment()
        result = get_member_pending_contribution_amendments(self.member.name)
        self.assertTrue(any(a["name"] == amendment.name for a in result))
        statuses = {a["status"] for a in result}
        self.assertTrue(statuses & {"Draft", "Pending Approval", "Approved"})

    def test_get_member_pending_contribution_amendments_excludes_expired_approved(self):
        # An approved amendment whose effective date is in the past must be
        # filtered out of the pending list.
        amendment = self._insert_amendment(status="Draft")
        amendment.db_set("status", "Approved")
        amendment.db_set("effective_date", add_days(today(), -10))
        result = get_member_pending_contribution_amendments(self.member.name)
        self.assertFalse(any(a["name"] == amendment.name for a in result))

    def test_get_member_pending_contribution_amendments_empty(self):
        lonely = self.create_test_member(
            first_name="Empty",
            last_name="Amendments",
            email=f"empty.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.assertEqual(get_member_pending_contribution_amendments(lonely.name), [])

    # ------------------------------------------------------------------ get_impact_preview

    def test_get_impact_preview_fee_change_html(self):
        amendment = self._insert_amendment(requested_amount=30.0)
        preview = amendment.get_impact_preview()
        self.assertIn("html", preview)
        self.assertIn("Amendment Impact Preview", preview["html"])

    def test_get_impact_preview_non_fee_change(self):
        # A non-Fee-Change amendment returns the "no preview" stub.
        amendment = frappe.new_doc("Contribution Amendment Request")
        amendment.amendment_type = "Membership Type Change"
        amendment.membership = self.membership.name
        preview = amendment.get_impact_preview()
        self.assertEqual(preview["html"], "<p>No preview available</p>")

    def test_get_impact_preview_no_membership(self):
        amendment = frappe.new_doc("Contribution Amendment Request")
        amendment.amendment_type = "Fee Change"
        preview = amendment.get_impact_preview()
        self.assertEqual(preview["html"], "<p>No preview available</p>")

    # ------------------------------------------------------------------ reject_amendment

    def test_reject_amendment_pending(self):
        # Build a pending amendment, then reject it.
        amendment = self._insert_amendment()
        amendment.db_set("status", "Pending Approval")
        amendment.reload()
        amendment.reject_amendment("not justified")
        amendment.reload()
        self.assertEqual(amendment.status, "Rejected")
        self.assertEqual(amendment.rejection_reason, "not justified")

    def test_reject_amendment_non_pending_throws(self):
        amendment = self._insert_amendment(status="Draft")
        # Draft (not Pending Approval) cannot be rejected.
        with self.assertRaises(frappe.ValidationError):
            amendment.reject_amendment("nope")

    # ------------------------------------------------------------------ create_dues_schedule_for_amendment / apply_fee_change

    def test_apply_fee_change_updates_schedule(self):
        # Approve then apply a fee change; the active dues schedule's rate should
        # reflect the requested amount.
        amendment = self._insert_amendment(requested_amount=21.0)
        amendment.db_set("status", "Approved")
        amendment.db_set("effective_date", today())
        amendment.reload()
        amendment._force_apply = True
        result = amendment.apply_amendment()
        self.assertEqual(result["status"], "success")
        amendment.reload()
        self.assertEqual(amendment.status, "Applied")
        # The member's active schedule now bills the requested amount.
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.assertTrue(schedule_name)
        self.assertEqual(
            float(frappe.db.get_value("Membership Dues Schedule", schedule_name, "dues_rate")),
            21.0,
        )

    def test_create_dues_schedule_for_amendment_delegates(self):
        # The delegator returns a dues-schedule name (creating one if needed).
        amendment = self._insert_amendment(requested_amount=19.0)
        amendment.db_set("status", "Approved")
        amendment.reload()
        schedule_name = amendment.create_dues_schedule_for_amendment()
        self.assertTrue(schedule_name)
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule_name))

    # ------------------------------------------------------------------ handle_mollie_sync_failure

    def test_handle_mollie_sync_failure_sets_status(self):
        amendment = self._insert_amendment()
        # No admin recipients / templates required for the status update path; the
        # notification send is wrapped in try/except so a missing template cannot
        # break the status transition.
        amendment.handle_mollie_sync_failure("simulated sync error")
        self.assertEqual(
            frappe.db.get_value(
                "Contribution Amendment Request", amendment.name, "mollie_sync_status"
            ),
            "Failed",
        )

    # ------------------------------------------------------------------ process_pending_amendments

    def test_process_pending_amendments_applies_due(self):
        # An approved amendment with an effective date today should be applied by
        # the scheduled processor.
        amendment = self._insert_amendment(requested_amount=18.0)
        amendment.db_set("status", "Approved")
        amendment.db_set("effective_date", today())
        result = process_pending_amendments()
        self.assertTrue(result["success"])
        # Our amendment was eligible and applied.
        amendment.reload()
        self.assertEqual(amendment.status, "Applied")

    def test_process_pending_amendments_returns_summary(self):
        # Even with no eligible amendments it returns a success summary dict.
        result = process_pending_amendments()
        self.assertTrue(result["success"])
        self.assertIn("processed", result)
        self.assertIn("errors", result)

    # ------------------------------------------------------------------ validate_amount_changes guards

    def test_amendment_rejects_zero_requested_amount(self):
        with self.assertRaises(frappe.ValidationError):
            self._insert_amendment(requested_amount=0)

    def test_amendment_rejects_same_amount(self):
        # current_amount comes from the active dues schedule; requesting exactly
        # that triggers the "same as current amount" guard. Read the live rate.
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        current_rate = frappe.db.get_value(
            "Membership Dues Schedule", schedule_name, "dues_rate"
        )
        with self.assertRaises(frappe.ValidationError):
            self._insert_amendment(requested_amount=float(current_rate))
