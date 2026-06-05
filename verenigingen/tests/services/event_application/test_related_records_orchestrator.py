"""Real-DB integration tests for MijnRoodRelatedRecordsOrchestrator.

Tests cover address/Mollie/membership/dues creation + chapter assignment
+ user account queueing + MijnRood comment append. Each method tested
against a real DB; the per-event ACR dedup state lives on the
get_related_records_orchestrator() singleton (reset_acr_dedup /
is_acr_queued / mark_acr_queued).
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
    get_related_records_orchestrator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


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

    # ─── join_date parameter coverage ─────────────────────────────────
    # Source: related_records_orchestrator._assign_chapter_from_division
    # (lines ~159-173). A valid past join_date is passed through to
    # ChapterAssignmentService.assign_with_cleanup → MemberManager, which
    # records it as Chapter Member.chapter_join_date. Future or unparseable
    # join_date values are coerced to None, and MemberManager then defaults
    # chapter_join_date to today(). These three tests exercise the real
    # validation/coercion path end to end against the Chapter Member row.

    def test_uses_join_date_when_provided(self):
        """A valid past join_date is recorded on the Chapter Member row."""
        chapter = self.factory.create_chapter(mijnrood_division_id=4444)
        self.addCleanup(_cleanup_chapter, chapter.name)

        member = self.factory.create_member(
            first_name="JoinDateValid", last_name="Test",
            email="join-date-valid@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        event = MagicMock()
        event.name = "EVT-RR-JD-001"

        result = get_related_records_orchestrator()._assign_chapter_from_division(
            member.name, 4444, event, join_date="2025-01-15"
        )
        self.assertIsNotNone(result)

        cm_join = frappe.db.get_value(
            "Chapter Member",
            {"parent": chapter.name, "member": member.name, "enabled": 1},
            "chapter_join_date",
        )
        self.assertEqual(str(cm_join), "2025-01-15")

    def test_falls_back_to_today_when_join_date_invalid(self):
        """An unparseable join_date string is coerced to None → today() used."""
        chapter = self.factory.create_chapter(mijnrood_division_id=4445)
        self.addCleanup(_cleanup_chapter, chapter.name)

        member = self.factory.create_member(
            first_name="JoinDateInvalid", last_name="Test",
            email="join-date-invalid@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        event = MagicMock()
        event.name = "EVT-RR-JD-002"

        result = get_related_records_orchestrator()._assign_chapter_from_division(
            member.name, 4445, event, join_date="not-a-date"
        )
        self.assertIsNotNone(result)

        cm_join = frappe.db.get_value(
            "Chapter Member",
            {"parent": chapter.name, "member": member.name, "enabled": 1},
            "chapter_join_date",
        )
        self.assertEqual(str(cm_join), today())

    def test_falls_back_to_today_when_join_date_in_future(self):
        """A future join_date is rejected (coerced to None) → today() used."""
        chapter = self.factory.create_chapter(mijnrood_division_id=4446)
        self.addCleanup(_cleanup_chapter, chapter.name)

        member = self.factory.create_member(
            first_name="JoinDateFuture", last_name="Test",
            email="join-date-future@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        event = MagicMock()
        event.name = "EVT-RR-JD-003"

        result = get_related_records_orchestrator()._assign_chapter_from_division(
            member.name, 4446, event, join_date="2099-01-01"
        )
        self.assertIsNotNone(result)

        cm_join = frappe.db.get_value(
            "Chapter Member",
            {"parent": chapter.name, "member": member.name, "enabled": 1},
            "chapter_join_date",
        )
        self.assertEqual(str(cm_join), today())


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


def _cleanup_user(name):
    """Delete a User and commit."""
    try:
        if frappe.db.exists("User", name):
            frappe.delete_doc("User", name, ignore_permissions=True, force=True)
    except Exception:
        pass
    frappe.db.commit()


class TestEnsureUserAccount(EnhancedTestCase):
    """Queues an Account Creation Request for a synced Member.

    Respects the global ``create_member_accounts`` toggle in MijnRood Sync
    Settings. When enabled and the Member has no User, delegates to the
    ACR pipeline and records the Member in the singleton's per-event ACR
    dedup set (mark_acr_queued / is_acr_queued).
    """

    def setUp(self):
        super().setUp()
        # Dedup state lives on the shared singleton — reset it so state
        # never leaks between tests.
        get_related_records_orchestrator().reset_acr_dedup()

    def _set_create_member_accounts(self, value: int):
        """Toggle ``create_member_accounts`` and register a restore."""
        original = frappe.db.get_single_value(
            "MijnRood Sync Settings", "create_member_accounts"
        )
        frappe.db.set_single_value(
            "MijnRood Sync Settings", "create_member_accounts", value
        )
        frappe.db.commit()

        def _restore():
            frappe.db.set_single_value(
                "MijnRood Sync Settings", "create_member_accounts", original or 0
            )
            frappe.db.commit()

        self.addCleanup(_restore)

    def test_returns_none_when_create_member_accounts_disabled(self):
        self._set_create_member_accounts(0)

        member = self.factory.create_member(
            first_name="DisabledACR", last_name="Test",
            email="disabled-acr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        frappe.db.set_value("Member", member.name, "user", "", update_modified=False)

        result = get_related_records_orchestrator()._ensure_user_account(
            member.name
        )
        self.assertIsNone(result)
        self.assertFalse(
            get_related_records_orchestrator().is_acr_queued(member.name)
        )

    def test_queues_acr_when_enabled_and_no_user(self):
        self._set_create_member_accounts(1)

        member = self.factory.create_member(
            first_name="QueueACR", last_name="Test",
            email="queue-acr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        frappe.db.set_value("Member", member.name, "user", "", update_modified=False)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = {"request_name": "ACR-XYZ-001"}

        # Mock justified: Infrastructure - ACR queueing covered by its own suite
        with patch(
            "verenigingen.utils.account_creation_manager.queue_account_creation_for_member",
            return_value=mock_result,
        ) as mock_queue:
            result = get_related_records_orchestrator()._ensure_user_account(
                member.name
            )

        self.assertIsNotNone(result)
        self.assertIn("ACR-XYZ-001", result)
        mock_queue.assert_called_once_with(
            member.name,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Member",
            priority="Low",
        )
        self.assertTrue(
            get_related_records_orchestrator().is_acr_queued(member.name)
        )


class TestEnsureUserAccountForVolunteer(EnhancedTestCase):
    """Queues an ACR for a volunteer Member who lacks a User account.

    Unconditional (no toggle); short-circuits if the Member already has a
    User or has already been queued in the current event's dedup set.
    """

    def setUp(self):
        super().setUp()
        # Dedup state lives on the shared singleton — reset it so state
        # never leaks between tests.
        get_related_records_orchestrator().reset_acr_dedup()

    def _create_user_for_member(self, email, first_name):
        """Factory helper: create a User and return it. Registers cleanup."""
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "send_welcome_email": 0,
            "enabled": 1,
        }).insert(ignore_permissions=True)
        self.addCleanup(_cleanup_user, user_doc.name)
        return user_doc

    def test_returns_none_when_member_already_has_user(self):
        member = self.factory.create_member(
            first_name="VolHasUser", last_name="Test",
            email="vol-has-user@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        user_doc = self._create_user_for_member(member.email, "VolHasUser")
        frappe.db.set_value("Member", member.name, "user", user_doc.name, update_modified=False)

        result = get_related_records_orchestrator()._ensure_user_account_for_volunteer(
            member.name
        )
        self.assertIsNone(result)
        self.assertFalse(
            get_related_records_orchestrator().is_acr_queued(member.name)
        )

    def test_returns_none_when_already_in_acr_queue(self):
        member = self.factory.create_member(
            first_name="VolDup", last_name="Test",
            email="vol-dup-acr@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        frappe.db.set_value("Member", member.name, "user", "", update_modified=False)

        # Pre-seed the singleton dedup set so the method short-circuits.
        get_related_records_orchestrator().mark_acr_queued(member.name)

        result = get_related_records_orchestrator()._ensure_user_account_for_volunteer(
            member.name
        )
        self.assertIsNone(result)


def _cleanup_membership(name):
    """Cancel + delete a Membership and commit."""
    try:
        if frappe.db.exists("Membership", name):
            mem = frappe.get_doc("Membership", name)
            if mem.docstatus == 1:
                mem.cancel()
            frappe.delete_doc("Membership", name, ignore_permissions=True, force=True)
    except Exception:
        pass
    frappe.db.commit()


def _cleanup_dues_schedule(name):
    """Delete a Membership Dues Schedule and commit."""
    try:
        if frappe.db.exists("Membership Dues Schedule", name):
            frappe.delete_doc(
                "Membership Dues Schedule", name, ignore_permissions=True, force=True
            )
    except Exception:
        pass
    frappe.db.commit()


class TestEnsureMembershipAndDues(EnhancedTestCase):
    """Creates a Membership + Dues Schedule for the synced Member.

    Source behaviour (verified against event_application_service.py):
    - Short-circuits if ``dues_rate`` is not in row_data → returns None.
    - Short-circuits if ``payment_period`` is not in row_data → returns None.
    - Short-circuits if Member.status != "Active" → returns None.
    - If an active submitted Membership exists, routes to either
      ``_update_existing_dues_schedule`` (when a schedule exists and
      dues_rate is supplied) or ``_backfill_dues_schedule`` (no schedule).
    - Otherwise delegates to
      ``MembershipImportService.create_membership_from_csv()``.

    The inner Membership creation pipeline (MembershipImportService →
    create_membership_on_approval → application workflow) is covered by
    its own test suite and requires a Verenigingen Settings
    default_membership_type fixture that is impractical to set up here.
    We use a justified mock for that inner call and verify the dispatcher
    routing only.
    """

    def test_returns_none_when_dues_rate_missing(self):
        # The plan referenced ``membership_type`` but the actual source
        # gate is ``dues_rate``. Verify the real gate.
        member = self.factory.create_member(
            first_name="NoDuesRate", last_name="Test",
            email="no-dues-rate@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._ensure_membership_and_dues(
            member.name, {"payment_period": "Maandelijks"}
        )
        self.assertIsNone(result)

    def test_creates_membership_when_none_exists(self):
        membership_type = self.factory.ensure_membership_type(
            "Related Records Dues Test Type"
        )
        member = self.factory.create_member(
            first_name="NewMembership", last_name="Test",
            email="new-membership@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        # Ensure status is Active (required by source gate)
        frappe.db.set_value("Member", member.name, "status", "Active", update_modified=False)
        frappe.db.commit()

        row_data = {
            "dues_rate": 12.50,
            "payment_period": "Maandelijks",
            "membership_type": membership_type.name,
            "member_since": today(),
        }

        # Mock justified: Infrastructure - the inner MembershipImportService
        # pipeline (create_membership_on_approval → application workflow) is
        # covered by its own test suite and requires fixtures
        # (default_membership_type, csv_*_dues_schedule, etc. in
        # Verenigingen Settings) that are impractical to set up at this
        # unit-test level. We verify the dispatcher routes to the import
        # service with the correct arguments.
        mock_service = MagicMock()
        mock_service.create_membership_from_csv = MagicMock(
            return_value="MEM-DUMMY-001"
        )
        with patch(
            "verenigingen.services.csv_import.membership_import_service.get_membership_import_service",
            return_value=mock_service,
        ):
            result = get_related_records_orchestrator()._ensure_membership_and_dues(
                member.name, row_data
            )

        self.assertIsNotNone(result)
        self.assertIn("MEM-DUMMY-001", result)
        mock_service.create_membership_from_csv.assert_called_once()
        # Verify first positional arg is the Member doc and second is row_data
        call_args = mock_service.create_membership_from_csv.call_args
        self.assertEqual(call_args[0][0].name, member.name)
        self.assertEqual(call_args[0][1], row_data)

    def _create_submitted_membership_without_schedule(
        self, member_name, membership_type_name
    ):
        """Factory helper: submitted Active Membership with no dues schedule.

        Sets flags.skip_dues_schedule_creation so on_submit doesn't auto-
        create a schedule (which would defeat the "no schedule" branch).
        """
        # Security: Test fixture - sets up controlled state for the
        # _ensure_membership_and_dues backfill branch.
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member_name,
            "membership_type": membership_type_name,
            "start_date": today(),
            "status": "Active",
        }).insert(ignore_permissions=True)
        membership.flags.skip_dues_schedule_creation = True
        membership.submit()
        frappe.db.commit()
        self.addCleanup(_cleanup_membership, membership.name)
        return membership

    def _ensure_quarterly_dues_template_configured(self, membership_type_name):
        """Seed a quarterly dues template and point Verenigingen Settings at it.

        Restores the original setting value on cleanup so the Single is not
        polluted for other tests.
        """
        template_name = "Test CSV Quarterly Template"
        if not frappe.db.exists("Membership Dues Schedule", template_name):
            frappe.get_doc({
                "doctype": "Membership Dues Schedule",
                "schedule_name": template_name,
                "is_template": 1,
                "membership_type": membership_type_name,
                "status": "Active",
                "billing_frequency": "Quarterly",
                "dues_rate": 12.50,
                "currency": "EUR",
                "minimum_amount": 0,
                "suggested_amount": 12.50,
            }).insert(ignore_permissions=True)
            self.addCleanup(_cleanup_dues_schedule, template_name)

        original = frappe.db.get_single_value("Verenigingen Settings", "csv_quarterly_dues_schedule")
        frappe.db.set_single_value("Verenigingen Settings", "csv_quarterly_dues_schedule", template_name)
        frappe.db.commit()
        self.addCleanup(
            lambda: (
                frappe.db.set_single_value(
                    "Verenigingen Settings", "csv_quarterly_dues_schedule", original
                ),
                frappe.db.commit(),
            )
        )

    def test_backfills_dues_schedule_when_membership_exists_without_schedule(self):
        # When an active Membership exists but no dues schedule, the source
        # routes to _backfill_dues_schedule which runs for real here: it
        # resolves the dues template from payment_period ("Per kwartaal" →
        # csv_quarterly_dues_schedule in Verenigingen Settings) and calls
        # MembershipDuesSchedule.create_from_template. We assert a real
        # non-template Dues Schedule row lands in the DB at the right rate.
        # Use a low minimum so the backfilled rate (€12.50) clears
        # validate_rate_boundaries.
        membership_type = self.factory.ensure_membership_type(
            "Related Records Dues Test Type Low Min", {"amount": 10.00}
        )
        member = self.factory.create_member(
            first_name="BackfillNeeded", last_name="Test",
            email="backfill-needed@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        frappe.db.set_value("Member", member.name, "status", "Active", update_modified=False)

        self._create_submitted_membership_without_schedule(
            member.name, membership_type.name
        )
        self.addCleanup(self._cleanup_member_dues_schedules, member.name)

        # The backfill resolves the dues template from payment_period
        # ("Per kwartaal" → Verenigingen Settings.csv_quarterly_dues_schedule).
        # test_site_2 has no such template configured, so seed one and point the
        # Single at it (restoring the original value afterwards).
        self._ensure_quarterly_dues_template_configured(membership_type.name)

        result = get_related_records_orchestrator()._ensure_membership_and_dues(
            member.name,
            {"dues_rate": 12.50, "payment_period": "Per kwartaal"},
        )

        self.assertIsNotNone(result)
        self.assertIn("created for existing membership", result)

        # A real non-template Dues Schedule row was created for the member.
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0},
            "name",
        )
        self.assertIsNotNone(
            schedule_name, "Backfill should create a real Dues Schedule row"
        )
        # custom_amount (dues_rate) is applied as the schedule rate.
        rate = frappe.db.get_value(
            "Membership Dues Schedule", schedule_name, "dues_rate"
        )
        self.assertEqual(float(rate), 12.50)

    def _cleanup_member_dues_schedules(self, member_name):
        """Delete any non-template Dues Schedules left for a member; commit.

        _backfill_dues_schedule's create_from_template commits, so the rows
        survive EnhancedTestCase rollback and must be removed explicitly.
        """
        for name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0},
            pluck="name",
        ):
            _cleanup_dues_schedule(name)


class TestUpdateExistingDuesSchedule(EnhancedTestCase):
    """Updates the dues rate on an existing schedule via DuesScheduleRepository.

    The orchestrator method is a thin wrapper over
    ``DuesScheduleRepository.update_schedule_rate`` which is idempotent
    (returns ``method_used="no_change_needed"`` when the rate matches).
    """

    def _create_active_dues_schedule(self, member_name, membership_type_name, rate):
        """Factory helper: create a non-template active Dues Schedule."""
        # Security: Test fixture - sets up controlled state for the
        # _update_existing_dues_schedule code path.
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "schedule_name": f"DS-{member_name}",
            "is_template": 0,
            "member": member_name,
            "membership_type": membership_type_name,
            "status": "Active",
            "billing_frequency": "Monthly",
            "dues_rate": rate,
            "currency": "EUR",
            "contribution_mode": "Custom",
            "minimum_amount": 0,
            "suggested_amount": rate,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        self.addCleanup(_cleanup_dues_schedule, schedule.name)
        return schedule

    def test_returns_none_when_no_active_schedule(self):
        member = self.factory.create_member(
            first_name="NoSchedule", last_name="Test",
            email="no-schedule@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        result = get_related_records_orchestrator()._update_existing_dues_schedule(
            member.name, 25.0
        )
        self.assertIsNone(result)

    def _create_active_membership(self, member_name, membership_type_name):
        """Factory helper: create a submitted, Active Membership.

        Sets ``flags.skip_dues_schedule_creation`` to prevent on_submit's
        auto dues-schedule creation — our test creates its own controlled
        schedule fixture afterwards.
        """
        # Security: Test fixture - required to satisfy
        # MembershipDuesSchedule.validate_member_membership() during
        # _create_active_dues_schedule below.
        membership = frappe.get_doc({
            "doctype": "Membership",
            "member": member_name,
            "membership_type": membership_type_name,
            "start_date": today(),
            "status": "Active",
        }).insert(ignore_permissions=True)
        membership.flags.skip_dues_schedule_creation = True
        membership.submit()
        frappe.db.commit()
        self.addCleanup(_cleanup_membership, membership.name)
        return membership

    def test_updates_rate_on_existing_schedule(self):
        membership_type = self.factory.ensure_membership_type(
            "Related Records Dues Test Type"
        )
        member = self.factory.create_member(
            first_name="UpdateRate", last_name="Test",
            email="update-rate@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)

        # Validate_member_membership requires an active submitted Membership.
        # ensure_membership_type creates the type with minimum_amount=50.00
        # by default, so schedule rates must be >= 50.00.
        self._create_active_membership(member.name, membership_type.name)
        schedule = self._create_active_dues_schedule(
            member.name, membership_type.name, rate=50.00
        )

        result = get_related_records_orchestrator()._update_existing_dues_schedule(
            member.name, 75.00
        )
        self.assertIsNotNone(result)
        self.assertIn(schedule.name, result)

        # Verify the rate was persisted
        new_rate = frappe.db.get_value(
            "Membership Dues Schedule", schedule.name, "dues_rate"
        )
        self.assertEqual(float(new_rate), 75.00)

    def test_updates_rate_as_non_admin_role(self):
        """The MijnRood sync updates the dues rate even when the calling user
        lacks Membership Dues Schedule write permission.

        The sync is a trusted system process and bypasses DocPerms like every
        other write in the mijnrood_sync module. Regression guard for the
        permission-gate inconsistency in
        DuesScheduleRepository.update_schedule_rate().
        """
        membership_type = self.factory.ensure_membership_type(
            "Related Records Dues Test Type"
        )
        member = self.factory.create_member(
            first_name="NonAdminRate", last_name="Test",
            email="non-admin-rate@example.org",
        )
        self.addCleanup(_cleanup_member_and_customer, self, member.name)
        self._create_active_membership(member.name, membership_type.name)
        schedule = self._create_active_dues_schedule(
            member.name, membership_type.name, rate=50.00
        )

        # Verenigingen Volunteer holds no write DocPerm on Membership Dues
        # Schedule — without the orchestrator passing ignore_permissions the
        # rate update is rejected with "Permission denied".
        with self.as_role("Verenigingen Volunteer"):
            result = get_related_records_orchestrator()._update_existing_dues_schedule(
                member.name, 75.00
            )

        self.assertIsNotNone(result)
        self.assertNotIn("failed", result.lower())

        new_rate = frappe.db.get_value(
            "Membership Dues Schedule", schedule.name, "dues_rate"
        )
        self.assertEqual(float(new_rate), 75.00)


class TestCreateRelatedRecords(EnhancedTestCase):
    """Entry-point orchestrator — fans out to sub-methods per row_data shape."""

    def setUp(self):
        super().setUp()
        # Mock justified: Routing - testing dispatcher logic, sub-methods
        # (_ensure_address, _ensure_mollie_data, etc.) are covered by
        # their own real-DB tests in this same file.
        from verenigingen.mijnrood_sync.services.event_application.related_records_orchestrator import (
            MijnRoodRelatedRecordsOrchestrator,
        )
        self.service = MijnRoodRelatedRecordsOrchestrator()
        self.service._assign_chapter_from_division = MagicMock(return_value="Chapter assigned")
        self.service._ensure_address = MagicMock(return_value="Address linked")
        self.service._ensure_mollie_data = MagicMock(return_value="Mollie synced")
        self.service._ensure_membership_and_dues = MagicMock(return_value="Membership created")
        self.service._ensure_user_account = MagicMock(return_value="Account queued")
        self.service._apply_mijnrood_comments = MagicMock(return_value="Comments added")

    def test_returns_all_sub_method_messages(self):
        event = MagicMock()
        event.name = "EVT-001"
        msgs = self.service._create_related_records(
            "MEM-001",
            {"chapter": 42, "member_since": "2025-01-01"},  # triggers chapter assignment
            event=event,
        )
        self.assertIn("Chapter assigned", msgs)
        self.assertIn("Address linked", msgs)
        self.assertIn("Mollie synced", msgs)
        self.assertIn("Membership created", msgs)
        self.assertIn("Account queued", msgs)
        self.assertIn("Comments added", msgs)

    def test_returns_empty_list_when_all_submethods_return_none(self):
        for attr in ("_assign_chapter_from_division", "_ensure_address",
                     "_ensure_mollie_data", "_ensure_membership_and_dues",
                     "_ensure_user_account", "_apply_mijnrood_comments"):
            setattr(self.service, attr, MagicMock(return_value=None))

        msgs = self.service._create_related_records(
            "MEM-002", {}, event=MagicMock(name="EVT-002")
        )
        self.assertEqual(msgs, [])

    def test_delegates_to_ensure_user_account(self):
        event = MagicMock()
        event.name = "EVT-003"
        self.service._create_related_records("MEM-003", {}, event=event)
        self.service._ensure_user_account.assert_called_once_with("MEM-003")
