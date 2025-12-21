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
            frappe.logger().error(f"SingletonBackup: Failed to restore {doctype_name}: {e}")


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
