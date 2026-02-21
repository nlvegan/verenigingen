"""
SEPA XML Adapter Service

This adapter bridges the Direct Debit Batch document with the EnhancedSEPAXMLGenerator.
It handles the transformation of batch invoice data into SEPATransaction dataclasses
and manages mandate sign date lookups with caching to prevent N+1 queries.

Key responsibilities:
- Transform batch invoices to SEPATransaction objects
- Look up mandate sign dates with DB fallback (configurable strict mode)
- Cache mandate data to prevent N+1 queries
- Generate SEPA XML using EnhancedSEPAXMLGenerator
- Track and report skipped transactions for operational alerting
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

import frappe
from frappe.utils import getdate

from verenigingen.utils.constants import Roles
from verenigingen.verenigingen_payments.services.sepa_configuration_service import sepa_config_service
from verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator import (
    EnhancedSEPAXMLGenerator,
    SEPACreditor,
    SEPADebtor,
    SEPALocalInstrument,
    SEPAMandate,
    SEPAPaymentInfo,
    SEPASequenceType,
    SEPATransaction,
)


@dataclass
class BatchValidationSummary:
    """Summary of batch validation results for operational alerting."""

    total_invoices: int = 0
    successful_transactions: int = 0
    skipped_transactions: int = 0
    missing_mandate_dates: int = 0
    skipped_invoice_details: List[dict] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        """Return True if any transactions were skipped or mandates missing."""
        return self.skipped_transactions > 0 or self.missing_mandate_dates > 0

    def add_skipped(self, invoice: str, reason: str) -> None:
        """Record a skipped transaction."""
        self.skipped_transactions += 1
        self.skipped_invoice_details.append({"invoice": invoice, "reason": reason})


class SEPAXMLAdapter:
    """
    Adapter for generating SEPA XML from Direct Debit Batch documents.

    Uses EnhancedSEPAXMLGenerator for proper pain.008.001.08 compliance
    with correct mandate sign dates (DtOfSgntr).

    Supports strict validation mode via Verenigingen Settings:
    - Strict mode: Fails XML generation if any mandate sign date is missing
    - Permissive mode: Falls back to today's date with warning (default)
    """

    def __init__(self):
        self.generator = EnhancedSEPAXMLGenerator()
        self._mandate_cache: Dict[str, dict] = {}
        self._validation_summary: Optional[BatchValidationSummary] = None

    def _is_strict_mode(self) -> bool:
        """Check if strict mandate validation is enabled."""
        try:
            return (
                frappe.db.get_single_value("Verenigingen Settings", "sepa_strict_mandate_validation") or False
            )
        except Exception:
            return False

    def _get_financial_admin_emails(self) -> List[str]:
        """Get financial admin email addresses for alerts."""
        try:
            emails = frappe.db.get_single_value("Verenigingen Settings", "stuck_schedule_notification_emails")
            if emails:
                return [e.strip() for e in emails.split(",") if e.strip()]
        except Exception:
            pass
        return []

    def generate_xml_for_batch(
        self,
        batch_doc,
        message_id: str,
        payment_info_id: str,
    ) -> str:
        """
        Generate SEPA XML for a Direct Debit Batch document.

        Args:
            batch_doc: Direct Debit Batch document
            message_id: Unique message identifier
            payment_info_id: Payment information identifier

        Returns:
            XML string in pain.008.001.08 format

        Raises:
            frappe.ValidationError: If strict mode is enabled and mandate dates are missing,
                                   or if no valid transactions can be built.
        """
        # Initialize validation summary for this batch
        self._validation_summary = BatchValidationSummary(total_invoices=len(batch_doc.invoices))

        # Get SEPA configuration settings
        settings = sepa_config_service.get_sepa_settings()

        # Create creditor from settings
        creditor = self._build_creditor_from_settings(settings)

        # Determine sequence type from batch
        sequence_type = self._get_sequence_type(batch_doc.batch_type or "RCUR")

        # Build transactions from batch invoices
        transactions = self._build_transactions_from_batch(batch_doc, sequence_type)

        # Update validation summary
        self._validation_summary.successful_transactions = len(transactions)

        # Check for issues and handle based on strict mode
        if self._validation_summary.has_issues:
            self._handle_validation_issues(batch_doc.name)

        if not transactions:
            frappe.throw("No valid transactions to include in SEPA XML")

        # Create payment info
        collection_date = getdate(batch_doc.batch_date)
        if isinstance(collection_date, str):
            collection_date = datetime.strptime(collection_date, "%Y-%m-%d").date()

        payment_info = SEPAPaymentInfo(
            payment_info_id=payment_info_id,
            payment_method="DD",
            batch_booking=True,
            requested_collection_date=collection_date,
            creditor=creditor,
            local_instrument=SEPALocalInstrument.CORE,
            sequence_type=sequence_type,
            transactions=transactions,
        )

        # Generate XML using enhanced generator
        xml_string = self.generator.generate_sepa_xml(
            message_id=message_id,
            creation_datetime=datetime.now(),
            payment_infos=[payment_info],
            initiating_party_name=settings["organization_name"],
        )

        # Log summary
        summary = self._validation_summary
        frappe.logger().info(
            f"Generated SEPA XML for batch {batch_doc.name}: "
            f"{len(transactions)} transactions, total {sum(t.amount for t in transactions):.2f} EUR"
            f"{f', {summary.skipped_transactions} skipped' if summary.skipped_transactions else ''}"
            f"{f', {summary.missing_mandate_dates} missing mandate dates' if summary.missing_mandate_dates else ''}"
        )

        return xml_string

    def _handle_validation_issues(self, batch_name: str) -> None:
        """Handle validation issues based on strict mode setting."""
        summary = self._validation_summary
        strict_mode = self._is_strict_mode()

        # Build issue message
        issues = []
        if summary.skipped_transactions > 0:
            issues.append(f"{summary.skipped_transactions} transactions skipped")
        if summary.missing_mandate_dates > 0:
            issues.append(f"{summary.missing_mandate_dates} mandates missing sign dates (using today)")

        issue_msg = f"SEPA XML batch {batch_name}: {', '.join(issues)}"

        if strict_mode and summary.missing_mandate_dates > 0:
            # In strict mode, fail if any mandate dates are missing
            frappe.throw(
                f"Strict SEPA validation failed: {summary.missing_mandate_dates} mandate(s) "
                f"missing sign dates. Fix mandate data or disable strict validation in settings."
            )

        # Log warning
        frappe.logger().warning(issue_msg)

        # Send alert to financial admins if any transactions were skipped
        if summary.skipped_transactions > 0:
            self._send_validation_alert(batch_name, summary)

    def _send_validation_alert(self, batch_name: str, summary: BatchValidationSummary) -> None:
        """Send alert email to financial admins about validation issues."""
        try:
            recipients = self._get_financial_admin_emails()
            if not recipients:
                # Fall back to system managers
                recipients = frappe.get_all(
                    "Has Role",
                    filters={"role": Roles.SYSTEM_MANAGER, "parenttype": "User"},
                    pluck="parent",
                    limit=5,
                )

            if not recipients:
                frappe.logger().warning(f"No recipients for SEPA validation alert for batch {batch_name}")
                return

            # Build details table
            details_html = ""
            if summary.skipped_invoice_details:
                rows = "".join(
                    f"<tr><td>{d['invoice']}</td><td>{d['reason']}</td></tr>"
                    for d in summary.skipped_invoice_details[:20]  # Limit to 20
                )
                if len(summary.skipped_invoice_details) > 20:
                    rows += f"<tr><td colspan='2'>... and {len(summary.skipped_invoice_details) - 20} more</td></tr>"
                details_html = f"""
                <h4>Skipped Transactions:</h4>
                <table border='1' cellpadding='5'>
                    <tr><th>Invoice</th><th>Reason</th></tr>
                    {rows}
                </table>
                """

            frappe.sendmail(
                recipients=recipients,
                subject=f"SEPA Batch {batch_name}: Validation Issues",
                message=f"""
                <h3>SEPA XML Generation Alert</h3>
                <p>Batch <strong>{batch_name}</strong> was generated with validation issues:</p>
                <ul>
                    <li>Total invoices: {summary.total_invoices}</li>
                    <li>Successful transactions: {summary.successful_transactions}</li>
                    <li>Skipped transactions: {summary.skipped_transactions}</li>
                    <li>Missing mandate sign dates: {summary.missing_mandate_dates}</li>
                </ul>
                {details_html}
                <p>Please review the batch and mandate data.</p>
                """,
                now=True,
            )

            frappe.logger().info(
                f"Sent SEPA validation alert for batch {batch_name} to {len(recipients)} recipients"
            )

        except Exception as e:
            frappe.logger().error(f"Failed to send SEPA validation alert: {str(e)}")

    def _build_creditor_from_settings(self, settings: dict) -> SEPACreditor:
        """Build SEPACreditor from SEPA configuration settings."""
        return SEPACreditor(
            name=settings["organization_name"],
            iban=settings["iban"],
            bic=settings.get("bic", ""),
            creditor_id=settings["creditor_id"],
            country="NL",
        )

    def _build_transactions_from_batch(
        self,
        batch_doc,
        batch_sequence_type: SEPASequenceType,
    ) -> List[SEPATransaction]:
        """
        Build SEPATransaction list from batch invoice items.

        Uses mandate_sign_date from invoice item with DB fallback.
        Caches mandate lookups to prevent N+1 queries.
        Tracks skipped transactions in validation summary.
        """
        transactions = []

        # Pre-fetch all mandate data for the batch to avoid N+1 queries
        self._prefetch_mandate_data(batch_doc.invoices)

        for invoice_item in batch_doc.invoices:
            try:
                transaction = self._build_transaction(invoice_item, batch_sequence_type)
                if transaction:
                    transactions.append(transaction)
            except Exception as e:
                error_msg = str(e)
                frappe.log_error(
                    title="SEPA XML Adapter - Transaction Build Error",
                    message=(
                        f"Error building transaction for invoice {invoice_item.invoice}: {error_msg}\n"
                        f"Traceback: {frappe.get_traceback()}"
                    ),
                )
                # Track skipped transaction
                if self._validation_summary:
                    self._validation_summary.add_skipped(
                        invoice_item.invoice, error_msg[:100]  # Truncate long error messages
                    )

        return transactions

    def _build_transaction(
        self,
        invoice_item,
        batch_sequence_type: SEPASequenceType,
    ) -> Optional[SEPATransaction]:
        """Build a single SEPATransaction from an invoice item."""
        # Get mandate sign date with fallback lookup
        mandate_sign_date, used_fallback = self._get_mandate_sign_date(invoice_item)

        # Track if we used fallback (missing mandate date)
        if used_fallback and self._validation_summary:
            self._validation_summary.missing_mandate_dates += 1

        # Determine transaction sequence type
        # Use invoice-level sequence type if available, otherwise use batch default
        invoice_sequence_type = invoice_item.sequence_type if invoice_item.sequence_type else None
        sequence_type = (
            self._get_sequence_type(invoice_sequence_type) if invoice_sequence_type else batch_sequence_type
        )

        # Build debtor
        debtor = SEPADebtor(
            name=invoice_item.member_name or "UNKNOWN",
            iban=invoice_item.iban or "",
            bic=getattr(invoice_item, "bic", None),
            country="NL",
        )

        # Build mandate
        mandate = SEPAMandate(
            mandate_id=invoice_item.mandate_reference or "UNKNOWN",
            date_of_signature=mandate_sign_date,
        )

        # Build EndToEndId - avoid double-prefixing
        invoice_id = invoice_item.invoice or "UNKNOWN"
        if invoice_id.startswith("INV-"):
            end_to_end_id = invoice_id
        else:
            end_to_end_id = f"INV-{invoice_id}"

        # Build transaction
        return SEPATransaction(
            end_to_end_id=end_to_end_id,
            amount=Decimal(str(invoice_item.amount or 0)),
            currency=invoice_item.currency or "EUR",
            debtor=debtor,
            mandate=mandate,
            remittance_info=f"Invoice {invoice_item.invoice}",
            sequence_type=sequence_type,
        )

    def _get_mandate_sign_date(self, invoice_item) -> tuple[date, bool]:
        """
        Get mandate sign date from invoice item or DB lookup.

        Priority:
        1. invoice_item.mandate_sign_date (if populated)
        2. Cached mandate data
        3. DB lookup with caching
        4. Fallback to today's date

        Returns:
            Tuple of (mandate sign date, used_fallback: bool)
            used_fallback is True if we fell back to today's date
        """
        # First check if sign date is already on the invoice item
        if hasattr(invoice_item, "mandate_sign_date") and invoice_item.mandate_sign_date:
            sign_date = getdate(invoice_item.mandate_sign_date)
            if isinstance(sign_date, date):
                return sign_date, False

        # Check cache
        mandate_ref = invoice_item.mandate_reference
        if mandate_ref and mandate_ref in self._mandate_cache:
            cached_date = self._mandate_cache[mandate_ref].get("sign_date")
            if cached_date:
                result_date = getdate(cached_date) if isinstance(cached_date, str) else cached_date
                return result_date, False

        # DB lookup as fallback
        return self._lookup_mandate_sign_date(
            mandate_reference=mandate_ref,
            member=getattr(invoice_item, "member", None),
        )

    def _lookup_mandate_sign_date(
        self,
        mandate_reference: Optional[str],
        member: Optional[str],
    ) -> tuple[date, bool]:
        """
        Look up mandate sign date from database.

        Falls back to today's date if mandate not found.

        Returns:
            Tuple of (date, used_fallback: bool)
        """
        if not mandate_reference:
            frappe.logger().warning("No mandate reference provided, using today's date as sign date")
            return date.today(), True

        try:
            # Try to find by mandate_id first
            mandate_data = frappe.db.get_value(
                "SEPA Mandate",
                {"mandate_id": mandate_reference, "status": "Active"},
                ["sign_date", "name"],
                as_dict=True,
            )

            if mandate_data and mandate_data.sign_date:
                sign_date = getdate(mandate_data.sign_date)
                # Cache for future lookups
                self._mandate_cache[mandate_reference] = {"sign_date": sign_date}
                return sign_date, False

            # Try to find by member if mandate_id lookup failed
            if member:
                mandate_data = frappe.db.get_value(
                    "SEPA Mandate",
                    {"member": member, "status": "Active"},
                    ["sign_date", "name", "mandate_id"],
                    as_dict=True,
                    order_by="creation desc",
                )

                if mandate_data and mandate_data.sign_date:
                    sign_date = getdate(mandate_data.sign_date)
                    # Cache using both mandate_id and mandate_reference
                    if mandate_data.mandate_id:
                        self._mandate_cache[mandate_data.mandate_id] = {"sign_date": sign_date}
                    self._mandate_cache[mandate_reference] = {"sign_date": sign_date}
                    return sign_date, False

        except Exception as e:
            frappe.logger().warning(f"Error looking up mandate sign date for {mandate_reference}: {str(e)}")

        # Fallback to today if no mandate found
        frappe.logger().warning(
            f"Mandate {mandate_reference} not found or has no sign date, using today's date"
        )
        return date.today(), True

    def _prefetch_mandate_data(self, invoices) -> None:
        """
        Pre-fetch mandate data for all invoices to prevent N+1 queries.

        Populates the mandate cache with sign dates for all mandates
        referenced in the batch.
        """
        # Get unique mandate references that need lookup
        mandate_refs_to_lookup = set()
        for invoice in invoices:
            # Skip if already have sign date on invoice or in cache
            if hasattr(invoice, "mandate_sign_date") and invoice.mandate_sign_date:
                continue
            mandate_ref = invoice.mandate_reference
            if mandate_ref and mandate_ref not in self._mandate_cache:
                mandate_refs_to_lookup.add(mandate_ref)

        if not mandate_refs_to_lookup:
            return

        # Batch fetch mandate data
        try:
            mandates = frappe.db.get_all(
                "SEPA Mandate",
                filters={
                    "mandate_id": ["in", list(mandate_refs_to_lookup)],
                    "status": "Active",
                },
                fields=["mandate_id", "sign_date"],
            )

            for mandate in mandates:
                if mandate.sign_date:
                    self._mandate_cache[mandate.mandate_id] = {"sign_date": getdate(mandate.sign_date)}

            frappe.logger().info(f"Pre-fetched {len(mandates)} mandates for SEPA XML generation")

        except Exception as e:
            frappe.logger().warning(f"Error pre-fetching mandate data: {str(e)}")

    def _get_sequence_type(self, type_str: Optional[str]) -> SEPASequenceType:
        """Convert sequence type string to SEPASequenceType enum."""
        type_map = {
            "FRST": SEPASequenceType.FRST,
            "RCUR": SEPASequenceType.RCUR,
            "OOFF": SEPASequenceType.OOFF,
            "FNAL": SEPASequenceType.FNAL,
            "CORE": SEPASequenceType.RCUR,  # CORE is not a sequence type, default to RCUR
        }
        return type_map.get(type_str, SEPASequenceType.RCUR)

    def clear_cache(self) -> None:
        """Clear the mandate cache."""
        self._mandate_cache.clear()


# Singleton instance
_adapter_instance: Optional[SEPAXMLAdapter] = None


def get_sepa_xml_adapter() -> SEPAXMLAdapter:
    """Get or create the SEPA XML adapter instance."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = SEPAXMLAdapter()
    return _adapter_instance
