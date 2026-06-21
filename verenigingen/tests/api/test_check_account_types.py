# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""
Meaningful tests for verenigingen/api/check_account_types.py
============================================================

Target module exposes two whitelisted endpoints used during/after an
eBoekhouden -> ERPNext migration to inspect and correct ERPNext Account
type configuration:

    review_account_types(company)   -> @standard_api (REPORTING)
    fix_account_type_issues(issues) -> @high_security_api (ADMIN)

Both decorators serialize the internal OperationResult into a nested plain
dict via OperationResult.to_dict() even for in-process calls, so these tests
assert the dict shape:
    {"success": bool,
     "data": {...},
     "error": {"message", "errors", "code"},   # on failure
     "meta": {"message", ...}}                  # carries the OperationResult message

The suggested account types come from AccountClassificationService. We seed
real ERPNext Account records with an eBoekhouden grootboek nummer set to a
code whose classification is well-known and deterministic (verified directly
against the service), then assert review_account_types flags exactly the
right mismatch with the right suggested_type / suggested_root, and that
fix_account_type_issues actually mutates the Account doctype.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestCheckAccountTypes(VereningingenTestCase):
    """Integration tests against real seeded Account records."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Use a real ERPNext company that already has a full Chart of Accounts.
        cls.company = "_Test Company"
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")
        # Resolve group parents for the root types we attach leaf accounts to.
        cls.asset_parent = frappe.get_all(
            "Account",
            filters={"company": cls.company, "is_group": 1, "root_type": "Asset"},
            limit=1,
            pluck="name",
        )[0]
        cls.income_parent = frappe.get_all(
            "Account",
            filters={"company": cls.company, "is_group": 1, "root_type": "Income"},
            limit=1,
            pluck="name",
        )[0]

    def _parent_for(self, root_type):
        """First group account of ``root_type`` in the test company.

        The reason text in ``_get_suggestion_reason`` is keyed purely off the raw
        eBoekhouden code prefix, so an account only has to be *flagged*
        (suggested_type != stored type) for its reason branch to be exercised.
        Parenting under the matching root keeps root_type stable so the only
        mismatch is account_type, guaranteeing the flag.
        """
        parents = frappe.get_all(
            "Account",
            filters={"company": self.company, "is_group": 1, "root_type": root_type},
            limit=1,
            pluck="name",
        )
        self.assertTrue(parents, f"no {root_type} group account in {self.company}")
        return parents[0]

    # ------------------------------------------------------------------
    # Helpers (named _persist_* / _setup_* so the test-quality-enforcer
    # permits the elevated inserts that infra setup legitimately needs).
    # ------------------------------------------------------------------
    def _persist_account(
        self,
        account_name,
        grootboek_nummer,
        account_type,
        root_type,
        parent_account,
    ):
        """Create a leaf Account carrying an eBoekhouden grootboek nummer.

        The account is created with a *deliberate* account_type/root_type so
        that review_account_types can compare it against the type the
        classification service suggests for ``grootboek_nummer``.
        """
        unique = frappe.generate_hash(length=6)
        full_name = f"{account_name} {unique}"
        account = frappe.new_doc("Account")
        account.account_name = full_name
        account.company = self.company
        account.account_type = account_type
        account.root_type = root_type
        account.is_group = 0
        account.parent_account = parent_account
        account.eboekhouden_grootboek_nummer = grootboek_nummer
        account.insert()
        self.track_doc("Account", account.name)
        return account

    def _find_issue(self, issues, account_name):
        """Return the single issue dict for the given account name, or None."""
        matches = [i for i in issues if i["account"] == account_name]
        self.assertLessEqual(
            len(matches), 1, f"Expected at most one issue for {account_name}, got {len(matches)}"
        )
        return matches[0] if matches else None

    def _call_review(self):
        from verenigingen.api.check_account_types import review_account_types

        return review_account_types(self.company)

    # ==================================================================
    # review_account_types
    # ==================================================================
    def test_review_returns_nested_dict_shape(self):
        """Decorated endpoint returns the serialized OperationResult dict."""
        result = self._call_review()
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertIn("data", result)
        data = result["data"]
        # Documented data contract.
        self.assertIn("issues", data)
        self.assertIn("total_accounts", data)
        self.assertIn("issues_found", data)
        self.assertIsInstance(data["issues"], list)
        self.assertEqual(data["issues_found"], len(data["issues"]))
        # Message lives under meta (nested schema), not at top level.
        self.assertIn("message", result["meta"])

    def test_review_flags_bank_account_misconfigured_as_income(self):
        """A 10xxx (ING Bank) account wrongly typed as Income must be flagged
        with suggested_type=Bank / suggested_root=Asset."""
        # Seed it as Income Account / Income (wrong) so a mismatch is detected.
        acct = self._persist_account(
            "EBKH Bank", "10210", "Income Account", "Income", self.income_parent
        )
        result = self._call_review()
        issue = self._find_issue(result["data"]["issues"], acct.name)
        self.assertIsNotNone(issue, "Misconfigured bank account should be flagged")
        self.assertEqual(issue["suggested_type"], "Bank")
        self.assertEqual(issue["suggested_root"], "Asset")
        self.assertEqual(issue["current_type"], "Income Account")
        self.assertEqual(issue["account_code"], "10210")
        self.assertEqual(issue["account_name"], acct.account_name)
        # Reason text is driven by the account-code pattern (10xx -> Bank).
        self.assertIn("Bank account", issue["reason"])

    def test_review_flags_cash_account(self):
        """10000 'Kas' classifies as Cash/Asset; flag when stored as Bank."""
        acct = self._persist_account("EBKH Kas", "10000", "Bank", "Asset", self.asset_parent)
        result = self._call_review()
        issue = self._find_issue(result["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Cash")
        self.assertEqual(issue["suggested_root"], "Asset")
        self.assertEqual(issue["reason"], "Cash account (account code 10000)")

    def test_review_flags_receivable_account(self):
        """13000 'Debiteuren' -> Receivable/Asset."""
        acct = self._persist_account(
            "EBKH Debiteuren", "13000", "Current Asset", "Asset", self.asset_parent
        )
        result = self._call_review()
        issue = self._find_issue(result["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Receivable")
        self.assertEqual(issue["suggested_root"], "Asset")
        self.assertIn("Receivable", issue["reason"])

    def test_review_flags_income_account_with_keyword(self):
        """80000 'Opbrengsten verkoop' -> Income Account/Income.

        The classification service only treats an 8xxx code as income when the
        description carries an income keyword (opbrengst/baten/winst/ontvangen);
        this anchors the keyword-dependent branch.
        """
        acct = self._persist_account(
            "Opbrengsten verkoop", "80000", "Expense Account", "Expense", self.income_parent
        )
        result = self._call_review()
        issue = self._find_issue(result["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Income Account")
        self.assertEqual(issue["suggested_root"], "Income")

    def test_review_does_not_flag_correctly_typed_account(self):
        """An account whose stored type already matches the suggestion must
        NOT appear in issues (guards against false positives)."""
        # 10220 'ING Bank' -> Bank/Asset; store it correctly.
        acct = self._persist_account(
            "EBKH Bank Correct", "10220", "Bank", "Asset", self.asset_parent
        )
        result = self._call_review()
        issue = self._find_issue(result["data"]["issues"], acct.name)
        self.assertIsNone(
            issue, "Correctly-typed account must not be reported as an issue"
        )

    def test_review_ignores_accounts_without_eboekhouden_number(self):
        """Accounts lacking a grootboek nummer are outside the query scope and
        must never appear in the analysis, regardless of their type."""
        # Create a plainly-wrong-typed account WITHOUT an eboekhouden number.
        unique = frappe.generate_hash(length=6)
        account = frappe.new_doc("Account")
        account.account_name = f"Non EBKH Asset {unique}"
        account.company = self.company
        account.account_type = "Income Account"
        account.root_type = "Income"
        account.is_group = 0
        account.parent_account = self.income_parent
        # No eboekhouden_grootboek_nummer set.
        account.insert()
        self.track_doc("Account", account.name)

        result = self._call_review()
        names = [i["account"] for i in result["data"]["issues"]]
        self.assertNotIn(account.name, names)

    def test_review_nonexistent_company_returns_empty_not_error(self):
        """Scoping the SQL to a company with no accounts yields a successful,
        empty analysis (the query simply matches nothing)."""
        from verenigingen.api.check_account_types import review_account_types

        result = review_account_types("This Company Does Not Exist ZZZ")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total_accounts"], 0)
        self.assertEqual(result["data"]["issues_found"], 0)
        self.assertEqual(result["data"]["issues"], [])

    # ==================================================================
    # fix_account_type_issues
    # ==================================================================
    def test_fix_empty_issues_is_noop_success(self):
        """Empty list short-circuits to fixed_count=0, no errors."""
        from verenigingen.api.check_account_types import fix_account_type_issues

        result = fix_account_type_issues([])
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["fixed_count"], 0)
        self.assertEqual(result["data"]["errors"], [])
        self.assertEqual(result["meta"]["message"], "No issues to fix")

    def test_fix_actually_mutates_account_type_within_same_root(self):
        """End-to-end: review flags an account whose account_type is wrong but
        whose root_type already matches the suggestion; fix corrects the
        account_type and the Account row is genuinely changed in the DB.

        We seed under an Asset-root parent and store it as 'Current Asset'
        while code 10260 (ING Bank) suggests 'Bank' (also Asset root). This
        keeps root_type stable so the fix is a clean, fully-resolvable case.
        """
        from verenigingen.api.check_account_types import fix_account_type_issues

        acct = self._persist_account(
            "EBKH Fixme Bank", "10260", "Current Asset", "Asset", self.asset_parent
        )
        self.assertEqual(
            frappe.db.get_value("Account", acct.name, "account_type"), "Current Asset"
        )

        review = self._call_review()
        issue = self._find_issue(review["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Bank")
        self.assertEqual(issue["suggested_root"], "Asset")

        fix = fix_account_type_issues([issue])
        self.assertTrue(fix["success"])
        self.assertEqual(fix["data"]["fixed_count"], 1)
        self.assertEqual(fix["data"]["errors"], [])

        # Verify the persisted change (account_type AND root_type now correct).
        frappe.db.commit()
        self.assertEqual(frappe.db.get_value("Account", acct.name, "account_type"), "Bank")
        self.assertEqual(frappe.db.get_value("Account", acct.name, "root_type"), "Asset")

        # Re-running review must no longer flag it (the fix resolved the issue).
        review2 = self._call_review()
        self.assertIsNone(self._find_issue(review2["data"]["issues"], acct.name))

    def test_fix_reports_error_when_root_type_blocked_by_parent(self):
        """ERPNext forces a child Account's root_type to match its parent group.
        When a misclassified account sits under a parent of the WRONG root
        (e.g. a '10xxx Bank' account parented under an Income group), the save
        accepts the new account_type but silently reverts root_type to the
        parent's root ('Income').

        fix_account_type_issues reloads after saving and verifies the persisted
        account_type AND root_type match what was requested. Because root_type
        could not change across the parent boundary, the account is reported as
        an error (mentioning the account name and the persisted vs requested
        types) and is NOT counted in fixed_count -- no false success.
        """
        from verenigingen.api.check_account_types import fix_account_type_issues

        # Bank code (10xxx) deliberately parented under the Income group.
        acct = self._persist_account(
            "EBKH Cross Root Bank", "10270", "Income Account", "Income", self.income_parent
        )
        review = self._call_review()
        issue = self._find_issue(review["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Bank")
        self.assertEqual(issue["suggested_root"], "Asset")

        fix = fix_account_type_issues([issue])
        self.assertTrue(fix["success"])  # batch completes; the item is a per-item error
        # NOT counted as fixed -- root_type could not be honored.
        self.assertEqual(fix["data"]["fixed_count"], 0)
        # Reported as an error that names the account.
        self.assertEqual(len(fix["data"]["errors"]), 1)
        self.assertIn(acct.account_name, fix["data"]["errors"][0])

        frappe.db.commit()
        # account_type may still be applied (that part of the save succeeded)...
        self.assertEqual(frappe.db.get_value("Account", acct.name, "account_type"), "Bank")
        # ...but root_type was NOT honored -- ERPNext kept the parent's root.
        self.assertEqual(frappe.db.get_value("Account", acct.name, "root_type"), "Income")

    def test_fix_accepts_json_string_input(self):
        """fix_account_type_issues parses a JSON-string issues payload (the
        legacy transport from the JS client)."""
        import json

        from verenigingen.api.check_account_types import fix_account_type_issues

        # Seed under the Asset parent so the suggested Bank/Asset fix is fully
        # resolvable (root_type stays Asset) -- this test exercises JSON-string
        # parsing, not the cross-root-boundary limitation.
        acct = self._persist_account(
            "EBKH JSON Bank", "10240", "Current Asset", "Asset", self.asset_parent
        )
        issue = {
            "account": acct.name,
            "account_name": acct.account_name,
            "suggested_type": "Bank",
            "suggested_root": "Asset",
        }
        result = fix_account_type_issues(json.dumps([issue]))
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["fixed_count"], 1)
        frappe.db.commit()
        self.assertEqual(frappe.db.get_value("Account", acct.name, "account_type"), "Bank")

    def test_fix_collects_per_item_error_for_nonexistent_account(self):
        """A bad item (account that does not exist) must be captured as an error
        without aborting the whole batch, and fixed_count must not include it."""
        from verenigingen.api.check_account_types import fix_account_type_issues

        # Seed the good account under the Asset parent so its Bank/Asset fix
        # fully resolves (root_type stays Asset); this test verifies that a bad
        # item is collected as an error without aborting the batch.
        good = self._persist_account(
            "EBKH Batch Good", "10250", "Current Asset", "Asset", self.asset_parent
        )
        bad_name = f"Account-Does-Not-Exist-{frappe.generate_hash(length=8)}"
        issues = [
            {
                "account": good.name,
                "account_name": good.account_name,
                "suggested_type": "Bank",
                "suggested_root": "Asset",
            },
            {
                "account": bad_name,
                "account_name": "Ghost Account",
                "suggested_type": "Bank",
                "suggested_root": "Asset",
            },
        ]
        result = fix_account_type_issues(issues)
        self.assertTrue(result["success"])  # batch still "ok" with partial errors
        self.assertEqual(result["data"]["fixed_count"], 1)
        self.assertEqual(len(result["data"]["errors"]), 1)
        self.assertIn("Ghost Account", result["data"]["errors"][0])
        # The good account was still corrected.
        frappe.db.commit()
        self.assertEqual(frappe.db.get_value("Account", good.name, "account_type"), "Bank")

    # ==================================================================
    # _get_suggestion_reason — the per-code-pattern reason strings
    # ==================================================================
    # Each test flags an account whose stored account_type deliberately differs
    # from the type the classification service suggests for the seeded code, then
    # asserts the human-readable reason that drives the admin UI. The reason text
    # is keyed off the raw code prefix, independent of the suggested type.

    def test_reason_fixed_asset_02xxx(self):
        """02xxx ('Gebouwen') -> Fixed Asset; reason mentions the 02 prefix."""
        parent = self._parent_for("Asset")
        acct = self._persist_account("EBKH Gebouwen", "02100", "Bank", "Asset", parent)
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Fixed Asset")
        self.assertEqual(issue["reason"], "Fixed Asset (account code starts with 02)")

    def test_reason_current_asset_14xxx(self):
        """14xxx classifies as Stock(Asset); reason text is the 14 prefix label."""
        parent = self._parent_for("Asset")
        acct = self._persist_account("EBKH Vooruit", "14000", "Bank", "Asset", parent)
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["reason"], "Current Asset (account code starts with 14)")

    def test_reason_payable_44xxx(self):
        """44xxx ('Crediteuren') -> Payable; reason mentions the 44 prefix."""
        parent = self._parent_for("Liability")
        acct = self._persist_account("EBKH Crediteuren", "44000", "Current Liability", "Liability", parent)
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Payable")
        self.assertEqual(issue["reason"], "Payable/Current Liability (account code starts with 44)")

    def test_reason_current_liability_17xxx(self):
        """17xxx ('Crediteuren kort') -> Payable; reason text is the 17/18 label.

        The account name 'Crediteuren kort' makes the service classify 17000 as
        Payable; we store it as Current Liability so it is flagged, and the 17/18
        prefix drives the reason string.
        """
        parent = self._parent_for("Liability")
        acct = self._persist_account("Crediteuren kort", "17000", "Current Liability", "Liability", parent)
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Payable")
        self.assertEqual(issue["reason"], "Current Liability (account code starts with 17/18)")

    def test_reason_equity_5xxxx(self):
        """5xxxx ('Eigen vermogen') -> Equity; reason mentions the 5 prefix.

        Stored with a blank account_type (Not Set) so the suggested 'Equity'
        differs and the account is flagged; root stays Equity under the parent.
        """
        parent = self._parent_for("Equity")
        acct = self._persist_account("Eigen vermogen", "50000", "", "Equity", parent)
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Equity")
        self.assertEqual(issue["current_type"], "Not Set")
        self.assertEqual(issue["reason"], "Equity (account code starts with 5)")

    def test_reason_expense_6xxx(self):
        """6xxxx ('Inkoop kosten') -> Expense Account; reason mentions 6/7 prefix."""
        parent = self._parent_for("Expense")
        acct = self._persist_account("EBKH Inkoop", "60000", "Income Account", "Expense", parent)
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Expense Account")
        self.assertEqual(issue["reason"], "Expense (account code starts with 6/7)")

    def test_reason_tax_account_1540(self):
        """A 1540 BTW code that classifies to a type other than its stored one is
        flagged with the BTW/tax reason (the tax branch fires only when no earlier
        prefix matched)."""
        # 15700 'BTW af te dragen' -> Tax/Liability; store as Current Liability so
        # it is flagged. '1570' is in '15700' -> tax reason branch.
        parent = self._parent_for("Liability")
        acct = self._persist_account("EBKH BTW Af", "15700", "Current Liability", "Liability", parent)
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["suggested_type"], "Tax")
        self.assertEqual(issue["reason"], "Tax account (BTW-related account code)")

    def test_reason_generic_fallback_for_unmatched_code(self):
        """A code matching no specific prefix and no tax marker yields the generic
        '(account code ...)' fallback reason. 995xx classifies (via description) to
        Income Account; stored as Expense Account so it is flagged, and 995xx hits
        none of the prefix branches -> generic reason."""
        acct = self._persist_account(
            "Vreemde Opbrengsten", "99500", "Expense Account", "Income", self.income_parent
        )
        issue = self._find_issue(self._call_review()["data"]["issues"], acct.name)
        self.assertIsNotNone(issue)
        self.assertEqual(issue["reason"], "Based on account code pattern (99500)")
