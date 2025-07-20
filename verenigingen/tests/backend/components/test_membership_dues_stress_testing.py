# -*- coding: utf-8 -*-
"""
Stress testing and performance tests for the membership dues system
Tests system behavior under load and with large datasets
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate, now_datetime
from verenigingen.tests.utils.base import VereningingenTestCase
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import random


class TestMembershipDuesStressTesting(VereningingenTestCase):
    """Test stress scenarios and performance limits for membership dues system"""

    def setUp(self):
        super().setUp()
        self.stress_test_prefix = f"stress_{frappe.generate_hash(length=8)}"
        
    # Performance Stress Tests
    
    def test_large_scale_member_creation_performance(self):
        """Test performance with large number of members and dues schedules"""
        membership_type = self.create_performance_membership_type()
        
        # Test parameters
        member_count = 100  # Reduced for CI environment
        batch_size = 20
        
        print(f"\n🔄 Creating {member_count} members in batches of {batch_size}")
        
        start_time = time.time()
        created_members = []
        created_schedules = []
        
        # Create members in batches
        for batch_start in range(0, member_count, batch_size):
            batch_end = min(batch_start + batch_size, member_count)
            batch_members = []
            batch_schedules = []
            
            # Create batch of members
            for i in range(batch_start, batch_end):
                member = self.create_stress_test_member(i)
                batch_members.append(member)
                
                # Create membership and dues schedule
                membership = self.create_stress_test_membership(member, membership_type)
                schedule = self.create_stress_test_dues_schedule(member, membership, membership_type, i)
                batch_schedules.append(schedule)
                
            created_members.extend(batch_members)
            created_schedules.extend(batch_schedules)
            
            batch_time = time.time() - start_time
            print(f"  ✅ Batch {batch_start//batch_size + 1}: {len(batch_members)} members created in {batch_time:.2f}s")
            
        total_time = time.time() - start_time
        avg_time_per_member = total_time / member_count
        
        print(f"📊 Performance Results:")
        print(f"  - Total time: {total_time:.2f} seconds")
        print(f"  - Average time per member: {avg_time_per_member:.3f} seconds")
        print(f"  - Members per second: {member_count/total_time:.2f}")
        
        # Verify all were created successfully
        self.assertEqual(len(created_members), member_count)
        self.assertEqual(len(created_schedules), member_count)
        
        # Performance assertions (adjust based on environment)
        self.assertLess(avg_time_per_member, 1.0, "Average creation time per member should be < 1 second")
        self.assertLess(total_time, 60.0, f"Total creation time for {member_count} members should be < 60 seconds")
        
    def test_concurrent_dues_schedule_modifications(self):
        """Test concurrent modifications to dues schedules"""
        membership_type = self.create_performance_membership_type()
        
        # Create base members for concurrent testing
        base_members = []
        for i in range(10):
            member = self.create_stress_test_member(f"concurrent_{i}")
            membership = self.create_stress_test_membership(member, membership_type)
            schedule = self.create_stress_test_dues_schedule(member, membership, membership_type, i)
            base_members.append((member, membership, schedule))
            
        # Define concurrent operations
        def modify_dues_schedule(member_data, operation_id):
            member, membership, schedule = member_data
            try:
                # Simulate concurrent modifications
                schedule.reload()
                
                if operation_id % 3 == 0:
                    # Change amount
                    new_amount = schedule.dues_rate + random.uniform(-10, 10)
                    schedule.dues_rate = max(5.0, new_amount)  # Keep above minimum
                elif operation_id % 3 == 1:
                    # Change billing frequency
                    frequencies = ["Monthly", "Quarterly", "Annual"]
                    schedule.billing_frequency = random.choice(frequencies)
                else:
                    # Add comment
                    schedule.add_comment(text=f"Concurrent modification {operation_id} at {now_datetime()}")
                    
                schedule.save()
                return f"Success: Operation {operation_id} completed"
                
            except Exception as e:
                return f"Error: Operation {operation_id} failed: {str(e)}"
                
        # Execute concurrent operations
        print(f"\n🔄 Testing concurrent modifications with {len(base_members)} schedules")
        
        start_time = time.time()
        results = []
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Submit multiple operations per schedule
            futures = []
            for i, member_data in enumerate(base_members):
                for j in range(3):  # 3 operations per schedule
                    future = executor.submit(modify_dues_schedule, member_data, i * 3 + j)
                    futures.append(future)
                    
            # Collect results
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                
        end_time = time.time()
        
        # Analyze results
        successful_operations = [r for r in results if r.startswith("Success")]
        failed_operations = [r for r in results if r.startswith("Error")]
        
        print(f"📊 Concurrent Operations Results:")
        print(f"  - Total operations: {len(results)}")
        print(f"  - Successful: {len(successful_operations)}")
        print(f"  - Failed: {len(failed_operations)}")
        print(f"  - Execution time: {end_time - start_time:.2f} seconds")
        
        if failed_operations:
            print(f"  - Sample failures: {failed_operations[:3]}")
            
        # Should handle concurrent operations gracefully
        # Some failures are acceptable due to race conditions
        success_rate = len(successful_operations) / len(results)
        self.assertGreater(success_rate, 0.7, "At least 70% of concurrent operations should succeed")
        
    def test_bulk_api_operations_performance(self):
        """Test performance of bulk API operations"""
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application
        from verenigingen.api.payment_plan_management import calculate_payment_plan_preview
        
        # Create multiple membership types for testing
        membership_types = []
        for i in range(10):
            mt = self.create_performance_membership_type(f"bulk_api_{i}")
            
            # Add varied tiers
            for j in range(5):
                tier = mt.append("predefined_tiers", {})
                tier.tier_name = f"Tier_{j}"
                tier.display_name = f"Tier {j+1}"
                tier.amount = 10.0 + (j * 10.0)
                tier.display_order = j + 1
                tier.description = f"Tier {j+1} description"
                
            mt.save()
            membership_types.append(mt)
            
        print(f"\n🔄 Testing bulk API operations with {len(membership_types)} membership types")
        
        # Test get_membership_types_for_application performance
        start_time = time.time()
        
        api_call_results = []
        for i in range(50):  # 50 API calls
            try:
                types = get_membership_types_for_application()
                api_call_results.append(len(types))
            except Exception as e:
                print(f"API call {i} failed: {e}")
                api_call_results.append(0)
                
        api_time = time.time() - start_time
        avg_api_time = api_time / 50
        
        print(f"📊 API Performance Results:")
        print(f"  - Total API calls: 50")
        print(f"  - Total time: {api_time:.2f} seconds")
        print(f"  - Average time per call: {avg_api_time:.3f} seconds")
        print(f"  - Calls per second: {50/api_time:.2f}")
        print(f"  - Average types returned: {sum(api_call_results)/len(api_call_results):.1f}")
        
        # Test payment plan preview calculations
        start_time = time.time()
        
        preview_results = []
        test_amounts = [50, 100, 150, 200, 250, 300, 400, 500]
        installment_counts = [2, 3, 4, 6, 12]
        frequencies = ["Monthly", "Quarterly"]
        
        for amount in test_amounts:
            for installments in installment_counts:
                for frequency in frequencies:
                    try:
                        preview = calculate_payment_plan_preview(amount, installments, frequency)
                        preview_results.append(preview.get("success", False))
                    except Exception as e:
                        preview_results.append(False)
                        
        preview_time = time.time() - start_time
        successful_previews = sum(preview_results)
        
        print(f"  - Payment plan previews: {len(preview_results)} calculated in {preview_time:.2f}s")
        print(f"  - Successful previews: {successful_previews}/{len(preview_results)}")
        
        # Performance assertions
        self.assertLess(avg_api_time, 0.5, "API calls should average < 0.5 seconds")
        self.assertGreater(successful_previews / len(preview_results), 0.9, "90%+ payment plan previews should succeed")
        
    def test_memory_usage_with_large_datasets(self):
        """Test memory efficiency with large datasets"""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        print(f"\n🔄 Testing memory usage (Initial: {initial_memory:.1f} MB)")
        
        membership_type = self.create_performance_membership_type()
        
        # Create large dataset
        large_dataset = []
        batch_size = 50
        total_records = 200
        
        for batch in range(0, total_records, batch_size):
            batch_data = []
            
            for i in range(batch, min(batch + batch_size, total_records)):
                member = self.create_stress_test_member(f"memory_{i}")
                membership = self.create_stress_test_membership(member, membership_type)
                schedule = self.create_stress_test_dues_schedule(member, membership, membership_type, i)
                
                batch_data.append({
                    "member": member,
                    "membership": membership,
                    "schedule": schedule
                })
                
            large_dataset.extend(batch_data)
            
            # Check memory after each batch
            current_memory = process.memory_info().rss / 1024 / 1024
            memory_increase = current_memory - initial_memory
            
            if batch % 100 == 0:  # Report every 100 records
                print(f"  - {len(large_dataset)} records: {current_memory:.1f} MB (+{memory_increase:.1f} MB)")
                
        final_memory = process.memory_info().rss / 1024 / 1024
        total_memory_increase = final_memory - initial_memory
        memory_per_record = total_memory_increase / len(large_dataset)
        
        print(f"📊 Memory Usage Results:")
        print(f"  - Initial memory: {initial_memory:.1f} MB")
        print(f"  - Final memory: {final_memory:.1f} MB")
        print(f"  - Total increase: {total_memory_increase:.1f} MB")
        print(f"  - Memory per record: {memory_per_record:.3f} MB")
        print(f"  - Records created: {len(large_dataset)}")
        
        # Memory efficiency assertions
        self.assertLess(memory_per_record, 0.5, "Memory usage should be < 0.5 MB per record")
        self.assertLess(total_memory_increase, 100, "Total memory increase should be < 100 MB for test dataset")
        
    def test_database_query_optimization(self):
        """Test database query performance and optimization"""
        membership_type = self.create_performance_membership_type()
        
        # Create test data
        members = []
        schedules = []
        
        print(f"\n🔄 Creating test data for query optimization testing")
        
        for i in range(50):
            member = self.create_stress_test_member(f"query_{i}")
            membership = self.create_stress_test_membership(member, membership_type)
            schedule = self.create_stress_test_dues_schedule(member, membership, membership_type, i)
            
            members.append(member)
            schedules.append(schedule)
            
        print(f"  - Created {len(members)} members and {len(schedules)} schedules")
        
        # Test various query patterns
        query_tests = [
            {
                "name": "Get all active dues schedules",
                "query": lambda: frappe.get_all("Membership Dues Schedule", 
                                               filters={"status": "Active"}, 
                                               fields=["name", "member", "dues_rate", "billing_frequency"])
            },
            {
                "name": "Get dues schedules by member",
                "query": lambda: [frappe.get_all("Membership Dues Schedule", 
                                                filters={"member": member.name}, 
                                                fields=["name", "dues_rate", "status"]) 
                                for member in members[:10]]  # Test first 10
            },
            {
                "name": "Get membership types with contribution options",
                "query": lambda: [frappe.get_doc("Membership Type", membership_type.name).get_contribution_options() 
                                for _ in range(20)]  # Multiple calls
            },
            {
                "name": "Count schedules by status",
                "query": lambda: frappe.db.sql("""
                    SELECT status, COUNT(*) as count 
                    FROM `tabMembership Dues Schedule` 
                    WHERE creation >= %s 
                    GROUP BY status
                """, (today(),), as_dict=True)
            },
            {
                "name": "Get member details with schedules",
                "query": lambda: frappe.db.sql("""
                    SELECT m.name, m.first_name, m.last_name, m.email,
                           mds.amount, mds.billing_frequency, mds.status
                    FROM `tabMember` m
                    LEFT JOIN `tabMembership Dues Schedule` mds ON mds.member = m.name
                    WHERE m.creation >= %s
                    LIMIT 50
                """, (today(),), as_dict=True)
            }
        ]
        
        print(f"📊 Query Performance Results:")
        
        for test in query_tests:
            start_time = time.time()
            
            try:
                result = test["query"]()
                end_time = time.time()
                query_time = end_time - start_time
                
                if isinstance(result, list):
                    result_count = len(result)
                else:
                    result_count = 1
                    
                print(f"  - {test['name']}: {query_time:.3f}s ({result_count} results)")
                
                # Performance assertion - queries should be fast
                self.assertLess(query_time, 2.0, f"Query '{test['name']}' should complete in < 2 seconds")
                
            except Exception as e:
                print(f"  - {test['name']}: FAILED - {str(e)}")
                self.fail(f"Query test '{test['name']}' failed: {str(e)}")
                
    def test_sepa_processor_scalability(self):
        """Test SEPA processor performance with many dues schedules"""
        from verenigingen.verenigingen.doctype.direct_debit_batch.enhanced_sepa_processor import EnhancedSEPAProcessor
        
        membership_type = self.create_performance_membership_type()
        
        # Create members with SEPA-enabled dues schedules
        sepa_schedules = []
        
        print(f"\n🔄 Creating SEPA dues schedules for processor testing")
        
        for i in range(30):
            member = self.create_stress_test_member(f"sepa_{i}")
            membership = self.create_stress_test_membership(member, membership_type)
            
            # Create dues schedule with SEPA payment method
            schedule = frappe.new_doc("Membership Dues Schedule")
            schedule.member = member.name
            schedule.membership = membership.name
            schedule.membership_type = membership_type.name
            schedule.contribution_mode = "Calculator"
            schedule.dues_rate = 25.0 + (i * 2.0)  # Varied amounts
            schedule.billing_frequency = "Monthly"
            schedule.payment_method = "SEPA Direct Debit"
            schedule.status = "Active"
            schedule.next_invoice_date = today()  # Due for collection
            schedule.auto_generate = 0
            schedule.save()
            self.track_doc("Membership Dues Schedule", schedule.name)
            sepa_schedules.append(schedule)
            
        print(f"  - Created {len(sepa_schedules)} SEPA-enabled schedules")
        
        # Test SEPA processor performance
        processor = EnhancedSEPAProcessor()
        
        # Test eligibility detection
        start_time = time.time()
        eligible_schedules = processor.get_eligible_dues_schedules(today())
        eligibility_time = time.time() - start_time
        
        print(f"📊 SEPA Processor Performance:")
        print(f"  - Eligibility check: {eligibility_time:.3f}s ({len(eligible_schedules)} eligible)")
        
        # Test batch creation if we have eligible schedules
        if eligible_schedules:
            start_time = time.time()
            
            try:
                # Create a small test batch
                test_batch = processor.create_dues_collection_batch(
                    collection_date=today(),
                    description="Performance test batch",
                    test_mode=True
                )
                batch_creation_time = time.time() - start_time
                
                print(f"  - Batch creation: {batch_creation_time:.3f}s")
                
                if test_batch:
                    self.track_doc("Direct Debit Batch", test_batch.name)
                    
            except Exception as e:
                print(f"  - Batch creation: FAILED - {str(e)}")
                
        # Performance assertions
        self.assertLess(eligibility_time, 1.0, "Eligibility check should complete in < 1 second")
        self.assertGreaterEqual(len(eligible_schedules), 1, "Should find at least some eligible schedules")
        
    # Stress Test Helper Methods
    
    def create_stress_test_member(self, identifier):
        """Create a member for stress testing"""
        member = frappe.new_doc("Member")
        member.first_name = f"Stress{identifier}"
        member.last_name = f"Test{self.stress_test_prefix}"
        member.email = f"stress.{identifier}.{self.stress_test_prefix}@example.com"
        member.member_since = add_days(today(), -random.randint(1, 365))
        member.address_line1 = f"{identifier} Stress Street"
        member.postal_code = f"{hash(str(identifier)) % 9000 + 1000:04d}AB"
        member.city = "Stress City"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        return member
        
    def create_stress_test_membership(self, member, membership_type):
        """Create a membership for stress testing"""
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = member.member_since
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        return membership
        
    def create_stress_test_dues_schedule(self, member, membership, membership_type, identifier):
        """Create a dues schedule for stress testing"""
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.member = member.name
        dues_schedule.membership = membership.name
        dues_schedule.membership_type = membership_type.name
        dues_schedule.contribution_mode = "Calculator"
        
        # Vary amounts and frequencies for realistic testing
        base_amount = membership_type.suggested_contribution
        multiplier = 0.5 + (identifier % 10) * 0.1  # 0.5 to 1.4
        dues_schedule.dues_rate = base_amount * multiplier
        
        frequencies = ["Monthly", "Quarterly", "Annual"]
        dues_schedule.billing_frequency = frequencies[identifier % 3]
        
        payment_methods = ["Bank Transfer", "SEPA Direct Debit"]
        dues_schedule.payment_method = payment_methods[identifier % 2]
        
        dues_schedule.status = "Active"
        dues_schedule.auto_generate = 0  # Test mode
        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule
        
    def create_performance_membership_type(self, suffix=""):
        """Create a membership type optimized for performance testing"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Performance Test {suffix} {self.stress_test_prefix}"
        membership_type.description = f"Performance testing membership type {suffix}"
        membership_type.amount = 50.0
        membership_type.billing_frequency = "Monthly"
        membership_type.is_active = 1
        membership_type.contribution_mode = "Calculator"
        membership_type.minimum_contribution = 10.0
        membership_type.suggested_contribution = 50.0
        membership_type.maximum_contribution = 500.0
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.75
        membership_type.allow_custom_amounts = 1
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type