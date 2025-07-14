#!/usr/bin/env python3
"""
Import Validation Script for CI/CD

This script validates all Python imports in the verenigingen app.
It can be run as part of CI/CD pipeline to catch import errors early.

Usage:
    python scripts/validation/validate_imports.py
    
Exit codes:
    0 - All imports valid
    1 - Import errors found
    2 - Typos in imports found
"""

import os
import sys
import ast
import re
from pathlib import Path


def find_python_files(root_path):
    """Find all Python files in the app"""
    python_files = []
    
    skip_dirs = {'.git', '__pycache__', '.egg-info', 'node_modules', '.venv', 'env'}
    
    for root, dirs, files in os.walk(root_path):
        # Remove skip directories from dirs to prevent walking into them
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
                
    return python_files


def extract_imports(file_path):
    """Extract all import statements from a Python file"""
    imports = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(('import', alias.name))
            elif isinstance(node, ast.ImportFrom):
                module = node.module if node.module else ''
                for alias in node.names:
                    imports.append(('from', module, alias.name))
                    
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}")
        
    return imports


def check_import_typos(file_path):
    """Check for common typos in import statements"""
    typos_found = []
    
    # Skip certain directories
    if any(skip in file_path for skip in ['archived_unused', 'api_backups', '.disabled', '_backup']):
        return []
    
    # Common typo patterns for 'verenigingen' in imports only
    typo_patterns = [
        (r'from\s+vereinigen\.', 'vereinigen (missing "g")'),
        (r'import\s+vereinigen\.', 'vereinigen (missing "g")'),
        (r'from\s+verenigingn\.', 'verenigingn (transposed letters)'),
        (r'import\s+verenigingn\.', 'verenigingn (transposed letters)'),
        (r'from\s+vereinigingen\.', 'vereinigingen (extra "i")'),
        (r'import\s+vereinigingen\.', 'vereinigingen (extra "i")'),
    ]
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        for line_num, line in enumerate(content.split('\n'), 1):
            # Skip comments and docstrings
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
                
            # Only check lines that contain import statements
            if 'import' not in line and 'from' not in line:
                continue
                
            for pattern, description in typo_patterns:
                if re.search(pattern, line):
                    typos_found.append({
                        'line': line_num,
                        'text': line.strip(),
                        'typo': description
                    })
                    
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}")
        
    return typos_found


def validate_verenigingen_imports(imports, file_path):
    """Validate that verenigingen imports are correct"""
    errors = []
    
    for imp in imports:
        if imp[0] == 'import':
            module = imp[1]
        else:  # from import
            module = imp[1]
            
        # Check if it's a verenigingen import
        if module and module.startswith('verenig'):
            # Check for typos
            if not module.startswith('verenigingen.'):
                errors.append(f"Invalid import: {module} (should be 'verenigingen')")
                
    return errors


def main():
    """Main validation function"""
    # Get app root
    script_dir = Path(__file__).parent.parent.parent
    app_root = script_dir
    
    print(f"Validating imports in: {app_root}")
    print("=" * 60)
    
    # Find all Python files
    python_files = find_python_files(app_root)
    print(f"Found {len(python_files)} Python files")
    
    # Track results
    total_files = len(python_files)
    files_with_errors = 0
    files_with_typos = 0
    all_errors = []
    all_typos = []
    
    # Check each file
    for file_path in python_files:
        relative_path = os.path.relpath(file_path, app_root)
        
        # Check for import typos
        typos = check_import_typos(file_path)
        if typos:
            files_with_typos += 1
            all_typos.append((relative_path, typos))
            
        # Extract and validate imports
        imports = extract_imports(file_path)
        errors = validate_verenigingen_imports(imports, file_path)
        
        if errors:
            files_with_errors += 1
            all_errors.append((relative_path, errors))
            
    # Report results
    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    
    if all_typos:
        print(f"\n❌ Found typos in {files_with_typos} files:\n")
        for file_path, typos in all_typos[:10]:  # Show first 10
            print(f"  {file_path}:")
            for typo in typos[:3]:  # Show first 3 typos per file
                print(f"    Line {typo['line']}: {typo['typo']}")
                print(f"    > {typo['text']}")
            print()
            
        if len(all_typos) > 10:
            print(f"  ... and {len(all_typos) - 10} more files with typos")
            
    if all_errors:
        print(f"\n❌ Found import errors in {files_with_errors} files:\n")
        for file_path, errors in all_errors[:10]:  # Show first 10
            print(f"  {file_path}:")
            for error in errors:
                print(f"    - {error}")
            print()
            
        if len(all_errors) > 10:
            print(f"  ... and {len(all_errors) - 10} more files with errors")
            
    if not all_typos and not all_errors:
        print("\n✅ All imports are valid!")
        print(f"   Checked {total_files} files")
        return 0
    else:
        print(f"\n📊 Summary:")
        print(f"   Total files checked: {total_files}")
        print(f"   Files with typos: {files_with_typos}")
        print(f"   Files with import errors: {files_with_errors}")
        
        # Return appropriate exit code
        if all_typos:
            return 2
        elif all_errors:
            return 1
            
    return 0


if __name__ == "__main__":
    sys.exit(main())