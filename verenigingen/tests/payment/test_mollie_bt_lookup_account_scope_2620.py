"""#2620 (part of): Mollie-reference Bank Transaction lookups are scoped to the Mollie account.

reference_number is unique per bank account only (#1267), so a lookup by reference alone can
return ANOTHER account's row, or a cancelled one, and report this payment as "already
processed" -- skipping a real booking. #2583 fixed the donation processor; this covers the
balance-transaction, bulk, orchestrator, recovery and debug-service siblings.

Rows are seeded with raw SQL (no Link validation); only the Mollie account config seam is
patched, and the Mollie SDK is stubbed where a site would otherwise reach the network.
Seeding a cancelled row does NOT exercise #2626 (the cancelled row still holds the #1267
unique key): each reference here has at most one row per account, so no 1062 can arise.

Run:
    scripts/testing/run_without_credentials.sh test_site_2 \\
        verenigingen.tests.payment.test_mollie_bt_lookup_account_scope_2620
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    BankTransactionCreator,
    get_bank_transaction_creator,
)

MOLLIE_ACCOUNT = "TEST-2620-Mollie Account"
OTHER_ACCOUNT = "TEST-2620-Other Account"
COMPANY = "TEST-2620-Company"


class BankTransactionScopeCase(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.ref = f"tr_2620{frappe.generate_hash(length=8)}"
        config = {"bank_account": MOLLIE_ACCOUNT, "company": COMPANY}
        patcher = patch.object(BankTransactionCreator, "get_mollie_bank_account_config", return_value=config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def seed_bt(self, suffix, bank_account, docstatus=1, reference=None, transaction_id=None):
        name = f"TEST-2620-{suffix}-{self.ref}"
        frappe.db.sql(
            """INSERT INTO `tabBank Transaction`
               (name, creation, modified, owner, modified_by, docstatus,
                bank_account, company, reference_number, transaction_id)
               VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', %s, %s, %s, %s, %s)""",
            (name, docstatus, bank_account, COMPANY, reference or self.ref, transaction_id),
        )
        self.addCleanup(frappe.db.sql, "DELETE FROM `tabBank Transaction` WHERE name = %s", name)
        return name

    def age(self, name):
        frappe.db.sql("UPDATE `tabBank Transaction` SET creation = creation - INTERVAL 1 DAY WHERE name = %s", name)


class TestCreatorMollieLookup2620(BankTransactionScopeCase):
    def test_single_lookup_scope(self):
        creator = get_bank_transaction_creator()
        self.seed_bt("OTHER", OTHER_ACCOUNT)
        self.seed_bt("CANCELLED", MOLLIE_ACCOUNT, docstatus=2)
        self.assertIsNone(creator.find_mollie_bank_transaction(self.ref))
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT, docstatus=0)
        self.assertEqual(creator.find_mollie_bank_transaction(self.ref).name, own)

    def test_batch_lookup_scope(self):
        creator = get_bank_transaction_creator()
        other_ref = f"{self.ref}b"
        self.seed_bt("OTHER", OTHER_ACCOUNT)
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT, reference=other_ref)
        self.assertEqual(creator.find_mollie_bank_transactions([self.ref, other_ref]), {other_ref: own})
        self.assertEqual(creator.find_mollie_bank_transactions([]), {})

    def test_unresolvable_mollie_account_reports_none(self):
        creator = get_bank_transaction_creator()
        self.seed_bt("NOACCOUNT", None)
        with patch.object(BankTransactionCreator, "get_mollie_bank_account_config", return_value={"error": "x"}):
            self.assertIsNone(creator.find_mollie_bank_transaction(self.ref))
            self.assertEqual(creator.find_mollie_bank_transactions([self.ref]), {})

    def test_mollie_check_newer_cancelled_row_does_not_hide_a_live_one(self):
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT)
        self.age(own)
        self.seed_bt("NEWER-CANCELLED", MOLLIE_ACCOUNT, docstatus=2)
        result = get_bank_transaction_creator().check_mollie_payment_processed(self.ref)
        self.assertTrue(result["already_processed"])
        self.assertEqual(result["bank_transaction"], own)

    def test_mollie_check_other_accounts_row_is_not_processed(self):
        self.seed_bt("OTHER", OTHER_ACCOUNT)
        result = get_bank_transaction_creator().check_mollie_payment_processed(self.ref)
        self.assertFalse(result["already_processed"])


class TestOrchestratorLookups2620(BankTransactionScopeCase):
    def setUp(self):
        super().setUp()
        from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
            MolliePaymentOrchestrator,
        )

        self.orchestrator = MolliePaymentOrchestrator()
        # Stop any path that gets past the idempotency check before it reaches the network.
        self.orchestrator.mollie_client = MagicMock()
        self.orchestrator.mollie_client.sdk_client.payments.get.side_effect = RuntimeError("stop-2620")

    def test_status_ignores_other_accounts_and_cancelled_rows(self):
        self.seed_bt("OTHER", OTHER_ACCOUNT)
        self.seed_bt("CANCELLED", MOLLIE_ACCOUNT, docstatus=2)
        self.assertFalse(self.orchestrator.get_processing_status(self.ref).has_bank_transaction)

    def test_status_finds_own_row_under_a_newer_foreign_row(self):
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT)
        self.age(own)
        self.seed_bt("NEWER-OTHER", OTHER_ACCOUNT)
        status = self.orchestrator.get_processing_status(self.ref)
        self.assertEqual(status.bank_transaction, own)

    def test_orphan_and_bt_only_paths_do_not_skip_on_foreign_or_cancelled_rows(self):
        self.seed_bt("OTHER", OTHER_ACCOUNT)
        self.seed_bt("CANCELLED", MOLLIE_ACCOUNT, docstatus=2)
        for method in (self.orchestrator.process_orphaned_payment, self.orchestrator.process_bt_only_payment):
            with self.subTest(method=method.__name__):
                result = method(self.ref)
                self.assertNotEqual(result.status, "already_processed")
                self.assertIn("stop-2620", result.error or "", "the path must go on to fetch the payment")

    def test_orphan_and_bt_only_paths_skip_on_own_row(self):
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT)
        for method in (self.orchestrator.process_orphaned_payment, self.orchestrator.process_bt_only_payment):
            with self.subTest(method=method.__name__):
                result = method(self.ref)
                self.assertEqual(result.status, "already_processed")
                self.assertEqual(result.bank_transaction, own)


class TestRecoveryAndBulkLookups2620(BankTransactionScopeCase):
    def test_recovery_status_ignores_other_accounts_and_cancelled_rows(self):
        from verenigingen.verenigingen_payments.utils.payment_processing_recovery import (
            get_payment_processing_status,
        )

        self.seed_bt("OTHER", OTHER_ACCOUNT)
        self.seed_bt("CANCELLED", MOLLIE_ACCOUNT, docstatus=2)
        self.assertFalse(get_payment_processing_status(self.ref)["has_bank_transaction"])
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT)
        self.assertEqual(get_payment_processing_status(self.ref)["bank_transaction"], own)

    def test_batch_checker_keeps_payments_whose_only_row_is_foreign_or_cancelled(self):
        from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import BulkPaymentChecker

        foreign_ref, cancelled_ref, own_ref = (f"{self.ref}{s}" for s in "fco")
        self.seed_bt("OTHER", OTHER_ACCOUNT, reference=foreign_ref)
        self.seed_bt("CANCELLED", MOLLIE_ACCOUNT, docstatus=2, reference=cancelled_ref)
        self.seed_bt("OWN", MOLLIE_ACCOUNT, reference=own_ref)
        unprocessed = BulkPaymentChecker._batch_check_already_processed([foreign_ref, cancelled_ref, own_ref])
        self.assertEqual(sorted(unprocessed), sorted([foreign_ref, cancelled_ref]))

    def test_bulk_run_row_is_skipped_only_for_a_live_row_on_the_mollie_account(self):
        from verenigingen.verenigingen_payments.services import mollie_bulk_run_service as svc

        foreign = SimpleNamespace(payment_id=self.ref, attempts=0, row_status="Pending")
        own_ref = f"{self.ref}o"
        own = SimpleNamespace(payment_id=own_ref, attempts=0, row_status="Pending")
        self.seed_bt("OTHER", OTHER_ACCOUNT)
        own_bt = self.seed_bt("OWN", MOLLIE_ACCOUNT, reference=own_ref)
        run = MagicMock(status="Processing", payments=[foreign, own], last_processed_index=0)
        run.total_succeeded = run.total_skipped = run.total_failed = 0
        orchestrator = MagicMock()
        orchestrator.process_payment.side_effect = RuntimeError("stop-2620")
        with patch(
            "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator.get_payment_orchestrator",
            return_value=orchestrator,
        ), patch.object(svc, "_checkpoint"), patch.object(svc, "_cancel_requested", return_value=False):
            svc._process_rows(run)
        self.assertEqual(foreign.row_status, "Failed", "a foreign-account row must not skip the payment")
        self.assertIn("stop-2620", foreign.message)
        self.assertEqual(own.row_status, "Skipped")
        self.assertEqual(own.bank_transaction, own_bt)

    def test_admin_global_retrieval_marks_processed_only_for_the_mollie_account(self):
        from verenigingen.verenigingen_payments.mollie.services import bulk_payment_admin_service as svc

        def payment(pid):
            return SimpleNamespace(
                id=pid, status="paid", amount={"currency": "EUR", "value": "10.00"}, created_at=None,
                paid_at=None, description="x", customer_id=None, subscription_id=None,
            )

        foreign_ref, own_ref = f"{self.ref}f", f"{self.ref}o"
        self.seed_bt("OTHER", OTHER_ACCOUNT, reference=foreign_ref)
        own_bt = self.seed_bt("OWN", MOLLIE_ACCOUNT, reference=own_ref)
        payment_list = MagicMock()
        payment_list.__iter__.return_value = iter([payment(foreign_ref), payment(own_ref)])
        payment_list.has_next.return_value = False
        client = MagicMock()
        client.sdk_client.payments.list.return_value = payment_list
        matcher = MagicMock()
        matcher.find_member_for_payment.return_value = None
        with patch(
            "verenigingen.verenigingen_payments.mollie.core.client.MollieClient", return_value=client
        ), patch(
            "verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher.get_member_payment_matcher",
            return_value=matcher,
        ):
            result = svc._retrieve_global_payments_with_orphans(days_back=3650, max_payments=10, payment_status_filter="all")
        self.assertNotIn("error", result)
        rows = {r["payment_id"]: r for r in result["orphaned_transactions"]}
        self.assertFalse(rows[foreign_ref]["already_processed"])
        self.assertTrue(rows[foreign_ref]["processable"])
        self.assertTrue(rows[own_ref]["already_processed"])
        self.assertEqual(rows[own_ref]["bank_transaction"], own_bt)


class TestBalanceTransactionLookups2620(BankTransactionScopeCase):
    def _transaction(self, payment_id=None):
        context = {"paymentId": payment_id} if payment_id else {}
        return SimpleNamespace(
            id=f"baltr_{self.ref}", type="payment", context=context,
            result_amount=None, initial_amount=None, created_at=None,
            get_total_deductions=lambda: 0,
        )

    def _process(self, transaction):
        from verenigingen.verenigingen_payments.services.balance_transaction_processor import (
            BalanceTransactionProcessor,
        )

        processor = BalanceTransactionProcessor.__new__(BalanceTransactionProcessor)
        return processor._process_single_transaction(transaction)

    def test_foreign_or_cancelled_rows_do_not_make_a_balance_transaction_already_processed(self):
        baltr = f"baltr_{self.ref}"
        payment_ref = f"{self.ref}p"
        cases = {
            "balance id, foreign": dict(reference=baltr, account=OTHER_ACCOUNT, docstatus=1),
            "balance id, cancelled": dict(reference=baltr, account=MOLLIE_ACCOUNT, docstatus=2),
            "payment id, foreign": dict(reference=payment_ref, account=OTHER_ACCOUNT, docstatus=1),
            "payment id, cancelled": dict(reference=payment_ref, account=MOLLIE_ACCOUNT, docstatus=2),
            "transaction_id field, foreign": dict(reference=None, account=OTHER_ACCOUNT, docstatus=1, txid=payment_ref),
            "transaction_id field, cancelled": dict(reference=None, account=MOLLIE_ACCOUNT, docstatus=2, txid=payment_ref),
        }
        for label, case in cases.items():
            with self.subTest(label):
                name = self.seed_bt(
                    "C" + frappe.generate_hash(length=4), case["account"], case["docstatus"],
                    reference=case["reference"] or f"unrelated-{frappe.generate_hash(length=6)}",
                    transaction_id=case.get("txid"),
                )
                self.addCleanup(frappe.db.sql, "DELETE FROM `tabBank Transaction` WHERE name = %s", name)
                result = self._process(self._transaction(payment_id=payment_ref))
                self.assertNotEqual(result["status"], "already_processed", result)
                self.assertNotEqual(result.get("bank_transaction"), name)
                frappe.db.sql("DELETE FROM `tabBank Transaction` WHERE name = %s", name)

    def test_own_live_row_is_already_processed_by_each_strategy(self):
        baltr = f"baltr_{self.ref}"
        payment_ref = f"{self.ref}p"
        for label, kwargs in {
            "balance id": dict(reference=baltr),
            "payment id": dict(reference=payment_ref),
            "transaction_id field": dict(reference=f"unrelated-{self.ref}", transaction_id=payment_ref),
        }.items():
            with self.subTest(label):
                name = self.seed_bt("OWN" + frappe.generate_hash(length=4), MOLLIE_ACCOUNT, **kwargs)
                self.addCleanup(frappe.db.sql, "DELETE FROM `tabBank Transaction` WHERE name = %s", name)
                result = self._process(self._transaction(payment_id=payment_ref))
                self.assertEqual(result["status"], "already_processed", result)
                self.assertEqual(result["bank_transaction"], name)
                frappe.db.sql("DELETE FROM `tabBank Transaction` WHERE name = %s", name)

    def test_status_api_reports_processed_only_for_a_live_mollie_account_row(self):
        from verenigingen.verenigingen_payments.api.balance_transaction_processing import (
            check_transaction_status,
        )

        baltr = f"baltr_{self.ref}"
        self.seed_bt("OTHER", OTHER_ACCOUNT, reference=baltr)
        self.seed_bt("CANCELLED", MOLLIE_ACCOUNT, docstatus=2, reference=baltr)
        self.assertFalse(check_transaction_status(baltr)["processed"])
        own = self.seed_bt("OWN", MOLLIE_ACCOUNT, reference=baltr)
        result = check_transaction_status(baltr)
        self.assertTrue(result["processed"])
        self.assertEqual(result["bank_transaction"]["name"], own)
