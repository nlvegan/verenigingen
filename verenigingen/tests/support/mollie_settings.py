"""Pin the Singles a Mollie money-path test needs, and put them back.

``Verenigingen Settings`` and ``Mollie Settings`` are Singles shared with every
co-tenant test in the shard, so a test that points them at its own fixtures has
to restore them -- and it has to do so through ``addCleanup``, because a
``tearDown`` restore is discarded by the base cleanup that runs after it.

Registered per test rather than per class: these tests build their accounts in
``setUp``, so there is nothing to point the Singles at until then. Contrast
:mod:`verenigingen.tests.support.verenigingen_settings`, which owns the
*company* pin at class scope for the whole suite.

The restores commit, deliberately. ``addCleanup`` is LIFO and the framework
registers its rollback first, so an uncommitted restore is thrown away by the
very next cleanup and the pin leaks permanently (#312).
"""

import frappe


def clear_mollie_config_cache() -> None:
    """Drop MollieConfigurationService's cached settings.

    It caches in Redis, which survives the harness rollback -- so a test that
    changes ``Mollie Settings`` and does not clear this reads the previous
    value, and the next test reads *this* one.
    """
    from verenigingen.verenigingen_payments.services.mollie_configuration_service import (
        MollieConfigurationService,
    )

    MollieConfigurationService.clear_cache()


def pin_verenigingen_settings(test_case, **fields) -> None:
    """Point ``Verenigingen Settings`` fields at this test's fixtures for its duration."""
    previous = {field: frappe.db.get_single_value("Verenigingen Settings", field) for field in fields}

    for field, value in fields.items():
        frappe.db.set_single_value("Verenigingen Settings", field, value)

    def restore():
        for field, value in previous.items():
            frappe.db.set_single_value("Verenigingen Settings", field, value)
        frappe.db.commit()

    test_case.addCleanup(restore)


def pin_mollie_clearing_account(test_case, clearing_account: str) -> None:
    """Point ``Mollie Settings.mollie_clearing_account`` at this test's account.

    The cache is cleared on both ends: on the way in so the pin is seen, and on
    the way out so the restored value is.
    """
    previous = frappe.db.get_single_value("Mollie Settings", "mollie_clearing_account")
    frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", clearing_account)
    clear_mollie_config_cache()

    def restore():
        frappe.db.set_single_value("Mollie Settings", "mollie_clearing_account", previous)
        frappe.db.commit()
        clear_mollie_config_cache()

    test_case.addCleanup(restore)
