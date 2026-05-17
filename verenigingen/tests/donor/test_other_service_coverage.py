"""
Test coverage for 4 additional services.

Services tested:
1. DocumentPortalService — document upload portal authorization and validation
2. TeamService + TeamValidationService — team management and validation
3. DonationDashboardService — donation dashboard data aggregation
4. AccountCreationService — user account creation for members
"""

import base64
import hashlib

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# 1. DocumentPortalService
# ---------------------------------------------------------------------------
class TestDocumentPortalService(EnhancedTestCase):
    """Tests for DocumentPortalService — authorization and file validation."""

    def _get_service(self):
        from verenigingen.services.document.document_portal_service import DocumentPortalService

        return DocumentPortalService()

    # --- get_upload_context ---
    def test_get_upload_context_returns_success(self):
        """get_upload_context returns success dict for any user."""
        svc = self._get_service()
        result = svc.get_upload_context(frappe.session.user)
        self.assertTrue(result.get("success"))
        self.assertIn("organizations", result)
        self.assertIn("categories", result)

    def test_get_upload_context_has_org_structure(self):
        """get_upload_context returns organizations grouped by type."""
        svc = self._get_service()
        result = svc.get_upload_context(frappe.session.user)
        orgs = result["organizations"]
        self.assertIn("chapters", orgs)
        self.assertIn("teams", orgs)
        self.assertIn("movements", orgs)

    def test_get_upload_context_nonexistent_user(self):
        """get_upload_context returns success even for user without member record."""
        svc = self._get_service()
        result = svc.get_upload_context("nonexistent@invalid.tld")
        # Should still return success (just empty organizations)
        self.assertTrue(result.get("success"))

    # --- can_upload_to ---
    def test_can_upload_admin_allowed(self):
        """can_upload_to returns True for System Manager."""
        svc = self._get_service()
        # Administrator has System Manager role
        result = svc.can_upload_to("Administrator", "Chapter", "SomeChapter")
        self.assertTrue(result)

    def test_can_upload_no_volunteer_denied(self):
        """can_upload_to returns False for user with no volunteer record."""
        svc = self._get_service()
        result = svc.can_upload_to("Guest", "Chapter", "SomeChapter")
        self.assertFalse(result)

    def test_can_upload_unknown_org_type(self):
        """can_upload_to returns False for unknown organization type."""
        svc = self._get_service()
        result = svc.can_upload_to("Guest", "UnknownType", "SomeName")
        self.assertFalse(result)

    # --- _validate_file ---
    def test_validate_file_missing_filename(self):
        """_validate_file rejects missing file name."""
        from verenigingen.services.document.document_portal_service import DocumentUploadRequest

        svc = self._get_service()
        req = DocumentUploadRequest(
            organization_type="Chapter", organization_name="Test",
            document_name="doc", document_type="Report",
            file_name="", file_content="", content_type="application/pdf",
        )
        result = svc._validate_file(req)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "missing_filename")

    def test_validate_file_invalid_extension(self):
        """_validate_file rejects disallowed file extension."""
        from verenigingen.services.document.document_portal_service import DocumentUploadRequest

        svc = self._get_service()
        req = DocumentUploadRequest(
            organization_type="Chapter", organization_name="Test",
            document_name="doc", document_type="Report",
            file_name="malware.exe", file_content="dGVzdA==", content_type="application/octet-stream",
        )
        result = svc._validate_file(req)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "invalid_file_type")

    def test_validate_file_valid_pdf(self):
        """_validate_file accepts a valid PDF upload request."""
        from verenigingen.services.document.document_portal_service import DocumentUploadRequest

        svc = self._get_service()
        req = DocumentUploadRequest(
            organization_type="Chapter", organization_name="Test",
            document_name="Annual Report", document_type="Report",
            file_name="report.pdf", file_content="dGVzdA==", content_type="application/pdf",
        )
        result = svc._validate_file(req)
        self.assertTrue(result["valid"])

    def test_validate_file_mime_extension_mismatch(self):
        """_validate_file rejects MIME/extension mismatch (spoofing prevention)."""
        from verenigingen.services.document.document_portal_service import DocumentUploadRequest

        svc = self._get_service()
        req = DocumentUploadRequest(
            organization_type="Chapter", organization_name="Test",
            document_name="doc", document_type="Report",
            file_name="image.png", file_content="dGVzdA==", content_type="application/pdf",
        )
        result = svc._validate_file(req)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "mime_extension_mismatch")

    def test_validate_file_too_large(self):
        """_validate_file rejects files exceeding size limit."""
        from verenigingen.services.document.document_portal_service import DocumentUploadRequest

        svc = self._get_service()
        # Create content that exceeds 10MB when decoded
        large_content = base64.b64encode(b"x" * (11 * 1024 * 1024)).decode()
        req = DocumentUploadRequest(
            organization_type="Chapter", organization_name="Test",
            document_name="big", document_type="Report",
            file_name="big.pdf", file_content=large_content, content_type="application/pdf",
        )
        result = svc._validate_file(req)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "file_too_large")

    # --- _normalize_document_name ---
    def test_normalize_document_name(self):
        """_normalize_document_name collapses whitespace and lowercases."""
        svc = self._get_service()
        self.assertEqual(svc._normalize_document_name("Annual  Report  2024"), "annual report 2024")
        self.assertEqual(svc._normalize_document_name(""), "")
        self.assertEqual(svc._normalize_document_name(None), "")

    # --- _clean_document_title ---
    def test_clean_document_title_replaces_dashes(self):
        """_clean_document_title replaces dashes with spaces when no spaces present."""
        svc = self._get_service()
        self.assertEqual(svc._clean_document_title("Annual-Report-2024"), "Annual Report 2024")

    def test_clean_document_title_replaces_underscores(self):
        """_clean_document_title replaces underscores with spaces."""
        svc = self._get_service()
        self.assertEqual(svc._clean_document_title("Annual_Report_2024"), "Annual Report 2024")

    def test_clean_document_title_preserves_spaces(self):
        """_clean_document_title does not alter titles with existing spaces."""
        svc = self._get_service()
        self.assertEqual(svc._clean_document_title("Report - 2024"), "Report - 2024")

    def test_clean_document_title_preserves_non_latin(self):
        """_clean_document_title preserves non-Latin script titles."""
        svc = self._get_service()
        self.assertEqual(svc._clean_document_title("---"), "---")

    def test_clean_document_title_empty(self):
        """_clean_document_title handles empty/None input."""
        svc = self._get_service()
        self.assertIsNone(svc._clean_document_title(None))
        self.assertEqual(svc._clean_document_title(""), "")

    # --- _compute_file_hash ---
    def test_compute_file_hash(self):
        """_compute_file_hash returns correct SHA256 hex digest."""
        svc = self._get_service()
        content = b"test content"
        expected = hashlib.sha256(content).hexdigest()
        self.assertEqual(svc._compute_file_hash(content), expected)

    # --- _get_member_for_user ---
    def test_get_member_for_user_none_for_unknown(self):
        """_get_member_for_user returns None for non-existent user."""
        svc = self._get_service()
        result = svc._get_member_for_user("nobody@invalid.tld")
        self.assertIsNone(result)

    # --- _get_volunteer_for_member ---
    def test_get_volunteer_for_member_none_for_none(self):
        """_get_volunteer_for_member returns None for None input."""
        svc = self._get_service()
        self.assertIsNone(svc._get_volunteer_for_member(None))


# ---------------------------------------------------------------------------
# 2. TeamService + TeamValidationService
# ---------------------------------------------------------------------------
class TestTeamService(EnhancedTestCase):
    """Tests for TeamService — team member operations and history."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="TeamSvc", last_name=f"S{self.uid}")

    def _get_service(self):
        from verenigingen.services.team_service import get_team_service

        return get_team_service()

    # --- sync_with_volunteers ---
    def test_sync_with_volunteers_returns_true(self):
        """sync_with_volunteers returns True for any team doc."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"SyncTeam-{self.uid}")
        result = svc.sync_with_volunteers(team)
        self.assertTrue(result)

    # --- validate_team_member_changes ---
    def test_validate_team_member_changes(self):
        """validate_team_member_changes returns True."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"ValTeam-{self.uid}")
        result = svc.validate_team_member_changes(team)
        self.assertTrue(result)

    # --- _get_role_description_for_history ---
    def test_get_role_description_default(self):
        """_get_role_description_for_history returns 'Team Member' as default."""
        svc = self._get_service()

        class FakeMember:
            team_role = None
            role_type = None
            role = None

        result = svc._get_role_description_for_history(FakeMember())
        self.assertEqual(result, "Team Member")

    def test_get_role_description_with_role_type(self):
        """_get_role_description_for_history uses role_type as fallback."""
        svc = self._get_service()

        class FakeMember:
            team_role = None
            role_type = "Coordinator"
            role = ""

        result = svc._get_role_description_for_history(FakeMember())
        self.assertEqual(result, "Coordinator")

    def test_get_role_description_with_role_append(self):
        """_get_role_description_for_history appends role description."""
        svc = self._get_service()

        class FakeMember:
            team_role = None
            role_type = "Lead"
            role = "Communications"

        result = svc._get_role_description_for_history(FakeMember())
        self.assertEqual(result, "Lead - Communications")

    # --- handle_member_role_change ---
    def test_handle_member_role_change_noop_on_none(self):
        """handle_member_role_change does nothing when old_member is None."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"RoleChg-{self.uid}")
        # Should not raise
        svc.handle_member_role_change(team, None, None)

    # --- validate_unique_roles: no unique roles ---
    def test_validate_unique_roles_no_roles(self):
        """validate_unique_roles returns True when no unique roles to validate."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"UniqueR-{self.uid}")
        result = svc.validate_unique_roles(team)
        self.assertTrue(result)


class TestTeamValidationService(EnhancedTestCase):
    """Tests for TeamValidationService — team structure validation."""

    def _get_service(self):
        from verenigingen.services.team_service import get_team_validation_service

        return get_team_validation_service()

    # --- validate_team_members ---
    def test_validate_team_members_empty(self):
        """validate_team_members returns True for empty team."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"EmptyVal-{self.uid}")
        result = svc.validate_team_members(team)
        self.assertTrue(result)

    # --- validate_dates ---
    def test_validate_dates_valid(self):
        """validate_dates passes when end_date >= start_date."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"DateVal-{self.uid}")
        team.start_date = "2025-01-01"
        team.end_date = "2025-12-31"
        result = svc.validate_dates(team)
        self.assertTrue(result)

    def test_validate_dates_rejects_end_before_start(self):
        """validate_dates raises when end_date < start_date."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"BadDate-{self.uid}")
        team.start_date = "2025-12-31"
        team.end_date = "2025-01-01"
        with self.assertRaises(frappe.ValidationError):
            svc.validate_dates(team)

    def test_validate_dates_no_end_date(self):
        """validate_dates passes when no end_date set."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"NoEnd-{self.uid}")
        team.start_date = "2025-01-01"
        team.end_date = None
        result = svc.validate_dates(team)
        self.assertTrue(result)

    # --- validate_role_profile_configuration ---
    def test_validate_role_profile_nonexistent_profile(self):
        """validate_role_profile_configuration raises for nonexistent profile."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"BadProf-{self.uid}")
        team.default_role_profile = "NONEXISTENT_PROFILE_XYZ"
        team.enable_role_specific_profiles = 0
        with self.assertRaises(frappe.ValidationError):
            svc.validate_role_profile_configuration(team)

    def test_validate_role_profile_no_profile_passes(self):
        """validate_role_profile_configuration passes with no profile set."""
        svc = self._get_service()
        team = self.create_test_team(team_name=f"NoProf-{self.uid}")
        team.default_role_profile = None
        team.enable_role_specific_profiles = 0
        result = svc.validate_role_profile_configuration(team)
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# 3. DonationDashboardService
# ---------------------------------------------------------------------------
class TestDonationDashboardService(EnhancedTestCase):
    """Tests for DonationDashboardService — dashboard data aggregation."""

    def _get_service(self):
        from verenigingen.services.donation.dashboard_service import (
            get_donation_dashboard_service,
        )

        return get_donation_dashboard_service()

    # --- _get_reportable_donations ---
    def test_reportable_donations_query_runs(self):
        """_get_reportable_donations executes and returns count/amount keys.

        Regression (audit T1.2, 2026-05-17): the query referenced a
        belastingdienst_reportable column absent from the Donation DocType,
        so the whole donation dashboard failed to load with 'Unknown column'.
        """
        svc = self._get_service()
        from frappe.utils import getdate

        year = getdate(today()).year
        result = svc._get_reportable_donations(f"{year}-01-01", f"{year}-12-31", 500.0)
        self.assertIn("reportable_donations_count", result)
        self.assertIn("reportable_donations_amount", result)

    # --- _get_year_to_date_stats ---
    def test_year_to_date_stats_returns_amounts(self):
        """_get_year_to_date_stats returns total_amount and count keys."""
        svc = self._get_service()
        from frappe.utils import getdate
        current_year = getdate(today()).year
        result = svc._get_year_to_date_stats(f"{current_year}-01-01", f"{current_year}-12-31")
        self.assertIn("total_donations_amount", result)
        self.assertIn("total_donations_count", result)
        self.assertIsInstance(result["total_donations_amount"], (int, float))

    def test_year_to_date_stats_with_donation(self):
        """_get_year_to_date_stats counts submitted donations."""
        svc = self._get_service()
        self.create_test_donation(amount=75.0)
        from frappe.utils import getdate
        current_year = getdate(today()).year
        result = svc._get_year_to_date_stats(f"{current_year}-01-01", f"{current_year}-12-31")
        self.assertGreaterEqual(result["total_donations_count"], 1)

    # --- _get_periodic_agreement_stats ---
    def test_periodic_agreement_stats(self):
        """_get_periodic_agreement_stats returns expected keys."""
        svc = self._get_service()
        result = svc._get_periodic_agreement_stats()
        self.assertIn("active_anbi_agreements", result)
        self.assertIn("active_pledge_agreements", result)
        self.assertIn("total_annual_commitment", result)
        self.assertIn("expiring_soon_count", result)

    # --- _get_donor_stats ---
    def test_donor_stats(self):
        """_get_donor_stats returns donor count keys."""
        svc = self._get_service()
        result = svc._get_donor_stats()
        self.assertIn("unique_donors", result)
        self.assertIn("individual_donors", result)
        self.assertIn("organization_donors", result)
        self.assertIn("consent_percentage", result)

    # --- _get_recent_donations ---
    def test_recent_donations_is_list(self):
        """_get_recent_donations returns a list."""
        svc = self._get_service()
        result = svc._get_recent_donations()
        self.assertIsInstance(result, list)

    # --- _get_expiring_agreements ---
    def test_expiring_agreements_is_list(self):
        """_get_expiring_agreements returns a list."""
        svc = self._get_service()
        result = svc._get_expiring_agreements()
        self.assertIsInstance(result, list)

    # --- _get_monthly_trend_chart ---
    def test_monthly_trend_chart_structure(self):
        """_get_monthly_trend_chart returns 12 months of labels and datasets."""
        svc = self._get_service()
        from frappe.utils import getdate
        current_year = getdate(today()).year
        chart = svc._get_monthly_trend_chart(current_year)
        self.assertIn("labels", chart)
        self.assertIn("datasets", chart)
        self.assertEqual(len(chart["labels"]), 12)
        self.assertEqual(chart["labels"][0], "Jan")
        self.assertEqual(chart["labels"][11], "Dec")

    # --- _get_agreement_distribution ---
    def test_agreement_distribution_structure(self):
        """_get_agreement_distribution returns labels and datasets."""
        svc = self._get_service()
        dist = svc._get_agreement_distribution()
        self.assertIn("labels", dist)
        self.assertIn("datasets", dist)


# ---------------------------------------------------------------------------
# 4. AccountCreationService
# ---------------------------------------------------------------------------
class TestAccountCreationService(EnhancedTestCase):
    """Tests for AccountCreationService — member account validation and creation."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="AcctSvc", last_name=f"S{self.uid}")

    def _get_service(self):
        from verenigingen.services.account.account_creation_service import (
            get_account_creation_service,
        )

        return get_account_creation_service()

    # --- validate_member_for_account ---
    def test_validate_no_email(self):
        """validate_member_for_account fails when member has no email."""
        svc = self._get_service()
        self.member.email = None
        is_valid, error = svc.validate_member_for_account(self.member)
        self.assertFalse(is_valid)
        self.assertIn("no email", error)

    def test_validate_invalid_email(self):
        """validate_member_for_account fails for invalid email format."""
        svc = self._get_service()
        self.member.email = "bademail"
        is_valid, error = svc.validate_member_for_account(self.member)
        self.assertFalse(is_valid)
        self.assertIn("invalid email", error)

    def test_validate_invalid_status(self):
        """validate_member_for_account fails for Quit/Banned/Deceased/Rejected status."""
        svc = self._get_service()
        self.member.email = "valid@example.com"
        for status in ["Quit", "Banned", "Deceased", "Rejected"]:
            self.member.status = status
            is_valid, error = svc.validate_member_for_account(self.member)
            self.assertFalse(is_valid, f"Should fail for status {status}")

    def test_validate_valid_member(self):
        """validate_member_for_account passes for member with email and valid status."""
        svc = self._get_service()
        self.member.email = "valid@example.com"
        self.member.status = "Active"
        self.member.user = None
        is_valid, error = svc.validate_member_for_account(self.member)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_already_complete_account(self):
        """validate_member_for_account rejects member with complete account setup."""
        svc = self._get_service()
        self.member.email = "valid@example.com"
        self.member.status = "Active"
        # Link to Administrator user (which exists)
        self.member.user = "Administrator"
        self.member.first_name = "Administrator"
        self.member.last_name = ""
        is_valid, error = svc.validate_member_for_account(self.member)
        self.assertFalse(is_valid)
        self.assertIn("already has complete account", error)

    # --- detect_existing_user ---
    def test_detect_existing_user_found(self):
        """detect_existing_user finds Administrator by email."""
        svc = self._get_service()
        admin_email = frappe.db.get_value("User", "Administrator", "email")
        if admin_email:
            result = svc.detect_existing_user(admin_email)
            self.assertIsNotNone(result)
            self.assertEqual(result["user_name"], "Administrator")

    def test_detect_existing_user_not_found(self):
        """detect_existing_user returns None for nonexistent email."""
        svc = self._get_service()
        result = svc.detect_existing_user("nonexistent_xyz_99@invalid.tld")
        self.assertIsNone(result)

    # --- link_existing_user ---
    def test_link_user_nonexistent(self):
        """link_existing_user fails for nonexistent user."""
        svc = self._get_service()
        success, error = svc.link_existing_user(self.member, "nonexistent_user@invalid.tld")
        self.assertFalse(success)
        self.assertIn("does not exist", error)

    def test_link_user_name_mismatch(self):
        """link_existing_user fails when names do not match."""
        svc = self._get_service()
        # Use Administrator which has different name
        success, error = svc.link_existing_user(self.member, "Administrator", validate_names=True)
        self.assertFalse(success)
        self.assertIn("Names do not match", error)

    def test_link_user_skip_name_validation(self):
        """link_existing_user succeeds when name validation is skipped."""
        svc = self._get_service()
        # Administrator exists but name won't match - skip validation
        admin_email = frappe.db.get_value("User", "Administrator", "email")
        if admin_email:
            # Only test if Administrator is not already linked to another member
            existing = frappe.db.get_value("Member", {"user": "Administrator"}, "name")
            if not existing:
                success, error = svc.link_existing_user(
                    self.member, "Administrator", validate_names=False
                )
                self.assertTrue(success)
                self.assertIsNone(error)
                # Verify the link was set
                self.member.reload()
                self.assertEqual(self.member.user, "Administrator")

    # --- queue_bulk_requests ---
    def test_queue_bulk_requests_empty_list(self):
        """queue_bulk_requests handles empty member list."""
        svc = self._get_service()
        result = svc.queue_bulk_requests(
            member_names=[],
            roles=["Verenigingen Member"],
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["requests_created"], 0)
        self.assertEqual(result["users_linked"], 0)

    def test_queue_bulk_requests_nonexistent_member(self):
        """queue_bulk_requests records error for nonexistent member."""
        svc = self._get_service()
        result = svc.queue_bulk_requests(
            member_names=["NONEXISTENT-MEMBER-XYZ"],
            roles=["Verenigingen Member"],
        )
        self.assertTrue(result["success"])  # Process succeeds overall
        self.assertEqual(result["validation_errors_count"], 1)
        self.assertIn("does not exist", result["validation_errors"][0])

    def test_queue_bulk_requests_skips_invalid_status(self):
        """queue_bulk_requests skips members with invalid status when filtering."""
        svc = self._get_service()
        # Set member to Quit status
        frappe.db.set_value("Member", self.member.name, "status", "Quit")
        result = svc.queue_bulk_requests(
            member_names=[self.member.name],
            roles=["Verenigingen Member"],
            filter_by_status=True,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["requests_created"], 0)
        self.assertEqual(result["users_linked"], 0)
