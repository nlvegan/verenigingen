#!/usr/bin/env python3
"""
Child Table Creation Pattern Validator

Detects incorrect child table creation patterns that bypass Frappe's ORM structure.
This validator addresses a critical gap in the existing validation infrastructure by
focusing on document creation patterns rather than field access patterns.

Key Patterns Detected:
1. Standalone child table creation with frappe.get_doc()
2. Missing parent.append() usage for child table records
3. Incorrect parenttype/parentfield values
4. Child table records created without proper parent context

Author: Claude Code Assistant
Created: 2025-08-24
"""

import ast
import re
import argparse
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple, Union
from dataclasses import dataclass
from doctype_loader import DocTypeLoader, DocTypeMetadata, FieldMetadata

@dataclass
class ChildTableIssue:
    """Represents a child table creation pattern issue"""
    file: str
    line: int
    doctype: str
    pattern: str  # The detected anti-pattern
    message: str
    context: str
    confidence: str  # high, medium, low
    issue_type: str
    suggested_fix: str
    parent_doctype: Optional[str] = None
    field_name: Optional[str] = None

class ChildTableMetadata:
    """Manages child table metadata and parent-child relationships"""
    
    def __init__(self, bench_path: Path):
        self.bench_path = bench_path
        self.doctype_loader = DocTypeLoader(str(bench_path), verbose=False)
        self.child_tables = self._build_child_table_registry()
        self.parent_child_map = self._build_parent_child_map()
        print(f"📋 Child Table Validator loaded {len(self.child_tables)} child table DocTypes")
        
    def _build_child_table_registry(self) -> Set[str]:
        """Build registry of all child table DocTypes"""
        child_tables = set()
        doctype_metas = self.doctype_loader.get_doctypes()
        
        for doctype_name, doctype_meta in doctype_metas.items():
            if doctype_meta.istable:  # Child table DocTypes have istable=True
                child_tables.add(doctype_name)
        
        return child_tables
    
    def _build_parent_child_map(self) -> Dict[str, List[Tuple[str, str]]]:
        """Build mapping of child_doctype -> [(parent_doctype, field_name), ...]"""
        parent_child_map = {}
        child_table_mapping = self.doctype_loader.get_child_table_mapping()
        
        # Reverse the mapping from parent.field -> child to child -> [(parent, field), ...]
        for parent_field, child_doctype in child_table_mapping.items():
            parent_doctype, field_name = parent_field.split('.', 1)
            
            if child_doctype not in parent_child_map:
                parent_child_map[child_doctype] = []
            parent_child_map[child_doctype].append((parent_doctype, field_name))
        
        return parent_child_map
    
    def is_child_table(self, doctype: str) -> bool:
        """Check if DocType is a child table"""
        return doctype in self.child_tables
    
    def get_parent_info(self, child_doctype: str) -> List[Tuple[str, str]]:
        """Get all possible (parent_doctype, field_name) combinations for a child table"""
        return self.parent_child_map.get(child_doctype, [])

class FrappeCallVisitor(ast.NodeVisitor):
    """AST visitor to detect frappe.get_doc() and frappe.new_doc() calls"""
    
    def __init__(self, file_path: str, metadata: ChildTableMetadata):
        self.file_path = file_path
        self.metadata = metadata
        self.issues = []
        self.lines = []
        
    def analyze_file(self, content: str) -> List[ChildTableIssue]:
        """Analyze file content for child table creation issues"""
        try:
            self.lines = content.split('\n')
            tree = ast.parse(content)
            self.visit(tree)
            return self.issues
        except SyntaxError as e:
            # Skip files with syntax errors
            return []
    
    def visit_Call(self, node: ast.Call):
        """Visit function calls looking for Frappe document creation patterns"""
        # Detect frappe.get_doc() and frappe.new_doc() calls
        if self._is_frappe_doc_creation_call(node):
            self._analyze_doc_creation_call(node)
        
        # Continue traversing
        self.generic_visit(node)
    
    def _is_frappe_doc_creation_call(self, node: ast.Call) -> bool:
        """Check if this is a frappe.get_doc() or frappe.new_doc() call"""
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                if (node.func.value.id == 'frappe' and 
                    node.func.attr in ['get_doc', 'new_doc']):
                    return True
        return False
    
    def _analyze_doc_creation_call(self, node: ast.Call):
        """Analyze a frappe doc creation call for child table issues"""
        doctype = self._extract_doctype_from_call(node)
        if not doctype:
            return
            
        # Check if this DocType is a child table
        if self.metadata.is_child_table(doctype):
            self._report_child_table_creation_issue(node, doctype)
    
    def _extract_doctype_from_call(self, node: ast.Call) -> Optional[str]:
        """Extract DocType name from frappe.get_doc() call"""
        if len(node.args) == 0:
            return None
            
        first_arg = node.args[0]
        
        # Handle string literal: frappe.get_doc("DocType", ...)
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            return first_arg.value
        elif hasattr(first_arg, 's'):  # ast.Str fallback for older Python versions
            return first_arg.s
        
        # Handle dict: frappe.get_doc({"doctype": "DocType", ...})
        elif isinstance(first_arg, ast.Dict):
            for key, value in zip(first_arg.keys, first_arg.values):
                key_value = None
                if isinstance(key, ast.Constant):
                    key_value = key.value
                elif hasattr(key, 's'):  # ast.Str fallback for older Python versions
                    key_value = key.s
                
                if key_value == 'doctype':
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        return value.value
                    elif hasattr(value, 's'):  # ast.Str fallback for older Python versions
                        return value.s
        
        return None
    
    def _report_child_table_creation_issue(self, node: ast.Call, doctype: str):
        """Report an issue with standalone child table creation"""
        line_num = node.lineno
        context = self._get_context(line_num)
        
        # Get parent information for this child table
        parent_info = self.metadata.get_parent_info(doctype)
        
        # Check if this appears to be setting parent/parenttype/parentfield
        has_parent_fields = self._check_for_parent_fields(node)
        
        # Determine confidence based on context
        confidence = self._calculate_confidence(node, doctype, has_parent_fields)
        
        # Generate suggested fix
        suggested_fix = self._generate_suggested_fix(doctype, parent_info)
        
        issue = ChildTableIssue(
            file=self.file_path,
            line=line_num,
            doctype=doctype,
            pattern=f"frappe.{node.func.attr}() with child table",
            message=f"Child table '{doctype}' created independently instead of via parent.append()",
            context=context,
            confidence=confidence,
            issue_type="child_table_creation",
            suggested_fix=suggested_fix,
            parent_doctype=parent_info[0][0] if parent_info else None,
            field_name=parent_info[0][1] if parent_info else None
        )
        
        self.issues.append(issue)
    
    def _check_for_parent_fields(self, node: ast.Call) -> bool:
        """Check if the call includes parenttype/parentfield settings"""
        if len(node.args) == 0:
            return False
            
        first_arg = node.args[0]
        
        # Check dictionary for parent fields
        if isinstance(first_arg, ast.Dict):
            keys = []
            for key in first_arg.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.append(key.value)
                elif hasattr(key, 's'):  # ast.Str fallback for older Python versions
                    keys.append(key.s)
            
            return any(field in keys for field in ['parent', 'parenttype', 'parentfield'])
        
        return False
    
    def _calculate_confidence(self, node: ast.Call, doctype: str, has_parent_fields: bool) -> str:
        """Calculate confidence level for this issue"""
        if has_parent_fields:
            return "high"  # Clearly trying to create child table with parent info
        elif self.metadata.get_parent_info(doctype):
            return "medium"  # Known child table without obvious parent context
        else:
            return "low"  # Child table but unclear context
    
    def _generate_suggested_fix(self, doctype: str, parent_info: List[Tuple[str, str]]) -> str:
        """Generate a suggested fix for the child table creation issue"""
        if not parent_info:
            return f"Verify that '{doctype}' should be created as a child table record"
        
        parent_doctype, field_name = parent_info[0]  # Use first parent option
        
        return f"""Instead of creating '{doctype}' directly, use:
parent_doc = frappe.get_doc('{parent_doctype}', parent_id)
child_record = parent_doc.append('{field_name}', {{
    # child table field values here
}})
parent_doc.save()"""
    
    def _get_context(self, line_num: int, context_lines: int = 2) -> str:
        """Get surrounding context for the issue"""
        start = max(0, line_num - context_lines - 1)
        end = min(len(self.lines), line_num + context_lines)
        
        context_lines_list = []
        for i in range(start, end):
            marker = ">>> " if i == line_num - 1 else "    "
            context_lines_list.append(f"{marker}{self.lines[i]}")
        
        return '\n'.join(context_lines_list)

class ChildTableCreationValidator:
    """Main validator class for child table creation patterns"""
    
    def __init__(self, bench_path: Path):
        self.bench_path = bench_path
        self.metadata = ChildTableMetadata(bench_path)
    
    def validate_file(self, file_path: Path) -> List[ChildTableIssue]:
        """Validate a single Python file for child table creation issues"""
        if not file_path.suffix == '.py':
            return []
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            visitor = FrappeCallVisitor(str(file_path), self.metadata)
            return visitor.analyze_file(content)
            
        except (IOError, UnicodeDecodeError):
            return []
    
    def validate_directory(self, directory: Path, 
                          exclude_patterns: Optional[List[str]] = None) -> List[ChildTableIssue]:
        """Validate all Python files in a directory"""
        if exclude_patterns is None:
            exclude_patterns = ['__pycache__', '.git', 'node_modules', '.pytest_cache']
        
        all_issues = []
        python_files = list(directory.rglob('*.py'))
        
        for file_path in python_files:
            # Skip excluded patterns
            if any(pattern in str(file_path) for pattern in exclude_patterns):
                continue
                
            issues = self.validate_file(file_path)
            all_issues.extend(issues)
        
        return all_issues
    
    def format_issues(self, issues: List[ChildTableIssue], 
                     confidence_filter: Optional[str] = None) -> str:
        """Format issues for human-readable output"""
        if confidence_filter:
            issues = [i for i in issues if i.confidence == confidence_filter]
        
        if not issues:
            return "✅ No child table creation issues found!"
        
        output = []
        output.append(f"🚨 Found {len(issues)} child table creation issues:\n")
        
        # Group by confidence
        by_confidence = {}
        for issue in issues:
            if issue.confidence not in by_confidence:
                by_confidence[issue.confidence] = []
            by_confidence[issue.confidence].append(issue)
        
        for confidence in ['high', 'medium', 'low']:
            if confidence in by_confidence:
                conf_issues = by_confidence[confidence]
                output.append(f"\n📊 {confidence.upper()} CONFIDENCE ({len(conf_issues)} issues):")
                
                for issue in conf_issues:
                    output.append(f"\n📁 {issue.file}:{issue.line}")
                    output.append(f"   DocType: {issue.doctype}")
                    output.append(f"   Issue: {issue.message}")
                    output.append(f"   Pattern: {issue.pattern}")
                    
                    if issue.suggested_fix:
                        output.append(f"   💡 Suggested Fix:\n{self._indent_text(issue.suggested_fix, '      ')}")
                    
                    output.append(f"   📝 Context:")
                    output.append(self._indent_text(issue.context, '      '))
        
        return '\n'.join(output)
    
    def _indent_text(self, text: str, indent: str) -> str:
        """Add indentation to multi-line text"""
        return '\n'.join(indent + line for line in text.split('\n'))

def main():
    """Main entry point for command-line usage"""
    parser = argparse.ArgumentParser(description='Validate child table creation patterns')
    parser.add_argument('paths', nargs='*', 
                       help='Path(s) to validate (file or directory). If none provided, validates current directory.')
    parser.add_argument('--bench-path', default='.',
                       help='Path to Frappe bench (default: current directory)')
    parser.add_argument('--confidence', choices=['high', 'medium', 'low'],
                       help='Filter by confidence level')
    parser.add_argument('--pre-commit', action='store_true',
                       help='Pre-commit mode (only high confidence issues)')
    
    args = parser.parse_args()
    
    # Set up paths  
    if args.paths:
        target_paths = [Path(p).resolve() for p in args.paths]
    else:
        target_paths = [Path('.').resolve()]
    
    bench_path = Path(args.bench_path).resolve()
    
    # Auto-detect bench path if we're in a Frappe app directory
    current_path = Path('.').resolve()
    if 'apps' in current_path.parts:
        # Try to find bench root
        for parent in current_path.parents:
            if (parent / 'apps').exists() and (parent / 'sites').exists():
                bench_path = parent
                break
    
    # Create validator
    validator = ChildTableCreationValidator(bench_path)
    
    # Collect all issues from all paths
    all_issues = []
    for target_path in target_paths:
        if target_path.is_file():
            issues = validator.validate_file(target_path)
        else:
            issues = validator.validate_directory(target_path)
        all_issues.extend(issues)
    
    # Apply filters
    confidence_filter = args.confidence
    if args.pre_commit:
        confidence_filter = 'high'  # Only high confidence in pre-commit mode
    
    # Output results
    output = validator.format_issues(all_issues, confidence_filter)
    print(output)
    
    # Exit with error code if issues found
    if confidence_filter:
        filtered_issues = [i for i in all_issues if i.confidence == confidence_filter]
        exit_code = 1 if filtered_issues else 0
    else:
        exit_code = 1 if all_issues else 0
    
    if exit_code == 0 and not args.pre_commit:
        print(f"\n✅ Child table creation validation passed!")
    elif exit_code != 0 and not args.pre_commit:
        print(f"\n❌ Child table creation validation failed!")
    
    return exit_code

if __name__ == '__main__':
    exit(main())