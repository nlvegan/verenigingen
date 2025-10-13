# Error Handling Standards for Verenigingen Services

## Overview

This document defines the error handling standards for service layer classes in the Verenigingen application. These standards ensure consistent, maintainable, and debuggable error handling across all services.

## Guiding Principles

1. **Fail Gracefully**: Services should handle errors gracefully and provide clear feedback
2. **Log Comprehensively**: All errors should be logged with sufficient context for debugging
3. **Validate Early**: Input validation should happen early to prevent cascading failures
4. **Return Meaningful Results**: Error results should contain actionable information
5. **Maintain Audit Trail**: Critical operations should be logged for compliance

## Error Handling Patterns

### 1. Result Objects Over Exceptions

Services should return result objects instead of raising exceptions for business logic failures.

**Good Example:**
```python
class DuplicateInvoiceDetectionResult:
    def __init__(self, can_generate: bool, reason: str, **metadata: Any) -> None:
        self.can_generate: bool = can_generate
        self.reason: str = reason
        self.metadata: Dict[str, Any] = metadata

def check_for_duplicates(self, start: date, end: date) -> DuplicateInvoiceDetectionResult:
    if not self.member:
        return DuplicateInvoiceDetectionResult(
            can_generate=True,
            reason="No member - skipping duplicate check"
        )
    # ... business logic
```

**Bad Example:**
```python
def check_for_duplicates(self, start: date, end: date) -> bool:
    if not self.member:
        raise ValueError("No member provided")
    # ... business logic
```

### 2. Comprehensive Validation with Clear Messages

Validate inputs early and provide clear, actionable error messages.

**Good Example:**
```python
def derive_coverage_from_invoice_data(posting_date, billing_frequency=None):
    # Input validation
    if not posting_date:
        raise ValueError("posting_date is required for coverage derivation")

    try:
        posting_date = getdate(posting_date)
    except Exception as e:
        raise ValueError(f"Invalid posting_date format: {posting_date} - {str(e)}")

    # Business logic validation
    valid_frequencies = ["Daily", "Weekly", "Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom"]
    if billing_frequency and billing_frequency not in valid_frequencies:
        frappe.log_error(
            f"Unknown billing frequency '{billing_frequency}' for coverage derivation",
            "Coverage Derivation Warning"
        )
        billing_frequency = None
```

### 3. Defensive Error Handling with Logging

Use try-except blocks defensively with comprehensive logging for unexpected errors.

**Good Example:**
```python
def _process_fallback_invoices(self, invoices: List[Dict[str, Any]], proposed_start: date, proposed_end: date) -> List[str]:
    overlapping_fallback_invoices = []

    for inv in invoices:
        try:
            # Derive coverage from invoice data
            inv_start, inv_end = derive_coverage_from_invoice_data(
                inv["posting_date"],
                inv["last_invoice_date"],
                inv["next_invoice_date"],
                inv["billing_frequency"] or self.billing_frequency,
            )

            # Validate derived coverage dates
            if not inv_start or not inv_end:
                frappe.log_error(
                    f"Failed to derive coverage dates for invoice {inv['name']}: "
                    f"posting_date={inv['posting_date']}, derived start={inv_start}, end={inv_end}",
                    "Coverage Derivation Error"
                )
                continue

            # Business logic...

        except Exception as e:
            # Clean up error message and log
            error_msg = re.sub("<[^<]+?>", "", str(e))
            frappe.log_error(
                f"Error processing fallback coverage for invoice {inv['name']}: {error_msg}",
                "Coverage Fallback Error"
            )
            continue

    return overlapping_fallback_invoices
```

### 4. Sanity Checks with Warning Logs

Implement sanity checks for derived data and log warnings for suspicious values.

**Good Example:**
```python
# Sanity check: coverage start shouldn't be too far in the future
if coverage_start > add_days(posting_date, 365):
    frappe.log_error(
        f"Suspicious coverage start derivation: last_invoice_date={last_invoice_date}, "
        f"posting_date={posting_date}, derived start={coverage_start}. Using posting date instead.",
        "Coverage Derivation Warning"
    )
    coverage_start = posting_date

# Sanity check: coverage period shouldn't exceed 2 years
if (coverage_end - coverage_start) > timedelta(days=730):
    frappe.log_error(
        f"Suspiciously long coverage period derived: {coverage_start} to {coverage_end} "
        f"({(coverage_end - coverage_start).days} days). This may indicate a data issue.",
        "Coverage Derivation Warning"
    )
```

## Error Logging Standards

### Log Levels

- **frappe.log_error()**: Use for recoverable errors that indicate data issues or unexpected conditions
- **frappe.logger().info()**: Use for informational messages about business logic decisions
- **frappe.logger().warning()**: Use for potential issues that don't prevent execution
- **Exceptions**: Raise only for critical failures that should halt execution

### Log Message Format

Error log messages should include:
1. **Context**: What operation was being performed
2. **Input Data**: Relevant input values that led to the error
3. **Error Details**: The specific error that occurred
4. **Impact**: What was skipped or what fallback was used

**Example:**
```python
frappe.log_error(
    f"Failed to derive coverage dates for invoice {inv['name']}: "
    f"posting_date={inv['posting_date']}, derived start={inv_start}, end={inv_end}",
    "Coverage Derivation Error"
)
```

### Error Title Categorization

Use consistent error titles for easier tracking:
- `"Coverage Derivation Error"`: Failed to calculate coverage periods
- `"Coverage Derivation Warning"`: Suspicious coverage calculation
- `"Coverage Gap Reset"`: Gap reset logic applied
- `"Coverage Fallback Error"`: Fallback coverage processing failed

## Constants and Business Rules

Extract magic numbers and business rules as named constants with clear documentation.

**Good Example:**
```python
# Business rule constants
GAP_RESET_THRESHOLD_DAYS = 30  # Billing gap threshold - prevents processing old invoices
MAX_OVERLAPPING_INVOICES = 10  # Maximum overlapping invoices to return from SQL query
FALLBACK_CUTOFF_DATE = "1900-01-01"  # Sentinel date for first-time invoice generation
```

## Type Hints for Error Handling

Use comprehensive type hints to document expected types and improve error detection.

**Good Example:**
```python
def _process_fallback_invoices(
    self,
    invoices: List[Dict[str, Any]],
    proposed_start: date,
    proposed_end: date
) -> List[str]:
    """
    Process invoices with missing coverage dates using derivation fallback.

    Args:
        invoices: List of invoice dictionaries with potentially missing coverage dates
        proposed_start: Proposed coverage period start date
        proposed_end: Proposed coverage period end date

    Returns:
        List of overlapping invoice names
    """
```

## Service-Specific Patterns

### DuplicateInvoiceDetector

The DuplicateInvoiceDetector implements a 4-phase pipeline with error handling at each phase:

1. **Phase 1: Validation** - Return early with skip result if preconditions not met
2. **Phase 2: Primary Detection** - Use efficient SQL queries with parameterized inputs
3. **Phase 3: Gap Reset** - Check for large gaps and skip fallback if applicable
4. **Phase 4: Fallback Detection** - Handle missing coverage dates with try-except blocks

Each phase returns `None` to continue to the next phase or a result object to short-circuit.

## Testing Error Handling

Always test error handling paths:

```python
@patch("frappe.log_error")
def test_fallback_handles_derivation_errors(self, mock_log_error):
    """Fallback detection gracefully handles derivation errors"""
    # Mock utility that raises error
    mock_derive_coverage.side_effect = Exception("Derivation failed")

    result = detector.check_for_duplicates(date(2025, 1, 1), date(2025, 1, 31))

    # Should continue gracefully after error
    self.assertTrue(result.can_generate)
    mock_log_error.assert_called_once()
```

## Checklist for New Services

- [ ] Use result objects instead of exceptions for business logic failures
- [ ] Validate all inputs early with clear error messages
- [ ] Use try-except blocks with comprehensive logging for unexpected errors
- [ ] Implement sanity checks for derived data
- [ ] Extract magic numbers to named constants
- [ ] Add comprehensive type hints
- [ ] Document error handling behavior
- [ ] Test error handling paths with unit tests
- [ ] Use consistent error titles for log categorization
- [ ] Clean up error messages (e.g., strip HTML tags)

## References

- `verenigingen/services/billing/duplicate_invoice_detector.py`: Reference implementation
- `verenigingen/utils/billing_period_calculator.py`: Pure function error handling
- `verenigingen/tests/unit/services/test_duplicate_invoice_detector.py`: Error handling tests
