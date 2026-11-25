"""#1169: scripts/ entry points must not open their own transaction with frappe.db.begin().

START TRANSACTION is refused (ImplicitCommitError) once the request has written anything,
and `@critical_api` writes an API Audit Log row before every admin entry point's body runs.
Each test dirties the transaction first (the decorator's audit write, stood in for by a
`frappe.db.set_value`: a probe shortcut, stated here rather than hidden) and then drives the
real function.

The nuclear TRUNCATE and the orphan schedule/invoice sweeps are not driven live (they destroy
data); the whole-tree validator test in scripts/validation/tests covers them.
"""

from unittest.mock import patch

import frappe

from scripts.cleanup import cleanup_invalid_member_schedules as schedules_module
from scripts.migration import member_import_cleanup as cleanup
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestScriptsDoNotBeginTransactions(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.db.rollback()
        self.addCleanup(frappe.db.rollback)

    def _dirty_the_transaction(self):
        member = self.create_test_member(
            first_name="Txn1169", last_name="Pending", email="txn1169.pending@test.invalid"
        )
        frappe.db.set_value("Member", member.name, "notes", "pending write", update_modified=False)
        self.assertGreater(frappe.db.transaction_writes, 0, "precondition: dirty transaction")

    def test_cleanup_invalid_schedules_live_run_reaches_the_schedule_with_pending_writes(self):
        self._dirty_the_transaction()
        fake = {"details": [{"name": "NO-SUCH-SCHEDULE-1169", "member": "NO-SUCH-MEMBER-1169"}]}
        with patch.object(schedules_module, "identify_invalid_schedules", return_value=fake):
            result = schedules_module.cleanup_invalid_schedules(dry_run=False)

        self.assertFalse(result["success"], result)  # the schedule really does not exist
        self.assertNotIn("implicit commit", result["message"].lower(), result)
        self.assertIn("NO-SUCH-SCHEDULE-1169", result["message"], result)

    def test_orphaned_contact_cleanup_live_run_deletes_with_pending_writes(self):
        ghost = "Assoc-Member-GONE-1169"
        self.assertFalse(frappe.db.exists("Member", ghost))
        anchor = self.create_test_member(
            first_name="Anchor1169", last_name="Orphan", email="anchor1169.orphan@test.invalid"
        )
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Orphan1169",
                "links": [{"link_doctype": "Member", "link_name": anchor.name}],
            }
        ).insert(ignore_permissions=True)
        # Dangle the link (probe shortcut: Contact validation refuses a link to a missing Member).
        frappe.db.sql(
            "UPDATE `tabDynamic Link` SET link_name = %s WHERE parent = %s AND link_doctype = 'Member'",
            (ghost, contact.name),
        )
        self._dirty_the_transaction()

        results = cleanup.cleanup_orphaned_addresses_and_contacts(dry_run=False)

        self.assertNotIn("implicit commit", results["summary"].lower(), results)
        self.assertGreaterEqual(results["contacts"]["deleted"], 1, results)
        self.assertFalse(frappe.db.exists("Contact", contact.name))
