"""#958: `create_payment_entry` must not flatten a non-resumable DB error.

`verenigingen/e_boekhouden/utils/consolidated/payment_entry_creation.py::create_payment_entry`
wraps `_create_payment_entry_impl` (eboekhouden_payment_import.create_payment_entry) and, on
its final `except Exception as e:`, re-raises `frappe.ValidationError(error_msg)` -- whatever
the underlying error actually was.

This function is called from `PaymentProcessor.process` (e_boekhouden/utils/processors/
payment_processor.py), which is invoked as `coordinator.process_mutation(mutation)` inside
`_process_mutation_with_coordinator` (eboekhouden_rest_full_migration.py). That caller has its
own `except NON_RESUMABLE_DB_ERRORS: raise` guard specifically so a 1213/1205 during
processing is never treated as an ordinary "new processor failed, fall back to legacy" case
against a transaction the server has already discarded or half-applied (#572, the same
reasoning documented on `_create_journal_entry`'s caller). A `ValidationError` can never
satisfy that guard, so this flattening silently defeats it for the payment-entry path exactly
as `_create_journal_entry` does for the journal-entry path.

No document fixtures are needed: `_create_payment_entry_impl` is invoked via a local import
inside the function body (`from ...eboekhouden_payment_import import create_payment_entry as
_create_payment_entry_impl`), which re-resolves the module attribute at call time -- so
patching that attribute before calling `create_payment_entry` is enough to inject the error at
exactly the point production reaches it, with mutation/company/cost_center left as opaque
values.
"""

from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.utils.consolidated.payment_entry_creation import create_payment_entry
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.non_resumable_errors import deadlock


class TestCreatePaymentEntryPreservesNonResumableErrors(EnhancedTestCase):
    def test_deadlock_from_impl_propagates_as_deadlock_not_validation_error(self):
        mutation = {"id": 900100}

        with patch(
            "verenigingen.e_boekhouden.utils.eboekhouden_payment_import.create_payment_entry",
            side_effect=deadlock(),
        ):
            with self.assertRaises(frappe.QueryDeadlockError):
                create_payment_entry(mutation, "Any Company", "Any Cost Center", debug_info=[])


if __name__ == "__main__":
    import unittest

    unittest.main()
