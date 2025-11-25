#!/usr/bin/env python3
"""
Child Table Iteration Detector
==============================

Detects when variables are created from iterating over child table fields,
which is crucial for accurate field reference validation. This complements
the existing child_table_creation_validator by focusing on field access
patterns rather than document creation patterns.

Key Patterns Detected:
1. for item in parent.child_table_field: item.field_name
2. parent.child_table_field[0].field_name  
3. child_record = parent.child_table_field.get(filter)
4. Loop variables from child table list comprehensions

Integration:
- Uses existing DocTypeLoader and ChildTableMetadata 
- Extends AdvancedContextAnalyzer with child table awareness
- Provides variable type context for false positive filtering
"""

import ast
import re
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Import existing validation infrastructure 
sys.path.insert(0, str(Path(__file__).parent))
from child_table_creation_validator import ChildTableMetadata
from advanced_context_analyzer import VariableContext


@dataclass
class ChildTableIterationContext:
    """Context for variables created from child table iterations"""
    variable_name: str
    child_doctype: str
    parent_variable: str
    parent_doctype: Optional[str]
    child_field_name: str
    line_number: int
    pattern_type: str  # 'for_loop', 'list_access', 'comprehension'
    confidence: float = 0.9


class ChildTableIterationDetector:
    """Detects child table iteration patterns using AST analysis"""
    
    def __init__(self, bench_path: str):
        self.bench_path = Path(bench_path)
        # Leverage existing child table metadata
        self.child_metadata = ChildTableMetadata(self.bench_path)
        
        # Cache for parent DocType -> child table fields mapping
        self._parent_child_fields = self._build_parent_child_fields_map()
    
    def _build_parent_child_fields_map(self) -> Dict[str, Dict[str, str]]:
        """Build mapping of parent_doctype -> {field_name: child_doctype}"""
        mapping = {}
        
        # Get the child table mapping from existing infrastructure
        child_table_mapping = self.child_metadata.doctype_loader.get_child_table_mapping()
        
        for parent_field, child_doctype in child_table_mapping.items():
            if '.' in parent_field:
                parent_doctype, field_name = parent_field.split('.', 1)
                
                if parent_doctype not in mapping:
                    mapping[parent_doctype] = {}
                mapping[parent_doctype][field_name] = child_doctype
        
        return mapping
    
    def analyze_file_for_child_table_iterations(self, file_path: str) -> Dict[str, ChildTableIterationContext]:
        """Analyze a file for child table iteration patterns"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception:
            return {}
        
        # Parse with AST
        try:
            tree = ast.parse(content)
            visitor = ChildTableASTVisitor(lines, self._parent_child_fields)
            visitor.visit(tree)
            return visitor.child_table_contexts
        except SyntaxError:
            # Fallback to regex analysis if AST fails
            return self._regex_fallback_analysis(lines)
    
    def _regex_fallback_analysis(self, lines: List[str]) -> Dict[str, ChildTableIterationContext]:
        """Regex-based fallback analysis"""
        contexts = {}
        
        for i, line in enumerate(lines):
            line_num = i + 1
            line_stripped = line.strip()
            
            # Pattern: for item in parent.child_field:
            for_loop_match = re.search(r'for\s+(\w+)\s+in\s+(\w+)\.(\w+):', line_stripped)
            if for_loop_match:
                var_name, parent_var, field_name = for_loop_match.groups()
                
                # Check if this could be a child table field
                if self._could_be_child_table_field(field_name):
                    contexts[var_name] = ChildTableIterationContext(
                        variable_name=var_name,
                        child_doctype='Unknown',  # Will be inferred if possible
                        parent_variable=parent_var,
                        parent_doctype=None,
                        child_field_name=field_name,
                        line_number=line_num,
                        pattern_type='for_loop',
                        confidence=0.7  # Lower confidence for regex
                    )
        
        return contexts
    
    def _could_be_child_table_field(self, field_name: str) -> bool:
        """Heuristic to determine if a field name looks like a child table field"""
        # Common child table field patterns
        child_table_patterns = [
            'members', 'items', 'lines', 'entries', 'records', 'details',
            'board_members', 'team_members', 'roles', 'permissions',
            'addresses', 'contacts', 'links', 'attachments'
        ]
        
        return (
            field_name.lower() in child_table_patterns or
            field_name.endswith('_members') or
            field_name.endswith('_items') or
            field_name.endswith('_list') or
            field_name.endswith('s')  # Plural form heuristic
        )


class ChildTableASTVisitor(ast.NodeVisitor):
    """AST visitor for detecting child table iteration patterns"""
    
    def __init__(self, lines: List[str], parent_child_fields: Dict[str, Dict[str, str]]):
        self.lines = lines
        self.parent_child_fields = parent_child_fields
        self.child_table_contexts = {}
        
        # Track variable types as we discover them
        self.variable_types = {}  # var_name -> doctype
    
    def visit_For(self, node: ast.For):
        """Visit for loops to detect child table iterations"""
        # Pattern: for item in parent.child_field:
        if (isinstance(node.target, ast.Name) and 
            isinstance(node.iter, ast.Attribute) and
            isinstance(node.iter.value, ast.Name)):
            
            var_name = node.target.id
            parent_var = node.iter.value.id
            field_name = node.iter.attr
            line_num = node.lineno
            
            # Check if we know the parent's DocType
            parent_doctype = self.variable_types.get(parent_var)
            child_doctype = None
            confidence = 0.8
            
            if parent_doctype and parent_doctype in self.parent_child_fields:
                if field_name in self.parent_child_fields[parent_doctype]:
                    child_doctype = self.parent_child_fields[parent_doctype][field_name]
                    confidence = 0.95  # High confidence - we know the exact mapping
            
            # Even if we don't know the exact types, record the pattern
            self.child_table_contexts[var_name] = ChildTableIterationContext(
                variable_name=var_name,
                child_doctype=child_doctype or 'Unknown',
                parent_variable=parent_var,
                parent_doctype=parent_doctype,
                child_field_name=field_name,
                line_number=line_num,
                pattern_type='for_loop',
                confidence=confidence
            )
        
        self.generic_visit(node)
    
    def visit_Subscript(self, node: ast.Subscript):
        """Visit subscript access to detect child table item access"""
        # Pattern: parent.child_field[0] or parent.child_field[index]
        if (isinstance(node.value, ast.Attribute) and
            isinstance(node.value.value, ast.Name)):
            
            parent_var = node.value.value.id
            field_name = node.value.attr
            
            # Check if this looks like child table access
            parent_doctype = self.variable_types.get(parent_var)
            if parent_doctype and parent_doctype in self.parent_child_fields:
                if field_name in self.parent_child_fields[parent_doctype]:
                    child_doctype = self.parent_child_fields[parent_doctype][field_name]
                    
                    # This creates an implicit variable context for the subscript result
                    implicit_var = f"{parent_var}_{field_name}_item"
                    self.child_table_contexts[implicit_var] = ChildTableIterationContext(
                        variable_name=implicit_var,
                        child_doctype=child_doctype,
                        parent_variable=parent_var,
                        parent_doctype=parent_doctype,
                        child_field_name=field_name,
                        line_number=node.lineno,
                        pattern_type='list_access',
                        confidence=0.9
                    )
        
        self.generic_visit(node)
    
    def visit_Assign(self, node: ast.Assign):
        """Visit assignments to track variable types"""
        # Track frappe.get_doc assignments for parent DocType inference
        if (len(node.targets) == 1 and 
            isinstance(node.targets[0], ast.Name) and
            isinstance(node.value, ast.Call)):
            
            var_name = node.targets[0].id
            
            # frappe.get_doc("DocType", name)
            if (isinstance(node.value.func, ast.Attribute) and
                isinstance(node.value.func.value, ast.Name) and
                node.value.func.value.id == 'frappe' and
                node.value.func.attr == 'get_doc' and
                len(node.value.args) >= 1):
                
                # Extract DocType from first argument
                if isinstance(node.value.args[0], ast.Constant):
                    doctype = node.value.args[0].value
                    self.variable_types[var_name] = doctype
        
        self.generic_visit(node)


def main():
    """Demo of child table iteration detection"""
    detector = ChildTableIterationDetector("/home/frappe/frappe-bench")
    
    # Test with the problematic chapter dashboard API
    test_file = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/chapter_dashboard_api.py"
    contexts = detector.analyze_file_for_child_table_iterations(test_file)
    
    print("🔍 Child Table Iteration Detection Demo")
    print("=" * 50)
    print(f"📄 Analyzed: {Path(test_file).name}")
    print(f"🔍 Found {len(contexts)} child table iteration contexts:")
    
    for var_name, context in contexts.items():
        print(f"\n  Variable: {var_name}")
        print(f"  Child DocType: {context.child_doctype}")
        print(f"  Pattern: {context.pattern_type}")
        print(f"  Line: {context.line_number}")
        print(f"  Confidence: {context.confidence:.2f}")
        print(f"  Context: {context.parent_variable}.{context.child_field_name}")


if __name__ == "__main__":
    main()