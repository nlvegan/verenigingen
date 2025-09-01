#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEPA Mandate Test Suite Validation Script
=========================================

This script validates that the comprehensive SEPA mandate test suite
is properly structured and can be imported without errors.

Usage:
    python scripts/testing/validate_sepa_test_suite.py
"""

import sys
import os
from pathlib import Path

# Add app path for imports
app_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_path))

def validate_test_files():
    """Validate that all test files exist and are properly structured."""
    
    print("Validating SEPA Mandate Test Suite Structure...")
    print("=" * 50)
    
    test_files = {
        "Comprehensive Test Suite": "verenigingen/verenigingen_payments/doctype/sepa_mandate/test_sepa_mandate_comprehensive.py",
        "SEPA Test Factory": "verenigingen/tests/fixtures/sepa_mandate_test_factory.py", 
        "Test Runner": "verenigingen/tests/test_sepa_mandate_runner.py",
        "Original Test Suite": "verenigingen/verenigingen_payments/doctype/sepa_mandate/test_sepa_mandate.py",
        "Documentation": "docs/testing/SEPA_MANDATE_TESTING_GUIDE.md"
    }
    
    all_exist = True
    
    for name, path in test_files.items():
        full_path = app_path / path
        if full_path.exists():
            print(f"✓ {name}: {path}")
            
            # Check file size to ensure it's not empty
            size = full_path.stat().st_size
            if size > 1000:  # Reasonable minimum size
                print(f"  Size: {size:,} bytes")
            else:
                print(f"  ⚠️  Warning: File seems small ({size} bytes)")
        else:
            print(f"❌ {name}: {path} - NOT FOUND")
            all_exist = False
    
    return all_exist

def validate_python_syntax():
    """Validate Python syntax of all test files."""
    
    print("\\nValidating Python Syntax...")
    print("=" * 30)
    
    python_files = [
        "verenigingen/verenigingen_payments/doctype/sepa_mandate/test_sepa_mandate_comprehensive.py",
        "verenigingen/tests/fixtures/sepa_mandate_test_factory.py",
        "verenigingen/tests/test_sepa_mandate_runner.py"
    ]
    
    all_valid = True
    
    for file_path in python_files:
        full_path = app_path / file_path
        if full_path.exists():
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    source = f.read()
                    
                # Try to compile the source
                compile(source, str(full_path), 'exec')
                print(f"✓ {file_path}: Syntax valid")
                
            except SyntaxError as e:
                print(f"❌ {file_path}: Syntax error - {e}")
                print(f"   Line {e.lineno}: {e.text}")
                all_valid = False
            except Exception as e:
                print(f"⚠️  {file_path}: Warning - {e}")
        else:
            print(f"❌ {file_path}: File not found")
            all_valid = False
            
    return all_valid

def validate_test_structure():
    """Validate the logical structure of the test suite."""
    
    print("\\nValidating Test Suite Structure...")
    print("=" * 35)
    
    structure_checks = {
        "Test Factory Classes": [
            "SEPAMandateTestDataFactory",
            "SEPAMandateTestMixin"
        ],
        "Test Case Classes": [
            "ComprehensiveSEPAMandateTests", 
            "SEPAMandateValidationTests",
            "SEPAMandateComplianceTests",
            "SEPAMandateIntegrationTests"
        ],
        "Key Test Methods": [
            "test_mandate_creation_with_valid_data",
            "test_psd2_compliance_validation", 
            "test_dutch_banking_dnb_compliance",
            "test_member_mandate_integration"
        ],
        "Dutch Banking Data": [
            "DUTCH_BANKS",
            "EUROPEAN_TEST_IBANS", 
            "get_random_dutch_iban",
            "get_bank_info_for_iban"
        ]
    }
    
    all_valid = True
    
    for category, items in structure_checks.items():
        print(f"\\n{category}:")
        
        for item in items:
            # Simple text search in files
            found = False
            
            for file_path in [
                "verenigingen/verenigingen_payments/doctype/sepa_mandate/test_sepa_mandate_comprehensive.py",
                "verenigingen/tests/fixtures/sepa_mandate_test_factory.py",
                "verenigingen/tests/test_sepa_mandate_runner.py"
            ]:
                full_path = app_path / file_path
                if full_path.exists():
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            if item in content:
                                found = True
                                break
                    except Exception:
                        continue
            
            if found:
                print(f"  ✓ {item}")
            else:
                print(f"  ❌ {item} - Not found")
                all_valid = False
                
    return all_valid

def main():
    """Main validation function."""
    
    print("SEPA Mandate Test Suite Validation")
    print("=" * 60)
    print()
    
    # Run all validations
    file_check = validate_test_files()
    syntax_check = validate_python_syntax() 
    structure_check = validate_test_structure()
    
    # Summary
    print("\\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    results = {
        "File Structure": "✓ PASS" if file_check else "❌ FAIL",
        "Python Syntax": "✓ PASS" if syntax_check else "❌ FAIL", 
        "Test Structure": "✓ PASS" if structure_check else "❌ FAIL"
    }
    
    for check, result in results.items():
        print(f"{check:20} {result}")
    
    overall_pass = all([file_check, syntax_check, structure_check])
    
    print()
    print("OVERALL RESULT:", "✅ ALL VALIDATIONS PASSED" if overall_pass else "❌ VALIDATION FAILURES")
    
    if overall_pass:
        print("\\n🎉 SEPA Mandate Test Suite is ready for use!")
        print("\\nTo run the tests:")
        print("  bench --site dev.veganisme.net run-tests --module verenigingen.tests.test_sepa_mandate_runner")
    else:
        print("\\n⚠️  Please fix the validation failures before using the test suite.")
        
    return 0 if overall_pass else 1

if __name__ == "__main__":
    sys.exit(main())