#!/usr/bin/env python3
"""
Pre-commit hook for JavaScript-Python parameter validation

This script integrates the JS-Python parameter validator with pre-commit hooks
to catch parameter mismatches before they are committed to the repository.
"""

import sys
import os
import subprocess
from pathlib import Path

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from js_python_parameter_validator import JSPythonParameterValidator

def get_changed_files():
    """Get list of changed files from git"""
    try:
        # Get staged files
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only'],
            capture_output=True,
            text=True,
            check=True
        )
        
        files = [line.strip() for line in result.stdout.split('\n') if line.strip()]
        
        # Filter for JS/Python files
        relevant_files = []
        for file in files:
            if file.endswith(('.js', '.ts', '.vue', '.py')):
                relevant_files.append(file)
        
        return relevant_files
        
    except subprocess.CalledProcessError:
        return []

def run_focused_validation(changed_files):
    """Run validation focused on changed files"""
    if not changed_files:
        return True, "No relevant files changed"
    
    # Determine project root
    project_root = Path(__file__).parent.parent.parent
    
    # Initialize validator
    validator = JSPythonParameterValidator(str(project_root))
    
    # Analyze only changed files
    js_files = [f for f in changed_files if f.endswith(('.js', '.ts', '.vue'))]
    py_files = [f for f in changed_files if f.endswith('.py')]
    
    # Quick scan of changed files
    for js_file in js_files:
        full_path = project_root / js_file
        if full_path.exists():
            validator._analyze_js_file(full_path)
            validator.stats['js_files_scanned'] += 1
    
    # Also scan all Python files to ensure we have complete function signatures
    # This is necessary because JS files might call functions not in changed Python files
    for py_file in project_root.glob("**/*.py"):
        if any(part in str(py_file) for part in ['.git', '__pycache__', 'node_modules']):
            continue
        validator._analyze_py_file(py_file)
        validator.stats['py_files_scanned'] += 1
    
    # Validate parameters
    validator.validate_parameters()
    
    # Check for critical/high issues
    critical_issues = [i for i in validator.issues if i.severity in ['critical', 'high']]
    
    if critical_issues:
        print("❌ JavaScript-Python parameter validation failed!")
        print(f"Found {len(critical_issues)} critical/high priority issues in changed files:\n")
        
        for issue in critical_issues[:10]:  # Show first 10 issues
            print(f"🔍 {issue.js_call.method_name} ({Path(issue.js_call.file_path).name}:{issue.js_call.line_number})")
            print(f"   {issue.description}")
            if issue.suggestion:
                print(f"   💡 {issue.suggestion}")
            print()
        
        if len(critical_issues) > 10:
            print(f"... and {len(critical_issues) - 10} more issues")
            print()
        
        print("🔧 To fix these issues:")
        print("   1. Review the parameter mismatches above")
        print("   2. Update JavaScript calls or Python function signatures")
        print("   3. Run validation again: python scripts/validation/js_python_parameter_validator.py")
        print("   4. Commit your fixes")
        print()
        
        return False, f"Critical validation issues found in {len(changed_files)} changed files"
    
    # Report on non-critical issues
    medium_issues = [i for i in validator.issues if i.severity == 'medium']
    if medium_issues:
        print(f"⚠️  Found {len(medium_issues)} medium priority issues (not blocking commit)")
        print("   Consider reviewing these in your next development cycle")
        print()
    
    print(f"✅ JavaScript-Python parameter validation passed!")
    print(f"   Checked {len(js_files)} JS files and {validator.stats['py_files_scanned']} Python files")
    print(f"   Found {len(validator.js_calls)} JS calls and {len(validator.python_functions)} Python functions")
    
    return True, "Validation passed"

def main():
    """Main pre-commit check function"""
    print("🔍 Running JavaScript-Python parameter validation...")
    
    # Get changed files
    changed_files = get_changed_files()
    
    if not changed_files:
        print("✅ No JavaScript or Python files changed - skipping validation")
        return 0
    
    print(f"📋 Checking {len(changed_files)} changed files...")
    
    # Run validation
    success, message = run_focused_validation(changed_files)
    
    if success:
        print(f"✅ {message}")
        return 0
    else:
        print(f"❌ {message}")
        return 1

if __name__ == "__main__":
    sys.exit(main())