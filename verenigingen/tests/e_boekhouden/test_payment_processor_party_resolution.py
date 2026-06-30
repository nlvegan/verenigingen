"""
Coverage sweep #3 for ``e_boekhouden/utils/processors/payment_processor.py``
(:class:`PaymentProcessor`).

The two sibling modules cover:
* ``test_payment_processor_coverage.py`` -- pure decision functions
  (``can_process``, ``get_payment_type``, gateway detect/adjust,
  ``_extract_bank_name_from_account``).
* ``test_payment_processor_sweep.py``    -- the money-transfer happy path and the
  link / update-party helpers with auto-create DISABLED.

This module targets the largest remaining uncovered cluster: the PARTY-RESOLUTION
block inside ``_create_bank_transaction_for_journal_entry`` (the relation-id and
name-matching branches, auto-create ON, bank-internal supplier resolution), the
existing-Bank-Transaction handling arms (overwrite / generic-party backfill /
already-reconciled), ``_update_bank_transaction_party`` with auto-create ON, the
``_process_money_transfer`` Receivable-without-party guard and no-valid-rows
guard, and the ``_adjust_payment_gateway_amount`` short-circuit branches.

Everything is REAL: a dedicated EUR company + chart of accounts (reused from the
sweep base), real Bank / Bank Account, real ``E-Boekhouden Ledger Mapping`` rows,
real ``Supplier``/``Customer`` masters and the real ``bank_transaction_creator``
service. Assertions check the concrete party_type/party written onto the Bank
Transaction, the debit/credit direction of produced Journal Entries, and that the
correct error is raised on the guard paths.

Run with::

    cd /home/frappeuser/frappe-bench && bench --site veg11.veganisme.org \\
        run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_payment_processor_party_resolution
"""

import frappe
from frappe.utils import flt, nowdate

from verenigingen.e_boekhouden.utils.processors.payment_processor import PaymentProcessor
from verenigingen.tests.e_boekhouden.test_payment_processor_sweep import (
    BANK_LEDGER,
    _PayProcBase,
)

# Dedicated ledger ids (74xxxxx range, unique to this module).
RECEIVABLE_LEDGER = "7400010"
PAYABLE_LEDGER = "7400011"


class _PartyBase(_PayProcBase):
    """Extend the sweep bootstrap with Receivable + Payable accounts/mappings."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.receivable = cls._make_account("EBPS Debtors", "Receivable", "Asset")
        cls.payable = cls._make_account("EBPS Creditors", "Payable", "Liability")
        cls._make_ledger_map(RECEIVABLE_LEDGER, cls.receivable, "EBPS Debtors")
        cls._make_ledger_map(PAYABLE_LEDGER, cls.payable, "EBPS Creditors")
        frappe.db.commit()

    # ---- shared helpers ----

    def _make_submitted_je(self, mut_id, amount=55.00):
        """A real submitted JE with a bank debit + income credit leg."""
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        je.voucher_type = "Journal Entry"
        je.eboekhouden_mutation_nr = str(mut_id)
        je.cheque_no = f"EB-{mut_id}"
        je.cheque_date = nowdate()
        je.append(
            "accounts",
            {
                "account": self.bank,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
                "cost_center": self.cost_center,
            },
        )
        je.append(
            "accounts",
            {
                "account": self.income,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
                "cost_center": self.cost_center,
            },
        )
        je.insert(ignore_permissions=True)
        je.submit()
        return je

    def _make_supplier(self, name):
        if frappe.db.exists("Supplier", name):
            return name
        sup = frappe.new_doc("Supplier")
        sup.supplier_name = name
        sup.supplier_group = frappe.db.get_value(
            "Supplier Group", {"is_group": 0}, "name", order_by="name"
        )
        sup.insert(ignore_permissions=True)
        return sup.name

    def _set_auto_create(self, value):
        saved = frappe.db.get_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions"
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions", value
        )
        self.addCleanup(
            frappe.db.set_single_value,
            "E-Boekhouden Settings",
            "auto_create_parties_from_bank_transactions",
            saved,
        )


# ---------------------------------------------------------------------------
# _create_bank_transaction_for_journal_entry  -- party resolution block
# ---------------------------------------------------------------------------
class TestCreateBTPartyResolution(_PartyBase):
    def _create_bt(self, processor, mut_id, party_info, bank_account=None):
        je = self._make_submitted_je(mut_id)
        return processor._create_bank_transaction_for_journal_entry(
            {"id": mut_id, "type": 5, "description": "party resolution test"},
            je,
            self.bank,
            bank_account or self.bank_account,
            party_info,
        )

    def test_party_resolved_by_name_auto_create_off(self):
        """A party_name that matches an existing Supplier is written onto the BT (auto-create off)."""
        self._set_auto_create(0)
        supplier = self._make_supplier("PPX NameMatch Supplier")
        p = self._processor()
        bt_name = self._create_bt(p, 7410001, {"party_type": "Supplier", "party_name": supplier})
        self.assertTrue(bt_name)
        bt = frappe.db.get_value(
            "Bank Transaction", bt_name, ["party_type", "party"], as_dict=True
        )
        self.assertEqual(bt.party_type, "Supplier")
        self.assertEqual(bt.party, supplier)

    def test_party_name_not_found_auto_create_off(self):
        """A party_name with no matching Supplier (auto-create off) -> BT without party."""
        self._set_auto_create(0)
        p = self._processor()
        bt_name = self._create_bt(
            p, 7410002, {"party_type": "Supplier", "party_name": "PPX Ghost Supplier 9931"}
        )
        self.assertTrue(bt_name)
        self.assertFalse(frappe.db.get_value("Bank Transaction", bt_name, "party"))
        self.assertTrue(
            any("auto-create disabled" in m for m in p.get_debug_info()),
            msg="missing-party-with-auto-create-off branch must be logged",
        )

    def test_party_auto_create_matches_existing(self):
        """Auto-create ON but the Supplier already exists -> matched, not duplicated."""
        self._set_auto_create(1)
        supplier = self._make_supplier("PPX AutoMatch Supplier")
        before = frappe.db.count("Supplier")
        p = self._processor()
        bt_name = self._create_bt(p, 7410003, {"party_type": "Supplier", "party_name": supplier})
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt_name, "party"), supplier)
        self.assertEqual(frappe.db.count("Supplier"), before, "must not create a duplicate Supplier")

    def test_party_auto_create_creates_new(self):
        """Auto-create ON with an unknown party_name -> a new Supplier is created and linked."""
        self._set_auto_create(1)
        new_name = "PPX FreshlyCreated Supplier 731"
        self.assertFalse(frappe.db.exists("Supplier", {"supplier_name": new_name}))
        p = self._processor()
        bt_name = self._create_bt(p, 7410004, {"party_type": "Supplier", "party_name": new_name})
        party = frappe.db.get_value("Bank Transaction", bt_name, "party")
        self.assertTrue(party, "auto-create should have produced a party")
        self.assertTrue(frappe.db.exists("Supplier", {"supplier_name": new_name}))
        self.assertTrue(any("Created new Supplier" in m for m in p.get_debug_info()))

    def test_relation_id_lookup_error_falls_through_to_name(self):
        """relation_id lookup hits a missing column -> caught, then name matching succeeds.

        Customer/Supplier carry no ``eboekhouden_relation_id`` column on this site,
        so the relation-id ``frappe.db.get_value`` raises; the code must catch it,
        log the error, and fall through to (successful) name matching.
        """
        self._set_auto_create(0)
        supplier = self._make_supplier("PPX RelationFallback Supplier")
        p = self._processor()
        bt_name = self._create_bt(
            p,
            7410005,
            {"party_type": "Supplier", "party_name": supplier, "relation_id": "EBPS-REL-1"},
        )
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt_name, "party"), supplier)
        self.assertTrue(
            any("Relation ID lookup error" in m for m in p.get_debug_info())
            or any("Trying party name matching" in m for m in p.get_debug_info()),
            msg="relation-id failure must be logged before falling through to name match",
        )

    def test_bank_internal_uses_bank_as_supplier(self):
        """is_bank_internal + a bank account that parses to a real Supplier -> bank is the party."""
        # self.bank_account name is "EBPS Main - EBPS Test Bank"; part[1] = "EBPS Test Bank".
        bank_supplier = self._make_supplier("EBPS Test Bank")
        p = self._processor()
        bt_name = self._create_bt(
            p,
            7410006,
            {"is_bank_internal": True, "party_type": "Supplier", "party_name": None},
        )
        bt = frappe.db.get_value(
            "Bank Transaction", bt_name, ["party_type", "party"], as_dict=True
        )
        self.assertEqual(bt.party_type, "Supplier")
        self.assertEqual(bt.party, bank_supplier)
        self.assertTrue(any("Bank internal transaction" in m for m in p.get_debug_info()))

    def test_bank_internal_without_supplier_has_no_party(self):
        """is_bank_internal but the parsed bank name is not a Supplier -> BT without party."""
        # Deliberately do NOT create "EBPS Test Bank" as a Supplier in this test.
        self.assertFalse(frappe.db.exists("Supplier", {"supplier_name": "EBPS Test Bank"}))
        p = self._processor()
        bt_name = self._create_bt(
            p,
            7410007,
            {"is_bank_internal": True, "party_type": "Supplier", "party_name": None},
        )
        self.assertTrue(bt_name)
        self.assertFalse(frappe.db.get_value("Bank Transaction", bt_name, "party"))


# ---------------------------------------------------------------------------
# _create_bank_transaction_for_journal_entry  -- existing-BT handling arms
# ---------------------------------------------------------------------------
class TestExistingBankTransactionArms(_PartyBase):
    def _preseed_bt(self, ref, amount=20.0, status="Unreconciled", party_type=None, party=None):
        from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
            get_bank_transaction_creator,
        )

        creator = get_bank_transaction_creator()
        return creator.create_from_dict(
            transaction_data={
                "date": nowdate(),
                "amount": amount,
                "currency": "EUR",
                "description": "preseed",
                "reference_number": ref,
                "party_type": party_type,
                "party": party,
            },
            bank_account=self.bank_account,
            company=self.company,
            source_type="Coverage Pre-Seed",
        )

    def _make_submitted_je(self, mut_id, amount=20.0):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = nowdate()
        je.voucher_type = "Journal Entry"
        je.eboekhouden_mutation_nr = str(mut_id)
        je.cheque_no = f"EB-{mut_id}"
        je.cheque_date = nowdate()
        je.append(
            "accounts",
            {"account": self.bank, "debit_in_account_currency": amount, "cost_center": self.cost_center},
        )
        je.append(
            "accounts",
            {"account": self.income, "credit_in_account_currency": amount, "cost_center": self.cost_center},
        )
        je.insert(ignore_permissions=True)
        je.submit()
        return je

    def _make_supplier(self, name):
        if frappe.db.exists("Supplier", name):
            return name
        sup = frappe.new_doc("Supplier")
        sup.supplier_name = name
        sup.supplier_group = frappe.db.get_value(
            "Supplier Group", {"is_group": 0}, "name", order_by="name"
        )
        sup.insert(ignore_permissions=True)
        return sup.name

    def test_overwrite_mode_deletes_and_recreates_with_party(self):
        """overwrite_existing=True + existing BT + party_info -> old BT deleted, new created with party."""
        ref = "EB-7420001"
        old_bt = self._preseed_bt(ref, amount=20.0)
        self.assertTrue(old_bt)
        # Match the part[1] of the bank account name so the (bank-internal) branch
        # isn't needed; use a plain name party instead.
        saved = frappe.db.get_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions"
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions", 0
        )
        self.addCleanup(
            frappe.db.set_single_value,
            "E-Boekhouden Settings",
            "auto_create_parties_from_bank_transactions",
            saved,
        )
        supplier = self._make_supplier("PPX Overwrite Supplier")

        p = PaymentProcessor(self.company, cost_center=self.cost_center, overwrite_existing=True)
        je = self._make_submitted_je(7420001, amount=20.0)
        new_bt = p._create_bank_transaction_for_journal_entry(
            {"id": 7420001, "type": 5, "description": "overwrite"},
            je,
            self.bank,
            self.bank_account,
            {"party_type": "Supplier", "party_name": supplier},
        )
        self.assertTrue(new_bt)
        # Exactly one BT with this reference, and it carries the new party.
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": ref}), 1)
        self.assertEqual(frappe.db.get_value("Bank Transaction", new_bt, "party"), supplier)
        self.assertTrue(any("Overwrite mode: Deleting" in m for m in p.get_debug_info()))

    def test_update_mode_backfills_generic_party(self):
        """Update mode: existing BT with a generic 'Bank Transfer' party gets backfilled."""
        ref = "EB-7420002"
        saved = frappe.db.get_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions"
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions", 0
        )
        self.addCleanup(
            frappe.db.set_single_value,
            "E-Boekhouden Settings",
            "auto_create_parties_from_bank_transactions",
            saved,
        )
        # Generic supplier so is_generic_party ("Bank Transfer" in party) is True.
        generic = self._make_supplier("PPX Bank Transfer Generic")
        real = self._make_supplier("PPX Real Backfill Supplier")
        self._preseed_bt(ref, amount=20.0, party_type="Supplier", party=generic)

        p = self._processor()
        je = self._make_submitted_je(7420002, amount=20.0)
        bt_name = p._create_bank_transaction_for_journal_entry(
            {"id": 7420002, "type": 5, "description": "update generic"},
            je,
            self.bank,
            self.bank_account,
            {"party_type": "Supplier", "party_name": real},
        )
        self.assertEqual(bt_name, self._ref_to_name(ref))
        self.assertEqual(frappe.db.get_value("Bank Transaction", bt_name, "party"), real)

    def test_existing_reconciled_bt_is_left_alone(self):
        """An already-reconciled existing BT is returned without re-linking."""
        ref = "EB-7420003"
        bt = self._preseed_bt(ref, amount=20.0)
        frappe.db.set_value("Bank Transaction", bt, "status", "Reconciled")
        p = self._processor()
        je = self._make_submitted_je(7420003, amount=20.0)
        result = p._create_bank_transaction_for_journal_entry(
            {"id": 7420003, "type": 5, "description": "already reconciled"},
            je,
            self.bank,
            self.bank_account,
            None,
        )
        self.assertEqual(result, bt)
        self.assertTrue(any("already reconciled" in m for m in p.get_debug_info()))

    @staticmethod
    def _ref_to_name(ref):
        return frappe.db.get_value("Bank Transaction", {"reference_number": ref}, "name")


# ---------------------------------------------------------------------------
# _update_bank_transaction_party  -- auto-create ON (sweep covers auto-create off)
# ---------------------------------------------------------------------------
class TestUpdateBTPartyAutoCreate(_PartyBase):
    def _make_draft_bt(self, ref):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = nowdate()
        bt.bank_account = self.bank_account
        bt.company = self.company
        bt.deposit = 10.0
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = ref
        bt.description = "party autocreate test"
        bt.status = "Unreconciled"
        bt.unallocated_amount = 10.0
        bt.allocated_amount = 0
        bt.insert(ignore_permissions=True)
        return bt

    def test_auto_create_on_creates_party_on_existing_bt(self):
        saved = frappe.db.get_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions"
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "auto_create_parties_from_bank_transactions", 1
        )
        self.addCleanup(
            frappe.db.set_single_value,
            "E-Boekhouden Settings",
            "auto_create_parties_from_bank_transactions",
            saved,
        )
        bt = self._make_draft_bt("EB-PARTY-7430001")
        new_name = "PPX Update AutoCreate Supplier 742"
        self.assertFalse(frappe.db.exists("Supplier", {"supplier_name": new_name}))
        p = self._processor()
        p._update_bank_transaction_party(
            bt.name, {"party_type": "Supplier", "party_name": new_name}
        )
        bt.reload()
        self.assertEqual(bt.party_type, "Supplier")
        self.assertTrue(bt.party)
        self.assertTrue(frappe.db.exists("Supplier", {"supplier_name": new_name}))


# ---------------------------------------------------------------------------
# _process_money_transfer  -- guard branches
# ---------------------------------------------------------------------------
class TestMoneyTransferGuards(_PartyBase):
    def test_receivable_row_without_party_raises(self):
        """A row mapping to a Receivable account with no resolvable party fails fast.

        For audit integrity, a Receivable/Payable JE line must carry a party. When
        party extraction yields nothing, ``_process_money_transfer`` must raise
        rather than book an unparteed receivable.
        """
        p = self._processor()
        mut = {
            "id": 7440001,
            "type": 5,
            "amount": 30.00,
            "ledgerId": int(BANK_LEDGER),
            "date": nowdate(),
            # Empty description => the party extractor returns None (no name, no
            # relation_id), so the Receivable line ends up without a party and the
            # audit guard must fire. A non-empty description would be matched /
            # auto-created into a Customer, masking the guard.
            "description": "",
            "rows": [{"amount": 30.00, "ledgerId": RECEIVABLE_LEDGER}],
        }
        # The outer handler in _process_money_transfer logs the failure before re-raising.
        self.expectErrorLog("Money Transfer Journal Entry Error")
        with self.assertRaises(ValueError) as ctx:
            p.process(mut)
        self.assertIn("requires a", str(ctx.exception))
        self.assertIn("party assignment", str(ctx.exception))

    def test_no_valid_rows_raises(self):
        """A Type 5 mutation whose rows are all near-zero produces no valid entries -> raises."""
        p = self._processor()
        mut = {
            "id": 7440002,
            "type": 5,
            "amount": 0,
            "ledgerId": int(BANK_LEDGER),
            "date": nowdate(),
            "description": "all zero rows",
            "rows": [
                {"amount": 0.001, "ledgerId": RECEIVABLE_LEDGER},
                {"amount": 0.002, "ledgerId": RECEIVABLE_LEDGER},
            ],
        }
        self.expectErrorLog("No Valid Rows")
        with self.assertRaises(Exception) as ctx:
            p.process(mut)
        self.assertIn("No valid row entries", str(ctx.exception))


# ---------------------------------------------------------------------------
# _process_money_transfer  -- party assignment onto Receivable/Payable JE lines
# ---------------------------------------------------------------------------
class TestMoneyTransferPartyAssignment(_PartyBase):
    def test_incoming_assigns_customer_to_receivable_line(self):
        """Type 5 with a Receivable row + extractable party -> Customer party on that line.

        Bank is DEBITED (money in), the Receivable line is CREDITED, and the party
        extracted from the description is resolved (find-or-create) onto the
        Receivable line -- a Receivable JE line is invalid without a party, so this
        proves the party-assignment wiring actually runs for incoming transfers.
        """
        p = self._processor()
        mut = {
            "id": 7460001,
            "type": 5,
            "amount": 30.00,
            "ledgerId": int(BANK_LEDGER),
            "date": nowdate(),
            "description": "ontvangen van PPX Acme Beheer",
            "rows": [{"amount": 30.00, "ledgerId": RECEIVABLE_LEDGER}],
        }
        je = p.process(mut)
        self.assertIsNotNone(je, f"debug={p.get_debug_info()}")
        self.assertEqual(je.docstatus, 1)
        bank_line = next(a for a in je.accounts if a.account == self.bank)
        recv_line = next(a for a in je.accounts if a.account == self.receivable)
        self.assertEqual(flt(bank_line.debit_in_account_currency), 30.00)
        self.assertEqual(flt(recv_line.credit_in_account_currency), 30.00)
        # Party resolved onto the Receivable line and points at a real Customer.
        self.assertEqual(recv_line.party_type, "Customer")
        self.assertTrue(recv_line.party)
        self.assertTrue(frappe.db.exists("Customer", recv_line.party))

    def test_outgoing_assigns_supplier_to_payable_line(self):
        """Type 6 with a Payable row + extractable party -> Supplier party on the debited line."""
        p = self._processor()
        mut = {
            "id": 7460002,
            "type": 6,
            "amount": 45.00,
            "ledgerId": int(BANK_LEDGER),
            "date": nowdate(),
            "description": "betaald aan PPX Globex Diensten",
            "rows": [{"amount": 45.00, "ledgerId": PAYABLE_LEDGER}],
        }
        je = p.process(mut)
        self.assertIsNotNone(je, f"debug={p.get_debug_info()}")
        self.assertEqual(je.docstatus, 1)
        bank_line = next(a for a in je.accounts if a.account == self.bank)
        pay_line = next(a for a in je.accounts if a.account == self.payable)
        self.assertEqual(flt(bank_line.credit_in_account_currency), 45.00)
        self.assertEqual(flt(pay_line.debit_in_account_currency), 45.00)
        self.assertEqual(pay_line.party_type, "Supplier")
        self.assertTrue(pay_line.party)
        self.assertTrue(frappe.db.exists("Supplier", pay_line.party))


# ---------------------------------------------------------------------------
# _adjust_payment_gateway_amount  -- short-circuit branches (gateway configured)
# ---------------------------------------------------------------------------
class TestAdjustGatewayBranches(_PartyBase):
    GATEWAY_LEDGER_ID = "7400999"
    GATEWAY_PREFIX = "PPXMOLLIE-"

    def setUp(self):
        super().setUp()
        self._saved_account = frappe.db.get_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account"
        )
        self._saved_prefix = frappe.db.get_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix"
        )
        # Map a real account as the gateway virtual account.
        self.gateway_account = self.expense
        self._make_ledger_map(self.GATEWAY_LEDGER_ID, self.gateway_account, "PPX Gateway")
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account", self.gateway_account
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix", self.GATEWAY_PREFIX
        )

    def tearDown(self):
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account", self._saved_account
        )
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_invoice_prefix", self._saved_prefix
        )
        super().tearDown()

    def _gateway_mutation(self, **over):
        m = {
            "id": 7450000,
            "type": 4,
            "amount": -10.0,
            "ledgerId": self.GATEWAY_LEDGER_ID,
            "invoiceNumber": f"{self.GATEWAY_PREFIX}INV-1",
        }
        m.update(over)
        return m

    def test_adjust_wrong_ledger_returns_original(self):
        """A Type-4 mutation on a non-gateway ledger is returned unchanged."""
        p = self._processor()
        mut = self._gateway_mutation(ledgerId="7400111")
        self.assertIs(p._adjust_payment_gateway_amount(mut), mut)

    def test_adjust_wrong_prefix_returns_original(self):
        """An invoice number lacking the gateway prefix is returned unchanged."""
        p = self._processor()
        mut = self._gateway_mutation(invoiceNumber="REGULAR-1")
        self.assertIs(p._adjust_payment_gateway_amount(mut), mut)

    def test_adjust_no_invoice_returns_original(self):
        """Gateway ledger + prefix but no matching invoice -> original returned, no adjustment keys."""
        p = self._processor()
        mut = self._gateway_mutation(invoiceNumber=f"{self.GATEWAY_PREFIX}NOPE")
        result = p._adjust_payment_gateway_amount(mut)
        self.assertIs(result, mut)
        self.assertNotIn("_original_amount", result)
        self.assertTrue(any("Could not find invoice" in m for m in p.get_debug_info()))

    def test_is_adjustment_false_when_gateway_account_unmapped(self):
        """_is_payment_gateway_adjustment short-circuits when the gateway account has no ledger map."""
        # Point the gateway account at the Receivable (which has no ledger mapping).
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account", self.receivable
        )
        existing = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"erpnext_account": self.receivable}, "name"
        )
        if existing:
            frappe.db.delete("E-Boekhouden Ledger Mapping", {"name": existing})
        p = self._processor()
        self.assertFalse(p._is_payment_gateway_adjustment(self._gateway_mutation()))

    def test_adjust_unmapped_gateway_account_returns_original(self):
        """When the gateway account has no ledger mapping, adjustment short-circuits."""
        # Point settings at an account that has NO ledger mapping.
        frappe.db.set_single_value(
            "E-Boekhouden Settings", "payment_gateway_virtual_account", self.receivable
        )
        # Remove any mapping for the receivable account.
        existing = frappe.db.get_value(
            "E-Boekhouden Ledger Mapping", {"erpnext_account": self.receivable}, "name"
        )
        if existing:
            frappe.db.delete("E-Boekhouden Ledger Mapping", {"name": existing})
        p = self._processor()
        mut = self._gateway_mutation()
        self.assertIs(p._adjust_payment_gateway_amount(mut), mut)


if __name__ == "__main__":
    import unittest

    unittest.main()
