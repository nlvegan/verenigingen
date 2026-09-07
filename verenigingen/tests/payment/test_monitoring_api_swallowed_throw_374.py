"""
Regression test for #374: process_recovery_queues()'s outer `except Exception`
swallows its own deliberate `frappe.throw(_(f"Recovery queue '{queue_name}'
not found"))` and replaces it with the generic `"Failed to process recovery
queues"` message, which does not tell the administrator whether they typo'd
the queue name or whether the system actually failed.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import monitoring_api


class TestProcessRecoveryQueuesSwallowedThrow374(EnhancedTestCase):
    def test_unknown_queue_name_message_is_not_genericized(self):
        with self.set_user("Administrator"):
            frappe.local.form_dict = frappe._dict(queue_name="definitely-not-a-real-queue-374")
            with self.assertRaises(frappe.ValidationError) as ctx:
                monitoring_api.process_recovery_queues()

        # The endpoint's own "queue not found" message must reach the caller
        # -- not the generic "Failed to process recovery queues" message the
        # surrounding `except Exception` currently substitutes.
        self.assertIn("definitely-not-a-real-queue-374", str(ctx.exception))
        self.assertIn("not found", str(ctx.exception))
