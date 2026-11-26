"""#2791: ``create_user_for_volunteer`` never wrote ``Volunteer.user``.

The Volunteer portal pages, the termination flow and ``member_portal_utils`` all resolve a
volunteer with ``Volunteer.user == <session user>``. The employee flows created (or found) a
User for the volunteer and only handed its name to ``update_employee_with_user``, so the
Volunteer stayed unlinked and no consumer could find it.

Probe shortcuts, stated: the volunteer is created with the account-creation hook skipped
(``skip_volunteer_account_creation``) so its ``user`` starts empty and Member.user stays empty;
the flows themselves (``create_employee_for_approved_volunteer``,
``enhanced_create_minimal_employee``) are driven for real as Administrator.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.employee_user_link import (
    create_employee_for_approved_volunteer,
    enhanced_create_minimal_employee,
)


class TestVolunteerUserBackref2791(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._skip_2791 = frappe.flags.get("skip_volunteer_account_creation")
        frappe.flags.skip_volunteer_account_creation = True
        self.member = self.create_test_member(first_name="Backref2791", last_name="Vol")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)
        self.email_2791 = f"backref2791-{frappe.generate_hash(length=6)}@test.invalid"
        frappe.db.set_value("Volunteer", self.volunteer.name, "email", self.email_2791, update_modified=False)
        frappe.db.set_value("Volunteer", self.volunteer.name, "user", None, update_modified=False)
        frappe.db.set_value("Member", self.member.name, "user", None, update_modified=False)
        self.volunteer.reload()

    def tearDown(self):
        frappe.flags.skip_volunteer_account_creation = self._skip_2791
        super().tearDown()

    def _track_2791(self, employee_id, user_name=None):
        if employee_id:
            self.factory.track_document("Employee", employee_id, priority=0)
        user_name = user_name or frappe.db.get_value("User", {"email": self.email_2791}, "name")
        if user_name:
            self.factory.track_document("User", user_name, priority=0)

    def _volunteer_user_2791(self):
        return frappe.db.get_value("Volunteer", self.volunteer.name, "user")

    def test_the_approval_flow_links_the_new_user_to_the_volunteer(self):
        employee_id = create_employee_for_approved_volunteer(self.volunteer)
        self._track_2791(employee_id)
        user = frappe.db.get_value("User", {"email": self.email_2791}, "name")
        self.assertTrue(user, "the flow should have created a User for the volunteer")
        self.assertEqual(frappe.db.get_value("Employee", employee_id, "user_id"), user)
        self.assertEqual(self._volunteer_user_2791(), user)
        self.assertEqual(self.volunteer.user, user)

    def test_an_existing_user_with_the_volunteers_email_is_linked(self):
        user = frappe.get_doc(
            {"doctype": "User", "email": self.email_2791, "first_name": "Backref2791", "send_welcome_email": 0}
        ).insert()
        self.factory.track_document("User", user.name, priority=0)
        employee_id = enhanced_create_minimal_employee(self.volunteer)
        self._track_2791(employee_id, user.name)
        self.assertEqual(self._volunteer_user_2791(), user.name)

    def test_a_different_existing_volunteer_user_is_not_overwritten(self):
        own = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"backref2791-own-{frappe.generate_hash(length=6)}@test.invalid",
                "first_name": "Own2791",
                "send_welcome_email": 0,
            }
        ).insert()
        self.factory.track_document("User", own.name, priority=0)
        frappe.db.set_value("Volunteer", self.volunteer.name, "user", own.name, update_modified=False)
        self.volunteer.reload()
        employee_id = create_employee_for_approved_volunteer(self.volunteer)
        self._track_2791(employee_id)
        # control: the email's User was created, so the flow really offered a different user
        self.assertTrue(frappe.db.exists("User", {"email": self.email_2791}))
        self.assertEqual(self._volunteer_user_2791(), own.name)
        self.assertEqual(self.volunteer.user, own.name)

    def test_a_volunteer_without_email_stays_unlinked(self):
        frappe.db.set_value("Volunteer", self.volunteer.name, "email", None, update_modified=False)
        self.volunteer.reload()
        employee_id = create_employee_for_approved_volunteer(self.volunteer)
        self._track_2791(employee_id)
        self.assertFalse(self._volunteer_user_2791())
