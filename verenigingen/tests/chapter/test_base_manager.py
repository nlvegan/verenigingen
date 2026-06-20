"""
Real-DB tests for the chapter ``BaseManager``
(``verenigingen/verenigingen/doctype/chapter/managers/base_manager.py``).

BaseManager is abstract, so its inherited behaviour is exercised through the real
concrete subclass ``VolunteerIntegrationManager`` (reached via
``chapter.volunteer_integration_manager``). Covered: the per-instance cache,
settings lookup, retry helper, permission resolution (admin short-circuit + board
member role mapping), comment creation, the template-missing notification branch,
and cleanup. No business logic is mocked; a throw-counter callable drives the retry
helper and a real Chapter Role drives the board-member permission mapping.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestBaseManager(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"BaseMgr Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )

    @property
    def manager(self):
        return self.chapter.volunteer_integration_manager

    # ------------------------------------------------------------------- cache

    def test_cache_set_get_clear(self):
        mgr = self.manager
        self.assertEqual(mgr.get_cached("missing", "default"), "default")
        mgr.set_cached("k", 42)
        self.assertEqual(mgr.get_cached("k"), 42)
        mgr.clear_cache("k")
        self.assertIsNone(mgr.get_cached("k"))

    def test_clear_cache_all(self):
        mgr = self.manager
        mgr.set_cached("a", 1)
        mgr.set_cached("b", 2)
        mgr.clear_cache()
        self.assertIsNone(mgr.get_cached("a"))
        self.assertIsNone(mgr.get_cached("b"))

    def test_chapter_name_property(self):
        self.assertEqual(self.manager.chapter_name, self.chapter.name)

    # ---------------------------------------------------------------- settings

    def test_settings_value_default_for_unknown(self):
        # A field that does not exist on Verenigingen Settings -> default returned
        self.assertEqual(
            self.manager.get_settings_value("definitely_not_a_real_setting_xyz", "fallback"),
            "fallback",
        )

    # ----------------------------------------------------------------- retry

    def test_retry_succeeds_first_try(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            return "ok"

        self.assertEqual(self.manager.execute_with_retry(fn, max_retries=2, delay=0), "ok")
        self.assertEqual(calls["n"], 1)

    def test_retry_recovers_after_failures(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("transient")
            return "recovered"

        result = self.manager.execute_with_retry(fn, max_retries=3, delay=0)
        self.assertEqual(result, "recovered")
        self.assertEqual(calls["n"], 3)

    def test_retry_reraises_after_exhausting(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise RuntimeError("always fails")

        with self.assertRaises(RuntimeError):
            self.manager.execute_with_retry(fn, max_retries=2, delay=0)
        # initial try + 2 retries
        self.assertEqual(calls["n"], 3)

    # -------------------------------------------------------------- permissions

    def test_admin_has_permission(self):
        # Test suite runs as Administrator -> System Manager short-circuit
        self.assertTrue(self.manager.validate_permissions("bulk_operations"))

    def test_non_member_user_denied(self):
        # A fresh user with no member/volunteer/board link -> denied
        user = self.create_test_user(
            f"basemgr.nonmember.{frappe.generate_hash(length=6)}@test.invalid", roles=[]
        )
        with self.set_user(user.name):
            self.assertFalse(self.manager.validate_permissions("manage_members"))

    def test_check_board_member_permissions_admin_role(self):
        role_name = f"BMPRole{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Admin",
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)

        # Admin level grants every mapped action
        self.assertTrue(self.manager._check_board_member_permissions({"role": role_name}, "remove_board_member"))
        self.assertTrue(self.manager._check_board_member_permissions({"role": role_name}, "bulk_operations"))

    def test_check_board_member_permissions_basic_role_denied_for_admin_action(self):
        role_name = f"BMPBasic{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": role_name,
                "permissions_level": "Basic",
                "is_active": 1,
            }
        ).insert()
        self.track_doc("Chapter Role", role_name)

        # Basic level may manage members but NOT remove board members
        self.assertTrue(self.manager._check_board_member_permissions({"role": role_name}, "manage_members"))
        self.assertFalse(
            self.manager._check_board_member_permissions({"role": role_name}, "remove_board_member")
        )

    def test_check_board_member_permissions_no_role_denied(self):
        self.assertFalse(self.manager._check_board_member_permissions({"role": None}, "manage_members"))

    def test_check_board_member_permissions_unknown_role_denied(self):
        self.assertFalse(
            self.manager._check_board_member_permissions({"role": "NO-SUCH-ROLE"}, "manage_members")
        )

    # ------------------------------------------------------------------ comment

    def test_create_comment_persists(self):
        before = frappe.db.count(
            "Comment", {"reference_doctype": "Chapter", "reference_name": self.chapter.name}
        )
        with self.assertNoErrorLog():
            self.manager.create_comment("Info", "BaseManager test comment")
        after = frappe.db.count(
            "Comment", {"reference_doctype": "Chapter", "reference_name": self.chapter.name}
        )
        self.assertEqual(after, before + 1)

    # ------------------------------------------------------------ notification

    def test_notification_no_recipients_is_noop(self):
        # No recipients -> returns immediately without error
        with self.assertNoErrorLog():
            self.manager.send_notification("Some Template", [], {})

    def test_notification_missing_template_logs_warning_not_error(self):
        # Missing Email Template -> warning branch, returns without raising.
        # log_action warning goes through frappe.logger(), not Error Log.
        with self.assertNoErrorLog():
            self.manager.send_notification(
                f"NoSuchTemplate{frappe.generate_hash(length=6)}",
                ["someone@test.invalid"],
                {},
            )

    # ------------------------------------------------------------------- cleanup

    def test_cleanup_clears_cache_and_context(self):
        mgr = self.manager
        mgr.set_cached("k", 1)
        mgr.context["x"] = 1
        mgr.cleanup()
        self.assertIsNone(mgr.get_cached("k"))
        self.assertEqual(mgr.context, {})

    def test_validate_chapter_doc_ok(self):
        # chapter present -> does not raise
        self.manager.validate_chapter_doc()


if __name__ == "__main__":
    import unittest

    unittest.main()
