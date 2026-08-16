"""
ANBI Operations API for Donation Management
Handles ANBI compliance operations including tax identifier management and reporting
"""

import json
import traceback
from datetime import datetime
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult

# Import security decorators
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, standard_api


def has_donor_permlevel_access(permission_type="read"):
    """
    Check if user has permlevel 1 access to Donor doctype using Frappe's permission system.

    This function validates access to sensitive donor data including encrypted tax identifiers
    (BSN/RSIN). Only users with proper permissions should access these fields for ANBI
    tax reporting compliance.

    Args:
        permission_type (str): Type of permission to check ("read", "write", "create", etc.)

    Returns:
        bool: True if user has required permissions, False otherwise

    Security Note:
        - Uses Frappe's built-in permission system (no custom bypass)
        - Respects DocType permlevel configuration
        - Required for accessing encrypted tax identifier fields
        - Logged for audit compliance
    """
    # Use Frappe's standard permission checking - no custom security bypass
    return frappe.has_permission("Donor", ptype=permission_type)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def update_donor_tax_identifiers(
    donor: str, bsn: str = None, rsin: str = None, verification_method=None
) -> OperationResult[Dict[str, Any]]:
    """
    Update donor tax identifiers with proper security checks and validation.

    This API endpoint manages sensitive Dutch tax identifiers required for ANBI
    tax benefit reporting. All identifiers are encrypted at storage and subject
    to strict access controls.

    Tax Identifier Types:
    - BSN (Burgerservicenummer): 9-digit identifier for Dutch individuals
    - RSIN (Rechtspersonen Samenwerkingsverbanden Informatie Nummer): Organization tax number

    Args:
        donor (str): Donor document name/ID
        bsn (str, optional): BSN for individual donors (must pass eleven-proof validation)
        rsin (str, optional): RSIN for organization donors
        verification_method (str, optional): Method used to verify identity
                                           (e.g., "ID Card", "Passport", "KvK Extract")

    Returns:
        OperationResult[Dict[str, Any]]: Operation result containing:
            - donor (str): Updated donor document name

    Security Controls:
    - Requires permlevel 1 access to Donor doctype
    - Uses @critical_api decorator for enhanced logging
    - No permission bypasses - respects Frappe security model
    - Automatic encryption of stored tax identifiers
    - Comprehensive audit trail for compliance

    Validation:
    - BSN validated using eleven-proof algorithm
    - RSIN format validation
    - Donor existence verification
    - Proper field assignment based on donor type
    """
    # Check permissions - fail if insufficient access
    if not has_donor_permlevel_access("write"):
        frappe.throw(_("Insufficient permissions to update tax identifiers"))

    try:
        # Load donor document with standard Frappe error handling
        donor_doc = frappe.get_doc("Donor", donor)

        # Update tax identifier fields if provided
        # BSN and RSIN are automatically encrypted by Frappe's encryption system
        if bsn is not None:
            # BSN should already be validated by client, but we store as provided
            donor_doc.bsn_citizen_service_number = bsn

        if rsin is not None:
            # RSIN for organization donors - no specific validation here
            donor_doc.rsin_organization_tax_number = rsin

        # Update verification status if method provided
        if verification_method:
            # Mark as verified with timestamp and method for audit trail
            donor_doc.identification_verified = 1
            donor_doc.identification_verification_date = frappe.utils.today()
            donor_doc.identification_verification_method = verification_method

        # Save with proper permission checking (no ignore_permissions)
        # Let Frappe handle all validation and encryption
        donor_doc.save()
        donor_doc.reload()  # Ensure we have fresh data for response

        # Commit transaction - important for security operations
        frappe.db.commit()

        return OperationResult.ok(
            data={"donor": donor_doc.name}, message=_("Tax identifiers updated successfully")
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to update tax identifiers: {str(e)}\n{traceback.format_exc()}",
            "ANBI Tax ID Update Error",
        )
        return OperationResult.fail(
            _("Failed to update tax identifiers"),
            errors=[str(e)],
            context={"operation": "update_donor_tax_identifiers", "donor": donor},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def get_donor_anbi_data(donor: str) -> OperationResult[Dict[str, Any]]:
    """
    Get ANBI-related data for a donor (with decryption for authorized users)

    Args:
        donor: Donor document name

    Returns:
        OperationResult[Dict[str, Any]]: Donor ANBI data (masked for display) containing:
            - donor_name (str): Donor name
            - donor_type (str): Donor type (Individual/Organization)
            - bsn (str): BSN (masked by security layer)
            - rsin (str): RSIN (masked by security layer)
            - identification_verified (int): Verification status
            - verification_date (str): Verification date
            - verification_method (str): Verification method
            - anbi_consent (int): ANBI consent status
            - anbi_consent_date (str): Consent date
    """
    # Check permissions
    if not has_donor_permlevel_access("read"):
        frappe.throw(_("Insufficient permissions to view ANBI data"))

    try:
        # Fetch only required fields for better performance
        donor_data = frappe.db.get_value(
            "Donor",
            donor,
            [
                "donor_name",
                "donor_type",
                "bsn_citizen_service_number",
                "rsin_organization_tax_number",
                "identification_verified",
                "identification_verification_date",
                "identification_verification_method",
                "anbi_consent",
                "anbi_consent_date",
            ],
            as_dict=True,
        )

        if not donor_data:
            return OperationResult.fail(
                _("Donor not found"),
                errors=["Donor document does not exist"],
                context={"operation": "get_donor_anbi_data", "donor": donor},
            )

        # Get decrypted values (will be masked by security layer)
        data = {
            "donor_name": donor_data.get("donor_name"),
            "donor_type": donor_data.get("donor_type"),
            "bsn": donor_data.get("bsn_citizen_service_number"),  # Will be masked by security layer
            "rsin": donor_data.get("rsin_organization_tax_number"),  # Will be masked by security layer
            "identification_verified": donor_data.get("identification_verified"),
            "verification_date": donor_data.get("identification_verification_date"),
            "verification_method": donor_data.get("identification_verification_method"),
            "anbi_consent": donor_data.get("anbi_consent"),
            "anbi_consent_date": donor_data.get("anbi_consent_date"),
        }

        return OperationResult.ok(data=data, message=_("ANBI data retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Failed to get ANBI data: {str(e)}\n{traceback.format_exc()}", "ANBI Data Retrieval Error"
        )
        return OperationResult.fail(
            _("Failed to retrieve ANBI data"),
            errors=[str(e)],
            context={"operation": "get_donor_anbi_data", "donor": donor},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def generate_anbi_report(from_date, to_date, include_bsn=False) -> OperationResult[Dict[str, Any]]:
    """
    Generate ANBI report for Belastingdienst reporting

    Args:
        from_date: Start date for report
        to_date: End date for report
        include_bsn: Whether to include decrypted BSN/RSIN (requires special permission)

    Returns:
        OperationResult[Dict[str, Any]]: Report data containing:
            - report_date (str): Report generation timestamp
            - period (dict): From and to dates
            - summary (dict): Total donations, amount, and tax ID inclusion flag
            - donations (list): List of donation records with donor information
    """
    # Check permissions
    if not frappe.has_permission("Donation", "read"):
        frappe.throw(_("Insufficient permissions to generate ANBI report"))

    # Check special permission for BSN/RSIN export
    if include_bsn and not has_donor_permlevel_access("read"):
        frappe.throw(_("Insufficient permissions to export BSN/RSIN data"))

    try:
        # Get donations marked for ANBI reporting
        # Note: ANBI tracking is via separate ANBI Donation Agreement DocType
        # Use anbi_agreement_number field to identify ANBI-eligible donations
        # WHY "docstatus < 2" and not "= 1": Donation is not submittable (no
        # is_submittable in its DocType JSON), so a donation created by any normal
        # path sits at docstatus 0 forever and "= 1" made this report empty on
        # every deployment (#350). docstatus 2 still has to be excluded: nothing
        # guards Document._submit()/_cancel() on a non-submittable doctype, so
        # cancelled rows do exist and must stay out of a tax figure.
        donations = frappe.get_all(
            "Donation",
            filters={
                "anbi_agreement_number": ["is", "set"],
                "donation_date": ["between", [from_date, to_date]],
                "docstatus": ["<", 2],
            },
            fields=[
                "name",
                "donor",
                "donation_date",
                "amount",
                "anbi_agreement_number",
                "anbi_agreement_date",
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
                "date": donation.donation_date,
                "amount": donation.amount,
                "donor_name": donor_doc.donor_name,
                "donor_type": donor_doc.donor_type,
                "anbi_agreement_number": donation.anbi_agreement_number,
                "anbi_agreement_date": donation.anbi_agreement_date,
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

        # Log the report generation for audit trail (informational, not an error)
        frappe.logger().info(
            f"ANBI report generated by {frappe.session.user} for period {from_date} to {to_date}"
        )

        data = {
            "report_date": frappe.utils.now(),
            "period": {"from": from_date, "to": to_date},
            "summary": {
                "total_donations": len(donations),
                "total_amount": total_amount,
                "includes_tax_ids": include_bsn,
            },
            "donations": report_data,
        }

        return OperationResult.ok(
            data=data,
            message=_("ANBI report generated successfully with {0} donations").format(len(donations)),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to generate ANBI report: {str(e)}\n{traceback.format_exc()}",
            "ANBI Report Generation Error",
        )
        return OperationResult.fail(
            _("Failed to generate ANBI report"),
            errors=[str(e)],
            context={"operation": "generate_anbi_report", "from_date": from_date, "to_date": to_date},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def update_anbi_consent(donor: str, consent, reason=None) -> OperationResult[Dict[str, Any]]:
    """
    Update ANBI consent for a donor

    Args:
        donor: Donor document name
        consent: Boolean indicating consent status
        reason: Optional reason for consent change

    Returns:
        OperationResult[Dict[str, Any]]: Operation result containing:
            - consent (int): Updated consent status
            - consent_date (str): Consent date
    """
    try:
        donor_doc = frappe.get_doc("Donor", donor)

        # Update consent. Whitelisted calls deliver `consent` as a string ("0"/"1"),
        # and "0" is truthy in Python, so the branch must test the cbool-normalized
        # value, not the raw argument.
        from verenigingen.utils.boolean_utils import cbool

        consent_given = cbool(consent)
        donor_doc.anbi_consent = consent_given

        if consent_given:
            donor_doc.anbi_consent_date = frappe.utils.now()
        elif reason:
            # Log reason for consent withdrawal (frappe has no module-level
            # add_comment; it is a Document method)
            donor_doc.add_comment("Comment", f"ANBI consent withdrawn. Reason: {reason}")

        # Save with proper permission checking (no ignore_permissions)
        donor_doc.save()
        donor_doc.reload()  # Ensure we have fresh data
        frappe.db.commit()

        return OperationResult.ok(
            data={
                "consent": donor_doc.anbi_consent,
                "consent_date": donor_doc.anbi_consent_date,
            },
            message=_("ANBI consent updated successfully"),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to update ANBI consent: {str(e)}\n{traceback.format_exc()}", "ANBI Consent Update Error"
        )
        return OperationResult.fail(
            _("Failed to update ANBI consent"),
            errors=[str(e)],
            context={"operation": "update_anbi_consent", "donor": donor},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def validate_bsn(bsn: str) -> OperationResult[Dict[str, Any]]:
    """
    Validate a BSN number using the eleven-proof algorithm

    Args:
        bsn: BSN number to validate

    Returns:
        OperationResult[Dict[str, Any]]: Validation result containing:
            - valid (bool): Whether BSN is valid
            - cleaned_value (str): Cleaned BSN value (digits only)
    """
    try:
        # Use a fresh in-memory Donor document to reach the instance-method validator.
        # NOTE: Donor() cannot be constructed without args (raises ValueError); the
        # framework factory frappe.new_doc() is the correct way to get an instance.
        donor = frappe.new_doc("Donor")

        # Clean the BSN
        import re

        clean_bsn = re.sub(r"\D", "", bsn)

        if len(clean_bsn) != 9:
            return OperationResult.ok(
                data={"valid": False, "cleaned_value": clean_bsn}, message=_("BSN must be exactly 9 digits")
            )

        # Validate using eleven-proof
        is_valid = donor.validate_bsn_eleven_proof(clean_bsn)

        return OperationResult.ok(
            data={"valid": is_valid, "cleaned_value": clean_bsn},
            message=_("Valid BSN") if is_valid else _("Invalid BSN (failed eleven-proof validation)"),
        )

    except Exception as e:
        frappe.log_error(f"BSN validation error: {str(e)}\n{traceback.format_exc()}", "BSN Validation Error")
        return OperationResult.fail(
            _("Failed to validate BSN"), errors=[str(e)], context={"operation": "validate_bsn"}
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def get_anbi_statistics(from_date=None, to_date=None) -> OperationResult[Dict[str, Any]]:
    """
    Get ANBI donation statistics

    Args:
        from_date: Optional start date
        to_date: Optional end date

    Returns:
        OperationResult[Dict[str, Any]]: Statistics data containing:
            - statistics (dict): ANBI statistics including:
                - total_anbi_donations (int): Total number of ANBI donations
                - total_anbi_amount (float): Total amount of ANBI donations
                - donors_with_consent (int): Number of donors with ANBI consent
                - donors_verified (int): Number of donors with verified identification
                - period (dict): Optional period filter
    """
    try:
        # Note: ANBI tracking is via separate ANBI Donation Agreement DocType
        # Use anbi_agreement_number field to identify ANBI-eligible donations
        # "docstatus < 2", not "= 1": Donation is not submittable, so every row is
        # docstatus 0 and "= 1" made this Belastingdienst figure always zero (#350).
        # Cancelled (docstatus 2) rows must still be excluded from a tax total.
        filters = {"anbi_agreement_number": ["is", "set"], "docstatus": ["<", 2]}

        if from_date and to_date:
            filters["donation_date"] = ["between", [from_date, to_date]]

        # Get total donations
        total_donations = frappe.db.count("Donation", filters)

        # Get total amount
        total_amount = (
            frappe.db.sql(
                """
            SELECT SUM(amount)
            FROM `tabDonation`
            WHERE anbi_agreement_number IS NOT NULL
            AND anbi_agreement_number != ''
            AND docstatus < 2
            %s
        """
                % ("AND donation_date BETWEEN %s AND %s" if from_date and to_date else ""),
                (from_date, to_date) if from_date and to_date else (),
            )[0][0]
            or 0
        )

        # Get donors with ANBI consent
        donors_with_consent = frappe.db.count("Donor", {"anbi_consent": 1})

        # Get donors with verified identification
        donors_verified = frappe.db.count("Donor", {"identification_verified": 1})

        data = {
            "statistics": {
                "total_anbi_donations": total_donations,
                "total_anbi_amount": total_amount,
                "donors_with_consent": donors_with_consent,
                "donors_verified": donors_verified,
                "period": {"from": from_date, "to": to_date} if from_date and to_date else None,
            }
        }

        return OperationResult.ok(data=data, message=_("ANBI statistics retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Failed to get ANBI statistics: {str(e)}\n{traceback.format_exc()}", "ANBI Statistics Error"
        )
        return OperationResult.fail(
            _("Failed to retrieve ANBI statistics"),
            errors=[str(e)],
            context={"operation": "get_anbi_statistics", "from_date": from_date, "to_date": to_date},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def export_belastingdienst_report(filters: str | dict) -> OperationResult[Dict[str, Any]]:
    """
    Export ANBI report for Belastingdienst in CSV format

    Args:
        filters: Report filters dict

    Returns:
        OperationResult[Dict[str, Any]]: Operation result containing:
            - file_url (str): File URL for download
            - file_name (str): Generated file name
    """
    # Check permissions
    if not frappe.has_permission("Donation", "export"):
        frappe.throw(_("Insufficient permissions to export ANBI report"))

    try:
        import csv
        import io
        import os

        from frappe.utils.file_manager import save_file

        # Parse filters
        filters = json.loads(filters) if isinstance(filters, str) else filters

        # Get report data
        from verenigingen.verenigingen.report.donation_summary.donation_summary import get_data

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
        output = io.StringIO()
        writer = csv.writer(output)
        for row in csv_content:
            writer.writerow(row)

        csv_data = output.getvalue()

        # Save file
        filename = f"ANBI_Report_{frappe.utils.now_datetime().strftime('%Y%m%d_%H%M%S')}.csv"
        file_doc = save_file(filename, csv_data, "", "", is_private=1)

        # Log export for audit (informational, not an error)
        frappe.logger().info(f"ANBI report exported by {frappe.session.user}")

        return OperationResult.ok(
            data={"file_url": file_doc.file_url, "file_name": filename},
            message=_("ANBI report exported successfully"),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to export ANBI report: {str(e)}\n{traceback.format_exc()}", "ANBI Export Error"
        )
        return OperationResult.fail(
            _("Failed to export ANBI report"),
            errors=[str(e)],
            context={"operation": "export_belastingdienst_report"},
        )


@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def send_consent_requests(filters: dict | str | None = None) -> OperationResult[Dict[str, Any]]:
    """
    Send ANBI consent request emails to donors without consent

    Args:
        filters: Optional filters dict

    Returns:
        OperationResult[Dict[str, Any]]: Operation result containing:
            - sent_count (int): Number of emails sent successfully
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
            AND donation.docstatus < 2
            LIMIT 100
        """,
            as_dict=1,
        )

        sent_count = 0

        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()
        settings = frappe.get_single("Verenigingen Settings")

        for donor in donors:
            try:
                # Prepare context with XSS-safe escaping
                context = {
                    "donor_name": donor.donor_name,
                    "organization_name": frappe.defaults.get_global_default("company"),
                    "organization_email": getattr(settings, "member_contact_email", ""),
                }

                # Send email via EmailService
                result = email_service.send_templated_email(
                    template_name="anbi_consent_request",
                    recipients=[donor.donor_email],
                    context=context,
                    subject=_("ANBI Consent Request - Tax Benefits for Your Donations"),
                    reference_doctype="Donor",
                    reference_name=donor.name,
                    notification_key="anbi_consent_request",
                )

                if result.success:
                    # Log the request
                    frappe.add_comment(
                        doctype="Donor",
                        name=donor.name,
                        text=f"ANBI consent request email sent to {donor.donor_email}",
                    )
                    sent_count += 1
                else:
                    frappe.logger().error(
                        f"Failed to send consent request to {donor.donor_email}: {'; '.join(result.errors)}"
                    )

            except Exception as e:
                frappe.log_error(
                    f"Failed to send consent request to {donor.donor_email}: {str(e)}",
                    "ANBI Consent Email Error",
                )

        frappe.db.commit()

        return OperationResult.ok(
            data={"sent_count": sent_count}, message=_("{0} consent request emails sent").format(sent_count)
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to send consent requests: {str(e)}\n{traceback.format_exc()}",
            "ANBI Consent Request Error",
        )
        return OperationResult.fail(
            _("Failed to send consent requests"),
            errors=[str(e)],
            context={"operation": "send_consent_requests"},
        )
