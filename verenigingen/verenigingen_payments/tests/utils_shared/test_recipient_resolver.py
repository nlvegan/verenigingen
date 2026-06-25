"""DB integration tests for get_recipients_by_roles."""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.shared.recipient_resolver import (
    get_recipients_by_roles,
)

# Unique prefix to avoid colliding with other test users that may exist.
_PREFIX = "rr-rslvr"


class TestGetRecipientsByRoles(EnhancedTestCase):
    """get_recipients_by_roles returns enabled-user emails for the given roles."""

    # ------------------------------------------------------------------ helpers

    def _make_enabled_user(self, tag: str, role: str) -> frappe.Document:
        """Create an enabled test User with *role* and track it for cleanup."""
        email = f"{_PREFIX}.{tag}.{frappe.generate_hash(length=6)}@test.invalid"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Rslvr"
        user.last_name = tag.capitalize()
        user.enabled = 1
        user.send_welcome_email = 0
        user.append("roles", {"role": role})
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user

    def _make_disabled_user(self, tag: str, role: str) -> frappe.Document:
        """Create a DISABLED test User with *role* and track it for cleanup."""
        email = f"{_PREFIX}.dis.{tag}.{frappe.generate_hash(length=6)}@test.invalid"
        user = frappe.new_doc("User")
        user.email = email
        user.first_name = "Disabled"
        user.last_name = tag.capitalize()
        user.enabled = 0
        user.send_welcome_email = 0
        user.append("roles", {"role": role})
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user

    # ------------------------------------------------------------------ tests

    def test_enabled_user_with_role_is_returned(self):
        """An enabled user holding the queried role appears in the result."""
        user = self._make_enabled_user("enabled", "System Manager")
        result = get_recipients_by_roles(["System Manager"])
        self.assertIn(user.email, result)

    def test_disabled_user_with_role_is_excluded(self):
        """A disabled user holding the queried role does NOT appear in the result."""
        user = self._make_disabled_user("disabled", "System Manager")
        result = get_recipients_by_roles(["System Manager"])
        self.assertNotIn(user.email, result)

    def test_multiple_roles_returns_union(self):
        """Users matching ANY of the listed roles are all returned."""
        user_a = self._make_enabled_user("multi-a", "System Manager")
        user_b = self._make_enabled_user("multi-b", "Guest")  # built-in role always exists
        result = get_recipients_by_roles(["System Manager", "Guest"])
        self.assertIn(user_a.email, result)
        self.assertIn(user_b.email, result)

    def test_result_is_sorted_and_deduplicated(self):
        """Returned list is sorted and contains no duplicate emails."""
        # Create two users with the same role to exercise deduplication logic.
        user_a = self._make_enabled_user("sort-a", "System Manager")
        user_b = self._make_enabled_user("sort-b", "System Manager")
        result = get_recipients_by_roles(["System Manager"])
        # Both must be present.
        self.assertIn(user_a.email, result)
        self.assertIn(user_b.email, result)
        # No duplicates.
        self.assertEqual(len(result), len(set(result)))
        # Must be sorted.
        self.assertEqual(result, sorted(result))

    def test_empty_role_list_returns_empty(self):
        """Passing an empty list returns an empty list without hitting the DB."""
        result = get_recipients_by_roles([])
        self.assertEqual(result, [])

    def test_unknown_role_returns_empty(self):
        """A role that no user holds returns an empty list."""
        result = get_recipients_by_roles(["__nonexistent_role_xyz__"])
        self.assertEqual(result, [])
