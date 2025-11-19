#!/usr/bin/env python3
"""
Fix missing app field in all verenigingen doctype JSON files
"""

import json
import os
import re


def fix_doctype_json_files():
    """Add app field to all doctype JSON files that are missing it"""

    doctype_dir = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype"

    if not os.path.exists(doctype_dir):
        print(f"Doctype directory not found: {doctype_dir}")
        return

    fixed_count = 0
    error_count = 0

    # Get all subdirectories (each contains a doctype)
    for item in os.listdir(doctype_dir):
        item_path = os.path.join(doctype_dir, item)
        if os.path.isdir(item_path):
            json_file = os.path.join(item_path, f"{item}.json")

            if os.path.exists(json_file):
                try:
                    print(f"Processing: {item}")

                    # Read the JSON file
                    with open(json_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    # Parse JSON
                    data = json.loads(content)

                    # Check if app field exists and is correct
                    if data.get("app") != "verenigingen":
                        print(f"  - Adding app field to {item}")

                        # Add app field in the right position (after actions, before autoname/creation)
                        # We'll do this with string manipulation to preserve formatting

                        # Find the position after opening brace and actions
                        pattern = r'(\{\s*"actions":\s*\[.*?\],?\s*)'
                        match = re.search(pattern, content, re.DOTALL)

                        if match:
                            # Insert app field after actions
                            before = match.group(1)
                            after = content[match.end() :]

                            # Add app field with proper formatting
                            new_content = before + '\n "app": "verenigingen",' + after
                        else:
                            # Fallback: insert after opening brace
                            new_content = content.replace("{", '{\n "app": "verenigingen",', 1)

                        # Write back to file
                        with open(json_file, "w", encoding="utf-8") as f:
                            f.write(new_content)

                        fixed_count += 1
                        print(f"  ✓ Fixed {item}")
                    else:
                        print(f"  - {item} already has correct app field")

                except Exception as e:
                    print(f"  ✗ Error processing {item}: {e}")
                    error_count += 1
            else:
                print(f"  - No JSON file found for {item}")

    print(f"\nSummary:")
    print(f"  Fixed: {fixed_count} doctypes")
    print(f"  Errors: {error_count} doctypes")


if __name__ == "__main__":
    fix_doctype_json_files()
