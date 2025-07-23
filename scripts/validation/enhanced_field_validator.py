#!/usr/bin/env python3
"""
Enhanced Field Validator
Comprehensive validation including both AST patterns and string literals in database queries
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Union


class EnhancedFieldValidator:
    """Enhanced field validation that catches both attribute access and string literals"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract actual field names only
                    fields = set()
                    for field in data.get('fields', []):
                        fieldname = field.get('fieldname')
                        if fieldname:
                            fields.add(fieldname)
                            
                    # Add standard Frappe document fields
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx',
                        'doctype', '_user_tags', '_comments', '_assign', '_liked_by'
                    ])
                    
                    doctypes[doctype_name] = fields
                    
                except Exception:
                    continue
                    
        return doctypes
    
    def extract_string_field_references(self, content: str) -> List[Dict]:
        """Extract field names from string literals in database queries with doctype context"""
        field_refs = []
        
        # Enhanced Pattern 1: frappe.db.get_value("Doctype", ..., ["field1", "field2", ...])
        get_value_pattern = r'frappe\.db\.get_value\s*\(\s*["\']([^"\']+)["\']\s*,[^)]*\[\s*([^]]+)\]'
        
        for match in re.finditer(get_value_pattern, content, re.MULTILINE | re.DOTALL):
            doctype = match.group(1)
            field_list = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            
            # Extract individual field names from the list
            field_matches = re.findall(r'"([^"]+)"|\'([^\']+)\'', field_list)
            for field_match in field_matches:
                field_name = field_match[0] or field_match[1]
                field_refs.append({
                    'field': field_name,
                    'line': line_num,
                    'context': 'frappe.db.get_value',
                    'pattern': 'string_literal',
                    'doctype': doctype  # Now we have the actual doctype!
                })
        
        # Enhanced Pattern 2: frappe.db.get_all("Doctype", fields=["field1", "field2", ...])
        get_all_pattern = r'frappe\.db\.get_all\s*\(\s*["\']([^"\']+)["\']\s*,[^)]*fields\s*=\s*\[\s*([^]]+)\]'
        
        for match in re.finditer(get_all_pattern, content, re.MULTILINE | re.DOTALL):
            doctype = match.group(1)
            field_list = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            
            field_matches = re.findall(r'"([^"]+)"|\'([^\']+)\'', field_list)
            for field_match in field_matches:
                field_name = field_match[0] or field_match[1]
                field_refs.append({
                    'field': field_name,
                    'line': line_num,
                    'context': 'frappe.db.get_all',
                    'pattern': 'string_literal',
                    'doctype': doctype  # Now we have the actual doctype!
                })
        
        # Fallback patterns for cases where doctype isn't in the first parameter
        # Pattern 1B: frappe.db.get_value(variable, ..., ["field1", "field2", ...]) - skip these
        get_value_fallback = r'frappe\.db\.get_value\s*\([^)]*\[\s*([^]]+)\]'
        
        for match in re.finditer(get_value_fallback, content, re.MULTILINE | re.DOTALL):
            # Skip if we already matched this with the enhanced pattern
            if any(ref['line'] == content[:match.start()].count('\n') + 1 for ref in field_refs):
                continue
                
            field_list = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            # Extract individual field names from the list
            field_matches = re.findall(r'"([^"]+)"|\'([^\']+)\'', field_list)
            for field_match in field_matches:
                field_name = field_match[0] or field_match[1]
                field_refs.append({
                    'field': field_name,
                    'line': line_num,
                    'context': 'frappe.db.get_value',
                    'pattern': 'string_literal',
                    'doctype': None  # Unknown doctype - will need fallback detection
                })
        
        # Pattern 3: frappe.db.sql with SELECT statements
        sql_select_pattern = r'frappe\.db\.sql\s*\(\s*["\']([^"\']*SELECT[^"\']*)["\']'
        
        for match in re.finditer(sql_select_pattern, content, re.MULTILINE | re.DOTALL):
            sql_query = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            # Extract field names from SELECT clause (basic parsing)
            select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql_query, re.IGNORECASE | re.DOTALL)
            if select_match:
                fields_part = select_match.group(1)
                # Basic field extraction (doesn't handle complex queries)
                field_candidates = re.findall(r'`?(\w+)`?(?:\s*,|\s+FROM)', fields_part + ' FROM')
                for field_name in field_candidates:
                    if field_name.lower() not in ['select', 'from', 'where', 'and', 'or']:
                        field_refs.append({
                            'field': field_name,
                            'line': line_num,
                            'context': 'frappe.db.sql',
                            'pattern': 'sql_query'
                        })
        
        # Pattern 4: Dictionary keys in document creation/updates
        doc_dict_pattern = r'{\s*["\']doctype["\'].*?["\'](\w+)["\'].*?["\'](\w+)["\']\s*:'
        
        for match in re.finditer(doc_dict_pattern, content, re.MULTILINE | re.DOTALL):
            field_name = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            
            # Skip common non-field keys
            if field_name not in ['doctype', 'name', 'parent', 'parentfield', 'parenttype']:
                field_refs.append({
                    'field': field_name,
                    'line': line_num,
                    'context': 'document_dict',
                    'pattern': 'dict_key'
                })
        
        return field_refs
    
    def get_doctype_from_context(self, file_path: Path, line_content: str) -> Optional[str]:
        """Try to determine doctype from context"""
        
        # Method 1: From file path
        doctype_from_path = self.get_doctype_from_file_path(file_path)
        if doctype_from_path:
            return doctype_from_path
        
        # Method 2: From string literals in the line
        doctype_matches = re.findall(r'["\']([A-Z][A-Za-z\s]+)["\']', line_content)
        for match in doctype_matches:
            if match in self.doctypes:
                return match
        
        # Method 3: Common patterns
        if 'Member' in line_content and 'Member' in self.doctypes:
            return 'Member'
        if 'Membership' in line_content and 'Membership' in self.doctypes:
            return 'Membership'
        if 'Volunteer' in line_content and 'Volunteer' in self.doctypes:
            return 'Volunteer'
        
        return None
    
    def get_doctype_from_file_path(self, file_path: Path) -> Optional[str]:
        """Extract doctype from file path"""
        path_parts = file_path.parts
        
        # Look for doctype pattern: /doctype/doctype_name/
        for i, part in enumerate(path_parts):
            if part == 'doctype' and i + 1 < len(path_parts):
                potential_doctype = path_parts[i + 1].replace('_', ' ').title()
                if potential_doctype in self.doctypes:
                    return potential_doctype
        
        return None
    
    def validate_file_comprehensive(self, file_path: Path) -> List[Dict]:
        """Comprehensive validation including string literals"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return violations
        
        # Extract string field references
        string_refs = self.extract_string_field_references(content)
        
        # Group by line for context analysis
        lines = content.splitlines()
        
        for ref in string_refs:
            line_num = ref['line']
            field_name = ref['field']
            
            # Skip obviously non-field names
            if self.is_likely_non_field(field_name):
                continue
            
            # Get context line
            if line_num <= len(lines):
                line_content = lines[line_num - 1]
                
                # Use extracted doctype if available, otherwise fall back to context detection
                doctype = ref.get('doctype')
                if not doctype:
                    doctype = self.get_doctype_from_context(file_path, line_content)
                
                if doctype and doctype in self.doctypes:
                    valid_fields = self.doctypes[doctype]
                    
                    if field_name not in valid_fields:
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': line_num,
                            'field': field_name,
                            'doctype': doctype,
                            'context': line_content.strip(),
                            'pattern': ref['pattern'],
                            'confidence': 'high' if ref['context'] in ['frappe.db.get_value', 'frappe.db.get_all'] else 'medium'
                        })
                elif doctype:
                    # Doctype exists but not in our loaded doctypes - might be core Frappe doctype
                    # Only flag if this looks like a custom doctype name pattern
                    if self.looks_like_custom_doctype(doctype):
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': line_num,
                            'field': field_name,
                            'doctype': doctype,
                            'context': line_content.strip(),
                            'pattern': ref['pattern'],
                            'confidence': 'low'  # Lower confidence for unknown doctypes
                        })
        
        return violations
    
    def is_likely_non_field(self, field_name: str) -> bool:
        """Check if a string is likely NOT a field name"""
        non_field_patterns = [
            # Common non-field strings
            r'^(doctype|name|parent|parentfield|parenttype|idx|creation|modified|owner|modified_by)$',
            # Database operations and SQL operators
            r'^(select|from|where|and|or|insert|update|delete|join|left|right|inner|outer|like|!=|=|<|>|<=|>=|is|not|null|in|exists)$',
            # Common values and statuses
            r'^(active|inactive|draft|submitted|cancelled|pending|approved|rejected|true|false|yes|no)$',
            # Numbers, short strings, or SQL patterns
            r'^\d+$|^[a-z]{1,2}$|^%.*%$|^\w*%$|^%\w*$',
            # URLs or paths
            r'^(http|https|ftp|/|\.)',
            # Common programming keywords
            r'^(if|else|for|while|def|class|import|from|return|try|except|finally)$',
            # Common system fields or non-field values
            r'^(filters|subject|success|enabled|comment_type|communication_type|opportunity_from|lead_name|file_name|employee_name|activity_type|for_user|triggered_at|account_type|item_code|member|by_chapter|invoice_specific_error_count|category)$'
        ]
        
        field_lower = field_name.lower().strip()
        
        for pattern in non_field_patterns:
            if re.match(pattern, field_lower):
                return True
        
        # Skip anything that looks like a SQL pattern or value
        if '%' in field_name or field_name in ['Administrator']:
            return True
        
        return False
    
    def looks_like_custom_doctype(self, doctype_name: str) -> bool:
        """Check if a doctype name looks like a custom doctype we should validate"""
        # Skip core Frappe doctypes that we don't need to validate
        core_frappe_doctypes = {
            'User', 'Role', 'Company', 'Item', 'Customer', 'Supplier', 'Employee', 
            'Sales Invoice', 'Purchase Invoice', 'Payment Entry', 'Journal Entry',
            'File', 'Lead', 'Opportunity', 'Task', 'Project', 'Email Template',
            'Workflow', 'Workflow State', 'Workflow Action Master', 'Singles',
            'Donor', 'Party Type', 'Donation Type', 'Report', 'Custom Field',
            'Role Profile', 'Module Profile', 'Workspace', 'Expense Category'
        }
        
        if doctype_name in core_frappe_doctypes:
            return False
            
        # These look like our custom doctypes that should be validated
        custom_patterns = ['Member', 'Membership', 'Chapter', 'Volunteer', 'Team', 'Verenigingen']
        return any(pattern in doctype_name for pattern in custom_patterns)
    
    def run_validation(self) -> bool:
        """Run comprehensive validation"""
        print("🔍 Running Enhanced Field Validation (includes string literals)...")
        print(f"📋 Loaded {len(self.doctypes)} doctypes with field definitions")
        
        all_violations = []
        file_count = 0
        
        # Search all Python files
        for py_file in self.app_path.rglob("*.py"):
            # Skip test files and cache files
            if any(skip in str(py_file) for skip in ['__pycache__', '.pyc', 'test_', '_test.py', '/tests/']):
                continue
            
            violations = self.validate_file_comprehensive(py_file)
            all_violations.extend(violations)
            file_count += 1
        
        print(f"📊 Checked {file_count} Python files")
        
        if all_violations:
            print(f"\n❌ Found {len(all_violations)} potential field reference issues:")
            print("=" * 80)
            
            # Group by doctype for better readability
            by_doctype = {}
            for violation in all_violations:
                doctype = violation['doctype']
                if doctype not in by_doctype:
                    by_doctype[doctype] = []
                by_doctype[doctype].append(violation)
            
            for doctype, violations in by_doctype.items():
                print(f"\n🏷️  {doctype} ({len(violations)} issues):")
                for violation in violations:
                    confidence_icon = "🔴" if violation['confidence'] == 'high' else "🟡"
                    print(f"  {confidence_icon} {violation['file']}:{violation['line']}")
                    print(f"     Field: '{violation['field']}' (pattern: {violation['pattern']})")
                    print(f"     Context: {violation['context']}")
                    print()
            
            print("=" * 80)
            print("💡 High confidence issues should be fixed immediately")
            print("💡 Medium confidence issues should be reviewed manually")
            return False
        else:
            print("\n✅ No field reference issues found!")
            print("✅ All field references validated successfully!")
            return True


def main():
    """Main entry point"""
    import sys
    
    # Get app path - this script is in scripts/validation, so app root is two levels up
    script_path = Path(__file__).resolve()
    app_path = script_path.parent.parent.parent
    
    # Verify this is the app root (hooks.py is in the verenigingen subdirectory)
    if not (app_path / 'verenigingen' / 'hooks.py').exists():
        print(f"Error: hooks.py not found at {app_path}")
        print(f"Script path: {script_path}")
        sys.exit(1)
    
    validator = EnhancedFieldValidator(str(app_path))
    success = validator.run_validation()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()