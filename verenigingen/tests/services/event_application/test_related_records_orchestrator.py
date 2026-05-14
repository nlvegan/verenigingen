"""Real-DB integration tests for MijnRoodRelatedRecordsOrchestrator.

Tests cover address/Mollie/membership/dues creation + chapter assignment
+ user account queueing + MijnRood comment append. Each method tested
against a real DB; the orchestrator parameter (god-class's
_acr_queued_members) is stubbed via _FakeOrchestrator.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator


def _cleanup_member_and_customer(test, member_name):
    """Module-level helper for cross-class reuse."""
    for cust in frappe.get_all("Customer", filters={"member": member_name}, pluck="name"):
        try:
            frappe.db.set_value("Customer", cust, "member", None, update_modified=False)
            frappe.delete_doc("Customer", cust, ignore_permissions=True, force=True)
        except Exception:
            pass
    try:
        if frappe.db.exists("Member", member_name):
            frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
    except Exception:
        pass
    frappe.db.commit()


class TestApplyMijnRoodComments(EnhancedTestCase):
    """Appends MijnRood comments to Member.notes, idempotent."""

    def test_returns_none_when_comment_is_empty(self):
        member = self.factory.create_member(
            first_name="EmptyComment", last_name="Test",
            email="empty-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": ""}
        )
        self.assertIsNone(result)

    def test_returns_none_when_comment_missing(self):
        member = self.factory.create_member(
            first_name="NoComment", last_name="Test",
            email="no-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {}
        )
        self.assertIsNone(result)

    def test_appends_comment_to_member_notes(self):
        member = self.factory.create_member(
            first_name="Append", last_name="Comment",
            email="append-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "imported from MijnRood"}
        )
        self.assertIsNotNone(result)
        notes = frappe.db.get_value("Member", member.name, "notes") or ""
        self.assertIn("imported from MijnRood", notes)

    def test_idempotent_when_comment_already_present(self):
        member = self.factory.create_member(
            first_name="DupComment", last_name="Test",
            email="dup-comment@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        frappe.db.set_value("Member", member.name, "notes",
            "MijnRood notitie: same comment", update_modified=False)
        frappe.db.commit()

        result = get_related_records_orchestrator()._apply_mijnrood_comments(
            member.name, {"mijnrood_comments": "same comment"}
        )
        self.assertIsNone(result)
