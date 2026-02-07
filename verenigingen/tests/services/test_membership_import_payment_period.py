# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Tests for MembershipImportService payment period → dues schedule template wiring.

Verifies that the CSV Betaalperiode column is correctly resolved to a
Membership Dues Schedule template via Verenigingen Settings, and that
failures fall back gracefully to the membership type default.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.csv_import.membership_import_service import (
    MembershipImportService,
)


class TestMembershipImportPaymentPeriod(FrappeTestCase):
    """Tests for payment period → dues schedule template resolution."""

    def setUp(self):
        super().setUp()
        self.service = MembershipImportService()

    # ── Successful resolution ──────────────────────────────────────────

    def test_monthly_payment_period_sets_application_dues_schedule(self):
        """Maandelijks payment period sets application_dues_schedule on member doc."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-001"
        row_data = {"payment_period": "Maandelijks"}

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
            return_value="Monthly Dues Template",
        ) as mock_resolve, patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            self.service._create_membership_unified_path(member_doc, row_data)

        mock_resolve.assert_called_once_with(row_data)
        self.assertEqual(member_doc.application_dues_schedule, "Monthly Dues Template")

    def test_quarterly_payment_period_sets_template(self):
        """Kwartaal payment period resolves to quarterly template."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-002"
        row_data = {"payment_period": "Kwartaal"}

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
            return_value="Quarterly Dues Template",
        ), patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            self.service._create_membership_unified_path(member_doc, row_data)

        self.assertEqual(
            member_doc.application_dues_schedule, "Quarterly Dues Template"
        )

    def test_annual_payment_period_sets_template(self):
        """Jaarlijks payment period resolves to annual template."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-003"
        row_data = {"payment_period": "Jaarlijks"}

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
            return_value="Annual Dues Template",
        ), patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            self.service._create_membership_unified_path(member_doc, row_data)

        self.assertEqual(
            member_doc.application_dues_schedule, "Annual Dues Template"
        )

    # ── Fallback on failure ────────────────────────────────────────────

    def test_resolution_failure_falls_back_gracefully(self):
        """When template resolution raises, application_dues_schedule is NOT set."""
        member_doc = MagicMock(spec=["name", "selected_membership_type", "create_membership_on_approval"])
        member_doc.name = "TEST-MEMBER-004"
        row_data = {"payment_period": "Maandelijks"}

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
            side_effect=frappe.ValidationError("No template configured"),
        ), patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            # Should not raise — falls back silently
            self.service._create_membership_unified_path(member_doc, row_data)

        # application_dues_schedule should NOT have been set on the mock
        self.assertFalse(
            hasattr(member_doc, "application_dues_schedule"),
            "application_dues_schedule should not be set when resolution fails",
        )

    def test_resolution_failure_still_calls_create_membership(self):
        """Even when template resolution fails, membership creation proceeds."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-005"
        row_data = {"payment_period": "Onbekend"}

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
            side_effect=frappe.ValidationError("Unknown payment period"),
        ), patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ) as mock_create:
            self.service._create_membership_unified_path(member_doc, row_data)

        mock_create.assert_called_once()

    # ── Edge cases: missing / empty payment_period ─────────────────────

    def test_missing_payment_period_skips_resolution(self):
        """When payment_period key is absent, template resolution is skipped entirely."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-006"
        row_data = {"member_since": "2024-01-01"}  # no payment_period

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
        ) as mock_resolve, patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            self.service._create_membership_unified_path(member_doc, row_data)

        mock_resolve.assert_not_called()

    def test_empty_string_payment_period_skips_resolution(self):
        """Empty string payment_period is falsy — skips resolution."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-007"
        row_data = {"payment_period": ""}

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
        ) as mock_resolve, patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            self.service._create_membership_unified_path(member_doc, row_data)

        mock_resolve.assert_not_called()

    def test_none_payment_period_skips_resolution(self):
        """Explicit None payment_period skips resolution."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-008"
        row_data = {"payment_period": None}

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
        ) as mock_resolve, patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            self.service._create_membership_unified_path(member_doc, row_data)

        mock_resolve.assert_not_called()

    # ── Wrapper method fix ─────────────────────────────────────────────

    def test_get_dues_schedule_template_passes_dict_not_string(self):
        """get_dues_schedule_template() passes the full row_data dict, not just the string value."""
        row_data = {"payment_period": "Maandelijks", "other_field": "value"}

        with patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
            return_value="Monthly Template",
        ) as mock_fn:
            result = self.service.get_dues_schedule_template(row_data)

        # Must pass the entire dict, not row_data.get("payment_period")
        mock_fn.assert_called_once_with(row_data)
        self.assertEqual(result, "Monthly Template")

    # ── Integration: row_data flows through correctly ──────────────────

    def test_row_data_passed_unmodified_to_resolver(self):
        """The full row_data dict is passed to the resolver, not a subset."""
        member_doc = MagicMock()
        member_doc.name = "TEST-MEMBER-009"
        row_data = {
            "payment_period": "Maandelijks",
            "member_since": "2024-01-01",
            "dues_rate": "25.00",
        }

        captured_args = []

        def capture_call(data):
            captured_args.append(data)
            return "Monthly Template"

        with patch.object(
            self.service, "determine_membership_type", return_value="Regular"
        ), patch(
            "verenigingen.services.csv_import.membership_import_service"
            ".get_dues_schedule_template_from_payment_period",
            side_effect=capture_call,
        ), patch.object(
            member_doc, "create_membership_on_approval", return_value=None
        ):
            self.service._create_membership_unified_path(member_doc, row_data)

        self.assertEqual(len(captured_args), 1)
        self.assertIs(captured_args[0], row_data, "Should pass the exact same dict object")
