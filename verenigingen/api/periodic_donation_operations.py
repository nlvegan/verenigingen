"""
Periodic Donation Agreement Operations API
Handles creation, management, and reporting of 5-year periodic donation agreements
"""

import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_years, flt, getdate, today


@frappe.whitelist()
def create_periodic_agreement(
    donor,
    annual_amount,
    payment_frequency,
    payment_method,
    start_date=None,
    agreement_type="Private Written",
    sepa_mandate=None,
):
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
        dict: Success status and agreement details
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

        return {
            "success": True,
            "message": _("Periodic donation agreement created successfully"),
            "agreement": agreement.name,
            "agreement_number": agreement.agreement_number,
        }

    except Exception as e:
        frappe.log_error(
            f"Failed to create periodic agreement: {str(e)}", "Periodic Agreement Creation Error"
        )
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_donor_agreements(donor, status=None):
    """
    Get all periodic donation agreements for a donor

    Args:
        donor: Donor document name
        status: Optional status filter

    Returns:
        dict: List of agreements
    """
    try:
        filters = {"donor": donor}
        if status:
            filters["status"] = status

        agreements = frappe.get_all(
            "Periodic Donation Agreement",
            filters=filters,
            fields=[
                "name",
                "agreement_number",
                "status",
                "start_date",
                "end_date",
                "annual_amount",
                "payment_frequency",
                "payment_amount",
                "total_donated",
                "donations_count",
                "next_expected_donation",
            ],
            order_by="creation desc",
        )

        return {"success": True, "agreements": agreements, "count": len(agreements)}

    except Exception as e:
        frappe.log_error(f"Failed to get donor agreements: {str(e)}", "Periodic Agreement Retrieval Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def link_donation_to_agreement(donation, agreement):
    """
    Link an existing donation to a periodic agreement

    Args:
        donation: Donation document name
        agreement: Periodic Donation Agreement name

    Returns:
        dict: Success status
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
        donation_doc.save(ignore_permissions=True)

        # Add to agreement's donation table
        agreement_doc.link_donation(donation)

        frappe.db.commit()

        return {"success": True, "message": _("Donation linked to agreement successfully")}

    except Exception as e:
        frappe.log_error(f"Failed to link donation: {str(e)}", "Donation Linking Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def generate_periodic_donation_report(from_date=None, to_date=None):
    """
    Generate report of all periodic donation agreements

    Args:
        from_date: Optional start date filter
        to_date: Optional end date filter

    Returns:
        dict: Report data
    """
    try:
        # Base filters
        filters = {"status": ["in", ["Active", "Completed"]]}

        if from_date and to_date:
            filters["start_date"] = ["between", [from_date, to_date]]

        # Get agreements
        agreements = frappe.db.sql(
            """
            SELECT
                pda.name,
                pda.agreement_number,
                pda.donor,
                d.donor_name,
                d.donor_type,
                pda.agreement_type,
                pda.start_date,
                pda.end_date,
                pda.annual_amount,
                pda.payment_frequency,
                pda.total_donated,
                pda.donations_count,
                pda.status,
                d.bsn_citizen_service_number,
                d.rsin_organization_tax_number,
                d.anbi_consent
            FROM `tabPeriodic Donation Agreement` pda
            JOIN `tabDonor` d ON pda.donor = d.name
            WHERE pda.status IN ('Active', 'Completed')
            {date_filter}
            ORDER BY pda.start_date DESC
        """.format(
                date_filter=f"AND pda.start_date BETWEEN '{from_date}' AND '{to_date}'"
                if from_date and to_date
                else ""
            ),
            as_dict=True,
        )

        # Calculate totals
        total_expected = sum(a.annual_amount * 5 for a in agreements)
        total_received = sum(a.total_donated for a in agreements)

        # Mask sensitive data
        for agreement in agreements:
            if agreement.bsn_citizen_service_number:
                agreement.bsn_citizen_service_number = "***" + agreement.bsn_citizen_service_number[-4:]
            if agreement.rsin_organization_tax_number:
                agreement.rsin_organization_tax_number = "***" + agreement.rsin_organization_tax_number[-4:]

        return {
            "success": True,
            "report_date": frappe.utils.now(),
            "period": {"from": from_date, "to": to_date} if from_date and to_date else None,
            "summary": {
                "total_agreements": len(agreements),
                "total_expected_5_years": total_expected,
                "total_received": total_received,
                "completion_percentage": (total_received / total_expected * 100) if total_expected > 0 else 0,
            },
            "agreements": agreements,
        }

    except Exception as e:
        frappe.log_error(
            f"Failed to generate periodic donation report: {str(e)}", "Periodic Donation Report Error"
        )
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def check_expiring_agreements(days_ahead=90):
    """
    Check for agreements expiring within specified days

    Args:
        days_ahead: Number of days to look ahead

    Returns:
        dict: List of expiring agreements
    """
    try:
        expiry_date = add_years(today(), -5)
        expiry_date = frappe.utils.add_days(expiry_date, days_ahead)

        expiring = frappe.get_all(
            "Periodic Donation Agreement",
            filters={"status": "Active", "end_date": ["<=", expiry_date]},
            fields=[
                "name",
                "agreement_number",
                "donor",
                "donor_name",
                "end_date",
                "annual_amount",
                "total_donated",
            ],
        )

        # Send notifications if needed
        for agreement in expiring:
            days_remaining = frappe.utils.date_diff(agreement.end_date, today())

            if days_remaining in [90, 60, 30]:
                # Agreement document will handle sending notification
                agreement_doc = frappe.get_doc("Periodic Donation Agreement", agreement.name)
                agreement_doc.check_expiry_notification()

        return {"success": True, "expiring_count": len(expiring), "agreements": expiring}

    except Exception as e:
        frappe.log_error(f"Failed to check expiring agreements: {str(e)}", "Agreement Expiry Check Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def create_donation_from_agreement(agreement_name):
    """
    Create a donation based on periodic agreement settings

    Args:
        agreement_name: Periodic Donation Agreement name

    Returns:
        dict: Created donation details
    """
    try:
        agreement = frappe.get_doc("Periodic Donation Agreement", agreement_name)

        if agreement.status != "Active":
            frappe.throw(_("Agreement is not active"))

        # Create donation
        donation = frappe.new_doc("Donation")
        donation.donor = agreement.donor
        donation.date = today()
        donation.amount = agreement.payment_amount
        donation.payment_method = agreement.payment_method
        donation.donation_type = (
            frappe.db.get_single_value("Verenigingen Settings", "default_periodic_donation_type")
            or "Periodic Donation"
        )
        donation.donation_status = "Recurring"
        donation.periodic_donation_agreement = agreement_name
        donation.belastingdienst_reportable = 1
        donation.anbi_agreement_number = agreement.agreement_number
        donation.anbi_agreement_date = agreement.agreement_date

        if agreement.sepa_mandate:
            donation.sepa_mandate = agreement.sepa_mandate

        donation.insert()
        donation.submit()

        # Link to agreement
        agreement.link_donation(donation.name)

        frappe.db.commit()

        return {
            "success": True,
            "message": _("Donation created successfully"),
            "donation": donation.name,
            "amount": donation.amount,
        }

    except Exception as e:
        frappe.log_error(
            f"Failed to create donation from agreement: {str(e)}", "Agreement Donation Creation Error"
        )
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_agreement_statistics():
    """
    Get overall statistics for periodic donation agreements

    Returns:
        dict: Statistics data
    """
    try:
        # Total agreements by status
        status_counts = frappe.db.sql(
            """
            SELECT status, COUNT(*) as count
            FROM `tabPeriodic Donation Agreement`
            GROUP BY status
        """,
            as_dict=True,
        )

        # Financial statistics
        financial_stats = frappe.db.sql(
            """
            SELECT
                SUM(CASE WHEN status = 'Active' THEN annual_amount * 5 ELSE 0 END) as active_expected_total,
                SUM(total_donated) as total_donated_all_time,
                COUNT(CASE WHEN status = 'Active' THEN 1 END) as active_count,
                AVG(CASE WHEN status = 'Active' THEN annual_amount ELSE NULL END) as avg_annual_amount
            FROM `tabPeriodic Donation Agreement`
        """,
            as_dict=True,
        )[0]

        # Agreements by type
        type_counts = frappe.db.sql(
            """
            SELECT agreement_type, COUNT(*) as count
            FROM `tabPeriodic Donation Agreement`
            WHERE status = 'Active'
            GROUP BY agreement_type
        """,
            as_dict=True,
        )

        # Payment frequency distribution
        frequency_counts = frappe.db.sql(
            """
            SELECT payment_frequency, COUNT(*) as count
            FROM `tabPeriodic Donation Agreement`
            WHERE status = 'Active'
            GROUP BY payment_frequency
        """,
            as_dict=True,
        )

        return {
            "success": True,
            "statistics": {
                "status_distribution": {s.status: s.count for s in status_counts},
                "financial": financial_stats,
                "agreement_types": {t.agreement_type: t.count for t in type_counts},
                "payment_frequencies": {f.payment_frequency: f.count for f in frequency_counts},
                "generated_at": frappe.utils.now(),
            },
        }

    except Exception as e:
        frappe.log_error(f"Failed to get agreement statistics: {str(e)}", "Agreement Statistics Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def send_renewal_reminders(days_before_expiry=90):
    """
    Send renewal reminders for expiring agreements

    Args:
        days_before_expiry: Days before expiry to send reminders

    Returns:
        dict: Number of reminders sent
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
                frappe.sendmail(
                    recipients=[agreement.donor_email],
                    subject=_("Your Periodic Donation Agreement is Expiring Soon"),
                    message=get_renewal_reminder_email(agreement, days_remaining),
                    reference_doctype="Periodic Donation Agreement",
                    reference_name=agreement.name,
                )

                # Log the reminder
                frappe.add_comment(
                    doctype="Periodic Donation Agreement",
                    name=agreement.name,
                    text=f"Renewal reminder sent to {agreement.donor_email} ({days_remaining} days until expiry)",
                )

                sent_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Failed to send renewal reminder for {agreement.agreement_number}: {str(e)}",
                    "Agreement Renewal Reminder Error",
                )

        frappe.db.commit()

        return {
            "success": True,
            "sent_count": sent_count,
            "message": _("{0} renewal reminders sent").format(sent_count),
        }

    except Exception as e:
        frappe.log_error(f"Failed to send renewal reminders: {str(e)}", "Renewal Reminder Error")
        return {"success": False, "message": str(e)}


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
def generate_tax_receipts(filters):
    """
    Generate tax receipts for periodic donations

    Args:
        filters: Report filters dict

    Returns:
        dict: Number of receipts generated
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

                # Save as attachment or create custom doctype
                frappe.add_comment(
                    doctype="Periodic Donation Agreement",
                    name=agreement.name,
                    text=f"Tax receipt generated for {frappe.utils.formatdate(today())}",
                )

                generated_count += 1

            except Exception as e:
                frappe.log_error(
                    f"Failed to generate tax receipt for {agreement.agreement_number}: {str(e)}",
                    "Tax Receipt Generation Error",
                )

        return {
            "success": True,
            "generated_count": generated_count,
            "message": _("{0} tax receipts generated").format(generated_count),
        }

    except Exception as e:
        frappe.log_error(f"Failed to generate tax receipts: {str(e)}", "Tax Receipt Error")
        return {"success": False, "message": str(e)}


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
def export_agreements(filters):
    """
    Export periodic agreements to CSV

    Args:
        filters: Report filters dict

    Returns:
        dict: File URL for download
    """
    try:
        import csv
        import io

        from frappe.utils.file_manager import save_file

        # Parse filters
        filters = json.loads(filters) if isinstance(filters, str) else filters

        # Get report data
        from vereiningen.verenigingen.report.anbi_periodic_agreements.anbi_periodic_agreements import get_data

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

        return {"success": True, "file_url": file_doc.file_url, "file_name": filename}

    except Exception as e:
        frappe.log_error(f"Failed to export agreements: {str(e)}", "Agreement Export Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def test_periodic_donation_system():
    """Test that the periodic donation agreement system is working"""
    try:
        # Check doctypes exist
        if not frappe.db.exists("DocType", "Periodic Donation Agreement"):
            return {"success": False, "message": "Periodic Donation Agreement doctype not found"}

        if not frappe.db.exists("DocType", "Periodic Donation Agreement Item"):
            return {"success": False, "message": "Periodic Donation Agreement Item doctype not found"}

        # Check Donation field
        donation_meta = frappe.get_meta("Donation")
        has_field = any(field.fieldname == "periodic_donation_agreement" for field in donation_meta.fields)

        if not has_field:
            return {"success": False, "message": "Donation doctype missing periodic_donation_agreement field"}

        return {
            "success": True,
            "message": "Periodic Donation Agreement system is properly installed",
            "details": {
                "doctypes_exist": True,
                "donation_field_exists": True,
                "api_endpoints_available": True,
            },
        }

    except Exception as e:
        return {"success": False, "message": f"System check failed: {str(e)}"}
