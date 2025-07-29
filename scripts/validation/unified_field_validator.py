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
        
        # Python standard library modules and common patterns that should not be validated as field references
        self.python_stdlib_patterns = {
            'time', 'datetime', 'json', 'os', 'sys', 'math', 'random', 'collections',
            'itertools', 'functools', 'pathlib', 'urllib', 'hashlib', 'uuid', 're',
            'ast', 'inspect', 'traceback', 'logging', 'unittest', 'subprocess',
            'threading', 'queue', 'socket', 'email', 'base64', 'csv', 'xml',
            'html', 'http', 'copy', 'pickle', 'tempfile', 'shutil', 'glob'
        }
        
        # Common test method names and variables that should not be validated
        self.test_patterns = {
            'assertEqual', 'assertTrue', 'assertFalse', 'assertIn', 'assertNotIn',
            'assertIsNone', 'assertIsNotNone', 'assertRaises', 'assertWarns',
            'test_member', 'test_volunteer', 'test_chapter', 'test_application',
            'test_data', 'test_result', 'mock_member', 'mock_volunteer'
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
    
    def should_skip_pattern(self, object_name: str, field_name: str, context: str = "") -> bool:
        """Check if an object.field pattern should be skipped as a false positive"""
        
        # Skip Python standard library calls
        if object_name.lower() in self.python_stdlib_patterns:
            return True
            
        # Skip common test patterns
        if object_name.lower() in self.test_patterns or field_name.lower() in self.test_patterns:
            return True
            
        # Skip frappe framework methods
        if object_name == 'frappe' and field_name in {'whitelist', 'api', 'client', 'utils', 'model', 'desk'}:
            return True
            
        # Skip method calls (indicated by parentheses after field)
        if '(' in context and ')' in context:
            return True
            
        # Skip obvious method names (contain verbs or end in common method suffixes)
        method_suffixes = ['_method', '_function', '_handler', '_callback', '_validator', '_manager']
        if any(field_name.lower().endswith(suffix) for suffix in method_suffixes):
            return True
            
        # Skip module imports and attribute access
        if any(pattern in context.lower() for pattern in ['import ', 'from ', 'class ', 'def ']):
            return True
            
        return False
    
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
        """Extract table aliases from SQL with improved detection"""
        aliases = {}
        
        # Enhanced patterns for tables with aliases - must not match SQL keywords as aliases
        alias_patterns = [
            r'FROM\s+`tab([^`]+)`\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\s*(?:WHERE|ORDER|GROUP|LIMIT|ON|SET|;|$|,))',
            r'JOIN\s+`tab([^`]+)`\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\s*(?:ON|WHERE|ORDER|GROUP|LIMIT|;|$))',
            r'UPDATE\s+`tab([^`]+)`\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\s*(?:SET|WHERE|ORDER|GROUP|LIMIT|;|$))',
            # Multiple table FROM patterns
            r',\s*`tab([^`]+)`\s+(?:AS\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*(?=\s*(?:WHERE|ORDER|GROUP|LIMIT|ON|SET|;|$|,))'
        ]
        
        # Patterns for tables without aliases (implicit table reference)
        implicit_table_patterns = [
            r'FROM\s+`tab([^`]+)`\s*(?=\s*(?:WHERE|ORDER|GROUP|LIMIT|;|$))',  # FROM `tabDoctype` followed by clause or end
            r'UPDATE\s+`tab([^`]+)`\s*(?=\s*(?:SET|WHERE|ORDER|GROUP|LIMIT|;|$))',  # UPDATE `tabDoctype`
            r'INSERT\s+INTO\s+`tab([^`]+)`\s*(?=\s*(?:VALUES|SELECT|;|$))',  # INSERT INTO `tabDoctype`
        ]
        
        # List of common SQL keywords that should never be treated as aliases
        sql_keywords = {
            'WHERE', 'ORDER', 'GROUP', 'HAVING', 'BY', 'ASC', 'DESC', 'LIMIT', 'OFFSET',
            'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN', 'IS', 'NULL', 'COUNT', 'SUM', 
            'AVG', 'MIN', 'MAX', 'DISTINCT', 'AS', 'ON', 'SET', 'VALUES', 'SELECT',
            'FROM', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'OUTER', 'UNION', 'ALL'
        }
        
        # Extract explicit aliases
        for pattern in alias_patterns:
            for match in re.finditer(pattern, sql, re.IGNORECASE):
                doctype = match.group(1)
                alias = match.group(2)
                
                # Skip if alias is a SQL keyword
                if alias.upper() not in sql_keywords:
                    aliases[alias] = doctype
        
        # For queries without aliases, try to determine the primary table
        if not aliases:  # Only if no explicit aliases found
            for pattern in implicit_table_patterns:
                for match in re.finditer(pattern, sql, re.IGNORECASE):
                    doctype = match.group(1)
                    # Use a special marker to indicate this is the implicit table
                    aliases['__implicit__'] = doctype
                    break
                
        return aliases
    
    def extract_field_references(self, sql: str, aliases: Dict[str, str]) -> List[Tuple[str, str, str]]:
        """Extract field references from SQL with improved filtering"""
        field_refs = []
        
        # Comprehensive SQL keywords and functions to skip
        sql_keywords = {
            'SELECT', 'FROM', 'WHERE', 'ORDER', 'GROUP', 'HAVING', 'BY', 'ASC', 'DESC',
            'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN', 'IS', 'NULL', 'COUNT', 'SUM', 
            'AVG', 'MIN', 'MAX', 'COALESCE', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
            'JOIN', 'INNER', 'LEFT', 'RIGHT', 'OUTER', 'ON', 'UNION', 'DISTINCT',
            'LIMIT', 'OFFSET', 'AS', 'ALL', 'ANY', 'SOME', 'EXISTS', 'SET', 'VALUES',
            'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'DATE', 'TIME', 'NOW', 'CURDATE',
            'CAST', 'CONVERT', 'IFNULL', 'CONCAT', 'SUBSTRING', 'TRIM', 'UPPER', 'LOWER',
            'ABS', 'ROUND', 'FLOOR', 'CEIL', 'IF', 'GREATEST', 'LEAST'
        }
        
        # Common status/enum values that appear in SQL but aren't fields
        sql_enum_values = {
            'Active', 'Inactive', 'Pending', 'Cancelled', 'Completed', 'Draft',
            'Submitted', 'Failed', 'Success', 'Open', 'Closed', 'Approved',
            'Rejected', 'Processing', 'Compliant', 'Exception', 'Enabled', 'Disabled'
        }
        
        # Single-letter aliases commonly used in SQL (these are almost never field names)
        single_letter_aliases = {'v', 'm', 'c', 't', 'd', 's', 'p', 'u', 'a', 'b', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'n', 'o', 'q', 'r', 'w', 'x', 'y', 'z'}
        
        # Common multi-letter SQL aliases that are not field names
        common_aliases = {'cm', 'tm', 'sm', 'mds', 'cbm', 'si', 'mtr', 'vs', 'ta', 'va', 'de', 'pe', 'tr'}
        
        # Check if this SQL contains aggregate functions (more lenient validation)
        has_aggregates = bool(re.search(r'\b(COUNT|SUM|AVG|MIN|MAX|GROUP_CONCAT)\s*\(', sql, re.IGNORECASE))
        
        # Check if this SQL contains date/time functions  
        has_date_functions = bool(re.search(r'\b(YEAR|MONTH|DAY|DATE|TIME|NOW|CURDATE)\s*\(', sql, re.IGNORECASE))
        
        # Check if this SQL has calculated fields or expressions
        has_calculations = bool(re.search(r'\bAS\s+\w+|\w+\s*[+\-*/]\s*\w+', sql, re.IGNORECASE))
        
        # Look for explicit alias.field references
        field_pattern = r'(\w+)\.(\w+)'
        for match in re.finditer(field_pattern, sql):
            alias = match.group(1)
            field = match.group(2)
            full_ref = f"{alias}.{field}"
            
            # Skip SQL keywords and functions
            if (alias.upper() in sql_keywords or 
                field.upper() in sql_keywords or
                field in sql_enum_values):
                continue
            
            # Skip single-letter aliases (very common in SQL, almost never real field references)
            if alias.lower() in single_letter_aliases:
                continue
                
            # Skip common multi-letter aliases
            if alias.lower() in common_aliases:
                continue
                
            # Be more lenient with aggregate queries - they often have calculated fields
            if has_aggregates or has_date_functions or has_calculations:
                # Only validate if we're very confident this is a real field reference
                # Skip fields that look like calculated columns
                if ('_count' in field.lower() or 'total_' in field.lower() or 
                    field.lower().endswith('_date') or field.lower().startswith('avg_') or
                    field.lower().startswith('sum_') or field.lower().startswith('count_')):
                    continue
                
            # Only validate aliases that we recognize as table aliases
            if alias in aliases:
                doctype = aliases[alias]
                field_refs.append((doctype, field, full_ref))
        
        # Handle implicit table references (queries without aliases) - be more conservative
        if '__implicit__' in aliases and not field_refs and not (has_aggregates or has_calculations):
            implicit_doctype = aliases['__implicit__']
            
            # Look for bare field names in WHERE clauses when there's an implicit table
            where_match = re.search(r'WHERE\s+(.+?)(?:ORDER\s+BY|GROUP\s+BY|LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)
            if where_match:
                where_clause = where_match.group(1)
                
                # Extract field names from WHERE clause (more conservative)
                field_names = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{2,})\s*[=<>!]', where_clause)  # At least 3 chars
                for field_name in field_names:
                    if (field_name.upper() not in sql_keywords and 
                        field_name not in sql_enum_values and
                        not field_name.lower().startswith('tab')):
                        field_refs.append((implicit_doctype, field_name, field_name))
            
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
    
    def validate_get_single_value_calls(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate get_single_value calls for Singles doctypes"""
        violations = []
        
        # Patterns to match get_single_value calls
        patterns = [
            # frappe.db.get_single_value("DocType", "field")
            r'frappe\.db\.get_single_value\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
            # frappe.get_single_value("DocType", "field")  
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
    
    def validate_filter_dictionaries(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate database filter dictionary patterns"""
        violations = []
        
        # Common SQL operators and keywords that are not field names
        sql_operators = {
            'in', 'like', 'between', 'not', 'is', 'null', 'and', 'or',
            '>=', '<=', '>', '<', '=', '!=', '!='
        }
        
        # Common enum/status values that are not field names
        common_status_values = {
            'Active', 'Inactive', 'Pending', 'Cancelled', 'Completed', 'Draft', 
            'Submitted', 'Failed', 'Success', 'Open', 'Closed', 'Approved',
            'Rejected', 'Processing', 'Compliant', 'Exception', 'Pending Review',
            'MONTH', 'YEAR', 'DAY', 'WEEK', 'HOUR', 'MINUTE', 'ASC', 'DESC'
        }
        
        # Patterns to match database calls with filter dictionaries
        filter_patterns = [
            r'frappe\.(?:db\.)?(?:get_all|get_list|exists|count)\(\s*["\']([^"\']+)["\']\s*,\s*[^)]*filters\s*=\s*(\{[^}]+\})',
        ]
        
        for pattern in filter_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                doctype = match.group(1)
                filter_dict_str = match.group(2)
                line_num = content[:match.start()].count('\n') + 1
                
                # Extract potential field names from the filter dictionary
                field_matches = re.findall(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', filter_dict_str)
                
                # More sophisticated parsing - only check strings that appear as keys
                key_pattern = r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']:\s*'
                key_matches = re.findall(key_pattern, filter_dict_str)
                
                if doctype in self.doctypes:
                    doctype_fields = self.doctypes[doctype]
                    
                    # Only validate strings that are actually filter keys, not values
                    for field_name in key_matches:
                        # Skip SQL operators and common status values
                        if (field_name.lower() in sql_operators or 
                            field_name in common_status_values or
                            field_name not in doctype_fields):
                            
                            # Only report if it's not a known operator/status value
                            if (field_name.lower() not in sql_operators and 
                                field_name not in common_status_values):
                                violations.append(ValidationIssue(
                                    file=str(file_path.relative_to(self.app_path)),
                                    line=line_num,
                                    field=field_name,
                                    doctype=doctype,
                                    reference=f"filter dict: {field_name}",
                                    message=f"Field '{field_name}' in filter dictionary does not exist in '{doctype}'",
                                    context=self._get_line_context(content, line_num),
                                    confidence="medium",  # Reduced confidence due to filter complexity
                                    issue_type="missing_filter_field",
                                    suggested_fix=f"Add field '{field_name}' to {doctype} doctype or check field name"
                                ))
        
        return violations
    
    def validate_set_single_value_calls(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate set_single_value calls for Singles doctypes"""
        violations = []
        
        # Patterns to match set_single_value calls
        patterns = [
            r'frappe\.db\.set_single_value\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,',
            r'frappe\.set_single_value\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*,',
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
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"set_single_value: {field_name}",
                            message=f"Field '{field_name}' does not exist in Singles doctype '{doctype}'",
                            context=self._get_line_context(content, line_num),
                            confidence="high",
                            issue_type="missing_singles_field_write",
                            suggested_fix=f"Add field '{field_name}' to {doctype} doctype or verify field name"
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
            
            # Validate get_single_value calls
            violations.extend(self.validate_get_single_value_calls(content, file_path))
            
            # Validate database filter dictionaries
            violations.extend(self.validate_filter_dictionaries(content, file_path))
            
            # Validate set_single_value calls
            violations.extend(self.validate_set_single_value_calls(content, file_path))
            
            # Validate SQL WHERE/ORDER BY/GROUP BY field patterns
            violations.extend(self.validate_sql_field_patterns(content, file_path))
            
            # Validate email template field variables
            violations.extend(self.validate_email_template_variables(content, file_path))
            
            # Validate report column/filter definitions
            violations.extend(self.validate_report_field_patterns(content, file_path))
            
            # Validate meta field validation calls
            violations.extend(self.validate_meta_field_patterns(content, file_path))
            
        except Exception as e:
            print(f"Error validating {file_path}: {e}")
            
        return violations
    
    def validate_html_file(self, file_path: Path) -> List[ValidationIssue]:
        """Validate field references in HTML template files"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Only validate email template variables for HTML files
            violations.extend(self.validate_email_template_variables(content, file_path))
            
        except Exception as e:
            print(f"Error validating HTML file {file_path}: {e}")
            
        return violations
    
    def validate_sql_field_patterns(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate SQL WHERE/ORDER BY/GROUP BY field references with improved filtering"""
        violations = []
        
        # More conservative patterns that focus on clear field references
        sql_patterns = [
            # Only validate WHERE clauses with clear table context
            (r'FROM\s+`tab(\w+)`[^`]*WHERE\s+([a-zA-Z_][a-zA-Z0-9_]{2,})\s*[=<>!]', 'WHERE clause', 1, 2),
            # Skip ORDER BY and GROUP BY entirely for now - too many false positives
        ]
        
        # Comprehensive list of SQL keywords and functions
        sql_keywords = {
            'SELECT', 'FROM', 'WHERE', 'ORDER', 'GROUP', 'HAVING', 'BY', 'AND', 'OR', 'NOT',
            'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'AS', 'LIKE', 'IN', 'ASC', 'DESC',
            'BETWEEN', 'IS', 'NULL', 'LIMIT', 'OFFSET', 'JOIN', 'INNER', 'LEFT', 'RIGHT',
            'UNION', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'CAST', 'CONVERT', 'COALESCE',
            'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'DATE', 'TIME', 'NOW', 'CURDATE'
        }
        
        for pattern_data in sql_patterns:
            if len(pattern_data) == 4:
                pattern, clause_type, doctype_group, field_group = pattern_data
            else:
                pattern, clause_type = pattern_data
                doctype_group, field_group = 1, 2
                
            for match in re.finditer(pattern, content, re.IGNORECASE):
                if len(match.groups()) >= max(doctype_group, field_group):
                    doctype = match.group(doctype_group) if doctype_group <= len(match.groups()) else None
                    field_name = match.group(field_group)
                else:
                    continue
                    
                line_num = content[:match.start()].count('\n') + 1
                
                # Skip SQL keywords and functions
                if field_name.upper() in sql_keywords:
                    continue
                
                # Skip calculated fields and common patterns
                if (field_name.endswith('_count') or field_name.startswith('total_') or
                    field_name.startswith('avg_') or field_name.startswith('sum_') or
                    field_name.lower() in ['enabled', 'disabled', 'active', 'inactive']):
                    continue
                
                # If we extracted doctype from pattern, use it; otherwise guess from context
                if not doctype:
                    doctype = self._guess_doctype_from_sql_context(content, match.start())
                
                if doctype and doctype in self.doctypes:
                    doctype_fields = self.doctypes[doctype]
                    
                    if field_name not in doctype_fields:
                        confidence = self.calculate_confidence(doctype, field_name, file_path, content[max(0, match.start()-100):match.end()+100])
                        suggested_fix = self.get_suggested_fix(doctype, field_name)
                        similar = self.find_similar_fields(field_name, doctype)
                        similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"SQL {clause_type}: {field_name}",
                            message=f"Field '{field_name}' does not exist in {doctype}{similar_text}",
                            context=self._get_line_context(content, line_num),
                            confidence=confidence,
                            issue_type="sql_field_clause",
                            suggested_fix=suggested_fix
                        ))
        
        return violations
    
    def validate_email_template_variables(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate email template field variables in HTML files"""
        violations = []
        
        # Enhanced patterns for Jinja2 template variables
        template_patterns = [
            (r'\{\{\s*doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}', 'template variable'),
            (r'\{\{\s*doc\.([a-zA-Z_][a-zA-Z0-9_]*)\|[^}]*\}\}', 'template variable with filter'),
            (r'\{%\s*if\s+doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*%\}', 'template condition'),
            (r'\{%\s*for\s+\w+\s+in\s+doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*%\}', 'template loop'),
            (r'\{%\s*set\s+\w+\s*=\s*doc\.([a-zA-Z_][a-zA-Z0-9_]*)\s*%\}', 'template assignment'),
        ]
        
        for pattern, pattern_type in template_patterns:
            for match in re.finditer(pattern, content):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Try to determine doctype from template context
                doctype = self._guess_doctype_from_template_context(content, match.start())
                
                if doctype and doctype in self.doctypes:
                    doctype_fields = self.doctypes[doctype]
                    
                    if field_name not in doctype_fields:
                        confidence = "medium"  # Template variables can have false positives
                        suggested_fix = self.get_suggested_fix(doctype, field_name)
                        similar = self.find_similar_fields(field_name, doctype)
                        similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"template: doc.{field_name}",
                            message=f"Field '{field_name}' in {pattern_type} does not exist in {doctype}{similar_text}",
                            context=self._get_line_context(content, line_num),
                            confidence=confidence,
                            issue_type="email_template_field",
                            suggested_fix=suggested_fix
                        ))
        
        return violations
    
    def validate_report_field_patterns(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate report column/filter field definitions"""
        violations = []
        
        # Patterns for report configurations
        report_patterns = [
            (r'columns\s*=\s*\[.*?{.*?"fieldname"\s*:\s*["\']([^"\']*)["\']', 'column definition'),
            (r'filters\s*=\s*\[.*?{.*?"fieldname"\s*:\s*["\']([^"\']*)["\']', 'filter definition'),
            (r'{\s*["\']fieldname["\']\s*:\s*["\']([^"\']*)["\']', 'fieldname property'),
            (r'"fieldname"\s*:\s*["\']([^"\']*)["\']', 'fieldname value'),
        ]
        
        for pattern, pattern_type in report_patterns:
            for match in re.finditer(pattern, content, re.DOTALL):
                field_name = match.group(1)
                line_num = content[:match.start()].count('\n') + 1
                
                # Try to determine doctype from report context
                doctype = self._guess_doctype_from_report_context(content, match.start())
                
                if doctype and doctype in self.doctypes:
                    doctype_fields = self.doctypes[doctype]
                    
                    if field_name not in doctype_fields:
                        confidence = "high"  # Report configurations are high confidence
                        suggested_fix = self.get_suggested_fix(doctype, field_name)
                        similar = self.find_similar_fields(field_name, doctype)
                        similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"report {pattern_type}: {field_name}",
                            message=f"Field '{field_name}' in {pattern_type} does not exist in {doctype}{similar_text}",
                            context=self._get_line_context(content, line_num),
                            confidence=confidence,
                            issue_type="report_field_definition",
                            suggested_fix=suggested_fix
                        ))
        
        return violations
    
    def validate_meta_field_patterns(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """Validate meta field validation calls"""
        violations = []
        
        # Patterns for meta field access
        meta_patterns = [
            (r'frappe\.get_meta\(["\']([^"\']*)["\']?\)\.get_field\(["\']([^"\']*)["\']?\)', 'get_meta().get_field()'),
            (r'frappe\.get_meta\(["\']([^"\']*)["\']?\)\.has_field\(["\']([^"\']*)["\']?\)', 'get_meta().has_field()'),
            (r'meta\.get_field\(["\']([^"\']*)["\']?\)', 'meta.get_field()'),
            (r'meta\.has_field\(["\']([^"\']*)["\']?\)', 'meta.has_field()'),
        ]
        
        for pattern, pattern_type in meta_patterns:
            for match in re.finditer(pattern, content):
                if match.lastindex == 2:  # Pattern with doctype and field
                    doctype = match.group(1)
                    field_name = match.group(2)
                else:  # Pattern with just field (meta variable context)
                    field_name = match.group(1)
                    doctype = self._guess_doctype_from_meta_context(content, match.start())
                
                line_num = content[:match.start()].count('\n') + 1
                
                if doctype and doctype in self.doctypes:
                    doctype_fields = self.doctypes[doctype]
                    
                    if field_name not in doctype_fields:
                        confidence = "high"  # Meta field calls are high confidence
                        suggested_fix = self.get_suggested_fix(doctype, field_name)
                        similar = self.find_similar_fields(field_name, doctype)
                        similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field=field_name,
                            doctype=doctype,
                            reference=f"meta: {pattern_type}",
                            message=f"Field '{field_name}' in {pattern_type} does not exist in {doctype}{similar_text}",
                            context=self._get_line_context(content, line_num),
                            confidence=confidence,
                            issue_type="meta_field_access",
                            suggested_fix=suggested_fix
                        ))
        
        return violations
    
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
            r'"ref_doctype"\s*:\s*"([^"]*)"',
            r"'ref_doctype'\s*:\s*'([^']*)'",
            r'"doctype"\s*:\s*"([^"]*)"',
            r"'doctype'\s*:\s*'([^']*)'",
            r'get_all\("([^"]*)"',
            r"get_all\('([^']*)'",
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
            r'meta\s*=\s*frappe\.get_meta\("([^"]*)"\)',
            r'meta\s*=\s*frappe\.get_meta\(\'([^\']*)\'\)',
            r'get_meta\("([^"]*)"\)',
            r'get_meta\(\'([^\']*)\'\)',
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
            r'{{.*?doctype.*?"([^"]*)".*?}}',
            r"{{.*?doctype.*?'([^']*)'.*?}}",
            r'{%\s*set.*?doctype.*?"([^"]*)".*?%}',
            r"{%\s*set.*?doctype.*?'([^']*)'.*?%}",
        ]
        
        for pattern in template_patterns:
            matches = list(re.finditer(pattern, context_before, re.IGNORECASE))
            if matches:
                doctype_name = matches[-1].group(1).strip()
                # Clean up doctype name
                if doctype_name.replace(' ', '') in self.doctypes:
                    return doctype_name.replace(' ', '')
        
        return None
    
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
        
        # Validate HTML files for template variables
        for html_file in self.app_path.rglob("*.html"):
            if any(skip in str(html_file) for skip in ['__pycache__', '/tests/']):
                continue
            
            violations = self.validate_html_file(html_file)
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
                    for violation in med_conf:
                        print(f"   {violation.file}:{violation.line} - {violation.message}")
                        print(f"   Reference: {violation.reference}")
                        print(f"   Context: {violation.context}")
                        print()
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