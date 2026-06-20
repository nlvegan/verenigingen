"""
Donation Financial Operations Service

Handles all financial operations for donations including payment entries,
sales invoices, and earmarking journal entries.
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.services.infrastructure.base_service import StatelessService


class DonationFinancialService(StatelessService):
    """Service for handling donation financial operations"""

    def __init__(self, donation_doc=None):
        super().__init__(service_name="DonationFinancialService")
        self.donation = donation_doc

    def process_financial_entries(self) -> Dict[str, Any]:
        """
        Process all financial entries for a donation

        Returns:
            Dict with processing results
        """
        results = {}

        # Create payment tracking entry if needed
        if self._should_create_payment_entry():
            try:
                payment_tracking = self.create_payment_tracking_entry()
                results["payment_tracking"] = payment_tracking.payment_id if payment_tracking else "created"
            except Exception as e:
                results["payment_tracking_error"] = str(e)
                self.logger.error(f"Payment tracking entry creation failed: {str(e)}")

        # Create payment entry if needed
        if self._should_create_payment_entry():
            try:
                payment_entry = self.create_payment_entry_for_sales_invoice()
                results["payment_entry"] = payment_entry.name
            except Exception as e:
                results["payment_entry_error"] = str(e)
                self.logger.error(f"Payment entry creation failed: {str(e)}")

        # Create earmarking journal entry if needed
        if self._should_create_earmarking_entry():
            try:
                journal_entry = self.create_earmarking_journal_entry()
                results["journal_entry"] = journal_entry.name
            except Exception as e:
                results["journal_entry_error"] = str(e)
                self.logger.error(f"Earmarking journal entry creation failed: {str(e)}")

        return results

    def create_payment_tracking_entry(self) -> Any:
        """
        Create payment tracking entry in the Donation Payment child table

        This tracks individual payments against a donation, particularly useful
        for recurring donations that may have multiple payment attempts.
        """
        # Check if payment tracking entry already exists for this payment_id
        existing_entries = [
            entry
            for entry in getattr(self.donation, "payments", [])
            if entry.payment_id == getattr(self.donation, "payment_id", None) and self.donation.payment_id
        ]

        if existing_entries:
            self.logger.info(f"Payment tracking entry already exists for donation {self.donation.name}")
            return existing_entries[0]

        # Add payment tracking record to donation
        payment_entry = self.donation.append("payments", {})
        payment_entry.payment_date = self.donation.donation_date or nowdate()
        payment_entry.amount = flt(self.donation.amount)
        payment_entry.payment_method = getattr(self.donation, "mode_of_payment", None)
        payment_entry.payment_id = getattr(self.donation, "payment_id", None)
        payment_entry.payment_reference = getattr(self.donation, "bank_reference", None)
        payment_entry.payment_status = "Paid" if getattr(self.donation, "paid", False) else "Pending"

        # Save the donation with the payment tracking
        self.donation.save()

        return payment_entry

    def create_payment_entry_for_sales_invoice(self, date: Optional[str] = None) -> Any:
        """Create payment entry for the donation's sales invoice"""
        # Get customer for this donation
        customer_name = self._get_customer_name()
        if not customer_name:
            frappe.throw(_("Customer not found for donor {0}").format(self.donation.donor))

        # Query sales invoice directly with filters (avoids N+1 query)
        # Match by customer, amount, and unpaid status
        sales_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": customer_name,
                "grand_total": flt(self.donation.amount),
                "docstatus": 1,
                "outstanding_amount": [">", 0],  # Only unpaid invoices
            },
            fields=["name", "customer"],
            order_by="posting_date desc",
            limit=1,
        )

        if not sales_invoices:
            frappe.throw(
                _("Sales Invoice not found for donation amount {0} and customer {1}").format(
                    flt(self.donation.amount), customer_name
                )
            )

        # Load the matched sales invoice
        sales_invoice = frappe.get_doc("Sales Invoice", sales_invoices[0].name)

        # Get accounting accounts
        accounts = self._get_accounting_accounts()

        # Create payment entry
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.company = self.donation.company
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = sales_invoice.customer
        payment_entry.paid_from = accounts["receivable_account"]
        payment_entry.paid_to = accounts["cash_account"]
        payment_entry.paid_amount = flt(self.donation.amount)
        payment_entry.received_amount = flt(self.donation.amount)
        payment_entry.reference_date = date or self.donation.donation_date or nowdate()
        payment_entry.mode_of_payment = self.donation.mode_of_payment

        # Reference the sales invoice
        payment_entry.append(
            "references",
            {
                "reference_doctype": "Sales Invoice",
                "reference_name": sales_invoice.name,
                "allocated_amount": flt(self.donation.amount),
            },
        )

        # Add payment reference details
        if self.donation.payment_id:
            payment_entry.reference_no = self.donation.payment_id
        elif self.donation.bank_reference:
            payment_entry.reference_no = self.donation.bank_reference

        payment_entry.insert()
        payment_entry.submit()

        return payment_entry

    def create_earmarking_journal_entry(self, date: Optional[str] = None) -> Any:
        """Create earmarking journal entry for designated donations"""
        if not self._requires_earmarking():
            return None

        accounts = self._get_earmarking_accounts()
        if not accounts:
            frappe.throw(_("Earmarking accounts not configured"))

        # Create journal entry
        journal_entry = frappe.new_doc("Journal Entry")
        journal_entry.company = self.donation.company
        journal_entry.posting_date = date or self.donation.donation_date or nowdate()
        journal_entry.voucher_type = "Journal Entry"
        journal_entry.user_remark = f"Earmarking for donation {self.donation.name}"

        # Add accounting entries
        amount = flt(self.donation.amount)

        # Debit the source account (general donations)
        journal_entry.append(
            "accounts",
            {
                "account": accounts["source_account"],
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
            },
        )

        # Credit the destination account (earmarked fund)
        journal_entry.append(
            "accounts",
            {
                "account": accounts["destination_account"],
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
            },
        )

        # Add project dimension if applicable
        project = self._get_campaign_project()
        if project:
            for account_entry in journal_entry.accounts:
                account_entry.project = project

        journal_entry.insert()
        journal_entry.submit()

        return journal_entry

    def get_earmarking_summary(self) -> Dict[str, Any]:
        """Get summary of earmarking requirements for this donation"""
        summary = {
            "requires_earmarking": self._requires_earmarking(),
            "earmarking_type": None,
            "destination_fund": None,
            "amount": flt(self.donation.amount),
        }

        if self.donation.donation_purpose_type == "Campaign":
            summary["earmarking_type"] = "Campaign"
            summary["destination_fund"] = f"Campaign: {self.donation.campaign}"
        elif self.donation.donation_purpose_type == "Chapter":
            summary["earmarking_type"] = "Chapter"
            summary["destination_fund"] = f"Chapter: {self.donation.chapter_reference}"
        elif self.donation.fund_designation:
            summary["earmarking_type"] = "Fund Designation"
            summary["destination_fund"] = self.donation.fund_designation

        return summary

    def _should_create_payment_entry(self) -> bool:
        """Check if payment entry should be created"""
        # Only create if donation is marked as paid
        return self.donation.payment_status == "Completed"

    def _should_create_earmarking_entry(self) -> bool:
        """Check if earmarking journal entry should be created"""
        return self._requires_earmarking()

    def _requires_earmarking(self) -> bool:
        """Check if donation requires earmarking"""
        return bool(
            self.donation.donation_purpose_type in ["Campaign", "Chapter"] or self.donation.fund_designation
        )

    def _get_accounting_accounts(self) -> Dict[str, str]:
        """Get accounting accounts for donation processing"""
        settings = frappe.get_single("Verenigingen Settings")
        company_doc = frappe.get_doc("Company", self.donation.company)

        accounts = {
            "cash_account": company_doc.default_cash_account,
            "receivable_account": settings.get("default_receivable_account"),
            "income_account": settings.get("default_donation_income_account")
            or company_doc.default_income_account,
            "cost_center": company_doc.cost_center,
        }

        # Validate required accounts exist
        for account_type, account in accounts.items():
            if not account:
                frappe.throw(
                    _("Missing {0} in accounting configuration").format(
                        account_type.replace("_", " ").title()
                    )
                )

        return accounts

    def _get_earmarking_accounts(self) -> Optional[Dict[str, str]]:
        """Get earmarking-specific accounts"""
        settings = frappe.get_single("Verenigingen Settings")

        accounts = {"source_account": settings.get("general_donations_account"), "destination_account": None}

        # Determine destination account based on earmarking type
        if self.donation.donation_purpose_type == "Campaign":
            accounts["destination_account"] = settings.get("campaign_donations_account")
        elif self.donation.donation_purpose_type == "Chapter":
            accounts["destination_account"] = settings.get("chapter_donations_account")
        elif self.donation.fund_designation:
            # Map fund designations to specific accounts
            fund_account_mapping = self._get_fund_designation_accounts()
            accounts["destination_account"] = fund_account_mapping.get(self.donation.fund_designation)

        # Validate accounts are configured
        if not accounts["source_account"] or not accounts["destination_account"]:
            return None

        return accounts

    def _get_fund_designation_accounts(self) -> Dict[str, str]:
        """
        Get mapping of fund designations to accounts

        This mapping is configured via Verenigingen Settings. Each fund type
        maps to a specific GL account for proper earmarking accounting.
        """
        settings = frappe.get_single("Verenigingen Settings")

        return {
            "General Fund": settings.get("general_fund_account"),
            "Emergency Fund": settings.get("emergency_fund_account"),
            "Campaign Fund": settings.get("campaign_fund_account"),
            "Chapter Fund": settings.get("chapter_fund_account"),
            "Project Fund": settings.get("project_fund_account"),
            "Research Fund": settings.get("research_fund_account"),
        }

    def _get_or_create_customer_from_donor(self) -> Any:
        """Get or create customer record from donor"""
        if not self.donation.donor:
            return None

        # Check if customer already exists for this donor
        existing_customer = frappe.db.get_value("Customer", {"donor": self.donation.donor})
        if existing_customer:
            return frappe.get_doc("Customer", existing_customer)

        # Create new customer from donor
        donor = frappe.get_doc("Donor", self.donation.donor)

        customer = frappe.new_doc("Customer")
        customer.customer_name = donor.donor_name
        customer.customer_type = "Individual"
        customer.territory = self._get_default_territory()
        customer.customer_group = resolve_non_group_customer_group()

        # Link back to donor
        # WHY: Customer's donor link field is `donor` (custom field Customer-donor),
        # not `donor_reference` (no such column). The old guard was always False so
        # the donor link was never written; the filter queries above raised
        # "Unknown column 'donor_reference'". Mirror donor_service.link_donor_to_customer.
        customer.donor = donor.name

        # Copy contact information
        if donor.donor_email:
            customer.email_id = donor.donor_email
        if hasattr(donor, "phone") and donor.phone:
            customer.mobile_no = donor.phone

        customer.insert()
        return customer

    def _get_customer_name(self) -> Optional[str]:
        """Get customer name for this donation's donor"""
        if not self.donation.donor:
            return None

        return frappe.db.get_value("Customer", {"donor": self.donation.donor})

    def _get_default_territory(self) -> str:
        """Get default territory for customer/sales invoice"""
        return frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"

    def _get_donation_item_code(self) -> str:
        """Get item code for donation items"""
        settings = frappe.get_single("Verenigingen Settings")
        return settings.get("default_donation_item") or "DONATION"

    def _get_campaign_accounting_dimension(self) -> Optional[Dict[str, str]]:
        """Get campaign accounting dimension configuration"""
        # Check if campaign dimension is configured
        dimensions = frappe.get_all(
            "Accounting Dimension", filters={"disabled": 0}, fields=["document_type", "fieldname"]
        )

        for dim in dimensions:
            if dim.document_type == "Campaign":
                return {"fieldname": dim.fieldname}

        return None

    def _get_campaign_project(self) -> Optional[str]:
        """Get project associated with campaign"""
        if not self.donation.campaign:
            return None

        campaign = frappe.get_doc("Campaign", self.donation.campaign)
        return getattr(campaign, "project", None)

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
