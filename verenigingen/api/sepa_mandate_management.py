import frappe
from frappe import _
from frappe.utils import nowdate, today

# Import security framework
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.verenigingen.doctype.member.member import derive_bic_from_iban


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_missing_sepa_mandates(dry_run=True):
    """
    Create SEPA mandates for members with SEPA Direct Debit payment method but no active mandate.

    Args:
        dry_run: If True, only show what would be created without actually creating
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
            AND NOT EXISTS (
                SELECT 1
                FROM `tabSEPA Mandate` sm
                WHERE sm.member = m.name
                AND sm.status = 'Active'
                AND sm.is_active = 1
            )
    """,
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

                mandate.insert(ignore_permissions=True)
                mandate.submit()

                # Link mandate to member
                member_doc = frappe.get_doc("Member", member.name)
                member_doc.append(
                    "sepa_mandates",
                    {
                        "sepa_mandate": mandate.name,
                        "mandate_reference": mandate_id,
                        "is_current": 1,
                        "status": "Active",
                        "valid_from": today(),
                    },
                )
                member_doc.save(ignore_permissions=True)

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
def fix_specific_member_sepa_mandate(member_name):
    """
    Create SEPA mandate for a specific member
    """
    if not frappe.has_permission("SEPA Mandate", "create"):
        frappe.throw(_("You don't have permission to create SEPA mandates"))

    member = frappe.get_doc("Member", member_name)

    # Validate member has required information
    if not member.iban:
        frappe.throw(_("Member does not have an IBAN"))

    if member.payment_method != "SEPA Direct Debit":
        frappe.throw(_("Member's payment method is not SEPA Direct Debit"))

    # Check if active mandate already exists
    existing_active = frappe.db.exists(
        "SEPA Mandate", {"member": member_name, "status": "Active", "is_active": 1}
    )

    if existing_active:
        return {"success": False, "message": _("Member already has an active SEPA mandate")}

    # Create the mandate
    result = create_missing_sepa_mandates(dry_run=False)

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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def periodic_sepa_mandate_child_table_sync():
    """
    Periodic cleanup to sync SEPA mandate child tables for all members.
    This catches cases where hooks didn't trigger properly.
    """
    try:
        # Get all members who have SEPA mandates but potentially incomplete child tables
        members_with_mandates = frappe.db.sql(
            """
            SELECT DISTINCT m.name, m.full_name,
                   COUNT(sm.name) as mandate_count,
                   COUNT(sml.name) as child_table_count
            FROM `tabMember` m
            LEFT JOIN `tabSEPA Mandate` sm ON sm.member = m.name
            LEFT JOIN `tabMember SEPA Mandate Link` sml ON sml.parent = m.name
            WHERE sm.name IS NOT NULL
            GROUP BY m.name, m.full_name
            HAVING mandate_count != child_table_count
               OR mandate_count = 0
               OR child_table_count = 0
        """,
            as_dict=True,
        )

        results = {
            "total_members_checked": 0,
            "members_needing_sync": len(members_with_mandates),
            "successfully_synced": 0,
            "sync_errors": [],
            "details": [],
        }

        # Also check all members with SEPA mandates for data consistency
        all_members_with_mandates = frappe.db.sql(
            """
            SELECT DISTINCT member as name
            FROM `tabSEPA Mandate`
            WHERE member IS NOT NULL AND member != ''
        """,
            as_dict=True,
        )

        results["total_members_checked"] = len(all_members_with_mandates)

        for member_data in all_members_with_mandates:
            try:
                member_name = member_data.name

                # Get all mandates for this member
                mandates = frappe.get_all(
                    "SEPA Mandate",
                    filters={"member": member_name},
                    fields=["name", "mandate_id", "status", "is_active", "sign_date", "expiry_date"],
                )

                if not mandates:
                    continue

                # Get member document
                member = frappe.get_doc("Member", member_name)

                # Check if child table needs sync
                needs_sync = False
                existing_links = {link.sepa_mandate: link for link in member.sepa_mandates}

                # Check for missing or outdated links
                for mandate in mandates:
                    if mandate.name not in existing_links:
                        needs_sync = True
                        break

                    # Check if existing link data is outdated
                    link = existing_links[mandate.name]
                    if (
                        link.mandate_reference != mandate.mandate_id
                        or link.status != mandate.status
                        or link.valid_from != mandate.sign_date
                        or link.valid_until != mandate.expiry_date
                    ):
                        needs_sync = True
                        break

                # Check for orphaned links (mandate deleted but link remains)
                mandate_names = {m.name for m in mandates}
                for link in member.sepa_mandates:
                    if link.sepa_mandate not in mandate_names:
                        needs_sync = True
                        break

                if needs_sync:
                    # Rebuild child table completely
                    member.sepa_mandates = []

                    for mandate in mandates:
                        member.append(
                            "sepa_mandates",
                            {
                                "sepa_mandate": mandate.name,
                                "mandate_reference": mandate.mandate_id,
                                "status": mandate.status,
                                "is_current": 1 if (mandate.status == "Active" and mandate.is_active) else 0,
                                "valid_from": mandate.sign_date,
                                "valid_until": mandate.expiry_date,
                            },
                        )

                    member.save(ignore_permissions=True)
                    results["successfully_synced"] += 1

                    results["details"].append(
                        {
                            "member": member_name,
                            "member_name": member.full_name,
                            "mandates_count": len(mandates),
                            "action": "synced",
                        }
                    )

            except Exception as e:
                results["sync_errors"].append({"member": member_name, "error": str(e)})
                frappe.log_error(
                    f"Error syncing SEPA mandates for {member_name}: {str(e)}", "SEPA Periodic Sync"
                )

        # Summary
        results[
            "message"
        ] = f"Checked {results['total_members_checked']} members, synced {results['successfully_synced']}, {len(results['sync_errors'])} errors"

        return {"success": True, "results": results}

    except Exception as e:
        frappe.log_error(f"Error in periodic SEPA mandate sync: {str(e)}", "SEPA Periodic Sync Error")
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
