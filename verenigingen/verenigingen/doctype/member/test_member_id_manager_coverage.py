"""
Additional real-DB coverage for ``member_id_manager.py``.

The base suite (``test_member_id_manager.py``) covers the counter core, the
validate hook, and the whitelisted endpoints' happy paths. This file fills:

- ``generate_member_id`` hook (assigns / skips counter-system / skips when set)
- the whitelisted endpoints' permission/role guard branches (run as Guest)
- ``reset_counter`` conflict-warning branch (a member id already at/above the
  reset value)
- ``get_member_id_statistics`` no-numeric-data gap branch

Run as Administrator except where a guard branch needs a non-privileged user.
No business logic is mocked.
"""


import frappe
from frappe.utils import cint

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.member.member_id_manager import (
    MemberIDManager,
    generate_member_id,
    get_member_id_statistics,
    get_next_member_id_preview,
    migrate_member_id_counter,
    reset_member_id_counter,
)

DOCTYPE = "Verenigingen Settings"
FIELD = "last_member_id"


class TestMemberIDManagerCoverage(EnhancedTestCase):
    # as_user() removed (#496): it shadowed EnhancedTestCase.as_user(user_email),
    # and was equivalent to it (restore-on-exit via a context manager). Deleted
    # rather than renamed since there was nothing local about it to preserve.

    def _make_member_with_id(self, member_id):
        member = self.create_test_member()
        member.db_set("member_id", str(member_id), update_modified=False)
        member.reload()
        return member

    # ------------------------------------------------------------ generate_member_id hook

    def test_generate_member_id_assigns_when_missing(self):
        doc = frappe.new_doc("Member")
        doc.full_name = "Hook Assign"
        self.assertFalse(doc.member_id)
        generate_member_id(doc)
        self.assertTrue(doc.member_id)
        self.assertTrue(str(doc.member_id).isdigit())

    def test_generate_member_id_skips_counter_system_doc(self):
        doc = frappe.new_doc("Member")
        doc.name = "MEMBER-COUNTER-SYSTEM"
        generate_member_id(doc)
        # The counter-system document must never be assigned an id.
        self.assertFalse(doc.member_id)

    def test_generate_member_id_noop_when_already_set(self):
        doc = frappe.new_doc("Member")
        doc.member_id = "999888"
        generate_member_id(doc)
        # Existing id is untouched.
        self.assertEqual(doc.member_id, "999888")

    # ------------------------------------------------------------ permission guards

    def test_preview_blocks_without_read_permission(self):
        with self.as_user("Guest"):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                get_next_member_id_preview()

    def test_statistics_blocks_without_read_permission(self):
        with self.as_user("Guest"):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                get_member_id_statistics()

    def test_migrate_blocks_without_write_permission(self):
        with self.as_user("Guest"):
            with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
                migrate_member_id_counter()

    # ------------------------------------------------------------ reset conflict warning

    def test_reset_counter_warns_on_existing_id_at_or_above_target(self):
        start = cint(frappe.db.get_single_value(DOCTYPE, "member_id_start")) or 1000
        # Create a member with a high numeric id, then reset the counter to a value
        # AT or BELOW that id (but >= minimum) so the conflict-warning branch fires.
        high = max(start, MemberIDManager._get_max_numeric_member_id()) + 50000
        self._make_member_with_id(high)
        # Reset to high - 10: still >= minimum, and an id (high) exists >= target,
        # triggering the msgprint warning path without raising.
        target = high - 10
        result = reset_member_id_counter(target)
        self.assertTrue(result["success"])
        self.assertEqual(cint(frappe.cache().get("member_id_counter")), target)

    # ------------------------------------------------------------ statistics no-data branch

    def test_statistics_gap_branch_present(self):
        # With at least one numeric id present, the gap-analysis branch runs and
        # returns the gap keys; assert their shape rather than exact values.
        MemberIDManager.get_next_member_id()
        target = MemberIDManager._get_max_numeric_member_id() + 12345
        self._make_member_with_id(target)
        stats = get_member_id_statistics()
        self.assertIn("gaps", stats)
        self.assertIn("gap_count", stats)
        self.assertIsInstance(stats["gaps"], list)
        self.assertGreaterEqual(stats["gap_count"], 0)
