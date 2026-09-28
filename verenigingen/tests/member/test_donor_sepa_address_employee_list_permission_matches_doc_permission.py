# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
#1543: sibling gap to #1529, found while fixing it. The Desk list-view board
conditions for Donor, SEPA Mandate, Address and Employee still matched
``Chapter Member.status = 'Active'`` with no ``cm.enabled`` check, while their
doc-level ``has_permission`` counterparts (all reached through
``_check_chapter_board_access`` -> ``_is_member_in_chapters``, or -- for
Employee -- the shared ``_employee_board_chapter_condition``) already require
``enabled = 1``. So a source chapter's board still LISTED a Donor / SEPA
Mandate / Address / Employee record belonging to a member who left
(``remove_member(permanent=False)``, which leaves ``enabled=0,
status='Active'``), was terminated (``disable_chapter_memberships_safe``,
``enabled=0, status='Inactive'``), or transferred out -- even though opening
that same record directly was already correctly refused doc-level.

Donor and SEPA Mandate share ``_make_member_linked_permission``'s
``permission_query`` closure (``include_pending=False`` for both, so unlike
Member/Membership in #1529 there is no Pending-application row to admit).
Address has its own, differently-shaped query with the identical gap. Employee
is different in kind, not just in doctype: ``get_employee_permission_query``
and ``has_employee_permission`` both call the SAME shared
``_employee_board_chapter_condition`` helper, so list and doc-level were WRONG
TOGETHER rather than disagreeing -- fixed once, in the shared helper.

Each test drives the underlying Chapter Member row through a REAL production
writer (never ``db.set_value``): ``add_member_to_test_chapter`` for the
positive/cross-chapter controls (mirroring #1529's own baseline fixture),
``chapter_doc.member_manager.remove_member(permanent=False)``,
``disable_chapter_memberships_safe``, and
``ChapterMembershipManager.transfer_member_between_chapters`` (which itself
calls ``remove_member(permanent=False)`` on the source chapter and
``add_member`` on the destination -- #1533's "a transfer counts only for the
destination" policy, at the list/doc-permission layer).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.services.termination.termination_integration import disable_chapter_memberships_safe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _ChapterBoardLinkedRecordListDocAgreement:
    """Mixin: the writer-produced Chapter Member states #1543 covers, applied to
    whatever doctype the concrete subclass links to a Member via
    ``self._record_creator`` (set per subclass in setUp).

    Not a TestCase itself (no unittest/EnhancedTestCase base), so test discovery
    cannot pick it up directly -- only the concrete subclasses below, which mix
    it in alongside EnhancedTestCase, are collected.
    """

    doctype = None  # set by subclass

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter()
        self.other_chapter = self.create_test_chapter()
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")

    # ---- hook for subclasses --------------------------------------------------
    #
    # Each subclass's setUp assigns self._record_creator to one of its OWN,
    # uniquely-named methods (bound method -> instance attribute, not a same-named
    # `def` in this base class) so duplicate_helper_validator.py's name-keyed
    # census -- which cannot tell a legitimate per-doctype override from a
    # copy-pasted duplicate -- does not see four/five defs sharing one name.

    def _make_test1543_member(self, suffix):
        return self.create_test_member(
            first_name="Test1543",
            last_name=f"{suffix}{self.uid}",
            email=f"test1543.{suffix.lower()}.{self.uid}@test.invalid",
            birth_date=add_days(today(), -365 * 30),
        )

    # ---- assertion helpers ------------------------------------------------

    def _listed_for_board_1543(self, name):
        with self.as_user(self.board.user):
            return name in frappe.get_list(self.doctype, filters={"name": name}, pluck="name")

    def _doc_permission_1543(self, name):
        return bool(frappe.has_permission(self.doctype, ptype="read", doc=name, user=self.board.user))

    def _assert_board_record_visibility_1543(self, name, expected, label):
        listed = self._listed_for_board_1543(name)
        doc_ok = self._doc_permission_1543(name)
        self.assertEqual(
            doc_ok,
            expected,
            f"{label}: has_permission({self.doctype}, {name}) expected {expected}, got {doc_ok}",
        )
        self.assertEqual(
            listed,
            expected,
            f"{label}: list-view({self.doctype}, {name}) expected {expected}, got {listed}",
        )
        self.assertEqual(
            listed,
            doc_ok,
            f"{label}: list-view and doc-level DISAGREE for {self.doctype} {name} "
            f"(listed={listed}, doc_permission={doc_ok})",
        )

    def _cm_row(self, member_name, chapter_name):
        return frappe.db.get_value(
            "Chapter Member",
            {"member": member_name, "parent": chapter_name},
            ["enabled", "status"],
            as_dict=True,
        )

    # ---- writer-produced states --------------------------------------------

    def test_positive_control_active_member_of_own_chapter(self):
        """Baseline: a plain Active member of the board's own chapter must stay
        listed and permitted. The fix must not remove existing, legitimate access."""
        member = self._make_test1543_member("Own")
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        record_name = self._record_creator(member.name)

        self._assert_board_record_visibility_1543(
            record_name, True, f"active member's {self.doctype}, own chapter"
        )

    def test_cross_chapter_active_member_not_visible(self):
        """An Active member of a DIFFERENT chapter must stay invisible to this
        board -- the fix must not become globally permissive."""
        member = self._make_test1543_member("Other")
        self.add_member_to_test_chapter(member.name, self.other_chapter.name)
        record_name = self._record_creator(member.name)

        self._assert_board_record_visibility_1543(
            record_name, False, f"active member's {self.doctype}, other chapter"
        )

    def test_remove_member_permanent_false_not_visible(self):
        """remove_member(permanent=False) -- what a member leaving the chapter
        actually does -- leaves enabled=0, status UNCHANGED ('Active'). The board
        that just lost this member must stop seeing their linked record. This is
        the CORE fix: the pre-#1543 query matched status='Active' with no
        `enabled` check, so this exact row stayed listed."""
        member = self._make_test1543_member("Leaving")
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        record_name = self._record_creator(member.name)

        # Sanity: visible before removal (else the test proves nothing).
        self._assert_board_record_visibility_1543(record_name, True, f"{self.doctype} before removal")

        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.member_manager.remove_member(member.name, leave_reason="left", notify=False)

        cm_row = self._cm_row(member.name, self.chapter.name)
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Active"),
            "fixture setup: remove_member(permanent=False) did not leave the expected "
            "enabled=0/status=Active row",
        )

        self._assert_board_record_visibility_1543(
            record_name, False, f"{self.doctype} after remove_member(permanent=False)"
        )

    def test_termination_disables_membership_not_visible(self):
        """disable_chapter_memberships_safe -- the writer termination actually
        calls -- leaves enabled=0, status='Inactive'. Must not be visible."""
        member = self._make_test1543_member("Terminated")
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        record_name = self._record_creator(member.name)

        self._assert_board_record_visibility_1543(record_name, True, f"{self.doctype} before termination")

        disabled_count = disable_chapter_memberships_safe(member.name, today(), "Test termination #1543")
        self.assertEqual(disabled_count, 1, "fixture setup: disable_chapter_memberships_safe disabled 0 rows")

        cm_row = self._cm_row(member.name, self.chapter.name)
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Inactive"),
            "fixture setup: disable_chapter_memberships_safe did not leave the expected "
            "enabled=0/status=Inactive row",
        )

        self._assert_board_record_visibility_1543(record_name, False, f"{self.doctype} after termination")

    def test_transfer_moves_visibility_from_source_to_destination_chapter(self):
        """ChapterMembershipManager.transfer_member_between_chapters -- leave_chapter
        (remove_member(permanent=False) under the hood, enabled=0/status='Active'
        on the SOURCE row) followed by assign_member_to_chapter (add_member,
        a NEW enabled=1/status='Active' row on the DESTINATION). #1533: a transfer
        counts only for the destination -- this is that policy applied to list/doc
        permission rather than to a chapter goal count. The source chapter's board
        must lose access to the member's linked record; the destination
        chapter's own board must gain it."""
        member = self._make_test1543_member("Transferred")
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        record_name = self._record_creator(member.name)

        destination_board = self.create_test_board_member(
            self.other_chapter.name, permissions_level="Admin", first_name="DestBoard"
        )

        self._assert_board_record_visibility_1543(
            record_name, True, f"{self.doctype} before transfer, source board"
        )

        result = ChapterMembershipManager.transfer_member_between_chapters(
            member_id=member.name,
            from_chapter=self.chapter.name,
            to_chapter=self.other_chapter.name,
            reason="Test transfer #1543",
        )
        self.assertTrue(result.get("success"), f"fixture setup: transfer failed: {result}")

        source_row = self._cm_row(member.name, self.chapter.name)
        self.assertEqual(
            (source_row.enabled, source_row.status),
            (0, "Active"),
            "fixture setup: transfer did not leave the expected enabled=0/status=Active "
            "row on the source chapter",
        )
        destination_row = self._cm_row(member.name, self.other_chapter.name)
        self.assertEqual(
            (destination_row.enabled, destination_row.status),
            (1, "Active"),
            "fixture setup: transfer did not leave the expected enabled=1/status=Active "
            "row on the destination chapter",
        )

        self._assert_board_record_visibility_1543(
            record_name, False, f"{self.doctype} after transfer, source board"
        )

        with self.as_user(destination_board.user):
            self.assertIn(
                record_name,
                frappe.get_list(self.doctype, filters={"name": record_name}, pluck="name"),
                f"{self.doctype} after transfer must be visible to the DESTINATION chapter's board",
            )
        self.assertTrue(
            frappe.has_permission(
                self.doctype, ptype="read", doc=record_name, user=destination_board.user
            ),
            f"{self.doctype} after transfer must be doc-permitted for the DESTINATION chapter's board",
        )


class TestDonorBoardListPermissionMatchesDocLevel(
    _ChapterBoardLinkedRecordListDocAgreement, EnhancedTestCase
):
    doctype = "Donor"

    def setUp(self):
        super().setUp()
        self._record_creator = self._make_donor_record_1543

    def _make_donor_record_1543(self, member_name):
        return self.create_test_donor(member=member_name).name


class TestSepaMandateBoardListPermissionMatchesDocLevel(
    _ChapterBoardLinkedRecordListDocAgreement, EnhancedTestCase
):
    doctype = "SEPA Mandate"

    def setUp(self):
        super().setUp()
        self._record_creator = self._make_sepa_mandate_record_1543

    def _make_sepa_mandate_record_1543(self, member_name):
        return self.create_test_sepa_mandate(member_name=member_name).name


class TestAddressBoardListPermissionMatchesDocLevel(
    _ChapterBoardLinkedRecordListDocAgreement, EnhancedTestCase
):
    doctype = "Address"

    def setUp(self):
        super().setUp()
        self._record_creator = self._make_address_record_1543

    def _make_address_record_1543(self, member_name):
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Addr1543 {member_name}",
                "address_type": "Personal",
                "address_line1": "Teststraat 1",
                "city": "Amsterdam",
                "country": "Netherlands",
                "links": [{"link_doctype": "Member", "link_name": member_name}],
            }
        )
        address.insert(ignore_permissions=True)
        self.factory.track_document("Address", address.name, priority=4)
        return address.name


class TestEmployeeBoardListPermissionMatchesDocLevel(
    _ChapterBoardLinkedRecordListDocAgreement, EnhancedTestCase
):
    """Employee is the "wrong together, not divergent" case: both halves call
    _employee_board_chapter_condition, so no test above can distinguish "list and
    doc agree because both are correct" from "list and doc agree because both are
    wrong". test_departed_member_employee_refused_at_doc_level_directly below
    checks the doc-level channel on its own, independent of the shared
    _assert_board_record_visibility_1543 helper, for exactly that reason."""

    doctype = "Employee"

    def setUp(self):
        super().setUp()
        self._record_creator = self._make_employee_record_1543

    def _make_employee_record_1543(self, member_name):
        company = frappe.get_value("Verenigingen Settings", None, "company")
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Emp1543{frappe.generate_hash(length=6)}",
                "last_name": "BoardListDoc",
                "status": "Active",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": today(),
                "company": company,
            }
        )
        emp.insert(ignore_permissions=True)
        self.factory.track_document("Employee", emp.name, priority=4)
        frappe.db.set_value("Member", member_name, "employee", emp.name, update_modified=False)
        return emp.name

    def test_departed_member_employee_refused_at_doc_level_directly(self):
        """Direct frappe.has_permission check, independent of _assert_board_record_visibility_1543's
        list-view half, for the enabled=0/status='Active' state left by
        remove_member(permanent=False). Employee's list and doc-level checks
        share one helper (_employee_board_chapter_condition), so this is the one
        doctype in this file where "list and doc agree" does not by itself prove
        the doc-level channel was ever checked in isolation."""
        member = self._make_test1543_member("EmpDocRefusal")
        self.add_member_to_test_chapter(member.name, self.chapter.name)
        employee_name = self._record_creator(member.name)

        self.assertTrue(
            frappe.has_permission(
                "Employee", ptype="read", doc=employee_name, user=self.board.user
            ),
            "fixture setup: board must be permitted before removal, or the refusal below proves nothing",
        )

        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.member_manager.remove_member(member.name, leave_reason="left", notify=False)

        cm_row = self._cm_row(member.name, self.chapter.name)
        self.assertEqual(
            (cm_row.enabled, cm_row.status),
            (0, "Active"),
            "fixture setup: remove_member(permanent=False) did not leave the expected "
            "enabled=0/status=Active row",
        )

        self.assertFalse(
            frappe.has_permission(
                "Employee", ptype="read", doc=employee_name, user=self.board.user
            ),
            "a departed member's Employee record must be refused at doc level directly, "
            "not only absent from the list",
        )
