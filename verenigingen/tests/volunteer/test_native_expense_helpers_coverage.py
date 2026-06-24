"""
Coverage-focused integration tests for
``verenigingen/services/volunteer/native_expense_helpers.py``.

The existing ``test_volunteer_expense_services_coverage.TestNativeExpenseHelpersDeep``
already exercises the shallow / no-op branches (approver lookup happy path,
no-employee_id and missing-employee returns, the validation-result shape, the
formatted refresh/issue strings, readiness boolean). This file targets the
*remaining* missed paths -- the ones that actually mutate Employee/User records
or run the maintenance whitelists end-to-end:

  * ``get_volunteer_expense_approver`` -- exception/fallback branch.
  * ``update_employee_approver`` -- the real success path (Employee.expense_approver
    written via ``secure_document_operation``), the string-volunteer-arg branch,
    and the no-op-when-unchanged branch.
  * ``validate_expense_approver_setup`` -- the approvers-without-role and
    inactive-approver diagnostic branches.
  * ``fix_expense_approver_issues`` -- the admin maintenance whitelist that
    reassigns approvers and grants the Expense Approver role (entirely uncovered).

Real integration only: every Employee / User / Volunteer is a real tracked
document, and assertions check the persisted DB state (Employee.expense_approver,
Has Role rows), not just "did not raise". The only swallow-into-log paths are
wrapped with ``assertNoErrorLog`` / ``expectErrorLog`` so a silent failure flips
the test red.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _NativeHelperFixtureMixin:
    """Real Employee / approver-User fixtures shared across the test classes."""

    def _company(self):
        return frappe.db.get_single_value("Verenigingen Settings", "company") or "_Test Company"

    def _make_employee(self, *, expense_approver=None, name_hint="EmpApr"):
        """Create a minimal real Employee (no expense_approver by default)."""
        gender = frappe.db.get_value("Gender", {}, "name") or "Other"
        emp = frappe.new_doc("Employee")
        emp.first_name = f"{name_hint}{frappe.generate_hash(length=5)}"
        emp.gender = gender
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = "2020-01-01"
        emp.status = "Active"
        emp.company = self._company()
        if expense_approver:
            emp.expense_approver = expense_approver
        emp.insert(ignore_permissions=True)
        self.factory.track_document("Employee", emp.name, priority=0)
        return emp

    def _make_approver_user(self, *, enabled=1, name_hint="approver"):
        """Create a real User to act as an expense approver.

        Note: linking this user as an Employee's ``expense_approver`` (which the
        approver-setup queries scan) auto-grants the 'Expense Approver' role via
        an ERPNext Employee hook. Tests that need the role ABSENT must revoke it
        after the Employee link with ``_revoke_expense_approver_role``.
        """
        email = f"{name_hint}.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = name_hint.title()
        user.send_welcome_email = 0
        user.enabled = enabled
        user.insert(ignore_permissions=True)
        self.factory.track_document("User", user.name, priority=2)
        return user

    def _revoke_expense_approver_role(self, user_name):
        """Remove the 'Expense Approver' Has Role row from a user.

        Deletes the child row directly (rather than re-saving the User) so the
        revoke does not re-trigger any role-sync hooks.
        """
        frappe.db.delete(
            "Has Role",
            {"parent": user_name, "parenttype": "User", "role": "Expense Approver"},
        )

    def _disable_user(self, user_name):
        frappe.db.set_value("User", user_name, "enabled", 0)

    def _link_volunteer_employee(self, volunteer, employee_name):
        """Persist volunteer.employee_id so the helper's exists() guard passes."""
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", employee_name)
        volunteer.reload()
        return volunteer


# ---------------------------------------------------------------------------
# get_volunteer_expense_approver -- exception / fallback branch
# ---------------------------------------------------------------------------
class TestGetVolunteerExpenseApprover(_NativeHelperFixtureMixin, EnhancedTestCase):
    def test_nonexistent_volunteer_falls_back_to_administrator(self):
        """A non-existent volunteer makes ``frappe.get_doc`` raise; the helper
        swallows it (logging 'Expense Approver Lookup Error') and returns the
        'Administrator' safe fallback."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            get_volunteer_expense_approver,
        )

        self.expectErrorLog("Expense Approver Lookup Error")
        approver = get_volunteer_expense_approver("VOL-DOES-NOT-EXIST-XYZ")
        self.assertEqual(approver, "Administrator")


# ---------------------------------------------------------------------------
# update_employee_approver -- the real Employee.expense_approver write path
# ---------------------------------------------------------------------------
class TestUpdateEmployeeApprover(_NativeHelperFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="EmpAprv", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    def test_success_writes_approver_and_clears_department(self):
        """A volunteer with a linked Employee whose current approver differs from
        the computed approver: the helper writes the new approver, clears the
        department, and persists it via secure_document_operation. Assert the
        real Employee row changed."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            update_employee_approver,
        )

        emp = self._make_employee(expense_approver=None)
        self._link_volunteer_employee(self.volunteer, emp.name)

        # With no organizational assignments the approver service falls back to a
        # real user (Administrator at minimum) -- a non-empty value that differs
        # from the employee's current empty approver, so the write branch runs.
        with self.assertNoErrorLog():
            approver = update_employee_approver(self.volunteer)

        self.assertTrue(approver, "computed approver should be a non-empty user")
        self.assertEqual(
            frappe.db.get_value("Employee", emp.name, "expense_approver"),
            approver,
            "the Employee row must carry the freshly written approver",
        )
        # Department dependency is removed as part of the native-expense migration.
        self.assertFalse(frappe.db.get_value("Employee", emp.name, "department"))

    def test_string_volunteer_arg_is_resolved(self):
        """Passing the volunteer *name* (string) rather than the doc is the
        document-hook calling convention: the helper loads it via get_doc and
        still drives the write path to completion."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            update_employee_approver,
        )

        emp = self._make_employee(expense_approver=None)
        self._link_volunteer_employee(self.volunteer, emp.name)

        with self.assertNoErrorLog():
            approver = update_employee_approver(self.volunteer.name)

        self.assertTrue(approver)
        self.assertEqual(
            frappe.db.get_value("Employee", emp.name, "expense_approver"),
            approver,
        )

    def test_noop_when_approver_unchanged(self):
        """When the Employee already has exactly the approver the service would
        compute, the unchanged branch returns the approver WITHOUT a save (the
        old==new guard)."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            update_employee_approver,
        )

        # Determine what the service would compute for this volunteer, then seed
        # the Employee with that exact value so old_approver == approver.
        computed = self.volunteer.get_expense_approver_from_assignments()
        self.assertTrue(computed)
        emp = self._make_employee(expense_approver=computed)
        self._link_volunteer_employee(self.volunteer, emp.name)
        modified_before = frappe.db.get_value("Employee", emp.name, "modified")

        with self.assertNoErrorLog():
            approver = update_employee_approver(self.volunteer)

        self.assertEqual(approver, computed)
        # No write occurred -> modified timestamp unchanged.
        self.assertEqual(frappe.db.get_value("Employee", emp.name, "modified"), modified_before)


# ---------------------------------------------------------------------------
# validate_expense_approver_setup -- the approver-role / inactive-approver
# diagnostic branches (the existing suite only seeds the no-approver branch).
# ---------------------------------------------------------------------------
class TestValidateExpenseApproverSetupBranches(_NativeHelperFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="ValSetup", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    def test_approver_without_role_is_flagged(self):
        """An Employee whose approver user lacks the 'Expense Approver' role
        surfaces in approvers_without_role and an interpolated issue string."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            validate_expense_approver_setup,
        )

        roleless = self._make_approver_user(name_hint="noroleappr")
        emp = self._make_employee(expense_approver=roleless.name)
        self._link_volunteer_employee(self.volunteer, emp.name)
        # The Employee insert auto-granted the role; revoke it so the
        # approvers-without-role branch is the one under test.
        self._revoke_expense_approver_role(roleless.name)

        result = validate_expense_approver_setup()

        flagged = {row["expense_approver"] for row in result["approvers_without_role"]}
        self.assertIn(roleless.name, flagged)
        self.assertTrue(
            any("without 'Expense Approver' role" in i and i[0].isdigit() for i in result["issues"]),
            f"expected an interpolated role-issue in: {result['issues']!r}",
        )

    def test_inactive_approver_is_flagged(self):
        """An Employee whose approver user is disabled surfaces in
        inactive_approvers with an interpolated issue string."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            validate_expense_approver_setup,
        )

        disabled = self._make_approver_user(name_hint="inactiveappr")
        emp = self._make_employee(expense_approver=disabled.name)
        self._link_volunteer_employee(self.volunteer, emp.name)
        # Disable AFTER the Employee link so the row still references the user.
        self._disable_user(disabled.name)

        result = validate_expense_approver_setup()

        flagged = {row["expense_approver"] for row in result["inactive_approvers"]}
        self.assertIn(disabled.name, flagged)
        self.assertTrue(
            any("inactive approvers" in i and i[0].isdigit() for i in result["issues"]),
            f"expected an interpolated inactive-approver issue in: {result['issues']!r}",
        )


# ---------------------------------------------------------------------------
# fix_expense_approver_issues -- admin maintenance whitelist (uncovered)
# ---------------------------------------------------------------------------
class TestFixExpenseApproverIssues(_NativeHelperFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="FixAprv", last_name="Test")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)

    def test_fix_assigns_approver_to_employee_without_one(self):
        """The 'employees_without_approvers' fix branch finds the volunteer for the
        bare Employee and writes a computed approver. Assert the Employee row is
        no longer approver-less after the fix."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            fix_expense_approver_issues,
        )

        emp = self._make_employee(expense_approver=None)
        self._link_volunteer_employee(self.volunteer, emp.name)
        self.assertFalse(frappe.db.get_value("Employee", emp.name, "expense_approver"))

        with self.assertNoErrorLog():
            result = fix_expense_approver_issues()

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["fixed"], 1)
        self.assertTrue(
            frappe.db.get_value("Employee", emp.name, "expense_approver"),
            "the bare Employee should have been assigned an approver by the fix",
        )

    def test_fix_grants_expense_approver_role(self):
        """The 'approvers_without_role' fix branch appends the Expense Approver
        role to the approver user via secure_document_operation. Assert the real
        Has Role row now exists."""
        from verenigingen.services.volunteer.native_expense_helpers import (
            fix_expense_approver_issues,
        )

        roleless = self._make_approver_user(name_hint="grantrole")
        emp = self._make_employee(expense_approver=roleless.name)
        self._link_volunteer_employee(self.volunteer, emp.name)
        # The Employee insert auto-granted the role; revoke it so the fix's
        # role-grant branch has work to do.
        self._revoke_expense_approver_role(roleless.name)

        self.assertFalse(
            frappe.db.exists(
                "Has Role",
                {"parent": roleless.name, "parenttype": "User", "role": "Expense Approver"},
            )
        )

        with self.assertNoErrorLog():
            result = fix_expense_approver_issues()

        self.assertTrue(result["success"])
        self.assertTrue(
            frappe.db.exists(
                "Has Role",
                {"parent": roleless.name, "parenttype": "User", "role": "Expense Approver"},
            ),
            "the fix must grant the Expense Approver role to the role-less approver",
        )
