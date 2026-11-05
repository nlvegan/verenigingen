"""
#2062: ``boot.boot_session`` ran ``enable_test_email_mocking()`` and set ``frappe.flags.mute_emails``
whenever ``in_test`` was set, and nothing ever undid either. A test that triggers a real session boot
therefore left ``frappe.sendmail`` replaced by ``mock_sendmail`` (and mail muted) for the rest of the
process, so every later test asserting on an Email Queue row failed (the #2060 shape).

Tests that want a mock install their own in scope, so a session boot must change neither.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen import boot
from verenigingen.tests.utils import test_config


class TestBootSessionLeavesSendmailAlone(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Mock justified: the process-wide frappe.sendmail swap is the state under test; the true
        # original and the harness bookkeeping are put back by the cleanup.
        saved = (frappe.sendmail, test_config._original_sendmail, frappe.flags.get("mute_emails"))
        self.addCleanup(self._put_back, saved)
        # a distinct stand-in for "the real sendmail" so an identity check cannot pass by luck
        self.real = lambda *a, **k: "real"
        frappe.sendmail = self.real
        test_config._original_sendmail = None
        frappe.flags.in_test = True
        frappe.flags.mute_emails = False

    @staticmethod
    def _put_back(saved):
        frappe.sendmail, test_config._original_sendmail, frappe.flags.mute_emails = saved

    def test_boot_session_does_not_replace_sendmail(self):
        bootinfo = frappe._dict()
        self.assertIs(boot.boot_session(bootinfo), bootinfo)
        self.assertIs(frappe.sendmail, self.real, "boot_session left frappe.sendmail mocked")
        self.assertIsNone(test_config._original_sendmail)

    def test_boot_session_does_not_mute_emails(self):
        boot.boot_session(frappe._dict())
        self.assertFalse(frappe.flags.mute_emails, "boot_session left mail muted for the process")

    def test_real_session_boot_does_not_replace_sendmail(self):
        """Drive the framework's own boot path, which calls the boot_session hook."""
        from frappe.boot import get_bootinfo

        get_bootinfo()
        self.assertIs(frappe.sendmail, self.real, "get_bootinfo left frappe.sendmail mocked")
