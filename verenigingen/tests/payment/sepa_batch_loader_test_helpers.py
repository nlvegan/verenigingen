"""Shared test helpers for the SEPA batch loader test files.

Both test_sepa_batch_ui.py and test_sepa_batch_ui_secure.py need to put a
freshly-built chain's invoice into a real Direct Debit Batch at a specific
docstatus/status, to exercise `get_open_batch_invoice_names()`
(verenigingen_payments/api/sepa_batch_ui.py). Kept here once rather than as two
near-identical copies -- one of those was exactly the "two divergent copies of
an exclusion rule" trap #1217 itself was filed for, and the duplicate-helper
ratchet (scripts/validation/duplicate_helper_validator.py) is what catches it
on the test side.

`customer_only_invoice` (#1218) is here for the same reason: both files'
eligibility-guard tests need a Sales Invoice with no `member` and no
`membership_dues_schedule_display` link (a donation-invoice/general-sale
shape), and the ratchet caught the first version of this as a near-identical
copy-paste across the two files.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory


def customer_only_invoice(test_case, first_name, currency="EUR"):
    """A Sales Invoice with no `member` and no dues-schedule link -- the shape
    of a donation invoice or a general sale (#1218).

    Sets `test_case.factory` to the factory it builds, matching the
    `_build_member_with_invoice` convention both callers already use.
    """
    f = SEPATestDataFactory(seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True)
    test_case.factory = f
    customer = f.create_test_customer(customer_name=f"Cust {first_name}").name
    return f.create_test_sales_invoice(
        customer=customer,
        grand_total=42.0,
        currency=currency,
        submit=True,
    )


def put_invoice_in_batch(
    test_case,
    chain,
    status="Draft",
    force_docstatus=None,
    batch_date=None,
    sepa_file_generated=False,
):
    """Insert chain['invoice'] as a child row of a real Direct Debit Batch.

    Inserted at docstatus=0/status="Draft" first (the shape
    `create_sepa_batch_validated` itself produces, so this is known to insert
    cleanly), then `status` and `docstatus` are moved directly in the DB rather
    than through `submit()` -- `DirectDebitBatch.on_submit()` calls
    `generate_sepa_xml()`, which these tests have no reason to exercise, and the
    controller's own `before_submit` docstring says exactly this bypass is a
    real, deliberate path ("historical batches recorded for reconciliation set
    docstatus directly in the DB and never call submit()").

    Child rows do not inherit a parent's docstatus from `frappe.db.set_value`
    the way a real `submit()` would cascade it, so both are set explicitly --
    this is the trap #1217's exclusion query depends on getting right.

    `batch_date` and `sepa_file_generated` let a caller build a "stranded"
    batch (Draft, no file generated, dated before today) to exercise
    `sepa_constants.stranded_batch_exclusion()` -- see
    `TestLoadUnpaidInvoicesExcludesAlreadyBatched` for why that matters.
    `before_submit` only runs on a real `submit()`, which this helper never
    calls, so inserting with a past `batch_date` is not itself rejected.

    `test_case` needs `_track_test_document` (EnhancedTestCase) for teardown.
    """
    batch = frappe.new_doc("Direct Debit Batch")
    batch.batch_date = batch_date or today()
    batch.batch_description = f"loader-exclusion {frappe.generate_hash(length=6)}"
    batch.batch_type = "CORE"
    batch.sequence_type = "RCUR"
    batch.currency = "EUR"
    batch.status = "Draft"
    batch.sepa_file_generated = 1 if sepa_file_generated else 0
    row = batch.append("invoices", {})
    row.invoice = chain["invoice"].name
    row.amount = float(chain["invoice"].outstanding_amount)
    row.currency = "EUR"
    row.member = chain["member"].name
    row.membership = chain["membership"].name
    row.member_name = chain["member"].full_name
    row.iban = chain["mandate"].iban
    row.mandate_reference = chain["mandate"].mandate_id
    row.status = "Pending"
    batch.insert()
    test_case._track_test_document("Direct Debit Batch", batch.name)

    if status != "Draft":
        frappe.db.set_value("Direct Debit Batch", batch.name, "status", status, update_modified=False)
    if force_docstatus is not None:
        frappe.db.set_value(
            "Direct Debit Batch", batch.name, "docstatus", force_docstatus, update_modified=False
        )
        frappe.db.sql(
            "UPDATE `tabDirect Debit Batch Invoice` SET docstatus=%s WHERE parent=%s",
            (force_docstatus, batch.name),
        )
    return batch


class BatchRowBankDataFromMandateMixin:
    """#2813: a batch row's bank data comes from the invoice's member's mandate,
    never from the caller's `invoice_list` payload.

    Shared by test_sepa_batch_ui.py and test_sepa_batch_ui_secure.py, whose two
    create endpoints carry the same row-building code. The subclass supplies
    `_build_member_with_invoice` (its test base) and a `_create_endpoint` staticmethod
    attribute naming the endpoint under test.
    """

    def _row_payload(self, chain, **overrides):
        # Not named after any caller key: `iban` is sent unspaced, like the real UI payload.
        row = {
            "invoice": chain["invoice"].name,
            "amount": float(chain["invoice"].outstanding_amount),
            "iban": chain["mandate"].iban.replace(" ", ""),
            "member_name": chain["member"].full_name,
            "mandate_reference": chain["mandate"].mandate_id,
            "currency": "EUR",
        }
        row.update(overrides)
        return row

    def _create_with_rows(self, rows):
        from frappe.utils import add_days, getdate

        batch_date = getdate(add_days(today(), 3))
        while batch_date.weekday() >= 5:
            batch_date = getdate(add_days(batch_date, 1))
        return self._create_endpoint(
            batch_date=str(batch_date), batch_type="CORE", invoice_list=rows
        )

    def _assert_refused_and_nothing_written(self, result, invoice_name):
        self.assertFalse(result.get("success"), result)
        self.assertIn("does not match the active SEPA mandate", " ".join(result.get("errors", [])))
        self.assertFalse(
            frappe.db.exists("Direct Debit Batch Invoice", {"invoice": invoice_name}),
            "a refused payload must not leave a batch row behind",
        )

    def test_another_members_mandate_and_iban_are_refused(self):
        """The issue's attack: member A's invoice collected with member B's mandate id + IBAN."""
        victim = self._build_member_with_invoice(first_name="MandateVictim")
        other = self._build_member_with_invoice(first_name="MandateOther")
        row = self._row_payload(
            victim,
            iban=other["mandate"].iban.replace(" ", ""),
            mandate_reference=other["mandate"].mandate_id,
        )
        self._assert_refused_and_nothing_written(self._create_with_rows([row]), victim["invoice"].name)

    def test_own_mandate_reference_with_a_foreign_iban_is_refused(self):
        """Mandate id is right, IBAN is not: the second half of the same disagreement."""
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        victim = self._build_member_with_invoice(first_name="MandateIbanVictim")
        # Derived, not borrowed from a second chain: each chain's factory restarts its IBAN
        # sequence, so two chains can draw the SAME IBAN (same bank) and the "foreign" IBAN
        # would then equal the victim's -- measured, it made this test pass for no reason.
        victim_iban = victim["mandate"].iban.replace(" ", "")
        foreign_iban = generate_test_iban(bank_code="INGB", account_number="0000987654")
        if foreign_iban == victim_iban:
            foreign_iban = generate_test_iban(bank_code="RABO", account_number="0000987654")
        self.assertNotEqual(foreign_iban, victim_iban)
        row = self._row_payload(victim, iban=foreign_iban)
        self._assert_refused_and_nothing_written(self._create_with_rows([row]), victim["invoice"].name)

    def test_foreign_mandate_reference_with_own_iban_is_refused(self):
        victim = self._build_member_with_invoice(first_name="MandateRefVictim")
        other = self._build_member_with_invoice(first_name="MandateRefOther")
        row = self._row_payload(victim, mandate_reference=other["mandate"].mandate_id)
        self._assert_refused_and_nothing_written(self._create_with_rows([row]), victim["invoice"].name)

    def test_row_is_written_from_the_mandate_and_the_member_not_the_payload(self):
        """Control for the refusals: an agreeing payload still creates the batch, and
        the row holds the MANDATE's values and the Member's own name (the payload's
        member_name is cosmetic and is never trusted)."""
        chain = self._build_member_with_invoice(first_name="MandateSourced")
        row = self._row_payload(chain, member_name="Somebody Else Entirely")
        result = self._create_with_rows([row])
        self.assertTrue(result.get("success"), result)

        written = frappe.get_doc("Direct Debit Batch", result["batch_name"]).invoices[0]
        mandate = chain["mandate"]
        self.assertEqual(written.iban.replace(" ", ""), mandate.iban.replace(" ", ""))
        self.assertEqual(written.mandate_reference, mandate.mandate_id)
        self.assertEqual(written.bic, mandate.bic)
        self.assertEqual(written.member_name, frappe.db.get_value("Member", chain["member"].name, "full_name"))
        self.assertNotEqual(written.member_name, "Somebody Else Entirely")

    def test_bic_is_taken_from_the_mandate_not_the_payload(self):
        chain = self._build_member_with_invoice(first_name="MandateBic")
        row = self._row_payload(chain, bic="DEUTDEFF")
        result = self._create_with_rows([row])
        self.assertTrue(result.get("success"), result)
        written = frappe.get_doc("Direct Debit Batch", result["batch_name"]).invoices[0]
        self.assertEqual(written.bic, chain["mandate"].bic)
        self.assertNotEqual(written.bic, "DEUTDEFF")

    def test_member_without_an_active_mandate_is_refused(self):
        chain = self._build_member_with_invoice(first_name="MandateNone")
        frappe.db.set_value(
            "SEPA Mandate", chain["mandate"].name, "status", "Cancelled", update_modified=False
        )  # probe shortcut: status flipped directly instead of the cancel flow
        result = self._create_with_rows([self._row_payload(chain)])
        self.assertFalse(result.get("success"), result)
        self.assertIn("No active SEPA mandate", " ".join(result.get("errors", [])))
        self.assertFalse(frappe.db.exists("Direct Debit Batch Invoice", {"invoice": chain["invoice"].name}))
