# Deprecated Function Usage Report

🔍 Deprecated Function Usage Report
==================================================
Total deprecated usages found: 5
Functions affected: 3

🚨 Function: create_sales_invoice
   Usages: 1
   Reason: DEPRECATED: Sales Invoice creation removed - using Payment History child table model
   Replacement: Use Payment History child table model

   📍 verenigingen/services/donation_financial_service.py:34
      sales_invoice = self.create_sales_invoice()

🚨 Function: get_creation_user
   Usages: 3
   Reason: Compatibility function - marked for migration review
   Replacement: Verify if secure_operations.get_creation_user exists or should be implemented

   📍 verenigingen/tests/test_membership_application_workflow.py:158
      user = get_creation_user()
   📍 verenigingen/utils/application_helpers.py:55
      with secure_user_context(get_creation_user(), context_description) as ctx:
   📍 verenigingen/utils/application_helpers.py:410
      "owner": get_creation_user(),

🚨 Function: save_with_system_context
   Usages: 1
   Reason: Working compatibility layer - no immediate action needed
   Replacement: Consider migrating to secure_operations.secure_user_context for new code

   📍 verenigingen/utils/application_helpers.py:980
      save_with_system_context(chapter_doc, "pending member addition to chapter")
