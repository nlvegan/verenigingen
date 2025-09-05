"""
Donation Financial Operations Service

Handles all financial operations for donations including payment entries,
sales invoices, and earmarking journal entries.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


class DonationFinancialService:
    """Service for handling donation financial operations"""

    def __init__(self, donation_doc):
        self.donation = donation_doc
        self.logger = frappe.logger()

    def process_financial_entries(self) -> Dict[str, Any]:
        """
        Process all financial entries for a donation

        Returns:
            Dict with processing results
        """
        results = {}

        # Create sales invoice if needed
        if self._should_create_sales_invoice():
            try:
                sales_invoice = self.create_sales_invoice()
                results["sales_invoice"] = sales_invoice.name
            except Exception as e:
                results["sales_invoice_error"] = str(e)
                self.logger.error(f"Sales invoice creation failed: {str(e)}")

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

    def create_sales_invoice(self) -> Any:
        """Create sales invoice for the donation"""
        # Get or create customer from donor
        customer = self._get_or_create_customer_from_donor()
        if not customer:
            frappe.throw(_("Cannot create sales invoice without customer"))

        # Create sales invoice
        sales_invoice = frappe.new_doc("Sales Invoice")
        sales_invoice.company = self.donation.company
        sales_invoice.customer = customer.name
        sales_invoice.posting_date = self.donation.donation_date or nowdate()
        sales_invoice.due_date = self.donation.donation_date or nowdate()

        # Set territory
        sales_invoice.territory = self._get_default_territory()

        # Add donation as line item
        sales_invoice.append(
            "items",
            {
                "item_code": self._get_donation_item_code(),
                "item_name": f"Donation - {self.donation.donation_type}",
                "description": f"Donation: {self.donation.donation_purpose or 'General'}",
                "qty": 1,
                "rate": flt(self.donation.amount),
                "amount": flt(self.donation.amount),
            },
        )

        # Set campaign dimension if applicable
        if self.donation.campaign:
            campaign_dimension = self._get_campaign_accounting_dimension()
            if campaign_dimension:
                for item in sales_invoice.items:
                    setattr(item, campaign_dimension["fieldname"], self.donation.campaign)

        sales_invoice.insert()
        sales_invoice.submit()

        return sales_invoice

    def create_payment_entry_for_sales_invoice(self, date: Optional[str] = None) -> Any:
        """Create payment entry for the donation's sales invoice"""
        # Find the sales invoice for this donation
        sales_invoices = frappe.get_all("Sales Invoice", filters={"docstatus": 1}, fields=["name"])

        # Filter by donation reference (this would need to be added as a custom field)
        sales_invoice = None
        for si in sales_invoices:
            si_doc = frappe.get_doc("Sales Invoice", si.name)
            # Check if this SI is for our donation (by amount and customer matching)
            if (
                flt(si_doc.grand_total) == flt(self.donation.amount)
                and si_doc.customer == self._get_customer_name()
            ):
                sales_invoice = si_doc
                break

        if not sales_invoice:
            frappe.throw(_("Sales Invoice not found for this donation"))

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

    def _should_create_sales_invoice(self) -> bool:
        """Check if sales invoice should be created"""
        # Check settings
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        if not getattr(verenigingen_settings, "create_sales_invoice_for_donations", True):
            return False

        # Don't create for recurring donations that already have agreements
        if self.donation.is_recurring and self.donation.periodic_donation_agreement:
            return False

        return True

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
        """Get mapping of fund designations to accounts"""
        settings = frappe.get_single("Verenigingen Settings")

        # This would ideally be configurable in settings
        # For now, return default mapping
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
        existing_customer = frappe.db.get_value("Customer", {"donor_reference": self.donation.donor})
        if existing_customer:
            return frappe.get_doc("Customer", existing_customer)

        # Create new customer from donor
        donor = frappe.get_doc("Donor", self.donation.donor)

        customer = frappe.new_doc("Customer")
        customer.customer_name = donor.donor_name
        customer.customer_type = "Individual"
        customer.territory = self._get_default_territory()
        customer.customer_group = (
            frappe.db.get_single_value("Selling Settings", "customer_group") or "Individual"
        )

        # Link back to donor
        if hasattr(customer, "donor_reference"):
            customer.donor_reference = donor.name

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

        return frappe.db.get_value("Customer", {"donor_reference": self.donation.donor})

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
