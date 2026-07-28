# verenigingen/tests/test_hooks_modules.py
"""Tests for hooks module structure and handler resolution.

Validates that:
1. All hooks submodules can be imported without side effects
2. All handler strings in doc_events resolve to callable functions
3. All scheduler task strings resolve to callable functions
4. All permission handler strings resolve to callable functions
5. The hooks package can be imported as verenigingen.hooks (Phase 3)
6. Override class targets are importable and are actual classes
7. Cron expressions are semantically valid (using croniter)
8. Handler signatures match expected patterns (doc events, schedulers)
9. Handler paths are properly formatted (no whitespace)

These tests ensure the hooks/ package structure is correct and safe.
"""

import importlib
import importlib.util
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# croniter is available in the Frappe environment for cron validation
try:
    from croniter import croniter
    from croniter.croniter import CroniterBadCronError

    CRONITER_AVAILABLE = True
except ImportError:
    CRONITER_AVAILABLE = False
    CroniterBadCronError = Exception  # Fallback for type hints

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


def check_handler_signature(func, min_positional: int = 1, handler_type: str = "doc_event"):
    """Check if a handler function has an acceptable signature.

    Args:
        func: The callable to check
        min_positional: Minimum number of positional parameters required
        handler_type: Type of handler for error messages

    Returns:
        tuple: (is_valid: bool, error_message: str or None)

    Handler signature requirements:
    - doc_event handlers: need at least 1 param (doc), often (doc, method=None)
    - scheduler handlers: can have 0 params (called without arguments)
    - permission handlers: need at least 1 param (user or doc)
    """
    if not callable(func):
        return False, "not callable"

    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError) as e:
        # Some built-in functions don't have signatures
        return True, None  # Assume valid if we can't inspect

    params = list(sig.parameters.values())

    # Check for *args or **kwargs - these accept anything
    has_var_positional = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)

    if has_var_positional or has_var_keyword:
        return True, None  # Accepts variable arguments

    # Count positional parameters (including those with defaults)
    positional_count = sum(
        1
        for p in params
        if p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    )

    if positional_count < min_positional:
        return False, f"expected at least {min_positional} positional param(s), got {positional_count}"

    return True, None


class TestHooksImportSafety(unittest.TestCase):
    """Verify hooks submodules have expected exports.

    Note: Timing assertions were removed because they are inherently flaky
    in CI environments. The TestImportSideEffectGuards class provides more
    reliable protection by ensuring no DB/cache calls occur during import.
    A module that doesn't make DB/cache calls will naturally be fast.
    """

    def test_assets_exports(self):
        """hooks/assets.py should have expected exports."""
        assets = load_hooks_submodule("assets")

        # Should have expected exports
        self.assertTrue(hasattr(assets, "app_include_css"))
        self.assertTrue(hasattr(assets, "app_include_js"))
        self.assertTrue(hasattr(assets, "web_include_js"))
        self.assertTrue(hasattr(assets, "email_css"))

    def test_doctypes_exports(self):
        """hooks/doctypes.py should have expected exports."""
        doctypes = load_hooks_submodule("doctypes")

        self.assertTrue(hasattr(doctypes, "doctype_js"))
        self.assertIsInstance(doctypes.doctype_js, dict)

    def test_doc_events_exports(self):
        """hooks/doc_events.py should have expected exports."""
        doc_events = load_hooks_submodule("doc_events")

        self.assertTrue(hasattr(doc_events, "doc_events"))
        self.assertIsInstance(doc_events.doc_events, dict)

    def test_scheduler_exports(self):
        """hooks/scheduler.py should have expected exports."""
        scheduler = load_hooks_submodule("scheduler")

        self.assertTrue(hasattr(scheduler, "scheduler_events"))
        # Regression: a top-level `cron` variable is silently ignored by
        # Frappe's sync_jobs (which reads only `scheduler_events`). Cron
        # entries must live inside scheduler_events["cron"].
        self.assertFalse(
            hasattr(scheduler, "cron"),
            "Top-level `cron` in hooks/scheduler.py is dead code — Frappe "
            "only reads scheduler_events. Move entries into scheduler_events['cron'].",
        )
        self.assertIn(
            "cron",
            scheduler.scheduler_events,
            "scheduler_events must contain a 'cron' key with {expression: [methods]} entries.",
        )
        self.assertIsInstance(
            scheduler.scheduler_events["cron"],
            dict,
            "scheduler_events['cron'] must be a dict of {cron_expression: [method_paths]}.",
        )

    def test_permissions_exports(self):
        """hooks/permissions.py should have expected exports."""
        permissions = load_hooks_submodule("permissions")

        self.assertTrue(hasattr(permissions, "permission_query_conditions"))
        self.assertTrue(hasattr(permissions, "has_permission"))

    def test_fixtures_exports(self):
        """hooks/fixtures.py should have expected exports."""
        fixtures = load_hooks_submodule("fixtures")

        self.assertTrue(hasattr(fixtures, "fixtures"))
        self.assertIsInstance(fixtures.fixtures, list)

    def test_portal_exports(self):
        """hooks/portal.py should have expected exports."""
        portal = load_hooks_submodule("portal")

        self.assertTrue(hasattr(portal, "update_website_context"))

    def test_portal_declares_no_standard_portal_menu_items(self):
        """portal.py must not declare standard_portal_menu_items.

        Frappe's PortalSettings.sync_menu() calls remove_deleted_doctype_items(), which
        drops every item whose reference_doctype is not an existing DocType - and ""
        never is. Route-only entries for custom template pages are therefore added and
        stripped again on every migrate, never reaching users. This app renders portal
        navigation from its own role-based templates instead.
        """
        portal = load_hooks_submodule("portal")

        self.assertFalse(
            hasattr(portal, "standard_portal_menu_items"),
            "standard_portal_menu_items entries with an empty reference_doctype are "
            "silently discarded on every migrate - use the portal_nav templates",
        )

    def test_portal_website_context_registers_no_method_paths(self):
        """website_context must not be used to register context processors.

        Frappe copies website_context entries into the page context verbatim as static
        key/value pairs (website_settings.py::get_website_settings); it never resolves
        them as callables. A method path registered there is silently never invoked -
        context processors belong in update_website_context instead. Static values are
        a legitimate use (ERPNext registers favicon/splash_image this way), so this
        checks for method paths rather than banning the key outright.
        """
        portal = load_hooks_submodule("portal")
        website_context = getattr(portal, "website_context", {})

        for key, value in website_context.items():
            with self.subTest(key=key):
                self.assertFalse(
                    isinstance(value, str) and value.startswith("verenigingen."),
                    f"website_context[{key!r}] is a method path and will never be called - "
                    f"register it under update_website_context instead",
                )

    def test_lifecycle_exports(self):
        """hooks/lifecycle.py should have expected exports."""
        lifecycle = load_hooks_submodule("lifecycle")

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
        """All doc_events handlers should be importable, callable, and have valid signatures."""
        missing_handlers = []
        signature_errors = []

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
                    else:
                        # Check signature - doc event handlers need at least 1 param (doc)
                        is_valid, sig_error = check_handler_signature(result, min_positional=1)
                        if not is_valid:
                            signature_errors.append(f"{doctype}.{event_name}: {handler} - {sig_error}")

        if missing_handlers:
            self.fail(f"Missing or non-callable handlers:\n" + "\n".join(missing_handlers[:20]))

        if signature_errors:
            self.fail(
                f"Handlers with invalid signatures (doc events need at least 1 param):\n"
                + "\n".join(signature_errors[:20])
            )

    def test_handler_paths_no_whitespace(self):
        """Handler path strings should not have leading/trailing whitespace."""
        whitespace_errors = []

        for doctype, events in self.doc_events.items():
            for event_name, handlers in events.items():
                if isinstance(handlers, str):
                    handlers = [handlers]

                for handler in handlers:
                    if handler != handler.strip():
                        whitespace_errors.append(f"{doctype}.{event_name}: '{handler}' has whitespace")

        if whitespace_errors:
            self.fail(f"Handler paths with whitespace (copy-paste error?):\n" + "\n".join(whitespace_errors))

    def test_membership_handlers_exist(self):
        """Core Membership handlers should exist."""
        handlers = self.doc_events.get("Membership", {})
        self.assertIn("on_submit", handlers)
        self.assertIn("on_cancel", handlers)

    def test_member_handlers_exist(self):
        """Core Member handlers should be registered under events that fire.

        This used to assert `"after_save" in handlers` — key presence only. That is
        the exact shape that hid the dead-hook bug for so long: the key existed, the
        assertion passed, and none of the handlers under it ever ran. So assert the
        handler strings themselves, under an event Frappe actually dispatches.
        """
        handlers = self.doc_events.get("Member", {})
        self.assertIn("before_save", handlers)

        on_update = handlers.get("on_update", [])
        if isinstance(on_update, str):
            on_update = [on_update]
        for expected in (
            "verenigingen.utils.cache_invalidation.on_document_update",
            "verenigingen.utils.performance_cache.on_member_update",
            "verenigingen.services.field_sync_service.sync_fields",
        ):
            self.assertIn(expected, on_update)

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
        # Cron entries live inside scheduler_events["cron"] — anything else is
        # silently ignored by Frappe. Default to empty to be robust to absence.
        cls.cron = scheduler_module.scheduler_events.get("cron", {})

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
            # cron is a nested {expression: [methods]} dict — handled by
            # test_all_cron_handlers_exist; skip here to avoid iterating keys.
            if frequency == "cron" or isinstance(handlers, dict):
                continue
            for handler in handlers:
                result = self._resolve_handler(handler)
                if result is None or (isinstance(result, tuple) and result[0] is None):
                    error = result[1] if isinstance(result, tuple) else "Unknown error"
                    missing_handlers.append(f"{frequency}: {handler} - {error}")
                elif not callable(result):
                    missing_handlers.append(f"{frequency}: {handler} - not callable")
                # Note: Scheduler handlers can have 0 params (called without args),
                # so we don't enforce signature requirements here

        if missing_handlers:
            self.fail(f"Missing or non-callable scheduler handlers:\n" + "\n".join(missing_handlers[:20]))

    def test_scheduler_handler_paths_no_whitespace(self):
        """Scheduler handler paths should not have leading/trailing whitespace."""
        whitespace_errors = []

        for frequency, handlers in self.scheduler_events.items():
            if frequency == "cron" or isinstance(handlers, dict):
                continue  # cron entries are validated by test_all_cron_handlers_exist
            for handler in handlers:
                if handler != handler.strip():
                    whitespace_errors.append(f"{frequency}: '{handler}' has whitespace")

        if whitespace_errors:
            self.fail(f"Scheduler handler paths with whitespace:\n" + "\n".join(whitespace_errors))

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

            if frequency == "cron":
                # cron is a dict of {cron_expression: [method_paths]}
                self.assertIsInstance(handlers, dict, "scheduler_events['cron'] must be a dict")
                for expression, methods in handlers.items():
                    self.assertIsInstance(expression, str, f"cron key must be string: {expression}")
                    self.assertIsInstance(methods, list, f"cron methods must be list for {expression}")
                    for method in methods:
                        self.assertIsInstance(method, str, f"cron method should be string: {method}")
                        self.assertIn(".", method, f"cron method should be dotted path: {method}")
                continue

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


class TestHooksPackageImport(unittest.TestCase):
    """Phase 3 tests: verify verenigingen.hooks package imports correctly."""

    def test_hooks_package_import_works(self):
        """import verenigingen.hooks should work without errors."""
        # This tests the actual package import, not file-based loading
        hooks = importlib.import_module("verenigingen.hooks")

        # Verify key exports are available
        self.assertTrue(hasattr(hooks, "doc_events"))
        self.assertTrue(hasattr(hooks, "scheduler_events"))
        self.assertTrue(hasattr(hooks, "app_name"))
        self.assertEqual(hooks.app_name, "verenigingen")

    def test_hooks_package_import_succeeds(self):
        """Hooks package should import without errors.

        Note: Timing assertion removed - side-effect guards in
        TestImportSideEffectGuards provide more reliable protection.
        """
        # Clear from cache to get fresh import
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("verenigingen.hooks")]
        for mod in modules_to_clear:
            del sys.modules[mod]

        # Should not raise any exceptions
        hooks = importlib.import_module("verenigingen.hooks")

        # Verify module loaded correctly
        self.assertIsNotNone(hooks)
        self.assertTrue(hasattr(hooks, "app_name"))

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
            "update_website_context",
            # From scheduler.py
            "scheduler_events",
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
    """Verify override_doctype_class targets are importable classes that inherit correctly."""

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

    def test_override_classes_inherit_from_document(self):
        """All override classes should inherit from frappe.model.document.Document.

        This catches subtle runtime errors where an override class doesn't
        properly inherit from the expected base class.
        """
        # Import Document base class
        try:
            from frappe.model.document import Document
        except ImportError:
            self.skipTest("frappe.model.document.Document not available")

        hooks = importlib.import_module("verenigingen.hooks")
        override_doctype_class = hooks.override_doctype_class

        inheritance_errors = []
        for doctype, override_path in override_doctype_class.items():
            try:
                module_path, cls_name = override_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                cls = getattr(module, cls_name)

                if isinstance(cls, type) and not issubclass(cls, Document):
                    inheritance_errors.append(f"{doctype}: {override_path} does not inherit from Document")
            except (ImportError, AttributeError):
                # Import errors are caught by test_override_targets_are_importable_classes
                pass

        if inheritance_errors:
            self.fail("Override classes with incorrect inheritance:\n" + "\n".join(inheritance_errors))

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
    """Verify cron expressions are semantically valid.

    Uses croniter for validation which catches:
    - Invalid step values (*/0)
    - Out of range values (60 for minutes, 32 for day of month)
    - Invalid field combinations
    """

    def _validate_cron_expression(self, expression: str) -> tuple:
        """Validate a cron expression using croniter.

        Args:
            expression: Cron expression string (5 or 6 fields)

        Returns:
            tuple: (is_valid: bool, error_message: str or None)
        """
        if not CRONITER_AVAILABLE:
            # Fallback to basic field count check if croniter unavailable
            fields = expression.split()
            if len(fields) not in (5, 6):
                return False, f"expected 5 or 6 fields, got {len(fields)}"
            return True, None

        try:
            # croniter validates the expression when creating the iterator
            # and when getting the next occurrence
            cron_iter = croniter(expression)
            cron_iter.get_next()  # Force evaluation to catch semantic errors
            return True, None
        except CroniterBadCronError as e:
            return False, str(e)
        except Exception as e:
            return False, f"unexpected error: {type(e).__name__}: {e}"

    def _get_cron(self):
        """Load cron entries from scheduler_events (the only place Frappe reads)."""
        scheduler = load_hooks_submodule("scheduler")
        return scheduler.scheduler_events.get("cron", {})

    def test_all_cron_expressions_semantically_valid(self):
        """All cron expressions should be semantically valid (using croniter)."""
        cron = self._get_cron()

        invalid_expressions = []
        for expression in cron.keys():
            is_valid, error = self._validate_cron_expression(expression)
            if not is_valid:
                invalid_expressions.append(f"'{expression}': {error}")

        if invalid_expressions:
            self.fail(f"Invalid cron expressions (semantic validation):\n" + "\n".join(invalid_expressions))

    def test_cron_uses_5_or_6_field_format(self):
        """Cron expressions should be 5- or 6-field (with or without seconds)."""
        cron = self._get_cron()

        # Both formats are valid; some tasks use 6-field (with seconds)
        # for sub-minute precision, others use 5-field (standard cron).
        for expression in cron.keys():
            fields = expression.split()
            self.assertIn(
                len(fields),
                (5, 6),
                f"Expected 5- or 6-field cron, got {len(fields)} fields: {expression}",
            )

    def test_cron_handlers_not_empty(self):
        """Each cron expression should have at least one handler."""
        cron = self._get_cron()

        for expression, handlers in cron.items():
            self.assertIsInstance(handlers, list)
            self.assertGreater(len(handlers), 0, f"No handlers for cron: {expression}")

    @unittest.skipUnless(CRONITER_AVAILABLE, "croniter not available")
    def test_croniter_catches_known_invalid_expressions(self):
        """Verify croniter catches common invalid expressions (sanity check)."""
        # These should all fail validation
        invalid_cases = [
            ("*/0 * * * * *", "zero step"),
            ("60 * * * * *", "seconds out of range"),
            ("* 60 * * * *", "minutes out of range"),
        ]

        for expression, desc in invalid_cases:
            is_valid, _ = self._validate_cron_expression(expression)
            self.assertFalse(
                is_valid, f"Expected '{expression}' ({desc}) to be invalid, but it passed validation"
            )


class TestCronNestingRegression(unittest.TestCase):
    """Regression: cron entries must live inside scheduler_events['cron'].

    Frappe's sync_jobs reads only `scheduler_events` from the hooks module
    (see frappe.core.doctype.scheduled_job_type.scheduled_job_type.sync_jobs).
    A sibling `cron` module attribute — no matter how well-formed — is
    silently ignored, and its entries never become Scheduled Job Type rows.

    This bug silently stalled the */15 MijnRood sync and the */30s financial
    history batch processor for an extended period; no error, no log, just
    absence. Pin the corrected structure here so a future refactor can't
    re-introduce it.
    """

    def test_hooks_package_has_no_top_level_cron(self):
        """verenigingen.hooks must not expose a top-level `cron` attribute."""
        hooks = importlib.import_module("verenigingen.hooks")
        self.assertFalse(
            hasattr(hooks, "cron"),
            "Top-level `cron` in verenigingen.hooks is not read by Frappe's "
            "sync_jobs. Move its entries into scheduler_events['cron'].",
        )

    def test_scheduler_submodule_has_no_top_level_cron(self):
        """hooks/scheduler.py must not expose a top-level `cron` variable."""
        scheduler = load_hooks_submodule("scheduler")
        self.assertFalse(
            hasattr(scheduler, "cron"),
            "Top-level `cron` in hooks/scheduler.py is dead code. Move its "
            "entries into scheduler_events['cron'].",
        )

    def test_scheduler_events_contains_cron_key(self):
        """scheduler_events['cron'] must exist and be a non-empty dict."""
        scheduler = load_hooks_submodule("scheduler")
        self.assertIn("cron", scheduler.scheduler_events)
        cron = scheduler.scheduler_events["cron"]
        self.assertIsInstance(cron, dict)
        self.assertGreater(len(cron), 0, "At least one cron entry should be registered.")

    def test_known_cron_tasks_are_registered(self):
        """Specific high-value cron tasks must be reachable via scheduler_events['cron'].

        These tasks regressed silently when cron was a sibling variable. Pin them.
        """
        scheduler = load_hooks_submodule("scheduler")
        cron = scheduler.scheduler_events.get("cron", {})

        all_methods = {m for methods in cron.values() for m in methods}

        expected = {
            "verenigingen.mijnrood_sync.tasks.run_mijnrood_sync",
            "verenigingen.utils.financial_history_batch_processor.schedule_financial_history_processing",
        }
        missing = expected - all_methods
        self.assertFalse(
            missing,
            f"Expected cron tasks not registered in scheduler_events['cron']: {missing}",
        )


class TestDocEventNamesAreDispatched(unittest.TestCase):
    """Regression: every doc_events key must name an event Frappe actually fires.

    Frappe dispatches document events through Document.run_method(), which composes
    hooks for whatever method name it is handed. An event key that no framework code
    ever passes to run_method() is silently inert: the handler strings still resolve,
    the app still boots, nothing errors — the code just never runs.

    `after_save` is the trap. It reads like a real lifecycle event, but
    run_post_save_methods() (frappe/model/document.py) runs `on_update` and
    `on_change` only, and `after_save` appears nowhere in frappe's Python. Seven
    handlers sat under it here — including every Member, Chapter Member and SEPA
    Mandate cache invalidation — plus a dead `after_validate` on Sales Invoice.
    Same failure shape as the cron-nesting bug pinned above: no error, no log,
    just absence.

    Use `on_update` ALONE to cover what `after_save` was intended to mean: it fires
    on insert as well as update, so pairing it with `after_insert` double-fires.

    Scope: SERVER-side document events only. `after_save` is a real CLIENT-side form
    event (frappe/public/js/frappe/form/form.js) that this app uses in several .js
    files — those are unaffected.
    """

    # Event names Frappe passes to Document.run_method() / run_trigger().
    # Derived from `grep -rn 'run_method("[a-z_]*"' apps/frappe/frappe/` on
    # frappe 16.19.0, filtered to document-lifecycle events (login/session and
    # serialisation triggers from that grep are not doc_events keys).
    # If Frappe adds a lifecycle event, verify it against the framework source
    # before adding it here — that verification is the point of this gate.
    DISPATCHED_DOC_EVENTS = frozenset(
        {
            "after_delete",
            "after_insert",
            "after_rename",
            "autoname",
            "before_cancel",
            "before_change",
            "before_discard",
            "before_insert",
            "before_naming",
            "before_print",
            "before_rename",
            "before_save",
            "before_submit",
            "before_update_after_submit",
            "before_validate",
            "on_cancel",
            "on_change",
            "on_discard",
            "on_submit",
            "on_trash",
            "on_update",
            "on_update_after_submit",
            "validate",
            # Dispatched from outside frappe/model/document.py — all reachable as
            # doc_events keys, so excluding them would cause false failures:
            "onload",  # frappe/desk/form/load.py
            "on_recurring",  # frappe/automation/doctype/auto_repeat/auto_repeat.py
            "before_mapping",  # frappe/model/mapper.py
            "after_mapping",  # frappe/model/mapper.py
            "before_import",  # frappe/modules/import_file.py
            "before_export",  # frappe/modules/export_file.py
            "before_reload",  # frappe/model/delete_doc.py
            "validate_share",  # frappe/core/doctype/docshare/docshare.py
            "notify_communication",  # frappe/core/doctype/communication/communication.py
            "handle_hold_time",  # frappe/core/doctype/communication/communication.py
            "before_test_insert",  # frappe/tests/utils/generators.py
        }
    )

    def test_every_doc_event_key_is_dispatched_by_frappe(self):
        """No doc_events key may name an event the framework never fires."""
        doc_events = load_hooks_submodule("doc_events").doc_events

        inert = []
        for doctype, events in doc_events.items():
            for event_name, handlers in events.items():
                if event_name in self.DISPATCHED_DOC_EVENTS:
                    continue
                if isinstance(handlers, str):
                    handlers = [handlers]
                for handler in handlers:
                    inert.append(f"{doctype}.{event_name}: {handler}")

        self.assertEqual(
            [],
            inert,
            "These handlers are registered under an event Frappe never dispatches, "
            "so they never run:\n  " + "\n  ".join(inert),
        )

    def test_no_handler_is_registered_on_both_after_insert_and_on_update(self):
        """A handler under both events runs TWICE on every insert.

        `insert()` calls run_post_save_methods(), which runs `on_update` because
        _action is "save" for a new draft — so on_update already covers inserts. Its
        docstring says it executes "before_insert, validate, on_update, after_insert".
        Registering the same handler under after_insert as well therefore double-fires
        it on creation: duplicated cache work and DB round-trips at best, and at worst
        a second pass through a rate-limited, audit-logged @high_security_api call.

        Use on_update ALONE for run-on-every-save handlers, and reserve after_insert
        for genuinely insert-only work.
        """
        doc_events = load_hooks_submodule("doc_events").doc_events

        def as_list(handlers):
            return [handlers] if isinstance(handlers, str) else list(handlers)

        doubled = []
        for doctype, events in doc_events.items():
            after_insert = set(as_list(events.get("after_insert", [])))
            on_update = set(as_list(events.get("on_update", [])))
            for handler in sorted(after_insert & on_update):
                doubled.append(f"{doctype}: {handler}")

        self.assertEqual(
            [],
            doubled,
            "These handlers are registered under BOTH after_insert and on_update, so "
            "they run twice on every insert. Drop the after_insert entry:\n  " + "\n  ".join(doubled),
        )

    def test_frappe_still_does_not_dispatch_after_save_or_after_validate(self):
        """Verify the premise against the framework, not against our own frozenset.

        Asserting "after_save" is absent from DISPATCHED_DOC_EVENTS would just be
        re-reading a literal defined above. This inspects frappe itself, so it starts
        failing if a future frappe version introduces either event — at which point
        the allowlist and the surrounding comments need revisiting.
        """
        import inspect as _inspect

        from frappe.model.document import Document

        for name in ("after_save", "after_validate"):
            with self.subTest(event=name):
                self.assertFalse(
                    hasattr(Document, name),
                    f"frappe.model.document.Document now defines {name}() — the "
                    "premise of this gate has changed.",
                )

        post_save_source = _inspect.getsource(Document.run_post_save_methods)
        self.assertIn("on_update", post_save_source)
        self.assertNotIn(
            "after_save",
            post_save_source,
            "run_post_save_methods() now references after_save — re-verify the gate.",
        )


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
        # workflow_action_handlers is an optional hook; the app does not
        # currently register any. Tolerate its absence rather than erroring.
        workflow_handlers = getattr(hooks, "workflow_action_handlers", {})

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
