"""Two distinct MT940 payments sharing one payer EREF must BOTH be created (#1267).

PR #1340's review reproduced silent data loss: `mt940_import.py:1262` used to wrap
`bt.insert(); bt.submit()` in `contextlib.suppress(frappe.exceptions.UniqueValidationError)`.
Before #1267 that `suppress` was inert (nothing on Bank Transaction was unique besides
`name`). Once #1267 added a real unique constraint scoped to `(bank_account,
reference_number)` for EVERY non-blank reference, two genuinely distinct MT940 payments that
happen to share one payer-chosen end-to-end reference (e.g. an unchanged standing-order
reference) collided on it, and the second vanished with zero trace -- no exception reaching
the caller, no Error Log entry, no `frappe.logger()` call on that path, counted in the import
summary exactly like an already-imported duplicate.

The maintainer's amended decision narrows the constraint to SYSTEM-issued references only
(Mollie/e-Boekhouden/Ponto) and requires removing the swallow so any remaining constraint
failure is loud. This test is RED against the state PR #1340 first shipped (wide scope +
swallow: only one of the two payments survives, silently) and GREEN after both fixes.
"""

import frappe

from verenigingen.tests.fixtures import mt940_sample_statements as S
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_mt940_import_integration import MT940BankAccountFixtureMixin
from verenigingen.verenigingen_payments.utils import mt940_import as M

# A fixed, well-known test company (same one test_bank_transaction_creator_coverage.py
# uses) rather than `frappe.get_list("Company", limit=1)[0].name`: the latter reuses
# whichever Company another file's setUp happened to leave first, which is exactly the
# order-dependence shape scan_order_dependence.py's REUSE check exists to catch.
COMPANY = "_Test Company 2"


class TestMT940ImportReferenceCollision(MT940BankAccountFixtureMixin, EnhancedTestCase):
    OWN_ACCOUNT_NAME = "MT940 Reference Collision Test Account"

    def setUp(self):
        super().setUp()
        self.company = COMPANY
        self.bank_account = self._ensure_bank_account()
        # The import path commits mid-transaction (see MT940BankAccountFixtureMixin's
        # docstring), so Bank Transactions it creates survive the per-test rollback.
        self._cleanup_bank_transactions()

    def tearDown(self):
        self._cleanup_bank_transactions()
        super().tearDown()

    def test_two_distinct_payments_sharing_one_eref_are_both_created(self):
        result = M.process_mt940_document(
            S.SHARED_EREF_DISTINCT_PAYMENTS, self.bank_account, self.company
        )

        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertEqual(
            result["errors"],
            [],
            "a real constraint failure must be reported as an error, not silently absorbed",
        )
        self.assertEqual(
            result["transactions_created"],
            2,
            "both distinct payments sharing one EREF must be created -- if only 1, the "
            "second was dropped (silently, on the old wide scope + suppress; loudly as an "
            "exception if the scope narrowed but the swallow is still present)",
        )

        bts = frappe.get_all(
            "Bank Transaction",
            filters={"bank_account": self.bank_account, "reference_number": "SHARED-REF-42"},
            fields=["name", "deposit"],
        )
        self.assertEqual(len(bts), 2)
        self.assertEqual(sorted(float(bt.deposit) for bt in bts), [42.0, 99.0])
