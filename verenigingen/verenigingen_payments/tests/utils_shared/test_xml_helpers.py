"""Tests for shared SEPA XML helpers.

Verifies that extract_xml_namespace, get_element_text, and build_postal_address
produce output identical to the original inline implementations they consolidate.
"""

import unittest
import xml.etree.ElementTree as ET


class TestExtractXmlNamespace(unittest.TestCase):
    """extract_xml_namespace must reproduce both _detect_namespace and _extract_namespace."""

    def test_extracts_namespace_from_clark_notation_tag(self):
        """Root tag '{urn:test}Doc' → 'urn:test'."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import extract_xml_namespace

        root = ET.Element("{urn:test}Doc")
        result = extract_xml_namespace(root, default="fallback")
        self.assertEqual(result, "urn:test")

    def test_extracts_pain008_namespace(self):
        """Real pain.008 namespace URI is extracted correctly."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import extract_xml_namespace

        ns_uri = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
        root = ET.Element(f"{{{ns_uri}}}Document")
        result = extract_xml_namespace(root, default="fallback")
        self.assertEqual(result, ns_uri)

    def test_extracts_pain002_namespace(self):
        """Real pain.002 namespace URI is extracted correctly."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import extract_xml_namespace

        ns_uri = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.03"
        root = ET.Element(f"{{{ns_uri}}}Document")
        result = extract_xml_namespace(root, default="fallback")
        self.assertEqual(result, ns_uri)

    def test_returns_default_when_tag_has_no_namespace(self):
        """Tag without Clark notation → default."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import extract_xml_namespace

        root = ET.Element("Document")
        result = extract_xml_namespace(root, default="my-default")
        self.assertEqual(result, "my-default")

    def test_returns_default_when_tag_is_empty(self):
        """Empty tag string → default."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import extract_xml_namespace

        # Simulate getattr fallback path (object with no .tag)
        class FakeRoot:
            tag = ""

        result = extract_xml_namespace(FakeRoot(), default="x")
        self.assertEqual(result, "x")

    def test_returns_default_for_opening_brace_only(self):
        """Tag '{' with no closing brace → default."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import extract_xml_namespace

        class FakeRoot:
            tag = "{"

        result = extract_xml_namespace(FakeRoot(), default="default-ns")
        self.assertEqual(result, "default-ns")

    def test_namespace_with_longer_path(self):
        """Namespace URI containing slashes is extracted verbatim."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import extract_xml_namespace

        ns_uri = "http://www.example.com/schema/v2"
        root = ET.Element(f"{{{ns_uri}}}Root")
        result = extract_xml_namespace(root, default="fallback")
        self.assertEqual(result, ns_uri)


class TestGetElementText(unittest.TestCase):
    """get_element_text must reproduce _get_text from sepa_return_parser."""

    def _make_parent(self):
        """Build a small element tree for tests."""
        parent = ET.Element("Parent")
        child = ET.SubElement(parent, "Child")
        child.text = "hello"
        return parent

    def test_returns_child_text_via_tag_path(self):
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import get_element_text

        parent = self._make_parent()
        result = get_element_text(parent, "Child", {})
        self.assertEqual(result, "hello")

    def test_returns_none_when_element_missing_and_no_default(self):
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import get_element_text

        parent = self._make_parent()
        result = get_element_text(parent, "Missing", {})
        self.assertIsNone(result)

    def test_returns_default_when_element_missing(self):
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import get_element_text

        parent = self._make_parent()
        result = get_element_text(parent, "Missing", {}, default="N/A")
        self.assertEqual(result, "N/A")

    def test_returns_none_when_element_found_but_text_is_none(self):
        """Element found but text=None → None returned (not default).

        The original _get_text returns ``child.text if child is not None``,
        so the default is only used when the element itself is missing.
        An element that exists but has no text node returns None directly.
        """
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import get_element_text

        parent = ET.Element("Parent")
        ET.SubElement(parent, "Empty")  # element exists, text is None
        result = get_element_text(parent, "Empty", {}, default="fallback")
        # Matches the original: child is not None, so child.text (= None) is returned.
        self.assertIsNone(result)

    def test_works_with_namespace_dict(self):
        """Namespaced path lookup via ns dict."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import get_element_text

        ns = {"sepa": "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"}
        parent = ET.Element(f"{{{ns['sepa']}}}Parent")
        child = ET.SubElement(parent, f"{{{ns['sepa']}}}MsgId")
        child.text = "MSG-001"
        result = get_element_text(parent, "sepa:MsgId", ns)
        self.assertEqual(result, "MSG-001")

    def test_returns_empty_string_as_is(self):
        """Empty string text is returned as empty string (not replaced by default)."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import get_element_text

        parent = ET.Element("Parent")
        child = ET.SubElement(parent, "Empty")
        child.text = ""
        result = get_element_text(parent, "Empty", {}, default="nope")
        # The original _get_text returns child.text if child is not None,
        # so "" is a valid non-None text value — returned as-is.
        self.assertEqual(result, "")


class TestBuildPostalAddress(unittest.TestCase):
    """build_postal_address must produce IDENTICAL sub-element tags and order to the
    original creditor/debtor blocks in sepa_xml_enhanced_generator.py."""

    def test_produces_no_children_when_all_fields_empty(self):
        """No address fields → no PstlAdr appended to parent."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(parent, {})
        self.assertEqual(len(list(parent)), 0)

    def test_produces_no_children_when_all_fields_falsy(self):
        """Explicitly None/empty fields → no PstlAdr appended."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(
            parent,
            {
                "address_line_1": None,
                "address_line_2": None,
                "postal_code": None,
                "town": None,
            },
        )
        self.assertEqual(len(list(parent)), 0)

    def test_appends_pstladr_when_any_field_set(self):
        """At least one address field → PstlAdr child appended."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(parent, {"town": "Amsterdam", "country": "NL"})
        children = list(parent)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].tag, "PstlAdr")

    def test_ctry_is_first_child_of_pstladr(self):
        """Ctry must be the FIRST element inside PstlAdr (matches original generator order)."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(
            parent,
            {
                "country": "NL",
                "address_line_1": "Keizersgracht 1",
                "address_line_2": "3e verdieping",
                "postal_code": "1015 CW",
                "town": "Amsterdam",
            },
        )
        pstl_adr = parent.find("PstlAdr")
        self.assertIsNotNone(pstl_adr)
        children = list(pstl_adr)
        self.assertEqual(children[0].tag, "Ctry")
        self.assertEqual(children[0].text, "NL")

    def test_full_address_element_order(self):
        """Full address → Ctry, AdrLine, AdrLine, PstCd, TwnNm (exact original order)."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(
            parent,
            {
                "country": "NL",
                "address_line_1": "Line 1",
                "address_line_2": "Line 2",
                "postal_code": "1234 AB",
                "town": "Utrecht",
            },
        )
        pstl_adr = parent.find("PstlAdr")
        children = list(pstl_adr)
        tags = [c.tag for c in children]
        # Original order: Ctry, AdrLine (1), AdrLine (2), PstCd, TwnNm
        self.assertEqual(tags, ["Ctry", "AdrLine", "AdrLine", "PstCd", "TwnNm"])
        texts = [c.text for c in children]
        self.assertEqual(texts, ["NL", "Line 1", "Line 2", "1234 AB", "Utrecht"])

    def test_optional_fields_omitted_when_missing(self):
        """Only country + town: AdrLine and PstCd are not emitted."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Dbtr")
        build_postal_address(parent, {"country": "DE", "town": "Berlin"})
        pstl_adr = parent.find("PstlAdr")
        tags = [c.tag for c in list(pstl_adr)]
        self.assertNotIn("AdrLine", tags)
        self.assertNotIn("PstCd", tags)
        self.assertIn("Ctry", tags)
        self.assertIn("TwnNm", tags)

    def test_only_address_line_1_set(self):
        """address_line_1 set but not 2 → single AdrLine, no PstCd, no TwnNm."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(parent, {"country": "NL", "address_line_1": "Hoofdstraat 5"})
        pstl_adr = parent.find("PstlAdr")
        children = list(pstl_adr)
        tags = [c.tag for c in children]
        self.assertEqual(tags.count("AdrLine"), 1)
        adr = pstl_adr.find("AdrLine")
        self.assertEqual(adr.text, "Hoofdstraat 5")

    def test_postal_code_without_town(self):
        """postal_code set but not town → PstCd present, TwnNm absent."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(parent, {"country": "NL", "postal_code": "2500 GH"})
        pstl_adr = parent.find("PstlAdr")
        tags = [c.tag for c in list(pstl_adr)]
        self.assertIn("PstCd", tags)
        self.assertNotIn("TwnNm", tags)

    def test_country_defaults_to_empty_string_when_not_given(self):
        """country key absent → Ctry element still emitted (with empty/None text)."""
        from verenigingen.verenigingen_payments.utils.shared.xml_helpers import build_postal_address

        parent = ET.Element("Cdtr")
        build_postal_address(parent, {"town": "Rotterdam"})
        pstl_adr = parent.find("PstlAdr")
        self.assertIsNotNone(pstl_adr)
        ctry = pstl_adr.find("Ctry")
        self.assertIsNotNone(ctry)


if __name__ == "__main__":
    unittest.main()
