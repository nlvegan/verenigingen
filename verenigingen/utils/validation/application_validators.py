"""
Validation utilities for membership applications
"""
import re

import frappe
from dateutil.relativedelta import relativedelta
from frappe import _
from frappe.utils import getdate, today, validate_email_address


def validate_email(email):
    """Validate email format and check if it already exists"""
    try:
        if not email:
            return {"valid": False, "message": _("Email is required")}

        # Use Frappe's built-in email validation
        validate_email_address(email, throw=True)

        # Check if email already exists
        existing_member = frappe.db.exists("Member", {"email": email})
        if existing_member:
            return {
                "valid": False,
                "message": _("A member with this email already exists. Please login or contact support."),
                "exists": True,
                "member_id": existing_member,
            }

        return {"valid": True, "message": _("Email is available")}

    except Exception as e:
        return {"valid": False, "message": str(e)}


def validate_postal_code(postal_code, country="Netherlands"):
    """Validate postal code format"""
    if not postal_code:
        return {"valid": False, "message": _("Postal code is required")}

    # Basic format validation based on country
    postal_patterns = {
        "Netherlands": r"^[1-9][0-9]{3}\s?[A-Z]{2}$",
        "Germany": r"^[0-9]{5}$",
        "Belgium": r"^[1-9][0-9]{3}$",
        "France": r"^[0-9]{5}$",
    }

    pattern = postal_patterns.get(country, r"^.+$")  # Default: any non-empty

    if not re.match(pattern, postal_code.upper().strip()):
        return {"valid": False, "message": _("Invalid postal code format for {0}").format(country)}

    return {"valid": True, "message": _("Valid postal code")}


def validate_phone_number(phone, country="Netherlands"):
    """Validate phone number format"""
    if not phone:
        return {"valid": True, "message": _("Phone number is optional")}

    # Remove spaces and common characters
    clean_phone = re.sub(r"[\s\-\(\)\+]", "", phone)

    # Basic patterns for different countries
    phone_patterns = {
        "Netherlands": r"^(06|0031|31)?[0-9]{8,9}$",
        "Germany": r"^(0049|49|0)?[1-9][0-9]{7,11}$",
        "Belgium": r"^(0032|32|0)?[1-9][0-9]{7,8}$",
    }

    pattern = phone_patterns.get(country, r"^[0-9\+]{8,15}$")  # Default: 8-15 digits

    if not re.match(pattern, clean_phone):
        return {"valid": False, "message": _("Invalid phone number format for {0}").format(country)}

    return {"valid": True, "message": _("Valid phone number")}


def validate_birth_date(birth_date):
    """Validate birth date"""
    try:
        if not birth_date:
            return {"valid": False, "message": _("Birth date is required")}

        birth_date_obj = getdate(birth_date)
        today_date = getdate(today())

        # Check if date is in the future
        if birth_date_obj > today_date:
            return {"valid": False, "message": _("Birth date cannot be in the future")}

        # Calculate age
        age_delta = relativedelta(today_date, birth_date_obj)
        age = age_delta.years

        # Check reasonable age limits (under 1000 for our immortal members, over 0)
        if age > 1000:
            return {
                "valid": False,
                "message": _("Even for immortals, ages over 1000 years require additional verification"),
            }

        if age < 0:
            return {"valid": False, "message": _("Invalid birth date")}

        return {"valid": True, "message": _("Valid birth date"), "age": age}

    except Exception:
        return {"valid": False, "message": _("Invalid birth date format")}


def validate_name(name, field_name="Name"):
    """Validate name fields"""
    if not name:
        return {"valid": False, "message": _("{field_name} is required")}

    # Sanitize the name by stripping whitespace and normalizing
    sanitized_name = name.strip()

    # Check length
    if len(sanitized_name) < 2:
        return {"valid": False, "message": _("{field_name} must be at least 2 characters")}

    if len(sanitized_name) > 50:
        return {"valid": False, "message": _("{field_name} must be less than 50 characters")}

    # Enhanced regex pattern to handle more special characters commonly found in names
    # Includes: letters (including accented), spaces, hyphens, apostrophes, periods, and common name characters
    # Also handles Unicode characters properly
    name_pattern = r"^[\w\s\-\'\.\u00C0-\u017F\u0100-\u024F\u1E00-\u1EFF]+$"

    if not re.match(name_pattern, sanitized_name, re.UNICODE):
        return {
            "valid": False,
            "message": _(
                "{field_name} contains invalid characters. Only letters, spaces, hyphens, apostrophes, and periods are allowed"
            ),
        }

    # Check for potentially dangerous patterns (basic security)
    dangerous_patterns = [
        r"<[^>]*>",  # HTML tags
        r"javascript:",  # JavaScript
        r"on\w+\s*=",  # Event handlers
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]",  # Control characters
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, sanitized_name, re.IGNORECASE):
            return {"valid": False, "message": _("{field_name} contains invalid characters")}

    return {"valid": True, "message": _("Valid name"), "sanitized": sanitized_name}


def validate_address(data):
    """Validate address data"""
    required_fields = ["address_line1", "city", "postal_code", "country"]
    errors = []

    for field in required_fields:
        if not data.get(field):
            errors.append(_(f"{field.replace('_', ' ').title()} is required"))

    # Validate postal code format
    if data.get("postal_code") and data.get("country"):
        postal_validation = validate_postal_code(data["postal_code"], data["country"])
        if not postal_validation["valid"]:
            errors.append(postal_validation["message"])

    return {"valid": len(errors) == 0, "errors": errors}


def validate_membership_amount_selection(membership_type, amount, uses_custom):
    """Validate membership amount selection"""
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Get standard amount from template, not minimum_amount
        standard_amount = 0
        if membership_type_doc.dues_schedule_template:
            try:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                standard_amount = template.dues_rate or template.suggested_amount or 0
            except Exception:
                pass

        # Fallback to minimum_amount if no template amount available
        if not standard_amount:
            standard_amount = membership_type_doc.minimum_amount

        # Convert to float for comparison
        amount = float(amount) if amount else 0
        standard_amount = float(standard_amount) if standard_amount else 0

        if uses_custom:
            # Custom amount validation
            if amount <= 0:
                return {"valid": False, "message": _("Custom amount must be greater than 0")}

            # Check if custom amount is reasonable (not less than 50% of standard)
            min_amount = standard_amount * 0.5
            if amount < min_amount:
                return {
                    "valid": False,
                    "message": _("Custom amount cannot be less than {0}% of standard amount ({1})").format(
                        50, frappe.utils.fmt_money(min_amount, currency="EUR")
                    ),
                }
        else:
            # Standard amount validation
            if abs(amount - standard_amount) > 0.01:  # Allow for small rounding differences
                return {"valid": False, "message": _("Amount does not match membership type standard amount")}

        return {"valid": True, "message": _("Valid amount selection")}

    except Exception as e:
        return {"valid": False, "message": str(e)}


def validate_custom_amount(membership_type, amount):
    """Validate custom membership amount"""
    try:
        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Get standard amount from template, not minimum_amount
        standard_amount = 0
        if membership_type_doc.dues_schedule_template:
            try:
                template = frappe.get_doc(
                    "Membership Dues Schedule", membership_type_doc.dues_schedule_template
                )
                standard_amount = template.dues_rate or template.suggested_amount or 0
            except Exception:
                pass

        # Fallback to minimum_amount if no template amount available
        if not standard_amount:
            standard_amount = membership_type_doc.minimum_amount

        standard_amount = float(standard_amount)

        # Handle null, empty, or invalid amount values
        if amount is None or amount == "null" or amount == "":
            return {"valid": False, "message": _("Please enter a valid amount")}

        try:
            custom_amount = float(amount)
        except (ValueError, TypeError):
            return {"valid": False, "message": _("Please enter a valid numeric amount")}

        # Custom amounts are allowed for all membership types in this simpler approach

        if custom_amount <= 0:
            return {"valid": False, "message": _("Amount must be greater than 0")}

        # Use 50% of standard amount as minimum
        min_amount = standard_amount * 0.5

        if custom_amount < min_amount:
            return {
                "valid": False,
                "message": _("Minimum amount is {0}").format(
                    frappe.utils.fmt_money(min_amount, currency=membership_type_doc.currency or "EUR")
                ),
            }

        # Get maximum fee multiplier from settings
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        maximum_fee_multiplier = getattr(verenigingen_settings, "maximum_fee_multiplier", 10)

        # Use configured multiplier as reasonable maximum, warn if exceeded
        max_reasonable = standard_amount * maximum_fee_multiplier
        warning = None
        if custom_amount > max_reasonable:
            warning = _("Amount is significantly higher than standard - may require review")

        return {"valid": True, "message": _("Valid custom amount"), "warning": warning}

    except Exception as e:
        return {"valid": False, "message": str(e)}


def check_application_eligibility(data):
    """Check if applicant is eligible for membership"""
    eligibility_issues = []
    warnings = []

    # Age check
    if data.get("birth_date"):
        birth_validation = validate_birth_date(data["birth_date"])
        if not birth_validation["valid"]:
            eligibility_issues.append(birth_validation["message"])
        elif birth_validation.get("age", 0) < 12:
            warnings.append(_("Applicants under 12 require parental consent"))
        elif birth_validation.get("age", 0) > 100:
            warnings.append(_("Age verification may be required"))

    # Email uniqueness
    if data.get("email"):
        email_validation = validate_email(data["email"])
        if not email_validation["valid"]:
            eligibility_issues.append(email_validation["message"])

    # Name validation
    for field, label in [("first_name", "First Name"), ("last_name", "Last Name")]:
        if data.get(field):
            name_validation = validate_name(data[field], label)
            if not name_validation["valid"]:
                eligibility_issues.append(name_validation["message"])

    # Address validation
    address_validation = validate_address(data)
    if not address_validation["valid"]:
        eligibility_issues.extend(address_validation["errors"])

    # Check if membership types are available
    available_types = frappe.get_all("Membership Type", filters={"is_active": 1}, fields=["name"])

    if not available_types:
        eligibility_issues.append(_("No membership types are currently available"))

    return {"eligible": len(eligibility_issues) == 0, "issues": eligibility_issues, "warnings": warnings}


@frappe.whitelist()
def debug_application_eligibility():
    """Debug function to test application eligibility validation"""
    # Security check: Only allow debug functions in development or for System Managers
    if not frappe.conf.get("developer_mode") and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Debug functions are only available in development mode or for System Managers"))

    # Test data that should pass
    valid_test_data = {
        "first_name": "Test",
        "last_name": "User",
        "email": f"test-eligibility-{frappe.utils.random_string(8)}@example.com",
        "birth_date": "1990-01-01",
        "address_line1": "Test Street 123",
        "city": "Amsterdam",
        "postal_code": "1000AA",
        "country": "Netherlands",
    }

    # Test data that should fail
    invalid_test_data = {
        "first_name": "",  # Missing required field
        "last_name": "User",
        "email": "invalid-email",  # Invalid email format
        "birth_date": "2020-01-01",  # Too young
        "address_line1": "",  # Missing required field
        "city": "",  # Missing required field
        "postal_code": "",  # Missing required field
        "country": "",  # Missing required field
    }

    try:
        # Test valid data
        valid_result = check_application_eligibility(valid_test_data)

        # Test invalid data
        invalid_result = check_application_eligibility(invalid_test_data)

        # Check if membership types exist
        membership_types = frappe.get_all("Membership Type", filters={"is_active": 1}, fields=["name"])

        return {
            "timestamp": frappe.utils.now(),
            "valid_test": {"data": valid_test_data, "result": valid_result},
            "invalid_test": {"data": invalid_test_data, "result": invalid_result},
            "membership_types_available": len(membership_types),
            "membership_types": [mt.name for mt in membership_types[:3]],  # Show first 3
        }

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


def validate_required_fields(data, required_fields):
    """Validate that all required fields are present and not empty"""
    missing_fields = []

    for field in required_fields:
        if not data.get(field) or str(data.get(field)).strip() == "":
            missing_fields.append(field.replace("_", " ").title())

    return {"valid": len(missing_fields) == 0, "missing_fields": missing_fields}
