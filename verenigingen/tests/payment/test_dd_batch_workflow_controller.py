"""
Real-integration tests for the SEPA Direct Debit Batch workflow controller.

Covers verenigingen/verenigingen_payments/api/dd_batch_workflow_controller.py
(previously 0% coverage). Drives real Direct Debit Batch / SEPA Mandate / Sales
Invoice documents built by the test factory - nothing is mocked.

The whitelisted endpoints are wrapped in @require_sepa_permission, which the test
user (Administrator) bypasses (the auth manager short-circuits Administrator/System
to allowed). Pure helper functions are called directly.

Covered:
    - validate_batch_for_approval: valid batch, empty batch, zero-amount,
      high-value risk routing, large-count risk routing, FRST risk, weekend warning,
      mandate-failure path
    - validate_sepa_mandates: missing reference, missing mandate, inactive mandate,
      member-mismatch, all-valid
    - validate_bank_details: missing IBAN, invalid IBAN, IBAN/mandate mismatch
    - is_valid_iban_format / normalize_iban
    - can_user_approve_batch (System Manager branch)
    - approve_batch / reject_batch / get_batch_approval_history
    - trigger_sepa_generation (not-approved guard)
    - get_batches_pending_approval
"""

import frappe
from frappe.utils import add_days, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.api import dd_batch_workflow_controller as ctrl


class TestDDBatchWorkflowHelpers(EnhancedTestCase):
    """Pure helper functions - no permission decorators involved."""

    def test_is_valid_iban_format_accepts_well_formed(self):
        self.assertTrue(ctrl.is_valid_iban_format("NL39RABO0300065264"))
        self.assertTrue(ctrl.is_valid_iban_format("nl39 rabo 0300 0652 64"))

    def test_is_valid_iban_format_rejects_bad(self):
        self.assertFalse(ctrl.is_valid_iban_format(""))
        self.assertFalse(ctrl.is_valid_iban_format("SHORT"))
        self.assertFalse(ctrl.is_valid_iban_format("12NL00000000000000"))  # no country letters
        self.assertFalse(ctrl.is_valid_iban_format("NLXXRABO0300065264"))  # non-digit check digits
        self.assertFalse(ctrl.is_valid_iban_format("X" * 40))  # too long

    def test_normalize_iban(self):
        self.assertEqual(ctrl.normalize_iban("nl39 rabo 0300 0652 64"), "NL39RABO0300065264")
        self.assertEqual(ctrl.normalize_iban(None), "")
        self.assertEqual(ctrl.normalize_iban(""), "")


class TestDDBatchMandateValidation(EnhancedTestCase):
    """validate_sepa_mandates against real SEPA Mandate documents.

    The validate helpers only iterate batch.invoices and read the row's
    mandate_reference / member / iban; they never touch the database for the
    batch itself, so an in-memory (unsaved) batch with appended rows is enough -
    this avoids the heavy DocType validate() that requires real Sales Invoices.
    """

    def _batch_with_one_invoice(self):
        member = self.create_test_member(first_name="MandateVal")
        mandate = self.create_test_sepa_mandate(member=member.name)
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.append(
            "invoices",
            {
                "invoice": "SINV-PLACEHOLDER",
                "member": member.name,
                "member_name": member.full_name,
                "amount": 25.0,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "status": "Pending",
                "sequence_type": "FRST",
            },
        )
        return batch, mandate, member

    def test_all_valid_mandates_no_issues(self):
        batch, _, _ = self._batch_with_one_invoice()
        self.assertEqual(ctrl.validate_sepa_mandates(batch), [])

    def test_missing_mandate_reference(self):
        batch, _, _ = self._batch_with_one_invoice()
        batch.invoices[0].mandate_reference = ""
        issues = ctrl.validate_sepa_mandates(batch)
        self.assertTrue(any("Missing mandate reference" in i for i in issues))

    def test_unknown_mandate_reference(self):
        batch, _, _ = self._batch_with_one_invoice()
        batch.invoices[0].mandate_reference = "NONEXISTENT-MANDATE-XYZ"
        issues = ctrl.validate_sepa_mandates(batch)
        self.assertTrue(any("not found" in i for i in issues))

    def test_inactive_mandate(self):
        batch, mandate, _ = self._batch_with_one_invoice()
        frappe.db.set_value("SEPA Mandate", mandate.name, {"status": "Cancelled", "is_active": 0})
        issues = ctrl.validate_sepa_mandates(batch)
        self.assertTrue(any("not active" in i for i in issues))

    def test_member_mismatch(self):
        batch, _, _ = self._batch_with_one_invoice()
        # Point the invoice row at a different member than the mandate's member.
        other = self.create_test_member(first_name="OtherMember")
        batch.invoices[0].member = other.name
        issues = ctrl.validate_sepa_mandates(batch)
        self.assertTrue(any("member mismatch" in i for i in issues))


class TestDDBatchBankValidation(EnhancedTestCase):
    """validate_bank_details against real mandate documents."""

    def _batch_with_one_invoice(self):
        member = self.create_test_member(first_name="BankVal")
        mandate = self.create_test_sepa_mandate(member=member.name)
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.append(
            "invoices",
            {
                "invoice": "SINV-PLACEHOLDER",
                "member": member.name,
                "member_name": member.full_name,
                "amount": 10.0,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "status": "Pending",
                "sequence_type": "FRST",
            },
        )
        return batch, mandate

    def test_matching_iban_no_warnings(self):
        batch, _ = self._batch_with_one_invoice()
        self.assertEqual(ctrl.validate_bank_details(batch), [])

    def test_missing_iban_warning(self):
        batch, _ = self._batch_with_one_invoice()
        batch.invoices[0].iban = ""
        warnings = ctrl.validate_bank_details(batch)
        self.assertTrue(any("Missing IBAN" in w for w in warnings))

    def test_invalid_iban_warning(self):
        batch, _ = self._batch_with_one_invoice()
        batch.invoices[0].iban = "BAD"
        warnings = ctrl.validate_bank_details(batch)
        self.assertTrue(any("Invalid IBAN format" in w for w in warnings))

    def test_iban_mandate_mismatch_warning(self):
        batch, _ = self._batch_with_one_invoice()
        # A well-formed but different IBAN than the mandate's.
        batch.invoices[0].iban = "NL39RABO0300065264"
        warnings = ctrl.validate_bank_details(batch)
        self.assertTrue(any("IBAN mismatch with mandate" in w for w in warnings))


class TestValidateBatchForApproval(EnhancedTestCase):
    """validate_batch_for_approval routing/risk logic (Administrator bypasses auth)."""

    def test_valid_low_risk_batch(self):
        # factory default sequence_type is FRST which bumps risk to Medium; use RCUR
        # with a small total/count so all risk factors stay at their Low baseline.
        batch = self.create_test_direct_debit_batch(invoice_count=2, sequence_type="RCUR")
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["risk_level"], "Low")
        self.assertEqual(result["recommended_state"], "Pending Approval")
        # risk_level should be persisted on the batch
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", batch.name, "risk_level"), "Low")

    def test_empty_batch_is_invalid(self):
        # An empty batch can't pass the DocType validate(), so insert one with
        # validation bypassed to exercise the controller's own empty/zero checks.
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = frappe.utils.today()
        batch.batch_description = "Empty batch under test"
        batch.currency = "EUR"
        batch.status = "Draft"
        batch.total_amount = 0
        batch.entry_count = 0
        batch.flags.ignore_validate = True
        batch.insert()
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertFalse(result["valid"])
        self.assertTrue(any("No invoices" in i for i in result["issues"]))
        self.assertTrue(any("Invalid total amount" in i for i in result["issues"]))

    def test_high_value_batch_routes_to_senior(self):
        batch = self.create_test_direct_debit_batch(invoice_count=2)
        # Force a high-value total to trip the >5000 risk factor.
        batch.db_set("total_amount", 6000)
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertEqual(result["risk_level"], "High")
        self.assertEqual(result["recommended_state"], "Pending Senior Approval")

    def test_large_count_batch_is_medium_risk(self):
        batch = self.create_test_direct_debit_batch(invoice_count=2)
        batch.db_set("entry_count", 60)
        batch.db_set("total_amount", 1000)
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertEqual(result["risk_level"], "Medium")

    def test_size_over_threshold_routes_to_senior(self):
        batch = self.create_test_direct_debit_batch(invoice_count=2)
        batch.db_set("entry_count", 120)
        batch.db_set("total_amount", 1000)
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertEqual(result["recommended_state"], "Pending Senior Approval")

    def test_frst_batch_bumps_to_medium(self):
        batch = self.create_test_direct_debit_batch(invoice_count=2)
        # factory default sequence_type is already FRST; ensure low base risk otherwise.
        batch.db_set("total_amount", 100)
        batch.db_set("entry_count", 2)
        self.assertEqual(batch.sequence_type, "FRST")
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertEqual(result["risk_level"], "Medium")

    def test_weekend_batch_warns(self):
        batch = self.create_test_direct_debit_batch(invoice_count=2)
        # Find the next Saturday.
        d = getdate()
        while d.weekday() != 5:
            d = getdate(add_days(d, 1))
        batch.db_set("batch_date", d)
        batch.db_set("sequence_type", "RCUR")  # avoid FRST so we isolate the weekend warning
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertTrue(any("weekend" in w.lower() for w in result["warnings"]))

    def test_invalid_mandate_makes_batch_invalid(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        # Break the mandate reference on the single row.
        batch.invoices[0].db_set("mandate_reference", "GONE-MANDATE")
        result = ctrl.validate_batch_for_approval(batch_name=batch.name)
        self.assertFalse(result["valid"])


class TestDDBatchApprovalEndpoints(EnhancedTestCase):
    """approve_batch / reject_batch / history / generation / pending list."""

    def test_can_user_approve_as_system_manager(self):
        # Administrator carries System Manager → can_user_approve_batch returns True.
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        self.assertTrue(ctrl.can_user_approve_batch(batch))

    def test_approve_valid_batch(self):
        batch = self.create_test_direct_debit_batch(invoice_count=2)
        batch.db_set("approval_status", "Pending Approval")
        batch.db_set("risk_level", "Low")
        result = ctrl.approve_batch(batch_name=batch.name, approval_notes="Looks good")
        self.assertTrue(result["success"])
        self.assertEqual(result["next_state"], "Approved")
        # approval note must be persisted with the user/timestamp prefix
        notes = frappe.db.get_value("Direct Debit Batch", batch.name, "approval_notes")
        self.assertIn("Looks good", notes)

    def test_reject_batch_records_reason(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        result = ctrl.reject_batch(batch_name=batch.name, rejection_reason="Bad IBANs")
        self.assertTrue(result["success"])
        notes = frappe.db.get_value("Direct Debit Batch", batch.name, "approval_notes")
        self.assertIn("REJECTED", notes)
        self.assertIn("Bad IBANs", notes)

    def test_approval_history_parses_notes(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        ctrl.reject_batch(batch_name=batch.name, rejection_reason="First problem")
        history = ctrl.get_batch_approval_history(batch_name=batch.name)
        self.assertTrue(history["success"])
        self.assertGreaterEqual(len(history["history"]), 1)
        self.assertTrue(any("REJECTED" in h["action"] for h in history["history"]))

    def test_trigger_generation_requires_approved_state(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        batch.db_set("approval_status", "Pending Approval")
        # The endpoint throws "Batch must be approved before SEPA generation".
        # The @require_sepa_permission wrapper re-raises any inner exception as a
        # PermissionError ("Authorization check failed"), so that is what callers
        # see. We accept either to be robust to the wrapping behaviour.
        with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
            ctrl.trigger_sepa_generation(batch_name=batch.name)

    def test_get_batches_pending_approval_returns_drafts(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        self.assertEqual(batch.status, "Draft")
        result = ctrl.get_batches_pending_approval()
        self.assertTrue(result["success"])
        names = {b["name"] for b in result["batches"]}
        self.assertIn(batch.name, names)


class TestRequireSepaPermissionErrorPropagation(EnhancedTestCase):
    """Regression: @require_sepa_permission no longer masks endpoint-body errors.

    The decorator used to wrap the whole endpoint body in `except Exception` and
    re-raise every inner error as a generic
    frappe.PermissionError("Authorization check failed"). It now guards only the
    authorization check, so real endpoint errors (e.g. frappe.ValidationError from
    the batch-state / validation checks) propagate with their true type and
    message instead of being hidden behind a PermissionError.

    Run as Administrator, who passes the auth gate - so any exception that reaches
    the caller comes from the endpoint body, exactly the path the fix protects.
    """

    def test_approve_empty_batch_raises_validation_error_not_permission_error(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        # Empty the batch so validate_batch_for_approval fails with "No invoices".
        batch.set("invoices", [])
        batch.db_set("entry_count", 0)
        batch.db_set("total_amount", 0)
        frappe.db.delete("Direct Debit Batch Invoice", {"parent": batch.name})

        # The endpoint body throws a ValidationError; the fixed decorator lets it
        # through with its real type rather than masking it as PermissionError.
        with self.assertRaises(frappe.ValidationError):
            ctrl.approve_batch(batch_name=batch.name)
        # And it must NOT be raised as a PermissionError.
        try:
            ctrl.approve_batch(batch_name=batch.name)
        except frappe.PermissionError:
            self.fail("approve_batch error was masked as PermissionError")
        except frappe.ValidationError:
            pass

    def test_trigger_generation_unapproved_raises_validation_error_mentioning_approved(self):
        batch = self.create_test_direct_debit_batch(invoice_count=1)
        batch.db_set("approval_status", "Pending Approval")

        # Not-approved guard raises a ValidationError whose message mentions
        # "approved" - it must reach the caller as a ValidationError, not a
        # generic PermissionError.
        with self.assertRaises(frappe.ValidationError) as ctx:
            ctrl.trigger_sepa_generation(batch_name=batch.name)
        self.assertIn("approved", str(ctx.exception).lower())

        try:
            ctrl.trigger_sepa_generation(batch_name=batch.name)
        except frappe.PermissionError:
            self.fail("trigger_sepa_generation error was masked as PermissionError")
        except frappe.ValidationError:
            pass
