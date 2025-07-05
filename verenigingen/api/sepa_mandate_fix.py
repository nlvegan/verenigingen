import frappe
from frappe import _
from frappe.utils import nowdate, today

from verenigingen.verenigingen.doctype.member.member import derive_bic_from_iban


@frappe.whitelist()
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
    for mandate_info in result.get("results", {}).get("mandates", []):
        if mandate_info.get("member") == member_name:
            return {
                "success": True,
                "message": f"SEPA mandate created successfully: {mandate_info.get('mandate_id')}",
                "mandate_id": mandate_info.get("mandate_id"),
            }

    # Check errors
    for error_info in result.get("results", {}).get("errors", []):
        if error_info.get("member") == member_name:
            return {"success": False, "message": f"Error creating mandate: {error_info.get('error')}"}

    return {"success": False, "message": "Member was not processed - please check the criteria"}
