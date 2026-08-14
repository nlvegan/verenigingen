"""
Security Configuration Onboarding Step

Validation helper for the "Verenigingen-Configure-Security" onboarding step.

This file sits in the *fixture* directory for Onboarding Step documents, not in a
doctype directory, so nothing here is ever bound as a controller: "Onboarding
Step" belongs to Frappe and is not listed in override_doctype_class. Only
module-level whitelisted functions work from here.
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def validate_security_configuration():
    """Validate that security configurations have been applied"""
    issues_found = []

    # Check guest permissions for Member doctype
    guest_member_perms = frappe.get_all(
        "DocPerm", filters={"parent": "Member", "role": "Guest", "read": 1}, fields=["name"]
    )

    if guest_member_perms:
        issues_found.append(
            {
                "issue": "Guest users still have read access to Member records",
                "action": "Remove Guest role permissions for Member DocType",
            }
        )

    # Change tracking is per-doctype. There is no global toggle to check: System
    # Settings has carried no version-tracking field since v16, so the check that
    # used to live here could only ever raise or fire spuriously.
    critical_doctypes = ["Member", "Membership", "SEPA Mandate", "Volunteer"]
    for doctype in critical_doctypes:
        try:
            meta = frappe.get_meta(doctype)
            if not meta.track_changes:
                issues_found.append(
                    {
                        "issue": f"{doctype} DocType does not have change tracking enabled",
                        "action": f"Enable 'Track Changes' for {doctype} DocType in Customize DocType",
                    }
                )
        except Exception:
            # DocType might not exist
            pass

    return {
        "configuration_complete": len(issues_found) == 0,
        "issues_remaining": issues_found,
        "next_steps": (
            "Address remaining issues and re-run validation"
            if issues_found
            else "Security configuration validated successfully"
        ),
    }
