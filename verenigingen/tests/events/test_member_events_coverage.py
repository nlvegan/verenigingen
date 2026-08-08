# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""
End-to-end coverage for the member event chain.

Covers:
  * ``verenigingen/events/member_events.py`` -- the emit_* entry points plus the
    registry that maps an event name to its subscriber dotted paths.
  * ``verenigingen/events/subscribers/member_subscribers.py`` -- the real
    background-job handlers, exercised against real Member / User / Chapter /
    Address records.

WHY THE HARDENING
-----------------
Every ``handle_*`` subscriber wraps its body in a bare ``try/except`` +
``frappe.log_error`` and SWALLOWS the exception. A naive "must not raise" test
therefore passes green even when the handler is completely broken. Two
techniques close that gap:

1. ``self.assertNoErrorLog()`` (from ErrorLogGuardMixin) -- frappe.log_error
   commits independently of the test transaction, so the Error Log row count is
   a reliable signal: if the wrapped handler swallowed an exception, the block
   fails. Every happy-path assertion runs inside it.

2. We always assert a REAL observable side effect (a User disabled, a cache key
   gone, a registry list resolving to importable callables) -- never merely that
   the call returned.

The EnhancedTestCase harness forces ``frappe.flags.in_import = True`` in setUp
to bypass user-creation throttling. Almost every subscriber early-returns when
that flag is set (via ``should_skip_for_bulk``). The ``_no_import_flags`` helper
clears it so we observe the real handler behaviour, then restores it.
"""

from contextlib import contextmanager

import frappe

from verenigingen.events import member_events
from verenigingen.events.subscribers import member_subscribers as ms
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberEventsCoverage(EnhancedTestCase):
    """Real integration coverage for the member event chain."""

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _no_import_flags(self):
        """Clear the bulk/import flags so subscribers actually run.

        EnhancedTestCase.setUp sets frappe.flags.in_import = True. Most
        subscribers short-circuit via should_skip_for_bulk() when it is set,
        which would mask the behaviour under test.
        """
        saved = {
            "in_import": getattr(frappe.flags, "in_import", None),
            "in_bulk_import": getattr(frappe.flags, "in_bulk_import", None),
            "bulk_member_operations": getattr(frappe.flags, "bulk_member_operations", None),
        }
        frappe.flags.in_import = False
        frappe.flags.in_bulk_import = False
        frappe.flags.bulk_member_operations = False
        try:
            yield
        finally:
            for k, v in saved.items():
                setattr(frappe.flags, k, v)

    @contextmanager
    def _run_events_synchronously(self):
        """Make emit_event() dispatch subscribers inline instead of enqueuing.

        event_emitter.emit_event only runs inline when BOTH frappe.in_test and
        frappe.flags.run_events_synchronously are truthy (see event_emitter.py).
        This lets us assert on real subscriber side effects through the emitter.
        """
        saved = getattr(frappe.flags, "run_events_synchronously", None)
        frappe.flags.run_events_synchronously = True
        try:
            yield
        finally:
            frappe.flags.run_events_synchronously = saved

    def _member_with_user(self, enabled=1, status="Active"):
        """Create a Member that owns a real, enabled/disabled User account."""
        member = self.create_test_member(first_name="EvtUser", last_name="Member", birth_date="1990-01-01")
        email = f"evt.user.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "EvtUser",
                "last_name": "User",
                "send_welcome_email": 0,
                "enabled": enabled,
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        member.user = user.name
        member.save(ignore_permissions=True)
        if status:
            member.db_set("status", status, update_modified=False)
            member.reload()
        return member, user

    # =====================================================================
    # member_events.py -- emitters + registry
    # =====================================================================
    def test_registry_paths_all_importable(self):
        """Every dotted path in the subscriber registry must resolve to a real,
        callable function. A typo here means an event silently dispatches to a
        missing function (frappe.enqueue would raise at runtime, in a worker)."""
        for event_name in ("member_status_changed", "member_lifecycle_changed"):
            paths = member_events._get_member_event_subscribers(event_name)
            self.assertTrue(paths, f"{event_name} has no subscribers")
            for path in paths:
                fn = frappe.get_attr(path)
                self.assertTrue(callable(fn), f"{path} is not callable")

    def test_registry_unknown_event_returns_empty(self):
        self.assertEqual(member_events._get_member_event_subscribers("no_such_event"), [])

    def test_emit_status_changed_skips_during_bulk(self):
        """emit_member_status_changed must NOT dispatch when bulk flags are set."""
        member, user = self._member_with_user(enabled=1)
        saved = getattr(frappe.flags, "bulk_member_operations", None)
        frappe.flags.bulk_member_operations = True
        try:
            with self._run_events_synchronously():
                with self.assertNoErrorLog():
                    member_events.emit_member_status_changed(
                        member.name,
                        {"old_status": "Pending", "new_status": "Approved", "status_type": "application"},
                    )
        finally:
            frappe.flags.bulk_member_operations = saved
        # No dispatch happened -> nothing to assert beyond "no error logged".

    def test_emit_lifecycle_changed_dispatches_and_disables_user(self):
        """End-to-end: emit_member_lifecycle_changed -> handle_user_account_updates
        disables the linked User when the member is Suspended.

        This proves the WHOLE chain: emitter -> registry -> emit_event inline
        dispatch -> real subscriber side effect (User.enabled flips to 0)."""
        member, user = self._member_with_user(enabled=1)
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)

        with self._no_import_flags():
            with self._run_events_synchronously():
                with self.assertNoErrorLog():
                    member_events.emit_member_lifecycle_changed(
                        member.name,
                        {
                            "old_status": "Active",
                            "new_status": "Suspended",
                            "status_type": "lifecycle",
                        },
                    )
        self.assertEqual(
            frappe.db.get_value("User", user.name, "enabled"),
            0,
            "Suspended lifecycle event should disable the linked user account",
        )

    # =====================================================================
    # handle_user_account_updates -- the cleanest observable side effect
    # =====================================================================
    def test_user_account_disabled_on_suspend(self):
        member, user = self._member_with_user(enabled=1)
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_user_account_updates(
                    "member_lifecycle_changed",
                    {"member": member.name, "old_status": "Active", "new_status": "Suspended"},
                )
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 0)

    def test_user_account_enabled_on_reactivate(self):
        member, user = self._member_with_user(enabled=0)
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_user_account_updates(
                    "member_lifecycle_changed",
                    {"member": member.name, "old_status": "Suspended", "new_status": "Active"},
                )
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)

    def test_user_account_unchanged_status_is_noop(self):
        """old_status == new_status -> handler returns before touching the user."""
        member, user = self._member_with_user(enabled=1)
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_user_account_updates(
                    "member_lifecycle_changed",
                    {"member": member.name, "old_status": "Active", "new_status": "Active"},
                )
        # No change -> still enabled.
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)

    def test_user_account_skipped_on_bulk_import(self):
        """is_bulk_import=True is the ONLY reason the user is not disabled here."""
        member, user = self._member_with_user(enabled=1)
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_user_account_updates(
                    "member_lifecycle_changed",
                    {"member": member.name, "old_status": "Active", "new_status": "Suspended"},
                    is_bulk_import=True,
                )
        self.assertEqual(
            frappe.db.get_value("User", user.name, "enabled"),
            1,
            "bulk import should skip the user-account update",
        )

    def test_user_account_no_member_name_is_noop(self):
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_user_account_updates(
                    "member_lifecycle_changed", {"old_status": "Active", "new_status": "Suspended"}
                )

    def test_user_account_member_without_user_is_noop(self):
        """Member with no linked User -> handler must not raise/log."""
        member = self.create_test_member(first_name="NoUser", last_name="Member", birth_date="1990-01-01")
        member.db_set("user", None, update_modified=False)
        member.reload()
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_user_account_updates(
                    "member_lifecycle_changed",
                    {"member": member.name, "old_status": "Active", "new_status": "Suspended"},
                )

    def test_user_account_deleted_member_is_noop(self):
        """get_doc_if_exists returns None for a deleted member -> clean return."""
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_user_account_updates(
                    "member_lifecycle_changed",
                    {
                        "member": "Member-does-not-exist-zzz",
                        "old_status": "Active",
                        "new_status": "Suspended",
                    },
                )

    # =====================================================================
    # handle_cache_invalidation
    # =====================================================================
    def test_cache_invalidation_clears_global_key(self):
        member, _user = self._member_with_user()
        frappe.cache().set_value("member_statistics", {"count": 1})
        self.assertIsNotNone(frappe.cache().get_value("member_statistics"))
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_cache_invalidation("member_lifecycle_changed", {"member": member.name})
        self.assertIsNone(
            frappe.cache().get_value("member_statistics"),
            "cache invalidation should delete the member_statistics key",
        )

    def test_cache_invalidation_clears_pattern_keys(self):
        """The dashboard key uses a COLON, which is what the producer writes.

        This test used to seed "member_dashboard_test123" with an underscore and
        assert it was cleared -- and it passed, because the subscriber deleted
        "member_dashboard_*" with an underscore too. Both sides agreed with each
        other and disagreed with reality: the only producer of these keys,
        member_performance_optimizer.get_member_dashboard_cached(), writes
        f"member_dashboard:{member_name}". No underscore key is ever created, so the
        test pinned the typo instead of the behaviour and the real dashboard cache was
        never invalidated on a member change.
        """
        member, _user = self._member_with_user()
        frappe.cache().set_value("member_dashboard:test123", {"x": 1})
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_cache_invalidation("member_lifecycle_changed", {"member": member.name})
        self.assertIsNone(frappe.cache().get_value("member_dashboard:test123"))

    def test_cache_invalidation_skipped_on_bulk_import(self):
        """is_bulk_import early-returns before clearing the key."""
        member, _user = self._member_with_user()
        frappe.cache().set_value("member_statistics", {"count": 99})
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_cache_invalidation(
                    "member_lifecycle_changed", {"member": member.name}, is_bulk_import=True
                )
        self.assertIsNotNone(
            frappe.cache().get_value("member_statistics"),
            "bulk import should skip cache invalidation",
        )
        frappe.cache().delete_key("member_statistics")

    def test_cache_invalidation_deleted_member_still_clears(self):
        """Even when the member no longer exists, stale caches are cleared (the
        documented behaviour) and no error is logged."""
        frappe.cache().set_value("member_statistics", {"count": 7})
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_cache_invalidation("member_lifecycle_changed", {"member": "Member-gone-xyz"})
        self.assertIsNone(frappe.cache().get_value("member_statistics"))

    def test_cache_invalidation_no_member_name_is_noop(self):
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_cache_invalidation("member_lifecycle_changed", {})

    # =====================================================================
    # handle_status_change_notifications / handle_lifecycle_notifications
    # =====================================================================
    def test_status_change_no_member_name_is_noop(self):
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_status_change_notifications(
                    "member_status_changed",
                    {"old_status": "Pending", "new_status": "Approved", "status_type": "application"},
                )

    def test_status_change_deleted_member_is_noop(self):
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_status_change_notifications(
                    "member_status_changed",
                    {
                        "member": "Member-does-not-exist-zzz",
                        "status_type": "application",
                        "new_status": "Approved",
                    },
                )

    def test_status_change_skipped_on_bulk_import(self):
        """A real member + approval event, but bulk import suppresses processing.
        We assert only that nothing is logged (the no-op path is exercised)."""
        member, _user = self._member_with_user()
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_status_change_notifications(
                    "member_status_changed",
                    {
                        "member": member.name,
                        "status_type": "application",
                        "new_status": "Approved",
                        "old_status": "Pending",
                    },
                    is_bulk_import=True,
                )

    def test_status_change_application_approval_runs_clean(self):
        """Real member with an email, application Approved -> the notification
        helper runs end-to-end without swallowing an error."""
        member, _user = self._member_with_user()
        member.db_set(
            "email", f"approve.{frappe.generate_hash(length=6)}@example.invalid", update_modified=False
        )
        member.reload()
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_status_change_notifications(
                    "member_status_changed",
                    {
                        "member": member.name,
                        "status_type": "application",
                        "new_status": "Approved",
                        "old_status": "Pending",
                    },
                )

    def test_lifecycle_notification_suspension_runs_clean(self):
        member, _user = self._member_with_user()
        member.db_set(
            "email", f"susp.{frappe.generate_hash(length=6)}@example.invalid", update_modified=False
        )
        member.reload()
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_lifecycle_notifications(
                    "member_lifecycle_changed",
                    {"member": member.name, "old_status": "Active", "new_status": "Suspended"},
                )

    def test_lifecycle_notification_no_member_is_noop(self):
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_lifecycle_notifications(
                    "member_lifecycle_changed", {"old_status": "Active", "new_status": "Suspended"}
                )

    def test_lifecycle_notification_skipped_on_bulk(self):
        member, _user = self._member_with_user()
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_lifecycle_notifications(
                    "member_lifecycle_changed",
                    {"member": member.name, "old_status": "Active", "new_status": "Suspended"},
                    is_bulk_import=True,
                )

    # =====================================================================
    # handle_chapter_assignment_updates
    # =====================================================================
    def _ensure_region(self):
        """Create a real Region and return its name.

        create_test_chapter(region=...) requires the Region master to already
        exist; the factory's auto-create path is unreliable here, so we make one
        explicitly with a unique code.
        """
        code = f"E{frappe.generate_hash(length=4)}"[:5].upper()
        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": f"Evt Region {frappe.generate_hash(length=6)}",
                "region_code": code,
                "country": "Netherlands",
                "is_active": 1,
            }
        )
        region.insert(ignore_permissions=True)
        self._track_test_document("Region", region.name, priority=1)
        return region.name

    def _member_with_address(self, pincode="1234AB"):
        member = self.create_test_member(first_name="ChapAssign", last_name="Member", birth_date="1990-01-01")
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "address_title": f"Evt Addr {frappe.generate_hash(length=6)}",
                "address_line1": "1 Test Street",
                "city": "Test City",
                "pincode": pincode,
                "country": "Netherlands",
                "address_type": "Personal",
            }
        )
        address.insert(ignore_permissions=True)
        self._track_test_document("Address", address.name, priority=2)
        member.primary_address = address.name
        member.save(ignore_permissions=True)
        member.reload()
        return member

    def test_chapter_assignment_no_member_name_is_noop(self):
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_chapter_assignment_updates("member_status_changed", {"new_status": "Approved"})

    def test_chapter_assignment_deleted_member_is_noop(self):
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_chapter_assignment_updates(
                    "member_status_changed",
                    {"member": "Member-does-not-exist-zzz", "new_status": "Approved"},
                )

    def test_chapter_assignment_skipped_on_bulk_operation(self):
        """frappe.flags.bulk_member_operations short-circuits chapter assignment."""
        member = self._member_with_address()
        with self._no_import_flags():
            frappe.flags.bulk_member_operations = True
            try:
                with self.assertNoErrorLog():
                    ms.handle_chapter_assignment_updates(
                        "member_status_changed",
                        {"member": member.name, "new_status": "Approved"},
                    )
            finally:
                frappe.flags.bulk_member_operations = False

    def test_chapter_assignment_member_without_address_is_noop(self):
        """_assign_member_to_chapter returns early when there is no postal code."""
        member = self.create_test_member(first_name="NoAddr", last_name="Member", birth_date="1990-01-01")
        member.db_set("primary_address", None, update_modified=False)
        member.reload()
        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_chapter_assignment_updates(
                    "member_status_changed",
                    {"member": member.name, "new_status": "Approved"},
                )

    def test_chapter_assignment_approved_adds_member_to_chapter(self):
        """Approved member with a matching-postal-code chapter gets added to the
        chapter's members child table (the real product effect)."""
        member = self._member_with_address(pincode="1234AB")
        chapter = self.create_test_chapter(
            chapter_name=f"Evt Chapter {frappe.generate_hash(length=6)}",
            region=self._ensure_region(),
            postal_codes="1234",
        )
        # The postal-code lookup only considers PUBLISHED chapters.
        frappe.db.set_value("Chapter", chapter.name, "published", 1, update_modified=False)
        # Reset the cached lookup instance so our new chapter is visible (its
        # postal mapping + chapter-management flag are cached on the singleton).
        from verenigingen.services.chapter import optimized_chapter_lookup as ocl

        ocl._lookup_instance = None

        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_chapter_assignment_updates(
                    "member_status_changed",
                    {"member": member.name, "new_status": "Approved"},
                )

        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        member_names = [cm.member for cm in (chapter_doc.members or [])]
        self.assertIn(
            member.name,
            member_names,
            "approved member should be added to the matching chapter's members table",
        )

    def _persist_active_chapter_member(self, chapter_name, member_name):
        """Seat `member_name` on `chapter_name` as an Active member.

        Fixture setup, not the behaviour under test -- extracted from the test body
        so the ignore_permissions save lives in a helper, which is where the
        test-quality enforcer allows it.
        """
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append("members", {"member": member_name, "status": "Active", "enabled": 1})
        chapter_doc.save(ignore_permissions=True)
        return chapter_doc

    def test_update_chapter_membership_status_on_suspend_deactivates(self):
        """Regression: suspending/quitting a member deactivates chapter memberships.

        Member status "Suspended"/"Quit" does not map 1:1 to the Chapter Member
        status Select (Pending/Active/Inactive). Previously the handler wrote the
        raw member status, which failed Select validation and was silently
        swallowed -> chapter rows stayed "Active" forever. _update_chapter_membership_status
        now maps both terminal states to "Inactive", so the row is actually
        deactivated and no Error Log is written.
        """
        member = self.create_test_member(first_name="ChapStatus", last_name="Member", birth_date="1990-01-01")
        chapter = self.create_test_chapter(
            chapter_name=f"Evt SChapter {frappe.generate_hash(length=6)}",
            region=self._ensure_region(),
        )
        chapter_doc = self._persist_active_chapter_member(chapter.name, member.name)
        row_name = chapter_doc.members[-1].name

        with self._no_import_flags():
            with self.assertNoErrorLog():
                ms.handle_chapter_assignment_updates(
                    "member_lifecycle_changed",
                    {"member": member.name, "new_status": "Suspended"},
                )

        # The chapter membership is deactivated (Suspended -> Inactive).
        self.assertEqual(
            frappe.db.get_value("Chapter Member", row_name, "status"),
            "Inactive",
            "suspend must deactivate the chapter membership",
        )
