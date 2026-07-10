"""
Data Retention Policy — SEPA Mandate coverage.

SEPA Mandate stores IBAN / BIC / account-holder-name PII, so it must be a
first-class category in ``DataRetentionPolicy``. These tests pin the *wiring*:

- ``MANDATE_DATA`` resolves to the ``SEPA Mandate`` DocType,
- a retention period AND action exist so the engine can iterate the category
  without ``KeyError`` (``apply_retention_policies`` / ``get_retention_report``
  loop over *every* ``DataCategory`` member),
- record counting and legal-hold detection route through the mapping to the
  real ``SEPA Mandate`` table.

The retention *period* value and anonymization specifics are PROVISIONAL /
deferred (see the comments in ``data_retention_policy.py``); these tests assert
the plumbing, not the final numbers. Every assertion here is mutation-sensitive
to the mapping/config added for SEPA Mandate (removing the mapping line or the
period/action entry turns a test red).
"""

import frappe
from frappe.utils import now_datetime

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    DataRetentionPolicy,
    RetentionAction,
)


class TestDataRetentionPolicySepaMandate(VereningingenTestCase):
    """SEPA Mandate must be covered by the data retention policy."""

    def setUp(self):
        super().setUp()
        self.policy = DataRetentionPolicy()

    def test_mandate_data_category_maps_to_sepa_mandate(self):
        """MANDATE_DATA must resolve to the 'SEPA Mandate' DocType."""
        self.assertEqual(
            self.policy._category_to_doctype(DataCategory.MANDATE_DATA),
            "SEPA Mandate",
        )

    def test_mandate_category_fully_configured_for_engine(self):
        """A period AND action must exist, else the engine KeyErrors on iteration."""
        self.assertIn(DataCategory.MANDATE_DATA, self.policy.retention_periods)
        self.assertIn(DataCategory.MANDATE_DATA, self.policy.retention_actions)
        # IBAN/BIC PII must be scrubbed on expiry — anonymize, not a bare delete
        # that would drop the legal/audit row, nor an archive that keeps the PII.
        self.assertEqual(
            self.policy.retention_actions[DataCategory.MANDATE_DATA],
            RetentionAction.ANONYMIZE,
        )

    def test_process_category_mandate_data_does_not_crash(self):
        """The engine can dry-run the new category without raising."""
        result = self.policy._process_category(DataCategory.MANDATE_DATA, dry_run=True)
        self.assertEqual(result["category"], "mandate_data")
        self.assertEqual(result["action"], "anonymize")
        # A provisional (placeholder) period is wired; the exact value is deferred.
        self.assertGreater(result["retention_days"], 0)

    def test_count_category_records_routes_to_sepa_mandate_table(self):
        """Counting MANDATE_DATA must count real SEPA Mandate rows via the mapping."""
        mandate = self.create_test_sepa_mandate()

        counted = self.policy._count_category_records(DataCategory.MANDATE_DATA)

        # If the mapping were missing, _category_to_doctype returns "" and the
        # count short-circuits to 0 — this equality would then fail.
        self.assertEqual(counted, frappe.db.count("SEPA Mandate"))
        self.assertGreaterEqual(counted, 1)
        self.assertTrue(frappe.db.exists("SEPA Mandate", mandate.name))

    def test_legal_hold_on_sepa_mandate_detected_via_mapping(self):
        """A legal hold on a real SEPA Mandate is found through the category mapping."""
        mandate = self.create_test_sepa_mandate()

        self.policy.add_legal_hold(
            hold_id="test-mandate-retention-hold",
            doctype="SEPA Mandate",
            filters={"name": mandate.name},
            reason="unit test — retention mapping",
        )

        # _check_legal_holds resolves MANDATE_DATA -> "SEPA Mandate" and queries it;
        # a broken mapping yields "" != "SEPA Mandate" and the hold is skipped.
        held = self.policy._check_legal_holds(DataCategory.MANDATE_DATA, now_datetime())
        self.assertIn(mandate.name, held)
        self.assertTrue(self.policy._is_on_legal_hold("SEPA Mandate", mandate.name))
