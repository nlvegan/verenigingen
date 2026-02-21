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
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    SecurityLevel,
    api_security_framework,
    high_security_api,
)

# Configuration constants
MAX_CSV_SIZE = 1024 * 1024  # 1MB limit for CSV uploads
MAX_CSV_ROWS = 1000  # Maximum rows to process
MAX_SUBSCRIPTIONS_PAYLOAD_SIZE = 100 * 1024  # 100KB for base64 payload
CANCELLATION_POLL_MAX_ATTEMPTS = 20  # Increased from 10 for reliability
CANCELLATION_POLL_INITIAL_DELAY = 0.3  # Initial delay in seconds
CANCELLATION_POLL_MAX_DELAY = 3.0  # Maximum delay for exponential backoff


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
        Roles.SYSTEM_MANAGER,
        "Administrator",
        Roles.VERENIGINGEN_ADMIN,
        Roles.VERENIGINGEN_STAFF,
        "Treasurer",
    ]
    user_roles = frappe.get_roles(frappe.session.user)
    return any(role in allowed_roles for role in user_roles)


def poll_subscription_cancellation(
    service: MollieDebugService,
    customer_id: str,
    subscription_id: str,
    max_attempts: int = CANCELLATION_POLL_MAX_ATTEMPTS,
    initial_delay: float = CANCELLATION_POLL_INITIAL_DELAY,
) -> bool:
    """
    Poll Mollie API to verify subscription cancellation with exponential backoff.

    Args:
        service: MollieDebugService instance
        customer_id: Mollie customer ID
        subscription_id: Mollie subscription ID
        max_attempts: Maximum number of polling attempts
        initial_delay: Initial delay in seconds before exponential backoff

    Returns:
        bool: True if subscription is cancelled, False if still active after max attempts
    """
    delay = initial_delay

    for attempt in range(max_attempts):
        try:
            result = service.debug_subscription(subscription_id, customer_id)

            if result.get("error"):
                # If subscription not found, it's been deleted/cancelled
                if "not found" in str(result.get("error")).lower():
                    frappe.logger().info(f"Subscription {subscription_id} confirmed cancelled (not found)")
                    return True
                # Other errors, wait and retry with exponential backoff
                time.sleep(delay)
                delay = min(delay * 1.5, CANCELLATION_POLL_MAX_DELAY)
                continue

            subscription_data = result.get("subscription_data", {})
            status = subscription_data.get("status")

            # Check if cancelled
            if status in ["cancelled", "canceled"]:
                frappe.logger().info(f"Subscription {subscription_id} confirmed cancelled (status: {status})")
                return True

            # Still active, wait and retry with exponential backoff
            time.sleep(delay)
            delay = min(delay * 1.5, CANCELLATION_POLL_MAX_DELAY)

        except Exception as e:
            frappe.log_error(f"Error polling subscription status: {str(e)}")
            time.sleep(delay)
            delay = min(delay * 1.5, CANCELLATION_POLL_MAX_DELAY)

    # Max attempts reached without confirmation
    frappe.logger().warning(
        f"Subscription {subscription_id} cancellation not confirmed after {max_attempts} attempts"
    )
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


def sanitize_csv_field(value: str) -> str:
    """
    Sanitize CSV field to prevent CSV injection attacks.

    Args:
        value: Field value to sanitize

    Returns:
        str: Sanitized value safe for CSV output
    """
    if not value:
        return value

    value_str = str(value)

    # Prevent CSV injection by escaping formula indicators
    dangerous_chars = ("=", "+", "-", "@", "\t", "\r")
    if value_str.startswith(dangerous_chars):
        return "'" + value_str  # Prefix with single quote to force text interpretation

    return value_str


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
    csv_content: str, planned_next_invoice_date: str = "", skip_date_validation: bool = False
) -> Dict:
    """
    Parse CSV file and validate subscription data against Mollie API.

    Expected CSV format:
    customer_id,subscription_id[,amount][,description][,next_payment_date]
    cst_xxx,sub_yyy[,25.00][,New description][,2026-01-01]

    Optional columns:
    - amount: Override subscription amount
    - description: Override subscription description
    - next_payment_date: Override next invoice date (takes precedence over global planned_next_invoice_date)

    Args:
        csv_content: CSV file content
        planned_next_invoice_date: Global next invoice date (optional if dates in CSV)
        skip_date_validation: Skip validation that current date is overdue

    Returns validation results with current vs planned comparison.
    """
    try:
        if not has_admin_access():
            frappe.throw(_("Access denied - Verenigingen Administrator role required"))

        # Validate CSV size to prevent DoS
        if len(csv_content) > MAX_CSV_SIZE:
            return {
                "status": "error",
                "error": f"CSV file too large. Maximum size: {MAX_CSV_SIZE / 1024:.0f}KB",
            }

        # Parse CSV
        rows = []
        reader = csv.DictReader(io.StringIO(csv_content))

        # Validate CSV has required columns
        if not reader.fieldnames or not all(
            col in reader.fieldnames for col in ["customer_id", "subscription_id"]
        ):
            return {
                "error": "Invalid CSV format. Required columns: customer_id, subscription_id (optional: amount, description, next_payment_date)",
                "status": "error",
            }

        # Check which optional columns are present
        has_amount_column = "amount" in reader.fieldnames
        has_description_column = "description" in reader.fieldnames
        has_date_column = "next_payment_date" in reader.fieldnames

        # Convert to list and validate row count
        all_rows = list(reader)
        if len(all_rows) > MAX_CSV_ROWS:
            return {"status": "error", "error": f"Too many rows. Maximum: {MAX_CSV_ROWS}"}

        for row in all_rows:
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

                # Parse optional description column if present
                if has_description_column and row.get("description"):
                    description = row["description"].strip()
                    if description:
                        row_data["custom_description"] = description

                # Parse optional next_payment_date column if present
                if has_date_column and row.get("next_payment_date"):
                    date_str = row["next_payment_date"].strip()
                    if date_str:
                        try:
                            # Validate date format
                            datetime.strptime(date_str, "%Y-%m-%d").date()
                            row_data["custom_next_payment_date"] = date_str
                        except ValueError:
                            pass  # Ignore invalid dates, will use global or current

                rows.append(row_data)

        if not rows:
            return {"error": "No valid rows found in CSV", "status": "error"}

        # Normalize empty string to None
        if planned_next_invoice_date == "":
            planned_next_invoice_date = None

        # Validate global planned date format if provided
        if planned_next_invoice_date:
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
            current_mandate_id = subscription.get("mandate_id")

            # Determine planned values: use CSV overrides if provided, otherwise current values
            # Amount is always preserved from current subscription (ignore CSV amount column)
            planned_amount = current_amount
            amount_changed = False

            planned_description = row.get("custom_description", current_description)
            description_changed = (
                "custom_description" in row and row["custom_description"] != current_description
            )

            # Determine planned date: Global date > CSV date > current date
            planned_date = (
                planned_next_invoice_date or row.get("custom_next_payment_date") or current_next_date
            )
            date_changed = planned_date != current_next_date

            # Validate mandate - check if customer has valid mandate
            mandate_status = None
            mandate_valid = False

            if current_mandate_id:
                mandate_result = service.debug_mandate(current_mandate_id, row["customer_id"])
                if not mandate_result.get("error"):
                    mandate_data = mandate_result.get("mandate_data", {})
                    mandate_status = mandate_data.get("status")
                    mandate_valid = mandate_status == "valid"

            # Validation checks
            status = "valid"
            warnings = []
            errors = []

            # Check mandate validity (skip warning if mandate_id is null - we'll fetch it during recreation)
            if current_mandate_id and not mandate_valid:
                warnings.append(f"Mandate status is {mandate_status or 'unknown'} (not valid)")
                status = "warning"

            # Check if current next invoice date is in the past (only if date is changing and validation not skipped)
            if not skip_date_validation and date_changed and current_next_date:
                current_date_obj = datetime.strptime(current_next_date, "%Y-%m-%d").date()
                if current_date_obj >= datetime.now().date():
                    warnings.append("Current next invoice date is NOT in the past")
                    status = "warning"

            # Check subscription status - block non-active/suspended subscriptions
            if current_status not in ["active", "suspended"]:
                errors.append(f"Cannot recreate {current_status} subscription")
                status = "error"

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
                    "current_mandate_id": current_mandate_id,
                    "mandate_status": mandate_status,
                    "mandate_valid": mandate_valid,
                    "planned_amount": planned_amount,
                    "planned_next_invoice_date": planned_date,
                    "planned_description": planned_description,
                    "amount_match": not amount_changed,
                    "amount_changed": amount_changed,
                    "description_changed": description_changed,
                    "date_changed": date_changed,
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

        # Validate encoded size first (base64 is ~133% of original)
        max_encoded_size = int(MAX_SUBSCRIPTIONS_PAYLOAD_SIZE * 1.4)
        if len(subscriptions_data) > max_encoded_size:
            return {"error": "Request payload too large", "status": "error"}

        try:
            decoded_data = base64.b64decode(subscriptions_data).decode("utf-8")
        except Exception as e:
            return {"error": f"Failed to decode data: {str(e)}", "status": "error"}

        if len(decoded_data) > MAX_SUBSCRIPTIONS_PAYLOAD_SIZE:
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
            # Use planned description (which includes CSV override if provided)
            description = sanitize_description(
                sub_data.get("planned_description") or sub_data.get("current_description")
            )
            description_changed = sub_data.get("description_changed", False)
            mandate_id = sub_data.get("current_mandate_id")
            mandate_valid = sub_data.get("mandate_valid", False)

            # Check for required data
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

            # If mandate_id is missing from subscription data, fetch customer's valid mandate
            if not mandate_id or not mandate_valid:
                # Fetch customer's mandates to find a valid one
                customer_data = service.debug_customer(customer_id)
                if not customer_data.get("error"):
                    mandates = customer_data.get("mandates", [])
                    # Find first valid mandate
                    for m in mandates:
                        if m.get("status") == "valid":
                            mandate_id = m.get("id")
                            mandate_valid = True
                            frappe.logger().info(
                                f"Using valid mandate {mandate_id} for customer {customer_id}"
                            )
                            break

            # Validate mandate before proceeding
            if not mandate_id:
                results.append(
                    {
                        "customer_id": customer_id,
                        "old_subscription_id": old_subscription_id,
                        "status": "error",
                        "error": "No valid mandate found - cannot recreate subscription",
                        "details": "The customer does not have a mandate ID. A valid SEPA mandate is required to create subscriptions.",
                    }
                )
                continue

            if not mandate_valid:
                results.append(
                    {
                        "customer_id": customer_id,
                        "old_subscription_id": old_subscription_id,
                        "status": "error",
                        "error": "Mandate is not valid - cannot recreate subscription",
                        "details": f"The mandate {mandate_id} is not in 'valid' status. Please ensure the customer has a valid SEPA mandate before recreating the subscription.",
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
            cancellation_confirmed = poll_subscription_cancellation(service, customer_id, old_subscription_id)

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

            # Only apply suffix if description wasn't overridden via CSV
            if description_changed:
                # CSV provided a new description, use it as-is
                unique_description = description
            else:
                # No CSV override, apply suffix to current description
                unique_description = generate_unique_description(description, description_suffix)

            try:

                def create_operation():
                    result = service.create_subscription(
                        customer_id=customer_id,
                        amount=amount,
                        interval=interval,
                        description=unique_description,
                        mandate_id=mandate_id,  # Use the validated mandate from the subscription
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


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def export_subscriptions_from_customers(customer_ids_csv: str) -> Dict:
    """
    Export active subscriptions for a list of customer IDs in recreation CSV format.

    Args:
        customer_ids_csv: CSV content with customer_id column

    Returns:
        Dict with CSV content ready for recreation tool
    """
    if not has_admin_access():
        frappe.throw(_("You don't have permission to access this function"), frappe.PermissionError)

    try:
        # Validate CSV size to prevent DoS
        if len(customer_ids_csv) > MAX_CSV_SIZE:
            return {
                "error": f"CSV file too large. Maximum size: {MAX_CSV_SIZE / 1024:.0f}KB",
                "status": "error",
            }

        # Parse customer IDs from CSV
        csv_file = io.StringIO(customer_ids_csv)
        reader = csv.DictReader(csv_file)

        # Validate required column
        if "customer_id" not in reader.fieldnames:
            return {"error": "CSV must contain 'customer_id' column", "status": "error"}

        # Convert to list and validate row count
        rows = list(reader)
        if len(rows) > MAX_CSV_ROWS:
            return {"error": f"Too many rows. Maximum: {MAX_CSV_ROWS}", "status": "error"}

        service = MollieDebugService()
        output_rows = []
        failed_customers = []

        for idx, row in enumerate(rows):
            customer_id = row.get("customer_id", "").strip()
            if not customer_id:
                continue

            # Add rate limiting pause every 10 requests to avoid overwhelming API
            if idx > 0 and idx % 10 == 0:
                time.sleep(0.5)

            # Get customer data including subscriptions
            customer_data = service.debug_customer(customer_id)

            if customer_data.get("error"):
                failed_customers.append({"customer_id": customer_id, "error": customer_data["error"]})
                continue

            # Process each active subscription
            for sub in customer_data.get("subscriptions", []):
                if sub["status"] != "active":
                    continue

                # Use helper to parse amount safely
                amount = parse_amount_string(sub.get("amount"))

                # Build output row matching recreation CSV format with CSV injection protection
                output_rows.append(
                    {
                        "customer_id": customer_id,
                        "subscription_id": sub["id"],
                        "amount": f"{amount:.2f}",
                        "interval": sanitize_csv_field(sub["interval"]),
                        "description": sanitize_csv_field(sub["description"]),
                        "next_payment_date": sub.get("next_payment_date", ""),
                        "mandate_id": sub.get("mandate_id", ""),
                    }
                )

        if not output_rows:
            return {
                "error": "No active subscriptions found for provided customer IDs",
                "status": "warning",
                "failed_customers": failed_customers,
            }

        # Generate CSV output
        output = io.StringIO()
        fieldnames = [
            "customer_id",
            "subscription_id",
            "amount",
            "interval",
            "description",
            "next_payment_date",
            "mandate_id",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

        csv_content = output.getvalue()

        result = {
            "status": "success" if not failed_customers else "partial",
            "csv_content": csv_content,
            "subscription_count": len(output_rows),
            "customer_count": len(set(row["customer_id"] for row in output_rows)),
            "failed_customers": failed_customers,
            "warnings": (
                f"{len(failed_customers)} customers could not be processed" if failed_customers else None
            ),
        }

        return result

    except Exception as e:
        frappe.log_error(f"Export subscriptions error: {str(e)}")
        return {"error": str(e), "status": "error"}
