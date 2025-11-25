#!/usr/bin/env python3
"""
Test script for JavaScript-Python Parameter Validator

This script demonstrates the validator capabilities on specific key files
and provides examples of the types of issues it can detect.
"""

import os
import sys
from pathlib import Path

# Add the current directory to Python path so we can import the validator
sys.path.insert(0, os.path.dirname(__file__))

from js_python_parameter_validator import JSPythonParameterValidator, ValidationIssue

def test_validator_on_key_files():
    """Test the validator on specific key files"""
    print("🔍 JavaScript-Python Parameter Validator - Proof of Concept")
    print("=" * 60)
    
    # Initialize validator with app root
    app_root = Path(__file__).parent.parent.parent
    validator = JSPythonParameterValidator(str(app_root))
    
    # Test on specific files
    key_files = [
        "verenigingen/public/js/services/api-service.js",
        "verenigingen/verenigingen/doctype/member/member.js",
        "verenigingen/api/membership_application.py",
    ]
    
    print("📁 Analyzing key files:")
    for file_path in key_files:
        full_path = app_root / file_path
        if full_path.exists():
            print(f"   ✓ {file_path}")
        else:
            print(f"   ✗ {file_path} (not found)")
    print()
    
    # Scan limited set of files for demonstration
    test_js_files = [
        app_root / "verenigingen/public/js/services/api-service.js",
        app_root / "verenigingen/verenigingen/doctype/member/member.js",
        app_root / "verenigingen/verenigingen/doctype/volunteer/volunteer.js",
    ]
    
    test_py_files = [
        app_root / "verenigingen/api/membership_application.py",
        app_root / "verenigingen/api/member_management.py",
        app_root / "verenigingen/verenigingen/doctype/member/member.py",
    ]
    
    # Analyze JavaScript files
    print("🔎 Analyzing JavaScript files...")
    for js_file in test_js_files:
        if js_file.exists():
            validator._analyze_js_file(js_file)
            validator.stats['js_files_scanned'] += 1
            print(f"   📄 {js_file.name}: {len([c for c in validator.js_calls if js_file.name in c.file_path])} calls found")
    
    print()
    
    # Analyze Python files  
    print("🐍 Analyzing Python files...")
    for py_file in test_py_files:
        if py_file.exists():
            validator._analyze_py_file(py_file)
            validator.stats['py_files_scanned'] += 1
            functions_in_file = len([f for f in validator.python_functions.values() if py_file.name in f.file_path])
            print(f"   📄 {py_file.name}: {functions_in_file} whitelisted functions found")
    
    print()
    
    # Validate parameters
    print("✅ Validating parameters...")
    validator.validate_parameters()
    
    # Display results
    print(f"📊 Results Summary:")
    print(f"   • JavaScript files scanned: {validator.stats['js_files_scanned']}")
    print(f"   • Python files scanned: {validator.stats['py_files_scanned']}")
    print(f"   • JavaScript calls found: {len(validator.js_calls)}")
    print(f"   • Python functions found: {len(validator.python_functions)}")
    print(f"   • Issues found: {len(validator.issues)}")
    print()
    
    # Show examples of what was found
    if validator.js_calls:
        print("🔗 JavaScript Call Examples:")
        for i, call in enumerate(validator.js_calls[:5]):  # Show first 5
            print(f"   {i+1}. {call.method_name} (line {call.line_number})")
            if call.args:
                args_str = ", ".join(call.args.keys())
                print(f"      args: {args_str}")
        if len(validator.js_calls) > 5:
            print(f"      ... and {len(validator.js_calls) - 5} more")
        print()
    
    if validator.python_functions:
        print("🐍 Python Function Examples:")
        for i, (path, func) in enumerate(list(validator.python_functions.items())[:5]):
            params_str = ", ".join(func.parameters) if func.parameters else "no parameters"
            print(f"   {i+1}. {func.function_name}({params_str})")
            print(f"      path: {path}")
        if len(validator.python_functions) > 5:
            print(f"      ... and {len(validator.python_functions) - 5} more")
        print()
    
    # Show issues if found
    if validator.issues:
        print("⚠️  Issues Found:")
        issues_by_type = {}
        for issue in validator.issues:
            if issue.issue_type not in issues_by_type:
                issues_by_type[issue.issue_type] = []
            issues_by_type[issue.issue_type].append(issue)
        
        for issue_type, issues in issues_by_type.items():
            print(f"   {issue_type}: {len(issues)} issues")
            
            # Show first example
            if issues:
                example = issues[0]
                print(f"      Example: {example.js_call.method_name} in {Path(example.js_call.file_path).name}:{example.js_call.line_number}")
                print(f"      Description: {example.description}")
                if example.suggestion:
                    print(f"      Suggestion: {example.suggestion}")
                print()
    else:
        print("✅ No parameter validation issues found in test files!")
        print()
    
    # Show some successful matches
    successful_matches = []
    for call in validator.js_calls:
        if call.method_name in validator.python_functions:
            successful_matches.append((call, validator.python_functions[call.method_name]))
    
    if successful_matches:
        print("✅ Successful Matches Found:")
        for i, (call, func) in enumerate(successful_matches[:3]):  # Show first 3
            print(f"   {i+1}. {call.method_name}")
            print(f"      JS args: {list(call.args.keys()) if call.args else 'none'}")
            print(f"      Python params: {func.parameters}")
            print(f"      File: {Path(call.file_path).name}:{call.line_number}")
            print()
    
    return validator

def demonstrate_validation_capabilities():
    """Demonstrate the different types of validation issues the system can detect"""
    print("🎯 Validation Capabilities Demonstration")
    print("=" * 45)
    print()
    
    print("This validator can detect the following types of issues:")
    print()
    
    print("1. 🔍 Method Not Found")
    print("   - JavaScript calls to Python methods that don't exist")
    print("   - Methods that exist but aren't decorated with @frappe.whitelist()")
    print("   - Typos in method names")
    print()
    
    print("2. ❌ Missing Required Parameters")
    print("   - JavaScript calls missing parameters required by Python function")
    print("   - Helps prevent runtime errors from missing arguments")
    print()
    
    print("3. ➕ Extra Parameters")
    print("   - JavaScript passes parameters not accepted by Python function")
    print("   - Identifies potential parameter name mismatches")
    print("   - Helps optimize API calls by removing unused parameters")
    print()
    
    print("4. 🔄 Parameter Count Mismatches")
    print("   - Functions expecting different number of parameters")
    print("   - Accounts for *args and **kwargs in Python functions")
    print()
    
    print("5. 📝 Documentation Mismatches")
    print("   - Helps identify where documentation doesn't match implementation")
    print("   - Suggests parameter names and types")
    print()
    
    print("Supported JavaScript Patterns:")
    patterns = [
        "frappe.call({ method: 'module.function', args: {...} })",
        "frm.call({ method: 'function_name', args: {...} })",
        "api.call('method_name', args)",
        "this.call('method_name', {...})",
        "Custom button handlers with method calls",
    ]
    
    for pattern in patterns:
        print(f"   • {pattern}")
    print()

if __name__ == "__main__":
    # Run demonstration
    demonstrate_validation_capabilities()
    
    # Run actual test
    validator = test_validator_on_key_files()
    
    print("🎉 Proof of concept complete!")
    print()
    print("💡 Next Steps:")
    print("   1. Integrate with pre-commit hooks")
    print("   2. Add to CI/CD pipeline")
    print("   3. Create IDE extensions for real-time validation")
    print("   4. Enhance parameter type checking")
    print("   5. Add support for more JavaScript frameworks")