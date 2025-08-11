#!/usr/bin/env python3
"""
Comprehensive Field Validator
Loads doctypes from all installed apps and validates field references comprehensively
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass

@dataclass
class ValidationIssue:
    """Represents a field validation issue"""
    file: str
    line: int
    field: str
    doctype: str
    reference: str
    message: str
    context: str
    confidence: str
    issue_type: str
    suggested_fix: Optional[str] = None

class ComprehensiveFieldValidator:
    """Comprehensive field validator that loads doctypes from all installed apps"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.bench_path = self.app_path.parent.parent
        self.doctypes = self.load_all_doctypes()
        self.issues = []
        
    def load_all_doctypes(self) -> Dict[str, Dict]:
        """Load doctypes from all installed apps"""
        doctypes = {}
        
        # Standard apps to check
        app_paths = [
            self.bench_path / "apps" / "frappe",  # Core Frappe
            self.bench_path / "apps" / "erpnext",  # ERPNext if available
            self.bench_path / "apps" / "payments",  # Payments app if available
            self.app_path,  # Current app (verenigingen)
        ]
        
        for app_path in app_paths:
            if app_path.exists():
                print(f"Loading doctypes from {app_path.name}...")
                app_doctypes = self._load_doctypes_from_app(app_path)
                doctypes.update(app_doctypes)
                
        print(f"📋 Loaded {len(doctypes)} doctypes from all apps")
        return doctypes
    
    def _load_doctypes_from_app(self, app_path: Path) -> Dict[str, Dict]:
        """Load doctypes from a specific app"""
        doctypes = {}
        
        # Find all doctype JSON files
        for json_file in app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract actual field names
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
                    
                    doctypes[doctype_name] = {
                        'fields': fields,
                        'data': data,
                        'app': app_path.name
                    }
                    
                except Exception as e:
                    # Skip problematic files silently
                    continue
                    
        return doctypes
    
    def validate_attribute_access(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate direct attribute access patterns like obj.field"""
        violations = []
        
        # Pattern for obj.field access
        pattern = r'(\w+)\.([a-zA-Z_][a-zA-Z0-9_]*)'
        
        for match in re.finditer(pattern, content):
            obj_name = match.group(1)
            field_name = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            
            # Skip common non-field patterns and Frappe API calls
            if field_name in {'save', 'insert', 'delete', 'get', 'set', 'append', 'extend', 'strip', 'lower', 'upper', 'split', 'join', 'format', 'replace', 'reload', 'submit', 'cancel', 'as_dict', 'as_json'}:
                continue
                
            # Skip Frappe module/API references
            if obj_name == 'frappe' and field_name in {'db', 'get_all', 'get_list', 'get_doc', 'get_value', 'get_single_value', 'set_value', 'new_doc', 'delete_doc', 'session', 'get_roles', 'throw', 'msgprint', 'enqueue', 'logger', 'cache', 'utils', 'form_dict', 'request', 'response', 'local'}:
                continue
                
            # Skip common method calls that aren't fields
            if field_name in {'meta', 'get_all', 'get_list', 'get_doc', 'get_value', 'db', 'session', 'get_roles', 'logger', 'can_view_member_payments', 'has_common_link', 'create_minimal_employee', 'add', 'members', 'enabled', 'member_name', 'print_exc', 'destroy', 'templates', 'volunteer', 'delete_doc', 'title'}:
                continue
                
            # Try to determine doctype from context
            doctype = self._guess_doctype_from_context(content, match.start(), obj_name)
            
            if doctype and doctype in self.doctypes:
                doctype_info = self.doctypes[doctype]
                fields = doctype_info['fields']
                
                if field_name not in fields:
                    # Find similar fields
                    similar = self._find_similar_fields(field_name, fields)
                    similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                    
                    violations.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype,
                        reference=f"{obj_name}.{field_name}",
                        message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
                        context=self._get_line_context(content, line_num),
                        confidence="high",
                        issue_type="missing_field_attribute_access",
                        suggested_fix=f"Use correct field name for {doctype} (from {doctype_info['app']} app)"
                    ))
        
        return violations
    
    def validate_field_lists(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate field lists in frappe.get_all() and similar queries"""
        violations = []
        
        # Pattern for frappe.get_all with fields parameter
        patterns = [
            r'frappe\.get_all\(\s*["\']([^"\']+)["\'][^)]*fields\s*=\s*\[(.*?)\]',
            r'frappe\.db\.get_all\(\s*["\']([^"\']+)["\'][^)]*fields\s*=\s*\[(.*?)\]',
            r'frappe\.get_list\(\s*["\']([^"\']+)["\'][^)]*fields\s*=\s*\[(.*?)\]',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                doctype = match.group(1)
                fields_content = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                if doctype in self.doctypes:
                    doctype_info = self.doctypes[doctype]
                    valid_fields = doctype_info['fields']
                    
                    # Extract individual field names
                    field_pattern = r'["\']([^"\']+)["\']'
                    for field_match in re.finditer(field_pattern, fields_content):
                        field_name = field_match.group(1)
                        
                        if field_name not in valid_fields:
                            # Find similar fields
                            similar = self._find_similar_fields(field_name, valid_fields)
                            similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                            
                            violations.append(ValidationIssue(
                                file=str(file_path.relative_to(self.app_path)),
                                line=line_num,
                                field=field_name,
                                doctype=doctype,
                                reference=f"fields=[..., '{field_name}', ...]",
                                message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
                                context=self._get_line_context(content, line_num),
                                confidence="high",
                                issue_type="missing_field_in_query",
                                suggested_fix=f"Use correct field name for {doctype} (from {doctype_info['app']} app)"
                            ))
        
        return violations
    
    def validate_filter_dictionaries(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate filter dictionaries in database queries"""
        violations = []
        
        # Patterns for database calls with filter dictionaries
        filter_patterns = [
            r'frappe\.(?:db\.)?(?:get_all|get_list|get_value|exists|count)\(\s*["\']([^"\']+)["\'][^)]*filters\s*=\s*(\{[^}]+\})',
        ]
        
        for pattern in filter_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                doctype = match.group(1)
                filter_dict_str = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                if doctype in self.doctypes:
                    doctype_info = self.doctypes[doctype]
                    valid_fields = doctype_info['fields']
                    
                    # Extract field names that are keys in the filter dictionary
                    key_pattern = r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']\s*:'
                    key_matches = re.findall(key_pattern, filter_dict_str)
                    
                    for field_name in key_matches:
                        # Skip SQL operators
                        if field_name.lower() in ['in', 'like', 'between', 'not', 'is', 'null']:
                            continue
                            
                        if field_name not in valid_fields:
                            # Find similar fields
                            similar = self._find_similar_fields(field_name, valid_fields)
                            similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                            
                            violations.append(ValidationIssue(
                                file=str(file_path.relative_to(self.app_path)),
                                line=line_num,
                                field=field_name,
                                doctype=doctype,
                                reference=f"filter dict: {field_name}",
                                message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
                                context=self._get_line_context(content, line_num),
                                confidence="high",
                                issue_type="missing_field_in_filter",
                                suggested_fix=f"Use correct field name for {doctype} (from {doctype_info['app']} app)"
                            ))
        
        return violations
    
    def validate_sql_queries(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate SQL queries for field references"""
        violations = []
        
        # Extract SQL queries
        sql_patterns = [
            r'"""([^"]*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^"]*)"""',
            r"'''([^']*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^']*)'''",
            r'"([^"]*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^"]*)"',
            r"'([^']*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^']*)'"
        ]
        
        for pattern in sql_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
                sql_content = match.group(1).strip()
                line_num = content[:match.start()].count('\n') + 1
                
                if len(sql_content) > 20:
                    # Extract table aliases
                    aliases = self._extract_table_aliases(sql_content)
                    
                    # Extract field references
                    field_refs = self._extract_field_references(sql_content, aliases)
                    
                    for doctype, field, full_ref in field_refs:
                        if doctype in self.doctypes:
                            doctype_info = self.doctypes[doctype]
                            valid_fields = doctype_info['fields']
                            
                            if field not in valid_fields:
                                # Find similar fields
                                similar = self._find_similar_fields(field, valid_fields)
                                similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                                
                                violations.append(ValidationIssue(
                                    file=str(file_path.relative_to(self.app_path)),
                                    line=line_num,
                                    field=field,
                                    doctype=doctype,
                                    reference=f"SQL: {full_ref}",
                                    message=f"Field '{field}' does not exist in {doctype}{similar_text}",
                                    context=sql_content[:100] + ('...' if len(sql_content) > 100 else ''),
                                    confidence="medium",
                                    issue_type="missing_field_in_sql",
                                    suggested_fix=f"Use correct field name for {doctype} (from {doctype_info['app']} app)"
                                ))
        
        return violations
    
    def _extract_table_aliases(self, sql: str) -> Dict[str, str]:
        """Extract table aliases from SQL"""
        aliases = {}
        
        # Pattern for table aliases
        alias_patterns = [
            r'FROM\s+`tab([^`]+)`\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\s*(?:WHERE|ORDER|GROUP|LIMIT|ON|SET|;|$))',
            r'JOIN\s+`tab([^`]+)`\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\s*(?:ON|WHERE|ORDER|GROUP|LIMIT|;|$))',
        ]
        
        for pattern in alias_patterns:
            for match in re.finditer(pattern, sql, re.IGNORECASE):
                doctype = match.group(1)
                alias = match.group(2)
                aliases[alias] = doctype
        
        return aliases
    
    def _extract_field_references(self, sql: str, aliases: Dict[str, str]) -> List[Tuple[str, str, str]]:
        """Extract field references from SQL"""
        field_refs = []
        
        # SQL keywords to skip
        sql_keywords = {
            'SELECT', 'FROM', 'WHERE', 'ORDER', 'GROUP', 'HAVING', 'BY', 'AND', 'OR', 'NOT',
            'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'AS', 'LIKE', 'IN', 'ASC', 'DESC',
            'BETWEEN', 'IS', 'NULL', 'LIMIT', 'OFFSET', 'JOIN', 'INNER', 'LEFT', 'RIGHT'
        }
        
        # Look for alias.field references
        field_pattern = r'(\w+)\.(\w+)'
        for match in re.finditer(field_pattern, sql):
            alias = match.group(1)
            field = match.group(2)
            
            # Skip SQL keywords
            if alias.upper() in sql_keywords or field.upper() in sql_keywords:
                continue
                
            if alias in aliases:
                doctype = aliases[alias]
                field_refs.append((doctype, field, f"{alias}.{field}"))
        
        return field_refs
    
    def _find_similar_fields(self, field_name: str, valid_fields: Set[str]) -> List[str]:
        """Find similar field names using string matching"""
        similar = []
        field_lower = field_name.lower()
        
        for valid_field in valid_fields:
            valid_lower = valid_field.lower()
            # Check for substring matches and similar patterns
            if (field_lower in valid_lower or valid_lower in field_lower or
                (len(field_lower) > 3 and len(valid_lower) > 3 and
                 (field_lower.startswith(valid_lower[:4]) or
                  field_lower.endswith(valid_lower[-4:]) or
                  valid_lower.startswith(field_lower[:4]) or
                  valid_lower.endswith(field_lower[-4:])))):
                similar.append(valid_field)
                
        return similar[:5]  # Return top 5 matches
    
    def _guess_doctype_from_context(self, content: str, position: int, obj_name: str = None) -> Optional[str]:
        """Try to guess the DocType from context"""
        # Look backwards for clues
        context_before = content[max(0, position - 500):position]
        
        # Look for frappe.get_doc calls
        get_doc_pattern = r'frappe\.get_doc\(["\']([^"\']+)["\']'
        matches = list(re.finditer(get_doc_pattern, context_before))
        if matches:
            return matches[-1].group(1)
        
        # Look for frappe.get_all calls
        get_all_pattern = r'frappe\.get_all\(["\']([^"\']+)["\']'
        matches = list(re.finditer(get_all_pattern, context_before))
        if matches:
            return matches[-1].group(1)
        
        # Look for variable assignments from DocTypes
        if obj_name:
            assign_pattern = rf'{obj_name}\s*=\s*frappe\.get_doc\(["\']([^"\']+)["\']'
            match = re.search(assign_pattern, context_before)
            if match:
                return match.group(1)
        
        return None
    
    def _get_line_context(self, content: str, line_num: int) -> str:
        """Get the line context for a given line number"""
        lines = content.split('\n')
        if 1 <= line_num <= len(lines):
            return lines[line_num - 1].strip()
        return ""
    
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate field references in a single file"""
        violations = []
        
        # Skip certain files to reduce noise
        skip_patterns = ['__pycache__', '.git', 'node_modules', '.pyc']
        if any(pattern in str(file_path) for pattern in skip_patterns):
            return violations
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Validate different types of field references
            violations.extend(self.validate_attribute_access(content, file_path))
            violations.extend(self.validate_field_lists(content, file_path))
            violations.extend(self.validate_filter_dictionaries(content, file_path))
            violations.extend(self.validate_sql_queries(content, file_path))
            
        except Exception as e:
            print(f"Error validating {file_path}: {e}")
            
        return violations
    
    def run_validation(self, pre_commit_mode: bool = False) -> bool:
        """Run comprehensive field validation"""
        if not pre_commit_mode:
            print("🔍 Running Comprehensive Field Validation...")
        
        all_violations = []
        file_count = 0
        
        # Validate all Python files in the current app
        for py_file in self.app_path.rglob("*.py"):
            # Skip cache files only
            if any(skip in str(py_file) for skip in ['__pycache__', '.pyc']):
                continue
            
            violations = self.validate_file(py_file)
            all_violations.extend(violations)
            file_count += 1
        
        if not pre_commit_mode:
            print(f"📊 Checked {file_count} Python files")
        
        # Filter by confidence for different modes
        if pre_commit_mode:
            # Only show high confidence issues in pre-commit  
            high_conf_violations = [v for v in all_violations if v.confidence == 'high']
            if high_conf_violations:
                print(f"🚨 Found {len(high_conf_violations)} critical field reference issues:")
                for violation in high_conf_violations:
                    print(f"❌ {violation.file}:{violation.line} - {violation.field} not in {violation.doctype}")
                    if violation.suggested_fix:
                        print(f"   → {violation.suggested_fix}")
                return False
            return True
        else:
            # Full reporting for manual runs
            if all_violations:
                # Group by confidence
                high_conf = [v for v in all_violations if v.confidence == 'high']
                med_conf = [v for v in all_violations if v.confidence == 'medium']
                
                print(f"\\n🔍 Comprehensive Field Validation Results:")
                print(f"📊 Total issues: {len(all_violations)}")
                print(f"🔴 High confidence (critical): {len(high_conf)}")
                print(f"🟡 Medium confidence (investigate): {len(med_conf)}")
                print()
                
                # Show high confidence issues
                if high_conf:
                    print("🔴 HIGH CONFIDENCE ISSUES (Priority fixes):")
                    for violation in high_conf:
                        print(f"❌ {violation.file}:{violation.line}")
                        print(f"   {violation.message}")
                        print(f"   Reference: {violation.reference}")
                        print(f"   Context: {violation.context}")
                        if violation.suggested_fix:
                            print(f"   💡 Fix: {violation.suggested_fix}")
                        print()
                
                # Show summary of medium confidence issues  
                if med_conf:
                    print(f"🟡 MEDIUM CONFIDENCE ISSUES ({len(med_conf)} total)")
                    for violation in med_conf[:10]:  # Limit output
                        print(f"   {violation.file}:{violation.line} - {violation.message}")
                        print(f"   Reference: {violation.reference}")
                        if violation.suggested_fix:
                            print(f"   💡 Fix: {violation.suggested_fix}")
                        print()
                    if len(med_conf) > 10:
                        print(f"   ... and {len(med_conf) - 10} more medium confidence issues")
                
                return len(high_conf) == 0
            else:
                print("✅ No field reference issues found!")
                return True

def main():
    """Main function"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Comprehensive field validation")
    parser.add_argument("--pre-commit", action="store_true", help="Run in pre-commit mode")
    args = parser.parse_args()
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = ComprehensiveFieldValidator(app_path)
    
    success = validator.run_validation(pre_commit_mode=args.pre_commit)
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())