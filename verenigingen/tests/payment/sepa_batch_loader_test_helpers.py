"""Shared test helper for the #1217 "already batched" exclusion tests.

Both test_sepa_batch_ui.py and test_sepa_batch_ui_secure.py need to put a
freshly-built chain's invoice into a real Direct Debit Batch at a specific
docstatus/status, to exercise `get_open_batch_invoice_names()`
(verenigingen_payments/api/sepa_batch_ui.py). Kept here once rather than as two
near-identical copies -- one of those was exactly the "two divergent copies of
an exclusion rule" trap #1217 itself was filed for, and the duplicate-helper
ratchet (scripts/validation/duplicate_helper_validator.py) is what catches it
on the test side.
"""

import frappe
from frappe.utils import today


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
