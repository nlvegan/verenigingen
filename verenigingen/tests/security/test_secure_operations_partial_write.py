"""
Tests for #385: secure_document_operation's success=False hides a partial submit
==================================================================================

`Document.save()` writes `db_update()` (which flips `docstatus` for a submit)
BEFORE `run_post_save_methods()` invokes `on_submit`. So a Journal Entry whose
`on_submit` hook fails partway (e.g. a GL Entry violates `balance_must_be`) has
already persisted `docstatus=1` to the DB by the time `secure_document_operation`
catches the exception -- `success=False` alone cannot tell a caller that a write
already landed from a caller for which nothing was persisted.

Both scenarios below use REAL ERPNext validation paths (no mocking):

* ``test_submit_violating_balance_must_be_reports_partial_write`` -- a 2-line
  Journal Entry that credits an account whose balance must be Debit. Each GL
  Entry row is `db_insert`ed and only THEN validated (`GLEntry.on_update` ->
  `validate_balance_type`), so the offending row lands in `tabGL Entry` before
  its own validation raises "Balance for Account ... must always be Debit".
  This all happens AFTER Frappe already wrote the Journal Entry's
  `docstatus=1`. This is the partial-write case: `result.partial_write` must
  be True, `result.persisted_docstatus` must reflect the real DB value (1),
  and the ledger is left holding a GL Entry that should never have posted.
  (This used a Group Account until ERPNext #59687 moved that check into the
  Journal Entry's own `validate`; see tests/fixtures/ledger_failure_accounts.py.)
* ``test_submit_unbalanced_je_reports_clean_failure`` -- the CONTROL. A
  Journal Entry with a single, deliberately unbalanced line fails
  `validate_total_debit_and_credit()` in `before_submit`, which runs BEFORE
  `db_update()`. So nothing is persisted: docstatus stays 0, no GL Entry rows
  exist. This must report `partial_write=False`, proving the two failure
  outcomes are genuinely distinguishable and not both mapped to the same flag.

See verenigingen/utils/secure_operations.py and issue #385.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ledger_failure_accounts import make_balance_restricted_account
from verenigingen.utils.secure_operations import secure_document_operation


class TestSecureOperationsPartialWrite(EnhancedTestCase):
    """Discriminate a partial submit write from a clean submit failure."""

    def setUp(self):
        super().setUp()
        self.company = self._get_test_company()
        self.income_account = self._get_or_create_income_account(self.company)
        self.cost_center = self._get_or_create_cost_center(self.company)
        # Crediting an account whose balance must be Debit is rejected by
        # GLEntry.on_update (validate_balance_type), which fires AFTER the
        # Journal Entry's own docstatus has already been written by db_update().
        self.debit_only_account = make_balance_restricted_account(self.company, "Income", "Debit")

    def _make_je(self, accounts):
        je = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "company": self.company,
                "voucher_type": "Journal Entry",
                "posting_date": today(),
                "accounts": accounts,
            }
        )
        je.insert()
        self.track_doc("Journal Entry", je.name)
        return je

    def test_submit_violating_balance_must_be_reports_partial_write(self):
        je = self._make_je(
            [
                {
                    "account": self.income_account,
                    "debit_in_account_currency": 100,
                    "cost_center": self.cost_center,
                },
                {
                    "account": self.debit_only_account,
                    "credit_in_account_currency": 100,
                    "cost_center": self.cost_center,
                },
            ]
        )
        self.assertEqual(je.docstatus, 0)

        # secure_document_operation itself logs an Error Log on the failure
        # this test deliberately provokes -- expected, not a swallowed error.
        self.expectErrorLog("Secure Operation Failed: submit on Journal Entry")
        result = secure_document_operation(
            operation="submit",
            doc=je,
            justification="test #385 partial-write reproduction",
        )

        self.assertFalse(result.success, "submit violating balance_must_be must fail")

        # The discriminating assertion: the caller can tell this was NOT a
        # clean failure. docstatus was already flipped to 1 in the DB before
        # the debit-only row's on_update threw.
        self.assertEqual(
            result.persisted_docstatus,
            1,
            "docstatus must already be persisted as 1 -- db_update() runs before on_submit",
        )
        self.assertTrue(
            result.partial_write,
            "result must flag that a write landed despite success=False",
        )
        self.assertTrue(
            any("PARTIAL_WRITE" in w for w in result.warnings),
            f"expected a PARTIAL_WRITE warning, got: {result.warnings}",
        )

        # And the ledger itself is left corrupted: each GL Entry row is
        # db_insert()ed and only then validated, so the debit-only account's
        # credit row lands before its own validation raises. A caller trusting
        # success=False alone would never learn this invalid posting exists.
        # Row order through ERPNext's make_gl_entries/process_gl_map is not a
        # contract this test controls, so the discriminating assertion is the
        # offending row's presence, not the exact count.
        gl_rows = frappe.get_all(
            "GL Entry",
            filters={"voucher_type": "Journal Entry", "voucher_no": je.name},
            fields=["account", "debit", "credit", "is_cancelled"],
        )
        self.assertGreaterEqual(len(gl_rows), 1, f"expected at least one GL Entry row, got: {gl_rows}")
        self.assertTrue(
            any(row.account == self.debit_only_account for row in gl_rows),
            f"expected an (invalid) GL Entry against the debit-only account, got: {gl_rows}",
        )

    def test_submit_unbalanced_je_reports_clean_failure(self):
        """CONTROL: a submit failure that persists NOTHING must NOT be flagged partial_write."""
        je = self._make_je(
            [
                {
                    "account": self.income_account,
                    "debit_in_account_currency": 100,
                    "cost_center": self.cost_center,
                }
            ]
        )
        self.assertEqual(je.docstatus, 0)

        self.expectErrorLog("Secure Operation Failed: submit on Journal Entry")
        result = secure_document_operation(
            operation="submit",
            doc=je,
            justification="test #385 clean-failure control",
        )

        self.assertFalse(result.success, "an unbalanced Journal Entry must fail submit")

        # before_submit's validate_total_debit_and_credit() throws BEFORE
        # db_update() runs, so nothing was persisted -- docstatus stays 0.
        persisted_docstatus = frappe.db.get_value("Journal Entry", je.name, "docstatus")
        self.assertEqual(persisted_docstatus, 0, "unbalanced JE must not have persisted docstatus=1")

        self.assertFalse(
            result.partial_write,
            "a clean failure (nothing persisted) must NOT be flagged as a partial write",
        )
        self.assertEqual(
            result.persisted_docstatus,
            0,
            "persisted_docstatus must reflect the real (unchanged) DB value",
        )

        gl_count = frappe.db.count("GL Entry", {"voucher_type": "Journal Entry", "voucher_no": je.name})
        self.assertEqual(gl_count, 0, "an unbalanced JE that never reached on_submit must post no GL Entry")
