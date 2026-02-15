"""
Donation History Manager Regression Tests
==========================================

Regression tests for bugs discovered in the DonationHistoryManager:

1. secure_document_operation + bypass_validations fails for background service users
   (background.service@verenigingen.local lacks System Manager role, so the role-gated
   bypass_validations check rejects the request before system user escalation happens).
   Fix: Inherit BaseHistoryManager which uses safe_child_table_update() — only syncs the
   specific child table via update_child_table(), avoiding unrelated link validation.

2. DonationHistoryManager() called without required donor_name arg in donor_service.py
   (silently fails due to try/except swallowing the TypeError).
   Fix: Converted to @staticmethod API — no constructor, no instance state to get wrong.

3. DRY violation: save/error boilerplate duplicated 3x instead of using BaseHistoryManager.
   Fix: Inherit BaseHistoryManager, use _with_doc() callback pattern.

Created: 2026-02-15
"""

import inspect
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import nowdate


class TestDonationHistoryManagerInheritsBaseHistoryManager(unittest.TestCase):
    """DonationHistoryManager must inherit BaseHistoryManager to avoid DRY violations."""

    def test_inherits_base_history_manager(self):
        """DonationHistoryManager must be a subclass of BaseHistoryManager."""
        from verenigingen.utils.base_history_manager import BaseHistoryManager
        from verenigingen.utils.donation_history_manager import DonationHistoryManager

        self.assertTrue(
            issubclass(DonationHistoryManager, BaseHistoryManager),
            "DonationHistoryManager must inherit BaseHistoryManager",
        )

    def test_class_constants_set(self):
        """Required class constants must be set for BaseHistoryManager protocol."""
        from verenigingen.utils.donation_history_manager import DonationHistoryManager

        self.assertEqual(DonationHistoryManager.PARENT_DOCTYPE, "Donor")
        self.assertEqual(DonationHistoryManager.CHILD_TABLE, "donor_history")
        self.assertEqual(DonationHistoryManager.PERMISSION, "Donor:write")
        self.assertTrue(
            DonationHistoryManager.RECURSION_FLAG,
            "RECURSION_FLAG must be set to a non-empty string",
        )


class TestDonationHistoryManagerUsesStaticMethods(unittest.TestCase):
    """DonationHistoryManager methods must be @staticmethod — no instance state."""

    def test_add_donation_entry_is_static(self):
        from verenigingen.utils.donation_history_manager import DonationHistoryManager

        self.assertIsInstance(
            inspect.getattr_static(DonationHistoryManager, "add_donation_entry"),
            staticmethod,
        )

    def test_remove_donation_entry_is_static(self):
        from verenigingen.utils.donation_history_manager import DonationHistoryManager

        self.assertIsInstance(
            inspect.getattr_static(DonationHistoryManager, "remove_donation_entry"),
            staticmethod,
        )

    def test_sync_donation_history_is_static(self):
        from verenigingen.utils.donation_history_manager import DonationHistoryManager

        self.assertIsInstance(
            inspect.getattr_static(DonationHistoryManager, "sync_donation_history"),
            staticmethod,
        )

    def test_get_donation_summary_is_static(self):
        from verenigingen.utils.donation_history_manager import DonationHistoryManager

        self.assertIsInstance(
            inspect.getattr_static(DonationHistoryManager, "get_donation_summary"),
            staticmethod,
        )


class TestNoSecureDocumentOperation(unittest.TestCase):
    """Regression: must NOT use secure_document_operation or bypass_validations."""

    def test_no_import_of_secure_document_operation(self):
        """
        Bug: Used secure_document_operation with bypass_validations=["link_validation"],
        which has role-gated permission checks that fail for background service users.
        Fix: Inherits BaseHistoryManager which uses safe_child_table_update().
        """
        import verenigingen.utils.donation_history_manager as mod

        source = inspect.getsource(mod)
        self.assertNotIn("secure_document_operation", source)

    def test_no_bypass_validations(self):
        """safe_child_table_update makes bypass_validations unnecessary."""
        import verenigingen.utils.donation_history_manager as mod

        source = inspect.getsource(mod)
        self.assertNotIn("bypass_validations", source)

    def test_no_allow_system_user(self):
        """Webhook User role has Donor:write directly — no escalation needed."""
        import verenigingen.utils.donation_history_manager as mod

        source = inspect.getsource(mod)
        self.assertNotIn("allow_system_user", source)


class TestDonorServiceCallsSiteCorrectly(unittest.TestCase):
    """Regression: donor_service must use the @staticmethod API."""

    def test_donor_service_uses_static_call(self):
        """
        Bug: Called DonationHistoryManager() without args — TypeError swallowed.
        Fix: Uses DonationHistoryManager.add_donation_entry(donor_name, donation).
        """
        from verenigingen.services.donation.donor_service import DonationDonorService

        source = inspect.getsource(DonationDonorService.update_donor_donation_history)
        self.assertIn(
            "DonationHistoryManager.add_donation_entry(",
            source,
            "Must use static method call, not instance constructor",
        )
        self.assertNotIn(
            "DonationHistoryManager(donor_name)",
            source,
            "Must not instantiate — use @staticmethod API",
        )


class TestDocEventHooksUseStaticAPI(unittest.TestCase):
    """Doc event hooks must use the @staticmethod API."""

    def test_hooks_use_static_calls(self):
        import verenigingen.utils.donation_history_manager as mod

        for fn_name in ["on_donation_insert", "on_donation_update", "on_donation_submit",
                        "on_donation_cancel", "on_donation_delete"]:
            fn = getattr(mod, fn_name)
            source = inspect.getsource(fn)
            self.assertIn(
                "DonationHistoryManager.",
                source,
                f"{fn_name} must use DonationHistoryManager.method() static call",
            )
            self.assertNotIn(
                "DonationHistoryManager(",
                source,
                f"{fn_name} must not instantiate DonationHistoryManager",
            )


class TestBaseHistoryManagerReturnsHistoryOperationResult(unittest.TestCase):
    """BaseHistoryManager._with_doc() must return HistoryOperationResult, not bool."""

    def test_return_type_annotation(self):
        from verenigingen.utils.base_history_manager import BaseHistoryManager
        from verenigingen.utils.history_manager_utils import HistoryOperationResult

        hints = BaseHistoryManager._with_doc.__annotations__
        self.assertIs(
            hints.get("return"),
            HistoryOperationResult,
            "_with_doc return annotation must be HistoryOperationResult",
        )

    def test_truthiness_backward_compatible(self):
        """HistoryOperationResult must be truthy/falsy for existing callers."""
        from verenigingen.utils.history_manager_utils import HistoryOperationResult

        self.assertTrue(bool(HistoryOperationResult(success=True)))
        self.assertFalse(bool(HistoryOperationResult(success=False)))


class TestWebhookUserPermissions(unittest.TestCase):
    """Prerequisite: Webhook User role must have Donor:write permission."""

    def test_webhook_user_has_donor_write_permission(self):
        meta = frappe.get_meta("Donor")
        webhook_perms = [p for p in meta.permissions if p.role == "Verenigingen Webhook User"]
        self.assertTrue(len(webhook_perms) > 0, "Donor must have Webhook User permissions")
        self.assertTrue(
            any(p.write for p in webhook_perms),
            "Webhook User must have write permission on Donor",
        )


class TestSafeChildTableUpdateReexport(unittest.TestCase):
    """safe_child_table_update must be importable from top-level utils."""

    def test_importable_from_utils(self):
        from verenigingen.utils import safe_child_table_update as fn

        self.assertTrue(callable(fn))

    def test_same_function_both_paths(self):
        from verenigingen.utils import safe_child_table_update as fn1
        from verenigingen.utils.history_manager_utils import safe_child_table_update as fn2

        self.assertIs(fn1, fn2)


class TestAddDonationEntryWithMockedWithDoc(unittest.TestCase):
    """Integration: add_donation_entry delegates to _with_doc correctly."""

    def test_delegates_to_with_doc(self):
        """add_donation_entry must call _with_doc with correct class constants."""
        from verenigingen.utils.donation_history_manager import DonationHistoryManager

        mock_donation = MagicMock()
        mock_donation.name = "DONATION-001"

        with patch.object(DonationHistoryManager, "_with_doc") as mock_with_doc:
            mock_with_doc.return_value = MagicMock(success=True, errors=[], message="ok")

            # Also mock the frappe.get_doc call in the action-detection path
            with patch("frappe.get_doc") as mock_get_doc:
                mock_donor = MagicMock()
                mock_donor.donor_history = []
                mock_get_doc.return_value = mock_donor

                DonationHistoryManager.add_donation_entry("DN-001", mock_donation)

            mock_with_doc.assert_called_once()
            call_args = mock_with_doc.call_args
            self.assertEqual(call_args[0][0], "DN-001")  # donor_name
            self.assertIn("DONATION-001", call_args[0][1])  # operation_name includes donation
            self.assertTrue(callable(call_args[0][2]))  # callback


if __name__ == "__main__":
    unittest.main()
