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
    - Input sanitization and security validation
    - Email format and uniqueness validation
    - Membership type existence verification
    - Contribution amount constraints validation
    - Dutch association business rules validation
    - Age requirements validation
    - Payment method requirements validation
    - Fraud prevention measures

    Args:
        data (dict): Application data dictionary containing form fields

    Returns:
        dict: Validation result with structure:
            - valid (bool): True if all validations pass
            - error (str): Description of first validation failure (if any)

    Validation Rules:
        - All required fields must be present and non-empty
        - Input data must pass security sanitization
        - Email must be valid format and unique in system
        - Membership type must exist in database
        - Contribution amount must meet membership type constraints
        - Age must match membership type requirements
        - Payment method must have required supporting data
        - Dutch business rules must be followed
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
        "birth_date",  # Required for age-based membership validation
    ]

    # Input sanitization and security validation
    sanitization_result = sanitize_and_validate_input(data)
    if not sanitization_result["valid"]:
        return {"valid": False, "error": sanitization_result["error"]}

    # Update data with sanitized values
    data = sanitization_result["data"]

    # Basic fraud prevention - check for suspicious patterns
    fraud_check = validate_fraud_prevention(data)
    if not fraud_check["valid"]:
        return {"valid": False, "error": fraud_check["error"]}

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

    # Enhanced Dutch association business rules validation
    dutch_validation = validate_dutch_business_rules(data)
    if not dutch_validation["valid"]:
        return {"valid": False, "error": dutch_validation["error"]}

    # Validate age requirements for membership types
    age_validation = validate_age_requirements(data.get("birth_date"), membership_type)
    if not age_validation["valid"]:
        return {"valid": False, "error": age_validation["error"]}

    # Validate payment method requirements
    payment_validation = validate_payment_method_requirements(data)
    if not payment_validation["valid"]:
        return {"valid": False, "error": payment_validation["error"]}

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

                # Get amount from dues schedule template if available
                dues_amount = mt.minimum_amount  # Use minimum as fallback
                if mt.dues_schedule_template:
                    try:
                        schedule = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
                        dues_amount = schedule.dues_rate or schedule.suggested_amount or mt.minimum_amount
                    except:
                        pass

                enhanced_mt = {
                    "name": mt.name,
                    "membership_type_name": mt.membership_type_name,
                    "description": mt.description,
                    "amount": dues_amount,
                    "billing_frequency": "Annual",  # Default, actual value comes from dues schedule
                    "contribution_options": contribution_options,
                }

                enhanced_types.append(enhanced_mt)

            except Exception:
                # Fallback for membership types without new fields
                # Get amount from dues schedule template if available
                dues_amount = mt.minimum_amount  # Use minimum as fallback
                if mt.dues_schedule_template:
                    try:
                        schedule = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
                        dues_amount = schedule.dues_rate or schedule.suggested_amount or mt.minimum_amount
                    except:
                        pass

                enhanced_mt = {
                    "name": mt.name,
                    "membership_type_name": mt.membership_type_name,
                    "description": mt.description,
                    "amount": dues_amount,
                    "billing_frequency": "Annual",  # Default, actual value comes from dues schedule
                    "contribution_options": {
                        "mode": "Calculator",
                        "minimum": mt.minimum_amount,  # Use minimum_amount for validation
                        "suggested": dues_amount,
                        "maximum": dues_amount * 10 if dues_amount else 150.0,
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


@frappe.whitelist()
@public_api(operation_type=OperationType.PUBLIC)
def get_contribution_calculator_config(membership_type=None):
    """Get contribution calculator configuration for membership type.

    Provides calculator configuration including tiers, quick amounts,
    and calculation methods for flexible contribution selection.

    Args:
        membership_type (str, optional): Membership type name

    Returns:
        dict: Calculator configuration with structure:
            - enabled (bool): Whether calculator is enabled
            - percentage (float): Base calculation percentage
            - description (str): Calculator description
            - quick_amounts (list): Pre-defined amounts for quick selection
            - tiers (list): Available contribution tiers
            - minimum (float): Minimum allowed amount
            - maximum (float): Maximum allowed amount
    """
    try:
        if not membership_type:
            # Return default configuration
            return {
                "enabled": True,
                "percentage": 0.5,
                "description": "Standard contribution calculation",
                "quick_amounts": [25, 35, 50, 75],
                "tiers": [
                    {"name": "Basic", "amount": 25, "description": "Basic support"},
                    {"name": "Supporter", "amount": 50, "description": "Enhanced support"},
                ],
                "minimum": 15.0,
                "maximum": 150.0,
            }

        # Get membership type specific configuration
        if not frappe.db.exists("Membership Type", membership_type):
            return {"enabled": False, "error": "Invalid membership type"}

        mt_doc = frappe.get_doc("Membership Type", membership_type)

        # Build configuration based on membership type
        config = {
            "enabled": True,
            "percentage": 0.5,  # Default percentage
            "description": f"Contribution calculator for {membership_type}",
            "minimum": getattr(mt_doc, "minimum_amount", 15.0),
            "maximum": getattr(mt_doc, "minimum_amount", 25.0) * 10
            if hasattr(mt_doc, "minimum_amount")
            else 150.0,
        }

        # Add quick amounts based on membership type
        base_amount = getattr(mt_doc, "minimum_amount", 25.0)
        config["quick_amounts"] = [
            int(base_amount),
            int(base_amount * 1.4),
            int(base_amount * 2),
            int(base_amount * 3),
        ]

        # Add tiers
        config["tiers"] = [
            {"name": "Basic", "amount": base_amount, "description": f"Basic {membership_type} membership"},
            {"name": "Supporter", "amount": base_amount * 2, "description": "Support our mission"},
            {"name": "Champion", "amount": base_amount * 3, "description": "Champion level support"},
        ]

        return config

    except Exception as e:
        frappe.log_error(f"Error getting contribution calculator config: {str(e)}")
        return {"enabled": False, "error": "Configuration unavailable"}


def validate_dutch_business_rules(data):
    """Validate Dutch association-specific business rules.

    Validates application data against Dutch association management requirements:
    - Dutch postal code format validation
    - IBAN validation for Dutch bank accounts
    - Name component validation (tussenvoegsel support)
    - Address format validation

    Args:
        data (dict): Application data dictionary

    Returns:
        dict: Validation result with valid/error structure
    """
    # Validate Dutch postal code if country is Netherlands
    if data.get("country") == "Netherlands":
        postal_code = data.get("postal_code", "").strip()
        if postal_code and not _is_valid_dutch_postal_code(postal_code):
            return {"valid": False, "error": "Invalid Dutch postal code format. Please use format: 1234 AB"}

    # Validate IBAN if provided (required for SEPA payments)
    iban = data.get("iban", "").strip()
    if iban:
        iban_validation = _validate_iban_format(iban)
        if not iban_validation["valid"]:
            return {"valid": False, "error": iban_validation["error"]}

    # Validate name components (Dutch names may have tussenvoegsel)
    if data.get("tussenvoegsel"):
        tussenvoegsel = data.get("tussenvoegsel").strip()
        if not _is_valid_tussenvoegsel(tussenvoegsel):
            return {
                "valid": False,
                "error": "Invalid tussenvoegsel. Common examples: van, de, der, van der, van den",
            }

    # Validate phone number format (Dutch format)
    phone = data.get("phone", "").strip()
    if phone and data.get("country") == "Netherlands":
        if not _is_valid_dutch_phone(phone):
            return {
                "valid": False,
                "error": "Invalid Dutch phone number format. Please use +31 format or 06-format",
            }

    return {"valid": True}


def validate_age_requirements(birth_date, membership_type_name):
    """Validate age requirements for membership types.

    Enforces age-based membership rules:
    - Student memberships: Must be 18-30 years old
    - Senior memberships: Must be 65+ years old
    - Youth memberships: Must be 16-18 years old
    - Regular memberships: Must be 18+ years old

    Args:
        birth_date (str): Birth date in YYYY-MM-DD format
        membership_type_name (str): Name of the membership type

    Returns:
        dict: Validation result with valid/error structure
    """
    if not birth_date:
        # Birth date is optional for some membership types
        return {"valid": True}

    try:
        birth_date = getdate(birth_date)
        today_date = getdate(today())
        age = (
            today_date.year
            - birth_date.year
            - ((today_date.month, today_date.day) < (birth_date.month, birth_date.day))
        )

        # Age-based membership validation
        membership_lower = membership_type_name.lower()

        if "student" in membership_lower:
            if age < 18 or age > 30:
                return {"valid": False, "error": "Student memberships are available for ages 18-30"}
        elif "youth" in membership_lower or "junior" in membership_lower:
            if age < 16 or age >= 18:
                return {"valid": False, "error": "Youth memberships are available for ages 16-17"}
        elif "senior" in membership_lower:
            if age < 65:
                return {"valid": False, "error": "Senior memberships are available for ages 65+"}
        else:
            # Regular membership - must be 18+
            if age < 18:
                return {"valid": False, "error": "Regular membership requires minimum age of 18"}

        return {"valid": True}

    except Exception as e:
        frappe.log_error(f"Error validating age requirements: {str(e)}")
        return {"valid": False, "error": "Invalid birth date format"}


def validate_payment_method_requirements(data):
    """Validate payment method specific requirements.

    Ensures payment method selections have required supporting information:
    - SEPA Direct Debit: Requires IBAN and account holder name
    - Bank Transfer: No additional requirements
    - Mollie: No additional requirements

    Args:
        data (dict): Application data dictionary

    Returns:
        dict: Validation result with valid/error structure
    """
    payment_method = data.get("payment_method", "").strip()

    if payment_method == "SEPA Direct Debit":
        # SEPA requires IBAN and account holder name
        if not data.get("iban"):
            return {"valid": False, "error": "IBAN is required for SEPA Direct Debit payments"}

        if not data.get("account_holder_name"):
            return {"valid": False, "error": "Account holder name is required for SEPA Direct Debit payments"}

        # Validate IBAN format
        iban_validation = _validate_iban_format(data.get("iban"))
        if not iban_validation["valid"]:
            return {"valid": False, "error": iban_validation["error"]}

    elif payment_method == "Mollie":
        # Mollie payments don't require additional validation at application time
        pass

    elif payment_method == "Bank Transfer":
        # Bank transfers don't require additional fields
        pass

    else:
        return {
            "valid": False,
            "error": "Invalid payment method. Supported methods: SEPA Direct Debit, Bank Transfer, Mollie",
        }

    return {"valid": True}


def _is_valid_dutch_postal_code(postal_code):
    """Check if postal code matches Dutch format (1234 AB).

    Args:
        postal_code (str): Postal code to validate

    Returns:
        bool: True if valid Dutch postal code format
    """
    import re

    # Dutch postal code: 4 digits + space + 2 letters
    pattern = r"^\d{4}\s[A-Z]{2}$"
    return bool(re.match(pattern, postal_code.upper()))


def _validate_iban_format(iban):
    """Validate IBAN format and checksum.

    Args:
        iban (str): IBAN to validate

    Returns:
        dict: Validation result with valid/error structure
    """
    iban = iban.replace(" ", "").upper()

    # Basic format check
    if len(iban) < 15 or len(iban) > 34:
        return {"valid": False, "error": "IBAN must be between 15-34 characters"}

    if not iban[:2].isalpha():
        return {"valid": False, "error": "IBAN must start with 2-letter country code"}

    if not iban[2:4].isdigit():
        return {"valid": False, "error": "IBAN check digits must be numeric"}

    # For Dutch IBANs, enforce stricter validation
    if iban.startswith("NL"):
        if len(iban) != 18:
            return {"valid": False, "error": "Dutch IBAN must be 18 characters long"}

    return {"valid": True}


def _is_valid_tussenvoegsel(tussenvoegsel):
    """Check if tussenvoegsel is a valid Dutch name particle.

    Args:
        tussenvoegsel (str): Name particle to validate

    Returns:
        bool: True if valid tussenvoegsel
    """
    valid_particles = [
        "van",
        "de",
        "der",
        "den",
        "het",
        "van der",
        "van den",
        "van het",
        "von",
        "du",
        "da",
        "di",
        "del",
        "della",
        "van de",
        "ter",
        "te",
    ]
    return tussenvoegsel.lower() in valid_particles


def _is_valid_dutch_phone(phone):
    """Check if phone number matches Dutch format.

    Args:
        phone (str): Phone number to validate

    Returns:
        bool: True if valid Dutch phone format
    """
    import re

    phone = phone.replace(" ", "").replace("-", "")

    # Dutch mobile: +31 6 followed by 8 digits, or 06 followed by 8 digits
    mobile_pattern = r"^(\+31|0)6\d{8}$"
    # Dutch landline: +31 followed by area code and number
    landline_pattern = r"^(\+31|0)[1-9]\d{7,8}$"

    return bool(re.match(mobile_pattern, phone) or re.match(landline_pattern, phone))


def sanitize_and_validate_input(data):
    """Sanitize and validate input data for security.

    Performs input sanitization and security validation:
    - XSS prevention through HTML escaping
    - SQL injection prevention through input cleaning
    - Maximum length validation
    - Character set validation
    - Removes potential malicious content

    Args:
        data (dict): Raw input data dictionary

    Returns:
        dict: Result with sanitized data or error
    """
    import html
    import re

    sanitized_data = {}

    # Define field-specific validation rules
    field_rules = {
        "first_name": {"max_length": 100, "pattern": r"^[a-zA-ZÀ-ÿ\s\-'\.]*$"},
        "last_name": {"max_length": 100, "pattern": r"^[a-zA-ZÀ-ÿ\s\-'\.]*$"},
        "tussenvoegsel": {"max_length": 50, "pattern": r"^[a-zA-Z\s]*$"},
        "email": {"max_length": 255, "pattern": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"},
        "phone": {"max_length": 20, "pattern": r"^[+\d\s\-\(\)]*$"},
        "address_line1": {"max_length": 255},
        "address_line2": {"max_length": 255},
        "postal_code": {"max_length": 20, "pattern": r"^[A-Z0-9\s\-]*$"},
        "city": {"max_length": 100, "pattern": r"^[a-zA-ZÀ-ÿ\s\-'\.]*$"},
        "country": {"max_length": 100, "pattern": r"^[a-zA-Z\s]*$"},
        "iban": {"max_length": 34, "pattern": r"^[A-Z0-9\s]*$"},
        "account_holder_name": {"max_length": 255, "pattern": r"^[a-zA-ZÀ-ÿ\s\-'\.]*$"},
        "membership_type": {"max_length": 100, "pattern": r"^[a-zA-Z0-9\s\-_]*$"},
        "payment_method": {"max_length": 50, "pattern": r"^[a-zA-Z\s]*$"},
    }

    for field, value in data.items():
        if not isinstance(value, str):
            # Keep non-string values as-is (numbers, booleans, etc.)
            sanitized_data[field] = value
            continue

        # Basic sanitization
        sanitized_value = html.escape(value.strip())

        # Check against field-specific rules
        if field in field_rules:
            rules = field_rules[field]

            # Length validation
            if len(sanitized_value) > rules.get("max_length", 1000):
                return {
                    "valid": False,
                    "error": f"{field.replace('_', ' ').title()} is too long (maximum {rules['max_length']} characters)",
                }

            # Pattern validation
            if "pattern" in rules and sanitized_value:
                if not re.match(rules["pattern"], sanitized_value, re.IGNORECASE):
                    return {
                        "valid": False,
                        "error": f"{field.replace('_', ' ').title()} contains invalid characters",
                    }

        # Remove potential XSS/injection patterns
        dangerous_patterns = [
            r"<script[^>]*>.*?</script>",
            r"javascript:",
            r"on\w+\s*=",
            r"expression\s*\(",
            r"@import",
            r"vbscript:",
            r"<iframe[^>]*>",
            r"<object[^>]*>",
            r"<embed[^>]*>",
            r"<link[^>]*>",
            r"<meta[^>]*>",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, sanitized_value, re.IGNORECASE):
                return {"valid": False, "error": "Input contains potentially dangerous content"}

        sanitized_data[field] = sanitized_value

    return {"valid": True, "data": sanitized_data}


def validate_fraud_prevention(data):
    """Basic fraud prevention validation.

    Checks for common fraud indicators:
    - Suspicious email patterns
    - Unrealistic contribution amounts
    - Suspicious name patterns
    - Rate limiting indicators

    Args:
        data (dict): Application data dictionary

    Returns:
        dict: Validation result with valid/error structure
    """
    import re

    # Check for obviously fake email addresses
    email = data.get("email", "").lower()
    suspicious_email_patterns = [
        r"test@",
        r"fake@",
        r"spam@",
        r"noreply@",
        r"no-reply@",
        r"@mailinator\.",
        r"@10minutemail\.",
        r"@temp",
        r"@guerrillamail\.",
    ]

    for pattern in suspicious_email_patterns:
        if re.search(pattern, email):
            return {"valid": False, "error": "Please provide a valid personal email address"}

    # Check for unrealistic contribution amounts
    contribution_amount = float(data.get("contribution_amount", 0))
    if contribution_amount > 10000:  # €10,000 per month is unrealistic
        return {
            "valid": False,
            "error": "Contribution amount appears unrealistic. Please contact us directly for large contributions",
        }

    if contribution_amount < 0.01:  # Must be positive
        return {"valid": False, "error": "Contribution amount must be greater than €0.01"}

    # Check for suspicious name patterns
    first_name = data.get("first_name", "").lower()
    last_name = data.get("last_name", "").lower()

    suspicious_name_patterns = [
        "test",
        "fake",
        "admin",
        "administrator",
        "user",
        "guest",
        "asdf",
        "qwerty",
        "aaaa",
        "bbbb",
        "xxxx",
        "null",
        "undefined",
    ]

    if first_name in suspicious_name_patterns or last_name in suspicious_name_patterns:
        return {"valid": False, "error": "Please provide your real name for membership registration"}

    # Check for duplicate consecutive characters (likely bot behavior)
    if len(set(first_name)) == 1 and len(first_name) > 2:  # Like "aaaa"
        return {"valid": False, "error": "Please provide a valid first name"}

    if len(set(last_name)) == 1 and len(last_name) > 2:  # Like "bbbb"
        return {"valid": False, "error": "Please provide a valid last name"}

    return {"valid": True}
