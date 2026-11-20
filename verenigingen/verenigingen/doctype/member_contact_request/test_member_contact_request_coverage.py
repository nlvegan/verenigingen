# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Real-DB coverage tests for the Member Contact Request *controller*
(member_contact_request.py).

The sibling test_contact_request_automation.py covers the scheduled-automation
module; this file covers the document controller itself:

- validate(): field defaulting, member-existence + active-status gate,
  member-detail auto-population, contact-preference enforcement
- after_insert(): notify_staff (see tests/test_contact_request_staff_mail_2174.py)
- on_update(): status-change side effects (response/closed dates, CRM lead
  status sync) and assignment-change follow-up dates
- get_notification_recipients(): role-based recipient resolution
- _create_member_contact_request / get_member_contact_requests endpoints

All Member / Lead / Member Contact Request docs are real and persisted; we
assert real field state, raised exceptions and linked-record creation.
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberContactRequestController(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._make_active_member()

    def _make_active_member(self, **overrides):
        member = self.create_test_member(
            first_name="Contact",
            last_name="Controller",
            email=overrides.pop("email", "contact.controller.mcr@example.invalid"),
            contact_number="+31611111111",
        )
        # membership_status is read-only/computed; force Active so the controller
        # validation (active-member gate) passes for inserts.
        frappe.db.set_value("Member", member.name, "membership_status", "Active")
        member.reload()
        return member

    def _make_request(self, **overrides):
        data = {
            "doctype": "Member Contact Request",
            "member": self.member.name,
            "subject": "Need help",
            "message": "Please contact me about my membership.",
            "preferred_contact_method": "Email",
            "urgency": "Normal",
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        doc.insert()
        self.track_doc("Member Contact Request", doc.name)
        return doc

    # --------------------------------------------------------------- defaults
    def test_field_defaults_applied_on_insert(self):
        """v16 doesn't apply JSON defaults on programmatic insert; controller does."""
        # Bracket the insert with the controller's own date source so a midnight
        # rollover between the stamp and the assertion can't fail this spuriously.
        before = getdate(today())
        doc = self._make_request(request_type=None, status=None, request_date=None)
        after = getdate(today())
        self.assertEqual(doc.request_type, "General Inquiry")
        self.assertEqual(doc.preferred_contact_method, "Email")
        self.assertEqual(doc.status, "Open")
        self.assertIn(getdate(doc.request_date), (before, after))

    # --------------------------------------------------------- member gate
    def test_rejects_missing_member(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Member Contact Request",
                    "subject": "x",
                    "message": "y",
                    "preferred_contact_method": "Email",
                    "email": "x@example.invalid",
                }
            ).insert()

    def test_rejects_inactive_member(self):
        inactive = self.create_test_member(
            first_name="In", last_name="Active", email="inactive.mcr@example.invalid"
        )
        frappe.db.set_value("Member", inactive.name, "membership_status", "Suspended")
        with self.assertRaises(frappe.ValidationError) as ctx:
            frappe.get_doc(
                {
                    "doctype": "Member Contact Request",
                    "member": inactive.name,
                    "subject": "x",
                    "message": "y",
                    "preferred_contact_method": "Email",
                }
            ).insert()
        self.assertIn("active members", str(ctx.exception))

    # ---------------------------------------------------- detail population
    def test_member_details_autopopulated(self):
        doc = self._make_request()
        # set_member_details copies full_name/email/phone from the Member.
        self.assertTrue(doc.member_name)
        self.assertEqual(doc.email, self.member.email)

    # ------------------------------------------------ contact preferences
    def test_phone_required_when_phone_preferred(self):
        # A member with no phone, preferred method Phone -> validation throws.
        nophone = self.create_test_member(
            first_name="No", last_name="Phone", email="nophone.mcr@example.invalid"
        )
        frappe.db.set_value("Member", nophone.name, "membership_status", "Active")
        frappe.db.set_value("Member", nophone.name, "contact_number", "")
        with self.assertRaises(frappe.ValidationError) as ctx:
            frappe.get_doc(
                {
                    "doctype": "Member Contact Request",
                    "member": nophone.name,
                    "subject": "x",
                    "message": "y",
                    "preferred_contact_method": "Phone",
                }
            ).insert()
        self.assertIn("Phone number is required", str(ctx.exception))

    # ------------------------------------------------------------- no CRM Lead
    def test_insert_does_not_create_a_crm_lead(self):
        # Maintainer ruling on #2174: the never-live Lead creation was dropped.
        doc = self._make_request(subject="Lead please")
        doc.reload()
        self.assertFalse(doc.crm_lead)

    # ------------------------------------------- get_notification_recipients
    def test_get_notification_recipients_returns_admin_emails(self):
        doc = self._make_request()
        recipients = doc.get_notification_recipients()
        self.assertIsInstance(recipients, list)
        for r in recipients:
            self.assertIn("@", r)

    def test_urgent_request_also_includes_system_managers(self):
        normal_doc = self._make_request(urgency="Normal")
        urgent_doc = self._make_request(urgency="Urgent")
        normal_recipients = set(normal_doc.get_notification_recipients())
        urgent_recipients = set(urgent_doc.get_notification_recipients())
        # Urgent escalates to System Managers too -> superset of normal recipients.
        self.assertTrue(urgent_recipients >= normal_recipients)

    # ----------------------------------------------------- status changes
    def test_status_in_progress_sets_response_date(self):
        # handle_status_change runs inside on_update (post-write) and mutates the
        # in-memory doc; assert the in-memory value (not a reload, which would not
        # see the post-write mutation).
        doc = self._make_request()
        doc.status = "In Progress"
        before = getdate(today())
        doc.save()
        after = getdate(today())
        self.assertIn(getdate(doc.response_date), (before, after))

    def test_status_closed_sets_closed_date(self):
        doc = self._make_request()
        doc.status = "Closed"
        before = getdate(today())
        doc.save()
        after = getdate(today())
        self.assertIn(getdate(doc.closed_date), (before, after))

    def test_resolved_status_syncs_linked_lead_to_converted(self):
        """A Lead linked by hand (no insert creates one any more, #2174) still follows the request status."""
        if not frappe.db.exists("DocType", "Lead"):
            self.skipTest("CRM Lead doctype not installed")
        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Linked Lead",
                "email_id": "linked.lead.mcr@example.invalid",
                "status": "Open",
                "title": "Linked Lead",
            }
        )
        lead.insert()
        self.track_doc("Lead", lead.name)
        doc = self._make_request()
        doc.db_set("crm_lead", lead.name, update_modified=False)
        doc.reload()
        doc.status = "Resolved"
        doc.save()
        self.assertEqual(frappe.db.get_value("Lead", lead.name, "status"), "Converted")

    # --------------------------------------------------- assignment changes
    def test_assignment_sets_follow_up_date(self):
        doc = self._make_request()
        doc.assigned_to = "Administrator"
        doc.save()
        # handle_assignment_change sets a follow-up date 2 days out when unset.
        # It runs in on_update (post-write), so assert the in-memory value.
        self.assertTrue(doc.follow_up_date)

    # ------------------------------------------ _create_member_contact_request
    def test_internal_create_helper_inserts_request(self):
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            _create_member_contact_request,
        )

        result = _create_member_contact_request(
            member=self.member.name,
            subject="Helper subject",
            message="Helper body",
        )
        self.assertTrue(result["success"])
        self.assertTrue(frappe.db.exists("Member Contact Request", result["contact_request"]))
        self.track_doc("Member Contact Request", result["contact_request"])
        created = frappe.get_doc("Member Contact Request", result["contact_request"])
        # created_by_portal flag is set by the internal helper path.
        self.assertEqual(created.created_by_portal, 1)

    # ---------------------------------------------- get_member_contact_requests
    def test_get_member_contact_requests_lists_for_member(self):
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            get_member_contact_requests,
        )

        self._make_request(subject="First")
        self._make_request(subject="Second")
        rows = get_member_contact_requests(member=self.member.name, limit=10)
        subjects = {r["subject"] for r in rows}
        self.assertIn("First", subjects)
        self.assertIn("Second", subjects)

    def test_get_member_contact_requests_rejects_unknown_member(self):
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            get_member_contact_requests,
        )

        with self.assertRaises(frappe.ValidationError):
            get_member_contact_requests(member="NO-SUCH-MEMBER-XYZ", limit=5)
