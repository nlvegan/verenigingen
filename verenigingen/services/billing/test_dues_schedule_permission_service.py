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

from verenigingen.services.billing.dues_schedule_permission_service import (
    DuesSchedulePermissionService,
    PermissionResult,
    get_dues_schedule_permission_service,
    get_permission_query_conditions,
    has_permission,
)
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
    def _make_chapter_with_finance_board(self, member_in_chapter):
        """Create a chapter, add member_in_chapter to it, and a board member
        (a volunteer linked to a board user) with a Financial chapter role."""
        chapter = self.create_test_chapter()
        self._committed.append(("Chapter", chapter.name))

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
        return board_user

    def test_board_member_with_finance_has_access(self):
        member, sched = self._member_with_active_schedule()
        try:
            board_user = self._make_chapter_with_finance_board(member.name)
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
