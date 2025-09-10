"""
Mollie Payment Webhook Handler

This webhook handler processes all Mollie payment types including:
1. Donations (one-time and recurring)
2. Membership dues subscriptions
3. Event payments
4. Other association payment types

Key Features:
- Unified webhook for all payment types
- Simple idempotency via payment_id tracking
- Full Mollie API data retrieval
- Rich Payment Entry creation with complete payment details
- Customer/timestamp fallback matching for edge cases
- Environment detection via URL parameters
"""

from datetime import datetime, timedelta

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True, methods=["POST"])
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

    # Log all webhook calls for debugging with full request details
    frappe.logger().info(f"🔗 Mollie webhook called at {frappe.utils.now()}")
    frappe.logger().info(
        f"📋 Request headers: {dict(frappe.request.headers) if frappe.request else 'No request object'}"
    )
    frappe.logger().info(f"📋 Request method: {frappe.request.method if frappe.request else 'Unknown'}")
    frappe.logger().info(f"📋 Form dict: {frappe.form_dict}")

    try:
        # Set webhook user context for proper security
        payment_settings = frappe.get_single("Verenigingen Payments Settings")

        if not payment_settings or not payment_settings.webhook_user:
            frappe.throw(
                "Webhook user not configured in Verenigingen Payments Settings. Please configure a dedicated webhook user with 'Verenigingen Webhook User' role."
            )

        webhook_user = payment_settings.webhook_user
        frappe.set_user(webhook_user)

        # Get payment ID from webhook data - handle both JSON and form-encoded
        raw_payload = frappe.request.get_data(as_text=True) if frappe.request else ""

        if raw_payload and raw_payload.strip():
            try:
                # Try JSON first
                webhook_data = frappe.parse_json(raw_payload)
            except (ValueError, TypeError, Exception):
                # Fall back to form-encoded parsing
                if "=" in raw_payload:
                    from urllib.parse import parse_qs, unquote_plus

                    if "&" in raw_payload:
                        parsed_data = parse_qs(raw_payload)
                        webhook_data = {k: (v[0] if len(v) == 1 else v) for k, v in parsed_data.items()}
                    else:
                        key, value = raw_payload.split("=", 1)
                        webhook_data = {unquote_plus(key): unquote_plus(value)}
                else:
                    webhook_data = {}
        else:
            webhook_data = frappe.form_dict

        payment_id = webhook_data.get("id")

        # Validate webhook payload structure
        if not payment_id:
            return {"status": "error", "message": "Missing payment ID"}

        if not isinstance(payment_id, str) or not payment_id.startswith("tr_"):
            return {"status": "error", "message": "Invalid payment ID format"}

        # Validate required webhook fields
        if "status" not in webhook_data:
            return {"status": "error", "message": "Missing payment status"}

        # Find donation for this payment ID with database lock to prevent race conditions
        donation = find_donation_for_payment_by_id(payment_id, with_lock=True)
        if not donation:
            return {"status": "error", "message": "No matching donation found"}

        # Check granular idempotency for each component AFTER acquiring lock
        idempotency_status = check_payment_processing_status(donation, payment_id)

        if idempotency_status["all_complete"]:
            return {"status": "already_processed", "donation": donation.name, "details": idempotency_status}

        # Get Mollie API client
        settings = frappe.get_single("Mollie Settings")
        if not settings:
            return {"status": "error", "message": "Mollie settings not configured"}

        import mollie.api.client

        client = mollie.api.client.Client()
        client.set_api_key(settings.get_active_api_key())

        # Retrieve full payment details from Mollie API
        try:
            payment = client.payments.get(payment_id)
        except Exception as e:
            return {"status": "error", "message": f"Failed to retrieve payment data: {str(e)}"}

        # Process payment based on status with proper Frappe transaction management
        if payment.is_paid():
            try:
                # Use Frappe's transaction system instead of raw SQL
                result = process_successful_payment_with_idempotency(donation, payment, idempotency_status)
                return {"status": "success", "result": result}
            except Exception as e:
                frappe.logger().error(f"Payment processing failed for {payment.id}: {str(e)}")
                # Frappe automatically handles rollback in webhook context
                raise

        elif payment.is_canceled() or payment.is_expired() or payment.is_failed():
            # Update donation status for failed payments
            donation.paid = 0
            if hasattr(donation, "payment_status"):
                donation.payment_status = "Failed"
            donation.save()
            return {"status": "processed", "payment_status": "failed"}

        else:
            # Payment still pending
            return {"status": "processed", "payment_status": "pending"}

    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        payment_id_str = locals().get("payment_id", "unknown")
        raw_payload_str = locals().get("raw_payload", "unknown")

        try:
            frappe.log_error(
                f"Mollie donation webhook error: {str(e)}\n"
                f"Payment ID: {payment_id_str}\n"
                f"Raw payload: {raw_payload_str}\n"
                f"Full traceback:\n{error_details}",
                "Mollie Donation Webhook",
            )
        except Exception:
            # If even logging fails, just continue
            pass

        return {"status": "error", "message": str(e), "traceback": error_details}


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
        "amount": payment.amount.get("value")
        if isinstance(payment.amount, dict)
        else getattr(payment.amount, "value", None)
        if hasattr(payment, "amount")
        else None,
        "currency": payment.amount.get("currency")
        if isinstance(payment.amount, dict)
        else getattr(payment.amount, "currency", None)
        if hasattr(payment, "amount")
        else None,
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
        # Check if Payment Entry already exists
        existing_pe = frappe.db.get_value(
            "Payment Entry",
            {"payment_type": "Receive", "reference_no": mollie_data["payment_id"], "party": donation.donor},
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
        if not frappe.db.exists("Mode of Payment", "Mollie"):
            frappe.logger().error("❌ Mollie Mode of Payment not configured")
            return None

        # Generate meaningful Payment Entry name using donor name + donation series
        donor_doc = frappe.get_doc("Donor", donation.donor)
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
                "party": donation.donor,
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
