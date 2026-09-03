"""Tests for v2_1.add_bank_transaction_reference_unique_index -- same defect class as #746.

Same shape as add_mollie_payment_entry_unique_index: the patch used to log a warning and
return normally when duplicate reference_number values already existed, which Frappe's
patch handler records as a completed patch. Confirmed to have actually happened on
test_site_3: the patch was recorded as executed, the index did not exist, and no
duplicates remained -- calling execute() directly created the index immediately with no
data changes, meaning the original run must have hit (now-resolved) duplicates and gotten
permanently marked done regardless. See #746's report on the sibling Mollie patch.

A skeptical review found this test file RED on test_site_1: 6 leaked `Bank Transaction`
rows with `reference_number='REF123'` from earlier, unrelated test runs made
`test_creates_index_once_duplicates_are_gone` and `test_skips_cleanly_when_index_already_exists`
fail with a raw MySQL 1062 (the same leaked-shared-site-data class this repo has hit
repeatedly -- see memory: "local green came from leaked test companies"). The Mollie test
file already defended against this; this one didn't. `_clean_leaked_duplicate_bank_transactions`
below closes that gap.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_1.add_bank_transaction_reference_unique_index import execute

INDEX_NAME = "idx_reference_number_unique"


class TestAddBankTransactionReferenceUniqueIndex(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self._drop_index_if_present()
        self._clean_leaked_duplicate_bank_transactions()
        self.inserted_names = []

    def tearDown(self):
        for name in self.inserted_names:
            frappe.db.sql("DELETE FROM `tabBank Transaction` WHERE name = %s", [name])
        frappe.db.commit()
        self._drop_index_if_present()
        super().tearDown()

    def _clean_leaked_duplicate_bank_transactions(self):
        """Remove leaked test-data Bank Transactions from earlier, unrelated runs.

        Confirmed on test_site_1: 6 rows with `reference_number='REF123'`, leaked by
        earlier tests, made `execute()` raise on a table this test never touched --
        exactly the (reference_number) group `_find_duplicates()` reacts to. Queries the
        same duplicate groups the patch itself would find, then read-then-confirms zero
        `Bank Transaction Payments` (the reconciliation link to Payment Entry) reference
        each group before deleting it. A group with any reconciliation link is left
        alone for a human.
        """
        from verenigingen.patches.v2_1.add_bank_transaction_reference_unique_index import (
            _find_duplicates,
        )

        for dup in _find_duplicates():
            names = frappe.db.sql_list(
                "SELECT name FROM `tabBank Transaction` WHERE reference_number = %s",
                (dup.reference_number,),
            )
            placeholders = ", ".join(["%s"] * len(names))
            linked_payment_count = frappe.db.sql(
                f"""
                SELECT COUNT(*) FROM `tabBank Transaction Payments`
                WHERE parent IN ({placeholders})
                """,
                names,
            )[0][0]
            if linked_payment_count:
                continue

            frappe.db.sql(f"DELETE FROM `tabBank Transaction` WHERE name IN ({placeholders})", names)

        frappe.db.commit()

    def _drop_index_if_present(self):
        if self._index_exists():
            frappe.db.sql_ddl(f"ALTER TABLE `tabBank Transaction` DROP INDEX `{INDEX_NAME}`")

    def _index_exists(self):
        return bool(
            frappe.db.sql(
                "SHOW INDEX FROM `tabBank Transaction` WHERE Key_name = %s",
                [INDEX_NAME],
            )
        )

    def _insert_bank_transaction(self, reference_number):
        name = f"BT-746-TEST-{frappe.generate_hash(length=10)}"
        frappe.db.sql(
            "INSERT INTO `tabBank Transaction` (name, docstatus, idx, reference_number) VALUES (%s, 0, 0, %s)",
            (name, reference_number),
        )
        self.inserted_names.append(name)
        return name

    def test_raises_instead_of_silently_returning_when_duplicates_exist(self):
        reference_number = f"746-test-{frappe.generate_hash(length=8)}"
        self._insert_bank_transaction(reference_number)
        self._insert_bank_transaction(reference_number)

        with self.assertRaises(Exception):
            execute()

        self.assertFalse(
            self._index_exists(),
            "index must not be created while duplicates remain unresolved",
        )

    def test_blank_reference_number_duplicates_also_block_creation(self):
        """A skeptical review found `_find_duplicates()` used to exclude blank
        `reference_number` from its check (`AND reference_number != ''`), while the
        real unique index does NOT exempt '' -- only NULL is exempt in MariaDB/InnoDB.
        Two blank-reference rows must be caught here, not let through to a raw MySQL
        1062 at the real ALTER TABLE.
        """
        self._insert_bank_transaction("")
        self._insert_bank_transaction("")

        with self.assertRaises(Exception):
            execute()

        self.assertFalse(self._index_exists())

    def test_creates_index_once_duplicates_are_gone(self):
        reference_number = f"746-test-{frappe.generate_hash(length=8)}"
        dup_a = self._insert_bank_transaction(reference_number)
        self._insert_bank_transaction(reference_number)

        with self.assertRaises(Exception):
            execute()

        frappe.db.sql("DELETE FROM `tabBank Transaction` WHERE name = %s", [dup_a])
        self.inserted_names.remove(dup_a)
        frappe.db.commit()

        execute()  # must not raise now

        self.assertTrue(self._index_exists())

    def test_skips_cleanly_when_index_already_exists(self):
        frappe.db.sql_ddl(
            f"ALTER TABLE `tabBank Transaction` ADD UNIQUE INDEX `{INDEX_NAME}` (`reference_number`)"
        )

        execute()  # must not raise

        self.assertTrue(self._index_exists())
