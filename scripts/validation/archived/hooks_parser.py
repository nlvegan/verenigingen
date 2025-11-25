#!/usr/bin/env python3
"""
Hooks Parser for AST Field Analyzer
==================================

Parses the hooks.py file to extract event handler mappings and build a registry
of which functions receive which DocTypes. This enables accurate type inference
for event-driven functions that receive documents from different DocTypes.

Key Features:
- Parses doc_events from hooks.py
- Maps function names to expected DocTypes
- Handles both string and list event handlers
- Provides fallback for missing hooks
"""

import ast
import re
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class EventMapping:
    """Represents an event handler mapping"""
    doctype: str
    event: str
    handler_function: str
    module_path: str
    confidence: float = 1.0

class HooksParser:
    """Parse hooks.py to extract DocType event mappings"""
    
    def __init__(self, app_path: str, verbose: bool = False):
        self.app_path = Path(app_path)
        self.verbose = verbose
        self.event_mappings: Dict[str, List[EventMapping]] = {}
        self.function_to_doctype: Dict[str, Set[str]] = {}
        
        # Parse hooks file (in the main app module directory)
        hooks_file = self.app_path / "verenigingen" / "hooks.py"
        if hooks_file.exists():
            self.parse_hooks_file(hooks_file)
        else:
            logger.warning(f"hooks.py not found at {hooks_file}")
    
    def parse_hooks_file(self, hooks_path: Path) -> None:
        """Parse hooks.py file to extract doc_events mappings"""
        try:
            with open(hooks_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse the AST
            tree = ast.parse(content)
            
            # Find doc_events assignment
            for node in ast.walk(tree):
                if (isinstance(node, ast.Assign) and 
                    len(node.targets) == 1 and
                    isinstance(node.targets[0], ast.Name) and
                    node.targets[0].id == 'doc_events'):
                    
                    self._parse_doc_events(node.value)
                    break
            
            # Build function -> DocType mapping
            self._build_function_mapping()
            
            if self.verbose:
                print(f"📋 Parsed {len(self.event_mappings)} DocType event mappings from hooks.py")
                print(f"🔗 Built {len(self.function_to_doctype)} function mappings")
                
        except Exception as e:
            logger.error(f"Error parsing hooks.py: {e}")
            if self.verbose:
                print(f"❌ Failed to parse hooks.py: {e}")
    
    def _parse_doc_events(self, node: ast.AST) -> None:
        """Parse the doc_events dictionary structure"""
        if not isinstance(node, ast.Dict):
            return
        
        for key_node, value_node in zip(node.keys, node.values):
            # Extract DocType name
            doctype = self._extract_string_value(key_node)
            if not doctype:
                continue
            
            # Parse event mappings for this DocType
            if isinstance(value_node, ast.Dict):
                self._parse_doctype_events(doctype, value_node)
    
    def _parse_doctype_events(self, doctype: str, events_node: ast.Dict) -> None:
        """Parse events for a specific DocType"""
        for event_key, handler_value in zip(events_node.keys, events_node.values):
            event_name = self._extract_string_value(event_key)
            if not event_name:
                continue
            
            # Handle different handler formats
            handlers = self._extract_handlers(handler_value)
            
            for handler in handlers:
                mapping = EventMapping(
                    doctype=doctype,
                    event=event_name,
                    handler_function=self._extract_function_name(handler),
                    module_path=handler
                )
                
                if doctype not in self.event_mappings:
                    self.event_mappings[doctype] = []
                self.event_mappings[doctype].append(mapping)
    
    def _extract_handlers(self, handler_node: ast.AST) -> List[str]:
        """Extract handler function paths from various node types"""
        handlers = []
        
        if isinstance(handler_node, ast.Constant) and isinstance(handler_node.value, str):
            # Single string handler
            handlers.append(handler_node.value)
        elif isinstance(handler_node, ast.List):
            # List of handlers
            for item in handler_node.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    handlers.append(item.value)
        
        return handlers
    
    def _extract_string_value(self, node: ast.AST) -> Optional[str]:
        """Extract string value from AST node"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None
    
    def _extract_function_name(self, handler_path: str) -> str:
        """Extract function name from module.path.function"""
        # Handle paths like "verenigingen.utils.module.function_name"
        parts = handler_path.split('.')
        return parts[-1] if parts else handler_path
    
    def _build_function_mapping(self) -> None:
        """Build mapping from function name to possible DocTypes"""
        for doctype, mappings in self.event_mappings.items():
            for mapping in mappings:
                func_name = mapping.handler_function
                
                if func_name not in self.function_to_doctype:
                    self.function_to_doctype[func_name] = set()
                
                self.function_to_doctype[func_name].add(doctype)
    
    def get_doctype_for_function(self, function_name: str, parameter_name: str = "doc") -> Optional[str]:
        """Get the DocType that a function receives as its doc parameter"""
        if function_name not in self.function_to_doctype:
            return None
        
        doctypes = self.function_to_doctype[function_name]
        
        # If function handles only one DocType, return it with high confidence
        if len(doctypes) == 1:
            return next(iter(doctypes))
        
        # If function handles multiple DocTypes, we can't be certain
        # This indicates a polymorphic function
        return None
    
    def is_polymorphic_function(self, function_name: str) -> bool:
        """Check if a function handles multiple DocTypes"""
        if function_name not in self.function_to_doctype:
            return False
        
        return len(self.function_to_doctype[function_name]) > 1
    
    def get_all_functions_for_doctype(self, doctype: str) -> Set[str]:
        """Get all functions that handle events for a specific DocType"""
        functions = set()
        
        if doctype in self.event_mappings:
            for mapping in self.event_mappings[doctype]:
                functions.add(mapping.handler_function)
        
        return functions
    
    def get_debug_info(self) -> Dict:
        """Get debug information about parsed mappings"""
        debug_info = {
            "total_doctypes": len(self.event_mappings),
            "total_functions": len(self.function_to_doctype),
            "polymorphic_functions": []
        }
        
        for func_name, doctypes in self.function_to_doctype.items():
            if len(doctypes) > 1:
                debug_info["polymorphic_functions"].append({
                    "function": func_name,
                    "doctypes": list(doctypes)
                })
        
        return debug_info

def test_hooks_parser():
    """Test the hooks parser with the current app"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    parser = HooksParser(app_path, verbose=True)
    
    # Test specific functions from our analysis
    test_functions = [
        "update_member_payment_history",
        "sync_member_counter_with_settings",
        "update_member_payment_history_from_invoice"
    ]
    
    print("\n🔍 Testing specific functions:")
    for func_name in test_functions:
        doctype = parser.get_doctype_for_function(func_name)
        is_poly = parser.is_polymorphic_function(func_name)
        print(f"  {func_name} -> {doctype} (polymorphic: {is_poly})")
    
    # Show debug info
    debug = parser.get_debug_info()
    print(f"\n📊 Debug Info:")
    print(f"  Total DocTypes with events: {debug['total_doctypes']}")
    print(f"  Total mapped functions: {debug['total_functions']}")
    print(f"  Polymorphic functions: {len(debug['polymorphic_functions'])}")
    
    if debug['polymorphic_functions']:
        print("\n⚠️  Polymorphic Functions (handle multiple DocTypes):")
        for poly in debug['polymorphic_functions'][:5]:  # Show first 5
            print(f"    {poly['function']} -> {poly['doctypes']}")

if __name__ == "__main__":
    test_hooks_parser()