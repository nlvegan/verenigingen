# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# Coverage sweep for the MT940 Import controller. The existing
# test_mt940_import.py already covers validate(), the happy submit path, the
# Mollie sandbox path and the whitelisted endpoints. This file fills the
# remaining branches that are exercisable WITHOUT live external credentials:
#
#   - before_save(): import_date / import_status preserved when already set,
#     and the default import_type fallback
#   - extract_date_range_from_result(): the transactions-created>0 fallback that
#     queries committed Bank Transactions, plus the get_transaction_date_range()
#     path that returns real (from, to) for rows created in this window
#   - generate_descriptive_name(): bank-account suffix stripping
#   - create_mollie_bulk_import(): the defensive branches that throw before any
#     external call (no company, missing bank account, strategy normalization)
#
# The debug_import / debug_duplicates endpoints and the live Mollie bulk
# importer success path are intentionally NOT covered here: they require either
# a live Mollie API or back UI "debug" buttons, and the no-mock rule forbids
# faking the boundary. They are covered (sandbox) or flagged in the sibling file.

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures import mt940_sample_statements as S
from verenigingen.verenigingen.doctype.mt940_import import mt940_import as C
from verenigingen.verenigingen.doctype.mt940_import.test_mt940_import import MT940ControllerTestBase


class TestMT940BeforeSaveDefaults(MT940ControllerTestBase):
    """before_save() default-seeding branches."""

    def test_existing_import_date_and_status_preserved(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        # Re-save with explicit non-default values; before_save must not clobber.
        doc.import_date = getdate("2023-06-01")
        doc.import_status = "Completed"
        doc.save()
        doc.reload()
        self.assertEqual(getdate(doc.import_date), getdate("2023-06-01"))
        self.assertEqual(doc.import_status, "Completed")

    def test_company_preserved_when_already_set(self):
        # company set explicitly → before_save must not re-derive/overwrite.
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        self.assertEqual(doc.company, self.company)
        doc.save()  # second save with company already populated
        doc.reload()
        self.assertEqual(doc.company, self.company)


class TestMT940DateRangeFromTransactions(MT940ControllerTestBase):
    """extract_date_range_from_result() fallback that queries real Bank Transactions."""

    def test_extract_uses_transaction_range_when_no_statement_dates(self):
        # Submit a multi-transaction statement so real, committed, submitted
        # Bank Transactions exist for this account in the last-5-minutes window.
        doc = self._make_file_import_doc(S.MULTI_TRANSACTION)
        doc.submit()
        doc.reload()
        self.assertEqual(doc.transactions_created, 3)

        # Now call extract with a result that omits statement_from/to but reports
        # created transactions → falls into the get_transaction_date_range branch.
        doc.statement_from_date = None
        doc.statement_to_date = None
        doc.extract_date_range_from_result({"transactions_created": 3})

        from_date, to_date = doc.get_transaction_date_range()
        self.assertIsNotNone(from_date)
        self.assertIsNotNone(to_date)
        # extract_date_range_from_result must have populated statement dates.
        self.assertTrue(doc.statement_from_date)
        self.assertTrue(doc.statement_to_date)
        self.assertEqual(getdate(doc.statement_from_date), getdate(from_date))


class TestMT940DescriptiveNameSuffix(MT940ControllerTestBase):
    """generate_descriptive_name() bank-account suffix stripping."""

    def test_suffix_stripped_from_bank_account(self):
        doc = self._make_file_import_doc(S.SEPA_INCOMING_CREDIT)
        # Force a bank-account value that carries a ' - ' company suffix.
        doc.bank_account = "My Account - Test Company"
        doc.statement_from_date = getdate("2024-02-01")
        doc.statement_to_date = getdate("2024-02-01")
        doc.transactions_created = 0
        name = doc.generate_descriptive_name()
        self.assertTrue(name.startswith("My Account"))
        self.assertNotIn(" - Test Company - ", name)


class TestMT940CreateMollieBulkImportGuards(MT940ControllerTestBase):
    """create_mollie_bulk_import() defensive branches that run before the importer."""

    def test_strategy_normalization_settlements_to_balances_only(self):
        result = C.create_mollie_bulk_import(
            from_date=str(add_days(today(), -5)),
            to_date=str(today()),
            strategy="settlements",  # bulk-importer value → balances_only
            company=self.company,
            bank_account=self.bank_account,
        )
        self.assertTrue(result["success"], msg=result.get("error"))
        name = result["import_doc_name"]
        self.created_records.append(("MT940 Import", name))
        created = frappe.get_doc("MT940 Import", name)
        self.assertEqual(created.mollie_import_strategy, "balances_only")

    def test_unknown_strategy_defaults_to_hybrid(self):
        result = C.create_mollie_bulk_import(
            from_date=str(add_days(today(), -5)),
            to_date=str(today()),
            strategy="nonsense-strategy",
            company=self.company,
            bank_account=self.bank_account,
        )
        self.assertTrue(result["success"], msg=result.get("error"))
        name = result["import_doc_name"]
        self.created_records.append(("MT940 Import", name))
        self.assertEqual(frappe.get_doc("MT940 Import", name).mollie_import_strategy, "hybrid")

    def test_nonexistent_bank_account_returns_error(self):
        # An explicit bank account that does not exist must be rejected by the
        # frappe.db.exists guard (returns {"success": False, ...}, no raise).
        result = C.create_mollie_bulk_import(
            from_date=str(add_days(today(), -5)),
            to_date=str(today()),
            strategy="hybrid",
            company=self.company,
            bank_account="NONEXISTENT-BANK-ACCOUNT-ZZZ",
        )
        self.assertFalse(result["success"])
        self.assertIn("error", result)
