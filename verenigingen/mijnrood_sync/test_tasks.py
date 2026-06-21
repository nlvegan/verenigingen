# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Tests for the MijnRood scheduled-task entry point.

run_mijnrood_sync() is the scheduler hook. Its only logic is the enabled-gate:
when MijnRood Sync Settings.enabled is off it must return EARLY without
touching the polling service; when on it delegates to the polling service's
run_sync().

The polling service's run_sync() connects to the remote MijnRood DB over an
SSH tunnel — that is the genuine external boundary, so it (and only it) is
mocked here. The enabled-gate itself is exercised against the real Settings
Single, not a mock.
"""

from unittest.mock import patch

import frappe

from verenigingen.mijnrood_sync import tasks
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestRunMijnRoodSyncTask(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("MijnRood Sync Settings")
        self._orig_enabled = self.settings.enabled

    def tearDown(self):
        frappe.db.set_single_value("MijnRood Sync Settings", "enabled", self._orig_enabled)
        frappe.db.commit()
        super().tearDown()

    def _set_enabled(self, value):
        frappe.db.set_single_value("MijnRood Sync Settings", "enabled", 1 if value else 0)
        frappe.db.commit()

    def test_disabled_does_not_invoke_polling_service(self):
        """The enabled-gate: when disabled the task returns early and the
        remote-connecting run_sync() is NEVER called."""
        self._set_enabled(False)
        # Patch the real remote boundary (the SSH/DB-connecting method).
        with patch(
            "verenigingen.mijnrood_sync.services.polling_service.MijnRoodPollingService.run_sync"
        ) as mock_run:
            result = tasks.run_mijnrood_sync()
        self.assertIsNone(result)
        mock_run.assert_not_called()

    def test_enabled_delegates_to_polling_service(self):
        """When enabled the task delegates to polling_service.run_sync()."""
        self._set_enabled(True)
        with patch(
            "verenigingen.mijnrood_sync.services.polling_service.MijnRoodPollingService.run_sync",
            return_value={"new": 0},
        ) as mock_run:
            tasks.run_mijnrood_sync()
        mock_run.assert_called_once_with()

    def test_get_polling_service_returns_singleton(self):
        """tasks delegates via get_polling_service(); confirm that accessor
        returns a stable singleton so repeated scheduler ticks reuse state."""
        from verenigingen.mijnrood_sync.services.polling_service import (
            MijnRoodPollingService,
            get_polling_service,
        )

        first = get_polling_service()
        second = get_polling_service()
        self.assertIs(first, second)
        self.assertIsInstance(first, MijnRoodPollingService)
