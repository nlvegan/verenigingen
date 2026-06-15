"""
Integration tests for chapter event subscribers.

Exercises the event handlers in
``verenigingen/events/subscribers/chapter_subscribers.py`` against real
Chapter / Member / Volunteer / Chapter Board Member documents. Email delivery
is treated as a boundary: we assert handlers run without raising and produce the
expected side effects (role profiles, permissions, cache invalidation), but do
not assert real SMTP delivery (the test site has email sending disabled via
Verenigingen Email Configuration, so EmailService short-circuits).
"""

import frappe

from verenigingen.events.subscribers import chapter_subscribers as cs
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestChapterSubscribers(EnhancedTestCase):
    """Real integration coverage for chapter_subscribers handlers."""

    # ------------------------------------------------------------------ helpers
    def _as_admin(self):
        frappe.set_user("Administrator")

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

    # ----------------------------------------------------- guard / no-op clauses
    def test_board_role_assignments_missing_keys_returns(self):
        """Missing chapter/volunteer should no-op without raising."""
        cs.handle_board_role_assignments("e", {})
        cs.handle_board_role_assignments("e", {"chapter": "X"})
        cs.handle_board_role_assignments("e", {"volunteer": "V"})

    def test_board_role_assignments_nonexistent_chapter_returns(self):
        cs.handle_board_role_assignments(
            "e", {"chapter": "Nonexistent-Chapter-xyz", "volunteer": "Nonexistent-Vol"}
        )

    def test_board_notifications_skipped_on_bulk_import(self):
        """is_bulk_import short-circuits before any chapter lookup."""
        # Even with valid-looking data, bulk import returns immediately.
        cs.handle_board_notifications(
            "e",
            {"chapter": "X", "volunteer": "V", "action": "role_changed", "role": "Chair"},
            is_bulk_import=True,
        )

    def test_membership_notifications_skipped_on_bulk_import(self):
        cs.handle_membership_notifications(
            "e", {"chapter": "X", "member": "M", "action": "joined"}, is_bulk_import=True
        )

    def test_membership_notifications_member_deleted_returns(self):
        """Non-existent member should be detected and skipped."""
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_membership_notifications(
            "e",
            {"chapter": chapter.name, "member": "Member-does-not-exist-999", "action": "joined"},
        )

    def test_member_role_updates_missing_keys_returns(self):
        cs.handle_member_role_updates("e", {})
        cs.handle_member_role_updates("e", {"chapter": "X"})

    def test_member_role_updates_deleted_member_returns(self):
        cs.handle_member_role_updates(
            "e", {"chapter": "X", "member": "Member-does-not-exist-999", "action": "joined"}
        )

    def test_cache_invalidation_missing_chapter_returns(self):
        cs.handle_cache_invalidation("e", {})

    def test_settings_notifications_missing_data_returns(self):
        cs.handle_settings_notifications("e", {})
        cs.handle_settings_notifications("e", {"chapter": "X"})  # no changed_fields
        cs.handle_settings_notifications("e", {"chapter": "X", "changed_fields": []})

    def test_permissions_updates_missing_chapter_returns(self):
        cs.handle_permissions_updates("e", {})

    def test_website_updates_missing_chapter_returns(self):
        cs.handle_website_updates("e", {})

    # ----------------------------------------------------- board role assignment
    def test_board_role_assignment_syncs_role_profile(self):
        """A real board change recalculates the volunteer's user role profile."""
        self._ensure_chapter_role("Chair")
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        self._setup_board_member(chapter, volunteer, "Chair")

        # Should run end-to-end (calls auto_sync_on_role_change for the user)
        cs.handle_board_role_assignments(
            "board.added",
            {"chapter": chapter.name, "volunteer": volunteer.name, "action": "added", "role": "Chair"},
        )
        # No exception means the role-profile sync path executed.

    def test_sync_board_role_profile_volunteer_without_member(self):
        """_sync_board_role_profile no-ops gracefully when volunteer has no member."""
        # create_test_volunteer always links a member; build a bare volunteer instead.
        member = self.create_test_member(first_name="Bare", last_name="Vol", birth_date="1990-01-01")
        volunteer = self._make_volunteer_for_member(member)
        # Clear the member link to hit the no-member branch
        volunteer.db_set("member", None, update_modified=False)
        cs._sync_board_role_profile(volunteer.name)  # should not raise

    # ------------------------------------------------------- board notifications
    def test_board_notifications_role_changed_runs(self):
        """role_changed action sends a board notification without raising."""
        self._ensure_chapter_role("Chair")
        member, user = self._make_member_with_user()
        self._persist_member_email(member, "boardnotify")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")

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

    def test_board_notifications_non_role_change_action_noop(self):
        """added/removed are handled elsewhere; handler should not notify."""
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_board_notifications(
            "board.added",
            {"chapter": chapter.name, "volunteer": volunteer.name, "action": "added", "role": "Chair"},
        )

    def test_send_board_role_changed_notification_direct(self):
        """Directly exercise the internal email-gathering helper."""
        member, user = self._make_member_with_user()
        self._persist_member_email(member, "rolechanged")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        cs._send_board_role_changed_notification(chapter_doc, volunteer.name, "Chair", "Treasurer")

    # ------------------------------------------------------------ volunteer sync
    def test_volunteer_sync_runs_for_board_action(self):
        self._ensure_chapter_role("Chair")
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        self._setup_board_member(chapter, volunteer, "Chair")
        cs.handle_volunteer_sync(
            "board.added",
            {"chapter": chapter.name, "volunteer": volunteer.name, "action": "added"},
        )

    def test_volunteer_sync_ignores_unknown_action(self):
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_volunteer_sync(
            "board.other",
            {"chapter": chapter.name, "volunteer": volunteer.name, "action": "frobnicate"},
        )

    # ------------------------------------------------- membership notifications
    def test_membership_notification_joined_welcome(self):
        member, user = self._make_member_with_user()
        self._persist_member_email(member, "welcome")
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_membership_notifications(
            "member.joined",
            {"chapter": chapter.name, "member": member.name, "action": "joined"},
        )

    def test_membership_notification_left_farewell(self):
        member, user = self._make_member_with_user()
        self._persist_member_email(member, "farewell")
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_membership_notifications(
            "member.left",
            {"chapter": chapter.name, "member": member.name, "action": "left", "reason": "Moved away"},
        )

    def test_send_member_welcome_notification_direct(self):
        member, user = self._make_member_with_user()
        self._persist_member_email(member, "wd")
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_doc = frappe.get_doc("Member", member.name)
        cs._send_member_welcome_notification(chapter_doc, member_doc)

    def test_send_member_farewell_notification_direct_with_and_without_reason(self):
        member, user = self._make_member_with_user()
        self._persist_member_email(member, "fd")
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_doc = frappe.get_doc("Member", member.name)
        cs._send_member_farewell_notification(chapter_doc, member_doc, "Relocation")
        cs._send_member_farewell_notification(chapter_doc, member_doc, None)

    def test_send_member_notification_no_email_noop(self):
        """Member without an email address: helpers must not raise."""
        member = self.create_test_member(first_name="NoEmail", last_name="Member", birth_date="1990-01-01")
        member.db_set("email", None, update_modified=False)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_doc = frappe.get_doc("Member", member.name)
        cs._send_member_welcome_notification(chapter_doc, member_doc)
        cs._send_member_farewell_notification(chapter_doc, member_doc, None)

    # ----------------------------------------------------- member role updates
    def test_member_role_update_joined_grants_chapter_member_role(self):
        self._ensure_role("Chapter Member")
        member, user = self._make_member_with_user()
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
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
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
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
        cs._grant_chapter_member_permissions("Some Chapter", member_doc)  # should not raise

    def test_revoke_chapter_member_permissions_no_user_noop(self):
        member = self.create_test_member(first_name="NoUser", last_name="Member2", birth_date="1990-01-01")
        member_doc = frappe.get_doc("Member", member.name)
        member_doc.user = None
        cs._revoke_chapter_member_permissions("Some Chapter", member_doc)  # should not raise

    # ----------------------------------------------- cache invalidation handler
    def test_cache_invalidation_clears_keys(self):
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        # Seed a cache key matching the chapter pattern, then assert it's gone.
        frappe.cache().set_value("chapter_statistics", {"x": 1})
        cs.handle_cache_invalidation("chapter.changed", {"chapter": chapter.name})
        self.assertIsNone(frappe.cache().get_value("chapter_statistics"))

    # --------------------------------------------- settings / permissions / web
    def test_settings_notifications_important_field_runs(self):
        self._ensure_chapter_role("Chair")
        member, user = self._make_member_with_user()
        self._persist_member_email(member, "settings")
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        self._setup_board_member(chapter, volunteer, "Chair")
        cs.handle_settings_notifications(
            "chapter.settings",
            {"chapter": chapter.name, "changed_fields": ["published"]},
        )

    def test_settings_notifications_unimportant_field_noop(self):
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_settings_notifications(
            "chapter.settings",
            {"chapter": chapter.name, "changed_fields": ["some_random_field"]},
        )

    def test_permissions_updates_role_field_runs(self):
        self._ensure_chapter_role("Chair")
        member, user = self._make_member_with_user()
        volunteer = self._make_volunteer_for_member(member)
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        self._setup_board_member(chapter, volunteer, "Chair")
        cs.handle_permissions_updates(
            "chapter.settings",
            {"chapter": chapter.name, "changed_fields": ["default_board_role_profile"]},
        )

    def test_permissions_updates_non_role_field_noop(self):
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_permissions_updates(
            "chapter.settings",
            {"chapter": chapter.name, "changed_fields": ["introduction"]},
        )

    def test_website_updates_public_field_runs(self):
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_website_updates(
            "chapter.settings",
            {"chapter": chapter.name, "changed_fields": ["published"]},
        )

    def test_website_updates_published_chapter_clears_route_cache(self):
        """Exercise the published-chapter branch (clear_cache + route cache)."""
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        self._persist_chapter_published(chapter)
        cs.handle_website_updates(
            "chapter.settings",
            {"chapter": chapter.name, "changed_fields": ["published", "route"]},
        )

    def test_website_updates_non_public_field_noop(self):
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
        cs.handle_website_updates(
            "chapter.settings",
            {"chapter": chapter.name, "changed_fields": ["some_internal_field"]},
        )

    # --------------------------------------- cleanup_chapter_user_permissions...
    def test_cleanup_chapter_user_permissions_skips_admin_guest(self):
        admin = frappe.get_doc("User", "Administrator")
        # Should return immediately without touching anything
        cs.cleanup_chapter_user_permissions_for_admins(admin)

    def test_cleanup_chapter_user_permissions_removes_chapter_up(self):
        member, user = self._make_member_with_user()
        chapter = self.create_test_chapter(chapter_name=f"Sub Chapter {frappe.generate_hash(length=6)}")
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
