#!/usr/bin/env python3
"""
Workspace Link Validator
Validates that workspace links point to existing DocTypes/Pages/Reports/Dashboards
"""

import frappe


def validate_workspace_links(workspace_name):
    """Check if all workspace links point to valid targets"""

    links = frappe.db.sql(
        """
        SELECT label, link_to, link_type, type
        FROM `tabWorkspace Link`
        WHERE parent = %s AND type = 'Link'
        ORDER BY label
    """,
        workspace_name,
        as_dict=True,
    )

    results = []

    for link in links:
        valid = True
        error_msg = None
        warning_msg = None

        try:
            if link.link_type == "DocType":
                # Check if DocType exists
                if not frappe.db.exists("DocType", link.link_to):
                    valid = False
                    error_msg = f"DocType '{link.link_to}' does not exist"
                else:
                    # Check if DocType is active
                    doctype_doc = frappe.get_doc("DocType", link.link_to)
                    if getattr(doctype_doc, "is_disabled", False):
                        warning_msg = f"DocType '{link.link_to}' is disabled"

            elif link.link_type == "Report":
                # Check if Report exists
                if not frappe.db.exists("Report", link.link_to):
                    valid = False
                    error_msg = f"Report '{link.link_to}' does not exist"
                else:
                    # Check if Report is enabled
                    report_doc = frappe.get_doc("Report", link.link_to)
                    if report_doc.disabled:
                        warning_msg = f"Report '{link.link_to}' is disabled"

            elif link.link_type == "Dashboard":
                # Check if Dashboard exists
                if not frappe.db.exists("Dashboard", link.link_to):
                    valid = False
                    error_msg = f"Dashboard '{link.link_to}' does not exist"

            elif link.link_type == "Page":
                # Check if Page exists (known valid pages)
                known_pages = ["Dashboard", "desk", "workspace"]
                if link.link_to not in known_pages:
                    if not frappe.db.exists("Page", link.link_to):
                        valid = False
                        error_msg = f"Page '{link.link_to}' does not exist"

            else:
                # Unknown link type
                valid = False
                error_msg = f"Unknown link_type '{link.link_type}'"

        except Exception as e:
            valid = False
            error_msg = f"Validation error: {str(e)}"

        results.append(
            {
                "label": link.label,
                "link_to": link.link_to,
                "link_type": link.link_type,
                "valid": valid,
                "error": error_msg,
                "warning": warning_msg,
            }
        )

    return results


def print_link_validation(workspace_name):
    """Print validation results for workspace links"""
    results = validate_workspace_links(workspace_name)

    print(f"=== Link Validation: {workspace_name} ===")

    valid_count = sum(1 for r in results if r["valid"])
    warning_count = sum(1 for r in results if r["warning"])
    total_count = len(results)

    print(f"Valid links: {valid_count}/{total_count}")
    if warning_count > 0:
        print(f"Warnings: {warning_count}")
    print()

    # Group by status
    errors = [r for r in results if not r["valid"]]
    warnings = [r for r in results if r["valid"] and r["warning"]]
    valid = [r for r in results if r["valid"] and not r["warning"]]

    if errors:
        print("❌ ERRORS:")
        for result in errors:
            print(f"   {result['label']}")
            print(f"   → {result['link_type']}: {result['link_to']}")
            print(f"   💥 {result['error']}")
            print()

    if warnings:
        print("⚠️  WARNINGS:")
        for result in warnings:
            print(f"   {result['label']}")
            print(f"   → {result['link_type']}: {result['link_to']}")
            print(f"   ⚠️  {result['warning']}")
            print()

    if valid:
        print(f"✅ VALID LINKS ({len(valid)}):")
        for result in valid[:10]:  # Show first 10
            print(f"   {result['label']} → {result['link_type']}: {result['link_to']}")
        if len(valid) > 10:
            print(f"   ... and {len(valid) - 10} more")
        print()

    return results


def fix_invalid_links(workspace_name, dry_run=True):
    """Attempt to fix common invalid link issues"""

    results = validate_workspace_links(workspace_name)
    errors = [r for r in results if not r["valid"]]

    if not errors:
        print("✅ No invalid links found")
        return True

    print(f"🔧 Found {len(errors)} invalid links to fix")

    for error in errors:
        print(f"Analyzing: {error['label']}")

        # Common fixes
        fixed = False

        if "does not exist" in error["error"]:
            if error["link_type"] == "DocType":
                # Try to find similar DocType names
                similar = frappe.db.sql(
                    """
                    SELECT name FROM `tabDocType`
                    WHERE name LIKE %s OR name LIKE %s
                    LIMIT 5
                """,
                    (f"%{error['link_to']}%", f"{error['link_to']}%"),
                    as_list=True,
                )

                if similar:
                    print(f"  Possible alternatives: {[s[0] for s in similar]}")

        if not fixed:
            print(f"  ❌ No automatic fix available")

    if not dry_run:
        print("🚫 Automatic fixes not implemented yet - manual intervention required")
    else:
        print("🚫 Dry run mode - no changes made")

    return len(errors) == 0
