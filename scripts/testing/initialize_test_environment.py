#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Environment Initialization Script
=====================================

Comprehensive test environment setup for the Verenigingen association management system.
This script ensures that all required fixtures, master data, and system configurations
are properly loaded for reliable test execution.

Usage:
    bench --site [site-name] execute scripts.testing.initialize_test_environment.main

Features:
- ✅ Load all essential fixtures in proper dependency order
- ✅ Create required master data (companies, accounts, etc.)
- ✅ Initialize system settings with production defaults
- ✅ Validate test environment completeness
- ✅ Report on initialization status and issues

This addresses Issue #5 (Test Environment Dependencies) by ensuring tests have
the foundational setup they expect.
"""

import os
import json
import frappe
from frappe import _
from datetime import datetime


class TestEnvironmentInitializer:
    """
    Comprehensive test environment initialization with progress tracking
    and error recovery capabilities.
    """
    
    def __init__(self):
        self.results = {
            'fixtures_loaded': 0,
            'fixtures_skipped': 0,
            'fixtures_failed': 0,
            'master_data_created': 0,
            'settings_configured': 0,
            'errors': [],
            'warnings': []
        }
        self.start_time = datetime.now()
    
    def initialize_complete_environment(self):
        """Main initialization orchestrator"""
        print("🔧 Initializing Verenigingen Test Environment...")
        print("=" * 60)
        
        try:
            # Phase 1: System Settings
            print("\n📋 Phase 1: Configuring System Settings...")
            self._configure_system_settings()
            
            # Phase 2: Load Essential Fixtures  
            print("\n📦 Phase 2: Loading Essential Fixtures...")
            self._load_all_fixtures()
            
            # Phase 3: Create Master Data
            print("\n🏗️  Phase 3: Creating Master Data...")
            self._create_master_data()
            
            # Phase 4: Validate Environment
            print("\n✅ Phase 4: Validating Test Environment...")
            self._validate_environment()
            
            # Phase 5: Report Results
            print("\n📊 Phase 5: Initialization Report...")
            self._print_summary()
            
        except Exception as e:
            self.results['errors'].append(f"Critical initialization failure: {str(e)}")
            print(f"\n❌ CRITICAL ERROR: {str(e)}")
            raise
    
    def _configure_system_settings(self):
        """Configure essential system settings for test environment"""
        try:
            # Initialize Verenigingen Settings
            from verenigingen.setup import create_default_verenigingen_settings
            create_default_verenigingen_settings()
            self.results['settings_configured'] += 1
            print("   ✅ Verenigingen Settings initialized")
            
            # Configure email settings for testing
            self._configure_email_settings()
            print("   ✅ Email settings configured for testing")
            
            # Set system manager for test operations
            if not frappe.db.exists("User", "test@example.com"):
                test_admin = frappe.get_doc({
                    "doctype": "User",
                    "email": "test@example.com", 
                    "first_name": "Test",
                    "last_name": "Administrator",
                    "enabled": 1,
                    "user_type": "System User"
                })
                test_admin.flags.ignore_permissions = True
                test_admin.insert()
                print("   ✅ Test administrator user created")
                
        except Exception as e:
            error_msg = f"System settings configuration failed: {str(e)}"
            self.results['errors'].append(error_msg)
            print(f"   ❌ {error_msg}")
    
    def _configure_email_settings(self):
        """Configure email settings optimized for testing"""
        # Disable actual email sending in test environment
        frappe.db.set_single_value("Email Account", "enable_outgoing", 0)
        frappe.db.set_single_value("Email Account", "enable_incoming", 0)
        
        # Set up email queue for testing
        frappe.db.set_single_value("System Settings", "disable_scheduler", 0)
        frappe.db.commit()
    
    def _load_all_fixtures(self):
        """Load all fixtures in proper dependency order"""
        # Define fixture loading order (dependencies first)
        fixture_order = [
            # System and security
            'role.json',
            'custom_field.json',
            'custom_docperm.json',
            
            # Master data  
            'team_role.json',
            'membership_type.json',
            'donation_type.json',
            'item_group.json',
            'item.json',
            
            # Workflow system
            'workflow_state.json', 
            'workflow_action_master.json',
            'workflow.json',
            'periodic_donation_agreement_workflow.json',
            
            # Templates and communication
            'email_template.json',
            'custom_html_block.json',
            
            # Organizational structure
            'team.json',
            'membership_dues_schedule.json',
            
            # Reports and profiles
            'report.json',
            'role_profile.json',
            'module_profile.json'
        ]
        
        fixtures_path = os.path.join(
            frappe.get_app_path("verenigingen"),
            "fixtures"
        )
        
        for fixture_file in fixture_order:
            fixture_path = os.path.join(fixtures_path, fixture_file)
            if os.path.exists(fixture_path):
                self._load_single_fixture(fixture_path, fixture_file)
            else:
                warning = f"Fixture file not found: {fixture_file}"
                self.results['warnings'].append(warning)
                print(f"   ⚠️  {warning}")
    
    def _load_single_fixture(self, file_path, fixture_name):
        """Load a single fixture file with comprehensive error handling"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                fixture_data = json.load(f)
            
            if not isinstance(fixture_data, list):
                self.results['fixtures_failed'] += 1
                print(f"   ❌ Invalid fixture format: {fixture_name}")
                return
            
            loaded = skipped = 0
            
            for record in fixture_data:
                if not isinstance(record, dict) or 'doctype' not in record:
                    continue
                
                try:
                    doctype = record['doctype']
                    name = record.get('name')
                    
                    if name and frappe.db.exists(doctype, name):
                        skipped += 1
                        continue
                    
                    # Create document
                    doc = frappe.get_doc(record)
                    doc.flags.ignore_permissions = True
                    doc.flags.ignore_links = True
                    doc.flags.ignore_validate = False  # Keep business validation
                    doc.insert()
                    loaded += 1
                    
                except Exception as e:
                    # Log individual record errors but continue
                    self.results['warnings'].append(f"Failed to load {doctype} {name}: {str(e)}")
                    continue
            
            self.results['fixtures_loaded'] += loaded
            self.results['fixtures_skipped'] += skipped
            
            if loaded > 0:
                print(f"   ✅ {fixture_name}: {loaded} loaded, {skipped} skipped")
            else:
                print(f"   ➖ {fixture_name}: {skipped} already exist")
                
        except Exception as e:
            error_msg = f"Failed to process {fixture_name}: {str(e)}"
            self.results['fixtures_failed'] += 1
            self.results['errors'].append(error_msg)
            print(f"   ❌ {error_msg}")
    
    def _create_master_data(self):
        """Create essential master data that tests depend on"""
        try:
            # Ensure default company exists
            self._ensure_default_company()
            print("   ✅ Default company configured")
            
            # Ensure fiscal year exists
            self._ensure_fiscal_year()
            print("   ✅ Fiscal year configured")
            
            # Ensure basic chart of accounts
            self._ensure_basic_accounts()
            print("   ✅ Basic accounts configured")
            
            # Ensure cost centers for volunteer expenses
            self._ensure_cost_centers()
            print("   ✅ Cost centers configured")
            
            # Commit all master data changes
            frappe.db.commit()
            
        except Exception as e:
            error_msg = f"Master data creation failed: {str(e)}"
            self.results['errors'].append(error_msg)
            print(f"   ❌ {error_msg}")
    
    def _ensure_default_company(self):
        """Ensure a default company exists for test operations"""
        company_name = "Test Company Netherlands"
        
        if not frappe.db.exists("Company", company_name):
            # Check if any company exists
            existing = frappe.db.get_list("Company", limit=1)
            if existing:
                # Use first existing company
                first_company = existing[0]['name']
                frappe.db.set_value("Company", first_company, "company_name", company_name)
                frappe.db.set_value("Company", first_company, "name", company_name)
                self.results['master_data_created'] += 1
            else:
                # Create new company
                company = frappe.get_doc({
                    "doctype": "Company",
                    "company_name": company_name,
                    "abbr": "TCN",
                    "default_currency": "EUR",
                    "country": "Netherlands"
                })
                company.flags.ignore_permissions = True
                company.insert()
                self.results['master_data_created'] += 1
    
    def _ensure_fiscal_year(self):
        """Ensure current fiscal year exists"""
        from frappe.utils import nowdate, get_year_start, get_year_ending
        
        current_date = nowdate()
        year_start = get_year_start(current_date)
        year_end = get_year_ending(current_date)
        fy_name = f"{year_start[:4]}-{year_end[:4]}"
        
        if not frappe.db.exists("Fiscal Year", fy_name):
            fy = frappe.get_doc({
                "doctype": "Fiscal Year",
                "year": fy_name,
                "year_start_date": year_start,
                "year_end_date": year_end
            })
            fy.flags.ignore_permissions = True
            fy.insert()
            self.results['master_data_created'] += 1
    
    def _ensure_basic_accounts(self):
        """Ensure basic account structure exists"""
        company_name = "Test Company Netherlands"
        
        basic_accounts = [
            {"account_name": "Test Cash", "account_type": "Cash", "is_group": 0},
            {"account_name": "Test Bank", "account_type": "Bank", "is_group": 0},
            {"account_name": "Test Income", "account_type": "Income Account", "is_group": 0},
            {"account_name": "Test Expenses", "account_type": "Expense Account", "is_group": 0}
        ]
        
        for acc_data in basic_accounts:
            account_name = f"{acc_data['account_name']} - TCN"
            if not frappe.db.exists("Account", account_name):
                account = frappe.get_doc({
                    "doctype": "Account",
                    "account_name": acc_data['account_name'],
                    "company": company_name,
                    "account_type": acc_data['account_type'],
                    "is_group": acc_data['is_group']
                })
                account.flags.ignore_permissions = True
                account.insert()
                self.results['master_data_created'] += 1
    
    def _ensure_cost_centers(self):
        """Ensure cost centers exist for expense tracking"""
        company_name = "Test Company Netherlands"
        
        if not frappe.db.exists("Cost Center", f"Main - TCN"):
            cost_center = frappe.get_doc({
                "doctype": "Cost Center",
                "cost_center_name": "Main",
                "company": company_name,
                "is_group": 0
            })
            cost_center.flags.ignore_permissions = True
            cost_center.insert()
            self.results['master_data_created'] += 1
    
    def _validate_environment(self):
        """Validate that the test environment is properly set up"""
        validation_checks = [
            ("Verenigingen Settings exists", lambda: frappe.db.exists("Verenigingen Settings", "Verenigingen Settings")),
            ("Team roles available", lambda: frappe.db.count("Team Role") > 0),
            ("Membership types available", lambda: frappe.db.count("Membership Type") > 0),
            ("Company exists", lambda: frappe.db.count("Company") > 0),
            ("Fiscal year exists", lambda: frappe.db.count("Fiscal Year") > 0),
            ("Basic accounts exist", lambda: frappe.db.count("Account") > 3),
        ]
        
        passed = failed = 0
        
        for check_name, check_func in validation_checks:
            try:
                if check_func():
                    print(f"   ✅ {check_name}")
                    passed += 1
                else:
                    print(f"   ❌ {check_name}")
                    failed += 1
                    self.results['errors'].append(f"Validation failed: {check_name}")
            except Exception as e:
                print(f"   ❌ {check_name}: {str(e)}")
                failed += 1
                self.results['errors'].append(f"Validation error for {check_name}: {str(e)}")
        
        print(f"\n   📊 Validation Summary: {passed} passed, {failed} failed")
    
    def _print_summary(self):
        """Print comprehensive initialization summary"""
        duration = (datetime.now() - self.start_time).total_seconds()
        
        print("=" * 60)
        print("🎯 TEST ENVIRONMENT INITIALIZATION COMPLETE")
        print("=" * 60)
        
        print(f"⏱️  Duration: {duration:.2f} seconds")
        print(f"📦 Fixtures: {self.results['fixtures_loaded']} loaded, {self.results['fixtures_skipped']} skipped, {self.results['fixtures_failed']} failed")
        print(f"🏗️  Master Data: {self.results['master_data_created']} items created")
        print(f"📋 Settings: {self.results['settings_configured']} configured")
        
        if self.results['warnings']:
            print(f"\n⚠️  Warnings ({len(self.results['warnings'])}):")
            for warning in self.results['warnings'][:5]:  # Show first 5
                print(f"   • {warning}")
            if len(self.results['warnings']) > 5:
                print(f"   • ... and {len(self.results['warnings']) - 5} more")
        
        if self.results['errors']:
            print(f"\n❌ Errors ({len(self.results['errors'])}):")
            for error in self.results['errors']:
                print(f"   • {error}")
            print("\n⚠️  Some components failed to initialize. Tests may experience issues.")
        else:
            print("\n✅ All components initialized successfully!")
            print("🚀 Test environment is ready for comprehensive testing.")
        
        print("=" * 60)


def main():
    """Main entry point for test environment initialization"""
    if not frappe.db:
        frappe.connect()
    
    # Ensure we're running as administrator
    frappe.set_user("Administrator")
    
    # Initialize the test environment
    initializer = TestEnvironmentInitializer()
    initializer.initialize_complete_environment()
    
    return initializer.results


# Command line execution support
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--site":
        # Running via bench execute
        main()
    else:
        print("Usage: bench --site [site-name] execute scripts.testing.initialize_test_environment.main")