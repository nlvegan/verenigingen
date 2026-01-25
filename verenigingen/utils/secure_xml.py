"""
Secure XML Parsing Utilities

This module provides secure XML parsing functions that protect against
common XML-based attacks:
- XXE (XML External Entity) attacks
- Billion laughs / XML bomb attacks
- Entity expansion attacks
- External DTD loading

All XML parsing in the application should use these functions instead
of the standard library xml.etree.ElementTree.

Usage:
    from verenigingen.utils.secure_xml import parse_xml_safely

    root = parse_xml_safely(xml_content)
"""

from typing import Optional, Union
from xml.etree.ElementTree import Element

import frappe

try:
    import defusedxml.ElementTree as ET
    from defusedxml import DefusedXmlException

    DEFUSEDXML_AVAILABLE = True
except ImportError:
    # Fallback to standard library with warnings
    import xml.etree.ElementTree as ET

    DefusedXmlException = Exception
    DEFUSEDXML_AVAILABLE = False
    frappe.logger().warning(
        "defusedxml not installed. XML parsing is vulnerable to XXE attacks. "
        "Install with: pip install defusedxml>=0.7.1"
    )

# Security limits
MAX_XML_SIZE_BYTES = 10 * 1024 * 1024  # 10MB max for general XML
MAX_SEPA_RETURN_SIZE_BYTES = 5 * 1024 * 1024  # 5MB max for SEPA return files
MAX_BANK_STATEMENT_SIZE_BYTES = 20 * 1024 * 1024  # 20MB for bank statements


class XMLSecurityError(Exception):
    """Raised when XML content fails security validation."""

    pass


class XMLSizeError(XMLSecurityError):
    """Raised when XML content exceeds size limits."""

    pass


def parse_xml_safely(
    xml_content: Union[str, bytes],
    max_size: Optional[int] = None,
    source_description: str = "XML content",
) -> Element:
    """
    Parse XML content with security protections.

    Uses defusedxml to protect against:
    - XXE (XML External Entity) attacks
    - Billion laughs (entity expansion bombs)
    - External DTD loading
    - Quadratic blowup attacks

    Args:
        xml_content: XML string or bytes to parse
        max_size: Maximum allowed size in bytes (default: MAX_XML_SIZE_BYTES)
        source_description: Description for error messages (e.g., "pain.002 file")

    Returns:
        ElementTree Element (root of parsed XML)

    Raises:
        XMLSizeError: If content exceeds max_size
        XMLSecurityError: If malicious XML patterns detected
        ValueError: If XML is malformed
    """
    if max_size is None:
        max_size = MAX_XML_SIZE_BYTES

    # Convert to bytes for size check
    if isinstance(xml_content, str):
        content_bytes = xml_content.encode("utf-8")
    else:
        content_bytes = xml_content

    # Size check - prevent DoS via large files
    if len(content_bytes) > max_size:
        raise XMLSizeError(
            f"{source_description} exceeds maximum size of {max_size:,} bytes "
            f"(received {len(content_bytes):,} bytes)"
        )

    try:
        # defusedxml automatically protects against:
        # - XXE (forbid_dtd, forbid_entities, forbid_external)
        # - Billion laughs (max_entity_expansions)
        # - External DTD loading
        if isinstance(xml_content, bytes):
            xml_content = xml_content.decode("utf-8")

        return ET.fromstring(xml_content)

    except DefusedXmlException as e:
        # Log security violation for monitoring
        frappe.log_error(
            f"XML security violation in {source_description}: {e}",
            "XML Security Alert",
        )
        raise XMLSecurityError(f"XML security violation: {e}") from e

    except ET.ParseError as e:
        raise ValueError(f"Malformed XML in {source_description}: {e}") from e


def parse_xml_file_safely(
    file_path: str,
    max_size: Optional[int] = None,
) -> Element:
    """
    Parse an XML file with security protections.

    Args:
        file_path: Path to XML file
        max_size: Maximum allowed file size (default: MAX_XML_SIZE_BYTES)

    Returns:
        ElementTree Element (root of parsed XML)

    Raises:
        XMLSizeError: If file exceeds max_size
        XMLSecurityError: If malicious XML patterns detected
        FileNotFoundError: If file doesn't exist
        ValueError: If XML is malformed
    """
    import os

    if max_size is None:
        max_size = MAX_XML_SIZE_BYTES

    # Check file size before reading
    file_size = os.path.getsize(file_path)
    if file_size > max_size:
        raise XMLSizeError(
            f"XML file exceeds maximum size of {max_size:,} bytes " f"(file is {file_size:,} bytes)"
        )

    with open(file_path, "rb") as f:
        content = f.read()

    return parse_xml_safely(content, max_size=max_size, source_description=file_path)


def is_defusedxml_available() -> bool:
    """Check if defusedxml is properly installed."""
    return DEFUSEDXML_AVAILABLE
