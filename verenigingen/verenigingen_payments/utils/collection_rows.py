"""One collection row per invoice -- the invariant, enforced where it is produced.

Every row a SEPA collection query returns becomes one `Direct Debit Batch Invoice`
child row, and every child row becomes one transaction in the SEPA XML. So a query
that returns an invoice twice debits the member twice for one debt.

`DirectDebitBatch.validate_no_duplicate_invoices` (#606) already rejects such a
batch, which is the right failure and the wrong outcome: it THROWS, and
`create_optimal_batches` wraps its whole group loop in `except Exception`, so one
member's bad data stops the collection for everyone in the run (#627). This module
is the same invariant one step earlier, where it can drop the affected invoice
instead of the month.

WHY THIS IS NOT THE ONLY GUARD, and must not be mistaken for one. It observes the
rows a particular SELECT actually returned, so it cannot over-refuse, cannot drift
away from the query's own predicates, and catches a fan-out through ANY join --
including the `tabMembership` one #616 fixed and any future one. What it cannot see
is an ambiguity that a downstream resolver collapses to a single row: two Active
mandates on two accounts still produce ONE row from
`batch_performance_optimizer.get_members_with_mandates_bulk`, whose last-wins loop
then picks an IBAN nobody chose. `mandate_candidates.members_with_ambiguous_mandate`
is what refuses that, by asking about the mandates rather than about the rows. The
two are complementary and neither subsumes the other.

REFUSING, not de-duplicating. Duplicate rows differ -- that is what makes them a
fan-out rather than a repeat -- and the fields they differ in (`mandate_reference`,
`iban`) are the ones the XML debits. Keeping one would debit an account nobody
chose, which is this repo's standing position on an ambiguous financial pick
(#567/#578/#584) and the behaviour
`patches/v2_2/report_members_with_multiple_active_mandates` already promises
operators. It is also what makes the bound real: if this is ever softened into
"keep one", the row count goes back to whatever the joins allow.
"""

import frappe

# The fields a refusal must name for an operator to act on it: what the duplicated
# rows disagree about, and what the SEPA XML would have debited. The last three are
# `dd_batch_api.DEBIT_DECIDING_FIELDS` -- the same set #613 refuses a de-duplication
# on, reached independently at the other end of the pipeline. NOT imported from
# there: this is a `utils` module and that is an `api` one, and here the set only
# shapes a message, while there it decides whether rows may be removed.
DISCRIMINATING_FIELDS = ("member", "member_name", "amount", "iban", "mandate_reference")


def refuse_invoices_with_more_than_one_row(rows, invoice_field: str, refusal_title: str):
    """Drop every row of any invoice this query returned more than once.

    Args:
        rows: the query's output, dicts keyed by `invoice_field`.
        invoice_field: the column naming the Sales Invoice -- `"invoice"` in the
            daily optimizer, `"name"` in the monthly service. Passed rather than
            guessed, because guessing wrong would silently disable the check.
        refusal_title: Error Log title, per flow, so an operator can filter the
            list by WHICH collection run refused.

    Returns:
        The rows for invoices that appeared exactly once, in their original order.
    """
    by_invoice = {}
    for row in rows:
        by_invoice.setdefault(row.get(invoice_field), []).append(row)

    duplicated = {invoice: dup for invoice, dup in by_invoice.items() if len(dup) > 1}
    if not duplicated:
        return list(rows)

    for invoice, dup in sorted(duplicated.items(), key=lambda item: str(item[0])):
        log_duplicate_row_refusal(invoice, dup, refusal_title)

    return [row for row in rows if row.get(invoice_field) not in duplicated]


def log_duplicate_row_refusal(invoice, rows, refusal_title: str) -> None:
    """Record which rows collided and how they differ.

    KEYWORD form. `frappe.log_error`'s signature is `log_error(title, message)`, so
    the common positional `log_error(f"...long...", "Title")` puts the message in
    `Error Log.method` (Data, truncated at 140 characters) and no title reaches the
    title column -- see `invoice_candidates.log_ambiguous_refusal` for the
    measurement (#602).
    """
    listed = "; ".join(
        ", ".join(f"{field}={row.get(field)}" for field in DISCRIMINATING_FIELDS if field in row)
        for row in rows
    )
    frappe.log_error(
        title=refusal_title,
        message=(
            f"Sales Invoice {invoice} was returned {len(rows)} times by the collection "
            f"query, so batching it would debit the member {len(rows)} times for one "
            f"debt. It is excluded from this run rather than collected on one of the "
            f"rows, because the rows disagree about what to debit. Rows: {listed}."
        ),
    )
