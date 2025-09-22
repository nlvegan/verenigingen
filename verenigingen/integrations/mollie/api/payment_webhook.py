"""
Mollie Payment Webhook Handler

Hybrid implementation that can optionally use the service layer architecture.
Falls back to direct function calls if service layer is not available.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, public_api
from verenigingen.utils.validation_utilities import DocumentExistenceValidator


@frappe.whitelist(allow_guest=True, methods=["POST"])
@public_api(operation_type=OperationType.PUBLIC)
def handle_mollie_payment_webhook():
    """
    Handle Mollie webhook for existing donations

    Flow:
    1. Get payment ID from webhook
    2. Find corresponding donation by payment_id (or customer+time)
    3. Retrieve full payment details from Mollie API
    4. Create Payment Entry if payment is successful
    5. Update Member Payment History
    6. Enrich donation/customer records with Mollie metadata
    """

    try:
        # Get webhook data
        data = frappe.local.form_dict
        payment_id = data.get("id")

        if not payment_id:
            frappe.response.http_status_code = 400
            return {"status": "error", "message": "No payment ID provided"}

        # Set proper user context for webhook processing
        def get_webhook_user():
            """Get the configured webhook user or fallback to a user with proper permissions"""
            try:
                # Try to get webhook user from Verenigingen Payments Settings
                settings = frappe.get_single("Verenigingen Payments Settings")
                webhook_user = settings.get("webhook_user")

                if webhook_user and frappe.db.exists("User", webhook_user):
                    return webhook_user
            except:
                pass

            # Fallback: Look for a user with Verenigingen Webhook User role
            webhook_users = frappe.get_all(
                "Has Role", filters={"role": "Verenigingen Webhook User"}, fields=["parent"], limit=1
            )

            if webhook_users:
                user_email = webhook_users[0].parent
                if frappe.db.get_value("User", user_email, "enabled"):
                    return user_email

            # Final fallback: Use Administrator (not ideal but ensures webhook works)
            return "Administrator"

        webhook_user = get_webhook_user()
        frappe.set_user(webhook_user)
        frappe.logger().info(f"🔐 Set webhook user context: {webhook_user}")

        frappe.logger().info(f"🔔 Webhook received for payment: {payment_id}")

        # Optional: Try service layer first (graceful fallback if not available)
        try:
            from verenigingen.integrations.mollie.services.webhook_wrapper_service import (
                WebhookWrapperService,
            )

            service = WebhookWrapperService()
            result = service.process_webhook(payment_id)
            frappe.logger().info(f"✅ Service layer processing complete for {payment_id}")
            return result
        except ImportError:
            frappe.logger().info(f"🔄 Service layer not available, using direct functions for {payment_id}")
        except Exception as service_error:
            frappe.logger().warning(
                f"⚠️ Service layer failed, falling back to direct functions: {service_error}"
            )

        # Fallback: Original implementation using direct function calls

        # Check for idempotency
        processing_status = check_payment_processing_status_by_id(payment_id)
        if processing_status.get("all_complete"):
            frappe.logger().info(f"⏭️ Payment {payment_id} already fully processed - webhook complete")
            return {
                "status": "success",
                "message": "Payment already processed",
                "payment_id": payment_id,
                "components": processing_status,
            }

        # Get full payment details from Mollie
        mollie_settings = frappe.get_single("Mollie Settings")
        mollie = mollie_settings.get_mollie_client()

        try:
            payment = mollie.payments.get(payment_id)
        except Exception as e:
            frappe.log_error(f"Failed to fetch payment {payment_id} from Mollie: {e}", "Mollie API")
            frappe.response.http_status_code = 502
            return {"status": "error", "message": f"Failed to fetch payment from Mollie: {e}"}

        if payment.status != "paid":
            frappe.logger().info(f"⏭️ Payment {payment_id} status: {payment.status} - not processing")
            return {"status": "success", "message": f"Payment status: {payment.status}"}

        # Find related donation
        donation = find_donation_for_payment(payment_id, payment)
        if not donation:
            frappe.logger().error(f"❌ No donation found for payment {payment_id}")
            frappe.response.http_status_code = 404
            return {"status": "error", "message": "No donation found for payment"}

        # Check idempotency for this specific donation
        idempotency_status = check_payment_processing_status(donation, payment_id)

        # Process payment with idempotency protection
        result = process_successful_payment_with_idempotency(donation, payment, idempotency_status)

        frappe.logger().info(f"✅ Webhook processing complete for {payment_id}")
        return {"status": "success", "message": "Payment processed successfully", "data": result}

    except Exception as e:
        frappe.log_error(f"Webhook processing failed: {e}", "Mollie Webhook")
        frappe.response.http_status_code = 500
        return {"status": "error", "message": "Internal server error", "error": str(e)}


# ==================================================================================
# LEGACY HELPER FUNCTIONS
# ==================================================================================
# The functions below are preserved for backward compatibility with test utilities.
# Production webhook processing now uses the WebhookService class above.
# These functions may contain outdated business logic and should not be used
# for new implementations.
# ==================================================================================


def find_donation_for_subscription_payment(payment_id, payment, with_lock=False):
    """
    Find donation record for subscription payments by looking at payment metadata

    Args:
        payment_id (str): Mollie payment ID
        payment: Full Mollie payment object (can be None if not available yet)
        with_lock (bool): If True, acquire FOR UPDATE lock
    """
    # If payment object is available, check if this is a subscription payment
    if payment and (not hasattr(payment, "subscription_id") or not payment.subscription_id):
        return None

    # If payment object is available, get donation_id from payment metadata
    if payment:
        metadata = getattr(payment, "metadata", {})
        donation_id = metadata.get("donation_id")

        if donation_id:
            frappe.logger().info(f"🔍 Found donation_id in subscription payment metadata: {donation_id}")
            try:
                if with_lock:
                    # Acquire row-level lock
                    frappe.db.sql("SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE", (donation_id,))
                return frappe.get_doc("Donation", donation_id)
            except frappe.DoesNotExistError:
                frappe.logger().error(f"❌ Donation {donation_id} from metadata not found")
                return None

        # Fallback: try to find by subscription_id (if donation has it stored)
        frappe.logger().info(f"🔍 Trying fallback lookup by subscription_id: {payment.subscription_id}")
        donation_name = frappe.db.get_value(
            "Donation", {"mollie_subscription_id": payment.subscription_id}, "name"
        )
        if donation_name:
            if with_lock:
                frappe.db.sql("SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE", (donation_name,))
            return frappe.get_doc("Donation", donation_name)

    # If no payment object or no subscription info found, return None
    # This is normal for first payments that haven't been processed yet
    return None


def find_donation_for_payment_by_id(payment_id, with_lock=False):
    """
    Find donation record by payment_id (primary matching only)

    Args:
        payment_id (str): Mollie payment ID
        with_lock (bool): If True, acquire FOR UPDATE lock to prevent race conditions
    """
    donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
    if donation_name:
        if with_lock:
            # Acquire row-level lock to prevent concurrent webhook processing
            frappe.db.sql("SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE", (donation_name,))
        return frappe.get_doc("Donation", donation_name)
    return None


def check_payment_processing_status(donation, payment_id):
    """
    Check the processing status of each component with isolated idempotency checks

    Returns dict with status of:
    - payment_entry_created: Whether Payment Entry exists for this transaction ID
    - payment_history_exists: Whether payment history record exists for this transaction
    - donation_status_updated: Whether donation status is properly set
    - all_complete: Whether all components are processed
    """

    # Check 1: Payment Entry (isolated check - only looks for PE with matching transaction ID)
    payment_entry = frappe.db.get_value(
        "Payment Entry",
        {"reference_no": payment_id, "docstatus": 1},  # Direct transaction ID match  # Must be submitted
        "name",
    )
    payment_entry_created = bool(payment_entry)

    # Check 2: Payment History (isolated check - only looks for history with this transaction)
    payment_history_exists = False
    if hasattr(donation, "payments") and donation.payments:
        for payment_record in donation.payments:
            # Check multiple possible field names for transaction ID
            if (
                getattr(payment_record, "mollie_payment_id", None) == payment_id
                or getattr(payment_record, "payment_reference", None) == payment_id
                or getattr(payment_record, "payment_id", None) == payment_id
            ):
                payment_history_exists = True
                break

    # Check 3: Donation Status (isolated check - only verifies status is not "Promised")
    donation_status_updated = donation.status in ["One-time", "Recurring"]

    all_complete = payment_entry_created and payment_history_exists and donation_status_updated

    return {
        "payment_entry_created": payment_entry_created,
        "payment_history_exists": payment_history_exists,
        "donation_status_updated": donation_status_updated,
        "payment_entry_name": payment_entry if payment_entry_created else None,
        "donation_history_updated": payment_history_exists,
        "all_complete": all_complete,
    }


def find_donation_for_payment(payment_id, payment):
    """
    Find donation record for the given payment

    Matching strategy:
    1. Primary: Match by donation.payment_id
    2. Fallback: Match by customer + timestamp window (for edge cases)
    """

    # Primary matching: by payment_id
    donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
    if donation_name:
        return frappe.get_doc("Donation", donation_name)

    # Fallback matching: by customer ID and time window
    customer_id = getattr(payment, "customer_id", None)
    if not customer_id:
        return None

    # Get payment creation time
    payment_created = getattr(payment, "created_at", None)
    if not payment_created:
        return None

    # Convert to datetime if it's a string
    if isinstance(payment_created, str):
        try:
            payment_created = datetime.fromisoformat(payment_created.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    # Search for donations within 30-minute window
    time_window_start = payment_created - timedelta(minutes=30)
    time_window_end = payment_created + timedelta(minutes=30)

    donations = frappe.get_all(
        "Donation",
        filters={
            "mollie_customer_id": customer_id,
            "creation": ["between", [time_window_start, time_window_end]],
            "paid": 0,  # Only unpaid donations
        },
        order_by="creation desc",
        limit=1,
    )

    if donations:
        frappe.logger().info("✅ Found donation via customer+timestamp fallback: %s", donations[0].name)
        return frappe.get_doc("Donation", donations[0].name)

    return None


def _determine_recurring_status(donation, mollie_data):
    """
    Determine if payment should be treated as recurring with priority ordering

    Priority 1: Explicit metadata override (highest priority)
    Priority 2: Mollie subscription ID (definitive)
    Priority 3: SEPA mandate setup (mandate + customer indicates subscription intent)
    Priority 4: Other metadata indicators
    Priority 5: Legacy JSON description parsing
    Priority 6: Existing donation status
    """

    # Priority 1: Explicit metadata override (highest priority)
    if "metadata" in mollie_data and mollie_data["metadata"]:
        metadata = mollie_data["metadata"]
        subscription_setup = metadata.get("subscription_setup")
        if subscription_setup == "false":
            frappe.logger().info("🔍 Explicit subscription_setup=false override - marking as one-time")
            return False  # Explicit override
        elif subscription_setup == "true":
            frappe.logger().info("🔍 Explicit subscription_setup=true override - marking as recurring")
            return True  # Explicit override

    # Priority 2: Mollie subscription ID (definitive)
    if mollie_data.get("subscription_id"):
        frappe.logger().info("🔍 Mollie subscription_id present - marking as recurring")
        return True

    # Priority 3: SEPA mandate setup (mandate + customer indicates subscription intent)
    if mollie_data.get("mandate_id") and mollie_data.get("customer_id"):
        frappe.logger().info("🔍 SEPA mandate + customer detected - marking as recurring")
        return True

    # Priority 4: Other metadata indicators
    if "metadata" in mollie_data and mollie_data["metadata"]:
        metadata = mollie_data["metadata"]
        if metadata.get("subscription_interval") or metadata.get("subscription_amount"):
            frappe.logger().info("🔍 Subscription metadata indicators found - marking as recurring")
            return True

    # Priority 5: Legacy JSON description parsing (backward compatibility)
    mollie_description = mollie_data.get("description")
    if mollie_description:
        try:
            import json

            desc_data = json.loads(mollie_description)
            if desc_data.get("type") == "recurring":
                frappe.logger().info("🔍 Legacy JSON description indicates recurring - marking as recurring")
                return True
        except (json.JSONDecodeError, TypeError):
            pass

    # Priority 6: Existing donation status (for subsequent payments)
    if hasattr(donation, "status") and donation.get("status") == "Recurring":
        frappe.logger().info("🔍 Donation already marked as recurring - preserving status")
        return True

    # Default to one-time if no indicators found
    frappe.logger().info("🔍 No subscription indicators found - marking as one-time")
    return False


def process_successful_payment_with_idempotency(donation, payment, idempotency_status):
    """
    Process successful payment with proper ordering and isolated idempotency checks
    Order: Payment Entry → Payment History → Status Updates → Paid Flag (one-time only)
    """

    # Extract Mollie metadata first
    mollie_data = extract_mollie_payment_data(payment)
    frappe.logger().info("🔍 Full mollie_data: %s", mollie_data)

    # Determine if this is recurring using improved detection logic
    is_recurring = _determine_recurring_status(donation, mollie_data)

    # Initialize results with base data
    results = {"donation_id": donation.name, "mollie_payment_id": payment.id, "components_processed": []}

    # STEP 1: Create Payment Entry FIRST (atomic transaction protection)
    if not idempotency_status["payment_entry_created"]:
        frappe.logger().info("🔄 Creating Payment Entry for %s", donation.name)

        payment_entry = create_payment_entry_for_donation(donation, mollie_data)
        if payment_entry:
            results["payment_entry"] = payment_entry.name
            results["components_processed"].append("payment_entry_created")
            frappe.logger().info("✅ Payment Entry created: %s", payment_entry.name)
        else:
            frappe.logger().error("❌ Failed to create Payment Entry for %s", donation.name)
            raise ValueError(f"Payment Entry creation failed for {donation.name}")
    else:
        frappe.logger().info("⏭️ Payment Entry already exists")
        # Get the existing PE name for results
        existing_pe = frappe.db.get_value(
            "Payment Entry", {"reference_no": payment.id, "docstatus": 1}, "name"
        )
        results["payment_entry"] = existing_pe

    # STEP 2: Update Payment History SECOND
    if not idempotency_status["payment_history_exists"]:
        frappe.logger().info("🔄 Updating payment history for %s", donation.name)
        history_result = update_donation_payment_history(donation, mollie_data, results.get("payment_entry"))
        if history_result:
            results["components_processed"].append("payment_history_updated")
            frappe.logger().info("✅ Payment history updated")
        else:
            frappe.logger().error("❌ Failed to update payment history for %s", donation.name)
            # Continue processing - history is important but not critical
    else:
        frappe.logger().info("⏭️ Payment history already exists for transaction %s", payment.id)

    # STEP 3: Update Status THIRD
    if not idempotency_status["donation_status_updated"]:
        frappe.logger().info("🔄 Updating donation status for %s", donation.name)

        # Update status based on payment type using proper document operations
        if is_recurring:
            donation.status = "Recurring"
            frappe.logger().info(
                "✅ Set status to Recurring (subscription: %s)", mollie_data.get("subscription_id")
            )
        else:
            donation.status = "One-time"
            frappe.logger().info("✅ Set status to One-time")
            # Also set paid flag for one-time donations
            if donation.paid != 1:
                donation.paid = 1
                results["components_processed"].append("paid_flag_set")

        # Single save operation with all changes
        donation.save()

        # Update Mollie metadata (this handles its own save internally)
        update_donation_with_mollie_data(donation, mollie_data)
        results["components_processed"].append("status_updated")
    else:
        frappe.logger().info("⏭️ Donation status already updated")

    # Populate final result data
    results["amount"] = donation.amount
    results["payment_method"] = mollie_data.get("method")

    frappe.logger().info("✅ Processing completed: %s", results["components_processed"])
    return results


def process_successful_payment(donation, payment):
    """
    Process successful payment: create PE, update history, enrich records
    """

    # Extract Mollie metadata first
    mollie_data = extract_mollie_payment_data(payment)

    # Determine if this is recurring using improved detection logic
    is_recurring = _determine_recurring_status(donation, mollie_data)

    # Update donation status using proper document operations
    donation.paid = 1
    if hasattr(donation, "payment_status"):
        donation.payment_status = "Completed"

    # Update donation status based on payment type (One-time vs Recurring)
    if is_recurring:
        donation.status = "Recurring"
        frappe.logger().info(
            "✅ Set donation %s status to Recurring (improved detection logic)",
            donation.name,
        )
    else:
        donation.status = "One-time"
        frappe.logger().info("✅ Set donation %s status to One-time", donation.name)

    # Save all changes in one operation
    donation.save()

    # Update donation with Mollie metadata
    update_donation_with_mollie_data(donation, mollie_data)

    # Create Payment Entry
    payment_entry = create_payment_entry_for_donation(donation, mollie_data)

    # Update payment history - this was missing!
    payment_entry_name = payment_entry.name if payment_entry else None
    history_updated = update_donation_payment_history(donation, mollie_data, payment_entry_name)

    if history_updated:
        frappe.logger().info("✅ Payment history updated for donation %s", donation.name)
    else:
        frappe.logger().error("⚠️ Payment history update failed for donation %s", donation.name)

    return {
        "donation_id": donation.name,
        "payment_entry": payment_entry_name,
        "payment_history_updated": history_updated,
        "amount": donation.amount,
        "payment_method": mollie_data.get("method"),
        "mollie_payment_id": payment.id,
    }


def _extract_record_reference_from_mollie_data(payment_data, payment_id: str) -> str:
    """
    Extract record reference from Mollie payment data for origin-agnostic payment entry titles.

    Args:
        payment_data: Mollie payment object or extracted data dict
        payment_id: Mollie payment ID as fallback

    Returns:
        Record reference string (donation ID, membership ID, etc.)
    """
    try:
        # Method 1: From metadata
        if hasattr(payment_data, "metadata") and payment_data.metadata:
            metadata = payment_data.metadata
            if isinstance(metadata, dict) and metadata.get("record_id"):
                frappe.logger().info(f"🔍 Found record_id in metadata: {metadata['record_id']}")
                return metadata["record_id"]

        # Method 2: From description JSON
        if hasattr(payment_data, "description") and payment_data.description:
            try:
                import json

                desc_data = json.loads(payment_data.description)
                if isinstance(desc_data, dict) and desc_data.get("record_id"):
                    frappe.logger().info(f"🔍 Found record_id in description: {desc_data['record_id']}")
                    return desc_data["record_id"]
            except (json.JSONDecodeError, TypeError):
                pass

        # Method 3: From dict-style data (if payment_data is already extracted)
        if isinstance(payment_data, dict):
            metadata = payment_data.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("record_id"):
                frappe.logger().info(f"🔍 Found record_id in dict metadata: {metadata['record_id']}")
                return metadata["record_id"]

        # Fallback to payment_id
        frappe.logger().info(f"🔍 Using payment_id as record reference: {payment_id}")
        return payment_id

    except Exception as e:
        frappe.logger().warning(f"⚠️ Error extracting record reference: {e}")
        return payment_id


def extract_mollie_payment_data(payment):
    """Extract relevant data from Mollie payment object"""

    return {
        "payment_id": payment.id,
        "status": payment.status,
        "amount": (
            payment.amount.get("value")
            if isinstance(payment.amount, dict)
            else getattr(payment.amount, "value", None)
            if hasattr(payment, "amount")
            else None
        ),
        "currency": (
            payment.amount.get("currency")
            if isinstance(payment.amount, dict)
            else getattr(payment.amount, "currency", None)
            if hasattr(payment, "amount")
            else None
        ),
        "method": getattr(payment, "method", None),
        "customer_id": getattr(payment, "customer_id", None),
        "mandate_id": getattr(payment, "mandate_id", None),
        "subscription_id": getattr(payment, "subscription_id", None),
        "created_at": getattr(payment, "created_at", None),
        "paid_at": getattr(payment, "paid_at", None),
        "description": getattr(payment, "description", None),
        "metadata": getattr(payment, "metadata", {}),
    }


def update_donation_with_mollie_data(donation, mollie_data):
    """Update donation record with Mollie metadata"""

    updates = {}

    # Store the Mollie payment ID (transaction ID)
    if mollie_data.get("payment_id"):
        updates["payment_id"] = mollie_data["payment_id"]

    if mollie_data.get("customer_id"):
        updates["mollie_customer_id"] = mollie_data["customer_id"]

    if mollie_data.get("mandate_id"):
        updates["mollie_mandate_id"] = mollie_data["mandate_id"]

    if mollie_data.get("subscription_id"):
        updates["mollie_subscription_id"] = mollie_data["subscription_id"]

    if mollie_data.get("method"):
        updates["mode_of_payment"] = "Mollie"  # Use standard Mollie payment mode

    # Skip payment_date - field doesn't exist on Donation DocType
    # paid_at info is stored in Payment Entry instead

    # Update fields and save document
    if updates:
        for field, value in updates.items():
            setattr(donation, field, value)
        donation.save()

        frappe.logger().info(
            "✅ Updated donation %s with Mollie metadata: %s", donation.name, list(updates.keys())
        )


def create_payment_entry_for_donation(donation, mollie_data):
    """Create Payment Entry for the successful donation payment"""

    try:
        # Get the customer linked to the donor first (needed for both checking existing PE and creating new one)
        donor_doc = frappe.get_doc("Donor", donation.donor)
        customer = donor_doc.customer

        # Create customer if missing (guest donation support)
        if not customer:
            frappe.logger().info("🔧 Creating customer for donor %s (guest donation)", donation.donor)
            customer = _create_customer_for_donor(donor_doc)
            if not customer:
                frappe.logger().error("❌ Failed to create customer for donor %s", donation.donor)
                return None

            # Link customer to donor
            donor_doc.customer = customer
            donor_doc.flags.ignore_permissions = True
            donor_doc.save()
            frappe.logger().info("✅ Created and linked customer %s to donor %s", customer, donation.donor)

        # Check if Payment Entry already exists
        existing_pe = frappe.db.get_value(
            "Payment Entry",
            {"payment_type": "Receive", "reference_no": mollie_data["payment_id"], "party": customer},
            "name",
        )

        if existing_pe:
            frappe.logger().info("⚠️ Payment Entry already exists: %s", existing_pe)
            return frappe.get_doc("Payment Entry", existing_pe)

        # Get company and accounts
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.donation_company or frappe.defaults.get_global_default("company")

        # Get donation receivable account from settings (for party tracking)
        donation_account = settings.donation_receivable_account
        if not donation_account:
            donation_account = frappe.get_value("Company", company, "default_receivable_account")

        # Get bank account (for Mollie payments) with validation
        bank_account = frappe.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
        if not bank_account:
            # Fallback to default bank account
            bank_account = frappe.get_value("Company", company, "default_bank_account")

        # Validate required accounts exist
        if not donation_account:
            frappe.logger().error("❌ No income account found for company %s", company)
            return None

        if not bank_account:
            frappe.logger().error("❌ No bank account found for company %s", company)
            return None

        # Validate Mode of Payment exists
        if not DocumentExistenceValidator.check_document_exists("Mode of Payment", "Mollie"):
            frappe.logger().error("❌ Mollie Mode of Payment not configured")
            return None

        # Extract record reference from Mollie data for origin-agnostic approach
        record_reference = _extract_record_reference_from_mollie_data(payment, mollie_data["payment_id"])

        # Get the actual customer name (not the customer ID) for proper display
        customer_doc = frappe.get_doc("Customer", customer)
        display_name = customer_doc.customer_name or donor_doc.donor_name or "Unknown"

        # Generate meaningful Payment Entry name using display name + record reference
        donor_name_clean = frappe.scrub(display_name)  # Clean name for naming
        record_number = record_reference.split("-")[-1] if "-" in record_reference else record_reference

        # Create custom naming series: PE-[DonorName]-[RecordNumber]-
        custom_naming_series = f"PE-{donor_name_clean}-{record_number}-"

        frappe.logger().info(
            "🏷️ Custom PE naming: %s for donor '%s' donation %s",
            custom_naming_series,
            donor_doc.donor_name,
            donation.name,
        )

        # Set cost center for the company to satisfy P&L account requirements
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

        # Create Payment Entry for donation (Receive type with party tracking)
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "naming_series": custom_naming_series,
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "paid_amount": donation.amount,
                "received_amount": donation.amount,
                "reference_no": mollie_data["payment_id"],
                "reference_date": frappe.utils.getdate(),
                "company": company,
                "paid_from": donation_account,  # Money comes FROM receivable account (party account)
                "paid_to": bank_account,  # Money goes TO Mollie bank account
                "mode_of_payment": "Mollie",
                "cost_center": cost_center,  # Required for P&L accounts
                "title": f"{display_name} - {record_reference}",
                "remarks": f"Payment for {record_reference} via Mollie ({mollie_data.get('method', 'Unknown method')}) - {donor_doc.donor_name}",
            }
        )

        # Use proper webhook user permissions - no bypass needed
        pe.insert()
        pe.submit()

        frappe.logger().info("✅ Created Payment Entry: %s", pe.name)
        return pe

    except Exception as e:
        frappe.logger().error("❌ Failed to create Payment Entry: %s", str(e))
        frappe.log_error(
            f"Payment Entry creation failed for donation {donation.name}: {str(e)}",
            "Payment Entry Creation",
        )
        return None


def update_donation_payment_history(donation, mollie_data, payment_entry_name):
    """
    Update donation payment history child table

    Returns:
        bool: True if successful, False if failed
    """

    try:
        # Check if entry already exists
        existing_entry = None
        if hasattr(donation, "payments") and donation.payments:
            for payment_row in donation.payments:
                if (
                    payment_row.get("mollie_payment_id") == mollie_data["payment_id"]
                    or payment_row.get("payment_id") == mollie_data["payment_id"]
                ):
                    existing_entry = payment_row
                    break

        if existing_entry:
            frappe.logger().info("⏭️ Payment history entry already exists for %s", mollie_data["payment_id"])
            return True  # Already exists counts as success

        # Create new payment history entry
        payment_date = mollie_data.get("paid_at") or frappe.utils.getdate()
        if isinstance(payment_date, str):
            try:
                # Parse ISO datetime
                from dateutil import parser

                payment_date = parser.parse(payment_date).date()
            except (ValueError, TypeError, ImportError):
                payment_date = frappe.utils.getdate()

        donation.append(
            "payments",
            {
                "payment_date": payment_date,
                "amount": donation.amount,
                "payment_method": "Mollie",
                "payment_id": payment_entry_name or mollie_data["payment_id"],
                "payment_reference": mollie_data["payment_id"],
                "payment_status": "Paid",
                "mollie_payment_id": mollie_data["payment_id"],
                "mollie_customer_id": mollie_data.get("customer_id"),
                "mollie_mandate_id": mollie_data.get("mandate_id"),
                "mollie_subscription_id": mollie_data.get("subscription_id"),
            },
        )

        # Save donation with new payment history
        donation.save()
        frappe.logger().info("✅ Added payment history entry for donation %s", donation.name)
        return True

    except Exception as e:
        frappe.logger().error("❌ Failed to update donation payment history: %s", str(e))
        # Don't fail the entire webhook for history update issues
        frappe.log_error(
            f"Donation payment history update failed for {donation.name}: {str(e)}",
            "Donation Payment History",
        )
        return False


def check_payment_processing_status_by_id(payment_id):
    """
    Check payment processing status by payment ID only

    Returns dict with all_complete=False if no donation found for the payment ID
    """
    donation = find_donation_for_payment_by_id(payment_id)
    if not donation:
        return {"all_complete": False, "message": "No donation found for payment ID"}

    return check_payment_processing_status(donation, payment_id)


def _create_customer_for_donor(donor_doc):
    """
    Create a Customer record for a donor (guest donation support)

    Args:
        donor_doc: Donor document

    Returns:
        Customer name if successful, None if failed
    """
    try:
        # Get company for customer creation
        settings = frappe.get_single("Verenigingen Settings")
        company = settings.donation_company or frappe.defaults.get_global_default("company")

        # Validate and get Customer Group with fallback
        customer_group = "Individual"
        if not frappe.db.exists("Customer Group", customer_group):
            frappe.logger().warning("⚠️ Customer Group 'Individual' not found, using fallback")
            # Get any non-group customer group as fallback
            fallback_group = frappe.get_value("Customer Group", {"is_group": 0}, "name")
            customer_group = fallback_group or "All Customer Groups"

        # Validate and get Territory with fallback
        territory = "Netherlands"
        if not frappe.db.exists("Territory", territory):
            frappe.logger().warning("⚠️ Territory 'Netherlands' not found, using fallback")
            # Get any non-group territory as fallback
            fallback_territory = frappe.get_value("Territory", {"is_group": 0}, "name")
            territory = fallback_territory or "All Territories"

        # Validate donor email
        donor_email = donor_doc.donor_email
        if donor_email and not frappe.utils.validate_email_address(donor_email):
            frappe.logger().warning("⚠️ Invalid email for donor %s: %s", donor_doc.name, donor_email)
            donor_email = None  # Customer creation can proceed without email

        # Create customer with validated information
        customer_doc = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": donor_doc.donor_name or f"Donor {donor_doc.name}",
                "customer_type": "Individual",
                "customer_group": customer_group,
                "territory": territory,
                "company": company,
                # Link to donor
                "custom_donor": donor_doc.name,
                # Contact information (only if valid)
                "email_id": donor_email,
            }
        )

        customer_doc.flags.ignore_permissions = True
        customer_doc.insert()

        frappe.logger().info(
            "✅ Created customer %s for donor %s (group: %s, territory: %s)",
            customer_doc.name,
            donor_doc.name,
            customer_group,
            territory,
        )
        return customer_doc.name

    except Exception as e:
        frappe.logger().error("❌ Failed to create customer for donor %s: %s", donor_doc.name, str(e))
        return None
