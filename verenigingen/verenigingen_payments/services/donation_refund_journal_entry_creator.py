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
        existing_je = self._check_existing_by_reference(reference_number)
        if existing_je:
            frappe.logger().info(f"Refund Journal Entry already exists for {refund_id}: {existing_je}")
            # Still attempt reconciliation in case it wasn't done previously
            if bank_transaction_name:
                self._reconcile_bank_transaction(bank_transaction_name, existing_je, flt(refund_amount))
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
                return self._discard_unposted_journal_entry(je.name, submit_result, donation_name)

            frappe.logger().info(
                f"Created and submitted Refund Journal Entry {je.name} for donation {donation_name}"
            )

            # Reconcile Bank Transaction with this Journal Entry
            if bank_transaction_name:
                self._reconcile_bank_transaction(bank_transaction_name, je.name, flt(amount))

            return je.name

        except Exception as e:
            frappe.logger().error(f"Failed to create Refund Journal Entry: {e}")
            frappe.log_error(
                f"Refund Journal Entry creation failed for donation {donation_name}: {e}",
                "Donation Refund Journal Entry Error",
            )
            return None

    def _discard_unposted_journal_entry(self, je_name: str, submit_result, donation_name: str) -> None:
        """A Journal Entry whose submit failed is not a booking. Always returns None.

        This used to log "(draft)" and ``return je.name`` anyway, so the caller's
        "did I get a name back?" success test read a failed posting as success.

        Two things make that worse than a wrong status code:

        * The entry is **not** a draft. Frappe's ``Document.save()`` runs
          ``db_update()`` before ``run_post_save_methods()``, and ``on_submit`` is
          what posts to the ledger -- so a submit that throws leaves ``docstatus=1``
          already written, and ``secure_document_operation`` catches the error
          without rolling back. ERPNext validates each GL row in
          ``GLEntry.on_update``, i.e. *after* inserting it, so the ledger can be
          left one-sided.
        * ``find_booked_reversal`` counts anything with ``docstatus != 2``. Left in
          place, the unposted entry claims the reversal key and every one of
          Mollie's redeliveries answers "already processed" -- the refund reported
          done, permanently, having never reached the ledger.

        So the entry is cancelled (which frees the key, since only ``docstatus=2``
        is ignored) and removed. Failure to clean up is logged and swallowed: the
        booking has already failed and been reported, and raising here would
        replace the real reason with a less useful one.
        """
        error_msg = ", ".join(submit_result.errors) if submit_result.errors else "Unknown error"
        message = (
            f"Refund Journal Entry {je_name} for donation {donation_name} could not be "
            f"submitted and did not post to the ledger: {error_msg}"
        )
        frappe.logger().error(message)
        frappe.log_error(message, "Donation Refund Journal Entry Not Posted")

        try:
            je = frappe.get_doc("Journal Entry", je_name)
            if je.docstatus == 1:
                je.cancel()
            frappe.delete_doc("Journal Entry", je_name, force=True)
        except Exception as cleanup_error:
            frappe.logger().error(
                f"Could not remove unposted Refund Journal Entry {je_name}: {cleanup_error}"
            )
            frappe.log_error(
                f"Unposted Refund Journal Entry {je_name} was left behind and still claims its "
                f"reversal key, so redeliveries will report it as already processed: {cleanup_error}",
                "Donation Refund Journal Entry Cleanup Failed",
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
            # For refunds, we check against withdrawal amount
            total_allocated = sum(flt(pe.allocated_amount) for pe in bt.payment_entries)
            withdrawal_amount = flt(bt.withdrawal or 0)
            if withdrawal_amount and total_allocated >= withdrawal_amount:
                bt.status = "Reconciled"

            bt.save()
            frappe.db.commit()

            frappe.logger().info(
                f"Reconciled Bank Transaction {bank_transaction_name} with Refund Journal Entry {journal_entry_name}"
            )

        except Exception as e:
            frappe.logger().error(f"Failed to reconcile Bank Transaction {bank_transaction_name}: {e}")
            # Don't raise - reconciliation failure shouldn't fail the whole operation


def get_donation_refund_journal_entry_creator() -> DonationRefundJournalEntryCreator:
    """Factory function to get DonationRefundJournalEntryCreator instance."""
    return DonationRefundJournalEntryCreator()
