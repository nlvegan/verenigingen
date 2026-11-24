"""#2895: coverage for the ``__wrapped__`` branch of
``FrappeWhitelistAdapter.get_allowed_http_methods``.

Uses the REAL ``frappe.whitelist`` registry and real ``functools.wraps``
wrappers (which set ``__wrapped__``), not a mock of the registry. The branch
matters because a non-re-registering outer decorator (plain ``@wraps``) sits
between a security decorator and the whitelisted function: without the branch
the inner function's GET-only restriction is lost and the wrapper silently
falls back to the POST default.
"""

import functools

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.security.frappe_whitelist_adapter import FrappeWhitelistAdapter


def _plain_wrap_2895(inner):
    """A decorator that wraps WITHOUT registering (like handle_api_error)."""

    @functools.wraps(inner)
    def outer(*args, **kwargs):
        return inner(*args, **kwargs)

    return outer


class TestWhitelistAdapterWrappedMethods2895(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.adapter = FrappeWhitelistAdapter()
        self._added = []

    def tearDown(self):
        for fn in self._added:
            frappe.whitelisted.discard(fn)
            frappe.allowed_http_methods_for_whitelisted_func.pop(fn, None)
        super().tearDown()

    def _track(self, *fns):
        self._added.extend(fns)

    def _whitelisted_get_only(self):
        @frappe.whitelist(methods=["GET"])
        def inner_2895():
            return 1

        self._track(inner_2895)
        return inner_2895

    def test_wrapped_registered_inner_methods_are_returned(self):
        inner = self._whitelisted_get_only()
        outer = _plain_wrap_2895(inner)
        self._track(outer)

        self.assertIs(outer.__wrapped__, inner)
        self.assertNotIn(outer, frappe.allowed_http_methods_for_whitelisted_func)
        self.assertEqual(self.adapter.get_allowed_http_methods(outer), ["GET"])

    def test_wrapped_unregistered_inner_returns_none(self):
        def bare_2895():
            return 1

        outer = _plain_wrap_2895(bare_2895)
        self.assertIs(outer.__wrapped__, bare_2895)
        self.assertIsNone(self.adapter.get_allowed_http_methods(outer))

    def test_direct_registration_wins_over_wrapped(self):
        inner = self._whitelisted_get_only()
        outer = _plain_wrap_2895(inner)
        frappe.allowed_http_methods_for_whitelisted_func[outer] = ["PUT"]
        self._track(outer)

        self.assertEqual(self.adapter.get_allowed_http_methods(outer), ["PUT"])

    def test_register_wrapper_keeps_inner_get_restriction_not_post_default(self):
        inner = self._whitelisted_get_only()
        outer = _plain_wrap_2895(inner)
        self._track(outer)

        def security_wrapper_2895():
            pass

        self._track(security_wrapper_2895)
        self.adapter.register_http_methods(security_wrapper_2895, outer)

        self.assertEqual(
            frappe.allowed_http_methods_for_whitelisted_func[security_wrapper_2895], ["GET"]
        )
