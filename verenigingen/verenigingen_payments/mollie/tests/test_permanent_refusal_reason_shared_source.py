"""
Regression test for issue #353 (the #341 shape).

``payment_gateways._permanent_refusal_reason`` (plus its sibling
``create_error_response`` call sites in the same module) NAME a Mollie refusal
that ``webhook_wrapper_service_unified._activate_donation_subscription``
classifies as permanent-vs-retryable. Before this fix the two sides agreed
only by spelling -- five string literals typed out independently in each
file, with no shared constant and no compiler to catch a rename on one side
and not the other.

This test does not merely restate today's spelling on both sides (that would
be tautological and would still pass after a shared-source regression). It
proves the *coupling*: the consumer's classification is driven by mutating
the ONE shared object, not by a copy. If a future edit reintroduces an
independent hardcoded tuple in the consumer, the mutation in
``test_consumer_classification_is_driven_by_the_shared_set_not_a_copy`` has
no effect and the assertion fails.
"""

import unittest
from unittest.mock import patch

from mollie.api.error import BadRequestError

from verenigingen.verenigingen_payments.mollie.services import (
    webhook_wrapper_service_unified as wrapper,
)
from verenigingen.verenigingen_payments.mollie.utils import (
    subscription_activation_reasons as reasons,
)
from verenigingen.verenigingen_payments.utils import payment_gateways


class TestPermanentRefusalReasonsShareOneSource(unittest.TestCase):
    def test_producer_reasons_are_members_of_the_shared_set(self):
        """Every reason payment_gateways can hand back names a shared constant.

        Not just "equals a string" -- equals the SAME constant the consumer
        will check membership against, so a typo on either side shows up as
        two different objects rather than two strings that merely read alike.
        """
        conflict_error = BadRequestError(
            {"status": 400, "title": "Bad Request", "detail": "conflict"},
            idempotency_key="donsub-x",
        )
        plain_error = BadRequestError({"status": 400, "title": "Bad Request", "detail": "plain"})

        self.assertEqual(
            payment_gateways._permanent_refusal_reason(conflict_error),
            reasons.IDEMPOTENCY_KEY_CONFLICT,
        )
        self.assertEqual(
            payment_gateways._permanent_refusal_reason(plain_error),
            reasons.MOLLIE_BAD_REQUEST,
        )

    def test_consumer_classification_is_driven_by_the_shared_set_not_a_copy(self):
        """Removing a reason from the shared set must flip the consumer's verdict.

        This is the mutation that proves the coupling is real: if
        ``webhook_wrapper_service_unified`` still carries its own hardcoded
        tuple of reason strings, patching the shared module's set changes
        nothing here, and the ``assertFalse`` below fails.
        """
        self.assertTrue(wrapper.is_permanent_subscription_refusal(reasons.INVALID_INTERVAL))

        with patch.object(
            reasons,
            "PERMANENT_SUBSCRIPTION_ACTIVATION_REASONS",
            frozenset({reasons.MOLLIE_BAD_REQUEST}),
        ):
            self.assertFalse(
                wrapper.is_permanent_subscription_refusal(reasons.INVALID_INTERVAL),
                "the consumer must read the shared set live, not a copy taken at import time",
            )

    def test_shared_set_names_exactly_the_five_documented_reasons(self):
        """Locks the set's membership so a silent addition/removal is visible here."""
        self.assertEqual(
            reasons.PERMANENT_SUBSCRIPTION_ACTIVATION_REASONS,
            frozenset(
                {
                    reasons.INVALID_INTERVAL,
                    reasons.MISSING_SUBSCRIPTION_DETAILS,
                    reasons.MISSING_CUSTOMER_ID,
                    reasons.IDEMPOTENCY_KEY_CONFLICT,
                    reasons.MOLLIE_BAD_REQUEST,
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
