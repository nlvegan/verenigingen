"""Shared SEPA XML helper utilities.

These three helpers consolidate identical patterns that were previously inlined
in sepa_return_parser, sepa_rulebook_validator, and sepa_xml_enhanced_generator.
They are intentionally free of any Frappe dependency so they can be tested with
plain ``unittest.TestCase`` and reused from any context.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional


def extract_xml_namespace(root, *, default: str) -> str:
    """Return the namespace URI embedded in *root.tag*, or *default*.

    ElementTree represents Clark-notation tags as ``{uri}localname``.  This
    function strips the ``{…}`` wrapper and returns the bare URI.  If the tag
    carries no namespace (or *root* has no ``.tag`` attribute), *default* is
    returned unchanged.

    Reproduces the logic of both:
    - ``SEPAReturnParser._detect_namespace`` in sepa_return_parser.py
    - ``SEPARulebookValidator._extract_namespace`` in sepa_rulebook_validator.py

    Args:
        root: Parsed XML element (or any object with a ``tag`` attribute).
        default: Value to return when no namespace can be detected.

    Returns:
        Namespace URI string, or *default*.
    """
    tag = getattr(root, "tag", "")
    if tag.startswith("{"):
        closing = tag.find("}")
        if closing > 0:
            return tag[1:closing]
    return default


def get_element_text(
    element: ET.Element, path: str, ns: dict, *, default: Optional[str] = None
) -> Optional[str]:
    """Return the text of the first sub-element matching *path*, or *default*.

    A safe wrapper around ``element.find(path, ns).text`` that avoids
    ``AttributeError`` when the element is absent.  When the element is found
    but its ``.text`` is ``None`` (i.e. an empty tag with no text node), the
    raw ``None`` is returned — callers that require a non-None fallback should
    pass an explicit *default*.

    Reproduces:
    - ``SEPAReturnParser._get_text`` in sepa_return_parser.py
    - The inline ``element.find(…).text`` pattern in sepa_rulebook_validator.py

    Args:
        element: The parent XML element to search within.
        path: XPath expression (ElementTree subset).
        ns: Namespace prefix-to-URI mapping dict.
        default: Returned when *path* matches nothing.

    Returns:
        Text string, ``None`` (when text node is absent), or *default*.
    """
    child = element.find(path, ns)
    if child is None:
        return default
    return child.text


def build_postal_address(parent: ET.Element, address: dict) -> None:
    """Append a SEPA ``PstlAdr`` block to *parent* if any address field is set.

    The sub-element tag names and their order match the creditor block in
    ``SEPAXMLEnhancedGenerator._generate_creditor_info`` and the debtor block
    in ``_generate_debtor_info`` exactly:

    .. code-block:: xml

        <PstlAdr>
            <Ctry>NL</Ctry>
            <AdrLine>Street 1</AdrLine>   <!-- only when address_line_1 set -->
            <AdrLine>Apt 2</AdrLine>       <!-- only when address_line_2 set -->
            <PstCd>1234 AB</PstCd>         <!-- only when postal_code set    -->
            <TwnNm>Amsterdam</TwnNm>       <!-- only when town set            -->
        </PstlAdr>

    The outer ``<PstlAdr>`` is only added when at least one of the four
    optional fields (``address_line_1``, ``address_line_2``, ``postal_code``,
    ``town``) is truthy — matching the ``any([…])`` guard in the original.

    Args:
        parent: The XML element to which ``PstlAdr`` will be appended
                (e.g. ``Cdtr`` or ``Dbtr``).
        address: Dict with optional keys ``country``, ``address_line_1``,
                 ``address_line_2``, ``postal_code``, ``town``.
    """
    address_line_1 = address.get("address_line_1")
    address_line_2 = address.get("address_line_2")
    postal_code = address.get("postal_code")
    town = address.get("town")

    if not any([address_line_1, address_line_2, postal_code, town]):
        return

    pstl_adr = ET.SubElement(parent, "PstlAdr")
    ET.SubElement(pstl_adr, "Ctry").text = address.get("country")

    if address_line_1:
        ET.SubElement(pstl_adr, "AdrLine").text = address_line_1
    if address_line_2:
        ET.SubElement(pstl_adr, "AdrLine").text = address_line_2
    if postal_code:
        ET.SubElement(pstl_adr, "PstCd").text = postal_code
    if town:
        ET.SubElement(pstl_adr, "TwnNm").text = town
