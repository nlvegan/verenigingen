"""Resolving ONE Sales Invoice out of a party's candidate set (#559, #567, #578).

Place after place in this app queried a party's invoices, took the first row, and then
moved money -- or reported a status -- against it: #559 fixed one, #567 four more, #578
five. None of them was choosing. Each was letting `ORDER BY ... LIMIT 1` choose, on
`creation`, `posting_date` or a coverage start date, for a payment that said nothing
about which invoice it was for. #559 (the reconciliation MEMBERSHIP branch) named the
rule; this module is that rule, in one place, so the next call site inherits it instead
of re-deriving it.

**This module is the rule, not a census of its users.** The AST sweep behind #567 matched
`get_all`/`get_list`/`get_value` only, so **raw `frappe.db.sql` with `LIMIT 1` was
invisible to it** -- and `services/billing/invoice_matcher._find_invoice_by_coverage_sql`
was exactly that, ~100 lines above a site the sweep DID surface and clear. Its two
coverage-keyed siblings were cleared affirmatively, on the reasoning that
`(customer, coverage_start, coverage_end)` is unique; it is not, and this codebase says so
by shipping `coverage_overlap_detector.find_overlapping_invoices`. All four were #578, and
one of them WARNED about the sibling invoice while allocating to the other anyway.

Before adding a caller, grep for `LIMIT 1` in raw SQL too -- and if a query cannot be
expressed as `frappe.get_all` filters, use `choose_unambiguous` on the rows rather than
re-deriving the rule beside it.

The rule, in order:

1. **One candidate -> that one, whatever the amount.** An amount smaller than the
   outstanding is a legitimate partial payment. Requiring the amount to match here
   is the tempting version of this fix and it removes something that worked -- the
   failure this repo keeps repeating (see the 2026-08-23b handoff by name).
2. **Several candidates, exactly one whose amount matches -> that one.** The
   discriminator was available all along and every one of these sites ignored it.
3. **Anything else is a CHOICE, not a match.** Refuse, and let the caller say so.
   Two candidates that both match the amount narrow nothing: picking either would
   be the same arbitrary pick reached through a filter instead of through creation
   order.

Callers need to tell rule 3 from "no candidates at all" -- the operator-facing
outcome differs, and #567 asks specifically that the refusal be *visible* rather
than logged into a void. `candidates` carries that count so nobody needs a second
query to get it.
"""

from typing import Optional

import frappe
from frappe.utils import flt


class InvoiceChoice:
    """The outcome of applying the rule: one invoice, or a refusal with its reason.

    `invoice` is the resolved row (a dict of the requested `fields`) or None.
    `candidates` is how many rows were in the candidate set, so a caller can
    distinguish "nothing to match" (0) from "a choice I must not make" (>1).
    `rows` is the candidate set itself, because a refusal that does not name the
    invoices it refused between cannot be acted on: #567 asks for the refusal to be
    visible, and "2 candidates" without their names sends the operator back to the
    query. Kept optional so a caller that only needs the count is unaffected.
    """

    __slots__ = ("invoice", "candidates", "rows")

    def __init__(self, invoice: Optional[dict], candidates: int, rows: Optional[list] = None):
        self.invoice = invoice
        self.candidates = candidates
        self.rows = rows or []

    @property
    def is_ambiguous(self) -> bool:
        """True only for rule 3: candidates existed and none of them was THE one."""
        return self.invoice is None and self.candidates > 0

    @property
    def candidate_names(self) -> list:
        """The candidate invoice names, for an operator-facing refusal message."""
        return [row.get("name") for row in self.rows if row.get("name")]


def unambiguous_invoice(
    filters: dict,
    amount,
    amount_field: str = "outstanding_amount",
    fields: Optional[list] = None,
) -> InvoiceChoice:
    """The ONE Sales Invoice in `filters`' candidate set that `amount` can be for.

    `amount_field` is the column the amount discriminator compares against.
    `outstanding_amount` is right for an incoming payment (what is still owed);
    a caller reversing a *settled* invoice wants `grand_total`, because the
    outstanding on a Paid invoice is 0 and carries no information.

    Compared at the field's own precision, as `create_payment_entry_from_transaction`
    does, so an amount differing by a fraction of a cent that ERPNext itself rounds
    away is still recognised as the amount match.

    `filters` is the caller's own candidate definition and is passed through
    untouched -- deliberately, because the four call sites disagree about which
    statuses are candidates and each is right about its own case. What they must
    NOT disagree about is what to do once there is more than one.
    """
    requested = list(fields or ["name"])
    if amount_field not in requested:
        requested.append(amount_field)

    candidates = frappe.get_all("Sales Invoice", filters=filters, fields=requested)
    return choose_unambiguous(candidates, amount, amount_field)


def log_ambiguous_refusal(title: str, refused: InvoiceChoice, detail: str) -> None:
    """Record a refusal where an operator will actually find it.

    KEYWORD form, deliberately. `frappe.log_error`'s signature is
    `log_error(title, message)`, so the near-universal positional
    `log_error(f"...long...", "Short Title")` passes the MESSAGE as the title: it lands
    in `Error Log.method` (Data, truncated at 140 characters mid-word) and no title
    reaches the title column at all. Measured on test_site_1 -- `error` keeps the full
    text, so nothing is lost; what breaks is the Error Log LIST, which becomes
    unreadable and unfilterable. That paragraph had been copied at four call sites,
    which is why the call lives here now instead.

    `title` stays per-flow so an operator can filter the list by WHICH flow refused;
    `detail` is that flow's own sentence. The candidate NAMES are appended here rather
    than left to each caller, because a refusal reporting only a count sends the reader
    back to the query it was supposed to save them.
    """
    message = detail
    names = refused.candidate_names
    if names:
        # Capped: `bank_integration` builds its candidate set from a
        # `like %debtor_name%` customer match, so this list is not inherently small,
        # and an Error Log row nobody can read is the thing this helper exists to avoid.
        shown = names[:10]
        listed = ", ".join(shown)
        if len(names) > len(shown):
            listed = f"{listed} and {len(names) - len(shown)} more"
        message = f"{message} Candidates: {listed}."
    frappe.log_error(title=title, message=message)


def choose_unambiguous(candidates: list, amount, amount_field: str = "outstanding_amount") -> InvoiceChoice:
    """The rule itself, applied to a candidate set the caller already fetched.

    Separate from `unambiguous_invoice` because one member of this class cannot be
    spelled as `frappe.get_all` filters at all: `invoice_matcher._find_invoice_by_coverage_sql`
    is raw SQL over a coverage window widened by a buffer, with a CASE that ranks
    invoices containing the payment date above ones merely near it (#578). Re-deriving
    "what to do once there is more than one" at that call site is exactly what this
    module exists to prevent, so the rule is reachable without the query.

    `candidates` rows must each carry `amount_field`. The caller owns which rows are
    candidates -- including any narrowing that is real evidence rather than an
    ordering, such as preferring the invoices whose coverage period actually contains
    the payment date.
    """
    if not candidates:
        return InvoiceChoice(None, 0)
    if len(candidates) == 1:
        return InvoiceChoice(candidates[0], 1, candidates)

    precision = frappe.get_precision("Sales Invoice", amount_field) or 2
    target = flt(amount or 0, precision)
    exact = [c for c in candidates if flt(c[amount_field], precision) == target]
    if len(exact) == 1:
        return InvoiceChoice(exact[0], len(candidates), candidates)

    return InvoiceChoice(None, len(candidates), candidates)
