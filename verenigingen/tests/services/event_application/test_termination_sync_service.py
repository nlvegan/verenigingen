"""Real-DB integration tests for MijnRoodTerminationSyncService.

The service routes terminated-status transitions to a Membership
Termination Request + TerminationExecutionService. Tests cover the
short-circuit paths (no status change, non-terminated transitions,
missing member, already-terminal member) and the happy-path execution.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.termination_sync_service import (
    get_termination_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCheckAndHandleTermination(EnhancedTestCase):
    """Routes terminated-status transitions to MTR + TerminationExecutionService."""

    ACTIVE_STATUS_ID = 9101
    TERMINATED_STATUS_ID = 9102

    def setUp(self):
        super().setUp()
        # Seed status mappings: one Active, one Terminated
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Termination Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": self.ACTIVE_STATUS_ID,
            "label": "Active (term test)",
            "membership_type_string": "test",
            "is_active": 1,
            "verenigingen_membership_type": membership_type.name,
        })
        settings.append("status_mapping", {
            "mijnrood_status_id": self.TERMINATED_STATUS_ID,
            "label": "Terminated (term test)",
            "membership_type_string": "test",
            "is_active": 0,  # Not active → terminated
            "verenigingen_membership_type": membership_type.name,
        })
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")
        self.addCleanup(self._cleanup_status_mapping)

    def _cleanup_status_mapping(self):
        s = frappe.get_single("MijnRood Sync Settings")
        s.status_mapping = self._original_status_mapping
        s.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")

    def _cleanup_member_and_customer(self, member_name):
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

    def _cleanup_termination_request(self, termination_name):
        try:
            if frappe.db.exists("Membership Termination Request", termination_name):
                frappe.delete_doc(
                    "Membership Termination Request",
                    termination_name,
                    ignore_permissions=True,
                    force=True,
                )
                frappe.db.commit()
        except Exception:
            pass

    def _make_event_mock(self, name="TEST-EVT-001", linked_member=None):
        event = MagicMock()
        event.name = name
        event.linked_member = linked_member
        return event

    def test_returns_none_when_no_status_change(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={},
            new_data={"id": "MR-NO-CHG"},
            changed_fields=[{"field": "first_name", "old": "A", "new": "B"}],
        )
        self.assertIsNone(result)

    def test_returns_none_when_new_status_not_terminated(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={"current_membership_status_id": self.ACTIVE_STATUS_ID},
            new_data={"id": "MR-STILL-ACTIVE", "current_membership_status_id": self.ACTIVE_STATUS_ID},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": self.ACTIVE_STATUS_ID,
                "new": self.ACTIVE_STATUS_ID,
            }],
        )
        self.assertIsNone(result)

    def test_returns_none_when_old_status_was_already_non_active(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={},
            new_data={"id": "MR-WAS-NON-ACTIVE"},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": 99999,  # Not in active list
                "new": self.TERMINATED_STATUS_ID,
            }],
        )
        self.assertIsNone(result)

    def test_returns_failure_when_no_linked_member_found(self):
        event = self._make_event_mock()
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={"email": "ghost-not-in-db@example.org"},
            new_data={"id": "MR-NO-MEMBER", "email": "ghost-not-in-db@example.org"},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": self.ACTIVE_STATUS_ID,
                "new": self.TERMINATED_STATUS_ID,
            }],
        )
        self.assertIsNotNone(result)
        self.assertFalse(result["success"])
        self.assertIn("no linked member", result["message"].lower())

    def test_skips_when_member_already_terminal(self):
        member = self.factory.create_member(
            first_name="Already",
            last_name="Quit",
            email="already-quit@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        frappe.db.set_value("Member", member.name, "status", "Quit", update_modified=False)
        frappe.db.commit()

        event = self._make_event_mock(linked_member=member.name)
        result = get_termination_sync_service()._check_and_handle_termination(
            event,
            old_data={},
            new_data={"id": "MR-ALREADY-QUIT"},
            changed_fields=[{
                "field": "current_membership_status_id",
                "old": self.ACTIVE_STATUS_ID,
                "new": self.TERMINATED_STATUS_ID,
            }],
        )
        self.assertTrue(result["success"])
        self.assertIn("already has status Quit", result["message"])

    def test_happy_path_creates_and_executes_termination(self):
        member = self.factory.create_member(
            first_name="Term",
            last_name="Test",
            email="term-test@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        frappe.db.set_value("Member", member.name, "status", "Active", update_modified=False)
        frappe.db.commit()

        event = self._make_event_mock(linked_member=member.name)

        # Mock justified: Infrastructure - TerminationExecutionService is
        # covered by its own tests; we verify the service is called with
        # the right MTR doc, not what it does internally.
        with patch(
            "verenigingen.services.termination.TerminationExecutionService"
        ) as mock_term_svc:
            mock_term_svc.return_value.execute = MagicMock()
            result = get_termination_sync_service()._check_and_handle_termination(
                event,
                old_data={},
                new_data={"id": "MR-TERM-HAPPY"},
                changed_fields=[{
                    "field": "current_membership_status_id",
                    "old": self.ACTIVE_STATUS_ID,
                    "new": self.TERMINATED_STATUS_ID,
                }],
            )

        self.assertTrue(result["success"])
        # An MTR was created — find it via the member link
        mtrs = frappe.get_all(
            "Membership Termination Request",
            filters={"member": member.name},
            pluck="name",
        )
        self.assertEqual(len(mtrs), 1)
        self.addCleanup(self._cleanup_termination_request, mtrs[0])

        # Service was called with the MTR doc
        mock_term_svc.return_value.execute.assert_called_once()

        # Verify the MTR fields are set correctly
        mtr = frappe.get_doc("Membership Termination Request", mtrs[0])
        self.assertEqual(mtr.member, member.name)
        self.assertEqual(mtr.status, "Approved")
