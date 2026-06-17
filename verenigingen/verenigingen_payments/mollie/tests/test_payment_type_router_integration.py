"""
Integration tests (Tier-2) for PaymentTypeRouter
(verenigingen/verenigingen_payments/mollie/services/payment_type_router.py).

LIVE: PaymentTypeRouter / get_payment_router() is used by
mollie_debug_service.py, the mollie_bulk_payment_discovery page, and
webhook_wrapper_service_unified.py to dispatch webhook payments.

Credential-free pattern (matches test_dues_payment_processor_integration.py):
    __init__ builds a real MollieClient + a DuesPaymentProcessor + an
    OrderPaymentProcessor (all of which need Mollie Settings). The routing
    logic under test only calls self.classifier (the REAL credential-free
    PaymentClassifier, run against SimpleNamespace payments), self.mollie_client
    (only when no payment is pre-supplied), and the two processors. We bypass
    __init__ via object.__new__() and attach the REAL classifier plus
    SimpleNamespace fakes for the SDK client and the two downstream processors —
    so classify_payment and route_payment's branching run for real; only the
    processor/SDK boundaries are stubbed.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.domain.payment_classification import PaymentClassifier
from verenigingen.verenigingen_payments.mollie.services.payment_type_router import PaymentTypeRouter


def _payment(**kwargs):
    defaults = dict(
        id="tr_router_test",
        status="paid",
        amount={"value": "10.00", "currency": "EUR"},
        description="",
        subscription_id=None,
        customer_id=None,
        metadata={},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _router(*, payment=None, fetch_raises=None, dues=None, order=None):
    """PaymentTypeRouter without __init__; real classifier, stubbed boundaries."""
    router = object.__new__(PaymentTypeRouter)
    router.classifier = PaymentClassifier()

    def get(pid):
        if fetch_raises is not None:
            raise fetch_raises
        return payment

    router.mollie_client = SimpleNamespace(sdk_client=SimpleNamespace(payments=SimpleNamespace(get=get)))
    router.dues_processor = dues or SimpleNamespace()
    router.order_processor = order or SimpleNamespace()
    return router


class TestClassifyPayment(EnhancedTestCase):
    """classify_payment — real classifier, result dict shape."""

    def test_order_classification_shape(self):
        router = _router()
        result = router.classify_payment(_payment(description="Bestelling 2025-55986"))
        self.assertEqual(result["payment_type"], "order")
        self.assertEqual(result["matched_by"], "order_keyword_bestelling")
        self.assertIsNone(result["member_id"])
        self.assertIsNone(result["donor_id"])

    def test_unknown_classification_shape(self):
        router = _router()
        result = router.classify_payment(_payment(description="totally unrelated"))
        self.assertEqual(result["payment_type"], "unknown")
        self.assertEqual(result["matched_by"], "no_rule_matched")


class TestRoutePayment(EnhancedTestCase):
    """route_payment — branch dispatch by classified type."""

    def test_routes_order_to_order_processor(self):
        captured = {}

        def _process_order(payment_id, payment):
            captured["payment_id"] = payment_id
            return {"status": "success", "bank_transaction": "BT-1"}

        order = SimpleNamespace(process_order_payment=_process_order)
        payment = _payment(description="Bestelling 2025-55986")
        router = _router(payment=payment, order=order)

        result = router.route_payment("tr_order")
        self.assertEqual(result["processor"], "OrderPaymentProcessor")
        self.assertEqual(result["payment_type"], "order")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["bank_transaction"], "BT-1")
        self.assertEqual(captured["payment_id"], "tr_order")

    def test_routes_dues_to_dues_processor(self):
        # A payment whose customer_id matches a real Member classifies as dues.
        token = frappe.generate_hash()[:8]
        cid = f"cst_router_{token}"
        member = self.create_test_member(
            first_name="Router", last_name=f"Dues{token}", email=f"router.dues.{token}@example.com"
        )
        frappe.db.set_value("Member", member.name, "mollie_customer_id", cid)

        def _process_dues(payment_id, payment):
            return {"status": "success", "member": member.name}

        dues = SimpleNamespace(process_dues_payment=_process_dues)
        payment = _payment(customer_id=cid)
        router = _router(payment=payment, dues=dues)

        result = router.route_payment("tr_dues")
        self.assertEqual(result["processor"], "DuesPaymentProcessor")
        self.assertEqual(result["payment_type"], "dues")
        self.assertEqual(result["member"], member.name)

    def test_donation_branch_pending_implementation(self):
        # A payment whose customer_id matches a real Donor classifies as donation;
        # the router does not yet route it, returning pending_implementation.
        token = frappe.generate_hash()[:8]
        cid = f"cst_router_don_{token}"
        donation = self.create_test_donation(donor_email=f"router.don.{token}@example.com", amount=20.0)
        donor = frappe.db.get_value("Donation", donation.name, "donor")
        frappe.db.set_value("Donor", donor, "mollie_customer_id", cid)

        router = _router(payment=_payment(customer_id=cid))
        result = router.route_payment("tr_don")
        self.assertEqual(result["payment_type"], "donation")
        self.assertEqual(result["processor"], "DonationProcessor")
        self.assertEqual(result["status"], "pending_implementation")

    def test_unknown_type_is_error(self):
        router = _router(payment=_payment(description="mystery"))
        result = router.route_payment("tr_unknown")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["processor"], "none")
        self.assertIn("Cannot determine payment type", result["message"])

    def test_fetch_when_no_payment_supplied(self):
        # route_payment with no pre-fetched payment must fetch via the SDK.
        order = SimpleNamespace(process_order_payment=lambda payment_id, payment: {"status": "success"})
        payment = _payment(description="Bestelling 12345")
        router = _router(payment=payment, order=order)
        result = router.route_payment("tr_fetch")  # no payment kwarg -> fetch path
        self.assertEqual(result["payment_type"], "order")
        self.assertEqual(result["status"], "success")

    def test_fetch_failure_returns_error_result(self):
        # When the SDK fetch raises, route_payment swallows it into an error dict.
        router = _router(fetch_raises=RuntimeError("mollie down"))
        result = router.route_payment("tr_boom")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["processor"], "none")
        self.assertIn("mollie down", result["message"])
