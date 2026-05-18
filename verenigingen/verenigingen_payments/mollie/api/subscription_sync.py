"""
Mollie Subscription Sync System
Retrieves subscription data from Mollie API and updates Customer records
"""

from typing import Dict

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
    MollieObjectType,
    get_payment_data_extractor,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def sync_mollie_subscriptions(dry_run=True) -> Dict:
    """
    Sync subscription data from Mollie API to Customer records

    Args:
        dry_run: If True, only simulate changes without saving

    Returns:
        Dict with sync results
    """
    # Convert string boolean to actual boolean
    if isinstance(dry_run, str):
        dry_run = dry_run.lower() in ("true", "1", "yes", "on")

    sync_results = {
        "success": True,
        "dry_run": dry_run,
        "customers_processed": 0,
        "subscriptions_updated": 0,
        "subscriptions_found": 0,
        "errors": [],
        "details": [],
    }

    try:
        frappe.set_user("Administrator")

        print("🚀 Starting Mollie subscription sync")
        print(f"   Mode: {'DRY RUN' if dry_run else 'LIVE EXECUTION'}")

        # Get the Mollie API client
        mollie_client = MollieClient()

        # Find all customers with existing Mollie customer IDs
        customers_with_mollie_ids = frappe.get_all(
            "Customer",
            filters={"custom_mollie_customer_id": ["!=", ""]},
            fields=["name", "custom_mollie_customer_id", "custom_mollie_subscription_id", "customer_name"],
        )

        print(f"📋 Found {len(customers_with_mollie_ids)} customers with Mollie IDs")
        sync_results["customers_processed"] = len(customers_with_mollie_ids)

        if not dry_run:
            frappe.db.begin()

        for customer_data in customers_with_mollie_ids:
            try:
                result = sync_customer_subscriptions(mollie_client, customer_data, dry_run)

                if result["subscriptions_found"] > 0:
                    sync_results["subscriptions_found"] += result["subscriptions_found"]

                if result["updated"]:
                    sync_results["subscriptions_updated"] += 1

                sync_results["details"].append(
                    {
                        "customer": customer_data["name"],
                        "customer_name": customer_data["customer_name"],
                        "mollie_customer_id": customer_data["custom_mollie_customer_id"],
                        "subscriptions_found": result["subscriptions_found"],
                        "updated": result["updated"],
                        "subscription_details": result.get("subscription_details", []),
                    }
                )

            except Exception as e:
                error_msg = f"Error syncing customer {customer_data['name']}: {str(e)}"
                sync_results["errors"].append(error_msg)
                print(f"❌ {error_msg}")

        # Commit or rollback (be resilient to API errors for old customers)
        if not dry_run:
            # Only rollback if there are critical errors, not just "customer not found" errors
            critical_errors = [
                error
                for error in sync_results["errors"]
                if "customer is no longer available" not in error.lower()
            ]

            if len(critical_errors) == 0:
                frappe.db.commit()
                print("✅ All changes committed successfully")
                if len(sync_results["errors"]) > 0:
                    print(f"   Note: {len(sync_results['errors'])} non-critical errors (old test customers)")
            else:
                frappe.db.rollback()
                print("❌ Critical errors detected, all changes rolled back")
                sync_results["success"] = False

        print("\n🎉 Subscription sync completed!")
        print(f"   Customers processed: {sync_results['customers_processed']}")
        print(f"   Subscriptions found: {sync_results['subscriptions_found']}")
        print(f"   Customer records updated: {sync_results['subscriptions_updated']}")
        print(f"   Errors: {len(sync_results['errors'])}")

        return sync_results

    except Exception as e:
        if not dry_run:
            frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Mollie Subscription Sync Error")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def sync_customer_subscriptions(mollie_client, customer_data: Dict, dry_run: bool = True) -> Dict:
    """
    Sync subscriptions for a specific customer

    Args:
        mollie_client: MollieClient instance
        customer_data: Customer record data
        dry_run: If True, only simulate changes

    Returns:
        Dict with sync results for this customer
    """
    result = {"subscriptions_found": 0, "updated": False, "subscription_details": []}

    mollie_customer_id = customer_data["custom_mollie_customer_id"]

    # Create extractor once for entire function (performance optimization)
    extractor = get_payment_data_extractor()

    try:
        # Get all subscriptions for this customer from Mollie
        # MollieClient has no customer-subscriptions method; use the raw SDK client directly
        customer_subscriptions = mollie_client.sdk_client.customers.get(
            mollie_customer_id
        ).subscriptions.list()

        active_subscription = None
        latest_subscription = None

        for subscription in customer_subscriptions:
            result["subscriptions_found"] += 1

            # Extract amount using centralized extractor (handles both object and dict formats)
            amount = extractor.extract_amount(
                subscription, allow_zero=True, source_type=MollieObjectType.SUBSCRIPTION
            )

            # Extract currency from subscription amount
            amount_value = subscription.amount
            if hasattr(amount_value, "currency"):
                currency = amount_value.currency
            elif isinstance(amount_value, dict):
                currency = amount_value.get("currency", "EUR")
            else:
                currency = "EUR"

            subscription_info = {
                "id": subscription.id,
                "status": subscription.status,
                "amount": amount,
                "currency": currency,
                "interval": subscription.interval,
                "description": subscription.description,
                "created_at": subscription.created_at,
                "next_payment_date": getattr(subscription, "next_payment_date", None),
            }

            result["subscription_details"].append(subscription_info)

            # Find the most relevant subscription
            if subscription.status == "active":
                active_subscription = subscription
            elif not latest_subscription or subscription.created_at > latest_subscription.created_at:
                latest_subscription = subscription

        # Determine which subscription to use for the customer record
        primary_subscription = active_subscription or latest_subscription

        if primary_subscription:
            # Update customer record with subscription data
            updates = {}

            current_subscription_id = customer_data.get("custom_mollie_subscription_id")
            new_subscription_id = primary_subscription.id

            # Only update if subscription ID changed or if we don't have one
            if not current_subscription_id or current_subscription_id != new_subscription_id:
                updates["custom_mollie_subscription_id"] = new_subscription_id
                updates["custom_subscription_status"] = primary_subscription.status

                if hasattr(primary_subscription, "next_payment_date"):
                    updates["custom_next_payment_date"] = primary_subscription.next_payment_date

                if dry_run:
                    print(f"   Would update {customer_data['name']} with subscription {new_subscription_id}")
                    result["updated"] = True
                else:
                    # Apply updates to customer record
                    customer = frappe.get_doc("Customer", customer_data["name"])
                    for field, value in updates.items():
                        customer.db_set(field, value, commit=False)

                    print(f"✅ Updated {customer_data['name']} with subscription {new_subscription_id}")
                    result["updated"] = True

    except Exception as e:
        print(f"❌ Error fetching subscriptions for customer {mollie_customer_id}: {str(e)}")
        raise

    return result


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def sync_single_customer_subscription(customer_name: str, dry_run: bool = True) -> Dict:
    """
    Sync subscriptions for a single customer

    Args:
        customer_name: Name of Customer record
        dry_run: If True, only simulate changes

    Returns:
        Dict with sync results
    """
    try:
        mollie_client = MollieClient()

        customer_data = frappe.get_value(
            "Customer",
            customer_name,
            ["name", "custom_mollie_customer_id", "custom_mollie_subscription_id", "customer_name"],
            as_dict=True,
        )

        if not customer_data or not customer_data.get("custom_mollie_customer_id"):
            return {"success": False, "error": "Customer not found or no Mollie Customer ID"}

        result = sync_customer_subscriptions(mollie_client, customer_data, dry_run)
        result["success"] = True
        result["customer"] = customer_name

        return result

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Single Customer Sync Error")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_mollie_subscription_details(customer_name: str) -> Dict:
    """
    Get subscription details from Mollie for a specific customer

    Args:
        customer_name: Name of Customer record

    Returns:
        Dict with subscription details
    """
    try:
        mollie_client = MollieClient()

        customer_data = frappe.get_value(
            "Customer",
            customer_name,
            ["name", "custom_mollie_customer_id", "custom_mollie_subscription_id", "customer_name"],
            as_dict=True,
        )

        if not customer_data or not customer_data.get("custom_mollie_customer_id"):
            return {"success": False, "error": "Customer not found or no Mollie Customer ID"}

        mollie_customer_id = customer_data["custom_mollie_customer_id"]

        # Get all subscriptions for this customer
        customer_subscriptions = mollie_client.sdk_client.customers.get(
            mollie_customer_id
        ).subscriptions.list()

        # Create extractor once for entire loop (performance optimization)
        extractor = get_payment_data_extractor()

        subscription_details = []

        for subscription in customer_subscriptions:
            # Extract amount using centralized extractor (handles both object and dict formats)
            amount = extractor.extract_amount(
                subscription, allow_zero=True, source_type=MollieObjectType.SUBSCRIPTION
            )

            # Extract currency from subscription amount
            amount_value = subscription.amount
            if hasattr(amount_value, "currency"):
                currency = amount_value.currency
            elif isinstance(amount_value, dict):
                currency = amount_value.get("currency", "EUR")
            else:
                currency = "EUR"

            subscription_info = {
                "id": subscription.id,
                "status": subscription.status,
                "amount": amount,
                "currency": currency,
                "interval": subscription.interval,
                "description": subscription.description,
                "created_at": subscription.created_at,
                "next_payment_date": getattr(subscription, "next_payment_date", None),
                "times_charged": getattr(subscription, "times_charged", 0),
            }

            # Get recent payments for this subscription
            try:
                recent_payments = []
                payments = subscription.payments.list(limit=5)
                for payment in payments:
                    # Extract payment amount using centralized extractor
                    payment_amount = extractor.extract_amount(payment, allow_zero=True)

                    recent_payments.append(
                        {
                            "id": payment.id,
                            "status": payment.status,
                            "amount": payment_amount,
                            "created_at": payment.created_at,
                        }
                    )
                subscription_info["recent_payments"] = recent_payments
            except:
                subscription_info["recent_payments"] = []

            subscription_details.append(subscription_info)

        return {
            "success": True,
            "customer": customer_name,
            "customer_name": customer_data["customer_name"],
            "mollie_customer_id": mollie_customer_id,
            "subscriptions": subscription_details,
            "total_subscriptions": len(subscription_details),
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Subscription Details Error")
        return {"success": False, "error": str(e)}
