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

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import sepa_xml_service


class TestStaffSubmitNotBlockedByCriticalGate(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._sepa = SEPATestDataFactory(seed=122411, use_faker=True)
        # Submitting dated invoices triggers eBoekhouden's benign FY auto-create log
        # on the shared test DB (same known test-artifact suppressed in
        # test_batch_processing_service_happy_path.py).
        self.expectErrorLog("Fiscal Year Auto-Creation Error")
        # on_submit's deferral path deliberately keeps an Error Log audit trail
        # (see direct_debit_batch.py on_submit) whenever generation is skipped.
        self.expectErrorLog("Direct Debit Batch SEPA Generation Deferred")

    def _make_draft_batch(self):
        # No explicit tearDown/commit/force-delete here (measured, #1224 review):
        # none of this module's tests reach a real accounting-commit boundary --
        # the Staff case is denied before generate_sepa_xml_for_batch ever runs,
        # the mocked case raises before it does any real work, and the control
        # never submits at all. So EnhancedTestCase's own captured-insert drain,
        # cleaned up by the standard FrappeTestCase rollback, already removes
        # everything created here. Measured directly: 0 leaked Member rows across
        # two clean runs of this module with no explicit commit, versus 2 leaked
        # rows (plus the drain's own lock-contention warning) when a
        # frappe.db.commit() was added to tearDown -- the commit converted rows
        # that would otherwise be rolled back into permanently committed orphans
        # whenever the drain's own delete happened to lose a row lock race. Adding
        # a commit here would be the same defect as #825/#933: this module's
        # scenario is not `test_batch_processing_service_happy_path.py`'s (real
        # Payment Entries / GL postings), so its "commit past the rollback"
        # justification does not transfer.
        return self._sepa.create_test_direct_debit_batch(batch_date=add_days(today(), 5), invoice_count=1)

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

    def test_non_auth_permission_error_is_not_misattributed_to_no_permission(self):
        """Review nit on #1224: api_security_framework's wrapper raises
        frappe.PermissionError from FOUR independent checks (validate_authentication,
        validate_ip_restrictions, validate_rate_limits, validate_request_method), not
        only a role/profile denial -- and generate_sepa_xml_for_batch's own body can
        also raise/wrap a PermissionError for a real, unrelated reason. on_submit
        must ask the AuthorizationEngine directly (via _can_clear_security_level)
        rather than catching broadly around the whole call, so ANY such failure for
        a user who genuinely holds CRITICAL still propagates as a real failure
        instead of being recorded as the false claim "{user} does not have
        permission".

        "Verenigingen Treasurer" is used here (not "Verenigingen Staff"): its Role
        Profile's own role list includes "Verenigingen Staff" (role_profile.json),
        so this user clears BOTH the DocType's submit permission AND the CRITICAL
        security level -- i.e. a genuinely AUTHORISED submitter. Faking
        generate_sepa_xml_for_batch's OWN result (not any validate_* method, and not
        generate_sepa_xml itself, which would also blind _can_clear_security_level
        to the real decorator's _security_level) keeps the decorator chain --
        including the authorisation check this test depends on -- completely real;
        only the wrapped function's own outcome is faked.
        """
        batch = self._make_draft_batch()

        with self.as_role("Verenigingen Treasurer"):
            batch.reload()
            with patch.object(
                sepa_xml_service,
                "generate_sepa_xml_for_batch",
                side_effect=frappe.PermissionError(
                    "Rate limit validation failed: simulated for #1224 review"
                ),
            ):
                with self.assertRaises(frappe.PermissionError) as ctx:
                    batch.submit()

        # The REAL cause must reach the caller -- not a silently-swallowed generic
        # "no permission" claim. (docstatus is not asserted here: on_submit runs
        # after _save()'s db_update(), so the in-transaction row already reads
        # docstatus=1 the instant the exception is raised, inside this FrappeTestCase
        # transaction that only rolls back at tearDown -- that reflects Frappe's own
        # save() ordering, not anything this fix controls, and asserting on it would
        # test that ordering rather than the misattribution this test targets.)
        self.assertIn(
            "rate limit",
            str(ctx.exception).lower(),
            "The genuine failure reason must propagate to the caller unchanged.",
        )

        batch.reload()
        self.assertNotIn(
            "does not have permission",
            (batch.batch_log or "").lower(),
            "A non-authorisation PermissionError for an AUTHORISED user must never "
            "be recorded as a false 'no permission' claim.",
        )
