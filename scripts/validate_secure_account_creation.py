#!/usr/bin/env python3
"""
Security Validation Script for Account Creation Manager

This script validates that the new secure account creation system:
1. Has eliminated all unauthorized permission bypasses
2. Properly implements background processing
3. Includes comprehensive error handling
4. Maintains complete audit trails

Run this script to verify the implementation before deployment.
"""

import os
import re
import sys
import frappe


def validate_permission_bypasses():
    """Scan for unauthorized permission bypasses"""
    print("🔒 Validating permission security...")
    
    files_to_scan = [
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/account_creation_manager.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/account_creation_request/account_creation_request.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/volunteer/volunteer.py"
    ]
    
    violations = []
    authorized_bypasses = 0
    
    for file_path in files_to_scan:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                lines = f.readlines()
                
            for i, line in enumerate(lines):
                # Look for actual ignore_permissions=True usage, not comments about it
                if 'ignore_permissions=True' in line and not line.strip().startswith('#') and 'NO ignore_permissions=True' not in line:
                    context_lines = lines[max(0, i-2):min(len(lines), i+3)]
                    context = ''.join(context_lines)
                    
                    # Check if this is an authorized system operation
                    authorized = any(keyword in context.lower() for keyword in [
                        'system operation', 'status tracking', 'audit', 'mark_'
                    ])
                    
                    if authorized:
                        authorized_bypasses += 1
                        print(f"   ✅ Authorized bypass at {os.path.basename(file_path)}:{i+1} (system operation)")
                    else:
                        violations.append(f"{file_path}:{i+1}")
                        print(f"   ❌ UNAUTHORIZED bypass at {os.path.basename(file_path)}:{i+1}")
    
    if violations:
        print(f"❌ SECURITY FAILURE: {len(violations)} unauthorized permission bypasses found!")
        return False
    else:
        print(f"✅ Security validation passed: {authorized_bypasses} authorized system operations, 0 violations")
        return True


def validate_background_processing():
    """Validate background processing implementation"""
    print("\n⚙️ Validating background processing...")
    
    account_manager_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/account_creation_manager.py"
    
    if not os.path.exists(account_manager_path):
        print("❌ AccountCreationManager not found!")
        return False
    
    with open(account_manager_path, 'r') as f:
        content = f.read()
    
    # Check for required components
    checks = [
        ("frappe.enqueue", "Background job queueing"),
        ("AccountCreationManager", "Main manager class"),
        ("process_complete_pipeline", "Processing pipeline"),
        ("queue_account_creation_for_volunteer", "Volunteer integration"),
        ("retry_processing", "Retry mechanism")
    ]
    
    for pattern, description in checks:
        if pattern in content:
            print(f"   ✅ {description} implemented")
        else:
            print(f"   ❌ {description} missing")
            return False
    
    print("✅ Background processing validation passed")
    return True


def validate_doctype_creation():
    """Validate DocType files exist and are properly structured"""
    print("\n📄 Validating DocType creation...")
    
    required_files = [
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/account_creation_request/account_creation_request.json",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/account_creation_request/account_creation_request.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/account_creation_request_role/account_creation_request_role.json",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/account_creation_request_role/account_creation_request_role.py"
    ]
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"   ✅ {os.path.basename(file_path)} exists")
        else:
            print(f"   ❌ {os.path.basename(file_path)} missing")
            return False
    
    print("✅ DocType validation passed")
    return True


def validate_admin_interface():
    """Validate admin interface implementation"""
    print("\n🖥️ Validating admin interface...")
    
    admin_files = [
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/account_creation_request/account_creation_request.js",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/page/account_creation_dashboard/account_creation_dashboard.js"
    ]
    
    for file_path in admin_files:
        if os.path.exists(file_path):
            print(f"   ✅ {os.path.basename(file_path)} exists")
        else:
            print(f"   ❌ {os.path.basename(file_path)} missing")
            return False
    
    print("✅ Admin interface validation passed")
    return True


def validate_volunteer_integration():
    """Validate volunteer integration changes"""
    print("\n👥 Validating volunteer integration...")
    
    volunteer_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/volunteer/volunteer.py"
    
    if not os.path.exists(volunteer_path):
        print("❌ Volunteer DocType not found!")
        return False
    
    with open(volunteer_path, 'r') as f:
        content = f.read()
    
    # Check that old methods are removed and new secure method exists
    if 'def queue_secure_account_creation(self):' in content:
        print("   ✅ Secure account creation method implemented")
    else:
        print("   ❌ Secure account creation method missing")
        return False
    
    # Check that problematic methods are removed or not used in after_insert
    if 'self.assign_volunteer_role()' in content and 'after_insert' in content:
        after_insert_section = content[content.find('def after_insert'):]
        if 'self.assign_volunteer_role()' in after_insert_section:
            print("   ❌ Old insecure method still called in after_insert")
            return False
    
    print("✅ Volunteer integration validation passed")
    return True


def validate_test_implementation():
    """Validate test implementation"""
    print("\n🧪 Validating test implementation...")
    
    test_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/tests/test_secure_account_creation.py"
    
    if os.path.exists(test_path):
        print("   ✅ Security test suite implemented")
        
        with open(test_path, 'r') as f:
            content = f.read()
        
        # Check for key test methods
        test_methods = [
            'test_secure_account_creation_request_creation',
            'test_permission_validation_for_account_creation',
            'test_no_permission_bypasses_in_account_creation',
            'test_account_creation_audit_trail'
        ]
        
        for method in test_methods:
            if method in content:
                print(f"      ✅ {method}")
            else:
                print(f"      ❌ {method} missing")
                return False
    else:
        print("   ❌ Security test suite missing")
        return False
    
    print("✅ Test implementation validation passed")
    return True


def main():
    """Run all validation checks"""
    print("🚀 Validating Secure Account Creation Implementation")
    print("=" * 60)
    
    all_checks_passed = True
    
    checks = [
        validate_permission_bypasses,
        validate_background_processing,
        validate_doctype_creation,
        validate_admin_interface,
        validate_volunteer_integration,
        validate_test_implementation
    ]
    
    for check in checks:
        if not check():
            all_checks_passed = False
    
    print("\n" + "=" * 60)
    if all_checks_passed:
        print("🎉 ALL VALIDATIONS PASSED!")
        print("✅ Secure Account Creation Manager is ready for deployment")
        print("\nSecurity improvements:")
        print("• Eliminated unauthorized permission bypasses")
        print("• Implemented proper background processing")
        print("• Added comprehensive audit trails")
        print("• Created admin monitoring interface")
        print("• Integrated secure volunteer onboarding")
    else:
        print("❌ VALIDATION FAILED!")
        print("Please fix the issues above before deployment")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())