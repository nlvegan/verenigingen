"""Volunteer.employee_id may not be repointed by a Volunteer writer (#2752).

`read_only` on the field is a form hint only; a server-side save or a REST PUT ignores it.
Users are built from the roles the SHIPPED Role Profiles grant (the board member through
`create_test_board_member`, staff through `create_test_user` + the shipped profile roles).
"""

import json
import time

import frappe

from verenigingen.services.member.account.account_creation_manager import AccountCreationManager
from verenigingen.services.volunteer.volunteer_employee_service import create_employee_for_volunteer
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _shipped_roles_2752(profile):
    path = frappe.get_app_path("verenigingen", "fixtures", "role_profile.json")
    with open(path) as f:
        for p in json.load(f):
            if p["name"] == profile:
                return [r["role"] for r in p["roles"]]
    raise AssertionError(f"Role Profile {profile} is not shipped")


class TestVolunteerEmployeeIdImmutable2752(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        chapter = self.create_test_chapter()
        self.board = self.create_test_board_member(chapter.name)
        # the board profile assignment may already have created the user's own Employee
        self.own_employee = frappe.db.get_value(
            "Employee", {"user_id": self.board.user}, "name"
        ) or self._make_employee_2752(user_id=self.board.user, tag="own")
        # the victim: another person's volunteer with their real Employee
        victim_member = self.create_test_member(
            first_name="Victim", last_name=f"V{self.token[-6:]}", email=f"victim2752-{self.token}@example.com"
        )
        victim_user = self.create_test_user(
            email=f"victim2752-{self.token}@example.com", roles=["Verenigingen Member"]
        )
        self.victim_employee = self._make_employee_2752(user_id=victim_user.name, tag="victim")
        self.victim_volunteer = self.create_test_volunteer(victim_member.name)
        frappe.db.set_value(
            "Volunteer", self.board.volunteer, "employee_id", self.own_employee, update_modified=False
        )
        self.staff = self._staff_user_2752()

    def _make_employee_2752(self, user_id, tag):
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"E2752{tag}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": frappe.get_single("Verenigingen Settings").company,
                "user_id": user_id,
                "create_user_permission": 0,
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Employee", employee.name, priority=2)
        return employee.name

    def _staff_user_2752(self):
        profile = "Verenigingen Staff"
        user = self.create_test_user(
            email=f"staff2752-{self.token}@test.com", roles=_shipped_roles_2752(profile)
        )
        user.append("role_profiles", {"role_profile": profile})
        user.save()
        return user

    def _set_employee_as_2752(self, user, volunteer_name, employee):
        original = frappe.session.user
        frappe.set_user(user)
        try:
            doc = frappe.get_doc("Volunteer", volunteer_name)
            doc.employee_id = employee
            doc.save()
        finally:
            frappe.set_user(original)

    def _stored_2752(self, volunteer_name):
        return frappe.db.get_value("Volunteer", volunteer_name, "employee_id")

    def test_board_member_cannot_repoint_to_another_persons_employee(self):
        with self.assertRaises(frappe.PermissionError):
            self._set_employee_as_2752(self.board.user, self.board.volunteer, self.victim_employee)
        self.assertEqual(self._stored_2752(self.board.volunteer), self.own_employee)

    def test_board_member_cannot_clear_it(self):
        with self.assertRaises(frappe.PermissionError):
            self._set_employee_as_2752(self.board.user, self.board.volunteer, None)
        self.assertEqual(self._stored_2752(self.board.volunteer), self.own_employee)

    def test_board_member_cannot_set_an_empty_field_to_another_persons_employee(self):
        frappe.db.set_value("Volunteer", self.board.volunteer, "employee_id", None, update_modified=False)
        with self.assertRaises(frappe.PermissionError):
            self._set_employee_as_2752(self.board.user, self.board.volunteer, self.victim_employee)
        self.assertFalse(self._stored_2752(self.board.volunteer))

    def test_board_member_can_set_an_empty_field_to_their_own_employee(self):
        frappe.db.set_value("Volunteer", self.board.volunteer, "employee_id", None, update_modified=False)
        self._set_employee_as_2752(self.board.user, self.board.volunteer, self.own_employee)
        self.assertEqual(self._stored_2752(self.board.volunteer), self.own_employee)

    def test_board_member_can_still_save_other_fields(self):
        original = frappe.session.user
        frappe.set_user(self.board.user)
        try:
            doc = frappe.get_doc("Volunteer", self.board.volunteer)
            doc.google_workspace_id = "gw-2752"
            doc.save()
        finally:
            frappe.set_user(original)
        self.assertEqual(
            frappe.db.get_value("Volunteer", self.board.volunteer, "google_workspace_id"), "gw-2752"
        )
        self.assertEqual(self._stored_2752(self.board.volunteer), self.own_employee)

    def test_staff_can_change_it(self):
        self._set_employee_as_2752(self.staff.name, self.board.volunteer, self.victim_employee)
        self.assertEqual(self._stored_2752(self.board.volunteer), self.victim_employee)

    def test_staff_can_clear_it(self):
        self._set_employee_as_2752(self.staff.name, self.board.volunteer, None)
        self.assertFalse(self._stored_2752(self.board.volunteer))

    def test_staff_service_action_still_links_the_employee(self):
        """Real flow: volunteer_employee_service.create_employee_for_volunteer as staff."""
        frappe.db.set_value("Volunteer", self.board.volunteer, "employee_id", None, update_modified=False)
        frappe.db.set_value("Employee", self.own_employee, "user_id", None, update_modified=False)
        original = frappe.session.user
        frappe.set_user(self.staff.name)
        try:
            result = create_employee_for_volunteer(self.board.volunteer)
        finally:
            frappe.set_user(original)
        self._track_test_document("Employee", result["employee"], priority=2)
        self.assertEqual(self._stored_2752(self.board.volunteer), result["employee"])

    def test_account_creation_pipeline_still_links_the_employee(self):
        """Real flow: AccountCreationManager.process_complete_pipeline writes employee_id."""
        member = self.create_test_member(
            first_name="Pipe",
            last_name=f"P{self.token[-6:]}",
            email=f"pipe2752-{self.token}@test.invalid",
            status="Active",
            birth_date="1990-01-01",
        )
        volunteer = self.create_test_volunteer(member_name=member.name, email=member.email)
        self.assertFalse(self._stored_2752(volunteer.name))
        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member", create_employee_record=1
        )
        AccountCreationManager(request.name).process_complete_pipeline()
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertTrue(request.created_employee, "precondition: the pipeline created an Employee")
        self._track_test_document("Employee", request.created_employee, priority=2)
        self.assertEqual(self._stored_2752(volunteer.name), request.created_employee)

    def test_rest_style_set_value_is_refused_for_a_board_member(self):
        """`frappe.client.set_value` is the whitelisted route behind a REST PUT/desk edit."""
        from frappe.client import set_value

        original = frappe.session.user
        frappe.set_user(self.board.user)
        try:
            with self.assertRaises(frappe.PermissionError):
                set_value("Volunteer", self.board.volunteer, "employee_id", self.victim_employee)
        finally:
            frappe.set_user(original)
        self.assertEqual(self._stored_2752(self.board.volunteer), self.own_employee)
