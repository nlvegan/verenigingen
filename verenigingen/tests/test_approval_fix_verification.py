"""
Simple test to verify the approval function parameter fix
"""
import frappe
import inspect
import unittest

class TestApprovalFunctionFix(unittest.TestCase):
    
    def test_function_signature_fix(self):
        """Verify the approve_membership_application function accepts create_invoice parameter"""
        from verenigingen.api.membership_application_review import approve_membership_application
        
        # Get function signature
        sig = inspect.signature(approve_membership_application)
        params = list(sig.parameters.keys())
        
        print(f"Function parameters: {params}")
        
        # Check that create_invoice parameter exists
        self.assertIn("create_invoice", params, 
            "create_invoice parameter missing - this will cause JavaScript errors!")
        
        # Check parameter has correct default
        create_invoice_param = sig.parameters.get("create_invoice")
        self.assertEqual(create_invoice_param.default, True,
            "create_invoice should default to True")
            
        print("✅ Function signature fix verified!")
        
    def test_field_name_fix(self):
        """Verify the correct field name is used for Verenigingen Settings"""
        # Check if the field exists
        doctype = frappe.get_doc("DocType", "Verenigingen Settings")
        field_names = [field.fieldname for field in doctype.fields]
        
        # Should have member_contact_email, not contact_email
        self.assertIn("member_contact_email", field_names,
            "member_contact_email field should exist")
        self.assertNotIn("contact_email", field_names,
            "contact_email field should not exist")
            
        print("✅ Field name fix verified!")
        
    def test_pending_applications_report_functions(self):
        """Verify the Pending Applications Report API functions work"""
        from verenigingen.api.membership_application_review import get_user_chapter_access, send_overdue_notifications
        
        # Test get_user_chapter_access - should accept **kwargs
        try:
            result = get_user_chapter_access()
            self.assertIsInstance(result, dict)
            self.assertIn("restrict_to_chapters", result)
            print("✅ get_user_chapter_access function works!")
        except TypeError as e:
            if "missing 1 required positional argument" in str(e):
                self.fail("get_user_chapter_access still has parameter issue!")
            else:
                raise
        
        # Test send_overdue_notifications - should accept **kwargs  
        try:
            result = send_overdue_notifications()
            print("✅ send_overdue_notifications function works!")
        except TypeError as e:
            if "missing 1 required positional argument" in str(e):
                self.fail("send_overdue_notifications still has parameter issue!")
            else:
                raise

if __name__ == "__main__":
    unittest.main()