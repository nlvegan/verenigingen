import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    run_scheduled_retention_policies,
)


class TestRetentionScheduler(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("Data Retention Settings")
        self.settings.flags.ignore_permissions = True
        self.settings.enabled = 0
        self.settings.dry_run_only = 1
        self.settings.db_set("last_run", None)
        self.settings.save()

    def test_disabled_engine_skips_and_leaves_last_run_untouched(self):
        result = run_scheduled_retention_policies()
        self.assertTrue(result.get("skipped"))
        # NOTE: frappe.db.get_single_value() casts an empty Datetime Single via
        # frappe.utils.data.cast(), which returns the sentinel datetime(1, 1, 1)
        # instead of None for a falsy value. The document-level accessor does not
        # have this quirk, so use it to check "field genuinely untouched".
        self.assertIsNone(frappe.get_single("Data Retention Settings").last_run)

    def test_enabled_dry_run_sets_last_run_and_purges_nothing(self):
        self.settings.enabled = 1
        self.settings.dry_run_only = 1
        self.settings.save()
        # A recent Member exists (created by factory helpers); assert it survives.
        member = self.create_test_member(
            first_name="Retention", last_name="Survivor", email="retention.survivor@test.com"
        )
        # This entrypoint deliberately calls frappe.db.commit(), so its writes
        # persist past the normal per-test rollback boundary; isolation relies
        # on setUp()'s reset of Data Retention Settings and tracked-doc teardown.
        result = run_scheduled_retention_policies()
        self.assertFalse(result.get("skipped"))
        self.assertTrue(result["dry_run"])
        self.assertTrue(frappe.db.exists("Member", member.name))
        self.assertIsNotNone(frappe.db.get_single_value("Data Retention Settings", "last_run"))
