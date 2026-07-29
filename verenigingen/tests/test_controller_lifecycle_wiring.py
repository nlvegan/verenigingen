# verenigingen/tests/test_controller_lifecycle_wiring.py
"""Controller lifecycle methods must be named after events Frappe actually calls.

Frappe invokes a controller method only when framework code passes that method
name to Document.run_method(). `after_save` is never passed — the string appears
nowhere in frappe's Python — so a controller that defines `def after_save(self)` has
written a method that is never called. It looks wired, it resolves, it lints, and
it silently does nothing. Same for `after_validate`.

Scope: SERVER-side only. `after_save` IS a real client-side form event
(frappe/public/js/frappe/form/form.js), used by this app in chapter.js,
chapter_role.js, member.js and volunteer.js. Nothing here applies to those.

Three controllers were in exactly that state (Chapter, Member, Chapter Role), and
the mistake also existed in hooks/doc_events.py under the same name — see
tests/test_hooks_modules.py::TestDocEventNamesAreDispatched for the hook-side gate.

This module holds the behavioural tests for the work those methods were supposed
to do, plus a structural gate so the name cannot come back.
"""

import inspect
import unittest

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase

# Controller method names Frappe never dispatches. Kept deliberately small: these
# are the two that read as real lifecycle hooks but are not.
NEVER_DISPATCHED_METHOD_NAMES = ("after_save", "after_validate")


class TestChapterBoardProfileSyncRunsOnSave(VereningingenTestCase):
    """Adding a board member and saving must drain the deferred role-profile sync.

    board_manager.handle_board_member_additions() runs during validate, before the
    Chapter Board Member child rows exist in the database, so it defers the
    role-profile sync onto chapter._pending_board_profile_syncs and relies on the
    controller to drain it once the rows are committed. While that drain lived in
    `after_save` it never ran, so a newly seated board member never received their
    board role profile.

    The existing BoardManager suite misses this because it calls
    flush_pending_board_profile_syncs() directly rather than going through a save.
    """

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"LifecycleWiring {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    def _make_role(self):
        role_name = f"Role{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)
        return role_name

    def test_seating_a_board_member_applies_their_board_role_profile(self):
        """The observable outcome: the volunteer's User gains the board role profile.

        Asserting only that the deferred queue ends up empty would be a weak proxy —
        `getattr(chapter, "_pending_board_profile_syncs", [])` cannot tell "drained"
        from "never enqueued", and the sync short-circuits at `if not user: return`
        when the member has no linked User, so a queue-only assertion passes without
        the sync ever doing anything. This asserts the role profile itself, and
        separately pins that the queue really was non-empty before the save.
        """
        from verenigingen.services.member.account.user_role_profile_calculator import (
            get_user_role_profiles,
        )

        email = f"drain.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)

        member = self.create_test_member(
            first_name="Drain",
            last_name="OnSave",
            email=email,
            status="Active",
        )
        member.db_set("user", user.name, update_modified=False)
        member.reload()
        volunteer = self.create_test_volunteer(member=member.name)
        role_name = self._make_role()

        # Deliberately hold ONE document instance across the save: the pending list
        # lives on the in-memory doc, so reloading would hide the bug.
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "volunteer_name": volunteer.volunteer_name,
                "chapter_role": role_name,
                "from_date": today(),
                "is_active": 1,
                "email": member.email,
            },
        )

        # Capture the queue at the moment it is populated (during validate), so this
        # test cannot pass vacuously if handle_board_member_additions stops enqueueing.
        enqueued = []
        original_flush = type(chapter.board_manager).flush_pending_board_profile_syncs

        def spy(manager_self):
            enqueued.extend(getattr(manager_self.chapter_doc, "_pending_board_profile_syncs", []))
            return original_flush(manager_self)

        type(chapter.board_manager).flush_pending_board_profile_syncs = spy
        try:
            chapter.save()
        finally:
            type(chapter.board_manager).flush_pending_board_profile_syncs = original_flush

        self.assertIn(
            volunteer.name,
            enqueued,
            "Seating a board member did not enqueue a deferred role-profile sync, so "
            "this test would pass vacuously — the enqueue side has regressed.",
        )
        self.assertEqual(
            getattr(chapter, "_pending_board_profile_syncs", []),
            [],
            "Saving a Chapter left the deferred board role-profile sync undrained.",
        )
        self.assertIn(
            "Verenigingen Chapter Board Member",
            get_user_role_profiles(user.name),
            "The newly seated board member's User did not receive the board role "
            "profile, so the deferred sync drained without achieving anything.",
        )


class TestMemberDoesNotCreateUserAccountDirectly(VereningingenTestCase):
    """Saving a Member must NOT provision a User directly.

    Member had a dead `after_save()` calling create_user_account_if_needed(), which
    creates the User immediately. It was tempting to treat that as a gap and rewire it
    to on_update/after_insert — but account provisioning has since moved to the
    Account Creation Request queue, and rewiring it reintroduces exactly the
    immediate-creation path that queue replaced. Doing so makes
    test_account_creation_pipeline::test_volunteer_integration_security fail, because
    the member already holds a user by the time the volunteer would queue its request.

    This pins the security property so the dead method is not "helpfully" revived.
    """

    def test_saving_a_member_does_not_provision_a_user_directly(self):
        email = f"noautouser.{frappe.generate_hash(length=6)}@test.invalid"
        member = self.create_test_member(
            first_name="NoAutouser",
            last_name="Wiring",
            email=email,
            status="Active",
        )

        member.reload()
        self.assertFalse(
            member.user,
            "Saving a Member provisioned a User directly, bypassing the Account "
            "Creation Request queue that owns account provisioning.",
        )
        self.assertFalse(
            frappe.db.exists("User", email),
            "A User was created immediately for a Member; provisioning must go "
            "through the Account Creation Request queue.",
        )


class TestControllerLifecycleMethodNames(unittest.TestCase):
    """Structural gate: no controller may define a never-dispatched lifecycle method.

    Guards against reintroducing `after_save`/`after_validate` on a Document
    subclass, where it would read as wired and silently never run.
    """

    def _iter_controllers(self):
        """Yield (doctype, class) for every Document subclass this app defines."""
        from frappe.model.base_document import get_controller

        for module in frappe.get_all(
            "DocType",
            filters={"custom": 0},
            fields=["name", "module"],
        ):
            if frappe.db.get_value("Module Def", module.module, "app_name") != "verenigingen":
                continue
            try:
                yield module.name, get_controller(module.name)
            except Exception:
                # A DocType whose controller cannot be resolved is a different
                # problem, already covered by the hooks-resolution tests.
                continue

    def test_no_controller_defines_a_never_dispatched_method(self):
        offenders = []
        seen = set()
        for doctype, controller in self._iter_controllers():
            # Walk the MRO, not just __dict__: controllers here mix in behaviour
            # (e.g. Member(Document, PaymentMixin, ExpenseMixin, ...)), and a method
            # defined on a mixin is just as inert. Restrict to classes this app owns
            # so framework/ERPNext base classes are not reported.
            for klass in controller.__mro__:
                if not klass.__module__.startswith("verenigingen"):
                    continue
                for method_name in NEVER_DISPATCHED_METHOD_NAMES:
                    if method_name not in klass.__dict__:
                        continue
                    key = f"{klass.__module__}.{klass.__qualname__}.{method_name}"
                    if key in seen:
                        continue
                    seen.add(key)
                    offenders.append(f"{doctype} -> {key} ({inspect.getfile(klass)})")

        self.assertEqual(
            [],
            offenders,
            "These controller methods are never called by Frappe — run_method() is "
            "never invoked with those names. Move the body to on_update (existing "
            "docs) and/or after_insert (new docs):\n  " + "\n  ".join(offenders),
        )
