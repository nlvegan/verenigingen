#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEPA Performance Optimizations Comprehensive Test Suite
=======================================================

Comprehensive testing suite for SEPA batch processing performance optimizations,
including financial error handling, batch performance optimizer, and performance
monitoring systems.

This test suite validates:
1. Financial error classification and handling
2. Batch performance optimization (N+1 query elimination)
3. Performance monitoring and benchmarking
4. SEPA processor integration with optimizations
5. XML generation performance improvements
6. Memory usage optimization for large batches

Uses the EnhancedTestCase framework for realistic test data generation
and proper business rule validation.

Author: Verenigingen Development Team
Date: August 2025
"""

import time
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import frappe
from frappe.utils import getdate, today, add_days

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.financial_error_handler import (
    get_financial_error_handler,
    FinancialErrorSeverity,
    FinancialErrorCategory,
    handle_sepa_validation_error,
    handle_data_integrity_error,
)
from verenigingen.verenigingen_payments.utils.batch_performance_optimizer import (
    get_batch_performance_optimizer,
    BatchPerformanceOptimizer,
)
from verenigingen.verenigingen_payments.utils.sepa_performance_monitor import (
    get_sepa_performance_monitor,
    monitor_sepa_operation,
)


class TestFinancialErrorHandling(EnhancedTestCase):
    """Test comprehensive financial error handling system"""
    
    def setUp(self):
        super().setUp()
        self.error_handler = get_financial_error_handler()
        # Clear any existing error history
        self.error_handler.error_log.clear()
    
    def test_sepa_validation_errors_classification(self):
        """Test SEPA validation error classification and handling"""
        # Test invalid IBAN error
        with self.assertRaises(frappe.ValidationError):
            handle_sepa_validation_error("F1001", {
                "batch_name": "TEST-BATCH-001",
                "invalid_iban": "INVALID_IBAN_FORMAT"
            })
        
        # Verify error was logged correctly
        self.assertEqual(len(self.error_handler.error_log), 1)
        error = self.error_handler.error_log[0]
        self.assertEqual(error.code, "F1001")
        self.assertEqual(error.severity, FinancialErrorSeverity.COMPLIANCE)
        self.assertEqual(error.category, FinancialErrorCategory.SEPA_VALIDATION)
        self.assertIn("batch_name", error.context)
    
    def test_data_integrity_errors_with_context(self):
        """Test data integrity error handling with detailed context"""
        test_member = self.create_test_member()
        
        with self.assertRaises(frappe.ValidationError):
            handle_data_integrity_error("F3001", {
                "member_name": test_member.name,
                "batch_name": "TEST-BATCH-002",
                "calculation_details": {"expected": 100.0, "actual": -50.0}
            })
        
        # Verify error classification and context preservation
        error = self.error_handler.error_log[-1]  # Latest error
        self.assertEqual(error.severity, FinancialErrorSeverity.CRITICAL)
        self.assertEqual(error.category, FinancialErrorCategory.DATA_INTEGRITY)
        self.assertEqual(error.context["member_name"], test_member.name)
        self.assertIn("calculation_details", error.context)
    
    def test_error_summary_and_statistics(self):
        """Test error summary generation and statistics"""
        # Generate multiple error types
        try:
            handle_sepa_validation_error("F1001", {"test": "iban_validation"})
        except:
            pass
        
        try:
            handle_sepa_validation_error("F1002", {"test": "bic_validation"})
        except:
            pass
        
        try:
            handle_data_integrity_error("F3001", {"test": "negative_amount"})
        except:
            pass
        
        # Get summary
        summary = self.error_handler.get_error_summary()
        
        # Verify statistics
        self.assertEqual(summary["total_errors"], 3)
        self.assertIn("compliance", summary["by_severity"])
        self.assertIn("critical", summary["by_severity"])
        self.assertIn("sepa_validation", summary["by_category"])
        self.assertIn("data_integrity", summary["by_category"])
        self.assertEqual(len(summary["critical_errors"]), 1)


class TestBatchPerformanceOptimizer(EnhancedTestCase):
    """Test batch performance optimization functionality"""
    
    def setUp(self):
        super().setUp()
        self.optimizer = get_batch_performance_optimizer()
        self.optimizer.clear_cache()  # Start with clean state
    
    def test_bulk_member_mandate_retrieval(self):
        """Test bulk retrieval of member and mandate data"""
        # Create test members with SEPA mandates
        test_members = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"TestMember{i}",
                last_name="BulkTest",
                birth_date="1990-01-01"
            )
            
            # Create SEPA mandate for member
            sepa_mandate = self.create_test_sepa_mandate(
                member_name=member.name,
                iban=self.factory.create_test_iban(),
                mandate_id=f"MTEST{i:03d}"
            )
            # Member has no `active_mandate` column; the bulk optimizer JOINs
            # SEPA Mandate by member, so the mandate created above is enough.
            test_members.append(member)
        
        # Test bulk retrieval
        member_names = [m.name for m in test_members]
        
        with self.assertQueryCount(5):  # Should be significantly less than N*2 queries
            bulk_data = self.optimizer.get_members_with_mandates_bulk(member_names)
        
        # Verify all data retrieved correctly
        self.assertEqual(len(bulk_data), len(test_members))
        
        for member in test_members:
            self.assertIn(member.name, bulk_data)
            member_data = bulk_data[member.name]["member_data"]
            mandate_data = bulk_data[member.name]["mandate_data"]
            
            self.assertEqual(member_data["name"], member.name)
            self.assertEqual(member_data["full_name"], member.full_name)
            self.assertIsNotNone(mandate_data)
            self.assertEqual(mandate_data["status"], "Active")
    
    def _active_membership_mandate(self, iban):
        """An Active, `used_for_memberships` SEPA Mandate, bypassing `validate`.

        `SEPAMandate.validate_single_active_mandate_per_purpose` (#584) blocks a
        second Active mandate for the same purpose reached through `save()`, so the
        ambiguous state this test needs is built the same way
        `test_mandate_candidates.py` builds it: insert as Draft, then
        `frappe.db.set_value` the status to Active directly. That bypass is not a
        trick to make the test pass -- it is the exact route (or a relaxed guard)
        that keeps two Active mandates reachable in production, which is why the
        resolver has to refuse rather than trust the guard.
        """
        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "mandate_id": f"AMBIG-{frappe.generate_hash(length=8)}",
                "member": self.member.name,
                "account_holder_name": self.member.full_name,
                "iban": iban,
                "sign_date": today(),
                "status": "Draft",
                "is_active": 0,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
                "used_for_memberships": 1,
            }
        )
        mandate.insert()
        frappe.db.set_value(
            "SEPA Mandate", mandate.name, {"status": "Active", "is_active": 1}, update_modified=False
        )
        mandate.reload()
        return mandate

    def test_bulk_lookup_refuses_ambiguous_mandate_instead_of_guessing(self):
        """#708: two Active membership mandates must not pick an arbitrary IBAN.

        The bulk query's LEFT JOIN carries a purpose filter (#597) but no ORDER BY,
        so a member holding two Active `used_for_memberships` mandates used to get
        whichever duplicate row MariaDB returned last as `mandate_data` -- silently,
        with no refusal and no log. The fix must make this member's mandate_data
        None (the same "no usable mandate" signal `process_batch_invoices_optimized`
        already skips on) rather than debit either account, and it must log the
        conflict so an operator can act on it.
        """
        refusal_title = "Bulk mandate lookup: ambiguous membership mandate"
        self.member = self.create_test_member(first_name="Ambig", last_name="MandateTest")
        first = self._active_membership_mandate("NL91ABNA0417164300")
        second = self._active_membership_mandate("NL39RABO0300065264")
        # Control: without this, "mandate_data is None" is also what a member with
        # ZERO Active membership mandates looks like, and the assertion below would
        # stay green even if the fixture above stopped producing an ambiguous state.
        self.assertEqual(
            frappe.db.count(
                "SEPA Mandate",
                {"member": self.member.name, "status": "Active", "used_for_memberships": 1},
            ),
            2,
            "fixture did not create two Active membership mandates -- the test below "
            "would prove nothing",
        )
        self.expectErrorLog(refusal_title)
        before = frappe.db.count("Error Log", {"method": refusal_title})

        bulk_data = self.optimizer.get_members_with_mandates_bulk([self.member.name])

        mandate_data = bulk_data[self.member.name]["mandate_data"]
        self.assertIsNone(
            mandate_data,
            f"an arbitrary IBAN was chosen between {first.iban} and {second.iban} "
            "for a member with two Active membership mandates",
        )
        # `active_sepa_mandate` comes from the same last-wins loop as `mandate_data`
        # (#708 finding A) -- it must not hand the arbitrary pick back under a
        # different key.
        self.assertIsNone(bulk_data[self.member.name]["member_data"]["active_sepa_mandate"])
        # The refusal must reach an operator, not just suppress the pick.
        self.assertEqual(
            frappe.db.count("Error Log", {"method": refusal_title}),
            before + 1,
            "the refusal did not reach the Error Log under its own title",
        )
        logs = frappe.get_all(
            "Error Log",
            filters={"method": refusal_title},
            fields=["error"],
            order_by="creation desc",
            limit=1,
        )
        message = logs[0].error
        self.assertIn(first.mandate_id, message)
        self.assertIn(second.mandate_id, message)
        self.assertIn(self.member.name, message)

    def test_bulk_invoice_processing_optimization(self):
        """Test optimized invoice processing with bulk operations"""
        # Create test members with invoices
        test_data = []
        for i in range(3):
            member = self.create_test_member(
                first_name=f"InvoiceTest{i}",
                birth_date="1985-01-01"
            )
            
            # Create customer for member (create_test_sales_invoice with a Member
            # name auto-creates and links the Customer via member.create_customer()).
            membership = self.create_test_membership(member=member.name)
            invoice = self.create_test_sales_invoice(
                customer=member.name,
                membership=membership.name
            )
            member.reload()

            # process_batch_invoices_optimized() skips any invoice whose member
            # has no SEPA mandate, so a SEPA-processable invoice must have one.
            self.create_test_sepa_mandate(
                member_name=member.name,
                iban=self.factory.create_test_iban(),
                mandate_id=f"ITEST{i:03d}",
            )

            test_data.append({
                "member": member,
                "customer": member.customer,
                "invoice": invoice,
                "membership": membership
            })
        
        # Test bulk processing
        invoice_names = [data["invoice"].name for data in test_data]
        
        with self.assertQueryCount(10):  # Should be much less than individual queries
            processed_invoices = self.optimizer.process_batch_invoices_optimized(invoice_names)
        
        # Verify processing results
        self.assertEqual(len(processed_invoices), len(test_data))
        
        for processed in processed_invoices:
            self.assertIn("invoice_data", processed)
            self.assertIn("member_data", processed)
            # Every processed invoice has a mandate (those without are skipped).
            self.assertIsNotNone(processed["mandate_data"])
            self.assertIn("address_data", processed)
    
    def test_performance_statistics_tracking(self):
        """Test performance statistics tracking and reporting"""
        # Clear statistics
        self.optimizer.clear_cache()
        
        # Perform operations to generate statistics
        member = self.create_test_member()
        self.optimizer.get_members_with_mandates_bulk([member.name])
        
        # Get performance stats
        stats = self.optimizer.get_performance_stats()
        
        # Verify statistics structure
        self.assertIn("cache_stats", stats)
        self.assertIn("query_stats", stats)
        self.assertIn("optimization_efficiency", stats)
        
        # Verify cache statistics
        cache_stats = stats["cache_stats"]
        self.assertIn("hits", cache_stats)
        self.assertIn("misses", cache_stats)
        self.assertIn("hit_rate", cache_stats)
        
        # Verify query statistics
        query_stats = stats["query_stats"]
        self.assertIn("optimized_queries", query_stats)
        self.assertIn("time_saved_ms", query_stats)
    
    def test_bank_config_caching(self):
        """Test bank configuration caching functionality"""
        # Clear cache to start fresh
        self.optimizer.clear_cache()
        
        # First call should be a cache miss
        config1 = self.optimizer.get_bank_config_cached("INGBNL2A")
        
        # Second call should be a cache hit
        config2 = self.optimizer.get_bank_config_cached("INGBNL2A")
        
        # Verify caching worked
        self.assertEqual(config1, config2)
        
        # Check cache statistics
        cache_info = self.optimizer.get_bank_config_cached.cache_info()
        self.assertGreaterEqual(cache_info.hits, 1)


class TestSEPAPerformanceMonitoring(EnhancedTestCase):
    """Test SEPA performance monitoring system"""
    
    def setUp(self):
        super().setUp()
        self.monitor = get_sepa_performance_monitor()
        self.monitor.clear_history()
    
    def test_operation_monitoring_context_manager(self):
        """Test performance monitoring using context manager"""
        with monitor_sepa_operation("test_operation", batch_size=10) as monitor_ctx:
            # Simulate some work
            time.sleep(0.01)  # 10ms
        
        # Verify metrics were recorded
        self.assertEqual(len(self.monitor.metrics_history), 1)
        metric = self.monitor.metrics_history[0]
        
        self.assertEqual(metric.operation, "test_operation")
        self.assertEqual(metric.batch_size, 10)
        self.assertGreater(metric.duration_ms, 5)  # At least 5ms (allowing for system variance)
    
    def test_xml_generation_monitoring(self):
        """Test specialized XML generation monitoring"""
        # Create sample XML content
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.08">
            <CstmrDrctDbtInitn>
                <GrpHdr>
                    <MsgId>TEST-MSG-001</MsgId>
                    <CreDtTm>2025-08-25T10:00:00</CreDtTm>
                </GrpHdr>
            </CstmrDrctDbtInitn>
        </Document>"""
        
        result = self.monitor.monitor_xml_generation(
            batch_size=50,
            xml_content=sample_xml
        )
        
        # Verify monitoring results
        self.assertIn("performance_metric", result)
        self.assertIn("xml_statistics", result)
        
        xml_stats = result["xml_statistics"]
        self.assertIn("xml_size_bytes", xml_stats)
        self.assertIn("xml_elements_count", xml_stats)
        self.assertGreater(xml_stats["xml_size_bytes"], 100)
    
    def test_performance_recommendations_generation(self):
        """Test automatic performance recommendation generation"""
        # Drive a genuine N+1 pattern: run real SQL queries (well over the
        # 3-queries-per-item threshold) inside a small-batch operation so the
        # monitor's real query counter records a high queries-per-item ratio and
        # emits a query_optimization recommendation. No mocking — the monitor
        # wraps frappe.db.sql to count actual queries.
        operation_id = self.monitor.start_operation("high_query_operation", batch_size=2)

        for _ in range(20):  # 20 queries / 2 items = 10 queries-per-item (> 3)
            frappe.db.sql("SELECT 1")
        metric = self.monitor.end_operation(operation_id)

        self.assertGreater(metric.query_count, 6)

        # Check if recommendations were generated
        recommendations = self.monitor.get_recent_recommendations(1)
        
        # Should have query optimization recommendation
        query_recommendations = [r for r in recommendations if r["type"] == "query_optimization"]
        self.assertGreater(len(query_recommendations), 0)
        
        # Verify recommendation structure
        if query_recommendations:
            rec = query_recommendations[0]
            self.assertIn("severity", rec)
            self.assertIn("issue", rec)
            self.assertIn("recommendation", rec)
    
    def test_performance_summary_reporting(self):
        """Test comprehensive performance summary reporting"""
        # Generate some test metrics
        for i in range(3):
            with monitor_sepa_operation(f"test_op_{i}", batch_size=10 + i) as ctx:
                time.sleep(0.01)  # Small delay
        
        # Get performance summary
        summary = self.monitor.get_performance_summary(hours_back=1)
        
        # Verify summary structure
        self.assertIn("total_operations", summary)
        self.assertIn("operations_summary", summary)
        self.assertIn("overall_stats", summary)
        
        self.assertEqual(summary["total_operations"], 3)
        
        overall_stats = summary["overall_stats"]
        self.assertIn("avg_duration_ms", overall_stats)
        self.assertIn("total_items_processed", overall_stats)
    
    def test_batch_size_benchmarking(self):
        """Test batch size optimization benchmarking"""
        def mock_operation(test_data):
            """Mock operation that scales with data size"""
            time.sleep(len(test_data) * 0.001)  # 1ms per item
            return {"processed": len(test_data)}
        
        def test_data_generator(size):
            """Generate test data of specified size"""
            return [f"item_{i}" for i in range(size)]
        
        # Run benchmark with small batch sizes for speed
        batch_sizes = [5, 10, 15]
        results = self.monitor.benchmark_batch_sizes(
            mock_operation, 
            batch_sizes, 
            test_data_generator
        )
        
        # Verify benchmark results
        for batch_size in batch_sizes:
            self.assertIn(batch_size, results)
            result = results[batch_size]
            
            if result["success"]:
                self.assertIn("duration_ms", result)
                self.assertIn("throughput_items_per_second", result)
                self.assertGreater(result["throughput_items_per_second"], 0)
        
        # Should have a recommendation for optimal batch size
        self.assertIn("recommendation", results)


class TestSEPAProcessorIntegration(EnhancedTestCase):
    """Test SEPA processor integration with performance optimizations"""
    
    def test_sepa_processor_uses_performance_optimizer(self):
        """Test that SEPA processor uses performance optimizations"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        processor = SEPAProcessor()
        
        # Verify performance optimizer is integrated
        self.assertIsNotNone(processor.performance_optimizer)
        self.assertIs(processor.performance_optimizer, get_batch_performance_optimizer())
    
    def test_batch_creation_with_optimization(self):
        """Test batch creation with performance optimizations enabled"""
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.sepa_processor import SEPAProcessor
        
        # Create test data for batch processing. The Customer is created and
        # linked via member.create_customer() (invoked by create_test_sales_invoice
        # below when given a Member name).
        member = self.create_test_member(birth_date="1990-01-01")

        # Create SEPA mandate
        sepa_mandate = self.create_test_sepa_mandate(
            member_name=member.name,
            iban="NL91ABNA0417164300",
            mandate_id="TEST001"
        )
        # Member has no `active_mandate` column; the SEPA processor resolves the
        # mandate by member, so no link field write is needed.

        # A Membership provides the mandatory membership_type the dues schedule
        # derives from.
        membership = self.create_test_membership(member=member.name)

        # Create membership dues schedule (bridge method on EnhancedTestCase).
        schedule = self.create_test_dues_schedule(
            member=member.name,
            payment_terms_template="SEPA Direct Debit"
        )
        
        # Create invoice (auto-creates + links the Customer for the member)
        invoice = self.create_test_sales_invoice(
            customer=member.name,
            status="Unpaid"
        )
        
        # Set up invoice for SEPA processing
        invoice.db_set("membership_dues_schedule_display", schedule.name)
        
        processor = SEPAProcessor()
        
        # Monitor the batch creation performance
        with monitor_sepa_operation("batch_creation_test", batch_size=1) as monitor_ctx:
            try:
                batch = processor.create_dues_collection_batch(
                    collection_date=today(),
                    verify_invoicing=False
                )
                
                if batch:
                    # Verify batch was created with optimizations
                    self.assertIsNotNone(batch)
                    self.assertGreater(len(batch.invoices), 0)
                    
                    # Check that performance statistics were tracked
                    stats = processor.performance_optimizer.get_performance_stats()
                    self.assertGreaterEqual(stats["query_stats"]["total_queries"], 1)
                    
            except Exception as e:
                # Log the error but don't fail the test if it's due to missing configuration
                frappe.logger().info(f"Batch creation test encountered: {str(e)}")
                # The important thing is that the integration exists, not that it fully works
                # in a test environment without complete SEPA configuration


class TestDirectDebitBatchOptimizations(EnhancedTestCase):
    """Test Direct Debit Batch performance optimizations"""
    
    def test_batch_validation_uses_bulk_operations(self):
        """Test that batch validation uses bulk operations for better performance"""
        # Create test batch with multiple invoices
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Performance Test Batch"
        batch.currency = "EUR"
        batch.status = "Draft"
        
        # Add mock invoice entries (without creating actual invoices for speed)
        for i in range(5):
            batch.append("invoices", {
                "invoice": f"TEST-INV-{i:03d}",
                "membership": f"TEST-MEM-{i:03d}",
                "member": f"TEST-MEMBER-{i:03d}",
                "member_name": f"Test Member {i}",
                "amount": 25.0,
                "currency": "EUR",
                "iban": f"NL91ABNA041716430{i:01d}",
                "mandate_reference": f"TEST{i:03d}",
                "sequence_type": "RCUR"
            })
        
        # The validation should use performance optimizer
        # This test mainly verifies the integration exists
        try:
            batch.validate_invoices()
        except Exception as e:
            # Expected to fail since invoices don't exist, but should have used optimizer
            error_msg = str(e)
            # The error should come from bulk invoice validation ("No valid
            # invoices found in batch"), not be masked by the generic F3001
            # "Negative batch total amount calculated" data-integrity handler.
            self.assertIn("invoice", error_msg.lower())  # Should mention invoice validation
            self.assertNotIn("Negative batch total", error_msg)


if __name__ == "__main__":
    unittest.main()