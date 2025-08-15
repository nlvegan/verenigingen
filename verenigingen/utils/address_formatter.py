"""
Address formatting utilities for different countries
"""

import html

import frappe

from verenigingen.utils.api_response import APIResponse, api_response_handler
from verenigingen.utils.error_handling import cache_with_ttl


def format_address_for_country(address_doc):
    """Format address according to country-specific conventions"""

    if not address_doc:
        return ""

    country = (address_doc.country or "").strip().lower()

    # Dutch address format
    if country in ["netherlands", "nederland", "nl"]:
        return format_dutch_address(address_doc)

    # Default international format
    return format_international_address(address_doc)


def format_dutch_address(address_doc):
    """
    Format address according to Dutch conventions:
    Line 1: Street name + house number
    Line 2: Postal code + City
    Line 3: Country (if not Netherlands)
    """
    lines = []

    # Line 1: Street + house number (address_line1)
    if address_doc.address_line1:
        lines.append(html.escape(address_doc.address_line1.strip()))

    # Line 2: Additional address info (address_line2) if present
    if address_doc.address_line2 and address_doc.address_line2.strip():
        lines.append(html.escape(address_doc.address_line2.strip()))

    # Line 3: Postal code + City (Dutch standard format)
    postal_city_line = []

    # Add postal code first (Dutch convention)
    if address_doc.pincode:
        postal_city_line.append(html.escape(address_doc.pincode.strip()))

    # Then add city
    if address_doc.city:
        postal_city_line.append(html.escape(address_doc.city.strip()))

    if postal_city_line:
        lines.append(" ".join(postal_city_line))

    # State (province) if present - not common in NL but include if specified
    if address_doc.state and address_doc.state.strip():
        lines.append(html.escape(address_doc.state.strip()))

    # Country - only show if not Netherlands or if specifically requested
    NETHERLANDS_IDENTIFIERS = {"netherlands", "nederland", "nl"}
    country = (address_doc.country or "").strip().lower()
    if country and country not in NETHERLANDS_IDENTIFIERS:
        lines.append(html.escape(address_doc.country))

    return "<br>".join(lines)


def format_international_address(address_doc):
    """
    Format address using international conventions:
    Line 1: Street address
    Line 2: Additional address info
    Line 3: City, State/Province
    Line 4: Postal code
    Line 5: Country
    """
    lines = []

    # Street address
    if address_doc.address_line1:
        lines.append(html.escape(address_doc.address_line1.strip()))

    # Additional address info
    if address_doc.address_line2 and address_doc.address_line2.strip():
        lines.append(html.escape(address_doc.address_line2.strip()))

    # City and state line
    city_state_parts = []
    if address_doc.city:
        city_state_parts.append(html.escape(address_doc.city.strip()))
    if address_doc.state:
        city_state_parts.append(html.escape(address_doc.state.strip()))

    if city_state_parts:
        lines.append(", ".join(city_state_parts))

    # Postal code
    if address_doc.pincode:
        lines.append(html.escape(address_doc.pincode.strip()))

    # Country
    if address_doc.country:
        lines.append(html.escape(address_doc.country.strip()))

    return "<br>".join(lines)


def format_address_single_line(address_doc):
    """Format address as a single line for compact display"""

    if not address_doc:
        return ""

    parts = []

    # Street address
    if address_doc.address_line1:
        parts.append(address_doc.address_line1.strip())

    # Additional address
    if address_doc.address_line2 and address_doc.address_line2.strip():
        parts.append(address_doc.address_line2.strip())

    # For Dutch addresses: postal code + city
    country = (address_doc.country or "").strip().lower()
    if country in ["netherlands", "nederland", "nl"]:
        postal_city = []
        if address_doc.pincode:
            postal_city.append(address_doc.pincode.strip())
        if address_doc.city:
            postal_city.append(address_doc.city.strip())
        if postal_city:
            parts.append(" ".join(postal_city))
    else:
        # International: city, state, postal code
        if address_doc.city:
            parts.append(address_doc.city.strip())
        if address_doc.state:
            parts.append(address_doc.state.strip())
        if address_doc.pincode:
            parts.append(address_doc.pincode.strip())

    # Country (if not Netherlands)
    if address_doc.country and country not in ["netherlands", "nederland", "nl"]:
        parts.append(address_doc.country.strip())

    return ", ".join(parts)


@frappe.whitelist()
@api_response_handler
@cache_with_ttl(ttl=1800)  # Cache for 30 minutes - addresses don't change frequently
def format_member_address(member_name):
    """Format a member's primary address using appropriate country conventions"""
    member = frappe.get_doc("Member", member_name, ignore_permissions=True)

    if not member.primary_address:
        return {"has_address": False, "formatted_address": None, "message": "No address found for member"}

    address = frappe.get_doc("Address", member.primary_address, ignore_permissions=True)
    formatted = format_address_for_country(address)

    return {
        "has_address": True,
        "formatted_address": formatted,
        "country": address.country,
        "address_type": "primary",
    }


@frappe.whitelist()
def test_address_formatting():
    """Test the address formatting with sample data"""
    try:
        # Get Foppe's address
        address_doc = frappe.get_doc("Address", "Foppe Haan-Personal", ignore_permissions=True)

        dutch_format = format_dutch_address(address_doc)
        international_format = format_international_address(address_doc)
        single_line = format_address_single_line(address_doc)
        auto_format = format_address_for_country(address_doc)

        return {
            "success": True,
            "address_data": {
                "address_line1": address_doc.address_line1,
                "address_line2": address_doc.address_line2,
                "city": address_doc.city,
                "state": address_doc.state,
                "country": address_doc.country,
                "pincode": address_doc.pincode,
            },
            "formats": {
                "dutch": dutch_format,
                "international": international_format,
                "single_line": single_line,
                "auto_detect": auto_format,
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
