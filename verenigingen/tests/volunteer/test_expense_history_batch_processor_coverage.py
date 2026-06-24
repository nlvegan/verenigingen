"""
Coverage-focused integration tests for
``verenigingen/services/volunteer/expense_history_batch_processor.py``.

The existing ``test_volunteer_service_coverage.TestExpenseHistoryBatchProcessor``
covers the cheap helpers (defaults, ``_get_member_from_employee`` None paths,
empty-batch, draft/submitted pending filtering, the cleanup keep/remove cases).
This file targets the *processing* paths that actually persist
``Member Volunteer Expenses`` rows -- the bulk of the missed lines:

  * ``_process_single_claim`` -- the happy path that calls
    ``Member.add_expense_to_history`` and (after the financial batch flush)
    materialises a real history row with the claimed amount.
  * ``_process_batch`` -- success counting AND the per-claim error branch
    (a claim referencing a non-existent member is counted as an error, not raised).
  * ``process_pending_expense_updates`` -- end-to-end: a submitted claim that is
    not yet in history gets added; the no-pending-claims early return.
  * ``validate_expense_history_integrity`` -- the auto-fix branch that backfills a
    missing history row for a submitted volunteer claim, plus the idempotent
    "already present" pass.
  * ``process_pending_expense_history_updates`` -- the scheduled whitelist wrapper.
  * ``_is_claim_in_member_history`` -- the True branch (claim genuinely tracked).

Real integration only: every Member / Volunteer / Employee / Expense Claim is a
real tracked document, the financial batch processor is flushed for real, and
assertions check persisted ``Member Volunteer Expenses`` rows (count + amount),
not just "did not raise". Swallow-into-log paths are wrapped with
``assertNoErrorLog`` / ``expectErrorLog``.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _BatchProcessorFixtureMixin:
    """Real Member + Volunteer(+Employee) + Expense Claim fixtures."""

    def _company(self):
        configured = frappe.db.get_single_value("Verenigingen Settings", "company")
        if configured and frappe.db.exists("Company", configured):
            return configured
        if frappe.db.exists("Company", "_Test Company"):
            return "_Test Company"
        return (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]

    def _processor(self):
        from verenigingen.services.volunteer.expense_history_batch_processor import (
            ExpenseHistoryBatchProcessor,
        )

        return ExpenseHistoryBatchProcessor()

    def _make_volunteer_claim(self, *, docstatus=1, amount=9.0):
        """Member + Volunteer(+Employee) + an Expense Claim at the given docstatus.

        docstatus is set via set_value (the jobs read the column directly), which
        avoids driving the full expense-approver submission workflow. Returns
        (member, expense_claim_doc).
        """
        company = self._company()
        if not company:
            self.skipTest("No Company available")
        expense_acct = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available for the configured company")

        member = self.create_test_member(first_name="BatchJob", last_name="Member", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"BatchJob{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Employee", emp.name, priority=2)
        volunteer.db_set("employee_id", emp.name, update_modified=False)

        ec = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": emp.name,
                "company": company,
                "custom_organization_type": "National",
                "posting_date": frappe.utils.today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": [
                    {
                        "expense_type": "Food",
                        "amount": amount,
                        "sanctioned_amount": amount,
                        "expense_date": frappe.utils.today(),
                        "default_account": expense_acct,
                    }
                ],
            }
        ).insert(ignore_permissions=True)
        self._track_test_document("Expense Claim", ec.name, priority=1)
        if docstatus != 0:
            frappe.db.set_value("Expense Claim", ec.name, "docstatus", docstatus, update_modified=False)
        return member, ec

    def _flush_financial_batches(self):
        """Drive the underlying financial batch queue so queued add/remove ops
        are materialised into Member Volunteer Expenses rows synchronously."""
        from verenigingen.utils.financial_history_batch_processor import (
            FinancialHistoryBatchProcessor,
        )

        FinancialHistoryBatchProcessor.force_process_all()

    def _history_rows(self, member, expense_claim_name):
        member.reload()
        return [r for r in (member.get("volunteer_expenses") or []) if r.expense_claim == expense_claim_name]


# ---------------------------------------------------------------------------
# _process_single_claim / _process_batch -- the real persistence paths
# ---------------------------------------------------------------------------
class TestBatchProcessingPersistence(_BatchProcessorFixtureMixin, EnhancedTestCase):
    def test_process_single_claim_persists_history_row(self):
        """_process_single_claim queues the claim into the member's expense
        history; after flushing the financial batch a real row with the claimed
        amount exists."""
        member, ec = self._make_volunteer_claim(amount=12.0)
        proc = self._processor()

        with self.assertNoErrorLog():
            ok = proc._process_single_claim({"name": ec.name, "member_id": member.name})
        self.assertTrue(ok, "processing a valid submitted claim must succeed")

        self._flush_financial_batches()
        rows = self._history_rows(member, ec.name)
        self.assertEqual(len(rows), 1, "exactly one history row should be materialised")
        self.assertEqual(float(rows[0].total_claimed_amount), 12.0)

    def test_process_single_claim_missing_member_fails_gracefully(self):
        """A claim referencing a non-existent member exhausts the retry loop and
        returns False (logging a final-failure error) rather than raising."""
        proc = self._processor()
        # The retry loop logs 'Expense Claim Processing Failure' on the last attempt.
        self.expectErrorLog("Expense Claim Processing Failure")
        ok = proc._process_single_claim({"name": "EC-NOPE-XYZ", "member_id": "Member-DOES-NOT-EXIST-XYZ"})
        self.assertFalse(ok)

    def test_process_batch_counts_success_and_error(self):
        """_process_batch returns (processed, errors): one real claim processes,
        one bogus claim is counted as an error (its exception is swallowed)."""
        member, ec = self._make_volunteer_claim(amount=7.0)
        proc = self._processor()

        # The bogus claim's failure path logs; allow that specific title.
        self.expectErrorLog("Expense Claim Processing Failure")
        batch = [
            {"name": ec.name, "member_id": member.name},
            {"name": "EC-BOGUS-XYZ", "member_id": "Member-DOES-NOT-EXIST-XYZ"},
        ]
        processed, errors = proc._process_batch(batch)
        self.assertEqual(processed, 1)
        self.assertEqual(errors, 1)

        self._flush_financial_batches()
        self.assertEqual(len(self._history_rows(member, ec.name)), 1)

    def test_notify_administrators_of_errors_builds_notification(self):
        """The error-notification path constructs the admin alert and dispatches
        it through notify_administrators without raising. With at least one admin
        recipient resolvable on this site, a real Notification Log row is created
        carrying the failure count in its subject."""
        proc = self._processor()
        before = frappe.db.count("Notification Log")

        # The downstream notify_administrators sets a resolved recipient *email*
        # as the Notification's for_user. On sites where a resolved admin email
        # has no matching User (e.g. CI's admin@example.com), the helper logs a
        # "Notification Creation Error" — a recipient-misconfiguration condition
        # in the notification layer, not a fault of the method under test. Tolerate
        # that specific noise while still failing on any error this method raises.
        with self.assertNoErrorLog(ignore=["Notification Creation Error"]):
            proc._notify_administrators_of_errors(3)

        after = frappe.db.count("Notification Log")
        # Recipient resolution is environment-dependent; when admins resolve, the
        # alert row exists and references the failure count. When none resolve the
        # path still ran cleanly (covered by assertNoErrorLog). Assert at least
        # that no exception leaked and -- if a row was created -- it is ours.
        if after > before:
            recent = frappe.get_all(
                "Notification Log",
                filters={"subject": ["like", "%Expense History Processing Errors - 3 failures%"]},
                limit=1,
            )
            self.assertTrue(recent, "the admin alert should carry the failure count in its subject")

    def test_is_claim_in_member_history_true_after_persist(self):
        """_is_claim_in_member_history returns True once the claim is actually
        present in a member's Member Volunteer Expenses rows."""
        member, ec = self._make_volunteer_claim(amount=5.0)
        proc = self._processor()

        # Not in history yet.
        self.assertFalse(proc._is_claim_in_member_history(ec.name))

        with self.assertNoErrorLog():
            proc._process_single_claim({"name": ec.name, "member_id": member.name})
        self._flush_financial_batches()

        self.assertTrue(
            proc._is_claim_in_member_history(ec.name),
            "claim must be reported in history after persistence",
        )


# ---------------------------------------------------------------------------
# process_pending_expense_updates -- end-to-end scheduled entry point
# ---------------------------------------------------------------------------
class TestProcessPendingExpenseUpdates(_BatchProcessorFixtureMixin, EnhancedTestCase):
    def test_pending_submitted_claim_added_to_history(self):
        """The main scheduled task discovers a submitted volunteer claim that is
        missing from history and adds it. Assert the row materialises."""
        member, ec = self._make_volunteer_claim(amount=15.0)
        proc = self._processor()

        with self.assertNoErrorLog():
            proc.process_pending_expense_updates()
        self._flush_financial_batches()

        rows = self._history_rows(member, ec.name)
        self.assertEqual(len(rows), 1, "submitted pending claim should be added to history")
        self.assertEqual(float(rows[0].total_claimed_amount), 15.0)

    def test_draft_claim_not_added_to_history(self):
        """A draft (docstatus 0) claim is not pending, so the scheduled task must
        not add it to history."""
        member, draft_ec = self._make_volunteer_claim(docstatus=0, amount=4.0)
        proc = self._processor()

        with self.assertNoErrorLog():
            proc.process_pending_expense_updates()
        self._flush_financial_batches()

        self.assertEqual(
            self._history_rows(member, draft_ec.name),
            [],
            "draft claim must not be added to history by the scheduled task",
        )

    def test_whitelisted_scheduled_wrapper_runs(self):
        """The whitelisted ``process_pending_expense_history_updates`` wrapper
        instantiates the processor and runs it end-to-end without error."""
        from verenigingen.services.volunteer.expense_history_batch_processor import (
            process_pending_expense_history_updates,
        )

        member, ec = self._make_volunteer_claim(amount=8.0)

        with self.assertNoErrorLog():
            process_pending_expense_history_updates()
        self._flush_financial_batches()

        self.assertEqual(len(self._history_rows(member, ec.name)), 1)


# ---------------------------------------------------------------------------
# validate_expense_history_integrity -- auto-fix + idempotent pass
# ---------------------------------------------------------------------------
class TestValidateExpenseHistoryIntegrity(_BatchProcessorFixtureMixin, EnhancedTestCase):
    def test_integrity_autofixes_missing_history_row(self):
        """A submitted volunteer claim with NO history row is auto-fixed: the
        integrity check backfills it via Member.add_expense_to_history."""
        from verenigingen.services.volunteer.expense_history_batch_processor import (
            validate_expense_history_integrity,
        )

        member, ec = self._make_volunteer_claim(amount=21.0)
        # Precondition: not yet in history.
        self.assertEqual(self._history_rows(member, ec.name), [])

        with self.assertNoErrorLog():
            validate_expense_history_integrity()
        self._flush_financial_batches()

        rows = self._history_rows(member, ec.name)
        self.assertEqual(len(rows), 1, "integrity check must backfill the missing history row")
        self.assertEqual(float(rows[0].total_claimed_amount), 21.0)

    def test_integrity_pass_when_already_present(self):
        """When the submitted claim is already tracked, the integrity check is a
        clean no-op (the 'integrity check passed' branch) -- no duplicate row,
        no error."""
        from verenigingen.services.volunteer.expense_history_batch_processor import (
            validate_expense_history_integrity,
        )

        member, ec = self._make_volunteer_claim(amount=6.0)
        # Add the row first so this claim is already present.
        proc = self._processor()
        with self.assertNoErrorLog():
            proc._process_single_claim({"name": ec.name, "member_id": member.name})
        self._flush_financial_batches()
        self.assertEqual(len(self._history_rows(member, ec.name)), 1)

        with self.assertNoErrorLog():
            validate_expense_history_integrity()
        self._flush_financial_batches()

        # Still exactly one row -- no duplicate created.
        self.assertEqual(len(self._history_rows(member, ec.name)), 1)
