# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Real-DB coverage tests for verenigingen/.../member/mixins/termination_mixin.py

TerminationMixin is mixed into the Member controller. These tests build REAL
Member and Membership Termination Request documents (no business-logic mocking)
and assert the observable behaviour of:

- get_termination_readiness_check(): impact preview + pending-request blocker
- terminate_membership(): the termination-type -> member-status mapping and the
  appended termination note, persisted via secure_document_operation
- update_termination_status_display(): badge color selection for the
  active/suspended cases that exist on the real Member schema

Runs as Administrator (has Member:write) so the secure save path succeeds.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTerminationMixinCoverage(EnhancedTestCase):
    def _make_member(self, **overrides):
        member = self.create_test_member(
            first_name="Term",
            last_name="Mixin",
            email=overrides.pop("email", frappe.generate_hash("term", 6) + "@example.invalid"),
        )
        return member

    # --------------------------------------------------- readiness check
    def test_readiness_check_clean_member_can_terminate(self):
        member = self._make_member()
        readiness = member.get_termination_readiness_check()
        self.assertTrue(readiness["can_terminate"])
        self.assertIn("impact", readiness)
        self.assertEqual(readiness["blockers"], [])

    def test_readiness_check_blocked_by_pending_request(self):
        member = self._make_member()
        # A pending termination request must block a new termination.
        req = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "status": "Draft",
                "termination_reason": "test pending",
                "requested_by": frappe.session.user,
                "request_date": frappe.utils.today(),
            }
        )
        req.insert()
        self.track_doc("Membership Termination Request", req.name)

        readiness = member.get_termination_readiness_check()
        self.assertFalse(readiness["can_terminate"])
        self.assertTrue(any("pending termination" in b.lower() for b in readiness["blockers"]))

    # --------------------------------------------------- terminate_membership
    def test_terminate_voluntary_maps_to_expired(self):
        member = self._make_member()
        member.terminate_membership("Voluntary", frappe.utils.today())
        member.reload()
        self.assertEqual(member.status, "Expired")
        self.assertIn("Membership terminated", member.notes or "")

    def test_terminate_deceased_maps_to_deceased(self):
        member = self._make_member()
        member.terminate_membership("Deceased", frappe.utils.today())
        member.reload()
        self.assertEqual(member.status, "Deceased")

    def test_terminate_expulsion_maps_to_banned(self):
        member = self._make_member()
        member.terminate_membership("Expulsion", frappe.utils.today())
        member.reload()
        self.assertEqual(member.status, "Banned")

    def test_terminate_unknown_type_defaults_to_suspended(self):
        member = self._make_member()
        member.terminate_membership("Some Unmapped Type", frappe.utils.today())
        member.reload()
        self.assertEqual(member.status, "Suspended")

    def test_terminate_note_includes_request_reference(self):
        member = self._make_member()
        member.terminate_membership("Voluntary", frappe.utils.today(), termination_request="MTR-XYZ")
        member.reload()
        self.assertIn("MTR-XYZ", member.notes or "")

    def test_terminate_appends_to_existing_notes(self):
        member = self._make_member()
        member.notes = "Pre-existing note."
        member.save()
        member.terminate_membership("Voluntary", frappe.utils.today())
        member.reload()
        self.assertIn("Pre-existing note.", member.notes)
        self.assertIn("Membership terminated", member.notes)

    # ------------------------------------------ update_termination_status_display
    def test_status_display_no_termination_is_crash_safe_noop(self):
        member = self._make_member()
        # termination_status is NOT a Member schema field, so the controller's
        # `if hasattr(self, "termination_status")` branches never fire — the
        # "Active"-reset display logic is vestigial/dead. Pin that reality: the
        # call is a crash-safe no-op and does not invent the attribute. (If the
        # field is ever re-added this assertion flips and forces a revisit.)
        member.update_termination_status_display()
        self.assertFalse(hasattr(member, "termination_status"))

    def test_status_display_badge_color_is_vestigial(self):
        member = self._make_member()
        member.status = "Suspended"
        # membership_badge_color is likewise not a Member field, so the entire
        # badge-colour block is dead code; the method must not fabricate it.
        member.update_termination_status_display()
        self.assertFalse(hasattr(member, "membership_badge_color"))
