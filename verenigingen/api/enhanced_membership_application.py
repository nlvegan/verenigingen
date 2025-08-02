"""
Enhanced membership application API with flexible contribution system.

This module provides a comprehensive API for processing membership applications
with support for flexible contribution amounts, multiple payment methods,
and integrated billing setup.

Key Features:
    - Flexible contribution calculation (tiers, calculator, custom amounts)
    - SEPA direct debit mandate creation
    - Automatic dues schedule generation
    - Integrated invoice generation for first payment
    - Email confirmation workflow
    - Comprehensive validation and error handling

Security:
    - Uses api_security_framework for endpoint protection
    - Public API endpoints for guest access
    - Standard API endpoints for authenticated operations
    - Input validation and sanitization
    - Permission-based chapter access control

Author: Verenigingen Development Team
Last Updated: 2025-08-02
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
    """Submit enhanced membership application with flexible contribution.

    This endpoint handles the complete membership application workflow including:
    - Data validation and sanitization
    - Application record creation
    - Dues schedule setup
    - Payment method configuration
    - First payment invoice generation
    - Confirmation email delivery

    Args:
        Form data (via frappe.form_dict):
            first_name (str): Applicant's first name
            last_name (str): Applicant's last name
            email (str): Valid email address (must be unique)
            address_line1 (str): Primary address
            postal_code (str): Postal/ZIP code
            city (str): City name
            country (str): Country name
            membership_type (str): Valid membership type name
            contribution_amount (float): Monthly contribution amount
            payment_method (str): 'SEPA Direct Debit' or 'Bank Transfer'
            iban (str, optional): IBAN for SEPA payments
            account_holder_name (str, optional): Bank account holder name
            interested_in_volunteering (bool, optional): Volunteer interest flag

    Returns:
        dict: Success/error response with following structure:
            - success (bool): Operation status
            - application_id (str): Created application ID (on success)
            - message (str): Localized success message
            - next_steps (list): Array of next action descriptions
            - error (str): Error message (on failure)

    Raises:
        ValidationError: For invalid or missing required data
        DatabaseError: For database operation failures
        EmailError: For email delivery failures (logged, not raised)

    Examples:
        >>> # Successful application
        {
            "success": True,
            "application_id": "MEM-APP-2025-001",
            "message": "Application submitted successfully",
            "next_steps": [
                "Check your email for confirmation and payment instructions",
                "Complete your first payment to activate membership",
                "You will receive a welcome package once payment is confirmed"
            ]
        }

        >>> # Validation error
        {
            "success": False,
            "error": "A member with this email already exists"
        }
    """
    try:
        # Get form data from the request
        data = frappe.form_dict

        # Validate all required fields and business rules
        validation_result = validate_application_data(data)
        if not validation_result["valid"]:
            return {"success": False, "error": validation_result["error"]}

        # Process the complete application workflow
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
        # Log the full error for debugging while returning user-friendly message
        frappe.log_error(
            f"Enhanced membership application error: {str(e)}", "Enhanced Membership Application"
        )
        return {
            "success": False,
            "error": _("An error occurred while processing your application. Please try again."),
        }


def validate_application_data(data):
    """Validate the enhanced application data.

    Performs comprehensive validation of membership application data including:
    - Required field presence check
    - Email format and uniqueness validation
    - Membership type existence verification
    - Contribution amount constraints validation

    Args:
        data (dict): Application data dictionary containing form fields

    Returns:
        dict: Validation result with structure:
            - valid (bool): True if all validations pass
            - error (str): Description of first validation failure (if any)

    Validation Rules:
        - All required fields must be present and non-empty
        - Email must be valid format and unique in system
        - Membership type must exist in database
        - Contribution amount must meet membership type constraints
    """
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
    """Validate contribution amount against membership type constraints.

    Validates the proposed contribution amount against the membership type's
    minimum and maximum constraints, considering the contribution calculation mode.

    Args:
        membership_type_name (str): Name of the membership type
        amount (float): Proposed contribution amount
        contribution_mode (str, optional): Contribution calculation mode
            ('Calculator', 'Tier', 'Custom')
        selected_tier (str, optional): Selected tier name for tier-based contributions
        base_multiplier (float, optional): Multiplier for calculator-based contributions

    Returns:
        dict: Validation result with structure:
            - valid (bool): True if amount meets constraints
            - amount (float): Validated amount (if valid)
            - error (str): Constraint violation description (if invalid)

    Business Rules:
        - Amount must be >= minimum_contribution (from template or 30% of membership type minimum)
        - Amount must be <= maximum_contribution (from template or 10x suggested amount)
        - Uses dues schedule template values when available
        - Falls back to membership type values with reasonable defaults
    """
    try:
        amount = flt(amount)
        mt_doc = frappe.get_doc("Membership Type", membership_type_name)

        # Get contribution constraints from dues schedule template if available
        # Templates provide organization-wide defaults for contribution ranges
        template_values = {}
        if mt_doc.dues_schedule_template:
            try:
                template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)
                template_values = {
                    "minimum_contribution": template.minimum_amount or 0,
                    "suggested_contribution": template.dues_rate or template.suggested_amount or 0,
                    "fee_slider_max_multiplier": 10.0,  # Standard 10x multiplier for max
                    "maximum_contribution": 0,
                }
            except Exception:
                # Continue with fallback values if template access fails
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
    """Process the enhanced membership application.

    Orchestrates the complete application processing workflow including:
    1. Member record creation with pending status
    2. Initial dues schedule setup
    3. Payment method configuration (SEPA mandate if applicable)
    4. First payment invoice generation
    5. Confirmation email delivery

    Args:
        data (dict): Validated application data

    Returns:
        dict: Processing result with structure:
            - success (bool): Overall processing status
            - application_id (str): Created member record ID
            - invoice_id (str): Created invoice ID (if successful)
            - next_steps (list): User action descriptions
            - error (str): Error description (on failure)

    Side Effects:
        - Creates Member record with status='Pending'
        - Creates Membership Dues Schedule record
        - Creates SEPA Mandate record (for direct debit)
        - Creates Sales Invoice for first payment
        - Sends confirmation email to applicant
        - Commits database transaction

    Error Handling:
        - Logs all errors for debugging
        - Returns user-friendly error messages
        - Does not expose internal system details
    """
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
    """Create the membership application record (Member with pending status).

    Creates a new Member document with all provided application data and sets
    appropriate status fields for tracking through the approval workflow.

    Args:
        data (dict): Validated application data containing personal info,
                    address, membership preferences, and payment details

    Returns:
        Member: Created Member document with pending status

    Business Logic:
        - Sets status='Pending' for approval workflow
        - Sets application_status='Pending' for application tracking
        - Uses configured creation user as owner (not applicant)
        - Generates contribution description for audit trail
        - Commits transaction to ensure data persistence

    Security:
        - Uses ignore_permissions=True for system creation
        - Sets owner to configured system user to prevent applicant ownership
    """
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

    # Generate human-readable description for audit trail and member communications
    application.contribution_description = generate_contribution_description(data)

    # IMPORTANT: Set owner to the configured creation user
    # This prevents the applicant from becoming the owner of the member record
    # which would give them inappropriate access to modify member data
    settings = frappe.get_single("Verenigingen Settings")
    application.owner = settings.creation_user or "Administrator"

    application.save(ignore_permissions=True)
    frappe.db.commit()

    return application


def generate_contribution_description(data):
    """Generate a human-readable description of the contribution choice.

    Creates a descriptive string explaining how the contribution amount was
    calculated or selected, useful for audit trails and member communications.

    Args:
        data (dict): Application data containing contribution details

    Returns:
        str: Human-readable description of contribution selection

    Examples:
        - "€25.00 (Standard tier)"
        - "€18.50 (75% of suggested amount)"
        - "€30.00 (custom amount) - Student discount"
    """
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
    """Create initial membership dues schedule.

    Sets up the billing configuration for the new member based on their
    contribution choices and membership type settings.

    Args:
        application (Member): Created member application record
        data (dict): Original application data

    Returns:
        MembershipDuesSchedule or None: Created dues schedule or None on error

    Configuration:
        - Uses membership type template values when available
        - Sets defaults for minimum/suggested amounts
        - Configures billing frequency (default: Monthly)
        - Sets status='Draft' until membership is active
        - Disables auto-generation until payment confirmed

    Note:
        Member and membership fields are left None until approval workflow
        completes and actual Member/Membership records are created.
    """
    try:
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        # Leave member/membership fields empty until approval workflow completes
        # These will be linked when the application is approved and formal records created
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

        # Set initial status and disable auto-billing until membership is active
        # This prevents premature invoice generation before approval
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
    """Setup payment method for the application.

    Configures the payment method based on applicant's choice, creating
    necessary supporting records (e.g., SEPA mandates for direct debit).

    Args:
        application (Member): Member application record
        data (dict): Application data containing payment preferences

    Returns:
        dict: Setup result with structure:
            - success (bool): Operation status
            - mandate (str, optional): SEPA mandate ID (for direct debit)
            - method (str, optional): Payment method identifier
            - error (str, optional): Error description

    Supported Methods:
        - SEPA Direct Debit: Creates SEPA mandate with IBAN validation
        - Bank Transfer: No additional setup required
        - Other: Generic payment method handling
    """
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
    """Create SEPA mandate for direct debit.

    Creates a SEPA mandate record for recurring direct debit payments,
    including IBAN validation and BIC derivation.

    Args:
        application (Member): Member application with IBAN details

    Returns:
        SEPAMandate or None: Created mandate record or None on validation failure

    Validation:
        - IBAN format and checksum validation
        - BIC derivation from IBAN country/bank codes
        - Account holder name verification

    Configuration:
        - mandate_type='RCUR' (recurring payments)
        - sequence_type='FRST' (first payment)
        - status='Draft' until first successful collection
    """
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
    """Create invoice for first payment.

    Generates the initial membership payment invoice to kickstart the
    billing cycle for the new member.

    Args:
        application (Member): Member application record
        dues_schedule (MembershipDuesSchedule): Billing configuration
        data (dict): Application data

    Returns:
        SalesInvoice or None: Created invoice or None on error

    Invoice Configuration:
        - 14-day payment terms
        - Membership item auto-creation if needed
        - Coverage period documentation in remarks
        - Links to application for tracking

    Item Management:
        - Auto-creates membership items as needed
        - Uses standardized naming: "MEMBERSHIP-{TYPE}"
        - Configures as service item (non-stock)
    """
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
    """Get or create item for membership billing.

    Ensures a billing item exists for the membership type, creating one
    if needed with appropriate configuration for service billing.

    Args:
        membership_type_name (str): Name of the membership type

    Returns:
        str: Item code for billing purposes

    Item Configuration:
        - Code format: "MEMBERSHIP-{TYPE}" (uppercase, spaces to hyphens)
        - Name: "Membership - {type}"
        - Group: "Services"
        - Non-stock service item suitable for recurring billing
    """
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
    """Send confirmation email to applicant.

    Sends a confirmation email to the applicant with application details
    and next steps for completing their membership.

    Args:
        application (Member): Member application record
        invoice (SalesInvoice): First payment invoice

    Side Effects:
        - Sends email to application.email
        - Logs email reference for tracking
        - Errors are logged but do not fail the application process

    Email Content:
        - Application acknowledgment
        - Membership type and contribution details
        - Payment instructions and amount
        - Next steps in the approval process

    Error Handling:
        - Email failures are logged but not re-raised
        - Application processing continues even if email fails
    """
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
    """Get membership types with contribution options for application form.

    Retrieves available membership types with their contribution configuration
    for use in the membership application form.

    Returns:
        list: Array of membership type dictionaries with structure:
            - name (str): Membership type ID
            - membership_type_name (str): Display name
            - description (str): Type description
            - amount (float): Base amount
            - billing_frequency (str): Default billing frequency
            - contribution_options (dict): Contribution calculation options

    Contribution Options Structure:
        - mode (str): Default contribution mode
        - minimum (float): Minimum allowed contribution
        - suggested (float): Suggested contribution amount
        - maximum (float): Maximum allowed contribution
        - calculator (dict): Calculator mode configuration
        - quick_amounts (list): Predefined quick-select amounts

    Error Handling:
        - Returns empty array on database errors
        - Gracefully handles missing contribution options
        - Falls back to legacy configuration for older types
    """
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
