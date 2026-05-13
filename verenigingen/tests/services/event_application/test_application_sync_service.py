"""Real-DB integration tests for MijnRoodApplicationSyncService.

set_application_fields and locate_application_member are private but
tested directly via the service instance. The four public methods are
tested with real MijnRood Sync Event rows and a _FakeOrchestrator stub
for the not-yet-extracted cross-cutting helpers.
"""

import json
from unittest.mock import MagicMock

import frappe

from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _FakeOrchestrator:
    """Stand-in for MijnRoodEventApplicationService.

    Records calls to cross-cutting helpers that have not yet been
    extracted (PR #6 for related records, unassigned chapter helpers).
    """

    def __init__(self):
        self._create_related_records = MagicMock(return_value=[])
        self._assign_chapter_from_division = MagicMock(return_value=None)
        self._handle_division_field_change = MagicMock(return_value=None)
        self._apply_new_member = MagicMock(
            return_value={"success": True, "message": "fallback from stub"}
        )
        self._find_existing_member_or_conflict = MagicMock(return_value=(None, None))


def _make_event(
    counter: dict,
    *,
    table: str = "admin_membership_application",
    event_type: str = "New",
    new_data: dict | None = None,
    old_data: dict | None = None,
    changed_fields: list | None = None,
    linked_member: str | None = None,
) -> "frappe.Document":
    """Insert a MijnRood Sync Event doc. `counter` is a mutable dict
    {"n": int} owned by the calling test class for row-id uniqueness.
    """
    counter["n"] = counter.get("n", 200000) + 1
    return frappe.get_doc({
        "doctype": "MijnRood Sync Event",
        "mijnrood_table": table,
        "event_type": event_type,
        "mijnrood_row_id": counter["n"],
        "status": "Approved",
        "new_data": json.dumps(new_data or {}),
        "old_data": json.dumps(old_data or {}),
        "changed_fields": json.dumps(changed_fields or []),
        "linked_member": linked_member,
    }).insert(ignore_permissions=True)


class TestSetApplicationFields(EnhancedTestCase):
    """Pure-logic field-by-field update of a Member doc."""

    def test_applies_mapped_fields_to_member(self):
        member = self.factory.create_member(
            first_name="OldFirst",
            last_name="OldLast",
            email="set-fields-1@example.org",
        )

        service = get_application_sync_service()
        changed = service._set_application_fields(
            member,
            row_data={"first_name": "NewFirst", "last_name": "NewLast"},
            is_new=False,
        )

        self.assertTrue(changed)
        self.assertEqual(member.first_name, "NewFirst")
        self.assertEqual(member.last_name, "NewLast")

    def test_returns_false_when_no_field_changes(self):
        member = self.factory.create_member(
            first_name="Same",
            last_name="Person",
            email="set-fields-2@example.org",
        )

        service = get_application_sync_service()
        # EnhancedTestDataFactory uniquifies last_name (e.g. "Person123"),
        # so use the stored value to confirm the no-change path.
        changed = service._set_application_fields(
            member,
            row_data={"first_name": "Same", "last_name": member.last_name},
            is_new=False,
        )

        self.assertFalse(changed)

    def test_is_new_infers_bank_transfer_when_iban_present(self):
        member = self.factory.create_member(
            first_name="Iban",
            last_name="Test",
            email="set-fields-3@example.org",
        )
        member.iban = "NL91ABNA0417164300"
        member.payment_method = None

        service = get_application_sync_service()
        service._set_application_fields(
            member, row_data={"first_name": "Iban"}, is_new=True
        )

        self.assertEqual(member.payment_method, "Bank Transfer")

    def test_mollie_customer_id_overrides_payment_method(self):
        member = self.factory.create_member(
            first_name="Mollie",
            last_name="Test",
            email="set-fields-4@example.org",
        )
        member.mollie_customer_id = None
        member.payment_method = "Bank Transfer"

        service = get_application_sync_service()
        changed = service._set_application_fields(
            member,
            row_data={"custom_mollie_customer_id": "cst_test123"},
            is_new=False,
        )

        self.assertTrue(changed)
        self.assertEqual(member.mollie_customer_id, "cst_test123")
        self.assertEqual(member.payment_method, "Mollie")

    def test_skips_empty_string_and_none_values(self):
        member = self.factory.create_member(
            first_name="Keep",
            last_name="Original",
            email="set-fields-5@example.org",
        )
        # EnhancedTestDataFactory uniquifies last_name (e.g. "Original123");
        # capture the stored values so we can assert they were not overwritten.
        original_first_name = member.first_name
        original_last_name = member.last_name

        service = get_application_sync_service()
        service._set_application_fields(
            member,
            row_data={"first_name": "", "last_name": None, "iban": "NL91ABNA0417164300"},
            is_new=False,
        )

        self.assertEqual(member.first_name, original_first_name)
        self.assertEqual(member.last_name, original_last_name)
        self.assertEqual(member.iban, "NL91ABNA0417164300")


class TestLocateApplicationMember(EnhancedTestCase):
    """Linked-member → application_id → email lookup order."""

    def test_returns_linked_member_when_set(self):
        result = get_application_sync_service()._locate_application_member(
            old_data={"id": 999},
            new_data={"email": "any@example.org"},
            linked_member="Member-Already-Linked",
        )
        self.assertEqual(result, "Member-Already-Linked")

    def test_falls_back_to_application_id_lookup(self):
        member = self.factory.create_member(
            first_name="App",
            last_name="IdMatch",
            email="app-id-match@example.org",
        )
        frappe.db.set_value(
            "Member", member.name, "application_id", "MR-APP-555", update_modified=False
        )

        result = get_application_sync_service()._locate_application_member(
            old_data={"id": 555},
            new_data={"email": "different@example.org"},
            linked_member=None,
        )
        self.assertEqual(result, member.name)

    def test_falls_back_to_email_lookup(self):
        member = self.factory.create_member(
            first_name="Email",
            last_name="Fallback",
            email="email-fallback@example.org",
        )

        result = get_application_sync_service()._locate_application_member(
            old_data={"id": 6666},  # no matching application_id
            new_data={"email": member.email},
            linked_member=None,
        )
        self.assertEqual(result, member.name)

    def test_returns_none_when_nothing_matches(self):
        result = get_application_sync_service()._locate_application_member(
            old_data={"id": 7777},
            new_data={"email": "nobody@nowhere.example"},
            linked_member=None,
        )
        self.assertIsNone(result)


class TestApplyNewMembershipApplication(EnhancedTestCase):
    """Creates a Pending Member from a MijnRood admin_membership_application row."""

    def setUp(self):
        super().setUp()
        self._row_counter = {"n": 300000}
        # Status mapping setup so map_member_fields doesn't raise
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("App Sync Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 8001,
            "label": "App Sync Test",
            "membership_type_string": "test",
            "is_active": 1,
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

    def _cleanup_event(self, event_name):
        frappe.delete_doc("MijnRood Sync Event", event_name, ignore_permissions=True, force=True)

    def _cleanup_member_by_application_id(self, application_id):
        rows = frappe.get_all("Member", filters={"application_id": application_id}, pluck="name")
        for name in rows:
            frappe.delete_doc("Member", name, ignore_permissions=True, force=True)

    def test_creates_pending_member_from_application_event(self):
        event = _make_event(
            self._row_counter,
            new_data={
                "id": "APP-NEW-1",
                "first_name": "Application",
                "last_name": "Pending",
                "email": "application-pending-1@example.org",
                "current_membership_status_id": 8001,
            },
        )
        self.addCleanup(self._cleanup_event, event.name)
        self.addCleanup(self._cleanup_member_by_application_id, "MR-APP-APP-NEW-1")

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().apply_new_membership_application(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertTrue(event.linked_member)
        member = frappe.get_doc("Member", event.linked_member)
        self.assertEqual(member.application_status, "Pending")
        self.assertEqual(member.status, "Pending")
        self.assertEqual(member.application_id, "MR-APP-APP-NEW-1")

    def test_idempotent_when_member_already_exists(self):
        # Pre-existing application with same email
        existing = self.factory.create_member(
            first_name="Already",
            last_name="Pending",
            email="already-pending@example.org",
            member_id="MR-EXIST-APP-1",
        )

        event = _make_event(
            self._row_counter,
            new_data={
                "id": "APP-DUP-1",
                "first_name": "Already",
                "last_name": "Pending",
                "email": existing.email,
                "current_membership_status_id": 8001,
            },
        )
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        # Simulate the not-yet-extracted conflict detector finding the existing
        # member by email. The default stub returns (None, None) which would
        # cause a new Member to be created — override here to exercise the
        # idempotent path.
        orchestrator._find_existing_member_or_conflict = MagicMock(
            return_value=(existing.name, {
                "success": True,
                "message": f"Member {existing.name} already exists (email={existing.email})",
            }),
        )
        result = get_application_sync_service().apply_new_membership_application(event, orchestrator)

        self.assertTrue(result["success"])
        # No new Member created for the duplicate application
        new_count = frappe.db.count("Member", {"application_id": "MR-APP-APP-DUP-1"})
        self.assertEqual(new_count, 0)

    def test_returns_failure_when_new_data_is_empty(self):
        event = _make_event(self._row_counter, new_data={})
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().apply_new_membership_application(event, orchestrator)

        self.assertFalse(result["success"])
        self.assertIn("No new data", result["message"])
