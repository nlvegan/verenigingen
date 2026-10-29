"""#1651: the per-chapter expense approval amount limits are enforced.

Maintainer ruling (2026-10-12): limits mainly restrict the LOCAL (chapter) treasurer; a claim
above a seat's limit goes up -- Admin/Basic seat -> the chapter's Financial seat -> the
national treasurer. Blank/zero limit = no limit (coordinator decision, stated in the PR).

Claims are real Expense Claims decided as the acting user through the document API, so the
``validate`` hook, the permlevel-1 field check and doc-level permission all run for real.

Probe shortcuts, stated: the national chapter is set with ``set_single_value`` (the
production reader is the same Single); the chapters' limits are written with
``frappe.db.set_value`` (a config input; the Chapter form is permlevel 1 and the unit under
test is the reader, not the form); a claim's ``expense_approver`` is set directly where the
test is about where the claim goes, which is what HRMS's form does on selecting an approver.
"""

import frappe
from frappe.utils import today

from verenigingen.services.volunteer.expense_approval_limits import (
    get_approval_limit,
    get_chapter_thresholds,
)
from verenigingen.tests.fixtures.region_fixtures import ensure_test_region
from verenigingen.tests.security.test_staff_expense_approval_1606 import StaffExpenseBase


class LimitBase(StaffExpenseBase):
    REGULAR_LIMIT = 100
    FINANCIAL_LIMIT = 500

    def setUp(self):
        super().setUp()
        self.set_national(None)
        self.chapter = self.chapter_b  # no seat of the 1606 fixtures sits here
        self.set_limits(self.chapter, self.REGULAR_LIMIT, self.FINANCIAL_LIMIT)
        self.national = self.create_chapter(chapter_name=f"Exp Nat {self.token}", region=ensure_test_region())
        self.fin_user, self.fin_vol = self.seat_holder("fin", self.chapter, "Financial")
        self.adm_user, self.adm_vol = self.seat_holder("adm1651", self.chapter, "Admin")
        self.claimant_emp = self.volunteer_emp  # a plain volunteer, no seat anywhere

    # ---------------------------------------------------------------- fixtures
    def set_limits(self, chapter, regular, financial):
        frappe.db.set_value(
            "Chapter",
            chapter.name,
            {"board_member_approval_limit": regular, "financial_role_approval_limit": financial},
            update_modified=False,
        )

    def role(self, level):
        doc = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"L1651 {level} {frappe.generate_hash(length=6)}",
                "permissions_level": level,
                "is_active": 1,
            }
        ).insert()
        self._track_test_document("Chapter Role", doc.name, priority=1)
        return doc.name

    def seat_holder(self, tag, chapter, level, extra_roles=()):
        """A user (Volunteer profile + Expense Approver) who holds a ``level`` seat on ``chapter``."""
        user = self._staffexp_user(
            "Verenigingen Volunteer", f"{tag}", extra_roles=("Expense Approver",) + tuple(extra_roles)
        )
        self._staffexp_employee(user)
        member = self.create_test_member(
            first_name="Seat", last_name=tag, email=user.name, user=user.name
        )
        volunteer = self.create_test_volunteer(member.name)
        frappe.db.set_value("Volunteer", volunteer.name, "email", user.name, update_modified=False)
        self.add_seat(volunteer, chapter, level)
        return user, volunteer

    def add_seat(self, volunteer, chapter, level):
        frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": volunteer.name,
                "chapter_role": self.role(level),
                "from_date": today(),
                "is_active": 1,
            }
        ).insert()

    def amount_claim(self, amount, chapter=None, team=None, expense_approver=None, employee=None):
        doc = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": (employee or self.claimant_emp).name,
                "company": self.company,
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": self.payable_account,
                "cost_center": self.cost_center,
                "approval_status": "Draft",
                "custom_chapter": (chapter or self.chapter).name if team is None else None,
                "custom_team": team.name if team else None,
                "expense_approver": expense_approver.name if expense_approver else None,
                "expenses": [
                    {
                        "expense_type": self.expense_type,
                        "amount": amount,
                        "sanctioned_amount": amount,
                        "expense_date": today(),
                        "default_account": self.expense_account,
                        "cost_center": self.cost_center,
                    }
                ],
            }
        ).insert()
        self._track_test_document("Expense Claim", doc.name, priority=6)
        return doc

    def status_of(self, claim):
        return frappe.db.get_value("Expense Claim", claim.name, "approval_status")

    def assert_refused(self, actor, claim, status="Approved", submit=False, fragment="approval limit"):
        with self.assertRaises(frappe.PermissionError) as ctx:
            self.decide(actor, claim.name, status, submit=submit)
        self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(self.status_of(claim), "Draft")
        return str(ctx.exception)


class TestApprovalIsRefusedAboveTheLimit(LimitBase):
    def test_financial_seat_approves_up_to_its_limit(self):
        claim = self.amount_claim(self.FINANCIAL_LIMIT)  # boundary is inclusive
        self.decide(self.fin_user, claim.name, "Approved")
        self.assertEqual(self.status_of(claim), "Approved")

    def test_financial_seat_cannot_approve_above_its_limit_on_save_or_submit(self):
        for submit in (False, True):
            with self.subTest(submit=submit):
                claim = self.amount_claim(self.FINANCIAL_LIMIT + 0.01)
                message = self.assert_refused(self.fin_user, claim, submit=submit)
                self.assertIn("national treasurer", message)
                self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "docstatus"), 0)

    def test_admin_seat_approves_up_to_the_regular_limit_only(self):
        ok = self.amount_claim(self.REGULAR_LIMIT)
        self.decide(self.adm_user, ok.name, "Approved")
        self.assertEqual(self.status_of(ok), "Approved")

        over = self.amount_claim(self.REGULAR_LIMIT + 0.01)
        message = self.assert_refused(self.adm_user, over)
        self.assertIn("financial board member", message)

    def test_the_same_claim_is_approved_by_the_financial_seat(self):
        # control for the refusal above: the claim itself is fine, only the actor's level is not
        claim = self.amount_claim(self.REGULAR_LIMIT + 50)
        self.assert_refused(self.adm_user, claim)
        self.decide(self.fin_user, claim.name, "Approved")
        self.assertEqual(self.status_of(claim), "Approved")

    def test_rejecting_above_the_limit_is_not_refused(self):
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1000)
        self.decide(self.fin_user, claim.name, "Rejected")
        self.assertEqual(self.status_of(claim), "Rejected")

    def test_the_api_route_is_gated_too(self):
        # frappe.client.set_value is what bulk-edit and the REST API call: it saves the doc
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1)

        def call():
            frappe.client.set_value("Expense Claim", claim.name, "approval_status", "Approved")

        with self.assertRaises(frappe.PermissionError):
            self.act_as(self.fin_user, call)
        self.assertEqual(self.status_of(claim), "Draft")

    def test_a_claim_of_a_team_is_judged_by_the_teams_chapter(self):
        # Called on the document: a team claim has no custom_chapter, so the chapter-scoped
        # permission query hides it from a chapter seat before the hook is reached (#1651
        # report: pre-existing, filed separately). What is under test is the chapter lookup.
        from verenigingen.services.volunteer.expense_approval_limits import (
            validate_amount_within_approval_limit,
        )

        team = self.create_test_team(chapter=self.chapter.name)
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1, team=team)
        self.assertFalse(frappe.db.get_value("Expense Claim", claim.name, "custom_chapter"))
        with self.assertRaises(frappe.PermissionError) as ctx:
            validate_amount_within_approval_limit(claim, self.fin_user.name)
        self.assertIn("approval limit", str(ctx.exception))
        # control: the same claim within the limit passes
        claim.total_claimed_amount = claim.total_sanctioned_amount = self.FINANCIAL_LIMIT
        validate_amount_within_approval_limit(claim, self.fin_user.name)

    def test_a_claim_without_chapter_or_team_is_not_limited(self):
        from verenigingen.services.volunteer.expense_approval_limits import (
            validate_amount_within_approval_limit,
        )

        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1)
        claim.custom_chapter = None
        validate_amount_within_approval_limit(claim, self.fin_user.name)  # does not raise


class TestLimitsAreNotBypassedByASecondSave(LimitBase):
    def test_raising_the_amount_of_an_already_approved_draft_is_refused(self):
        claim = self.amount_claim(50)
        self.decide(self.fin_user, claim.name, "Approved")

        def raise_amount():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.expenses[0].amount = self.FINANCIAL_LIMIT + 1
            doc.expenses[0].sanctioned_amount = self.FINANCIAL_LIMIT + 1
            doc.save()

        with self.assertRaises(frappe.PermissionError):
            self.act_as(self.fin_user, raise_amount)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "total_claimed_amount"), 50)

    def test_moving_an_approved_draft_to_a_limited_chapter_is_refused(self):
        free = self.create_chapter(chapter_name=f"Exp Free {self.token}", region=ensure_test_region())
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1, chapter=free)
        self.add_seat(self.fin_vol, free, "Financial")  # no limits set on `free`
        self.decide(self.fin_user, claim.name, "Approved")

        def move():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.custom_chapter = self.chapter.name
            doc.save()

        with self.assertRaises(frappe.PermissionError):
            self.act_as(self.fin_user, move)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "custom_chapter"), free.name)

    def test_an_unrelated_edit_of_an_approved_claim_is_not_refused(self):
        # control: the gate keys on a change of decision / amount / chapter, not on every save
        claim = self.amount_claim(self.FINANCIAL_LIMIT)
        self.decide(self.fin_user, claim.name, "Approved")
        self.set_limits(self.chapter, 10, 20)  # limits fall below the amount afterwards

        def edit():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.remark = "note"
            doc.save()

        self.act_as(self.fin_user, edit)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "remark"), "note")


class TestWhoIsNotLimited(LimitBase):
    def test_the_national_treasurer_approves_above_every_limit(self):
        # self.treasurer carries the shipped Treasurer profile (the national treasurer)
        claim = self.amount_claim(self.FINANCIAL_LIMIT * 10)
        self.decide(self.treasurer, claim.name, "Approved")
        self.assertEqual(self.status_of(claim), "Approved")

    def test_a_national_financial_seat_without_the_treasurer_role_is_unlimited(self):
        # identity is the seat on the national board chapter, not a role profile. (Such a user
        # cannot save a chapter's claim at all without a wide role: chapter-access is separate.)
        self.set_national(self.national)
        nat_fin, _vol = self.seat_holder("nfin", self.national, "Financial")
        self.assertIsNone(get_approval_limit(nat_fin.name, self.chapter.name))

    def test_a_national_admin_seat_is_not_unlimited(self):
        # control: only a FINANCIAL national seat counts as a national approver (#1650); an Admin
        # seat there is bound like any other user without a seat on THIS chapter
        self.set_national(self.national)
        nat_adm, _vol = self.seat_holder("nadm", self.national, "Admin")
        self.assertEqual(get_approval_limit(nat_adm.name, self.chapter.name), self.REGULAR_LIMIT)
        self.set_limits(self.national, 10, 20)
        self.assertEqual(get_approval_limit(nat_adm.name, self.national.name), 10)

    def test_a_seat_on_another_chapter_does_not_unlock_this_one(self):
        # fail closed (ruling 2026-10-29): no seat HERE = bound like a regular seat
        other = self.create_chapter(chapter_name=f"Exp Other {self.token}", region=ensure_test_region())
        stranger, _vol = self.seat_holder("stranger", other, "Financial")
        self.assertEqual(get_approval_limit(stranger.name, self.chapter.name), self.REGULAR_LIMIT)

    def test_a_system_manager_who_is_not_a_verenigingen_administrator_is_unlimited(self):
        sysmgr = self.create_test_user(
            email=f"x1651-sm-{self.token}@test.com", roles=["System Manager", "Expense Approver"]
        )
        self.assertIsNone(get_approval_limit(sysmgr.name, self.chapter.name))

    def test_the_administrator_user_is_unlimited(self):
        self.assertIsNone(get_approval_limit("Administrator", self.chapter.name))

    def test_unset_limits_mean_no_limit(self):
        self.set_limits(self.chapter, 0, 0)
        claim = self.amount_claim(1_000_000)
        self.decide(self.adm_user, claim.name, "Approved")
        self.assertEqual(self.status_of(claim), "Approved")

    def test_only_the_financial_limit_set_also_caps_the_regular_seat(self):
        # a claim must not skip a level: regular seats are capped by the financial limit
        self.set_limits(self.chapter, 0, 300)
        self.assertEqual(get_approval_limit(self.adm_user.name, self.chapter.name), 300)
        self.assertEqual(get_approval_limit(self.fin_user.name, self.chapter.name), 300)

    def test_only_the_regular_limit_set_leaves_the_financial_seat_unlimited(self):
        self.set_limits(self.chapter, 80, 0)
        self.assertEqual(get_approval_limit(self.adm_user.name, self.chapter.name), 80)
        self.assertIsNone(get_approval_limit(self.fin_user.name, self.chapter.name))

    def test_the_regular_limit_is_capped_by_a_lower_financial_limit(self):
        self.set_limits(self.chapter, 900, 300)
        self.assertEqual(get_approval_limit(self.adm_user.name, self.chapter.name), 300)

    def test_an_inactive_seat_is_no_seat_so_the_user_is_bound_as_a_regular_seat(self):
        frappe.db.set_value("Chapter Board Member", {"parent": self.chapter.name, "volunteer": self.adm_vol.name}, "is_active", 0)
        self.assertEqual(get_approval_limit(self.adm_user.name, self.chapter.name), self.REGULAR_LIMIT)

    def test_a_seat_found_by_email_only_is_not_a_seat(self):
        # #1546: identity is Member.user; a Member that merely shares the email grants nothing
        lone = self._staffexp_user("Verenigingen Volunteer", "mailonly", extra_roles=("Expense Approver",))
        member = self.create_test_member(first_name="Mail", last_name="Only", email=lone.name)
        frappe.db.set_value("Member", member.name, "user", None, update_modified=False)
        volunteer = self.create_test_volunteer(member.name)
        frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.chapter.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": volunteer.name,
                "chapter_role": self.role("Financial"),
                "from_date": today(),
                "is_active": 1,
            }
        ).insert()
        self.assertEqual(get_approval_limit(lone.name, self.chapter.name), self.REGULAR_LIMIT)


class TestEveryoneWithoutASeatIsRefused(LimitBase):
    """Ruling 2026-10-29: only the Treasurer role, System Manager and a national Financial seat
    are unlimited. Each wide role below used to be waved through; each is a real save."""

    OVER = 10000

    def test_plain_staff_designated_approver_without_a_seat_is_refused(self):
        staff = self._staffexp_user("Verenigingen Staff", "stf1651", extra_roles=("Expense Approver",))
        self._staffexp_employee(staff)
        # Designated while within the limit, then raised: the DocShare outlives the re-routing
        claim = self.amount_claim(50, expense_approver=staff)
        doc = frappe.get_doc("Expense Claim", claim.name)
        doc.expenses[0].amount = doc.expenses[0].sanctioned_amount = self.OVER
        doc.save()
        self.assert_refused(staff, claim)

    def test_a_financial_seat_who_is_also_a_verenigingen_administrator_is_bound_by_the_seat(self):
        user, _vol = self.seat_holder("favad", self.chapter, "Financial", extra_roles=("Verenigingen Administrator", "System Manager"))
        claim = self.amount_claim(self.OVER)
        self.assert_refused(user, claim)

    def test_national_board_member_profile_without_a_seat_is_refused(self):
        self.assert_refused(self.nbm, self.amount_claim(self.OVER))

    def test_verenigingen_administrator_without_a_seat_is_refused(self):
        self.assert_refused(self.admin, self.amount_claim(self.OVER))

    def test_hr_manager_staff_without_a_seat_is_refused(self):
        self.assert_refused(self.hr_staff, self.amount_claim(self.OVER))

    def test_the_same_users_may_approve_within_the_regular_limit(self):
        # control: the refusal is about the amount, not about who they are
        for actor in (self.nbm, self.admin, self.hr_staff):
            with self.subTest(actor=actor.name):
                claim = self.amount_claim(self.REGULAR_LIMIT)
                self.decide(actor, claim.name, "Approved")
                self.assertEqual(self.status_of(claim), "Approved")

    def test_without_limits_configured_nobody_is_refused(self):
        # fail-closed applies only where a limit exists
        self.set_limits(self.chapter, 0, 0)
        claim = self.amount_claim(self.OVER)
        self.decide(self.nbm, claim.name, "Approved")
        self.assertEqual(self.status_of(claim), "Approved")

    def test_a_system_manager_user_may_approve_above_the_limit(self):
        sysmgr = self.create_test_user(
            email=f"x1651-sm2-{self.token}@test.com", roles=["System Manager", "Expense Approver"]
        )
        self._staffexp_employee(sysmgr)
        claim = self.amount_claim(self.OVER)
        self.decide(sysmgr, claim.name, "Approved")
        self.assertEqual(self.status_of(claim), "Approved")


class TestTaxesCountTowardsTheLimit(LimitBase):
    def tax_claim(self, amount, tax):
        claim = self.amount_claim(amount)
        doc = frappe.get_doc("Expense Claim", claim.name)
        doc.append(
            "taxes",
            {
                "account_head": self.expense_account,
                "description": "tax 1651",
                "tax_amount": tax,
                "cost_center": self.cost_center,
            },
        )
        doc.save()
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "grand_total"), amount + tax)
        return doc

    def test_amount_at_the_limit_plus_tax_is_refused(self):
        claim = self.tax_claim(self.FINANCIAL_LIMIT, 400)
        self.assert_refused(self.fin_user, claim)

    def test_amount_plus_tax_within_the_limit_is_approved(self):
        # control: taxes alone do not make a claim refusable
        claim = self.tax_claim(self.FINANCIAL_LIMIT - 400, 400)
        self.decide(self.fin_user, claim.name, "Approved")
        self.assertEqual(self.status_of(claim), "Approved")

    def test_adding_tax_to_an_approved_claim_is_refused(self):
        claim = self.amount_claim(self.FINANCIAL_LIMIT)
        self.decide(self.fin_user, claim.name, "Approved")

        def add_tax():
            doc = frappe.get_doc("Expense Claim", claim.name)
            doc.append(
                "taxes",
                {"account_head": self.expense_account, "description": "t", "tax_amount": 400, "cost_center": self.cost_center},
            )
            doc.save()

        with self.assertRaises(frappe.PermissionError):
            self.act_as(self.fin_user, add_tax)


class TestClaimsGoUp(LimitBase):
    def setUp(self):
        super().setUp()
        self.set_national(self.national)
        self.treasurer_user, self.treasurer_vol = self.seat_holder(
            "ntr2", self.national, "Financial", extra_roles=("Verenigingen Treasurer",)
        )

    def test_a_claim_above_the_financial_limit_is_assigned_to_the_national_treasurer(self):
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1, expense_approver=self.fin_user)
        self.assertEqual(claim.expense_approver, self.treasurer_user.name)

    def test_a_claim_within_the_limit_stays_with_its_approver(self):
        # control: the routing does not move everything
        claim = self.amount_claim(self.FINANCIAL_LIMIT, expense_approver=self.fin_user)
        self.assertEqual(claim.expense_approver, self.fin_user.name)

    def test_a_claim_above_a_regular_seats_limit_goes_to_the_chapters_financial_seat(self):
        claim = self.amount_claim(self.REGULAR_LIMIT + 1, expense_approver=self.adm_user)
        self.assertEqual(claim.expense_approver, self.fin_user.name)

    def test_a_claim_above_both_limits_from_a_regular_seat_goes_to_the_national_treasurer(self):
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1, expense_approver=self.adm_user)
        self.assertEqual(claim.expense_approver, self.treasurer_user.name)

    def test_the_employees_own_approver_is_judged_when_the_claim_names_none(self):
        # the portal creates claims with no expense_approver: the Employee's one applies
        frappe.db.set_value("Employee", self.claimant_emp.name, "expense_approver", self.fin_user.name)
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1)
        self.assertEqual(claim.expense_approver, self.treasurer_user.name)

    def test_no_national_treasurer_leaves_the_assignment_and_the_gate_still_holds(self):
        self.set_national(None)
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1, expense_approver=self.fin_user)
        self.assertEqual(claim.expense_approver, self.fin_user.name)
        self.assert_refused(self.fin_user, claim)

    def test_a_decided_claim_is_not_rerouted(self):
        claim = self.amount_claim(self.FINANCIAL_LIMIT, expense_approver=self.fin_user)
        self.decide(self.fin_user, claim.name, "Approved")
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "expense_approver"), self.fin_user.name)

    def test_the_escalated_approver_is_notified_not_the_employees_default(self):
        from verenigingen.services.volunteer.expense_handlers import get_designated_approver_email

        frappe.db.set_value("Employee", self.claimant_emp.name, "expense_approver", self.fin_user.name)
        claim = self.amount_claim(self.FINANCIAL_LIMIT + 1)
        employee = frappe.get_doc("Employee", self.claimant_emp.name)
        self.assertEqual(get_designated_approver_email(claim, employee), self.treasurer_user.name)
        # control: a claim that names no approver falls back to the employee's default
        claim.expense_approver = None
        self.assertEqual(get_designated_approver_email(claim, employee), self.fin_user.name)


class TestPortalTellsWhatIsEnforced(LimitBase):
    def test_thresholds_come_from_the_chapter_fields(self):
        thresholds = get_chapter_thresholds()
        self.assertEqual(
            thresholds[self.chapter.name],
            {"regular_limit": self.REGULAR_LIMIT, "financial_limit": self.FINANCIAL_LIMIT},
        )

    def test_a_chapter_without_limits_is_absent(self):
        self.assertNotIn(self.chapter_a.name, get_chapter_thresholds())

    def test_the_portal_function_reads_the_chapters_not_hardcoded_numbers(self):
        from verenigingen.services.volunteer.volunteer_expense_portal_utils import get_approval_thresholds

        self.set_limits(self.chapter, 12, 34)
        self.assertEqual(
            get_approval_thresholds()[self.chapter.name], {"regular_limit": 12, "financial_limit": 34}
        )
