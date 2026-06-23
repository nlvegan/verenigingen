"""
Coverage sweep for eboekhouden_ledger_mapping.py

Target: verenigingen/e_boekhouden/utils/eboekhouden_ledger_mapping.py

Testable surface (REAL DB, no live eBoekhouden HTTP):
- _find_erpnext_account_by_code  -- pure DB lookup by account_number
- get_account_code_from_ledger_id -- pure DB lookup in the mapping table
- quick_create_mapping_from_logs  -- parses Error Log rows and creates temp mappings
- create_ledger_mapping_doctype   -- idempotent DocType bootstrap (DocType already
                                     exists on veg11, so we exercise the early-return)

OUT OF SCOPE (API-REQUIRED, enforcer bans mocking the HTTP/Frappe boundary):
- fetch_and_create_ledger_mapping -- requires a live eBoekhouden session token +
  paginated /v1/ledger HTTP fetch. Its DB-write half (create/update/auto-link) is
  the same code path quick_create_mapping_from_logs and the auto-link helper exercise.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_ledger_mapping_coverage
"""

import frappe

from verenigingen.e_boekhouden.utils.eboekhouden_ledger_mapping import (
    _find_erpnext_account_by_code,
    create_ledger_mapping_doctype,
    get_account_code_from_ledger_id,
    quick_create_mapping_from_logs,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFindErpnextAccountByCode(EnhancedTestCase):
    """_find_erpnext_account_by_code matches Account.account_number to a ledger code."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Reuse the canonical EUR test company (get-or-create with a full ERPNext
        # Chart of Accounts). Creating a fresh company here ran ERPNext's company
        # setup wizard, which is environmentally fragile on this bench (it choked
        # on a stale 'Cash - <abbr>' default-account reference left by another
        # company). We only need a company that owns Accounts, so borrow the
        # shared one.
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        cls.company = get_eur_test_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    def _persist_account(self, acct_name, account_number, *, disabled=0):
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Asset", "is_group": 1}, "name"
        )
        full = f"{acct_name} - {self.abbr}"
        if frappe.db.exists("Account", full):
            if disabled:
                frappe.db.set_value("Account", full, "disabled", disabled)
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = "Asset"
        doc.account_number = account_number
        doc.disabled = disabled
        doc.insert(ignore_permissions=True)
        return doc.name

    def test_empty_code_returns_none(self):
        # Guard clause: falsy ledger_code short-circuits before any DB hit.
        self.assertIsNone(_find_erpnext_account_by_code(""))
        self.assertIsNone(_find_erpnext_account_by_code(None))

    def test_resolves_by_account_number_with_company(self):
        # Sentinel account_number unlikely to collide with the shared CoA.
        acct = self._persist_account("Ledger Map ByNumber", "EBK-TEST-91110")
        with self.assertNoErrorLog():
            found = _find_erpnext_account_by_code("EBK-TEST-91110", self.company)
        self.assertEqual(found, acct)

    def test_unknown_code_returns_none(self):
        with self.assertNoErrorLog():
            self.assertIsNone(_find_erpnext_account_by_code("NO-SUCH-9999", self.company))

    def test_disabled_account_is_excluded(self):
        # The lookup filters disabled=0; a disabled account must not be returned.
        self._persist_account("Ledger Map Disabled", "EBK-TEST-91190", disabled=1)
        with self.assertNoErrorLog():
            self.assertIsNone(_find_erpnext_account_by_code("EBK-TEST-91190", self.company))

    def test_company_filter_scopes_result(self):
        # With no company filter the lookup still resolves the (uniquely-numbered)
        # account we just created (company is an optional filter).
        acct = self._persist_account("Ledger Map NoCompanyFilter", "EBK-TEST-91120")
        with self.assertNoErrorLog():
            found = _find_erpnext_account_by_code("EBK-TEST-91120")
        self.assertEqual(found, acct)


class TestGetAccountCodeFromLedgerId(EnhancedTestCase):
    """get_account_code_from_ledger_id reads ledger_code from the mapping table."""

    def _make_mapping(self, ledger_id, ledger_code, ledger_name="Test Ledger"):
        if frappe.db.exists("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}):
            frappe.delete_doc(
                "E-Boekhouden Ledger Mapping",
                frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "name"),
                ignore_permissions=True,
                force=True,
            )
        doc = frappe.new_doc("E-Boekhouden Ledger Mapping")
        doc.ledger_id = ledger_id
        doc.ledger_code = ledger_code
        doc.ledger_name = ledger_name
        doc.insert(ignore_permissions=True)
        return doc

    def test_returns_code_for_known_ledger(self):
        self._make_mapping("550001", "4200")
        self.assertEqual(get_account_code_from_ledger_id("550001"), "4200")

    def test_accepts_int_ledger_id(self):
        # Function str()-normalizes the input; an int must resolve the same row.
        self._make_mapping("550002", "4300")
        self.assertEqual(get_account_code_from_ledger_id(550002), "4300")

    def test_missing_ledger_returns_none(self):
        self.assertIsNone(get_account_code_from_ledger_id("999000111"))

    def test_falsy_ledger_id_returns_none(self):
        self.assertIsNone(get_account_code_from_ledger_id(None))
        self.assertIsNone(get_account_code_from_ledger_id(""))
        self.assertIsNone(get_account_code_from_ledger_id(0))


class TestQuickCreateMappingFromLogs(EnhancedTestCase):
    """
    quick_create_mapping_from_logs scrapes Error Log rows of the form
    'Account code <id> not found in company Ned Ver Vegan' and creates temporary
    E-Boekhouden Ledger Mapping rows for each new numeric id.
    """

    def _insert_error_log(self, ledger_id):
        # The SQL parses the id out of the message text; the title is irrelevant.
        # Mark our own fixture rows as expected so the tearDown Error-Log guard
        # does not flag the bait we deliberately planted.
        self.expectErrorLog("not found in company Ned Ver Vegan")
        doc = frappe.new_doc("Error Log")
        doc.method = "Account code error"
        doc.error = f"Account code {ledger_id} not found in company Ned Ver Vegan"
        doc.insert(ignore_permissions=True)
        # The production SQL filters creation > '2025-01-01'; rows insert with now().
        return doc.name

    def _cleanup_mapping(self, ledger_id):
        existing = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "name"
        )
        if existing:
            frappe.delete_doc(
                "E-Boekhouden Ledger Mapping", existing, ignore_permissions=True, force=True
            )

    def _make_ledger_mapping(self, ledger_id, ledger_code, ledger_name):
        existing = frappe.new_doc("E-Boekhouden Ledger Mapping")
        existing.ledger_id = ledger_id
        existing.ledger_code = ledger_code
        existing.ledger_name = ledger_name
        existing.insert(ignore_permissions=True)
        return existing.name

    def test_creates_temp_mapping_from_log(self):
        ledger_id = "7654321"
        self._cleanup_mapping(ledger_id)
        self._insert_error_log(ledger_id)

        result = quick_create_mapping_from_logs()

        self.assertTrue(result["success"])
        # A mapping row must now exist for the scraped id with the TEMP- code.
        row = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping",
            {"ledger_id": ledger_id},
            ["ledger_code", "ledger_name"],
            as_dict=True,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.ledger_code, f"TEMP-{ledger_id}")
        self.assertEqual(row.ledger_name, f"Unmapped Ledger {ledger_id}")

    def test_message_interpolates_created_count(self):
        # REGRESSION GUARD for an f-string defect: the success message used
        # "Created {created} temporary mappings." WITHOUT an f-prefix, so the
        # literal text "{created}" leaked to the caller instead of the count.
        ledger_id = "8765432"
        self._cleanup_mapping(ledger_id)
        self._insert_error_log(ledger_id)

        result = quick_create_mapping_from_logs()

        self.assertTrue(result["success"])
        self.assertNotIn("{created}", result["message"])
        # The created count must appear as a real integer in the message.
        self.assertIn(str(result["created"]), result["message"])

    def test_skips_already_mapped_ledger(self):
        # If a mapping already exists, the function must NOT create a duplicate.
        ledger_id = "9876543"
        self._cleanup_mapping(ledger_id)
        self._make_ledger_mapping(ledger_id, "REAL-CODE", "Already mapped")
        self._insert_error_log(ledger_id)

        quick_create_mapping_from_logs()

        # Code must remain the real code, NOT be overwritten with TEMP-.
        self.assertEqual(
            frappe.db.get_value("E-Boekhouden Ledger Mapping", {"ledger_id": ledger_id}, "ledger_code"),
            "REAL-CODE",
        )


class TestCreateLedgerMappingDoctype(EnhancedTestCase):
    """create_ledger_mapping_doctype is idempotent: it returns early if it exists."""

    def test_already_exists_returns_early(self):
        # The DocType is shipped with the app, so this must hit the early-return
        # branch and never attempt a re-create.
        self.assertTrue(frappe.db.exists("DocType", "E-Boekhouden Ledger Mapping"))
        with self.assertNoErrorLog():
            result = create_ledger_mapping_doctype()
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "DocType already exists")
