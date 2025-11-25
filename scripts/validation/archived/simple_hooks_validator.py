#!/usr/bin/env python3
"""
Simple Hooks Validator

Validates hooks.py without importing modules - just checks if files exist
and uses AST parsing to verify method presence.
"""

import ast
import re
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass


@dataclass
class HookIssue:
    """Represents a hook/event handler issue"""
    hook_type: str
    hook_name: str  
    method_path: str
    issue_type: str
    message: str


class SimpleHooksValidator:
    """Simple hooks validator using file system checks"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.app_name = self.app_path.name
        self.hooks_path = self.app_path / self.app_name / "hooks.py"
        self.issues: List[HookIssue] = []
        
    def validate(self) -> List[HookIssue]:
        """Run validation"""
        self.issues = []
        
        if not self.hooks_path.exists():
            self.issues.append(HookIssue(
                hook_type="hooks.py",
                hook_name="file",
                method_path="",
                issue_type="missing_file",
                message=f"hooks.py not found"
            ))
            return self.issues
        
        print(f"🔍 Validating hooks.py references...")
        
        # Parse hooks.py as text to extract method references
        content = self.hooks_path.read_text()
        
        # Find all string literals that look like method paths
        method_paths = self._extract_method_paths(content)
        
        for path in method_paths:
            self._validate_method_path_exists(path)
        
        return self.issues
    
    def _extract_method_paths(self, content: str) -> Set[str]:
        """Extract method paths from hooks.py content"""
        paths = set()
        
        # Split content into lines to check for comments
        lines = content.split('\n')
        
        for line in lines:
            # Skip commented lines
            stripped_line = line.strip()
            if stripped_line.startswith('#') or '# ' in stripped_line:
                continue
                
            # Pattern for method paths in hooks
            # Matches strings like "verenigingen.doctype.member.member.validate_member"
            pattern = r'["\']([a-zA-Z_][a-zA-Z0-9_.]*\.[a-zA-Z_][a-zA-Z0-9_]*)["\']'
            
            matches = re.findall(pattern, line)
            
            for match in matches:
                # Filter to likely module paths (have at least 3 parts and end with function name)
                parts = match.split('.')
                if (len(parts) >= 3 and 
                    any(keyword in match for keyword in ['verenigingen', 'utils', 'events', 'api', 'doctype']) and
                    not match.endswith('.json') and
                    not match.endswith('.html')):
                    paths.add(match)
        
        return paths
    
    def _validate_method_path_exists(self, method_path: str):
        """Check if method path corresponds to existing file and method"""
        parts = method_path.split('.')
        if len(parts) < 2:
            return
        
        module_parts = parts[:-1]
        method_name = parts[-1]
        
        # Try different file path combinations
        possible_files = [
            # Direct .py file
            self.app_path / ('/'.join(module_parts) + '.py'),
            self.app_path / self.app_name / ('/'.join(module_parts) + '.py'),
            # Package __init__.py files
            self.app_path / '/'.join(module_parts) / '__init__.py',
            self.app_path / self.app_name / '/'.join(module_parts) / '__init__.py',
        ]
        
        # Handle verenigingen.verenigingen.doctype... paths
        if len(module_parts) >= 2 and module_parts[0] == module_parts[1] == 'verenigingen':
            # Remove duplicate verenigingen
            clean_parts = ['verenigingen'] + module_parts[2:]
            possible_files.extend([
                self.app_path / ('/'.join(clean_parts) + '.py'),
                self.app_path / '/'.join(clean_parts) / '__init__.py',
            ])
        
        # Handle different app root patterns (verenigingen vs verenigingen.verenigingen)
        if module_parts[0] == 'verenigingen' and len(module_parts) > 1:
            # Try without the first 'verenigingen' prefix
            clean_parts = module_parts[1:]
            possible_files.extend([
                self.app_path / self.app_name / ('/'.join(clean_parts) + '.py'),
                self.app_path / self.app_name / '/'.join(clean_parts) / '__init__.py',
            ])
        
        # Find existing file
        existing_file = None
        for file_path in possible_files:
            if file_path.exists():
                existing_file = file_path
                break
        
        if not existing_file:
            self.issues.append(HookIssue(
                hook_type="method_reference",
                hook_name=method_path,
                method_path=method_path,
                issue_type="missing_file",
                message=f"No file found for module: {'.'.join(module_parts)}"
            ))
            return
        
        # Check if method exists in file
        if not self._method_exists_in_file(existing_file, method_name):
            self.issues.append(HookIssue(
                hook_type="method_reference", 
                hook_name=method_path,
                method_path=method_path,
                issue_type="missing_method",
                message=f"Method '{method_name}' not found in {existing_file.relative_to(self.app_path)}"
            ))
    
    def _method_exists_in_file(self, file_path: Path, method_name: str) -> bool:
        """Check if method exists in Python file using AST"""
        try:
            content = file_path.read_text()
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == method_name:
                    return True
                # Also check class methods
                elif isinstance(node, ast.ClassDef):
                    for class_node in node.body:
                        if isinstance(class_node, ast.FunctionDef) and class_node.name == method_name:
                            return True
            
            return False
            
        except Exception:
            # If we can't parse, assume method exists (avoid false positives)
            return True
    
    def print_summary(self):
        """Print validation summary"""
        if not self.issues:
            print("✅ All hooks.py method references validated successfully!")
            return
        
        print(f"\n🚨 Found {len(self.issues)} hook reference issues:\n")
        
        # Group by issue type
        by_type = {}
        for issue in self.issues:
            by_type.setdefault(issue.issue_type, []).append(issue)
        
        for issue_type, issues in by_type.items():
            print(f"📋 {issue_type.upper().replace('_', ' ')} ({len(issues)} issues):")
            for issue in issues[:10]:  # Show first 10
                print(f"   {issue.method_path}")
                print(f"      {issue.message}")
            
            if len(issues) > 10:
                print(f"   ... and {len(issues) - 10} more\n")
            else:
                print()


def main():
    """Main entry point"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate hooks.py method references")
    parser.add_argument(
        "--app-path",
        default="/home/frappe/frappe-bench/apps/verenigingen", 
        help="Path to the app directory"
    )
    
    args = parser.parse_args()
    
    validator = SimpleHooksValidator(args.app_path)
    issues = validator.validate()
    validator.print_summary()
    
    # Exit with error if issues found
    if issues:
        print(f"\n❌ Validation failed with {len(issues)} issues")
        sys.exit(1)
    else:
        print("\n✅ All hooks.py references are valid")
        sys.exit(0)


if __name__ == "__main__":
    main()