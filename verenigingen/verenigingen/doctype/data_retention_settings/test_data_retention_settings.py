import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
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
