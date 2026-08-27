"""
Test SEPA performance optimizations - N+1 query elimination
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists
from verenigingen.verenigingen_payments.api.sepa_batch_ui import load_unpaid_invoices, get_invoice_mandate_info, validate_invoice_mandate


def _unwrap(fn):
    """Return the undecorated business function.

    These endpoints are wrapped by @frappe.whitelist() + @high_security_api,
    whose audit/rate-limit/permission machinery issues a fixed number of extra
    SQL queries per call. Those are constant overhead, not part of the N+1
    behaviour under test, so the query-count assertions measure the bare
    business function (reached via __wrapped__).
    """
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


class TestSEPAPerformanceOptimization(EnhancedTestCase):
    """Test performance improvements in SEPA operations"""

    def setUp(self):
        super().setUp()
        # Tests reference the "Monthly Standard" Membership Type by literal name
        ensure_membership_type_exists("Monthly Standard")
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
                member_name=member.name,
                bank_code="TEST"
            )

        # Warm DocType meta caches (tabDocType/DocField/DocPerm/Custom Field/
        # Property Setter lookups) so the per-test assertQueryCount measures only
        # the business SQL, not one-time meta loading on first access.
        for dt in ("Sales Invoice", "Membership Dues Schedule", "Member", "SEPA Mandate"):
            frappe.get_meta(dt)
        frappe.db.get_value("Sales Invoice", "__warm_cache__")  # warm table-info cache

        # Warm the COLUMN-LIST cache for each table too. `get_meta` does not do it:
        # `Database.get_db_table_columns` keeps its own
        # `table_columns::tab<DocType>` entry in `frappe.client_cache` (Redis), and
        # on a miss it issues an extra
        #     SELECT column_name FROM information_schema.columns WHERE table_name=...
        # INSIDE whatever assertQueryCount window happens to be open. Because that
        # cache is Redis-backed it is shared across processes and survives between
        # runs, so whether the query fires depends on whether anything earlier in
        # the shard touched the table -- and shard bins re-pack whenever any test
        # file is edited. That made `test_validate_invoice_mandate_single_query`
        # fail on a branch that changed none of the code it measures, while passing
        # on the same commit in a differently-packed shard.
        #
        # Reproduce the failure with:
        #     frappe.client_cache.delete_value("table_columns::tabSEPA Mandate")
        for dt in ("Sales Invoice", "Membership Dues Schedule", "Member", "SEPA Mandate"):
            frappe.db.get_table_columns(dt)

    def test_load_unpaid_invoices_query_efficiency(self):
        """Test that load_unpaid_invoices uses efficient batch queries"""
        
        # Should use maximum 3 queries regardless of result size
        with self.assertQueryCount(3):
            result = _unwrap(load_unpaid_invoices)(limit=20)
        
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
            result = _unwrap(get_invoice_mandate_info)("DUMMY-INVOICE-001")
        
        # Result should be None for non-existent invoice
        self.assertIsNone(result, "Should return None for non-existent invoice")

    def test_validate_invoice_mandate_single_query(self):
        """Test that validate_invoice_mandate uses single optimized query"""
        
        if not self.members:
            self.skipTest("No test members available")
        
        member_name = self.members[0].name
        
        # Should use at most 2 queries: 1 for member/mandate data + 1 for IBAN validation
        with self.assertQueryCount(2):
            result = _unwrap(validate_invoice_mandate)("DUMMY-INVOICE", member_name)
        
        # Verify result structure
        self.assertIsInstance(result, dict, "Should return dictionary")
        self.assertIn('valid', result, "Should have 'valid' field")

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()