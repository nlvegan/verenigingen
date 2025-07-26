"""
Test SEPA performance optimizations - N+1 query elimination
"""

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.api.sepa_batch_ui import load_unpaid_invoices, get_invoice_mandate_info, validate_invoice_mandate


class TestSEPAPerformanceOptimization(VereningingenTestCase):
    """Test performance improvements in SEPA operations"""

    def setUp(self):
        super().setUp()
        # Create minimal test data for performance testing
        self.chapter = self.create_test_chapter()
        self.members = []
        
        # Create multiple members with memberships and mandates
        for i in range(5):
            member = self.create_test_member(
                first_name=f"TestMember{i}",
                email=f"testmember{i}@example.com",
                chapter=self.chapter.name
            )
            self.members.append(member)
            
            # Create membership
            membership = self.create_test_membership(
                member=member.name,
                membership_type="Monthly Standard"
            )
            
            # Create SEPA mandate
            sepa_mandate = self.create_test_sepa_mandate(
                member=member.name,
                bank_code="TEST"
            )

    def test_load_unpaid_invoices_query_efficiency(self):
        """Test that load_unpaid_invoices uses efficient batch queries"""
        
        # Should use maximum 3 queries regardless of result size
        with self.assertQueryCount(3):
            result = load_unpaid_invoices(limit=20)
        
        # Verify data structure (if results exist)
        if result:
            for invoice in result:
                required_fields = ['invoice', 'member', 'member_name', 'iban', 
                                 'bic', 'mandate_reference', 'mandate_date']
                for field in required_fields:
                    self.assertIn(field, invoice, f"Missing field: {field}")

    def test_get_invoice_mandate_info_single_query(self):
        """Test that get_invoice_mandate_info uses single optimized query"""
        
        # Should use exactly 1 query with joins
        with self.assertQueryCount(1):
            result = get_invoice_mandate_info("DUMMY-INVOICE-001")
        
        # Result should be None for non-existent invoice
        self.assertIsNone(result, "Should return None for non-existent invoice")

    def test_validate_invoice_mandate_single_query(self):
        """Test that validate_invoice_mandate uses single optimized query"""
        
        if not self.members:
            self.skipTest("No test members available")
        
        member_name = self.members[0].name
        
        # Should use at most 2 queries: 1 for member/mandate data + 1 for IBAN validation
        with self.assertQueryCount(2):
            result = validate_invoice_mandate("DUMMY-INVOICE", member_name)
        
        # Verify result structure
        self.assertIsInstance(result, dict, "Should return dictionary")
        self.assertIn('valid', result, "Should have 'valid' field")

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()