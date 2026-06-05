#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Member DocType Bulk Loading Optimization
Validates that the new bulk loading eliminates the 114 queries/member performance issue
"""

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.batch_performance_optimizer import get_batch_performance_optimizer


class TestMemberBulkOptimization(EnhancedTestCase):
    """Test the optimized bulk loading for Member relationships"""

    def setUp(self):
        super().setUp()
        self.optimizer = get_batch_performance_optimizer()
        
        # Create test members with various relationships to test bulk loading
        self.test_members = []
        for i in range(5):  # Test with 5 members
            member = self.create_test_member(
                first_name=f"BulkTest{i}",
                last_name="Member",
                birth_date="1990-01-01",
                email=f"bulktest{i}@test.invalid"
            )
            self.test_members.append(member)

    def test_bulk_member_loading_query_efficiency(self):
        """Test that bulk loading dramatically reduces query count vs individual loading"""
        member_names = [member.name for member in self.test_members]
        
        # Test the optimized bulk loading method
        with self.assertQueryCount(15):  # 7 bulk queries + some framework overhead, much less than 114 * 5 = 570
            bulk_data = self.optimizer.get_members_with_all_relationships_bulk(member_names)
        
        # Validate we got data for all members
        self.assertEqual(len(bulk_data), len(member_names))
        
        # Validate data structure for each member. The optimizer now returns
        # member_data plus a child_table_stats dict of COUNTS (sepa_mandates,
        # payment_history) — the N+1 elimination tracks counts rather than
        # returning the full relationship lists.
        for member_name in member_names:
            self.assertIn(member_name, bulk_data)
            member_data = bulk_data[member_name]

            self.assertIn("member_data", member_data, f"Missing member_data for {member_name}")
            self.assertIn(
                "child_table_stats", member_data, f"Missing child_table_stats for {member_name}"
            )

            # Validate member_data contains essential fields
            member_base = member_data["member_data"]
            self.assertIn("name", member_base)
            self.assertIn("full_name", member_base)
            self.assertIn("status", member_base)

            # Validate child table stats expose integer counts
            stats = member_data["child_table_stats"]
            for stat_key in ["sepa_mandates", "payment_history"]:
                self.assertIn(stat_key, stats, f"{stat_key} count missing for {member_name}")
                self.assertIsInstance(stats[stat_key], int, f"{stat_key} count must be an int")

    def test_bulk_loading_vs_individual_performance_comparison(self):
        """Compare performance of bulk loading vs individual member loading"""
        member_names = [member.name for member in self.test_members]
        
        # Measure bulk loading performance
        with self.assertQueryCount(15):  # Should be much less than individual
            bulk_start_time = frappe.utils.now_datetime()
            bulk_data = self.optimizer.get_members_with_all_relationships_bulk(member_names) 
            bulk_end_time = frappe.utils.now_datetime()
        
        # Validate bulk loading gives us complete data
        self.assertEqual(len(bulk_data), len(self.test_members))
        
        # Log the performance improvement for verification
        bulk_duration = (bulk_end_time - bulk_start_time).total_seconds() * 1000
        frappe.logger().info(
            f"Bulk loading completed in ~{bulk_duration:.2f}ms for {len(member_names)} members. "
            f"Individual loading would be ~{len(member_names) * 114} queries vs ~7 bulk queries."
        )

    def test_bulk_loading_empty_list_handling(self):
        """Test bulk loading handles empty member list gracefully"""
        with self.assertQueryCount(1):  # Should not execute major queries for empty list
            result = self.optimizer.get_members_with_all_relationships_bulk([])
            
        self.assertEqual(result, {}, "Empty list should return empty dict")

    def test_bulk_loading_nonexistent_members(self):
        """Test bulk loading handles nonexistent members gracefully"""
        nonexistent_members = ["FAKE-MEMBER-1", "FAKE-MEMBER-2"]
        
        with self.assertQueryCount(15):  # Queries should still execute, just return empty results
            result = self.optimizer.get_members_with_all_relationships_bulk(nonexistent_members)
            
        # Should return empty dict since no members found
        self.assertEqual(len(result), 0)

    def test_bulk_loading_performance_statistics_tracking(self):
        """Test that performance statistics are properly tracked"""
        member_names = [member.name for member in self.test_members]
        
        # Clear stats for clean measurement
        initial_optimized_queries = self.optimizer.query_stats.get("optimized_queries", 0)
        
        # Run bulk loading
        self.optimizer.get_members_with_all_relationships_bulk(member_names)
        
        # Verify stats were updated
        final_optimized_queries = self.optimizer.query_stats.get("optimized_queries", 0) 
        self.assertGreater(
            final_optimized_queries, 
            initial_optimized_queries,
            "Optimized query count should increase after bulk loading"
        )
        
        # Verify time saved tracking (should be significant)
        time_saved = self.optimizer.query_stats.get("time_saved_ms", 0)
        self.assertGreater(
            time_saved, 
            0, 
            "Should track time saved vs individual queries"
        )

    def test_bulk_loading_with_sepa_mandate_creation(self):
        """Test bulk loading works correctly when members have SEPA mandates"""
        # Create SEPA mandates for some test members. Use a checksum-valid test
        # IBAN — the previous hand-built "NL91 ABNA 0417 164{i}" values failed
        # IBAN checksum validation.
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        for i in range(2):  # Create mandates for first 2 members
            member = self.test_members[i]

            # Create SEPA mandate for this member
            sepa_mandate = frappe.new_doc("SEPA Mandate")
            sepa_mandate.member = member.name
            sepa_mandate.member_name = member.full_name
            sepa_mandate.mandate_id = f"TEST-MANDATE-{i:03d}"
            sepa_mandate.iban = generate_test_iban("TEST")
            sepa_mandate.bic = "TESTNL2A"
            sepa_mandate.status = "Active"
            sepa_mandate.account_holder_name = member.full_name
            sepa_mandate.sign_date = frappe.utils.today()
            sepa_mandate.save()

            self.track_doc("SEPA Mandate", sepa_mandate.name)
            
        member_names = [member.name for member in self.test_members]
        
        # Test bulk loading with SEPA mandates present
        with self.assertQueryCount(15):
            bulk_data = self.optimizer.get_members_with_all_relationships_bulk(member_names)
        
        # The optimizer exposes SEPA mandate presence via child_table_stats
        # counts rather than the full mandate-link list.
        members_with_mandates = 0
        for member_name, data in bulk_data.items():
            if data["child_table_stats"].get("sepa_mandates", 0) > 0:
                members_with_mandates += 1

        self.assertGreaterEqual(
            members_with_mandates,
            2,
            "Should find at least 2 members with SEPA mandates"
        )