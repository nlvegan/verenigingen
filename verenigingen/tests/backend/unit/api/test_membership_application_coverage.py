# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Branch-coverage tests for verenigingen.api.membership_application.

Targets uncovered branches not exercised by the existing characterization
suites (test_validation_endpoint_wrappers, test_membership_application):

- _handle_existing_member reapplication scenarios (Rejected/Active/Quit/unknown)
  via the public submit_application entry point.
- suggest_chapters_for_postal_code + the pure _match_chapter_* matchers.
- The deprecated reject_membership_application / approve_membership_application
  redirect endpoints in this module.
- validate_email / validate_postal_code response shaping.
- get_application_form_data success path.

All tests use real DB fixtures (no business-logic mocking). The @public_api /
@high_security_api decorators serialise OperationResult into a plain dict, so
the assertions match the dict the caller actually receives.
"""

import json

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application import (
    _handle_existing_member,
    _match_chapter_postal_codes,
    _match_chapter_region_heuristic,
    approve_membership_application as deprecated_approve,
    get_application_form_data,
    reject_membership_application as deprecated_reject,
    submit_application,
    suggest_chapters_for_postal_code,
    validate_email,
    validate_postal_code,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _ensure_test_membership_type():
    """Create a simple membership type usable by submit_application."""
    if not frappe.db.exists("Item Group", "Membership"):
        frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": "Membership",
                "parent_item_group": "All Item Groups",
                "is_group": 0,
            }
        ).insert()
    name = "Coverage Test Membership"
    if not frappe.db.exists("Membership Type", name):
        frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": name,
                "minimum_amount": 15,
                "role_profile": "Verenigingen Member",
            }
        ).insert()
    return name


# ---------------------------------------------------------------------------
# Pure postal-code matchers (no DB, no side effects)
# ---------------------------------------------------------------------------


class TestMatchChapterPostalCodes(EnhancedTestCase):
    """_match_chapter_postal_codes: parse comma-separated ranges / prefixes."""

    def test_range_match_scores_100(self):
        score, match_type = _match_chapter_postal_codes("1000-2000", 1500, "1500AB")
        self.assertEqual(score, 100)
        self.assertEqual(match_type, "postal_range")

    def test_prefix_match_scores_90(self):
        score, match_type = _match_chapter_postal_codes("1500", 1500, "1500AB")
        self.assertEqual(score, 90)
        self.assertEqual(match_type, "postal_prefix")

    def test_exact_full_postal_match_scores_100(self):
        # Full 6-char token equals the full postal code.
        score, match_type = _match_chapter_postal_codes("1500AB", 1500, "1500AB")
        self.assertEqual(score, 100)
        self.assertEqual(match_type, "postal_exact")

    def test_no_match_returns_zero(self):
        score, match_type = _match_chapter_postal_codes("3000-4000", 1500, "1500AB")
        self.assertEqual(score, 0)
        self.assertIsNone(match_type)

    def test_malformed_range_is_skipped(self):
        # "abc-def" raises ValueError on int() -> continue; falls through to 0.
        score, match_type = _match_chapter_postal_codes("abc-def", 1500, "1500AB")
        self.assertEqual(score, 0)
        self.assertIsNone(match_type)

    def test_spaces_are_stripped(self):
        score, match_type = _match_chapter_postal_codes(" 1000 - 2000 ", 1500, "1500AB")
        self.assertEqual(score, 100)


class TestMatchChapterRegionHeuristic(EnhancedTestCase):
    """_match_chapter_region_heuristic: regional fallback guessing."""

    def test_amsterdam_under_2000(self):
        score, match_type = _match_chapter_region_heuristic("Amsterdam Chapter", "Noord-Holland", 1015)
        self.assertEqual(score, 30)
        self.assertEqual(match_type, "region_guess")

    def test_den_haag_under_3000(self):
        score, match_type = _match_chapter_region_heuristic("Den Haag Chapter", "Zuid-Holland", 2500)
        self.assertEqual(score, 30)

    def test_rotterdam_under_4000(self):
        score, match_type = _match_chapter_region_heuristic("Rotterdam Chapter", "Zuid-Holland", 3500)
        self.assertEqual(score, 30)

    def test_no_region_match_returns_zero(self):
        score, match_type = _match_chapter_region_heuristic("Groningen Chapter", "Groningen", 9700)
        self.assertEqual(score, 0)
        self.assertIsNone(match_type)

    def test_none_names_handled_gracefully(self):
        score, match_type = _match_chapter_region_heuristic(None, None, 1500)
        self.assertEqual(score, 0)


# ---------------------------------------------------------------------------
# suggest_chapters_for_postal_code (DB-backed)
# ---------------------------------------------------------------------------


class TestSuggestChaptersForPostalCode(EnhancedTestCase):
    """suggest_chapters_for_postal_code: validation + matching + sorting."""

    def test_empty_postal_code_fails(self):
        result = suggest_chapters_for_postal_code("")
        self.assertFalse(result["success"])
        self.assertIn("postal_code_required", json.dumps(result))

    def test_invalid_format_fails(self):
        result = suggest_chapters_for_postal_code("ABCDEF")
        self.assertFalse(result["success"])
        self.assertIn("invalid_postal_code_format", json.dumps(result))

    def test_valid_postal_returns_success_shape(self):
        result = suggest_chapters_for_postal_code("1015cj")  # lower-cased, normalised internally
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["postal_code"], "1015CJ")
        self.assertIn("suggestions", data)
        self.assertIsInstance(data["suggestions"], list)
        self.assertEqual(data["total_suggestions"], len(data["suggestions"]))

    def test_published_chapter_with_matching_range_is_suggested(self):
        """A published chapter whose postal_codes range covers the code is returned."""
        region = frappe.get_all("Region", limit=1, pluck="name")
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Cov Postal Chapter {frappe.generate_hash(length=6)}",
                "region": region[0] if region else None,
                "postal_codes": "1000-1999",
                "published": 1,
                "introduction": "Coverage test chapter",
            }
        )
        chapter.insert()
        self.track_doc("Chapter", chapter.name)

        result = suggest_chapters_for_postal_code("1500AB")
        self.assertTrue(result["success"])
        names = [s["name"] for s in result["data"]["suggestions"]]
        self.assertIn(chapter.name, names)
        match = next(s for s in result["data"]["suggestions"] if s["name"] == chapter.name)
        self.assertEqual(match["match_type"], "postal_range")
        self.assertEqual(match["relevance_score"], 100)


# ---------------------------------------------------------------------------
# validate_email / validate_postal_code response shaping
# ---------------------------------------------------------------------------


class TestValidateEmailEndpoint(EnhancedTestCase):
    def test_empty_email_required(self):
        result = validate_email("")
        self.assertFalse(result["success"])
        self.assertIn("email_required", json.dumps(result))

    def test_malformed_email_fails(self):
        result = validate_email("not-an-email")
        self.assertFalse(result["success"])

    def test_well_formed_unused_email_valid(self):
        unique = f"cov-{frappe.generate_hash(length=8)}@example.com"
        result = validate_email(unique)
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["valid"])


class TestValidatePostalCodeEndpoint(EnhancedTestCase):
    def test_valid_postal_includes_suggested_chapters_key(self):
        result = validate_postal_code("1015CJ", "Netherlands")
        self.assertTrue(result["success"])
        self.assertIn("suggested_chapters", result["data"])
        self.assertIsInstance(result["data"]["suggested_chapters"], list)

    def test_invalid_postal_fails(self):
        result = validate_postal_code("XX", "Netherlands")
        self.assertFalse(result["success"])


class TestGetApplicationFormData(EnhancedTestCase):
    def test_returns_success_with_form_fields(self):
        result = get_application_form_data()
        self.assertTrue(result["success"])
        data = result["data"]
        # get_form_data() returns these top-level keys on the success path.
        self.assertIn("membership_types", data)
        self.assertIn("chapters", data)
        self.assertIn("countries", data)


# ---------------------------------------------------------------------------
# _handle_existing_member reapplication scenarios (via submit_application)
# ---------------------------------------------------------------------------


class TestHandleExistingMember(EnhancedTestCase):
    """Unit tests for _handle_existing_member: reapplication scenario routing.

    NOTE: _handle_existing_member is only reached by submit_application AFTER the
    eligibility gate, which unconditionally fails for any existing email (see
    TestSubmitApplicationExistingEmailGate below). These tests call the helper
    directly to cover its branch logic, which is the documented intent of the
    reapplication routing.
    """

    def _make_member(self, *, status, application_status):
        member = self.create_test_member(
            first_name="HEM",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"hem-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("status", status, update_modified=False)
        member.db_set("application_status", application_status, update_modified=False)
        member.reload()
        return member

    def _existing(self, member):
        return frappe._dict(
            name=member.name,
            status=member.status,
            application_status=member.application_status,
        )

    def test_rejected_application_allows_reapplication(self):
        member = self._make_member(status="Rejected", application_status="Rejected")
        action, error = _handle_existing_member(self._existing(member), {})
        self.assertEqual(action, "update")
        self.assertIsNone(error)

    def test_pending_application_allows_update(self):
        member = self._make_member(status="Pending", application_status="Pending")
        action, error = _handle_existing_member(self._existing(member), {})
        self.assertEqual(action, "update")
        self.assertIsNone(error)

    def test_active_member_is_blocked(self):
        member = self._make_member(status="Active", application_status="Approved")
        action, error = _handle_existing_member(self._existing(member), {})
        self.assertIsNone(action)
        self.assertFalse(error.success)
        self.assertIn("already_active_member", json.dumps(error.to_dict(nested=True)))

    def test_unknown_status_blocks_with_contact_message(self):
        member = self._make_member(status="Suspended", application_status="Approved")
        action, error = _handle_existing_member(self._existing(member), {})
        self.assertIsNone(action)
        self.assertFalse(error.success)
        self.assertIn("membership_record_exists", json.dumps(error.to_dict(nested=True)))

    def test_quit_without_termination_request_requires_contact(self):
        """Quit status but no Executed termination request -> data-integrity block."""
        member = self._make_member(status="Quit", application_status="Approved")
        # No Membership Termination Request exists for this member.
        self.expectErrorLog("Termination Data Integrity")
        action, error = _handle_existing_member(self._existing(member), {})
        self.assertIsNone(action)
        self.assertFalse(error.success)
        self.assertIn("termination_status_unclear", json.dumps(error.to_dict(nested=True)))

    def test_quit_voluntary_termination_allows_reapplication(self):
        """Quit status with an Executed *Voluntary* termination -> reapplication allowed."""
        member = self._make_member(status="Quit", application_status="Approved")
        # Seed an Executed Voluntary termination request.
        membership_type = _ensure_test_membership_type()  # noqa: F841 (ensures masters)
        tr = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Voluntary",
                "status": "Executed",
                "termination_reason": "Member requested to leave",
                "request_date": today(),
                "execution_date": today(),
            }
        )
        tr.flags.ignore_validate = True
        tr.insert(ignore_mandatory=True)
        self.track_doc("Membership Termination Request", tr.name)

        action, error = _handle_existing_member(self._existing(member), {})
        self.assertEqual(action, "update")
        self.assertIsNone(error)

    def test_quit_involuntary_termination_is_blocked(self):
        """Quit status with an Executed *Disciplinary* termination -> blocked."""
        member = self._make_member(status="Quit", application_status="Approved")
        tr = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": "Policy Violation",
                "status": "Executed",
                "termination_reason": "Serious policy violation",
                "request_date": today(),
                "execution_date": today(),
            }
        )
        tr.flags.ignore_validate = True
        tr.insert(ignore_mandatory=True)
        self.track_doc("Membership Termination Request", tr.name)

        action, error = _handle_existing_member(self._existing(member), {})
        self.assertIsNone(action)
        self.assertFalse(error.success)
        self.assertIn("involuntary_termination", json.dumps(error.to_dict(nested=True)))


class TestSubmitApplicationExistingEmailGate(EnhancedTestCase):
    """Characterizes submit_application's eligibility gate for existing emails.

    FLAG: The eligibility check (check_application_eligibility) runs BEFORE
    _handle_existing_member and fails for ANY existing email regardless of the
    member's status. This means the Rejected/Pending "reapplication allowed"
    branches of _handle_existing_member are effectively unreachable through
    submit_application -- an existing-email applicant is always blocked at the
    eligibility gate with the generic "already exists" message. Recorded here as
    a characterization test so a future fix to the intake flow is detectable.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()
        cls.membership_type = _ensure_test_membership_type()
        frappe.db.commit()

    def test_existing_email_blocked_at_eligibility_gate(self):
        email = f"gate-{frappe.generate_hash(length=8)}@example.com"
        member = self.create_test_member(
            first_name="Gate",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=email,
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("application_status", "Rejected", update_modified=False)
        member.db_set("status", "Rejected", update_modified=False)
        frappe.db.commit()

        data = {
            "first_name": "Reapply",
            "last_name": f"Case{frappe.generate_hash(length=6)}",
            "email": email,
            "birth_date": "1990-01-01",
            "address_line1": "123 Test Street",
            "city": "Amsterdam",
            "postal_code": "1234AB",
            "country": "Netherlands",
            "selected_membership_type": self.membership_type,
        }
        self.expectErrorLog("Application Eligibility Failed")
        result = submit_application(**data)
        self.assertFalse(result["success"])
        self.assertIn("already exists", json.dumps(result).lower())


# ---------------------------------------------------------------------------
# Deprecated redirect endpoints in this module
# ---------------------------------------------------------------------------


class TestDeprecatedRejectEndpoint(EnhancedTestCase):
    """membership_application.reject_membership_application (deprecated path)."""

    def _pending_member(self):
        member = self.create_test_member(
            first_name="DepReject",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"depreject-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("status", "Pending", update_modified=False)
        member.db_set("application_status", "Pending", update_modified=False)
        member.reload()
        return member

    def test_reject_pending_member_sets_rejected(self):
        member = self._pending_member()
        # send_rejection_notification renders an email template; in the test bench
        # (no SMTP / template config) it may log. Allow those expected titles.
        self.expectErrorLog(
            "Email", "Notification", "Template", "rejection", "membership_application_rejected"
        )
        result = deprecated_reject(member.name, "Incomplete application")

        self.assertTrue(result["success"], msg=json.dumps(result))
        member.reload()
        self.assertEqual(member.application_status, "Rejected")
        self.assertEqual(member.status, "Rejected")
        self.assertEqual(member.review_notes, "Incomplete application")

    def test_reject_already_approved_member_fails(self):
        member = self._pending_member()
        member.db_set("application_status", "Approved", update_modified=False)

        result = deprecated_reject(member.name, "too late")
        self.assertFalse(result["success"])
        self.assertIn("invalid_application_status", json.dumps(result))


class TestDeprecatedApproveRedirect(EnhancedTestCase):
    """membership_application.approve_membership_application redirects to canonical."""

    def test_approve_nonexistent_member_returns_failure_dict(self):
        # The canonical implementation throws for a non-existent member; the
        # @high_security_api wrapper serialises that into a failure dict.
        self.expectErrorLog("Invalid member", "member access", "approval", "Member", "security")
        result = deprecated_approve("NONEXISTENT-MEMBER-COV-12345")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
