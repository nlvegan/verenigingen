import unittest

import frappe
from frappe.tests.utils import FrappeTestCase


class TestMembershipType(FrappeTestCase):
    def setUp(self):
        # Create "Membership" item group if it doesn't exist
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = "Membership"
            item_group.parent_item_group = "All Item Groups"
            item_group.insert(ignore_permissions=True)

        # Create test membership type data
        self.membership_type_data = {
            "membership_type_name": "Test Membership Type",
            "description": "Test Membership Type for Unit Tests",
            "billing_period": "Annual",
            "amount": 120,
            "currency": "EUR",
            "is_active": 1,
            "allow_auto_renewal": 1,
        }

        # Delete any existing test membership types
        if frappe.db.exists("Membership Type", self.membership_type_data["membership_type_name"]):
            frappe.delete_doc(
                "Membership Type", self.membership_type_data["membership_type_name"], force=True
            )

        # Delete any test items
        item_code = f"MEM-{self.membership_type_data['membership_type_name']}".upper().replace(" ", "-")
        if frappe.db.exists("Item", item_code):
            frappe.delete_doc("Item", item_code, force=True)

    def tearDown(self):
        # Clean up test data
        if frappe.db.exists("Membership Type", self.membership_type_data["membership_type_name"]):
            frappe.delete_doc(
                "Membership Type", self.membership_type_data["membership_type_name"], force=True
            )

        # Clean up any test items
        item_code = f"MEM-{self.membership_type_data['membership_type_name']}".upper().replace(" ", "-")
        if frappe.db.exists("Item", item_code):
            frappe.delete_doc("Item", item_code, force=True)

        # We don't delete the Item Group as it might be used by other tests

    def test_create_membership_type(self):
        """Test creating a new membership type"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.update(self.membership_type_data)
        membership_type.insert()

        self.assertEqual(membership_type.membership_type_name, "Test Membership Type")
        self.assertEqual(membership_type.billing_period, "Annual")
        self.assertEqual(membership_type.minimum_amount, 120)

    def test_custom_billing_period(self):
        """Test validation for custom billing period"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.update(self.membership_type_data)

        # Change to custom period without setting months
        membership_type.billing_period = "Custom"

        # Should raise an error
        with self.assertRaises(frappe.exceptions.ValidationError):
            membership_type.insert()

        # Now set the months
        membership_type.billing_period_in_months = 6
        membership_type.insert()

        # Should be valid now
        self.assertEqual(membership_type.billing_period, "Custom")
        self.assertEqual(membership_type.billing_period_in_months, 6)

    def test_negative_amount(self):
        """Test validation for negative amount"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.update(self.membership_type_data)

        # Set negative amount
        membership_type.minimum_amount = -100

        # Should raise an error
        with self.assertRaises(frappe.exceptions.ValidationError):
            membership_type.insert()

    def test_default_membership_type(self):
        """Test setting a membership type as default"""
        # Create a first membership type
        first_type = frappe.new_doc("Membership Type")
        first_type.membership_type_name = "First Default Type"
        first_type.billing_period = "Annual"
        first_type.amount = 100
        first_type.currency = "EUR"
        first_type.default_for_new_members = 1
        first_type.insert()

        # Create a second membership type
        second_type = frappe.new_doc("Membership Type")
        second_type.membership_type_name = "Second Default Type"
        second_type.billing_period = "Annual"
        second_type.amount = 120
        second_type.currency = "EUR"
        second_type.default_for_new_members = 1
        second_type.insert()

        # Reload first type
        first_type.reload()

        # First type should no longer be default
        self.assertEqual(first_type.default_for_new_members, 0)

        # Only second type should be default
        self.assertEqual(second_type.default_for_new_members, 1)

        # Clean up
        first_type.delete()
        second_type.delete()


if __name__ == "__main__":
    unittest.main()
