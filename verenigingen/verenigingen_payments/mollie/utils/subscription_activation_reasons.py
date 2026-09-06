"""
Shared vocabulary for permanent Mollie subscription-activation refusals.

Two modules used to agree on these five reason strings only by spelling,
across a module boundary with no shared constant (issue #353, the #341
shape):

- ``verenigingen_payments.utils.payment_gateways`` PRODUCES a reason when a
  subscription cannot be created (an interval Mollie rejects, missing
  metadata, or a permanent Mollie 400).
- ``verenigingen_payments.mollie.services.webhook_wrapper_service_unified``
  CONSUMES the reason to decide whether a webhook redelivery is retried or
  refused for good -- see ``is_permanent_subscription_refusal`` below.

Both sides import from here so a renamed reason is a ``NameError`` (or an
``AttributeError`` on this module), not a silent behaviour change where a
redelivery is retried forever, or a refusal is wrongly treated as permanent.
"""

INVALID_INTERVAL = "invalid_interval"
MISSING_SUBSCRIPTION_DETAILS = "missing_subscription_details"
MISSING_CUSTOMER_ID = "missing_customer_id"
IDEMPOTENCY_KEY_CONFLICT = "idempotency_key_conflict"
MOLLIE_BAD_REQUEST = "mollie_bad_request"

# The consumer checks membership against this set, read live at call time --
# see webhook_wrapper_service_unified.is_permanent_subscription_refusal().
PERMANENT_SUBSCRIPTION_ACTIVATION_REASONS = frozenset(
    {
        INVALID_INTERVAL,
        MISSING_SUBSCRIPTION_DETAILS,
        MISSING_CUSTOMER_ID,
        IDEMPOTENCY_KEY_CONFLICT,
        MOLLIE_BAD_REQUEST,
    }
)
