"""Resolve a member's Active SEPA Mandate, or refuse when the pick is ambiguous.

`get_invoice_mandate_info` used to resolve the mandate inside its invoice query as

    LEFT JOIN `tabSEPA Mandate` sm ON sm.member = mem.name AND sm.status = 'Active'
    ORDER BY sm.creation DESC
    LIMIT 1

The invoice is given by name, so that `LIMIT 1` was never choosing an invoice -- it
was choosing among however many rows the Active-mandate join produced, newest first.
The result is written straight into the Direct Debit Batch child row (`iban`, `bic`,
`mandate_reference`, `mandate_date`), which is what the SEPA XML is generated from.
So a member holding two Active mandates got whichever IBAN happened to be created
most recently debited, with no record that a choice was made (#584).

`SEPAMandate.validate_single_active_mandate` now blocks the second Active mandate, so
the ambiguous branch should be unreachable. This exists anyway because that guard is
not the only way a mandate becomes Active: `frappe.db.set_value` on `status` bypasses
`validate` entirely, and the guard can be relaxed by a later change. Defence in depth
is cheap here -- refusing costs nothing when the ambiguity cannot occur.

A refusal is NOT "no mandate found". Collapsing the two is the mistake #581/#584's
neighbours keep making: a caller that reads a falsy return as "nothing here" goes on
to create what is missing, and this repo has already billed a member a third period
that way. `MandateChoice` therefore carries the refusal as its own state.
"""

from typing import Optional

import frappe

MANDATE_FIELDS = ["name", "mandate_id", "iban", "bic", "sign_date"]


class MandateChoice:
    """One Active mandate, nothing, or a refusal -- three outcomes, not two."""

    def __init__(self, mandate: Optional[dict], candidates: int):
        self.mandate = mandate
        self.candidates = candidates

    @property
    def is_ambiguous(self) -> bool:
        """True only when more than one Active mandate existed and none was chosen."""
        return self.mandate is None and self.candidates > 1

    def __bool__(self):
        """Deliberately NOT defined by candidate count: truthiness means "usable"."""
        return self.mandate is not None


def unambiguous_active_mandate(member: str, refusal_title: str) -> MandateChoice:
    """The member's single Active SEPA Mandate, or a refusal.

    Args:
        member: Member name.
        refusal_title: Error Log title, per flow, so an operator can filter the list
            by WHICH flow refused.
    """
    if not member:
        return MandateChoice(None, 0)

    rows = frappe.get_all(
        "SEPA Mandate",
        filters={"member": member, "status": "Active"},
        fields=MANDATE_FIELDS,
        order_by="creation desc",
    )

    if not rows:
        return MandateChoice(None, 0)
    if len(rows) == 1:
        return MandateChoice(rows[0], 1)

    # Keyword form: `frappe.log_error`'s signature is `log_error(title, message)`, so
    # the common positional `log_error(f"...long...", "Title")` puts the message in
    # `Error Log.method` (Data, truncated at 140 chars) and no title reaches the title
    # column -- see `invoice_candidates.log_ambiguous_refusal` for the measurement.
    listed = ", ".join(f"{r.mandate_id} ({r.iban})" for r in rows)
    frappe.log_error(
        title=refusal_title,
        message=(
            f"Member {member} has {len(rows)} Active SEPA Mandates, so no IBAN can be "
            f"chosen for direct debit without guessing. Cancel all but one. "
            f"Candidates: {listed}."
        ),
    )
    return MandateChoice(None, len(rows))
