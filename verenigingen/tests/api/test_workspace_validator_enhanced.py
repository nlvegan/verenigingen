"""
Real integration tests for the enhanced workspace validator.

Target: verenigingen/api/workspace_validator_enhanced.py

These tests exercise EnhancedWorkspaceValidator against the REAL committed
fixtures file (verenigingen/fixtures/workspace.json), the REAL module workspace
JSON files on disk, and REAL Workspace documents in the database. No business
logic is mocked.

The validator is a read-only auditor, so most tests either:
  * assert it validates the real committed workspaces without hard errors, or
  * create a Workspace with a deliberately-broken link (persisted via
    ignore_links so the framework's own link validation does not block us) and
    assert the validator flags it.
"""

import os

import frappe

from verenigingen.api.workspace_validator_enhanced import (
    EnhancedWorkspaceValidator,
    validate_workspaces_enhanced,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestWorkspaceValidatorEnhanced(VereningingenTestCase):
    """Integration tests for the enhanced workspace validator."""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _make_workspace_with_links(self, title, links):
        """Persist a Workspace with the given links.

        ignore_links=True lets us store intentionally-broken links (the point of
        several tests) that Frappe's own link validation would otherwise reject.
        """
        ws = frappe.new_doc("Workspace")
        ws.title = title
        ws.label = title
        ws.public = 1
        for link in links:
            ws.append("links", link)
        ws.insert(ignore_permissions=True, ignore_links=True)
        self.track_doc("Workspace", ws.name)
        return ws

    # ------------------------------------------------------------------ #
    # Return shape / real-data sanity
    # ------------------------------------------------------------------ #
    def test_whitelisted_fn_returns_expected_structure(self):
        """The whitelisted entrypoint returns the documented summary dict."""
        result = validate_workspaces_enhanced()

        self.assertIsInstance(result, dict)
        for key in ("status", "errors", "warnings", "info", "summary"):
            self.assertIn(key, result)

        self.assertIn(result["status"], ("passed", "failed"))
        self.assertIsInstance(result["errors"], list)
        self.assertIsInstance(result["warnings"], list)
        self.assertIsInstance(result["info"], list)

        summary = result["summary"]
        self.assertEqual(summary["error_count"], len(result["errors"]))
        self.assertEqual(summary["warning_count"], len(result["warnings"]))
        self.assertEqual(summary["info_count"], len(result["info"]))

    def test_real_committed_workspaces_have_no_errors(self):
        """The real committed workspaces (fixtures + DB) must validate cleanly.

        This is a regression guard: if someone points a shipped workspace link
        at a non-existent DocType, this test fails.
        """
        result = validate_workspaces_enhanced()

        self.assertEqual(
            result["errors"],
            [],
            f"Committed workspaces produced validation errors: {result['errors']}",
        )
        self.assertEqual(result["status"], "passed")

    # ------------------------------------------------------------------ #
    # Fixtures loading from disk
    # ------------------------------------------------------------------ #
    def test_fixtures_file_is_read_from_disk(self):
        """The validator reads the committed fixtures/workspace.json file."""
        validator = EnhancedWorkspaceValidator()

        # The path it targets is the real committed fixtures file.
        self.assertTrue(validator.fixtures_path.endswith("fixtures/workspace.json"))
        self.assertTrue(
            os.path.exists(validator.fixtures_path),
            f"Fixtures file not found at {validator.fixtures_path}",
        )

        workspaces = validator._load_fixtures_workspaces()

        # The three committed top-level workspaces must be present.
        for expected in ("Verenigingen", "Verenigingen Payments", "E-Boekhouden"):
            self.assertIn(expected, workspaces)

        # And the info log records that it loaded from the main fixtures file.
        self.assertTrue(
            any("from main fixtures file" in msg for msg in validator.info),
            f"Expected a 'main fixtures file' info message, got: {validator.info}",
        )

    def test_database_workspaces_are_read(self):
        """_get_database_workspaces returns real Workspace rows with links."""
        validator = EnhancedWorkspaceValidator()
        db_workspaces = validator._get_database_workspaces()

        # There is always at least one workspace in a live site.
        self.assertGreater(len(db_workspaces), 0)
        # Structure sanity on an arbitrary entry.
        sample = next(iter(db_workspaces.values()))
        for key in ("name", "label", "public", "links"):
            self.assertIn(key, sample)
        self.assertIsInstance(sample["links"], list)

    # ------------------------------------------------------------------ #
    # Broken database link detection
    # ------------------------------------------------------------------ #
    def test_detects_broken_database_doctype_link(self):
        """A DB workspace linking to a non-existent DocType is reported as error."""
        title = "ZZ Test Broken Doctype WS"
        self._make_workspace_with_links(
            title,
            [{"type": "Link", "link_type": "DocType", "link_to": "NoSuchDoctypeXYZ", "label": "Bad"}],
        )

        result = validate_workspaces_enhanced()

        self.assertEqual(result["status"], "failed")
        matching = [e for e in result["errors"] if title in e and "NoSuchDoctypeXYZ" in e]
        self.assertTrue(
            matching,
            f"Expected an error about the broken DocType link, got: {result['errors']}",
        )

    def test_detects_broken_database_report_link(self):
        """A DB workspace linking to a non-existent Report is reported as warning."""
        title = "ZZ Test Broken Report WS"
        self._make_workspace_with_links(
            title,
            [{"type": "Link", "link_type": "Report", "link_to": "NoSuchReportXYZ", "label": "BadRep"}],
        )

        result = validate_workspaces_enhanced()

        matching = [w for w in result["warnings"] if title in w and "NoSuchReportXYZ" in w]
        self.assertTrue(
            matching,
            f"Expected a warning about the broken Report link, got: {result['warnings']}",
        )

    def test_valid_database_doctype_link_produces_no_error(self):
        """A DB workspace linking to a real DocType must NOT be flagged."""
        title = "ZZ Test Valid Doctype WS"
        self._make_workspace_with_links(
            title,
            [{"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Member"}],
        )

        result = validate_workspaces_enhanced()

        offending = [e for e in result["errors"] if title in e]
        self.assertEqual(
            offending,
            [],
            f"Valid DocType link should not produce errors, got: {offending}",
        )

    # ------------------------------------------------------------------ #
    # Fixtures-only DocType directory validation (hardcoded-path bug fix)
    # ------------------------------------------------------------------ #
    def test_fixtures_workspace_resolves_doctype_dir_under_app_path(self):
        """Regression guard for the previously hardcoded /home/frappe path.

        _validate_fixtures_workspace resolves a DocType link to its on-disk
        directory. It must use the real app path (self.app_path), so a genuine
        verenigingen DocType such as 'Member' resolves and produces NO error.
        """
        validator = EnhancedWorkspaceValidator()
        workspace = {
            "name": "ZZ Fixtures Only WS",
            "links": [{"link_type": "DocType", "link_to": "Member", "label": "Member"}],
        }

        validator._validate_fixtures_workspace("ZZ Fixtures Only WS", workspace)

        self.assertEqual(
            validator.errors,
            [],
            f"Real verenigingen DocType 'Member' should resolve on disk, got: {validator.errors}",
        )

    def test_fixtures_workspace_flags_missing_doctype_dir(self):
        """A fixtures workspace with a non-existent DocType dir is flagged."""
        validator = EnhancedWorkspaceValidator()
        workspace = {
            "name": "ZZ Fixtures Bad WS",
            "links": [{"link_type": "DocType", "link_to": "NoSuchDoctypeXYZ", "label": "Bad"}],
        }

        validator._validate_fixtures_workspace("ZZ Fixtures Bad WS", workspace)

        self.assertTrue(
            any("NoSuchDoctypeXYZ" in e for e in validator.errors),
            f"Expected an error about the missing DocType directory, got: {validator.errors}",
        )
