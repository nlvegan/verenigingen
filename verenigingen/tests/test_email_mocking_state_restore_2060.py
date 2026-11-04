"""
#2060: the harness's disable/restore pair for the process-wide ``frappe.sendmail`` mock must put
back EXACTLY the state it found.

The defect: ``disable_test_email_mocking()`` is a no-op when mocking is off, but the cleanup that
followed it, ``enable_test_email_mocking``, forced the mock ON, so every later test in the process
saw ``frappe.sendmail`` replaced and no Email Queue row ever appeared.

Each test starts from a state it sets itself and restores the true original on exit, so the module
leaves the process as it found it whichever state that was.
"""

import importlib.util

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.utils import test_config
from verenigingen.tests.utils.test_config import (
    disable_test_email_mocking,
    email_mocking_disabled,
    enable_test_email_mocking,
    mock_sendmail,
    restore_test_email_mocking,
)


class TestEmailMockingStateRestore(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Mock justified: this IS the harness's process-wide frappe.sendmail swap under test; the
        # real function and the module's bookkeeping are put back by the cleanup below.
        self._saved = (frappe.sendmail, test_config._original_sendmail)
        self.addCleanup(self._put_back)
        # a real, distinct stand-in for "the real sendmail" so identity checks cannot pass by luck
        self.real = lambda *a, **k: "real"
        self._set_state(mocked=False)

    def _put_back(self):
        frappe.sendmail, test_config._original_sendmail = self._saved

    def _set_state(self, mocked):
        if mocked:
            frappe.sendmail = self.real
            test_config._original_sendmail = None
            enable_test_email_mocking()
            self.assertIs(frappe.sendmail, mock_sendmail)
        else:
            frappe.sendmail = self.real
            test_config._original_sendmail = None

    def test_pair_started_with_mocking_off_leaves_it_off(self):
        was = disable_test_email_mocking()
        restore_test_email_mocking(was)
        self.assertIs(frappe.sendmail, self.real, "restore turned the mock ON in a process that had it off")

    def test_pair_started_with_mocking_on_puts_it_back_on(self):
        self._set_state(mocked=True)
        was = disable_test_email_mocking()
        self.assertIs(frappe.sendmail, self.real, "disable did not expose the real sendmail")
        restore_test_email_mocking(was)
        self.assertIs(frappe.sendmail, mock_sendmail, "restore did not re-enable a mock that was on")
        # and the bookkeeping still works: a later disable reaches the real function again
        disable_test_email_mocking()
        self.assertIs(frappe.sendmail, self.real)

    def test_context_manager_off_to_off(self):
        with email_mocking_disabled():
            self.assertIs(frappe.sendmail, self.real)
        self.assertIs(frappe.sendmail, self.real)

    def test_context_manager_on_to_on(self):
        self._set_state(mocked=True)
        with email_mocking_disabled():
            self.assertIs(frappe.sendmail, self.real)
        self.assertIs(frappe.sendmail, mock_sendmail)

    def test_context_manager_restores_after_an_exception(self):
        self._set_state(mocked=True)
        with self.assertRaises(RuntimeError):
            with email_mocking_disabled():
                raise RuntimeError("boom")
        self.assertIs(frappe.sendmail, mock_sendmail)

    def test_importing_the_module_does_not_install_the_mock(self):
        """The 1999 module imports test_config at collection time, with in_test set. The import
        used to enable the mock process-wide, so the module's own disable/restore pair then saw
        "was on" and restored it, leaving every later module with no Email Queue rows."""
        self.assertTrue(frappe.flags.get("in_test"), "the import side effect only fires in test context")
        # a throwaway copy, so this module's own globals (and the names imported above) stay intact
        spec = importlib.util.spec_from_file_location("_test_config_import_probe_2060", test_config.__file__)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        self.assertIs(frappe.sendmail, self.real, "importing test_config installed the sendmail mock")
        self.assertIsNone(fresh._original_sendmail)
