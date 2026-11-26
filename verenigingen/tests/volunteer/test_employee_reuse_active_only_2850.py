"""#2850: every Employee reuse for a volunteer's user is Active-only, like #2802.

Maintainer ruling (2026-11-19): a Left, Inactive or Suspended Employee is never re-linked
automatically; a rehire is an explicit staff action. Two lookups reused an Employee by
``user_id`` with no status filter:

* the Staff action ``create_employee_for_volunteer`` (services/volunteer/volunteer_employee_service)
* the account pipeline's ``AccountCreationManager._insert_employee_for_created_user``
  (reached by a Member Account Creation Request that asks for the Employee role, for a user that
  already exists)

Both are driven through their real entry points. Probe shortcuts, stated: the User is inserted
directly, and the Employee's ``user_id`` and ``status`` are written with ``db.set_value`` after
a normal insert (the flow that retires an Employee is not driven).
"""

import frappe

from verenigingen.services.member.account.account_creation_manager import AccountCreationManager
from verenigingen.services.volunteer.volunteer_employee_service import create_employee_for_volunteer
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.security.test_volunteer_employee_service_1606 import _shipped_roles

_NOT_REUSABLE = ("Left", "Inactive", "Suspended")


class _ReuseFixture2850:
    def _fixture_2850(self, hint):
        token = frappe.generate_hash(length=6)
        email = f"reuse2850-{hint}-{token}@test.invalid"
        self.user_2850 = self.create_test_user(email=email, roles=_shipped_roles("Verenigingen Volunteer"))
        self.user_2850.append("role_profiles", {"role_profile": "Verenigingen Volunteer"})
        self.user_2850.save()
        self.member_2850 = self.create_test_member(
            first_name="Reuse2850", last_name=hint.title(), email=email, user=email
        )
        self.volunteer_2850 = self.create_test_volunteer(self.member_2850.name)
        frappe.db.set_value("Volunteer", self.volunteer_2850.name, "employee_id", None, update_modified=False)
        self.assertFalse(frappe.db.exists("Employee", {"user_id": email}), "precondition: no Employee")
        return email

    def _employee_2850(self, user, status):
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Emp2850{frappe.generate_hash(length=4)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": frappe.get_single("Verenigingen Settings").company,
                "create_user_permission": 0,
            }
        ).insert()
        self._track_test_document("Employee", employee.name, priority=2)
        # user_id and status by set_value: ERPNext refuses a second Active Employee on one user
        # at insert, but a retired one next to a live one is exactly the state under test
        frappe.db.set_value(
            "Employee", employee.name, {"user_id": user, "status": status}, update_modified=False
        )
        return employee.name

    def _assert_left_is_newer_2850(self, active, left):
        # frappe.db.get_value orders by creation DESC, so an unfiltered lookup returns the
        # NEWEST row: the Left one must be newer for a pick-first lookup to find the wrong row.
        self.assertGreater(
            frappe.db.get_value("Employee", left, "creation"),
            frappe.db.get_value("Employee", active, "creation"),
        )

    def _employees_2850(self, user):
        return set(frappe.get_all("Employee", filters={"user_id": user}, pluck="name"))

    def _track_new_2850(self, user, known):
        for name in self._employees_2850(user) - known:
            self._track_test_document("Employee", name, priority=2)


class TestStaffActionReusesOnlyActive2850(_ReuseFixture2850, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.email = self._fixture_2850("staff")
        self.staff = self.create_test_user(
            email=f"reuse2850-staffer-{frappe.generate_hash(length=6)}@test.invalid",
            roles=_shipped_roles("Verenigingen Staff"),
        )
        self.staff.append("role_profiles", {"role_profile": "Verenigingen Staff"})
        self.staff.save()

    def _act(self):
        original = frappe.session.user
        frappe.set_user(self.staff.name)
        try:
            return create_employee_for_volunteer(self.volunteer_2850.name)
        finally:
            frappe.set_user(original)

    def test_a_not_active_employee_is_not_relinked_and_a_new_one_is_created(self):
        for status in _NOT_REUSABLE:
            with self.subTest(status=status):
                frappe.db.set_value("Volunteer", self.volunteer_2850.name, "employee_id", None)
                old = self._employee_2850(self.email, status)
                known = self._employees_2850(self.email)

                result = self._act()
                self._track_new_2850(self.email, known)

                self.assertTrue(result["created"], result)
                self.assertNotEqual(result["employee"], old)
                self.assertEqual(
                    frappe.db.get_value("Volunteer", self.volunteer_2850.name, "employee_id"),
                    result["employee"],
                )
                self.assertEqual(frappe.db.get_value("Employee", result["employee"], "status"), "Active")
                self.assertEqual(frappe.db.get_value("Employee", old, "status"), status, "left alone")
                frappe.db.delete("Employee", {"name": ("in", list(self._employees_2850(self.email)))})

    def test_an_active_employee_is_still_reused(self):
        active = self._employee_2850(self.email, "Active")

        result = self._act()

        self.assertEqual(result, {"employee": active, "created": False})
        self.assertEqual(self._employees_2850(self.email), {active})

    def test_with_two_employees_the_active_one_is_chosen_not_the_first(self):
        active = self._employee_2850(self.email, "Active")
        left = self._employee_2850(self.email, "Left")
        self._assert_left_is_newer_2850(active, left)

        result = self._act()

        self.assertEqual(result, {"employee": active, "created": False})


class TestAccountPipelineReusesOnlyActive2850(_ReuseFixture2850, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.email = self._fixture_2850("acr")

    def _run_pipeline(self):
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                # Member type: its link phase is the one that writes Volunteer.employee_id
                "request_type": "Member",
                "source_record": self.member_2850.name,
                "email": self.email,
                "full_name": self.member_2850.full_name,
                "role_profile": "Verenigingen Volunteer",
                "requested_roles": [{"role": "Verenigingen Volunteer"}, {"role": "Employee"}],
                "business_justification": "#2850 Employee reuse",
            }
        ).insert()
        AccountCreationManager(request.name).process_complete_pipeline()
        request.reload()
        return request

    def test_a_not_active_employee_is_not_reused_and_a_new_one_is_created(self):
        for status in _NOT_REUSABLE:
            with self.subTest(status=status):
                frappe.db.set_value("Volunteer", self.volunteer_2850.name, "employee_id", None)
                old = self._employee_2850(self.email, status)
                known = self._employees_2850(self.email)

                request = self._run_pipeline()
                self._track_new_2850(self.email, known)

                self.assertEqual(request.created_user, self.email)
                self.assertTrue(request.created_employee)
                self.assertNotEqual(request.created_employee, old)
                self.assertEqual(frappe.db.get_value("Employee", request.created_employee, "status"), "Active")
                self.assertEqual(frappe.db.get_value("Employee", old, "status"), status, "left alone")
                self.assertEqual(
                    frappe.db.get_value("Volunteer", self.volunteer_2850.name, "employee_id"),
                    request.created_employee,
                )
                frappe.db.delete("Account Creation Request", {"name": request.name})
                frappe.db.delete("Employee", {"name": ("in", list(self._employees_2850(self.email)))})

    def test_an_active_employee_is_still_reused(self):
        active = self._employee_2850(self.email, "Active")

        request = self._run_pipeline()

        self.assertEqual(request.created_employee, active)
        self.assertEqual(self._employees_2850(self.email), {active})

    def test_with_two_employees_the_active_one_is_chosen_not_the_first(self):
        active = self._employee_2850(self.email, "Active")
        left = self._employee_2850(self.email, "Left")
        self._assert_left_is_newer_2850(active, left)

        request = self._run_pipeline()

        self.assertEqual(request.created_employee, active)
