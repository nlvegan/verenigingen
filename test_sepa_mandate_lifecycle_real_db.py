#!/usr/bin/env python3
"""
Integration test for SEPA Mandate Lifecycle Manager using real database operations
This test ensures the code works with actual database fields, not mocked data.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.sepa_mandate_lifecycle_manager import SEPAMandateLifecycleManager


class TestSEPAMandateLifecycleRealDB(VereningingenTestCase):
    """Test SEPA mandate lifecycle manager with real database operations"""

    def setUp(self):
        super().setUp()
        frappe.init(site="dev.veganisme.net")
        frappe.connect()

    def test_get_mandate_info_real_db(self):
        """Test _get_mandate_info with real database fields"""

        # Create a real member and SEPA mandate
        member = self.create_test_member(
            first_name="RealDB", last_name="TestMember", email="realdb@example.com"
        )

        mandate = self.create_test_sepa_mandate(member=member.name, iban="NL91ABNA0417164300")

        # Test the actual _get_mandate_info method (no mocking)
        manager = SEPAMandateLifecycleManager()
        result = manager._get_mandate_info(mandate.mandate_id)

        # Verify the method returns data and doesn't crash
        self.assertIsNotNone(result, "Should return mandate info")
        self.assertEqual(result["mandate_id"], mandate.mandate_id)
        self.assertEqual(result["status"], "Active")
        self.assertEqual(result["member"], member.name)
        self.assertEqual(result["iban"], "NL91ABNA0417164300")

        # Verify it uses correct field names (not the old fake fields)
        # These should be present in the result:
        self.assertIn("first_collection_date", result)  # not "valid_from"
        self.assertIn("expiry_date", result)  # not "valid_until"
        self.assertIn("mandate_type", result)

        # These fake fields should NOT be in the result:
        self.assertNotIn("valid_from", result)
        self.assertNotIn("valid_until", result)
        self.assertNotIn("usage_count", result)  # This should be calculated, not from DB
        self.assertNotIn("last_used_date", result)  # This should be calculated, not from DB

        print(f"✅ Real DB test passed. Result keys: {list(result.keys())}")

    def test_determine_sequence_type_real_db(self):
        """Test determine_sequence_type with real database operations"""

        # Create real test data
        member = self.create_test_member(
            first_name="SeqType", last_name="TestMember", email="seqtype@example.com"
        )

        mandate = self.create_test_sepa_mandate(member=member.name, iban="NL91ABNA0417164301")

        # Test sequence type determination with real data
        manager = SEPAMandateLifecycleManager()
        result = manager.determine_sequence_type(mandate.mandate_id)

        # Should work without errors
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, "is_valid"))
        self.assertTrue(hasattr(result, "usage_type"))

        # For a new mandate with no usage history, should be first use
        print(
            f"✅ Sequence type determination passed. Is valid: {result.is_valid}, Usage type: {result.usage_type}"
        )

    def test_validate_mandate_usage_real_db(self):
        """Test validate_mandate_usage with real database operations"""

        # Create real test data
        member = self.create_test_member(
            first_name="ValidateUsage", last_name="TestMember", email="validateusage@example.com"
        )

        mandate = self.create_test_sepa_mandate(member=member.name, iban="NL91ABNA0417164302")

        # Test mandate usage validation
        manager = SEPAMandateLifecycleManager()
        result = manager.validate_mandate_usage(mandate.mandate_id, 100.0)

        # Should work without database errors
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, "is_valid"))

        print(f"✅ Mandate usage validation passed. Is valid: {result.is_valid}")

    def test_record_mandate_usage_real_db(self):
        """Test record_mandate_usage with real database operations"""

        # Create real test data
        member = self.create_test_member(
            first_name="RecordUsage", last_name="TestMember", email="recordusage@example.com"
        )

        mandate = self.create_test_sepa_mandate(member=member.name, iban="NL91ABNA0417164303")

        # Test recording mandate usage
        manager = SEPAMandateLifecycleManager()

        # This should not crash even though we removed the fake database field updates
        result = manager.record_mandate_usage(mandate.mandate_id, 25.0, "RCUR", "Monthly membership dues")

        # Should return success
        self.assertTrue(result, "record_mandate_usage should return True for success")

        print("✅ Mandate usage recording passed")


if __name__ == "__main__":
    import unittest

    # Run the tests
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSEPAMandateLifecycleRealDB)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("\n🎉 All real database tests passed!")
        print("The SEPA mandate lifecycle manager now works with actual database fields.")
    else:
        print("\n❌ Some tests failed. The fixes may need adjustment.")
        for failure in result.failures:
            print(f"FAILURE: {failure[0]}")
            print(f"         {failure[1]}")
        for error in result.errors:
            print(f"ERROR: {error[0]}")
            print(f"       {error[1]}")
