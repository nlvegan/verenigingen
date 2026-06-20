# -*- coding: utf-8 -*-
# Copyright (c) 2026, Your Organization and Contributors
# See license.txt

"""
Coverage-focused integration tests for the previously-uncovered surfaces of
verenigingen/api/member_management.py:

  (A) Member-data permission helpers + email endpoint:
        can_view_members_without_chapter (admin / plain / board-with-role),
        get_chapter_member_emails + can_approve_members (admin path, deny path,
        nonexistent-chapter validation).

  (B) The MT940 import pipeline that the sibling coverage suite intentionally
      left out: extract_transaction_data_improved, _build_transaction_description,
      _resolve_mt940_bank_account (param / IBAN-autodetect / not-found / no-IBAN
      branches), create_bank_transaction_improved (idempotency + missing-account),
      and import_mt940_improved / _process_mt940_statements end-to-end against a
      real Bank Account using the committed hand-crafted MT940 fixtures (NO
      mocking; real Bank Transactions are created and asserted).

All tests use real Member/Chapter/Volunteer/Bank Account documents and assert DB
state + the OperationResult shape the caller actually receives.
"""

import frappe

from verenigingen.api import member_management
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.mt940_sample_statements import (
    GARBAGE_CONTENT,
    MULTI_TRANSACTION,
    SEPA_INCOMING_CREDIT,
    as_base64,
    parse_first,
)
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.utils.operation_result import OperationResult

# IBAN the committed MT940 fixtures use in their :25: account-id tag.
FIXTURE_STATEMENT_IBAN = "NL02ABNA0123456789"


def _ok(result):
    if isinstance(result, OperationResult):
        return result.success
    return result.get("success") is True


def _data(result):
    if isinstance(result, OperationResult):
        return result.data
    return result.get("data")


class TestMemberManagementMemberDataGates(PortalSelfServiceTestMixin, EnhancedTestCase):
    """Area (A): can_view_members_without_chapter, get_chapter_member_emails,
    can_approve_members."""

    def setUp(self):
        super().setUp()
        self.chapter = self.factory.create_chapter(
            chapter_name=f"MMEmail-{self.uid}", region="Test Region MME"
        )

    def _make_member(self, **kwargs):
        kwargs.setdefault(
            "email", f"mme-{self.uid}-{frappe.generate_hash(length=6)}@example.com"
        )
        return self.factory.create_member(first_name="MME", last_name="Member", **kwargs)

    def _add_chapter_member(self, member_name, status="Active", enabled=1):
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "members",
            {
                "member": member_name,
                "status": status,
                "enabled": enabled,
                "chapter_join_date": frappe.utils.today(),
            },
        )
        chapter_doc.save()

    def _make_board_admin_member(self):
        """member -> volunteer -> active board seat (Admin permissions_level), linked
        User. Returns (member, user)."""
        member = self._make_member()
        volunteer = self.factory.create_volunteer(member_name=member.name)
        role = self.factory.ensure_chapter_role(
            f"MME Board Role {self.uid}", attributes={"permissions_level": "Admin"}
        )
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()
        user = self._link_member_to_user(member, roles=("Verenigingen Member",))
        return member, user

    # ----- can_view_members_without_chapter ----------------------------
    def test_can_view_admin_is_true(self):
        # setUp runs as Administrator (an ADMIN_ROLES holder).
        self.assertTrue(member_management.can_view_members_without_chapter())

    def test_can_view_plain_member_is_false(self):
        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        with self._as_user(user.name):
            self.assertFalse(member_management.can_view_members_without_chapter())

    def test_can_view_no_member_record_is_false(self):
        user = self.factory.create_user_with_roles(
            email=f"mme-nomember-{self.uid}@example.com", roles=["Verenigingen Member"]
        )
        with self._as_user(user.name):
            self.assertFalse(member_management.can_view_members_without_chapter())

    def test_can_view_board_admin_member_is_true(self):
        _member, user = self._make_board_admin_member()
        with self._as_user(user.name):
            self.assertTrue(member_management.can_view_members_without_chapter())

    # ----- can_approve_members -----------------------------------------
    def test_can_approve_admin_is_true(self):
        self.assertTrue(member_management.can_approve_members())

    def test_can_approve_plain_member_is_false(self):
        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        with self._as_user(user.name):
            self.assertFalse(member_management.can_approve_members())

    # ----- get_chapter_member_emails (member_management version) --------
    def test_get_chapter_member_emails_admin(self):
        m1 = self._make_member(email=f"mme-a-{self.uid}@example.com")
        m2 = self._make_member(email=f"mme-b-{self.uid}@example.com")
        # The endpoint requires Member.membership_status in (Active, Pending).
        m1.db_set("membership_status", "Active")
        m2.db_set("membership_status", "Active")
        self._add_chapter_member(m1.name, status="Active")
        self._add_chapter_member(m2.name, status="Active")

        result = member_management.get_chapter_member_emails(self.chapter.name)

        self.assertTrue(_ok(result))
        emails = _data(result)["emails"]
        self.assertIn(m1.email, emails)
        self.assertIn(m2.email, emails)
        self.assertEqual(_data(result)["total_members"], len(_data(result)["members"]))
        self.assertEqual(_data(result)["chapter"]["name"], self.chapter.name)

    def test_get_chapter_member_emails_nonexistent_chapter_fails(self):
        # @handle_api_error converts the ValidationError raise into a failure result.
        result = member_management.get_chapter_member_emails(f"NO-CHAPTER-{self.uid}")
        self.assertFalse(_ok(result))

    def test_get_chapter_member_emails_denied_for_plain_member(self):
        # get_chapter_member_emails requires MEDIUM (member-email export); a plain
        # member (LOW profile) is denied by the security ladder, which RAISES a
        # PermissionError before the endpoint body runs. Assert the denial mechanism.
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        plain = self._make_member()
        user = self._link_member_to_user(plain, roles=("Verenigingen Member",))
        with self._as_user(user.name):
            self.expectErrorLog()
            with self.assertRaises(VPermissionError):
                member_management.get_chapter_member_emails(self.chapter.name)


class TestMemberManagementMT940Pipeline(EnhancedTestCase):
    """Area (B): MT940 extraction + resolution + import pipeline (real banking)."""

    def setUp(self):
        super().setUp()
        self.company = frappe.get_all("Company", limit=1)[0].name
        self.bank_name = f"MM MT940 Bank {self.uid}"
        if not frappe.db.exists("Bank", self.bank_name):
            frappe.get_doc({"doctype": "Bank", "bank_name": self.bank_name}).insert()
        self.bank_account = frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": f"MM MT940 Acct {self.uid}",
                "bank": self.bank_name,
                "iban": FIXTURE_STATEMENT_IBAN,
                "bank_account_no": FIXTURE_STATEMENT_IBAN,
                "company": self.company,
            }
        )
        self.bank_account.insert()

    # ----- extract_transaction_data_improved + _build_description ------
    def test_extract_transaction_data_from_real_statement(self):
        txn = parse_first(SEPA_INCOMING_CREDIT)
        data = member_management.extract_transaction_data_improved(txn)
        self.assertIsNotNone(data)
        self.assertAlmostEqual(float(data["amount"]), 150.00)
        self.assertEqual(data["currency"], "EUR")
        # SEPA counterparty parsed from the :86: /CNTP/ block.
        self.assertEqual(data["counterparty_name"], "Jan de Vries")
        # Description is built from SEPA remittance info, not raw tagged text.
        self.assertIn("Contributie 2024", data["description"])
        # end-to-end reference comes from the EREF tag.
        self.assertEqual(data["reference"], "INV-2024-0001")

    def test_extract_returns_none_for_unparseable_transaction(self):
        # A transaction object with no data dict yields None (no date/amount).
        class _Empty:
            data = {}

        self.assertIsNone(member_management.extract_transaction_data_improved(_Empty()))

    def test_build_transaction_description_prefers_sepa_remittance(self):
        sepa = {"remittance_info": "Clean SEPA text"}
        data = {"extra_details": "RAW DO NOT USE", "transaction_details": "ALSO RAW"}
        desc = member_management._build_transaction_description(sepa, data, "REF1")
        self.assertEqual(desc, "Clean SEPA text")

    def test_build_transaction_description_falls_back_to_raw(self):
        sepa = {}
        data = {"extra_details": "raw extra", "transaction_details": "raw details"}
        desc = member_management._build_transaction_description(sepa, data, "REF1")
        self.assertIn("raw extra", desc)
        self.assertIn("raw details", desc)

    def test_build_transaction_description_default_when_empty(self):
        desc = member_management._build_transaction_description({}, {}, "")
        self.assertEqual(desc, "MT940 Transaction")

    # ----- _resolve_mt940_bank_account ---------------------------------
    def test_resolve_with_explicit_bank_account(self):
        ba, company, error = member_management._resolve_mt940_bank_account(
            self.bank_account.name, None, SEPA_INCOMING_CREDIT
        )
        self.assertIsNone(error)
        self.assertEqual(ba, self.bank_account.name)
        # Company derived from the bank account.
        self.assertEqual(company, self.company)

    def test_resolve_autodetects_by_iban(self):
        ba, company, error = member_management._resolve_mt940_bank_account(
            None, self.company, SEPA_INCOMING_CREDIT
        )
        self.assertIsNone(error)
        self.assertEqual(ba, self.bank_account.name)

    def test_resolve_no_iban_in_content_returns_error(self):
        ba, _company, error = member_management._resolve_mt940_bank_account(
            None, self.company, "no iban tag anywhere here"
        )
        self.assertIsNone(ba)
        self.assertIsInstance(error, OperationResult)
        self.assertFalse(error.success)

    def test_resolve_iban_present_but_no_matching_account(self):
        # A :25: IBAN that has no Bank Account -> autodetect fails with error.
        content = ":25:NL99BANK0000000099\n:61:foo\n"
        ba, _company, error = member_management._resolve_mt940_bank_account(
            None, self.company, content
        )
        self.assertIsNone(ba)
        self.assertIsInstance(error, OperationResult)
        self.assertFalse(error.success)

    def test_resolve_explicit_nonexistent_account_returns_error(self):
        ba, _company, error = member_management._resolve_mt940_bank_account(
            f"NO-SUCH-ACCT-{self.uid}", self.company, SEPA_INCOMING_CREDIT
        )
        self.assertIsNone(ba)
        self.assertIsInstance(error, OperationResult)
        self.assertFalse(error.success)

    # ----- create_bank_transaction_improved ----------------------------
    def test_create_bank_transaction_missing_required_data(self):
        result = member_management.create_bank_transaction_improved(
            {"date": None, "amount": None}, self.bank_account.name, self.company
        )
        self.assertEqual(result, "missing_required_data")

    def test_create_bank_transaction_unknown_account(self):
        result = member_management.create_bank_transaction_improved(
            {"date": "2024-01-01", "amount": 10.0, "description": "x"},
            f"NO-SUCH-ACCT-{self.uid}",
            self.company,
        )
        self.assertTrue(result.startswith("bank_account_not_found"))

    def test_create_bank_transaction_created_then_idempotent(self):
        txn_data = {
            "date": "2024-03-03",
            "amount": 12.34,
            "description": "Unit test deposit",
            "reference": f"UTREF-{self.uid}",
            "counterparty_name": "Test Counterparty",
        }
        first = member_management.create_bank_transaction_improved(
            txn_data, self.bank_account.name, self.company
        )
        self.assertEqual(first, "created")
        # Same data -> deterministic transaction_id -> deduplicated.
        second = member_management.create_bank_transaction_improved(
            txn_data, self.bank_account.name, self.company
        )
        self.assertEqual(second, "exists")

    # ----- import_mt940_improved (end-to-end) --------------------------
    def test_import_mt940_improved_creates_transactions(self):
        result = member_management.import_mt940_improved(
            as_base64(MULTI_TRANSACTION), bank_account=self.bank_account.name
        )
        self.assertTrue(_ok(result), msg=result)
        # The 3-entry fixture creates 3 distinct Bank Transactions.
        self.assertEqual(_data(result)["transactions_created"], 3)
        self.assertEqual(_data(result)["bank_account"], self.bank_account.name)

    def test_import_mt940_improved_idempotent_on_rerun(self):
        b64 = as_base64(SEPA_INCOMING_CREDIT)
        first = member_management.import_mt940_improved(
            b64, bank_account=self.bank_account.name
        )
        self.assertTrue(_ok(first))
        self.assertEqual(_data(first)["transactions_created"], 1)
        # Re-importing the same statement creates nothing new (skipped).
        second = member_management.import_mt940_improved(
            b64, bank_account=self.bank_account.name
        )
        self.assertTrue(_ok(second))
        self.assertEqual(_data(second)["transactions_created"], 0)
        self.assertGreaterEqual(_data(second)["transactions_skipped"], 1)

    def test_import_mt940_improved_autodetects_bank_account_by_iban(self):
        # No explicit bank_account: resolved via the :25: IBAN in the fixture.
        result = member_management.import_mt940_improved(as_base64(SEPA_INCOMING_CREDIT))
        self.assertTrue(_ok(result), msg=result)
        self.assertEqual(_data(result)["bank_account"], self.bank_account.name)

    def test_import_mt940_improved_garbage_content_fails_gracefully(self):
        result = member_management.import_mt940_improved(
            as_base64(GARBAGE_CONTENT), bank_account=self.bank_account.name
        )
        # Either "no statements" or a parse failure -> a failure result, no crash.
        self.assertFalse(_ok(result))
