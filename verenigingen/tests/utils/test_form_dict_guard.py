# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""#1991: a test that assigns the MODULE attribute ``frappe.form_dict`` must not leak it.

The ordered pairs below use the alphabetical method order unittest applies: ``test_1``
pollutes, ``test_2`` is the next test in the same process.
"""

import unittest

import frappe
from frappe.utils.local import LocalProxy

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.form_dict_guard import guard_form_dict


def _is_proxy():
    return isinstance(frappe.__dict__["form_dict"], LocalProxy)


def _pollute():
    frappe.form_dict = frappe._dict({"doctype": "Member", "docname": "stale"})


class TestVereningingenBaseRestoresFormDict(VereningingenTestCase):
    def test_1_polluter(self):
        _pollute()
        self.assertFalse(_is_proxy(), "control: the polluter must really replace the proxy")

    def test_2_next_test_sees_proxy(self):
        self.assertTrue(_is_proxy())
        frappe.local.form_dict = frappe._dict({"marker": "x"})
        self.assertEqual(frappe.form_dict.get("marker"), "x")


class TestEnhancedBaseRestoresFormDict(EnhancedTestCase):
    def test_1_polluter(self):
        _pollute()
        self.assertFalse(_is_proxy(), "control: the polluter must really replace the proxy")

    def test_2_next_test_sees_proxy(self):
        self.assertTrue(_is_proxy())


class TestGuardCleanupRestoresAfterTheTest(unittest.TestCase):
    """The LAST polluter of a class has no 'next setUp' in its own class to fix it up;
    only the cleanup protects whatever class runs next (even a plain FrappeTestCase)."""

    def test_cleanup_restores_proxy_after_a_polluting_test(self):
        class _Probe(unittest.TestCase):
            def setUp(self):
                guard_form_dict(self)

            def runTest(self):
                _pollute()

        result = unittest.TestResult()
        _Probe().run(result)
        self.assertTrue(result.wasSuccessful(), result.errors)
        self.assertTrue(_is_proxy())
