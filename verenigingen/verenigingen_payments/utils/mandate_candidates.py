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

# The short vocabulary that predates PURPOSE_FLAGS. `has_active_mandate` and
# `Member.has_active_sepa_mandate` take "memberships"/"donations", while the
# resolvers take the column names -- so the same concept had two spellings, and
# passing one function's vocabulary to the other silently applied NO purpose filter
# (`has_active_mandate(m, "used_for_memberships")` answered "any Active mandate
# exists"). One resolver now accepts both and refuses anything else.
PURPOSE_ALIASES = {
    "memberships": "used_for_memberships",
    "donations": "used_for_donations",
    "other": "used_for_other",
}


def resolve_purpose_flag(purpose):
    """Normalise a purpose to a `SEPA Mandate` column name, or raise.

    `None` means "any purpose" and is returned unchanged. Note that this is
    `is None`, not falsiness: `""` and `0` are rejected rather than treated as
    "any purpose", because a caller writing `purpose=cfg.get("purpose") or ""`
    would otherwise get purpose-blind resolution back with no error -- which is
    exactly the bug #597 fixed. Asking for any purpose has to be deliberate.
    """
    if purpose is None:
        return None
    if purpose in PURPOSE_FLAGS:
        return purpose
    if purpose in PURPOSE_ALIASES:
        return PURPOSE_ALIASES[purpose]
    raise ValueError(f"unknown mandate purpose {purpose!r}")


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
    purpose = resolve_purpose_flag(purpose)
    if purpose is not None:
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


def members_with_ambiguous_mandate(members, refusal_title: str, purpose: str = "used_for_memberships") -> set:
    """Which of `members` have no single Active mandate for `purpose` to debit.

    `unambiguous_active_mandate` above asks that question one member at a time,
    which is the right shape for a form and the wrong one for a collection run
    of a thousand invoices. This is the same rule, set-based: ONE query, the same
    refusal, and the same Error Log through `log_ambiguous_mandate_refusal`, so
    an operator reads one message format wherever the refusal came from.

    It exists for the MONTHLY automated producer, which resolves the mandate inside
    its invoice query:

        LEFT JOIN `tabSEPA Mandate` sm
            ON sm.member = mem.name
            AND sm.status = 'Active' AND sm.used_for_memberships = 1

    A join is not a choice. #597/#604's purpose filter bounds a member holding a
    membership mandate AND a donation mandate, but two Active mandates SHARING the
    membership purpose still make that join one-to-many, so one Sales Invoice comes
    back once per mandate -- same invoice, different `mandate_id`, in general a
    different IBAN. Both rows become `Direct Debit Batch Invoice` child rows, i.e.
    two debits for one debt off two accounts; since #606 the batch is rejected
    instead, which takes down the WHOLE run for every other member in it (#627).

    Refusing rather than de-duplicating is the point, and it is the behaviour the app
    has already PROMISED. `patches/v2_2/report_members_with_multiple_active_mandates`
    exists because rows predating #584's guard are deliberately not rewritten -- which
    mandate a member intends to be charged on is a data decision -- and it tells the
    operator, verbatim, that until they cancel the superseded ones "direct debit
    batches will REFUSE to select an IBAN for it (rather than guess)". That was true
    of `get_invoice_mandate_info` and false of both AUTOMATED producers, which fanned
    out instead. So this is not a `frappe.db.set_value` edge case: it is the default
    state of any install upgraded across #584, and the guard cannot be an index either
    -- MariaDB has no partial unique index, as that patch spells out. The guard is also
    an unlocked read-then-throw, so two concurrent activations both pass it.

    THE FILTER SET IS DELIBERATELY LOOSER THAN THE QUERY IT GUARDS, and it is worth
    being exact about the direction, because an earlier draft of this docstring
    claimed parity and was wrong.

    `get_sepa_invoices_with_mandates`' WHERE also carries `sm.iban IS NOT NULL AND
    sm.iban != '' AND sm.mandate_id IS NOT NULL`; this counter carries none of those,
    so a member whose second Active membership mandate has a blank `iban` is counted
    here as two and refused, while that query returns exactly one row. (`is_active` is
    parity: neither mentions it.)

    That looseness is the POINT, not a defect. The account a monthly child row is
    debited on does not come from that query at all --
    `batch_performance_optimizer.get_members_with_mandates_bulk` re-resolves the
    mandate filtering only on member + status + purpose, and assigns it in a last-wins
    loop with no ORDER BY (#708). Measured: 2 candidates on 2 accounts in, one
    arbitrarily chosen IBAN out, no refusal and no log. So a pair the collection query
    can tell apart is still a pair the resolver cannot, and tightening this filter to
    match the query would hand it an arbitrary IBAN.

    NOT used by the daily producer, deliberately. There, the row's `iban` comes from
    `mem`, `sm.mandate_id IS NOT NULL` is in the WHERE, and `get_mandate_for_batch_row`
    re-keys on `mandate_id`, which is `unique: 1` -- one row or none, not a choice. A
    looser count there could only over-refuse a member that query resolves cleanly, so
    the daily producer relies on
    `collection_rows.refuse_invoices_with_more_than_one_row` alone.

    That row-level guard is the exact, drift-proof half of this invariant: it observes
    the rows a query actually returned, so it cannot over-refuse and cannot drift. It
    also cannot see the resolver ambiguity above, which is why the monthly path needs
    both.

    Returns the members to EXCLUDE; the caller drops their rows. That loses one
    member's collection for the period, which is why the refusal is logged with the
    mandate ids: it is only defensible if an operator can find out it happened and
    which mandate to cancel.
    """
    wanted = {m for m in members if m}
    if not wanted:
        return set()

    purpose = resolve_purpose_flag(purpose)
    filters = {"member": ["in", sorted(wanted)], "status": "Active"}
    if purpose is not None:
        filters[purpose] = 1

    by_member = {}
    for row in frappe.get_all("SEPA Mandate", filters=filters, fields=["member", *MANDATE_FIELDS]):
        by_member.setdefault(row.member, []).append(row)

    refused = set()
    for member, rows in by_member.items():
        if len(rows) > 1:
            log_ambiguous_mandate_refusal(member, rows, purpose, refusal_title)
            refused.add(member)
    return refused


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
    Active mandate regardless of purpose. Note that this is `is None`, not
    falsiness: an EMPTY sequence means "this replacement serves nothing, so nothing
    overlaps it", and the answer to that is to cancel nothing -- not to cancel
    everything. Three of the five call sites compute their purposes with a list
    comprehension over the flags the request set, so `[]` is what a purposeless
    request produces, and reading it as "every purpose" cancelled the member's
    membership AND donation mandates on a request that authorized neither (#617).
    That is the same falsy-vs-None trap `resolve_purpose_flag` documents above
    (#597): asking for any purpose has to be deliberate.

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
    wanted = PURPOSE_FLAGS if purposes is None else tuple(purposes)
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
