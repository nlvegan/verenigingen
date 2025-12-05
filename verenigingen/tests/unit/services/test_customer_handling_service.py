# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import unittest
from unittest.mock import MagicMock, patch

import frappe
from verenigingen.services.customer_handling_service import CustomerHandlingService


class TestCustomerHandlingService(unittest.TestCase):
    def setUp(self):
        self.service = CustomerHandlingService()

    @patch("verenigingen.services.customer_handling_service.secure_document_operation")
    @patch("frappe.new_doc")
    @patch("frappe.db.get_value")
    def test_create_customer_for_member_success(self, mock_get_value, mock_new_doc, mock_secure_op):
        # Setup
        member_doc = MagicMock()
        member_doc.name = "MEM-001"
        member_doc.full_name = "John Doe"
        member_doc.email = "john@example.com"
        member_doc.customer = None
        
        mock_get_value.return_value = None # No existing customer
        
        mock_customer = MagicMock()
        mock_customer.name = "CUST-001"
        mock_new_doc.return_value = mock_customer
        
        mock_result = MagicMock()
        mock_result.success = True
        mock_secure_op.return_value = mock_result

        # Mock check_similar_customers to return empty
        with patch.object(self.service, 'check_similar_customers', return_value=[]):
            # Execute
            result = self.service.create_customer_for_member(member_doc)

            # Verify
            self.assertEqual(result, "CUST-001")
            mock_secure_op.assert_called_once()
            self.assertEqual(mock_customer.member, "MEM-001")

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

    @patch("frappe.get_doc")
    @patch("frappe.get_all")
    def test_update_customer_mandate(self, mock_get_all, mock_get_doc):
        customer_id = "cst_123"
        mandate_id = "mdt_456"
        
        mock_get_all.return_value = [{"name": "CUST-001"}]
        mock_customer = MagicMock()
        mock_customer.name = "CUST-001"
        mock_customer.custom_mollie_dues_mandate = None
        mock_get_doc.return_value = mock_customer
        
        result = self.service.update_customer_mandate(customer_id, mandate_id)
        
        self.assertTrue(result["success"])
        self.assertEqual(mock_customer.custom_mollie_dues_mandate, mandate_id)
        mock_customer.save.assert_called_once()
