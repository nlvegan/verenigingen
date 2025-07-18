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

    # DEPRECATED: Subscription period calculator has been replaced by dues schedule system
    # try:
    #     from verenigingen.utils.subscription_period_calculator import (
    #         format_subscription_period_description,
    #         get_aligned_subscription_dates,
    #     )
    # except ImportError:
    # Variables would be used if subscription utilities were imported

    settings = frappe.get_single("Verenigingen Settings")

    # Create or get customer
    if not member.customer:
        customer = create_customer_for_member(member)
        member.db_set("customer", customer.name)

    membership_type = frappe.get_doc("Membership Type", membership.membership_type)

    # DEPRECATED: Subscription period calculation replaced by dues schedule system
    # subscription_dates = None
    # if get_aligned_subscription_dates and membership.start_date:
    #     subscription_dates = get_aligned_subscription_dates(
    #         membership.start_date, membership_type, has_application_invoice=True
    #     )

    # Determine invoice description based on amount type and dues schedule
    description = f"Membership Fee - {membership_type.membership_type_name}"
    if hasattr(membership, "uses_custom_amount") and membership.uses_custom_amount:
        if amount > membership_type.amount:
            description += " (Supporter Contribution)"
        elif amount < membership_type.amount:
            description += " (Reduced Rate)"

    # DEPRECATED: Subscription period description replaced by dues schedule system
    # Add billing period to description if available
    billing_period = getattr(
        membership_type, "billing_period", getattr(membership_type, "subscription_period", "Annual")
    )
    if billing_period and billing_period != "Annual":
        description += f" - {billing_period} Billing"

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
                "item_code": get_or_create_membership_item(membership_type),
                "qty": 1,
                "rate": amount,
                "description": description,
            }
        ],
        "remarks": f"Membership application invoice for {member.full_name}",
    }

    # DEPRECATED: Subscription period dates replaced by dues schedule system
    # The dues schedule system handles billing periods automatically
    # No need to set subscription_period_start/end fields

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
    """Create customer record for member"""
    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": member.full_name,
            "customer_type": "Individual",
            "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group")
            or "Individual",
            "territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
            "email_id": member.email,
            "mobile_no": member.contact_number or "",
        }
    )
    customer.insert(ignore_permissions=True)
    return customer


def get_or_create_membership_item(membership_type):
    """Get or create item for membership type"""
    item_code = f"MEMB-{membership_type.name}"

    if not frappe.db.exists("Item", item_code):
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": item_code,
                "item_name": f"Membership - {membership_type.membership_type_name}",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "is_sales_item": 1,
                "is_purchase_item": 0,
            }
        )
        item.insert()

    return item_code


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
    base_amount = float(membership_type.amount)
    final_amount = base_amount
    discounts_applied = []

    # Student discount
    if data.get("is_student") and membership_type.student_discount_percentage:
        discount_amount = base_amount * (membership_type.student_discount_percentage / 100)
        final_amount -= discount_amount
        discounts_applied.append(
            {
                "type": "Student Discount",
                "percentage": membership_type.student_discount_percentage,
                "amount": discount_amount,
            }
        )

    # Early bird discount
    if data.get("early_bird_eligible") and membership_type.early_bird_discount:
        discount_amount = base_amount * (membership_type.early_bird_discount / 100)
        final_amount -= discount_amount
        discounts_applied.append(
            {
                "type": "Early Bird Discount",
                "percentage": membership_type.early_bird_discount,
                "amount": discount_amount,
            }
        )

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
        amount = membership_type.amount

    return create_membership_invoice_with_amount(member, membership, amount)


def format_currency_for_display(amount, currency="EUR"):
    """Format currency amount for display"""
    return frappe.utils.fmt_money(amount, currency=currency)
