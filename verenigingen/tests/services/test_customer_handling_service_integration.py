# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Integration tests for CustomerHandlingService - Real database testing

Tests verify customer creation and management with actual database operations:
- Customer creation for new members
- Duplicate customer detection
- Customer validation
- Error handling with proper context

Uses Enhanced Test Factory for realistic test data.
No database mocking - all operations use real Frappe database.
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.services.customer_handling_service import CustomerHandlingService


class TestCustomerHandlingServiceIntegration(EnhancedTestCase):
    """Integration test suite for CustomerHandlingService with real database"""

    # Class-level tracking for cleanup
    _created_members = []
    _created_customers = []

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        super().setUpClass()
        cls._created_members = []
        cls._created_customers = []

    @classmethod
    def tearDownClass(cls):
        """Clean up test data after all tests"""
        # Clean up customers first (due to FK constraints)
        for customer_name in cls._created_customers:
            try:
                if frappe.db.exists("Customer", customer_name):
                    frappe.delete_doc("Customer", customer_name, force=True)
            except Exception:
                pass

        # Clean up members
        for member_name in cls._created_members:
            try:
                if frappe.db.exists("Member", member_name):
                    frappe.delete_doc("Member", member_name, force=True)
            except Exception:
                pass

        frappe.db.commit()
        super().tearDownClass()

    def setUp(self):
        """Set up test fixtures for each test"""
        super().setUp()
        self.service = CustomerHandlingService()

    def test_create_customer_for_member_success(self):
        """Test successful customer creation for a member"""
        # Create a member without a customer
        member = self.create_test_member(
            first_name="Customer",
            last_name="Test",
            email="customer.test@verenigingen.invalid",
            birth_date="1990-01-01"
        )
        self._created_members.append(member.name)

        # Clear any auto-created customer
        if member.customer:
            self._created_customers.append(member.customer)
            member.db_set("customer", None, update_modified=False)
            member.reload()

        # Create customer using the service
        customer_name = self.service.create_customer_for_member(member, suppress_messages=True)

        # Verify customer was created
        self.assertIsNotNone(customer_name)
        self.assertTrue(frappe.db.exists("Customer", customer_name))
        self._created_customers.append(customer_name)

        # Verify customer has correct data
        customer = frappe.get_doc("Customer", customer_name)
        self.assertEqual(customer.customer_name, member.full_name)
        self.assertEqual(customer.customer_type, "Individual")

    def test_create_customer_returns_existing(self):
        """Test that creating customer returns existing customer if already linked"""
        # Create a member with a customer already linked
        member = self.create_test_member(
            first_name="Existing",
            last_name="Customer",
            email="existing.customer@verenigingen.invalid",
            birth_date="1985-01-01"
        )
        self._created_members.append(member.name)

        # Create initial customer
        if not member.customer:
            customer_name = self.service.create_customer_for_member(member, suppress_messages=True)
            member.db_set("customer", customer_name, update_modified=False)
            member.reload()
            self._created_customers.append(customer_name)

        existing_customer = member.customer

        # Try to create customer again
        result = self.service.create_customer_for_member(member, suppress_messages=True)

        # Should return existing customer, not create new one
        self.assertEqual(result, existing_customer)

    def test_check_similar_customers(self):
        """Test similar customer detection"""
        # Create a customer directly for testing similarity search
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Similar Name Test"
        customer.customer_type = "Individual"
        customer.insert()
        self._created_customers.append(customer.name)
        frappe.db.commit()

        # Search for similar customers
        similar = self.service.check_similar_customers("Similar Name")

        # Should find the customer we just created
        self.assertIsInstance(similar, list)
        found_names = [c.customer_name for c in similar]
        self.assertIn("Similar Name Test", found_names)

    def test_check_similar_customers_empty_name(self):
        """Test similar customer check with empty name returns empty list"""
        result = self.service.check_similar_customers("")
        self.assertEqual(result, [])

        result = self.service.check_similar_customers(None)
        self.assertEqual(result, [])

    def test_validate_customer_creation_requirements_valid(self):
        """Test validation passes for valid member"""
        member = self.create_test_member(
            first_name="Valid",
            last_name="Member",
            email="valid.member@verenigingen.invalid",
            birth_date="1988-01-01"
        )
        self._created_members.append(member.name)

        result = self.service.validate_customer_creation_requirements(member)

        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_validate_customer_creation_requirements_missing_name(self):
        """Test validation fails for member without full_name"""
        # Create a mock-like object with missing full_name
        class MemberWithoutName:
            full_name = None
            name = "MEM-TEST-001"

        member = MemberWithoutName()
        result = self.service.validate_customer_creation_requirements(member)

        self.assertFalse(result["valid"])
        self.assertIn("Member must have a full name to create customer", result["errors"])

    def test_validate_customer_creation_requirements_unsaved(self):
        """Test validation fails for unsaved member"""
        class UnsavedMember:
            full_name = "Test Name"
            name = None

        member = UnsavedMember()
        result = self.service.validate_customer_creation_requirements(member)

        self.assertFalse(result["valid"])
        self.assertIn("Member must be saved before creating customer", result["errors"])

    def test_find_exact_customer_match(self):
        """Test exact customer name matching"""
        # Create a customer with known name
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Exact Match Customer"
        customer.customer_type = "Individual"
        customer.insert()
        self._created_customers.append(customer.name)
        frappe.db.commit()

        # Test exact match (case-insensitive)
        result = self.service.find_exact_customer_match("exact match customer")
        self.assertIsNotNone(result)
        self.assertEqual(result["customer_name"], "Exact Match Customer")

        # Test no match
        result = self.service.find_exact_customer_match("Nonexistent Customer Name")
        self.assertIsNone(result)

    def test_update_member_customer_reference(self):
        """Test updating member with customer reference"""
        member = self.create_test_member(
            first_name="Reference",
            last_name="Update",
            email="reference.update@verenigingen.invalid",
            birth_date="1992-01-01"
        )
        self._created_members.append(member.name)

        # Update reference
        result = self.service.update_member_customer_reference(member, "TEST-CUSTOMER-001")

        self.assertTrue(result)
        self.assertEqual(member.customer, "TEST-CUSTOMER-001")

    def test_service_configuration_validation(self):
        """Test that service validates its configuration"""
        # Service should have valid configuration after init
        result = self.service.validate_configuration()
        self.assertTrue(result)

    def test_create_customer_with_contact_info(self):
        """Test customer creation includes contact information"""
        member = self.create_test_member(
            first_name="Contact",
            last_name="Info",
            email="contact.info@verenigingen.invalid",
            birth_date="1987-01-01"
        )
        self._created_members.append(member.name)

        # Clear any auto-created customer
        if member.customer:
            self._created_customers.append(member.customer)
            member.db_set("customer", None, update_modified=False)
            member.reload()

        customer_name = self.service.create_customer_for_member(member, suppress_messages=True)
        self._created_customers.append(customer_name)

        customer = frappe.get_doc("Customer", customer_name)

        # Verify email was set
        self.assertEqual(customer.email_id, member.email)

    def test_return_type_is_optional_string(self):
        """Test that create_customer_for_member returns Optional[str]"""
        member = self.create_test_member(
            first_name="Return",
            last_name="Type",
            email="return.type@verenigingen.invalid",
            birth_date="1995-01-01"
        )
        self._created_members.append(member.name)

        if member.customer:
            self._created_customers.append(member.customer)
            member.db_set("customer", None, update_modified=False)
            member.reload()

        result = self.service.create_customer_for_member(member, suppress_messages=True)

        # Result should be a string (customer name) or None
        self.assertTrue(result is None or isinstance(result, str))
        if result:
            self._created_customers.append(result)
