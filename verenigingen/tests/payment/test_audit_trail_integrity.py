"""
ImmutableAuditTrail.verify_integrity coverage.

The Mollie Audit Log table is a shared sink: ImmutableAuditTrail writes
cryptographically chained entries (event_data carries `sequence` + `previous_hash`),
while other writers (mollie security manager, mollie/utils/audit.py) write
standalone entries with no chain linkage. verify_integrity must verify the
chain it created and ignore the unrelated entries — without querying
`previous_hash`/`sequence` as columns (they live inside event_data JSON).
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.core.compliance.audit_trail import (
    AuditEventType,
    AuditSeverity,
    ImmutableAuditTrail,
)


class TestAuditTrailIntegrity(EnhancedTestCase):
    """Tests for ImmutableAuditTrail chain integrity verification."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _log_and_flush(self, trail, n=3):
        """Log n events through the trail and flush them to the DB."""
        for i in range(n):
            trail.log_event(
                AuditEventType.PAYMENT_CREATED,
                AuditSeverity.INFO,
                f"integrity test event {i}",
            )
        trail._flush_buffer()

    def test_log_event_redacts_sensitive_details(self):
        """log_event must redact secrets/PII in the details payload before the entry
        is hashed and persisted, so credentials and bank/card data never reach the
        Mollie Audit Log. Non-sensitive fields are preserved and the caller's dict is
        not mutated. Recurses into nested dicts and lists."""
        trail = ImmutableAuditTrail()
        original = {
            "api_key": "sk_live_secret",
            "password": "hunter2",
            "iban": "NL02ABNA0123456789",
            "credit_card": "4111111111111111",
            "amount": 50.0,
            "nested": {"access_token": "tok-123", "status": "paid"},
            "items": [{"secret": "x", "label": "ok"}],
        }
        trail.log_event(
            AuditEventType.PAYMENT_CREATED, AuditSeverity.INFO, "redaction test", details=original
        )
        stored = trail.buffer[-1]["details"]

        # Secrets / PII redacted (including nested dict + list-of-dict).
        for path in (
            stored["api_key"],
            stored["password"],
            stored["iban"],
            stored["credit_card"],
            stored["nested"]["access_token"],
            stored["items"][0]["secret"],
        ):
            self.assertEqual(path, trail._REDACTED)

        # Non-sensitive values preserved.
        self.assertEqual(stored["amount"], 50.0)
        self.assertEqual(stored["nested"]["status"], "paid")
        self.assertEqual(stored["items"][0]["label"], "ok")

        # The caller's original dict must NOT be mutated.
        self.assertEqual(original["api_key"], "sk_live_secret")

    def test_verify_integrity_valid_chain(self):
        """A freshly written chain should verify as valid (no crash, no errors)."""
        start = add_to_date(now_datetime(), seconds=-1)
        trail = ImmutableAuditTrail()
        self._log_and_flush(trail, n=3)

        is_valid, errors = trail.verify_integrity(start_date=start)

        self.assertTrue(is_valid, f"expected valid chain, got errors: {errors}")
        self.assertEqual(errors, [])

    def test_verify_integrity_detects_tampering(self):
        """Direct DB modification of a chained entry must be detected."""
        start = add_to_date(now_datetime(), seconds=-1)
        trail = ImmutableAuditTrail()
        self._log_and_flush(trail, n=3)

        # Tamper with the most recent entry's description (a hashed field),
        # bypassing the DocType immutability guard via direct DB write.
        victim = frappe.get_all(
            "Mollie Audit Log",
            filters={"timestamp": [">=", start]},
            fields=["name"],
            order_by="creation desc",
            limit=1,
        )[0]["name"]
        frappe.db.set_value("Mollie Audit Log", victim, "description", "TAMPERED", update_modified=False)

        is_valid, errors = trail.verify_integrity(start_date=start)

        self.assertFalse(is_valid)
        self.assertTrue(errors)

    def _make_audit_log_entry(self, **fields):
        """Factory helper: insert a standalone (non-chain) Mollie Audit Log entry for
        test scenarios. ignore_permissions is confined to this factory method (per the
        test-quality standard) rather than being scattered through test bodies."""
        entry = frappe.new_doc("Mollie Audit Log")
        entry.update(fields)
        entry.insert(ignore_permissions=True)
        return entry

    def test_verify_integrity_ignores_non_chain_entries(self):
        """Standalone Mollie Audit Log entries (no chain linkage) must not break verification."""
        start = add_to_date(now_datetime(), seconds=-1)
        trail = ImmutableAuditTrail()
        self._log_and_flush(trail, n=2)

        # Insert a standalone entry the way mollie/utils/audit.py does:
        # event_data WITHOUT a previous_hash marker, no chain participation.
        self._make_audit_log_entry(
            event_type="webhook_validation",
            event_category="Security",
            description="standalone non-chain entry",
            event_data=json.dumps({"foo": "bar"}),
            severity="info",
            timestamp=now_datetime(),
            user="Administrator",
        )

        # Log one more chained event after the interloper.
        self._log_and_flush(trail, n=1)

        is_valid, errors = trail.verify_integrity(start_date=start)

        self.assertTrue(is_valid, f"non-chain entry broke verification: {errors}")
        self.assertEqual(errors, [])

    def test_get_last_hash_survives_decoy_overflow(self):
        """A flood of non-chain entries that merely contain a 'previous_hash' key
        must not bury the real chain tail — otherwise a fresh trail forks the
        chain and verification false-alarms with 'chain broken'."""
        trail = ImmutableAuditTrail()
        self._log_and_flush(trail, n=2)
        tail_hash = trail.last_hash  # most recent chain entry's hash after flush

        # Flood with more decoys than any fixed scan window: event_data carries a
        # "previous_hash" key but no "sequence", so it is NOT a chain entry
        # (writer #3 / mollie/utils/audit.py serializes arbitrary caller data).
        for i in range(25):
            self._make_audit_log_entry(
                event_type="webhook_validation",
                description=f"decoy {i}",
                event_data=json.dumps({"previous_hash": "deadbeef", "n": i}),
                severity="info",
                timestamp=now_datetime(),
                user="Administrator",
            )

        fresh = ImmutableAuditTrail()
        self.assertEqual(fresh._get_last_hash(), tail_hash)
