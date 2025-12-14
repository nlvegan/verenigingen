"""
Bulk Payment Checker for Mollie Customer IDs

This service iterates through all Member records with Mollie customer IDs
and checks for new payments that haven't been processed yet.

Designed as a two-stage manual function with the aim to become a scheduled task.
"""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.integrations.mollie.core.client import MollieClient
from verenigingen.integrations.mollie.core.mollie_models import Payment as MolliePayment
from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor
from verenigingen.integrations.mollie.utils.amount_helpers import (
    extract_amount_currency,
    extract_amount_float,
    extract_amount_value,
)


# Configuration constants
class BulkPaymentCheckerConfig:
    """Configuration constants for bulk payment checker"""

    # API and processing limits
    MAX_PAYMENTS_PER_CUSTOMER = 250  # Mollie API limit
    DEFAULT_LOOKBACK_DAYS = 7  # One week of recent payments
    MAX_DAYS_BACK = 30  # Maximum 1 month history per run (reduced from 90 to prevent memory issues)

    # Batch processing
    MAX_BATCH_SIZE = 50  # Maximum payments to process at once (reduced from 100 for safer manual processing)
    MAX_MEMBERS_PER_RUN = 100  # Maximum members to check per operation

    # Circuit breaker settings
    MAX_CONSECUTIVE_ERRORS = 5  # Stop after N consecutive API failures
    ERROR_BUDGET_PERCENTAGE = 10  # Stop if >10% of operations fail (reduced from 20% - 1 in 10 is concerning)

    # Rate limiting (Mollie: 100 requests/minute limit)
    # At 600ms delay: 1000ms / 600ms = 1.67 req/sec = ~100 req/min (safe)
    # At 100ms delay: 1000ms / 100ms = 10 req/sec = 600 req/min (EXCEEDS LIMIT!)
    API_CALL_DELAY_MS = 600  # 600ms delay between Mollie API calls (matches Mollie's 100 req/min limit)
    MAX_REQUESTS_PER_MINUTE = 80  # Safety margin below Mollie's 100/min

    # Invoice matching constants
    # Allow payment matching within 3 months before/after coverage period
    # Business rule: Members may pay early or late, we still want to match
    INVOICE_MATCH_BUFFER_MONTHS = 3

    # Amount matching tolerance in EUR (1 cent)
    # Prevents floating-point comparison issues while ensuring exact matches
    INVOICE_AMOUNT_TOLERANCE_EUR = 0.01


class BulkPaymentChecker:
    """
    Check all Member Mollie customer IDs for new payments.

    Two-stage process:
    1. Discovery: Find all unprocessed payments for all customers
    2. Processing: Process selected payments through dues payment processor
    """

    def __init__(self):
        self.mollie_client = MollieClient()
        self.dues_processor = DuesPaymentProcessor()

    def find_matching_unpaid_dues_invoice(
        self,
        member_name: str,
        payment_amount: float,
        payment_date: datetime,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a matching unpaid dues invoice for a member and payment.

        Matching criteria:
        1. is_membership_invoice = 1
        2. Has coverage_start_date and coverage_end_date
        3. Amount matches exactly
        4. Invoice is unpaid (outstanding_amount > 0, docstatus = 1)
        5. Payment date within coverage period OR within 3-month buffer

        Priority:
        1. Primary: Payment date falls within coverage period
        2. Fallback: Payment date within 3-month buffer of coverage period

        Args:
            member_name: Member record name
            payment_amount: Payment amount in EUR
            payment_date: Payment date (datetime)

        Returns:
            Dict with invoice details if found, None otherwise
        """
        # Get member's customer
        customer = frappe.db.get_value("Member", member_name, "customer")
        if not customer:
            return None

        # Validate and convert payment_date to date
        if isinstance(payment_date, datetime):
            payment_date_only = payment_date.date()
        elif isinstance(payment_date, date):
            payment_date_only = payment_date
        else:
            raise ValueError(f"payment_date must be date or datetime, got {type(payment_date).__name__}")

        # Query for matching unpaid dues invoices
        # Uses CASE to prioritize invoices where payment falls within coverage period
        #
        # Field validation note: This query uses custom fields on Sales Invoice:
        # - custom_coverage_start_date, custom_coverage_end_date: Created via fixtures (custom_field.json)
        # - is_membership_invoice: Standard field from verenigingen customizations
        # Constants: INVOICE_AMOUNT_TOLERANCE_EUR (0.01), INVOICE_MATCH_BUFFER_MONTHS (3)
        amount_tolerance = BulkPaymentCheckerConfig.INVOICE_AMOUNT_TOLERANCE_EUR
        buffer_months = BulkPaymentCheckerConfig.INVOICE_MATCH_BUFFER_MONTHS

        invoices = frappe.db.sql(
            f"""
            SELECT
                name,
                grand_total,
                outstanding_amount,
                custom_coverage_start_date,
                custom_coverage_end_date,
                posting_date,
                CASE
                    WHEN %s BETWEEN custom_coverage_start_date AND custom_coverage_end_date
                    THEN 0
                    ELSE 1
                END as match_priority
            FROM `tabSales Invoice`
            WHERE customer = %s
              AND is_membership_invoice = 1
              AND docstatus = 1
              AND outstanding_amount > 0
              AND ABS(grand_total - %s) < {amount_tolerance}
              AND custom_coverage_start_date IS NOT NULL
              AND custom_coverage_end_date IS NOT NULL
              AND %s BETWEEN
                  DATE_SUB(custom_coverage_start_date, INTERVAL {buffer_months} MONTH)
                  AND DATE_ADD(custom_coverage_end_date, INTERVAL {buffer_months} MONTH)
            ORDER BY match_priority ASC, custom_coverage_start_date DESC
            LIMIT 1
            """,
            (payment_date_only, customer, payment_amount, payment_date_only),
            as_dict=True,
        )

        if invoices:
            invoice = invoices[0]
            return {
                "invoice_name": invoice.name,
                "invoice_amount": float(invoice.grand_total),
                "outstanding_amount": float(invoice.outstanding_amount),
                "coverage_start": str(invoice.custom_coverage_start_date),
                "coverage_end": str(invoice.custom_coverage_end_date),
                "posting_date": str(invoice.posting_date),
                "match_type": "within_coverage" if invoice.match_priority == 0 else "within_buffer",
            }

        return None

    def check_invoice_match_for_payment(
        self,
        sdk_payment: Any,
        member_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Check if an SDK payment matches an unpaid dues invoice.

        Convenience method that handles date parsing from SDK payment objects
        and delegates to find_matching_unpaid_dues_invoice.

        Args:
            sdk_payment: Raw Mollie SDK payment object (supports dict-like access)
            member_name: Member record name

        Returns:
            Dict with invoice details if found, None otherwise
        """
        try:
            # Extract amount
            amount_obj = sdk_payment.amount if hasattr(sdk_payment, "amount") else sdk_payment.get("amount")
            if not amount_obj:
                return None

            payment_amount = float(
                amount_obj["value"] if isinstance(amount_obj, dict) else amount_obj.get("value")
            )

            # Parse payment date - prefer paid_at for accuracy
            paid_at = getattr(sdk_payment, "paid_at", None) or sdk_payment.get("paidAt")
            created_at = getattr(sdk_payment, "created_at", None) or sdk_payment.get("createdAt")

            date_str = paid_at or created_at
            if not date_str:
                return None

            # Parse ISO date string to datetime
            if isinstance(date_str, str):
                payment_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                payment_date = date_str  # Already a datetime

            return self.find_matching_unpaid_dues_invoice(
                member_name=member_name, payment_amount=payment_amount, payment_date=payment_date
            )
        except Exception as e:
            frappe.logger().warning(f"Error checking invoice match for payment: {e}")
            return None

    def get_members_with_mollie_customers(
        self, limit: Optional[int] = None, offset: int = 0
    ) -> Dict[str, Any]:
        """
        Get Member records that have a Mollie customer ID (with pagination).

        Args:
            limit: Maximum members to retrieve (defaults to MAX_MEMBERS_PER_RUN)
            offset: Number of records to skip (for pagination)

        Returns:
            Dict with:
                - members: List of member dicts
                - count: Number of members returned
                - has_more: Whether more members exist
                - total_count: Total members with Mollie customer IDs
        """
        if limit is None:
            limit = BulkPaymentCheckerConfig.MAX_MEMBERS_PER_RUN

        # Enforce maximum limit (only when called without explicit override)
        # Allow larger limits when explicitly requested (e.g., from mollie_payments_debug page)
        # Cap at a reasonable maximum to prevent memory issues
        if limit > 10000:
            limit = 10000

        # Get total count (for progress tracking)
        total_count = frappe.db.count(
            "Member",
            filters={
                "mollie_customer_id": ["not in", ["", None]],
            },
        )

        # Fetch one extra to check if more exist
        members = frappe.db.sql(
            """
            SELECT name, full_name, mollie_customer_id
            FROM `tabMember`
            WHERE mollie_customer_id IS NOT NULL
              AND mollie_customer_id != ''
            ORDER BY modified DESC
            LIMIT %s OFFSET %s
            """,
            (limit + 1, offset),
            as_dict=True,
        )

        has_more = len(members) > limit
        if has_more:
            members = members[:limit]

        frappe.logger().info(
            f"Retrieved {len(members)} members (offset: {offset}, total: {total_count}, has_more: {has_more})"
        )

        return {
            "members": members,
            "count": len(members),
            "has_more": has_more,
            "total_count": total_count,
            "offset": offset,
        }

    def check_payments_for_customer(
        self,
        customer_id: str,
        member_name: str,
        from_date: Optional[datetime] = None,
        limit: int = 250,
    ) -> Dict[str, Any]:
        """
        Check for new payments for a specific Mollie customer.

        Args:
            customer_id: Mollie customer ID
            member_name: Member record name (for logging and linking)
            from_date: Only retrieve payments after this date
            limit: Maximum payments to retrieve per customer

        Returns:
            Dict containing:
                - customer_id: Mollie customer ID
                - member: Member record name
                - payments: List of payment details with processing status
                - total_found: Total payments retrieved
                - new_payments: Number of unprocessed payments
                - error: Error message if failed
        """
        result = {
            "customer_id": customer_id,
            "member": member_name,
            "payments": [],
            "total_found": 0,
            "new_payments": 0,
            "error": None,
            "filtered_by_date": 0,
            "filtered_by_duplicate": 0,
        }

        try:
            # Get customer object from Mollie with retry logic for rate limiting
            client = self.mollie_client.sdk_client

            # Try to get customer with HTTP 429 handling
            try:
                customer_obj = client.customers.get(customer_id)
            except Exception as e:
                # Check if this is a rate limit error (HTTP 429)
                if hasattr(e, "status") and e.status == 429:
                    # Mollie rate limit hit - wait and retry once
                    retry_after = 60  # Default 60 seconds if no Retry-After header

                    frappe.logger().warning(
                        f"Mollie rate limit (HTTP 429) hit for customer {customer_id}. "
                        f"Waiting {retry_after}s before retry..."
                    )

                    time.sleep(retry_after)

                    # Retry once after waiting
                    try:
                        customer_obj = client.customers.get(customer_id)
                        frappe.logger().info(f"✅ Retry successful after rate limit wait for {customer_id}")
                    except Exception as retry_error:
                        # Retry failed - propagate error
                        frappe.logger().error(f"Retry failed after rate limit wait: {retry_error}")
                        raise
                else:
                    # Not a rate limit error - propagate normally
                    raise

            # Get all payments for this customer and convert to typed objects
            sdk_payments = customer_obj.payments.list(limit=limit)
            result["total_found"] = len(sdk_payments)

            # Convert SDK payments to typed Payment objects with proper datetime parsing
            # This ensures created_at and paid_at are datetime objects, not strings
            payments: List[MolliePayment] = []
            for sdk_payment in sdk_payments:
                try:
                    payments.append(MolliePayment.from_mollie_api(sdk_payment))
                except Exception as e:
                    frappe.logger().warning(
                        f"Could not convert payment {sdk_payment.get('id', 'unknown')} to typed object: {e}"
                    )
                    continue

            # Filter by date if requested
            if from_date:
                # Ensure from_date is timezone-aware
                if from_date.tzinfo is None:
                    from_date = from_date.replace(tzinfo=timezone.utc)

            # Deduplicate payment IDs (Mollie API sometimes returns duplicates)
            seen_payment_ids = set()

            # Debug counters to track filtering
            filtered_by_date = 0
            filtered_by_duplicate = 0
            payments_added = 0

            for payment in payments:
                # Apply date filter
                # CRITICAL: Use paid_at for financial reconciliation (when money actually moved)
                # Fall back to created_at only for pending/unpaid payments
                if from_date:
                    # Use paid_at (when payment completed) for accurate financial reconciliation
                    payment_date = payment.paid_at if payment.paid_at else payment.created_at

                    if payment_date is None:
                        frappe.logger().warning(f"Payment {payment.id} has no date, excluding from results")
                        filtered_by_date += 1
                        continue

                    # Make payment_date timezone-aware if needed
                    if payment_date.tzinfo is None:
                        payment_date = payment_date.replace(tzinfo=timezone.utc)

                    if payment_date < from_date:
                        filtered_by_date += 1
                        continue

                # Deduplicate: Skip if we've already seen this payment ID
                if payment.id in seen_payment_ids:
                    filtered_by_duplicate += 1
                    frappe.logger().warning(
                        f"⚠️ Duplicate payment ID from Mollie API: {payment.id} for member {member_name}. "
                        f"This indicates the API returned the same payment multiple times."
                    )
                    continue
                seen_payment_ids.add(payment.id)

                # Memory protection: Circuit breaker for excessive payment volumes
                if len(seen_payment_ids) > 10000:
                    frappe.logger().error(
                        f"⚠️ MEMORY LIMIT EXCEEDED: Processed {len(seen_payment_ids)} unique payments "
                        f"for customer {customer_id} (Member: {member_name}). "
                        f"Stopping pagination to prevent memory issues. "
                        f"This indicates either an API issue or misconfigured date range."
                    )
                    break

                # Check if already processed using centralized service
                from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                    get_bank_transaction_creator,
                )

                creator = get_bank_transaction_creator()
                idempotency_check = creator.check_already_processed(
                    payment.id,
                    check_payment_entry=True,
                )

                # Identify payment type
                payment_type = self.dues_processor.identify_payment_type(payment)

                # Extract amount using helper functions that handle SDK dict format
                amount_value = extract_amount_value(payment.amount)
                currency = extract_amount_currency(payment.amount)

                # Check for currency mismatch (warning if not EUR)
                currency_warning = None
                if currency != "Unknown" and currency != "EUR":
                    currency_warning = (
                        f"Non-EUR currency: {currency}. Exchange rate handling may be required."
                    )
                    frappe.logger().warning(
                        f"Payment {payment.id} uses {currency} instead of EUR. "
                        f"Member: {member_name}. Manual review may be needed."
                    )

                # Check for matching unpaid dues invoice (for intelligent processing)
                matching_invoice = None
                if (
                    payment.status == "paid"
                    and payment_type == "dues"
                    and not idempotency_check["already_processed"]
                    and currency_warning is None
                    and amount_value != "Unknown"
                ):
                    try:
                        # Get payment date (prefer paid_at for accuracy)
                        # MolliePayment has typed datetime fields - no string parsing needed
                        invoice_check_date = payment.paid_at or payment.created_at

                        payment_amount_float = extract_amount_float(payment.amount)
                        matching_invoice = self.find_matching_unpaid_dues_invoice(
                            member_name=member_name,
                            payment_amount=payment_amount_float,
                            payment_date=invoice_check_date,
                        )
                    except (ValueError, TypeError) as e:
                        frappe.logger().warning(
                            f"Could not check for matching invoice for payment {payment.id}: {e}"
                        )

                payment_info = {
                    "id": payment.id,
                    "status": payment.status,
                    "amount": amount_value,
                    "currency": currency,
                    "amount_display": (
                        f"{currency} {amount_value}" if amount_value != "Unknown" else "Unknown"
                    ),
                    "description": payment.description,
                    "created_at": str(payment.created_at),
                    "paid_at": str(payment.paid_at) if payment.paid_at else None,
                    "subscription_id": payment.subscription_id,
                    "payment_type": payment_type,
                    "already_processed": idempotency_check["already_processed"],
                    "payment_entry": idempotency_check.get("payment_entry"),
                    "bank_transaction": idempotency_check.get("bank_transaction"),
                    "currency_warning": currency_warning,  # Alert UI about currency issues
                    "processable": (
                        payment.status == "paid"
                        and payment_type == "dues"
                        and not idempotency_check["already_processed"]
                        and currency_warning is None  # Don't auto-process non-EUR payments
                    ),
                    # Intelligent processing: matching invoice info
                    "matching_invoice": matching_invoice,
                    "processing_mode": ("bt_pe_reconcile" if matching_invoice else "bt_only")
                    if (
                        payment.status == "paid"
                        and payment_type == "dues"
                        and not idempotency_check["already_processed"]
                    )
                    else None,
                }

                result["payments"].append(payment_info)
                payments_added += 1

                # Count new unprocessed payments
                if payment_info["processable"]:
                    result["new_payments"] += 1

            # Save filtering statistics to result
            result["filtered_by_date"] = filtered_by_date
            result["filtered_by_duplicate"] = filtered_by_duplicate

            # Validate counter accuracy - ensure no payments are lost or double-counted
            expected_after_filtering = result["total_found"] - (filtered_by_date + filtered_by_duplicate)
            actual_after_filtering = len(result["payments"])
            if expected_after_filtering != actual_after_filtering:
                frappe.logger().error(
                    f"⚠️ COUNTER MISMATCH for customer {customer_id} (Member: {member_name}): "
                    f"Expected {expected_after_filtering} payments after filtering "
                    f"(found={result['total_found']}, date_filtered={filtered_by_date}, "
                    f"dup_filtered={filtered_by_duplicate}), "
                    f"but got {actual_after_filtering} in result. "
                    f"This indicates a bug in filtering logic."
                )

            # Log filtering statistics for this customer
            if filtered_by_date > 0 or filtered_by_duplicate > 0:
                frappe.logger().info(
                    f"Customer {customer_id} (Member: {member_name}): "
                    f"Found {result['total_found']} payments from Mollie API, "
                    f"added {payments_added} after filtering "
                    f"(filtered: {filtered_by_date} by date, {filtered_by_duplicate} duplicates)"
                )
            else:
                frappe.logger().info(
                    f"Customer {customer_id} (Member: {member_name}): "
                    f"Found {result['total_found']} payments, {result['new_payments']} new/unprocessed"
                )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(
                f"Error checking payments for customer {customer_id} (Member: {member_name}): {e}",
                "Bulk Payment Checker Error",
            )

        return result

    def check_all_customers_for_new_payments(
        self,
        days_back: int = 7,
        all_history: bool = False,
        limit_per_customer: int = 250,
        max_members: Optional[int] = None,
        retrieval_mode: str = "customer",
        date_offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Stage 1: Discovery - Check all member Mollie customers for new payments.

        This is the discovery phase that identifies which payments exist but haven't
        been processed. The results should be reviewed before processing.

        Args:
            days_back: Number of days back to check (default: 7 for this week)
            all_history: If True, retrieve all historical payments (ignores days_back)
            limit_per_customer: Maximum payments to retrieve per customer (customer mode only)
            max_members: Maximum members to check (defaults to MAX_MEMBERS_PER_RUN, customer mode only)
            retrieval_mode: "customer" (iterate through members) or "balance_transactions" (get all balance txs)
            date_offset: Start lookback N days ago (e.g., 30 = check days 30-37 ago if days_back=7)

        Returns:
            Dict containing:
                - total_members: Total members with Mollie customer IDs (customer mode only)
                - members_checked: Number of members successfully checked (customer mode only)
                - total_payments_found: Total payments discovered
                - total_new_payments: Total unprocessed payments
                - customers: List of customer results (customer mode) or None
                - balance_transactions: List of balance transaction results (balance mode) or None
                - errors: Number of errors encountered
                - circuit_breaker_triggered: Whether operation stopped due to errors
                - summary: Human-readable summary
                - retrieval_mode: Mode used for retrieval
        """
        # Validate retrieval mode
        if retrieval_mode not in ["customer", "balance_transactions"]:
            frappe.throw(_("Invalid retrieval_mode. Must be 'customer' or 'balance_transactions'"))

        # Route to appropriate method
        if retrieval_mode == "balance_transactions":
            return self._check_via_balance_transactions(days_back=days_back, date_offset=date_offset)
        else:
            return self._check_via_customers(
                days_back=days_back,
                all_history=all_history,
                limit_per_customer=limit_per_customer,
                max_members=max_members,
                date_offset=date_offset,
            )

    def _check_via_customers(
        self,
        days_back: int = 7,
        all_history: bool = False,
        limit_per_customer: int = 250,
        max_members: Optional[int] = None,
        date_offset: int = 0,
    ) -> Dict[str, Any]:
        """Customer-by-customer payment checking (original implementation)"""
        result = {
            "retrieval_mode": "customer",
            "total_members": 0,
            "members_checked": 0,
            "total_payments_found": 0,
            "total_new_payments": 0,
            "customers": [],
            "errors": 0,
            "error_details": [],  # List of error messages with member/customer context
            "circuit_breaker_triggered": False,
            "started_at": frappe.utils.now(),
            "completed_at": None,
            "summary": "",
            # Filtering statistics
            "total_filtered_by_date": 0,
            "total_filtered_by_duplicate": 0,
            "total_payments_after_filtering": 0,
        }

        try:
            # Validate and enforce limits
            if days_back > BulkPaymentCheckerConfig.MAX_DAYS_BACK:
                frappe.throw(
                    _(
                        f"Cannot retrieve more than {BulkPaymentCheckerConfig.MAX_DAYS_BACK} days of history. "
                        f"Use multiple smaller requests for historical data."
                    )
                )

            # Calculate date filter with offset support
            # date_offset allows searching historical periods
            # Example: offset=30, days_back=7 searches days 30-37 ago
            from_date = None
            if not all_history:
                # Apply offset: start from (now - offset - days_back) to (now - offset)
                end_offset = date_offset
                start_offset = date_offset + days_back

                from_date = datetime.now(timezone.utc) - timedelta(days=start_offset)
                to_date = (
                    datetime.now(timezone.utc) - timedelta(days=end_offset)
                    if end_offset > 0
                    else datetime.now(timezone.utc)
                )

                frappe.logger().info(
                    f"Checking payments from {from_date.strftime('%Y-%m-%d')} "
                    f"to {to_date.strftime('%Y-%m-%d')} (offset: {date_offset} days)"
                )
            else:
                frappe.logger().info("Checking ALL historical payments (limited to 90 days)")
                from_date = datetime.now(timezone.utc) - timedelta(
                    days=BulkPaymentCheckerConfig.MAX_DAYS_BACK
                )

            # Get members with pagination
            members_data = self.get_members_with_mollie_customers(limit=max_members)
            members = members_data["members"]
            result["total_members"] = members_data["total_count"]

            # Circuit breaker state
            consecutive_errors = 0
            error_budget = int(len(members) * BulkPaymentCheckerConfig.ERROR_BUDGET_PERCENTAGE / 100)

            # Check each customer with circuit breaker
            for idx, member in enumerate(members):
                # Progress logging every 10 members
                if (idx + 1) % 10 == 0:
                    frappe.logger().info(f"Progress: {idx + 1}/{len(members)} members checked")

                customer_result = self.check_payments_for_customer(
                    customer_id=member["mollie_customer_id"],
                    member_name=member["name"],
                    from_date=from_date,
                    limit=limit_per_customer,
                )

                result["customers"].append(customer_result)
                result["members_checked"] += 1
                result["total_payments_found"] += customer_result["total_found"]
                result["total_new_payments"] += customer_result["new_payments"]

                # Aggregate filtering statistics
                result["total_payments_after_filtering"] += len(customer_result.get("payments", []))
                result["total_filtered_by_date"] += customer_result.get("filtered_by_date", 0)
                result["total_filtered_by_duplicate"] += customer_result.get("filtered_by_duplicate", 0)

                if customer_result["error"]:
                    result["errors"] += 1
                    consecutive_errors += 1

                    # Collect error details for display
                    result["error_details"].append(
                        {
                            "member": member["name"],
                            "member_full_name": member.get("full_name", "Unknown"),
                            "customer_id": member["mollie_customer_id"],
                            "error": customer_result["error"],
                            "step": "customer_payment_check",
                        }
                    )

                    # Circuit breaker: Stop after consecutive errors
                    if consecutive_errors >= BulkPaymentCheckerConfig.MAX_CONSECUTIVE_ERRORS:
                        result["circuit_breaker_triggered"] = True
                        result[
                            "summary"
                        ] = f"STOPPED: {BulkPaymentCheckerConfig.MAX_CONSECUTIVE_ERRORS} consecutive API errors"
                        frappe.logger().warning(
                            f"Circuit breaker triggered: {consecutive_errors} consecutive errors"
                        )
                        break

                    # Circuit breaker: Stop if error budget exceeded
                    if result["errors"] > error_budget:
                        result["circuit_breaker_triggered"] = True
                        result[
                            "summary"
                        ] = f"STOPPED: Error rate exceeded {BulkPaymentCheckerConfig.ERROR_BUDGET_PERCENTAGE}% threshold"
                        frappe.logger().warning(
                            f"Circuit breaker triggered: {result['errors']} total errors (budget: {error_budget})"
                        )
                        break
                else:
                    consecutive_errors = 0  # Reset on success

                # Rate limiting: Small delay between API calls
                time.sleep(BulkPaymentCheckerConfig.API_CALL_DELAY_MS / 1000)

            result["completed_at"] = frappe.utils.now()

            # Generate summary if not already set by circuit breaker
            if not result["summary"]:
                date_range = (
                    f"last {days_back} days"
                    if not all_history
                    else f"last {BulkPaymentCheckerConfig.MAX_DAYS_BACK} days"
                )

                # Calculate total filtered
                total_filtered = result["total_filtered_by_date"] + result["total_filtered_by_duplicate"]

                # Build summary with filtering details if any filtering occurred
                if total_filtered > 0:
                    result["summary"] = (
                        f"Checked {result['members_checked']}/{result['total_members']} members. "
                        f"Found {result['total_payments_found']} payments from Mollie API ({date_range}), "
                        f"{result['total_payments_after_filtering']} after filtering "
                        f"({result['total_filtered_by_date']} by date, {result['total_filtered_by_duplicate']} duplicates). "
                        f"{result['total_new_payments']} new/unprocessed. "
                        f"Errors: {result['errors']}"
                    )
                else:
                    result["summary"] = (
                        f"Checked {result['members_checked']}/{result['total_members']} members. "
                        f"Found {result['total_payments_found']} payments ({date_range}), "
                        f"{result['total_new_payments']} new/unprocessed. "
                        f"Errors: {result['errors']}"
                    )

            # Audit logging
            self._log_bulk_operation_audit(result, "discovery", days_back, all_history)

            frappe.logger().info(f"✅ Bulk payment check complete: {result['summary']}")

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(f"Error in bulk payment check: {e}", "Bulk Payment Checker Error")

        return result

    def _log_bulk_operation_audit(
        self, result: Dict[str, Any], operation_type: str, days_back: int = None, all_history: bool = False
    ):
        """Log bulk payment operation to audit trail"""
        try:
            from verenigingen.utils.security.audit_logging import log_security_event

            severity = "INFO"
            if result.get("circuit_breaker_triggered"):
                severity = "WARNING"
            elif result.get("errors", 0) > 0:
                severity = "WARNING"

            details = {
                "user": frappe.session.user,
                "operation": operation_type,
                "members_checked": result.get("members_checked", 0),
                "total_members": result.get("total_members", 0),
                "total_payments_found": result.get("total_payments_found", 0),
                "new_payments": result.get("total_new_payments", 0),
                "errors": result.get("errors", 0),
                "circuit_breaker_triggered": result.get("circuit_breaker_triggered", False),
            }

            if operation_type == "discovery":
                details["date_range"] = "all_history" if all_history else f"{days_back}_days"
            elif operation_type == "processing":
                details["processed"] = result.get("processed", 0)
                details["skipped"] = result.get("skipped", 0)
                details["dry_run"] = result.get("dry_run", False)

            log_security_event(
                event_type="other",  # Use "other" instead of custom event types
                details={
                    **details,
                    "custom_event_type": f"bulk_payment_{operation_type}",  # Store actual type in details
                },
                severity=severity,
            )
        except Exception as e:
            # Don't fail bulk operation if audit logging fails, but alert admins
            frappe.logger().warning(f"Failed to log audit event: {e}")

            # CRITICAL: Log to Error Log for monitoring and alerting
            frappe.log_error(
                title="Audit Logging Failure - CRITICAL",
                message=f"Bulk payment {operation_type} completed but audit logging failed: {str(e)}\n\n"
                f"Operation details: {details}",
            )

            # Increment failure counter for monitoring dashboard
            cache_key = "audit_log_failures_count"
            failures = frappe.cache().get(cache_key) or 0
            frappe.cache().set(cache_key, failures + 1, ex=3600)  # 1 hour window

    def process_discovered_payments(self, payment_ids: List[str], dry_run: bool = False) -> Dict[str, Any]:
        """
        Stage 2: Processing - Process selected payments through dues payment processor.

        Takes the payment IDs discovered in Stage 1 and processes them.

        Args:
            payment_ids: List of Mollie payment IDs to process
            dry_run: If True, don't actually create Payment Entries (for testing)

        Returns:
            Dict with processing results:
                - total_requested: Number of payments requested to process
                - processed: Successfully processed payments
                - skipped: Payments skipped (already processed, wrong status, etc.)
                - errors: Number of errors
                - results: Detailed results for each payment
        """
        if not payment_ids:
            raise ValueError(_("No payment IDs provided"))

        result = {
            "total_requested": len(payment_ids),
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
            "dry_run": dry_run,
            "started_at": frappe.utils.now(),
            "completed_at": None,
        }

        try:
            for payment_id in payment_ids:
                try:
                    if dry_run:
                        # In dry run mode, just check what would happen
                        payment = self.mollie_client.sdk_client.payments.get(payment_id)
                        payment_type = self.dues_processor.identify_payment_type(payment)
                        member_name = self.dues_processor.find_member_for_payment(payment)

                        payment_result = {
                            "payment_id": payment_id,
                            "status": "dry_run",
                            "payment_type": payment_type,
                            "member": member_name,
                            "would_process": payment.status == "paid" and payment_type == "dues",
                        }
                        result["results"].append(payment_result)
                        result["skipped"] += 1
                    else:
                        # Actually process the payment
                        payment_result = self.dues_processor.process_dues_payment(payment_id)
                        result["results"].append(payment_result)

                        if payment_result["status"] == "success":
                            result["processed"] += 1
                        elif payment_result["status"] in ["skipped", "already_processed"]:
                            result["skipped"] += 1
                        elif payment_result["status"] == "error":
                            result["errors"] += 1

                except Exception as e:
                    result["errors"] += 1
                    result["results"].append({"payment_id": payment_id, "status": "error", "error": str(e)})
                    frappe.log_error(f"Error processing payment {payment_id}: {e}")

            result["completed_at"] = frappe.utils.now()

            # Audit logging
            self._log_bulk_operation_audit(result, "processing")

            frappe.logger().info(
                f"✅ Bulk payment processing complete: "
                f"{result['processed']} processed, {result['skipped']} skipped, {result['errors']} errors"
            )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(f"Error in bulk payment processing: {e}")

        return result

    def _check_via_balance_transactions(self, days_back: int = 10, date_offset: int = 0) -> Dict[str, Any]:
        """
        Balance transaction-based payment checking (systematic approach).

        Retrieves balance transactions from Mollie Balance API and extracts payments.
        This is more systematic than customer-by-customer iteration.

        Args:
            days_back: Number of days back to check (default: 10)
            date_offset: Start lookback N days ago (e.g., 30 = check days 30-40 ago if days_back=10)

        Returns:
            Dict with same structure as customer mode but different data source
        """
        result = {
            "retrieval_mode": "balance_transactions",
            "total_payments_found": 0,
            "total_new_payments": 0,
            "balance_transactions": [],
            "orphaned_transactions": [],  # Transactions without payment IDs
            "errors": 0,
            "error_details": [],  # List of error messages with payment IDs
            "circuit_breaker_triggered": False,
            "started_at": frappe.utils.now(),
            "completed_at": None,
            "summary": "",
        }

        try:
            # Import balance client
            from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

            balance_client = BalancesClient()

            # Calculate date range with offset support
            # date_offset allows searching historical periods
            # Example: offset=30, days_back=10 searches days 30-40 ago
            end_offset = date_offset
            start_offset = date_offset + days_back

            from_date = datetime.now(timezone.utc) - timedelta(days=start_offset)
            to_date = (
                datetime.now(timezone.utc) - timedelta(days=end_offset)
                if end_offset > 0
                else datetime.now(timezone.utc)
            )

            frappe.logger().info(
                f"Checking balance transactions from {from_date.strftime('%Y-%m-%d')} "
                f"to {to_date.strftime('%Y-%m-%d')} (offset: {date_offset} days)"
            )

            # Get primary balance
            primary_balance = balance_client.get_primary_balance()
            if not primary_balance:
                result["error"] = "No primary balance found"
                return result

            balance_id = primary_balance.id
            frappe.logger().info(f"Using primary balance: {balance_id}")

            # List balance transactions for the period
            # Note: Mollie balance API doesn't support date filtering directly
            # We get recent transactions and filter in memory
            transactions = balance_client.list_balance_transactions(
                balance_id=balance_id, limit=250  # Get last 250 transactions
            )

            frappe.logger().info(f"Retrieved {len(transactions)} balance transactions")

            # Extract payment IDs from balance transactions
            payment_ids_found = set()

            for tx in transactions:
                # Balance transactions have context with payment references
                context = getattr(tx, "context", {})

                # Extract payment ID from context
                payment_id = None
                if isinstance(context, dict):
                    payment_id = context.get("paymentId") or context.get("payment_id")

                if not payment_id:
                    # Try to get from transaction ID (some transactions have payment ID in ID)
                    tx_id = getattr(tx, "id", "")
                    if tx_id.startswith("tr_"):
                        payment_id = tx_id

                # Check date range
                tx_created = getattr(tx, "created_at", None)
                if tx_created:
                    try:
                        if isinstance(tx_created, str):
                            tx_date = datetime.fromisoformat(tx_created.replace("Z", "+00:00"))
                        else:
                            tx_date = tx_created

                        if tx_date.tzinfo is None:
                            tx_date = tx_date.replace(tzinfo=timezone.utc)

                        # Only process transactions in date range
                        if from_date <= tx_date <= to_date:
                            if payment_id and payment_id.startswith("tr_"):
                                # Valid payment found - will check member matching later
                                payment_ids_found.add(payment_id)

                                result["balance_transactions"].append(
                                    {
                                        "transaction_id": tx.id,
                                        "payment_id": payment_id,
                                        "created_at": str(tx_created),
                                        "type": getattr(tx, "type", "unknown"),
                                        "amount": str(getattr(tx, "amount", {}).get("value", "Unknown")),
                                    }
                                )
                    except Exception as date_error:
                        frappe.logger().warning(f"Could not parse date for transaction {tx.id}: {date_error}")

            result["total_payments_found"] = len(payment_ids_found)
            frappe.logger().info(f"Found {len(payment_ids_found)} unique payment IDs in date range")

            # OPTIMIZATION: Batch check all payment IDs for existing processing (2 queries instead of N*2)
            payment_ids_list = list(payment_ids_found)

            # Batch query for Payment Entries
            existing_payment_entries = {}
            if payment_ids_list:
                placeholders = ", ".join(["%s"] * len(payment_ids_list))
                pe_results = frappe.db.sql(
                    f"""
                    SELECT reference_no, name, docstatus
                    FROM `tabPayment Entry`
                    WHERE reference_no IN ({placeholders})
                    AND docstatus != 2
                    """,
                    tuple(payment_ids_list),
                    as_dict=True,
                )
                existing_payment_entries = {pe["reference_no"]: pe for pe in pe_results}
                frappe.logger().info(
                    f"Batch check found {len(existing_payment_entries)} existing Payment Entries"
                )

            # Batch query for Bank Transactions
            existing_bank_txs = {}
            if payment_ids_list:
                placeholders = ", ".join(["%s"] * len(payment_ids_list))
                bt_results = frappe.db.sql(
                    f"""
                    SELECT reference_number, name, docstatus
                    FROM `tabBank Transaction`
                    WHERE reference_number IN ({placeholders})
                    AND docstatus != 2
                    """,
                    tuple(payment_ids_list),
                    as_dict=True,
                )
                existing_bank_txs = {bt["reference_number"]: bt for bt in bt_results}
                frappe.logger().info(f"Batch check found {len(existing_bank_txs)} existing Bank Transactions")

            # Filter to only unprocessed payments
            unprocessed_payment_ids = [
                pid
                for pid in payment_ids_list
                if pid not in existing_payment_entries and pid not in existing_bank_txs
            ]

            frappe.logger().info(
                f"After batch idempotency check: {len(unprocessed_payment_ids)} unprocessed payments "
                f"out of {len(payment_ids_list)} total"
            )

            # Now process only unprocessed payments (much fewer API calls)
            for payment_id in unprocessed_payment_ids:
                try:
                    # Fetch payment details from Mollie (only for unprocessed)
                    payment = self.mollie_client.sdk_client.payments.get(payment_id)

                    # Identify payment type
                    payment_type = self.dues_processor.identify_payment_type(payment)

                    # Try to find member/donor for this payment
                    member_name = self.dues_processor.find_member_for_payment(payment)

                    # Extract currency
                    currency = payment.amount["currency"] if payment.amount else "Unknown"
                    amount = payment.amount["value"] if payment.amount else "Unknown"

                    # If we can't match to a member/donor, mark as orphaned
                    if not member_name:
                        result["orphaned_transactions"].append(
                            {
                                "payment_id": payment_id,
                                "status": payment.status,
                                "amount": f"{currency} {amount}",
                                "description": getattr(payment, "description", "No description"),
                                "customer_id": getattr(payment, "customer_id", "No customer"),
                                "subscription_id": getattr(payment, "subscription_id", None),
                                "payment_type": payment_type,
                                "paid_at": str(getattr(payment, "paid_at", None)),
                                "reason": "Cannot match to any member or donor",
                            }
                        )
                        frappe.logger().warning(
                            f"⚠️ Orphaned payment {payment_id}: {currency} {amount}, "
                            f"type: {payment_type}, cannot match to member"
                        )
                    else:
                        # Check if processable
                        is_processable = (
                            payment.status == "paid" and payment_type == "dues" and currency == "EUR"
                        )

                        if is_processable:
                            result["total_new_payments"] += 1

                    # Reduced delay for balance mode (100ms instead of 600ms)
                    # We're not hammering the primary payments API, just fetching details
                    time.sleep(0.1)

                except Exception as e:
                    result["errors"] += 1
                    error_msg = str(e)
                    result["error_details"].append(
                        {"payment_id": payment_id, "error": error_msg, "step": "payment_detail_fetch"}
                    )
                    frappe.logger().warning(f"Error checking payment {payment_id}: {e}")

            result["completed_at"] = frappe.utils.now()

            # Generate summary
            orphaned_count = len(result["orphaned_transactions"])
            result["summary"] = (
                f"Checked {result['total_payments_found']} payments from balance transactions "
                f"(last {days_back} days). Found {result['total_new_payments']} new/unprocessed. "
                f"Orphaned (no member match): {orphaned_count}. "
                f"Errors: {result['errors']}"
            )

            if orphaned_count > 0:
                frappe.logger().warning(
                    f"⚠️ {orphaned_count} orphaned payments found that cannot be matched to members"
                )

            frappe.logger().info(f"✅ Balance transaction check complete: {result['summary']}")

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(f"Error in balance transaction check: {e}", "Bulk Payment Checker Error")

        return result
