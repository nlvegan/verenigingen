"""#2577: functions that raise ``frappe.flags`` must hand back the CALLER's value.

#2559 fixed the account-creation endpoints. These are the siblings that cleared the flag to
``False`` (or deleted it) on exit, so a caller that already had it True lost it: a nested use
switched off the outer scope's ``in_background_job`` / ``in_import`` /
``bulk_member_operations`` / ``bulk_invoice_generation`` behaviour.

Each case runs twice: the flag True beforehand (must still be True), and absent beforehand
(must be absent again, not left as False).
"""

from types import SimpleNamespace

import frappe

from verenigingen.services.billing.bulk_invoice_generation_service import BulkInvoiceGenerationService
from verenigingen.services.billing.invoice_generation_orchestrator import InvoiceGenerationOrchestrator
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.csv_import_processor import bulk_member_operations
from verenigingen.utils.operation_result import OperationResult

_ABSENT = object()


class FlagRestoreCase(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._tracked = set()

    def tearDown(self):
        for name, before in getattr(self, "_saved", {}).items():
            if before is _ABSENT:
                frappe.flags.pop(name, None)
            else:
                frappe.flags[name] = before
        super().tearDown()

    def _arm(self, names, value):
        """Put every flag in ``names`` in the caller state under test (True or absent)."""
        self._saved = getattr(self, "_saved", {})
        for name in names:
            self._saved.setdefault(name, frappe.flags.get(name, _ABSENT))
            if value is _ABSENT:
                frappe.flags.pop(name, None)
            else:
                frappe.flags[name] = value

    def assert_restored(self, names, call):
        """``call()`` runs with the flags True beforehand, then absent beforehand."""
        for beforehand in (True, _ABSENT):
            self._arm(names, beforehand)
            try:
                call()
            except Exception:
                # Some sites are driven with a doc that does not exist: the exit path is
                # what is under test, not the outcome.
                pass
            for name in names:
                if beforehand is True:
                    self.assertTrue(
                        frappe.flags.get(name),
                        f"{name} was True for the caller and was cleared (#2577)",
                    )
                else:
                    self.assertNotIn(
                        name, frappe.flags, f"{name} was absent for the caller and was left behind (#2577)"
                    )


class TestInvoiceFlagsRestored(FlagRestoreCase):
    def test_orchestrator_restores_in_invoice_generation(self):
        seen = []

        class Orchestrator(InvoiceGenerationOrchestrator):
            def _acquire_lock(self):
                return False, None, "lock"

            def _release_lock(self, *args):
                pass

            def _execute_generation(self):
                seen.append(frappe.flags.get("in_invoice_generation"))
                return OperationResult.ok(None)

        schedule = SimpleNamespace(
            name="SCHED-2577", test_mode=False, can_generate_invoice=lambda: (True, "")
        )
        self.assert_restored(["in_invoice_generation"], lambda: Orchestrator(schedule).generate())
        self.assertEqual(seen, [True, True], "the flag must still be raised while generating")

    def test_orchestrator_restores_when_generation_raises(self):
        class Boom(BaseException):
            """Not an Exception, so generate()'s own except cannot absorb it."""

        class Orchestrator(InvoiceGenerationOrchestrator):
            def _acquire_lock(self):
                return False, None, "lock"

            def _release_lock(self, *args):
                pass

            def _execute_generation(self):
                raise Boom()

        schedule = SimpleNamespace(
            name="SCHED-2577", test_mode=False, can_generate_invoice=lambda: (True, "")
        )

        def call():
            try:
                Orchestrator(schedule).generate()
            except Boom:
                pass

        self.assert_restored(["in_invoice_generation"], call)

    def test_bulk_service_restores_bulk_invoice_generation(self):
        seen = []

        class Service(BulkInvoiceGenerationService):
            def _validate_accounting_configuration(self):
                pass

            def get_eligible_schedules(self, **kwargs):
                return SimpleNamespace(
                    eligible_schedules=[],
                    filtered_members=[],
                    total_filtered=0,
                    summary={"total_schedules_checked": 0},
                )

            def _process_sequential(self, schedules, cutoff_date, test_mode, result):
                seen.append(frappe.flags.get("bulk_invoice_generation"))
                return result

        self.assert_restored(
            ["bulk_invoice_generation"],
            lambda: Service()._execute_invoice_generation(True, SimpleNamespace()),
        )
        self.assertEqual(seen, [True, True], "the flag must still be raised while generating")


class TestBulkMemberOperationsRestored(FlagRestoreCase):
    def test_context_manager_restores_caller_value(self):
        def call():
            with bulk_member_operations("X-2577"):
                self.assertTrue(frappe.flags.bulk_member_operations)

        self.assert_restored(["bulk_member_operations"], call)

    def test_context_manager_restores_on_exception(self):
        def call():
            with bulk_member_operations("X-2577"):
                raise ValueError("boom")

        self.assert_restored(["bulk_member_operations"], call)


class TestQueueRequestsRestored(FlagRestoreCase):
    def test_bulk_queue_requests_restores_bulk_account_creation(self):
        from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
            bulk_queue_requests,
        )

        self.assert_restored(["bulk_account_creation"], lambda: bulk_queue_requests([]))


class TestImportJobsRestored(FlagRestoreCase):
    """The background jobs raise in_background_job & co and never put them back.

    Driven with an import doc that does not exist: the job fails fast, which is a real exit
    path (the failure branch), and the flags must still come back.
    """

    NAME = "NO-SUCH-IMPORT-2577"

    def _job(self, dotted):
        return frappe.get_attr(dotted)

    def test_procurios_membership_import(self):
        fn = self._job(
            "verenigingen.verenigingen.doctype.procurios_membership_import."
            "procurios_membership_import.process_import_background"
        )
        self.assert_restored(
            ["in_background_job", "ignore_version_changes"], lambda: fn(self.NAME)
        )

    def test_procurios_mandate_import(self):
        fn = self._job(
            "verenigingen.verenigingen_payments.doctype.procurios_mandate_import."
            "procurios_mandate_import.process_import_background"
        )
        self.assert_restored(
            ["in_background_job", "ignore_version_changes"], lambda: fn(self.NAME)
        )

    def test_member_import(self):
        fn = self._job(
            "verenigingen.verenigingen.doctype.member_import.member_import.process_import_background"
        )
        self.assert_restored(
            ["in_background_job", "ignore_version_changes"], lambda: fn(self.NAME)
        )

    def test_mijnrood_csv_import(self):
        self.expectErrorLog("CSV Import Background Job Failed")  # the job logs its own failure for the missing doc
        fn = self._job(
            "verenigingen.verenigingen.doctype.mijnrood_csv_import."
            "mijnrood_csv_import.process_import_background"
        )
        self.assert_restored(
            [
                "in_background_job",
                "in_bulk_import",
                "bulk_chapter_operations",
                "bulk_member_operations",
                "ignore_version_changes",
            ],
            lambda: fn(self.NAME),
        )
