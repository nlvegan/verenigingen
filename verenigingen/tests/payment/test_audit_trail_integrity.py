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

    def test_verify_integrity_ignores_non_chain_entries(self):
        """Standalone Mollie Audit Log entries (no chain linkage) must not break verification."""
        start = add_to_date(now_datetime(), seconds=-1)
        trail = ImmutableAuditTrail()
        self._log_and_flush(trail, n=2)

        # Insert a standalone entry the way mollie/utils/audit.py does:
        # event_data WITHOUT a previous_hash marker, no chain participation.
        other = frappe.new_doc("Mollie Audit Log")
        other.event_type = "webhook_validation"
        other.event_category = "Security"
        other.description = "standalone non-chain entry"
        other.event_data = json.dumps({"foo": "bar"})
        other.severity = "info"
        other.timestamp = now_datetime()
        other.user = "Administrator"
        other.insert(ignore_permissions=True)

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
            decoy = frappe.new_doc("Mollie Audit Log")
            decoy.event_type = "webhook_validation"
            decoy.description = f"decoy {i}"
            decoy.event_data = json.dumps({"previous_hash": "deadbeef", "n": i})
            decoy.severity = "info"
            decoy.timestamp = now_datetime()
            decoy.user = "Administrator"
            decoy.insert(ignore_permissions=True)

        fresh = ImmutableAuditTrail()
        self.assertEqual(fresh._get_last_hash(), tail_hash)
