"""
Comprehensive integration tests for membership application approval workflow
Tests the complete end-to-end flow including JavaScript-Python integration
"""

import frappe
import unittest
from unittest.mock import patch
from verenigingen.tests.utils.base import VereningingenTestCase


class TestMembershipApplicationIntegration(VereningingenTestCase):
    """Test the complete membership application approval workflow"""

    def setUp(self):
        super().setUp()
        
        # Create a test member in pending status
        self.test_member = self.create_test_member(
            first_name="Integration",
            last_name="Test",
            email="integration.test@example.com",
            status="Pending",
            application_status="Pending"
        )
        
        # Create a test membership type
        self.membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "name": "Test Integration Type",
            "membership_type_name": "Test Integration Type",
            "amount": 25.0,
            "is_active": 1,
            "is_published": 1
        })
        self.membership_type.insert()
        self.track_doc("Membership Type", self.membership_type.name)

    def test_function_signature_compatibility(self):
        """Test that the approve_membership_application function accepts all expected parameters"""
        from verenigingen.api.membership_application_review import approve_membership_application
        import inspect
        
        # Get function signature
        sig = inspect.signature(approve_membership_application)
        
        # Check that all expected parameters exist
        expected_params = ["member_name", "membership_type", "chapter", "notes", "create_invoice"]
        actual_params = list(sig.parameters.keys())
        
        for param in expected_params:
            self.assertIn(param, actual_params, 
                f"Function missing expected parameter: {param}")

    def test_verenigingen_settings_fields_exist(self):
        """Test that all required fields exist in Verenigingen Settings"""
        # Check if the doctype exists
        self.assertTrue(frappe.db.exists("DocType", "Verenigingen Settings"))
        
        # Get the doctype structure
        doctype = frappe.get_doc("DocType", "Verenigingen Settings")
        field_names = [field.fieldname for field in doctype.fields]
        
        # Check for required fields
        required_fields = [
            "member_contact_email",
            "support_email",
            "company_name",
            "creditor_id"
        ]
        
        for field in required_fields:
            self.assertIn(field, field_names, 
                f"Verenigingen Settings missing required field: {field}")

    def test_approval_function_with_all_parameters(self):
        """Test approval function with all JavaScript parameters"""
        from verenigingen.api.membership_application_review import approve_membership_application
        
        # Test with all parameters that JavaScript sends
        try:
            # Mock the frappe.db.get_single_value to return a valid email
            with patch('frappe.db.get_single_value') as mock_get_single:
                mock_get_single.return_value = "test@example.com"
                
                # This should not raise an error about missing parameters
                result = approve_membership_application(
                    member_name=self.test_member.name,
                    membership_type=self.membership_type.name,
                    chapter=None,
                    notes="Test approval",
                    create_invoice=True
                )
                
                # The function should complete without parameter errors
                self.assertIsNotNone(result)
                
        except TypeError as e:
            self.fail(f"Function signature mismatch: {str(e)}")

    def test_missing_field_error_handling(self):
        """Test that missing field errors are handled gracefully"""
        from verenigingen.api.membership_application_review import send_approval_notification
        
        # Test with a member, mock invoice, and membership type
        mock_invoice = frappe._dict({
            "name": "TEST-INV-001",
            "grand_total": 25.0
        })
        
        # This should handle missing fields gracefully
        try:
            send_approval_notification(
                self.test_member, 
                mock_invoice, 
                self.membership_type
            )
        except frappe.ValidationError as e:
            # If we get a validation error, it should be descriptive
            error_message = str(e)
            self.assertIn("does not exist", error_message)
            
    def test_email_template_fallback(self):
        """Test that email sending falls back gracefully when templates don't exist"""
        from verenigingen.api.membership_application_review import send_approval_notification
        
        # Mock invoice
        mock_invoice = frappe._dict({
            "name": "TEST-INV-002",
            "grand_total": 25.0
        })
        
        # Mock the single value calls to return valid data
        with patch('frappe.db.get_single_value') as mock_get_single:
            mock_get_single.return_value = "test@example.com"
            
            with patch('frappe.sendmail') as mock_sendmail:
                try:
                    send_approval_notification(
                        self.test_member,
                        mock_invoice,
                        self.membership_type
                    )
                    
                    # Should call sendmail without errors
                    mock_sendmail.assert_called()
                    
                except Exception as e:
                    self.fail(f"Email sending failed: {str(e)}")

    def test_application_approval_complete_workflow(self):
        """Test the complete approval workflow end-to-end"""
        from verenigingen.api.membership_application_review import approve_membership_application
        
        # Mock all external dependencies
        with patch('frappe.db.get_single_value') as mock_get_single:
            mock_get_single.return_value = "test@example.com"
            
            with patch('frappe.sendmail') as mock_sendmail:
                with patch('frappe.defaults.get_global_default') as mock_default:
                    mock_default.return_value = "Test Company"
                    
                    # Run the complete approval workflow
                    try:
                        result = approve_membership_application(
                            member_name=self.test_member.name,
                            membership_type=self.membership_type.name,
                            create_invoice=True
                        )
                        
                        # Check that the member status was updated
                        self.test_member.reload()
                        self.assertEqual(self.test_member.application_status, "Approved")
                        
                        # Should have called sendmail for notification
                        mock_sendmail.assert_called()
                        
                    except Exception as e:
                        self.fail(f"Complete workflow failed: {str(e)}")

    def test_javascript_parameter_validation(self):
        """Test that we catch JavaScript-Python parameter mismatches"""
        # Simulate the exact parameters that JavaScript sends
        js_parameters = {
            "member_name": self.test_member.name,
            "create_invoice": True,
            "membership_type": self.membership_type.name,
            "chapter": None,
            "notes": "Test approval from JS"
        }
        
        from verenigingen.api.membership_application_review import approve_membership_application
        
        # Mock dependencies
        with patch('frappe.db.get_single_value') as mock_get_single:
            mock_get_single.return_value = "test@example.com"
            
            with patch('frappe.sendmail'):
                with patch('frappe.defaults.get_global_default') as mock_default:
                    mock_default.return_value = "Test Company"
                    
                    try:
                        # This should work without any parameter errors
                        result = approve_membership_application(**js_parameters)
                        self.assertIsNotNone(result)
                        
                    except TypeError as e:
                        if "unexpected keyword argument" in str(e) or "missing" in str(e):
                            self.fail(f"JavaScript-Python parameter mismatch: {str(e)}")
                        else:
                            # Other errors are acceptable for this test
                            pass

    def test_field_name_consistency(self):
        """Test that field names used in code match actual DocType fields"""
        # Check Member doctype fields
        member_doctype = frappe.get_doc("DocType", "Member")
        member_fields = [field.fieldname for field in member_doctype.fields]
        
        # Check for commonly used fields
        expected_member_fields = [
            "application_status",
            "selected_membership_type",
            "email",
            "full_name",
            "first_name"
        ]
        
        for field in expected_member_fields:
            self.assertIn(field, member_fields,
                f"Member doctype missing expected field: {field}")
                
        # Check Verenigingen Settings fields
        settings_doctype = frappe.get_doc("DocType", "Verenigingen Settings")
        settings_fields = [field.fieldname for field in settings_doctype.fields]
        
        # This test would have caught the contact_email vs member_contact_email issue
        self.assertIn("member_contact_email", settings_fields,
            "Verenigingen Settings should have member_contact_email field")
        self.assertNotIn("contact_email", settings_fields,
            "contact_email field doesn't exist - should use member_contact_email")

if __name__ == "__main__":
    unittest.main()