#!/usr/bin/env python3
"""
Test script to validate hooks.py configuration.

This script checks for common issues in the hooks configuration:
1. Duplicate doc_events dictionaries
2. Proper Sales Invoice hook configuration
3. Import validation
"""

import ast
import os
import sys


def analyze_hooks_file(file_path):
    """Analyze hooks.py file for configuration issues."""
    print("Analyzing hooks.py file...")

    with open(file_path, "r") as f:
        content = f.read()

    # Parse the Python file
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        print(f"❌ Syntax error in hooks.py: {e}")
        return False

    # Find all doc_events assignments
    doc_events_assignments = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "doc_events":
                    doc_events_assignments.append(node.lineno)

    print(f"Found {len(doc_events_assignments)} doc_events assignments at lines: {doc_events_assignments}")

    if len(doc_events_assignments) > 1:
        print("❌ CRITICAL: Multiple doc_events dictionaries found!")
        print("   This means only the LAST one will be used, and previous ones are ignored!")
        return False

    # Check for Sales Invoice configuration
    sales_invoice_hooks = []
    lines = content.split("\n")

    for i, line in enumerate(lines, 1):
        if (
            "Sales Invoice" in line
            and "doc_events" in content[max(0, content.find(line) - 500) : content.find(line) + 500]
        ):
            sales_invoice_hooks.append((i, line.strip()))

    print(f"\nSales Invoice hooks found:")
    for line_num, line_content in sales_invoice_hooks:
        print(f"  Line {line_num}: {line_content}")

    # Test import of the hooks module
    try:
        # Add the verenigingen app to the path
        app_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, app_path)

        # Mock frappe for import
        class MockFrappe:
            pass

        sys.modules["frappe"] = MockFrappe()

        # Import the hooks module
        import hooks

        # Check if doc_events exists and has Sales Invoice
        if hasattr(hooks, "doc_events"):
            doc_events = hooks.doc_events
            if isinstance(doc_events, dict):
                print(f"\n✓ doc_events imported successfully with {len(doc_events)} doctypes")

                if "Sales Invoice" in doc_events:
                    si_events = doc_events["Sales Invoice"]
                    print(f"✓ Sales Invoice events found: {list(si_events.keys())}")

                    # Check for the specific handler
                    for event, handlers in si_events.items():
                        if isinstance(handlers, list):
                            for handler in handlers:
                                if "sales_invoice_account_handler" in str(handler):
                                    print(f"✓ Found sales_invoice_account_handler in {event} event")
                        elif "sales_invoice_account_handler" in str(handlers):
                            print(f"✓ Found sales_invoice_account_handler in {event} event")
                else:
                    print("❌ Sales Invoice not found in doc_events")
                    return False
            else:
                print("❌ doc_events is not a dictionary")
                return False
        else:
            print("❌ doc_events not found in hooks module")
            return False

    except Exception as e:
        print(f"❌ Error importing hooks: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✅ Hooks validation completed successfully!")
    return True


def main():
    """Run hooks validation."""
    hooks_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/hooks.py"

    if not os.path.exists(hooks_path):
        print(f"❌ hooks.py not found at {hooks_path}")
        return False

    return analyze_hooks_file(hooks_path)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
