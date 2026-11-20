"""Pin the Mollie bank account that account-scoped Bank Transaction lookups resolve (#2620).

Mollie-reference lookups only count a live Bank Transaction on the Mollie bank account
(`BankTransactionCreator.find_mollie_bank_transaction`). A test that seeds a Bank Transaction
for such a lookup must put it on THAT account, so the seam and the row come from one place.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.verenigingen_payments.services.bank_transaction_creator import BankTransactionCreator


def pin_mollie_bank_account(test_case, bank_account: str | None = None) -> dict:
    """Point the Mollie config seam at a Bank Account; undone at cleanup.

    Defaults to the owned EUR test Bank Account; pass ``bank_account`` for a test that builds
    its own. Returns ``{"bank_account", "company"}``: create the Bank Transactions under test
    with them.
    """
    if bank_account:
        company = frappe.db.get_value("Bank Account", bank_account, "company")
    else:
        company = get_eur_test_company()
        bank_account = get_eur_bank_account(company)
    config = {"bank_account": bank_account, "company": company}
    patcher = patch.object(BankTransactionCreator, "get_mollie_bank_account_config", return_value=config)
    patcher.start()
    test_case.addCleanup(patcher.stop)
    return config
