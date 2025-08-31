# Test Safe Member Optimizer Child Table Fix

import frappe

from verenigingen.utils.safe_member_optimizer import safe_member_optimizer


def test_child_table_optimization():
    """Test that child table optimization doesn't crash with _cached_meta error"""

    print("Testing Safe Member Optimizer child table fix...")

    # Create a mock member document with the structure that caused issues
    class MockMember:
        def __init__(self):
            self.doctype = "Member"
            self.name = "test-member-001"

            # Mock metadata with child table fields (like the real Member DocType)
            class MockField:
                def __init__(self, fieldname, fieldtype, options=None):
                    self.fieldname = fieldname
                    self.fieldtype = fieldtype
                    self.options = options

            class MockMeta:
                def __init__(self):
                    self.fields = [
                        MockField("iban_history", "Table", "Member IBAN History"),
                        MockField("sepa_mandates", "Table", "Member SEPA Mandate Link"),
                        MockField("payment_history", "Table", "Member Payment History"),
                        MockField("volunteer_expenses", "Table", "Member Volunteer Expenses"),
                        MockField("chapter_membership_history", "Table", "Chapter Membership History"),
                        MockField("volunteer_assignment_history", "Table", "Volunteer Assignment"),
                        MockField("fee_change_history", "Table", "Member Fee Change History"),
                    ]

            self.meta = MockMeta()

            # Initialize empty child tables (lists) - this is what caused the original error
            self.iban_history = []
            self.sepa_mandates = []
            self.payment_history = []
            self.volunteer_expenses = []
            self.chapter_membership_history = []
            self.volunteer_assignment_history = []
            self.fee_change_history = []

    # Test the child table optimization that was failing
    try:
        mock_member = MockMember()
        safe_member_optimizer._optimize_child_tables(mock_member)

        print("✅ Child table optimization completed without errors")
        print("✅ Fix successful - no '_cached_meta' errors on list objects")

        return {"success": True, "message": "Child table optimization fix working correctly"}

    except Exception as e:
        print(f"❌ Child table optimization still failing: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    result = test_child_table_optimization()
    print(f"Test result: {result}")
