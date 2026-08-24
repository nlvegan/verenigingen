"""Coherent Mollie GL account provisioning for tests.

WHY THIS EXISTS
---------------
`Mollie Settings` is a Single, so it holds whatever the last thing to touch it left
behind, and its three GL account fields were never provisioned by the harness at
all. Two consequences, both measured:

* On veg11 the live values are `mollie_bank_account == mollie_clearing_account ==
  '10440 - Triodos 1 - TPIC - TPIC'` -- one account, belonging to a leaked test
  company, doing duty as both ends of a transfer. That is #540, and it is why
  #508's settlement payout leg was a no-op: it moved money from an account to
  itself.
* Tests that need a Mollie configuration either wrote the fields and restored them
  to `None` rather than to their previous value (#548), or branched on ambient
  state -- `if settings.mollie_clearing_account and settings.mollie_bank_account:`
  -- and so asserted nothing whenever the site happened to be unconfigured.

`ensure_mollie_gl_accounts` provisions a configuration that is coherent by
construction: a clearing account and a bank account that are DIFFERENT accounts in
the SAME company, a `Bank Account` record linked to the bank GL (which the
settlement gate needs -- #544/#553), and a fees account for the fee Journal Entry.

`provisioned_mollie_settings` points `Mollie Settings` at that set for the duration
of a block and restores the ORIGINAL values afterwards, via `singleton_backup`
rather than a hand-rolled snapshot.

THE DRAIN
---------
`ensure_mollie_gl_accounts` is `@shared_fixture`. It creates Accounts and a Bank
Account, which are shared master data owned by the site: without the decorator the
captured-insert drain claims them for whichever test called first and deletes them
at that test's teardown, and every later class in the shard then fails in setUp.
`test_the_shared_mollie_account_helper_is_declared_shared` enforces the decorator
by name -- an unenforced shared helper is how #444 happened.
"""

import contextlib

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import shared_fixture
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.support.sepa_test_company import get_eur_test_company

#: Account names this fixture owns. Distinct, descriptive, and prefixed so a stray
#: row is attributable to this helper rather than to "some Mollie test".
CLEARING_ACCOUNT_NAME = "Mollie Clearing (fixture)"
BANK_ACCOUNT_NAME = "Mollie Payout Bank (fixture)"
FEES_ACCOUNT_NAME = "Mollie Processing Fees (fixture)"
BANK_ACCOUNT_DOC_NAME = "Mollie Fixture Bank"


def _leaf_account(company, account_name, account_type, root_type):
    """Get-or-create one leaf Account under the company's matching group."""
    existing = frappe.db.get_value(
        "Account", {"company": company, "account_name": account_name, "is_group": 0}, "name"
    )
    if existing:
        return existing

    parent = frappe.db.get_value(
        "Account", {"company": company, "is_group": 1, "account_type": account_type}, "name"
    ) or frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": root_type}, "name")
    if not parent:
        raise AssertionError(
            f"company {company!r} has no group Account to parent {account_name!r} under "
            f"(looked for is_group with account_type={account_type!r}, then root_type={root_type!r})"
        )

    doc = frappe.new_doc("Account")
    doc.account_name = account_name
    doc.company = company
    doc.parent_account = parent
    doc.account_type = account_type
    doc.is_group = 0
    doc.account_currency = frappe.db.get_value("Company", company, "default_currency")
    doc.insert(ignore_permissions=True)
    return doc.name


def ensure_bank_account_record(company, gl_account):
    """Get-or-create the `Bank Account` record the settlement gate resolves.

    The gate added in #553 tests MEMBERSHIP of the set of Bank Accounts on the
    configured GL account, so at least one has to exist or the gate stays closed --
    the failure mode the `is_company_account: 1` filter had on test_site_4.

    The account_name is derived from the GL account rather than fixed, because
    `Bank Account` autonames `account_name + " - " + bank`: a constant name made the
    second call (for a different GL account) collide on the docname with a
    DuplicateEntryError. One Bank Account per GL account, each named after it.
    """
    existing = frappe.db.get_value("Bank Account", {"account": gl_account}, "name")
    if existing:
        return existing

    if not frappe.db.exists("Bank", BANK_ACCOUNT_DOC_NAME):
        bank = frappe.new_doc("Bank")
        bank.bank_name = BANK_ACCOUNT_DOC_NAME
        bank.insert(ignore_permissions=True)

    doc = frappe.new_doc("Bank Account")
    doc.account_name = frappe.db.get_value("Account", gl_account, "account_name") or gl_account
    doc.bank = BANK_ACCOUNT_DOC_NAME
    doc.company = company
    doc.account = gl_account
    doc.is_company_account = 1
    doc.insert(ignore_permissions=True)
    return doc.name


@shared_fixture
def ensure_mollie_gl_accounts(company=None):
    """Provision a coherent Mollie GL account set for `company`, idempotently.

    Returns a dict with `company`, `clearing_account`, `bank_account`,
    `fees_account` and `bank_account_doc`.

    Coherent by construction, which is the point: clearing and bank are two
    DIFFERENT accounts in the SAME company. Those are exactly the two invariants
    `MollieConfigurationService.validate_all_mollie_accounts` enforces, so a test
    built on this fixture cannot accidentally assert against an incoherent config.
    """
    company = company or get_eur_test_company()
    clearing = _leaf_account(company, CLEARING_ACCOUNT_NAME, "Bank", "Asset")
    bank = _leaf_account(company, BANK_ACCOUNT_NAME, "Bank", "Asset")
    fees = _leaf_account(company, FEES_ACCOUNT_NAME, "Expense Account", "Expense")
    bank_doc = ensure_bank_account_record(company, bank)
    return {
        "company": company,
        "clearing_account": clearing,
        "bank_account": bank,
        "fees_account": fees,
        "bank_account_doc": bank_doc,
    }


@contextlib.contextmanager
def provisioned_mollie_settings(company=None, **overrides):
    """Point `Mollie Settings` at a provisioned, coherent account set.

    Restores the ORIGINAL field values on exit -- via `singleton_backup`, not a
    hand-rolled snapshot, so the Password fields and the derived
    `MollieConfigurationService` cache are handled too. Restoring to the original
    rather than to `None` is what #548 is about: three tests currently depend on a
    neighbour leaving the field `None`, which makes doing this correctly a breaking
    change.

    `overrides` replaces individual Mollie Settings fields after the coherent set is
    written, for tests that need a specific INcoherent configuration (e.g. pointing
    both fields at one account to exercise the #540 guard).

    Yields the dict from `ensure_mollie_gl_accounts`.
    """
    accounts = ensure_mollie_gl_accounts(company)
    fields = {
        "mollie_clearing_account": accounts["clearing_account"],
        "mollie_bank_account": accounts["bank_account"],
        "payment_processing_fees_account": accounts["fees_account"],
    }
    fields.update(overrides)

    with singleton_backup("Mollie Settings"):
        for field, value in fields.items():
            frappe.db.set_value("Mollie Settings", "Mollie Settings", field, value)
        _clear_config_cache()
        try:
            yield accounts
        finally:
            _clear_config_cache()


def _clear_config_cache():
    from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
        MollieConfigurationService,
    )

    MollieConfigurationService.clear_cache()
