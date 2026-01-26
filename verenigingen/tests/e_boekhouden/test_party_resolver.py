"""
Tests for E-Boekhouden Party Resolver

Tests the party resolution module which handles Customer/Supplier creation
and management during E-Boekhouden data import.

Key functionality tested:
- Party name extraction from various API field formats
- Duplicate name handling and deduplication
- Provisional party creation when API is unavailable
- Party update with fresh API data
- Generic resolution logic for both Customer and Supplier

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_party_resolver
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe


class TestPartyConfig(unittest.TestCase):
    """Tests for PARTY_CONFIG structure validation"""

    def test_party_config_has_required_keys(self):
        """Test that PARTY_CONFIG has Customer and Supplier configurations"""
        from verenigingen.e_boekhouden.utils.party_resolver import PARTY_CONFIG

        self.assertIn("Customer", PARTY_CONFIG)
        self.assertIn("Supplier", PARTY_CONFIG)

    def test_customer_config_has_required_fields(self):
        """Test that Customer config has all required fields"""
        from verenigingen.e_boekhouden.utils.party_resolver import PARTY_CONFIG

        customer_config = PARTY_CONFIG["Customer"]

        required_fields = [
            "doctype",
            "name_field",
            "type_field",
            "group_field",
            "default_group",
            "territory_field",
            "default_territory",
            "provisional_prefix",
        ]

        for field in required_fields:
            self.assertIn(field, customer_config, f"Missing field: {field}")

        self.assertEqual(customer_config["doctype"], "Customer")
        self.assertEqual(customer_config["name_field"], "customer_name")
        self.assertEqual(customer_config["territory_field"], "territory")

    def test_supplier_config_has_required_fields(self):
        """Test that Supplier config has all required fields"""
        from verenigingen.e_boekhouden.utils.party_resolver import PARTY_CONFIG

        supplier_config = PARTY_CONFIG["Supplier"]

        self.assertEqual(supplier_config["doctype"], "Supplier")
        self.assertEqual(supplier_config["name_field"], "supplier_name")
        self.assertIsNone(supplier_config["territory_field"])  # Suppliers don't have territory


class TestExtractPartyNameAndType(unittest.TestCase):
    """Tests for _extract_party_name_and_type method"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_extracts_name_from_rest_api_name_field(self, mock_frappe):
        """Test extraction from REST API 'name' field"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "name": "Test Company B.V.",
            "type": "B",  # Business
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Customer", self.debug_info
        )

        self.assertEqual(name, "Test Company B.V.")
        self.assertEqual(entity_type, "Company")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_extracts_individual_from_personal_type(self, mock_frappe):
        """Test that type 'P' results in Individual entity type"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "name": "Jan de Vries",
            "type": "P",  # Personal
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Customer", self.debug_info
        )

        self.assertEqual(name, "Jan de Vries")
        self.assertEqual(entity_type, "Individual")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_extracts_from_legacy_dutch_company_field(self, mock_frappe):
        """Test extraction from legacy 'bedrijfsnaam' field"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "bedrijfsnaam": "Nederlandse Vegetariersbond",
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Customer", self.debug_info
        )

        self.assertEqual(name, "Nederlandse Vegetariersbond")
        self.assertEqual(entity_type, "Company")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_extracts_from_legacy_dutch_name_fields(self, mock_frappe):
        """Test extraction from legacy 'voornaam' and 'achternaam' fields"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "voornaam": "Pieter",
            "achternaam": "van der Berg",
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Customer", self.debug_info
        )

        self.assertEqual(name, "Pieter van der Berg")
        self.assertEqual(entity_type, "Individual")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_extracts_from_english_name_fields(self, mock_frappe):
        """Test extraction from English field names (companyName, firstName, lastName)"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "firstName": "John",
            "lastName": "Smith",
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Customer", self.debug_info
        )

        self.assertEqual(name, "John Smith")
        self.assertEqual(entity_type, "Individual")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_fallback_for_customer_with_empty_data(self, mock_frappe):
        """Test fallback name generation for Customer with empty data"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "456",
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Customer", self.debug_info
        )

        self.assertEqual(name, "E-Boekhouden Relation 456")
        self.assertEqual(entity_type, "Individual")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_fallback_for_supplier_with_empty_data(self, mock_frappe):
        """Test fallback name generation for Supplier with empty data"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "789",
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Supplier", self.debug_info
        )

        self.assertEqual(name, "Supplier 789 (eBoekhouden)")
        self.assertEqual(entity_type, "Individual")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_strips_whitespace_from_name(self, mock_frappe):
        """Test that whitespace is stripped from extracted names"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "name": "  Whitespace Company  ",
            "type": "B",
        }

        name, entity_type = resolver._extract_party_name_and_type(
            relation_details, "Customer", self.debug_info
        )

        self.assertEqual(name, "Whitespace Company")


class TestHandleDuplicateName(unittest.TestCase):
    """Tests for _handle_duplicate_name method"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_no_duplicate_returns_original_name(self, mock_frappe):
        """Test that original name is returned when no duplicate exists"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.exists.return_value = False

        resolver = EBoekhoudenPartyResolver()

        final_name, already_exists = resolver._handle_duplicate_name(
            "Customer", "New Company B.V.", "123", self.debug_info
        )

        self.assertEqual(final_name, "New Company B.V.")
        self.assertFalse(already_exists)

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_same_relation_returns_existing(self, mock_frappe):
        """Test that existing party is returned when same relation ID"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.exists.return_value = True
        mock_frappe.db.get_value.return_value = "123"  # Same relation code

        resolver = EBoekhoudenPartyResolver()

        final_name, already_exists = resolver._handle_duplicate_name(
            "Customer", "Existing Company", "123", self.debug_info
        )

        self.assertEqual(final_name, "Existing Company")
        self.assertTrue(already_exists)
        self.assertTrue(any("same relation code" in msg for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_different_relation_creates_unique_name(self, mock_frappe):
        """Test that unique name is created when different relation ID"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.exists.side_effect = [True, False]  # Original exists, unique doesn't
        mock_frappe.db.get_value.return_value = "999"  # Different relation code

        resolver = EBoekhoudenPartyResolver()

        final_name, already_exists = resolver._handle_duplicate_name(
            "Customer", "Duplicate Company", "123", self.debug_info
        )

        self.assertEqual(final_name, "Duplicate Company (123)")
        self.assertFalse(already_exists)
        self.assertTrue(any("unique name" in msg for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_truncates_long_names(self, mock_frappe):
        """Test that names longer than 140 chars are truncated"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.exists.return_value = False

        resolver = EBoekhoudenPartyResolver()

        long_name = "A" * 200  # 200 characters

        final_name, already_exists = resolver._handle_duplicate_name(
            "Customer", long_name, "123", self.debug_info
        )

        self.assertEqual(len(final_name), 140)
        self.assertFalse(already_exists)


class TestCreateProvisionalParty(unittest.TestCase):
    """Tests for _create_provisional_party method"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_creates_provisional_customer(self, mock_frappe):
        """Test provisional customer creation with correct naming"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.exists.return_value = False

        mock_doc = MagicMock()
        mock_doc.name = "E-Boekhouden Customer 123"
        mock_frappe.new_doc.return_value = mock_doc

        resolver = EBoekhoudenPartyResolver()

        result = resolver._create_provisional_party("Customer", "123", self.debug_info)

        mock_frappe.new_doc.assert_called_once_with("Customer")
        self.assertEqual(mock_doc.customer_name, "E-Boekhouden Customer 123")
        self.assertEqual(mock_doc.customer_group, "All Customer Groups")
        self.assertEqual(mock_doc.territory, "All Territories")
        self.assertEqual(mock_doc.eboekhouden_relation_code, "123")
        mock_doc.insert.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_creates_provisional_supplier(self, mock_frappe):
        """Test provisional supplier creation with correct naming"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.exists.return_value = False

        mock_doc = MagicMock()
        mock_doc.name = "Supplier 456 (eBoekhouden)"
        mock_frappe.new_doc.return_value = mock_doc

        resolver = EBoekhoudenPartyResolver()

        result = resolver._create_provisional_party("Supplier", "456", self.debug_info)

        mock_frappe.new_doc.assert_called_once_with("Supplier")
        self.assertEqual(mock_doc.supplier_name, "Supplier 456 (eBoekhouden)")
        self.assertEqual(mock_doc.supplier_group, "All Supplier Groups")
        self.assertEqual(mock_doc.eboekhouden_relation_code, "456")
        mock_doc.insert.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_returns_existing_provisional(self, mock_frappe):
        """Test that existing provisional party is returned instead of creating duplicate"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.exists.return_value = True
        mock_frappe.db.get_value.return_value = "E-Boekhouden Customer 123"

        resolver = EBoekhoudenPartyResolver()

        result = resolver._create_provisional_party("Customer", "123", self.debug_info)

        self.assertEqual(result, "E-Boekhouden Customer 123")
        mock_frappe.new_doc.assert_not_called()
        self.assertTrue(any("already exists" in msg for msg in self.debug_info))


class TestUpdatePartyWithFreshData(unittest.TestCase):
    """Tests for _update_party_with_fresh_data method"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_updates_provisional_name(self, mock_frappe):
        """Test that provisional names are updated with better data"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        mock_doc = MagicMock()
        mock_doc.customer_name = "E-Boekhouden Customer 123"
        mock_doc.get.return_value = None
        mock_frappe.get_doc.return_value = mock_doc

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "name": "Actual Company Name",
            "type": "B",
        }

        result = resolver._update_party_with_fresh_data(
            "Customer", "E-Boekhouden Customer 123", relation_details, self.debug_info
        )

        self.assertTrue(result)
        self.assertEqual(mock_doc.customer_name, "Actual Company Name")
        self.assertEqual(mock_doc.customer_type, "Company")
        mock_doc.save.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_does_not_update_good_name(self, mock_frappe):
        """Test that good names are not overwritten"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        mock_doc = MagicMock()
        mock_doc.customer_name = "Already Good Company Name"
        mock_frappe.get_doc.return_value = mock_doc

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "name": "Different Name",
            "type": "B",
        }

        result = resolver._update_party_with_fresh_data(
            "Customer", "Already Good Company Name", relation_details, self.debug_info
        )

        self.assertFalse(result)
        mock_doc.save.assert_not_called()
        self.assertTrue(any("already has good name" in msg for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_handles_update_exception(self, mock_frappe):
        """Test that exceptions during update are handled gracefully"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.get_doc.side_effect = Exception("Database error")

        resolver = EBoekhoudenPartyResolver()

        relation_details = {"id": "123", "name": "Test"}

        result = resolver._update_party_with_fresh_data(
            "Customer", "Some Customer", relation_details, self.debug_info
        )

        self.assertFalse(result)
        self.assertTrue(any("Failed to update" in msg for msg in self.debug_info))


class TestResolveParty(unittest.TestCase):
    """Tests for _resolve_party method - main resolution logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_returns_existing_party(self, mock_frappe):
        """Test that existing party is returned when found by relation code"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.get_value.return_value = {
            "name": "Existing Customer",
            "customer_name": "Existing Customer",
        }

        resolver = EBoekhoudenPartyResolver()

        # Mock fetch_relation_details to return None (API unavailable)
        with patch.object(resolver, "fetch_relation_details", return_value=None):
            result = resolver._resolve_party("Customer", "123", self.debug_info)

        self.assertEqual(result, "Existing Customer")
        self.assertTrue(any("existing customer" in msg.lower() for msg in self.debug_info))

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_creates_from_api_data(self, mock_frappe):
        """Test that new party is created from API data when not existing"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.get_value.return_value = None  # No existing party
        mock_frappe.db.exists.return_value = False

        mock_doc = MagicMock()
        mock_doc.name = "New API Customer"
        mock_frappe.new_doc.return_value = mock_doc

        resolver = EBoekhoudenPartyResolver()

        relation_details = {"id": "123", "name": "New API Customer", "type": "B"}

        with patch.object(resolver, "fetch_relation_details", return_value=relation_details):
            with patch.object(resolver, "create_contact"):  # Skip contact creation
                result = resolver._resolve_party("Customer", "123", self.debug_info)

        self.assertEqual(result, "New API Customer")
        mock_doc.insert.assert_called_once()

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_creates_provisional_when_api_unavailable(self, mock_frappe):
        """Test that provisional party is created when API is unavailable"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.db.get_value.return_value = None  # No existing party
        mock_frappe.db.exists.return_value = False

        mock_doc = MagicMock()
        mock_doc.name = "E-Boekhouden Customer 123"
        mock_frappe.new_doc.return_value = mock_doc

        resolver = EBoekhoudenPartyResolver()

        with patch.object(resolver, "fetch_relation_details", return_value=None):
            result = resolver._resolve_party("Customer", "123", self.debug_info)

        self.assertEqual(result, "E-Boekhouden Customer 123")
        self.assertTrue(any("provisional" in msg.lower() for msg in self.debug_info))


class TestLegacyMethodWrappers(unittest.TestCase):
    """Tests for backwards-compatible legacy method wrappers"""

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_resolve_customer_calls_resolve_party(self, mock_frappe):
        """Test that resolve_customer delegates to _resolve_party"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        with patch.object(resolver, "_resolve_party", return_value="Test Customer") as mock_resolve:
            result = resolver.resolve_customer("123", [])

        mock_resolve.assert_called_once_with("Customer", "123", [])
        self.assertEqual(result, "Test Customer")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_resolve_supplier_calls_resolve_party(self, mock_frappe):
        """Test that resolve_supplier delegates to _resolve_party"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        with patch.object(resolver, "_resolve_party", return_value="Test Supplier") as mock_resolve:
            result = resolver.resolve_supplier("456", [])

        mock_resolve.assert_called_once_with("Supplier", "456", [])
        self.assertEqual(result, "Test Supplier")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_create_customer_from_relation_delegates(self, mock_frappe):
        """Test that create_customer_from_relation delegates correctly"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {"id": "123", "name": "Test"}

        with patch.object(
            resolver, "_create_party_from_relation", return_value="New Customer"
        ) as mock_create:
            result = resolver.create_customer_from_relation(relation_details, [])

        mock_create.assert_called_once_with("Customer", relation_details, [])
        self.assertEqual(result, "New Customer")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_create_supplier_from_relation_delegates(self, mock_frappe):
        """Test that create_supplier_from_relation delegates correctly"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {"id": "456", "name": "Test"}

        with patch.object(
            resolver, "_create_party_from_relation", return_value="New Supplier"
        ) as mock_create:
            result = resolver.create_supplier_from_relation(relation_details, [])

        mock_create.assert_called_once_with("Supplier", relation_details, [])
        self.assertEqual(result, "New Supplier")


class TestConvenienceFunctions(unittest.TestCase):
    """Tests for module-level convenience functions"""

    @patch("verenigingen.e_boekhouden.utils.party_resolver.EBoekhoudenPartyResolver")
    def test_resolve_customer_function(self, mock_resolver_class):
        """Test that resolve_customer function creates resolver and calls method"""
        from verenigingen.e_boekhouden.utils.party_resolver import resolve_customer

        mock_resolver = MagicMock()
        mock_resolver.resolve_customer.return_value = "Test Customer"
        mock_resolver_class.return_value = mock_resolver

        result = resolve_customer("123", [])

        mock_resolver.resolve_customer.assert_called_once_with("123", [])
        self.assertEqual(result, "Test Customer")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.EBoekhoudenPartyResolver")
    def test_resolve_supplier_function(self, mock_resolver_class):
        """Test that resolve_supplier function creates resolver and calls method"""
        from verenigingen.e_boekhouden.utils.party_resolver import resolve_supplier

        mock_resolver = MagicMock()
        mock_resolver.resolve_supplier.return_value = "Test Supplier"
        mock_resolver_class.return_value = mock_resolver

        result = resolve_supplier("456", [])

        mock_resolver.resolve_supplier.assert_called_once_with("456", [])
        self.assertEqual(result, "Test Supplier")


class TestExtractSupplierFallbackName(unittest.TestCase):
    """Tests for _extract_supplier_fallback_name method"""

    def setUp(self):
        """Set up test fixtures"""
        self.debug_info = []

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_extracts_from_company_field(self, mock_frappe):
        """Test extraction from company-related fields"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "company": "Hidden Company Name",
        }

        result = resolver._extract_supplier_fallback_name(relation_details, self.debug_info)

        self.assertEqual(result, "Hidden Company Name")

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_extracts_from_address_field(self, mock_frappe):
        """Test extraction of business name from address field"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
            "street": "Bakkerij De Gouden Korst 123",
        }

        result = resolver._extract_supplier_fallback_name(relation_details, self.debug_info)

        self.assertIn("Bakkerij De Gouden Korst", result)
        self.assertIn("eBoekhouden", result)

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_returns_none_when_no_fallback_available(self, mock_frappe):
        """Test that None is returned when no fallback name can be extracted"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()

        resolver = EBoekhoudenPartyResolver()

        relation_details = {
            "id": "123",
        }

        result = resolver._extract_supplier_fallback_name(relation_details, self.debug_info)

        self.assertIsNone(result)


class TestGetDefaultParty(unittest.TestCase):
    """Tests for _get_default_party method (disabled functionality)"""

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_raises_validation_error_for_customer(self, mock_frappe):
        """Test that validation error is raised for missing customer"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.ValidationError = frappe.ValidationError
        # Configure throw to actually raise an exception
        mock_frappe.throw.side_effect = frappe.ValidationError("Test error")

        resolver = EBoekhoudenPartyResolver()

        with self.assertRaises(frappe.ValidationError):
            resolver._get_default_party("Customer")

        mock_frappe.throw.assert_called_once()
        call_args = mock_frappe.throw.call_args
        self.assertIn("CUSTOMER", call_args[0][0].upper())
        self.assertIn("data corruption", call_args[0][0].lower())

    @patch("verenigingen.e_boekhouden.utils.party_resolver.frappe")
    def test_raises_validation_error_for_supplier(self, mock_frappe):
        """Test that validation error is raised for missing supplier"""
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        mock_frappe.get_single.return_value = MagicMock()
        mock_frappe.ValidationError = frappe.ValidationError
        # Configure throw to actually raise an exception
        mock_frappe.throw.side_effect = frappe.ValidationError("Test error")

        resolver = EBoekhoudenPartyResolver()

        with self.assertRaises(frappe.ValidationError):
            resolver._get_default_party("Supplier")

        mock_frappe.throw.assert_called_once()
        call_args = mock_frappe.throw.call_args
        self.assertIn("SUPPLIER", call_args[0][0].upper())
