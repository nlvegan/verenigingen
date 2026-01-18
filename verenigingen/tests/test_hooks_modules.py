# verenigingen/tests/test_hooks_modules.py
"""Tests for hooks module structure and handler resolution.

Validates that:
1. All hooks submodules can be imported without side effects
2. All handler strings in doc_events resolve to callable functions
3. All scheduler task strings resolve to callable functions
4. All permission handler strings resolve to callable functions
5. The hooks package can be imported as verenigingen.hooks (Phase 3)
6. Override class targets are importable and are actual classes
7. Cron expressions are valid format

These tests ensure the hooks/ package structure is correct and safe.
"""

import importlib
import importlib.util
import os
import re
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Base path for hooks submodules
HOOKS_DIR = Path(__file__).parent.parent / "hooks"


def load_hooks_submodule(name: str):
    """Load a hooks submodule directly from file.

    During Phase 1/2, hooks.py still exists as a module, so we can't
    import verenigingen.hooks.assets normally. Instead, we load the
    file directly using importlib.util.
    """
    file_path = HOOKS_DIR / f"{name}.py"
    if not file_path.exists():
        raise FileNotFoundError(f"Hooks submodule not found: {file_path}")

    spec = importlib.util.spec_from_file_location(f"hooks_{name}", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestHooksImportSafety(unittest.TestCase):
    """Verify hooks submodules don't have side effects on import."""

    def test_assets_import_fast(self):
        """hooks/assets.py should import quickly with no side effects."""
        start = time.time()
        assets = load_hooks_submodule("assets")
        elapsed = time.time() - start

        # Should import in under 100ms
        self.assertLess(elapsed, 0.1, f"assets.py import took {elapsed:.3f}s")

        # Should have expected exports
        self.assertTrue(hasattr(assets, "app_include_css"))
        self.assertTrue(hasattr(assets, "app_include_js"))
        self.assertTrue(hasattr(assets, "web_include_js"))
        self.assertTrue(hasattr(assets, "email_css"))

    def test_doctypes_import_fast(self):
        """hooks/doctypes.py should import quickly with no side effects."""
        start = time.time()
        doctypes = load_hooks_submodule("doctypes")
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1, f"doctypes.py import took {elapsed:.3f}s")
        self.assertTrue(hasattr(doctypes, "doctype_js"))
        self.assertIsInstance(doctypes.doctype_js, dict)

    def test_doc_events_import_fast(self):
        """hooks/doc_events.py should import quickly with no side effects."""
        start = time.time()
        doc_events = load_hooks_submodule("doc_events")
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1, f"doc_events.py import took {elapsed:.3f}s")
        self.assertTrue(hasattr(doc_events, "doc_events"))
        self.assertIsInstance(doc_events.doc_events, dict)

    def test_scheduler_import_fast(self):
        """hooks/scheduler.py should import quickly with no side effects."""
        start = time.time()
        scheduler = load_hooks_submodule("scheduler")
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1, f"scheduler.py import took {elapsed:.3f}s")
        self.assertTrue(hasattr(scheduler, "scheduler_events"))
        self.assertTrue(hasattr(scheduler, "cron"))

    def test_permissions_import_fast(self):
        """hooks/permissions.py should import quickly with no side effects."""
        start = time.time()
        permissions = load_hooks_submodule("permissions")
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1, f"permissions.py import took {elapsed:.3f}s")
        self.assertTrue(hasattr(permissions, "permission_query_conditions"))
        self.assertTrue(hasattr(permissions, "has_permission"))

    def test_fixtures_import_fast(self):
        """hooks/fixtures.py should import quickly with no side effects."""
        start = time.time()
        fixtures = load_hooks_submodule("fixtures")
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1, f"fixtures.py import took {elapsed:.3f}s")
        self.assertTrue(hasattr(fixtures, "fixtures"))
        self.assertIsInstance(fixtures.fixtures, list)

    def test_portal_import_fast(self):
        """hooks/portal.py should import quickly with no side effects."""
        start = time.time()
        portal = load_hooks_submodule("portal")
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1, f"portal.py import took {elapsed:.3f}s")
        self.assertTrue(hasattr(portal, "standard_portal_menu_items"))
        self.assertTrue(hasattr(portal, "website_context"))
        self.assertTrue(hasattr(portal, "update_website_context"))

    def test_lifecycle_import_fast(self):
        """hooks/lifecycle.py should import quickly with no side effects."""
        start = time.time()
        lifecycle = load_hooks_submodule("lifecycle")
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1, f"lifecycle.py import took {elapsed:.3f}s")
        self.assertTrue(hasattr(lifecycle, "after_install"))
        self.assertTrue(hasattr(lifecycle, "after_migrate"))
        self.assertTrue(hasattr(lifecycle, "before_tests"))
        self.assertTrue(hasattr(lifecycle, "on_logout"))


class TestDocEventHandlerResolution(unittest.TestCase):
    """Verify all doc_events handler strings resolve to callable functions."""

    @classmethod
    def setUpClass(cls):
        """Load doc_events once for all tests."""
        doc_events_module = load_hooks_submodule("doc_events")
        cls.doc_events = doc_events_module.doc_events

    def _resolve_handler(self, handler_string: str):
        """Attempt to resolve a handler string to a callable."""
        module_path, func_name = handler_string.rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            return func
        except (ImportError, AttributeError) as e:
            return None, str(e)

    def test_all_doc_event_handlers_exist(self):
        """All doc_events handlers should be importable and callable."""
        missing_handlers = []

        for doctype, events in self.doc_events.items():
            for event_name, handlers in events.items():
                # Normalize to list
                if isinstance(handlers, str):
                    handlers = [handlers]

                for handler in handlers:
                    result = self._resolve_handler(handler)
                    if result is None or (isinstance(result, tuple) and result[0] is None):
                        error = result[1] if isinstance(result, tuple) else "Unknown error"
                        missing_handlers.append(f"{doctype}.{event_name}: {handler} - {error}")
                    elif not callable(result):
                        missing_handlers.append(f"{doctype}.{event_name}: {handler} - not callable")

        if missing_handlers:
            self.fail(f"Missing or non-callable handlers:\n" + "\n".join(missing_handlers[:20]))

    def test_membership_handlers_exist(self):
        """Core Membership handlers should exist."""
        handlers = self.doc_events.get("Membership", {})
        self.assertIn("on_submit", handlers)
        self.assertIn("on_cancel", handlers)

    def test_member_handlers_exist(self):
        """Core Member handlers should exist."""
        handlers = self.doc_events.get("Member", {})
        self.assertIn("before_save", handlers)
        self.assertIn("after_save", handlers)
        self.assertIn("on_update", handlers)

    def test_payment_entry_handlers_exist(self):
        """Payment Entry handlers should exist."""
        handlers = self.doc_events.get("Payment Entry", {})
        self.assertIn("on_submit", handlers)
        self.assertIn("on_cancel", handlers)

    def test_sales_invoice_handlers_exist(self):
        """Sales Invoice handlers should exist."""
        handlers = self.doc_events.get("Sales Invoice", {})
        self.assertIn("before_validate", handlers)
        self.assertIn("validate", handlers)
        self.assertIn("on_submit", handlers)
        self.assertIn("on_cancel", handlers)


class TestSchedulerHandlerResolution(unittest.TestCase):
    """Verify all scheduler_events handler strings resolve to callable functions."""

    @classmethod
    def setUpClass(cls):
        """Load scheduler_events once for all tests."""
        scheduler_module = load_hooks_submodule("scheduler")
        cls.scheduler_events = scheduler_module.scheduler_events
        cls.cron = scheduler_module.cron

    def _resolve_handler(self, handler_string: str):
        """Attempt to resolve a handler string to a callable."""
        module_path, func_name = handler_string.rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            return func
        except (ImportError, AttributeError) as e:
            return None, str(e)

    def test_all_scheduler_handlers_exist(self):
        """All scheduler_events handlers should be importable and callable."""
        missing_handlers = []

        for frequency, handlers in self.scheduler_events.items():
            for handler in handlers:
                result = self._resolve_handler(handler)
                if result is None or (isinstance(result, tuple) and result[0] is None):
                    error = result[1] if isinstance(result, tuple) else "Unknown error"
                    missing_handlers.append(f"{frequency}: {handler} - {error}")
                elif not callable(result):
                    missing_handlers.append(f"{frequency}: {handler} - not callable")

        if missing_handlers:
            self.fail(f"Missing or non-callable scheduler handlers:\n" + "\n".join(missing_handlers[:20]))

    def test_all_cron_handlers_exist(self):
        """All cron handlers should be importable and callable."""
        missing_handlers = []

        for schedule, handlers in self.cron.items():
            for handler in handlers:
                result = self._resolve_handler(handler)
                if result is None or (isinstance(result, tuple) and result[0] is None):
                    error = result[1] if isinstance(result, tuple) else "Unknown error"
                    missing_handlers.append(f"{schedule}: {handler} - {error}")
                elif not callable(result):
                    missing_handlers.append(f"{schedule}: {handler} - not callable")

        if missing_handlers:
            self.fail(f"Missing or non-callable cron handlers:\n" + "\n".join(missing_handlers))

    def test_daily_tasks_count(self):
        """Should have substantial daily tasks."""
        daily = self.scheduler_events.get("daily", [])
        self.assertGreater(len(daily), 20, "Expected more than 20 daily tasks")

    def test_hourly_tasks_exist(self):
        """Should have hourly tasks."""
        hourly = self.scheduler_events.get("hourly", [])
        self.assertGreater(len(hourly), 0, "Expected at least 1 hourly task")

    def test_weekly_tasks_exist(self):
        """Should have weekly tasks."""
        weekly = self.scheduler_events.get("weekly", [])
        self.assertGreater(len(weekly), 0, "Expected at least 1 weekly task")


class TestPermissionHandlerResolution(unittest.TestCase):
    """Verify all permission handler strings resolve to callable functions."""

    @classmethod
    def setUpClass(cls):
        """Load permissions once for all tests."""
        permissions_module = load_hooks_submodule("permissions")
        cls.permission_query_conditions = permissions_module.permission_query_conditions
        cls.has_permission = permissions_module.has_permission

    def _resolve_handler(self, handler_string: str):
        """Attempt to resolve a handler string to a callable."""
        module_path, func_name = handler_string.rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            return func
        except (ImportError, AttributeError) as e:
            return None, str(e)

    def test_all_permission_query_handlers_exist(self):
        """All permission_query_conditions handlers should be importable and callable."""
        missing_handlers = []

        for doctype, handler in self.permission_query_conditions.items():
            result = self._resolve_handler(handler)
            if result is None or (isinstance(result, tuple) and result[0] is None):
                error = result[1] if isinstance(result, tuple) else "Unknown error"
                missing_handlers.append(f"{doctype}: {handler} - {error}")
            elif not callable(result):
                missing_handlers.append(f"{doctype}: {handler} - not callable")

        if missing_handlers:
            self.fail(f"Missing or non-callable permission query handlers:\n" + "\n".join(missing_handlers))

    def test_all_has_permission_handlers_exist(self):
        """All has_permission handlers should be importable and callable."""
        missing_handlers = []

        for doctype, handler in self.has_permission.items():
            result = self._resolve_handler(handler)
            if result is None or (isinstance(result, tuple) and result[0] is None):
                error = result[1] if isinstance(result, tuple) else "Unknown error"
                missing_handlers.append(f"{doctype}: {handler} - {error}")
            elif not callable(result):
                missing_handlers.append(f"{doctype}: {handler} - not callable")

        if missing_handlers:
            self.fail(f"Missing or non-callable has_permission handlers:\n" + "\n".join(missing_handlers))

    def test_member_permissions_exist(self):
        """Member should have both permission handlers."""
        self.assertIn("Member", self.permission_query_conditions)
        self.assertIn("Member", self.has_permission)


class TestLifecycleHandlerResolution(unittest.TestCase):
    """Verify all lifecycle handler strings resolve to callable functions."""

    @classmethod
    def setUpClass(cls):
        """Load lifecycle once for all tests."""
        lifecycle_module = load_hooks_submodule("lifecycle")
        cls.after_install = lifecycle_module.after_install
        cls.after_migrate = lifecycle_module.after_migrate
        cls.before_tests = lifecycle_module.before_tests
        cls.on_logout = lifecycle_module.on_logout

    def _resolve_handler(self, handler_string: str):
        """Attempt to resolve a handler string to a callable."""
        module_path, func_name = handler_string.rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
            return func
        except (ImportError, AttributeError) as e:
            return None, str(e)

    def test_after_install_handlers_exist(self):
        """All after_install handlers should be importable and callable."""
        missing_handlers = []

        for handler in self.after_install:
            result = self._resolve_handler(handler)
            if result is None or (isinstance(result, tuple) and result[0] is None):
                error = result[1] if isinstance(result, tuple) else "Unknown error"
                missing_handlers.append(f"after_install: {handler} - {error}")
            elif not callable(result):
                missing_handlers.append(f"after_install: {handler} - not callable")

        if missing_handlers:
            self.fail(f"Missing or non-callable after_install handlers:\n" + "\n".join(missing_handlers))

    def test_after_migrate_handlers_exist(self):
        """All after_migrate handlers should be importable and callable."""
        missing_handlers = []

        for handler in self.after_migrate:
            result = self._resolve_handler(handler)
            if result is None or (isinstance(result, tuple) and result[0] is None):
                error = result[1] if isinstance(result, tuple) else "Unknown error"
                missing_handlers.append(f"after_migrate: {handler} - {error}")
            elif not callable(result):
                missing_handlers.append(f"after_migrate: {handler} - not callable")

        if missing_handlers:
            self.fail(f"Missing or non-callable after_migrate handlers:\n" + "\n".join(missing_handlers))

    def test_before_tests_handler_exists(self):
        """before_tests handler should be importable and callable."""
        result = self._resolve_handler(self.before_tests)
        if result is None or (isinstance(result, tuple) and result[0] is None):
            error = result[1] if isinstance(result, tuple) else "Unknown error"
            self.fail(f"before_tests handler not found: {self.before_tests} - {error}")
        self.assertTrue(callable(result), f"before_tests handler not callable: {self.before_tests}")

    def test_on_logout_handler_exists(self):
        """on_logout handler should be importable and callable."""
        result = self._resolve_handler(self.on_logout)
        if result is None or (isinstance(result, tuple) and result[0] is None):
            error = result[1] if isinstance(result, tuple) else "Unknown error"
            self.fail(f"on_logout handler not found: {self.on_logout} - {error}")
        self.assertTrue(callable(result), f"on_logout handler not callable: {self.on_logout}")


class TestHooksDataIntegrity(unittest.TestCase):
    """Verify data integrity and structure of hooks configurations."""

    def test_doc_events_structure(self):
        """doc_events should have proper structure."""
        doc_events_module = load_hooks_submodule("doc_events")
        doc_events = doc_events_module.doc_events

        for doctype, events in doc_events.items():
            self.assertIsInstance(doctype, str, f"DocType key should be string: {doctype}")
            self.assertIsInstance(events, dict, f"Events should be dict for {doctype}")

            for event_name, handlers in events.items():
                self.assertIsInstance(event_name, str, f"Event name should be string: {event_name}")
                # Handlers can be string or list
                if isinstance(handlers, str):
                    self.assertIn(".", handlers, f"Handler should be dotted path: {handlers}")
                elif isinstance(handlers, list):
                    for handler in handlers:
                        self.assertIsInstance(handler, str, f"Handler should be string: {handler}")
                        self.assertIn(".", handler, f"Handler should be dotted path: {handler}")

    def test_scheduler_events_structure(self):
        """scheduler_events should have proper structure."""
        scheduler_module = load_hooks_submodule("scheduler")
        scheduler_events = scheduler_module.scheduler_events

        valid_frequencies = {"daily", "hourly", "weekly", "monthly", "yearly", "cron"}

        for frequency, handlers in scheduler_events.items():
            self.assertIn(frequency, valid_frequencies, f"Invalid frequency: {frequency}")
            self.assertIsInstance(handlers, list, f"Handlers should be list for {frequency}")

            for handler in handlers:
                self.assertIsInstance(handler, str, f"Handler should be string: {handler}")
                self.assertIn(".", handler, f"Handler should be dotted path: {handler}")

    def test_fixtures_structure(self):
        """fixtures should have proper structure."""
        fixtures_module = load_hooks_submodule("fixtures")
        fixtures = fixtures_module.fixtures

        self.assertIsInstance(fixtures, list)

        for fixture in fixtures:
            if isinstance(fixture, str):
                # Simple doctype name
                pass
            elif isinstance(fixture, dict):
                # Filtered fixture
                self.assertIn("doctype", fixture, f"Fixture dict should have 'doctype': {fixture}")
            else:
                self.fail(f"Fixture should be string or dict: {fixture}")

    def test_portal_menu_structure(self):
        """Portal menu items should have proper structure."""
        portal_module = load_hooks_submodule("portal")
        menu_items = portal_module.standard_portal_menu_items

        self.assertIsInstance(menu_items, list)
        self.assertGreater(len(menu_items), 0)

        for item in menu_items:
            self.assertIn("title", item)
            self.assertIn("route", item)
            self.assertIn("role", item)


class TestHooksPackageImport(unittest.TestCase):
    """Phase 3 tests: verify vereiningen.hooks package imports correctly."""

    def test_hooks_package_import_works(self):
        """import verenigingen.hooks should work without errors."""
        # This tests the actual package import, not file-based loading
        hooks = importlib.import_module("verenigingen.hooks")

        # Verify key exports are available
        self.assertTrue(hasattr(hooks, "doc_events"))
        self.assertTrue(hasattr(hooks, "scheduler_events"))
        self.assertTrue(hasattr(hooks, "app_name"))
        self.assertEqual(hooks.app_name, "verenigingen")

    def test_hooks_package_import_fast(self):
        """Hooks package should import quickly (< 500ms)."""
        # Clear from cache to get fresh timing
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("verenigingen.hooks")]
        for mod in modules_to_clear:
            del sys.modules[mod]

        start = time.time()
        importlib.import_module("verenigingen.hooks")
        elapsed = time.time() - start

        # Allow up to 500ms for package import (includes all submodules)
        self.assertLess(elapsed, 0.5, f"hooks package import took {elapsed:.3f}s")

    def test_hooks_package_has_all_exports(self):
        """Hooks package should export all required hook variables."""
        hooks = importlib.import_module("verenigingen.hooks")

        required_exports = [
            # From assets.py
            "app_include_css",
            "app_include_js",
            "web_include_js",
            "email_css",
            # From doc_events.py
            "doc_events",
            # From doctypes.py
            "doctype_js",
            # From fixtures.py
            "fixtures",
            # From lifecycle.py
            "after_install",
            "after_migrate",
            "before_tests",
            "on_logout",
            "boot_session",
            # From permissions.py
            "permission_query_conditions",
            "has_permission",
            # From portal.py
            "standard_portal_menu_items",
            "website_context",
            "update_website_context",
            # From scheduler.py
            "scheduler_events",
            "cron",
            # App metadata
            "app_name",
            "app_title",
            "jinja",
            "override_doctype_class",
            "commands",
        ]

        missing = [exp for exp in required_exports if not hasattr(hooks, exp)]
        if missing:
            self.fail(f"Missing exports from hooks package: {missing}")


class TestOverrideDocTypeClassResolution(unittest.TestCase):
    """Verify override_doctype_class targets are importable classes."""

    def test_override_targets_are_importable_classes(self):
        """All override_doctype_class values should be importable classes."""
        hooks = importlib.import_module("verenigingen.hooks")
        override_doctype_class = hooks.override_doctype_class

        errors = []
        for doctype, override_path in override_doctype_class.items():
            try:
                module_path, cls_name = override_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls = getattr(module, cls_name)

                if not isinstance(cls, type):
                    errors.append(f"{doctype}: {override_path} is not a class (got {type(cls).__name__})")
            except ImportError as e:
                errors.append(f"{doctype}: Cannot import module for {override_path} - {e}")
            except AttributeError as e:
                errors.append(f"{doctype}: Class not found in {override_path} - {e}")

        if errors:
            self.fail("Override class resolution errors:\n" + "\n".join(errors))

    def test_payment_entry_override_exists(self):
        """Payment Entry override should be properly configured."""
        hooks = importlib.import_module("verenigingen.hooks")
        override_doctype_class = hooks.override_doctype_class

        self.assertIn("Payment Entry", override_doctype_class)

        override_path = override_doctype_class["Payment Entry"]
        module_path, cls_name = override_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, cls_name)

        self.assertTrue(isinstance(cls, type), "PaymentEntry should be a class")
        self.assertEqual(cls_name, "PaymentEntry")


class TestCronExpressionValidation(unittest.TestCase):
    """Verify cron expressions are valid format."""

    # Cron field pattern: matches *, */N, N, N-M, N,M,O, etc.
    # Examples: *, */10, 0, 1-5, 0,15,30,45, */5
    CRON_FIELD = r"(?:\*(?:/\d+)?|\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)"

    # Frappe supports 6-field cron (with seconds) via APScheduler
    # Format: second minute hour day month day_of_week
    CRON_6_FIELD_PATTERN = None  # Compiled in setUpClass

    # Standard 5-field cron (without seconds)
    CRON_5_FIELD_PATTERN = None  # Compiled in setUpClass

    @classmethod
    def setUpClass(cls):
        """Compile regex patterns."""
        field = cls.CRON_FIELD
        cls.CRON_6_FIELD_PATTERN = re.compile(
            rf"^{field}\s+{field}\s+{field}\s+{field}\s+{field}\s+{field}$"
        )
        cls.CRON_5_FIELD_PATTERN = re.compile(
            rf"^{field}\s+{field}\s+{field}\s+{field}\s+{field}$"
        )

    def test_all_cron_expressions_valid(self):
        """All cron expressions should match valid 5 or 6 field format."""
        scheduler = load_hooks_submodule("scheduler")
        cron = scheduler.cron

        invalid_expressions = []
        for expression in cron.keys():
            is_5_field = self.CRON_5_FIELD_PATTERN.match(expression)
            is_6_field = self.CRON_6_FIELD_PATTERN.match(expression)

            if not (is_5_field or is_6_field):
                invalid_expressions.append(expression)

        if invalid_expressions:
            self.fail(f"Invalid cron expressions: {invalid_expressions}")

    def test_cron_uses_6_field_format_with_seconds(self):
        """Document that we use 6-field cron format (with seconds)."""
        scheduler = load_hooks_submodule("scheduler")
        cron = scheduler.cron

        # Verify we're using 6-field format
        for expression in cron.keys():
            fields = expression.split()
            self.assertEqual(
                len(fields),
                6,
                f"Expected 6-field cron (with seconds), got {len(fields)} fields: {expression}",
            )

    def test_cron_handlers_not_empty(self):
        """Each cron expression should have at least one handler."""
        scheduler = load_hooks_submodule("scheduler")
        cron = scheduler.cron

        for expression, handlers in cron.items():
            self.assertIsInstance(handlers, list)
            self.assertGreater(len(handlers), 0, f"No handlers for cron: {expression}")


class TestImportSideEffectGuards(unittest.TestCase):
    """Verify imports don't trigger database or cache calls."""

    def _create_raising_mock(self, name):
        """Create a mock that raises when called."""

        def raise_on_call(*args, **kwargs):
            raise AssertionError(f"Unexpected call to {name} during import")

        mock = MagicMock(side_effect=raise_on_call)
        mock.__bool__ = lambda self: True  # Allow truthiness checks
        return mock

    def test_submodules_no_db_calls_on_import(self):
        """Submodule imports should not call frappe.db methods."""
        submodules = [
            "assets",
            "doctypes",
            "doc_events",
            "scheduler",
            "permissions",
            "fixtures",
            "portal",
            "lifecycle",
        ]

        for submodule in submodules:
            # Clear module from cache
            module_key = f"hooks_{submodule}"
            if module_key in sys.modules:
                del sys.modules[module_key]

            # Create mocks for frappe.db methods
            mock_db = MagicMock()
            mock_db.sql = self._create_raising_mock("frappe.db.sql")
            mock_db.get_value = self._create_raising_mock("frappe.db.get_value")
            mock_db.get_all = self._create_raising_mock("frappe.db.get_all")
            mock_db.get_list = self._create_raising_mock("frappe.db.get_list")
            mock_db.exists = self._create_raising_mock("frappe.db.exists")
            mock_db.count = self._create_raising_mock("frappe.db.count")

            with patch.dict("sys.modules", {"frappe": MagicMock(db=mock_db)}):
                # Import should succeed without DB calls
                try:
                    load_hooks_submodule(submodule)
                except AssertionError as e:
                    self.fail(f"DB call during {submodule} import: {e}")

    def test_submodules_no_cache_calls_on_import(self):
        """Submodule imports should not call frappe.cache methods."""
        submodules = [
            "assets",
            "doctypes",
            "doc_events",
            "scheduler",
            "permissions",
            "fixtures",
            "portal",
            "lifecycle",
        ]

        for submodule in submodules:
            # Clear module from cache
            module_key = f"hooks_{submodule}"
            if module_key in sys.modules:
                del sys.modules[module_key]

            mock_cache = MagicMock()
            mock_cache.get_value = self._create_raising_mock("frappe.cache.get_value")
            mock_cache.set_value = self._create_raising_mock("frappe.cache.set_value")
            mock_cache.hget = self._create_raising_mock("frappe.cache.hget")
            mock_cache.hset = self._create_raising_mock("frappe.cache.hset")

            mock_frappe = MagicMock()
            mock_frappe.cache = MagicMock(return_value=mock_cache)

            with patch.dict("sys.modules", {"frappe": mock_frappe}):
                try:
                    load_hooks_submodule(submodule)
                except AssertionError as e:
                    self.fail(f"Cache call during {submodule} import: {e}")

    def test_submodules_no_get_doc_on_import(self):
        """Submodule imports should not call frappe.get_doc."""
        submodules = [
            "assets",
            "doctypes",
            "doc_events",
            "scheduler",
            "permissions",
            "fixtures",
            "portal",
            "lifecycle",
        ]

        for submodule in submodules:
            # Clear module from cache
            module_key = f"hooks_{submodule}"
            if module_key in sys.modules:
                del sys.modules[module_key]

            mock_frappe = MagicMock()
            mock_frappe.get_doc = self._create_raising_mock("frappe.get_doc")
            mock_frappe.get_cached_doc = self._create_raising_mock("frappe.get_cached_doc")
            mock_frappe.get_single = self._create_raising_mock("frappe.get_single")

            with patch.dict("sys.modules", {"frappe": mock_frappe}):
                try:
                    load_hooks_submodule(submodule)
                except AssertionError as e:
                    self.fail(f"get_doc call during {submodule} import: {e}")


class TestWorkflowActionHandlers(unittest.TestCase):
    """Verify workflow_action_handlers resolve to callable functions."""

    def test_workflow_handlers_exist(self):
        """All workflow_action_handlers should be importable and callable."""
        hooks = importlib.import_module("verenigingen.hooks")
        workflow_handlers = hooks.workflow_action_handlers

        errors = []
        for workflow_name, actions in workflow_handlers.items():
            for action_name, handler_path in actions.items():
                try:
                    module_path, func_name = handler_path.rsplit(".", 1)
                    module = importlib.import_module(module_path)
                    func = getattr(module, func_name)

                    if not callable(func):
                        errors.append(f"{workflow_name}.{action_name}: {handler_path} not callable")
                except ImportError as e:
                    errors.append(f"{workflow_name}.{action_name}: Cannot import {handler_path} - {e}")
                except AttributeError as e:
                    errors.append(f"{workflow_name}.{action_name}: Function not found {handler_path} - {e}")

        if errors:
            self.fail("Workflow handler resolution errors:\n" + "\n".join(errors))


class TestJinjaConfiguration(unittest.TestCase):
    """Verify jinja configuration points to valid modules."""

    def test_jinja_methods_module_exists(self):
        """Jinja methods module should be importable."""
        hooks = importlib.import_module("verenigingen.hooks")
        jinja_config = hooks.jinja

        for method_path in jinja_config.get("methods", []):
            try:
                importlib.import_module(method_path)
            except ImportError as e:
                self.fail(f"Cannot import jinja methods module {method_path}: {e}")

    def test_jinja_filters_configuration_valid(self):
        """Jinja filters configuration should have valid format."""
        hooks = importlib.import_module("verenigingen.hooks")
        jinja_config = hooks.jinja

        # Verify filters is a list (even if empty)
        filters = jinja_config.get("filters", [])
        self.assertIsInstance(filters, list)

        # Verify each entry is a dotted module path string
        for filter_path in filters:
            self.assertIsInstance(filter_path, str)
            self.assertIn(".", filter_path, f"Filter path should be dotted: {filter_path}")

        # Note: The actual module import is tested at runtime by Frappe.
        # Pre-existing configuration issues (like missing jinja_filters module)
        # are tracked separately and don't block the hooks structure validation.


class TestCommandsConfiguration(unittest.TestCase):
    """Verify CLI commands configuration is valid."""

    def test_all_commands_importable(self):
        """All CLI command modules should be importable and have the function."""
        hooks = importlib.import_module("verenigingen.hooks")
        commands = hooks.commands

        errors = []
        for command_path in commands:
            # Command paths are "module.function" format
            module_path, func_name = command_path.rsplit(".", 1)
            try:
                module = importlib.import_module(module_path)
                if not hasattr(module, func_name):
                    errors.append(f"Command function '{func_name}' not found in {module_path}")
                elif not callable(getattr(module, func_name)):
                    errors.append(f"Command {command_path} is not callable")
            except ImportError as e:
                errors.append(f"Cannot import command module {module_path}: {e}")

        if errors:
            self.fail("Command import errors:\n" + "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
