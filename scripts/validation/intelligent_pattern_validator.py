#!/usr/bin/env python3
"""
Smart Field Validator - Focuses on real issues, ignores framework noise
Based on lessons learned from analyzing 8,479 validation results
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata


class SmartFieldValidator:
    """Smart field validation that focuses on real issues"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        
        # Initialize comprehensive DocType loader
        bench_path = self.app_path.parent.parent
        self.doctype_loader = DocTypeLoader(str(bench_path), verbose=False)
        self.doctypes = self._convert_doctypes_for_compatibility()
        print(f"🤖 Intelligent validator loaded {len(self.doctypes)} DocTypes")
        
        # Known problematic patterns from our analysis
        self.critical_field_patterns = {
            'amount',  # Changed to dues_rate in Membership Dues Schedule
            'suggested_contribution', 
            'minimum_contribution',
            'maximum_contribution',
            'default_amount',  # Changed to minimum_amount in Membership Type
        }
        
        # Framework attributes that are NOT field access issues
        self.framework_attributes = {
            # Frappe framework
            'whitelist', 'get_doc', 'new_doc', 'get_value', 'get_all', 'db', 'session',
            'throw', 'msgprint', 'log_error', 'utils', 'local', 'response',
            
            # Python/system attributes
            'path', 'exists', 'load', 'loads', 'dumps', 'join', 'split', 'strip',
            'format', 'replace', 'startswith', 'endswith', 'lower', 'upper',
            'append', 'remove', 'insert', 'save', 'delete', 'update', 'get',
            'keys', 'values', 'items', 'reload', 'today', 'now', 'add_days',
            
            # Common object methods/properties
            'name', 'creation', 'modified', 'status', 'enabled', 'is_active',
            'member', 'volunteer', 'chapter', 'role', 'email', 'user',
        }
        
    def _convert_doctypes_for_compatibility(self) -> Dict[str, Set[str]]:
        """Convert doctype_loader format to simple dict for compatibility"""
        simple_format = {}
        doctype_metas = self.doctype_loader.get_doctypes()
        
        for doctype_name, doctype_meta in doctype_metas.items():
            field_names = self.doctype_loader.get_field_names(doctype_name)
            simple_format[doctype_name] = set(field_names)
        
        return simple_format
    
    def is_critical_pattern(self, field_name: str, line_content: str) -> bool:
        """Check if this is a critical field pattern we care about"""
        
        # Focus on our known problematic patterns
        if field_name not in self.critical_field_patterns:
            return False
            
        # Additional context checks to reduce false positives
        critical_contexts = [
            'membership', 'dues', 'billing', 'contribution', 'template'
        ]
        
        line_lower = line_content.lower()
        return any(context in line_lower for context in critical_contexts)
    
    def is_sql_field_reference(self, line_content: str) -> List[str]:
        """Check for SQL field references that might be problematic"""
        problematic_sql = []
        
        # Look for SQL queries with our critical fields
        if 'select' in line_content.lower() and any(field in line_content.lower() for field in self.critical_field_patterns):
            for field in self.critical_field_patterns:
                if field in line_content.lower():
                    # Check if it's in a table that we care about
                    if any(table in line_content.lower() for table in [
                        'tabmembership dues schedule',
                        'tabmembership type', 
                        'tabmember'
                    ]):
                        problematic_sql.append(field)
                        
        return problematic_sql
    
    def analyze_file_focused(self, file_path: Path) -> List[Dict]:
        """Analyze file with focus on real issues only"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            source_lines = content.splitlines()
            
            # Check for SQL field references
            for line_no, line in enumerate(source_lines, 1):
                sql_issues = self.is_sql_field_reference(line)
                for field in sql_issues:
                    violations.append({
                        'file': str(file_path.relative_to(self.app_path)),
                        'line': line_no,
                        'field': field,
                        'content': line.strip(),
                        'type': 'sql_field_reference',
                        'severity': 'high',
                        'description': f'SQL query references deprecated field "{field}"'
                    })
            
            # Parse AST for Python field access
            try:
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        field_name = node.attr
                        line_no = node.lineno
                        
                        if line_no <= len(source_lines):
                            line_content = source_lines[line_no - 1].strip()
                        else:
                            continue
                            
                        # Skip framework attributes
                        if field_name in self.framework_attributes:
                            continue
                            
                        # Only flag critical patterns
                        if self.is_critical_pattern(field_name, line_content):
                            violations.append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': line_no,
                                'field': field_name,
                                'content': line_content,
                                'type': 'critical_field_access',
                                'severity': 'high',
                                'description': f'Field "{field_name}" may be deprecated or incorrect'
                            })
                            
            except SyntaxError:
                # Skip files with syntax errors
                pass
                
        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")
            
        return violations
    
    def validate_app_focused(self) -> List[Dict]:
        """Validate app with focus on real issues"""
        violations = []
        files_checked = 0
        
        print(f"🎯 Smart validation of {self.app_path}...")
        print(f"📊 Focusing on {len(self.critical_field_patterns)} critical field patterns")
        
        # Prioritize production code over debug scripts
        production_patterns = [
            '*/api/*.py',
            '*/doctype/*/*.py',
            '*/templates/**/*.py',
            '*/utils/*.py',
            '*/page/*/*.py'
        ]
        
        debug_patterns = [
            'debug*.py',
            '**/debug/*.py',
            'test*.py'
        ]
        
        # Check production code first
        for pattern in production_patterns:
            for py_file in self.app_path.glob(pattern):
                if self._should_check_file(py_file):
                    files_checked += 1
                    file_violations = self.analyze_file_focused(py_file)
                    if file_violations:
                        print(f"  ⚠️  {len(file_violations)} issues in {py_file.relative_to(self.app_path)}")
                    violations.extend(file_violations)
        
        # Check debug files separately (lower priority)
        debug_violations = []
        for pattern in debug_patterns:
            for py_file in self.app_path.glob(pattern):
                if self._should_check_file(py_file):
                    file_violations = self.analyze_file_focused(py_file)
                    debug_violations.extend(file_violations)
        
        print(f"📈 Checked {files_checked} production files")
        print(f"🔍 Found {len(violations)} production issues, {len(debug_violations)} debug issues")
        
        return violations, debug_violations
    
    def _should_check_file(self, file_path: Path) -> bool:
        """Check if file should be validated"""
        skip_patterns = [
            '__pycache__', '.git', 'node_modules', 'migrations',
            'patches', 'archived', 'backup', '.disabled'
        ]
        
        return not any(skip in str(file_path) for skip in skip_patterns)
    
    def generate_smart_report(self, violations: List[Dict], debug_violations: List[Dict] = None) -> str:
        """Generate a focused, actionable report"""
        if not violations and not debug_violations:
            return "✅ No critical field reference issues found!"
        
        report = []
        
        if violations:
            report.append(f"🚨 CRITICAL ISSUES ({len(violations)} found)")
            report.append("=" * 50)
            
            # Group by severity and type
            by_severity = {}
            for v in violations:
                severity = v.get('severity', 'medium')
                if severity not in by_severity:
                    by_severity[severity] = []
                by_severity[severity].append(v)
            
            for severity in ['high', 'medium', 'low']:
                if severity not in by_severity:
                    continue
                    
                report.append(f"\n## {severity.upper()} PRIORITY ({len(by_severity[severity])} issues)")
                
                # Group by file
                by_file = {}
                for v in by_severity[severity]:
                    file_path = v['file']
                    if file_path not in by_file:
                        by_file[file_path] = []
                    by_file[file_path].append(v)
                
                for file_path, file_violations in by_file.items():
                    report.append(f"\n### 📁 {file_path}")
                    for v in file_violations:
                        report.append(f"  - Line {v['line']}: `{v['field']}` - {v['description']}")
                        report.append(f"    Context: `{v['content']}`")
                        
                        # Provide specific fix suggestions
                        if v['field'] == 'amount':
                            if 'membership dues schedule' in v['content'].lower():
                                report.append(f"    💡 Fix: Replace `{v['field']}` with `dues_rate`")
                            elif 'membership type' in v['content'].lower():
                                report.append(f"    💡 Fix: Replace `{v['field']}` with `minimum_amount`")
        
        if debug_violations:
            report.append(f"\n\n🔧 DEBUG/TEST FILES ({len(debug_violations)} issues)")
            report.append("These are lower priority but should be fixed eventually:")
            for v in debug_violations[:5]:  # Show first 5
                report.append(f"  - {v['file']}:{v['line']} - {v['field']}")
            if len(debug_violations) > 5:
                report.append(f"  ... and {len(debug_violations) - 5} more")
        
        report.append(f"\n\n📊 SUMMARY:")
        report.append(f"  - Production code issues: {len(violations)}")
        report.append(f"  - Debug/test issues: {len(debug_violations) if debug_violations else 0}")
        report.append(f"  - Total issues: {len(violations) + len(debug_violations) if debug_violations else len(violations)}")
        
        return '\n'.join(report)


def main():
    """Main function with smart validation"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🧠 Running SMART field validation...")
    print("   Focusing on real issues, ignoring framework noise")
    
    validator = SmartFieldValidator(app_path)
    
    print(f"📚 Loaded {len(validator.doctypes)} doctypes")
    print(f"🎯 Tracking {len(validator.critical_field_patterns)} critical field patterns")
    
    violations, debug_violations = validator.validate_app_focused()
    
    report = validator.generate_smart_report(violations, debug_violations)
    print("\n" + "="*60)
    print(report)
    
    total_issues = len(violations) + (len(debug_violations) if debug_violations else 0)
    
    if violations:
        print(f"\n❌ Found {len(violations)} CRITICAL issues that need immediate attention")
        return 1
    elif debug_violations:
        print(f"\n⚠️  Found {len(debug_violations)} debug/test issues (lower priority)")
        return 0  
    else:
        print("\n✅ No critical field reference issues found!")
        return 0


if __name__ == "__main__":
    exit(main())