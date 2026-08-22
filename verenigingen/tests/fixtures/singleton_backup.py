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


class SingletonBackup:
    """
    Backup and restore singleton DocType values.

    Handles regular fields and Password fields separately to ensure
    encrypted values are properly preserved.
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
                    "Table",  # Child tables need special handling
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

            frappe.logger().debug(
                f"SingletonBackup: Backed up {doctype_name} "
                f"({len(field_values)} fields, {len(password_values)} passwords)"
            )

        except Exception as e:
            frappe.logger().warning(f"SingletonBackup: Failed to backup {doctype_name}: {e}")

    def _restore_singleton(self, doctype_name: str) -> None:
        """Restore a single singleton DocType."""
        if doctype_name not in self._backups:
            frappe.logger().warning(
                f"SingletonBackup: No backup found for {doctype_name}, skipping restore"
            )
            return

        try:
            doc = frappe.get_single(doctype_name)

            # Restore regular fields
            field_values = self._backups[doctype_name]
            for fieldname, value in field_values.items():
                try:
                    setattr(doc, fieldname, value)
                except Exception:
                    pass  # Some fields may be read-only

            doc.save(ignore_permissions=True)

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
                    frappe.logger().warning(
                        f"SingletonBackup: Failed to restore password field "
                        f"{doctype_name}.{fieldname}: {e}"
                    )

            frappe.db.commit()

            frappe.logger().debug(
                f"SingletonBackup: Restored {doctype_name} "
                f"({len(field_values)} fields, {len(password_values)} passwords)"
            )

        except Exception as e:
            # get_harness_logger, NOT frappe.logger(): a failed restore leaves a
            # single carrying whatever this test set, for every test that follows
            # it in the shard. That is a contamination vector, and through
            # frappe.logger() it announced itself only in logs/frappe.log, which
            # CI does not surface (#433).
            get_harness_logger("singleton-backup").error(
                "SingletonBackup: Failed to restore %s: %s", doctype_name, e
            )


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
