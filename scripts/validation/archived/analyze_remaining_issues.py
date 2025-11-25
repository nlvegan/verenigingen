#!/usr/bin/env python3
"""
Analyze remaining issues from the field validator to identify patterns
"""

import subprocess
import re
from collections import Counter

def main():
    # Run the validator and capture output
    try:
        result = subprocess.run([
            'python', 'scripts/validation/production_field_validator.py', '--pre-commit'
        ], capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            output = result.stdout
        else:
            output = result.stdout
            
    except subprocess.TimeoutExpired:
        print("Validator timed out")
        return
    except Exception as e:
        print(f"Error running validator: {e}")
        return
    
    # Extract error patterns
    error_lines = []
    for line in output.split('\n'):
        if line.startswith('❌') and ' - ' in line and ' not in ' in line:
            error_lines.append(line)
    
    print(f"Found {len(error_lines)} error lines to analyze")
    
    # Analyze patterns
    field_patterns = Counter()
    doctype_patterns = Counter()
    field_doctype_patterns = Counter()
    
    for line in error_lines:
        # Extract field and doctype
        match = re.search(r'❌ .+?:(\d+) - (\w+) not in (.+)', line)
        if match:
            field = match.group(2)
            doctype = match.group(3)
            
            field_patterns[field] += 1
            doctype_patterns[doctype] += 1
            field_doctype_patterns[f"{field} not in {doctype}"] += 1
    
    print("\n=== TOP 20 MOST COMMON FIELD ISSUES ===")
    for field, count in field_patterns.most_common(20):
        print(f"{field:30} {count:3d} times")
    
    print("\n=== TOP 20 MOST COMMON DOCTYPE INFERENCE ISSUES ===")
    for doctype, count in doctype_patterns.most_common(20):
        print(f"{doctype:35} {count:3d} times")
    
    print("\n=== TOP 20 MOST COMMON FIELD-DOCTYPE COMBINATIONS ===")
    for pattern, count in field_doctype_patterns.most_common(20):
        print(f"{pattern:50} {count:3d} times")
    
    # Look for specific problematic patterns
    print("\n=== SPECIFIC PROBLEMATIC PATTERNS ===")
    
    # Find recursive reference issues
    recursive_issues = [line for line in error_lines if 'member not in Member' in line]
    print(f"Recursive 'member' references: {len(recursive_issues)}")
    if recursive_issues:
        print("Sample:", recursive_issues[0])
    
    # Find settings field issues
    settings_issues = [line for line in error_lines if any(term in line for term in [
        'default_grace_period_days', 'grace_period_notification_days', 'membership_type'
    ])]
    print(f"Settings field issues: {len(settings_issues)}")
    if settings_issues:
        print("Sample:", settings_issues[0])
    
    # Find child table confusion
    child_table_issues = [line for line in error_lines if 'child table' in line]
    print(f"Child table issues: {len(child_table_issues)}")
    if child_table_issues:
        print("Sample:", child_table_issues[0])

if __name__ == "__main__":
    main()