# Developer Guide - Enhanced Testing Infrastructure

This guide documents how to use the **Phase 1 Enhanced Testing Infrastructure** for the Verenigingen application, including coverage reporting, performance analysis, and advanced testing features.

## Table of Contents

1. [Overview](#overview)
2. [Enhanced Test Runner](#enhanced-test-runner)
3. [Coverage Dashboard](#coverage-dashboard)
4. [Performance Analysis](#performance-analysis)
5. [Edge Case Testing](#edge-case-testing)
6. [Advanced Features](#advanced-features)
7. [Command Line Interface](#command-line-interface)
8. [Integration Workflows](#integration-workflows)

## Overview

The enhanced testing infrastructure builds upon the existing **VereningingenTestCase** base class and provides:

- **📊 Coverage Dashboard** - Visual HTML dashboard showing test coverage, performance metrics, and trends
- **⚡ Performance Analysis** - Detailed performance tracking with query monitoring and optimization insights
- **🎯 Edge Case Coverage** - Comprehensive edge case tracking and validation
- **🚀 Enhanced Test Runner** - Command-line interface with multiple reporting options
- **📈 Trend Analysis** - Historical tracking of test metrics and quality improvements

## Enhanced Test Runner

### Basic Usage

The enhanced test runner extends the existing `TestRunner` class with new capabilities:

```python
from verenigingen.tests.utils.test_runner import TestRunner

# Create runner with enhanced features
runner = TestRunner(enable_coverage=True, enable_performance=True)

# Run tests with automatic reporting
result = runner.run_test_suite(tests, "My Test Suite")

# Generate reports
coverage_report = runner.generate_coverage_report()
performance_report = runner.generate_performance_report()
edge_case_summary = runner.generate_edge_case_summary()
```

### Available Test Suites

| Suite | Description | Usage |
|-------|-------------|-------|
| `quick` | Fast validation tests for pre-commit hooks | `run_quick_tests()` |
| `comprehensive` | Full test suite for CI/CD | `run_comprehensive_tests()` |
| `performance` | Performance-focused analysis | `run_performance_test_analysis()` |
| `edge_cases` | Edge case validation | `run_edge_case_validation()` |
| `all` | Complete test run with all reports | `run_tests_with_coverage_dashboard()` |

### Enhanced Output

Tests now show performance metrics in real-time:

```
📋 test_member_creation.test_create_member_happy_path
----------------------------------------
✅ PASSED: Member created successfully [0.15s, 8 queries]

📋 test_sepa_mandate_validation.test_iban_validation
----------------------------------------
✅ PASSED: IBAN validation successful [0.08s, 3 queries]
```

## Coverage Dashboard

### Generating Coverage Reports

#### Via API
```python
# Generate coverage dashboard programmatically
import frappe

result = frappe.get_attr("verenigingen.tests.utils.coverage_reporter.generate_coverage_dashboard")()

print(f"Dashboard available at: {result['dashboard_path']}")
print(f"JSON report at: {result['json_path']}")
```

#### Via Command Line
```bash
# Run tests with coverage dashboard
python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --coverage --html-report
```

### Dashboard Features

The HTML dashboard includes:

- **📈 Coverage Metrics** - Line coverage, branch coverage, and function coverage
- **⚡ Performance Trends** - Test execution time and query efficiency over time
- **🎯 Edge Case Tracking** - Coverage of validation, security, performance, and integration edge cases
- **📊 Visual Charts** - Interactive charts showing test health and trends
- **🔍 Detailed Reports** - Drill-down into specific test results and failures

### Coverage Data Structure

```json
{
  "timestamp": "2024-01-15T10:30:00",
  "summary": {
    "total_tests": 150,
    "passed_tests": 147,
    "failed_tests": 2,
    "error_tests": 1,
    "pass_percentage": 98.0,
    "total_duration": 45.2,
    "total_queries": 1250
  },
  "coverage": {
    "totals": {
      "percent_covered": 87.5,
      "lines_covered": 2100,
      "lines_missing": 300
    },
    "files": {
      "verenigingen/utils/member_utils.py": {
        "percent_covered": 92.0,
        "lines_covered": 184,
        "lines_missing": 16
      }
    }
  },
  "performance": {
    "average_duration": 0.301,
    "max_duration": 2.15,
    "average_queries": 8.3,
    "slow_tests": [
      ["test_bulk_member_processing", 2.15],
      ["test_complex_sepa_validation", 1.87]
    ]
  }
}
```

## Performance Analysis

### Performance Tracking

The enhanced infrastructure automatically tracks:

- **⏱️ Execution Time** - Per test and overall duration
- **🗄️ Database Queries** - Query count and efficiency
- **💾 Memory Usage** - Memory consumption patterns
- **📈 Trends** - Performance improvements/regressions over time

### Using Performance Monitoring

```python
from verenigingen.tests.utils.base import VereningingenTestCase

class TestMyFeature(VereningingenTestCase):
    def test_performance_sensitive_operation(self):
        """Test with performance monitoring"""
        
        # Monitor query count
        with self.assertQueryCount(50):  # Max 50 queries
            result = bulk_process_members()
        
        # Monitor execution time
        with self.assertMaxExecutionTime(2.0):  # Max 2 seconds
            result = complex_calculation()
        
        # Access performance metrics
        duration = self.get_last_test_duration()
        query_count = self.get_last_query_count()
        
        self.assertLess(duration, 1.0)
        self.assertLess(query_count, 25)
```

### Performance Targets

| Test Type | Duration Target | Query Target | Notes |
|-----------|-----------------|--------------|-------|
| Unit Tests | < 0.1s | < 10 queries | Fast, isolated tests |
| Integration Tests | < 1.0s | < 50 queries | Component interactions |
| Workflow Tests | < 5.0s | < 100 queries | End-to-end scenarios |
| Performance Tests | Varies | Optimized | Benchmarking specific operations |

### Performance Reports

Generate detailed performance analysis:

```bash
# Generate performance report
python scripts/testing/runners/enhanced_test_runner.py --suite performance

# Results saved to:
# /home/frappe/frappe-bench/sites/dev.veganisme.net/test-results/performance_report.json
```

Performance report structure:
```json
{
  "timestamp": "2024-01-15T10:30:00",
  "total_tests": 45,
  "average_duration": 0.285,
  "max_duration": 1.95,
  "average_queries": 12.4,
  "max_queries": 75,
  "slow_tests": [
    ["test_bulk_sepa_processing", 1.95],
    ["test_member_lifecycle_complete", 1.23]
  ],
  "query_heavy_tests": [
    ["test_complex_reporting", 75],
    ["test_data_migration", 68]
  ],
  "efficiency_score": 85.2
}
```

## Edge Case Testing

### Using Edge Case Methods

The **VereningingenTestCase** provides specialized methods for edge case testing:

```python
def test_billing_frequency_conflicts(self):
    """Test detection of billing frequency conflicts"""
    
    # 1. Create member and clear auto-schedules
    member = self.create_test_member()
    self.clear_member_auto_schedules(member.name)
    
    # 2. Create controlled test scenarios
    monthly_schedule = self.create_controlled_dues_schedule(
        member.name, "Monthly", 25.0,
        start_date="2024-01-01"
    )
    
    annual_schedule = self.create_controlled_dues_schedule(
        member.name, "Annual", 250.0,
        start_date="2024-01-15"  # Creates overlap
    )
    
    # 3. Test conflict detection
    conflicts = self._detect_billing_conflicts(member.name)
    self.assertTrue(conflicts["has_conflicts"])
    self.assertEqual(len(conflicts["conflicts"]), 1)
```

### Edge Case Categories

The system tracks edge cases in these categories:

- **🔍 Validation** - Data validation, format checking, business rules
- **🔒 Security** - Permission testing, access control, input sanitization  
- **⚡ Performance** - Load testing, scalability, optimization
- **🔗 Integration** - API testing, workflow testing, cross-component
- **💼 Business Logic** - Domain-specific rules, edge conditions

### Edge Case Coverage Report

```bash
# Generate edge case coverage summary
python scripts/testing/runners/enhanced_test_runner.py --suite edge_cases
```

Report structure:
```json
{
  "timestamp": "2024-01-15T10:30:00",
  "categories": {
    "validation": {
      "total_tests": 45,
      "passed_tests": 43,
      "coverage_percentage": 95.6,
      "tests": [
        ["test_email_validation", "passed"],
        ["test_date_boundary_validation", "passed"]
      ]
    },
    "security": {
      "total_tests": 28,
      "passed_tests": 28,
      "coverage_percentage": 100.0
    }
  }
}
```

## Advanced Features

### Mock Bank System

Comprehensive mock banking for SEPA testing:

```python
from verenigingen.utils.iban_validator import generate_test_iban

# Generate test IBANs for different mock banks
test_iban = generate_test_iban("TEST")  # NL13TEST0123456789
mock_iban = generate_test_iban("MOCK")  # NL82MOCK0123456789  
demo_iban = generate_test_iban("DEMO")  # NL93DEMO0123456789

# All IBANs pass full MOD-97 validation
# BICs are auto-derived: TESTNL2A, MOCKNL2A, DEMONL2A

# Use in tests
def test_sepa_mandate_creation(self):
    member = self.create_test_member()
    test_iban = self.factory.generate_test_iban("TEST")
    
    mandate = self.create_sepa_mandate(
        member=member.name,
        iban=test_iban
    )
    
    self.assertFieldEqual(mandate, "iban", test_iban)
    self.assertTrue(mandate.validate_iban())
```

### Automatic Cleanup System

The base class automatically tracks and cleans up test data:

```python
def test_complex_workflow(self):
    # All these will be automatically cleaned up
    chapter = self.create_test_chapter()
    member = self.create_test_member(chapter=chapter.name)
    membership = self.create_test_membership(member=member.name)
    volunteer = self.create_test_volunteer(member=member.name)
    
    # Approve membership application (creates customer automatically)
    application = self.create_membership_application(member=member.name)
    approved_member = self.approve_application(application)
    
    # No manual cleanup needed!
    # System handles dependencies and relationships automatically
```

### Enhanced Assertions

Domain-specific assertions for common patterns:

```python
# Document and field assertions
self.assertFieldEqual(doc, "status", "Active")
self.assertFieldNotEmpty(doc, "creation_date")
self.assertDocumentExists("Member", member_name)
self.assertDocumentStatus(doc, "Completed")

# Relationship assertions
self.assertDocumentLinked(member, volunteer, "member")
self.assertRelationshipExists("Member", member.name, "Verenigingen Volunteer")

# Validation assertions
self.assertValidationError("Email already exists"):
    self.create_test_member(email="duplicate@example.com")

# Performance assertions
with self.assertQueryCount(10):
    with self.assertMaxExecutionTime(1.0):
        result = complex_operation()
```

## Command Line Interface

### Enhanced Test Runner Script

The `enhanced_test_runner.py` provides a comprehensive CLI:

```bash
# Basic usage
python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive

# With coverage and HTML dashboard
python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --coverage --html-report

# Performance analysis
python scripts/testing/runners/enhanced_test_runner.py --suite performance

# All reports with automatic browser opening
python scripts/testing/runners/enhanced_test_runner.py --suite all --all-reports --html-report

# Quick tests for pre-commit
python scripts/testing/runners/enhanced_test_runner.py --suite quick --performance-report

# List available reports
python scripts/testing/runners/enhanced_test_runner.py --list-reports
```

### Command Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--suite` | Test suite to run | `--suite comprehensive` |
| `--coverage` | Generate coverage report | `--coverage` |
| `--performance-report` | Generate performance analysis | `--performance-report` |
| `--edge-case-summary` | Generate edge case coverage | `--edge-case-summary` |
| `--html-report` | Generate HTML dashboard and open in browser | `--html-report` |
| `--all-reports` | Generate all available reports | `--all-reports` |
| `--list-reports` | List all available test reports | `--list-reports` |
| `--verbose` | Verbose output | `--verbose` |

### Report File Locations

All reports are saved to: `/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results/`

| Report Type | Filename | Description |
|-------------|----------|-------------|
| Coverage Dashboard | `coverage_dashboard.html` | Interactive HTML dashboard |
| Coverage Data | `coverage_report.json` | Raw coverage data |
| Performance Analysis | `performance_report.json` | Performance metrics and trends |
| Edge Case Summary | `edge_case_summary.json` | Edge case coverage tracking |
| Quick Tests | `quick_tests.json` | Quick test results |
| Comprehensive Tests | `comprehensive_tests.json` | Full test suite results |
| Complete Run | `full_test_run.json` | All tests with all reports |

## Integration Workflows

### Pre-Commit Hook Integration

```bash
# Add to .git/hooks/pre-commit
#!/bin/bash
cd /path/to/verenigingen
python scripts/testing/runners/enhanced_test_runner.py --suite quick
if [ $? -ne 0 ]; then
    echo "Pre-commit tests failed!"
    exit 1
fi
```

### CI/CD Integration

```yaml
# GitHub Actions example
- name: Run Comprehensive Tests
  run: |
    cd apps/verenigingen
    python scripts/testing/runners/enhanced_test_runner.py \
      --suite comprehensive --all-reports
    
- name: Upload Test Reports
  uses: actions/upload-artifact@v2
  with:
    name: test-reports
    path: sites/dev.veganisme.net/test-results/
```

### Development Workflow

1. **During Development**:
   ```bash
   # Quick feedback loop
   python scripts/testing/runners/enhanced_test_runner.py --suite quick
   ```

2. **Before Committing**:
   ```bash
   # Comprehensive validation
   python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --performance-report
   ```

3. **Weekly Quality Review**:
   ```bash
   # Full analysis with dashboard
   python scripts/testing/runners/enhanced_test_runner.py --suite all --all-reports --html-report
   ```

### Performance Monitoring Workflow

1. **Establish Baseline**:
   ```bash
   python scripts/testing/runners/enhanced_test_runner.py --suite performance
   # Save baseline metrics
   ```

2. **Regular Monitoring**:
   ```bash
   # Compare against baseline
   python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --performance-report
   ```

3. **Performance Regression Detection**:
   - Automatic alerts when tests exceed duration targets
   - Query count regression detection
   - Memory usage monitoring

### Coverage Improvement Workflow

1. **Identify Gaps**:
   ```bash
   python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --coverage
   # Review coverage_dashboard.html
   ```

2. **Target Low Coverage Areas**:
   - Focus on files with < 80% coverage
   - Prioritize critical business logic
   - Add edge case tests for complex functions

3. **Validate Improvements**:
   ```bash
   # Verify coverage improvements
   python scripts/testing/runners/enhanced_test_runner.py --coverage
   ```

## Best Practices

### Test Organization

- **Use descriptive test names** that explain the scenario
- **Group related tests** in focused test classes  
- **Separate unit, integration, and workflow tests** into different files
- **Use mock banks** for financial testing to avoid external dependencies

### Performance Guidelines

- **Monitor query counts** in all tests to prevent N+1 queries
- **Set performance targets** for different test categories
- **Use bulk operations** when testing multiple records
- **Profile slow tests** and optimize bottlenecks

### Coverage Targets

- **Overall coverage**: > 85%
- **Critical modules**: > 95%
- **Edge case coverage**: > 90%
- **Integration paths**: 100%

### Reporting Guidelines

- **Generate reports regularly** (at least weekly for comprehensive analysis)
- **Monitor trends** for quality regression detection
- **Share dashboards** with team for visibility
- **Act on performance regressions** promptly

---

## Quick Reference

### Essential Commands

```bash
# Quick development testing
python scripts/testing/runners/enhanced_test_runner.py --suite quick

# Pre-commit validation  
python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --performance-report

# Weekly quality review
python scripts/testing/runners/enhanced_test_runner.py --suite all --all-reports --html-report

# Performance analysis
python scripts/testing/runners/enhanced_test_runner.py --suite performance

# Coverage improvement
python scripts/testing/runners/enhanced_test_runner.py --suite comprehensive --coverage
```

### Key Files

- **Base Test Class**: `verenigingen/tests/utils/base.py`
- **Enhanced Test Runner**: `verenigingen/tests/utils/test_runner.py`  
- **Coverage Reporter**: `verenigingen/tests/utils/coverage_reporter.py`
- **CLI Interface**: `scripts/testing/runners/enhanced_test_runner.py`
- **Test Templates**: `verenigingen/tests/docs/test_templates.md`

### Report Access

- **HTML Dashboard**: `file:///home/frappe/frappe-bench/sites/dev.veganisme.net/test-results/coverage_dashboard.html`
- **JSON Reports**: `/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results/`

This enhanced testing infrastructure provides a solid foundation for maintaining high-quality code with comprehensive test coverage, performance monitoring, and continuous quality improvement.