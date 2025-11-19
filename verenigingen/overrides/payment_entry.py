"""
Custom Payment Entry Override for Verenigingen

This override addresses the HRMS global override issue where ALL Payment Entries
(including Customer payments) are forced to use EmployeePaymentEntry class,
which prevents normal Document cancellation behavior.

This class simply inherits from standard ERPNext PaymentEntry to restore
proper cancellation behavior for all payment types while preserving HRMS
functionality where appropriate.
"""

import frappe
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry as StandardPaymentEntry


class PaymentEntry(StandardPaymentEntry):
    """
    Payment Entry override that restores standard ERPNext behavior.

    This fixes the issue where HRMS was globally overriding ALL Payment Entries,
    preventing standard Document cancellation behavior from working properly.

    By inheriting from the standard PaymentEntry, we restore normal cancellation
    while preserving all other ERPNext functionality.
    """

    pass  # Simply inherit standard PaymentEntry behavior
