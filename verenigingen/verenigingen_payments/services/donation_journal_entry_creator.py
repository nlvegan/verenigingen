"""
Donation Journal Entry Creator Service

Creates Journal Entries for donation payments. This is the correct accounting
treatment for donations (not Payment Entries, which are for receivables).

Architecture:
    Mollie Webhook → Bank Transaction → Journal Entry → Record Updates
                     (deposit)          (Debit: Mollie Clearing, Credit: Donation Income)

The Bank Transaction represents the bank statement line item.
The Journal Entry records the actual accounting entry (income recognition).
"""

from typing import Any, Dict, Optional

import frappe
from frappe.utils import flt, getdate, nowdate

from verenigingen.utils.secure_operations import secure_document_operation


class DonationJournalEntryCreator:
    """
    Service for creating Journal Entries for donation payments.

    Uses the correct accounting treatment:
    - Debit: Mollie Clearing Account (or cash/bank account)
    - Credit: Donation Income Account

    This is distinct from Payment Entries which handle receivables/payables.
    """

    def __init__(self):
        """Initialize with configuration from Mollie settings."""
        self._config = None

    def _resolve_company(self, donation_doc: Any) -> Optional[str]:
        """
        Resolve company for donation journal entry.

        Fallback order:
        1. donation_doc.company (if set on donation)
        2. Verenigingen Settings.company

        Returns:
            Company name or None if not resolvable
        """
        company = getattr(donation_doc, "company", None)
        if not company:
            settings = frappe.get_single("Verenigingen Settings")
            company = settings.company
            if not company:
                frappe.logger().error("No company on donation and no default in Verenigingen Settings")
                return None
        return company

    def create_from_mollie_payment(
        self,
        payment_data: Dict[str, Any],
        donation_doc: Any,
        bank_transaction_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create Journal Entry from Mollie payment for a donation.

        Args:
            payment_data: Mollie payment data dict (id, amount, paid_at, etc.)
            donation_doc: The Donation document
            bank_transaction_name: Optional Bank Transaction to link

        Returns:
            Journal Entry name if created, None on failure
        """
        payment_id = payment_data.get("id")

        # Idempotency check - avoid duplicate Journal Entries
        existing_je = self._check_existing_by_reference(payment_id)
        if existing_je:
            frappe.logger().info(f"Journal Entry already exists for {payment_id}: {existing_je}")
            # Still attempt reconciliation in case it wasn't done previously
            if bank_transaction_name:
                from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
                    get_payment_data_extractor,
                )

                extractor = get_payment_data_extractor()
                amount = extractor.extract_amount(payment_data, allow_zero=False) or 0
                self._reconcile_bank_transaction(bank_transaction_name, existing_je, flt(amount))
            return existing_je

        # Resolve company
        company = self._resolve_company(donation_doc)
        if not company:
            return None

        # Get configuration
        config = self._get_config(company)
        if config.get("error"):
            frappe.logger().error(f"Configuration error: {config['error']}")
            return None

        # Extract payment details
        from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

        extractor = get_payment_data_extractor()
        amount = extractor.extract_amount(payment_data, allow_zero=False)
        if not amount:
            frappe.logger().error(f"Invalid or zero amount for payment {payment_id}")
            return None

        # Get posting date from payment or donation
        posting_date = None
        paid_at = payment_data.get("paid_at") or payment_data.get("created_at")
        if paid_at:
            try:
                from dateutil import parser

                posting_date = parser.parse(paid_at).date()
            except (ValueError, TypeError, ImportError):
                pass
        if not posting_date:
            posting_date = donation_doc.donation_date or nowdate()

        # Create Journal Entry
        # NOTE: Customer/party info is tracked on Bank Transaction, not Journal Entry
        # (ERPNext only allows party on Receivable/Payable accounts)
        je_name = self._create_journal_entry(
            posting_date=posting_date,
            company=company,
            amount=amount,
            reference_number=payment_id,
            donation_name=donation_doc.name,
            donor_name=donation_doc.donor,
            clearing_account=config["clearing_account"],
            income_account=config["income_account"],
            cost_center=config.get("cost_center"),
            bank_transaction_name=bank_transaction_name,
        )

        # Write Journal Entry reference back to Donation record
        if je_name:
            self._update_donation_journal_entry(donation_doc.name, je_name)

        return je_name

    def create_from_dict(
        self,
        transaction_data: Dict[str, Any],
        donation_doc: Any,
    ) -> Optional[str]:
        """
        Create Journal Entry from generic transaction data.

        Args:
            transaction_data: Dict with amount, date, reference_number
            donation_doc: The Donation document

        Returns:
            Journal Entry name if created, None on failure
        """
        reference_number = transaction_data.get("reference_number", "")

        # Idempotency check
        if reference_number:
            existing_je = self._check_existing_by_reference(reference_number)
            if existing_je:
                frappe.logger().info(f"Journal Entry already exists: {existing_je}")
                return existing_je

        # Resolve company
        company = self._resolve_company(donation_doc)
        if not company:
            return None

        # Get configuration
        config = self._get_config(company)
        if config.get("error"):
            frappe.logger().error(f"Configuration error: {config['error']}")
            return None

        amount = flt(transaction_data.get("amount", 0))
        if not amount:
            frappe.logger().error("Invalid or zero amount in transaction data")
            return None

        posting_date = transaction_data.get("date")
        if isinstance(posting_date, str):
            posting_date = getdate(posting_date)
        if not posting_date:
            posting_date = donation_doc.donation_date or nowdate()

        # NOTE: Customer/party info is tracked on Bank Transaction, not Journal Entry
        je_name = self._create_journal_entry(
            posting_date=posting_date,
            company=company,
            amount=amount,
            reference_number=reference_number,
            donation_name=donation_doc.name,
            donor_name=donation_doc.donor,
            clearing_account=config["clearing_account"],
            income_account=config["income_account"],
            cost_center=config.get("cost_center"),
        )

        # Write Journal Entry reference back to Donation record
        if je_name:
            self._update_donation_journal_entry(donation_doc.name, je_name)

        return je_name

    def _update_donation_journal_entry(self, donation_name: str, journal_entry_name: str) -> None:
        """
        Update the Donation record with the Journal Entry reference.

        Args:
            donation_name: Name of the Donation record
            journal_entry_name: Name of the Journal Entry to link
        """
        try:
            frappe.db.set_value(
                "Donation",
                donation_name,
                "journal_entry",
                journal_entry_name,
                update_modified=False,
            )
            frappe.logger().info(f"Updated Donation {donation_name} with Journal Entry {journal_entry_name}")
        except Exception as e:
            frappe.logger().error(
                f"Failed to update Donation {donation_name} with Journal Entry {journal_entry_name}: {e}"
            )
            # Don't raise - JE was created successfully, just couldn't link back

    def _check_existing_by_reference(self, reference_number: str) -> Optional[str]:
        """Check if Journal Entry already exists with this reference."""
        if not reference_number:
            return None
        return frappe.db.get_value(
            "Journal Entry",
            {"cheque_no": reference_number, "docstatus": ["!=", 2]},
            "name",
        )

    def _get_config(self, company: str) -> Dict[str, Any]:
        """
        Get accounting configuration for donation journal entries.

        Returns:
            Dict with clearing_account, income_account, cost_center or error
        """
        if self._config and self._config.get("company") == company:
            return self._config

        try:
            # Get Mollie clearing account
            from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
                get_mollie_config,
            )

            mollie_config = get_mollie_config()
            clearing_account = mollie_config.get_clearing_account()

            # Get donation income account from Verenigingen Settings
            settings = frappe.get_single("Verenigingen Settings")
            income_account = settings.get("unrestricted_donation_account")

            if not income_account:
                # Fallback to company default income account
                income_account = frappe.db.get_value("Company", company, "default_income_account")

            if not income_account:
                # Last resort - find any income account
                income_account = frappe.db.get_value(
                    "Account",
                    {
                        "company": company,
                        "account_type": "Income Account",
                        "is_group": 0,
                    },
                    "name",
                )

            if not clearing_account:
                return {"error": "Mollie clearing account not configured"}
            if not income_account:
                return {"error": "Donation income account not configured"}

            # Get cost center
            cost_center = frappe.db.get_value("Company", company, "cost_center")

            self._config = {
                "company": company,
                "clearing_account": clearing_account,
                "income_account": income_account,
                "cost_center": cost_center,
            }

            return self._config

        except Exception as e:
            return {"error": str(e)}

    def _create_journal_entry(
        self,
        posting_date,
        company: str,
        amount: float,
        reference_number: str,
        donation_name: str,
        donor_name: Optional[str],
        clearing_account: str,
        income_account: str,
        cost_center: Optional[str] = None,
        bank_transaction_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create and submit Journal Entry using secure operations framework.

        Accounting entries:
            Debit:  Mollie Clearing Account (asset increases - we received money)
            Credit: Donation Income Account (income recognized)
        """
        try:
            # Build remark
            remark_parts = [f"Donation payment: {donation_name}"]
            if donor_name:
                remark_parts.append(f"Donor: {donor_name}")
            if reference_number:
                remark_parts.append(f"Ref: {reference_number}")
            user_remark = " | ".join(remark_parts)

            # Create Journal Entry
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.company = company
            je.posting_date = posting_date
            je.cheque_no = reference_number  # Journal Entry uses cheque_no for reference
            je.cheque_date = posting_date
            je.user_remark = user_remark

            # Debit entry - Mollie Clearing (we received money)
            debit_entry = {
                "account": clearing_account,
                "debit_in_account_currency": flt(amount),
                "credit_in_account_currency": 0,
                "user_remark": f"Donation received: {donation_name}",
            }
            if cost_center:
                debit_entry["cost_center"] = cost_center
            je.append("accounts", debit_entry)

            # Credit entry - Donation Income (income recognized)
            # NOTE: Party Type and Party are NOT set on income accounts - ERPNext only
            # allows party data on Receivable/Payable accounts. The donor reference is
            # tracked via user_remark and the Bank Transaction party fields instead.
            credit_entry = {
                "account": income_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": flt(amount),
                "user_remark": f"Donation income: {donation_name}"
                + (f" | Donor: {donor_name}" if donor_name else ""),
            }
            if cost_center:
                credit_entry["cost_center"] = cost_center
            je.append("accounts", credit_entry)

            # Create using secure operations framework
            create_result = secure_document_operation(
                operation="create",
                doc=je,
                justification=f"Donation Journal Entry for {donation_name} (ref: {reference_number})",
                required_permissions=["Journal Entry:create"],
                allow_system_user=True,
            )

            if not create_result.success:
                error_msg = ", ".join(create_result.errors) if create_result.errors else "Unknown error"
                frappe.logger().error(f"Failed to create Journal Entry: {error_msg}")
                return None

            je = create_result.document

            # Submit the Journal Entry
            submit_result = secure_document_operation(
                operation="submit",
                doc=je,
                justification=f"Journal Entry submission for donation {donation_name}",
                required_permissions=["Journal Entry:submit"],
                allow_system_user=True,
            )

            if submit_result.success:
                frappe.logger().info(
                    f"Created and submitted Journal Entry {je.name} for donation {donation_name}"
                )

                # Reconcile Bank Transaction with this Journal Entry
                if bank_transaction_name:
                    self._reconcile_bank_transaction(bank_transaction_name, je.name, flt(amount))
            else:
                frappe.logger().info(f"Created Journal Entry {je.name} (draft) for donation {donation_name}")

            return je.name

        except Exception as e:
            frappe.logger().error(f"Failed to create Journal Entry: {e}")
            frappe.log_error(
                f"Journal Entry creation failed for donation {donation_name}: {e}",
                "Donation Journal Entry Error",
            )
            return None

    def _reconcile_bank_transaction(
        self,
        bank_transaction_name: str,
        journal_entry_name: str,
        amount: float,
    ):
        """
        Reconcile Bank Transaction with the created Journal Entry.

        Links the Bank Transaction to the Journal Entry via payment_entries child table
        and updates the Bank Transaction status to 'Reconciled'.

        Args:
            bank_transaction_name: Name of the Bank Transaction
            journal_entry_name: Name of the Journal Entry to link
            amount: Amount to allocate
        """
        try:
            bt = frappe.get_doc("Bank Transaction", bank_transaction_name)

            # Check if already reconciled with this JE
            existing_link = next(
                (pe for pe in bt.payment_entries if pe.payment_entry == journal_entry_name),
                None,
            )
            if existing_link:
                frappe.logger().info(
                    f"Bank Transaction {bank_transaction_name} already linked to {journal_entry_name}"
                )
                return

            # Add Journal Entry to payment_entries
            bt.append(
                "payment_entries",
                {
                    "payment_document": "Journal Entry",
                    "payment_entry": journal_entry_name,
                    "allocated_amount": flt(amount),
                },
            )

            # Update status to Reconciled if fully allocated
            total_allocated = sum(flt(pe.allocated_amount) for pe in bt.payment_entries)
            if total_allocated >= flt(bt.deposit or 0):
                bt.status = "Reconciled"

            bt.save()
            frappe.db.commit()

            frappe.logger().info(
                f"Reconciled Bank Transaction {bank_transaction_name} with Journal Entry {journal_entry_name}"
            )

        except Exception as e:
            frappe.logger().error(f"Failed to reconcile Bank Transaction {bank_transaction_name}: {e}")
            # Don't raise - reconciliation failure shouldn't fail the whole operation


def get_donation_journal_entry_creator() -> DonationJournalEntryCreator:
    """Factory function to get DonationJournalEntryCreator instance."""
    return DonationJournalEntryCreator()
