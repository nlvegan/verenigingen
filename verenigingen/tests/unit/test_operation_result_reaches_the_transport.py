"""A failing ``OperationResult`` that names an HTTP status must be delivered with it (#481).

``OperationResult.http_status`` was a number in the JSON body and nothing else: nothing in
``operation_result.py``, ``error_handling.py`` or ``api_security_framework.py`` assigned
``frappe.local.response["http_status_code"]``. So ``http_status=500`` shipped as **HTTP 200**
and every caller that checks the transport saw success.

**Where this is applied, and why there.** At the one place an ``OperationResult`` becomes a
response: the ``api_security_framework`` wrapper's ``to_dict`` conversion. The decorator
``@handle_api_error`` cannot do it -- endpoints also ``return OperationResult.fail(...)``
directly, never passing through its ``except`` branches, and nine such sites in
``payment_processing.py`` are exactly the ones whose status was being dropped.

**What actually changes, measured rather than estimated.** 1218 endpoints wear a security
decorator and 180 of them touch ``OperationResult`` -- but ``http_status`` is optional and
defaults to ``None``, and a result without one is left alone. The call sites that set it are:
the four branches of ``handle_api_error`` (so: the 50 endpoints wearing it, on any exception
they catch), the nine in ``payment_processing.py``, and ``volunteer_skills.py:250``. Every
other failure keeps its HTTP 200, which ``test_a_failure_without_a_status_is_left_alone``
pins -- without it this change would be indistinguishable from "every failure is now a 4xx".

**Durability is NOT what this changes.** ``frappe/app.py:428`` commits on POST/PUT/DELETE
whatever the response status is, so a 500 here does not mean nothing was written. Only the
raise added by part 1 reaches ``db.rollback(chain=True)`` at ``app.py:147``.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class TestTheStatusReachesTheResponse(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        frappe.local.response.pop("http_status_code", None)
        self.addCleanup(frappe.local.response.pop, "http_status_code", None)

    def _endpoint_returning(self, result):
        @critical_api(operation_type=OperationType.FINANCIAL)
        def endpoint():
            return result

        return endpoint

    def test_a_failure_carrying_a_status_sets_it_on_the_response(self):
        self._endpoint_returning(OperationResult.fail("denied", http_status=403))()

        self.assertEqual(403, frappe.local.response.get("http_status_code"))

    def test_a_failure_without_a_status_is_left_alone(self):
        """CONTROL, and the one that bounds this change. Most ``OperationResult.fail()`` calls
        in the app pass no ``http_status`` at all; if those started returning a 4xx this would
        be a far larger change than #481 asks for, and no other assertion here would see it."""
        self._endpoint_returning(OperationResult.fail("just a failure"))()

        # assertNotIn, not assertIsNone: writing the key with a None value would satisfy
        # assertIsNone while still being the wrong behaviour, so the weaker assertion could
        # not tell the ``if status:`` guard from its absence.
        self.assertNotIn("http_status_code", frappe.local.response)

    def test_a_success_carrying_a_status_is_still_delivered_as_a_success(self):
        """CONTROL for the ``success`` guard specifically.

        Constructed directly rather than via ``ok()``, which never sets ``http_status`` -- so
        an ``ok()`` result cannot tell the success guard from the ``if status:`` check below
        it, and this control would have been satisfied by a version with no success guard at
        all. ``chain()`` propagates ``http_status`` (``operation_result.py:432``), so a
        successful result carrying one is reachable."""
        self._endpoint_returning(OperationResult(success=True, data={"count": 1}, http_status=200))()

        self.assertNotIn("http_status_code", frappe.local.response)

    def test_the_status_from_handle_api_error_reaches_the_response_too(self):
        """Composition. ``handle_api_error`` builds the 403 and the security wrapper delivers
        it; a test of either frame alone says nothing about the pair, which is the mistake
        #475 boundaries 1+2 made."""

        @critical_api(operation_type=OperationType.FINANCIAL)
        @handle_api_error
        def endpoint():
            raise frappe.PermissionError("nope")

        self.expectErrorLog("PermissionError", "endpoint")
        result = endpoint()

        self.assertFalse(result["success"])
        self.assertEqual(403, frappe.local.response.get("http_status_code"))


class TestAnInnerFailureDoesNotColourTheOuterResponse(VereningingenTestCase):
    """These endpoints call each other, and the response status is one shared slot.

    ``volunteer_application.submit_volunteer_application`` is exactly this shape: it calls
    the ``submit_application`` endpoint, recovers from a failure, and deliberately returns
    ``OperationResult.ok(...)`` carrying a ``membership_application_error``. If the wrapper
    only ever *sets* the status, the inner 4xx is still sitting in
    ``frappe.local.response`` when the outer success is serialised, and
    ``frappe/utils/response.py:150`` consumes it -- so a recovered failure ships a success
    body with an error status.
    """

    def setUp(self):
        super().setUp()
        frappe.local.response.pop("http_status_code", None)
        self.addCleanup(frappe.local.response.pop, "http_status_code", None)

    def test_an_outer_success_clears_an_inner_failures_status(self):
        @critical_api(operation_type=OperationType.FINANCIAL)
        def inner():
            return OperationResult.fail("inner blew up", http_status=400)

        @critical_api(operation_type=OperationType.FINANCIAL)
        def outer():
            inner()  # recovered from, exactly as volunteer_application does
            return OperationResult.ok({"recovered": True})

        outer()

        self.assertNotIn("http_status_code", frappe.local.response)


class TestTheStatusSurvivesTheFlattener(VereningingenTestCase):
    """``payment_processing``'s three flattened endpoints lift ``error`` to the top level.

    Before #481 they carried ``http_status_code`` in the body by accident -- the misspelled
    kwarg landed in ``metadata`` and the flattener lifts ``meta``. Renaming it (part 2) moved
    the value into ``error``, which the flattener did not lift, so the body would have lost it
    silently. This keeps the body and the transport saying the same thing.
    """

    def test_the_flattened_body_carries_the_status(self):
        from verenigingen.api.payment_processing import _flatten_api_response

        envelope = OperationResult.fail("denied", http_status=403).to_dict(scrub_sensitive=True)
        flat = _flatten_api_response(envelope)

        self.assertIs(False, flat["success"])
        self.assertEqual(403, flat["http_status"])

    def test_a_flattened_success_has_no_status_key(self):
        """CONTROL. The lift must not invent a key on the success shape."""
        from verenigingen.api.payment_processing import _flatten_api_response

        envelope = OperationResult.ok({"count": 0}, message="none").to_dict(scrub_sensitive=True)
        flat = _flatten_api_response(envelope)

        self.assertNotIn("http_status", flat)
