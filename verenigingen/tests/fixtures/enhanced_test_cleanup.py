"""
Enhanced test cleanup that handles customers created by membership applications
"""

import frappe


class EnhancedTestCleanup:
    """Enhanced cleanup that tracks and cleans up related customers"""
    
    def __init__(self):
        self.tracked_members = []
        self.tracked_customers = []
        self.tracked_applications = []
        
    def track_member(self, member_name):
        """Track a member for cleanup including their customer"""
        self.tracked_members.append(member_name)
        
    def track_membership_application(self, application_name):
        """Track a membership application for cleanup"""
        self.tracked_applications.append(application_name)
        
    def track_customer(self, customer_name):
        """Explicitly track a customer for cleanup"""
        self.tracked_customers.append(customer_name)
        
    def cleanup_all(self):
        """Clean up all tracked records including customers created by members"""
        errors = []
        
        # First, collect all customers linked to tracked members
        for member_name in self.tracked_members:
            try:
                member = frappe.get_doc("Member", member_name)
                if member.customer:
                    self.tracked_customers.append(member.customer)
            except Exception as e:
                errors.append(f"Error checking member {member_name}: {str(e)}")
        
        # Also check membership applications
        for app_name in self.tracked_applications:
            try:
                app = frappe.get_doc("Membership Application", app_name)
                if hasattr(app, "member") and app.member:
                    member = frappe.get_doc("Member", app.member)
                    if member.customer:
                        self.tracked_customers.append(member.customer)
            except Exception as e:
                errors.append(f"Error checking application {app_name}: {str(e)}")
        
        # Clean up in dependency order
        # 1. First clean up documents that depend on customers
        self._cleanup_dependent_documents()
        
        # 2. Clean up customers
        for customer_name in list(set(self.tracked_customers)):  # Remove duplicates
            try:
                if frappe.db.exists("Customer", customer_name):
                    # Cancel and delete any linked documents
                    self._cleanup_customer_dependencies(customer_name)
                    
                    # Delete the customer
                    frappe.delete_doc("Customer", customer_name, force=True, )
                    print(f"✅ Deleted customer: {customer_name}")
            except Exception as e:
                errors.append(f"Error deleting customer {customer_name}: {str(e)}")
        
        # 3. Clean up members
        for member_name in self.tracked_members:
            try:
                if frappe.db.exists("Member", member_name):
                    member = frappe.get_doc("Member", member_name)
                    # Cancel memberships first
                    for membership in frappe.get_all("Membership", filters={"member": member_name}):
                        try:
                            membership_doc = frappe.get_doc("Membership", membership.name)
                            if membership_doc.docstatus == 1:
                                membership_doc.cancel()
                            frappe.delete_doc("Membership", membership.name, force=True, )
                        except:
                            pass
                    
                    # Delete member
                    frappe.delete_doc("Member", member_name, force=True, )
                    print(f"✅ Deleted member: {member_name}")
            except Exception as e:
                errors.append(f"Error deleting member {member_name}: {str(e)}")
        
        # 4. Clean up applications
        for app_name in self.tracked_applications:
            try:
                if frappe.db.exists("Membership Application", app_name):
                    frappe.delete_doc("Membership Application", app_name, force=True, )
                    print(f"✅ Deleted application: {app_name}")
            except Exception as e:
                errors.append(f"Error deleting application {app_name}: {str(e)}")
        
        # Clear tracking lists
        self.tracked_members = []
        self.tracked_customers = []
        self.tracked_applications = []
        
        if errors:
            print("⚠️ Cleanup errors:")
            for error in errors:
                print(f"  - {error}")
        
        return {"success": len(errors) == 0, "errors": errors}
    
    def _cleanup_customer_dependencies(self, customer_name):
        """Clean up documents that depend on a customer"""
        # Cancel and delete Sales Invoices
        for invoice in frappe.get_all("Sales Invoice", filters={"customer": customer_name}):
            try:
                doc = frappe.get_doc("Sales Invoice", invoice.name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Sales Invoice", invoice.name, force=True, )
            except:
                pass
        
        # Cancel and delete Payment Entries
        for payment in frappe.get_all("Payment Entry", filters={"party": customer_name, "party_type": "Customer"}):
            try:
                doc = frappe.get_doc("Payment Entry", payment.name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Payment Entry", payment.name, force=True, )
            except:
                pass
        
        # Delete SEPA Mandates
        for mandate in frappe.get_all("SEPA Mandate", filters={"customer": customer_name}):
            try:
                frappe.delete_doc("SEPA Mandate", mandate.name, force=True, )
            except:
                pass
    
    def _cleanup_dependent_documents(self):
        """Clean up other dependent documents"""
        # This can be extended to clean up other document types as needed
        pass


def cleanup_test_customers_by_pattern(pattern="TEST-*"):
    """
    Clean up customers matching a pattern
    Useful for cleaning up test customers that weren't tracked
    """
    customers = frappe.get_all("Customer", filters={"customer_name": ["like", pattern]})
    
    cleanup = EnhancedTestCleanup()
    for customer in customers:
        cleanup.track_customer(customer.name)
    
    return cleanup.cleanup_all()


def cleanup_orphaned_test_customers():
    """
    Clean up customers linked to test members that no longer exist
    """
    # Find customers linked to non-existent members
    orphaned_customers = frappe.db.sql("""
        SELECT c.name, c.customer_name
        FROM `tabCustomer` c
        LEFT JOIN `tabMember` m ON m.customer = c.name
        WHERE c.customer_name LIKE 'TEST-%'
        AND m.name IS NULL
    """, as_dict=True)
    
    cleanup = EnhancedTestCleanup()
    for customer in orphaned_customers:
        cleanup.track_customer(customer.name)
        print(f"Found orphaned customer: {customer.customer_name}")
    
    return cleanup.cleanup_all()


# Example usage in test cases:
"""
from verenigingen.tests.fixtures.enhanced_test_cleanup import EnhancedTestCleanup

class TestMembershipApplication(unittest.TestCase):
    def setUp(self):
        self.cleanup = EnhancedTestCleanup()
        
    def tearDown(self):
        self.cleanup.cleanup_all()
        
    def test_membership_application_approval(self):
        # Create application
        app = create_test_application()
        self.cleanup.track_membership_application(app.name)
        
        # Approve it (this creates member and customer)
        member = approve_application(app)
        self.cleanup.track_member(member.name)
        
        # Test continues...
        # Customer will be automatically cleaned up in tearDown
"""