"""Real-DB integration coverage for the SEPA mandate-lifecycle / retry / rollback
cluster and the SEPA Mandate Issues report.

CLUSTER 3 targets:
- verenigingen_payments/report/sepa_mandate_issues/sepa_mandate_issues.py
- verenigingen_payments/services/sepa_mandate_lifecycle_service.py
- verenigingen_payments/doctype/sepa_retry_batch/sepa_retry_batch.py
- verenigingen_payments/doctype/sepa_retry_operation/sepa_retry_operation.py
- verenigingen_payments/utils/sepa_rollback_manager.py

Design notes / hard-constraint compliance:
- No business-logic mocking. The notification/email boundary is the only external
  side effect; it is left to run (it logs a warning at most) rather than mocked.
- Tests run as Administrator (no ignore_permissions in test logic).
- The report's get_data() calls the SITE-WIDE diagnostics query get_mandate_issues(),
  so on the shared CI DB it also returns sibling tests' rows. Every report
  assertion therefore filters to THIS test's own member ids and never asserts a
  global total.
- The lifecycle service operates on real SEPA Mandate documents (the existing
  test_sepa_mandate_lifecycle_service.py drives it with Mock objects). These tests
  drive the same methods against real persisted docs to cover the genuine DB paths
  (member-integration updates, status sync after save) that mocked mandates skip.
- SEPA Retry Batch is submittable and on_submit calls save() (committing past the
  test transaction is avoided because FrappeTestCase wraps each test; submitted
  docs are tracked and force-deleted in tearDown to keep the shared shards clean).
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.report.sepa_mandate_issues import sepa_mandate_issues as report
from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
    SEPAMandateLifecycleService,
)


class TestSEPAMandateIssuesReport(EnhancedTestCase):
    """Real-DB coverage for the SEPA Mandate Issues query report (was 0%)."""

    def setUp(self):
        super().setUp()
        self.service = SEPAMandateLifecycleService()

    # ---- get_columns: every issue-type branch + default ----
    def test_get_columns_default_has_details(self):
        cols = report.get_columns(None)
        fieldnames = [c["fieldname"] for c in cols]
        self.assertIn("member_id", fieldnames)
        self.assertIn("severity", fieldnames)
        # No filter -> the generic "details" column is appended.
        self.assertIn("details", fieldnames)

    def test_get_columns_per_issue_type(self):
        expected_extra = {
            "multiple_current_mandates": ["current_count", "mandate_ids"],
            "mandate_member_data_mismatch": [
                "mandate_id",
                "mismatch_type",
                "member_iban",
                "mandate_iban",
            ],
            "sepa_selected_no_mandate": ["payment_method", "iban", "banking_status"],
            "missing_child_table_entries": ["mandate_count", "mandate_ids"],
            "orphaned_child_table_entries": ["mandate_name", "mandate_reference"],
            "outdated_child_table_data": ["mandate_id", "current_status", "child_table_status"],
        }
        for issue_type, extras in expected_extra.items():
            with self.subTest(issue_type=issue_type):
                cols = report.get_columns({"issue_type": issue_type})
                fieldnames = [c["fieldname"] for c in cols]
                for extra in extras:
                    self.assertIn(extra, fieldnames)
                # Issue-type-specific columns replace the generic "details" column.
                self.assertNotIn("details", fieldnames)

    # ---- sepa_selected_no_mandate: critical issue, full execute() path ----
    def test_execute_sepa_selected_no_mandate(self):
        """Member with SEPA payment method but no active mandate and no banking
        data surfaces in the critical 'sepa_selected_no_mandate' category."""
        member = self.create_test_member()
        # SEPA Direct Debit selected, but IBAN/account holder blank and no mandate.
        frappe.db.set_value(
            "Member",
            member.name,
            {"payment_method": "SEPA Direct Debit", "iban": "", "bank_account_name": ""},
            update_modified=False,
        )

        columns, data, _msg, chart, summary = report.execute({"issue_type": "sepa_selected_no_mandate"})

        my_rows = [r for r in data if r["member_id"] == member.name]
        self.assertEqual(len(my_rows), 1, "member should appear exactly once")
        row = my_rows[0]
        self.assertEqual(row["severity"], "critical")
        self.assertEqual(row["total_mandates"], 0)
        self.assertEqual(row["active_mandates"], 0)
        # banking_status formatted via _format_banking_status (missing IBAN).
        self.assertEqual(row["banking_status"], "Missing IBAN")
        # Columns reflect the filtered issue type.
        self.assertIn("banking_status", [c["fieldname"] for c in columns])
        # Summary + chart are built from the same (non-empty) data set.
        self.assertGreaterEqual(summary[0]["value"], 1)
        self.assertEqual(summary[0]["label"], "Total Issues")
        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "bar")

    def test_execute_sepa_selected_missing_account_name_banking_status(self):
        """IBAN present but account holder blank -> 'Missing Account Name'."""
        member = self.create_test_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "payment_method": "SEPA Direct Debit",
                "iban": "NL02ABNA0123456789",
                "bank_account_name": "",
            },
            update_modified=False,
        )

        _cols, data, _msg, _chart, _summary = report.execute({"issue_type": "sepa_selected_no_mandate"})
        my_rows = [r for r in data if r["member_id"] == member.name]
        self.assertEqual(len(my_rows), 1)
        self.assertEqual(my_rows[0]["banking_status"], "Missing Account Name")

    def test_execute_active_mandate_excludes_member(self):
        """A member with an ACTIVE mandate must NOT appear in the
        sepa_selected_no_mandate category (HAVING active_mandates = 0)."""
        member = self.create_test_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "payment_method": "SEPA Direct Debit",
                "iban": "NL02ABNA0123456789",
                "bank_account_name": "Test Holder",
            },
            update_modified=False,
        )
        mandate = self.create_test_sepa_mandate(
            member=member.name, iban="NL02ABNA0123456789", status="Active"
        )
        frappe.db.set_value("SEPA Mandate", mandate.name, "is_active", 1, update_modified=False)

        _cols, data, _msg, _chart, _summary = report.execute({"issue_type": "sepa_selected_no_mandate"})
        my_rows = [r for r in data if r["member_id"] == member.name]
        self.assertEqual(my_rows, [], "member with active mandate should be excluded")

    # ---- mandate_member_data_mismatch: holder/IBAN differs ----
    def test_execute_mandate_member_data_mismatch_iban(self):
        """Active mandate whose IBAN differs from the member record surfaces as a
        data mismatch with mismatch_type formatted to a human label."""
        member = self.create_test_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {
                "payment_method": "SEPA Direct Debit",
                "iban": "NL02ABNA0123456789",
                "bank_account_name": "Same Holder",
            },
            update_modified=False,
        )
        # A valid (MOD-97) IBAN that differs from the member's ABNA IBAN; the
        # SEPA Mandate controller validates the IBAN checksum on insert, so a
        # bogus string would raise ValidationError before the report runs.
        mandate = self.create_test_sepa_mandate(
            member=member.name,
            iban="NL13TEST0123456789",  # different (valid) IBAN
            status="Active",
            account_holder_name="Same Holder",
        )
        frappe.db.set_value("SEPA Mandate", mandate.name, "is_active", 1, update_modified=False)

        _cols, data, _msg, _chart, _summary = report.execute({"issue_type": "mandate_member_data_mismatch"})
        my_rows = [r for r in data if r["member_id"] == member.name]
        self.assertEqual(len(my_rows), 1)
        row = my_rows[0]
        self.assertEqual(row["member_iban"], "NL02ABNA0123456789")
        # The SEPA Mandate controller stores the IBAN in human-readable spaced
        # groups; the member IBAN (set via raw db.set_value) keeps its compact
        # form. The report surfaces both as stored, and the differing values are
        # what makes this an IBAN mismatch.
        self.assertEqual(row["mandate_iban"], "NL13 TEST 0123 4567 89")
        # _format_mismatch_type turns the raw key into a label.
        self.assertEqual(row["mismatch_type"], "IBAN Mismatch")

    # ---- missing_child_table_entries: mandate without a child link ----
    def test_execute_missing_child_table_entries(self):
        """A SEPA Mandate exists for a member but no Member SEPA Mandate Link row
        references it -> 'missing_child_table_entries'."""
        member = self.create_test_member()
        mandate = self.create_test_sepa_mandate(member=member.name, status="Active")
        # Remove any auto-created child link so the mandate is orphaned from the
        # member's child table (the condition the query detects: sml.name IS NULL).
        frappe.db.delete("Member SEPA Mandate Link", {"parent": member.name})
        frappe.db.commit()
        self.addCleanup(frappe.db.rollback)

        _cols, data, _msg, _chart, _summary = report.execute({"issue_type": "missing_child_table_entries"})
        my_rows = [r for r in data if r["member_id"] == member.name]
        self.assertEqual(len(my_rows), 1)
        self.assertGreaterEqual(my_rows[0]["mandate_count"], 1)
        self.assertIn(mandate.mandate_id, my_rows[0]["mandate_ids"])

    # ---- severity filter + no-data summary/chart ----
    def test_severity_filter_excludes_non_matching(self):
        """Filtering by a severity that none of MY rows carry returns no rows for
        my member (severity_filter branch in get_data)."""
        member = self.create_test_member()
        frappe.db.set_value(
            "Member",
            member.name,
            {"payment_method": "SEPA Direct Debit", "iban": "", "bank_account_name": ""},
            update_modified=False,
        )
        # sepa_selected_no_mandate is 'critical'; ask only for 'low'.
        _cols, data, _msg, _chart, _summary = report.execute(
            {"issue_type": "sepa_selected_no_mandate", "severity": "low"}
        )
        self.assertEqual([r for r in data if r["member_id"] == member.name], [])

    def test_get_summary_empty(self):
        summary = report.get_summary([])
        self.assertEqual(summary[0]["value"], 0)
        self.assertEqual(summary[0]["color"], "green")

    def test_get_chart_data_empty(self):
        self.assertIsNone(report.get_chart_data([]))

    def test_get_summary_counts_each_severity(self):
        data = [
            {"member_id": "M1", "severity": "critical", "issue_type": "A"},
            {"member_id": "M2", "severity": "high", "issue_type": "A"},
            {"member_id": "M3", "severity": "medium", "issue_type": "B"},
            {"member_id": "M4", "severity": "low", "issue_type": "B"},
        ]
        summary = report.get_summary(data)
        labels = {s["label"]: s["value"] for s in summary}
        self.assertEqual(labels["Total Issues"], 4)
        self.assertEqual(labels["Affected Members"], 4)
        self.assertEqual(labels["Critical"], 1)
        self.assertEqual(labels["High Severity"], 1)
        self.assertEqual(labels["Medium"], 1)
        self.assertEqual(labels["Low"], 1)

    def test_get_chart_data_groups_by_issue_type(self):
        data = [
            {"issue_type": "X", "severity": "high"},
            {"issue_type": "X", "severity": "high"},
            {"issue_type": "Y", "severity": "low"},
        ]
        chart = report.get_chart_data(data)
        labels = chart["data"]["labels"]
        values = chart["data"]["datasets"][0]["values"]
        idx = labels.index("X")
        self.assertEqual(values[idx], 2)

    def test_format_helpers_passthrough_unknown(self):
        # Unknown keys pass straight through (the .get default branch).
        self.assertEqual(report._format_mismatch_type("not_a_key"), "not_a_key")
        self.assertEqual(report._format_banking_status("not_a_key"), "not_a_key")
        self.assertEqual(report._format_mismatch_type("both_mismatch"), "IBAN & Holder Mismatch")
        self.assertEqual(report._format_banking_status("has_banking_data"), "Has Banking Data")


class TestSEPAMandateLifecycleServiceRealDB(EnhancedTestCase):
    """Real-document coverage for the lifecycle service DB paths (74% -> up)."""

    def setUp(self):
        super().setUp()
        self.service = SEPAMandateLifecycleService()

    def _make_member_with_mandate(self, status="Draft", **mandate_kwargs):
        member = self.create_test_member()
        mandate = self.create_test_sepa_mandate(member=member.name, status=status, **mandate_kwargs)
        return member, mandate

    # ---- set_status_based_on_dates against a real persisted mandate ----
    def test_set_status_future_sign_date_pending(self):
        _member, mandate = self._make_member_with_mandate(status="Draft")
        mandate.sign_date = add_days(today(), 10)
        self.assertEqual(self.service.set_status_based_on_dates(mandate), "Pending")

    def test_set_status_expired_when_past_expiry(self):
        _member, mandate = self._make_member_with_mandate(status="Active")
        mandate.sign_date = add_days(today(), -100)
        mandate.expiry_date = add_days(today(), -1)
        self.assertEqual(self.service.set_status_based_on_dates(mandate), "Expired")

    def test_set_status_no_dates_returns_current(self):
        _member, mandate = self._make_member_with_mandate(status="Suspended")
        mandate.sign_date = None
        mandate.expiry_date = None
        self.assertEqual(self.service.set_status_based_on_dates(mandate), "Suspended")

    # ---- sync_status_and_active_flag on real doc ----
    def test_sync_flag_active(self):
        _member, mandate = self._make_member_with_mandate(status="Active")
        mandate.is_active = 0
        self.service.sync_status_and_active_flag(mandate)
        self.assertEqual(mandate.is_active, 1)

    def test_sync_flag_cancelled(self):
        _member, mandate = self._make_member_with_mandate(status="Active")
        mandate.status = "Cancelled"
        mandate.is_active = 1
        self.service.sync_status_and_active_flag(mandate)
        self.assertEqual(mandate.is_active, 0)

    # ---- process_mandate_cancellation against a real, member-linked doc ----
    def test_process_cancellation_real_doc_updates_member_integration(self):
        """Cancellation flows through the REAL member-integration service path
        (mocked mandates in the sibling test skip this), exercising
        _update_member_mandate_status end to end."""
        _member, mandate = self._make_member_with_mandate(status="Active")
        result = self.service.process_mandate_cancellation(mandate, reason="Member request")
        self.assertTrue(result["success"], result.get("errors"))
        self.assertEqual(mandate.status, "Cancelled")
        self.assertEqual(mandate.is_active, 0)
        self.assertEqual(mandate.cancellation_reason, "Member request")

    def test_process_cancellation_already_cancelled_warns(self):
        _member, mandate = self._make_member_with_mandate(status="Active")
        frappe.db.set_value("SEPA Mandate", mandate.name, "status", "Cancelled")
        mandate.status = "Cancelled"
        result = self.service.process_mandate_cancellation(mandate)
        self.assertTrue(result["success"])
        self.assertTrue(any("already cancelled" in w for w in result["warnings"]))

    # ---- handle_status_transition (real doc, valid + invalid) ----
    def test_handle_status_transition_invalid(self):
        _member, mandate = self._make_member_with_mandate(status="Cancelled")
        result = self.service.handle_status_transition(mandate, old_status="Cancelled")
        # Cancelled is terminal -> no valid transition out of it.
        self.assertFalse(result["success"])
        self.assertTrue(any("Invalid status transition" in e for e in result["errors"]))

    def test_handle_status_transition_activation_requires_iban(self):
        """Activation reports ALL missing requirements; a mandate missing IBAN
        fails activation with a specific error (real _handle_activation path)."""
        _member, mandate = self._make_member_with_mandate(status="Active")
        mandate.iban = ""
        result = self.service.handle_status_transition(mandate, old_status="Draft")
        self.assertFalse(result["success"])
        self.assertTrue(any("IBAN is required" in e for e in result["errors"]))

    def test_handle_status_transition_activation_success(self):
        _member, mandate = self._make_member_with_mandate(status="Active")
        result = self.service.handle_status_transition(mandate, old_status="Draft")
        self.assertTrue(result["success"], result.get("errors"))
        # is_active synced on after a successful Active transition.
        self.assertEqual(mandate.is_active, 1)

    # ---- handle_mandate_creation / handle_mandate_update (real member integration) ----
    def test_handle_mandate_creation_active_real(self):
        _member, mandate = self._make_member_with_mandate(status="Active")
        result = self.service.handle_mandate_creation(mandate)
        self.assertTrue(result["success"], result.get("errors"))

    def test_handle_mandate_update_no_status_change_still_syncs_member(self):
        _member, mandate = self._make_member_with_mandate(status="Active")
        # Establish the "before save" snapshot from the persisted DB row so that
        # has_value_changed("status") reflects a re-save with NO status change.
        # A freshly inserted doc has no _doc_before_save, which would make
        # has_value_changed return True for every field (treating it as brand new);
        # load_doc_before_save() mirrors what Frappe does on a real on_update.
        mandate.load_doc_before_save()
        result = self.service.handle_mandate_update(mandate)
        # Status is unchanged vs the loaded snapshot -> no transition handling,
        # but the member SEPA-mandate child table is still synced.
        self.assertFalse(result["status_changed"])
        self.assertEqual(result["notifications_sent"], [])
        self.assertTrue(result["success"], result.get("errors"))

    # ---- metrics collector (singleton, threshold logic) ----
    def test_metrics_record_transition_and_summary(self):
        from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
            get_mandate_metrics_collector,
        )

        collector = get_mandate_metrics_collector()
        collector.reset_metrics()
        try:
            collector.record_status_transition("Draft", "Active")
            collector.record_status_transition("Active", "Cancelled")
            summary = collector.get_metrics_summary()
            self.assertEqual(summary["activation_count"], 1)
            self.assertEqual(summary["cancellation_count"], 1)
            self.assertEqual(summary["status_transitions"]["Draft->Active"], 1)
            self.assertEqual(summary["status_transitions"]["Active->Cancelled"], 1)
        finally:
            # Clean the singleton even if an assertion fails, so we never leak
            # counts into sibling tests in the same process.
            collector.reset_metrics()

    def test_metrics_check_thresholds_high_cancellation(self):
        from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
            get_mandate_metrics_collector,
        )

        collector = get_mandate_metrics_collector()
        collector.reset_metrics()
        try:
            # 11 cancellations, 0 activations -> high_cancellation_rate alert.
            for _ in range(11):
                collector.record_status_transition("Active", "Cancelled")
            alerts = collector.check_thresholds()
            types = {a["type"] for a in alerts}
            self.assertIn("high_cancellation_rate", types)
        finally:
            collector.reset_metrics()

    def test_metrics_record_error_caps_at_100(self):
        from verenigingen.verenigingen_payments.services.sepa_mandate_lifecycle_service import (
            get_mandate_metrics_collector,
        )

        collector = get_mandate_metrics_collector()
        collector.reset_metrics()
        try:
            for i in range(120):
                collector.record_error("op", f"err{i}", "MID")
            summary = collector.get_metrics_summary()
            self.assertEqual(summary["error_count"], 100)
            # high_error_rate alert fires once errors > 20.
            self.assertIn("high_error_rate", {a["type"] for a in collector.check_thresholds()})
        finally:
            collector.reset_metrics()


class TestSEPARetryOperationController(EnhancedTestCase):
    """Real-doc coverage for the SEPA Retry Operation child controller (18.6%)."""

    def _validated_operation(self, **kwargs):
        """Build a standalone SEPA Retry Operation and run its REAL controller
        validate(), returning the validated doc.

        Frappe does NOT auto-run a child-table controller's validate() when the
        parent is saved, and EnhancedTestCase runs with frappe.flags.in_import
        set (which also suppresses JSON field defaults on child rows). Inserting
        a parent batch therefore neither applies the operation's defaults nor
        runs its business rules. Driving SEPARetryOperation.validate() directly
        exercises the actual production unit under test (the same approach the
        is_eligible_for_retry / should_retry_now tests already use).
        """
        from verenigingen.verenigingen_payments.doctype.sepa_retry_operation.sepa_retry_operation import (
            SEPARetryOperation,
        )

        op = SEPARetryOperation({"doctype": "SEPA Retry Operation", "operation_type": "Other", **kwargs})
        op.validate()
        return op

    def test_validate_sets_defaults(self):
        op = self._validated_operation()
        self.assertEqual(op.status, "Pending")
        self.assertEqual(op.retry_attempts, 0)
        self.assertEqual(op.max_retries, 3)

    def test_validate_rejects_attempts_over_max(self):
        with self.assertRaises(frappe.ValidationError):
            self._validated_operation(retry_attempts=5, max_retries=3)

    def test_validate_success_forces_one_attempt(self):
        op = self._validated_operation(status="Success", retry_attempts=0)
        # Success with zero attempts is bumped to one recorded attempt.
        self.assertEqual(op.retry_attempts, 1)

    def test_validate_invalid_error_category_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self._validated_operation(error_category="not_valid")

    def test_validate_reference_missing_document_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self._validated_operation(
                reference_doctype="Member", reference_document="NON-EXISTENT-MEMBER-XYZ"
            )

    def test_next_retry_time_exponential_backoff(self):
        op = self._validated_operation(
            status="Pending", retry_attempts=2, max_retries=5, error_category="temporary"
        )
        # retry_attempts=2 -> base 5 * 2**(2-1) = 10 minutes ahead, not yet None.
        self.assertIsNotNone(op.next_retry_time)
        delta = getdate(op.next_retry_time) - getdate(today())
        self.assertGreaterEqual(delta.days, 0)

    def test_is_eligible_for_retry_matrix(self):
        from verenigingen.verenigingen_payments.doctype.sepa_retry_operation.sepa_retry_operation import (
            SEPARetryOperation,
        )

        def make(status, attempts, max_r, category):
            op = SEPARetryOperation(
                {
                    "doctype": "SEPA Retry Operation",
                    "operation_type": "Other",
                    "status": status,
                    "retry_attempts": attempts,
                    "max_retries": max_r,
                    "error_category": category,
                }
            )
            return op

        # Already succeeded -> not eligible.
        self.assertFalse(make("Success", 0, 3, "temporary").is_eligible_for_retry())
        # Exceeded max retries -> not eligible.
        self.assertFalse(make("Pending", 3, 3, "temporary").is_eligible_for_retry())
        # validation/data categories -> not eligible (manual intervention).
        self.assertFalse(make("Pending", 0, 3, "validation").is_eligible_for_retry())
        self.assertFalse(make("Pending", 0, 3, "data").is_eligible_for_retry())
        # authorization after first attempt -> not eligible.
        self.assertFalse(make("Pending", 1, 3, "authorization").is_eligible_for_retry())
        # temporary/unknown with attempts left -> eligible.
        self.assertTrue(make("Pending", 0, 3, "temporary").is_eligible_for_retry())
        self.assertTrue(make("Pending", 1, 3, "unknown").is_eligible_for_retry())

    def test_should_retry_now(self):
        from frappe.utils import now_datetime

        from verenigingen.verenigingen_payments.doctype.sepa_retry_operation.sepa_retry_operation import (
            SEPARetryOperation,
        )

        op = SEPARetryOperation(
            {
                "doctype": "SEPA Retry Operation",
                "operation_type": "Other",
                "status": "Pending",
                "retry_attempts": 0,
                "max_retries": 3,
                "error_category": "temporary",
            }
        )
        # No next_retry_time set -> retry now.
        self.assertTrue(op.should_retry_now())
        # Future next_retry_time -> not yet.
        op.next_retry_time = now_datetime() + timedelta(hours=1)
        self.assertFalse(op.should_retry_now())
        # Ineligible (Success) -> never now.
        op.status = "Success"
        self.assertFalse(op.should_retry_now())


class TestSEPARetryBatchController(EnhancedTestCase):
    """Real-doc coverage for the SEPA Retry Batch controller (32%)."""

    def _new_batch(self, operations=None):
        batch = frappe.new_doc("SEPA Retry Batch")
        batch.batch_date = today()
        for opdata in operations or []:
            batch.append("operations", opdata)
        batch.insert()
        self._track_test_document("SEPA Retry Batch", batch.name)
        return batch

    def test_empty_batch_defaults_to_pending(self):
        batch = self._new_batch()
        self.assertEqual(batch.status, "Pending")
        self.assertEqual(batch.total_operations, 0)

    def test_validate_operation_requires_type(self):
        # A new row cannot reach this check: _set_defaults() fills an empty child
        # Select with its first option on insert, so operation_type is only ever
        # missing on an existing batch whose value was cleared.
        batch = frappe.new_doc("SEPA Retry Batch")
        batch.batch_date = today()
        batch.append("operations", {"operation_type": "Other", "status": "Pending"})
        batch.insert()
        self.addCleanup(frappe.delete_doc, "SEPA Retry Batch", batch.name, force=True)

        batch.operations[0].operation_type = None
        with self.assertRaises(frappe.ValidationError):
            batch.save()

    def test_validate_invalid_error_category_throws(self):
        batch = frappe.new_doc("SEPA Retry Batch")
        batch.batch_date = today()
        batch.append("operations", {"operation_type": "Other", "error_category": "bogus"})
        with self.assertRaises(frappe.ValidationError):
            batch.insert()

    def test_validate_attempts_over_max_throws(self):
        batch = frappe.new_doc("SEPA Retry Batch")
        batch.batch_date = today()
        batch.append(
            "operations",
            {"operation_type": "Other", "retry_attempts": 9, "max_retries": 2},
        )
        with self.assertRaises(frappe.ValidationError):
            batch.insert()

    def test_calculate_totals_counts_statuses(self):
        """After insert, calculate_totals uses SQL aggregation (self.name set) to
        tally success/failed/pending counts from the persisted child rows."""
        batch = self._new_batch(
            operations=[
                {"operation_type": "Other", "status": "Success", "retry_attempts": 1},
                {"operation_type": "Other", "status": "Failed"},
                {"operation_type": "Other", "status": "Pending"},
            ]
        )
        batch.reload()
        batch.calculate_totals()
        self.assertEqual(batch.total_operations, 3)
        self.assertEqual(batch.successful_retries, 1)
        self.assertEqual(batch.failed_retries, 1)

    def test_calculate_totals_all_success_marks_completed(self):
        batch = self._new_batch(
            operations=[
                {"operation_type": "Other", "status": "Success", "retry_attempts": 1},
                {"operation_type": "Other", "status": "Success", "retry_attempts": 1},
            ]
        )
        batch.reload()
        batch.calculate_totals()
        self.assertEqual(batch.successful_retries, 2)
        self.assertEqual(batch.status, "Completed")

    def test_calculate_totals_all_failed_marks_failed(self):
        batch = self._new_batch(
            operations=[
                {"operation_type": "Other", "status": "Failed"},
                {"operation_type": "Other", "status": "Failed"},
            ]
        )
        batch.reload()
        batch.calculate_totals()
        self.assertEqual(batch.failed_retries, 2)
        self.assertEqual(batch.status, "Failed")

    def test_process_single_operation_by_category(self):
        batch = self._new_batch()
        validation_op = frappe._dict(error_category="validation")
        temporary_op = frappe._dict(error_category="temporary")
        other_op = frappe._dict(error_category="unknown")
        self.assertFalse(batch.process_single_operation(validation_op)["success"])
        self.assertTrue(batch.process_single_operation(temporary_op)["success"])
        self.assertTrue(batch.process_single_operation(other_op)["success"])

    def test_add_to_batch_log_appends_notes(self):
        batch = self._new_batch()
        batch.add_to_batch_log("first message")
        batch.add_to_batch_log("second message")
        self.assertIn("first message", batch.notes)
        self.assertIn("second message", batch.notes)

    def test_on_submit_processes_pending_operations(self):
        """on_submit -> process_retry_operations runs each Pending op through
        process_single_operation, recording the outcome and timestamps."""
        batch = self._new_batch(
            operations=[
                {"operation_type": "Other", "status": "Pending", "error_category": "temporary"},
                {"operation_type": "Other", "status": "Pending", "error_category": "validation"},
            ]
        )
        batch.submit()
        batch.reload()
        # temporary -> Success, validation -> Failed.
        statuses = sorted(op.status for op in batch.operations)
        self.assertEqual(statuses, ["Failed", "Success"])
        self.assertEqual(batch.successful_retries, 1)
        self.assertEqual(batch.failed_retries, 1)
        self.assertIsNotNone(batch.processing_started)
        self.assertIsNotNone(batch.processing_completed)

    def test_on_cancel_sets_cancelled(self):
        batch = self._new_batch(
            operations=[
                {"operation_type": "Other", "status": "Pending", "error_category": "temporary"},
            ]
        )
        batch.submit()
        batch.reload()
        batch.cancel()
        batch.reload()
        self.assertEqual(batch.status, "Cancelled")
        self.assertIn("cancelled", (batch.notes or "").lower())


class TestSEPARollbackManagerNetNew(EnhancedTestCase):
    """Net-new coverage for sepa_rollback_manager branches not exercised by the
    existing test_sepa_rollback_manager.py (the paid-invoice rollback path and
    the get_rollback_status JSON shaping for an operation with no compensation)."""

    def setUp(self):
        super().setUp()
        from verenigingen.verenigingen_payments.utils.sepa_rollback_manager import SEPARollbackManager

        self.mgr = SEPARollbackManager()
        self._created_operation_ids = []

    def tearDown(self):
        for op_id in self._created_operation_ids:
            for table in (
                "tabSEPA_Compensation_Transaction",
                "tabSEPA_Rollback_Audit",
                "tabSEPA_Rollback_Operation",
            ):
                try:
                    frappe.db.sql(f"DELETE FROM `{table}` WHERE operation_id = %s", (op_id,))
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def test_rollback_invoice_statuses_resets_paid_invoice(self):
        """A Sales Invoice marked Paid is rolled back to Unpaid (the success_count
        branch the existing test could not reach with fresh Unpaid invoices)."""
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        invoice_name = batch.invoices[0].invoice
        # Force the invoice into a Paid state via set_value (bypasses the normal
        # payment workflow; we only need the status the rollback step keys on).
        frappe.db.set_value("Sales Invoice", invoice_name, "status", "Paid")
        frappe.db.commit()
        self.addCleanup(frappe.db.rollback)

        res = self.mgr._rollback_invoice_statuses([invoice_name])
        self.assertTrue(res["success"], res.get("errors"))
        self.assertEqual(res["processed_count"], 1)
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice_name, "status"), "Unpaid")

    def test_get_rollback_status_no_compensation(self):
        """get_rollback_status for a freshly initiated operation returns empty
        compensation/audit lists shaped correctly (JSON parse-back path)."""
        from verenigingen.verenigingen_payments.utils.sepa_rollback_manager import RollbackReason

        batch = self.create_test_direct_debit_batch(invoice_count=1)
        result = self.mgr.initiate_batch_rollback(batch_name=batch.name, reason=RollbackReason.USER_REQUESTED)
        op_id = result["operation_id"]
        self._created_operation_ids.append(op_id)

        status = self.mgr.get_rollback_status(op_id)
        self.assertTrue(status["success"])
        self.assertEqual(status["operation"]["reason"], "user_requested")
        self.assertIsInstance(status["operation"]["affected_members"], list)
        self.assertIsInstance(status["compensation_transactions"], list)

    def test_get_batch_info_missing_returns_none(self):
        self.assertIsNone(self.mgr._get_batch_info("NO-SUCH-BATCH-ABC-123"))

    def test_rollback_payment_entries_no_linked_payments(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        res = self.mgr._rollback_payment_entries([batch.invoices[0].invoice])
        self.assertTrue(res["success"])
        self.assertEqual(res["cancelled_payments"], [])
