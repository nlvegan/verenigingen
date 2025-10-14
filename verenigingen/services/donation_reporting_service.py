"""
Donation Reporting Service

Handles all donation reporting and analytics operations.
Extracted from the Donation DocType controller to follow service-oriented architecture.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class DonationReportingService:
    """Service for handling donation reporting and analytics"""

    def __init__(self):
        self.logger = frappe.logger()

    def get_anbi_donations_for_reporting(self, from_date: str, to_date: str) -> List[Dict[str, Any]]:
        """
        Get all ANBI donations requiring Belastingdienst reporting

        Note: This queries donations with ANBI agreement numbers. For comprehensive
        ANBI reporting, you should use the ANBI Donation Agreement DocType which
        provides full compliance tracking.

        Args:
            from_date: Start date for report period
            to_date: End date for report period

        Returns:
            List of donation report data dictionaries
        """
        # Query donations that have ANBI agreement numbers (indicating ANBI eligibility)
        donations = frappe.get_all(
            "Donation",
            filters={
                "anbi_agreement_number": ["is", "set"],
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
            ],
        )

        report_data = []
        for donation in donations:
            # Use the fields we already fetched to avoid N+1 query
            anbi_data = self._generate_anbi_report_data_from_dict(donation)
            if anbi_data:
                report_data.append(anbi_data)

        return report_data

    def get_donations_by_chapter(
        self, chapter: str, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get all donations earmarked for a specific chapter

        Args:
            chapter: Chapter ID
            from_date: Optional start date filter
            to_date: Optional end date filter

        Returns:
            Dictionary with donations list and summary totals
        """
        if not DocumentExistenceValidator.check_document_exists("Chapter", chapter):
            frappe.throw(_("Chapter {0} does not exist").format(chapter))

        filters = {"chapter_reference": chapter, "donation_purpose_type": "Chapter", "docstatus": 1}

        if from_date and to_date:
            filters["donation_date"] = ["between", [from_date, to_date]]

        donations = frappe.get_all(
            "Donation",
            filters=filters,
            fields=["name", "donor", "donation_date", "amount", "donation_type", "paid"],
            order_by="donation_date desc",
        )

        total_amount = sum(d.amount for d in donations if d.amount)
        paid_amount = sum(d.amount for d in donations if d.amount and d.paid)

        return {
            "donations": donations,
            "total_amount": total_amount,
            "paid_amount": paid_amount,
            "outstanding_amount": total_amount - paid_amount,
            "count": len(donations),
        }

    def get_donations_by_campaign(
        self, campaign: str, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get all donations for a specific campaign

        Args:
            campaign: Campaign ID
            from_date: Optional start date filter
            to_date: Optional end date filter

        Returns:
            Dictionary with donations list and summary totals
        """
        filters = {"campaign": campaign, "donation_purpose_type": "Campaign", "docstatus": 1}

        if from_date and to_date:
            filters["donation_date"] = ["between", [from_date, to_date]]

        donations = frappe.get_all(
            "Donation",
            filters=filters,
            fields=["name", "donor", "donation_date", "amount", "donation_type", "paid"],
            order_by="donation_date desc",
        )

        total_amount = sum(d.amount for d in donations if d.amount)
        paid_amount = sum(d.amount for d in donations if d.amount and d.paid)

        return {
            "donations": donations,
            "total_amount": total_amount,
            "paid_amount": paid_amount,
            "outstanding_amount": total_amount - paid_amount,
            "count": len(donations),
        }

    def get_donation_summary_by_purpose(
        self, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get donation summary grouped by purpose type

        Args:
            from_date: Optional start date filter
            to_date: Optional end date filter

        Returns:
            Dictionary with summary data by purpose type
        """
        filters = {"docstatus": 1}

        if from_date and to_date:
            filters["donation_date"] = ["between", [from_date, to_date]]

        donations = frappe.get_all(
            "Donation",
            filters=filters,
            fields=["donation_purpose_type", "amount", "paid", "chapter_reference", "campaign"],
        )

        summary = {
            "General": {"total": 0, "paid": 0, "count": 0},
            "Campaign": {"total": 0, "paid": 0, "count": 0, "campaigns": {}},
            "Chapter": {"total": 0, "paid": 0, "count": 0, "chapters": {}},
            "Specific Goal": {"total": 0, "paid": 0, "count": 0},
        }

        for donation in donations:
            purpose = donation.donation_purpose_type or "General"
            amount = donation.amount or 0

            if purpose in summary:
                summary[purpose]["total"] += amount
                summary[purpose]["count"] += 1
                if donation.paid:
                    summary[purpose]["paid"] += amount

                # Track individual campaigns and chapters
                if purpose == "Campaign" and donation.campaign:
                    if donation.campaign not in summary["Campaign"]["campaigns"]:
                        summary["Campaign"]["campaigns"][donation.campaign] = {
                            "total": 0,
                            "paid": 0,
                            "count": 0,
                        }
                    summary["Campaign"]["campaigns"][donation.campaign]["total"] += amount
                    summary["Campaign"]["campaigns"][donation.campaign]["count"] += 1
                    if donation.paid:
                        summary["Campaign"]["campaigns"][donation.campaign]["paid"] += amount

                elif purpose == "Chapter" and donation.chapter_reference:
                    if donation.chapter_reference not in summary["Chapter"]["chapters"]:
                        summary["Chapter"]["chapters"][donation.chapter_reference] = {
                            "total": 0,
                            "paid": 0,
                            "count": 0,
                        }
                    summary["Chapter"]["chapters"][donation.chapter_reference]["total"] += amount
                    summary["Chapter"]["chapters"][donation.chapter_reference]["count"] += 1
                    if donation.paid:
                        summary["Chapter"]["chapters"][donation.chapter_reference]["paid"] += amount

        return summary

    def get_donation_accounting_summary(
        self, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get donation accounting summary with GL account details

        Args:
            from_date: Optional start date filter
            to_date: Optional end date filter

        Returns:
            Dictionary with accounting summary and GL entries
        """
        filters = {"docstatus": 1, "paid": 1}

        if from_date and to_date:
            filters["donation_date"] = ["between", [from_date, to_date]]

        donations = frappe.get_all(
            "Donation",
            filters=filters,
            fields=[
                "name",
                "amount",
                "donation_purpose_type",
                "chapter_reference",
                "campaign",
                "company",
            ],
        )

        accounting_summary = {"total_donations": 0, "by_purpose": {}, "gl_entries": []}

        for donation in donations:
            amount = flt(donation.amount)
            accounting_summary["total_donations"] += amount

            purpose = donation.donation_purpose_type or "General"
            if purpose not in accounting_summary["by_purpose"]:
                accounting_summary["by_purpose"][purpose] = 0
            accounting_summary["by_purpose"][purpose] += amount

            # Get related GL entries for this donation
            gl_entries = frappe.get_all(
                "GL Entry",
                filters={"voucher_no": donation.name, "voucher_type": "Payment Entry"},
                fields=["account", "debit", "credit", "posting_date"],
            )

            for gl in gl_entries:
                gl["donation"] = donation.name
                gl["purpose"] = purpose
                accounting_summary["gl_entries"].append(gl)

        return accounting_summary

    def create_donation_allocation_report(
        self, chapter: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create detailed allocation report for chapter or overall donations

        Args:
            chapter: Optional chapter filter
            from_date: Optional start date filter
            to_date: Optional end date filter

        Returns:
            Dictionary with detailed donation allocation report
        """
        filters = {"docstatus": 1}

        if chapter:
            filters["chapter_reference"] = chapter
            filters["donation_purpose_type"] = "Chapter"

        if from_date and to_date:
            filters["donation_date"] = ["between", [from_date, to_date]]

        donations = frappe.get_all(
            "Donation",
            filters=filters,
            fields=[
                "name",
                "donor",
                "donation_date",
                "amount",
                "paid",
                "donation_purpose_type",
                "chapter_reference",
                "campaign",
                "specific_goal_description",
            ],
        )

        # Get donor details
        for donation in donations:
            if donation.donor:
                donor_doc = frappe.get_doc("Donor", donation.donor)
                donation["donor_name"] = getattr(donor_doc, "donor_name", "")
                donation["donor_email"] = getattr(donor_doc, "donor_email", "")

        report = {
            "donations": donations,
            "summary": {
                "total_amount": sum(d.amount for d in donations if d.amount),
                "paid_amount": sum(d.amount for d in donations if d.amount and d.paid),
                "outstanding_amount": sum(d.amount for d in donations if d.amount and not d.paid),
                "count": len(donations),
            },
            "filters_applied": {"chapter": chapter, "from_date": from_date, "to_date": to_date},
        }

        return report

    def _generate_anbi_report_data_from_dict(self, donation_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generate ANBI report data from donation dictionary (optimized to avoid N+1 queries)

        Args:
            donation_dict: Donation data dictionary from frappe.get_all()

        Returns:
            ANBI report data dictionary or None if not reportable
        """
        if not donation_dict.get("anbi_agreement_number"):
            return None

        # Fetch donor info separately for this donation
        donor_doc = frappe.get_doc("Donor", donation_dict["donor"])

        return {
            "donation_id": donation_dict["name"],
            "anbi_agreement_number": donation_dict["anbi_agreement_number"],
            "anbi_agreement_date": donation_dict.get("anbi_agreement_date"),
            "donation_date": donation_dict["donation_date"],
            "amount": donation_dict["amount"],
            "donor_name": donor_doc.donor_name,
            "donor_email": getattr(donor_doc, "donor_email", ""),
            "donation_type": donation_dict.get("donation_type"),
        }


# Whitelisted API methods that delegate to the service
@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_anbi_donations_for_reporting(from_date: str, to_date: str):
    """API: Get ANBI donations for Belastingdienst reporting"""
    service = DonationReportingService()
    return service.get_anbi_donations_for_reporting(from_date, to_date)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donations_by_chapter(chapter: str, from_date: str = None, to_date: str = None):
    """API: Get donations earmarked for a specific chapter"""
    service = DonationReportingService()
    return service.get_donations_by_chapter(chapter, from_date, to_date)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donations_by_campaign(campaign: str, from_date: str = None, to_date: str = None):
    """API: Get donations for a specific campaign"""
    service = DonationReportingService()
    return service.get_donations_by_campaign(campaign, from_date, to_date)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donation_summary_by_purpose(from_date: str = None, to_date: str = None):
    """API: Get donation summary grouped by purpose type"""
    service = DonationReportingService()
    return service.get_donation_summary_by_purpose(from_date, to_date)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donation_accounting_summary(from_date: str = None, to_date: str = None):
    """API: Get donation accounting summary with GL entries"""
    service = DonationReportingService()
    return service.get_donation_accounting_summary(from_date, to_date)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def create_donation_allocation_report(chapter: str = None, from_date: str = None, to_date: str = None):
    """API: Create detailed donation allocation report"""
    service = DonationReportingService()
    return service.create_donation_allocation_report(chapter, from_date, to_date)
