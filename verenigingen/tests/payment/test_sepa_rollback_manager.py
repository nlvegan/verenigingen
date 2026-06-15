"""
Tests for verenigingen.verenigingen_payments.utils.sepa_rollback_manager

Covers the SEPARollbackManager rollback orchestration, compensation-transaction
generation, audit trail, status reporting, and the module-level whitelisted API
functions.

Strategy:
- Pure-logic helpers (enum mapping, dataclasses, compensation-action selection)
  are exercised directly with real objects.
- DB-touching paths run against real fixtures created via the SEPA test factory
  (Direct Debit Batch + invoices + mandates). The manager creates its own
  tracking tables (tabSEPA_Rollback_Operation / _Compensation_Transaction /
  _Rollback_Audit) on init and commits to them, so those rows survive the test
  transaction; tests assert on the state the methods leave behind and clean up
  their own rows in tearDown.
- The email/notification boundary is stubbed (external side effect only).

Four genuine product bugs discovered while testing were originally pinned with
@unittest.expectedFailure; they are now FIXED in sepa_rollback_manager.py (and,
for the "Rolled Back" status, in direct_debit_batch.json) and the corresponding
tests assert the corrected behaviour. See the individual test docstrings.
"""

import unittest
import uuid
from datetime import datetime
from decimal import Decimal

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import sepa_rollback_manager as srm
from verenigingen.verenigingen_payments.utils.sepa_rollback_manager import (
    AuditEntry,
    CompensationAction,
    CompensationTransaction,
    RollbackOperation,
    RollbackReason,
    RollbackScope,
    SEPARollbackManager,
    list_rollback_operations,
)


# ---------------------------------------------------------------------------
# Pure-logic tests (no DB required)
# ---------------------------------------------------------------------------
class TestRollbackEnumsAndDataclasses(unittest.TestCase):
    """Enum values, dataclass defaults and the compensation-action mapping."""

    def test_rollback_reason_values(self):
        self.assertEqual(RollbackReason.BANK_REJECTION.value, "bank_rejection")
        self.assertEqual(RollbackReason("user_requested"), RollbackReason.USER_REQUESTED)
        # All eight reasons are distinct
        self.assertEqual(len({r.value for r in RollbackReason}), 8)

    def test_rollback_scope_values(self):
        self.assertEqual(RollbackScope.FULL_BATCH.value, "full_batch")
        self.assertEqual(RollbackScope("partial_batch"), RollbackScope.PARTIAL_BATCH)

    def test_compensation_action_values(self):
        self.assertEqual(CompensationAction.CREDIT_NOTE.value, "credit_note")
        self.assertEqual(len({a.value for a in CompensationAction}), 5)

    def test_invalid_enum_raises_value_error(self):
        with self.assertRaises(ValueError):
            RollbackReason("not_a_reason")
        with self.assertRaises(ValueError):
            RollbackScope("not_a_scope")

    def test_rollback_operation_defaults(self):
        op = RollbackOperation(
            operation_id="OP1",
            batch_name="B1",
            reason=RollbackReason.USER_REQUESTED,
            scope=RollbackScope.FULL_BATCH,
            initiated_by="tester",
            initiated_at=datetime.now(),
            affected_invoices=["INV-1"],
            affected_members=["MEM-1"],
            total_amount=Decimal("25.00"),
        )
        # Mutable defaults must not be shared between instances
        self.assertEqual(op.compensation_actions, [])
        self.assertEqual(op.status, "pending")
        self.assertIsNone(op.completed_at)
        self.assertEqual(op.error_log, [])
        op2 = RollbackOperation(
            operation_id="OP2",
            batch_name="B2",
            reason=RollbackReason.USER_REQUESTED,
            scope=RollbackScope.FULL_BATCH,
            initiated_by="tester",
            initiated_at=datetime.now(),
            affected_invoices=[],
            affected_members=[],
            total_amount=Decimal("0"),
        )
        op.error_log.append("boom")
        self.assertEqual(op2.error_log, [])

    def test_compensation_transaction_dataclass(self):
        ct = CompensationTransaction(
            transaction_id="T1",
            action_type=CompensationAction.CREDIT_NOTE,
            original_invoice="INV-1",
            original_amount=Decimal("10"),
            compensation_amount=Decimal("10"),
            reason="x",
            status="pending",
            created_at=datetime.now(),
        )
        self.assertEqual(ct.document_references, [])
        self.assertEqual(ct.action_type, CompensationAction.CREDIT_NOTE)

    def test_audit_entry_dataclass(self):
        ae = AuditEntry(
            entry_id="A1",
            operation_id="OP1",
            timestamp=datetime.now(),
            action="x",
            details={"k": "v"},
            user="tester",
            system_info={"site": "test"},
        )
        self.assertEqual(ae.details["k"], "v")


class TestCompensationActionMapping(unittest.TestCase):
    """_determine_compensation_actions is pure logic over the reason enum."""

    @classmethod
    def setUpClass(cls):
        # Manager __init__ creates tracking tables; that is harmless/idempotent.
        cls.mgr = SEPARollbackManager()

    def test_each_reason_maps_to_expected_action(self):
        expected = {
            RollbackReason.BATCH_PROCESSING_FAILED: CompensationAction.MANUAL_CORRECTION,
            RollbackReason.BANK_REJECTION: CompensationAction.CREDIT_NOTE,
            RollbackReason.VALIDATION_ERRORS: CompensationAction.MANUAL_CORRECTION,
            RollbackReason.MANDATE_ISSUES: CompensationAction.MANUAL_CORRECTION,
            RollbackReason.TECHNICAL_ERROR: CompensationAction.ACCOUNT_ADJUSTMENT,
            RollbackReason.BUSINESS_RULE_VIOLATION: CompensationAction.INVOICE_CANCELLATION,
            RollbackReason.USER_REQUESTED: CompensationAction.MANUAL_CORRECTION,
            RollbackReason.COMPLIANCE_ISSUE: CompensationAction.CREDIT_NOTE,
        }
        for reason, action in expected.items():
            actions = self.mgr._determine_compensation_actions(reason)
            self.assertEqual(actions, [action], f"reason {reason} mapped wrong")

    def test_unknown_reason_falls_back_to_manual_correction(self):
        # Pass an object that is not in the map -> default branch.
        class _Fake:
            pass

        actions = self.mgr._determine_compensation_actions(_Fake())
        self.assertEqual(actions, [CompensationAction.MANUAL_CORRECTION])


# ---------------------------------------------------------------------------
# Integration tests with real Direct Debit Batch fixtures
# ---------------------------------------------------------------------------
class TestSEPARollbackManagerIntegration(EnhancedTestCase):
    """Exercises the DB-touching rollback paths against real batch fixtures."""

    def setUp(self):
        super().setUp()
        self.mgr = SEPARollbackManager()
        self._created_operation_ids = []

    def tearDown(self):
        # The manager commits its tracking rows outside the test transaction,
        # so remove them explicitly to avoid cross-test leakage.
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

    # ----- helpers -----
    def _make_batch(self, invoice_count=2):
        batch = self.create_test_direct_debit_batch(invoice_count=invoice_count)
        return batch

    def _track(self, result):
        op_id = result.get("operation_id")
        if op_id:
            self._created_operation_ids.append(op_id)
        return result

    # ----- _get_batch_info -----
    def test_get_batch_info_returns_details(self):
        batch = self._make_batch(invoice_count=2)
        info = self.mgr._get_batch_info(batch.name)
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], batch.name)
        self.assertEqual(len(info["invoices"]), 2)

    def test_get_batch_info_missing_batch_returns_none(self):
        self.assertIsNone(self.mgr._get_batch_info("NON-EXISTENT-BATCH-XYZ"))

    # ----- initiate_batch_rollback: guard paths -----
    def test_initiate_rollback_missing_batch(self):
        result = self._track(
            self.mgr.initiate_batch_rollback(
                batch_name="NO-SUCH-BATCH-123",
                reason=RollbackReason.USER_REQUESTED,
            )
        )
        self.assertFalse(result["success"])
        self.assertIn("Batch not found", result["error"])
        self.assertIn("operation_id", result)

    def test_initiate_partial_rollback_without_invoices_errors(self):
        batch = self._make_batch(invoice_count=2)
        result = self._track(
            self.mgr.initiate_batch_rollback(
                batch_name=batch.name,
                reason=RollbackReason.VALIDATION_ERRORS,
                scope=RollbackScope.PARTIAL_BATCH,
                affected_invoices=None,
            )
        )
        self.assertFalse(result["success"])
        self.assertIn("Affected invoices must be specified", result["error"])

    # ----- initiate_batch_rollback: full happy path -----
    def test_initiate_full_batch_rollback_persists_operation_and_audit(self):
        batch = self._make_batch(invoice_count=2)
        result = self._track(
            self.mgr.initiate_batch_rollback(
                batch_name=batch.name,
                reason=RollbackReason.BANK_REJECTION,
                scope=RollbackScope.FULL_BATCH,
                metadata={"note": "test rollback"},
            )
        )
        op_id = result["operation_id"]
        self.assertEqual(result["batch_name"], batch.name)
        self.assertEqual(result["affected_invoices_count"], 2)
        self.assertGreater(result["total_amount"], 0)

        # Operation row persisted. The tracking tables are raw SQL tables (not
        # registered DocTypes), so query them directly -- frappe.db.get_value
        # would prepend "tab" and look for tabtabSEPA_Rollback_Operation.
        op_rows = frappe.db.sql(
            "SELECT batch_name, reason, scope, status FROM `tabSEPA_Rollback_Operation` "
            "WHERE operation_id = %s",
            (op_id,),
            as_dict=True,
        )
        self.assertEqual(len(op_rows), 1)
        op_row = op_rows[0]
        self.assertEqual(op_row.batch_name, batch.name)
        self.assertEqual(op_row.reason, "bank_rejection")
        # Mandate-usage step is now a safe no-op and the audit writes succeed, so
        # a clean rollback reports "completed".
        self.assertEqual(op_row.status, "completed")

        # Audit trail IS now written outside a request context (bug #2 fixed).
        audit_rows = frappe.db.sql(
            "SELECT action FROM `tabSEPA_Rollback_Audit` WHERE operation_id = %s",
            (op_id,),
        )
        self.assertGreater(len(audit_rows), 0)

    def test_initiate_rollback_marks_batch_rolled_back(self):
        batch = self._make_batch(invoice_count=1)
        self._track(
            self.mgr.initiate_batch_rollback(
                batch_name=batch.name,
                reason=RollbackReason.TECHNICAL_ERROR,
            )
        )
        # _rollback_batch_status writes "Rolled Back" via set_value (bypasses
        # the Select validation), so the value persists even though it is not a
        # declared option (see test_batch_status_value_not_in_doctype_options).
        status = frappe.db.get_value("Direct Debit Batch", batch.name, "status")
        self.assertEqual(status, "Rolled Back")

    # ----- get_rollback_status round-trip -----
    def test_get_rollback_status_round_trip(self):
        """Former PRODUCT BUG (FIXED): get_rollback_status read the tracking table via
            frappe.db.get_value("SEPA_Rollback_Operation", {filters}, [fields])
        but SEPA_Rollback_Operation is a raw SQL table, NOT a registered
        DocType. When a matching row existed, get_value's meta-driven field
        validation raised "DocType SEPA_Rollback_Operation not found", swallowed
        into {"success": False, "error": ...}, so status could NEVER be retrieved
        for an operation that actually existed. The method now queries the raw
        table with frappe.db.sql, so a round-trip read succeeds.
        """
        batch = self._make_batch(invoice_count=1)
        result = self._track(
            self.mgr.initiate_batch_rollback(
                batch_name=batch.name,
                reason=RollbackReason.COMPLIANCE_ISSUE,
            )
        )
        op_id = result["operation_id"]
        status = self.mgr.get_rollback_status(op_id)
        self.assertTrue(status["success"])
        self.assertEqual(status["operation"]["operation_id"], op_id)
        self.assertEqual(status["operation"]["batch_name"], batch.name)
        self.assertEqual(status["operation"]["reason"], "compliance_issue")
        self.assertIsInstance(status["compensation_transactions"], list)
        self.assertIsInstance(status["audit_trail"], list)
        # affected_invoices is JSON-serialized then parsed back to a list
        self.assertIsInstance(status["operation"]["affected_invoices"], list)

    def test_get_rollback_status_unknown_operation(self):
        status = self.mgr.get_rollback_status("ROLLBACK_DOES_NOT_EXIST")
        self.assertFalse(status["success"])
        self.assertIn("not found", status["error"])

    # ----- compensation transactions -----
    # These exercise _generate_compensation_transactions directly for focused
    # coverage. The end-to-end path through initiate_batch_rollback now also
    # reaches compensation generation (the former mandate-usage gating bug is
    # fixed -- see test_full_rollback_generates_compensation).
    def _operation_for(self, batch, reason):
        op_id = f"ROLLBACK_TEST_{uuid.uuid4().hex[:8].upper()}"
        self._created_operation_ids.append(op_id)
        batch_info = self.mgr._get_batch_info(batch.name)
        affected = [row.invoice for row in batch.invoices]
        op = RollbackOperation(
            operation_id=op_id,
            batch_name=batch.name,
            reason=reason,
            scope=RollbackScope.FULL_BATCH,
            initiated_by="tester",
            initiated_at=datetime.now(),
            affected_invoices=affected,
            affected_members=[],
            total_amount=Decimal("0"),
        )
        return op, batch_info

    def test_compensation_transactions_created_for_bank_rejection(self):
        # BANK_REJECTION maps to CREDIT_NOTE -> one compensation row per invoice.
        batch = self._make_batch(invoice_count=2)
        op, batch_info = self._operation_for(batch, RollbackReason.BANK_REJECTION)
        gen = self.mgr._generate_compensation_transactions(op, batch_info)
        self.assertTrue(gen["success"], gen.get("errors"))
        frappe.db.commit()
        comps = frappe.db.sql(
            "SELECT action_type, status FROM `tabSEPA_Compensation_Transaction` WHERE operation_id = %s",
            (op.operation_id,),
            as_dict=True,
        )
        self.assertEqual(len(comps), 2)
        for c in comps:
            self.assertEqual(c.action_type, "credit_note")
            # CREDIT_NOTE executor marks the row "completed"
            self.assertEqual(c.status, "completed")

    def test_compensation_manual_correction_flagged(self):
        # USER_REQUESTED maps to MANUAL_CORRECTION -> status requires_manual_action
        batch = self._make_batch(invoice_count=1)
        op, batch_info = self._operation_for(batch, RollbackReason.USER_REQUESTED)
        gen = self.mgr._generate_compensation_transactions(op, batch_info)
        self.assertTrue(gen["success"], gen.get("errors"))
        frappe.db.commit()
        comps = frappe.db.sql(
            "SELECT action_type, status FROM `tabSEPA_Compensation_Transaction` WHERE operation_id = %s",
            (op.operation_id,),
            as_dict=True,
        )
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].action_type, "manual_correction")
        self.assertEqual(comps[0].status, "requires_manual_action")

    def test_full_rollback_generates_compensation(self):
        """Regression for the former mandate-usage gating bug: _rollback_mandate_usage
        used to UPDATE a non-existent `usage_count` column, which always failed for a
        mandate-bearing batch and -- because compensation generation is gated on overall
        rollback success -- blocked ALL compensation transactions while reporting the
        whole rollback as failed. With the step neutralized to a safe no-op, the
        end-to-end rollback now succeeds and compensation transactions ARE generated.
        """
        batch = self._make_batch(invoice_count=1)
        result = self._track(
            self.mgr.initiate_batch_rollback(
                batch_name=batch.name,
                reason=RollbackReason.BANK_REJECTION,
            )
        )
        self.assertTrue(result["success"], result.get("rollback_details", {}).get("errors"))
        # BANK_REJECTION -> CREDIT_NOTE: one compensation row per affected invoice.
        comps = frappe.db.sql(
            "SELECT name FROM `tabSEPA_Compensation_Transaction` WHERE operation_id = %s",
            (result["operation_id"],),
        )
        self.assertEqual(len(comps), 1)

    # ----- direct helper coverage -----
    def test_rollback_batch_status_helper(self):
        batch = self._make_batch(invoice_count=1)
        res = self.mgr._rollback_batch_status(batch.name)
        self.assertTrue(res["success"])
        self.assertEqual(
            frappe.db.get_value("Direct Debit Batch", batch.name, "status"),
            "Rolled Back",
        )

    def test_rollback_invoice_statuses_only_touches_paid(self):
        # Fresh test invoices are typically Unpaid/Overdue -> helper skips them
        # (only Paid/Partly Paid roll back) but still reports success.
        batch = self._make_batch(invoice_count=2)
        invoice_names = [row.invoice for row in batch.invoices]
        res = self.mgr._rollback_invoice_statuses(invoice_names)
        self.assertTrue(res["success"])
        self.assertEqual(res["errors"], [])

    def test_rollback_payment_entries_no_payments(self):
        # No payment entries linked -> empty cancel list, success.
        batch = self._make_batch(invoice_count=2)
        invoice_names = [row.invoice for row in batch.invoices]
        res = self.mgr._rollback_payment_entries(invoice_names)
        self.assertTrue(res["success"])
        self.assertEqual(res["cancelled_payments"], [])

    def test_rollback_membership_statuses(self):
        batch = self._make_batch(invoice_count=2)
        members = [row.member for row in batch.invoices if row.member]
        res = self.mgr._rollback_membership_statuses(members)
        self.assertTrue(res["success"])
        self.assertEqual(res["errors"], [])

    def test_audit_entry_written_outside_request_context(self):
        """Former PRODUCT BUG (FIXED): _create_audit_entry built system_info with
            frappe.local.request.environ.get("REMOTE_ADDR") if frappe.local.request else None
        but frappe.local.request RAISES AttributeError (it is not merely falsy)
        when there is no active HTTP request -- i.e. in every background job,
        scheduled task, or test run. The whole INSERT was then swallowed by the
        method's try/except, so NO audit row was ever written outside a web
        request. The fix guards access with getattr(frappe.local, "request", None),
        so the audit entry now persists regardless of request context. This test
        runs outside an HTTP request and asserts the row IS written.
        """
        op_id = f"ROLLBACK_TEST_{uuid.uuid4().hex[:8].upper()}"
        self._created_operation_ids.append(op_id)
        self.mgr._create_audit_entry(
            operation_id=op_id,
            action="unit_test_action",
            details={"foo": "bar"},
        )
        frappe.db.commit()
        rows = frappe.db.sql(
            "SELECT action, details FROM `tabSEPA_Rollback_Audit` WHERE operation_id = %s",
            (op_id,),
            as_dict=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].action, "unit_test_action")
        self.assertEqual(frappe.parse_json(rows[0].details), {"foo": "bar"})

    def test_update_operation_status(self):
        # Seed an operation row through the public path, then mutate its status.
        batch = self._make_batch(invoice_count=1)
        result = self._track(
            self.mgr.initiate_batch_rollback(
                batch_name=batch.name,
                reason=RollbackReason.USER_REQUESTED,
            )
        )
        op_id = result["operation_id"]
        self.mgr._update_operation_status(op_id, "completed", ["a", "b"])
        frappe.db.commit()
        rows = frappe.db.sql(
            "SELECT status, error_log, completed_at FROM `tabSEPA_Rollback_Operation` "
            "WHERE operation_id = %s",
            (op_id,),
            as_dict=True,
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.status, "completed")
        self.assertEqual(frappe.parse_json(row.error_log), ["a", "b"])
        self.assertIsNotNone(row.completed_at)

    # ----- notification recipients (real role query) -----
    def test_get_notification_recipients_returns_emails(self):
        recipients = self.mgr._get_notification_recipients(RollbackReason.BANK_REJECTION)
        self.assertIsInstance(recipients, list)
        # Administrator holds System Manager -> at least one recipient on a
        # standard test site; all entries are email-looking strings.
        for r in recipients:
            self.assertIn("@", r)

    # ----- mandate usage rollback -----
    def _persist_mandate_usage(self, mandate_name, invoice_name, amount, status="Pending"):
        """Create a SEPA Mandate Usage row (usage_history) via the production
        helper, optionally forcing a terminal status afterwards."""
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            create_mandate_usage_record,
        )

        usage_name = create_mandate_usage_record(
            mandate_name, "Sales Invoice", invoice_name, amount, sequence_type="FRST"
        )
        if status != "Pending":
            frappe.db.set_value("SEPA Mandate Usage", usage_name, "status", status)
        return usage_name

    def _mandate_name_for_batch_row(self, row):
        name = frappe.db.get_value("SEPA Mandate", {"mandate_id": row.mandate_reference}, "name")
        self.assertTrue(name, f"could not resolve mandate for {row.mandate_reference}")
        return name

    def test_rollback_mandate_usage_cancels_pending_rows(self):
        """A rolled-back collection never effectively happened, so its
        not-yet-collected usage_history row is cancelled (so it stops counting
        toward mandate usage and FRST/RCUR sequence determination)."""
        batch = self._make_batch(invoice_count=1)
        batch_info = self.mgr._get_batch_info(batch.name)
        row = batch.invoices[0]
        mandate_name = self._mandate_name_for_batch_row(row)
        usage_name = self._persist_mandate_usage(mandate_name, row.invoice, row.amount)

        res = self.mgr._rollback_mandate_usage([row.invoice], batch_info)

        self.assertTrue(res["success"], f"mandate usage rollback failed: {res.get('errors')}")
        self.assertEqual(res["errors"], [])
        self.assertIn(usage_name, res["cancelled_usages"])
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate Usage", usage_name, "status"), "Cancelled"
        )
        self.assertIn(mandate_name, res["affected_mandates"])

    def test_rollback_mandate_usage_leaves_collected_rows_untouched(self):
        """A Collected usage row is a settled debit -- it is unwound via a
        compensation transaction (credit note / refund), NOT by rewriting
        history. The rollback step must leave it Collected."""
        batch = self._make_batch(invoice_count=1)
        batch_info = self.mgr._get_batch_info(batch.name)
        row = batch.invoices[0]
        mandate_name = self._mandate_name_for_batch_row(row)
        usage_name = self._persist_mandate_usage(
            mandate_name, row.invoice, row.amount, status="Collected"
        )

        res = self.mgr._rollback_mandate_usage([row.invoice], batch_info)

        self.assertTrue(res["success"], f"mandate usage rollback failed: {res.get('errors')}")
        self.assertEqual(res["cancelled_usages"], [])
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate Usage", usage_name, "status"), "Collected"
        )

    def test_rollback_mandate_usage_no_rows_surfaces_batch_mandates(self):
        """When the batch recorded no usage rows, the step still succeeds and
        surfaces the batch's mandate references for visibility/audit."""
        batch = self._make_batch(invoice_count=1)
        batch_info = self.mgr._get_batch_info(batch.name)
        invoice_names = [r.invoice for r in batch.invoices]

        res = self.mgr._rollback_mandate_usage(invoice_names, batch_info)

        self.assertTrue(res["success"], f"mandate usage rollback failed: {res.get('errors')}")
        self.assertEqual(res["cancelled_usages"], [])
        # Falls back to the batch rows' mandate references.
        self.assertTrue(res["affected_mandates"])


# ---------------------------------------------------------------------------
# Module-level whitelisted API functions
# ---------------------------------------------------------------------------
class TestRollbackAPIFunctions(EnhancedTestCase):
    """list_rollback_operations and the initiate/status wrappers."""

    def setUp(self):
        super().setUp()
        # Ensure tracking tables exist for the list query.
        SEPARollbackManager()

    def test_list_rollback_operations_empty_filter(self):
        res = list_rollback_operations(batch_name="DEFINITELY-NO-SUCH-BATCH")
        self.assertTrue(res["success"])
        self.assertEqual(res["total_operations"], 0)
        self.assertEqual(res["operations"], [])

    def test_list_rollback_operations_finds_seeded_op(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        mgr = SEPARollbackManager()
        result = mgr.initiate_batch_rollback(
            batch_name=batch.name,
            reason=RollbackReason.USER_REQUESTED,
        )
        op_id = result["operation_id"]
        try:
            listing = list_rollback_operations(batch_name=batch.name)
            self.assertTrue(listing["success"])
            self.assertGreaterEqual(listing["total_operations"], 1)
            found = [o for o in listing["operations"] if o["operation_id"] == op_id]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["batch_name"], batch.name)
        finally:
            for table in (
                "tabSEPA_Compensation_Transaction",
                "tabSEPA_Rollback_Audit",
                "tabSEPA_Rollback_Operation",
            ):
                frappe.db.sql(f"DELETE FROM `{table}` WHERE operation_id = %s", (op_id,))
            frappe.db.commit()

    def test_list_rollback_operations_days_back_window(self):
        # A 0-day lookback window starts at the beginning of today; just assert
        # the query runs and returns the documented shape.
        res = list_rollback_operations(days_back=0)
        self.assertTrue(res["success"])
        self.assertIn("operations", res)
        self.assertIn("total_operations", res)


# ---------------------------------------------------------------------------
# DocType-options integrity (latent data issue, pinned not fixed)
# ---------------------------------------------------------------------------
class TestBatchStatusOptionIntegrity(unittest.TestCase):
    def test_batch_status_value_in_doctype_options(self):
        """Former LATENT ISSUE (FIXED): _rollback_batch_status sets
        Direct Debit Batch.status = "Rolled Back", but the DocType's `status`
        Select options used to be only Draft/Generated/Submitted/Processed/Failed.
        Because the write goes through frappe.db.set_value it bypassed Select
        validation and persisted an undeclared value the UI/reports did not
        recognise. "Rolled Back" is a legitimate lifecycle state introduced by
        the rollback feature, so it is now a declared Select option in
        direct_debit_batch.json. This test asserts it is present.
        """
        import json
        import os

        path = os.path.join(
            os.path.dirname(srm.__file__),
            "..",
            "doctype",
            "direct_debit_batch",
            "direct_debit_batch.json",
        )
        with open(path) as fh:
            doc = json.load(fh)
        status_field = next(f for f in doc["fields"] if f.get("fieldname") == "status")
        options = (status_field.get("options") or "").split("\n")
        self.assertIn("Rolled Back", options)


if __name__ == "__main__":
    unittest.main()
