"""
Singleton DocType Backup/Restore Utility for Tests

Prevents tests from permanently corrupting singleton settings like
Ponto Settings, Verenigingen Settings, etc.

Usage:

1. As a context manager:
    ```python
    from verenigingen.tests.fixtures.singleton_backup import singleton_backup

    def test_something(self):
        with singleton_backup("Ponto Settings"):
            settings = frappe.get_single("Ponto Settings")
            settings.sandbox_mode = 0  # Modify for test
            settings.save()
            # ... test code ...
        # Original values automatically restored
    ```

2. As a decorator:
    ```python
    from verenigingen.tests.fixtures.singleton_backup import backup_singleton

    @backup_singleton("Ponto Settings")
    def test_something(self):
        # Modify settings freely - they'll be restored after
        pass

    # Multiple singletons:
    @backup_singleton("Ponto Settings", "Verenigingen Settings")
    def test_something(self):
        pass
    ```

3. In setUpClass/tearDownClass:
    ```python
    from verenigingen.tests.fixtures.singleton_backup import SingletonBackup

    class TestMyFeature(FrappeTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            cls._singleton_backup = SingletonBackup("Ponto Settings")
            cls._singleton_backup.backup()
            # Now safe to modify settings

        @classmethod
        def tearDownClass(cls):
            cls._singleton_backup.restore()
            super().tearDownClass()
    ```

4. Multiple singletons:
    ```python
    with singleton_backup("Ponto Settings", "Verenigingen Settings"):
        # Both will be restored
        pass
    ```
"""

import functools
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from verenigingen.tests.harness_logger import get_harness_logger

# Cache-clearing methods to call after a restore, per doctype.
#
# `restore()` deliberately does not run `on_update` (see `_restore_singleton`),
# but for `Ponto Settings` that hook is nothing BUT cache invalidation, and
# losing it trades one contamination vector for another:
# `tests/sepa/test_ponto_client.py` plants `PontoTokenManager.TOKEN_CACHE_KEY` in
# SHARED redis with a 3600s TTL and never clears it, and `ponto_settings_cache`
# (300s) is read by `ponto_client`, `betaalverzoek_client` and
# `transaction_importer`. Measured: without this map both keys survive a restore
# that used to clear them.
#
# Named methods rather than `on_update` itself, because on the other singles that
# hook writes CSS into the public dir, syncs Select options across doctypes,
# registers payment gateways and calls the Mollie API. A doctype absent from this
# map gets no invalidation, which is the old failing path's behaviour, so adding
# an entry can only ever help.
CACHE_CLEARING_METHODS = {
    "Ponto Settings": ("clear_configuration_cache", "clear_token_cache"),
}


class SingletonBackup:
    """
    Backup and restore singleton DocType values.

    Handles regular fields and Password fields separately to ensure
    encrypted values are properly preserved.

    `restore()` writes straight into `tabSingles` and `__Auth`; it does NOT go
    through `doc.save()`, so no `validate`/`before_save`/`on_update` hook runs.
    That is deliberate -- see `_restore_singleton` (#537). The cache invalidation
    those hooks used to give it is done explicitly instead, per
    `CACHE_CLEARING_METHODS`.

    Child tables are still not backed up at all: `_backup_singleton` skips the
    `Table` fieldtype, so rows a test adds to one survive the restore -- measured,
    one leftover `Ponto Bank Account Mapping` row on `test_site_3`, though whether
    a row survives depends on which module wrote last. Unchanged by #537, and
    untested either way; `test_ponto_doctype_coverage_extra` has a docstring
    claiming the mappings are restored, and they are not.
    """

    def __init__(self, *doctype_names: str):
        """
        Initialize backup for one or more singleton DocTypes.

        Args:
            *doctype_names: Names of singleton DocTypes to backup
        """
        self.doctype_names = doctype_names
        self._backups: Dict[str, Dict[str, Any]] = {}
        self._password_backups: Dict[str, Dict[str, str]] = {}

    def backup(self) -> None:
        """
        Capture current values of all configured singletons.

        Call this before modifying settings in tests.
        """
        for doctype_name in self.doctype_names:
            self._backup_singleton(doctype_name)

    def restore(self) -> None:
        """
        Restore all singletons to their backed-up values.

        Call this after tests complete (in tearDown/tearDownClass).
        """
        for doctype_name in self.doctype_names:
            self._restore_singleton(doctype_name)

    def _backup_singleton(self, doctype_name: str) -> None:
        """Backup a single singleton DocType."""
        try:
            doc = frappe.get_single(doctype_name)
            meta = frappe.get_meta(doctype_name)

            # Backup regular fields
            field_values = {}
            password_fields = []

            for field in meta.fields:
                if field.fieldtype == "Password":
                    password_fields.append(field.fieldname)
                elif field.fieldtype not in (
                    "Section Break",
                    "Column Break",
                    "Tab Break",
                    "HTML",
                    "Button",
                    # Child tables need special handling. `Table MultiSelect` is
                    # here because its value is a LIST of child documents too:
                    # `setattr` + `save()` coped with one, a `tabSingles` write
                    # would not. No app Single declares one today.
                    "Table",
                    "Table MultiSelect",
                ):
                    field_values[field.fieldname] = getattr(doc, field.fieldname, None)

            self._backups[doctype_name] = field_values

            # Backup password fields separately (they're encrypted)
            password_values = {}
            for fieldname in password_fields:
                try:
                    value = get_decrypted_password(
                        doctype_name, doctype_name, fieldname, raise_exception=False
                    )
                    if value:
                        password_values[fieldname] = value
                except Exception:
                    # Field might not have a value
                    pass

            self._password_backups[doctype_name] = password_values

            get_harness_logger("singleton-backup").debug(
                "Backed up %s (%d fields, %d passwords)",
                doctype_name,
                len(field_values),
                len(password_values),
            )

        except Exception as e:
            get_harness_logger("singleton-backup").warning(
                "Failed to backup %s: %s", doctype_name, e
            )

    def _restore_singleton(self, doctype_name: str) -> None:
        """Restore a single singleton DocType."""
        if doctype_name not in self._backups:
            get_harness_logger("singleton-backup").warning(
                "No backup found for %s, skipping restore", doctype_name
            )
            return

        try:
            # Straight into `tabSingles`, NOT through doc.save(): a restore puts
            # back a state that was already persisted, so a controller's
            # validate() must not get a veto over it. It used to, and the state it
            # rejected was `Ponto Settings`' own factory default -- `sandbox_mode`
            # defaults to 1 with no `sandbox_client_id`, which
            # `validate_credentials_configured` throws on. Measured across all 12
            # shards of PR #525 (green): 34 swallowed restores, every one that
            # pair, leaving the test's credential in the Single for the rest of
            # the shard and on the site afterwards (#537).
            #
            # Skipping the lifecycle is wanted, not merely tolerable: `on_update`
            # on these singles writes CSS into the public dir, syncs Select
            # options across doctypes and registers payment gateways, and
            # `Mollie Settings.validate` calls the Mollie API. A teardown must do
            # none of that. The one thing worth keeping from `on_update` is the
            # cache invalidation, done explicitly below. Password fields are
            # restored below too -- they live in `__Auth` and never enter
            # `field_values`.
            #
            # `set_single_value` runs values through `sbool`, which converts
            # exactly "true"/"1"/"false"/"0" (case-insensitive) and leaves
            # everything else alone -- "yes"/"no" included. "1"/"0" round-trip
            # byte-identically (True -> literal 1 -> read back "1"), which is what
            # the eight sbool-ambiguous Single defaults declare, e.g.
            # `E-Boekhouden Settings.fiscal_year_start_month`. Only a literal
            # "true"/"false" in a text field would be lossy and nothing declares
            # one, so the framework's own Single-write API is worth more than
            # hand-rolling the insert to avoid that edge.
            field_values = self._backups[doctype_name]
            if field_values:
                frappe.db.set_single_value(doctype_name, dict(field_values))

            # Restore password fields
            password_values = self._password_backups.get(doctype_name, {})
            for fieldname, value in password_values.items():
                try:
                    set_encrypted_password(
                        doctype_name,
                        doctype_name,  # For singletons, name == doctype
                        value,
                        fieldname=fieldname,
                    )
                except Exception as e:
                    # Neither `e` nor `fieldname`. This logger writes to stderr, which
                    # in CI is a PUBLIC job log, and both are derived from the password
                    # map: `e` comes out of `set_encrypted_password(..., value, ...)`,
                    # and CodeQL flags the loop key itself as sensitive
                    # (py/clear-text-logging-sensitive-data, high -- it was raised
                    # against both in turn). Conservative on the analyser's side rather
                    # than arguing that a field name is not a secret: the doctype and
                    # the failure class are what a reader acts on, and a Single has few
                    # password fields.
                    #
                    # The alert only exists because this stopped being a bare
                    # `frappe.logger()`, which CodeQL does not recognise as a sink. The
                    # exposure was always here; nothing was watching.
                    get_harness_logger("singleton-backup").warning(
                        "Failed to restore a password field on %s: %s",
                        doctype_name,
                        type(e).__name__,
                    )

            frappe.db.commit()

            self._clear_derived_caches(doctype_name)

            get_harness_logger("singleton-backup").debug(
                "Restored %s (%d fields, %d passwords)",
                doctype_name,
                len(field_values),
                len(password_values),
            )

        except Exception as e:
            # get_harness_logger, NOT frappe.logger(): a failed restore leaves a
            # single carrying whatever this test set, for every test that follows
            # it in the shard. That is a contamination vector, and through
            # frappe.logger() it announced itself only in logs/frappe.log, which
            # CI does not surface (#433).
            get_harness_logger("singleton-backup").error(
                "Failed to restore %s: %s", doctype_name, e
            )


    @staticmethod
    def _clear_derived_caches(doctype_name: str) -> None:
        """Drop app-level caches keyed off this Single. See CACHE_CLEARING_METHODS."""
        methods = CACHE_CLEARING_METHODS.get(doctype_name)
        if not methods:
            return
        doc = frappe.get_single(doctype_name)
        for method in methods:
            getattr(doc, method)()


@contextmanager
def singleton_backup(*doctype_names: str):
    """
    Context manager for backing up and restoring singleton DocTypes.

    Usage:
        with singleton_backup("Ponto Settings"):
            # Modify settings freely
            pass
        # Settings automatically restored

    Args:
        *doctype_names: Names of singleton DocTypes to backup
    """
    backup = SingletonBackup(*doctype_names)
    backup.backup()
    try:
        yield backup
    finally:
        backup.restore()


def backup_singleton(*doctype_names: str):
    """
    Decorator for backing up and restoring singleton DocTypes around a test.

    Usage:
        @backup_singleton("Ponto Settings")
        def test_something(self):
            # Modify settings freely
            pass

        # Multiple singletons:
        @backup_singleton("Ponto Settings", "Verenigingen Settings")
        def test_something(self):
            pass

    Args:
        *doctype_names: Names of singleton DocTypes to backup
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with singleton_backup(*doctype_names):
                return func(*args, **kwargs)

        return wrapper

    return decorator


class SingletonBackupMixin:
    """
    Mixin class for test cases that need singleton backup/restore.

    Usage:
        class TestMyFeature(SingletonBackupMixin, FrappeTestCase):
            # Specify which singletons to protect
            protected_singletons = ["Ponto Settings", "Verenigingen Settings"]

            def test_something(self):
                # All listed singletons are automatically backed up
                # and restored for each test method
                pass

    The mixin automatically:
    - Backs up singletons in setUp()
    - Restores them in tearDown()
    """

    # Override in subclass to specify which singletons to protect
    protected_singletons: List[str] = []

    def setUp(self):
        """Back up singletons before each test."""
        super().setUp()
        if self.protected_singletons:
            self._singleton_backup = SingletonBackup(*self.protected_singletons)
            self._singleton_backup.backup()

    def tearDown(self):
        """Restore singletons after each test."""
        if hasattr(self, "_singleton_backup"):
            self._singleton_backup.restore()
        super().tearDown()


class FlagBackupMixin:
    """
    Mixin class for test cases that need frappe.flags backup/restore.

    Usage:
        class TestMyFeature(FlagBackupMixin, FrappeTestCase):
            # Specify which flags to manage
            protected_flags = ["suppress_notifications", "suppress_all_notifications", "in_import"]

            def test_something(self):
                frappe.flags.suppress_notifications = True
                # Flag will be automatically restored after test
                pass

    The mixin automatically:
    - Backs up flag values in setUp()
    - Restores them in tearDown()
    """

    # Override in subclass to specify which flags to protect
    protected_flags: List[str] = []

    def setUp(self):
        """Back up flags before each test."""
        super().setUp()
        self._flag_backup = {}
        for flag_name in self.protected_flags:
            self._flag_backup[flag_name] = getattr(frappe.flags, flag_name, None)

    def tearDown(self):
        """Restore flags after each test."""
        for flag_name, original_value in self._flag_backup.items():
            if original_value is None:
                # Remove the flag if it wasn't set before
                if hasattr(frappe.flags, flag_name):
                    delattr(frappe.flags, flag_name)
            else:
                setattr(frappe.flags, flag_name, original_value)
        super().tearDown()


@contextmanager
def flag_backup(*flag_names: str):
    """
    Context manager for backing up and restoring frappe.flags.

    Usage:
        with flag_backup("suppress_notifications", "in_import"):
            frappe.flags.suppress_notifications = True
            # ... test code ...
        # Flags automatically restored

    Args:
        *flag_names: Names of flags to backup
    """
    backup = {}
    for flag_name in flag_names:
        backup[flag_name] = getattr(frappe.flags, flag_name, None)

    try:
        yield
    finally:
        for flag_name, original_value in backup.items():
            if original_value is None:
                if hasattr(frappe.flags, flag_name):
                    delattr(frappe.flags, flag_name)
            else:
                setattr(frappe.flags, flag_name, original_value)
