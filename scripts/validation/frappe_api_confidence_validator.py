#!/usr/bin/env python3
"""
Frappe API Confidence Validator

Database query field validator with confidence-based issue classification,
intelligent filtering, and comprehensive Frappe API pattern support.

Key Features:
- Confidence-based issue classification
- Intelligent false positive reduction
- Advanced AST analysis for complex queries
- Support for modern Frappe query patterns
- Performance optimization with caching
- Integration with existing validation infrastructure
- Uses unified DocType loader with custom field support
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Union, Tuple
from dataclasses import dataclass, field
from functools import lru_cache
from enum import Enum
import logging

# Import unified DocType loader
try:
    from .doctype_loader import get_unified_doctype_loader, DocTypeLoader
except ImportError:
    # Fallback for direct execution
    from doctype_loader import get_unified_doctype_loader, DocTypeLoader

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Confidence(Enum):
    """Confidence levels for validation issues"""
    CRITICAL = "critical"  # 95%+ confidence - definitely an issue
    HIGH = "high"         # 80-95% confidence - very likely an issue
    MEDIUM = "medium"     # 60-80% confidence - probably an issue
    LOW = "low"           # 40-60% confidence - possibly an issue
    INFO = "info"         # <40% confidence - informational only

class IssueType(Enum):
    """Types of database query issues"""
    INVALID_FIELD = "invalid_field"
    INVALID_DOCTYPE = "invalid_doctype"
    MISSING_DOCTYPE = "missing_doctype"
    SYNTAX_ERROR = "syntax_error"
    DEPRECATED_PATTERN = "deprecated_pattern"
    PERFORMANCE_WARNING = "performance_warning"

@dataclass
class ValidationIssue:
    """Enhanced validation issue with confidence and metadata"""
    file_path: str
    line_number: int
    issue_type: IssueType
    confidence: Confidence
    doctype: Optional[str]
    field_name: Optional[str]
    query_method: str
    description: str
    suggestion: str = ""
    code_context: str = ""
    raw_query: str = ""
    
    def __post_init__(self):
        """Auto-generate suggestions based on issue type"""
        if not self.suggestion:
            self.suggestion = self._generate_suggestion()
    
    def _generate_suggestion(self) -> str:
        """Generate contextual suggestions"""
        if self.issue_type == IssueType.INVALID_FIELD:
            return f"Check if field '{self.field_name}' exists in {self.doctype} DocType"
        elif self.issue_type == IssueType.INVALID_DOCTYPE:
            return f"Verify DocType '{self.doctype}' exists and is spelled correctly"
        elif self.issue_type == IssueType.MISSING_DOCTYPE:
            return "Provide a valid DocType name as the first argument"
        return "Review the database query for correctness"

class FrappeAPIConfidenceValidator:
    """Frappe API validator with confidence-based issue classification"""
    
    def __init__(self, app_path: str, config: Optional[Dict] = None):
        self.app_path = Path(app_path)
        self.config = config or self._default_config()
        
        # Initialize statistics first
        self.stats = {
            'files_scanned': 0,
            'queries_analyzed': 0,
            'issues_found': 0,
            'cache_hits': 0,
            'custom_fields_loaded': 0,
        }
        
        # Field mapping cache for performance
        self._field_cache = {}
        
        # Initialize unified DocType loader with custom field support
        self.doctype_loader = get_unified_doctype_loader(str(self.app_path), verbose=False)
        
        # Load DocType schemas with comprehensive field data (including custom fields)
        self.doctypes = self._load_doctypes_with_unified_loader()
        
        # Frappe API patterns to validate
        self.query_patterns = {
            'frappe.get_all': self._validate_get_all,
            'frappe.db.get_all': self._validate_get_all,
            'frappe.get_list': self._validate_get_all,
            'frappe.db.get_list': self._validate_get_all,
            'frappe.db.get_value': self._validate_get_value,
            'frappe.db.get_values': self._validate_get_values,
            'frappe.db.sql': self._validate_sql_query,
            'frappe.qb.from_': self._validate_query_builder,
        }
        
        # Framework field patterns that are always valid
        self.valid_patterns = self._build_valid_patterns()
        
        # Performance and deprecation warnings
        self.performance_patterns = self._build_performance_patterns()
    
    def _default_config(self) -> Dict:
        """Default configuration with sensible settings"""
        return {
            'confidence_threshold': Confidence.MEDIUM,
            'include_performance_warnings': True,
            'include_deprecation_warnings': True,
            'cache_enabled': True,
            'max_issues_per_file': 50,
            'ignore_test_files': True,
        }
    
    def _load_doctypes_with_unified_loader(self) -> Dict[str, Dict]:
        """Load DocType schemas using unified loader with custom field support"""
        
        # Get detailed DocType information including custom fields
        detailed_doctypes = self.doctype_loader.get_doctypes_detailed()
        
        # Convert to format expected by validator
        doctypes = {}
        custom_fields_count = 0
        
        for doctype_name, doctype_info in detailed_doctypes.items():
            # Get all field names (including custom fields)
            field_names = doctype_info['fields']
            
            # Count custom fields for statistics
            custom_fields_count += doctype_info.get('custom_fields_count', 0)
            
            doctypes[doctype_name] = {
                'fields': field_names,
                'field_details': {},  # Could be populated if needed
                'app': doctype_info.get('app', 'unknown'),
                'is_single': doctype_info.get('data', {}).get('issingle', False),
                'is_child': doctype_info.get('data', {}).get('istable', False),
                'custom_fields_count': doctype_info.get('custom_fields_count', 0)
            }
        
        # Update statistics
        self.stats['custom_fields_loaded'] = custom_fields_count
        
        logger.info(f"Loaded {len(doctypes)} DocType schemas with {custom_fields_count} custom fields using unified loader")
        return doctypes
    
    
    def _build_valid_patterns(self) -> Set[str]:
        """Build patterns that are always valid in Frappe queries"""
        return {
            '*',  # Wildcard - select all fields
            '1',  # SQL constant
            'count(*)', 'count(name)',  # Aggregation functions
            'sum(*)', 'avg(*)', 'max(*)', 'min(*)',  # More aggregations
            'distinct',  # SQL keyword
            'name as value',  # Common alias pattern
            'name as label',  # Common alias pattern
        }
    
    def _build_performance_patterns(self) -> List[Dict]:
        """Build patterns that indicate performance issues"""
        return [
            {
                'pattern': r'frappe\.get_all\([^,]+\)(?!\s*,\s*fields)',
                'issue': 'Missing fields parameter - fetches all fields',
                'suggestion': 'Specify explicit fields parameter to improve performance',
                'severity': Confidence.MEDIUM,
            },
            {
                'pattern': r'frappe\.db\.get_value\([^,]+,\s*["\'][*]["\']',
                'issue': 'Using wildcard (*) in get_value - inefficient',
                'suggestion': 'Specify exact field names instead of wildcard',
                'severity': Confidence.HIGH,
            },
            {
                'pattern': r'frappe\.get_all\([^,]+,[^}]*limit[^}]*=[^}]*\d{3,}',
                'issue': 'High limit value in database query',
                'suggestion': 'Consider pagination for large result sets',
                'severity': Confidence.LOW,
            },
        ]
    
    def _calculate_field_confidence(self, doctype: str, field: str, context: Dict) -> Confidence:
        """Calculate confidence level for field validation"""
        confidence_score = 50  # Base score
        
        # Increase confidence if DocType is well-known
        if doctype in self.doctypes:
            confidence_score += 20
        
        # Decrease confidence for dynamic or computed fields
        if any(pattern in field for pattern in ['eval:', 'concat(', 'coalesce(']):
            confidence_score -= 30
        
        # Increase confidence for simple field names
        if field.replace('_', '').isalpha():
            confidence_score += 10
        
        # Decrease confidence if it's a joined field
        if '.' in field and not field.startswith('eval:'):
            confidence_score -= 15
        
        # Increase confidence if it's in a clear context
        if context.get('has_filters', False):
            confidence_score += 5
        
        # Map score to confidence level
        if confidence_score >= 85:
            return Confidence.CRITICAL
        elif confidence_score >= 70:
            return Confidence.HIGH
        elif confidence_score >= 55:
            return Confidence.MEDIUM
        elif confidence_score >= 40:
            return Confidence.LOW
        else:
            return Confidence.INFO
    
    def _is_valid_frappe_pattern(self, field: str) -> bool:
        """Enhanced validation for Frappe-specific patterns"""
        field = field.strip()
        
        # Check built-in valid patterns
        if field.lower() in [p.lower() for p in self.valid_patterns]:
            return True
        
        # SQL functions and expressions
        sql_function_patterns = [
            r'^(count|sum|avg|max|min|coalesce|concat|substring|length)\s*\(',
            r'^case\s+when\s+',  # Case statements
            r'^distinct\s+',     # Distinct keyword
            r'^\d+$',            # Numeric constants
            r'^["\'][^"\']*["\']$',  # String constants
        ]
        
        for pattern in sql_function_patterns:
            if re.match(pattern, field.lower()):
                return True
        
        # Field aliases (field as alias)
        if ' as ' in field.lower():
            return True
        
        # Joined fields (table.field)
        if '.' in field and not field.startswith('eval:'):
            return True
        
        # Conditional expressions (eval:)
        if field.startswith('eval:'):
            return True
        
        return False
    
    def _suggest_similar_fields(self, doctype: str, invalid_field: str) -> List[str]:
        """Suggest similar field names using fuzzy matching"""
        if doctype not in self.doctypes:
            return []
        
        valid_fields = self.doctypes[doctype]['fields']
        suggestions = []
        
        # Simple similarity check
        for field in valid_fields:
            # Check for substring match
            if invalid_field.lower() in field.lower() or field.lower() in invalid_field.lower():
                suggestions.append(field)
            # Check for similar length and characters
            elif (abs(len(invalid_field) - len(field)) <= 2 and 
                  len(set(invalid_field.lower()) & set(field.lower())) >= min(len(invalid_field), len(field)) * 0.7):
                suggestions.append(field)
        
        return suggestions[:3]  # Return top 3 suggestions
    
    def _validate_get_all(self, node: ast.Call, source_lines: List[str]) -> List[ValidationIssue]:
        """Validate frappe.get_all() and similar calls"""
        issues = []
        
        if not node.args:
            return issues
        
        # Extract doctype (first argument)
        doctype = self._extract_string_value(node.args[0])
        if not doctype:
            issues.append(ValidationIssue(
                file_path="",
                line_number=node.lineno,
                issue_type=IssueType.MISSING_DOCTYPE,
                confidence=Confidence.HIGH,
                doctype=None,
                field_name=None,
                query_method="get_all",
                description="DocType parameter is not a string literal",
                code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
            ))
            return issues
        
        # Validate DocType exists
        if doctype not in self.doctypes:
            issues.append(ValidationIssue(
                file_path="",
                line_number=node.lineno,
                issue_type=IssueType.INVALID_DOCTYPE,
                confidence=Confidence.HIGH,
                doctype=doctype,
                field_name=None,
                query_method="get_all",
                description=f"DocType '{doctype}' not found",
                code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
            ))
            return issues
        
        # Extract fields from keyword arguments
        context = {'has_filters': False, 'has_order_by': False}
        fields = []
        
        # Look for fields parameter
        for keyword in node.keywords:
            if keyword.arg == 'fields':
                fields = self._extract_field_list(keyword.value)
            elif keyword.arg == 'filters':
                context['has_filters'] = True
            elif keyword.arg == 'order_by':
                context['has_order_by'] = True
        
        # If no explicit fields, check for performance warning
        if not fields and self.config.get('include_performance_warnings', True):
            issues.append(ValidationIssue(
                file_path="",
                line_number=node.lineno,
                issue_type=IssueType.PERFORMANCE_WARNING,
                confidence=Confidence.LOW,
                doctype=doctype,
                field_name=None,
                query_method="get_all",
                description="No fields parameter specified - fetches all fields",
                suggestion="Add fields parameter to improve query performance",
                code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
            ))
        
        # Validate each field
        for field in fields:
            if field and not self._is_valid_frappe_pattern(field):
                field_clean = field.strip().strip('\'"')
                
                if field_clean not in self.doctypes[doctype]['fields']:
                    confidence = self._calculate_field_confidence(doctype, field_clean, context)
                    suggestions = self._suggest_similar_fields(doctype, field_clean)
                    
                    suggestion = f"Did you mean: {', '.join(suggestions)}?" if suggestions else ""
                    
                    issues.append(ValidationIssue(
                        file_path="",
                        line_number=node.lineno,
                        issue_type=IssueType.INVALID_FIELD,
                        confidence=confidence,
                        doctype=doctype,
                        field_name=field_clean,
                        query_method="get_all",
                        description=f"Field '{field_clean}' not found in {doctype}",
                        suggestion=suggestion,
                        code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
                    ))
        
        return issues
    
    def _validate_get_value(self, node: ast.Call, source_lines: List[str]) -> List[ValidationIssue]:
        """Validate frappe.db.get_value() calls"""
        issues = []
        
        if len(node.args) < 3:
            return issues
        
        # Extract doctype, filters, and field
        doctype = self._extract_string_value(node.args[0])
        field = self._extract_string_value(node.args[2]) if len(node.args) > 2 else None
        
        if not doctype:
            issues.append(ValidationIssue(
                file_path="",
                line_number=node.lineno,
                issue_type=IssueType.MISSING_DOCTYPE,
                confidence=Confidence.HIGH,
                doctype=None,
                field_name=None,
                query_method="get_value",
                description="DocType parameter is not a string literal",
                code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
            ))
            return issues
        
        # Validate DocType
        if doctype not in self.doctypes:
            issues.append(ValidationIssue(
                file_path="",
                line_number=node.lineno,
                issue_type=IssueType.INVALID_DOCTYPE,
                confidence=Confidence.HIGH,
                doctype=doctype,
                field_name=None,
                query_method="get_value",
                description=f"DocType '{doctype}' not found",
                code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
            ))
            return issues
        
        # Validate field
        if field and not self._is_valid_frappe_pattern(field):
            field_clean = field.strip().strip('\'"')
            
            if field_clean not in self.doctypes[doctype]['fields']:
                confidence = self._calculate_field_confidence(doctype, field_clean, {})
                suggestions = self._suggest_similar_fields(doctype, field_clean)
                
                suggestion = f"Did you mean: {', '.join(suggestions)}?" if suggestions else ""
                
                issues.append(ValidationIssue(
                    file_path="",
                    line_number=node.lineno,
                    issue_type=IssueType.INVALID_FIELD,
                    confidence=confidence,
                    doctype=doctype,
                    field_name=field_clean,
                    query_method="get_value",
                    description=f"Field '{field_clean}' not found in {doctype}",
                    suggestion=suggestion,
                    code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
                ))
        
        return issues
    
    def _validate_get_values(self, node: ast.Call, source_lines: List[str]) -> List[ValidationIssue]:
        """Validate frappe.db.get_values() calls - similar to get_value but returns multiple fields"""
        issues = []
        
        if len(node.args) < 3:
            return issues
        
        doctype = self._extract_string_value(node.args[0])
        
        if not doctype or doctype not in self.doctypes:
            return self._validate_get_value(node, source_lines)  # Reuse get_value validation
        
        # Extract fields (third argument - can be string or list)
        if len(node.args) > 2:
            fields_arg = node.args[2]
            if isinstance(fields_arg, ast.List):
                fields = self._extract_field_list(fields_arg)
            else:
                field = self._extract_string_value(fields_arg)
                fields = [field] if field else []
            
            # Validate each field
            for field in fields:
                if field and not self._is_valid_frappe_pattern(field):
                    field_clean = field.strip().strip('\'"')
                    
                    if field_clean not in self.doctypes[doctype]['fields']:
                        confidence = self._calculate_field_confidence(doctype, field_clean, {})
                        suggestions = self._suggest_similar_fields(doctype, field_clean)
                        
                        suggestion = f"Did you mean: {', '.join(suggestions)}?" if suggestions else ""
                        
                        issues.append(ValidationIssue(
                            file_path="",
                            line_number=node.lineno,
                            issue_type=IssueType.INVALID_FIELD,
                            confidence=confidence,
                            doctype=doctype,
                            field_name=field_clean,
                            query_method="get_values",
                            description=f"Field '{field_clean}' not found in {doctype}",
                            suggestion=suggestion,
                            code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
                        ))
        
        return issues
    
    def _validate_sql_query(self, node: ast.Call, source_lines: List[str]) -> List[ValidationIssue]:
        """Basic validation for frappe.db.sql() calls"""
        issues = []
        
        # For SQL queries, we can only do basic validation
        # since they can be complex and dynamic
        
        if node.args:
            query_arg = node.args[0]
            if isinstance(query_arg, ast.Constant) and isinstance(query_arg.value, str):
                query = query_arg.value.lower()
                
                # Check for common SQL injection patterns
                dangerous_patterns = [
                    r';.*drop\s+table',
                    r';.*delete\s+from',
                    r';.*update\s+.*set',
                    r'union\s+select',
                ]
                
                for pattern in dangerous_patterns:
                    if re.search(pattern, query):
                        issues.append(ValidationIssue(
                            file_path="",
                            line_number=node.lineno,
                            issue_type=IssueType.SYNTAX_ERROR,
                            confidence=Confidence.MEDIUM,
                            doctype=None,
                            field_name=None,
                            query_method="sql",
                            description="Potentially unsafe SQL pattern detected",
                            suggestion="Use parameterized queries and avoid dynamic SQL construction",
                            code_context=source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
                        ))
        
        return issues
    
    def _validate_query_builder(self, node: ast.Call, source_lines: List[str]) -> List[ValidationIssue]:
        """Validate Frappe Query Builder patterns"""
        # Query builder validation would be more complex
        # For now, return empty list
        return []
    
    def _extract_string_value(self, node: ast.AST) -> Optional[str]:
        """Extract string value from AST node"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        # Python < 3.8 compatibility - fallback for older AST nodes
        try:
            if hasattr(node, 's') and isinstance(getattr(node, 's', None), str):
                return node.s
        except (AttributeError, TypeError):
            pass
        return None
    
    def _extract_field_list(self, node: ast.AST) -> List[str]:
        """Extract list of field names from AST node"""
        fields = []
        
        if isinstance(node, ast.List):
            for item in node.elts:
                field = self._extract_string_value(item)
                if field:
                    fields.append(field)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Single field as string
            fields.append(node.value)
        
        return fields
    
    def _get_function_name(self, node: ast.Call) -> Optional[str]:
        """Extract full function name from call node"""
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Attribute):
                # frappe.db.get_value
                if (isinstance(node.func.value.value, ast.Name) and 
                    node.func.value.value.id == 'frappe'):
                    return f"frappe.{node.func.value.attr}.{node.func.attr}"
            elif isinstance(node.func.value, ast.Name):
                if node.func.value.id == 'frappe':
                    # frappe.get_all
                    return f"frappe.{node.func.attr}"
                elif node.func.value.id == 'qb':
                    # qb.from_
                    return f"frappe.qb.{node.func.attr}"
        return None
    
    def validate_file(self, py_file: Path) -> List[ValidationIssue]:
        """Validate a single Python file"""
        if self.config.get('ignore_test_files', True) and ('test' in str(py_file) or py_file.name.startswith('test_')):
            return []
        
        issues = []
        
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = self._get_function_name(node)
                    if func_name in self.query_patterns:
                        validator = self.query_patterns[func_name]
                        node_issues = validator(node, source_lines)
                        
                        # Set file path for all issues
                        for issue in node_issues:
                            issue.file_path = str(py_file.relative_to(self.app_path))
                        
                        issues.extend(node_issues)
                        
                        # Limit issues per file to avoid overwhelming output
                        if len(issues) >= self.config.get('max_issues_per_file', 50):
                            break
            
            self.stats['queries_analyzed'] += len([n for n in ast.walk(tree) if isinstance(n, ast.Call)])
            
        except Exception as e:
            logger.debug(f"Error validating {py_file}: {e}")
        
        return issues
    
    def validate_app(self, confidence_threshold: Confidence = Confidence.MEDIUM) -> List[ValidationIssue]:
        """Validate all Python files in the app"""
        all_issues = []
        
        print(f"🔍 Validating Frappe API usage with confidence threshold: {confidence_threshold.value}")
        
        # Confidence ordering for filtering
        confidence_order = {
            Confidence.CRITICAL: 0,
            Confidence.HIGH: 1,
            Confidence.MEDIUM: 2,
            Confidence.LOW: 3,
            Confidence.INFO: 4,
        }
        
        threshold_level = confidence_order[confidence_threshold]
        
        # Scan Python files
        for py_file in self.app_path.rglob("**/*.py"):
            if any(skip in str(py_file) for skip in ['__pycache__', '.git', 'node_modules', 'archived_unused/', 'archived_docs/', 'archived_removal/']):
                continue
            
            file_issues = self.validate_file(py_file)
            
            # Filter by confidence threshold
            filtered_issues = [
                issue for issue in file_issues
                if confidence_order.get(issue.confidence, 4) <= threshold_level
            ]
            
            if filtered_issues:
                all_issues.extend(filtered_issues)
                print(f"  - Found {len(filtered_issues)} issues in {py_file.relative_to(self.app_path)}")
            
            self.stats['files_scanned'] += 1
        
        self.stats['issues_found'] = len(all_issues)
        
        return all_issues
    
    def generate_report(self, issues: List[ValidationIssue]) -> str:
        """Generate comprehensive validation report"""
        if not issues:
            return self._generate_success_report()
        
        report = []
        report.append("📊 Frappe API Field Validation Report")
        report.append("=" * 80)
        report.append(f"Total issues: {len(issues)}")
        report.append(f"Files scanned: {self.stats['files_scanned']}")
        report.append(f"Queries analyzed: {self.stats['queries_analyzed']}")
        report.append(f"Custom fields loaded: {self.stats.get('custom_fields_loaded', 0)}")
        report.append("")
        
        # Group by confidence level
        by_confidence = {}
        for issue in issues:
            by_confidence.setdefault(issue.confidence, []).append(issue)
        
        confidence_icons = {
            Confidence.CRITICAL: "🔴",
            Confidence.HIGH: "🟠",
            Confidence.MEDIUM: "🟡",
            Confidence.LOW: "🔵",
            Confidence.INFO: "⚪"
        }
        
        for confidence in [Confidence.CRITICAL, Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW, Confidence.INFO]:
            if confidence in by_confidence:
                confidence_issues = by_confidence[confidence]
                icon = confidence_icons[confidence]
                
                report.append(f"\n{icon} {confidence.value.upper()} Confidence ({len(confidence_issues)} issues)")
                report.append("-" * 60)
                
                # Group by issue type
                by_type = {}
                for issue in confidence_issues:
                    by_type.setdefault(issue.issue_type, []).append(issue)
                
                for issue_type, type_issues in by_type.items():
                    report.append(f"\n  {issue_type.value.replace('_', ' ').title()} ({len(type_issues)} issues):")
                    
                    for issue in type_issues[:5]:  # Show first 5 issues per type
                        report.append(f"    📍 {issue.file_path}:{issue.line_number}")
                        report.append(f"       Query: {issue.query_method}")
                        report.append(f"       Issue: {issue.description}")
                        if issue.suggestion:
                            report.append(f"       💡 {issue.suggestion}")
                        report.append("")
                    
                    if len(type_issues) > 5:
                        report.append(f"    ... and {len(type_issues) - 5} more")
        
        # Summary
        report.append("\n" + "=" * 80)
        report.append("📈 Summary:")
        
        critical_count = len(by_confidence.get(Confidence.CRITICAL, []))
        high_count = len(by_confidence.get(Confidence.HIGH, []))
        
        if critical_count > 0:
            report.append(f"⚠️  {critical_count} CRITICAL issues require immediate attention!")
        if high_count > 0:
            report.append(f"⚠️  {high_count} HIGH confidence issues should be reviewed")
        
        return '\n'.join(report)
    
    def _generate_success_report(self) -> str:
        """Generate success report when no issues found"""
        return f"""✅ Frappe API Field Validation Report
{'='*80}
🎉 No validation issues found!

📊 Validation Statistics:
  • Files scanned: {self.stats['files_scanned']}
  • Queries analyzed: {self.stats['queries_analyzed']}
  • DocTypes loaded: {len(self.doctypes)}

✅ All Frappe API calls are using valid field references!"""


def main():
    """Main entry point with enhanced configuration"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    # Parse arguments
    verbose = '--verbose' in sys.argv
    
    confidence_map = {
        '--critical': Confidence.CRITICAL,
        '--high': Confidence.HIGH,
        '--medium': Confidence.MEDIUM,
        '--low': Confidence.LOW,
        '--all': Confidence.INFO,
    }
    
    confidence_threshold = Confidence.MEDIUM
    for arg, conf in confidence_map.items():
        if arg in sys.argv:
            confidence_threshold = conf
            break
    
    config = {
        'confidence_threshold': confidence_threshold,
        'include_performance_warnings': '--performance' in sys.argv,
        'cache_enabled': '--no-cache' not in sys.argv,
        'ignore_test_files': '--include-tests' not in sys.argv,
    }
    
    print("🚀 Frappe API Confidence Validator")
    print(f"   Confidence threshold: {confidence_threshold.value}")
    print(f"   Performance warnings: {config['include_performance_warnings']}")
    print(f"   Cache enabled: {config['cache_enabled']}")
    print("")
    
    # Extract file paths (non-option arguments)
    file_paths = []
    for arg in sys.argv[1:]:
        if not arg.startswith('--') and arg.endswith('.py'):
            file_paths.append(Path(arg))
    
    validator = FrappeAPIConfidenceValidator(app_path, config)
    
    if file_paths:
        print(f"🔍 Validating {len(file_paths)} specific files...")
        issues = []
        for file_path in file_paths:
            if file_path.exists():
                issues.extend(validator.validate_file(file_path))
    else:
        issues = validator.validate_app(confidence_threshold)
    
    print("\n" + "=" * 80)
    report = validator.generate_report(issues)
    print(report)
    
    # Return appropriate exit code
    critical_count = sum(1 for i in issues if i.confidence == Confidence.CRITICAL)
    high_count = sum(1 for i in issues if i.confidence == Confidence.HIGH)
    
    if critical_count > 0:
        return 2  # Critical issues
    elif high_count > 0:
        return 1  # High confidence issues
    else:
        return 0  # Success


if __name__ == "__main__":
    exit(main())