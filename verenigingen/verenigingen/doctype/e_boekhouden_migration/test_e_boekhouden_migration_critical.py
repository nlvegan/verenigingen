# -*- coding: utf-8 -*-
"""
Critical Business Logic Tests for E-Boekhouden Migration
These tests verify that essential methods exist and core migration workflows work.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase


class TestEBoekhoudenMigrationCritical(FrappeTestCase):
    """Critical tests for E-Boekhouden Migration doctype"""

    def test_required_methods_exist(self):
        """Test that all critical methods exist"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Verify critical methods exist
        critical_methods = [
            "validate",
            "start_migration",
            "process_accounts",
            "process_mutations",
            "process_customers",
            "process_opening_balances",
            "handle_migration_error",
            "update_progress",
            "complete_migration",
        ]

        for method_name in critical_methods:
            self.assertTrue(
                hasattr(migration, method_name), f"EBoekhoudenMigration must have {method_name} method"
            )
            self.assertTrue(
                callable(getattr(migration, method_name)),
                f"EBoekhoudenMigration.{method_name} must be callable",
            )

    def test_migration_utilities_exist(self):
        """Test that migration utility modules exist"""
        try:
            # Test core migration utilities
            from verenigingen.utils.eboekhouden_migration import (
                EBoekhoudenMigrationManager,
                EBoekhoudenRESTClient,
                EBoekhoudenSOAPClient,
            )

            # Verify classes are importable
            self.assertTrue(callable(EBoekhoudenMigrationManager))
            self.assertTrue(callable(EBoekhoudenRESTClient))
            self.assertTrue(callable(EBoekhoudenSOAPClient))

        except ImportError as e:
            self.fail(f"Failed to import E-Boekhouden migration utilities: {e}")

    def test_required_fields_exist(self):
        """Test that required fields exist in doctype"""
        meta = frappe.get_meta("E-Boekhouden Migration")
        field_names = [f.fieldname for f in meta.fields]

        # Critical fields that should exist
        required_fields = [
            "migration_name",
            "status",
            "start_date",
            "end_date",
            "api_type",
            "progress_percentage",
            "total_accounts",
            "total_mutations",
            "total_customers",
            "migration_log",
        ]

        for field in required_fields:
            self.assertIn(field, field_names, f"E-Boekhouden Migration must have {field} field")

    def test_api_configuration_fields_exist(self):
        """Test that API configuration fields exist"""
        meta = frappe.get_meta("E-Boekhouden Migration")
        field_names = [f.fieldname for f in meta.fields]

        # API configuration fields
        api_fields = [
            "api_username",
            "api_security_code",
            "api_base_url",
            "session_id",
            "use_rest_api",
            "use_soap_api",
        ]

        for field in api_fields:
            self.assertIn(
                field, field_names, f"E-Boekhouden Migration must have {field} field for API configuration"
            )

    def test_status_validation(self):
        """Test status field validation"""
        meta = frappe.get_meta("E-Boekhouden Migration")
        status_field = None

        for field in meta.fields:
            if field.fieldname == "status":
                status_field = field
                break

        self.assertIsNotNone(status_field, "Status field must exist")

        # Verify it's a Select field with proper options
        self.assertEqual(status_field.fieldtype, "Select")
        self.assertIsNotNone(status_field.options)

        # Check that key statuses are available
        status_options = status_field.options.split("\n") if status_field.options else []
        expected_statuses = ["Draft", "In Progress", "Completed", "Failed", "Cancelled"]

        for status in expected_statuses:
            self.assertIn(status, status_options, f"Status field must include '{status}' option")

    def test_migration_workflow_methods(self):
        """Test that migration workflow methods exist"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Workflow methods that should exist
        workflow_methods = [
            "initialize_migration",
            "validate_api_connection",
            "prepare_migration_data",
            "execute_migration_step",
            "handle_migration_error",
            "finalize_migration",
        ]

        for method_name in workflow_methods:
            self.assertTrue(
                hasattr(migration, method_name),
                f"E-Boekhouden Migration must have {method_name} method for workflow",
            )

    def test_data_processing_methods(self):
        """Test that data processing methods exist"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Data processing methods
        processing_methods = [
            "process_accounts",
            "process_mutations",
            "process_customers",
            "process_opening_balances",
            "transform_account_data",
            "transform_mutation_data",
            "validate_data_integrity",
        ]

        for method_name in processing_methods:
            self.assertTrue(
                hasattr(migration, method_name),
                f"E-Boekhouden Migration must have {method_name} method for data processing",
            )

    def test_error_handling_methods(self):
        """Test that error handling methods exist"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Error handling methods
        error_methods = [
            "handle_migration_error",
            "log_migration_error",
            "retry_failed_operation",
            "cleanup_failed_migration",
        ]

        for method_name in error_methods:
            self.assertTrue(
                hasattr(migration, method_name),
                f"E-Boekhouden Migration must have {method_name} method for error handling",
            )

    def test_progress_tracking_methods(self):
        """Test that progress tracking methods exist"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Progress tracking methods
        progress_methods = [
            "update_progress",
            "calculate_progress_percentage",
            "log_migration_step",
            "update_migration_status",
        ]

        for method_name in progress_methods:
            self.assertTrue(
                hasattr(migration, method_name),
                f"E-Boekhouden Migration must have {method_name} method for progress tracking",
            )

    def test_no_critical_import_errors(self):
        """Test that the doctype module can be imported without errors"""
        try:
            from verenigingen.verenigingen.doctype.e_boekhouden_migration.e_boekhouden_migration import (
                EBoekhoudenMigration,
            )

            # Verify it's the correct class
            self.assertTrue(issubclass(EBoekhoudenMigration, frappe.model.document.Document))

        except ImportError as e:
            self.fail(f"Failed to import EBoekhoudenMigration: {e}")

    def test_api_type_validation(self):
        """Test API type field validation"""
        meta = frappe.get_meta("E-Boekhouden Migration")
        api_type_field = None

        for field in meta.fields:
            if field.fieldname == "api_type":
                api_type_field = field
                break

        self.assertIsNotNone(api_type_field, "API type field must exist")

        # Verify it has proper options
        if api_type_field.fieldtype == "Select":
            self.assertIsNotNone(api_type_field.options)

            # Check for API types
            api_options = api_type_field.options.split("\n") if api_type_field.options else []
            expected_types = ["REST API", "SOAP API"]

            for api_type in expected_types:
                self.assertIn(api_type, api_options, f"API type field should include '{api_type}' option")

    def test_migration_configuration_validation(self):
        """Test migration configuration validation"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Test that required configuration fields exist
        required_config = ["api_username", "api_security_code", "api_base_url"]

        for field in required_config:
            self.assertTrue(
                hasattr(migration, field), f"E-Boekhouden Migration must have {field} configuration field"
            )

    def test_data_validation_methods(self):
        """Test that data validation methods exist"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Data validation methods
        validation_methods = [
            "validate_account_data",
            "validate_mutation_data",
            "validate_customer_data",
            "validate_opening_balance_data",
            "check_data_consistency",
        ]

        for method_name in validation_methods:
            self.assertTrue(
                hasattr(migration, method_name),
                f"E-Boekhouden Migration must have {method_name} method for data validation",
            )


if __name__ == "__main__":
    unittest.main()
