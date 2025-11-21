#!/usr/bin/env python3
"""
Unit Tests for SEPA Mandate Lifecycle Service

Tests the SEPAMandateLifecycleService class methods in isolation with realistic
data generation and minimal mocking. Focuses on status management, workflow
transitions, and lifecycle event handling.

Test Coverage:
- set_status_based_on_dates() with various date scenarios
- handle_status_transition() validation and workflow
- process_mandate_cancellation() workflow and notifications
- sync_status_and_active_flag() consistency
- Event handling: handle_mandate_creation() and handle_mandate_update()
- Edge cases: invalid transitions, date-based expiry, cancellation scenarios
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import date, timedelta

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import SEPAMandateLifecycleService


class TestSEPAMandateLifecycleService(EnhancedTestCase):
    """Unit tests for SEPA Mandate Lifecycle Service"""

    def setUp(self):
        """Set up test environment and service instance"""
        super().setUp()
        self.service = SEPAMandateLifecycleService()

    def tearDown(self):
        """Clean up after each test"""
        super().tearDown()

    def _create_mock_mandate(self, **kwargs):
        """Create a mock mandate document with default values"""
        defaults = {
            'sign_date': None,
            'expiry_date': None,
            'status': None,
            'is_active': 0,
            'member': None,
            'mandate_id': None,
            'iban': None,
            'name': 'SEPA-MANDATE-001',
            'cancellation_date': None,
            'cancellation_reason': None
        }
        defaults.update(kwargs)
        mock_mandate = Mock(**defaults)

        # Add methods that might be called
        mock_mandate.has_value_changed = Mock(return_value=False)
        mock_mandate.get_doc_before_save = Mock(return_value=None)

        return mock_mandate

    # ========================================================================
    # Tests for set_status_based_on_dates()
    # ========================================================================

    def test_set_status_based_on_dates_no_dates(self):
        """Test status calculation when no dates are provided"""
        mandate = self._create_mock_mandate(
            sign_date=None,
            expiry_date=None,
            status='Draft'
        )

        result = self.service.set_status_based_on_dates(mandate)

        # Should preserve existing status
        self.assertEqual(result, 'Draft')

    def test_set_status_based_on_dates_future_sign_date(self):
        """Test status calculation when sign date is in the future"""
        future_date = date.today() + timedelta(days=10)

        mandate = self._create_mock_mandate(
            sign_date=future_date,
            expiry_date=None,
            status='Draft'
        )

        with patch('frappe.utils.getdate', side_effect=lambda x: x if x else date.today()):
            result = self.service.set_status_based_on_dates(mandate)

            # Should be Pending when sign date is in future
            self.assertEqual(result, 'Pending')

    def test_set_status_based_on_dates_expired_mandate(self):
        """Test status calculation for expired mandate"""
        past_expiry = date.today() - timedelta(days=10)

        mandate = self._create_mock_mandate(
            sign_date=date.today() - timedelta(days=365),
            expiry_date=past_expiry,
            status='Active'
        )

        with patch('frappe.utils.getdate', side_effect=lambda x: x if x else date.today()):
            result = self.service.set_status_based_on_dates(mandate)

            # Should be Expired when past expiry date
            self.assertEqual(result, 'Expired')

    def test_set_status_based_on_dates_active_period(self):
        """Test status calculation during valid active period"""
        past_sign = date.today() - timedelta(days=30)
        future_expiry = date.today() + timedelta(days=365)

        mandate = self._create_mock_mandate(
            sign_date=past_sign,
            expiry_date=future_expiry,
            status=None  # No existing status
        )

        with patch('frappe.utils.getdate', side_effect=lambda x: x if x else date.today()):
            result = self.service.set_status_based_on_dates(mandate)

            # Should auto-activate when no status and within valid period
            self.assertEqual(result, 'Active')

    def test_set_status_based_on_dates_preserve_terminal_states(self):
        """Test that terminal states are preserved"""
        terminal_states = ['Cancelled', 'Rejected', 'Expired']

        for terminal_status in terminal_states:
            with self.subTest(status=terminal_status):
                mandate = self._create_mock_mandate(
                    sign_date=date.today() - timedelta(days=30),
                    expiry_date=date.today() + timedelta(days=30),
                    status=terminal_status
                )

                with patch('frappe.utils.getdate', side_effect=lambda x: x if x else date.today()):
                    result = self.service.set_status_based_on_dates(mandate)

                    # Terminal states should be preserved
                    self.assertEqual(result, terminal_status)

    def test_set_status_based_on_dates_preserve_explicit_status(self):
        """Test that explicitly set non-terminal statuses are preserved"""
        explicit_statuses = ['Draft', 'Suspended']

        for explicit_status in explicit_statuses:
            with self.subTest(status=explicit_status):
                mandate = self._create_mock_mandate(
                    sign_date=date.today() - timedelta(days=30),
                    expiry_date=date.today() + timedelta(days=30),
                    status=explicit_status
                )

                with patch('frappe.utils.getdate', side_effect=lambda x: x if x else date.today()):
                    result = self.service.set_status_based_on_dates(mandate)

                    # Explicit statuses should be preserved
                    self.assertEqual(result, explicit_status)

    def test_set_status_based_on_dates_exception_handling(self):
        """Test exception handling in status calculation"""
        mandate = self._create_mock_mandate(status='Draft')

        with patch('frappe.utils.getdate', side_effect=Exception("Date error")):
            result = self.service.set_status_based_on_dates(mandate)

            # Should fallback to existing status on error
            self.assertEqual(result, 'Draft')

    # ========================================================================
    # Tests for sync_status_and_active_flag()
    # ========================================================================

    def test_sync_status_and_active_flag_active(self):
        """Test synchronization when status is Active"""
        mandate = self._create_mock_mandate(status='Active', is_active=0)

        self.service.sync_status_and_active_flag(mandate)

        # Should set is_active to 1 when status is Active
        self.assertEqual(mandate.is_active, 1)

    def test_sync_status_and_active_flag_non_active(self):
        """Test synchronization when status is not Active"""
        non_active_statuses = ['Draft', 'Cancelled', 'Expired', 'Suspended']

        for status in non_active_statuses:
            with self.subTest(status=status):
                mandate = self._create_mock_mandate(status=status, is_active=1)

                self.service.sync_status_and_active_flag(mandate)

                # Should set is_active to 0 for non-Active statuses
                self.assertEqual(mandate.is_active, 0)

    def test_sync_status_and_active_flag_exception_handling(self):
        """Test exception handling in status synchronization"""
        mandate = Mock()
        mandate.status = 'Active'
        # Make is_active assignment fail
        type(mandate).is_active = Mock(side_effect=Exception("Sync error"))

        # Should not raise exception
        self.service.sync_status_and_active_flag(mandate)

    # ========================================================================
    # Tests for handle_status_transition()
    # ========================================================================

    def test_handle_status_transition_valid_transition(self):
        """Test handling of valid status transitions"""
        mandate = self._create_mock_mandate(status='Active', mandate_id='TEST-001', iban='NL91TEST0123456789')

        with patch.object(self.service, '_is_valid_status_transition', return_value=True):
            with patch.object(self.service, '_handle_activation') as mock_activation:
                with patch.object(self.service, 'sync_status_and_active_flag') as mock_sync:

                    result = self.service.handle_status_transition(mandate, 'Draft')

                    self.assertTrue(result['success'])
                    mock_activation.assert_called_once()
                    mock_sync.assert_called_once()

    def test_handle_status_transition_invalid_transition(self):
        """Test handling of invalid status transitions"""
        mandate = self._create_mock_mandate(status='Active')

        with patch.object(self.service, '_is_valid_status_transition', return_value=False):

            result = self.service.handle_status_transition(mandate, 'Cancelled')

            self.assertFalse(result['success'])
            self.assertIn('Invalid status transition', result['errors'][0])

    def test_handle_status_transition_cancellation(self):
        """Test handling of cancellation transition"""
        mandate = self._create_mock_mandate(status='Cancelled')

        with patch.object(self.service, '_is_valid_status_transition', return_value=True):
            with patch.object(self.service, '_handle_cancellation') as mock_cancellation:

                result = self.service.handle_status_transition(mandate, 'Active')

                mock_cancellation.assert_called_once()

    def test_handle_status_transition_expiration(self):
        """Test handling of expiration transition"""
        mandate = self._create_mock_mandate(status='Expired')

        with patch.object(self.service, '_is_valid_status_transition', return_value=True):
            with patch.object(self.service, '_handle_expiration') as mock_expiration:

                result = self.service.handle_status_transition(mandate, 'Active')

                mock_expiration.assert_called_once()

    def test_is_valid_status_transition_matrix(self):
        """Test status transition validation matrix"""
        # Define valid transitions as per service logic
        valid_transitions = {
            'Draft': ['Pending', 'Active', 'Cancelled'],
            'Pending': ['Active', 'Cancelled', 'Rejected'],
            'Active': ['Cancelled', 'Expired'],
            'Cancelled': [],  # Terminal state
            'Expired': ['Cancelled'],
            'Rejected': ['Draft', 'Cancelled']
        }

        for from_status, allowed_statuses in valid_transitions.items():
            for to_status in ['Draft', 'Pending', 'Active', 'Cancelled', 'Expired', 'Rejected']:
                with self.subTest(from_status=from_status, to_status=to_status):
                    expected = to_status in allowed_statuses
                    result = self.service._is_valid_status_transition(from_status, to_status)
                    self.assertEqual(result, expected)

    # ========================================================================
    # Tests for process_mandate_cancellation()
    # ========================================================================

    def test_process_mandate_cancellation_successful(self):
        """Test successful mandate cancellation"""
        mandate = self._create_mock_mandate(
            status='Active',
            member='MEMBER-001'
        )

        with patch.object(self.service, '_update_member_mandate_status') as mock_update:
            with patch('frappe.utils.today', return_value=date.today()):

                result = self.service.process_mandate_cancellation(mandate, "Member request")

                self.assertTrue(result['success'])
                self.assertEqual(mandate.status, 'Cancelled')
                self.assertEqual(mandate.is_active, 0)
                self.assertEqual(mandate.cancellation_reason, "Member request")
                mock_update.assert_called_once_with(mandate, 'Cancelled')

    def test_process_mandate_cancellation_already_cancelled(self):
        """Test cancellation of already cancelled mandate"""
        mandate = self._create_mock_mandate(status='Cancelled')

        result = self.service.process_mandate_cancellation(mandate)

        self.assertTrue(result['success'])  # Still success, but with warning
        self.assertTrue(any('already cancelled' in warning for warning in result['warnings']))

    def test_process_mandate_cancellation_with_notifications(self):
        """Test cancellation with notifications"""
        mandate = self._create_mock_mandate(status='Active')

        mock_notification_manager = Mock()
        with patch('verenigingen.verenigingen_payments.utils.sepa_notifications.SEPAMandateNotificationManager', return_value=mock_notification_manager):
            with patch.object(self.service, '_update_member_mandate_status'):

                result = self.service.process_mandate_cancellation(mandate)

                mock_notification_manager.send_mandate_status_notification.assert_called_once()
                self.assertIn('status_change', result['notifications_sent'])

    def test_process_mandate_cancellation_notification_failure(self):
        """Test cancellation when notification fails"""
        mandate = self._create_mock_mandate(status='Active')

        with patch('verenigingen.verenigingen_payments.utils.sepa_notifications.SEPAMandateNotificationManager', side_effect=Exception("Notification error")):
            with patch.object(self.service, '_update_member_mandate_status'):

                result = self.service.process_mandate_cancellation(mandate)

                self.assertTrue(result['success'])  # Should still succeed
                self.assertTrue(any('Failed to send notification' in warning for warning in result['warnings']))

    # ========================================================================
    # Tests for handle_mandate_creation()
    # ========================================================================

    def test_handle_mandate_creation_successful(self):
        """Test successful mandate creation handling"""
        mandate = self._create_mock_mandate(
            status='Active',
            member='MEMBER-001'
        )

        # Mock the member integration service
        mock_integration_service = Mock()
        mock_integration_service.update_member_mandate_relationship.return_value = {'success': True, 'errors': []}

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service.sepa_mandate_member_integration_service', mock_integration_service):
            mock_notification_manager = Mock()
            with patch('verenigingen.verenigingen_payments.utils.sepa_notifications.SEPAMandateNotificationManager', return_value=mock_notification_manager):

                result = self.service.handle_mandate_creation(mandate)

                self.assertTrue(result['success'])
                mock_integration_service.update_member_mandate_relationship.assert_called_once_with(mandate)
                mock_notification_manager.send_mandate_created_notification.assert_called_once_with(mandate)

    def test_handle_mandate_creation_integration_failure(self):
        """Test mandate creation handling when member integration fails"""
        mandate = self._create_mock_mandate(status='Active')

        # Mock failed integration
        mock_integration_service = Mock()
        mock_integration_service.update_member_mandate_relationship.return_value = {
            'success': False,
            'errors': ['Integration failed']
        }

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service.sepa_mandate_member_integration_service', mock_integration_service):

            result = self.service.handle_mandate_creation(mandate)

            self.assertEqual(result['errors'], ['Integration failed'])

    def test_handle_mandate_creation_draft_status(self):
        """Test mandate creation handling for draft status (no notifications)"""
        mandate = self._create_mock_mandate(
            status='Draft',
            member='MEMBER-001'
        )

        mock_integration_service = Mock()
        mock_integration_service.update_member_mandate_relationship.return_value = {'success': True, 'errors': []}

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service.sepa_mandate_member_integration_service', mock_integration_service):

            result = self.service.handle_mandate_creation(mandate)

            # Should not send notifications for draft status
            self.assertEqual(len(result['notifications_sent']), 0)

    # ========================================================================
    # Tests for handle_mandate_update()
    # ========================================================================

    def test_handle_mandate_update_status_change(self):
        """Test mandate update handling with status change"""
        mandate = self._create_mock_mandate(
            status='Active',
            member='MEMBER-001'
        )

        # Mock status change detection
        mandate.has_value_changed.return_value = True
        old_mandate = Mock(status='Draft')
        mandate.get_doc_before_save.return_value = old_mandate

        # Mock integration service
        mock_integration_service = Mock()
        mock_integration_service.update_member_mandate_relationship.return_value = {'success': True, 'errors': []}

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service.sepa_mandate_member_integration_service', mock_integration_service):
            with patch.object(self.service, 'handle_status_transition') as mock_transition:
                mock_transition.return_value = {'success': True, 'errors': []}

                mock_notification_manager = Mock()
                with patch('verenigingen.verenigingen_payments.utils.sepa_notifications.SEPAMandateNotificationManager', return_value=mock_notification_manager):

                    result = self.service.handle_mandate_update(mandate)

                    self.assertTrue(result['status_changed'])
                    mock_transition.assert_called_once_with(mandate, 'Draft')
                    mock_notification_manager.send_mandate_created_notification.assert_called_once_with(mandate)

    def test_handle_mandate_update_no_status_change(self):
        """Test mandate update handling without status change"""
        mandate = self._create_mock_mandate(
            status='Active',
            member='MEMBER-001'
        )

        # Mock no status change
        mandate.has_value_changed.return_value = False

        mock_integration_service = Mock()
        mock_integration_service.update_member_mandate_relationship.return_value = {'success': True, 'errors': []}

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service.sepa_mandate_member_integration_service', mock_integration_service):

            result = self.service.handle_mandate_update(mandate)

            self.assertFalse(result['status_changed'])
            # Should still update member relationship
            mock_integration_service.update_member_mandate_relationship.assert_called_once_with(mandate)

    def test_handle_mandate_update_cancellation_notification(self):
        """Test mandate update with cancellation notification"""
        mandate = self._create_mock_mandate(
            status='Cancelled',
            cancellation_reason='Member request'
        )

        # Mock status change to Cancelled
        mandate.has_value_changed.return_value = True
        old_mandate = Mock(status='Active')
        mandate.get_doc_before_save.return_value = old_mandate

        mock_integration_service = Mock()
        mock_integration_service.update_member_mandate_relationship.return_value = {'success': True, 'errors': []}

        with patch('verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service.sepa_mandate_member_integration_service', mock_integration_service):
            with patch.object(self.service, 'handle_status_transition') as mock_transition:
                mock_transition.return_value = {'success': True, 'errors': []}

                mock_notification_manager = Mock()
                with patch('verenigingen.verenigingen_payments.utils.sepa_notifications.SEPAMandateNotificationManager', return_value=mock_notification_manager):

                    result = self.service.handle_mandate_update(mandate)

                    mock_notification_manager.send_mandate_cancelled_notification.assert_called_once_with(mandate, 'Member request')
                    self.assertIn('mandate_cancelled', result['notifications_sent'])

    # ========================================================================
    # Tests for _handle_activation(), _handle_cancellation(), _handle_expiration()
    # ========================================================================

    def test_handle_activation_successful(self):
        """Test successful mandate activation"""
        mandate = self._create_mock_mandate(
            mandate_id='TEST-001',
            iban='NL91TEST0123456789'
        )
        result = {'success': True, 'warnings': [], 'errors': []}

        with patch.object(self.service, '_update_member_mandate_status') as mock_update:

            self.service._handle_activation(mandate, result)

            self.assertTrue(result['success'])
            self.assertTrue(any('activated successfully' in warning for warning in result['warnings']))

    def test_handle_activation_missing_requirements(self):
        """Test mandate activation with missing requirements"""
        mandate = self._create_mock_mandate(
            mandate_id=None,  # Missing
            iban=None  # Missing
        )
        result = {'success': True, 'warnings': [], 'errors': []}

        self.service._handle_activation(mandate, result)

        self.assertFalse(result['success'])
        self.assertEqual(len(result['errors']), 2)  # Two missing requirements

    def test_handle_cancellation_workflow(self):
        """Test cancellation workflow handling"""
        mandate = self._create_mock_mandate()
        result = {'success': True, 'warnings': [], 'errors': []}

        with patch('frappe.utils.today', return_value=date.today()):
            with patch.object(self.service, '_update_member_mandate_status') as mock_update:

                self.service._handle_cancellation(mandate, result)

                self.assertEqual(mandate.cancellation_date, date.today())
                mock_update.assert_called_once_with(mandate, 'Cancelled')

    def test_handle_expiration_workflow(self):
        """Test expiration workflow handling"""
        mandate = self._create_mock_mandate()
        result = {'success': True, 'warnings': [], 'errors': []}

        with patch.object(self.service, '_update_member_mandate_status') as mock_update:

            self.service._handle_expiration(mandate, result)

            mock_update.assert_called_once_with(mandate, 'Expired')
            self.assertTrue(any('expired' in warning for warning in result['warnings']))

    # ========================================================================
    # Integration and realistic scenario tests
    # ========================================================================

    def test_complete_mandate_lifecycle_workflow(self):
        """Test complete mandate lifecycle from creation to cancellation"""
        mandate = self._create_mock_mandate(
            status='Draft',
            mandate_id='VEG-2024-001',
            iban='NL91INGB0001234567',
            member='MEMBER-001'
        )

        # Test progression through lifecycle
        with patch('frappe.utils.getdate', side_effect=lambda x: x if x else date.today()):

            # 1. Draft -> Active (activation)
            mandate.status = 'Active'
            with patch.object(self.service, '_update_member_mandate_status'):
                result = self.service.handle_status_transition(mandate, 'Draft')
                self.assertTrue(result['success'])
                self.assertEqual(mandate.is_active, 1)

            # 2. Active -> Cancelled (cancellation)
            result = self.service.process_mandate_cancellation(mandate, "Member terminated")
            self.assertTrue(result['success'])
            self.assertEqual(mandate.status, 'Cancelled')
            self.assertEqual(mandate.is_active, 0)

    def test_date_based_status_transitions(self):
        """Test automatic status transitions based on dates"""
        today = date.today()

        # Test future sign date -> Pending
        mandate = self._create_mock_mandate(
            sign_date=today + timedelta(days=10),
            status='Draft'
        )

        with patch('frappe.utils.getdate', side_effect=lambda x: x if x else today):
            status = self.service.set_status_based_on_dates(mandate)
            self.assertEqual(status, 'Pending')

        # Test expired mandate -> Expired
        mandate.sign_date = today - timedelta(days=100)
        mandate.expiry_date = today - timedelta(days=10)
        mandate.status = 'Active'

        status = self.service.set_status_based_on_dates(mandate)
        self.assertEqual(status, 'Expired')

    def test_edge_case_same_day_expiry(self):
        """Test mandate expiring on the same day"""
        today = date.today()

        mandate = self._create_mock_mandate(
            sign_date=today - timedelta(days=30),
            expiry_date=today,  # Expires today
            status='Active'
        )

        with patch('frappe.utils.getdate', side_effect=lambda x: x if x else today):
            status = self.service.set_status_based_on_dates(mandate)

            # Should still be active on expiry date (expires at end of day)
            self.assertEqual(status, 'Active')

    def test_notification_failure_resilience(self):
        """Test that service continues working when notifications fail"""
        mandate = self._create_mock_mandate(status='Active')

        with patch('verenigingen.verenigingen_payments.utils.sepa_notifications.SEPAMandateNotificationManager', side_effect=ImportError("Module not found")):

            result = self.service.process_mandate_cancellation(mandate)

            # Should still succeed despite notification failure
            self.assertTrue(result['success'])
            self.assertEqual(mandate.status, 'Cancelled')


if __name__ == "__main__":
    unittest.main()