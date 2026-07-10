"""Engine-level live-execution gate + guarded custom-policy load.

The layered gate makes live purging reachable ONLY when the global dry_run flag
is off AND the category's live flag is on AND the category is in the code-level
LIVE_CAPABLE_CATEGORIES allowlist. Every assertion is mutation-sensitive.
"""

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    LIVE_CAPABLE_CATEGORIES,
    DataCategory,
    DataRetentionPolicy,
)


class TestDataRetentionEngineGate(VereningingenTestCase):
    def test_only_temporary_data_is_live_capable(self):
        self.assertEqual(LIVE_CAPABLE_CATEGORIES, {DataCategory.TEMPORARY_DATA})

    def test_load_custom_policies_is_noop_without_rows(self):
        # With no configured settings rows, code defaults survive and no live flags set.
        policy = DataRetentionPolicy()
        self.assertEqual(policy.retention_periods[DataCategory.PAYMENT_DATA], 2555)
        self.assertEqual(policy.category_live_flags, {})

    def test_effective_dry_run_gate_blocks_non_capable_even_when_flagged(self):
        # personal_data is NOT live-capable; even fully "live" it must stay dry-run.
        policy = DataRetentionPolicy()
        policy.category_live_flags = {DataCategory.PERSONAL_DATA: True}
        result = policy._process_category(DataCategory.PERSONAL_DATA, dry_run=False)
        # dry-run means it only counts; no member is deleted. Assert via effective flag.
        self.assertTrue(policy._effective_dry_run(DataCategory.PERSONAL_DATA, dry_run=False))

    def test_effective_dry_run_gate_allows_capable_when_flagged(self):
        policy = DataRetentionPolicy()
        policy.category_live_flags = {DataCategory.TEMPORARY_DATA: True}
        self.assertFalse(policy._effective_dry_run(DataCategory.TEMPORARY_DATA, dry_run=False))

    def test_global_dry_run_always_wins(self):
        policy = DataRetentionPolicy()
        policy.category_live_flags = {DataCategory.TEMPORARY_DATA: True}
        self.assertTrue(policy._effective_dry_run(DataCategory.TEMPORARY_DATA, dry_run=True))
