# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Mollie Payment Orchestrator - Unified orchestration for Mollie payment processing.

Consolidates the three overlapping code paths:
1. /mollie_payment_processing page → MollieDebugService methods
2. complete_partial_payments → payment_processing_recovery.py
3. DuesPaymentProcessor.process_dues_payment() → Core processing

Provides a single canonical flow for processing Mollie payments regardless of entry point.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe.utils import getdate

from verenigingen.services.billing.invoice_matcher import InvoiceMatchResult, find_matching_invoice


def is_payment_successful(payment) -> bool:
    """
    Check if a Mollie payment is in a successful state.

    Centralizes payment status checking to ensure consistent handling
    across all processing methods.

    Args:
        payment: Mollie payment object

    Returns:
        True if payment status is 'paid', False otherwise
    """
    return getattr(payment, "status", None) == "paid"


@dataclass
class ProcessingStatus:
    """
    Status of a Mollie payment's processing in ERPNext.

    Attributes:
        payment_id: Mollie payment ID
        has_bank_transaction: Whether BT exists
        bank_transaction: BT name if exists
        has_payment_entry: Whether PE exists
        payment_entry: PE name if exists
        has_sales_invoice: Whether matching SINV exists
        sales_invoice: SINV name if exists
        bt_pe_linked: Whether BT is linked to PE
        member: Member name if identified
        status: 'complete', 'partial', or 'unprocessed'
        missing_documents: List of missing document types
    """

    payment_id: str
    has_bank_transaction: bool = False
    bank_transaction: Optional[str] = None
    has_payment_entry: bool = False
    payment_entry: Optional[str] = None
    has_sales_invoice: bool = False
    sales_invoice: Optional[str] = None
    bt_pe_linked: bool = False
    member: Optional[str] = None
    status: str = "unprocessed"
    missing_documents: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Whether all required documents exist and are linked."""
        return self.status == "complete"

    @property
    def is_partial(self) -> bool:
        """Whether processing started but not complete."""
        return self.status == "partial"

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "payment_id": self.payment_id,
            "has_bank_transaction": self.has_bank_transaction,
            "bank_transaction": self.bank_transaction,
            "has_payment_entry": self.has_payment_entry,
            "payment_entry": self.payment_entry,
            "has_sales_invoice": self.has_sales_invoice,
            "sales_invoice": self.sales_invoice,
            "bt_pe_linked": self.bt_pe_linked,
            "member": self.member,
            "status": self.status,
            "missing_documents": self.missing_documents,
            "is_complete": self.is_complete,
        }


@dataclass
class PaymentProcessingResult:
    """
    Result of processing a single Mollie payment.

    Attributes:
        payment_id: Mollie payment ID
        status: 'success', 'skipped', 'error', 'already_processed', 'needs_review'
        bank_transaction: Created/existing BT name
        payment_entry: Created/existing PE name
        sales_invoice: Matched/created SINV name
        member: Member name
        actions_taken: List of actions performed
        error: Error message if failed
        skipped_reason: Reason if skipped
        failed_step: Which processing step failed (for diagnostics)
        exception_type: Type of exception that caused failure
        link_error: Specific error if BT-PE linking failed
    """

    payment_id: str
    status: str = "pending"
    bank_transaction: Optional[str] = None
    payment_entry: Optional[str] = None
    sales_invoice: Optional[str] = None
    member: Optional[str] = None
    actions_taken: List[str] = field(default_factory=list)
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
    reconciled: bool = False
    failed_step: Optional[str] = None
    exception_type: Optional[str] = None
    link_error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "payment_id": self.payment_id,
            "status": self.status,
            "bank_transaction": self.bank_transaction,
            "payment_entry": self.payment_entry,
            "sales_invoice": self.sales_invoice,
            "member": self.member,
            "actions_taken": self.actions_taken,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
            "reconciled": self.reconciled,
            "failed_step": self.failed_step,
            "exception_type": self.exception_type,
            "link_error": self.link_error,
        }


class MolliePaymentOrchestrator:
    """
    Unified orchestration layer for Mollie payment processing.

    Provides consistent flow regardless of entry point:
    - /mollie_payment_processing page (discovery mode)
    - complete_partial_payments (recovery mode)
    - Direct API calls

    Uses:
    - InvoiceMatcher for invoice lookup
    - BankTransactionCreator for BT creation with idempotency
    - DuesPaymentProcessor for PE creation and member finding
    """

    def __init__(self):
        """Initialize with required services."""
        from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        self.mollie_client = MollieClient()
        self.dues_processor = DuesPaymentProcessor()
        self.bt_creator = get_bank_transaction_creator()

    def get_processing_status(self, payment_id: str) -> ProcessingStatus:
        """
        Check what documents exist for a Mollie payment.

        Comprehensive status check that identifies:
        - Existing Bank Transaction
        - Existing Payment Entry
        - Matching Sales Invoice
        - Whether BT and PE are linked
        - Associated member

        Args:
            payment_id: Mollie payment ID (e.g., 'tr_abc123')

        Returns:
            ProcessingStatus with complete document state
        """
        status = ProcessingStatus(payment_id=payment_id)

        # Check for Bank Transaction
        bt = frappe.db.get_value(
            "Bank Transaction",
            {"reference_number": payment_id},
            ["name", "party", "date"],
            as_dict=True,
        )

        if bt:
            status.has_bank_transaction = True
            status.bank_transaction = bt.name

            # Try to get member from party (Customer)
            if bt.party:
                member = frappe.db.get_value("Member", {"customer": bt.party}, "name")
                if member:
                    status.member = member

        # Check for Payment Entry (must be submitted, docstatus=1)
        pe = None
        if bt:
            # Check if PE is linked to BT
            pe_link = frappe.db.get_value(
                "Bank Transaction Payments",
                {"parent": bt.name, "payment_document": "Payment Entry"},
                "payment_entry",
            )
            if pe_link:
                # Verify the linked PE is submitted (not cancelled)
                pe_docstatus = frappe.db.get_value("Payment Entry", pe_link, "docstatus")
                if pe_docstatus == 1:
                    pe = pe_link
                    status.bt_pe_linked = True

        # Also check for PE with matching reference (must be submitted, not cancelled)
        if not pe:
            pe = frappe.db.get_value("Payment Entry", {"reference_no": payment_id, "docstatus": 1}, "name")

        if pe:
            status.has_payment_entry = True
            status.payment_entry = pe

            # Get member from PE if we don't have it yet
            if not status.member:
                pe_party = frappe.db.get_value("Payment Entry", pe, "party")
                if pe_party:
                    member = frappe.db.get_value("Member", {"customer": pe_party}, "name")
                    if member:
                        status.member = member

            # Check for linked Sales Invoice in PE references
            sinv_ref = frappe.db.get_value(
                "Payment Entry Reference",
                {"parent": pe, "reference_doctype": "Sales Invoice"},
                "reference_name",
            )
            if sinv_ref:
                status.has_sales_invoice = True
                status.sales_invoice = sinv_ref

        # If no linked SINV but we have member and BT date, look for matching invoice
        if not status.sales_invoice and status.member and bt:
            from verenigingen.services.billing.coverage_calculator import calculate_coverage_for_payment_date

            coverage_start, coverage_end = calculate_coverage_for_payment_date(status.member, bt.date)

            member_doc = frappe.get_doc("Member", status.member)
            if member_doc.customer:
                existing_invoice = frappe.db.get_value(
                    "Sales Invoice",
                    filters={
                        "customer": member_doc.customer,
                        "custom_coverage_start_date": coverage_start,
                        "custom_coverage_end_date": coverage_end,
                        "docstatus": 1,
                        "outstanding_amount": [">", 0],
                    },
                    fieldname="name",
                )
                if existing_invoice:
                    status.sales_invoice = existing_invoice
                    status.has_sales_invoice = True

        # Determine overall status
        if status.has_bank_transaction and status.has_payment_entry and status.has_sales_invoice:
            if status.bt_pe_linked:
                status.status = "complete"
            else:
                status.status = "partial"
                status.missing_documents.append("Bank Transaction → Payment Entry Link")
        elif status.has_bank_transaction or status.has_payment_entry or status.has_sales_invoice:
            status.status = "partial"
            if not status.has_bank_transaction:
                status.missing_documents.append("Bank Transaction")
            if not status.has_payment_entry:
                status.missing_documents.append("Payment Entry")
            if not status.has_sales_invoice:
                status.missing_documents.append("Sales Invoice")
            if not status.bt_pe_linked and status.has_bank_transaction and status.has_payment_entry:
                status.missing_documents.append("Bank Transaction → Payment Entry Link")
        else:
            status.status = "unprocessed"
            status.missing_documents = ["Bank Transaction", "Payment Entry", "Sales Invoice"]

        return status

    def find_matching_invoice(
        self,
        member_name: str,
        payment_date: Union[date, datetime],
        amount: Union[float, Decimal],
    ) -> InvoiceMatchResult:
        """
        Find best matching unpaid invoice for a payment.

        Delegates to centralized InvoiceMatcher service.

        Args:
            member_name: Member record name
            payment_date: Payment date
            amount: Payment amount in EUR

        Returns:
            InvoiceMatchResult with match details
        """
        return find_matching_invoice(
            member_name=member_name,
            payment_date=payment_date,
            payment_amount=amount,
            check_overlap=True,
        )

    def process_payment(
        self,
        payment_id: str,
        payment: Optional[Any] = None,
        member_name: Optional[str] = None,
        invoice_name: Optional[str] = None,
        create_missing_invoice: bool = False,
    ) -> PaymentProcessingResult:
        """
        Process a single Mollie payment through the canonical flow.

        This is the primary entry point for payment processing. It handles:
        1. Idempotency (skip if already processed)
        2. Member identification
        3. Invoice matching or creation
        4. Bank Transaction creation
        5. Payment Entry creation (with invoice reference)
        6. BT ↔ PE reconciliation

        Args:
            payment_id: Mollie payment ID
            payment: Optional pre-fetched Mollie payment object
            member_name: Optional pre-resolved member name
            invoice_name: Optional pre-matched invoice name
            create_missing_invoice: If True, creates invoice if not found (recovery mode)
                                   If False, skips invoice creation (discovery mode)

        Returns:
            PaymentProcessingResult with processing outcome
        """
        result = PaymentProcessingResult(payment_id=payment_id)

        try:
            # Check current processing status (idempotency)
            status = self.get_processing_status(payment_id)

            if status.is_complete:
                result.status = "already_processed"
                result.bank_transaction = status.bank_transaction
                result.payment_entry = status.payment_entry
                result.sales_invoice = status.sales_invoice
                result.member = status.member
                result.skipped_reason = "Already fully processed"
                return result

            # Fetch payment from Mollie if not provided
            if not payment:
                payment = self.mollie_client.sdk_client.payments.get(payment_id)

            # Validate payment status
            if not is_payment_successful(payment):
                result.status = "skipped"
                result.skipped_reason = f"Payment status is '{payment.status}', not 'paid'"
                return result

            # Identify payment type
            payment_type = self.dues_processor.identify_payment_type(payment)
            if payment_type != "dues":
                result.status = "skipped"
                result.skipped_reason = f"Payment type is '{payment_type}', not membership dues"
                return result

            # Find member if not provided
            if not member_name:
                member_name = status.member or self.dues_processor.find_member_for_payment(payment)

            if not member_name:
                result.status = "error"
                result.error = "Cannot determine member for payment"
                return result

            result.member = member_name

            # Extract payment data
            from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
                get_payment_data_extractor,
            )

            extractor = get_payment_data_extractor()
            payment_amount = extractor.extract_amount(payment)
            payment_date = extractor.extract_date(payment, field_name="paid_at")

            # Extract and save consumer bank data (IBAN, etc.)
            self.dues_processor._extract_and_save_consumer_bank_data(member_name, payment)

            # Step 1: Find or create invoice
            if not invoice_name and not status.sales_invoice:
                # Try to find matching invoice
                match_result = self.find_matching_invoice(
                    member_name=member_name,
                    payment_date=payment_date,
                    amount=payment_amount,
                )

                if match_result.found:
                    invoice_name = match_result.invoice_name
                    result.actions_taken.append(f"Matched invoice {invoice_name} ({match_result.match_type})")
                    if match_result.overlap_warning:
                        result.actions_taken.append(f"Warning: {match_result.overlap_warning}")
                elif create_missing_invoice:
                    # Recovery mode: create invoice if not found
                    invoice_name = self._create_invoice_if_safe(
                        member_name=member_name,
                        payment_date=payment_date,
                        payment_amount=payment_amount,
                        result=result,
                    )
                    if invoice_name:
                        result.actions_taken.append(f"Created Sales Invoice: {invoice_name}")
                else:
                    # Discovery mode: don't create, just note it
                    result.actions_taken.append("No matching invoice found (create_missing_invoice=False)")

            elif status.sales_invoice:
                # Re-validate that the status-cached invoice is still payable
                # This prevents TOCTOU issues where invoice was paid between status check and execution
                cached_outstanding = frappe.db.get_value(
                    "Sales Invoice", status.sales_invoice, "outstanding_amount"
                )
                if cached_outstanding and float(cached_outstanding) > 0:
                    invoice_name = status.sales_invoice
                else:
                    # Invoice from status check is no longer payable - try to find another
                    result.actions_taken.append(
                        f"Invoice {status.sales_invoice} is now fully paid, searching for alternative"
                    )
                    match_result = self.find_matching_invoice(
                        member_name=member_name,
                        payment_date=payment_date,
                        amount=payment_amount,
                    )
                    if match_result.found:
                        invoice_name = match_result.invoice_name
                        result.actions_taken.append(f"Found alternative invoice: {invoice_name}")
                    elif create_missing_invoice:
                        invoice_name = self._create_invoice_if_safe(
                            member_name=member_name,
                            payment_date=payment_date,
                            payment_amount=payment_amount,
                            result=result,
                        )
                        if invoice_name:
                            result.actions_taken.append(f"Created new Sales Invoice: {invoice_name}")

            result.sales_invoice = invoice_name

            # Step 2: Create Bank Transaction (if not exists)
            if not status.has_bank_transaction:
                bt_name = self._create_bank_transaction(payment, member_name)
                if bt_name:
                    result.bank_transaction = bt_name
                    result.actions_taken.append(f"Created Bank Transaction: {bt_name}")
                    status.has_bank_transaction = True
                    status.bank_transaction = bt_name
            else:
                result.bank_transaction = status.bank_transaction
                result.actions_taken.append(f"Bank Transaction exists: {status.bank_transaction}")

            # Step 3: Create Payment Entry (if not exists and we have invoice)
            if not status.has_payment_entry:
                pe_name = self.dues_processor._create_payment_entry_for_dues(
                    member_name,
                    payment,
                    invoice_name=invoice_name,
                    allow_invoice_creation=create_missing_invoice,
                    # In recovery mode, require invoice - don't create orphaned PEs
                    require_invoice=create_missing_invoice,
                )
                if pe_name:
                    result.payment_entry = pe_name
                    result.actions_taken.append(f"Created Payment Entry: {pe_name}")
                    status.has_payment_entry = True
                    status.payment_entry = pe_name
                elif create_missing_invoice and not invoice_name:
                    # Recovery mode but no invoice - this is a failure, not a success
                    result.actions_taken.append(
                        f"FAILED: Cannot create Payment Entry - no valid invoice for payment {payment_id}. "
                        f"Invoice creation may have failed due to coverage overlap, missing membership type, "
                        f"or other validation issue."
                    )
                    result.failed_step = "create_payment_entry"
            else:
                result.payment_entry = status.payment_entry
                result.actions_taken.append(f"Payment Entry exists: {status.payment_entry}")

            # Step 4: Link BT ↔ PE (if both exist but not linked)
            if status.has_bank_transaction and status.has_payment_entry and not status.bt_pe_linked:
                linked = self._link_bt_to_pe(
                    bt_name=result.bank_transaction,
                    pe_name=result.payment_entry,
                )
                if linked:
                    result.reconciled = True
                    result.actions_taken.append(
                        f"Linked BT {result.bank_transaction} to PE {result.payment_entry}"
                    )
                else:
                    # Log linking failure for troubleshooting - this indicates a reconciliation issue
                    link_error_msg = (
                        f"Failed to link BT {result.bank_transaction} to PE {result.payment_entry}"
                    )
                    frappe.log_error(
                        title="Mollie BT-PE Link Failure",
                        message=f"{link_error_msg} for payment {payment_id}",
                    )
                    result.link_error = link_error_msg
                    result.actions_taken.append(f"Warning: {link_error_msg}")

            # Determine final status
            if result.failed_step:
                # A step failed - partial success at best
                result.status = "partial"
                result.error = f"Processing incomplete: failed at step '{result.failed_step}'"
            elif result.bank_transaction and result.payment_entry:
                result.status = "success"
            elif result.bank_transaction or result.payment_entry:
                # Only partial documents created
                result.status = "partial"
                missing = []
                if not result.bank_transaction:
                    missing.append("Bank Transaction")
                if not result.payment_entry:
                    missing.append("Payment Entry")
                result.error = f"Partial processing: missing {', '.join(missing)}"
            else:
                result.status = "error"
                result.error = "No documents created"

        except Exception as e:
            result.status = "error"
            result.error = str(e)
            result.exception_type = type(e).__name__
            # Determine failed step based on what we have so far
            if not result.sales_invoice and not result.bank_transaction:
                result.failed_step = "invoice_matching"
            elif not result.bank_transaction:
                result.failed_step = "create_bank_transaction"
            elif not result.payment_entry:
                result.failed_step = "create_payment_entry"
            else:
                result.failed_step = "link_bt_pe"
            # Log error with short title (Error Log title field has 140 char limit)
            frappe.log_error(
                title="Mollie Payment Orchestrator Error",
                message=f"Error processing payment {payment_id} at step '{result.failed_step}': {e}",
            )

        return result

    def _create_bank_transaction(
        self,
        payment: Any,
        member_name: str,
    ) -> Optional[str]:
        """
        Create Bank Transaction for a Mollie payment.

        Uses BankTransactionCreator service with proper idempotency.

        Args:
            payment: Mollie payment object
            member_name: Member name for party linking

        Returns:
            Bank Transaction name if created, None otherwise
        """
        # Get configuration
        config = self.bt_creator.get_mollie_bank_account_config()
        if config.get("error"):
            frappe.log_error(
                f"Bank account config error: {config['error']}",
                "Mollie Bank Account Config Error",
            )
            return None

        # Get customer for party linking
        customer = frappe.db.get_value("Member", member_name, "customer")

        return self.bt_creator.create_from_mollie_payment(
            payment=payment,
            bank_account=config["bank_account"],
            company=config["company"],
            additional_description=f"Member: {member_name}",
            party_type="Customer" if customer else None,
            party=customer,
        )

    def _create_invoice_if_safe(
        self,
        member_name: str,
        payment_date: date,
        payment_amount: float,
        result: PaymentProcessingResult,
    ) -> Optional[str]:
        """
        Create invoice only if no coverage overlap exists.

        Performs overlap detection before creating to prevent duplicates.

        Args:
            member_name: Member name
            payment_date: Payment date for coverage calculation
            payment_amount: Payment amount
            result: Result object to update with warnings

        Returns:
            Sales Invoice name if created, None otherwise
        """
        from verenigingen.services.billing.coverage_calculator import calculate_coverage_for_payment_date
        from verenigingen.services.billing.coverage_overlap_detector import check_coverage_overlap

        # Calculate expected coverage
        coverage_start, coverage_end = calculate_coverage_for_payment_date(member_name, payment_date)

        # Get customer
        member = frappe.get_doc("Member", member_name)
        if not member.customer:
            result.actions_taken.append("Cannot create invoice: member has no customer")
            return None

        # Check for overlap
        overlap_result = check_coverage_overlap(
            customer=member.customer,
            proposed_start=coverage_start,
            proposed_end=coverage_end,
            exclude_cancelled=True,
        )

        if overlap_result.has_overlap:
            if overlap_result.exact_match:
                # Exact match found - but only use it if it has outstanding amount
                outstanding = frappe.db.get_value(
                    "Sales Invoice", overlap_result.exact_match, "outstanding_amount"
                )
                if outstanding and float(outstanding) > 0:
                    result.actions_taken.append(
                        f"Found existing unpaid invoice with exact coverage: {overlap_result.exact_match}"
                    )
                    return overlap_result.exact_match
                else:
                    # Invoice exists but is already paid - need to create new one
                    result.actions_taken.append(
                        f"Existing invoice {overlap_result.exact_match} is already paid, creating new invoice"
                    )
                    # Fall through to invoice creation below
            else:
                # Overlapping but not exact - flag for review
                overlapping_names = [inv["name"] for inv in overlap_result.overlapping_invoices]
                result.actions_taken.append(
                    f"Coverage overlap detected with: {', '.join(overlapping_names)}. "
                    f"Manual review required."
                )
                return None

        # Ensure fiscal year exists before invoice creation
        from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        company = verenigingen_settings.company or frappe.defaults.get_global_default("company")

        try:
            fiscal_year = ensure_fiscal_year_exists(payment_date, company)
            if fiscal_year:
                result.actions_taken.append(f"Ensured Fiscal Year: {fiscal_year}")
        except Exception as fy_error:
            result.actions_taken.append(f"Cannot create invoice: missing fiscal year for {payment_date}")
            frappe.log_error(
                f"Could not ensure fiscal year for {payment_date}: {fy_error}",
                "Mollie Fiscal Year Error",
            )
            return None

        # Safe to create
        return self.dues_processor._get_or_create_historical_invoice(
            member_name, payment_date, payment_amount
        )

    def _link_bt_to_pe(self, bt_name: str, pe_name: str) -> bool:
        """
        Link Bank Transaction to Payment Entry.

        Delegates to BankTransactionCreator.link_payment_entry() which uses
        ERPNext's standard reconciliation pattern.

        Args:
            bt_name: Bank Transaction name
            pe_name: Payment Entry name

        Returns:
            True if linked successfully, False otherwise
        """
        return self.bt_creator.link_payment_entry(bt_name, pe_name)

    def process_orphaned_payment(
        self,
        payment_id: str,
        payment: Optional[Any] = None,
        allow_anonymous: bool = True,
    ) -> PaymentProcessingResult:
        """
        Process an orphaned payment (no member match) - creates Bank Transaction only.

        This handles payments that cannot be matched to a member but still need
        to be recorded for accounting purposes. It:
        1. Attempts to find or create a Customer from Mollie customer data (if available)
        2. Creates Bank Transaction (linked to Customer if found, otherwise unlinked)
        3. Does NOT create Payment Entry or Sales Invoice

        Args:
            payment_id: Mollie payment ID
            payment: Optional pre-fetched Mollie payment object
            allow_anonymous: If True, allows creating BT without Customer link when
                           no Mollie customer ID exists (default: True)

        Returns:
            PaymentProcessingResult with processing outcome
        """
        result = PaymentProcessingResult(payment_id=payment_id)

        try:
            # Check if BT already exists (idempotency)
            existing_bt = frappe.db.get_value(
                "Bank Transaction",
                {"reference_number": payment_id},
                "name",
            )
            if existing_bt:
                result.status = "already_processed"
                result.bank_transaction = existing_bt
                result.skipped_reason = "Bank Transaction already exists"
                return result

            # Fetch payment from Mollie if not provided
            if not payment:
                payment = self.mollie_client.sdk_client.payments.get(payment_id)

            # Validate payment status
            if not is_payment_successful(payment):
                result.status = "skipped"
                result.skipped_reason = f"Payment status is '{payment.status}', not 'paid'"
                return result

            # Get Mollie customer ID and try to find/create Customer
            mollie_customer_id = getattr(payment, "customer_id", None)
            customer_name = None

            if mollie_customer_id:
                # Try to find or create Customer from Mollie data
                customer_name = self._find_or_create_customer_from_mollie(mollie_customer_id, payment, result)
            elif not allow_anonymous:
                # No customer ID and anonymous not allowed
                result.status = "error"
                result.error = "Payment has no Mollie customer ID and anonymous processing is disabled"
                return result
            else:
                # Anonymous payment - no customer ID available
                result.actions_taken.append("Anonymous payment (no Mollie customer ID)")

            # Get BT configuration
            config = self.bt_creator.get_mollie_bank_account_config()
            if config.get("error"):
                result.status = "error"
                result.error = f"Bank account config error: {config['error']}"
                return result

            # Build description based on available info
            description_parts = ["Orphaned payment (no member match)"]
            if not customer_name:
                description_parts.append("NEEDS MANUAL REVIEW")

            # Create Bank Transaction
            bt_name = self.bt_creator.create_from_mollie_payment(
                payment=payment,
                bank_account=config["bank_account"],
                company=config["company"],
                additional_description=" | ".join(description_parts),
                party_type="Customer" if customer_name else None,
                party=customer_name,
            )

            if bt_name:
                result.bank_transaction = bt_name
                result.status = "success"
                result.actions_taken.append(f"Created Bank Transaction: {bt_name}")
                if customer_name:
                    result.actions_taken.append(f"Linked to Customer: {customer_name}")
                else:
                    result.actions_taken.append("No party link - requires manual reconciliation")
            else:
                result.status = "error"
                result.error = "Failed to create Bank Transaction"

        except Exception as e:
            result.status = "error"
            result.error = str(e)
            frappe.log_error(
                title="Mollie Orphaned Payment Error",
                message=f"Error processing orphaned payment {payment_id}: {e}",
            )

        return result

    def process_orphaned_payment_with_invoice(
        self,
        payment_id: str,
        payment: Optional[Any] = None,
    ) -> PaymentProcessingResult:
        """
        Process an orphaned payment by creating SI, PE, and BT with a fallback customer.

        WARNING: This creates invoices for payments that could NOT be matched to any member.
        These invoices require manual review to:
        - Identify the actual member (if possible)
        - Reallocate the payment to the correct member
        - Or write off as unidentifiable donation

        The invoices are created with:
        - A generic "Orphaned Payments" customer
        - Clear warning remarks indicating manual review is needed
        - No cost center (defaults to company cost center)

        Args:
            payment_id: Mollie payment ID
            payment: Optional pre-fetched Mollie payment object

        Returns:
            PaymentProcessingResult with processing outcome
        """
        result = PaymentProcessingResult(payment_id=payment_id)

        try:
            # Fetch payment if not provided
            if not payment:
                payment = self.mollie_client.get_payment(payment_id)

            if not payment:
                result.status = "error"
                result.error = f"Payment {payment_id} not found in Mollie"
                return result

            # Check payment status
            if not is_payment_successful(payment):
                result.status = "skipped"
                result.skipped_reason = f"Payment status is '{getattr(payment, 'status', 'unknown')}'"
                return result

            # Extract payment data
            from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
                get_payment_data_extractor,
            )

            extractor = get_payment_data_extractor()
            payment_amount = extractor.extract_amount(payment)
            payment_date = extractor.extract_date(payment, field_name="paid_at")

            result.actions_taken.append("WARNING: Processing as ORPHANED payment - no member match found")

            # Get or create orphaned payments customer
            orphan_customer = self._get_or_create_orphan_customer()
            if not orphan_customer:
                result.status = "error"
                result.error = "Could not create orphan payments customer"
                return result

            result.actions_taken.append(f"Using fallback customer: {orphan_customer}")

            # Create Sales Invoice for orphan
            invoice_name = self._create_orphan_invoice(
                payment_id=payment_id,
                customer=orphan_customer,
                amount=payment_amount,
                payment_date=payment_date,
                payment_description=getattr(payment, "description", None),
            )

            if invoice_name:
                result.sales_invoice = invoice_name
                result.actions_taken.append(f"Created orphan Sales Invoice: {invoice_name}")
            else:
                result.status = "error"
                result.error = "Failed to create orphan invoice"
                return result

            # Create Bank Transaction
            status = self.get_processing_status(payment_id)
            if not status.has_bank_transaction:
                bt_name = self._create_orphan_bank_transaction(
                    payment=payment,
                    customer=orphan_customer,
                )
                if bt_name:
                    result.bank_transaction = bt_name
                    result.actions_taken.append(f"Created Bank Transaction: {bt_name}")
            else:
                result.bank_transaction = status.bank_transaction
                result.actions_taken.append(f"Bank Transaction exists: {status.bank_transaction}")

            # Create Payment Entry
            pe_name = self._create_orphan_payment_entry(
                payment_id=payment_id,
                customer=orphan_customer,
                invoice_name=invoice_name,
                amount=payment_amount,
                payment_date=payment_date,
            )

            if pe_name:
                result.payment_entry = pe_name
                result.actions_taken.append(f"Created Payment Entry: {pe_name}")
            else:
                result.status = "partial"
                result.error = "Created invoice but failed to create Payment Entry"
                return result

            # Link BT to PE
            if result.bank_transaction and result.payment_entry:
                linked = self._link_bt_to_pe(result.bank_transaction, result.payment_entry)
                if linked:
                    result.actions_taken.append(
                        f"Linked BT {result.bank_transaction} to PE {result.payment_entry}"
                    )

            result.status = "success"
            result.actions_taken.append(
                "REMINDER: This payment requires manual review to identify the member"
            )

        except Exception as e:
            result.status = "error"
            result.error = str(e)
            frappe.log_error(
                title="Mollie Orphan Invoice Error",
                message=f"Error processing orphaned payment with invoice {payment_id}: {e}",
            )

        return result

    def _get_or_create_orphan_customer(self) -> Optional[str]:
        """Get or create the orphaned payments fallback customer."""
        orphan_customer_name = "Orphaned Mollie Payments"

        # Check if exists
        existing = frappe.db.get_value("Customer", {"customer_name": orphan_customer_name}, "name")
        if existing:
            return existing

        # Create it
        try:
            settings = frappe.get_single("Verenigingen Settings")
            company = settings.company or frappe.defaults.get_global_default("company")

            customer = frappe.new_doc("Customer")
            customer.customer_name = orphan_customer_name
            customer.customer_type = "Individual"
            customer.customer_group = (
                frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
            )
            customer.territory = (
                frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
            )
            # Clear warning in the customer record
            customer.customer_details = (
                "AUTO-CREATED: This customer is used for Mollie payments that could not be "
                "matched to any member. Invoices assigned to this customer require manual "
                "review to identify the actual member."
            )

            customer.insert(ignore_permissions=True)
            frappe.logger().info(f"Created orphan customer: {customer.name}")
            return customer.name

        except Exception as e:
            frappe.log_error(
                title="Orphan Customer Creation Error",
                message=f"Failed to create orphan customer: {e}",
            )
            return None

    def _create_orphan_invoice(
        self,
        payment_id: str,
        customer: str,
        amount: float,
        payment_date: date,
        payment_description: Optional[str] = None,
    ) -> Optional[str]:
        """Create a Sales Invoice for an orphaned payment."""
        try:
            from verenigingen.e_boekhouden.utils.invoice_helpers import ensure_fiscal_year_exists

            settings = frappe.get_single("Verenigingen Settings")
            company = settings.company or frappe.defaults.get_global_default("company")

            # Ensure fiscal year
            ensure_fiscal_year_exists(payment_date, company)

            # Get income account
            from verenigingen.utils.settings_utils import get_payments_settings

            payments_settings = get_payments_settings()
            income_account = payments_settings.dues_income_account if payments_settings else None
            if not income_account:
                income_account = frappe.get_cached_value("Company", company, "default_income_account")

            # Create invoice
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = customer
            invoice.company = company
            invoice.posting_date = payment_date
            invoice.due_date = payment_date
            invoice.is_membership_invoice = 1

            # Warning remarks
            desc = payment_description or "No description"
            invoice.remarks = (
                f"⚠️ ORPHANED PAYMENT - MANUAL REVIEW REQUIRED ⚠️\n\n"
                f"This invoice was auto-generated for a Mollie payment that could NOT be "
                f"matched to any member.\n\n"
                f"Mollie Payment ID: {payment_id}\n"
                f"Original Description: {desc}\n\n"
                f"ACTION NEEDED:\n"
                f"1. Identify the actual member who made this payment\n"
                f"2. Create a proper invoice for that member\n"
                f"3. Reallocate the Payment Entry to the correct invoice\n"
                f"4. Cancel this orphan invoice"
            )

            # Get or create dues item - find a valid item dynamically
            dues_item = getattr(settings, "default_membership_dues_item", None)
            if not dues_item or not frappe.db.exists("Item", dues_item):
                # Try to find an existing membership dues item
                dues_item = frappe.db.get_value(
                    "Item",
                    {"item_code": ["like", "%Membership Dues%"], "disabled": 0},
                    "item_code",
                )
                if not dues_item:
                    # Fallback: find any active sales item
                    dues_item = frappe.db.get_value(
                        "Item",
                        {"is_sales_item": 1, "disabled": 0},
                        "item_code",
                    )
                if not dues_item:
                    raise ValueError("No valid item found for orphan invoice")

            invoice.append(
                "items",
                {
                    "item_code": dues_item,
                    "qty": 1,
                    "rate": amount,
                    "income_account": income_account,
                    "description": f"Orphaned payment {payment_id} - requires manual review",
                },
            )

            invoice.insert(ignore_permissions=True)
            invoice.submit()

            return invoice.name

        except Exception as e:
            frappe.log_error(
                title="Orphan Invoice Creation Error",
                message=f"Failed to create orphan invoice for {payment_id}: {e}",
            )
            return None

    def _create_orphan_bank_transaction(
        self,
        payment: Any,
        customer: str,
    ) -> Optional[str]:
        """Create Bank Transaction for orphaned payment."""
        config = self.bt_creator.get_mollie_bank_account_config()
        if config.get("error"):
            return None

        from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
            get_payment_data_extractor,
        )

        extractor = get_payment_data_extractor()
        payment_id = extractor.extract_payment_id(payment)

        return self.bt_creator.create_from_mollie_payment(
            payment=payment,
            bank_account=config["bank_account"],
            company=config["company"],
            additional_description="ORPHANED - requires member identification",
            party_type="Customer",
            party=customer,
        )

    def _create_orphan_payment_entry(
        self,
        payment_id: str,
        customer: str,
        invoice_name: str,
        amount: float,
        payment_date: date,
    ) -> Optional[str]:
        """Create Payment Entry for orphaned payment."""
        try:
            from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

            settings = frappe.get_single("Verenigingen Settings")
            company = settings.company or frappe.defaults.get_global_default("company")

            # Get Mollie clearing account
            from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
                get_mollie_config,
            )

            mollie_config = get_mollie_config()
            mollie_clearing_account = mollie_config.get_clearing_account()

            # Use ERPNext's get_payment_entry for proper account handling
            payment_entry = get_payment_entry(
                dt="Sales Invoice",
                dn=invoice_name,
                party_amount=amount,
                bank_account=mollie_clearing_account,
            )

            payment_entry.posting_date = payment_date
            payment_entry.reference_no = payment_id
            payment_entry.reference_date = payment_date
            payment_entry.mode_of_payment = getattr(settings, "mode_of_payment", None) or "Mollie"
            payment_entry.paid_to = mollie_clearing_account
            payment_entry.remarks = (
                f"⚠️ ORPHANED PAYMENT - Mollie ID: {payment_id}\n"
                f"This payment requires manual review to identify the member."
            )

            payment_entry.insert(ignore_permissions=True)
            payment_entry.submit()

            return payment_entry.name

        except Exception as e:
            frappe.log_error(
                title="Orphan PE Creation Error",
                message=f"Failed to create orphan PE for {payment_id}: {e}",
            )
            return None

    def process_bt_only_payment(
        self,
        payment_id: str,
        payment: Optional[Any] = None,
        member_name: Optional[str] = None,
    ) -> PaymentProcessingResult:
        """
        Process a payment in BT-only mode - creates Bank Transaction only, no Payment Entry.

        This handles payments that have a member but no matching invoice. It:
        1. Finds the member and their Customer record
        2. Creates Bank Transaction linked to that Customer
        3. Does NOT create Payment Entry or Sales Invoice

        Use this mode when you want to record the bank transaction for reconciliation
        but need to handle invoicing separately or manually.

        Args:
            payment_id: Mollie payment ID
            payment: Optional pre-fetched Mollie payment object
            member_name: Optional pre-resolved member name

        Returns:
            PaymentProcessingResult with processing outcome
        """
        result = PaymentProcessingResult(payment_id=payment_id)

        try:
            # Check if BT already exists (idempotency)
            existing_bt = frappe.db.get_value(
                "Bank Transaction",
                {"reference_number": payment_id},
                "name",
            )
            if existing_bt:
                result.status = "already_processed"
                result.bank_transaction = existing_bt
                result.skipped_reason = "Bank Transaction already exists"
                return result

            # Fetch payment from Mollie if not provided
            if not payment:
                payment = self.mollie_client.sdk_client.payments.get(payment_id)

            # Validate payment status
            if not is_payment_successful(payment):
                result.status = "skipped"
                result.skipped_reason = f"Payment status is '{payment.status}', not 'paid'"
                return result

            # Find member if not provided
            if not member_name:
                member_name = self.dues_processor.find_member_for_payment(payment)

            if member_name:
                result.member = member_name

            # Get Customer from member
            customer_name = None
            if member_name:
                customer_name = frappe.db.get_value("Member", member_name, "customer")
                if customer_name:
                    result.actions_taken.append(f"Found member's Customer: {customer_name}")

            # Get BT configuration
            config = self.bt_creator.get_mollie_bank_account_config()
            if config.get("error"):
                result.status = "error"
                result.error = f"Bank account config error: {config['error']}"
                return result

            # Create Bank Transaction (BT only mode - no PE)
            bt_name = self.bt_creator.create_from_mollie_payment(
                payment=payment,
                bank_account=config["bank_account"],
                company=config["company"],
                additional_description=f"BT-only mode (no matching invoice)",
                party_type="Customer" if customer_name else None,
                party=customer_name,
            )

            if bt_name:
                result.bank_transaction = bt_name
                result.status = "success"
                result.actions_taken.append(f"Created Bank Transaction: {bt_name}")
                result.actions_taken.append("PE skipped: bt_only mode (no matching invoice)")
            else:
                result.status = "error"
                result.error = "Failed to create Bank Transaction"

        except Exception as e:
            result.status = "error"
            result.error = str(e)
            frappe.log_error(
                title="Mollie BT-Only Payment Error",
                message=f"Error processing bt_only payment {payment_id}: {e}",
            )

        return result

    def _find_or_create_customer_from_mollie(
        self,
        mollie_customer_id: str,
        payment: Any,
        result: PaymentProcessingResult,
    ) -> Optional[str]:
        """
        Find existing Customer by Mollie customer ID or create a new one.

        Args:
            mollie_customer_id: Mollie customer ID
            payment: Mollie payment object (for additional data)
            result: Result object to update with actions

        Returns:
            Customer name if found/created, None otherwise
        """
        # Try to find existing Customer with this Mollie customer ID
        existing_customer = frappe.db.get_value(
            "Customer",
            {"custom_mollie_customer_id": mollie_customer_id},
            "name",
        )
        if existing_customer:
            result.actions_taken.append(f"Found existing Customer: {existing_customer}")
            return existing_customer

        # Try to get customer details from Mollie
        try:
            mollie_customer = self.mollie_client.sdk_client.customers.get(mollie_customer_id)
            customer_name = getattr(mollie_customer, "name", None)
            customer_email = getattr(mollie_customer, "email", None)

            if not customer_name:
                # Use email prefix or customer ID as fallback name
                if customer_email:
                    customer_name = customer_email.split("@")[0].replace(".", " ").title()
                else:
                    customer_name = f"Mollie Customer {mollie_customer_id}"

            # Create new Customer
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{customer_name} (Orphaned)"
            customer.customer_type = "Individual"
            customer.customer_group = (
                frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
            )
            customer.territory = (
                frappe.db.get_single_value("Selling Settings", "territory") or "All Territories"
            )
            customer.custom_mollie_customer_id = mollie_customer_id

            # Add email if available
            if customer_email:
                customer.append("email_ids", {"email_id": customer_email, "is_primary": 1})

            # Permission bypass is intentional for orphaned payment reconciliation.
            # Authorization context depends on caller:
            # - Webhook path: authenticated via Mollie HMAC-SHA256 signature verification
            # - Admin batch path: authenticated via @high_security_api(OperationType.FINANCIAL)
            # Customer created with "(Orphaned)" suffix for easy identification during reconciliation.
            try:
                customer.insert(ignore_permissions=True)
                result.actions_taken.append(f"Created Customer: {customer.name} from Mollie data")
                return customer.name
            except frappe.exceptions.DuplicateEntryError:
                # Race condition: another process created this Customer concurrently
                existing_customer = frappe.db.get_value(
                    "Customer",
                    {"custom_mollie_customer_id": mollie_customer_id},
                    "name",
                )
                if existing_customer:
                    result.actions_taken.append(f"Found concurrently created Customer: {existing_customer}")
                    return existing_customer
                raise  # Re-raise if we still can't find it

        except Exception as e:
            frappe.log_error(
                title="Mollie Customer Creation Error",
                message=f"Could not fetch/create customer from Mollie {mollie_customer_id}: {e}",
            )
            result.actions_taken.append(f"Warning: Could not create Customer ({e})")
            return None

    def process_payments_batch(
        self,
        payment_ids: List[str],
        create_missing_invoice: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Process multiple payments in batch.

        Args:
            payment_ids: List of Mollie payment IDs to process
            create_missing_invoice: If True, creates invoices if not found
            dry_run: If True, only check status without making changes

        Returns:
            Dict with batch processing results
        """
        batch_result = {
            "total_requested": len(payment_ids),
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "already_complete": 0,
            "results": [],
            "dry_run": dry_run,
            "timestamp": frappe.utils.now(),
        }

        for payment_id in payment_ids:
            if dry_run:
                # Just check status
                status = self.get_processing_status(payment_id)
                batch_result["results"].append(
                    {
                        "payment_id": payment_id,
                        "status": "dry_run",
                        "current_status": status.to_dict(),
                    }
                )
                continue

            result = self.process_payment(
                payment_id=payment_id,
                create_missing_invoice=create_missing_invoice,
            )

            batch_result["results"].append(result.to_dict())

            if result.status == "success":
                batch_result["processed"] += 1
            elif result.status == "already_processed":
                batch_result["already_complete"] += 1
            elif result.status == "skipped":
                batch_result["skipped"] += 1
            elif result.status == "error":
                batch_result["errors"] += 1

        return batch_result


# Singleton accessor
_orchestrator_instance = None


def get_payment_orchestrator() -> MolliePaymentOrchestrator:
    """Get singleton MolliePaymentOrchestrator instance."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = MolliePaymentOrchestrator()
    return _orchestrator_instance
