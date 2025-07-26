"""
ANBI Operations API for Donation Management
Handles ANBI compliance operations including tax identifier management and reporting
"""

import json
from datetime import datetime

import frappe
from frappe import _


def has_donor_permlevel_access(permission_type="read"):
    """Check if user has permlevel 1 access to Donor doctype"""
    # Check if user has basic permission first
    if not frappe.has_permission("Donor", ptype=permission_type):
        return False

    # Check if user has permlevel 1 access by checking user permissions
    user_roles = frappe.get_roles(frappe.session.user)

    # System Manager and Administrator roles typically have all permissions
    if "System Manager" in user_roles or "Administrator" in user_roles:
        return True

    # Check if user has specific roles that should have permlevel access
    privileged_roles = ["Verenigingen Administrator", "Donor Administrator", "Finance Manager"]
    return any(role in user_roles for role in privileged_roles)


@frappe.whitelist()
def update_donor_tax_identifiers(donor, bsn=None, rsin=None, verification_method=None):
    """
    Update donor tax identifiers with proper security checks

    Args:
        donor: Donor document name
        bsn: BSN (Citizen Service Number) for individuals
        rsin: RSIN (Organization Tax Number) for organizations
        verification_method: Method used to verify the identity

    Returns:
        dict: Success status and message
    """
    # Check permissions
    if not has_donor_permlevel_access("write"):
        frappe.throw(_("Insufficient permissions to update tax identifiers"))

    try:
        donor_doc = frappe.get_doc("Donor", donor)

        # Update fields if provided
        if bsn is not None:
            donor_doc.bsn_citizen_service_number = bsn

        if rsin is not None:
            donor_doc.rsin_organization_tax_number = rsin

        if verification_method:
            donor_doc.identification_verified = 1
            donor_doc.identification_verification_date = frappe.utils.today()
            donor_doc.identification_verification_method = verification_method

        # Save with validation
        donor_doc.save(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "message": _("Tax identifiers updated successfully"),
            "donor": donor_doc.name,
        }

    except Exception as e:
        frappe.log_error(f"Failed to update tax identifiers: {str(e)}", "ANBI Tax ID Update Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_donor_anbi_data(donor):
    """
    Get ANBI-related data for a donor (with decryption for authorized users)

    Args:
        donor: Donor document name

    Returns:
        dict: Donor ANBI data (masked for display)
    """
    # Check permissions
    if not has_donor_permlevel_access("read"):
        frappe.throw(_("Insufficient permissions to view ANBI data"))

    try:
        donor_doc = frappe.get_doc("Donor", donor)

        # Get decrypted values (will be masked by the document class)
        return {
            "success": True,
            "donor_name": donor_doc.donor_name,
            "donor_type": donor_doc.donor_type,
            "bsn": donor_doc.bsn_citizen_service_number,  # Will be masked
            "rsin": donor_doc.rsin_organization_tax_number,  # Will be masked
            "identification_verified": donor_doc.identification_verified,
            "verification_date": donor_doc.identification_verification_date,
            "verification_method": donor_doc.identification_verification_method,
            "anbi_consent": donor_doc.anbi_consent,
            "anbi_consent_date": donor_doc.anbi_consent_date,
        }

    except Exception as e:
        frappe.log_error(f"Failed to get ANBI data: {str(e)}", "ANBI Data Retrieval Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def generate_anbi_report(from_date, to_date, include_bsn=False):
    """
    Generate ANBI report for Belastingdienst reporting

    Args:
        from_date: Start date for report
        to_date: End date for report
        include_bsn: Whether to include decrypted BSN/RSIN (requires special permission)

    Returns:
        dict: Report data
    """
    # Check permissions
    if not frappe.has_permission("Donation", "read"):
        frappe.throw(_("Insufficient permissions to generate ANBI report"))

    # Check special permission for BSN/RSIN export
    if include_bsn and not has_donor_permlevel_access("read"):
        frappe.throw(_("Insufficient permissions to export BSN/RSIN data"))

    try:
        # Get donations marked for ANBI reporting
        donations = frappe.get_all(
            "Donation",
            filters={
                "belastingdienst_reportable": 1,
                "donation_date": ["between", [from_date, to_date]],
                "docstatus": 1,
            },
            fields=[
                "name",
                "donor",
                "donation_date",
                "amount",
                "anbi_agreement_number",
                "anbi_agreement_date",
                "donation_type",
                "donation_purpose_type",
            ],
        )

        report_data = []
        total_amount = 0

        for donation in donations:
            donor_doc = frappe.get_doc("Donor", donation.donor)

            # Basic donor info
            donor_data = {
                "donation_id": donation.name,
                "date": donation.date,
                "amount": donation.amount,
                "donor_name": donor_doc.donor_name,
                "donor_type": donor_doc.donor_type,
                "anbi_agreement_number": donation.anbi_agreement_number,
                "anbi_agreement_date": donation.anbi_agreement_date,
                "donation_type": donation.donation_type,
                "purpose": donation.donation_purpose_type,
            }

            # Include tax identifiers if requested and permitted
            if include_bsn:
                if donor_doc.donor_type == "Individual" and donor_doc.bsn_citizen_service_number:
                    donor_data["bsn"] = donor_doc.get_decrypted_bsn()
                elif donor_doc.donor_type == "Organization" and donor_doc.rsin_organization_tax_number:
                    donor_data["rsin"] = donor_doc.get_decrypted_rsin()

            report_data.append(donor_data)
            total_amount += donation.amount

        # Log the report generation for audit trail
        frappe.log_error(
            f"ANBI report generated by {frappe.session.user} for period {from_date} to {to_date}",
            "ANBI Report Generation",
        )

        return {
            "success": True,
            "report_date": frappe.utils.now(),
            "period": {"from": from_date, "to": to_date},
            "summary": {
                "total_donations": len(donations),
                "total_amount": total_amount,
                "includes_tax_ids": include_bsn,
            },
            "donations": report_data,
        }

    except Exception as e:
        frappe.log_error(f"Failed to generate ANBI report: {str(e)}", "ANBI Report Generation Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def update_anbi_consent(donor, consent, reason=None):
    """
    Update ANBI consent for a donor

    Args:
        donor: Donor document name
        consent: Boolean indicating consent status
        reason: Optional reason for consent change

    Returns:
        dict: Success status and message
    """
    try:
        donor_doc = frappe.get_doc("Donor", donor)

        # Update consent
        from verenigingen.utils.boolean_utils import cbool

        donor_doc.anbi_consent = cbool(consent)

        if consent:
            donor_doc.anbi_consent_date = frappe.utils.now()
        else:
            # Log reason for consent withdrawal
            if reason:
                frappe.add_comment(
                    doctype="Donor", name=donor, text=f"ANBI consent withdrawn. Reason: {reason}"
                )

        donor_doc.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "message": _("ANBI consent updated successfully"),
            "consent": donor_doc.anbi_consent,
            "consent_date": donor_doc.anbi_consent_date,
        }

    except Exception as e:
        frappe.log_error(f"Failed to update ANBI consent: {str(e)}", "ANBI Consent Update Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def validate_bsn(bsn):
    """
    Validate a BSN number using the eleven-proof algorithm

    Args:
        bsn: BSN number to validate

    Returns:
        dict: Validation result
    """
    try:
        # Import the validation from donor
        from verenigingen.verenigingen.doctype.donor.donor import Donor

        donor = Donor()

        # Clean the BSN
        import re

        clean_bsn = re.sub(r"\D", "", bsn)

        if len(clean_bsn) != 9:
            return {"valid": False, "message": _("BSN must be exactly 9 digits")}

        # Validate using eleven-proof
        is_valid = donor.validate_bsn_eleven_proof(clean_bsn)

        return {
            "valid": is_valid,
            "message": _("Valid BSN") if is_valid else _("Invalid BSN (failed eleven-proof validation)"),
            "cleaned_value": clean_bsn,
        }

    except Exception as e:
        return {"valid": False, "message": str(e)}


@frappe.whitelist()
def get_anbi_statistics(from_date=None, to_date=None):
    """
    Get ANBI donation statistics

    Args:
        from_date: Optional start date
        to_date: Optional end date

    Returns:
        dict: Statistics data
    """
    try:
        filters = {"belastingdienst_reportable": 1, "docstatus": 1}

        if from_date and to_date:
            filters["date"] = ["between", [from_date, to_date]]

        # Get total donations
        total_donations = frappe.db.count("Donation", filters)

        # Get total amount
        total_amount = (
            frappe.db.sql(
                """
            SELECT SUM(amount)
            FROM `tabDonation`
            WHERE belastingdienst_reportable = 1
            AND docstatus = 1
            %s
        """
                % ("AND date BETWEEN %s AND %s" if from_date and to_date else ""),
                (from_date, to_date) if from_date and to_date else (),
            )[0][0]
            or 0
        )

        # Get donors with ANBI consent
        donors_with_consent = frappe.db.count("Donor", {"anbi_consent": 1})

        # Get donors with verified identification
        donors_verified = frappe.db.count("Donor", {"identification_verified": 1})

        return {
            "success": True,
            "statistics": {
                "total_anbi_donations": total_donations,
                "total_anbi_amount": total_amount,
                "donors_with_consent": donors_with_consent,
                "donors_verified": donors_verified,
                "period": {"from": from_date, "to": to_date} if from_date and to_date else None,
            },
        }

    except Exception as e:
        frappe.log_error(f"Failed to get ANBI statistics: {str(e)}", "ANBI Statistics Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def export_belastingdienst_report(filters):
    """
    Export ANBI report for Belastingdienst in CSV format

    Args:
        filters: Report filters dict

    Returns:
        dict: File URL for download
    """
    # Check permissions
    if not frappe.has_permission("Donation", "export"):
        frappe.throw(_("Insufficient permissions to export ANBI report"))

    try:
        import csv
        import os

        from frappe.utils.file_manager import save_file

        # Parse filters
        filters = json.loads(filters) if isinstance(filters, str) else filters

        # Get report data
        from verenigingen.verenigingen.report.anbi_donation_summary.anbi_donation_summary import get_data

        data = get_data(filters)

        # Create CSV content
        csv_content = []
        csv_content.append(["ANBI Donation Report", "", "", "", "", ""])
        csv_content.append(["Generated on:", frappe.utils.now(), "", "", "", ""])
        if filters.get("from_date") and filters.get("to_date"):
            csv_content.append(["Period:", f"{filters['from_date']} to {filters['to_date']}", "", "", "", ""])
        csv_content.append([])

        # Headers
        csv_content.append(
            [
                "Donor Name",
                "Donor Type",
                "Tax ID (BSN/RSIN)",
                "Agreement Type",
                "Agreement Number",
                "Total Donations",
                "Number of Donations",
                "First Donation",
                "Last Donation",
                "Consent Given",
            ]
        )

        # Data rows
        for row in data:
            csv_content.append(
                [
                    row.get("donor_name", ""),
                    row.get("donor_type", ""),
                    row.get("tax_id", ""),
                    row.get("agreement_type", ""),
                    row.get("agreement_number", ""),
                    row.get("total_donations", 0),
                    row.get("donation_count", 0),
                    row.get("first_donation", ""),
                    row.get("last_donation", ""),
                    "Yes" if row.get("consent_given") else "No",
                ]
            )

        # Summary
        csv_content.append([])
        csv_content.append(["Summary", "", "", "", "", ""])
        csv_content.append(["Total Donors:", len(data), "", "", "", ""])
        csv_content.append(
            ["Total Amount:", sum(row.get("total_donations", 0) for row in data), "", "", "", ""]
        )

        # Convert to CSV string
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        for row in csv_content:
            writer.writerow(row)

        csv_data = output.getvalue()

        # Save file
        filename = f"ANBI_Report_{frappe.utils.now_datetime().strftime('%Y%m%d_%H%M%S')}.csv"
        file_doc = save_file(filename, csv_data, "", "", is_private=1)

        # Log export for audit
        frappe.log_error(f"ANBI report exported by {frappe.session.user}", "ANBI Report Export")

        return {"success": True, "file_url": file_doc.file_url, "file_name": filename}

    except Exception as e:
        frappe.log_error(f"Failed to export ANBI report: {str(e)}", "ANBI Export Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def send_consent_requests(filters=None):
    """
    Send ANBI consent request emails to donors without consent

    Args:
        filters: Optional filters dict

    Returns:
        dict: Number of emails sent
    """
    # Check permissions
    if not frappe.has_permission("Donor", "write"):
        frappe.throw(_("Insufficient permissions to send consent requests"))

    try:
        # Get donors without consent who have made donations
        donors = frappe.db.sql(
            """
            SELECT DISTINCT
                donor.name,
                donor.donor_name,
                donor.donor_email
            FROM `tabDonor` donor
            INNER JOIN `tabDonation` donation ON donation.donor = donor.name
            WHERE (donor.anbi_consent = 0 OR donor.anbi_consent IS NULL)
            AND donor.donor_email IS NOT NULL
            AND donor.donor_email != ''
            AND donation.paid = 1
            AND donation.docstatus = 1
            LIMIT 100
        """,
            as_dict=1,
        )

        sent_count = 0

        for donor in donors:
            try:
                # Send email
                frappe.sendmail(
                    recipients=[donor.donor_email],
                    subject=_("ANBI Consent Request - Tax Benefits for Your Donations"),
                    message=get_consent_request_email(donor),
                    reference_doctype="Donor",
                    reference_name=donor.name,
                )

                # Log the request
                frappe.add_comment(
                    doctype="Donor",
                    name=donor.name,
                    text=f"ANBI consent request email sent to {donor.donor_email}",
                )

                sent_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Failed to send consent request to {donor.donor_email}: {str(e)}",
                    "ANBI Consent Email Error",
                )

        frappe.db.commit()

        return {
            "success": True,
            "sent_count": sent_count,
            "message": _("{0} consent request emails sent").format(sent_count),
        }

    except Exception as e:
        frappe.log_error(f"Failed to send consent requests: {str(e)}", "ANBI Consent Request Error")
        return {"success": False, "message": str(e)}


def get_consent_request_email(donor):
    """Generate consent request email content"""
    return f"""
    <p>Dear {donor.donor_name},</p>

    <p>Thank you for your generous donations to our organization.</p>

    <p>As an ANBI-registered organization, we can provide you with tax benefits for your donations.
    To enable these benefits and comply with Dutch tax regulations, we need your consent to:</p>

    <ul>
        <li>Store your tax identification number (BSN for individuals, RSIN for organizations)</li>
        <li>Report eligible donations to the Belastingdienst for automatic tax deduction</li>
    </ul>

    <p><strong>Benefits for you:</strong></p>
    <ul>
        <li>Automatic tax deduction for donations</li>
        <li>No need to manually claim deductions in your tax return</li>
        <li>Full deductibility for periodic donation agreements (5+ years)</li>
    </ul>

    <p><strong>Your privacy is protected:</strong></p>
    <ul>
        <li>Tax identifiers are encrypted and stored securely</li>
        <li>Data is only used for tax reporting purposes</li>
        <li>You can withdraw consent at any time</li>
    </ul>

    <p>To provide your consent, please:</p>
    <ol>
        <li>Log in to your donor portal</li>
        <li>Navigate to your profile settings</li>
        <li>Click on "ANBI Consent" and follow the instructions</li>
    </ol>

    <p>If you have any questions, please don't hesitate to contact us.</p>

    <p>With gratitude,<br>
    Your Organization</p>

    <hr>
    <p style="font-size: 12px; color: #666;">
    This email was sent because you are a registered donor.
    If you no longer wish to receive these communications,
    please update your preferences in your donor portal.
    </p>
    """
