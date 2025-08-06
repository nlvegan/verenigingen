#!/usr/bin/env python3
"""
Update Role References Script

This script updates all code references to use the new Verenigingen-prefixed role names.
It performs comprehensive find-and-replace operations across Python, JSON, and HTML files.
"""

import json
import os
import re
from pathlib import Path

import frappe

# Role mapping: old_name -> new_name
ROLE_MAPPINGS = {
    "Verenigingen Chapter Board Member": "Verenigingen Chapter Board Member",
    "Verenigingen Chapter Manager": "Verenigingen Chapter Manager",
    "Verenigingen Volunteer": "Verenigingen Volunteer",
    "Verenigingen Volunteer Manager": "Verenigingen Volunteer Manager",
    "Verenigingen Governance Auditor": "Verenigingen Governance Auditor",  # For future use if role is created
}


@frappe.whitelist()
def update_all_role_references():
    """Update all role references in code files"""

    results = {"files_updated": [], "files_skipped": [], "errors": [], "summary": {}}

    print("🔄 Starting role reference update process...")
    print("=" * 60)

    # Get app path
    app_path = frappe.get_app_path("verenigingen")

    # Define file patterns to search
    file_patterns = ["**/*.py", "**/*.json", "**/*.html", "**/*.js", "**/*.md"]

    files_to_update = []

    # Collect all relevant files
    for pattern in file_patterns:
        files_to_update.extend(Path(app_path).glob(pattern))

    # Add additional search locations
    additional_paths = [
        Path(app_path).parent / "scripts",
        Path(app_path).parent / "docs",
        Path(app_path).parent / "archived_docs",
    ]

    for additional_path in additional_paths:
        if additional_path.exists():
            for pattern in file_patterns:
                files_to_update.extend(additional_path.glob(pattern))

    print(f"📁 Found {len(files_to_update)} files to check")

    # Process each file
    for file_path in files_to_update:
        try:
            # Skip binary files and certain directories
            if should_skip_file(file_path):
                continue

            if update_file_role_references(file_path):
                results["files_updated"].append(str(file_path))
                print(f"✅ Updated: {file_path.relative_to(Path(app_path).parent)}")
            else:
                results["files_skipped"].append(str(file_path))

        except Exception as e:
            error_msg = f"Error processing {file_path}: {str(e)}"
            results["errors"].append(error_msg)
            print(f"❌ Error: {error_msg}")
            frappe.log_error(error_msg, "Role Reference Update")

    # Generate summary
    results["summary"] = {
        "total_files_checked": len(files_to_update),
        "files_updated": len(results["files_updated"]),
        "files_skipped": len(results["files_skipped"]),
        "errors": len(results["errors"]),
    }

    print("\n" + "=" * 60)
    print("📊 FINAL SUMMARY:")
    print(f"   Total files checked: {results['summary']['total_files_checked']}")
    print(f"   Files updated: {results['summary']['files_updated']}")
    print(f"   Files skipped: {results['summary']['files_skipped']}")
    print(f"   Errors: {results['summary']['errors']}")

    print("\n🎉 Role reference update process complete!")

    return results


def should_skip_file(file_path):
    """Check if file should be skipped"""

    # Skip certain file types and directories
    skip_patterns = [
        "__pycache__",
        ".git",
        ".pyc",
        "node_modules",
        ".egg-info",
        "archived_unused",
        "one-off-test-utils",
    ]

    file_str = str(file_path)

    for pattern in skip_patterns:
        if pattern in file_str:
            return True

    # Skip very large files
    try:
        if file_path.stat().st_size > 1024 * 1024:  # 1MB
            return True
    except:
        return True

    return False


def update_file_role_references(file_path):
    """Update role references in a single file"""

    try:
        # Read file content
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        original_content = content

        # Apply role mappings
        for old_role, new_role in ROLE_MAPPINGS.items():
            # Update quoted strings
            content = content.replace(f'"{old_role}"', f'"{new_role}"')
            content = content.replace(f"'{old_role}'", f"'{new_role}'")

            # Handle role lists and arrays
            content = re.sub(rf'(\[[\s\S]*?"){re.escape(old_role)}("[\s\S]*?\])', rf"\1{new_role}\2", content)

            # Handle dictionary/object values
            content = re.sub(
                rf"([\"\']role[\"\'][\s:=]+[\"\']){re.escape(old_role)}([\"\'])", rf"\1{new_role}\2", content
            )

            # Handle has_role and similar function calls
            content = re.sub(
                rf"(has_role\([^\)]*[\"\']){re.escape(old_role)}([\"\'][^\)]*\))", rf"\1{new_role}\2", content
            )

            # Handle get_roles comparisons
            content = re.sub(rf"([=!]+[\s]*[\"\']){re.escape(old_role)}([\"\'])", rf"\1{new_role}\2", content)

            # Handle 'in' operator with roles
            content = re.sub(
                rf"([\"\']){re.escape(old_role)}([\"\'][\s]+in[\s]+)", rf"\1{new_role}\2", content
            )

        # Only write if content changed
        if content != original_content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True

        return False

    except Exception as e:
        raise Exception(f"Failed to update {file_path}: {str(e)}")


@frappe.whitelist()
def validate_role_updates():
    """Validate that role updates were applied correctly"""

    validation_results = {"old_references_found": [], "new_references_confirmed": [], "potential_issues": []}

    app_path = frappe.get_app_path("verenigingen")

    # Search for any remaining old role references
    for old_role in ROLE_MAPPINGS.keys():
        # Skip "Verenigingen Volunteer" as it might be used in other contexts
        if old_role == "Verenigingen Volunteer":
            continue

        old_refs = search_for_role_references(app_path, old_role)
        if old_refs:
            validation_results["old_references_found"].extend(old_refs)

    # Check for new role references
    for new_role in ROLE_MAPPINGS.values():
        new_refs = search_for_role_references(app_path, new_role)
        validation_results["new_references_confirmed"].extend(new_refs)

    print("🔍 Validation Results:")
    print(f"   Old references still found: {len(validation_results['old_references_found'])}")
    print(f"   New references confirmed: {len(validation_results['new_references_confirmed'])}")

    if validation_results["old_references_found"]:
        print("\n⚠️  Old references still found in:")
        for ref in validation_results["old_references_found"][:10]:  # Show first 10
            print(f"   - {ref}")

    return validation_results


def search_for_role_references(base_path, role_name):
    """Search for role references in files"""
    references = []

    try:
        for file_path in Path(base_path).rglob("*.py"):
            if should_skip_file(file_path):
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Look for quoted role references
                if f'"{role_name}"' in content or f"'{role_name}'" in content:
                    references.append(str(file_path.relative_to(Path(base_path).parent)))

            except Exception:
                continue

    except Exception as e:
        frappe.log_error(f"Error searching for {role_name}: {str(e)}")

    return references


if __name__ == "__main__":
    # For direct execution
    print("🚀 Role Reference Updater")
    print(
        "Run via: bench --site dev.veganisme.net execute verenigingen.utils.update_role_references.update_all_role_references"
    )
