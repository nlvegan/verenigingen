"""
Mollie Webhook Wrapper Service - UNIFIED IDEMPOTENCY VERSION

Complete consolidation of idempotency checks using the UnifiedIdempotencyManager.
This replaces the fragmented approach with a single authoritative source for
payment processing state across all webhook code paths.
"""

import json
import time
from types import SimpleNamespace
from typing import Any, Dict, Optional

import frappe

from verenigingen.verenigingen_payments.core.resilience import CircuitBreakerConfig, RetryConfig

# Import services for correct donation processing flow
from verenigingen.verenigingen_payments.services.bank_transaction_creator import get_bank_transaction_creator
from verenigingen.verenigingen_payments.services.donation_journal_entry_creator import (
    get_donation_journal_entry_creator,
)

# Import payment data extraction utilities
from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

# Import custom exceptions
from ..exceptions import MolliePaymentError, MollieSecurityError, MollieWebhookError

# Import logging and monitoring utilities
from ..utils.logging import MollieLogger, log_payment_processing, log_webhook_received
from ..utils.monitoring import record_operation_performance

# REMOVED: Old payment_webhook functions archived to break hybrid system
# These functions were causing duplicate Payment Entries by competing with unified idempotency
# TODO: Reimplement needed functionality using UnifiedIdempotencyManager


class UnifiedWebhookWrapperService:
    """
    UNIFIED webhook wrapper using UnifiedIdempotencyManager.

    This eliminates all fragmented idempotency checks by using a single
    authoritative source for payment processing state. Prevents duplicate
    payment entries by ensuring all code paths check the same unified state.
    """

    def __init__(self):
        self.logger = MollieLogger("unified_webhook_wrapper")
        # Enable verbose debug logging via site_config.mollie_debug_webhooks = True
        self._debug_mode = frappe.conf.get("mollie_debug_webhooks", False)
        # Import the unified idempotency manager - single source of truth
        from .unified_idempotency_manager import get_unified_idempotency_manager

        self.idempotency_manager = get_unified_idempotency_manager()

    def _process_pending_refunds(self, donation, payment_id: str, pending_refunds: list) -> list:
        """
        Process pending refunds for a payment.

        Extracted method to avoid duplication between new payment and fully processed paths.
        Both paths can have pending refunds that need processing.

        Architecture (mirrors donation processing):
            Mollie Refund → Bank Transaction → Journal Entry → Record Updates
                            (withdrawal)       (Debit: Income, Credit: Clearing)

        Args:
            donation: Donation document
            payment_id: Mollie payment ID
            pending_refunds: List of pending refund dicts with refund_id, amount, refund_date

        Returns:
            List of refund processing results
        """
        refund_results = []

        if not pending_refunds:
            return refund_results

        self.logger.info(f"🔄 Processing {len(pending_refunds)} pending refunds for {payment_id}")

        # Get configuration for Bank Transaction creation
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )
        from verenigingen.verenigingen_payments.services.donation_refund_journal_entry_creator import (
            get_donation_refund_journal_entry_creator,
        )

        bt_creator = get_bank_transaction_creator()
        je_creator = get_donation_refund_journal_entry_creator()

        # Get Mollie config for bank account
        config = bt_creator.get_mollie_bank_account_config()
        if config.get("error"):
            self.logger.error(f"❌ Mollie config error for refunds: {config['error']}")
            return [{"status": "error", "refund_id": "all", "message": config["error"]}]

        # Get party info for Bank Transaction (Customer linked to Donor)
        party_type = None
        party = None
        bank_party_name = None
        if donation.donor:
            donor_doc = frappe.db.get_value("Donor", donation.donor, ["donor_name", "customer"], as_dict=True)
            if donor_doc:
                bank_party_name = donor_doc.get("donor_name")
                if donor_doc.get("customer"):
                    party_type = "Customer"
                    party = donor_doc.get("customer")

        # Collect all payment history entries first (don't save in loop)
        payment_history_entries = []

        for pending_refund in pending_refunds:
            try:
                refund_id = pending_refund["refund_id"]
                refund_amount = pending_refund["amount"]
                refund_date = pending_refund.get("refund_date")

                # Parse refund_date to proper date format
                parsed_date = refund_date
                if isinstance(refund_date, str):
                    try:
                        from dateutil import parser

                        parsed_date = parser.parse(refund_date).date()
                    except (ValueError, TypeError, ImportError):
                        parsed_date = frappe.utils.getdate()
                elif not parsed_date:
                    parsed_date = frappe.utils.getdate()

                # Build unique reference number for this refund
                refund_reference = f"{payment_id}_refund_{refund_id}"

                # Step 1: Create Bank Transaction (withdrawal)
                self.logger.info(f"  Creating Bank Transaction for refund {refund_id}...")
                bank_transaction_name = bt_creator.create_from_dict(
                    transaction_data={
                        "date": parsed_date,
                        "amount": -float(refund_amount),  # Negative for withdrawal
                        "currency": "EUR",
                        "reference_number": refund_reference,
                        "description": f"Mollie Refund: {donation.name} | Refund ID: {refund_id}",
                        "party_type": party_type,
                        "party": party,
                        "bank_party_name": bank_party_name,
                    },
                    bank_account=config["bank_account"],
                    company=config["company"],
                    source_type="Mollie Refund",
                )

                if not bank_transaction_name:
                    self.logger.error(f"❌ Failed to create Bank Transaction for refund {refund_id}")
                    refund_results.append(
                        {
                            "status": "error",
                            "refund_id": refund_id,
                            "message": "Failed to create Bank Transaction",
                        }
                    )
                    continue

                self.logger.info(f"✅ Created Bank Transaction: {bank_transaction_name}")

                # Step 2: Create Journal Entry (reverses donation income)
                self.logger.info(f"  Creating Journal Entry for refund {refund_id}...")
                journal_entry_name = je_creator.create_refund_journal_entry(
                    refund_id=refund_id,
                    refund_amount=refund_amount,
                    refund_date=refund_date,
                    donation_doc=donation,
                    original_payment_id=payment_id,
                    bank_transaction_name=bank_transaction_name,
                )

                if not journal_entry_name:
                    self.logger.error(f"❌ Failed to create Journal Entry for refund {refund_id}")
                    refund_results.append(
                        {
                            "status": "error",
                            "refund_id": refund_id,
                            "bank_transaction": bank_transaction_name,
                            "message": "Failed to create Journal Entry",
                        }
                    )
                    continue

                self.logger.info(f"✅ Created Journal Entry: {journal_entry_name}")

                # Collect payment history entry (don't save yet)
                payment_history_entries.append(
                    {
                        "journal_entry": journal_entry_name,  # Link to Journal Entry
                        "amount": -float(refund_amount),  # Negative for refunds
                        "payment_date": parsed_date,
                        "mollie_payment_id": refund_id,  # Store refund ID for idempotency
                        "payment_status": "Refunded",
                        "payment_method": "Mollie",
                    }
                )

                refund_results.append(
                    {
                        "status": "success",
                        "refund_id": refund_id,
                        "bank_transaction": bank_transaction_name,
                        "journal_entry": journal_entry_name,
                        "amount": refund_amount,
                    }
                )
                # Mark as processed in unified manager (use JE name for tracking)
                self.idempotency_manager.mark_refund_processed(payment_id, refund_id, journal_entry_name)

            except Exception as e:
                self.logger.error(f"Failed to process pending refund {pending_refund.get('refund_id')}: {e}")
                refund_results.append(
                    {"status": "error", "refund_id": pending_refund.get("refund_id"), "message": str(e)}
                )

        # Now append all payment history entries in one batch and save once
        if payment_history_entries:
            try:
                donation.reload()  # Single reload before batch update

                # Filter out entries that already exist (idempotency check)
                # Check both payment_entry (for Payment Entries) and journal_entry (for Journal Entries)
                entries_to_add = []
                for entry in payment_history_entries:
                    # Check which type of entry this is
                    pe_name = entry.get("payment_entry")
                    je_name = entry.get("journal_entry")

                    already_exists = False
                    for p in donation.payments or []:
                        if pe_name and getattr(p, "payment_entry", None) == pe_name:
                            already_exists = True
                            break
                        if je_name and getattr(p, "journal_entry", None) == je_name:
                            already_exists = True
                            break

                    if already_exists:
                        doc_name = pe_name or je_name
                        self.logger.info(f"⏭️ Payment history entry already exists for {doc_name}, skipping")
                        continue

                    entries_to_add.append(entry)

                # Only save if we have new entries to add
                if entries_to_add:
                    # Allow modifying submitted document
                    donation.flags.ignore_validate_update_after_submit = True

                    for entry in entries_to_add:
                        donation.append("payments", entry)

                    donation.save()  # Single save after all appends
                    self.logger.info(f"✅ Updated payment history with {len(entries_to_add)} refund entries")
                else:
                    self.logger.info("⏭️ All refund payment history entries already exist, nothing to add")
            except Exception as hist_err:
                self.logger.error(f"❌ Failed to batch update payment history: {hist_err}")
                frappe.log_error(
                    f"Payment history batch update failed for {donation.name}: {hist_err}",
                    "Payment History Update Error",
                )

        return refund_results

    def _update_missing_payment_history(self, donation, payment_id: str, missing_entries: list) -> int:
        """
        Update payment history for refunds that have Payment Entries but missing history rows.

        Args:
            donation: Donation document
            payment_id: Payment ID
            missing_entries: List of dicts with refund_id, payment_entry, amount

        Returns:
            Count of successfully updated entries
        """
        if not missing_entries:
            return 0

        self.logger.info(f"📝 Updating {len(missing_entries)} missing payment history entries")

        try:
            donation.reload()

            # Check which entries actually need to be added (idempotency check)
            entries_to_add = []
            for entry in missing_entries:
                # Check if this Payment Entry already exists in payment history
                already_exists = any(
                    p.payment_entry == entry["payment_entry"] for p in (donation.payments or [])
                )

                if already_exists:
                    self.logger.info(
                        f"⏭️ Payment history entry already exists for PE {entry['payment_entry']}, skipping"
                    )
                    continue

                # Parse date if needed (PEs have dates, fetch from PE if available)
                pe_doc = frappe.get_doc("Payment Entry", entry["payment_entry"])
                payment_date = pe_doc.posting_date if pe_doc else frappe.utils.getdate()

                entries_to_add.append(
                    {
                        "payment_entry": entry["payment_entry"],
                        "amount": -float(entry["amount"]),
                        "payment_date": payment_date,
                        "mollie_payment_id": entry["refund_id"],  # Store refund ID in this field
                        "payment_status": "Refunded",
                        "payment_method": "Mollie",
                    }
                )

            # Only save if we actually have entries to add
            if entries_to_add:
                # Sort entries by payment_date chronologically before adding
                entries_to_add.sort(key=lambda x: x["payment_date"])

                # Allow modifying submitted document
                donation.flags.ignore_validate_update_after_submit = True

                for entry_data in entries_to_add:
                    donation.append("payments", entry_data)

                donation.save()
                self.logger.info(
                    f"✅ Updated {len(entries_to_add)} payment history entries (sorted chronologically)"
                )
                return len(entries_to_add)
            else:
                self.logger.info("⏭️ All payment history entries already exist, nothing to add")
                return 0
        except Exception as e:
            self.logger.error(f"❌ Failed to update missing payment history: {e}")
            frappe.log_error(
                f"Payment history backfill failed for {donation.name}: {e}", "Payment History Backfill Error"
            )
            return 0

    def process_payment_webhook(self, payment_id: str, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process payment webhook with UNIFIED idempotency management.

        This is the main entry point that ensures consistent state checking
        across all webhook processing scenarios.

        Now supports both donation and membership dues payments via PaymentTypeRouter.
        """
        start_time = time.time()

        try:
            self.logger.info(f"🚀 UNIFIED webhook processing started for payment {payment_id}")

            # STEP 0: PAYMENT TYPE CLASSIFICATION & ROUTING
            # Try to classify the payment type first to route to appropriate processor
            from .payment_type_router import get_payment_router

            router = get_payment_router()

            # Fetch payment to classify it
            try:
                payment = router.fetch_payment(payment_id)

                # PAYMENT PLAN PAYMENTS: finalize the installment and return
                # BEFORE donation classification (whose "donation" keyword would
                # otherwise misroute these to the donation lookup -> 500 loop).
                _md = (
                    payment.get("metadata")
                    if isinstance(payment, dict)
                    else getattr(payment, "metadata", None)
                )
                if isinstance(_md, dict) and _md.get("reference_doctype") == "Payment Plan Payment":
                    from .payment_plan_payment_handler import handle_payment_plan_payment

                    result = handle_payment_plan_payment(payment_id, payment)
                    result["duration_seconds"] = time.time() - start_time
                    return result

                classification = router.classify_payment(payment)

                self.logger.info(
                    f"📊 Payment classification: type={classification['payment_type']}, "
                    f"confidence={classification['confidence']}, matched_by={classification['matched_by']}"
                )

                # Route based on payment type
                from ..domain.payment_classification import PaymentType

                payment_type = classification["payment_type"]

                # ORDER payments: Create Bank Transactions for reconciliation
                if payment_type == PaymentType.ORDER:
                    self.logger.info(f"🛒 Routing {payment_id} to OrderPaymentProcessor")
                    result = router.route_payment(payment_id, payment)

                    # Add timing information
                    duration = time.time() - start_time
                    result["duration_seconds"] = duration
                    record_operation_performance(
                        "unified_webhook_processing",
                        duration,
                        result.get("status") not in ["error", "skipped"],
                    )

                    return result

                # DUES payments: Create Payment Entries for membership dues
                elif payment_type == PaymentType.DUES:
                    self.logger.info(f"🔀 Routing {payment_id} to DuesPaymentProcessor")
                    result = router.route_payment(payment_id, payment)

                    # Add timing information
                    duration = time.time() - start_time
                    result["duration_seconds"] = duration
                    record_operation_performance(
                        "unified_webhook_processing",
                        duration,
                        result.get("status") not in ["error", "skipped"],
                    )

                    return result

                # DONATION and UNKNOWN types: Continue with existing donation-focused logic
                # NOTE: Donation routing not yet implemented in PaymentTypeRouter
                # This maintains backward compatibility for donation and unclassified payments
                else:
                    self.logger.info(
                        f"📝 Continuing with existing donation processor for {payment_id} "
                        f"(type: {payment_type})"
                    )

            except Exception as classification_error:
                # If classification fails, continue with existing donation logic as fallback
                self.logger.warning(
                    f"⚠️ Payment classification failed for {payment_id}: {classification_error}. "
                    f"Falling back to donation processor"
                )

            # A recurring donation charge has no Donation yet, and STEP 1 below
            # is keyed on Donation.payment_id -- it would ask about a record that
            # does not exist. Materialise it first, then FALL THROUGH: the charge
            # now carries its own payment_id, so everything below works on it
            # unchanged.
            #
            # Do not return from here. check_payment_processing_state is also the
            # only discovery of pending refunds and chargebacks on this webhook
            # (Mollie signals a refund by re-posting the same payment id), so an
            # early return would strand every refund of every recurring charge
            # while first payments kept theirs. Issue #345.
            from .recurring_donation_charge import (
                RecurringChargeOriginMissing,
                ensure_donation_for_recurring_charge,
            )

            # self._fetch_payment_from_mollie rather than the `payment` bound
            # inside the classification try: that name is unbound when
            # classification raised, and the branch must still run in that case.
            # The normalised dict is a shape read_payment_field handles.
            #
            # The cost is one extra Mollie GET on EVERY donation / unknown /
            # classification-failed webhook, not just on charges: the argument is
            # evaluated before the service can decline. That is the price of not
            # trusting a `payment` that may be unbound, and it is why the fetch is
            # guarded below rather than left to the outer handler.
            try:
                charge_payment = self._fetch_payment_from_mollie(payment_id)
            except MolliePaymentError as fetch_error:
                # Mollie is unreachable. STEP 1's include_mollie_api check hits the
                # same outage and returns 503 + Retry-After, which is the designed
                # degradation; do not pre-empt it with a generic 500. Not a
                # swallow: Mollie re-delivers either way, and the charge is booked
                # on the retry.
                self.logger.error(f"Charge fetch for {payment_id} failed, deferring to STEP 1: {fetch_error}")
                charge_payment = None

            if charge_payment is not None:
                try:
                    charge_donation = ensure_donation_for_recurring_charge(charge_payment)
                    if charge_donation:
                        self.logger.info(
                            f"💶 Recurring charge {payment_id} booked to donation {charge_donation}"
                        )
                except RecurringChargeOriginMissing as e:
                    # Money received and unattributable. Report failure so Mollie
                    # re-delivers rather than swallowing it into a 200.
                    duration = time.time() - start_time
                    record_operation_performance("unified_webhook_processing", duration, False)
                    return {
                        "status": "error",
                        "message": str(e),
                        "payment_id": payment_id,
                        "duration_seconds": duration,
                    }

            # STEP 1: UNIFIED IDEMPOTENCY CHECK - single source of truth
            self.logger.info(f"🔍 STEP 1: Unified idempotency check for {payment_id}")
            processing_state = self.idempotency_manager.check_payment_processing_state(
                payment_id, include_mollie_api=True
            )

            # DEBUG: Log detailed processing state (enable with mollie_debug_webhooks)
            if self._debug_mode:
                self.logger.info(f"🔬 IDEMPOTENCY STATE for {payment_id}:")
                self.logger.info(f"  - payment_entry_exists: {processing_state.payment_entry_exists}")
                self.logger.info(f"  - payment_entry_name: {processing_state.payment_entry_name}")
                self.logger.info(f"  - payment_history_updated: {processing_state.payment_history_updated}")
                self.logger.info(f"  - donation_status_updated: {processing_state.donation_status_updated}")
                self.logger.info(f"  - is_fully_processed(): {processing_state.is_fully_processed()}")
                self.logger.info(
                    f"  - needs_payment_processing(): {processing_state.needs_payment_processing()}"
                )
                self.logger.info(f"  - pending_refunds count: {len(processing_state.pending_refunds)}")
                self.logger.info(
                    f"  - payment_history_missing count: {len(processing_state.payment_history_missing)}"
                )
                self.logger.info(f"  - refunds_processed count: {len(processing_state.refunds_processed)}")

            # CRITICAL FIX: Check if refund/chargeback validation failed due to Mollie API errors
            if processing_state.refund_check_failed or processing_state.chargeback_check_failed:
                self.logger.error("❌ Cannot process webhook - Mollie API validation failed")
                duration = time.time() - start_time
                record_operation_performance("unified_webhook_processing", duration, False)

                # Set HTTP 503 status for service unavailability
                frappe.local.response.http_status_code = 503
                frappe.local.response["Retry-After"] = "60"  # Mollie should retry after 60 seconds

                response = {
                    "status": "service_unavailable",
                    "message": "Mollie API unavailable - cannot verify refund/chargeback state",
                    "payment_id": payment_id,
                    "duration_seconds": duration,
                }

                # Include debug info only in developer mode
                if frappe.conf.get("developer_mode"):
                    response["debug"] = {
                        "refund_check_failed": processing_state.refund_check_failed,
                        "chargeback_check_failed": processing_state.chargeback_check_failed,
                    }

                return response

            # STEP 2: Handle based on unified state
            if processing_state.is_fully_processed():
                self.logger.info(f"🎯 ROUTING: {payment_id} → _handle_fully_processed_payment")
                return self._handle_fully_processed_payment(payment_id, processing_state, start_time)
            elif processing_state.needs_payment_processing():
                self.logger.info(f"🎯 ROUTING: {payment_id} → _handle_new_payment_processing")
                return self._handle_new_payment_processing(
                    payment_id, webhook_data, processing_state, start_time
                )
            else:
                # Partial processing - determine what needs to be completed
                self.logger.info(f"🎯 ROUTING: {payment_id} → _handle_partial_processing")
                return self._handle_partial_processing(payment_id, webhook_data, processing_state, start_time)

        except Exception as e:
            self.logger.error(f"❌ Unified webhook processing failed for {payment_id}: {e}")
            duration = time.time() - start_time
            record_operation_performance("unified_webhook_processing", duration, False)
            return {
                "status": "error",
                "message": f"Webhook processing failed: {str(e)}",
                "payment_id": payment_id,
                "duration_seconds": duration,
            }

    def _handle_fully_processed_payment(
        self, payment_id: str, processing_state, start_time: float
    ) -> Dict[str, Any]:
        """Handle payments that are already fully processed."""
        self.logger.info(f"✅ Payment {payment_id} already fully processed")

        # DEBUG: Log detailed state information (enable with mollie_debug_webhooks)
        if self._debug_mode:
            self.logger.info(f"🔬 FULLY PROCESSED HANDLER for {payment_id}:")
            self.logger.info(f"  - Payment Entry: {processing_state.payment_entry_name}")
            self.logger.info(f"  - Payment History Updated: {processing_state.payment_history_updated}")
            self.logger.info(f"  - Donation Status Updated: {processing_state.donation_status_updated}")
            self.logger.info(f"  - Pending Refunds: {len(processing_state.pending_refunds)}")

        # Find donation for potential refund/history processing
        donation = find_donation_for_payment_by_id(payment_id)

        # Handle any pending refunds/chargebacks identified by unified check
        refund_results = []
        if processing_state.has_pending_refunds():
            if not donation:
                self.logger.error(f"No donation found for payment {payment_id}, cannot process refunds")
                refund_results = [
                    {"status": "error", "message": f"No donation found for payment {payment_id}"}
                ]
            else:
                # Use extracted method to process refunds
                refund_results = self._process_pending_refunds(
                    donation, payment_id, processing_state.pending_refunds
                )

        # Handle refunds with missing payment history
        if donation and processing_state.payment_history_missing:
            self._update_missing_payment_history(
                donation, payment_id, processing_state.payment_history_missing
            )

        # NOTE: subscription activation is deliberately NOT retried here.
        # This branch cannot be reached for a donation today -- is_fully_processed()
        # keys off a submitted Payment Entry that the Bank Transaction + Journal
        # Entry architecture never creates (issue #344) -- so every re-delivery
        # lands on the new-payment path, where activation IS retried. Wiring it in
        # here would cost an unconditional _fetch_payment_from_mollie() on a path
        # that needs no payment data and whose refund/chargeback handling would
        # then break on any Mollie fetch failure, in exchange for a benefit that
        # only materialises once #344 is fixed. #344 carries the note to wire
        # activation in at that point.

        # Handle any pending chargebacks
        chargeback_results = []
        if processing_state.has_pending_chargebacks():
            self.logger.info(f"Processing {len(processing_state.pending_chargebacks)} pending chargebacks")
            # TODO: Implement chargeback processing when needed

        # CRITICAL FIX: Determine overall success based on refund processing results
        failed_refunds = [r for r in refund_results if r.get("status") == "error"]
        succeeded_refunds = [r for r in refund_results if r.get("status") == "success"]

        overall_success = len(failed_refunds) == 0
        duration = time.time() - start_time
        record_operation_performance(
            "unified_webhook_processing", duration, overall_success, {"idempotent": True}
        )

        if failed_refunds:
            # CRITICAL: Return error status if ANY refunds failed - this triggers Mollie retry
            self.logger.error(f"❌ {len(failed_refunds)} refunds failed for payment {payment_id}")
            return {
                "status": "error",
                "message": f"Payment processed but {len(failed_refunds)} refunds failed - requires retry",
                "payment_id": payment_id,
                "idempotent": True,
                "unified_state": {
                    "payment_entry_exists": processing_state.payment_entry_exists,
                    "payment_history_updated": processing_state.payment_history_updated,
                    "donation_status_updated": processing_state.donation_status_updated,
                    "refunds_processed": len(processing_state.refunds_processed),
                    "pending_operations_handled": len(succeeded_refunds),
                },
                "refund_processing": refund_results,
                "failed_refunds": failed_refunds,
                "succeeded_refunds": succeeded_refunds,
                "duration_seconds": duration,
            }
        else:
            # All refunds succeeded or no refunds to process
            return {
                "status": "success",
                "message": f"Payment already processed, handled {len(refund_results)} pending operations",
                "payment_id": payment_id,
                "idempotent": True,
                "unified_state": {
                    "payment_entry_exists": processing_state.payment_entry_exists,
                    "payment_history_updated": processing_state.payment_history_updated,
                    "donation_status_updated": processing_state.donation_status_updated,
                    "refunds_processed": len(processing_state.refunds_processed),
                    "pending_operations_handled": len(refund_results) + len(chargeback_results),
                },
                "refund_processing": refund_results,
                "duration_seconds": duration,
            }

    def _handle_new_payment_processing(
        self, payment_id: str, webhook_data: Dict[str, Any], processing_state, start_time: float
    ) -> Dict[str, Any]:
        """Handle payments that need initial processing."""
        self.logger.info(
            f"🔄 Payment {payment_id} needs processing: "
            f"PE={processing_state.payment_entry_exists}, "
            f"PH={processing_state.payment_history_updated}, "
            f"DS={processing_state.donation_status_updated}"
        )

        try:
            # Fetch payment data directly from Mollie API (unified approach)
            payment_data = self._fetch_payment_from_mollie(payment_id)

            # Validate payment status
            if payment_data.get("status") != "paid":
                self.logger.info(f"Payment {payment_id} not in paid status: {payment_data.get('status')}")
                return {
                    "status": "skipped",
                    "message": f"Payment status '{payment_data.get('status')}' not processable",
                    "payment_id": payment_id,
                }

            # Find the donation for this payment
            donation = find_donation_for_payment_by_id(payment_id)
            if not donation:
                self.logger.error(f"❌ No donation found for payment {payment_id}")
                return {
                    "status": "error",
                    "message": f"No donation found for payment {payment_id}",
                    "payment_id": payment_id,
                }

            # =========================================================================
            # NEW ARCHITECTURE: Bank Transaction → Journal Entry → Record Updates
            # =========================================================================

            # Step 1-2: Create Bank Transaction and Journal Entry
            financial_result = self._create_donation_financial_entries(donation, payment_data)
            if not financial_result:
                return {
                    "status": "error",
                    "message": "Failed to create financial entries (Bank Transaction / Journal Entry)",
                    "payment_id": payment_id,
                }

            # A partial result is TRUTHY: the Bank Transaction landed and the
            # Journal Entry did not. Letting it through returns 200, Mollie never
            # re-delivers, and the donor is debited against half a booking.
            # Reported as an error so the delivery is retried -- both creators are
            # idempotent per payment id, so a retry completes the missing half
            # rather than duplicating the finished one.
            if financial_result.get("partial_success"):
                return {
                    "status": "error",
                    "message": (
                        f"Payment {payment_id} recorded a Bank Transaction "
                        f"({financial_result.get('bank_transaction_name')}) but no Journal Entry"
                    ),
                    "payment_id": payment_id,
                    "bank_transaction": financial_result.get("bank_transaction_name"),
                }

            journal_entry_name = financial_result.get("journal_entry_name")
            bank_transaction_name = financial_result.get("bank_transaction_name")

            # Step 3: Create the Mollie subscription this first payment set up.
            # Runs BEFORE the status update so _update_donation_status sees the
            # subscription id and can mark the donation Recurring.
            activation = self._activate_donation_subscription(donation, payment_data)

            # Step 4: Update donation status and metadata
            self._update_donation_status(donation, payment_data)

            # Steps 5-7: the three financial-history tables.
            #
            # Their results are collected rather than discarded. Each of these
            # returns False -- it does not raise -- for a builder that returns None
            # or raises, a TimestampMismatchError surviving five attempts, an
            # `update_child_table` that fails three retries, and anything caught by
            # the manager's outer `except Exception`. Discarding that answered 200
            # to Mollie, so the delivery was never retried (#449).
            #
            # How much is lost depends on the table, and is smaller than it looks
            # for one of them. `donor_history` has THREE writers: Donation's
            # `after_insert` and `on_update` doc events both call
            # DonationHistoryManager, and `on_update` fires from the `donation.save()`
            # in _update_donation_status just above -- so on the measured
            # first-payment path the row is already present and already correct, and
            # this write adds only Mollie's paid_at date. It is NOT the sole writer,
            # and an earlier version of this comment wrongly said the entry was lost
            # permanently. Where it IS the only writer is the case where that save
            # itself failed, which _update_donation_status silently swallows.
            #
            # Asking Mollie to re-deliver is safe here: the money-side steps are
            # each individually idempotent on the payment id
            # (`bank_transaction_creator._check_existing_by_reference` and the
            # donation Journal Entry creator's own idempotency check), so a retry
            # cannot double-book even though the top-level `is_fully_processed()`
            # gate is broken for donations (#344) and every re-delivery therefore
            # lands back on this path.
            #
            # All three answer True when there is nothing to do -- no donor, no
            # member, an entry already present -- so False here means a real failure.
            history_failures = []

            if not self._update_donation_payment_history_atomic(donation, payment_data, journal_entry_name):
                history_failures.append("donation payment history")

            if not self._update_donor_record(donation, payment_data):
                history_failures.append("donor_history")

            if not self._update_member_payment_history(donation, payment_data, journal_entry_name):
                history_failures.append("member payment history")

            # Check for pending refunds even during new payment processing
            # Refunds may exist if payment was processed then immediately refunded
            refund_results = self._process_pending_refunds(
                donation, payment_id, processing_state.pending_refunds
            )

            # Same defect as the history writes above, and it has to be detected HERE
            # rather than where the result dict is decorated below -- that block runs
            # after the early return and an append there would be dead code.
            #
            # A failed refund booking answered 200, so Mollie never re-delivered and
            # the GL permanently overstated income. The CORRECT handling already
            # existed verbatim in _handle_fully_processed_payment -- but
            # is_fully_processed() is permanently false for donations (#344), so that
            # handler is dead code and this was the only reachable path. Mollie
            # signals a refund by re-posting the same payment id, which is how every
            # donation refund arrives.
            failed_refunds = [r for r in (refund_results or []) if r.get("status") == "error"]
            if failed_refunds:
                self.logger.error(f"{len(failed_refunds)} refund booking(s) failed for {payment_id}")
                history_failures.append(f"{len(failed_refunds)} refund booking(s)")

            # A history write that failed must not be reported as success: the
            # financial entries are already booked and idempotent, so a non-2xx buys
            # a re-delivery that cannot double-book (measured: one JE, one Bank
            # Transaction, and a GL debit of the charge amount rather than twice it).
            #
            # Deliberately NOT claiming the re-delivery "completes what is missing".
            # Measured counter-example: if the Journal Entry stayed at docstatus 0,
            # the re-delivery adopts the draft (the creator's idempotency filter is
            # `docstatus != 2`) and then reconciles the Bank Transaction against it,
            # producing a bank line marked Reconciled against an unposted JE with no
            # GL entries -- and reporting success, which ends the retry ladder. That
            # is #383's mechanism reached through the JE creator; pre-existing, but a
            # re-delivery can make a visibly broken state a silently broken one.
            if history_failures:
                return {
                    "status": "error",
                    "message": (
                        f"Payment {payment_id} booked, but "
                        f"{', '.join(history_failures)} could not be written"
                    ),
                    "payment_id": payment_id,
                    "bank_transaction": bank_transaction_name,
                    "journal_entry": journal_entry_name,
                    "donation_id": donation.name,
                    "history_failures": history_failures,
                    "refund_failures": failed_refunds,
                    "duration_seconds": time.time() - start_time,
                }

            # Return success result
            result = {
                "status": "success",
                "message": f"Payment {payment_id} processed successfully",
                "payment_id": payment_id,
                "bank_transaction": bank_transaction_name,
                "journal_entry": journal_entry_name,
                "donation_id": donation.name,
                "amount": payment_data.get("amount", {}).get("value"),
            }

            # Include refund processing results if any
            if refund_results:
                result["refunds_processed"] = refund_results
                # Failures are detected and reported above, before the early return;
                # reaching here means there were none.

            if activation:
                result["subscription_activation"] = activation
                # A recurring donor whose subscription was not created is the
                # whole of issue #343, and there is no sweep that would find them
                # later. Report failure so Mollie re-delivers on its own retry
                # schedule -- safe because the Bank Transaction and Journal Entry
                # creators are idempotent per payment id, and activation itself
                # is guarded against creating a second subscription. Permanent
                # refusals (a bad interval, missing metadata) are excluded: a
                # retry would produce the identical refusal.
                if activation.get("status") == "error" and not activation.get("permanent"):
                    result["status"] = "error"
                    result["message"] = (
                        f"Payment {payment_id} recorded, but creating the Mollie subscription "
                        f"failed: {activation.get('message')}"
                    )

            duration = time.time() - start_time
            record_operation_performance(
                "unified_webhook_processing", duration, result.get("status") == "success"
            )

            # Add unified state information to result
            if isinstance(result, dict):
                result["unified_processing"] = True
                result["duration_seconds"] = duration

                # Add processing state to response only in debug mode
                if self._debug_mode:
                    result["debug_processing_state"] = {
                        "payment_entry_exists": processing_state.payment_entry_exists,
                        "payment_entry_name": processing_state.payment_entry_name,
                        "payment_history_updated": processing_state.payment_history_updated,
                        "donation_status_updated": processing_state.donation_status_updated,
                        "is_fully_processed": processing_state.is_fully_processed(),
                        "needs_payment_processing": processing_state.needs_payment_processing(),
                        "pending_refunds_count": len(processing_state.pending_refunds),
                    }

            return result

        except Exception as e:
            self.logger.error(f"❌ Payment processing failed for {payment_id}: {e}")
            duration = time.time() - start_time
            record_operation_performance("unified_webhook_processing", duration, False)
            return {
                "status": "error",
                "message": f"Payment processing failed: {str(e)}",
                "payment_id": payment_id,
                "duration_seconds": duration,
            }

    def _handle_partial_processing(
        self, payment_id: str, webhook_data: Dict[str, Any], processing_state, start_time: float
    ) -> Dict[str, Any]:
        """Handle payments that are partially processed."""
        self.logger.info(f"🔄 Payment {payment_id} partially processed, completing missing components")

        # Determine what components need completion
        # NOTE: payment_entry_exists now refers to financial entries (BT + JE)
        missing_components = []
        if not processing_state.payment_entry_exists:
            missing_components.append("financial_entries")  # BT + JE
        if not processing_state.payment_history_updated:
            missing_components.append("payment_history")
        if not processing_state.donation_status_updated:
            missing_components.append("donation_status")

        self.logger.info(f"Missing components for {payment_id}: {missing_components}")

        try:
            # Fetch payment data directly from Mollie API (unified approach)
            payment_data = self._fetch_payment_from_mollie(payment_id)

            # Find the donation for this payment
            donation = find_donation_for_payment_by_id(payment_id)
            if not donation:
                self.logger.error(f"❌ No donation found for payment {payment_id}")
                return {
                    "status": "error",
                    "message": f"No donation found for payment {payment_id}",
                    "payment_id": payment_id,
                }

            # Process missing components based on unified state
            results = []
            journal_entry_name = None
            # A Bank Transaction with no Journal Entry is half a booking, not a
            # completed component -- the same defect as in
            # _handle_new_payment_processing. Tracked separately from `results`
            # because "Journal Entry creation failed (partial)" being a non-empty
            # string does not make `results` falsy, so it could not fail the
            # overall status on its own.
            financial_entries_incomplete = False

            if "financial_entries" in missing_components:
                # Create Bank Transaction + Journal Entry using new architecture
                financial_result = self._create_donation_financial_entries(donation, payment_data)
                if financial_result:
                    results.append(
                        f"Bank Transaction created: {financial_result.get('bank_transaction_name')}"
                    )
                    if financial_result.get("journal_entry_name"):
                        results.append(f"Journal Entry created: {financial_result.get('journal_entry_name')}")
                        journal_entry_name = financial_result.get("journal_entry_name")
                    else:
                        results.append("Journal Entry creation failed (partial)")
                        financial_entries_incomplete = True
                else:
                    results.append("Financial entries creation failed")
                    financial_entries_incomplete = True

            # NOTE: subscription activation is deliberately NOT called here.
            # This branch is currently unreachable -- needs_payment_processing()
            # is `not is_fully_processed()`, so process_payment_webhook's else
            # can never be taken -- and if it is ever revived, activation would
            # need the same ordering guarantee it has in the new-payment path
            # (it must precede _update_donation_status, which only runs here when
            # "donation_status" is among the missing components).

            if "donation_status" in missing_components:
                self._update_donation_status(donation, payment_data)
                results.append("Donation status updated")

            if "payment_history" in missing_components:
                # Try to get existing journal entry name from database if not created above.
                # Journal Entry has no `reference_no` column (that is a Payment Entry field);
                # the donation Journal Entry creator stores the Mollie payment id in
                # `cheque_no`, so we must match on that. Querying `reference_no` here raised
                # "Unknown column 'reference_no'" and aborted the whole partial-processing
                # backfill whenever the JE had to be looked up from the DB.
                if not journal_entry_name:
                    journal_entry_name = frappe.db.get_value(
                        "Journal Entry",
                        {"cheque_no": payment_id, "docstatus": ["!=", 2]},
                        "name",
                    )
                if self._update_donation_payment_history_atomic(donation, payment_data, journal_entry_name):
                    results.append("Donation payment history updated")
                else:
                    results.append("Donation payment history update failed")

                # Also update Donor and Member records
                if self._update_donor_record(donation, payment_data):
                    results.append("Donor record updated")
                if self._update_member_payment_history(donation, payment_data, journal_entry_name):
                    results.append("Member payment history updated")

            # CRITICAL FIX: Also handle refund payment history backfill during partial processing
            # This ensures that when main payment history is missing, we also check for missing refund history
            if donation and processing_state.payment_history_missing:
                refund_history_count = self._update_missing_payment_history(
                    donation, payment_id, processing_state.payment_history_missing
                )
                if refund_history_count > 0:
                    results.append(f"Backfilled {refund_history_count} refund payment history entries")

            result = {
                "status": "success" if results and not financial_entries_incomplete else "error",
                "message": f"Partial processing completed: {', '.join(results)}",
                "payment_id": payment_id,
                "components_processed": results,
            }

            duration = time.time() - start_time
            record_operation_performance(
                "unified_webhook_processing", duration, result.get("status") == "success"
            )

            # Add partial processing information
            if isinstance(result, dict):
                result["partial_processing"] = True
                result["completed_components"] = missing_components
                result["duration_seconds"] = duration

            return result

        except Exception as e:
            self.logger.error(f"❌ Partial processing completion failed for {payment_id}: {e}")
            duration = time.time() - start_time
            record_operation_performance("unified_webhook_processing", duration, False)
            return {
                "status": "error",
                "message": f"Partial processing completion failed: {str(e)}",
                "payment_id": payment_id,
                "missing_components": missing_components,
                "duration_seconds": duration,
            }

    def process_reversal_webhook(
        self,
        payment_id: str,
        reversal_id: str,
        amount: float,
        reversal_type: str,
        reversal_date: Optional[str] = None,
        reason: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Generic reversal processor - handles refunds, chargebacks, and other payment reversals.

        Args:
            payment_id: Mollie payment ID
            reversal_id: ID of the reversal (refund_id or chargeback_id)
            amount: Reversal amount
            reversal_type: Type of reversal ("refund" or "chargeback")
            reversal_date: Date of the reversal (optional)
            reason: Reason dict for chargebacks (optional, contains code and description)

        Returns:
            Dict with processing results
        """
        start_time = time.time()

        try:
            # Input validation
            ALLOWED_REVERSAL_TYPES = {"refund", "chargeback"}
            if reversal_type not in ALLOWED_REVERSAL_TYPES:
                error_msg = f"Invalid reversal_type: {reversal_type}. Must be one of {ALLOWED_REVERSAL_TYPES}"
                self.logger.error(error_msg)
                return {
                    "status": "error",
                    "message": error_msg,
                    "payment_id": payment_id,
                    "reversal_id": reversal_id,
                }

            # Validate amount is positive
            if amount <= 0:
                error_msg = f"Invalid amount: {amount}. Amount must be greater than 0"
                self.logger.error(error_msg)
                return {
                    "status": "error",
                    "message": error_msg,
                    "payment_id": payment_id,
                    "reversal_id": reversal_id,
                    f"{reversal_type}_id": reversal_id,
                }

            self.logger.info(
                f"🔄 Processing {reversal_type} webhook for {reversal_id} (payment: {payment_id})"
            )

            # Check unified state first
            processing_state = self.idempotency_manager.check_payment_processing_state(payment_id)

            if not processing_state.payment_entry_exists:
                return {
                    "status": "error",
                    "message": f"Cannot process {reversal_type} - original payment {payment_id} not found",
                    "payment_id": payment_id,
                    f"{reversal_type}_id": reversal_id,
                }

            # Check if this specific reversal is already processed (type-specific check)
            # Build reference_no pattern that includes reversal type for proper collision prevention
            reference_pattern = f"{payment_id}_{reversal_type}_{reversal_id}"
            existing_reversal = frappe.db.get_value(
                "Payment Entry",
                {"payment_type": "Pay", "reference_no": reference_pattern, "docstatus": 1},
                "name",
            )

            if existing_reversal:
                self.logger.info(
                    f"✅ {reversal_type.capitalize()} {reversal_id} already processed: {existing_reversal}"
                )
                return {
                    "status": "success",
                    "message": f"{reversal_type.capitalize()} {reversal_id} already processed",
                    "payment_id": payment_id,
                    f"{reversal_type}_id": reversal_id,
                    "existing_reference": existing_reversal,
                    "idempotent": True,
                }

            # Process the reversal using unified approach
            from ..utils.unified_payment_entry_creator import create_unified_payment_entry
            from ..utils.webhook_utilities import get_donation_by_payment_id, standardized_webhook_response

            # Find donation using utility
            donation_doc = get_donation_by_payment_id(payment_id)
            if not donation_doc:
                return standardized_webhook_response(
                    "ignored", f"Original donation not found for payment {payment_id}", payment_id=payment_id
                )

            # Build description based on reversal type
            if reversal_type == "chargeback" and reason:
                reason_text = f"{reason.get('code', 'unknown')}: {reason.get('description', '')}"
                description = f"Chargeback {reversal_id} - Reason: {reason_text}"
            else:
                description = f"{reversal_type.capitalize()} {reversal_id} of €{amount:.2f}"

            # Create reversal Payment Entry using unified creator
            reversal_pe = create_unified_payment_entry(
                donation_doc=donation_doc,
                mollie_payment_id=payment_id,
                amount=amount,
                payment_type="Pay",  # Reversals are outgoing
                reference_suffix=f"_{reversal_type}_{reversal_id}",
                refund_date=reversal_date,
                description=description,
            )

            # Update donation payment history for reversals
            if reversal_pe:
                try:
                    # Parse reversal date to proper format
                    parsed_date = reversal_date
                    if isinstance(reversal_date, str):
                        try:
                            from dateutil import parser

                            parsed_date = parser.parse(reversal_date).date()
                        except (ValueError, TypeError, ImportError):
                            parsed_date = frappe.utils.getdate()
                    elif not parsed_date:
                        parsed_date = frappe.utils.getdate()

                    # Append payment history entry for reversal
                    donation_doc.reload()

                    # Allow modifying submitted document
                    donation_doc.flags.ignore_validate_update_after_submit = True

                    donation_doc.append(
                        "payments",
                        {
                            "payment_entry": reversal_pe.name,
                            "amount": -float(amount),  # Negative for reversals
                            "payment_date": parsed_date,
                            "mollie_payment_id": reversal_id,  # Store reversal ID
                            "payment_status": "Refunded" if reversal_type == "refund" else "Chargeback",
                            "payment_method": "Mollie",
                        },
                    )
                    donation_doc.save()
                    self.logger.info(f"✅ Updated payment history with {reversal_type} entry")
                except Exception as hist_err:
                    self.logger.error(f"❌ Failed to update payment history for {reversal_type}: {hist_err}")
                    frappe.log_error(
                        f"Payment history update failed for {donation_doc.name} {reversal_type}: {hist_err}",
                        "Reversal Payment History Update Error",
                    )

            # Create standardized result
            if reversal_pe:
                result = standardized_webhook_response(
                    "success",
                    f"{reversal_type.capitalize()} Payment Entry created: {reversal_pe.name}",
                    payment_entry_id=reversal_pe.name,
                    payment_id=payment_id,
                )
                result[f"{reversal_type}_id"] = reversal_id
            else:
                result = standardized_webhook_response(
                    "error",
                    f"Failed to create {reversal_type} Payment Entry",
                    payment_id=payment_id,
                )
                result[f"{reversal_type}_id"] = reversal_id

            # Mark as processed if successful
            if result.get("status") == "success":
                if reversal_type == "refund":
                    self.idempotency_manager.mark_refund_processed(
                        payment_id, reversal_id, result.get("payment_entry_id")
                    )
                elif reversal_type == "chargeback":
                    self.idempotency_manager.mark_chargeback_processed(
                        payment_id, reversal_id, result.get("payment_entry_id")
                    )

            duration = time.time() - start_time
            result["duration_seconds"] = duration

            return result

        except Exception as e:
            self.logger.error(f"❌ {reversal_type.capitalize()} webhook processing failed: {e}")
            duration = time.time() - start_time
            return {
                "status": "error",
                "message": f"{reversal_type.capitalize()} processing failed: {str(e)}",
                "payment_id": payment_id,
                f"{reversal_type}_id": reversal_id,
                "duration_seconds": duration,
            }

    def process_refund_webhook(self, payment_id: str, refund_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process refund webhook - delegates to generic reversal processor.

        Args:
            payment_id: Mollie payment ID
            refund_data: Refund data from webhook

        Returns:
            Dict with processing results
        """
        from ..utils.webhook_utilities import safe_extract_amount, safe_extract_date

        refund_id = refund_data.get("id") or refund_data.get("refund", {}).get("id")
        refund_amount = safe_extract_amount(refund_data)
        refund_date = safe_extract_date(refund_data)

        return self.process_reversal_webhook(
            payment_id=payment_id,
            reversal_id=refund_id,
            amount=refund_amount,
            reversal_type="refund",
            reversal_date=refund_date,
        )

    def process_chargeback_webhook(self, payment_id: str, chargeback_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process chargeback webhook - delegates to generic reversal processor.

        Args:
            payment_id: Mollie payment ID
            chargeback_data: Chargeback data from webhook

        Returns:
            Dict with processing results
        """
        from ..utils.webhook_utilities import safe_extract_amount, safe_extract_date

        chargeback_id = chargeback_data.get("id") or chargeback_data.get("chargeback", {}).get("id")
        chargeback_amount = safe_extract_amount(chargeback_data)
        chargeback_date = safe_extract_date(chargeback_data)
        reason = chargeback_data.get("reason") or chargeback_data.get("chargeback", {}).get("reason")

        return self.process_reversal_webhook(
            payment_id=payment_id,
            reversal_id=chargeback_id,
            amount=chargeback_amount,
            reversal_type="chargeback",
            reversal_date=chargeback_date,
            reason=reason,
        )

    def _fetch_payment_from_mollie(self, payment_id: str) -> Dict[str, Any]:
        """Fetch payment data from Mollie API."""
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            mollie = mollie_settings.get_mollie_client()
            payment = mollie.payments.get(payment_id)

            # Handle both dict and object formats from Mollie client
            if isinstance(payment, dict):
                # Handle dictionary format
                return {
                    "id": payment.get("id"),
                    "status": payment.get("status"),
                    "amount": payment.get("amount", {}),
                    "description": payment.get("description"),
                    "metadata": payment.get("metadata") or {},
                    "created_at": payment.get("createdAt") or payment.get("created_at"),
                    "paid_at": payment.get("paidAt") or payment.get("paid_at"),
                    "method": payment.get("method"),
                    # Mollie names these camelCase; every reader downstream asks
                    # for snake_case. Omitting them made three readers dead:
                    # the donation Recurring/One-time stamp, Donor.
                    # mollie_subscription_id, and the donor history entry type
                    # all silently saw None on every payment. See issue #343.
                    "sequence_type": payment.get("sequenceType") or payment.get("sequence_type"),
                    "customer_id": payment.get("customerId") or payment.get("customer_id"),
                    "subscription_id": payment.get("subscriptionId") or payment.get("subscription_id"),
                    # Same omission, same shape of bug: a recurring charge's
                    # Donation records mollie_mandate_id, and this dict is what
                    # the webhook hands the booking path, so without it every
                    # charge booked from a webhook stored None for the mandate.
                    "mandate_id": payment.get("mandateId") or payment.get("mandate_id"),
                }
            else:
                # Handle object format
                amount_obj = getattr(payment, "amount", None)
                if hasattr(amount_obj, "value"):
                    amount = {"value": amount_obj.value, "currency": amount_obj.currency}
                elif isinstance(amount_obj, dict):
                    amount = {"value": amount_obj.get("value"), "currency": amount_obj.get("currency")}
                else:
                    amount = {"value": "0", "currency": "EUR"}

                return {
                    "id": getattr(payment, "id", None),
                    "status": getattr(payment, "status", None),
                    "amount": amount,
                    "description": getattr(payment, "description", None),
                    "metadata": getattr(payment, "metadata", None) or {},
                    "created_at": getattr(payment, "created_at", None),
                    "paid_at": getattr(payment, "paid_at", None),
                    "method": getattr(payment, "method", None),
                    # See the dict branch above (issue #343).
                    "sequence_type": getattr(payment, "sequence_type", None),
                    "customer_id": getattr(payment, "customer_id", None),
                    "subscription_id": getattr(payment, "subscription_id", None),
                    "mandate_id": getattr(payment, "mandate_id", None),
                }
        except Exception as e:
            self.logger.error(f"Failed to fetch payment {payment_id} from Mollie: {e}")
            raise MolliePaymentError(
                f"Cannot fetch payment data: {str(e)}",
                payment_id=payment_id,
                original_error=e,
            ) from e

    def _activate_donation_subscription(self, donation, payment_data):
        """Create the Mollie subscription that this first payment set up.

        Mollie does not create subscriptions on its own: a ``sequenceType:
        "first"`` payment only establishes the mandate, and the merchant must
        then call the subscriptions API (Mollie's recurring guide). The donation
        flow defers that call to webhook time, stamping the payment with
        ``subscription_setup``/``subscription_interval``/``subscription_amount``
        -- so this is the step that turns a recurring donor's first charge into
        an actual recurring donation.

        It has to live on THIS webhook because this is the one Mollie can reach.
        The member-dues webhook that used to own the call
        (``payment_gateways.mollie_subscription_webhook``) is not guest-
        accessible, only accepts a ``sub_`` id where Mollie posts ``id=tr_...``,
        and gates on a Customer->Member lookup plus an unpaid Sales Invoice that
        a donor -- who need not be a member at all -- can never satisfy. Issue #343.

        Returns None when this is not a recurring first payment at all, and
        otherwise one of ``success`` / ``skipped`` / ``error`` so the caller can
        tell "nothing to do" from "tried and failed".

        Mollie charges the first subscription payment one interval after the
        start date, not on it -- measured against the API, with a future
        startDate as the control -- so leaving startDate unset for monthly
        intervals does NOT double-charge the donor on signup day.
        """
        # Bound before the try so the failure log below can name a subscription
        # Mollie has already created -- without it, a local write that fails
        # after a successful create leaves a donor being charged on a
        # subscription no log and no record identifies.
        created_subscription_id = None
        try:
            if payment_data.get("sequence_type") != "first":
                return None

            metadata = payment_data.get("metadata") or {}
            if metadata.get("subscription_setup") != "true":
                return None

            # Guarded here rather than at the call site so no future caller can
            # subscribe a donor off a failed/expired/canceled payment.
            if payment_data.get("status") != "paid":
                return None

            # Cheap short-circuit for the common retry. It is NOT the real
            # duplicate guard: this read cannot close the window where Mollie
            # created the subscription but the response was lost, because nothing
            # local was written in that case. The actual protection is in
            # payment_gateways._get_or_create_subscription: it asks Mollie what
            # already carries this payment's fingerprint (metadata.payment_id)
            # and adopts it. That listing runs FIRST and unconditionally; the
            # deterministic Idempotency-Key is the backstop BEHIND it, not a fast
            # path in front of it, and it could not do the job alone because
            # Mollie evicts keys after an hour against a retry ladder that runs
            # twenty-six.
            #
            # Residual, stated because it is on exactly this path:
            # _find_subscription_for_payment returns None both when nothing
            # matched and when the listing itself raised, and the caller cannot
            # tell those apart. So if the listing is failing AND the key has
            # expired -- attempts 8-10, at T+2h/4h/26h -- the guard degrades to
            # nothing and a retry can create a second live subscription. That
            # tradeoff is deliberate (a listing outage must not block a
            # first-time donor) and is recorded at _find_subscription_for_payment.
            #
            # That remote check is also why
            # no row lock is taken here: holding a transaction open across a
            # gateway round-trip would extend the tabSeries lock this request
            # already holds, for no correctness gain.
            existing = frappe.db.get_value("Donation", donation.name, "mollie_subscription_id")
            if existing:
                # Re-publish for the steps that run after this one: without it
                # _update_donation_status sees no subscription and stamps the
                # donation back to "One-time" on every retry, undoing the first
                # delivery's work.
                payment_data["subscription_id"] = existing
                self.logger.info(
                    f"Donation {donation.name} already has Mollie subscription {existing}, "
                    "skipping activation"
                )
                return {"status": "skipped", "reason": "already_subscribed", "subscription_id": existing}

            # Reuse the existing builder rather than growing a second grammar for
            # the same Mollie call. It reads only .metadata/.id/.customer_id off
            # the payment and reaches the SDK through gateway.client, so the
            # normalised dict is adapted to that shape here.
            from verenigingen.verenigingen_payments.utils.payment_gateways import (
                _activate_direct_subscription_after_first_payment,
            )

            mollie_client = frappe.get_single("Mollie Settings").get_mollie_client()
            result = _activate_direct_subscription_after_first_payment(
                SimpleNamespace(client=mollie_client),
                SimpleNamespace(
                    metadata=metadata,
                    id=payment_data.get("id"),
                    # Same fallback as _update_donor_record: the producer writes
                    # the customer id into metadata too, so a regression in the
                    # camelCase plumbing does not silently turn every recurring
                    # donation into a "missing_customer_id" refusal.
                    customer_id=payment_data.get("customer_id") or metadata.get("customer_id"),
                ),
            )

            if result and result.get("status") == "success":
                subscription_id = created_subscription_id = result["subscription_id"]

                # The builder links the subscription onto the Donation via the
                # metadata's donation_id. Link it here too, from the donation we
                # already resolved: without this a payment whose metadata lacks
                # donation_id would create a subscription that is never recorded,
                # and the idempotency guard above -- which reads exactly this
                # field -- would let a webhook retry create a second one.
                # The builder's own write is wrapped in a bare `except: pass`, so
                # this is the only reliable link. Commit it immediately: the id is
                # otherwise only persisted by a later, unrelated step, and if that
                # step fails Mollie is charging a donor on a subscription no record
                # names (CLAUDE.md transaction pattern 1).
                frappe.db.set_value("Donation", donation.name, "mollie_subscription_id", subscription_id)
                frappe.db.commit()

                # The steps after this read the subscription off payment_data
                # (donation Recurring/One-time stamp, Donor.mollie_subscription_id,
                # donor history entry type). Mollie only sets subscriptionId on
                # payments a subscription generated, which a first payment by
                # definition is not, so it is set here instead -- this donation
                # is recurring from now on.
                payment_data["subscription_id"] = subscription_id
                self.logger.info(
                    f"Created Mollie subscription {subscription_id} for donation {donation.name}"
                )
                return result

            # The builder's own "skipped" is not a failure -- it means the payment
            # never asked for a subscription. Switch on its status explicitly
            # rather than treating everything that is not "success" as an error,
            # which would turn a skip into a permanent 500 retry loop.
            if (result or {}).get("status") == "skipped":
                return {"status": "skipped", "reason": (result or {}).get("reason")}

            # create_error_response only builds a dict -- nothing raises and
            # nothing stores this result, so without logging here a failed
            # activation would be completely silent.
            frappe.log_error(
                f"Subscription activation did not succeed for donation {donation.name} "
                f"(payment {payment_data.get('id')}): {result}",
                "Mollie Donation Subscription Activation",
            )
            # Only refusals we can NAME are permanent; anything else is retried.
            #
            # The builder collapses every internal failure -- including a dropped
            # connection -- into a generic error dict, so the exception type is
            # not visible here and unclassifiable failures have to be guessed.
            # Guessing "retry" is the right guess now that the create adopts any
            # subscription already carrying this payment's fingerprint, with the
            # deterministic Idempotency-Key as a backstop behind that adopt: a
            # re-delivery re-attempts rather than duplicating. At its real
            # strength, which is not unconditional -- if Mollie's own subscription
            # listing is failing too, the adopt returns the same None it returns
            # for "nothing matched", falls through to the key, and past the key's
            # one hour has nothing left. See the fuller note above.
            # Retrying is still the one case that recovers the worst failure
            # mode there is -- Mollie created the subscription but the response
            # was lost, so nothing local recorded it. Without a retry that donor
            # holds a subscription this system cannot see. The cost of guessing
            # wrong is a bounded number of re-deliveries that refuse identically.
            #
            # The two *_bad_request / *_key_conflict names come from
            # payment_gateways._permanent_refusal_reason: Mollie answered 400, so
            # the request as sent is unacceptable and every redelivery sends the
            # identical request. Retrying one runs the full 10-attempt / 26-hour
            # ladder against a refusal that cannot change.
            reason = (result or {}).get("reason")
            return {
                "status": "error",
                "permanent": reason
                in (
                    "invalid_interval",
                    "missing_subscription_details",
                    "missing_customer_id",
                    "idempotency_key_conflict",
                    "mollie_bad_request",
                ),
                "reason": reason,
                "message": (result or {}).get("message") or f"activation failed: {result}",
            }

        except Exception as e:
            # A failed subscription must not roll back a payment the donor has
            # already made -- the money is banked either way. Retryable for the
            # same reason as above, and with the same limit: what makes a
            # re-delivery safe is the adopt-by-fingerprint in
            # _get_or_create_subscription, backed by the Idempotency-Key -- not
            # the key on its own, which Mollie evicts after an hour. That is also
            # what recovers a create that succeeded at Mollie while the response
            # was lost. Either way the donation stays queryable as an
            # unfulfilled recurring intent -- see _update_donation_status.
            frappe.log_error(
                f"Error activating donation subscription for {donation.name} "
                f"(payment {payment_data.get('id')}, "
                f"subscription created at Mollie: {created_subscription_id}): {e}\n"
                f"{frappe.get_traceback()}",
                "Mollie Donation Subscription Activation",
            )
            return {
                "status": "error",
                "permanent": False,
                "subscription_id": created_subscription_id,
                "message": str(e),
            }

    def _update_donation_status(self, donation, payment_data):
        """Update donation status based on payment data."""
        try:
            # Reload first: _create_donation_financial_entries -> the Journal
            # Entry creator writes Donation.journal_entry via frappe.db.set_value
            # (DB only, the in-memory object is untouched). Without this reload
            # the donation.save() below writes back the stale in-memory
            # journal_entry (None), clobbering the just-created JE link.
            donation.reload()

            # Mark donation as paid
            donation.paid = 1
            if hasattr(donation, "payment_status"):
                donation.payment_status = "Completed"

            # Determine if this is recurring (simple check for now)
            metadata = payment_data.get("metadata") or {}
            subscription_id = payment_data.get("subscription_id") or metadata.get("subscription_id")
            # A donor who asked for a recurring donation stays recorded as one even
            # if creating the subscription failed. Otherwise the failure is
            # invisible: "Recurring with no subscription id" is the only query that
            # can find donors owed a subscription, and stamping them One-time makes
            # that query return nothing -- which is exactly the invisibility of #343.
            intended_recurring = metadata.get("subscription_setup") == "true"
            if subscription_id or intended_recurring:
                donation.status = "Recurring"
                self.logger.info(f"✅ Set donation {donation.name} status to Recurring")
            else:
                donation.status = "One-time"
                self.logger.info(f"✅ Set donation {donation.name} status to One-time")

            # Save donation
            donation.save()
            self.logger.info(f"✅ Updated donation {donation.name} status")

        except Exception as e:
            self.logger.error("Error updating donation status", error=e)

    def _update_donation_payment_history(self, donation, payment_data, payment_entry_name):
        """Update donation payment history with payment details."""
        try:
            # Check if payment history already exists for this payment
            payment_id = payment_data.get("id")
            existing_entry = None
            for payment_hist in donation.payments or []:
                if getattr(payment_hist, "mollie_payment_id", None) == payment_id:
                    existing_entry = payment_hist
                    break

            if existing_entry:
                self.logger.info(f"Payment history already exists for {payment_id}")
                return True

            # Add new payment history entry using centralized extractor
            extractor = get_payment_data_extractor()
            payment_amount = extractor.extract_amount(
                payment_data, allow_zero=True
            )  # payment_data is dict format
            paid_date = payment_data.get("paid_at") or payment_data.get("created_at")

            # Parse ISO datetime to date
            if isinstance(paid_date, str):
                try:
                    from dateutil import parser

                    paid_date = parser.parse(paid_date).date()
                except (ValueError, TypeError, ImportError):
                    paid_date = frappe.utils.getdate()
            elif not paid_date:
                paid_date = frappe.utils.getdate()

            donation.append(
                "payments",
                {
                    "mollie_payment_id": payment_id,
                    "payment_entry": payment_entry_name,
                    "amount": payment_amount,
                    "payment_date": paid_date,
                    "payment_method": "Mollie",  # Use standard Mode of Payment, not Mollie's method
                    "payment_status": "Paid",
                },
            )

            # Save donation with updated payment history
            donation.save()
            self.logger.info(f"✅ Added payment history for donation {donation.name}")
            return True

        except Exception as e:
            self.logger.error("Error updating payment history", error=e)
            return False

    # =========================================================================
    # NEW ARCHITECTURE: Bank Transaction → Journal Entry → Record Updates
    # =========================================================================

    def _create_donation_financial_entries(self, donation, payment_data):
        """
        Create financial entries for donation using correct architecture.

        Flow:
            1. Bank Transaction (represents bank statement line)
            2. Journal Entry (Debit: Mollie Clearing, Credit: Donation Income)

        This replaces the incorrect Payment Entry approach.

        Args:
            donation: Donation document
            payment_data: Mollie payment data dict

        Returns:
            dict with bank_transaction_name and journal_entry_name, or None on failure
        """
        payment_id = payment_data.get("id")
        self.logger.info(f"📋 Creating financial entries for donation {donation.name} (payment {payment_id})")

        try:
            # Step 1: Create Bank Transaction
            self.logger.info("  Step 1: Getting bank transaction creator...")
            bt_creator = get_bank_transaction_creator()

            # Get Mollie bank account configuration
            self.logger.info("  Step 1a: Getting Mollie bank account config...")
            config = bt_creator.get_mollie_bank_account_config()
            if config.get("error"):
                self.logger.error(f"❌ Mollie config error: {config['error']}")
                # Log to Mollie Audit Log for visibility
                self._log_webhook_event(
                    payment_id,
                    "financial_entry_error",
                    f"Mollie bank account config error: {config['error']}",
                    {"donation": donation.name, "config_error": config.get("error")},
                )
                return None

            self.logger.info(
                f"  Step 1b: Config OK - bank_account={config.get('bank_account')}, company={config.get('company')}"
            )

            # Fetch full payment object from Mollie for Bank Transaction creation
            self.logger.info("  Step 1c: Fetching payment object from Mollie API...")
            try:
                mollie_settings = frappe.get_single("Mollie Settings")
                from mollie.api.client import Client as MollieClient

                mollie_client = MollieClient()
                # Use get_api_key() which handles test_mode correctly
                api_key = mollie_settings.get_api_key()
                if not api_key:
                    raise ValueError("Mollie API key not configured in Mollie Settings")
                mollie_client.set_api_key(api_key)
                payment_obj = mollie_client.payments.get(payment_id)
                self.logger.info(
                    f"  Step 1c: Got payment object, status={getattr(payment_obj, 'status', 'unknown')}"
                )
            except Exception as mollie_err:
                self.logger.error("❌ Failed to fetch payment from Mollie API", error=mollie_err)
                self._log_webhook_event(
                    payment_id,
                    "financial_entry_error",
                    f"Mollie API error: {type(mollie_err).__name__}: {str(mollie_err)}",
                    {"donation": donation.name},
                )
                return None

            # Create Bank Transaction
            self.logger.info("  Step 1d: Creating Bank Transaction...")
            try:
                # Get party info for Bank Transaction (Customer linked to Donor)
                party_type = None
                party = None
                bank_party_name = None
                if donation.donor:
                    # Get donor name for bank_party_name
                    donor_doc = frappe.db.get_value(
                        "Donor", donation.donor, ["donor_name", "customer"], as_dict=True
                    )
                    if donor_doc:
                        bank_party_name = donor_doc.get("donor_name")
                        if donor_doc.get("customer"):
                            party_type = "Customer"
                            party = donor_doc.get("customer")

                bank_transaction_name = bt_creator.create_from_mollie_payment(
                    payment=payment_obj,
                    bank_account=config["bank_account"],
                    company=config["company"],
                    additional_description=f"Donation: {donation.name}",
                    party_type=party_type,
                    party=party,
                    bank_party_name=bank_party_name,
                )
            except Exception as bt_err:
                self.logger.error("❌ Exception creating Bank Transaction", error=bt_err)
                self._log_webhook_event(
                    payment_id,
                    "financial_entry_error",
                    f"Bank Transaction creation exception: {type(bt_err).__name__}: {str(bt_err)}",
                    {"donation": donation.name},
                )
                return None

            if not bank_transaction_name:
                self.logger.error(
                    f"❌ Failed to create Bank Transaction for payment {payment_id} (returned None)"
                )
                self._log_webhook_event(
                    payment_id,
                    "financial_entry_error",
                    "Bank Transaction creation returned None (check Error Log for details)",
                    {"donation": donation.name},
                )
                return None

            self.logger.info(f"✅ Created Bank Transaction: {bank_transaction_name}")

            # Step 2: Create Journal Entry
            self.logger.info("  Step 2: Creating Journal Entry...")
            try:
                je_creator = get_donation_journal_entry_creator()
                journal_entry_name = je_creator.create_from_mollie_payment(
                    payment_data=payment_data,
                    donation_doc=donation,
                    bank_transaction_name=bank_transaction_name,
                )
            except Exception as je_err:
                self.logger.error("❌ Exception creating Journal Entry", error=je_err)
                self._log_webhook_event(
                    payment_id,
                    "financial_entry_error",
                    f"Journal Entry creation exception: {type(je_err).__name__}: {str(je_err)}",
                    {"donation": donation.name, "bank_transaction": bank_transaction_name},
                )
                return {
                    "bank_transaction_name": bank_transaction_name,
                    "journal_entry_name": None,
                    "partial_success": True,
                }

            if not journal_entry_name:
                self.logger.error(
                    f"❌ Failed to create Journal Entry for donation {donation.name} (returned None)"
                )
                self._log_webhook_event(
                    payment_id,
                    "financial_entry_error",
                    "Journal Entry creation returned None (check Error Log for details)",
                    {"donation": donation.name, "bank_transaction": bank_transaction_name},
                )
                # Bank Transaction was created, but Journal Entry failed
                # Return partial success so we can retry Journal Entry later
                return {
                    "bank_transaction_name": bank_transaction_name,
                    "journal_entry_name": None,
                    "partial_success": True,
                }

            self.logger.info(f"✅ Created Journal Entry: {journal_entry_name}")
            self._log_webhook_event(
                payment_id,
                "financial_entries_created",
                f"Created Bank Transaction {bank_transaction_name} and Journal Entry {journal_entry_name}",
                {
                    "donation": donation.name,
                    "bank_transaction": bank_transaction_name,
                    "journal_entry": journal_entry_name,
                },
            )

            return {
                "bank_transaction_name": bank_transaction_name,
                "journal_entry_name": journal_entry_name,
                "partial_success": False,
            }

        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            self.logger.error(
                f"Error creating financial entries for donation {donation.name}",
                error=e,
            )
            self._log_webhook_event(
                payment_id,
                "financial_entry_error",
                f"Unexpected exception: {type(e).__name__}: {str(e)}",
                {"donation": donation.name, "traceback": tb[:2000]},
            )
            frappe.log_error(
                f"Financial entry creation failed for donation {donation.name}\n\n{tb}",
                "Donation Financial Entry Error",
            )
            return None

    def _update_donor_record(self, donation, payment_data):
        """
        Update Donor record with payment information and subscription details.

        Updates:
            - mollie_customer_id, mollie_subscription_id (if subscription payment)
            - donor_history child table (via MemberFinancialHistoryManager for atomic update)

        Args:
            donation: Donation document
            payment_data: Mollie payment data dict

        Returns:
            bool: Success status
        """
        if not donation.donor:
            self.logger.info(f"No donor linked to donation {donation.name}, skipping donor update")
            return True

        try:
            donor = frappe.get_doc("Donor", donation.donor)
            _payment_id = payment_data.get("id")  # noqa: F841
            metadata = payment_data.get("metadata", {}) or {}

            # Check for subscription details
            subscription_id = payment_data.get("subscription_id") or metadata.get("subscription_id")
            customer_id = payment_data.get("customer_id") or metadata.get("customer_id")

            fields_updated = []

            # Update Mollie IDs if present (requires full save)
            mollie_fields_changed = False
            if customer_id and donor.mollie_customer_id != customer_id:
                donor.mollie_customer_id = customer_id
                fields_updated.append("mollie_customer_id")
                mollie_fields_changed = True

            if subscription_id and donor.mollie_subscription_id != subscription_id:
                donor.mollie_subscription_id = subscription_id
                fields_updated.append("mollie_subscription_id")
                mollie_fields_changed = True

            # Save Mollie ID changes if any
            if mollie_fields_changed:
                donor.save()
                self.logger.info(f"✅ Updated Donor {donor.name} Mollie IDs: {', '.join(fields_updated)}")

            # Add to donor_history using MemberFinancialHistoryManager for atomic updates
            if hasattr(donor, "donor_history"):
                from verenigingen.utils.member_financial_history_manager import MemberFinancialHistoryManager

                # Self-healing: Fix any existing broken entries missing mandatory donation_date
                # This handles legacy entries created with wrong field names
                broken_entries_fixed = 0
                for entry in donor.donor_history or []:
                    if not entry.donation_date:
                        # Try to get date from linked donation, fall back to today
                        if entry.donation_reference:
                            linked_date = frappe.db.get_value(
                                "Donation", entry.donation_reference, "donation_date"
                            )
                            entry.donation_date = linked_date or frappe.utils.nowdate()
                        else:
                            entry.donation_date = frappe.utils.nowdate()
                        broken_entries_fixed += 1

                if broken_entries_fixed > 0:
                    self.logger.info(
                        f"🔧 Fixed {broken_entries_fixed} broken donor_history entries for {donor.name}"
                    )
                    # Save the fixes before proceeding
                    donor.flags.ignore_validate_update_after_submit = True
                    donor.save()

                # Use centralized history manager for atomic child table updates
                history_manager = MemberFinancialHistoryManager(
                    doc=donor,
                    history_field_name="donor_history",
                    max_entries=30,
                )

                # Extract payment details using centralized extractor
                extractor = get_payment_data_extractor()

                def build_donor_history_entry():
                    amount = extractor.extract_amount(payment_data, allow_zero=True)
                    paid_date = extractor.extract_payment_date(payment_data)
                    # Field names must match Donation History child table schema
                    return {
                        "donation_reference": donation.name,
                        "donation_date": paid_date or donation.donation_date or frappe.utils.nowdate(),
                        "donation_amount": amount,
                        "donation_status": (
                            "One-time" if not payment_data.get("subscription_id") else "Recurring"
                        ),
                        "payment_method": "Mollie",
                        "paid": 1,
                    }

                success = history_manager.add_or_update_entry(
                    entry_id=donation.name,
                    entry_builder=build_donor_history_entry,
                    id_field_name="donation_reference",
                )

                if success:
                    fields_updated.append("donor_history")
                    self.logger.info(f"✅ Updated Donor {donor.name} history for donation {donation.name}")
                else:
                    # `.error`, not `.warning`: a bare frappe logger defaults to level
                    # ERROR under `bench run-tests`, so a warning here is discarded
                    # entirely and the failure would be invisible to the suite too.
                    self.logger.error(
                        f"donor_history update returned False for Donor {donor.name}, "
                        f"donation {donation.name}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error("Error updating Donor record", error=e)
            return False

    def _update_member_payment_history(self, donation, payment_data, journal_entry_name):
        """
        Update Member payment history for ALL donations (not just subscriptions).

        Uses MemberFinancialHistoryManager for atomic child table updates
        without full document save.

        Args:
            donation: Donation document
            payment_data: Mollie payment data dict
            journal_entry_name: Journal Entry name to link

        Returns:
            bool: Success status
        """
        # Find linked member - either directly or through donor
        member_name = None

        # Check for direct member link on donation
        if hasattr(donation, "member") and donation.member:
            member_name = donation.member

        # Check for member via donor
        if not member_name and donation.donor:
            member_name = frappe.db.get_value("Donor", donation.donor, "member")

        if not member_name:
            self.logger.info(f"No member linked to donation {donation.name}, skipping member update")
            return True

        try:
            member = frappe.get_doc("Member", member_name)
            payment_id = payment_data.get("id")

            # Use MemberFinancialHistoryManager for atomic updates
            from verenigingen.utils.member_financial_history_manager import get_payment_history_manager

            history_manager = get_payment_history_manager(member)

            # Extract payment details using centralized extractor
            extractor = get_payment_data_extractor()

            def build_entry():
                return {
                    "mollie_payment_id": payment_id,
                    "invoice": donation.name,  # Use donation as reference
                    "journal_entry": journal_entry_name,
                    "amount": extractor.extract_amount(payment_data, allow_zero=True),
                    "payment_date": extractor.extract_payment_date(payment_data),
                    "payment_method": "Mollie",
                    "status": "Completed",
                    "payment_type": "Donation",
                }

            success = history_manager.add_or_update_entry(
                entry_id=donation.name,
                entry_builder=build_entry,
                id_field_name="invoice",
            )

            if success:
                self.logger.info(
                    f"✅ Updated Member {member_name} payment history for donation {donation.name}"
                )
            else:
                # `.error`, not `.warning`, for the same reason as the donor path
                # above: a bare frappe logger defaults to level ERROR under
                # `bench run-tests`, so a warning here is discarded entirely.
                self.logger.error(f"member payment history update returned False for {donation.name}")

            return success

        except Exception as e:
            self.logger.error("Error updating Member payment history", error=e)
            return False

    def _update_donation_payment_history_atomic(self, donation, payment_data, journal_entry_name):
        """
        Update donation payment history using atomic child table update.

        This version uses update_child_table() to avoid full document validation.

        Args:
            donation: Donation document
            payment_data: Mollie payment data dict
            journal_entry_name: Journal Entry name to link

        Returns:
            bool: Success status
        """
        try:
            payment_id = payment_data.get("id")

            # Check if payment history already exists for this payment
            existing_entry = None
            for payment_hist in donation.payments or []:
                if getattr(payment_hist, "mollie_payment_id", None) == payment_id:
                    existing_entry = payment_hist
                    break

            if existing_entry:
                self.logger.info(f"Payment history already exists for {payment_id}")
                return True

            # Extract payment details using centralized extractor
            extractor = get_payment_data_extractor()

            # Append payment history entry
            donation.append(
                "payments",
                {
                    "mollie_payment_id": payment_id,
                    "journal_entry": journal_entry_name,
                    "amount": extractor.extract_amount(payment_data, allow_zero=True),
                    "payment_date": extractor.extract_payment_date(payment_data),
                    "payment_method": "Mollie",
                    "payment_status": "Paid",
                },
            )

            # Use atomic child table update
            donation.flags.ignore_version = True
            donation.update_child_table("payments")
            frappe.db.commit()

            self.logger.info(f"✅ Added payment history for donation {donation.name} (atomic)")
            return True

        except Exception as e:
            self.logger.error("Error updating donation payment history (atomic)", error=e)
            return False

    def _log_webhook_event(
        self,
        payment_id: str,
        event_type: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        severity: str = "info",
    ):
        """
        Log webhook processing event to Mollie Audit Log for visibility.

        Args:
            payment_id: Mollie payment ID
            event_type: Type of event (e.g., 'financial_entry_error', 'financial_entries_created')
            description: Human-readable description
            details: Additional details dict
            severity: Log severity ('info', 'warning', 'error', 'critical')
        """
        try:
            from ..utils.audit import MollieAuditLogger

            audit_logger = MollieAuditLogger()
            audit_logger._create_audit_log(
                event_type=event_type,
                event_category="webhook_processing",
                description=f"[{payment_id}] {description}",
                data={
                    "payment_id": payment_id,
                    **(details or {}),
                },
                severity=severity if event_type.endswith("_error") else "info",
            )
        except Exception as e:
            # Don't let audit logging failure break webhook processing
            self.logger.warning(f"Failed to create audit log entry: {e}")


# Utility functions needed for unified processing
def find_donation_for_payment_by_id(payment_id: str) -> Any:
    """
    Find donation record by payment_id (unified implementation).

    This replaces the old function from payment_webhook.py to maintain
    unified architecture without external dependencies.
    """
    donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
    if donation_name:
        return frappe.get_doc("Donation", donation_name)
    return None


# Global instance for backwards compatibility
_unified_webhook_service = None


def get_unified_webhook_service() -> UnifiedWebhookWrapperService:
    """Get the global unified webhook service instance."""
    global _unified_webhook_service
    if _unified_webhook_service is None:
        _unified_webhook_service = UnifiedWebhookWrapperService()
    return _unified_webhook_service
