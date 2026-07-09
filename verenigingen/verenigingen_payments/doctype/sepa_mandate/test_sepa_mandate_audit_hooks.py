# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""Tests for the SEPA Mandate audit-trail doc_events hooks.

These verify that creating and changing the status of a SEPA Mandate writes the
expected SEPAAuditLog entries automatically, and that an unrelated save does not
emit a spurious status-change entry.
"""

import json

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSEPAMandateAuditHooks(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.create_test_member()

    def _mandate_audit_rows(self, mandate_name, action=None):
        filters = {"reference_doctype": "SEPA Mandate", "reference_name": mandate_name}
        if action:
            filters["action"] = action
        return frappe.get_all(
            "SEPA Audit Log",
            filters=filters,
            fields=["name", "process_type", "action", "details", "sensitive_data"],
            order_by="creation asc",
        )

    def _insert_mandate_ignoring_perms(self, **overrides):
        """Insert a SEPA Mandate as fixture data, bypassing DocPerm. Used to simulate
        a non-privileged actor creating a mandate: the mandate insert itself is
        permission-bypassed, while its after_insert audit hook still runs under the
        (unprivileged) session user set by the caller."""
        payload = {
            "doctype": "SEPA Mandate",
            "member": self.member.name,
            "iban": "NL91ABNA0417164300",
            "mandate_id": f"MC{frappe.generate_hash(length=8)}",
            "status": "Active",
            "mandate_type": "RCUR",
            "scheme": "SEPA",
            "account_holder_name": "Self Service Member",
            "sign_date": frappe.utils.today(),
        }
        payload.update(overrides)
        mandate = frappe.get_doc(payload).insert(ignore_permissions=True)
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate

    def test_mandate_creation_is_audit_logged(self):
        """Creating a SEPA Mandate emits a 'mandate_created' audit entry with a
        masked IBAN, linked back to the mandate."""
        mandate = self.create_test_sepa_mandate(member=self.member.name)
        actual_iban = mandate.iban  # the factory generates its own valid test IBAN

        rows = self._mandate_audit_rows(mandate.name, action="mandate_created")
        self.assertEqual(len(rows), 1, "exactly one mandate_created audit entry expected")
        row = rows[0]
        self.assertEqual(row["process_type"], "Mandate Creation")
        self.assertTrue(row["sensitive_data"])

        details = json.loads(row["details"])
        # GDPR: the raw IBAN must never be stored in cleartext.
        self.assertNotIn(actual_iban, row["details"])
        expected_mask = actual_iban[:4] + "****" + actual_iban[-4:]
        self.assertEqual(details["iban_masked"], expected_mask)
        self.assertEqual(details["member"], self.member.name)

    def test_mandate_status_change_is_audit_logged(self):
        """Changing a mandate's status emits a 'mandate_status_changed' audit entry
        recording the previous and new status."""
        mandate = self.create_test_sepa_mandate(member=self.member.name)
        self.assertEqual(mandate.status, "Active")

        mandate.status = "Cancelled"
        mandate.save()

        rows = self._mandate_audit_rows(mandate.name, action="mandate_status_changed")
        self.assertEqual(len(rows), 1, "exactly one status-change audit entry expected")
        details = json.loads(rows[0]["details"])
        self.assertEqual(details["previous_status"], "Active")
        self.assertEqual(details["new_status"], "Cancelled")

    def test_audit_logged_for_non_privileged_creator(self):
        """The compliance trail must capture mandate creation even when the acting
        user has no 'SEPA Audit Log:create' grant (e.g. a member creating a mandate
        via self-service). Regression guard for the system-level audit write."""
        # Creating a mandate under an unprivileged session makes a separate Member <->
        # SEPA Mandate link integration log a swallowed "Insufficient permissions"
        # Error Log row (pre-existing, unrelated to the audit trail under test). Mark it
        # expected so the ErrorLogGuardMixin tearDown check stays quiet.
        self.expectErrorLog("Insufficient permissions to update SEPA mandate")

        member_user = self.create_test_user(
            email=f"mand-actor-{frappe.generate_hash(length=6)}@example.com",
            roles=["Verenigingen Member"],
        )
        original_user = frappe.session.user
        try:
            frappe.set_user(member_user.name)
            self.assertFalse(
                frappe.has_permission("SEPA Audit Log", "create"),
                "precondition: a plain member must not hold SEPA Audit Log:create",
            )
            mandate = self._insert_mandate_ignoring_perms()
        finally:
            frappe.set_user(original_user)

        rows = self._mandate_audit_rows(mandate.name, action="mandate_created")
        self.assertEqual(len(rows), 1, "mandate creation must be audited even for a non-privileged actor")

    def test_save_without_status_change_does_not_log(self):
        """A save that does not change status must not emit a status-change entry
        (guards the has-value-changed check against spurious audit noise)."""
        mandate = self.create_test_sepa_mandate(member=self.member.name)

        # Touch a non-status field and save.
        mandate.account_holder_name = (mandate.account_holder_name or "Holder") + " Jr"
        mandate.save()

        rows = self._mandate_audit_rows(mandate.name, action="mandate_status_changed")
        self.assertEqual(len(rows), 0, "no status-change entry expected when status is unchanged")
