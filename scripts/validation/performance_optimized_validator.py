#!/usr/bin/env python3
"""
Optimized Field Validator
Improved version with reduced false positives and better accuracy
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

class OptimizedFieldValidator:
    """Optimized field validator with reduced false positives"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        
        # Enhanced exclusion lists to reduce false positives
        self.sql_operators = {
            'in', 'like', 'and', 'or', 'not', 'is', 'as', 'on', 'by',
            'asc', 'desc', 'null', 'where', 'order', 'group', 'having',
            'select', 'from', 'join', 'left', 'right', 'inner', 'outer',
            'union', 'distinct', 'count', 'sum', 'avg', 'min', 'max',
            'case', 'when', 'then', 'else', 'end', 'between', 'exists',
            'all', 'any', 'some', 'limit', 'offset'
        }
        
        self.status_values = {
            'active', 'inactive', 'draft', 'cancelled', 'approved', 
            'rejected', 'pending', 'submitted', 'completed', 'open',
            'closed', 'enabled', 'disabled', 'valid', 'invalid',
            'terminated', 'suspended', 'expired'
        }
        
        # Common programming terms that are not field names
        self.programming_terms = {
            'self', 'cls', 'args', 'kwargs', 'result', 'data', 'value',
            'key', 'item', 'index', 'length', 'size', 'count', 'total',
            'error', 'success', 'failure', 'response', 'request',
            'config', 'settings', 'options', 'params', 'meta'
        }
        
        # Known field mappings from recent fixes
        self.known_field_mappings = {
            'SEPA Mandate': {
                'valid_from': 'first_collection_date',
                'valid_until': 'expiry_date',
                'usage_count': None,  # Use usage_history child table
                'last_used_date': None,  # Use usage_history child table
            },
            'Member': {
                'email_id': 'email',
                'chapter': None,  # Use Chapter Member relationship
            },
            'Chapter Member': {
                'is_active': 'enabled',
            },
            'Donor': {
                'email': 'donor_email',
                'anbi_consent_given': 'anbi_consent',
            },
            'System Alert': {
                'event_type': 'process_type',
                'severity': 'compliance_status',
                'ip_address': 'action',
            }
        }
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
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
                    
                    doctypes[doctype_name] = fields
                    
                except Exception:
                    continue
                    
        return doctypes
    
    def is_false_positive(self, field_name: str, context: str = "") -> bool:
        """Check if a field reference is likely a false positive"""
        field_lower = field_name.lower()
        
        # SQL operators and keywords
        if field_lower in self.sql_operators:
            return True
            
        # Status values
        if field_lower in self.status_values:
            return True
            
        # Programming terms
        if field_lower in self.programming_terms:
            return True
            
        # Single character variables (likely aliases)
        if len(field_name) == 1:
            return True
            
        # Common filter patterns that are not fields
        if any(pattern in context.lower() for pattern in [
            'filters=', 'where ', 'order by', 'group by'
        ]):
            # Check if this looks like a filter value rather than field name
            if field_lower in ['like', 'in', 'not', 'is', 'and', 'or']:
                return True
                
        return False
    
    def get_suggested_fix(self, doctype: str, field: str) -> Optional[str]:
        """Get suggested fix from known field mappings"""
        if doctype in self.known_field_mappings:
            mapping = self.known_field_mappings[doctype].get(field)
            if mapping is None:
                if field == 'chapter' and doctype == 'Member':
                    return "Use Chapter Member relationship or current_chapter_display field"
                return f"Field removed - check {doctype} doctype for alternatives"
            return mapping
        return None
    
    def find_similar_fields(self, field_name: str, doctype: str) -> List[str]:
        """Find similar field names using string matching"""
        if doctype not in self.doctypes:
            return []
            
        valid_fields = self.doctypes[doctype]
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
                
        return similar[:3]  # Return top 3 matches
    
    def calculate_confidence(self, doctype: str, field: str, file_path: Path, context: str) -> str:
        """Calculate confidence level for validation issue"""
        
        # Skip false positives entirely
        if self.is_false_positive(field, context):
            return 'skip'
        
        # High confidence for known deprecated fields
        if doctype in self.known_field_mappings and field in self.known_field_mappings[doctype]:
            return 'high'
        
        # High confidence for clear field references with doctype context
        if doctype and doctype in self.doctypes:
            # Field clearly doesn't exist and has similar alternatives
            if self.find_similar_fields(field, doctype):
                return 'high'
                
        # Medium confidence for SQL queries with clear table references
        if any(pattern in context.lower() for pattern in ['select', 'from', 'join', 'where']):
            if f'tab{doctype}' in context or doctype.lower() in context.lower():
                return 'medium'
        
        # Low confidence for unclear context
        return 'low'
    
    def validate_filter_dictionaries(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate database filter dictionary patterns with improved accuracy"""
        violations = []
        
        # More precise patterns for filter dictionaries
        filter_patterns = [
            r'frappe\.(?:db\.)?(?:get_all|get_list|exists|count)\(\s*["\']([^"\']+)["\']\s*,\s*[^)]*filters\s*=\s*\{([^}]+)\}',
        ]
        
        for pattern in filter_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                doctype = match.group(1)
                filter_dict_str = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                # More sophisticated field extraction
                # Look for field: value patterns, excluding operators
                field_value_pattern = r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']:\s*(?:["\']([^"\']+)["\']|\[)'
                field_matches = re.findall(field_value_pattern, filter_dict_str)
                
                if doctype in self.doctypes:
                    doctype_fields = self.doctypes[doctype]
                    
                    for field_name, value in field_matches:
                        # Skip if field exists
                        if field_name in doctype_fields:
                            continue
                            
                        # Check if this is a false positive
                        confidence = self.calculate_confidence(doctype, field_name, file_path, filter_dict_str)
                        if confidence == 'skip':
                            continue
                            
                        suggested_fix = self.get_suggested_fix(doctype, field_name)
                        similar = self.find_similar_fields(field_name, doctype)
                        similar_text = f" (similar: {', '.join(similar)})" if similar else ""
                        
                        message = f"Field '{field_name}' in filter dictionary does not exist in '{doctype}'{similar_text}"
                        if suggested_fix:
                            message += f" → Suggested: {suggested_fix}"
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"filter dict: {field_name}",
                            message=message,
                            context=self._get_line_context(content, line_num),
                            confidence=confidence,
                            issue_type="missing_filter_field",
                            suggested_fix=suggested_fix
                        ))
        
        return violations
    
    def validate_sql_field_patterns(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate SQL field references with improved accuracy"""
        violations = []
        
        # Extract SQL queries first
        queries = self.extract_sql_queries(content)
        for sql, line_num in queries:
            # Extract table aliases
            aliases = self.extract_table_aliases(sql)
            
            # Extract field references with alias context
            field_refs = self.extract_field_references(sql, aliases)
            
            for doctype, field, full_ref in field_refs:
                if doctype in self.doctypes:
                    valid_fields = self.doctypes[doctype]
                    
                    # Skip if field exists
                    if field in valid_fields:
                        continue
                        
                    # Check confidence and skip false positives
                    confidence = self.calculate_confidence(doctype, field, file_path, sql)
                    if confidence == 'skip':
                        continue
                    
                    suggested_fix = self.get_suggested_fix(doctype, field)
                    similar = self.find_similar_fields(field, doctype)
                    similar_text = f" (similar: {', '.join(similar)})" if similar else ""
                    
                    message = f"Field '{field}' does not exist in {doctype}{similar_text}"
                    if suggested_fix:
                        message += f" → Suggested: {suggested_fix}"
                    
                    violations.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field,
                        doctype=doctype,
                        reference=full_ref,
                        message=message,
                        context=sql[:100] + ('...' if len(sql) > 100 else ''),
                        confidence=confidence,
                        issue_type='sql_field_reference',
                        suggested_fix=suggested_fix
                    ))
        
        return violations
    
    def extract_sql_queries(self, content: str) -> List[Tuple[str, int]]:
        """Extract SQL queries from string literals"""
        queries = []
        
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
                
                if len(sql_content) > 20 and any(keyword in sql_content.upper() 
                                               for keyword in ['SELECT', 'FROM', 'JOIN']):
                    queries.append((sql_content, line_num))
                    
        return queries
    
    def extract_table_aliases(self, sql: str) -> Dict[str, str]:
        """Extract table aliases from SQL"""
        aliases = {}
        
        alias_patterns = [
            r'`tab([^`]+)`\s+(\w+)',
            r'FROM\s+`tab([^`]+)`\s+(\w+)',
            r'JOIN\s+`tab([^`]+)`\s+(\w+)',
        ]
        
        for pattern in alias_patterns:
            for match in re.finditer(pattern, sql, re.IGNORECASE):
                doctype = match.group(1)
                alias = match.group(2)
                aliases[alias] = doctype
                
        return aliases
    
    def extract_field_references(self, sql: str, aliases: Dict[str, str]) -> List[Tuple[str, str, str]]:
        """Extract field references from SQL"""
        field_refs = []
        field_pattern = r'(\w+)\.(\w+)'
        
        for match in re.finditer(field_pattern, sql):
            alias = match.group(1)
            field = match.group(2)
            full_ref = f"{alias}.{field}"
            
            # Skip SQL keywords and functions
            if alias.upper() in self.sql_operators or field.upper() in self.sql_operators:
                continue
                
            if alias in aliases:
                doctype = aliases[alias]
                field_refs.append((doctype, field, full_ref))
            
        return field_refs
    
    def validate_get_single_value_calls(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate get_single_value calls for Singles doctypes"""
        violations = []
        
        patterns = [
            r'frappe\.db\.get_single_value\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
            r'frappe\.get_single_value\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content):
                doctype = match.group(1)
                field_name = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                # Check if the doctype exists and has the field
                if doctype in self.doctypes:
                    doctype_fields = self.doctypes[doctype]
                    
                    if field_name not in doctype_fields:
                        # Skip false positives
                        confidence = self.calculate_confidence(doctype, field_name, file_path, content[max(0, match.start()-50):match.end()+50])
                        if confidence == 'skip':
                            continue
                            
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"get_single_value: {field_name}",
                            message=f"Field '{field_name}' does not exist in Singles doctype '{doctype}'",
                            context=self._get_line_context(content, line_num),
                            confidence="high",
                            issue_type="missing_singles_field",
                            suggested_fix=f"Add field '{field_name}' to {doctype} doctype or verify field name"
                        ))
        
        return violations
    
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
        skip_patterns = ['test_', 'debug_', '__pycache__', '/archived_', '/tests/']
        if any(pattern in str(file_path) for pattern in skip_patterns):
            return violations
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Validate different types of field references
            violations.extend(self.validate_filter_dictionaries(content, file_path))
            violations.extend(self.validate_sql_field_patterns(content, file_path))
            violations.extend(self.validate_get_single_value_calls(content, file_path))
            
        except Exception as e:
            # Silently skip files that can't be read
            pass
            
        return violations
    
    def run_validation(self, pre_commit_mode: bool = False) -> bool:
        """Run comprehensive field validation"""
        if not pre_commit_mode:
            print("🔍 Running Optimized Field Validation...")
            print(f"📋 Loaded {len(self.doctypes)} doctypes with field definitions")
        
        all_violations = []
        file_count = 0
        
        # Validate all Python files
        for py_file in self.app_path.rglob("*.py"):
            violations = self.validate_file(py_file)
            all_violations.extend(violations)
            file_count += 1
        
        if not pre_commit_mode:
            print(f"📊 Checked {file_count} Python files")
        
        # Filter and report results
        if pre_commit_mode:
            # Only show high confidence issues in pre-commit
            high_conf_violations = [v for v in all_violations if v.confidence == 'high']
            if high_conf_violations:
                print(f"🚨 Found {len(high_conf_violations)} critical field reference issues:")
                for violation in high_conf_violations:
                    print(f"❌ {violation.file}:{violation.line} - {violation.field} not in {violation.doctype}")
                    if violation.suggested_fix:
                        print(f"   → Suggested: {violation.suggested_fix}")
                return False
            return True
        else:
            # Full reporting for manual runs
            if all_violations:
                # Group by confidence
                high_conf = [v for v in all_violations if v.confidence == 'high']
                med_conf = [v for v in all_violations if v.confidence == 'medium']
                low_conf = [v for v in all_violations if v.confidence == 'low']
                
                print(f"\n🔍 Optimized Field Validation Results:")
                print(f"📊 Total issues: {len(all_violations)}")
                print(f"🔴 High confidence (critical): {len(high_conf)}")
                print(f"🟡 Medium confidence (investigate): {len(med_conf)}")
                print(f"🟢 Low confidence (likely false positives): {len(low_conf)}")
                print()
                
                # Show high confidence issues
                if high_conf:
                    print("🔴 HIGH CONFIDENCE ISSUES (Priority fixes):")
                    for violation in high_conf:
                        print(f"❌ {violation.file}:{violation.line}")
                        print(f"   {violation.message}")
                        print(f"   Reference: {violation.reference}")
                        print()
                
                # Show summary of other issues
                if med_conf:
                    print(f"🟡 MEDIUM CONFIDENCE ISSUES ({len(med_conf)} total)")
                    for violation in med_conf[:5]:
                        print(f"   {violation.file}:{violation.line} - {violation.reference}")
                    if len(med_conf) > 5:
                        print(f"   ... and {len(med_conf) - 5} more")
                    print()
                
                return len(high_conf) == 0
            else:
                print("✅ No field reference issues found!")
                return True

def main():
    """Main function"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Optimized field validation")
    parser.add_argument("--pre-commit", action="store_true", help="Run in pre-commit mode")
    args = parser.parse_args()
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = OptimizedFieldValidator(app_path)
    
    success = validator.run_validation(pre_commit_mode=args.pre_commit)
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())