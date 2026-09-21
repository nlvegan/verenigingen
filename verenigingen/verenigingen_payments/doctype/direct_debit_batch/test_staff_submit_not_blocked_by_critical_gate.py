"""
Regression coverage for #1224.

DirectDebitBatch.on_submit() calls self.generate_sepa_xml(), which carries
@critical_api(OperationType.FINANCIAL) (CRITICAL). In this app security
decorators run on INTERNAL calls too (only whitelist *dispatch* is
entry-point-only), so an ordinary doc.submit() by a "Verenigingen Staff" user
hit the CRITICAL gate and aborted the whole submit -- even though the DocType
itself grants Staff `submit: 1`. Per ROLE_PROFILE_SECURITY_MAPPING
(authorization_policy.py), CRITICAL access is deliberately reserved for a
Treasurer/National-Board/Admin Role Profile and is NEVER granted to the
Staff profile -- and the live approval workflow
(dd_batch_workflow_controller.trigger_sepa_generation) separately restricts
real SEPA generation to Financial Manager/System Manager even for an
Approved batch. So the fix does not lift Staff's authority over the CRITICAL
financial operation (that would be a real privilege expansion this evidence
argues against) -- it makes submission itself tolerate the denial: the doc
still submits, generation is deferred, and the existing "Generate SEPA File"
button (docstatus==1 and not sepa_file_generated) is what a privileged user
uses to finish the job.

Run:
  cd ~/frappe-bench && PYTHONPATH=<worktree> bench --site test_site_3 run-tests \
    --app verenigingen --module verenigingen.verenigingen_payments.doctype.direct_debit_batch.test_staff_submit_not_blocked_by_critical_gate
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory


class TestStaffSubmitNotBlockedByCriticalGate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._sepa = SEPATestDataFactory(seed=122411, use_faker=True)
        self._committed = []
        # Submitting dated invoices triggers eBoekhouden's benign FY auto-create log
        # on the shared test DB (same known test-artifact suppressed in
        # test_batch_processing_service_happy_path.py).
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

    def tearDown(self):
        # Submitted batches / their invoices can commit past the FrappeTestCase
        # rollback (see test_batch_processing_service_happy_path.py); force-delete
        # anything this test actually committed.
        for doctype, name in reversed(self._committed):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _make_draft_batch(self):
        batch = self._sepa.create_test_direct_debit_batch(batch_date=add_days(today(), 5), invoice_count=1)
        # Submitted batches can commit past the FrappeTestCase rollback (see
        # test_batch_processing_service_happy_path.py); track for force-delete.
        self._committed.append(("Direct Debit Batch", batch.name))
        return batch

    def test_staff_submit_succeeds_and_defers_sepa_generation(self):
        """The core defect: a Staff-only user's ordinary Submit action must not
        be aborted by the internal CRITICAL check on generate_sepa_xml()."""
        batch = self._make_draft_batch()

        with self.as_role("Verenigingen Staff"):
            batch.reload()
            batch.submit()  # must NOT raise

        batch.reload()
        self.assertEqual(batch.docstatus, 1, "Staff submit must actually commit docstatus=1")
        self.assertFalse(
            batch.sepa_file_generated,
            "Staff cannot clear the CRITICAL gate, so the file must not be generated "
            "under their authority -- it must stay pending for a privileged user.",
        )
        self.assertIn(
            "permission",
            (batch.batch_log or "").lower(),
            "The deferral must be recorded on the batch so an operator can see why " "the file is missing.",
        )

    def test_generate_sepa_xml_endpoint_still_denied_to_staff(self):
        """Control: proves we removed the double-gating on the LIFECYCLE HOOK, not
        the CRITICAL gate itself -- the external generate_sepa_xml() endpoint must
        remain exactly as restricted for a direct/API-style call."""
        batch = self._make_draft_batch()

        with self.as_role("Verenigingen Staff"):
            batch.reload()
            with self.assertRaises(frappe.PermissionError):
                batch.generate_sepa_xml()
