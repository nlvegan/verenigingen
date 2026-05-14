"""Real-DB integration tests for MijnRoodVolunteerSyncService.

Pure-function tests (_parse_mijnrood_roles) don't need a real DB but
live here for cohesion. Tests for ensure_volunteer / ensure_*_membership
/ end_*_membership / _process_member_roles use EnhancedTestCase with
real Chapter + Team + Volunteer + User fixtures.
"""

import json

import frappe

from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
    get_volunteer_sync_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.event_application._fixtures import _FakeOrchestrator


class TestParseMijnRoodRoles(EnhancedTestCase):
    """Static-method JSON parser for the MijnRood roles column."""

    def test_returns_empty_set_for_none(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles(None)
        self.assertEqual(result, set())

    def test_returns_empty_set_for_empty_string(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles("")
        self.assertEqual(result, set())

    def test_parses_json_array_string(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles('["ROLE_ADMIN", "ROLE_DIVISION_CONTACT"]')
        self.assertEqual(result, {"ROLE_ADMIN", "ROLE_DIVISION_CONTACT"})

    def test_passes_through_python_list(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles(["ROLE_ADMIN"])
        self.assertEqual(result, {"ROLE_ADMIN"})

    def test_filters_non_role_entries(self):
        # Only entries starting with "ROLE_" survive — other strings dropped
        result = get_volunteer_sync_service()._parse_mijnrood_roles(
            '["ROLE_ADMIN", "SOMETHING_ELSE", "ROLE_DIVISION_CONTACT"]'
        )
        self.assertEqual(result, {"ROLE_ADMIN", "ROLE_DIVISION_CONTACT"})

    def test_returns_empty_set_for_malformed_json(self):
        result = get_volunteer_sync_service()._parse_mijnrood_roles("not-valid-json")
        self.assertEqual(result, set())
