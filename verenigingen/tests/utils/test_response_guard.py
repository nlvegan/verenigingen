# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""#1983: a test that replaces ``frappe.local.response`` must not break a later ``run_doc_method``.

Ordered pairs use the alphabetical method order unittest applies: ``test_1`` pollutes (as the
real webhook tests do, with a bare ``frappe._dict()`` and no restore), ``test_2`` is the next
test in the same process and calls the real ``frappe.handler.run_doc_method``, which ends with
``frappe.response.docs.append(doc)``.
"""

import unittest
from types import SimpleNamespace

import frappe
from frappe.handler import run_doc_method

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.response_guard import guard_local_response


def _pollute_response():
    frappe.local.response = frappe._dict()


def _run_doc_method_victim(test):
    """The real handler path; User.populate_role_profile_roles is whitelisted and a no-op for
    Administrator (no role profiles), so only the response bookkeeping is under test."""
    previous_request = getattr(frappe.local, "request", None)
    test.addCleanup(setattr, frappe.local, "request", previous_request)
    frappe.local.request = SimpleNamespace(
        method="POST", path="/api/method/run_doc_method", headers={}, remote_addr="127.0.0.1",
        environ={}, args={}, form={}, get_data=lambda *a, **k: b"{}", content_length=2,
    )
    run_doc_method(method="populate_role_profile_roles", dt="User", dn="Administrator")
    return frappe.local.response


class TestVereningingenBaseKeepsResponseUsable(VereningingenTestCase):
    def test_1_polluter(self):
        _pollute_response()
        self.assertIsNone(frappe.local.response.get("docs"), "control: the polluter must drop docs")

    def test_2_run_doc_method_after_a_polluter(self):
        response = _run_doc_method_victim(self)
        self.assertEqual(len(response["docs"]), 1)


class TestEnhancedBaseKeepsResponseUsable(EnhancedTestCase):
    def test_1_polluter(self):
        _pollute_response()
        self.assertIsNone(frappe.local.response.get("docs"), "control: the polluter must drop docs")

    def test_2_run_doc_method_after_a_polluter(self):
        response = _run_doc_method_victim(self)
        self.assertEqual(len(response["docs"]), 1)


class TestGuardOnAPlainTestCase(unittest.TestCase):
    """Guard behaviour in isolation, driven through a probe so the guard's own cleanup runs."""

    def _run_probe(self, body):
        class _Probe(unittest.TestCase):
            def setUp(self):
                guard_local_response(self)

            def runTest(self):
                body(self)

        result = unittest.TestResult()
        _Probe().run(result)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_a_response_left_bare_by_a_guardless_polluter_is_normalised_at_setup(self):
        original = frappe.local.response
        self.addCleanup(setattr, frappe.local, "response", original)
        _pollute_response()  # what a plain FrappeTestCase polluter leaves behind, no guard involved
        seen = {}
        self._run_probe(lambda probe: seen.update(docs=frappe.local.response.get("docs")))
        self.assertEqual(seen["docs"], [])

    def test_cleanup_restores_the_original_object_and_its_contents(self):
        original = frappe._dict(docs=["kept"], marker="before", headers={"Pragma": "kept"})
        self.addCleanup(setattr, frappe.local, "response", frappe.local.response)
        frappe.local.response = original

        def body(probe):
            frappe.local.response = frappe._dict()  # replaced wholesale ...
            original["http_status_code"] = 500  # ... and mutated in place
            original["docs"].append("appended by run_doc_method")
            original["headers"]["Cache-Control"] = "leaked"  # brand_css pages write here

        self._run_probe(body)
        self.assertIs(frappe.local.response, original)
        self.assertEqual(dict(original), {"docs": ["kept"], "marker": "before", "headers": {"Pragma": "kept"}})
