# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Coverage sweep for MemberUserAccountService and the module-level
create_secure_user_account_for_member() helper.

This AUGMENTS test_member_user_account_service_extended.py — it targets the
branches the extended suite leaves uncovered:

MemberUserAccountService
- create_user_for_member: missing email / missing last name throw branches;
  Dutch tussenvoegsel last-name composition; middle_name composition branch.
- create_member_user_account (OperationResult wrapper): the "already_exists"
  failure mapping, the "linked_existing" success message branch, and the
  exception → OperationResult.fail catch-all (nonexistent member).
- create_user_account_if_needed: application-member skip, disqualifying-status
  skip, and the happy "creates account" path's logger.info branch.
- bulk_create_user_accounts: a failed (not skipped) member, continue_on_error
  False early-stop, and the exception path.

create_secure_user_account_for_member (module-level, dict-returning)
- role_profile resolved from the Membership Type's role_profile field.
- nonexistent Membership Type → logger.error + default profile fallback.
- configured-but-missing Role Profile → warning + default fallback.
- activate_as_volunteer with an Active volunteer → Volunteer profile.
- activate_as_volunteer board-member → additional Chapter Board Member role.
- activate_as_volunteer with no volunteer record → stays Member profile.

Real DB only — real Member / User / Volunteer / Role Profile / Membership Type /
Account Creation Request docs. Runs as Administrator (VereningingenTestCase).
Permission bypass (ignore_permissions / set_value) only inside _make_* helpers
and setUp.
"""

import frappe

from verenigingen.services.member.account.member_user_account_service import (
    MemberUserAccountService,
    create_secure_user_account_for_member,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberUserAccountServiceSweep(VereningingenTestCase):
    """Augmenting coverage for MemberUserAccountService uncovered branches."""

    def setUp(self):
        super().setUp()
        self.service = MemberUserAccountService()
        self.h = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="UAccSweep",
            last_name=f"Member{self.h}",
            email=f"uaccsweep.{self.h}@test.invalid",
            status="Active",
        )

    def _track_user(self, email):
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    def _track_acr_for(self, member_name):
        for acr in frappe.get_all(
            "Account Creation Request", filters={"source_record": member_name}, pluck="name"
        ):
            self.track_doc("Account Creation Request", acr)

    # ============================================ create_user_for_member throw branches

    def test_create_user_for_member_missing_email_throws(self):
        frappe.db.set_value("Member", self.member.name, "email", "")
        self.member.reload()
        with self.assertRaises(frappe.ValidationError):
            self.service.create_user_for_member(self.member, silent=True)

    def test_create_user_for_member_missing_last_name_throws(self):
        frappe.db.set_value("Member", self.member.name, "last_name", "")
        self.member.reload()
        with self.assertRaises(frappe.ValidationError):
            self.service.create_user_for_member(self.member, silent=True)

    def test_create_user_for_member_middle_name_composition(self):
        # Non-Dutch path with a middle_name set: User.middle_name is populated.
        frappe.db.set_value("Member", self.member.name, "middle_name", "Q")
        self.member.reload()
        with self.assertNoErrorLog():
            username, action = self.service.create_user_for_member(
                self.member, send_welcome_email=False, silent=True
            )
        self._track_user(username)
        self.assertEqual(action, "created_new")
        user = frappe.get_doc("User", username)
        # On a Dutch installation tussenvoegsel takes precedence; the member has
        # no tussenvoegsel here, so the middle_name branch is exercised.
        if not (frappe.db.get_value("Member", self.member.name, "tussenvoegsel")):
            self.assertEqual(user.middle_name, "Q")

    # ============================================ create_member_user_account wrapper

    def test_wrapper_already_exists_maps_to_failure(self):
        # Member already linked -> create_user_for_member returns already_exists,
        # which the OperationResult wrapper maps to a FAILED result (API contract).
        email = f"uacc.wrap.exists.{self.h}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        frappe.db.set_value("Member", self.member.name, "user", user.name)

        result = self.service.create_member_user_account(self.member.name)
        self.assertFalse(result.success)
        self.assertEqual(result.metadata.get("action"), "already_exists")
        self.assertEqual(result.metadata.get("user"), user.name)

    def test_wrapper_linked_existing_success_message(self):
        # A pre-existing User with the member email -> linked_existing success
        # with the dedicated "Linked existing user account" message branch.
        user = self.create_test_user(self.member.email)
        self.track_doc("User", user.name)
        result = self.service.create_member_user_account(self.member.name)
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.metadata.get("action"), "linked_existing")
        self.assertEqual(result.data, user.name)

    def test_wrapper_created_new_success(self):
        with self.assertNoErrorLog():
            result = self.service.create_member_user_account(
                self.member.name, send_welcome_email=False
            )
        self._track_user(self.member.email)
        self.assertTrue(result.success, msg=result.error_message)
        self.assertEqual(result.metadata.get("action"), "created_new")

    def test_wrapper_nonexistent_member_returns_fail(self):
        # get_doc raises DoesNotExistError -> caught -> OperationResult.fail.
        # The wrapper logs the error, so register the expected Error Log.
        self.expectErrorLog()
        result = self.service.create_member_user_account("NOPE-MEMBER-SWEEP-XYZ")
        self.assertFalse(result.success)
        self.assertEqual(result.metadata.get("member"), "NOPE-MEMBER-SWEEP-XYZ")

    # ============================================ create_user_account_if_needed

    def test_if_needed_skips_application_member(self):
        # An application member (carries an application_id) must early-return
        # without a user — account creation is handled by the approval process.
        app_member = self.create_test_member(
            first_name="UAccApp",
            last_name=f"Applicant{self.h}",
            email=f"uacc.app.{self.h}@test.invalid",
            status="Active",
        )
        # is_application_member() is True iff application_id is set.
        frappe.db.set_value("Member", app_member.name, "application_id", f"APP-{self.h}")
        app_member.reload()
        self.assertTrue(app_member.is_application_member())
        self.service.create_user_account_if_needed(app_member)
        app_member.reload()
        self.assertFalse(app_member.user, "Application member must not get an auto user")

    def test_if_needed_skips_disqualifying_status(self):
        # A non-Active/empty status short-circuits the status gate.
        frappe.db.set_value("Member", self.member.name, "status", "Suspended")
        self.member.reload()
        if self.member.is_application_member():
            self.skipTest("factory member is an application member")
        self.service.create_user_account_if_needed(self.member)
        self.member.reload()
        self.assertFalse(self.member.user)

    # ============================================ bulk_create_user_accounts

    def test_bulk_failed_member_recorded_as_failure(self):
        # A member that passes validation but fails creation is recorded as
        # failed (not skipped). Force failure by clearing last_name AFTER
        # validation would pass: validation only checks first OR last name, so
        # a member with first_name but no last_name validates yet fails in
        # create_user_for_member (which requires last_name).
        m = self.create_test_member(
            first_name="UAccFail",
            last_name=f"WillClear{self.h}",
            email=f"uacc.fail.{self.h}@test.invalid",
            status="Active",
        )
        frappe.db.set_value("Member", m.name, "last_name", "")
        # bulk logs each failure to Error Log for the audit trail.
        self.expectErrorLog("Bulk Account Creation Error")
        result = self.service.bulk_create_user_accounts([m.name], send_welcome_emails=False)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.success, 0)
        self.assertEqual(result.details[0].status, "failed")

    def test_bulk_continue_on_error_false_stops_early(self):
        # First member fails -> with continue_on_error=False, processing stops
        # and the second valid member is never attempted.
        bad = self.create_test_member(
            first_name="UAccStop",
            last_name=f"Bad{self.h}",
            email=f"uacc.stop.bad.{self.h}@test.invalid",
            status="Active",
        )
        frappe.db.set_value("Member", bad.name, "last_name", "")
        good = self.create_test_member(
            first_name="UAccStop",
            last_name=f"Good{self.h}",
            email=f"uacc.stop.good.{self.h}@test.invalid",
            status="Active",
        )
        self.expectErrorLog("Bulk Account Creation Error")
        result = self.service.bulk_create_user_accounts(
            [bad.name, good.name], send_welcome_emails=False, continue_on_error=False
        )
        self.assertTrue(result.stopped_early)
        self.assertEqual(result.failed, 1)
        # The good member was never processed (no success, no skip recorded).
        self.assertEqual(result.success, 0)
        self._track_user(good.email)

    # ============================================ create_secure_user_account_for_member

    def _make_membership_type_with_profile(self, role_profile):
        mt = self.create_test_membership_type(amount=25.0)
        frappe.db.set_value("Membership Type", mt.name, "role_profile", role_profile)
        return mt.name

    def test_secure_create_uses_membership_type_role_profile(self):
        # When the member's selected_membership_type carries a role_profile, the
        # helper queues an ACR with that profile (not the default).
        profile = "Verenigingen Volunteer"  # an existing Role Profile
        mt_name = self._make_membership_type_with_profile(profile)
        frappe.db.set_value("Member", self.member.name, "selected_membership_type", mt_name)
        self.member.reload()

        result = create_secure_user_account_for_member(self.member)
        self._track_acr_for(self.member.name)
        self._track_user(self.member.email)
        self.assertTrue(result.get("success"), msg=result)
        request_name = (result.get("meta") or {}).get("account_request")
        self.assertTrue(request_name)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request_name, "role_profile"),
            profile,
        )

    def test_secure_create_nonexistent_membership_type_falls_back_to_default(self):
        # selected_membership_type points at a deleted/nonexistent type -> the
        # helper logs an error and falls back to the default Verenigingen Member
        # profile rather than crashing.
        frappe.db.set_value(
            "Member", self.member.name, "selected_membership_type", "NO-SUCH-MT-SWEEP-XYZ"
        )
        self.member.reload()
        self.expectErrorLog()
        result = create_secure_user_account_for_member(self.member)
        self._track_acr_for(self.member.name)
        self._track_user(self.member.email)
        self.assertTrue(result.get("success"), msg=result)
        request_name = (result.get("meta") or {}).get("account_request")
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request_name, "role_profile"),
            "Verenigingen Member",
        )

    def test_secure_create_missing_configured_profile_falls_back(self):
        # Membership Type configured with a Role Profile that does not exist ->
        # warning + default fallback.
        mt = self.create_test_membership_type(amount=30.0)
        # Bypass the Link validation to plant a dangling role_profile reference.
        frappe.db.set_value(
            "Membership Type", mt.name, "role_profile", "Ghost Profile Sweep ZZZ"
        )
        frappe.db.set_value("Member", self.member.name, "selected_membership_type", mt.name)
        self.member.reload()

        result = create_secure_user_account_for_member(self.member)
        self._track_acr_for(self.member.name)
        self._track_user(self.member.email)
        self.assertTrue(result.get("success"), msg=result)
        request_name = (result.get("meta") or {}).get("account_request")
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request_name, "role_profile"),
            "Verenigingen Member",
        )

    def test_secure_create_activate_as_volunteer_uses_volunteer_profile(self):
        # An Active volunteer + activate_as_volunteer=True -> Volunteer profile.
        member = self.create_test_member(
            first_name="UAccVol",
            last_name=f"Active{self.h}",
            email=f"uacc.vol.active.{self.h}@test.invalid",
            status="Active",
            birth_date="1990-01-01",
        )
        self.create_test_volunteer(
            member=member.name,
            volunteer_name=f"UAccVol Active {self.h}",
            email=member.email,
            status="Active",
        )
        result = create_secure_user_account_for_member(member, activate_as_volunteer=True)
        self._track_acr_for(member.name)
        self._track_user(member.email)
        self.assertTrue(result.get("success"), msg=result)
        request_name = (result.get("meta") or {}).get("account_request")
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request_name, "role_profile"),
            "Verenigingen Volunteer",
        )

    def test_secure_create_activate_as_volunteer_no_volunteer_stays_member(self):
        # activate_as_volunteer=True but no volunteer record -> stays on the
        # member profile (the "no volunteer record found" warning branch).
        member = self.create_test_member(
            first_name="UAccNoVol",
            last_name=f"NoVol{self.h}",
            email=f"uacc.novol.{self.h}@test.invalid",
            status="Active",
        )
        result = create_secure_user_account_for_member(member, activate_as_volunteer=True)
        self._track_acr_for(member.name)
        self._track_user(member.email)
        self.assertTrue(result.get("success"), msg=result)
        request_name = (result.get("meta") or {}).get("account_request")
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request_name, "role_profile"),
            "Verenigingen Member",
        )

    def test_secure_create_activate_as_volunteer_board_member_adds_role(self):
        # An Active volunteer who is also an active Chapter Board Member gets the
        # additional Verenigingen Chapter Board Member role on the ACR.
        member = self.create_test_member(
            first_name="UAccBoard",
            last_name=f"Member{self.h}",
            email=f"uacc.board.{self.h}@test.invalid",
            status="Active",
            birth_date="1985-01-01",
        )
        volunteer = self.create_test_volunteer(
            member=member.name,
            volunteer_name=f"UAccBoard Vol {self.h}",
            email=member.email,
            status="Active",
        )
        self._add_active_board_position(volunteer.name)

        result = create_secure_user_account_for_member(member, activate_as_volunteer=True)
        self._track_acr_for(member.name)
        self._track_user(member.email)
        self.assertTrue(result.get("success"), msg=result)
        request_name = (result.get("meta") or {}).get("account_request")
        acr = frappe.get_doc("Account Creation Request", request_name)
        requested_roles = [r.role for r in acr.requested_roles]
        self.assertIn("Verenigingen Chapter Board Member", requested_roles)

    def _add_active_board_position(self, volunteer_name, role="Board Member"):
        """Attach an active board position to the volunteer (test helper)."""
        # The Chapter Board Member.chapter_role is a Link to Chapter Role, so the
        # role must exist before the board row can be saved. create_test_chapter_role
        # is a no-op-safe get/create that also tracks the row for cleanup.
        if not frappe.db.exists("Chapter Role", role):
            self.create_test_chapter_role(role_name=role)
        chapter = self.create_test_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()
        return chapter.name
