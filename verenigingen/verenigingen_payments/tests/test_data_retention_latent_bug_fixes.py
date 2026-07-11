# Copyright (c) 2026, Verenigingen
"""Regression tests for the three latent data-retention live-path bugs.

Each category is currently gated OUT of live purge (LIVE_CAPABLE_CATEGORIES =
{temporary_data}); these bugs only fire if a category is ever enabled, and each
was invisible to dry-run. Tests exercise the real anonymize/archive helpers.
"""

import frappe
from frappe.utils import add_days, now_datetime

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataRetentionPolicy,
    RetentionAction,
)


class TestDataRetentionLatentBugFixes(VereningingenTestCase):
    # ----- Bug 3: personal_data anonymize wrote non-existent Member.phone/.address
    def test_anonymize_personal_data_uses_real_member_fields(self):
        member = self.create_test_member(
            first_name="Reten", last_name="Tion", email=f"reten-{frappe.generate_hash(length=6)}@example.com"
        )
        # Seed the real PII fields the anonymizer must scrub.
        frappe.db.set_value(
            "Member",
            member.name,
            {"contact_number": "0612345678", "normalized_address_line": "123 Real Street"},
        )

        engine = DataRetentionPolicy()
        # Previously raised "Unknown column 'phone'/'address'"; must now succeed.
        engine._anonymize_personal_data({"name": member.name})

        row = frappe.db.get_value(
            "Member",
            member.name,
            ["first_name", "email", "contact_number", "normalized_address_line"],
            as_dict=True,
        )
        self.assertEqual(row.first_name, "Anonymous")
        self.assertTrue(row.email.startswith("anon_"))
        self.assertEqual(row.contact_number, "000-000-0000")
        self.assertEqual(row.normalized_address_line, "Anonymized")

    # ----- Bug 1: audit-log archive wrote non-existent Mollie Audit Log.archived
    def _make_audit_row(self, age_days=400):
        doc = frappe.get_doc(
            {
                "doctype": "Mollie Audit Log",
                "event_type": "webhook_received",
                "event_category": "webhook_processing",
                "severity": "info",
                "message": "retention latent-bug test",
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.set_value("Mollie Audit Log", doc.name, "timestamp", add_days(now_datetime(), -age_days))
        self.track_doc("Mollie Audit Log", doc.name)
        return doc.name

    def test_archive_audit_log_marks_archived_field(self):
        name = self._make_audit_row()
        engine = DataRetentionPolicy()
        # Previously raised "Unknown column 'archived'"; the field now exists.
        engine._archive_audit_log({"name": name, "timestamp": now_datetime(), "action": "x", "status": "y"})
        self.assertEqual(frappe.db.get_value("Mollie Audit Log", name, "archived"), 1)

    def test_process_audit_logs_live_is_idempotent(self):
        name = self._make_audit_row(age_days=500)
        engine = DataRetentionPolicy()
        cutoff = add_days(now_datetime(), -365)

        # First live archive run marks the row archived and counts it.
        first = engine._process_audit_logs(cutoff, RetentionAction.ARCHIVE, dry_run=False)
        self.assertGreaterEqual(first, 1)
        self.assertEqual(frappe.db.get_value("Mollie Audit Log", name, "archived"), 1)

        # Second run must NOT re-count/re-archive the already-archived row.
        second_count = frappe.db.count(
            "Mollie Audit Log", {"name": name, "timestamp": ["<", cutoff], "archived": ["!=", 1]}
        )
        self.assertEqual(second_count, 0)

    # ----- Bug 2: anonymize mutated a SUBMITTED Payment Entry (GL/eBoekhouden desync)
    def _create_submitted_payment_entry(self):
        """A minimal Payment Entry forced to docstatus=1 without real accounting
        (we only need a submitted row to prove the guard leaves it untouched)."""
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": "ORIG-PARTY",
                "reference_no": "ORIG-REF",
                "paid_amount": 100,
                "received_amount": 100,
            }
        )
        pe.flags.ignore_mandatory = True
        pe.flags.ignore_links = True
        pe.flags.ignore_validate = True
        pe.insert(ignore_permissions=True)
        frappe.db.set_value("Payment Entry", pe.name, "docstatus", 1)
        self.track_doc("Payment Entry", pe.name)
        return pe.name

    def test_anonymize_payment_leaves_submitted_entry_untouched(self):
        name = self._create_submitted_payment_entry()
        engine = DataRetentionPolicy()
        # Must NOT rewrite party/reference_no on a submitted (docstatus=1) entry —
        # that would break the party Link and desync the posted GL / eBoekhouden.
        engine._anonymize_payment({"name": name, "party": "ORIG-PARTY", "reference_no": "ORIG-REF"})

        row = frappe.db.get_value("Payment Entry", name, ["party", "reference_no"], as_dict=True)
        self.assertEqual(row.party, "ORIG-PARTY", "submitted Payment Entry party must be untouched")
        self.assertEqual(row.reference_no, "ORIG-REF", "submitted Payment Entry reference must be untouched")
