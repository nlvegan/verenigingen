# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""#2256: VereningingenTestCase must not leave User creation exposed to "Throttled"."""

import unittest
from unittest.mock import patch

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

    def test_a_user_above_the_hourly_limit_is_not_throttled(self):
        """The count is patched, not seeded: 61 real Users commit (User insert creates
        Contacts outside the class rollback) and leaked into later modules. Only the one
        User that must not be throttled is inserted for real, and removed again."""
        # Mock justified: drives the over-60 condition without leaving 61 committed Users;
        # the subject is the harness-raised limit in throttle_user_creation(), not row counting.
        with patch.object(frappe.db, "get_creation_count", return_value=10_000):
            user = _insert_user("over")  # raises ValidationError("Throttled") if armed
        self.addCleanup(_remove_user, user.name)
        self.assertTrue(frappe.db.exists("User", user.name))


def _remove_user(name):
    for contact in frappe.get_all("Contact", filters={"user": name}, pluck="name"):
        frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
    frappe.delete_doc("User", name, force=True, ignore_permissions=True)


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
