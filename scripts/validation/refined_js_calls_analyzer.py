#!/usr/bin/env python3
"""
Refined JavaScript Call Analyzer
Focuses on actionable missing methods with better function purpose analysis.
"""

import os
import re
import json
import glob
from pathlib import Path
from collections import defaultdict

def find_js_files():
    """Find all JavaScript files in the project."""
    js_files = []
    base_dir = "/home/frappe/frappe-bench/apps/verenigingen"
    
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
            r'frappe\.call\s*\(\s*\{[^}]*?method\s*:\s*[\'"`]([^\'"`]+)[\'"`]',
            r'await\s+frappe\.call\s*\(\s*\{[^}]*?method\s*:\s*[\'"`]([^\'"`]+)[\'"`]',
            r'const\s+\w+\s*=\s*await\s+frappe\.call\s*\(\s*\{[^}]*?method\s*:\s*[\'"`]([^\'"`]+)[\'"`]',
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, content, re.DOTALL | re.IGNORECASE)
            
            for match in matches:
                method_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Extract broader context
                start_pos = max(0, match.start() - 150)
                end_pos = min(len(content), match.end() + 150)
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
    """Check if a Python method exists in the codebase with enhanced accuracy."""
    base_dir = "/home/frappe/frappe-bench/apps/verenigingen"
    
    if '.' not in method_path:
        return False, "Invalid method path format"
    
    # Split method path and handle verenigingen prefix
    parts = method_path.split('.')
    if parts[0] == 'verenigingen':
        parts = parts[1:]
    
    if len(parts) < 2:
        return False, "Method path too short"
    
    module_parts = parts[:-1]
    method_name = parts[-1]
    
    # Try multiple file path patterns
    possible_files = [
        f"{base_dir}/verenigingen/{'/'.join(module_parts)}.py",
        f"{base_dir}/{'/'.join(module_parts)}.py",
    ]
    
    # Special handling for e_boekhouden APIs
    if 'e_boekhouden' in module_parts:
        # Check if this is referencing the existing e_boekhouden structure
        ebh_file = f"{base_dir}/verenigingen/e_boekhouden/api.py"
        if os.path.exists(ebh_file):
            possible_files.insert(0, ebh_file)
    
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
                        whitelist_pattern = rf'@frappe\.whitelist\(\)\s*\n\s*def\s+{re.escape(method_name)}\s*\('
                        has_whitelist = bool(re.search(whitelist_pattern, content, re.MULTILINE))
                        
                        return True, f"Found in {file_path}" + (" (whitelisted)" if has_whitelist else " (missing @frappe.whitelist)")
                
                return False, f"Method '{method_name}' not found in {file_path}"
            
            except Exception as e:
                return False, f"Error reading {file_path}: {e}"
    
    return False, f"No suitable file found for method path: {'/'.join(module_parts)}"

def analyze_method_purpose_enhanced(method_name, context, file_path):
    """Enhanced method purpose analysis with context awareness."""
    name_lower = method_name.lower()
    
    # Context analysis for better purpose detection
    context_lower = context.lower() if context else ""
    
    # Enhanced patterns with context awareness
    if 'get_' in name_lower or 'fetch_' in name_lower:
        if 'status' in name_lower:
            return "Status Check", "Retrieves current status information"
        elif 'summary' in name_lower or 'list' in name_lower:
            return "Data Aggregation", "Fetches summarized or aggregated data"
        elif 'config' in name_lower:
            return "Configuration", "Retrieves configuration settings"
        else:
            return "Data Retrieval", "Fetches data from database"
    
    elif 'create_' in name_lower or 'add_' in name_lower:
        return "Create Operation", "Creates new records or entities"
    
    elif 'update_' in name_lower or 'modify_' in name_lower or 'bulk_update' in name_lower:
        return "Update Operation", "Modifies existing records"
    
    elif 'delete_' in name_lower or 'remove_' in name_lower or 'clear_' in name_lower:
        return "Delete Operation", "Removes records or entities"
    
    elif 'validate_' in name_lower or 'check_' in name_lower:
        return "Validation", "Validates data or business rules"
    
    elif 'process_' in name_lower or 'handle_' in name_lower:
        return "Processing", "Processes data or handles workflow"
    
    elif 'send_' in name_lower or 'notify_' in name_lower:
        return "Communication", "Sends notifications or communications"
    
    elif 'export_' in name_lower or 'import_' in name_lower:
        return "Data Transfer", "Handles data import/export operations"
    
    elif 'search_' in name_lower or 'find_' in name_lower or 'suggest_' in name_lower:
        return "Search/Suggestion", "Searches for records or provides suggestions"
    
    elif 'calculate_' in name_lower or 'compute_' in name_lower:
        return "Calculation", "Performs calculations or computations"
    
    elif 'start_' in name_lower or 'begin_' in name_lower:
        return "Workflow Control", "Initiates processes or workflows"
    
    elif 'apply_' in name_lower:
        return "Application", "Applies changes or configurations"
    
    elif 'preview_' in name_lower:
        return "Preview", "Provides preview of operations before execution"
    
    elif 'stage_' in name_lower:
        return "Staging", "Stages data for processing"
    
    elif 'migrate_' in name_lower:
        return "Migration", "Handles data migration operations"
    
    # Special handling for e_boekhouden methods
    if 'e_boekhouden' in method_name:
        if 'migration' in name_lower:
            return "Migration Tool", "E-Boekhouden data migration functionality"
        elif 'mapping' in name_lower:
            return "Account Mapping", "Manages account mappings for E-Boekhouden"
        else:
            return "E-Boekhouden Integration", "Integrates with E-Boekhouden accounting system"
    
    return "Unknown", "Purpose unclear from method name and context"

def is_framework_method(method_path):
    """Check if this is a Frappe framework method that should be ignored."""
    framework_prefixes = [
        'frappe.client.',
        'frappe.db.',
        'frappe.core.',
        'frappe.desk.',
        'frappe.utils.',
        'frappe.model.',
        'frappe.website.',
        'frappe.email.',
        'frappe.auth.',
        'erpnext.',
    ]
    
    return any(method_path.startswith(prefix) for prefix in framework_prefixes)

def categorize_by_complexity(method_name, purpose_type):
    """Categorize implementation complexity."""
    name_lower = method_name.lower()
    
    # Simple operations
    if purpose_type in ["Data Retrieval", "Status Check", "Configuration"] and "get_" in name_lower:
        return "Easy"
    
    # Medium complexity operations
    if purpose_type in ["Create Operation", "Update Operation", "Validation", "Search/Suggestion"]:
        return "Medium"
    
    # Complex operations
    if purpose_type in ["Migration Tool", "Workflow Control", "Data Transfer", "Processing"]:
        return "Hard"
    
    # Migration and e_boekhouden specific
    if "migration" in name_lower or "e_boekhouden" in method_name:
        return "Hard"
    
    return "Medium"

def group_by_component(results):
    """Group results by component/module for better organization."""
    groups = defaultdict(list)
    
    for result in results:
        method_path = result['method']
        
        if 'e_boekhouden' in method_path:
            groups['E-Boekhouden Integration'].append(result)
        elif 'member_management' in method_path:
            groups['Member Management'].append(result)
        elif 'termination' in method_path:
            groups['Termination Workflow'].append(result)
        elif 'dd_batch' in method_path:
            groups['Direct Debit Batching'].append(result)
        elif 'membership_application' in method_path:
            groups['Membership Applications'].append(result)
        elif 'chapter' in method_path:
            groups['Chapter Management'].append(result)
        elif 'volunteer' in method_path:
            groups['Volunteer Management'].append(result)
        else:
            groups['General/Other'].append(result)
    
    return groups

def main():
    """Main analysis function."""
    print("🔍 Refined JavaScript Call Analyzer")
    print("=" * 60)
    
    js_files = find_js_files()
    print(f"📁 Found {len(js_files)} JavaScript files")
    
    all_calls = []
    
    # Extract all calls
    for js_file in js_files:
        calls = extract_frappe_calls(js_file)
        all_calls.extend(calls)
    
    print(f"📞 Found {len(all_calls)} frappe.call() method calls")
    
    # Filter out duplicates
    unique_calls = {}
    for call in all_calls:
        key = f"{call['method']}|{call['file']}"
        if key not in unique_calls:
            unique_calls[key] = call
    
    print(f"🔄 Deduplicated to {len(unique_calls)} unique calls")
    
    # Analyze each call
    results = []
    
    for call in unique_calls.values():
        # Skip framework methods
        if is_framework_method(call['method']):
            continue
        
        exists, status = check_python_method_exists(call['method'])
        purpose_type, purpose_desc = analyze_method_purpose_enhanced(
            call['method'], call['context'], call['file']
        )
        complexity = categorize_by_complexity(call['method'], purpose_type)
        
        result = {
            'method': call['method'],
            'file': call['file'].replace('/home/frappe/frappe-bench/apps/verenigingen/', ''),
            'line': call['line'],
            'exists': exists,
            'status': status,
            'purpose_type': purpose_type,
            'purpose_description': purpose_desc,
            'complexity': complexity,
            'context': call['context'],
            'priority': 'OK' if exists else 'FIX',
            'action': 'Verify implementation' if exists else 'Add missing method'
        }
        
        results.append(result)
    
    # Filter results
    missing_methods = [r for r in results if not r['exists']]
    existing_methods = [r for r in results if r['exists']]
    
    print(f"\n📊 Analysis Results:")
    print(f"   ✅ Existing methods: {len(existing_methods)}")
    print(f"   ❌ Missing methods: {len(missing_methods)}")
    
    # Group missing methods by component
    grouped_missing = group_by_component(missing_methods)
    
    # Generate comprehensive markdown report
    markdown_content = f"""# Enhanced JavaScript Calls Review - Refined Analysis

## Executive Summary
- **Total JavaScript files analyzed**: {len(js_files)}
- **Total unique method calls found**: {len(unique_calls)}
- **Framework methods (excluded)**: {len(all_calls) - len(results)}
- **App-specific methods analyzed**: {len(results)}
- **Missing methods requiring implementation**: {len(missing_methods)}
- **Existing methods (verified)**: {len(existing_methods)}

## Missing Methods by Component

"""
    
    # Sort groups by priority (E-Boekhouden first as it has the most missing methods)
    priority_order = [
        'E-Boekhouden Integration',
        'Direct Debit Batching',
        'Member Management',
        'Membership Applications',
        'Termination Workflow',
        'Chapter Management',
        'Volunteer Management',
        'General/Other'
    ]
    
    for component in priority_order:
        if component in grouped_missing:
            methods = grouped_missing[component]
            
            # Sort by complexity and purpose
            methods.sort(key=lambda x: (x['complexity'], x['purpose_type']))
            
            markdown_content += f"""### {component} ({len(methods)} methods)

"""
            
            for result in methods:
                markdown_content += f"""#### `{result['method']}`

- **File**: `{result['file']}:{result['line']}`
- **Purpose**: {result['purpose_type']} - {result['purpose_description']}
- **Implementation Complexity**: {result['complexity']}
- **Status**: {result['status']}
- **Recommended Action**: {result['action']}

**Context Preview:**
```javascript
{result['context'][:300]}{'...' if len(result['context']) > 300 else ''}
```

**Implementation Notes:**
"""
                
                # Add specific implementation guidance
                if 'e_boekhouden' in result['method']:
                    markdown_content += """- Should be implemented in `verenigingen/e_boekhouden/api/` directory
- Requires `@frappe.whitelist()` decorator for web access
- May need integration with existing e_boekhouden utilities
- Consider error handling for API failures
"""
                elif 'get_' in result['method']:
                    markdown_content += """- Simple data retrieval method
- Should use `frappe.db.get_value()` or `frappe.get_doc()`
- Add appropriate permission checks
- Return data in expected JSON format
"""
                elif 'create_' in result['method'] or 'add_' in result['method']:
                    markdown_content += """- Data creation operation
- Validate input parameters
- Use `frappe.get_doc()` and `doc.insert()`
- Handle validation errors gracefully
"""
                else:
                    markdown_content += """- Implement with appropriate business logic
- Add input validation and error handling
- Ensure proper permission checks
- Test thoroughly with edge cases
"""
                
                markdown_content += "\n---\n\n"
    
    # Add implementation priorities
    markdown_content += f"""## Implementation Priorities

### High Priority (Production Critical)
These methods are likely being called in production interfaces:

"""
    
    # Identify high priority methods (those in main UI files)
    high_priority = [r for r in missing_methods if any(ui_file in r['file'] for ui_file in [
        'chapter_dashboard.js', 'termination_dashboard.js', 'member_counter.js',
        'membership_application.js', 'dd_batch_management_enhanced.js'
    ])]
    
    for result in high_priority:
        markdown_content += f"- `{result['method']}` ({result['purpose_type']}) - {result['complexity']} complexity\n"
    
    markdown_content += f"""
### Medium Priority (Feature Enhancements)
E-Boekhouden migration interface methods:

"""
    
    ebh_methods = [r for r in missing_methods if 'e_boekhouden' in r['method']]
    for result in ebh_methods[:5]:  # Show first 5
        markdown_content += f"- `{result['method']}` ({result['purpose_type']}) - {result['complexity']} complexity\n"
    
    if len(ebh_methods) > 5:
        markdown_content += f"- ... and {len(ebh_methods) - 5} more e_boekhouden methods\n"
    
    markdown_content += f"""
### Low Priority (Optional Features)
Other missing methods that may be legacy or test functions.

## Next Steps

1. **Audit Production Usage**: Verify which missing methods are actually being called in production
2. **Prioritize by User Impact**: Focus on methods in user-facing interfaces first
3. **Create Implementation Plan**: Start with "Easy" complexity methods
4. **Add Testing**: Ensure all new methods have appropriate test coverage
5. **Update Documentation**: Document new API endpoints as they're implemented

## Files Generated
- **Detailed CSV**: `docs/validation/enhanced-js-calls-review.csv`
- **Implementation Tracker**: Use this markdown file to track progress

"""
    
    # Save comprehensive markdown report
    with open('/home/frappe/frappe-bench/apps/verenigingen/docs/validation/enhanced-js-calls-review.md', 'w') as f:
        f.write(markdown_content)
    
    # Generate actionable CSV
    csv_content = "Method,File,Line,Component,Purpose Type,Purpose Description,Complexity,Status,Action,Priority\n"
    
    for result in missing_methods:
        # Determine component
        component = "General"
        for comp, methods in grouped_missing.items():
            if result in methods:
                component = comp
                break
        
        csv_content += f'"{result["method"]}","{result["file"]}",{result["line"]},"{component}","{result["purpose_type"]}","{result["purpose_description"]}","{result["complexity"]}","{result["status"]}","{result["action"]}",{result["priority"]}\n'
    
    # Save CSV
    with open('/home/frappe/frappe-bench/apps/verenigingen/docs/validation/enhanced-js-calls-review.csv', 'w') as f:
        f.write(csv_content)
    
    print(f"\n📄 Reports generated:")
    print(f"   - Comprehensive Markdown: docs/validation/enhanced-js-calls-review.md")
    print(f"   - Actionable CSV: docs/validation/enhanced-js-calls-review.csv")
    print(f"\n🎯 Key Findings:")
    print(f"   - {len(ebh_methods)} E-Boekhouden integration methods missing")
    print(f"   - {len(high_priority)} high-priority UI methods missing")
    print(f"   - {len([r for r in missing_methods if r['complexity'] == 'Easy'])} easy-to-implement methods")

if __name__ == "__main__":
    main()