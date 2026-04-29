# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for MollieSyncService.

Regression coverage for the bug where _update_customer_mollie_fields tried to
write a non-existent custom_subscription_status column to the Customer table,
and where the service hard-coded subscription_status="active" on Member instead
of honoring the caller-supplied status.
"""

from unittest.mock import MagicMock, patch

from verenigingen.services.csv_import.mollie_sync_service import MollieSyncService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestUpdateCustomerMollieFields(EnhancedTestCase):
    """Tests for MollieSyncService._update_customer_mollie_fields()."""

    def setUp(self):
        super().setUp()
        self.service = MollieSyncService()

    @patch("verenigingen.services.csv_import.mollie_sync_service.frappe")
    def test_writes_only_real_customer_columns(self, mock_frappe):
        """custom_subscription_status must NOT be written to Customer.

        Customer has custom_mollie_customer_id and custom_mollie_subscription_id
        only; subscription_status lives on Member. Writing custom_subscription_status
        to Customer caused MySQL 1054 'Unknown column' errors in production.
        """
        self.service._update_customer_mollie_fields(
            "CUST-001",
            {
                "custom_mollie_customer_id": "cst_abc",
                "custom_mollie_subscription_id": "sub_123",
                "custom_subscription_status": "canceled",
            },
        )

        mock_frappe.db.set_value.assert_called_once()
        args = mock_frappe.db.set_value.call_args[0]
        self.assertEqual(args[0], "Customer")
        self.assertEqual(args[1], "CUST-001")
        values = args[2]
        self.assertIn("custom_mollie_customer_id", values)
        self.assertIn("custom_mollie_subscription_id", values)
        self.assertNotIn("custom_subscription_status", values)

    @patch("verenigingen.services.csv_import.mollie_sync_service.frappe")
    def test_skips_write_when_no_real_fields_present(self, mock_frappe):
        """When neither real Mollie ID is in the dict, no DB write happens."""
        self.service._update_customer_mollie_fields(
            "CUST-001",
            {"custom_subscription_status": "canceled"},
        )

        mock_frappe.db.set_value.assert_not_called()

    @patch("verenigingen.services.csv_import.mollie_sync_service.frappe")
    def test_writes_only_provided_fields(self, mock_frappe):
        """Only fields actually supplied by the caller end up in the DB write."""
        self.service._update_customer_mollie_fields(
            "CUST-001",
            {"custom_mollie_customer_id": "cst_abc"},
        )

        mock_frappe.db.set_value.assert_called_once()
        values = mock_frappe.db.set_value.call_args[0][2]
        self.assertEqual(values, {"custom_mollie_customer_id": "cst_abc"})


class TestSyncMollieData(EnhancedTestCase):
    """Tests for MollieSyncService.sync_mollie_data() Member status handling."""

    def setUp(self):
        super().setUp()
        self.service = MollieSyncService()

    def _make_member_doc(self):
        member_doc = MagicMock()
        member_doc.name = "MEM-001"
        member_doc.customer = "CUST-001"
        return member_doc

    @patch("verenigingen.services.csv_import.mollie_sync_service.frappe")
    def test_honors_canceled_status_from_mollie_data(self, _mock_frappe):
        """subscription_status='canceled' from mollie_data must reach Member.

        Previously the service hard-coded 'active', which forced callers to
        post-correct the Member after the call. Now the service honors what the
        caller passes, so terminated members get 'canceled' on the first write.
        """
        member_doc = self._make_member_doc()

        with patch.object(self.service, "_validate_mollie_data"), patch.object(
            self.service, "_update_customer_mollie_fields"
        ):
            self.service.sync_mollie_data(
                member_doc,
                {
                    "custom_mollie_customer_id": "cst_abc",
                    "custom_mollie_subscription_id": "sub_123",
                    "custom_subscription_status": "canceled",
                },
            )

        self.assertEqual(member_doc.subscription_status, "canceled")
        self.assertEqual(member_doc.mollie_subscription_id, "sub_123")
        member_doc.save.assert_called_once()

    @patch("verenigingen.services.csv_import.mollie_sync_service.frappe")
    def test_defaults_to_active_when_status_missing(self, _mock_frappe):
        """When no status is supplied but a subscription exists, default to 'active'.

        This preserves backward-compat for callers (member_import_service,
        mijnrood_csv_import) that pass 'active' implicitly.
        """
        member_doc = self._make_member_doc()

        with patch.object(self.service, "_validate_mollie_data"), patch.object(
            self.service, "_update_customer_mollie_fields"
        ):
            self.service.sync_mollie_data(
                member_doc,
                {
                    "custom_mollie_customer_id": "cst_abc",
                    "custom_mollie_subscription_id": "sub_123",
                },
            )

        self.assertEqual(member_doc.subscription_status, "active")

    @patch("verenigingen.services.csv_import.mollie_sync_service.frappe")
    def test_no_subscription_status_change_without_subscription_id(self, _mock_frappe):
        """If there's no subscription_id, subscription_status is left untouched.

        Member.subscription_status is only set when a subscription is present.
        """
        member_doc = self._make_member_doc()
        # Sentinel that should never be overwritten
        member_doc.subscription_status = "<UNCHANGED>"

        with patch.object(self.service, "_validate_mollie_data"), patch.object(
            self.service, "_update_customer_mollie_fields"
        ):
            self.service.sync_mollie_data(
                member_doc,
                {"custom_mollie_customer_id": "cst_abc"},
            )

        self.assertEqual(member_doc.subscription_status, "<UNCHANGED>")
