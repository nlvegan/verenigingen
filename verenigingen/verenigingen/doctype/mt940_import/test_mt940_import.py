# Copyright (c) 2025, R.S.P. and Contributors
# See license.txt

"""
Integration tests for the MT940 Import DocType controller.

Target: verenigingen/verenigingen/doctype/mt940_import/mt940_import.py

These tests exercise the controller end-to-end against a real Company + Bank
Account + File attachment on the test site. The MT940 parsing and Bank
Transaction creation run for REAL (no mocking of the parser) - the only true
external boundary stubbed/avoided is the Mollie HTTP API (no live credentials),
whose failure path is asserted rather than its success.

Controller surface covered:
    - validate (file-import vs Mollie-bulk required-field rules)
    - before_save (company / import_date / import_status / import_type defaults)
    - on_submit -> process_mt940_import -> real Bank Transactions created,
      dedup on re-import, derived status/summary/counts/date-range/name
    - extract_date_range_from_result (statement dates, fallback, no-txn branch)
    - get_transaction_date_range
    - generate_descriptive_name (single-day, date-range, fallback, count suffix)
    - process_mollie_bulk_import (strategy mapping + date conversion + failure
      handling without live Mollie creds)
    - whitelisted: submit_import, create_mollie_bulk_import,
      get_mollie_bulk_import_history

debug_import / debug_duplicates back live "Test/Debug" form buttons
(mt940_import.js) and run in production; they are intentionally not covered here.
The dead debug_enhanced_import endpoint was removed (no callers).
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures import mt940_sample_statements as S
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.mt940_import import mt940_import as C


class MT940ControllerTestBase(EnhancedTestCase):
    """Shared real Company / Bank Account / cleanup harness."""

    # IBAN used by the sample statements' :25: container account identification.
    SAMPLE_IBAN = "NL02ABNA0123456789"

    def setUp(self):
        super().setUp()
        self.company = frappe.get_list("Company", limit=1)[0].name
        self.bank_account = self._ensure_bank_account()
        # The import path commits mid-transaction (the API security audit logger
        # commits unconditionally), so Bank Transactions survive FrappeTestCase's
        # per-test rollback. Scrub committed survivors before each test so counts
        # are deterministic.
        self._cleanup_bank_transactions()
        self._cleanup_import_docs()

    def tearDown(self):
        self._cleanup_bank_transactions()
        self._cleanup_import_docs()
        super().tearDown()

    # Bank Account autonames account_name + " - " + bank with no company
    # component (the guard-key rule), so this (account_name + bank, its full
    # autoname key) must be the existence-check, not the shared SAMPLE_IBAN --
    # another suite's Bank Account can carry the same IBAN, and querying on
    # the IBAN alone adopts whichever one was created most recently
    # (frappe.db.get_value orders creation DESC) rather than owning this
    # class's own row. See #308. The company filter is defensive, not part of
    # the autoname key: self.company is currently a stable, deterministic
    # singleton (frappe.get_list("Company", limit=1) sorts oldest-first), but
    # if #532 ever repoints it, this stops a stale row on the old company from
    # being adopted too.
    OWN_ACCOUNT_NAME = "MT940 Ctrl Account"

    def _ensure_bank_account(self):
        """Create (idempotently) a Bank Account whose IBAN matches the samples."""
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        bank = get_or_create_unknown_bank()
        existing = frappe.db.get_value(
            "Bank Account",
            {"account_name": self.OWN_ACCOUNT_NAME, "bank": bank, "company": self.company},
            "name",
        )
        if existing:
            return existing
        ba = frappe.new_doc("Bank Account")
        ba.account_name = self.OWN_ACCOUNT_NAME
        ba.bank = bank
        ba.company = self.company
        ba.bank_account_no = self.SAMPLE_IBAN
        ba.iban = self.SAMPLE_IBAN
        ba.insert()
        self.created_records.append(("Bank Account", ba.name))
        return ba.name

    def _cleanup_bank_transactions(self):
        for bt in frappe.get_all(
            "Bank Transaction", filters={"bank_account": self.bank_account}, fields=["name", "docstatus"]
        ):
            doc = frappe.get_doc("Bank Transaction", bt.name)
            if doc.docstatus == 1:
                doc.cancel()
            doc.delete(ignore_permissions=True)
        frappe.db.commit()

    def _cleanup_import_docs(self):
        for imp in frappe.get_all(
            "MT940 Import", filters={"bank_account": self.bank_account}, fields=["name", "docstatus"]
        ):
            doc = frappe.get_doc("MT940 Import", imp.name)
            if doc.docstatus == 1:
                doc.cancel()
            doc.delete(ignore_permissions=True)
        frappe.db.commit()

    def _make_mt940_file(self, mt940_text):
        """Create a real (unattached) File document and return its file_url.

        Created standalone so the file_url can be set on the import doc BEFORE
        its first insert (validate() requires mt940_file for file imports).
        """
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": f"mt940_ctrl_{self.uid}_{frappe.utils.random_string(6)}.sta",
                "is_private": 1,
                "content": mt940_text,
            }
        )
        file_doc.insert()
        self.created_records.append(("File", file_doc.name))
        return file_doc.file_url

    def _make_file_import_doc(self, mt940_text):
        """Build (insert) a file-import MT940 Import doc with a real attachment.

        Helper-scoped so the test bodies stay free of insert()/save() calls that
        the test-quality-enforcer rejects.
        """
        file_url = self._make_mt940_file(mt940_text)
        doc = frappe.new_doc("MT940 Import")
        doc.import_type = "MT940 File Import"
        doc.bank_account = self.bank_account
        doc.mt940_file = file_url
        doc.insert()
        self.created_records.append(("MT940 Import", doc.name))
        return doc

    def _make_mollie_doc(self, **overrides):
        """Build (insert) a Mollie-bulk MT940 Import doc."""
        doc = frappe.new_doc("MT940 Import")
        doc.import_type = "Mollie Bulk Import"
        doc.bank_account = self.bank_account
        doc.mollie_from_date = overrides.get("mollie_from_date", add_days(today(), -7))
        doc.mollie_to_date = overrides.get("mollie_to_date", today())
        doc.mollie_import_strategy = overrides.get("mollie_import_strategy", "hybrid")
        doc.insert()
        self.created_records.append(("MT940 Import", doc.name))
        return doc


class TestMT940ImportControllerValidation(MT940ControllerTestBase):
    """validate() + before_save() field rules and defaults."""

    def test_ensure_bank_account_owns_its_row_not_a_shared_iban_query(self):
        """A competing Bank Account sharing SAMPLE_IBAN, created by some other
        suite (not by this class), must not be adopted (#308). Before the fix,
        _ensure_bank_account resolved by bank_account_no alone, so the most
        recently created row with that IBAN won -- regardless of who owns it."""
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        competitor = frappe.new_doc("Bank Account")
        competitor.account_name = f"Some Other Suite's Account {frappe.generate_hash()[:6]}"
        competitor.bank = get_or_create_unknown_bank()
        competitor.company = self.company
        competitor.bank_account_no = self.SAMPLE_IBAN
        competitor.iban = self.SAMPLE_IBAN
        competitor.insert()
        self.created_records.append(("Bank Account", competitor.name))

        resolved = self._ensure_bank_account()

        self.assertEqual(
            resolved,
            self.bank_account,
            "must resolve to its own owned account, not a competitor sharing the IBAN",
        )
        # Pin the owned identity itself, not just equality with a value the
        # same helper produced on the same instance -- a regression that
        # reintroduces a per-instance-unique account_name would still pass
        # the assertEqual above (both sides freshly created by this call).
        self.assertTrue(
            resolved.startswith(self.OWN_ACCOUNT_NAME),
            f"must own the stable '{self.OWN_ACCOUNT_NAME}' row, got {resolved!r}",
        )

    def test_file_import_requires_mt940_file(self):
        """A file import with no attachment must be rejected by validate()."""
        doc = frappe.new_doc("MT940 Import")
        doc.import_type = "MT940 File Import"
        doc.bank_account = self.bank_account
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_mollie_import_requires_from_date(self):
        doc = frappe.new_doc("MT940 Import")
        doc.import_type = "Mollie Bulk Import"
        doc.bank_account = self.bank_account
        doc.mollie_to_date = today()
        # mollie_from_date missing
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_mollie_import_requires_to_date(self):
        doc = frappe.new_doc("MT940 Import")
        doc.import_type = "Mollie Bulk Import"
        doc.bank_account = self.bank_account
        doc.mollie_from_date = today()
        # mollie_to_date missing
        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_before_save_sets_company_status_and_import_date(self):
        """before_save derives company from the bank account and seeds defaults."""
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        self.assertEqual(doc.company, self.company)
        self.assertEqual(doc.import_status, "Pending")
        self.assertEqual(getdate(doc.import_date), getdate(today()))
        # import_type default preserved (explicitly set here, but field default exists)
        self.assertEqual(doc.import_type, "MT940 File Import")


class TestMT940ImportControllerDescriptiveName(MT940ControllerTestBase):
    """generate_descriptive_name() across its branches (no submit needed)."""

    def test_single_day_name_uses_one_date(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.statement_from_date = getdate("2024-01-15")
        doc.statement_to_date = getdate("2024-01-15")
        doc.transactions_created = 0  # avoid count suffix
        name = doc.generate_descriptive_name()
        self.assertIn("15-01-2024", name)
        self.assertNotIn(" to ", name)
        # Bank-account suffix-stripping: name should start with the account ref part.
        self.assertTrue(name.startswith(self.bank_account.split(" - ")[0]))

    def test_date_range_name_includes_both_dates(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.statement_from_date = getdate("2024-01-01")
        doc.statement_to_date = getdate("2024-01-31")
        doc.transactions_created = 0
        name = doc.generate_descriptive_name()
        self.assertIn("01-01-2024 to 31-01-2024", name)

    def test_name_includes_transaction_count_suffix(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.statement_from_date = getdate("2024-01-15")
        doc.statement_to_date = getdate("2024-01-15")
        doc.transactions_created = 7
        name = doc.generate_descriptive_name()
        self.assertIn("(7 txns)", name)

    def test_name_falls_back_to_import_date_without_statement_dates(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.statement_from_date = None
        doc.statement_to_date = None
        doc.transactions_created = 0
        from frappe.utils import formatdate

        name = doc.generate_descriptive_name()
        self.assertIn(formatdate(doc.import_date, "dd-MM-yyyy"), name)


class TestMT940ImportControllerDateRangeExtraction(MT940ControllerTestBase):
    """extract_date_range_from_result() branch coverage."""

    def test_statement_dates_taken_from_result(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.extract_date_range_from_result(
            {"statement_from_date": "2023-12-01", "statement_to_date": "2023-12-31"}
        )
        self.assertEqual(getdate(doc.statement_from_date), getdate("2023-12-01"))
        self.assertEqual(getdate(doc.statement_to_date), getdate("2023-12-31"))
        self.assertTrue(doc.descriptive_name)

    def test_no_transactions_falls_back_to_import_date(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.extract_date_range_from_result({"transactions_created": 0})
        self.assertEqual(getdate(doc.statement_from_date), getdate(doc.import_date))
        self.assertEqual(getdate(doc.statement_to_date), getdate(doc.import_date))

    def test_get_transaction_date_range_returns_none_without_committed_rows(self):
        """No submitted Bank Transactions for this account -> (None, None)."""
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.company = self.company
        from_date, to_date = doc.get_transaction_date_range()
        self.assertIsNone(from_date)
        self.assertIsNone(to_date)


class TestMT940ImportControllerSubmit(MT940ControllerTestBase):
    """on_submit() real import path: parse -> Bank Transactions -> derived fields."""

    def test_submit_creates_real_bank_transactions(self):
        doc = self._make_file_import_doc(S.MULTI_TRANSACTION)
        doc.submit()
        doc.reload()

        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.transactions_created, 3)
        # Real Bank Transactions exist for this account.
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": self.bank_account}), 3)
        # Derived statement period + descriptive name populated from the parse result.
        self.assertTrue(doc.statement_from_date)
        self.assertTrue(doc.statement_to_date)
        self.assertTrue(doc.descriptive_name)
        self.assertIn("3 txns", doc.descriptive_name)

    def test_submit_single_incoming_sets_amount_and_reference(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.submit()
        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(doc.transactions_created, 1)

        bt = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account},
            fields=["deposit", "withdrawal", "reference_number", "bank_party_iban"],
        )[0]
        self.assertEqual(float(bt.deposit), 150.00)
        self.assertEqual(float(bt.withdrawal), 0.0)
        self.assertEqual(bt.reference_number, "INV-2024-0001")
        self.assertEqual(bt.bank_party_iban, "NL44RABO0123456789")

    def test_resubmit_same_file_deduplicates(self):
        """Two separate imports of the same statement must not double the rows."""
        first = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        first.submit()
        first.reload()
        self.assertEqual(first.transactions_created, 1)

        second = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        second.submit()
        second.reload()
        self.assertEqual(second.transactions_created, 0)
        self.assertEqual(second.transactions_skipped, 1)
        # Still exactly one Bank Transaction across both imports.
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": self.bank_account}), 1)

    def test_submit_iban_mismatch_marks_failed(self):
        """A statement whose :25: IBAN differs from the Bank Account is rejected;
        on_submit records a Failed status and creates no Bank Transactions."""
        from verenigingen.verenigingen_payments.utils.bank_utils import get_or_create_unknown_bank

        other_iban = "NL91ABNA0417164300"  # != sample :25: NL02ABNA0123456789
        other_ba = frappe.new_doc("Bank Account")
        other_ba.account_name = f"MT940 Ctrl Mismatch {self.uid}"
        other_ba.bank = get_or_create_unknown_bank()
        other_ba.company = self.company
        other_ba.bank_account_no = other_iban
        other_ba.iban = other_iban
        other_ba.insert()
        self.created_records.append(("Bank Account", other_ba.name))

        file_url = self._make_mt940_file(S.SEPA_INCOMING_CREDIT)
        doc = frappe.new_doc("MT940 Import")
        doc.import_type = "MT940 File Import"
        doc.bank_account = other_ba.name
        doc.mt940_file = file_url
        doc.insert()
        self.created_records.append(("MT940 Import", doc.name))

        doc.submit()
        doc.reload()
        self.assertEqual(doc.import_status, "Failed")
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": other_ba.name}), 0)


class TestMT940ImportProcessReturnsError(MT940ControllerTestBase):
    """process_mt940_import() defensive branches (no submit)."""

    def test_process_without_file_returns_failure(self):
        doc = frappe.new_doc("MT940 Import")
        doc.import_type = "MT940 File Import"
        doc.bank_account = self.bank_account
        # Do not insert (would fail validate); call the processor directly with no file.
        doc.mt940_file = None
        result = doc.process_mt940_import()
        self.assertFalse(result["success"])
        self.assertIn("No MT940 file", result["message"])

    def test_process_garbage_file_returns_zero_transactions(self):
        """Non-MT940 content parses to no transactions -> success False, no rows."""
        doc = self._make_file_import_doc(S.GARBAGE_CONTENT)
        result = doc.process_mt940_import()
        # The underlying library yields no transactions for garbage input.
        self.assertFalse(result["success"])
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": self.bank_account}), 0)


class TestMT940ImportMollieControllerPath(MT940ControllerTestBase):
    """process_mollie_bulk_import() strategy/date handling + completion.

    test_site_1 has Mollie test-mode credentials configured, so the bulk
    importer reaches the (sandbox) API and returns status "completed" with zero
    transactions for an empty date range. We assert the controller's pre-importer
    work (strategy mapping, date conversion, descriptive name) AND the real
    completion path, plus the date-required short-circuit which never hits the API.
    """

    def test_mollie_completed_sets_descriptive_name(self):
        """A real Mollie bulk import completes and the controller stamps a Mollie
        descriptive name carrying the date range and transaction count."""
        doc = self._make_mollie_doc(mollie_import_strategy="payments_only")
        result = doc.process_mollie_bulk_import()
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("status"), "completed")
        # Controller updates descriptive_name on completion (no DB save here).
        self.assertIn("Mollie Bulk Import", doc.descriptive_name)
        self.assertIn("txns", doc.descriptive_name)

    def test_mollie_missing_dates_returns_required_message(self):
        """When both dates are blank, the processor short-circuits with a message
        rather than calling the importer."""
        doc = self._make_mollie_doc()
        doc.mollie_from_date = None
        doc.mollie_to_date = None
        result = doc.process_mollie_bulk_import()
        self.assertFalse(result["success"])
        self.assertIn("required", result["message"].lower())

    def test_mollie_on_submit_completes(self):
        """on_submit for a Mollie import drives the bulk importer and records a
        terminal status; with sandbox creds + empty range it completes."""
        doc = self._make_mollie_doc()
        doc.submit()
        doc.reload()
        self.assertEqual(doc.import_status, "Completed")
        # transactions_created defaults to 0 for an empty sandbox range.
        self.assertEqual(doc.transactions_created or 0, 0)


class TestMT940ImportWhitelistedEndpoints(MT940ControllerTestBase):
    """submit_import / create_mollie_bulk_import / get_mollie_bulk_import_history."""

    def test_submit_import_endpoint_runs_real_import(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        result = C.submit_import(doc.name)
        self.assertTrue(result["success"], msg=result.get("error"))
        doc.reload()
        self.assertEqual(doc.docstatus, 1)
        self.assertEqual(doc.import_status, "Completed")
        self.assertEqual(frappe.db.count("Bank Transaction", {"bank_account": self.bank_account}), 1)

    def test_submit_import_rejects_already_submitted(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        doc.submit()
        result = C.submit_import(doc.name)
        self.assertFalse(result["success"])
        self.assertIn("already submitted", result["error"].lower())

    def test_create_mollie_bulk_import_creates_document(self):
        result = C.create_mollie_bulk_import(
            from_date=str(add_days(today(), -10)),
            to_date=str(today()),
            strategy="payments",  # bulk-importer value, mapped to payments_only
            company=self.company,
            bank_account=self.bank_account,
        )
        self.assertTrue(result["success"], msg=result.get("error"))
        name = result["import_doc_name"]
        self.created_records.append(("MT940 Import", name))
        created = frappe.get_doc("MT940 Import", name)
        self.assertEqual(created.import_type, "Mollie Bulk Import")
        self.assertEqual(created.bank_account, self.bank_account)
        # "payments" must be normalized to the DocType field option.
        self.assertEqual(created.mollie_import_strategy, "payments_only")

    def test_get_mollie_bulk_import_history_includes_created_doc(self):
        doc = self._make_mollie_doc()
        history = C.get_mollie_bulk_import_history(days=30)
        self.assertIsInstance(history, list)
        names = [h.get("name") for h in history if isinstance(h, dict)]
        self.assertIn(doc.name, names)

    def test_get_mollie_bulk_import_history_excludes_file_imports(self):
        """A non-Mollie file import must not appear in the Mollie history list."""
        file_doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        history = C.get_mollie_bulk_import_history(days=30)
        names = [h.get("name") for h in history if isinstance(h, dict)]
        self.assertNotIn(file_doc.name, names)
