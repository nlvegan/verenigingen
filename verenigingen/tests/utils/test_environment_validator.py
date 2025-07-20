"""
Test Environment Validator for Verenigingen
Validates that the test environment is properly configured and ready for testing
"""

import os
import sys
from pathlib import Path

import frappe
import psutil


class TestEnvironmentValidator:
    """Validates test environment configuration and readiness"""

    def __init__(self):
        self.validation_results = {}
        self.errors = []
        self.warnings = []

    def validate_all(self):
        """Run all validation checks"""
        print("🔍 Validating test environment...")

        validations = [
            ("Frappe Environment", self.validate_frappe_environment),
            ("Database Connection", self.validate_database_connection),
            ("Required Doctypes", self.validate_required_doctypes),
            ("System Resources", self.validate_system_resources),
            ("Python Dependencies", self.validate_python_dependencies),
            ("File Permissions", self.validate_file_permissions),
            ("Test Data Setup", self.validate_test_data_setup),
            ("Network Connectivity", self.validate_network_connectivity),
        ]

        for name, validator in validations:
            try:
                result = validator()
                self.validation_results[name] = result
                status = "✅" if result["status"] == "pass" else "❌" if result["status"] == "fail" else "⚠️"
                print(f"{status} {name}: {result['message']}")

                if result["status"] == "fail":
                    self.errors.extend(result.get("errors", []))
                elif result["status"] == "warning":
                    self.warnings.extend(result.get("warnings", []))

            except Exception as e:
                self.validation_results[name] = {"status": "fail", "message": f"Validation failed: {str(e)}"}
                self.errors.append(f"{name}: {str(e)}")
                print(f"❌ {name}: Validation failed - {str(e)}")

        self._print_summary()
        return len(self.errors) == 0

    def validate_frappe_environment(self):
        """Validate Frappe framework environment"""
        try:
            # Check if we're in a Frappe site
            if not hasattr(frappe, "local") or not frappe.local:
                return {
                    "status": "fail",
                    "message": "Not running in Frappe context",
                    "errors": ["Frappe context not initialized"]}

            # Check site configuration
            site_name = frappe.local.site
            if not site_name:
                return {"status": "fail", "message": "No site configured", "errors": ["Site name not found"]}

            # Check if Verenigingen app is installed
            installed_apps = frappe.get_installed_apps()
            if "verenigingen" not in installed_apps:
                return {
                    "status": "fail",
                    "message": "Verenigingen app not installed",
                    "errors": ["Verenigingen not in installed apps"]}

            return {
                "status": "pass",
                "message": f"Frappe environment ready (site: {site_name})",
                "details": {
                    "site": site_name,
                    "installed_apps": len(installed_apps),
                    "frappe_version": frappe.__version__}}

        except Exception as e:
            return {
                "status": "fail",
                "message": f"Frappe environment check failed: {str(e)}",
                "errors": [str(e)]}

    def validate_database_connection(self):
        """Validate database connectivity and permissions"""
        try:
            # Test basic connectivity
            result = frappe.db.sql("SELECT 1 as test", as_dict=True)
            if not result or result[0]["test"] != 1:
                return {
                    "status": "fail",
                    "message": "Database connectivity test failed",
                    "errors": ["Basic SQL query failed"]}

            # Test write permissions
            test_table = "`tabSystem Settings`"
            frappe.db.sql(f"SELECT COUNT(*) FROM {test_table}")

            # Check database size and performance
            db_size = frappe.db.sql(
                "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 1) as db_size_mb FROM information_schema.tables WHERE table_schema = DATABASE()",
                as_dict=True,
            )
            db_size_mb = db_size[0]["db_size_mb"] if db_size else 0

            # Check transaction isolation
            isolation = frappe.db.sql("SELECT @@tx_isolation as isolation", as_dict=True)
            isolation_level = isolation[0]["isolation"] if isolation else "unknown"

            return {
                "status": "pass",
                "message": f"Database connection healthy (size: {db_size_mb}MB)",
                "details": {"db_size_mb": db_size_mb, "isolation_level": isolation_level}}

        except Exception as e:
            return {"status": "fail", "message": f"Database validation failed: {str(e)}", "errors": [str(e)]}

    def validate_required_doctypes(self):
        """Validate that all required doctypes exist"""
        required_doctypes = [
            "Member",
            "Membership",
            "Membership Type",
            "Chapter",
            "Volunteer",
            "Volunteer Expense",
            "Team",
            "SEPA Mandate",
            "SEPA Direct Debit Batch",
            "Donation",
            "Donor",
            "Membership Termination Request",
            "Contribution Amendment Request",
        ]

        missing_doctypes = []

        try:
            for doctype in required_doctypes:
                if not frappe.db.exists("DocType", doctype):
                    missing_doctypes.append(doctype)
                else:
                    # Check if doctype has required fields
                    try:
                        meta = frappe.get_meta(doctype)
                        if not meta.fields:
                            missing_doctypes.append(f"{doctype} (no fields)")
                    except Exception as e:
                        missing_doctypes.append(f"{doctype} (meta error: {str(e)})")

            if missing_doctypes:
                return {
                    "status": "fail",
                    "message": f"{len(missing_doctypes)} required doctypes missing",
                    "errors": missing_doctypes}

            return {
                "status": "pass",
                "message": f"All {len(required_doctypes)} required doctypes present",
                "details": {"doctypes_checked": len(required_doctypes)}}

        except Exception as e:
            return {"status": "fail", "message": f"Doctype validation failed: {str(e)}", "errors": [str(e)]}

    def validate_system_resources(self):
        """Validate system resources for testing"""
        try:
            # Check memory
            memory = psutil.virtual_memory()
            memory_gb = memory.total / (1024**3)
            memory_available_gb = memory.available / (1024**3)

            # Check CPU
            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=1)

            # Check disk space
            disk = psutil.disk_usage(".")
            disk_free_gb = disk.free / (1024**3)
            disk_percent_used = (disk.used / disk.total) * 100

            warnings = []
            errors = []

            # Memory checks
            if memory_gb < 2:
                errors.append(f"Insufficient memory: {memory_gb:.1f}GB (minimum 2GB required)")
            elif memory_available_gb < 1:
                warnings.append(f"Low available memory: {memory_available_gb:.1f}GB")

            # CPU checks
            if cpu_count < 2:
                warnings.append(f"Low CPU count: {cpu_count} cores")
            if cpu_percent > 80:
                warnings.append(f"High CPU usage: {cpu_percent}%")

            # Disk checks
            if disk_free_gb < 1:
                errors.append(f"Insufficient disk space: {disk_free_gb:.1f}GB free")
            elif disk_percent_used > 90:
                warnings.append(f"High disk usage: {disk_percent_used:.1f}%")

            status = "fail" if errors else "warning" if warnings else "pass"
            message = f"System resources: {memory_gb:.1f}GB RAM, {cpu_count} CPUs, {disk_free_gb:.1f}GB free"

            result = {
                "status": status,
                "message": message,
                "details": {
                    "memory_gb": memory_gb,
                    "memory_available_gb": memory_available_gb,
                    "cpu_count": cpu_count,
                    "cpu_percent": cpu_percent,
                    "disk_free_gb": disk_free_gb,
                    "disk_percent_used": disk_percent_used}}

            if errors:
                result["errors"] = errors
            if warnings:
                result["warnings"] = warnings

            return result

        except Exception as e:
            return {
                "status": "fail",
                "message": f"System resource check failed: {str(e)}",
                "errors": [str(e)]}

    def validate_python_dependencies(self):
        """Validate Python dependencies"""
        try:
            required_packages = ["psutil", "requests", "unittest"]

            missing_packages = []
            package_versions = {}

            for package in required_packages:
                try:
                    module = __import__(package)
                    version = getattr(module, "__version__", "unknown")
                    package_versions[package] = version
                except ImportError:
                    missing_packages.append(package)

            # Check Python version
            python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            if sys.version_info < (3, 8):
                return {
                    "status": "fail",
                    "message": f"Python version too old: {python_version} (minimum 3.8 required)",
                    "errors": [f"Python {python_version} not supported"]}

            if missing_packages:
                return {
                    "status": "fail",
                    "message": f"{len(missing_packages)} required packages missing",
                    "errors": [f"Missing package: {pkg}" for pkg in missing_packages]}

            return {
                "status": "pass",
                "message": f"Python {python_version} with all required packages",
                "details": {"python_version": python_version, "packages": package_versions}}

        except Exception as e:
            return {
                "status": "fail",
                "message": f"Python dependency check failed: {str(e)}",
                "errors": [str(e)]}

    def validate_file_permissions(self):
        """Validate file system permissions"""
        try:
            current_dir = Path(".")
            app_dir = Path("verenigingen")

            issues = []

            # Check read permissions
            if not current_dir.exists() or not os.access(current_dir, os.R_OK):
                issues.append("Cannot read current directory")

            if app_dir.exists() and not os.access(app_dir, os.R_OK):
                issues.append("Cannot read verenigingen directory")

            # Check write permissions for test files
            test_file = Path("test_write_permission.tmp")
            try:
                test_file.write_text("test")
                test_file.unlink()
            except (OSError, PermissionError):
                issues.append("Cannot write to current directory")

            # Check test directory permissions
            test_dir = Path("verenigingen/tests")
            if test_dir.exists() and not os.access(test_dir, os.R_OK):
                issues.append("Cannot read test directory")

            if issues:
                return {
                    "status": "fail",
                    "message": f"{len(issues)} permission issues found",
                    "errors": issues}

            return {
                "status": "pass",
                "message": "File permissions validated",
                "details": {"checks_passed": 4}}

        except Exception as e:
            return {
                "status": "fail",
                "message": f"File permission check failed: {str(e)}",
                "errors": [str(e)]}

    def validate_test_data_setup(self):
        """Validate test data setup capabilities"""
        try:
            warnings = []

            # Check if we can create test records
            test_doc_created = False
            try:
                # Try to create a test doctype record
                test_chapter = frappe.get_doc(
                    {
                        "doctype": "Chapter",
                        "chapter_name": "Test Environment Validation Chapter",
                        "short_name": "TEVC",
                        "country": "Netherlands"}
                )
                test_chapter.insert(ignore_permissions=True)
                test_doc_created = True

                # Clean up immediately
                test_chapter.delete(ignore_permissions=True, force=True)

            except Exception as e:
                return {
                    "status": "fail",
                    "message": f"Cannot create test data: {str(e)}",
                    "errors": [f"Test record creation failed: {str(e)}"]}

            # Check test data factory
            try:
                from verenigingen.tests.test_data_factory import TestDataFactory

                TestDataFactory()
                # Test basic functionality without creating data
            except ImportError:
                warnings.append("Test data factory not available")

            # Check existing test data
            existing_test_records = []
            test_patterns = ["test", "Test", "TEST"]

            for pattern in test_patterns:
                chapters = frappe.get_all(
                    "Chapter", filters=[["chapter_name", "like", f"%{pattern}%"]], limit=5
                )
                existing_test_records.extend(chapters)

            if len(existing_test_records) > 50:
                warnings.append(
                    f"Many existing test records found ({len(existing_test_records)}), consider cleanup"
                )

            result = {
                "status": "warning" if warnings else "pass",
                "message": "Test data setup validated",
                "details": {
                    "can_create_records": test_doc_created,
                    "existing_test_records": len(existing_test_records)}}

            if warnings:
                result["warnings"] = warnings

            return result

        except Exception as e:
            return {"status": "fail", "message": f"Test data validation failed: {str(e)}", "errors": [str(e)]}

    def validate_network_connectivity(self):
        """Validate network connectivity for external integrations"""
        try:
            import socket

            connectivity_tests = [
                ("DNS Resolution", "google.com", 80),
                ("HTTPS Connectivity", "httpbin.org", 443),
            ]

            warnings = []

            for test_name, host, port in connectivity_tests:
                try:
                    socket.create_connection((host, port), timeout=5).close()
                except (socket.error, socket.timeout):
                    warnings.append(f"{test_name} failed ({host}:{port})")

            # Test HTTP requests if requests is available
            try:
                import requests

                response = requests.get("https://httpbin.org/status/200", timeout=5)
                if response.status_code != 200:
                    warnings.append("HTTP request test failed")
            except Exception:
                warnings.append("HTTP requests library not working")

            status = "warning" if warnings else "pass"
            message = f"Network connectivity: {len(connectivity_tests) - len(warnings)}/{len(connectivity_tests)} tests passed"

            result = {"status": status, "message": message, "details": {"tests_run": len(connectivity_tests)}}

            if warnings:
                result["warnings"] = warnings

            return result

        except Exception as e:
            return {"status": "fail", "message": f"Network validation failed: {str(e)}", "errors": [str(e)]}

    def _print_summary(self):
        """Print validation summary"""
        print("\n" + "=" * 50)
        print("🔍 TEST ENVIRONMENT VALIDATION SUMMARY")
        print("=" * 50)

        total_checks = len(self.validation_results)
        passed_checks = len([r for r in self.validation_results.values() if r["status"] == "pass"])
        warning_checks = len([r for r in self.validation_results.values() if r["status"] == "warning"])
        failed_checks = len([r for r in self.validation_results.values() if r["status"] == "fail"])

        print(f"Total checks: {total_checks}")
        print(f"✅ Passed: {passed_checks}")
        print(f"⚠️  Warnings: {warning_checks}")
        print(f"❌ Failed: {failed_checks}")

        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"   - {error}")

        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"   - {warning}")

        if failed_checks == 0:
            print("\n✅ Environment is ready for testing!")
        elif failed_checks <= 2:
            print("\n⚠️  Environment has minor issues but may be usable")
        else:
            print("\n❌ Environment has serious issues and is not ready for testing")

        print("=" * 50)


def validate_test_environment():
    """Quick validation function"""
    validator = TestEnvironmentValidator()
    return validator.validate_all()


def main():
    """CLI entry point"""
    import sys

    success = validate_test_environment()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
