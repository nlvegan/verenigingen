"""The backfill patch's duplicate detection and its refusal to proceed (#1267, #809).

#746/#1267 are what a quiet decline costs: the old v2_1 patch logged a warning, returned
normally, was recorded as executed, and the guarantee stayed absent on most sites for months.
These tests pin the two properties that prevent a repeat -- the detector SEES a duplicate, and
the abort RAISES while naming it.

They exercise the detector and the abort directly rather than calling `execute()`. DDL
autocommits, so a test that ran the whole patch would leave a column and a unique index
behind after the transaction rolled back -- the orphan state that Frappe's schema sync later
drops silently, which is the very failure mode this issue exists to avoid creating.
"""

import frappe

from verenigingen.patches.v2_2 import enforce_unique_bank_transaction_reference as patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils import bank_transaction_reference_key as key_module


class TestBankTransactionReferenceBackfill(EnhancedTestCase):
    def _seed(self, name, bank_account, reference_number, docstatus=1):
        frappe.db.sql(
            """INSERT INTO `tabBank Transaction`
               (name, creation, modified, owner, modified_by, docstatus,
                bank_account, reference_number)
               VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', %s, %s, %s)""",
            (name, docstatus, bank_account, reference_number),
        )
        self.addCleanup(frappe.db.sql, "DELETE FROM `tabBank Transaction` WHERE name = %s", name)

    def test_detector_finds_a_duplicate_on_one_account(self):
        ref = f"PROBE-{frappe.generate_hash()[:10]}"
        self._seed("TEST-1267-DUP-A", "PROBE-Bank Account 1", ref)
        self._seed("TEST-1267-DUP-B", "PROBE-Bank Account 1", ref)

        groups = {(d.bank_account, d.reference_number): d.count for d in patch._find_duplicates()}
        self.assertEqual(groups.get(("PROBE-Bank Account 1", ref)), 2)

    def test_detector_counts_a_cancelled_row(self):
        # A unique index has no docstatus predicate, so a cancelled Bank Transaction still
        # occupies the key.
        ref = f"PROBE-{frappe.generate_hash()[:10]}"
        self._seed("TEST-1267-CANC-A", "PROBE-Bank Account 1", ref, docstatus=1)
        self._seed("TEST-1267-CANC-B", "PROBE-Bank Account 1", ref, docstatus=2)

        groups = {(d.bank_account, d.reference_number): d.count for d in patch._find_duplicates()}
        self.assertEqual(groups.get(("PROBE-Bank Account 1", ref)), 2)

    def test_detector_ignores_the_same_reference_on_two_different_accounts(self):
        # The whole reason the index is scoped per account (#383, #1267): different banks
        # do not coordinate reference numbering. If this test fails the scope has widened
        # back to global and the patch will refuse to run on any real site.
        ref = f"PROBE-{frappe.generate_hash()[:10]}"
        self._seed("TEST-1267-OK-A", "PROBE-Bank Account 1", ref)
        self._seed("TEST-1267-OK-B", "PROBE-Bank Account 2", ref)

        groups = {(d.bank_account, d.reference_number): d.count for d in patch._find_duplicates()}
        self.assertNotIn(("PROBE-Bank Account 1", ref), groups)
        self.assertNotIn(("PROBE-Bank Account 2", ref), groups)

    def test_detector_ignores_repeated_blank_references_on_one_account(self):
        # Blanks are exempt by decision (MT940 NONREF, member_management.py, etc default
        # to ""). If this test fails the exemption has been lost and the patch will refuse
        # to run on every site with more than one blank-reference transaction per account.
        self._seed("TEST-1267-BLANK-A", "PROBE-Bank Account 1", "")
        self._seed("TEST-1267-BLANK-B", "PROBE-Bank Account 1", "")

        groups = {(d.bank_account, d.reference_number): d.count for d in patch._find_duplicates()}
        self.assertNotIn(("PROBE-Bank Account 1", ""), groups)

    def test_abort_raises_and_names_the_offending_group(self):
        duplicates = [
            frappe._dict(bank_account="PROBE-Bank Account 1", reference_number="REF123", count=42)
        ]
        # _abort_on_duplicates logs before it raises; declare it so the harness's
        # "errors logged during test" guard does not treat it as an unexpected error.
        self.expectErrorLog("Bank Transaction reference key: duplicates block unique index")
        with self.assertRaises(frappe.ValidationError) as caught:
            patch._abort_on_duplicates(duplicates)

        message = str(caught.exception)
        self.assertIn("PROBE-Bank Account 1", message)
        self.assertIn("REF123", message)
        self.assertIn("x42", message)
        # It must say what to do next: this patch stays unrecorded and retries, which is
        # the whole difference from #746/#1267's silent success.
        self.assertIn("bench migrate", message)

    def test_patch_and_hook_derive_the_key_with_the_same_function(self):
        # The patch and the validate hook must derive the SAME key, or a backfilled row and
        # a freshly saved one would occupy two different slots for one (account, reference).
        # This asserts identity, not equality on a sample: a re-implementation inside the
        # patch would pass any corpus test the day it was written and drift afterwards.
        self.assertIs(patch.build_reference_key, key_module.build_reference_key)
        self.assertIs(
            key_module.set_bank_transaction_reference_key.__globals__["build_reference_key"],
            key_module.build_reference_key,
        )

    def test_backfill_writes_the_derived_key_and_exempts_blanks(self):
        in_scope_ref = f"PROBE-{frappe.generate_hash()[:10]}"
        self._seed("TEST-1267-BF-A", "PROBE-Bank Account 1", in_scope_ref)
        self._seed("TEST-1267-BF-BLANK", "PROBE-Bank Account 1", "")

        patch._backfill()

        self.assertEqual(
            frappe.db.get_value("Bank Transaction", "TEST-1267-BF-A", key_module.FIELDNAME),
            key_module.build_reference_key("PROBE-Bank Account 1", in_scope_ref),
        )
        self.assertIsNone(
            frappe.db.get_value("Bank Transaction", "TEST-1267-BF-BLANK", key_module.FIELDNAME)
        )

    def _index_exists(self, index_name):
        return bool(
            frappe.db.sql(
                "SHOW INDEX FROM `tabBank Transaction` WHERE Key_name = %s", index_name
            )
        )

    def test_drop_legacy_global_index_removes_it_when_present(self):
        # A site where the retired v2_1 patch already created its global unique index
        # (test_site_3, per #1267's own measurement) must not be left with BOTH that
        # stricter constraint and this patch's per-account one.
        self.assertFalse(
            self._index_exists(patch.LEGACY_GLOBAL_INDEX),
            "test setup assumption violated: the legacy index already exists on this site",
        )
        # Matches the retired v2_1 patch's exact statement (no prefix length -- #1267's
        # own investigation measured that this succeeds against a real TEXT column here).
        frappe.db.sql_ddl(
            f"ALTER TABLE `tabBank Transaction` ADD UNIQUE INDEX `{patch.LEGACY_GLOBAL_INDEX}` (`reference_number`)"
        )
        self.addCleanup(self._drop_index_if_present, patch.LEGACY_GLOBAL_INDEX)
        self.assertTrue(self._index_exists(patch.LEGACY_GLOBAL_INDEX))

        patch._drop_legacy_global_index()

        self.assertFalse(self._index_exists(patch.LEGACY_GLOBAL_INDEX))

    def _drop_index_if_present(self, index_name):
        if self._index_exists(index_name):
            frappe.db.sql_ddl(f"ALTER TABLE `tabBank Transaction` DROP INDEX `{index_name}`")

    def test_drop_legacy_global_index_is_a_noop_when_absent(self):
        self.assertFalse(self._index_exists(patch.LEGACY_GLOBAL_INDEX))
        # Must not raise (e.g. a bare DROP INDEX on a name that does not exist).
        patch._drop_legacy_global_index()
        self.assertFalse(self._index_exists(patch.LEGACY_GLOBAL_INDEX))
