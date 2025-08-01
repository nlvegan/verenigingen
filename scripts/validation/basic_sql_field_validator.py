#!/usr/bin/env python3
"""
SQL Field Validator

Validates field references in SQL string literals to prevent database errors
caused by referencing non-existent columns.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple


class SQLFieldValidator:
    """Validator for SQL string literals containing database field references"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        
        # Common table name patterns
        self.table_patterns = {
            r'`tab([^`]+)`': lambda m: m.group(1),  # `tabSEPA Mandate`
            r'FROM\s+([A-Z][A-Za-z\s]+)\s+': lambda m: m.group(1),  # FROM SEPA Mandate
            r'JOIN\s+([A-Z][A-Za-z\s]+)\s+': lambda m: m.group(1),  # JOIN SEPA Mandate
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
    
    def extract_sql_queries(self, content: str) -> List[Tuple[str, int]]:
        """Extract SQL queries from string literals"""
        queries = []
        
        # Pattern to match multi-line SQL strings
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
                
                # Skip very short strings that aren't real SQL
                if len(sql_content) > 20 and any(keyword in sql_content.upper() 
                                               for keyword in ['SELECT', 'FROM', 'JOIN']):
                    queries.append((sql_content, line_num))
                    
        return queries
    
    def extract_table_aliases(self, sql: str) -> Dict[str, str]:
        """Extract table aliases from SQL (e.g., 'sm' -> 'SEPA Mandate')"""
        aliases = {}
        
        # Pattern for table aliases: `tabDocType` alias or DocType alias
        alias_patterns = [
            r'`tab([^`]+)`\s+(\w+)',  # `tabSEPA Mandate` sm
            r'FROM\s+`tab([^`]+)`\s+(\w+)',  # FROM `tabSEPA Mandate` sm
            r'JOIN\s+`tab([^`]+)`\s+(\w+)',  # JOIN `tabSEPA Mandate` sm
        ]
        
        for pattern in alias_patterns:
            for match in re.finditer(pattern, sql, re.IGNORECASE):
                doctype = match.group(1)
                alias = match.group(2)
                aliases[alias] = doctype
                
        return aliases
    
    def extract_field_references(self, sql: str, aliases: Dict[str, str]) -> List[Tuple[str, str, str]]:
        """Extract field references from SQL (alias.field -> doctype, field, alias.field)"""
        field_refs = []
        
        # Pattern for aliased field references: alias.fieldname
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
                
            # Check if alias maps to a known doctype
            if alias in aliases:
                doctype = aliases[alias]
                field_refs.append((doctype, field, full_ref))
            
        return field_refs
    
    def validate_sql_query(self, sql: str, line_num: int, file_path: Path) -> List[Dict]:
        """Validate field references in a single SQL query"""
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
                    # Find similar fields for suggestions
                    similar = self.find_similar_fields(field, doctype)
                    similar_text = f" (similar: {', '.join(similar[:3])})" if similar else ""
                    
                    violations.append({
                        'file': str(file_path.relative_to(self.app_path)),
                        'line': line_num,
                        'field': field,
                        'doctype': doctype,
                        'reference': full_ref,
                        'type': 'invalid_sql_field',
                        'message': f"Field '{field}' does not exist in {doctype}{similar_text}",
                        'sql_context': sql[:100] + ('...' if len(sql) > 100 else '')
                    })
                    
        return violations
    
    def find_similar_fields(self, field_name: str, doctype: str) -> List[str]:
        """Find similar field names using simple string matching"""
        if doctype not in self.doctypes:
            return []
            
        valid_fields = self.doctypes[doctype]
        similar = []
        
        # Simple similarity checks
        for valid_field in valid_fields:
            # Exact substring match
            if field_name.lower() in valid_field.lower() or valid_field.lower() in field_name.lower():
                similar.append(valid_field)
            # Common prefix/suffix
            elif (field_name.lower().startswith(valid_field[:3].lower()) or 
                  field_name.lower().endswith(valid_field[-3:].lower())):
                similar.append(valid_field)
                
        return similar[:5]  # Return top 5 matches
    
    def validate_file(self, file_path: Path) -> List[Dict]:
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
                
        except Exception as e:
            print(f"Error validating SQL in {file_path}: {e}")
            
        return violations
    
    def validate_directory(self, directory: str = None) -> List[Dict]:
        """Validate all Python files in a directory"""
        violations = []
        search_path = Path(directory) if directory else self.app_path
        
        for py_file in search_path.rglob("*.py"):
            # Skip test files and debug files
            if any(skip in str(py_file) for skip in ['test_', 'debug_', '__pycache__']):
                continue
                
            file_violations = self.validate_file(py_file)
            violations.extend(file_violations)
            
        return violations


def main():
    """Main function to run SQL field validation"""
    import sys
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = SQLFieldValidator(app_path)
    
    # Validate specific file if provided
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        violations = validator.validate_file(file_path)
    else:
        # Validate all files
        violations = validator.validate_directory()
    
    if violations:
        print(f"🚨 Found {len(violations)} SQL field reference issues:")
        print()
        
        for violation in violations:
            print(f"❌ {violation['file']}:{violation['line']}")
            print(f"   Field '{violation['field']}' does not exist in {violation['doctype']}")
            print(f"   Reference: {violation['reference']}")
            print(f"   {violation['message']}")
            print(f"   SQL: {violation['sql_context']}")
            print()
    else:
        print("✅ No SQL field reference issues found!")
        
    return len(violations)


if __name__ == "__main__":
    exit(main())