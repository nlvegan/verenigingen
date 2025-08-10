#!/usr/bin/env python3
"""
Debug AST method detection to understand why methods aren't being detected as method calls
"""

import sys
import ast
from pathlib import Path

# Add current directory to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

from schema_aware_validator import SchemaAwareValidator

def debug_ast_method_detection():
    """Debug AST method call detection"""
    
    print("🔍 DEBUGGING AST METHOD DETECTION")
    print("=" * 50)
    
    # Test code with clear method calls and field access
    test_code = '''
def test_ast_detection():
    member = frappe.get_doc("Member", "test")
    
    # Clear method calls - should be detected as method calls
    member.save()           # Method call
    result = member.get("field")  # Method call with return value
    member.submit()         # Method call
    
    # Clear field access - should NOT be detected as method calls
    email = member.email    # Field access
    name = member.name      # Field access
    status = member.status  # Field access
'''
    
    print("📄 Test code:")
    lines = test_code.strip().split('\n')
    for i, line in enumerate(lines, 1):
        print(f"   {i:2}: {line}")
    
    # Parse AST
    tree = ast.parse(test_code)
    
    # Use the existing AST visitor from the validator
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    validator = SchemaAwareValidator(app_path, min_confidence=0.1, verbose=False)
    
    accesses = validator.validation_engine._extract_field_accesses(tree)
    
    print(f"\n📊 AST Results:")
    print(f"   Total accesses found: {len(accesses)}")
    
    for access in accesses:
        is_method = access.get('is_method', False)
        access_type = "METHOD CALL" if is_method else "FIELD ACCESS"
        print(f"   • Line {access['line']}: {access['obj_name']}.{access['field_name']} -> {access_type}")
    
    # Let's manually check what the AST looks like
    print(f"\n🔍 Manual AST Analysis:")
    
    class DebugVisitor(ast.NodeVisitor):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'member':
                print(f"\n   Found attribute access: member.{node.attr} (line {node.lineno})")
                
                # Check the parent node
                # We need to walk up the AST to find the parent
                # This is a limitation - we need the parent map
                print(f"      Node type: {type(node).__name__}")
                
                # Let's examine the context by looking at what the AST visitor is doing
                
    # Let's look at the FieldAccessVisitor implementation
    print(f"\n🔍 Examining FieldAccessVisitor implementation:")
    
    # Create a more detailed visitor
    class DetailedVisitor(ast.NodeVisitor):
        def __init__(self):
            self.parent_map = {}
            self.current_parent = None
            
        def visit(self, node):
            # Build parent mapping
            old_parent = self.current_parent  
            self.current_parent = node
            for child in ast.iter_child_nodes(node):
                self.parent_map[child] = node
            super().visit(node)
            self.current_parent = old_parent
            
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'member':
                parent = self.parent_map.get(node)
                print(f"\n      member.{node.attr} (line {node.lineno})")
                print(f"         Parent node type: {type(parent).__name__ if parent else 'None'}")
                
                if parent:
                    if isinstance(parent, ast.Call):
                        print(f"         Parent is Call - func matches node: {parent.func == node}")
                        if parent.func == node:
                            print(f"         ✅ This IS a method call")
                        else:
                            print(f"         ❌ This is NOT a method call")
                    else:
                        print(f"         ❌ This is NOT a method call (parent is {type(parent).__name__})")
                else:
                    print(f"         ❌ No parent found")
            
            self.generic_visit(node)
    
    visitor = DetailedVisitor()
    visitor.visit(tree)
    
    # Compare with actual FieldAccessVisitor
    print(f"\n🔍 Actual FieldAccessVisitor results:")
    
    # Let me examine the actual implementation more closely
    class TestFieldAccessVisitor(ast.NodeVisitor):
        def __init__(self):
            self.accesses = []
            self.parent_map = {}
            self.current_parent = None
                
        def visit(self, node):
            # More efficient parent tracking (as in original)
            old_parent = self.current_parent
            self.current_parent = node
            for child in ast.iter_child_nodes(node):
                self.parent_map[child] = node
            super().visit(node)
            self.current_parent = old_parent
            
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name):
                # Check if this attribute is being called as a method
                parent = self.parent_map.get(node)
                is_method_call = isinstance(parent, ast.Call) and parent.func == node
                
                print(f"   Testing: {node.value.id}.{node.attr}")
                print(f"      Parent: {type(parent).__name__ if parent else 'None'}")  
                print(f"      Is Call: {isinstance(parent, ast.Call) if parent else False}")
                print(f"      Func matches: {parent.func == node if parent and isinstance(parent, ast.Call) else False}")
                print(f"      Final is_method: {is_method_call}")
                
                if node.value.id == 'member':
                    self.accesses.append({
                        'obj_name': node.value.id,
                        'field_name': node.attr,
                        'line': node.lineno,
                        'col': node.col_offset,
                        'is_method': is_method_call
                    })
            self.generic_visit(node)
    
    test_visitor = TestFieldAccessVisitor()
    test_visitor.visit(tree)
    
    print(f"\n📊 Test visitor results:")
    for access in test_visitor.accesses:
        is_method = access.get('is_method', False)
        access_type = "METHOD CALL" if is_method else "FIELD ACCESS"
        print(f"   • {access['obj_name']}.{access['field_name']} -> {access_type}")

if __name__ == "__main__":
    debug_ast_method_detection()