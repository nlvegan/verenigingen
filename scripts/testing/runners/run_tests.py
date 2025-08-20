#!/usr/bin/env python3
"""
Standalone Test Runner for Mollie Backend Integration
Can run without full Frappe environment
"""

import importlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


# Color codes for terminal output
class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def print_header(text):
    """Print colored header"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")


def print_success(text):
    """Print success message"""
    print(f"{Colors.OKGREEN}✅ {text}{Colors.ENDC}")


def print_error(text):
    """Print error message"""
    print(f"{Colors.FAIL}❌ {text}{Colors.ENDC}")


def print_warning(text):
    """Print warning message"""
    print(f"{Colors.WARNING}⚠️  {text}{Colors.ENDC}")


def print_info(text):
    """Print info message"""
    print(f"{Colors.OKCYAN}ℹ️  {text}{Colors.ENDC}")


class TestValidator:
    """Validates the Mollie Backend Integration implementation"""

    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "components": {},
        }

    def validate_project_structure(self):
        """Validate project structure and files exist"""
        print_header("VALIDATING PROJECT STRUCTURE")

        required_dirs = [
            "vereiningen/vereiningen_payments/clients",
            "vereiningen/vereiningen_payments/core/security",
            "verenigingen/vereiningen_payments/core/resilience",
            "verenigingen/verenigingen_payments/core/compliance",
            "verenigingen/verenigingen_payments/workflows",
            "verenigingen/vereiningen_payments/monitoring",
            "verenigingen/verenigingen_payments/integration",
            "verenigingen/tests",
            "docs",
            "monitoring",
            "config",
        ]

        required_files = [
            "pyproject.toml",
            "verenigingen/verenigingen_payments/integration/mollie_connector.py",
            "verenigingen/tests/test_harness.py",
            "docs/API_DOCUMENTATION.md",
            "docs/DEPLOYMENT_GUIDE.md",
            "docs/OPERATIONS_RUNBOOK.md",
        ]

        all_valid = True

        # Check directories
        for dir_path in required_dirs:
            full_path = project_root / dir_path
            if full_path.exists():
                print_success(f"Directory exists: {dir_path}")
            else:
                print_error(f"Missing directory: {dir_path}")
                all_valid = False

        # Check files
        for file_path in required_files:
            full_path = project_root / file_path
            if full_path.exists():
                print_success(f"File exists: {file_path}")
            else:
                print_error(f"Missing file: {file_path}")
                all_valid = False

        self.results["components"]["structure"] = all_valid
        return all_valid

    def validate_dependencies(self):
        """Check if required dependencies can be imported"""
        print_header("VALIDATING DEPENDENCIES")

        dependencies = {
            "requests": "Network requests",
            "cryptography": "Encryption support",
            "json": "JSON handling",
            "datetime": "Date/time operations",
            "decimal": "Financial calculations",
            "hashlib": "Hashing operations",
            "hmac": "HMAC validation",
            "base64": "Encoding/decoding",
        }

        optional_deps = {
            "mollie": "Mollie SDK (optional - will use mocks if not available)",
            "frappe": "Frappe framework (optional - will use mocks if not available)",
            "pytest": "Testing framework (optional)",
            "prometheus_client": "Monitoring (optional)",
        }

        all_valid = True

        # Check required dependencies
        for module, description in dependencies.items():
            try:
                importlib.import_module(module)
                print_success(f"{module}: {description}")
            except ImportError:
                print_error(f"Missing required: {module} ({description})")
                all_valid = False

        # Check optional dependencies
        print_info("Optional dependencies:")
        for module, description in optional_deps.items():
            try:
                importlib.import_module(module)
                print_success(f"{module}: {description}")
            except ImportError:
                print_warning(f"Not installed: {module} ({description})")

        self.results["components"]["dependencies"] = all_valid
        return all_valid

    def validate_code_imports(self):
        """Validate that core modules can be imported"""
        print_header("VALIDATING CODE IMPORTS")

        test_imports = [
            ("vereiningen.verenigingen_payments.core.security.encryption_handler", "EncryptionHandler"),
            ("verenigingen.verenigingen_payments.core.security.webhook_validator", "WebhookValidator"),
            ("verenigingen.verenigingen_payments.core.resilience.circuit_breaker", "CircuitBreaker"),
            ("verenigingen.verenigingen_payments.core.resilience.rate_limiter", "RateLimiter"),
            ("verenigingen.verenigingen_payments.core.resilience.retry_policy", "RetryPolicy"),
            ("verenigingen.verenigingen_payments.core.compliance.financial_validator", "FinancialValidator"),
            ("verenigingen.verenigingen_payments.core.compliance.audit_trail", "AuditTrail"),
        ]

        all_valid = True

        for module_path, class_name in test_imports:
            try:
                module = importlib.import_module(module_path)
                if hasattr(module, class_name):
                    print_success(f"Imported: {class_name} from {module_path.split('.')[-1]}")
                else:
                    print_error(f"Class not found: {class_name} in {module_path}")
                    all_valid = False
            except ImportError as e:
                print_error(f"Import failed: {module_path} ({str(e)})")
                all_valid = False

        self.results["components"]["imports"] = all_valid
        return all_valid

    def run_test_harness(self):
        """Run the test harness with mocked environment"""
        print_header("RUNNING TEST HARNESS")

        try:
            # Import and run test harness
            from verenigingen.tests.test_harness import main as run_tests

            print_info("Executing test harness with mocked environment...")

            # Capture test output
            import contextlib
            from io import StringIO

            output = StringIO()
            with contextlib.redirect_stdout(output):
                try:
                    run_tests()
                    test_passed = True
                except SystemExit as e:
                    test_passed = e.code == 0

            # Parse output
            output_text = output.getvalue()
            if "All connector tests passed" in output_text:
                print_success("Mollie Connector tests passed")
            if "All resilience tests passed" in output_text:
                print_success("Resilience Pattern tests passed")
            if "All security tests passed" in output_text:
                print_success("Security Component tests passed")
            if "All workflow tests passed" in output_text:
                print_success("Business Workflow tests passed")

            self.results["components"]["test_harness"] = test_passed
            return test_passed

        except Exception as e:
            print_error(f"Test harness failed: {str(e)}")
            self.results["components"]["test_harness"] = False
            return False

    def validate_api_patterns(self):
        """Validate API patterns and error handling"""
        print_header("VALIDATING API PATTERNS")

        try:
            # Test circuit breaker pattern
            from verenigingen.verenigingen_payments.core.resilience.circuit_breaker import (
                CircuitBreaker,
                CircuitState,
            )

            breaker = CircuitBreaker(failure_threshold=3, timeout=1)
            assert breaker.state == CircuitState.CLOSED
            print_success("Circuit Breaker pattern validated")

            # Test rate limiter
            from verenigingen.verenigingen_payments.core.resilience.rate_limiter import RateLimiter

            limiter = RateLimiter(requests_per_second=10)
            allowed, wait = limiter.check_rate_limit("test")
            assert isinstance(allowed, bool)
            print_success("Rate Limiter pattern validated")

            # Test retry policy
            from verenigingen.verenigingen_payments.core.resilience.retry_policy import RetryPolicy

            policy = RetryPolicy(max_attempts=3)
            assert policy.max_attempts == 3
            print_success("Retry Policy pattern validated")

            self.results["components"]["patterns"] = True
            return True

        except Exception as e:
            print_error(f"Pattern validation failed: {str(e)}")
            self.results["components"]["patterns"] = False
            return False

    def generate_report(self):
        """Generate final validation report"""
        print_header("VALIDATION REPORT")

        # Count results
        total_components = len(self.results["components"])
        passed_components = sum(1 for v in self.results["components"].values() if v)

        # Print summary
        print(f"\n{Colors.BOLD}Components Validated: {total_components}{Colors.ENDC}")
        print(f"{Colors.BOLD}Components Passed: {passed_components}{Colors.ENDC}")
        print(f"{Colors.BOLD}Components Failed: {total_components - passed_components}{Colors.ENDC}")

        # Component status
        print(f"\n{Colors.BOLD}Component Status:{Colors.ENDC}")
        for component, status in self.results["components"].items():
            if status:
                print_success(f"{component.replace('_', ' ').title()}: PASSED")
            else:
                print_error(f"{component.replace('_', ' ').title()}: FAILED")

        # Overall status
        all_passed = all(self.results["components"].values())

        print(f"\n{Colors.BOLD}{'='*60}{Colors.ENDC}")
        if all_passed:
            print_success("🎉 ALL VALIDATIONS PASSED - Implementation is functional!")
            print_info("The integration layer is now complete and testable.")
        else:
            print_warning("⚠️ SOME VALIDATIONS FAILED - Additional work needed")
            print_info("Review the failed components and address the issues.")
        print(f"{Colors.BOLD}{'='*60}{Colors.ENDC}")

        # Save report to file
        report_file = project_root / "validation_report.json"
        with open(report_file, "w") as f:
            json.dump(self.results, f, indent=2)
        print_info(f"Detailed report saved to: {report_file}")

        return all_passed


def main():
    """Main validation entry point"""
    print_header("MOLLIE BACKEND INTEGRATION VALIDATOR")
    print(f"Project Root: {project_root}")
    print(f"Python Version: {sys.version}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    validator = TestValidator()

    # Run validations
    validator.validate_project_structure()
    validator.validate_dependencies()
    validator.validate_code_imports()
    validator.validate_api_patterns()

    # Try to run test harness (may fail if dependencies missing)
    try:
        validator.run_test_harness()
    except Exception as e:
        print_warning(f"Test harness skipped: {str(e)}")

    # Generate report
    success = validator.generate_report()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
