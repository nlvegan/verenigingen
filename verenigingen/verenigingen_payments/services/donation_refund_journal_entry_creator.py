"""
Donation Refund Journal Entry Creator Service

Creates Journal Entries for donation refunds. This is the correct accounting
treatment for refunds (reversing the original donation income entry).

Architecture:
    Mollie Refund Webhook → Bank Transaction → Journal Entry → Record Updates
                            (withdrawal)       (Debit: Donation Income, Credit: Mollie Clearing)

The Bank Transaction represents the bank statement line item (withdrawal).
The Journal Entry records the actual accounting entry (income reversal).
"""

from typing import Any, Dict, Optional

import frappe
from frappe.utils import flt, getdate, nowdate

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.verenigingen_payments.services.journal_entry_booking_support import (
    discard_unposted_journal_entry,
    find_journal_entry_by_reference,
    reconcile_bank_transaction_with_journal_entry,
)


class DonationRefundJournalEntryCreator:
    """
    Service for creating Journal Entries for donation refunds.

    Uses the correct accounting treatment (reverse of donation):
    - Debit: Donation Income Account (reduce income)
    - Credit: Mollie Clearing Account (money leaves)

    This mirrors DonationJournalEntryCreator but with reversed accounts.
    """

    def __init__(self):
        """Initialize with configuration from Mollie settings."""
        self._config = None

    def _resolve_company(self, donation_doc: Any) -> Optional[str]:
        """
        Resolve company for donation refund journal entry.

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

    def create_refund_journal_entry(
        self,
        refund_id: str,
        refund_amount: float,
        refund_date: Optional[str],
        donation_doc: Any,
        original_payment_id: str,
        bank_transaction_name: Optional[str] = None,
        reversal_type: str = "refund",
        description: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create Journal Entry for a Mollie reversal (refund or chargeback).

        Args:
            refund_id: Mollie reversal ID (e.g., re_xxxxx / chb_xxxxx)
            refund_amount: Reversal amount (positive number)
            refund_date: Date of the reversal (ISO format string or None)
            donation_doc: The Donation document
            original_payment_id: Original Mollie payment ID (e.g., tr_xxxxx)
            bank_transaction_name: Optional Bank Transaction to link
            reversal_type: "refund" (default) or "chargeback". This lands in the
                reference key, so a chargeback is not filed under a refund key --
                which would make the two collide on one payment and hide one of
                them from the idempotency lookup. It also lands in the narration:
                a chargeback filed under a reference key of its own but described
                as a "REFUND" is still unreadable to whoever reconciles it.
            description: Caller-built detail, for a chargeback the Mollie reason
                code and text. Recorded in the remark; a chargeback's reason is
                the single most useful thing on the entry and was being dropped.

        Returns:
            Journal Entry name if created, None on failure
        """
        # Build reference number that includes both original payment and reversal ID.
        # Shared with every other reversal route so they agree on one key (#370).
        from verenigingen.verenigingen_payments.mollie.utils.reversal_idempotency import (
            build_reversal_key,
        )

        reference_number = build_reversal_key(original_payment_id, reversal_type, refund_id)

        # Idempotency check - avoid duplicate Journal Entries
        existing_je = find_journal_entry_by_reference(reference_number)
        if existing_je:
            frappe.logger().info(f"Refund Journal Entry already exists for {refund_id}: {existing_je}")
            # Still attempt reconciliation in case it wasn't done previously
            if bank_transaction_name:
                reconcile_bank_transaction_with_journal_entry(
                    bank_transaction_name, existing_je, flt(refund_amount)
                )
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

        # Parse refund date
        posting_date = None
        if refund_date:
            try:
                if isinstance(refund_date, str):
                    from dateutil import parser

                    posting_date = parser.parse(refund_date).date()
                else:
                    posting_date = getdate(refund_date)
            except (ValueError, TypeError, ImportError):
                pass
        if not posting_date:
            posting_date = nowdate()

        # Get donor name for remarks
        donor_name = donation_doc.donor if hasattr(donation_doc, "donor") else None

        # Create Journal Entry with reversed accounts
        return self._create_refund_journal_entry(
            posting_date=posting_date,
            company=company,
            amount=refund_amount,
            reference_number=reference_number,
            refund_id=refund_id,
            original_payment_id=original_payment_id,
            donation_name=donation_doc.name,
            donor_name=donor_name,
            clearing_account=config["clearing_account"],
            income_account=config["income_account"],
            cost_center=config.get("cost_center"),
            bank_transaction_name=bank_transaction_name,
            reversal_type=reversal_type,
            description=description,
        )

    def _get_config(self, company: str) -> Dict[str, Any]:
        """
        Get accounting configuration for donation refund journal entries.

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

    def _create_refund_journal_entry(
        self,
        posting_date,
        company: str,
        amount: float,
        reference_number: str,
        refund_id: str,
        original_payment_id: str,
        donation_name: str,
        donor_name: Optional[str],
        clearing_account: str,
        income_account: str,
        cost_center: Optional[str] = None,
        bank_transaction_name: Optional[str] = None,
        reversal_type: str = "refund",
        description: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create and submit refund Journal Entry using secure operations framework.

        Accounting entries (REVERSED from donation):
            Debit:  Donation Income Account (reduce income - we're giving money back)
            Credit: Mollie Clearing Account (money leaves the clearing account)
        """
        try:
            # Build remark. Say which kind of reversal this is: a chargeback and a
            # refund are different events to whoever reconciles the account, and
            # both were being narrated as "REFUND".
            label = reversal_type.upper()
            remark_parts = [f"Donation {label}: {donation_name}"]
            if donor_name:
                remark_parts.append(f"Donor: {donor_name}")
            remark_parts.append(f"{reversal_type.capitalize()} ID: {refund_id}")
            remark_parts.append(f"Original Payment: {original_payment_id}")
            if description:
                remark_parts.append(description)
            user_remark = " | ".join(remark_parts)

            # Create Journal Entry
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.company = company
            je.posting_date = posting_date
            je.cheque_no = reference_number  # Journal Entry uses cheque_no for reference
            je.cheque_date = posting_date
            je.user_remark = user_remark

            # Debit entry - Donation Income (reduce income - we're reversing the donation)
            debit_entry = {
                "account": income_account,
                "debit_in_account_currency": flt(amount),
                "credit_in_account_currency": 0,
                "user_remark": f"Donation {reversal_type}: {donation_name} | {reversal_type.capitalize()}: {refund_id}",
            }
            if cost_center:
                debit_entry["cost_center"] = cost_center
            je.append("accounts", debit_entry)

            # Credit entry - Mollie Clearing (money leaves the clearing account)
            credit_entry = {
                "account": clearing_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": flt(amount),
                "user_remark": f"{reversal_type.capitalize()} paid out: {donation_name}"
                + (f" | Donor: {donor_name}" if donor_name else ""),
            }
            if cost_center:
                credit_entry["cost_center"] = cost_center
            je.append("accounts", credit_entry)

            # Create using secure operations framework
            create_result = secure_document_operation(
                operation="create",
                doc=je,
                justification=f"Donation Refund Journal Entry for {donation_name} (refund: {refund_id})",
                required_permissions=["Journal Entry:create"],
                allow_system_user=True,
            )

            if not create_result.success:
                error_msg = ", ".join(create_result.errors) if create_result.errors else "Unknown error"
                frappe.logger().error(f"Failed to create Refund Journal Entry: {error_msg}")
                return None

            je = create_result.document

            # Submit the Journal Entry
            submit_result = secure_document_operation(
                operation="submit",
                doc=je,
                justification=f"Refund Journal Entry submission for donation {donation_name}",
                required_permissions=["Journal Entry:submit"],
                allow_system_user=True,
            )

            if not submit_result.success:
                return discard_unposted_journal_entry(
                    je.name,
                    subject=f"donation {donation_name} ({reversal_type}: {refund_id})",
                    error_message=(
                        ", ".join(submit_result.errors) if submit_result.errors else "Unknown error"
                    ),
                )

            frappe.logger().info(
                f"Created and submitted Refund Journal Entry {je.name} for donation {donation_name}"
            )

            # Reconcile Bank Transaction with this Journal Entry
            if bank_transaction_name:
                reconcile_bank_transaction_with_journal_entry(bank_transaction_name, je.name, flt(amount))

            return je.name

        except Exception as e:
            frappe.logger().error(f"Failed to create Refund Journal Entry: {e}")
            frappe.log_error(
                title="Donation Refund Journal Entry Error",
                message=f"Refund Journal Entry creation failed for donation {donation_name}: {e}",
            )
            return None


def get_donation_refund_journal_entry_creator() -> DonationRefundJournalEntryCreator:
    """Factory function to get DonationRefundJournalEntryCreator instance."""
    return DonationRefundJournalEntryCreator()
