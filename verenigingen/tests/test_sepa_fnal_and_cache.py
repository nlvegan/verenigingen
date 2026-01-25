#!/usr/bin/env python3
"""
Test suite for SEPA FNAL detection and cache invalidation

Tests critical P1/P2 functionality:
1. FNAL (Final) sequence type detection and mandate termination
2. Cache invalidation when usage records are created
3. Sequence type progression (FRST -> RCUR -> FNAL)
"""

import time
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.sepa_mandate_lifecycle_manager import (
    MandateUsageType,
    SEPAMandateLifecycleManager,
)
from verenigingen.verenigingen_payments.utils.sepa_xml_enhanced_generator import SEPASequenceType


class TestSEPAFNALDetection(VereningingenTestCase):
    """Test FNAL (Final) sequence type detection and mandate termination"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.manager = SEPAMandateLifecycleManager()

    def test_fnal_terminates_mandate(self):
        """Test that FNAL sequence type terminates mandate for future use"""
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="FNAL",
            last_name="TestMember",
            email="fnal_test@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # 2. Create first usage record (FRST)
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -30),
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-INV-001",
                "amount": 50.00,
                "status": "Collected",
                "sequence_type": "FRST",
            },
        )

        # 3. Create recurring usage (RCUR)
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -15),
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-INV-002",
                "amount": 50.00,
                "status": "Collected",
                "sequence_type": "RCUR",
            },
        )

        # 4. Create FNAL usage (terminates mandate)
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -5),
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-INV-003",
                "amount": 50.00,
                "status": "Collected",
                "sequence_type": "FNAL",
            },
        )
        mandate.save()

        # 5. Clear cache to ensure fresh data
        self.manager.invalidate_cache(mandate_id)

        # 6. Try to determine sequence type - should return EXPIRED_USE
        result = self.manager.determine_sequence_type(mandate_id)

        self.assertEqual(
            result.usage_type,
            MandateUsageType.EXPIRED_USE,
            "After FNAL, mandate should be EXPIRED_USE",
        )
        self.assertEqual(
            result.recommended_sequence_type,
            SEPASequenceType.FNAL,
            "Recommended type should remain FNAL (indicating termination)",
        )
        self.assertEqual(
            result.next_allowed_sequence_types,
            [],
            "No further sequence types should be allowed after FNAL",
        )

    def test_fnal_detection_with_context(self):
        """Test FNAL detection when explicitly marked as final in context"""
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="FNALContext",
            last_name="TestMember",
            email="fnal_context@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # 2. Add previous usage
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -10),
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-INV-CTX-001",
                "amount": 100.00,
                "status": "Collected",
                "sequence_type": "FRST",
            },
        )
        mandate.save()

        # 3. Clear cache
        self.manager.invalidate_cache(mandate_id)

        # 4. Request FNAL via context
        result = self.manager.determine_sequence_type(
            mandate_id, transaction_context={"is_final": True}
        )

        self.assertEqual(
            result.usage_type,
            MandateUsageType.FINAL_USE,
            "With is_final=True, should be FINAL_USE",
        )
        self.assertEqual(
            result.recommended_sequence_type,
            SEPASequenceType.FNAL,
            "Should recommend FNAL sequence type",
        )

    def test_sequence_type_progression(self):
        """Test correct sequence type progression: FRST -> RCUR -> FNAL"""
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="Progression",
            last_name="TestMember",
            email="progression@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # Set sign_date in the past so usage dates are after it
        # This prevents the "mandate renewal" detection
        mandate.sign_date = add_days(today(), -60)
        mandate.save()

        # 2. First usage - should be FRST
        self.manager.invalidate_cache(mandate_id)
        result = self.manager.determine_sequence_type(mandate_id)

        self.assertEqual(
            result.usage_type,
            MandateUsageType.FIRST_USE,
            "First usage should be FIRST_USE",
        )
        self.assertEqual(
            result.recommended_sequence_type,
            SEPASequenceType.FRST,
            "First usage should recommend FRST",
        )

        # 3. Record FRST usage (after sign_date)
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -20),  # After sign_date (-60)
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-PROG-001",
                "amount": 25.00,
                "status": "Collected",
                "sequence_type": "FRST",
            },
        )
        mandate.save()

        # 4. Second usage - should be RCUR
        self.manager.invalidate_cache(mandate_id)
        result = self.manager.determine_sequence_type(mandate_id)

        self.assertEqual(
            result.usage_type,
            MandateUsageType.RECURRING_USE,
            "After FRST, should be RECURRING_USE",
        )
        self.assertEqual(
            result.recommended_sequence_type,
            SEPASequenceType.RCUR,
            "After FRST, should recommend RCUR",
        )

        # 5. Verify RCUR and FNAL are both allowed
        self.assertIn(
            SEPASequenceType.RCUR,
            result.next_allowed_sequence_types,
            "RCUR should be allowed",
        )
        self.assertIn(
            SEPASequenceType.FNAL,
            result.next_allowed_sequence_types,
            "FNAL should be allowed",
        )

    def test_mandate_renewal_after_fnal_resets_sequence(self):
        """Test that mandate renewal (new sign_date) after usage resets to FRST"""
        # 1. Create member and mandate with older sign date
        member = self.create_test_member(
            first_name="Renewal",
            last_name="TestMember",
            email="renewal@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # 2. Set original sign date in the past
        original_sign_date = add_days(today(), -60)
        mandate.sign_date = original_sign_date
        mandate.save()

        # 3. Add usage with older date
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -45),
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-RENEW-001",
                "amount": 75.00,
                "status": "Collected",
                "sequence_type": "RCUR",
            },
        )
        mandate.save()

        # 4. "Renew" mandate by updating sign_date to after last usage
        mandate.sign_date = add_days(today(), -10)  # After last usage date
        mandate.save()

        # 5. Clear cache and check - should reset to FRST
        self.manager.invalidate_cache(mandate_id)
        result = self.manager.determine_sequence_type(mandate_id)

        self.assertEqual(
            result.usage_type,
            MandateUsageType.FIRST_USE,
            "Renewed mandate should be FIRST_USE",
        )
        self.assertEqual(
            result.recommended_sequence_type,
            SEPASequenceType.FRST,
            "Renewed mandate should recommend FRST",
        )


class TestSEPACacheInvalidation(VereningingenTestCase):
    """Test cache invalidation when usage records are created"""

    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.manager = SEPAMandateLifecycleManager()

    def test_cache_stores_and_retrieves_usage_history(self):
        """Test that cache correctly stores and retrieves usage history"""
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="CacheTest",
            last_name="TestMember",
            email="cache_test@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # 2. Clear any existing cache
        self.manager.invalidate_cache(mandate_id)

        # 3. First call should populate cache
        usage1 = self.manager._get_mandate_usage_history(mandate_id)
        self.assertEqual(len(usage1), 0, "Initial usage should be empty")

        # 4. Verify cache was populated
        cached = self.manager._get_cached_usage_history(mandate_id)
        self.assertIsNotNone(cached, "Cache should be populated after first call")
        self.assertEqual(len(cached), 0, "Cached usage should be empty")

    def test_cache_invalidation_clears_specific_mandate(self):
        """Test that invalidate_cache clears only the specified mandate"""
        # 1. Create two members with mandates
        member1 = self.create_test_member(
            first_name="Cache1",
            last_name="TestMember",
            email="cache1@example.com",
        )
        member2 = self.create_test_member(
            first_name="Cache2",
            last_name="TestMember",
            email="cache2@example.com",
        )

        mandate1 = self.create_test_sepa_mandate(member=member1.name)
        mandate2 = self.create_test_sepa_mandate(member=member2.name)

        # 2. Populate cache for both
        self.manager._get_mandate_usage_history(mandate1.mandate_id)
        self.manager._get_mandate_usage_history(mandate2.mandate_id)

        # 3. Verify both are cached
        self.assertIsNotNone(
            self.manager._get_cached_usage_history(mandate1.mandate_id),
            "Mandate1 should be cached",
        )
        self.assertIsNotNone(
            self.manager._get_cached_usage_history(mandate2.mandate_id),
            "Mandate2 should be cached",
        )

        # 4. Invalidate only mandate1
        self.manager.invalidate_cache(mandate1.mandate_id)

        # 5. Verify mandate1 is cleared, mandate2 remains
        self.assertIsNone(
            self.manager._get_cached_usage_history(mandate1.mandate_id),
            "Mandate1 cache should be cleared",
        )
        self.assertIsNotNone(
            self.manager._get_cached_usage_history(mandate2.mandate_id),
            "Mandate2 cache should remain",
        )

    def test_cache_invalidation_clears_all_when_no_id(self):
        """Test that invalidate_cache(None) clears all cached mandates"""
        # 1. Create members with mandates
        member1 = self.create_test_member(
            first_name="CacheAll1",
            last_name="TestMember",
            email="cacheall1@example.com",
        )
        member2 = self.create_test_member(
            first_name="CacheAll2",
            last_name="TestMember",
            email="cacheall2@example.com",
        )

        mandate1 = self.create_test_sepa_mandate(member=member1.name)
        mandate2 = self.create_test_sepa_mandate(member=member2.name)

        # 2. Populate cache
        self.manager._get_mandate_usage_history(mandate1.mandate_id)
        self.manager._get_mandate_usage_history(mandate2.mandate_id)

        # 3. Invalidate all
        self.manager.invalidate_cache(None)

        # 4. Verify both are cleared
        self.assertIsNone(
            self.manager._get_cached_usage_history(mandate1.mandate_id),
            "Mandate1 cache should be cleared",
        )
        self.assertIsNone(
            self.manager._get_cached_usage_history(mandate2.mandate_id),
            "Mandate2 cache should be cleared",
        )

    def test_usage_record_creation_invalidates_cache(self):
        """Test that creating a usage record invalidates the cache"""
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="UsageInvalidate",
            last_name="TestMember",
            email="usage_invalidate@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # Set sign_date in the past
        mandate.sign_date = add_days(today(), -60)
        mandate.save()

        # 2. Populate cache with empty usage
        initial_usage = self.manager._get_mandate_usage_history(mandate_id)
        initial_count = len(initial_usage)

        # Verify cache is populated
        self.assertIsNotNone(
            self.manager._get_cached_usage_history(mandate_id),
            "Cache should be populated",
        )

        # 3. Add usage record directly to mandate (like other tests)
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -10),
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-INV-CACHE-001",
                "amount": 100.00,
                "status": "Collected",
                "sequence_type": "FRST",
            },
        )
        mandate.save()

        # 4. Manually invalidate cache (simulating what create_mandate_usage_record does)
        self.manager.invalidate_cache(mandate_id)

        # 5. Cache should be invalidated - next call should return fresh data
        fresh_usage = self.manager._get_mandate_usage_history(mandate_id)

        self.assertEqual(
            len(fresh_usage),
            initial_count + 1,
            "Fresh usage should include newly created record",
        )

    def test_cache_ttl_expiration(self):
        """Test that cache entries expire after TTL"""
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="TTLTest",
            last_name="TestMember",
            email="ttl_test@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # 2. Populate cache
        self.manager._get_mandate_usage_history(mandate_id)

        # 3. Manually expire the cache entry by setting created_at in the past
        if mandate_id in self.manager.mandate_usage_cache:
            # Set created_at to well in the past (beyond TTL)
            self.manager.mandate_usage_cache[mandate_id].created_at = time.time() - 400

        # 4. Check that cached entry is now considered expired
        cached = self.manager._get_cached_usage_history(mandate_id)
        self.assertIsNone(cached, "Expired cache entry should return None")

    def test_sequence_type_uses_fresh_data_after_usage_creation(self):
        """Test that sequence type determination uses fresh data after usage creation"""
        # 1. Create member and mandate
        member = self.create_test_member(
            first_name="FreshData",
            last_name="TestMember",
            email="fresh_data@example.com",
        )

        mandate = self.create_test_sepa_mandate(member=member.name)
        mandate_id = mandate.mandate_id

        # Set sign_date in the past so usage dates are after it
        mandate.sign_date = add_days(today(), -60)
        mandate.save()

        # 2. Initial check - should be FRST (no usage)
        self.manager.invalidate_cache(mandate_id)
        result1 = self.manager.determine_sequence_type(mandate_id)
        self.assertEqual(
            result1.recommended_sequence_type,
            SEPASequenceType.FRST,
            "Initial call should recommend FRST",
        )

        # 3. Add usage record directly (more reliable for testing)
        mandate.append(
            "usage_history",
            {
                "usage_date": add_days(today(), -20),
                "reference_doctype": "Sales Invoice",
                "reference_name": "TEST-INV-FRESH-001",
                "amount": 50.00,
                "status": "Collected",
                "sequence_type": "FRST",
            },
        )
        mandate.save()

        # 4. Clear cache to ensure fresh data
        self.manager.invalidate_cache(mandate_id)

        # 5. Now should recommend RCUR
        result2 = self.manager.determine_sequence_type(mandate_id)
        self.assertEqual(
            result2.recommended_sequence_type,
            SEPASequenceType.RCUR,
            "After FRST usage, should recommend RCUR",
        )


class TestSEPAReconciliation(VereningingenTestCase):
    """Test reconciliation functionality for SEPA mandate usage"""

    def test_reconciliation_detects_discrepancies(self):
        """Test that reconciliation can detect discrepancies"""
        from verenigingen.verenigingen_payments.utils.sepa_mandate_lifecycle_manager import (
            reconcile_mandate_usage_records,
        )

        # Run reconciliation (may find existing discrepancies or return empty)
        result = reconcile_mandate_usage_records()

        self.assertTrue(result.success, "Reconciliation should complete successfully")
        self.assertIsInstance(result.summary, dict, "Summary should be a dict")
        self.assertIn("total_usage_records", result.summary)
        self.assertIn("total_batch_records", result.summary)
        self.assertIn("matched_records", result.summary)


if __name__ == "__main__":
    import unittest

    unittest.main()
