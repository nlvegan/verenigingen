"""
Mollie Refund Processing Utility

Extracted from the complex webhook handler to be reusable by any webhook endpoint.
Handles both partial and full refunds with proper incremental processing.
"""

import frappe
from frappe.utils import flt, today


def process_payment_refund(payment_id, refund_amount_total, debug_context="webhook"):
    """
    Process refund detected in payment webhook

    Args:
        payment_id: Mollie payment ID (tr_xxxxx)
        refund_amount_total: Cumulative total refund amount from Mollie
        debug_context: Context string for logging

    Returns:
        dict: Processing result with status and details
    """
    try:
        frappe.logger().info(
            f"🔄 [{debug_context}] Processing refund for payment {payment_id}, total: €{refund_amount_total}"
        )

        # Find the original donation by payment ID
        donations = frappe.get_all(
            "Donation",
            filters={"payment_id": payment_id},
            fields=["name", "amount", "payment_status", "donor", "donation_date"],
        )

        if not donations:
            frappe.logger().warning(
                f"❌ [{debug_context}] Original donation not found for payment {payment_id}"
            )
            return {"status": "ignored", "message": f"Original donation not found for payment {payment_id}"}

        donation = frappe.get_doc("Donation", donations[0]["name"])
        frappe.logger().info(
            f"✅ [{debug_context}] Found original donation: {donation.name} (€{donation.amount})"
        )

        # Calculate previously recorded refund total from payment history
        existing_refund_total = 0.0
        payment_history_entries = frappe.get_all(
            "Payment History",
            filters={"parent": donation.name, "parenttype": "Donation"},
            fields=["amount", "mollie_payment_id"],
        )
        for history_entry in payment_history_entries:
            if (
                history_entry.get("mollie_payment_id")
                and payment_id in str(history_entry.get("mollie_payment_id", ""))
                and flt(history_entry.get("amount", 0)) < 0
            ):  # Negative amounts are refunds
                existing_refund_total += abs(flt(history_entry.get("amount", 0)))

        # Calculate incremental refund (what's new)
        incremental_refund = flt(refund_amount_total) - existing_refund_total

        frappe.logger().info(
            f"📊 [{debug_context}] Refund calculation: Mollie total: €{refund_amount_total}, Previously recorded: €{existing_refund_total}, Incremental: €{incremental_refund}"
        )

        # If no new refund amount, skip processing
        if incremental_refund <= 0.01:  # Use small threshold for float comparison
            frappe.logger().info(f"⏭️ [{debug_context}] No new refund amount to process")
            return {
                "status": "ignored",
                "message": f"No new refund detected. Total: €{refund_amount_total}, Previously recorded: €{existing_refund_total}",
            }

        # Create refund payment history entry for INCREMENTAL amount only
        refund_payment_history = {
            "payment_date": today(),
            "amount": -incremental_refund,  # Negative amount for refund (incremental only)
            "mollie_payment_id": payment_id,  # Keep original payment ID for reference
            "payment_status": "Completed",
            "payment_method": "Mollie Refund",
            "transaction_reference": f"{payment_id}_refund",
            "notes": f"Partial refund of €{incremental_refund:.2f} (total refunded now: €{refund_amount_total:.2f}) for payment {payment_id}",
        }

        # Add refund entry to payment history
        donation.append("payment_history", refund_payment_history)
        donation.save()

        is_full_refund = abs(flt(refund_amount_total) - flt(donation.amount)) < 0.01

        # Handle Payment Entry accounting for refunds using unified logic
        payment_entry_result = _handle_refund_payment_entries_unified(
            donation, payment_id, incremental_refund, is_full_refund, debug_context
        )

        frappe.logger().info(
            f"✅ [{debug_context}] Refund processed: €{incremental_refund} added to {donation.name} (Full refund: {is_full_refund})"
        )
        frappe.logger().info(
            f"💳 [{debug_context}] Payment Entry handling: {payment_entry_result.get('message', 'Unknown status')}"
        )

        return {
            "status": "success",
            "message": f"Refund processed: €{incremental_refund}",
            "donation_id": donation.name,
            "refund_amount": incremental_refund,
            "total_refunded": refund_amount_total,
            "is_full_refund": is_full_refund,
        }

    except Exception as e:
        error_msg = f"Refund processing failed for {payment_id}: {str(e)}"
        frappe.log_error(error_msg, f"Refund Processing Error [{debug_context}]")
        frappe.logger().error(f"❌ [{debug_context}] {error_msg}")
        return {"status": "error", "message": error_msg}


def detect_refund_in_payment(payment_data):
    """
    Detect if a payment contains refund information

    Args:
        payment_data: Mollie payment object or dict

    Returns:
        tuple: (has_refund: bool, refund_amount: float)
    """
    try:
        # Handle different payment data formats
        if hasattr(payment_data, "_data"):
            # Mollie API payment object
            amount_refunded = payment_data._data.get("amountRefunded", {})
        elif isinstance(payment_data, dict):
            # Dict format
            amount_refunded = payment_data.get("amountRefunded", {})
        else:
            # Try direct attribute access
            amount_refunded = getattr(payment_data, "amountRefunded", {})

        if not amount_refunded or not isinstance(amount_refunded, dict):
            return False, 0.0

        refund_value = amount_refunded.get("value", "0.00")
        refund_amount = flt(refund_value)

        has_refund = refund_amount > 0.01

        frappe.logger().info(
            f"🔍 Refund detection: amount_refunded={amount_refunded}, parsed_amount={refund_amount}, has_refund={has_refund}"
        )

        return has_refund, refund_amount

    except Exception as e:
        frappe.logger().error(f"❌ Error detecting refund: {str(e)}")
        return False, 0.0


def detect_chargeback_in_payment(payment_data):
    """
    Detect if a payment contains chargeback information

    Args:
        payment_data: Mollie payment object or dict

    Returns:
        tuple: (has_chargeback: bool, chargeback_amount: float)
    """
    try:
        # Handle different payment data formats
        if hasattr(payment_data, "_data"):
            # Mollie API payment object
            amount_chargedback = payment_data._data.get("amountChargedBack", {})
        elif isinstance(payment_data, dict):
            # Dict format
            amount_chargedback = payment_data.get("amountChargedBack", {})
        else:
            # Try direct attribute access
            amount_chargedback = getattr(payment_data, "amountChargedBack", {})

        if not amount_chargedback or not isinstance(amount_chargedback, dict):
            return False, 0.0

        chargeback_value = amount_chargedback.get("value", "0.00")
        chargeback_amount = flt(chargeback_value)

        has_chargeback = chargeback_amount > 0.01

        frappe.logger().info(
            f"🔍 Chargeback detection: amount_chargedback={amount_chargedback}, parsed_amount={chargeback_amount}, has_chargeback={has_chargeback}"
        )

        return has_chargeback, chargeback_amount

    except Exception as e:
        frappe.logger().error(f"❌ Error detecting chargeback: {str(e)}")
        return False, 0.0


def process_payment_chargeback(payment_id, chargeback_amount_total, debug_context="webhook"):
    """
    Process chargeback for a payment with incremental detection to avoid duplicates

    Args:
        payment_id: Mollie payment ID
        chargeback_amount_total: Total chargeback amount from Mollie
        debug_context: Context string for logging

    Returns:
        dict: Processing result with status and details
    """
    try:
        from frappe.utils import flt, today

        # Find donation by payment ID
        donations = frappe.get_all("Donation", filters={"payment_id": payment_id}, fields=["name"])

        if not donations:
            frappe.logger().info(
                f"⚠️ [{debug_context}] No donation found for chargeback payment {payment_id}"
            )
            return {
                "status": "warning",
                "message": f"No donation found for payment {payment_id} - chargeback noted but no donation to update",
            }

        donation = frappe.get_doc("Donation", donations[0].name)

        # Check existing chargeback history to calculate incremental amount
        existing_chargeback_total = 0.0
        chargeback_history_entries = frappe.get_all(
            "Payment History",
            filters={"parent": donation.name, "parenttype": "Donation"},
            fields=["amount", "mollie_payment_id", "payment_method"],
        )
        for history_entry in chargeback_history_entries:
            if (
                history_entry.get("mollie_payment_id") == payment_id
                and "chargeback" in str(history_entry.get("payment_method", "")).lower()
                and flt(history_entry.get("amount", 0)) < 0
            ):  # Negative amounts are chargebacks
                existing_chargeback_total += abs(flt(history_entry.get("amount", 0)))

        # Calculate incremental chargeback (what's new)
        incremental_chargeback = flt(chargeback_amount_total) - existing_chargeback_total

        frappe.logger().info(
            f"📊 [{debug_context}] Chargeback calculation: Mollie total: €{chargeback_amount_total}, Previously recorded: €{existing_chargeback_total}, Incremental: €{incremental_chargeback}"
        )

        # If no new chargeback amount, skip processing
        if incremental_chargeback <= 0.01:  # Use small threshold for float comparison
            frappe.logger().info(f"⏭️ [{debug_context}] No new chargeback amount to process")
            return {
                "status": "ignored",
                "message": f"No new chargeback detected. Total: €{chargeback_amount_total}, Previously recorded: €{existing_chargeback_total}",
            }

        # Create chargeback payment history entry for INCREMENTAL amount only
        chargeback_payment_history = {
            "payment_date": today(),
            "amount": -incremental_chargeback,  # Negative amount for chargeback (incremental only)
            "mollie_payment_id": payment_id,  # Keep original payment ID for reference
            "payment_status": "Completed",
            "payment_method": "Mollie Chargeback",
            "transaction_reference": f"{payment_id}_chargeback",
            "notes": f"Chargeback of €{incremental_chargeback:.2f} (total charged back now: €{chargeback_amount_total:.2f}) for payment {payment_id}. Disputed by customer.",
        }

        # Add chargeback entry to payment history
        donation.append("payment_history", chargeback_payment_history)
        donation.save()

        frappe.logger().info(
            f"✅ [{debug_context}] Chargeback processed successfully: €{incremental_chargeback} for donation {donation.name}"
        )

        # Determine if this is a full chargeback
        original_amount = flt(donation.amount)
        is_full_chargeback = flt(chargeback_amount_total) >= original_amount - 0.01

        return {
            "status": "success",
            "message": f"Chargeback of €{incremental_chargeback:.2f} processed for donation {donation.name}",
            "donation_id": donation.name,
            "incremental_chargeback": incremental_chargeback,
            "total_chargedback": chargeback_amount_total,
            "is_full_chargeback": is_full_chargeback,
        }

    except Exception as e:
        error_msg = f"Chargeback processing failed for {payment_id}: {str(e)}"
        frappe.log_error(error_msg, f"Chargeback Processing Error [{debug_context}]")
        frappe.logger().error(f"❌ [{debug_context}] {error_msg}")
        return {"status": "error", "message": error_msg}


def _handle_refund_payment_entries_unified(
    donation,
    payment_id,
    incremental_refund_amount,
    is_full_refund,
    debug_context,
    refund_date=None,
    refund_id=None,
):
    """
    Handle refund Payment Entry creation using unified logic.

    This replaces the complex separate logic with the unified Payment Entry creator
    that ensures proper idempotency and consistency with regular payment processing.
    """
    try:
        # Import the unified Payment Entry creator
        from verenigingen.verenigingen_payments.mollie.utils.unified_payment_entry_creator import (
            create_refund_payment_entry,
        )

        frappe.logger().info(
            f"🔄 [{debug_context}] Creating refund Payment Entry for €{incremental_refund_amount}"
        )

        # Use provided refund_id or fall back to amount-based ID
        actual_refund_id = refund_id or f"incr_{int(incremental_refund_amount * 100)}"

        frappe.logger().info(f"📝 [{debug_context}] Using refund ID: {actual_refund_id}")

        # Create refund Payment Entry using unified logic
        refund_pe = create_refund_payment_entry(
            donation_doc=donation,
            mollie_payment_id=payment_id,
            refund_id=actual_refund_id,
            refund_amount=incremental_refund_amount,
            refund_date=refund_date,
        )

        if refund_pe:
            frappe.logger().info(f"✅ [{debug_context}] Created refund Payment Entry: {refund_pe.name}")
            return {
                "status": "success",
                "message": f"Refund Payment Entry created: {refund_pe.name}",
                "payment_entry_name": refund_pe.name,
                "refund_amount": incremental_refund_amount,
                "is_full_refund": is_full_refund,
            }
        else:
            frappe.logger().warning(f"⚠️ [{debug_context}] Failed to create refund Payment Entry")
            return {
                "status": "warning",
                "message": "Failed to create refund Payment Entry",
            }

    except Exception as e:
        error_msg = f"Unified refund Payment Entry creation failed: {str(e)}"
        frappe.log_error(error_msg, f"Unified Refund PE Error [{debug_context}]")
        frappe.logger().error(f"❌ [{debug_context}] {error_msg}")
        return {"status": "error", "message": error_msg}


# ARCHIVED: _handle_refund_payment_entries_old function moved to:
# archived/refund_chargeback_service/_handle_refund_payment_entries_old.py
# Reason: Replaced by unified payment processing architecture
