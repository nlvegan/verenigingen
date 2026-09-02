"""
Mollie Payment Webhook Handler

Hybrid implementation that can optionally use the service layer architecture.
Falls back to direct function calls if service layer is not available.
"""

import frappe
from frappe import _

from verenigingen.services.customer_group_resolver import resolve_non_group_customer_group
from verenigingen.utils.validation_utilities import DocumentExistenceValidator

# Import extracted handlers
from verenigingen.verenigingen_payments.mollie.services.handlers import (
    check_payment_processing_status as _handler_check_payment_processing_status,
    find_donation_for_payment as _handler_find_donation_for_payment,
    find_donation_for_payment_by_id as _handler_find_donation_for_payment_by_id,
    find_donation_for_subscription_payment as _handler_find_donation_for_subscription_payment,
)


def get_appropriate_cost_center(donation, company):
    """
    Get appropriate cost center based on donation purpose instead of random selection.

    Args:
        donation: Donation document
        company: Company name

    Returns:
        str: Cost center name
    """
    # Default fallback cost center
    default_cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")

    if not donation:
        return default_cost_center

    # Check donation purpose type
    purpose_type = getattr(donation, "donation_purpose_type", None)

    if purpose_type == "Chapter" and hasattr(donation, "chapter_reference"):
        # Try to get chapter-specific cost center
        chapter_cost_center = frappe.db.get_value(
            "Cost Center",
            {
                "company": company,
                "cost_center_name": ["like", f"%{donation.chapter_reference}%"],
                "is_group": 0,
            },
            "name",
        )
        if chapter_cost_center:
            return chapter_cost_center

    # For General Fund or any other purpose, use a general cost center
    # Look for a cost center with "General" or "Main" in the name first
    general_cost_center = frappe.db.get_value(
        "Cost Center",
        {
            "company": company,
            "is_group": 0,
            "cost_center_name": ["in", ["General", "Main", "General Fund", "Operations"]],
        },
        "name",
    )

    if general_cost_center:
        return general_cost_center

    # If no specific general cost center found, return the default
    return default_cost_center


# ARCHIVED: handle_mollie_payment_webhook_DISABLED function moved to:
# archived/refund_chargeback_service/handle_mollie_payment_webhook_DISABLED.py
# Reason: Replaced by unified payment processing architecture
# Use unified_payment_api.handle_payment_webhook instead


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
    Find donation record for subscription payments by looking at payment metadata.

    DELEGATED: This function now delegates to the extracted DonationLookup handler.

    Args:
        payment_id (str): Mollie payment ID
        payment: Full Mollie payment object (can be None if not available yet)
        with_lock (bool): If True, acquire FOR UPDATE lock
    """
    return _handler_find_donation_for_subscription_payment(payment_id, payment, with_lock)


def find_donation_for_payment_by_id(payment_id, with_lock=False):
    """
    Find donation record by payment_id (primary matching only).

    DELEGATED: This function now delegates to the extracted DonationLookup handler.

    Args:
        payment_id (str): Mollie payment ID
        with_lock (bool): If True, acquire FOR UPDATE lock to prevent race conditions
    """
    return _handler_find_donation_for_payment_by_id(payment_id, with_lock)


def check_payment_processing_status(donation, payment_id):
    """
    Check the processing status of each component with isolated idempotency checks.

    DELEGATED: This function now delegates to the extracted DonationLookup handler.

    Returns dict with status of:
    - payment_entry_created: Whether Payment Entry exists for this transaction ID
    - payment_history_exists: Whether payment history record exists for this transaction
    - donation_status_updated: Whether donation status is properly set
    - all_complete: Whether all components are processed
    """
    return _handler_check_payment_processing_status(donation, payment_id)


def find_donation_for_payment(payment_id, payment):
    """
    Find donation record for the given payment.

    DELEGATED: This function now delegates to the extracted DonationLookup handler.

    Matching strategy:
    1. Primary: Match by donation.payment_id
    2. Fallback: Match by customer + timestamp window (for edge cases)
    """
    return _handler_find_donation_for_payment(payment_id, payment)


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

    # Priority 0: Mollie sequence_type (most reliable — set by Mollie itself)
    sequence_type = mollie_data.get("sequence_type")
    if sequence_type in ("first", "recurring"):
        frappe.logger().info(f"Mollie sequence_type={sequence_type} - marking as recurring")
        return True
    if sequence_type == "oneoff":
        frappe.logger().info("Mollie sequence_type=oneoff - marking as one-time")
        return False

    # Priority 1: Explicit metadata override
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
    # Log sanitized data (exclude sensitive fields like customer_id, metadata)
    safe_log_data = {
        k: v for k, v in mollie_data.items() if k not in ("customer_id", "metadata", "mandate_id")
    }
    frappe.logger().info("🔍 Mollie payment data: %s", safe_log_data)

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
        # Get the existing PE name using unified idempotency manager
        from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
            get_unified_idempotency_manager,
        )

        idempotency_manager = get_unified_idempotency_manager()
        existing_pe = idempotency_manager.payment_entry_exists(payment.id)
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

        # Set paid flag for both one-time and recurring donations when payment is received
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

    # Read amount once via getattr: a payment object with no `amount` attribute
    # must not raise. (The previous expression dereferenced payment.amount in the
    # first ternary clause before the trailing `hasattr(payment, "amount")` guard
    # could short-circuit, so that guard was dead and an amount-less object raised
    # AttributeError.) amount may be a dict, an SDK object with .value/.currency,
    # or None.
    amount = getattr(payment, "amount", None)

    return {
        "payment_id": payment.id,
        "status": payment.status,
        "amount": (amount.get("value") if isinstance(amount, dict) else getattr(amount, "value", None)),
        "currency": (
            amount.get("currency") if isinstance(amount, dict) else getattr(amount, "currency", None)
        ),
        "method": getattr(payment, "method", None),
        "customer_id": getattr(payment, "customer_id", None),
        "mandate_id": getattr(payment, "mandate_id", None),
        "subscription_id": getattr(payment, "subscription_id", None),
        "created_at": getattr(payment, "created_at", None),
        "paid_at": getattr(payment, "paid_at", None),
        "description": getattr(payment, "description", None),
        "metadata": getattr(payment, "metadata", {}),
        "sequence_type": getattr(payment, "sequence_type", None),
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
        # updates["mode_of_payment"] = "Mollie"  # Temporarily commented out to fix cancel button issue
        pass

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

            # Link customer to donor (webhook user has Donor write permission)
            donor_doc.customer = customer
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
        company = settings.company or frappe.defaults.get_global_default("company")

        # Get donation receivable account from settings (for party tracking)
        donation_account = settings.donation_receivable_account
        if not donation_account:
            donation_account = frappe.get_value("Company", company, "default_receivable_account")

        # Get bank account (Mollie) from the canonical config source, then fall
        # back to a "Mollie" named account, then the company default.
        # mollie_bank_account was migrated off Verenigingen Settings (patch v2_1)
        # to Mollie Settings, so reading it from `settings` here always returned
        # None and silently ignored a configured account.
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
            get_mollie_config,
        )

        bank_account = get_mollie_config().get_settings().get("mollie_bank_account")
        if not bank_account:
            bank_account = frappe.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
        if not bank_account:
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
        record_reference = _extract_record_reference_from_mollie_data(mollie_data, mollie_data["payment_id"])

        # Get the actual customer name (not the customer ID) for proper display
        customer_doc = frappe.get_doc("Customer", customer)
        display_name = customer_doc.customer_name or donor_doc.donor_name or "Unknown"

        # Set cost center based on donation purpose to satisfy P&L account requirements
        cost_center = get_appropriate_cost_center(donation, company)

        # Ensure amount is properly formatted as Decimal/float
        amount = float(donation.amount) if donation.amount else 0.0

        # Create Payment Entry for donation (Receive type with party tracking)
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "paid_amount": amount,
                "received_amount": amount,
                "reference_no": mollie_data["payment_id"],
                "reference_date": frappe.utils.getdate(),
                "company": company,
                "paid_from": donation_account,  # Money comes FROM receivable account (party account)
                "paid_to": bank_account,  # Money goes TO Mollie bank account
                "mode_of_payment": "Mollie",  # Re-enabled after fixing HRMS override issue
                "cost_center": cost_center,  # Required for P&L accounts
                "title": f"{display_name} - {record_reference}",
                "remarks": f"Payment for {record_reference} via Mollie ({mollie_data.get('method', 'Unknown method')}) - {donor_doc.donor_name}",
            }
        )

        # Use proper webhook user permissions - no bypass needed
        try:
            pe.insert()
            pe.submit()
            frappe.logger().info("✅ Created Payment Entry: %s", pe.name)
            return pe
        except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
            # Race condition: another webhook created the PE between our check and insert.
            #
            # patches/v2_1/add_mollie_payment_entry_unique_index.py is INTENDED
            # to add a composite UNIQUE INDEX on (reference_no, payment_type,
            # party) as this guard's DB-level backstop -- a multi-column unique
            # isn't expressible via DocType `unique: 1`, so a collision on it
            # would classify as UniqueValidationError, not DuplicateEntryError
            # (unrelated classes -- see #699), which DuplicateEntryError alone
            # would miss.
            #
            # That index is NOT currently present, on either veg11 or
            # test_site_1 (checked via `SHOW INDEX`): the patch bails out
            # without creating it whenever pre-existing duplicate Mollie
            # references are found (it did, on both), and because the patch is
            # recorded in Patch Log as already run, Frappe will not retry it.
            # So today this whole `except` branch is unreachable in practice --
            # Payment Entry's only real unique constraints are `PRIMARY` and
            # `eboekhouden_mutation_nr`, and this code path sets neither. Kept
            # anyway because it is correct once the index exists and harmless
            # while it doesn't; see the follow-up issue for actually landing
            # the index (clear the stale Patch Log entries, resolve the
            # existing duplicate Payment Entries, re-run the patch).
            frappe.logger().info("⚠️ Duplicate Payment Entry detected, fetching existing")
            existing_pe = frappe.db.get_value(
                "Payment Entry",
                {"reference_no": mollie_data["payment_id"], "party": customer},
                "name",
            )
            if existing_pe:
                return frappe.get_doc("Payment Entry", existing_pe)
            frappe.logger().error("❌ Duplicate error but no existing PE found")
            return None

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
        company = settings.company or frappe.defaults.get_global_default("company")

        # Resolve Customer Group via the shared helper. The previous code
        # tried "Individual" then "any leaf" then "All Customer Groups" (the
        # last branch is the group-node bug); the resolver does the safe
        # version (Selling Settings → "Individual" leaf → any leaf → throw).
        customer_group = resolve_non_group_customer_group()

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

        # Webhook user has Customer create permission via role
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


def find_member_for_payment(payment_id, payment):
    """
    Find member record associated with this payment

    Matching strategy:
    1. By subscription_id if this is a subscription payment
    2. By customer_id + timestamp window for regular member payments
    3. By payment metadata if available
    """
    try:
        # Method 1: Direct subscription payment
        if hasattr(payment, "subscription_id") and payment.subscription_id:
            frappe.logger().info(f"🔍 Looking for member with subscription_id: {payment.subscription_id}")
            member_name = frappe.db.get_value(
                "Member", {"mollie_subscription_id": payment.subscription_id}, "name"
            )
            if member_name:
                frappe.logger().info(f"✅ Found member via subscription_id: {member_name}")
                return frappe.get_doc("Member", member_name)

        # Method 2: By customer_id (for one-time member payments)
        if hasattr(payment, "customer_id") and payment.customer_id:
            frappe.logger().info(f"🔍 Looking for member with customer_id: {payment.customer_id}")
            member_name = frappe.db.get_value("Member", {"mollie_customer_id": payment.customer_id}, "name")
            if member_name:
                frappe.logger().info(f"✅ Found member via customer_id: {member_name}")
                return frappe.get_doc("Member", member_name)

        # Method 3: Check metadata for member_id
        if hasattr(payment, "metadata") and payment.metadata:
            metadata = payment.metadata if isinstance(payment.metadata, dict) else {}
            member_id = metadata.get("member_id")
            if member_id and frappe.db.exists("Member", member_id):
                frappe.logger().info(f"✅ Found member via metadata: {member_id}")
                return frappe.get_doc("Member", member_id)

        frappe.logger().info(f"❌ No member found for payment {payment_id}")
        return None

    except Exception as e:
        frappe.logger().error(f"❌ Error finding member for payment {payment_id}: {e}")
        return None


def process_successful_member_payment(member, payment):
    """
    Process successful member subscription payment
    """
    try:
        frappe.logger().info(f"🔄 Processing successful payment for member {member.name}")

        # Extract payment data
        mollie_data = extract_mollie_payment_data(payment)

        # Update member payment history
        member.append(
            "payment_history",
            {
                "payment_date": frappe.utils.getdate(),
                "amount": _validate_payment_amount(payment),
                "payment_method": "Mollie",
                "payment_reference": payment.id,
                "payment_status": "Paid",
                "mollie_payment_id": payment.id,
                "mollie_subscription_id": getattr(payment, "subscription_id", None),
                "remarks": f"Subscription payment via {mollie_data.get('method', 'Unknown')}",
            },
        )

        # Update next payment date if this is a subscription
        if hasattr(payment, "subscription_id") and payment.subscription_id:
            # Get subscription details to calculate next payment date
            from verenigingen.verenigingen_payments.mollie.services.subscription_service import (
                SubscriptionService,
            )

            subscription_service = SubscriptionService()

            try:
                sub_status = subscription_service.get_subscription_status(
                    member.mollie_customer_id, payment.subscription_id
                )
                if sub_status.get("next_payment_date"):
                    member.next_payment_date = sub_status["next_payment_date"]

            except Exception as e:
                frappe.logger().warning(f"⚠️ Could not update next payment date: {e}")

        member.save()  # Webhook user has proper permissions via role assignment

        frappe.logger().info(f"✅ Successfully processed member payment for {member.name}")

        return {
            "member_id": member.name,
            "payment_id": payment.id,
            "amount": mollie_data.get("amount"),
            "method": mollie_data.get("method"),
            "status": "processed",
        }

    except Exception as e:
        frappe.logger().error(f"❌ Error processing member payment: {e}")
        frappe.log_error(f"Member payment processing failed: {e}", "Member Payment Processing")
        raise


def process_failed_payment(payment_id, payment):
    """
    Process failed payment for both donations and member subscriptions
    """
    try:
        frappe.logger().info(f"🔄 Processing failed payment {payment_id}")

        # Extract payment data
        mollie_data = extract_mollie_payment_data(payment)

        results = {
            "payment_id": payment_id,
            "status": payment.status,
            "amount": mollie_data.get("amount"),
            "method": mollie_data.get("method"),
            "processed_records": [],
        }

        # Try to find related donation first
        donation = find_donation_for_payment(payment_id, payment)
        if donation:
            frappe.logger().info(f"📝 Recording failed payment for donation {donation.name}")

            # Add failed payment to donation history
            donation.append(
                "payments",
                {
                    "payment_date": frappe.utils.getdate(),
                    "amount": donation.amount,
                    "payment_method": "Mollie",
                    "payment_id": payment_id,
                    "payment_reference": payment_id,
                    "payment_status": "Cancelled",
                    "mollie_payment_id": payment_id,
                    "remarks": f"Payment failed: {payment.status}",
                },
            )

            donation.save()  # Webhook user has proper permissions via role assignment
            results["processed_records"].append(
                {"type": "donation", "id": donation.name, "status": "failed_payment_recorded"}
            )

        # Try to find related member
        member = find_member_for_payment(payment_id, payment)
        if member:
            frappe.logger().info(f"📝 Recording failed payment for member {member.name}")

            # NOTE: do NOT call frappe.db.begin() here. This function already runs
            # inside Frappe's implicit request/webhook transaction, and on MariaDB in
            # v16 issuing a fresh START TRANSACTION raises "This statement can cause
            # implicit commit". The explicit commit()/rollback() below provide the
            # required atomicity within the existing transaction.
            try:
                # Add failed payment to member history with subscription ID
                member.append(
                    "payment_history",
                    {
                        "posting_date": frappe.utils.getdate(),
                        "payment_date": frappe.utils.getdate(),
                        "amount": _validate_payment_amount(payment),
                        "payment_method": "Mollie",
                        "payment_status": "Cancelled",
                        "transaction_type": "Subscription Payment",
                        "notes": f"Mollie payment {payment_id} (subscription {getattr(payment, 'subscription_id', None)}) failed: {payment.status}",
                    },
                )

                # Handle subscription failures
                if hasattr(payment, "subscription_id") and payment.subscription_id:
                    # Check if subscription needs status update
                    if payment.status == "failed":
                        # Get current failure count BEFORE adding this failure to prevent race condition
                        current_failure_count = _get_subscription_failure_count(
                            member.name, payment.subscription_id
                        )
                        new_failure_count = (
                            current_failure_count + 1
                        )  # Account for the failure we're about to save

                        frappe.logger().info(
                            f"📊 Failure count for subscription {payment.subscription_id}: {current_failure_count} -> {new_failure_count}"
                        )

                        # Save the failure record within transaction
                        member.save()  # Webhook user has proper permissions via role assignment
                        frappe.db.commit()

                        # Trigger member notification with accurate failure count
                        _notify_member_of_payment_failure(member, payment, new_failure_count)

                        results["processed_records"].append(
                            {"type": "member", "id": member.name, "status": "failed_payment_recorded"}
                        )
                        # Return the populated results (a bare `return` here would hand
                        # the caller None on the most common subscription-failure path).
                        return results  # Early return - transaction already committed

                # Save member record within transaction
                member.save()  # Webhook user has proper permissions via role assignment
                frappe.db.commit()

                results["processed_records"].append(
                    {"type": "member", "id": member.name, "status": "failed_payment_recorded"}
                )

            except Exception as member_error:
                frappe.db.rollback()
                frappe.logger().error(f"❌ Failed to save member payment failure: {member_error}")
                # Continue processing - don't fail entire webhook for one member save error

        if not donation and not member:
            frappe.logger().warning(f"⚠️ No donation or member found for failed payment {payment_id}")
            results["warning"] = "No associated record found"

        frappe.logger().info(f"✅ Failed payment processing complete for {payment_id}")
        return results

    except Exception as e:
        frappe.logger().error(f"❌ Error processing failed payment {payment_id}: {e}")
        frappe.log_error(f"Failed payment processing error: {e}", "Failed Payment Processing")

        # Return success to Mollie to prevent webhook retries
        # Critical payment info is already logged for manual review
        return {
            "payment_id": payment_id,
            "status": "processing_error",
            "error": str(e),
            "message": "Error logged for manual review - webhook acknowledged",
        }


def _get_subscription_failure_count(member_name, subscription_id):
    """
    Get failure count atomically from database to prevent race conditions

    Args:
        member_name: Member document name
        subscription_id: Mollie subscription ID

    Returns:
        int: Number of failed payments for this subscription
    """
    try:
        # Query the Member Payment History child table directly
        failure_count = frappe.db.count(
            "Member Payment History",
            {
                "parent": member_name,
                "payment_status": "Cancelled",
                "notes": ["like", f"%subscription {subscription_id}%"],
            },
        )

        frappe.logger().info(f"🔍 Atomic failure count query for {member_name}: {failure_count}")
        return failure_count

    except Exception as e:
        frappe.logger().error(f"❌ Error counting subscription failures: {e}")
        return 0  # Safe fallback


def _validate_payment_amount(payment):
    """
    Safely extract and validate payment amount with comprehensive error handling

    Args:
        payment: Mollie payment object

    Returns:
        float: Payment amount or 0.0 if invalid/unavailable

    Note:
        - Negative amounts are rejected (logged as error, returns 0.0)
        - Amounts over €100,000 are logged as unusual (but still processed)
    """
    # Maximum reasonable donation/payment amount (€100,000)
    MAX_REASONABLE_AMOUNT = 100000.0

    try:
        payment_id = getattr(payment, "id", "unknown")

        # Handle None payment object
        if not payment:
            frappe.logger().warning("⚠️ Payment object is None")
            return 0.0

        amount_obj = getattr(payment, "amount", None)

        # Handle missing amount entirely
        if not amount_obj:
            frappe.logger().warning("⚠️ Payment %s has no amount field", payment_id)
            return 0.0

        # Extract raw value based on format
        raw_value = None

        # Handle dictionary format (API response)
        if isinstance(amount_obj, dict):
            raw_value = amount_obj.get("value", 0)
        # Handle object format (SDK object)
        elif hasattr(amount_obj, "value"):
            raw_value = getattr(amount_obj, "value", 0)
        # Handle direct numeric value
        elif isinstance(amount_obj, (int, float, str)):
            raw_value = amount_obj
        else:
            frappe.logger().error("⚠️ Unknown amount format for payment %s: %s", payment_id, type(amount_obj))
            return 0.0

        # Convert to float
        if raw_value in [None, "", "0", "0.00"]:
            frappe.log_error(f"Zero/empty payment amount for {payment_id}", "Payment Amount Validation Error")
            frappe.throw(_("Payment {0} has zero or empty amount - cannot process").format(payment_id))

        value = float(raw_value)

        # RANGE VALIDATION: Reject negative amounts
        if value < 0:
            frappe.log_error(
                f"Negative payment amount detected: {payment_id} = {value}", "Payment Amount Validation Error"
            )
            frappe.throw(_("Payment {0} has negative amount ({1}) - rejecting").format(payment_id, value))

        # RANGE VALIDATION: Reject zero amounts
        if value == 0.0:
            frappe.log_error(f"Zero payment amount for {payment_id}", "Payment Amount Validation Error")
            frappe.throw(_("Payment {0} has zero amount - cannot process").format(payment_id))

        # RANGE VALIDATION: Log unusually large amounts (but process them)
        if value > MAX_REASONABLE_AMOUNT:
            frappe.logger().warning("⚠️ Payment %s has unusually large amount: €%.2f", payment_id, value)
            frappe.log_error(
                f"Unusually large payment amount: {payment_id} = €{value:.2f}", "Payment Amount Warning"
            )
            # Still process - just log for review

        return value

    except frappe.ValidationError:
        # Re-raise validation errors (from frappe.throw)
        raise
    except (ValueError, AttributeError, TypeError) as e:
        frappe.log_error(
            f"Payment amount validation error for {getattr(payment, 'id', 'unknown')}: {e}",
            "Payment Amount Validation Error",
        )
        frappe.throw(
            _("Invalid payment amount format for payment {0}").format(getattr(payment, "id", "unknown"))
        )


def _validate_webhook_signature():
    """
    Validate Mollie webhook signature using webhook secret key.

    NOTE: This is a STRICT HMAC validator that REQUIRES a signature header,
    distinct from the lenient ``verify_mollie_webhook_signature`` used by the
    active ``authenticate_mollie_webhook`` path. It currently has no production
    caller (only behavioural tests exercise it). Kept as a maintained utility
    pending a decision to wire it in or remove it.

    Raises:
        frappe.PermissionError: If signature validation fails
    """
    try:
        # Get request data
        request_body = frappe.request.get_data(as_text=True) if frappe.request else ""
        signature_header = frappe.request.headers.get("X-Mollie-Signature") if frappe.request else None

        if not signature_header:
            frappe.logger().warning("⚠️ No X-Mollie-Signature header found in webhook request")
            frappe.throw("Missing webhook signature", frappe.PermissionError)

        # Get webhook secret from Mollie Settings
        mollie_settings = frappe.get_single("Mollie Settings")
        webhook_secret = mollie_settings.get_webhook_secret()

        if not webhook_secret:
            frappe.logger().error("❌ No webhook secret configured in Mollie Settings")
            frappe.throw("Webhook secret not configured", frappe.PermissionError)

        # Calculate expected signature
        import hashlib
        import hmac

        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"), request_body.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Extract signature from header (remove "sha256=" prefix if present)
        if signature_header.startswith("sha256="):
            received_signature = signature_header[7:]  # Remove "sha256=" prefix
        else:
            received_signature = signature_header

        # Compare signatures (constant time comparison for security)
        if not hmac.compare_digest(received_signature, expected_signature):
            frappe.logger().error("❌ Webhook signature validation failed")
            frappe.logger().error(f"Expected: {expected_signature[:10]}...")
            frappe.logger().error(f"Received: {received_signature[:10]}...")
            frappe.throw("Invalid webhook signature", frappe.PermissionError)

        frappe.logger().info("✅ Webhook signature validated successfully")

    except frappe.PermissionError:
        raise  # Re-raise permission errors
    except Exception as e:
        frappe.logger().error(f"❌ Webhook signature validation error: {e}")
        frappe.throw(f"Webhook validation failed: {e}", frappe.PermissionError)


def _notify_member_of_payment_failure(member, payment, failure_count):
    """
    Notify member of payment failure and take appropriate action
    """
    try:
        # Import email service
        from verenigingen.services.communication.email_service import get_email_service

        frappe.logger().info(
            f"📧 Notifying member {member.name} of payment failure (attempt #{failure_count})"
        )

        # Determine email template based on failure count
        if failure_count == 1:
            template_name = "payment_failure_first"
        elif failure_count == 2:
            template_name = "payment_failure_second"
        else:
            template_name = "payment_failure_final"

        # Check if template exists, fallback to generic if not
        if not frappe.db.exists("Email Template", template_name):
            template_name = "payment_failure_generic"

        # If generic template doesn't exist either, log and continue
        if not frappe.db.exists("Email Template", template_name):
            frappe.logger().warning("⚠️ No payment failure email template found")
            return

        # Send notification email
        email_service = get_email_service()

        context = {
            "member": member,
            "payment": payment,
            "failure_count": failure_count,
            "payment_status": payment.status,
            "amount": _validate_payment_amount(payment),
            "next_payment_date": member.next_payment_date,
        }

        # Map template to notification key
        notification_key_map = {
            "payment_failure_first": "payment_failure_first",
            "payment_failure_second": "payment_failure_second",
            "payment_failure_final": "payment_failure_final",
            "payment_failure_generic": "payment_failure_first",  # Fallback to first
        }
        notification_key = notification_key_map.get(template_name, "payment_failure_first")

        result = email_service.send_templated_email(
            template_name=template_name,
            recipients=[member.email],
            context=context,
            reference_doctype="Member",
            reference_name=member.name,
            notification_key=notification_key,
        )

        # send_templated_email returns an OperationResult dataclass (which has no
        # dict-style .get); read its .success flag rather than result.get("status"),
        # otherwise this raised AttributeError on every send and logged a spurious
        # "Payment Notification Error" even when the email went out fine.
        if result.success:
            frappe.logger().info(f"✅ Payment failure notification sent to {member.email}")
        else:
            frappe.logger().warning(f"⚠️ Failed to send payment failure notification: {result.error_message}")

    except Exception as e:
        frappe.logger().error(f"❌ Error sending payment failure notification: {e}")
        frappe.log_error(
            f"Payment failure notification error for member {member.name}: {e}", "Payment Notification Error"
        )
        # Don't raise - notification failure shouldn't stop payment processing
