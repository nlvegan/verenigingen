#!/usr/bin/env python3
"""
Small Scale Payment History Test
===============================

Test payment history performance with a small, manageable dataset to validate
the test infrastructure and measure baseline performance.
"""

import time
from datetime import datetime

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.scalability.payment_history_test_factory import PaymentHistoryTestFactory


class TestSmallScalePaymentHistory(VereningingenTestCase):
    """Test payment history at small scale for validation"""
    
    def setUp(self):
        """Set up test environment"""
        super().setUp()
        self.factory = PaymentHistoryTestFactory(cleanup_on_exit=False, seed=42)
        self.test_start_time = time.time()
        
    def tearDown(self):
        """Clean up test data"""
        try:
            self.factory.cleanup()
        except Exception as e:
            print(f"Warning: Cleanup error: {e}")
        super().tearDown()
    
    def test_payment_history_creation_50_members(self):
        """Test creating payment history for 50 members"""
        print("\n🧪 Testing payment history creation with 50 members")
        
        start_time = time.time()
        
        # Create small batch
        batch_result = self.factory.create_payment_history_batch(
            member_count=50,
            months_history=3,
            avg_payments_per_month=1.0
        )
        
        creation_time = time.time() - start_time
        
        # Validate results
        self.assertEqual(len(batch_result["members"]), 50)
        self.assertGreater(len(batch_result["invoices"]), 100)  # Should have 150+ invoices
        self.assertGreater(len(batch_result["payments"]), 90)   # 90% success rate
        
        # Performance metrics
        total_records = batch_result["metrics"]["total_records"]
        records_per_second = total_records / creation_time if creation_time > 0 else 0
        
        print(f"✅ Created {total_records} records in {creation_time:.2f}s")
        print(f"📊 Rate: {records_per_second:.1f} records/second")
        
        # Performance assertions (lenient for initial validation)
        self.assertLess(creation_time, 60, "Should complete within 1 minute")
        self.assertGreater(records_per_second, 10, "Should maintain reasonable throughput")
        
        return {
            "member_count": 50,
            "total_records": total_records,
            "creation_time": creation_time,
            "records_per_second": records_per_second
        }
    
    def test_payment_history_creation_100_members(self):
        """Test creating payment history for 100 members"""
        print("\n🧪 Testing payment history creation with 100 members")
        
        start_time = time.time()
        
        # Create medium-small batch
        batch_result = self.factory.create_payment_history_batch(
            member_count=100,
            months_history=3,
            avg_payments_per_month=1.2
        )
        
        creation_time = time.time() - start_time
        
        # Validate results
        self.assertEqual(len(batch_result["members"]), 100)
        self.assertGreater(len(batch_result["invoices"]), 200)  # Should have 360+ invoices
        self.assertGreater(len(batch_result["payments"]), 180)  # 90% success rate
        
        # Performance metrics
        total_records = batch_result["metrics"]["total_records"]
        records_per_second = total_records / creation_time if creation_time > 0 else 0
        
        print(f"✅ Created {total_records} records in {creation_time:.2f}s")
        print(f"📊 Rate: {records_per_second:.1f} records/second")
        
        # Performance assertions
        self.assertLess(creation_time, 120, "Should complete within 2 minutes")
        self.assertGreater(records_per_second, 5, "Should maintain reasonable throughput")
        
        return {
            "member_count": 100,
            "total_records": total_records,
            "creation_time": creation_time,
            "records_per_second": records_per_second
        }
    
    def test_payment_history_update_performance(self):
        """Test payment history update performance"""
        print("\n🧪 Testing payment history update performance")
        
        # Create a small batch first
        batch_result = self.factory.create_payment_history_batch(
            member_count=25,
            months_history=2,
            avg_payments_per_month=1.0
        )
        
        # Test payment history updates
        update_start = time.time()
        update_times = []
        
        for member in batch_result["members"]:
            member_start = time.time()
            
            # Update payment history for this member
            member_doc = frappe.get_doc("Member", member.name)
            member_doc.load_payment_history()
            member_doc.save(ignore_permissions=True)
            
            member_time = time.time() - member_start
            update_times.append(member_time)
        
        total_update_time = time.time() - update_start
        avg_update_time = sum(update_times) / len(update_times) if update_times else 0
        
        print(f"✅ Updated {len(batch_result['members'])} members in {total_update_time:.2f}s")
        print(f"📊 Average update time: {avg_update_time:.3f}s per member")
        print(f"📊 Update rate: {len(update_times) / total_update_time:.1f} members/second")
        
        # Performance assertions
        self.assertLess(avg_update_time, 2.0, "Average update should be under 2 seconds")
        self.assertLess(max(update_times), 5.0, "No single update should take more than 5 seconds")
        
        return {
            "member_count": len(batch_result["members"]),
            "total_update_time": total_update_time,
            "avg_update_time": avg_update_time,
            "max_update_time": max(update_times) if update_times else 0
        }
    
    def test_infrastructure_validation(self):
        """Validate test infrastructure is working correctly"""
        print("\n🔧 Validating test infrastructure")
        
        # Test basic factory functionality
        member = self.factory.create_test_member(
            first_name="Infrastructure",
            last_name="Test",
            email="infra.test@example.com"
        )
        
        self.assertIsNotNone(member)
        self.assertEqual(member.first_name, "Infrastructure")
        
        # Test SEPA mandate creation
        mandate = self.factory.create_test_sepa_mandate(
            member=member.name,
            scenario="normal"
        )
        
        self.assertIsNotNone(mandate)
        self.assertEqual(mandate.member, member.name)
        
        # Test invoice creation (using the factory's internal method)
        invoice = self.factory._create_test_invoice(member, frappe.utils.today())
        
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.customer, member.customer)
        
        print("✅ Infrastructure validation completed successfully")
        
        return {
            "member_created": True,
            "mandate_created": True,
            "invoice_created": True,
            "infrastructure_valid": True
        }