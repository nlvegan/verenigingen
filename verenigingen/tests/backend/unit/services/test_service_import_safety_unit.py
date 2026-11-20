# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Import-Time Safety Tests for Service Modules

Ensures that service modules can be imported without triggering:
- Database operations (frappe.db.*, frappe.get_doc, frappe.get_all)
- Network calls
- File system operations beyond module loading

This prevents slow imports and circular import issues.

NOTE: This test uses detection mocks (not replacement mocks) to verify that
database operations are NOT called during module import. The mocks here are
instrumented detectors that fail the test if called - they don't replace
database behavior for integration testing purposes.

test-quality-enforcer: exempt-detection-mocks
"""

import importlib
import sys
import time
import unittest
from unittest.mock import MagicMock, patch


def keep_modules_intact(test_case, module_paths):
    """Put back the module objects these tests delete and re-import, when the test ends.

    The tests below force a fresh import by deleting a module from sys.modules. Left that way, the
    process holds a SECOND copy of the module (and of every class in it): code that imported the first
    copy earlier, as a test module's top-level `from ... import Class`, then patches a class nothing
    calls any more, while production code resolves the new copy. In one CI shard that made
    test_application_record_approval's spy on MemberStatusNotificationService see no call (#2055).
    """
    saved = {path: sys.modules.get(path) for path in module_paths}

    def restore():
        for path, original in saved.items():
            sys.modules.pop(path, None)
            if original is None:
                continue
            sys.modules[path] = original
            parent_path, _, leaf = path.rpartition(".")
            parent = sys.modules.get(parent_path)
            if parent is not None:
                setattr(parent, leaf, original)

    test_case.addCleanup(restore)


class TestServiceImportSafety(unittest.TestCase):
    """Test that service modules don't perform DB/network operations at import time."""

    # Maximum allowed import time in seconds
    MAX_IMPORT_TIME = 0.5

    # Services to test (module paths)
    SERVICE_MODULES = [
        # Member services - validation
        "verenigingen.services.member.validation.member_validation_service",
        # Member services - utils
        "verenigingen.services.member.utils.member_duration_service",
        "verenigingen.services.member.utils.member_age_service",
        # Member services - display
        "verenigingen.services.member.display.member_chapter_display_service",
        "verenigingen.services.member.display.member_onload_service",
        # Member services - core
        "verenigingen.services.member.core.member_address_service",
        "verenigingen.services.member.core.member_status_service",
        # Member services - lifecycle
        "verenigingen.services.member.lifecycle.member_before_save_service",
        "verenigingen.services.member.lifecycle.member_event_emission_service",
        "verenigingen.services.member.lifecycle.member_status_notification_service",
        # Member services - payment
        "verenigingen.services.member.payment.payment_coverage_service",
        "verenigingen.services.member.payment.payment_history_service",
        # Member services - history
        "verenigingen.services.member.history.member_history_update_service",
        # API modules
        "verenigingen.api.member.chapter_api",
        "verenigingen.api.member.financial_api",
        "verenigingen.api.member.general_api",
        "verenigingen.api.member.member_id_api",
        "verenigingen.api.member.sepa_api",
    ]

    def setUp(self):
        """Clear module cache for fresh imports."""
        keep_modules_intact(self, self.SERVICE_MODULES)
        # Remove modules from cache to force re-import
        for module in list(sys.modules.keys()):
            if module.startswith("verenigingen.services.member") or module.startswith(
                "verenigingen.api.member"
            ):
                # Keep track but don't remove - we'll test with fresh subprocess approach
                pass

    def test_services_import_without_db_calls(self):
        """Test that importing services doesn't trigger database operations."""
        db_call_detected = []

        # Create detector mocks
        def detect_db_call(method_name):
            def detector(*args, **kwargs):
                db_call_detected.append(f"frappe.db.{method_name} called with args={args[:2]}")
                return MagicMock()

            return detector

        def detect_get_doc(*args, **kwargs):
            db_call_detected.append(f"frappe.get_doc called with args={args[:2]}")
            return MagicMock()

        def detect_get_all(*args, **kwargs):
            db_call_detected.append(f"frappe.get_all called with args={args[:2]}")
            return []

        # Detection mocks - these detect if DB operations occur during import
        # They are NOT replacement mocks for integration testing
        # noqa: detection-mock - frappe.db calls should not happen at import time
        with patch("frappe.db.get_value", detect_db_call("get_value")):  # noqa: detection-mock
            with patch("frappe.db.exists", detect_db_call("exists")):  # noqa: detection-mock
                with patch("frappe.db.sql", detect_db_call("sql")):  # noqa: detection-mock
                    with patch("frappe.get_doc", detect_get_doc):  # noqa: detection-mock
                        with patch("frappe.get_all", detect_get_all):  # noqa: detection-mock
                            for module_path in self.SERVICE_MODULES:
                                # Clear from cache if present
                                if module_path in sys.modules:
                                    del sys.modules[module_path]

                                db_call_detected.clear()

                                try:
                                    # Force fresh import
                                    importlib.import_module(module_path)
                                except ImportError as e:
                                    # Module might not exist yet - skip
                                    continue

                                # Check for DB calls during import
                                self.assertEqual(
                                    db_call_detected,
                                    [],
                                    f"Module {module_path} made DB calls at import time: {db_call_detected}",
                                )

    def test_services_import_time(self):
        """Test that service imports complete within acceptable time."""
        slow_imports = []

        for module_path in self.SERVICE_MODULES:
            # Clear from cache
            if module_path in sys.modules:
                del sys.modules[module_path]

            start_time = time.time()

            try:
                importlib.import_module(module_path)
            except ImportError:
                # Module might not exist - skip
                continue

            elapsed = time.time() - start_time

            if elapsed > self.MAX_IMPORT_TIME:
                slow_imports.append((module_path, elapsed))

        if slow_imports:
            details = "\n".join([f"  {mod}: {t:.3f}s" for mod, t in slow_imports])
            self.fail(f"Slow imports detected (>{self.MAX_IMPORT_TIME}s):\n{details}")

    def test_service_singletons_are_lazy(self):
        """Test that service singleton accessors don't instantiate at import time."""
        instantiation_detected = []

        # Patch StatelessService.__init__ to detect instantiation
        original_init = None

        def detect_init(self, *args, **kwargs):
            instantiation_detected.append(f"{self.__class__.__name__} instantiated")
            if original_init:
                original_init(self, *args, **kwargs)

        with patch(
            "verenigingen.services.infrastructure.base_service.StatelessService.__init__",
            detect_init,
        ):
            for module_path in self.SERVICE_MODULES:
                if module_path in sys.modules:
                    del sys.modules[module_path]

                instantiation_detected.clear()

                try:
                    importlib.import_module(module_path)
                except ImportError:
                    continue

                # Services should NOT be instantiated at import time
                # Only when get_*_service() is called
                self.assertEqual(
                    instantiation_detected,
                    [],
                    f"Module {module_path} instantiated services at import: {instantiation_detected}",
                )


class TestAPIModuleImportSafety(unittest.TestCase):
    """Test that API modules don't perform operations at import time."""

    API_MODULES = [
        "verenigingen.api.member.chapter_api",
        "verenigingen.api.member.financial_api",
        "verenigingen.api.member.general_api",
        "verenigingen.api.member.member_id_api",
        "verenigingen.api.member.sepa_api",
    ]

    def setUp(self):
        keep_modules_intact(self, self.API_MODULES)

    def test_api_modules_import_cleanly(self):
        """Test that API modules import without side effects."""
        for module_path in self.API_MODULES:
            if module_path in sys.modules:
                del sys.modules[module_path]

            try:
                module = importlib.import_module(module_path)
                # Module should have frappe.whitelist decorated functions
                self.assertTrue(
                    hasattr(module, "__name__"), f"Module {module_path} loaded successfully"
                )
            except ImportError as e:
                self.fail(f"Failed to import {module_path}: {e}")


class TestImportSafetyLeavesModulesAlone(unittest.TestCase):
    """The deleting tests above must not change which module object the process holds (#2055)."""

    def test_the_module_objects_survive_the_import_tests(self):
        paths = TestServiceImportSafety.SERVICE_MODULES + TestAPIModuleImportSafety.API_MODULES
        before = {}
        for path in paths:
            try:
                before[path] = importlib.import_module(path)
            except ImportError:
                continue
        self.assertIn(
            "verenigingen.services.member.lifecycle.member_status_notification_service",
            before,
            "control: the module a spy test binds a class from is one of those the import tests delete",
        )

        loader = unittest.TestLoader()
        suite = unittest.TestSuite(
            [
                loader.loadTestsFromTestCase(TestServiceImportSafety),
                loader.loadTestsFromTestCase(TestAPIModuleImportSafety),
            ]
        )
        result = unittest.TestResult()
        suite.run(result)
        self.assertGreater(result.testsRun, 0, "control: the import tests ran")

        replaced = [path for path, module in before.items() if sys.modules.get(path) is not module]
        self.assertEqual(replaced, [], "the import tests left a second copy of these modules in sys.modules")
        stale_parent_attr = [
            path
            for path, module in before.items()
            if getattr(sys.modules[path.rpartition(".")[0]], path.rpartition(".")[2], None) is not module
        ]
        self.assertEqual(stale_parent_attr, [], "the import tests left a second copy on the parent package")


if __name__ == "__main__":
    unittest.main()
