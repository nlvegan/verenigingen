"""
Real-integration tests for the chapter ``BoardManager``
``verenigingen/verenigingen/doctype/chapter/managers/board_manager.py``.

The manager owns chapter board-member operations (add / remove / transition /
bulk remove / bulk deactivate / queries / role-profile sync). It is reached in
production via ``chapter_doc.board_manager`` (a lazily-built ``BoardManager(self)``),
so every test resolves the manager that way to mirror the real call path rather
than instantiating the class directly.

All Chapters/Members/Volunteers/Chapter Roles/board members are created via the
real test factory (no business-logic mocking) and the suite runs as
Administrator. Notification helpers send through the unified EmailService (a
no-op in tests), so they are exercised indirectly via add/remove/transition and
asserted only on their observable side effects (board-member rows, is_active,
to_date, roles dict) rather than the email send itself.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestBoardManager(VereningingenTestCase):
    """Exercise the chapter BoardManager end to end via chapter.board_manager."""

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"BoardMgr Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    # ------------------------------------------------------------------ helpers

    @property
    def manager(self):
        """Resolve the manager the same way production does."""
        return self.chapter.board_manager

    def _reload_chapter(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_role(self, permissions_level="Basic", is_chair=0, is_unique=0, is_active=1):
        role_name = f"Role{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": permissions_level,
                "is_chair": is_chair,
                "is_unique": is_unique,
                "is_active": is_active,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def _make_volunteer(self, first="Board"):
        member = self.create_test_member(
            first_name=first,
            last_name="BoardMgr",
            email=f"boardmgr.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        volunteer = self.create_test_volunteer(member=member.name)
        return member, volunteer

    def _seat_board(self, permissions_level="Basic", is_chair=0, first="Board", role_name=None):
        """Seat a real volunteer in a real role on self.chapter via the factory helper.

        Returns (member, volunteer, role_name).
        """
        member, volunteer = self._make_volunteer(first=first)
        if role_name is None:
            role_name = self._make_role(permissions_level=permissions_level, is_chair=is_chair)
        self.add_board_member_to_chapter(self.chapter, volunteer, role_name, email=member.email)
        self._reload_chapter()
        return member, volunteer, role_name

    # ====================================================== add_board_member

    def test_add_board_member_happy_path(self):
        member, volunteer = self._make_volunteer(first="Adder")
        role_name = self._make_role()
        result = self.manager.add_board_member(volunteer.name, role_name, notify=False)
        self.assertTrue(result["success"])

        self._reload_chapter()
        seated = [b for b in self.chapter.board_members if b.volunteer == volunteer.name and b.is_active]
        self.assertEqual(len(seated), 1)
        self.assertEqual(seated[0].chapter_role, role_name)
        self.assertEqual(str(seated[0].from_date), today())
        # board member added => member auto-added to chapter members
        self.assertTrue(any(m.member == member.name for m in self.chapter.members))

    def test_add_board_member_nonexistent_volunteer_throws(self):
        role_name = self._make_role()
        with self.assertRaises(frappe.ValidationError):
            self.manager.add_board_member("NONEXISTENT-VOLUNTEER-XYZ", role_name, notify=False)

    def test_add_board_member_nonexistent_role_throws(self):
        _member, volunteer = self._make_volunteer(first="NoRole")
        with self.assertRaises(frappe.ValidationError):
            self.manager.add_board_member(volunteer.name, "NONEXISTENT-ROLE-XYZ", notify=False)

    def test_add_board_member_inactive_role_throws(self):
        _member, volunteer = self._make_volunteer(first="InactRole")
        role_name = self._make_role(is_active=0)
        with self.assertRaises(frappe.ValidationError):
            self.manager.add_board_member(volunteer.name, role_name, notify=False)

    def test_add_board_member_honours_explicit_from_date(self):
        _member, volunteer = self._make_volunteer(first="DatedAdd")
        role_name = self._make_role()
        self.manager.add_board_member(volunteer.name, role_name, from_date="2024-02-01", notify=False)
        self._reload_chapter()
        seated = next(b for b in self.chapter.board_members if b.volunteer == volunteer.name)
        self.assertEqual(str(seated.from_date), "2024-02-01")

    # =============================================== unique-role assignment

    def test_unique_role_deactivates_previous_holder(self):
        # A unique role can only be held by one active board member at a time.
        role_name = self._make_role(is_unique=1)
        _m1, vol1 = self._make_volunteer(first="UniqueA")
        _m2, vol2 = self._make_volunteer(first="UniqueB")

        self.manager.add_board_member(vol1.name, role_name, notify=False)
        self._reload_chapter()
        self.chapter.board_manager.add_board_member(vol2.name, role_name, notify=False)
        self._reload_chapter()

        active = [
            b for b in self.chapter.board_members if b.chapter_role == role_name and b.is_active
        ]
        self.assertEqual(len(active), 1, "unique role must have exactly one active holder")
        self.assertEqual(active[0].volunteer, vol2.name)

        # The displaced holder was deactivated, not deleted.
        displaced = next(
            b for b in self.chapter.board_members if b.volunteer == vol1.name
        )
        self.assertFalse(displaced.is_active)

    # ====================================================== remove_board_member

    def test_remove_board_member_happy_path(self):
        _member, volunteer, _role = self._seat_board(first="Remover")
        result = self.manager.remove_board_member(
            volunteer.name, end_date=today(), reason="stepped down", notify=False
        )
        self.assertTrue(result["success"])

        self._reload_chapter()
        row = next(b for b in self.chapter.board_members if b.volunteer == volunteer.name)
        self.assertFalse(row.is_active)
        self.assertEqual(str(row.to_date), today())
        self.assertIn("stepped down", row.notes or "")

    def test_remove_board_member_not_active_throws(self):
        _member, volunteer = self._make_volunteer(first="NeverSeated")
        with self.assertRaises(frappe.ValidationError):
            self.manager.remove_board_member(volunteer.name, notify=False)

    # ==================================================== transition_board_role

    def test_transition_board_role_deactivates_old_role(self):
        # transition_board_role ends the current role (the add-new-role line is
        # commented out in production), so the observable effect is the old role
        # row going inactive.
        _member, volunteer, old_role = self._seat_board(first="Transit")
        result = self.manager.transition_board_role(
            volunteer.name, "Treasurer-elect", transition_date=today(), reason="reorg"
        )
        self.assertTrue(result["success"])

        self._reload_chapter()
        old_row = next(
            b for b in self.chapter.board_members if b.volunteer == volunteer.name and b.chapter_role == old_role
        )
        self.assertFalse(old_row.is_active)
        self.assertFalse(self.chapter.board_manager.is_board_member(volunteer_name=volunteer.name))

    def test_transition_board_role_not_active_throws(self):
        _member, volunteer = self._make_volunteer(first="NoTransit")
        with self.assertRaises(frappe.ValidationError):
            self.manager.transition_board_role(volunteer.name, "Whatever")

    # ===================================================== bulk_remove_board_members

    def test_bulk_remove_board_members_removes_matching_rows(self):
        _member, volunteer, role_name = self._seat_board(first="BulkRem")
        from_date = next(
            b.from_date for b in self.chapter.board_members if b.volunteer == volunteer.name
        )
        result = self.manager.bulk_remove_board_members(
            [
                {
                    "volunteer": volunteer.name,
                    "chapter_role": role_name,
                    "from_date": str(from_date),
                    "end_date": today(),
                    "reason": "bulk cleanup",
                }
            ]
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)

        self._reload_chapter()
        # Removal deletes the row entirely.
        self.assertFalse(any(b.volunteer == volunteer.name for b in self.chapter.board_members))

    def test_bulk_remove_board_members_empty_list(self):
        result = self.manager.bulk_remove_board_members([])
        self.assertFalse(result["success"])
        self.assertIn("No board members", result["error"])

    def test_bulk_remove_board_members_accepts_json_string(self):
        result = self.manager.bulk_remove_board_members("[]")
        self.assertFalse(result["success"])

    def test_bulk_remove_board_members_missing_volunteer_records_error(self):
        result = self.manager.bulk_remove_board_members([{"chapter_role": "X", "from_date": today()}])
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 0)
        self.assertIn("Missing volunteer ID", result["errors"])

    def test_bulk_remove_board_members_not_found_records_error(self):
        _m, volunteer = self._make_volunteer(first="BulkMiss")
        result = self.manager.bulk_remove_board_members(
            [{"volunteer": volunteer.name, "chapter_role": "X", "from_date": today()}]
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 0)
        self.assertTrue(any("not found" in e for e in result["errors"]))

    # ================================================= bulk_deactivate_board_members

    def test_bulk_deactivate_board_members_marks_inactive(self):
        _member, volunteer, role_name = self._seat_board(first="BulkDeact")
        from_date = next(
            b.from_date for b in self.chapter.board_members if b.volunteer == volunteer.name
        )
        result = self.manager.bulk_deactivate_board_members(
            [
                {
                    "volunteer": volunteer.name,
                    "chapter_role": role_name,
                    "from_date": str(from_date),
                    "end_date": today(),
                    "reason": "deactivated in bulk",
                }
            ]
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 1)

        self._reload_chapter()
        # Deactivation keeps the row but marks it inactive.
        row = next(b for b in self.chapter.board_members if b.volunteer == volunteer.name)
        self.assertFalse(row.is_active)
        self.assertEqual(str(row.to_date), today())
        self.assertIn("deactivated in bulk", row.notes or "")

    def test_bulk_deactivate_board_members_empty_list(self):
        result = self.manager.bulk_deactivate_board_members([])
        self.assertFalse(result["success"])

    def test_bulk_deactivate_board_members_missing_volunteer_records_error(self):
        result = self.manager.bulk_deactivate_board_members([{"chapter_role": "X"}])
        self.assertTrue(result["success"])
        self.assertEqual(result["processed"], 0)
        self.assertIn("Missing volunteer ID", result["errors"])

    # ================================================= get_board_members / queries

    def test_get_board_members_active_only_by_default(self):
        _member, volunteer, role_name = self._seat_board(first="Queryme")
        members = self.manager.get_board_members()
        self.assertTrue(any(m["volunteer"] == volunteer.name and m["role"] == role_name for m in members))

    def test_get_board_members_include_inactive(self):
        _member, volunteer, _role = self._seat_board(first="InactQuery")
        self.manager.remove_board_member(volunteer.name, notify=False)
        self._reload_chapter()

        active_only = self.chapter.board_manager.get_board_members()
        self.assertFalse(any(m["volunteer"] == volunteer.name for m in active_only))

        with_inactive = self.chapter.board_manager.get_board_members(include_inactive=True)
        self.assertTrue(any(m["volunteer"] == volunteer.name for m in with_inactive))

    def test_get_board_members_role_filter(self):
        _m1, vol1, role1 = self._seat_board(first="RoleFilterA")
        _m2, vol2, role2 = self._seat_board(first="RoleFilterB")
        only_role1 = self.chapter.board_manager.get_board_members(role=role1)
        vols = {m["volunteer"] for m in only_role1}
        self.assertIn(vol1.name, vols)
        self.assertNotIn(vol2.name, vols)

    def test_get_board_members_empty_chapter(self):
        self.assertEqual(self.manager.get_board_members(), [])

    # ===================================================== get_active_board_roles

    def test_get_active_board_roles(self):
        member, volunteer, role_name = self._seat_board(first="ActiveRoles")
        roles = self.manager.get_active_board_roles()
        self.assertIn(role_name, roles)
        self.assertEqual(roles[role_name]["volunteer"], volunteer.name)
        self.assertEqual(roles[role_name]["member"], member.name)

    def test_get_active_board_roles_empty(self):
        self.assertEqual(self.manager.get_active_board_roles(), {})

    def test_get_active_board_roles_excludes_inactive(self):
        _member, volunteer, role_name = self._seat_board(first="InactRoles")
        self.manager.remove_board_member(volunteer.name, notify=False)
        self._reload_chapter()
        self.assertNotIn(role_name, self.chapter.board_manager.get_active_board_roles())

    # ===================================================== is_board_member

    def test_is_board_member_by_member_name(self):
        member, _vol, _role = self._seat_board(first="IsBoardMem")
        self.assertTrue(self.manager.is_board_member(member_name=member.name))

    def test_is_board_member_by_volunteer_name(self):
        _member, volunteer, _role = self._seat_board(first="IsBoardVol")
        self.assertTrue(self.manager.is_board_member(volunteer_name=volunteer.name))

    def test_is_board_member_by_user(self):
        member, _vol, _role = self._seat_board(first="IsBoardUser")
        user = self.create_test_user(
            f"isboard.{frappe.generate_hash(length=6)}@test.invalid", roles=["Verenigingen Member"]
        )
        frappe.db.set_value("Member", member.name, "user", user.name)
        self.assertTrue(self.chapter.board_manager.is_board_member(user=user.name))

    def test_is_board_member_false_for_non_board(self):
        member = self.create_test_member(
            first_name="NonBoard",
            last_name="BoardMgr",
            email=f"nonboard.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.assertFalse(self.manager.is_board_member(member_name=member.name))

    def test_is_board_member_inactive_volunteer_is_false(self):
        _member, volunteer, _role = self._seat_board(first="IsBoardInact")
        self.manager.remove_board_member(volunteer.name, notify=False)
        self._reload_chapter()
        self.assertFalse(self.chapter.board_manager.is_board_member(volunteer_name=volunteer.name))

    # ===================================================== get_member_role

    def test_get_member_role_by_member_name(self):
        member, _vol, role_name = self._seat_board(first="RoleByMem")
        self.assertEqual(self.manager.get_member_role(member_name=member.name), role_name)

    def test_get_member_role_by_volunteer_name(self):
        _member, volunteer, role_name = self._seat_board(first="RoleByVol")
        self.assertEqual(self.manager.get_member_role(volunteer_name=volunteer.name), role_name)

    def test_get_member_role_by_user(self):
        member, _vol, role_name = self._seat_board(first="RoleByUser")
        user = self.create_test_user(
            f"rolebyuser.{frappe.generate_hash(length=6)}@test.invalid", roles=["Verenigingen Member"]
        )
        frappe.db.set_value("Member", member.name, "user", user.name)
        self.assertEqual(self.chapter.board_manager.get_member_role(user=user.name), role_name)

    def test_get_member_role_none_for_non_board(self):
        member = self.create_test_member(
            first_name="NoRoleMem",
            last_name="BoardMgr",
            email=f"noromem.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.assertIsNone(self.manager.get_member_role(member_name=member.name))

    # ===================================================== can_view_member_payments

    def test_can_view_member_payments_basic_denied(self):
        member, _vol, _role = self._seat_board(permissions_level="Basic", first="PayBasic")
        self.assertFalse(self.manager.can_view_member_payments(member_name=member.name))

    def test_can_view_member_payments_financial_allowed(self):
        member, _vol, _role = self._seat_board(permissions_level="Financial", first="PayFin")
        self.assertTrue(self.manager.can_view_member_payments(member_name=member.name))

    def test_can_view_member_payments_admin_allowed(self):
        member, _vol, _role = self._seat_board(permissions_level="Admin", first="PayAdmin")
        self.assertTrue(self.manager.can_view_member_payments(member_name=member.name))

    def test_can_view_member_payments_non_board_denied(self):
        member = self.create_test_member(
            first_name="PayNonBoard",
            last_name="BoardMgr",
            email=f"paynonboard.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.assertFalse(self.manager.can_view_member_payments(member_name=member.name))

    def test_can_view_member_payments_no_member_returns_false(self):
        # No member resolved (passing an unknown user) -> False, no exception.
        self.assertFalse(
            self.manager.can_view_member_payments(user="nonexistent-user-xyz@test.invalid")
        )

    # ===================================================== get_summary

    def test_get_summary_counts_and_distribution(self):
        _member, _vol, role_name = self._seat_board(first="SummaryA")
        summary = self.manager.get_summary()
        self.assertEqual(summary["total_board_members"], 1)
        self.assertEqual(summary["active_board_members"], 1)
        self.assertEqual(summary["inactive_board_members"], 0)
        self.assertEqual(summary["role_distribution"].get(role_name), 1)
        self.assertFalse(summary["has_chair"])
        self.assertIn("average_tenure_days", summary)
        self.assertIn("recent_changes", summary)

    def test_get_summary_detects_chair(self):
        self._seat_board(is_chair=1, first="SummaryChair")
        summary = self.manager.get_summary()
        self.assertTrue(summary["has_chair"])

    def test_get_summary_counts_inactive(self):
        _member, volunteer, _role = self._seat_board(first="SummaryInact")
        self.manager.remove_board_member(volunteer.name, notify=False)
        self._reload_chapter()
        summary = self.chapter.board_manager.get_summary()
        self.assertEqual(summary["inactive_board_members"], 1)
        self.assertEqual(summary["active_board_members"], 0)

    # ===================================================== _is_chair_role (via summary)

    def test_is_chair_role_true_for_chair(self):
        role_name = self._make_role(is_chair=1)
        self.assertTrue(self.manager._is_chair_role(role_name))

    def test_is_chair_role_false_for_non_chair(self):
        role_name = self._make_role(is_chair=0)
        self.assertFalse(self.manager._is_chair_role(role_name))

    def test_is_chair_role_false_for_unknown(self):
        self.assertFalse(self.manager._is_chair_role("NONEXISTENT-ROLE-XYZ"))

    def test_is_chair_role_false_for_none(self):
        self.assertFalse(self.manager._is_chair_role(None))

    # ===================================================== flush_pending_board_profile_syncs

    def test_flush_pending_board_profile_syncs_noop_when_empty(self):
        # No pending list attribute -> safe no-op.
        if hasattr(self.chapter, "_pending_board_profile_syncs"):
            delattr(self.chapter, "_pending_board_profile_syncs")
        self.manager.flush_pending_board_profile_syncs()  # must not raise

    def test_flush_pending_board_profile_syncs_drains_and_clears(self):
        member, volunteer, _role = self._seat_board(first="FlushSync")
        # Seating already drained any pending syncs via after_save. Re-arm the list
        # with a real volunteer and confirm flush clears it without raising.
        self.chapter._pending_board_profile_syncs = [volunteer.name]
        self.chapter.board_manager.flush_pending_board_profile_syncs()
        self.assertEqual(self.chapter._pending_board_profile_syncs, [])

    # ===================================================== handle_board_member_* (via save)

    def test_handle_board_member_additions_on_save_appends_history(self):
        # Seating a board member via parent save runs handle_board_member_additions,
        # which appends a volunteer assignment-history row.
        _member, volunteer, role_name = self._seat_board(first="AddHist")
        history = frappe.get_all(
            "Volunteer Assignment",
            filters={"parent": volunteer.name, "reference_name": self.chapter.name},
            fields=["name", "role"],
        )
        self.assertTrue(history, "board addition should append a volunteer assignment-history row")

    def test_handle_board_member_changes_role_change_via_save(self):
        # Edit the seated row's role and re-save; handle_board_member_changes should
        # close the old assignment and open a new one.
        _member, volunteer, old_role = self._seat_board(first="ChangeRole")
        new_role = self._make_role()
        self._reload_chapter()
        for b in self.chapter.board_members:
            if b.volunteer == volunteer.name and b.is_active:
                b.chapter_role = new_role
        self.chapter.save()
        self._reload_chapter()
        row = next(b for b in self.chapter.board_members if b.volunteer == volunteer.name and b.is_active)
        self.assertEqual(row.chapter_role, new_role)

    def test_role_change_does_not_duplicate_assignment_history(self):
        # Regression: a role change must produce exactly ONE Active assignment for
        # the new role and complete the old one — not two Active rows for the new
        # role. handle_board_member_additions used to misread the role change as a
        # brand-new member and re-add the new role with a different start_date,
        # which slipped past the (reference, role, start_date) dedup.
        #
        # The board member is seated with a PAST from_date so the original
        # assignment's start_date differs from today() (the role-change date).
        # This reproduces production, where the seating day and the change day
        # differ — without it, both adds share today() and the old dedup hides
        # the bug.
        from frappe.utils import add_days, today

        member, volunteer = self._make_volunteer(first="DupHist")
        old_role = self._make_role()
        self.add_board_member_to_chapter(
            self.chapter, volunteer, old_role, email=member.email, from_date=add_days(today(), -10)
        )
        self._reload_chapter()

        new_role = self._make_role()
        for b in self.chapter.board_members:
            if b.volunteer == volunteer.name and b.is_active:
                b.chapter_role = new_role
        self.chapter.save()

        history = frappe.get_all(
            "Volunteer Assignment",
            filters={
                "parent": volunteer.name,
                "reference_doctype": "Chapter",
                "reference_name": self.chapter.name,
            },
            fields=["role", "status", "start_date", "end_date"],
        )

        active_new = [h for h in history if h.role == new_role and h.status == "Active"]
        self.assertEqual(
            len(active_new), 1, f"expected exactly one Active entry for the new role, got {active_new}"
        )

        completed_old = [h for h in history if h.role == old_role and h.status == "Completed"]
        self.assertEqual(
            len(completed_old), 1, f"old role should be completed exactly once, got {completed_old}"
        )
        self.assertTrue(completed_old[0].end_date, "completed old-role assignment must carry an end_date")

        # No lingering Active row for the old role.
        self.assertFalse(
            [h for h in history if h.role == old_role and h.status == "Active"],
            "old role must not remain Active after a role change",
        )

    def test_add_assignment_history_is_idempotent_on_active_role(self):
        # Idempotency guard: adding the same Active (reference, role) twice — even
        # with a different start_date — must not create a duplicate Active row.
        from frappe.utils import add_days, today

        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        _member, volunteer, role_name = self._seat_board(first="Idempot")
        # Seating already created one Active assignment. A second add for the same
        # role with a different start_date must be a no-op.
        AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer.name,
            assignment_type="Board Position",
            reference_doctype="Chapter",
            reference_name=self.chapter.name,
            role=role_name,
            start_date=add_days(today(), -5),
        )
        active = frappe.get_all(
            "Volunteer Assignment",
            filters={
                "parent": volunteer.name,
                "reference_doctype": "Chapter",
                "reference_name": self.chapter.name,
                "role": role_name,
                "status": "Active",
            },
        )
        self.assertEqual(len(active), 1, "duplicate Active assignment must be suppressed")

    def test_handle_board_member_deletions_via_save(self):
        # Delete the seated row and re-save; handle_board_member_deletions runs.
        _member, volunteer, _role = self._seat_board(first="DeleteRow")
        self._reload_chapter()
        self.chapter.board_members = [
            b for b in self.chapter.board_members if b.volunteer != volunteer.name
        ]
        self.chapter.save()
        self._reload_chapter()
        self.assertFalse(any(b.volunteer == volunteer.name for b in self.chapter.board_members))

    def test_handle_board_member_changes_none_old_doc_noops(self):
        self.manager.handle_board_member_changes(None)  # must not raise
        self.manager.handle_board_member_additions(None)  # new-chapter path: assigns roles
        self.manager.handle_board_member_deletions(None)  # must not raise
