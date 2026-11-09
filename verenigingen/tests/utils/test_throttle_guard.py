# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""#2256: VereningingenTestCase must not leave User creation exposed to "Throttled"."""

import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.throttle_guard import raise_throttle_user_limit

_KEY = "throttle_user_limit"


def _insert_user(tag):
    return frappe.get_doc(
        {
            "doctype": "User",
            "email": f"throttle.{tag}.{frappe.generate_hash(length=8)}@test.invalid",
            "first_name": "Throttle",
            "send_welcome_email": 0,
        }
    ).insert(ignore_permissions=True)


class TestBaseRaisesThrottleLimit(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Sites may carry throttle_user_limit in site_config (test_site_1/2 do, CI does not);
        # remove it so only the base class can be what keeps the limit out of the way.
        had = _KEY in frappe.local.conf
        old = frappe.local.conf.get(_KEY)
        frappe.local.conf.pop(_KEY, None)

        def restore():
            if had:
                frappe.local.conf[_KEY] = old
            else:
                frappe.local.conf.pop(_KEY, None)

        cls.addClassCleanup(restore)

    def test_a_61st_user_in_the_hour_is_not_throttled(self):
        current = frappe.local.conf.get(_KEY)
        frappe.local.conf[_KEY] = 1000000  # seeding must not throttle itself
        try:
            seeded = 0
            while frappe.db.get_creation_count("User", 60) <= 60:
                _insert_user("seed")
                seeded += 1
        finally:
            if current is None:
                frappe.local.conf.pop(_KEY, None)
            else:
                frappe.local.conf[_KEY] = current
        self.assertGreater(frappe.db.get_creation_count("User", 60), 60)
        # Real Users above the stock limit exist; the base class's own setUp state decides.
        _insert_user("over")  # raises ValidationError("Throttled") if the base left it armed


class TestRaiseThrottleUserLimitRestores(unittest.TestCase):
    def _run_probe(self):
        class _Probe(unittest.TestCase):
            def setUp(self):
                raise_throttle_user_limit(self)

            def runTest(self):
                _Probe.seen = frappe.local.conf.get(_KEY)

        result = unittest.TestResult()
        _Probe().run(result)
        self.assertTrue(result.wasSuccessful(), result.errors)
        return _Probe.seen

    def test_key_is_deleted_when_it_was_absent(self):
        had, old = _KEY in frappe.local.conf, frappe.local.conf.get(_KEY)
        frappe.local.conf.pop(_KEY, None)
        try:
            self.assertGreaterEqual(self._run_probe(), 1000000)
            self.assertNotIn(_KEY, frappe.local.conf)
        finally:
            if had:
                frappe.local.conf[_KEY] = old

    def test_a_deliberate_zero_survives(self):
        had, old = _KEY in frappe.local.conf, frappe.local.conf.get(_KEY)
        frappe.local.conf[_KEY] = 0
        try:
            self._run_probe()
            self.assertEqual(frappe.local.conf.get(_KEY), 0)
        finally:
            if had:
                frappe.local.conf[_KEY] = old
            else:
                frappe.local.conf.pop(_KEY, None)
