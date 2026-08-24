"""Coherent Mollie GL account provisioning for tests.

WHY THIS EXISTS
---------------
`Mollie Settings` is a Single, so it holds whatever the last thing to touch it left
behind, and its three GL account fields were never provisioned by the harness at
all. Two consequences, both measured:

* On veg11 the live values are `mollie_bank_account == mollie_clearing_account ==
  '10440 - Triodos 1 - TPIC - TPIC'`, an account belonging to a leaked
  `TEST-Payment-Integration-Company` while settlements book into NVV. That is #540.
  One account serving as both ends is NOT itself the problem -- see
  `_book_settlement_payout`, which supports it -- the company mismatch is.
  (An earlier version of this docstring said the shared account is why #508's payout
  leg was a no-op. That is false: per #508 the leg was a no-op because the code did
  not exist.)
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


def _provisioning_company():
    """The company settlements are booked into.

    NOT named `_booking_company`: that is the service's method, this wraps it, and
    the duplicate-helper census counts NAMES -- a shared one would have added a
    baseline line for a pair that is not a clone. The wrapper is also genuinely a
    different thing, since it carries a test-only fallback.

    Delegates to `MollieConfigurationService._booking_company` rather than
    reimplementing its rule. An earlier version copied the two-line resolution here,
    which the duplicate-helper ratchet flagged as a name collision -- and it was not
    a coincidence but a real clone: the fixture's whole contract is that it
    provisions what the guard accepts, so a second copy of that rule is the one
    place divergence would be invisible.

    The `get_eur_test_company()` fallback is test-only, for a site with neither
    setting; the owned EUR company is better than provisioning into whatever
    `frappe.defaults` happens to hold.
    """
    from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
        MollieConfigurationService,
    )

    return MollieConfigurationService._booking_company() or get_eur_test_company()


#: Account names this fixture owns. Distinct, descriptive, and prefixed so a stray
#: row is attributable to this helper rather than to "some Mollie test".
CLEARING_ACCOUNT_NAME = "Mollie Clearing (fixture)"
BANK_ACCOUNT_NAME = "Mollie Payout Bank (fixture)"
FEES_ACCOUNT_NAME = "Mollie Processing Fees (fixture)"
BANK_ACCOUNT_DOC_NAME = "Mollie Fixture Bank"


def _get_or_create_leaf_account(company, account_name, account_type, root_type):
    """Get-or-create one leaf Account under the company's matching group.

    NOT named `_leaf_account`: two e_boekhouden test modules already own that name
    for a helper that only LOOKS UP an existing leaf by root_type and inserts
    nothing. Those two are byte-identical to each other, so adding a third copy of
    the name pushed the family over the duplicate ratchet's clone threshold -- and
    the two are not clones of this one, they are a different operation wearing the
    same name. The verb belongs in the name.
    """
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


@shared_fixture
def ensure_bank_account_record(company, gl_account):
    """Get-or-create the `Bank Account` record the settlement gate resolves.

    The gate added in #553 tests MEMBERSHIP of the set of Bank Accounts on the
    configured GL account, so at least one has to exist or the gate stays closed --
    the failure mode the `is_company_account: 1` filter had on test_site_4.

    `@shared_fixture` in its own right, not merely because
    `ensure_mollie_gl_accounts` is: measured, a Bank Account created by calling this
    DIRECTLY was taken by the captured-insert drain while one created through the
    shared path survived. The `Bank` doc it inserts is shared master data too, and
    the first caller to reach here before `ensure_mollie_gl_accounts` would have had
    that insert captured and drained out from under every Bank Account linking to it.

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
    # The GL DOCNAME, not its `account_name` field: the latter is identical across
    # companies ("Mollie Payout Bank (fixture)"), so once this fixture provisioned
    # into a second company the autoname collided with the first company's Bank
    # Account and raised DuplicateEntryError. The docname carries the company abbr,
    # so it is unique exactly where the Bank Account needs to be.
    doc.account_name = gl_account
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

    Coherent by construction, which is the point: all three accounts are created in
    the company settlements are actually booked into, resolved by the SAME rule
    `MollieConfigurationService._account_coherence_errors` validates against. A test
    built on this fixture therefore cannot accidentally assert against an incoherent
    configuration -- and if the two rules ever diverge, the controls
    (`test_a_provisioned_configuration_is_valid`,
    `test_a_provisioned_configuration_is_accepted`) go red rather than every other
    test quietly changing meaning.

    Deliberately NOT `get_eur_test_company()`, which owns
    `TEST-Payment-Integration-Company`: on test_site_1 the booking company is
    `_Test Company`, so provisioning into the EUR company produced exactly the
    cross-company configuration the guard exists to reject, and the controls caught
    it.
    """
    company = company or _provisioning_company()
    clearing = _get_or_create_leaf_account(company, CLEARING_ACCOUNT_NAME, "Bank", "Asset")
    bank = _get_or_create_leaf_account(company, BANK_ACCOUNT_NAME, "Bank", "Asset")
    fees = _get_or_create_leaf_account(company, FEES_ACCOUNT_NAME, "Expense Account", "Expense")
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
