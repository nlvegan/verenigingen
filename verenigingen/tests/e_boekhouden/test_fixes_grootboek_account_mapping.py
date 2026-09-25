"""Regression tests for #1363.

``verenigingen/fixes/eboekhouden_utils.py::map_grootboek_to_erpnext_account()``
built an unescaped substring LIKE (``account_name LIKE f"%{grootboek_nr}%"``)
from an external e-Boekhouden ledger number and took the single match with no
ambiguity guard at all -- a grootboek_nr of "80" matched an account whose name
merely CONTAINED "80", e.g. "8000 - Sales - ABBR". Fixed to match the exact
``account_number`` field instead, refusing (falling through to account
creation) on 0 or more than 1 match rather than guessing.

This is defensive hardening of code that is currently UNREACHABLE, not a live
exploit fix: the only caller, ``verenigingen/fixes/step1_fix_data_fetching.py``,
calls 14 names (including ``map_grootboek_to_erpnext_account`` itself) that it
neither defines nor imports, so every real invocation of its whitelisted
``test_new_invoice_creation()`` NameErrors first (filed as #1395; NOT fixed
here -- restoring that import would make a `si.save(); si.submit()` write path
against real e-Boekhouden data callable on any site with `developer_mode`
enabled, which veg11's site_config has, and #1395's own investigation found
that path would silently create duplicate Accounts on real data. See #1395 for
the full evidence and the quarantine-vs-delete question for that module).

All accounts created here are inserted WITHOUT commit, so EnhancedTestCase's
per-method rollback removes them; nothing here needs ``track_doc``.

Run with:
    bench --site test_site_8 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_fixes_grootboek_account_mapping
"""

from unittest.mock import patch

import frappe

import verenigingen.fixes.eboekhouden_utils as eboekhouden_utils
from verenigingen.fixes.eboekhouden_utils import map_grootboek_to_erpnext_account
from verenigingen.tests.e_boekhouden.test_account_hierarchy_service_db_coverage import _uniq
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class _GrootboekMappingBase(EnhancedTestCase):
    """Shared EUR company with a full default ERPNext chart of accounts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def _asset_group(self):
        return frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Asset", "is_group": 1}, "name"
        )

    def _make_leaf_account(self, account_name, account_number):
        """Insert a real leaf Account with a given account_number (uncommitted)."""
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": account_name,
                "company": self.company,
                "account_number": account_number,
                "root_type": "Asset",
                "is_group": 0,
                "parent_account": self._asset_group(),
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name


class TestMapGrootboekToErpnextAccountByNumber(_GrootboekMappingBase):
    """#1363: exact account_number match, refuse-don't-guess on 0 or >1 matches."""

    def test_partial_number_does_not_match_an_account_whose_name_merely_contains_it(self):
        """Pre-fix: `account_name LIKE f"%{grootboek_nr}%"` matched "8000 - ..."
        for grootboek_nr "80", because "80" is a substring of "8000". Post-fix:
        account_number is matched exactly, so a coincidental substring cannot
        match, and the (distinct) 8000 account is never returned."""
        unrelated = self._make_leaf_account(_uniq("Sales 8000"), "8000")

        matched = map_grootboek_to_erpnext_account("80", "sales", self.company)

        self.assertNotEqual(
            matched,
            unrelated,
            f"grootboek_nr '80' must not match account_number '8000' ({unrelated}) "
            f"via a substring coincidence, but got {matched!r}",
        )

    def test_partial_number_mutation_control_reproduces_the_original_bug(self):
        """Control: the substring-LIKE the fix replaced really does over-match,
        proving the fix (not incidental test setup) is what changes the outcome.
        This re-implements the pre-fix query shape directly rather than editing
        production code, so it never needs reverting."""
        unrelated = self._make_leaf_account(_uniq("Sales 8000"), "8000")

        old_vulnerable_match = frappe.db.get_value(
            "Account", {"company": self.company, "account_name": ["like", "%80%"]}, "name"
        )

        self.assertEqual(
            old_vulnerable_match,
            unrelated,
            "control did not reproduce the substring over-match the fix addresses",
        )

    def test_exact_account_number_match_is_returned_and_mapping_attempt_recorded(self):
        """A genuine, unambiguous account_number match is still resolved and a
        mapping is still attempted (create_account_mapping's own persistence
        target is a separately-tracked no-op, #689 -- not re-verified here)."""
        number = _uniq("42")[:20]
        expected = self._make_leaf_account(_uniq("Exact Match"), number)

        with patch.object(eboekhouden_utils, "create_account_mapping") as mock_create_mapping:
            matched = map_grootboek_to_erpnext_account(number, "sales", self.company)

        self.assertEqual(matched, expected)
        mock_create_mapping.assert_called_once_with(number, expected)

    def test_ambiguous_account_number_refuses_rather_than_guessing(self):
        """ERPNext's own Account.validate_account_number() rejects a second
        account with the same account_number in the same company through normal
        insert, so an ambiguous match cannot arise from ordinary use -- but stale
        data (e.g. written via frappe.db.set_value, which bypasses validation)
        can still produce it. Force that shape directly rather than asserting
        something ERPNext itself already prevents."""
        number = _uniq("dup")[:20]
        first = self._make_leaf_account(_uniq("Dup One"), number)
        second = self._make_leaf_account(_uniq("Dup Two"), f"{number}-tmp")
        frappe.db.set_value("Account", second, "account_number", number, update_modified=False)

        # The refuse-and-create-new fallback also carries account_number =
        # grootboek_nr (see create_account_from_grootboek), which collides with
        # `second`'s forced duplicate here -- an expected, harness-caught
        # Error Log from that specific fallback attempt, not a defect.
        self.expectErrorLog("Failed to create account for", "Account Number")

        matched = map_grootboek_to_erpnext_account(number, "sales", self.company)

        # Refuses to guess between the two ambiguous existing accounts: falls
        # through to creating a genuinely new one instead of reusing either.
        self.assertNotIn(matched, (first, second))

    def test_self_created_account_is_reused_on_the_next_call_not_duplicated(self):
        """create_account_from_grootboek() must set account_number to the same
        grootboek_nr the lookup above now matches on. Without that, every call
        for an unmapped grootboek_nr would create a fresh duplicate account
        instead of finding the one a prior call already created."""
        number = _uniq("new")[:20]

        first_call = map_grootboek_to_erpnext_account(number, "sales", self.company)
        second_call = map_grootboek_to_erpnext_account(number, "sales", self.company)

        self.assertEqual(
            first_call,
            second_call,
            "second call for the same grootboek_nr created a duplicate account "
            "instead of reusing the one the first call created",
        )
        self.assertEqual(frappe.db.get_value("Account", first_call, "account_number"), number)
