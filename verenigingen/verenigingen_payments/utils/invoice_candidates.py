"""Resolving ONE Sales Invoice out of a party's candidate set (#559, #567).

Four places in this app queried a party's invoices, took the first row, and then
moved money against it.

**This module is the rule, not a census of its users.** The AST sweep that found those
four matched `get_all`/`get_list`/`get_value` only, so **raw `frappe.db.sql` with
`LIMIT 1` is invisible to it** -- and `services/billing/invoice_matcher.py`
`_find_invoice_by_coverage_sql` is exactly that, ~100 lines above a site the sweep DID
surface and clear. It is reachable in production (Mollie Bulk Run ->
`mollie_bulk_run_service` -> `MolliePaymentOrchestrator.process_payment` ->
`_resolve_invoice_fresh`) and allocates against
`ORDER BY match_priority ASC, custom_coverage_start_date DESC LIMIT 1`. Tracked in
**#578**, with two coverage-keyed siblings, not fixed here. Before adding a fifth caller, grep for `LIMIT 1` in raw SQL too. None of them was choosing -- each was letting
`ORDER BY ... LIMIT 1` choose, on `creation` or `posting_date`, for a payment that
said nothing about which invoice it was for. #559 fixed the fifth (the
reconciliation MEMBERSHIP branch) and named the rule; this module is that rule,
in one place, so the next call site inherits it instead of re-deriving it.

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
    """

    __slots__ = ("invoice", "candidates")

    def __init__(self, invoice: Optional[dict], candidates: int):
        self.invoice = invoice
        self.candidates = candidates

    @property
    def is_ambiguous(self) -> bool:
        """True only for rule 3: candidates existed and none of them was THE one."""
        return self.invoice is None and self.candidates > 0


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
    if not candidates:
        return InvoiceChoice(None, 0)
    if len(candidates) == 1:
        return InvoiceChoice(candidates[0], 1)

    precision = frappe.get_precision("Sales Invoice", amount_field) or 2
    target = flt(amount or 0, precision)
    exact = [c for c in candidates if flt(c[amount_field], precision) == target]
    if len(exact) == 1:
        return InvoiceChoice(exact[0], len(candidates))

    return InvoiceChoice(None, len(candidates))
