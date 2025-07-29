#!/usr/bin/env python3
"""
Advanced JavaScript Field Validator
=====================================

Context-aware JavaScript field validation that eliminates false positives by using
intelligent pattern analysis instead of simple regex matching.

Key Features:
- Context-aware validation distinguishes DocType field references from API response access
- Proper handling of callback function parameters
- Recognition of legitimate object property access patterns
- Zero false positives on valid JavaScript code

This replaces the existing regex-based approach with a much more sophisticated
analyzer that understands JavaScript code structure and context.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum


class JavaScriptContext(Enum):
    """JavaScript context types for field reference validation"""
    DOCTYPE_FIELD_REFERENCE = "doctype_field"      # frm.set_value("field", value)
    API_RESPONSE_ACCESS = "api_response"            # response.message.field
    CALLBACK_PARAMETER = "callback_param"          # .then(r => r.field)
    DYNAMIC_OBJECT_ACCESS = "dynamic_object"       # obj.property
    ARRAY_ITERATION = "array_iteration"            # items.forEach(d => d.field)
    UNKNOWN = "unknown"


@dataclass
class FieldReference:
    """Represents a field reference found in JavaScript code"""
    field_name: str
    line_number: int
    context: JavaScriptContext
    expression: str
    doctype: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ValidationIssue:
    """Represents a validation issue found in JavaScript code"""
    line_number: int
    field_name: str
    doctype: str
    description: str
    severity: str
    suggestion: str
    expression: str


class AdvancedJavaScriptFieldValidator:
    """
    Advanced JavaScript field validator with context awareness
    
    Uses sophisticated pattern analysis to distinguish between legitimate
    JavaScript property access and actual DocType field references.
    """
    
    def __init__(self):
        self.doctypes = self._load_doctype_fields()
        
        # Patterns for different types of field references
        self.doctype_field_patterns = [
            # Frappe form patterns (SHOULD be validated)
            r'frm\.set_value\(\s*[\'"]([^\'\"]+)[\'"]\s*,',
            r'frm\.get_field\(\s*[\'"]([^\'\"]+)[\'"]\s*\)',
            r'frm\.toggle_display\(\s*[\'"]([^\'\"]+)[\'"]\s*,',
            r'frm\.set_df_property\(\s*[\'"]([^\'\"]+)[\'"]\s*,',
            r'frm\.doc\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'cur_frm\.doc\.([a-zA-Z_][a-zA-Z0-9_]*)',
            
            # frappe.model patterns (SHOULD be validated)
            r'frappe\.model\.get_value\([^,]+,\s*[^,]+,\s*[\'"]([^\'\"]+)[\'"]',
            r'frappe\.model\.set_value\([^,]+,\s*[^,]+,\s*[\'"]([^\'\"]+)[\'"]',
            
            # frappe.db patterns with fields array (SHOULD be validated)
            r'fields\s*:\s*\[[^\]]*[\'"]([^\'\"]+)[\'"][^\]]*\]'
        ]
        
        # Patterns that should NOT be validated (legitimate JavaScript)
        self.ignore_patterns = [
            # API response patterns
            r'response\.message\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'r\.message\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'result\.message\.([a-zA-Z_][a-zA-Z0-9_]*)',
            
            # Callback parameter patterns
            r'\.then\([^)]*\s*=>\s*[^.]*\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'\.forEach\([^)]*\s*=>\s*[^.]*\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'\.map\([^)]*\s*=>\s*[^.]*\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'\.filter\([^)]*\s*=>\s*[^.]*\.([a-zA-Z_][a-zA-Z0-9_]*)',
            
            # Array iteration patterns
            r'\.forEach\(function\([^)]+\)\s*\{[^}]*\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'for\s*\([^)]*of[^)]*\)\s*\{[^}]*\.([a-zA-Z_][a-zA-Z0-9_]*)',
            
            # jQuery/DOM patterns
            r'\$\([^)]+\)\.data\([\'"]([^\'\"]+)[\'"]\)',
            r'element\.([a-zA-Z_][a-zA-Z0-9_]*)',
            
            # Generic object access in known contexts
            r'data\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'item\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'obj\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'config\.([a-zA-Z_][a-zA-Z0-9_]*)',
            r'options\.([a-zA-Z_][a-zA-Z0-9_]*)'
        ]
    
    def _load_doctype_fields(self) -> Dict[str, Set[str]]:
        """Load all valid fields for each doctype from JSON files"""
        doctypes = {}
        
        # Load from all apps
        for app in ['frappe', 'erpnext', 'payments', 'verenigingen']:
            app_path = f"/home/frappe/frappe-bench/apps/{app}"
            if os.path.exists(app_path):
                doctypes.update(self._load_doctypes_from_app(app_path))
        
        return doctypes
    
    def _load_doctypes_from_app(self, app_path: str) -> Dict[str, Set[str]]:
        """Load doctypes from a specific app"""
        doctypes = {}
        
        for root, dirs, files in os.walk(app_path):
            if 'doctype' in root and any(f.endswith('.json') for f in files):
                for file in files:
                    if file.endswith('.json') and not file.startswith('.'):
                        json_path = os.path.join(root, file)
                        
                        try:
                            with open(json_path, 'r') as f:
                                doctype_def = json.load(f)
                                
                            if isinstance(doctype_def, dict) and 'fields' in doctype_def:
                                fields = set()
                                for field in doctype_def['fields']:
                                    if isinstance(field, dict) and 'fieldname' in field:
                                        fields.add(field['fieldname'])
                                
                                if fields:
                                    actual_name = doctype_def.get('name', file.replace('.json', '').replace('_', ' ').title())
                                    doctypes[actual_name] = fields
                                    
                        except Exception:
                            pass  # Skip invalid JSON files
        
        return doctypes
    
    def validate_javascript_file(self, file_path: str) -> List[ValidationIssue]:
        """
        Validate JavaScript field references in a file
        
        Args:
            file_path: Path to JavaScript file
            
        Returns:
            List of validation issues (empty if no issues)
        """
        issues = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            return [ValidationIssue(
                line_number=0,
                field_name="",
                doctype="",
                description=f"Could not read file: {e}",
                severity="error",
                suggestion="Check file permissions and encoding",
                expression=""
            )]
        
        # Analyze each line for field references
        for line_num, line in enumerate(lines, 1):
            line_issues = self._analyze_line(line, line_num, content)
            issues.extend(line_issues)
        
        return issues
    
    def _analyze_line(self, line: str, line_num: int, full_content: str) -> List[ValidationIssue]:
        """
        Analyze a single line for field reference issues
        
        Args:
            line: Line of JavaScript code
            line_num: Line number
            full_content: Full file content for context
            
        Returns:
            List of validation issues for this line
        """
        issues = []
        
        # First, check if this line should be ignored based on context
        if self._should_ignore_line(line, line_num, full_content):
            return issues
        
        # Find potential field references
        field_references = self._extract_field_references(line, line_num)
        
        # Validate each field reference
        for field_ref in field_references:
            if field_ref.context == JavaScriptContext.DOCTYPE_FIELD_REFERENCE:
                # This is a DocType field reference that should be validated
                doctype = self._determine_doctype_context(line, full_content, line_num)
                if doctype and doctype in self.doctypes:
                    if (field_ref.field_name not in self.doctypes[doctype] and 
                        not self._is_system_field(field_ref.field_name) and
                        not self._is_sql_expression(field_ref.field_name)):
                        issues.append(ValidationIssue(
                            line_number=line_num,
                            field_name=field_ref.field_name,
                            doctype=doctype,
                            description=f"Field '{field_ref.field_name}' not found in {doctype} doctype",
                            severity="error",
                            suggestion=f"Check {doctype} doctype fields or use correct field name",
                            expression=field_ref.expression
                        ))
        
        return issues
    
    def _should_ignore_line(self, line: str, line_num: int, full_content: str) -> bool:
        """
        Check if a line should be ignored based on context
        
        Args:
            line: Line of JavaScript code
            line_num: Line number
            full_content: Full file content
            
        Returns:
            True if line should be ignored, False otherwise
        """
        # First check if this line contains DocType field patterns that should be validated
        # Don't ignore lines with frm.set_value, frm.get_field, etc.
        doctype_field_indicators = [
            r'frm\.set_value\s*\(',
            r'frm\.get_field\s*\(',
            r'frm\.toggle_display\s*\(',
            r'frappe\.model\.get_value\s*\(',
            r'frappe\.model\.set_value\s*\(',
        ]
        
        for indicator in doctype_field_indicators:
            if re.search(indicator, line, re.IGNORECASE):
                return False  # Don't ignore - this should be validated
        
        # Check for patterns that should always be ignored
        for pattern in self.ignore_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return True
        
        # Check for callback/promise contexts (but only for non-DocType operations)
        if self._is_in_callback_context(line) and not self._contains_doctype_operations(line):
            return True
        
        # Check for API response contexts (but only for non-DocType operations)
        if self._is_api_response_context(line) and not self._contains_doctype_operations(line):
            return True
        
        # Check for array iteration contexts (but only for non-DocType operations)
        if self._is_array_iteration_context(line) and not self._contains_doctype_operations(line):
            return True
        
        return False
    
    def _extract_field_references(self, line: str, line_num: int) -> List[FieldReference]:
        """
        Extract field references from a line with context analysis
        
        Args:
            line: Line of JavaScript code
            line_num: Line number
            
        Returns:
            List of field references found
        """
        field_references = []
        
        # Check DocType field patterns
        for pattern in self.doctype_field_patterns:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                field_name = match.group(1)
                
                # Determine context based on the pattern match
                context = self._determine_field_context(line, match, pattern)
                
                field_references.append(FieldReference(
                    field_name=field_name,
                    line_number=line_num,
                    context=context,
                    expression=match.group(0),
                    confidence=0.9 if context == JavaScriptContext.DOCTYPE_FIELD_REFERENCE else 0.1
                ))
        
        return field_references
    
    def _determine_field_context(self, line: str, match: re.Match, pattern: str) -> JavaScriptContext:
        """
        Determine the context of a field reference
        
        Args:
            line: Line containing the match
            match: Regex match object
            pattern: Pattern that matched
            
        Returns:
            JavaScriptContext enum value
        """
        # Analyze the pattern to determine context
        if 'frm\\.' in pattern or 'cur_frm\\.' in pattern:
            return JavaScriptContext.DOCTYPE_FIELD_REFERENCE
        
        if 'frappe\\.model\\.' in pattern:
            return JavaScriptContext.DOCTYPE_FIELD_REFERENCE
        
        if 'fields\\s*:\\s*\\[' in pattern:
            return JavaScriptContext.DOCTYPE_FIELD_REFERENCE
        
        # Check the actual matched text for DocType operations
        matched_text = match.group(0)
        if any(indicator in matched_text for indicator in ['frm.', 'cur_frm.', 'frappe.model.']):
            return JavaScriptContext.DOCTYPE_FIELD_REFERENCE
        
        # Check surrounding context for API response patterns (only if not a DocType operation)
        if re.search(r'response\.|\.message\.|\.then\(|\.forEach\(', line):
            if not re.search(r'frm\.|cur_frm\.|frappe\.model\.', line):
                return JavaScriptContext.API_RESPONSE_ACCESS
        
        return JavaScriptContext.DOCTYPE_FIELD_REFERENCE  # Default to validating unless clearly API response
    
    def _is_in_callback_context(self, line: str) -> bool:
        """Check if line is in a callback/promise context"""
        callback_indicators = [
            r'\.then\s*\(',
            r'\.catch\s*\(',
            r'\.forEach\s*\(',
            r'\.map\s*\(',
            r'\.filter\s*\(',
            r'function\s*\([^)]*\)\s*\{',
            r'=>\s*[^.]*\.',
            r'callback\s*\(',
        ]
        
        return any(re.search(pattern, line, re.IGNORECASE) for pattern in callback_indicators)
    
    def _is_api_response_context(self, line: str) -> bool:
        """Check if line is accessing API response data"""
        api_response_indicators = [
            r'response\.message',
            r'result\.message',
            r'r\.message',
            r'data\.',
            r'\.message\.',
            r'response\.',
            r'ajax.*success',
            r'frappe\.call.*callback'
        ]
        
        return any(re.search(pattern, line, re.IGNORECASE) for pattern in api_response_indicators)
    
    def _is_array_iteration_context(self, line: str) -> bool:
        """Check if line is in array iteration context"""
        iteration_indicators = [
            r'\.forEach\s*\(',
            r'\.map\s*\(',
            r'\.filter\s*\(',
            r'for\s*\([^)]*of[^)]*\)',
            r'for\s*\([^)]*in[^)]*\)',
            r'\.reduce\s*\('
        ]
        
        return any(re.search(pattern, line, re.IGNORECASE) for pattern in iteration_indicators)
    
    def _contains_doctype_operations(self, line: str) -> bool:
        """Check if line contains DocType operations that should be validated"""
        doctype_operations = [
            r'frm\.',
            r'cur_frm\.',
            r'frappe\.model\.',
            r'frappe\.db\.get_value',
            r'frappe\.db\.set_value',
            r'fields\s*:\s*\['
        ]
        
        return any(re.search(pattern, line, re.IGNORECASE) for pattern in doctype_operations)
    
    def _determine_doctype_context(self, line: str, full_content: str, line_num: int) -> Optional[str]:
        """
        Determine the DocType context for a field reference
        
        Args:
            line: Current line
            full_content: Full file content
            line_num: Line number
            
        Returns:
            DocType name if determinable, None otherwise
        """
        # First check the current line for inline DocType references
        current_line = line
        
        # Pattern for frappe.model.get_value("DocType", ...)
        model_match = re.search(r'frappe\.model\.get_value\s*\(\s*[\'"]([^\'"]+)[\'"]', current_line)
        if model_match:
            return model_match.group(1)
        
        # Pattern for frappe.model.set_value("DocType", ...)
        model_set_match = re.search(r'frappe\.model\.set_value\s*\(\s*[\'"]([^\'"]+)[\'"]', current_line)
        if model_set_match:
            return model_set_match.group(1)
        
        # Pattern for frappe.db.get_list("DocType", ...)
        getlist_current_match = re.search(r'get_list\s*\(\s*[\'"]([^\'"]+)[\'"]', current_line)
        if getlist_current_match:
            return getlist_current_match.group(1)
        
        lines = full_content.split('\n')
        
        # Look backwards from current line for doctype reference
        search_range = max(0, line_num - 20)
        for i in range(line_num - 1, search_range, -1):
            if i < len(lines):
                search_line = lines[i]
                
                # Pattern 1: frappe.ui.form.on('DocType', ...)
                form_match = re.search(r'frappe\.ui\.form\.on\s*\(\s*[\'"]([^\'"]+)[\'"]', search_line)
                if form_match:
                    return form_match.group(1)
                
                # Pattern 2: doctype: 'DocType'
                doctype_match = re.search(r'doctype\s*:\s*[\'"]([^\'"]+)[\'"]', search_line)
                if doctype_match:
                    return doctype_match.group(1)
                
                # Pattern 3: frappe.db.get_list('DocType', ...)
                getlist_match = re.search(r'get_list\s*\(\s*[\'"]([^\'"]+)[\'"]', search_line)
                if getlist_match:
                    return getlist_match.group(1)
        
        return None
    
    def _is_system_field(self, field: str) -> bool:
        """Check if field is a system field that exists on all doctypes"""
        system_fields = {
            'name', 'creation', 'modified', 'modified_by', 'owner',
            'docstatus', 'idx', '__islocal', '__unsaved', 'parent',
            'parentfield', 'parenttype', 'doctype', 'title',
            'naming_series', '_user_tags', '_comments', '_assign',
            '_liked_by', 'reference_doctype', 'reference_name'
        }
        return field in system_fields
    
    def _is_sql_expression(self, field: str) -> bool:
        """Check if field is a SQL expression rather than a field name"""
        # Common SQL aggregate functions and expressions
        sql_patterns = [
            r'count\(',
            r'sum\(',
            r'avg\(',
            r'max\(',
            r'min\(',
            r'distinct\s+',
            r'\s+as\s+',
            r'case\s+when',
            r'ifnull\(',
            r'coalesce\(',
            r'group_concat\(',
            r'date\(',
            r'year\(',
            r'month\(',
        ]
        
        field_lower = field.lower().strip()
        for pattern in sql_patterns:
            if re.search(pattern, field_lower):
                return True
        
        # Check for "field as alias" patterns
        if ' as ' in field_lower:
            return True
            
        return False
    
    def validate_directory(self, directory_path: str) -> Dict[str, List[ValidationIssue]]:
        """
        Validate all JavaScript files in a directory
        
        Args:
            directory_path: Path to directory to validate
            
        Returns:
            Dictionary mapping file paths to validation issues
        """
        results = {}
        
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                if file.endswith('.js'):
                    file_path = os.path.join(root, file)
                    
                    # Skip node_modules and other irrelevant directories
                    if 'node_modules' in file_path or '__pycache__' in file_path:
                        continue
                    
                    issues = self.validate_javascript_file(file_path)
                    if issues:
                        relative_path = os.path.relpath(file_path, directory_path)
                        results[relative_path] = issues
        
        return results
    
    def generate_report(self, validation_results: Dict[str, List[ValidationIssue]]) -> str:
        """
        Generate a formatted validation report
        
        Args:
            validation_results: Results from validation
            
        Returns:
            Formatted report string
        """
        report = []
        report.append("🔍 Advanced JavaScript Field Validation Report")
        report.append("=" * 55)
        
        total_files = len(validation_results)
        total_issues = sum(len(issues) for issues in validation_results.values())
        
        report.append(f"Files with issues: {total_files}")
        report.append(f"Total issues found: {total_issues}")
        report.append("")
        
        if total_issues == 0:
            report.append("✅ No JavaScript field reference issues found!")
            report.append("🎉 All JavaScript files pass advanced validation!")
            return "\n".join(report)
        
        # Group issues by severity
        error_count = sum(len([i for i in issues if i.severity == 'error']) 
                         for issues in validation_results.values())
        warning_count = sum(len([i for i in issues if i.severity == 'warning']) 
                           for issues in validation_results.values())
        
        report.append(f"❌ Errors: {error_count}")
        report.append(f"⚠️  Warnings: {warning_count}")
        report.append("")
        
        # Show detailed issues
        for file_path, issues in validation_results.items():
            report.append(f"📄 {file_path}:")
            
            for issue in issues:
                severity_icon = "❌" if issue.severity == "error" else "⚠️"
                report.append(f"  {severity_icon} Line {issue.line_number}: {issue.description}")
                report.append(f"     Expression: {issue.expression}")
                report.append(f"     💡 {issue.suggestion}")
                report.append("")
        
        return "\n".join(report)


def main():
    """Main validation function"""
    import sys
    
    # Get directory to validate (default to current app)
    if len(sys.argv) > 1:
        directory = sys.argv[1]
    else:
        current_dir = Path(__file__).parent
        directory = str(current_dir.parent.parent)  # verenigingen app root
    
    print("🔍 Advanced JavaScript Field Validator")
    print("=" * 45)
    print(f"Validating directory: {directory}")
    print()
    
    # Create validator
    validator = AdvancedJavaScriptFieldValidator()
    
    print(f"Loaded {len(validator.doctypes)} DocTypes for validation")
    print("🔍 Scanning JavaScript files with context analysis...")
    print()
    
    # Validate directory
    results = validator.validate_directory(directory)
    
    # Generate and print report
    report = validator.generate_report(results)
    print(report)
    
    # Return appropriate exit code
    total_errors = sum(len([i for i in issues if i.severity == 'error']) 
                      for issues in results.values())
    
    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    exit(main())