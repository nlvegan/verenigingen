"""
Repo-wide ratchet: no NEW package __init__.py may start importing its own
submodules at module-import time.

## The mechanism (see issue #396 and verenigingen/services/billing/__init__.py,
where this first surfaced in production)

A package __init__.py that re-exports its submodules
(`from .submodule import Name`, or the absolute equivalent) means every
`import verenigingen.<pkg>.<anything>` runs all of those imports first, while
holding that package's import lock. CPython's import machinery takes the
*submodule* lock before the *package* lock
(importlib._bootstrap._find_and_load acquires the lock for the full dotted
name, then _find_and_load_unlocked re-enters the import of a parent whose spec
is still _initializing). So under a threaded web worker, one thread can be
inside a barrel __init__ (holding the package lock) while a second thread is
inside a submodule it imported directly (holding the submodule lock, waiting
on the package) - a cycle CPython detects and reports as:

    _frozen_importlib._DeadlockError: deadlock detected by
    _ModuleLock('verenigingen.<pkg>.<submodule>')

This is 3.13+ behaviour: python 3.12's _find_and_load_unlocked re-imports a
parent only when it is absent from sys.modules, so the cycle could not close.

A barrel alone is necessary but not sufficient - it also needs some OTHER
module doing a module-level `from verenigingen.<pkg>.<submodule> import ...`,
so a second thread can be caught inside the submodule while the package is
mid-init. That second ingredient can be added by an unrelated change at any
time, so a currently-inert barrel is one caller away from being exploitable -
which is why this ratchet flags every self-importing __init__.py, not just
the ones with a known caller today.

## What this test does NOT flag

Only code that runs at module-import time can hold the package lock while
still `_initializing`. A function/async-function body is deferred until
someone calls it - by then this module has long finished initializing, so an
import inside a function cannot participate in this deadlock. See
verenigingen/utils/security/__init__.py's `setup_all_security()` for a
production example: its submodule imports live inside the function body
specifically so this check does not need to flag them.

## The allow-list

`ALLOWED_SELF_IMPORTING_PACKAGES` is the enumerated class of every package
that still imports its own submodules at module level. It may only SHRINK:
fix a barrel the way verenigingen/services/billing/__init__.py and
verenigingen/services/chapter/__init__.py were fixed (empty the __init__,
point callers at the defining submodule), then remove its entry here.

`verenigingen.hooks` is a PERMANENT exception, not a to-do: Frappe reads
`doc_events`, `scheduler_events`, etc. as attributes of that module, so it
must keep re-exporting them. It is imported once at app boot, single-threaded,
before any request thread exists, so the ingredient that makes a barrel
dangerous (a second, concurrent thread already inside one of its submodules)
cannot apply to it.

Two checks, because neither alone is enough: the AST one names every offender
so a failure explains itself, and the runtime one (see
verenigingen/tests/utils/barrel_init_ast.py's runtime_own_names) is what
actually matters - it survives an import bound under a different name that
the AST walk cannot see. The runtime check only runs for the already-fixed
packages (see FIXED_PACKAGES below) - running it for all ~90 packages in the
app on every test invocation (one subprocess import each) would be
needlessly slow for packages this ratchet already treats as allow-listed
technical debt.
"""

import unittest
from pathlib import Path

import frappe

from verenigingen.tests.utils.barrel_init_ast import (
    eager_imports,
    is_own_submodule,
    runtime_own_names,
)

APP_ROOT = Path(frappe.get_app_path("verenigingen"))
APP_PARENT = APP_ROOT.parent  # so dotted paths start with "verenigingen."

# Packages that import their own submodules at module-import time today.
# This list may only shrink. See the module docstring.
ALLOWED_SELF_IMPORTING_PACKAGES = {
    "verenigingen.hooks",  # permanent - see module docstring
    "verenigingen.api.member",
    "verenigingen.e_boekhouden.services",
    "verenigingen.e_boekhouden.utils.consolidated",
    "verenigingen.e_boekhouden.utils.payment_processing",
    "verenigingen.repositories",
    "verenigingen.services.approval",
    "verenigingen.services.communication",
    "verenigingen.services.csv_import",
    "verenigingen.services.document",
    "verenigingen.services.member.chapter",
    "verenigingen.services.member.debug",
    "verenigingen.services.member.display",
    "verenigingen.services.member.donor",
    "verenigingen.services.member.financial",
    "verenigingen.services.member.identification",
    "verenigingen.services.member.lifecycle",
    "verenigingen.services.member.payment",
    "verenigingen.services.member.utils",
    "verenigingen.services.member.validation",
    "verenigingen.services.monitoring",
    "verenigingen.services.payment",
    "verenigingen.services.termination",
    "verenigingen.utils",
    "verenigingen.verenigingen.doctype.chapter.managers",
    "verenigingen.verenigingen.doctype.chapter.validators",
    "verenigingen.verenigingen_payments.clients",
    "verenigingen.verenigingen_payments.core.models",
    "verenigingen.verenigingen_payments.core.resilience",
    "verenigingen.verenigingen_payments.core.security",
    "verenigingen.verenigingen_payments.hooks",
    "verenigingen.verenigingen_payments.ing_checkout.services",
    "verenigingen.verenigingen_payments.mollie",
    "verenigingen.verenigingen_payments.mollie.api",
    "verenigingen.verenigingen_payments.mollie.core",
    "verenigingen.verenigingen_payments.mollie.services",
    "verenigingen.verenigingen_payments.mollie.services.handlers",
    "verenigingen.verenigingen_payments.mollie.services.shared",
    "verenigingen.verenigingen_payments.mollie.utils",
    "verenigingen.verenigingen_payments.ponto",
    "verenigingen.verenigingen_payments.ponto.api",
    "verenigingen.verenigingen_payments.ponto.clients",
    "verenigingen.verenigingen_payments.ponto.core",
    "verenigingen.verenigingen_payments.ponto.services",
    "verenigingen.verenigingen_payments.ponto.utils",
    "verenigingen.verenigingen_payments.services.payment",
    "verenigingen.verenigingen_payments.utils.payment_services",
    "verenigingen.verenigingen_payments.utils.webhook",
    "verenigingen.verenigingen_payments.workflows",
}

# Packages already fixed for #396: must never re-appear in the allow-list,
# and are checked at runtime (see TestFixedPackagesDefineNoNewName) against
# the non-dunder names each one's __init__.py is allowed to define directly
# (a function like setup_all_security is fine; a name bound by importing a
# submodule is exactly the bug). Empty for billing/chapter: their __init__.py
# files are docstring-only.
FIXED_PACKAGES = {
    "verenigingen.services.billing": [],
    "verenigingen.services.chapter": [],
    "verenigingen.utils.security": ["setup_all_security"],
}


def _find_self_importing_packages() -> dict[str, list[str]]:
    """Every `verenigingen.*` package whose __init__.py imports its own
    submodules at module-import time, mapped to the offending names.

    Test packages are excluded: tests only ever run single-threaded within
    one process, so they cannot supply the concurrent second thread this
    deadlock needs.
    """
    offenders = {}
    for init_path in sorted(APP_ROOT.rglob("__init__.py")):
        if "__pycache__" in init_path.parts:
            continue
        pkg_dir = init_path.parent
        rel_parts = pkg_dir.relative_to(APP_PARENT).parts
        if "tests" in rel_parts:
            continue
        dotted = ".".join(rel_parts)
        self_imports = sorted(
            {name for name in eager_imports(init_path, dotted) if is_own_submodule(name, dotted)}
        )
        if self_imports:
            offenders[dotted] = self_imports
    return offenders


class TestBarrelInitNoSelfImport(unittest.TestCase):
    def test_no_self_importing_package_outside_the_allow_list(self):
        found = _find_self_importing_packages()

        unexpected = sorted(set(found) - ALLOWED_SELF_IMPORTING_PACKAGES)

        self.assertEqual(
            unexpected,
            [],
            "New barrel __init__.py file(s) import their own submodules at module-import "
            "time, which reopens the concurrent-import deadlock from issue #396: "
            + "; ".join(f"{pkg} imports {found[pkg]}" for pkg in unexpected)
            + ". Either fix the barrel (see verenigingen/services/billing/__init__.py and "
            "verenigingen/services/chapter/__init__.py) or, if it is truly unavoidable, add "
            "it to ALLOWED_SELF_IMPORTING_PACKAGES with a reason.",
        )

    def test_allow_list_has_no_stale_entries(self):
        """The allow-list may only shrink - prune an entry once its barrel is fixed."""
        found = _find_self_importing_packages()

        stale = sorted(ALLOWED_SELF_IMPORTING_PACKAGES - set(found))

        self.assertEqual(
            stale,
            [],
            f"{stale} no longer import their own submodules but are still on the "
            "allow-list. Remove the stale entries - the list documents current debt, "
            "not history.",
        )

    def test_fixed_packages_are_not_reintroduced(self):
        """A regression here must be fixed again, not silently re-allow-listed."""
        found = _find_self_importing_packages()

        regressed = sorted(set(FIXED_PACKAGES) & (set(found) | ALLOWED_SELF_IMPORTING_PACKAGES))

        self.assertEqual(
            regressed,
            [],
            f"{regressed} were fixed for issue #396 and must not import their own "
            "submodules again, on the allow-list or off it.",
        )


class TestFixedPackagesDefineNoNewName(unittest.TestCase):
    """The property the AST check only approximates, for each already-fixed package.

    See verenigingen/tests/utils/barrel_init_ast.py's runtime_own_names for why
    this compares each package's OWN post-import namespace against an
    explicit allow-list, rather than asking what sys.modules picked up: an
    ancestor package can have its own separate, tracked instance of this bug
    (verenigingen.utils does, for verenigingen.utils.security - see that
    package's entry on ALLOWED_SELF_IMPORTING_PACKAGES) and Python always
    imports ancestors first, so a sys.modules-based check would bury a real
    regression in a fixed package under noise it did not cause.
    """

    def test_fixed_packages_define_no_new_name(self):
        for package, allowed_names in FIXED_PACKAGES.items():
            with self.subTest(package=package):
                own_names = runtime_own_names(package)

                self.assertEqual(
                    own_names,
                    sorted(allowed_names),
                    f"importing {package} left {own_names} bound in its own namespace, expected "
                    f"only {sorted(allowed_names)}. Whatever caused the extra names - an import "
                    f"in {package}'s own __init__.py, a lazy __getattr__, importlib bound to a "
                    "name - re-opens the deadlock window.",
                )
