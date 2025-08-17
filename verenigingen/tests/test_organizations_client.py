"""
Integration tests for Mollie Organizations API Client
"""

import json
import unittest
from unittest.mock import MagicMock, Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.organizations_client import OrganizationsClient
from verenigingen.verenigingen_payments.core.models.organization import Organization


class TestOrganizationsClient(FrappeTestCase):
    """Test suite for Organizations API Client"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        
        # Create mock dependencies
        self.mock_audit_trail = MagicMock()
        self.mock_settings = MagicMock()
        self.mock_settings.get_api_key.return_value = "test_api_key_123"
        
        # Create client instance
        with patch('verenigingen.verenigingen_payments.core.mollie_base_client.frappe.get_doc'):
            self.client = OrganizationsClient("test_settings")
            self.client.audit_trail = self.mock_audit_trail
            self.client.settings = self.mock_settings

    def test_get_current_organization(self):
        """Test retrieving current organization"""
        mock_response = {
            "resource": "organization",
            "id": "org_12345",
            "name": "Test Organization B.V.",
            "email": "info@testorg.nl",
            "locale": "nl_NL",
            "address": {
                "streetAndNumber": "Keizersgracht 123",
                "postalCode": "1015 CJ",
                "city": "Amsterdam",
                "country": "NL"
            },
            "registrationNumber": "12345678",
            "vatNumber": "NL123456789B01",
            "vatRegulation": "dutch"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            org = self.client.get_current_organization()
            
            # Verify API call
            mock_get.assert_called_once_with("/organizations/me")
            
            # Verify response
            self.assertIsInstance(org, Organization)
            self.assertEqual(org.id, "org_12345")
            self.assertEqual(org.name, "Test Organization B.V.")
            self.assertEqual(org.email, "info@testorg.nl")
            self.assertTrue(org.has_vat_number())
            self.assertEqual(org.vat_number, "NL123456789B01")
            
            # Verify address
            self.assertEqual(org.address.city, "Amsterdam")
            self.assertEqual(org.address.country, "NL")
            
            # Verify audit logging
            self.mock_audit_trail.log_event.assert_called()

    def test_get_organization_by_id(self):
        """Test retrieving specific organization"""
        org_id = "org_specific"
        mock_response = {
            "resource": "organization",
            "id": org_id,
            "name": "Specific Org",
            "email": "contact@specific.com"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response) as mock_get:
            org = self.client.get_organization(org_id)
            
            mock_get.assert_called_once_with(f"/organizations/{org_id}")
            self.assertEqual(org.id, org_id)
            self.assertEqual(org.name, "Specific Org")

    def test_get_organization_info(self):
        """Test getting comprehensive organization information"""
        mock_response = {
            "resource": "organization",
            "id": "org_12345",
            "name": "Test Organization B.V.",
            "email": "info@testorg.nl",
            "locale": "nl_NL",
            "address": {
                "streetAndNumber": "Keizersgracht 123",
                "postalCode": "1015 CJ",
                "city": "Amsterdam",
                "country": "NL"
            },
            "registrationNumber": "12345678",
            "vatNumber": "NL123456789B01",
            "vatRegulation": "dutch"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            info = self.client.get_organization_info()
            
            # Verify info structure
            self.assertEqual(info["id"], "org_12345")
            self.assertEqual(info["name"], "Test Organization B.V.")
            self.assertEqual(info["email"], "info@testorg.nl")
            self.assertEqual(info["locale"], "nl_NL")
            self.assertTrue(info["has_vat"])
            self.assertEqual(info["vat_number"], "NL123456789B01")
            self.assertEqual(info["display_name"], "Test Organization B.V.")
            
            # Verify address info
            self.assertIn("address", info)
            self.assertEqual(info["address"]["city"], "Amsterdam")
            self.assertEqual(info["address"]["country"], "NL")
            self.assertIn("Keizersgracht 123", info["address"]["full"])

    def test_verify_organization_status_valid(self):
        """Test organization verification with valid data"""
        mock_response = {
            "resource": "organization",
            "id": "org_valid",
            "name": "Valid Organization",
            "email": "valid@org.com",
            "address": {
                "streetAndNumber": "Main St 1",
                "city": "City",
                "country": "NL"
            },
            "vatNumber": "NL123456789B01",
            "vatRegulation": "dutch"
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            verification = self.client.verify_organization_status()
            
            # Verify valid organization
            self.assertTrue(verification["verified"])
            self.assertEqual(len(verification["issues"]), 0)
            self.assertEqual(len(verification["warnings"]), 0)
            
            # Verify info logging for valid org
            audit_calls = self.mock_audit_trail.log_event.call_args_list
            info_logged = any(
                call[0][1].value == "INFO" 
                for call in audit_calls
            )
            self.assertTrue(info_logged)

    def test_verify_organization_status_missing_email(self):
        """Test organization verification with missing email"""
        mock_response = {
            "resource": "organization",
            "id": "org_no_email",
            "name": "No Email Org",
            "email": None
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            verification = self.client.verify_organization_status()
            
            # Verify email issue detected
            self.assertFalse(verification["verified"])
            self.assertIn("Email address missing", verification["issues"])
            
            # Verify warning logged
            audit_calls = self.mock_audit_trail.log_event.call_args_list
            warning_logged = any(
                call[0][1].value == "WARNING" 
                for call in audit_calls
            )
            self.assertTrue(warning_logged)

    def test_verify_organization_status_missing_vat(self):
        """Test organization verification with VAT regulation but no VAT number"""
        mock_response = {
            "resource": "organization",
            "id": "org_no_vat",
            "name": "No VAT Org",
            "email": "info@org.com",
            "vatRegulation": "dutch",
            "vatNumber": None
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            verification = self.client.verify_organization_status()
            
            # Should be verified but with warning
            self.assertTrue(verification["verified"])
            self.assertIn("VAT number not configured", verification["warnings"])

    def test_sync_organization_to_frappe_new_company(self):
        """Test syncing organization to new Frappe company"""
        mock_org_response = {
            "resource": "organization",
            "id": "org_sync",
            "name": "Sync Test Company",
            "email": "sync@test.com",
            "vatNumber": "NL987654321B01",
            "address": {
                "streetAndNumber": "Test Street 42",
                "city": "Test City",
                "postalCode": "1234 AB",
                "country": "NL"
            }
        }
        
        with patch.object(self.client, 'get', return_value=mock_org_response):
            with patch('frappe.db.exists', return_value=False):
                with patch('frappe.new_doc') as mock_new_doc:
                    with patch('frappe.db.commit'):
                        mock_company = MagicMock()
                        mock_new_doc.return_value = mock_company
                        
                        result = self.client.sync_organization_to_frappe()
                        
                        # Verify new company created
                        mock_new_doc.assert_called_once_with("Company")
                        
                        # Verify fields set
                        self.assertEqual(mock_company.company_name, "Sync Test Company")
                        self.assertEqual(mock_company.email, "sync@test.com")
                        self.assertEqual(mock_company.tax_id, "NL987654321B01")
                        self.assertEqual(mock_company.address_line1, "Test Street 42")
                        self.assertEqual(mock_company.city, "Test City")
                        self.assertEqual(mock_company.postal_code, "1234 AB")
                        self.assertEqual(mock_company.country, "NL")
                        
                        # Verify save called
                        mock_company.save.assert_called_once()
                        
                        # Verify result
                        self.assertEqual(result["status"], "success")
                        self.assertIn("email", result["synced_fields"])
                        self.assertIn("vat_number", result["synced_fields"])

    def test_sync_organization_to_frappe_existing_company(self):
        """Test syncing organization to existing Frappe company"""
        mock_org_response = {
            "resource": "organization",
            "id": "org_update",
            "name": "Existing Company",
            "email": "updated@email.com",
            "vatNumber": "NL111222333B01"
        }
        
        with patch.object(self.client, 'get', return_value=mock_org_response):
            with patch('frappe.db.exists', return_value=True):
                with patch('frappe.get_doc') as mock_get_doc:
                    with patch('frappe.db.commit'):
                        mock_company = MagicMock()
                        mock_get_doc.return_value = mock_company
                        
                        result = self.client.sync_organization_to_frappe()
                        
                        # Verify existing company fetched
                        mock_get_doc.assert_called_once_with("Company", "Existing Company")
                        
                        # Verify fields updated
                        self.assertEqual(mock_company.email, "updated@email.com")
                        self.assertEqual(mock_company.tax_id, "NL111222333B01")
                        
                        # Verify save called
                        mock_company.save.assert_called_once()
                        
                        # Verify result
                        self.assertEqual(result["status"], "success")
                        self.assertEqual(result["company_name"], "Existing Company")

    def test_sync_organization_to_frappe_error_handling(self):
        """Test error handling during organization sync"""
        mock_org_response = {
            "resource": "organization",
            "id": "org_error",
            "name": "Error Company"
        }
        
        with patch.object(self.client, 'get', return_value=mock_org_response):
            with patch('frappe.db.exists', side_effect=Exception("Database error")):
                with patch('frappe.log_error') as mock_log_error:
                    result = self.client.sync_organization_to_frappe()
                    
                    # Verify error handling
                    self.assertEqual(result["status"], "failed")
                    self.assertIn("Database error", result["error"])
                    
                    # Verify error logged
                    mock_log_error.assert_called_once()
                    
                    # Verify audit trail error
                    audit_calls = self.mock_audit_trail.log_event.call_args_list
                    error_logged = any(
                        call[0][1].value == "ERROR" 
                        for call in audit_calls
                    )
                    self.assertTrue(error_logged)

    def test_organization_without_address(self):
        """Test handling organization without address"""
        mock_response = {
            "resource": "organization",
            "id": "org_no_address",
            "name": "No Address Org",
            "email": "noaddress@org.com",
            "address": None
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            info = self.client.get_organization_info()
            
            # Should handle missing address gracefully
            self.assertNotIn("address", info)
            
            # Verify warning in verification
            verification = self.client.verify_organization_status()
            self.assertIn("Address information incomplete", verification["warnings"])

    def test_organization_display_name(self):
        """Test organization display name generation"""
        # Test with full name
        mock_response = {
            "resource": "organization",
            "id": "org_1",
            "name": "Test Organization B.V."
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            org = self.client.get_current_organization()
            self.assertEqual(org.get_display_name(), "Test Organization B.V.")
        
        # Test with no name
        mock_response["name"] = None
        with patch.object(self.client, 'get', return_value=mock_response):
            org = self.client.get_current_organization()
            self.assertEqual(org.get_display_name(), "Organization org_1")

    def test_organization_partial_address(self):
        """Test organization with partial address information"""
        mock_response = {
            "resource": "organization",
            "id": "org_partial",
            "name": "Partial Address Org",
            "email": "partial@org.com",
            "address": {
                "city": "Amsterdam",
                "country": "NL"
                # Missing street and postal code
            }
        }
        
        with patch.object(self.client, 'get', return_value=mock_response):
            result = self.client.sync_organization_to_frappe()
            
            # Should sync available fields only
            self.assertEqual(result["status"], "success")
            self.assertIn("city", result["synced_fields"])
            self.assertIn("country", result["synced_fields"])
            self.assertNotIn("street", result["synced_fields"])
            self.assertNotIn("postal_code", result["synced_fields"])


if __name__ == "__main__":
    unittest.main()