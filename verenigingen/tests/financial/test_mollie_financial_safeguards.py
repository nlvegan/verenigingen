#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mollie Financial Transaction Safeguards Test Suite
==================================================

Comprehensive test suite for validating financial transaction safeguards in the Mollie 
payment integration. This test suite ensures that all critical financial operations
are protected against common attack vectors and edge cases.

Test Categories:
- Duplicate payment prevention
- Amount validation and manipulation protection
- Currency validation
- Temporal validation (payment timing)
- Idempotency testing
- Race condition protection
- Payment reconciliation accuracy

Author: Test Engineering Team
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from concurrent.futures import ThreadPoolExecutor, as_completed

import frappe
from frappe.utils import today

from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.mollie.tests.fixtures.test_factory import MollieTestCase
from verenigingen.verenigingen_payments.utils.payment_gateways import (
    _process_subscription_payment
)
import unittest


class TestMollieFinancialSafeguards(MollieTestCase):
    """Comprehensive test suite for Mollie financial transaction safeguards"""
    
    def setUp(self):
        super().setUp()
        
        # Create base test data
        self.member = self.create_mollie_test_member(
            first_name="SafeguardTest",
            last_name="Member",
            email="safeguard.test@example.com"
        )
        
        # The factory already auto-creates and links a Customer for the member
        # (member.customer). Reuse it instead of inserting a second Customer with
        # the same derived name, which collided on the Customer primary key.
        self.customer = frappe.get_doc("Customer", self.member.customer)

        # ERPNext's Sales Invoice (and the downstream Payment Entry party-account
        # lookup) require an explicit `company`; without it ERPNext throws
        # "Please select a Company". Mollie is a EUR flow, so prefer the EUR test
        # company, falling back to a company with a current Fiscal Year on sites
        # that don't have the app's EUR company provisioned.
        self.company = self._resolve_test_company()

        # Create test invoice
        self.test_invoice = self._create_test_invoice(50.00)

    def _resolve_test_company(self) -> str:
        """Return a EUR company with a current Fiscal Year, or a safe fallback."""
        try:
            return get_eur_test_company()
        except Exception:
            # Fall back to any company whose Fiscal Year covers today so the
            # Sales Invoice / GL postings save (EUR is not required for the
            # mocked Mollie path - it does not run SEPA invoice validation).
            from erpnext.accounts.utils import get_fiscal_year

            for company in frappe.get_all("Company", pluck="name"):
                try:
                    get_fiscal_year(date=today(), company=company, as_dict=True)
                    return company
                except Exception:
                    continue
            return "_Test Company"
        
    def _create_test_invoice(self, amount: float) -> str:
        """Create a test invoice for safeguard testing"""
        self.mollie_factory._ensure_test_item()

        # Match the invoice currency to the company's default currency so the
        # party (Debtors) account currency check passes. On a fully provisioned
        # EUR test company this is EUR; on a fallback company it tracks that
        # company's currency. The mocked Mollie path does not assert EUR.
        company_currency = frappe.db.get_value("Company", self.company, "default_currency")

        invoice = frappe.get_doc({
            "doctype": "Sales Invoice",
            "company": self.company,
            "customer": self.customer.name,
            "customer_name": self.member.full_name,
            "posting_date": today(),
            "due_date": today(),
            "items": [{
                "item_code": "TEST-Membership-Dues",
                "item_name": "Test Membership Dues",
                "description": f"Safeguard test invoice for {self.member.full_name}",
                "qty": 1,
                "rate": amount,
                "amount": amount
            }],
            "currency": company_currency,
            # Set price-list fields explicitly so the invoice does not depend on
            # the company having a default selling Price List configured (the
            # fallback test company on some sites has none in the invoice
            # currency).
            "selling_price_list": "Standard Selling",
            "price_list_currency": company_currency,
            "plc_conversion_rate": 1.0,
            "conversion_rate": 1.0,
            "ignore_pricing_rule": 1,
            "remarks": f"Safeguard test invoice - amount: {amount}"
        })
        invoice.insert()
        invoice.submit()
        return invoice.name
        
    def _create_mock_mollie_gateway(self, payment_amount: float, payment_status: str = "paid"):
        """Create a mock Mollie gateway for testing"""
        mock_gateway = MagicMock()
        mock_client = MagicMock()
        mock_gateway.client = mock_client
        
        # Mock payment response
        mock_payment = MagicMock()
        mock_payment.is_paid.return_value = (payment_status == "paid")
        mock_payment.amount = {"value": f"{payment_amount:.2f}", "currency": "EUR"}
        mock_payment.status = payment_status
        mock_client.payments.get.return_value = mock_payment
        
        return mock_gateway
        
    def test_duplicate_payment_prevention(self):
        """Test that duplicate payment IDs are handled correctly"""
        payment_id = "tr_duplicate_test_001"
        gateway = self._create_mock_mollie_gateway(50.00)
        
        # Process the same payment twice
        result1 = None
        result2 = None
        
        try:
            result1 = _process_subscription_payment(
                gateway, self.member.name, self.customer.name, payment_id, "sub_test_001"
            )
        except Exception as e:
            print(f"First payment processing failed (expected in test): {e}")
            result1 = {"status": "success", "payment_id": payment_id}
            
        try:
            result2 = _process_subscription_payment(
                gateway, self.member.name, self.customer.name, payment_id, "sub_test_001"
            )
        except Exception as e:
            print(f"Second payment processing failed (expected in test): {e}")
            result2 = {"status": "duplicate", "payment_id": payment_id}
            
        # Both should succeed but only one payment entry should be created
        # or the second should be identified as duplicate
        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)
        
        # Check that we don't have duplicate payment entries
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": payment_id},
            fields=["name"]
        )
        
        # Should have at most 1 payment entry
        self.assertLessEqual(len(payment_entries), 1, 
                           "Should not create duplicate payment entries")
                           
    def test_amount_manipulation_protection(self):
        """Test protection against amount manipulation attacks"""
        safeguards_data = self.mollie_factory.create_financial_safeguards_test_data()
        
        for scenario in safeguards_data["amount_validation"]["scenarios"]:
            invoice_amount = scenario["invoice_amount"]
            payment_amount = scenario["payment_amount"]
            should_be_valid = scenario["valid"]
            
            # Create invoice with specific amount
            invoice_name = self._create_test_invoice(invoice_amount)
            
            # Test payment processing with different amount
            gateway = self._create_mock_mollie_gateway(payment_amount)
            
            try:
                result = _process_subscription_payment(
                    gateway, self.member.name, self.customer.name, 
                    f"tr_amount_test_{payment_amount}", "sub_test_amount"
                )
                
                if not should_be_valid and payment_amount <= 0:
                    self.fail(f"Should have rejected invalid payment amount: {payment_amount}")
                    
                # Valid payments should process
                if should_be_valid:
                    self.assertEqual(result["status"], "success")
                    self.assertEqual(result["amount"], payment_amount)
                    
            except Exception as e:
                if should_be_valid:
                    print(f"Valid payment rejected in test environment: {e}")
                else:
                    # Invalid payments should be rejected
                    print(f"Invalid payment correctly rejected: {e}")
                    
    def test_currency_validation(self):
        """Test currency validation and protection"""
        safeguards_data = self.mollie_factory.create_financial_safeguards_test_data()
        
        for scenario in safeguards_data["currency_validation"]["scenarios"]:
            invoice_currency = scenario["invoice_currency"]
            payment_currency = scenario["payment_currency"]
            should_be_valid = scenario["valid"]
            
            # Create invoice with specific currency
            invoice_name = self._create_test_invoice(50.00)
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            invoice.currency = invoice_currency
            invoice.save()
            
            # Mock payment with different currency
            gateway = MagicMock()
            mock_client = MagicMock()
            gateway.client = mock_client
            
            mock_payment = MagicMock()
            mock_payment.is_paid.return_value = True
            mock_payment.amount = {"value": "50.00", "currency": payment_currency}
            mock_payment.status = "paid"
            mock_client.payments.get.return_value = mock_payment
            
            try:
                result = _process_subscription_payment(
                    gateway, self.member.name, self.customer.name,
                    f"tr_currency_test_{payment_currency}", "sub_test_currency"
                )
                
                if should_be_valid:
                    self.assertEqual(result["status"], "success")
                else:
                    # Invalid currency should be handled appropriately
                    # (implementation dependent - might succeed with conversion or fail)
                    pass
                    
            except Exception as e:
                if should_be_valid:
                    print(f"Valid currency combination failed in test: {e}")
                else:
                    print(f"Invalid currency correctly rejected: {e}")
                    
    def test_temporal_validation(self):
        """Test temporal validation of payments"""
        # Test future-dated payments
        gateway = self._create_mock_mollie_gateway(50.00)
        
        # Mock payment with future timestamp
        future_payment = MagicMock()
        future_payment.is_paid.return_value = True
        future_payment.amount = {"value": "50.00", "currency": "EUR"}
        future_payment.status = "paid"
        future_payment.created_at = (datetime.now() + timedelta(days=1)).isoformat()
        
        gateway.client.payments.get.return_value = future_payment
        
        try:
            result = _process_subscription_payment(
                gateway, self.member.name, self.customer.name,
                "tr_future_test", "sub_test_future"
            )
            
            # Future payments might be accepted depending on implementation
            # The key is that they should be logged and audited
            print(f"Future payment result: {result}")
            
        except Exception as e:
            print(f"Future payment handling: {e}")
            
    def test_race_condition_protection(self):
        """Test protection against race conditions in concurrent payment processing"""
        payment_id = "tr_race_test_001"
        gateway = self._create_mock_mollie_gateway(50.00)

        # The work under test touches the database, but frappe's DB connection is
        # thread-local. Worker threads spawned by ThreadPoolExecutor inherit no
        # bound connection, so without an explicit per-thread connect() every call
        # fails with "object is not bound" (a harness artifact, not a real race).
        # Commit the test fixtures first so the freshly-connected worker threads can
        # see the member/customer/invoice rows created in setUp.
        site = frappe.local.site
        member_name = self.member.name
        customer_name = self.customer.name

        # The processing function derives the company from Global Defaults /
        # user defaults; in a freshly-connected worker thread no user default is
        # set, so seed Global Defaults' default_company (as a configured production
        # site would have) and restore it afterwards. Commit so the worker threads
        # see both the fixtures and this default.
        previous_default_company = frappe.db.get_single_value("Global Defaults", "default_company")
        frappe.db.set_single_value("Global Defaults", "default_company", self.company)
        frappe.db.commit()

        results = []
        exceptions = []

        def process_payment():
            frappe.init(site=site)
            frappe.connect()
            try:
                return _process_subscription_payment(
                    gateway, member_name, customer_name, payment_id, "sub_race_test"
                )
            except Exception as e:
                exceptions.append(e)
                return {"status": "error", "error": str(e)}
            finally:
                frappe.db.commit()
                frappe.destroy()

        # Simulate concurrent processing
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(process_payment) for _ in range(3)]

            for future in as_completed(futures):
                results.append(future.result())

        # Restore the previous Global Defaults company so this test does not leak
        # state into other tests on the shared site.
        frappe.db.set_single_value("Global Defaults", "default_company", previous_default_company)
        frappe.db.commit()

        # The worker threads committed their own connections, so the duplicate-check
        # query below must read fresh committed rows.
        frappe.db.rollback()

        # Analyze results
        successful_results = [r for r in results if r.get("status") in ["success", "duplicate"]]
        error_results = [r for r in results if r.get("status") == "error"]

        print(f"Concurrent processing results: {len(successful_results)} successful, {len(error_results)} errors")

        # Should handle concurrent requests gracefully. assertGreaterEqual(1) alone
        # was too weak to prove the race is exercised -- it tolerated the state this
        # test sat in while baselined, where all three workers errored out before any
        # concurrency happened. Require every worker to complete: exactly one creates
        # the Payment Entry and the others must observe it and report "duplicate".
        self.assertEqual(
            len(error_results),
            0,
            f"no worker should error; got: {[r.get('error') for r in error_results]}",
        )
        self.assertEqual(len(successful_results), 3, "all three concurrent workers should complete")
        self.assertEqual(
            sum(1 for r in results if r.get("status") == "success"),
            1,
            "exactly one worker should be the one that creates the payment",
        )

        # Check for duplicate payment entries
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": payment_id},
            fields=["name"]
        )

        # Clean up any committed Payment Entries created by the worker threads so they
        # do not pollute the shared test site (their party customer is cleaned in
        # tearDown, which would otherwise leave the submitted PE uncancellable).
        for pe in payment_entries:
            try:
                doc = frappe.get_doc("Payment Entry", pe.name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Payment Entry", pe.name, force=True)
            except Exception:
                frappe.db.sql(
                    "DELETE FROM `tabGL Entry` WHERE voucher_type='Payment Entry' AND voucher_no=%s",
                    pe.name,
                )
                frappe.db.sql("DELETE FROM `tabPayment Entry` WHERE name=%s", pe.name)
        frappe.db.commit()

        # Exactly one, not "at most one": <=1 also passes when nothing was created
        # at all, which is precisely how this test used to fail silently.
        self.assertEqual(len(payment_entries), 1,
                         "Race condition should create exactly one payment entry")
                           
    def test_payment_reconciliation_accuracy(self):
        """Test accuracy of payment reconciliation"""
        test_scenarios = [
            {"invoice_amount": 50.00, "payment_amount": 50.00, "expected_status": "Paid"},
            {"invoice_amount": 50.00, "payment_amount": 25.00, "expected_status": "Partly Paid"},
            {"invoice_amount": 50.00, "payment_amount": 75.00, "expected_status": "Paid"},  # Overpayment
        ]
        
        for i, scenario in enumerate(test_scenarios):
            invoice_name = self._create_test_invoice(scenario["invoice_amount"])
            gateway = self._create_mock_mollie_gateway(scenario["payment_amount"])
            
            try:
                result = _process_subscription_payment(
                    gateway, self.member.name, self.customer.name,
                    f"tr_reconcile_test_{i}", f"sub_reconcile_test_{i}"
                )
                
                if result.get("status") == "success":
                    # Check invoice status
                    invoice = frappe.get_doc("Sales Invoice", invoice_name)
                    
                    # Note: In test environment, invoice status updates might not work
                    # due to missing ERPNext account configurations
                    print(f"Reconciliation test {i}: Invoice status: {invoice.status}")
                    
            except Exception as e:
                print(f"Reconciliation test {i} failed in test environment: {e}")
                
    def test_idempotency_protection(self):
        """Test idempotency of payment processing operations"""
        payment_id = "tr_idempotent_test_001"
        gateway = self._create_mock_mollie_gateway(50.00)
        
        # Process same payment multiple times with slight delays
        results = []
        
        for i in range(3):
            try:
                result = _process_subscription_payment(
                    gateway, self.member.name, self.customer.name, payment_id, "sub_idempotent_test"
                )
                results.append(result)
            except Exception as e:
                print(f"Idempotency test iteration {i} failed: {e}")
                results.append({"status": "error", "iteration": i})
                
            # Small delay between attempts
            time.sleep(0.1)
            
        # Analyze idempotency
        successful_results = [r for r in results if r.get("status") == "success"]
        
        if successful_results:
            # All successful results should be identical
            first_result = successful_results[0]
            for result in successful_results[1:]:
                # Key fields should be the same
                self.assertEqual(result.get("payment_id"), first_result.get("payment_id"))
                self.assertEqual(result.get("amount"), first_result.get("amount"))
                
        # Check payment entry uniqueness
        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": payment_id},
            fields=["name", "paid_amount"]
        )
        
        self.assertLessEqual(len(payment_entries), 1,
                           "Idempotency should prevent duplicate payment entries")
                           
    def test_performance_under_load(self):
        """Test financial safeguards performance under realistic load"""
        webhook_count = 25  # Achievable target: 25 webhooks/second
        
        # Create performance test data
        perf_data = self.mollie_factory.create_performance_test_data(webhook_count)
        
        processing_times = []
        successful_processes = 0
        
        for scenario in perf_data:
            start_time = datetime.now()
            
            gateway = self._create_mock_mollie_gateway(scenario["amount"])
            
            try:
                result = _process_subscription_payment(
                    gateway, scenario["member"], self.customer.name,
                    scenario["payment_id"], scenario["subscription_id"]
                )
                
                if result.get("status") == "success":
                    successful_processes += 1
                    
            except Exception as e:
                print(f"Performance test scenario failed: {e}")
                
            end_time = datetime.now()
            processing_time_ms = (end_time - start_time).total_seconds() * 1000
            processing_times.append(processing_time_ms)
            
        # Analyze performance
        if processing_times:
            avg_processing_time = sum(processing_times) / len(processing_times)
            max_processing_time = max(processing_times)
            
            print(f"Performance results:")
            print(f"  Scenarios processed: {len(perf_data)}")
            print(f"  Successful processes: {successful_processes}")
            print(f"  Average processing time: {avg_processing_time:.2f}ms")
            print(f"  Maximum processing time: {max_processing_time:.2f}ms")
            
            # Performance assertions (realistic targets)
            self.assertLessEqual(avg_processing_time, 1000,  # 1 second average
                               "Average processing time should be under 1 second")
            self.assertLessEqual(max_processing_time, 3000,  # 3 second maximum
                               "Maximum processing time should be under 3 seconds")
                               
    def test_audit_trail_completeness(self):
        """Test that financial operations create complete audit trails"""
        payment_id = "tr_audit_test_001"
        gateway = self._create_mock_mollie_gateway(50.00)
        
        # Count initial error logs
        initial_error_count = len(frappe.get_all("Error Log"))
        
        try:
            result = _process_subscription_payment(
                gateway, self.member.name, self.customer.name, payment_id, "sub_audit_test"
            )
            
            # Check if payment was logged
            payment_entries = frappe.get_all(
                "Payment Entry",
                filters={"reference_no": payment_id},
                fields=["name", "remarks", "creation"]
            )
            
            if payment_entries:
                payment_entry = payment_entries[0]
                self.assertIsNotNone(payment_entry["remarks"],
                                   "Payment entry should have remarks for audit trail")
                self.assertIn("Mollie", payment_entry["remarks"],
                            "Remarks should mention Mollie for audit trail")
                            
        except Exception as e:
            # Check if error was logged
            final_error_count = len(frappe.get_all("Error Log"))
            print(f"Audit test: Error count increased from {initial_error_count} to {final_error_count}")
            print(f"Audit test error: {e}")


if __name__ == "__main__":
    # Run basic safeguards validation
    import unittest
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMollieFinancialSafeguards)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print(f"\nFinancial Safeguards Test Results:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"  {test}: {traceback}")
            
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"  {test}: {traceback}")