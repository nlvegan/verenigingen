# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Volunteer.status -> role profile recalculation, end to end (#688).

`volunteer_role_profile_hooks.on_volunteer_status_change` was registered under the
key "Verenigingen Volunteer" -- a Role name, not a DocType -- from the commit that
created volunteer.json, so it had never fired. #688 moved it to "Volunteer". These
tests exist because the handler had no coverage at all, which is why nine months of
dead registration went unnoticed.

They drive a real `Volunteer.save()` and read the User's stored role profiles. No
mock stands between the save and the profile: the whole point is to prove the hook
is WIRED, and a patched sync would prove only that a function can be called.

The controls matter as much as the assertions. `sync_user_role_profile` reports
`changed` by comparing stored state against a recomputation, so a test that only
watches a profile move cannot tell "the hook did it" from "it was already going to
move". Each test below therefore establishes the pre-save state explicitly and
asserts the direction, and `test_status_change_is_what_moves_the_profile` pins the
negative: a save that does NOT change status must leave the profile alone.
"""

import frappe

from verenigingen.services.member.account.user_role_profile_calculator import (
    get_user_role_profiles,
    sync_user_role_profile,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

PROFILE_VOLUNTEER = "Verenigingen Volunteer"
PROFILE_MEMBER = "Verenigingen Member"

# calculate_user_role_profile confers PROFILE_VOLUNTEER via is_active_volunteer(),
# which reads Volunteer.status through {"status": ["in", ["Active", "Onboarding"]]}.
ACTIVE_STATUSES = ["Active", "Onboarding"]
INACTIVE_STATUSES = ["New", "Inactive", "Retired"]


class TestVolunteerStatusRoleProfileSync(EnhancedTestCase):
    """The restored hook, exercised through a real Volunteer save."""

    def _volunteer_with_user(self, status="Active"):
        """A Volunteer whose member has an enabled User account.

        Every link has to exist or the handler returns early for a reason the test
        is not about: it resolves Volunteer -> Member -> Member.user and does
        nothing when either is missing.
        """
        run = f"{frappe.generate_hash(length=8)}0"
        email = f"volstatus-{run}@example.com"

        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "VolStatus",
                "send_welcome_email": 0,
                "enabled": 1,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        user.insert(ignore_permissions=True)
        self.factory.track_document("User", user.name, priority=2)

        member = self.create_test_member(
            first_name="VolStatus", last_name=f"Sync{run[:6]}", email=email, birth_date="1985-01-01"
        )
        member.db_set("status", "Active")
        member.db_set("user", email)

        volunteer = self.create_test_volunteer(member_name=member.name)
        volunteer.db_set("status", status)
        volunteer.reload()
        return volunteer, email

    def _set_status(self, volunteer, status):
        """Change status through a real save, so the doc_event actually dispatches."""
        volunteer.reload()
        volunteer.status = status
        volunteer.save(ignore_permissions=True)
        return volunteer

    # ------------------------------------------------------------------ wiring

    def test_the_hook_is_registered_on_the_volunteer_doctype(self):
        """Read frappe's dispatch map, not our own hooks dict.

        get_doc_hooks() is what Document.run_method() consults; our dict having the
        right key proves nothing if the framework never builds it into that map.
        """
        doc_hooks = frappe.get_doc_hooks()

        self.assertIsNotNone(doc_hooks.get("Volunteer"), "Volunteer dispatches no doc_events")
        self.assertIn(
            "verenigingen.services.volunteer.volunteer_role_profile_hooks.on_volunteer_status_change",
            doc_hooks["Volunteer"].get("on_update", []),
        )

    # ------------------------------------------------------- behaviour on save

    def test_going_inactive_withdraws_the_volunteer_profile(self):
        """Active -> Inactive downgrades the profile on a real save."""
        volunteer, email = self._volunteer_with_user(status="Active")
        sync_user_role_profile(email, dry_run=False)
        self.assertEqual([PROFILE_VOLUNTEER], get_user_role_profiles(email))

        self._set_status(volunteer, "Inactive")

        self.assertEqual(
            [PROFILE_MEMBER],
            get_user_role_profiles(email),
            "A volunteer set Inactive kept the volunteer role profile — the hook did "
            "not fire, or did not reach sync_user_role_profile.",
        )

    def test_reactivation_restores_the_volunteer_profile(self):
        """Inactive -> Active upgrades it again.

        The reverse direction is its own test because the downgrade could pass while
        the upgrade silently does not: sync_user_role_profile takes an extra branch
        on the way up (_ensure_employee_for_profile) that the way down never reaches.
        """
        volunteer, email = self._volunteer_with_user(status="Inactive")
        sync_user_role_profile(email, dry_run=False)
        self.assertEqual([PROFILE_MEMBER], get_user_role_profiles(email))

        self._set_status(volunteer, "Active")

        self.assertEqual([PROFILE_VOLUNTEER], get_user_role_profiles(email))

    def test_only_a_status_change_moves_the_profile(self):
        """Both legs, in one test, on one fixture.

        The negative leg alone would pass just as happily with the hook unregistered,
        so it proves nothing on its own — that is exactly how the dead registration
        survived. Pairing it with a status-changing save on the same volunteer makes
        the difference between the two saves the only thing that can explain the
        outcome.
        """
        volunteer, email = self._volunteer_with_user(status="Active")
        sync_user_role_profile(email, dry_run=False)
        self.assertEqual([PROFILE_VOLUNTEER], get_user_role_profiles(email))

        # Drive the stored profile out of sync so a recalculation is visible either way.
        user_doc = frappe.get_doc("User", email)
        user_doc.set("role_profiles", [])
        user_doc.save(ignore_permissions=True)
        self.assertEqual([], get_user_role_profiles(email))

        # NEGATIVE leg: a save that does not touch status must not recalculate.
        volunteer.reload()
        volunteer.note = "unrelated edit"
        volunteer.save(ignore_permissions=True)
        self.assertEqual(
            [],
            get_user_role_profiles(email),
            "A save that did not change status still recalculated the role profile — "
            "the handler is running on every save, not on status transitions.",
        )

        # POSITIVE leg: the very next save, differing only in that status moved.
        self._set_status(volunteer, "Inactive")
        self.assertEqual(
            [PROFILE_MEMBER],
            get_user_role_profiles(email),
            "The status-changing save did not recalculate either — the hook is not "
            "firing at all, so the negative leg above was vacuous.",
        )

    def test_every_status_option_lands_on_the_expected_profile(self):
        """All five Select options, so a renamed option cannot pass silently."""
        for status in ACTIVE_STATUSES + INACTIVE_STATUSES:
            with self.subTest(status=status):
                expected = PROFILE_VOLUNTEER if status in ACTIVE_STATUSES else PROFILE_MEMBER
                # Start from the opposite side so the save always changes status.
                start = "Inactive" if status in ACTIVE_STATUSES else "Active"
                volunteer, email = self._volunteer_with_user(status=start)
                sync_user_role_profile(email, dry_run=False)

                self._set_status(volunteer, status)

                self.assertEqual([expected], get_user_role_profiles(email))

    def test_status_options_still_match_the_calculators_active_set(self):
        """The premise, checked against the DocType rather than against this file.

        ACTIVE_STATUSES above is a literal. If someone adds a sixth Volunteer status,
        the subTest sweep would keep passing while the new option is untested, so read
        the Select options from the meta and require every one of them to be covered.
        """
        options = frappe.get_meta("Volunteer").get_field("status").options.split("\n")
        options = [o.strip() for o in options if o.strip()]

        self.assertCountEqual(
            options,
            ACTIVE_STATUSES + INACTIVE_STATUSES,
            "Volunteer.status options changed. Re-check is_active_volunteer() in "
            "user_role_profile_calculator.py and update the lists above.",
        )

    def test_a_disabled_user_is_skipped(self):
        """The termination case is deliberately NOT covered by this hook.

        Termination runs DeactivateUserAccountOperation BEFORE
        TerminateVolunteerRecordsOperation (termination_execution_service.py), so by
        the time the volunteer goes Inactive the User is already disabled and
        sync_user_role_profile returns `skipped: user_disabled` rather than syncing.
        Pinned so nobody reads the tests above as proof that termination withdraws
        the volunteer profile — it does not. See the follow-up issue in doc_events.py.

        Run against an enabled twin taking the identical transition, because "the
        profile did not move" is equally consistent with "the hook never fired", and
        a test that cannot tell those apart is the defect this whole PR is about.
        """
        disabled_vol, disabled_email = self._volunteer_with_user(status="Active")
        enabled_vol, enabled_email = self._volunteer_with_user(status="Active")
        for email in (disabled_email, enabled_email):
            sync_user_role_profile(email, dry_run=False)
            self.assertEqual([PROFILE_VOLUNTEER], get_user_role_profiles(email))

        frappe.db.set_value("User", disabled_email, "enabled", 0)

        self._set_status(disabled_vol, "Inactive")
        self._set_status(enabled_vol, "Inactive")

        self.assertEqual(
            [PROFILE_MEMBER],
            get_user_role_profiles(enabled_email),
            "CONTROL: the enabled twin did not resync either, so this test says "
            "nothing about the disabled account.",
        )
        self.assertEqual(
            [PROFILE_VOLUNTEER],
            get_user_role_profiles(disabled_email),
            "The sync ran for a disabled user. If sync_user_role_profile stopped "
            "skipping them, re-read the comment it carries about _ensure_employee_"
            "for_profile force-enabling the account.",
        )
