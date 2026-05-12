"""Real-DB integration tests for MijnRoodMappingService.

extract_email() is tested as a pure helper; map_member_fields() and
resolve_division_id() require Chapter / MijnRood Sync State fixtures.
"""

import frappe

from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    extract_email,
    get_mapping_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExtractEmail(EnhancedTestCase):
    """extract_email is a pure helper — no DB needed but kept here for cohesion."""

    def test_returns_value_for_valid_email_string(self):
        self.assertEqual(extract_email("alice@example.org"), "alice@example.org")

    def test_returns_none_for_numeric_string(self):
        # MijnRood's email_id column sometimes contains a numeric FK
        self.assertIsNone(extract_email("12345"))

    def test_returns_none_for_string_without_at_sign(self):
        self.assertIsNone(extract_email("not-an-email"))

    def test_returns_none_for_none(self):
        self.assertIsNone(extract_email(None))

    def test_returns_none_for_integer(self):
        self.assertIsNone(extract_email(12345))

    def test_returns_none_for_empty_string(self):
        self.assertIsNone(extract_email(""))
