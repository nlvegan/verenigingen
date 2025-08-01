#!/usr/bin/env python3
"""
Enhanced SQL Field Validator with Confidence Scoring

Validates field references in SQL string literals to prevent database errors
caused by referencing non-existent columns. Enhanced version with:
- Confidence scoring to reduce false positives
- Common field mapping patterns
- Better filtering of archived/test files
- Improved standard field detection
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, NamedTuple
from dataclasses import dataclass


@dataclass
class ValidationIssue:
    """Represents a field validation issue with confidence scoring"""
    file: str
    line: int
    field: str
    doctype: str
    reference: str
    message: str
    sql_context: str
    confidence: str  # high, medium, low
    issue_type: str
    suggested_fix: Optional[str] = None


class EnhancedSQLFieldValidator:
    """Enhanced validator for SQL string literals with confidence scoring"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        
        # Extended standard Frappe fields (initialize before load_doctypes)
        self.standard_frappe_fields = {
            'name', 'creation', 'modified', 'modified_by', 'owner',
            'docstatus', 'parent', 'parentfield', 'parenttype', 'idx',
            'doctype', '_user_tags', '_comments', '_assign', '_liked_by',
            # Additional standard fields
            'naming_series', 'title', 'disabled', 'is_group', 'lft', 'rgt',
            'old_parent', 'workflow_state', '_seen', '_liked_by', '_comments',
            # Common computed fields that might appear in views/queries
            'full_name', 'status', 'total', 'amount', 'count'
        }
        
        self.doctypes = self.load_doctypes()
        
        # Known field mappings from SEPA fixes and common patterns
        self.field_mappings = {
            # SEPA Mandate field mappings
            'SEPA Mandate': {
                'valid_from': 'first_collection_date',
                'valid_until': 'expiry_date',
                'usage_count': None,  # Use usage_history child table
                'last_used_date': None,  # Use usage_history child table
            },
            # Common field name mappings
            'Donation': {
                'date': 'donation_date',
            },
            'Donor': {
                'email': 'donor_email',
            },
            'Chapter Board Member': {
                'member': 'volunteer',
            },
            'Volunteer Assignment': {
                'volunteer': None,  # This field doesn't exist - it's a child table
            },
            'Membership': {
                'subscription': None,  # This field was removed/renamed
            },
            'Membership Dues Schedule': {
                'start_date': 'next_invoice_date',  # Based on actual fields
            }
        }
        
        # File patterns to deprioritize (likely false positives)
        self.low_priority_patterns = [
            r'archived_unused/',
            r'_backup',
            r'test_',
            r'debug_',
            r'performance_benchmark',
            r'scripts/testing/',
            r'_disabled'
        ]
        
        # SQL keywords and functions that might appear as table aliases
        self.sql_keywords = {
            'select', 'from', 'where', 'join', 'inner', 'left', 'right', 'outer',
            'group', 'order', 'having', 'union', 'distinct', 'as', 'on', 'and', 
            'or', 'not', 'in', 'like', 'between', 'exists', 'case', 'when', 'then',
            'else', 'end', 'null', 'count', 'sum', 'avg', 'min', 'max', 'coalesce',
            'cast', 'convert', 'date', 'year', 'month', 'day', 'now', 'today'
        }
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions with better error handling"""
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
                    fields.update(self.standard_frappe_fields)
                    
                    doctypes[doctype_name] = fields
                    
                except Exception as e:
                    print(f"Warning: Could not parse {json_file}: {e}")
                    continue
                    
        return doctypes
    
    def extract_sql_queries(self, content: str) -> List[Tuple[str, int]]:
        """Extract SQL queries from string literals with better filtering"""
        queries = []
        
        # Enhanced SQL patterns
        sql_patterns = [
            # Triple quoted strings containing SQL keywords
            r'"""([^"]*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^"]*)"""',
            r"'''([^']*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^']*)'''",
            # Regular string literals with SQL keywords
            r'"([^"]*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^"]*)"',
            r"'([^']*(?:SELECT|FROM|JOIN|WHERE|INSERT|UPDATE|DELETE)[^']*)'"
        ]
        
        for pattern in sql_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
                sql_content = match.group(1).strip()
                line_num = content[:match.start()].count('\n') + 1
                
                # Enhanced filtering for actual SQL queries
                if (len(sql_content) > 20 and 
                    any(keyword in sql_content.upper() for keyword in ['SELECT', 'FROM', 'JOIN']) and
                    'tab' in sql_content):  # Likely contains Frappe table references
                    queries.append((sql_content, line_num))
                    
        return queries
    
    def extract_table_aliases(self, sql: str) -> Dict[str, str]:
        """Enhanced table alias extraction with better patterns"""
        aliases = {}
        
        # Enhanced patterns for table aliases
        alias_patterns = [
            r'`tab([^`]+)`\s+(?:AS\s+)?(\w+)',  # `tabSEPA Mandate` AS sm or `tabSEPA Mandate` sm
            r'FROM\s+`tab([^`]+)`\s+(?:AS\s+)?(\w+)',  # FROM `tabSEPA Mandate` sm
            r'(?:INNER|LEFT|RIGHT|OUTER)?\s*JOIN\s+`tab([^`]+)`\s+(?:AS\s+)?(\w+)',  # JOIN variations
        ]
        
        for pattern in alias_patterns:
            for match in re.finditer(pattern, sql, re.IGNORECASE):
                doctype = match.group(1)
                alias = match.group(2)
                
                # Skip SQL keywords used as "aliases"
                if alias.lower() not in self.sql_keywords:
                    aliases[alias] = doctype
                
        return aliases
    
    def extract_field_references(self, sql: str, aliases: Dict[str, str]) -> List[Tuple[str, str, str]]:
        """Enhanced field reference extraction with better filtering"""
        field_refs = []
        
        # Pattern for aliased field references: alias.fieldname
        field_pattern = r'(\w+)\.(\w+)'
        
        for match in re.finditer(field_pattern, sql):
            alias = match.group(1)
            field = match.group(2)
            full_ref = f"{alias}.{field}"
            
            # Enhanced keyword filtering
            if alias.lower() in self.sql_keywords or field.lower() in self.sql_keywords:
                continue
                
            # Check if alias maps to a known doctype
            if alias in aliases:
                doctype = aliases[alias]
                field_refs.append((doctype, field, full_ref))
            
        return field_refs
    
    def calculate_confidence(self, doctype: str, field: str, file_path: Path, sql: str) -> str:
        """Calculate confidence level for a field validation issue"""
        
        # Low confidence indicators (likely false positives)
        if any(pattern in str(file_path) for pattern in self.low_priority_patterns):
            return 'low'
        
        # Check for known field mappings (high confidence if mapping exists)
        if doctype in self.field_mappings and field in self.field_mappings[doctype]:
            return 'high'
        
        # Common field patterns that are likely real issues
        common_wrong_fields = {
            'member', 'date', 'email', 'volunteer', 'subscription', 'start_date'
        }
        if field in common_wrong_fields:
            return 'high'
        
        # Medium confidence for other cases
        return 'medium'
    
    def get_suggested_fix(self, doctype: str, field: str) -> Optional[str]:
        """Get suggested fix for a field reference issue"""
        
        # Check known mappings first
        if doctype in self.field_mappings and field in self.field_mappings[doctype]:
            suggested = self.field_mappings[doctype][field]
            if suggested:
                return suggested
            else:
                return f"Use child table or alternative approach (field removed)"
        
        # Try to find similar fields
        if doctype in self.doctypes:
            valid_fields = self.doctypes[doctype]
            
            # Look for exact substring matches first
            for valid_field in valid_fields:
                if field.lower() in valid_field.lower() or valid_field.lower() in field.lower():
                    return valid_field
            
            # Look for common patterns
            field_lower = field.lower()
            for valid_field in valid_fields:
                valid_lower = valid_field.lower()
                if (field_lower.startswith(valid_lower[:3]) or 
                    field_lower.endswith(valid_lower[-3:]) or
                    valid_lower.startswith(field_lower[:3]) or
                    valid_lower.endswith(field_lower[-3:])):
                    return valid_field
        
        return None
    
    def validate_sql_query(self, sql: str, line_num: int, file_path: Path) -> List[ValidationIssue]:
        """Validate field references in a single SQL query with confidence scoring"""
        violations = []
        
        # Extract table aliases
        aliases = self.extract_table_aliases(sql)
        
        # Extract field references
        field_refs = self.extract_field_references(sql, aliases)
        
        # Validate each field reference
        for doctype, field, full_ref in field_refs:
            if doctype in self.doctypes:
                valid_fields = self.doctypes[doctype]
                
                if field not in valid_fields:
                    confidence = self.calculate_confidence(doctype, field, file_path, sql)
                    suggested_fix = self.get_suggested_fix(doctype, field)
                    
                    # Find similar fields for the message
                    similar = self.find_similar_fields(field, doctype)
                    similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                    
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
                        sql_context=sql[:100] + ('...' if len(sql) > 100 else ''),
                        confidence=confidence,
                        issue_type='invalid_sql_field',
                        suggested_fix=suggested_fix
                    ))
                    
        return violations
    
    def find_similar_fields(self, field_name: str, doctype: str) -> List[str]:
        """Find similar field names using enhanced string matching"""
        if doctype not in self.doctypes:
            return []
            
        valid_fields = self.doctypes[doctype]
        similar = []
        
        # Enhanced similarity checks
        field_lower = field_name.lower()
        for valid_field in valid_fields:
            valid_lower = valid_field.lower()
            
            # Exact substring match
            if field_lower in valid_lower or valid_lower in field_lower:
                similar.append(valid_field)
            # Common prefix/suffix (longer than 3 chars)
            elif (len(field_name) >= 4 and len(valid_field) >= 4 and
                  (field_lower.startswith(valid_lower[:4]) or 
                   field_lower.endswith(valid_lower[-4:]) or
                   valid_lower.startswith(field_lower[:4]) or
                   valid_lower.endswith(field_lower[-4:]))):
                similar.append(valid_field)
                
        return similar[:5]  # Return top 5 matches
    
    def extract_data_structure_fields(self, content: str) -> List[Tuple[str, List[str], int]]:
        """Extract field lists from data structures like index definitions"""
        field_structures = []
        
        # Pattern for index definitions with columns
        index_patterns = [
            r'"columns":\s*\[(.*?)\]',  # "columns": ["field1", "field2"]
            r'"expected_columns":\s*\[(.*?)\]',  # "expected_columns": ["field1", "field2"]
            r'columns\s*=\s*\[(.*?)\]',  # columns = ["field1", "field2"]
        ]
        
        # Pattern for table specifications
        table_patterns = [
            r'"table":\s*"tab([^"]+)"',  # "table": "tabSEPA Mandate"
            r'table\s*=\s*"tab([^"]+)"',  # table = "tabSEPA Mandate"
        ]
        
        lines = content.splitlines()
        current_table = None
        
        for line_num, line in enumerate(lines, 1):
            # Try to find table references
            for table_pattern in table_patterns:
                table_match = re.search(table_pattern, line)
                if table_match:
                    current_table = table_match.group(1)
                    break
            
            # Try to find field lists
            for index_pattern in index_patterns:
                field_match = re.search(index_pattern, line, re.DOTALL)
                if field_match and current_table:
                    fields_str = field_match.group(1)
                    
                    # Extract individual field names
                    field_pattern = r'"([^"]+)"'
                    fields = re.findall(field_pattern, fields_str)
                    
                    if fields:
                        field_structures.append((current_table, fields, line_num))
                    break
        
        return field_structures
    
    def validate_data_structure_fields(self, table: str, fields: List[str], line_num: int, file_path: Path) -> List[ValidationIssue]:
        """Validate field references in data structures like index definitions"""
        violations = []
        
        if table in self.doctypes:
            valid_fields = self.doctypes[table]
            
            for field in fields:
                if field not in valid_fields:
                    confidence = 'high'  # Data structure field references are high confidence
                    suggested_fix = self.get_suggested_fix(table, field)
                    
                    # Find similar fields
                    similar = self.find_similar_fields(field, table)
                    similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                    
                    message = f"Field '{field}' does not exist in {table}{similar_text}"
                    if suggested_fix:
                        message += f" → Suggested: {suggested_fix}"
                    
                    violations.append(ValidationIssue(
                        file=str(file_path.relative_to(self.app_path)),
                        line=line_num,
                        field=field,
                        doctype=table,
                        reference=f"{table}.{field}",
                        message=message,
                        sql_context=f"Data structure field reference: {fields}",
                        confidence=confidence,
                        issue_type='invalid_data_structure_field',
                        suggested_fix=suggested_fix
                    ))
        
        return violations
    
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate SQL field references in a file"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Extract SQL queries
            queries = self.extract_sql_queries(content)
            
            # Validate each query
            for sql, line_num in queries:
                violations.extend(self.validate_sql_query(sql, line_num, file_path))
            
            # Extract and validate data structure field references
            data_structures = self.extract_data_structure_fields(content)
            for table, fields, line_num in data_structures:
                violations.extend(self.validate_data_structure_fields(table, fields, line_num, file_path))
                
        except Exception as e:
            print(f"Error validating SQL in {file_path}: {e}")
            
        return violations
    
    def validate_directory(self, directory: str = None) -> List[ValidationIssue]:
        """Validate all Python files in a directory"""
        violations = []
        search_path = Path(directory) if directory else self.app_path
        
        for py_file in search_path.rglob("*.py"):
            # Enhanced file filtering
            file_str = str(py_file)
            if any(skip in file_str for skip in ['test_', 'debug_', '__pycache__', '.pyc']):
                continue
                
            file_violations = self.validate_file(py_file)
            violations.extend(file_violations)
            
        return violations


def main():
    """Main function to run enhanced SQL field validation"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate SQL field references")
    parser.add_argument("--pre-commit", action="store_true", help="Run in pre-commit mode")
    parser.add_argument("file", nargs="?", help="Specific file to validate")
    args = parser.parse_args()
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = EnhancedSQLFieldValidator(app_path)
    
    # Validate specific file if provided
    if args.file:
        file_path = Path(args.file)
        violations = validator.validate_file(file_path)
    else:
        # Validate all files
        violations = validator.validate_directory()
    
    if args.pre_commit:
        # Pre-commit mode: Only show high confidence issues, concise output
        high_conf = [v for v in violations if v.confidence == 'high']
        if high_conf:
            print(f"🚨 Found {len(high_conf)} critical SQL field reference issues:")
            for violation in high_conf:
                print(f"❌ {violation.file}:{violation.line} - {violation.field} not in {violation.doctype}")
                if violation.suggested_fix:
                    print(f"   → Suggested: {violation.suggested_fix}")
            return len(high_conf)
        else:
            return 0
    else:
        # Regular mode: Full detailed output
        if violations:
            # Group by confidence level
            high_conf = [v for v in violations if v.confidence == 'high']
            med_conf = [v for v in violations if v.confidence == 'medium']
            low_conf = [v for v in violations if v.confidence == 'low']
            
            print(f"🔍 Enhanced SQL Field Validation Results:")
            print(f"📊 Total issues: {len(violations)}")
            print(f"🔴 High confidence (likely real issues): {len(high_conf)}")
            print(f"🟡 Medium confidence (needs investigation): {len(med_conf)}")
            print(f"🟢 Low confidence (likely false positives): {len(low_conf)}")
            print()
            
            # Show high confidence issues first
            if high_conf:
                print("🔴 HIGH CONFIDENCE ISSUES (Priority fixes):")
                for violation in high_conf:
                    print(f"❌ {violation.file}:{violation.line}")
                    print(f"   {violation.message}")
                    print(f"   Reference: {violation.reference}")
                    print(f"   SQL: {violation.sql_context}")
                    print()
            
            # Show summary of other confidence levels
            if med_conf:
                print(f"🟡 MEDIUM CONFIDENCE ISSUES ({len(med_conf)} total) - Sample:")
                for violation in med_conf[:3]:  # Show first 3
                    print(f"   {violation.file}:{violation.line} - {violation.reference}")
                if len(med_conf) > 3:
                    print(f"   ... and {len(med_conf) - 3} more")
                print()
            
            if low_conf:
                print(f"🟢 LOW CONFIDENCE ISSUES ({len(low_conf)} total) - Likely false positives")
                for violation in low_conf[:3]:  # Show first 3
                    print(f"   {violation.file}:{violation.line} - {violation.reference}")
                if len(low_conf) > 3:
                    print(f"   ... and {len(low_conf) - 3} more")
                print()
                
        else:
            print("✅ No SQL field reference issues found!")
            
        return len([v for v in violations if v.confidence in ['high', 'medium']])


if __name__ == "__main__":
    exit(main())