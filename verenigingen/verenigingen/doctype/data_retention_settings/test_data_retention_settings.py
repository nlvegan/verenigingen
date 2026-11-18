import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
    run_scheduled_retention_policies,
)


class TestDataRetentionSettings(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("Data Retention Settings")
        # Start from a known clean state for each test.
        self.settings.set("category_policies", [])
        self.settings.enabled = 0
        self.settings.dry_run_only = 1
        self.settings.flags.ignore_permissions = True
        self.settings.save()

    def _seed(self):
        self.settings.reset_category_policies()
        self.settings.reload()

    def test_reset_seeds_nine_rows_from_defaults(self):
        self._seed()
        rows = self.settings.category_policies
        self.assertEqual(len(rows), 9)
        payment = next(r for r in rows if r.category == "payment_data")
        self.assertEqual(payment.retention_days, 2555)
        self.assertEqual(payment.action, "anonymize")
        self.assertEqual(payment.live_enabled, 0)

    def test_save_does_not_reseed_after_row_removed(self):
        self._seed()
        self.settings.set("category_policies", self.settings.category_policies[:-1])
        self.settings.save()
        self.settings.reload()
        self.assertEqual(len(self.settings.category_policies), 8)

    def test_duplicate_category_rejected(self):
        self.settings.append(
            "category_policies", {"category": "payment_data", "retention_days": 100, "action": "review"}
        )
        self.settings.append(
            "category_policies", {"category": "payment_data", "retention_days": 200, "action": "review"}
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.save()

    def test_retention_days_below_minimum_rejected(self):
        self.settings.append(
            "category_policies", {"category": "payment_data", "retention_days": 10, "action": "review"}
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.save()

    def test_live_enabled_on_non_capable_category_rejected(self):
        self.settings.append(
            "category_policies",
            {"category": "personal_data", "retention_days": 1095, "action": "delete", "live_enabled": 1},
        )
        with self.assertRaises(frappe.ValidationError):
            self.settings.save()

    def test_live_enabled_on_capable_category_allowed(self):
        self.settings.append(
            "category_policies",
            {"category": "temporary_data", "retention_days": 30, "action": "delete", "live_enabled": 1},
        )
        self.settings.save()  # must not raise
        self.assertEqual(len(self.settings.category_policies), 1)

    def test_custom_period_flows_into_engine(self):
        self._seed()
        payment = next(r for r in self.settings.category_policies if r.category == "payment_data")
        payment.retention_days = 999
        self.settings.save()
        policy = DataRetentionPolicy()
        self.assertEqual(policy.retention_periods[DataCategory.PAYMENT_DATA], 999)
        # seeded defaults set live_enabled=0 everywhere -> flag loaded as False
        self.assertFalse(policy.category_live_flags[DataCategory.PAYMENT_DATA])


class TestStaleSettingsSaveKeepsRunStatus2739(VereningingenTestCase):
    """#2739: a form loaded BEFORE a scheduled run must not roll the run status back.

    The weekly job writes ``last_run`` / ``last_run_summary`` with
    ``set_single_value(update_modified=False)``, so ``modified`` does not move and
    Frappe's stale-save check cannot refuse a stale Single save, which rewrites every
    tabSingles row from the in-memory doc. The writer is the REAL ``run_scheduled_retention_policies``
    (disabled by default, so no policy runs): the second branch writes an ERROR summary,
    which is forced by making ``apply_retention_policies`` raise.
    """

    DOCTYPE = "Data Retention Settings"

    def _raw_retention_single_2739(self, field):
        row = frappe.db.sql(
            "SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s", (self.DOCTYPE, field)
        )
        return row[0][0] if row else None

    def _run_the_job_after_loading_a_stale_doc(self):
        from unittest.mock import patch

        settings = frappe.get_single(self.DOCTYPE)
        settings.enabled = 1
        settings.save()
        frappe.db.set_single_value(
            self.DOCTYPE,
            {"last_run": "2020-01-01 00:00:00", "last_run_summary": "old"},
            update_modified=False,
        )
        frappe.clear_document_cache(self.DOCTYPE, self.DOCTYPE)
        stale = frappe.get_doc(self.DOCTYPE)  # the form open in a browser tab
        self.expectErrorLog("Data retention run failed")  # the forced failure logs it on purpose
        self.assertEqual(stale.last_run_summary, "old")
        # boundary stub: the retention engine itself; the writer under test is the job's own
        with patch.object(DataRetentionPolicy, "apply_retention_policies", side_effect=RuntimeError("boom")):
            with patch.object(frappe.db, "commit"):
                run_scheduled_retention_policies()
        return stale

    def test_stale_save_does_not_roll_back_the_run_summary(self):
        stale = self._run_the_job_after_loading_a_stale_doc()
        written = self._raw_retention_single_2739("last_run_summary")
        self.assertEqual(written, "ERROR: boom")
        stale.save()
        self.assertEqual(self._raw_retention_single_2739("last_run_summary"), written)

    def test_stale_save_does_not_roll_back_last_run(self):
        stale = self._run_the_job_after_loading_a_stale_doc()
        written = self._raw_retention_single_2739("last_run")
        self.assertNotIn("2020-01-01", str(written))
        stale.save()
        self.assertEqual(self._raw_retention_single_2739("last_run"), written)

    def test_control_a_stale_save_still_writes_what_staff_edit(self):
        """Control: only the job-owned fields are re-read; a staff edit still lands."""
        stale = self._run_the_job_after_loading_a_stale_doc()
        stale.dry_run_only = 0
        stale.save()
        self.assertEqual(int(self._raw_retention_single_2739("dry_run_only")), 0)
        self.assertEqual(self._raw_retention_single_2739("last_run_summary"), "ERROR: boom")
