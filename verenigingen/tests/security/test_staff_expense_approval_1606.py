"""Staff expense approval rulings of 2026-10-12 (PR #1606).

Users are built from the roles the SHIPPED Role Profiles grant (fixtures/role_profile.json),
and claims are real Expense Claims for a real Employee, saved and submitted through the
document API as the acting user, so the hooks, the permlevel-1 field check and the
doc-level permission all run for real.

Probe shortcuts, stated: the "national" chapter is set with ``set_single_value`` (the
production reader is the same Single); a claim's ``expense_approver`` is set directly and the
HRMS ``on_update`` hook creates the DocShare, which is the real path.
"""

import json
import time

import frappe
from frappe.utils import today

from verenigingen.permissions import get_expense_claim_permission_query
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.region_fixtures import ensure_test_region
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.utils.constants import Roles


def _roles_shipped_for_profile(profile):
    path = frappe.get_app_path("verenigingen", "fixtures", "role_profile.json")
    with open(path) as f:
        for p in json.load(f):
            if p["name"] == profile:
                return [r["role"] for r in p["roles"] if r["role"] not in ("All", "Guest")]
    raise AssertionError(f"Role Profile {profile} is not shipped")


class StaffExpenseBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        if not frappe.get_meta("Expense Claim").has_field("custom_chapter"):
            # Shipped as fixtures/expense_claim_custom_fields.json: a fresh install (CI) has it,
            # a site restored from an older snapshot only gets it from `bench migrate`.
            self.skipTest("Expense Claim Custom Fields missing on this site: run bench migrate")
        self.token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        self.company = get_eur_test_company()
        self.expense_account = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Expense", "is_group": 0}, "name"
        )
        self.payable_account = frappe.db.get_value(
            "Account", {"company": self.company, "account_type": "Payable", "is_group": 0}, "name"
        )
        self.assertTrue(self.expense_account and self.payable_account, "fixture company lacks accounts")
        self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")
        self.expense_type = self._make_expense_claim_type()

        region = ensure_test_region()
        self.chapter_a = self.create_chapter(chapter_name=f"Exp A {self.token}", region=region)
        self.chapter_b = self.create_chapter(chapter_name=f"Exp B {self.token}", region=region)

        self.staff = self._registered_staff_user("staff")
        self.staff_emp = self._staffexp_employee(self.staff)
        # plain Staff sits on the board of chapter A (a default seat; after #1969 is decided a seated
        # staffer may also get the board role, which these fixtures do not assume either way)
        self.staff_boards(self.chapter_a)

        self.other_staff = self._registered_staff_user("staff2")
        self.other_staff_emp = self._staffexp_employee(self.other_staff)

        self.volunteer_user = self._staffexp_user("Verenigingen Volunteer", "vol")
        self.volunteer_emp = self._staffexp_employee(self.volunteer_user)

        self.treasurer = self._staffexp_user("Verenigingen Treasurer", "treas")
        self.treasurer_emp = self._staffexp_employee(self.treasurer)

        self.nbm = self._staffexp_user("Verenigingen National Board Member", "nbm")
        self.nbm_emp = self._staffexp_employee(self.nbm)

        # The Administrator profile carries no Expense Claim DocPerm of its own (System Manager has
        # none), so the variant that can act on claims gets Expense Approver on top.
        self.admin = self._staffexp_user("Verenigingen Administrator", "adm", extra_roles=("Expense Approver",))
        self.admin_emp = self._staffexp_employee(self.admin)

        # Staff who also holds HR Manager is not "plain" Staff
        self.hr_staff = self._registered_staff_user("hr", extra_roles=("HR Manager",))
        self.hr_staff_emp = self._staffexp_employee(self.hr_staff)

    # ---------------------------------------------------------------- fixtures
    def _make_expense_claim_type(self):
        name = f"T1606 {self.token}"
        doc = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": name,
                "accounts": [{"company": self.company, "default_account": self.expense_account}],
            }
        ).insert()
        self._track_test_document("Expense Claim Type", doc.name, priority=1)
        return doc.name

    def _staffexp_user(self, profile, tag, extra_roles=()):
        return self.create_test_user(
            email=f"x1606-{tag}-{self.token}@test.com", roles=_roles_shipped_for_profile(profile) + list(extra_roles)
        )

    def _staffexp_employee(self, user):
        # Creating a user's volunteer (registered Staff, seated board members) already makes an
        # Employee stub for them via the role-profile sync: use it rather than a duplicate.
        existing = frappe.db.get_value("Employee", {"user_id": user.name}, "name")
        if existing:
            frappe.db.set_value("Employee", existing, "company", self.company)
            self._track_test_document("Employee", existing, priority=2)
            return frappe.get_doc("Employee", existing)
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"E{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": self.company,
                "user_id": user.name,
                # as the app's own Employee creation does: ERPNext's default would add a User
                # Permission pinning the user to this one Employee
                "create_user_permission": 0,
            }
        ).insert()
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _registered_staff_user(self, tag, extra_roles=()):
        """A Staff user registered the production way: the person's volunteer is a member of an
        association-wide Team whose default profile is Verenigingen Staff, and the Team save
        syncs the profile. The user starts with only the Member role; Staff comes from the sync.

        ``extra_roles`` (HR Manager is in no shipped staff profile) go through a Role Profile an
        administrator attaches by hand next to the synced one; the sync removes only profiles it
        granted itself, so the manual one stays."""
        user = self.create_test_user(email=f"x1606-{tag}-{self.token}@test.com", roles=["Verenigingen Member"])
        member = self.create_test_member(first_name="Stf", last_name=tag, email=user.name, user=user.name)
        volunteer = self.create_test_volunteer(member.name)
        team = self._association_staff_team_1922()
        team.append(
            "team_members",
            {"volunteer": volunteer.name, "team_role": "Team Member", "from_date": today(), "status": "Active"},
        )
        team.save()
        have = set(frappe.get_all("Has Role", filters={"parent": user.name, "parenttype": "User"}, pluck="role"))
        self.assertLessEqual(
            set(_roles_shipped_for_profile("Verenigingen Staff")), have, "control: the team made the user Staff"
        )
        if extra_roles:
            self._attach_manual_profile_1922(user, tag, extra_roles)
        user.volunteer_1922 = volunteer
        return user

    def _attach_manual_profile_1922(self, user, tag, roles):
        profile = frappe.get_doc(
            {
                "doctype": "Role Profile",
                "role_profile": f"X1606 {tag} {self.token}",
                "roles": [{"role": r} for r in roles],
            }
        ).insert()
        self._track_test_document("Role Profile", profile.name, priority=1)
        user_doc = frappe.get_doc("User", user.name)
        user_doc.append("role_profiles", {"role_profile": profile.name})
        user_doc.save()
        have = set(frappe.get_all("Has Role", filters={"parent": user.name, "parenttype": "User"}, pluck="role"))
        self.assertLessEqual(
            {*roles, *_roles_shipped_for_profile("Verenigingen Staff")}, have, "control: both profiles' roles"
        )

    def _association_staff_team_1922(self):
        if not getattr(self, "_staff_team_doc", None):
            self._staff_team_doc = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": f"Staff {self.token}",
                    "status": "Active",
                    "team_type": "Project Team",
                    "start_date": today(),
                    "is_association_wide": 1,
                    "default_role_profile": "Verenigingen Staff",
                }
            ).insert()
            self._track_test_document("Team", self._staff_team_doc.name, priority=3)
        return self._staff_team_doc

    def staff_boards(self, chapter):
        """Seat the registered Staff user on a DEFAULT board seat (no role-specific profile)."""
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Exp Fin {self.token}",
                "permissions_level": "Financial",
                "is_active": 1,
            }
        ).insert()
        frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": self.staff.volunteer_1922.name,
                "chapter_role": role.name,
                "from_date": today(),
                "is_active": 1,
            }
        ).insert()

    def seat_holder_without_claim_read(self, tag):
        """(user, chapter): a seat holder who truly lacks the Expense Claim read right, by a real path.

        The chapter's default board profile is mapped to ``Verenigingen Member``, which grants no
        Expense Claim read; seating the user then gives them exactly that profile's roles (the
        flush a Chapter save also runs). Returns the chapter because the seat only counts there.
        """
        chapter = self.create_chapter(chapter_name=f"Exp N {tag} {self.token}", region=ensure_test_region())
        chapter.default_board_role_profile = "Verenigingen Member"
        chapter.save()
        user = self.create_test_user(email=f"x1606-{tag}-{self.token}@test.com", roles=["Verenigingen Member"])
        member = self.create_test_member(first_name="Brd", last_name=tag, email=user.name, user=user.name)
        volunteer = self.create_test_volunteer(member.name)
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"Exp N {tag} {self.token}",
                "permissions_level": "Financial",
                "is_active": 1,
            }
        ).insert()
        frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": today(),
                "is_active": 1,
            }
        ).insert()
        self.assertFalse(
            self.act_as(user, lambda: frappe.has_permission("Expense Claim", "read")),
            "control: the mapped profile really carries no claim read right",
        )
        return user, chapter

    def claim(self, employee, chapter=None, expense_approver=None, submit=False, approval_status="Draft"):
        data = {
            "doctype": "Expense Claim",
            "employee": employee.name,
            "company": self.company,
            "posting_date": today(),
            "currency": "EUR",
            "exchange_rate": 1,
            "payable_account": self.payable_account,
            "cost_center": self.cost_center,
            "approval_status": approval_status,
            "expenses": [
                {
                    "expense_type": self.expense_type,
                    "amount": 12.5,
                    "sanctioned_amount": 12.5,
                    "expense_date": today(),
                    "default_account": self.expense_account,
                    "cost_center": self.cost_center,
                }
            ],
        }
        if chapter:
            data["custom_chapter"] = chapter.name
        if expense_approver:
            data["expense_approver"] = expense_approver.name
        doc = frappe.get_doc(data).insert()
        self._track_test_document("Expense Claim", doc.name, priority=6)
        if submit:
            # HRMS refuses to submit a claim still in Draft: submit it decided, by Administrator.
            doc.approval_status = "Approved"
            doc.submit()
        return doc

    def act_as(self, user, fn):
        original = frappe.session.user
        frappe.set_user(user.name)
        try:
            return fn()
        finally:
            frappe.set_user(original)

    def decide(self, actor, claim_name, status, submit=False):
        """Load the claim as `actor`, set approval_status, save (or submit)."""

        def run():
            doc = frappe.get_doc("Expense Claim", claim_name)
            doc.approval_status = status
            doc.submit() if submit else doc.save()
            return doc

        return self.act_as(actor, run)

    def visible_to(self, user):
        return set(
            self.act_as(user, lambda: frappe.get_list("Expense Claim", pluck="name", limit_page_length=0))
        )

    def can_read(self, user, claim):
        return frappe.has_permission("Expense Claim", "read", doc=claim.name, user=user.name)

    def set_national(self, chapter):
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", chapter.name if chapter else None)


class TestStaffSeesOnlyScopedClaims(StaffExpenseBase):
    """Plain Staff approves as an Expense Approver and is scoped like one."""

    def test_plain_staff_visibility_is_scoped(self):
        own = self.claim(self.staff_emp)
        in_chapter = self.claim(self.volunteer_emp, chapter=self.chapter_a)
        other_chapter = self.claim(self.volunteer_emp, chapter=self.chapter_b)
        unattributed = self.claim(self.volunteer_emp)
        designated = self.claim(self.volunteer_emp, chapter=self.chapter_b, expense_approver=self.staff)
        self.set_national(None)

        visible = self.visible_to(self.staff)

        self.assertIn(own.name, visible)
        self.assertIn(in_chapter.name, visible)
        self.assertIn(designated.name, visible, "the designated approver must see the claim (DocShare)")
        self.assertNotIn(other_chapter.name, visible)
        self.assertNotIn(unattributed.name, visible)
        self.assertTrue(self.can_read(self.staff, in_chapter))
        self.assertTrue(self.can_read(self.staff, designated))
        self.assertFalse(self.can_read(self.staff, other_chapter))
        self.assertFalse(self.can_read(self.staff, unattributed))

    def test_plain_staff_without_board_seat_or_designation_sees_only_own(self):
        # control: a Staff user who sits on no board and is nobody's designated approver
        lonely = self._registered_staff_user("lonely")
        lonely_emp = self._staffexp_employee(lonely)
        own = self.claim(lonely_emp)
        stranger = self.claim(self.volunteer_emp, chapter=self.chapter_a)
        self.set_national(None)

        self.assertEqual(self.visible_to(lonely) & {own.name, stranger.name}, {own.name})

    def test_national_branch_gives_unattributed_claims_only(self):
        unattributed = self.claim(self.volunteer_emp)
        other_chapter = self.claim(self.volunteer_emp, chapter=self.chapter_b)
        self.set_national(self.chapter_a)  # Staff boards chapter A

        visible = self.visible_to(self.staff)

        self.assertIn(unattributed.name, visible)
        self.assertNotIn(other_chapter.name, visible, "the national branch is not 'all'")
        self.assertTrue(self.can_read(self.staff, unattributed))

    def test_wide_roles_still_see_everything(self):
        # control for the split: these carry Verenigingen Staff too and must keep org-wide access.
        claim = self.claim(self.volunteer_emp, chapter=self.chapter_b)
        self.set_national(None)
        for user in (self.treasurer, self.nbm, self.admin, self.hr_staff):
            with self.subTest(user=user.name):
                self.assertEqual(get_expense_claim_permission_query(user.name), "")
                self.assertTrue(self.can_read(user, claim))

    def test_employee_permissions_still_use_the_wide_hr_admin_set(self):
        # HR_ADMIN_ROLES must not have been narrowed globally (Employee permissions use it)
        self.assertIn(Roles.VERENIGINGEN_STAFF, Roles.HR_ADMIN_ROLES)


class TestApprovalRules(StaffExpenseBase):
    def setUp(self):
        super().setUp()
        self.set_national(None)

    # ---- positive controls: the guard must not refuse legitimate approvals
    def test_staff_can_approve_a_non_staff_claim_in_their_chapter(self):
        claim = self.claim(self.volunteer_emp, chapter=self.chapter_a)
        self.decide(self.staff, claim.name, "Approved")
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "approval_status"), "Approved")

    def test_staff_can_approve_a_non_staff_claim_designated_to_them(self):
        claim = self.claim(self.volunteer_emp, chapter=self.chapter_b, expense_approver=self.staff)
        self.decide(self.staff, claim.name, "Approved")
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "approval_status"), "Approved")

    def test_staff_can_reject_a_non_staff_claim(self):
        claim = self.claim(self.volunteer_emp, chapter=self.chapter_a)
        self.decide(self.staff, claim.name, "Rejected")
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "approval_status"), "Rejected")

    # ---- rule 4: plain Staff does not decide another Staff member's claim
    def test_plain_staff_cannot_decide_a_staff_claim_on_save(self):
        for status in ("Approved", "Rejected"):
            with self.subTest(status=status):
                claim = self.claim(self.other_staff_emp, chapter=self.chapter_a)
                with self.assertRaises(frappe.PermissionError) as ctx:
                    self.decide(self.staff, claim.name, status)
                self.assertIn("another Staff member", str(ctx.exception))
                self.assertEqual(
                    frappe.db.get_value("Expense Claim", claim.name, "approval_status"), "Draft"
                )

    def test_plain_staff_cannot_decide_a_staff_claim_on_submit(self):
        claim = self.claim(self.other_staff_emp, chapter=self.chapter_a)
        with self.assertRaises(frappe.PermissionError) as ctx:
            self.decide(self.staff, claim.name, "Approved", submit=True)
        self.assertIn("another Staff member", str(ctx.exception))
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "docstatus"), 0)

    def test_a_submitted_decision_cannot_be_changed_at_all(self):
        # Why the guard hooks validate only: no update-after-submit path exists to guard
        claim = self.claim(self.volunteer_emp, chapter=self.chapter_a, submit=True)
        with self.assertRaises(frappe.UpdateAfterSubmitError):
            self.decide(self.treasurer, claim.name, "Rejected")

    def test_wide_roles_may_decide_a_staff_claim(self):
        # control: Treasurer / NBM / Administrator / Staff+HR Manager carry Staff but are not plain Staff
        for actor in (self.treasurer, self.nbm, self.admin, self.hr_staff):
            with self.subTest(actor=actor.name):
                claim = self.claim(self.other_staff_emp, chapter=self.chapter_a)
                self.decide(actor, claim.name, "Approved")
                self.assertEqual(
                    frappe.db.get_value("Expense Claim", claim.name, "approval_status"), "Approved"
                )

    def test_plain_staff_cannot_decide_a_treasurers_claim(self):
        # a Treasurer user also holds Verenigingen Staff, so "claimant is Staff" covers them
        claim = self.claim(self.treasurer_emp, chapter=self.chapter_a)
        with self.assertRaises(frappe.PermissionError):
            self.decide(self.staff, claim.name, "Approved")

    # ---- rule 5: no self-approval except the Treasurer
    def test_nobody_but_the_treasurer_decides_their_own_claim(self):
        cases = (
            (self.staff, self.staff_emp),
            (self.nbm, self.nbm_emp),
            (self.admin, self.admin_emp),  # System Manager: no exception
            (self.hr_staff, self.hr_staff_emp),
        )
        for actor, emp in cases:
            for submit in (False, True):
                with self.subTest(actor=actor.name, submit=submit):
                    claim = self.claim(emp, chapter=self.chapter_a)
                    with self.assertRaises(frappe.PermissionError) as ctx:
                        self.decide(actor, claim.name, "Approved", submit=submit)
                    self.assertIn("your own expense claim", str(ctx.exception))

    def test_self_rejection_is_refused_too(self):
        claim = self.claim(self.nbm_emp, chapter=self.chapter_a)
        with self.assertRaises(frappe.PermissionError):
            self.decide(self.nbm, claim.name, "Rejected")

    def test_treasurer_may_decide_their_own_claim(self):
        for submit in (False, True):
            with self.subTest(submit=submit):
                claim = self.claim(self.treasurer_emp, chapter=self.chapter_a)
                self.decide(self.treasurer, claim.name, "Approved", submit=submit)
                self.assertEqual(
                    frappe.db.get_value("Expense Claim", claim.name, "approval_status"), "Approved"
                )

    def test_saving_without_changing_the_decision_is_not_refused(self):
        # control: the guard keys on a CHANGE of approval_status, so an unrelated edit by the
        # claimant of an already-decided claim must go through
        claim = self.claim(self.volunteer_emp, expense_approver=self.staff)
        self.decide(self.staff, claim.name, "Approved")

        def edit():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.remark = "unrelated edit"
            doc.save()

        self.act_as(self.volunteer_user, edit)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "remark"), "unrelated edit")

    # ---- two-save bypass: decide a stranger's claim, then re-point it at a Staff employee
    def _decide_then_reassign(self, actor, new_employee, submit=False):
        claim = self.claim(self.volunteer_emp, chapter=self.chapter_a)
        self.decide(actor, claim.name, "Approved")

        def reassign():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.employee = new_employee.name
            doc.submit() if submit else doc.save()

        try:
            self.act_as(actor, reassign)
        finally:
            self.reassigned_to = frappe.db.get_value("Expense Claim", claim.name, "employee")
        return claim

    def test_two_saves_cannot_turn_an_approval_into_a_self_approval(self):
        for submit in (False, True):
            with self.subTest(submit=submit):
                with self.assertRaises(frappe.PermissionError) as ctx:
                    self._decide_then_reassign(self.staff, self.staff_emp, submit=submit)
                self.assertIn("your own expense claim", str(ctx.exception))
                self.assertEqual(self.reassigned_to, self.volunteer_emp.name)

    def test_two_saves_cannot_move_an_approval_to_another_staff_member(self):
        for submit in (False, True):
            with self.subTest(submit=submit):
                with self.assertRaises(frappe.PermissionError) as ctx:
                    self._decide_then_reassign(self.staff, self.other_staff_emp, submit=submit)
                self.assertIn("another Staff member", str(ctx.exception))
                self.assertEqual(self.reassigned_to, self.volunteer_emp.name)

    def test_treasurer_may_reassign_a_decided_claim_to_a_staff_member(self):
        # control: the rule bites plain Staff, not every actor who re-points a decided claim
        self._decide_then_reassign(self.treasurer, self.other_staff_emp)
        self.assertEqual(self.reassigned_to, self.other_staff_emp.name)

    def test_plain_staff_may_still_edit_a_decided_claim_without_changing_its_employee(self):
        claim = self.claim(self.volunteer_emp, chapter=self.chapter_a)
        self.decide(self.staff, claim.name, "Approved")

        def edit():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.remark = "staff note"
            doc.save()

        self.act_as(self.staff, edit)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "remark"), "staff note")
