"""
Relation Migration Service Tests
=================================

Integration tests for RelationMigrationService using real document operations.
Tests customer and supplier creation from eBoekhouden API data formats.

These tests use real document creation (no mocks) to validate:
- Proper data transformation from eBoekhouden formats
- Security and permission validation
- Document validity and field population
- Contact and address linking
"""

import frappe

from verenigingen.e_boekhouden.services.relation_migration_service import RelationMigrationService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestRelationMigrationService(EnhancedTestCase):
    """Integration tests for RelationMigrationService with real ERPNext documents."""

    def setUp(self):
        """Set up test environment with service instance."""
        super().setUp()
        self.service = RelationMigrationService()
        self.test_parties = []  # Track for cleanup

    def tearDown(self):
        """Clean up created test parties, contacts, and addresses."""
        # Clean up contacts first (they link to parties)
        for party_type, party_name in self.test_parties:
            try:
                # Delete linked contacts
                contacts = frappe.get_all(
                    "Dynamic Link",
                    filters={"link_doctype": party_type, "link_name": party_name},
                    fields=["parent"],
                )
                for contact_link in contacts:
                    if frappe.db.exists("Contact", contact_link.parent):
                        frappe.delete_doc("Contact", contact_link.parent, force=True)

                # Delete linked addresses
                addresses = frappe.get_all(
                    "Dynamic Link",
                    filters={"link_doctype": party_type, "link_name": party_name, "parenttype": "Address"},
                    fields=["parent"],
                )
                for address_link in addresses:
                    if frappe.db.exists("Address", address_link.parent):
                        frappe.delete_doc("Address", address_link.parent, force=True)

                # Delete the party
                if frappe.db.exists(party_type, party_name):
                    frappe.delete_doc(party_type, party_name, force=True)
            except Exception as e:
                self.logger.warning(f"Error cleaning up {party_type} {party_name}: {str(e)}")

        super().tearDown()

    def _track_party(self, party_type, party_name):
        """Track party for cleanup."""
        if party_name:
            self.test_parties.append((party_type, party_name))

    # =========================================================================
    # Party Type Determination Tests (Pure Logic - No Database)
    # =========================================================================

    def test_determine_party_type_soap_business(self):
        """Test party type determination with SOAP BP='B' (Business)."""
        result = self.service._determine_party_type(
            bp_type="B", company_name="Test BV", contact_name="", vat_number=""
        )
        self.assertTrue(result, "SOAP BP='B' should return Company (True)")

    def test_determine_party_type_soap_person(self):
        """Test party type determination with SOAP BP='P' (Person)."""
        result = self.service._determine_party_type(
            bp_type="P", company_name="", contact_name="Jan de Vries", vat_number=""
        )
        self.assertFalse(result, "SOAP BP='P' should return Individual (False)")

    def test_determine_party_type_company_name_only(self):
        """Test party type determination with only company name (REST API)."""
        result = self.service._determine_party_type(
            bp_type="", company_name="Vereniging Test BV", contact_name="", vat_number=""
        )
        self.assertTrue(result, "Company name without contact should return Company")

    def test_determine_party_type_contact_name_only(self):
        """Test party type determination with only contact name (REST API)."""
        result = self.service._determine_party_type(
            bp_type="", company_name="", contact_name="Maria van den Berg", vat_number=""
        )
        self.assertFalse(result, "Contact name without company should return Individual")

    def test_determine_party_type_vat_number_implies_business(self):
        """Test party type determination with VAT number (suppliers)."""
        result = self.service._determine_party_type(
            bp_type="", company_name="", contact_name="", vat_number="NL123456789B01"
        )
        self.assertTrue(result, "VAT number should imply Company")

    def test_determine_party_type_priority_soap_over_names(self):
        """Test that SOAP BP type takes priority over name analysis."""
        # BP='P' should override company name presence
        result = self.service._determine_party_type(
            bp_type="P", company_name="Test BV", contact_name="Jan Jansen", vat_number=""
        )
        self.assertFalse(result, "SOAP BP='P' should take priority over company name")

        # BP='B' should override contact name only
        result = self.service._determine_party_type(
            bp_type="B", company_name="", contact_name="Jan Jansen", vat_number=""
        )
        self.assertTrue(result, "SOAP BP='B' should take priority over contact name")

    # =========================================================================
    # Customer Creation Tests (Real Documents)
    # =========================================================================

    def test_create_customer_soap_format_company(self):
        """Test customer creation with SOAP API format (company) - real document."""
        # SOAP format customer data (company)
        customer_data = {
            "ID": "12345",
            "Bedrijf": "Test SOAP Company BV",
            "Contactpersoon": "Jan de Vries",
            "Email": "contact@soaptest.nl",
            "BP": "B",  # Business
            "Adres": "Teststraat 123",
            "Postcode": "1234 AB",
            "Plaats": "Amsterdam",
        }

        result = self.service.create_customer(customer_data)

        self.assertTrue(result, "Customer creation should succeed")

        # Verify customer was actually created
        customer_name = "Test SOAP Company BV"
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self._track_party("Customer", customer_name)

        # Verify customer fields
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_type, "Company")
        self.assertEqual(customer.eboekhouden_relation_code, "12345")
        self.assertIsNotNone(customer.territory)

        # Verify contact was created
        contacts = frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": "Customer", "link_name": customer_name},
            fields=["parent"],
        )
        self.assertGreater(len(contacts), 0, "Contact should be created")

        # Verify address was created
        addresses = frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": "Customer", "link_name": customer_name, "parenttype": "Address"},
            fields=["parent"],
        )
        self.assertGreater(len(addresses), 0, "Address should be created")

    def test_create_customer_soap_format_individual(self):
        """Test customer creation with SOAP API format (individual) - real document."""
        # SOAP format customer data (person)
        customer_data = {
            "ID": "67890",
            "Contactpersoon": "Maria van den Berg",
            "Email": "maria@example.nl",
            "BP": "P",  # Person
            "Telefoon": "0612345678",
        }

        result = self.service.create_customer(customer_data)

        self.assertTrue(result, "Customer creation should succeed")

        # Verify customer was actually created
        customer_name = "Maria van den Berg"
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self._track_party("Customer", customer_name)

        # Verify customer fields
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_type, "Individual")
        self.assertEqual(customer.eboekhouden_relation_code, "67890")

        # Verify contact was created
        contacts = frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": "Customer", "link_name": customer_name},
            fields=["parent"],
        )
        self.assertGreater(len(contacts), 0, "Contact should be created")

    def test_create_customer_rest_format(self):
        """Test customer creation with REST API format - real document."""
        # REST format customer data
        customer_data = {
            "id": "REST123",
            "companyName": "REST Company BV",
            "contactName": "Pieter Jansen",
            "email": "info@restcompany.nl",
            "address": "REST Street 456",
            "city": "Rotterdam",
            "postalCode": "3000 AA",
        }

        result = self.service.create_customer(customer_data)

        self.assertTrue(result, "Customer creation should succeed")

        # Verify customer was actually created
        customer_name = "REST Company BV"
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self._track_party("Customer", customer_name)

        # Verify customer fields
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.eboekhouden_relation_code, "REST123")

        # Verify contact and address were created
        contacts = frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": "Customer", "link_name": customer_name},
            fields=["parent"],
        )
        self.assertGreater(len(contacts), 0, "Contact should be created")

        addresses = frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": "Customer", "link_name": customer_name, "parenttype": "Address"},
            fields=["parent"],
        )
        self.assertGreater(len(addresses), 0, "Address should be created")

    # =========================================================================
    # Supplier Creation Tests (Real Documents)
    # =========================================================================

    def test_create_supplier_with_vat_number(self):
        """Test supplier creation with VAT number (BTW) - real document."""
        # SOAP format supplier data with VAT
        supplier_data = {
            "ID": "SUP123",
            "Bedrijf": "Leverancier XYZ BV",
            "Contactpersoon": "Kees Pietersen",
            "Email": "kees@xyz.nl",
            "BP": "B",
            "BTWNummer": "NL123456789B01",
        }

        result = self.service.create_supplier(supplier_data)

        self.assertTrue(result, "Supplier creation should succeed")

        # Verify supplier was actually created
        supplier_name = "Leverancier XYZ BV"
        self.assertTrue(frappe.db.exists("Supplier", supplier_name))
        self._track_party("Supplier", supplier_name)

        # Verify supplier fields
        supplier = frappe.get_doc("Supplier", supplier_name)
        self.assertEqual(supplier.supplier_type, "Company")
        self.assertEqual(supplier.tax_id, "NL123456789B01")
        self.assertEqual(supplier.eboekhouden_relation_code, "SUP123")

        # Verify contact was created
        contacts = frappe.get_all(
            "Dynamic Link",
            filters={"link_doctype": "Supplier", "link_name": supplier_name},
            fields=["parent"],
        )
        self.assertGreater(len(contacts), 0, "Contact should be created")

    def test_create_supplier_rest_format_with_vat(self):
        """Test supplier creation with REST API format and VAT - real document."""
        # REST format supplier data
        supplier_data = {
            "id": "REST_SUP456",
            "companyName": "REST Leverancier NV",
            "email": "contact@restleverancier.nl",
            "vatNumber": "NL987654321B02",
        }

        result = self.service.create_supplier(supplier_data)

        self.assertTrue(result, "Supplier creation should succeed")

        # Verify supplier was actually created
        supplier_name = "REST Leverancier NV"
        self.assertTrue(frappe.db.exists("Supplier", supplier_name))
        self._track_party("Supplier", supplier_name)

        # Verify supplier fields
        supplier = frappe.get_doc("Supplier", supplier_name)
        self.assertEqual(supplier.tax_id, "NL987654321B02")
        self.assertEqual(supplier.eboekhouden_relation_code, "REST_SUP456")

    # =========================================================================
    # Edge Cases Tests
    # =========================================================================

    def test_create_customer_skip_id_only(self):
        """Test that customer with only ID is skipped during CoA import."""
        # Common case with REST API during Chart of Accounts import
        customer_data = {"id": "999", "name": ""}

        result = self.service.create_customer(customer_data)

        self.assertFalse(result, "Customer with only ID should be skipped")
        # Verify no customer was created
        self.assertFalse(frappe.db.exists("Customer", {"eboekhouden_relation_code": "999"}))

    def test_create_supplier_skip_id_only(self):
        """Test that supplier with only ID is skipped during CoA import."""
        supplier_data = {"id": "888"}

        result = self.service.create_supplier(supplier_data)

        self.assertFalse(result, "Supplier with only ID should be skipped")
        # Verify no supplier was created
        self.assertFalse(frappe.db.exists("Supplier", {"eboekhouden_relation_code": "888"}))

    def test_create_customer_no_usable_data(self):
        """Test handling of customer data with no usable information."""
        customer_data = {"random_field": "random_value"}

        result = self.service.create_customer(customer_data)

        self.assertFalse(result, "Customer with no usable data should fail")

    def test_create_customer_already_exists(self):
        """Test that existing customer is skipped."""
        # Create test customer first
        customer_name = "Existing Test Customer BV"
        existing_customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": customer_name,
                "customer_type": "Company",
                "customer_group": "Individual",
                "territory": "Netherlands",
            }
        )
        existing_customer.insert(ignore_permissions=True)
        self._track_party("Customer", existing_customer.name)

        # Try to create duplicate
        customer_data = {
            "ID": "DUP123",
            "Bedrijf": customer_name,
            "BP": "B",
        }

        result = self.service.create_customer(customer_data)

        self.assertFalse(result, "Duplicate customer should be skipped")

        # Verify only one customer exists with this name
        customers = frappe.get_all("Customer", filters={"customer_name": customer_name})
        self.assertEqual(len(customers), 1, "Should only have one customer with this name")

    def test_mixed_soap_rest_fields(self):
        """Test handling of data with mixed SOAP and REST fields - real document."""
        # Some systems might send mixed format
        mixed_data = {
            "ID": "MIX123",  # SOAP
            "companyName": "Mixed Format BV",  # REST
            "Contactpersoon": "Mixed Person",  # SOAP
            "email": "mixed@test.nl",  # REST (lowercase)
            "BP": "B",  # SOAP
        }

        result = self.service.create_customer(mixed_data)

        self.assertTrue(result, "Should handle mixed format data")

        # Verify customer was created with correct data
        customer_name = "Mixed Format BV"
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self._track_party("Customer", customer_name)

        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_type, "Company")
        self.assertEqual(customer.eboekhouden_relation_code, "MIX123")
