"""#2802: a portal volunteer may link their OWN existing Employee at the first expense.

Maintainer ruling (2026-11-18): "own" means ``Employee.user_id == Member.user`` AND that user
is ``frappe.session.user``. The reuse-and-link runs before the ``has_permission("Employee",
"create")`` guard; CREATING an Employee stays HR-gated. Also pinned here: a failure in a later
user step after the link is written does not turn into a reported failure, and a Left Employee
is never reused.

Probe shortcuts, stated: the Website User is inserted directly with its two roles (the portal
signup flow is not driven), ``Member.user`` and ``Employee.user_id`` are written with
``db.set_value`` (the account-creation flow is not driven), and the Expense Claim Type /
Category are created directly. The claim itself is filed through the real service.
"""

import re

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.harness_logger import get_harness_logger
from verenigingen.tests.volunteer.test_volunteer_expense_services_coverage import _ExpenseFixtureMixin
from verenigingen.utils.employee_user_link import create_employee_for_approved_volunteer

_LOG = get_harness_logger(__name__)
_PORTAL_ROLES = ("Verenigingen Volunteer", "Verenigingen Member")
_REFUSAL = "Unable to create employee record automatically"


class TestOwnEmployeeLink2802(_ExpenseFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._runner_2802 = frappe.session.user
        self.member = self.create_test_member(first_name="Own2802", last_name="Portal")
        self.volunteer = self.create_test_volunteer(member_name=self.member.name)
        self.chapter = self.ensure_test_chapter("Own2802Chap")
        self._add_chapter_member(self.chapter.name, self.member.name)
        category = self._make_expense_category(name_hint="Own2802")
        claim_type = frappe.get_doc(
            {
                "doctype": "Expense Claim Type",
                "expense_type": category.name,
                "accounts": [{"company": self._company(), "default_account": self._expense_account()}],
            }
        ).insert()
        self.factory.track_document("Expense Claim Type", claim_type.name, priority=1)
        self.category = category.name
        self.portal_user = self._portal_user_2802("own")
        frappe.db.set_value("Member", self.member.name, "user", self.portal_user, update_modified=False)
        self.volunteer.reload()

    def tearDown(self):
        frappe.set_user(self._runner_2802)
        super().tearDown()

    # -- fixtures ---------------------------------------------------------------

    def _portal_user_2802(self, hint):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": f"own2802-{hint}-{frappe.generate_hash(length=6)}@test.invalid",
                "first_name": "Own2802",
                "send_welcome_email": 0,
                "user_type": "Website User",
                "roles": [{"role": r} for r in _PORTAL_ROLES],
            }
        ).insert()
        self.factory.track_document("User", user.name, priority=0)
        return user.name

    def _employee_for_2802(self, user, *, status="Active", employee_name=None):
        employee = self._make_employee(name_hint="Own2802Emp")
        values = {"user_id": user, "status": status}
        if employee_name:
            values["employee_name"] = employee_name
        for field, value in values.items():
            frappe.db.set_value("Employee", employee.name, field, value, update_modified=False)
        return employee

    def _linked_2802(self):
        return frappe.db.get_value("Volunteer", self.volunteer.name, "employee_id")

    def _track_new_employees_2802(self, before_names):
        for name in set(frappe.get_all("Employee", pluck="name")) - before_names:
            self.factory.track_document("Employee", name, priority=0)

    def _submit_first_expense_2802(self):
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

    # -- the ruling ---------------------------------------------------------------

    def test_portal_volunteer_links_their_own_employee_via_the_first_expense(self):
        own = self._employee_for_2802(self.portal_user)
        before = set(frappe.get_all("Employee", pluck="name"))
        frappe.set_user(self.portal_user)
        self.assertFalse(frappe.has_permission("Employee", "create"), "fixture user must be a portal user")

        try:
            result = self._submit_first_expense_2802()
        finally:
            frappe.set_user(self._runner_2802)
        self._track_new_employees_2802(before)

        self.assertEqual(self._linked_2802(), own.name)
        self.assertEqual(set(frappe.get_all("Employee", pluck="name")), before, "no Employee created")
        self.assertNotIn(_REFUSAL, str(result.error_message or ""))

    def test_member_user_that_is_not_the_session_user_is_not_linked(self):
        # staff-on-behalf / impersonation shape: the member's user owns an Employee, but
        # the caller is a different portal user without Employee create
        self._employee_for_2802(self.portal_user)
        caller = self._portal_user_2802("caller")
        frappe.set_user(caller)
        try:
            result = create_employee_for_approved_volunteer(self.volunteer)
        finally:
            frappe.set_user(self._runner_2802)

        self.assertIsNone(result)
        self.assertFalse(self._linked_2802())

    def test_portal_volunteer_without_an_own_employee_is_refused_and_creates_none(self):
        before = set(frappe.get_all("Employee", pluck="name"))
        frappe.set_user(self.portal_user)
        try:
            result = self._submit_first_expense_2802()
        finally:
            frappe.set_user(self._runner_2802)

        self.assertFalse(result.success)
        self.assertIn(_REFUSAL, str(result.error_message))
        self.assertIn("contact your administrator", str(result.error_message))
        self.assertEqual(set(frappe.get_all("Employee", pluck="name")), before)
        self.assertFalse(self._linked_2802())

    def test_a_left_employee_is_not_reused_by_the_portal_volunteer(self):
        self._employee_for_2802(self.portal_user, status="Left")
        frappe.set_user(self.portal_user)
        try:
            result = create_employee_for_approved_volunteer(self.volunteer)
        finally:
            frappe.set_user(self._runner_2802)
        self.assertIsNone(result)
        self.assertFalse(self._linked_2802())

    def test_a_left_employee_is_not_reused_by_hr_either_and_a_new_one_is_created(self):
        left = self._employee_for_2802(self.portal_user, status="Left")
        before = set(frappe.get_all("Employee", pluck="name"))
        employee_id = create_employee_for_approved_volunteer(self.volunteer)
        self._track_new_employees_2802(before)
        self.assertTrue(employee_id)
        self.assertNotEqual(employee_id, left.name)
        self.assertEqual(self._linked_2802(), employee_id)

    def test_an_inactive_employee_is_not_reused(self):
        self._employee_for_2802(self.portal_user, status="Inactive")
        frappe.set_user(self.portal_user)
        try:
            result = create_employee_for_approved_volunteer(self.volunteer)
        finally:
            frappe.set_user(self._runner_2802)
        self.assertIsNone(result)
        self.assertFalse(self._linked_2802())

    def test_name_alone_never_selects_an_employee(self):
        # same employee_name as the member, but a different user_id: must not be borrowed
        other = self._portal_user_2802("other")
        self._employee_for_2802(other, employee_name=self.member.full_name)
        frappe.set_user(self.portal_user)
        try:
            result = create_employee_for_approved_volunteer(self.volunteer)
        finally:
            frappe.set_user(self._runner_2802)
        self.assertIsNone(result)
        self.assertFalse(self._linked_2802())

    def test_an_existing_link_to_a_left_employee_is_left_alone(self):
        # reported, not silently relinked: an existing employee_id wins as before
        left = self._employee_for_2802(self.portal_user, status="Left")
        self._own_active = self._employee_for_2802(self.portal_user)
        frappe.db.set_value("Employee", left.name, "user_id", None, update_modified=False)
        frappe.db.set_value("Volunteer", self.volunteer.name, "employee_id", left.name)
        self.volunteer.reload()
        result = create_employee_for_approved_volunteer(self.volunteer)
        self.assertEqual(result, left.name)
        self.assertEqual(self._linked_2802(), left.name)

    # -- item 2: a late failure after the link is written -------------------------

    def test_a_failing_user_step_after_the_link_still_returns_the_employee(self):
        from unittest import mock

        before = set(frappe.get_all("Employee", pluck="name"))
        with mock.patch(
            "verenigingen.utils.employee_user_link.create_user_for_volunteer",
            side_effect=RuntimeError("user step boom"),
        ):
            employee_id = create_employee_for_approved_volunteer(self.volunteer)
        self._track_new_employees_2802(before)

        self.assertTrue(employee_id)
        self.assertEqual(self._linked_2802(), employee_id)
        logged = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%user step boom%"]},
            pluck="name",
            limit=1,
        )
        self.assertTrue(logged, "the failed user step must be logged, not swallowed")

    # -- existence oracle ---------------------------------------------------------

    def _probe_channels_2802(self, volunteer_name, user):
        """Everything a portal caller could observe from one refused first expense."""
        from unittest import mock

        from verenigingen.services.volunteer.expense_submission_service import (
            get_expense_submission_service,
        )

        frappe.set_user(user)
        frappe.local.message_log = []
        errors_before = frappe.db.count("Error Log")
        real_sql = frappe.db.sql
        with mock.patch.object(frappe.db, "sql", wraps=real_sql) as sql_spy:
            result = get_expense_submission_service(volunteer_name).submit_expense(
                {
                    "description": "Train ticket",
                    "amount": 5.0,
                    "expense_date": frappe.utils.today(),
                    "organization_type": "Chapter",
                    "chapter": self.chapter.name,
                    "category": self.category,
                }
            )
        frappe.set_user(self._runner_2802)
        return {
            "success": result.success,
            "message": str(result.error_message),
            "message_log": [re.sub(r"'__frappe_exc_id': '\w+'", "", str(m)) for m in frappe.local.message_log],
            "errors": frappe.db.count("Error Log") - errors_before,
            "queries": sql_spy.call_count,
        }

    def test_refusal_is_identical_whether_or_not_someone_else_has_an_employee(self):
        # volunteer 1 (self): the portal user has no Employee and nobody else does either
        self._probe_channels_2802(self.volunteer.name, self.portal_user)  # warm per-user caches
        baseline = self._probe_channels_2802(self.volunteer.name, self.portal_user)

        # volunteer 2: same shape, but ANOTHER user owns an Employee carrying the member's name
        member2 = self.create_test_member(first_name="Own2802", last_name="Probe")
        volunteer2 = self.create_test_volunteer(member_name=member2.name)
        self._add_chapter_member(self.chapter.name, member2.name)
        user2 = self._portal_user_2802("probe")
        frappe.db.set_value("Member", member2.name, "user", user2, update_modified=False)
        self._employee_for_2802(self._portal_user_2802("holder"), employee_name=member2.full_name)
        self._probe_channels_2802(volunteer2.name, user2)  # warm per-user caches
        with_other = self._probe_channels_2802(volunteer2.name, user2)

        self.assertFalse(baseline["success"], baseline)
        self.assertIn(_REFUSAL, baseline["message"])
        self.assertEqual(with_other, baseline)
