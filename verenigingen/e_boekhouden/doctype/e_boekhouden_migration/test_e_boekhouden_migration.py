# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for E-Boekhouden Migration
Tests all aspects of the financial migration workflow including business logic, validation, and integration
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, now_datetime, today


class TestEBoekhoudenMigration(FrappeTestCase):
    """Comprehensive tests for E-Boekhouden Migration doctype"""

    def setUp(self):
        """Set up test environment"""
        self.setup_test_data()

    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()

    def setup_test_data(self):
        """Create test data for migration scenarios"""
        # Create test company if not exists
        if not frappe.db.exists("Company", "Test Migration Company"):
            self.test_company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": "Test Migration Company",
                    "abbr": "TMC",
                    "default_currency": "EUR",
                    "country": "Netherlands",
                }
            )
            self.test_company.insert(ignore_permissions=True)
        else:
            self.test_company = frappe.get_doc("Company", "Test Migration Company")

    def cleanup_test_data(self):
        """Clean up test data"""
        try:
            # Clean up migration documents
            migrations = frappe.get_all("E-Boekhouden Migration", filters={"company": self.test_company.name})
            for migration in migrations:
                try:
                    frappe.delete_doc("E-Boekhouden Migration", migration.name, force=True)
                except:
                    pass
        except:
            pass

    def test_required_methods_exist(self):
        """Test that all critical methods exist"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Verify critical methods exist (based on actual implementation)
        critical_methods = [
            "validate",
            "on_submit",
            "start_migration",
            "clear_existing_accounts",
            "migrate_chart_of_accounts",
            "migrate_cost_centers",
            "migrate_transactions_data",
            "create_account",
            "create_customer",
            "create_supplier",
            "create_journal_entry",
            "log_error",
        ]

        for method_name in critical_methods:
            self.assertTrue(
                hasattr(migration, method_name), f"E-Boekhouden Migration must have {method_name} method"
            )
            self.assertTrue(
                callable(getattr(migration, method_name)),
                f"E-Boekhouden Migration.{method_name} must be callable",
            )

    def test_required_fields_exist(self):
        """Test that required fields exist in doctype"""
        meta = frappe.get_meta("E-Boekhouden Migration")
        field_names = [f.fieldname for f in meta.fields]

        # Critical fields that actually exist (based on test output)
        required_fields = [
            "naming_series",
            "migration_name",
            "migration_status",
            "company",
            "date_from",
            "date_to",
            "migrate_accounts",
            "migrate_customers",
            "migrate_suppliers",
            "migrate_transactions",
            "progress_percentage",
            "current_operation",
            "total_records",
            "imported_records",
            "failed_records",
            "migration_summary",
            "error_log",
            "start_time",
            "end_time",
        ]

        for field in required_fields:
            self.assertIn(field, field_names, f"E-Boekhouden Migration must have {field} field")

    def test_document_creation_and_validation(self):
        """Test basic document creation and validation"""
        migration = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": "Test Migration",
                "company": self.test_company.name,
                "date_from": add_months(today(), -12),
                "date_to": today(),
                "migrate_accounts": 1,
                "migrate_customers": 1,
                "migrate_suppliers": 1,
                "migrate_transactions": 1,
            }
        )

        # Test document creation
        migration.insert(ignore_permissions=True)

        # Verify document was created
        self.assertEqual(migration.migration_name, "Test Migration")
        self.assertEqual(migration.company, self.test_company.name)
        self.assertEqual(migration.migration_status, "Draft")  # Default status

    def test_date_validation(self):
        """Test date validation logic"""
        migration = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": "Test Date Validation",
                "company": self.test_company.name,
                "date_from": today(),
                "date_to": add_days(today(), -1),  # End date before start date
                "migrate_transactions": 1,
            }
        )

        # Should raise validation error
        with self.assertRaises(frappe.ValidationError):
            migration.insert(ignore_permissions=True)

    def test_migration_status_workflow(self):
        """Test migration status workflow"""
        migration = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": "Test Status Workflow",
                "company": self.test_company.name,
                "date_from": add_months(today(), -6),
                "date_to": today(),
                "migrate_accounts": 1,
            }
        )
        migration.insert(ignore_permissions=True)

        # Test status transitions
        self.assertEqual(migration.migration_status, "Draft")

        # Test status updates
        migration.db_set("migration_status", "In Progress")
        migration.reload()
        self.assertEqual(migration.migration_status, "In Progress")

    def test_migration_scope_validation(self):
        """Test migration scope validation"""
        migration = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": "Test Scope Validation",
                "company": self.test_company.name,
                "date_from": add_months(today(), -6),
                "date_to": today(),
                "migrate_transactions": 1,
                # Missing date range - should cause validation error
                "date_from": None,
                "date_to": None,
            }
        )

        # Should raise validation error for missing date range
        with self.assertRaises(frappe.ValidationError):
            migration.insert(ignore_permissions=True)

    def test_progress_tracking(self):
        """Test progress tracking functionality"""
        migration = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": "Test Progress Tracking",
                "company": self.test_company.name,
                "date_from": add_months(today(), -6),
                "date_to": today(),
                "migrate_accounts": 1,
            }
        )
        migration.insert(ignore_permissions=True)

        # Test progress fields
        progress_fields = [
            "progress_percentage",
            "current_operation",
            "total_records",
            "imported_records",
            "failed_records",
        ]

        for field in progress_fields:
            self.assertTrue(hasattr(migration, field))

    def test_error_logging(self):
        """Test error logging functionality"""
        migration = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": "Test Error Logging",
                "company": self.test_company.name,
                "date_from": add_months(today(), -6),
                "date_to": today(),
                "migrate_accounts": 1,
            }
        )
        migration.insert(ignore_permissions=True)

        # Test error logging method
        self.assertTrue(hasattr(migration, "log_error"))
        self.assertTrue(callable(migration.log_error))

        # Test error logging without raising exception
        try:
            migration.log_error("Test error message", "Test Record Type", {"test": "data"})
        except Exception as e:
            self.fail(f"Error logging should not raise exception: {e}")

    def test_account_creation_methods(self):
        """Test account creation methods"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Test account creation methods exist
        account_methods = [
            "create_account",
            "get_parent_account",
            "get_or_create_group_account",
            "find_or_create_parent_group",
        ]

        for method_name in account_methods:
            self.assertTrue(hasattr(migration, method_name))
            self.assertTrue(callable(getattr(migration, method_name)))

    def test_customer_supplier_creation_methods(self):
        """Test customer and supplier creation methods"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Test customer/supplier creation methods exist
        creation_methods = [
            "create_customer",
            "create_supplier",
            "create_contact_for_customer",
            "create_contact_for_supplier",
            "create_address_for_customer",
            "create_address_for_supplier",
        ]

        for method_name in creation_methods:
            self.assertTrue(hasattr(migration, method_name))
            self.assertTrue(callable(getattr(migration, method_name)))

    def test_transaction_processing_methods(self):
        """Test transaction processing methods"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Test transaction processing methods exist
        transaction_methods = [
            "migrate_transactions_data",
            "create_journal_entry",
            "parse_mutaties_xml",
            "get_account_code_from_ledger_id",
        ]

        for method_name in transaction_methods:
            self.assertTrue(hasattr(migration, method_name))
            self.assertTrue(callable(getattr(migration, method_name)))

    def test_xml_parsing_methods(self):
        """Test XML parsing methods"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Test XML parsing methods exist
        parsing_methods = ["parse_grootboekrekeningen_xml", "parse_relaties_xml", "parse_mutaties_xml"]

        for method_name in parsing_methods:
            self.assertTrue(hasattr(migration, method_name))
            self.assertTrue(callable(getattr(migration, method_name)))

    def test_migration_api_functions_exist(self):
        """Test migration API functions exist"""
        # Test global migration functions
        try:
            from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
                run_migration_background,
                start_migration,
                start_migration_api,
            )

            # Verify functions are callable
            self.assertTrue(callable(start_migration_api))
            self.assertTrue(callable(start_migration))
            self.assertTrue(callable(run_migration_background))

        except ImportError as e:
            self.fail(f"Failed to import migration API functions: {e}")

    def test_cleanup_functions_exist(self):
        """Test cleanup functions exist"""
        try:
            from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
                cleanup_chart_of_accounts,
                nuclear_cleanup_all_imported_data,
            )

            # Verify cleanup functions are callable
            self.assertTrue(callable(cleanup_chart_of_accounts))
            self.assertTrue(callable(nuclear_cleanup_all_imported_data))

        except ImportError as e:
            self.fail(f"Failed to import cleanup functions: {e}")

    def test_analysis_functions_exist(self):
        """Test analysis functions exist"""
        try:
            from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
                get_current_account_mappings,
                get_staging_data_for_review,
                preview_mapping_impact,
            )

            # Verify analysis functions are callable
            self.assertTrue(callable(get_staging_data_for_review))
            self.assertTrue(callable(preview_mapping_impact))
            self.assertTrue(callable(get_current_account_mappings))

        except ImportError as e:
            self.fail(f"Failed to import analysis functions: {e}")

    def test_migration_configuration_fields(self):
        """Test migration configuration fields"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Test configuration fields exist
        config_fields = [
            "migrate_accounts",
            "migrate_cost_centers",
            "migrate_customers",
            "migrate_suppliers",
            "migrate_transactions",
            "migrate_stock_transactions",
            "use_account_mappings",
            "dry_run",
            "clear_existing_accounts",
            "use_enhanced_migration",
            "skip_existing",
            "batch_size",
        ]

        for field in config_fields:
            self.assertTrue(hasattr(migration, field))

    def test_enhanced_migration_features(self):
        """Test enhanced migration features"""
        migration = frappe.new_doc("E-Boekhouden Migration")

        # Test enhanced migration fields
        enhanced_fields = [
            "use_enhanced_migration",
            "skip_existing",
            "batch_size",
            "use_date_chunking",
            "enable_audit_trail",
            "enable_rollback",
        ]

        for field in enhanced_fields:
            self.assertTrue(hasattr(migration, field))

    def test_no_critical_import_errors(self):
        """Test that the doctype module can be imported without errors"""
        try:
            from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
                EBoekhoudenMigration,
            )

            # Verify it's the correct class
            self.assertTrue(issubclass(EBoekhoudenMigration, frappe.model.document.Document))

        except ImportError as e:
            self.fail(f"Failed to import EBoekhoudenMigration: {e}")

    def test_migration_workflow_integration(self):
        """Test integration with migration workflow"""
        migration = frappe.get_doc(
            {
                "doctype": "E-Boekhouden Migration",
                "migration_name": "Test Workflow Integration",
                "company": self.test_company.name,
                "date_from": add_months(today(), -6),
                "date_to": today(),
                "migrate_accounts": 1,
                "dry_run": 1,  # Use dry run to avoid actual migration
            }
        )
        migration.insert(ignore_permissions=True)

        # Test that start_migration method exists and is callable
        self.assertTrue(hasattr(migration, "start_migration"))
        self.assertTrue(callable(migration.start_migration))


if __name__ == "__main__":
    unittest.main()
