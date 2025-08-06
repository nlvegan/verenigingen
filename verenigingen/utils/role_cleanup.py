#!/usr/bin/env python3
"""
Role Cleanup Utilities - Fix identified role issues
"""
import frappe
from frappe import _


@frappe.whitelist()
def remove_redundant_admin_roles():
    """Remove redundant Verenigingen Administrator roles from System Manager users"""

    results = {"removed_count": 0, "errors": [], "processed_users": []}

    try:
        # Find all users with System Manager role
        system_managers = frappe.get_all(
            "Has Role", filters={"role": "System Manager"}, fields=["parent"], pluck="parent"
        )

        for user in system_managers:
            try:
                # Check if this user also has Verenigingen Administrator role
                redundant_roles = frappe.get_all(
                    "Has Role",
                    filters={
                        "parent": user,
                        "role": ["in", ["Verenigingen Administrator", "Verenigingen Manager"]],
                    },
                    fields=["name", "role"],
                )

                for role_assignment in redundant_roles:
                    # Delete the redundant role assignment
                    frappe.delete_doc("Has Role", role_assignment.name)
                    results["removed_count"] += 1

                    results["processed_users"].append(
                        {"user": user, "removed_role": role_assignment.role, "status": "success"}
                    )

            except Exception as e:
                results["errors"].append({"user": user, "error": str(e)})
                continue

        # Commit changes
        frappe.db.commit()

        return results

    except Exception as e:
        frappe.db.rollback()
        results["errors"].append({"general_error": str(e)})
        return results


@frappe.whitelist()
def fix_chapter_permission_conflicts():
    """Fix permission conflicts in Chapter DocType for Chapter Board Member role"""

    results = {"conflicts_resolved": 0, "errors": []}

    try:
        # Get all Chapter Board Member permissions for Chapter DocType
        chapter_perms = frappe.get_all(
            "DocPerm",
            filters={"parent": "Chapter", "role": "Verenigingen Chapter Board Member"},
            fields=["name", "read", "write", "create", "delete", "if_owner", "idx"],
            order_by="idx",
        )

        if len(chapter_perms) > 1:
            # Keep the most permissive rule (the one with write=1)
            keep_rule = None
            remove_rules = []

            for perm in chapter_perms:
                if perm.write == 1:  # More permissive rule
                    if keep_rule is None:
                        keep_rule = perm
                    else:
                        remove_rules.append(perm)  # Duplicate permissive rule
                else:
                    remove_rules.append(perm)  # Less permissive rule

            # Remove redundant/conflicting rules
            for rule in remove_rules:
                frappe.delete_doc("DocPerm", rule.name)
                results["conflicts_resolved"] += 1

        frappe.db.commit()
        return results

    except Exception as e:
        frappe.db.rollback()
        results["errors"].append(str(e))
        return results


@frappe.whitelist()
def validate_role_cleanup():
    """Validate that role cleanup was successful"""

    validation = {
        "redundant_roles_remaining": 0,
        "permission_conflicts_remaining": 0,
        "cleanup_successful": True,
    }

    try:
        # Check for remaining redundant roles
        system_managers = frappe.get_all("Has Role", filters={"role": "System Manager"}, pluck="parent")

        for user in system_managers:
            redundant_roles = frappe.get_all(
                "Has Role",
                filters={
                    "parent": user,
                    "role": ["in", ["Verenigingen Administrator", "Verenigingen Manager"]],
                },
            )
            validation["redundant_roles_remaining"] += len(redundant_roles)

        # Check for remaining permission conflicts
        chapter_perms = frappe.get_all(
            "DocPerm", filters={"parent": "Chapter", "role": "Verenigingen Chapter Board Member"}
        )

        if len(chapter_perms) > 1:
            validation["permission_conflicts_remaining"] = len(chapter_perms) - 1

        validation["cleanup_successful"] = (
            validation["redundant_roles_remaining"] == 0 and validation["permission_conflicts_remaining"] == 0
        )

        return validation

    except Exception as e:
        validation["error"] = str(e)
        validation["cleanup_successful"] = False
        return validation


@frappe.whitelist()
def create_role_hierarchy_documentation():
    """Create documentation of the proper role hierarchy"""

    role_hierarchy = {
        "admin_tier": {
            "roles": ["System Manager"],
            "description": "Full system access - no other admin roles needed",
            "permissions": "Complete access to all doctypes and system functions",
        },
        "verenigingen_admin_tier": {
            "roles": ["Verenigingen Administrator"],
            "description": "Full access to Verenigingen module only",
            "permissions": "Create, read, update, delete all Verenigingen documents",
        },
        "verenigingen_staff_tier": {
            "roles": ["Verenigingen Staff", "Verenigingen Manager"],
            "description": "Daily operational access to Verenigingen functions",
            "permissions": "Read/write access to most Verenigingen documents, limited admin functions",
        },
        "specialized_roles": {
            "roles": ["Verenigingen Chapter Board Member", "Verenigingen Financial Manager"],
            "description": "Context-specific permissions for special functions",
            "permissions": "Limited access based on user's organizational role",
        },
        "member_tier": {
            "roles": ["Verenigingen Member"],
            "description": "Self-service access for association members",
            "permissions": "Read own records, update limited personal information",
        },
    }

    guidelines = {
        "assignment_rules": [
            "Never assign both System Manager and Verenigingen Administrator to the same user",
            "Use System Manager only for technical administrators",
            "Use Verenigingen Administrator for business administrators",
            "Assign Chapter Board Member only to actual board members",
            "Regular members should only have Verenigingen Member role",
        ],
        "common_mistakes": [
            "Assigning multiple admin roles to one user",
            "Using System Manager for business users",
            "Creating conflicting permission rules for the same role",
            "Assigning disabled roles to active users",
        ],
    }

    return {
        "hierarchy": role_hierarchy,
        "guidelines": guidelines,
        "generated_at": frappe.utils.now(),
        "total_active_roles": frappe.db.count("Role", {"disabled": 0}),
    }
