"""
BaseHistoryManager Unit Tests
=============================

Tests for the _with_doc() callback protocol, return types, and error handling.
BaseHistoryManager is shared infrastructure used by AssignmentHistoryManager,
ChapterMembershipHistoryManager, and DonationHistoryManager.

The callback protocol is:
    None  → save via safe_child_table_update, return its HistoryOperationResult
    True  → skip save, return HistoryOperationResult(success=True)
    False → skip save, return HistoryOperationResult(success=False)
"""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from verenigingen.utils.base_history_manager import BaseHistoryManager
from verenigingen.utils.history_manager_utils import HistoryOperationResult

# All patches target base_history_manager's namespace (where the imports live)
_BHM = "verenigingen.utils.base_history_manager"


class ConcreteHistoryManager(BaseHistoryManager):
    """Minimal concrete subclass for testing."""

    PARENT_DOCTYPE = "Donor"
    CHILD_TABLE = "donor_history"
    PERMISSION = "Donor:write"
    RECURSION_FLAG = "_test_recursion_flag"


@contextmanager
def _standard_mocks(exists=True, should_proceed=True):
    """Set up the standard mock chain for _with_doc: exists → get_doc → recursion_guard."""
    with (
        patch(f"{_BHM}.ensure_doc_exists", return_value=exists) as mock_exists,
        patch(f"{_BHM}.frappe") as mock_frappe,
    ):
        mock_doc = MagicMock(doctype="Donor")
        mock_frappe.get_doc.return_value = mock_doc

        # recursion_guard is the real context manager from history_manager_utils.
        # It checks getattr(doc, flag, False). MagicMock auto-creates attributes
        # as truthy MagicMock objects, so we MUST explicitly set the flag value.
        setattr(mock_doc, ConcreteHistoryManager.RECURSION_FLAG, not should_proceed)

        yield {
            "exists": mock_exists,
            "frappe": mock_frappe,
            "doc": mock_doc,
        }


class TestCallbackProtocolNone(unittest.TestCase):
    """Callback returns None → save via safe_child_table_update."""

    def test_triggers_save_and_returns_save_result(self):
        expected = HistoryOperationResult(success=True, message="saved")
        with _standard_mocks():
            with patch(f"{_BHM}.safe_child_table_update", return_value=expected) as mock_save:
                result = ConcreteHistoryManager._with_doc("DN-001", "test op", lambda doc: None)

        self.assertIsInstance(result, HistoryOperationResult)
        self.assertIs(result, expected)
        mock_save.assert_called_once()

    def test_passes_class_constants_to_save(self):
        with _standard_mocks() as mocks:
            with patch(
                f"{_BHM}.safe_child_table_update",
                return_value=HistoryOperationResult(success=True),
            ) as mock_save:
                ConcreteHistoryManager._with_doc("DN-001", "test op", lambda doc: None)

        kwargs = mock_save.call_args[1]
        self.assertIs(kwargs["doc"], mocks["doc"])
        self.assertEqual(kwargs["child_table_name"], "donor_history")
        self.assertEqual(kwargs["doctype_permission"], "Donor:write")
        self.assertTrue(kwargs["auto_cleanup"])


class TestCallbackProtocolTrue(unittest.TestCase):
    """Callback returns True → skip save, return success."""

    def test_skips_save_returns_success(self):
        with _standard_mocks():
            with patch(f"{_BHM}.safe_child_table_update") as mock_save:
                result = ConcreteHistoryManager._with_doc("DN-001", "test op", lambda doc: True)

        self.assertIsInstance(result, HistoryOperationResult)
        self.assertTrue(result.success)
        self.assertIn("skipped", result.message)
        mock_save.assert_not_called()


class TestCallbackProtocolFalse(unittest.TestCase):
    """Callback returns False → skip save, return failure."""

    def test_skips_save_returns_failure(self):
        with _standard_mocks():
            with patch(f"{_BHM}.safe_child_table_update") as mock_save:
                result = ConcreteHistoryManager._with_doc("DN-001", "test op", lambda doc: False)

        self.assertIsInstance(result, HistoryOperationResult)
        self.assertFalse(result.success)
        self.assertTrue(len(result.errors) > 0)
        mock_save.assert_not_called()


class TestExistenceCheck(unittest.TestCase):
    """_with_doc must check document existence before loading."""

    def test_nonexistent_doc_returns_failure(self):
        with _standard_mocks(exists=False) as mocks:
            result = ConcreteHistoryManager._with_doc("MISSING", "test op", lambda doc: None)

        self.assertIsInstance(result, HistoryOperationResult)
        self.assertFalse(result.success)
        self.assertIn("not found", result.errors[0])
        mocks["frappe"].get_doc.assert_not_called()


class TestRecursionGuard(unittest.TestCase):
    """_with_doc must prevent recursive calls via the recursion flag."""

    def test_recursive_call_skips_callback(self):
        callback = MagicMock()
        with _standard_mocks(should_proceed=False):
            result = ConcreteHistoryManager._with_doc("DN-001", "test op", callback)

        self.assertIsInstance(result, HistoryOperationResult)
        self.assertTrue(result.success)
        callback.assert_not_called()


class TestExceptionHandling(unittest.TestCase):
    """_with_doc must catch exceptions and return failure, not raise."""

    def test_callback_exception_returns_failure(self):
        def exploding_callback(doc):
            raise ValueError("something broke")

        with _standard_mocks():
            with patch(f"{_BHM}.log_history_error"):
                result = ConcreteHistoryManager._with_doc(
                    "DN-001", "test op", exploding_callback
                )

        self.assertIsInstance(result, HistoryOperationResult)
        self.assertFalse(result.success)
        self.assertIn("something broke", result.errors[0])

    def test_callback_exception_logs_error(self):
        def exploding_callback(doc):
            raise ValueError("boom")

        with _standard_mocks():
            with patch(f"{_BHM}.log_history_error") as mock_log:
                ConcreteHistoryManager._with_doc("DN-001", "test op", exploding_callback)

        mock_log.assert_called_once()
        self.assertTrue(mock_log.call_args[1].get("include_traceback", False))


class TestSaveFailure(unittest.TestCase):
    """_with_doc must propagate save failures from safe_child_table_update."""

    def test_returns_failed_save_result(self):
        failed = HistoryOperationResult(success=False, message="fail", errors=["Permission denied"])
        with _standard_mocks():
            with patch(f"{_BHM}.safe_child_table_update", return_value=failed):
                with patch(f"{_BHM}.log_history_error"):
                    result = ConcreteHistoryManager._with_doc(
                        "DN-001", "test op", lambda doc: None
                    )

        self.assertIsInstance(result, HistoryOperationResult)
        self.assertFalse(result.success)
        self.assertIs(result, failed)

    def test_logs_on_save_failure(self):
        failed = HistoryOperationResult(success=False, message="fail", errors=["DB error"])
        with _standard_mocks():
            with patch(f"{_BHM}.safe_child_table_update", return_value=failed):
                with patch(f"{_BHM}.log_history_error") as mock_log:
                    ConcreteHistoryManager._with_doc(
                        "DN-001", "test op", lambda doc: None, error_title="Test Error"
                    )

        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args[1]["title"], "Test Error")


class TestTruthinessBackwardCompatibility(unittest.TestCase):
    """Existing callers use `if result:` and `if not result:` — must work."""

    def test_success_is_truthy(self):
        self.assertTrue(HistoryOperationResult(success=True))

    def test_failure_is_falsy(self):
        self.assertFalse(HistoryOperationResult(success=False))

    def test_if_not_pattern_for_error_handling(self):
        """Pattern: `if not cls._with_doc(...):`"""
        fail = HistoryOperationResult(success=False, errors=["err"])
        entered = False
        if not fail:
            entered = True
        self.assertTrue(entered)

    def test_if_pattern_for_success(self):
        """Pattern: `success = cls._with_doc(...); if success:`"""
        ok = HistoryOperationResult(success=True)
        entered = False
        if ok:
            entered = True
        self.assertTrue(entered)


if __name__ == "__main__":
    unittest.main()
