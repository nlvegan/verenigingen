"""
Coverage sweep for the Mollie bulk transaction importer's import/extraction paths.

Complements ``test_bulk_transaction_importer.py`` (which covers the pure helpers)
and the consumer-data QA suite by exercising the previously-uncovered branches:

    - _create_bank_transaction_from_payment: deposit vs WITHDRAWAL sign, description
      fallback, consumer extraction per method (ideal/banktransfer/directdebit/
      creditcard), member matching -> party_type/party, invalid-IBAN-not-matched.
    - _create_bank_transaction_from_settlement: settlement -> Bank Transaction
      (deposit, reference, custom settlement id, description).
    - _process_payment_for_import / _process_settlement_for_import: date parsing,
      missing-date guards, imported flags.
    - import_transactions orchestration (settlements / payments / hybrid) driven by
      hand-written stub API clients (the live Mollie HTTP boundary only), asserting
      real imported counts and a persisted MT940 Import record.
    - _import_payment_data duplicate skipping.
    - _save_import_record persisted-field mapping.
    - get_import_history / estimate_import_size against stub clients.

Only the Mollie SDK/HTTP boundary is stubbed (hand-written stub clients returning
canned API dicts). Every importer method under test runs for real, against real
Bank Transaction / Member / SEPA Mandate / MT940 Import documents.
"""

from datetime import datetime, timezone

import frappe
from frappe.utils import getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
    BulkTransactionImporter,
)


# ---------------------------------------------------------------------------
# Hand-written stubs for the Mollie API clients. These stand in for the live
# HTTP/SDK boundary only - the importer's extraction/mapping/persistence logic
# runs for real against whatever these return.
# ---------------------------------------------------------------------------
class _StubSettlementsClient:
    def __init__(self, settlements):
        self._settlements = settlements

    def get_settlements_by_date_range(self, from_str, to_str):
        return list(self._settlements)


class _StubPaymentsClient:
    def __init__(self, payments):
        self._payments = payments

    def list_payments(self, from_date=None, to_date=None):
        return list(self._payments)


def _payment(payment_id, value="25.00", method="ideal", details=None, **extra):
    """Build a Mollie-shaped payment dict (the importer reads dicts via .get())."""
    p = {
        "id": payment_id,
        "amount": {"value": value, "currency": "EUR"},
        "createdAt": "2024-03-15T10:30:00.000Z",
        "method": method,
        "status": "paid",
        "details": details if details is not None else {},
    }
    p.update(extra)
    return p


class _BulkImporterSweepBase(EnhancedTestCase):
    """Shared EUR company + company bank account for the sweep."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.bank_account = cls._persist_company_bank_account(cls.company)
        cls._persist_mollie_custom_fields()
        frappe.db.commit()

    @staticmethod
    def _persist_mollie_custom_fields():
        """Provision the 9 Mollie custom fields on Bank Transaction if absent.

        _validate_mollie_custom_fields() raises (swallowed) when any are missing;
        production installs them via fixtures/custom_field.json on migrate.
        """
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        required = [
            ("custom_mollie_settlement_id", "Mollie Settlement ID"),
            ("custom_mollie_payment_id", "Mollie Payment ID"),
            ("custom_mollie_reference", "Mollie Reference"),
            ("custom_mollie_status", "Mollie Status"),
            ("custom_mollie_method", "Mollie Method"),
            ("custom_mollie_consumer_name", "Mollie Consumer Name"),
            ("custom_mollie_consumer_account", "Mollie Consumer Account"),
            ("custom_mollie_import_source", "Mollie Import Source"),
            ("custom_import_batch_id", "Import Batch ID"),
        ]
        existing = {f.fieldname for f in frappe.get_meta("Bank Transaction").fields}
        missing = [
            {"fieldname": fn, "label": lbl, "fieldtype": "Data", "insert_after": "description"}
            for fn, lbl in required
            if fn not in existing
        ]
        if missing:
            create_custom_fields({"Bank Transaction": missing}, ignore_validate=True)
            frappe.clear_cache(doctype="Bank Transaction")

    @classmethod
    def _persist_company_bank_account(cls, company):
        """Get-or-create a default company Bank Account for the EUR test company."""
        existing = frappe.db.get_value(
            "Bank Account", {"company": company, "is_default": 1}, "name"
        ) or frappe.db.get_value("Bank Account", {"company": company}, "name")
        if existing:
            return existing

        bank_name = "TEST Mollie Sweep Bank"
        if not frappe.db.exists("Bank", bank_name):
            bank = frappe.new_doc("Bank")
            bank.bank_name = bank_name
            bank.insert(ignore_permissions=True)

        gl_account = cls._persist_bank_gl_account(company)
        ba = frappe.new_doc("Bank Account")
        # Bank Account.autoname is ``account_name + " - " + bank`` with NO company
        # component (erpnext bank_account.py), so a fixed account_name is a GLOBAL
        # unique key. This helper is per-company, and is called with two different
        # companies in one run -- the EUR test company from this base class, and
        # whatever default company test_bulk_transaction_importer_branches resolves
        # -- so a fixed name made the second call die with DuplicateEntryError.
        # The GL account below needs no such treatment: erpnext already suffixes
        # Account names with the company abbreviation.
        abbr = frappe.db.get_value("Company", company, "abbr") or company
        ba.account_name = f"TEST Mollie Sweep Account {abbr}"
        ba.bank = bank_name
        ba.company = company
        ba.account = gl_account
        ba.is_default = 1
        ba.is_company_account = 1
        ba.insert(ignore_permissions=True)
        return ba.name

    @staticmethod
    def _persist_bank_gl_account(company):
        existing = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
        )
        if existing:
            return existing
        parent = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name")
        account = frappe.new_doc("Account")
        account.account_name = "TEST Mollie Sweep Bank GL"
        account.company = company
        account.parent_account = parent
        account.account_type = "Bank"
        account.is_group = 0
        account.insert(ignore_permissions=True)
        return account.name

    def setUp(self):
        super().setUp()
        self.imp = BulkTransactionImporter()

    def _unique_iban(self, bank_code="RABO"):
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        account_number = (str(self.uid) + "0000000000")[:10]
        return generate_test_iban(bank_code, account_number=account_number)


class TestCreateBankTransactionFromPayment(_BulkImporterSweepBase):
    """_create_bank_transaction_from_payment field mapping and branches."""

    def _create_bt(self, payment, date=None):
        date = date or datetime(2024, 3, 15, 10, 30, tzinfo=timezone.utc)
        return self.imp._create_bank_transaction_from_payment(payment, date, self.company, self.bank_account)

    def test_positive_amount_is_deposit(self):
        bt = self._create_bt(_payment(f"tr_pos_{self.uid}", value="75.50", method="ideal"))
        self.assertIsNotNone(bt)
        self.assertEqual(bt.deposit, 75.50)
        self.assertEqual(bt.withdrawal, 0)
        self.assertEqual(bt.currency, "EUR")
        self.assertEqual(bt.date, getdate("2024-03-15"))
        self.assertEqual(bt.reference_number, f"tr_pos_{self.uid}")
        self.assertEqual(bt.bank_account, self.bank_account)
        self.assertEqual(bt.company, self.company)

    def test_negative_amount_is_withdrawal(self):
        """A negative Mollie amount (e.g. refund/chargeback) must map to WITHDRAWAL,
        not deposit. This sign branch is not exercised by the QA suite (all-positive)."""
        bt = self._create_bt(_payment(f"tr_neg_{self.uid}", value="-30.00", method="ideal"))
        self.assertIsNotNone(bt)
        self.assertEqual(bt.withdrawal, 30.0)
        self.assertEqual(bt.deposit, 0)

    def test_description_fallback_when_missing(self):
        """No 'description' key -> synthesized 'Mollie Payment <id>'."""
        payment = _payment(f"tr_nodesc_{self.uid}", value="10.00")
        payment.pop("description", None)  # ensure absent (default already absent)
        bt = self._create_bt(payment)
        self.assertEqual(bt.description, f"Mollie Payment tr_nodesc_{self.uid}")

    def test_explicit_description_preserved(self):
        payment = _payment(f"tr_desc_{self.uid}", value="10.00")
        payment["description"] = "Contributie maart"
        bt = self._create_bt(payment)
        self.assertEqual(bt.description, "Contributie maart")

    def test_ideal_consumer_iban_extracted(self):
        bt = self._create_bt(
            _payment(
                f"tr_ideal_{self.uid}",
                method="ideal",
                details={"consumerName": "Jan de Vries", "consumerAccount": "NL91ABNA0417164300"},
            )
        )
        self.assertEqual(bt.bank_party_name, "Jan de Vries")
        self.assertEqual(bt.bank_party_iban, "NL91ABNA0417164300")
        self.assertEqual(bt.bank_party_account_number, "NL91ABNA0417164300")
        self.assertEqual(bt.get("custom_mollie_method"), "ideal")
        self.assertEqual(bt.get("custom_mollie_status"), "paid")
        self.assertEqual(bt.get("custom_mollie_import_source"), "Bulk Import")

    def test_banktransfer_consumer_iban_extracted(self):
        bt = self._create_bt(
            _payment(
                f"tr_bt_{self.uid}",
                method="banktransfer",
                details={"consumerName": "Maria Jansen", "consumerAccount": "DE89370400440532013000"},
            )
        )
        self.assertEqual(bt.bank_party_name, "Maria Jansen")
        self.assertEqual(bt.bank_party_iban, "DE89370400440532013000")

    def test_directdebit_consumer_iban_extracted(self):
        bt = self._create_bt(
            _payment(
                f"tr_dd_{self.uid}",
                method="directdebit",
                details={"consumerName": "Piet Bakker", "consumerAccount": "BE68539007547034"},
            )
        )
        self.assertEqual(bt.bank_party_name, "Piet Bakker")
        self.assertEqual(bt.bank_party_iban, "BE68539007547034")

    def test_creditcard_leaves_consumer_fields_blank(self):
        """creditcard is not one of the IBAN-extracting branches; no consumer fields,
        no party matching."""
        bt = self._create_bt(_payment(f"tr_cc_{self.uid}", method="creditcard", details={"cardHolder": "X"}))
        self.assertIsNone(bt.bank_party_name)
        self.assertIsNone(bt.bank_party_iban)
        self.assertFalse(bt.party_type)
        self.assertFalse(bt.party)
        self.assertEqual(bt.get("custom_mollie_method"), "creditcard")

    def test_invalid_consumer_iban_not_stored_as_iban(self):
        """A non-IBAN consumerAccount must leave bank_party_iban unset (validate_iban
        fails) while still recording the raw account number."""
        bt = self._create_bt(
            _payment(
                f"tr_badiban_{self.uid}",
                method="ideal",
                details={"consumerName": "Bad Iban", "consumerAccount": "NOT-AN-IBAN"},
            )
        )
        self.assertIsNone(bt.bank_party_iban)
        self.assertEqual(bt.bank_party_account_number, "NOT-AN-IBAN")

    def test_member_matched_sets_party(self):
        """A directdebit whose consumerAccount matches an Active SEPA Mandate IBAN
        links the Bank Transaction to that Member (party_type/party)."""
        member = self.create_test_member(
            first_name="Match",
            last_name=f"Payer{self.uid}",
            email=f"match.payer.{self.uid}@example.com",
        )
        iban = self._unique_iban("RABO")
        mandate = self.create_test_sepa_mandate(member=member.name, status="Active", iban=iban)
        self.created_records.append(("SEPA Mandate", mandate.name))

        bt = self._create_bt(
            _payment(
                f"tr_member_{self.uid}",
                method="directdebit",
                details={"consumerName": "Anything", "consumerAccount": iban},
            )
        )
        self.assertEqual(bt.party_type, "Member")
        self.assertEqual(bt.party, member.name)


class TestCreateBankTransactionFromSettlement(_BulkImporterSweepBase):
    """_create_bank_transaction_from_settlement field mapping."""

    def test_settlement_creates_bank_transaction(self):
        self.imp.import_id = f"batch_{self.uid}"
        settlement = {
            "id": f"stl_{self.uid}",
            "reference": f"1234567.2024.03",
            "amount": {"value": "500.00", "currency": "EUR"},
            "settledAt": "2024-03-20T00:00:00.000Z",
        }
        settled_at = datetime(2024, 3, 20, tzinfo=timezone.utc)
        bt = self.imp._create_bank_transaction_from_settlement(
            settlement, settled_at, self.company, self.bank_account
        )
        self.assertIsNotNone(bt)
        self.assertEqual(bt.deposit, 500.00)
        self.assertEqual(bt.withdrawal, 0)
        self.assertEqual(bt.date, getdate("2024-03-20"))
        self.assertEqual(bt.reference_number, f"stl_{self.uid}")
        self.assertEqual(bt.description, "Mollie Settlement 1234567.2024.03")
        self.assertEqual(bt.get("custom_mollie_settlement_id"), f"stl_{self.uid}")
        self.assertEqual(bt.get("custom_mollie_reference"), "1234567.2024.03")
        self.assertEqual(bt.get("custom_import_batch_id"), f"batch_{self.uid}")


class TestProcessForImport(_BulkImporterSweepBase):
    """_process_payment_for_import / _process_settlement_for_import wrappers."""

    def test_process_payment_missing_date_errors(self):
        result = self.imp._process_payment_for_import({"id": "tr_x"}, self.company, self.bank_account)
        # Early return replaces the seed dict, so only the error key is present.
        self.assertEqual(result, {"error": "No payment date"})

    def test_process_payment_imports_and_returns_name(self):
        self.imp.import_id = f"b_{self.uid}"
        result = self.imp._process_payment_for_import(
            _payment(f"tr_proc_{self.uid}", value="40.00"), self.company, self.bank_account
        )
        self.assertTrue(result["imported"])
        self.assertTrue(frappe.db.exists("Bank Transaction", result["transaction"]))

    def test_process_settlement_missing_date_skipped(self):
        result = self.imp._process_settlement_for_import(
            {"id": "stl_nodate"}, self.company, self.bank_account
        )
        self.assertEqual(result.get("skipped"), 1)
        self.assertEqual(result.get("reason"), "No settlement date")

    def test_process_settlement_imports(self):
        self.imp.import_id = f"bs_{self.uid}"
        settlement = {
            "id": f"stl_proc_{self.uid}",
            "reference": "ref-x",
            "amount": {"value": "100.00", "currency": "EUR"},
            "settledAt": "2024-03-20T00:00:00.000Z",
        }
        result = self.imp._process_settlement_for_import(settlement, self.company, self.bank_account)
        self.assertEqual(result.get("imported"), 1)
        self.assertTrue(frappe.db.exists("Bank Transaction", result["transaction"]))


class TestImportTransactionsOrchestration(_BulkImporterSweepBase):
    """import_transactions across strategies, driven by stub API clients."""

    def _from_to(self):
        return (
            datetime(2024, 3, 1, tzinfo=timezone.utc),
            datetime(2024, 3, 31, tzinfo=timezone.utc),
        )

    def test_payments_only_strategy(self):
        payments = [
            _payment(f"tr_imp_a_{self.uid}", value="10.00"),
            _payment(f"tr_imp_b_{self.uid}", value="20.00"),
        ]
        self.imp.payments_client = _StubPaymentsClient(payments)
        self.imp.settlements_client = _StubSettlementsClient([])

        from_d, to_d = self._from_to()
        results = self.imp.import_transactions(from_d, to_d, "payments", self.company, self.bank_account)

        self.assertEqual(results["transactions"]["payments_imported"], 2)
        self.assertEqual(results["transactions"]["settlements_imported"], 0)
        self.assertEqual(results["transactions"]["total_imported"], 2)
        self.assertEqual(results["status"], "completed")
        self.assertEqual(results["strategy"], "payments")
        # Both payments persisted as real Bank Transactions.
        self.assertTrue(frappe.db.exists("Bank Transaction", {"reference_number": f"tr_imp_a_{self.uid}"}))
        self.assertTrue(frappe.db.exists("Bank Transaction", {"reference_number": f"tr_imp_b_{self.uid}"}))

    def test_settlements_only_strategy(self):
        settlements = [
            {
                "id": f"stl_imp_{self.uid}",
                "reference": "settle-ref",
                "amount": {"value": "999.00", "currency": "EUR"},
                "settledAt": "2024-03-10T00:00:00.000Z",
            }
        ]
        self.imp.settlements_client = _StubSettlementsClient(settlements)
        self.imp.payments_client = _StubPaymentsClient([])

        from_d, to_d = self._from_to()
        results = self.imp.import_transactions(from_d, to_d, "settlements", self.company, self.bank_account)
        self.assertEqual(results["transactions"]["settlements_imported"], 1)
        self.assertEqual(results["transactions"]["payments_imported"], 0)
        self.assertEqual(results["status"], "completed")
        self.assertTrue(
            frappe.db.exists("Bank Transaction", {"custom_mollie_settlement_id": f"stl_imp_{self.uid}"})
        )

    def test_hybrid_strategy_combines_and_persists_import_record(self):
        payments = [_payment(f"tr_hy_{self.uid}", value="15.00")]
        settlements = [
            {
                "id": f"stl_hy_{self.uid}",
                "reference": "hy-ref",
                "amount": {"value": "200.00", "currency": "EUR"},
                "settledAt": "2024-03-12T00:00:00.000Z",
            }
        ]
        self.imp.payments_client = _StubPaymentsClient(payments)
        self.imp.settlements_client = _StubSettlementsClient(settlements)

        from_d, to_d = self._from_to()
        results = self.imp.import_transactions(from_d, to_d, "hybrid", self.company, self.bank_account)

        self.assertEqual(results["transactions"]["settlements_imported"], 1)
        self.assertEqual(results["transactions"]["payments_imported"], 1)
        self.assertEqual(results["transactions"]["total_imported"], 2)
        self.assertEqual(results["status"], "completed")
        self.assertIn("duration_seconds", results)

        # A tracking MT940 Import record was persisted by _save_import_record.
        rec = frappe.db.get_value(
            "MT940 Import",
            {"import_summary": ["like", f"%{results['import_id']}%"]},
            ["name", "import_type", "transactions_created", "mollie_import_strategy"],
            as_dict=True,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.import_type, "Mollie Bulk Import")
        self.assertEqual(rec.transactions_created, 2)
        self.assertEqual(rec.mollie_import_strategy, "hybrid")

    def test_duplicate_payment_skipped(self):
        """Re-importing the same payment id is detected as a duplicate, not re-created."""
        payment = _payment(f"tr_dupimp_{self.uid}", value="33.00")
        self.imp.settlements_client = _StubSettlementsClient([])

        from_d, to_d = self._from_to()
        # First import creates the Bank Transaction.
        self.imp.payments_client = _StubPaymentsClient([payment])
        first = self.imp.import_transactions(from_d, to_d, "payments", self.company, self.bank_account)
        self.assertEqual(first["transactions"]["payments_imported"], 1)
        frappe.db.commit()

        # Second import of the same payment id: duplicate detection skips it.
        imp2 = BulkTransactionImporter()
        imp2.settlements_client = _StubSettlementsClient([])
        imp2.payments_client = _StubPaymentsClient([payment])
        second = imp2.import_transactions(from_d, to_d, "payments", self.company, self.bank_account)
        self.assertEqual(second["transactions"]["payments_imported"], 0)
        self.assertEqual(second["transactions"]["duplicates_skipped"], 1)


class TestSaveImportRecordAndHistory(_BulkImporterSweepBase):
    """_save_import_record persisted fields + get_import_history retrieval."""

    def _results(self):
        return {
            "import_id": f"hist_{self.uid}",
            "strategy": "payments",
            "company": self.company,
            "bank_account": self.bank_account,
            "status": "completed",
            "date_range": {"from": "2024-03-01T00:00:00+00:00", "to": "2024-03-31T00:00:00+00:00"},
            "transactions": {
                "settlements_imported": 0,
                "payments_imported": 3,
                "duplicates_skipped": 1,
                "errors": 0,
                "total_imported": 3,
            },
        }

    def test_save_import_record_persists_fields(self):
        self.imp.import_id = f"hist_{self.uid}"
        results = self._results()
        self.imp._save_import_record(results)

        rec = frappe.db.get_value(
            "MT940 Import",
            {"import_summary": ["like", f"%hist_{self.uid}%"]},
            [
                "name",
                "import_type",
                "bank_account",
                "company",
                "transactions_created",
                "transactions_skipped",
                "mollie_import_strategy",
                "import_status",
            ],
            as_dict=True,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.import_type, "Mollie Bulk Import")
        self.assertEqual(rec.bank_account, self.bank_account)
        self.assertEqual(rec.transactions_created, 3)
        self.assertEqual(rec.transactions_skipped, 1)
        # strategy "payments" maps to DocType value "payments_only".
        self.assertEqual(rec.mollie_import_strategy, "payments_only")
        self.assertEqual(rec.import_status, "Completed")

    def test_get_import_history_returns_saved_record(self):
        self.imp.import_id = f"hist_{self.uid}"
        self.imp._save_import_record(self._results())
        frappe.db.commit()

        history = self.imp.get_import_history(days=30)
        self.assertTrue(any(f"hist_{self.uid}" in (r.get("import_summary") or "") for r in history))


class TestEstimateImportSize(_BulkImporterSweepBase):
    """estimate_import_size against stub clients (no live API)."""

    def test_estimate_settlements_strategy(self):
        self.imp.settlements_client = _StubSettlementsClient([{"id": "a"}, {"id": "b"}, {"id": "c"}])
        from_d = datetime(2024, 3, 1, tzinfo=timezone.utc)
        to_d = datetime(2024, 3, 31, tzinfo=timezone.utc)
        est = self.imp.estimate_import_size(from_d, to_d, "settlements")
        self.assertEqual(est["settlements_count"], 3)
        self.assertEqual(est["estimated_transactions"], 3)
        self.assertEqual(est["date_range"]["days"], 30)

    def test_estimate_payments_warns_on_large_range(self):
        self.imp.settlements_client = _StubSettlementsClient([])
        from_d = datetime(2024, 1, 1, tzinfo=timezone.utc)
        to_d = datetime(2024, 6, 1, tzinfo=timezone.utc)  # >90 days
        est = self.imp.estimate_import_size(from_d, to_d, "payments")
        self.assertIn("estimated_payments", est)
        self.assertTrue(any("Large date range" in w for w in est["warnings"]))


class TestWhitelistedApiEndpoints(_BulkImporterSweepBase):
    """Module-level @frappe.whitelist API wrappers."""

    def test_estimate_bulk_import_size_bad_date_returns_error(self):
        """Invalid ISO date input is caught and surfaced as an {'error': ...} dict
        rather than raising out of the whitelisted endpoint."""
        from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
            estimate_bulk_import_size,
        )

        result = estimate_bulk_import_size("not-a-date", "2024-03-31", "hybrid")
        self.assertIn("error", result)

    def test_get_bulk_import_history_returns_saved_record(self):
        """The whitelisted history endpoint returns previously-saved bulk imports."""
        from verenigingen.verenigingen_payments.clients.bulk_transaction_importer import (
            get_bulk_import_history,
        )

        imp = BulkTransactionImporter()
        imp.import_id = f"apihist_{self.uid}"
        imp._save_import_record(
            {
                "import_id": f"apihist_{self.uid}",
                "strategy": "hybrid",
                "company": self.company,
                "bank_account": self.bank_account,
                "status": "completed",
                "date_range": {
                    "from": "2024-03-01T00:00:00+00:00",
                    "to": "2024-03-31T00:00:00+00:00",
                },
                "transactions": {
                    "settlements_imported": 1,
                    "payments_imported": 1,
                    "duplicates_skipped": 0,
                    "errors": 0,
                    "total_imported": 2,
                },
            }
        )
        frappe.db.commit()

        history = get_bulk_import_history(days=30)
        self.assertTrue(any(f"apihist_{self.uid}" in (r.get("import_summary") or "") for r in history))
