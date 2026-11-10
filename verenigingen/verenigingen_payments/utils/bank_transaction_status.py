"""The reconcile pool's own record of what it did to a draft Bank Transaction (#2082).

ERPNext owns ``Bank Transaction.status``: from version-16 7526af9b2 ``validate()`` resets a
DRAFT to "Pending" on every save, and a SUBMITTED row's status is derived from
``unallocated_amount``. The app used to stamp "Reconciled"/"Unreconciled" onto drafts to take
them out of ``reconcile_bank_transactions``' pool; the next ordinary save undid the stamp and
the pool picked the row up again.

Maintainer ruling (2026-11-05): follow ERPNext's model. The app never writes ``status``. The
pool's outcome lives in the app-owned ``custom_processing_status`` instead, which ERPNext does
not touch, and the pool takes in only drafts that carry no TERMINAL outcome there. The other
labels on that field ("SEPA Identified", "Partial - Manual Review Required", ...) mark work
still in progress, and such drafts stay in the pool, as they always did.
"""

FIELD = "custom_processing_status"

RECONCILED = "Fully Reconciled"
FAILED = "Reconciliation Failed"

# Outcomes that take a draft out of the pool for good. "Manually Reconciled" and
# "Mollie Settlement Processed" are written by the SEPA dashboard and the settlement branch.
TERMINAL_OUTCOMES = (RECONCILED, FAILED, "Manually Reconciled", "Mollie Settlement Processed")
RECONCILED_OUTCOMES = tuple(o for o in TERMINAL_OUTCOMES if o != FAILED)


def pool_filters():
    """Filters selecting the drafts the pool should still work on."""
    return {
        "docstatus": 0,
        "allocated_amount": ["in", [0, None]],
        FIELD: ["not in", list(TERMINAL_OUTCOMES)],
    }


RECONCILED_STATE = "reconciled"
UNRECONCILED_STATE = "unreconciled"
PENDING_STATE = "pending"


def row_outcome(docstatus, status, marker):
    """Classify one Bank Transaction for display: reconciled, unreconciled or pending (#2396).

    A submitted row's state is ERPNext's ``status``; a draft's is the pool's marker, because
    ERPNext keeps every draft at "Pending". A draft with no terminal marker (none, or an
    in-progress label such as "Partial - Manual Review Required") is still pending.
    """
    if docstatus == 1:
        return {"Reconciled": RECONCILED_STATE, "Unreconciled": UNRECONCILED_STATE}.get(status, PENDING_STATE)
    if marker in RECONCILED_OUTCOMES:
        return RECONCILED_STATE
    if marker == FAILED:
        return UNRECONCILED_STATE
    return PENDING_STATE


def record_pool_outcome(bank_transaction, outcome):
    """Record ``outcome`` on a DRAFT ``bank_transaction``; no-op once submitted.

    A submitted row is outside the pool and its state is ERPNext's (``status`` derived from
    the allocation), so nothing is recorded there. A direct write: the caller may already
    have saved, and the marker must not depend on a further save succeeding.
    """
    if bank_transaction.docstatus != 0:
        return
    bank_transaction.db_set(FIELD, outcome, update_modified=False)
