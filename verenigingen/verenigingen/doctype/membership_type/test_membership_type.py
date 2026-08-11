import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase


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

    def _make_type(self, suffix, default=0):
        data = dict(self.membership_type_data)
        data["membership_type_name"] = f"{data['membership_type_name']} {suffix}"
        data["default_for_new_members"] = default
        doc = frappe.new_doc("Membership Type")
        doc.update(data)
        doc.insert()
        return doc

    def test_default_for_new_members_is_exclusive(self):
        """Only one Membership Type may be default_for_new_members at a time.

        Saving a second type as default must clear the flag on the previous default --
        enforced server-side (MembershipType.enforce_single_default), not only by the
        client script, so REST API / Data Import / console writes cannot leave two
        simultaneous defaults.
        """
        type_a = self._make_type("A", default=1)
        self.assertEqual(frappe.db.get_value("Membership Type", type_a.name, "default_for_new_members"), 1)

        type_b = self._make_type("B", default=1)

        # Saving B as the default cleared A's flag -> exactly one default survives.
        self.assertEqual(frappe.db.get_value("Membership Type", type_b.name, "default_for_new_members"), 1)
        self.assertEqual(
            frappe.db.get_value("Membership Type", type_a.name, "default_for_new_members"),
            0,
            "server-side enforcement must clear the previous default_for_new_members type",
        )

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


class TestMembershipItemDefaults(VereningingenTestCase):
    """
    get_or_create_membership_item() appends an item_defaults row with
    default_warehouse: None, meaning "no warehouse". _set_defaults() fills child rows
    too and only skips a value that is not None, so None was replaced by the acting
    user's default warehouse — which ERPNext rejects when it belongs to a different
    company than Verenigingen Settings.company. secure_document_operation turned that
    into success=False, and the user was told to "check permissions".

    On VereningingenTestCase, not EnhancedTestCase: the latter sets in_import, which
    makes _set_defaults() return immediately, so the None was never replaced.
    """

    def test_membership_item_is_created_without_a_warehouse(self):
        membership_type = frappe.new_doc("Membership Type")
        membership_type.update(
            {
                "membership_type_name": f"WH Test {frappe.generate_hash(length=8)}",
                "description": "Warehouse default regression",
                "billing_period": "Annual",
                "minimum_amount": 10,
                "is_active": 1,
            }
        )
        membership_type.insert()
        self.track_doc("Membership Type", membership_type.name)

        item_name = membership_type.get_or_create_membership_item()
        self.assertTrue(item_name)
        self.track_doc("Item", item_name)

        item = frappe.get_doc("Item", item_name)
        self.assertEqual(len(item.item_defaults), 1)
        # The user default warehouse must not have leaked into the row; this is a
        # service item, so it wants no warehouse at all.
        self.assertFalse(item.item_defaults[0].default_warehouse)
