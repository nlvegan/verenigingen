"""#2775: the first-expense path creates the volunteer's Employee but never linked it.

``create_employee_for_approved_volunteer`` inserted an Employee and returned its id without
writing ``Volunteer.employee_id``.  Its caller (``_ensure_employee_exists``) discarded the id,
so ``_create_expense_claim`` filed the claim with ``employee = None`` and the volunteer saw
"Failed to create expense claim" - while an unlinked Employee was left behind, and every retry
created another one.

Probe shortcuts, stated: the Expense Claim Type and Expense Category are created directly (the
portal files the category NAME as the line's type); the claim is filed through the real service
in the Administrator session, not a portal session.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.volunteer.test_volunteer_expense_services_coverage import _ExpenseFixtureMixin
from verenigingen.utils.employee_user_link import create_employee_for_approved_volunteer


class TestFirstExpenseEmployeeLink2775(_ExpenseFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Link2775", last_name="First")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)
        self.chapter = self.ensure_test_chapter("Link2775Chap")
        self._add_chapter_member(self.chapter.name, self.member.name)
        category = self._make_expense_category(name_hint="Link2775")
        claim_type = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": category.name,
                "accounts": [{"company": self._company(), "default_account": self._expense_account()}],
            }
        ).insert()
        self.factory.track_document("Expense Claim Type", claim_type.name, priority=1)
        self.category = category.name

    def _linked_employee(self):
        return frappe.db.get_value("Volunteer", self.volunteer.name, "employee_id")

    def _employee_count(self):
        return frappe.db.count("Employee")

    def _submit_first_expense(self):
        from verenigingen.services.volunteer.expense_submission_service import (
            get_expense_submission_service,
        )

        return get_expense_submission_service(self.volunteer.name).submit_expense(
            {
                "description": "Train ticket",
                "amount": 5.0,
                "expense_date": frappe.utils.today(),
                "organization_type": "Chapter",
                "chapter": self.chapter.name,
                "category": self.category,
            }
        )

    def _track_new_employees(self, before_names):
        for name in set(frappe.get_all("Employee", pluck="name")) - before_names:
            self.factory.track_document("Employee", name, priority=0)

    def test_creating_the_employee_links_the_volunteer(self):
        before = set(frappe.get_all("Employee", pluck="name"))
        employee_id = create_employee_for_approved_volunteer(self.volunteer)
        self._track_new_employees(before)
        self.assertTrue(employee_id)
        self.assertEqual(self._linked_employee(), employee_id)

    def test_first_expense_files_a_claim_for_the_new_employee(self):
        before = set(frappe.get_all("Employee", pluck="name"))
        result = self._submit_first_expense()
        self._track_new_employees(before)
        self.assertTrue(result.success, result.error_message)
        self.assertTrue(result.metadata["employee_created"])
        linked = self._linked_employee()
        self.assertTrue(linked)
        self.assertEqual(result.data.employee, linked)

    def test_a_second_expense_reuses_the_linked_employee(self):
        before = set(frappe.get_all("Employee", pluck="name"))
        first = self._submit_first_expense()
        self._track_new_employees(before)
        self.assertTrue(first.success, first.error_message)
        employees_after_first = self._employee_count()

        second = self._submit_first_expense()
        self.assertTrue(second.success, second.error_message)
        self.assertFalse(second.metadata["employee_created"])
        self.assertEqual(self._employee_count(), employees_after_first)
        self.assertEqual(second.data.employee, first.data.employee)

    def _employee_for_user(self, user_email):
        user = frappe.get_doc(
            {"doctype": "User", "email": user_email, "first_name": "Link2775", "send_welcome_email": 0}
        ).insert()
        self.factory.track_document("User", user.name, priority=0)
        employee = self._make_employee(name_hint="Link2775Emp")
        frappe.db.set_value("Employee", employee.name, "user_id", user.name)
        return user, employee

    def test_an_existing_employee_of_the_members_user_is_linked_not_duplicated(self):
        user, employee = self._employee_for_user(f"link2775-{frappe.generate_hash(length=6)}@test.invalid")
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        self.volunteer.reload()
        before = self._employee_count()

        employee_id = create_employee_for_approved_volunteer(self.volunteer)

        self.assertEqual(employee_id, employee.name)
        self.assertEqual(self._linked_employee(), employee.name)
        self.assertEqual(self._employee_count(), before)

    def test_another_users_employee_is_not_borrowed(self):
        # control: an Employee exists, but for a user who is not this member's. It carries the
        # MEMBER'S OWN name, so a name-based reuse would pick it (#2802 item 4)
        _user, other_employee = self._employee_for_user(
            f"link2775-other-{frappe.generate_hash(length=6)}@test.invalid"
        )
        frappe.db.set_value(
            "Employee", other_employee.name, "employee_name", self.member.full_name, update_modified=False
        )
        own_user, _own = self._employee_for_user(
            f"link2775-own-{frappe.generate_hash(length=6)}@test.invalid"
        )
        # the member's own user has no Employee of its own: detach the one made for it
        frappe.db.set_value("Employee", _own.name, "user_id", None)
        frappe.db.set_value("Member", self.member.name, "user", own_user.name)
        self.volunteer.reload()
        before = set(frappe.get_all("Employee", pluck="name"))

        employee_id = create_employee_for_approved_volunteer(self.volunteer)
        self._track_new_employees(before)

        self.assertNotEqual(employee_id, other_employee.name)
        self.assertEqual(self._linked_employee(), employee_id)
