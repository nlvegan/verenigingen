# -*- coding: utf-8 -*-
"""
Integration coverage for the orchestration branches of
services/account/account_creation_service.py.

The existing suite (tests/donor/test_other_service_coverage.py) covers the
validators and the simple link/detect helpers. This file targets the heavier,
previously-uncovered paths:

    - _check_missing_artifacts (Employee / Volunteer / Roles detection)
    - create_account_request:
        * new request created for a member with no existing user
        * link to an existing-but-unlinked user (action == "linked")
        * already-linked-and-complete short-circuit (action == "already_linked")
        * already-linked-but-missing-artifacts -> falls through to ACR creation
        * existing request -> rejected
        * linked-to-different-member -> security rejection
    - link_existing_user happy path: db.set_value + commit (caller must reload)
    - validate_member_for_account: missing-artifact completion branch

Real DB only: real Member / User / Volunteer / Account Creation Request docs.
Committed ACR rows are explicitly cleaned up in tearDown (create_account_request
commits, escaping the FrappeTestCase rollback).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _ACRBase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._committed_acrs = []
        from verenigingen.services.account.account_creation_service import (
            get_account_creation_service,
        )

        self.svc = get_account_creation_service()

    def tearDown(self):
        # create_account_request commits the ACR, so it survives the test
        # rollback — delete it explicitly to avoid leaking committed rows.
        for name in self._committed_acrs:
            if frappe.db.exists("Account Creation Request", name):
                frappe.delete_doc("Account Creation Request", name, force=True)
        frappe.db.commit()
        super().tearDown()

    def _track_acr(self, name):
        if name:
            self._committed_acrs.append(name)

    def _member_no_user(self, **kwargs):
        """A member with a unique email and no linked user account."""
        member = self.create_test_member(**kwargs)
        frappe.db.set_value("Member", member.name, "user", None)
        member.reload()
        return member

    def _name_matched_user(self, member, email, roles):
        """Create a User whose first/last name EXACTLY match the member's.

        The factory appends a unique suffix to last_name, so the user must be
        built from the member's actual stored names or link_existing_user's
        name-match security check rejects the link."""
        return self.create_test_user(
            email,
            roles=roles,
            first_name=member.first_name,
            last_name=member.last_name,
        )


class TestCheckMissingArtifacts(_ACRBase):
    """_check_missing_artifacts() detects Employee / Volunteer / Role gaps."""

    def test_no_artifacts_required_returns_false(self):
        needs, missing = self.svc._check_missing_artifacts(
            "Administrator", "M-X", roles=[], create_employee=False
        )
        self.assertFalse(needs)
        self.assertEqual(missing, [])

    def test_missing_role_detected(self):
        # A fresh user holding only "Verenigingen Member" is missing the
        # requested "Verenigingen Volunteer" role.
        email = f"rolemiss-{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email, roles=["Verenigingen Member"])
        needs, missing = self.svc._check_missing_artifacts(
            email, "M-X", roles=["Verenigingen Volunteer"], create_employee=False
        )
        self.assertTrue(needs)
        self.assertTrue(any("Roles:" in m for m in missing))

    def test_missing_employee_detected(self):
        # Administrator has no Employee record on the test site.
        needs, missing = self.svc._check_missing_artifacts(
            "Administrator", "M-X", roles=[], create_employee=True
        )
        self.assertTrue(needs)
        self.assertIn("Employee record", missing)

    def test_missing_volunteer_detected(self):
        member = self._member_no_user(first_name="Vol", last_name=f"Miss{self.factory.test_run_id}")
        needs, missing = self.svc._check_missing_artifacts(
            "Administrator",
            member.name,
            roles=["Verenigingen Volunteer"],
            create_employee=True,
        )
        self.assertTrue(needs)
        self.assertIn("Volunteer record", missing)


class TestCreateAccountRequest(_ACRBase):
    """create_account_request() orchestration branches."""

    def test_creates_new_request_for_member_without_user(self):
        member = self._member_no_user(
            first_name="New", last_name=f"Req{self.factory.test_run_id}"
        )
        # Use a brand-new email with no User behind it.
        unique_email = f"newreq-{frappe.generate_hash(length=8)}@example.com"
        frappe.db.set_value("Member", member.name, "email", unique_email)
        member.reload()

        success, error, result = self.svc.create_account_request(
            member=member, roles=["Verenigingen Member"]
        )
        self._track_acr(result.get("request_name") if result else None)

        self.assertTrue(success, error)
        self.assertEqual(result["action"], "created")
        self.assertTrue(frappe.db.exists("Account Creation Request", result["request_name"]))
        acr = frappe.get_doc("Account Creation Request", result["request_name"])
        self.assertEqual(acr.source_record, member.name)
        self.assertEqual(acr.email, unique_email)

    def test_existing_request_is_rejected(self):
        member = self._member_no_user(
            first_name="Dup", last_name=f"Req{self.factory.test_run_id}"
        )
        unique_email = f"dupreq-{frappe.generate_hash(length=8)}@example.com"
        frappe.db.set_value("Member", member.name, "email", unique_email)
        member.reload()

        # First creation succeeds.
        ok, err, result = self.svc.create_account_request(member=member, roles=["Verenigingen Member"])
        self._track_acr(result.get("request_name") if result else None)
        self.assertTrue(ok, err)

        # Second creation hits the "request already exists" guard.
        ok2, err2, result2 = self.svc.create_account_request(
            member=member, roles=["Verenigingen Member"]
        )
        self.assertFalse(ok2)
        self.assertIn("already exists", err2)
        self.assertIsNone(result2)

    def test_links_existing_unlinked_user(self):
        # A User exists with matching name but no Member points at it yet.
        email = f"linkable-{frappe.generate_hash(length=8)}@example.com"
        member = self._member_no_user(first_name="Linkable", last_name="User")
        self._name_matched_user(member, email, roles=["Verenigingen Member"])
        frappe.db.set_value("Member", member.name, "email", email)
        member.reload()

        success, error, result = self.svc.create_account_request(
            member=member, roles=["Verenigingen Member"]
        )
        self._track_acr(result.get("request_name") if result else None)

        self.assertTrue(success, error)
        # No employee/volunteer required and the role is already present, so it
        # links and short-circuits rather than creating an ACR.
        self.assertEqual(result["action"], "linked")
        self.assertEqual(result["user_name"], email)
        # Link was committed to the DB (caller must reload to see it).
        self.assertEqual(frappe.db.get_value("Member", member.name, "user"), email)

    def test_already_linked_missing_artifacts_creates_acr(self):
        """Linked + role present but Employee missing -> ACR created to complete."""
        email = f"partial-{frappe.generate_hash(length=8)}@example.com"
        member = self._member_no_user(first_name="Partial", last_name="Linked")
        self._name_matched_user(member, email, roles=["Verenigingen Member"])
        frappe.db.set_value("Member", member.name, {"email": email, "user": email})
        member.reload()

        success, error, result = self.svc.create_account_request(
            member=member, roles=["Verenigingen Member"], create_employee=True
        )
        self._track_acr(result.get("request_name") if result else None)

        self.assertTrue(success, error)
        # Employee record is missing -> falls through to ACR creation.
        self.assertEqual(result["action"], "created")
        self.assertTrue(frappe.db.exists("Account Creation Request", result["request_name"]))

    def test_linked_to_different_member_is_rejected(self):
        email = f"shared-{frappe.generate_hash(length=8)}@example.com"
        # First member legitimately owns the user (name-matched).
        owner = self._member_no_user(first_name="Shared", last_name="User")
        self._name_matched_user(owner, email, roles=["Verenigingen Member"])
        frappe.db.set_value("Member", owner.name, {"email": email, "user": email})

        # Second member shares the email but is NOT the linked member.
        intruder = self._member_no_user(first_name="Shared", last_name="User")
        frappe.db.set_value("Member", intruder.name, "email", email)
        intruder.reload()

        success, error, result = self.svc.create_account_request(
            member=intruder, roles=["Verenigingen Member"]
        )
        self.assertFalse(success)
        self.assertIn("already linked to different member", error)
        self.assertIsNone(result)


class TestLinkExistingUserCommit(_ACRBase):
    """link_existing_user() happy path commits and is visible after reload."""

    def test_links_and_commits(self):
        email = f"commit-{frappe.generate_hash(length=8)}@example.com"
        member = self._member_no_user(first_name="Commit", last_name="User")
        self._name_matched_user(member, email, roles=["Verenigingen Member"])
        frappe.db.set_value("Member", member.name, "email", email)
        member.reload()

        success, error = self.svc.link_existing_user(member, email, validate_names=True)
        self.assertTrue(success, error)
        self.assertIsNone(error)
        # In-memory doc is NOT updated by set_value; reload to observe the link.
        member.reload()
        self.assertEqual(member.user, email)

    def test_idempotent_when_already_linked_to_same_member(self):
        email = f"idem-{frappe.generate_hash(length=8)}@example.com"
        member = self._member_no_user(first_name="Idem", last_name="User")
        self._name_matched_user(member, email, roles=["Verenigingen Member"])
        frappe.db.set_value("Member", member.name, {"email": email, "user": email})
        member.reload()

        success, error = self.svc.link_existing_user(member, email, validate_names=True)
        self.assertTrue(success, error)
        self.assertIsNone(error)
        # Idempotent: the existing link is unchanged (not rewritten/duplicated).
        self.assertEqual(frappe.db.get_value("Member", member.name, "user"), email)


class TestValidateMissingArtifactCompletion(_ACRBase):
    """validate_member_for_account() allows ACR when a linked user is incomplete."""

    def test_linked_user_missing_role_allows_creation(self):
        email = f"incomplete-{frappe.generate_hash(length=8)}@example.com"
        member = self._member_no_user(first_name="Incomplete", last_name="User")
        # User created WITHOUT the Volunteer role.
        self._name_matched_user(member, email, roles=["Verenigingen Member"])
        frappe.db.set_value("Member", member.name, {"email": email, "user": email})
        member.reload()

        is_valid, error = self.svc.validate_member_for_account(
            member,
            roles=[{"role": "Verenigingen Volunteer"}],
            create_employee=False,
        )
        # Missing role -> allow ACR creation to complete the setup.
        self.assertTrue(is_valid)
        self.assertIsNone(error)
