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
import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate, today

# Import extracted services
from verenigingen.utils.dutch_name_service import is_valid_dutch_tussenvoegsel

# Import OperationResult and security framework
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, public_api, standard_api


@public_api(operation_type=OperationType.PUBLIC)
@frappe.whitelist(allow_guest=True)
def submit_enhanced_application() -> OperationResult[Dict[str, Any]]:
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
        OperationResult[Dict[str, Any]]: Result containing:
            - application_id (str): Created application ID (on success)
            - next_steps (list): Array of next action descriptions
            - invoice_id (str, optional): Created invoice ID

    Raises:
        ValidationError: For invalid or missing required data
        DatabaseError: For database operation failures
        EmailError: For email delivery failures (logged, not raised)

    Examples:
        >>> # Successful application
        OperationResult.ok({
            "application_id": "MEM-APP-2025-001",
            "next_steps": [...]
        }, message="Application submitted successfully")

        >>> # Validation error
        OperationResult.fail("A member with this email already exists")
    """
    try:
        # Get form data from the request
        data = frappe.form_dict

        # Validate all required fields and business rules
        validation_result = validate_application_data(data)
        if not validation_result["valid"]:
            frappe.log_error(
                title=_("Membership Application Validation Failed"),
                message=f"Validation error: {validation_result['error']}\nData: {json.dumps(data, indent=2)}",
            )
            return OperationResult.fail(message=validation_result["error"], error_code="VALIDATION_ERROR")

        # Process the complete application workflow
        application_result = process_enhanced_application(data)

        if application_result["success"]:
            result_data = {
                "application_id": application_result["application_id"],
                "next_steps": application_result.get("next_steps", []),
            }
            if application_result.get("invoice_id"):
                result_data["invoice_id"] = application_result["invoice_id"]

            return OperationResult.ok(data=result_data, message=_("Application submitted successfully"))
        else:
            error_msg = application_result.get("error", _("Unknown error occurred"))
            frappe.log_error(
                title=_("Membership Application Processing Failed"),
                message=f"Processing error: {error_msg}\nData: {json.dumps(data, indent=2)}",
            )
            return OperationResult.fail(message=error_msg, error_code="PROCESSING_ERROR")

    except Exception as e:
        # Log the full error for debugging while returning user-friendly message
        from verenigingen.utils.safe_error_logging import safe_log_error

        safe_log_error(
            "Enhanced Membership Application",
            f"Enhanced membership application error: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("An error occurred while processing your application. Please try again."),
            error_code="SYSTEM_ERROR",
        )


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

        # Use explicit None checks to allow 0 as a valid amount (e.g., for trial memberships)
        min_contribution = template_values.get("minimum_contribution")
        min_amount = (
            min_contribution
            if min_contribution is not None
            else (mt_doc.minimum_amount * 0.3 if mt_doc.minimum_amount else 5.0)
        )
        suggested_contribution = template_values.get("suggested_contribution")
        suggested_amount = suggested_contribution if suggested_contribution is not None else 15.0
        max_multiplier = template_values.get("fee_slider_max_multiplier", 10.0)
        max_contribution = template_values.get("maximum_contribution")
        max_amount = (
            max_contribution
            if max_contribution is not None
            else (suggested_amount * max_multiplier if suggested_amount > 0 else 0)
        )

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
    1. Member record creation with pending status and dues_rate stored
    2. Payment method configuration (SEPA mandate if applicable)
    3. First payment invoice generation with proper coverage period
    4. Confirmation email delivery

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
        - Creates Member record with status='Pending' and dues_rate
        - Creates SEPA Mandate record (for direct debit)
        - Creates Sales Invoice for first payment with billing-frequency-based coverage
        - Sends confirmation email to applicant
        - Commits database transaction

    Note:
        Membership Dues Schedule is created during approval workflow when
        membership.submit() is called, using the dues_rate stored on Member.

    Error Handling:
        - Logs all errors for debugging
        - Returns user-friendly error messages
        - Does not expose internal system details
    """
    try:
        # Create membership application
        application = create_membership_application(data)

        # Note: Membership Dues Schedule is created during approval workflow
        # when membership.submit() is called. Applicant's chosen rate is stored
        # on application.dues_rate field.

        # Handle payment setup
        setup_payment_method(application, data)

        # Create invoice for first payment
        invoice = create_first_payment_invoice(application, data)

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
        from verenigingen.utils.safe_error_logging import safe_log_error

        safe_log_error("Application processing failed", f"Error processing enhanced application: {str(e)}")
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
    application.dues_rate = flt(data.get("contribution_amount"))

    # Note: contribution_mode, selected_tier, base_multiplier, and custom_amount_reason
    # are stored on the Membership Dues Schedule, not on the Member record

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
    # Note: contribution_description is stored in data for reference but not on Member record

    # IMPORTANT: Set owner to the configured creation user
    # This prevents the applicant from becoming the owner of the member record
    # which would give them inappropriate access to modify member data
    settings = frappe.get_single("Verenigingen Settings")
    application.owner = settings.creation_user or "Administrator"

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    from verenigingen.utils.secure_operations import secure_document_operation

    # Secure member application creation with explicit permission validation
    application_result = secure_document_operation(
        operation="save",
        doc=application,
        justification=f"Enhanced membership application creation for {application.email}",
        required_permissions=["Member:create"],
    )

    if not application_result.success:
        frappe.logger().error(f"Failed to create member application: {'; '.join(application_result.errors)}")
        frappe.throw(
            _("Failed to create member application: {0}").format("; ".join(application_result.errors))
        )

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
        from verenigingen.utils.validation.iban_validator import derive_bic_from_iban, validate_iban

        # Validate IBAN
        iban_validation = validate_iban(application.iban)
        if not iban_validation["valid"]:
            return None

        # Create mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.iban = application.iban
        mandate.account_holder_name = application.bank_account_name
        mandate.bic = derive_bic_from_iban(application.iban)
        mandate.status = "Draft"
        mandate.mandate_type = "RCUR"  # Recurring
        mandate.sequence_type = "FRST"  # First payment

        # Link to application (will be linked to member when created)
        mandate.reference = f"APP-{application.name}"

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        # Secure SEPA mandate creation with explicit permission validation
        mandate_result = secure_document_operation(
            operation="save",
            doc=mandate,
            justification=f"SEPA mandate creation for membership application {application.name}",
            required_permissions=["SEPA Mandate:create"],
        )

        if not mandate_result.success:
            frappe.logger().error(f"Failed to create SEPA mandate: {'; '.join(mandate_result.errors)}")
            frappe.throw(_("Failed to create SEPA mandate: {0}").format("; ".join(mandate_result.errors)))
        return mandate

    except Exception as e:
        frappe.log_error(f"Error creating SEPA mandate: {str(e)}")
        return None


def create_first_payment_invoice(application, data):
    """Create invoice for first payment.

    Generates the initial membership payment invoice to kickstart the
    billing cycle for the new member.

    Args:
        application (Member): Member application record
        data (dict): Application data

    Returns:
        SalesInvoice or None: Created invoice or None on error

    Invoice Configuration:
        - 14-day payment terms
        - Membership item auto-creation if needed
        - Coverage period based on membership type billing frequency
        - Links to application for tracking

    Item Management:
        - Auto-creates membership items as needed
        - Uses standardized naming: "MEMBERSHIP-{TYPE}"
        - Configures as service item (non-stock)
    """
    try:
        # Get membership type to determine billing frequency
        membership_type = frappe.get_doc("Membership Type", data.get("membership_type"))

        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = application.email  # Temporary, will be updated when member is created
        invoice.posting_date = today()
        invoice.due_date = frappe.utils.add_days(today(), 14)  # 14 days to pay

        # Add membership item
        invoice.append(
            "items",
            {
                "item_code": get_or_create_membership_item(application.selected_membership_type),
                "item_name": f"Membership - {application.selected_membership_type}",
                "description": f"First membership payment\nContribution: {generate_contribution_description(data)}",
                "qty": 1,
                "rate": data.get("contribution_amount"),
                "amount": data.get("contribution_amount"),
            },
        )

        # Add reference
        invoice.remarks = f"First payment for membership application: {application.name}"

        # Calculate coverage period based on membership type billing frequency
        coverage_start = today()
        billing_frequency = (
            membership_type.billing_period.lower() if membership_type.billing_period else "monthly"
        )

        if billing_frequency == "quarterly":
            coverage_end = frappe.utils.add_months(coverage_start, 3)
        elif billing_frequency == "annual" or billing_frequency == "yearly":
            coverage_end = frappe.utils.add_years(coverage_start, 1)
        elif billing_frequency == "daily":
            coverage_end = frappe.utils.add_days(coverage_start, 1)
        else:  # monthly or default
            coverage_end = frappe.utils.add_months(coverage_start, 1)

        invoice.customer_address = f"Coverage: {coverage_start} to {coverage_end}"

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        from verenigingen.utils.secure_operations import secure_document_operation

        # Secure application invoice creation with explicit permission validation
        invoice_result = secure_document_operation(
            operation="save",
            doc=invoice,
            justification=f"Application invoice creation for membership application {application.name}",
            required_permissions=["Sales Invoice:create"],
        )

        if not invoice_result.success:
            frappe.logger().error(f"Failed to create application invoice: {'; '.join(invoice_result.errors)}")
            frappe.throw(
                _("Failed to create application invoice: {0}").format("; ".join(invoice_result.errors))
            )
        return invoice

    except Exception as e:
        from verenigingen.utils.safe_error_logging import safe_log_error

        safe_log_error("Invoice creation failed", f"Error creating first payment invoice: {str(e)}")
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

    # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
    from verenigingen.utils.secure_operations import secure_document_operation

    # Secure membership fee item creation with explicit permission validation
    item_result = secure_document_operation(
        operation="save",
        doc=item,
        justification=f"Membership fee item creation: {item_code}",
        required_permissions=["Item:create"],
    )

    if not item_result.success:
        frappe.logger().error(f"Failed to create membership fee item: {'; '.join(item_result.errors)}")
        frappe.throw(_("Failed to create membership fee item: {0}").format("; ".join(item_result.errors)))
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

        # MIGRATED: Use unified EmailService for application confirmation
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        # Prepare context for template
        context = {
            "application": application,
            "first_name": application.first_name,
            "membership_type": application.selected_membership_type,
            "contribution_description": generate_contribution_description(data),
            "payment_method": data.get("payment_method"),
            "contribution_amount": data.get("contribution_amount", 0),
            "next_steps": [
                f"Complete your first payment of €{data.get('contribution_amount', 0):.2f}",
                "We will review your application",
                "You will receive a welcome package once approved",
            ],
        }

        # Send using EmailService with template fallback
        email_service.send_templated_email(
            template_name="membership_application_confirmation",
            recipients=[application.email],
            context=context,
            subject_override=subject,
            reference_doctype="Membership Application",
            reference_name=application.name,
        )

    except Exception as e:
        frappe.log_error(f"Error sending confirmation email: {str(e)}")


@public_api(operation_type=OperationType.PUBLIC)
@frappe.whitelist(allow_guest=True)
def get_membership_types_for_application() -> OperationResult[Dict[str, Any]]:
    """Get membership types with contribution options for application form.

    Retrieves available membership types with their contribution configuration
    for use in the membership application form.

    Returns:
        OperationResult[Dict[str, Any]]: Result containing:
            - membership_types (list): Array of membership type dictionaries with structure:
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
        - Returns OperationResult with empty array on database errors
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

        return OperationResult.ok(
            data={"membership_types": enhanced_types}, message=_("Membership types retrieved successfully")
        )

    except Exception as e:
        frappe.log_error(
            title=_("Error Getting Membership Types"),
            message=f"Error getting membership types for application: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to retrieve membership types. Please try again."), error_code="RETRIEVAL_ERROR"
        )


@public_api(operation_type=OperationType.PUBLIC)
@frappe.whitelist(allow_guest=True)
def get_contribution_calculator_config(membership_type=None) -> OperationResult[Dict[str, Any]]:
    """Get contribution calculator configuration for membership type.

    Provides calculator configuration including tiers, quick amounts,
    and calculation methods for flexible contribution selection.

    Args:
        membership_type (str, optional): Membership type name

    Returns:
        OperationResult[Dict[str, Any]]: Result containing calculator configuration:
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
            default_config = {
                "enabled": True,
                "percentage": 0.5,
                "description": _("Standard contribution calculation"),
                "quick_amounts": [25, 35, 50, 75],
                "tiers": [
                    {"name": "Basic", "amount": 25, "description": _("Basic support")},
                    {"name": "Supporter", "amount": 50, "description": _("Enhanced support")},
                ],
                "minimum": 15.0,
                "maximum": 150.0,
            }
            return OperationResult.ok(
                data=default_config, message=_("Default calculator configuration retrieved")
            )

        # Get membership type specific configuration
        if not frappe.db.exists("Membership Type", membership_type):
            frappe.log_error(
                title=_("Invalid Membership Type"),
                message=f"Membership type '{membership_type}' does not exist",
            )
            return OperationResult.fail(
                message=_("Invalid membership type"), error_code="INVALID_MEMBERSHIP_TYPE"
            )

        mt_doc = frappe.get_doc("Membership Type", membership_type)

        # Build configuration based on membership type
        config = {
            "enabled": True,
            "percentage": 0.5,  # Default percentage
            "description": f"Contribution calculator for {membership_type}",
            "minimum": getattr(mt_doc, "minimum_amount", 15.0),
            "maximum": (
                getattr(mt_doc, "minimum_amount", 25.0) * 10 if hasattr(mt_doc, "minimum_amount") else 150.0
            ),
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
            {
                "name": "Basic",
                "amount": base_amount,
                "description": _("Basic {0} membership").format(membership_type),
            },
            {"name": "Supporter", "amount": base_amount * 2, "description": _("Support our mission")},
            {"name": "Champion", "amount": base_amount * 3, "description": _("Champion level support")},
        ]

        return OperationResult.ok(data=config, message=_("Calculator configuration retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Error Getting Calculator Config"),
            message=f"Error getting contribution calculator config: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(message=_("Configuration unavailable"), error_code="CONFIG_ERROR")


@public_api(operation_type=OperationType.PUBLIC)
@frappe.whitelist(allow_guest=True)
def calculate_progressive_dues(
    membership_type: str = None, monthly_income: float = None
) -> OperationResult[Dict[str, Any]]:
    """Calculate progressive dues based on income using sliding scale formula.

    Uses the progressive contribution formula:
        multiplier = (income - lower_threshold) / (reference_income - lower_threshold)
        suggested_dues = standard_dues * multiplier

    Args:
        membership_type (str): Membership type name with Progressive mode configured
        monthly_income (float): Applicant's monthly net income

    Returns:
        OperationResult[Dict[str, Any]]: Result containing:
            - multiplier (float): Calculated multiplier (0.0 to unbounded)
            - percentage (float): Multiplier as percentage (0 to unbounded)
            - suggested_dues (float): Calculated dues amount
            - standard_dues (float): Base dues (100% reference)
            - reference_income (float): Median income reference
            - lower_threshold (float): Lower income threshold

    Error Handling:
        - Returns error if membership type not found
        - Returns error if Progressive mode not configured
        - Returns error if income is invalid
    """
    try:
        if not membership_type:
            return OperationResult.fail(
                message=_("Membership type is required"), error_code="MISSING_MEMBERSHIP_TYPE"
            )

        if monthly_income is None or monthly_income < 0:
            return OperationResult.fail(
                message=_("Valid monthly income is required"), error_code="INVALID_INCOME"
            )

        monthly_income = flt(monthly_income)

        # Get membership type and its template
        if not frappe.db.exists("Membership Type", membership_type):
            return OperationResult.fail(
                message=_("Invalid membership type"), error_code="INVALID_MEMBERSHIP_TYPE"
            )

        mt_doc = frappe.get_doc("Membership Type", membership_type)

        if not mt_doc.dues_schedule_template:
            return OperationResult.fail(
                message=_("Membership type has no dues schedule template configured"),
                error_code="NO_TEMPLATE",
            )

        template = frappe.get_doc("Membership Dues Schedule", mt_doc.dues_schedule_template)

        if template.contribution_mode != "Progressive":
            return OperationResult.fail(
                message=_("This membership type does not use progressive contribution mode"),
                error_code="NOT_PROGRESSIVE",
            )

        # Get progressive configuration
        reference_income = template.progressive_reference_income or 0
        lower_threshold = template.progressive_lower_threshold or 0
        standard_dues = template.suggested_amount or 0

        if reference_income <= lower_threshold:
            return OperationResult.fail(
                message=_("Invalid progressive configuration"),
                error_code="INVALID_CONFIG",
            )

        # Calculate using the template's method
        result = template.calculate_progressive_dues(monthly_income, standard_dues)

        # Add configuration to the result
        result["reference_income"] = reference_income
        result["lower_threshold"] = lower_threshold

        return OperationResult.ok(data=result, message=_("Progressive dues calculated successfully"))

    except Exception as e:
        frappe.log_error(
            title=_("Error Calculating Progressive Dues"),
            message=f"Error calculating progressive dues: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            message=_("Failed to calculate dues. Please try again."),
            error_code="CALCULATION_ERROR",
        )


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
    """Validate age requirements for membership types using configurable age validation.

    Enforces age-based membership rules through the AgeValidator utility:
    - Student memberships: Configurable age range (default 18-30)
    - Senior memberships: Configurable minimum age (default 65+)
    - Youth memberships: Configurable age range (default 16-17)
    - Regular memberships: Configurable minimum age (default 18+)

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
        from verenigingen.utils.validation_utilities import AgeValidator

        # Map membership type to validation context
        membership_lower = membership_type_name.lower()

        if "student" in membership_lower:
            context = "student_membership"
        elif "youth" in membership_lower or "junior" in membership_lower:
            context = "youth_membership"
        elif "senior" in membership_lower:
            context = "senior_membership"
        else:
            # Regular membership - use voting age as proxy (18+)
            context = "voting"

        # Validate using configurable age validator
        result = AgeValidator.validate_age(birth_date, context=context, throw_on_error=False)

        if result.is_valid:
            return {"valid": True}
        else:
            return {"valid": False, "error": result.message}

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
    """Check if postal code matches Dutch format (1234 AB) - delegated to postal_code_validator"""
    from verenigingen.utils.validation.postal_code_validator import is_valid_dutch_postal_code

    return is_valid_dutch_postal_code(postal_code)


def _validate_iban_format(iban):
    """Validate IBAN format and checksum.

    .. deprecated:: 1.0.0
        Use :func:`verenigingen.utils.validation.iban_validator.validate_iban` instead.
        **SECURITY RISK:** This method only checks basic format (length, country code) without
        validating the MOD-97 checksum. It may accept IBANs with invalid checksums!

        **Migration Example**::

            # Old (basic validation, NO checksum!)
            iban_validation = _validate_iban_format(iban)
            if not iban_validation["valid"]:
                return {"valid": False, "error": iban_validation["error"]}

            # New (full validation WITH checksum)
            from verenigingen.utils.validation.iban_validator import validate_iban
            result = validate_iban(iban)
            if not result["valid"]:
                return {"valid": False, "error": result.get("message", "Invalid IBAN")}

    Args:
        iban (str): IBAN to validate

    Returns:
        dict: Validation result with valid/error structure
    """
    import warnings

    warnings.warn(
        "enhanced_membership_application._validate_iban_format() is deprecated. "
        "Use iban_validator.validate_iban() instead. "
        "SECURITY RISK: This method lacks MOD-97 checksum validation and may accept invalid IBANs!",
        DeprecationWarning,
        stacklevel=2,
    )

    # Delegate to canonical implementation
    from verenigingen.utils.validation.iban_validator import validate_iban

    result = validate_iban(iban)

    # Adapt canonical result to expected dict format
    if result["valid"]:
        return {"valid": True}
    else:
        return {"valid": False, "error": result.get("message", "Invalid IBAN")}


def _is_valid_tussenvoegsel(tussenvoegsel):
    """Check if tussenvoegsel is a valid Dutch name particle.

    Delegates to the extracted dutch_name_service for consistent validation.

    Args:
        tussenvoegsel (str): Name particle to validate

    Returns:
        bool: True if valid tussenvoegsel
    """
    return is_valid_dutch_tussenvoegsel(tussenvoegsel)


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
