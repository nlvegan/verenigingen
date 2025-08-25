"""
Payment processing utilities for membership applications
"""
import frappe
from frappe import _
from frappe.utils import add_days, today


def create_membership_invoice_with_amount(member, membership, amount):
    """Create invoice with specific amount (custom or standard)"""
    try:
        from verenigingen.utils import DutchTaxExemptionHandler
    except ImportError:
        DutchTaxExemptionHandler = None

    # Legacy subscription utilities have been replaced by dues schedule system

    settings = frappe.get_single("Verenigingen Settings")

    # Create or get customer
    if not member.customer:
        customer = create_customer_for_member(member)
        member.db_set("customer", customer.name)

    membership_type = frappe.get_doc("Membership Type", membership.membership_type)

    # Legacy subscription period calculation replaced by dues schedule system

    # Calculate coverage period for the first billing cycle
    from frappe.utils import add_months, add_years, getdate

    billing_period = getattr(membership_type, "billing_period", "Annual")
    period_start = today()

    # Calculate period end based on billing frequency
    if billing_period == "Daily":
        period_end = add_days(period_start, 1)
    elif billing_period == "Monthly":
        period_end = add_months(period_start, 1)
    elif billing_period == "Quarterly":
        period_end = add_months(period_start, 3)
    elif billing_period == "Biannual":
        period_end = add_months(period_start, 6)
    elif billing_period == "Annual":
        period_end = add_years(period_start, 1)
    elif billing_period == "Custom" and hasattr(membership_type, "billing_period_in_months"):
        months = getattr(membership_type, "billing_period_in_months", 12) or 12
        period_end = add_months(period_start, months)
    else:
        # Default to annual
        period_end = add_years(period_start, 1)

    # Determine invoice description with coverage period
    description = f"Membership Fee - {membership_type.membership_type_name}"
    if hasattr(membership, "uses_custom_amount") and membership.uses_custom_amount:
        # Get suggested amount from template for comparison
        if not membership_type.dues_schedule_template:
            frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
        template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
        suggested_amount = template.suggested_amount or 0

        if amount > suggested_amount:
            description += " (Supporter Contribution)"
        elif amount < suggested_amount:
            description += " (Reduced Rate)"

    # Add coverage period to description
    if billing_period == "Daily":
        description += f" - {billing_period} fee for {period_start}"
    else:
        description += f" - {billing_period} period: {period_start} to {period_end}"

    # Create invoice with dues schedule system
    invoice_data = {
        "doctype": "Sales Invoice",
        "customer": member.customer,
        "member": member.name,
        "membership": membership.name,
        "posting_date": today(),
        "due_date": add_days(today(), 14),
        "items": [
            {
                "item_code": get_membership_item(membership_type),
                "qty": 1,
                "rate": amount,
                "description": description,
            }
        ],
        "remarks": f"Membership application invoice for {member.full_name}\nFirst billing period: {period_start} to {period_end}",
    }

    # The dues schedule system handles billing periods automatically

    invoice = frappe.get_doc(invoice_data)

    # Apply tax exemption if configured
    if settings.tax_exempt_for_contributions and DutchTaxExemptionHandler:
        try:
            handler = DutchTaxExemptionHandler()
            handler.apply_exemption_to_invoice(invoice, "EXEMPT_MEMBERSHIP")
        except Exception as e:
            frappe.log_error(f"Error applying tax exemption: {str(e)}", "Tax Exemption Error")

    invoice.insert(ignore_permissions=True)
    invoice.submit()

    return invoice


def create_customer_for_member(member):
    """Create customer record for member with proper Contact integration"""
    # Validate permissions
    if not frappe.has_permission("Customer", "create"):
        frappe.throw(_("Insufficient permissions to create Customer"))

    if not frappe.has_permission("Contact", "create"):
        frappe.throw(_("Insufficient permissions to create Contact"))

    # Use transaction management for data integrity
    try:
        frappe.db.begin()

        # Create Customer record (without direct email/mobile - these come from Contact via fetch_from)
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": member.full_name,
                "customer_type": "Individual",
                "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group")
                or "Individual",
                "territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
                "member": member.name,  # Direct link to member record
            }
        )
        customer.insert()

        # Create Contact record using existing Dutch name utilities
        contact = create_contact_for_customer(customer, member)
        if not contact:
            frappe.db.rollback()
            frappe.throw(_("Failed to create Contact for Customer"))

        # Set primary contact - ERPNext will automatically populate email_id/mobile_no via fetch_from
        customer.db_set("customer_primary_contact", contact.name, update_modified=False)

        frappe.db.commit()
        frappe.logger().info(
            f"Created Customer {customer.name} with Contact {contact.name} for Member {member.name}"
        )

        return customer

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(
            f"Failed to create Customer for Member {member.name}: {str(e)}", "Customer Creation Error"
        )
        raise


def get_membership_item(membership_type):
    """Get membership item for membership type - requires explicit creation"""
    # Note: membership_item field does not exist in current Membership Type DocType
    # Item creation is handled through membership type controller methods

    # Fallback to membership type's own method if available
    if hasattr(membership_type, "get_or_create_membership_item"):
        return membership_type.get_or_create_membership_item()

    # If no explicit configuration, require manual setup
    frappe.throw(
        f"No membership item configured for membership type '{membership_type.membership_type_name}'. "
        "Please create the item manually through the membership type controller. "
        "Auto-creation has been disabled to ensure proper item configuration."
    )


def process_application_payment(member_name, payment_method, payment_reference=None):
    """Process payment for approved application"""
    member = frappe.get_doc("Member", member_name)

    if member.application_status != "Approved":
        frappe.throw(_("Payment can only be processed for approved applications"))

    # Get the invoice
    invoice = frappe.get_doc("Sales Invoice", member.application_invoice)

    # Create payment entry
    payment_entry = frappe.get_doc(
        {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": member.customer,
            "paid_amount": invoice.grand_total,
            "received_amount": invoice.grand_total,
            "reference_no": payment_reference,
            "reference_date": today(),
            "mode_of_payment": payment_method,
            "references": [
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": invoice.grand_total,
                }
            ],
        }
    )

    payment_entry.insert(ignore_permissions=True)
    payment_entry.submit()

    # Update member payment status
    member.application_payment_status = "Paid"

    # Handle concurrency with retry logic
    try:
        member.save()
    except frappe.TimestampMismatchError:
        # Reload member and retry save once
        member.reload()
        member.application_payment_status = "Paid"
        member.save()

    # Activate membership
    membership = frappe.get_doc("Membership", invoice.membership)
    membership.status = "Active"
    membership.save()

    return payment_entry


def get_payment_methods():
    """Get available payment methods"""
    try:
        payment_methods = frappe.get_all(
            "Mode of Payment", filters={"enabled": 1}, fields=["name", "mode_of_payment"], order_by="name"
        )

        # Add descriptions for common methods
        method_descriptions = {
            "Bank Transfer": "Direct bank transfer (SEPA)",
            "PayPal": "PayPal payment",
            "iDEAL": "iDEAL (Netherlands)",
            "Cash": "Cash payment (in-person only)",
        }

        for method in payment_methods:
            method["description"] = method_descriptions.get(method["name"], "")

        return {"success": True, "payment_methods": payment_methods}

    except Exception as e:
        frappe.log_error(f"Error getting payment methods: {str(e)}")
        return {"success": False, "error": str(e), "payment_methods": []}


def get_payment_instructions_html(invoice, payment_url):
    """Generate HTML for payment instructions"""
    settings = frappe.get_single("Verenigingen Settings")

    # bank_info = ""
    if settings.bank_account_number:
        pass
        # bank_info = """
        # <div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 20px 0;">
        #     <h4>Bank Transfer Details:</h4>
        #     <ul>
        #         <li><strong>Account Number:</strong> {settings.bank_account_number}</li>
        #         <li><strong>Account Name:</strong> {settings.bank_account_name or 'Organization'}</li>
        #         <li><strong>Reference:</strong> {invoice.name}</li>
        #         <li><strong>Amount:</strong> {frappe.utils.fmt_money(invoice.grand_total, currency=invoice.currency)}</li>
        #     </ul>
        # </div>
        # """

    # online_payment = ""
    if payment_url:
        pass
        # online_payment = """
        # <div style="background: #f3e5f5; padding: 15px; border-radius: 8px; margin: 20px 0;">
        #     <h4>Online Payment:</h4>
        #     <p><a href="{payment_url}"
        #          style="background: #673ab7; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
        #         Pay Online
        #     </a></p>
        # </div>
        # """

    return """
    <div style="font-family: Arial, sans-serif;">
        <h3>Payment Instructions</h3>

        <div style="background: #fff3e0; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Invoice Details:</h4>
            <ul>
                <li><strong>Invoice Number:</strong> {invoice.name}</li>
                <li><strong>Amount Due:</strong> {frappe.utils.fmt_money(invoice.grand_total, currency=invoice.currency)}</li>
                <li><strong>Due Date:</strong> {frappe.format_date(invoice.due_date)}</li>
            </ul>
        </div>

        {online_payment}

        {bank_info}

        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h4>Important Notes:</h4>
            <ul>
                <li>Please include the invoice number as reference when making payment</li>
                <li>Your membership will be activated once payment is received</li>
                <li>You will receive a confirmation email after payment</li>
            </ul>
        </div>
    </div>
    """


def calculate_membership_amount_with_discounts(membership_type, data):
    """Calculate membership amount considering any applicable discounts"""
    # Get base amount from template
    if not membership_type.dues_schedule_template:
        frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
    template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
    # Validate suggested amount - allow zero if minimum_amount is also zero (free membership)
    if template.suggested_amount is None:
        frappe.throw(f"Dues Schedule Template '{template.name}' must have a suggested_amount configured")

    if template.suggested_amount < 0:
        frappe.throw(
            f"Dues Schedule Template '{template.name}' cannot have negative suggested_amount: {template.suggested_amount}"
        )

    # Allow zero amounts only if the membership type minimum is also zero (free membership)
    if template.suggested_amount == 0:
        membership_type_minimum = getattr(membership_type, "minimum_amount", None)
        if membership_type_minimum is None or membership_type_minimum > 0:
            frappe.throw(
                f"Dues Schedule Template '{template.name}' has zero suggested_amount but Membership Type '{membership_type.name}' minimum_amount is {membership_type_minimum}. For free memberships, both must be zero."
            )
    base_amount = float(template.suggested_amount)
    final_amount = base_amount
    discounts_applied = []

    # Note: Discount logic has been moved to the Dues Schedule Template system
    # Custom amounts and adjustments are handled through the dues schedule contribution system
    # Legacy student_discount_percentage and early_bird_discount fields do not exist in current Membership Type DocType

    # Ensure minimum amount
    if final_amount < 1:
        final_amount = 1

    return {
        "base_amount": base_amount,
        "final_amount": final_amount,
        "discounts_applied": discounts_applied,
        "total_discount": base_amount - final_amount,
    }


def validate_payment_amount(invoice, received_amount):
    """Validate that the received payment amount is correct"""
    invoice_amount = float(invoice.grand_total)
    received_amount = float(received_amount)

    # Allow small differences due to rounding
    tolerance = 0.01

    if abs(invoice_amount - received_amount) <= tolerance:
        return {"valid": True, "message": "Payment amount is correct"}
    elif received_amount < invoice_amount - tolerance:
        return {
            "valid": False,
            "message": f"Payment amount ({received_amount}) is less than invoice amount ({invoice_amount})",
        }
    else:
        return {
            "valid": True,
            "message": f"Payment amount ({received_amount}) exceeds invoice amount - treating as donation",
            "overpayment": received_amount - invoice_amount,
        }


def create_membership_invoice(member, membership, membership_type, amount=None):
    """Create invoice for membership with optional custom amount"""
    if amount is None:
        # Get default amount from template
        if not membership_type.dues_schedule_template:
            frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
        template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
        amount = template.suggested_amount or 0

    return create_membership_invoice_with_amount(member, membership, amount)


def format_currency_for_display(amount, currency="EUR"):
    """Format currency amount for display"""
    return frappe.utils.fmt_money(amount, currency=currency)


def create_contact_for_customer(customer, member):
    """Create Contact record for Customer with proper Dutch name handling"""
    try:
        from verenigingen.utils.dutch_name_utils import get_full_last_name

        contact = frappe.new_doc("Contact")

        # Use Member's Dutch name fields properly
        contact.first_name = member.first_name
        if hasattr(member, "middle_name") and member.middle_name:
            contact.middle_name = member.middle_name

        # Combine tussenvoegsel + last_name using existing utility
        contact.last_name = get_full_last_name(member.last_name, getattr(member, "tussenvoegsel", None))

        # Add email to email_ids child table (this populates the read-only email_id field via ERPNext)
        if member.email:
            contact.append("email_ids", {"email_id": member.email, "is_primary": 1})

        # Add phone to phone_nos child table (this populates the read-only mobile_no field via ERPNext)
        if member.contact_number:
            contact.append("phone_nos", {"phone": member.contact_number, "is_primary_mobile_no": 1})

        # Link to customer
        contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})

        # Insert with proper permissions (no bypass)
        contact.insert()

        frappe.logger().info(
            f"Created Contact {contact.name} for Customer {customer.name} (Member: {member.name})"
        )
        return contact

    except Exception as e:
        frappe.log_error(
            f"Error creating Contact for Customer {customer.name} (Member: {member.name}): {str(e)}",
            "Customer Contact Creation Error",
        )
        return None
