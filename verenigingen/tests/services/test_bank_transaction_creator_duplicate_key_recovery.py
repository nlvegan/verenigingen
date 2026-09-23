"""BankTransactionCreator's recovery from a real (bank_account, reference_number) race (#1267).

A genuine race -- two writers both pass the pre-insert existence check before either
commits -- cannot be reproduced deterministically in a single-threaded test. This mocks
ONE seam, `_find_matching_bank_transaction`, purely to force that timing window: it is made
to miss on its first two calls (the pre-insert checks in `create()` and in
`_create_bank_transaction`'s retry loop), exactly as it would if a second writer's row
had not committed yet when this caller checked. Everything downstream of that is real: a
real colliding Bank Transaction (inserted through the ORM beforehand, so it carries a real
`custom_reference_number_key`), a real unique-index violation from MariaDB, and the real
(unmocked) `secure_document_operation()` failure handling.

This is deliberately NOT in test_bank_transaction_creator_coverage.py, whose module
docstring commits to no business-logic mocks -- there is no way to force this specific
timing window without mocking something, so it gets its own file and this explanation.

What this caught: `secure_document_operation()` catches the IntegrityError/
UniqueValidationError that `doc.insert()` raises and reports it as `success=False` with
the error text in `.errors` -- it does NOT re-raise (empirically confirmed against
`tabUser`'s primary-key uniqueness on 2026-09-23: a duplicate create through
`secure_document_operation` returned `success=False`, no exception). That means
`_create_bank_transaction`'s own `except (DuplicateEntryError, frappe.UniqueValidationError)`
block, written for exactly this race, is unreachable for a `create()` collision: the
exception never leaves `secure_document_operation()` to reach it. Before #1267 this was
latent (nothing enforced uniqueness on `reference_number` besides `name`, so the collision
this block exists to recover from could not happen via this path); once #1267's unique
index is live, a real race hits this dead branch and the writer that lost the race would
get `None` back instead of the winning row.
"""

from unittest import mock

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.services.test_bank_transaction_creator_coverage import (
    COMPANY,
    _BankTxnFixtureMixin,
)
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    BankTransactionCreator,
)


class TestBankTransactionCreatorDuplicateKeyRecovery(_BankTxnFixtureMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.gl_account = self._ensure_gl_account()
        self.bank_account = self._ensure_bank_account(self.gl_account)
        self.creator = BankTransactionCreator()

    def tearDown(self):
        frappe.db.rollback()
        super().tearDown()

    def _force_a_missed_pre_insert_check(self):
        """Make the next 2 calls to _find_matching_bank_transaction return None (the
        pre-insert checks in create() and _create_bank_transaction's retry loop), then
        fall through to the real lookup for anything after that -- in particular, the
        recovery lookup this test is asserting on."""
        original_lookup = self.creator._find_matching_bank_transaction
        calls = {"n": 0}

        def flaky_lookup(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] <= 2:
                return None
            return original_lookup(*args, **kwargs)

        return mock.patch.object(self.creator, "_find_matching_bank_transaction", side_effect=flaky_lookup)

    def test_duplicate_key_create_failure_recovers_the_winner_of_the_race(self):
        # Must be a SYSTEM-issued shape (here: Mollie's tr_ prefix) -- the amended #1267
        # scope leaves an MT940/manual-shaped reference unconstrained, so a race on one of
        # those could never collide on custom_reference_number_key in the first place.
        ref = f"tr_{frappe.generate_hash()[:10]}"
        winner = self._insert_draft_bank_transaction(ref, self.bank_account)

        # secure_document_operation() itself logs the swallowed IntegrityError via
        # frappe.log_error before returning success=False -- that happens regardless of
        # how _create_bank_transaction handles the failure afterwards, so it is expected
        # here rather than a symptom of a bug.
        self.expectErrorLog("Secure Operation Failed")

        with self._force_a_missed_pre_insert_check():
            result = self.creator.create(
                date=today(),
                bank_account=self.bank_account,
                company=COMPANY,
                deposit=12.0,
                withdrawal=0.0,
                currency="EUR",
                reference_number=ref,
                description="racing writer",
            )

        self.assertEqual(
            result,
            winner.name,
            "a create() that collides with the row that won the race must recover it, "
            "not silently return None",
        )
        self.assertEqual(frappe.db.count("Bank Transaction", {"reference_number": ref}), 1)
