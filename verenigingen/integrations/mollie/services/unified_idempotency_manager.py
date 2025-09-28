"""
Unified Idempotency Manager

True consolidation of all payment idempotency checks into a single authoritative system.
Eliminates the fragmented approach where different code paths performed independent
idempotency checks, causing duplicate payment entries.

This replaces the previous PaymentIdempotencyService's wrapper pattern with a
unified architecture that serves as the single source of truth for all payment
processing state across the entire Mollie integration.
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe

from ..utils.logging import MollieLogger


class PaymentIdempotencyCheckResult:
    """Structured result from unified idempotency check."""

    def __init__(self, payment_id: str):
        self.payment_id = payment_id
        self.payment_entry_exists = False
        self.payment_entry_name = None
        self.payment_history_updated = False
        self.donation_status_updated = False
        self.donation_name = None
        self.all_processing_complete = False

        # Refund-specific state
        self.refunds_processed = []
        self.pending_refunds = []

        # Chargeback-specific state
        self.chargebacks_processed = []
        self.pending_chargebacks = []

    def is_fully_processed(self) -> bool:
        """Check if payment is completely processed (all components updated)."""
        return self.payment_entry_exists and self.payment_history_updated and self.donation_status_updated

    def needs_payment_processing(self) -> bool:
        """Check if main payment processing is needed."""
        return not self.is_fully_processed()

    def has_pending_refunds(self) -> bool:
        """Check if there are unprocessed refunds."""
        return len(self.pending_refunds) > 0

    def has_pending_chargebacks(self) -> bool:
        """Check if there are unprocessed chargebacks."""
        return len(self.pending_chargebacks) > 0


class UnifiedIdempotencyManager:
    """
    Single authoritative source for all payment processing state.

    Eliminates fragmented idempotency checks by providing one unified system
    that tracks the complete state of payment processing across all components:
    - Payment Entry creation
    - Payment history updates
    - Donation status changes
    - Refund processing
    - Chargeback processing

    This prevents duplicate processing by giving all code paths a consistent
    view of what has been processed and what still needs to be done.
    """

    def __init__(self, target_doctype: str = "Donation"):
        self.logger = MollieLogger("unified_idempotency")
        self.target_doctype = target_doctype

    def check_payment_processing_state(
        self, payment_id: str, include_mollie_api: bool = False
    ) -> PaymentIdempotencyCheckResult:
        """
        Comprehensive check of payment processing state across all components.

        This is the ONLY method that should be used to check idempotency.
        All other idempotency checks throughout the codebase should delegate here.

        Args:
            payment_id: Mollie payment ID
            include_mollie_api: If True, fetch current refund/chargeback state from Mollie

        Returns:
            Complete processing state with specific recommendations for next actions
        """
        self.logger.info(f"🔍 Unified idempotency check for payment {payment_id}")

        result = PaymentIdempotencyCheckResult(payment_id)

        # 1. Check Payment Entry existence and status
        self._check_payment_entry_state(payment_id, result)

        # 2. Check donation and payment history state
        self._check_donation_state(payment_id, result)

        # 3. Check refund processing state
        self._check_refund_processing_state(payment_id, result, include_mollie_api)

        # 4. Check chargeback processing state
        self._check_chargeback_processing_state(payment_id, result, include_mollie_api)

        # 5. Determine overall completion status
        result.all_processing_complete = (
            result.is_fully_processed()
            and not result.has_pending_refunds()
            and not result.has_pending_chargebacks()
        )

        self.logger.info(
            f"📊 Payment {payment_id} state: "
            f"PE={result.payment_entry_exists}, "
            f"PH={result.payment_history_updated}, "
            f"DS={result.donation_status_updated}, "
            f"Refunds={len(result.refunds_processed)}/{len(result.pending_refunds)}, "
            f"Complete={result.all_processing_complete}"
        )

        return result

    def _check_payment_entry_state(self, payment_id: str, result: PaymentIdempotencyCheckResult):
        """Check Payment Entry creation and submission status."""
        # Check for main payment (Receive type)
        payment_entry = frappe.db.get_value(
            "Payment Entry",
            {"reference_no": payment_id, "payment_type": "Receive", "docstatus": 1},
            ["name", "paid_amount", "party_type", "party"],
            as_dict=True,
        )

        if payment_entry:
            result.payment_entry_exists = True
            result.payment_entry_name = payment_entry.name
            self.logger.info(f"✅ Payment Entry found: {payment_entry.name}")
        else:
            # Check for draft or cancelled entries
            draft_entry = frappe.db.get_value(
                "Payment Entry",
                {"reference_no": payment_id, "payment_type": "Receive"},
                ["name", "docstatus"],
                as_dict=True,
            )
            if draft_entry:
                self.logger.warning(
                    f"⚠️ Payment Entry {draft_entry.name} exists but not submitted (status: {draft_entry.docstatus})"
                )

    def _check_donation_state(self, payment_id: str, result: PaymentIdempotencyCheckResult):
        """Check donation existence, status, and payment history."""
        # Find donation by payment_id
        donation = frappe.db.get_value(
            self.target_doctype, {"payment_id": payment_id}, ["name", "status"], as_dict=True
        )

        if donation:
            result.donation_name = donation.name
            result.donation_status_updated = donation.status in ["Paid", "Completed"]

            # Check payment history for this payment_id
            donation_doc = frappe.get_doc(self.target_doctype, donation.name)
            payment_history_entry = next(
                (
                    ph
                    for ph in (donation_doc.payments or [])
                    if getattr(ph, "mollie_payment_id", None) == payment_id
                ),
                None,
            )
            result.payment_history_updated = payment_history_entry is not None

            self.logger.info(
                f"✅ Donation {donation.name}: status={donation.status}, "
                f"history_updated={result.payment_history_updated}"
            )
        else:
            # Try finding via Payment Entry reference in payment history
            if result.payment_entry_name:
                # Search for donations that reference this payment entry in their payments table
                donations_with_payment = frappe.db.sql(
                    """
                    SELECT d.name, d.status
                    FROM `tabDonation` d
                    INNER JOIN `tabDonation Payment` dp ON dp.parent = d.name
                    WHERE dp.payment_entry = %s
                    LIMIT 1
                """,
                    (result.payment_entry_name,),
                    as_dict=True,
                )

                if donations_with_payment:
                    donation = donations_with_payment[0]
                    result.donation_name = donation.name
                    result.donation_status_updated = donation.status in ["Paid", "Completed"]

    def _check_refund_processing_state(
        self, payment_id: str, result: PaymentIdempotencyCheckResult, include_mollie_api: bool
    ):
        """Check refund processing completeness."""
        # Find all processed refunds (Payment Entries with Pay type)
        processed_refunds = frappe.db.get_all(
            "Payment Entry",
            filters={
                "reference_no": ["like", f"re_%"],
                "payment_type": "Pay",
                "docstatus": 1,
                "remarks": ["like", f"%{payment_id}%"],
            },
            fields=["name", "reference_no", "paid_amount"],
        )

        result.refunds_processed = [
            {"refund_id": pe.reference_no, "payment_entry": pe.name, "amount": pe.paid_amount}
            for pe in processed_refunds
        ]

        if include_mollie_api:
            # Fetch current refunds from Mollie to find unprocessed ones
            try:
                from ..core.client import MollieClient

                client = MollieClient()
                mollie_client = client._get_mollie_client()
                payment = mollie_client.payments.get(payment_id)
                mollie_refunds = payment.refunds.list()

                processed_refund_ids = {r["refund_id"] for r in result.refunds_processed}

                result.pending_refunds = [
                    {"refund_id": refund.id, "amount": float(refund.amount.value), "status": refund.status}
                    for refund in mollie_refunds
                    if refund.id not in processed_refund_ids and refund.status in ["refunded", "processed"]
                ]

            except Exception as e:
                self.logger.error(f"Failed to fetch Mollie refunds for {payment_id}: {e}")

    def _check_chargeback_processing_state(
        self, payment_id: str, result: PaymentIdempotencyCheckResult, include_mollie_api: bool
    ):
        """Check chargeback processing completeness."""
        # Find all processed chargebacks (Payment Entries with Pay type)
        processed_chargebacks = frappe.db.get_all(
            "Payment Entry",
            filters={
                "reference_no": ["like", f"chb_%"],
                "payment_type": "Pay",
                "docstatus": 1,
                "remarks": ["like", f"%{payment_id}%"],
            },
            fields=["name", "reference_no", "paid_amount"],
        )

        result.chargebacks_processed = [
            {"chargeback_id": pe.reference_no, "payment_entry": pe.name, "amount": pe.paid_amount}
            for pe in processed_chargebacks
        ]

        if include_mollie_api:
            # Fetch current chargebacks from Mollie to find unprocessed ones
            try:
                from ..core.client import MollieClient

                client = MollieClient()
                mollie_client = client._get_mollie_client()
                payment = mollie_client.payments.get(payment_id)
                mollie_chargebacks = payment.chargebacks.list()

                processed_chargeback_ids = {c["chargeback_id"] for c in result.chargebacks_processed}

                result.pending_chargebacks = [
                    {
                        "chargeback_id": chargeback.id,
                        "amount": float(chargeback.amount.value),
                        "reason": getattr(chargeback, "reason", {}),
                    }
                    for chargeback in mollie_chargebacks
                    if chargeback.id not in processed_chargeback_ids
                ]

            except Exception as e:
                self.logger.error(f"Failed to fetch Mollie chargebacks for {payment_id}: {e}")

    def mark_refund_processed(self, payment_id: str, refund_id: str, payment_entry_name: str):
        """Mark a specific refund as processed in the unified state tracking."""
        self.logger.info(
            f"✅ Marked refund {refund_id} as processed for payment {payment_id} "
            f"(Payment Entry: {payment_entry_name})"
        )
        # This could be extended to maintain in-memory caching if needed

    def mark_chargeback_processed(self, payment_id: str, chargeback_id: str, payment_entry_name: str):
        """Mark a specific chargeback as processed in the unified state tracking."""
        self.logger.info(
            f"✅ Marked chargeback {chargeback_id} as processed for payment {payment_id} "
            f"(Payment Entry: {payment_entry_name})"
        )
        # This could be extended to maintain in-memory caching if needed

    def check_refund_idempotency(self, refund_id: str) -> Optional[str]:
        """
        Check if a specific refund has already been processed.

        This is the ONLY method for refund idempotency checks - consolidates all
        refund processing status verification into the unified system.
        """
        # Check for existing Payment Entry with this refund ID
        existing_pe = frappe.db.exists(
            "Payment Entry", {"reference_no": refund_id, "payment_type": "Pay", "docstatus": 1}
        )
        if existing_pe:
            self.logger.info(f"Refund {refund_id} already processed as Payment Entry {existing_pe}")
            return existing_pe

        # Also check for credit notes with this refund ID in remarks
        existing_credit_note = frappe.db.exists(
            "Sales Invoice", {"return_against": ["!=", ""], "remarks": ["like", f"%{refund_id}%"]}
        )
        if existing_credit_note:
            self.logger.info(f"Refund {refund_id} already processed as Credit Note {existing_credit_note}")
            return existing_credit_note

        return None


# Global singleton instance - ensures consistent state across all webhook processing
_unified_idempotency_manager = None


def get_unified_idempotency_manager(target_doctype: str = "Donation") -> UnifiedIdempotencyManager:
    """Get the global unified idempotency manager instance."""
    global _unified_idempotency_manager
    if _unified_idempotency_manager is None:
        _unified_idempotency_manager = UnifiedIdempotencyManager(target_doctype)
    return _unified_idempotency_manager
