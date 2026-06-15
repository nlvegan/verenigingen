"""
Tests for SmartTegenrekeningMapper (DEPRECATED module, still loaded).

Target: verenigingen/e_boekhouden/utils/smart_tegenrekening_mapper.py

NOTE: create_invoice_line_for_tegenrekening is already partially exercised by
test_rest_migration_helpers.py (the "no code raises ValidationError" path).
Here we cover the class internals NOT touched there:
- _generate_item_name (pure string)
- _get_descriptive_name_from_account (pure string)
- _get_account_by_code lookup paths (DB-backed, account-code / account-number /
  name-pattern resolution + ledger-id branch)
- get_item_for_tegenrekening guard clauses

No live eBoekhouden HTTP connection is needed.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_tegenrekening_mapper
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.smart_tegenrekening_mapper import SmartTegenrekeningMapper
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# Pure string helpers (no DB) - mapper company doesn't matter
# ---------------------------------------------------------------------------
class TestPureStringHelpers(unittest.TestCase):
    def setUp(self):
        # __init__ only emits a warning + sets attributes; no DB access.
        self.mapper = SmartTegenrekeningMapper(company="Whatever Co")

    def test_generate_item_name_passthrough(self):
        out = self.mapper._generate_item_name("Algemene kosten advies", "4500")
        self.assertEqual(out, "Algemene kosten advies")

    def test_generate_item_name_truncates_long(self):
        long_name = "A" * 100
        out = self.mapper._generate_item_name(long_name, "4500")
        self.assertEqual(len(out), 60)
        self.assertTrue(out.endswith("..."))

    def test_descriptive_name_three_parts(self):
        out = self.mapper._get_descriptive_name_from_account(
            "42308", "42308 - Bijeenkomsten: deelnemersbijdragen - NVV"
        )
        self.assertEqual(out, "Bijeenkomsten: deelnemersbijdragen")

    def test_descriptive_name_two_parts(self):
        out = self.mapper._get_descriptive_name_from_account("80001", "80001 - Contributie")
        self.assertEqual(out, "Contributie")

    def test_descriptive_name_many_parts_joins_middle(self):
        out = self.mapper._get_descriptive_name_from_account("100", "100 - Foo - Bar - NVV")
        self.assertEqual(out, "Foo - Bar")

    def test_descriptive_name_no_separator(self):
        self.assertIsNone(self.mapper._get_descriptive_name_from_account("100", "JustAName"))

    def test_descriptive_name_none_account(self):
        self.assertIsNone(self.mapper._get_descriptive_name_from_account("100", None))


# ---------------------------------------------------------------------------
# get_item_for_tegenrekening guard clauses
# ---------------------------------------------------------------------------
class TestGetItemGuards(unittest.TestCase):
    def setUp(self):
        self.mapper = SmartTegenrekeningMapper(company="Whatever Co")

    def test_no_account_code_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.mapper.get_item_for_tegenrekening("")


# ---------------------------------------------------------------------------
# _get_account_by_code - DB-backed resolution paths
# ---------------------------------------------------------------------------
class TestGetAccountByCode(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST Tegenrek Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TTGC"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    @classmethod
    def _persist_account(cls, acct_name, *, account_number=None, grootboek=None):
        parent = frappe.db.get_value(
            "Account", {"company": cls.company, "root_type": "Income", "is_group": 1}, "name"
        )
        full = f"{acct_name} - {cls.abbr}"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = cls.company
        doc.parent_account = parent
        doc.root_type = "Income"
        doc.account_type = "Income Account"
        if account_number:
            doc.account_number = account_number
        if grootboek and frappe.db.has_column("Account", "eboekhouden_grootboek_nummer"):
            doc.eboekhouden_grootboek_nummer = grootboek
        doc.insert(ignore_permissions=True)
        return doc.name

    def _mapper(self):
        return SmartTegenrekeningMapper(company=self.company)

    def test_resolve_by_account_number(self):
        acct = self._persist_account("Tegenrek ByNumber", account_number="80501")
        mapper = self._mapper()
        self.assertEqual(mapper._get_account_by_code("80501"), acct)

    def test_resolve_by_name_pattern(self):
        # Persist an account with NO account_number and NO grootboek so the
        # grootboek and account_number lookups MISS; only the name-pattern
        # branch ("<code> - % - <abbr>", prod ~lines 259-268) can resolve it.
        # The account name itself starts with the code so it matches the pattern.
        code = "80502"
        acct = self._persist_account(f"{code} - ByPattern")
        # Guard the premise: the lookups that precede the name-pattern branch
        # must genuinely find nothing for this code.
        self.assertFalse(
            frappe.db.exists("Account", {"company": self.company, "account_number": code}),
            "Premise broken: account_number lookup would short-circuit the name-pattern branch",
        )
        if frappe.db.has_column("Account", "eboekhouden_grootboek_nummer"):
            self.assertFalse(
                frappe.db.exists(
                    "Account", {"company": self.company, "eboekhouden_grootboek_nummer": code}
                ),
                "Premise broken: grootboek lookup would short-circuit the name-pattern branch",
            )
        mapper = self._mapper()
        self.assertEqual(mapper._get_account_by_code(code), acct)

    def test_unknown_code_returns_none_and_caches(self):
        mapper = self._mapper()
        self.assertIsNone(mapper._get_account_by_code("ZZZ-NO-SUCH"))
        # cached on second call
        self.assertIn("ZZZ-NO-SUCH", mapper._account_cache)
        self.assertIsNone(mapper._get_account_by_code("ZZZ-NO-SUCH"))

    def test_long_digit_ledger_id_unmapped_returns_none(self):
        # > 5 digits and all-digit => treated as ledger ID; unknown ledger => None
        mapper = self._mapper()
        self.assertIsNone(mapper._get_account_by_code("999999999"))

    def test_cache_hit_returns_same(self):
        acct = self._persist_account("Tegenrek Cache", account_number="80503")
        mapper = self._mapper()
        # Cache starts empty for this code.
        self.assertNotIn("80503", mapper._account_cache)
        first = mapper._get_account_by_code("80503")
        self.assertEqual(first, acct)
        # The lookup must have populated the cache (prod caches the resolved value).
        self.assertIn("80503", mapper._account_cache)
        self.assertEqual(mapper._account_cache["80503"], acct)
        # Second call serves from cache and returns the identical value.
        self.assertEqual(mapper._get_account_by_code("80503"), first)


if __name__ == "__main__":
    unittest.main()
