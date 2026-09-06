"""
Regression test for #374: initiate_refund()'s outer `except Exception` swallows
its own deliberate `frappe.throw(_("Payment ID is required"))` -- a plain
missing-parameter validation -- and replaces it with `"Internal refund
processing error"`, which mischaracterises a simple client mistake as a
server-side failure.

An existing test (test_mollie_unified_payment_api.py::TestInitiateRefund::
test_missing_payment_id_throws) only asserts the exception TYPE
(ValidationError) and passes either way -- both the specific and the generic
message raise ValidationError. This test asserts the MESSAGE.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.api import unified_payment_api


class TestInitiateRefundSwallowedThrow374(EnhancedTestCase):
    def test_missing_payment_id_message_is_not_genericized(self):
        with self.set_user("Administrator"):
            frappe.local.form_dict = frappe._dict()
            with self.assertRaises(frappe.ValidationError) as ctx:
                unified_payment_api.initiate_refund()

        # The endpoint's own validation message must reach the caller --
        # not the generic "Internal refund processing error" the surrounding
        # `except Exception` currently substitutes, which tells the caller
        # this was a server fault instead of a missing parameter.
        self.assertIn("Payment ID is required", str(ctx.exception))
