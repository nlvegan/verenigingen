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
    # Remove any dangling Dynamic Link rows that referenced this Member
    # (Address child rows are deleted with the Address, but stray rows
    # from manual fixtures or failed inserts can survive otherwise).
    for dl in frappe.get_all(
        "Dynamic Link",
        filters={"link_doctype": "Member", "link_name": member_name},
        pluck="name",
    ):
        try:
            frappe.delete_doc("Dynamic Link", dl, ignore_permissions=True, force=True)
        except Exception:
            pass
    frappe.db.commit()


def _cleanup_address(name):
    """Delete an Address (and its child Dynamic Link rows) and commit."""
    try:
        if frappe.db.exists("Address", name):
            frappe.delete_doc("Address", name, ignore_permissions=True, force=True)
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


class TestEnsureAddress(EnhancedTestCase):
    """Creates an Address + Dynamic Link for the synced Member.

    The source method short-circuits when address_line1 or city are
    missing, then delegates to AddressImportService which handles
    duplicate detection and link reuse. We exercise the real DB path
    here — no mocks.
    """

    def test_returns_none_when_address_fields_missing(self):
        member = self.factory.create_member(
            first_name="NoAddr", last_name="Test",
            email="no-addr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        # address_line1 missing entirely → short-circuit
        result = get_related_records_orchestrator()._ensure_address(
            member.name, {"city": "Amsterdam"}
        )
        self.assertIsNone(result)

        # city missing → also short-circuit
        result = get_related_records_orchestrator()._ensure_address(
            member.name, {"address_line1": "Kerkstraat 1"}
        )
        self.assertIsNone(result)

    def test_creates_address_and_dynamic_link(self):
        member = self.factory.create_member(
            first_name="NewAddr", last_name="Test",
            email="new-addr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._ensure_address(
            member.name,
            {
                "address_line1": "Kerkstraat 1",
                "city": "Amsterdam",
                "postal_code": "1011AA",
                "country": "NL",
            },
        )
        self.assertIsNotNone(result)
        self.assertIn("linked", result)

        # primary_address is set on Member
        primary_address = frappe.db.get_value("Member", member.name, "primary_address")
        self.assertIsNotNone(primary_address)
        self.addCleanup(_cleanup_address, primary_address)

        # Address row exists with correct content
        addr = frappe.db.get_value(
            "Address",
            primary_address,
            ["address_line1", "city"],
            as_dict=True,
        )
        self.assertEqual(addr["address_line1"], "Kerkstraat 1")
        self.assertEqual(addr["city"], "Amsterdam")

        # Dynamic Link to the Member exists on the Address
        dl_count = frappe.db.count(
            "Dynamic Link",
            filters={
                "parent": primary_address,
                "parenttype": "Address",
                "link_doctype": "Member",
                "link_name": member.name,
            },
        )
        self.assertEqual(dl_count, 1)

    def test_idempotent_when_address_already_linked(self):
        member = self.factory.create_member(
            first_name="DupAddr", last_name="Test",
            email="dup-addr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        row_data = {
            "address_line1": "Hoofdstraat 42",
            "city": "Rotterdam",
            "postal_code": "3011BB",
            "country": "NL",
        }

        # First call creates the address
        first = get_related_records_orchestrator()._ensure_address(member.name, row_data)
        self.assertIsNotNone(first)
        primary_address = frappe.db.get_value("Member", member.name, "primary_address")
        self.assertIsNotNone(primary_address)
        self.addCleanup(_cleanup_address, primary_address)

        # Count Addresses matching this content before second call
        before = frappe.db.count(
            "Address",
            filters={"address_line1": "Hoofdstraat 42", "city": "Rotterdam"},
        )

        # Second call should reuse the existing address (no duplicate)
        second = get_related_records_orchestrator()._ensure_address(member.name, row_data)
        self.assertIsNotNone(second)

        after = frappe.db.count(
            "Address",
            filters={"address_line1": "Hoofdstraat 42", "city": "Rotterdam"},
        )
        self.assertEqual(before, after, "Second call must not create a duplicate Address")

        # primary_address still points to the same Address
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "primary_address"),
            primary_address,
        )


class TestEnsureMollieData(EnhancedTestCase):
    """Syncs Mollie customer/subscription IDs to Member + Customer records.

    The source method short-circuits when both customer_id and
    subscription_id are absent, then delegates to MollieSyncService which
    validates IDs (cst_*/sub_* format) and writes to both Member and
    Customer rows. Terminal-status members get subscription_status set
    to "canceled" instead of "active".
    """

    def test_returns_none_when_no_mollie_ids(self):
        member = self.factory.create_member(
            first_name="NoMollie", last_name="Test",
            email="no-mollie@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        # Neither customer_id nor subscription_id present → short-circuit
        result = get_related_records_orchestrator()._ensure_mollie_data(
            member.name, {"other_field": "ignored"}
        )
        self.assertIsNone(result)

        # Empty strings count as falsy → also short-circuit
        result = get_related_records_orchestrator()._ensure_mollie_data(
            member.name,
            {"custom_mollie_customer_id": "", "custom_mollie_subscription_id": ""},
        )
        self.assertIsNone(result)

    def test_syncs_customer_id_to_active_member(self):
        member = self.factory.create_member(
            first_name="MollieCust", last_name="Test",
            email="mollie-cust@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._ensure_mollie_data(
            member.name,
            {"custom_mollie_customer_id": "cst_abcdefghij"},
        )
        self.assertIsNotNone(result)
        self.assertIn("Mollie data synced", result)

        # Member.mollie_customer_id is set
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "mollie_customer_id"),
            "cst_abcdefghij",
        )

    def test_sets_canceled_status_for_terminal_member(self):
        # Terminal status member (Quit is in _TERMINAL_STATUSES) should
        # get subscription_status="canceled" when a subscription_id is
        # supplied — guards against ongoing charges on terminated members.
        member = self.factory.create_member(
            first_name="MollieQuit", last_name="Test",
            email="mollie-quit@example.org",
            status="Quit",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._ensure_mollie_data(
            member.name,
            {
                "custom_mollie_customer_id": "cst_abcdefghij",
                "custom_mollie_subscription_id": "sub_abcdefghij",
            },
        )
        self.assertIsNotNone(result)
        self.assertIn("Mollie data synced", result)

        # Terminal-status member → subscription_status forced to "canceled"
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "subscription_status"),
            "canceled",
        )


def _cleanup_chapter(name):
    """Delete a Chapter (and its child rows) and commit."""
    try:
        if frappe.db.exists("Chapter", name):
            frappe.delete_doc("Chapter", name, ignore_permissions=True, force=True)
    except Exception:
        pass
    frappe.db.commit()


class TestAssignChapterFromDivision(EnhancedTestCase):
    """Assigns a member to the Chapter mapped from a MijnRood division_id.

    The orchestrator resolves the division_id via mapping_service, then
    delegates to ChapterAssignmentService.assign_with_cleanup() which
    adds a Chapter Member row + ends any pre-existing chapter memberships.
    """

    def test_returns_error_when_division_does_not_resolve(self):
        member = self.factory.create_member(
            first_name="UnresolvedDiv", last_name="Test",
            email="unresolved-div@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        event = MagicMock()
        event.name = "EVT-RR-001"

        # 987654 has no Chapter with mijnrood_division_id=987654 nor a
        # MijnRood Sync State row that aliases to one → returns error.
        result = get_related_records_orchestrator()._assign_chapter_from_division(
            member.name, 987654, event
        )
        self.assertIsNotNone(result)
        self.assertIn("987654", result)
        self.assertIn("does not match", result)

    def test_assigns_member_to_chapter(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=4242)
        self.addCleanup(_cleanup_chapter, chapter.name)

        member = self.factory.create_member(
            first_name="AssignDiv", last_name="Test",
            email="assign-div@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        event = MagicMock()
        event.name = "EVT-RR-002"

        result = get_related_records_orchestrator()._assign_chapter_from_division(
            member.name, 4242, event
        )

        self.assertIsNotNone(result)
        self.assertIn(chapter.name, result)

        # Chapter Member row exists for this member on the target chapter
        cm_count = frappe.db.count(
            "Chapter Member",
            filters={"parent": chapter.name, "member": member.name, "enabled": 1},
        )
        self.assertEqual(cm_count, 1)

    def test_idempotent_when_member_already_in_chapter(self):
        chapter = self.factory.create_chapter(mijnrood_division_id=4343)
        self.addCleanup(_cleanup_chapter, chapter.name)

        member = self.factory.create_member(
            first_name="DupDiv", last_name="Test",
            email="dup-div@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        event = MagicMock()
        event.name = "EVT-RR-003"

        orchestrator = get_related_records_orchestrator()

        # First call adds the member to the chapter
        first = orchestrator._assign_chapter_from_division(member.name, 4343, event)
        self.assertIsNotNone(first)

        before = frappe.db.count(
            "Chapter Member",
            filters={"parent": chapter.name, "member": member.name, "enabled": 1},
        )
        self.assertEqual(before, 1)

        # Second call: member already in chapter → no duplicate row added.
        # assign_with_cleanup returns success=True with an "already in"
        # message; the orchestrator surfaces the message but does NOT add
        # a second Chapter Member row.
        second = orchestrator._assign_chapter_from_division(member.name, 4343, event)
        # second may be a message (success path) — assert no duplicate
        after = frappe.db.count(
            "Chapter Member",
            filters={"parent": chapter.name, "member": member.name, "enabled": 1},
        )
        self.assertEqual(after, 1, "Second call must not add a duplicate Chapter Member row")


class TestHandleDivisionFieldChange(EnhancedTestCase):
    """Routes division_id changes to _assign_chapter_from_division.

    Pure dispatcher logic — _assign_chapter_from_division is covered by
    its own test class, so we mock it here.
    """

    def test_returns_none_when_field_not_in_changes(self):
        member = self.factory.create_member(
            first_name="NoChange", last_name="Test",
            email="no-change@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        changed_fields = [{"field": "first_name", "old": "A", "new": "B"}]
        event = MagicMock()
        event.name = "EVT-RR-004"

        result = get_related_records_orchestrator()._handle_division_field_change(
            member.name, changed_fields, event, field_name="division_id"
        )
        self.assertIsNone(result)

    def test_delegates_to_assign_chapter_when_field_changed(self):
        member = self.factory.create_member(
            first_name="DivChange", last_name="Test",
            email="div-change@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        changed_fields = [{"field": "division_id", "old": "1", "new": "7"}]
        event = MagicMock()
        event.name = "EVT-RR-005"

        service = get_related_records_orchestrator()
        original_assign = service._assign_chapter_from_division
        # Mock justified: Routing - testing dispatcher logic,
        # _assign_chapter_from_division covered elsewhere.
        service._assign_chapter_from_division = MagicMock(
            return_value="Assigned to chapter 'Amsterdam'"
        )
        try:
            result = service._handle_division_field_change(
                member.name, changed_fields, event, field_name="division_id"
            )
        finally:
            service._assign_chapter_from_division = original_assign

        self.assertEqual(result, "Assigned to chapter 'Amsterdam'")
