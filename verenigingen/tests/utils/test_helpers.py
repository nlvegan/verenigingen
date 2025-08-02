"""
Test Helper Utilities
====================

Collection of utility functions for test execution, result analysis, and testing workflow
automation in the Verenigingen association management system.

This module provides programmatic access to test execution with structured result reporting,
enabling integration with custom test runners, monitoring systems, and quality assurance
workflows.

Purpose and Design
-----------------
The test helpers address the need for programmatic test execution beyond the standard
unittest framework, providing:

- **Structured Result Reporting**: Standardized test result format for analysis
- **Success Rate Calculation**: Automatic calculation of test success metrics
- **Error Aggregation**: Comprehensive error and failure collection
- **Integration Support**: Easy integration with monitoring and reporting systems

Key Features
-----------
- **Programmatic Execution**: Run tests from Python code without command-line tools
- **Metric Calculation**: Automatic success rate and failure analysis
- **Exception Handling**: Graceful handling of test execution errors
- **Standardized Output**: Consistent result format across different test types

Usage Patterns
-------------
```python
# Direct test execution with metrics
from vereinigingen.tests.utils.test_helpers import run_member_tests

results = run_member_tests()
print(f"Success rate: {results['success_rate']:.1f}%")

# Integration with monitoring systems
test_metrics = run_member_tests()
send_metrics_to_monitoring(test_metrics)

# Automated quality gates
results = run_member_tests()
if results['success_rate'] < 95.0:
    alert_quality_team(results)
```

Integration Capabilities
-----------------------
The test helpers are designed for integration with:

- **CI/CD Pipelines**: Programmatic test execution in automated builds
- **Monitoring Systems**: Structured metrics for dashboards and alerting
- **Quality Gates**: Automated decision making based on test results
- **Reporting Tools**: Data input for test result analysis and trending

Future Enhancements
------------------
The test helper framework can be extended to support:

- **Multiple Test Classes**: Execution of test suites beyond single classes
- **Parallel Execution**: Concurrent test execution for improved performance
- **Custom Filtering**: Selective test execution based on tags or categories
- **Historical Tracking**: Test result trending and historical analysis
- **Integration Testing**: Cross-module test execution and coordination
"""

import unittest

from verenigingen.verenigingen.doctype.member.test_member import TestMember


def run_member_tests():
    """
    Execute Member DocType tests and return structured results
    
    This function provides programmatic access to Member test execution with
    comprehensive result analysis and metrics calculation.
    
    Returns:
        dict: Test execution results containing:
            - tests_run (int): Total number of tests executed
            - failures (int): Number of test failures (assertion errors)
            - errors (int): Number of test errors (exceptions)
            - success_rate (float): Percentage of successful tests (0-100)
            - error (str): Error message if execution fails entirely
    
    Example:
        >>> results = run_member_tests()
        >>> if results.get('success_rate', 0) >= 95:
        ...     print("✅ Member tests passed quality gate")
        ... else:
        ...     print(f"❌ Member tests failed: {results['success_rate']:.1f}% success")
    
    Integration Notes:
        - Compatible with CI/CD pipeline result processing
        - Structured output suitable for monitoring system ingestion
        - Error handling prevents test infrastructure failures
        - Success rate calculation handles division by zero gracefully
    """
    try:
        suite = unittest.TestLoader().loadTestsFromTestCase(TestMember)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "success_rate": (result.testsRun - len(result.failures) - len(result.errors))
            / result.testsRun
            * 100
            if result.testsRun > 0
            else 0}
    except Exception as e:
        return {"error": str(e)}
