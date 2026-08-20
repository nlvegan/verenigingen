"""
Donation Reporting Service

Handles all donation reporting and analytics operations.
Extracted from the Donation DocType controller to follow service-oriented architecture.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All API methods return OperationResult with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- get_anbi_donations_for_reporting: Returns OperationResult[List[Dict]] (ANBI donations for tax reporting)
- get_donations_by_chapter: Returns OperationResult[Dict] (chapter donations with list and totals)
- get_donations_by_campaign: Returns OperationResult[Dict] (campaign donations with list and totals)
- get_donation_summary_by_purpose: Returns OperationResult[Dict] (donation summary by purpose)
- get_donation_accounting_summary: Returns OperationResult[Dict] (accounting summary with GL entries)
- create_donation_allocation_report: Returns OperationResult[Dict] (allocation report data)

Migration Status: ✅ COMPLETE (2025-11-24)
- All 6 API methods migrated to OperationResult pattern
- Comprehensive exception handling for all endpoints
- Type-safe error handling with metadata
- All high_security_api decorations preserved

DOCSTATUS PREDICATES: ``< 2``, NEVER ``= 1``
============================================
Donation is not submittable (its DocType JSON has no ``is_submittable``), so a
donation created by any normal path stays at docstatus 0 for its whole life.
Every query below used to carry a ``docstatus = 1`` predicate, which meant they
all returned nothing on every deployment (issue #350).

The fix is ``docstatus < 2``, not removal. Nothing guards ``Document._submit()``
or ``._cancel()`` on a non-submittable doctype, so both docstatus 1 and
docstatus 2 rows do exist in the wild; cancelled donations must stay out of
these totals.

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class DonationReportingService(StatelessService):
    """Service for handling donation reporting and analytics.

    Inherits from StatelessService for consistent logging, metrics, and error handling.
    """

    def __init__(self):
        super().__init__(service_name="DonationReportingService")

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
                "docstatus": ["<", 2],
            },
            # NOTE: the Donation DocType has no ``donation_type`` column —
            # selecting it raised an OperationalError (1054 Unknown column),
            # breaking this whitelisted ANBI reporting API on every call.
            # _generate_anbi_report_data_from_dict reads it via dict.get(), which
            # safely returns None, so it is simply omitted from the SELECT.
            fields=[
                "name",
                "donor",
                "donation_date",
                "amount",
                "anbi_agreement_number",
                "anbi_agreement_date",
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

        filters = {
            "chapter_reference": chapter,
            "donation_purpose_type": "Chapter",
            "docstatus": ["<", 2],
        }

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
            ],  # Donation has no donation_type column
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
        filters = {
            "campaign": campaign,
            "donation_purpose_type": "Campaign",
            "docstatus": ["<", 2],
        }

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
            ],  # Donation has no donation_type column
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
        filters = {"docstatus": ["<", 2]}

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
        filters = {"paid": 1, "docstatus": ["<", 2]}

        if from_date and to_date:
            filters["donation_date"] = ["between", [from_date, to_date]]

        # NOTE: the Donation DocType has no ``company`` column — selecting it
        # raised an OperationalError (1054 Unknown column), breaking this
        # whitelisted accounting-summary API on every call. ``company`` was never
        # used below, so it is dropped (same schema fix as elsewhere in this file
        # and donor_service).
        donations = frappe.get_all(
            "Donation",
            filters=filters,
            fields=[
                "name",
                "amount",
                "donation_purpose_type",
                "chapter_reference",
                "campaign",
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
        # NOTE: this method used to build an ORM ``filters`` dict here and then
        # never use it — the query below is raw SQL. Mutation testing for #350
        # found it: both mutants of its docstatus predicate survived, because
        # nothing reads the dict. Removed rather than left to rot as a second,
        # silently-diverging copy of the WHERE clause.

        # Use SQL to join donor data efficiently (avoids N+1 query)
        donations = frappe.db.sql(
            """
            SELECT
                d.name,
                d.donor,
                d.donation_date,
                d.amount,
                d.paid,
                d.donation_purpose_type,
                d.chapter_reference,
                d.campaign,
                d.specific_goal_description,
                don.donor_name,
                don.donor_email
            FROM `tabDonation` d
            LEFT JOIN `tabDonor` don ON d.donor = don.name
            WHERE d.docstatus < 2
                {chapter_filter}
                {date_filter}
            ORDER BY d.donation_date DESC
        """.format(
                chapter_filter=(
                    "AND d.chapter_reference = %(chapter)s AND d.donation_purpose_type = 'Chapter'"
                    if chapter
                    else ""
                ),
                date_filter=(
                    "AND d.donation_date BETWEEN %(from_date)s AND %(to_date)s"
                    if from_date and to_date
                    else ""
                ),
            ),
            {"chapter": chapter, "from_date": from_date, "to_date": to_date},
            as_dict=True,
        )

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
def get_anbi_donations_for_reporting(from_date: str, to_date: str) -> OperationResult[List[Dict[str, Any]]]:
    """
    API: Get ANBI donations for Belastingdienst reporting

    Returns:
        OperationResult[List[Dict]]: ANBI donation report data

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - High security API with REPORTING operation classification
    """
    # Validate date parameters
    try:
        getdate(from_date)
        getdate(to_date)
    except Exception:
        return OperationResult.fail(
            _("Invalid date format. Please use YYYY-MM-DD format."),
            errors=["Invalid date format provided"],
            context={"operation": "anbi_reporting", "params": {"from_date": from_date, "to_date": to_date}},
        )

    service = DonationReportingService()
    try:
        donations = service.get_anbi_donations_for_reporting(from_date, to_date)
        return OperationResult.ok(donations, message=f"Retrieved {len(donations)} ANBI donations")
    except Exception as e:
        service.logger.error(f"Error retrieving ANBI donations: {str(e)}")
        return OperationResult.fail(
            _("Unable to retrieve ANBI donations. Please contact support."),
            errors=[str(e)],
            context={"operation": "anbi_reporting", "params": {"from_date": from_date, "to_date": to_date}},
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donations_by_chapter(
    chapter: str, from_date: str = None, to_date: str = None
) -> OperationResult[Dict[str, Any]]:
    """
    API: Get donations earmarked for a specific chapter

    Returns:
        OperationResult[Dict]: Chapter donation report data with donations list and totals

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - High security API with REPORTING operation classification
    """
    # Validate date parameters if provided
    if from_date or to_date:
        try:
            if from_date:
                getdate(from_date)
            if to_date:
                getdate(to_date)
        except Exception:
            return OperationResult.fail(
                _("Invalid date format. Please use YYYY-MM-DD format."),
                errors=["Invalid date format provided"],
                context={
                    "operation": "chapter_donations",
                    "params": {"chapter": chapter, "from_date": from_date, "to_date": to_date},
                },
            )

    service = DonationReportingService()
    try:
        donations = service.get_donations_by_chapter(chapter, from_date, to_date)
        return OperationResult.ok(donations, message=f"Retrieved {donations['count']} donations for chapter")
    except Exception as e:
        service.logger.error(f"Error retrieving chapter donations: {str(e)}")
        return OperationResult.fail(
            _("Unable to retrieve chapter donations. Please contact support."),
            errors=[str(e)],
            context={
                "operation": "chapter_donations",
                "params": {"chapter": chapter, "from_date": from_date, "to_date": to_date},
            },
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donations_by_campaign(
    campaign: str, from_date: str = None, to_date: str = None
) -> OperationResult[Dict[str, Any]]:
    """
    API: Get donations for a specific campaign

    Returns:
        OperationResult[Dict]: Campaign donation report data with donations list and totals

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - High security API with REPORTING operation classification
    """
    # Validate date parameters if provided
    if from_date or to_date:
        try:
            if from_date:
                getdate(from_date)
            if to_date:
                getdate(to_date)
        except Exception:
            return OperationResult.fail(
                _("Invalid date format. Please use YYYY-MM-DD format."),
                errors=["Invalid date format provided"],
                context={
                    "operation": "campaign_donations",
                    "params": {"campaign": campaign, "from_date": from_date, "to_date": to_date},
                },
            )

    service = DonationReportingService()
    try:
        donations = service.get_donations_by_campaign(campaign, from_date, to_date)
        return OperationResult.ok(donations, message=f"Retrieved {donations['count']} donations for campaign")
    except Exception as e:
        service.logger.error(f"Error retrieving campaign donations: {str(e)}")
        return OperationResult.fail(
            _("Unable to retrieve campaign donations. Please contact support."),
            errors=[str(e)],
            context={
                "operation": "campaign_donations",
                "params": {"campaign": campaign, "from_date": from_date, "to_date": to_date},
            },
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donation_summary_by_purpose(
    from_date: str = None, to_date: str = None
) -> OperationResult[Dict[str, Any]]:
    """
    API: Get donation summary grouped by purpose type

    Returns:
        OperationResult[Dict]: Donation summary by purpose type

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - High security API with REPORTING operation classification
    """
    # Validate date parameters if provided
    if from_date or to_date:
        try:
            if from_date:
                getdate(from_date)
            if to_date:
                getdate(to_date)
        except Exception:
            return OperationResult.fail(
                _("Invalid date format. Please use YYYY-MM-DD format."),
                errors=["Invalid date format provided"],
                context={
                    "operation": "summary_by_purpose",
                    "params": {"from_date": from_date, "to_date": to_date},
                },
            )

    service = DonationReportingService()
    try:
        summary = service.get_donation_summary_by_purpose(from_date, to_date)
        return OperationResult.ok(summary, message="Retrieved donation summary by purpose")
    except Exception as e:
        service.logger.error(f"Error retrieving donation summary: {str(e)}")
        return OperationResult.fail(
            _("Unable to retrieve donation summary. Please contact support."),
            errors=[str(e)],
            context={
                "operation": "summary_by_purpose",
                "params": {"from_date": from_date, "to_date": to_date},
            },
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donation_accounting_summary(
    from_date: str = None, to_date: str = None
) -> OperationResult[Dict[str, Any]]:
    """
    API: Get donation accounting summary with GL entries

    Returns:
        OperationResult[Dict]: Accounting summary with GL entry data

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - High security API with REPORTING operation classification
    """
    # Validate date parameters if provided
    if from_date or to_date:
        try:
            if from_date:
                getdate(from_date)
            if to_date:
                getdate(to_date)
        except Exception:
            return OperationResult.fail(
                _("Invalid date format. Please use YYYY-MM-DD format."),
                errors=["Invalid date format provided"],
                context={
                    "operation": "accounting_summary",
                    "params": {"from_date": from_date, "to_date": to_date},
                },
            )

    service = DonationReportingService()
    try:
        summary = service.get_donation_accounting_summary(from_date, to_date)
        return OperationResult.ok(summary, message="Retrieved donation accounting summary")
    except Exception as e:
        service.logger.error(f"Error retrieving accounting summary: {str(e)}")
        return OperationResult.fail(
            _("Unable to retrieve accounting summary. Please contact support."),
            errors=[str(e)],
            context={
                "operation": "accounting_summary",
                "params": {"from_date": from_date, "to_date": to_date},
            },
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def create_donation_allocation_report(
    chapter: str = None, from_date: str = None, to_date: str = None
) -> OperationResult[Dict[str, Any]]:
    """
    API: Create detailed donation allocation report

    Returns:
        OperationResult[Dict]: Donation allocation report data

    Note:
        - Never throws exceptions (returns failed OperationResult)
        - High security API with REPORTING operation classification
    """
    # Validate date parameters if provided
    if from_date or to_date:
        try:
            if from_date:
                getdate(from_date)
            if to_date:
                getdate(to_date)
        except Exception:
            return OperationResult.fail(
                _("Invalid date format. Please use YYYY-MM-DD format."),
                errors=["Invalid date format provided"],
                context={
                    "operation": "allocation_report",
                    "params": {"chapter": chapter, "from_date": from_date, "to_date": to_date},
                },
            )

    service = DonationReportingService()
    try:
        report = service.create_donation_allocation_report(chapter, from_date, to_date)
        return OperationResult.ok(report, message="Created donation allocation report")
    except Exception as e:
        service.logger.error(f"Error creating allocation report: {str(e)}")
        return OperationResult.fail(
            _("Unable to create allocation report. Please contact support."),
            errors=[str(e)],
            context={
                "operation": "allocation_report",
                "params": {"chapter": chapter, "from_date": from_date, "to_date": to_date},
            },
        )
