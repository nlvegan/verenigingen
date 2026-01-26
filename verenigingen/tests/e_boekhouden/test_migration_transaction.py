"""
Tests for migration_transaction context manager in security_helper.py

Tests the transaction management features:
- Time-based auto-commit (auto_commit_interval parameter)
- Batch-size auto-commit (batch_size parameter)
- last_commit_time tracking across commits
- State management (operations_count, pending_operations, etc.)
- Savepoint handling for rollback capability

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_transaction
"""

import unittest
from unittest.mock import patch


class TestMigrationTransactionAutoCommit(unittest.TestCase):
    """Tests for auto-commit behavior in migration_transaction"""

    def setUp(self):
        """Set up test mocks - permission bypass allowed in setUp per testing standards"""
        self.frappe_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.frappe")
        self.time_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.time")
        self.perm_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.has_migration_permission")

        self.mock_frappe = self.frappe_patcher.start()
        self.mock_time = self.time_patcher.start()
        self.mock_has_perm = self.perm_patcher.start()

        # Default configuration - permission bypass in setUp is allowed
        self.mock_frappe.session.user = "Administrator"
        self.mock_has_perm.return_value = True
        self.mock_time.time.return_value = 1000.0

    def tearDown(self):
        """Clean up patches"""
        self.perm_patcher.stop()
        self.time_patcher.stop()
        self.frappe_patcher.stop()

    def test_batch_size_triggers_commit(self):
        """Test that reaching batch_size triggers auto-commit"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with migration_transaction(
            operation_type="account_creation", batch_size=3, auto_commit_interval=9999
        ) as tx:
            tx.track_operation("test", "doc1")
            tx.track_operation("test", "doc2")
            tx.track_operation("test", "doc3")

            self.assertEqual(tx.state["operations_count"], 3)
            self.assertEqual(tx.state["last_commit_count"], 3)
            self.mock_frappe.db.commit.assert_called()

    def test_time_interval_triggers_commit(self):
        """Test that exceeding auto_commit_interval triggers auto-commit"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        # Time progression for time-based commit test
        time_values = [
            1000.0, 1000.0, 1000.0,  # start + op1
            1000.0, 1060.0,  # op2 - 60s later triggers commit
            1060.0, 1060.0, 1060.0,  # commit + cleanup
        ]
        self.mock_time.time.side_effect = time_values

        with migration_transaction(
            operation_type="account_creation", batch_size=9999, auto_commit_interval=50
        ) as tx:
            tx.track_operation("test", "doc1")
            self.assertEqual(tx.state["last_commit_count"], 0)

            tx.track_operation("test", "doc2")
            self.assertEqual(tx.state["last_commit_count"], 2)
            self.mock_frappe.db.commit.assert_called()

    def test_last_commit_time_updated_after_commit(self):
        """Test that last_commit_time is updated in state after each commit"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        call_count = [0]
        time_mapping = {
            0: 1000.0,  # start_time
            1: 1001.0, 2: 1001.0,  # op1
            3: 1002.0, 4: 1002.0,  # op2
            5: 1003.0, 6: 1003.0,  # op3 (commit)
            7: 1003.5,  # commit time
            8: 1004.0, 9: 1004.0,  # op4
            10: 1005.0, 11: 1005.0,  # op5
            12: 1006.0, 13: 1006.0,  # op6 (commit)
            14: 1006.5, 15: 1007.0,  # commit + stats
        }

        def get_time():
            idx = call_count[0]
            call_count[0] += 1
            return time_mapping.get(idx, 1010.0)

        self.mock_time.time.side_effect = get_time

        with migration_transaction(
            operation_type="account_creation", batch_size=3, auto_commit_interval=9999
        ) as tx:
            self.assertEqual(tx.state["last_commit_time"], 1000.0)

            tx.track_operation("test", "doc1")
            tx.track_operation("test", "doc2")
            tx.track_operation("test", "doc3")

            self.assertEqual(tx.state["last_commit_time"], 1003.5)
            self.assertEqual(tx.state["last_commit_count"], 3)

            tx.track_operation("test", "doc4")
            tx.track_operation("test", "doc5")
            tx.track_operation("test", "doc6")

            self.assertEqual(tx.state["last_commit_time"], 1006.5)
            self.assertEqual(tx.state["last_commit_count"], 6)

    def test_pending_operations_moved_to_committed_on_commit(self):
        """Test that pending operations are moved to committed list after commit"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with migration_transaction(
            operation_type="account_creation", batch_size=2, auto_commit_interval=9999
        ) as tx:
            tx.track_operation("create", "doc1", {"key": "value1"})
            self.assertEqual(len(tx.state["pending_operations"]), 1)
            self.assertEqual(len(tx.state["committed_operations"]), 0)

            tx.track_operation("create", "doc2", {"key": "value2"})

            self.assertEqual(len(tx.state["pending_operations"]), 0)
            self.assertEqual(len(tx.state["committed_operations"]), 2)
            self.assertEqual(tx.state["committed_operations"][0]["doc_name"], "doc1")
            self.assertEqual(tx.state["committed_operations"][1]["doc_name"], "doc2")

    def test_get_stats_returns_correct_values(self):
        """Test that get_stats() returns accurate transaction statistics"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with migration_transaction(
            operation_type="account_creation", batch_size=2, auto_commit_interval=9999
        ) as tx:
            tx.track_operation("create", "doc1")
            tx.track_operation("create", "doc2")

            stats = tx.get_stats()

            self.assertEqual(stats["total_operations"], 2)
            self.assertEqual(stats["committed_operations"], 2)
            self.assertEqual(stats["pending_operations"], 0)
            self.assertEqual(stats["errors"], 0)
            self.assertGreaterEqual(stats["duration"], 0)


class TestMigrationTransactionStateManagement(unittest.TestCase):
    """Tests for state management in migration_transaction"""

    def setUp(self):
        """Set up test mocks - permission bypass allowed in setUp per testing standards"""
        self.frappe_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.frappe")
        self.time_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.time")
        self.perm_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.has_migration_permission")

        self.mock_frappe = self.frappe_patcher.start()
        self.mock_time = self.time_patcher.start()
        self.mock_has_perm = self.perm_patcher.start()

        # Default configuration - permission bypass in setUp is allowed
        self.mock_frappe.session.user = "Administrator"
        self.mock_has_perm.return_value = True
        self.mock_time.time.return_value = 1000.0

    def tearDown(self):
        """Clean up patches"""
        self.perm_patcher.stop()
        self.time_patcher.stop()
        self.frappe_patcher.stop()

    def test_initial_state_contains_last_commit_time(self):
        """Test that initial state includes last_commit_time set to start_time"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        self.mock_time.time.return_value = 1234.5

        with migration_transaction(operation_type="account_creation") as tx:
            self.assertIn("last_commit_time", tx.state)
            self.assertEqual(tx.state["last_commit_time"], 1234.5)
            self.assertEqual(tx.state["operations_count"], 0)
            self.assertEqual(tx.state["last_commit_count"], 0)
            self.assertEqual(tx.state["pending_operations"], [])
            self.assertEqual(tx.state["committed_operations"], [])
            self.assertEqual(tx.state["errors"], [])

    def test_operations_count_increments_correctly(self):
        """Test that operations_count increments with each tracked operation"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with migration_transaction(
            operation_type="account_creation", batch_size=9999, auto_commit_interval=9999
        ) as tx:
            self.assertEqual(tx.state["operations_count"], 0)

            tx.track_operation("create", "doc1")
            self.assertEqual(tx.state["operations_count"], 1)

            tx.track_operation("update", "doc2")
            self.assertEqual(tx.state["operations_count"], 2)

            tx.track_operation("delete", "doc3")
            self.assertEqual(tx.state["operations_count"], 3)

    def test_track_operation_stores_timestamp(self):
        """Test that tracked operations include timestamp"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        self.mock_time.time.side_effect = [1000.0, 1001.5, 1001.5, 1002.0, 1002.0, 1002.0]

        with migration_transaction(
            operation_type="account_creation", batch_size=9999, auto_commit_interval=9999
        ) as tx:
            tx.track_operation("create", "doc1")

            self.assertEqual(len(tx.state["pending_operations"]), 1)
            op = tx.state["pending_operations"][0]
            self.assertEqual(op["type"], "create")
            self.assertEqual(op["doc_name"], "doc1")
            self.assertEqual(op["timestamp"], 1001.5)


class TestMigrationTransactionSavepoints(unittest.TestCase):
    """Tests for savepoint handling in migration_transaction"""

    def setUp(self):
        """Set up test mocks - permission bypass allowed in setUp per testing standards"""
        self.frappe_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.frappe")
        self.time_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.time")
        self.perm_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.has_migration_permission")

        self.mock_frappe = self.frappe_patcher.start()
        self.mock_time = self.time_patcher.start()
        self.mock_has_perm = self.perm_patcher.start()

        # Default configuration - permission bypass in setUp is allowed
        self.mock_frappe.session.user = "Administrator"
        self.mock_has_perm.return_value = True
        self.mock_time.time.return_value = 1000.0

    def tearDown(self):
        """Clean up patches"""
        self.perm_patcher.stop()
        self.time_patcher.stop()
        self.frappe_patcher.stop()

    def test_savepoint_created_on_entry(self):
        """Test that a savepoint is created when entering the context"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with migration_transaction(operation_type="account_creation") as tx:
            self.mock_frappe.db.sql.assert_any_call("SAVEPOINT migration_start")
            self.assertEqual(tx.state["rollback_savepoint"], "migration_start")

    def test_savepoint_refreshed_after_commit(self):
        """Test that savepoint is released and recreated after commit"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with migration_transaction(
            operation_type="account_creation", batch_size=1, auto_commit_interval=9999
        ) as tx:
            tx.track_operation("create", "doc1")

            calls = self.mock_frappe.db.sql.call_args_list
            self.assertTrue(
                any("RELEASE SAVEPOINT migration_start" in str(c) for c in calls),
                f"Expected RELEASE SAVEPOINT call, got: {[str(c) for c in calls]}",
            )

    def test_savepoint_released_on_normal_exit(self):
        """Test that savepoint is released when context exits normally"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with migration_transaction(operation_type="account_creation"):
            pass

        calls = self.mock_frappe.db.sql.call_args_list
        self.assertTrue(
            any("RELEASE SAVEPOINT migration_start" in str(c) for c in calls),
            "Expected final RELEASE SAVEPOINT call",
        )


class TestMigrationTransactionRollback(unittest.TestCase):
    """Tests for rollback behavior in migration_transaction"""

    def setUp(self):
        """Set up test mocks - permission bypass allowed in setUp per testing standards"""
        self.frappe_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.frappe")
        self.time_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.time")
        self.perm_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.has_migration_permission")

        self.mock_frappe = self.frappe_patcher.start()
        self.mock_time = self.time_patcher.start()
        self.mock_has_perm = self.perm_patcher.start()

        # Default configuration - permission bypass in setUp is allowed
        self.mock_frappe.session.user = "Administrator"
        self.mock_has_perm.return_value = True
        self.mock_time.time.return_value = 1000.0

    def tearDown(self):
        """Clean up patches"""
        self.perm_patcher.stop()
        self.time_patcher.stop()
        self.frappe_patcher.stop()

    def test_rollback_on_exception(self):
        """Test that rollback is triggered when an exception occurs"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        with self.assertRaises(ValueError):
            with migration_transaction(operation_type="account_creation") as tx:
                tx.track_operation("create", "doc1")
                raise ValueError("Test error")

        calls = self.mock_frappe.db.sql.call_args_list
        self.assertTrue(
            any("ROLLBACK TO SAVEPOINT migration_start" in str(c) for c in calls),
            "Expected ROLLBACK TO SAVEPOINT call",
        )

    def test_user_restored_after_exception(self):
        """Test that original user is restored even after exception"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        # Use non-admin user for this test - still configured in setUp context
        self.mock_frappe.session.user = "test@example.com"

        try:
            with migration_transaction(operation_type="account_creation"):
                raise ValueError("Test error")
        except ValueError:
            pass

        self.mock_frappe.set_user.assert_called_with("test@example.com")


class TestMigrationTransactionPermissions(unittest.TestCase):
    """Tests for permission checking in migration_transaction"""

    def setUp(self):
        """Set up test mocks - permission bypass allowed in setUp per testing standards"""
        self.frappe_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.frappe")
        self.time_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.time")
        self.perm_patcher = patch("verenigingen.e_boekhouden.utils.security_helper.has_migration_permission")

        self.mock_frappe = self.frappe_patcher.start()
        self.mock_time = self.time_patcher.start()
        self.mock_has_perm = self.perm_patcher.start()

        # Default configuration
        self.mock_frappe.session.user = "limited@example.com"
        self.mock_time.time.return_value = 1000.0

    def tearDown(self):
        """Clean up patches"""
        self.perm_patcher.stop()
        self.time_patcher.stop()
        self.frappe_patcher.stop()

    def test_permission_denied_throws_error(self):
        """Test that permission denial raises an error"""
        from verenigingen.e_boekhouden.utils.security_helper import migration_transaction

        self.mock_has_perm.return_value = False
        self.mock_frappe.throw.side_effect = Exception("Permission denied")

        with self.assertRaises(Exception):
            with migration_transaction(operation_type="account_creation"):
                pass

        self.mock_frappe.throw.assert_called()
        call_args = str(self.mock_frappe.throw.call_args)
        self.assertIn("permission", call_args.lower())


if __name__ == "__main__":
    unittest.main()
