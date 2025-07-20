# Hybrid Report Testing Framework

## Overview

The Verenigingen app now includes a comprehensive hybrid report testing framework that combines the best practices from ERPNext with enhanced regression detection capabilities.

## Framework Components

### 1. **Hybrid Report Test Case** (`HybridReportTestCase`)
Enhanced test case that extends Frappe's standard testing with:
- Regression pattern detection
- Structure validation
- Export functionality testing
- Optional filter testing

### 2. **Verenigingen Report Test Case** (`VereningingenReportTestCase`)
Pre-configured test case for all Verenigingen reports with:
- Predefined regression patterns for known issues
- Standard filter test cases
- Comprehensive report coverage

### 3. **Standalone Utilities**
- `execute_script_report_hybrid()` - Standalone testing function
- `test_all_reports_hybrid()` - Whitelisted function for bench execution
- `test_single_report_hybrid()` - Test individual reports

## Key Features

### ✅ **ERPNext Compatibility**
Follows ERPNext's established patterns:
```python
REPORT_FILTER_TEST_CASES = [
    ("ANBI Donation Summary", {"donor_type": "Individual"}),
    ("Overdue Member Payments", {"days_overdue": 30}),
]
```

### 🛡️ **Regression Detection**
Specific patterns for known issues:
```python
REGRESSION_PATTERNS = {
    "ANBI Donation Summary": [
        {"pattern": "bsn_encrypted", "description": "Database field name issue"}
    ],
    "Overdue Member Payments": [
        {"pattern": "today", "description": "today() function import issue"}
    ]
}
```

### 📊 **Structure Analysis**
Automatic validation of report return structures:
- List vs Dict format detection
- Column and data validation
- Chart and summary validation

### 🔄 **Optional Filter Testing**
Tests each optional filter individually following ERPNext patterns:
```python
optional_filters = {"company": "_Test Company", "chapter": "Test Chapter"}
```

## Usage Examples

### Command Line Testing
```bash
# Test all reports with hybrid framework
bench --site dev.veganisme.net execute verenigingen.tests.utils.hybrid_report_tester.test_all_reports_hybrid

# Test single report
bench --site dev.veganisme.net execute verenigingen.tests.utils.hybrid_report_tester.test_single_report_hybrid --args "report_name=ANBI Donation Summary"

# Run via test runner wrapper
bench --site dev.veganisme.net execute verenigingen.tests.utils.test_runner_wrappers.run_hybrid_report_tests

# Comprehensive testing (traditional + hybrid)
bench --site dev.veganisme.net execute verenigingen.tests.utils.test_runner_wrappers.run_comprehensive_report_tests
```

### Python Testing
```python
# In test files
from verenigingen.tests.utils.hybrid_report_tester import VereningingenReportTestCase

class TestMyReports(VereningingenReportTestCase):
    def test_my_custom_report(self):
        result = self.execute_script_report_enhanced(
            report_name="My Custom Report",
            module="Verenigingen",
            filters={"custom_filter": "value"},
            regression_patterns=[
                {"pattern": "error_keyword", "description": "Known issue description"}
            ]
        )
        self.assertTrue(result.get("success"))
```

## Test Results Structure

The framework returns detailed test results:
```python
{
    "success": true,
    "tests_run": 7,
    "tests_passed": 7,
    "tests_failed": 0,
    "regression_detected": false,
    "structure_analysis": {
        "valid": true,
        "format_type": "list",
        "has_data": false
    },
    "execution_method": "frappe.desk.query_report.run"
}
```

## Benefits Over Standard Testing

1. **Automatic Regression Detection**: Prevents known issues from returning
2. **Structure Validation**: Ensures reports return expected data formats
3. **ERPNext Compatibility**: Uses established testing patterns
4. **Comprehensive Coverage**: Tests multiple filter combinations
5. **Easy Integration**: Works with existing test infrastructure

## Integration with Test Runner

The hybrid framework is fully integrated with the existing test runner:
- Available in comprehensive test suite
- Includes both traditional and hybrid testing approaches
- Provides detailed comparison results

## Current Test Coverage

**Reports Tested**: 7/7 reports in REPORT_FILTER_TEST_CASES
**Success Rate**: 100% (7/7 reports passing)
**Regression Detection**: Active for ANBI and Overdue Payments reports

## Adding New Reports

To add a new report to the test suite:

1. **Add to test cases**:
```python
REPORT_FILTER_TEST_CASES.append(
    ("New Report Name", {"filter_key": "filter_value"})
)
```

2. **Add regression patterns** (if needed):
```python
REGRESSION_PATTERNS["New Report Name"] = [
    {"pattern": "error_pattern", "description": "Known issue description"}
]
```

3. **Run tests**:
```bash
bench --site dev.veganisme.net execute verenigingen.tests.utils.hybrid_report_tester.test_all_reports_hybrid
```

The framework will automatically include the new report in all test runs.
