#!/usr/bin/env python3
"""
Enhanced JavaScript Call Analyzer
Analyzes JavaScript files for frappe.call() patterns and checks if corresponding Python methods exist.
"""

import os
import re
import json
import glob
from pathlib import Path

def find_js_files():
    """Find all JavaScript files in the project."""
    js_files = []
    base_dir = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Look in public/js, templates, and doctype folders
    patterns = [
        f"{base_dir}/verenigingen/public/js/**/*.js",
        f"{base_dir}/verenigingen/templates/**/*.js", 
        f"{base_dir}/verenigingen/**/doctype/**/*.js"
    ]
    
    for pattern in patterns:
        js_files.extend(glob.glob(pattern, recursive=True))
    
    return js_files

def extract_frappe_calls(js_file):
    """Extract frappe.call() method calls from JavaScript file."""
    calls = []
    
    try:
        with open(js_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Multiple patterns to catch different frappe.call formats
        patterns = [
            # Pattern 1: frappe.call({ method: 'path.to.method'
            r'frappe\.call\s*\(\s*\{[^}]*?method\s*:\s*[\'"`]([^\'"`]+)[\'"`]',
            # Pattern 2: await frappe.call({ method: "path.to.method"
            r'await\s+frappe\.call\s*\(\s*\{[^}]*?method\s*:\s*[\'"`]([^\'"`]+)[\'"`]',
            # Pattern 3: const response = await frappe.call({ method: 'path'
            r'const\s+\w+\s*=\s*await\s+frappe\.call\s*\(\s*\{[^}]*?method\s*:\s*[\'"`]([^\'"`]+)[\'"`]',
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, content, re.DOTALL | re.IGNORECASE)
            
            for match in matches:
                method_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Extract broader context around the call
                start_pos = max(0, match.start() - 100)
                end_pos = min(len(content), match.end() + 200)
                context = content[start_pos:end_pos]
                
                calls.append({
                    'file': js_file,
                    'line': line_num,
                    'method': method_name,
                    'context': context.strip()
                })
    
    except Exception as e:
        print(f"Error processing {js_file}: {e}")
    
    return calls

def check_python_method_exists(method_path):
    """Check if a Python method exists in the codebase."""
    base_dir = "/home/frappe/frappe-bench/apps/verenigingen"
    
    if '.' not in method_path:
        return False, "Invalid method path format"
    
    # Split method path: vereinigingen.api.member_management.get_member_data
    parts = method_path.split('.')
    
    if len(parts) < 3:
        return False, "Method path too short"
    
    # Skip verenigingen prefix if present
    if parts[0] == 'verenigingen':
        parts = parts[1:]
    
    if len(parts) < 2:
        return False, "Missing module or method"
    
    # Reconstruct file path
    module_parts = parts[:-1]  # All but last part
    method_name = parts[-1]    # Last part is method name
    
    # Try different file patterns
    possible_files = [
        f"{base_dir}/verenigingen/{'/'.join(module_parts)}.py",
        f"{base_dir}/{'/'.join(module_parts)}.py",
    ]
    
    for file_path in possible_files:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for function definition patterns
                patterns = [
                    rf'def\s+{re.escape(method_name)}\s*\(',
                    rf'@frappe\.whitelist\(\)\s*\n\s*def\s+{re.escape(method_name)}\s*\(',
                ]
                
                for pattern in patterns:
                    if re.search(pattern, content, re.MULTILINE):
                        # Check if it has @frappe.whitelist() decorator
                        whitelist_pattern = rf'@frappe\.whitelist\(\)\s*\n\s*def\s+{re.escape(method_name)}\s*\('
                        has_whitelist = bool(re.search(whitelist_pattern, content, re.MULTILINE))
                        
                        return True, f"Found in {file_path}" + (" (whitelisted)" if has_whitelist else " (no @frappe.whitelist)")
                
                return False, f"Method not found in {file_path}"
            
            except Exception as e:
                return False, f"Error reading {file_path}: {e}"
    
    return False, f"File not found for module path: {'/'.join(module_parts)}"

def analyze_method_purpose(method_name, context):
    """Analyze method purpose based on name and context."""
    name_lower = method_name.lower()
    
    # Common patterns
    if 'get_' in name_lower:
        return "Data retrieval", "Fetches data from database"
    elif 'create_' in name_lower or 'add_' in name_lower:
        return "Create operation", "Creates new records or entities"
    elif 'update_' in name_lower or 'modify_' in name_lower:
        return "Update operation", "Modifies existing records"
    elif 'delete_' in name_lower or 'remove_' in name_lower:
        return "Delete operation", "Removes records or entities"
    elif 'validate_' in name_lower or 'check_' in name_lower:
        return "Validation", "Validates data or business rules"
    elif 'process_' in name_lower or 'handle_' in name_lower:
        return "Processing", "Processes data or handles workflow"
    elif 'send_' in name_lower or 'notify_' in name_lower:
        return "Communication", "Sends notifications or communications"
    elif 'export_' in name_lower or 'import_' in name_lower:
        return "Data transfer", "Handles data import/export operations"
    elif 'search_' in name_lower or 'find_' in name_lower:
        return "Search", "Searches for records matching criteria"
    elif 'calculate_' in name_lower or 'compute_' in name_lower:
        return "Calculation", "Performs calculations or computations"
    else:
        return "Unknown", "Purpose unclear from method name"

def main():
    """Main analysis function."""
    print("🔍 JavaScript Call Analyzer - Enhanced Version")
    print("=" * 60)
    
    js_files = find_js_files()
    print(f"📁 Found {len(js_files)} JavaScript files")
    
    all_calls = []
    
    # Extract all calls
    for js_file in js_files:
        calls = extract_frappe_calls(js_file)
        all_calls.extend(calls)
    
    print(f"📞 Found {len(all_calls)} frappe.call() method calls")
    
    # Analyze each call
    results = []
    
    for call in all_calls:
        exists, status = check_python_method_exists(call['method'])
        purpose_type, purpose_desc = analyze_method_purpose(call['method'], call['context'])
        
        result = {
            'method': call['method'],
            'file': call['file'].replace('/home/frappe/frappe-bench/apps/verenigingen/', ''),
            'line': call['line'],
            'exists': exists,
            'status': status,
            'purpose_type': purpose_type,
            'purpose_description': purpose_desc,
            'context': call['context'],
            'priority': 'FIX' if not exists else 'OK',
            'action': 'Add missing method' if not exists else 'Verify implementation'
        }
        
        results.append(result)
    
    # Filter and sort results
    missing_methods = [r for r in results if not r['exists']]
    existing_methods = [r for r in results if r['exists']]
    
    print(f"\n📊 Analysis Results:")
    print(f"   ✅ Existing methods: {len(existing_methods)}")
    print(f"   ❌ Missing methods: {len(missing_methods)}")
    
    # Output detailed results
    print(f"\n🚨 MISSING METHODS ({len(missing_methods)}):")
    print("-" * 80)
    
    for result in missing_methods:
        print(f"Method: {result['method']}")
        print(f"File: {result['file']}:{result['line']}")
        print(f"Purpose: {result['purpose_type']} - {result['purpose_description']}")
        print(f"Status: {result['status']}")
        print(f"Action: {result['action']}")
        print(f"Context: {result['context'][:100]}...")
        print("-" * 80)
    
    # Generate CSV for spreadsheet analysis
    csv_content = "Method,File,Line,Purpose Type,Purpose Description,Status,Action,Priority\n"
    
    for result in missing_methods:
        csv_content += f"\"{result['method']}\",\"{result['file']}\",{result['line']},\"{result['purpose_type']}\",\"{result['purpose_description']}\",\"{result['status']}\",\"{result['action']}\",{result['priority']}\n"
    
    # Save results
    with open('/home/frappe/frappe-bench/apps/verenigingen/docs/validation/enhanced-js-calls-review.csv', 'w') as f:
        f.write(csv_content)
    
    # Generate markdown report
    markdown_content = f"""# Enhanced JavaScript Calls Review

## Summary
- **Total JavaScript files analyzed**: {len(js_files)}
- **Total frappe.call() methods found**: {len(all_calls)}
- **Missing methods requiring fixes**: {len(missing_methods)}
- **Existing methods (OK)**: {len(existing_methods)}

## Missing Methods Analysis

"""
    
    for result in missing_methods:
        markdown_content += f"""### {result['method']}

- **File**: `{result['file']}:{result['line']}`
- **Purpose Type**: {result['purpose_type']}
- **Description**: {result['purpose_description']}
- **Status**: {result['status']}
- **Recommended Action**: {result['action']}
- **Priority**: {result['priority']}

**Context:**
```javascript
{result['context'][:200]}...
```

---

"""
    
    with open('/home/frappe/frappe-bench/apps/verenigingen/docs/validation/enhanced-js-calls-review.md', 'w') as f:
        f.write(markdown_content)
    
    print(f"\n📄 Reports generated:")
    print(f"   - Markdown: docs/validation/enhanced-js-calls-review.md")
    print(f"   - CSV: docs/validation/enhanced-js-calls-review.csv")

if __name__ == "__main__":
    main()