#!/usr/bin/env python3
"""
Final Field Validator
Ultra-precise validation focusing only on clear field access patterns
"""

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Union


class FinalFieldValidator:
    """Ultra-precise field validation"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self.load_doctypes()
        
    def load_doctypes(self) -> Dict[str, Set[str]]:
        """Load doctype field definitions"""
        doctypes = {}
        
        for json_file in self.app_path.rglob("**/doctype/*/*.json"):
            if json_file.name == json_file.parent.name + ".json":
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        
                    doctype_name = data.get('name', json_file.stem)
                    
                    # Extract actual field names only
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
    
    def get_doctype_from_file_path(self, file_path: Path) -> Optional[str]:
        """Extract doctype name from file path"""
        parts = file_path.parts
        if 'doctype' in parts:
            doctype_idx = parts.index('doctype')
            if doctype_idx + 1 < len(parts):
                doctype_dir = parts[doctype_idx + 1]
                doctype_name = doctype_dir.replace('_', ' ').title()
                return doctype_name
        return None
    
    def is_definitely_field_access(self, node: ast.Attribute, source_lines: List[str]) -> bool:
        """Check if this is definitely a field access (not a method call)"""
        
        # Only check self.attribute patterns
        if not isinstance(node.value, ast.Name) or node.value.id != 'self':
            return False
            
        # Skip Frappe framework built-in attributes
        frappe_builtin_attributes = {
            'flags', 'meta', '_doc_before_save', 'doctype', 'name', 'owner',
            'creation', 'modified', 'modified_by', 'docstatus', 'parent',
            'parenttype', 'parentfield', 'idx', '_user_tags', '_comments',
            '_assign', '_liked_by', '_doc_before_validate', '_doc_before_insert',
            '_doc_before_update', '_doc_before_cancel', '_doc_before_delete',
            '_original_modified'
        }
        
        if node.attr in frappe_builtin_attributes:
            return False
            
        # Skip internal/private attributes (start with _)
        if node.attr.startswith('_'):
            return False
            
        # Skip common property patterns that aren't fields
        property_patterns = {
            'board_manager', 'member_manager', 'communication_manager',
            'volunteer_integration_manager', 'validator', 'is_anbi_eligible'
        }
        
        if node.attr in property_patterns:
            return False
            
        # Get the line content
        line_num = node.lineno - 1
        if line_num >= len(source_lines):
            return False
            
        line = source_lines[line_num].strip()
        
        # Skip if it's clearly a method call
        if f"{node.attr}(" in line:
            return False
            
        # Skip if it's an assignment to self (defining methods/properties)
        if f"self.{node.attr} =" in line:
            return False
            
        # Skip if it's in a function definition line
        if line.startswith('def ') and f"{node.attr}(" in line:
            return False
            
        # Skip common patterns that are definitely not fields
        skip_patterns = [
            f"self.{node.attr}()",  # Method call
            f"def {node.attr}(",    # Method definition  
            f"self.{node.attr} = ",  # Assignment
            f"hasattr(self, '{node.attr}')",  # hasattr check
            f'hasattr(self, "{node.attr}")',  # hasattr check
        ]
        
        for pattern in skip_patterns:
            if pattern in line:
                return False
                
        # Look for field access patterns
        field_access_patterns = [
            f"self.{node.attr}",  # Direct access
            f"if self.{node.attr}",  # Conditional
            f"or self.{node.attr}",  # Boolean operation
            f"and self.{node.attr}",  # Boolean operation
            f"not self.{node.attr}",  # Boolean operation
            f"self.{node.attr} or",  # Boolean operation
            f"self.{node.attr} and",  # Boolean operation
            f"return self.{node.attr}",  # Return statement
            f"self.{node.attr}.",  # Chained access
        ]
        
        for pattern in field_access_patterns:
            if pattern in line:
                return True
                
        return False
    
    def validate_file(self, file_path: Path) -> List[Dict]:
        """Validate a single file"""
        violations = []
        
        # Only check files in doctype directories
        doctype_name = self.get_doctype_from_file_path(file_path)
        if not doctype_name or doctype_name not in self.doctypes:
            return violations
            
        valid_fields = self.doctypes[doctype_name]
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            # Find attribute access nodes
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    if self.is_definitely_field_access(node, source_lines):
                        field_name = node.attr
                        
                        # Check if this field exists in the doctype
                        if field_name not in valid_fields:
                            # Get context
                            line_num = node.lineno - 1
                            context = source_lines[line_num].strip() if line_num < len(source_lines) else ""
                            
                            violations.append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': node.lineno,
                                'field': field_name,
                                'doctype': doctype_name,
                                'context': context,
                                'confidence': 'high'
                            })
                            
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return violations
    
    def validate_file_comprehensive(self, file_path: Path) -> List[Dict]:
        """Validate a file with comprehensive DocType detection"""
        violations = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse AST for better accuracy
            try:
                tree = ast.parse(content)
                source_lines = content.splitlines()
                
                # Find attribute access patterns
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        attr_name = node.attr
                        
                        # Skip common non-field attributes
                        if attr_name in {'name', 'insert', 'save', 'delete', 'get', 'set', 
                                       'append', 'remove', 'update', 'keys', 'values', 
                                       'items', 'format', 'replace', 'split', 'join',
                                       'strip', 'lower', 'upper', 'startswith', 'endswith'}:
                            continue
                            
                        # Try to determine context and validate field
                        violation = self.check_field_access_comprehensive(
                            node, attr_name, file_path, source_lines
                        )
                        if violation:
                            violations.append(violation)
                            
            except SyntaxError:
                # If AST parsing fails, fall back to regex
                violations.extend(self.validate_with_regex(content, file_path))
                
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return violations
    
    def check_field_access_comprehensive(self, node: ast.Attribute, attr_name: str, 
                                       file_path: Path, source_lines: List[str]) -> Optional[Dict]:
        """Check if field access is valid with comprehensive DocType detection"""
        
        # Get the line content for context
        line_no = node.lineno - 1
        if line_no < len(source_lines):
            line_content = source_lines[line_no].strip()
        else:
            line_content = ""
            
        # Detect potential DocType references in various patterns
        detected_doctypes = self.detect_doctypes_in_context(node, line_content, source_lines, line_no)
        
        # Check if the field exists in any of the detected DocTypes
        for doctype in detected_doctypes:
            if doctype in self.doctypes and attr_name in self.doctypes[doctype]:
                return None  # Valid field access
                
        # If we detected specific DocTypes and the field doesn't exist in any of them
        if detected_doctypes:
            return {
                "file": str(file_path),
                "line": node.lineno,
                "content": line_content,
                "field": attr_name,
                "detected_doctypes": detected_doctypes,
                "type": "invalid_field_access"
            }
            
        # For unknown context, check if it's a known problematic pattern
        if self.is_suspicious_field_pattern(attr_name, line_content):
            return {
                "file": str(file_path),
                "line": node.lineno,
                "content": line_content,
                "field": attr_name,
                "detected_doctypes": ["Unknown"],
                "type": "suspicious_field_access"
            }
            
        return None
    
    def detect_doctypes_in_context(self, node: ast.Attribute, line_content: str, 
                                  source_lines: List[str], line_no: int) -> List[str]:
        """Detect which DocTypes might be referenced in the current context"""
        detected = []
        
        # Method 1: Look for explicit DocType references in the line
        line_lower = line_content.lower()
        for doctype in self.doctypes.keys():
            if doctype.lower().replace(' ', '') in line_lower or \
               doctype.lower().replace(' ', '_') in line_lower:
                detected.append(doctype)
                
        # Method 2: Look for frappe.get_doc patterns
        import re
        get_doc_patterns = [
            r'frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.new_doc\(\s*["\']([^"\']+)["\']',
            r'doctype\s*=\s*["\']([^"\']+)["\']'
        ]
        
        for pattern in get_doc_patterns:
            matches = re.findall(pattern, line_content)
            detected.extend(matches)
            
        # Method 3: Look for table alias patterns (like mt.amount -> Membership Type)
        alias_patterns = {
            'mt': 'Membership Type',
            'mem': 'Member', 
            'schedule': 'Membership Dues Schedule',
            'membership_type': 'Membership Type',
            'member': 'Member'
        }
        
        # Extract the object being accessed (before the dot)
        if hasattr(node, 'value') and hasattr(node.value, 'id'):
            obj_name = node.value.id
            if obj_name in alias_patterns:
                detected.append(alias_patterns[obj_name])
                
        # Method 4: Look at surrounding context (previous lines for variable assignments)
        context_lines = max(0, line_no - 5)
        for i in range(context_lines, line_no):
            if i < len(source_lines):
                prev_line = source_lines[i]
                for doctype in self.doctypes.keys():
                    if doctype in prev_line and ('=' in prev_line or 'get_doc' in prev_line):
                        detected.append(doctype)
                        
        return list(set(detected))  # Remove duplicates
    
    def is_suspicious_field_pattern(self, attr_name: str, line_content: str) -> bool:
        """Check if this looks like a suspicious field access pattern"""
        
        # Known problematic patterns we want to catch
        suspicious_patterns = [
            'amount',  # The specific field we were missing
            'suggested_contribution',
            'minimum_contribution', 
            'maximum_contribution'
        ]
        
        if attr_name in suspicious_patterns:
            # Additional context checks to reduce false positives
            if any(indicator in line_content.lower() for indicator in [
                'membership', 'member', 'dues', 'billing', 'contribution'
            ]):
                return True
                
        return False
    
    def validate_with_regex(self, content: str, file_path: Path) -> List[Dict]:
        """Fallback regex validation for when AST parsing fails"""
        violations = []
        import re
        
        # Pattern to catch .amount and similar suspicious patterns
        pattern = r'(\w+)\.(' + '|'.join([
            'amount(?!_)', 'suggested_contribution', 'minimum_contribution', 
            'maximum_contribution'
        ]) + r')\b'
        
        lines = content.splitlines()
        for line_no, line in enumerate(lines, 1):
            matches = re.finditer(pattern, line)
            for match in matches:
                violations.append({
                    "file": str(file_path),
                    "line": line_no,
                    "content": line.strip(),
                    "field": match.group(2),
                    "detected_doctypes": ["RegexDetected"],
                    "type": "regex_detected_suspicious"
                })
                
        return violations
    
    def validate_app(self) -> List[Dict]:
        """Validate the entire app with comprehensive coverage"""
        violations = []
        files_checked = 0
        
        print(f"🔍 Scanning all Python files in {self.app_path}...")
        
        # Check ALL Python files, not just those in doctype directories
        for py_file in self.app_path.rglob("**/*.py"):
            # Skip certain directories and files
            if any(skip in str(py_file) for skip in [
                'node_modules', '__pycache__', '.git', 'migrations',
                'archived_unused', 'backup', '.disabled', 'patches'
            ]):
                continue
                
            # Skip test files for now (they have different patterns)
            if py_file.name.startswith('test_') or '/tests/' in str(py_file):
                continue
            
            files_checked += 1
            
            # Use comprehensive validation for all files
            file_violations = self.validate_file_comprehensive(py_file)
            if file_violations:
                print(f"  - Found {len(file_violations)} issues in {py_file.relative_to(self.app_path)}")
            violations.extend(file_violations)
        
        print(f"📊 Checked {files_checked} Python files")
        return violations
    
    def generate_report(self, violations: List[Dict]) -> str:
        """Generate a comprehensive report"""
        if not violations:
            return "✅ No field reference issues found!"
            
        report = []
        report.append(f"❌ Found {len(violations)} field reference issues:")
        report.append("")
        
        # Group by type and severity
        by_type = {}
        for violation in violations:
            violation_type = violation.get('type', 'unknown')
            if violation_type not in by_type:
                by_type[violation_type] = []
            by_type[violation_type].append(violation)
        
        # Report by type
        for vtype, type_violations in by_type.items():
            report.append(f"## {vtype.replace('_', ' ').title()} ({len(type_violations)} issues)")
            
            # Group by file for cleaner presentation
            by_file = {}
            for violation in type_violations:
                file_path = violation['file']
                if file_path not in by_file:
                    by_file[file_path] = []
                by_file[file_path].append(violation)
            
            for file_path, file_violations in by_file.items():
                report.append(f"\n### {file_path}")
                
                for violation in file_violations:
                    report.append(f"- Line {violation['line']}: Field `{violation['field']}`")
                    report.append(f"  - Context: `{violation.get('content', 'N/A')}`")
                    
                    # Show detected doctypes if available
                    if violation.get('detected_doctypes'):
                        detected = ', '.join(violation['detected_doctypes'])
                        report.append(f"  - Detected DocTypes: {detected}")
                    
                    # Show suggestions for old doctype-based validation
                    if 'doctype' in violation:
                        similar = self.find_similar_fields(violation['field'], violation['doctype'])
                        if similar:
                            report.append(f"  - Similar fields: {', '.join(f'`{f}`' for f in similar)}")
                
                report.append("")
                
        return '\n'.join(report)
    
    def find_similar_fields(self, field_name: str, doctype: str) -> List[str]:
        """Find similar field names"""
        if doctype not in self.doctypes:
            return []
            
        similar = []
        field_lower = field_name.lower()
        
        for existing_field in self.doctypes[doctype]:
            existing_lower = existing_field.lower()
            
            # Check for substring matches
            if (field_lower in existing_lower or 
                existing_lower in field_lower or
                abs(len(field_lower) - len(existing_lower)) <= 2):
                similar.append(existing_field)
                
        return similar[:3]


def main():
    """Main function with enhanced reporting"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🔍 Running enhanced field validation (comprehensive)...")
    validator = FinalFieldValidator(app_path)
    
    print(f"📋 Loaded {len(validator.doctypes)} doctypes with field definitions")
    
    violations = validator.validate_app()
    
    print("\n" + "="*50)
    report = validator.generate_report(violations)
    print(report)
    
    if violations:
        print(f"\n💡 Summary: Found {len(violations)} field reference issues across the codebase")
        
        # Show breakdown by issue type
        by_type = {}
        for violation in violations:
            vtype = violation.get('type', 'unknown')
            by_type[vtype] = by_type.get(vtype, 0) + 1
            
        print("\n📊 Issue breakdown:")
        for vtype, count in by_type.items():
            print(f"   - {vtype.replace('_', ' ').title()}: {count}")
        
        return 1
    else:
        print("✅ All field references validated successfully!")
        return 0


if __name__ == "__main__":
    exit(main())