#!/usr/bin/env python3
"""
Enhanced Field Validator
Catches all types of field references including those missed by the current validator
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

class EnhancedFieldValidator:
    """Enhanced field validator that catches all types of field references"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        self.deprecated_fields = self.load_deprecated_fields()
        self.issues = []
        
    def load_doctypes(self) -> Dict[str, Dict]:
        """Load all DocType definitions"""
        doctypes = {}
        doctype_path = self.app_path / "verenigingen" / "verenigingen" / "doctype"
        
        for doctype_dir in doctype_path.iterdir():
            if doctype_dir.is_dir():
                json_file = doctype_dir / f"{doctype_dir.name}.json"
                if json_file.exists():
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            doctype_data = json.load(f)
                            doctype_name = doctype_data.get('name', '')
                            
                            # Extract field names
                            fields = set()
                            for field in doctype_data.get('fields', []):
                                if 'fieldname' in field:
                                    fields.add(field['fieldname'])
                            
                            doctypes[doctype_name] = {
                                'fields': fields,
                                'data': doctype_data
                            }
                    except Exception as e:
                        print(f"Error loading {json_file}: {e}")
        
        return doctypes
    
    def load_deprecated_fields(self) -> Dict[str, List[str]]:
        """Load deprecated fields configuration"""
        # Known deprecated fields based on recent fixes
        return {
            'Membership': ['next_billing_date'],
            'SEPA Audit Log': ['event_type', 'severity', 'ip_address'],
            'Member': ['chapter'],  # Direct chapter field doesn't exist on Member doctype
        }
    
    def validate_all_files(self) -> List[ValidationIssue]:
        """Validate all files in the application"""
        self.issues = []
        
        # Validate Python files
        for py_file in self.app_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            self._validate_python_file(py_file)
        
        # Validate HTML template files
        for html_file in self.app_path.rglob("*.html"):
            if self._should_skip_file(html_file):
                continue
            self._validate_template_file(html_file)
        
        # Validate JavaScript files
        for js_file in self.app_path.rglob("*.js"):
            if self._should_skip_file(js_file):
                continue
            self._validate_javascript_file(js_file)
        
        return self.issues
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped"""
        skip_patterns = [
            '__pycache__',
            '.git',
            'node_modules',
            '.pyc',
            'test_field_validation_gaps.py'  # Skip our own test file
        ]
        
        file_str = str(file_path)
        return any(pattern in file_str for pattern in skip_patterns)
    
    def _validate_python_file(self, file_path: Path):
        """Validate a Python file for field references"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            # Pattern 1: getattr() access
            self._check_getattr_patterns(file_path, content, lines)
            
            # Pattern 2: Direct attribute access
            self._check_attribute_access(file_path, content, lines)
            
            # Pattern 3: Field lists in queries
            self._check_field_lists(file_path, content, lines)
            
            # Pattern 4: SQL queries
            self._check_sql_queries(file_path, content, lines)
            
            # Pattern 5: Database operations (db_set, db_get)
            self._check_database_operations(file_path, content, lines)
            
            # Pattern 6: Dictionary keys and get() calls
            self._check_dictionary_patterns(file_path, content, lines)
            
            # Pattern 7: get_single_value calls for Singles doctypes
            self._check_get_single_value_patterns(file_path, content, lines)
            
            # Pattern 8: Database filter dictionaries
            self._check_filter_dictionary_patterns(file_path, content, lines)
            
            # Pattern 9: Child table field access
            self._check_child_table_field_access(file_path, content, lines)
            
            # Pattern 10: set_single_value calls
            self._check_set_single_value_patterns(file_path, content, lines)
            
            # Pattern 11: set_value calls
            self._check_set_value_patterns(file_path, content, lines)
            
            # Pattern 12: SQL WHERE/ORDER BY/GROUP BY fields
            self._check_sql_field_patterns(file_path, content, lines)
            
            # Pattern 13: Report column/filter definitions
            self._check_report_field_patterns(file_path, content, lines)
            
            # Pattern 14: Meta field validation calls
            self._check_meta_field_patterns(file_path, content, lines)
            
        except Exception as e:
            print(f"Error validating {file_path}: {e}")
    
    def _validate_template_file(self, file_path: Path):
        """Validate HTML template files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            # Check Jinja2 template variables
            self._check_template_variables(file_path, content, lines)
            
            # Check email template field variables
            self._check_email_template_variables(file_path, content, lines)
            
        except Exception as e:
            print(f"Error validating template {file_path}: {e}")
    
    def _validate_javascript_file(self, file_path: Path):
        """Validate JavaScript files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
            
            # Check object property access
            self._check_js_property_access(file_path, content, lines)
            
        except Exception as e:
            print(f"Error validating JavaScript {file_path}: {e}")
    
    def _check_getattr_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check getattr() function calls"""
        pattern = r'getattr\([^,]+,\s*["\']([^"\']+)["\']'
        
        for match in re.finditer(pattern, content):
            field_name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            doctype = self._guess_doctype_from_context(content, match.start())
            
            if self._is_deprecated_field(field_name, doctype):
                self.issues.append(ValidationIssue(
                    file=str(file_path.relative_to(self.app_path)),
                    line=line_num,
                    field=field_name,
                    doctype=doctype or "Unknown",
                    reference=f"getattr(..., '{field_name}')",
                    message=f"Deprecated field '{field_name}' accessed via getattr()",
                    context=lines[line_num - 1].strip(),
                    confidence="high",
                    issue_type="deprecated_field_access",
                    suggested_fix=self._get_suggested_fix(field_name, doctype)
                ))
    
    def _check_attribute_access(self, file_path: Path, content: str, lines: List[str]):
        """Check direct attribute access"""
        # Look for obj.field_name patterns
        pattern = r'(\w+)\.([a-zA-Z_][a-zA-Z0-9_]*)'
        
        for match in re.finditer(pattern, content):
            obj_name = match.group(1)
            field_name = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            
            doctype = self._guess_doctype_from_context(content, match.start(), obj_name)
            
            if self._is_deprecated_field(field_name, doctype):
                self.issues.append(ValidationIssue(
                    file=str(file_path.relative_to(self.app_path)),
                    line=line_num,
                    field=field_name,
                    doctype=doctype or "Unknown",
                    reference=f"{obj_name}.{field_name}",
                    message=f"Deprecated field '{field_name}' accessed directly",
                    context=lines[line_num - 1].strip(),
                    confidence="high" if doctype else "medium",
                    issue_type="deprecated_field_access",
                    suggested_fix=self._get_suggested_fix(field_name, doctype)
                ))
    
    def _check_field_lists(self, file_path: Path, content: str, lines: List[str]):
        """Check field lists in frappe.get_all() and similar queries"""
        # Pattern for fields parameter in frappe.get_all
        pattern = r'fields\s*=\s*\[(.*?)\]'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            fields_content = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            # Extract individual field names
            field_pattern = r'["\']([^"\']+)["\']'
            for field_match in re.finditer(field_pattern, fields_content):
                field_name = field_match.group(1)
                
                if self._is_deprecated_field(field_name):
                    doctype = self._guess_doctype_from_context(content, match.start())
                    
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype or "Unknown",
                        reference=f"fields=[..., '{field_name}', ...]",
                        message=f"Deprecated field '{field_name}' in query field list",
                        context=lines[line_num - 1].strip(),
                        confidence="high",
                        issue_type="deprecated_field_query",
                        suggested_fix=self._get_suggested_fix(field_name, doctype)
                    ))
    
    def _check_sql_queries(self, file_path: Path, content: str, lines: List[str]):
        """Check SQL queries for deprecated fields"""
        # Look for SQL keywords followed by deprecated fields
        sql_pattern = r'(SELECT|FROM|WHERE|ORDER BY|GROUP BY|UPDATE|INSERT)\s+.*?([a-zA-Z_][a-zA-Z0-9_]*)'
        
        for line_num, line in enumerate(lines, 1):
            for deprecated_field in self._get_all_deprecated_fields():
                if deprecated_field in line and any(keyword in line.upper() for keyword in ['SELECT', 'FROM', 'WHERE', 'ORDER', 'GROUP', 'UPDATE', 'INSERT']):
                    
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=deprecated_field,
                        doctype="Unknown",
                        reference=f"SQL: {deprecated_field}",
                        message=f"Deprecated field '{deprecated_field}' in SQL query",
                        context=line.strip(),
                        confidence="medium",
                        issue_type="deprecated_field_sql",
                        suggested_fix=f"Replace with appropriate field from dues schedule system"
                    ))
    
    def _check_database_operations(self, file_path: Path, content: str, lines: List[str]):
        """Check database operations like db_set, db_get"""
        patterns = [
            r'\.db_set\(["\']([^"\']+)["\']',
            r'\.db_get\(["\']([^"\']+)["\']',
            r'frappe\.db\.set_value\([^,]+,\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                if self._is_deprecated_field(field_name):
                    doctype = self._guess_doctype_from_context(content, match.start())
                    
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype or "Unknown",
                        reference=f"db operation: {field_name}",
                        message=f"Deprecated field '{field_name}' in database operation",
                        context=lines[line_num - 1].strip(),
                        confidence="high",
                        issue_type="deprecated_field_db_operation",
                        suggested_fix=self._get_suggested_fix(field_name, doctype)
                    ))
    
    def _check_get_single_value_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check get_single_value calls for Singles doctypes"""
        patterns = [
            # frappe.db.get_single_value("DocType", "field")
            r'frappe\.db\.get_single_value\(["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']',
            # frappe.get_single_value("DocType", "field")
            r'frappe\.get_single_value\(["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']',
            # doc.get_single_value("field")
            r'\.get_single_value\(["\']([^"\']+)["\']'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                if match.lastindex == 2:  # Pattern with doctype and field
                    doctype = match.group(1)
                    field_name = match.group(2)
                else:  # Pattern with just field
                    doctype = self._guess_doctype_from_context(content, match.start())
                    field_name = match.group(1)
                
                line_num = content[:match.start()].count('\n') + 1
                
                # Check if this is a Singles doctype and if the field exists
                if doctype and doctype in self.doctypes:
                    doctype_fields = self.doctypes.get(doctype, {})
                    if isinstance(doctype_fields, dict):
                        fields = doctype_fields.get('fields', set())
                    else:
                        fields = doctype_fields
                    
                    if field_name not in fields and not self._is_standard_field(field_name):
                        self.issues.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"get_single_value: {field_name}",
                            message=f"Field '{field_name}' does not exist in Singles doctype '{doctype}'",
                            context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                            confidence="high",
                            issue_type="missing_singles_field",
                            suggested_fix=f"Add field '{field_name}' to {doctype} doctype or use an existing field"
                        ))
    
    def _check_filter_dictionary_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check database filter dictionary patterns"""
        # Pattern: frappe.get_all("DocType", filters={"field": "value"})
        filter_patterns = [
            r'frappe\.(?:db\.)?(?:get_all|get_list|get_value|exists|count)\(\s*["\']([^"\']+)["\']\s*,\s*[^)]*filters\s*=\s*(\{[^}]+\})',
            r'frappe\.(?:db\.)?(?:get_all|get_list|get_value|exists|count)\(\s*["\']([^"\']+)["\']\s*,\s*filters\s*=\s*(\{[^}]+\})',
        ]
        
        for pattern in filter_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                doctype = match.group(1)
                filter_dict_str = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                # Extract field names from the filter dictionary
                field_matches = re.findall(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', filter_dict_str)
                
                if doctype in self.doctypes:
                    doctype_fields = self.doctypes.get(doctype, {})
                    if isinstance(doctype_fields, dict):
                        fields = doctype_fields.get('fields', set())
                    else:
                        fields = doctype_fields
                    
                    for field_name in field_matches:
                        if field_name not in fields and not self._is_standard_field(field_name):
                            self.issues.append(ValidationIssue(
                                file=str(file_path.relative_to(self.app_path)),
                                line=line_num,
                                field=field_name,
                                doctype=doctype,
                                reference=f"filter dict: {field_name}",
                                message=f"Field '{field_name}' in filter dictionary does not exist in '{doctype}'",
                                context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                                confidence="high",
                                issue_type="missing_filter_field",
                                suggested_fix=f"Add field '{field_name}' to {doctype} doctype or check field name"
                            ))
    
    def _check_child_table_field_access(self, file_path: Path, content: str, lines: List[str]):
        """Check child table field access patterns"""
        # Pattern: for row in doc.table: value = row.field_name
        child_access_patterns = [
            r'for\s+(\w+)\s+in\s+[^:]+:\s*[^=]*\1\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'(\w+)\.([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=|==|!=|in|not\s+in)',
        ]
        
        for pattern in child_access_patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                var_name = match.group(1)
                field_name = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                # Skip common non-field patterns
                if field_name in {'name', 'idx', 'append', 'insert', 'remove', 'get', 'set', 'update', 'save', 'delete'}:
                    continue
                
                # Try to determine if this is a child table access
                context_before = content[max(0, match.start() - 200):match.start()]
                if 'for' in context_before and 'in' in context_before:
                    # This looks like child table access - we'd need more sophisticated detection
                    # For now, flag as potential issue with lower confidence
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype="Unknown Child Table",
                        reference=f"child table access: {var_name}.{field_name}",
                        message=f"Potential child table field '{field_name}' access - verify field exists",
                        context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                        confidence="medium",
                        issue_type="potential_child_table_field",
                        suggested_fix=f"Verify that field '{field_name}' exists in the child table"
                    ))
    
    def _check_set_single_value_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check set_single_value calls for Singles doctypes"""
        patterns = [
            # frappe.db.set_single_value("DocType", "field", "value")
            r'frappe\.db\.set_single_value\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,',
            # frappe.set_single_value("DocType", "field", "value")
            r'frappe\.set_single_value\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                doctype = match.group(1)
                field_name = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                # Check if this is a Singles doctype and if the field exists
                if doctype in self.doctypes:
                    doctype_fields = self.doctypes.get(doctype, {})
                    if isinstance(doctype_fields, dict):
                        fields = doctype_fields.get('fields', set())
                    else:
                        fields = doctype_fields
                    
                    if field_name not in fields and not self._is_standard_field(field_name):
                        self.issues.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"set_single_value: {field_name}",
                            message=f"Field '{field_name}' does not exist in Singles doctype '{doctype}'",
                            context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                            confidence="high",
                            issue_type="missing_singles_field_write",
                            suggested_fix=f"Add field '{field_name}' to {doctype} doctype or use an existing field"
                        ))
    
    def _check_set_value_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check frappe.db.set_value calls"""
        patterns = [
            # frappe.db.set_value("DocType", "name", "field", "value")
            r'frappe\.db\.set_value\(\s*["\']([^"\']+)["\']\s*,\s*[^,]+,\s*["\']([^"\']+)["\']\s*,',
            # frappe.db.set_value("DocType", "name", {"field": "value"})
            r'frappe\.db\.set_value\(\s*["\']([^"\']+)["\']\s*,\s*[^,]+,\s*(\{[^}]+\})',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                doctype = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                if match.lastindex >= 3 and match.group(3):  # Dictionary pattern
                    # Extract field names from dictionary
                    dict_str = match.group(3)
                    field_matches = re.findall(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', dict_str)
                else:  # Single field pattern
                    field_matches = [match.group(2)]
                
                if doctype in self.doctypes:
                    doctype_fields = self.doctypes.get(doctype, {})
                    if isinstance(doctype_fields, dict):
                        fields = doctype_fields.get('fields', set())
                    else:
                        fields = doctype_fields
                    
                    for field_name in field_matches:
                        if field_name not in fields and not self._is_standard_field(field_name):
                            self.issues.append(ValidationIssue(
                                file=str(file_path.relative_to(self.app_path)),
                                line=line_num,
                                field=field_name,
                                doctype=doctype,
                                reference=f"set_value: {field_name}",
                                message=f"Field '{field_name}' does not exist in '{doctype}'",
                                context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                                confidence="high",
                                issue_type="missing_set_value_field",
                                suggested_fix=f"Add field '{field_name}' to {doctype} doctype or check field name"
                            ))
    
    def _check_dictionary_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check dictionary access patterns"""
        patterns = [
            r'\.get\(["\']([^"\']+)["\']',  # dict.get('field')
            r'\[["\']([^"\']+)["\']\]',     # dict['field']
            r'["\']([^"\']+)["\']\s*:',     # 'field': value
            r'"([^"]+)"\s*:\s*[^,}]+',      # "field": value (in return statements)
            r"'([^']+)'\s*:\s*[^,}]+",      # 'field': value (in return statements)
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                if self._is_deprecated_field(field_name):
                    doctype = self._guess_doctype_from_context(content, match.start())
                    
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype or "Unknown", 
                        reference=f"dict access: {field_name}",
                        message=f"Deprecated field '{field_name}' in dictionary operation",
                        context=lines[line_num - 1].strip(),
                        confidence="high" if "return" in lines[line_num - 1] else "medium",
                        issue_type="deprecated_field_dict_access",
                        suggested_fix=self._get_suggested_fix(field_name, doctype)
                    ))
    
    def _check_template_variables(self, file_path: Path, content: str, lines: List[str]):
        """Check Jinja2 template variables"""
        patterns = [
            r'\{\{.*?\.([a-zA-Z_][a-zA-Z0-9_]*).*?\}\}',  # {{ obj.field }}
            r'\{%\s*if\s+.*?\.([a-zA-Z_][a-zA-Z0-9_]*).*?%\}',  # {% if obj.field %}
            r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}',  # {{ field }}
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                if self._is_deprecated_field(field_name):
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype="Unknown",
                        reference=f"template: {field_name}",
                        message=f"Deprecated field '{field_name}' in template",
                        context=lines[line_num - 1].strip(),
                        confidence="high",
                        issue_type="deprecated_field_template",
                        suggested_fix=f"Update template to use current field name"
                    ))
    
    def _check_js_property_access(self, file_path: Path, content: str, lines: List[str]):
        """Check JavaScript object property access"""
        pattern = r'(\w+)\.([a-zA-Z_][a-zA-Z0-9_]*)'
        
        for match in re.finditer(pattern, content):
            field_name = match.group(2)
            line_num = content[:match.start()].count('\n') + 1
            
            if self._is_deprecated_field(field_name):
                self.issues.append(ValidationIssue(
                    file=str(file_path.relative_to(self.app_path)),
                    line=line_num,
                    field=field_name,
                    doctype="Unknown",
                    reference=f"JS: {field_name}",
                    message=f"Deprecated field '{field_name}' in JavaScript",
                    context=lines[line_num - 1].strip(),
                    confidence="medium",
                    issue_type="deprecated_field_js",
                    suggested_fix=f"Update JavaScript to use current field name"
                ))
    
    def _check_sql_field_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check SQL WHERE/ORDER BY/GROUP BY field references"""
        # Patterns for SQL clauses with field names
        sql_patterns = [
            r'WHERE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[=<>!]',  # WHERE field =
            r'ORDER\s+BY\s+([a-zA-Z_][a-zA-Z0-9_]*)',      # ORDER BY field
            r'GROUP\s+BY\s+([a-zA-Z_][a-zA-Z0-9_]*)',      # GROUP BY field
            r'FROM\s+tab\w+\s+WHERE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[=<>!]',  # FROM tabDoc WHERE field
            r'SELECT\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*,',     # SELECT field,
            r',\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+FROM',        # , field FROM
        ]
        
        for pattern in sql_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Skip SQL keywords and common non-field words
                if field_name.upper() in ['SELECT', 'FROM', 'WHERE', 'ORDER', 'GROUP', 'BY', 'AND', 'OR', 'NOT',
                                          'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'AS', 'LIKE', 'IN',
                                          'BETWEEN', 'IS', 'NULL', 'ASC', 'DESC', 'LIMIT', 'OFFSET']:
                    continue
                
                # Try to determine doctype from context
                doctype = self._guess_doctype_from_sql_context(content, match.start())
                
                if doctype and self._is_deprecated_field(field_name, doctype):
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype,
                        reference=f"SQL field: {field_name}",
                        message=f"Deprecated field '{field_name}' in SQL query for {doctype}",
                        context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                        confidence="high",
                        issue_type="deprecated_field_sql_clause",
                        suggested_fix=self._get_suggested_fix(field_name, doctype)
                    ))
    
    def _check_report_field_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check report column/filter field definitions"""
        # Patterns for report configurations
        report_patterns = [
            r'columns\s*=\s*\[.*?{.*?"fieldname"\s*:\s*["\']([^"\']*)["\']',  # columns = [{"fieldname": "field"}
            r'filters\s*=\s*\[.*?{.*?"fieldname"\s*:\s*["\']([^"\']*)["\']',  # filters = [{"fieldname": "field"}
            r'{\s*["\']fieldname["\']\s*:\s*["\']([^"\']*)["\']',              # {"fieldname": "field"}
            r'"fieldname"\s*:\s*["\']([^"\']*)["\']',                        # "fieldname": "field"
        ]
        
        for pattern in report_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Try to determine doctype from report context
                doctype = self._guess_doctype_from_report_context(content, match.start())
                
                if doctype and self._is_deprecated_field(field_name, doctype):
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype,
                        reference=f"report field: {field_name}",
                        message=f"Deprecated field '{field_name}' in report configuration for {doctype}",
                        context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                        confidence="high",
                        issue_type="deprecated_field_report_config",
                        suggested_fix=self._get_suggested_fix(field_name, doctype)
                    ))
    
    def _check_meta_field_patterns(self, file_path: Path, content: str, lines: List[str]):
        """Check meta field validation calls"""
        # Patterns for meta field access
        meta_patterns = [
            r'frappe\.get_meta\(["\']([^"\']*)["\']?\)\.get_field\(["\']([^"\']*)["\']?\)',  # get_meta("DocType").get_field("field")
            r'frappe\.get_meta\(["\']([^"\']*)["\']?\)\.has_field\(["\']([^"\']*)["\']?\)',  # get_meta("DocType").has_field("field")
            r'meta\.get_field\(["\']([^"\']*)["\']?\)',                                    # meta.get_field("field")
            r'meta\.has_field\(["\']([^"\']*)["\']?\)',                                    # meta.has_field("field")
        ]
        
        for pattern in meta_patterns:
            for match in re.finditer(pattern, content):
                if match.lastindex == 2:  # Pattern with doctype and field
                    doctype = match.group(1)
                    field_name = match.group(2)
                else:  # Pattern with just field (meta variable context)
                    field_name = match.group(1)
                    doctype = self._guess_doctype_from_meta_context(content, match.start())
                
                line_num = content[:match.start()].count('\n') + 1
                
                if doctype and self._is_deprecated_field(field_name, doctype):
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype,
                        reference=f"meta field: {field_name}",
                        message=f"Deprecated field '{field_name}' in meta field access for {doctype}",
                        context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                        confidence="high",
                        issue_type="deprecated_field_meta_access",
                        suggested_fix=self._get_suggested_fix(field_name, doctype)
                    ))
    
    def _check_email_template_variables(self, file_path: Path, content: str, lines: List[str]):
        """Check email template field variables in HTML files"""
        # Enhanced patterns for Jinja2 template variables
        template_patterns = [
            r'\{\{\s*doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}',                    # {{ doc.field }}
            r'\{\{\s*doc\.([a-zA-Z_][a-zA-Z0-9_]*)\|[^}]*\}\}',               # {{ doc.field|filter }}
            r'\{%\s*if\s+doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*%\}',               # {% if doc.field %}
            r'\{%\s*for\s+\w+\s+in\s+doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*%\}',   # {% for item in doc.field %}
            r'\{%\s*set\s+\w+\s*=\s*doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*%\}',   # {% set var = doc.field %}
        ]
        
        for pattern in template_patterns:
            for match in re.finditer(pattern, content):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Try to determine doctype from template context
                doctype = self._guess_doctype_from_template_context(content, match.start())
                
                if doctype and self._is_deprecated_field(field_name, doctype):
                    confidence = "medium"  # Template variables can have false positives
                    self.issues.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field_name,
                        doctype=doctype,
                        reference=f"template var: doc.{field_name}",
                        message=f"Deprecated field '{field_name}' in email template for {doctype}",
                        context=lines[line_num - 1].strip() if line_num <= len(lines) else "",
                        confidence=confidence,
                        issue_type="deprecated_field_email_template",
                        suggested_fix=self._get_suggested_fix(field_name, doctype)
                    ))
    
    def _is_deprecated_field(self, field_name: str, doctype: str = None) -> bool:
        """Check if a field is deprecated for a specific doctype"""
        if doctype and doctype in self.deprecated_fields:
            return field_name in self.deprecated_fields[doctype]
        
        # For general checks without doctype context, only flag if deprecated in any doctype
        for dt, fields in self.deprecated_fields.items():
            if field_name in fields:
                return True
        return False
    
    def _get_all_deprecated_fields(self) -> List[str]:
        """Get all deprecated field names"""
        all_fields = []
        for fields in self.deprecated_fields.values():
            all_fields.extend(fields)
        return all_fields
    
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
    
    def _guess_doctype_from_sql_context(self, content: str, position: int) -> Optional[str]:
        """Guess DocType from SQL context"""
        context_before = content[max(0, position - 300):position]
        
        # Look for table references in SQL
        table_patterns = [
            r'FROM\s+`?tab([^`\s]+)`?',
            r'JOIN\s+`?tab([^`\s]+)`?',
            r'UPDATE\s+`?tab([^`\s]+)`?',
            r'INSERT\s+INTO\s+`?tab([^`\s]+)`?',
        ]
        
        for pattern in table_patterns:
            matches = list(re.finditer(pattern, context_before, re.IGNORECASE))
            if matches:
                return matches[-1].group(1)
        
        return None
    
    def _guess_doctype_from_report_context(self, content: str, position: int) -> Optional[str]:
        """Guess DocType from report context"""
        context_before = content[max(0, position - 500):position]
        
        # Look for report doctype references
        report_patterns = [
            r'ref_doctype["\']?\s*:\s*["\']([^"\']*)["\']',
            r'"ref_doctype"\s*:\s*["\']([^"\']*)["\']',
            r'doctype["\']?\s*:\s*["\']([^"\']*)["\']',
            r'get_all\(["\']([^"\']*)["\']',
        ]
        
        for pattern in report_patterns:
            matches = list(re.finditer(pattern, context_before))
            if matches:
                return matches[-1].group(1)
        
        return None
    
    def _guess_doctype_from_meta_context(self, content: str, position: int) -> Optional[str]:
        """Guess DocType from meta context"""
        context_before = content[max(0, position - 200):position]
        
        # Look for meta variable assignments
        meta_patterns = [
            r'meta\s*=\s*frappe\.get_meta\(["\']([^"\']*)["\']?\)',
            r'get_meta\(["\']([^"\']*)["\']?\)',
        ]
        
        for pattern in meta_patterns:
            matches = list(re.finditer(pattern, context_before))
            if matches:
                return matches[-1].group(1)
        
        return None
    
    def _guess_doctype_from_template_context(self, content: str, position: int) -> Optional[str]:
        """Guess DocType from template context"""
        # Look for HTML comments or template headers that indicate doctype
        context_before = content[max(0, position - 800):position]
        
        template_patterns = [
            r'<!--\s*([A-Z][a-zA-Z\s]+)\s*template\s*-->',
            r'{{.*?doctype.*?["\']([^"\']*)["\'].*?}}',
            r'{%\s*set.*?doctype.*?["\']([^"\']*)["\'].*?%}',
        ]
        
        for pattern in template_patterns:
            matches = list(re.finditer(pattern, context_before, re.IGNORECASE))
            if matches:
                doctype_name = matches[-1].group(1).strip()
                # Clean up doctype name
                if doctype_name.replace(' ', '') in self.doctypes:
                    return doctype_name.replace(' ', '')
        
        return None
    
    def _is_standard_field(self, field_name: str) -> bool:
        """Check if field is a standard Frappe field"""
        standard_fields = {
            'name', 'creation', 'modified', 'modified_by', 'owner',
            'docstatus', 'parent', 'parentfield', 'parenttype', 'idx',
            'doctype', '_user_tags', '_comments', '_assign', '_liked_by'
        }
        return field_name in standard_fields
    
    def _get_suggested_fix(self, field_name: str, doctype: str) -> Optional[str]:
        """Get suggested fix for deprecated field"""
        if field_name == "next_billing_date":
            return "Use next_invoice_date from Membership Dues Schedule"
        elif field_name == "chapter" and doctype == "Member":
            return "Use Chapter Member relationship or current_chapter_display field"
        elif field_name == "event_type":
            return "Use process_type field"
        elif field_name == "severity":
            return "Use compliance_status field"
        elif field_name == "ip_address":
            return "Use action field"
        return None
    
    def print_report(self):
        """Print validation report"""
        if not self.issues:
            print("✅ No deprecated field references found!")
            return
        
        # Group by confidence level
        high_confidence = [i for i in self.issues if i.confidence == "high"]
        medium_confidence = [i for i in self.issues if i.confidence == "medium"]
        
        print(f"🚨 Found {len(self.issues)} deprecated field references:")
        print(f"   🔴 High confidence: {len(high_confidence)}")
        print(f"   🟡 Medium confidence: {len(medium_confidence)}")
        
        if high_confidence:
            print(f"\n🔴 HIGH CONFIDENCE ISSUES:")
            for issue in high_confidence:
                print(f"   {issue.file}:{issue.line} - {issue.field} ({issue.issue_type})")
                print(f"      {issue.message}")
                if issue.suggested_fix:
                    print(f"      💡 Fix: {issue.suggested_fix}")
        
        if medium_confidence:
            print(f"\n🟡 MEDIUM CONFIDENCE ISSUES:")
            for issue in medium_confidence[:10]:  # Limit output
                print(f"   {issue.file}:{issue.line} - {issue.field} ({issue.issue_type})")

if __name__ == "__main__":
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = EnhancedFieldValidator(app_path)
    
    print("🔍 Running Enhanced Field Validation...")
    issues = validator.validate_all_files()
    
    validator.print_report()
    
    # Exit with error code if critical issues found
    high_confidence_issues = [i for i in issues if i.confidence == "high"]
    if high_confidence_issues:
        print(f"\n❌ Validation failed: {len(high_confidence_issues)} critical issues found")
        sys.exit(1)
    else:
        print(f"\n✅ Validation passed")
        sys.exit(0)