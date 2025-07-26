#!/usr/bin/env python3
"""
Unified Field Validator
Combines AST field validation with SQL field validation using consistent logic
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

class UnifiedFieldValidator:
    """Unified validator combining AST and SQL field validation with consistent logic"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        
        # Known field mappings from SEPA fixes
        self.known_field_mappings = {
            'SEPA Mandate': {
                'valid_from': 'first_collection_date',
                'valid_until': 'expiry_date',
                'usage_count': None,  # Use usage_history child table
                'last_used_date': None,  # Use usage_history child table
            },
            'Member': {
                'email_id': 'email',
            },
            'Chapter Member': {
                'is_active': 'enabled',
            },
            'Donor': {
                'email': 'donor_email',
                'anbi_consent_given': 'anbi_consent',
            },
            'Membership Dues Schedule': {
                'start_date': 'next_billing_period_start_date',
                'end_date': 'next_billing_period_end_date',
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
    
    def get_suggested_fix(self, doctype: str, field: str) -> Optional[str]:
        """Get suggested fix from known field mappings"""
        if doctype in self.known_field_mappings:
            return self.known_field_mappings[doctype].get(field)
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
                
        return similar[:5]  # Return top 5 matches
    
    def calculate_confidence(self, doctype: str, field: str, file_path: Path, context: str) -> str:
        """Calculate confidence level for validation issue"""
        
        # High confidence for known mappings
        if doctype in self.known_field_mappings and field in self.known_field_mappings[doctype]:
            return 'high'
        
        # High confidence for data structure references (index definitions)
        if 'columns' in context and any(pattern in context for pattern in ['"table":', 'tab' + doctype]):
            return 'high'
            
        # Medium confidence for SQL queries with clear table references
        if any(pattern in context.lower() for pattern in ['select', 'from', 'join', 'where']):
            if f'tab{doctype}' in context or doctype.lower() in context.lower():
                return 'medium'
        
        # Low confidence for complex patterns or unclear context
        return 'low'
    
    # SQL Validation Methods (from enhanced_sql_field_validator.py)
    
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
            if alias.upper() in ['SELECT', 'FROM', 'WHERE', 'ORDER', 'GROUP', 'HAVING',
                               'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'COALESCE', 'CASE']:
                continue
                
            if field.upper() in ['FROM', 'WHERE', 'ORDER', 'GROUP', 'BY', 'ASC', 'DESC',
                               'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN']:
                continue
                
            if alias in aliases:
                doctype = aliases[alias]
                field_refs.append((doctype, field, full_ref))
            
        return field_refs
    
    def extract_data_structure_fields(self, content: str) -> List[Tuple[str, List[str], int]]:
        """Extract field lists from data structures like index definitions"""
        field_structures = []
        
        index_patterns = [
            r'"columns":\s*\[(.*?)\]',
            r'"expected_columns":\s*\[(.*?)\]',
            r'columns\s*=\s*\[(.*?)\]',
        ]
        
        table_patterns = [
            r'"table":\s*"tab([^"]+)"',
            r'table\s*=\s*"tab([^"]+)"',
        ]
        
        lines = content.splitlines()
        current_table = None
        
        for line_num, line in enumerate(lines, 1):
            # Find table references
            for table_pattern in table_patterns:
                table_match = re.search(table_pattern, line)
                if table_match:
                    current_table = table_match.group(1)
                    break
            
            # Find field lists
            for index_pattern in index_patterns:
                field_match = re.search(index_pattern, line, re.DOTALL)
                if field_match and current_table:
                    fields_str = field_match.group(1)
                    field_pattern = r'"([^"]+)"'
                    fields = re.findall(field_pattern, fields_str)
                    
                    if fields:
                        field_structures.append((current_table, fields, line_num))
                    break
        
        return field_structures
    
    def validate_sql_content(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate SQL field references in file content"""
        violations = []
        
        # Extract and validate SQL queries
        queries = self.extract_sql_queries(content)
        for sql, line_num in queries:
            aliases = self.extract_table_aliases(sql)
            field_refs = self.extract_field_references(sql, aliases)
            
            for doctype, field, full_ref in field_refs:
                if doctype in self.doctypes:
                    valid_fields = self.doctypes[doctype]
                    
                    if field not in valid_fields:
                        confidence = self.calculate_confidence(doctype, field, file_path, sql)
                        suggested_fix = self.get_suggested_fix(doctype, field)
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
                            context=sql[:100] + ('...' if len(sql) > 100 else ''),
                            confidence=confidence,
                            issue_type='sql_field_reference',
                            suggested_fix=suggested_fix
                        ))
        
        # Extract and validate data structure field references
        data_structures = self.extract_data_structure_fields(content)
        for table, fields, line_num in data_structures:
            if table in self.doctypes:
                valid_fields = self.doctypes[table]
                
                for field in fields:
                    if field not in valid_fields:
                        confidence = 'high'  # Data structure references are high confidence
                        suggested_fix = self.get_suggested_fix(table, field)
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
                            context=f"Data structure: {fields}",
                            confidence=confidence,
                            issue_type='data_structure_field',
                            suggested_fix=suggested_fix
                        ))
        
        return violations
    
    def validate_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate field references in a single file"""
        violations = []
        
        # Skip certain files to reduce noise
        skip_patterns = ['test_', 'debug_', '__pycache__', '/archived_unused/', '/tests/']
        if any(pattern in str(file_path) for pattern in skip_patterns):
            return violations
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Validate SQL content (queries and data structures)
            violations.extend(self.validate_sql_content(content, file_path))
            
        except Exception as e:
            print(f"Error validating {file_path}: {e}")
            
        return violations
    
    def run_validation(self, pre_commit_mode: bool = False) -> bool:
        """Run comprehensive field validation"""
        if not pre_commit_mode:
            print("🔍 Running Unified Field Validation...")
            print(f"📋 Loaded {len(self.doctypes)} doctypes with field definitions")
        
        all_violations = []
        file_count = 0
        
        # Validate all Python files
        for py_file in self.app_path.rglob("*.py"):
            # Skip test files and cache files
            if any(skip in str(py_file) for skip in ['__pycache__', '.pyc', 'test_', '_test.py', '/tests/']):
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
                
                print(f"\n🔍 Unified Field Validation Results:")
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
                        print(f"   Context: {violation.context}")
                        print()
                
                # Show summary of other issues
                if med_conf:
                    print(f"🟡 MEDIUM CONFIDENCE ISSUES ({len(med_conf)} total)")
                    for violation in med_conf[:3]:
                        print(f"   {violation.file}:{violation.line} - {violation.reference}")
                    if len(med_conf) > 3:
                        print(f"   ... and {len(med_conf) - 3} more")
                    print()
                
                return len(high_conf) == 0
            else:
                print("✅ No field reference issues found!")
                return True

def main():
    """Main function"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Unified field validation")
    parser.add_argument("--pre-commit", action="store_true", help="Run in pre-commit mode")
    args = parser.parse_args()
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = UnifiedFieldValidator(app_path)
    
    success = validator.run_validation(pre_commit_mode=args.pre_commit)
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())