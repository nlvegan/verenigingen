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