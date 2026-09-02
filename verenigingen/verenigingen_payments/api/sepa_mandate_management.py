import frappe
from frappe import _
from frappe.utils import nowdate, today

from verenigingen.utils.secure_operations import secure_document_operation

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.validation.iban_validator import derive_bic_from_iban
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_missing_sepa_mandates(dry_run=True, member_name: str | None = None):
    """
    Create SEPA mandates for members with SEPA Direct Debit payment method but no active mandate.

    Args:
        dry_run: If True, only show what would be created without actually creating
        member_name: Restrict the sweep to one member. `fix_specific_member_sepa_mandate`
            passes it: without it, "fix this member" ran the whole-site sweep and
            created mandates for every other eligible member as a side effect, then
            filtered the report down to the one that was asked about (#605).
    """
    # Check permissions
    if not frappe.has_permission("SEPA Mandate", "create"):
        frappe.throw(_("You don't have permission to create SEPA mandates"))

    # Find members with SEPA Direct Debit but no mandates
    members_needing_mandates = frappe.db.sql(
        """
        SELECT
            m.name,
            m.full_name,
            m.iban,
            m.bic,
            m.bank_account_name,
            m.member_id
        FROM `tabMember` m
        WHERE
            m.payment_method = 'SEPA Direct Debit'
            AND m.iban IS NOT NULL
            AND m.iban != ''
            AND m.docstatus != 2
            AND (%(member)s IS NULL OR m.name = %(member)s)
            -- The mandate this sweep creates is `used_for_memberships = 1`, so that
            -- is the mandate whose absence it must look for (#605). Unscoped, a
            -- member whose only Active mandate is a DONATION mandate counted as
            -- covered and was skipped -- leaving them with no membership mandate,
            -- which every collection path has resolved by purpose since #597.
            AND NOT EXISTS (
                SELECT 1
                FROM `tabSEPA Mandate` sm
                WHERE sm.member = m.name
                AND sm.status = 'Active'
                AND sm.is_active = 1
                AND sm.used_for_memberships = 1
            )
    """,
        {"member": member_name},
        as_dict=True,
    )

    results = {"found": len(members_needing_mandates), "created": 0, "errors": [], "mandates": []}

    for member in members_needing_mandates:
        try:
            if dry_run:
                results["mandates"].append(
                    {
                        "member": member.name,
                        "member_name": member.full_name,
                        "iban": member.iban,
                        "action": "Would create mandate",
                    }
                )
            else:
                # Generate mandate reference
                member_id = member.member_id or member.name.replace("Assoc-Member-", "").replace("-", "")
                date_str = nowdate().replace("-", "")

                # Count existing mandates for this member today
                existing_today = frappe.db.count(
                    "SEPA Mandate", {"mandate_id": ["like", f"M-{member_id}-{date_str}-%"]}
                )

                sequence = str(existing_today + 1).zfill(3)
                mandate_id = f"M-{member_id}-{date_str}-{sequence}"

                # Derive BIC if not present
                bic = member.bic
                if not bic and member.iban:
                    bic_result = derive_bic_from_iban(member.iban)
                    if bic_result and bic_result.get("bic"):
                        bic = bic_result["bic"]

                # Create mandate
                mandate = frappe.get_doc(
                    {
                        "doctype": "SEPA Mandate",
                        "mandate_id": mandate_id,
                        "member": member.name,
                        "member_name": member.full_name,
                        "iban": member.iban,
                        "bic": bic or "",
                        "account_holder_name": member.bank_account_name or member.full_name,
                        "mandate_type": "RCUR",  # Recurring
                        "sign_date": today(),
                        "used_for_memberships": 1,
                        "used_for_donations": 0,
                        "status": "Active",
                        "is_active": 1,
                        "notes": "Auto-created by system - member had SEPA Direct Debit payment method but no mandate",
                    }
                )

                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                mandate_result = secure_document_operation(
                    operation="insert",
                    doc=mandate,
                    justification=f"Auto-create SEPA mandate {mandate_id} for member {member.name} with SEPA Direct Debit payment method",
                    required_permissions=["SEPA Mandate:create"],
                )
                if not mandate_result.success:
                    raise Exception(
                        f"Failed to create SEPA mandate for {member.name}: {'; '.join(mandate_result.errors)}"
                    )

                mandate.submit()

                # Link mandate to member
                member_doc = frappe.get_doc("Member", member.name)
                member_doc.append(
                    "sepa_mandates",
                    {
                        # sepa_mandate is a Dynamic Link whose target doctype is
                        # read from sepa_mandate_doctype. That field carries a
                        # DocField-level default ("SEPA Mandate") that
                        # Document._set_defaults() copies onto a new row before
                        # _validate_links() runs on the .save() path this append
                        # feeds -- so leaving it unset happens not to throw here.
                        # But that self-heal is skipped under
                        # frappe.flags.in_import, and does not run at all on any
                        # path that bypasses _save()/_insert() (e.g.
                        # update_child_table()). Set it explicitly so this row
                        # does not depend on which persistence path is used
                        # (#667; this comment previously overstated the
                        # mechanism -- see that issue for the measured behavior).
                        "sepa_mandate_doctype": "SEPA Mandate",
                        "sepa_mandate": mandate.name,
                        "mandate_reference": mandate_id,
                        "is_current": 1,
                        "status": "Active",
                        "valid_from": today(),
                    },
                )
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                member_result = secure_document_operation(
                    operation="save",
                    doc=member_doc,
                    justification=f"Link SEPA mandate {mandate_id} to member {member.name} child table after mandate creation",
                    required_permissions=["Member:write"],
                )
                if not member_result.success:
                    raise Exception(
                        f"Failed to link mandate to member {member.name}: {'; '.join(member_result.errors)}"
                    )

                results["created"] += 1
                results["mandates"].append(
                    {
                        "member": member.name,
                        "member_name": member.full_name,
                        "mandate_id": mandate_id,
                        "action": "Created successfully",
                    }
                )

        except Exception as e:
            results["errors"].append({"member": member.name, "error": str(e)})

    # Create summary message
    if dry_run:
        message = f"DRY RUN: Found {results['found']} members needing SEPA mandates"
    else:
        message = f"Created {results['created']} SEPA mandates out of {results['found']} members needing them"

    if results["errors"]:
        message += f"\n{len(results['errors'])} errors occurred"

    return {"success": True, "message": message, "results": results}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def fix_specific_member_sepa_mandate(member_name: str):
    """
    Create SEPA mandate for a specific member
    """
    try:
        # Input validation
        if not member_name:
            frappe.throw(_("Member name is required"))

        if not isinstance(member_name, str):
            frappe.throw(_("Member name must be a string"))

        if not frappe.has_permission("SEPA Mandate", "create"):
            frappe.throw(_("You don't have permission to create SEPA mandates"))

        # Validate member exists
        if not DocumentExistenceValidator.check_document_exists("Member", member_name):
            frappe.throw(_("Member {0} does not exist").format(member_name))

        member = frappe.get_doc("Member", member_name)

        # Validate member has required information
        if not member.iban:
            frappe.throw(_("Member does not have an IBAN"))

        if member.payment_method != "SEPA Direct Debit":
            frappe.throw(_("Member's payment method is not SEPA Direct Debit"))

        # Check if an active MEMBERSHIP mandate already exists (#605). A donation
        # mandate is not one, and refusing on it left the member without the mandate
        # this endpoint exists to create.
        existing_active = frappe.db.exists(
            "SEPA Mandate",
            {"member": member_name, "status": "Active", "is_active": 1, "used_for_memberships": 1},
        )

        if existing_active:
            return {"success": False, "message": _("Member already has an active SEPA mandate")}

        # Create the mandate -- for THIS member only; see create_missing_sepa_mandates
        result = create_missing_sepa_mandates(dry_run=False, member_name=member_name)

        # Check if this specific member was processed
        # Safe extraction of results data
        results_data = result.get("results")
        if not results_data or not isinstance(results_data, dict):
            return {"success": False, "message": "Invalid results format from mandate creation"}

        mandates_list = results_data.get("mandates", [])
        if not isinstance(mandates_list, list):
            mandates_list = []

        for mandate_info in mandates_list:
            if mandate_info.get("member") == member_name:
                return {
                    "success": True,
                    "message": f"SEPA mandate created successfully: {mandate_info.get('mandate_id')}",
                    "mandate_id": mandate_info.get("mandate_id"),
                }

        # Check errors
        errors_list = results_data.get("errors", [])
        if not isinstance(errors_list, list):
            errors_list = []

        for error_info in errors_list:
            if error_info.get("member") == member_name:
                return {"success": False, "message": f"Error creating mandate: {error_info.get('error')}"}

        return {"success": False, "message": "Member was not processed - please check the criteria"}

    except Exception as e:
        frappe.log_error(f"Error creating SEPA mandate for member {member_name}: {str(e)}")
        # Don't expose internal errors to users
        if hasattr(e, "message"):
            frappe.throw(e.message)
        else:
            frappe.throw(_("Failed to create SEPA mandate. Please check the system logs."))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def periodic_sepa_mandate_child_table_sync():
    """
    Periodic monitoring check for SEPA mandate synchronization issues.

    Does NOT auto-fix issues - instead alerts administrators when problems are detected.
    Admins should use the SEPA Mandate Diagnostics page to review and fix issues selectively.
    """
    try:
        from verenigingen.verenigingen_payments.page.sepa_mandate_diagnostics.sepa_mandate_diagnostics import (
            get_mandate_issues,
        )

        # Get current issues without fixing
        diagnostic_data = get_mandate_issues()
        issues = diagnostic_data["issues"]
        summary = diagnostic_data["summary"]

        # Check if there are any issues that need attention
        high_severity_count = sum(issue["count"] for issue in issues.values() if issue["severity"] == "high")

        results = {
            "total_issues": summary["total_issues"],
            "unique_members": summary["unique_members"],
            "high_severity_issues": high_severity_count,
            "issue_breakdown": {
                key: {"count": issue["count"], "severity": issue["severity"]} for key, issue in issues.items()
            },
        }

        # Alert if there are high-severity issues
        if high_severity_count > 0:
            alert_message = f"Found {high_severity_count} high-severity SEPA mandate sync issues affecting {summary['unique_members']} member(s).\n\n"
            alert_message += "Issue breakdown:\n"
            for key, issue in issues.items():
                if issue["count"] > 0:
                    alert_message += f"- {issue['title']}: {issue['count']} ({issue['severity']} severity)\n"

            alert_message += "\nPlease review and fix these issues at: sepa_mandate_diagnostics"

            # Create notification for administrators
            frappe.log_error(alert_message, "SEPA Mandate Sync - Issues Detected")

            # Send realtime notification to System Managers
            frappe.publish_realtime(
                event="sepa_mandate_issues_detected",
                message={
                    "title": "SEPA Mandate Sync Issues Detected",
                    "message": f"{high_severity_count} high-severity issues found. Check SEPA Mandate Diagnostics.",
                    "indicator": "orange",
                    "issue_count": high_severity_count,
                },
                user="Administrator",
            )

            results["alert_sent"] = True
            results[
                "message"
            ] = f"Detected {high_severity_count} high-severity issues. Alert sent to administrators."
        else:
            results["alert_sent"] = False
            results[
                "message"
            ] = f"All clear. Checked {summary['total_issues']} total issues, none require immediate attention."

        return {"success": True, "results": results}

    except Exception as e:
        frappe.log_error(
            f"Error in periodic SEPA mandate monitoring: {str(e)}", "SEPA Periodic Monitoring Error"
        )
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def detect_sepa_mandate_inconsistencies():
    """
    Detect various inconsistencies in SEPA mandate data without fixing them.
    Useful for monitoring and alerting.
    """
    try:
        issues = {
            "missing_child_table_entries": [],
            "orphaned_child_table_entries": [],
            "outdated_child_table_data": [],
            "multiple_current_mandates": [],
            "active_mandates_not_current": [],
        }

        # Find members with mandates but no child table entries
        missing_entries = frappe.db.sql(
            """
            SELECT m.name, m.full_name, COUNT(sm.name) as mandate_count
            FROM `tabMember` m
            INNER JOIN `tabSEPA Mandate` sm ON sm.member = m.name
            LEFT JOIN `tabMember SEPA Mandate Link` sml ON sml.parent = m.name AND sml.sepa_mandate = sm.name
            WHERE sml.name IS NULL
            GROUP BY m.name, m.full_name
        """,
            as_dict=True,
        )

        issues["missing_child_table_entries"] = missing_entries

        # Find child table entries without corresponding mandates
        orphaned_entries = frappe.db.sql(
            """
            SELECT sml.parent as member, sml.sepa_mandate, sml.mandate_reference
            FROM `tabMember SEPA Mandate Link` sml
            LEFT JOIN `tabSEPA Mandate` sm ON sm.name = sml.sepa_mandate
            WHERE sm.name IS NULL
        """,
            as_dict=True,
        )

        issues["orphaned_child_table_entries"] = orphaned_entries

        # Find members with multiple current mandates
        multiple_current = frappe.db.sql(
            """
            SELECT parent as member, COUNT(*) as current_count
            FROM `tabMember SEPA Mandate Link`
            WHERE is_current = 1
            GROUP BY parent
            HAVING COUNT(*) > 1
        """,
            as_dict=True,
        )

        issues["multiple_current_mandates"] = multiple_current

        return {
            "success": True,
            "issues": issues,
            "total_issues": sum(len(issue_list) for issue_list in issues.values()),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
