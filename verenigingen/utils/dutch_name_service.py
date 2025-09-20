"""
Dutch Name Service - Centralized Dutch name validation and formatting.

This service handles Dutch-specific name formatting including tussenvoegsel
(name particles) and name validation. Extracted from member.py for reusability.

Functions:
    - validate_member_name_fields(): Validate name fields for special characters
    - update_member_full_name(): Generate full name with Dutch naming conventions
    - format_name_field(): Individual name field formatting
"""

import re

import frappe
from frappe import _

from verenigingen.utils.service_error_handler import handle_service_error, safe_import

# Safe imports with fallbacks for Dutch utilities
try:
    from verenigingen.utils.dutch_name_utils import format_dutch_full_name, is_dutch_installation
except ImportError as e:
    handle_service_error(
        e,
        "DutchNameService",
        "Import Dutch utilities",
        {"fallback_used": True},
        raise_error=False,
        log_level="warning",
    )

    # Fallback implementations
    def format_dutch_full_name(first_name, middle_name, tussenvoegsel, last_name):
        """Fallback Dutch name formatter"""
        parts = [p for p in [first_name, tussenvoegsel, last_name] if p]
        return " ".join(parts)

    def is_dutch_installation():
        """Fallback Dutch installation check"""
        return False


def validate_member_name_fields(member_doc):
    """Validate that name fields don't contain special characters.

    Extracted from member.py without modification. Uses application_validators
    for consistent validation across the system.

    Args:
        member_doc: Member document instance to validate

    Raises:
        frappe.ValidationError: If any name field contains invalid characters
    """
    for field in ["first_name", "middle_name", "last_name"]:
        if not hasattr(member_doc, field) or not getattr(member_doc, field):
            continue

        # Use the improved validation from application_validators
        try:
            from verenigingen.utils.validation.application_validators import validate_name

            field_value = getattr(member_doc, field)
            field_name = field.replace("_", " ").title()

            validation_result = validate_name(field_value, field_name)

            if not validation_result["valid"]:
                frappe.throw(_(validation_result["message"]))

            # Use sanitized version if available
            if validation_result.get("sanitized"):
                setattr(member_doc, field, validation_result["sanitized"])

        except ImportError:
            # Fallback to basic validation if import fails
            field_value = getattr(member_doc, field)
            # Allow letters, spaces, hyphens, apostrophes, and accented characters
            if not re.match(
                r"^[\w\s\-\'\.\u00C0-\u017F\u0100-\u024F\u1E00-\u1EFF]+$", field_value, re.UNICODE
            ):
                frappe.throw(_("{0} contains invalid characters").format(field.replace("_", " ").title()))


def update_member_full_name(member_doc):
    """Update the full name based on first names, name particles (tussenvoegsels), and last name.

    Extracted from member.py without modification. Handles both Dutch naming conventions
    with tussenvoegsel field and legacy middle_name approach.

    Args:
        member_doc: Member document instance to update
    """
    # For Dutch installations, prioritize tussenvoegsel field over middle_name
    if is_dutch_installation() and hasattr(member_doc, "tussenvoegsel") and member_doc.tussenvoegsel:
        full_name = format_dutch_full_name(
            member_doc.first_name,
            None,  # Don't use middle_name for Dutch names when tussenvoegsel is available
            member_doc.tussenvoegsel,
            member_doc.last_name,
        )
    else:
        # Build full name with proper handling of name particles (legacy approach)
        name_parts = []

        if member_doc.first_name:
            name_parts.append(member_doc.first_name.strip())

        # Handle name particles (tussenvoegsels) - these should be lowercase when in the middle
        if member_doc.middle_name:
            particles = member_doc.middle_name.strip()
            # Check if it's a Dutch particle (like van, de, der, etc.) or a regular middle name
            dutch_particles = ["van", "de", "der", "den", "ter", "te", "het", "'t", "op", "in"]

            if particles:
                # Split to handle compound particles like "van der"
                words = particles.split()
                if words and words[0].lower() in dutch_particles:
                    # It's a particle, make it lowercase
                    name_parts.append(particles.lower())
                else:
                    # It's a regular middle name, keep original casing
                    name_parts.append(particles)

        if member_doc.last_name:
            name_parts.append(member_doc.last_name.strip())

        full_name = " ".join(name_parts)

    member_doc.full_name = None
    if member_doc.full_name != full_name:
        member_doc.full_name = full_name


def format_name_field(field_value, field_name):
    """Format and validate a single name field.

    Args:
        field_value (str): The name field value to validate
        field_name (str): Human-readable field name for error messages

    Returns:
        dict: Validation result with valid/sanitized fields

    Raises:
        frappe.ValidationError: If validation fails
    """
    if not field_value:
        return {"valid": True, "sanitized": field_value}

    try:
        from verenigingen.utils.validation.application_validators import validate_name

        return validate_name(field_value, field_name)
    except ImportError:
        # Fallback validation
        if not re.match(r"^[\w\s\-\'\.\u00C0-\u017F\u0100-\u024F\u1E00-\u1EFF]+$", field_value, re.UNICODE):
            frappe.throw(_("{0} contains invalid characters").format(field_name))
        return {"valid": True, "sanitized": field_value}


def normalize_dutch_name_particles(particles):
    """Normalize Dutch name particles (tussenvoegsels) to proper casing.

    Args:
        particles (str): Name particles to normalize

    Returns:
        str: Normalized particles with proper casing
    """
    if not particles:
        return particles

    dutch_particles = ["van", "de", "der", "den", "ter", "te", "het", "'t", "op", "in"]
    words = particles.split()

    normalized_words = []
    for word in words:
        if word.lower() in dutch_particles:
            normalized_words.append(word.lower())
        else:
            normalized_words.append(word)

    return " ".join(normalized_words)


def is_valid_dutch_tussenvoegsel(tussenvoegsel):
    """Check if tussenvoegsel is a valid Dutch name particle.

    Consolidated validation using the most comprehensive list of Dutch and
    international name particles found in Dutch applications.

    Args:
        tussenvoegsel (str): Name particle to validate

    Returns:
        bool: True if valid tussenvoegsel
    """
    if not tussenvoegsel:
        return True  # Empty is valid

    # Comprehensive list from enhanced_membership_application.py plus our existing particles
    valid_particles = [
        "van",
        "de",
        "der",
        "den",
        "het",
        "'t",
        "ter",
        "te",
        "op",
        "in",
        "van der",
        "van den",
        "van het",
        "van de",
        "von",
        "du",
        "da",
        "di",
        "del",
        "della",
    ]

    return tussenvoegsel.lower() in valid_particles


def get_dutch_full_name_parts(member_doc):
    """Get the components of a Dutch full name for external processing.

    Args:
        member_doc: Member document instance

    Returns:
        dict: Dictionary with first_name, tussenvoegsel, last_name parts
    """
    if is_dutch_installation() and hasattr(member_doc, "tussenvoegsel"):
        return {
            "first_name": getattr(member_doc, "first_name", ""),
            "tussenvoegsel": getattr(member_doc, "tussenvoegsel", ""),
            "last_name": getattr(member_doc, "last_name", ""),
        }
    else:
        # Parse middle_name for Dutch particles
        middle_name = getattr(member_doc, "middle_name", "")
        tussenvoegsel = ""

        if middle_name:
            dutch_particles = ["van", "de", "der", "den", "ter", "te", "het", "'t", "op", "in"]
            words = middle_name.split()
            if words and words[0].lower() in dutch_particles:
                tussenvoegsel = middle_name.lower()

        return {
            "first_name": getattr(member_doc, "first_name", ""),
            "tussenvoegsel": tussenvoegsel,
            "last_name": getattr(member_doc, "last_name", ""),
        }
