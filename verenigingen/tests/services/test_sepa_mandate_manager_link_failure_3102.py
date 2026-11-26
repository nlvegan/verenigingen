"""#3102: create_mandate must not leave the inserted Draft mandate behind when linking fails.

Step 5 inserts the SEPA Mandate, Step 6 links it to the member. When Step 6 raised, the outer
``except Exception`` returned ``ValidationResult.failure`` but the Draft row stayed, so a retry on
the same IBAN met the duplicate-IBAN check.
"""

from unittest.mock import patch

import frappe
import pymysql

from verenigingen.services.payment.sepa_mandate_manager import (
    SEPAMandateManager,
    get_sepa_mandate_manager,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestCreateMandateLinkFailure3102(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.manager = get_sepa_mandate_manager()
        self.member = self.create_test_member(
            first_name="Link",
            last_name="Fail",
            birth_date="1990-01-01",
            email=f"link.fail.{frappe.generate_hash(length=8)}@example.com",
        )
        self.iban = generate_test_iban("RABO", "0123456789")

    def _create(self, mandate_id):
        return self.manager.create_mandate(
            member=self.member.name,
            iban=self.iban,
            account_holder_name="Link Fail",
            mandate_id=mandate_id,
        )

    def _mandates_of_member(self):
        return frappe.get_all("SEPA Mandate", filters={"member": self.member.name}, pluck="name")

    def _link_raising(self, error):
        # Mock justified: fault injection at Step 6 only; Steps 1-5 run for real
        return patch.object(SEPAMandateManager, "_link_mandate_to_member", side_effect=error)

    def test_failed_link_leaves_no_draft_mandate_and_a_retry_succeeds(self):
        mandate_id = f"M-3102-{frappe.generate_hash(length=8)}"
        with self._link_raising(frappe.ValidationError("boom in link")):
            result = self._create(mandate_id)

        self.assertFalse(result.valid)
        self.assertEqual(self._mandates_of_member(), [], "the Draft inserted at Step 5 must be rolled back")
        self.assertFalse(frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id}))

        retry = self._create(f"M-3102-{frappe.generate_hash(length=8)}")
        self.assertTrue(retry.valid, retry.message)
        self.assertEqual(len(self._mandates_of_member()), 1)

    def test_pre_existing_mandate_survives_a_failed_link(self):
        """Control: only the mandate this call inserted goes; an earlier row for the member stays."""
        first = self._create(f"M-3102-{frappe.generate_hash(length=8)}")
        self.assertTrue(first.valid, first.message)
        other_iban = generate_test_iban("INGB", "0987654321")
        with self._link_raising(frappe.ValidationError("boom in link")):
            result = self.manager.create_mandate(
                member=self.member.name,
                iban=other_iban,
                account_holder_name="Link Fail",
                mandate_id=f"M-3102-{frappe.generate_hash(length=8)}",
            )
        self.assertFalse(result.valid)
        self.assertEqual(self._mandates_of_member(), [first.data["mandate_name"]])

    def test_successful_create_still_persists_mandate(self):
        result = self._create(f"M-3102-{frappe.generate_hash(length=8)}")
        self.assertTrue(result.valid, result.message)
        self.assertEqual(self._mandates_of_member(), [result.data["mandate_name"]])

    def test_driver_fault_on_the_member_link_insert_leaves_no_mandate(self):
        """No patch on the manager: the fault is injected at frappe.db.sql, so the Member save in
        Step 6 fails for real. Step 6 is normally a no-op (the SEPA Mandate after_insert hook has
        already linked the row), so the injection also fails the hook's own link, which the hook
        contains; only then does Step 6 find the mandate unlinked and try (and fail) itself.
        """
        real_sql = frappe.db.sql

        def sql(query, *args, **kwargs):
            if "INSERT INTO `tabMember SEPA Mandate Link`" in str(query):
                raise pymysql.err.OperationalError(2013, "injected: lost connection on link insert")
            return real_sql(query, *args, **kwargs)

        # Mock justified: fault injection at the driver boundary; all SQL except the link insert runs
        with patch.object(frappe.db, "sql", sql):
            result = self._create(f"M-3102-{frappe.generate_hash(length=8)}")

        self.assertFalse(result.valid)
        self.assertIn("injected", result.message)
        self.assertEqual(self._mandates_of_member(), [])

    def test_deadlock_from_the_link_step_propagates(self):
        """NON_RESUMABLE branch: a 1213 is re-raised, not flattened into a failure result."""
        with self._link_raising(frappe.QueryDeadlockError("injected deadlock")):
            with self.assertRaises(frappe.QueryDeadlockError):
                self._create(f"M-3102-{frappe.generate_hash(length=8)}")
