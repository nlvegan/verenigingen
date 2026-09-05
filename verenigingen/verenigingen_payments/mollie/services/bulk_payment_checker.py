"""
Bulk Payment Checker for Mollie Customer IDs

This service iterates through all Member records with Mollie customer IDs
and checks for new payments that haven't been processed yet.

Designed as a two-stage manual function with the aim to become a scheduled task.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import cint

from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.core.mollie_models import Payment as MolliePayment
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor
from verenigingen.verenigingen_payments.mollie.utils.amount_helpers import (
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

        DEPRECATED: Use InvoiceMatcher.find_matching_invoice() instead.
        This method now delegates to the centralized InvoiceMatcher service.

        Args:
            member_name: Member record name
            payment_amount: Payment amount in EUR
            payment_date: Payment date (datetime)

        Returns:
            Dict with invoice details if found, None otherwise
        """
        import warnings

        warnings.warn(
            "BulkPaymentChecker.find_matching_unpaid_dues_invoice() is deprecated. "
            "Use InvoiceMatcher.find_matching_invoice() instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        from verenigingen.services.billing.invoice_matcher import find_matching_invoice

        result = find_matching_invoice(
            member_name=member_name,
            payment_date=payment_date,
            payment_amount=payment_amount,
            check_overlap=False,  # Preserve original behavior (no overlap warning)
        )

        if result.found:
            return {
                "invoice_name": result.invoice_name,
                "invoice_amount": result.invoice_amount,
                "outstanding_amount": result.outstanding_amount,
                "coverage_start": str(result.coverage_start) if result.coverage_start else None,
                "coverage_end": str(result.coverage_end) if result.coverage_end else None,
                "posting_date": None,  # InvoiceMatcher doesn't return posting_date
                "match_type": result.match_type,
            }

        return None

    def check_invoice_match_for_payment(
        self,
        sdk_payment: Any,
        member_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Check if an SDK payment matches an unpaid dues invoice.

        DEPRECATED: Use InvoiceMatcher.find_matching_invoice_for_payment() instead.
        This method now delegates to the centralized InvoiceMatcher service.

        Args:
            sdk_payment: Raw Mollie SDK payment object (supports dict-like access)
            member_name: Member record name

        Returns:
            Dict with invoice details if found, None otherwise
        """
        import warnings

        warnings.warn(
            "BulkPaymentChecker.check_invoice_match_for_payment() is deprecated. "
            "Use InvoiceMatcher.find_matching_invoice_for_payment() instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        from verenigingen.services.billing.invoice_matcher import find_matching_invoice_for_payment

        result = find_matching_invoice_for_payment(
            sdk_payment=sdk_payment,
            member_name=member_name,
            check_overlap=False,
        )

        if result.found:
            return {
                "invoice_name": result.invoice_name,
                "invoice_amount": result.invoice_amount,
                "outstanding_amount": result.outstanding_amount,
                "coverage_start": str(result.coverage_start) if result.coverage_start else None,
                "coverage_end": str(result.coverage_end) if result.coverage_end else None,
                "posting_date": None,
                "match_type": result.match_type,
            }

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

        # Get total count (for progress tracking).
        # NOTE: a ["not in", ["", None]] filter compiles to SQL
        # `NOT IN ('', NULL)`, which - by SQL's three-valued logic - matches
        # NOTHING (any comparison against NULL yields UNKNOWN), so the count was
        # always 0. That silently broke the progress total (result["total_members"]),
        # so bulk runs reported 0 members to process. (The error-budget breaker is
        # derived from len(members) below, not this count, so it was unaffected.)
        # Use an explicit "is set" filter that mirrors the IS NOT NULL AND != ''
        # listing query below.
        total_count = frappe.db.count(
            "Member",
            filters={
                "mollie_customer_id": ["is", "set"],
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

    @staticmethod
    def _fetch_customer_with_rate_limit_retry(client, customer_id):
        """Fetch Mollie customer object, retrying once on HTTP 429 rate limit."""
        try:
            return client.customers.get(customer_id)
        except Exception as e:
            if hasattr(e, "status") and e.status == 429:
                retry_after = 60
                frappe.logger().warning(
                    f"Mollie rate limit (HTTP 429) hit for customer {customer_id}. "
                    f"Waiting {retry_after}s before retry..."
                )
                time.sleep(retry_after)
                try:
                    customer = client.customers.get(customer_id)
                    frappe.logger().info(f"Retry successful after rate limit wait for {customer_id}")
                    return customer
                except Exception as retry_error:
                    frappe.logger().error(f"Retry failed after rate limit wait: {retry_error}")
                    raise
            raise

    def _check_for_matching_invoice(
        self, payment, member_name, idempotency_check, payment_type, currency_warning, amount_value
    ):
        """Check for a matching unpaid dues invoice for intelligent processing. Returns invoice or None."""
        if not (
            payment.status == "paid"
            and payment_type == "dues"
            and not idempotency_check["already_processed"]
            and currency_warning is None
            and amount_value != "Unknown"
        ):
            return None

        try:
            invoice_check_date = payment.paid_at or payment.created_at
            payment_amount_float = extract_amount_float(payment.amount)
            return self.find_matching_unpaid_dues_invoice(
                member_name=member_name,
                payment_amount=payment_amount_float,
                payment_date=invoice_check_date,
            )
        except (ValueError, TypeError) as e:
            frappe.logger().warning(f"Could not check for matching invoice for payment {payment.id}: {e}")
            return None

    @staticmethod
    def _build_payment_info(
        payment, payment_type, idempotency_check, amount_value, currency, currency_warning, matching_invoice
    ):
        """Build the payment info dict for a single Mollie payment."""
        is_processable_dues = (
            payment.status == "paid" and payment_type == "dues" and not idempotency_check["already_processed"]
        )

        return {
            "id": payment.id,
            "status": payment.status,
            "amount": amount_value,
            "currency": currency,
            "amount_display": f"{currency} {amount_value}" if amount_value != "Unknown" else "Unknown",
            "description": payment.description,
            "created_at": str(payment.created_at),
            "paid_at": str(payment.paid_at) if payment.paid_at else None,
            "subscription_id": payment.subscription_id,
            "payment_type": payment_type,
            "already_processed": idempotency_check["already_processed"],
            "payment_entry": idempotency_check.get("payment_entry"),
            "bank_transaction": idempotency_check.get("bank_transaction"),
            "currency_warning": currency_warning,
            "processable": is_processable_dues and currency_warning is None,
            "matching_invoice": matching_invoice,
            "processing_mode": (
                ("bt_pe_reconcile" if matching_invoice else "bt_only") if is_processable_dues else None
            ),
        }

    @staticmethod
    def _filter_payment_by_date(payment, from_date):
        """Apply date filter to a payment. Returns True if payment should be EXCLUDED."""
        if not from_date:
            return False

        payment_date = payment.paid_at if payment.paid_at else payment.created_at
        if payment_date is None:
            frappe.logger().warning(f"Payment {payment.id} has no date, excluding from results")
            return True

        if payment_date.tzinfo is None:
            payment_date = payment_date.replace(tzinfo=timezone.utc)

        return payment_date < from_date

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
            Dict with customer_id, member, payments, total_found, new_payments, error.
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
            customer_obj = self._fetch_customer_with_rate_limit_retry(
                self.mollie_client.sdk_client, customer_id
            )

            sdk_payments = customer_obj.payments.list(limit=limit)
            result["total_found"] = len(sdk_payments)

            payments: List[MolliePayment] = []
            for sdk_payment in sdk_payments:
                try:
                    payments.append(MolliePayment.from_mollie_api(sdk_payment))
                except Exception as e:
                    frappe.logger().warning(
                        f"Could not convert payment {sdk_payment.get('id', 'unknown')} to typed object: {e}"
                    )

            if from_date and from_date.tzinfo is None:
                from_date = from_date.replace(tzinfo=timezone.utc)

            seen_payment_ids = set()
            filtered_by_date = 0
            filtered_by_duplicate = 0

            from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                get_bank_transaction_creator,
            )

            creator = get_bank_transaction_creator()

            for payment in payments:
                if self._filter_payment_by_date(payment, from_date):
                    filtered_by_date += 1
                    continue

                if payment.id in seen_payment_ids:
                    filtered_by_duplicate += 1
                    frappe.logger().warning(
                        f"Duplicate payment ID from Mollie API: {payment.id} for member {member_name}."
                    )
                    continue
                seen_payment_ids.add(payment.id)

                if len(seen_payment_ids) > 10000:
                    frappe.logger().error(
                        f"MEMORY LIMIT EXCEEDED: {len(seen_payment_ids)} unique payments "
                        f"for customer {customer_id} (Member: {member_name}). Stopping."
                    )
                    break

                idempotency_check = creator.check_already_processed(payment.id, check_payment_entry=True)
                payment_type = self.dues_processor.identify_payment_type(payment)
                amount_value = extract_amount_value(payment.amount)
                currency = extract_amount_currency(payment.amount)

                currency_warning = None
                if currency not in ("Unknown", "EUR"):
                    currency_warning = (
                        f"Non-EUR currency: {currency}. Exchange rate handling may be required."
                    )
                    frappe.logger().warning(
                        f"Payment {payment.id} uses {currency} instead of EUR. "
                        f"Member: {member_name}. Manual review may be needed."
                    )

                matching_invoice = self._check_for_matching_invoice(
                    payment, member_name, idempotency_check, payment_type, currency_warning, amount_value
                )

                payment_info = self._build_payment_info(
                    payment,
                    payment_type,
                    idempotency_check,
                    amount_value,
                    currency,
                    currency_warning,
                    matching_invoice,
                )

                result["payments"].append(payment_info)
                if payment_info["processable"]:
                    result["new_payments"] += 1

            result["filtered_by_date"] = filtered_by_date
            result["filtered_by_duplicate"] = filtered_by_duplicate

            # Validate counter accuracy
            expected = result["total_found"] - (filtered_by_date + filtered_by_duplicate)
            actual = len(result["payments"])
            if expected != actual:
                frappe.logger().error(
                    f"COUNTER MISMATCH for customer {customer_id} (Member: {member_name}): "
                    f"Expected {expected}, got {actual} after filtering."
                )

            frappe.logger().info(
                f"Customer {customer_id} (Member: {member_name}): "
                f"Found {result['total_found']} payments, {result['new_payments']} new/unprocessed"
                + (
                    f" (filtered: {filtered_by_date} by date, {filtered_by_duplicate} duplicates)"
                    if filtered_by_date or filtered_by_duplicate
                    else ""
                )
            )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(
                title="Bulk Payment Checker Error",
                message=f"Error checking payments for customer {customer_id} (Member: {member_name}): {e}",
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
            frappe.log_error(title="Bulk Payment Checker Error", message=f"Error in bulk payment check: {e}")

        return result

    def _log_bulk_operation_audit(
        self, result: Dict[str, Any], operation_type: str, days_back: int = None, all_history: bool = False
    ):
        """Log bulk payment operation to audit trail"""
        try:
            from verenigingen.utils.security.audit_logging import log_security_event

            # Lowercase to match the Select on API Audit Log.severity. These were "INFO"
            # and "WARNING", which the field rejects, so every audit row this method
            # produced was discarded by log_event's broad except -- the missing
            # compliance row in #197. log_event now normalises the case as a safety net,
            # but emitting a valid value here keeps the intent visible at the source.
            severity = "info"
            if result.get("circuit_breaker_triggered"):
                severity = "warning"
            elif result.get("errors", 0) > 0:
                severity = "warning"

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

            event_id = log_security_event(
                event_type="other",  # Use "other" instead of custom event types
                details={
                    **details,
                    "custom_event_type": f"bulk_payment_{operation_type}",  # Store actual type in details
                },
                severity=severity,
            )

            # log_security_event() -> log_event() cannot be trusted to report
            # failure: _store_audit_event/_store_api_audit_event/_log_to_file/
            # _check_alert_conditions (audit_logging.py) each catch and log
            # their OWN exceptions internally, so log_event's outer try never
            # sees a storage failure -- it always returns a normal-looking
            # event id even when the row was never written. event_type="other"
            # always routes here to API Audit Log (never SEPA Audit Log; see
            # SEPAAuditLogger.SEPA_EVENT_TYPES), so verify presence directly
            # instead of trusting the return value. See #197.
            if not event_id or not frappe.db.exists("API Audit Log", {"event_id": event_id}):
                raise RuntimeError(f"Audit event was not persisted to API Audit Log (event_id={event_id!r})")
        except Exception as e:
            # Don't fail bulk operation if audit logging fails, but alert admins
            frappe.logger().warning(f"Failed to log audit event: {e}")

            # CRITICAL: Log to Error Log for monitoring and alerting
            frappe.log_error(
                title="Audit Logging Failure - CRITICAL",
                message=f"Bulk payment {operation_type} completed but audit logging failed: {str(e)}\n\n"
                f"Operation details: {details}",
            )

            # Increment failure counter for monitoring dashboard. cache().get()
            # returns bytes for a value set by a previous call (cache().set()
            # stores via raw redis, not frappe's get_value/set_value), so
            # cint() is required -- a bare `bytes + 1` raises TypeError. This
            # whole block was unreachable before the fix above, so neither bug
            # had ever run; wrapped in its own try/except so a Redis outage
            # here (raw cache calls, no ConnectionError suppression) cannot
            # turn "don't fail the bulk operation" into a failing one.
            try:
                cache_key = "audit_log_failures_count"
                failures = cint(frappe.cache().get(cache_key))
                frappe.cache().set(cache_key, failures + 1, ex=3600)  # 1 hour window
            except Exception as cache_error:
                frappe.logger().warning(f"Failed to bump audit failure counter: {cache_error}")

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

    @staticmethod
    def _extract_payment_ids_from_transactions(transactions, from_date, to_date):
        """Extract payment IDs and transaction info from balance transactions within date range.

        Returns:
            Tuple of (payment_ids_found: set, transaction_list: list of dicts)
        """
        payment_ids_found = set()
        transaction_list = []

        for tx in transactions:
            context = getattr(tx, "context", {})
            payment_id = None
            if isinstance(context, dict):
                payment_id = context.get("paymentId") or context.get("payment_id")

            if not payment_id:
                tx_id = getattr(tx, "id", "")
                if tx_id.startswith("tr_"):
                    payment_id = tx_id

            tx_created = getattr(tx, "created_at", None)
            if not tx_created:
                continue

            try:
                if isinstance(tx_created, str):
                    tx_date = datetime.fromisoformat(tx_created.replace("Z", "+00:00"))
                else:
                    tx_date = tx_created

                if tx_date.tzinfo is None:
                    tx_date = tx_date.replace(tzinfo=timezone.utc)

                if from_date <= tx_date <= to_date and payment_id and payment_id.startswith("tr_"):
                    payment_ids_found.add(payment_id)
                    transaction_list.append(
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

        return payment_ids_found, transaction_list

    @staticmethod
    def _batch_check_already_processed(payment_ids_list):
        """Batch check payment IDs against Payment Entries and Bank Transactions.

        Returns:
            List of unprocessed payment IDs.
        """
        if not payment_ids_list:
            return []

        placeholders = ", ".join(["%s"] * len(payment_ids_list))
        params = tuple(payment_ids_list)

        pe_results = frappe.db.sql(
            f"""
            SELECT reference_no FROM `tabPayment Entry`
            WHERE reference_no IN ({placeholders}) AND docstatus != 2
            """,
            params,
            as_dict=True,
        )
        existing_pe = {pe["reference_no"] for pe in pe_results}

        bt_results = frappe.db.sql(
            f"""
            SELECT reference_number FROM `tabBank Transaction`
            WHERE reference_number IN ({placeholders}) AND docstatus != 2
            """,
            params,
            as_dict=True,
        )
        existing_bt = {bt["reference_number"] for bt in bt_results}

        frappe.logger().info(
            f"Batch check found {len(existing_pe)} Payment Entries, {len(existing_bt)} Bank Transactions"
        )

        return [pid for pid in payment_ids_list if pid not in existing_pe and pid not in existing_bt]

    @staticmethod
    def _classify_orphaned_payment(payment, payment_id, payment_type, currency, amount):
        """Classify an unmatched payment as an orphaned transaction.

        Returns:
            Tuple of (orphan_info dict, is_processable bool)
        """
        mollie_customer_id = getattr(payment, "customer_id", None)
        is_processable = payment.status == "paid" and currency == "EUR"

        if is_processable:
            if mollie_customer_id:
                processing_mode = "bt_only_orphaned"
                reason = "Cannot match to any member (has Mollie customer)"
            else:
                processing_mode = "bt_only_anonymous"
                reason = "Anonymous payment (no member, no Mollie customer)"
        else:
            processing_mode = None
            reason = "Cannot match to any member or donor"

        orphan_info = {
            "payment_id": payment_id,
            "status": payment.status,
            "amount": f"{currency} {amount}",
            "amount_value": amount,
            "currency": currency,
            "description": getattr(payment, "description", "No description"),
            "customer_id": mollie_customer_id or "No customer",
            "subscription_id": getattr(payment, "subscription_id", None),
            "payment_type": payment_type,
            "paid_at": str(getattr(payment, "paid_at", None)),
            "created_at": str(getattr(payment, "created_at", None)),
            "reason": reason,
            "processable": is_processable,
            "processing_mode": processing_mode,
        }

        return orphan_info, is_processable

    def _check_via_balance_transactions(self, days_back: int = 10, date_offset: int = 0) -> Dict[str, Any]:
        """
        Balance transaction-based payment checking (systematic approach).

        Retrieves balance transactions from Mollie Balance API and extracts payments.
        More systematic than customer-by-customer iteration.

        Args:
            days_back: Number of days back to check (default: 10)
            date_offset: Start lookback N days ago (e.g., 30 = check days 30-40 ago if days_back=10)

        Returns:
            Dict with retrieval_mode, total_payments_found, total_new_payments, etc.
        """
        result = {
            "retrieval_mode": "balance_transactions",
            "total_payments_found": 0,
            "total_new_payments": 0,
            "balance_transactions": [],
            "orphaned_transactions": [],
            "errors": 0,
            "error_details": [],
            "circuit_breaker_triggered": False,
            "started_at": frappe.utils.now(),
            "completed_at": None,
            "summary": "",
        }

        try:
            from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

            balance_client = BalancesClient()

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

            primary_balance = balance_client.get_primary_balance()
            if not primary_balance:
                result["error"] = "No primary balance found"
                return result

            frappe.logger().info(f"Using primary balance: {primary_balance.id}")

            transactions = balance_client.list_balance_transactions(balance_id=primary_balance.id, limit=250)
            frappe.logger().info(f"Retrieved {len(transactions)} balance transactions")

            payment_ids_found, transaction_list = self._extract_payment_ids_from_transactions(
                transactions, from_date, to_date
            )
            result["balance_transactions"] = transaction_list
            result["total_payments_found"] = len(payment_ids_found)
            frappe.logger().info(f"Found {len(payment_ids_found)} unique payment IDs in date range")

            unprocessed_payment_ids = self._batch_check_already_processed(list(payment_ids_found))
            frappe.logger().info(
                f"After batch idempotency check: {len(unprocessed_payment_ids)} unprocessed "
                f"out of {len(payment_ids_found)} total"
            )

            for payment_id in unprocessed_payment_ids:
                try:
                    payment = self.mollie_client.sdk_client.payments.get(payment_id)
                    payment_type = self.dues_processor.identify_payment_type(payment)
                    member_name = self.dues_processor.find_member_for_payment(payment)

                    currency = payment.amount["currency"] if payment.amount else "Unknown"
                    amount = payment.amount["value"] if payment.amount else "Unknown"

                    if not member_name:
                        orphan_info, is_processable = self._classify_orphaned_payment(
                            payment, payment_id, payment_type, currency, amount
                        )
                        result["orphaned_transactions"].append(orphan_info)
                        if is_processable:
                            result["total_new_payments"] += 1
                        frappe.logger().warning(
                            f"Orphaned payment {payment_id}: {currency} {amount}, "
                            f"type: {payment_type}, processable: {is_processable}"
                        )
                    else:
                        if payment.status == "paid" and payment_type == "dues" and currency == "EUR":
                            result["total_new_payments"] += 1

                    time.sleep(0.1)

                except Exception as e:
                    result["errors"] += 1
                    result["error_details"].append(
                        {"payment_id": payment_id, "error": str(e), "step": "payment_detail_fetch"}
                    )
                    frappe.logger().warning(f"Error checking payment {payment_id}: {e}")

            result["completed_at"] = frappe.utils.now()

            orphaned_count = len(result["orphaned_transactions"])
            processable_orphaned = sum(1 for o in result["orphaned_transactions"] if o.get("processable"))
            result["processable_orphaned_count"] = processable_orphaned

            result["summary"] = (
                f"Checked {result['total_payments_found']} payments from balance transactions "
                f"(last {days_back} days). Found {result['total_new_payments']} new/unprocessed. "
                f"Orphaned (no member match): {orphaned_count} ({processable_orphaned} processable). "
                f"Errors: {result['errors']}"
            )

            if orphaned_count > 0:
                frappe.logger().warning(
                    f"{orphaned_count} orphaned payments found ({processable_orphaned} processable for BT-only import)"
                )

            frappe.logger().info(f"Balance transaction check complete: {result['summary']}")

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(
                title="Bulk Payment Checker Error", message=f"Error in balance transaction check: {e}"
            )

        return result
