"""
Enhanced membership application API with flexible contribution system
"""

import json

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, today

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, public_api, standard_api


@frappe.whitelist(allow_guest=True)
@public_api(operation_type=OperationType.PUBLIC)
def submit_enhanced_application():
    """Submit enhanced membership application with flexible contribution"""
    try:
        # Get form data
        data = frappe.form_dict

        # Validate required fields
        validation_result = validate_application_data(data)
        if not validation_result["valid"]:
            return {"success": False, "error": validation_result["error"]}

        # Process the application
        application_result = process_enhanced_application(data)

        if application_result["success"]:
            return {
                "success": True,
                "application_id": application_result["application_id"],
                "message": _("Application submitted successfully"),
                "next_steps": application_result.get("next_steps", []),
            }
        else:
            return {"success": False, "error": application_result.get("error", "Unknown error occurred")}

    except Exception as e:
        frappe.log_error(
            f"Enhanced membership application error: {str(e)}", "Enhanced Membership Application"
        )
        return {
            "success": False,
            "error": _("An error occurred while processing your application. Please try again."),
        }


def validate_application_data(data):
    """Validate the enhanced application data"""
    required_fields = [
        "first_name",
        "last_name",
        "email",
        "address_line1",
        "postal_code",
        "city",
        "country",
        "membership_type",
        "contribution_amount",
        "payment_method",
    ]

    for field in required_fields:
        if not data.get(field):
            return {"valid": False, "error": f"Required field missing: {field.replace('_', ' ').title()}"}

    # Validate email format
    email = data.get("email")
    if not frappe.utils.validate_email_address(email):
        return {"valid": False, "error": "Invalid email address"}

    # Check if email already exists
    existing_member = frappe.db.get_value("Member", {"email": email})
    if existing_member:
        return {"valid": False, "error": "A member with this email already exists"}

    # Validate membership type
    membership_type = data.get("membership_type")
    if not frappe.db.exists("Membership Type", membership_type):
        return {"valid": False, "error": "Invalid membership type"}

    # Validate contribution amount
    contribution_validation = validate_contribution_amount(
        membership_type,
        data.get("contribution_amount"),
        data.get("contribution_mode"),
        data.get("selected_tier"),
        data.get("base_multiplier"),
    )

    if not contribution_validation["valid"]:
        return {"valid": False, "error": contribution_validation["error"]}

    return {"valid": True}


def validate_contribution_amount(
    membership_type_name, amount, contribution_mode=None, selected_tier=None, base_multiplier=None
):
    """Validate contribution amount against membership type constraints"""
    try:
        amount = flt(amount)
        mt_doc = frappe.get_doc("Membership Type", membership_type_name)

        # Get minimum and maximum constraints from template
        template_values = {}
        if mt_doc.dues_schedule_template:
            try:
                template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)
                template_values = {
                    "minimum_contribution": template.minimum_amount or 0,
                    "suggested_contribution": template.dues_rate or template.suggested_amount or 0,
                    "fee_slider_max_multiplier": 10.0,
                    "maximum_contribution": 0,
                }
            except Exception:
                pass

        min_amount = template_values.get("minimum_contribution", 0) or (
            mt_doc.minimum_amount * 0.3 if mt_doc.minimum_amount else 5.0
        )
        # Use template amount directly, with fallback to reasonable default
        suggested_amount = template_values.get("suggested_contribution", 0) or 15.0
        max_multiplier = template_values.get("fee_slider_max_multiplier", 10.0)
        max_amount = template_values.get("maximum_contribution", 0) or (suggested_amount * max_multiplier)

        # Validate against constraints
        if amount < min_amount:
            return {"valid": False, "error": f"Amount cannot be less than minimum: €{min_amount:.2f}"}

        if max_amount and amount > max_amount:
            return {"valid": False, "error": f"Amount cannot be more than maximum: €{max_amount:.2f}"}

        return {"valid": True, "amount": amount}

    except Exception as e:
        frappe.log_error(f"Error validating contribution amount: {str(e)}")
        return {"valid": False, "error": "Error validating contribution amount"}


def process_enhanced_application(data):
    """Process the enhanced membership application"""
    try:
        # Create membership application
        application = create_membership_application(data)

        # Create initial dues schedule
        dues_schedule = create_initial_dues_schedule(application, data)

        # Handle payment setup
        setup_payment_method(application, data)

        # Create invoice for first payment
        invoice = create_first_payment_invoice(application, dues_schedule, data)

        # Send confirmation email
        send_application_confirmation(application, invoice)

        return {
            "success": True,
            "application_id": application.name,
            "invoice_id": invoice.name if invoice else None,
            "next_steps": [
                _("Check your email for confirmation and payment instructions"),
                _("Complete your first payment to activate membership"),
                _("You will receive a welcome package once payment is confirmed"),
            ],
        }

    except Exception as e:
        frappe.log_error(f"Error processing enhanced application: {str(e)}")
        return {"success": False, "error": _("Failed to process application. Please contact support.")}


def create_membership_application(data):
    """Create the membership application record (Member with pending status)"""
    application = frappe.new_doc("Member")

    # Personal information
    application.first_name = cstr(data.get("first_name"))
    application.middle_name = cstr(data.get("middle_name", ""))
    application.last_name = cstr(data.get("last_name"))
    application.email = cstr(data.get("email"))
    application.mobile_no = cstr(data.get("mobile_no", ""))

    # Address information
    application.address_line1 = cstr(data.get("address_line1"))
    application.address_line2 = cstr(data.get("address_line2", ""))
    application.postal_code = cstr(data.get("postal_code"))
    application.city = cstr(data.get("city"))
    application.country = cstr(data.get("country"))

    # Membership information
    application.membership_type = cstr(data.get("membership_type"))
    application.contribution_amount = flt(data.get("contribution_amount"))
    application.contribution_mode = cstr(data.get("contribution_mode", "Calculator"))

    # Additional contribution details
    if data.get("selected_tier"):
        application.selected_tier = cstr(data.get("selected_tier"))
    if data.get("base_multiplier"):
        application.base_multiplier = flt(data.get("base_multiplier"))
    if data.get("custom_amount_reason"):
        application.custom_amount_reason = cstr(data.get("custom_amount_reason"))

    # Payment information
    application.payment_method = cstr(data.get("payment_method"))
    application.iban = cstr(data.get("iban", ""))
    application.account_holder_name = cstr(data.get("account_holder_name", ""))

    # Volunteer information
    application.interested_in_volunteering = 1 if data.get("interested_in_volunteering") else 0

    # Member status and application tracking
    application.status = "Pending"  # Member status
    application.application_status = "Pending"  # Application review status
    application.application_date = today()
    application.selected_membership_type = cstr(data.get("membership_type"))

    # Generate description
    application.contribution_description = generate_contribution_description(data)

    application.save(ignore_permissions=True)
    frappe.db.commit()

    return application


def generate_contribution_description(data):
    """Generate a human-readable description of the contribution choice"""
    mode = data.get("contribution_mode", "Calculator")
    amount = flt(data.get("contribution_amount"))

    description = f"€{amount:.2f}"

    if mode == "Tier" and data.get("selected_tier"):
        description += f" ({data.get('selected_tier')} tier)"
    elif mode == "Calculator" and data.get("base_multiplier"):
        multiplier = flt(data.get("base_multiplier"))
        percentage = int(multiplier * 100)
        description += f" ({percentage}% of suggested amount)"
    elif mode == "Custom":
        description += " (custom amount)"
        if data.get("custom_amount_reason"):
            description += f" - {data.get('custom_amount_reason')}"

    return description


def create_initial_dues_schedule(application, data):
    """Create initial membership dues schedule"""
    try:
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = None  # Will be set when member is created
        dues_schedule.membership = None  # Will be set when membership is created
        dues_schedule.membership_type = application.membership_type

        # Contribution configuration
        dues_schedule.contribution_mode = application.contribution_mode
        dues_schedule.dues_rate = application.contribution_amount

        if hasattr(application, "selected_tier") and application.selected_tier:
            dues_schedule.selected_tier = application.selected_tier
        if hasattr(application, "base_multiplier") and application.base_multiplier:
            dues_schedule.base_multiplier = application.base_multiplier

        # Get membership type details for defaults
        mt_doc = frappe.get_doc("Membership Type", application.membership_type)

        # Get amounts from template if available
        template_minimum_amount = 0
        template_suggested_amount = 0
        if mt_doc.dues_schedule_template:
            try:
                template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)
                template_minimum_amount = template.minimum_amount or 0
                template_suggested_amount = template.dues_rate or template.suggested_amount or 0
            except Exception:
                pass

        dues_schedule.minimum_amount = template_minimum_amount or (
            mt_doc.minimum_amount * 0.3 if mt_doc.minimum_amount else 5.0
        )
        dues_schedule.suggested_amount = template_suggested_amount or 15.0

        # Custom amount handling
        if application.contribution_mode == "Custom":
            dues_schedule.uses_custom_amount = 1
            if hasattr(application, "custom_amount_reason"):
                dues_schedule.custom_amount_reason = application.custom_amount_reason

        # Payment configuration
        dues_schedule.payment_method = application.payment_method
        dues_schedule.billing_frequency = "Monthly"  # Default, can be changed later
        dues_schedule.billing_day = 1  # Will be updated when member is created

        # Status
        dues_schedule.status = "Draft"
        dues_schedule.auto_generate = 0  # Don't auto-generate until membership is active

        # Coverage dates (will be updated when first payment is received)
        dues_schedule.current_coverage_start = today()

        dues_schedule.save(ignore_permissions=True)
        return dues_schedule

    except Exception as e:
        frappe.log_error(f"Error creating dues schedule: {str(e)}")
        return None


def setup_payment_method(application, data):
    """Setup payment method for the application"""
    try:
        if application.payment_method == "SEPA Direct Debit" and application.iban:
            # Create SEPA mandate for direct debit
            mandate = create_sepa_mandate(application)
            return {"success": True, "mandate": mandate.name if mandate else None}
        elif application.payment_method == "Bank Transfer":
            # Bank transfer setup - no additional setup needed
            return {"success": True, "method": "bank_transfer"}
        else:
            return {"success": True, "method": "other"}

    except Exception as e:
        frappe.log_error(f"Error setting up payment method: {str(e)}")
        return {"success": False, "error": str(e)}


def create_sepa_mandate(application):
    """Create SEPA mandate for direct debit"""
    try:
        from verenigingen.utils.iban_validator import derive_bic_from_iban, validate_iban

        # Validate IBAN
        iban_validation = validate_iban(application.iban)
        if not iban_validation["valid"]:
            return None

        # Create mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.iban = application.iban
        mandate.account_holder_name = application.account_holder_name
        mandate.bic = derive_bic_from_iban(application.iban)
        mandate.status = "Draft"
        mandate.mandate_type = "RCUR"  # Recurring
        mandate.sequence_type = "FRST"  # First payment

        # Link to application (will be linked to member when created)
        mandate.reference = f"APP-{application.name}"

        mandate.save(ignore_permissions=True)
        return mandate

    except Exception as e:
        frappe.log_error(f"Error creating SEPA mandate: {str(e)}")
        return None


def create_first_payment_invoice(application, dues_schedule, data):
    """Create invoice for first payment"""
    try:
        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = application.email  # Temporary, will be updated when member is created
        invoice.posting_date = today()
        invoice.due_date = frappe.utils.add_days(today(), 14)  # 14 days to pay

        # Add membership item
        invoice.append(
            "items",
            {
                "item_code": get_or_create_membership_item(application.membership_type),
                "item_name": f"Membership - {application.membership_type}",
                "description": f"First membership payment\nContribution: {application.contribution_description}",
                "qty": 1,
                "rate": application.contribution_amount,
                "amount": application.contribution_amount,
            },
        )

        # Add reference
        invoice.remarks = f"First payment for membership application: {application.name}"

        # Coverage period
        coverage_start = today()
        coverage_end = frappe.utils.add_months(coverage_start, 1)  # First month
        invoice.customer_address = f"Coverage: {coverage_start} to {coverage_end}"

        invoice.save(ignore_permissions=True)
        return invoice

    except Exception as e:
        frappe.log_error(f"Error creating first payment invoice: {str(e)}")
        return None


def get_or_create_membership_item(membership_type_name):
    """Get or create item for membership billing"""
    item_code = f"MEMBERSHIP-{membership_type_name}".replace(" ", "-").upper()

    if frappe.db.exists("Item", item_code):
        return item_code

    # Create item
    item = frappe.new_doc("Item")
    item.item_code = item_code
    item.item_name = f"Membership - {membership_type_name}"
    item.item_group = "Services"
    item.is_stock_item = 0
    item.is_sales_item = 1
    item.is_service_item = 1

    item.save(ignore_permissions=True)
    return item_code


def send_application_confirmation(application, invoice):
    """Send confirmation email to applicant"""
    try:
        # Get email template or create basic email
        subject = _("Membership Application Received")

        message = f"""
        Dear {application.first_name},

        Thank you for your membership application! We have received your application with the following details:

        Membership Type: {application.membership_type}
        Contribution: {application.contribution_description}
        Payment Method: {application.payment_method}

        Next Steps:
        1. Complete your first payment of €{application.contribution_amount:.2f}
        2. We will review your application
        3. You will receive a welcome package once approved

        If you have any questions, please contact us.

        Best regards,
        The Membership Team
        """

        frappe.sendmail(
            recipients=[application.email],
            subject=subject,
            message=message,
            reference_doctype="Membership Application",
            reference_name=application.name,
        )

    except Exception as e:
        frappe.log_error(f"Error sending confirmation email: {str(e)}")


@frappe.whitelist()
@standard_api(operation_type=OperationType.PUBLIC)
def get_membership_types_for_application():
    """Get membership types with contribution options for application form"""
    try:
        membership_types = frappe.get_all(
            "Membership Type",
            filters={"is_active": 1},
            fields=[
                "name",
                "membership_type_name",
                "description",
                "minimum_amount",
                "dues_schedule_template",
            ],
            order_by="membership_type_name",
        )

        enhanced_types = []
        for mt in membership_types:
            try:
                # Get the membership type document to access contribution options
                mt_doc = frappe.get_doc("Membership Type", mt.name)
                contribution_options = mt_doc.get_contribution_options()

                enhanced_mt = {
                    "name": mt.name,
                    "membership_type_name": mt.membership_type_name,
                    "description": mt.description,
                    "amount": mt.amount,
                    "billing_frequency": "Annual",  # Default, actual value comes from dues schedule
                    "contribution_options": contribution_options,
                }

                enhanced_types.append(enhanced_mt)

            except Exception:
                # Fallback for membership types without new fields
                enhanced_mt = {
                    "name": mt.name,
                    "membership_type_name": mt.membership_type_name,
                    "description": mt.description,
                    "amount": mt.amount,
                    "billing_frequency": "Annual",  # Default, actual value comes from dues schedule
                    "contribution_options": {
                        "mode": "Calculator",
                        "minimum": mt.amount * 0.5 if mt.amount else 5.0,
                        "suggested": mt.amount or 15.0,
                        "maximum": (mt.amount or 15.0) * 10,
                        "calculator": {
                            "enabled": True,
                            "percentage": 0.5,
                            "description": "Standard contribution calculation",
                        },
                        "quick_amounts": [],
                    },
                }
                enhanced_types.append(enhanced_mt)

        return enhanced_types

    except Exception as e:
        frappe.log_error(f"Error getting membership types for application: {str(e)}")
        return []
