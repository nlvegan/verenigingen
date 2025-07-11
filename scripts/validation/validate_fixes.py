#!/usr/bin/env python3
"""
Quick validation script to check that the field fixes are syntactically correct
"""

import ast
import sys
from pathlib import Path

def validate_python_file(file_path):
    """Check if a Python file has valid syntax"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the AST to check for syntax errors
        ast.parse(content)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except Exception as e:
        return False, f"Error: {e}"

def main():
    """Validate the files we modified"""
    app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")
    
    # Files we modified
    files_to_check = [
        "verenigingen/verenigingen/doctype/chapter/chapter.py",
        "verenigingen/verenigingen/doctype/member/member.py",
        "verenigingen/verenigingen/doctype/membership/membership.py",
        "verenigingen/verenigingen/doctype/membership_type/membership_type.py",
        "verenigingen/verenigingen/doctype/donation/donation.py",
        "verenigingen/verenigingen/doctype/periodic_donation_agreement/periodic_donation_agreement.py",
    ]
    
    print("🔍 Validating Python syntax for modified files...")
    
    all_valid = True
    for file_path in files_to_check:
        full_path = app_path / file_path
        if full_path.exists():
            is_valid, error = validate_python_file(full_path)
            if is_valid:
                print(f"✅ {file_path}")
            else:
                print(f"❌ {file_path}: {error}")
                all_valid = False
        else:
            print(f"⚠️  {file_path}: File not found")
            all_valid = False
    
    if all_valid:
        print("\n✅ All modified files have valid Python syntax!")
        return 0
    else:
        print("\n❌ Some files have syntax errors!")
        return 1

if __name__ == "__main__":
    sys.exit(main())