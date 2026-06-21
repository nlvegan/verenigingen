# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.services.customer_handling_service import CustomerHandlingService


class TestCustomerHandlingService(unittest.TestCase):
    def setUp(self):
        self.service = CustomerHandlingService()

    # CustomerHandlingService.create_customer_for_member delegates the actual
    # Customer + Contact creation to the canonical
    # verenigingen.utils.application_payments.create_customer_for_member, which
    # the service imports lazily. Patch that delegate.
    @patch("verenigingen.utils.application_payments.create_customer_for_member")
    @patch("frappe.db.get_value")
    def test_create_customer_for_member_success(self, mock_get_value, mock_create_customer):
        # Setup
        member_doc = MagicMock()
        member_doc.name = "MEM-001"
        member_doc.full_name = "John Doe"
        member_doc.email = "john@example.com"
        member_doc.customer = None

        mock_get_value.return_value = None  # No existing customer

        mock_customer = MagicMock()
        mock_customer.name = "CUST-001"
        mock_create_customer.return_value = mock_customer

        # Mock check_similar_customers to return empty
        with patch.object(self.service, "check_similar_customers", return_value=[]):
            # Execute
            result = self.service.create_customer_for_member(member_doc)

            # Verify
            self.assertEqual(result, "CUST-001")
            mock_create_customer.assert_called_once_with(member_doc)

    @patch("frappe.get_all")
    def test_check_similar_customers(self, mock_get_all):
        # Setup
        mock_get_all.return_value = [{"name": "CUST-001", "customer_name": "John Doe"}]

        # Execute
        result = self.service.check_similar_customers("John Doe")

        # Verify
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "CUST-001")

    def test_validate_customer_creation_requirements_valid(self):
        member_doc = MagicMock()
        member_doc.name = "MEM-001"
        member_doc.full_name = "John Doe"

        result = self.service.validate_customer_creation_requirements(member_doc)
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)

    def test_validate_customer_creation_requirements_invalid(self):
        member_doc = MagicMock()
        member_doc.name = None
        member_doc.full_name = None

        result = self.service.validate_customer_creation_requirements(member_doc)
        self.assertFalse(result["valid"])
        self.assertEqual(len(result["errors"]), 2)

    def test_update_member_customer_reference(self):
        member_doc = MagicMock()
        customer_name = "CUST-001"

        result = self.service.update_member_customer_reference(member_doc, customer_name)

        self.assertTrue(result)
        self.assertEqual(member_doc.customer, customer_name)
