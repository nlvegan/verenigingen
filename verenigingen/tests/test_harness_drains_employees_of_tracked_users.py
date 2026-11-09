"""The harness drain deletes the stub Employees a test caused for the Users it tracks (#1886).

`_ensure_employee_for_profile()` inserts an Employee for a User whose role profile
carries the Employee role. When a test then commits, that Employee outlives the
rollback, and the tracked User is deleted out from under it: a dangling
`Employee.user_id` that later breaks HRMS (`LinkValidationError: Could not find From
User`, #1689/#1694). Four modules each carried a tearDown copy of the cure. The cure
now lives in `VereningingenTestCase.tearDown`, and these tests pin its two edges:

- an Employee the test CAUSED (committed after setUp) for a tracked User goes;
- an Employee that already existed before the test, or belongs to a User the test
  does not track, is NOT the test's to delete.

The assertions run in tearDown AFTER the drain, because the drain is the code under
test. Each case seeds committed rows, so the wrong behaviour has a real row to find.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


def _insert_user_1886(email):
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": "Harness1886",
            "enabled": 1,
            "send_welcome_email": 0,
        }
    )
    user.insert(ignore_permissions=True)
    return user


def _insert_employee_1886(user_id, company):
    emp = frappe.new_doc("Employee")
    emp.first_name = "Harness1886"
    emp.employee_name = "Harness1886"
    emp.company = company
    emp.user_id = user_id
    emp.status = "Active"
    emp.gender = "Prefer not to say"
    emp.date_of_birth = "1990-01-01"
    emp.date_of_joining = frappe.utils.today()
    emp.create_user_permission = 0
    emp.insert(ignore_permissions=True)
    return emp.name


class TestHarnessDrainsEmployeesOfTrackedUsers(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A User + Employee that exist BEFORE any test's setUp, committed.
        cls._old_email = f"h1886.old.{frappe.generate_hash(length=8)}@test.invalid"
        _insert_user_1886(cls._old_email)
        cls._old_employee = _insert_employee_1886(cls._old_email, cls.settings_company)
        cls._create_committed_1886()

    @staticmethod
    def _create_committed_1886():
        """Persist seeded rows: the drain under test exists for what a commit leaves behind."""
        frappe.db.commit()

    @staticmethod
    def _cleanup_committed_1886():
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        if frappe.db.exists("Employee", cls._old_employee):
            frappe.delete_doc("Employee", cls._old_employee, force=True)
        if frappe.db.exists("User", cls._old_email):
            frappe.delete_doc("User", cls._old_email, force=True)
        cls._cleanup_committed_1886()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._must_be_gone = []
        self._must_survive = []

    def tearDown(self):
        super().tearDown()
        try:
            gone_but_present = [e for e in self._must_be_gone if frappe.db.exists("Employee", e)]
            survivors_missing = [e for e in self._must_survive if not frappe.db.exists("Employee", e)]
        finally:
            # the survivors are deliberate leaks; do not pass them on to the next test
            for name in self._must_survive + self._must_be_gone:
                if frappe.db.exists("Employee", name):
                    frappe.delete_doc("Employee", name, force=True)
            self._cleanup_committed_1886()
        self.assertEqual(gone_but_present, [], "Employee of a tracked User outlived the drain")
        self.assertEqual(survivors_missing, [], "drain deleted an Employee the test did not cause")

    def _tracked_user(self):
        email = f"h1886.{frappe.generate_hash(length=8)}@test.invalid"
        _insert_user_1886(email)
        self.track_doc("User", email)
        return email

    def test_committed_employee_of_a_tracked_user_is_drained(self):
        email = self._tracked_user()
        employee = _insert_employee_1886(email, self.settings_company)
        self._create_committed_1886()
        self._must_be_gone.append(employee)

    def test_employee_that_predates_the_test_is_left_alone(self):
        # The test tracks a User that already had an Employee before setUp.
        self.track_doc("User", self._old_email)
        self._must_survive.append(self._old_employee)

    def test_employee_of_an_untracked_user_is_left_alone(self):
        self._tracked_user()  # a tracked User exists, so the drain does look at Employees
        email = f"h1886.untracked.{frappe.generate_hash(length=8)}@test.invalid"
        _insert_user_1886(email)
        employee = _insert_employee_1886(email, self.settings_company)
        self._create_committed_1886()
        self._must_survive.append(employee)
        self.addCleanup(self._drop_untracked_user, email)

    @staticmethod
    def _drop_untracked_user(email):
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, force=True)
            TestHarnessDrainsEmployeesOfTrackedUsers._cleanup_committed_1886()
