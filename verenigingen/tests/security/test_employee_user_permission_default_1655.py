"""#1655: an approver with a hand-made Employee must still reach the claims they approve.

ERPNext's ``create_user_permission`` default (1) pins the linked user to their own Employee
through User Permissions. HRMS relies on exactly that User Permission to scope Employee-role
users (Leave Application, Expense Claim, Salary Slip, ...), so the default is KEPT. The app's
own Expense Claim permission hooks already decide who may see which claim, so Expense Claim's
``employee`` link ignores User Permissions (fixtures/property_setter.json) and those hooks are
the single scope. Frappe lets a ``has_permission`` hook only DENY, never grant, which is why the
User Permission has to be lifted at the field rather than overridden in the hook.

Real flow: Employees are inserted through the document API as the desk form does (``user_id``
set, ``create_user_permission`` left out so the default of 1 applies). Doc-level reads use
``frappe.has_permission(doc=...)``, list reads use ``frappe.get_list`` as the user, and the
approval is a real save by the approver.

Probe shortcut, stated: the claimants' Employees are built with ``create_user_permission=0``
so only the Employee under test carries the default.
"""

import time

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.security.test_staff_expense_approval_1606 import (
    StaffExpenseBase,
    _roles_shipped_for_profile,
)
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestApproverEmployeeUserPermission1655(EnhancedTestCase):
    def setUp(self):
        super().setUp()
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
        self.expense_type = self._make_claim_type_1655()
        self.treasurer = self.create_test_user(
            email=f"x1655-treas-{self.token}@test.com",
            roles=_roles_shipped_for_profile("Verenigingen Treasurer"),
        )
        self.claimant = self.create_test_user(
            email=f"x1655-claim-{self.token}@test.com", roles=["Verenigingen Volunteer"]
        )
        self.claimant_emp = self._employee_1655(self.claimant, create_user_permission=0)
        self.claim = self._claim_1655(self.claimant_emp)

    # ---------------------------------------------------------------- fixtures
    def _make_claim_type_1655(self):
        doc = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": f"T1655 {self.token}",
                "accounts": [{"company": self.company, "default_account": self.expense_account}],
            }
        ).insert()
        self._track_test_document("Expense Claim Type", doc.name, priority=1)
        return doc.name

    def _employee_1655(self, user, **extra):
        """Inserted like the desk form: only the fields the form asks for, user_id linked."""
        data = {
            "doctype": "Employee",
            "first_name": f"E{frappe.generate_hash(length=5)}",
            "gender": "Other",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2020-01-01",
            "status": "Active",
            "company": self.company,
            "user_id": user.name,
        }
        data.update(extra)
        emp = frappe.get_doc(data).insert()
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _hand_made_employee_1655(self, user):
        """A default hand-made Employee, and proof the default User Permission is really there."""
        emp = self._employee_1655(user)
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "create_user_permission"), 1)
        self.assertIn(
            ("Employee", emp.name),
            [
                (p.allow, p.for_value)
                for p in frappe.get_all("User Permission", filters={"user": user.name}, fields=["allow", "for_value"])
            ],
            "control: the default really pinned the user to their Employee",
        )
        return emp

    def _claim_1655(self, employee):
        doc = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": self.company,
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": self.payable_account,
                "cost_center": self.cost_center,
                "approval_status": "Draft",
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
        ).insert()
        self._track_test_document("Expense Claim", doc.name, priority=6)
        return doc

    def _as_user_1655(self, user, fn):
        original = frappe.session.user
        frappe.set_user(user.name)
        try:
            return fn()
        finally:
            frappe.set_user(original)

    def _can(self, user, claim, ptype="read"):
        return frappe.has_permission("Expense Claim", ptype, doc=claim.name, user=user.name)

    def _listed_as(self, user, doctype="Expense Claim"):
        return set(self._as_user_1655(user, lambda: frappe.get_list(doctype, pluck="name", limit_page_length=0)))

    def _make_leave_application(self, employee, leave_type):
        doc = frappe.get_doc(
            {
                "doctype": "Leave Application",
                "employee": employee.name,
                "leave_type": leave_type,
                "from_date": add_days(today(), 400),
                "to_date": add_days(today(), 400),
                "posting_date": today(),
                "company": self.company,
                "status": "Open",
            }
        ).insert()
        self._track_test_document("Leave Application", doc.name, priority=6)
        return doc

    def _make_leave_type(self):
        doc = frappe.get_doc(
            {
                "doctype": "Leave Type",
                "leave_type_name": f"L1655 {self.token}",
                "allow_negative": 1,
                "include_holiday": 1,
            }
        ).insert()
        self._track_test_document("Leave Type", doc.name, priority=1)
        return doc.name

    # ------------------------------------------------------------------- tests
    def test_the_shipped_fixture_lifts_the_employee_user_permission_on_expense_claim_only(self):
        """The mechanism: only the Expense Claim 'employee' link ignores User Permissions."""
        self.assertEqual(frappe.get_meta("Expense Claim").get_field("employee").ignore_user_permissions, 1)
        for doctype in ("Leave Application", "Salary Slip", "Attendance", "Employee Advance"):
            if frappe.db.exists("DocType", doctype):
                self.assertFalse(
                    frappe.get_meta(doctype).get_field("employee").ignore_user_permissions,
                    f"{doctype} must stay scoped by the Employee User Permission",
                )

    def test_treasurer_with_a_hand_made_employee_reads_another_employees_claim(self):
        self._hand_made_employee_1655(self.treasurer)
        self.assertTrue(self._can(self.treasurer, self.claim))
        self.assertIn(self.claim.name, self._listed_as(self.treasurer))

    def test_treasurer_with_a_hand_made_employee_can_approve_another_employees_claim(self):
        self._hand_made_employee_1655(self.treasurer)
        self.assertTrue(self._can(self.treasurer, self.claim, "write"))

        def approve():
            doc = frappe.get_doc("Expense Claim", self.claim.name)
            doc.approval_status = "Approved"
            doc.save()

        self._as_user_1655(self.treasurer, approve)
        self.assertEqual(frappe.db.get_value("Expense Claim", self.claim.name, "approval_status"), "Approved")

    def test_control_a_plain_employee_role_user_still_sees_only_their_own_claims(self):
        plain = self.create_test_user(email=f"x1655-plain-{self.token}@test.com", roles=["Employee"])
        plain_emp = self._hand_made_employee_1655(plain)
        own = self._claim_1655(plain_emp)
        self.assertFalse(self._can(plain, self.claim), "another employee's claim")
        self.assertTrue(self._can(plain, own), "control: their own claim is readable")
        listed = self._listed_as(plain)
        self.assertIn(own.name, listed)
        self.assertNotIn(self.claim.name, listed)

    def test_control_an_expense_approver_without_a_seat_in_the_claims_chapter_cannot_read_it(self):
        """Approver role alone is not entitlement: the existing chapter rules still decide."""
        approver = self.create_test_user(
            email=f"x1655-appr-{self.token}@test.com", roles=["Employee", "Expense Approver"]
        )
        self._hand_made_employee_1655(approver)
        self.assertFalse(self._can(approver, self.claim))
        self.assertNotIn(self.claim.name, self._listed_as(approver))

    def test_control_a_plain_employee_role_user_still_sees_only_their_own_leave_applications(self):
        """The reviewer's harm: HRMS scopes Leave Application through the Employee User Permission."""
        leave_type = self._make_leave_type()
        plain = self.create_test_user(email=f"x1655-leave-{self.token}@test.com", roles=["Employee"])
        plain_emp = self._hand_made_employee_1655(plain)
        other = self._make_leave_application(self.claimant_emp, leave_type)
        own = self._make_leave_application(plain_emp, leave_type)
        listed = self._listed_as(plain, "Leave Application")
        self.assertIn(own.name, listed, "control: their own leave application is visible")
        self.assertNotIn(other.name, listed)


class TestChapterSeatApproverEmployeeUserPermission1655(StaffExpenseBase):
    """The case the ruling names: a Financial board seat approver, who is NOT a full-access role.

    Staff reaches claims through ``get_user_accessible_chapters`` and the chapter branch of
    ``has_expense_claim_permission``, not through the full-access shortcut the Treasurer takes.
    Probe shortcut, stated: the Staff user's auto-made Employee stub is replaced by an Employee
    inserted as the desk form does (``create_user_permission`` left at ERPNext's default of 1),
    because the stub is built with the permission off; the seat itself and the Staff profile come
    from the real Team and Chapter Board Member flows in ``StaffExpenseBase``.
    """

    def setUp(self):
        super().setUp()
        self.set_national(None)
        self._give_staff_a_hand_made_employee()
        self.claim_a = self.claim(self.volunteer_emp, chapter=self.chapter_a)
        self.claim_b = self.claim(self.volunteer_emp, chapter=self.chapter_b)
        self.claim_none = self.claim(self.volunteer_emp)

    def _give_staff_a_hand_made_employee(self):
        for name in frappe.get_all("Employee", filters={"user_id": self.staff.name}, pluck="name"):
            frappe.db.set_value("Employee", name, "user_id", None)
        for name in frappe.get_all(
            "User Permission", filters={"user": self.staff.name, "allow": "Employee"}, pluck="name"
        ):
            frappe.delete_doc("User Permission", name, force=1)
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"H{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": self.company,
                "user_id": self.staff.name,
            }
        ).insert()
        self._track_test_document("Employee", emp.name, priority=2)
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "create_user_permission"), 1)
        pinned = frappe.get_all(
            "User Permission", filters={"user": self.staff.name, "allow": "Employee"}, pluck="for_value"
        )
        self.assertEqual(pinned, [emp.name], "control: the default really pinned the approver to their Employee")
        self.assertNotIn(
            "Verenigingen Treasurer", frappe.get_roles(self.staff.name), "control: not a full-access role"
        )
        frappe.clear_cache(user=self.staff.name)

    def test_seat_approver_with_an_employee_user_permission_reads_lists_and_approves_a_chapter_claim(self):
        self.assertTrue(self.can_read(self.staff, self.claim_a))
        self.assertIn(self.claim_a.name, self.visible_to(self.staff))
        self.assertTrue(frappe.has_permission("Expense Claim", "write", doc=self.claim_a.name, user=self.staff.name))

        self.decide(self.staff, self.claim_a.name, "Approved")

        self.assertEqual(frappe.db.get_value("Expense Claim", self.claim_a.name, "approval_status"), "Approved")

    def test_control_the_same_approver_still_cannot_reach_another_chapters_claim(self):
        self.assertFalse(self.can_read(self.staff, self.claim_b))
        self.assertNotIn(self.claim_b.name, self.visible_to(self.staff))

    def test_control_the_same_approver_still_cannot_reach_an_unattributed_claim(self):
        self.assertFalse(self.can_read(self.staff, self.claim_none))
        self.assertNotIn(self.claim_none.name, self.visible_to(self.staff))
