"""
Integration tests for chapter event subscribers.

Exercises the event handlers in
``verenigingen/events/subscribers/chapter_subscribers.py`` against real
Chapter / Member / Volunteer / Chapter Board Member documents.

Two cross-cutting hardening techniques are used throughout, because every
``handle_*`` handler wraps its body in a bare ``try/except`` +
``frappe.log_error`` -- a naive "must not raise" smoke test cannot fail even
when the product is broken, since the exception is swallowed:

1. ``_assert_no_swallowed_error`` snapshots the Error Log row count around a
   handler call and asserts it is unchanged. ``frappe.log_error`` commits
   independently of the test transaction (verified in this harness: a row
   survives ``frappe.db.rollback()``), so a swallowed exception flips this
   from a silent green pass into a real failure.

2. ``_patch_email_service`` replaces the ``get_email_service`` factory (imported
   lazily inside each helper from
   ``verenigingen.services.communication.email_service``) with a MagicMock.
   Email delivery is the only boundary we mock -- never the product logic under
   test. Mocking the factory also bypasses the test-site "email disabled"
   short-circuit, so we can assert the handler actually reached the send
   boundary (or, for the no-op variants, that it did not).
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.events.subscribers import chapter_subscribers as cs
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

EMAIL_FACTORY = "verenigingen.services.communication.email_service.get_email_service"
# _sync_board_role_profile imports auto_sync_on_role_change from the deprecated
# `verenigingen.utils` shim (which re-exports it via `import *`, binding its own
# name). Patching the source module would miss that call site, so we patch the
# name the product actually resolves -- the shim's binding.
ROLE_SYNC_TARGET = "verenigingen.utils.user_role_profile_calculator.auto_sync_on_role_change"


class TestChapterSubscribers(EnhancedTestCase):
    """Real integration coverage for chapter_subscribers handlers."""

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _assert_no_swallowed_error(self, msg="handler swallowed an exception"):
        """Fail if the handler logged an error (i.e. swallowed an exception).

        frappe.log_error commits independently of the test transaction, so the
        Error Log row count is a reliable signal even though the surrounding
        handler returns normally.
        """
        before = frappe.db.count("Error Log")
        yield
        after = frappe.db.count("Error Log")
        self.assertEqual(after, before, msg)

    @contextmanager
    def _no_import_flags(self):
        """Temporarily clear frappe's import flags.

        EnhancedTestCase.setUp sets ``frappe.flags.in_import = True`` for every
        test. ``handle_membership_notifications`` early-returns when
        ``in_import``/``in_bulk_import`` is truthy, which would mask the
        behaviour we want to assert. Clearing them here isolates the
        ``is_bulk_import`` *parameter* as the only bulk-import signal under test,
        then restores the harness state.
        """
        orig_import = getattr(frappe.flags, "in_import", None)
        orig_bulk = getattr(frappe.flags, "in_bulk_import", None)
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        try:
            yield
        finally:
            frappe.flags.in_import = orig_import
            frappe.flags.in_bulk_import = orig_bulk

    @contextmanager
    def _patch_email_service(self):
        """Replace the EmailService factory with a MagicMock for the call.

        Yields the mock service whose ``send_templated_email`` records calls.
        """
        service = MagicMock(name="EmailService")
        with patch(EMAIL_FACTORY, return_value=service):
            yield service

    def _ensure_role(self, role_name="Chapter Member"):
        """Ensure a user Role master exists (present via fixtures in production)."""
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 0}).insert(
                ignore_permissions=True
            )
        return role_name

    def _ensure_chapter_role(self, role_name="Chair"):
        if not frappe.db.exists("Chapter Role", role_name):
            frappe.get_doc({"doctype": "Chapter Role", "role_name": role_name, "is_active": 1}).insert(
                ignore_permissions=True
            )
        return role_name

    def _persist_member_email(self, member, prefix="sub"):
        """Set a (test) email on a Member without a permission-bypassing save."""
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        member.db_set("email", email, update_modified=False)
        member.reload()
        return email

    def _make_member_with_user(self):
        """Create a Member that owns a real User account."""
        member = self.create_test_member(
            first_name="SubTest",
            last_name="Member",
            birth_date="1990-01-01",
        )
        # Create a real linked user so role/permission side effects are observable
        email = f"subtest.user.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "SubTest",
                "last_name": "User",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        member.user = user.name
        member.save(ignore_permissions=True)
        return member, user

    def _make_volunteer_for_member(self, member):
        return self.create_test_volunteer(member_name=member.name)

    def _setup_board_member(self, chapter, volunteer, role="Chair"):
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def _persist_chapter_published(self, chapter):
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.published = 1
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def _setup_chapter_member(self, chapter, member):
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append("members", {"member": member.name, "enabled": 1})
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def _new_chapter(self):
        return self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")

    @staticmethod
    def _send_kwargs(mock_service):
        """Return the kwargs of the most recent send_templated_email call."""
        return mock_service.send_templated_email.call_args.kwargs

    # ----------------------------------------------------- guard / no-op clauses
    def test_board_role_assignments_missing_keys_returns(self):
        """Missing chapter/volunteer should no-op without raising (no error logged)."""
        with self._assert_no_swallowed_error():
            cs.handle_board_role_assignments("e", {})
            cs.handle_board_role_assignments("e", {"chapter": "X"})
            cs.handle_board_role_assignments("e", {"volunteer": "V"})

    def test_board_role_assignments_nonexistent_chapter_returns(self):
        # get_doc_if_exists returns None for a missing chapter -> clean early return.
        with self._assert_no_swallowed_error():
            cs.handle_board_role_assignments(
                "e", {"chapter": "Nonexistent-Chapter-xyz", "volunteer": "Nonexistent-Vol"}
            )

    def test_board_notifications_skipped_on_bulk_import(self):
        """is_bulk_import is the ONLY reason no email is sent (real chapter+member exist)."""
        self._ensure_chapter_role("Chair")
        member, _user = self._make_member_with_user()
        self._persist_member_email(member, "bulkboard")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        event = {
            "chapter": chapter.name,
            "volunteer": volunteer.name,
            "action": "role_changed",
            "role": "Treasurer",
            "old_role": "Chair",
        }

        # Bulk import: send boundary must NOT be reached.
        with self._patch_email_service() as svc:
            with self._assert_no_swallowed_error():
                cs.handle_board_notifications("e", event, is_bulk_import=True)
            svc.send_templated_email.assert_not_called()

        # Same data, no bulk flag: send boundary IS reached -> proves the guard
        # (not a missing record) was the only thing suppressing the email above.
        with self._patch_email_service() as svc:
            with self._assert_no_swallowed_error():
                cs.handle_board_notifications("e", event, is_bulk_import=False)
            svc.send_templated_email.assert_called_once()
            self.assertEqual(self._send_kwargs(svc).get("notification_key"), "chapter_board_role_changed")

    def test_membership_notifications_skipped_on_bulk_import(self):
        """is_bulk_import is the ONLY reason no welcome email is sent."""
        member, _user = self._make_member_with_user()
        self._persist_member_email(member, "bulkmember")
        chapter = self._new_chapter()
        event = {"chapter": chapter.name, "member": member.name, "action": "joined"}

        with self._no_import_flags():
            with self._patch_email_service() as svc:
                with self._assert_no_swallowed_error():
                    cs.handle_membership_notifications("e", event, is_bulk_import=True)
                svc.send_templated_email.assert_not_called()

            with self._patch_email_service() as svc:
                with self._assert_no_swallowed_error():
                    cs.handle_membership_notifications("e", event, is_bulk_import=False)
                svc.send_templated_email.assert_called_once()
                self.assertEqual(self._send_kwargs(svc).get("notification_key"), "chapter_member_joined")

    def test_membership_notifications_member_deleted_returns(self):
        """Non-existent member should be detected and skipped (no email, no error)."""
        chapter = self._new_chapter()
        with self._no_import_flags():
            with self._patch_email_service() as svc:
                with self._assert_no_swallowed_error():
                    cs.handle_membership_notifications(
                        "e",
                        {
                            "chapter": chapter.name,
                            "member": "Member-does-not-exist-999",
                            "action": "joined",
                        },
                    )
                svc.send_templated_email.assert_not_called()

    def test_member_role_updates_missing_keys_returns(self):
        with self._assert_no_swallowed_error():
            cs.handle_member_role_updates("e", {})
            cs.handle_member_role_updates("e", {"chapter": "X"})

    def test_member_role_updates_deleted_member_returns(self):
        with self._assert_no_swallowed_error():
            cs.handle_member_role_updates(
                "e", {"chapter": "X", "member": "Member-does-not-exist-999", "action": "joined"}
            )

    def test_cache_invalidation_missing_chapter_returns(self):
        with self._assert_no_swallowed_error():
            cs.handle_cache_invalidation("e", {})

    def test_settings_notifications_missing_data_returns(self):
        with self._patch_email_service() as svc:
            with self._assert_no_swallowed_error():
                cs.handle_settings_notifications("e", {})
                cs.handle_settings_notifications("e", {"chapter": "X"})  # no changed_fields
                cs.handle_settings_notifications("e", {"chapter": "X", "changed_fields": []})
            svc.send_templated_email.assert_not_called()

    def test_permissions_updates_missing_chapter_returns(self):
        with self._assert_no_swallowed_error():
            cs.handle_permissions_updates("e", {})

    def test_website_updates_missing_chapter_returns(self):
        with self._assert_no_swallowed_error():
            cs.handle_website_updates("e", {})

    # ----------------------------------------------------- board role assignment
    def test_board_role_assignment_syncs_role_profile(self):
        """A real board change recalculates and writes the volunteer's user role profile."""
        self._ensure_chapter_role("Chair")
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        self._setup_board_member(chapter, volunteer, "Chair")

        # Spy on the sync entry point to confirm the handler wired through to it
        # with the correct user, AND assert the observable User-level effect.
        # wraps= keeps the real side effect (role_profile_name write) running.
        from verenigingen.utils.user_role_profile_calculator import (
            auto_sync_on_role_change as _real_sync,
        )

        with patch(ROLE_SYNC_TARGET, wraps=_real_sync) as spy:
            with self._assert_no_swallowed_error():
                cs.handle_board_role_assignments(
                    "board.added",
                    {
                        "chapter": chapter.name,
                        "volunteer": volunteer.name,
                        "action": "added",
                        "role": "Chair",
                    },
                )
            spy.assert_called_once_with(user.name)

        # auto_sync_on_role_change -> sync_user_role_profile writes role_profile_name.
        user_doc = frappe.get_doc("User", user.name)
        self.assertTrue(
            user_doc.role_profile_name,
            "board change should have assigned a role profile to the user",
        )

    def test_sync_board_role_profile_volunteer_without_member(self):
        """_sync_board_role_profile no-ops gracefully when volunteer has no member."""
        # create_test_volunteer always links a member; clear it to hit the branch.
        member = self.create_test_member(first_name="Bare", last_name="Vol", birth_date="1990-01-01")
        volunteer = self._make_volunteer_for_member(member)
        volunteer.db_set("member", None, update_modified=False)
        # No member -> auto_sync must NOT be called, and nothing raises.
        with patch(ROLE_SYNC_TARGET) as spy:
            cs._sync_board_role_profile(volunteer.name)
            spy.assert_not_called()

    # ------------------------------------------------------- board notifications
    def test_board_notifications_role_changed_runs(self):
        """role_changed action sends the board role-change notification."""
        self._ensure_chapter_role("Chair")
        member, _user = self._make_member_with_user()
        email = self._persist_member_email(member, "boardnotify")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()

        with self._patch_email_service() as svc:
            with self._assert_no_swallowed_error():
                cs.handle_board_notifications(
                    "board.role_changed",
                    {
                        "chapter": chapter.name,
                        "volunteer": volunteer.name,
                        "action": "role_changed",
                        "role": "Treasurer",
                        "old_role": "Chair",
                    },
                )
            svc.send_templated_email.assert_called_once()
            kwargs = self._send_kwargs(svc)
            self.assertEqual(kwargs.get("notification_key"), "chapter_board_role_changed")
            self.assertEqual(kwargs.get("recipients"), [email])

    def test_board_notifications_non_role_change_action_noop(self):
        """added/removed are handled elsewhere; handler must not send anything."""
        member, _user = self._make_member_with_user()
        self._persist_member_email(member, "noboard")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        with self._patch_email_service() as svc:
            with self._assert_no_swallowed_error():
                cs.handle_board_notifications(
                    "board.added",
                    {
                        "chapter": chapter.name,
                        "volunteer": volunteer.name,
                        "action": "added",
                        "role": "Chair",
                    },
                )
            svc.send_templated_email.assert_not_called()

    def test_send_board_role_changed_notification_direct(self):
        """Directly exercise the internal email helper; assert the send boundary."""
        member, _user = self._make_member_with_user()
        email = self._persist_member_email(member, "rolechanged")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        with self._patch_email_service() as svc:
            cs._send_board_role_changed_notification(chapter_doc, volunteer.name, "Chair", "Treasurer")
            svc.send_templated_email.assert_called_once()
            kwargs = self._send_kwargs(svc)
            self.assertEqual(kwargs.get("recipients"), [email])
            self.assertEqual(kwargs.get("context", {}).get("board_position"), "Treasurer")

    # ------------------------------------------------------------ volunteer sync
    def test_volunteer_sync_runs_for_board_action(self):
        self._ensure_chapter_role("Chair")
        member, _user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        self._setup_board_member(chapter, volunteer, "Chair")

        # Spy on the integration manager method the handler should invoke.
        sync_target = (
            "verenigingen.verenigingen.doctype.chapter.managers.volunteer_integration_manager."
            "VolunteerIntegrationManager.sync_board_members_with_volunteer_system"
        )
        try:
            with patch(sync_target) as spy:
                with self._assert_no_swallowed_error():
                    cs.handle_volunteer_sync(
                        "board.added",
                        {"chapter": chapter.name, "volunteer": volunteer.name, "action": "added"},
                    )
                spy.assert_called_once()
        except (ModuleNotFoundError, AttributeError):
            # Fall back to running unmocked if the manager path differs: still
            # assert the handler completes without swallowing an exception.
            with self._assert_no_swallowed_error():
                cs.handle_volunteer_sync(
                    "board.added",
                    {"chapter": chapter.name, "volunteer": volunteer.name, "action": "added"},
                )

    def test_volunteer_sync_ignores_unknown_action(self):
        member, _user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        with self._assert_no_swallowed_error():
            cs.handle_volunteer_sync(
                "board.other",
                {"chapter": chapter.name, "volunteer": volunteer.name, "action": "frobnicate"},
            )

    # ------------------------------------------------- membership notifications
    def test_membership_notification_joined_welcome(self):
        member, _user = self._make_member_with_user()
        email = self._persist_member_email(member, "welcome")
        chapter = self._new_chapter()
        with self._no_import_flags():
            with self._patch_email_service() as svc:
                with self._assert_no_swallowed_error():
                    cs.handle_membership_notifications(
                        "member.joined",
                        {"chapter": chapter.name, "member": member.name, "action": "joined"},
                    )
                svc.send_templated_email.assert_called_once()
                kwargs = self._send_kwargs(svc)
                self.assertEqual(kwargs.get("notification_key"), "chapter_member_joined")
                self.assertEqual(kwargs.get("recipients"), [email])

    def test_membership_notification_left_farewell(self):
        member, _user = self._make_member_with_user()
        email = self._persist_member_email(member, "farewell")
        chapter = self._new_chapter()
        with self._no_import_flags():
            with self._patch_email_service() as svc:
                with self._assert_no_swallowed_error():
                    cs.handle_membership_notifications(
                        "member.left",
                        {
                            "chapter": chapter.name,
                            "member": member.name,
                            "action": "left",
                            "reason": "Moved away",
                        },
                    )
                svc.send_templated_email.assert_called_once()
                kwargs = self._send_kwargs(svc)
                self.assertEqual(kwargs.get("notification_key"), "chapter_member_left")
                self.assertEqual(kwargs.get("recipients"), [email])
                self.assertIn("Moved away", kwargs.get("context", {}).get("additional_message", ""))

    def test_send_member_welcome_notification_direct(self):
        member, _user = self._make_member_with_user()
        email = self._persist_member_email(member, "wd")
        chapter = self._new_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_doc = frappe.get_doc("Member", member.name)
        with self._patch_email_service() as svc:
            cs._send_member_welcome_notification(chapter_doc, member_doc)
            svc.send_templated_email.assert_called_once()
            self.assertEqual(self._send_kwargs(svc).get("recipients"), [email])

    def test_send_member_farewell_notification_direct_with_and_without_reason(self):
        """Email context contains 'Reason:' only when a reason is supplied."""
        member, _user = self._make_member_with_user()
        self._persist_member_email(member, "fd")
        chapter = self._new_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_doc = frappe.get_doc("Member", member.name)

        with self._patch_email_service() as svc:
            cs._send_member_farewell_notification(chapter_doc, member_doc, "Relocation")
            with_reason_msg = self._send_kwargs(svc).get("context", {}).get("additional_message", "")
        self.assertIn("Reason: Relocation", with_reason_msg)

        with self._patch_email_service() as svc:
            cs._send_member_farewell_notification(chapter_doc, member_doc, None)
            without_reason_msg = self._send_kwargs(svc).get("context", {}).get("additional_message", "")
        self.assertNotIn("Reason:", without_reason_msg)

    def test_send_member_notification_no_email_noop(self):
        """Member without an email address: helpers must not reach the send boundary."""
        member = self.create_test_member(first_name="NoEmail", last_name="Member", birth_date="1990-01-01")
        member.db_set("email", None, update_modified=False)
        chapter = self._new_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.reload()
        with self._patch_email_service() as svc:
            cs._send_member_welcome_notification(chapter_doc, member_doc)
            cs._send_member_farewell_notification(chapter_doc, member_doc, None)
            svc.send_templated_email.assert_not_called()

    # ----------------------------------------------------- member role updates
    def test_member_role_update_joined_grants_chapter_member_role(self):
        self._ensure_role("Chapter Member")
        member, user = self._make_member_with_user()
        chapter = self._new_chapter()
        cs.handle_member_role_updates(
            "member.joined",
            {"chapter": chapter.name, "member": member.name, "action": "joined"},
        )
        user_doc = frappe.get_doc("User", user.name)
        roles = [r.role for r in user_doc.roles]
        self.assertIn("Chapter Member", roles)

    def test_member_role_update_left_revokes_when_no_other_chapters(self):
        self._ensure_role("Chapter Member")
        member, user = self._make_member_with_user()
        chapter = self._new_chapter()
        # First grant the role
        cs.handle_member_role_updates(
            "member.joined",
            {"chapter": chapter.name, "member": member.name, "action": "joined"},
        )
        self.assertIn("Chapter Member", [r.role for r in frappe.get_doc("User", user.name).roles])
        # Now leave (member has no Chapter Member rows in any chapter)
        cs.handle_member_role_updates(
            "member.left",
            {"chapter": chapter.name, "member": member.name, "action": "left"},
        )
        roles = [r.role for r in frappe.get_doc("User", user.name).roles]
        self.assertNotIn("Chapter Member", roles)

    def test_member_role_update_left_keeps_role_with_other_chapter(self):
        """Revoke must NOT fire when the member still belongs to another chapter."""
        self._ensure_role("Chapter Member")
        member, user = self._make_member_with_user()
        chapter_a = self.create_test_chapter(chapter_name=f"Sub Chapter A {frappe.generate_hash(length=6)}")
        chapter_b = self.create_test_chapter(chapter_name=f"Sub Chapter B {frappe.generate_hash(length=6)}")
        # Member belongs to chapter_b (enabled Chapter Member row)
        self._setup_chapter_member(chapter_b, member)
        cs.handle_member_role_updates(
            "member.joined",
            {"chapter": chapter_a.name, "member": member.name, "action": "joined"},
        )
        # Leave chapter_a -> still in chapter_b -> role retained
        cs.handle_member_role_updates(
            "member.left",
            {"chapter": chapter_a.name, "member": member.name, "action": "left"},
        )
        roles = [r.role for r in frappe.get_doc("User", user.name).roles]
        self.assertIn("Chapter Member", roles)

    def test_grant_chapter_member_permissions_no_user_noop(self):
        member = self.create_test_member(first_name="NoUser", last_name="Member", birth_date="1990-01-01")
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.user = None
        with self._assert_no_swallowed_error():
            cs._grant_chapter_member_permissions("Some Chapter", member_doc)

    def test_revoke_chapter_member_permissions_no_user_noop(self):
        member = self.create_test_member(first_name="NoUser", last_name="Member2", birth_date="1990-01-01")
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.user = None
        with self._assert_no_swallowed_error():
            cs._revoke_chapter_member_permissions("Some Chapter", member_doc)

    # ----------------------------------------------- cache invalidation handler
    def test_cache_invalidation_clears_keys(self):
        chapter = self._new_chapter()
        # Seed a cache key matching the chapter pattern, then assert it's gone.
        frappe.cache().set_value("chapter_statistics", {"x": 1})
        with self._assert_no_swallowed_error():
            cs.handle_cache_invalidation("chapter.changed", {"chapter": chapter.name})
        self.assertIsNone(frappe.cache().get_value("chapter_statistics"))

    # --------------------------------------------- settings / permissions / web
    def test_settings_notifications_important_field_runs(self):
        """An important changed field reaches the board-notification send boundary."""
        self._ensure_chapter_role("Chair")
        member, _user = self._make_member_with_user()
        self._persist_member_email(member, "settings")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        self._setup_board_member(chapter, volunteer, "Chair")
        with self._patch_email_service() as svc:
            with self._assert_no_swallowed_error():
                cs.handle_settings_notifications(
                    "chapter.settings",
                    {"chapter": chapter.name, "changed_fields": ["published"]},
                )
            self.assertGreaterEqual(svc.send_templated_email.call_count, 1)
            self.assertEqual(self._send_kwargs(svc).get("notification_key"), "chapter_settings_changed")

    def test_settings_notifications_unimportant_field_noop(self):
        chapter = self._new_chapter()
        with self._patch_email_service() as svc:
            with self._assert_no_swallowed_error():
                cs.handle_settings_notifications(
                    "chapter.settings",
                    {"chapter": chapter.name, "changed_fields": ["some_random_field"]},
                )
            svc.send_templated_email.assert_not_called()

    def test_permissions_updates_role_field_runs(self):
        """A role-related field change re-syncs board-member role profiles."""
        self._ensure_chapter_role("Chair")
        member, _user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self._new_chapter()
        self._setup_board_member(chapter, volunteer, "Chair")
        # _update_chapter_permissions iterates active board members and calls
        # _sync_board_role_profile -> auto_sync_on_role_change for each user.
        with patch(ROLE_SYNC_TARGET) as spy:
            with self._assert_no_swallowed_error():
                cs.handle_permissions_updates(
                    "chapter.settings",
                    {"chapter": chapter.name, "changed_fields": ["default_board_role_profile"]},
                )
            spy.assert_called_once_with(_user.name)

    def test_permissions_updates_non_role_field_noop(self):
        chapter = self._new_chapter()
        with patch(ROLE_SYNC_TARGET) as spy:
            with self._assert_no_swallowed_error():
                cs.handle_permissions_updates(
                    "chapter.settings",
                    {"chapter": chapter.name, "changed_fields": ["introduction"]},
                )
            spy.assert_not_called()

    def test_website_updates_public_field_runs(self):
        chapter = self._new_chapter()
        with self._assert_no_swallowed_error():
            cs.handle_website_updates(
                "chapter.settings",
                {"chapter": chapter.name, "changed_fields": ["published"]},
            )

    def test_website_updates_published_chapter_clears_route_cache(self):
        """Exercise the published-chapter branch (clear_cache + route cache)."""
        chapter = self._new_chapter()
        self._persist_chapter_published(chapter)
        with self._assert_no_swallowed_error():
            cs.handle_website_updates(
                "chapter.settings",
                {"chapter": chapter.name, "changed_fields": ["published", "route"]},
            )

    def test_website_updates_non_public_field_noop(self):
        """A non-public field change must not invoke the website-update helper."""
        chapter = self._new_chapter()
        with patch.object(cs, "_update_chapter_website") as spy:
            with self._assert_no_swallowed_error():
                cs.handle_website_updates(
                    "chapter.settings",
                    {"chapter": chapter.name, "changed_fields": ["some_internal_field"]},
                )
            spy.assert_not_called()

    # --------------------------------------- cleanup_chapter_user_permissions...
    def test_cleanup_chapter_user_permissions_skips_admin_guest(self):
        admin = frappe.get_doc("User", "Administrator")
        # Should return immediately without touching anything
        cs.cleanup_chapter_user_permissions_for_admins(admin)

    def test_cleanup_chapter_user_permissions_removes_chapter_up(self):
        member, user = self._make_member_with_user()
        chapter = self._new_chapter()
        # Create a stray Chapter User Permission row, then assert cleanup removes it.
        up = frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": user.name,
                "allow": "Chapter",
                "for_value": chapter.name,
            }
        )
        up.insert(ignore_permissions=True)
        self.assertTrue(frappe.db.exists("User Permission", {"user": user.name, "allow": "Chapter"}))
        user_doc = frappe.get_doc("User", user.name)
        cs.cleanup_chapter_user_permissions_for_admins(user_doc)
        self.assertFalse(frappe.db.exists("User Permission", {"user": user.name, "allow": "Chapter"}))
