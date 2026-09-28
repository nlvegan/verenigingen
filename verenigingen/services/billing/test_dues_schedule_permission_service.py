# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/dues_schedule_permission_service.py

This service is ABOUT permissions, so the tests exercise the REAL permission logic
by creating factory users with concrete roles and passing them as the `user=`
argument to the service methods (the methods accept user explicitly). There is NO
permission escalation: we never call frappe.set_user to bypass checks, never set
ignore_permissions in a test body. The one ignore-permissions branch we DO test is
the service's OWN documented short-circuit (schedule_doc._ignore_permissions), which
is the production behaviour under test.

Real Members / Volunteers / Chapters / Chapter Board Members back the board-finance
path so the chapter resolution is genuine.
"""

import frappe
from frappe.utils import today

from verenigingen.services.billing.dues_schedule_permission_service import (
    DuesSchedulePermissionService,
    PermissionResult,
    get_dues_schedule_permission_service,
    get_permission_query_conditions,
    has_permission,
)
from verenigingen.services.termination.termination_integration import disable_chapter_memberships_safe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


class _BasePermissionTest(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = get_dues_schedule_permission_service()
        self._committed = []

    def tearDown(self):
        order = {
            "Membership Dues Schedule": 0,
            "Chapter Board Member": 1,
            "Membership": 2,
            "Volunteer": 3,
            "Chapter": 4,
            "Chapter Role": 5,
            "Membership Type": 6,
            "User": 7,
            "Member": 8,
        }
        for doctype, name in sorted(self._committed, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def _member_with_active_schedule(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        membership = self.create_test_membership(member_name=member.name)
        self._committed.append(("Membership", membership.name))
        sched_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self._committed.append(("Membership Dues Schedule", sched_name))
        frappe.db.commit()
        sched = frappe.get_doc("Membership Dues Schedule", sched_name)
        # Populate the pre-save image so has_value_changed() behaves as it does
        # during a real validation pass (otherwise it returns True for every field
        # on a freshly fetched doc, masking the permission logic under test).
        sched.load_doc_before_save()
        return member, sched

    def _template_schedule(self):
        """Return a REAL template dues schedule (auto-created by a Membership Type)
        with its pre-save image loaded so is_template is not seen as 'changed'."""
        mt = self.create_test_membership_type()
        self._committed.append(("Membership Type", mt.name))
        tmpl_name = frappe.db.get_value(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": mt.name}, "name"
        )
        if not tmpl_name:
            self.skipTest("Membership Type did not auto-create a template schedule")
        self._committed.append(("Membership Dues Schedule", tmpl_name))
        frappe.db.commit()
        sched = frappe.get_doc("Membership Dues Schedule", tmpl_name)
        sched.load_doc_before_save()
        return sched

    def _user(self, roles):
        u = self.create_test_user_with_roles(roles=roles)
        self._committed.append(("User", u.name))
        return u.name

    def _make_chapter_with_finance_board(self, member_in_chapter=None):
        """Create a chapter, optionally add member_in_chapter to it, and a board
        member (a volunteer linked to a board user) with a Financial chapter role.

        Returns (board_user, chapter_doc) -- the chapter doc is returned (rather than
        just its name) so callers can drive real writers against the target member's
        Chapter Member row afterward (chapter.member_manager.remove_member(...)),
        matching #1562's "real flow, not db.set_value" requirement. member_in_chapter
        is optional so a cross-chapter test can seat a board on a chapter the target
        member never joins.
        """
        chapter = self.create_test_chapter()
        self._committed.append(("Chapter", chapter.name))

        if member_in_chapter:
            # Add the target member to the chapter
            chapter.append("members", {"member": member_in_chapter, "status": "Active"})
            chapter.save()
            frappe.db.commit()

        # Board user -> member -> volunteer
        board_user = self._user([Roles.CHAPTER_BOARD_MEMBER])
        board_member = self.create_test_member()
        self._committed.append(("Member", board_member.name))
        frappe.db.set_value("Member", board_member.name, "user", board_user)
        volunteer = self.create_test_volunteer(member_name=board_member.name)
        self._committed.append(("Volunteer", volunteer.name))

        # Find/create a Financial chapter role
        fin_role = frappe.db.get_value("Chapter Role", {"permissions_level": "Financial"}, "name")
        if not fin_role:
            role_doc = frappe.new_doc("Chapter Role")
            role_doc.role_name = f"Fin-{frappe.generate_hash(length=6)}"
            role_doc.permissions_level = "Financial"
            role_doc.is_active = 1
            role_doc.insert(ignore_permissions=True)
            fin_role = role_doc.name
            self._committed.append(("Chapter Role", fin_role))

        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": fin_role,
                "is_active": 1,
                "from_date": frappe.utils.today(),
            },
        )
        chapter.save()
        frappe.db.commit()
        return board_user, chapter

    def _with_ignore_permissions(self, doc):
        """Set the schedule's documented ignore-permissions short-circuit flag.

        This mutates the doc the same way production callers do before saving with
        permissions bypassed; the test then verifies validate_permissions honours it.
        """
        doc._ignore_permissions = True
        return doc


class TestValidatePermissions(_BasePermissionTest):
    def test_factory_returns_singleton(self):
        self.assertIsInstance(self.service, DuesSchedulePermissionService)

    def test_ignore_permissions_flag_short_circuits(self):
        member, sched = self._member_with_active_schedule()
        sched = self._with_ignore_permissions(sched)
        result = self.service.validate_permissions(sched, user="random@example.com")
        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "admin")

    def test_system_manager_full_access(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.SYSTEM_MANAGER])
        result = self.service.validate_permissions(sched, user=user)
        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "admin")

    def test_verenigingen_admin_full_access(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.VERENIGINGEN_ADMIN])
        result = self.service.validate_permissions(sched, user=user)
        self.assertTrue(result.allowed)

    def test_regular_member_cannot_edit_other_members_schedule(self):
        # schedule belongs to member A; user is a different plain member
        member, sched = self._member_with_active_schedule()
        other_user = self._user([Roles.VERENIGINGEN_MEMBER])
        result = self.service.validate_permissions(sched, user=other_user)
        self.assertFalse(result.allowed)
        self.assertIn("don't have permission", result.reason)


class TestTemplatePermissions(_BasePermissionTest):
    def test_only_admin_edits_template(self):
        sched = self._template_schedule()
        user = self._user([Roles.VERENIGINGEN_MEMBER])
        result = self.service.validate_permissions(sched, user=user)
        self.assertFalse(result.allowed)
        self.assertIn("template", result.reason.lower())

    def test_admin_can_edit_template(self):
        sched = self._template_schedule()
        user = self._user([Roles.VERENIGINGEN_ADMIN])
        result = self.service.validate_permissions(sched, user=user)
        self.assertTrue(result.allowed)

    def test_changing_template_status_blocked(self):
        # Real behaviour: flipping is_template on an existing schedule is rejected.
        member, sched = self._member_with_active_schedule()
        sched.is_template = 1  # was 0 -> genuine change
        user = self._user([Roles.VERENIGINGEN_ADMIN])
        result = self.service.validate_permissions(sched, user=user)
        self.assertFalse(result.allowed)
        self.assertIn("Cannot change template status", result.reason)


class TestCanUserEditSchedule(_BasePermissionTest):
    def test_no_member_assigned_denied(self):
        member, sched = self._member_with_active_schedule()
        sched.member = None
        result = self.service.can_user_edit_schedule(sched, user="x@example.com")
        self.assertFalse(result.allowed)
        self.assertIn("no member assigned", result.reason)

    def test_member_self_edit_allowed(self):
        member, sched = self._member_with_active_schedule()
        # link a user to the member so member_user == user
        user = self._user([Roles.VERENIGINGEN_MEMBER])
        frappe.db.set_value("Member", member.name, "user", user)
        frappe.db.commit()
        result = self.service.can_user_edit_schedule(sched, user=user)
        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "member")

    def test_staff_access(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.VERENIGINGEN_STAFF])
        result = self.service.can_user_edit_schedule(sched, user=user)
        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "staff")

    def test_unrelated_user_denied(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.VERENIGINGEN_MEMBER])
        result = self.service.can_user_edit_schedule(sched, user=user)
        self.assertFalse(result.allowed)


class TestValidateMemberEdit(_BasePermissionTest):
    def test_new_doc_allowed(self):
        sched = frappe.new_doc("Membership Dues Schedule")
        result = self.service.validate_member_edit(sched)
        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "member")

    def test_editing_allowed_field_passes(self):
        member, sched = self._member_with_active_schedule()
        # 'notes' is in the allowed list - changing it is permitted
        sched.notes = "member updated note"
        result = self.service.validate_member_edit(sched)
        self.assertTrue(result.allowed)

    def test_editing_disallowed_field_blocked(self):
        member, sched = self._member_with_active_schedule()
        # billing_frequency is NOT in the member-allowed list
        sched.billing_frequency = "Annual" if sched.billing_frequency != "Annual" else "Monthly"
        result = self.service.validate_member_edit(sched)
        self.assertFalse(result.allowed)
        self.assertIn("cannot modify", result.reason)


class TestChapterBoardWithFinance(_BasePermissionTest):
    def test_board_member_with_finance_has_access(self):
        member, sched = self._member_with_active_schedule()
        try:
            board_user, _chapter = self._make_chapter_with_finance_board(member.name)
        except Exception as e:
            self.skipTest(f"Chapter board fixture unavailable in this site: {e}")
        result = self.service.is_chapter_board_with_finance(member.name, board_user)
        self.assertTrue(result)

    def test_no_chapter_returns_false(self):
        member, sched = self._member_with_active_schedule()
        # member not in any chapter -> False
        self.assertFalse(self.service.is_chapter_board_with_finance(member.name, "nobody@example.com"))

    def test_empty_member_returns_false(self):
        self.assertFalse(self.service.is_chapter_board_with_finance(None, "x@example.com"))


class TestBoardFinanceEnabledCheckAgreesAcrossChannels(_BasePermissionTest):
    """#1562: this service has THREE independent board-finance access checks on
    Membership Dues Schedule, and until this fix all three matched
    ``Chapter Member.status = 'Active'`` with no ``cm.enabled`` check:

    - list side  -- get_permission_query_conditions's board branch (the live
      ``permission_query_conditions`` hook)
    - doc side   -- check_document_permission's board branch (the live
      ``has_permission`` hook)
    - edit/API   -- is_chapter_board_with_finance, called both by
      validate_permissions -> can_user_edit_schedule on save, and by the
      whitelisted get_member_dues_schedule API

    So a chapter treasurer/admin kept LIST, READ and EDIT access to a member's dues
    schedule -- arguably more sensitive than the Donor/SEPA Mandate/Address/Employee
    records #1543 fixed -- after that member left (remove_member(permanent=False),
    which leaves enabled=0, status UNCHANGED at 'Active') or was terminated
    (disable_chapter_memberships_safe, enabled=0, status='Inactive').

    Each test drives the target member's REAL Chapter Member row through a production
    writer, never db.set_value/db_set. self.as_user() below is not a permission
    bypass -- it puts the real board user in frappe.session.user so frappe.get_list's
    list-view path and frappe.has_permission's doc-level path run exactly as they
    would in the Desk for that user, matching this module's own stated approach of
    testing the real permission logic with concrete users and roles.
    """

    def _channels(self, member_name, sched_name, board_user):
        with self.as_user(board_user):
            listed = sched_name in frappe.get_list(
                "Membership Dues Schedule", filters={"name": sched_name}, pluck="name"
            )
        doc_permitted = bool(
            frappe.has_permission("Membership Dues Schedule", ptype="read", doc=sched_name, user=board_user)
        )
        edit_permitted = self.service.is_chapter_board_with_finance(member_name, board_user)
        return listed, doc_permitted, edit_permitted

    def _cm_row_1562(self, member_name, chapter_name):
        return frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "parent": chapter_name},
            ["enabled", "status"],
            as_dict=True,
        )

    def test_positive_control_enabled_active_board_seat_has_access_on_all_channels(self):
        """Control: a genuinely enabled, Active board-finance seat must keep access on
        all three channels. This is the row an overly-broad ("always exclude") fix
        would break, and the row an always-True mutant of the real fix would still
        pass -- it is the OTHER two tests below that a wrong fix fails."""
        member, sched = self._member_with_active_schedule()
        board_user, chapter = self._make_chapter_with_finance_board(member.name)

        cm_row = self._cm_row_1562(member.name, chapter.name)
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (1, "Active"),
            "fixture setup: expected an enabled=1/status=Active Chapter Member row",
        )

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, board_user)
        self.assertTrue(listed, "list-view must show an enabled board-finance seat's dues schedule")
        self.assertTrue(doc_permitted, "has_permission must allow an enabled board-finance seat")
        self.assertTrue(
            edit_permitted, "is_chapter_board_with_finance must allow an enabled board-finance seat"
        )

    def test_cross_chapter_active_member_no_access_on_any_channel(self):
        """A board seat in a DIFFERENT chapter than the member must not gain access
        on any channel -- the fix must not become globally permissive."""
        member, sched = self._member_with_active_schedule()
        other_chapter = self.create_test_chapter()
        self._committed.append(("Chapter", other_chapter.name))
        other_chapter.append("members", {"member": member.name, "status": "Active"})
        other_chapter.save()

        board_user, _board_chapter = self._make_chapter_with_finance_board()

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, board_user)
        self.assertFalse(listed, "list-view must not show a different chapter's member")
        self.assertFalse(doc_permitted, "has_permission must refuse a different chapter's member")
        self.assertFalse(
            edit_permitted, "is_chapter_board_with_finance must refuse a different chapter's member"
        )

    def test_remove_member_permanent_false_loses_access_on_all_channels(self):
        """remove_member(permanent=False) -- what a member leaving the chapter
        actually does -- leaves enabled=0, status UNCHANGED ('Active'). The board
        that just lost this member must lose list, doc and edit access. This is the
        CORE fix: the pre-#1562 checks matched status='Active' with no enabled
        check, so this exact row stayed permitted on all three channels."""
        member, sched = self._member_with_active_schedule()
        board_user, chapter = self._make_chapter_with_finance_board(member.name)

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, board_user)
        self.assertTrue(
            listed and doc_permitted and edit_permitted,
            "fixture setup: board must have access before removal, or the refusal below proves nothing",
        )

        chapter.member_manager.remove_member(member.name, leave_reason="left", notify=False)

        cm_row = self._cm_row_1562(member.name, chapter.name)
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Active"),
            "fixture setup: remove_member(permanent=False) did not leave the expected "
            "enabled=0/status=Active row",
        )

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, board_user)
        self.assertFalse(listed, "list-view must stop showing a departed member's dues schedule")
        self.assertFalse(doc_permitted, "has_permission must refuse a departed member's dues schedule")
        self.assertFalse(edit_permitted, "is_chapter_board_with_finance must refuse a departed member")

    def test_termination_disables_membership_loses_access_on_all_channels(self):
        """disable_chapter_memberships_safe -- the writer termination actually calls
        -- leaves enabled=0, status='Inactive'. Must lose list, doc and edit access."""
        member, sched = self._member_with_active_schedule()
        board_user, chapter = self._make_chapter_with_finance_board(member.name)

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, board_user)
        self.assertTrue(
            listed and doc_permitted and edit_permitted,
            "fixture setup: board must have access before termination, or the refusal below proves nothing",
        )

        disabled_count = disable_chapter_memberships_safe(member.name, today(), "Test termination #1562")
        self.assertEqual(disabled_count, 1, "fixture setup: disable_chapter_memberships_safe disabled 0 rows")

        cm_row = self._cm_row_1562(member.name, chapter.name)
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Inactive"),
            "fixture setup: disable_chapter_memberships_safe did not leave the expected "
            "enabled=0/status=Inactive row",
        )

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, board_user)
        self.assertFalse(listed, "list-view must stop showing a terminated member's dues schedule")
        self.assertFalse(doc_permitted, "has_permission must refuse a terminated member's dues schedule")
        self.assertFalse(edit_permitted, "is_chapter_board_with_finance must refuse a terminated member")

    def test_transfer_moves_access_from_source_to_destination_board(self):
        """ChapterMembershipManager.transfer_member_between_chapters -- leave_chapter
        (remove_member(permanent=False) under the hood, enabled=0/status='Active' on
        the SOURCE row) followed by assign_member_to_chapter (add_member, a NEW
        enabled=1/status='Active' row on the DESTINATION). #1533: a transfer counts
        only for the destination -- applied here to list/doc/edit permission rather
        than a chapter goal count. The source chapter's board must lose access on all
        three channels; the destination chapter's own board must gain it."""
        from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager

        member, sched = self._member_with_active_schedule()
        source_board_user, source_chapter = self._make_chapter_with_finance_board(member.name)
        dest_board_user, dest_chapter = self._make_chapter_with_finance_board()

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, source_board_user)
        self.assertTrue(
            listed and doc_permitted and edit_permitted,
            "fixture setup: source board must have access before transfer, or the loss below proves nothing",
        )

        result = ChapterMembershipManager.transfer_member_between_chapters(
            member_id=member.name,
            from_chapter=source_chapter.name,
            to_chapter=dest_chapter.name,
            reason="Test transfer #1562",
        )
        self.assertTrue(result.get("success"), f"fixture setup: transfer failed: {result}")

        source_row = self._cm_row_1562(member.name, source_chapter.name)
        self.assertEqual(
            (source_row.enabled, source_row.status),
            (0, "Active"),
            "fixture setup: transfer did not leave the expected enabled=0/status=Active row "
            "on the source chapter",
        )
        dest_row = self._cm_row_1562(member.name, dest_chapter.name)
        self.assertEqual(
            (dest_row.enabled, dest_row.status),
            (1, "Active"),
            "fixture setup: transfer did not leave the expected enabled=1/status=Active row "
            "on the destination chapter",
        )

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, source_board_user)
        self.assertFalse(listed, "source board's list-view must lose the transferred member's schedule")
        self.assertFalse(doc_permitted, "source board's has_permission must refuse after transfer")
        self.assertFalse(
            edit_permitted, "source board's is_chapter_board_with_finance must refuse after transfer"
        )

        listed, doc_permitted, edit_permitted = self._channels(member.name, sched.name, dest_board_user)
        self.assertTrue(listed, "destination board's list-view must show the transferred member's schedule")
        self.assertTrue(doc_permitted, "destination board's has_permission must allow after transfer")
        self.assertTrue(
            edit_permitted, "destination board's is_chapter_board_with_finance must allow after transfer"
        )


class TestCheckDocumentPermission(_BasePermissionTest):
    def test_system_manager_reads_anything(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.SYSTEM_MANAGER])
        self.assertTrue(self.service.check_document_permission(sched, user=user))

    def test_staff_reads_anything(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.VERENIGINGEN_STAFF])
        self.assertTrue(self.service.check_document_permission(sched, user=user))

    def test_template_visible_to_plain_member(self):
        member, sched = self._member_with_active_schedule()
        sched.is_template = 1
        user = self._user([Roles.VERENIGINGEN_MEMBER])
        self.assertTrue(self.service.check_document_permission(sched, user=user))

    def test_owner_member_can_read_own(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.VERENIGINGEN_MEMBER])
        frappe.db.set_value("Member", member.name, "user", user)
        frappe.db.commit()
        self.assertTrue(self.service.check_document_permission(sched, user=user))

    def test_unrelated_member_denied_nontemplate(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.VERENIGINGEN_MEMBER])
        self.assertFalse(self.service.check_document_permission(sched, user=user))

    def test_module_has_permission_hook_delegates(self):
        member, sched = self._member_with_active_schedule()
        user = self._user([Roles.SYSTEM_MANAGER])
        self.assertTrue(has_permission(sched, user=user))


class TestPermissionQueryConditions(_BasePermissionTest):
    def test_system_manager_no_restrictions(self):
        user = self._user([Roles.SYSTEM_MANAGER])
        self.assertEqual(self.service.get_permission_query_conditions(user=user), "")

    def test_staff_no_restrictions(self):
        user = self._user([Roles.VERENIGINGEN_STAFF])
        self.assertEqual(self.service.get_permission_query_conditions(user=user), "")

    def test_member_restricted_to_templates_and_own(self):
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        user = self._user([Roles.VERENIGINGEN_MEMBER])
        frappe.db.set_value("Member", member.name, "user", user)
        frappe.db.commit()
        cond = self.service.get_permission_query_conditions(user=user)
        self.assertIn("is_template = 1", cond)
        # Their own member name is escaped into the condition
        self.assertIn(frappe.db.escape(member.name), cond)

    def test_user_without_member_sees_only_templates(self):
        user = self._user([Roles.VERENIGINGEN_MEMBER])  # not linked to any Member
        cond = self.service.get_permission_query_conditions(user=user)
        self.assertEqual(cond, "`tabMembership Dues Schedule`.is_template = 1")

    def test_module_query_conditions_hook_delegates(self):
        user = self._user([Roles.SYSTEM_MANAGER])
        self.assertEqual(get_permission_query_conditions(user=user), "")


class TestPermissionResult(EnhancedTestCase):
    def test_bool_and_aliases(self):
        ok = PermissionResult(True, "yes", "admin")
        self.assertTrue(bool(ok))
        self.assertTrue(ok.success)
        self.assertIsNone(ok.error_message)

        no = PermissionResult(False, "no")
        self.assertFalse(bool(no))
        self.assertFalse(no.success)
        self.assertEqual(no.error_message, "no")
        self.assertEqual(no.permission_level, "none")
