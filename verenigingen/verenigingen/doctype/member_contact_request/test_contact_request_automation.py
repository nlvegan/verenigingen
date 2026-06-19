"""
Tests for contact_request_automation.py

Covers the scheduled-automation helpers and the two whitelisted CRM endpoints
for the Member Contact Request doctype:

- send_follow_up_reminders
- escalate_overdue_requests / escalate_contact_request
- auto_close_resolved_requests
- sync_crm_status_updates
- process_contact_request_automation (top-level orchestrator)
- create_opportunity_from_contact_request (whitelisted, critical_api)
- get_contact_request_analytics (whitelisted, high_security_api)

Email delivery (frappe.sendmail) is the only thing patched: it is an external
service (SMTP), not business logic under test. All Member Contact Request /
Lead / Opportunity documents are real and persisted, and assertions check real
state changes, return values, raised exceptions and branch selection.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestContactRequestAutomation(VereningingenTestCase):
    """Integration tests for the contact request automation module."""

    def setUp(self):
        super().setUp()
        # An active member is required: the controller's validate() rejects
        # contact requests for members whose membership_status != "Active".
        self.member = self._make_active_member()

    # ------------------------------------------------------------------
    # Helpers (privileged data creation lives here, NOT in test bodies)
    # ------------------------------------------------------------------
    def _make_active_member(self):
        member = self.create_test_member(
            first_name="Auto",
            last_name="Mation",
            email="auto.mation.cra@example.invalid",
            contact_number="+31600000000",
        )
        # membership_status is a read-only computed field; force it Active so the
        # Member Contact Request controller validation passes for test inserts.
        frappe.db.set_value("Member", member.name, "membership_status", "Active")
        member.reload()
        return member

    def _make_contact_request(self, **overrides):
        data = {
            "doctype": "Member Contact Request",
            "member": self.member.name,
            "subject": "Automation Subject",
            "message": "Automation message body",
            "request_type": "General Inquiry",
            "preferred_contact_method": "Email",
            "urgency": "Normal",
            "status": "Open",
            "request_date": today(),
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert(ignore_permissions=True)
        self.track_doc("Member Contact Request", doc.name)
        return doc

    def _make_lead(self, **overrides):
        data = {
            "doctype": "Lead",
            "lead_name": "Automation Lead",
            "email_id": "automation.lead.cra@example.invalid",
            "status": "Open",
            "title": "Automation Lead",
        }
        data.update(overrides)
        lead = frappe.get_doc(data)
        lead.insert(ignore_permissions=True)
        self.track_doc("Lead", lead.name)
        return lead

    def _link_lead(self, request, lead):
        request.db_set("crm_lead", lead.name, update_modified=False)
        request.reload()

    # ------------------------------------------------------------------
    # send_follow_up_reminders
    # ------------------------------------------------------------------
    @patch("frappe.sendmail")
    def test_follow_up_reminder_advances_follow_up_date(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            send_follow_up_reminders,
        )

        request = self._make_contact_request(
            subject="Needs follow-up",
            status="Open",
            follow_up_date=today(),
            assigned_to="Administrator",
        )

        send_follow_up_reminders()

        request.reload()
        # The reminder pushes the follow-up date out 2 days to avoid duplicate
        # reminders on the next scheduler run.
        self.assertEqual(str(request.follow_up_date), add_days(today(), 2))

    @patch("frappe.sendmail")
    def test_follow_up_reminder_skips_unassigned_and_future_dated(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            send_follow_up_reminders,
        )

        # Unassigned -> excluded by the assigned_to != "" filter.
        unassigned = self._make_contact_request(
            subject="Unassigned", status="Open", follow_up_date=today(), assigned_to=None
        )
        # Future follow-up date -> excluded by the follow_up_date <= today filter.
        future = self._make_contact_request(
            subject="Future",
            status="Open",
            follow_up_date=add_days(today(), 5),
            assigned_to="Administrator",
        )

        send_follow_up_reminders()

        unassigned.reload()
        future.reload()
        # Unassigned request is excluded from the reminder query, so its
        # follow_up_date is NOT advanced (stays at today, not pushed +2 days).
        self.assertEqual(str(unassigned.follow_up_date), today())
        # Future-dated request is also excluded: still the original future date.
        self.assertEqual(str(future.follow_up_date), add_days(today(), 5))

    # ------------------------------------------------------------------
    # escalate_overdue_requests / escalate_contact_request
    # ------------------------------------------------------------------
    @patch("frappe.sendmail")
    def test_escalate_overdue_requests_adds_escalation_note(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            escalate_overdue_requests,
        )

        # Urgent threshold is 1 day; request_date 5 days ago is well past it.
        request = self._make_contact_request(
            subject="Urgent overdue",
            status="Open",
            urgency="Urgent",
            request_date=add_days(today(), -5),
        )

        escalate_overdue_requests()

        request.reload()
        self.assertIn("ESCALATED", request.notes or "")
        self.assertIn("Managers notified", request.notes)

    @patch("frappe.sendmail")
    def test_escalate_overdue_requests_skips_recent_low_urgency(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            escalate_overdue_requests,
        )

        # Low urgency threshold is 14 days; 2 days old is NOT overdue yet.
        request = self._make_contact_request(
            subject="Low recent",
            status="Open",
            urgency="Low",
            request_date=add_days(today(), -2),
        )

        escalate_overdue_requests()

        request.reload()
        self.assertNotIn("ESCALATED", request.notes or "")

    @patch("frappe.sendmail")
    def test_escalate_contact_request_appends_to_existing_notes(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            escalate_contact_request,
        )

        request = self._make_contact_request(
            subject="Has prior notes",
            status="In Progress",
            urgency="High",
            request_date=add_days(today(), -10),
            notes="PRIOR NOTE",
        )

        escalate_contact_request(
            frappe._dict(
                {
                    "name": request.name,
                    "subject": request.subject,
                    "member_name": self.member.full_name,
                    "assigned_to": None,
                    "request_date": request.request_date,
                    "urgency": "High",
                }
            ),
            10,
        )

        request.reload()
        # Prior content preserved, escalation note appended.
        self.assertIn("PRIOR NOTE", request.notes)
        self.assertIn("overdue by 10 days", request.notes)

    # ------------------------------------------------------------------
    # auto_close_resolved_requests
    # ------------------------------------------------------------------
    @patch("frappe.sendmail")
    def test_auto_close_closes_old_resolved_request(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            auto_close_resolved_requests,
        )

        request = self._make_contact_request(
            subject="Resolved old",
            status="Resolved",
            response_date=add_days(today(), -10),
        )

        auto_close_resolved_requests()

        request.reload()
        self.assertEqual(request.status, "Closed")
        self.assertEqual(str(request.closed_date), today())
        self.assertIn("AUTO-CLOSED", request.notes or "")

    @patch("frappe.sendmail")
    def test_auto_close_skips_within_grace_period(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            auto_close_resolved_requests,
        )

        # Resolved only 2 days ago: inside the 7-day grace period.
        request = self._make_contact_request(
            subject="Resolved recent",
            status="Resolved",
            response_date=add_days(today(), -2),
        )

        auto_close_resolved_requests()

        request.reload()
        self.assertEqual(request.status, "Resolved")

    # ------------------------------------------------------------------
    # sync_crm_status_updates
    # ------------------------------------------------------------------
    @patch("frappe.sendmail")
    def test_sync_crm_status_maps_resolved_to_converted(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            sync_crm_status_updates,
        )

        lead = self._make_lead(status="Open")
        request = self._make_contact_request(subject="Sync resolved", status="Resolved")
        self._link_lead(request, lead)

        sync_crm_status_updates()

        lead.reload()
        self.assertEqual(lead.status, "Converted")

    @patch("frappe.sendmail")
    def test_sync_crm_status_maps_closed_to_do_not_contact(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            sync_crm_status_updates,
        )

        lead = self._make_lead(status="Open")
        request = self._make_contact_request(subject="Sync closed", status="Closed")
        self._link_lead(request, lead)

        sync_crm_status_updates()

        lead.reload()
        self.assertEqual(lead.status, "Do Not Contact")

    @patch("frappe.sendmail")
    def test_sync_crm_status_no_change_when_already_aligned(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            sync_crm_status_updates,
        )

        # Lead already "Open"; request "Open" maps to "Open" -> no write needed.
        lead = self._make_lead(status="Open")
        request = self._make_contact_request(subject="Sync open", status="Open")
        self._link_lead(request, lead)
        modified_before = frappe.db.get_value("Lead", lead.name, "modified")

        sync_crm_status_updates()

        modified_after = frappe.db.get_value("Lead", lead.name, "modified")
        self.assertEqual(modified_before, modified_after)

    # ------------------------------------------------------------------
    # process_contact_request_automation (orchestrator)
    # ------------------------------------------------------------------
    @patch("frappe.sendmail")
    def test_process_automation_runs_all_steps(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            process_contact_request_automation,
        )

        # One request that should be auto-closed by the orchestrated run.
        request = self._make_contact_request(
            subject="Orchestrated close",
            status="Resolved",
            response_date=add_days(today(), -10),
        )

        process_contact_request_automation()

        request.reload()
        self.assertEqual(request.status, "Closed")

    # ------------------------------------------------------------------
    # create_opportunity_from_contact_request (whitelisted)
    # ------------------------------------------------------------------
    @patch("frappe.sendmail")
    def test_create_opportunity_success(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            create_opportunity_from_contact_request,
        )

        lead = self._make_lead()
        request = self._make_contact_request(subject="Opp source")
        self._link_lead(request, lead)

        result = create_opportunity_from_contact_request(request.name)

        self.assertTrue(result["success"])
        opportunity_name = result["opportunity"]
        self.track_doc("Opportunity", opportunity_name)

        # The opportunity is created from the linked lead and linked back.
        opportunity = frappe.get_doc("Opportunity", opportunity_name)
        self.assertEqual(opportunity.party_name, lead.name)
        self.assertEqual(opportunity.title, f"Follow-up: {request.subject}")

        request.reload()
        self.assertEqual(request.crm_opportunity, opportunity_name)

    def test_create_opportunity_without_lead_raises(self):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            create_opportunity_from_contact_request,
        )

        request = self._make_contact_request(subject="No lead")
        # No crm_lead linked.
        with self.assertRaises(frappe.ValidationError) as ctx:
            create_opportunity_from_contact_request(request.name)
        self.assertIn("No CRM Lead", str(ctx.exception))

    @patch("frappe.sendmail")
    def test_create_opportunity_twice_raises_already_exists(self, _sendmail):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            create_opportunity_from_contact_request,
        )

        lead = self._make_lead()
        request = self._make_contact_request(subject="Dup opp")
        self._link_lead(request, lead)

        first = create_opportunity_from_contact_request(request.name)
        self.track_doc("Opportunity", first["opportunity"])

        request.reload()
        with self.assertRaises(frappe.ValidationError) as ctx:
            create_opportunity_from_contact_request(request.name)
        self.assertIn("already exists", str(ctx.exception))

    # ------------------------------------------------------------------
    # get_contact_request_analytics (whitelisted)
    # ------------------------------------------------------------------
    def test_get_analytics_returns_expected_structure(self):
        from verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation import (
            get_contact_request_analytics,
        )

        # Seed a couple of requests with different statuses/types.
        self._make_contact_request(subject="Analytics A", status="Open", request_type="General Inquiry")
        self._make_contact_request(
            subject="Analytics B",
            status="Resolved",
            request_type="Complaint",
            response_date=today(),
        )

        analytics = get_contact_request_analytics()

        self.assertIn("status_distribution", analytics)
        self.assertIn("request_types", analytics)
        self.assertIn("avg_response_time_days", analytics)
        self.assertIn("monthly_volume", analytics)
        # status_distribution is a list of {status, count} rows.
        statuses = {row["status"] for row in analytics["status_distribution"]}
        self.assertIn("Open", statuses)
