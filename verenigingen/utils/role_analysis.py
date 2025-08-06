#!/usr/bin/env python3
"""
Role Analysis Utilities - Analyze current role usage and identify issues
"""
import frappe
from frappe import _


def analyze_current_role_structure():
    """Analyze current roles and identify potential issues"""

    results = {
        "total_roles": 0,
        "role_categories": {},
        "redundancy_issues": [],
        "permission_conflicts": [],
        "hierarchy_problems": [],
    }

    # Get all active roles
    roles = frappe.get_all(
        "Role",
        filters={"disabled": 0},
        fields=["name", "desk_access", "is_custom", "home_page"],
        order_by="name",
    )

    results["total_roles"] = len(roles)

    # Categorize roles
    system_roles = []
    custom_roles = []
    verenigingen_roles = []

    for role in roles:
        if role.is_custom:
            custom_roles.append(role.name)
        elif "Verenigingen" in role.name or "Chapter" in role.name:
            verenigingen_roles.append(role.name)
        else:
            system_roles.append(role.name)

    results["role_categories"] = {
        "system": system_roles,
        "verenigingen": verenigingen_roles,
        "custom": custom_roles,
    }

    # Find role assignment redundancies
    admin_role_patterns = [
        "System Manager",
        "Verenigingen Administrator",
        "Verenigingen Manager",
        "Administrator",
        "Verenigingen Chapter Board Member",
    ]

    # Get users with multiple admin roles
    all_users = frappe.get_all(
        "User", filters={"enabled": 1, "user_type": "System User"}, fields=["name", "email"], limit=50
    )

    for user in all_users:
        try:
            user_roles = frappe.get_roles(user.name)
            admin_roles = [
                role for role in user_roles if any(pattern in role for pattern in admin_role_patterns)
            ]

            if len(admin_roles) > 1:
                results["redundancy_issues"].append(
                    {"user": user.email, "roles": admin_roles, "issue": "Multiple admin-level roles"}
                )
        except Exception:
            continue

    # Check for permission conflicts in key DocTypes
    key_doctypes = ["Member", "Volunteer", "Donation", "Chapter", "Membership"]

    for doctype in key_doctypes:
        try:
            permissions = frappe.get_all(
                "DocPerm",
                filters={"parent": doctype},
                fields=["role", "read", "write", "create", "delete", "if_owner"],
                order_by="idx",
            )

            # Group by role to find conflicts
            role_perms = {}
            for perm in permissions:
                if perm.role not in role_perms:
                    role_perms[perm.role] = []
                role_perms[perm.role].append(perm)

            # Find roles with multiple conflicting permission rules
            for role, perms in role_perms.items():
                if len(perms) > 1:
                    # Check for actual conflicts
                    has_conflict = False
                    for i in range(len(perms)):
                        for j in range(i + 1, len(perms)):
                            perm1, perm2 = perms[i], perms[j]
                            if (
                                perm1.read != perm2.read
                                or perm1.write != perm2.write
                                or perm1.if_owner != perm2.if_owner
                            ):
                                has_conflict = True
                                break
                        if has_conflict:
                            break

                    if has_conflict:
                        results["permission_conflicts"].append(
                            {
                                "doctype": doctype,
                                "role": role,
                                "rules_count": len(perms),
                                "issue": "Conflicting permission rules",
                            }
                        )
        except Exception:
            continue

    return results


@frappe.whitelist()
def get_role_usage_report():
    """Get comprehensive role usage analysis"""
    return analyze_current_role_structure()


def identify_role_problems():
    """Identify specific problems with current role setup"""

    problems = []

    # Problem 1: Check for users with both System Manager and custom admin roles
    system_managers = frappe.get_all(
        "Has Role", filters={"role": "System Manager"}, fields=["parent"], pluck="parent"
    )

    for user in system_managers:
        try:
            user_roles = frappe.get_roles(user)
            redundant_roles = []

            if "Verenigingen Administrator" in user_roles:
                redundant_roles.append("Verenigingen Administrator")
            if "Verenigingen Manager" in user_roles:
                redundant_roles.append("Verenigingen Manager")

            if redundant_roles:
                problems.append(
                    {
                        "type": "role_redundancy",
                        "user": user,
                        "issue": f"System Manager has redundant roles: {redundant_roles}",
                        "severity": "medium",
                        "recommendation": "Remove redundant admin roles - System Manager already provides full access",
                    }
                )
        except Exception:
            continue

    # Problem 2: Check for conflicting Member DocType permissions
    member_perms = frappe.get_all(
        "DocPerm", filters={"parent": "Member"}, fields=["role", "read", "write", "if_owner"]
    )

    # Look for roles that have both general access and if_owner access
    role_access = {}
    for perm in member_perms:
        if perm.role not in role_access:
            role_access[perm.role] = {"general": False, "owner_only": False}

        if perm.read and not perm.if_owner:
            role_access[perm.role]["general"] = True
        elif perm.read and perm.if_owner:
            role_access[perm.role]["owner_only"] = True

    for role, access in role_access.items():
        if access["general"] and access["owner_only"]:
            problems.append(
                {
                    "type": "permission_conflict",
                    "doctype": "Member",
                    "role": role,
                    "issue": "Role has both general access and owner-only access rules",
                    "severity": "high",
                    "recommendation": "Consolidate permission rules - remove either general or owner-only access",
                }
            )

    # Problem 3: Check for inactive roles still being assigned
    disabled_roles = frappe.get_all("Role", filters={"disabled": 1}, fields=["name"], pluck="name")

    for role in disabled_roles:
        assignments = frappe.get_all("Has Role", filters={"role": role}, limit=1)
        if assignments:
            problems.append(
                {
                    "type": "disabled_role_assigned",
                    "role": role,
                    "issue": "Disabled role is still assigned to users",
                    "severity": "low",
                    "recommendation": "Remove role assignments for disabled roles",
                }
            )

    return problems


@frappe.whitelist()
def get_role_optimization_recommendations():
    """Get recommendations for optimizing role structure"""

    problems = identify_role_problems()
    analysis = analyze_current_role_structure()

    recommendations = {"high_priority": [], "medium_priority": [], "low_priority": []}

    # Categorize problems by severity
    for problem in problems:
        severity = problem.get("severity", "low")
        if severity == "high":
            recommendations["high_priority"].append(problem)
        elif severity == "medium":
            recommendations["medium_priority"].append(problem)
        else:
            recommendations["low_priority"].append(problem)

    # Add general recommendations
    if len(analysis["redundancy_issues"]) > 0:
        recommendations["medium_priority"].append(
            {
                "type": "general_recommendation",
                "issue": f"{len(analysis['redundancy_issues'])} users have multiple admin roles",
                "recommendation": "Review and consolidate admin role assignments",
            }
        )

    if len(analysis["permission_conflicts"]) > 0:
        recommendations["high_priority"].append(
            {
                "type": "general_recommendation",
                "issue": f"{len(analysis['permission_conflicts'])} DocTypes have permission conflicts",
                "recommendation": "Review and consolidate DocType permissions",
            }
        )

    return recommendations
