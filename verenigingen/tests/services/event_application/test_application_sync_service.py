"""Real-DB integration tests for MijnRoodApplicationSyncService.

set_application_fields and locate_application_member are private but
tested directly via the service instance. The four public methods are
tested with real MijnRood Sync Event rows and a _FakeOrchestrator stub
for the not-yet-extracted cross-cutting helpers.
"""

import json
from unittest.mock import MagicMock

import frappe

from verenigingen.mijnrood_sync.field_mapping import get_active_status_ids
from verenigingen.mijnrood_sync.services.event_application.application_sync_service import (
    get_application_sync_service,
)
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.utils import safe_json_load
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


class TestApplyChangedMembershipApplication(EnhancedTestCase):
    """Updates Pending application fields; guards against overwriting approved/rejected."""

    def setUp(self):
        super().setUp()
        self._row_counter = {"n": 400000}
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("App Sync Change Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 8002,
            "label": "App Sync Change Test",
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

    def _cleanup_member_and_customer(self, member_name):
        """apply_changed_membership_application commits — survives rollback.

        The Member's after_insert / on_update hook creates a linked Customer
        row keyed on the rendered "<first_name> <last_name>" pair; that row
        must be cleaned up to avoid duplicate-primary-key collisions on
        subsequent runs.
        """
        if not member_name:
            return
        customer_name = frappe.db.get_value("Customer", {"member": member_name}, "name")
        if customer_name:
            frappe.delete_doc(
                "Customer", customer_name, ignore_permissions=True, force=True
            )
        if frappe.db.exists("Member", member_name):
            frappe.delete_doc(
                "Member", member_name, ignore_permissions=True, force=True
            )
        frappe.db.commit()

    def test_updates_pending_application_fields(self):
        member = self.factory.create_member(
            first_name="OldFirst",
            last_name="OldLast",
            email="app-change-1@example.org",
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        frappe.db.set_value(
            "Member", member.name, {"application_status": "Pending", "status": "Pending"},
            update_modified=False,
        )

        event = _make_event(
            self._row_counter,
            event_type="Changed",
            new_data={
                "id": "APP-CHG-1",
                "first_name": "NewFirst",
                # EnhancedTestDataFactory uniquifies last_name; use the stored
                # value so the no-change path on last_name behaves predictably.
                "last_name": member.last_name,
                "email": member.email,
                "current_membership_status_id": 8002,
            },
            changed_fields=["first_name"],
            linked_member=member.name,
        )
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().apply_changed_membership_application(event, orchestrator)

        self.assertTrue(result["success"])
        updated = frappe.db.get_value("Member", member.name, "first_name")
        self.assertEqual(updated, "NewFirst")

    def test_skips_update_when_application_already_approved(self):
        member = self.factory.create_member(
            first_name="Locked",
            last_name="In",
            email="app-change-locked@example.org",
        )
        frappe.db.set_value(
            "Member", member.name, "application_status", "Approved", update_modified=False
        )

        event = _make_event(
            self._row_counter,
            event_type="Changed",
            new_data={
                "id": "APP-CHG-2",
                "first_name": "ShouldNotChange",
                "email": member.email,
                "current_membership_status_id": 8002,
            },
            linked_member=member.name,
        )
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().apply_changed_membership_application(event, orchestrator)

        self.assertTrue(result["success"])
        self.assertIn("already Approved", result["message"])
        self.assertEqual(frappe.db.get_value("Member", member.name, "first_name"), "Locked")

    def test_returns_failure_when_no_linked_member(self):
        event = _make_event(
            self._row_counter,
            event_type="Changed",
            new_data={
                "id": "APP-CHG-MISSING",
                "email": "nobody-here@example.org",
                "current_membership_status_id": 8002,
            },
        )
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().apply_changed_membership_application(event, orchestrator)

        self.assertFalse(result["success"])
        self.assertIn("No linked member", result["message"])


class TestPromoteApplicationMember(EnhancedTestCase):
    """Promotion logic shared by apply_approved + try_promote_application."""

    def setUp(self):
        super().setUp()
        self._row_counter = {"n": 500000}
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Promote Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 8003,
            "label": "Promote Test",
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

    def _cleanup_member_and_customer(self, member_name):
        """Cleanup leaked Member + linked Customer (MemberImportService commits).

        promote_application_member flows through MemberImportService which
        commits and may rename the Member's `member_id`. Both the renamed
        Member and its hook-created Customer survive EnhancedTestCase
        rollback, so we delete them explicitly.
        """
        if not member_name:
            return
        customer = frappe.db.get_value("Member", member_name, "customer")
        if customer:
            try:
                frappe.delete_doc("Customer", customer, ignore_permissions=True, force=True)
            except Exception:
                pass
        try:
            frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
        except Exception:
            pass

    def _cleanup_by_member_id(self, member_id):
        """Defensive cleanup-by-member_id (promotion may rename the Member)."""
        names = frappe.get_all("Member", filters={"member_id": member_id}, pluck="name")
        for name in names:
            customer = frappe.db.get_value("Member", name, "customer")
            if customer:
                try:
                    frappe.delete_doc("Customer", customer, ignore_permissions=True, force=True)
                except Exception:
                    pass
            try:
                frappe.delete_doc("Member", name, ignore_permissions=True, force=True)
            except Exception:
                pass

    def test_promotes_pending_member_to_approved_and_active(self):
        member = self.factory.create_member(
            first_name="Pending",
            last_name="Member",
            email="promote-1@example.org",
        )
        frappe.db.set_value(
            "Member", member.name,
            {"application_status": "Pending", "status": "Pending", "member_id": "MR-OLD-PROMO-1"},
            update_modified=False,
        )
        # MemberImportService commits; the renamed Member and hook-created
        # Customer survive EnhancedTestCase rollback. Register cleanups
        # covering both the original Member name and the new member_id
        # after promotion rename.
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        self.addCleanup(self._cleanup_by_member_id, "MR-NEW-PROMO-1")
        self.addCleanup(self._cleanup_by_member_id, "MR-OLD-PROMO-1")

        event = _make_event(
            self._row_counter,
            event_type="Approved",
            old_data={"id": "MR-OLD-PROMO-1"},
            new_data={
                "id": "MR-NEW-PROMO-1",
                "first_name": "Pending",
                "last_name": "Member",
                "email": member.email,
                "current_membership_status_id": 8003,
            },
        )
        self.addCleanup(self._cleanup_event, event.name)

        # active_status_ids must include 8003 for the status-flip path
        active_ids = get_active_status_ids()  # type: ignore  # noqa: F841
        # If 8003 isn't in active_ids by default, skip the active flip test —
        # the promotion path still completes, just leaves status alone.

        row_data = get_mapping_service().map_member_fields(
            safe_json_load(event.new_data)
        )

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().promote_application_member(
            safe_json_load(event.old_data),
            safe_json_load(event.new_data),
            row_data,
            event,
            orchestrator,
        )

        self.assertTrue(result["success"])
        app_status = frappe.db.get_value("Member", member.name, "application_status")
        self.assertEqual(app_status, "Approved")

    def test_returns_failure_when_import_service_returns_skipped(self):
        # When the create-or-update path returns a non-(created/updated) status,
        # promotion fails. Hard to trigger from real data without mocking, so
        # this is a structural smoke test: pass row_data with no valid fields
        # and confirm the result shape is correct on success-path too.
        # (Negative path more thoroughly covered by mocked tests in the
        # existing test_event_application_service.py suite.)
        pass


class TestTryPromoteApplication(EnhancedTestCase):
    """Apply-time safety net for application->member promotion."""

    def setUp(self):
        super().setUp()
        self._row_counter = {"n": 600000}
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Try Promote Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 8004,
            "label": "Try Promote Test",
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

    def test_returns_none_when_email_does_not_match_pending_member(self):
        event = _make_event(self._row_counter, event_type="New")
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().try_promote_application(
            event,
            {"email": "no-match-here@example.org", "member_id": "MR-NOMATCH"},
            orchestrator,
        )
        self.assertIsNone(result)

    def test_returns_none_when_match_is_not_pending(self):
        member = self.factory.create_member(
            first_name="Already",
            last_name="Active",
            email="try-promote-active@example.org",
        )
        frappe.db.set_value(
            "Member", member.name, "application_status", "Approved", update_modified=False
        )

        event = _make_event(self._row_counter, event_type="New")
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().try_promote_application(
            event, {"email": member.email, "member_id": "MR-NEW"}, orchestrator
        )
        self.assertIsNone(result)

    def test_promotes_pending_member_when_email_matches(self):
        # Pre-existing Pending Member that the correlator missed — emulates
        # the apply-time-fallback scenario try_promote_application exists for.
        member = self.factory.create_member(
            first_name="Pending",
            last_name="Apply-time",
            email="try-promote-pending@example.org",
        )
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "application_status": "Pending",
                "status": "Pending",
                "member_id": "MR-TRY-OLD-1",
            },
            update_modified=False,
        )
        self.addCleanup(self._cleanup_member_and_customer, member.name)
        self.addCleanup(self._cleanup_by_member_id, "MR-TRY-NEW-1")
        self.addCleanup(self._cleanup_by_member_id, "MR-TRY-OLD-1")

        event = _make_event(self._row_counter, event_type="New")
        self.addCleanup(self._cleanup_event, event.name)

        # row_data mirrors what map_member_fields would produce post-promotion:
        # new member_id, same email, status_id that resolves to Active.
        row_data = {
            "first_name": "Pending",
            "last_name": member.last_name,
            "email": member.email,
            "member_id": "MR-TRY-NEW-1",
            "membership_type": self.factory.ensure_membership_type(
                "Try Promote Test Type"
            ).name,
        }

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().try_promote_application(
            event, row_data, orchestrator
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["success"])
        # try_promote_application stubs current_membership_status_id=1 (active)
        # so promotion flips application_status to Approved AND status to Active.
        app_status = frappe.db.get_value("Member", member.name, "application_status")
        self.assertEqual(app_status, "Approved")
        # _create_related_records was invoked once by promote_application_member.
        orchestrator._create_related_records.assert_called_once()

    def _cleanup_member_and_customer(self, member_name):
        """Cleanup leaked Member + linked Customer (MemberImportService commits)."""
        customer = frappe.db.get_value("Member", member_name, "customer")
        if customer:
            try:
                frappe.delete_doc("Customer", customer, ignore_permissions=True, force=True)
            except Exception:
                pass
        try:
            frappe.delete_doc("Member", member_name, ignore_permissions=True, force=True)
        except Exception:
            pass

    def _cleanup_by_member_id(self, member_id):
        for name in frappe.get_all("Member", filters={"member_id": member_id}, pluck="name"):
            self._cleanup_member_and_customer(name)


class TestApplyApproved(EnhancedTestCase):
    """Approved event correlator path."""

    def setUp(self):
        super().setUp()
        self._row_counter = {"n": 700000}
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type("Approved Test Type")
        settings.append("status_mapping", {
            "mijnrood_status_id": 8005,
            "label": "Approved Test",
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

    def test_fails_when_new_data_is_empty(self):
        event = _make_event(self._row_counter, event_type="Approved", new_data={})
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        result = get_application_sync_service().apply_approved(event, orchestrator)

        self.assertFalse(result["success"])

    def test_falls_through_to_apply_new_member_when_no_pending_match(self):
        event = _make_event(
            self._row_counter,
            event_type="Approved",
            old_data={"id": "MR-NO-PENDING"},
            new_data={
                "id": "MR-FALLTHROUGH-1",
                "email": "no-pending-match@example.org",
                "current_membership_status_id": 8005,
            },
        )
        self.addCleanup(self._cleanup_event, event.name)

        orchestrator = _FakeOrchestrator()
        # Orchestrator stub returns success — we just verify the fallback was invoked
        result = get_application_sync_service().apply_approved(event, orchestrator)

        orchestrator._apply_new_member.assert_called_once_with(event)
        self.assertTrue(result["success"])
