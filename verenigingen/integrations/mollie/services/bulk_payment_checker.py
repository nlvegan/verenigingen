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

from verenigingen.integrations.mollie.core.mollie_client import MollieClient
from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor


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

        # Enforce maximum limit
        if limit > BulkPaymentCheckerConfig.MAX_MEMBERS_PER_RUN:
            limit = BulkPaymentCheckerConfig.MAX_MEMBERS_PER_RUN

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

            # Get all payments for this customer
            payments = customer_obj.payments.list(limit=limit)
            result["total_found"] = len(payments)

            # Filter by date if requested
            if from_date:
                # Ensure from_date is timezone-aware
                if from_date.tzinfo is None:
                    from_date = from_date.replace(tzinfo=timezone.utc)

            for payment in payments:
                # Apply date filter
                # CRITICAL: Use paid_at for financial reconciliation (when money actually moved)
                # Fall back to created_at only for pending/unpaid payments
                if from_date:
                    try:
                        # Use paid_at (when payment completed) for accurate financial reconciliation
                        payment_date = getattr(payment, "paid_at", None)

                        # Fallback to created_at if paid_at is None (pending/failed payments)
                        if payment_date is None:
                            payment_date = payment.created_at
                            frappe.logger().debug(
                                f"Payment {payment.id} has no paid_at, using created_at (status: {payment.status})"
                            )

                        # Make payment_date timezone-aware if needed
                        if payment_date.tzinfo is None:
                            payment_date = payment_date.replace(tzinfo=timezone.utc)

                        if payment_date < from_date:
                            continue
                    except (AttributeError, TypeError):
                        frappe.logger().warning(
                            f"Could not parse payment date for {payment.id}, skipping date filter"
                        )

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

                # Extract and validate currency
                amount_value = payment.amount["value"] if payment.amount else "Unknown"
                currency = payment.amount["currency"] if payment.amount else "Unknown"

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

                payment_info = {
                    "id": payment.id,
                    "status": payment.status,
                    "amount": amount_value,
                    "currency": currency,
                    "amount_display": (
                        f"{currency} {amount_value}" if amount_value != "Unknown" else "Unknown"
                    ),
                    "description": getattr(payment, "description", ""),
                    "created_at": str(payment.created_at),
                    "paid_at": (
                        str(getattr(payment, "paid_at", None)) if getattr(payment, "paid_at", None) else None
                    ),
                    "subscription_id": getattr(payment, "subscription_id", None),
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
                }

                result["payments"].append(payment_info)

                # Count new unprocessed payments
                if payment_info["processable"]:
                    result["new_payments"] += 1

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
            return self._check_via_balance_transactions(days_back=days_back)
        else:
            return self._check_via_customers(
                days_back=days_back,
                all_history=all_history,
                limit_per_customer=limit_per_customer,
                max_members=max_members,
            )

    def _check_via_customers(
        self,
        days_back: int = 7,
        all_history: bool = False,
        limit_per_customer: int = 250,
        max_members: Optional[int] = None,
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
            "circuit_breaker_triggered": False,
            "started_at": frappe.utils.now(),
            "completed_at": None,
            "summary": "",
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

            # Calculate date filter
            from_date = None
            if not all_history:
                from_date = datetime.now(timezone.utc) - timedelta(days=days_back)
                frappe.logger().info(f"Checking payments from {from_date.strftime('%Y-%m-%d')} onwards")
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

                if customer_result["error"]:
                    result["errors"] += 1
                    consecutive_errors += 1

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
                category="financial",
                event_type=f"bulk_payment_{operation_type}",
                details=details,
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
                reference_doctype="Bulk Payment Checker",
                reference_name=f"audit_failure_{operation_type}",
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

    def _check_via_balance_transactions(self, days_back: int = 10) -> Dict[str, Any]:
        """
        Balance transaction-based payment checking (systematic approach).

        Retrieves balance transactions from Mollie Balance API and extracts payments.
        This is more systematic than customer-by-customer iteration.

        Args:
            days_back: Number of days back to check (default: 10, fixed for this mode)

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
            "circuit_breaker_triggered": False,
            "started_at": frappe.utils.now(),
            "completed_at": None,
            "summary": "",
        }

        try:
            # Import balance client
            from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient

            balance_client = BalancesClient()

            # Calculate date range (fixed 10 days for this mode)
            from_date = datetime.now(timezone.utc) - timedelta(days=days_back)
            to_date = datetime.now(timezone.utc)

            frappe.logger().info(
                f"Checking balance transactions from {from_date.strftime('%Y-%m-%d')} "
                f"to {to_date.strftime('%Y-%m-%d')}"
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

            # Now check each payment for processing status and member matching
            new_payments = []

            for payment_id in payment_ids_found:
                try:
                    # Check idempotency
                    from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                        get_bank_transaction_creator,
                    )

                    creator = get_bank_transaction_creator()
                    idempotency_check = creator.check_already_processed(
                        payment_id,
                        check_payment_entry=True,
                    )

                    if not idempotency_check["already_processed"]:
                        # Fetch payment details from Mollie
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
                            # Remove from regular transactions, add to orphaned
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
                                new_payments.append(payment_id)
                                result["total_new_payments"] += 1

                    # Small delay to respect rate limits
                    time.sleep(BulkPaymentCheckerConfig.API_CALL_DELAY_MS / 1000)

                except Exception as e:
                    result["errors"] += 1
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
