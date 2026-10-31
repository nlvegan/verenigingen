# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""#1758: a mail-sending test must not depend on which ``test_site_N`` it runs on.

``frappe.sendmail`` raises ``OutgoingEmailError`` when the site has no enabled default
outgoing account. CI's site config carries ``mail_server`` etc. so it always has one
(``EmailAccount.find_from_config``); local test sites 1, 4, 5 and 13 had none, so the
same tests failed here and passed in CI. The harness base classes now call
``ensure_outgoing_mail_account`` in ``setUpClass``.

Two things are checked, because each alone leaves a gap:

* the helper itself, against REAL site state with the DB accounts switched off, through
  the real ``frappe.sendmail`` (it must queue, never send);
* that BOTH base classes actually call it, driven through ``unittest`` the way a shard
  runs them. ``find_default_outgoing`` is patched to "no account" for that part only,
  because the DB cannot be damaged from inside a harness class (its rollback cleanup
  would undo the damage before the test body ran).
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.email.doctype.email_account.email_account import EmailAccount

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.outgoing_mail_guard import ensure_outgoing_mail_account

_NO_ACCOUNT = "frappe.email.doctype.email_account.email_account.EmailAccount.find_default_outgoing"


def _forget_cached_account():
    frappe.local.outgoing_email_account = {}


class TestEnsureOutgoingMailAccount(unittest.TestCase):
    def setUp(self):
        # Real site state: no enabled outgoing account of any kind, no conf account.
        self.addCleanup(frappe.db.rollback)
        frappe.db.sql("UPDATE `tabEmail Account` SET enable_outgoing = 0, default_outgoing = 0")
        self._saved_conf = {k: frappe.conf.pop(k, None) for k in ("mail_server", "mute_emails")}
        self.addCleanup(self._restore_conf)
        self.addCleanup(_forget_cached_account)
        _forget_cached_account()

    def _restore_conf(self):
        for key, value in self._saved_conf.items():
            if value is not None:
                frappe.conf[key] = value

    def _sendmail(self):
        frappe.sendmail(
            recipients=["guard.probe@example.org"],
            subject="outgoing mail guard probe",
            message="probe",
            delayed=True,
        )

    def test_without_the_guard_sendmail_refuses(self):
        """Control: the premise. With no account, sendmail raises."""
        with self.assertRaises(frappe.OutgoingEmailError):
            self._sendmail()

    def test_with_the_guard_sendmail_queues_and_sends_nothing(self):
        before = frappe.db.count("Email Queue", {"status": "Not Sent"})
        sent_before = frappe.db.count("Email Queue", {"status": "Sent"})

        class Probe(unittest.TestCase):
            def test_noop(self):
                pass

        ensure_outgoing_mail_account(Probe)
        self._sendmail()

        self.assertEqual(frappe.db.count("Email Queue", {"status": "Not Sent"}), before + 1)
        self.assertEqual(frappe.db.count("Email Queue", {"status": "Sent"}), sent_before)

    def test_cleanup_restores_conf_and_the_refusal(self):
        class Probe(unittest.TestCase):
            def test_noop(self):
                pass

        ensure_outgoing_mail_account(Probe)
        self.assertEqual(frappe.conf.get("mail_server"), "localhost")
        result = unittest.TestResult()
        unittest.TestLoader().loadTestsFromTestCase(Probe).run(result)  # runs class cleanups
        self.assertIsNone(frappe.conf.get("mail_server"))
        with self.assertRaises(frappe.OutgoingEmailError):
            self._sendmail()

    def test_it_is_a_noop_when_the_site_already_has_an_account(self):
        class Probe(unittest.TestCase):
            def test_noop(self):
                pass

        frappe.db.sql("UPDATE `tabEmail Account` SET enable_outgoing = 1, default_outgoing = 1 LIMIT 1")
        self.assertTrue(EmailAccount.find_default_outgoing())
        ensure_outgoing_mail_account(Probe)
        self.assertIsNone(frappe.conf.get("mail_server"))


class TestBaseClassesCallTheGuard(unittest.TestCase):
    """Each harness base class must apply the guard in ``setUpClass`` and undo it after."""

    def _observed_conf(self, base):
        seen = {}

        class Inner(base):
            def test_conf(self):
                seen["mail_server"] = frappe.conf.get("mail_server")

        # Mock justified: "this site has no outgoing account" cannot be built from inside
        # a harness class (its rollback cleanup undoes it); the guard's own behaviour
        # against a real empty site is covered by TestEnsureOutgoingMailAccount.
        with patch(_NO_ACCOUNT, return_value=None):
            result = unittest.TestResult()
            unittest.TestLoader().loadTestsFromTestCase(Inner).run(result)
        self.assertEqual(result.errors + result.failures, [])
        return seen

    def test_enhanced_test_case(self):
        self.assertEqual(self._observed_conf(EnhancedTestCase)["mail_server"], "localhost")
        self.assertIsNone(frappe.conf.get("mail_server"))

    def test_vereniging_test_case(self):
        self.assertEqual(self._observed_conf(VereningingenTestCase)["mail_server"], "localhost")
        self.assertIsNone(frappe.conf.get("mail_server"))
