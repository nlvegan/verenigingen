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
    Generate ANBI confirmation receipts for active periodic donation agreements.

    For each Active + ANBI-eligible agreement, renders a confirmation receipt,
    converts it to a PDF, and attaches it to the agreement as a private File
    (deterministically named, replacing any prior receipt so exactly one current
    receipt exists per agreement). Only agreements whose receipt is actually
    produced and saved are counted.

    Args:
        filters: Report filters dict (parsed for HTTP-layer compatibility; the
            selection itself is fixed to Active + ANBI-eligible agreements).

    Returns:
        OperationResult: {"generated_count": int, "failed": [{name, error}, ...]}
    """
    try:
        # Parse filters (may arrive as a JSON string from the HTTP layer).
        filters = json.loads(filters) if isinstance(filters, str) else filters

        # Only Active, ANBI-eligible agreements receive a tax receipt.
        agreements = frappe.get_all(
            "Periodic Donation Agreement",
            filters={"status": "Active", "anbi_eligible": 1},
            fields=["name", "agreement_number"],
        )

        generated_count = 0
        failed = []

        for agreement in agreements:
            try:
                _attach_tax_receipt_pdf(agreement.name, agreement.agreement_number)

                # Audit comment is recorded ONLY after the receipt File is saved,
                # so the trail never claims a receipt that was not produced.
                frappe.get_doc("Periodic Donation Agreement", agreement.name).add_comment(
                    "Comment",
                    f"Tax receipt generated for {frappe.utils.formatdate(today())}",
                )

                generated_count += 1

            except Exception as e:
                failed.append({"name": agreement.name, "error": str(e)})
                frappe.log_error(
                    f"Failed to generate tax receipt for {agreement.agreement_number}: {str(e)}\n{traceback.format_exc()}",
                    "Tax Receipt Generation Error",
                )

        # Persist the File attachments/deletions (consistent with the sibling
        # whitelisted ops in this module, and required if ever run from a
        # background/scheduled context).
        frappe.db.commit()

        return OperationResult.ok(
            {
                "generated_count": generated_count,
                "failed": failed,
            },
            message=_("{0} tax receipts generated").format(generated_count),
        )

    except Exception as e:
        frappe.log_error(
            f"Failed to generate tax receipts: {str(e)}\n{traceback.format_exc()}", "Tax Receipt Error"
        )
        return OperationResult.fail(_("Failed to generate tax receipts"), errors=[str(e)])


def _attach_tax_receipt_pdf(agreement_name: str, agreement_number: str) -> str:
    """Render the receipt, convert to PDF, and attach it (idempotent replace).

    Returns the file_url of the attached receipt File.
    """
    from frappe.utils.file_manager import save_file
    from frappe.utils.pdf import get_pdf

    html = render_tax_receipt_html(agreement_name)
    pdf_bytes = get_pdf(html)
    file_stem = f"ANBI_Tax_Receipt_{agreement_number}"
    file_name = f"{file_stem}.pdf"

    # Save the fresh receipt FIRST, so a failure here never destroys a
    # previously-good receipt (delete-then-save would leave the agreement with
    # nothing if save_file raised).
    file_doc = save_file(
        file_name,
        pdf_bytes,
        "Periodic Donation Agreement",
        agreement_name,
        is_private=1,
    )

    # Then remove any OTHER (older) receipt File for this agreement so exactly
    # one current receipt remains (idempotent replace). Match by the
    # deterministic stem -- save_file inserts a uniqueness hash before the
    # extension when a same-named file already exists on disk -- with LIKE
    # metacharacters escaped, scoped to this agreement via attached_to_name, and
    # excluding the file we just saved.
    like_stem = file_stem.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    stale = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Periodic Donation Agreement",
            "attached_to_name": agreement_name,
            "file_name": ["like", f"{like_stem}%"],
            "name": ["!=", file_doc.name],
        },
        pluck="name",
    )
    for file_id in stale:
        # Security: called only from the FINANCIAL @critical_api generate_tax_receipts
        # (privileged actors). Targets are this app's own auto-generated receipt Files,
        # scoped to a single agreement (attached_to_name) by the deterministic receipt
        # stem -- never arbitrary user attachments. ignore_permissions lets the receipt
        # replace run for background/service actors without a role-gated permission check.
        frappe.delete_doc("File", file_id, ignore_permissions=True, force=True)

    return file_doc.file_url


def render_tax_receipt_html(agreement_name: str) -> str:
    """Render the ANBI confirmation-receipt HTML for a periodic donation agreement.

    Pure (no side effects) so it is independently testable. Pulls the issuing
    organization identity from Verenigingen Settings and the donor identity from
    the linked Donor record.

    Frappe's render_template does NOT autoescape, and the rendered HTML is fed to
    wkhtmltopdf, so every donor/org-controlled string is escaped here before it
    reaches the template (prevents HTML/JS injection into the PDF). Money/date
    values are framework-formatted and safe.
    """
    from frappe.utils import escape_html

    agreement = frappe.get_doc("Periodic Donation Agreement", agreement_name)
    donor = frappe.get_doc("Donor", agreement.donor)

    org_name = frappe.db.get_single_value("Verenigingen Settings", "company_name") or ""
    company = frappe.db.get_single_value("Verenigingen Settings", "company")
    org_rsin = frappe.db.get_value("Company", company, "tax_id") if company else None
    donor_address = donor.get("address")

    context = {
        "org_name": escape_html(org_name),
        "org_rsin": escape_html(org_rsin) if org_rsin else None,
        "issue_date": frappe.utils.formatdate(today()),
        "donor_name": escape_html(agreement.donor_name or donor.donor_name or ""),
        "donor_address": escape_html(donor_address) if donor_address else None,
        "agreement_number": escape_html(agreement.agreement_number or ""),
        "agreement_type": escape_html(agreement.agreement_type) if agreement.agreement_type else None,
        "annual_amount": frappe.utils.fmt_money(agreement.annual_amount, currency="EUR"),
        "start_date": frappe.utils.formatdate(agreement.start_date) if agreement.start_date else None,
        "end_date": frappe.utils.formatdate(agreement.end_date) if agreement.end_date else None,
    }
    return frappe.render_template("verenigingen/templates/donation/anbi_tax_receipt.html", context)


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
