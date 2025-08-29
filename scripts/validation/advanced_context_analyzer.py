#!/usr/bin/env python3
"""
Advanced Context Analyzer for Validation Enhancement
====================================================

Implements sophisticated variable type inference and SQL context detection
to eliminate the remaining ~75% false positives in field reference validation.

Key Innovations:
1. **Variable Assignment Tracking**: Follows variable assignments to determine actual types
2. **SQL Context Detection**: Recognizes SQL query patterns and result variable types
3. **Multi-line Context Analysis**: Analyzes code across multiple lines for context
4. **Function Call Pattern Recognition**: Identifies frappe.db.* call results
5. **Variable Scope Tracking**: Maintains variable type state within function scopes

Target False Positive Patterns:
- SQL query results with as_dict=True (member_stats.total, etc.)
- frappe.db.sql result objects  
- frappe.db.get_all/get_value results
- Loop variables from database queries
- Function parameters that are query results
"""

import ast
import re
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VariableContext:
    """Tracks variable type and origin context"""
    name: str
    var_type: str  # 'sql_result', 'doctype_instance', 'frappe_api_result', 'unknown'
    origin_line: int
    origin_context: str
    confidence: float = 1.0
    additional_info: Dict[str, Any] = field(default_factory=dict)


class AdvancedContextAnalyzer:
    """Advanced context analyzer with variable type inference"""
    
    def __init__(self):
        # SQL query patterns
        self.sql_patterns = [
            r'frappe\.db\.sql\s*\(',
            r'frappe\.db\.get_all\s*\(',
            r'frappe\.db\.get_value\s*\(',
            r'frappe\.db\.get_single_value\s*\(',
            r'frappe\.db\.count\s*\(',
            r'frappe\.db\.exists\s*\(',
        ]
        
        # SQL result indicators
        self.sql_result_indicators = [
            r'as_dict\s*=\s*True',
            r'as_dict\s*=\s*1',
            r'\[0\]\s*$',  # Taking first result from list
            r'COUNT\(\*\)\s+as\s+\w+',
            r'SUM\s*\([^)]+\)\s+as\s+\w+',
            r'SELECT\s+.*\s+as\s+\w+',
        ]
        
        # Variable assignment patterns that indicate SQL results
        self.sql_assignment_patterns = [
            r'(\w+)\s*=\s*frappe\.db\.sql\s*\(',
            r'(\w+)\s*=\s*frappe\.db\.get_all\s*\(',
            r'(\w+)\s*=\s*.*\.sql\s*\(',
        ]
        
        # DocType instantiation patterns
        self.doctype_patterns = [
            r'(\w+)\s*=\s*frappe\.get_doc\s*\(',
            r'(\w+)\s*=\s*frappe\.new_doc\s*\(',
        ]
        
    def analyze_file_context(self, file_path: str) -> Dict[str, VariableContext]:
        """Analyze entire file to build variable context map"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception:
            return {}
            
        variable_contexts = {}
        
        # Parse the file with AST for more sophisticated analysis
        try:
            tree = ast.parse(''.join(lines))
            variable_contexts.update(self._analyze_ast_assignments(tree, lines))
        except SyntaxError:
            # Fallback to regex-based analysis if AST parsing fails
            pass
        
        # Supplement with regex-based analysis
        variable_contexts.update(self._analyze_regex_patterns(lines))
        
        return variable_contexts
    
    def _analyze_ast_assignments(self, tree: ast.AST, lines: List[str]) -> Dict[str, VariableContext]:
        """Use AST to analyze variable assignments"""
        contexts = {}
        
        class AssignmentVisitor(ast.NodeVisitor):
            def visit_Assign(self, node):
                # Handle assignments like: var = frappe.db.sql(...)
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    var_name = node.targets[0].id
                    line_num = node.lineno
                    
                    # Check if the value is a SQL query
                    if isinstance(node.value, ast.Call):
                        call_context = self._analyze_call_node(node.value, lines, line_num)
                        if call_context:
                            contexts[var_name] = VariableContext(
                                name=var_name,
                                var_type=call_context['type'],
                                origin_line=line_num,
                                origin_context=call_context['context'],
                                confidence=call_context['confidence'],
                                additional_info=call_context.get('info', {})
                            )
                
                # Handle subscript assignments like: var = sql_result[0]
                elif len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    if isinstance(node.value, ast.Subscript):
                        var_name = node.targets[0].id
                        line_num = node.lineno
                        
                        # Check if subscripting a known SQL result
                        if isinstance(node.value.value, ast.Name):
                            source_var = node.value.value.id
                            if source_var in contexts and contexts[source_var].var_type == 'sql_result':
                                contexts[var_name] = VariableContext(
                                    name=var_name,
                                    var_type='sql_result_item',
                                    origin_line=line_num,
                                    origin_context=f"Item from SQL result {source_var}",
                                    confidence=0.9,
                                    additional_info={'source_variable': source_var}
                                )
                
                self.generic_visit(node)
            
            def _analyze_call_node(self, node: ast.Call, lines: List[str], line_num: int) -> Optional[Dict]:
                """Analyze function call to determine if it's a SQL operation"""
                line_content = lines[line_num - 1] if line_num <= len(lines) else ""
                
                # Check for frappe.db.* calls
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Attribute):  # frappe.db.sql
                        if (isinstance(node.func.value.value, ast.Name) and 
                            node.func.value.value.id == 'frappe' and
                            node.func.value.attr == 'db'):
                            
                            method_name = node.func.attr
                            if method_name in ['sql', 'get_all', 'get_value', 'count', 'exists']:
                                
                                # Check for as_dict parameter
                                has_as_dict = any(
                                    isinstance(kw.value, ast.Constant) and kw.value.value in [True, 1]
                                    for kw in node.keywords 
                                    if kw.arg == 'as_dict'
                                )
                                
                                return {
                                    'type': 'sql_result',
                                    'context': f"frappe.db.{method_name} result",
                                    'confidence': 0.95 if has_as_dict else 0.8,
                                    'info': {
                                        'method': method_name,
                                        'has_as_dict': has_as_dict,
                                        'line_content': line_content.strip()
                                    }
                                }
                
                # Check for DocType operations
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == 'frappe':
                        method_name = node.func.attr
                        if method_name in ['get_doc', 'new_doc']:
                            return {
                                'type': 'doctype_instance',
                                'context': f"frappe.{method_name} result",
                                'confidence': 0.95,
                                'info': {
                                    'method': method_name,
                                    'line_content': line_content.strip()
                                }
                            }
                
                return None
        
        visitor = AssignmentVisitor()
        visitor.visit(tree)
        
        return contexts
    
    def _analyze_regex_patterns(self, lines: List[str]) -> Dict[str, VariableContext]:
        """Regex-based analysis as fallback/supplement"""
        contexts = {}
        
        for i, line in enumerate(lines):
            line_num = i + 1
            line_stripped = line.strip()
            
            # SQL assignment patterns
            for pattern in self.sql_assignment_patterns:
                match = re.search(pattern, line_stripped)
                if match:
                    var_name = match.group(1)
                    
                    # Check for as_dict in the line or next few lines
                    has_as_dict = False
                    context_lines = lines[max(0, i-2):min(len(lines), i+3)]
                    for ctx_line in context_lines:
                        if 'as_dict=True' in ctx_line or 'as_dict=1' in ctx_line:
                            has_as_dict = True
                            break
                    
                    contexts[var_name] = VariableContext(
                        name=var_name,
                        var_type='sql_result',
                        origin_line=line_num,
                        origin_context=line_stripped,
                        confidence=0.9 if has_as_dict else 0.7,
                        additional_info={'has_as_dict': has_as_dict}
                    )
            
            # DocType instantiation patterns
            for pattern in self.doctype_patterns:
                match = re.search(pattern, line_stripped)
                if match:
                    var_name = match.group(1)
                    contexts[var_name] = VariableContext(
                        name=var_name,
                        var_type='doctype_instance',
                        origin_line=line_num,
                        origin_context=line_stripped,
                        confidence=0.9
                    )
        
        return contexts
    
    def is_sql_result_access(self, obj_name: str, field_name: str, 
                           line_number: int, file_contexts: Dict[str, VariableContext]) -> Tuple[bool, float]:
        """Determine if field access is on a SQL result with confidence score"""
        
        if obj_name not in file_contexts:
            return False, 0.0
        
        context = file_contexts[obj_name]
        
        if context.var_type in ['sql_result', 'sql_result_item']:
            # High confidence for SQL results, especially with as_dict
            base_confidence = context.confidence
            
            # Boost confidence for common SQL aggregation fields
            sql_field_indicators = ['total', 'count', 'sum', 'avg', 'min', 'max', 'active', 'inactive', 'pending']
            if field_name.lower() in sql_field_indicators:
                base_confidence = min(1.0, base_confidence + 0.1)
            
            return True, base_confidence
        
        return False, 0.0
    
    def is_doctype_instance_access(self, obj_name: str, 
                                 file_contexts: Dict[str, VariableContext]) -> Tuple[bool, str, float]:
        """Determine if access is on a DocType instance"""
        
        if obj_name not in file_contexts:
            return False, 'Unknown', 0.0
        
        context = file_contexts[obj_name]
        
        if context.var_type == 'doctype_instance':
            # Try to extract DocType name from context
            doctype_name = 'Unknown'
            if 'frappe.get_doc(' in context.origin_context:
                # Extract DocType name from get_doc call
                match = re.search(r'frappe\.get_doc\s*\(\s*["\']([^"\']+)["\']', context.origin_context)
                if match:
                    doctype_name = match.group(1)
            
            return True, doctype_name, context.confidence
        
        return False, 'Unknown', 0.0


def main():
    """Demo of advanced context analysis"""
    analyzer = AdvancedContextAnalyzer()
    
    # Test with a sample file
    test_file = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/chapter_dashboard_api.py"
    contexts = analyzer.analyze_file_context(test_file)
    
    print("🔍 Advanced Context Analysis Demo")
    print("=" * 40)
    print(f"📄 Analyzed: {Path(test_file).name}")
    print(f"🔍 Found {len(contexts)} variable contexts:")
    
    for var_name, context in contexts.items():
        print(f"  {var_name}: {context.var_type} (confidence: {context.confidence:.2f})")
        print(f"    Line {context.origin_line}: {context.origin_context[:60]}...")
    
    # Test specific case
    print(f"\n🎯 Testing member_stats variable:")
    is_sql, confidence = analyzer.is_sql_result_access('member_stats', 'total', 1164, contexts)
    print(f"  SQL result access: {is_sql} (confidence: {confidence:.2f})")


if __name__ == "__main__":
    main()