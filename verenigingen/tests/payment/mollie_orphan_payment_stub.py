"""Shared stand-in for a paid Mollie payment that matches no invoice (an "orphan").

Used by the orphan-path tests of MolliePaymentOrchestrator (#2406, #3013). One definition
instead of a near-identical copy per test module: the duplicate-helper ratchet refuses a new
clone family recorded into its baseline. Deliberately not named test_*, so the runner never
collects it as a test module.
"""

from types import SimpleNamespace

from frappe.utils import today

_UNSET = object()


def orphan_payment_stub(payment_id, amount, description, customer_id=_UNSET):
    """A paid iDEAL payment as the orchestrator reads it from the Mollie SDK.

    ``customer_id`` (None included) is set only when passed, so a caller that omits it gets an
    object without the attribute, exactly as before the two copies were merged.
    """
    payment = SimpleNamespace(
        id=payment_id,
        status="paid",
        amount={"value": f"{amount:.2f}", "currency": "EUR"},
        paid_at=f"{today()}T10:05:00+00:00",
        created_at=f"{today()}T10:00:00+00:00",
        description=description,
        method="ideal",
        metadata={},
    )
    if customer_id is not _UNSET:
        payment.customer_id = customer_id
    return payment
