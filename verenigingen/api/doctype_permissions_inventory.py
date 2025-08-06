import json
import os
from pathlib import Path

import frappe


@frappe.whitelist()
def create_complete_doctype_inventory():
    """Create comprehensive DocType permissions inventory"""

    try:
        # Get all DocTypes in the system
        all_doctypes = frappe.db.sql(
            """
            SELECT name, module, app, custom, is_submittable, is_tree, istable, issingle
            FROM `tabDocType`
            ORDER BY app, module, name
        """,
            as_dict=True,
        )

        inventory = {
            "metadata": {
                "generated_by": frappe.session.user,
                "generated_at": frappe.utils.now(),
                "total_doctypes": len(all_doctypes),
                "apps": {},
                "modules": {},
            },
            "doctypes": {},
            "permission_summary": {
                "has_custom_permissions": [],
                "has_server_side_handlers": [],
                "has_query_conditions": [],
                "public_access": [],
                "restricted_access": [],
                "potential_issues": [],
            },
        }

        # Load hooks configuration
        hooks_config = load_hooks_permissions()

        # Process each DocType
        for doctype_info in all_doctypes:
            doctype_name = doctype_info["name"]

            try:
                # Get DocType meta
                meta = frappe.get_meta(doctype_name)

                # Analyze permissions
                permission_analysis = analyze_doctype_permissions(
                    doctype_name, meta, hooks_config, doctype_info
                )

                inventory["doctypes"][doctype_name] = permission_analysis

                # Update summaries
                update_permission_summaries(
                    inventory["permission_summary"], doctype_name, permission_analysis
                )

                # Update app/module stats
                app_name = doctype_info.get("app") or "Unknown"
                module_name = doctype_info.get("module") or "Unknown"

                if app_name not in inventory["metadata"]["apps"]:
                    inventory["metadata"]["apps"][app_name] = 0
                inventory["metadata"]["apps"][app_name] += 1

                if module_name not in inventory["metadata"]["modules"]:
                    inventory["metadata"]["modules"][module_name] = 0
                inventory["metadata"]["modules"][module_name] += 1

            except Exception as e:
                inventory["doctypes"][doctype_name] = {
                    "error": f"Failed to analyze: {str(e)}",
                    "basic_info": doctype_info,
                }

        # Save inventory to file
        inventory_file = "/home/frappe/frappe-bench/apps/verenigingen/docs/DOCTYPE_PERMISSIONS_INVENTORY.json"
        with open(inventory_file, "w") as f:
            json.dump(inventory, f, indent=2, default=str)

        # Create summary report
        create_summary_report(inventory)

        return {
            "success": True,
            "total_doctypes": len(all_doctypes),
            "inventory_file": inventory_file,
            "summary": {
                "apps": len(inventory["metadata"]["apps"]),
                "modules": len(inventory["metadata"]["modules"]),
                "custom_permissions": len(inventory["permission_summary"]["has_custom_permissions"]),
                "server_handlers": len(inventory["permission_summary"]["has_server_side_handlers"]),
                "potential_issues": len(inventory["permission_summary"]["potential_issues"]),
            },
        }

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


def load_hooks_permissions():
    """Load permission handlers from hooks.py"""
    try:
        # Import hooks module
        from verenigingen import hooks

        return {
            "permission_query_conditions": getattr(hooks, "permission_query_conditions", {}),
            "has_permission": getattr(hooks, "has_permission", {}),
        }
    except Exception as e:
        return {"permission_query_conditions": {}, "has_permission": {}, "hooks_error": str(e)}


def analyze_doctype_permissions(doctype_name, meta, hooks_config, doctype_info):
    """Analyze permissions for a single DocType"""

    analysis = {
        "basic_info": {
            "name": doctype_name,
            "app": doctype_info.get("app"),
            "module": doctype_info.get("module"),
            "custom": doctype_info.get("custom", 0),
            "is_submittable": doctype_info.get("is_submittable", 0),
            "is_tree": doctype_info.get("is_tree", 0),
            "is_child_table": doctype_info.get("istable", 0),
            "is_single": doctype_info.get("issingle", 0),
        },
        "doctype_permissions": [],
        "roles_with_access": {
            "read": [],
            "write": [],
            "create": [],
            "delete": [],
            "submit": [],
            "cancel": [],
        },
        "server_side_handlers": {
            "has_query_conditions": doctype_name in hooks_config["permission_query_conditions"],
            "has_permission_handler": doctype_name in hooks_config["has_permission"],
            "query_function": hooks_config["permission_query_conditions"].get(doctype_name),
            "permission_function": hooks_config["has_permission"].get(doctype_name),
        },
        "security_analysis": {
            "public_read": False,
            "guest_access": False,
            "owner_restricted": False,
            "user_permission_restricted": False,
            "select_conditions": False,
        },
        "potential_issues": [],
    }

    # Analyze DocType permissions
    if hasattr(meta, "permissions") and meta.permissions:
        for perm in meta.permissions:
            perm_data = {
                "role": perm.role,
                "read": getattr(perm, "read", 0),
                "write": getattr(perm, "write", 0),
                "create": getattr(perm, "create", 0),
                "delete": getattr(perm, "delete", 0),
                "submit": getattr(perm, "submit", 0),
                "cancel": getattr(perm, "cancel", 0),
                "amend": getattr(perm, "amend", 0),
                "print": getattr(perm, "print", 0),
                "email": getattr(perm, "email", 0),
                "share": getattr(perm, "share", 0),
                "export": getattr(perm, "export", 0),
                "report": getattr(perm, "report", 0),
                "import": getattr(perm, "import", 0),
                "if_owner": getattr(perm, "if_owner", 0),
                "select": getattr(perm, "select", None),
                "user_permission_doctypes": getattr(perm, "user_permission_doctypes", None),
            }

            analysis["doctype_permissions"].append(perm_data)

            # Track roles with different permissions
            for perm_type in ["read", "write", "create", "delete", "submit", "cancel"]:
                if perm_data.get(perm_type):
                    analysis["roles_with_access"][perm_type].append(perm.role)

            # Security analysis
            if perm_data["read"]:
                if perm.role == "Guest":
                    analysis["security_analysis"]["guest_access"] = True
                if perm.role in ["All", "Website User"]:
                    analysis["security_analysis"]["public_read"] = True
                if perm_data["if_owner"]:
                    analysis["security_analysis"]["owner_restricted"] = True
                if perm_data["user_permission_doctypes"]:
                    analysis["security_analysis"]["user_permission_restricted"] = True
                if perm_data["select"]:
                    analysis["security_analysis"]["select_conditions"] = True

    # Identify potential issues
    identify_potential_issues(analysis, doctype_name)

    return analysis


def identify_potential_issues(analysis, doctype_name):
    """Identify potential permission issues"""

    issues = []

    # Issue 1: No read access for any role
    if not analysis["roles_with_access"]["read"]:
        issues.append("NO_READ_ACCESS: No roles have read access to this DocType")

    # Issue 2: Guest/Public access without restrictions
    if (
        analysis["security_analysis"]["guest_access"]
        and not analysis["server_side_handlers"]["has_permission_handler"]
    ):
        issues.append("UNRESTRICTED_GUEST_ACCESS: Guest role has access without server-side restrictions")

    # Issue 3: Public read without filtering
    if analysis["security_analysis"]["public_read"] and not (
        analysis["server_side_handlers"]["has_query_conditions"]
        or analysis["security_analysis"]["select_conditions"]
    ):
        issues.append("UNRESTRICTED_PUBLIC_READ: Public read access without filtering")

    # Issue 4: Sensitive DocTypes with broad access
    sensitive_doctypes = [
        "User",
        "Member",
        "Payment Entry",
        "Sales Invoice",
        "Purchase Invoice",
        "Membership Dues Schedule",
        "Verenigingen Volunteer",
        "Donation",
    ]
    if doctype_name in sensitive_doctypes:
        read_roles = analysis["roles_with_access"]["read"]
        if len(read_roles) > 5:  # More than 5 roles have read access
            issues.append(
                f"BROAD_ACCESS_SENSITIVE: Sensitive DocType has {len(read_roles)} roles with read access"
            )

    # Issue 5: Write access without read access
    for role_data in analysis["doctype_permissions"]:
        if role_data["write"] and not role_data["read"]:
            issues.append(f"WRITE_WITHOUT_READ: Role '{role_data['role']}' has write but not read access")

    # Issue 6: Server-side handler exists but no DocType permissions
    if analysis["server_side_handlers"]["has_permission_handler"] and not analysis["doctype_permissions"]:
        issues.append("HANDLER_WITHOUT_DOCTYPE_PERMS: Has server-side handler but no DocType permissions")

    # Issue 7: Complex permission setup (potential maintenance issue)
    if len(analysis["doctype_permissions"]) > 8:
        issues.append(
            f"COMPLEX_PERMISSIONS: {len(analysis['doctype_permissions'])} permission entries may be hard to maintain"
        )

    analysis["potential_issues"] = issues


def update_permission_summaries(summary, doctype_name, analysis):
    """Update summary statistics"""

    # Custom permissions (non-standard permission patterns)
    if (
        analysis["security_analysis"]["select_conditions"]
        or analysis["security_analysis"]["user_permission_restricted"]
        or len(analysis["doctype_permissions"]) > 4
    ):
        summary["has_custom_permissions"].append(doctype_name)

    # Server-side handlers
    if (
        analysis["server_side_handlers"]["has_query_conditions"]
        or analysis["server_side_handlers"]["has_permission_handler"]
    ):
        summary["has_server_side_handlers"].append(doctype_name)

    # Query conditions
    if analysis["server_side_handlers"]["has_query_conditions"]:
        summary["has_query_conditions"].append(doctype_name)

    # Public access
    if analysis["security_analysis"]["public_read"] or analysis["security_analysis"]["guest_access"]:
        summary["public_access"].append(doctype_name)

    # Restricted access
    if (
        analysis["security_analysis"]["owner_restricted"]
        or analysis["security_analysis"]["user_permission_restricted"]
        or analysis["server_side_handlers"]["has_permission_handler"]
    ):
        summary["restricted_access"].append(doctype_name)

    # Potential issues
    if analysis["potential_issues"]:
        summary["potential_issues"].append({"doctype": doctype_name, "issues": analysis["potential_issues"]})


def create_summary_report(inventory):
    """Create human-readable summary report"""

    report_lines = [
        "# DocType Permissions Inventory Summary",
        f"Generated: {inventory['metadata']['generated_at']}",
        f"By: {inventory['metadata']['generated_by']}",
        "",
        "## Overview",
        f"- Total DocTypes: {inventory['metadata']['total_doctypes']}",
        f"- Apps: {len(inventory['metadata']['apps'])}",
        f"- Modules: {len(inventory['metadata']['modules'])}",
        "",
        "## Apps Breakdown",
    ]

    for app, count in sorted(inventory["metadata"]["apps"].items()):
        report_lines.append(f"- {app}: {count} DocTypes")

    report_lines.extend(
        [
            "",
            "## Permission Categories",
            f"- Custom Permissions: {len(inventory['permission_summary']['has_custom_permissions'])}",
            f"- Server-Side Handlers: {len(inventory['permission_summary']['has_server_side_handlers'])}",
            f"- Query Conditions: {len(inventory['permission_summary']['has_query_conditions'])}",
            f"- Public Access: {len(inventory['permission_summary']['public_access'])}",
            f"- Restricted Access: {len(inventory['permission_summary']['restricted_access'])}",
            "",
            "## Potential Issues",
            f"Total DocTypes with issues: {len(inventory['permission_summary']['potential_issues'])}",
        ]
    )

    if inventory["permission_summary"]["potential_issues"]:
        report_lines.append("")
        report_lines.append("### Issues by DocType")
        for issue_info in inventory["permission_summary"]["potential_issues"]:
            report_lines.append(f"**{issue_info['doctype']}**:")
            for issue in issue_info["issues"]:
                report_lines.append(f"  - {issue}")
            report_lines.append("")

    # High-priority issues
    high_priority_issues = []
    for issue_info in inventory["permission_summary"]["potential_issues"]:
        for issue in issue_info["issues"]:
            if any(keyword in issue for keyword in ["UNRESTRICTED", "SENSITIVE", "NO_READ_ACCESS"]):
                high_priority_issues.append(f"{issue_info['doctype']}: {issue}")

    if high_priority_issues:
        report_lines.extend(["## High Priority Issues", "These issues should be addressed immediately:", ""])
        for issue in high_priority_issues:
            report_lines.append(f"- {issue}")

    # Save summary report
    summary_file = "/home/frappe/frappe-bench/apps/verenigingen/docs/DOCTYPE_PERMISSIONS_SUMMARY.md"
    with open(summary_file, "w") as f:
        f.write("\n".join(report_lines))

    return summary_file
