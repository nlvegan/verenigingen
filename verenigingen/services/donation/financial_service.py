"""
Donation Financial Operations Service

Handles all financial operations for donations including payment entries,
sales invoices, and earmarking journal entries.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.services.infrastructure.base_service import StatelessService


class DonationFinancialService(StatelessService):
    """Service for handling donation financial operations"""

    def __init__(self, donation_doc=None):
        super().__init__(service_name="DonationFinancialService")
        self.donation = donation_doc

    def create_donation_from_bank_transfer(
        self, donor: str, amount: float, date: str, bank_reference: str, donation_type: Optional[str] = None
    ) -> Any:
        """
        Create donation from bank transfer details (payment-first architecture)

        Args:
            donor: Donor ID
            amount: Donation amount
            date: Donation date
            bank_reference: Bank transaction reference
            donation_type: Optional donation type override

        Returns:
            Created and submitted donation document
        """
        # NOTE: donation_type is accepted for backwards compatibility but the
        # Donation DocType has no donation_type column (it was removed), so the
        # value is not persisted. The previous default-path lookup of the phantom
        # "default_donation_type" Verenigingen Settings field raised a
        # ValidationError on every call without an explicit donation_type; that
        # crashing lookup has been removed. company is likewise not a Donation
        # column and is no longer written.
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor,
                "donation_date": getdate(date),
                "amount": flt(amount),
                "mode_of_payment": "Bank Transfer",
                "bank_reference": bank_reference,
                "paid": 1,
            }
        ).insert()

        donation.submit()
        # Note: Payment Entry should be created separately by bank reconciliation system
        return donation

    def create_sepa_donation(
        self,
        donor: str,
        amount: float,
        date: str,
        sepa_mandate: str,
        donation_type: Optional[str] = None,
        recurring_frequency: Optional[str] = None,
    ) -> Any:
        """
        Create donation for SEPA direct debit

        Args:
            donor: Donor ID
            amount: Donation amount
            date: Donation date
            sepa_mandate: SEPA mandate reference
            donation_type: Optional donation type override
            recurring_frequency: Optional recurring frequency

        Returns:
            Created donation document (not submitted - SEPA batch will process)
        """
        # NOTE: donation_type is accepted for backwards compatibility but is not a
        # Donation column (removed); the crashing phantom "default_donation_type"
        # settings lookup and the phantom company write have been removed. See
        # create_donation_from_bank_transfer for details.
        status = "Recurring" if recurring_frequency else "Promised"

        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor,
                "donation_date": getdate(date),
                "amount": flt(amount),
                "mode_of_payment": "SEPA Direct Debit",
                "status": status,
                "sepa_mandate": sepa_mandate,
                "recurring_frequency": recurring_frequency,
                "paid": 0,  # Will be marked paid when SEPA batch is processed
            }
        ).insert()

        return donation

    def create_chapter_donation(
        self,
        donor: str,
        amount: float,
        chapter: str,
        date: Optional[str] = None,
        donation_type: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Any:
        """
        Create a donation earmarked for a specific chapter

        Args:
            donor: Donor ID
            amount: Donation amount
            chapter: Chapter ID
            date: Optional donation date (defaults to today)
            donation_type: Optional donation type override
            notes: Optional notes

        Returns:
            Created donation document
        """
        if not frappe.db.exists("Chapter", chapter):
            frappe.throw(_("Chapter {0} does not exist").format(chapter))

        # NOTE: donation_type is accepted for backwards compatibility but is not a
        # Donation column (removed); the crashing phantom "default_donation_type"
        # settings lookup and the phantom company write have been removed.
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor,
                "donation_date": getdate(date) if date else getdate(),
                "amount": flt(amount),
                "donation_purpose_type": "Chapter",
                "chapter_reference": chapter,
                "donation_notes": notes or f"Donation earmarked for {chapter}",
                # WHY: mode_of_payment is a mandatory field on Donation. Without it
                # this whitelisted API raised MandatoryError on every call. Default
                # to "Bank Transfer" to mirror create_donation_from_bank_transfer
                # (chapter pledges are typically settled by transfer).
                "mode_of_payment": "Bank Transfer",
            }
        ).insert()

        return donation

    def reconcile_donation_accounts(self) -> Dict[str, Any]:
        """
        Reconcile donation amounts with GL entries

        Returns:
            Dict with reconciliation report including discrepancies
        """
        # Get all paid donations
        # WHY: the Donation DocType has no ``company`` column — selecting it raises
        # an OperationalError (1054 Unknown column), which broke this whitelisted
        # reconcile API on every call. ``company`` was never used in the report
        # below, so it is simply dropped. Mirrors the schema fix in
        # donor_service.get_donor_summary for the same DocType.
        donations = frappe.get_all(
            "Donation",
            filters={"paid": 1, "docstatus": 1},
            fields=["name", "amount", "donation_date"],
        )

        reconciliation_report = {
            "total_donations": 0,
            "total_gl_credits": 0,
            "discrepancies": [],
            "summary": {},
        }

        for donation in donations:
            amount = flt(donation.amount)
            reconciliation_report["total_donations"] += amount

            # Get GL entries for this donation
            # Note: Frappe GL Entry uses voucher_no/voucher_type, not reference_name/reference_type
            gl_credits = frappe.db.sql(
                """
                SELECT SUM(credit) as total_credit
                FROM `tabGL Entry`
                WHERE voucher_no = %s AND voucher_type = 'Donation'
            """,
                donation.name,
                as_dict=True,
            )

            gl_credit_amount = (
                flt(gl_credits[0].total_credit) if gl_credits and gl_credits[0].total_credit else 0
            )
            reconciliation_report["total_gl_credits"] += gl_credit_amount

            # Check for discrepancies
            if abs(amount - gl_credit_amount) > 0.01:  # Allow for minor rounding
                reconciliation_report["discrepancies"].append(
                    {
                        "donation": donation.name,
                        "donation_amount": amount,
                        "gl_amount": gl_credit_amount,
                        "difference": amount - gl_credit_amount,
                        "donation_date": donation.donation_date,
                    }
                )

        reconciliation_report["summary"] = {
            "total_difference": reconciliation_report["total_donations"]
            - reconciliation_report["total_gl_credits"],
            "discrepancy_count": len(reconciliation_report["discrepancies"]),
            "reconciliation_status": (
                "Clean" if len(reconciliation_report["discrepancies"]) == 0 else "Needs Review"
            ),
        }

        return reconciliation_report

    def _get_company_for_donations(self) -> str:
        """Get company for donation operations"""
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        if not company:
            from verenigingen.utils import get_company

            company = get_company()
        return company
