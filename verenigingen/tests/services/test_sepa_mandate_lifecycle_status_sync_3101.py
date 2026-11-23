"""#3101: a failed member-link sync in the SEPA mandate lifecycle must be visible.

``SEPAMandateLifecycleService._update_member_mandate_status`` (activation / cancellation /
expiry sync, where ``Member SEPA Mandate Link.is_current`` is written) only called
``frappe.logger().warning`` when the integration step returned ``success: False``, and the
handlers then reported "Mandate activated successfully" with ``success: True``.

``is_current`` is NOT read by any mandate-resolution query (they filter on ``status``; see
``SEPAMandate`` docstring near the duplicate-mandate guard), so a stale flag does not by itself
mis-route a debit. The harm is a silent divergence the caller (the doc hooks, #2992) cannot see.
The fault is injected at the DB driver on ``UPDATE tabMember``, the same technique as #2992/#2869;
the integration service contains it and returns ``success: False`` (a real result, not a stub).
"""

from unittest.mock import patch

import frappe

from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban
from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
    SEPAMandateLifecycleService,
)

FAULT_TEXT = "injected at the driver 3101"
LIFECYCLE_TITLE = "SEPA Mandate Lifecycle"


class TestLifecycleStatusSyncFailure3101(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.service = SEPAMandateLifecycleService()
        self.member = self.create_test_member(
            first_name="Sync",
            last_name="Fail",
            birth_date="1990-01-01",
            email=f"sync.fail.{frappe.generate_hash(length=8)}@example.com",
        )
        mandate_id = f"M-3101-{frappe.generate_hash(length=8)}"
        result = get_sepa_mandate_manager().create_mandate(
            member=self.member.name,
            iban=generate_test_iban("RABO", "0123456789"),
            account_holder_name="Sync Fail",
            mandate_id=mandate_id,
        )
        self.assertTrue(result.valid, result.message)
        self.mandate = frappe.get_doc("SEPA Mandate", {"mandate_id": mandate_id})

    def _driver_fails_member_update_3101(self):
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute

        def execute(cursor, query, *args, **kwargs):
            if (
                isinstance(query, str)
                and query.lstrip().upper().startswith("UPDATE")
                and "`tabMember`" in query
            ):
                raise frappe.db.OperationalError(1064, FAULT_TEXT)
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; calls through for every other statement
        return patch.object(cursor_cls, "execute", execute)

    def _lifecycle_rows(self):
        return frappe.db.count(
            "Error Log",
            {"method": LIFECYCLE_TITLE, "error": ["like", f"%{self.mandate.name}%"]},
        )

    def _expect_logs(self):
        self.expectErrorLog("SEPA Mandate Member Integration Error", LIFECYCLE_TITLE)

    # -- _update_member_mandate_status -------------------------------------------------

    def test_a_failed_integration_step_is_returned_and_written_to_the_error_log(self):
        self._expect_logs()
        before = self._lifecycle_rows()
        with self._driver_fails_member_update_3101():
            errors = self.service._update_member_mandate_status(self.mandate, "Active")
        self.assertTrue(any(FAULT_TEXT in e for e in errors), errors)
        self.assertEqual(self._lifecycle_rows(), before + 1)

    def test_an_exception_escaping_the_integration_step_is_returned_too(self):
        """A ValidationError (child-table path) takes the except branch; same contract."""
        self._expect_logs()
        from verenigingen.verenigingen_payments.services.sepa_mandate_member_integration_service import (
            sepa_mandate_member_integration_service as integration,
        )

        def boom(*args, **kwargs):
            raise frappe.ValidationError("link sync refused 3101")

        before = self._lifecycle_rows()
        # Mock justified: the integration service contains every Exception itself, so the
        # lifecycle layer's own except is only reachable by raising past it.
        with patch.object(integration, "update_member_mandate_relationship", boom):
            errors = self.service._update_member_mandate_status(self.mandate, "Active")
        self.assertTrue(any("link sync refused 3101" in e for e in errors), errors)
        self.assertEqual(self._lifecycle_rows(), before + 1)

    def test_control_a_clean_sync_returns_no_errors_and_writes_no_row(self):
        before = self._lifecycle_rows()
        self.assertEqual(self.service._update_member_mandate_status(self.mandate, "Active"), [])
        self.assertEqual(self._lifecycle_rows(), before)

    # -- the handlers must not report success ------------------------------------------

    def test_activation_reports_failure(self):
        self._expect_logs()
        self.mandate.status = "Active"
        with self._driver_fails_member_update_3101():
            result = self.service.handle_status_transition(self.mandate, "Draft")
        self.assertFalse(result["success"])
        self.assertTrue(any(FAULT_TEXT in e for e in result["errors"]), result)
        self.assertNotIn("Mandate activated successfully", result["warnings"])

    def test_expiration_reports_failure(self):
        self._expect_logs()
        self.mandate.status = "Expired"
        with self._driver_fails_member_update_3101():
            result = self.service.handle_status_transition(self.mandate, "Active")
        self.assertFalse(result["success"])
        self.assertTrue(any(FAULT_TEXT in e for e in result["errors"]), result)

    def test_cancellation_via_the_transition_reports_failure(self):
        self._expect_logs()
        self.mandate.status = "Cancelled"
        # A plain attribute, as process_mandate_cancellation sets it: the field is really
        # `cancelled_date` (#2989), which is a separate defect.
        self.mandate.cancellation_date = frappe.utils.today()
        with self._driver_fails_member_update_3101():
            result = self.service.handle_status_transition(self.mandate, "Active")
        self.assertFalse(result["success"])
        self.assertTrue(any(FAULT_TEXT in e for e in result["errors"]), result)

    def test_process_mandate_cancellation_reports_failure(self):
        self._expect_logs()
        with self._driver_fails_member_update_3101():
            result = self.service.process_mandate_cancellation(self.mandate)
        # (its notification step also fails today for an unrelated reason, #2989)
        self.assertFalse(result["success"])
        self.assertTrue(any(FAULT_TEXT in e for e in result["errors"]), result)
        self.assertNotIn("Mandate cancelled successfully", result["warnings"])

    def test_control_clean_transitions_still_succeed(self):
        self.mandate.status = "Active"
        result = self.service.handle_status_transition(self.mandate, "Draft")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["errors"], [])
        self.assertIn("Mandate activated successfully", result["warnings"])

    # -- the doc-hook entry points: errors present => success must be False -----------

    def test_handle_mandate_update_reports_a_status_sync_failure(self):
        self._expect_logs()
        self.mandate.status = "Cancelled"
        self.mandate.cancellation_date = frappe.utils.today()  # plain attribute, see #2989
        self.mandate.load_doc_before_save()
        self.mandate._doc_before_save.status = "Active"
        with self._driver_fails_member_update_3101():
            result = self.service.handle_mandate_update(self.mandate)
        self.assertTrue(any(FAULT_TEXT in e for e in result["errors"]), result)
        self.assertFalse(result["success"], "errors present but success True: the hook never msgprints")

    def test_handle_mandate_update_reports_a_failed_link_write_without_a_status_change(self):
        self._expect_logs()
        self.mandate.load_doc_before_save()
        with self._driver_fails_member_update_3101():
            result = self.service.handle_mandate_update(self.mandate)
        self.assertTrue(any(FAULT_TEXT in e for e in result["errors"]), result)
        self.assertFalse(result["success"])

    def test_handle_mandate_creation_reports_a_failed_link_write(self):
        self._expect_logs()
        with self._driver_fails_member_update_3101():
            result = self.service.handle_mandate_creation(self.mandate)
        self.assertTrue(any(FAULT_TEXT in e for e in result["errors"]), result)
        self.assertFalse(result["success"])
