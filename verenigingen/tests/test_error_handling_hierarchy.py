"""
Regression tests for the verenigingen exception hierarchy
=========================================================

Specifically guards the ``PermissionError`` fix that closes the
hierarchy + HTTP status mismatch documented in PR #104 / follow-up
PR for issue 2 of the rate-limit handoff:

1. The previous ``PermissionError(VerenigingenException)`` inherited
   ``http_status_code = 417`` from ``frappe.ValidationError`` and
   ``isinstance(e, frappe.PermissionError)`` returned False.
2. ``self.http_status = 403`` on the instance was dead — Frappe reads
   the class attribute ``http_status_code`` via ``app.py:346``.

The fix multi-inherits from ``frappe.PermissionError`` and sets the
class attribute. These tests pin both properties so a future refactor
of the hierarchy can't silently regress either.
"""

import unittest

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.error_handling import (
    ConfigurationError,
    PermissionError as VPermissionError,
    ValidationError as VValidationError,
    VerenigingenException,
)


class TestPermissionErrorHierarchy(VereningingenTestCase):
    """Pins the PermissionError MRO so the HTTP status + isinstance
    contracts can't silently regress."""

    def test_http_status_code_is_403_not_417(self):
        """Frappe reads exc.http_status_code (class attribute) via
        ``apps/frappe/frappe/app.py:346`` — must be 403, not the 417
        inherited via frappe.ValidationError."""
        exc = VPermissionError("Access denied")
        # Class attribute, matching what Frappe's getattr() reads.
        self.assertEqual(exc.http_status_code, 403)
        # Also accessible via the class itself (no instance needed).
        self.assertEqual(VPermissionError.http_status_code, 403)

    def test_isinstance_frappe_permission_error_true(self):
        """except frappe.PermissionError sites (Frappe core uses this
        in client.py:488, permissions.py:892; this codebase has 24+
        such sites) must now catch our exception."""
        exc = VPermissionError("Access denied")
        self.assertIsInstance(exc, frappe.PermissionError)

    def test_isinstance_frappe_validation_error_still_true(self):
        """Back-compat: existing ``except frappe.ValidationError`` sites
        that previously caught our PermissionError (via
        VerenigingenException → frappe.ValidationError) must continue to.
        We don't want silent breakage of broad catch sites."""
        exc = VPermissionError("Access denied")
        self.assertIsInstance(exc, frappe.ValidationError)

    def test_isinstance_verenigingen_exception_still_true(self):
        """Back-compat: ``except VerenigingenException`` at
        error_handling.py:455 (and aliases like VPermissionError /
        VerenigingenPermissionError used across security modules) must
        keep catching."""
        exc = VPermissionError("Access denied")
        self.assertIsInstance(exc, VerenigingenException)

    def test_other_subclasses_still_417(self):
        """Targeted fix: only PermissionError gets 403. ValidationError
        and other VerenigingenException subclasses must keep their
        inherited 417 from frappe.ValidationError."""
        # ValidationError and ConfigurationError both inherit http_status_code
        # from frappe.ValidationError (the base of VerenigingenException).
        self.assertEqual(VValidationError("x").http_status_code, 417)
        self.assertEqual(ConfigurationError("x").http_status_code, 417)

    def test_validation_error_is_not_frappe_permission_error(self):
        """Targeted fix: only PermissionError gains the
        frappe.PermissionError lineage. ValidationError stays a pure
        ValidationError so its catch-routing doesn't change."""
        exc = VValidationError("x")
        self.assertNotIsInstance(exc, frappe.PermissionError)

    def test_metadata_attributes_preserved(self):
        """The fix must not break the structured-error metadata that
        VerenigingenException provides (error_code, http_status,
        details). These power the API response and audit logging
        layers."""
        exc = VPermissionError(
            message="Cannot edit national board",
            error_code="CHAPTER_BOARD_NATIONAL",
            details={"user": "test@example.com", "chapter": "national"},
        )
        self.assertEqual(exc.error_code, "CHAPTER_BOARD_NATIONAL")
        self.assertEqual(exc.http_status, 403)  # instance attr, separate from http_status_code
        self.assertEqual(exc.details, {"user": "test@example.com", "chapter": "national"})

    def test_raise_and_catch_via_frappe_permission_error(self):
        """End-to-end: raising VPermissionError and catching as
        frappe.PermissionError works. This is the primary behavior
        change the fix enables."""
        with self.assertRaises(frappe.PermissionError):
            raise VPermissionError("denied")

    def test_raise_and_catch_via_frappe_validation_error_back_compat(self):
        """End-to-end back-compat: existing catch-as-ValidationError
        sites still fire."""
        with self.assertRaises(frappe.ValidationError):
            raise VPermissionError("denied")


if __name__ == "__main__":
    unittest.main()
