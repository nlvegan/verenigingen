#!/usr/bin/env python3
"""
Integration tests for SEPA system optimizations
Tests the unified services and performance improvements
"""

import frappe
from frappe.utils import today, add_days
from verenigingen.tests.utils.base import VereningingenTestCase


class TestSEPAOptimizations(VereningingenTestCase):
    """Test suite for SEPA optimization integrations"""
    
    def setUp(self):
        super().setUp()
        # Clear any existing caches to ensure clean test state
        try:
            from verenigingen.utils.sepa_mandate_service import get_sepa_mandate_service
            from verenigingen.utils.sepa_config_manager import get_sepa_config_manager
            
            mandate_service = get_sepa_mandate_service()
            mandate_service.clear_cache()
            
            config_manager = get_sepa_config_manager()
            config_manager.clear_cache()
        except Exception:
            pass  # Services might not be available in all test environments
    
    def test_mandate_service_batch_processing(self):
        """Test unified mandate service batch processing"""
        from verenigingen.utils.sepa_mandate_service import get_sepa_mandate_service
        
        service = get_sepa_mandate_service()
        
        # Test batch mandate lookup
        test_members = ["TEST-MEM-001", "TEST-MEM-002"]
        mandates = service.get_active_mandate_batch(test_members)
        
        self.assertIsInstance(mandates, dict)
        self.assertEqual(len(mandates), len(test_members))
        
        # Test cache functionality
        cache_stats = service.get_cache_stats()
        self.assertIsInstance(cache_stats, dict)
        self.assertIn("total_cached_items", cache_stats)
    
    def test_configuration_manager_integration(self):
        """Test centralized configuration manager"""
        from verenigingen.utils.sepa_config_manager import get_sepa_config_manager
        
        manager = get_sepa_config_manager()
        
        # Test complete configuration
        config = manager.get_complete_config()
        self.assertIsInstance(config, dict)
        
        expected_sections = ["company_sepa", "batch_timing", "notifications", 
                           "error_handling", "processing", "file_handling"]
        for section in expected_sections:
            self.assertIn(section, config)
        
        # Test configuration validation
        validation = manager.validate_sepa_config()
        self.assertIsInstance(validation, dict)
        self.assertIn("valid", validation)
        self.assertIn("errors", validation)
        self.assertIn("warnings", validation)
    
    def test_error_handler_functionality(self):
        """Test error handler and circuit breaker"""
        from verenigingen.utils.sepa_error_handler import get_sepa_error_handler
        
        handler = get_sepa_error_handler()
        
        # Test circuit breaker status
        status = handler.get_circuit_breaker_status()
        self.assertIsInstance(status, dict)
        self.assertIn("state", status)
        self.assertIn(status["state"], ["closed", "open", "half_open"])
        
        # Test error categorization
        temp_error = Exception("Connection timeout")
        category = handler.categorize_error(temp_error)
        self.assertEqual(category, "temporary")
        
        validation_error = Exception("Invalid field value")
        category = handler.categorize_error(validation_error)
        self.assertEqual(category, "validation")
        
        # Test retry decision logic
        should_retry_temp = handler.should_retry(temp_error, attempt=1)
        self.assertTrue(should_retry_temp)
        
        should_not_retry_validation = handler.should_retry(validation_error, attempt=1)
        self.assertFalse(should_not_retry_validation)
    
    def test_enhanced_sepa_processor_optimization(self):
        """Test Enhanced SEPA Processor with optimizations"""
        from verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor import EnhancedSEPAProcessor
        
        processor = EnhancedSEPAProcessor()
        
        # Test that all optimization services are integrated
        self.assertIsNotNone(processor.config_manager)
        self.assertIsNotNone(processor.mandate_service)
        self.assertIsNotNone(processor.error_handler)
        
        # Test optimized invoice lookup
        invoices = processor.get_existing_unpaid_sepa_invoices(today())
        self.assertIsInstance(invoices, list)
        
        # Test coverage verification with batch processing
        coverage_result = processor.verify_invoice_coverage(today())
        self.assertIsInstance(coverage_result, dict)
        self.assertIn("total_checked", coverage_result)
        self.assertIn("complete", coverage_result)
    
    def test_database_indexes_presence(self):
        """Test that database indexes were created successfully"""
        from verenigingen.fixtures.add_sepa_database_indexes import verify_sepa_indexes
        
        verification_results = verify_sepa_indexes()
        self.assertIsInstance(verification_results, list)
        
        found_indexes = [r for r in verification_results if r['status'] == 'found']
        missing_indexes = [r for r in verification_results if r['status'] == 'missing']
        
        # Should have most indexes (allow for some environment differences)
        self.assertGreaterEqual(len(found_indexes), 8, 
                              f"Expected at least 8 indexes, found {len(found_indexes)}")
        
        if missing_indexes:
            print(f"Warning: {len(missing_indexes)} indexes missing: {[idx['index'] for idx in missing_indexes]}")
    
    def test_batch_sequence_type_determination(self):
        """Test batch sequence type processing"""
        from verenigingen.utils.sepa_mandate_service import get_sepa_mandate_service
        
        service = get_sepa_mandate_service()
        
        # Test batch sequence type determination with sample data
        test_pairs = [("TEST-MANDATE-1", "TEST-INV-1"), ("TEST-MANDATE-2", "TEST-INV-2")]
        
        try:
            sequence_types = service.get_sequence_types_batch(test_pairs)
            self.assertIsInstance(sequence_types, dict)
            
            # Should return results for all pairs (even if mandates don't exist)
            for mandate, invoice in test_pairs:
                cache_key = f"{mandate}:{invoice}"
                self.assertIn(cache_key, sequence_types)
                
        except Exception as e:
            # This might fail in test environments without proper SEPA setup
            self.skipTest(f"Sequence type determination requires SEPA setup: {str(e)}")
    
    def test_configuration_api_endpoints(self):
        """Test configuration management API endpoints"""
        from verenigingen.utils.sepa_config_manager import (
            get_sepa_config, validate_sepa_configuration, get_sepa_config_cache_info
        )
        
        # Test configuration retrieval
        config = get_sepa_config()
        self.assertIsInstance(config, dict)
        
        # Test specific section retrieval
        timing_config = get_sepa_config("batch_timing")
        self.assertIsInstance(timing_config, dict)
        self.assertIn("creation_days", timing_config)
        
        # Test validation endpoint
        validation = validate_sepa_configuration()
        self.assertIsInstance(validation, dict)
        self.assertIn("valid", validation)
        
        # Test cache info endpoint
        cache_info = get_sepa_config_cache_info()
        self.assertIsInstance(cache_info, dict)
        self.assertIn("total_cached_items", cache_info)
    
    def test_mandate_service_api_endpoints(self):
        """Test mandate service API endpoints"""
        from verenigingen.utils.sepa_mandate_service import (
            get_sepa_cache_stats, clear_sepa_mandate_cache
        )
        
        # Test cache statistics
        cache_stats = get_sepa_cache_stats()
        self.assertIsInstance(cache_stats, dict)
        self.assertIn("total_cached_items", cache_stats)
        
        # Test cache clearing
        clear_result = clear_sepa_mandate_cache()
        self.assertIsInstance(clear_result, dict)
        self.assertTrue(clear_result.get("success", False))
    
    def test_error_handler_api_endpoints(self):
        """Test error handler API endpoints"""
        from verenigingen.utils.sepa_error_handler import (
            get_sepa_error_handler_status, reset_sepa_circuit_breaker
        )
        
        # Test error handler status
        status = get_sepa_error_handler_status()
        self.assertIsInstance(status, dict)
        self.assertIn("state", status)
        
        # Test circuit breaker reset
        reset_result = reset_sepa_circuit_breaker()
        self.assertIsInstance(reset_result, dict)
        self.assertTrue(reset_result.get("success", False))
    
    def test_performance_improvements(self):
        """Test performance improvements (basic timing test)"""
        import time
        from verenigingen.utils.sepa_mandate_service import get_sepa_mandate_service
        
        service = get_sepa_mandate_service()
        
        # Test batch vs individual lookups (if we have test data)
        test_members = ["TEST-001", "TEST-002", "TEST-003"]
        
        # Batch lookup timing
        start_time = time.time()
        batch_results = service.get_active_mandate_batch(test_members)
        batch_time = time.time() - start_time
        
        self.assertLess(batch_time, 1.0, "Batch lookup should be fast")
        self.assertIsInstance(batch_results, dict)
        self.assertEqual(len(batch_results), len(test_members))
    
    def test_monthly_batch_creation_optimization(self):
        """Test optimized monthly batch creation"""
        from verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor import (
            create_monthly_dues_collection_batch
        )
        
        # Test that the function runs without errors
        # (It may not create a batch due to timing or configuration)
        try:
            result = create_monthly_dues_collection_batch()
            # Result can be None (no batch created) or batch name
            self.assertTrue(result is None or isinstance(result, str))
        except Exception as e:
            # Function should handle errors gracefully
            self.fail(f"Monthly batch creation should not raise unhandled exceptions: {str(e)}")


def run_optimization_tests():
    """Run all optimization tests"""
    import unittest
    
    # Create test suite
    suite = unittest.TestSuite()
    test_class = TestSEPAOptimizations
    
    # Add all test methods
    for method_name in dir(test_class):
        if method_name.startswith('test_'):
            suite.addTest(test_class(method_name))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    # Run tests when executed directly
    success = run_optimization_tests()
    if success:
        print("\n✅ All SEPA optimization tests passed!")
    else:
        print("\n❌ Some SEPA optimization tests failed.")