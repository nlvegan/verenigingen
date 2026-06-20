# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Extended tests for MemberUserAccountService covering the methods that the
existing test_member_user_account_service.py does NOT exercise:

- validate_member_for_user_account (all rejection branches + valid path)
- create_user_for_member (direct, exception-raising path + linking)
- create_organization_user_for_member
- create_user_account_if_needed (after_save hook gate)
- bulk_create_user_accounts (success / skip / mixed)
- create_secure_user_account_for_member (module-level, dict-returning)

These exercise real Member / User / Role docs against the DB (no business-logic
mocking) and run as the default Administrator user.
"""

import frappe
from frappe.utils import random_string

from verenigingen.services.member.account.member_user_account_service import (
    MemberUserAccountService,
    create_secure_user_account_for_member,
    get_member_user_account_service,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberUserAccountServiceExtended(VereningingenTestCase):
    """Cover the uncovered branches of MemberUserAccountService."""

    def setUp(self):
        super().setUp()
        self.service = MemberUserAccountService()
        self.h = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="UAccSvc",
            last_name=f"Member{self.h}",
            email=f"uaccsvc.{self.h}@test.invalid",
            status="Active",
        )

    def _track_user(self, email):
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    # ============================================================ validate_member_for_user_account

    def test_validate_nonexistent_member_invalid(self):
        result = self.service.validate_member_for_user_account("NOPE-MEMBER-XYZ")
        self.assertFalse(result.valid)
        self.assertTrue(any("does not exist" in i for i in result.issues))

    def test_validate_member_already_has_user_invalid(self):
        # Link a user, then validation must reject (already has account).
        email = f"uacc.has.{self.h}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        self.member.reload()

        result = self.service.validate_member_for_user_account(self.member.name)
        self.assertFalse(result.valid)
        self.assertEqual(result.existing_user, user.name)
        self.assertTrue(any("already has user account" in i for i in result.issues))

    def test_validate_member_missing_email_invalid(self):
        frappe.db.set_value("Member", self.member.name, "email", "")
        self.member.reload()
        result = self.service.validate_member_for_user_account(self.member)
        self.assertFalse(result.valid)
        self.assertTrue(any("email address" in i for i in result.issues))

    def test_validate_member_disqualifying_status_invalid(self):
        # "Banned" is not in the permitted {Active, Approved, ""} set.
        frappe.db.set_value("Member", self.member.name, "status", "Banned")
        self.member.reload()
        result = self.service.validate_member_for_user_account(self.member)
        self.assertFalse(result.valid)
        self.assertTrue(any("not suitable" in i for i in result.issues))

    def test_validate_duplicate_email_in_other_member_invalid(self):
        # A second member sharing the email makes validation report a duplicate.
        other = self.create_test_member(
            first_name="UAccDup",
            last_name=f"Other{self.h}",
            email=f"uaccdup.{self.h}@test.invalid",
            status="Active",
        )
        shared = self.member.email
        frappe.db.set_value("Member", other.name, "email", shared)
        other.reload()

        result = self.service.validate_member_for_user_account(other)
        self.assertFalse(result.valid)
        self.assertEqual(result.duplicate_member, self.member.name)
        self.assertTrue(any("already used by member" in i for i in result.issues))

    def test_validate_valid_member_passes(self):
        with self.assertNoErrorLog():
            result = self.service.validate_member_for_user_account(self.member.name)
        self.assertTrue(result.valid, msg=result.issues)
        self.assertEqual(result.member_name, self.member.name)
        self.assertEqual(result.member_email, self.member.email)
        self.assertIsNone(result.existing_user)

    def test_validate_existing_user_is_informational_not_blocking(self):
        # A pre-existing User with the member's email is informational (we can
        # link to it), so the member is still valid.
        user = self.create_test_user(self.member.email)
        self.track_doc("User", user.name)
        result = self.service.validate_member_for_user_account(self.member.name)
        self.assertTrue(result.valid, msg=result.issues)
        self.assertEqual(result.existing_user, user.name)

    def test_validate_result_to_dict_shape(self):
        result = self.service.validate_member_for_user_account(self.member.name)
        d = result.to_dict()
        self.assertIn("valid", d)
        self.assertIn("issues", d)
        self.assertEqual(d["member_name"], self.member.name)

    # ============================================================ create_user_for_member (direct)

    def test_create_user_for_member_already_exists_branch(self):
        # Member already linked to a user -> returns (user, "already_exists").
        email = f"uacc.already.{self.h}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        self.member.reload()

        username, action = self.service.create_user_for_member(self.member, silent=True)
        self.assertEqual(username, user.name)
        self.assertEqual(action, "already_exists")

    def test_create_user_for_member_missing_first_name_throws(self):
        # create_user_for_member raises (unlike the OperationResult wrapper).
        frappe.db.set_value("Member", self.member.name, "first_name", "")
        self.member.reload()
        with self.assertRaises(frappe.ValidationError):
            self.service.create_user_for_member(self.member, silent=True)

    def test_create_user_for_member_creates_new(self):
        # send_welcome_email=False avoids the (unconfigured-SMTP) welcome-mail
        # error log on this dev bench; the creation path itself is what we pin.
        with self.assertNoErrorLog():
            username, action = self.service.create_user_for_member(
                self.member, send_welcome_email=False, silent=True
            )
        self._track_user(username)
        self.assertEqual(action, "created_new")
        self.assertTrue(frappe.db.exists("User", username))
        # Ownership of the member transfers to the new user.
        self.member.reload()
        self.assertEqual(self.member.user, username)
        self.assertEqual(frappe.db.get_value("Member", self.member.name, "owner"), username)

    def test_create_user_for_member_links_existing(self):
        # A pre-existing User with the member's email is linked (not duplicated).
        user = self.create_test_user(self.member.email)
        self.track_doc("User", user.name)
        username, action = self.service.create_user_for_member(self.member, silent=True)
        self.assertEqual(username, user.name)
        self.assertEqual(action, "linked_existing")
        self.member.reload()
        self.assertEqual(self.member.user, user.name)

    # ============================================================ create_organization_user_for_member

    def test_create_organization_user_creates_with_supplied_email(self):
        # Org-user creation assigns the member role profile via the v16 role_profiles
        # child table; on older Frappe (CI) that append raises and logs an Error,
        # tripping assertNoErrorLog. Skip there — it runs on the v16 dev/prod sites.
        if not frappe.get_meta("User").has_field("role_profiles"):
            self.skipTest("requires Frappe v16 User.role_profiles child table")
        org_email = f"uacc.org.{self.h}@org.invalid"
        with self.assertNoErrorLog():
            username, action = self.service.create_organization_user_for_member(
                self.member,
                email=org_email,
                first_name="OrgFirst",
                last_name="OrgLast",
                send_welcome_email=False,
            )
        self._track_user(username)
        self.assertEqual(action, "created_new")
        self.assertEqual(username, org_email)
        user = frappe.get_doc("User", username)
        self.assertEqual(user.first_name, "OrgFirst")
        self.assertEqual(user.user_type, "System User")
        self.member.reload()
        self.assertEqual(self.member.user, org_email)

    def test_create_organization_user_requires_email(self):
        with self.assertRaises(frappe.ValidationError):
            self.service.create_organization_user_for_member(
                self.member, email="", first_name="X"
            )

    def test_create_organization_user_already_exists_short_circuits(self):
        existing_email = f"uacc.orgexists.{self.h}@org.invalid"
        user = self.create_test_user(existing_email)
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        self.member.reload()
        username, action = self.service.create_organization_user_for_member(
            self.member, email="brand.new@org.invalid", first_name="X"
        )
        self.assertEqual(username, user.name)
        self.assertEqual(action, "already_exists")

    # ============================================================ create_user_account_if_needed

    def test_create_user_account_if_needed_skips_when_user_set(self):
        # When member already has a user, the hook is a no-op (no new user).
        email = f"uacc.ifneeded.set.{self.h}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        self.member.reload()
        # Should return without creating anything / raising.
        self.service.create_user_account_if_needed(self.member)
        self.member.reload()
        self.assertEqual(self.member.user, user.name)

    def test_create_user_account_if_needed_skips_when_no_email(self):
        frappe.db.set_value("Member", self.member.name, "email", "")
        self.member.reload()
        self.service.create_user_account_if_needed(self.member)
        self.member.reload()
        self.assertFalse(self.member.user)

    def test_create_user_account_if_needed_creates_for_active_member(self):
        # Active, no user, has email, not an application member -> creates account.
        # (Guard: only run the create path if the member is not an application member.)
        if self.member.is_application_member():
            self.skipTest("factory member is an application member")
        self.service.create_user_account_if_needed(self.member)
        self.member.reload()
        self.assertTrue(self.member.user)
        self._track_user(self.member.user)

    # ============================================================ bulk_create_user_accounts

    def test_bulk_create_all_valid(self):
        m2 = self.create_test_member(
            first_name="UAccBulk",
            last_name=f"Two{self.h}",
            email=f"uacc.bulk2.{self.h}@test.invalid",
            status="Active",
        )
        result = self.service.bulk_create_user_accounts(
            [self.member.name, m2.name], send_welcome_emails=False
        )
        self._track_user(self.member.email)
        self._track_user(m2.email)
        self.assertEqual(result.total, 2)
        self.assertEqual(result.success, 2)
        self.assertEqual(result.failed, 0)
        self.assertEqual(len(result.details), 2)
        d = result.to_dict()
        self.assertEqual(d["success"], 2)

    def test_bulk_create_skips_invalid_member(self):
        # A member that fails validation (already has a user) is skipped, not failed.
        email = f"uacc.bulkskip.{self.h}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", self.member.name, "user", user.name)

        result = self.service.bulk_create_user_accounts(
            [self.member.name], send_welcome_emails=False
        )
        self.assertEqual(result.total, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.success, 0)
        self.assertEqual(result.details[0].status, "skipped")

    def test_bulk_create_empty_list(self):
        result = self.service.bulk_create_user_accounts([])
        self.assertEqual(result.total, 0)
        self.assertEqual(result.success, 0)
        self.assertFalse(result.stopped_early)

    # ============================================================ create_secure_user_account_for_member

    # create_secure_user_account_for_member returns OperationResult.to_dict(),
    # which nests action / account_request under the "meta" key.
    @staticmethod
    def _meta(result):
        return result.get("meta") or {}

    def test_secure_create_links_existing_user(self):
        # When a User already exists for the member's email, the helper links it
        # (db.set_value + commit) and returns action linked_existing.
        user = self.create_test_user(self.member.email)
        self.track_doc("User", user.name)
        self.member.reload()
        result = create_secure_user_account_for_member(self.member)
        self.assertTrue(result.get("success"))
        self.assertEqual(self._meta(result).get("action"), "linked_existing")
        self.assertEqual(
            frappe.db.get_value("Member", self.member.name, "user"), self.member.email
        )

    def test_secure_create_existing_request_short_circuits(self):
        # An existing in-progress/completed ACR makes the helper report
        # action existing_request without queueing a new one.
        request = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": self.member.name,
                "email": self.member.email,
                "full_name": self.member.full_name,
                "role_profile": "Verenigingen Member",
                "business_justification": "test",
                "requested_roles": [{"role": "Verenigingen Member"}],
            }
        )
        request.insert()
        self.track_doc("Account Creation Request", request.name)
        frappe.db.set_value("Account Creation Request", request.name, "status", "In Progress")

        result = create_secure_user_account_for_member(self.member)
        self.assertTrue(result.get("success"))
        self.assertEqual(self._meta(result).get("action"), "existing_request")
        self.assertEqual(self._meta(result).get("account_request"), request.name)

    def test_secure_create_queues_new_request(self):
        # No existing user, no existing request -> queues a secure ACR.
        result = create_secure_user_account_for_member(self.member)
        self._track_user(self.member.email)
        self.assertTrue(result.get("success"), msg=result)
        self.assertEqual(self._meta(result).get("action"), "queued_secure")
        request_name = self._meta(result).get("account_request")
        self.assertTrue(request_name)
        self.track_doc("Account Creation Request", request_name)

    def test_singleton_accessor(self):
        s1 = get_member_user_account_service()
        s2 = get_member_user_account_service()
        self.assertIsInstance(s1, MemberUserAccountService)
        self.assertIsInstance(s2, MemberUserAccountService)
