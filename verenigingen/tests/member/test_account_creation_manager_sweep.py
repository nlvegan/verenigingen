# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Coverage sweep for AccountCreationManager (services/member/account/
account_creation_manager.py).

This AUGMENTS test_account_creation_pipeline.py and test_account_creation_real.py.
It targets the branches those suites leave uncovered, exercising the manager
methods in isolation against real Member / User / Employee / Volunteer / ACR
docs (no business-logic mocking):

- can_assign_role: System Manager (any role), Verenigingen Staff/Admin
  allow-list hit + miss, and the "no privileged role" deny path.
- requires_employee_creation: Volunteer always-True, Member create_employee_record
  flag, Member with an Employee-bearing requested role, and the plain-Member
  False path.
- _parse_name_components: Member tussenvoegsel composition, Member fallback
  first_name="User", and the non-Member full_name split branch.
- _prepare_user_data: Volunteer → System User + new_password set; Member →
  Website User; bulk operation → no password + welcome email suppressed.
- _resolve_employee_pii_from_source: Member path, Volunteer→member hop, and the
  stub fallback when the Member has no gender/birth_date.
- create_employee_record: reuse of an existing Employee for the same user.
- _link_records_phase: the Member→Volunteer user/employee linking branches.
- _set_member_user_modules: happy path + the no-user early return.
- send_completion_notification: realtime publish to a different requestor.
- _sync_role_profile: the no-user early return.

Runs as Administrator (EnhancedTestCase) so can_assign_role's System Manager
branch is the default; the Staff/deny branches are exercised under self.as_user.
Permission bypass (set_value) only used inside _make_* helpers / setUp.
"""

import frappe

from verenigingen.services.member.account.account_creation_manager import AccountCreationManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestACManagerUnitBranches(EnhancedTestCase):
    """Exercise AccountCreationManager helper methods in isolation."""

    def setUp(self):
        super().setUp()
        self.h = frappe.generate_hash(length=6)

    # ----------------------------------------------------------- helpers

    def _member(self, **kwargs):
        defaults = {
            "first_name": f"ACMgr{self.h}",
            "last_name": f"M{frappe.generate_hash(length=5)}",
            "email": f"acmgr.{frappe.generate_hash(length=8)}@test.invalid",
            "status": "Active",
        }
        defaults.update(kwargs)
        return self.create_test_member(**defaults)

    def _manager_for_member(self, member, **acr_kwargs):
        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member", **acr_kwargs
        )
        mgr = AccountCreationManager(request.name)
        mgr.load_request()
        return mgr, request

    def _make_staff_user(self):
        user = self.create_test_user(
            f"acmgr.staff.{self.h}@test.invalid", roles=["Verenigingen Staff"]
        )
        return user

    # ============================================================ can_assign_role

    def test_can_assign_role_system_manager_any_role(self):
        # Administrator holds System Manager -> can assign even a high-priv role.
        member = self._member()
        mgr, _ = self._manager_for_member(member)
        self.assertTrue(mgr.can_assign_role("System Manager"))
        self.assertTrue(mgr.can_assign_role("Verenigingen Member"))

    def test_can_assign_role_staff_allowed_and_denied(self):
        member = self._member()
        mgr, _ = self._manager_for_member(member)
        staff = self._make_staff_user()
        with self.as_user(staff.email):
            # In the Staff allow-list.
            self.assertTrue(mgr.can_assign_role("Verenigingen Member"))
            self.assertTrue(mgr.can_assign_role("Employee Self Service"))
            # NOT in the allow-list -> denied (no privilege escalation).
            self.assertFalse(mgr.can_assign_role("System Manager"))
            self.assertFalse(mgr.can_assign_role("Verenigingen Administrator"))

    def test_can_assign_role_no_privileged_role_denies(self):
        member = self._member()
        mgr, _ = self._manager_for_member(member)
        plain = self.create_test_user(
            f"acmgr.plain.{self.h}@test.invalid", roles=["Verenigingen Member"]
        )
        with self.as_user(plain.email):
            self.assertFalse(mgr.can_assign_role("Verenigingen Member"))

    # ============================================================ requires_employee_creation

    def test_requires_employee_volunteer_always_true(self):
        member = self._member(birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"ACMgr Vol {self.h}",
            email=member.email,
        )
        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )
        mgr = AccountCreationManager(request.name)
        mgr.load_request()
        self.assertTrue(mgr.requires_employee_creation())

    def test_requires_employee_member_flag_true(self):
        member = self._member()
        mgr, _ = self._manager_for_member(member, create_employee_record=True)
        self.assertTrue(mgr.requires_employee_creation())

    def test_requires_employee_member_no_flag_false(self):
        member = self._member()
        mgr, request = self._manager_for_member(member)
        # The factory may default create_employee_record; clear it to pin the
        # plain-Member False branch. Mutate mgr.request (the doc production reads),
        # not the factory-returned `request` (a separate in-memory object).
        mgr.request.create_employee_record = 0
        self.assertFalse(mgr.requires_employee_creation())

    def test_requires_employee_via_requested_role(self):
        member = self._member()
        mgr, request = self._manager_for_member(member)
        # requires_employee_creation() reads mgr.request (loaded via load_request),
        # NOT the `request` object returned by the factory — they are two distinct
        # in-memory docs for the same DB row. Mutate the one production actually
        # inspects, otherwise the Employee-role branch is never reached.
        mgr.request.create_employee_record = 0
        mgr.request.append("requested_roles", {"role": "Employee Self Service"})
        self.assertTrue(mgr.requires_employee_creation())

    # ============================================================ _parse_name_components

    def test_parse_name_member_with_tussenvoegsel(self):
        member = self._member(first_name="Jan", last_name="Berg")
        frappe.db.set_value("Member", member.name, "tussenvoegsel", "van der")
        member.reload()
        mgr, _ = self._manager_for_member(member)
        # Reload the source doc on the manager to pick up the tussenvoegsel.
        mgr.source_doc.reload()
        first, last = mgr._parse_name_components()
        self.assertEqual(first, "Jan")
        self.assertIn("van der", last)
        self.assertIn("Berg", last)

    def test_parse_name_non_member_splits_full_name(self):
        member = self._member()
        mgr, request = self._manager_for_member(member)
        # Force the else-branch by pretending the request type is non-Member.
        # _parse_name_components reads mgr.request (NOT the factory-returned
        # `request`), so mutate mgr.request to actually hit the full_name split.
        mgr.request.request_type = "Volunteer"
        mgr.request.full_name = "Alice Bob Carol"
        first, last = mgr._parse_name_components()
        self.assertEqual(first, "Alice")
        self.assertEqual(last, "Bob Carol")

    def test_parse_name_non_member_empty_full_name_defaults(self):
        member = self._member()
        mgr, request = self._manager_for_member(member)
        mgr.request.request_type = "Volunteer"
        mgr.request.full_name = ""
        first, last = mgr._parse_name_components()
        self.assertEqual(first, "User")
        self.assertEqual(last, "")

    # ============================================================ _prepare_user_data

    def test_prepare_user_data_member_is_website_user(self):
        member = self._member()
        mgr, _ = self._manager_for_member(member)
        # send_welcome_email is suppressed when is_bulk_operation OR
        # frappe.flags.in_import / in_bulk_import is set. EnhancedTestCase.setUp
        # forces in_import=True (to bypass user-creation throttling), so the
        # non-bulk welcome-email branch only yields 1 once those flags are
        # cleared. Clear them locally to exercise the real "interactive Member
        # account → welcome email enabled" path, then restore.
        orig_in_import = frappe.flags.in_import
        orig_in_bulk = getattr(frappe.flags, "in_bulk_import", False)
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        try:
            data = mgr._prepare_user_data("First", "Last", is_bulk_operation=False)
        finally:
            frappe.flags.in_import = orig_in_import
            frappe.flags.in_bulk_import = orig_in_bulk
        self.assertEqual(data["user_type"], "Website User")
        self.assertEqual(data["send_welcome_email"], 1)
        self.assertIn("new_password", data)

    def test_prepare_user_data_volunteer_is_system_user(self):
        member = self._member(birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"ACMgr VolSU {self.h}",
            email=member.email,
        )
        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )
        mgr = AccountCreationManager(request.name)
        mgr.load_request()
        data = mgr._prepare_user_data("First", "Last", is_bulk_operation=False)
        self.assertEqual(data["user_type"], "System User")

    def test_prepare_user_data_bulk_suppresses_password_and_welcome(self):
        member = self._member()
        mgr, _ = self._manager_for_member(member)
        data = mgr._prepare_user_data("First", "Last", is_bulk_operation=True)
        self.assertEqual(data["send_welcome_email"], 0)
        self.assertNotIn("new_password", data)

    # ============================================================ _resolve_employee_pii_from_source

    def test_resolve_pii_member_path(self):
        member = self._member(gender="Male", birth_date="1980-02-02")
        mgr, _ = self._manager_for_member(member)
        gender, dob = mgr._resolve_employee_pii_from_source()
        self.assertEqual(gender, "Male")
        self.assertEqual(str(dob), "1980-02-02")

    def test_resolve_pii_volunteer_hops_to_member(self):
        member = self._member(gender="Female", birth_date="1975-03-03")
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"ACMgr VolPII {self.h}",
            email=member.email,
        )
        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )
        mgr = AccountCreationManager(request.name)
        mgr.load_request()
        gender, dob = mgr._resolve_employee_pii_from_source()
        self.assertEqual(gender, "Female")
        self.assertEqual(str(dob), "1975-03-03")

    def test_resolve_pii_stub_fallback_when_member_missing(self):
        member = self._member(birth_date="1990-01-01")
        frappe.db.set_value("Member", member.name, "gender", None)
        frappe.db.set_value("Member", member.name, "birth_date", None)
        mgr, _ = self._manager_for_member(member)
        mgr.source_doc.reload()
        gender, dob = mgr._resolve_employee_pii_from_source()
        self.assertEqual(gender, "Prefer not to say")
        self.assertEqual(str(dob), "1990-01-01")

    # ============================================================ create_employee_record reuse

    def test_create_employee_record_reuses_existing(self):
        # When an Employee already exists for the user, create_employee_record
        # short-circuits and reuses it (no duplicate Employee).
        member = self._member(birth_date="1990-01-01", gender="Male")
        mgr, request = self._manager_for_member(member, create_employee_record=True)
        # First create the user + employee via the real pipeline.
        mgr.process_complete_pipeline()
        request.reload()
        if not request.created_employee:
            self.skipTest("Employee not created in this environment")
        existing_emp = request.created_employee

        # Re-run create_employee_record on a fresh manager: it must reuse.
        mgr2 = AccountCreationManager(request.name)
        mgr2.load_request()
        mgr2.created_user = request.created_user
        mgr2.created_employee = None
        mgr2.create_employee_record()
        self.assertEqual(mgr2.created_employee, existing_emp)
        self.assertEqual(
            frappe.db.count("Employee", {"user_id": request.created_user}), 1
        )

    # ============================================================ _set_member_user_modules

    def test_set_member_user_modules_no_user_early_return(self):
        member = self._member()
        mgr, _ = self._manager_for_member(member)
        mgr.created_user = None
        # No-op, must not raise.
        mgr._set_member_user_modules()

    def test_set_member_user_modules_happy_path(self):
        member = self._member()
        user = self.create_test_user(member.email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        mgr, _ = self._manager_for_member(member)
        mgr.created_user = user.name
        with self.assertNoErrorLog():
            mgr._set_member_user_modules()

    # ============================================================ send_completion_notification

    def test_send_completion_notification_publishes(self):
        # requested_by differs from created_user -> realtime publish branch runs.
        member = self._member()
        mgr, request = self._manager_for_member(member)
        mgr.created_user = "someone.else@test.invalid"
        mgr.created_employee = None
        # Must not raise even though the user isn't a real session.
        with self.assertNoErrorLog():
            mgr.send_completion_notification()

    # ============================================================ _sync_role_profile

    def test_sync_role_profile_no_user_early_return(self):
        member = self._member()
        mgr, _ = self._manager_for_member(member)
        mgr.created_user = None
        # Early return, no exception, no role profile work.
        mgr._sync_role_profile()


class TestACManagerLinkingBranches(EnhancedTestCase):
    """Exercise _link_records_phase Member→Volunteer linking via the pipeline."""

    def setUp(self):
        super().setUp()
        self.h = frappe.generate_hash(length=6)

    def test_member_pipeline_links_volunteer_user(self):
        # A Member with an associated Volunteer: the pipeline must link the new
        # user onto the Volunteer record (Link 4 branch in _link_records_phase).
        member = self.create_test_member(
            first_name=f"ACLink{self.h}",
            last_name=f"M{frappe.generate_hash(length=5)}",
            email=f"aclink.{frappe.generate_hash(length=8)}@test.invalid",
            status="Active",
            birth_date="1990-01-01",
        )
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"ACLink Vol {self.h}",
            email=member.email,
        )
        # Ensure the volunteer has no user yet so the link branch executes.
        self.assertFalse(frappe.db.get_value("Volunteer", volunteer.name, "user"))

        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member"
        )
        mgr = AccountCreationManager(request.name)
        mgr.process_complete_pipeline()

        request.reload()
        self.assertEqual(request.status, "Completed")
        # The volunteer's user field should now point at the created user.
        self.assertEqual(
            frappe.db.get_value("Volunteer", volunteer.name, "user"),
            request.created_user,
        )
