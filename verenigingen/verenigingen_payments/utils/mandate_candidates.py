"""The one-Active-mandate invariant: resolve it, or supersede it.

Two halves of the same rule live here so that every flow enforcing it shares one
implementation rather than a copy per call site.

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

MANDATE_FIELDS = ["name", "mandate_id", "iban", "bic", "sign_date", "expiry_date", "status"]

PURPOSE_FLAGS = ("used_for_memberships", "used_for_donations", "used_for_other")

PURPOSE_LABELS = {
    "used_for_memberships": "memberships",
    "used_for_donations": "donations",
    "used_for_other": "other collections",
}


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


def unambiguous_active_mandate(
    member: str, refusal_title: str, purpose: str = "used_for_memberships"
) -> MandateChoice:
    """The member's single Active SEPA Mandate FOR A PURPOSE, or a refusal.

    The purpose filter is the point, not a refinement. A member may legitimately
    hold an Active membership mandate and an Active donation mandate at once, so a
    query that asks only for "Active" is ambiguous by construction -- and
    `test_payment_history_writer_parity` already records a real divergence caused by
    exactly that: `get_default_mandate` picked the newest Active mandate with no
    purpose filter while the incremental writer filtered on `used_for_memberships`,
    and the two disagreed whenever a member's donation mandate was newer.

    Callers resolving a mandate for a MEMBERSHIP invoice want the default,
    `used_for_memberships`. Pass `purpose=None` only to ask "any Active mandate",
    which is almost never what a collection wants.

    Args:
        member: Member name.
        refusal_title: Error Log title, per flow, so an operator can filter the list
            by WHICH flow refused.
        purpose: One of PURPOSE_FLAGS, or None for no purpose filter.
    """
    if not member:
        return MandateChoice(None, 0)

    filters = {"member": member, "status": "Active"}
    if purpose:
        if purpose not in PURPOSE_FLAGS:
            raise ValueError(f"unknown mandate purpose {purpose!r}")
        filters[purpose] = 1

    rows = frappe.get_all(
        "SEPA Mandate",
        filters=filters,
        fields=MANDATE_FIELDS,
        order_by="creation desc",
    )

    if not rows:
        return MandateChoice(None, 0)
    if len(rows) == 1:
        return MandateChoice(rows[0], 1)

    log_ambiguous_mandate_refusal(member, rows, purpose, refusal_title)
    return MandateChoice(None, len(rows))


def log_ambiguous_mandate_refusal(member: str, rows, purpose, refusal_title: str) -> None:
    """Record WHY a mandate was not chosen, so a refusal is actionable.

    Shared with `SEPAMandateManager.get_default_mandate`, which reaches the same
    verdict from an already-fetched list rather than from its own query (#597). One
    implementation, so the two flows cannot drift into describing the same state
    differently -- and so `mandate_id (iban)` stays the one format an operator
    learns to read.

    `rows` may hold plain dicts or `MandateInfo` dataclasses; both expose
    `mandate_id` and `iban`.
    """
    # Keyword form: `frappe.log_error`'s signature is `log_error(title, message)`, so
    # the common positional `log_error(f"...long...", "Title")` puts the message in
    # `Error Log.method` (Data, truncated at 140 chars) and no title reaches the title
    # column -- see `invoice_candidates.log_ambiguous_refusal` for the measurement.
    listed = ", ".join(f"{getattr(r, 'mandate_id', None)} ({getattr(r, 'iban', None)})" for r in rows)
    scope = PURPOSE_LABELS.get(purpose, "any purpose")
    frappe.log_error(
        title=refusal_title,
        message=(
            f"Member {member} has {len(rows)} Active SEPA Mandates for {scope}, so no "
            f"IBAN can be chosen for direct debit without guessing. Cancel all but "
            f"one. Candidates: {listed}."
        ),
    )


def cancel_active_mandates(member: str, reason: str, purposes=None, new_status: str = "Cancelled") -> dict:
    """Cancel every Active mandate of a member; report what they were used for.

    A member may hold at most one Active mandate PER PURPOSE (#584), so a
    replacement has to cancel the overlapping ones first -- in that order.
    Activating first and tidying up afterwards trips
    `SEPAMandate.validate_single_active_mandate_per_purpose` before the cleanup can
    run.

    `purposes` is the set the REPLACEMENT will serve; pass None to supersede every
    Active mandate regardless of purpose.

    Returns the cancelled names AND the union of their purpose flags. The union is
    the part that is easy to get wrong: `SEPA Mandate` carries
    `used_for_memberships` / `used_for_donations` / `used_for_other` as independent
    checkboxes, so one mandate can serve several purposes. Replacing a
    memberships mandate with a donations-only one and dropping the first would
    silently stop that member's membership collections. Callers are expected to OR
    the returned flags into the replacement.

    `new_status` exists because `create_and_link_mandate` deliberately SUSPENDS
    rather than cancels -- `enforce_terminal_status` treats Cancelled and Expired as
    irreversible, Suspended as recoverable -- and converging these flows must not
    quietly make a recoverable state terminal. Either satisfies the guard; only
    `Active` does not.

    Measured on veg11: all 66 Active mandates are memberships-only, and there are no
    donation-only or dual-purpose mandates -- so this union is defensive today
    rather than load-bearing. It is here because the flag combination is reachable
    (three independent checkboxes) and the failure it prevents is silent.
    """
    wanted = tuple(purposes) if purposes else PURPOSE_FLAGS
    for flag in wanted:
        if flag not in PURPOSE_FLAGS:
            raise ValueError(f"unknown mandate purpose {flag!r}")

    active = frappe.get_all(
        "SEPA Mandate",
        filters={"member": member, "status": "Active"},
        fields=["name", *PURPOSE_FLAGS],
    )
    # Only mandates that OVERLAP the incoming purposes are superseded. Cancelling a
    # member's donation mandate because they re-signed for memberships would end a
    # collection nobody asked to stop.
    cancelled = [row for row in active if any(row.get(flag) for flag in wanted)]

    purposes = {flag: 0 for flag in PURPOSE_FLAGS}
    names = []
    for row in cancelled:
        for flag in PURPOSE_FLAGS:
            if row.get(flag):
                purposes[flag] = 1
        doc = frappe.get_doc("SEPA Mandate", row.name)
        doc.status = new_status
        doc.is_active = 0
        if new_status == "Cancelled":
            doc.cancelled_date = frappe.utils.today()
            doc.cancellation_reason = reason
        doc.save()
        names.append(row.name)

    return {"names": names, "purposes": purposes}


def carry_forward_purposes(mandate, purposes: dict) -> None:
    """OR a superseded mandate's purpose flags into its replacement."""
    for flag, was_set in (purposes or {}).items():
        if was_set:
            mandate.set(flag, 1)
