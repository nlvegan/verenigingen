"""The e-Boekhouden Bank Transaction writers mark their `EB-<mutation id>` reference (#1349).

`EB-<mutation id>` is minted by the importer, unique per mutation by construction, so it stays
constrained per account -- but because the WRITER says so (`custom_reference_is_system_issued`),
not because of its prefix (a payer can type "EB-2024" on an MT940 line). Both writers are
driven here through their real flows and the row is read back: flag set, key present, and the
database refuses a second flagged row with the same reference on the same account.

Run:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.e_boekhouden.test_eboekhouden_reference_flag_1349
"""

import frappe
from frappe.utils import nowdate

from verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler import PaymentEntryHandler
from verenigingen.tests.e_boekhouden.test_payment_processor_party_resolution import _PartyBase
from verenigingen.tests.utils.system_issued_reference_assertions import SystemIssuedReferenceAssertions


class TestEBoekhoudenWritersMarkTheirReferences(SystemIssuedReferenceAssertions, _PartyBase):
    def test_journal_entry_writer(self):
        mutation_id = 7491001
        je = self._make_submitted_je(mutation_id, amount=33.0)
        bt = self._processor()._create_bank_transaction_for_journal_entry(
            {"id": mutation_id, "type": 5, "description": "journal entry writer"},
            je,
            self.bank,
            self.bank_account,
        )
        self._assert_written_as_system_issued(bt, f"EB-{mutation_id}")

    def test_payment_entry_writer(self):
        mutation_id = 7491002
        payment_entry = frappe._dict(
            payment_type="Receive",
            paid_amount=21.0,
            received_amount=21.0,
            posting_date=nowdate(),
            party_type=None,
            party=None,
        )
        bt = PaymentEntryHandler(self.company)._create_bank_transaction_for_payment(
            {"id": mutation_id, "description": "payment entry writer"}, payment_entry, self.bank_account
        )
        self._assert_written_as_system_issued(bt, f"EB-{mutation_id}")
