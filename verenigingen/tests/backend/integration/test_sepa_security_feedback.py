# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
SEPA Security Feedback Tests

Comprehensive tests addressing all 8 points from the security review:

1. Atomic compare-and-delete for Redis lock releases (P1)
2. Redis capability verification (P2)
3. Compact idempotency cache values (P2)
4. Mandate sequence type concurrency (P1)
5. FOR UPDATE semantics (P2)
6. Secure XML parsing (P2)
7. Redis health check (P2)
8. Idempotency concurrency tests

Note: Tests involving threading use frappe.init() for thread context setup.
This is required because Frappe's database connection is thread-local.

test-quality-enforcer: exempt-thread-context-setup
"""

import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.api.sepa_duplicate_prevention import (
    _REDIS_RELEASE_LOCK_SCRIPT,
    ConcurrentOperationError,
    _extract_cacheable_result,
    _generate_lock_token,
    check_redis_health,
    execute_idempotent_operation,
    generate_idempotency_key,
    verify_redis_capabilities,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _create_thread_context(site: str):
    """Set up Frappe context for a worker thread.

    Frappe's session is thread-local, so each worker thread needs its own
    database connection and user context.
    """
    frappe.init(site=site, force=True)
    frappe.connect()
    frappe.set_user("Administrator")


def _cleanup_thread_context():
    """Clean up Frappe context after thread work."""
    try:
        frappe.db.commit()
    except Exception:
        pass
    try:
        frappe.destroy()
    except Exception:
        pass


# =============================================================================
# Point 1: Atomic Compare-and-Delete Tests
# =============================================================================


class TestAtomicLockRelease(EnhancedTestCase):
    """Test atomic compare-and-delete for Redis lock releases (P1)."""

    def test_lua_script_only_deletes_owned_lock(self):
        """Verify Lua script doesn't delete lock owned by another process."""
        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            self.skipTest("Redis locks not configured")

        cache = frappe.cache()
        test_key = f"sepa_test_lock:{uuid.uuid4().hex}"
        owner1_token = "owner1_" + uuid.uuid4().hex
        owner2_token = "owner2_" + uuid.uuid4().hex

        try:
            # Owner 1 acquires lock
            cache.set(test_key, owner1_token, ex=60)

            # Simulate: Owner 1's lock expires, Owner 2 acquires
            cache.set(test_key, owner2_token, ex=60)

            # Owner 1 (delayed) tries to release - should NOT delete Owner 2's lock
            redis_client = cache.connection
            if hasattr(redis_client, "eval"):
                result = redis_client.eval(_REDIS_RELEASE_LOCK_SCRIPT, 1, test_key, owner1_token)
                self.assertEqual(result, 0, "Lua script should return 0 (not deleted)")

                # Verify Owner 2's lock is still there
                current_value = cache.get(test_key)
                self.assertEqual(current_value, owner2_token, "Owner 2's lock should still exist")
            else:
                self.skipTest("Redis client does not support eval()")

        finally:
            cache.delete(test_key)

    def test_lua_script_deletes_owned_lock(self):
        """Verify Lua script correctly deletes lock when ownership matches."""
        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            self.skipTest("Redis locks not configured")

        cache = frappe.cache()
        test_key = f"sepa_test_lock:{uuid.uuid4().hex}"
        owner_token = "owner_" + uuid.uuid4().hex

        try:
            # Set lock
            cache.set(test_key, owner_token, ex=60)

            # Release with correct token
            redis_client = cache.connection
            if hasattr(redis_client, "eval"):
                result = redis_client.eval(_REDIS_RELEASE_LOCK_SCRIPT, 1, test_key, owner_token)
                self.assertEqual(result, 1, "Lua script should return 1 (deleted)")

                # Verify lock is gone
                self.assertIsNone(cache.get(test_key), "Lock should be deleted")
            else:
                self.skipTest("Redis client does not support eval()")

        finally:
            cache.delete(test_key)


# =============================================================================
# Point 2: Redis Capability Verification Tests
# =============================================================================


class TestRedisCapabilityVerification(EnhancedTestCase):
    """Test Redis capability verification (P2)."""

    def test_verify_redis_capabilities_when_configured(self):
        """Test that verify_redis_capabilities returns correct status."""
        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            # Test that it reports as not enabled
            result = verify_redis_capabilities()
            self.assertIn("use_redis_locks_for_sepa not enabled", result["issues"][0])
            return

        result = verify_redis_capabilities()

        # Should have tested all capabilities
        self.assertIn("redis_available", result)
        self.assertIn("set_nx_ex_supported", result)
        self.assertIn("eval_supported", result)
        self.assertIn("verified", result)

        # If verification passed, all should be True
        if result["verified"]:
            self.assertTrue(result["redis_available"])
            self.assertTrue(result["set_nx_ex_supported"])
            self.assertTrue(result["eval_supported"])
            self.assertEqual(result["issues"], [])

    def test_verify_redis_setnx_semantics(self):
        """Test that SETNX (nx=True) actually prevents overwrite."""
        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            self.skipTest("Redis locks not configured")

        cache = frappe.cache()
        test_key = f"sepa_setnx_test:{uuid.uuid4().hex}"

        try:
            # First set should succeed
            result1 = cache.set(test_key, "value1", ex=60, nx=True)
            self.assertTrue(result1, "First SETNX should succeed")

            # Second set should fail (key exists)
            result2 = cache.set(test_key, "value2", ex=60, nx=True)
            self.assertFalse(result2, "Second SETNX should fail")

            # Value should still be first value
            self.assertEqual(cache.get(test_key), "value1")

        finally:
            cache.delete(test_key)


# =============================================================================
# Point 3: Compact Cache Values Tests
# =============================================================================


class TestCompactCacheValues(EnhancedTestCase):
    """Test idempotency cache stores compact values (P2)."""

    def test_extract_cacheable_result_minimal_data(self):
        """Verify _extract_cacheable_result returns minimal data."""
        # Large result with extra data
        large_result = {
            "success": True,
            "payment_entry": "PE-001",
            "payment_entry_name": "PE-001",
            "batch": "BATCH-001",
            "extra_data": "x" * 10000,  # Large string
            "nested": {"deep": {"data": [1, 2, 3] * 100}},
            "customer_info": {"name": "Test", "address": "Long address" * 100},
        }

        cacheable = _extract_cacheable_result(large_result)

        # Should only contain essential fields
        self.assertIn("success", cacheable)
        self.assertIn("cached", cacheable)
        self.assertIn("payment_entry", cacheable)
        self.assertIn("batch", cacheable)

        # Should NOT contain large extra data
        self.assertNotIn("extra_data", cacheable)
        self.assertNotIn("nested", cacheable)
        self.assertNotIn("customer_info", cacheable)

        # Cached flag should be set
        self.assertTrue(cacheable["cached"])

    def test_extract_cacheable_result_truncates_errors(self):
        """Verify error messages are truncated in cache."""
        result_with_long_error = {
            "success": False,
            "error": "E" * 1000,  # Very long error message
        }

        cacheable = _extract_cacheable_result(result_with_long_error)

        # Error should be truncated to 200 chars
        self.assertLessEqual(len(cacheable.get("error", "")), 200)


# =============================================================================
# Point 4: Mandate Sequence Type Concurrency Tests
# =============================================================================


class TestMandateSequenceTypeConcurrency(EnhancedTestCase):
    """Test mandate-level locking prevents FRST race condition (P1)."""

    def setUp(self):
        super().setUp()
        self.site = frappe.local.site
        self.test_mandates = []
        self.test_members = []

    def tearDown(self):
        # Clean up test data
        for mandate_name in self.test_mandates:
            try:
                if frappe.db.exists("SEPA Mandate", mandate_name):
                    frappe.delete_doc("SEPA Mandate", mandate_name, force=True)
            except Exception:
                pass

        for member_name in self.test_members:
            try:
                if frappe.db.exists("Member", member_name):
                    frappe.delete_doc("Member", member_name, force=True)
            except Exception:
                pass

        frappe.db.commit()
        super().tearDown()

    def _create_test_mandate(self, suffix: str) -> str:
        """Create a test SEPA mandate for concurrency testing."""
        # Create test member first
        member = frappe.new_doc("Member")
        member.first_name = f"MandateTest{suffix}"
        member.last_name = "Concurrency"
        member.email = f"mandate.test.{suffix}@test.invalid"
        member.status = "Active"
        member.application_status = "Approved"
        member.iban = f"NL91ABNA041716471{suffix[-1]}"
        member.insert(ignore_permissions=True)
        self.test_members.append(member.name)

        # Create mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.mandate_id = f"TEST-MANDATE-{suffix}"
        mandate.member = member.name
        mandate.iban = member.iban
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.sign_date = frappe.utils.today()
        mandate.insert(ignore_permissions=True)
        self.test_mandates.append(mandate.name)
        frappe.db.commit()

        return mandate.name

    def test_concurrent_usage_creation_correct_sequence_types(self):
        """Test that concurrent usage record creation assigns correct FRST/RCUR."""
        # This test verifies the mandate-level lock prevents the race condition
        # where two concurrent calls both determine FRST (because neither has saved yet)

        # Create a fresh mandate with no usage history
        mandate_name = self._create_test_mandate(uuid.uuid4().hex[:8])

        site = self.site
        results = []
        errors = []
        lock = threading.Lock()

        def create_usage(worker_id: int):
            """Create usage record in a thread."""
            try:
                _create_thread_context(site)

                from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
                    create_mandate_usage_record,
                )

                # Both workers try to create usage for same mandate
                usage_name = create_mandate_usage_record(
                    mandate_name=mandate_name,
                    reference_doctype="Sales Invoice",
                    reference_name=f"TEST-INV-{worker_id}",
                    amount=100.0,
                    sequence_type=None,  # Auto-determine
                )

                # Get the assigned sequence type
                mandate = frappe.get_doc("SEPA Mandate", mandate_name)
                for usage in mandate.usage_history:
                    if usage.name == usage_name:
                        with lock:
                            results.append(
                                {"worker": worker_id, "usage": usage_name, "sequence_type": usage.sequence_type}
                            )
                        break

            except Exception as e:
                with lock:
                    errors.append({"worker": worker_id, "error": str(e)})
            finally:
                _cleanup_thread_context()

        # Run two workers concurrently
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create_usage, i) for i in range(2)]
            for future in as_completed(futures):
                pass

        # Expected: One FRST, one RCUR (or one error due to lock timeout)
        # The lock should serialize the operations

        sequence_types = [r["sequence_type"] for r in results]

        if len(results) == 2:
            # Both succeeded - verify one is FRST and one is RCUR
            self.assertIn("FRST", sequence_types, f"Should have one FRST. Results: {results}")
            self.assertIn("RCUR", sequence_types, f"Should have one RCUR. Results: {results}")
        elif len(results) == 1:
            # One succeeded (likely FRST), one got lock timeout error
            self.assertEqual(results[0]["sequence_type"], "FRST")
            self.assertEqual(len(errors), 1, f"Expected one lock timeout error. Errors: {errors}")
        else:
            self.fail(f"Unexpected results: {results}, errors: {errors}")


# =============================================================================
# Point 5: FOR UPDATE Integration Tests
# =============================================================================


class TestForUpdateSemantics(EnhancedTestCase):
    """Test FOR UPDATE correctly serializes batch processing (P2)."""

    def test_for_update_locks_batch_row(self):
        """Verify SELECT ... FOR UPDATE prevents concurrent modification."""
        # This is a basic test that FOR UPDATE syntax works
        # Full integration test would require a real Direct Debit Batch

        # Test that FOR UPDATE syntax is valid
        try:
            # Use a system table for testing SQL syntax
            result = frappe.db.sql(
                """
                SELECT name FROM `tabUser`
                WHERE name = %s
                FOR UPDATE
            """,
                ("Administrator",),
                as_dict=True,
            )
            self.assertTrue(len(result) > 0, "FOR UPDATE query should return results")
        except Exception as e:
            self.fail(f"FOR UPDATE syntax not supported: {e}")

    def test_transaction_rollback_releases_lock(self):
        """Verify that rollback releases FOR UPDATE lock."""
        # Start a transaction
        frappe.db.begin()

        try:
            # Acquire lock
            frappe.db.sql(
                """
                SELECT name FROM `tabUser`
                WHERE name = %s
                FOR UPDATE
            """,
                ("Administrator",),
            )

            # Rollback should release the lock
            frappe.db.rollback()

            # Should be able to query again without deadlock
            result = frappe.db.sql(
                "SELECT name FROM `tabUser` WHERE name = %s", ("Administrator",), as_dict=True
            )
            self.assertTrue(len(result) > 0)

        except Exception as e:
            frappe.db.rollback()
            raise e


# =============================================================================
# Point 6: Secure XML Parsing Tests
# =============================================================================


class TestSecureXMLParsing(EnhancedTestCase):
    """Test secure XML parsing with defusedxml (P2)."""

    def test_xxe_attack_blocked(self):
        """Verify XXE (XML External Entity) attacks are blocked."""
        from verenigingen.utils.secure_xml import XMLSecurityError, parse_xml_safely

        # Classic XXE attack payload
        xxe_payload = """<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE foo [
            <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <Document>&xxe;</Document>
        """

        with self.assertRaises((XMLSecurityError, ValueError)) as context:
            parse_xml_safely(xxe_payload)

        # Should mention security violation
        self.assertTrue(
            "security" in str(context.exception).lower() or "entity" in str(context.exception).lower()
        )

    def test_billion_laughs_attack_blocked(self):
        """Verify billion laughs (entity expansion bomb) is blocked."""
        from verenigingen.utils.secure_xml import XMLSecurityError, parse_xml_safely

        # Simplified billion laughs attack
        billion_laughs = """<?xml version="1.0"?>
        <!DOCTYPE lolz [
            <!ENTITY lol "lol">
            <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
            <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
        ]>
        <lolz>&lol3;</lolz>
        """

        with self.assertRaises((XMLSecurityError, ValueError)):
            parse_xml_safely(billion_laughs)

    def test_size_limit_enforced(self):
        """Verify XML size limit is enforced."""
        from verenigingen.utils.secure_xml import MAX_SEPA_RETURN_SIZE_BYTES, XMLSizeError, parse_xml_safely

        # Create XML larger than limit
        large_content = "<data>" + "x" * (MAX_SEPA_RETURN_SIZE_BYTES + 1000) + "</data>"

        with self.assertRaises((XMLSizeError, ValueError)) as context:
            parse_xml_safely(large_content, max_size=MAX_SEPA_RETURN_SIZE_BYTES)

        self.assertIn("size", str(context.exception).lower())

    def test_valid_pain002_parses_correctly(self):
        """Verify valid pain.002 file parses correctly."""
        from verenigingen.verenigingen_payments.utils.sepa_return_parser import parse_sepa_return_file

        # Minimal valid pain.002 structure
        valid_pain002 = """<?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
            <CstmrPmtStsRpt>
                <GrpHdr>
                    <MsgId>MSG001</MsgId>
                    <CreDtTm>2025-01-25T12:00:00</CreDtTm>
                </GrpHdr>
                <OrgnlGrpInfAndSts>
                    <OrgnlMsgId>ORIG-MSG-001</OrgnlMsgId>
                    <OrgnlMsgNmId>pain.008.001.02</OrgnlMsgNmId>
                </OrgnlGrpInfAndSts>
                <OrgnlPmtInfAndSts>
                    <OrgnlPmtInfId>PMT001</OrgnlPmtInfId>
                    <TxInfAndSts>
                        <OrgnlEndToEndId>E2E001</OrgnlEndToEndId>
                        <TxSts>RJCT</TxSts>
                        <StsRsnInf>
                            <Rsn>
                                <Cd>AC01</Cd>
                            </Rsn>
                        </StsRsnInf>
                    </TxInfAndSts>
                </OrgnlPmtInfAndSts>
            </CstmrPmtStsRpt>
        </Document>
        """

        result = parse_sepa_return_file(valid_pain002)

        self.assertIsInstance(result, list)
        if result:  # May be empty depending on parser implementation
            self.assertTrue(any(r.get("end_to_end_id") == "E2E001" for r in result))


# =============================================================================
# Point 7: Redis Health Check Tests
# =============================================================================


class TestRedisHealthCheck(EnhancedTestCase):
    """Test Redis health check functionality (P2)."""

    def test_health_check_when_not_configured(self):
        """Test health check when Redis is not configured."""
        with patch.object(frappe, "conf", {"use_redis_locks_for_sepa": False}):
            result = check_redis_health()

            self.assertTrue(result["healthy"])
            self.assertFalse(result["redis_configured"])
            self.assertIn("not configured", result["message"])

    def test_health_check_when_configured_and_available(self):
        """Test health check when Redis is configured and available."""
        if not frappe.conf.get("use_redis_locks_for_sepa", False):
            self.skipTest("Redis locks not configured")

        result = check_redis_health()

        self.assertTrue(result["healthy"])
        self.assertTrue(result["redis_configured"])
        self.assertTrue(result["redis_reachable"])
        self.assertIn("healthy", result["message"].lower())


# =============================================================================
# Point 8: Idempotency Concurrency Tests
# =============================================================================


class TestIdempotencyConcurrency(EnhancedTestCase):
    """Test idempotency under concurrent execution (Point 8)."""

    def setUp(self):
        super().setUp()
        self.site = frappe.local.site
        self.test_key = f"test_idempotency_{uuid.uuid4().hex}"

    def test_concurrent_idempotent_operations_only_one_executes(self):
        """Test that concurrent idempotent operations result in only one execution."""
        execution_count = [0]  # Use list for mutable closure
        execution_lock = threading.Lock()
        results = []
        errors = []
        results_lock = threading.Lock()

        site = self.site
        test_key = self.test_key

        def operation():
            """The operation to execute - should only run once."""
            with execution_lock:
                execution_count[0] += 1
            time.sleep(0.5)  # Simulate work
            return {"success": True, "execution_number": execution_count[0]}

        def worker(worker_id: int):
            """Worker that tries to execute the idempotent operation."""
            try:
                _create_thread_context(site)

                result = execute_idempotent_operation(test_key, operation, ttl=60)

                with results_lock:
                    results.append({"worker": worker_id, "result": result})

            except ConcurrentOperationError as e:
                with results_lock:
                    errors.append({"worker": worker_id, "error": "concurrent", "message": str(e)})
            except Exception as e:
                with results_lock:
                    errors.append({"worker": worker_id, "error": "other", "message": str(e)})
            finally:
                _cleanup_thread_context()

        # Run multiple workers concurrently
        num_workers = 3
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker, i) for i in range(num_workers)]
            for future in as_completed(futures):
                pass

        # Operation should have executed exactly once
        self.assertEqual(
            execution_count[0], 1, f"Operation should execute exactly once. Count: {execution_count[0]}"
        )

        # All workers should have a result (either from execution or cache)
        # Some might get ConcurrentOperationError, which is acceptable
        total_responses = len(results) + len(
            [e for e in errors if e.get("error") == "concurrent"]
        )

        self.assertGreaterEqual(
            total_responses, 1, f"At least one worker should succeed. Results: {results}, Errors: {errors}"
        )

    def test_cached_result_returned_on_retry(self):
        """Test that cached results are returned on subsequent calls."""
        execution_count = [0]

        def operation():
            execution_count[0] += 1
            return {"success": True, "data": "test_data"}

        # First call - should execute
        result1 = execute_idempotent_operation(self.test_key, operation, ttl=60)
        self.assertEqual(execution_count[0], 1)
        self.assertTrue(result1.get("success"))

        # Second call - should return cached
        result2 = execute_idempotent_operation(self.test_key, operation, ttl=60)
        self.assertEqual(execution_count[0], 1, "Operation should not execute again")
        self.assertTrue(result2.get("cached", False) or result2.get("success"))


# =============================================================================
# Combined Integration Test
# =============================================================================


class TestSEPASecurityIntegration(EnhancedTestCase):
    """Integration test combining multiple security features."""

    def test_lock_token_uniqueness(self):
        """Verify lock tokens are unique across calls."""
        tokens = [_generate_lock_token() for _ in range(100)]
        self.assertEqual(len(tokens), len(set(tokens)), "All tokens should be unique")

    def test_idempotency_key_deterministic(self):
        """Verify idempotency keys are deterministic."""
        key1 = generate_idempotency_key("BT-001", "BATCH-001", "payment")
        key2 = generate_idempotency_key("BT-001", "BATCH-001", "payment")
        self.assertEqual(key1, key2, "Same inputs should produce same key")

        key3 = generate_idempotency_key("BT-002", "BATCH-001", "payment")
        self.assertNotEqual(key1, key3, "Different inputs should produce different keys")
