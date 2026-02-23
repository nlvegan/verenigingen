"""
Mollie Bulk Payment Creation Tool
Administrative interface for creating one-time payments in bulk against existing mandates
"""

import csv
import hashlib
import io
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _

from verenigingen.services.mollie_debug_service import MollieDebugService
from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import require_login
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

# Configuration constants
MAX_CSV_SIZE = 1024 * 1024  # 1MB limit for CSV uploads
MAX_CSV_ROWS = 500  # Maximum rows to process (lower for payments)
MAX_PAYMENTS_PAYLOAD_SIZE = 100 * 1024  # 100KB for base64 payload


def get_context(context):
    """Get context for Mollie bulk payment creation page"""
    require_login()

    # Check permissions - only administrators
    if not has_admin_access():
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Mollie Bulk Payment Creation")

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
    """Check if current user has access to bulk payment creation tool"""
    allowed_roles = [
        Roles.SYSTEM_MANAGER,
        "Administrator",
        Roles.VERENIGINGEN_ADMIN,
        Roles.VERENIGINGEN_STAFF,
        "Treasurer",
    ]
    user_roles = frappe.get_roles(frappe.session.user)
    return any(role in allowed_roles for role in user_roles)


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
        return "'" + value_str

    return value_str


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def validate_csv_members(
    csv_content: str,
    global_charge_date: str = "",
    global_amount: str = "",
    global_description: str = "",
    include_member_id_suffix: bool = False,
    payment_interval: str = "1 month",
    payment_times: int = 1,
) -> Dict:
    """
    Parse CSV file and validate member data for bulk payment creation.

    Expected CSV format:
    customer_id[,amount][,charge_date][,description]

    Args:
        csv_content: CSV file content
        global_charge_date: Global charge date for rows without charge_date (YYYY-MM-DD)
        global_amount: Global amount for rows without amount
        global_description: Global description for all payments

    Returns:
        Dict with validation results including member status and mandate status
    """
    try:
        if not has_admin_access():
            frappe.throw(_("Access denied - Administrator role required"))

        # Convert boolean parameter (may come as string from JS)
        include_suffix = include_member_id_suffix in (True, "true", "1", 1)

        # Validate interval
        valid_intervals = ["1 month", "2 months", "3 months", "6 months", "12 months"]
        if payment_interval not in valid_intervals:
            return {
                "status": "error",
                "error": f"Invalid interval. Must be one of: {', '.join(valid_intervals)}",
            }

        # Validate times (convert from string if needed)
        try:
            payment_times_int = int(payment_times)
            if payment_times_int < 1:
                return {"status": "error", "error": "Number of payments must be at least 1"}
            if payment_times_int > 100:
                return {"status": "error", "error": "Number of payments cannot exceed 100"}
        except (ValueError, TypeError):
            return {"status": "error", "error": "Invalid number of payments"}

        # Validate CSV size to prevent DoS
        if len(csv_content) > MAX_CSV_SIZE:
            return {
                "status": "error",
                "error": f"CSV file too large. Maximum size: {MAX_CSV_SIZE / 1024:.0f}KB",
            }

        # Parse CSV
        reader = csv.DictReader(io.StringIO(csv_content))

        # Validate CSV has required columns
        if not reader.fieldnames or "customer_id" not in reader.fieldnames:
            return {
                "error": "Invalid CSV format. Required column: customer_id (optional: amount, charge_date, description)",
                "status": "error",
            }

        # Check which optional columns are present
        has_amount_column = "amount" in reader.fieldnames
        has_date_column = "charge_date" in reader.fieldnames
        has_description_column = "description" in reader.fieldnames

        # Convert to list and validate row count
        all_rows = list(reader)
        if len(all_rows) > MAX_CSV_ROWS:
            return {"status": "error", "error": f"Too many rows. Maximum: {MAX_CSV_ROWS}"}

        # Parse global values
        parsed_global_amount = None
        if global_amount:
            try:
                parsed_global_amount = float(global_amount)
                if parsed_global_amount <= 0:
                    return {"status": "error", "error": "Global amount must be positive"}
            except ValueError:
                return {"status": "error", "error": "Invalid global amount format"}

        # Validate global date format if provided
        parsed_global_date = None
        max_date = (datetime.now() + timedelta(days=365)).date()
        if global_charge_date:
            try:
                parsed_global_date = datetime.strptime(global_charge_date, "%Y-%m-%d").date()
                # Charge date should be in the future (at least tomorrow)
                if parsed_global_date <= datetime.now().date():
                    return {"status": "error", "error": "Global charge date must be in the future"}
                # Charge date should not be more than 1 year in the future
                if parsed_global_date > max_date:
                    return {
                        "status": "error",
                        "error": "Global charge date cannot be more than 1 year in the future",
                    }
            except ValueError:
                return {"status": "error", "error": "Invalid date format. Use YYYY-MM-DD format."}

        # Initialize Mollie service for mandate validation
        service = MollieDebugService()
        validation_results = []

        for row in all_rows:
            customer_id = row.get("customer_id", "").strip()
            if not customer_id:
                continue

            result = {
                "customer_id": customer_id,
                "member_name": None,
                "member_id": None,
                "member_status": None,
                "mandate_id": None,
                "mandate_valid": False,
                "amount": None,
                "charge_date": None,
                "description": global_description or "Membership payment",
                "interval": payment_interval,
                "times": payment_times_int,
                "status": "valid",
                "issues": [],
            }

            # Parse row-specific amount
            if has_amount_column and row.get("amount"):
                try:
                    result["amount"] = float(row["amount"].strip())
                except (ValueError, AttributeError):
                    pass

            # Use global amount if no row-specific amount
            if not result["amount"] and parsed_global_amount:
                result["amount"] = parsed_global_amount

            # Parse row-specific date
            if has_date_column and row.get("charge_date"):
                try:
                    row_date = datetime.strptime(row["charge_date"].strip(), "%Y-%m-%d").date()
                    if row_date <= datetime.now().date():
                        result["issues"].append("Charge date must be in the future")
                    elif row_date > max_date:
                        result["issues"].append("Charge date cannot be more than 1 year in the future")
                    else:
                        result["charge_date"] = row["charge_date"].strip()
                except ValueError:
                    result["issues"].append("Invalid charge_date format")

            # Use global date if no row-specific date
            if not result["charge_date"] and parsed_global_date:
                result["charge_date"] = global_charge_date

            # Parse row-specific description
            if has_description_column and row.get("description"):
                result["description"] = row["description"].strip()[:140]  # Mollie limit

            # Look up member by Mollie customer ID
            member = frappe.db.get_value(
                "Member",
                {"mollie_customer_id": customer_id},
                ["name", "member_id", "full_name", "status", "mollie_mandate_id"],
                as_dict=True,
            )

            if not member:
                result["status"] = "error"
                result["issues"].append("Member not found with this customer ID")
                validation_results.append(result)
                continue

            result["member_id"] = member.name
            result["member_name"] = member.full_name or member.name
            result["member_status"] = member.status
            result["mandate_id"] = member.mollie_mandate_id

            # Append member ID suffix to description if enabled
            if include_suffix:
                result["description"] = f"{result['description']} voor lidnummer {member.member_id}"

            # Check member status
            if member.status != "Active":
                result["status"] = "warning"
                result["issues"].append(f"Member status is {member.status}")

            # Check mandate exists and is valid
            if not member.mollie_mandate_id:
                # Try to find a valid mandate from Mollie
                try:
                    customer_data = service.debug_customer(customer_id)
                    if not customer_data.get("error"):
                        mandates = customer_data.get("mandates", [])
                        for m in mandates:
                            if m.get("status") == "valid":
                                result["mandate_id"] = m.get("id")
                                result["mandate_valid"] = True
                                # Note: mandate discovered from Mollie API, not stored on Member
                                result["issues"].append("Mandate found via Mollie API (not stored on Member)")
                                break

                        if not result["mandate_valid"]:
                            result["status"] = "error"
                            result["issues"].append("No valid mandate found")
                except Exception as e:
                    result["status"] = "error"
                    result["issues"].append(f"Error checking mandates: {str(e)}")
            else:
                # Verify mandate is still valid
                try:
                    mandate_result = service.debug_mandate(member.mollie_mandate_id, customer_id)
                    if not mandate_result.get("error"):
                        mandate_data = mandate_result.get("mandate_data", {})
                        mandate_status = mandate_data.get("status")
                        result["mandate_valid"] = mandate_status == "valid"

                        if not result["mandate_valid"]:
                            result["status"] = "error"
                            result["issues"].append(f"Mandate status is {mandate_status}")
                    else:
                        result["status"] = "error"
                        result["issues"].append("Could not verify mandate")
                except Exception as e:
                    result["status"] = "error"
                    result["issues"].append(f"Mandate check failed: {str(e)}")

            # Validate amount is present
            if not result["amount"]:
                result["status"] = "error"
                result["issues"].append("Amount is required")

            # Validate charge date is present
            if not result["charge_date"]:
                result["status"] = "error"
                result["issues"].append("Charge date is required")

            # Final status determination
            if result["issues"] and result["status"] == "valid":
                result["status"] = "warning"

            validation_results.append(result)

        if not validation_results:
            return {"status": "error", "error": "No valid rows found in CSV"}

        return {
            "status": "success",
            "results": validation_results,
            "total_rows": len(validation_results),
        }

    except Exception as e:
        frappe.log_error(f"Bulk payment validation error: {str(e)}")
        return {"error": str(e), "status": "error"}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_bulk_payments(payments_json: str) -> Dict:
    """
    Create payments in bulk using Mollie subscriptions API.

    This creates subscriptions with the specified number of payments (times parameter).
    Using subscriptions allows specifying the startDate for when the first payment occurs.

    Args:
        payments_json: JSON string of validated payment data

    Returns:
        Dict with payment creation results
    """
    try:
        if not has_admin_access():
            frappe.throw(_("Access denied - Administrator role required"))

        if not payments_json:
            return {"status": "error", "error": "Payments data is required"}

        # Validate payload size
        if len(payments_json) > MAX_PAYMENTS_PAYLOAD_SIZE:
            return {"status": "error", "error": "Request payload too large"}

        try:
            payments = json.loads(payments_json)
        except json.JSONDecodeError as e:
            return {"status": "error", "error": f"Invalid JSON: {str(e)}"}

        # Initialize MollieDebugService for subscription creation
        service = MollieDebugService()

        # Also get raw client for duplicate checking
        mollie_settings = frappe.get_single("Mollie Settings")
        mollie_client = mollie_settings.get_mollie_client()

        results = []
        total_amount = 0.0

        for idx, payment_data in enumerate(payments):
            # Rate limiting: pause every 10 requests to avoid overwhelming Mollie API
            if idx > 0 and idx % 10 == 0:
                time.sleep(0.5)

            customer_id = payment_data.get("customer_id")
            member_name = payment_data.get("member_name", "Unknown")
            amount = float(payment_data.get("amount", 0))
            charge_date = payment_data.get("charge_date")
            description = payment_data.get("description", "Membership payment")
            mandate_id = payment_data.get("mandate_id")
            interval = payment_data.get("interval", "1 month")
            times = int(payment_data.get("times", 1))

            result = {
                "customer_id": customer_id,
                "member_name": member_name,
                "amount": amount,
                "charge_date": charge_date,
                "status": "pending",
                "payment_id": None,  # Will contain subscription_id
                "error": None,
            }

            # Validate required data
            if not mandate_id:
                result["status"] = "error"
                result["error"] = "No valid mandate ID"
                results.append(result)
                continue

            if amount <= 0:
                result["status"] = "error"
                result["error"] = "Invalid amount"
                results.append(result)
                continue

            if not charge_date:
                result["status"] = "error"
                result["error"] = "Charge date is required for subscriptions"
                results.append(result)
                continue

            try:
                # Generate idempotency key to prevent duplicate subscriptions
                # Based on customer + amount + date - same combination = same key
                idempotency_data = f"{customer_id}:{amount}:{charge_date}"
                _idempotency_key = hashlib.sha256(idempotency_data.encode()).hexdigest()[:32]  # noqa: F841

                # Check for duplicate subscriptions (same customer, amount, start date)
                # Skip cancelled subscriptions - they didn't actually charge the customer
                is_duplicate = False
                try:
                    customer = mollie_client.customers.get(customer_id)
                    # Check existing subscriptions
                    existing_subscriptions = customer.subscriptions.list()
                    for existing_sub in existing_subscriptions:
                        # Skip cancelled subscriptions - allow retry after cancellation
                        sub_status = getattr(existing_sub, "status", "")
                        if sub_status in ["canceled", "cancelled"]:
                            continue

                        # Check by start date and amount
                        sub_start = getattr(existing_sub, "startDate", None)
                        sub_amount = getattr(existing_sub, "amount", {})
                        sub_amount_value = (
                            float(sub_amount.get("value", 0)) if isinstance(sub_amount, dict) else 0
                        )

                        if sub_start == charge_date and abs(sub_amount_value - amount) < 0.01:
                            result["status"] = "skipped"
                            result[
                                "error"
                            ] = f"Duplicate: subscription {existing_sub.id} already exists for this date/amount"
                            result["payment_id"] = existing_sub.id
                            is_duplicate = True
                            frappe.logger().warning(
                                f"Skipped duplicate subscription for {customer_id}: {existing_sub.id}"
                            )
                            break
                except Exception as dup_check_error:
                    # If duplicate check fails, log but continue with subscription creation
                    frappe.logger().warning(f"Duplicate check failed for {customer_id}: {dup_check_error}")

                if is_duplicate:
                    results.append(result)
                    continue

                # Create subscription using MollieDebugService
                # The times parameter limits the subscription to N payments
                create_result = service.create_subscription(
                    customer_id=customer_id,
                    amount=amount,
                    interval=interval,
                    description=description[:140],  # Mollie has 140 char limit
                    mandate_id=mandate_id,
                    start_date=charge_date,
                    times=times,
                )

                if create_result.get("status") == "error" or create_result.get("error"):
                    result["status"] = "error"
                    result["error"] = create_result.get("error", "Unknown error creating subscription")
                else:
                    subscription_id = create_result.get("subscription_id")
                    result["status"] = "success"
                    result["payment_id"] = subscription_id  # Store subscription ID in payment_id field
                    total_amount += amount

                    # Log successful creation
                    frappe.logger().info(
                        f"Bulk subscription created: {subscription_id} for customer {customer_id}, "
                        f"amount {amount}, start {charge_date}, times {times}"
                    )

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
                frappe.log_error(
                    f"Bulk subscription creation failed for {customer_id}: {str(e)}", "Bulk Payment Error"
                )

            results.append(result)

        success_count = sum(1 for r in results if r["status"] == "success")
        error_count = sum(1 for r in results if r["status"] == "error")
        skipped_count = sum(1 for r in results if r["status"] == "skipped")

        return {
            "status": "completed",
            "results": results,
            "summary": {
                "total": len(results),
                "success": success_count,
                "errors": error_count,
                "skipped": skipped_count,
                "total_amount": total_amount,
            },
        }

    except Exception as e:
        frappe.log_error(f"Bulk payment creation error: {str(e)}")
        return {"error": str(e), "status": "error"}


def get_webhook_url() -> str:
    """Get the webhook URL for payment notifications with environment parameter"""
    site_url = frappe.utils.get_url()
    base_url = f"{site_url}/api/method/verenigingen.utils.payment_gateways.mollie_payment_webhook"

    # Add environment parameter based on Mollie Settings test_mode
    try:
        mollie_settings = frappe.get_single("Mollie Settings")
        env_param = "test" if mollie_settings.test_mode else "live"
    except Exception:
        # Fallback to test mode if settings unavailable
        env_param = "test"

    return f"{base_url}?env={env_param}"
