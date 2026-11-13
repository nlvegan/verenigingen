"""#2528: an ACTIVE chapter member may FILE a Chapter expense claim; only APPROVING needs a seat.

Maintainer ruling (2026-11-12). The gate is ``validate_expense_claim_chapter_access`` (Expense Claim
validate hook), so every path is exercised for real: the volunteer portal endpoint, a Desk insert
and a REST insert. Membership is a real ``Chapter Member`` row (enabled, status Active) found
through ``Member.user`` only.

Probe shortcuts, stated: ``Chapter Member`` rows are inserted as child rows directly (the Chapter
form flow that writes them is not under test) and their ``status``/``enabled`` are then set with
``frappe.db.set_value`` to stand for the states the real writers leave (Pending from
request_to_join, enabled=0 from remove_member, Inactive from termination);
``Verenigingen Settings.company`` is set with ``set_single_value`` (the production reader is the
same Single).
"""

import json

import frappe
from frappe.utils import today

from verenigingen.templates.pages.volunteer import expenses
from verenigingen.tests.security.test_expense_approval_limits_1651 import LimitBase


class MemberClaimBase(LimitBase):
    def setUp(self):
        super().setUp()
        self.set_limits(self.chapter, 0, 0)
        frappe.db.set_single_value("Verenigingen Settings", "company", self.company)
        self.category = self._expense_category()
        self.user, self.employee, self.member, self.volunteer = self._person("filer")

    def _person(self, tag, link_user=True, extra_roles=()):
        user = self._staffexp_user("Verenigingen Volunteer", tag, extra_roles=extra_roles)
        employee = self._staffexp_employee(user)
        member = self.create_test_member(
            first_name="Fil", last_name=tag, email=user.name, user=user.name if link_user else None
        )
        volunteer = self.create_test_volunteer(member.name)
        frappe.db.set_value("Volunteer", volunteer.name, {"email": user.name, "employee_id": employee.name})
        return user, employee, member, volunteer

    def _expense_category(self):
        cat = frappe.new_doc("Expense Category")
        cat.category_name = f"Travel 2528 {self.token}"
        cat.is_active = 1
        cat.expense_account = self.expense_account
        cat.insert()
        self._track_test_document("Expense Category", cat.name, priority=0)
        claim_type = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": cat.name,
                "accounts": [{"company": self.company, "default_account": self.expense_account}],
            }
        ).insert()
        self._track_test_document("Expense Claim Type", claim_type.name, priority=1)
        return cat.name

    def join(self, member_name, chapter, status="Active", enabled=1):
        row = frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "members",
                "member": member_name,
                "chapter_join_date": today(),
                "enabled": 1,
                "status": "Active",
            }
        ).insert()
        if status != "Active" or not enabled:
            frappe.db.set_value("Chapter Member", row.name, {"status": status, "enabled": enabled})
        return row

    def claim_data(self, employee=None, **fields):
        data = {
            "doctype": "Expense Claim",
            "employee": (employee or self.employee).name,
            "company": self.company,
            "posting_date": today(),
            "currency": "EUR",
            "exchange_rate": 1,
            "payable_account": self.payable_account,
            "cost_center": self.cost_center,
            "approval_status": "Draft",
            "expenses": [
                {
                    "expense_type": self.category,
                    "amount": 5,
                    "sanctioned_amount": 5,
                    "expense_date": today(),
                    "default_account": self.expense_account,
                    "cost_center": self.cost_center,
                }
            ],
        }
        data.update(fields)
        return data

    def file_as(self, user, chapter, **fields):
        employee = frappe.get_doc("Employee", frappe.db.get_value("Employee", {"user_id": user.name}, "name"))
        data = self.claim_data(employee=employee, custom_chapter=chapter.name, **fields)
        return self.act_as(user, lambda: frappe.get_doc(data).insert())

    def portal_file(self, user, volunteer, chapter):
        payload = {
            "description": "Train ticket",
            "amount": 12.5,
            "expense_date": today(),
            "category": self.category,
            "volunteer": volunteer.name,
            "organization_type": "Chapter",
            "chapter": chapter.name,
        }
        return self.act_as(user, lambda: expenses.submit_expense(json.dumps(payload)))


class TestMemberFilesChapterClaim(MemberClaimBase):
    def test_an_active_member_files_through_the_portal_and_keeps_the_claim(self):
        self.join(self.member.name, self.chapter)
        result = self.portal_file(self.user, self.volunteer, self.chapter)
        self.assertTrue(result["success"], result)
        stored = frappe.db.get_value(
            "Expense Claim", result["expense_claim_name"], ["custom_chapter", "approval_status"], as_dict=True
        )
        self.assertEqual((stored.custom_chapter, stored.approval_status), (self.chapter.name, "Draft"))

    def test_an_active_member_files_through_a_desk_and_a_rest_insert(self):
        self.join(self.member.name, self.chapter)
        claim = self.file_as(self.user, self.chapter)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "custom_chapter"), self.chapter.name)
        data = self.claim_data(custom_chapter=self.chapter.name)
        name = self.act_as(self.user, lambda: frappe.client.insert(data))["name"]
        self.assertEqual(frappe.db.get_value("Expense Claim", name, "custom_chapter"), self.chapter.name)

    def test_the_member_can_edit_their_own_undecided_claim(self):
        self.join(self.member.name, self.chapter)
        claim = self.file_as(self.user, self.chapter)

        def edit():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.remark = "edited by the filer"
            doc.save()

        self.act_as(self.user, edit)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "remark"), "edited by the filer")

    def _assert_refused(self, user, chapter):
        with self.assertRaises(frappe.exceptions.ValidationError) as raised:
            self.file_as(user, chapter)
        self.assertIn("chapter", str(raised.exception).lower())

    def test_a_non_member_is_still_refused(self):
        self.join(self.member.name, self.chapter)  # the chapter has an active member: someone else
        outsider, _emp, _member, _vol = self._person("outsider")
        self._assert_refused(outsider, self.chapter)

    def test_a_member_of_a_different_chapter_is_refused(self):
        self.join(self.member.name, self.chapter_a)
        self._assert_refused(self.user, self.chapter)
        # control: the same person files for the chapter they ARE an active member of
        self.assertTrue(self.file_as(self.user, self.chapter_a).name)

    def test_a_row_that_is_not_an_active_membership_does_not_count(self):
        for status, enabled in (("Pending", 1), ("Active", 0), ("Inactive", 0), ("Inactive", 1)):
            with self.subTest(status=status, enabled=enabled):
                user, _emp, member, _vol = self._person(f"st{status[:3]}{enabled}")
                self.join(member.name, self.chapter, status=status, enabled=enabled)
                self._assert_refused(user, self.chapter)

    def test_membership_is_resolved_through_member_user_only(self):
        # a Member whose email equals the User's, but whose `user` link is unset, is not that user
        user, _emp, member, _vol = self._person("nolink", link_user=False)
        self.join(member.name, self.chapter)
        self._assert_refused(user, self.chapter)

    def test_a_member_cannot_file_for_the_chapter_by_editing_in_the_chapter(self):
        self.join(self.member.name, self.chapter_a)
        claim = self.act_as(self.user, lambda: frappe.get_doc(self.claim_data()).insert())

        def edit():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.custom_chapter = self.chapter.name
            doc.save()

        with self.assertRaises(frappe.exceptions.ValidationError):
            self.act_as(self.user, edit)

    def test_a_team_claim_is_still_attributed_and_a_member_forging_another_chapter_is_refused(self):
        team = self.create_test_team(chapter=self.chapter.name)
        self.create_test_team_member(team.name, self.volunteer.name)
        self.join(self.member.name, self.chapter_a)
        claim = self.act_as(self.user, lambda: frappe.get_doc(self.claim_data(custom_team=team.name)).insert())
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "custom_chapter"), self.chapter.name)
        with self.assertRaises(frappe.exceptions.ValidationError):
            self.file_as(self.user, self.national, custom_team=team.name)


class TestMembershipDoesNotGrantApproval(MemberClaimBase):
    """Filing is open to members; deciding a claim is not, through any save or submit path."""

    def setUp(self):
        super().setUp()
        self.join(self.member.name, self.chapter)
        # a member who ALSO holds Expense Approver (the role a designated approver carries)
        self.approver, _emp, self.approver_member, _vol = self._person("apr", extra_roles=("Expense Approver",))
        self.join(self.approver_member.name, self.chapter)
        self.claim = self.file_as(self.user, self.chapter, expense_approver=self.approver.name)

    def _decide(self, actor, status, submit=False):
        return self.decide(actor, self.claim.name, status, submit=submit)

    def _state(self):
        return frappe.db.get_value("Expense Claim", self.claim.name, ["approval_status", "docstatus"], as_dict=True)

    def test_a_plain_member_cannot_approve_reject_or_submit_as_approver(self):
        for status, submit in (("Approved", False), ("Rejected", False), ("Approved", True)):
            with self.subTest(status=status, submit=submit):
                with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                    self._decide(self.approver, status, submit=submit)
                state = self._state()
                self.assertEqual((state.approval_status, state.docstatus), ("Draft", 0))

    def test_the_filer_cannot_approve_their_own_claim(self):
        # Frappe may drop the permlevel-1 field silently instead of raising: the outcome is the
        # claim, not the exception.
        try:
            self._decide(self.user, "Approved")
        except (frappe.PermissionError, frappe.ValidationError):
            pass
        self.assertEqual(self._state().approval_status, "Draft")

    def test_the_gate_refuses_a_member_deciding_in_the_hook_itself(self):
        """The hook, called directly: a decided claim does not get the membership allowance."""
        from verenigingen.utils.account_group_validation_hooks import validate_expense_claim_chapter_access

        for status in ("Approved", "Rejected"):
            doc = frappe.get_doc("Expense Claim", self.claim.name)
            doc.approval_status = status
            original = frappe.session.user
            frappe.set_user(self.approver.name)
            try:
                with self.assertRaises(frappe.exceptions.ValidationError):
                    validate_expense_claim_chapter_access(doc)
            finally:
                frappe.set_user(original)

    def test_a_member_cannot_reopen_or_edit_a_claim_a_seat_decided(self):
        self._decide(self.fin_user, "Approved")
        for field, value in (("approval_status", "Draft"), ("remark", "tampering")):
            with self.subTest(field=field):

                def edit():
                    doc = frappe.get_doc("Expense Claim", self.claim.name)
                    setattr(doc, field, value)
                    doc.save()

                with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                    self.act_as(self.user, edit)
                self.assertEqual(self._state().approval_status, "Approved")

    def test_control_the_financial_seat_still_approves(self):
        self._decide(self.fin_user, "Approved")
        self.assertEqual(self._state().approval_status, "Approved")
