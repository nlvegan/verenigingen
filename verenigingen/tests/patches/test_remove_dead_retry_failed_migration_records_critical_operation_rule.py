"""#660: the patch must delete the Critical Operation Rule left behind on sites
that imported it before `retry_failed_migration_records` was deleted. COR is
excluded from the `fixtures` hook, so nothing else prunes the imported row.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import frappe
from frappe.modules import patch_handler
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_retry_failed_migration_records_critical_operation_rule import (
    DEAD_RULES,
    execute,
)
from verenigingen.setup import patch_fragments
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

PATCH_LINE = "verenigingen.patches.v2_2.remove_dead_retry_failed_migration_records_critical_operation_rule"
# An unrelated rule the patch must not touch.
CONTROL = "get_suspension_status_safe"


class TestRemoveDeadRetryFailedMigrationRecordsRule(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rule_name_is_the_deleted_function(self):
        self.assertEqual(DEAD_RULES, ["retry_failed_migration_records"])

    def test_execute_deletes_the_dead_rule_and_keeps_the_control(self):
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "retry_failed_migration_records"))

        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "retry_failed_migration_records"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        execute()
        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "retry_failed_migration_records"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_the_patch_is_registered_through_a_fragment(self):
        patch_fragments.install()
        self.assertIn(PATCH_LINE, patch_handler.get_patches_from_app("verenigingen"))
