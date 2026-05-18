"""Unit tests for the migration phase-failure helpers (audit T2.2).

The e-Boekhouden migration phase methods catch their own exceptions and
return a structured ``{"success": bool, "message": str}`` result instead of
raising. start_migration must detect a failed phase from that result and
reflect it in migration_status, otherwise a failed phase is still recorded
as a "Completed" migration.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_phase_failure
"""

import unittest

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    _migration_phase_failed,
    _resolve_migration_status,
)


class TestMigrationPhaseFailed(unittest.TestCase):
    """Detect a failed migration phase from its structured result."""

    def test_success_result_is_not_failure(self):
        """A phase result with success=True is not a failure."""
        self.assertFalse(_migration_phase_failed({"success": True, "message": "Imported 5"}))

    def test_failure_result_is_failure(self):
        """A phase result with success=False is a failure."""
        self.assertTrue(
            _migration_phase_failed({"success": False, "message": "Error migrating Transactions"})
        )

    def test_missing_success_key_is_failure(self):
        """A dict without an explicit success=True is treated as a failure."""
        self.assertTrue(_migration_phase_failed({"message": "something"}))
        self.assertTrue(_migration_phase_failed({}))

    def test_non_true_success_value_is_failure(self):
        """Only a literal True counts as success — a truthy string does not."""
        self.assertTrue(_migration_phase_failed({"success": "yes"}))
        self.assertTrue(_migration_phase_failed({"success": 1}))

    def test_non_dict_result_is_failure(self):
        """A malformed (non-dict) result is treated as a failure — fail loud,
        never silently record a broken phase as Completed."""
        self.assertTrue(_migration_phase_failed(None))
        self.assertTrue(_migration_phase_failed(""))
        self.assertTrue(_migration_phase_failed("Error migrating Transactions"))


class TestResolveMigrationStatus(unittest.TestCase):
    """start_migration's final status reflects whether any phase failed."""

    def test_no_failed_phases_is_completed(self):
        """An empty failed-phases list resolves to Completed."""
        status, operation = _resolve_migration_status([])
        self.assertEqual(status, "Completed")
        self.assertEqual(operation, "Migration completed successfully")

    def test_one_failed_phase_is_failed(self):
        """A single failed phase resolves to Failed and names the phase."""
        status, operation = _resolve_migration_status(["Transactions"])
        self.assertEqual(status, "Failed")
        self.assertIn("Transactions", operation)

    def test_multiple_failed_phases_named(self):
        """All failed phases are named in the operation message."""
        status, operation = _resolve_migration_status(["Transactions", "Cost Centers"])
        self.assertEqual(status, "Failed")
        self.assertIn("Transactions", operation)
        self.assertIn("Cost Centers", operation)


if __name__ == "__main__":
    unittest.main()
