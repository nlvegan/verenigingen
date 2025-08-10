#!/usr/bin/env python3
"""
Database Field Issue Inventory

Creates a comprehensive inventory of all database field issues found,
categorized by type, doctype, and severity for analysis.
"""

import ast
import json
from pathlib import Path
from typing import Dict, List, Set, Optional, Union
from collections import defaultdict, Counter


class DatabaseFieldInventory:
    """Creates comprehensive inventory of database field issues"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        self.violations = []
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name')
                    if not doctype_name:
                        continue
                        
                    fields = set()
                    for field in data.get('fields', []):
                        if 'fieldname' in field:
                            fields.add(field['fieldname'])
                    
                    # Add standard fields that exist on all doctypes
                    fields.update([
                        'name', 'creation', 'modified', 'modified_by', 'owner',
                        'docstatus', 'parent', 'parentfield', 'parenttype', 'idx'
                    ])
                    
                    doctypes[doctype_name] = fields
                    
                except Exception as e:
                    print(f"Error loading {json_file}: {e}")
                    
        return doctypes
    
    def extract_query_calls(self, content: str, file_path: Path) -> List[Dict]:
        """Extract database query calls from Python content"""
        queries = []
        
        try:
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    query_info = self.analyze_query_call(node, source_lines, file_path)
                    if query_info:
                        queries.append(query_info)
                        
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return queries
    
    def analyze_query_call(self, node: ast.Call, source_lines: List[str], file_path: Path) -> Optional[Dict]:
        """Analyze a function call to see if it's a database query"""
        
        # Check for frappe.get_all, frappe.db.get_value, etc.
        call_patterns = {
            'frappe.get_all': self.extract_get_all_fields,
            'frappe.db.get_all': self.extract_get_all_fields,
            'frappe.get_list': self.extract_get_all_fields,
            'frappe.db.get_list': self.extract_get_all_fields,
            'frappe.db.get_value': self.extract_get_value_fields,
            'frappe.db.get_values': self.extract_get_value_fields,
        }
        
        # Get the full function call name
        func_name = self.get_function_name(node)
        if not func_name or func_name not in call_patterns:
            return None
            
        # Extract doctype and fields
        extractor = call_patterns[func_name]
        return extractor(node, source_lines, func_name, file_path)
    
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
    
    def extract_get_all_fields(self, node: ast.Call, source_lines: List[str], func_name: str, file_path: Path) -> Optional[Dict]:
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
            'file_path': file_path,
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
    
    def extract_get_value_fields(self, node: ast.Call, source_lines: List[str], func_name: str, file_path: Path) -> Optional[Dict]:
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
            'file_path': file_path,
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
    
    def extract_string_value(self, node: ast.AST) -> Optional[str]:
        """Extract string value from an AST node"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        # Python < 3.8 compatibility - fallback for older AST nodes
        try:
            if hasattr(node, 's') and isinstance(getattr(node, 's', None), str):
                return node.s
        except (AttributeError, TypeError):
            pass
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
        elif self.extract_string_value(node):
            # Single field as string
            field_name = self.extract_string_value(node)
            if field_name:
                fields.append(field_name)
                
        return fields
    
    def categorize_file_type(self, file_path: Path) -> str:
        """Categorize file by type for priority assessment"""
        path_str = str(file_path)
        
        if 'templates/pages/' in path_str:
            return 'user_facing_page'
        elif '/api/' in path_str:
            return 'api_endpoint'
        elif '/doctype/' in path_str and file_path.name.endswith('.py'):
            return 'doctype_controller'
        elif '/tests/' in path_str:
            return 'test_file'
        elif 'debug' in path_str or 'test_' in file_path.name:
            return 'debug_script'
        elif '/utils/' in path_str:
            return 'utility'
        elif '/web_form/' in path_str:
            return 'web_form'
        elif '/report/' in path_str:
            return 'report'
        else:
            return 'other'
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate database queries in a single file"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            queries = self.extract_query_calls(content, file_path)
            
            for query in queries:
                if query['doctype'] not in self.doctypes:
                    continue  # Skip unknown doctypes
                    
                valid_fields = self.doctypes[query['doctype']]
                file_type = self.categorize_file_type(file_path)
                
                # Check filter fields
                for field in query['filter_fields']:
                    if field not in valid_fields:
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'file_type': file_type,
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
                            'file_type': file_type,
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
            # Skip certain directories
            if any(skip in str(py_file) for skip in ['__pycache__', '.git', 'node_modules']):
                continue
                
            file_violations = self.validate_file(py_file)
            violations.extend(file_violations)
            
        return violations
    
    def generate_inventory_report(self, violations: List[Dict]) -> Dict:
        """Generate comprehensive inventory report"""
        report = {
            'summary': {
                'total_issues': len(violations),
                'total_files': len(set(v['file'] for v in violations)),
                'total_doctypes': len(set(v['doctype'] for v in violations)),
            },
            'by_file_type': {},
            'by_doctype': {},
            'by_issue_type': {},
            'by_function': {},
            'most_common_missing_fields': {},
            'critical_user_facing': [],
            'detailed_issues': violations
        }
        
        # Group by file type
        file_type_groups = defaultdict(list)
        for v in violations:
            file_type_groups[v['file_type']].append(v)
            
        for file_type, issues in file_type_groups.items():
            report['by_file_type'][file_type] = {
                'count': len(issues),
                'files': len(set(i['file'] for i in issues)),
                'doctypes': list(set(i['doctype'] for i in issues))
            }
        
        # Group by doctype
        doctype_groups = defaultdict(list)
        for v in violations:
            doctype_groups[v['doctype']].append(v)
            
        for doctype, issues in doctype_groups.items():
            missing_fields = [i['field'] for i in issues]
            report['by_doctype'][doctype] = {
                'count': len(issues),
                'missing_fields': list(set(missing_fields)),
                'files_affected': len(set(i['file'] for i in issues))
            }
        
        # Group by issue type
        issue_type_counts = Counter(v['issue_type'] for v in violations)
        report['by_issue_type'] = dict(issue_type_counts)
        
        # Group by function
        function_counts = Counter(v['function'] for v in violations)
        report['by_function'] = dict(function_counts)
        
        # Most common missing fields
        field_counts = Counter(v['field'] for v in violations)
        report['most_common_missing_fields'] = dict(field_counts.most_common(20))
        
        # Critical user-facing issues
        critical_types = ['user_facing_page', 'api_endpoint', 'web_form']
        critical_issues = [v for v in violations if v['file_type'] in critical_types]
        report['critical_user_facing'] = critical_issues[:50]  # Top 50
        
        return report


def main():
    """Generate comprehensive database field issue inventory"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen"
    
    print("📊 Creating comprehensive database field issue inventory...")
    
    inventory = DatabaseFieldInventory(app_path)
    print(f"📋 Loaded {len(inventory.doctypes)} doctypes")
    
    print("🔍 Scanning all Python files...")
    violations = inventory.validate_app()
    
    print("📈 Generating inventory report...")
    report = inventory.generate_inventory_report(violations)
    
    # Print summary
    print(f"\n{'='*80}")
    print("📊 DATABASE FIELD ISSUE INVENTORY REPORT")
    print(f"{'='*80}")
    
    print(f"\n📋 SUMMARY:")
    print(f"   • Total Issues: {report['summary']['total_issues']}")
    print(f"   • Files Affected: {report['summary']['total_files']}")
    print(f"   • DocTypes Affected: {report['summary']['total_doctypes']}")
    
    print(f"\n🗂️  BY FILE TYPE:")
    for file_type, data in sorted(report['by_file_type'].items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"   • {file_type}: {data['count']} issues in {data['files']} files")
        
    print(f"\n📄 BY DOCTYPE (Top 10):")
    sorted_doctypes = sorted(report['by_doctype'].items(), key=lambda x: x[1]['count'], reverse=True)
    for doctype, data in sorted_doctypes[:10]:
        print(f"   • {doctype}: {data['count']} issues ({data['files_affected']} files)")
        
    print(f"\n🔍 BY ISSUE TYPE:")
    for issue_type, count in report['by_issue_type'].items():
        print(f"   • {issue_type}: {count}")
        
    print(f"\n⚡ BY FUNCTION:")
    for function, count in sorted(report['by_function'].items(), key=lambda x: x[1], reverse=True):
        print(f"   • {function}: {count}")
        
    print(f"\n🏷️  MOST COMMON MISSING FIELDS (Top 15):")
    for field, count in list(report['most_common_missing_fields'].items())[:15]:
        print(f"   • {field}: {count} occurrences")
        
    print(f"\n🚨 CRITICAL USER-FACING ISSUES ({len(report['critical_user_facing'])}):")
    for issue in report['critical_user_facing'][:10]:  # Show first 10
        print(f"   • {issue['file']}:{issue['line']} - {issue['doctype']}.{issue['field']}")
        
    if len(report['critical_user_facing']) > 10:
        print(f"   ... and {len(report['critical_user_facing']) - 10} more critical issues")
    
    # Save detailed report
    output_file = "/home/frappe/frappe-bench/apps/verenigingen/database_field_inventory.json"
    with open(output_file, 'w') as f:
        # Convert Path objects to strings for JSON serialization
        json_report = report.copy()
        for violation in json_report['detailed_issues']:
            if 'file_path' in violation:
                del violation['file_path']  # Remove non-serializable Path object
        json.dump(json_report, f, indent=2, default=str)
    
    print(f"\n💾 Detailed report saved to: {output_file}")
    print(f"{'='*80}")
    
    return 0


if __name__ == "__main__":
    exit(main())