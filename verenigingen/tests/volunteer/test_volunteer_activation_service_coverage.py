"""
Real-integration coverage for
``verenigingen/services/volunteer/volunteer_activation_service.py``.

The module's public entry point is ``activate_volunteer_record(member)``. It
wraps its whole body in a bare ``try/except`` that routes failures to
``safe_log_error`` (title "Volunteer activation error") and SWALLOWS — so a
naive "did not raise" smoke test passes even when the product is broken. Two
hardening techniques (mirroring tests/events/test_team_events_coverage.py) are
used here:

1. ``self.assertNoErrorLog()`` around every happy/no-op path. ``log_error``
   commits independently of the test transaction, so a swallowed exception
   flips a silent green pass into a real failure.

2. Real side-effect assertions — the Volunteer row actually flips to "Active",
   the orphaned-by-email volunteer is actually relinked to the member, the
   member's ``volunteer_record`` is actually populated, and re-activation is
   idempotent — not just "the call returned".

The existing TestVolunteerActivationService in
``test_volunteer_service_coverage.py`` only smoke-tests ``_log_upgrade_result``
and wraps ``activate_volunteer_record`` in ``except Exception: pass`` (so it
cannot fail). This file deliberately does NOT duplicate those weak methods; it
asserts the real status/link side effects instead.

The user-account upgrade branch (``if member.user:`` ->
``upgrade_member_to_volunteer_user``) IS exercised end to end here. Despite an
earlier sweep's conclusion, that path is a *pure local-DB* operation (it flips
the linked User's ``user_type`` from "Website User" to "System User" and resets
``block_modules``) with NO external API call. The ``@critical_api`` decorator on
``upgrade_member_to_volunteer_user`` runs unconditionally and converts its
``OperationResult`` into the nested dict the service consumes; under
``frappe.flags.in_test`` the framework treats the call as CLI, so rate-limit /
IP / request-size / CSRF gates are skipped and an Administrator-context test
reaches the real upgrade. We assert the real ``user_type`` flip, the
already-upgraded no-op, and the create-fallback variant.
"""

import frappe

from verenigingen.services.volunteer.volunteer_activation_service import (
    _log_upgrade_result,
    activate_volunteer_record,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerActivationServiceCoverage(EnhancedTestCase):
    """Real integration coverage for activate_volunteer_record + helpers."""

    # ------------------------------------------------------------------ helpers
    def _make_member(self, prefix="act"):
        """Member with a real, unique email and no linked user (avoids the
        heavy System-User upgrade branch)."""
        member = self.create_test_member(
            first_name="Activate", last_name=prefix.title(), birth_date="1990-01-01"
        )
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        member.db_set("email", email, update_modified=False)
        member.reload()
        return member, email

    def _make_volunteer(self, member, status="New"):
        return self.create_test_volunteer(member_name=member.name, status=status)

    def _make_website_user_for_member(self, member, prefix="vu"):
        """Create a real ``Website User`` and link it to ``member.user``.

        ``create_test_user`` switches to Administrator internally (a factory
        helper, not a test-body privileged write), so this stays enforcer
        compliant. The user is created as a *Website User* so the activation
        upgrade branch has something real to flip to *System User*.
        """
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        # No roles -> avoids the System-Manager default; we want a plain
        # Website User as the genuine pre-upgrade state.
        user = self.create_test_user(email, roles=[])
        # Force the pre-upgrade state directly (db_set bypasses the User save
        # hooks and avoids ignore_permissions in the test body).
        user.db_set("user_type", "Website User", update_modified=False)
        user.reload()
        member.db_set("user", user.name, update_modified=False)
        member.reload()
        return user

    # ============================================================ _log_upgrade_result
    # The convenience logger has four distinct branches; the existing file covers
    # success + meta-None + plain failure. These add the two uncovered shapes.
    def test_log_upgrade_result_failure_non_dict_error(self):
        """error that is not a dict -> errors defaults to [] (no crash)."""
        with self.assertNoErrorLog():
            _log_upgrade_result({"success": False, "error": "a bare string"}, "ctx")

    def test_log_upgrade_result_failure_with_error_list(self):
        """error dict with an 'errors' list -> joined into the warning."""
        with self.assertNoErrorLog():
            _log_upgrade_result(
                {"success": False, "error": {"errors": ["role missing", "user gone"]}},
                "ctx",
            )

    def test_log_upgrade_result_success_with_message(self):
        with self.assertNoErrorLog():
            _log_upgrade_result({"success": True, "meta": {"message": "done"}}, "ctx")

    # ============================================================ existing-volunteer path
    def test_activate_flips_existing_volunteer_to_active(self):
        """An existing volunteer linked by ``member`` is set to Active and the
        member's ``volunteer_record`` is populated."""
        member, _ = self._make_member("flip")
        volunteer = self._make_volunteer(member, status="New")
        self.assertEqual(volunteer.status, "New")

        with self.assertNoErrorLog():
            activate_volunteer_record(member)

        volunteer.reload()
        self.assertEqual(volunteer.status, "Active", "existing volunteer must be flipped to Active")
        # member.volunteer_record should now point at the volunteer.
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "volunteer_record"),
            volunteer.name,
            "member.volunteer_record must be linked to the activated volunteer",
        )

    def test_activate_is_idempotent_on_already_active(self):
        """Re-activating an already-Active volunteer is a clean no-op (still
        Active, still linked, no error)."""
        member, _ = self._make_member("idem")
        volunteer = self._make_volunteer(member, status="Active")

        with self.assertNoErrorLog():
            activate_volunteer_record(member)
            # Second call - must remain stable and not error.
            activate_volunteer_record(member)

        volunteer.reload()
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "volunteer_record"),
            volunteer.name,
        )

    # ===================================================== user-account upgrade branch
    def test_activate_upgrades_linked_website_user_to_system_user(self):
        """Existing volunteer + member.user is a Website User -> the user is
        really upgraded to System User (lines 80-87, the previously-"ceiling"
        branch).

        This is a pure-DB upgrade: no external API, no banned mock. We assert
        the real side effect (user_type flips) plus the usual activation effects.
        """
        member, _ = self._make_member("upg")
        volunteer = self._make_volunteer(member, status="New")
        user = self._make_website_user_for_member(member)
        self.assertEqual(
            frappe.db.get_value("User", user.name, "user_type"),
            "Website User",
            "precondition: linked user starts as a Website User",
        )

        with self.assertNoErrorLog():
            activate_volunteer_record(member)

        volunteer.reload()
        self.assertEqual(volunteer.status, "Active")
        # The real upgrade side effect: Website User -> System User.
        self.assertEqual(
            frappe.db.get_value("User", user.name, "user_type"),
            "System User",
            "the linked Website User must be upgraded to System User on activation",
        )

    def test_activate_upgrade_is_noop_when_user_already_system_user(self):
        """member.user is already a System User -> upgrade returns the
        already-upgraded success branch; activation stays clean (still exercises
        lines 80-87 + the success arm of _log_upgrade_result)."""
        member, _ = self._make_member("alreadysys")
        volunteer = self._make_volunteer(member, status="New")
        user = self._make_website_user_for_member(member)
        # Promote up front so the upgrade is a no-op.
        user.db_set("user_type", "System User", update_modified=False)
        user.reload()

        with self.assertNoErrorLog():
            activate_volunteer_record(member)

        volunteer.reload()
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(
            frappe.db.get_value("User", user.name, "user_type"),
            "System User",
            "an already-System User stays a System User (no-op upgrade)",
        )

    # ============================================================ orphaned-by-email path
    def test_activate_relinks_orphaned_volunteer_found_by_email(self):
        """A volunteer whose ``member`` link is broken but whose ``email``
        matches the member is relinked, renamed, and activated.

        Build two members sharing the activation target's email path: create a
        volunteer linked to a *throwaway* member, then null its ``member`` link
        so ``get_volunteer_for_member`` cannot find it and the by-email lookup
        is exercised.
        """
        member, email = self._make_member("orphan")

        # Orphan volunteer: linked to a different member, but carrying the
        # target member's email; then sever its member link.
        other, _ = self._make_member("orphan-other")
        volunteer = self._make_volunteer(other, status="New")
        volunteer.db_set("email", email, update_modified=False)
        volunteer.db_set("member", None, update_modified=False)
        volunteer.reload()
        self.assertIsNone(frappe.db.get_value("Volunteer", volunteer.name, "member"))

        with self.assertNoErrorLog():
            activate_volunteer_record(member)

        volunteer.reload()
        # Relinked to the target member ...
        self.assertEqual(volunteer.member, member.name, "orphaned volunteer must be relinked by email")
        # ... renamed to the member's full name ...
        self.assertEqual(volunteer.volunteer_name, member.full_name)
        # ... and activated.
        self.assertEqual(volunteer.status, "Active")
        self.assertEqual(
            frappe.db.get_value("Member", member.name, "volunteer_record"),
            volunteer.name,
        )

    # ============================================================ create-fallback path
    def test_activate_creates_volunteer_when_none_exists(self):
        """No volunteer exists and member is interested_in_volunteering ->
        a new volunteer is created and activated."""
        member, _ = self._make_member("create")
        member.db_set("interested_in_volunteering", 1, update_modified=False)
        member.reload()
        self.assertFalse(frappe.db.exists("Volunteer", {"member": member.name}))

        with self.assertNoErrorLog():
            activate_volunteer_record(member)

        vol_name = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        self.assertTrue(vol_name, "a volunteer should have been created for the interested member")
        self.assertEqual(
            frappe.db.get_value("Volunteer", vol_name, "status"),
            "Active",
            "the newly-created volunteer must be activated",
        )
        if vol_name:
            self._track_test_document("Volunteer", vol_name, priority=1)

    def test_activate_creates_volunteer_and_upgrades_linked_user(self):
        """No volunteer exists, member is interested AND has a linked Website
        User -> a volunteer is created/activated and the user is upgraded
        (the create-fallback upgrade branch, lines 111-118)."""
        member, _ = self._make_member("createupg")
        member.db_set("interested_in_volunteering", 1, update_modified=False)
        member.reload()
        user = self._make_website_user_for_member(member)
        self.assertFalse(frappe.db.exists("Volunteer", {"member": member.name}))

        with self.assertNoErrorLog():
            activate_volunteer_record(member)

        vol_name = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        self.assertTrue(vol_name, "a volunteer should have been created for the interested member")
        self.assertEqual(
            frappe.db.get_value("Volunteer", vol_name, "status"),
            "Active",
            "the newly-created volunteer must be activated",
        )
        self.assertEqual(
            frappe.db.get_value("User", user.name, "user_type"),
            "System User",
            "the linked Website User must be upgraded during create-fallback activation",
        )
        if vol_name:
            self._track_test_document("Volunteer", vol_name, priority=1)

    def test_activate_no_volunteer_and_not_interested_is_clean_noop(self):
        """No existing volunteer + member not interested -> create_volunteer_record
        returns None; activation is a clean no-op (no error, no volunteer)."""
        member, _ = self._make_member("nointerest")
        member.db_set("interested_in_volunteering", 0, update_modified=False)
        member.reload()

        with self.assertNoErrorLog():
            activate_volunteer_record(member)

        self.assertFalse(
            frappe.db.exists("Volunteer", {"member": member.name}),
            "uninterested member without a volunteer must not get one created",
        )

    # ===================================================== outer swallow-and-log contract
    def test_activate_swallows_and_logs_on_save_failure(self):
        """The whole body is wrapped in a try/except that routes failures to
        ``safe_log_error`` and SWALLOWS them, so a volunteer-activation hiccup
        never blocks membership approval (lines 122-123).

        Trigger a *real* save failure with no mock: point the volunteer's
        ``member`` link at a deleted Member, then activate. The activation's
        ``volunteer.save()`` re-validates the dangling link and raises
        ``LinkValidationError``, which the outer handler must catch + log
        rather than propagate.
        """
        member, email = self._make_member("swallow")

        # An orphaned-by-email volunteer (member link severed) so the by-email
        # relink path runs. That path sets
        #   volunteer.volunteer_name = member.full_name or "{first} {last}".strip()
        # then saves. Blank the member's name fields (a real possibility for a
        # partially-imported/corrupt member) so volunteer_name resolves to ""
        # and the save trips Volunteer's mandatory volunteer_name -> the outer
        # handler must catch + log it, not propagate.
        other, _ = self._make_member("swallow-other")
        volunteer = self._make_volunteer(other, status="New")
        volunteer.db_set("email", email, update_modified=False)
        volunteer.db_set("member", None, update_modified=False)
        volunteer.reload()

        member.db_set("full_name", "", update_modified=False)
        member.db_set("first_name", "", update_modified=False)
        member.db_set("last_name", "", update_modified=False)
        member.reload()

        # The outer handler logs via safe_log_error (title "Volunteer activation
        # error"); register it so the automatic tearDown check tolerates it.
        self.expectErrorLog("Volunteer activation error")

        # Must NOT raise regardless of the internal mandatory-field failure.
        activate_volunteer_record(member)

        # The volunteer was NOT activated (the relink save failed before the
        # status flip), proving the failure path really fired.
        self.assertEqual(
            frappe.db.get_value("Volunteer", volunteer.name, "status"),
            "New",
            "a failed relink must leave the volunteer un-activated",
        )

    # ============================================================ permission gate
    def test_activate_throws_without_volunteer_write_permission(self):
        """The function refuses to run for a user lacking Volunteer write.

        A freshly created member-portal User (no Volunteer write) must trip the
        ``frappe.has_permission("Volunteer", "write")`` guard and raise.
        """
        member, _ = self._make_member("perm")
        volunteer = self._make_volunteer(member, status="New")

        user = self._make_unprivileged_user()
        with self.as_user(user):
            self.assertFalse(frappe.has_permission("Volunteer", "write"))
            # The guard uses frappe.throw -> ValidationError (not PermissionError).
            with self.assertRaises(frappe.ValidationError):
                activate_volunteer_record(member)

        # Status untouched by the rejected attempt.
        volunteer.reload()
        self.assertEqual(volunteer.status, "New")

    # ------------------------------------------------------------------ helper
    def _make_unprivileged_user(self, prefix="noperm"):
        """A real enabled User with no roles (so no Volunteer write)."""
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "NoPerm",
                "last_name": "User",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        return email
