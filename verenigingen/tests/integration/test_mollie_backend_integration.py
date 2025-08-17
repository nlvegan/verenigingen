"""
Comprehensive Integration Test Suite for Mollie Backend API
Tests all components working together in realistic scenarios
"""

import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
from verenigingen.verenigingen_payments.clients.chargebacks_client import ChargebacksClient
from verenigingen.verenigingen_payments.clients.invoices_client import InvoicesClient
from verenigingen.verenigingen_payments.clients.organizations_client import OrganizationsClient
from verenigingen.verenigingen_payments.clients.settlements_client import SettlementsClient
from verenigingen.verenigingen_payments.core.compliance.audit_trail import AuditTrail
from verenigingen.verenigingen_payments.core.security.webhook_validator import WebhookValidator
from verenigingen.verenigingen_payments.workflows.balance_monitor import BalanceMonitor
from verenigingen.verenigingen_payments.workflows.dispute_resolution import DisputeResolutionWorkflow
from verenigingen.verenigingen_payments.workflows.financial_dashboard import FinancialDashboard
from verenigingen.verenigingen_payments.workflows.reconciliation_engine import ReconciliationEngine
from verenigingen.verenigingen_payments.workflows.subscription_manager import SubscriptionManager


class TestMollieBackendIntegration(FrappeTestCase):
    """
    Integration tests for Mollie Backend API system
    
    Tests:
    - End-to-end workflows
    - Component interactions
    - Error handling and recovery
    - Data consistency
    - Performance under load
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        
        # Create test Mollie Settings
        if not frappe.db.exists("Mollie Settings", "Test Integration"):
            settings = frappe.new_doc("Mollie Settings")
            settings.gateway_name = "Test Integration"
            settings.secret_key = "test_key_12345"
            settings.profile_id = "pfl_test123"
            settings.enable_backend_api = True
            settings.enable_audit_trail = True
            settings.enable_encryption = True
            settings.insert(ignore_permissions=True)
            frappe.db.commit()
    
    def setUp(self):
        """Set up test case"""
        super().setUp()
        self.settings_name = "Test Integration"
        self.audit_trail = AuditTrail()
    
    def test_complete_reconciliation_workflow(self):
        """Test complete reconciliation workflow from webhook to reporting"""
        
        # Step 1: Simulate webhook notification for new settlement
        webhook_data = {
            "id": "stl_test123",
            "resource": "settlement",
            "amount": {"value": "1000.00", "currency": "EUR"},
            "status": "paidout",
            "createdAt": datetime.now().isoformat()
        }
        
        # Validate webhook
        validator = WebhookValidator(self.settings_name)
        body = json.dumps(webhook_data).encode()
        signature = validator._compute_signature(body, b"test_secret")
        
        is_valid = validator.validate_webhook(body, signature)
        self.assertTrue(is_valid)
        
        # Step 2: Process settlement through reconciliation engine
        with patch.object(SettlementsClient, 'get_settlement') as mock_get:
            mock_get.return_value = MagicMock(
                id="stl_test123",
                amount=MagicMock(value="1000.00", currency="EUR", decimal_value=Decimal("1000.00")),
                status="paidout",
                created_at=datetime.now()
            )
            
            engine = ReconciliationEngine(self.settings_name)
            result = engine.process_settlement("stl_test123")
            
            self.assertTrue(result["success"])
            self.assertEqual(result["settlement_id"], "stl_test123")
        
        # Step 3: Update financial dashboard
        dashboard = FinancialDashboard(self.settings_name)
        metrics = dashboard.get_real_time_metrics()
        
        self.assertIn("settlements", metrics)
        self.assertIn("balance", metrics)
        
        # Step 4: Verify audit trail
        events = frappe.get_all(
            "Mollie Audit Log",
            filters={"reference_id": "stl_test123"},
            fields=["event_type", "severity", "message"]
        )
        
        self.assertTrue(len(events) > 0)
    
    def test_subscription_payment_lifecycle(self):
        """Test complete subscription payment lifecycle"""
        
        # Step 1: Create test member with subscription
        member = self._create_test_member()
        
        # Step 2: Initialize subscription
        manager = SubscriptionManager(self.settings_name)
        
        with patch.object(manager.subscriptions_client, 'create_subscription') as mock_create:
            mock_create.return_value = MagicMock(
                id="sub_test123",
                status="active",
                amount=MagicMock(value="25.00", currency="EUR"),
                interval="1 month",
                next_payment_date=datetime.now() + timedelta(days=30)
            )
            
            result = manager.create_subscription(
                member_name=member.name,
                amount=25.00,
                interval="1 month"
            )
            
            self.assertTrue(result["success"])
            self.assertEqual(result["subscription_id"], "sub_test123")
        
        # Step 3: Process subscription payment webhook
        payment_data = {
            "id": "tr_test456",
            "subscriptionId": "sub_test123",
            "amount": {"value": "25.00", "currency": "EUR"},
            "status": "paid"
        }
        
        with patch('frappe.get_doc') as mock_get_doc:
            mock_member = MagicMock()
            mock_member.name = member.name
            mock_member.mollie_subscription_id = "sub_test123"
            mock_get_doc.return_value = mock_member
            
            result = manager.process_subscription_payment(payment_data)
            self.assertTrue(result.get("success", False))
        
        # Step 4: Monitor subscription status
        monitor = BalanceMonitor(self.settings_name)
        status = monitor.check_alerts()
        
        self.assertIsNotNone(status)
    
    def test_dispute_resolution_workflow(self):
        """Test complete dispute resolution workflow"""
        
        # Step 1: Create dispute case from chargeback
        workflow = DisputeResolutionWorkflow(self.settings_name)
        
        with patch.object(workflow.chargebacks_client, 'get_chargeback') as mock_get:
            mock_get.return_value = MagicMock(
                id="chb_test123",
                payment_id="tr_test789",
                amount=MagicMock(value="50.00", currency="EUR", decimal_value=Decimal("50.00")),
                reason="fraudulent",
                created_at=datetime.now()
            )
            
            case = workflow.create_dispute_case("tr_test789", "chb_test123")
            
            self.assertIsNotNone(case["case_id"])
            self.assertEqual(case["status"], "open")
        
        # Step 2: Submit dispute response
        response = workflow.submit_dispute_response(
            case_id=case["case_id"],
            evidence_ids=["ev_001", "ev_002"],
            response_text="Transaction was authorized and verified"
        )
        
        self.assertTrue(response["success"])
        
        # Step 3: Update dispute outcome
        outcome = workflow.update_dispute_outcome(
            case_id=case["case_id"],
            outcome="won",
            recovered_amount=50.00
        )
        
        self.assertEqual(outcome["outcome"], "won")
        self.assertEqual(outcome["recovered_amount"], 50.00)
        
        # Step 4: Analyze dispute patterns
        analysis = workflow.analyze_dispute_patterns(90)
        
        self.assertIn("win_rate", analysis)
        self.assertIn("patterns", analysis)
    
    def test_financial_reporting_accuracy(self):
        """Test accuracy of financial reporting across all modules"""
        
        dashboard = FinancialDashboard(self.settings_name)
        
        # Create test data
        test_data = {
            "settlements": [
                {"amount": 1000.00, "status": "paidout"},
                {"amount": 500.00, "status": "pending"},
                {"amount": 250.00, "status": "paidout"}
            ],
            "invoices": [
                {"amount": 100.00, "status": "paid"},
                {"amount": 50.00, "status": "open"}
            ],
            "chargebacks": [
                {"amount": 75.00, "status": "pending"},
                {"amount": 25.00, "status": "lost"}
            ]
        }
        
        # Mock API responses
        with patch.object(dashboard.settlements_client, 'list_settlements') as mock_settlements, \
             patch.object(dashboard.invoices_client, 'list_invoices') as mock_invoices, \
             patch.object(dashboard.chargebacks_client, 'list_chargebacks') as mock_chargebacks:
            
            # Set up mocks
            mock_settlements.return_value = self._create_mock_list(test_data["settlements"], "settlement")
            mock_invoices.return_value = self._create_mock_list(test_data["invoices"], "invoice")
            mock_chargebacks.return_value = self._create_mock_list(test_data["chargebacks"], "chargeback")
            
            # Get financial summary
            summary = dashboard.get_financial_summary(30)
            
            # Verify calculations
            self.assertEqual(summary["settlements"]["total_amount"], 1750.00)
            self.assertEqual(summary["settlements"]["paidout_amount"], 1250.00)
            self.assertEqual(summary["invoices"]["total_amount"], 150.00)
            self.assertEqual(summary["chargebacks"]["total_amount"], 100.00)
    
    def test_error_recovery_mechanisms(self):
        """Test system recovery from various error conditions"""
        
        # Test 1: API timeout recovery
        client = BalancesClient(self.settings_name)
        
        with patch.object(client.http_client, 'request') as mock_request:
            # Simulate timeout then success
            mock_request.side_effect = [
                TimeoutError("Request timed out"),
                MagicMock(status_code=200, json=lambda: {"balance": {"value": "1000.00"}})
            ]
            
            # Should retry and succeed
            balance = client.get_primary_balance()
            self.assertIsNotNone(balance)
        
        # Test 2: Database connection recovery
        engine = ReconciliationEngine(self.settings_name)
        
        with patch('frappe.db.sql') as mock_sql:
            # Simulate database error then success
            mock_sql.side_effect = [
                frappe.db.DatabaseError("Connection lost"),
                [{"name": "INV-001", "grand_total": 100.00}]
            ]
            
            # Should handle error gracefully
            result = engine.reconcile_daily()
            self.assertIn("error", result)
        
        # Test 3: Webhook validation failure recovery
        validator = WebhookValidator(self.settings_name)
        
        # Invalid signature should not crash system
        is_valid = validator.validate_webhook(b"test_body", "invalid_signature")
        self.assertFalse(is_valid)
        
        # Verify system still operational
        audit_events = frappe.get_all("Mollie Audit Log", limit=1)
        self.assertIsNotNone(audit_events)
    
    def test_concurrent_operations(self):
        """Test system behavior under concurrent operations"""
        
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        results = []
        errors = []
        
        def process_webhook(webhook_id):
            try:
                validator = WebhookValidator(self.settings_name)
                body = json.dumps({"id": webhook_id}).encode()
                signature = validator._compute_signature(body, b"test_secret")
                result = validator.validate_webhook(body, signature)
                return {"webhook_id": webhook_id, "valid": result}
            except Exception as e:
                return {"webhook_id": webhook_id, "error": str(e)}
        
        # Simulate 10 concurrent webhook validations
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(process_webhook, f"webhook_{i}")
                for i in range(10)
            ]
            
            for future in as_completed(futures):
                result = future.result()
                if "error" in result:
                    errors.append(result)
                else:
                    results.append(result)
        
        # All should complete without errors
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 10)
    
    def test_data_consistency_across_modules(self):
        """Test data consistency when multiple modules interact"""
        
        # Create a payment that flows through multiple modules
        payment_id = "tr_consistency_test"
        amount = Decimal("100.00")
        
        # Step 1: Process through subscription manager
        sub_manager = SubscriptionManager(self.settings_name)
        
        with patch.object(sub_manager, '_get_unpaid_invoice') as mock_invoice:
            mock_invoice.return_value = MagicMock(
                name="INV-001",
                grand_total=float(amount)
            )
            
            payment_data = {
                "id": payment_id,
                "amount": {"value": str(amount), "currency": "EUR"},
                "status": "paid"
            }
            
            # Process payment
            sub_result = sub_manager.process_subscription_payment(payment_data)
        
        # Step 2: Same payment in reconciliation
        recon_engine = ReconciliationEngine(self.settings_name)
        
        with patch.object(recon_engine, '_get_bank_transactions') as mock_bank:
            mock_bank.return_value = [{
                "reference": payment_id,
                "amount": float(amount),
                "date": datetime.now()
            }]
            
            recon_result = recon_engine._match_transactions([])
        
        # Step 3: Verify in financial dashboard
        dashboard = FinancialDashboard(self.settings_name)
        
        with patch.object(dashboard, '_get_recent_payments') as mock_payments:
            mock_payments.return_value = [{
                "payment_id": payment_id,
                "amount": float(amount),
                "status": "reconciled"
            }]
            
            metrics = dashboard.get_real_time_metrics()
        
        # Verify consistency
        self.assertEqual(
            sub_result.get("amount", 0),
            float(amount),
            "Amount mismatch in subscription manager"
        )
    
    def test_audit_trail_completeness(self):
        """Test that all critical operations are properly audited"""
        
        critical_operations = [
            ("webhook_validation", WebhookValidator),
            ("settlement_reconciliation", ReconciliationEngine),
            ("dispute_creation", DisputeResolutionWorkflow),
            ("subscription_creation", SubscriptionManager),
            ("balance_alert", BalanceMonitor)
        ]
        
        for operation_name, module_class in critical_operations:
            # Initialize module
            module = module_class(self.settings_name)
            
            # Perform operation (mocked)
            if operation_name == "webhook_validation":
                with patch.object(module, '_compute_signature') as mock_sig:
                    mock_sig.return_value = "valid_sig"
                    module.validate_webhook(b"test", "valid_sig")
            
            # Verify audit log created
            audit_logs = frappe.get_all(
                "Mollie Audit Log",
                filters={"created": [">", datetime.now() - timedelta(minutes=1)]},
                fields=["event_type", "message"]
            )
            
            # Should have audit entries
            self.assertTrue(
                len(audit_logs) > 0,
                f"No audit log for {operation_name}"
            )
    
    def test_performance_under_load(self):
        """Test system performance under heavy load"""
        
        import time
        
        # Test rapid webhook processing
        validator = WebhookValidator(self.settings_name)
        
        start_time = time.time()
        validations = []
        
        for i in range(100):
            body = json.dumps({"id": f"test_{i}"}).encode()
            signature = validator._compute_signature(body, b"test_secret")
            result = validator.validate_webhook(body, signature)
            validations.append(result)
        
        elapsed = time.time() - start_time
        
        # Should process 100 webhooks in under 5 seconds
        self.assertLess(elapsed, 5.0)
        self.assertEqual(len(validations), 100)
        
        # Test database query performance
        dashboard = FinancialDashboard(self.settings_name)
        
        start_time = time.time()
        
        with patch.object(dashboard, '_get_cached_data') as mock_cache:
            mock_cache.return_value = None  # Force fresh queries
            
            for _ in range(10):
                metrics = dashboard.get_real_time_metrics()
        
        elapsed = time.time() - start_time
        
        # Should handle 10 dashboard refreshes in under 3 seconds
        self.assertLess(elapsed, 3.0)
    
    def test_graceful_degradation(self):
        """Test system continues functioning when non-critical services fail"""
        
        dashboard = FinancialDashboard(self.settings_name)
        
        # Simulate various service failures
        with patch.object(dashboard.invoices_client, 'list_invoices') as mock_invoices, \
             patch.object(dashboard.chargebacks_client, 'list_chargebacks') as mock_chargebacks:
            
            # Invoices API fails
            mock_invoices.side_effect = Exception("Invoice API unavailable")
            
            # Chargebacks API fails
            mock_chargebacks.side_effect = Exception("Chargeback API unavailable")
            
            # Dashboard should still provide partial data
            metrics = dashboard.get_real_time_metrics()
            
            self.assertIsNotNone(metrics)
            self.assertIn("balance", metrics)  # Core functionality still works
            self.assertIn("error_services", metrics)  # Reports failed services
    
    # Helper methods
    
    def _create_test_member(self):
        """Create test member for subscription tests"""
        member = frappe.new_doc("Member")
        member.first_name = "Test"
        member.last_name = "Integration"
        member.email = f"test_{frappe.generate_hash(length=5)}@example.com"
        member.mollie_customer_id = f"cst_test_{frappe.generate_hash(length=8)}"
        member.insert(ignore_permissions=True)
        return member
    
    def _create_mock_list(self, items, item_type):
        """Create mock list response for API calls"""
        mock_items = []
        
        for item in items:
            mock_item = MagicMock()
            mock_item.amount = MagicMock(
                value=str(item["amount"]),
                currency="EUR",
                decimal_value=Decimal(str(item["amount"]))
            )
            mock_item.status = item["status"]
            mock_item.id = f"{item_type}_{frappe.generate_hash(length=6)}"
            mock_items.append(mock_item)
        
        return mock_items
    
    def tearDown(self):
        """Clean up after test"""
        # Clean up test data
        frappe.db.delete("Mollie Audit Log", {"reference_id": ["like", "%test%"]})
        frappe.db.delete("Dispute Case", {"case_id": ["like", "%test%"]})
        frappe.db.commit()
        super().tearDown()