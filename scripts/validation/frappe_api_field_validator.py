#!/usr/bin/env python3
"""
Database Query Field Validator

Validates field names in database queries (frappe.get_all, frappe.db.get_value, etc.)
to catch references to non-existent fields before runtime.

This complements the existing field validators which focus on attribute access.
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Union
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata


class DatabaseQueryFieldValidator:
    """Validates field names in database queries"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        
        # Initialize comprehensive DocType loader
        # Calculate bench path correctly from app path
        bench_path = self.app_path.parent.parent  # From apps/verenigingen to bench root
        self.doctype_loader = DocTypeLoader(str(bench_path), verbose=False)
        self.doctypes = self._convert_doctypes_for_compatibility()
        print(f"🔗 Database query validator loaded {len(self.doctypes)} DocTypes")
        
        self.violations = []
        
    def _convert_doctypes_for_compatibility(self) -> Dict[str, Set[str]]:
        """Convert doctype_loader format to simple dict for compatibility"""
        simple_format = {}
        doctype_metas = self.doctype_loader.get_doctypes()
        
        for doctype_name, doctype_meta in doctype_metas.items():
            field_names = self.doctype_loader.get_field_names(doctype_name)
            simple_format[doctype_name] = set(field_names)
        
        return simple_format
    
    def extract_query_calls(self, content: str) -> List[Dict]:
        """Extract database query calls from Python content"""
        queries = []
        
        try:
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    query_info = self.analyze_query_call(node, source_lines)
                    if query_info:
                        queries.append(query_info)
                        
        except Exception as e:
            print(f"Error parsing content: {e}")
            
        return queries
    
    def analyze_query_call(self, node: ast.Call, source_lines: List[str]) -> Optional[Dict]:
        """Analyze a function call to see if it's a database query"""
        
        # Check for frappe.get_all, frappe.db.get_value, etc.
        call_patterns = {
            'frappe.get_all': self.extract_get_all_fields,
            'frappe.db.get_all': self.extract_get_all_fields,
            'frappe.get_list': self.extract_get_all_fields,
            'frappe.db.get_list': self.extract_get_all_fields,
            'frappe.db.get_value': self.extract_get_value_fields,
            'frappe.db.get_values': self.extract_get_value_fields,
            'frappe.db.sql': self.extract_sql_fields,  # Basic SQL validation
        }
        
        # Get the full function call name
        func_name = self.get_function_name(node)
        if not func_name or func_name not in call_patterns:
            return None
            
        # Extract doctype and fields
        extractor = call_patterns[func_name]
        return extractor(node, source_lines, func_name)
    
    def get_function_name(self, node: ast.Call) -> Optional[str]:
        """Extract the full function name from a call node"""
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Attribute):
                # frappe.db.get_all
                if (isinstance(node.func.value.value, ast.Name) and 
                    node.func.value.value.id == 'frappe'):
                    return f"frappe.{node.func.value.attr}.{node.func.attr}"
            elif isinstance(node.func.value, ast.Name) and node.func.value.id == 'frappe':
                # frappe.get_all
                return f"frappe.{node.func.attr}"
        return None
    
    def extract_get_all_fields(self, node: ast.Call, source_lines: List[str], func_name: str) -> Optional[Dict]:
        """Extract fields from frappe.get_all() calls"""
        if not node.args:
            return None
            
        # First argument should be doctype
        doctype = self.extract_string_value(node.args[0])
        if not doctype:
            return None
            
        result = {
            'line': node.lineno,
            'function': func_name,
            'doctype': doctype,
            'context': source_lines[node.lineno - 1].strip() if node.lineno <= len(source_lines) else "",
            'filter_fields': [],
            'select_fields': []
        }
        
        # Look for filters and fields in keyword arguments
        for keyword in node.keywords:
            if keyword.arg == 'filters':
                result['filter_fields'] = self.extract_filter_fields(keyword.value)
            elif keyword.arg == 'fields':
                result['select_fields'] = self.extract_field_list(keyword.value)
        
        return result
    
    def extract_get_value_fields(self, node: ast.Call, source_lines: List[str], func_name: str) -> Optional[Dict]:
        """Extract fields from frappe.db.get_value() calls"""
        if len(node.args) < 2:
            return None
            
        doctype = self.extract_string_value(node.args[0])
        if not doctype:
            return None
            
        result = {
            'line': node.lineno,
            'function': func_name,
            'doctype': doctype,
            'context': source_lines[node.lineno - 1].strip() if node.lineno <= len(source_lines) else "",
            'filter_fields': [],
            'select_fields': []
        }
        
        # Second argument can be filters (dict) or name (string)
        if len(node.args) > 1:
            filters = self.extract_filter_fields(node.args[1])
            if filters:
                result['filter_fields'] = filters
        
        # Third argument is usually the fields to select
        if len(node.args) > 2:
            result['select_fields'] = self.extract_field_list(node.args[2])
            
        return result
    
    def extract_sql_fields(self, node: ast.Call, source_lines: List[str], func_name: str) -> Optional[Dict]:
        """Basic SQL field extraction (limited)"""
        # This is more complex as it requires SQL parsing
        # For now, just return the context for manual review
        return {
            'line': node.lineno,
            'function': func_name,
            'doctype': 'SQL_QUERY',
            'context': source_lines[node.lineno - 1].strip() if node.lineno <= len(source_lines) else "",
            'filter_fields': [],
            'select_fields': [],
            'note': 'SQL queries require manual validation'
        }
    
    def extract_string_value(self, node: ast.AST) -> Optional[str]:
        """Extract string value from an AST node"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        # Fallback for older Python versions
        elif hasattr(node, 's') and isinstance(getattr(node, 's', None), str):
            return node.s
        return None
    
    def extract_filter_fields(self, node: ast.AST) -> List[str]:
        """Extract field names from filter dictionaries"""
        fields = []
        
        if isinstance(node, ast.Dict):
            for key in node.keys:
                field_name = self.extract_string_value(key)
                if field_name:
                    fields.append(field_name)
                    
        return fields
    
    def extract_field_list(self, node: ast.AST) -> List[str]:
        """Extract field names from field lists"""
        fields = []
        
        if isinstance(node, ast.List):
            for item in node.elts:
                field_name = self.extract_string_value(item)
                if field_name:
                    fields.append(field_name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Single field as string
            field_name = self.extract_string_value(node)
            if field_name:
                fields.append(field_name)
        # Fallback for older Python versions
        elif hasattr(node, 's') and isinstance(getattr(node, 's', None), str):
            field_name = self.extract_string_value(node)
            if field_name:
                fields.append(field_name)
                
        return fields
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate database queries in a single file"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            queries = self.extract_query_calls(content)
            
            for query in queries:
                if query['doctype'] not in self.doctypes:
                    continue  # Skip unknown doctypes
                    
                valid_fields = self.doctypes[query['doctype']]
                
                # Check filter fields
                for field in query['filter_fields']:
                    if field not in valid_fields:
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': query['line'],
                            'field': field,
                            'doctype': query['doctype'],
                            'context': query['context'],
                            'issue_type': 'filter_field',
                            'function': query['function']
                        })
                
                # Check select fields  
                for field in query['select_fields']:
                    if field not in valid_fields:
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': query['line'],
                            'field': field,
                            'doctype': query['doctype'],
                            'context': query['context'],
                            'issue_type': 'select_field',
                            'function': query['function']
                        })
                        
        except Exception as e:
            print(f"Error validating {file_path}: {e}")
            
        return violations
    
    def validate_app(self) -> List[Dict]:
        """Validate database queries in the entire app"""
        violations = []
        
        # Check Python files throughout the app
        for py_file in self.app_path.rglob("**/*.py"):
            # Skip test files and __pycache__
            if '__pycache__' in str(py_file) or '.git' in str(py_file):
                continue
                
            file_violations = self.validate_file(py_file)
            violations.extend(file_violations)
            
        return violations


def main():
    """Run the database query field validator"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Running database query field validation...")
    
    validator = DatabaseQueryFieldValidator(app_path)
    
    print(f"📋 Loaded {len(validator.doctypes)} doctypes")
    
    violations = validator.validate_app()
    
    if violations:
        print(f"\n❌ Found {len(violations)} database query field issues:")
        print("-" * 80)
        
        for v in violations:
            print(f"📁 {v['file']}:{v['line']}")
            print(f"   🏷️  {v['doctype']}.{v['field']} - Field does not exist")
            print(f"   📋 {v['issue_type']} in {v['function']}()")
            print(f"   💾 {v['context']}")
            print()
            
        return 1
    else:
        print("✅ No database query field issues found!")
        return 0


if __name__ == "__main__":
    exit(main())