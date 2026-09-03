"""Tests for v2_1.add_mollie_payment_entry_unique_index (#746).

The patch is supposed to create `idx_mollie_payment_ref_unique` on `tabPayment Entry`,
the DB-level backstop for Mollie webhook idempotency. Before this fix, when duplicate
Mollie-style references already existed, the patch printed a warning, logged an Error
Log entry, and returned normally -- which Frappe's patch handler records as a completed
patch (see frappe.modules.patch_handler.execute_patch: `update_patch_log()` only runs
when `execute()` does NOT raise). That left the index missing FOREVER on any site that
had duplicates at patch time, with no way to retry short of manually deleting the
`Patch Log` row -- confirmed on veg11 and test_site_1 (#746), and reproduced fresh here
on test_site_3.

The fix makes `execute()` raise instead of returning when duplicates block the index, so
the patch is never recorded as done until it actually succeeds -- the same pattern this
app already uses in v2_2.enforce_unique_user_per_member / enforce_unique_volunteer_per_member.

See the KNOWN LIMITATION in the patch's module docstring: the duplicate pre-check only
screens Mollie-style references, matching #746's own scope. `test_non_mollie_duplicate_
is_not_diagnosed_but_still_blocks_creation` and `test_blank_reference_no_duplicate_is_
not_diagnosed_but_still_blocks_creation` pin that gap down as an intentional, honest
trade-off -- both real shapes measured on veg11 (214 non-Mollie groups; 7 blank-reference
groups) -- rather than a silent regression: the index still doesn't get created, but the
failure is loud and the patch stays retriable, which is what #746 asks for. A generated-
column technique that closed this gap entirely was built, verified in isolation, and then
found to be actively unsafe: Frappe's own schema sync silently strips a unique index on
any column not declared in DocType/Custom Field metadata on the very next `bench migrate`
that syncs customizations -- reproducing #746's failure mode in a sneakier form. See #809.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_1.add_mollie_payment_entry_unique_index import execute

INDEX_NAME = "idx_mollie_payment_ref_unique"


class TestAddMollieePaymentEntryUniqueIndex(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self._drop_index_if_present()
        self._clean_leaked_mollie_style_test_data()
        self.inserted_names = []

    def tearDown(self):
        for name in self.inserted_names:
            frappe.db.sql("DELETE FROM `tabPayment Entry` WHERE name = %s", [name])
        frappe.db.commit()
        self._drop_index_if_present()
        super().tearDown()

    def _clean_leaked_mollie_style_test_data(self):
        """Remove leaked Mollie-style test Payment Entries from earlier, unrelated runs.

        #746 documented `tr_webhook_test_12345` x-many and `tr_donation_test_*` rows
        leaked onto veg11 and test_site_1; the same shape (7 rows, docstatus=1, all
        named `tr_webhook_test_12345`) was found here on test_site_3. That is exactly
        the (reference_no, payment_type, party) group `_find_duplicates()` reacts to, so
        a test asserting "the index gets created once duplicates are resolved" cannot
        pass while it sits on the table.

        Scoped to the same Mollie-style population the pre-check itself is scoped to --
        NOT "every duplicate currently on the table" (a non-Mollie duplicate is a
        different, intentionally out-of-scope case -- see the two "is_not_diagnosed"
        tests below). Read-then-confirms zero GL Entry references before deleting --
        these are all Administrator-owned, no-ledger-impact fixtures, not live
        financial records. A group with any GL Entry is left alone for a human.
        """
        from verenigingen.patches.v2_1.add_mollie_payment_entry_unique_index import (
            _find_duplicates,
        )

        for dup in _find_duplicates():
            names = frappe.db.sql_list(
                """
                SELECT name FROM `tabPayment Entry`
                WHERE reference_no = %s AND payment_type = %s AND party = %s AND docstatus != 2
                """,
                (dup.reference_no, dup.payment_type, dup.party),
            )
            placeholders = ", ".join(["%s"] * len(names))
            gl_entry_count = frappe.db.sql(
                f"""
                SELECT COUNT(*) FROM `tabGL Entry`
                WHERE voucher_type = 'Payment Entry' AND voucher_no IN ({placeholders})
                """,
                names,
            )[0][0]
            if gl_entry_count:
                continue

            frappe.db.sql(f"DELETE FROM `tabPayment Entry` WHERE name IN ({placeholders})", names)

        frappe.db.commit()

    def _drop_index_if_present(self):
        if self._index_exists():
            frappe.db.sql_ddl(f"DROP INDEX `{INDEX_NAME}` ON `tabPayment Entry`")

    def _index_exists(self):
        return bool(
            frappe.db.sql(
                "SHOW INDEX FROM `tabPayment Entry` WHERE Key_name = %s",
                [INDEX_NAME],
            )
        )

    def _insert_payment_entry(self, reference_no, party, payment_type="Receive", docstatus=0):
        name = f"PE-746-TEST-{frappe.generate_hash(length=10)}"
        frappe.db.sql(
            """
            INSERT INTO `tabPayment Entry`
                (name, docstatus, idx, payment_type, party, reference_no)
            VALUES (%s, %s, 0, %s, %s, %s)
            """,
            (name, docstatus, payment_type, party, reference_no),
        )
        self.inserted_names.append(name)
        return name

    def test_raises_instead_of_silently_returning_when_duplicates_exist(self):
        """The core #746 regression: a bail-out must not look like success.

        Before the fix, `execute()` returned `None` here -- indistinguishable from the
        "index already exists" or "nothing to do" success paths, and (in the real
        Frappe patch handler, not exercised by this direct call) that return value is
        exactly what causes the patch to be permanently marked executed. Asserting a
        raise is what actually distinguishes "blocked" from "done".
        """
        reference_no = f"tr_746_test_{frappe.generate_hash(length=8)}"
        party = f"Test Party 746 {frappe.generate_hash(length=6)}"
        self._insert_payment_entry(reference_no, party)
        self._insert_payment_entry(reference_no, party)

        with self.assertRaises(Exception):
            execute()

        self.assertFalse(
            self._index_exists(),
            "index must not be created while duplicates remain unresolved",
        )

    def test_cancelled_and_active_duplicate_is_diagnosed_not_a_raw_ddl_error(self):
        """A cancelled Payment Entry still collides with the unique index.

        An earlier version of `_find_duplicates()` excluded docstatus == 2 on the
        theory that "a cancelled entry is not a live conflict" -- true for the
        application's business logic, false for what MariaDB's unique index actually
        enforces (it has no concept of docstatus). One active (docstatus=1) and one
        cancelled (docstatus=2) Payment Entry sharing a Mollie-style reference must
        still be caught by `_find_duplicates()` and reported via the friendly
        `_abort_on_duplicates()` message -- not surface as an unlogged raw MySQL 1062
        from the real `CREATE UNIQUE INDEX`, which is what happened before this fix.
        """
        reference_no = f"tr_746_test_{frappe.generate_hash(length=8)}"
        party = f"Test Party 746 {frappe.generate_hash(length=6)}"
        self._insert_payment_entry(reference_no, party, docstatus=1)
        self._insert_payment_entry(reference_no, party, docstatus=2)

        with self.assertRaises(Exception) as ctx:
            execute()

        self.assertIn(
            "Cannot create unique index",
            str(ctx.exception),
            "must be the friendly diagnostic, not a raw MySQL error",
        )
        self.assertFalse(self._index_exists())

    def test_creates_index_once_duplicates_are_gone(self):
        """Confirms the patch is genuinely re-runnable, not merely loud."""
        reference_no = f"tr_746_test_{frappe.generate_hash(length=8)}"
        party = f"Test Party 746 {frappe.generate_hash(length=6)}"
        dup_a = self._insert_payment_entry(reference_no, party)
        self._insert_payment_entry(reference_no, party)

        with self.assertRaises(Exception):
            execute()

        # Resolve the duplicate the way an operator would: remove the extra row.
        frappe.db.sql("DELETE FROM `tabPayment Entry` WHERE name = %s", [dup_a])
        self.inserted_names.remove(dup_a)
        frappe.db.commit()

        execute()  # must not raise now

        self.assertTrue(self._index_exists())

    def test_non_mollie_duplicate_is_not_diagnosed_but_still_blocks_creation(self):
        """Pins down the KNOWN LIMITATION from the patch's module docstring.

        A non-Mollie duplicate is intentionally invisible to `_find_duplicates()` (see
        MOLLIE_STYLE_CONDITION) -- widening that check to catch it was tried and found
        to make the index permanently uncreatable on veg11, where 214 such groups are
        legitimate, intentional data (invoice numbers, payroll batch references), not a
        "resolve by hand" problem. So this duplicate is NOT reported nicely -- but
        `execute()` must still raise, via the real `CREATE UNIQUE INDEX` colliding, and
        must still leave the patch retriable (no index created). The failure must never
        be silent; it's fine for it to be less friendly.
        """
        self._insert_payment_entry("INV-001", "Some Customer")
        self._insert_payment_entry("INV-001", "Some Customer")

        with self.assertRaises(Exception):
            execute()

        self.assertFalse(self._index_exists())

    def test_blank_reference_no_duplicate_is_not_diagnosed_but_still_blocks_creation(self):
        """Same shape as the non-Mollie test above, for the second real pattern found on
        veg11: 7 groups of Payment Entries sharing a blank reference_no and the same
        (payment_type, party). A blank reference_no can never match
        MOLLIE_STYLE_CONDITION, so `_find_duplicates()` never sees it either -- the real
        index creation is still the backstop that turns this into a loud, retriable
        failure rather than a false "success".
        """
        self._insert_payment_entry("", "Blank Ref Customer")
        self._insert_payment_entry("", "Blank Ref Customer")

        with self.assertRaises(Exception):
            execute()

        self.assertFalse(self._index_exists())

    def test_ddl_still_rejects_a_mollie_duplicate_the_precheck_missed(self):
        """Defense-in-depth: the real unique index is the backstop, not just the Python
        precheck. Stubs `_find_duplicates` to report nothing while two genuine
        Mollie-style duplicates sit on the table, proving the actual `CREATE UNIQUE
        INDEX` still fails rather than silently creating a broken/incomplete index.
        """
        reference_no = f"tr_746_test_{frappe.generate_hash(length=8)}"
        party = f"Test Party 746 {frappe.generate_hash(length=6)}"
        self._insert_payment_entry(reference_no, party)
        self._insert_payment_entry(reference_no, party)

        module_path = "verenigingen.patches.v2_1.add_mollie_payment_entry_unique_index"
        with patch(f"{module_path}._find_duplicates", return_value=[]):
            with self.assertRaises(Exception):
                execute()

        self.assertFalse(self._index_exists())

    def test_skips_cleanly_when_index_already_exists(self):
        """Already-done is a real no-op, not a retry target.

        Stubs `_index_exists` rather than creating a real global unique index on the
        shared table: this table carries unrelated duplicate (reference_no,
        payment_type, party) combinations from other tests/fixtures, so a real
        `CREATE UNIQUE INDEX` here can fail on data this test has no business
        touching. The behaviour under test -- "skip without raising, without
        touching duplicates, when the index is already there" -- doesn't need a real
        index to prove.
        """
        module_path = "verenigingen.patches.v2_1.add_mollie_payment_entry_unique_index"
        with patch(f"{module_path}._index_exists", return_value=True):
            with patch(f"{module_path}._find_duplicates") as find_duplicates:
                execute()  # must not raise
                find_duplicates.assert_not_called()
