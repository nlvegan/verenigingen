# -*- coding: utf-8 -*-
# Copyright (c) 2026, Your Organization and Contributors
# See license.txt

"""
Coverage-focused integration tests for verenigingen/api/member_management.py

Two areas:
  (A) Chapter-assignment APIs (PRIMARY): assign_member_to_chapter,
      can_assign_member_to_chapter, get_members_without_chapter,
      bulk_assign_members_to_chapters, get_members_with_chapter_info,
      add_member_to_chapter_roster, _sanitize_member_filters,
      _enrich_members_with_chapters.
  (B) MT940 PURE helpers only: get_mt940_import_url,
      extract_iban_from_mt940_content, _parse_mt940_amount,
      find_bank_account_by_iban_improved. The full import pipeline
      (import_mt940_improved / _process_mt940_statements /
      _resolve_mt940_bank_account) is owned by the bank-reconciliation
      session and is NOT exercised here against live banking.

These are REAL integration tests: real Member/Chapter/Volunteer/Bank Account
docs are created, the whitelisted APIs are called, and DB state + the
OperationResult return shape are asserted. Permission gates are exercised by
switching the session user via frappe.set_user (allow + deny paths).
"""

import frappe

from verenigingen.api import member_management
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.operation_result import OperationResult


def _ok(result):
    """True if ``result`` (an OperationResult or its serialized dict) succeeded.

    Whitelisted endpoints decorated by the security framework return the
    *serialized* dict form ({'success': ..., 'data': ..., 'error': ...}); the
    undecorated callees return the raw OperationResult object.
    """
    if isinstance(result, OperationResult):
        return result.success
    return result.get("success") is True


def _data(result):
    """Return the data payload from an OperationResult or its serialized dict."""
    if isinstance(result, OperationResult):
        return result.data
    return result.get("data")


class TestMemberManagementChapterAssignment(PortalSelfServiceTestMixin, EnhancedTestCase):
    """Area (A): chapter-assignment APIs."""

    def setUp(self):
        super().setUp()
        # A dedicated chapter for assignment targets.
        self.chapter = self.factory.create_chapter(
            chapter_name=f"MMChapter-{self.uid}",
            region="Test Region MM",
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_member(self, **kwargs):
        return self.factory.create_member(
            first_name="MMTest",
            last_name="Member",
            email=f"mm-{self.uid}-{frappe.generate_hash(length=6)}@example.com",
            **kwargs,
        )

    def _chapter_member_parent(self, member_name):
        return frappe.db.get_value(
            "Chapter Member", {"member": member_name, "enabled": 1}, "parent"
        )

    def _make_board_admin_member(self, chapter):
        """Create a member who is an active board member (Membership level) of
        ``chapter``, link a User, and return (member, user)."""
        member = self._make_member()
        volunteer = self.factory.create_volunteer(member_name=member.name)
        role = self.factory.ensure_chapter_role(
            f"MM Board Role {self.uid}", attributes={"permissions_level": "Membership"}
        )
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.board_manager.add_board_member(  # ast-skip: @property not field
            volunteer=volunteer.name, role=role.name, notify=False
        )
        user = self._link_member_to_user(member, roles=("Verenigingen Member",))
        return member, user

    # ------------------------------------------------------------------
    # assign_member_to_chapter  (admin path)
    # ------------------------------------------------------------------
    def test_assign_member_to_chapter_success(self):
        member = self._make_member()

        result = member_management.assign_member_to_chapter(member.name, self.chapter.name)

        self.assertTrue(_ok(result))
        self.assertEqual(_data(result)["new_chapter"], self.chapter.name)
        self.assertEqual(self._chapter_member_parent(member.name), self.chapter.name)

    def test_assign_member_to_chapter_idempotent(self):
        """Re-assigning a member already in the target chapter is a success no-op."""
        member = self._make_member()
        member_management.assign_member_to_chapter(member.name, self.chapter.name)

        result = member_management.assign_member_to_chapter(member.name, self.chapter.name)

        self.assertTrue(_ok(result))
        self.assertEqual(_data(result)["new_chapter"], self.chapter.name)

    def test_assign_member_to_chapter_nonexistent_member_fails(self):
        # @handle_api_error converts the raised ValidationError into a failure
        # result rather than propagating the exception.
        result = member_management.assign_member_to_chapter(
            f"NONEXISTENT-{self.uid}", self.chapter.name
        )
        self.assertFalse(_ok(result))

    # ------------------------------------------------------------------
    # can_assign_member_to_chapter  (permission gate)
    # ------------------------------------------------------------------
    def test_can_assign_admin_is_true(self):
        # EnhancedTestCase.setUp runs as Administrator (an ADMIN_ROLES holder).
        member = self._make_member()
        self.assertTrue(
            member_management.can_assign_member_to_chapter(member.name, self.chapter.name)
        )

    def test_can_assign_plain_member_is_false(self):
        target = self._make_member()
        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        with self._as_user(user.name):
            self.assertFalse(
                member_management.can_assign_member_to_chapter(target.name, self.chapter.name)
            )

    def test_can_assign_no_member_record_is_false(self):
        target = self._make_member()
        # A user that exists but has no linked Member record.
        user = self.factory.create_user_with_roles(
            email=f"nomember-{self.uid}@example.com", roles=["Verenigingen Member"]
        )
        with self._as_user(user.name):
            self.assertFalse(
                member_management.can_assign_member_to_chapter(target.name, self.chapter.name)
            )

    def test_can_assign_board_member_with_membership_level_is_true(self):
        target = self._make_member()
        _board_member, board_user = self._make_board_admin_member(self.chapter)
        with self._as_user(board_user.name):
            self.assertTrue(
                member_management.can_assign_member_to_chapter(target.name, self.chapter.name)
            )

    def test_assign_denied_for_plain_member(self):
        """A plain member calling the whitelisted assign API is denied.

        The @critical_api tier gate rejects the plain member before the inner
        can_assign_member_to_chapter check is reached, raising a permission error
        ("Access denied. Required: critical ...").
        """
        target = self._make_member()
        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        with self._as_user(user.name):
            with self.assertRaises(Exception) as ctx:
                member_management.assign_member_to_chapter(target.name, self.chapter.name)
        self.assertIn("denied", str(ctx.exception).lower())

    def test_assign_denied_by_inner_check_for_authorized_non_chapter_role(self):
        """Deny via the BODY-level check, not the decorator.

        Every other deny test stops at the @critical_api tier gate, leaving the
        inner ``if not can_assign_member_to_chapter(...)`` branch
        (member_management.py:43-44) untested. To reach it we need an actor that
        clears the CRITICAL decorator but that ``can_assign_member_to_chapter``
        rejects.

        After the audit #2 Rule-5 cap, CRITICAL is grantable only through an
        assigned role PROFILE (decorator Rule 4 reads ``get_user_role_profiles``),
        yet every CRITICAL-granting profile also syncs an ADMIN_ROLE (e.g.
        'Verenigingen Staff') that would satisfy ``can_assign``'s admin fast-path.
        So we assign the 'Verenigingen National Board Member' profile (→ CRITICAL
        at the decorator) and then strip the synced ADMIN_ROLES from the user's
        Has Role rows, WITHOUT touching the profile assignment. The decorator
        still sees the profile; ``can_assign`` (which reads ``frappe.get_roles``)
        no longer sees an admin role and, with no board seat on the target
        chapter, returns False. @handle_api_error then converts the raised
        PermissionError into a failure OperationResult rather than propagating it.
        """
        from verenigingen.utils.constants import Roles

        target = self._make_member()
        actor = self._make_member()
        user = self._link_member_to_user(
            actor,
            roles=("Verenigingen National Board Member",),
            role_profile="Verenigingen National Board Member",
        )
        # Strip the profile-synced admin roles via direct SQL so User.save does not
        # re-sync them, leaving the profile assignment (hence CRITICAL) intact.
        frappe.db.delete(
            "Has Role", {"parent": user.name, "role": ["in", list(Roles.ADMIN_ROLES)]}
        )
        frappe.db.commit()
        frappe.clear_cache(user=user.name)
        from verenigingen.utils.security.api_security_framework import get_security_framework

        get_security_framework().auth_engine.invalidate_user_cache(user.name)
        with self._as_user(user.name):
            result = member_management.assign_member_to_chapter(target.name, self.chapter.name)
        # Passed the decorator (no "access denied" raise) but the inner check
        # blocked it -> failure result mentioning the permission denial...
        self.assertFalse(_ok(result))
        if isinstance(result, OperationResult):
            message = result.message or ""
        else:
            # The serialized OperationResult nests the text under "error".
            err = result.get("error")
            message = (err.get("message") if isinstance(err, dict) else str(err or "")) or result.get(
                "message", ""
            )
        self.assertIn("permission", message.lower())
        # ...and the target was NOT assigned to the chapter.
        self.assertIsNone(self._chapter_member_parent(target.name))

    # ------------------------------------------------------------------
    # get_members_without_chapter
    # ------------------------------------------------------------------
    def test_get_members_without_chapter_returns_unassigned(self):
        unassigned = self._make_member()
        assigned = self._make_member()
        member_management.assign_member_to_chapter(assigned.name, self.chapter.name)

        result = member_management.get_members_without_chapter(limit=1000)

        self.assertTrue(_ok(result))
        names = [m["name"] for m in _data(result)["members"]]
        self.assertIn(unassigned.name, names)
        self.assertNotIn(assigned.name, names)
        self.assertEqual(_data(result)["count"], len(_data(result)["members"]))

    def test_get_members_without_chapter_limit_capped(self):
        """limit > 1000 is capped at 1000 (no crash, returns ok)."""
        result = member_management.get_members_without_chapter(limit=99999)
        self.assertTrue(_ok(result))

    def test_get_members_without_chapter_denied_for_plain_member(self):
        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        with self._as_user(user.name):
            result = member_management.get_members_without_chapter()
        self.assertFalse(_ok(result))

    # ------------------------------------------------------------------
    # bulk_assign_members_to_chapters
    # ------------------------------------------------------------------
    def test_bulk_assign_success_and_error_counts(self):
        m1 = self._make_member()
        m2 = self._make_member()
        assignments = [
            {"member_name": m1.name, "chapter_name": self.chapter.name},
            {"member_name": m2.name, "chapter_name": self.chapter.name},
            {"member_name": f"NOPE-{self.uid}", "chapter_name": self.chapter.name},
        ]

        result = member_management.bulk_assign_members_to_chapters(assignments)

        self.assertTrue(_ok(result))
        self.assertEqual(_data(result)["success_count"], 2)
        self.assertEqual(_data(result)["error_count"], 1)
        self.assertEqual(len(_data(result)["results"]), 3)
        self.assertEqual(self._chapter_member_parent(m1.name), self.chapter.name)

    def test_bulk_assign_empty_fails(self):
        result = member_management.bulk_assign_members_to_chapters([])
        self.assertFalse(_ok(result))

    # ------------------------------------------------------------------
    # get_members_with_chapter_info  +  _enrich_members_with_chapters
    # ------------------------------------------------------------------
    def test_get_members_with_chapter_info_enriches(self):
        member = self._make_member(member_since="1990-06-15")
        member_management.assign_member_to_chapter(member.name, self.chapter.name)

        # Filter on the member's synthetic member_since (no real member shares it)
        # so the seeded member is deterministically present despite the endpoint's
        # 500-row, full_name-ordered cap on a site with hundreds of members.
        result = member_management.get_members_with_chapter_info(
            filters={"member_since": "1990-06-15"}, limit=500
        )

        self.assertTrue(_ok(result))
        self.assertTrue(_data(result)["query_optimization"]["n_plus_1_prevented"])
        found = next((m for m in _data(result)["members"] if m["name"] == member.name), None)
        self.assertIsNotNone(found)
        self.assertEqual(len(found["chapters"]), 1)
        self.assertEqual(found["chapters"][0]["chapter_name"], self.chapter.name)
        self.assertIsNotNone(found["primary_chapter"])

    def test_get_members_with_chapter_info_member_without_chapter(self):
        member = self._make_member(member_since="1990-06-16")
        result = member_management.get_members_with_chapter_info(
            filters={"member_since": "1990-06-16"}, limit=500
        )
        self.assertTrue(_ok(result))
        found = next((m for m in _data(result)["members"] if m["name"] == member.name), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["chapters"], [])
        self.assertIsNone(found["primary_chapter"])

    def test_get_members_with_chapter_info_filters_sanitized(self):
        """A status filter is honored; unknown filter keys are stripped silently."""
        member = self._make_member(status="Active", member_since="1990-06-17")
        # member_since narrows to the seeded member (deterministic); evil_field
        # must be stripped (not injected) -> a clean result, not a SQL error.
        result = member_management.get_members_with_chapter_info(
            filters={"status": "Active", "member_since": "1990-06-17", "evil_field": "x' OR 1=1"},
            limit=500,
        )
        self.assertTrue(_ok(result))
        names = [m["name"] for m in _data(result)["members"]]
        self.assertIn(member.name, names)

    def test_get_members_with_chapter_info_limit_capped(self):
        result = member_management.get_members_with_chapter_info(limit=99999)
        self.assertTrue(_ok(result))

    # ------------------------------------------------------------------
    # _sanitize_member_filters  (pure helper)
    # ------------------------------------------------------------------
    def test_sanitize_filters_whitelist(self):
        out = member_management._sanitize_member_filters(
            {"status": "Active", "current_membership_type": "X", "secret": "drop"}
        )
        self.assertEqual(set(out.keys()), {"status", "current_membership_type"})

    def test_sanitize_filters_json_string(self):
        out = member_management._sanitize_member_filters('{"status": "Active", "bogus": 1}')
        self.assertEqual(out, {"status": "Active"})

    def test_sanitize_filters_invalid_json_returns_empty(self):
        out = member_management._sanitize_member_filters("not-json{{{")
        self.assertEqual(out, {})

    def test_sanitize_filters_none_returns_empty(self):
        self.assertEqual(member_management._sanitize_member_filters(None), {})

    def test_enrich_members_with_chapters_pure(self):
        members = [{"name": "M1"}, {"name": "M2"}]
        rels = {
            "M1": [{"parent": "ChA", "status": "Active", "chapter_join_date": "2026-01-01"}],
        }
        info = {"ChA": {"name": "ChA", "region": "RegA"}}
        enriched = member_management._enrich_members_with_chapters(members, rels, info)
        self.assertEqual(len(enriched[0]["chapters"]), 1)
        self.assertEqual(enriched[0]["chapters"][0]["region"], "RegA")
        self.assertIsNotNone(enriched[0]["primary_chapter"])
        self.assertEqual(enriched[1]["chapters"], [])
        self.assertIsNone(enriched[1]["primary_chapter"])

    # ------------------------------------------------------------------
    # add_member_to_chapter_roster  (non-whitelisted helper)
    # ------------------------------------------------------------------
    def test_add_member_to_chapter_roster(self):
        member = self._make_member()
        member_management.add_member_to_chapter_roster(member.name, self.chapter.name)
        self.assertEqual(self._chapter_member_parent(member.name), self.chapter.name)

    def test_add_member_to_chapter_roster_no_chapter_noop(self):
        member = self._make_member()
        # Should not raise and should not assign anything.
        member_management.add_member_to_chapter_roster(member.name, None)
        self.assertIsNone(self._chapter_member_parent(member.name))


class TestMemberManagementMT940Helpers(EnhancedTestCase):
    """Area (B): MT940 PURE helpers only (no live import pipeline)."""

    def test_get_mt940_import_url(self):
        result = member_management.get_mt940_import_url()
        self.assertTrue(_ok(result))
        self.assertEqual(_data(result), "/mt940_import")

    # ------------------------------------------------------------------
    # extract_iban_from_mt940_content
    # ------------------------------------------------------------------
    def test_extract_iban_from_25_tag(self):
        content = ":20:STARTUMS\n:25:NL39RABO0300065264\n:28C:1/1\n"
        self.assertEqual(
            member_management.extract_iban_from_mt940_content(content), "NL39RABO0300065264"
        )

    def test_extract_iban_fallback_pattern(self):
        # No :25: tag; long IBAN pattern present elsewhere.
        content = "garbage DE89370400440532013000 more text"
        self.assertEqual(
            member_management.extract_iban_from_mt940_content(content), "DE89370400440532013000"
        )

    def test_extract_iban_none_when_absent(self):
        self.assertIsNone(
            member_management.extract_iban_from_mt940_content("no iban here at all")
        )

    # ------------------------------------------------------------------
    # _parse_mt940_amount
    # ------------------------------------------------------------------
    def test_parse_amount_with_trailing_currency(self):
        amount, currency = member_management._parse_mt940_amount({"amount": "-898.54 EUR"})
        self.assertAlmostEqual(amount, -898.54)
        self.assertEqual(currency, "EUR")

    def test_parse_amount_plain_number_defaults_eur(self):
        amount, currency = member_management._parse_mt940_amount({"amount": "1234.56"})
        self.assertAlmostEqual(amount, 1234.56)
        self.assertEqual(currency, "EUR")

    def test_parse_amount_explicit_currency_field_wins(self):
        amount, currency = member_management._parse_mt940_amount(
            {"amount": "10.00", "currency": "USD"}
        )
        self.assertAlmostEqual(amount, 10.0)
        self.assertEqual(currency, "USD")

    def test_parse_amount_missing_returns_none(self):
        amount, currency = member_management._parse_mt940_amount({})
        self.assertIsNone(amount)
        self.assertEqual(currency, "EUR")

    def test_parse_amount_garbage_with_embedded_number(self):
        amount, currency = member_management._parse_mt940_amount({"amount": "abc-50.25xyz"})
        self.assertAlmostEqual(amount, -50.25)

    # ------------------------------------------------------------------
    # find_bank_account_by_iban_improved
    # ------------------------------------------------------------------
    def _make_bank_account(self, iban):
        company = frappe.get_all("Company", limit=1)[0].name
        # A Bank master is required for Bank Account.
        bank_name = f"MM Test Bank {self.uid}"
        if not frappe.db.exists("Bank", bank_name):
            frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert()
        ba = frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": f"MM Acct {self.uid} {frappe.generate_hash(length=4)}",
                "bank": bank_name,
                "iban": iban,
                "bank_account_no": iban,
                "company": company,
            }
        )
        ba.insert()
        return ba, company

    def test_find_bank_account_by_iban_with_company(self):
        iban = "NL39RABO0300065264"
        ba, company = self._make_bank_account(iban)
        found = member_management.find_bank_account_by_iban_improved(iban, company)
        self.assertEqual(found, ba.name)

    def test_find_bank_account_by_iban_without_company_fallback(self):
        iban = "NL91ABNA0417164300"
        ba, _company = self._make_bank_account(iban)
        found = member_management.find_bank_account_by_iban_improved(iban)
        self.assertEqual(found, ba.name)

    def test_find_bank_account_by_iban_not_found(self):
        found = member_management.find_bank_account_by_iban_improved("NL00BANK0000000000")
        self.assertIsNone(found)
