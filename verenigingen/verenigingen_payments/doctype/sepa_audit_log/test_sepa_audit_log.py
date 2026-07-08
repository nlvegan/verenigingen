# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import json

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.doctype.sepa_audit_log.sepa_audit_log import SEPAAuditLog


class TestSEPAAuditLog(EnhancedTestCase):
    """Test SEPA Audit Log business logic validation"""

    def setUp(self):
        super().setUp()
        self.test_member = self.create_test_member()

    def test_log_mandate_creation_masks_iban_and_links_reference(self):
        """log_mandate_creation() must create a real, linked audit entry with a
        masked IBAN (never store the raw IBAN in cleartext audit details)."""
        audit_log = SEPAAuditLog.log_mandate_creation(
            member=self.test_member,
            mandate=None,
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            success=True,
        )

        self.assertIsNotNone(audit_log, "log_mandate_creation should return the created audit log")
        self.assertTrue(frappe.db.exists("SEPA Audit Log", audit_log.name))

        # Reference linking to the source document.
        self.assertEqual(audit_log.reference_doctype, "Member")
        self.assertEqual(audit_log.reference_name, self.test_member.name)

        # Compliance status and event_id are populated by before_insert()/validate().
        self.assertEqual(audit_log.compliance_status, "Compliant")
        self.assertIsNotNone(audit_log.event_id)
        self.assertEqual(len(audit_log.event_id), 12)

        # The raw IBAN must never appear in the stored details JSON (GDPR masking).
        details = json.loads(audit_log.details)
        self.assertNotIn("NL91ABNA0417164300", audit_log.details)
        self.assertEqual(details["iban_masked"], "NL91****4300")

    def test_invalid_compliance_status_raises_validation_error(self):
        """validate() must reject a compliance_status outside the approved
        regulatory values instead of silently accepting it."""
        doc = frappe.new_doc("SEPA Audit Log")
        doc.process_type = "Mandate Creation"
        doc.action = "mandate_created"
        doc.compliance_status = "Not A Real Status"

        with self.assertRaises(frappe.ValidationError):
            doc.insert()
