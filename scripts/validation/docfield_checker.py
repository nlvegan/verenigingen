#!/usr/bin/env python3
"""
Focused Docfield Checker
Targets the most common real field reference issues
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata


class DocfieldChecker:
    """Focused checker for common docfield issues"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        
        # Initialize comprehensive DocType loader
        bench_path = self.app_path.parent.parent
        self.doctype_loader = DocTypeLoader(str(bench_path), verbose=False)
        self.doctypes = self._convert_doctypes_for_compatibility()
        print(f"📋 Docfield checker loaded {len(self.doctypes)} DocTypes")
        
    def _convert_doctypes_for_compatibility(self) -> Dict[str, Set[str]]:
        """Convert doctype_loader format to simple dict for compatibility"""
        simple_format = {}
        doctype_metas = self.doctype_loader.get_doctypes()
        
        for doctype_name, doctype_meta in doctype_metas.items():
            field_names = self.doctype_loader.get_field_names(doctype_name)
            simple_format[doctype_name] = set(field_names)
        
        return simple_format
    
    
    def check_doctype_files(self) -> List[Dict]:
        """Check files in doctype directories for field references"""
        violations = []
        
        for doctype_dir in self.app_path.rglob("**/doctype/*/"):
            doctype_name = doctype_dir.name
            
            # Skip if we don't have the doctype definition
            if doctype_name not in self.doctypes:
                continue
                
            valid_fields = self.doctypes[doctype_name]
            
            # Check Python files in this doctype directory
            for py_file in doctype_dir.glob("*.py"):
                if py_file.name.startswith('test_'):
                    continue
                    
                file_violations = self.check_file_for_fields(py_file, doctype_name, valid_fields)
                violations.extend(file_violations)
                
        return violations
    
    def check_file_for_fields(self, file_path: Path, doctype_name: str, valid_fields: Set[str]) -> List[Dict]:
        """Check a specific file for field reference issues"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            lines = content.splitlines()
            
            # Focus on the most common problematic patterns
            patterns = [
                # Direct field access on self (most common in doctype files)
                (r'self\.([a-zA-Z_][a-zA-Z0-9_]*)', 'self'),
                # Field access on doc variable
                (r'doc\.([a-zA-Z_][a-zA-Z0-9_]*)', 'doc'),
                # frappe.db.get_value field references
                (r'frappe\.db\.get_value\([^,]+,\s*[^,]+,\s*["\']([^"\']+)["\']', 'db_get_value'),
                # frappe.db.set_value field references
                (r'frappe\.db\.set_value\([^,]+,\s*[^,]+,\s*["\']([^"\']+)["\']', 'db_set_value'),
                # hasattr checks
                (r'hasattr\([^,]+,\s*["\']([^"\']+)["\']', 'hasattr'),
                # getattr calls
                (r'getattr\([^,]+,\s*["\']([^"\']+)["\']', 'getattr'),
            ]
            
            for pattern, context_type in patterns:
                for match in re.finditer(pattern, content):
                    field_name = match.group(1)
                    line_num = content[:match.start()].count('\n') + 1
                    
                    # Skip obvious false positives
                    if self.is_false_positive(field_name, context_type, lines[line_num - 1] if line_num <= len(lines) else ""):
                        continue
                        
                    # Check if field exists in doctype
                    if field_name not in valid_fields:
                        violations.append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': line_num,
                            'field': field_name,
                            'doctype': doctype_name,
                            'pattern': context_type,
                            'context': lines[line_num - 1].strip() if line_num <= len(lines) else ""
                        })
                        
        except Exception as e:
            print(f"Error checking {file_path}: {e}")
            
        return violations
    
    def is_false_positive(self, field_name: str, context_type: str, line_content: str) -> bool:
        """Check if this is likely a false positive"""
        
        # Always skip these common method names and attributes
        skip_always = {
            'save', 'insert', 'delete', 'reload', 'submit', 'cancel', 'validate',
            'before_save', 'after_insert', 'before_delete', 'on_update', 'on_submit',
            'on_cancel', 'before_submit', 'before_cancel', 'after_delete',
            'flags', 'meta', 'as_dict', 'as_json', 'get_formatted',
            'run_method', 'has_permission', 'get_doc_before_save',
            'get_title', 'get_feed', 'get_timeline_data', 'doctype',
            'db_set', 'db_get', 'set_value', 'get_value'
        }
        
        if field_name in skip_always:
            return True
            
        # Skip private attributes
        if field_name.startswith('_'):
            return True
            
        # Skip if it's clearly a method call (has parentheses after)
        if '(' in line_content and line_content.find('(') > line_content.find(field_name):
            return True
            
        # Skip if it's in a string literal (not a field reference)
        if field_name in ['"', "'"] or line_content.count('"') % 2 == 1 or line_content.count("'") % 2 == 1:
            return True
            
        # Context-specific false positives
        if context_type == 'self':
            # Skip common class attributes that aren't docfields
            if field_name in ['logger', 'config', 'settings', 'cache', 'session', 'user', 'context']:
                return True
                
        return False
    
    def generate_summary(self, violations: List[Dict]) -> str:
        """Generate a concise summary of violations"""
        if not violations:
            return "✅ No field reference issues found in doctype files!"
            
        # Group by doctype
        by_doctype = {}
        for violation in violations:
            doctype = violation['doctype']
            if doctype not in by_doctype:
                by_doctype[doctype] = []
            by_doctype[doctype].append(violation)
            
        summary = []
        summary.append(f"❌ Found {len(violations)} potential field reference issues:")
        summary.append("")
        
        # Show top issues by doctype
        for doctype, doctype_violations in sorted(by_doctype.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
            summary.append(f"**{doctype}** ({len(doctype_violations)} issues):")
            
            # Show most common fields
            field_counts = {}
            for v in doctype_violations:
                field_counts[v['field']] = field_counts.get(v['field'], 0) + 1
                
            for field, count in sorted(field_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                examples = [v for v in doctype_violations if v['field'] == field][:2]
                summary.append(f"  - `{field}` ({count}x): {examples[0]['file']}:{examples[0]['line']}")
                
            summary.append("")
            
        return '\n'.join(summary)
    
    def find_likely_corrections(self, violations: List[Dict]) -> List[str]:
        """Suggest likely corrections for common issues"""
        suggestions = []
        
        # Group violations by field name
        field_violations = {}
        for violation in violations:
            field = violation['field']
            if field not in field_violations:
                field_violations[field] = []
            field_violations[field].append(violation)
            
        # Look for common patterns
        for field, field_viols in field_violations.items():
            if len(field_viols) < 2:  # Only suggest for recurring issues
                continue
                
            # Check if there's a similar field name in the doctype
            doctype = field_viols[0]['doctype']
            if doctype in self.doctypes:
                similar_fields = []
                for existing_field in self.doctypes[doctype]:
                    if (field.lower() in existing_field.lower() or 
                        existing_field.lower() in field.lower() or
                        abs(len(field) - len(existing_field)) <= 2):
                        similar_fields.append(existing_field)
                        
                if similar_fields:
                    suggestions.append(f"💡 `{field}` ({len(field_viols)}x) → Maybe `{similar_fields[0]}`? ({doctype})")
                    
        return suggestions[:10]


def main():
    """Main function"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Checking docfield references in doctype files...")
    checker = DocfieldChecker(app_path)
    
    print(f"📋 Loaded {len(checker.doctypes)} doctypes")
    
    violations = checker.check_doctype_files()
    
    # Generate summary
    summary = checker.generate_summary(violations)
    print(summary)
    
    # Show suggestions
    suggestions = checker.find_likely_corrections(violations)
    if suggestions:
        print("\n🔧 Suggested corrections:")
        for suggestion in suggestions:
            print(f"  {suggestion}")
    
    # Save detailed report
    if violations:
        report_file = Path(app_path) / "docfield_issues_report.json"
        import json
        with open(report_file, 'w') as f:
            json.dump(violations, f, indent=2)
        print(f"\n📄 Detailed report saved to: {report_file}")
        
    return 1 if violations else 0


if __name__ == "__main__":
    exit(main())