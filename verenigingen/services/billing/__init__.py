# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Billing services for membership dues processing.

Import from the submodule that defines what you need, not from this package:

    from verenigingen.services.billing.billing_date_service import BillingDateService

This __init__ deliberately imports nothing. It used to re-export thirteen
submodules, which made `import verenigingen.services.billing.<anything>` run
all thirteen first. CPython takes the submodule lock before the package lock
(importlib._bootstrap._find_and_load acquires the lock for the full dotted
name, then _find_and_load_unlocked re-enters the import of a parent whose spec
is still _initializing), so under a threaded web worker one thread could hold
the package lock inside this file while a second held a submodule lock and
waited for the package - a cycle CPython reports as

    _frozen_importlib._DeadlockError: deadlock detected by
    _ModuleLock('verenigingen.services.billing.template_configuration_service')

Note this is 3.13+ behaviour: python 3.12's _find_and_load_unlocked re-imports
the parent only when it is absent from sys.modules, so the cycle never closed.

test_billing_package_init.py keeps this file honest.
"""
