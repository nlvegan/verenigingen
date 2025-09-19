"""
Mollie Payment Webhook Handler

Hybrid implementation that can optionally use the service layer architecture.
Falls back to direct function calls if service layer is not available.
"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, public_api


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
    """Determine if payment should be treated as recurring based on Mollie data and donation status"""
    has_mollie_subscription = bool(mollie_data.get("subscription_id"))

    # Check Mollie payment description for recurring intent (primary source of truth for first payments)
    donation_metadata_recurring = False
    mollie_description = mollie_data.get("description")
    if mollie_description:
        try:
            import json

            desc_data = json.loads(mollie_description)
            donation_metadata_recurring = desc_data.get("type") == "recurring"
        except (json.JSONDecodeError, TypeError):
            pass

    # Also check if donation was already marked as recurring (for subsequent payments)
    already_recurring = donation.get("status") == "Recurring" if hasattr(donation, "status") else False

    return has_mollie_subscription or donation_metadata_recurring or already_recurring


def process_successful_payment_with_idempotency(donation, payment, idempotency_status):
    """
    Process successful payment with proper ordering and isolated idempotency checks
    Order: Payment Entry → Payment History → Status Updates → Paid Flag (one-time only)
    """

    # Extract Mollie metadata first
    mollie_data = extract_mollie_payment_data(payment)
    frappe.logger().info("🔍 Full mollie_data: %s", mollie_data)

    # Determine if this is recurring - check both Mollie data AND original donation intent
    has_mollie_subscription = bool(mollie_data.get("subscription_id"))

    # For first payments of subscriptions, Mollie won't have subscription_id yet
    # So we check the Mollie payment description for recurring metadata
    donation_metadata_recurring = False
    mollie_description = mollie_data.get("description")
    frappe.logger().info("🔍 Mollie description raw: %s", repr(mollie_description))

    if mollie_description:
        try:
            import json

            desc_data = json.loads(mollie_description)
            donation_metadata_recurring = desc_data.get("type") == "recurring"
            frappe.logger().info("🔍 Parsed description JSON: %s", desc_data)
            frappe.logger().info("🔍 Type field: %s", desc_data.get("type"))
            frappe.logger().info("🔍 Is recurring from description: %s", donation_metadata_recurring)
        except (json.JSONDecodeError, TypeError) as e:
            frappe.logger().info("⚠️ Failed to parse Mollie description JSON: %s", e)
    else:
        frappe.logger().info("⚠️ No Mollie description found")

    # Also check if donation was already marked as recurring (for subsequent payments)
    already_recurring = donation.get("status") == "Recurring" if hasattr(donation, "status") else False

    is_recurring = has_mollie_subscription or donation_metadata_recurring or already_recurring

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

    # Determine if this is recurring - same logic as process_successful_payment_with_idempotency
    has_mollie_subscription = bool(mollie_data.get("subscription_id"))

    # Check Mollie payment description for recurring intent (primary source of truth for first payments)
    donation_metadata_recurring = False
    mollie_description = mollie_data.get("description")
    if mollie_description:
        try:
            import json

            desc_data = json.loads(mollie_description)
            donation_metadata_recurring = desc_data.get("type") == "recurring"
        except (json.JSONDecodeError, TypeError):
            pass

    # Also check if donation was already marked as recurring (for subsequent payments)
    already_recurring = donation.get("status") == "Recurring" if hasattr(donation, "status") else False

    is_recurring = has_mollie_subscription or donation_metadata_recurring or already_recurring

    # Update donation status using proper document operations
    donation.paid = 1
    if hasattr(donation, "payment_status"):
        donation.payment_status = "Completed"

    # Update donation status based on payment type (One-time vs Recurring)
    if is_recurring:
        donation.status = "Recurring"
        frappe.logger().info(
            "✅ Set donation %s status to Recurring (has_subscription=%s, already_recurring=%s, metadata_recurring=%s)",
            donation.name,
            has_mollie_subscription,
            already_recurring,
            donation_metadata_recurring,
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
        if not customer:
            frappe.logger().error("❌ No customer linked to donor %s", donation.donor)
            return None

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

        # Generate meaningful Payment Entry name using donor name + donation series
        donor_name_clean = frappe.scrub(donor_doc.donor_name)  # Clean name for naming
        donation_number = donation.name.split("-")[-1]  # Extract number from donation name

        # Create custom naming series: PE-[DonorName]-[DonationNumber]-
        custom_naming_series = f"PE-{donor_name_clean}-{donation_number}-"

        frappe.logger().info(
            "🏷️ Custom PE naming: %s for donor '%s' donation %s",
            custom_naming_series,
            donor_doc.donor_name,
            donation.name,
        )

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
                "remarks": f"Donation payment {donation.name} via Mollie ({mollie_data.get('method', 'Unknown method')}) - {donor_doc.donor_name}",
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
