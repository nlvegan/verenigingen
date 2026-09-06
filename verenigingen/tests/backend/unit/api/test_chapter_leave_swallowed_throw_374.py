"""
Regression test for #374: chapter.leave()'s outer `except Exception` swallows
its own deliberate `frappe.throw(_("Chapter and Member ID are required"))` and
replaces it with the generic `"An error occurred while leaving the chapter"`
message, which tells the caller nothing about what to fix.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import leave


class TestChapterLeaveSwallowedThrow374(EnhancedTestCase):
    def test_missing_member_id_message_is_not_genericized(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            leave(title="Some Chapter", member_id="", leave_reason="Moving away")

        # The endpoint's own validation message must reach the caller -- not
        # the generic "An error occurred while leaving the chapter" message
        # the surrounding `except Exception` currently substitutes.
        self.assertIn("Chapter and Member ID are required", str(ctx.exception))
