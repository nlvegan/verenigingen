# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Tests for #1195: a plain ``user.append("roles", {"role": X}) + user.save()``
is silently defeated when the user carries a Role Profile that does not
include ``X`` -- ``User.populate_role_profile_roles()`` re-derives ``roles``
from ``role_profiles`` on every save and strips anything not in that
derived set, including the role just appended, in the SAME ``validate()``
call.

Covers the shared fix (``verenigingen.utils.user_role_grant.
ensure_role_survives_profile_resync``) and its rollout to the call sites
found by the class sweep that grep'd for ``append("roles"`` across the app:

- verenigingen/utils/team_role_profile_hooks.py::_sync_team_lead_role
- verenigingen/services/volunteer/native_expense_helpers.py::fix_expense_approver_issues
- verenigingen/setup/public_document_creator_setup.py::assign_public_creator_roles
- verenigingen/services/member/account/member_role_service.py::_assign_individual_member_roles
- verenigingen/services/member/account/account_creation_manager.py::assign_roles_and_profile
- verenigingen/services/volunteer/expense_approver_service.py::ensure_user_has_expense_approver_role
  (refactored to delegate to the shared helper instead of duplicating it)

Two sites named in #1195 were checked and found NOT affected (see
verenigingen/utils/employee_user_link.py and
verenigingen/setup/webhook_user_setup.py) -- not covered here because
there is no defect to reproduce.

verenigingen/events/subscribers/chapter_subscribers.py::_grant_chapter_member_permissions
and verenigingen/utils/department_hierarchy.py::_ensure_expense_approver_role
were also found affected by the same sweep; their tests live in those
modules' own existing test files (test_chapter_subscribers.py,
test_department_hierarchy.py) rather than here.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.utils.constants import Roles
from verenigingen.utils.user_role_grant import ensure_role_survives_profile_resync

# "Verenigingen Volunteer" is a real, fixture-shipped Role Profile
# (verenigingen/fixtures/role_profile.json) whose roles are exactly
# [Verenigingen Member, Verenigingen Volunteer, Employee, Employee Self
# Service, Projects User] -- it does NOT include Expense Approver, Team
# Lead, Chapter Member, or "Verenigingen Public Document Creator". Using a
# real, checked-in profile (rather than creating one) means the test fails
# for the right reason if that fixture ever changes to include one of these
# roles, instead of silently testing nothing.
PROFILE_WITHOUT_EXTRA_ROLES = Roles.VOLUNTEER


class TestUserRoleGrant(EnhancedTestCase):
    # ------------------------------------------------------------------ helpers
    def _make_user_with_role_profile(self, profile=PROFILE_WITHOUT_EXTRA_ROLES, prefix="role-grant"):
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "RoleGrantTest",
                "send_welcome_email": 0,
                "enabled": 1,
                "role_profiles": [{"role_profile": profile}],
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        return email

    def _make_plain_user(self, prefix="role-grant-plain"):
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "RoleGrantPlain",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        return email

    def _grant_role_via_append_save(self, email, role):
        """The plain append+save pattern under test -- reproduces #1195 when
        `email` carries a Role Profile that doesn't include `role`."""
        user = frappe.get_doc("User", email)
        user.append("roles", {"role": role})
        user.save(ignore_permissions=True)

    def _make_unrelated_save(self, email):
        """A save that has nothing to do with roles -- used to show a LATER
        save re-strips a role a prior call granted (the durability gap)."""
        user = frappe.get_doc("User", email)
        user.bio = "unrelated field change forcing a full User.validate()"
        user.save(ignore_permissions=True)

    def _ensure_role_exists(self, role_name):
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 0}).insert(
                ignore_permissions=True
            )

    def _ensure_admin_session(self):
        frappe.set_user("Administrator")

    def _make_team_led_by(self, email):
        """Team.team_lead is derived (Team._update_team_lead), not settable
        directly: it reads back the volunteer on an active team_members row
        whose Team Role has is_team_leader=1. Build that shape for real,
        rather than setting team_lead on the insert dict (which the
        controller silently overwrites to None -- confirmed empirically).
        Returns the Team document."""
        member = self.create_test_member(user=email, chapter=False)
        volunteer = self.create_test_volunteer(member_name=member.name)

        team = self.create_test_team()
        self._track_test_document("Team", team.name, priority=2)
        if not frappe.db.exists("Team Role", "Team Leader"):
            frappe.get_doc(
                {"doctype": "Team Role", "role_name": "Team Leader", "is_team_leader": 1}
            ).insert(ignore_permissions=True)
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": "Team Leader",
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team_doc.save(ignore_permissions=True)
        return team_doc

    def _make_employee_with_expense_approver(self, email):
        """A real Employee whose expense_approver is `email`, so
        validate_expense_approver_setup() genuinely flags it (rather than
        mocking that DB-query helper, which the repo's test-quality gate
        blocks as a business-logic mock -- and rightly so, since it would
        stop testing whether the real query even finds the row).

        expense_approver is set via db_set AFTER insert, deliberately
        bypassing Employee's own on_update hook
        (hrms.overrides.employee_master.update_approver_role, which calls
        User.add_roles("Expense Approver") and would otherwise grant the
        role through a completely different path, defeating the point of
        this test). This also matches the real scenario
        fix_expense_approver_issues() exists for: an expense_approver
        reference written by a path that never ran that hook (bulk import,
        a patch, or a direct SQL update)."""
        company = get_eur_test_company()
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"RoleGrantEmp{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
                "user_id": email,
            }
        )
        emp.insert(ignore_permissions=True)
        emp.db_set("expense_approver", email, update_modified=False)  # ast-skip: ERPNext HR field
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    # ------------------------------------------------------------- core helper
    def test_plain_append_save_is_silently_defeated_by_role_profile(self):
        """The bug #1195 reports, reproduced directly against frappe core.

        Not a regression test for OUR code (frappe core's behaviour is not
        something this PR changes) -- it documents why the workaround in
        ensure_role_survives_profile_resync is needed at all, and fails loudly
        if a future frappe upgrade changes this behaviour (in which case the
        workaround should be reconsidered, not silently left in place).
        """
        email = self._make_user_with_role_profile()
        self._grant_role_via_append_save(email, Roles.EXPENSE_APPROVER)

        self.assertNotIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))

    def test_ensure_role_survives_profile_resync_grants_the_role(self):
        email = self._make_user_with_role_profile()
        self._grant_role_via_append_save(email, Roles.EXPENSE_APPROVER)
        # Confirmed dropped by the test above; this is the fix:
        self.assertTrue(ensure_role_survives_profile_resync(email, Roles.EXPENSE_APPROVER))

        self.assertIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))
        # ... and survives a fresh load, not just the in-memory doc mutated above.
        frappe.get_doc("User", email)
        self.assertIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))

    def test_ensure_role_survives_profile_resync_is_a_noop_when_already_granted(self):
        """A role the profile itself grants must not get a duplicate Has Role row."""
        email = self._make_user_with_role_profile()
        self.assertTrue(ensure_role_survives_profile_resync(email, Roles.VOLUNTEER))

        count = frappe.db.count(
            "Has Role", {"parent": email, "role": Roles.VOLUNTEER, "parenttype": "User"}
        )
        self.assertEqual(count, 1)

    def test_positive_control_no_role_profile_append_save_still_works(self):
        """A user with NO role profile is unaffected: append+save alone grants
        the role, exactly as before #1195 -- confirming the bug is specific to
        role-profile-carrying users, not a general break in role assignment."""
        email = self._make_plain_user()
        self._grant_role_via_append_save(email, Roles.EXPENSE_APPROVER)

        self.assertIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))

    def test_known_gap_role_does_not_survive_a_later_unrelated_save(self):
        """#1195's fix covers the SAME-SAVE defeat only.

        A direct Has Role insert is NOT durable: a LATER, unrelated
        user.save() re-runs User.populate_role_profile_roles(), which strips
        the role again because it is still not part of any attached Role
        Profile. This is measured, current behaviour, not a bug this PR
        introduces -- the pre-existing "known correct pattern"
        (expense_approver_service.ensure_user_has_expense_approver_role) has
        the exact same limitation. Making the grant durable across arbitrary
        future saves needs a policy decision (extend a Role Profile, add a
        dedicated profile, or a "sticky role" re-application mechanism) --
        see the follow-up issue filed alongside this PR.

        If this assertion ever starts failing (i.e. the role DOES survive),
        that is good news: update this test and the durability caveat in
        user_role_grant.py's module docstring, and close that issue.
        """
        email = self._make_user_with_role_profile()
        ensure_role_survives_profile_resync(email, Roles.EXPENSE_APPROVER)
        self.assertIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))

        self._make_unrelated_save(email)

        self.assertNotIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))

    # -------------------------------------------------- team_role_profile_hooks
    def test_sync_team_lead_role_survives_role_profile(self):
        from verenigingen.utils.team_role_profile_hooks import _sync_team_lead_role

        email = self._make_user_with_role_profile()
        team_doc = self._make_team_led_by(email)
        self.assertEqual(
            frappe.db.get_value("Team", team_doc.name, "team_lead"),
            email,
            "fixture setup did not actually make this user the team_lead",
        )

        _sync_team_lead_role(email)

        self.assertIn("Team Lead", frappe.get_roles(email))

    # ------------------------------------------------- native_expense_helpers
    def test_fix_expense_approver_issues_survives_role_profile(self):
        from verenigingen.services.volunteer import native_expense_helpers as neh

        email = self._make_user_with_role_profile(prefix="native-expense-helpers-test")
        self._make_employee_with_expense_approver(email)

        result = neh.fix_expense_approver_issues()

        self.assertGreaterEqual(result["fixed"], 1)
        self.assertIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))

    # --------------------------------------------- public_document_creator_setup
    def test_assign_public_creator_roles_survives_role_profile(self):
        from verenigingen.setup.public_document_creator_setup import (
            PUBLIC_CREATOR_ROLE,
            assign_public_creator_roles,
        )

        self._ensure_role_exists(PUBLIC_CREATOR_ROLE)

        email = self._make_user_with_role_profile(prefix="public-creator-test")
        result = assign_public_creator_roles(email)

        self.assertTrue(result["success"])
        self.assertIn(PUBLIC_CREATOR_ROLE, frappe.get_roles(email))

    # ------------------------------------------------------- member_role_service
    def test_assign_individual_member_roles_survives_role_profile(self):
        """_assign_individual_member_roles is the fallback used when the
        requested Role Profile record doesn't exist -- reachable on an
        EXISTING, role-profile-carrying user via
        member_user_account_service.create_organization_user_for_member's
        "linked_existing" path (frappe.get_doc("User", existing_user), not a
        fresh insert), so role_profiles can be non-empty here despite the
        module's own comment claiming this only runs for new accounts."""
        from verenigingen.services.member.account.member_role_service import get_member_role_service

        # "Verenigingen Webhook User" is the one shipped profile that does NOT
        # include "Verenigingen Member" (its roles are Verenigingen Webhook
        # User / Accounts User / Sales User) -- needed so the assertion below
        # actually exercises the defeat. "All" would pass regardless of the
        # defect: frappe.get_roles() unconditionally appends it outside the
        # Has Role query, so it is not evidence of anything.
        email = self._make_user_with_role_profile(
            profile="Verenigingen Webhook User", prefix="member-role-service-test"
        )
        service = get_member_role_service()

        # "Nonexistent Role Profile For Test" deliberately does not exist, so
        # add_member_roles_to_user takes the fallback branch under test.
        result = service.add_member_roles_to_user(email, role_profile_name="Nonexistent Role Profile For Test")

        self.assertEqual(result, email)
        self.assertIn(Roles.VERENIGINGEN_MEMBER, frappe.get_roles(email))

    # ---------------------------------------------------- account_creation_manager
    def test_assign_roles_and_profile_survives_existing_role_profile(self):
        """assign_roles_and_profile appends individually-requested roles AND a
        role profile in the same in-memory User doc before a single save --
        if the user already carries role_profiles (e.g. a retried ACR for an
        already-provisioned user), a requested role outside the profile is
        defeated the same way (#1195)."""
        from verenigingen.services.member.account.account_creation_manager import AccountCreationManager

        email = self._make_user_with_role_profile(prefix="acr-role-test")

        member = self.factory.create_member(email=email)
        request = self.factory.create_account_creation_request(
            source_record=member.name,
            request_type="Member",
            role_profile=PROFILE_WITHOUT_EXTRA_ROLES,
            requested_roles=[{"role": Roles.VERENIGINGEN_MEMBER}, {"role": "Team Lead"}],
        )

        manager = AccountCreationManager(request.name)
        manager.load_request()
        manager.created_user = email

        self._ensure_admin_session()
        manager.assign_roles_and_profile()

        self.assertIn("Team Lead", frappe.get_roles(email))

    # ------------------------------------------------- expense_approver_service
    def test_expense_approver_service_still_grants_role_after_refactor(self):
        """Regression test for delegating ensure_user_has_expense_approver_role's
        tail (verify + fallback direct insert) to the shared helper -- the
        externally observable behaviour (role ends up granted, even against a
        role-profile-carrying user) must be unchanged."""
        from verenigingen.services.volunteer.expense_approver_service import (
            VolunteerExpenseApproverService,
        )

        email = self._make_user_with_role_profile(prefix="expense-approver-refactor-test")
        service = VolunteerExpenseApproverService(volunteer_name="unused-not-loaded")

        service.ensure_user_has_expense_approver_role(email)

        self.assertIn(Roles.EXPENSE_APPROVER, frappe.get_roles(email))
