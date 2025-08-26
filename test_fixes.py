"""
Fixes for SEPA Test Infrastructure Field References

This file contains the corrected field references and improved patterns
for the SEPA test infrastructure.
"""

# Fixed Member-Mandate relationship query
CORRECTED_MEMBER_MANDATE_QUERY = """
SELECT
    m.name as member_name,
    m.full_name as member_full_name,
    m.customer,
    sm.name as mandate_name,
    sm.iban as mandate_iban,
    sm.mandate_id,
    sm.status as mandate_status,
    sm.sign_date,
    sm.bic as mandate_bic,
    sm.account_holder_name
FROM `tabMember` m
JOIN `tabSEPA Mandate` sm ON sm.member = m.name
WHERE m.name IN %(member_names)s
    AND m.status = 'Active'
    AND sm.status = 'Active'
ORDER BY m.name, sm.creation DESC
"""


# Improved test factory pattern
class ImprovedSEPATestFactory:
    """
    Demonstrates improved patterns for SEPA test data factory
    """

    def create_member_with_active_mandate(self, **kwargs):
        """Create member with guaranteed active SEPA mandate"""
        # Create member first
        member = self.create_test_member(**kwargs)

        # Create SEPA mandate
        mandate = self.create_test_sepa_mandate(
            member=member.name,
            status="Active",
            iban=self.generate_test_iban(),
            mandate_id=self.generate_mandate_id(),
        )

        # Verify the relationship exists
        self.assertTrue(frappe.db.exists("SEPA Mandate", {"member": member.name, "status": "Active"}))

        return {"member": member, "mandate": mandate, "relationship_verified": True}

    def get_active_mandate_for_member(self, member_name: str):
        """Get active mandate using proper query"""
        mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member_name, "status": "Active"},
            fields=["name", "iban", "mandate_id", "bic"],
            order_by="creation desc",
            limit=1,
        )

        return mandates[0] if mandates else None


# Corrected Sales Invoice field usage
def create_test_sales_invoice_corrected(self, customer, member, **kwargs):
    """Corrected Sales Invoice creation with proper field names"""
    invoice = frappe.new_doc("Sales Invoice")
    invoice.update(
        {
            "customer": customer,
            "member": member,  # Correct: not custom_member
            "membership": kwargs.get("membership"),  # Correct: not custom_membership
            "custom_paying_for_member": kwargs.get("paying_for_member"),  # Correct custom field
            "membership_dues_schedule_display": kwargs.get("schedule"),  # Correct custom field
            **kwargs,
        }
    )

    return invoice


# Performance testing patterns
def test_query_optimization_pattern(self):
    """Template for proper query optimization testing"""

    # 1. Establish baseline
    def baseline_operation(items):
        results = []
        for item in items:
            # Simulate N+1 queries
            result = frappe.get_doc("Sales Invoice", item)
            member = frappe.get_doc("Member", result.member) if result.member else None
            mandate = None
            if member:
                mandates = frappe.get_all("SEPA Mandate", filters={"member": member.name, "status": "Active"})
                if mandates:
                    mandate = frappe.get_doc("SEPA Mandate", mandates[0].name)
            results.append({"invoice": result, "member": member, "mandate": mandate})
        return results

    # 2. Create test data
    test_items = [self.create_test_sales_invoice() for _ in range(10)]
    item_names = [item.name for item in test_items]

    # 3. Measure baseline (expect high query count)
    with self.assertQueryCount(35, 45):  # Range for N+1 queries (10*3 + overhead)
        baseline_results = baseline_operation(item_names)

    # 4. Test optimized version (should be much lower)
    with self.assertQueryCount(5, 10):  # Should be constant regardless of batch size
        optimized_results = self.optimizer.process_batch_invoices_optimized(item_names)

    # 5. Verify equivalent results
    self.assertEqual(len(baseline_results), len(optimized_results))
