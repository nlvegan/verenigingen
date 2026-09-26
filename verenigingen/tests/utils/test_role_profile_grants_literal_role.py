# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Tests for #1504: the Role Profiles named "Verenigingen Auditor" and
"Verenigingen Treasurer" (verenigingen/fixtures/role_profile.json) did not
include the literal role of the same name in their own ``roles`` list, so a
user provisioned through the real Role Profile path
(``role_profiles`` + ``User.save()``, which runs
``User.populate_role_profile_roles()``) never actually held
"Verenigingen Auditor" / "Verenigingen Treasurer" in ``frappe.get_roles()``.

That made every permission check naming these roles literally (the
"ANBI Periodic Agreements" and "Donation Summary" report role lists, and the
SEPA Operation Audit Log DocPerm/``has_permission`` check) unreachable for
role-profile-provisioned Auditors/Treasurers -- see #1504 and the #1486
PR it was found in.

Maintainer ruling (2026-09-26): fix via option (a) -- make the Role Profiles
grant their literal roles. The "Verenigingen Treasurer" Role record did not
exist at all on test_site_2 (confirmed empirically), only referenced by two
Report role lists and a Critical Operation Rule fixture, so the fix also
adds that Role (verenigingen/fixtures/role.json) alongside granting it from
the Role Profile.

These tests drive the REAL provisioning path (``role_profiles`` +
``User.insert()/save()``, which is what ``User.populate_role_profile_roles()``
resyncs from), not a direct role grant -- a direct grant would pass even with
the bug reintroduced, which is the whole point of #1504.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles

TREASURER_ROLE_PROFILE = "Verenigingen Treasurer"


class TestRoleProfileGrantsLiteralRole(EnhancedTestCase):
    def _make_role_profile_user(self, profile, prefix):
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "RoleProfileLiteralTest",
                "send_welcome_email": 0,
                "enabled": 1,
                "role_profiles": [{"role_profile": profile}],
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        return email

    def test_auditor_role_profile_grants_literal_auditor_role(self):
        """A user provisioned through the "Verenigingen Auditor" Role Profile
        must end up holding the literal "Verenigingen Auditor" role -- the
        role every report/DocPerm that names it literally actually checks."""
        email = self._make_role_profile_user(Roles.AUDITOR, "auditor-literal")

        roles = frappe.get_roles(email)

        self.assertIn(
            Roles.AUDITOR,
            roles,
            f"'{Roles.AUDITOR}' Role Profile did not grant its own literal role; "
            f"got {sorted(roles)}",
        )

    def test_treasurer_role_profile_grants_literal_treasurer_role(self):
        """Same defect, Treasurer side. Also exercises that the
        'Verenigingen Treasurer' Role record exists at all -- it did not,
        on develop, so a User carrying this literal role in its profile
        would fail Link validation on save if the Role were still missing."""
        email = self._make_role_profile_user(TREASURER_ROLE_PROFILE, "treasurer-literal")

        roles = frappe.get_roles(email)

        self.assertIn(
            TREASURER_ROLE_PROFILE,
            roles,
            f"'{TREASURER_ROLE_PROFILE}' Role Profile did not grant its own literal role; "
            f"got {sorted(roles)}",
        )

    def test_treasurer_role_record_exists(self):
        """Regression guard for the missing Role record itself (not just the
        Role Profile grant): 'Verenigingen Treasurer' was referenced by the
        ANBI/Donation Summary report role lists and by
        fixtures/critical_operation_rule.json, but was never created as an
        actual Role -- confirmed missing via frappe.db.exists on
        test_site_2 before this fix."""
        self.assertTrue(
            frappe.db.exists("Role", TREASURER_ROLE_PROFILE),
            "'Verenigingen Treasurer' Role record does not exist",
        )
