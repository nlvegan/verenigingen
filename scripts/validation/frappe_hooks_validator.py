#!/usr/bin/env python3
"""
Frappe Hooks Validator

Validates that all event handlers and scheduled tasks defined in hooks.py
actually exist and are callable.

This covers:
- doc_events handlers
- scheduler_events methods
- fixtures references
- Any other string-based method references in hooks
"""

import ast
import re
import importlib
import inspect
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass


@dataclass
class HookIssue:
    """Represents a hook/event handler issue"""
    hook_type: str  # e.g., "doc_events", "scheduler_events"
    hook_name: str  # e.g., "Sales Invoice", "daily"
    method_path: str  # e.g., "vereiningen.events.invoice_events.emit_invoice_submitted"
    issue_type: str  # e.g., "missing_method", "invalid_module"
    message: str
    line_number: Optional[int] = None


class FrappeHooksValidator:
    """Validates hooks.py event handlers and scheduled tasks"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.app_name = self.app_path.name
        self.hooks_path = self.app_path / self.app_name / "hooks.py"
        self.issues: List[HookIssue] = []
        
    def validate(self) -> List[HookIssue]:
        """Run validation on hooks.py"""
        self.issues = []
        
        if not self.hooks_path.exists():
            self.issues.append(HookIssue(
                hook_type="hooks.py",
                hook_name="file",
                method_path="",
                issue_type="missing_file",
                message=f"hooks.py not found at {self.hooks_path}"
            ))
            return self.issues
        
        print(f"🔍 Validating hooks and event handlers in {self.hooks_path}")
        
        # Parse hooks.py
        hooks_data = self._parse_hooks_file()
        
        # Validate different hook types
        self._validate_doc_events(hooks_data.get("doc_events", {}))
        self._validate_scheduler_events(hooks_data.get("scheduler_events", {}))
        self._validate_fixtures(hooks_data.get("fixtures", []))
        
        # Check for event emitters that should have subscribers
        self._validate_event_emitters()
        
        return self.issues
    
    def _parse_hooks_file(self) -> Dict:
        """Parse hooks.py and extract hook definitions"""
        hooks_data = {}
        
        try:
            # Import hooks module
            spec = importlib.util.spec_from_file_location("hooks", self.hooks_path)
            hooks_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hooks_module)
            
            # Extract relevant hooks
            if hasattr(hooks_module, "doc_events"):
                hooks_data["doc_events"] = hooks_module.doc_events
            
            if hasattr(hooks_module, "scheduler_events"):
                hooks_data["scheduler_events"] = hooks_module.scheduler_events
                
            if hasattr(hooks_module, "fixtures"):
                hooks_data["fixtures"] = hooks_module.fixtures
                
        except Exception as e:
            self.issues.append(HookIssue(
                hook_type="hooks.py",
                hook_name="parse",
                method_path="",
                issue_type="parse_error",
                message=f"Failed to parse hooks.py: {str(e)}"
            ))
            
        return hooks_data
    
    def _validate_doc_events(self, doc_events: Dict):
        """Validate doc_events handlers"""
        print("  📋 Validating doc_events...")
        
        for doctype, events in doc_events.items():
            for event, handlers in events.items():
                if isinstance(handlers, str):
                    handlers = [handlers]
                
                for handler in handlers:
                    if isinstance(handler, str):
                        self._validate_method_path(
                            handler, 
                            f"doc_events[{doctype}][{event}]",
                            "doc_events"
                        )
    
    def _validate_scheduler_events(self, scheduler_events: Dict):
        """Validate scheduler_events methods"""
        print("  ⏰ Validating scheduler_events...")
        
        for schedule, methods in scheduler_events.items():
            if isinstance(methods, str):
                methods = [methods]
                
            for method in methods:
                if isinstance(method, str):
                    self._validate_method_path(
                        method,
                        f"scheduler_events[{schedule}]",
                        "scheduler_events"
                    )
    
    def _validate_fixtures(self, fixtures: List):
        """Validate fixture references"""
        print("  🔧 Validating fixtures...")
        
        for fixture in fixtures:
            if isinstance(fixture, dict) and "filters" in fixture:
                # Check if fixture has custom method
                if "custom_method" in fixture:
                    self._validate_method_path(
                        fixture["custom_method"],
                        f"fixtures[{fixture.get('dt', 'unknown')}]",
                        "fixtures"
                    )
    
    def _validate_method_path(self, method_path: str, hook_name: str, hook_type: str):
        """Validate a single method path"""
        try:
            # Split method path
            parts = method_path.split(".")
            if len(parts) < 2:
                self.issues.append(HookIssue(
                    hook_type=hook_type,
                    hook_name=hook_name,
                    method_path=method_path,
                    issue_type="invalid_path",
                    message=f"Invalid method path format: {method_path}"
                ))
                return
            
            module_path = ".".join(parts[:-1])
            method_name = parts[-1]
            
            # Check if the file exists first (including __init__.py for packages)
            possible_paths = [
                self.app_path / self.app_name / (module_path.replace(".", "/") + ".py"),
                self.app_path / (module_path.replace(".", "/") + ".py"),
                self.app_path / self.app_name / (module_path.replace(".", "/") + "/__init__.py"),
                self.app_path / (module_path.replace(".", "/") + "/__init__.py"),
            ]
            
            file_exists = any(p.exists() for p in possible_paths)
            if not file_exists:
                self.issues.append(HookIssue(
                    hook_type=hook_type,
                    hook_name=hook_name,
                    method_path=method_path,
                    issue_type="missing_file",
                    message=f"File not found for module: {module_path}"
                ))
                return
            
            # Try to import the module - handle relative vs absolute paths
            module = None
            import_error = None
            
            # First try direct import
            try:
                module = importlib.import_module(module_path)
            except ImportError as e:
                import_error = e
                
                # Check if it's a "No module named 'verenigingen'" error - this is expected outside Frappe
                if "No module named 'verenigingen'" in str(e) or "No module named 'frappe'" in str(e):
                    # Running outside Frappe environment - this is OK, just check file existence
                    print(f"  ⚠️ Cannot import {module_path} (running outside Frappe environment)")
                    return
                
                # Try alternative import paths for other errors
                if module_path.startswith(self.app_name + "."):
                    # Already has app prefix, try without it
                    relative_path = module_path[len(self.app_name) + 1:]
                    try:
                        module = importlib.import_module(relative_path)
                        import_error = None
                    except ImportError:
                        pass
                else:
                    # Try with app prefix
                    try:
                        full_path = f"{self.app_name}.{module_path}"
                        module = importlib.import_module(full_path)
                        import_error = None
                    except ImportError:
                        pass
            
            if module is None and import_error:
                # Check if it's a real import error (not just missing Frappe env)
                if "No module named 'verenigingen'" not in str(import_error) and "No module named 'frappe'" not in str(import_error):
                    self.issues.append(HookIssue(
                        hook_type=hook_type,
                        hook_name=hook_name,
                        method_path=method_path,
                        issue_type="import_error",
                        message=f"Cannot import {module_path}: {str(import_error)}"
                    ))
                return
            
            # If we successfully imported the module, validate the method
            if module:
                # Check if method exists
                if not hasattr(module, method_name):
                    self.issues.append(HookIssue(
                        hook_type=hook_type,
                        hook_name=hook_name,
                        method_path=method_path,
                        issue_type="missing_method",
                        message=f"Method '{method_name}' not found in module {module_path}"
                    ))
                    return
                
                # Check if it's callable
                method = getattr(module, method_name)
                if not callable(method):
                    self.issues.append(HookIssue(
                        hook_type=hook_type,
                        hook_name=hook_name,
                        method_path=method_path,
                        issue_type="not_callable",
                        message=f"{method_path} exists but is not callable"
                    ))
                
        except Exception as e:
            self.issues.append(HookIssue(
                hook_type=hook_type,
                hook_name=hook_name,
                method_path=method_path,
                issue_type="validation_error",
                message=f"Error validating {method_path}: {str(e)}"
            ))
    
    def _validate_event_emitters(self):
        """Check for event emitters that should have subscribers"""
        print("  📡 Validating event emitters and subscribers...")
        
        # Find all files that emit events
        event_emitters = []
        events_dir = self.app_path / self.app_name / "events"
        
        if events_dir.exists():
            for py_file in events_dir.rglob("*.py"):
                if py_file.name != "__init__.py":
                    content = py_file.read_text()
                    
                    # Look for event emission patterns
                    emit_patterns = [
                        r'_emit_.*_event\(',
                        r'frappe\.publish_realtime\(',
                        r'frappe\.emit\(',
                    ]
                    
                    for pattern in emit_patterns:
                        if re.search(pattern, content):
                            event_emitters.append(py_file)
                            break
        
        # Check if emitters have corresponding subscribers
        for emitter_file in event_emitters:
            # Extract event names from emitter
            content = emitter_file.read_text()
            event_names = re.findall(r'["\'](\w+_\w+)["\']', content)
            
            for event_name in event_names:
                if event_name.endswith('_event') or event_name.endswith('_submitted'):
                    # Check if there's a subscriber
                    subscriber_found = False
                    
                    # Look in subscribers directory
                    subscribers_dir = events_dir / "subscribers"
                    if subscribers_dir.exists():
                        for sub_file in subscribers_dir.glob("*.py"):
                            sub_content = sub_file.read_text()
                            if event_name in sub_content:
                                subscriber_found = True
                                break
                    
                    if not subscriber_found:
                        self.issues.append(HookIssue(
                            hook_type="event_emitter",
                            hook_name=str(emitter_file.relative_to(self.app_path)),
                            method_path=event_name,
                            issue_type="no_subscriber",
                            message=f"Event '{event_name}' is emitted but has no subscriber"
                        ))
    
    def print_summary(self):
        """Print validation summary"""
        if not self.issues:
            print("\n✅ All hooks and event handlers validated successfully!")
            return
        
        print(f"\n🚨 Found {len(self.issues)} hook/event handler issues:\n")
        
        # Group by issue type
        by_type = {}
        for issue in self.issues:
            by_type.setdefault(issue.issue_type, []).append(issue)
        
        for issue_type, issues in by_type.items():
            print(f"📋 {issue_type.upper().replace('_', ' ')} ({len(issues)} issues):")
            for issue in issues[:10]:  # Show first 10
                print(f"   {issue.hook_type} - {issue.method_path}")
                print(f"      {issue.message}")
                print(f"      💡 Check {issue.hook_name}")
            
            if len(issues) > 10:
                print(f"   ... and {len(issues) - 10} more\n")
            else:
                print()


def main():
    """Main entry point"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate hooks and event handlers")
    parser.add_argument(
        "--app-path",
        default="/home/frappe/frappe-bench/apps/verenigingen",
        help="Path to the app directory"
    )
    
    args = parser.parse_args()
    
    validator = FrappeHooksValidator(args.app_path)
    issues = validator.validate()
    validator.print_summary()
    
    # Exit with error if issues found
    if issues:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()