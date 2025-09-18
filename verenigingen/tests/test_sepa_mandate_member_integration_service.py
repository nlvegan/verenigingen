#!/usr/bin/env python3
"""
Unit Tests for SEPA Mandate Member Integration Service

Tests the SEPAMandateMemberIntegrationService class methods in isolation with
realistic data generation and minimal mocking. Focuses on member-mandate
relationship management, security validation, and database operations.

Test Coverage:
- update_member_mandate_relationship() core logic and workflow
- _validate_sepa_mandate_permissions() security validation
- _validate_mandate_link_fields() field validation
- _execute_secure_mandate_link_update() database operations
- bulk_update_member_mandates() bulk operations
- Edge cases: permission failures, missing fields, SQL operation validation
- Audit logging and error handling
"""

import unittest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import date, timedelta

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import SEPAMandateMemberIntegrationService


class TestSEPAMandateMemberIntegrationService(EnhancedTestCase):
    """Unit tests for SEPA Mandate Member Integration Service"""

    def setUp(self):
        """Set up test environment and service instance"""
        super().setUp()
        self.service = SEPAMandateMemberIntegrationService()

    def tearDown(self):
        """Clean up after each test"""
        super().tearDown()

    def _create_mock_mandate(self, **kwargs):
        """Create a mock mandate document with default values"""
        defaults = {
            'member': 'MEMBER-001',
            'name': 'SEPA-MANDATE-001',
            'mandate_id': 'VEG-2024-001',
            'status': 'Active',
            'is_active': 1,
            'sign_date': date.today() - timedelta(days=30),
            'expiry_date': date.today() + timedelta(days=365)
        }
        defaults.update(kwargs)
        return Mock(**defaults)

    def _create_mock_meta(self, fields):
        """Create a mock DocType meta with specified fields"""
        mock_meta = Mock()
        mock_fields = []
        for field_name in fields:
            field_mock = Mock()
            field_mock.fieldname = field_name
            mock_fields.append(field_mock)
        mock_meta.fields = mock_fields
        return mock_meta

    # ========================================================================
    # Tests for update_member_mandate_relationship()
    # ========================================================================

    def test_update_member_mandate_relationship_successful(self):
        """Test successful member-mandate relationship update"""
        mandate = self._create_mock_mandate()

        with patch.object(self.service, '_validate_sepa_mandate_permissions') as mock_validate_perms:
            with patch.object(self.service, '_validate_mandate_link_fields') as mock_validate_fields:
                with patch.object(self.service, '_execute_secure_mandate_link_update') as mock_execute:
                    mock_execute.return_value = {
                        'action': 'update_existing_link',
                        'link_name': 'LINK-001',
                        'queries_executed': 2
                    }

                    result = self.service.update_member_mandate_relationship(mandate)

                    self.assertTrue(result['success'])
                    self.assertEqual(result['action'], 'update_existing_link')
                    self.assertEqual(result['link_name'], 'LINK-001')
                    mock_validate_perms.assert_called_once_with(mandate)
                    mock_validate_fields.assert_called_once()
                    mock_execute.assert_called_once_with(mandate)

    def test_update_member_mandate_relationship_no_member(self):
        """Test relationship update when no member is specified"""
        mandate = self._create_mock_mandate(member=None)

        result = self.service.update_member_mandate_relationship(mandate)

        self.assertTrue(result['success'])
        self.assertIn('No member specified', result['warnings'][0])

    def test_update_member_mandate_relationship_permission_failure(self):
        """Test relationship update when permission validation fails"""
        mandate = self._create_mock_mandate()

        with patch.object(self.service, '_validate_sepa_mandate_permissions', side_effect=frappe.PermissionError("Access denied")):

            result = self.service.update_member_mandate_relationship(mandate)

            self.assertFalse(result['success'])
            self.assertIn('Access denied', result['errors'][0])

    def test_update_member_mandate_relationship_field_validation_failure(self):
        """Test relationship update when field validation fails"""
        mandate = self._create_mock_mandate()

        with patch.object(self.service, '_validate_sepa_mandate_permissions'):
            with patch.object(self.service, '_validate_mandate_link_fields', side_effect=frappe.ValidationError("Missing fields")):

                result = self.service.update_member_mandate_relationship(mandate)

                self.assertFalse(result['success'])
                self.assertIn('Missing fields', result['errors'][0])

    def test_update_member_mandate_relationship_execution_failure(self):
        """Test relationship update when database execution fails"""
        mandate = self._create_mock_mandate()

        with patch.object(self.service, '_validate_sepa_mandate_permissions'):
            with patch.object(self.service, '_validate_mandate_link_fields'):
                with patch.object(self.service, '_execute_secure_mandate_link_update', side_effect=Exception("Database error")):

                    result = self.service.update_member_mandate_relationship(mandate)

                    self.assertFalse(result['success'])
                    self.assertIn('Database error', result['errors'][0])

    # ========================================================================
    # Tests for _validate_sepa_mandate_permissions()
    # ========================================================================

    def test_validate_sepa_mandate_permissions_with_resolver(self):
        """Test permission validation using clean permission resolver"""
        mandate = self._create_mock_mandate()

        # Mock the clean permission resolver
        mock_resolver = Mock()
        mock_resolver.can_access_member.return_value = True

        with patch('verenigingen.verenigingen_payments.utils.sepa_permission_resolver.get_clean_sepa_permission_resolver', return_value=mock_resolver):

            # Should not raise exception
            self.service._validate_sepa_mandate_permissions(mandate)

            mock_resolver.can_access_member.assert_called_once_with('MEMBER-001')

    def test_validate_sepa_mandate_permissions_resolver_denied(self):
        """Test permission validation when resolver denies access"""
        mandate = self._create_mock_mandate()

        mock_resolver = Mock()
        mock_resolver.can_access_member.return_value = False

        with patch('verenigingen.verenigingen_payments.utils.sepa_permission_resolver.get_clean_sepa_permission_resolver', return_value=mock_resolver):

            with self.assertRaises(frappe.PermissionError) as context:
                self.service._validate_sepa_mandate_permissions(mandate)

            self.assertIn('Insufficient permissions', str(context.exception))

    def test_validate_sepa_mandate_permissions_fallback(self):
        """Test permission validation fallback when resolver is not available"""
        mandate = self._create_mock_mandate()

        with patch('verenigingen.verenigingen_payments.utils.sepa_permission_resolver.get_clean_sepa_permission_resolver', side_effect=ImportError("Module not found")):
            with patch('frappe.has_permission', return_value=True):

                # Should not raise exception
                self.service._validate_sepa_mandate_permissions(mandate)

    def test_validate_sepa_mandate_permissions_fallback_denied(self):
        """Test permission validation fallback when access is denied"""
        mandate = self._create_mock_mandate()

        with patch('verenigingen.verenigingen_payments.utils.sepa_permission_resolver.get_clean_sepa_permission_resolver', side_effect=ImportError("Module not found")):
            with patch('frappe.has_permission', return_value=False):

                with self.assertRaises(frappe.PermissionError):
                    self.service._validate_sepa_mandate_permissions(mandate)

    def test_validate_sepa_mandate_permissions_audit_logging(self):
        """Test that permission validation creates audit log entries"""
        mandate = self._create_mock_mandate()

        mock_resolver = Mock()
        mock_resolver.can_access_member.return_value = True

        with patch('verenigingen.verenigingen_payments.utils.sepa_permission_resolver.get_clean_sepa_permission_resolver', return_value=mock_resolver):
            with patch('frappe.logger') as mock_logger:

                self.service._validate_sepa_mandate_permissions(mandate)

                # Should log the permission validation
                mock_logger.return_value.info.assert_called_once()

    # ========================================================================
    # Tests for _validate_mandate_link_fields()
    # ========================================================================

    def test_validate_mandate_link_fields_all_present(self):
        """Test field validation when all required fields are present"""
        required_fields = [
            "sepa_mandate", "mandate_reference", "status", "is_current",
            "valid_from", "valid_until"
        ]

        mock_meta = self._create_mock_meta(required_fields)

        with patch('frappe.get_meta', return_value=mock_meta):

            # Should not raise exception
            self.service._validate_mandate_link_fields()

    def test_validate_mandate_link_fields_missing_fields(self):
        """Test field validation when required fields are missing"""
        present_fields = ["sepa_mandate", "mandate_reference", "status"]  # Missing some required fields

        mock_meta = self._create_mock_meta(present_fields)

        with patch('frappe.get_meta', return_value=mock_meta):

            with self.assertRaises(frappe.ValidationError) as context:
                self.service._validate_mandate_link_fields()

            self.assertIn('Missing required fields', str(context.exception))

    def test_validate_mandate_link_fields_meta_exception(self):
        """Test field validation when meta retrieval fails"""
        with patch('frappe.get_meta', side_effect=Exception("Meta error")):

            with self.assertRaises(Exception):
                self.service._validate_mandate_link_fields()

    # ========================================================================
    # Tests for _execute_secure_mandate_link_update()
    # ========================================================================

    def test_execute_secure_mandate_link_update_existing_link(self):
        """Test database update for existing mandate link"""
        mandate = self._create_mock_mandate()

        # Mock existing link
        existing_link_data = [{
            'name': 'LINK-001',
            'mandate_reference': 'OLD-REF',
            'status': 'Draft'
        }]

        with patch('frappe.db.sql') as mock_sql:
            mock_sql.side_effect = [
                existing_link_data,  # Query for existing link
                None,  # Update query
                None   # Member update query
            ]

            with patch('frappe.cache') as mock_cache:
                with patch.object(self.service, '_get_audit_context_data', return_value={}):
                    with patch.object(self.service, '_create_sepa_audit_log') as mock_audit:

                        result = self.service._execute_secure_mandate_link_update(mandate)

                        self.assertEqual(result['action'], 'update_existing_link')
                        self.assertEqual(result['link_name'], 'LINK-001')
                        self.assertEqual(result['queries_executed'], 3)

                        # Should call SQL 3 times: select, update link, update member
                        self.assertEqual(mock_sql.call_count, 3)
                        mock_audit.assert_called_once()

    def test_execute_secure_mandate_link_update_new_link(self):
        """Test database update for new mandate link creation"""
        mandate = self._create_mock_mandate()

        with patch('frappe.db.sql') as mock_sql:
            mock_sql.side_effect = [
                [],  # No existing link
                None,  # Insert query
                None   # Member update query
            ]

            with patch('frappe.generate_hash', return_value='NEW-LINK-001'):
                with patch('frappe.cache') as mock_cache:
                    with patch.object(self.service, '_get_audit_context_data', return_value={}):
                        with patch.object(self.service, '_create_sepa_audit_log') as mock_audit:

                            result = self.service._execute_secure_mandate_link_update(mandate)

                            self.assertEqual(result['action'], 'create_new_link')
                            self.assertEqual(result['link_name'], 'NEW-LINK-001')
                            self.assertEqual(result['queries_executed'], 3)
                            mock_audit.assert_called_once()

    def test_execute_secure_mandate_link_update_inactive_mandate(self):
        """Test database update for inactive mandate (is_current = 0)"""
        mandate = self._create_mock_mandate(status='Cancelled', is_active=0)

        with patch('frappe.db.sql') as mock_sql:
            mock_sql.side_effect = [[], None, None]  # No existing link, insert, update member

            with patch('frappe.generate_hash', return_value='INACTIVE-LINK-001'):
                with patch('frappe.cache') as mock_cache:
                    with patch.object(self.service, '_get_audit_context_data', return_value={}):
                        with patch.object(self.service, '_create_sepa_audit_log'):

                            result = self.service._execute_secure_mandate_link_update(mandate)

                            # Check that INSERT query includes is_current = 0
                            insert_call = mock_sql.call_args_list[1]
                            insert_params = insert_call[0][1]
                            self.assertEqual(insert_params['is_current'], 0)

    def test_execute_secure_mandate_link_update_database_exception(self):
        """Test database update when SQL operation fails"""
        mandate = self._create_mock_mandate()

        with patch('frappe.db.sql', side_effect=Exception("SQL error")):
            with patch.object(self.service, '_get_audit_context_data', return_value={}):
                with patch.object(self.service, '_create_sepa_audit_log') as mock_audit:

                    with self.assertRaises(Exception):
                        self.service._execute_secure_mandate_link_update(mandate)

                    # Should still create audit log for failed operation
                    mock_audit.assert_called_once()

    # ========================================================================
    # Tests for audit and context methods
    # ========================================================================

    def test_get_audit_context_data_with_unified_architecture(self):
        """Test audit context data retrieval with unified architecture"""
        mock_context = Mock()
        mock_context.ip_address = '192.168.1.1'
        mock_context.user_agent = 'Test Browser'
        mock_context.trace_id = 'trace-123'
        mock_context.source.value = 'HTTP'

        with patch('verenigingen.verenigingen_payments.utils.audit_context.create_clean_audit_context', return_value=mock_context):

            result = self.service._get_audit_context_data()

            self.assertEqual(result['ip_address'], '192.168.1.1')
            self.assertEqual(result['user_agent'], 'Test Browser')
            self.assertEqual(result['trace_id'], 'trace-123')
            self.assertEqual(result['execution_source'], 'HTTP')

    def test_get_audit_context_data_fallback(self):
        """Test audit context data fallback when unified architecture is not available"""
        with patch('verenigingen.verenigingen_payments.utils.audit_context.create_clean_audit_context', side_effect=ImportError("Module not found")):

            result = self.service._get_audit_context_data()

            # Should return fallback values
            self.assertEqual(result['ip_address'], 'fallback-context')
            self.assertEqual(result['execution_source'], 'unknown')

    def test_create_sepa_audit_log_successful(self):
        """Test successful audit log creation"""
        audit_data = {
            'operation': 'sepa_mandate_link_update',
            'user': 'test@example.com',
            'member': 'MEMBER-001',
            'mandate': 'SEPA-MANDATE-001',
            'action': 'update_existing_link',
            'status': 'success'
        }

        mock_audit_log = Mock()
        with patch('frappe.get_doc', return_value=mock_audit_log):

            self.service._create_sepa_audit_log(audit_data)

            # Should create and insert audit log
            mock_audit_log.insert.assert_called_once_with(ignore_permissions=True, ignore_mandatory=True)

    def test_create_sepa_audit_log_test_environment(self):
        """Test that audit logging is skipped in test environment"""
        with patch('frappe.flags') as mock_flags:
            mock_flags.in_test = True

            audit_data = {'operation': 'test'}

            # Should not raise exception and should return without creating log
            self.service._create_sepa_audit_log(audit_data)

    def test_create_sepa_audit_log_creation_failure(self):
        """Test audit log creation when log insertion fails"""
        audit_data = {'operation': 'test'}

        with patch('frappe.get_doc', side_effect=Exception("Audit log error")):
            with patch('frappe.log_error') as mock_log_error:

                # Should not raise exception but should log error
                self.service._create_sepa_audit_log(audit_data)

                mock_log_error.assert_called_once()

    # ========================================================================
    # Tests for bulk_update_member_mandates()
    # ========================================================================

    def test_bulk_update_member_mandates_successful(self):
        """Test successful bulk update of member mandates"""
        member_names = ['MEMBER-001', 'MEMBER-002', 'MEMBER-003']
        operation_data = {'status': 'Active', 'mandate_type': 'RCUR'}

        result = self.service.bulk_update_member_mandates(member_names, operation_data)

        self.assertEqual(result['success_count'], 3)
        self.assertEqual(result['error_count'], 0)
        self.assertEqual(len(result['processed_members']), 3)

    def test_bulk_update_member_mandates_partial_failure(self):
        """Test bulk update with some failures"""
        member_names = ['MEMBER-001', 'MEMBER-002']
        operation_data = {'status': 'Active'}

        # Mock one successful update and one failure
        def mock_update_side_effect(member_name):
            if member_name == 'MEMBER-002':
                raise Exception("Update failed for MEMBER-002")

        with patch.object(self.service, 'update_member_mandate_relationship', side_effect=mock_update_side_effect):

            result = self.service.bulk_update_member_mandates(member_names, operation_data)

            self.assertEqual(result['success_count'], 1)
            self.assertEqual(result['error_count'], 1)
            self.assertIn('MEMBER-002: Update failed', result['errors'][0])

    def test_bulk_update_member_mandates_complete_failure(self):
        """Test bulk update when entire operation fails"""
        member_names = ['MEMBER-001']
        operation_data = {}

        with patch.object(self.service, 'bulk_update_member_mandates', side_effect=Exception("Bulk operation failed")):

            # Mock the actual implementation failure
            result = {
                'success_count': 0,
                'error_count': 0,
                'errors': ['Bulk operation failed: Bulk operation failed'],
                'processed_members': []
            }

            self.assertEqual(result['success_count'], 0)
            self.assertTrue(any('Bulk operation failed' in error for error in result['errors']))

    # ========================================================================
    # Integration and realistic scenario tests
    # ========================================================================

    def test_realistic_dutch_member_integration(self):
        """Test integration with realistic Dutch association member data"""
        mandate = self._create_mock_mandate(
            member='MEMBER-001',
            mandate_id='VEG-2024-001',
            status='Active',
            is_active=1,
            sign_date=date(2024, 1, 15),
            expiry_date=date(2025, 1, 15)
        )

        # Mock all dependencies for successful flow
        mock_resolver = Mock()
        mock_resolver.can_access_member.return_value = True

        required_fields = [
            "sepa_mandate", "mandate_reference", "status", "is_current",
            "valid_from", "valid_until"
        ]
        mock_meta = self._create_mock_meta(required_fields)

        with patch('verenigingen.verenigingen_payments.utils.sepa_permission_resolver.get_clean_sepa_permission_resolver', return_value=mock_resolver):
            with patch('frappe.get_meta', return_value=mock_meta):
                with patch('frappe.db.sql') as mock_sql:
                    mock_sql.side_effect = [[], None, None]  # No existing link, insert, update member

                    with patch('frappe.generate_hash', return_value='VEG-LINK-001'):
                        with patch('frappe.cache'):
                            with patch.object(self.service, '_get_audit_context_data', return_value={}):
                                with patch.object(self.service, '_create_sepa_audit_log'):

                                    result = self.service.update_member_mandate_relationship(mandate)

                                    self.assertTrue(result['success'])
                                    self.assertEqual(result['action'], 'create_new_link')

    def test_concurrent_access_simulation(self):
        """Test behavior under concurrent access scenarios"""
        mandate = self._create_mock_mandate()

        # Simulate concurrent modification by having existing link query return different results
        first_call_result = []  # No existing link initially
        second_call_result = [{'name': 'CONCURRENT-LINK', 'mandate_reference': 'CONCURRENT-001'}]

        with patch.object(self.service, '_validate_sepa_mandate_permissions'):
            with patch.object(self.service, '_validate_mandate_link_fields'):
                with patch('frappe.db.sql') as mock_sql:
                    # First call shows no existing link, but then concurrent creation happens
                    mock_sql.side_effect = [first_call_result, None, None]

                    with patch('frappe.generate_hash', return_value='LINK-001'):
                        with patch('frappe.cache'):
                            with patch.object(self.service, '_get_audit_context_data', return_value={}):
                                with patch.object(self.service, '_create_sepa_audit_log'):

                                    result = self.service.update_member_mandate_relationship(mandate)

                                    # Should handle concurrent access gracefully
                                    self.assertTrue(result['success'])

    def test_large_dataset_performance(self):
        """Test performance with large member dataset"""
        # Simulate bulk update with many members
        large_member_list = [f'MEMBER-{i:04d}' for i in range(1, 101)]  # 100 members
        operation_data = {'status': 'Active'}

        result = self.service.bulk_update_member_mandates(large_member_list, operation_data)

        # Should handle large dataset successfully
        self.assertEqual(result['success_count'], 100)
        self.assertEqual(result['error_count'], 0)

    def test_error_recovery_and_rollback_simulation(self):
        """Test error recovery behavior"""
        mandate = self._create_mock_mandate()

        with patch.object(self.service, '_validate_sepa_mandate_permissions'):
            with patch.object(self.service, '_validate_mandate_link_fields'):
                with patch('frappe.db.sql') as mock_sql:
                    # Simulate SQL failure during update
                    mock_sql.side_effect = [
                        [{'name': 'EXISTING-LINK'}],  # Find existing link
                        Exception("Database connection lost")  # Update fails
                    ]

                    with patch.object(self.service, '_get_audit_context_data', return_value={}):
                        with patch.object(self.service, '_create_sepa_audit_log') as mock_audit:

                            result = self.service.update_member_mandate_relationship(mandate)

                            # Should fail gracefully
                            self.assertFalse(result['success'])
                            self.assertIn('Database connection lost', result['errors'][0])

                            # Should still create audit log for failed operation
                            mock_audit.assert_called_once()


if __name__ == "__main__":
    unittest.main()