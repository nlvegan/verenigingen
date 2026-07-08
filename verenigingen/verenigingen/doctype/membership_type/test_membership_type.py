import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipType(EnhancedTestCase):
    def setUp(self):
        super().setUp()

        # Create "Membership" item group if it doesn't exist
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = "Membership"
            item_group.parent_item_group = "All Item Groups"
            item_group.insert()

        # Create test membership type data with timestamp-based uniqueness
        import time

        self.unique_id = str(int(time.time() * 1000))[-8:]  # Use last 8 digits of timestamp

        self.membership_type_data = {
            "membership_type_name": f"Test Membership Type {self.unique_id}",
            "description": "Test Membership Type for Unit Tests",
            "billing_period": "Annual",
            "minimum_amount": 120,
            "is_active": 1,
            "role_profile": "Verenigingen Member",
        }

        # Enhanced Test Factory will handle cleanup automatically

    def tearDown(self):
        super().tearDown()  # Enhanced Test Factory handles cleanup

    def test_create_membership_type(self):
        """Test creating a new membership type"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.update(self.membership_type_data)
        membership_type.insert()

        self.assertEqual(
            membership_type.membership_type_name, self.membership_type_data["membership_type_name"]
        )
        self.assertEqual(membership_type.billing_period, "Annual")
        self.assertEqual(membership_type.minimum_amount, 120)

    def test_custom_billing_period(self):
        """Test validation for custom billing period"""
        # First test - should fail without billing_period_in_months
        membership_type_fail = frappe.new_doc("Membership Type")
        test_data_fail = self.membership_type_data.copy()
        test_data_fail["membership_type_name"] = f"Test Custom Fail {self.unique_id}"
        test_data_fail["billing_period"] = "Custom"
        membership_type_fail.update(test_data_fail)

        # Should raise an error
        with self.assertRaises(frappe.exceptions.ValidationError):
            membership_type_fail.insert()

        # Second test - should succeed with billing_period_in_months
        membership_type_success = frappe.new_doc("Membership Type")
        test_data_success = self.membership_type_data.copy()
        test_data_success["membership_type_name"] = f"Test Custom Success {self.unique_id}"
        test_data_success["billing_period"] = "Custom"
        test_data_success["billing_period_in_months"] = 6
        membership_type_success.update(test_data_success)

        membership_type_success.insert()

        # Should be valid now
        self.assertEqual(membership_type_success.billing_period, "Custom")
        self.assertEqual(membership_type_success.billing_period_in_months, 6)

    def test_negative_amount(self):
        """Test validation for negative amount"""
        membership_type = frappe.new_doc("Membership Type")
        test_data = self.membership_type_data.copy()
        test_data["membership_type_name"] = f"Test Negative {self.unique_id}"
        test_data["minimum_amount"] = -100
        membership_type.update(test_data)

        # Should raise an error
        with self.assertRaises(frappe.exceptions.ValidationError):
            membership_type.insert()
