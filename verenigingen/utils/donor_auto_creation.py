"""
Automatic Donor Creation from Payment Allocations

This module handles automatic creation of donor records when payments
are allocated to donations GL accounts from unknown customers.
"""

import frappe
from frappe import _
from frappe.utils import flt, now


def process_payment_for_donor_creation(doc, method=None):
    """
    Process Payment Entry or Journal Entry for automatic donor creation

    Called from document hooks for Payment Entry and Journal Entry

    Args:
        doc: Payment Entry or Journal Entry document
        method: Hook method name (not used)
    """
    # Skip if auto-creation is disabled
    settings = frappe.get_single("Verenigingen Settings")
    if not settings.auto_create_donors or not settings.donations_gl_account:
        return

    # Skip if this is a test or sync operation
    if hasattr(doc, "flags") and (doc.flags.in_test or doc.flags.ignore_donor_creation):
        return

    try:
        if doc.doctype == "Payment Entry":
            process_payment_entry(doc, settings)
        elif doc.doctype == "Journal Entry":
            process_journal_entry(doc, settings)

    except Exception as e:
        frappe.log_error(
            f"Error processing {doc.doctype} {doc.name} for donor creation: {str(e)}",
            "Donor Auto-Creation Error",
        )


def process_payment_entry(payment_entry, settings):
    """
    Process Payment Entry for donor creation

    Args:
        payment_entry: Payment Entry document
        settings: Verenigingen Settings document
    """
    # Only process receipts (incoming payments)
    if payment_entry.payment_type != "Receive":
        return

    # Check if payment has a party (customer/supplier)
    if not payment_entry.party or payment_entry.party_type != "Customer":
        return

    # Check if payment is allocated to donations GL account
    donations_allocated = False
    total_donation_amount = 0

    # Check references (allocated invoices/journal entries)
    for reference in payment_entry.references:
        if reference.reference_doctype == "Journal Entry":
            je_doc = frappe.get_doc("Journal Entry", reference.reference_name)
            for account in je_doc.accounts:
                if account.account == settings.donations_gl_account and account.credit > 0:
                    donations_allocated = True
                    total_donation_amount += account.credit
                    break

    # Check accounts directly (for direct GL postings)
    for account in getattr(payment_entry, "accounts", []):
        if account.account == settings.donations_gl_account:
            donations_allocated = True
            total_donation_amount += abs(account.paid_amount or 0)

    # Also check paid_to account for simple direct donations
    if payment_entry.paid_to == settings.donations_gl_account:
        donations_allocated = True
        total_donation_amount = payment_entry.paid_amount

    if not donations_allocated:
        return

    # Check minimum amount threshold
    if flt(total_donation_amount) < flt(settings.minimum_donation_amount):
        return

    # Get customer details
    customer_name = payment_entry.party
    customer_doc = frappe.get_doc("Customer", customer_name)

    # Check if customer group is eligible
    if not is_customer_group_eligible(customer_doc.customer_group, settings):
        return

    # Check if donor already exists for this customer
    if has_existing_donor(customer_name):
        return

    # Create donor record
    create_donor_from_customer(customer_doc, total_donation_amount, payment_entry.name)


def process_journal_entry(journal_entry, settings):
    """
    Process Journal Entry for donor creation

    Args:
        journal_entry: Journal Entry document
        settings: Verenigingen Settings document
    """
    # Check if journal entry has donations GL account credit entries
    donations_amount = 0
    customer_accounts = []

    for account in journal_entry.accounts:
        # Check for donations account credit
        if account.account == settings.donations_gl_account and account.credit > 0:
            donations_amount += account.credit

        # Check for customer account debits (indicating payment from customer)
        if account.party_type == "Customer" and account.debit > 0:
            customer_accounts.append({"customer": account.party, "amount": account.debit})

    if not donations_amount or not customer_accounts:
        return

    # Check minimum amount threshold
    if flt(donations_amount) < flt(settings.minimum_donation_amount):
        return

    # Process each customer account
    for customer_account in customer_accounts:
        customer_name = customer_account["customer"]

        try:
            customer_doc = frappe.get_doc("Customer", customer_name)

            # Check if customer group is eligible
            if not is_customer_group_eligible(customer_doc.customer_group, settings):
                continue

            # Check if donor already exists for this customer
            if has_existing_donor(customer_name):
                continue

            # Create donor record
            create_donor_from_customer(customer_doc, customer_account["amount"], journal_entry.name)

        except Exception as e:
            frappe.log_error(
                f"Error processing customer {customer_name} from journal entry {journal_entry.name}: {str(e)}",
                "Donor Creation Customer Error",
            )


def is_customer_group_eligible(customer_group, settings):
    """
    Check if customer group is eligible for automatic donor creation

    Args:
        customer_group: Customer group name
        settings: Verenigingen Settings document

    Returns:
        bool: True if eligible, False otherwise
    """
    # If no specific groups configured, allow all
    if not settings.donor_customer_groups:
        return True

    # Parse comma-separated list and check if customer group is included
    eligible_groups = [group.strip() for group in settings.donor_customer_groups.split(",")]
    return customer_group in eligible_groups


def has_existing_donor(customer_name):
    """
    Check if a donor record already exists for the given customer

    Args:
        customer_name: Customer name/ID

    Returns:
        bool: True if donor exists, False otherwise
    """
    # Check by customer link
    if frappe.db.exists("Donor", {"customer": customer_name}):
        return True

    # Check by customer reference field
    if frappe.db.exists("Customer", {"name": customer_name, "custom_donor_reference": ("!=", "")}):
        return True

    return False


def create_donor_from_customer(customer_doc, donation_amount, reference_doc):
    """
    Create a new donor record from customer data

    Args:
        customer_doc: Customer document
        donation_amount: Amount of donation that triggered creation
        reference_doc: Reference document name (Payment Entry or Journal Entry)

    Returns:
        str: Name of created donor record, or None if creation failed
    """
    try:
        # Check if donor already exists (defensive check)
        if has_existing_donor(customer_doc.name):
            frappe.logger().info(f"Donor already exists for customer {customer_doc.name}, skipping creation")
            return None

        # Create donor document
        donor = frappe.new_doc("Donor")

        # Copy basic information from customer
        donor.donor_name = customer_doc.customer_name
        donor.donor_type = "Organization" if customer_doc.customer_type == "Company" else "Individual"

        # Copy contact information (donor_email is required)
        if customer_doc.email_id:
            donor.donor_email = customer_doc.email_id
        else:
            # Generate a placeholder email if none provided
            donor.donor_email = f"donor.{customer_doc.name.lower().replace(' ', '.')}@example.com"

        if customer_doc.mobile_no:
            donor.phone = customer_doc.mobile_no

        # Set customer link
        donor.customer = customer_doc.name

        # Set creation metadata
        donor.created_from_payment = reference_doc
        donor.creation_trigger_amount = donation_amount
        donor.customer_sync_status = "Auto-Created"
        donor.last_customer_sync = now()

        # Set flags to prevent validation loops
        donor.flags.ignore_customer_sync = True
        donor.flags.from_auto_creation = True

        # Insert donor
        donor.insert()

        # Add creation note after insertion
        donor.add_comment(
            comment_type="Info",
            text=f"Automatically created from payment allocation to donations account. "
            f"Reference: {reference_doc}, Amount: {donation_amount}",
        )

        # Update customer with donor reference (if field exists)
        try:
            frappe.db.set_value("Customer", customer_doc.name, "custom_donor_reference", donor.name)
        except Exception as e:
            frappe.logger().warning(
                f"Could not set custom_donor_reference on customer {customer_doc.name}: {str(e)}"
            )

        frappe.logger().info(
            f"Auto-created donor {donor.name} for customer {customer_doc.name} "
            f"from {reference_doc} with amount {donation_amount}"
        )

        return donor.name

    except Exception as e:
        frappe.log_error(
            f"Error creating donor for customer {customer_doc.name}: {str(e)}", "Donor Auto-Creation Error"
        )
        return None


@frappe.whitelist()
def get_auto_creation_settings():
    """
    Get current auto-creation settings for display

    Returns:
        dict: Auto-creation configuration
    """
    settings = frappe.get_single("Verenigingen Settings")

    return {
        "enabled": settings.auto_create_donors,
        "donations_gl_account": settings.donations_gl_account,
        "eligible_customer_groups": settings.donor_customer_groups,
        "minimum_amount": settings.minimum_donation_amount,
    }


@frappe.whitelist()
def get_auto_creation_stats():
    """
    Get statistics on auto-created donors

    Returns:
        dict: Statistics on auto-created donors
    """
    try:
        # Count auto-created donors
        auto_created_count = frappe.db.count("Donor", filters={"customer_sync_status": "Auto-Created"})

        # Get recent auto-creations
        recent_creations = frappe.db.sql(
            """
            SELECT
                name,
                donor_name,
                customer,
                creation_trigger_amount,
                created_from_payment,
                creation
            FROM `tabDonor`
            WHERE customer_sync_status = 'Auto-Created'
            ORDER BY creation DESC
            LIMIT 10
        """,
            as_dict=True,
        )

        # Get total amount from auto-created donors
        total_amount_result = frappe.db.sql(
            """
            SELECT COALESCE(SUM(creation_trigger_amount), 0) as total_amount
            FROM `tabDonor`
            WHERE customer_sync_status = 'Auto-Created'
            AND creation_trigger_amount IS NOT NULL
        """
        )

        total_amount = total_amount_result[0][0] if total_amount_result else 0

        return {
            "auto_created_count": auto_created_count,
            "recent_creations": recent_creations,
            "total_trigger_amount": total_amount,
        }

    except Exception as e:
        frappe.log_error(f"Error getting auto-creation stats: {str(e)}", "Auto-Creation Stats Error")
        return {"error": str(e)}


@frappe.whitelist()
def test_auto_creation_conditions(customer_name, amount):
    """
    Test if auto-creation conditions would be met for a given customer and amount

    Args:
        customer_name: Customer name to test
        amount: Donation amount to test

    Returns:
        dict: Test results with detailed conditions
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")

        results = {"would_create": False, "conditions": {}}

        # Check if auto-creation is enabled
        results["conditions"]["auto_creation_enabled"] = bool(settings.auto_create_donors)
        if not settings.auto_create_donors:
            results["conditions"]["failure_reason"] = "Auto-creation is disabled"
            return results

        # Check if donations GL account is configured
        results["conditions"]["donations_account_configured"] = bool(settings.donations_gl_account)
        if not settings.donations_gl_account:
            results["conditions"]["failure_reason"] = "Donations GL account not configured"
            return results

        # Check customer exists
        customer_exists = frappe.db.exists("Customer", customer_name)
        results["conditions"]["customer_exists"] = customer_exists
        if not customer_exists:
            results["conditions"]["failure_reason"] = f"Customer {customer_name} does not exist"
            return results

        customer_doc = frappe.get_doc("Customer", customer_name)

        # Check customer group eligibility
        group_eligible = is_customer_group_eligible(customer_doc.customer_group, settings)
        results["conditions"]["customer_group_eligible"] = group_eligible
        results["conditions"]["customer_group"] = customer_doc.customer_group
        if not group_eligible:
            results["conditions"][
                "failure_reason"
            ] = f"Customer group {customer_doc.customer_group} not eligible"
            return results

        # Check minimum amount
        amount_sufficient = flt(amount) >= flt(settings.minimum_donation_amount)
        results["conditions"]["amount_sufficient"] = amount_sufficient
        results["conditions"]["minimum_required"] = settings.minimum_donation_amount
        results["conditions"]["amount_provided"] = amount
        if not amount_sufficient:
            results["conditions"][
                "failure_reason"
            ] = f"Amount {amount} below minimum {settings.minimum_donation_amount}"
            return results

        # Check if donor already exists
        donor_exists = has_existing_donor(customer_name)
        results["conditions"]["donor_already_exists"] = donor_exists
        if donor_exists:
            results["conditions"]["failure_reason"] = "Donor already exists for this customer"
            return results

        # All conditions met
        results["would_create"] = True
        results["conditions"]["all_conditions_met"] = True

        return results

    except Exception as e:
        return {"error": str(e)}
