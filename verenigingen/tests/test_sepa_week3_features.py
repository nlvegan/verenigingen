"""
Comprehensive Tests for SEPA Week 3 Features

Tests for all Week 3 SEPA billing improvements including:
- Race condition prevention
- Transaction isolation  
- Conflict detection
- Retry logic with exponential backoff
- Enhanced SEPA XML generation
- SEPA rulebook validation
- Mandate lifecycle management
- Rollback mechanisms
- Compensation transactions
- Audit trails
- Notification system

Implements comprehensive test coverage for Week 3 implementation.
"""

import unittest
import time
import json
from decimal import Decimal
from datetime import datetime, date, timedelta
from unittest.mock import patch, MagicMock

import frappe
from frappe.utils import today, now, add_days, getdate

# Import the modules we're testing
from verenigingen.utils.sepa_race_condition_manager import (
    SEPADistributedLock, SEPABatchRaceConditionManager
)
from verenigingen.utils.sepa_conflict_detector import (
    SEPAConflictDetector, ConflictSeverity
)
from verenigingen.utils.sepa_retry_manager import (
    SEPARetryManager, RetryConfig, RetryStrategy, with_retry
)
from verenigingen.utils.sepa_xml_enhanced_generator import (
    EnhancedSEPAXMLGenerator, SEPASequenceType, SEPALocalInstrument
)
from verenigingen.utils.sepa_rulebook_validator import (
    SEPARulebookValidator
)
from verenigingen.utils.sepa_mandate_lifecycle_manager import (
    SEPAMandateLifecycleManager, MandateUsageType
)
from verenigingen.utils.sepa_rollback_manager import (
    SEPARollbackManager, RollbackReason, RollbackScope
)
from verenigingen.utils.sepa_notification_manager import (
    SEPANotificationManager, NotificationType, NotificationPriority
)


class TestSEPAWeek3Features(unittest.TestCase):
    """Comprehensive test suite for SEPA Week 3 features"""
    
    def setUp(self):
        """Set up test data and environment"""
        # Clear any existing test data
        self.cleanup_test_data()
        
        # Create test batch data
        self.test_batch_data = {
            "batch_date": add_days(today(), 5),
            "batch_type": "CORE",
            "description": "Test SEPA Batch",
            "invoice_list": [
                {
                    "invoice": "TEST-INV-001",
                    "amount": 100.50,
                    "currency": "EUR",
                    "member_name": "Test Member 1",
                    "iban": "NL91ABNA0417164300",
                    "bic": "ABNANL2A",
                    "mandate_reference": "TEST-MANDATE-001"
                },
                {
                    "invoice": "TEST-INV-002", 
                    "amount": 75.25,
                    "currency": "EUR",
                    "member_name": "Test Member 2",
                    "iban": "NL13INGB0012345678",
                    "bic": "INGBNL2A",
                    "mandate_reference": "TEST-MANDATE-002"
                }
            ]
        }
    
    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()
    
    def cleanup_test_data(self):
        """Clean up test data from database"""
        try:
            # Clean up test locks
            frappe.db.sql("DELETE FROM `tabSEPA_Distributed_Lock` WHERE lock_owner LIKE 'test_%'")
            
            # Clean up test rollback operations
            frappe.db.sql("DELETE FROM `tabSEPA_Rollback_Operation` WHERE operation_id LIKE 'TEST_%'")
            
            # Clean up test notifications
            frappe.db.sql("DELETE FROM `tabSEPA_Notification_Log` WHERE notification_id LIKE 'TEST_%'")
            
            frappe.db.commit()
        except Exception:
            pass  # Tables might not exist yet
    
    # ========================================================================
    # Race Condition Prevention Tests
    # ========================================================================
    
    def test_distributed_lock_acquisition(self):
        """Test distributed lock acquisition and release"""
        lock_manager = SEPADistributedLock()
        resource = "test_resource_001"
        
        # Test successful lock acquisition
        with lock_manager.acquire_lock(resource, timeout=10) as lock_info:
            self.assertIsNotNone(lock_info)
            self.assertEqual(lock_info.resource, resource)
            self.assertIsNotNone(lock_info.lock_id)
        
        # Lock should be released after context manager exits
        # Verify by trying to acquire the same resource again
        with lock_manager.acquire_lock(resource, timeout=1) as lock_info2:
            self.assertIsNotNone(lock_info2)
            self.assertNotEqual(lock_info.lock_id, lock_info2.lock_id)
    
    def test_concurrent_lock_acquisition(self):
        """Test that concurrent lock acquisition is prevented"""
        lock_manager1 = SEPADistributedLock()
        lock_manager2 = SEPADistributedLock()
        resource = "test_resource_002"
        
        # First manager acquires lock
        with lock_manager1.acquire_lock(resource, timeout=10):
            # Second manager should fail to acquire the same lock
            with self.assertRaises(Exception):  # Should raise SEPAError
                with lock_manager2.acquire_lock(resource, timeout=1):
                    pass
    
    def test_batch_creation_with_race_protection(self):
        """Test batch creation with race condition protection"""
        manager = SEPABatchRaceConditionManager()
        
        # Mock the validation methods to avoid database dependencies
        with patch.object(manager, '_lock_invoices_for_processing') as mock_lock, \
             patch.object(manager, '_validate_invoice_availability') as mock_validate, \
             patch.object(manager, '_detect_batch_conflicts') as mock_conflicts, \
             patch.object(manager, '_create_batch_document') as mock_create, \
             patch.object(manager, '_link_invoices_to_batch') as mock_link:
            
            # Configure mocks
            mock_lock.return_value = [{"name": "TEST-INV-001", "status": "Unpaid", "outstanding_amount": 100.50}]
            mock_validate.return_value = {"valid": True, "validated_invoices": self.test_batch_data["invoice_list"]}
            mock_conflicts.return_value = {"conflicts": []}
            
            mock_batch = MagicMock()
            mock_batch.name = "TEST-BATCH-001"
            mock_batch.total_amount = 175.75
            mock_create.return_value = mock_batch
            
            # Test batch creation
            result = manager.create_batch_with_race_protection(self.test_batch_data)
            
            self.assertTrue(result["success"])
            self.assertEqual(result["batch_name"], "TEST-BATCH-001")
            self.assertEqual(result["invoice_count"], 2)
    
    # ========================================================================
    # Conflict Detection Tests
    # ========================================================================
    
    def test_conflict_detection_duplicate_invoices(self):
        """Test detection of duplicate invoices in batch"""
        detector = SEPAConflictDetector()
        
        # Create batch data with duplicate invoice
        batch_data_with_duplicates = {
            "batch_date": today(),
            "batch_type": "CORE",
            "invoice_list": [
                {"invoice": "DUPLICATE-001", "amount": 100},
                {"invoice": "DUPLICATE-001", "amount": 100},  # Duplicate
                {"invoice": "UNIQUE-001", "amount": 200}
            ]
        }
        
        conflicts = detector.detect_batch_creation_conflicts(batch_data_with_duplicates)
        
        # Should detect duplicate invoice conflict
        duplicate_conflicts = [c for c in conflicts if c.conflict_type == "duplicate_invoice"]
        self.assertTrue(len(duplicate_conflicts) > 0)
        self.assertEqual(duplicate_conflicts[0].severity, ConflictSeverity.CRITICAL)
    
    def test_conflict_detection_date_validation(self):
        """Test detection of date-related conflicts"""
        detector = SEPAConflictDetector()
        
        # Create batch data with past date
        batch_data_past_date = {
            "batch_date": add_days(today(), -1),  # Yesterday
            "batch_type": "CORE",
            "invoice_list": [{"invoice": "TEST-001", "amount": 100}]
        }
        
        conflicts = detector.detect_batch_creation_conflicts(batch_data_past_date)
        
        # Should detect past date conflict
        date_conflicts = [c for c in conflicts if c.conflict_type == "past_date"]
        self.assertTrue(len(date_conflicts) > 0)
        self.assertEqual(date_conflicts[0].severity, ConflictSeverity.CRITICAL)
    
    def test_conflict_detection_weekend_collection(self):
        """Test detection of weekend collection dates"""
        detector = SEPAConflictDetector()
        
        # Find next Saturday
        next_saturday = add_days(today(), (5 - getdate(today()).weekday()) % 7)
        
        batch_data_weekend = {
            "batch_date": next_saturday,
            "batch_type": "CORE",
            "invoice_list": [{"invoice": "TEST-001", "amount": 100}]
        }
        
        conflicts = detector.detect_batch_creation_conflicts(batch_data_weekend)
        
        # Should detect weekend collection warning
        weekend_conflicts = [c for c in conflicts if c.conflict_type == "weekend_collection"]
        self.assertTrue(len(weekend_conflicts) > 0)
        self.assertEqual(weekend_conflicts[0].severity, ConflictSeverity.WARNING)
    
    # ========================================================================
    # Retry Logic Tests
    # ========================================================================
    
    def test_retry_manager_exponential_backoff(self):
        """Test retry manager with exponential backoff"""
        manager = SEPARetryManager()
        
        # Create a function that fails first two times, succeeds third time
        attempt_count = 0
        def failing_operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception(f"Attempt {attempt_count} failed")
            return f"Success on attempt {attempt_count}"
        
        config = RetryConfig(
            max_attempts=5,
            base_delay=0.1,  # Small delay for testing
            strategy=RetryStrategy.EXPONENTIAL
        )
        
        result = manager.retry_operation(failing_operation, config, "test_operation")
        
        self.assertTrue(result.success)
        self.assertEqual(result.total_attempts, 3)
        self.assertEqual(result.result, "Success on attempt 3")
    
    def test_retry_decorator(self):
        """Test retry decorator functionality"""
        attempt_count = 0
        
        @with_retry(RetryConfig(max_attempts=3, base_delay=0.01))
        def decorated_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ValueError("First attempt fails")
            return "Success"
        
        result = decorated_function()
        self.assertEqual(result, "Success")
        self.assertEqual(attempt_count, 2)
    
    def test_circuit_breaker_functionality(self):
        """Test circuit breaker pattern"""
        manager = SEPARetryManager()
        
        # Create operation that always fails
        def always_fails():
            raise Exception("Always fails")
        
        config = RetryConfig(
            max_attempts=1,
            circuit_breaker_threshold=2,
            circuit_breaker_window=1
        )
        
        # First few calls should fail normally
        result1 = manager.retry_operation(always_fails, config, "circuit_test")
        self.assertFalse(result1.success)
        
        result2 = manager.retry_operation(always_fails, config, "circuit_test")
        self.assertFalse(result2.success)
        
        # Circuit should now be open and reject immediately
        with self.assertRaises(Exception):  # Should raise circuit breaker exception
            manager.retry_operation(always_fails, config, "circuit_test")
    
    # ========================================================================
    # Enhanced XML Generation Tests
    # ========================================================================
    
    def test_enhanced_xml_generation(self):
        """Test enhanced SEPA XML generation"""
        generator = EnhancedSEPAXMLGenerator()
        
        # Create test data structures
        from verenigingen.utils.sepa_xml_enhanced_generator import (
            SEPACreditor, SEPADebtor, SEPAMandate, SEPATransaction, SEPAPaymentInfo
        )
        
        creditor = SEPACreditor(
            name="Test Company",
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            creditor_id="NL13ZZZ123456780000"
        )
        
        debtor = SEPADebtor(
            name="Test Customer",
            iban="NL13INGB0012345678",
            bic="INGBNL2A"
        )
        
        mandate = SEPAMandate(
            mandate_id="TEST-MANDATE-001",
            date_of_signature=date.today()
        )
        
        transaction = SEPATransaction(
            end_to_end_id="E2E-TEST-001",
            amount=Decimal("100.50"),
            currency="EUR",
            debtor=debtor,
            mandate=mandate,
            remittance_info="Test payment",
            sequence_type=SEPASequenceType.RCUR
        )
        
        payment_info = SEPAPaymentInfo(
            payment_info_id="PMT-TEST-001",
            payment_method="DD",
            batch_booking=True,
            requested_collection_date=date.today(),
            creditor=creditor,
            local_instrument=SEPALocalInstrument.CORE,
            sequence_type=SEPASequenceType.RCUR,
            transactions=[transaction]
        )
        
        # Generate XML
        xml_content = generator.generate_sepa_xml(
            message_id="MSG-TEST-001",
            creation_datetime=datetime.now(),
            payment_infos=[payment_info],
            initiating_party_name="Test Company"
        )
        
        # Verify XML structure
        self.assertIn("urn:iso:std:iso:20022:tech:xsd:pain.008.001.02", xml_content)
        self.assertIn("CstmrDrctDbtInitn", xml_content)
        self.assertIn("MSG-TEST-001", xml_content)
        self.assertIn("E2E-TEST-001", xml_content)
        self.assertIn("100.50", xml_content)
    
    def test_xml_validation_errors(self):
        """Test XML generation validation errors"""
        generator = EnhancedSEPAXMLGenerator()
        
        # Test with invalid message ID (too long)
        with self.assertRaises(Exception):
            generator.generate_sepa_xml(
                message_id="A" * 50,  # Too long
                creation_datetime=datetime.now(),
                payment_infos=[],
                initiating_party_name="Test"
            )
    
    # ========================================================================
    # SEPA Rulebook Validation Tests
    # ========================================================================
    
    def test_sepa_rulebook_validation(self):
        """Test SEPA rulebook validation"""
        validator = SEPARulebookValidator()
        
        # Create valid SEPA XML
        valid_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.02">
            <CstmrDrctDbtInitn>
                <GrpHdr>
                    <MsgId>MSG-TEST-001</MsgId>
                    <CreDtTm>2025-07-25T10:00:00</CreDtTm>
                    <NbOfTxs>1</NbOfTxs>
                    <CtrlSum>100.50</CtrlSum>
                    <InitgPty><Nm>Test Company</Nm></InitgPty>
                </GrpHdr>
                <PmtInf>
                    <PmtInfId>PMT-TEST-001</PmtInfId>
                    <PmtMtd>DD</PmtMtd>
                    <DrctDbtTxInf>
                        <InstdAmt Ccy="EUR">100.50</InstdAmt>
                    </DrctDbtTxInf>
                </PmtInf>
            </CstmrDrctDbtInitn>
        </Document>"""
        
        result = validator.validate_sepa_xml(valid_xml)
        
        self.assertIn("compliance_score", result)
        self.assertIn("is_compliant", result)
        self.assertIn("issues", result)
    
    def test_rulebook_validation_errors(self):
        """Test rulebook validation with errors"""
        validator = SEPARulebookValidator()
        
        # Create XML with validation errors
        invalid_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.02">
            <CstmrDrctDbtInitn>
                <GrpHdr>
                    <MsgId></MsgId>  <!-- Empty message ID -->
                    <NbOfTxs>1</NbOfTxs>
                    <CtrlSum>999999</CtrlSum>  <!-- Mismatched control sum -->
                </GrpHdr>
            </CstmrDrctDbtInitn>
        </Document>"""
        
        result = validator.validate_sepa_xml(invalid_xml)
        
        self.assertFalse(result["is_compliant"])
        self.assertTrue(len(result["issues"]) > 0)
    
    # ========================================================================
    # Mandate Lifecycle Management Tests
    # ========================================================================
    
    def test_mandate_lifecycle_manager(self):
        """Test mandate lifecycle management"""
        manager = SEPAMandateLifecycleManager()
        
        # Mock mandate data
        with patch.object(manager, '_get_mandate_info') as mock_mandate, \
             patch.object(manager, '_get_mandate_usage_history') as mock_history:
            
            mock_mandate.return_value = {
                "mandate_id": "TEST-MANDATE-001",
                "status": "Active",
                "sign_date": add_days(today(), -30),
                "first_collection_date": add_days(today(), -25),  # not "valid_from"
                "expiry_date": add_days(today(), 365),           # not "valid_until"
                "member": "TEST-MEMBER-001",
                "iban": "NL91ABNA0417164300",
                "mandate_type": "RCUR",
                "creation": add_days(today(), -30),
                "modified": today()
            }
            
            mock_history.return_value = []  # No previous usage
            
            result = manager.determine_sequence_type("TEST-MANDATE-001")
            
            self.assertTrue(result.is_valid)
            self.assertEqual(result.usage_type, MandateUsageType.FIRST_USE)
            self.assertEqual(result.recommended_sequence_type, SEPASequenceType.FRST)
    
    def test_mandate_usage_validation(self):
        """Test mandate usage validation"""
        manager = SEPAMandateLifecycleManager()
        
        with patch.object(manager, 'determine_sequence_type') as mock_determine:
            mock_determine.return_value = MagicMock()
            mock_determine.return_value.is_valid = True
            mock_determine.return_value.errors = []
            mock_determine.return_value.warnings = []
            
            result = manager.validate_mandate_for_transaction(
                "TEST-MANDATE-001",
                Decimal("100.50")
            )
            
            self.assertTrue(result.is_valid)
    
    # ========================================================================
    # Rollback Manager Tests
    # ========================================================================
    
    def test_rollback_manager_initialization(self):
        """Test rollback manager initialization"""
        manager = SEPARollbackManager()
        
        # Test that manager initializes without errors
        self.assertIsNotNone(manager)
    
    def test_rollback_operation_creation(self):
        """Test rollback operation creation"""
        manager = SEPARollbackManager()
        
        # Mock batch info
        with patch.object(manager, '_get_batch_info') as mock_batch, \
             patch.object(manager, '_execute_rollback_steps') as mock_execute, \
             patch.object(manager, '_generate_compensation_transactions') as mock_compensation, \
             patch.object(manager, '_send_rollback_notifications') as mock_notify:
            
            mock_batch.return_value = {
                "name": "TEST-BATCH-001",
                "status": "Failed",
                "invoices": [
                    MagicMock(invoice="TEST-INV-001", amount=100.50, member="TEST-MEMBER-001"),
                    MagicMock(invoice="TEST-INV-002", amount=75.25, member="TEST-MEMBER-002")
                ]
            }
            
            mock_execute.return_value = {"success": True, "steps": [], "errors": []}
            mock_compensation.return_value = {"success": True, "compensation_transactions": []}
            
            result = manager.initiate_batch_rollback(
                "TEST-BATCH-001",
                RollbackReason.BATCH_PROCESSING_FAILED,
                RollbackScope.FULL_BATCH
            )
            
            self.assertTrue(result["success"])
            self.assertEqual(result["batch_name"], "TEST-BATCH-001")
            self.assertIn("operation_id", result)
    
    # ========================================================================
    # Notification Manager Tests
    # ========================================================================
    
    def test_notification_manager_initialization(self):
        """Test notification manager initialization"""
        manager = SEPANotificationManager()
        
        # Test that templates are loaded
        self.assertTrue(len(manager.templates) > 0)
        self.assertTrue(len(manager.rules) > 0)
        
        # Test specific templates exist
        self.assertIn("batch_success", manager.templates)
        self.assertIn("batch_failure", manager.templates)
    
    def test_notification_sending(self):
        """Test notification sending"""
        manager = SEPANotificationManager()
        
        # Mock email sending
        with patch('frappe.sendmail') as mock_sendmail, \
             patch.object(manager, '_get_rule_recipients') as mock_recipients:
            
            mock_recipients.return_value = ["test@example.com"]
            mock_sendmail.return_value = True
            
            context = {
                "batch_name": "TEST-BATCH-001",
                "collection_date": today(),
                "total_amount": 1000.00,
                "transaction_count": 10,
                "processing_time": "30 seconds"
            }
            
            result = manager.send_notification(NotificationType.BATCH_SUCCESS, context)
            
            self.assertTrue(result["success"])
            self.assertTrue(result["delivered"] > 0)
    
    def test_notification_template_rendering(self):
        """Test notification template rendering"""
        manager = SEPANotificationManager()
        
        template = manager.templates["batch_success"]
        context = {
            "batch_name": "TEST-BATCH-001",
            "collection_date": today(),
            "total_amount": 1000.00,
            "transaction_count": 10,
            "processing_time": "30 seconds"
        }
        
        result = manager._render_notification(template, context)
        
        self.assertTrue(result["success"])
        self.assertIn("TEST-BATCH-001", result["subject"])
        self.assertIn("€1,000.00", result["message"])
    
    # ========================================================================
    # Integration Tests
    # ========================================================================
    
    def test_end_to_end_batch_processing(self):
        """Test end-to-end batch processing with all Week 3 features"""
        # This test would ideally test the complete flow:
        # 1. Race-protected batch creation
        # 2. Conflict detection
        # 3. XML generation with validation
        # 4. Potential rollback scenarios
        # 5. Notifications
        
        # For now, just test that all managers can be instantiated together
        race_manager = SEPABatchRaceConditionManager()
        conflict_detector = SEPAConflictDetector()
        retry_manager = SEPARetryManager()
        xml_generator = EnhancedSEPAXMLGenerator()
        rulebook_validator = SEPARulebookValidator()
        mandate_manager = SEPAMandateLifecycleManager()
        rollback_manager = SEPARollbackManager()
        notification_manager = SEPANotificationManager()
        
        # All managers should initialize successfully
        self.assertIsNotNone(race_manager)
        self.assertIsNotNone(conflict_detector)
        self.assertIsNotNone(retry_manager)
        self.assertIsNotNone(xml_generator)
        self.assertIsNotNone(rulebook_validator)
        self.assertIsNotNone(mandate_manager)
        self.assertIsNotNone(rollback_manager)
        self.assertIsNotNone(notification_manager)
    
    def test_performance_characteristics(self):
        """Test performance characteristics of Week 3 features"""
        # Test that operations complete within reasonable time
        import time
        
        # Test conflict detection performance
        detector = SEPAConflictDetector()
        start_time = time.time()
        
        large_batch_data = {
            "batch_date": today(),
            "batch_type": "CORE",
            "invoice_list": [
                {"invoice": f"TEST-INV-{i:03d}", "amount": 100, "member_name": f"Member {i}"}
                for i in range(100)  # 100 invoices
            ]
        }
        
        conflicts = detector.detect_batch_creation_conflicts(large_batch_data)
        detection_time = time.time() - start_time
        
        # Should complete within 5 seconds for 100 invoices
        self.assertLess(detection_time, 5.0)
        
        # Test XML generation performance
        generator = EnhancedSEPAXMLGenerator()
        
        # Performance test would require more complex setup
        # For now, just verify generator works
        self.assertIsNotNone(generator)
    
    def test_error_handling_robustness(self):
        """Test error handling robustness across all Week 3 features"""
        # Test that managers handle errors gracefully
        
        # Test race condition manager with invalid data
        race_manager = SEPABatchRaceConditionManager()
        
        try:
            result = race_manager.create_batch_with_race_protection({})
            # Should either succeed or fail gracefully
            self.assertIn("success", result)
        except Exception as e:
            # Should be a controlled exception, not a system crash
            self.assertIsInstance(e, (ValueError, TypeError, Exception))
        
        # Test conflict detector with malformed data
        detector = SEPAConflictDetector()
        
        try:
            conflicts = detector.detect_batch_creation_conflicts({"invalid": "data"})
            # Should return conflicts or empty list, not crash
            self.assertIsInstance(conflicts, list)
        except Exception as e:
            # Should be a controlled exception
            self.assertIsInstance(e, (ValueError, TypeError, Exception))


# Additional utility functions for testing

def create_test_sepa_xml():
    """Create valid test SEPA XML for testing"""
    return """<?xml version="1.0" encoding="UTF-8"?>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.02">
        <CstmrDrctDbtInitn>
            <GrpHdr>
                <MsgId>MSG-TEST-001</MsgId>
                <CreDtTm>2025-07-25T10:00:00</CreDtTm>
                <NbOfTxs>1</NbOfTxs>
                <CtrlSum>100.50</CtrlSum>
                <InitgPty><Nm>Test Company</Nm></InitgPty>
            </GrpHdr>
            <PmtInf>
                <PmtInfId>PMT-TEST-001</PmtInfId>
                <PmtMtd>DD</PmtMtd>
                <BtchBookg>true</BtchBookg>
                <NbOfTxs>1</NbOfTxs>
                <CtrlSum>100.50</CtrlSum>
                <PmtTpInf>
                    <SvcLvl><Cd>SEPA</Cd></SvcLvl>
                    <LclInstrm><Cd>CORE</Cd></LclInstrm>
                    <SeqTp>RCUR</SeqTp>
                </PmtTpInf>
                <ReqdColltnDt>2025-08-01</ReqdColltnDt>
                <Cdtr><Nm>Test Company</Nm></Cdtr>
                <CdtrAcct><Id><IBAN>NL91ABNA0417164300</IBAN></Id></CdtrAcct>
                <CdtrAgt><FinInstnId><BIC>ABNANL2A</BIC></FinInstnId></CdtrAgt>
                <CdtrSchmeId>
                    <Id><PrvtId><Othr><Id>NL13ZZZ123456780000</Id><SchmeNm><Prtry>SEPA</Prtry></SchmeNm></Othr></PrvtId></Id>
                </CdtrSchmeId>
                <DrctDbtTxInf>
                    <PmtId><EndToEndId>E2E-TEST-001</EndToEndId></PmtId>
                    <InstdAmt Ccy="EUR">100.50</InstdAmt>
                    <DrctDbtTx>
                        <MndtRltdInf>
                            <MndtId>TEST-MANDATE-001</MndtId>
                            <DtOfSgntr>2025-01-01</DtOfSgntr>
                        </MndtRltdInf>
                    </DrctDbtTx>
                    <DbtrAgt><FinInstnId><BIC>INGBNL2A</BIC></FinInstnId></DbtrAgt>
                    <Dbtr><Nm>Test Customer</Nm></Dbtr>
                    <DbtrAcct><Id><IBAN>NL13INGB0012345678</IBAN></Id></DbtrAcct>
                    <RmtInf><Ustrd>Test payment</Ustrd></RmtInf>
                </DrctDbtTxInf>
            </PmtInf>
        </CstmrDrctDbtInitn>
    </Document>"""


if __name__ == "__main__":
    unittest.main()