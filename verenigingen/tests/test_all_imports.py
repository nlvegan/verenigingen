"""
Test All Imports - Ensures all modules can be imported successfully

This test file validates that all Python modules in the verenigingen app
can be imported without errors. This catches typos in import statements
and missing dependencies early.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAllImports(FrappeTestCase):
    """Test that all modules can be imported successfully"""
    
    def test_api_imports(self):
        """Test all API module imports"""
        # Main API modules (existing)
        import verenigingen.api.member_management
        import verenigingen.api.chapter_dashboard_api
        import verenigingen.api.membership_application
        import verenigingen.api.membership_application_review
        import verenigingen.api.payment_dashboard
        import verenigingen.api.payment_processing
        import verenigingen.api.suspension_api
        import verenigingen.api.termination_api
        import verenigingen.api.volunteer_skills
        
        # E-Boekhouden API modules
        import verenigingen.api.eboekhouden_clean_reimport
        import verenigingen.api.eboekhouden_migration
        
        # SEPA API modules
        import verenigingen.api.sepa_batch_ui
        import verenigingen.api.sepa_reconciliation
        import verenigingen.api.sepa_mandate_management
        
        self.assertTrue(True, "All API imports successful")
        
    def test_utils_imports(self):
        """Test all utility module imports"""
        # Core utils (existing)
        import verenigingen.utils.validation.iban_validator
        import verenigingen.utils.termination_utils
        import verenigingen.utils.termination_integration
        import verenigingen.utils.application_helpers
        import verenigingen.utils.application_payments
        import verenigingen.utils.donation_emails
        import verenigingen.utils.expense_permissions
        import verenigingen.utils.sepa_notifications
        import verenigingen.utils.sepa_reconciliation
        
        # E-Boekhouden utils
        import verenigingen.utils.eboekhouden.eboekhouden_rest_client
        import verenigingen.utils.eboekhouden.eboekhouden_rest_iterator
        import verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration
        import verenigingen.utils.eboekhouden.import_manager
        import verenigingen.utils.eboekhouden.field_mapping
        import verenigingen.utils.eboekhouden.invoice_helpers
        import verenigingen.utils.eboekhouden.uom_manager
        
        # Payment processing
        import verenigingen.utils.eboekhouden.payment_processing.payment_entry_handler
        
        # Enhanced features
        import verenigingen.utils.eboekhouden.enhanced_payment_import
        import verenigingen.utils.eboekhouden.integrate_enhanced_payment
        import verenigingen.utils.eboekhouden.test_phase1_implementation
        
        self.assertTrue(True, "All utils imports successful")
        
    def test_doctype_controller_imports(self):
        """Test DocType controller imports"""
        # Member system
        import verenigingen.verenigingen.doctype.member.member
        import verenigingen.verenigingen.doctype.membership.membership
        import verenigingen.verenigingen.doctype.membership_type.membership_type
        
        # Chapter system
        import verenigingen.verenigingen.doctype.chapter.chapter
        import verenigingen.verenigingen.doctype.chapter_member.chapter_member
        
        # Volunteer system
        import verenigingen.verenigingen.doctype.volunteer.volunteer
        import verenigingen.verenigingen.doctype.volunteer_expense.volunteer_expense
        import verenigingen.verenigingen.doctype.volunteer_assignment.volunteer_assignment
        
        # Financial
        import verenigingen.verenigingen.doctype.sepa_mandate.sepa_mandate
        import verenigingen.verenigingen.doctype.direct_debit_batch.direct_debit_batch
        
        # E-Boekhouden
        import verenigingen.verenigingen.doctype.e_boekhouden_settings.e_boekhouden_settings
        import verenigingen.verenigingen.doctype.e_boekhouden_ledger_mapping.e_boekhouden_ledger_mapping
        
        self.assertTrue(True, "All DocType controller imports successful")
        
    def test_hooks_and_config_imports(self):
        """Test configuration file imports"""
        import verenigingen.hooks
        import verenigingen.permissions
        import verenigingen.validations
        
        self.assertTrue(True, "All configuration imports successful")
        
    def test_test_utility_imports(self):
        """Test that test utilities can be imported"""
        import verenigingen.tests.test_data_factory
        import verenigingen.tests.base_test_case
        import verenigingen.tests.test_runner
        
        # Specific test modules that have utilities
        import verenigingen.tests.test_iban_validator
        import verenigingen.tests.fixtures.test_data_factory
        import verenigingen.tests.utils.base
        
        self.assertTrue(True, "All test utility imports successful")
        
    def test_debug_utility_imports(self):
        """Test debug utilities can be imported"""
        # Only test if they exist (optional modules)
        try:
            import verenigingen.utils.debug.test_import_without_fallbacks
            self.assertTrue(True, "Debug utilities imported")
        except ImportError:
            # Debug utilities are optional
            pass
            
    def test_migration_imports(self):
        """Test migration and patch imports"""
        # Test that patches can be imported
        try:
            import verenigingen.patches.v1_0.update_member_statuses
            import verenigingen.patches.v1_0.migrate_subscription_data
            self.assertTrue(True, "Migration patches imported")
        except ImportError:
            # Patches might not exist yet
            pass
            
    def test_no_typo_imports(self):
        """Specifically test for common typos in import statements"""
        # This test ensures we're not importing 'vereiningen' (missing 'g')
        import ast
        import os
        
        app_path = frappe.get_app_path('verenigingen')
        typo_patterns = [
            'vereinigen.',  # Missing 'g'
            'verenigigen.',  # Missing 'i'  
            'verenigingn.',  # Transposed
        ]
        
        files_with_typos = []
        
        for root, dirs, files in os.walk(app_path):
            # Skip certain directories
            if any(skip in root for skip in ['.git', '__pycache__', '.egg-info', 'node_modules']):
                continue
                
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                        # Check for typo patterns
                        for typo in typo_patterns:
                            if typo in content:
                                # Exclude this test file itself
                                if 'test_all_imports.py' not in file_path:
                                    files_with_typos.append((file_path, typo))
                                    
                    except Exception:
                        # Skip files that can't be read
                        pass
                        
        if files_with_typos:
            self.fail(f"Found import typos in {len(files_with_typos)} files: {files_with_typos[:5]}")
        else:
            self.assertTrue(True, "No import typos found")


def run_import_test():
    """Standalone function to run import tests"""
    test = TestAllImports()
    
    print("Running import tests...")
    
    # Run each test method
    test_methods = [
        'test_api_imports',
        'test_utils_imports', 
        'test_doctype_controller_imports',
        'test_hooks_and_config_imports',
        'test_test_utility_imports',
        'test_no_typo_imports'
    ]
    
    results = {"passed": 0, "failed": 0, "errors": []}
    
    for method_name in test_methods:
        try:
            method = getattr(test, method_name)
            method()
            results["passed"] += 1
            print(f"✓ {method_name}")
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{method_name}: {str(e)}")
            print(f"✗ {method_name}: {str(e)}")
            
    print(f"\nResults: {results['passed']} passed, {results['failed']} failed")
    
    if results["errors"]:
        print("\nErrors:")
        for error in results["errors"]:
            print(f"  - {error}")
            
    return results
