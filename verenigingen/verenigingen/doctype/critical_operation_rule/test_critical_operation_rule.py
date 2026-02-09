# Copyright (c) 2024, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCriticalOperationRule(FrappeTestCase):
    """Test Critical Operation Rule DocType"""

    def setUp(self):
        """Set up test data"""
        # Clean up any existing test rules
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_%"]})
        frappe.db.commit()

    def test_rule_creation_and_validation(self):
        """Test creating a critical operation rule with validation"""
        # Create a financial operation rule
        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": "test_create_invoice",
                "operation_type": "financial",
                "security_level": "critical",
                "description": "Test rule for invoice creation",
                "enabled": 1,
                "required_roles": "Accounts Manager, Verenigingen Administrator",
                "required_permissions": "Sales Invoice:create",
                "rate_limit_calls": 5,
                "rate_limit_period_seconds": 3600,
                "enable_business_validation": 1,
                "amount_threshold": 1000,
                "audit_level": "detailed",
                "requires_justification": 1,
            }
        )

        rule.insert()

        # Verify the rule was created correctly
        self.assertEqual(rule.operation_name, "test_create_invoice")
        self.assertEqual(rule.security_level, "critical")
        self.assertTrue(rule.enabled)

    def test_security_level_validation(self):
        """Test security level consistency validation"""
        # This should generate a warning but not fail
        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": "test_financial_low_security",
                "operation_type": "financial",
                "security_level": "low",  # This should trigger a warning
                "enabled": 1,
            }
        )

        # Should not raise an exception, but validation should run
        rule.insert()
        self.assertEqual(rule.security_level, "low")

    def test_rate_limit_validation(self):
        """Test rate limit validation rejects zero and negative values"""
        # rate_limit_calls=0 must be rejected (must be at least 1)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Critical Operation Rule",
                    "operation_name": "test_zero_rate_limit",
                    "operation_type": "financial",
                    "security_level": "critical",
                    "rate_limit_calls": 0,
                    "enabled": 1,
                }
            ).insert()

        # Negative values must also be rejected
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Critical Operation Rule",
                    "operation_name": "test_negative_rate_limit",
                    "operation_type": "financial",
                    "security_level": "critical",
                    "rate_limit_calls": -1,
                    "enabled": 1,
                }
            ).insert()

    def test_notification_validation(self):
        """Test notification settings validation"""
        # Note: The validation checks `notification_recipients` (not `alert_recipients`)
        # and auto-populates from Verenigingen Settings if missing, so it doesn't throw error
        # Test validates current behavior: alert_on_execution without notification_recipients
        # is allowed (gets auto-populated from settings)

        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": "test_alert_auto_recipients",
                "operation_type": "admin",
                "security_level": "high",
                "alert_on_execution": 1,
                # Missing notification_recipients - will be auto-populated
                "enabled": 1,
            }
        )
        rule.insert()  # Should succeed - auto-populates recipients from settings
        # Verify it was inserted successfully
        self.assertTrue(rule.name)

    def test_rule_config_retrieval(self):
        """Test getting rule configuration"""
        # Create a test rule
        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": "test_payment_processing",
                "operation_type": "financial",
                "security_level": "critical",
                "required_roles": "Accounts Manager",
                "rate_limit_calls": 10,
                "rate_limit_period_seconds": 3600,
                "enable_business_validation": 1,
                "amount_threshold": 5000,
                "enabled": 1,
            }
        )
        rule.insert()

        # Test configuration retrieval
        from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
            CriticalOperationRule,
        )

        config = CriticalOperationRule.get_rule_config("test_payment_processing")

        self.assertIsNotNone(config)
        self.assertEqual(config["operation_name"], "test_payment_processing")
        self.assertEqual(config["security_level"], "critical")
        self.assertEqual(config["rate_limit"]["calls"], 10)
        self.assertTrue(config["business_rules"]["enabled"])
        self.assertEqual(config["business_rules"]["amount_threshold"], 5000)

    def test_disabled_rule_not_retrieved(self):
        """Test that disabled rules are not retrieved"""
        # Create a disabled rule
        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": "test_disabled_rule",
                "operation_type": "financial",
                "security_level": "critical",
                "enabled": 0,  # Disabled
            }
        )
        rule.insert()

        from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
            CriticalOperationRule,
        )

        config = CriticalOperationRule.get_rule_config("test_disabled_rule")
        self.assertIsNone(config)

    def test_cache_invalidation(self):
        """Test that cache is properly invalidated on updates"""
        # Create a rule
        rule = frappe.get_doc(
            {
                "doctype": "Critical Operation Rule",
                "operation_name": "test_cache_invalidation",
                "operation_type": "financial",
                "security_level": "high",
                "rate_limit_calls": 5,
                "enabled": 1,
            }
        )
        rule.insert()

        from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
            CriticalOperationRule,
        )

        # Get config (should cache it)
        config1 = CriticalOperationRule.get_rule_config("test_cache_invalidation")
        self.assertEqual(config1["rate_limit"]["calls"], 5)

        # Update the rule
        rule.rate_limit_calls = 15
        rule.save()

        # Get config again (should reflect the update due to cache invalidation)
        config2 = CriticalOperationRule.get_rule_config("test_cache_invalidation")
        self.assertEqual(config2["rate_limit"]["calls"], 15)

    def tearDown(self):
        """Clean up test data"""
        frappe.db.delete("Critical Operation Rule", {"operation_name": ["like", "test_%"]})
        frappe.db.commit()
