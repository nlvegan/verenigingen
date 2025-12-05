"""
SEPA Mandate Diagnostics Page

Interactive diagnostic and repair tool for SEPA mandate synchronization issues.
Replaces blind nightly sync tasks with targeted problem detection and resolution.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, standard_api


@frappe.whitelist()
@standard_api(operation_type=OperationType.READ)
def get_mandate_issues():
    """
    Get all SEPA mandate synchronization issues categorized by type.

    Returns:
        dict: Issue categories with counts and affected members
    """
    issues = {
        "sepa_selected_no_mandate": {
            "title": _("SEPA Payment Method Without Mandate"),
            "description": _(
                "Members have SEPA Direct Debit selected but lack active mandate or required banking data (IBAN, account holder name)"
            ),
            "severity": "critical",
            "count": 0,
            "members": [],
        },
        "missing_child_table_entries": {
            "title": _("Missing Child Table Entries"),
            "description": _("Members have SEPA mandates but no child table entries"),
            "severity": "high",
            "count": 0,
            "members": [],
        },
        "orphaned_child_table_entries": {
            "title": _("Orphaned Child Table Entries"),
            "description": _("Child table entries point to deleted mandates"),
            "severity": "medium",
            "count": 0,
            "members": [],
        },
        "outdated_child_table_data": {
            "title": _("Outdated Child Table Data"),
            "description": _("Child table data doesn't match current mandate status"),
            "severity": "low",
            "count": 0,
            "members": [],
        },
        "multiple_current_mandates": {
            "title": _("Multiple Current Mandates"),
            "description": _("Members marked as having multiple 'current' mandates"),
            "severity": "high",
            "count": 0,
            "members": [],
        },
        "mandate_member_data_mismatch": {
            "title": _("Mandate/Member Data Mismatch"),
            "description": _(
                "Active SEPA mandates where IBAN or account holder name differs from member record"
            ),
            "severity": "high",
            "count": 0,
            "members": [],
        },
    }

    # CRITICAL: Members with SEPA payment method but no active mandate
    sepa_no_mandate = frappe.db.sql(
        """
        SELECT
            m.name as member_id,
            m.full_name,
            m.payment_method,
            m.iban,
            m.bank_account_name,
            COUNT(sm.name) as total_mandates,
            COUNT(CASE WHEN sm.status = 'Active' AND sm.is_active = 1 THEN 1 END) as active_mandates,
            CASE
                WHEN m.iban IS NULL OR m.iban = '' THEN 'missing_iban'
                WHEN m.bank_account_name IS NULL OR m.bank_account_name = '' THEN 'missing_account_name'
                ELSE 'has_banking_data'
            END as banking_status
        FROM `tabMember` m
        LEFT JOIN `tabSEPA Mandate` sm ON sm.member = m.name
        WHERE m.payment_method = 'SEPA Direct Debit'
        GROUP BY m.name, m.full_name, m.payment_method, m.iban, m.bank_account_name
        HAVING active_mandates = 0
        """,
        as_dict=True,
    )
    issues["sepa_selected_no_mandate"]["count"] = len(sepa_no_mandate)
    issues["sepa_selected_no_mandate"]["members"] = sepa_no_mandate

    # Missing child table entries
    missing_entries = frappe.db.sql(
        """
        SELECT
            m.name as member_id,
            m.full_name,
            COUNT(sm.name) as mandate_count,
            GROUP_CONCAT(sm.mandate_id SEPARATOR ', ') as mandate_ids
        FROM `tabMember` m
        INNER JOIN `tabSEPA Mandate` sm ON sm.member = m.name
        LEFT JOIN `tabMember SEPA Mandate Link` sml ON sml.parent = m.name AND sml.sepa_mandate = sm.name
        WHERE sml.name IS NULL
        GROUP BY m.name, m.full_name
        """,
        as_dict=True,
    )
    issues["missing_child_table_entries"]["count"] = len(missing_entries)
    issues["missing_child_table_entries"]["members"] = missing_entries

    # Orphaned child table entries
    orphaned_entries = frappe.db.sql(
        """
        SELECT
            sml.parent as member_id,
            m.full_name,
            sml.sepa_mandate as mandate_name,
            sml.mandate_reference
        FROM `tabMember SEPA Mandate Link` sml
        INNER JOIN `tabMember` m ON m.name = sml.parent
        LEFT JOIN `tabSEPA Mandate` sm ON sm.name = sml.sepa_mandate
        WHERE sm.name IS NULL
        GROUP BY sml.parent, m.full_name, sml.sepa_mandate, sml.mandate_reference
        """,
        as_dict=True,
    )
    issues["orphaned_child_table_entries"]["count"] = len(orphaned_entries)
    issues["orphaned_child_table_entries"]["members"] = orphaned_entries

    # Outdated child table data
    outdated_data = frappe.db.sql(
        """
        SELECT
            m.name as member_id,
            m.full_name,
            sm.mandate_id,
            sm.status as current_status,
            sml.status as child_table_status,
            sm.sign_date as current_valid_from,
            sml.valid_from as child_table_valid_from
        FROM `tabMember` m
        INNER JOIN `tabSEPA Mandate` sm ON sm.member = m.name
        INNER JOIN `tabMember SEPA Mandate Link` sml ON sml.parent = m.name AND sml.sepa_mandate = sm.name
        WHERE sml.status != sm.status
           OR sml.mandate_reference != sm.mandate_id
           OR sml.valid_from != sm.sign_date
           OR sml.valid_until != sm.expiry_date
        """,
        as_dict=True,
    )
    issues["outdated_child_table_data"]["count"] = len(outdated_data)
    issues["outdated_child_table_data"]["members"] = outdated_data

    # Multiple current mandates
    multiple_current = frappe.db.sql(
        """
        SELECT
            m.name as member_id,
            m.full_name,
            COUNT(sml.name) as current_count,
            GROUP_CONCAT(sml.mandate_reference SEPARATOR ', ') as mandate_ids
        FROM `tabMember` m
        INNER JOIN `tabMember SEPA Mandate Link` sml ON sml.parent = m.name
        WHERE sml.is_current = 1
        GROUP BY m.name, m.full_name
        HAVING current_count > 1
        """,
        as_dict=True,
    )
    issues["multiple_current_mandates"]["count"] = len(multiple_current)
    issues["multiple_current_mandates"]["members"] = multiple_current

    # Mandate/Member data mismatch - IBAN or account holder name differs
    data_mismatch = frappe.db.sql(
        """
        SELECT
            m.name as member_id,
            m.full_name,
            m.iban as member_iban,
            m.bank_account_name as member_account_holder,
            sm.name as mandate_name,
            sm.mandate_id,
            sm.iban as mandate_iban,
            sm.account_holder_name as mandate_account_holder,
            CASE
                WHEN REPLACE(REPLACE(m.iban, ' ', ''), '-', '') != REPLACE(REPLACE(sm.iban, ' ', ''), '-', '')
                    AND (m.bank_account_name IS NULL OR m.bank_account_name = '' OR m.bank_account_name = sm.account_holder_name)
                    THEN 'iban_mismatch'
                WHEN m.bank_account_name IS NOT NULL AND m.bank_account_name != '' AND m.bank_account_name != sm.account_holder_name
                    AND REPLACE(REPLACE(m.iban, ' ', ''), '-', '') = REPLACE(REPLACE(sm.iban, ' ', ''), '-', '')
                    THEN 'holder_mismatch'
                ELSE 'both_mismatch'
            END as mismatch_type
        FROM `tabMember` m
        INNER JOIN `tabSEPA Mandate` sm ON sm.member = m.name
        WHERE sm.status = 'Active'
          AND sm.is_active = 1
          AND (
              -- IBAN mismatch (normalized comparison without spaces/dashes)
              REPLACE(REPLACE(m.iban, ' ', ''), '-', '') != REPLACE(REPLACE(sm.iban, ' ', ''), '-', '')
              -- OR account holder name mismatch (when member has one set)
              OR (
                  m.bank_account_name IS NOT NULL
                  AND m.bank_account_name != ''
                  AND m.bank_account_name != sm.account_holder_name
              )
          )
        """,
        as_dict=True,
    )
    issues["mandate_member_data_mismatch"]["count"] = len(data_mismatch)
    issues["mandate_member_data_mismatch"]["members"] = data_mismatch

    # Calculate totals
    total_issues = sum(issue["count"] for issue in issues.values())
    unique_members = len(
        set(member.get("member_id") for issue in issues.values() for member in issue["members"])
    )

    return {
        "issues": issues,
        "summary": {
            "total_issues": total_issues,
            "unique_members": unique_members,
            "last_checked": frappe.utils.now(),
        },
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def fix_member_mandate_issues(member_id, issue_types=None):
    """
    Fix SEPA mandate issues for a specific member.

    Args:
        member_id: Member document name
        issue_types: List of issue types to fix (None = all)

    Returns:
        dict: Success status and details
    """
    try:
        member = frappe.get_doc("Member", member_id)

        # Use the existing refresh method
        result = member.refresh_sepa_mandates_table()

        return {"success": True, "member": member_id, "member_name": member.full_name, "details": result}

    except Exception as e:
        frappe.log_error(f"Failed to fix mandate issues for {member_id}: {str(e)}", "SEPA Mandate Fix Error")
        return {"success": False, "member": member_id, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def bulk_fix_mandate_issues(issue_type=None, member_ids=None):
    """
    Fix SEPA mandate issues for multiple members.

    Args:
        issue_type: Specific issue type to fix (optional)
        member_ids: List of member IDs (optional, defaults to all with issues)

    Returns:
        dict: Batch operation results
    """
    results = {"total": 0, "success": 0, "failed": 0, "errors": []}

    # If no member IDs provided, get all members with issues
    if not member_ids:
        issues = get_mandate_issues()

        if issue_type and issue_type in issues["issues"]:
            # Fix specific issue type
            member_ids = [m["member_id"] for m in issues["issues"][issue_type]["members"]]
        else:
            # Fix all issues
            all_members = set()
            for issue_data in issues["issues"].values():
                all_members.update(m["member_id"] for m in issue_data["members"])
            member_ids = list(all_members)

    results["total"] = len(member_ids)

    # Process each member
    for member_id in member_ids:
        fix_result = fix_member_mandate_issues(member_id)

        if fix_result["success"]:
            results["success"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({"member": member_id, "error": fix_result.get("error", "Unknown error")})

    # Log summary if there were errors
    if results["errors"]:
        error_summary = f"Failed to fix {results['failed']} of {results['total']} members:\n\n"
        for err in results["errors"][:20]:
            error_summary += f"- {err['member']}: {err['error']}\n"
        if len(results["errors"]) > 20:
            error_summary += f"\n... and {len(results['errors']) - 20} more errors"

        frappe.log_error(error_summary, "SEPA Mandate Bulk Fix Errors")

    return results
