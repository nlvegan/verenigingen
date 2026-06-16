"""
Periodic Donation Agreement Operations API
Handles creation, management, and reporting of 5-year periodic donation agreements
"""

import json
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import flt, today

# Import email service
from verenigingen.services.communication.email_service import get_email_service

# Import security decorators and OperationResult
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_periodic_agreement(
    donor: str,
    annual_amount,
    payment_frequency: str,
    payment_method: str,
    start_date=None,
    agreement_type="Private Written",
    sepa_mandate=None,
) -> OperationResult[Dict[str, Any]]:
    """
    Create a new periodic donation agreement

    Args:
        donor: Donor document name
        annual_amount: Annual donation amount
        payment_frequency: Monthly/Quarterly/Annually
        payment_method: Payment method
        start_date: Agreement start date (defaults to today)
        agreement_type: Notarial/Private Written
        sepa_mandate: SEPA mandate if applicable

    Returns:
        OperationResult: Success status and agreement details
    """
    try:
        # Validate donor has ANBI consent
        donor_doc = frappe.get_doc("Donor", donor)

        if not donor_doc.anbi_consent:
            frappe.msgprint(
                _(
                    "Warning: This donor has not given ANBI consent. "
                    "The agreement will be created but may not be valid for tax purposes."
                )
            )

        # Create agreement
        agreement = frappe.new_doc("Periodic Donation Agreement")
        agreement.donor = donor
        agreement.annual_amount = flt(annual_amount)
        agreement.payment_frequency = payment_frequency
        agreement.payment_method = payment_method
        agreement.start_date = start_date or today()
        agreement.agreement_type = agreement_type
        agreement.status = "Draft"

        if sepa_mandate:
            agreement.sepa_mandate = sepa_mandate

        # Auto-calculate end date and payment amount
        agreement.calculate_end_date()
        agreement.calculate_payment_amount()

        agreement.insert()

        frappe.db.commit()

        return OperationResult.ok(
            {
                "agreement": agreement.name,
                "agreement_number": agreement.agreement_number,
            },
            message=_("Periodic donation agreement created successfully"),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to create periodic agreement: {str(e)}\n{traceback.format_exc()}",
            "Periodic Agreement Creation Error",
        )
        return OperationResult.fail(_("Failed to create periodic donation agreement"), errors=[str(e)])


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def link_donation_to_agreement(donation, agreement) -> OperationResult[Dict[str, Any]]:
    """
    Link an existing donation to a periodic agreement

    Args:
        donation: Donation document name
        agreement: Periodic Donation Agreement name

    Returns:
        OperationResult: Success status
    """
    try:
        # Validate donation and agreement
        donation_doc = frappe.get_doc("Donation", donation)
        agreement_doc = frappe.get_doc("Periodic Donation Agreement", agreement)

        # Check donor matches
        if donation_doc.donor != agreement_doc.donor:
            frappe.throw(_("Donation donor does not match agreement donor"))

        # Check if already linked
        if donation_doc.periodic_donation_agreement:
            frappe.throw(_("Donation is already linked to an agreement"))

        # Link donation
        donation_doc.periodic_donation_agreement = agreement

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        # Secure donation update with explicit permission validation
        donation_result = secure_document_operation(
            operation="save",
            doc=donation_doc,
            justification=f"Link donation {donation} to periodic donation agreement {agreement}",
            required_permissions=["Donation:write"],
        )

        if not donation_result.success:
            frappe.throw(
                _("Failed to link donation to agreement: {0}").format("; ".join(donation_result.errors))
            )

        # Add to agreement's donation table
        agreement_doc.link_donation(donation)

        frappe.db.commit()

        return OperationResult.ok({}, message=_("Donation linked to agreement successfully"))

    except Exception as e:
        frappe.log_error(
            f"Failed to link donation: {str(e)}\n{traceback.format_exc()}", "Donation Linking Error"
        )
        return OperationResult.fail(_("Failed to link donation to agreement"), errors=[str(e)])


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def send_renewal_reminders(days_before_expiry=90) -> OperationResult[Dict[str, Any]]:
    """
    Send renewal reminders for expiring agreements

    Args:
        days_before_expiry: Days before expiry to send reminders

    Returns:
        OperationResult: Number of reminders sent
    """
    try:
        expiry_date = frappe.utils.add_days(today(), days_before_expiry)

        agreements = frappe.db.sql(
            """
            SELECT
                pda.name,
                pda.agreement_number,
                pda.donor,
                pda.donor_name,
                pda.end_date,
                pda.annual_amount,
                donor.donor_email
            FROM `tabPeriodic Donation Agreement` pda
            INNER JOIN `tabDonor` donor ON pda.donor = donor.name
            WHERE pda.status = 'Active'
            AND pda.end_date <= %s
            AND donor.donor_email IS NOT NULL
            AND donor.donor_email != ''
        """,
            (expiry_date,),
            as_dict=1,
        )

        sent_count = 0

        for agreement in agreements:
            days_remaining = frappe.utils.date_diff(agreement.end_date, today())

            try:
                email_service = get_email_service()
                email_service.send_simple_email(
                    recipients=[agreement.donor_email],
                    subject=_("Your Periodic Donation Agreement is Expiring Soon"),
                    message=get_renewal_reminder_email(agreement, days_remaining),
                    reference_doctype="Periodic Donation Agreement",
                    reference_name=agreement.name,
                    notification_key="periodic_donation_expiry",
                )

                # Log the reminder (frappe has no module-level add_comment; it is a
                # Document method)
                frappe.get_doc("Periodic Donation Agreement", agreement.name).add_comment(
                    "Comment",
                    f"Renewal reminder sent to {agreement.donor_email} ({days_remaining} days until expiry)",
                )

                sent_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Failed to send renewal reminder for {agreement.agreement_number}: {str(e)}\n{traceback.format_exc()}",
                    "Agreement Renewal Reminder Error",
                )

        frappe.db.commit()

        return OperationResult.ok(
            {
                "sent_count": sent_count,
            },
            message=_("{0} renewal reminders sent").format(sent_count),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to send renewal reminders: {str(e)}\n{traceback.format_exc()}", "Renewal Reminder Error"
        )
        return OperationResult.fail(_("Failed to send renewal reminders"), errors=[str(e)])


def get_renewal_reminder_email(agreement, days_remaining):
    """Generate renewal reminder email content"""
    return f"""
    <p>Dear {agreement.donor_name},</p>

    <p>Your periodic donation agreement ({agreement.agreement_number}) will expire in <strong>{days_remaining} days</strong>
    on {frappe.utils.formatdate(agreement.end_date)}.</p>

    <p>Your support through this agreement has made a significant impact:</p>
    <ul>
        <li>Annual commitment: €{agreement.annual_amount:,.2f}</li>
        <li>5-year total commitment: €{agreement.annual_amount * 5:,.2f}</li>
        <li>Full tax deductibility under ANBI regulations</li>
    </ul>

    <p><strong>To continue your support and tax benefits:</strong></p>
    <p>We invite you to renew your periodic donation agreement before it expires.
    Renewing ensures:</p>
    <ul>
        <li>Uninterrupted tax benefits</li>
        <li>Continued support for our mission</li>
        <li>Simplified donation process</li>
    </ul>

    <p>You can renew your agreement by:</p>
    <ol>
        <li>Logging into your donor portal</li>
        <li>Clicking on "Renew Agreement"</li>
        <li>Confirming your details</li>
    </ol>

    <p>If you have any questions or would like to discuss your renewal,
    please don't hesitate to contact us.</p>

    <p>Thank you for your continued support!</p>

    <p>With gratitude,<br>
    Your Organization</p>
    """


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def generate_tax_receipts(filters: dict | str) -> OperationResult[Dict[str, Any]]:
    """
    Generate tax receipts for periodic donations

    Args:
        filters: Report filters dict

    Returns:
        OperationResult: Number of receipts generated
    """
    try:
        # Parse filters
        filters = json.loads(filters) if isinstance(filters, str) else filters

        # Get agreements that need receipts
        agreement_filters = {"status": "Active", "anbi_eligible": 1}

        agreements = frappe.get_all(
            "Periodic Donation Agreement",
            filters=agreement_filters,
            fields=["name", "donor", "donor_name", "agreement_number", "annual_amount"],
        )

        generated_count = 0

        for agreement in agreements:
            try:
                # Generate receipt document (placeholder - implement actual receipt generation)
                generate_tax_receipt_content(agreement)

                # Save as attachment or create custom doctype (frappe has no
                # module-level add_comment; it is a Document method)
                frappe.get_doc("Periodic Donation Agreement", agreement.name).add_comment(
                    "Comment",
                    f"Tax receipt generated for {frappe.utils.formatdate(today())}",
                )

                generated_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Failed to generate tax receipt for {agreement.agreement_number}: {str(e)}\n{traceback.format_exc()}",
                    "Tax Receipt Generation Error",
                )

        return OperationResult.ok(
            {
                "generated_count": generated_count,
            },
            message=_("{0} tax receipts generated").format(generated_count),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to generate tax receipts: {str(e)}\n{traceback.format_exc()}", "Tax Receipt Error"
        )
        return OperationResult.fail(_("Failed to generate tax receipts"), errors=[str(e)])


def generate_tax_receipt_content(agreement):
    """Generate tax receipt content"""
    # This is a placeholder - implement actual receipt generation
    return f"""
    TAX RECEIPT - ANBI PERIODIC DONATION

    Agreement Number: {agreement.agreement_number}
    Donor: {agreement.donor_name}
    Annual Amount: €{agreement.annual_amount:,.2f}

    This receipt confirms your periodic donation agreement qualifies for full tax deductibility
    under Dutch ANBI regulations.
    """


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def export_agreements(filters: dict | str) -> OperationResult[Dict[str, Any]]:
    """
    Export periodic agreements to CSV

    Args:
        filters: Report filters dict

    Returns:
        OperationResult: File URL for download
    """
    try:
        import csv
        import io

        from frappe.utils.file_manager import save_file

        # Parse filters
        filters = json.loads(filters) if isinstance(filters, str) else filters

        # Get report data
        from verenigingen.verenigingen.report.anbi_periodic_agreements.anbi_periodic_agreements import (
            get_data,
        )

        data = get_data(filters)

        # Create CSV content
        csv_content = []
        csv_content.append(["ANBI Periodic Agreements Report", "", "", "", "", ""])
        csv_content.append(["Generated on:", frappe.utils.now(), "", "", "", ""])
        csv_content.append([])

        # Headers
        csv_content.append(
            [
                "Agreement Number",
                "Status",
                "Type",
                "Donor Name",
                "Duration",
                "Start Date",
                "End Date",
                "Days Remaining",
                "Annual Amount",
                "Payment Frequency",
                "Total Donated",
                "Completion %",
                "Expected Total",
                "ANBI Eligible",
            ]
        )

        # Data rows
        for row in data:
            csv_content.append(
                [
                    row.get("agreement_number", ""),
                    row.get("status", ""),
                    row.get("commitment_type", ""),
                    row.get("donor_name", ""),
                    row.get("duration", ""),
                    row.get("start_date", ""),
                    row.get("end_date", ""),
                    row.get("days_remaining", 0),
                    row.get("annual_amount", 0),
                    row.get("payment_frequency", ""),
                    row.get("total_donated", 0),
                    row.get("completion_percentage", 0),
                    row.get("expected_total", 0),
                    "Yes" if row.get("anbi_eligible") else "No",
                ]
            )

        # Convert to CSV string
        output = io.StringIO()
        writer = csv.writer(output)
        for row in csv_content:
            writer.writerow(row)

        csv_data = output.getvalue()

        # Save file
        filename = f"Periodic_Agreements_{frappe.utils.now_datetime().strftime('%Y%m%d_%H%M%S')}.csv"
        file_doc = save_file(filename, csv_data, "", "", is_private=1)

        return OperationResult.ok(
            {"file_url": file_doc.file_url, "file_name": filename},
            message=_("Agreements exported successfully"),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to export agreements: {str(e)}\n{traceback.format_exc()}", "Agreement Export Error"
        )
        return OperationResult.fail(_("Failed to export agreements"), errors=[str(e)])
