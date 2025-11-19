"""
SEPA Duplicate Prevention and Safeguards
Implements robust mechanisms to prevent double debiting and duplicate processing
"""

import hashlib
import time
from typing import Dict, List

import frappe
from frappe import _
from frappe.utils import flt, getdate

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.audit_logging import log_sensitive_operation

# =============================================================================
# DUPLICATE PAYMENT PREVENTION
# =============================================================================


@critical_api(operation_type=OperationType.FINANCIAL)
def create_payment_entry_with_duplicate_check(invoice_name: str, amount: float, payment_data: Dict) -> Dict:
    """
    Create payment entry with comprehensive duplicate checking

    Args:
        invoice_name: Sales Invoice name
        amount: Payment amount
        payment_data: Payment entry data

    Returns:
        Payment entry creation result

    Raises:
        ValidationError: If duplicate payment detected
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_processing",
        "create_payment_entry_with_duplicate_check",
        {"invoice_name": invoice_name, "amount": amount},
    )

    # Check for existing payments
    existing_payments = frappe.get_all(
        "Payment Entry Reference",
        filters={
            "reference_name": invoice_name,
            "reference_doctype": "Sales Invoice",
            "parenttype": "Payment Entry",
        },
        fields=["parent", "allocated_amount"],
    )

    # Calculate total already allocated
    total_allocated = sum(flt(payment.allocated_amount) for payment in existing_payments)

    # Get invoice total to check against
    invoice_total = frappe.db.get_value("Sales Invoice", invoice_name, "grand_total")

    if not invoice_total:
        raise frappe.ValidationError(_("Invoice {0} not found or has no total amount").format(invoice_name))

    if total_allocated >= flt(invoice_total):
        raise frappe.ValidationError(
            _("Invoice {0} already fully paid. Total allocated: {1}, Invoice total: {2}").format(
                invoice_name, total_allocated, invoice_total
            )
        )

    if total_allocated + amount > flt(invoice_total):
        raise frappe.ValidationError(
            _(
                "Payment amount {0} would exceed invoice total. Already allocated: {1}, Invoice total: {2}"
            ).format(amount, total_allocated, invoice_total)
        )

    # Generate idempotency key
    idempotency_key = generate_idempotency_key(
        payment_data.get("custom_bank_transaction", ""),
        payment_data.get("custom_sepa_batch", ""),
        f"payment_{invoice_name}",
    )

    # Check if operation already executed
    return execute_idempotent_operation(idempotency_key, lambda: _create_payment_entry(payment_data))


def _create_payment_entry(payment_data: Dict) -> Dict:
    """Internal function to create payment entry"""
    payment_entry = frappe.get_doc(payment_data)
    payment_entry.insert()
    payment_entry.submit()

    return {"success": True, "payment_entry": payment_entry.name, "amount": payment_entry.paid_amount}


# =============================================================================
# BATCH PROCESSING PREVENTION
# =============================================================================


@critical_api(operation_type=OperationType.FINANCIAL)
def check_batch_processing_status(batch_name: str, transaction_name: str) -> None:
    """
    Check if SEPA batch has already been processed

    Args:
        batch_name: SEPA Direct Debit Batch name
        transaction_name: Bank Transaction name

    Raises:
        ValidationError: If batch already processed
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_processing",
        "check_batch_processing_status",
        {"batch_name": batch_name, "transaction_name": transaction_name},
    )

    # Check for existing payment entries linked to this batch
    existing_payments = frappe.get_all(
        "Payment Entry",
        filters={"custom_sepa_batch": batch_name, "docstatus": 1},  # Submitted payments only
        fields=["name", "custom_bank_transaction", "paid_amount"],
    )

    if existing_payments:
        # Check if any payments are from different bank transaction
        other_transactions = [p for p in existing_payments if p.custom_bank_transaction != transaction_name]

        if other_transactions:
            raise frappe.ValidationError(
                _("SEPA batch {0} has already been processed with different bank transaction(s): {1}").format(
                    batch_name, ", ".join([p.custom_bank_transaction for p in other_transactions[:3]])
                )
            )

        # Check if same transaction is being reprocessed
        same_transaction_payments = [
            p for p in existing_payments if p.custom_bank_transaction == transaction_name
        ]
        if same_transaction_payments:
            raise frappe.ValidationError(
                _("Bank transaction {0} has already been used to process SEPA batch {1}").format(
                    transaction_name, batch_name
                )
            )


@critical_api(operation_type=OperationType.FINANCIAL)
def check_return_file_processed(return_file_hash: str) -> None:
    """
    Check if return file has already been processed

    Args:
        return_file_hash: SHA256 hash of return file content

    Raises:
        ValidationError: If return file already processed
    """
    # Log this sensitive operation
    log_sensitive_operation(
        "sepa_processing", "check_return_file_processed", {"file_hash": return_file_hash[:16] + "..."}
    )

    if frappe.db.exists("SEPA Return File Log", {"file_hash": return_file_hash}):
        raise frappe.ValidationError(_("Return file already processed"))


# =============================================================================
# PROCESSING LOCKS
# =============================================================================

_processing_locks = {}  # In-memory locks for testing; use Redis in production


@high_security_api(operation_type=OperationType.FINANCIAL)
def acquire_processing_lock(resource_type: str, resource_id: str, timeout: int = 300) -> bool:
    """
    Acquire processing lock to prevent concurrent operations

    Args:
        resource_type: Type of resource (e.g., 'sepa_batch', 'bank_transaction')
        resource_id: Unique identifier for resource
        timeout: Lock timeout in seconds

    Returns:
        True if lock acquired, False otherwise
    """
    lock_key = f"{resource_type}:{resource_id}"
    current_time = time.time()

    # Check if lock exists and is still valid
    if lock_key in _processing_locks:
        lock_time = _processing_locks[lock_key]
        if current_time - lock_time < timeout:
            return False  # Lock still active
        else:
            # Lock expired, remove it
            del _processing_locks[lock_key]

    # Acquire new lock
    _processing_locks[lock_key] = current_time
    return True


@high_security_api(operation_type=OperationType.FINANCIAL)
def release_processing_lock(resource_type: str, resource_id: str) -> None:
    """Release processing lock"""
    lock_key = f"{resource_type}:{resource_id}"
    if lock_key in _processing_locks:
        del _processing_locks[lock_key]


# =============================================================================
# IDEMPOTENCY HANDLING
# =============================================================================

_operation_cache = {}  # In-memory cache for testing; use Redis in production


@standard_api(operation_type=OperationType.FINANCIAL)
def generate_idempotency_key(bank_transaction: str, batch: str, operation: str) -> str:
    """
    Generate unique idempotency key for operation

    Args:
        bank_transaction: Bank transaction identifier
        batch: SEPA batch identifier
        operation: Operation type

    Returns:
        SHA256 hash as idempotency key
    """
    content = f"{bank_transaction}:{batch}:{operation}:{frappe.session.user}"
    return hashlib.sha256(content.encode()).hexdigest()


@critical_api(operation_type=OperationType.FINANCIAL)
def execute_idempotent_operation(idempotency_key: str, operation_func) -> Dict:
    """
    Execute operation with idempotency protection

    Args:
        idempotency_key: Unique key for operation
        operation_func: Function to execute

    Returns:
        Operation result
    """
    # Check if operation already executed
    if idempotency_key in _operation_cache:
        cached_result = _operation_cache[idempotency_key]
        frappe.logger().info(f"Returning cached result for idempotency key: {idempotency_key}")
        return cached_result

    # Execute operation and cache result
    try:
        result = operation_func()
        _operation_cache[idempotency_key] = result
        return result
    except Exception as e:
        # Don't cache failures
        frappe.logger().error(f"Operation failed for idempotency key {idempotency_key}: {str(e)}")
        raise


# =============================================================================
# AMOUNT MATCHING WITH TOLERANCE
# =============================================================================


def amounts_match_with_tolerance(expected: float, actual: float, tolerance: float = 0.02) -> bool:
    """
    Check if amounts match within tolerance

    Args:
        expected: Expected amount
        actual: Actual amount received
        tolerance: Maximum difference allowed

    Returns:
        True if amounts match within tolerance
    """
    difference = abs(flt(expected) - flt(actual))
    return difference <= tolerance


# =============================================================================
# SPLIT PAYMENT DETECTION
# =============================================================================


@standard_api(operation_type=OperationType.FINANCIAL)
def identify_split_payment_scenario(bank_transaction) -> List[Dict]:
    """
    Identify scenarios where one bank transaction covers multiple SEPA batches

    Args:
        bank_transaction: Bank transaction document

    Returns:
        List of possible batch combinations
    """
    transaction_amount = flt(bank_transaction.deposit)
    transaction_date = bank_transaction.date

    # Get potential batches within date range
    date_range_start = transaction_date if transaction_date else getdate()
    date_range_end = date_range_start  # Same day for split payments

    potential_batches = frappe.get_all(
        "Direct Debit Batch",
        filters={
            "batch_date": ["between", [date_range_start, date_range_end]],
            "docstatus": 1,
            "status": ["in", ["Submitted", "Generated"]],
        },
        fields=["name", "total_amount", "batch_date", "entry_count"],
    )

    # Find combinations that sum to transaction amount
    valid_combinations = []

    def find_combinations(batches, target_amount, current_combination=None, start_index=0):
        if current_combination is None:
            current_combination = []

        current_sum = sum(batch["total_amount"] for batch in current_combination)

        # Check if we've found a valid combination
        if amounts_match_with_tolerance(current_sum, target_amount):
            valid_combinations.append(
                {
                    "batches": current_combination.copy(),
                    "total_amount": current_sum,
                    "batch_count": len(current_combination),
                }
            )
            return

        # If sum exceeds target, stop exploring this path
        if current_sum > target_amount:
            return

        # Try adding each remaining batch
        for i in range(start_index, len(batches)):
            batch = batches[i]
            current_combination.append(batch)
            find_combinations(batches, target_amount, current_combination, i + 1)
            current_combination.pop()

    find_combinations(potential_batches, transaction_amount)

    # Sort by preference (fewer batches preferred)
    valid_combinations.sort(key=lambda x: x["batch_count"])

    return valid_combinations


# =============================================================================
# PARTIAL SUCCESS ITEM IDENTIFICATION
# =============================================================================


@standard_api(operation_type=OperationType.FINANCIAL)
def identify_partial_success_items(batch_items: List[Dict], received_amount: float) -> List[List[Dict]]:
    """
    Identify which batch items match the received amount in partial success scenarios

    Args:
        batch_items: List of items in SEPA batch
        received_amount: Amount actually received

    Returns:
        List of possible item combinations
    """
    valid_combinations = []

    def find_item_combinations(items, target_amount, current_combination=None, start_index=0):
        if current_combination is None:
            current_combination = []

        current_sum = sum(flt(item["amount"]) for item in current_combination)

        # Check if we've found a valid combination
        if amounts_match_with_tolerance(current_sum, target_amount):
            valid_combinations.append(current_combination.copy())
            return

        # If sum exceeds target, stop exploring this path
        if current_sum > target_amount:
            return

        # Try adding each remaining item
        for i in range(start_index, len(items)):
            item = items[i]
            current_combination.append(item)
            find_item_combinations(items, target_amount, current_combination, i + 1)
            current_combination.pop()

    find_item_combinations(batch_items, received_amount)

    return valid_combinations


# =============================================================================
# TRANSACTION ORDERING
# =============================================================================


def process_out_of_order_transactions(transactions: List[Dict]) -> List[Dict]:
    """
    Sort transactions in chronological order for proper processing

    Args:
        transactions: List of bank transactions

    Returns:
        Transactions sorted by date
    """
    return sorted(transactions, key=lambda t: t.get("date", getdate()))


# =============================================================================
# DATA INTEGRITY CHECKS
# =============================================================================


@standard_api(operation_type=OperationType.FINANCIAL)
def detect_orphaned_payments() -> List[Dict]:
    """
    Detect payment entries without corresponding bank transactions

    Returns:
        List of orphaned payment entries
    """
    # Get all SEPA-related payment entries
    sepa_payments = frappe.get_all(
        "Payment Entry",
        filters={"custom_sepa_batch": ["!=", ""], "docstatus": 1},
        fields=["name", "custom_bank_transaction", "custom_sepa_batch", "paid_amount"],
    )

    orphaned = []

    for payment in sepa_payments:
        bank_transaction = payment.custom_bank_transaction

        if not bank_transaction:
            orphaned.append(
                {
                    "name": payment.name,
                    "reason": "Missing bank transaction reference",
                    "sepa_batch": payment.custom_sepa_batch,
                }
            )
        elif not frappe.db.exists("Bank Transaction", bank_transaction):
            orphaned.append(
                {
                    "name": payment.name,
                    "reason": "Referenced bank transaction does not exist",
                    "missing_transaction": bank_transaction,
                    "sepa_batch": payment.custom_sepa_batch,
                }
            )

    return orphaned


@standard_api(operation_type=OperationType.FINANCIAL)
def detect_incomplete_reversals() -> List[Dict]:
    """
    Detect incomplete payment reversals from return processing

    Returns:
        List of incomplete reversals
    """
    # Find return file logs that have been processed
    return_records = frappe.get_all(
        "SEPA Return File Log",
        filters={"status": "Completed"},
        fields=["name", "processing_result", "return_count", "processed_by"],
    )

    incomplete = []

    for return_record in return_records:
        # Parse return data from processing result
        try:
            if not return_record.processing_result:
                continue

            # This is a simplified check - actual implementation would need
            # to parse the SEPA return file format and check individual returns
            # TODO: Parse return_data = json.loads(return_record.processing_result) for detailed analysis
            if return_record.return_count > 0:
                incomplete.append(
                    {
                        "return_file_log": return_record.name,
                        "return_count": return_record.return_count,
                        "reason": "Return file processed but individual return handling may need review",
                        "processed_by": return_record.processed_by,
                    }
                )

        except Exception as e:
            # Skip records with invalid JSON
            frappe.logger().warning(f"Could not parse processing_result for {return_record.name}: {str(e)}")
            continue

    return incomplete


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================


@standard_api(operation_type=OperationType.FINANCIAL)
def validate_batch_mandates(batch_data: Dict) -> Dict:
    """
    Validate that all batch items have valid SEPA mandates

    Args:
        batch_data: SEPA batch data

    Returns:
        Validation result with missing mandates
    """
    missing_mandates = []

    for item in batch_data.get("invoices", []):
        customer = item.get("customer")

        if not customer:
            missing_mandates.append({"invoice": item.get("invoice"), "reason": "No customer specified"})
            continue

        # Check for active SEPA mandate
        active_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": customer, "status": "Active", "is_active": 1, "used_for_memberships": 1},
            fields=["name", "mandate_id"],
        )

        if not active_mandates:
            missing_mandates.append(
                {
                    "customer": customer,
                    "invoice": item.get("invoice"),
                    "reason": "No active SEPA mandate found",
                }
            )

    return {
        "valid": len(missing_mandates) == 0,
        "missing_mandates": missing_mandates,
        "total_items": len(batch_data.get("invoices", [])),
        "valid_items": len(batch_data.get("invoices", [])) - len(missing_mandates),
    }


@standard_api(operation_type=OperationType.FINANCIAL)
def validate_bank_details_consistency(batch_data: Dict) -> Dict:
    """
    Validate consistency of bank details between batch creation and processing

    Args:
        batch_data: SEPA batch data

    Returns:
        Validation result with inconsistencies
    """
    iban_mismatches = []

    for item in batch_data.get("invoices", []):
        mandate_name = item.get("mandate")
        customer = item.get("customer")

        if not mandate_name or not customer:
            continue

        try:
            # Get mandate IBAN
            mandate = frappe.get_doc("SEPA Mandate", mandate_name)
            mandate_iban = mandate.iban.replace(" ", "").upper() if mandate.iban else ""

            # Get current member IBAN
            member = frappe.get_doc("Member", {"customer": customer})
            current_iban = member.iban.replace(" ", "").upper() if member.iban else ""

            if mandate_iban != current_iban:
                iban_mismatches.append(
                    {
                        "customer": customer,
                        "mandate": mandate_name,
                        "mandate_iban": mandate.iban,
                        "current_iban": member.iban,
                        "invoice": item.get("invoice"),
                    }
                )

        except frappe.DoesNotExistError:
            # Handle missing mandate or member gracefully
            pass

    return {
        "valid": len(iban_mismatches) == 0,
        "iban_mismatches": iban_mismatches,
        "total_items": len(batch_data.get("invoices", [])),
        "consistent_items": len(batch_data.get("invoices", [])) - len(iban_mismatches),
    }
