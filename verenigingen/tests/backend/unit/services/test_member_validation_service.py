# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Unit Tests for MemberValidationService

Tests the member validation orchestration service to ensure:
- All validations are executed
- Core field validations work correctly
- Duration updates are conditional
- Payment validations are called
- Member ID and fee validations are called
- Status sync is conditional
- Application status clearing works correctly

Extracted from Member.validate() method.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestMemberValidationServiceExecute(unittest.TestCase):
    """Test execute_validation() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.validation.member_validation_service import (
            get_member_validation_service,
        )
        self.service = get_member_validation_service()

    def test_executes_all_validations(self):
        """Test that all validation operations are executed"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.is_new.return_value = False
        mock_member.status = "Active"
        mock_member.application_status = None
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = False

        with patch.object(self.service, "_validate_core_fields", return_value={"success": True}):
            with patch.object(self.service, "_validate_payment_fields", return_value={"success": True}):
                with patch.object(self.service, "_validate_member_id_and_fees", return_value={"success": True}):
                    with patch.object(self.service, "_sync_status_fields_if_needed", return_value={"success": True}):
                        result = self.service.execute_validation(mock_member)

        # All validations should be in the result
        self.assertIn("core_fields", result["validations"])
        self.assertIn("duration", result["validations"])
        self.assertIn("payment", result["validations"])
        self.assertIn("member_id", result["validations"])
        self.assertIn("status_sync", result["validations"])
        self.assertIn("application_status", result["validations"])


class TestMemberValidationServiceDuration(unittest.TestCase):
    """Test _update_duration_if_needed() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.validation.member_validation_service import (
            get_member_validation_service,
        )
        self.service = get_member_validation_service()

    def test_updates_when_force_flag_set(self):
        """Test that duration is updated when _force_duration_update flag is set"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member._force_duration_update = True
        mock_member.is_new.return_value = False

        result = self.service._update_duration_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["updated"])
        mock_member.calculate_cumulative_membership_duration.assert_called_once()

    def test_updates_for_new_members(self):
        """Test that duration is updated for new members"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member._force_duration_update = False
        mock_member.is_new.return_value = True

        result = self.service._update_duration_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["updated"])
        mock_member.calculate_cumulative_membership_duration.assert_called_once()

    def test_skips_when_not_needed(self):
        """Test that duration is skipped when not needed"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member._force_duration_update = False
        mock_member.is_new.return_value = False

        result = self.service._update_duration_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["updated"])
        self.assertEqual(result["reason"], "not_needed")
        mock_member.calculate_cumulative_membership_duration.assert_not_called()


class TestMemberValidationServicePayment(unittest.TestCase):
    """Test _validate_payment_fields() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.validation.member_validation_service import (
            get_member_validation_service,
        )
        self.service = get_member_validation_service()

    def test_calls_payment_validations(self):
        """Test that payment validation methods are called"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"

        result = self.service._validate_payment_fields(mock_member)

        self.assertTrue(result["success"])
        mock_member.validate_payment_method.assert_called_once()
        mock_member.set_payment_reference.assert_called_once()
        mock_member.validate_bank_details.assert_called_once()


class TestMemberValidationServiceStatusSync(unittest.TestCase):
    """Test _sync_status_fields_if_needed() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.validation.member_validation_service import (
            get_member_validation_service,
        )
        self.service = get_member_validation_service()

    @patch("verenigingen.services.member.core.member_status_service.sync_member_status_fields")
    def test_syncs_when_flag_not_set(self, mock_sync):
        """Test that status is synced when ignore flag is not set"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = False

        result = self.service._sync_status_fields_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["synced"])
        mock_sync.assert_called_once_with(mock_member)

    def test_skips_when_flag_set(self):
        """Test that status sync is skipped when ignore flag is set"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = True

        result = self.service._sync_status_fields_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "ignore_status_validation")


class TestMemberValidationServiceApplicationStatus(unittest.TestCase):
    """Test _clear_application_status_if_needed() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.validation.member_validation_service import (
            get_member_validation_service,
        )
        self.service = get_member_validation_service()

    def test_clears_when_conditions_met(self):
        """Test that application_status is cleared when conditions are met"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.status = "Active"  # Not Pending or Rejected
        mock_member.application_status = "Approved"  # Is workflow status
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = False

        result = self.service._clear_application_status_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertTrue(result["cleared"])
        self.assertIsNone(mock_member.application_status)

    def test_skips_when_ignore_flag_set(self):
        """Test that clearing is skipped when ignore flag is set"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.status = "Active"
        mock_member.application_status = "Approved"
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = True

        result = self.service._clear_application_status_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["cleared"])
        self.assertEqual(result["reason"], "ignore_status_validation")

    def test_skips_when_status_is_pending(self):
        """Test that clearing is skipped when status is Pending"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.status = "Pending"
        mock_member.application_status = "Under Review"
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = False

        result = self.service._clear_application_status_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["cleared"])
        self.assertEqual(result["reason"], "conditions_not_met")

    def test_skips_when_status_is_rejected(self):
        """Test that clearing is skipped when status is Rejected"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.status = "Rejected"
        mock_member.application_status = "Approved"
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = False

        result = self.service._clear_application_status_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["cleared"])
        self.assertEqual(result["reason"], "conditions_not_met")

    def test_skips_when_application_status_not_workflow(self):
        """Test that clearing is skipped when application_status is not a workflow status"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        mock_member.status = "Active"
        mock_member.application_status = None  # Not a workflow status
        mock_member.flags = MagicMock()
        mock_member.flags.ignore_status_validation = False

        result = self.service._clear_application_status_if_needed(mock_member)

        self.assertTrue(result["success"])
        self.assertFalse(result["cleared"])
        self.assertEqual(result["reason"], "conditions_not_met")


class TestMemberValidationServiceMemberIdAndFees(unittest.TestCase):
    """Test _validate_member_id_and_fees() method"""

    def setUp(self):
        super().setUp()
        from verenigingen.services.member.validation.member_validation_service import (
            get_member_validation_service,
        )
        self.service = get_member_validation_service()

    def test_validates_member_id_and_fees(self):
        """Test that member ID and fee validation method completes and calls fee handler"""
        mock_member = MagicMock()
        mock_member.name = "MEM-001"
        # Simulate a new local document that won't trigger ID change validation
        mock_member.get.return_value = True  # __islocal = True

        result = self.service._validate_member_id_and_fees(mock_member)

        self.assertTrue(result["success"])
        mock_member.handle_fee_override_changes.assert_called_once()


if __name__ == "__main__":
    unittest.main()
