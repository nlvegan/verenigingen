"""
Mollie Subscription Recreation Tool
Administrative interface for recreating broken subscriptions from CSV upload
"""

import base64
import csv
import io
import json
import time
from datetime import datetime
from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.mollie_debug_service import MollieDebugService
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    SecurityLevel,
    api_security_framework,
    high_security_api,
)


def get_context(context):
    """Get context for Mollie subscription recreation page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Check permissions - only administrators
    if not has_admin_access():
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Mollie Subscription Recreation")

    # Ensure CSRF token is available
    from frappe.sessions import get_csrf_token

    context.csrf_token = get_csrf_token()

    # Get Mollie settings info
    try:
        mollie_settings = frappe.get_single("Mollie Settings")
        context.mollie_configured = bool(mollie_settings.test_secret_key or mollie_settings.live_secret_key)
        context.test_mode = mollie_settings.test_mode
        context.api_key_type = "test" if mollie_settings.test_mode else "live"
    except Exception:
        context.mollie_configured = False
        context.test_mode = True
        context.api_key_type = "unknown"

    return context


def has_admin_access():
    """Check if current user has access to subscription recreation tool"""
    # Match mollie_payments_debug permissions for consistency
    allowed_roles = [
        "System Manager",
        "Administrator",
        "Verenigingen Administrator",
        "Verenigingen Staff",
        "Treasurer",
    ]
    user_roles = frappe.get_roles(frappe.session.user)
    return any(role in allowed_roles for role in user_roles)


def poll_subscription_cancellation(
    service: MollieDebugService,
    customer_id: str,
    subscription_id: str,
    max_attempts: int = 10,
    delay: float = 0.5,
) -> bool:
    """
    Poll Mollie API to verify subscription cancellation.

    Args:
        service: MollieDebugService instance
        customer_id: Mollie customer ID
        subscription_id: Mollie subscription ID
        max_attempts: Maximum number of polling attempts (default 10)
        delay: Delay between attempts in seconds (default 0.5)

    Returns:
        bool: True if subscription is cancelled, False if still active after max attempts
    """
    for attempt in range(max_attempts):
        try:
            result = service.debug_subscription(subscription_id, customer_id)

            if result.get("error"):
                # If subscription not found, it's been deleted/cancelled
                if "not found" in str(result.get("error")).lower():
                    return True
                # Other errors, wait and retry
                time.sleep(delay)
                continue

            subscription_data = result.get("subscription_data", {})
            status = subscription_data.get("status")

            # Check if cancelled
            if status in ["cancelled", "canceled"]:
                return True

            # Still active, wait and retry
            time.sleep(delay)

        except Exception as e:
            frappe.log_error(f"Error polling subscription status: {str(e)}")
            time.sleep(delay)

    # Max attempts reached without confirmation
    return False


def parse_amount_string(amount_str) -> float:
    """
    Parse amount from various Mollie API formats.

    Args:
        amount_str: Amount in various formats ("25.00 EUR", "25.00", 25.00, None)

    Returns:
        float: Parsed amount, 0.0 if parsing fails
    """
    if amount_str is None:
        return 0.0

    try:
        if isinstance(amount_str, str):
            # Handle "25.00 EUR" format
            return float(amount_str.split()[0])
        return float(amount_str)
    except (ValueError, IndexError, AttributeError):
        return 0.0


def sanitize_description(description: Optional[str]) -> str:
    """
    Sanitize description field, providing default if None or empty.

    Args:
        description: Description from Mollie API (may be None)

    Returns:
        str: Sanitized description, never None or empty
    """
    if not description or not description.strip():
        return "Membership dues"
    return description.strip()


def generate_unique_description(base_description: str, custom_suffix: str = "") -> str:
    """
    Generate unique description with custom suffix or UTC timestamp.

    Args:
        base_description: Original subscription description
        custom_suffix: Optional custom suffix (uses timestamp if empty)

    Returns:
        str: Description with suffix for uniqueness
    """
    if custom_suffix:
        return f"{base_description} ({custom_suffix})"

    # Default to timestamp if no custom suffix provided
    timestamp = frappe.utils.now()
    return f"{base_description} (updated {timestamp})"


def retry_api_call(func, max_attempts: int = 3, backoff_factor: float = 2.0):
    """
    Retry API call with exponential backoff.

    Args:
        func: Callable to retry
        max_attempts: Maximum retry attempts
        backoff_factor: Exponential backoff multiplier

    Returns:
        Result of func() if successful

    Raises:
        Last exception if all attempts fail
    """
    last_exception = None

    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_attempts - 1:
                sleep_time = backoff_factor**attempt
                frappe.logger().warning(
                    f"API call failed (attempt {attempt + 1}/{max_attempts}): {str(e)}. "
                    f"Retrying in {sleep_time}s..."
                )
                time.sleep(sleep_time)

    # All attempts failed
    raise last_exception


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def parse_and_validate_csv(
    csv_content: str, planned_next_invoice_date: str, skip_date_validation: bool = False
) -> Dict:
    """
    Parse CSV file and validate subscription data against Mollie API.

    Expected CSV format:
    customer_id,subscription_id[,amount]
    cst_xxx,sub_yyy[,25.00]

    The 'amount' column is optional. If provided, the new subscription will use that amount.
    If not provided, the current subscription amount will be preserved.

    Returns validation results with current vs planned comparison.
    """
    try:
        if not has_admin_access():
            frappe.throw(_("Access denied - Verenigingen Administrator role required"))

        # Parse CSV
        rows = []
        reader = csv.DictReader(io.StringIO(csv_content))

        # Validate CSV has required columns
        if not reader.fieldnames or not all(
            col in reader.fieldnames for col in ["customer_id", "subscription_id"]
        ):
            return {
                "error": "Invalid CSV format. Required columns: customer_id, subscription_id (optional: amount)",
                "status": "error",
            }

        # Check if amount column is present
        has_amount_column = "amount" in reader.fieldnames

        for row in reader:
            if row.get("customer_id") and row.get("subscription_id"):
                row_data = {
                    "customer_id": row["customer_id"].strip(),
                    "subscription_id": row["subscription_id"].strip(),
                }

                # Parse optional amount column if present
                if has_amount_column and row.get("amount"):
                    try:
                        custom_amount = float(row["amount"].strip())
                        if custom_amount > 0:
                            row_data["custom_amount"] = custom_amount
                    except (ValueError, AttributeError):
                        pass  # Ignore invalid amounts, will use current amount

                rows.append(row_data)

        if not rows:
            return {"error": "No valid rows found in CSV", "status": "error"}

        # Validate planned date format
        try:
            datetime.strptime(planned_next_invoice_date, "%Y-%m-%d").date()
        except ValueError:
            return {
                "error": "Invalid date format. Use YYYY-MM-DD format.",
                "status": "error",
            }

        # Fetch current subscription data from Mollie
        service = MollieDebugService()
        validation_results = []

        for row in rows:
            result = service.debug_subscription(row["subscription_id"], row["customer_id"])

            if "error" in result and result["error"]:
                validation_results.append(
                    {
                        "customer_id": row["customer_id"],
                        "subscription_id": row["subscription_id"],
                        "status": "error",
                        "error": result["error"],
                        "current_amount": None,
                        "current_next_invoice_date": None,
                        "planned_amount": None,
                        "planned_next_invoice_date": planned_next_invoice_date,
                    }
                )
                continue

            # Extract current subscription details
            subscription = result.get("subscription_data", {})

            # Parse subscription data using helper functions
            current_amount = parse_amount_string(subscription.get("amount"))
            current_next_date = subscription.get("next_payment_date")
            current_status = subscription.get("status")
            current_interval = subscription.get("interval")
            current_description = sanitize_description(subscription.get("description"))

            # Determine planned amount: use custom amount if provided, otherwise current amount
            planned_amount = row.get("custom_amount", current_amount)
            amount_changed = "custom_amount" in row and row["custom_amount"] != current_amount

            # Validation checks
            status = "valid"
            warnings = []

            # Check if current next invoice date is in the past (unless validation skipped)
            if not skip_date_validation and current_next_date:
                current_date_obj = datetime.strptime(current_next_date, "%Y-%m-%d").date()
                if current_date_obj >= datetime.now().date():
                    warnings.append("Current next invoice date is NOT in the past")
                    status = "warning"

            # Check subscription status
            if current_status not in ["active", "suspended"]:
                warnings.append(f"Subscription status is {current_status}")
                status = "warning"

            validation_results.append(
                {
                    "customer_id": row["customer_id"],
                    "subscription_id": row["subscription_id"],
                    "status": status,
                    "warnings": warnings,
                    "current_amount": current_amount,
                    "current_next_invoice_date": current_next_date,
                    "current_status": current_status,
                    "current_interval": current_interval,
                    "current_description": current_description,
                    "planned_amount": planned_amount,
                    "planned_next_invoice_date": planned_next_invoice_date,
                    "amount_match": not amount_changed,
                    "amount_changed": amount_changed,
                }
            )

        return {"status": "success", "results": validation_results, "total_rows": len(validation_results)}

    except Exception as e:
        return {"error": str(e), "status": "error"}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def recreate_subscriptions(subscriptions_data: str, description_suffix: str = "") -> Dict:
    """
    Recreate subscriptions with new next invoice dates.

    Args:
        subscriptions_data: Base64-encoded JSON string of validated subscriptions to recreate
        description_suffix: Optional custom suffix to append to descriptions (defaults to timestamp if empty)
    """
    try:
        if not has_admin_access():
            frappe.throw(_("Access denied - Verenigingen Administrator role required"))

        # Decode base64-encoded JSON payload
        if not subscriptions_data:
            return {"error": "Subscriptions data is required", "status": "error"}

        try:
            decoded_data = base64.b64decode(subscriptions_data).decode("utf-8")
        except Exception as e:
            return {"error": f"Failed to decode data: {str(e)}", "status": "error"}

        if len(decoded_data) > 100000:  # 100KB limit
            return {"error": "Subscriptions data too large", "status": "error"}

        subscriptions = json.loads(decoded_data)

        service = MollieDebugService()
        results = []

        for sub_data in subscriptions:
            customer_id = sub_data["customer_id"]
            old_subscription_id = sub_data["subscription_id"]
            amount = sub_data["planned_amount"]
            start_date = sub_data["planned_next_invoice_date"]
            interval = sub_data.get("current_interval")
            description = sanitize_description(sub_data.get("current_description"))

            if not interval:
                results.append(
                    {
                        "customer_id": customer_id,
                        "old_subscription_id": old_subscription_id,
                        "status": "error",
                        "error": "Missing interval data - cannot recreate subscription",
                        "details": "The subscription data does not include interval information. This is required to recreate the subscription.",
                    }
                )
                continue

            # Cancel old subscription with retry logic
            try:

                def cancel_operation():
                    result = service.admin_cancel_subscription(
                        customer_id, old_subscription_id, reason="Recreating with updated invoice date"
                    )
                    if result.get("error"):
                        raise RuntimeError(result["error"])
                    return result

                retry_api_call(cancel_operation, max_attempts=3)

            except Exception as e:
                results.append(
                    {
                        "customer_id": customer_id,
                        "old_subscription_id": old_subscription_id,
                        "status": "error",
                        "error": f"Failed to cancel old subscription: {str(e)}",
                        "details": "The old subscription could not be cancelled. No changes were made.",
                    }
                )
                continue

            # Poll Mollie API to confirm cancellation before proceeding
            cancellation_confirmed = poll_subscription_cancellation(
                service, customer_id, old_subscription_id, max_attempts=10, delay=0.5
            )

            if not cancellation_confirmed:
                results.append(
                    {
                        "customer_id": customer_id,
                        "old_subscription_id": old_subscription_id,
                        "status": "error",
                        "error": "Cancellation timeout - subscription may still be active",
                        "details": "The Mollie API did not confirm cancellation within the expected timeframe. Please verify the subscription status manually before proceeding.",
                    }
                )
                continue

            # Create new subscription with unique description
            unique_description = generate_unique_description(description, description_suffix)

            try:

                def create_operation():
                    result = service.create_subscription(
                        customer_id=customer_id,
                        amount=amount,
                        interval=interval,
                        description=unique_description,
                        mandate_id=None,  # Will use customer's default mandate
                        start_date=start_date,
                    )
                    if result.get("error"):
                        raise RuntimeError(result["error"])
                    return result

                create_result = retry_api_call(create_operation, max_attempts=3)

                new_subscription_id = create_result.get("subscription_id")

                results.append(
                    {
                        "customer_id": customer_id,
                        "old_subscription_id": old_subscription_id,
                        "new_subscription_id": new_subscription_id,
                        "status": "success",
                        "interval": interval,
                        "amount": amount,
                        "next_invoice_date": start_date,
                        "description": unique_description,
                    }
                )

            except Exception as e:
                results.append(
                    {
                        "customer_id": customer_id,
                        "old_subscription_id": old_subscription_id,
                        "status": "error",
                        "error": f"Failed to create new subscription: {str(e)}",
                        "details": "The old subscription was cancelled but the new subscription could not be created. You can manually create a new subscription for this customer.",
                    }
                )

        success_count = sum(1 for r in results if r["status"] == "success")
        error_count = sum(1 for r in results if r["status"] == "error")

        return {
            "status": "completed",
            "results": results,
            "summary": {
                "total": len(results),
                "success": success_count,
                "errors": error_count,
            },
        }

    except Exception as e:
        frappe.log_error(f"Subscription recreation error: {str(e)}")
        return {"error": str(e), "status": "error"}
