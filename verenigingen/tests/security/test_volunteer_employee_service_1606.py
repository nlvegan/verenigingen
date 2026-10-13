"""Staff action "create the Employee record for this volunteer" (PR #1606).

Staff deliberately hold no Employee DocPerm (salary, bank and health fields sit at permlevel
0), so when the account pipeline leaves a volunteer without an Employee they use this
whitelisted action. Users are built from the roles the SHIPPED Role Profiles grant.
"""

import json
import time

import frappe

from verenigingen.services.volunteer.volunteer_employee_service import create_employee_for_volunteer
from verenigingen.setup.custom_docperm_setup import CORE_GRANTS
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _shipped_roles(profile):
    path = frappe.get_app_path("verenigingen", "fixtures", "role_profile.json")
    with open(path) as f:
        for p in json.load(f):
            if p["name"] == profile:
                return [r["role"] for r in p["roles"]]
    raise AssertionError(f"Role Profile {profile} is not shipped")


class TestCreateEmployeeForVolunteer(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.token = f"{int(time.time() * 1000)}{frappe.generate_hash(length=4)}"
        self.staff = self._employee_svc_user("Verenigingen Staff", "staff")
        # A board member passes the HIGH security tier like Staff does, so only this module's own
        # role gate stands between them and the action.
        self.outsider = self._employee_svc_user("Verenigingen Chapter Board Member", "outsider")
        self.volunteer_user = self._employee_svc_user("Verenigingen Volunteer", "target")
        self.member = self.create_test_member(
            first_name="Emp", last_name="Target", email=self.volunteer_user.name, user=self.volunteer_user.name
        )
        self.volunteer = self.create_test_volunteer(self.member.name)
        self.assertFalse(
            frappe.db.exists("Employee", {"user_id": self.volunteer_user.name}),
            "precondition: the automated flow left this volunteer without an Employee",
        )
        frappe.db.set_value("Volunteer", self.volunteer.name, "employee_id", None, update_modified=False)

    def _employee_svc_user(self, profile, tag):
        # Role Profile assigned as well as its roles: the @high_security_api tier is decided by
        # the user's profile, not by individual roles.
        user = self.create_test_user(email=f"emp1606-{tag}-{self.token}@test.com", roles=_shipped_roles(profile))
        user.append("role_profiles", {"role_profile": profile})
        user.save()
        return user

    def _call_create_employee_as(self, user, volunteer_name):
        original = frappe.session.user
        frappe.set_user(user.name)
        try:
            return create_employee_for_volunteer(volunteer_name)
        finally:
            frappe.set_user(original)

    def _employees(self):
        return frappe.get_all("Employee", filters={"user_id": self.volunteer_user.name}, pluck="name")

    def test_staff_creates_the_employee_and_gets_only_its_name(self):
        result = self._call_create_employee_as(self.staff, self.volunteer.name)

        employees = self._employees()
        self.assertEqual(len(employees), 1)
        self._track_test_document("Employee", employees[0], priority=2)
        self.assertEqual(result, {"employee": employees[0], "created": True})
        self.assertEqual(frappe.db.get_value("Volunteer", self.volunteer.name, "employee_id"), employees[0])
        # the Employee is the pipeline's: no User Permission pinning, same insert as the ACR path
        self.assertEqual(frappe.db.get_value("Employee", employees[0], "create_user_permission"), 0)

    def test_it_is_idempotent(self):
        first = self._call_create_employee_as(self.staff, self.volunteer.name)
        self._track_test_document("Employee", first["employee"], priority=2)

        second = self._call_create_employee_as(self.staff, self.volunteer.name)

        self.assertEqual(second, {"employee": first["employee"], "created": False})
        self.assertEqual(self._employees(), [first["employee"]])

    def test_an_existing_employee_is_linked_not_duplicated(self):
        # the Employee exists (made by another path) but the Volunteer never got linked
        existing = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": "Pre",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": frappe.get_single("Verenigingen Settings").company,
                "user_id": self.volunteer_user.name,
                "create_user_permission": 0,
            }
        ).insert()
        self._track_test_document("Employee", existing.name, priority=2)

        result = self._call_create_employee_as(self.staff, self.volunteer.name)

        self.assertEqual(result, {"employee": existing.name, "created": False})
        self.assertEqual(frappe.db.get_value("Volunteer", self.volunteer.name, "employee_id"), existing.name)

    def test_a_volunteer_without_a_user_account_is_refused_for_staff(self):
        loose = self.create_test_member(first_name="No", last_name="User")
        volunteer = self.create_test_volunteer(loose.name)
        frappe.db.set_value("Member", loose.name, "user", None, update_modified=False)
        with self.assertRaises(frappe.ValidationError):
            self._call_create_employee_as(self.staff, volunteer.name)

    def test_a_non_staff_caller_is_refused_and_nothing_is_created(self):
        with self.assertRaises(frappe.PermissionError):
            self._call_create_employee_as(self.outsider, self.volunteer.name)
        self.assertEqual(self._employees(), [])

    def test_unknown_and_real_volunteer_are_refused_identically_for_non_staff(self):
        test_user = frappe.session.user

        def probe(volunteer_name):
            frappe.local.message_log = []  # Mock justified: execution-context reset, not a stub
            errors_before = frappe.db.count("Error Log")
            statements = []
            real_sql = frappe.db.__class__.sql

            def counting_sql(db, *args, **kwargs):
                statements.append(1)
                return real_sql(db, *args, **kwargs)

            frappe.set_user(self.outsider.name)
            outcome = None
            try:
                frappe.db.__class__.sql = counting_sql  # Mock justified: counts statements, calls through
                create_employee_for_volunteer(volunteer_name)
            except Exception as e:
                outcome = (type(e).__name__, str(e))
            finally:
                frappe.db.__class__.sql = real_sql  # Mock justified: restores the original
                log = [{k: v for k, v in m.items() if k != "__frappe_exc_id"} for m in frappe.local.message_log]
                frappe.set_user(test_user)
            return outcome, log, frappe.db.count("Error Log") - errors_before, len(statements)

        probe(self.volunteer.name)  # warm the role / profile caches so counts compare like for like
        real = probe(self.volunteer.name)
        unknown = probe(f"Assoc-Vol-nonexistent-{self.token}")

        self.assertEqual(real[0][0], "PermissionError")
        self.assertTrue(real[1], "control: the refusal does put a message in message_log")
        self.assertEqual(real, unknown)

    def _point_member_at(self, user):
        frappe.db.set_value("Member", self.member.name, "user", user.name, update_modified=False)

    def test_staff_cannot_hand_the_employee_role_to_a_higher_tier_user(self):
        # Staff can edit Member.user; the action must not turn that into Employee-role and
        # User Permission grants for a System Manager, Staff or Treasurer account.
        for profile in ("Verenigingen Staff", "Verenigingen Treasurer", "Verenigingen Administrator"):
            with self.subTest(profile=profile):
                target = self._employee_svc_user(profile, f"hi{profile[-5:]}".lower())
                self._point_member_at(target)
                with self.assertRaises(frappe.ValidationError) as ctx:
                    self._call_create_employee_as(self.staff, self.volunteer.name)
                self.assertIn("above the member and volunteer level", str(ctx.exception))
                self.assertFalse(frappe.db.exists("Employee", {"user_id": target.name}))
                self.assertFalse(frappe.db.exists("User Permission", {"user": target.name}))

    def test_an_employee_of_another_user_is_neither_linked_nor_named(self):
        stranger_user = self._employee_svc_user("Verenigingen Volunteer", "stranger")
        stranger = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": "Stranger",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": frappe.get_single("Verenigingen Settings").company,
                "user_id": stranger_user.name,
                "create_user_permission": 0,
            }
        ).insert()
        self._track_test_document("Employee", stranger.name, priority=2)
        frappe.db.set_value("Volunteer", self.volunteer.name, "employee_id", stranger.name, update_modified=False)

        with self.assertRaises(frappe.ValidationError) as ctx:
            self._call_create_employee_as(self.staff, self.volunteer.name)

        self.assertNotIn(stranger.name, str(ctx.exception))
        self.assertEqual(frappe.db.get_value("Volunteer", self.volunteer.name, "employee_id"), stranger.name)
        self.assertEqual(self._employees(), [])

    def test_an_existing_employee_of_a_higher_tier_user_is_not_linked_either(self):
        target = self._employee_svc_user("Verenigingen Staff", "hiexist")
        existing = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": "Boss",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": frappe.get_single("Verenigingen Settings").company,
                "user_id": target.name,
                "create_user_permission": 0,
            }
        ).insert()
        self._track_test_document("Employee", existing.name, priority=2)
        self._point_member_at(target)

        with self.assertRaises(frappe.ValidationError) as ctx:
            self._call_create_employee_as(self.staff, self.volunteer.name)

        self.assertNotIn(existing.name, str(ctx.exception))
        self.assertFalse(frappe.db.get_value("Volunteer", self.volunteer.name, "employee_id"))

    def test_staff_still_holds_no_employee_permission(self):
        # The reason this action exists: no DocPerm grant (and none in CORE_GRANTS, which never
        # revokes -- #1642) may give Staff the doctype.
        self.assertFalse(frappe.has_permission("Employee", "create", user=self.staff.name))
        self.assertFalse(frappe.has_permission("Employee", "delete", user=self.staff.name))
        self.assertNotIn("Verenigingen Staff", {role for dt, role, _p in CORE_GRANTS if dt == "Employee"})
        # control: the scan sees the roles that do carry an Employee grant
        self.assertIn("HR User", {role for dt, role, _p in CORE_GRANTS if dt == "Employee"})
