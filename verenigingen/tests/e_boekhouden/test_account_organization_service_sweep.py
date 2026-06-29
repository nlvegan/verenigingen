"""
Coverage sweep for the DB-touching surface of AccountOrganizationService.

Target: verenigingen/e_boekhouden/services/account_organization_service.py

The pure range-parsing helpers (_parse_account_ranges / _extract_* / _is_in_ranges)
are already exercised by test_account_services.py. This module covers the
*structure-mutating* methods that re-parent a Dutch-style Chart of Accounts:

- organize_balance_sheet_accounts()  (full orchestration + the per-leaf moves)
- _ensure_account_group()            (find / reparent / create branches)
- _get_activa_root() / _get_passiva_root()
- _create_group_account()            (success + missing-parent failure)
- _name_filter()

These run against a DEDICATED throwaway company with a hand-built Dutch chart
(an Activa root numbered "0", a Passiva root numbered "3", and a handful of
numbered leaf accounts). organize_balance_sheet_accounts() calls
frappe.db.commit(), so we never run it against the shared veg11 chart -- only
against this isolated company whose mutations are harmless.

Assertions check the *final* parent of each leaf (deterministic and idempotent
across re-runs) rather than the transient "updated" diff. Each organize test
first resets the leaves back under the roots so the move-branches always execute.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_account_organization_service_sweep
"""

import frappe

from verenigingen.e_boekhouden.services.account_organization_service import AccountOrganizationService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_COMPANY = "TEST AcctOrg Sweep Co"
_ABBR = "TAOSC"

# (account_number, account_name, root_type) for the numbered leaf accounts.
_ASSET_LEAVES = [
    ("1300", "Debiteuren", "Asset"),  # receivable range 1300-1399 -> Vorderingen
    ("1000", "Triodos Bank", "Asset"),  # financial range 1000-1299 -> Financial Accounts
    ("1480", "Vooruitbetaalde kosten", "Asset"),  # explicit prepaid -> Overlopende activa
    ("1530", "BTW te vorderen", "Asset"),  # tax receivable -> Belastingen (Activa)
]
_LIABILITY_LEAVES = [
    ("1600", "Crediteuren", "Liability"),  # creditor range 1600-1699 -> Schulden
    ("1500", "BTW af te dragen", "Liability"),  # 15xx (not 1530) -> Belastingen (Passiva)
]


class _AcctOrgBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._ensure_company()
        cls.asset_root = cls._root_account("Asset")
        cls.liability_root = cls._root_account("Liability")
        # Dutch-style group roots the service looks up by account_number.
        cls.activa_group = cls._ensure_account("0", "Activa", cls.asset_root, "Asset", is_group=1)
        cls.passiva_group = cls._ensure_account("3", "Passiva", cls.liability_root, "Liability", is_group=1)
        for number, name, root_type in _ASSET_LEAVES:
            cls._ensure_account(number, name, cls.activa_group, root_type, is_group=0)
        for number, name, root_type in _LIABILITY_LEAVES:
            cls._ensure_account(number, name, cls.passiva_group, root_type, is_group=0)
        frappe.db.commit()

    # ---- fixture builders -------------------------------------------------
    @classmethod
    def _ensure_company(cls):
        if not frappe.db.exists("Company", _COMPANY):
            doc = frappe.new_doc("Company")
            doc.company_name = _COMPANY
            doc.abbr = _ABBR
            doc.default_currency = "EUR"
            doc.country = "Netherlands"
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
        return _COMPANY

    @classmethod
    def _root_account(cls, root_type):
        for a in frappe.get_all(
            "Account",
            filters={"company": _COMPANY, "root_type": root_type, "is_group": 1},
            fields=["name", "parent_account"],
        ):
            if not a.parent_account:
                return a.name
        raise RuntimeError(f"No {root_type} root account for {_COMPANY}")

    @classmethod
    def _ensure_account(cls, number, account_name, parent, root_type, is_group):
        existing = frappe.db.get_value(
            "Account", {"company": _COMPANY, "account_number": number, "is_group": is_group}, "name"
        )
        if existing:
            return existing
        acc = frappe.new_doc("Account")
        acc.account_name = account_name
        acc.account_number = number
        acc.company = _COMPANY
        acc.parent_account = parent
        acc.root_type = root_type
        acc.is_group = is_group
        acc.insert(ignore_permissions=True)
        return acc.name

    # ---- helpers ----------------------------------------------------------
    def _service(self):
        # Transient settings -> the service falls back to default group names
        # and default account ranges, which is what our fixture is built for.
        settings = frappe.new_doc("E-Boekhouden Settings")
        return AccountOrganizationService(self.company, settings=settings)

    def _leaf(self, number, is_group=0):
        return frappe.db.get_value(
            "Account", {"company": self.company, "account_number": number, "is_group": is_group}, "name"
        )

    def _parent(self, number, is_group=0):
        return frappe.db.get_value("Account", self._leaf(number, is_group), "parent_account")

    def _reset_leaves(self):
        """Put every numbered leaf back under its root group so the move-branches run."""
        for number, _name, _rt in _ASSET_LEAVES:
            frappe.db.set_value("Account", self._leaf(number), "parent_account", self.activa_group)
        for number, _name, _rt in _LIABILITY_LEAVES:
            frappe.db.set_value("Account", self._leaf(number), "parent_account", self.passiva_group)


class TestOrganizeBalanceSheetAccounts(_AcctOrgBase):
    def test_full_organize_moves_each_leaf_to_correct_group(self):
        self._reset_leaves()
        svc = self._service()
        results = svc.organize_balance_sheet_accounts()

        # No failures, and the four mandatory groups were ensured/created.
        self.assertEqual(results["errors"], [])
        created_blob = " | ".join(results["created_groups"])
        for marker in ("Vorderingen:", "Financial Accounts:", "Overlopende activa:", "Schulden:"):
            self.assertIn(marker, created_blob)

        # Resolve the (now-existing) target groups by the same criteria the
        # service uses, then assert every leaf landed in the right group.
        vorderingen = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_number": "4", "is_group": 1, "root_type": "Asset"},
            "name",
        )
        financial = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Financiële rekeningen%"],
                "is_group": 1,
                "root_type": "Asset",
            },
            "name",
        )
        overlopende = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Overlopende activa%"],
                "is_group": 1,
                "root_type": "Asset",
            },
            "name",
        )
        schulden = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Schulden%"],
                "is_group": 1,
                "root_type": "Liability",
            },
            "name",
        )
        tax_payable = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Belastingen%"],
                "is_group": 1,
                "root_type": "Liability",
            },
            "name",
        )
        tax_receivable = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Belastingen%"],
                "is_group": 1,
                "root_type": "Asset",
            },
            "name",
        )

        self.assertTrue(all([vorderingen, financial, overlopende, schulden, tax_payable, tax_receivable]))

        self.assertEqual(self._parent("1300"), vorderingen)
        self.assertEqual(self._parent("1000"), financial)
        self.assertEqual(self._parent("1480"), overlopende)
        self.assertEqual(self._parent("1530"), tax_receivable)
        self.assertEqual(self._parent("1600"), schulden)
        self.assertEqual(self._parent("1500"), tax_payable)

        # The mutating run records the moves it performed this pass.
        self.assertIn("1300 → Vorderingen", results["updated"])
        self.assertIn("1600 → Schulden", results["updated"])

    def test_tax_groups_attach_under_correct_roots(self):
        self._reset_leaves()
        self._service().organize_balance_sheet_accounts()

        tax_payable = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Belastingen%"],
                "is_group": 1,
                "root_type": "Liability",
            },
            "name",
        )
        tax_receivable = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_name": ["like", "%Belastingen%"],
                "is_group": 1,
                "root_type": "Asset",
            },
            "name",
        )
        # Payable tax group hangs off Passiva, receivable tax group off Activa.
        self.assertEqual(frappe.db.get_value("Account", tax_payable, "parent_account"), self.passiva_group)
        self.assertEqual(frappe.db.get_value("Account", tax_receivable, "parent_account"), self.activa_group)
        # 1530 must NOT be swept into the payable group with the other 15xx rows.
        self.assertEqual(self._parent("1530"), tax_receivable)


class TestRootLookups(_AcctOrgBase):
    def test_get_activa_root(self):
        self.assertEqual(self._service()._get_activa_root(), self.activa_group)

    def test_get_passiva_root(self):
        self.assertEqual(self._service()._get_passiva_root(), self.passiva_group)


class TestCreateGroupAccount(_AcctOrgBase):
    def test_missing_parent_returns_none(self):
        # No parent -> the method bails out and returns None (logged, not raised).
        self.assertIsNone(self._service()._create_group_account("Orphan Group", "Asset", "97", None))

    def test_creates_group_under_parent(self):
        svc = self._service()
        name = svc._create_group_account("Sweep Temp Group", "Asset", "96", self.activa_group)
        self.assertTrue(name)
        self.assertEqual(frappe.db.get_value("Account", name, "is_group"), 1)
        self.assertEqual(frappe.db.get_value("Account", name, "parent_account"), self.activa_group)
        self.assertEqual(frappe.db.get_value("Account", name, "root_type"), "Asset")
        # not committed -> rolled back by the test harness


class TestEnsureAccountGroup(_AcctOrgBase):
    def _make_misplaced_asset_group(self):
        """Create an Asset group (account_number 95) hanging off the wrong parent."""
        existing = frappe.db.get_value(
            "Account", {"company": self.company, "account_number": "95", "is_group": 1}, "name"
        )
        if existing:
            frappe.db.set_value("Account", existing, "parent_account", self.asset_root)
            return existing
        acc = frappe.new_doc("Account")
        acc.account_name = "Misplaced Group"
        acc.account_number = "95"
        acc.company = self.company
        acc.parent_account = self.asset_root  # wrong: should be under activa_group ("0")
        acc.root_type = "Asset"
        acc.is_group = 1
        acc.insert(ignore_permissions=True)
        return acc.name

    def _filter(self):
        return {"company": self.company, "account_number": "95", "is_group": 1, "root_type": "Asset"}

    def test_reparents_existing_group_when_enabled(self):
        name = self._make_misplaced_asset_group()
        self.assertNotEqual(frappe.db.get_value("Account", name, "parent_account"), self.activa_group)
        svc = self._service()
        returned = svc._ensure_account_group(
            self._filter(), "Misplaced Group", "Asset", svc._get_activa_root, reparent=True
        )
        self.assertEqual(returned, name)
        self.assertEqual(frappe.db.get_value("Account", name, "parent_account"), self.activa_group)

    def test_no_reparent_leaves_parent_untouched(self):
        name = self._make_misplaced_asset_group()
        svc = self._service()
        returned = svc._ensure_account_group(
            self._filter(), "Misplaced Group", "Asset", svc._get_activa_root, reparent=False
        )
        self.assertEqual(returned, name)
        # reparent disabled -> stays under the wrong (asset root) parent.
        self.assertEqual(frappe.db.get_value("Account", name, "parent_account"), self.asset_root)

    def test_creates_when_missing(self):
        # A filter that matches nothing -> the create branch runs.
        svc = self._service()
        missing_filter = {
            "company": self.company,
            "account_number": "93",
            "is_group": 1,
            "root_type": "Asset",
        }
        name = svc._ensure_account_group(
            missing_filter, "Brand New Group", "Asset", svc._get_activa_root, account_number="93"
        )
        self.assertTrue(name)
        self.assertEqual(frappe.db.get_value("Account", name, "parent_account"), self.activa_group)
        self.assertEqual(frappe.db.get_value("Account", name, "account_number"), "93")


class TestNameFilter(_AcctOrgBase):
    def test_name_filter_strips_suffix_and_builds_like(self):
        flt = self._service()._name_filter("Vorderingen - Receivables", "Asset")
        self.assertEqual(flt["account_name"], ["like", "%Vorderingen%"])
        self.assertEqual(flt["root_type"], "Asset")
        self.assertEqual(flt["is_group"], 1)
        self.assertEqual(flt["company"], self.company)
