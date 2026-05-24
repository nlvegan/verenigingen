"""Regression tests for EnhancedTestCase._drain_tracked_documents.

The drain runs in tearDown after frappe.db.rollback() and deletes documents
the factory tracked, so that records committed during a test (or by production
code the test invoked) do not survive into the next run.

Pre-fix history: 3 PRs (#57, #60, plus an earlier) added test-specific
tearDown overrides to clean up leaked Customer/Member records. Those were
symptoms of this framework gap; see
docs/plans/2026-05-24-test-framework-tracked-doc-drain-design.md.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDrainTrackedDocuments(EnhancedTestCase):
    """Verify the drain deletes committed records and tracks the auto-Customer."""

    def test_factory_tracks_auto_created_customer(self):
        """A Member created with auto_create_customer should have its Customer tracked."""
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="AutoCustomer",
            email="draintest.autocustomer@test.invalid",
        )

        self.assertTrue(member.customer, "Expected auto-created Customer on member")

        tracked = [(d["doctype"], d["name"]) for d in self.factory.core.created_records]
        self.assertIn(
            ("Customer", member.customer),
            tracked,
            "Customer should be tracked by Core factory for tearDown drain",
        )

    def test_drain_deletes_committed_member_and_customer(self):
        """Drain removes committed Member + auto-Customer that rollback couldn't undo."""
        member = self.create_test_member(
            first_name="DrainTest",
            last_name="Committed",
            email="draintest.committed@test.invalid",
        )
        member_name = member.name
        customer_name = member.customer

        frappe.db.commit()

        self.assertTrue(frappe.db.exists("Member", member_name))
        self.assertTrue(frappe.db.exists("Customer", customer_name))

        self._drain_tracked_documents()

        self.assertFalse(
            frappe.db.exists("Member", member_name),
            f"Member {member_name} should be deleted by drain",
        )
        self.assertFalse(
            frappe.db.exists("Customer", customer_name),
            f"Customer {customer_name} should be deleted by drain",
        )

    def test_drain_is_idempotent(self):
        """Calling drain twice should not raise; second call is a no-op."""
        self.create_test_member(
            first_name="DrainTest",
            last_name="Idempotent",
            email="draintest.idempotent@test.invalid",
        )
        frappe.db.commit()

        self._drain_tracked_documents()
        self._drain_tracked_documents()

        self.assertEqual(self.factory.created_documents, [])
        self.assertEqual(self.factory.core.created_records, [])
