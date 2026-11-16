"""Shared assertion for the writers that mint a system-issued Bank Transaction reference (#1349)."""

import frappe
from frappe.utils import nowdate

from verenigingen.verenigingen_payments.utils.bank_transaction_reference_key import (
    FIELDNAME,
    SYSTEM_ISSUED_FIELDNAME,
)


class SystemIssuedReferenceAssertions:
    """Needs `self.bank_account` and `self.company` on the test case."""

    def _assert_written_as_system_issued(self, bt_name, reference):
        self.assertTrue(bt_name, "the writer did not create a Bank Transaction")
        row = frappe.db.get_value(
            "Bank Transaction",
            bt_name,
            ["reference_number", "bank_account", SYSTEM_ISSUED_FIELDNAME, FIELDNAME],
            as_dict=True,
        )
        self.assertEqual(row.reference_number, reference)
        self.assertEqual(row.bank_account, self.bank_account)
        self.assertEqual(row[SYSTEM_ISSUED_FIELDNAME], 1, "the writer did not set the system-issued flag")
        self.assertTrue(row[FIELDNAME], "a flagged row has no reference key")
        # The control that makes this a test of the GUARD: the database refuses the twin.
        twin = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "date": nowdate(),
                "bank_account": self.bank_account,
                "company": self.company,
                "deposit": 1.0,
                "withdrawal": 0.0,
                "currency": "EUR",
                "reference_number": reference,
                "description": "twin of a system-issued row",
                "unallocated_amount": 1.0,
                "allocated_amount": 0.0,
                SYSTEM_ISSUED_FIELDNAME: 1,
            }
        )
        with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
            twin.insert(ignore_permissions=True)
